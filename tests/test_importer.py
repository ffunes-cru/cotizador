from markupsafe import escape

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.cotizador.models.sembradora_import_wizard import parse_price

from .common import HEADER, MATRIX_CSV, CotizadorCase


@tagged('post_install', '-at_install')
class TestImporter(CotizadorCase):

    def assertAnalysisError(self, csv_text, message):
        wizard = self._wizard(csv_text)
        self.assertTrue(wizard.has_errors)
        self.assertIn(escape(message), wizard.analysis_summary)
        with self.assertRaises(UserError):
            wizard.action_import()

    def test_parse_price(self):
        cases = {
            'USD $248.866,00': 248866.0, '248866,5': 248866.5, '248.866': 248866.0,
            '248866.00': 248866.0, '248,866.00': 248866.0, '1500': 1500.0, '': None, 'abc': None,
        }
        for raw, expected in cases.items():
            self.assertEqual(parse_price(raw), expected, raw)

    def test_import_end_to_end(self):
        wizard = self._import(MATRIX_CSV)
        self.assertIn('Configuraciones creadas / actualizadas: <b>2</b> / <b>0</b>', wizard.analysis_summary)
        config = self._imported('cfg_pionera_001')
        self.assertEqual(config.price, 1000.0)
        self.assertTrue(config.modelo_id.is_maquina)
        self.assertEqual(sorted(config.value_ids.mapped('name')), ['16 Lineas', '52 cm'])

        lines = self._lines(config)
        self.assertEqual({n for n, l in lines.items() if l.is_standard}, {'Monitor', 'Kit Fino'})
        self.assertTrue(lines['Monitor'].is_trigger)
        self.assertEqual(lines['Kit Grueso'].rule_ids.rule_type, 'choice')

        # Calc_param: categoría vinculada al atributo y cantidad guardada en cada valor
        sensor = lines['Sensor'].product_id
        self.assertTrue(sensor.is_accesorio)
        self.assertEqual(sensor.categ_id.cotizador_qty_attribute_id, self._imported('attr_lineas'))
        self.assertEqual(self._imported('val_lineas_16_lineas').cotizador_qty, 16.0)
        self.assertEqual(self._imported('val_lineas_18_lineas').cotizador_qty, 18.0)

    def test_reimport_uses_xmlids_not_names(self):
        self._import(MATRIX_CSV)
        monitor = self._imported('acc_monitor')
        monitor.name = 'Monitor renombrado en Odoo'
        self._imported('modelo_pionera').name = 'Pionera II'
        counts = {model: self.env[model].search_count([]) for model in (
            'product.template', 'product.category', 'product.attribute.value', 'sembradora.accessory.rule')}

        # Se quita Cuchilla B de la 001 y se re-importa
        wizard = self._import(MATRIX_CSV.replace("001,Pionera,OPCIONAL,,Cuchilla B,25,,Cuchillas:e,,,\n", ""))
        self.assertIn('Configuraciones creadas / actualizadas: <b>0</b> / <b>2</b>', wizard.analysis_summary)
        for model, count in counts.items():
            self.assertEqual(self.env[model].search_count([]), count, model)
        config = self._imported('cfg_pionera_001')
        self.assertEqual(config.modelo_id.name, 'Pionera II')
        self.assertIn(monitor, config.accessory_line_ids.product_id)
        self.assertNotIn('Cuchilla B', config.accessory_line_ids.product_id.mapped('name'))

    def test_format_errors(self):
        self.assertAnalysisError(MATRIX_CSV.replace('ATR_Distancia', 'Distancia'), 'columnas desconocidas Distancia')
        self.assertAnalysisError(MATRIX_CSV.replace('Cuchillas:e', 'Cuchillas'), "regla 'Cuchillas' inválida")
        self.assertAnalysisError(MATRIX_CSV.replace(',ESTANDAR,,Monitor', ',STD,,Monitor'), "Tipo_Item 'STD' inválido")
        self.assertAnalysisError(MATRIX_CSV.replace('ATR_Lineas,Monitor:i', 'Lineas,Monitor:i'),
                                 "Calc_param 'Lineas' debe ser el nombre exacto")
        self.assertAnalysisError(MATRIX_CSV.replace('16 Lineas', 'dieciseis'), "el valor 'dieciseis' no contiene un número")
        self.assertAnalysisError(MATRIX_CSV.replace('"USD $1.000,00"', 'consultar'), "Precio_Base 'consultar'")
        self.assertAnalysisError(HEADER + "009,Pionera,OPCIONAL,,Kit,10,,,,,\n", 'no tiene fila BASE')
        self.assertAnalysisError(MATRIX_CSV.replace('18 Lineas', '16 Lineas'), 'misma combinación de atributos')
        self.assertAnalysisError(MATRIX_CSV.replace('Cuchilla B', 'cuchilla-a'), 'son indistinguibles')

    def test_rule_coherence_errors(self):
        # Opción única sin estándar / con dos estándar
        self.assertAnalysisError(MATRIX_CSV.replace(',ESTANDAR,,Kit Fino,50', ',OPCIONAL,,Kit Fino,50'),
                                 "'Kit Siembra' debe tener exactamente un accesorio ESTANDAR (tiene 0)")
        self.assertAnalysisError(MATRIX_CSV.replace(',OPCIONAL,,Kit Mixto', ',ESTANDAR,,Kit Mixto'),
                                 '(tiene 2)')
        # Un miembro de opción única no puede tener otras reglas
        self.assertAnalysisError(MATRIX_CSV.replace('Kit Mixto,30,,Kit Siembra:u', 'Kit Mixto,30,,Kit Siembra:u|Cuchillas:e'),
                                 'no puede tener otras reglas')
        # Dos estándar en un grupo de exclusión
        self.assertAnalysisError(MATRIX_CSV.replace(',OPCIONAL,,Cuchilla A', ',ESTANDAR,,Cuchilla A')
                                           .replace(',OPCIONAL,,Cuchilla B', ',ESTANDAR,,Cuchilla B'),
                                 "exclusión 'Cuchillas' tiene más de un accesorio ESTANDAR")
        # Estándar que depende de un trigger no estándar
        self.assertAnalysisError(MATRIX_CSV.replace(',ESTANDAR,,Monitor', ',OPCIONAL,,Monitor')
                                           .replace(',OPCIONAL,,Sensor', ',ESTANDAR,,Sensor'),
                                 "cuyo accesorio habilitante (:it) no es ESTANDAR")

    def test_manual_rule_with_same_name_blocks_import(self):
        self.env['sembradora.accessory.rule'].create({'name': 'Cuchillas', 'rule_type': 'exclusion'})
        wizard = self._wizard(MATRIX_CSV)
        with self.assertRaisesRegex(UserError, 'creada fuera del importador'):
            wizard.action_import()
