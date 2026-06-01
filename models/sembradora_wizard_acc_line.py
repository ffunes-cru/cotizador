from odoo import models, fields


class SembradoraWizardAccSelection(models.TransientModel):
    _name = 'sembradora.config.wizard.acc.selection'
    _description = 'Selección de Accesorio en Wizard'

    wizard_id = fields.Many2one('sembradora.config.wizard', ondelete='cascade')

    # Referencia a la línea de accesorio de la configuración (tiene producto + precio)
    config_acc_line_id = fields.Many2one(
        'sembradora.config.accessory.line',
        string='Línea Accesorio Config')

    product_id = fields.Many2one(
        'product.product',
        related='config_acc_line_id.product_id',
        string='Accesorio',
        readonly=True)

    price = fields.Float(
        related='config_acc_line_id.price',
        string='Precio',
        readonly=True)

    # Cantidad predefinida desde la configuración (fallback)
    config_quantity = fields.Float(
        related='config_acc_line_id.quantity',
        string='Cant. Config',
        readonly=True)

    selected = fields.Boolean(string='Seleccionar', default=False)