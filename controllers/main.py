# -*- coding: utf-8 -*-
import logging
from markupsafe import escape
from odoo import http, _, fields
from odoo.http import request

_logger = logging.getLogger(__name__)


class CotizadorWebsiteController(http.Controller):

    @http.route(
        '/cotizador/solicitar_cotizacion',
        type='http', auth='public', methods=['POST'], website=True, csrf=True
    )
    def solicitar_cotizacion(self, **post):
        """Procesa la solicitud de cotización desde la tienda online de forma segura."""
        # 0. Anti-bot honeypot check (campo oculto para bots)
        if post.get('website_quick_check'):
            _logger.warning("[Cotizador Security] Bot submission detected via honeypot field.")
            return request.redirect('/shop')

        # Conversión segura de enteros para prevenir errores 500 por valores inválidos
        try:
            template_id = int(post.get('product_template_id', 0))
        except (ValueError, TypeError):
            template_id = 0

        try:
            variant_id = int(post.get('product_id', 0))
        except (ValueError, TypeError):
            variant_id = 0

        try:
            config_id = int(post.get('config_id', 0))
        except (ValueError, TypeError):
            config_id = 0
        
        # Sanitizar y limitar longitud de entradas para prevenir abusos de memoria / DoS
        contact_name = (post.get('contact_name') or '').strip()[:100]
        company_name = (post.get('company_name') or '').strip()[:100]
        phone = (post.get('phone') or '').strip()[:40]
        email = (post.get('email') or '').strip()[:100]
        city = (post.get('city') or '').strip()[:100]
        notes = (post.get('notes') or '').strip()[:1500]

        # Validaciones de integridad básicas
        if not template_id or not contact_name or not (email or phone):
            return request.redirect('/shop')

        template = request.env['product.template'].sudo().browse(template_id)
        if not template.exists() or not template.sale_ok:
            return request.redirect('/shop')

        # 1. Identificar o crear cliente (res.partner) de forma segura
        partner = False
        if not request.env.user._is_public():
            partner = request.env.user.partner_id
        else:
            # Buscar coincidencia solo entre contactos externos (NUNCA asignar a usuarios internos del sistema)
            if email:
                partner = request.env['res.partner'].sudo().search([
                    ('email', '=ilike', email),
                    ('user_ids', '=', False),
                ], limit=1)
            if not partner and phone:
                partner = request.env['res.partner'].sudo().search([
                    ('phone', '=', phone),
                    ('user_ids', '=', False),
                ], limit=1)

            # Si no existe, crear nuevo contacto (no sobreescribir datos de partners existentes de forma anónima)
            if not partner:
                partner = request.env['res.partner'].sudo().create({
                    'name': company_name or contact_name,
                    'is_company': bool(company_name),
                    'email': email,
                    'phone': phone,
                    'city': city,
                    'customer_rank': 1,
                })

        # 2. Identificar la variante y configuración de sembradora.config.rel
        config_id = int(post.get('config_id', 0))
        variant = request.env['product.product'].sudo().browse(variant_id) if variant_id else False
        configs = request.env['sembradora.config.rel'].sudo().search([('modelo_id', '=', template.id)])

        matching_config = False
        valores_seleccionados = request.env['product.attribute.value'].sudo()

        if config_id:
            cfg = request.env['sembradora.config.rel'].sudo().browse(config_id)
            if cfg.exists() and cfg.modelo_id.id == template.id:
                matching_config = cfg
                valores_seleccionados = cfg.value_ids

        if not matching_config and variant and variant.exists():
            val_ids = set(variant.product_template_attribute_value_ids.mapped('product_attribute_value_id.id'))
            for c in configs:
                if set(c.value_ids.ids) == val_ids:
                    matching_config = c
                    valores_seleccionados = c.value_ids
                    break
        elif not matching_config and configs:
            matching_config = configs[0]
            valores_seleccionados = matching_config.value_ids

        # Si no había variante existente, buscar o crear la variante exacta
        if (not variant or not variant.exists()) and matching_config:
            domain = [('product_tmpl_id', '=', template.id)]
            for val in valores_seleccionados:
                domain.append(('product_template_attribute_value_ids.product_attribute_value_id', '=', val.id))
            variant = request.env['product.product'].sudo().search(domain, limit=1)
            if not variant:
                template_attribute_values = request.env['product.template.attribute.value'].sudo().search([
                    ('product_tmpl_id', '=', template.id),
                    ('product_attribute_value_id', 'in', valores_seleccionados.ids)
                ])
                variant = request.env['product.product'].sudo().create({
                    'product_tmpl_id': template.id,
                    'product_template_attribute_value_ids': [(6, 0, template_attribute_values.ids)],
                    'list_price': matching_config.price,
                })

        base_price = matching_config.price if matching_config else (variant.list_price if variant else template.list_price)

        # Construir descripción de la máquina
        detalle_variante = f"{template.name}"
        if valores_seleccionados:
            lineas_attr = [f"• {v.attribute_id.name}: {v.name}" for v in valores_seleccionados]
            detalle_variante += "\n" + "\n".join(lineas_attr)

        tax_105 = request.env['account.tax'].sudo().search([
            ('type_tax_use', '=', 'sale'),
            ('amount', '=', 10.5)
        ], limit=1)
        tax_commands = [(6, 0, [tax_105.id])] if tax_105 else False

        # 3. Crear Oportunidad en CRM primero (evita duplicación automática en _sync_with_crm)
        # El campo description en crm.lead es fields.Html, sanitizamos contenido para prevenir Stored XSS
        safe_detalle_html = escape(detalle_variante).replace('\n', '<br/>')
        lead_description_html = (
            f"<p><strong>Solicitud recibida desde la tienda online.</strong></p>"
            f"<p><strong>Modelo:</strong> {escape(template.name)}<br/>"
            f"<strong>Configuración:</strong><br/>{safe_detalle_html}</p>"
        )
        if notes:
            safe_notes_html = escape(notes).replace('\n', '<br/>')
            lead_description_html += f"<p><strong>Notas del cliente:</strong><br/>{safe_notes_html}</p>"

        lead_vals = {
            'name': f"Solicitud Web: {template.name} - {partner.name}",
            'partner_id': partner.id,
            'contact_name': contact_name,
            'phone': phone,
            'email_from': email,
            'city': city,
            'equipo_cotizado_id': template.id,
            'expected_revenue': base_price,
            'description': lead_description_html,
            'type': 'opportunity',
        }
        lead = request.env['crm.lead'].sudo().create(lead_vals)

        # 4. Crear Cotización (sale.order) vinculada directamente a la Oportunidad creada en USD
        pricelist_usd = request.env['product.pricelist'].sudo().search([
            ('currency_id.name', '=', 'USD')
        ], limit=1)

        mode_conf = request.env['ir.config_parameter'].sudo().get_param(
            'cotizador.portal_confirmation_mode', default='salesman_enables'
        )

        order_vals = {
            'partner_id': partner.id,
            'origin': _('Tienda Online / Sitio Web'),
            'equipo_cotizado_id': template.id,
            'opportunity_id': lead.id,
            'state': 'sent',  # Marca como enviada para que aparezca en el portal y en el contador de cotizaciones
            'portal_confirmation_mode': mode_conf,
            'portal_confirmation_allowed': False,
        }
        if pricelist_usd:
            order_vals['pricelist_id'] = pricelist_usd.id

        order = request.env['sale.order'].sudo().with_context(skip_crm_sync=True).create(order_vals)

        # Sección y línea de producto
        request.env['sale.order.line'].sudo().create({
            'order_id': order.id,
            'name': _('Variante de Configuracion'),
            'display_type': 'line_section',
        })

        if variant and variant.exists():
            request.env['sale.order.line'].sudo().create({
                'order_id': order.id,
                'product_id': variant.id,
                'name': detalle_variante,
                'product_uom_qty': 1.0,
                'price_unit': base_price,
                'tax_ids': tax_commands,
            })

        order._compute_totales_cotizador()
        if order.amount_saldo_cancelar:
            lead.sudo().write({'expected_revenue': order.amount_saldo_cancelar})

        # Sanitizar strings de usuario contra XSS antes de publicar en el chatter
        order.sudo().message_post(
            body=_(
                "Solicitud de cotización generada desde la Tienda Online por <strong>%s</strong>.<br/>"
                "Teléfono: %s | Email: %s<br/>"
                "Oportunidad CRM vinculada: <strong>%s</strong>"
            ) % (
                escape(partner.name or contact_name),
                escape(phone or '-'),
                escape(email or '-'),
                escape(lead.name),
            ),
            message_type='notification',
            subtype_xmlid='mail.mt_note',
        )

        # Redirigir al cliente de forma segura con su token criptográfico a la vista portal
        portal_url = order.get_portal_url(query_string='&quote_requested=1')
        return request.redirect(portal_url)


