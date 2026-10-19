"""@file
Línea de accesorio de una configuración: precio, reglas y marca de equipamiento estándar."""
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class SembradoraConfigAccessoryLine(models.Model):
    """Accesorio compatible con una configuración (`sembradora.config.accessory.line`).

    El precio vive acá (no en el producto): el mismo accesorio puede costar distinto en cada
    configuración. El accesorio pertenece al mismo modelo de máquina que la configuración
    (_check_product_modelo()).
    """
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

    quantity = fields.Float(
        string='Cantidad (opcional)',
        default=0,
        help='Si se especifica (> 0), se usa esta cantidad. '
             'Si se deja en 0, se calcula dinámicamente según la configuración.')

    @api.constrains('product_id', 'config_id')
    def _check_product_modelo(self):
        """El accesorio debe ser del mismo modelo de máquina que la configuración.

        También la llaman las restricciones de product.template (al cambiar el modelo de un
        accesorio) y de sembradora.config.rel (al cambiar el modelo de una configuración).

        @throws ValidationError Si `product_id.cotizador_modelo_id` no es `config_id.modelo_id`.
        """
        for line in self:
            if line.product_id.cotizador_modelo_id != line.config_id.modelo_id:
                raise ValidationError(
                    f"El accesorio '{line.product_id.display_name}' pertenece al modelo "
                    f"'{line.product_id.cotizador_modelo_id.name or 'ninguno'}' y no puede usarse en una "
                    f"configuración de '{line.config_id.modelo_id.name}'. Cada accesorio es de un único modelo "
                    f"(campo Modelo de Máquina del producto)."
                )
