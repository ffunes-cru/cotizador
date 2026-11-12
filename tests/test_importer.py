from markupsafe import escape

from odoo import Command
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from odoo.addons.cotizador.models.sembradora_import_wizard import parse_price

from .common import HEADER, MATRIX_CSV, CotizadorCase

# Segundo modelo con accesorios del mismo nombre que Pionera
DRILLA_CSV = """\
Drilla,BASE,500,,,,,,16 Lineas,70 cm
Drilla,ESTANDAR,,Monitor,90,,,,,
Drilla,OPCIONAL,,Sensor,12,ATR_Lineas,,,,
"""


@tagged('post_install', '-at_install')
class TestImporter(CotizadorCase):

    def assertAnalysisError(self, csv_text, message, currency=None):
        wizard = self._wizard(csv_text, currency)
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
        self.assertIn('Configuraciones nuevas: <b>2</b>', wizard.analysis_summary)
        config = self._config('Pionera', '16 Lineas', '52 cm')
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

        # Moneda elegida en el importador → Moneda del Cotizador de modelos y accesorios
        self.assertEqual(config.modelo_id.cotizador_currency_id, self.usd)
        self.assertEqual(sensor.cotizador_currency_id, self.usd)
        self.assertEqual(sensor.cotizador_modelo_id, config.modelo_id)

    def test_accessories_are_unique_per_model(self):
        self._import(MATRIX_CSV + DRILLA_CSV)
        pionera, drilla = self._imported('modelo_pionera'), self._imported('modelo_drilla')
        monitor_p, monitor_d = self._imported('acc_pionera_monitor'), self._imported('acc_drilla_monitor')
        self.assertNotEqual(monitor_p, monitor_d)
        self.assertEqual((monitor_p.cotizador_modelo_id, monitor_d.cotizador_modelo_id), (pionera, drilla))
        self.assertEqual(self._config('Drilla', '16 Lineas', '70 cm').accessory_line_ids.product_id,
                         monitor_d | self._imported('acc_drilla_sensor'))

        # El accesorio de un modelo no se puede usar en configuraciones de otro
        with self.assertRaisesRegex(ValidationError, 'pertenece al modelo'):
            self._config('Drilla', '16 Lineas', '70 cm').accessory_line_ids = [Command.create({'product_id': monitor_p.id})]
        with self.assertRaisesRegex(ValidationError, 'pertenece al modelo'):
            monitor_p.cotizador_modelo_id = drilla

    def test_price_currency_must_match(self):
        eur = self.env.ref('base.EUR')
        eur.active = True
        self.assertAnalysisError(MATRIX_CSV, "está en USD, pero la moneda de los precios elegida es EUR", eur)

    def test_reimport_uses_xmlids_not_names(self):
        self._import(MATRIX_CSV)
        monitor = self._imported('acc_pionera_monitor')
        monitor.name = 'Monitor renombrado en Odoo'
        self._imported('modelo_pionera').name = 'Pionera II'
        counts = {model: self.env[model].search_count([]) for model in (
            'product.template', 'product.category', 'product.attribute.value', 'sembradora.accessory.rule')}

        # Se quita Cuchilla B de la 001 (la única configuración que la usa) y se re-importa
        cuchilla_b = self._imported('acc_pionera_cuchilla_b')
        wizard = self._import(MATRIX_CSV.replace("Pionera,OPCIONAL,,Cuchilla B,25,,Cuchillas:e,,,\n", ""))
        self.assertIn('Configuraciones modificadas: <b>1</b>', wizard.analysis_summary)
        self.assertFalse(cuchilla_b.active)  # ya no está en el CSV: se archiva
        counts['product.template'] -= 1
        for model, count in counts.items():
            self.assertEqual(self.env[model].search_count([]), count, model)
        config = self._config('Pionera', '16 Lineas', '52 cm')
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
        self.assertAnalysisError(HEADER + "Pionera,OPCIONAL,,Kit,10,,,,,\n", 'el accesorio no tiene una fila BASE antes')
        self.assertAnalysisError(MATRIX_CSV.replace('18 Lineas', '16 Lineas'), 'ya está en otra fila BASE')
        self.assertAnalysisError(MATRIX_CSV.replace('Cuchilla B', 'cuchilla-a'), 'son indistinguibles')

    def test_rule_coherence_errors(self):
        # Opción única sin estándar / con dos estándar
        self.assertAnalysisError(MATRIX_CSV.replace(',ESTANDAR,,Kit Fino,50', ',OPCIONAL,,Kit Fino,50'),
                                 "'Kit Siembra' debe tener exactamente un accesorio ESTANDAR (tiene 0)")
        self.assertAnalysisError(MATRIX_CSV.replace(',OPCIONAL,,Kit Mixto', ',ESTANDAR,,Kit Mixto'),
                                 '(tiene 2)')
        # Un miembro de opción única puede estar en una exclusión (MATRIX_CSV), pero no en una inclusión
        self.assertAnalysisError(MATRIX_CSV.replace('Kit Siembra:u|Cuchillas:e', 'Kit Siembra:u|Monitor:i'),
                                 'solo puede estar en grupos de exclusión')
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

    def test_orphan_identifier_is_reused(self):
        """Un atributo borrado deja los xmlids de sus valores sin registro: se reutilizan."""
        self._import(MATRIX_CSV)
        distancia = self._imported('attr_distancia')
        self.env['sembradora.config.rel'].search([]).unlink()
        self._imported('modelo_pionera').unlink()
        distancia.unlink()  # sus valores se borran en cascada en la base, sin borrar sus xmlids
        orphan = self.env['ir.model.data'].search([('module', '=', 'cotizador_import'), ('name', '=', 'val_distancia_52_cm')])
        self.assertTrue(orphan)
        self.assertFalse(self.env.ref('cotizador_import.val_distancia_52_cm', raise_if_not_found=False))

        self._import(MATRIX_CSV)
        value = self._imported('val_distancia_52_cm')
        self.assertEqual(value.name, '52 cm')
        self.assertEqual(value.attribute_id, self._imported('attr_distancia'))
        self.assertEqual(orphan.res_id, value.id)

    def test_reimport_replaces_lines_with_accessories_of_another_criterion(self):
        """Re-importar sobre líneas cuyo accesorio no es del modelo (criterio anterior) las reemplaza."""
        self._import(MATRIX_CSV)
        config = self._config('Pionera', '16 Lineas', '52 cm')
        old_monitor = self._imported('acc_pionera_monitor')
        # Como lo dejaba la versión anterior: accesorio compartido (sin modelo) y xmlid sin modelo
        self.env.cr.execute("UPDATE product_template SET cotizador_modelo_id = NULL WHERE id = %s",
                            [old_monitor.product_tmpl_id.id])
        self.env.cr.execute("UPDATE ir_model_data SET name = 'acc_monitor' "
                            "WHERE module = 'cotizador_import' AND name = 'acc_pionera_monitor'")
        self.env.invalidate_all()
        self.env.registry.clear_cache()

        self._import(MATRIX_CSV)
        monitor_line = config.accessory_line_ids.filtered(lambda l: l.product_id.name == 'Monitor')
        self.assertNotEqual(monitor_line.product_id, old_monitor)
        self.assertEqual(monitor_line.product_id.cotizador_modelo_id, config.modelo_id)
