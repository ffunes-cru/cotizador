import logging
import time
from datetime import timedelta

from markupsafe import Markup, escape

from odoo import _, fields, http
from odoo.exceptions import UserError, ValidationError
from odoo.http import request
from odoo.tools import consteq
from odoo.tools.misc import hmac as hmac_sign

from odoo.addons.website_sale.controllers.main import WebsiteSale

_logger = logging.getLogger(__name__)

# Acción de captcha (reCAPTCHA v3 / Cloudflare Turnstile) del formulario de solicitud
CAPTCHA_ACTION = 'cotizador_quote'
RATE_LIMIT_WINDOW = timedelta(hours=1)
# Validez del token del formulario (se pide al abrir la página)
FORM_TOKEN_SCOPE = 'cotizador.quote_form'
FORM_TOKEN_MAX_AGE = 2 * 3600


class CotizadorWebsiteController(http.Controller):

    # -------------------------------------------------------------------------
    #  Protecciones del formulario
    # -------------------------------------------------------------------------

    @http.route('/cotizador/form_token', type='jsonrpc', auth='public', website=True)
    def form_token(self):
        """Token firmado con la hora de apertura del formulario (lo pide el JS de la página)."""
        timestamp = str(int(time.time()))
        return f"{timestamp}.{hmac_sign(request.env(su=True), FORM_TOKEN_SCOPE, timestamp)}"

    def _check_form_token(self, token):
        """
        True si el token es auténtico y el formulario se completó en un tiempo humano: ni antes
        del mínimo configurado (bots que envían al instante) ni con un token vencido o reusado
        de otra página vieja.
        """
        timestamp, _sep, signature = (token or '').partition('.')
        if not timestamp.isdigit() or not consteq(
            signature, hmac_sign(request.env(su=True), FORM_TOKEN_SCOPE, timestamp),
        ):
            return False
        min_seconds = int(request.env['ir.config_parameter'].sudo().get_param('cotizador.quote_min_seconds', 3))
        elapsed = time.time() - int(timestamp)
        return min_seconds <= elapsed <= FORM_TOKEN_MAX_AGE

    @staticmethod
    def _contact_domain(email, phone):
        """Leads con el mismo email o el mismo teléfono (al menos uno viene informado)."""
        if email and phone:
            return ['|', ('email_from', '=ilike', email), ('phone', '=', phone)]
        return [('email_from', '=ilike', email)] if email else [('phone', '=', phone)]

    def _is_rate_limited(self, ip_addr, email, phone):
        """Limita solicitudes por IP y por contacto en la última hora (0 = sin límite)."""
        params = request.env['ir.config_parameter'].sudo()
        max_ip = int(params.get_param('cotizador.quote_rate_limit_ip', 5) or 0)
        max_contact = int(params.get_param('cotizador.quote_rate_limit_contact', 3) or 0)
        Lead = request.env['crm.lead'].sudo().with_context(active_test=False)
        recent = [('cotizador_request_ip', '!=', False),
                  ('create_date', '>=', fields.Datetime.now() - RATE_LIMIT_WINDOW)]
        if max_ip and Lead.search_count(recent + [('cotizador_request_ip', '=', ip_addr)], limit=max_ip) >= max_ip:
            return True
        return bool(max_contact) and Lead.search_count(
            recent + self._contact_domain(email, phone), limit=max_contact,
        ) >= max_contact

    def _quote_error_redirect(self, template, code):
        """Vuelve a la ficha del producto mostrando el motivo del rechazo."""
        return request.redirect(f"{template.website_url if template else '/shop'}?quote_error={code}")

    # -------------------------------------------------------------------------
    #  Solicitud de cotización
    # -------------------------------------------------------------------------

    @http.route('/cotizador/solicitud_recibida', type='http', auth='public', website=True, sitemap=False)
    def solicitud_recibida(self, **kw):
        """Confirmación para visitantes anónimos (sin enlaces a documentos)."""
        return request.render('cotizador.quote_request_received')

    @http.route(
        '/cotizador/solicitar_cotizacion',
        type='http', auth='public', methods=['POST'], website=True, csrf=True
    )
    def solicitar_cotizacion(self, **post):
        """
        Solicitud de cotización desde la tienda.
          - Visitante anónimo: SOLO se crea un lead del CRM (sin contacto ni cotización). El
            vendedor lo convierte con el asistente estándar (vincular a un cliente existente o
            crear uno) y arma la cotización con "Crear Cotización".
          - Usuario logueado: oportunidad + cotización a su nombre, y se lo lleva al portal.
        """
        if post.get('website_quick_check'):  # honeypot
            _logger.warning("[Cotizador Security] Envío de bot detectado (honeypot).")
            return request.redirect('/shop')

        def to_int(key):
            try:
                return int(post.get(key) or 0)
            except ValueError:
                return 0

        contact_name = (post.get('contact_name') or '').strip()[:100]
        company_name = (post.get('company_name') or '').strip()[:100]
        phone = (post.get('phone') or '').strip()[:40]
        email = (post.get('email') or '').strip()[:100]
        city = (post.get('city') or '').strip()[:100]
        notes = (post.get('notes') or '').strip()[:1500]

        template = request.env['product.template'].sudo().browse(to_int('product_template_id')).exists()
        if not template or not template.sale_ok:
            return request.redirect('/shop')

        try:
            request.env['ir.http']._verify_request_recaptcha_token(CAPTCHA_ACTION)
        except (UserError, ValidationError) as e:
            _logger.warning("[Cotizador Security] Captcha rechazado: %s", e)
            return self._quote_error_redirect(template, 'captcha')
        if not self._check_form_token(post.get('cotizador_form_token')):
            _logger.warning("[Cotizador Security] Token de formulario inválido o enviado demasiado rápido.")
            return self._quote_error_redirect(template, 'captcha')

        if not contact_name or not (email or phone):
            return self._quote_error_redirect(template, 'invalid')

        # Máquinas: la configuración elegida es obligatoria y debe ser de esa máquina
        config = request.env['sembradora.config.rel']
        if template.is_maquina:
            config = config.sudo().browse(to_int('config_id')).exists()
            if config.modelo_id != template:
                return self._quote_error_redirect(template, 'invalid')

        is_public = request.env.user._is_public()
        ip_addr = request.httprequest.remote_addr
        if is_public and self._is_rate_limited(ip_addr, email, phone):
            _logger.warning("[Cotizador Security] Límite de solicitudes web alcanzado: ip=%s", ip_addr)
            return self._quote_error_redirect(template, 'rate_limit')

        lead = self._create_lead(template, config, contact_name, company_name, phone, email, city,
                                 notes, ip_addr, partner=None if is_public else request.env.user.partner_id)
        if is_public:
            return request.redirect('/cotizador/solicitud_recibida')

        order = self._create_order(lead, template, config, to_int('product_id'))
        return request.redirect(order.get_portal_url(query_string='&quote_requested=1'))

    def _create_lead(self, template, config, contact_name, company_name, phone, email, city, notes,
                     ip_addr, partner):
        """Lead (anónimo) u oportunidad (cliente logueado) con el detalle de lo solicitado."""
        Lead = request.env['crm.lead'].sudo()

        def text_to_html(text):
            return Markup('<br/>').join(escape(text).split('\n'))

        detail = config._get_variant_description() if config else template.name
        description = Markup(
            "<p><strong>Solicitud recibida desde la tienda online.</strong></p>"
            "<p><strong>Configuración:</strong><br/>%s</p>"
        ) % text_to_html(detail)
        standard = config._get_default_accessory_lines() if config else ()
        if standard:
            description += Markup("<p><strong>Equipamiento estándar:</strong><br/>%s</p>") % text_to_html(
                '\n'.join(f"• {line.product_id.display_name}" for line in standard))
        if notes:
            description += Markup("<p><strong>Notas del cliente:</strong><br/>%s</p>") % text_to_html(notes)

        use_leads = request.env['res.groups'].sudo()._is_feature_enabled('crm.group_use_lead')
        return Lead.create({
            'name': f"Solicitud Web: {template.name} - {company_name or contact_name}",
            'type': 'opportunity' if partner or not use_leads else 'lead',
            'partner_id': partner.id if partner else False,
            'contact_name': contact_name,
            'partner_name': company_name,
            'phone': phone,
            'email_from': email,
            'city': city,
            'equipo_cotizado_id': template.id if template.is_maquina else False,
            'cotizador_config_id': config.id,
            'description': description,
            'cotizador_request_ip': ip_addr,
        })

    def _create_order(self, lead, template, config, variant_id):
        """Cotización del cliente logueado, enviada y vinculada a la oportunidad."""
        company = request.website.company_id
        order = request.env['sale.order'].sudo().with_context(skip_crm_sync=True).create({
            'partner_id': lead.partner_id.id,
            'origin': _('Tienda Online / Sitio Web'),
            'opportunity_id': lead.id,
            'company_id': company.id,
            'equipo_cotizado_id': template.id if template.is_maquina else False,
            'pricelist_id': (company.cotizador_pricelist_id or request.pricelist).id,
            'state': 'sent',  # visible en el portal
            'portal_confirmation_allowed': False,
        })
        if config:
            order._cotizador_add_configuration(config, config._get_default_accessory_lines())
        else:
            variant = request.env['product.product'].sudo().browse(variant_id).exists()
            if variant.product_tmpl_id != template:
                variant = template.product_variant_id
            # Producto común: precio y descripción los calcula Odoo con la lista de la orden
            request.env['sale.order.line'].sudo().create({'order_id': order.id, 'product_id': variant.id})
        lead._sync_expected_revenue_from_orders()
        order.message_post(
            body=Markup(_("Solicitud de cotización generada desde la Tienda Online. Oportunidad: <strong>%s</strong>"))
            % lead.name,
            message_type='notification',
            subtype_xmlid='mail.mt_note',
        )
        return order


class CotizadorWebsiteSale(WebsiteSale):
    """En modo 'Solo cotización' la tienda no permite checkout ni pago online."""

    def _cotizador_quote_only(self):
        return request.env['ir.config_parameter'].sudo().get_param(
            'cotizador.ecommerce_mode', default='quote_only'
        ) == 'quote_only'

    @http.route()
    def shop_checkout(self, try_skip_step=None, **query_params):
        if self._cotizador_quote_only():
            return request.redirect('/shop')
        return super().shop_checkout(try_skip_step=try_skip_step, **query_params)

    @http.route()
    def shop_payment(self, **post):
        if self._cotizador_quote_only():
            return request.redirect('/shop')
        return super().shop_payment(**post)
