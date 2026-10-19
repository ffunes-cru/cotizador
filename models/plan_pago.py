"""@file
Planes de pago: catálogo de opciones (plantillas) y su selección en la cotización.

Flujo: el administrador carga plantillas por tipo de plan (*Ventas › Configuración*); en la
cotización, el botón de plan de pago abre cotizador.plan.pago.wizard con todas las opciones
activas y el total simulado de cada una; al elegir una se agregan una sección y una línea con
el producto de servicio del tipo (`cotizador.product_plan_<tipo>`) y el recargo o descuento.
"""
from odoo import api, fields, models
from odoo.exceptions import ValidationError

## Tipos de plan. Cada clave tiene su producto de servicio `cotizador.product_plan_<clave>`
## (data/product_plan_pago_data.xml).
TIPO_PLAN_SELECTION = [
    ('canje_cereal', 'Plan Canje Cereal'),
    ('cheques', 'Plan Cheques'),
    ('documentos', 'Plan Documentos'),
    ('credito_bancario', 'Plan Crédito Bancario'),
]


class PlanPagoTemplate(models.Model):
    """Plantilla de plan de pago (`cotizador.plan.pago.template`): un tipo con sus opciones."""
    _name = 'cotizador.plan.pago.template'
    _description = 'Plantilla de Plan de Pago'

    name = fields.Char(string='Nombre', required=True)
    tipo = fields.Selection(TIPO_PLAN_SELECTION, string='Tipo de Plan', required=True)
    active = fields.Boolean(default=True)
    line_ids = fields.One2many(
        'cotizador.plan.pago.template.line',
        'template_id',
        string='Opciones del Plan')


class PlanPagoTemplateLine(models.Model):
    """Opción de un plan de pago (`cotizador.plan.pago.template.line`).

    Cada tipo usa su propio grupo de campos de texto (ver la vista); `descuento` es común:
    porcentaje negativo = descuento, positivo = recargo. Ejemplo para *Plan Cheques*:
    "30-60-90", 60 días promedio, 3 cheques, -5 %.
    """
    _name = 'cotizador.plan.pago.template.line'
    _description = 'Línea de Plantilla de Plan de Pago'
    _order = 'sequence, id'

    template_id = fields.Many2one(
        'cotizador.plan.pago.template',
        string='Plantilla',
        required=True,
        ondelete='cascade')

    sequence = fields.Integer(string='Secuencia', default=10)

    # Tipo heredado de la plantilla padre
    tipo = fields.Selection(related='template_id.tipo', store=True, readonly=True)

    # === Campos Plan Canje Cereal ===
    opcion = fields.Char(string='Opción')
    entrega_canje = fields.Char(string='Entrega (Canje)')
    condicion = fields.Char(string='Condición')

    # === Campos Plan Cheques ===
    plan_cheques = fields.Char(string='Plan (Cheques)')
    promedio_dias = fields.Integer(string='Promedio de Días')
    cheques_desc = fields.Char(string='Cheques')

    # === Campos Plan Documentos ===
    plan_documentos = fields.Char(string='Plan (Documentos)')
    entrega_pct = fields.Char(string='Entrega (%)')
    saldo = fields.Char(string='Saldo')

    # === Campos Plan Crédito Bancario ===
    banco_linea = fields.Char(string='Banco - Moneda - Línea')
    plazo_tasa = fields.Char(string='Plazo - Tasa')
    financiacion = fields.Char(string='Financiación')

    # === Campo común: Descuento/Recargo ===
    descuento = fields.Float(string='Descuento o Recargo (%)', default=0,
                             help='Valor negativo = descuento, valor positivo = recargo. Ej: -10 para 10% descuento, 11 para 11% recargo')

    name = fields.Char(string='Descripción', compute='_compute_name', store=True)

    @api.depends('tipo', 'opcion', 'plan_cheques', 'plan_documentos', 'banco_linea',
                 'entrega_canje', 'condicion', 'promedio_dias', 'cheques_desc',
                 'entrega_pct', 'saldo', 'plazo_tasa', 'financiacion')
    def _compute_name(self):
        """Resumen de una línea según el tipo, p. ej. "Cheques: 30-60-90 (60 días | Chq: 3)"."""
        for rec in self:
            if rec.tipo == 'canje_cereal':
                rec.name = f"Canje: {rec.opcion or ''} (Entr: {rec.entrega_canje or ''} | Cond: {rec.condicion or ''})"
            elif rec.tipo == 'cheques':
                rec.name = f"Cheques: {rec.plan_cheques or ''} ({rec.promedio_dias or 0} días | Chq: {rec.cheques_desc or ''})"
            elif rec.tipo == 'documentos':
                rec.name = f"Docts: {rec.plan_documentos or ''} (Entr: {rec.entrega_pct or ''} | Saldo: {rec.saldo or ''})"
            elif rec.tipo == 'credito_bancario':
                rec.name = f"Crédito: {rec.banco_linea or ''} (Plazo/Tasa: {rec.plazo_tasa or ''} | Fin: {rec.financiacion or ''})"
            else:
                rec.name = "Línea de Plan de Pago"

    def action_select_line(self):
        """Agrega esta opción a la cotización del contexto (`default_sale_order_id` o `active_id`).

        Crea una sección y, por cada grupo de impuestos, una línea con el producto del tipo de
        plan, los impuestos del grupo y el porcentaje de la opción (`cotizador_pct`). El importe
        es neto con descuentos × porcentaje y se recalcula solo cuando cambian las líneas
        (sale.order._cotizador_update_adjustments()). Solo puede haber un plan por cotización.

        @return Acción que cierra el asistente.
        @throws ValidationError Si no se identifica la cotización o ya tiene un plan.
        """
        sale_order_id = self.env.context.get('default_sale_order_id') or self.env.context.get('active_id')
        if not sale_order_id:
            # Llamado desde una sub-vista: el id viene en los parámetros de la acción
            sale_order_id = self.env.context.get('params', {}).get('id')

        if not sale_order_id:
            raise ValidationError("No se pudo identificar la cotización activa para asociar el plan de pago.")

        order = self.env['sale.order'].browse(sale_order_id)
        
        tipo_dict = dict(TIPO_PLAN_SELECTION)
        tipo_legible = tipo_dict.get(self.tipo, self.tipo)

        descripcion_detallada = ""
        
        if self.tipo == 'canje_cereal':
            descripcion_detallada += f"• Opción: {self.opcion or '-'}\n"
            descripcion_detallada += f"• Entrega: {self.entrega_canje or '-'}\n"
            descripcion_detallada += f"• Condición: {self.condicion or '-'}"
            
        elif self.tipo == 'cheques':
            descripcion_detallada += f"• Plan: {self.plan_cheques or '-'}\n"
            descripcion_detallada += f"• Promedio de Días: {self.promedio_dias or 0}\n"
            descripcion_detallada += f"• Cheques: {self.cheques_desc or '-'}"
            
        elif self.tipo == 'documentos':
            descripcion_detallada += f"• Plan: {self.plan_documentos or '-'}\n"
            descripcion_detallada += f"• Entrega: {self.entrega_pct or '-'}\n"
            descripcion_detallada += f"• Saldo: {self.saldo or '-'}"
            
        elif self.tipo == 'credito_bancario':
            descripcion_detallada += f"• Banco/Línea: {self.banco_linea or '-'}\n"
            descripcion_detallada += f"• Plazo/Tasa: {self.plazo_tasa or '-'}\n"
            descripcion_detallada += f"• Financiación: {self.financiacion or '-'}"

        if self.descuento:
            tipo_movimiento = "Recargo" if self.descuento > 0 else "Descuento"
            descripcion_detallada += f"\n• {tipo_movimiento}: {abs(self.descuento)}%"

        if order.order_line.filtered('is_plan_pago'):
            raise ValidationError("Ya existe un Plan de pago seleccionado. Elimine el existente antes de añadir uno nuevo.")
        
        payplan = self.env.ref(f'cotizador.product_plan_{self.tipo}')
        groups = order._cotizador_tax_groups()
        sequence = max(order.order_line.mapped('sequence') or [0]) + 1
        vals_list = [{
            'order_id': order.id,
            'name': f'Información de Pago: {tipo_legible}',
            'display_type': 'line_section',
            'sequence': sequence,
            'is_plan_pago': True,
        }]
        # Una línea por grupo de impuestos: el recargo o descuento lleva el IVA de lo que ajusta.
        # El importe lo calcula sale.order._cotizador_update_adjustments() al crearlas.
        for taxes in groups or {self.env['account.tax']: 0.0}:
            sequence += 1
            vals_list.append({
                'order_id': order.id,
                'product_id': payplan.id,
                'name': descripcion_detallada,
                'product_uom_qty': 1,
                'is_plan_pago': True,
                'cotizador_pct': self.descuento,
                'tax_ids': [fields.Command.set(taxes.ids)],
                'price_unit': 0.0,
                'sequence': sequence,
            })
        self.env['sale.order.line'].create(vals_list)
        return {'type': 'ir.actions.act_window_close'}


