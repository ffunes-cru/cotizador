from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class EquipoUsadoWizard(models.TransientModel):
    _name = 'equipo.usado.wizard'
    _description = 'Añadir Equipo Usado como Pago'

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
    descripcion = fields.Text(
        string='Descripción del Equipo Usado',
        required=True,
        help='Indique marca, modelo, cantidad de líneas, año, estado o cualquier detalle del equipo tomado.',
    )
    monto = fields.Monetary(
        string='Monto de Toma (Pago)',
        currency_field='currency_id',
        required=True,
        help='Valor acordado por el equipo usado que se descontará de la cotización.',
    )

    def action_confirm(self):
        self.ensure_one()
        order = self.sale_order_id
        if not order:
            raise ValidationError(_("No se pudo identificar la cotización activa."))

        raw_monto = float(self.monto or 0.0)
        if raw_monto == 0.0:
            raise ValidationError(_("El monto del equipo usado debe ser mayor a cero."))

        # Asegurar matemáticamente que el precio sea SIEMPRE negativo
        precio_negativo = -abs(raw_monto)

        # Verificar si ya existe una sección 'Equipo Usado'
        existing_section = order.order_line.filtered(lambda l: l.cotizador_section == 'usados')

        max_sequence = max(order.order_line.mapped('sequence') or [0])

        if not existing_section:
            max_sequence += 1
            self.env['sale.order.line'].create({
                'order_id': order.id,
                'name': 'Equipo Usado',
                'display_type': 'line_section',
                'cotizador_section': 'usados',
                'sequence': max_sequence,
            })

        max_sequence += 1
        nombre_linea = self.descripcion.strip()
        self.env['sale.order.line'].create({
            'order_id': order.id,
            'name': nombre_linea,
            'product_uom_qty': 1.0,
            'price_unit': precio_negativo,
            'tax_ids': False,
            'is_equipo_usado': True,
            'sequence': max_sequence,
        })

        # Sincronización automática de CRM si existe oportunidad vinculada
        if order.opportunity_id:
            order.opportunity_id._sync_expected_revenue_from_orders()

        return {'type': 'ir.actions.act_window_close'}
