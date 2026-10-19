from odoo import models, fields, api
from odoo.exceptions import ValidationError

TIPO_PLAN_SELECTION = [
    ('canje_cereal', 'Plan Canje Cereal'),
    ('cheques', 'Plan Cheques'),
    ('documentos', 'Plan Documentos'),
    ('credito_bancario', 'Plan Crédito Bancario'),
]


class PlanPagoTemplate(models.Model):
    """Plantillas de planes de pago configuradas por el administrador.
    Definen las opciones fijas que luego se copian a cada cotización."""
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
    """Línea de plantilla: cada opción dentro de un tipo de plan.
    Ej: Para 'Plan Cheques' → opción 1 (30 días), opción 5 (90 días), etc."""
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
        """Selecciona esta línea de plantilla para la cotización activa."""
        sale_order_id = self.env.context.get('default_sale_order_id') or self.env.context.get('active_id')
        if not sale_order_id:
            # Fallback en caso de llamarse desde sub-vistas
            sale_order_id = self.env.context.get('params', {}).get('id')

        if not sale_order_id:
            raise ValidationError("No se pudo identificar la cotización activa para asociar el plan de pago.")

        order = self.env['sale.order'].browse(sale_order_id)
        
        # Obtenemos el nombre legible del tipo (ej: en vez de 'canje_cereal' -> 'Plan Canje Cereal')
        tipo_dict = dict(TIPO_PLAN_SELECTION)
        tipo_legible = tipo_dict.get(self.tipo, self.tipo)

        # 1. Armamos una descripción detallada según el tipo de plan
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

        # Validamos que no se haya añadido un plan de pago previamente.
        if order.order_line.filtered('is_plan_pago'):
            raise ValidationError("Ya existe un Plan de pago seleccionado. Elimine el existente antes de añadir uno nuevo.")
        
        payplan = self.env.ref(f'cotizador.product_plan_{self.tipo}')
        payprice = order.amount_total * (self.descuento / 100)

        max_sequence = max(order.order_line.mapped('sequence') or [0])

        self.env['sale.order.line'].create({
            'order_id': order.id,
            'name': f'Información de Pago: {tipo_legible}', 
            'display_type': 'line_section',
            'sequence': max_sequence + 1,
            'is_plan_pago': True,
        })

        self.env['sale.order.line'].create({
            'order_id': order.id,
            'product_id': payplan.id,
            'name': descripcion_detallada, 
            'product_uom_qty': 1,
            'is_plan_pago': True,
            'tax_ids': [(6, 0, [])], 
            'price_unit': payprice, 
            'sequence': max_sequence + 2, 
        })


        return {'type': 'ir.actions.act_window_close'}


class PlanPagoWizard(models.TransientModel):
    """Wizard para seleccionar el plan de pago directamente desde las plantillas activas."""
    _name = 'cotizador.plan.pago.wizard'
    _description = 'Wizard de Selección de Plan de Pago'

    sale_order_id = fields.Many2one('sale.order', string='Cotización', required=True)

    # Campo Many2many computado que trae todas las opciones de plantillas disponibles
    # template_line_ids = fields.Many2many(
    #     'cotizador.plan.pago.template.line',
    #     string='Opciones de Planes Disponibles',
    #     compute='_compute_template_lines')

    wizard_line_ids = fields.One2many(
        'cotizador.plan.pago.wizard.line', 
        'wizard_id', 
        string='Opciones de Planes Disponibles'
    )

    # @api.depends('sale_order_id')
    # def _compute_template_lines(self):
    #     for wiz in self:
    #         # Trae todas las opciones que pertenecen a plantillas activas
    #         wiz.template_line_ids = self.env['cotizador.plan.pago.template.line'].search([
    #             ('template_id.active', '=', True)
    #         ])

    # def action_eliminar_plan(self):
    #     """Elimina el plan de pago seleccionado de la cotización."""
    #     self.sale_order_id.plan_pago_ids.unlink()
    #     return {'type': 'ir.actions.act_window_close'}


class PlanPagoWizardLine(models.TransientModel):
    """Línea temporal dentro del wizard para mostrar datos calculados en tiempo real."""
    _name = 'cotizador.plan.pago.wizard.line'
    _description = 'Línea Temporal de Selección de Plan'

    wizard_id = fields.Many2one('cotizador.plan.pago.wizard', ondelete='cascade')
    template_line_id = fields.Many2one('cotizador.plan.pago.template.line', required=True)
    
    tipo = fields.Selection(TIPO_PLAN_SELECTION, string='Tipo de Plan')
    name = fields.Char(string='Detalle de la Opción')
    descuento = fields.Float(string='Descuento / Recargo (%)')
    total_simulado = fields.Float(string='Total Simulado', compute='_compute_total_simulado')

    @api.depends('wizard_id.sale_order_id.amount_total', 'descuento')
    def _compute_total_simulado(self):
        for rec in self:
            precio_base = rec.wizard_id.sale_order_id.amount_total or 0
            rec.total_simulado = precio_base * (1 + rec.descuento / 100)

    def action_select_line(self):
        self.ensure_one()
        return self.template_line_id.with_context(
            default_sale_order_id=self.wizard_id.sale_order_id.id
        ).action_select_line()