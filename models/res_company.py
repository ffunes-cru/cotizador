"""@file
Ajustes del cotizador que dependen de la compañía (Ajustes › Ventas › Cotizador de Sembradoras)."""
from odoo import fields, models


class ResCompany(models.Model):
    """Compañía (`res.company`): impuesto y lista de precios de las cotizaciones de máquinas.

    Se editan desde res.config.settings con campos *related*.
    """
    _inherit = 'res.company'

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
