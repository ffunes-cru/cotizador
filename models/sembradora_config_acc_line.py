from odoo import api, fields, models
from odoo.exceptions import ValidationError


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

    currency_id = fields.Many2one(related='product_id.cotizador_currency_id', string='Moneda')
    price = fields.Monetary(string='Precio en esta Configuración',
                            help='En la Moneda del Cotizador del accesorio.')

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

    @api.constrains('product_id', 'config_id')
    def _check_product_modelo(self):
        for line in self:
            if line.product_id.cotizador_modelo_id != line.config_id.modelo_id:
                raise ValidationError(
                    f"El accesorio '{line.product_id.display_name}' pertenece al modelo "
                    f"'{line.product_id.cotizador_modelo_id.name or 'ninguno'}' y no puede usarse en una "
                    f"configuración de '{line.config_id.modelo_id.name}'. Cada accesorio es de un único modelo "
                    f"(campo Modelo de Máquina del producto)."
                )
