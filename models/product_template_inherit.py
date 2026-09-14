from odoo import models, fields, api


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    is_maquina = fields.Boolean(
        string="Es Máquina",
        compute="_compute_is_maquina",
        store=True,
        help="Indica si este producto pertenece a la categoría de máquinas configurables."
    )
    available_attribute_ids = fields.Many2many(
        'product.attribute',
        string="Atributos de la Máquina",
        compute="_compute_available_attributes",
        help="Atributos configurados en las líneas de variantes de esta máquina."
    )
    available_attribute_value_ids = fields.Many2many(
        'product.attribute.value',
        string="Valores de Atributos Disponibles",
        compute="_compute_available_attributes",
        help="Todos los valores de atributo disponibles para configurar en esta máquina."
    )
    description_attribute_id = fields.Many2one(
        'product.attribute',
        string="Atributo Rector (Opcional)",
        domain="[('id', 'in', available_attribute_ids)]",
        help="Atributo de referencia si desea categorizar por una característica principal."
    )
    description_line_ids = fields.One2many(
        'product.template.description.line',
        'product_tmpl_id',
        string="Reglas de Descripción Paramétrica"
    )
    description_default = fields.Html(
        string="Descripción por Defecto",
        sanitize_style=True,
        help="Descripción general de respaldo si la combinación configurada no coincide con ninguna regla específica."
    )

    @api.depends('categ_id', 'categ_id.name')
    def _compute_is_maquina(self):
        for tmpl in self:
            tmpl.is_maquina = bool(tmpl.categ_id and tmpl.categ_id.name == 'Maquina')

    @api.depends('attribute_line_ids', 'attribute_line_ids.attribute_id', 'attribute_line_ids.value_ids')
    def _compute_available_attributes(self):
        for tmpl in self:
            tmpl.available_attribute_ids = tmpl.attribute_line_ids.mapped('attribute_id')
            tmpl.available_attribute_value_ids = tmpl.attribute_line_ids.mapped('value_ids')

    def get_config_description(self, value_ids):
        """
        Retorna la descripción HTML correspondiente a la combinación de valores dada.
        Evalúa reglas con N atributos requeridos:
        1. Filtra reglas cuyos 'value_ids' sean subconjunto de los valores seleccionados.
        2. Ordena por mayor especificidad (cantidad de atributos requeridos) y luego secuencia.
        3. Si no hay coincidencia, retorna la descripción por defecto.
        """
        self.ensure_one()
        if self.description_line_ids and value_ids:
            selected_set = set(value_ids.ids)
            matching_rules = []
            for rule in self.description_line_ids:
                if rule.value_ids and set(rule.value_ids.ids).issubset(selected_set):
                    matching_rules.append(rule)

            if matching_rules:
                # Ordenar: primero las que requieren más atributos (más específicas), luego por secuencia
                matching_rules.sort(key=lambda r: (-len(r.value_ids), r.sequence))
                best_rule = matching_rules[0]
                if best_rule.description:
                    return best_rule.description

        return self.description_default or self.description_sale or ''


class ProductTemplateDescriptionLine(models.Model):
    _name = 'product.template.description.line'
    _description = 'Regla de Descripción Paramétrica por Combinación de Atributos'
    _order = 'sequence asc, id asc'

    product_tmpl_id = fields.Many2one(
        'product.template',
        string="Modelo de Máquina",
        required=True,
        ondelete='cascade',
        index=True
    )
    name = fields.Char(
        string="Nombre / Referencia",
        help="Ej: Leaf Mecánica, Leaf Neumática, Pionera..."
    )
    sequence = fields.Integer(
        string="Secuencia",
        default=10,
        help="Orden de evaluación y prioridad para desempatar reglas con igual cantidad de atributos."
    )
    value_ids = fields.Many2many(
        'product.attribute.value',
        'product_tmpl_desc_line_attr_val_rel',
        'line_id',
        'val_id',
        string="Valores de Atributo Requeridos",
        help="Seleccione uno o más valores que deben estar presentes en la variante para aplicar esta descripción (ej. LEAF + Mecánico)."
    )
    description = fields.Html(
        string="Descripción Técnica (Rich Text)",
        sanitize_style=True,
        required=True,
        help="Texto enriquecido que se mostrará en el configurador interactivo y en la cotización PDF."
    )

    @api.onchange('value_ids')
    def _onchange_value_ids_name(self):
        """Genera un nombre sugerido automáticamente si está vacío."""
        if not self.name and self.value_ids:
            self.name = " + ".join(self.value_ids.mapped('name'))
