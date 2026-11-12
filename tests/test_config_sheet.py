"""@file
Tests de la planilla de configuraciones (config_sheet.py): conversión al formato del CSV, archivos
.xlsx, hojas y filas ocultas, y configuraciones identificadas por su combinación."""
import base64
import csv
import io

import openpyxl
from markupsafe import escape

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import Form, tagged

from odoo.addons.cotizador.models.config_sheet import Grid, config_sheet_rows, grid_files

from .common import MATRIX_CSV, CotizadorCase

## Planilla de configuraciones de ejemplo: tres filas de metadatos (tipo, cantidad, reglas), encabezado en la
## fila 4, una columna oculta de costo (D), la regla "Kit Siembra:u" en una celda combinada sobre los
## dos kits y la columna Tolva con variantes (su PRECIO al lado). La fila 6 repite la configuración
## de la 5 (celdas vacías = las de arriba) y agrega otra Tolva; la fila 7 es otra configuración.
CONFIG_SHEET_VALUES = [
    ['TIPO', '', '', '', '', 'ESTANDAR', '', 'Estándar', '', '', '', ''],
    ['CALC PARAM', '', '', '', '', '', 'Lineas', '', '', '', '', ''],
    ['REGLAS', '', '', '', '', 'Monitor:it', 'Monitor:i', 'Kit Siembra:u', '', '', '', 'Cuchillas:e'],
    ['Modelo', 'Lineas', 'Distancia', 'Costo', 'PRECIO', 'Monitor', 'Sensor', 'Kit Fino', 'Kit Grueso', 'Tolva',
     'PRECIO', 'Cuchilla A'],
    ['Pionera', '16 Lineas', '52 cm', 999, 1000, 100, 10, 50, 80, 'Chica', 30, 20],
    ['', '', '', '', '', '', '', '', '', 'Grande', 45.5, ''],
    ['', '18 Lineas', '52 cm', '', 2000, 100, '-', 55, 85, '', '', 0],
]
CONFIG_SHEET_GRID = {
    'name': 'Pionera',
    'values': CONFIG_SHEET_VALUES,
    'hidden_cols': [3],
    'merges': [[2, 7, 2, 8]],
}


def analyze_grids(env, grids, sheets=('Pionera',)):
    """Analiza hojas ya evaluadas como lo hace el módulo cotizador_spreadsheet, con las hojas marcadas.

    @param env Entorno.
    @param grids Lista de dicts de grilla.
    @param sheets Hojas marcadas.
    @return Asistente analizado.
    """
    wizard = env['sembradora.import.wizard'].create({
        'currency_id': env.ref('base.USD').id,
        'sheet_ids': [Command.create({'source': 'Matriz', 'name': name, 'selected': True}) for name in sheets],
    })
    notes = []
    wizard._analyze(wizard._files_from_grids('Matriz', grids, notes), from_sheets=True, notes=notes)
    return wizard


