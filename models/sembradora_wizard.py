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
        '''
        Va agregando de forma secuencial, los distintos valores de atributo posibles para las configuraciones dadas.
        
        OPTIMIZADO: Una sola query al inicio, luego filtrado en memoria con .filtered()
        '''
        if not self.modelo_id:
            self.line_ids = [(5, 0, 0)]
            self.accessory_selection_ids = [(5, 0, 0)]
            self.config_base_price = 0
            return

        # === QUERY ÚNICA: Traemos TODAS las configs de este modelo una sola vez ===
        todas_configs = self.env['sembradora.config.rel'].search([
            ('modelo_id', '=', self.modelo_id.id)
        ])

        # 1. Caso inicial: Sin líneas
        if not self.line_ids:
            primer_attr = todas_configs.mapped('value_ids.attribute_id')
            if primer_attr:
                _logger.debug("Se añade el primer atributo %s", primer_attr[0].name)
                self.line_ids = [(0, 0, {'attribute_id': primer_attr[0].id})]
            return
        
        nuevos_comandos = []
        # Dominio acumulado: set de value_ids seleccionados (para filtrar en memoria)
        valores_seleccionados_ids = []

        cortar = False
        for line in self.line_ids:
            if cortar:
                nuevos_comandos.append((2, line.id.origin or line.id))
                continue

            if line.value_id:
                # OPTIMIZACIÓN: Filtrado en memoria en vez de search_count
                check_ids = valores_seleccionados_ids + [line.value_id.id]
                existe = todas_configs.filtered(
                    lambda c, ids=check_ids: all(vid in c.value_ids.ids for vid in ids)
                )
                
                if existe:
                    nuevos_comandos.append((4, line.id.origin or line.id))
                    valores_seleccionados_ids.append(line.value_id.id)
                else:
                    nuevos_comandos.append((2, line.id.origin or line.id))
                    cortar = True
            else:
                # fila vacía
                nuevos_comandos.append((4, line.id.origin or line.id))
                cortar = True

        self.line_ids = nuevos_comandos

        # Filtrar configs válidas en memoria con los valores acumulados
        configs_validas = todas_configs.filtered(
            lambda c: all(vid in c.value_ids.ids for vid in valores_seleccionados_ids)
        )

        # Poblar accesorios y precio base
        # self._poblar_accesorios(configs_validas)
        if len(configs_validas) == 1:
            self.config_base_price = configs_validas.price
        else:
            self.config_base_price = 0

        self.config_finalizada = False

        # --- GENERACIÓN AUTOMÁTICA Y SALTO DE FILAS ÚNICAS ---
        while True:
            lineas_vivas = self.line_ids.filtered(lambda l: not isinstance(l, tuple) or l[0] != 2)

            if not lineas_vivas:
                break
                
            ultima = lineas_vivas[-1]
            
            if not ultima.value_id:
                break

            # OPTIMIZACIÓN: Filtrado en memoria (no más search)
            configs_restantes = configs_validas  # Ya filtradas arriba
            attrs_actuales = lineas_vivas.mapped('attribute_id')
            attrs_posibles = configs_restantes.mapped('value_ids.attribute_id')
            proximos = attrs_posibles - attrs_actuales
            
            if not proximos:
                self.config_finalizada = True

                # Configuración completa: actualizar precio base y accesorios
                if len(configs_restantes) == 1:
                    self.config_base_price = configs_restantes.price
                    self._poblar_accesorios(configs_restantes)

                break

            # Analizar el siguiente atributo
            siguiente_attr = proximos[0]
            valores_disponibles = configs_restantes.mapped('value_ids').filtered(
                lambda v: v.attribute_id == siguiente_attr
            )
            
            nueva_linea_vals = {'attribute_id': siguiente_attr.id}
            
            # Si solo hay un valor posible, lo seleccionamos automáticamente
            if len(valores_disponibles) == 1:
                val_unico = valores_disponibles[0]
                nueva_linea_vals['value_id'] = val_unico.id
                nueva_linea_vals['is_single_option'] = True  # Marcar como auto-seleccionado
                valores_seleccionados_ids.append(val_unico.id)
                
                # Refiltrar configs_validas con el nuevo valor
                configs_validas = configs_validas.filtered(
                    lambda c, vid=val_unico.id: vid in c.value_ids.ids
                )
                configs_restantes = configs_validas
                
                self.line_ids = [(4, l.id.origin or l.id) for l in lineas_vivas] + [(0, 0, nueva_linea_vals)]
                continue 
            else:
                # Múltiples opciones: el usuario debe elegir
                self.line_ids = [(4, l.id.origin or l.id) for l in lineas_vivas] + [(0, 0, nueva_linea_vals)]
                break

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