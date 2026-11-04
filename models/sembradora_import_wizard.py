"""@file
Importador CSV de la matriz de ingeniería (asistente `sembradora.import.wizard`).

Formato y reglas para el usuario: docs/importador.md. Diseño:

1. **Análisis** (action_analyze()): lee los archivos, los valida completos (_parse() y
   _validate_parsed()) y muestra errores con archivo y línea y un resumen. No escribe nada.
2. **Importación** (action_import()): vuelve a validar exactamente lo analizado y escribe todo en
   la misma transacción, en orden: atributos y valores, categorías de cantidad, modelos (con sus
   valores exactos), borrado de las configuraciones que ya no están, accesorios, reglas,
   configuraciones, archivado de los accesorios que ya no están y borrado de las reglas sin uso.

**Espejo del CSV**: cada máquina del archivo queda igual al CSV; las que no están no se tocan. El
plan de cambios (_plan_changes()) se muestra al analizar y, después de importar, queda como log en
el asistente y en el chatter de cada máquina.

**Identidad**: el importador nunca busca por nombre. Lo que crea queda con un xmlid del módulo
IMPORT_MODULE armado con el texto del CSV (_xmlid_name()); al re-importar se lo encuentra por
ese xmlid aunque se haya renombrado en Odoo.
"""
import csv
import io
import json
import logging
import re
import unicodedata

from markupsafe import Markup

from odoo import Command, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare, formatLang, html2plaintext

from .sembradora_config import validate_rule_set

_logger = logging.getLogger(__name__)

## Módulo de los xmlids que el importador asigna a lo que crea: es su única forma de
## reencontrar registros (nunca busca por nombre), así renombrar en Odoo no rompe la re-importación.
IMPORT_MODULE = 'cotizador_import'

## Columnas con significado fijo. Las de atributos llevan el prefijo ATTRIBUTE_PREFIX.
FIXED_COLUMNS = {
    'ID_Configuracion', 'Modelo', 'Tipo_Item', 'Precio_Base', 'Nombre_Item', 'Precio_Item',
    'Calc_param', 'Reglas', 'Descripcion',
}
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


def _strip_accents(text):
    """Quita acentos y diacríticos: 'Líneas' → 'Lineas'.

    @param text Texto.
    @return Texto sin marcas diacríticas.
    """
    return ''.join(c for c in unicodedata.normalize('NFD', text) if unicodedata.category(c) != 'Mn')


def slugify(text):
    """Convierte un texto en parte de un xmlid: 'Cantidad de Líneas' → 'cantidad_de_lineas'.

    @param text Texto del CSV.
    @return Minúsculas sin acentos, con `_` en lugar de cualquier otro símbolo.
    """
    return re.sub(r'[^a-z0-9]+', '_', _strip_accents(text).lower()).strip('_')


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


