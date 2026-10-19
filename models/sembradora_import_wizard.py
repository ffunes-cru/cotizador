import csv
import io
import json
import logging
import re
import unicodedata

from markupsafe import Markup

from odoo import Command, fields, models
from odoo.exceptions import UserError

from .sembradora_config import validate_rule_set

_logger = logging.getLogger(__name__)

# Módulo de los xmlids que el importador asigna a lo que crea: es su única forma de
# reencontrar registros (nunca busca por nombre), así renombrar en Odoo no rompe la re-importación.
IMPORT_MODULE = 'cotizador_import'

# Columnas con significado fijo. Las de atributos llevan el prefijo ATTRIBUTE_PREFIX.
FIXED_COLUMNS = {
    'ID_Configuracion', 'Modelo', 'Tipo_Item', 'Precio_Base', 'Nombre_Item', 'Precio_Item',
    'Calc_param', 'Reglas', 'Descripcion',
}
ATTRIBUTE_PREFIX = 'ATR_'

TYPE_BASE = 'BASE'
TYPE_OPTIONAL = 'OPCIONAL'
TYPE_STANDARD = 'ESTANDAR'  # accesorio preseleccionado (equipamiento estándar)
ITEM_TYPES = {TYPE_BASE, TYPE_OPTIONAL, TYPE_STANDARD}

# Sufijo de regla → (tipo, es trigger)
RULE_SUFFIXES = {
    'e': ('exclusion', False),
    'et': ('exclusion', True),
    'i': ('inclusion', False),
    'it': ('inclusion', True),
    'u': ('choice', False),
}


def _strip_accents(text):
    return ''.join(c for c in unicodedata.normalize('NFD', text) if unicodedata.category(c) != 'Mn')


def slugify(text):
    """'Cantidad de Líneas' → 'cantidad_de_lineas' (parte de un xmlid)."""
    return re.sub(r'[^a-z0-9]+', '_', _strip_accents(text).lower()).strip('_')


def first_number(text):
    """'16 Líneas' → 16.0, '52,5 cm' → 52.5; None si no hay número."""
    match = re.search(r'\d+(?:[.,]\d+)?', text or '')
    return float(match.group().replace(',', '.')) if match else None


