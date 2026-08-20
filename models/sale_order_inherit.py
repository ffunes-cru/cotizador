# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
import logging
from .bcra_service import consultar_bcra_completo, SITUACION_LABELS

_logger = logging.getLogger(__name__)


class SaleOrderInherit(models.Model):
    _inherit = 'sale.order'

    # --- Campos de Integración BCRA Central de Deudores ---
    bcra_consulta_fecha = fields.Datetime(string="Fecha Consulta BCRA", readonly=True, copy=False)
    bcra_denominacion = fields.Char(string="Denominación BCRA", readonly=True, copy=False)
    bcra_tiene_deuda = fields.Boolean(string="Tiene Deuda BCRA", default=False, readonly=True, copy=False)
    bcra_peor_situacion = fields.Selection([
        ('1', '1 - Normal'),
        ('2', '2 - Con Seguimiento Especial'),
        ('3', '3 - Con Problemas'),
        ('4', '4 - Alto Riesgo de Insolvencia'),
        ('5', '5 - Irrecuperable'),
        ('6', '6 - Irrecuperable Técnica'),
    ], string="Peor Situación BCRA", readonly=True, copy=False)
    bcra_monto_total = fields.Monetary(string="Total Deuda BCRA", currency_field='currency_id', readonly=True, copy=False)
    bcra_alerta_mensaje = fields.Text(string="Mensaje de Alerta BCRA", readonly=True, copy=False)

    bcra_deuda_ids = fields.One2many(
        'sale.order.bcra.deuda',
        'order_id',
        string="Deudas en Sistema Financiero",
        copy=False
    )
    bcra_cheque_ids = fields.One2many(
        'sale.order.bcra.cheque',
        'order_id',
        string="Cheques Rechazados",
        copy=False
    )

    def _consultar_y_cargar_bcra(self, partner):
        """Ejecuta la consulta a la API del BCRA para el partner y puebla los campos y líneas de la orden."""
        if not partner or not partner.vat:
            self.bcra_consulta_fecha = False
            self.bcra_denominacion = False
            self.bcra_tiene_deuda = False
            self.bcra_peor_situacion = False
            self.bcra_monto_total = 0.0
            self.bcra_alerta_mensaje = "El cliente no posee CUIT cargado en su ficha."
            self.bcra_deuda_ids = [(5, 0, 0)]
            self.bcra_cheque_ids = [(5, 0, 0)]
            return None

        data = consultar_bcra_completo(partner.vat)
        if not data or not data.get('success'):
            self.bcra_consulta_fecha = fields.Datetime.now()
            self.bcra_alerta_mensaje = data.get('error', 'Error al consultar la API del BCRA.') if data else 'Error desconocido.'
            return None

        self.bcra_consulta_fecha = fields.Datetime.now()
        self.bcra_denominacion = data.get('denominacion') or partner.name
        self.bcra_tiene_deuda = data.get('tiene_deuda', False)
        self.bcra_peor_situacion = data.get('peor_situacion') or ('1' if data.get('deudas') else False)
        self.bcra_monto_total = data.get('monto_total_deuda', 0.0)
        self.bcra_alerta_mensaje = data.get('mensaje_resumen', '')

        # Líneas de deuda bancaria
        deuda_commands = [(5, 0, 0)]
        for d in data.get('deudas', []):
            deuda_commands.append((0, 0, {
                'periodo': d.get('periodo'),
                'entidad': d.get('entidad'),
                'situacion': d.get('situacion'),
                'monto': d.get('monto'),
                'dias_atraso': d.get('dias_atraso'),
                'observaciones': d.get('observaciones'),
            }))
        self.bcra_deuda_ids = deuda_commands

        # Líneas de cheques rechazados
        cheque_commands = [(5, 0, 0)]
        for ch in data.get('cheques_rechazados', []):
            cheque_commands.append((0, 0, {
                'nro_cheque': ch.get('nro_cheque'),
                'fecha_rechazo': ch.get('fecha_rechazo'),
                'monto': ch.get('monto'),
                'causal': ch.get('causal'),
                'estado': ch.get('estado'),
            }))
        self.bcra_cheque_ids = cheque_commands

        return data

    @api.onchange('partner_id')
    def _onchange_partner_id_bcra(self):
        """Al seleccionar cliente, consulta en tiempo real al BCRA y emite alerta si posee deudas."""
        if self.partner_id:
            res_bcra = self._consultar_y_cargar_bcra(self.partner_id)
            if self.bcra_tiene_deuda and self.bcra_monto_total > 0:
                monto_fmt = f"{self.bcra_monto_total:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                peor_desc = SITUACION_LABELS.get(int(self.bcra_peor_situacion or 1), f"Situación {self.bcra_peor_situacion}")
                return {
                    'warning': {
                        'title': _("⚠️ Alerta Crediticia - Central de Deudores BCRA"),
                        'message': _(
                            "El cliente '%s' (CUIT: %s) registra deudas informadas en el BCRA por un monto total de $ %s (%s).\n\n"
                            "Por favor revise los detalles de bancos y cheques en la pestaña 'Situación Crediticia BCRA'."
                        ) % (self.partner_id.name, self.partner_id.vat or '', monto_fmt, peor_desc)
                    }
                }

    def action_consultar_bcra(self):
        """Botón manual para refrescar la información del BCRA."""
        self.ensure_one()
        if not self.partner_id:
            raise UserError(_("Por favor seleccione primero un cliente."))
        if not self.partner_id.vat:
            raise UserError(_("El cliente seleccionado '%s' no tiene CUIT configurado.") % self.partner_id.name)

        self._consultar_y_cargar_bcra(self.partner_id)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Consulta BCRA Actualizada'),
                'message': _('Se actualizó la información crediticia de %s desde el BCRA.') % self.partner_id.name,
                'type': 'info' if not self.bcra_tiene_deuda else 'warning',
                'sticky': False,
            }
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

    # --- Métodos Existentes ---

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

    def action_open_config_wizard(self):
        """Abre nuestro wizard de configuración de sembradora."""
        order_id = self.id or self.env.context.get('active_id') or self.env.context.get('params', {}).get('id')
        return {
            'type': 'ir.actions.act_window',
            'name': 'Configurar Sembradora',
            'res_model': 'sembradora.config.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_sale_order_id': order_id},
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


