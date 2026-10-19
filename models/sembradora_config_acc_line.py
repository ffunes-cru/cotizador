from odoo import fields, models


class SembradoraConfigAccessoryLine(models.Model):
    _name = 'sembradora.config.accessory.line'
    _description = 'Accesorio por Configuración con Precio'

    config_id = fields.Many2one(
        'sembradora.config.rel',
        string='Configuración',
        required=True,
        ondelete='cascade')

    product_id = fields.Many2one(
        'product.product',
        string='Accesorio',
        required=True,
        domain=[('is_accesorio', '=', True)])

    price = fields.Float(string='Precio en esta Configuración')

    # Relación Many2many directa con reglas
    rule_ids = fields.Many2many(
        'sembradora.accessory.rule',
        string='Reglas')

    is_trigger = fields.Boolean(
        string='Es Trigger',
        default=False,
        help='Indica si este accesorio habilita a los demás accesorios '
             'pertenecientes a sus reglas de inclusión al ser seleccionado.')

    is_standard = fields.Boolean(
        string='Estándar',
        default=False,
        help='Equipamiento estándar de la configuración: el accesorio aparece '
             'seleccionado por defecto en el configurador (el vendedor puede quitarlo). '
             'En el CSV se indica con Tipo_Item = ESTANDAR.')

    # Campo opcional: cantidad del accesorio para esta configuración.
    # Si se deja en 0 o vacío, se usa la lógica dinámica (sembradora.config.rel._get_accessory_offer).
    quantity = fields.Float(
        string='Cantidad (opcional)',
        default=0,
        help='Si se especifica (> 0), se usa esta cantidad. '
             'Si se deja en 0, se calcula dinámicamente según la configuración.')
