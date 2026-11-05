"""@file
Tests del importador como espejo del CSV: lo que sale del archivo se borra (configuraciones,
valores de atributo, reglas sin uso) o se archiva (accesorios), las máquinas que no están no se
tocan, y el detalle de cambios se muestra antes de importar y queda en el chatter."""
from markupsafe import escape

from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import HEADER, MATRIX_CSV, CotizadorCase

## La matriz de ejemplo con cambios: precio de la 001 y de su Kit Fino, sin Cuchilla B, sin la 002
## y con una 003 nueva (20 líneas).
CHANGED_CSV = (
    MATRIX_CSV
    .replace('"USD $1.000,00"', '"USD $1.100,00"')
    .replace('001,Pionera,ESTANDAR,,Kit Fino,50,', '001,Pionera,ESTANDAR,,Kit Fino,60,')
    .replace('001,Pionera,OPCIONAL,,Cuchilla B,25,,Cuchillas:e,,,\n', '')
    .split('002,Pionera,BASE')[0]
    + '003,Pionera,BASE,3000,,,,,,20 Lineas,52 cm\n'
    + '003,Pionera,ESTANDAR,,Kit Fino,70,,Kit Siembra:u,,,\n'
)

## Segunda máquina, con un accesorio en el grupo de exclusión "Cuchillas".
DRILLA_CSV = """\
100,Drilla,BASE,500,,,,,,16 Lineas,70 cm
100,Drilla,ESTANDAR,,Monitor,90,,,,,
100,Drilla,OPCIONAL,,Cuchilla D,10,,Cuchillas:e,,,
"""