class PlanPagoWizard(models.TransientModel):
    """Selección del plan de pago (`cotizador.plan.pago.wizard`).

    sale.order.action_open_plan_pago_wizard() lo crea con una línea por opción activa.
    """
    _name = 'cotizador.plan.pago.wizard'
    _description = 'Wizard de Selección de Plan de Pago'

    sale_order_id = fields.Many2one('sale.order', string='Cotización', required=True)

    wizard_line_ids = fields.One2many(
        'cotizador.plan.pago.wizard.line', 
        'wizard_id', 
        string='Opciones de Planes Disponibles'
    )


class PlanPagoWizardLine(models.TransientModel):
    """Opción dentro del asistente, con el total simulado de la cotización si se elige."""
    _name = 'cotizador.plan.pago.wizard.line'
    _description = 'Línea Temporal de Selección de Plan'

    wizard_id = fields.Many2one('cotizador.plan.pago.wizard', ondelete='cascade')
    template_line_id = fields.Many2one('cotizador.plan.pago.template.line', required=True)
    
    tipo = fields.Selection(TIPO_PLAN_SELECTION, string='Tipo de Plan')
    name = fields.Char(string='Detalle de la Opción')
    descuento = fields.Float(string='Descuento / Recargo (%)')
    total_simulado = fields.Float(string='Total Simulado', compute='_compute_total_simulado')

    @api.depends('wizard_id.sale_order_id.amount_saldo_cancelar', 'descuento')
    def _compute_total_simulado(self):
        """Saldo de la cotización si se elige esta opción (sale.order._cotizador_simulate_plan())."""
        for rec in self:
            order = rec.wizard_id.sale_order_id
            rec.total_simulado = order._cotizador_simulate_plan(rec.descuento) if order else 0.0

    def action_select_line(self):
        """Elige esta opción: delega en cotizador.plan.pago.template.line.action_select_line().

        @return Acción que cierra el asistente.
        """
        self.ensure_one()
        return self.template_line_id.with_context(
            default_sale_order_id=self.wizard_id.sale_order_id.id
        ).action_select_line()
