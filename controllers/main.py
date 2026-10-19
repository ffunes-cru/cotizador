"""@file
Rutas del sitio web: solicitud de cotización desde la tienda y bloqueo del pago online.

Solicitud de cotización (`POST /cotizador/solicitar_cotizacion`), validaciones en orden:
1. campo trampa (honeypot) vacío;
2. captcha (reCAPTCHA v3 o Cloudflare Turnstile, si está configurado en el sitio web);
3. token del formulario: firmado, ni muy rápido ni vencido (ver form_token());
4. nombre y email o teléfono;
5. para máquinas, una configuración de esa máquina;
6. para visitantes anónimos, límites por hora por IP y por email/teléfono.

Después:
- **visitante anónimo**: solo un lead del CRM (sin contacto ni cotización) y la página de
  confirmación `/cotizador/solicitud_recibida`;
- **usuario logueado**: oportunidad y cotización enviada a su nombre, y se lo lleva al portal.
"""
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
from odoo.addons.website_sale.controllers.payment import PaymentPortal

_logger = logging.getLogger(__name__)

## Acción de captcha (reCAPTCHA v3 / Cloudflare Turnstile) del formulario; la misma que `data-captcha` en la vista.
CAPTCHA_ACTION = 'cotizador_quote'
## Ventana de los límites de solicitudes anónimas.
RATE_LIMIT_WINDOW = timedelta(hours=1)
## Ámbito de la firma HMAC del token del formulario.
FORM_TOKEN_SCOPE = 'cotizador.quote_form'
## Validez máxima del token del formulario, en segundos (se pide al abrir la página).
FORM_TOKEN_MAX_AGE = 2 * 3600
## Error de las rutas de pago en modo "Solo cotización".
QUOTE_ONLY_MESSAGE = "La tienda solo recibe solicitudes de cotización: no admite pagos online."


def _to_int(value):
    """Convierte un valor de formulario a entero.

    @param value Texto del formulario (o None).
    @return El entero, o 0 si está vacío o no es un número.
    """
    try:
        return int(value or 0)
    except ValueError:
        return 0


def _text_to_html(text):
    """Texto ingresado por el usuario → HTML seguro, con saltos de línea como `<br/>`.

    @param text Texto plano (se escapa todo).
    @return Markup.
    """
    return Markup('<br/>').join(escape(text).split('\n'))


def quote_only_mode():
    """Indica si la tienda está en modo "Solo cotización" (parámetro `cotizador.ecommerce_mode`).

    @return True en modo "Solo cotización" (el valor por defecto).
    """
    return request.env['ir.config_parameter'].sudo().get_param(
        'cotizador.ecommerce_mode', default='quote_only'
    ) == 'quote_only'


