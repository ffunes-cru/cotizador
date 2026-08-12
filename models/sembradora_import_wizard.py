import base64
import csv
import io
import json
import logging
import os
from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Mapeo de Calc_param del CSV → XML ID de categoría hija de Accesorio.
# Las claves deben coincidir exactamente con los valores de la columna Calc_param.
CALC_PARAM_CATEGORY_MAP = {
    'Cantidad de Líneas': 'cotizador.cat_accesorio_cantidad_lineas',
    'Distancia Entre Líneas': 'cotizador.cat_accesorio_distancia_lineas',
}
# Categoría fallback para accesorios sin Calc_param (precio fijo de la matriz)
CATEGORY_FALLBACK_XMLID = 'cotizador.cat_accesorio_por_maquina'
# Categoría base de accesorios (padre de todas las subcategorías)
CATEGORY_BASE_XMLID = 'cotizador.cat_accesorio_base'


class SembradoraImportWizard(models.TransientModel):
    _name = 'sembradora.import.wizard'
    _description = 'Importador CSV de Configuraciones de Sembradora'

    # --- Paso 1: Carga ---
    csv_file_ids = fields.Many2many('ir.attachment', string='Archivos CSV')

    # --- Resultado del análisis ---
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('analyzed', 'Analizado'),
        ('done', 'Importado'),
    ], default='draft', string='Estado')

    analysis_summary = fields.Html(string='Resumen del Análisis', readonly=True)

    # Checkboxes para creación automática
    create_missing_products = fields.Boolean(
        string='Crear productos faltantes',
        default=True,
        help='Crea automáticamente los product.template (Máquina) y product.product (Accesorio) '
             'que no existan en el sistema.')
    create_missing_attributes = fields.Boolean(
        string='Crear atributos/valores faltantes',
        default=True,
        help='Crea automáticamente los product.attribute y product.attribute.value que no existan.')
    create_missing_categories = fields.Boolean(
        string='Crear categorías faltantes',
        default=True,
        help='Crea subcategorías hijas de Accesorio para nuevos valores de Calc_param.')

    # Campo interno: datos parseados almacenados como texto para no re-parsear
    _parsed_data = fields.Text(string='Datos Parseados', readonly=True)

    # =========================================================================
    #  UTILIDADES
    # =========================================================================

    def _parse_price(self, price_str):
        """Convierte 'USD $248.866,00' → 248866.00"""
        if not price_str:
            return 0.0
        clean = price_str.replace('USD', '').replace('$', '').replace('"', '').strip()
        # Formato argentino: punto = miles, coma = decimal
        clean = clean.replace('.', '').replace(',', '.')
        try:
            return float(clean)
        except ValueError:
            _logger.warning("No se pudo parsear el precio: '%s'", price_str)
            return 0.0

    def _make_ext_id(self, conf_id_raw, modelo_name):
        """
        Genera un ext_id único prefijado por el nombre del modelo si no lo incluye ya.
        Evita colisiones entre configuraciones de distintos modelos que usen el mismo ID.
        Ejemplos:
          conf_id_raw='CONF-001', modelo_name='Pionera' -> 'C-PIONERA-CONF-001'
          conf_id_raw='001', modelo_name='Pionera' -> 'C-PIONERA-001'
          conf_id_raw='C-PIONERA-001', modelo_name='Pionera' -> 'C-PIONERA-001'
        """
        if not conf_id_raw:
            return ''
        conf_id = conf_id_raw.strip()
        if not modelo_name:
            return conf_id

        mod_clean = modelo_name.strip().upper().replace(' ', '-')
        conf_upper = conf_id.upper()

        if conf_upper.startswith(f"C-{mod_clean}") or mod_clean in conf_upper:
            return conf_id
        if conf_upper.startswith("C-"):
            return f"C-{mod_clean}-{conf_id[2:]}"
        return f"C-{mod_clean}-{conf_id}"

    def _parse_rules_str(self, rules_str):
        """
        Parsea la cadena de reglas del CSV.

        Formato soportado:
          - "Kit Grano grueso"           → exclusion, not trigger
          - "Kit Grano grueso:e"         → exclusion, not trigger (explícito)
          - "Requiere Monitor:i"         → inclusion, not trigger
          - "Requiere Monitor:it"        → inclusion, IS trigger
          - "Kit GG:e|Requiere Monitor:it" → dos reglas

        Retorna: list of dicts:
            [{'name': str, 'rule_type': 'exclusion'|'inclusion', 'is_trigger': bool}]
        """
        if not rules_str or not rules_str.strip():
            return []

        result = []
        parts = rules_str.strip().split('|')
        for part in parts:
            part = part.strip()
            if not part:
                continue

            is_trigger = False
            rule_type = 'exclusion'  # default

            if part.endswith(':it'):
                rule_type = 'inclusion'
                is_trigger = True
                name = part[:-3].strip()
            elif part.endswith(':i'):
                rule_type = 'inclusion'
                is_trigger = False
                name = part[:-2].strip()
            elif part.endswith(':et'):
                rule_type = 'exclusion'
                is_trigger = True
                name = part[:-3].strip()
            elif part.endswith(':e'):
                rule_type = 'exclusion'
                is_trigger = False
                name = part[:-2].strip()
            else:
                name = part

            if name:
                result.append({
                    'name': name,
                    'rule_type': rule_type,
                    'is_trigger': is_trigger,
                })
        return result

    def _read_csv(self):
        """Lee los CSVs subidos en csv_file_ids o recupera los datos parseados de _parsed_data."""
        if self._parsed_data:
            try:
                return json.loads(self._parsed_data)
            except Exception as e:
                _logger.warning("No se pudo parsear _parsed_data: %s", e)

        if not self.csv_file_ids:
            raise UserError("Por favor, seleccione al menos un archivo CSV.")

        all_rows = []
        for att in self.csv_file_ids:
            raw = att.raw
            if not raw:
                continue
            try:
                text = raw.decode('utf-8-sig')
            except UnicodeDecodeError:
                text = raw.decode('latin-1')
            reader = csv.DictReader(io.StringIO(text))
            file_rows = list(reader)
            all_rows.extend(file_rows)

        if not all_rows:
            raise UserError("Los archivos CSV seleccionados están vacíos o no tienen el formato esperado.")
        return all_rows

    def _get_attribute_columns(self, rows):
        """
        Detecta dinámicamente las columnas de atributos de variante.
        Son las columnas que NO están en el set de columnas fijas del CSV.
        """
        fixed_columns = {
            'ID_Configuracion', 'Modelo', 'Precio_Base', 'Tipo_Item',
            'Nombre_Item', 'Precio_Item', 'Calc_param', 'Grupo de exclusion',
            'Reglas',  # Nueva columna para el formato con reglas
        }
        if not rows:
            return []
        all_columns = list(rows[0].keys())
        return [col for col in all_columns if col not in fixed_columns]

    # =========================================================================
    #  PASO 1: ANÁLISIS
    # =========================================================================

    def action_analyze(self):
        """Parsea el CSV y genera un resumen de lo que se importará/creará."""
        self.ensure_one()
        rows = self._read_csv()
        attribute_columns = self._get_attribute_columns(rows)

        # --- Recolectar datos únicos ---
        modelos = set()
        configs = {}  # {conf_id: {modelo, attrs:{col: val}, precio, nombre_base}}
        accesorios = {}  # {nombre_item: {calc_param, precios}}
        attr_values = {}  # {nombre_atributo: set(valores)}
        rules_detected = {}  # {(name, type): {'is_trigger_seen': bool}}
        calc_params = set()

        for row in rows:
            conf_id_raw = row.get('ID_Configuracion', '').strip()
            modelo = row.get('Modelo', '').strip()
            tipo = row.get('Tipo_Item', '').strip().upper()
            conf_id = self._make_ext_id(conf_id_raw, modelo)

            if modelo:
                modelos.add(modelo)

            # Recoger valores de atributos de las columnas dinámicas
            for col in attribute_columns:
                val = row.get(col, '').strip()
                if val:
                    attr_name = col.replace('_', ' ')
                    attr_values.setdefault(attr_name, set()).add(val)

            if tipo == 'BASE':
                if conf_id not in configs:
                    attrs = {}
                    for col in attribute_columns:
                        val = row.get(col, '').strip()
                        if val:
                            attrs[col.replace('_', ' ')] = val
                    configs[conf_id] = {
                        'modelo': modelo,
                        'attrs': attrs,
                        'precio': self._parse_price(row.get('Precio_Base', '')),
                        'nombre_base': row.get('Nombre_Item', '').strip(),
                    }
            elif tipo == 'OPCIONAL':
                nombre_item = row.get('Nombre_Item', '').strip()
                calc_param = row.get('Calc_param', '').strip()
                # Soportar ambas columnas: nueva "Reglas" y legacy "Grupo de exclusion"
                rules_str = row.get('Reglas', '').strip() or row.get('Grupo de exclusion', '').strip()

                if nombre_item:
                    if nombre_item not in accesorios:
                        accesorios[nombre_item] = {
                            'calc_param': calc_param,
                        }
                if calc_param:
                    calc_params.add(calc_param)
                # Parsear reglas
                parsed_rules = self._parse_rules_str(rules_str)
                for pr in parsed_rules:
                    key = (pr['name'], pr['rule_type'])
                    if key not in rules_detected:
                        rules_detected[key] = {'is_trigger_seen': False}
                    if pr['is_trigger']:
                        rules_detected[key]['is_trigger_seen'] = True

        # --- Verificar existencia en Odoo ---
        # --- Verificar existencia en Odoo (optimizado en lote) ---
        ProductTemplate = self.env['product.template']
        ProductProduct = self.env['product.product']
        ProductAttribute = self.env['product.attribute']
        ProductAttributeValue = self.env['product.attribute.value']

        # Modelos (product.template con categ "Maquina")
        found_templates = ProductTemplate.search([
            ('name', 'in', list(modelos)),
            ('categ_id.name', '=', 'Maquina')
        ]) if modelos else ProductTemplate
        modelos_existentes = set(found_templates.mapped('name'))
        modelos_faltantes = modelos - modelos_existentes

        # Atributos y valores (en lote)
        all_attr_names = list(attr_values.keys())
        found_attrs = ProductAttribute.search([('name', 'in', all_attr_names)]) if all_attr_names else ProductAttribute
        attr_by_name = {a.name: a for a in found_attrs}

        all_val_strings = set()
        for vals in attr_values.values():
            all_val_strings.update(vals)
        found_vals = ProductAttributeValue.search([
            ('name', 'in', list(all_val_strings)),
            ('attribute_id', 'in', [a.id for a in found_attrs])
        ]) if (found_attrs and all_val_strings) else ProductAttributeValue
        val_exist_set = set((v.name, v.attribute_id.id) for v in found_vals)

        attrs_existentes = {}
        attrs_faltantes = {}
        valores_existentes = {}
        valores_faltantes = {}

        for attr_name, values in attr_values.items():
            if attr_name in attr_by_name:
                attr = attr_by_name[attr_name]
                attrs_existentes[attr_name] = attr
                for v in values:
                    if (v, attr.id) in val_exist_set:
                        valores_existentes.setdefault(attr_name, set()).add(v)
                    else:
                        valores_faltantes.setdefault(attr_name, set()).add(v)
            else:
                attrs_faltantes[attr_name] = values

        # Accesorios (product.product en lote)
        cat_base = self.env.ref(CATEGORY_BASE_XMLID, raise_if_not_found=False)
        child_cat_ids = []
        if cat_base:
            child_cats = self.env['product.category'].search([('id', 'child_of', cat_base.id)])
            child_cat_ids = child_cats.ids

        acc_domain = [('name', 'in', list(accesorios.keys()))]
        if child_cat_ids:
            acc_domain.append(('categ_id', 'in', child_cat_ids))

        found_prods = ProductProduct.search(acc_domain) if accesorios else ProductProduct
        accs_existentes = set(found_prods.mapped('name'))
        accs_faltantes = set(accesorios.keys()) - accs_existentes

        # Categorías de Calc_param (en lote)
        cats_faltantes_param = set()
        if cat_base and calc_params:
            existing_cats = self.env['product.category'].search([
                ('parent_id', '=', cat_base.id)
            ])
            existing_cat_names = set(existing_cats.mapped('name'))
            for cp in calc_params:
                xmlid = CALC_PARAM_CATEGORY_MAP.get(cp)
                if xmlid:
                    cat = self.env.ref(xmlid, raise_if_not_found=False)
                    if not cat:
                        cats_faltantes_param.add(cp)
                elif cp not in existing_cat_names:
                    cats_faltantes_param.add(cp)

        # Configs existentes (por ext_id en lote)
        ConfigRel = self.env['sembradora.config.rel']
        found_configs = ConfigRel.search([('ext_id', 'in', list(configs.keys()))]) if configs else ConfigRel
        configs_existentes = set(found_configs.mapped('ext_id'))
        configs_nuevas = set(configs.keys()) - configs_existentes

        # --- Generar HTML del resumen ---
        html = self._build_analysis_html(
            modelos, modelos_existentes, modelos_faltantes,
            attr_values, attrs_existentes, attrs_faltantes,
            valores_existentes, valores_faltantes,
            accesorios, accs_existentes, accs_faltantes,
            configs, configs_existentes, configs_nuevas,
            rules_detected, calc_params, cats_faltantes_param,
        )

        self.write({
            'state': 'analyzed',
            'analysis_summary': html,
            '_parsed_data': json.dumps(rows),
        })

        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _build_analysis_html(self, modelos, modelos_exist, modelos_falt,
                              attr_values, attrs_exist, attrs_falt,
                              valores_exist, valores_falt,
                              accesorios, accs_exist, accs_falt,
                              configs, configs_exist, configs_new,
                              rules_detected, calc_params, cats_falt):
        """Genera HTML del resumen del análisis."""
        lines = ['<div style="font-family: sans-serif; font-size: 13px;">']

        # Configuraciones
        lines.append(f'<h3>📋 Configuraciones: {len(configs)}</h3>')
        lines.append('<ul>')
        sorted_cids = sorted(configs.keys())
        max_configs = 25
        for cid in sorted_cids[:max_configs]:
            status = '✅ existente' if cid in configs_exist else '🆕 nueva'
            c = configs[cid]
            attrs_str = ', '.join(f'{k}: {v}' for k, v in c['attrs'].items())
            lines.append(f'<li><b>{cid}</b> — {c["modelo"]} ({attrs_str}) — ${c["precio"]:,.2f} — {status}</li>')
        if len(sorted_cids) > max_configs:
            lines.append(f'<li><i>... y {len(sorted_cids) - max_configs} configuraciones más.</i></li>')
        lines.append('</ul>')

        # Modelos
        lines.append(f'<h3>🚜 Modelos de Máquina: {len(modelos)}</h3>')
        if modelos_falt:
            lines.append(f'<p style="color: #e65100;">⚠️ Faltantes (se crearán): {", ".join(sorted(modelos_falt))}</p>')
        if modelos_exist:
            lines.append(f'<p style="color: #2e7d32;">✅ Existentes: {", ".join(sorted(modelos_exist))}</p>')

        # Atributos
        lines.append(f'<h3>🏷️ Atributos de Variante</h3>')
        for attr_name, values in attr_values.items():
            if attr_name in attrs_exist:
                lines.append(f'<p>✅ <b>{attr_name}</b>: existente</p>')
                falt = valores_falt.get(attr_name, set())
                exist = valores_exist.get(attr_name, set())
                if exist:
                    lines.append(f'<ul><li>Valores existentes: {", ".join(sorted(exist))}</li></ul>')
                if falt:
                    lines.append(f'<ul><li style="color: #e65100;">Valores a crear: {", ".join(sorted(falt))}</li></ul>')
            elif attr_name in attrs_falt:
                lines.append(f'<p style="color: #e65100;">🆕 <b>{attr_name}</b>: a crear con valores: {", ".join(sorted(values))}</p>')

        # Accesorios
        lines.append(f'<h3>🔧 Accesorios: {len(accesorios)}</h3>')
        if accs_falt:
            lines.append('<p style="color: #e65100;">⚠️ A crear:</p><ul>')
            sorted_accs = sorted(accs_falt)
            max_accs = 25
            for a in sorted_accs[:max_accs]:
                cp = accesorios[a]['calc_param']
                cp_str = f' (Calc: {cp})' if cp else ''
                lines.append(f'<li>{a}{cp_str}</li>')
            if len(sorted_accs) > max_accs:
                lines.append(f'<li><i>... y {len(sorted_accs) - max_accs} accesorios más.</i></li>')
            lines.append('</ul>')
        if accs_exist:
            lines.append(f'<p style="color: #2e7d32;">✅ Existentes: {len(accs_exist)} accesorios</p>')

        # Categorías de Calc_param
        if cats_falt:
            lines.append(f'<h3>📂 Categorías a crear (nuevos Calc_param)</h3>')
            lines.append('<ul>')
            for cp in sorted(cats_falt):
                lines.append(f'<li style="color: #e65100;">🆕 {cp} (subcategoría de Accesorio)</li>')
            lines.append('</ul>')

        # Reglas de exclusión/inclusión
        if rules_detected:
            lines.append(f'<h3>📏 Reglas de Exclusión/Inclusión: {len(rules_detected)}</h3>')
            lines.append('<ul>')
            sorted_rules = sorted(rules_detected.items())
            max_rules = 25
            found_rules = self.env['sembradora.accessory.rule'].search([])
            existing_rule_keys = set((r.name, r.rule_type) for r in found_rules)
            for (name, rtype), info in sorted_rules[:max_rules]:
                tipo_label = '🚫 Exclusión' if rtype == 'exclusion' else '🔗 Inclusión'
                trigger_str = ' (con trigger)' if info['is_trigger_seen'] else ''
                status = '✅' if (name, rtype) in existing_rule_keys else '🆕'
                lines.append(f'<li>{status} <b>{name}</b> — {tipo_label}{trigger_str}</li>')
            if len(sorted_rules) > max_rules:
                lines.append(f'<li><i>... y {len(sorted_rules) - max_rules} reglas más.</i></li>')
            lines.append('</ul>')

        lines.append('</div>')
        return '\n'.join(lines)

    # =========================================================================
    #  PASO 2: IMPORTACIÓN
    # =========================================================================

    def action_import(self):
        """Ejecuta la importación creando/actualizando todos los registros."""
        self.ensure_one()
        if self.state != 'analyzed':
            raise UserError("Primero debe analizar el CSV.")

        rows = self._read_csv()
        attribute_columns = self._get_attribute_columns(rows)

        counters = {
            'configs_created': 0,
            'configs_updated': 0,
            'acc_lines_created': 0,
            'acc_lines_updated': 0,
            'products_created': 0,
            'attributes_created': 0,
            'values_created': 0,
            'categories_created': 0,
            'rules_created': 0,
        }

        # 1. Asegurar atributos y valores existen
        attr_map = self._ensure_attributes(rows, attribute_columns, counters)

        # 2. Asegurar que los modelos (product.template) existen
        template_map = self._ensure_templates(rows, attr_map, attribute_columns, counters)

        # 3. Asegurar categorías de Calc_param
        category_map = self._ensure_categories(rows, counters)

        # 4. Asegurar productos de accesorio existen
        acc_product_map = self._ensure_accessory_products(rows, category_map, counters)

        # 5. Asegurar reglas de exclusión/inclusión existen
        rule_map = self._ensure_rules(rows, counters)

        # 6. Crear/actualizar configuraciones y líneas de accesorio
        self._upsert_configs_and_lines(
            rows, attribute_columns, attr_map, template_map,
            acc_product_map, rule_map, counters
        )

        # Resumen final
        summary = (
            f"<div style='font-family: sans-serif;'>"
            f"<h3>✅ Importación completada</h3>"
            f"<ul>"
            f"<li>Configuraciones creadas: <b>{counters['configs_created']}</b></li>"
            f"<li>Configuraciones actualizadas: <b>{counters['configs_updated']}</b></li>"
            f"<li>Líneas de accesorio creadas: <b>{counters['acc_lines_created']}</b></li>"
            f"<li>Líneas de accesorio actualizadas: <b>{counters['acc_lines_updated']}</b></li>"
            f"<li>Productos creados: <b>{counters['products_created']}</b></li>"
            f"<li>Atributos creados: <b>{counters['attributes_created']}</b></li>"
            f"<li>Valores de atributo creados: <b>{counters['values_created']}</b></li>"
            f"<li>Categorías creadas: <b>{counters['categories_created']}</b></li>"
            f"<li>Reglas creadas: <b>{counters['rules_created']}</b></li>"
            f"</ul></div>"
        )

        self.write({
            'state': 'done',
            'analysis_summary': summary,
        })

        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    # =========================================================================
    #  SUB-PASOS DE IMPORTACIÓN
    # =========================================================================

    def _ensure_attributes(self, rows, attribute_columns, counters):
        """
        Asegura que existan los product.attribute y product.attribute.value.
        Retorna: {attr_name: {value_str: product.attribute.value record}}
        """
        ProductAttribute = self.env['product.attribute']
        ProductAttributeValue = self.env['product.attribute.value']

        # Recolectar todos los valores únicos por atributo
        attr_values = {}
        for row in rows:
            for col in attribute_columns:
                val = row.get(col, '').strip()
                if val:
                    attr_name = col.replace('_', ' ')
                    attr_values.setdefault(attr_name, set()).add(val)

        attr_map = {}  # {attr_name: {value_str: record}}

        for idx, col in enumerate(attribute_columns, start=10):
            attr_name = col.replace('_', ' ')
            if attr_name not in attr_values:
                continue
            values = attr_values[attr_name]
            # Buscar o crear el atributo
            attr = ProductAttribute.search([('name', '=', attr_name)], limit=1)
            if not attr:
                if self.create_missing_attributes:
                    attr = ProductAttribute.create({
                        'name': attr_name,
                        'sequence': idx,
                        'create_variant': 'dynamic',
                    })
                    counters['attributes_created'] += 1
                    _logger.info("Atributo creado: %s (secuencia: %d, variantes: dynamic)", attr_name, idx)
                else:
                    raise UserError(
                        f"El atributo '{attr_name}' no existe y la opción de crear faltantes está desactivada."
                    )
            else:
                write_vals = {'sequence': idx}
                # Forzar modo dinámico si está en 'always' para evitar explosión combinatoria
                if attr.create_variant == 'always' and not attr.number_related_products:
                    write_vals['create_variant'] = 'dynamic'
                attr.write(write_vals)

            attr_map[attr_name] = {}
            for val_str in values:
                val = ProductAttributeValue.search([
                    ('name', '=', val_str),
                    ('attribute_id', '=', attr.id)
                ], limit=1)
                if not val:
                    if self.create_missing_attributes:
                        val = ProductAttributeValue.create({
                            'name': val_str,
                            'attribute_id': attr.id,
                        })
                        counters['values_created'] += 1
                        _logger.info("Valor de atributo creado: %s → %s", attr_name, val_str)
                    else:
                        raise UserError(
                            f"El valor '{val_str}' del atributo '{attr_name}' no existe "
                            f"y la opción de crear faltantes está desactivada."
                        )
                attr_map[attr_name][val_str] = val

        return attr_map

    def _ensure_templates(self, rows, attr_map, attribute_columns, counters):
        """
        Asegura que existan los product.template (Máquina) y que tengan
        las attribute lines asignadas.
        Retorna: {modelo_name: product.template record}
        """
        ProductTemplate = self.env['product.template']

        # Buscar o crear categoría "Maquina"
        cat_maquina = self.env['product.category'].search([('name', '=', 'Maquina')], limit=1)
        if not cat_maquina:
            if self.create_missing_products:
                cat_maquina = self.env['product.category'].create({'name': 'Maquina'})
                _logger.info("Categoría 'Maquina' creada.")
            else:
                raise UserError("La categoría 'Maquina' no existe.")

        modelos = set()
        for row in rows:
            m = row.get('Modelo', '').strip()
            if m:
                modelos.add(m)

        template_map = {}
        for modelo_name in modelos:
            tmpl = ProductTemplate.search([
                ('name', '=', modelo_name),
                ('categ_id', '=', cat_maquina.id)
            ], limit=1)
            if not tmpl:
                if self.create_missing_products:
                    tmpl = ProductTemplate.create({
                        'name': modelo_name,
                        'categ_id': cat_maquina.id,
                        'type': 'consu',
                    })
                    counters['products_created'] += 1
                    _logger.info("Template de máquina creado: %s", modelo_name)
                else:
                    raise UserError(
                        f"El producto template '{modelo_name}' con categoría 'Maquina' no existe "
                        f"y la opción de crear faltantes está desactivada."
                    )

            # Asegurar que el template tenga las attribute lines necesarias
            self._ensure_template_attribute_lines(tmpl, attr_map, rows, attribute_columns, modelo_name)
            template_map[modelo_name] = tmpl

        return template_map

    def _ensure_template_attribute_lines(self, tmpl, attr_map, rows, attribute_columns, modelo_name):
        """
        Asegura que el product.template tenga product.template.attribute.line
        para cada atributo, con los valores correspondientes y su secuencia.
        """
        PTAL = self.env['product.template.attribute.line']

        # Recoger todos los valores usados por este modelo en el CSV
        model_attr_values = {}  # {attr_name: set(value_str)}
        for row in rows:
            if row.get('Modelo', '').strip() != modelo_name:
                continue
            for col in attribute_columns:
                val = row.get(col, '').strip()
                if val:
                    attr_name = col.replace('_', ' ')
                    model_attr_values.setdefault(attr_name, set()).add(val)

        for idx, col in enumerate(attribute_columns, start=10):
            attr_name = col.replace('_', ' ')
            if attr_name not in model_attr_values:
                continue
            value_strs = model_attr_values[attr_name]
            if attr_name not in attr_map:
                continue
            attr_record = list(attr_map[attr_name].values())[0].attribute_id if attr_map[attr_name] else None
            if not attr_record:
                continue

            value_records = [attr_map[attr_name][vs] for vs in value_strs if vs in attr_map[attr_name]]
            if not value_records:
                continue

            # Buscar si ya existe la attribute line
            existing_ptal = PTAL.search([
                ('product_tmpl_id', '=', tmpl.id),
                ('attribute_id', '=', attr_record.id),
            ], limit=1)

            value_ids = [v.id for v in value_records]

            if existing_ptal:
                current_ids = existing_ptal.value_ids.ids
                new_ids = list(set(current_ids + value_ids))
                write_vals = {'sequence': idx}
                if set(new_ids) != set(current_ids):
                    write_vals['value_ids'] = [(6, 0, new_ids)]
                existing_ptal.write(write_vals)
                _logger.info("Secuencia y valores actualizados en attribute line de %s / %s (secuencia: %d)", tmpl.name, attr_name, idx)
            else:
                PTAL.create({
                    'product_tmpl_id': tmpl.id,
                    'attribute_id': attr_record.id,
                    'sequence': idx,
                    'value_ids': [(6, 0, value_ids)],
                })
                _logger.info("Attribute line creada para %s / %s con secuencia %d", tmpl.name, attr_name, idx)

    def _ensure_categories(self, rows, counters):
        """
        Asegura que existan las subcategorías de Accesorio para cada Calc_param.
        Retorna: {calc_param_str: product.category record}
        """
        cat_base = self.env.ref(CATEGORY_BASE_XMLID, raise_if_not_found=False)
        if not cat_base:
            raise UserError("La categoría base 'Accesorio' (cat_accesorio_base) no existe. "
                            "Instale los datos de categorías primero.")

        calc_params = set()
        for row in rows:
            cp = row.get('Calc_param', '').strip()
            if cp:
                calc_params.add(cp)

        category_map = {}

        for cp in calc_params:
            xmlid = CALC_PARAM_CATEGORY_MAP.get(cp)
            if xmlid:
                cat = self.env.ref(xmlid, raise_if_not_found=False)
                if cat:
                    category_map[cp] = cat
                    continue

            # Buscar por nombre como hija de Accesorio
            cat = self.env['product.category'].search([
                ('name', '=', cp),
                ('parent_id', '=', cat_base.id)
            ], limit=1)

            if not cat:
                if self.create_missing_categories:
                    cat = self.env['product.category'].create({
                        'name': cp,
                        'parent_id': cat_base.id,
                    })
                    counters['categories_created'] += 1
                    _logger.info("Categoría de accesorio creada: %s", cp)
                else:
                    raise UserError(
                        f"La categoría para Calc_param '{cp}' no existe y la opción de crear está desactivada."
                    )
            category_map[cp] = cat

        # Agregar el fallback (Por Máquina) para accesorios sin Calc_param
        #cat_fallback = self.env.ref(CATEGORY_FALLBACK_XMLID, raise_if_not_found=False)
        #if cat_fallback:
        #    category_map[''] = cat_fallback
        #else:
        category_map[''] = cat_base

        return category_map

    def _ensure_accessory_products(self, rows, category_map, counters):
        """
        Asegura que existan los product.product para accesorios.
        Retorna: {nombre_item: product.product record}
        """
        ProductProduct = self.env['product.product']
        cat_base = self.env.ref(CATEGORY_BASE_XMLID, raise_if_not_found=False)

        # Recoger accesorios únicos con su calc_param
        accesorios = {}
        for row in rows:
            tipo = row.get('Tipo_Item', '').strip().upper()
            if tipo != 'OPCIONAL':
                continue
            nombre = row.get('Nombre_Item', '').strip()
            cp = row.get('Calc_param', '').strip()
            precio_str = row.get('Precio_Item', '')

            if nombre and nombre not in accesorios:
                accesorios[nombre] = {
                    'calc_param': cp,
                    'precio': self._parse_price(precio_str)
                }

        # IDs de todas las categorías hijas de Accesorio (para búsqueda)
        child_cat_ids = []
        if cat_base:
            child_cats = self.env['product.category'].search([
                ('id', 'child_of', cat_base.id)
            ])
            child_cat_ids = child_cats.ids

        acc_map = {}

        for nombre, info in accesorios.items():
            cp = info['calc_param']
            precio = info['precio']
            
            domain = [('name', '=', nombre)]
            if child_cat_ids:
                domain.append(('categ_id', 'in', child_cat_ids))

            prod = ProductProduct.search(domain, limit=1)
            if not prod:
                if self.create_missing_products:

                    categ = category_map.get(cp, category_map.get(''))
                    create_vals = {
                        'name': nombre,
                        'categ_id': categ.id if categ else (cat_base.id if cat_base else False),
                        'type': 'consu',
                    }

                    if cp:
                        create_vals['list_price'] = precio

                    prod = ProductProduct.create(create_vals)
                    counters['products_created'] += 1
                    _logger.info("Producto accesorio creado: %s (categoría: %s)", nombre, categ.name if categ else 'N/A')
                else:
                    raise UserError(
                        f"El producto accesorio '{nombre}' no existe y la opción de crear está desactivada."
                    )
            else:
                # Si el producto ya existe y se especificó Calc_param, actualizar la categoría si cambió
                if cp:
                    categ = category_map.get(cp, category_map.get(''))
                    if categ and prod.categ_id != categ:
                        prod.write({'categ_id': categ.id})
                        _logger.info("Categoría de accesorio '%s' actualizada a: %s", nombre, categ.name)
            acc_map[nombre] = prod

        return acc_map

    def _ensure_rules(self, rows, counters):
        """
        Asegura que existan los sembradora.accessory.rule para cada regla
        mencionada en el CSV.
        Retorna: {(name, rule_type): sembradora.accessory.rule record}
        """
        Rule = self.env['sembradora.accessory.rule']

        # Recoger todas las reglas únicas del CSV
        rules_needed = {}  # {(name, rule_type): bool}
        for row in rows:
            tipo = row.get('Tipo_Item', '').strip().upper()
            if tipo != 'OPCIONAL':
                continue
            rules_str = row.get('Reglas', '').strip() or row.get('Grupo de exclusion', '').strip()
            parsed = self._parse_rules_str(rules_str)
            for pr in parsed:
                key = (pr['name'], pr['rule_type'])
                rules_needed[key] = True

        rule_map = {}
        for (name, rtype) in rules_needed:
            rule = Rule.search([('name', '=', name), ('rule_type', '=', rtype)], limit=1)
            if not rule:
                rule = Rule.create({
                    'name': name,
                    'rule_type': rtype,
                })
                counters['rules_created'] += 1
                _logger.info("Regla creada: %s (%s)", name, rtype)
            rule_map[(name, rtype)] = rule

        return rule_map

    def _upsert_configs_and_lines(self, rows, attribute_columns, attr_map,
                                   template_map, acc_product_map, rule_map, counters):
        """Crea o actualiza sembradora.config.rel y sus accessory lines."""
        ConfigRel = self.env['sembradora.config.rel']
        AccLine = self.env['sembradora.config.accessory.line']

        # Agrupar filas por ID_Configuracion prefijado por modelo
        grouped = {}
        for row in rows:
            conf_id_raw = row.get('ID_Configuracion', '').strip()
            modelo_name = row.get('Modelo', '').strip()
            ext_id = self._make_ext_id(conf_id_raw, modelo_name)
            if ext_id:
                grouped.setdefault(ext_id, []).append(row)

        for ext_id, conf_rows in grouped.items():
            # Tomar datos de la primera fila BASE
            base_row = None
            for r in conf_rows:
                if r.get('Tipo_Item', '').strip().upper() == 'BASE':
                    base_row = r
                    break
            if not base_row:
                _logger.warning("Configuración %s sin fila BASE, usando primera fila.", ext_id)
                base_row = conf_rows[0]

            modelo_name = base_row.get('Modelo', '').strip()
            tmpl = template_map.get(modelo_name)
            if not tmpl:
                _logger.error("Template no encontrado para modelo '%s' en config %s", modelo_name, ext_id)
                continue

            # Construir los value_ids (product.attribute.value) de la combinación
            value_ids = []
            for col in attribute_columns:
                val_str = base_row.get(col, '').strip()
                if val_str:
                    attr_name = col.replace('_', ' ')
                    val_record = attr_map.get(attr_name, {}).get(val_str)
                    if val_record:
                        value_ids.append(val_record.id)

            precio = self._parse_price(base_row.get('Precio_Base', ''))

            # Buscar config existente por ext_id
            config = ConfigRel.search([('ext_id', '=', ext_id)], limit=1)
            if config:
                config.write({
                    'modelo_id': tmpl.id,
                    'value_ids': [(6, 0, value_ids)],
                    'price': precio,
                })
                counters['configs_updated'] += 1
                _logger.info("Config actualizada: %s", ext_id)
            else:
                config = ConfigRel.create({
                    'ext_id': ext_id,
                    'modelo_id': tmpl.id,
                    'value_ids': [(6, 0, value_ids)],
                    'price': precio,
                })
                counters['configs_created'] += 1
                _logger.info("Config creada: %s", ext_id)

            # --- Líneas de accesorio ---
            existing_acc_lines = AccLine.search([('config_id', '=', config.id)])
            existing_by_product = {line.product_id.id: line for line in existing_acc_lines}
            processed_product_ids = set()

            for r in conf_rows:
                if r.get('Tipo_Item', '').strip().upper() != 'OPCIONAL':
                    continue
                nombre_item = r.get('Nombre_Item', '').strip()
                if not nombre_item:
                    continue

                acc_prod = acc_product_map.get(nombre_item)
                if not acc_prod:
                    _logger.warning("Accesorio '%s' no encontrado en mapa, saltando.", nombre_item)
                    continue

                precio_item = self._parse_price(r.get('Precio_Item', ''))
                # Parsear reglas de esta fila
                rules_str = r.get('Reglas', '').strip() or r.get('Grupo de exclusion', '').strip()
                parsed_rules = self._parse_rules_str(rules_str)
                
                rule_ids = []
                is_trigger = False
                for pr in parsed_rules:
                    key = (pr['name'], pr['rule_type'])
                    rule = rule_map.get(key)
                    if rule:
                        rule_ids.append(rule.id)
                        if pr.get('is_trigger'):
                            is_trigger = True

                if acc_prod.id in existing_by_product:
                    # Actualizar línea existente
                    acc_line = existing_by_product[acc_prod.id]
                    acc_line.write({
                        'price': precio_item,
                        'rule_ids': [(6, 0, rule_ids)],
                        'is_trigger': is_trigger,
                    })
                    counters['acc_lines_updated'] += 1
                else:
                    # Crear nueva línea
                    acc_line = AccLine.create({
                        'config_id': config.id,
                        'product_id': acc_prod.id,
                        'price': precio_item,
                        'rule_ids': [(6, 0, rule_ids)],
                        'is_trigger': is_trigger,
                    })
                    counters['acc_lines_created'] += 1

                processed_product_ids.add(acc_prod.id)

            # Líneas de accesorio que estaban antes y ya no están en el CSV → se eliminan
            for prod_id, line in existing_by_product.items():
                if prod_id not in processed_product_ids:
                    _logger.info("Eliminando línea de accesorio obsoleta: %s en config %s",
                                 line.product_id.name, conf_id)
                    line.unlink()
