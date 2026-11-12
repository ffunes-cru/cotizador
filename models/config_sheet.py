"""@file
Planilla de configuraciones → filas del importador (las del CSV normalizado, docs/importador.md §2).

Una **grilla** es una hoja con los valores ya calculados, venga de un .xlsx (grids_from_xlsx()) o de una
planilla de Odoo (módulo cotizador_spreadsheet, que la evalúa en el navegador). Es un dict:

- `name`: nombre de la hoja;
- `values`: filas de valores calculados (texto, número, booleano o None), desde A1;
- `display`: opcional, mismas filas con el texto que se ve en la celda (formato aplicado);
- `hidden_cols` / `hidden_rows`: índices (desde 0) de las columnas y filas ocultas (a mano o por un filtro);
- `merges`: celdas combinadas `[fila_sup, col_izq, fila_inf, col_der]` (desde 0, inclusive);
- `hidden`: la hoja está oculta (no se lee).

La hoja tiene el diseño de la planilla de configuraciones (config_sheet_rows(), docs/importador.md
§11.1), y sale con la forma de un archivo de _read_files(): `(encabezado, [(ubicación, fila)])`. Los precios se leen del valor calculado (no del texto formateado) y el resto del texto que se ve.
Lo oculto no se lee: las columnas ocultas se saltean y las filas ocultas son como filas vacías (sirven
para cálculos auxiliares).
"""
import io
import re
import unicodedata
import zipfile
from datetime import date, datetime

from lxml import etree

try:
    import openpyxl
    OPENPYXL_AVAILABLE = True
except ImportError:
    OPENPYXL_AVAILABLE = False

## Filas donde se busca el encabezado de la planilla de configuraciones.
HEADER_SEARCH_ROWS = 50
## Encabezados de la columna de precio de la máquina (en mayúsculas).
PRICE_HEADERS = ('PRECIO', 'PRECIO BASE')
## Encabezado de la columna de precio que acompaña a una columna de accesorio con variantes.
PAIRED_PRICE_HEADER = 'PRECIO'
## Celdas que significan "no tiene" en una columna de accesorio.
EMPTY_MARKS = ('', '-')
## Columnas fijas del CSV normalizado, en orden. Las de atributos llevan el prefijo `ATR_`.
FIXED_COLUMNS = ('Modelo', 'Tipo_Item', 'Precio_Base', 'Nombre_Item', 'Precio_Item', 'Calc_param', 'Reglas',
                 'Descripcion')


class MatrixError(ValueError):
    """La hoja no tiene la estructura esperada (p. ej. le falta la columna Modelo)."""


def strip_accents(text):
    """Quita acentos y diacríticos: 'Líneas' → 'Lineas'.

    @param text Texto.
    @return Texto sin marcas diacríticas.
    """
    return ''.join(c for c in unicodedata.normalize('NFD', text) if unicodedata.category(c) != 'Mn')


def _upper_plain(text):
    """Mayúsculas sin acentos: 'Estándar' → 'ESTANDAR'.

    @param text Texto.
    @return Texto normalizado.
    """
    return strip_accents(text).upper()


def format_number(number):
    """Número como texto para el importador, con coma decimal (parse_price() lee '1.125' como 1125).

    @param number int o float.
    @return '1500', '1500,5', '1,125'.
    """
    if float(number).is_integer():
        return str(int(number))
    return repr(float(number)).replace('.', ',')


def cell_text(value):
    """Texto de un valor de celda cuando no se tiene el texto formateado.

    @param value Valor calculado (texto, número, booleano, fecha o None).
    @return Texto sin espacios en los extremos.
    """
    if value is None:
        return ''
    if isinstance(value, bool):
        return 'VERDADERO' if value else 'FALSO'
    if isinstance(value, (int, float)):
        return format_number(value)
    if isinstance(value, (datetime, date)):
        return value.strftime('%d/%m/%Y')
    return str(value).strip()


