from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    def _default_cotizador_matrix_currency(self):
        return self.env.ref('base.USD', raise_if_not_found=False)

    cotizador_matrix_currency_id = fields.Many2one(
        'res.currency',
        string='Moneda de la Matriz',
        default=_default_cotizador_matrix_currency,
        required=True,
        help='Moneda en la que están cargados los precios de configuraciones y accesorios '
             '(columnas Precio_Base y Precio_Item del importador).',
    )
    cotizador_tax_id = fields.Many2one(
        'account.tax',
        string='Impuesto de Maquinaria',
        domain="[('type_tax_use', '=', 'sale'), ('company_id', 'parent_of', id)]",
        help='Impuesto que se aplica a máquinas y accesorios cotizados con el configurador. '
             'Si se deja vacío se usan los impuestos de cada producto.',
    )
    cotizador_pricelist_id = fields.Many2one(
        'product.pricelist',
        string='Lista de Precios de Cotizaciones',
        help='Lista de precios de las cotizaciones de máquinas (backend y solicitudes web). '
             'Si se deja vacía se usa la lista habitual del cliente.',
    )