class SaleOrderBcraDeuda(models.Model):
    _name = 'sale.order.bcra.deuda'
    _description = 'Línea de Deuda Financiera BCRA'
    _order = 'situacion desc, monto desc'

    order_id = fields.Many2one('sale.order', string="Orden de Venta", ondelete='cascade', required=True)
    periodo = fields.Char(string="Período")
    entidad = fields.Char(string="Entidad Financiera", required=True)
    situacion = fields.Selection([
        ('1', '1 - Normal'),
        ('2', '2 - Con Seguimiento Especial'),
        ('3', '3 - Con Problemas'),
        ('4', '4 - Alto Riesgo'),
        ('5', '5 - Irrecuperable'),
        ('6', '6 - Irrecuperable Técnica'),
    ], string="Situación")
    monto = fields.Monetary(string="Monto ($)", currency_field='currency_id')
    currency_id = fields.Many2one(related='order_id.currency_id', string="Moneda", readonly=True)
    dias_atraso = fields.Integer(string="Días Atraso")
    observaciones = fields.Char(string="Observaciones")


class SaleOrderBcraCheque(models.Model):
    _name = 'sale.order.bcra.cheque'
    _description = 'Línea de Cheque Rechazado BCRA'
    _order = 'fecha_rechazo desc'

    order_id = fields.Many2one('sale.order', string="Orden de Venta", ondelete='cascade', required=True)
    nro_cheque = fields.Char(string="Nº Cheque")
    fecha_rechazo = fields.Date(string="Fecha Rechazo")
    monto = fields.Monetary(string="Monto ($)", currency_field='currency_id')
    currency_id = fields.Many2one(related='order_id.currency_id', string="Moneda", readonly=True)
    causal = fields.Char(string="Causal")
    estado = fields.Char(string="Estado")


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
                ctx.get('active_id') or 
                ctx.get('default_order_id') or 
                ctx.get('params', {}).get('id')
            )
            if parent_id:
                order_id = self.env['sale.order'].browse(parent_id)

        if not order_id:
            raise ValidationError("No se pudo identificar la orden de venta activa. Por favor, guarde la cotización antes de configurar.")

        return order_id.action_open_config_wizard()
