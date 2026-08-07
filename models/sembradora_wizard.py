from odoo import models, fields, api
from odoo.exceptions import ValidationError
import logging
import re
_logger = logging.getLogger(__name__)

class SembradoraConfigWizard(models.TransientModel):
    _name = 'sembradora.config.wizard'
    _description = 'Configurador Dinámico'

    sale_order_id = fields.Many2one('sale.order', string='Venta')
    modelo_id = fields.Many2one('product.template', string='Modelo',
                                domain=[("categ_id.name", "=", "Maquina")])

    # Filas dinámicas
    line_ids = fields.One2many('sembradora.config.wizard.line', 'wizard_id', string='Atributos')

    # Selección de accesorios (One2many a línea transient con checkbox)
    accessory_selection_ids = fields.One2many(
        'sembradora.config.wizard.acc.selection',
        'wizard_id',
        string='Accesorios Disponibles')

    config_finalizada = fields.Boolean(string="¿Configuración Completa?", default=False)

    # Precio total computado: precio base + accesorios seleccionados
    config_base_price = fields.Float(string="Precio Base Configuración", readonly=True)
    accessories_total = fields.Float(string="Total Accesorios", compute="_compute_accessories_total")
    total_price = fields.Float(string="Precio Total", compute="_compute_total_price")

    @api.depends('accessory_selection_ids.selected', 'accessory_selection_ids.price')
    def _compute_accessories_total(self):
        for wiz in self:
            wiz.accessories_total = sum(
                line.price for line in wiz.accessory_selection_ids if line.selected
            )

    @api.depends('config_base_price', 'accessories_total')
    def _compute_total_price(self):
        for wiz in self:
            wiz.total_price = wiz.config_base_price + wiz.accessories_total

    def _extraer_factor_de_atributos(self, nombres_atributo):
        """
        Busca en las líneas del wizard un atributo cuyo nombre coincida exactamente con
        algún elemento de 'nombres_atributo' y extrae el primer número (entero o decimal).
        """
        if isinstance(nombres_atributo, str):
            nombres_atributo = [nombres_atributo]
        nombres_clean = [n.strip().lower() for n in nombres_atributo]

        for line in self.line_ids:
            if line.attribute_id and line.value_id:
                nombre_attr = line.attribute_id.name.strip().lower()
                if nombre_attr in nombres_clean:
                    texto_valor = line.value_id.name
                    numeros = re.findall(r'\d+\.?\d*', texto_valor)
                    if numeros:
                        return float(numeros[0])
        return 1.0  # Fallback si no encuentra el atributo o un número válido

    def _poblar_accesorios(self, configs):
        """Pobla los accesorios aplicando precios unitarios y cantidades dinámicas por separado."""
        acc_lines = configs.mapped('accessory_line_ids')
        acc_commands = [(5, 0, 0)]  # Limpiar líneas existentes del wizard
        
        cat_lineas = self.env.ref('cotizador.cat_accesorio_cantidad_lineas', raise_if_not_found=False)
        cat_distancia = self.env.ref('cotizador.cat_accesorio_distancia_lineas', raise_if_not_found=False)
        cat_por_maquina = self.env.ref('cotizador.cat_accesorio_por_maquina', raise_if_not_found=False)

        for acc_line in acc_lines:
            producto = acc_line.product_id
            categoria = producto.categ_id
            
            # Valores base por defecto
            precio_unitario = producto.list_price
            cantidad = 1.0

            # 1. Determinación de Cantidad y Precio según Categoría
            if cat_lineas and categoria == cat_lineas:
                precio_unitario = producto.list_price
                cantidad = self._extraer_factor_de_atributos([
                    'cantidad de líneas', 'cantidad de lineas', 'cantidad lineas', 'cantidad de líneas:'
                ])
                
            elif cat_distancia and categoria == cat_distancia:
                precio_unitario = producto.list_price
                cantidad = self._extraer_factor_de_atributos([
                    'distancia entre líneas', 'distancia entre lineas', 'distancia de lineas', 'espaciamiento'
                ])
                
            elif cat_por_maquina and categoria == cat_por_maquina:
                precio_unitario = producto.list_price
                cantidad = 1.0
                
            elif categoria.id == 9:  # Ruedas / Keeton
                precio_unitario = acc_line.price  # Trae el precio unitario de la matriz
                cantidad = self.get_acc_quan('Keeton')
                
            elif categoria.id == 8:  # Cuerpos
                precio_unitario = acc_line.price  # Trae el precio unitario de la matriz
                cantidad = self.get_acc_quan('Cuerpos')
                
            else:
                # Cualquier otro accesorio general de la matriz
                precio_unitario = acc_line.price
                cantidad = 1.0

            _logger.info("Accesorio detectado: %s -> Cantidad: %s, Precio Unitario: %s", producto.name, cantidad, precio_unitario)

            # 2. Determinar estado de bloqueo inicial por reglas de inclusión
            #    Un accesorio con regla de inclusión donde NO es trigger → empieza bloqueado
            is_inclusion_locked = False
            for rule in acc_line.rule_ids:
                if rule.rule_type == 'inclusion' and not acc_line.is_trigger:
                    is_inclusion_locked = True
                    break

            # 3. Construir comando para el One2many del Wizard
            acc_commands.append((0, 0, {
                'config_acc_line_id': acc_line.id,
                'selected': False,
                'price_unit': precio_unitario,
                'quantity': cantidad,
                'is_locked': is_inclusion_locked,
                'is_inclusion_locked': is_inclusion_locked,
            }))

        self.accessory_selection_ids = acc_commands

    @api.onchange('modelo_id', 'line_ids')
    def _onchange_configuracion_secuencial(self):
        if not self.modelo_id:
            self.line_ids = [(5, 0, 0)]
            self.accessory_selection_ids = [(5, 0, 0)]
            self.config_base_price = 0
            return

        todas_configs = self.env['sembradora.config.rel'].search([
            ('modelo_id', '=', self.modelo_id.id)
        ])

        # 1. Caso inicial: Sin líneas
        if not self.line_ids:
            all_attrs = todas_configs.mapped('value_ids.attribute_id')
            if all_attrs:
                model_attr_order = {attr.id: i for i, attr in enumerate(self.modelo_id.attribute_line_ids.sorted('sequence').mapped('attribute_id'))}
                all_attrs_sorted = sorted(all_attrs, key=lambda a: model_attr_order.get(a.id, a.sequence or 999))
                self.line_ids = [(0, 0, {'attribute_id': all_attrs_sorted[0].id})]
            return
        
        # --- OPTIMIZACIÓN: Trabajaremos con listas locales de registros (memoria pura) ---
        lineas_vivas_list = [l for l in self.line_ids if not isinstance(l, tuple) or l[0] != 2]
        valores_seleccionados_ids = [l.value_id.id for l in lineas_vivas_list if l.value_id]

        # Validar consistencia de lo que ya está seleccionado
        cortar = False
        lineas_validadas = []
        valores_filtrados_ids = []

        for line in lineas_vivas_list:
            if cortar:
                continue
            if line.value_id:
                check_ids = valores_filtrados_ids + [line.value_id.id]
                # Al tener name con store=True, esto vuela
                if todas_configs.filtered(lambda c: all(vid in c.value_ids.ids for vid in check_ids)):
                    lineas_validadas.append(line)
                    valores_filtrados_ids.append(line.value_id.id)
                else:
                    cortar = True
            else:
                lineas_validadas.append(line)
                cortar = True

        valores_seleccionados_ids = valores_filtrados_ids

        # Filtrar configs válidas en memoria
        configs_validas = todas_configs.filtered(
            lambda c: all(vid in c.value_ids.ids for vid in valores_seleccionados_ids)
        )

        self.config_finalizada = False
        configs_restantes = configs_validas

        # --- EL BUCLE OPTIMIZADO (Sin escrituras intermedias a la UI) ---
        while True:
            if not lineas_validadas:
                break
                
            ultima = lineas_validadas[-1]
            if not ultima.value_id:
                break

            attrs_actuales = [l.attribute_id for l in lineas_validadas]
            attrs_posibles = configs_restantes.mapped('value_ids.attribute_id')
            
            # Ordenar atributos según la secuencia definida en la plantilla del producto
            model_attr_order = {attr.id: i for i, attr in enumerate(self.modelo_id.attribute_line_ids.sorted('sequence').mapped('attribute_id'))}
            attrs_posibles_sorted = sorted(attrs_posibles, key=lambda a: model_attr_order.get(a.id, a.sequence or 999))

            # Restar usando conjuntos en lugar de objetos de Odoo (más rápido)
            proximos = [a for a in attrs_posibles_sorted if a not in attrs_actuales]
            
            if not proximos:
                self.config_finalizada = True
                break

            siguiente_attr = proximos[0]
            valores_disponibles = configs_restantes.mapped('value_ids').filtered(
                lambda v: v.attribute_id == siguiente_attr
            )
            
            # Simulamos el registro en la lista local de Python
            nueva_linea_mock = {
                'attribute_id': siguiente_attr,
                'value_id': False,
                'is_single_option': False
            }
            
            if len(valores_disponibles) == 1:
                val_unico = valores_disponibles[0]
                nueva_linea_mock['value_id'] = val_unico
                nueva_linea_mock['is_single_option'] = True
                valores_seleccionados_ids.append(val_unico.id)
                
                configs_validas = configs_validas.filtered(lambda c: val_unico.id in c.value_ids.ids)
                configs_restantes = configs_validas
                
                # Lo agregamos a nuestra colección temporal de Python
                # Usamos un objeto Dummy/Banda para que el bucle pueda seguir leyendo
                class DummyRecord:
                    def __init__(self, d):
                        self.attribute_id = d['attribute_id']
                        self.value_id = d['value_id']
                lineas_validadas.append(DummyRecord(nueva_linea_mock))
                continue 
            else:
                class DummyRecordVacio:
                    def __init__(self, d):
                        self.attribute_id = d['attribute_id']
                        self.value_id = False
                lineas_validadas.append(DummyRecordVacio(nueva_linea_mock))
                break

        # --- UNA SOLA ESCRITURA FINAL A ODOO ---
        # Convertimos nuestra lista de Python al formato de comandos de Odoo (4, id) y (0, 0, vals)
        comandos_finales = []
        for l in lineas_vivas_list:
            if l in lineas_validadas:
                comandos_finales.append((4, l.id.origin or l.id))
            else:
                comandos_finales.append((2, l.id.origin or l.id)) # Borrar las sobrantes

        # Agregar las nuevas líneas auto-generadas del bucle
        for l in lineas_validadas:
            if not hasattr(l, 'id'): # Es una línea nueva simulada
                comandos_finales.append((0, 0, {
                    'attribute_id': l.attribute_id.id,
                    'value_id': l.value_id.id if l.value_id else False,
                    'is_single_option': True if l.value_id else False
                }))

        self.line_ids = comandos_finales

        # === OPTIMIZACIÓN CRÍTICA DE ACCESORIOS ===
        # Solo poblamos accesorios y disparamos lógica pesada si la máquina está completa
        if self.config_finalizada and len(configs_restantes) == 1:
            self.config_base_price = configs_restantes.price
            self._poblar_accesorios(configs_restantes) # <--- Aquí adentro metes las queries pesadas
        else:
            self.config_base_price = 0
            self.accessory_selection_ids = [(5, 0, 0)] # Mantener vacío mientras elige
            
    def get_acc_quan(self, attribute_name):
        linea_cantidad = self.line_ids.filtered(
            lambda l: l.attribute_id.name in [attribute_name]
        )
        
        factor_qty = 1
        if linea_cantidad and linea_cantidad.value_id:
            # Extraemos el número del nombre del valor (ej: de "16 Líneas" extrae 16)
            texto_valor = linea_cantidad.value_id.name
            numeros = re.findall(r'\d+', texto_valor)
            _logger.info("valores a parsear %s y texto parseado %s" ,texto_valor, numeros)
            if numeros:
                factor_qty = int(numeros[0])
        else:
            _logger.warning("valores null de %s y %s",linea_cantidad, self.line_ids.mapped("attribute_id.name"))
        return factor_qty

    @api.onchange('accessory_selection_ids')
    def _onchange_accessory_rules(self):
        """Bloquea/desbloquea accesorios según reglas de exclusión e inclusión."""
        # --- Paso 1: Recopilar el estado actual de reglas ---
        rule_state = {}

        for wiz_line in self.accessory_selection_ids:
            if not wiz_line.rule_ids:
                continue
            for rule in wiz_line.rule_ids:
                rid = rule.id
                if rid not in rule_state:
                    rule_state[rid] = {
                        'rule': rule,
                        'selected_lines': [],
                        'all_lines': [],
                        'triggers': [],
                        'non_triggers': [],
                    }
                rule_state[rid]['all_lines'].append(wiz_line)
                if wiz_line.selected:
                    rule_state[rid]['selected_lines'].append(wiz_line)
                if wiz_line.is_trigger:
                    rule_state[rid]['triggers'].append(wiz_line)
                else:
                    rule_state[rid]['non_triggers'].append(wiz_line)

        # --- Paso 2: Evaluar bloqueos ---
        lock_reasons = {wiz_line: set() for wiz_line in self.accessory_selection_ids}

        for rid, state in rule_state.items():
            rule = state['rule']

            if rule.rule_type == 'exclusion':
                # EXCLUSIÓN: Si hay alguno seleccionado, bloquear los demás del grupo
                if state['selected_lines']:
                    for wiz_line in state['all_lines']:
                        if not wiz_line.selected:
                            lock_reasons.setdefault(wiz_line, set()).add(f'excl:{rule.name}')

            elif rule.rule_type == 'inclusion':
                # INCLUSIÓN: Los non-triggers empiezan bloqueados.
                # Se desbloquean solo si un trigger del grupo está seleccionado.
                trigger_selected = any(t.selected for t in state['triggers'])
                if not trigger_selected:
                    for wiz_line in state['non_triggers']:
                        lock_reasons.setdefault(wiz_line, set()).add(f'incl:{rule.name}')

        # --- Paso 3: Aplicar estado de bloqueo ---
        for wiz_line in self.accessory_selection_ids:
            reasons = lock_reasons.get(wiz_line, set())
            wiz_line.is_locked = bool(reasons)
            wiz_line.is_inclusion_locked = any(r.startswith('incl:') for r in reasons)

    def action_confirm_config(self):
        if not self.sale_order_id:
            active_id = (
                self.env.context.get('default_sale_order_id') or 
                self.env.context.get('params', {}).get('id')
            )
            if active_id:
                self.sale_order_id = active_id
            else:
                raise ValidationError("No se puede completar la operación porque el identificador de la orden de venta (sale_order_id) está vacío. Por favor, guarde la cotización antes de configurar la sembradora.")

        accesorios_seleccionados = self.accessory_selection_ids.filtered(lambda a: a.selected)

        # Validar reglas de exclusión: no puede haber >1 seleccionado por grupo
        exclusion_check = {}  # {rule_id: [acc_names]}
        for acc in accesorios_seleccionados:
            for rule in acc.rule_ids:
                if rule.rule_type == 'exclusion':
                    exclusion_check.setdefault(rule.id, []).append((rule.name, acc.product_id.name))

        for rule_id, entries in exclusion_check.items():
            if len(entries) > 1:
                rule_name = entries[0][0]
                acc_names = ', '.join(e[1] for e in entries)
                raise ValidationError(
                    f"Configuración inválida: Ha seleccionado más de un accesorio "
                    f"del grupo de exclusión '{rule_name}': {acc_names}. "
                    f"Verifique su selección."
                )
        
        valores_seleccionados = self.line_ids.mapped('value_id')

        template_attribute_values = self.env['product.template.attribute.value'].search([
            ('product_tmpl_id', '=', self.modelo_id.id),
            ('product_attribute_value_id', 'in', valores_seleccionados.ids)
        ])

        variant = self.env['product.product'].search([
            ('product_tmpl_id', '=', self.modelo_id.id),
            ('product_template_attribute_value_ids', 'in', template_attribute_values.ids)
        ]).filtered(lambda p: set(p.product_template_attribute_value_ids.ids) == set(template_attribute_values.ids))

        config = self.env['sembradora.config.rel'].search([
            ('modelo_id', '=', self.modelo_id.id),
            ('value_ids', 'in', valores_seleccionados.ids)
        ]).filtered(lambda c: set(c.value_ids.ids) == set(valores_seleccionados.ids))        
        
        if not config:
            raise ValidationError("No existe una configuración de precio definida para esta combinación.")

        if variant:
            if variant.list_price != config.price:
                variant.write({'list_price': config.price})
        else:
            template_attribute_values = self.env['product.template.attribute.value'].search([
                ('product_tmpl_id', '=', self.modelo_id.id),
                ('product_attribute_value_id', 'in', valores_seleccionados.ids)
            ])

            variant = self.env['product.product'].create({
                'product_tmpl_id': self.modelo_id.id,
                'product_template_attribute_value_ids': [(6, 0, template_attribute_values.ids)],
                'list_price': config.price
            })

        detalle_variante = f"{self.modelo_id.name}"
        lineas_detalle = []
        for line in self.line_ids:
            if line.attribute_id and line.value_id and line.show_in_description:
                lineas_detalle.append(f"• {line.attribute_id.name}: {line.value_id.name}")
        if lineas_detalle:
            detalle_variante += "\n" + "\n".join(lineas_detalle)

        tax_105 = self.env['account.tax'].search([
            ('type_tax_use', '=', 'sale'),
            ('amount', '=', 10.5)
        ], limit=1)
        tax_commands = [(6, 0, [tax_105.id])] if tax_105 else False

        self.env['sale.order.line'].create({
            'order_id': self.sale_order_id.id,
            'name': 'Variante de Configuracion',
            'display_type': 'line_section',
        })

        # Cremos la línea de la variante inyectando su precio real
        self.env['sale.order.line'].create({
            'order_id': self.sale_order_id.id,
            'product_id': variant.id,
            'product_uom_qty': 1,
            'name': detalle_variante,
            'price_unit': config.price,  # <--- DESCOMENTADO: Clave para que no sea 0.0
            'tax_ids': tax_commands,
        })

        if accesorios_seleccionados:
            self.env['sale.order.line'].create({
                'order_id': self.sale_order_id.id,
                'name': 'Accesorios',
                'display_type': 'line_section',
            })

            for acc_sel in accesorios_seleccionados:
                # Tomamos los datos directamente procesados por el wizard
                cantidad_final = acc_sel.quantity
                precio_unitario_final = acc_sel.price_unit

                _logger.info("Enviando a cotización - Producto: %s | Cantidad: %s | Unitario: %s", 
                             acc_sel.product_id.name, cantidad_final, precio_unitario_final)

                self.env['sale.order.line'].create({
                    'order_id': self.sale_order_id.id,
                    'product_id': acc_sel.product_id.id,
                    'product_uom_qty': cantidad_final,
                    'price_unit': precio_unitario_final,  # <--- AGREGADO: Pasa el unitario calculado
                    'tax_ids': tax_commands,
                })

        return {'type': 'ir.actions.act_window_close'}