def _xlsx(values, hidden_cols=(), merges=(), extra_sheets=()):
    """Arma un .xlsx con openpyxl.

    @param values Filas de la primera hoja.
    @param hidden_cols Columnas ocultas (desde 0).
    @param merges Celdas combinadas `[fila_sup, col_izq, fila_inf, col_der]` (desde 0).
    @param extra_sheets Otras hojas `(nombre, filas)`.
    @return Bytes del archivo.
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Pionera'
    for row in values:
        ws.append([None if v == '' else v for v in row])
    for col in hidden_cols:
        ws.column_dimensions[openpyxl.utils.get_column_letter(col + 1)].hidden = True
    for top, left, bottom, right in merges:
        ws.merge_cells(start_row=top + 1, start_column=left + 1, end_row=bottom + 1, end_column=right + 1)
    for name, rows in extra_sheets:
        extra = wb.create_sheet(name)
        for row in rows:
            extra.append(row)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


@tagged('post_install', '-at_install')
class TestConfigSheet(CotizadorCase):
    """La planilla de configuraciones llega al importador igual que un CSV."""

    def _analyze_grids(self, grids):
        """Analiza hojas ya evaluadas con la hoja Pionera marcada (analyze_grids()).

        @param grids Lista de dicts de grilla.
        @return Asistente analizado.
        """
        return analyze_grids(self.env, grids)

    def _analyze_attachment(self, name, content, sheets=()):
        """Analiza un archivo adjunto, marcando hojas como en la lista del asistente.

        @param name Nombre del archivo.
        @param content Bytes.
        @param sheets Hojas a marcar (un libro de una sola hoja ya viene marcado).
        @return Asistente analizado.
        """
        attachment = self.env['ir.attachment'].create({'name': name, 'raw': content})
        wizard = self.env['sembradora.import.wizard'].create({
            'csv_file_ids': [(6, 0, attachment.ids)], 'currency_id': self.usd.id,
        })
        wizard._onchange_csv_file_ids()
        wizard.sheet_ids.filtered(lambda sheet: sheet.name in sheets).selected = True
        wizard.action_analyze()
        return wizard

    def test_config_sheet_rows(self):
        """Atributos, configuraciones, accesorios y metadatos como los armaba el script de Google Sheets."""
        header, rows = config_sheet_rows(Grid(CONFIG_SHEET_GRID))
        self.assertEqual(header[-2:], ['ATR_Lineas', 'ATR_Distancia'])  # la columna oculta no es atributo
        summary = [(where, r['Tipo_Item'], r['Nombre_Item'], r['Precio_Base'] or r['Precio_Item'], r['Calc_param'],
                    r['Reglas']) for where, r in rows]
        self.assertEqual(summary, [
            ('fila 5', 'BASE', '', '1000', '', ''),
            ('fila 5, columna F', 'ESTANDAR', 'Monitor', '100', '', 'Monitor:it'),
            ('fila 5, columna G', 'OPCIONAL', 'Sensor', '10', 'ATR_Lineas', 'Monitor:i'),
            ('fila 5, columna H', 'ESTANDAR', 'Kit Fino', '50', '', 'Kit Siembra:u'),
            ('fila 5, columna I', 'OPCIONAL', 'Kit Grueso', '80', '', 'Kit Siembra:u'),
            ('fila 5, columna J', 'OPCIONAL', 'Tolva - Chica', '30', '', ''),
            ('fila 5, columna L', 'OPCIONAL', 'Cuchilla A', '20', '', 'Cuchillas:e'),
            # Fila 6: misma configuración (lo repetido no se duplica), otra variante de Tolva
            ('fila 6, columna J', 'OPCIONAL', 'Tolva - Grande', '45,5', '', ''),
            # Fila 7: precio nuevo = configuración nueva; el modelo se repite, los accesorios no
            ('fila 7', 'BASE', '', '2000', '', ''),
            ('fila 7, columna F', 'ESTANDAR', 'Monitor', '100', '', 'Monitor:it'),
            ('fila 7, columna H', 'ESTANDAR', 'Kit Fino', '55', '', 'Kit Siembra:u'),
            ('fila 7, columna I', 'OPCIONAL', 'Kit Grueso', '85', '', 'Kit Siembra:u'),
        ])
        bases = [r for _w, r in rows if r['Tipo_Item'] == 'BASE']
        self.assertEqual([(r['Modelo'], r['ATR_Lineas'], r['ATR_Distancia']) for r in bases],
                         [('Pionera', '16 Lineas', '52 cm'), ('Pionera', '18 Lineas', '52 cm')])

    def test_display_text(self):
        """Los textos salen de lo que se ve en la celda (p. ej. un código con ceros a la izquierda),
        y los precios del valor calculado."""
        values = [row[:] for row in CONFIG_SHEET_VALUES]
        values[4][1] = 16
        display = [[None] * 12 for _row in values]
        display[4][1] = '016 Lineas'
        display[4][4] = 'USD 1.000,00'
        _header, rows = config_sheet_rows(Grid({**CONFIG_SHEET_GRID, 'values': values, 'display': display}))
        self.assertEqual((rows[0][1]['ATR_Lineas'], rows[0][1]['Precio_Base']), ('016 Lineas', '1000'))

    def test_hidden_rows(self):
        """Una fila oculta no se lee: arriba del encabezado (cálculos auxiliares) no da reglas, y una
        fila de datos oculta no carga nada pero se avisa en el análisis."""
        values = [row[:] for row in CONFIG_SHEET_VALUES]
        values.insert(3, ['', '', '', '', '', 207, 305, '', '', '', '', ''])  # cálculo auxiliar, fila 4
        grid = {**CONFIG_SHEET_GRID, 'values': values}
        _header, rows = config_sheet_rows(Grid(grid))
        self.assertEqual(rows[1][1]['Reglas'], 'Monitor:it|207')  # visible: se lee como regla

        notes = []
        files = grid_files('Matriz', [{**grid, 'hidden_rows': [3, 6]}], ['Pionera'], notes)
        rows = files[0][2]
        self.assertEqual(rows[1][1]['Reglas'], 'Monitor:it')
        self.assertNotIn('Tolva - Grande', [r['Nombre_Item'] for _w, r in rows])  # fila 7, oculta
        self.assertEqual(notes, ['Matriz › Pionera: no se leyeron 1 filas de datos ocultas (7).'])

        wizard = self._analyze_grids([{**grid, 'hidden_rows': [3, 6]}])
        self.assertFalse(wizard.has_errors, wizard.analysis_summary)
        self.assertIn('no se leyeron 1 filas de datos ocultas (7)', wizard.analysis_summary)

    def test_sheet_selection(self):
        """Solo se leen las hojas elegidas: una copia de la misma máquina no choca. Una hoja elegida sin
        encabezados es un error (no se omite en silencio)."""
        copy = {**CONFIG_SHEET_GRID, 'name': 'Copia de Pionera'}
        files = grid_files('Matriz', [CONFIG_SHEET_GRID, copy], ['Pionera'], [])
        self.assertEqual([name for name, _h, _r in files], ['Matriz › Pionera'])
        with self.assertRaisesRegex(Exception, 'Costos: la hoja no tiene la fila de encabezados'):
            grid_files('Matriz', [CONFIG_SHEET_GRID, {'name': 'Costos', 'values': [['Chasis', 600]]}], ['Costos'], [])
        with self.assertRaisesRegex(Exception, 'no tiene las hojas Gringa'):
            grid_files('Matriz', [CONFIG_SHEET_GRID], ['Gringa'], [])

    def test_xlsx_requires_sheet_selection(self):
        """Un libro de varias hojas lista sus hojas visibles y pide marcar cuáles importar."""
        content = _xlsx(CONFIG_SHEET_VALUES, extra_sheets=[('Costos', [['Chasis', 600]])])
        with self.assertRaisesRegex(UserError, 'marque las hojas a importar'):
            self._analyze_attachment('matriz.xlsx', content)
        attachment = self.env['ir.attachment'].create({'name': 'matriz.xlsx', 'raw': content})
        wizard = self.env['sembradora.import.wizard'].new({'csv_file_ids': [(6, 0, attachment.ids)]})
        wizard._onchange_csv_file_ids()
        self.assertEqual(wizard.sheet_ids.mapped('name'), ['Pionera', 'Costos'])
        self.assertFalse(any(wizard.sheet_ids.mapped('selected')))

    def test_sheet_list_in_form(self):
        """Desde el formulario (como el navegador): subir el libro lista las hojas, marcar una y guardar."""
        attachment = self.env['ir.attachment'].create({
            'name': 'matriz.xlsx', 'raw': _xlsx(CONFIG_SHEET_VALUES, extra_sheets=[('Costos', [['Chasis', 600]])]),
        })
        form = Form(self.env['sembradora.import.wizard'])
        form.currency_id = self.usd
        form.csv_file_ids.add(attachment)
        self.assertEqual(len(form.sheet_ids), 2)
        with form.sheet_ids.edit(0) as line:
            line.selected = True
        wizard = form.save()
        self.assertEqual(wizard.sheet_ids.filtered('selected').mapped('name'), ['Pionera'])
        wizard.action_analyze()
        self.assertFalse(wizard.has_errors, wizard.analysis_summary)

    def test_import_from_grid(self):
        """La planilla se importa como el CSV, y el CSV leído se puede volver a importar sin cambios."""
        wizard = self._analyze_grids([CONFIG_SHEET_GRID, {'name': 'Costos', 'values': [['Chasis', 600]]}])
        self.assertFalse(wizard.has_errors, wizard.analysis_summary)
        self.assertIn('Configuraciones nuevas: <b>2</b>', wizard.analysis_summary)
        wizard.action_import()

        config = self._config('Pionera', '16 Lineas', '52 cm')
        self.assertEqual(config.price, 1000.0)
        lines = self._lines(config)
        self.assertEqual(lines['Tolva - Grande'].price, 45.5)
        self.assertEqual({name for name, line in lines.items() if line.is_standard}, {'Monitor', 'Kit Fino'})
        self.assertEqual(lines['Sensor'].product_id.categ_id.cotizador_qty_attribute_id.name, 'Lineas')

        normalized = base64.b64decode(wizard.normalized_csv).decode('utf-8-sig')
        self.assertEqual(next(csv.reader(io.StringIO(normalized)))[:3], ['Modelo', 'Tipo_Item', 'Precio_Base'])
        again = self._wizard(normalized)
        self.assertFalse(again.has_errors, again.analysis_summary)
        self.assertNotIn('Configuraciones nuevas: <b>', again.analysis_summary)

    def test_errors_point_to_cells(self):
        """Los errores del análisis indican la fila y la columna de la planilla."""
        values = [row[:] for row in CONFIG_SHEET_VALUES]
        values[4][7] = 'consultar'
        wizard = self._analyze_grids([{**CONFIG_SHEET_GRID, 'values': values}])
        self.assertTrue(wizard.has_errors)
        self.assertIn(escape("Matriz › Pionera, fila 5, columna H: Precio_Item 'consultar' no es un precio válido."),
                      wizard.analysis_summary)

    def test_xlsx(self):
        """Un .xlsx con la planilla de configuraciones: columnas ocultas y celdas combinadas incluidas."""
        content = _xlsx(CONFIG_SHEET_VALUES, hidden_cols=[3], merges=[[2, 7, 2, 8]],
                        extra_sheets=[('Costos', [['Chasis', 600]])])
        wizard = self._analyze_attachment('matriz.xlsx', content, sheets=['Pionera'])
        self.assertFalse(wizard.has_errors, wizard.analysis_summary)
        self.assertIn('Configuraciones nuevas: <b>2</b>', wizard.analysis_summary)
        self.assertTrue(wizard.normalized_csv)
        wizard.action_import()
        lines = self._lines(self._config('Pionera', '18 Lineas', '52 cm'))
        self.assertEqual(lines['Kit Grueso'].rule_ids.rule_type, 'choice')

    def test_xlsx_formula_without_value(self):
        """Una fórmula sin valor calculado (archivo que no pasó por una planilla) se rechaza."""
        values = [row[:] for row in CONFIG_SHEET_VALUES]
        values[4][4] = '=D5+1'
        with self.assertRaisesRegex(UserError, 'celda E5: la fórmula no tiene valor calculado'):
            self._analyze_attachment('matriz.xlsx', _xlsx(values))

    def test_rows_follow_their_base(self):
        """Cada accesorio es de la fila BASE anterior, y una combinación no puede repetirse."""
        header = MATRIX_CSV.splitlines()[0] + '\n'
        wizard = self._wizard(header + 'Pionera,OPCIONAL,,Sensor,10,,,,,\n'
                                       'Pionera,BASE,1000,,,,,,16 Lineas,52 cm\n'
                                       'Pionera,BASE,1100,,,,,,16 Lineas,52 cm\n')
        self.assertIn(escape("matriz.csv, línea 2: el accesorio no tiene una fila BASE antes"),
                      wizard.analysis_summary)
        self.assertIn(escape('matriz.csv, línea 4: la combinación 16 Lineas · 52 cm de Pionera ya está en otra fila BASE.'),
                      wizard.analysis_summary)


@tagged('post_install', '-at_install')
class TestConfigIdentity(CotizadorCase):
    """Una configuración es su combinación: la planilla actualiza las que ya se importaron."""

    @classmethod
    def setUpClass(cls):
        """Matriz de ejemplo importada y una oportunidad que pide la configuración de 16 líneas."""
        super().setUpClass()
        cls._import(MATRIX_CSV)
        cls.config = cls._config('Pionera', '16 Lineas', '52 cm')
        cls.lead = cls.env['crm.lead'].create({'name': 'Pedido web', 'cotizador_config_id': cls.config.id})

    def test_config_sheet_adopts_configs(self):
        """Importar la planilla sobre lo importado por CSV conserva las configuraciones (y sus oportunidades)."""
        wizard = analyze_grids(self.env, [CONFIG_SHEET_GRID])
        self.assertFalse(wizard.has_errors, wizard.analysis_summary)
        self.assertNotIn('Configuraciones nuevas: <b>', wizard.analysis_summary)
        wizard.action_import()
        self.assertEqual(self._config('Pionera', '16 Lineas', '52 cm'), self.config)
        self.assertEqual(self.lead.cotizador_config_id, self.config)
        self.assertIn('Tolva - Chica', self._lines(self.config))
