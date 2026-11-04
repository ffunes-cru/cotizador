"""@file
Tests del asistente de Teamcenter: plantilla espejo (Excel y CSV), ida y vuelta con Ingeniería
(plantilla → códigos completados → simulación → aplicación) y el resumen de la simulación."""
import base64
import csv
import io
from unittest.mock import patch

import openpyxl

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.cotizador.models import engineering_code_wizard
from .common import MATRIX_CSV, CotizadorCase

HEADERS = ['ID_Odoo', 'Modelo', 'Lineas', 'Distancia', 'CODIGO_INGENIERIA_TEAMCENTER', 'Codigo_Actual_Odoo']


@tagged('post_install', '-at_install')
class TestTeamcenterTemplate(CotizadorCase):
    """Plantilla espejo y carga de códigos de ingeniería."""

    @classmethod
    def setUpClass(cls):
        """Matriz de ejemplo: la Pionera con dos configuraciones (001 y 002), una variante cada una."""
        super().setUpClass()
        cls._import(MATRIX_CSV)
        cls.v001 = cls._imported('cfg_pionera_001')._get_variant()
        cls.v002 = cls._imported('cfg_pionera_002')._get_variant()
        cls.modelo = cls.v001.product_tmpl_id

    def _wizard(self, **vals):
        """@param vals Valores extra del asistente.
        @return Asistente de Teamcenter de la Pionera."""
        return self.env['engineering.code.wizard'].create({'modelo_id': self.modelo.id, **vals})

    def _template_rows(self, wizard):
        """Lee la plantilla generada, sea Excel o CSV.

        @param wizard Asistente con la plantilla generada.
        @return Lista de filas (listas de textos), la primera es el encabezado.
        """
        raw = base64.b64decode(wizard.template_file)
        if wizard.template_filename.endswith('.xlsx'):
            sheet = openpyxl.load_workbook(io.BytesIO(raw)).active
            return [['' if cell is None else str(cell) for cell in row] for row in sheet.iter_rows(values_only=True)]
        return list(csv.reader(io.StringIO(raw.decode('utf-8-sig')), delimiter=';'))

    def _fill_codes(self, rows, codes):
        """Completa la columna del código como lo haría Ingeniería.

        @param rows Filas de la plantilla (con encabezado).
        @param codes {id de variante: código}.
        @return Filas con la columna CODIGO_INGENIERIA_TEAMCENTER completada.
        """
        code_col = rows[0].index('CODIGO_INGENIERIA_TEAMCENTER')
        filled = [rows[0]]
        for row in rows[1:]:
            row = list(row)
            row[code_col] = codes.get(int(row[0]), '')
            filled.append(row)
        return filled

    def _upload(self, wizard, rows, xlsx):
        """Carga en el asistente el archivo devuelto por Ingeniería.

        @param wizard Asistente.
        @param rows Filas (con encabezado).
        @param xlsx True para Excel, False para CSV con punto y coma.
        """
        if xlsx:
            book = openpyxl.Workbook()
            for row in rows:
                book.active.append(row)
            output = io.BytesIO()
            book.save(output)
            raw, name = output.getvalue(), 'codigos.xlsx'
        else:
            output = io.StringIO()
            csv.writer(output, delimiter=';').writerows(rows)
            raw, name = output.getvalue().encode('utf-8-sig'), 'codigos.csv'
        wizard.write({'import_file': base64.b64encode(raw), 'import_filename': name})

    def _expected_rows(self):
        """@return Filas de datos esperadas: una por variante, valores en orden de los atributos."""
        return sorted([
            [str(self.v001.id), 'Pionera', '16 Lineas', '52 cm', '', self.v001.default_code or ''],
            [str(self.v002.id), 'Pionera', '18 Lineas', '52 cm', '', self.v002.default_code or ''],
        ])

    def test_excel_template_has_one_row_per_variant(self):
        """Excel: encabezado fijo, un atributo por columna y una fila por variante con su id."""
        wizard = self._wizard()
        wizard.action_generate_template()
        self.assertEqual(wizard.template_filename, 'Plantilla_Ingenieria_Pionera.xlsx')
        self.assertEqual(wizard.total_odoo_variants, 2)
        rows = self._template_rows(wizard)
        self.assertEqual(rows[0], HEADERS)
        self.assertEqual(sorted(rows[1:]), self._expected_rows())

    def test_csv_template_without_openpyxl(self):
        """Sin openpyxl la plantilla es un CSV con punto y coma y BOM (Excel lo abre con acentos)."""
        wizard = self._wizard()
        with patch.object(engineering_code_wizard, 'OPENPYXL_AVAILABLE', False):
            wizard.action_generate_template()
        self.assertEqual(wizard.template_filename, 'Plantilla_Ingenieria_Pionera.csv')
        self.assertTrue(base64.b64decode(wizard.template_file).startswith('﻿'.encode()))
        rows = self._template_rows(wizard)
        self.assertEqual(rows[0], HEADERS)
        self.assertEqual(sorted(rows[1:]), self._expected_rows())

    def test_template_shows_current_code(self):
        """La última columna trae la referencia interna actual de la variante."""
        self.v001.default_code = 'TC-VIEJO'
        wizard = self._wizard()
        wizard.action_generate_template()
        rows = {row[0]: row for row in self._template_rows(wizard)[1:]}
        self.assertEqual(rows[str(self.v001.id)][-1], 'TC-VIEJO')
        self.assertEqual(rows[str(self.v002.id)][-1], '')

    def test_template_columns_follow_attribute_order(self):
        """Las columnas de atributo siguen el orden de los atributos en la máquina."""
        lines = self.modelo.attribute_line_ids.sorted(lambda l: (l.sequence, l.id))
        lines[0].sequence, lines[1].sequence = 20, 10
        wizard = self._wizard()
        wizard.action_generate_template()
        self.assertEqual(self._template_rows(wizard)[0][2:4], ['Distancia', 'Lineas'])

    def test_model_without_attributes_is_an_error(self):
        """Una máquina sin atributos no tiene plantilla."""
        machine = self.env['product.template'].create({
            'name': 'Sin atributos', 'categ_id': self.modelo.categ_id.id,
        })
        wizard = self.env['engineering.code.wizard'].create({'modelo_id': machine.id})
        with self.assertRaisesRegex(UserError, 'no tiene atributos'):
            wizard.action_generate_template()

    def _round_trip(self, xlsx):
        """Plantilla → Ingeniería completa los códigos → simulación → aplicación.

        @param xlsx True para ir y volver en Excel, False en CSV.
        """
        wizard = self._wizard()
        if xlsx:
            wizard.action_generate_template()
        else:
            with patch.object(engineering_code_wizard, 'OPENPYXL_AVAILABLE', False):
                wizard.action_generate_template()
        rows = self._fill_codes(self._template_rows(wizard), {self.v001.id: 'TC-001', self.v002.id: 'TC-002'})
        self._upload(wizard, rows, xlsx)
        wizard.action_analyze_file()
        self.assertEqual(wizard.state, 'preview')
        self.assertEqual(
            (wizard.total_odoo_variants, wizard.matched_count, wizard.missing_in_file_count,
             wizard.extra_in_file_count),
            (2, 2, 0, 0))
        wizard.action_apply_codes()
        self.assertEqual(wizard.state, 'done')
        self.assertEqual((self.v001.default_code, self.v002.default_code), ('TC-001', 'TC-002'))

    def test_round_trip_excel(self):
        """La plantilla en Excel, completada, carga los códigos en cada variante."""
        self._round_trip(xlsx=True)

    def test_round_trip_csv(self):
        """Lo mismo con la plantilla en CSV."""
        self._round_trip(xlsx=False)

    def test_regenerated_template_shows_applied_codes(self):
        """Después de aplicar, una plantilla nueva trae los códigos cargados como código actual."""
        self._round_trip(xlsx=True)
        wizard = self._wizard()
        wizard.action_generate_template()
        current = {row[0]: row[-1] for row in self._template_rows(wizard)[1:]}
        self.assertEqual(current, {str(self.v001.id): 'TC-001', str(self.v002.id): 'TC-002'})

    def test_partial_file_and_unknown_rows(self):
        """Una variante sin código cuenta como faltante y una fila que no existe, como no reconocida."""
        wizard = self._wizard()
        wizard.action_generate_template()
        rows = self._fill_codes(self._template_rows(wizard), {self.v001.id: 'TC-001'})
        rows.append(['', 'Pionera', '20 Lineas', '70 cm', 'TC-XXX', ''])
        self._upload(wizard, rows, xlsx=True)
        wizard.action_analyze_file()
        self.assertEqual(
            (wizard.matched_count, wizard.missing_in_file_count, wizard.extra_in_file_count), (1, 1, 1))
        self.assertIn('TC-XXX', wizard.preview_html)
        wizard.action_apply_codes()
        self.assertEqual(self.v001.default_code, 'TC-001')
        self.assertFalse(self.v002.default_code)

    def test_id_of_another_variant_is_not_trusted(self):
        """Si el ID_Odoo no coincide con los valores de la fila, manda la combinación de valores."""
        wizard = self._wizard()
        wizard.action_generate_template()
        rows = self._fill_codes(self._template_rows(wizard), {self.v001.id: 'TC-001', self.v002.id: 'TC-002'})
        rows[1][0], rows[2][0] = rows[2][0], rows[1][0]  # ids cruzados
        self._upload(wizard, rows, xlsx=True)
        wizard.action_analyze_file()
        wizard.action_apply_codes()
        self.assertEqual((self.v001.default_code, self.v002.default_code), ('TC-001', 'TC-002'))

    def test_back_to_upload_discards_simulation(self):
        """Volver al paso 1 descarta el archivo y la simulación."""
        wizard = self._wizard()
        wizard.action_generate_template()
        self._upload(wizard, self._fill_codes(self._template_rows(wizard), {self.v001.id: 'TC-001'}), xlsx=True)
        wizard.action_analyze_file()
        wizard.action_back_to_upload()
        self.assertEqual(wizard.state, 'upload')
        self.assertFalse(wizard.import_file or wizard.matched_data_json)
        with self.assertRaisesRegex(UserError, 'No hay datos'):
            wizard.action_apply_codes()

    def test_file_without_code_column_is_an_error(self):
        """Un archivo sin columna de código se rechaza con un mensaje claro."""
        wizard = self._wizard()
        self._upload(wizard, [['ID_Odoo', 'Lineas'], [str(self.v001.id), '16 Lineas']], xlsx=False)
        with self.assertRaisesRegex(UserError, 'columna de código'):
            wizard.action_analyze_file()
