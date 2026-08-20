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
    description = fields.Html(string="Descripción", help="Descripción detallada de la configuración de la máquina.")

    name = fields.Char(string="Configuración", compute="_compute_name", store=True)

    @api.depends('modelo_id', 'value_ids')
    def _compute_name(self):
        for reg in self:
            # .mapped('name') extrae todos los nombres de los valores y los une con comas
            attrs = ", ".join(reg.value_ids.mapped('name'))
            reg.name = f"{reg.modelo_id.name}: {attrs}"