def column_letter(index):
    """Letra de una columna: 0 → 'A', 27 → 'AB'.

    @param index Índice desde 0.
    @return Letras de la columna.
    """
    letters = ''
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        letters = chr(65 + rest) + letters
    return letters


class Grid:
    """Hoja con las celdas combinadas resueltas (cada celda de una combinación vale lo de la superior
    izquierda) y las filas ocultas vaciadas.

    `raw` conserva los valores calculados sin resolver combinaciones (para saber qué está escrito en
    cada fila) y `text` / `value` dan el texto visible y el valor de cada celda ya resuelta.
    `hidden_data_rows` son las filas ocultas que tenían algo escrito (para avisar que no se leyeron).
    """

    def __init__(self, grid):
        """Arma la grilla rectangular, resuelve las celdas combinadas y vacía las filas ocultas.

        @param grid dict de grilla (ver el encabezado del archivo).
        """
        self.name = grid.get('name') or ''
        values = [list(row or []) for row in grid.get('values') or []]
        display = grid.get('display')
        self.width = max((len(row) for row in values), default=0)
        self.raw = [row + [None] * (self.width - len(row)) for row in values]
        self.texts = [[
            (str(display[r][c]).strip() if display and r < len(display) and c < len(display[r])
             and display[r][c] is not None else cell_text(self.raw[r][c]))
            for c in range(self.width)] for r in range(len(self.raw))]
        self.values = [row[:] for row in self.raw]
        self.hidden_cols = set(grid.get('hidden_cols') or [])
        for top, left, bottom, right in grid.get('merges') or []:
            if top >= len(self.raw) or left >= self.width:
                continue
            for r in range(top, min(bottom, len(self.raw) - 1) + 1):
                for c in range(left, min(right, self.width - 1) + 1):
                    self.texts[r][c] = self.texts[top][left]
                    self.values[r][c] = self.values[top][left]
        self.hidden_data_rows = []
        for r in sorted(set(grid.get('hidden_rows') or [])):
            if r < len(self.raw):
                if any(self.texts[r]):
                    self.hidden_data_rows.append(r)
                self.raw[r] = [None] * self.width
                self.values[r] = [None] * self.width
                self.texts[r] = [''] * self.width

    def __len__(self):
        """Cantidad de filas.

        @return int.
        """
        return len(self.raw)

    def text(self, row, col):
        """Texto visible de una celda (combinaciones resueltas).

        @param row Fila desde 0.
        @param col Columna desde 0.
        @return Texto ('' fuera de la grilla).
        """
        return self.texts[row][col] if row < len(self.texts) and col < self.width else ''

    def price(self, row, col):
        """Precio de una celda para el importador: el número calculado con coma decimal, o el texto.

        @param row Fila desde 0.
        @param col Columna desde 0.
        @return Texto ('' si está vacía).
        """
        value = self.values[row][col] if row < len(self.values) and col < self.width else None
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return format_number(value)
        return self.text(row, col)

    def is_empty_row(self, row):
        """La fila no tiene ningún texto (combinaciones resueltas).

        @param row Fila desde 0.
        @return bool.
        """
        return not any(self.texts[row])


def find_header_row(grid):
    """Fila de encabezados de la planilla de configuraciones: tiene `Modelo` y `PRECIO` (o `PRECIO BASE`).

    @param grid Grid.
    @return Índice de la fila, o None.
    """
    for r in range(min(HEADER_SEARCH_ROWS, len(grid))):
        upper = [_upper_plain(t) for t in grid.texts[r]]
        if 'MODELO' in upper and any(h in upper for h in PRICE_HEADERS):
            return r
    return None


def _attribute_header(name):
    """Encabezado ATR_ de una columna de atributo: 'Cantidad de Lineas' → 'ATR_Cantidad_de_Lineas'.

    @param name Encabezado de la planilla.
    @return Encabezado del CSV.
    """
    return 'ATR_' + re.sub(r'\s+', '_', re.sub(r'^ATR_', '', name, flags=re.I).strip())


