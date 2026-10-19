# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class CotizadorDescuentoWizard(models.TransientModel):
    _name = 'cotizador.descuento.wizard'
    _description = 'Añadir Descuento Comercial a la Cotización'

    sale_order_id = fields.Many2one(
        'sale.order',
        string='Cotización / Pedido',
        required=True,
    )
    currency_id = fields.Many2one(
        related='sale_order_id.currency_id',
        string='Moneda',
        readonly=True,
    )
    tipo_calculo = fields.Selection([
        ('porcentaje', 'Porcentaje (%)'),
        ('monto', 'Monto Fijo ($)'),
    ], string='Tipo de Descuento', default='porcentaje', required=True)

    porcentaje = fields.Float(
        string='Porcentaje (%)',
        default=8.0,
        digits=(16, 2),
        help='Porcentaje de bonificación a aplicar sobre el saldo total vigente.',
    )
    monto_fijo = fields.Monetary(
        string='Monto Fijo ($)',
        currency_field='currency_id',
        help='Importe neto a descontar.',
    )
    base_saldo = fields.Monetary(
        string='Base de Cálculo (Saldo con IVA)',
        currency_field='currency_id',
        compute='_compute_base_saldo',
        readonly=True,
        help='Importe sobre el cual se aplicará el porcentaje de descuento en cascada.',
    )
    monto_descuento = fields.Monetary(
        string='Monto Resultante del Descuento',
        currency_field='currency_id',
        compute='_compute_monto_descuento',
        inverse='_inverse_monto_descuento',
        store=True,
        readonly=False,
    )
    nombre = fields.Char(
        string='Descripción del Descuento',
        required=True,
        default='Descuento Especial 8%',
    )

    @api.depends('sale_order_id')
    def _compute_base_saldo(self):
        for rec in self:
            if not rec.sale_order_id:
                rec.base_saldo = 0.0
                continue
            order = rec.sale_order_id
            # Base = Total con IVA de productos menos descuentos previos ya aplicados
            # Total base de productos
            prod_lines = order.order_line.filtered(
                lambda l: not l.display_type and not l.is_descuento and not l.is_equipo_usado
            )
            subtotal_prod = sum(prod_lines.mapped('price_subtotal'))
            iva_prod = sum(prod_lines.mapped('price_tax'))
            total_prod = subtotal_prod + iva_prod

            # Descuentos previos ya existentes
            desc_lines = order.order_line.filtered(lambda l: l.is_descuento)
            descuentos_previos = sum(abs(l.price_subtotal) for l in desc_lines)

            saldo_restante = max(0.0, total_prod - descuentos_previos)
            rec.base_saldo = saldo_restante

    @api.depends('tipo_calculo', 'porcentaje', 'monto_fijo', 'base_saldo')
    def _compute_monto_descuento(self):
        for rec in self:
            if rec.tipo_calculo == 'porcentaje':
                pct = rec.porcentaje or 0.0
                rec.monto_descuento = round(rec.base_saldo * (pct / 100.0), 2)
            else:
                rec.monto_descuento = round(rec.monto_fijo or 0.0, 2)

    def _inverse_monto_descuento(self):
        for rec in self:
            if rec.tipo_calculo == 'monto':
                rec.monto_fijo = rec.monto_descuento

    @api.onchange('tipo_calculo', 'porcentaje')
    def _onchange_nombre_sugerido(self):
        if self.tipo_calculo == 'porcentaje' and self.porcentaje:
            pct_str = f"{int(self.porcentaje)}" if self.porcentaje.is_integer() else f"{self.porcentaje:.2f}"
            self.nombre = f"Descuento Especial {pct_str}%"
        elif self.tipo_calculo == 'monto':
            self.nombre = "Descuento Especial"

    def action_confirm(self):
        self.ensure_one()
        order = self.sale_order_id
        if not order:
            raise ValidationError(_("No se pudo identificar la cotización activa."))

        monto = float(self.monto_descuento or 0.0)
        if monto <= 0.0:
            raise ValidationError(_("El monto del descuento debe ser mayor a cero."))

        precio_negativo = -abs(monto)

        # Buscar si ya existe la sección 'Descuentos'
        existing_section = order.order_line.filtered(lambda l: l.cotizador_section == 'descuentos')

        max_sequence = max(order.order_line.mapped('sequence') or [0])

        if not existing_section:
            max_sequence += 1
            self.env['sale.order.line'].create({
                'order_id': order.id,
                'name': 'Descuentos',
                'display_type': 'line_section',
                'cotizador_section': 'descuentos',
                'sequence': max_sequence,
            })

        max_sequence += 1
        self.env['sale.order.line'].create({
            'order_id': order.id,
            'name': (self.nombre or 'Descuento').strip(),
            'product_uom_qty': 1.0,
            'price_unit': precio_negativo,
            'tax_ids': False,
            'is_descuento': True,
            'sequence': max_sequence,
        })

        if order.opportunity_id:
            order.opportunity_id._sync_expected_revenue_from_orders()

        return {'type': 'ir.actions.act_window_close'}
