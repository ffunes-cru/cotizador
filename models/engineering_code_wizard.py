"""@file
Asistente de códigos de ingeniería (Teamcenter): exporta una plantilla y carga los códigos.

Flujo en tres pasos:
1. **Plantilla espejo** (action_generate_template()): Excel (o CSV si falta `openpyxl`) con una
   fila por variante (hay una por configuración de la matriz). Las alternativas para máquinas sin
   variantes (una fila por configuración o por combinación teórica) quedan por compatibilidad con
   plantillas ya enviadas. Ingeniería completa la columna `CODIGO_INGENIERIA_TEAMCENTER`.
2. **Simulación** (action_analyze_file()): cruza cada fila con Odoo, primero por `ID_Odoo`
   confirmado con los valores de atributo de la fila, y si no por los valores de atributo; muestra
   coincidencias, faltantes y códigos sin match.
3. **Aplicación** (action_apply_codes()): escribe los códigos en la referencia interna de la
   variante (`product.product.default_code`) con SQL directo por lotes (miles de filas).
"""
import base64
import csv
import io
import json
import logging
from odoo import models, fields, api, _
from odoo.tools import SQL
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

## Filas por sentencia UPDATE al aplicar los códigos.
APPLY_BATCH_SIZE = 5000

try:
    import openpyxl
    OPENPYXL_AVAILABLE = True
except ImportError:
    OPENPYXL_AVAILABLE = False


