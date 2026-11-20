"""@file
Análisis de ventas por CUIT: el mismo cliente puede tener una ficha en cada concesionario (models/res_partner.py), y
agrupar por *Cliente* lo mostraría partido. El CUIT va sin guiones para que coincida aunque se haya cargado distinto.
"""
from odoo import fields, models


class SaleReport(models.Model):
    """Análisis de ventas (`sale.report`) con el CUIT del cliente."""
    _inherit = 'sale.report'

    cotizador_cuit = fields.Char(string='CUIT', readonly=True)

    def _select_additional_fields(self):
        """Agrega el CUIT del cliente, solo con dígitos.

        @return dict campo → expresión SQL.
        """
        res = super()._select_additional_fields()
        res['cotizador_cuit'] = "NULLIF(regexp_replace(partner.vat, '[^0-9]', '', 'g'), '')"
        return res

    def _group_by_sale(self):
        """Agrupa también por el CUIT del cliente.

        @return str con el GROUP BY.
        """
        return super()._group_by_sale() + """,
            partner.vat"""
