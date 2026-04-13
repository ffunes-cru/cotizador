from odoo import models, fields, api
import logging
import re
_logger = logging.getLogger(__name__)

class SembradoraConfigWizard(models.TransientModel):
    _name = 'sembradora.config.wizard'
    _description = 'Configurador Dinámico'

    sale_order_id = fields.Many2one('sale.order', string='Venta')
    modelo_id = fields.Many2one('product.template', string='Modelo', domain=[("categ_id", "in", [6, 7])])

    # Aquí se generarán las filas dinámicas
    line_ids = fields.One2many('sembradora.config.wizard.line', 'wizard_id', string='Atributos')

    # Agregamos nombres de tabla manuales para evitar la colisión
    accesories_id = fields.Many2many(
        'product.product', 
        'wizard_accessories_rel', # Nombre de la tabla 1
        'wizard_id', 'product_id', # Columnas
        string='Accesorios Seleccionados'
    )

    allowed_accessory_ids = fields.Many2many(
        'product.product', 
        'wizard_allowed_accessories_rel', # Nombre de la tabla 2 (DIFERENTE)
        'wizard_id', 'product_id',        # Columnas
        string='Accesorios Permitidos'
    )

    config_finalizada = fields.Boolean(string="¿Configuración Completa?", default=False)

    @api.onchange('modelo_id', 'line_ids')
    def _onchange_configuracion_secuencial(self):
        if not self.modelo_id:
            self.line_ids = [(5, 0, 0)]
            return

        # 1. Caso inicial: Sin líneas
        if not self.line_ids:
            configs = self.env['sembradora.config.rel'].search([('modelo_id', '=', self.modelo_id.id)])
            primer_attr = configs.mapped('value_ids.attribute_id')
            if primer_attr:
                self.line_ids = [(0, 0, {'attribute_id': primer_attr[0].id})]
            return

        # --- LÓGICA DE VALIDACIÓN DE CADENA ---
        nuevos_comandos = []
        # Empezamos con el dominio base del modelo
        dominio_acumulado = [('modelo_id', '=', self.modelo_id.id)]
        
        cortar = False
        for line in self.line_ids:
            if cortar:
                # Si ya marcamos corte, eliminamos lo que siga
                nuevos_comandos.append((2, line.id.origin or line.id))
                continue

            # Verificamos si el valor de ESTA línea es compatible con las ANTERIORES
            if line.value_id:
                # Buscamos en la matriz si existe una config que tenga este valor 
                # Y TAMBIÉN todos los valores que ya aceptamos de las filas de arriba
                check_dominio = dominio_acumulado + [('value_ids', 'in', line.value_id.id)]
                existe = self.env['sembradora.config.rel'].search_count(check_dominio)
                
                if existe > 0:
                    # Es válido: lo mantenemos y actualizamos el dominio para la fila de abajo
                    nuevos_comandos.append((4, line.id.origin or line.id))
                    dominio_acumulado.append(('value_ids', 'in', line.value_id.id))
                else:
                    # El usuario cambió algo arriba y esta fila ya no coincide con la matriz
                    nuevos_comandos.append((2, line.id.origin or line.id))
                    cortar = True
            else:
                # Fila vacía: la mantenemos pero cortamos la generación de las de abajo
                nuevos_comandos.append((4, line.id.origin or line.id))
                cortar = True

        # Aplicamos los cambios de la poda
        self.line_ids = nuevos_comandos

        # 1. Buscamos las configs válidas según lo que hay en pantalla
        configs_validas = self.env['sembradora.config.rel'].search(dominio_acumulado)
        
        # 2. Obtenemos los accesorios de esas configs
        accesorios_posibles = configs_validas.mapped('accesories_id')
        
        # 3. LO CLAVE: Llenamos el campo técnico
        self.allowed_accessory_ids = accesorios_posibles

        # 4. Limpieza: Si ya eligió algo que ahora no es compatible, lo sacamos
        if self.accesories_id:
            self.accesories_id = self.accesories_id.filtered(lambda a: a.id in accesorios_posibles.ids)

        # Por defecto, asumimos que no terminó
        self.config_finalizada = False

# --- GENERACIÓN AUTOMÁTICA Y SALTO DE FILAS ÚNICAS ---
        while True:
            # 1. Ver qué tenemos en pantalla ahora mismo
            # Filtramos para ignorar las líneas que acabamos de marcar para borrar (comando 2)
            lineas_vivas = self.line_ids.filtered(lambda l: not isinstance(l, tuple) or l[0] != 2)
            
            if not lineas_vivas:
                break
                
            ultima = lineas_vivas[-1]
            
            # Si la última línea aún no tiene valor, no podemos avanzar a la siguiente
            if not ultima.value_id:
                break
            
            # 2. Buscar qué atributos faltan
            configs_restantes = self.env['sembradora.config.rel'].search(dominio_acumulado)
            attrs_actuales = lineas_vivas.mapped('attribute_id')
            attrs_posibles = configs_restantes.mapped('value_ids.attribute_id')
            proximos = attrs_posibles - attrs_actuales
            
            if not proximos:
                self.config_finalizada = True
                break
            
            # 3. Analizar el siguiente atributo
            siguiente_attr = proximos[0]
            # Buscamos qué valores de este atributo existen en las combinaciones que aún son válidas
            valores_disponibles = configs_restantes.mapped('value_ids').filtered(
                lambda v: v.attribute_id == siguiente_attr
            )
            
            # Preparar la nueva línea
            nueva_linea_vals = {'attribute_id': siguiente_attr.id}
            
            # --- EL TRUCO: Si solo hay uno, lo llenamos de una vez ---
            if len(valores_disponibles) == 1:
                val_unico = valores_disponibles[0]
                nueva_linea_vals['value_id'] = val_unico.id
                # Importante: actualizamos el dominio acumulado para que la 
                # siguiente vuelta del bucle sepa que este valor ya está "elegido"
                dominio_acumulado.append(('value_ids', 'in', val_unico.id))
                
                # Añadimos la línea y CONTINUAMOS el bucle para ver si la que sigue también es única
                self.line_ids = [(4, l.id.origin or l.id) for l in lineas_vivas] + [(0, 0, nueva_linea_vals)]
                continue 
            else:
                # Si hay múltiples opciones, creamos la línea vacía y PARAMOS (break)
                # El usuario debe elegir.
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
            raise models.ValidationError("No existe una configuración de precio definida para esta combinación.")

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

        # 3. Finalmente, creamos la línea de la orden de venta
        self.env['sale.order.line'].create({
            'order_id': self.sale_order_id.id,
            'product_id': variant.id,
            'product_uom_qty': 1,
            # Odoo tomará automáticamente el list_price de la variante si no pasamos 'price_unit'
        })

        self.env['sale.order.line'].create({
            'order_id': self.sale_order_id.id,
            'name': 'Accesorios',
            'display_type': 'line_section',   #lo convierte en separador
        })

        # 3. CREAMOS LOS ACCESORIOS CON CANTIDAD DINÁMICA
        for acc_id in self.accesories_id:
            cantidad_final = 1
            
            if acc_id.categ_id.id == 9:
                _logger.info("Entro a categoria Ruedas pero uso el campo Keeton")
                cantidad_final = self.get_acc_quan('Keeton')
            if acc_id.categ_id.id == 8:
                _logger.info("Entro a categoria Cuerpos")
                cantidad_final = self.get_acc_quan('Cuerpos')

            self.env['sale.order.line'].create({
                'order_id': self.sale_order_id.id,
                'product_id': acc_id.id,
                'product_uom_qty': cantidad_final,
            })

        return {'type': 'ir.actions.act_window_close'}