class SembradoraImportWizard(models.TransientModel):
    """Asistente de importación (`sembradora.import.wizard`), solo Administrador del Configurador.

    Estados: `draft` (carga de archivos y moneda) → `analyzed` (resumen y errores) → `done`.
    `parsed_data` guarda los archivos leídos en el análisis para importar exactamente eso.
    """
    _name = 'sembradora.import.wizard'
    _description = 'Importador CSV de Configuraciones de Sembradora'

    csv_file_ids = fields.Many2many('ir.attachment', string='Archivos CSV')
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

    # =========================================================================
    #  LECTURA Y VALIDACIÓN (sin escribir nada)
    # =========================================================================

    def _read_files(self):
        """Lee los CSV adjuntos (UTF-8 con o sin BOM; si falla, Latin-1).

        @return Lista de tuplas `(nombre_archivo, encabezado, [(número_de_línea, fila), ...])`,
                con cada fila como dict {columna: valor}. Es serializable a JSON (parsed_data).
        @throws UserError Si no hay archivos.
        """
        if not self.csv_file_ids:
            raise UserError("Seleccione al menos un archivo CSV.")
        files = []
        for att in self.csv_file_ids:
            raw = att.raw or b''
            try:
                text = raw.decode('utf-8-sig')
            except UnicodeDecodeError:
                text = raw.decode('latin-1')
            reader = csv.DictReader(io.StringIO(text))
            rows = [(reader.line_num, row) for row in reader]
            files.append((att.name, reader.fieldnames or [], rows))
        return files

    def _parse(self, files):
        """Valida los archivos completos y los convierte a una estructura independiente de Odoo.

        No consulta la base salvo para la moneda: el mismo análisis sirve para mostrar y para importar.

        @param files Salida de _read_files() (o su copia de `parsed_data`).
        @return Tupla `(data, errors)`. `data` tiene `attributes` {columna: {name, values:
                {valor: cantidad}}}, `qty_columns`, `models` {modelo: {columna: valores}},
                `accessories` {(modelo, nombre): Calc_param}, `rules` {(nombre, tipo)} y
                `configs` {(modelo, id): {modelo, conf_id, base, values, price, description,
                lines}}. Si `errors` no está vacía no se debe importar.
        """
        errors = []
        data = {
            'attributes': {},      # columna → {'name', 'values': {valor: cantidad|None}}
            'qty_columns': set(),  # columnas de atributo usadas como Calc_param
            'models': {},          # modelo → {columna: set(valores)}
            'accessories': {},     # (modelo, nombre) → columna Calc_param ('' si no tiene)
            'rules': set(),        # (nombre, tipo)
            'configs': {},         # (modelo, id) → {...}
        }
        accessory_origin = {}

        for fname, header, rows in files:
            unknown = [c for c in header if c not in FIXED_COLUMNS and not c.startswith(ATTRIBUTE_PREFIX)]
            if unknown:
                errors.append(
                    f"{fname}: columnas desconocidas {', '.join(unknown)}. Las columnas de atributos "
                    f"deben empezar con '{ATTRIBUTE_PREFIX}' (p.ej. {ATTRIBUTE_PREFIX}Cantidad_de_Lineas)."
                )
                continue
            missing = {'ID_Configuracion', 'Modelo', 'Tipo_Item'} - set(header)
            if missing:
                errors.append(f"{fname}: faltan las columnas {', '.join(sorted(missing))}.")
                continue
            attr_columns = [c for c in header if c.startswith(ATTRIBUTE_PREFIX)]
            for col in attr_columns:
                name = col[len(ATTRIBUTE_PREFIX):].replace('_', ' ').strip()
                if not name:
                    errors.append(f"{fname}: la columna '{col}' no tiene nombre de atributo.")
                data['attributes'].setdefault(col, {'name': name, 'values': {}})

            for line_num, row in rows:
                where = f"{fname}, línea {line_num}"
                cell = {k: (v or '').strip() for k, v in row.items() if k}
                tipo = _strip_accents(cell.get('Tipo_Item', '')).upper()
                modelo, conf_id = cell.get('Modelo', ''), cell.get('ID_Configuracion', '')
                if tipo not in ITEM_TYPES:
                    errors.append(f"{where}: Tipo_Item '{cell.get('Tipo_Item', '')}' inválido "
                                  f"(use BASE, OPCIONAL o ESTANDAR).")
                    continue
                if not modelo or not conf_id:
                    errors.append(f"{where}: Modelo e ID_Configuracion son obligatorios.")
                    continue
                config = data['configs'].setdefault((modelo, conf_id), {
                    'modelo': modelo, 'conf_id': conf_id, 'base': False,
                    'values': {}, 'price': 0.0, 'description': '', 'lines': [],
                })

                if tipo == TYPE_BASE:
                    if config['base']:
                        errors.append(f"{where}: la configuración {modelo}/{conf_id} tiene más de una fila BASE.")
                        continue
                    price = parse_price(cell.get('Precio_Base'))
                    if price is None:
                        errors.append(f"{where}: Precio_Base '{cell.get('Precio_Base', '')}' no es un precio válido.")
                    errors += self._check_price_currency(where, 'Precio_Base', cell.get('Precio_Base'))
                    config.update(base=True, price=price or 0.0, description=cell.get('Descripcion', ''))
                    model_values = data['models'].setdefault(modelo, {})
                    for col in attr_columns:
                        if cell.get(col):
                            config['values'][col] = cell[col]
                            data['attributes'][col]['values'].setdefault(cell[col], None)
                            model_values.setdefault(col, set()).add(cell[col])
                    if not config['values']:
                        errors.append(f"{where}: la fila BASE no tiene valores de atributos ({ATTRIBUTE_PREFIX}…).")
                    continue

                # Accesorio (OPCIONAL / ESTANDAR)
                nombre = cell.get('Nombre_Item', '')
                if not nombre:
                    errors.append(f"{where}: Nombre_Item es obligatorio en filas de accesorio.")
                    continue
                price = parse_price(cell.get('Precio_Item'))
                if price is None:
                    errors.append(f"{where}: Precio_Item '{cell.get('Precio_Item', '')}' no es un precio válido.")
                errors += self._check_price_currency(where, 'Precio_Item', cell.get('Precio_Item'))
                calc_param = cell.get('Calc_param', '')
                if calc_param and calc_param not in attr_columns:
                    errors.append(f"{where}: Calc_param '{calc_param}' debe ser el nombre exacto de una "
                                  f"columna de atributo del archivo ({', '.join(attr_columns) or 'no hay'}).")
                    continue
                if calc_param:
                    data['qty_columns'].add(calc_param)
                previous = data['accessories'].setdefault((modelo, nombre), calc_param)
                accessory_origin.setdefault((modelo, nombre), where)
                if previous != calc_param:
                    errors.append(f"{where}: '{nombre}' de {modelo} tiene Calc_param '{calc_param}', pero en "
                                  f"{accessory_origin[modelo, nombre]} tiene '{previous}'.")

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
                    errors.append(f"{where}: '{nombre}' aparece dos veces en la configuración {modelo}/{conf_id}.")
                    continue
                config['lines'].append({
                    'name': nombre, 'price': price or 0.0, 'calc_param': calc_param,
                    'is_standard': tipo == TYPE_STANDARD, 'is_trigger': is_trigger, 'rules': rules,
                })

        errors += self._validate_parsed(data)
        return data, errors

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
        (un valor por cada atributo que usa la máquina) y no repetidas, Calc_param presente en la
        fila BASE, reglas (validate_rule_set()) y textos que darían el mismo xmlid.

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
        for (modelo, _conf_id), config in data['configs'].items():
            model_columns.setdefault(modelo, set()).update(config['values'])

        combinations = {}
        for (modelo, conf_id), config in data['configs'].items():
            label = f"Configuración {modelo}/{conf_id}"
            if not config['base']:
                errors.append(f"{label}: no tiene fila BASE.")
                continue
            missing = sorted(model_columns[modelo] - set(config['values']))
            if missing:
                errors.append(f"{label}: no tiene valor en {', '.join(missing)}, que usan otras configuraciones de "
                              f"{modelo}. Cada configuración necesita un valor de cada atributo de la máquina "
                              f"(una variante por configuración).")
            combo = (modelo, frozenset(config['values'].items()))
            if combo in combinations:
                errors.append(f"{label}: misma combinación de atributos que {modelo}/{combinations[combo]}.")
            combinations.setdefault(combo, conf_id)
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
        for modelo in data['models']:
            check_slugs(f"ID_Configuracion de {modelo}", [c for m, c in data['configs'] if m == modelo])
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

    def _find_or_create(self, model, xmlid_name, create_vals, counters, counter_key):
        """Devuelve el registro del xmlid o lo crea (con su xmlid `noupdate`).

        @param model Modelo.
        @param xmlid_name Nombre del xmlid en IMPORT_MODULE.
        @param create_vals Valores para crearlo si no existe (no se aplican si ya existe).
        @param counters dict de contadores del resumen.
        @param counter_key Contador a incrementar si se crea.
        @return El registro.
        """
        record = self._find(model, xmlid_name)
        if not record:
            record = self.env[model].create(create_vals)
            self._register_xmlid(model, xmlid_name, record)
            counters[counter_key] += 1
        return record

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
        return {
            'machines': [self._plan_machine(modelo, data) for modelo in sorted(data['models'])],
            **self._plan_master_data(data, rule_types),
            'rules_deleted': sorted(f"{rule.name} ({rule_types[rule.rule_type]})"
                                    for rule in self._stale_rules(data, self._planned_templates(data))),
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

    def _plan_machine(self, modelo, data):
        """Cambios de una máquina: configuraciones, accesorios y valores de atributo.

        @param modelo Nombre de la máquina en el CSV.
        @param data Estructura de _parse().
        @return dict `{modelo, new, configs_new: [textos], configs_changed: [(id, [cambios])],
                configs_unchanged: int, configs_deleted: [textos], accessories_new: [nombres],
                accessories_archived: [nombres], accessories_restored: [nombres], attributes: [textos]}`.
        """
        tmpl = self._find('product.template', self._xmlid_name('modelo', modelo))
        configs = {conf_id: config for (m, conf_id), config in data['configs'].items() if m == modelo}
        return {
            'modelo': modelo,
            'new': not tmpl,
            **self._plan_configs(modelo, tmpl, configs),
            **self._plan_accessories(modelo, tmpl, data),
            'attributes': self._plan_attribute_lines(tmpl, data['models'][modelo], data) if tmpl else [],
        }

    def _plan_configs(self, modelo, tmpl, configs):
        """Configuraciones nuevas, modificadas (con el detalle), sin cambios y que se borran.

        @param modelo Nombre de la máquina en el CSV.
        @param tmpl Máquina en Odoo (vacía si es nueva).
        @param configs {ID_Configuracion: datos de _parse()} de esa máquina.
        @return dict con `configs_new`, `configs_changed`, `configs_unchanged` y `configs_deleted`.
        """
        Config = self.env['sembradora.config.rel']
        plan = {'configs_new': [], 'configs_changed': [], 'configs_unchanged': 0}
        kept = Config
        for conf_id in sorted(configs):
            config = self._find(Config._name, self._xmlid_name('cfg', modelo, conf_id))
            if not config:
                values = ', '.join(sorted(configs[conf_id]['values'].values()))
                plan['configs_new'].append(f"{conf_id} · {values} · {self._amount(configs[conf_id]['price'])}")
                continue
            kept |= config
            changes = self._config_changes(config, configs[conf_id], modelo)
            if changes:
                plan['configs_changed'].append((conf_id, changes))
            else:
                plan['configs_unchanged'] += 1
        stale = self._stale_configs(tmpl, kept)
        plan['configs_deleted'] = sorted(f"{config.ext_id or '—'} · {config.name}" for config in stale)
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
        old_values, new_values = sorted(config.value_ids.mapped('name')), sorted(config_data['values'].values())
        if old_values != new_values:
            changes.append(f"Combinación: {', '.join(old_values)} → {', '.join(new_values)}")
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
        files = self._read_files()
        data, errors = self._parse(files)
        self.write({
            'state': 'analyzed',
            'has_errors': bool(errors),
            'analysis_summary': self._build_analysis_html(data, errors, None if errors else self._plan_changes(data)),
            'parsed_data': json.dumps(files),
        })
        return self._reopen()

    def action_back_to_upload(self):
        """Vuelve a la carga de archivos descartando el análisis.

        @return Acción que reabre el asistente.
        """
        self.write({'state': 'draft', 'has_errors': False, 'analysis_summary': False, 'parsed_data': False})
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
        changed = [Markup('<b>%s</b>: %s') % (conf_id, '; '.join(changes)) for conf_id, changes in machine['configs_changed']]
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

        counters = dict.fromkeys([
            'configs_created', 'configs_updated', 'lines', 'standard_lines', 'models_created',
            'accessories_created', 'attributes_created', 'values_created', 'categories_created',
            'rules_created',
        ], 0)
        values = self._import_attributes(data, counters)
        qty_categories = self._import_qty_categories(data, values, counters)
        templates = self._import_models(data, values, counters)
        self._delete_stale_configs(data, templates)
        accessories = self._import_accessories(data, templates, qty_categories, counters)
        rules = self._import_rules(data, counters)
        self._import_configs(data, values, templates, accessories, rules, counters)
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

    def _delete_stale_configs(self, data, templates):
        """Borra las configuraciones de cada máquina del CSV que no están en el archivo.

        Va antes de crear las nuevas: así una combinación que cambia de ID_Configuracion no choca
        con la restricción de combinación única. Las variantes se quitan al final (las usadas en
        ventas se archivan) y una oportunidad que pedía esa configuración la pierde.

        @param data Estructura de _parse().
        @param templates Salida de _import_models().
        """
        Config = self.env['sembradora.config.rel']
        for modelo, tmpl in templates.items():
            kept = Config.union(*(self._find(Config._name, self._xmlid_name('cfg', modelo, conf_id))
                                  for m, conf_id in data['configs'] if m == modelo))
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
                        ', '.join(a.name for a in self.csv_file_ids), detail))

    def _import_attributes(self, data, counters):
        """Crea atributos (variantes "Siempre") y valores; guarda la cantidad de los de cantidad.

        @param data Estructura de _parse().
        @param counters dict de contadores del resumen.
        @return dict {(columna, valor): product.attribute.value}.
        """
        values = {}
        for sequence, (col, attr_data) in enumerate(data['attributes'].items(), start=1):
            if not attr_data['values']:
                continue
            attribute = self._find_or_create('product.attribute', self._xmlid_name('attr', attr_data['name']), {
                'name': attr_data['name'], 'create_variant': 'always',
            }, counters, 'attributes_created')
            if attribute.create_variant != 'always':
                raise UserError(f"El atributo '{attribute.name}' crea variantes en modo '{attribute.create_variant}'; "
                                f"el cotizador necesita el modo 'Siempre' (una variante por configuración).")
            attribute.sequence = sequence * 10
            for value_name, qty in attr_data['values'].items():
                value = self._find_or_create(
                    'product.attribute.value', self._xmlid_name('val', attr_data['name'], value_name),
                    {'name': value_name, 'attribute_id': attribute.id}, counters, 'values_created',
                )
                if col in data['qty_columns'] and value.cotizador_qty != qty:
                    value.cotizador_qty = qty
                values[col, value_name] = value
        return values

    def _import_qty_categories(self, data, values, counters):
        """Una subcategoría de *Accesorio* por atributo de cantidad, vinculada a él.

        @param data Estructura de _parse().
        @param values Salida de _import_attributes().
        @param counters dict de contadores del resumen.
        @return dict {columna: product.category}.
        """
        cat_base = self.env.ref('cotizador.cat_accesorio_base')
        categories = {}
        for col in data['qty_columns']:
            attribute = next(v.attribute_id for (c, _name), v in values.items() if c == col)
            categ = self._find_or_create('product.category', self._xmlid_name('qty', attribute.name), {
                'name': attribute.name, 'parent_id': cat_base.id,
            }, counters, 'categories_created')
            if categ.cotizador_qty_attribute_id != attribute:
                categ.cotizador_qty_attribute_id = attribute
            categories[col] = categ
        return categories

    def _import_models(self, data, values, counters):
        """Máquinas (categoría *Máquina*) con la moneda elegida y sus líneas de atributo.

        Las líneas de atributo quedan con exactamente los valores del CSV y en el orden de las
        columnas; las de atributos "Siempre" que la máquina ya no usa se quitan.

        @param data Estructura de _parse().
        @param values Salida de _import_attributes().
        @param counters dict de contadores del resumen.
        @return dict {modelo: product.template}.
        """
        cat_maquina = self.env.ref('cotizador.cat_maquina')
        attr_sequence = {col: i * 10 for i, col in enumerate(data['attributes'], start=1)}
        templates = {}
        for modelo, model_values in data['models'].items():
            tmpl = self._find_or_create('product.template', self._xmlid_name('modelo', modelo), {
                'name': modelo, 'categ_id': cat_maquina.id, 'type': 'consu',
                'cotizador_currency_id': self.currency_id.id,
            }, counters, 'models_created')
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

    def _import_accessories(self, data, templates, qty_categories, counters):
        """Accesorios: uno por (modelo, nombre), con su categoría, modelo y moneda.

        El mismo nombre en dos modelos son dos productos. Si ya existen se actualizan solo
        categoría, modelo y moneda (el nombre puede haberse cambiado en Odoo), y se reactivan si
        estaban archivados porque habían salido del CSV.

        @param data Estructura de _parse().
        @param templates Salida de _import_models().
        @param qty_categories Salida de _import_qty_categories().
        @param counters dict de contadores del resumen.
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
            }, counters, 'accessories_created')
            if not product.active:
                product.product_tmpl_id.active = True
                product.active = True
            product.product_tmpl_id.write({
                field: value for field, value in vals.items() if product.product_tmpl_id[field].id != value
            })
            accessories[modelo, nombre] = product
        return accessories

    def _import_rules(self, data, counters):
        """Reglas: una por (nombre, tipo).

        @param data Estructura de _parse().
        @param counters dict de contadores del resumen.
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
                Rule._name, xmlid_name, {'name': name, 'rule_type': rtype}, counters, 'rules_created',
            )
        return rules

    def _import_configs(self, data, values, templates, accessories, rules, counters):
        """Crea o actualiza configuraciones y reemplaza sus líneas de accesorio.

        Datos y líneas se escriben en una sola operación, así las restricciones (reglas,
        accesorios del mismo modelo) se validan sobre el estado final: re-importar sobre líneas
        con accesorios de otro criterio (p. ej. compartidos entre modelos) las reemplaza sin
        fallar. El `ext_id` se fija solo al crear.

        @param data Estructura de _parse().
        @param values Salida de _import_attributes().
        @param templates Salida de _import_models().
        @param accessories Salida de _import_accessories().
        @param rules Salida de _import_rules().
        @param counters dict de contadores del resumen.
        """
        Config = self.env['sembradora.config.rel']
        for (modelo, conf_id), config_data in data['configs'].items():
            xmlid_name = self._xmlid_name('cfg', modelo, conf_id)
            vals = {
                'modelo_id': templates[modelo].id,
                'value_ids': [Command.set([values[col, v].id for col, v in config_data['values'].items()])],
                'price': config_data['price'],
            }
            if config_data['description']:
                vals['description'] = config_data['description']
            # Datos de la configuración y líneas en una sola operación: las restricciones (reglas,
            # accesorios del mismo modelo) se validan sobre el estado final, no con las líneas
            # viejas todavía puestas.
            vals['accessory_line_ids'] = [Command.create({
                'product_id': accessories[modelo, line['name']].id,
                'price': line['price'],
                'is_standard': line['is_standard'],
                'is_trigger': line['is_trigger'],
                'rule_ids': [Command.set([rules[r].id for r in line['rules']])],
            }) for line in config_data['lines']]
            config = self._find(Config._name, xmlid_name)
            if config:
                vals['accessory_line_ids'] = [Command.delete(line.id) for line in config.accessory_line_ids] + vals['accessory_line_ids']
                config.write(vals)
                counters['configs_updated'] += 1
            else:
                self._find_or_create(Config._name, xmlid_name, {**vals, 'ext_id': conf_id}, counters, 'configs_created')
            counters['lines'] += len(config_data['lines'])
            counters['standard_lines'] += sum(1 for line in config_data['lines'] if line['is_standard'])
