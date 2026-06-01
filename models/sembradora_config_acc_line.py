from odoo import models, fields


class SembradoraConfigAccessoryLine(models.Model):
    _name = 'sembradora.config.accessory.line'
    _description = 'Accesorio por Configuración con Precio'

    ext_id = fields.Char(string='ID Externo', readonly=False)

    config_id = fields.Many2one(
        'sembradora.config.rel',
        string='Configuración',
        required=True,
        ondelete='cascade')

    product_id = fields.Many2one(
        'product.product',
        string='Accesorio',
        required=True,
        domain=[("categ_id.name", "=", "Accesorio")])

    price = fields.Float(string='Precio en esta Configuración')

    # Campo opcional: cantidad del accesorio para esta configuración.
    # Si se deja en 0 o vacío, se usa la lógica dinámica (get_acc_quan).
    quantity = fields.Float(
        string='Cantidad (opcional)',
        default=0,
        help='Si se especifica (> 0), se usa esta cantidad. '
             'Si se deja en 0, se calcula dinámicamente según la configuración.')