def parse_price(price_str):
    """
    Convierte un precio del CSV a float; None si está vacío o no es un número.
      'USD $248.866,00' → 248866.0 (punto miles, coma decimal)   '248866,5' → 248866.5
      '248.866' → 248866.0 (punto miles)   '248866.00' → 248866.0   '248,866.00' → 248866.0
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
    _name = 'sembradora.import.wizard'
    _description = 'Importador CSV de Configuraciones de Sembradora'

    csv_file_ids = fields.Many2many('ir.attachment', string='Archivos CSV')
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
        """[(nombre_archivo, encabezado, [(n_linea, fila), ...]), ...]"""
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
        """
        Valida el CSV completo y lo convierte a una estructura independiente de Odoo.
        :return: (data, errors) — si hay errores, no se debe importar.
        """
        errors = []
        data = {
            'attributes': {},      # columna → {'name', 'values': {valor: cantidad|None}}
            'qty_columns': set(),  # columnas de atributo usadas como Calc_param
            'models': {},          # modelo → {columna: set(valores)}
            'accessories': {},     # nombre → columna Calc_param ('' si no tiene)
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
                calc_param = cell.get('Calc_param', '')
                if calc_param and calc_param not in attr_columns:
                    errors.append(f"{where}: Calc_param '{calc_param}' debe ser el nombre exacto de una "
                                  f"columna de atributo del archivo ({', '.join(attr_columns) or 'no hay'}).")
                    continue
                if calc_param:
                    data['qty_columns'].add(calc_param)
                previous = data['accessories'].setdefault(nombre, calc_param)
                accessory_origin.setdefault(nombre, where)
                if previous != calc_param:
                    errors.append(f"{where}: '{nombre}' tiene Calc_param '{calc_param}', pero en "
                                  f"{accessory_origin[nombre]} tiene '{previous}'.")

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

    def _validate_parsed(self, data):
        """Validaciones que necesitan el CSV completo."""
        errors = []
        # Atributos de cantidad: cada valor debe contener un número
        for col in sorted(data['qty_columns']):
            values = data['attributes'][col]['values']
            for value in values:
                values[value] = first_number(value)
                if values[value] is None:
                    errors.append(f"Atributo de cantidad {col}: el valor '{value}' no contiene un número.")

        combinations = {}
        for (modelo, conf_id), config in data['configs'].items():
            label = f"Configuración {modelo}/{conf_id}"
            if not config['base']:
                errors.append(f"{label}: no tiene fila BASE.")
                continue
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

        # Dos textos distintos no pueden producir el mismo xmlid
        def check_slugs(kind, names):
            seen = {}
            for name in names:
                other = seen.setdefault(slugify(name), name)
                if other != name:
                    errors.append(f"{kind} '{name}' y '{other}' son indistinguibles para el importador "
                                  f"(solo difieren en acentos, mayúsculas o símbolos).")
        check_slugs('Modelo', data['models'])
        check_slugs('Accesorio', data['accessories'])
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
        return '_'.join([kind, *(slugify(p) for p in parts)])

    def _find(self, model, xmlid_name):
        record = self.env.ref(f'{IMPORT_MODULE}.{xmlid_name}', raise_if_not_found=False)
        return record if record and record._name == model else self.env[model]

    def _find_or_create(self, model, xmlid_name, create_vals, counters, counter_key):
        record = self._find(model, xmlid_name)
        if not record:
            record = self.env[model].create(create_vals)
            self.env['ir.model.data'].create({
                'module': IMPORT_MODULE, 'name': xmlid_name, 'model': model,
                'res_id': record.id, 'noupdate': True,
            })
            counters[counter_key] += 1
        return record

    # =========================================================================
    #  PASO 1: ANÁLISIS
    # =========================================================================

    def action_analyze(self):
        """Valida el CSV y resume lo que se creará o actualizará; no escribe nada."""
        self.ensure_one()
        files = self._read_files()
        data, errors = self._parse(files)
        self.write({
            'state': 'analyzed',
            'has_errors': bool(errors),
            'analysis_summary': self._build_analysis_html(data, errors),
            'parsed_data': json.dumps(files),
        })
        return self._reopen()

    def action_back_to_upload(self):
        self.write({'state': 'draft', 'has_errors': False, 'analysis_summary': False, 'parsed_data': False})
        return self._reopen()

    def _reopen(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _build_analysis_html(self, data, errors):
        html = Markup('<div style="font-size: 13px;">')
        if errors:
            html += Markup('<h3 style="color: #c62828;">❌ %s errores: corríjalos y vuelva a analizar</h3><ul>') % len(errors)
            for error in errors[:200]:
                html += Markup('<li style="color: #c62828;">%s</li>') % error
            if len(errors) > 200:
                html += Markup('<li><i>… y %s más.</i></li>') % (len(errors) - 200)
            html += Markup('</ul>')

        def existing(kind, model, keys, xmlid_parts):
            found = sum(1 for k in keys if self._find(model, self._xmlid_name(kind, *xmlid_parts(k))))
            return found, len(keys) - found

        configs = [c for c in data['configs'].values() if c['base']]
        rows = [
            ('📋 Configuraciones', *existing('cfg', 'sembradora.config.rel', configs,
                                             lambda c: (c['modelo'], c['conf_id']))),
            ('🚜 Modelos', *existing('modelo', 'product.template', list(data['models']), lambda m: (m,))),
            ('🏷️ Atributos', *existing('attr', 'product.attribute',
                                        [a['name'] for a in data['attributes'].values()], lambda n: (n,))),
            ('🔧 Accesorios', *existing('acc', 'product.product', list(data['accessories']), lambda n: (n,))),
            ('📏 Reglas', *existing('rule', 'sembradora.accessory.rule', list(data['rules']),
                                     lambda r: (r[1], r[0]))),
        ]
        html += Markup('<table class="table table-sm w-auto"><tr><th></th><th>Existentes</th><th>Nuevos</th></tr>')
        for label, found, new in rows:
            html += Markup('<tr><td>%s</td><td>%s</td><td>%s</td></tr>') % (label, found, new)
        html += Markup('</table>')

        lines = [line for c in configs for line in c['lines']]
        choice_groups = {name for name, rtype in data['rules'] if rtype == 'choice'}
        html += Markup('<p>⭐ Líneas de accesorio: <b>%s</b> (estándar: <b>%s</b>) · '
                       'Grupos de opción única: <b>%s</b></p>') % (
            len(lines), sum(1 for line in lines if line['is_standard']), len(choice_groups))
        if data['qty_columns']:
            html += Markup('<p>📐 Atributos de cantidad (Calc_param): %s</p>') % ', '.join(
                data['attributes'][col]['name'] for col in sorted(data['qty_columns']))
        return html + Markup('</div>')

    # =========================================================================
    #  PASO 2: IMPORTACIÓN
    # =========================================================================

    def action_import(self):
        """Crea/actualiza todo lo analizado. Re-valida: si hay errores no escribe nada."""
        self.ensure_one()
        if self.state != 'analyzed' or not self.parsed_data:
            raise UserError("Primero debe analizar el CSV.")
        # El wizard solo es accesible al grupo Administrador del Configurador (ACL); los datos
        # maestros que necesita (productos, atributos, categorías) se crean con sudo.
        self = self.sudo()
        data, errors = self._parse(json.loads(self.parsed_data))
        if errors:
            raise UserError("El CSV tiene errores; vuelva a analizarlo:\n" + "\n".join(errors[:50]))

        counters = dict.fromkeys([
            'configs_created', 'configs_updated', 'lines', 'standard_lines', 'models_created',
            'accessories_created', 'attributes_created', 'values_created', 'categories_created',
            'rules_created',
        ], 0)
        values = self._import_attributes(data, counters)
        qty_categories = self._import_qty_categories(data, values, counters)
        templates = self._import_models(data, values, counters)
        accessories = self._import_accessories(data, qty_categories, counters)
        rules = self._import_rules(data, counters)
        self._import_configs(data, values, templates, accessories, rules, counters)

        self.write({
            'state': 'done',
            'analysis_summary': Markup(
                "<h3>✅ Importación completada</h3><ul>"
                "<li>Configuraciones creadas / actualizadas: <b>%(configs_created)s</b> / <b>%(configs_updated)s</b></li>"
                "<li>Líneas de accesorio: <b>%(lines)s</b> (estándar: <b>%(standard_lines)s</b>)</li>"
                "<li>Modelos creados: <b>%(models_created)s</b> · Accesorios creados: <b>%(accessories_created)s</b></li>"
                "<li>Atributos / valores creados: <b>%(attributes_created)s</b> / <b>%(values_created)s</b></li>"
                "<li>Categorías de cantidad creadas: <b>%(categories_created)s</b> · Reglas creadas: <b>%(rules_created)s</b></li>"
                "</ul>"
            ) % counters,
        })
        return self._reopen()

    def _import_attributes(self, data, counters):
        """:return: {(columna, valor): product.attribute.value}"""
        values = {}
        for sequence, (col, attr_data) in enumerate(data['attributes'].items(), start=1):
            if not attr_data['values']:
                continue
            attribute = self._find_or_create('product.attribute', self._xmlid_name('attr', attr_data['name']), {
                'name': attr_data['name'], 'create_variant': 'dynamic',
            }, counters, 'attributes_created')
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
        """Una subcategoría de Accesorio por atributo de cantidad, vinculada a él. :return: {columna: categoría}"""
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
        """Máquinas (categoría Máquina) con sus líneas de atributo. :return: {modelo: product.template}"""
        cat_maquina = self.env.ref('cotizador.cat_maquina')
        attr_sequence = {col: i * 10 for i, col in enumerate(data['attributes'], start=1)}
        templates = {}
        for modelo, model_values in data['models'].items():
            tmpl = self._find_or_create('product.template', self._xmlid_name('modelo', modelo), {
                'name': modelo, 'categ_id': cat_maquina.id, 'type': 'consu',
            }, counters, 'models_created')
            for col, value_names in model_values.items():
                value_records = self.env['product.attribute.value'].union(*(values[col, v] for v in value_names))
                ptal = tmpl.attribute_line_ids.filtered(lambda l: l.attribute_id == value_records.attribute_id)
                if ptal:
                    ptal.write({'sequence': attr_sequence[col], 'value_ids': [Command.link(v.id) for v in value_records]})
                else:
                    self.env['product.template.attribute.line'].create({
                        'product_tmpl_id': tmpl.id, 'attribute_id': value_records.attribute_id.id,
                        'sequence': attr_sequence[col], 'value_ids': [Command.set(value_records.ids)],
                    })
            templates[modelo] = tmpl
        return templates

    def _import_accessories(self, data, qty_categories, counters):
        """:return: {nombre: product.product}"""
        cat_base = self.env.ref('cotizador.cat_accesorio_base')
        accessories = {}
        for nombre, calc_param in data['accessories'].items():
            categ = qty_categories[calc_param] if calc_param else cat_base
            product = self._find_or_create('product.product', self._xmlid_name('acc', nombre), {
                'name': nombre, 'categ_id': categ.id, 'type': 'consu',
            }, counters, 'accessories_created')
            if product.categ_id != categ:
                product.categ_id = categ
            accessories[nombre] = product
        return accessories

    def _import_rules(self, data, counters):
        """:return: {(nombre, tipo): sembradora.accessory.rule}"""
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
        """Crea/actualiza configuraciones y reemplaza sus líneas de accesorio en un solo write."""
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
            config = self._find(Config._name, xmlid_name)
            if config:
                config.write(vals)
                counters['configs_updated'] += 1
            else:
                config = self._find_or_create(Config._name, xmlid_name, {**vals, 'ext_id': conf_id},
                                              counters, 'configs_created')
            # Un solo write: las restricciones de reglas se validan sobre el estado final
            config.write({'accessory_line_ids': [Command.delete(line.id) for line in config.accessory_line_ids] + [
                Command.create({
                    'product_id': accessories[line['name']].id,
                    'price': line['price'],
                    'is_standard': line['is_standard'],
                    'is_trigger': line['is_trigger'],
                    'rule_ids': [Command.set([rules[r].id for r in line['rules']])],
                }) for line in config_data['lines']
            ]})
            counters['lines'] += len(config_data['lines'])
            counters['standard_lines'] += sum(1 for line in config_data['lines'] if line['is_standard'])