def _squash(text):
    """Para comparar nombres de atributo: sin ATR_, minúsculas, sin espacios ni `_`.

    @param text Texto.
    @return Texto comparable.
    """
    return re.sub(r'[\s_]+', '', re.sub(r'^ATR_', '', text.strip(), flags=re.I).lower())


def _column_metadata(grid, header_row, col, attributes):
    """Tipo, Calc_param y reglas de una columna de accesorio, de las filas sobre el encabezado.

    La etiqueta de cada fila está en la columna A: `TIPO…` (ESTANDAR u OPCIONAL), `CALC…` / `…PARAM…`
    (atributo de cantidad) y `REGLA…` o vacía (reglas; ahí también se acepta ESTANDAR o el nombre de un
    atributo como Calc_param). En otra fila, ESTANDAR marca el tipo y cualquier otro texto es una regla.

    @param grid Grid.
    @param header_row Fila del encabezado.
    @param col Columna del accesorio.
    @param attributes Lista de (columna, encabezado de la planilla, encabezado ATR_).
    @return dict `{tipo, calc_param, reglas}`.
    """
    tipo, raw_calc, rules = 'OPCIONAL', '', []
    attribute_names = {name.lower(): name for _c, name, _h in attributes}
    for r in range(header_row):
        text = grid.text(r, col)
        if not text:
            continue
        tag = _upper_plain(grid.text(r, 0))
        is_standard = re.search(r'\bESTANDAR\b', _upper_plain(text)) is not None
        if 'TIPO' in tag:
            tipo = 'ESTANDAR' if is_standard else 'OPCIONAL'
        elif 'CALC' in tag or 'PARAM' in tag:
            raw_calc = text
        elif is_standard:
            tipo = 'ESTANDAR'
        elif ('REGLA' in tag or not tag) and text.lower() in attribute_names:
            raw_calc = text
        elif text not in rules:
            rules.append(text)
    calc_param = ''
    if raw_calc:
        calc_param = next((h for _c, name, h in attributes if _squash(name) == _squash(raw_calc)),
                          _attribute_header(raw_calc))
    return {'tipo': tipo, 'calc_param': calc_param, 'reglas': '|'.join(rules)}


