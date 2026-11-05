from odoo.tests import TransactionCase

HEADER = "ID_Configuracion,Modelo,Tipo_Item,Precio_Base,Nombre_Item,Precio_Item,Calc_param,Reglas,Descripcion,ATR_Lineas,ATR_Distancia\n"

# Pionera 001: Monitor (estándar, habilita Sensor), Sensor por línea, grupo de opción única
# "Kit Siembra" (Fino estándar; Grueso y Mixto alternativas) y grupo exclusivo "Cuchillas" (Cuchilla A,
# Cuchilla B y la alternativa Kit Mixto: una opción única también puede estar en una exclusión).
MATRIX_CSV = HEADER + """\
001,Pionera,BASE,"USD $1.000,00",,,,,,16 Lineas,52 cm
001,Pionera,ESTANDAR,,Monitor,100,,Monitor:it,,,
001,Pionera,OPCIONAL,,Sensor,10,ATR_Lineas,Monitor:i,,,
001,Pionera,ESTANDAR,,Kit Fino,50,,Kit Siembra:u,,,
001,Pionera,OPCIONAL,,Kit Grueso,80,,Kit Siembra:u,,,
001,Pionera,OPCIONAL,,Kit Mixto,30,,Kit Siembra:u|Cuchillas:e,,,
001,Pionera,OPCIONAL,,Cuchilla A,20,,Cuchillas:e,,,
001,Pionera,OPCIONAL,,Cuchilla B,25,,Cuchillas:e,,,
002,Pionera,BASE,2000,,,,,,18 Lineas,52 cm
002,Pionera,ESTANDAR,,Kit Fino,55,,Kit Siembra:u,,,
002,Pionera,OPCIONAL,,Kit Grueso,85,,Kit Siembra:u,,,
"""


def analyze_matrix(env, csv_text, currency=None):
    attachment = env['ir.attachment'].create({'name': 'matriz.csv', 'raw': csv_text.encode()})
    wizard = env['sembradora.import.wizard'].create({
        'csv_file_ids': [(6, 0, attachment.ids)],
        'currency_id': (currency or env.ref('base.USD')).id,
    })
    wizard.action_analyze()
    return wizard


def import_matrix(env, csv_text, currency=None):
    wizard = analyze_matrix(env, csv_text, currency)
    assert not wizard.has_errors, wizard.analysis_summary
    wizard.action_import()
    return wizard


class CotizadorCase(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.usd = cls.env.ref('base.USD')
        cls.env.company.cotizador_tax_id = False
        cls.pricelist = cls.env['product.pricelist'].create({'name': 'Cotizador USD', 'currency_id': cls.usd.id})
        cls.partner = cls.env['res.partner'].create({'name': 'Cliente Test'})

    @classmethod
    def _wizard(cls, csv_text, currency=None):
        return analyze_matrix(cls.env, csv_text, currency)

    @classmethod
    def _import(cls, csv_text, currency=None):
        return import_matrix(cls.env, csv_text, currency)

    @classmethod
    def _imported(cls, xmlid_name):
        return cls.env.ref(f'cotizador_import.{xmlid_name}')

    def _order(self, **vals):
        return self.env['sale.order'].create({'partner_id': self.partner.id, 'pricelist_id': self.pricelist.id, **vals})

    def _lines(self, config):
        return {line.product_id.name: line for line in config.accessory_line_ids}
