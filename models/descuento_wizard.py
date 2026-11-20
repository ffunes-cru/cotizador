"""@file
Asistente para agregar un descuento o un recargo comercial a la cotización (secciones *Descuentos* y *Recargos*)."""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class CotizadorDescuentoWizard(models.TransientModel):
    """Descuento o recargo comercial (`cotizador.descuento.wizard`), en porcentaje o monto fijo.

    Se aplica sobre el **neto** (sin IVA) y el IVA se calcula después sobre el neto ajustado:
    100.000 neto con 6 % de descuento → 94.000 + IVA; con 6 % de recargo → 106.000 + IVA. Con
    varios, cada porcentaje se aplica sobre lo que dejaron los anteriores (cascada), en el orden
    en que se cargaron. El recargo (`tipo_ajuste = 'recargo'`, issue #21) es el mismo cálculo con
    el signo contrario, en la sección `recargos` y con `is_recargo`.

    Crea, en la sección `cotizador_section = 'descuentos'` (la crea si falta), una línea sin
    producto con precio negativo por cada grupo de impuestos de la cotización, con los mismos
    impuestos que los productos del grupo. Un descuento en porcentaje guarda el porcentaje
    (`cotizador_pct`) y se recalcula solo si cambian los productos
    (sale.order._cotizador_update_adjustments()); uno de monto fijo se reparte entre los grupos
    en proporción a su neto y no cambia.
    """
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
    tipo_ajuste = fields.Selection([
        ('descuento', 'Descuento'),
        ('recargo', 'Recargo'),
    ], string='Ajuste', default='descuento', required=True)
    tipo_calculo = fields.Selection([
        ('porcentaje', 'Porcentaje (%)'),
        ('monto', 'Monto Fijo ($)'),
    ], string='Tipo de Cálculo', default='porcentaje', required=True)

    porcentaje = fields.Float(
        string='Porcentaje (%)',
        default=8.0,
        digits=(16, 2),
        help='Porcentaje sobre el neto vigente (después de los descuentos y recargos anteriores).',
    )
    monto_fijo = fields.Monetary(
        string='Monto Fijo ($)',
        currency_field='currency_id',
        help='Importe neto (sin IVA) a descontar o recargar.',
    )
    base_neto = fields.Monetary(
        string='Base de Cálculo (Neto)',
        currency_field='currency_id',
        compute='_compute_base_neto',
        readonly=True,
        help='Neto de los productos con los descuentos y recargos ya cargados, sin IVA.',
    )
    monto_descuento = fields.Monetary(
        string='Importe Neto Resultante',
        currency_field='currency_id',
        compute='_compute_monto_descuento',
        inverse='_inverse_monto_descuento',
        store=True,
        readonly=False,
    )
    nombre = fields.Char(
        string='Descripción',
        required=True,
        default=lambda self: ('Recargo 8%' if self.env.context.get('default_tipo_ajuste') == 'recargo'
                              else 'Descuento Especial 8%'),
    )

    @api.depends('sale_order_id')
    def _compute_base_neto(self):
        """Base del ajuste: neto de los productos con los descuentos y recargos ya cargados."""
        for rec in self:
            groups = rec.sale_order_id._cotizador_tax_groups() if rec.sale_order_id else {}
            rec.base_neto = max(0.0, sum(groups.values()))

    @api.depends('tipo_calculo', 'porcentaje', 'monto_fijo', 'base_neto')
    def _compute_monto_descuento(self):
        """Importe neto: base × porcentaje, o el monto fijo (siempre positivo; el signo lo da el tipo)."""
        for rec in self:
            if rec.tipo_calculo == 'porcentaje':
                rec.monto_descuento = round(rec.base_neto * (rec.porcentaje or 0.0) / 100.0, 2)
            else:
                rec.monto_descuento = round(rec.monto_fijo or 0.0, 2)

    def _inverse_monto_descuento(self):
        """Editar el monto resultante en modo "monto" actualiza el monto fijo."""
        for rec in self:
            if rec.tipo_calculo == 'monto':
                rec.monto_fijo = rec.monto_descuento

    @api.onchange('tipo_ajuste', 'tipo_calculo', 'porcentaje')
    def _onchange_nombre_sugerido(self):
        """Sugiere la descripción de la línea según el ajuste, el tipo y el porcentaje."""
        base = "Recargo" if self.tipo_ajuste == 'recargo' else "Descuento Especial"
        if self.tipo_calculo == 'porcentaje' and self.porcentaje:
            pct_str = f"{int(self.porcentaje)}" if self.porcentaje.is_integer() else f"{self.porcentaje:.2f}"
            self.nombre = f"{base} {pct_str}%"
        elif self.tipo_calculo == 'monto':
            self.nombre = base

    def action_confirm(self):
        """Crea las líneas de descuento o recargo (y su sección si falta) y actualiza la oportunidad.

        @return Acción que cierra el asistente.
        @throws ValidationError Si no hay cotización, no hay neto para ajustar, el monto no es
                positivo o un descuento supera el neto.
        """
        self.ensure_one()
        order = self.sale_order_id
        if not order:
            raise ValidationError(_("No se pudo identificar la cotización activa."))
        groups = order._cotizador_tax_groups()
        base = sum(groups.values())
        recargo = self.tipo_ajuste == 'recargo'
        if base <= 0:
            raise ValidationError(_("La cotización no tiene productos para recargar.") if recargo
                                  else _("La cotización no tiene productos para descontar."))
        monto = float(self.monto_descuento or 0.0)
        if monto <= 0.0:
            raise ValidationError(_("El monto del recargo debe ser mayor a cero.") if recargo
                                  else _("El monto del descuento debe ser mayor a cero."))
        if not recargo and order.currency_id.compare_amounts(monto, base) > 0:
            raise ValidationError(_("El descuento supera el neto de la cotización."))

        section = 'recargos' if recargo else 'descuentos'
        sequence = max(order.order_line.mapped('sequence') or [0])
        vals_list = []
        if not order.order_line.filtered(lambda l: l.cotizador_section == section):
            sequence += 1
            vals_list.append({
                'order_id': order.id, 'name': 'Recargos' if recargo else 'Descuentos', 'display_type': 'line_section',
                'cotizador_section': section, 'sequence': sequence,
            })
        name = (self.nombre or ('Recargo' if recargo else 'Descuento')).strip()
        pct = self.porcentaje if self.tipo_calculo == 'porcentaje' else 0.0
        remaining = monto
        items = list(groups.items())
        for index, (taxes, net) in enumerate(items):
            # Monto fijo: reparto proporcional al neto de cada grupo; el último toma el resto
            if index == len(items) - 1:
                amount = remaining
            else:
                amount = order.currency_id.round(monto * net / base)
            remaining -= amount
            sequence += 1
            vals_list.append({
                'order_id': order.id,
                'name': f"{name} ({', '.join(taxes.mapped('name'))})" if len(items) > 1 and taxes else name,
                'product_uom_qty': 1.0,
                'price_unit': amount if recargo else -amount,
                'tax_ids': [fields.Command.set(taxes.ids)],
                'is_descuento': not recargo,
                'is_recargo': recargo,
                'cotizador_pct': pct,
                'sequence': sequence,
            })
        self.env['sale.order.line'].create(vals_list)

        if order.opportunity_id:
            order.opportunity_id._sync_expected_revenue_from_orders()
        return {'type': 'ir.actions.act_window_close'}