@tagged('post_install', '-at_install')
class TestImportMirror(CotizadorCase):
    """Cada máquina del CSV queda igual al archivo."""

    @classmethod
    def setUpClass(cls):
        """Matriz de ejemplo importada (Pionera 001 y 002)."""
        super().setUpClass()
        cls._import(MATRIX_CSV)
        cls.pionera = cls._imported('modelo_pionera')

    def _exists(self, xmlid_name):
        """@param xmlid_name Nombre del xmlid del importador.
        @return El registro, o None si se borró."""
        return self.env.ref(f'cotizador_import.{xmlid_name}', raise_if_not_found=False)

    def assertSummary(self, wizard, *texts):
        """Cada texto aparece en el resumen del asistente (escapado como en el HTML).

        @param wizard Asistente.
        @param texts Textos esperados.
        """
        for text in texts:
            self.assertIn(escape(text), wizard.analysis_summary)

    def test_analysis_details_every_change_without_writing(self):
        """El análisis detalla precios, accesorios, configuraciones y valores, y no escribe nada."""
        config_002 = self._imported('cfg_pionera_002')
        wizard = self._wizard(CHANGED_CSV)
        amount = wizard._amount
        self.assertFalse(wizard.has_errors)
        self.assertSummary(
            wizard,
            f"Precio: {amount(1000)} → {amount(1100)}",
            f"Kit Fino: precio {amount(50)} → {amount(60)}",
            "− Cuchilla B",
            f"002 · {config_002.name}",
            "Lineas: + 20 Lineas",
            "Lineas: − 18 Lineas",
            "Cuchilla B",
        )
        self.assertIn('Configuraciones nuevas: <b>1</b>', wizard.analysis_summary)
        self.assertIn('Configuraciones que se borran: <b>1</b>', wizard.analysis_summary)
        self.assertIn('Se van a borrar configuraciones: <b>1</b>', wizard.analysis_summary)
        self.assertIn('Accesorios que se archivan (ya no están en el CSV): <b>1</b>', wizard.analysis_summary)
        # Nada se escribió todavía
        self.assertTrue(config_002.exists())
        self.assertEqual(self._imported('cfg_pionera_001').price, 1000.0)

    def test_import_leaves_the_machine_equal_to_the_csv(self):
        """Después de importar, la Pionera es exactamente el CSV."""
        variant_002 = self._imported('cfg_pionera_002')._get_variant()
        cuchilla_b = self._imported('acc_pionera_cuchilla_b')
        before = self.pionera.message_ids
        wizard = self._import(CHANGED_CSV)

        self.assertIsNone(self._exists('cfg_pionera_002'))
        config_001, config_003 = self._imported('cfg_pionera_001'), self._imported('cfg_pionera_003')
        self.assertEqual((config_001.price, config_003.price), (1100.0, 3000.0))
        kit_fino = config_001.accessory_line_ids.filtered(lambda l: l.product_id.name == 'Kit Fino')
        self.assertEqual(kit_fino.price, 60.0)
        self.assertNotIn(cuchilla_b, config_001.accessory_line_ids.product_id)
        self.assertFalse(cuchilla_b.active)
        lineas = self.pionera.attribute_line_ids.filtered(lambda l: l.attribute_id == self._imported('attr_lineas'))
        self.assertEqual(set(lineas.value_ids.mapped('name')), {'16 Lineas', '20 Lineas'})
        # Una variante por configuración: la de la 002 ya no está activa
        self.assertEqual(len(self.pionera.product_variant_ids), 2)
        self.assertFalse(variant_002.exists() and variant_002.active)

        # El log: en el asistente y en el chatter de la máquina
        self.assertSummary(wizard, "Importación completada", f"Precio: {wizard._amount(1000)} → {wizard._amount(1100)}")
        log = self.pionera.message_ids - before
        self.assertEqual(len(log), 1)
        self.assertIn('Importación de la matriz', log.body)
        self.assertIn('Configuraciones que se borran', log.body)

    def test_unchanged_csv_changes_nothing(self):
        """Re-importar el mismo CSV no escribe nada ni deja mensaje en el chatter."""
        messages = len(self.pionera.message_ids)
        lines = self.env['sembradora.config.accessory.line'].search([])
        wizard = self._import(MATRIX_CSV)
        self.assertNotIn('Configuraciones modificadas', wizard.analysis_summary)
        self.assertNotIn('se borran', wizard.analysis_summary)
        self.assertEqual(len(self.pionera.message_ids), messages)
        self.assertEqual(self.env['sembradora.config.accessory.line'].search([]), lines)  # no se recrearon

    def test_price_change_keeps_accessory_lines(self):
        """Si solo cambia el precio de la máquina, las líneas de accesorio no se reescriben."""
        config = self._imported('cfg_pionera_001')
        lines = config.accessory_line_ids
        self._import(MATRIX_CSV.replace('"USD $1.000,00"', '"USD $1.100,00"'))
        self.assertEqual(config.price, 1100.0)
        self.assertEqual(config.accessory_line_ids, lines)

    def test_duplicate_combination_is_rejected(self):
        """La restricción de combinación única (una consulta SQL) rechaza una combinación repetida."""
        config = self._imported('cfg_pionera_001')
        with self.assertRaisesRegex(ValidationError, 'misma combinación'):
            self.env['sembradora.config.rel'].create({
                'modelo_id': self.pionera.id, 'price': 1, 'value_ids': [Command.set(config.value_ids.ids)],
            })

    def test_archived_accessory_is_restored(self):
        """Un accesorio que vuelve al CSV se reactiva: es el mismo producto."""
        cuchilla_b = self._imported('acc_pionera_cuchilla_b')
        self._import(CHANGED_CSV)
        self.assertFalse(cuchilla_b.active)
        wizard = self._import(MATRIX_CSV)
        self.assertTrue(cuchilla_b.active)
        self.assertIn('Accesorios que se reactivan: <b>1</b>', wizard.analysis_summary)
        self.assertIn(cuchilla_b, self._imported('cfg_pionera_001').accessory_line_ids.product_id)

    def test_machines_not_in_the_file_are_untouched(self):
        """Importar el CSV de una máquina no toca a las demás."""
        self._import(MATRIX_CSV + DRILLA_CSV)
        pionera_configs = self.env['sembradora.config.rel'].search([('modelo_id', '=', self.pionera.id)])
        wizard = self._import(HEADER + DRILLA_CSV.replace('100,Drilla,BASE,500', '100,Drilla,BASE,600'))
        self.assertEqual(self.env['sembradora.config.rel'].search([('modelo_id', '=', self.pionera.id)]), pionera_configs)
        self.assertEqual(self._imported('cfg_drilla_100').price, 600.0)
        self.assertNotIn('Pionera', wizard.analysis_summary)

    def test_manual_configuration_is_replaced(self):
        """Una configuración sin xmlid (creada a mano) que no está en el CSV se borra antes de crear
        las del archivo: la misma combinación con otro origen no choca."""
        manual = self._imported('cfg_pionera_002')
        self.env['ir.model.data'].search([('module', '=', 'cotizador_import'), ('name', '=', 'cfg_pionera_002')]).unlink()
        wizard = self._wizard(MATRIX_CSV)
        self.assertIn(escape(f"002 · {manual.name}"), wizard.analysis_summary)
        wizard.action_import()
        self.assertFalse(manual.exists())
        self.assertEqual(self._imported('cfg_pionera_002').price, 2000.0)

    def test_unused_rules_are_deleted_and_shared_ones_kept(self):
        """Una regla del importador se borra cuando ninguna máquina la usa; si otra máquina la usa, queda."""
        self._import(MATRIX_CSV + DRILLA_CSV)
        cuchillas = self._imported('rule_exclusion_cuchillas')
        without_knives = MATRIX_CSV.replace('001,Pionera,OPCIONAL,,Cuchilla A,20,,Cuchillas:e,,,\n', '').replace(
            '001,Pionera,OPCIONAL,,Cuchilla B,25,,Cuchillas:e,,,\n', '').replace('Kit Siembra:u|Cuchillas:e', 'Kit Siembra:u')
        self._import(without_knives)  # la Drilla todavía la usa
        self.assertTrue(cuchillas.exists())
        wizard = self._import(HEADER + DRILLA_CSV.replace(',Cuchillas:e,', ',,'))
        self.assertIn('Reglas que se borran (ya no las usa nadie): <b>1</b>', wizard.analysis_summary)
        self.assertFalse(cuchillas.exists())

    def test_attribute_no_longer_used_is_removed_from_the_machine(self):
        """Un atributo "Siempre" que la máquina ya no usa en el CSV se le quita."""
        tolva = self.env['product.attribute'].create({'name': 'Tolva', 'create_variant': 'always'})
        value = self.env['product.attribute.value'].create({'name': 'Grande', 'attribute_id': tolva.id})
        self.pionera.attribute_line_ids = [Command.create({'attribute_id': tolva.id, 'value_ids': [Command.set(value.ids)]})]
        wizard = self._wizard(MATRIX_CSV)
        self.assertIn(escape("Tolva: se quita de la máquina"), wizard.analysis_summary)
        wizard.action_import()
        self.assertNotIn(tolva, self.pionera.attribute_line_ids.attribute_id)
        self.assertEqual(len(self.pionera.product_variant_ids), 2)