from odoo.addons.website_sale.controllers.main import WebsiteSale
from odoo.addons.sale.controllers.portal import CustomerPortal


class CotizadorCustomerPortal(CustomerPortal):

    def _prepare_quotations_domain(self, partner):
        """Permite al cliente visualizar en /my/quotes tanto presupuestos enviados como en borrador."""
        return [
            ('partner_id', 'child_of', [partner.commercial_partner_id.id]),
            ('state', 'in', ['sent', 'draft']),
        ]

    @http.route(['/my/quotes', '/my/quotes/page/<int:page>'], type='http', auth="user", website=True)
    def portal_my_quotes(self, **kwargs):
        return super().portal_my_quotes(**kwargs)


CustomerPortal._prepare_quotations_domain = CotizadorCustomerPortal._prepare_quotations_domain


class CotizadorWebsiteSale(WebsiteSale):

    @http.route()
    def payment(self, **post):
        """Bypassea o bloquea la pantalla de pagos si la tienda está en modo Solicitud de Cotización."""
        mode = request.env['ir.config_parameter'].sudo().get_param(
            'cotizador.ecommerce_mode', default='quote_only'
        )
        if mode == 'quote_only':
            return request.redirect('/shop')
        return super().payment(**post)

    @http.route()
    def checkout(self, **post):
        """Bypassea o bloquea el checkout si la tienda está en modo Solicitud de Cotización."""
        mode = request.env['ir.config_parameter'].sudo().get_param(
            'cotizador.ecommerce_mode', default='quote_only'
        )
        if mode == 'quote_only':
            return request.redirect('/shop')
        return super().checkout(**post)
