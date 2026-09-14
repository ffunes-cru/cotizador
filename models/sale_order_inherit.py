# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
import logging
from .bcra_service import consultar_bcra_completo, SITUACION_LABELS

_logger = logging.getLogger(__name__)


class SaleOrderInherit(models.Model):
    _inherit = 'sale.order'

    @api.onchange('partner_id')
    def _onchange_partner_id_bcra(self):
        """Al seleccionar cliente, consulta en tiempo real al BCRA y emite alerta si posee deudas."""
        if self.partner_id and self.partner_id.vat:
            data = consultar_bcra_completo(self.partner_id.vat)
            if data and data.get('success') and data.get('tiene_deuda') and data.get('monto_total_deuda', 0.0) > 0:
                monto_total = data.get('monto_total_deuda', 0.0)
                peor_sit = data.get('peor_situacion') or '1'
                monto_fmt = f"{monto_total:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                peor_desc = SITUACION_LABELS.get(int(peor_sit), f"Situación {peor_sit}")
                return {
                    'warning': {
                        'title': _("⚠️ Alerta Crediticia - Central de Deudores BCRA"),
                        'message': _(
                            "El cliente '%s' (CUIT: %s) registra deudas informadas en el BCRA por un monto total de $ %s (%s).\n\n"
                            "Puede consultar el detalle completo haciendo clic en el botón 'Situación BCRA'."
                        ) % (self.partner_id.name, self.partner_id.vat or '', monto_fmt, peor_desc)
                    }
                }

    def action_ver_bcra_wizard(self):
        """Abre un wizard modal con el informe crediticio en tiempo real del BCRA."""
        self.ensure_one()
        if not self.partner_id:
            raise UserError(_("Por favor seleccione primero un cliente."))
        if not self.partner_id.vat:
            raise UserError(_("El cliente seleccionado '%s' no tiene CUIT configurado.") % self.partner_id.name)

        data = consultar_bcra_completo(self.partner_id.vat)
        if not data or not data.get('success'):
            raise UserError(data.get('error', _('No se pudo obtener información desde la API del BCRA.')))

        # Comandos de creación de líneas de deuda
        deuda_commands = []
        for d in data.get('deudas', []):
            deuda_commands.append((0, 0, {
                'periodo': d.get('periodo'),
                'entidad': d.get('entidad'),
                'situacion': d.get('situacion'),
                'monto': d.get('monto'),
                'dias_atraso': d.get('dias_atraso'),
                'observaciones': d.get('observaciones'),
            }))

        # Comandos de creación de líneas de cheques rechazados
        cheque_commands = []
        for ch in data.get('cheques_rechazados', []):
            cheque_commands.append((0, 0, {
                'nro_cheque': ch.get('nro_cheque'),
                'fecha_rechazo': ch.get('fecha_rechazo'),
                'monto': ch.get('monto'),
                'causal': ch.get('causal'),
                'estado': ch.get('estado'),
            }))

        wizard = self.env['cotizador.bcra.wizard'].create({
            'partner_id': self.partner_id.id,
            'cuit': data.get('cuit') or self.partner_id.vat,
            'denominacion': data.get('denominacion') or self.partner_id.name,
            'tiene_deuda': data.get('tiene_deuda', False),
            'peor_situacion': data.get('peor_situacion') or ('1' if data.get('deudas') else False),
            'monto_total': data.get('monto_total_deuda', 0.0),
            'alerta_mensaje': data.get('mensaje_resumen', ''),
            'deuda_ids': deuda_commands,
            'cheque_ids': cheque_commands,
        })

        return {
            'name': _('Situación Crediticia BCRA - %s') % (self.partner_id.name),
            'type': 'ir.actions.act_window',
            'res_model': 'cotizador.bcra.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    # --- Sincronización Automática con Oportunidades del CRM ---

    @api.model_create_multi
    def create(self, vals_list):
        orders = super().create(vals_list)
        for order in orders:
            if order.opportunity_id:
                order.opportunity_id._sync_expected_revenue_from_orders()
        return orders

    def write(self, vals):
        res = super().write(vals)
        if any(f in vals for f in ('amount_untaxed', 'amount_total', 'order_line', 'state', 'opportunity_id')):
            for order in self:
                if order.opportunity_id:
                    order.opportunity_id._sync_expected_revenue_from_orders()
        return res

    # --- Métodos de Configuración y Planes de Pago ---

    def action_confirm(self):
        """Override para validar que exista al menos una línea de plan de pago antes de confirmar (si está configurado como obligatorio)."""
        plan_pago_required = self.env['ir.config_parameter'].sudo().get_param(
            'cotizador.plan_pago_required', default='False'
        )
        if plan_pago_required == 'True':
            for order in self:
                tiene_plan_pago = order.order_line.filtered(lambda l: l.is_plan_pago)
                if not tiene_plan_pago:
                    raise UserError(
                        _("No se puede confirmar la orden '%s' porque no tiene un Plan de Pago seleccionado.\n"
                          "Por favor, agregue un Plan de Pago antes de confirmar.") % order.name
                    )
        return super().action_confirm()

    def print_quotation(self):
        """Override del botón estándar de impresión de Odoo para emitir el reporte personalizado con planes de pago."""
        report = self.env.ref('cotizador.action_report_cotizacion_planes', raise_if_not_found=False)
        if report:
            self.filtered(lambda s: s.state == 'draft').write({'state': 'sent'})
            return report.report_action(self)
        return super().print_quotation()

    def action_open_config_wizard(self):
        """Abre el configurador de sembradora (Visual OWL o Wizard Legacy según la configuración del sistema)."""
        order_id = self.id or self.env.context.get('active_id') or self.env.context.get('params', {}).get('id')
        use_legacy = self.env['ir.config_parameter'].sudo().get_param(
            'cotizador.use_legacy_wizard', default='False'
        )
        if use_legacy == 'True':
            return {
                'type': 'ir.actions.act_window',
                'name': 'Configurar Sembradora (Legacy)',
                'res_model': 'sembradora.config.wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': {'default_sale_order_id': order_id},
            }

        return {
            'type': 'ir.actions.client',
            'tag': 'cotizador_configurator',
            'target': 'current',
            'params': {
                'order_id': order_id,
            },
            'context': {
                'active_id': order_id,
                'default_sale_order_id': order_id,
            },
        }

    def action_open_plan_pago_wizard(self):
        self.ensure_one()
        templates = self.env['cotizador.plan.pago.template.line'].search([
            ('template_id.active', '=', True)
        ])
        lines = []
        for t in templates:
            lines.append((0, 0, {
                'template_line_id': t.id,
                'tipo': t.tipo,
                'name': t.name,
                'descuento': t.descuento,
            }))
        wizard = self.env['cotizador.plan.pago.wizard'].create({
            'sale_order_id': self.id,
            'wizard_line_ids': lines,
        })
        return {
            'name': 'Seleccionar Plan de Pago',
            'type': 'ir.actions.act_window',
            'res_model': 'cotizador.plan.pago.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }


class SaleOrderLineInherit(models.Model):
    _inherit = 'sale.order.line'

    is_plan_pago = fields.Boolean(default=False)

    def action_open_config_wizard(self):
        """Delegación del botón del listado de líneas al sale.order padre."""
        order_id = False
        if self.order_id:
            order_id = self.order_id
        else:
            ctx = self.env.context
            parent_id = (
                ctx.get('default_sale_order_id') or
                ctx.get('order_id') or
                ctx.get('active_id') or 
                ctx.get('default_order_id') or 
                ctx.get('params', {}).get('id')
            )
            if parent_id:
                order_id = self.env['sale.order'].browse(parent_id)

        if not order_id:
            raise ValidationError("No se pudo identificar la orden de venta activa. Por favor, guarde la cotización antes de configurar.")

        return order_id.action_open_config_wizard()