class CotizadorWebsiteController(http.Controller):
    """Solicitud de cotización desde la ficha de producto de la tienda."""

    # -------------------------------------------------------------------------
    #  Protecciones del formulario
    # -------------------------------------------------------------------------

    @http.route('/cotizador/form_token', type='jsonrpc', auth='public', website=True)
    def form_token(self):
        """Token del formulario: la hora de apertura de la página, firmada con HMAC.

        Lo pide static/src/js/cotizador_quote_form.js al cargar la página. Sin JavaScript no
        hay token, así que los bots más simples quedan afuera.

        @return Texto "<timestamp>.<firma>".
        """
        timestamp = str(int(time.time()))
        return f"{timestamp}.{hmac_sign(request.env(su=True), FORM_TOKEN_SCOPE, timestamp)}"

    def _check_form_token(self, token):
        """Valida el token del formulario.

        @param token Token recibido en el campo oculto `cotizador_form_token`.
        @return True si la firma es auténtica y pasaron entre `cotizador.quote_min_seconds`
                (envíos instantáneos de bots) y FORM_TOKEN_MAX_AGE segundos (token vencido).
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
        """Dominio de leads con el mismo email o el mismo teléfono.

        @param email Email ingresado (puede estar vacío).
        @param phone Teléfono ingresado (puede estar vacío; al menos uno de los dos viene).
        @return Dominio de crm.lead.
        """
        if email and phone:
            return ['|', ('email_from', '=ilike', email), ('phone', '=', phone)]
        return [('email_from', '=ilike', email)] if email else [('phone', '=', phone)]

    def _is_rate_limited(self, ip_addr, email, phone):
        """Límites de solicitudes anónimas en la última hora (0 = sin límite).

        Cuenta leads con `cotizador_request_ip` (los creados por este formulario), incluso
        archivados.

        @param ip_addr IP del visitante.
        @param email Email ingresado.
        @param phone Teléfono ingresado.
        @return True si se alcanzó `cotizador.quote_rate_limit_ip` para la IP o
                `cotizador.quote_rate_limit_contact` para el email/teléfono.
        """
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
        """Vuelve a la ficha del producto con el motivo del rechazo.

        @param template Producto de la solicitud (o vacío: vuelve a /shop).
        @param code Motivo: `captcha`, `invalid` o `rate_limit` (los muestra la plantilla
               `cotizador.quote_error`).
        @return Redirección HTTP.
        """
        return request.redirect(f"{template.website_url if template else '/shop'}?quote_error={code}")

    # -------------------------------------------------------------------------
    #  Solicitud de cotización
    # -------------------------------------------------------------------------

    @http.route('/cotizador/solicitud_recibida', type='http', auth='public', website=True, sitemap=False)
    def solicitud_recibida(self, **kw):
        """Página de confirmación para visitantes anónimos (sin enlaces a documentos).

        @param kw Parámetros de la URL (no se usan).
        @return Página `cotizador.quote_request_received`.
        """
        return request.render('cotizador.quote_request_received')

    @http.route(
        '/cotizador/solicitar_cotizacion',
        type='http', auth='public', methods=['POST'], website=True, csrf=True
    )
    def solicitar_cotizacion(self, **post):
        """Recibe el formulario *Solicitar Cotización* (validaciones: ver el encabezado del archivo).

        @param post Campos del formulario: `product_template_id`, `product_id`, `config_id`,
               `contact_name`, `company_name`, `phone`, `email`, `city`, `notes`,
               `cotizador_form_token`, el campo trampa `website_quick_check` y el token del captcha.
        @return Redirección: a la confirmación (anónimo), a la cotización en el portal
                (logueado) o a la ficha del producto con el motivo del rechazo.
        """
        if post.get('website_quick_check'):  # honeypot
            _logger.warning("[Cotizador Security] Envío de bot detectado (honeypot).")
            return request.redirect('/shop')

        contact_name = (post.get('contact_name') or '').strip()[:100]
        company_name = (post.get('company_name') or '').strip()[:100]
        phone = (post.get('phone') or '').strip()[:40]
        email = (post.get('email') or '').strip()[:100]
        city = (post.get('city') or '').strip()[:100]
        notes = (post.get('notes') or '').strip()[:1500]

        template = request.env['product.template'].sudo().browse(_to_int(post.get('product_template_id'))).exists()
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
            config = config.sudo().browse(_to_int(post.get('config_id'))).exists()
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

        order = self._create_order(lead, template, config, _to_int(post.get('product_id')))
        return request.redirect(order.get_portal_url(query_string='&quote_requested=1'))

    def _create_lead(self, template, config, contact_name, company_name, phone, email, city, notes,
                     ip_addr, partner):
        """Crea el lead (anónimo) o la oportunidad (cliente logueado) de la solicitud.

        La descripción lista la configuración, el equipamiento estándar y las notas, con todo el
        texto del visitante escapado.

        @param template Producto solicitado.
        @param config Configuración elegida (vacía si no es máquina).
        @param contact_name Nombre del contacto.
        @param company_name Empresa (opcional).
        @param phone Teléfono (opcional si hay email).
        @param email Email (opcional si hay teléfono).
        @param city Localidad (opcional).
        @param notes Notas del visitante (opcional).
        @param ip_addr IP del visitante (para los límites y el control de abuso).
        @param partner Contacto del usuario logueado, o None para visitantes anónimos.
        @return crm.lead creado (con sudo). Es `lead` si el anónimo usa leads en el CRM; si no, `opportunity`.
        """
        Lead = request.env['crm.lead'].sudo()

        detail = config._get_variant_description() if config else template.name
        description = Markup(
            "<p><strong>Solicitud recibida desde la tienda online.</strong></p>"
            "<p><strong>Configuración:</strong><br/>%s</p>"
        ) % _text_to_html(detail)
        standard = config._get_default_accessory_lines() if config else ()
        if standard:
            description += Markup("<p><strong>Equipamiento estándar:</strong><br/>%s</p>") % _text_to_html(
                '\n'.join(f"• {line.product_id.display_name}" for line in standard))
        if notes:
            description += Markup("<p><strong>Notas del cliente:</strong><br/>%s</p>") % _text_to_html(notes)

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
        """Crea la cotización del cliente logueado, enviada y vinculada a la oportunidad.

        Máquina: configuración con su equipamiento estándar. Otro producto: la variante elegida
        con el precio nativo de Odoo.

        @param lead Oportunidad creada por _create_lead().
        @param template Producto solicitado.
        @param config Configuración elegida (vacía si no es máquina).
        @param variant_id Id de la variante elegida en la ficha (solo productos que no son máquina).
        @return sale.order creada (con sudo), en estado `sent` para que el cliente la vea.
        """
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
    """En modo "Solo cotización" la tienda no permite checkout ni pago online.

    Se cierran todas las entradas al pago de un carrito: las páginas de checkout y de pago
    (redirigen a /shop), el *express checkout* (Google Pay, Apple Pay…) y la creación de la
    transacción (ver CotizadorPaymentPortal). El pago de cotizaciones desde el portal lo
    decide sale.order._has_to_be_paid() según el modo de aceptación.
    """

    @http.route()
    def shop_checkout(self, try_skip_step=None, **query_params):
        """Página de checkout: redirige a la tienda en modo "Solo cotización".

        @param try_skip_step Estándar de Odoo.
        @param query_params Estándar de Odoo.
        @return Redirección a /shop, o la página estándar.
        """
        if quote_only_mode():
            return request.redirect('/shop')
        return super().shop_checkout(try_skip_step=try_skip_step, **query_params)

    @http.route()
    def shop_payment(self, **post):
        """Página de pago: redirige a la tienda en modo "Solo cotización".

        @param post Estándar de Odoo.
        @return Redirección a /shop, o la página estándar.
        """
        if quote_only_mode():
            return request.redirect('/shop')
        return super().shop_payment(**post)

    @http.route()
    def process_express_checkout(self, billing_address, shipping_address=None, shipping_option=None, **kwargs):
        """Express checkout (JSON-RPC), bloqueado en modo "Solo cotización".

        @param billing_address Estándar de Odoo.
        @param shipping_address Estándar de Odoo.
        @param shipping_option Estándar de Odoo.
        @param kwargs Estándar de Odoo.
        @return Resultado estándar.
        @throws UserError En modo "Solo cotización".
        """
        if quote_only_mode():
            raise UserError(QUOTE_ONLY_MESSAGE)
        return super().process_express_checkout(
            billing_address, shipping_address=shipping_address, shipping_option=shipping_option, **kwargs)


class CotizadorPaymentPortal(PaymentPortal):
    """Creación de la transacción de pago de un carrito de la tienda."""

    @http.route()
    def shop_payment_transaction(self, order_id, access_token, **kwargs):
        """Crea la transacción de pago del carrito (JSON-RPC), bloqueada en modo "Solo cotización".

        @param order_id Estándar de Odoo.
        @param access_token Estándar de Odoo.
        @param kwargs Estándar de Odoo.
        @return Resultado estándar.
        @throws UserError En modo "Solo cotización".
        """
        if quote_only_mode():
            raise UserError(QUOTE_ONLY_MESSAGE)
        return super().shop_payment_transaction(order_id, access_token, **kwargs)
