from odoo import models, fields


class ProductAttributeInherit(models.Model):
    _inherit = 'product.attribute'

    show_in_description = fields.Boolean(
        string='Mostrar en Descripción',
        default=True,
        help='Si está activo, este atributo aparecerá en la descripción de la línea '
             'al confirmar la configuración en la cotización. '
             'Si está desactivado, la línea se ocultará en el wizard cuando sea opción única.')