def config_sheet_rows(grid):
    """Convierte la planilla de configuraciones al diseño del CSV normalizado.

    Reglas (las del script de Google Sheets que reemplaza; docs/importador.md §11):

    - Encabezado: la fila con `Modelo` y `PRECIO`. Las columnas no ocultas antes de PRECIO (salvo
      Modelo) son **atributos** (`ATR_<nombre>`); las de después, **accesorios**. Las columnas ocultas
      se ignoran y las filas ocultas cuentan como vacías (Grid; son cálculos auxiliares).
    - Las celdas combinadas valen en todas sus celdas. Una celda vacía repite la de arriba; cuando
      una fila escribe Modelo o PRECIO, las columnas de accesorio dejan de repetirse.
    - Filas seguidas con el mismo modelo, precio y atributos son **una configuración** (una fila BASE).
    - Accesorio: la celda es su precio; vacía, `-` o 0 = no lo tiene. Si la columna siguiente se llama
      `PRECIO`, la celda es la variante (`Kit` + `Fino` → accesorio `Kit - Fino`) y el precio va al lado.
    - Tipo, Calc_param y reglas de cada accesorio salen de las filas sobre el encabezado
      (_column_metadata()). Un accesorio repetido con el mismo precio en una configuración va una vez.

    @param grid Grid.
    @return `(encabezado, [(ubicación, {columna: valor})])`, con la ubicación como texto
            ("fila 12" o "fila 12, columna K") para los mensajes del análisis.
    @throws MatrixError Si falta la fila de encabezados (p. ej. se marcó una hoja auxiliar).
    """
    header_row = find_header_row(grid)
    if header_row is None:
        raise MatrixError(f"la hoja no tiene la fila de encabezados con 'Modelo' y 'PRECIO' (en las primeras "
                          f"{HEADER_SEARCH_ROWS} filas visibles).")
    upper = [_upper_plain(t) for t in grid.texts[header_row]]
    model_col = upper.index('MODELO')
    price_col = next(c for c, h in enumerate(upper) if h in PRICE_HEADERS)
    attributes = [(c, grid.text(header_row, c), _attribute_header(grid.text(header_row, c)))
                  for c in range(price_col)
                  if c != model_col and c not in grid.hidden_cols and grid.text(header_row, c)]
    accessory_cols = [c for c in range(price_col + 1, grid.width)
                      if c not in grid.hidden_cols and grid.text(header_row, c)
                      and upper[c] != PAIRED_PRICE_HEADER]
    metadata = {c: _column_metadata(grid, header_row, c, attributes) for c in accessory_cols}
    header = [*FIXED_COLUMNS, *(h for _c, _n, h in attributes)]

    rows, last, last_key, seen = [], [''] * grid.width, None, set()
    for r in range(header_row + 1, len(grid)):
        if grid.is_empty_row(r):
            continue
        if cell_text(grid.raw[r][model_col]) or cell_text(grid.raw[r][price_col]):
            for c in range(price_col + 1, grid.width):
                last[c] = ''
        texts, prices = [], []
        for c in range(grid.width):
            if grid.text(r, c):
                last[c] = (grid.text(r, c), grid.price(r, c))
            texts.append(last[c][0] if last[c] else '')
            prices.append(last[c][1] if last[c] else '')
        modelo, price = texts[model_col], prices[price_col]
        values = [texts[c] for c, _n, _h in attributes]
        key = (modelo, price, tuple(values))
        if key != last_key:
            last_key, seen = key, set()
            rows.append((f"fila {r + 1}", {
                **dict.fromkeys(header, ''), 'Modelo': modelo, 'Tipo_Item': 'BASE', 'Precio_Base': price,
                **{h: texts[c] for c, _n, h in attributes},
            }))
        for c in accessory_cols:
            name = grid.text(header_row, c)
            if c + 1 < grid.width and upper[c + 1] == PAIRED_PRICE_HEADER:
                variant, item_price = texts[c], prices[c + 1]
                if variant in EMPTY_MARKS or _is_zero(item_price):
                    continue
                name = f"{name} - {variant}"
            else:
                item_price = prices[c]
                if _is_zero(item_price):
                    continue
            if (name, item_price) in seen:
                continue
            seen.add((name, item_price))
            meta = metadata[c]
            rows.append((f"fila {r + 1}, columna {column_letter(c)}", {
                **dict.fromkeys(header, ''), 'Modelo': modelo, 'Tipo_Item': meta['tipo'], 'Nombre_Item': name,
                'Precio_Item': item_price, 'Calc_param': meta['calc_param'], 'Reglas': meta['reglas'],
            }))
    return header, rows


def _is_zero(price):
    """Una celda de precio de accesorio que significa "no lo tiene": vacía, `-` o cero.

    @param price Texto de precio (Grid.price()).
    @return bool.
    """
    return price in EMPTY_MARKS or re.fullmatch(r'0+([.,]0+)?', price) is not None


