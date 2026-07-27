from odoo import models, fields, api


class SembradoraWizardAccSelection(models.TransientModel):
    _name = 'sembradora.config.wizard.acc.selection'
    _description = 'Selección de Accesorio en Wizard'

    wizard_id = fields.Many2one('sembradora.config.wizard', ondelete='cascade')

    config_acc_line_id = fields.Many2one(
        'sembradora.config.accessory.line',
        string='Línea Accesorio Config')

    product_id = fields.Many2one(
        'product.product',
        related='config_acc_line_id.product_id',
        string='Accesorio',
        readonly=True)

    rule_ids = fields.Many2many(
        'sembradora.accessory.rule',
        related='config_acc_line_id.rule_ids',
        readonly=True)

    is_trigger = fields.Boolean(
        related='config_acc_line_id.is_trigger',
        readonly=True)

    price = fields.Float(string='Subtotal', digits='Product Price', compute='_compute_price', store=True)
    quantity = fields.Float(string='Cantidad', default=1.0)
    price_unit = fields.Float(string='Precio Unitario')

    is_locked = fields.Boolean(string='Bloqueado', default=False)

    is_inclusion_locked = fields.Boolean(
        string='Bloqueado por Inclusión',
        default=False,
        help='True si este accesorio pertenece a un grupo de inclusión '
             'y su trigger no está seleccionado.')

    selected = fields.Boolean(string='Seleccionar', default=False)

    @api.depends('price_unit', 'quantity')
    def _compute_price(self):
        for line in self:
            line.price = line.price_unit * line.quantity