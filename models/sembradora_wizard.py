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

    def _poblar_accesorios(self, configs):
        """Método unificado para poblar accesorios desde un recordset de configs válidas."""
        acc_lines = configs.mapped('accessory_line_ids')
        acc_commands = [(5, 0, 0)]  # Limpiar todo primero
        for acc_line in acc_lines:
            acc_commands.append((0, 0, {
                'config_acc_line_id': acc_line.id,
                'selected': False,
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
            primer_attr = todas_configs.mapped('value_ids.attribute_id')
            if primer_attr:
                self.line_ids = [(0, 0, {'attribute_id': primer_attr[0].id})]
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
            
            # Restar usando conjuntos en lugar de objetos de Odoo (más rápido)
            proximos = [a for a in attrs_posibles if a not in attrs_actuales]
            
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

    def action_confirm_config(self):
        if not self.sale_order_id:
            # Fallback robusto en caso de que sale_order_id no venga persistido
            active_id = (
                self.env.context.get('default_sale_order_id') or 
                self.env.context.get('params', {}).get('id')
            )
            if active_id:
                self.sale_order_id = active_id
            else:
                raise ValidationError("No se puede completar la operación porque el identificador de la orden de venta (sale_order_id) está vacío. Por favor, guarde la cotización antes de configurar la sembradora.")

        # 1. Obtenemos los valores que el usuario seleccionó en las líneas del Wizard
        valores_seleccionados = self.line_ids.mapped('value_id')

        # 2. Obtener los 'Template Attribute Values' correspondientes
        # En Odoo, para crear una variante necesitas los IDs de la tabla intermedia 
        # que une el atributo con el producto específico.
        template_attribute_values = self.env['product.template.attribute.value'].search([
            ('product_tmpl_id', '=', self.modelo_id.id),
            ('product_attribute_value_id', 'in', valores_seleccionados.ids)
        ])

        # 3. Intentar buscar la variante existente
        variant = self.env['product.product'].search([
            ('product_tmpl_id', '=', self.modelo_id.id),
            ('product_template_attribute_value_ids', 'in', template_attribute_values.ids)
        ])
        
        # Filtrar para asegurar match exacto
        variant = variant.filtered(
            lambda p: set(p.product_template_attribute_value_ids.ids) == set(template_attribute_values.ids)
        )

        # 1. Buscamos la configuración exacta en la matriz
        # (Usamos filtered para asegurar que la combinación de valores sea idéntica)
        config = self.env['sembradora.config.rel'].search([
            ('modelo_id', '=', self.modelo_id.id),
            ('value_ids', 'in', valores_seleccionados.ids)
        ]).filtered(lambda c: set(c.value_ids.ids) == set(valores_seleccionados.ids))        
        _logger.info("Valor de config: %s", config.mapped("name"))
        
        if not config:
            raise ValidationError("No existe una configuración de precio definida para esta combinación.")

        _logger.info("Configuración encontrada: %s - Precio: %s", config.display_name, config.price)

        # 2. Lógica de Variantes (Actualizar o Crear)
        if variant:
            # SI LA VARIANTE YA EXISTE: Comparamos y actualizamos si el precio cambió en la matriz
            if variant.list_price != config.price:
                _logger.info("Actualizando precio de variante existente %s: %s -> %s", 
                             variant.display_name, variant.list_price, config.price)
                
                # .write() actualiza el registro en la base de datos
                variant.write({'list_price': config.price})
        else:
            # SI LA VARIANTE NO EXISTE: La creamos desde cero
            _logger.info("Variante no encontrada. Creando nueva variante para el modelo %s", self.modelo_id.name)
            
            # Obtenemos los IDs de la tabla intermedia necesarios para la creación
            template_attribute_values = self.env['product.template.attribute.value'].search([
                ('product_tmpl_id', '=', self.modelo_id.id),
                ('product_attribute_value_id', 'in', valores_seleccionados.ids)
            ])

            variant = self.env['product.product'].create({
                'product_tmpl_id': self.modelo_id.id,
                'product_template_attribute_value_ids': [(6, 0, template_attribute_values.ids)],
                'list_price': config.price  # Se asigna el precio de la matriz al crear
            })
            _logger.info("Variante creada exitosamente con ID %s y precio %s", variant.id, variant.list_price)

        # Construir descripción detallada de la variante seleccionada
        # Solo incluye atributos marcados con show_in_description en product.attribute
        detalle_variante = f"{self.modelo_id.name}"
        lineas_detalle = []
        for line in self.line_ids:
            if line.attribute_id and line.value_id and line.show_in_description:
                lineas_detalle.append(f"• {line.attribute_id.name}: {line.value_id.name}")
        if lineas_detalle:
            detalle_variante += "\n" + "\n".join(lineas_detalle)

        self.env['sale.order.line'].create({
            'order_id': self.sale_order_id.id,
            'name': 'Variante de Configuracion',
            'display_type': 'line_section',   #lo convierte en separador
        })

        # 3. Finalmente, creamos la línea de la orden de venta para la variante
        self.env['sale.order.line'].create({
            'order_id': self.sale_order_id.id,
            'product_id': variant.id,
            'product_uom_qty': 1,
            'name': detalle_variante,
            # Odoo tomará automáticamente el list_price de la variante si no pasamos 'price_unit'
        })

        # 4. CREAMOS LOS ACCESORIOS SELECCIONADOS
        accesorios_seleccionados = self.accessory_selection_ids.filtered(lambda a: a.selected)

        if accesorios_seleccionados:
            self.env['sale.order.line'].create({
                'order_id': self.sale_order_id.id,
                'name': 'Accesorios',
                'display_type': 'line_section',   #lo convierte en separador
            })

            for acc_sel in accesorios_seleccionados:
                # Determinar cantidad: si hay cantidad en la config, usarla; sino, lógica dinámica
                if acc_sel.config_quantity and acc_sel.config_quantity > 0:
                    cantidad_final = acc_sel.config_quantity
                else:
                    # Fallback: lógica dinámica por categoría
                    cantidad_final = 1
                    if acc_sel.product_id.categ_id.id == 9:
                        _logger.info("Entro a categoria Ruedas pero uso el campo Keeton")
                        cantidad_final = self.get_acc_quan('Keeton')
                    if acc_sel.product_id.categ_id.id == 8:
                        _logger.info("Entro a categoria Cuerpos")
                        cantidad_final = self.get_acc_quan('Cuerpos')

                self.env['sale.order.line'].create({
                    'order_id': self.sale_order_id.id,
                    'product_id': acc_sel.product_id.id,
                    'product_uom_qty': cantidad_final,
                    'price_unit': acc_sel.price,  # Precio de la tabla de accesorios por config
                })

        return {'type': 'ir.actions.act_window_close'}