def grids_from_xlsx(content, sheet_names):
    """Lee hojas de un .xlsx como grillas, con los valores calculados que guardó la planilla.

    @param content Bytes del archivo.
    @param sheet_names Hojas a leer (las demás no se abren).
    @return Lista de dicts de grilla, en el orden de `sheet_names`.
    @throws MatrixError Si falta openpyxl o una fórmula no tiene valor calculado (archivo generado por un
            programa que no calcula, p. ej. openpyxl): hay que abrirlo y guardarlo en Excel, LibreOffice o
            Google Sheets.
    """
    if not OPENPYXL_AVAILABLE:
        raise MatrixError("para leer archivos .xlsx el servidor necesita la librería openpyxl.")
    values_wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
    formulas_wb = openpyxl.load_workbook(io.BytesIO(content), data_only=False)
    grids = []
    for ws in (values_wb[name] for name in sheet_names if name in values_wb.sheetnames):
        max_row, max_col = ws.max_row, ws.max_column
        values = [list(row) for row in ws.iter_rows(min_row=1, min_col=1, max_row=max_row, max_col=max_col,
                                                     values_only=True)]
        formulas = formulas_wb[ws.title]
        for r, row in enumerate(values):
            for c, value in enumerate(row):
                source = formulas.cell(row=r + 1, column=c + 1).value
                if value is None and isinstance(source, str) and source.startswith('='):
                    raise MatrixError(
                        f"hoja '{ws.title}', celda {column_letter(c)}{r + 1}: la fórmula no tiene valor calculado. "
                        f"Abra el archivo en Excel, LibreOffice o Google Sheets y vuelva a guardarlo.")
        hidden = {c - 1 for dim in ws.column_dimensions.values() if dim.hidden and dim.min
                  for c in range(dim.min, (dim.max or dim.min) + 1)}
        grids.append({
            'name': ws.title,
            'values': values,
            'hidden_cols': sorted(hidden),
            'hidden_rows': sorted(r - 1 for r, dim in ws.row_dimensions.items() if dim.hidden),
            'merges': [[m.min_row - 1, m.min_col - 1, m.max_row - 1, m.max_col - 1] for m in ws.merged_cells.ranges],
            'hidden': ws.sheet_state != 'visible',
        })
    return grids


def grid_files(source_name, grids, sheet_names, notes):
    """Convierte las hojas elegidas de una planilla en archivos para el importador, una por hoja.

    @param source_name Nombre de la planilla, para los mensajes.
    @param grids Lista de dicts de grilla (puede tener más hojas que las elegidas).
    @param sheet_names Hojas a leer; cada una tiene que tener la fila de encabezados con Modelo y PRECIO.
    @param notes Lista donde se agregan avisos para el análisis (filas de datos ocultas que no se leyeron).
    @return Lista de `(nombre, encabezado, [(ubicación, fila)])`, como _read_files().
    @throws MatrixError Si falta una hoja, no tiene un diseño reconocible o está mal armada.
    """
    by_name = {raw.get('name'): raw for raw in grids}
    missing = [name for name in sheet_names if name not in by_name]
    if missing:
        raise MatrixError(f"{source_name}: no tiene las hojas {', '.join(missing)}.")
    files = []
    for sheet_name in sheet_names:
        grid = Grid(by_name[sheet_name])
        name = f"{source_name} › {sheet_name}"
        try:
            header, rows = config_sheet_rows(grid)
        except MatrixError as e:
            raise MatrixError(f"{name}: {e}") from e
        skipped = [r + 1 for r in grid.hidden_data_rows if r > find_header_row(grid)]
        if skipped:
            notes.append(f"{name}: no se leyeron {len(skipped)} filas de datos ocultas "
                         f"({', '.join(map(str, skipped[:20]))}{'…' if len(skipped) > 20 else ''}).")
        files.append((name, header, rows))
    return files


def workbook_sheet_names(workbook_xml):
    """Hojas visibles de un libro, en orden, leídas de `xl/workbook.xml` (sin abrir las hojas).

    @param workbook_xml Contenido de `xl/workbook.xml` (texto o bytes).
    @return Lista de nombres.
    """
    root = etree.fromstring(workbook_xml.encode() if isinstance(workbook_xml, str) else workbook_xml)
    return [sheet.get('name') for sheet in root.iter('{*}sheet') if sheet.get('state', 'visible') == 'visible']


def xlsx_sheet_names(content):
    """Hojas visibles de un .xlsx, sin leer su contenido.

    @param content Bytes del archivo.
    @return Lista de nombres (vacía si no es un .xlsx válido).
    """
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as xlsx:
            return workbook_sheet_names(xlsx.read('xl/workbook.xml'))
    except (zipfile.BadZipFile, KeyError, etree.XMLSyntaxError):
        return []
