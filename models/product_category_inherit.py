from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ProductCategory(models.Model):
    _inherit = 'product.category'

    cotizador_qty_attribute_id = fields.Many2one(
        'product.attribute',
        string='Atributo de Cantidad (Cotizador)',
        ondelete='restrict',
        help='Los accesorios de esta categoría se cotizan multiplicando su precio por el número '
             'del valor de este atributo en la configuración (p.ej. "16 Líneas" → 16). '
             'El importador lo completa a partir de la columna Calc_param.',
    )

    @api.constrains('cotizador_qty_attribute_id')
    def _check_cotizador_qty_attribute_unique(self):
        """Un atributo de cantidad corresponde a una única categoría (relación 1:1 coherente)."""
        for categ in self.filtered('cotizador_qty_attribute_id'):
            other = self.search([
                ('cotizador_qty_attribute_id', '=', categ.cotizador_qty_attribute_id.id),
                ('id', '!=', categ.id),
            ], limit=1)
            if other:
                raise ValidationError(self.env._(
                    "El atributo '%(attr)s' ya es el atributo de cantidad de la categoría '%(categ)s'.",
                    attr=categ.cotizador_qty_attribute_id.name, categ=other.complete_name,
                ))
