"""@file
Importador CSV de la matriz de ingeniería (asistente `sembradora.import.wizard`).

Formato y reglas para el usuario: docs/importador.md. Lee CSV en el formato del importador y
planillas (.xlsx, o planillas de Odoo con el módulo cotizador_spreadsheet) en ese formato o en el de
la planilla de configuraciones, que config_sheet.py convierte al del CSV. Diseño:

1. **Análisis** (action_analyze()): lee los archivos, los valida completos (_parse() y
   _validate_parsed()) y muestra errores con archivo y línea y un resumen. No escribe nada.
2. **Importación** (action_import()): vuelve a validar exactamente lo analizado y escribe todo en
   la misma transacción, en orden: atributos y valores, categorías de cantidad, modelos (con sus
   valores exactos), borrado de las configuraciones que ya no están, accesorios, reglas,
   configuraciones, archivado de los accesorios que ya no están y borrado de las reglas sin uso.

**Espejo del CSV**: cada máquina del archivo queda igual al CSV; las que no están no se tocan. El
plan de cambios (_plan_changes()) se muestra al analizar y, después de importar, queda como log en
el asistente y en el chatter de cada máquina.

**Identidad**: una configuración es su **combinación de atributos** dentro de su máquina
(_match_configs()). El resto (máquinas, atributos, valores, accesorios, reglas) queda con un xmlid del
módulo IMPORT_MODULE armado con el texto del CSV (_xmlid_name()): el importador nunca busca por nombre,
así renombrar en Odoo no rompe la re-importación.
"""
import base64
import csv
import io
import json
import logging
import re
import zipfile

from markupsafe import Markup

from odoo import Command, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare, formatLang, html2plaintext

from .config_sheet import FIXED_COLUMNS, MatrixError, grid_files, grids_from_xlsx, strip_accents, xlsx_sheet_names
from .sembradora_config import validate_rule_set

_logger = logging.getLogger(__name__)

## Módulo de los xmlids que el importador asigna a lo que crea: es su única forma de
## reencontrar registros (nunca busca por nombre), así renombrar en Odoo no rompe la re-importación.
IMPORT_MODULE = 'cotizador_import'

## Prefijo de las columnas de atributo: `ATR_Cantidad_de_Lineas` → atributo "Cantidad de Lineas".
ATTRIBUTE_PREFIX = 'ATR_'

## Tipo_Item de la fila de la máquina (atributos y precio de la configuración).
TYPE_BASE = 'BASE'
## Tipo_Item de un accesorio que el vendedor puede agregar.
TYPE_OPTIONAL = 'OPCIONAL'
## Tipo_Item de un accesorio preseleccionado (equipamiento estándar).
TYPE_STANDARD = 'ESTANDAR'
## Valores válidos de Tipo_Item.
ITEM_TYPES = {TYPE_BASE, TYPE_OPTIONAL, TYPE_STANDARD}

## Máximo de renglones por lista en el detalle de cambios (el resto se resume en "… y N más").
DETAIL_LIMIT = 200

## Sufijo de regla en la columna Reglas → (tipo de regla, es habilitante).
RULE_SUFFIXES = {
    'e': ('exclusion', False),
    'et': ('exclusion', True),
    'i': ('inclusion', False),
    'it': ('inclusion', True),
    'u': ('choice', False),
}


def slugify(text):
    """Convierte un texto en parte de un xmlid: 'Cantidad de Líneas' → 'cantidad_de_lineas'.

    @param text Texto del CSV.
    @return Minúsculas sin acentos, con `_` en lugar de cualquier otro símbolo.
    """
    return re.sub(r'[^a-z0-9]+', '_', strip_accents(text).lower()).strip('_')


def first_number(text):
    """Primer número de un texto: '16 Líneas' → 16.0, '52,5 cm' → 52.5.

    @param text Texto (o None).
    @return El número, o None si no hay ninguno.
    """
    match = re.search(r'\d+(?:[.,]\d+)?', text or '')
    return float(match.group().replace(',', '.')) if match else None


def price_currency_codes(price_str):
    """Códigos ISO de moneda escritos en un precio: 'USD $248.866,00' → {'USD'}.

    @param price_str Celda de precio (o None).
    @return set de códigos de tres letras mayúsculas.
    """
    return set(re.findall(r'\b[A-Z]{3}\b', price_str or ''))


def parse_price(price_str):
    """Convierte una celda de precio a número; acepta formato argentino e internacional.

    | Celda | Resultado |
    |---|---|
    | 'USD $248.866,00' | 248866.0 (punto de miles, coma decimal) |
    | '248866,5' | 248866.5 |
    | '248.866' | 248866.0 (punto de miles) |
    | '248866.00' / '248,866.00' | 248866.0 |

    @param price_str Celda de precio (o None).
    @return El precio, o None si está vacía o no es un número.
    """
    clean = re.sub(r'[^\d.,\-]', '', price_str or '')
    if not re.search(r'\d', clean):
        return None
    if ',' in clean and '.' in clean:
        # El último separador que aparece es el decimal
        if clean.rfind(',') > clean.rfind('.'):
            clean = clean.replace('.', '').replace(',', '.')
        else:
            clean = clean.replace(',', '')
    elif ',' in clean:
        clean = clean.replace(',', '.')
    elif re.fullmatch(r'-?\d{1,3}(\.\d{3})+', clean):
        clean = clean.replace('.', '')
    try:
        return float(clean)
    except ValueError:
        return None


