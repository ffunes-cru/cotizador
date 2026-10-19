from odoo import models, fields


class ProductAttributeInherit(models.Model):
    _inherit = 'product.attribute'
    show_incompatible_alternatives = fields.Boolean(
        string='Mostrar Alternativas Incompatibles',
        default=True,
        help='Si está activo, se mostraran las alternativas incompatibles en el wizard de configuración.')
    show_in_description = fields.Boolean(
        string='Mostrar en Descripción',
        default=True,
        help='Si está activo, este atributo aparecerá en la descripción de la línea '
             'al confirmar la configuración en la cotización. '
             'Si está desactivado, la línea se ocultará en el wizard cuando sea opción única.')


class ProductAttributeValue(models.Model):
    _inherit = 'product.attribute.value'

    cotizador_qty = fields.Float(
        string='Cantidad (Cotizador)',
        help='Multiplicador de los accesorios que se cotizan por este atributo (categoría con '
             'Atributo de Cantidad). El importador lo toma del número del valor: "16 Líneas" → 16.')
