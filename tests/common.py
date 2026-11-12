from odoo.tests import TransactionCase

HEADER = "Modelo,Tipo_Item,Precio_Base,Nombre_Item,Precio_Item,Calc_param,Reglas,Descripcion,ATR_Lineas,ATR_Distancia\n"

# Pionera 16 líneas: Monitor (estándar, habilita Sensor), Sensor por línea, grupo de opción única
# "Kit Siembra" (Fino estándar; Grueso y Mixto alternativas) y grupo exclusivo "Cuchillas" (Cuchilla A,
# Cuchilla B y la alternativa Kit Mixto: una opción única también puede estar en una exclusión).
MATRIX_CSV = HEADER + """\
Pionera,BASE,"USD $1.000,00",,,,,,16 Lineas,52 cm
Pionera,ESTANDAR,,Monitor,100,,Monitor:it,,,
Pionera,OPCIONAL,,Sensor,10,ATR_Lineas,Monitor:i,,,
Pionera,ESTANDAR,,Kit Fino,50,,Kit Siembra:u,,,
Pionera,OPCIONAL,,Kit Grueso,80,,Kit Siembra:u,,,
Pionera,OPCIONAL,,Kit Mixto,30,,Kit Siembra:u|Cuchillas:e,,,
Pionera,OPCIONAL,,Cuchilla A,20,,Cuchillas:e,,,
Pionera,OPCIONAL,,Cuchilla B,25,,Cuchillas:e,,,
Pionera,BASE,2000,,,,,,18 Lineas,52 cm
Pionera,ESTANDAR,,Kit Fino,55,,Kit Siembra:u,,,
Pionera,OPCIONAL,,Kit Grueso,85,,Kit Siembra:u,,,
"""


def find_config(env, modelo, *values):
    """Configuración importada de una máquina por su combinación de valores.

    @param env Entorno.
    @param modelo Nombre de la máquina en el CSV.
    @param values Nombres de los valores de atributo.
    @return sembradora.config.rel (vacío si no existe).
    """
    tmpl = env.ref(f"cotizador_import.modelo_{modelo.lower()}")
    return env['sembradora.config.rel'].search([('modelo_id', '=', tmpl.id)]).filtered(
        lambda config: set(config.value_ids.mapped('name')) == set(values))


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
    def _config(cls, modelo, *values):
        return find_config(cls.env, modelo, *values)

    @classmethod
    def _imported(cls, xmlid_name):
        return cls.env.ref(f'cotizador_import.{xmlid_name}')

    def _order(self, **vals):
        return self.env['sale.order'].create({'partner_id': self.partner.id, 'pricelist_id': self.pricelist.id, **vals})

    def _lines(self, config):
        return {line.product_id.name: line for line in config.accessory_line_ids}