class SembradoraImportSheet(models.TransientModel):
    """Hoja de una planilla del importador, para elegir cuáles se importan (`selected`)."""
    _name = 'sembradora.import.sheet'
    _description = 'Hoja de Planilla a Importar'
    _order = 'sequence, id'

    wizard_id = fields.Many2one('sembradora.import.wizard', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    source = fields.Char(string='Planilla', readonly=True, help='Archivo o planilla de Odoo de la hoja.')
    name = fields.Char(string='Hoja', readonly=True, required=True)
    selected = fields.Boolean(string='Importar')


class SembradoraImportWizard(models.TransientModel):
    """Asistente de importación (`sembradora.import.wizard`), solo Administrador del Configurador.

    Estados: `draft` (carga de archivos y moneda) → `analyzed` (resumen y errores) → `done`.
    `parsed_data` guarda los archivos leídos en el análisis para importar exactamente eso.
    """
    _name = 'sembradora.import.wizard'
    _description = 'Importador CSV de Configuraciones de Sembradora'

    csv_file_ids = fields.Many2many(
        'ir.attachment', string='Archivos CSV o Excel',
        help='CSV en el formato del importador, o planillas .xlsx en ese formato o en el de la planilla de configuraciones.',
    )
    currency_id = fields.Many2one(
        'res.currency', string='Moneda de los Precios', required=True,
        default=lambda self: self.env.company.currency_id,
        help='Moneda de Precio_Base y Precio_Item. Se guarda como Moneda del Cotizador de los '
             'modelos y accesorios importados.',
    )
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('analyzed', 'Analizado'),
        ('done', 'Importado'),
    ], default='draft', string='Estado')
    has_errors = fields.Boolean(string='Tiene Errores', readonly=True)
    analysis_summary = fields.Html(string='Resumen del Análisis', readonly=True, sanitize=False)
    # Archivos leídos en el análisis, para importar exactamente lo analizado
    parsed_data = fields.Text(string='Datos Parseados', readonly=True)
    normalized_csv = fields.Binary(
        string='CSV Normalizado', readonly=True, attachment=False,
        help='Lo que se leyó de las planillas, en el formato del CSV del importador (para revisarlo).',
    )
    normalized_csv_name = fields.Char(string='Nombre del CSV Normalizado', readonly=True)
    sheet_ids = fields.One2many(
        'sembradora.import.sheet', 'wizard_id', string='Hojas',
        help='Hojas de las planillas. Solo se importan las marcadas: un libro suele tener varias máquinas, '
             'hojas auxiliares y copias, y cada máquina importada queda igual a su hoja.',
    )

    @api.onchange('csv_file_ids')
    def _onchange_csv_file_ids(self):
        """Lista las hojas de los .xlsx adjuntos, conservando las que ya estaban marcadas."""
        self._set_sheets([(att.name, xlsx_sheet_names(att.raw or b''))
                          for att in self.csv_file_ids if (att.name or '').lower().endswith('.xlsx')])

    def _set_sheets(self, sources):
        """Reemplaza la lista de hojas, conservando las marcadas. Un libro de una sola hoja la marca.

        @param sources Lista de `(planilla, [hojas])`.
        """
        before = {(sheet.source, sheet.name) for sheet in self.sheet_ids if sheet.selected}
        commands = [Command.clear()]
        for source, names in sources:
            for sequence, name in enumerate(names):
                commands.append(Command.create({
                    'sequence': sequence, 'source': source, 'name': name,
                    'selected': (source, name) in before or len(names) == 1,
                }))
        self.sheet_ids = commands

    def _selected_sheets(self, source):
        """Hojas marcadas de una planilla.

        @param source Nombre del archivo o de la planilla de Odoo.
        @return Lista de nombres de hoja, en orden.
        @throws UserError Si no hay ninguna marcada.
        """
        names = [sheet.name for sheet in self.sheet_ids if sheet.source == source and sheet.selected]
        if not names:
            raise UserError(f"{source}: marque las hojas a importar en la lista de hojas.")
        return names

    # =========================================================================
    #  LECTURA Y VALIDACIÓN (sin escribir nada)
    # =========================================================================

    def _read_files(self, notes):
        """Lee los archivos adjuntos: CSV (UTF-8 con o sin BOM; si falla, Latin-1) o Excel (.xlsx).

        De un .xlsx se leen las hojas marcadas en `sheet_ids` (con el diseño del CSV o el de la
        planilla de configuraciones, config_sheet.grid_files()).

        @param notes Lista donde se agregan avisos para el análisis (filas ocultas no leídas).
        @return Lista de tuplas `(nombre_archivo, encabezado, [(ubicación, fila), ...])`, con cada fila
                como dict {columna: valor}. La ubicación es el número de línea del CSV o un texto
                ("fila 12, columna K") en las planillas. Es serializable a JSON (parsed_data).
        @throws UserError Si no hay archivos o una planilla no se puede leer.
        """
        if not self.csv_file_ids:
            raise UserError("Seleccione al menos un archivo CSV o Excel.")
        files = []
        for att in self.csv_file_ids:
            raw = att.raw or b''
            if (att.name or '').lower().endswith('.xlsx'):
                sheet_names = self._selected_sheets(att.name)
                try:
                    files += grid_files(att.name, grids_from_xlsx(raw, sheet_names), sheet_names, notes)
                except MatrixError as e:
                    raise UserError(str(e)) from e
                except (zipfile.BadZipFile, KeyError, ValueError) as e:
                    raise UserError(f"{att.name}: no es un archivo Excel (.xlsx) válido ({e}).") from e
                continue
            try:
                text = raw.decode('utf-8-sig')
            except UnicodeDecodeError:
                text = raw.decode('latin-1')
            reader = csv.DictReader(io.StringIO(text))
            rows = [(reader.line_num, row) for row in reader]
            files.append((att.name, reader.fieldnames or [], rows))
        return files

    def _files_from_grids(self, source_name, grids, notes):
        """Archivos para el importador a partir de las hojas de una planilla ya evaluada.

        Lo usa el módulo cotizador_spreadsheet con las hojas de una planilla de Odoo.

        @param source_name Nombre de la planilla (el de sus hojas en `sheet_ids`).
        @param grids Lista de dicts de grilla (config_sheet) de las hojas marcadas.
        @param notes Lista donde se agregan avisos para el análisis.
        @return Lista como _read_files().
        @throws UserError Si falta una hoja marcada o no tiene un diseño reconocible.
        """
        try:
            return grid_files(source_name, grids, self._selected_sheets(source_name), notes)
        except MatrixError as e:
            raise UserError(str(e)) from e

    def _parse(self, files):
        """Valida los archivos completos y los convierte a una estructura independiente de Odoo.

        Cada configuración es una fila BASE y las filas de accesorio que la siguen. No consulta la base
        salvo para la moneda: el mismo análisis sirve para mostrar y para importar.

        @param files Salida de _read_files() (o su copia de `parsed_data`).
        @return Tupla `(data, errors)`. `data` tiene `attributes` {columna: {name, values:
                {valor: cantidad}}}, `qty_columns`, `models` {modelo: {columna: valores}},
                `accessories` {(modelo, nombre): Calc_param}, `rules` {(nombre, tipo)} y
                `configs` {(modelo, frozenset de (columna, valor)): {modelo, label, values, price,
                description, lines}}. Si `errors` no está vacía no se debe importar.
        """
        errors = []
        data = {
            'attributes': {},      # columna → {'name', 'values': {valor: cantidad|None}}
            'qty_columns': set(),  # columnas de atributo usadas como Calc_param
            'models': {},          # modelo → {columna: set(valores)}
            'accessories': {},     # (modelo, nombre) → columna Calc_param ('' si no tiene)
            'rules': set(),        # (nombre, tipo)
            'configs': {},         # (modelo, combinación) → {...}
        }
        origins = {}  # (modelo, accesorio) → dónde apareció primero, para los mensajes
        for fname, header, rows in files:
            attr_columns = self._parse_header(fname, header, data, errors)
            if attr_columns is None:
                continue
            config = None  # configuración de la última BASE; False si esa BASE tenía errores
            for line, row in rows:
                where = f"{fname}, línea {line}" if isinstance(line, int) else f"{fname}, {line}"
                cell = {k: (v or '').strip() for k, v in row.items() if k}
                tipo = strip_accents(cell.get('Tipo_Item', '')).upper()
                if tipo not in ITEM_TYPES:
                    errors.append(f"{where}: Tipo_Item '{cell.get('Tipo_Item', '')}' inválido "
                                  f"(use BASE, OPCIONAL o ESTANDAR).")
                elif tipo == TYPE_BASE:
                    config = self._parse_base(where, cell, attr_columns, data, errors)
                elif config is None:
                    errors.append(f"{where}: el accesorio no tiene una fila BASE antes (cada accesorio es de la "
                                  f"fila BASE anterior).")
                elif config and cell.get('Modelo', '') != config['modelo']:
                    errors.append(f"{where}: el accesorio es de '{cell.get('Modelo', '')}', pero la fila BASE "
                                  f"anterior es de '{config['modelo']}'.")
                elif config:
                    self._parse_line(where, cell, tipo, config, attr_columns, data, errors, origins)
        errors += self._validate_parsed(data)
        return data, errors

    def _parse_header(self, fname, header, data, errors):
        """Valida las columnas de un archivo y registra sus atributos.

        @param fname Nombre del archivo.
        @param header Columnas.
        @param data Estructura de _parse() (se completan los atributos).
        @param errors Lista de errores (se agregan los del encabezado).
        @return Columnas de atributo, o None si el archivo no se puede leer.
        """
        unknown = [c for c in header if c not in FIXED_COLUMNS and not c.startswith(ATTRIBUTE_PREFIX)]
        if unknown:
            errors.append(f"{fname}: columnas desconocidas {', '.join(unknown)}. Las columnas de atributos deben "
                          f"empezar con '{ATTRIBUTE_PREFIX}' (p.ej. {ATTRIBUTE_PREFIX}Cantidad_de_Lineas).")
            return None
        missing = {'Modelo', 'Tipo_Item'} - set(header)
        if missing:
            errors.append(f"{fname}: faltan las columnas {', '.join(sorted(missing))}.")
            return None
        attr_columns = [c for c in header if c.startswith(ATTRIBUTE_PREFIX)]
        for col in attr_columns:
            name = col[len(ATTRIBUTE_PREFIX):].replace('_', ' ').strip()
            if not name:
                errors.append(f"{fname}: la columna '{col}' no tiene nombre de atributo.")
            data['attributes'].setdefault(col, {'name': name, 'values': {}})
        return attr_columns

    def _parse_base(self, where, cell, attr_columns, data, errors):
        """Fila BASE: una configuración nueva con su combinación y su precio.

        @param where Ubicación para los mensajes.
        @param cell Fila {columna: texto}.
        @param attr_columns Columnas de atributo del archivo.
        @param data Estructura de _parse().
        @param errors Lista de errores.
        @return La configuración, o False si la fila tiene errores (sus accesorios no se leen).
        """
        modelo = cell.get('Modelo', '')
        values = {col: cell[col] for col in attr_columns if cell.get(col)}
        if not modelo or not values:
            errors.append(f"{where}: la fila BASE necesita Modelo y algún valor de atributo ({ATTRIBUTE_PREFIX}…).")
            return False
        key = (modelo, frozenset(values.items()))
        label = ' · '.join(values.values())
        if key in data['configs']:
            errors.append(f"{where}: la combinación {label} de {modelo} ya está en otra fila BASE.")
            return False
        price = parse_price(cell.get('Precio_Base'))
        if price is None:
            errors.append(f"{where}: Precio_Base '{cell.get('Precio_Base', '')}' no es un precio válido.")
        errors += self._check_price_currency(where, 'Precio_Base', cell.get('Precio_Base'))
        model_values = data['models'].setdefault(modelo, {})
        for col, value in values.items():
            data['attributes'][col]['values'].setdefault(value, None)
            model_values.setdefault(col, set()).add(value)
        config = data['configs'][key] = {
            'modelo': modelo, 'label': label, 'values': values, 'price': price or 0.0,
            'description': cell.get('Descripcion', ''), 'lines': [],
        }
        return config

    def _parse_line(self, where, cell, tipo, config, attr_columns, data, errors, origins):
        """Fila de accesorio (OPCIONAL / ESTANDAR) de una configuración.

        @param where Ubicación para los mensajes.
        @param cell Fila {columna: texto}.
        @param tipo TYPE_OPTIONAL o TYPE_STANDARD.
        @param config Configuración de la fila BASE anterior.
        @param attr_columns Columnas de atributo del archivo.
        @param data Estructura de _parse().
        @param errors Lista de errores.
        @param origins {(modelo, accesorio): ubicación} de la primera aparición de cada accesorio.
        """
        modelo, nombre = config['modelo'], cell.get('Nombre_Item', '')
        if not nombre:
            errors.append(f"{where}: Nombre_Item es obligatorio en filas de accesorio.")
            return
        price = parse_price(cell.get('Precio_Item'))
        if price is None:
            errors.append(f"{where}: Precio_Item '{cell.get('Precio_Item', '')}' no es un precio válido.")
        errors += self._check_price_currency(where, 'Precio_Item', cell.get('Precio_Item'))
        calc_param = cell.get('Calc_param', '')
        if calc_param and calc_param not in attr_columns:
            errors.append(f"{where}: Calc_param '{calc_param}' debe ser el nombre exacto de una columna de "
                          f"atributo del archivo ({', '.join(attr_columns) or 'no hay'}).")
            return
        if calc_param:
            data['qty_columns'].add(calc_param)
        previous = data['accessories'].setdefault((modelo, nombre), calc_param)
        origins.setdefault((modelo, nombre), where)
        if previous != calc_param:
            errors.append(f"{where}: '{nombre}' de {modelo} tiene Calc_param '{calc_param}', pero en "
                          f"{origins[modelo, nombre]} tiene '{previous}'.")
        rules, is_trigger = [], False
        for part in filter(None, (p.strip() for p in cell.get('Reglas', '').split('|'))):
            name, sep, suffix = part.rpartition(':')
            suffix = suffix.strip().lower()
            if not sep or not name.strip() or suffix not in RULE_SUFFIXES:
                errors.append(f"{where}: regla '{part}' inválida; use Nombre:sufijo con sufijo "
                              f"{', '.join(':' + s for s in RULE_SUFFIXES)}.")
                continue
            rtype, trigger = RULE_SUFFIXES[suffix]
            rules.append((name.strip(), rtype))
            data['rules'].add((name.strip(), rtype))
            is_trigger = is_trigger or trigger
        if any(line['name'] == nombre for line in config['lines']):
            errors.append(f"{where}: '{nombre}' aparece dos veces en la configuración {config['label']} de {modelo}.")
            return
        config['lines'].append({
            'name': nombre, 'price': price or 0.0, 'calc_param': calc_param,
            'is_standard': tipo == TYPE_STANDARD, 'is_trigger': is_trigger, 'rules': rules,
        })

    def _check_price_currency(self, where, column, price_str):
        """Un precio que indica su moneda (p. ej. 'USD 1.000') debe estar en la moneda elegida.

        @param where Ubicación "archivo, línea N" para el mensaje.
        @param column Nombre de la columna (Precio_Base o Precio_Item).
        @param price_str Celda de precio.
        @return Lista con un mensaje de error, o vacía.
        """
        codes = price_currency_codes(price_str)
        if codes and codes != {self.currency_id.name}:
            return [f"{where}: {column} '{price_str}' está en {', '.join(sorted(codes))}, pero la "
                    f"moneda de los precios elegida es {self.currency_id.name}."]
        return []

    def _validate_parsed(self, data):
        """Validaciones que necesitan todos los archivos: cantidades, combinaciones completas
        (un valor por cada atributo que usa la máquina), Calc_param presente en la fila BASE, reglas
        (validate_rule_set()) y textos que darían el mismo xmlid.

        @param data Estructura de _parse(); completa las cantidades de los atributos de cantidad.
        @return Lista de mensajes de error.
        """
        errors = []
        # Atributos de cantidad: cada valor debe contener un número
        for col in sorted(data['qty_columns']):
            values = data['attributes'][col]['values']
            for value in values:
                values[value] = first_number(value)
                if values[value] is None:
                    errors.append(f"Atributo de cantidad {col}: el valor '{value}' no contiene un número.")

        model_columns = {}
        for (modelo, _combination), config in data['configs'].items():
            model_columns.setdefault(modelo, set()).update(config['values'])

        for (modelo, _combination), config in data['configs'].items():
            label = f"Configuración {config['label']} de {modelo}"
            missing = sorted(model_columns[modelo] - set(config['values']))
            if missing:
                errors.append(f"{label}: no tiene valor en {', '.join(missing)}, que usan otras configuraciones de "
                              f"{modelo}. Cada configuración necesita un valor de cada atributo de la máquina "
                              f"(una variante por configuración).")
            for line in config['lines']:
                if line['calc_param'] and line['calc_param'] not in config['values']:
                    errors.append(f"{label}: '{line['name']}' se cotiza por {line['calc_param']}, "
                                  f"pero la fila BASE no tiene valor en esa columna.")
            errors += [f"{label}: {e}" for e in validate_rule_set([{
                **line, 'rules': [((name, rtype), rtype, name) for name, rtype in line['rules']],
            } for line in config['lines']])]

        def check_slugs(kind, names):
            """Dos textos distintos no pueden producir el mismo xmlid.

            @param kind Qué se compara, para el mensaje (p. ej. "Modelo").
            @param names Textos del CSV.
            """
            seen = {}
            for name in names:
                other = seen.setdefault(slugify(name), name)
                if other != name:
                    errors.append(f"{kind} '{name}' y '{other}' son indistinguibles para el importador "
                                  f"(solo difieren en acentos, mayúsculas o símbolos).")
        check_slugs('Modelo', data['models'])
        for modelo in data['models']:
            check_slugs(f"Accesorio de {modelo}", [n for m, n in data['accessories'] if m == modelo])
        check_slugs('Atributo', [a['name'] for a in data['attributes'].values()])
        for attr in data['attributes'].values():
            check_slugs(f"Valor de {attr['name']}", attr['values'])
        for rtype, _trigger in set(RULE_SUFFIXES.values()):
            check_slugs('Regla', [name for name, t in data['rules'] if t == rtype])
        return errors

    # =========================================================================
    #  IDENTIDAD: xmlids propios del importador
    # =========================================================================

    def _xmlid_name(self, kind, *parts):
        """Nombre del xmlid (sin módulo) de un registro del importador.

        @param kind Prefijo del tipo: `modelo`, `cfg`, `attr`, `val`, `acc`, `qty` o `rule`.
        @param parts Textos del CSV que lo identifican (se pasan por slugify()).
        @return P. ej. `acc_pionera_kit_fino`.
        """
        return '_'.join([kind, *(slugify(p) for p in parts)])

    def _find(self, model, xmlid_name):
        """Busca un registro del importador por su xmlid.

        @param model Modelo esperado.
        @param xmlid_name Nombre del xmlid en IMPORT_MODULE.
        @return El registro, o un recordset vacío si no existe o es de otro modelo.
        """
        record = self.env.ref(f'{IMPORT_MODULE}.{xmlid_name}', raise_if_not_found=False)
        return record if record and record._name == model else self.env[model]

    def _find_or_create(self, model, xmlid_name, create_vals):
        """Devuelve el registro del xmlid o lo crea (con su xmlid `noupdate`).

        @param model Modelo.
        @param xmlid_name Nombre del xmlid en IMPORT_MODULE.
        @param create_vals Valores para crearlo si no existe (no se aplican si ya existe).
        @return El registro.
        """
        record = self._find(model, xmlid_name)
        if not record:
            record = self.env[model].create(create_vals)
            self._register_xmlid(model, xmlid_name, record)
        return record

    def _match_configs(self, data, templates):
        """Configuración de Odoo de cada configuración del CSV: la de su máquina con la misma combinación.

        Renombrar o reordenar filas no cambia nada, y las oportunidades conservan su configuración.
        Una combinación con un valor que todavía no existe es nueva.

        @param data Estructura de _parse().
        @param templates dict {modelo: product.template} de las máquinas que ya existen.
        @return dict {clave de configuración: sembradora.config.rel}; vacío si es nueva.
        """
        Config = self.env['sembradora.config.rel']
        existing = {
            (config.modelo_id.id, frozenset(config.value_ids.ids)): config
            for config in Config.search([('modelo_id', 'in', [t.id for t in templates.values()])])
        }
        matches = {}
        for key, config_data in data['configs'].items():
            values = [self._find('product.attribute.value', self._xmlid_name('val', data['attributes'][col]['name'], v))
                      for col, v in config_data['values'].items()]
            tmpl = templates.get(key[0])
            matches[key] = (existing.get((tmpl.id, frozenset(v.id for v in values)), Config)
                            if tmpl and all(values) else Config)
        return matches

    def _register_xmlid(self, model, xmlid_name, record):
        """Asocia el xmlid del importador a un registro recién creado.

        Si el xmlid ya existe es un identificador **huérfano**: su registro se borró sin borrar
        el identificador (p. ej. los valores de un atributo borrado, que la base elimina en
        cascada sin pasar por el ORM). En ese caso se reutiliza apuntándolo al registro nuevo, en
        lugar de fallar por la clave única (módulo, nombre).

        @param model Modelo del registro.
        @param xmlid_name Nombre del xmlid en IMPORT_MODULE.
        @param record Registro recién creado.
        """
        IrModelData = self.env['ir.model.data']
        vals = {'model': model, 'res_id': record.id, 'noupdate': True}
        orphan = IrModelData.search([('module', '=', IMPORT_MODULE), ('name', '=', xmlid_name)], limit=1)
        if orphan:
            orphan.write(vals)
        else:
            IrModelData.create({'module': IMPORT_MODULE, 'name': xmlid_name, **vals})

    # =========================================================================
    #  PLAN DE CAMBIOS: el CSV contra la base (sin escribir nada)
    # =========================================================================
    #
    # Cada máquina del CSV queda igual al archivo: configuraciones, líneas de accesorio, accesorios
    # (los que faltan se archivan) y valores de sus atributos. Las máquinas que no están en el CSV
    # no se tocan. El plan se calcula al analizar (para mostrarlo) y otra vez al importar, antes de
    # escribir: es el log de lo que se aplicó.

    def _plan_changes(self, data):
        """Compara lo que dice el CSV con la base, sin escribir nada.

        @param data Estructura de _parse() sin errores.
        @return dict `{machines: [plan de _plan_machine()], attributes_new: [nombres],
                values_new: int, rules_new: [textos], rules_deleted: [textos]}`.
        """
        rule_types = self._rule_type_labels()
        templates = self._planned_templates(data)
        matches = self._match_configs(data, templates)
        return {
            'machines': [self._plan_machine(modelo, templates.get(modelo), data, matches)
                         for modelo in sorted(data['models'])],
            **self._plan_master_data(data, rule_types),
            'rules_deleted': sorted(f"{rule.name} ({rule_types[rule.rule_type]})"
                                    for rule in self._stale_rules(data, templates)),
        }

    def _rule_type_labels(self):
        """@return dict {tipo de regla: etiqueta} (p. ej. 'choice' → 'Opción única')."""
        field = self.env['sembradora.accessory.rule']._fields['rule_type']
        return dict(field._description_selection(self.env))

    def _plan_master_data(self, data, rule_types):
        """Atributos, valores y reglas que se van a crear.

        @param data Estructura de _parse().
        @param rule_types Salida de _rule_type_labels().
        @return dict `{attributes_new: [nombres], values_new: int, rules_new: [textos]}`.
        """
        attributes = [a for a in data['attributes'].values() if a['values']]
        return {
            'attributes_new': sorted(a['name'] for a in attributes
                                     if not self._find('product.attribute', self._xmlid_name('attr', a['name']))),
            'values_new': sum(1 for a in attributes for value in a['values']
                              if not self._find('product.attribute.value', self._xmlid_name('val', a['name'], value))),
            'rules_new': sorted(f"{name} ({rule_types[rtype]})" for name, rtype in data['rules']
                                if not self._find('sembradora.accessory.rule', self._xmlid_name('rule', rtype, name))),
        }

    def _planned_templates(self, data):
        """Máquinas del CSV que ya existen en Odoo.

        @param data Estructura de _parse().
        @return dict {modelo: product.template} (solo las que existen).
        """
        templates = {modelo: self._find('product.template', self._xmlid_name('modelo', modelo)) for modelo in data['models']}
        return {modelo: tmpl for modelo, tmpl in templates.items() if tmpl}

    def _plan_machine(self, modelo, tmpl, data, matches):
        """Cambios de una máquina: configuraciones, accesorios y valores de atributo.

        @param modelo Nombre de la máquina en el CSV.
        @param tmpl Máquina en Odoo (None si es nueva).
        @param data Estructura de _parse().
        @param matches Salida de _match_configs().
        @return dict `{modelo, new, configs_new: [textos], configs_changed: [(id, [cambios])],
                configs_unchanged: int, configs_deleted: [textos], accessories_new: [nombres],
                accessories_archived: [nombres], accessories_restored: [nombres], attributes: [textos]}`.
        """
        tmpl = tmpl or self.env['product.template']
        configs = {key: config for key, config in data['configs'].items() if key[0] == modelo}
        return {
            'modelo': modelo,
            'new': not tmpl,
            **self._plan_configs(modelo, tmpl, configs, matches),
            **self._plan_accessories(modelo, tmpl, data),
            'attributes': self._plan_attribute_lines(tmpl, data['models'][modelo], data) if tmpl else [],
        }

    def _plan_configs(self, modelo, tmpl, configs, matches):
        """Configuraciones nuevas, modificadas (con el detalle), sin cambios y que se borran.

        @param modelo Nombre de la máquina en el CSV.
        @param tmpl Máquina en Odoo (vacía si es nueva).
        @param configs {clave: datos de _parse()} de esa máquina.
        @param matches Salida de _match_configs().
        @return dict con `configs_new`, `configs_changed`, `configs_unchanged` y `configs_deleted`.
        """
        plan = {'configs_new': [], 'configs_changed': [], 'configs_unchanged': 0}
        kept = self.env['sembradora.config.rel']
        for key, config_data in sorted(configs.items(), key=lambda item: item[1]['label']):
            config = matches[key]
            if not config:
                plan['configs_new'].append(f"{config_data['label']} · {self._amount(config_data['price'])}")
                continue
            kept |= config
            changes = self._config_changes(config, config_data, modelo)
            if changes:
                plan['configs_changed'].append((config_data['label'], changes))
            else:
                plan['configs_unchanged'] += 1
        plan['configs_deleted'] = sorted(self._stale_configs(tmpl, kept).mapped('name'))
        return plan

    def _stale_configs(self, tmpl, kept):
        """Configuraciones de una máquina que no están en el CSV (también las creadas a mano).

        @param tmpl Máquina (puede estar vacía).
        @param kept Configuraciones de la máquina que sí están en el CSV.
        @return Recordset de sembradora.config.rel.
        """
        Config = self.env['sembradora.config.rel']
        return (Config.search([('modelo_id', '=', tmpl.id)]) if tmpl else Config) - kept

    def _config_changes(self, config, config_data, modelo):
        """Diferencias entre una configuración y su fila del CSV, en texto.

        @param config Configuración existente.
        @param config_data Datos de la configuración en _parse().
        @param modelo Nombre de la máquina en el CSV.
        @return Lista de cambios ("Precio: 1.000,00 → 1.100,00", "+ Sensor (10,00)"…); vacía si es igual.
        """
        changes = []
        if float_compare(config.price, config_data['price'], precision_digits=2):
            changes.append(f"Precio: {self._amount(config.price)} → {self._amount(config_data['price'])}")
        if config_data['description'] and html2plaintext(config.description or '').strip() != config_data['description']:
            changes.append("Descripción")
        return changes + self._line_changes(config.accessory_line_ids, config_data['lines'], modelo)

    def _line_changes(self, lines, csv_lines, modelo):
        """Diferencias entre las líneas de accesorio de una configuración y las del CSV.

        @param lines Líneas actuales (sembradora.config.accessory.line).
        @param csv_lines Líneas del CSV (datos de _parse()).
        @param modelo Nombre de la máquina en el CSV.
        @return Lista de textos: `+ accesorio`, `− accesorio` o `accesorio: cambios`.
        """
        current = {line.product_id: line for line in lines}
        changes, seen = [], self.env['product.product']
        for csv_line in csv_lines:
            product = self._find('product.product', self._xmlid_name('acc', modelo, csv_line['name']))
            line = current.get(product)
            if not line:
                standard = ', estándar' if csv_line['is_standard'] else ''
                changes.append(f"+ {csv_line['name']} ({self._amount(csv_line['price'])}{standard})")
                continue
            seen |= product
            changes += [f"{csv_line['name']}: {diff}" for diff in self._line_diff(line, csv_line)]
        return changes + [f"− {product.name}" for product in current if product not in seen]

    def _line_diff(self, line, csv_line):
        """Diferencias de una línea de accesorio con su fila del CSV.

        @param line Línea actual.
        @param csv_line Línea del CSV (datos de _parse()).
        @return Lista de textos ("precio 50,00 → 55,00", "pasa a estándar"…).
        """
        diffs = []
        if float_compare(line.price, csv_line['price'], precision_digits=2):
            diffs.append(f"precio {self._amount(line.price)} → {self._amount(csv_line['price'])}")
        for field, label in (('is_standard', 'estándar'), ('is_trigger', 'habilitante')):
            if line[field] != csv_line[field]:
                diffs.append(f"pasa a {label}" if csv_line[field] else f"deja de ser {label}")
        old_rules = sorted(rule.name for rule in line.rule_ids)
        new_rules = sorted(name for name, _rtype in csv_line['rules'])
        if old_rules != new_rules:
            diffs.append(f"reglas {', '.join(old_rules) or '—'} → {', '.join(new_rules) or '—'}")
        return diffs

    def _plan_accessories(self, modelo, tmpl, data):
        """Accesorios de la máquina que se crean, se archivan (ya no están) o se reactivan.

        @param modelo Nombre de la máquina en el CSV.
        @param tmpl Máquina en Odoo (vacía si es nueva).
        @param data Estructura de _parse().
        @return dict con `accessories_new`, `accessories_archived` y `accessories_restored`.
        """
        Product = self.env['product.product']
        names = sorted(nombre for m, nombre in data['accessories'] if m == modelo)
        found = {nombre: self._find(Product._name, self._xmlid_name('acc', modelo, nombre)) for nombre in names}
        keep = Product.union(*found.values())
        return {
            'accessories_new': [nombre for nombre, product in found.items() if not product],
            'accessories_restored': [nombre for nombre, product in found.items() if product and not product.active],
            'accessories_archived': sorted(self._stale_accessories(tmpl, keep).mapped('name')),
        }

    def _stale_accessories(self, tmpl, keep):
        """Accesorios activos de una máquina que no están en el CSV (también los creados a mano).

        @param tmpl Máquina (puede estar vacía).
        @param keep Accesorios de la máquina que sí están en el CSV.
        @return Recordset de product.product.
        """
        Product = self.env['product.product']
        return (Product.search([('cotizador_modelo_id', '=', tmpl.id)]) if tmpl else Product) - keep

    def _plan_attribute_lines(self, tmpl, model_values, data):
        """Valores de atributo que la máquina gana o pierde (y atributos que deja de usar).

        Solo atributos que crean variantes ("Siempre"): son los que definen las configuraciones.

        @param tmpl Máquina existente.
        @param model_values {columna: valores} de la máquina en el CSV.
        @param data Estructura de _parse().
        @return Lista de textos ("Lineas: + 20 Lineas", "Distancia: − 70 cm", "Tolva: se quita").
        """
        wanted = self._wanted_attribute_values(model_values, data)
        changes = []
        for ptal in tmpl.attribute_line_ids.filtered(lambda l: l.attribute_id.create_variant == 'always'):
            names = wanted.pop(ptal.attribute_id, None)
            if names is None:
                changes.append(f"{ptal.attribute_id.name}: se quita de la máquina")
                continue
            current = set(ptal.value_ids.mapped('name'))
            changes += [f"{ptal.attribute_id.name}: + {n}" for n in sorted(names - current)]
            changes += [f"{ptal.attribute_id.name}: − {n}" for n in sorted(current - names)]
        # Lo que queda son atributos que la máquina todavía no tiene
        changes += [f"{getattr(key, 'name', key)}: + {', '.join(sorted(names))}" for key, names in wanted.items()]
        return changes

    def _wanted_attribute_values(self, model_values, data):
        """Valores que la máquina debe tener por atributo, según el CSV.

        @param model_values {columna: valores} de la máquina en el CSV.
        @param data Estructura de _parse().
        @return dict {product.attribute (o el nombre, si el atributo es nuevo): set(nombres de valor)}.
        """
        wanted = {}
        for col, values in model_values.items():
            name = data['attributes'][col]['name']
            wanted[self._find('product.attribute', self._xmlid_name('attr', name)) or name] = set(values)
        return wanted

    def _stale_rules(self, data, templates):
        """Reglas creadas por el importador que no están en el CSV y que nadie va a usar.

        Una regla de otra máquina (que no está en el CSV) sigue en uso y no se borra. Las reglas
        creadas a mano no se tocan.

        @param data Estructura de _parse().
        @param templates {modelo: product.template} de las máquinas del CSV que ya existen.
        @return Recordset de sembradora.accessory.rule.
        """
        Rule = self.env['sembradora.accessory.rule']
        csv_names = {self._xmlid_name('rule', rtype, name) for name, rtype in data['rules']}
        imported = self.env['ir.model.data'].search([('module', '=', IMPORT_MODULE), ('model', '=', Rule._name)])
        candidates = Rule.browse([x.res_id for x in imported if x.name not in csv_names]).exists()
        machine_ids = [tmpl.id for tmpl in templates.values()]
        in_use = self.env['sembradora.config.accessory.line'].search([
            ('rule_ids', 'in', candidates.ids), ('config_id.modelo_id', 'not in', machine_ids),
        ]).rule_ids
        return candidates - in_use

    def _amount(self, amount):
        """Importe con el formato del idioma del usuario (para el detalle de cambios).

        @param amount Número.
        @return Texto, p. ej. "1.000,00".
        """
        return formatLang(self.env, amount, digits=2)

    # =========================================================================
    #  PASO 1: ANÁLISIS
    # =========================================================================

    def action_analyze(self):
        """Paso 1: valida los archivos y resume lo que se creará o actualizará. No escribe datos.

        @return Acción que reabre el asistente en estado `analyzed`.
        @throws UserError Si no hay archivos.
        """
        self.ensure_one()
        notes = []
        files = self._read_files(notes)
        return self._analyze(files, any((att.name or '').lower().endswith('.xlsx') for att in self.csv_file_ids), notes)

    def _analyze(self, files, from_sheets=False, notes=()):
        """Valida los archivos leídos, arma el resumen y los guarda para importarlos tal cual.

        @param files Lista como _read_files().
        @param from_sheets Algún archivo vino de una planilla: deja además el CSV normalizado para
               descargar, para revisar cómo se leyó.
        @param notes Avisos de la lectura (filas ocultas no leídas), que se muestran en el resumen.
        @return Acción que reabre el asistente en estado `analyzed`.
        """
        data, errors = self._parse(files)
        summary = self._build_analysis_html(data, errors, None if errors else self._plan_changes(data))
        if notes:
            summary = Markup('<div style="font-size: 13px; color: #8a6d00;"><p>⚠️ Lo que no se leyó (oculto en la '
                             'planilla): revise que no falte ninguna configuración.</p>%s</div>') % (
                self._html_list(list(notes))) + summary
        self.write({
            'state': 'analyzed',
            'has_errors': bool(errors),
            'analysis_summary': summary,
            'parsed_data': json.dumps(files),
            'normalized_csv': base64.b64encode(self._normalized_csv(files)) if from_sheets else False,
            'normalized_csv_name': 'matriz_normalizada.csv' if from_sheets else False,
        })
        return self._reopen()

    def _normalized_csv(self, files):
        """Los archivos leídos en un solo CSV con el formato del importador (re-importable).

        @param files Lista como _read_files().
        @return Bytes del CSV (UTF-8 con BOM, para que Excel muestre bien los acentos).
        """
        header = list(FIXED_COLUMNS)
        for _name, file_header, _rows in files:
            header += [c for c in file_header if c.startswith(ATTRIBUTE_PREFIX) and c not in header]
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=header, extrasaction='ignore', lineterminator='\n')
        writer.writeheader()
        for _name, _header, rows in files:
            writer.writerows(row for _line, row in rows)
        return out.getvalue().encode('utf-8-sig')

    def action_back_to_upload(self):
        """Vuelve a la carga de archivos descartando el análisis.

        @return Acción que reabre el asistente.
        """
        self.write({'state': 'draft', 'has_errors': False, 'analysis_summary': False, 'parsed_data': False,
                    'normalized_csv': False, 'normalized_csv_name': False})
        return self._reopen()

    def _reopen(self):
        """Acción que reabre este asistente (los botones de un asistente lo cierran si no).

        @return Acción de ventana.
        """
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _build_analysis_html(self, data, errors, plan):
        """Resumen del análisis: moneda, errores y, si no hay errores, el detalle de lo que va a cambiar.

        @param data Estructura de _parse().
        @param errors Mensajes de error (se muestran los primeros DETAIL_LIMIT).
        @param plan Salida de _plan_changes(), o None si hay errores.
        @return Markup.
        """
        html = Markup('<div style="font-size: 13px;">')
        html += Markup('<p>💱 Moneda de los precios: <b>%s</b> (se guarda en los modelos y accesorios importados)</p>') % (
            self.currency_id.name)
        if errors:
            html += Markup('<h3 style="color: #c62828;">❌ %s errores: corríjalos y vuelva a analizar</h3>') % len(errors)
            return html + self._html_list(errors, color='#c62828') + Markup('</div>')
        html += Markup('<h3>Lo que va a cambiar al importar</h3>')
        html += Markup('<p>Cada máquina del archivo queda <b>igual al CSV</b>: lo que no está se borra (los '
                       'accesorios se archivan). Las máquinas que no están en el archivo no se tocan.</p>')
        deleted = sum(len(m['configs_deleted']) for m in plan['machines'])
        if deleted:
            html += Markup('<p style="color: #c62828;">⚠️ Se van a borrar configuraciones: <b>%s</b>. '
                           'Revise la lista antes de importar.</p>') % deleted
        lines = [line for (m, _c), c in data['configs'].items() for line in c['lines']]
        html += Markup('<p>⭐ Líneas de accesorio: <b>%s</b> (estándar: <b>%s</b>)</p>') % (
            len(lines), sum(1 for line in lines if line['is_standard']))
        if data['qty_columns']:
            html += Markup('<p>📐 Atributos de cantidad (Calc_param): %s</p>') % ', '.join(
                data['attributes'][col]['name'] for col in sorted(data['qty_columns']))
        return html + self._changes_html(plan) + Markup('</div>')

    def _changes_html(self, plan):
        """Detalle de cambios: una tabla por máquina con los totales y una lista desplegable por tipo.

        Es el mismo texto antes de importar (análisis) y después (log y chatter de cada máquina).

        @param plan Salida de _plan_changes().
        @return Markup.
        """
        html = Markup('<table class="table table-sm w-auto"><tr><th>Máquina</th><th>Configuraciones nuevas</th>'
                      '<th>Modificadas</th><th>Sin cambios</th><th>Borradas</th><th>Accesorios nuevos</th>'
                      '<th>Archivados</th></tr>')
        for machine in plan['machines']:
            html += Markup('<tr><td>%s%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>') % (
                machine['modelo'], ' (nueva)' if machine['new'] else '', len(machine['configs_new']),
                len(machine['configs_changed']), machine['configs_unchanged'], len(machine['configs_deleted']),
                len(machine['accessories_new']), len(machine['accessories_archived']))
        html += Markup('</table>')
        for machine in plan['machines']:
            html += self._machine_changes_html(machine)
        for label, items in (('Atributos nuevos', plan['attributes_new']), ('Reglas nuevas', plan['rules_new']),
                             ('Reglas que se borran (ya no las usa nadie)', plan['rules_deleted'])):
            html += self._html_details(label, items)
        if plan['values_new']:
            html += Markup('<p>Valores de atributo nuevos: <b>%s</b></p>') % plan['values_new']
        return html

    def _machine_changes_html(self, machine):
        """Detalle de una máquina: listas desplegables de lo que se crea, cambia, borra o archiva.

        @param machine Un elemento de `machines` de _plan_changes().
        @return Markup (vacío si la máquina no cambia).
        """
        changed = [Markup('<b>%s</b>: %s') % (label, '; '.join(changes)) for label, changes in machine['configs_changed']]
        sections = (
            ('Configuraciones nuevas', machine['configs_new']),
            ('Configuraciones modificadas', changed),
            ('Configuraciones que se borran', machine['configs_deleted']),
            ('Accesorios nuevos', machine['accessories_new']),
            ('Accesorios que se archivan (ya no están en el CSV)', machine['accessories_archived']),
            ('Accesorios que se reactivan', machine['accessories_restored']),
            ('Valores de atributo', machine['attributes']),
        )
        body = Markup().join(self._html_details(label, items) for label, items in sections)
        return Markup('<h4>%s</h4>%s') % (machine['modelo'], body) if body else Markup()

    def _html_details(self, label, items):
        """Lista desplegable con su cantidad en el título.

        @param label Título.
        @param items Textos (o Markup).
        @return Markup (vacío si no hay elementos).
        """
        if not items:
            return Markup()
        return Markup('<details><summary>%s: <b>%s</b></summary>%s</details>') % (
            label, len(items), self._html_list(items))

    def _html_list(self, items, color=None):
        """Lista HTML de hasta DETAIL_LIMIT elementos, con "… y N más".

        @param items Textos (o Markup).
        @param color Color del texto (opcional).
        @return Markup.
        """
        style = Markup(' style="color: %s;"') % color if color else Markup()
        html = Markup('<ul>') + Markup().join(Markup('<li%s>%s</li>') % (style, item) for item in items[:DETAIL_LIMIT])
        if len(items) > DETAIL_LIMIT:
            html += Markup('<li><i>… y %s más.</i></li>') % (len(items) - DETAIL_LIMIT)
        return html + Markup('</ul>')

    # =========================================================================
    #  PASO 2: IMPORTACIÓN
    # =========================================================================

    def action_import(self):
        """Paso 2: deja cada máquina del CSV igual al archivo, en una sola transacción.

        Vuelve a validar `parsed_data`; si hay errores no escribe nada. Calcula el plan de cambios
        antes de escribir (es el log que se muestra y se publica en el chatter de cada máquina) y
        después crea o actualiza, borra las configuraciones que no están, archiva los accesorios
        que faltan y borra las reglas del importador que ya no se usan. Corre con sudo (el
        asistente es solo del administrador y crea productos, atributos y categorías).

        @return Acción que reabre el asistente con el log de cambios.
        @throws UserError Si no se analizó, el CSV tiene errores o una regla manual tiene el
                mismo nombre y tipo que una del CSV.
        """
        self.ensure_one()
        if self.state != 'analyzed' or not self.parsed_data:
            raise UserError("Primero debe analizar el CSV.")
        # El wizard solo es accesible al grupo Administrador del Configurador (ACL); los datos
        # maestros que necesita (productos, atributos, categorías) se crean con sudo.
        # Sin generar variantes mientras se crean atributos y configuraciones: se sincronizan
        # una sola vez al final, cuando la matriz está completa.
        self = self.sudo().with_context(cotizador_skip_variants=True)
        data, errors = self._parse(json.loads(self.parsed_data))
        if errors:
            raise UserError("El CSV tiene errores; vuelva a analizarlo:\n" + "\n".join(errors[:50]))
        plan = self._plan_changes(data)

        values = self._import_attributes(data)
        qty_categories = self._import_qty_categories(data, values)
        templates = self._import_models(data, values)
        matches = self._match_configs(data, templates)
        self._delete_stale_configs(templates, matches)
        accessories = self._import_accessories(data, templates, qty_categories)
        rules = self._import_rules(data)
        self._import_configs(data, values, templates, accessories, rules, matches)
        self._archive_stale_accessories(templates, accessories)
        self._stale_rules(data, templates).unlink()
        self.env['product.template'].union(*templates.values()).with_context(
            cotizador_skip_variants=False)._cotizador_sync_variants()
        self._log_changes(plan, templates)

        self.write({
            'state': 'done',
            'analysis_summary': Markup('<div style="font-size: 13px;"><h3>✅ Importación completada</h3>'
                                       '<p>Cambios aplicados (también quedan en el chatter de cada máquina):</p>')
                                + self._changes_html(plan) + Markup('</div>'),
        })
        return self._reopen()

    def _delete_stale_configs(self, templates, matches):
        """Borra las configuraciones de cada máquina del CSV que no están en el archivo.

        Va antes de crear las nuevas: así una combinación que pasa de una configuración borrada a
        una nueva no choca con la restricción de combinación única. Las variantes se quitan al final
        (las usadas en ventas se archivan) y una oportunidad que pedía esa configuración la pierde.

        @param templates Salida de _import_models().
        @param matches Salida de _match_configs() (las configuraciones que siguen).
        """
        Config = self.env['sembradora.config.rel']
        for modelo, tmpl in templates.items():
            kept = Config.union(*(config for (m, _combination), config in matches.items() if m == modelo))
            self._stale_configs(tmpl, kept).unlink()

    def _archive_stale_accessories(self, templates, accessories):
        """Archiva los accesorios de cada máquina del CSV que ya no están en el archivo.

        Se archivan y no se borran porque pueden estar en cotizaciones. Si vuelven al CSV, la
        importación los reactiva (_import_accessories()).

        @param templates Salida de _import_models().
        @param accessories Salida de _import_accessories().
        """
        Product = self.env['product.product']
        for modelo, tmpl in templates.items():
            keep = Product.union(*(product for (m, _nombre), product in accessories.items() if m == modelo))
            self._stale_accessories(tmpl, keep).product_tmpl_id.write({'active': False})

    def _log_changes(self, plan, templates):
        """Deja el detalle de cambios en el chatter de cada máquina que cambió, y un resumen en el log.

        @param plan Salida de _plan_changes() (calculado antes de escribir).
        @param templates Salida de _import_models().
        """
        for machine in plan['machines']:
            detail = self._machine_changes_html(machine)
            _logger.info("Importación de la matriz, %s: %s nuevas, %s modificadas, %s borradas; "
                         "%s accesorios nuevos, %s archivados", machine['modelo'], len(machine['configs_new']),
                         len(machine['configs_changed']), len(machine['configs_deleted']),
                         len(machine['accessories_new']), len(machine['accessories_archived']))
            if detail:
                templates[machine['modelo']].message_post(
                    body=Markup('<p>Importación de la matriz (%s):</p>%s') % (
                        ', '.join(name for name, _header, _rows in json.loads(self.parsed_data)), detail))

    def _import_attributes(self, data):
        """Crea atributos (variantes "Siempre") y valores; guarda la cantidad de los de cantidad.

        @param data Estructura de _parse().
        @return dict {(columna, valor): product.attribute.value}.
        """
        values = {}
        for sequence, (col, attr_data) in enumerate(data['attributes'].items(), start=1):
            if not attr_data['values']:
                continue
            attribute = self._find_or_create('product.attribute', self._xmlid_name('attr', attr_data['name']), {
                'name': attr_data['name'], 'create_variant': 'always',
            })
            if attribute.create_variant != 'always':
                raise UserError(f"El atributo '{attribute.name}' crea variantes en modo '{attribute.create_variant}'; "
                                f"el cotizador necesita el modo 'Siempre' (una variante por configuración).")
            attribute.sequence = sequence * 10
            for value_name, qty in attr_data['values'].items():
                value = self._find_or_create(
                    'product.attribute.value', self._xmlid_name('val', attr_data['name'], value_name),
                    {'name': value_name, 'attribute_id': attribute.id},
                )
                if col in data['qty_columns'] and value.cotizador_qty != qty:
                    value.cotizador_qty = qty
                values[col, value_name] = value
        return values

    def _import_qty_categories(self, data, values):
        """Una subcategoría de *Accesorio* por atributo de cantidad, vinculada a él.

        @param data Estructura de _parse().
        @param values Salida de _import_attributes().
        @return dict {columna: product.category}.
        """
        cat_base = self.env.ref('cotizador.cat_accesorio_base')
        categories = {}
        for col in data['qty_columns']:
            attribute = next(v.attribute_id for (c, _name), v in values.items() if c == col)
            categ = self._find_or_create('product.category', self._xmlid_name('qty', attribute.name), {
                'name': attribute.name, 'parent_id': cat_base.id,
            })
            if categ.cotizador_qty_attribute_id != attribute:
                categ.cotizador_qty_attribute_id = attribute
            categories[col] = categ
        return categories

    def _import_models(self, data, values):
        """Máquinas (categoría *Máquina*) con la moneda elegida y sus líneas de atributo.

        Las líneas de atributo quedan con exactamente los valores del CSV y en el orden de las
        columnas; las de atributos "Siempre" que la máquina ya no usa se quitan.

        @param data Estructura de _parse().
        @param values Salida de _import_attributes().
        @return dict {modelo: product.template}.
        """
        cat_maquina = self.env.ref('cotizador.cat_maquina')
        attr_sequence = {col: i * 10 for i, col in enumerate(data['attributes'], start=1)}
        templates = {}
        for modelo, model_values in data['models'].items():
            tmpl = self._find_or_create('product.template', self._xmlid_name('modelo', modelo), {
                'name': modelo, 'categ_id': cat_maquina.id, 'type': 'consu',
                'cotizador_currency_id': self.currency_id.id,
            })
            if tmpl.cotizador_currency_id != self.currency_id:
                tmpl.cotizador_currency_id = self.currency_id
            for col, value_names in model_values.items():
                value_records = self.env['product.attribute.value'].union(*(values[col, v] for v in value_names))
                ptal = tmpl.attribute_line_ids.filtered(lambda l: l.attribute_id == value_records.attribute_id)
                if ptal:
                    ptal.write({'sequence': attr_sequence[col], 'value_ids': [Command.set(value_records.ids)]})
                else:
                    self.env['product.template.attribute.line'].create({
                        'product_tmpl_id': tmpl.id, 'attribute_id': value_records.attribute_id.id,
                        'sequence': attr_sequence[col], 'value_ids': [Command.set(value_records.ids)],
                    })
            used = self.env['product.attribute'].union(*(values[col, v].attribute_id for col, names in model_values.items() for v in names))
            tmpl.attribute_line_ids.filtered(
                lambda l: l.attribute_id.create_variant == 'always' and l.attribute_id not in used).unlink()
            templates[modelo] = tmpl
        return templates

    def _import_accessories(self, data, templates, qty_categories):
        """Accesorios: uno por (modelo, nombre), con su categoría, modelo y moneda.

        El mismo nombre en dos modelos son dos productos. Si ya existen se actualizan solo
        categoría, modelo y moneda (el nombre puede haberse cambiado en Odoo), y se reactivan si
        estaban archivados porque habían salido del CSV.

        @param data Estructura de _parse().
        @param templates Salida de _import_models().
        @param qty_categories Salida de _import_qty_categories().
        @return dict {(modelo, nombre): product.product}.
        """
        cat_base = self.env.ref('cotizador.cat_accesorio_base')
        accessories = {}
        for (modelo, nombre), calc_param in data['accessories'].items():
            vals = {
                'categ_id': (qty_categories[calc_param] if calc_param else cat_base).id,
                'cotizador_modelo_id': templates[modelo].id,
                'cotizador_currency_id': self.currency_id.id,
            }
            product = self._find_or_create('product.product', self._xmlid_name('acc', modelo, nombre), {
                **vals, 'name': nombre, 'type': 'consu',
            })
            if not product.active:
                product.product_tmpl_id.active = True
                product.active = True
            product.product_tmpl_id.write({
                field: value for field, value in vals.items() if product.product_tmpl_id[field].id != value
            })
            accessories[modelo, nombre] = product
        return accessories

    def _import_rules(self, data):
        """Reglas: una por (nombre, tipo).

        @param data Estructura de _parse().
        @return dict {(nombre, tipo): sembradora.accessory.rule}.
        @throws UserError Si existe una regla creada a mano con el mismo nombre y tipo.
        """
        Rule = self.env['sembradora.accessory.rule']
        rules = {}
        for name, rtype in data['rules']:
            xmlid_name = self._xmlid_name('rule', rtype, name)
            if not self._find(Rule._name, xmlid_name) and Rule.search_count([('name', '=', name), ('rule_type', '=', rtype)]):
                # La restricción unique(name, rule_type) impediría crearla: avisar claramente
                raise UserError(f"Ya existe una regla '{name}' ({rtype}) creada fuera del importador. "
                                f"Renómbrela o elimínela antes de importar.")
            rules[name, rtype] = self._find_or_create(
                Rule._name, xmlid_name, {'name': name, 'rule_type': rtype},
            )
        return rules

    def _import_configs(self, data, values, templates, accessories, rules, matches):
        """Crea las configuraciones nuevas y actualiza solo lo que cambió.

        Una configuración igual al CSV no se escribe (re-importar el mismo archivo no toca la base).
        Si alguna línea de accesorio cambió se reemplazan todas, junto con los datos y en una sola
        escritura: las restricciones (reglas, accesorios del mismo modelo) se validan sobre el estado final.

        @param data Estructura de _parse().
        @param values Salida de _import_attributes().
        @param templates Salida de _import_models().
        @param accessories Salida de _import_accessories().
        @param rules Salida de _import_rules().
        @param matches Salida de _match_configs().
        """
        Config = self.env['sembradora.config.rel']
        for key, config_data in data['configs'].items():
            modelo, config = key[0], matches[key]
            if not config:
                Config.create({
                    'modelo_id': templates[modelo].id,
                    'value_ids': [Command.set([values[col, v].id for col, v in config_data['values'].items()])],
                    'price': config_data['price'],
                    'description': config_data['description'] or False,
                    'accessory_line_ids': self._line_commands(modelo, config_data, accessories, rules),
                })
                continue
            changed = self._changed_config_vals(config, config_data)
            if self._line_changes(config.accessory_line_ids, config_data['lines'], modelo):
                changed['accessory_line_ids'] = [Command.delete(line.id) for line in config.accessory_line_ids] + \
                    self._line_commands(modelo, config_data, accessories, rules)
            if changed:
                config.write(changed)

    def _line_commands(self, modelo, config_data, accessories, rules):
        """Comandos que crean las líneas de accesorio de una configuración del CSV.

        @param modelo Nombre de la máquina.
        @param config_data Configuración de _parse().
        @param accessories Salida de _import_accessories().
        @param rules Salida de _import_rules().
        @return Lista de Command.create.
        """
        return [Command.create({
            'product_id': accessories[modelo, line['name']].id,
            'price': line['price'],
            'is_standard': line['is_standard'],
            'is_trigger': line['is_trigger'],
            'rule_ids': [Command.set([rules[r].id for r in line['rules']])],
        }) for line in config_data['lines']]

    def _changed_config_vals(self, config, config_data):
        """Precio y descripción de la configuración, si difieren del CSV.

        @param config Configuración existente (misma máquina y combinación).
        @param config_data Datos de la configuración en _parse().
        @return dict para write() (vacío si no cambió nada).
        """
        changed = {}
        if float_compare(config.price, config_data['price'], precision_digits=2):
            changed['price'] = config_data['price']
        if config_data['description'] and html2plaintext(config.description or '').strip() != config_data['description']:
            changed['description'] = config_data['description']
        return changed
