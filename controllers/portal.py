import logging
from odoo import http, _, fields
from odoo.http import request
from odoo.exceptions import AccessError, MissingError, ValidationError
from odoo.addons.sale.controllers.portal import CustomerPortal

_logger = logging.getLogger(__name__)


class CotizadorCustomerPortal(CustomerPortal):

    def portal_order_page(self, order_id, **kw):
        """Override para inyectar los planes de pago al contexto del portal."""
        response = super().portal_order_page(order_id, **kw)

        # Solo inyectar si es una respuesta de render (no un PDF/redirect)
        if hasattr(response, 'qcontext'):
            plan_templates = request.env['cotizador.plan.pago.template'].sudo().search([
                ('active', '=', True)
            ])
            response.qcontext['plan_templates'] = plan_templates

        return response

    @http.route(
        '/my/orders/<int:order_id>/select_plan',
        type='http', auth='public', methods=['POST'], website=True
    )
    def portal_select_plan(self, order_id, access_token=None, plan_line_id=None, **kwargs):
        """Ruta POST para que el cliente seleccione un plan de pago desde el portal."""
        try:
            order_sudo = self._document_check_access('sale.order', order_id, access_token=access_token)
        except (AccessError, MissingError):
            return request.redirect('/my')

        if order_sudo.state not in ('draft', 'sent'):
            return request.redirect(order_sudo.get_portal_url())

        if not plan_line_id:
            return request.redirect(order_sudo.get_portal_url())

        try:
            plan_line_id = int(plan_line_id)
        except (ValueError, TypeError):
            return request.redirect(order_sudo.get_portal_url())

        template_line = request.env['cotizador.plan.pago.template.line'].sudo().browse(plan_line_id)
        if not template_line.exists():
            return request.redirect(order_sudo.get_portal_url())

        try:
            template_line.with_context(
                default_sale_order_id=order_sudo.id
            ).action_select_line()

            # Postear un mensaje en el chatter informando la selección del cliente
            order_sudo.message_post(
                body=_(
                    "El cliente seleccionó el plan de pago <strong>%s</strong> desde el portal.",
                    template_line.name
                ),
                message_type='comment',
                subtype_xmlid='mail.mt_note',
            )
        except ValidationError as e:
            _logger.warning("Error al seleccionar plan de pago desde portal: %s", e)

        return request.redirect(order_sudo.get_portal_url(query_string='&message=plan_selected'))
