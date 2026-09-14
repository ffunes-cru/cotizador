from odoo import models, fields, api


class SembradoraConfigRel(models.Model):
    _name = 'sembradora.config.rel'
    _description = 'Matriz de Configuraciones Permitidas'

    ext_id = fields.Char(string='ID Externo', readonly=False)
    modelo_id = fields.Many2one('product.template', string='Modelo', required=True,
                                domain=[("categ_id.name", "=", "Maquina")])
    # Cambiamos a Many2many para que en una sola fila pongas TODA la configuración
    value_ids = fields.Many2many('product.attribute.value', string='Combinación Permitida')

    # Relación 1:N con accesorios (cada uno con su precio en esta configuración)
    accessory_line_ids = fields.One2many(
        'sembradora.config.accessory.line',
        'config_id',
        string='Accesorios con Precio')

    price = fields.Float(string="Precio de Configuración")
    description = fields.Html(
        string="Descripción",
        compute="_compute_description",
        store=True,
        readonly=False,
        help="Descripción detallada de la configuración de la máquina, calculada según el atributo rector de la plantilla."
    )

    name = fields.Char(string="Configuración", compute="_compute_name", store=True)

    @api.depends(
        'modelo_id.description_line_ids.value_ids',
        'modelo_id.description_line_ids.sequence',
        'modelo_id.description_line_ids.description',
        'modelo_id.description_default',
        'value_ids'
    )
    def _compute_description(self):
        for reg in self:
            if reg.modelo_id:
                desc = reg.modelo_id.get_config_description(reg.value_ids)
                if desc:
                    reg.description = desc
                elif not reg.description:
                    reg.description = ''
            elif not reg.description:
                reg.description = ''

    @api.depends('modelo_id', 'value_ids')
    def _compute_name(self):
        for reg in self:
            # .mapped('name') extrae todos los nombres de los valores y los une con comas
            attrs = ", ".join(reg.value_ids.mapped('name'))
            reg.name = f"{reg.modelo_id.name}: {attrs}"