class EngineeringCodeWizard(models.TransientModel):
    """Asistente `engineering.code.wizard` (solo Administrador del Configurador)."""
    _name = 'engineering.code.wizard'
    _description = 'Asistente de Carga de Códigos de Ingeniería (Teamcenter)'

    modelo_id = fields.Many2one(
        'product.template',
        string='Modelo de Máquina',
        required=True,
        domain=[('is_maquina', '=', True)],
        help='Seleccione el modelo de máquina a sincronizar con Teamcenter.'
    )

    state = fields.Selection([
        ('upload', '1. Plantilla y Carga'),
        ('preview', '2. Simulación de Matching'),
        ('done', '3. Sincronización Completada')
    ], string='Estado', default='upload')

    # Archivo Plantilla generado para Ingeniería
    template_file = fields.Binary(string='Descargar Plantilla Espejo', readonly=True)
    template_filename = fields.Char(string='Nombre Plantilla')

    # Archivo completado por Ingeniería
    import_file = fields.Binary(string='Archivo de Ingeniería (Excel o CSV)')
    import_filename = fields.Char(string='Nombre del Archivo')

    # Métricas de la simulación
    total_odoo_variants = fields.Integer(string='Total Variantes en Odoo', readonly=True)
    matched_count = fields.Integer(string='Coincidencias Exactas', readonly=True)
    missing_in_file_count = fields.Integer(string='Variantes Odoo Faltantes en Archivo', readonly=True)
    extra_in_file_count = fields.Integer(string='Filas de Archivo sin Match en Odoo', readonly=True)

    preview_html = fields.Html(string='Resumen de Simulación', readonly=True)
    matched_data_json = fields.Text(string='Datos de Coincidencia (JSON)')

    # -------------------------------------------------------------------------
    # 1. EXPORTACIÓN DE PLANTILLA ESPEJO
    # -------------------------------------------------------------------------

    def action_generate_template(self):
        """Paso 1: genera la plantilla espejo para que Ingeniería complete los códigos.

        Columnas: `ID_Odoo`, `Modelo`, un atributo por columna (en orden de la plantilla),
        `CODIGO_INGENIERIA_TEAMCENTER` (vacía) y `Codigo_Actual_Odoo`.

        @return Acción que reabre el asistente con el archivo para descargar.
        @throws UserError Si no hay modelo o el modelo no tiene atributos.
        """
        self.ensure_one()
        if not self.modelo_id:
            raise UserError(_("Debe seleccionar un modelo de máquina."))

        # Asegurarse de tener los atributos ordenados por secuencia
        ptals = self.modelo_id.attribute_line_ids.sorted(lambda l: (l.sequence, l.id))
        if not ptals:
            raise UserError(_("El modelo seleccionado no tiene atributos configurados."))

        attr_names = [ptal.attribute_id.name for ptal in ptals]

        # 1. Variantes físicas creadas en product.product
        variants = self.env['product.product'].search([
            ('product_tmpl_id', '=', self.modelo_id.id)
        ])

        # 2. Configuraciones de la máquina en sembradora.config.rel
        configs = self.env['sembradora.config.rel'].search([
            ('modelo_id', '=', self.modelo_id.id)
        ])

        # Filas a exportar: tuplas de (id_odoo, model_name, val_by_attr, current_code)
        export_rows = []
        if variants:
            for var in variants:
                val_by_attr = {
                    ptav.attribute_id.name: ptav.name
                    for ptav in var.product_template_attribute_value_ids
                }
                export_rows.append((var.id, self.modelo_id.name, val_by_attr, var.default_code or ''))
        elif configs:
            for cfg in configs:
                val_by_attr = {
                    val.attribute_id.name: val.name
                    for val in cfg.value_ids
                }
                export_rows.append((cfg.id, self.modelo_id.name, val_by_attr, cfg.ext_id or ''))
        else:
            # Fallback para modelos con creación dinámica de variantes sin configs aún
            import itertools
            val_options = [[(val.attribute_id.name, val.name) for val in ptal.value_ids] for ptal in ptals]
            for combo in itertools.product(*val_options):
                val_by_attr = dict(combo)
                export_rows.append(('', self.modelo_id.name, val_by_attr, ''))

        total_rows = len(export_rows)

        # Generación con openpyxl si está disponible, o CSV como fallback
        if OPENPYXL_AVAILABLE:
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Variantes_Odoo"

            # Encabezados
            headers = ["ID_Odoo", "Modelo"] + attr_names + ["CODIGO_INGENIERIA_TEAMCENTER", "Codigo_Actual_Odoo"]
            ws.append(headers)

            # Estilo básico en cabecera
            header_fill = openpyxl.styles.PatternFill(start_color="C8102E", end_color="C8102E", fill_type="solid")
            header_font = openpyxl.styles.Font(color="FFFFFF", bold=True)
            for col_num, _ in enumerate(headers, 1):
                cell = ws.cell(row=1, column=col_num)
                cell.fill = header_fill
                cell.font = header_font

            # Filas
            for row_id, mname, val_by_attr, cur_code in export_rows:
                row_data = [row_id, mname]
                for aname in attr_names:
                    row_data.append(val_by_attr.get(aname, ''))
                row_data.append('')  # Espacio para que completen el código
                row_data.append(cur_code)
                ws.append(row_data)

            output = io.BytesIO()
            wb.save(output)
            file_data = base64.b64encode(output.getvalue())
            filename = f"Plantilla_Ingenieria_{self.modelo_id.name.replace(' ', '_')}.xlsx"
        else:
            output = io.StringIO()
            writer = csv.writer(output, delimiter=';')
            headers = ["ID_Odoo", "Modelo"] + attr_names + ["CODIGO_INGENIERIA_TEAMCENTER", "Codigo_Actual_Odoo"]
            writer.writerow(headers)

            for row_id, mname, val_by_attr, cur_code in export_rows:
                row_data = [row_id, mname]
                for aname in attr_names:
                    row_data.append(val_by_attr.get(aname, ''))
                row_data.append('')
                row_data.append(cur_code)
                writer.writerow(row_data)

            file_data = base64.b64encode(output.getvalue().encode('utf-8-sig'))
            filename = f"Plantilla_Ingenieria_{self.modelo_id.name.replace(' ', '_')}.csv"

        self.write({
            'template_file': file_data,
            'template_filename': filename,
            'total_odoo_variants': total_rows,
        })

        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    # -------------------------------------------------------------------------
    # 2. SIMULACIÓN Y CRUCE (DRY-RUN MATCHING)
    # -------------------------------------------------------------------------

    def _clean_str(self, val):
        """Normaliza un valor de celda para comparar: mayúsculas, sin acentos, sin ".0" final.

        @param val Valor de la celda (texto, número o None).
        @return Texto normalizado ('' para None).
        """
        if val is None:
            return ""
        s = str(val).strip().upper()
        # Normalizaciones de decimales habituales
        if s.endswith('.0'):
            s = s[:-2]
        # Reemplazar acentos
        replacements = (
            ('Á', 'A'), ('É', 'E'), ('Í', 'I'), ('Ó', 'O'), ('Ú', 'U'),
            ('À', 'A'), ('È', 'E'), ('Ì', 'I'), ('Ò', 'O'), ('Ù', 'U'),
        )
        for r, to in replacements:
            s = s.replace(r, to)
        return s

    def _parse_input_file(self):
        """Lee el archivo completado por Ingeniería (.xlsx, o CSV con separador detectado).

        @return Lista de dicts {encabezado: valor}, sin filas vacías.
        @throws UserError Si no hay archivo, el Excel está vacío o no se reconoce la codificación.
        """
        if not self.import_file:
            raise UserError(_("Por favor, cargue el archivo completado por Ingeniería."))

        file_bytes = base64.b64decode(self.import_file)
        fname = (self.import_filename or '').lower()

        rows = []
        if fname.endswith('.xlsx') and OPENPYXL_AVAILABLE:
            wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
            ws = wb.active
            iter_rows = ws.iter_rows(values_only=True)
            try:
                headers = [str(h).strip() if h is not None else f"COL_{i}" for i, h in enumerate(next(iter_rows))]
            except StopIteration:
                raise UserError(_("El archivo Excel está vacío."))

            for r in iter_rows:
                if any(cell is not None and str(cell).strip() != '' for cell in r):
                    row_dict = {headers[i]: r[i] for i in range(min(len(headers), len(r)))}
                    rows.append(row_dict)
        else:
            # Intentar decodificar como CSV
            text = None
            for encoding in ['utf-8-sig', 'utf-8', 'latin-1', 'cp1252']:
                try:
                    text = file_bytes.decode(encoding)
                    break
                except UnicodeDecodeError:
                    continue

            if not text:
                raise UserError(_("No se pudo leer la codificación del archivo."))

            # Detectar delimitador
            sample = text[:4096]
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=',;\t|')
                delimiter = dialect.delimiter
            except Exception:
                delimiter = ';' if ';' in sample else ','

            reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
            rows = [dict(r) for r in reader if any(v.strip() for v in r.values() if v)]

        return rows

    def action_analyze_file(self):
        """Paso 2: cruza las filas del archivo con las variantes y configuraciones del modelo.

        Cada fila con código se busca:
          1. por `ID_Odoo`: puede ser de una variante o (plantillas anteriores) de una
             configuración, y el mismo número puede existir en los dos; se acepta el registro
             cuyos valores de atributo coinciden con los de la fila (o el único, si el archivo no
             tiene columnas de atributo);
          2. si no, por la tupla de valores de atributo normalizados (con la tabla de alias).
        Una configuración se resuelve a su variante: el código siempre va a la variante. Guarda
        las coincidencias en `matched_data_json` y arma un resumen HTML con muestras.

        @return Acción que reabre el asistente en el paso de simulación.
        @throws UserError Si el archivo no tiene filas o no tiene columna de código.
        """
        self.ensure_one()
        rows = self._parse_input_file()
        if not rows:
            raise UserError(_("No se encontraron filas con datos en el archivo cargado."))

        variants = self.env['product.product'].search([
            ('product_tmpl_id', '=', self.modelo_id.id)
        ])
        configs = self.env['sembradora.config.rel'].search([
            ('modelo_id', '=', self.modelo_id.id)
        ])
        total_variants = len(variants) or len(configs)
        if total_variants == 0:
            total_variants = 1
            for ptal in self.modelo_id.attribute_line_ids:
                total_variants *= len(ptal.value_ids) or 1

        # 1. Mapas de lookup por ID directo de Odoo
        variant_by_id = {v.id: v for v in variants}
        config_by_id = {c.id: c for c in configs}

        # 2. Mapas de lookup por tupla ordenada de valores de atributo normalizados
        variant_attrs = {}
        variant_by_attrs = {}
        for var in variants:
            attr_tuple = tuple(sorted(
                self._clean_str(ptav.name)
                for ptav in var.product_template_attribute_value_ids
            ))
            variant_by_attrs[attr_tuple] = var
            variant_attrs[var.id] = attr_tuple

        config_attrs = {}
        config_by_attrs = {}
        for cfg in configs:
            attr_tuple = tuple(sorted(
                self._clean_str(v.name)
                for v in cfg.value_ids
            ))
            config_by_attrs[attr_tuple] = cfg
            config_attrs[cfg.id] = attr_tuple

        # Identificar columna del código de ingeniería
        first_row = rows[0]
        code_col = None
        for col_name in first_row.keys():
            cleaned_col = self._clean_str(col_name)
            if any(k in cleaned_col for k in ['CODIGO_INGENIERIA', 'CODIGO_TEAMCENTER', 'CODE', 'CODIGO', 'INGENIERIA']):
                code_col = col_name
                break

        if not code_col:
            for col_name in first_row.keys():
                if 'COD' in self._clean_str(col_name):
                    code_col = col_name
                    break

        if not code_col:
            raise UserError(_(
                "No se encontró una columna de código en el archivo. "
                "Asegúrese de nombrar la columna 'CODIGO_INGENIERIA_TEAMCENTER' o 'CODIGO'."
            ))

        # Atributos válidos del modelo en Odoo
        ptals = self.modelo_id.attribute_line_ids
        odoo_attr_names = {self._clean_str(ptal.attribute_id.name): ptal.attribute_id.name for ptal in ptals}

        # Detección de columnas de atributo en el archivo
        file_attr_cols = {}
        for col_name in first_row.keys():
            c_clean = self._clean_str(col_name)
            if c_clean in odoo_attr_names:
                file_attr_cols[col_name] = odoo_attr_names[c_clean]

        matched_data = []  # [{product_id, code, old_code, name}]
        matched_variant_ids = set()
        extra_rows = []

        # Alias comunes para atributos
        alias_map = {
            '0.35': '35', '0.42': '42', '0.525': '52.5', '0.52': '52.5', '0.70': '70', '0.7': '70',
            '35CM': '35', '42CM': '42', '52CM': '52.5', '70CM': '70',
            'MEC': 'MECANICO', 'NEU': 'NEUMATICO', 'NEUM': 'NEUMATICO', 'PRECISION': 'NEUMATICO',
            'PP': 'PP', 'LEAF': 'LEAF', 'CLASICA': 'LEAF CLASICA',
            'INT': 'TOLVA INTEGRAL S/F', 'SS': 'TOLVA SS + ADICIONAL FERT.',
        }

        for row in rows:
            code_val = str(row.get(code_col) or '').strip()
            if not code_val:
                continue

            # Valores de atributo de la fila, normalizados (vacío si el archivo no tiene esas columnas)
            row_tuple = tuple(sorted(
                value for value in (alias_map.get(self._clean_str(row.get(fcol)), self._clean_str(row.get(fcol)))
                                    for fcol in file_attr_cols) if value
            ))

            # Intento A: por ID_Odoo. Plantillas anteriores pueden traer ids de variantes o de
            # configuraciones; un mismo número puede existir en los dos, así que se acepta solo si
            # los valores de la fila confirman a cuál corresponde (o si es inequívoco).
            matched_var = matched_cfg = None
            for id_col in ['ID_Odoo', 'ID_ODIO', 'ID_VARIANTE', 'ID']:
                if id_col not in row or not row[id_col]:
                    continue
                try:
                    vid = int(str(row[id_col]).strip())
                except ValueError:
                    continue
                candidates = [rec for rec, attrs in (
                    (variant_by_id.get(vid), variant_attrs.get(vid)),
                    (config_by_id.get(vid), config_attrs.get(vid)),
                ) if rec and (attrs == row_tuple if row_tuple else True)]
                if len(candidates) == 1:
                    matched_var = candidates[0] if candidates[0]._name == 'product.product' else None
                    matched_cfg = candidates[0] if candidates[0]._name == 'sembradora.config.rel' else None
                break

            # Intento B: por los valores de atributo
            if not matched_var and not matched_cfg and row_tuple:
                matched_var = variant_by_attrs.get(row_tuple)
                matched_cfg = None if matched_var else config_by_attrs.get(row_tuple)

            # El código va siempre a la variante (una por configuración)
            if matched_cfg:
                try:
                    matched_var = matched_cfg._get_variant()
                except UserError:
                    matched_var = None
            if matched_var:
                key_id = f"V_{matched_var.id}"
                if key_id not in matched_variant_ids:
                    matched_variant_ids.add(key_id)
                    matched_data.append({
                        'product_id': matched_var.id,
                        'code': code_val,
                        'old_code': matched_var.default_code or '',
                        'name': matched_var.display_name,
                    })
            else:
                extra_rows.append({
                    'code': code_val,
                    'raw_row': {k: str(v) for k, v in row.items() if v}
                })

        missing_count = total_variants - len(matched_variant_ids)
        matched_count = len(matched_variant_ids)
        extra_count = len(extra_rows)

        # Generar Reporte HTML de Simulación
        preview_html = f"""
        <div class="mb-3">
            <div class="row g-3 text-center mb-4">
                <div class="col-md-3">
                    <div class="p-3 bg-light rounded border">
                        <div class="text-muted small fw-bold">TOTAL VARIANTES ODOO</div>
                        <div class="fs-4 fw-bold text-dark">{total_variants:,}</div>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="p-3 bg-success-subtle rounded border border-success">
                        <div class="text-success small fw-bold">COINCIDENCIAS EXACTAS 🟢</div>
                        <div class="fs-4 fw-bold text-success">{matched_count:,}</div>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="p-3 bg-warning-subtle rounded border border-warning">
                        <div class="text-warning-emphasis small fw-bold">SIN CÓDIGO EN ARCHIVO 🟡</div>
                        <div class="fs-4 fw-bold text-warning-emphasis">{missing_count:,}</div>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="p-3 bg-danger-subtle rounded border border-danger">
                        <div class="text-danger small fw-bold">CÓDIGOS NO RECONOCIDOS 🔴</div>
                        <div class="fs-4 fw-bold text-danger">{extra_count:,}</div>
                    </div>
                </div>
            </div>
        """

        if matched_count > 0:
            sample_matched = matched_data[:8]
            preview_html += """
            <h6 class="fw-bold text-success mb-2"><i class="fa fa-check-circle me-1"/> Muestra de Códigos a Asignar:</h6>
            <div class="table-responsive mb-3 border rounded">
                <table class="table table-sm table-hover mb-0" style="font-size: 12.5px;">
                    <thead class="table-light">
                        <tr>
                            <th>ID Odoo</th>
                            <th>Variante</th>
                            <th>Código Anterior</th>
                            <th>Nuevo Código Ingeniería</th>
                        </tr>
                    </thead>
                    <tbody>
            """
            for m in sample_matched:
                old_badge = f"<span class='text-muted'>{m['old_code']}</span>" if m['old_code'] else "<span class='badge bg-light text-secondary'>Sin código</span>"
                preview_html += f"""
                    <tr>
                        <td><strong>{m['product_id']}</strong></td>
                        <td>{m['name']}</td>
                        <td>{old_badge}</td>
                        <td><span class="badge bg-success font-monospace">{m['code']}</span></td>
                    </tr>
                """
            if matched_count > 8:
                preview_html += f"<tr><td colspan='4' class='text-center text-muted font-italic'>... y {matched_count - 8:,} variantes más listas para sincronizar.</td></tr>"
            preview_html += "</tbody></table></div>"

        if extra_count > 0:
            sample_extra = extra_rows[:5]
            preview_html += f"""
            <h6 class="fw-bold text-danger mt-3 mb-2"><i class="fa fa-exclamation-triangle me-1"/> Códigos de Teamcenter que no coinciden con ninguna variante de Odoo ({extra_count:,}):</h6>
            <div class="table-responsive mb-3 border rounded">
                <table class="table table-sm table-hover mb-0" style="font-size: 12px;">
                    <thead class="table-danger">
                        <tr>
                            <th>Código</th>
                            <th>Datos en Archivo</th>
                        </tr>
                    </thead>
                    <tbody>
            """
            for ex in sample_extra:
                desc = ", ".join(f"{k}: {v}" for k, v in list(ex['raw_row'].items())[:4])
                preview_html += f"<tr><td><strong>{ex['code']}</strong></td><td><span class='text-muted'>{desc}</span></td></tr>"
            preview_html += "</tbody></table></div>"

        preview_html += "</div>"

        self.write({
            'state': 'preview',
            'total_odoo_variants': total_variants,
            'matched_count': matched_count,
            'missing_in_file_count': missing_count,
            'extra_in_file_count': extra_count,
            'preview_html': preview_html,
            'matched_data_json': json.dumps(matched_data),
        })

        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    # -------------------------------------------------------------------------
    # 3. APLICACIÓN MASIVA DE ALTA VELOCIDAD (SQL DIRECTO)
    # -------------------------------------------------------------------------

    def action_apply_codes(self):
        """Paso 3: escribe los códigos simulados.

        Escribe `default_code` de las variantes con SQL directo con parámetros, por lotes de
        APPLY_BATCH_SIZE filas; después invalida la caché del ORM.

        @return Acción que reabre el asistente con el resumen.
        @throws UserError Si no hay coincidencias para aplicar.
        """
        self.ensure_one()
        if not self.matched_data_json:
            raise UserError(_("No hay datos de coincidencia para aplicar."))

        matched_data = json.loads(self.matched_data_json)
        if not matched_data:
            raise UserError(_("La lista de códigos coincidentes está vacía."))

        products = [(int(item['product_id']), item['code']) for item in matched_data if item.get('product_id')]
        # SQL directo (miles de filas en una sola sentencia), con parámetros: nunca texto concatenado
        for i in range(0, len(products), APPLY_BATCH_SIZE):
            values = SQL(", ").join(SQL("(%s::int, %s::varchar)", pid, code) for pid, code in products[i:i + APPLY_BATCH_SIZE])
            self.env.cr.execute(SQL(
                "UPDATE product_product AS t SET default_code = v.code FROM (VALUES %s) AS v(id, code) WHERE t.id = v.id",
                values,
            ))
        applied_total = len(matched_data)

        # Invalidar caché de Odoo en memoria
        self.env['product.product'].invalidate_model(['default_code'])

        summary_done = f"""
        <div class="alert alert-success p-3 text-center my-3">
            <h4 class="alert-heading fw-bold"><i class="fa fa-check-circle me-2"/>¡Sincronización Exitosa!</h4>
            <p class="mb-0 fs-5">Se actualizaron <strong>{applied_total:,}</strong> códigos de ingeniería en el modelo <strong>{self.modelo_id.name}</strong>.</p>
        </div>
        """

        self.write({
            'state': 'done',
            'preview_html': summary_done,
        })

        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_back_to_upload(self):
        """Vuelve al paso 1 descartando el archivo y la simulación.

        @return Acción que reabre el asistente.
        """
        self.write({
            'state': 'upload',
            'import_file': False,
            'preview_html': False,
            'matched_data_json': False,
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
