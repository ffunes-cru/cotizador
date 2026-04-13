from odoo import models, fields, api

class SembradoraConfigRel(models.Model):
    _name = 'sembradora.config.rel'
    _description = 'Matriz de Configuraciones Permitidas'

    modelo_id = fields.Many2one('product.template', string='Modelo', required=True)
    # Cambiamos a Many2many para que en una sola fila pongas TODA la configuración
    value_ids = fields.Many2many('product.attribute.value', string='Combinación Permitida')

    accesories_id = fields.Many2many(
            'product.product', 
            string='Accesorios Compatibles',
            domain=[("categ_id", "child_of", [4])])

    price = fields.Float(string="Precio de Configuración")
    
    name = fields.Char(string="Configuración", compute="_compute_name")

    @api.depends('modelo_id', 'value_ids')
    def _compute_name(self):
        for reg in self:
            # .mapped('name') extrae todos los nombres de los valores y los une con comas
            attrs = ", ".join(reg.value_ids.mapped('name'))
            reg.name = f"{reg.modelo_id.name}: {attrs}"