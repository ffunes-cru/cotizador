from odoo import models, fields, api
import logging
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

        # --- GENERACIÓN DE LA SIGUIENTE FILA / FINALIZACIÓN ---
        lineas_vivas = self.line_ids.filtered(lambda l: not isinstance(l, tuple) or l[0] != 2)
        if lineas_vivas:
            ultima = lineas_vivas[-1]
            if ultima.value_id:
                configs_restantes = self.env['sembradora.config.rel'].search(dominio_acumulado)
                attrs_actuales = lineas_vivas.mapped('attribute_id')
                attrs_posibles = configs_restantes.mapped('value_ids.attribute_id')
                proximos = attrs_posibles - attrs_actuales
                
                if proximos:
                    # Todavía hay atributos: creamos la siguiente fila
                    self.line_ids = [(0, 0, {'attribute_id': proximos[0].id})]
                else:
                    # ¡NO HAY MÁS ATRIBUTOS! La configuración está completa
                    self.config_finalizada = True
                    
                    # Ahora sí, cargamos los accesorios permitidos
                    accesorios_posibles = configs_restantes.mapped('accesories_id')
                    self.allowed_accessory_ids = accesorios_posibles

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

        # 4. CRITICAL: Si no existe, la creamos dinámicamente
        if not variant:
            # Odoo crea la variante automáticamente al llamar a este método 
            # si la configuración de la plantilla es "Dynamic" o "Instantly"
            variant = self.modelo_id._create_variant_ids()
            
            # Si el método estándar no la encuentra/crea por restricciones, 
            # forzamos la creación del registro (Solo si el producto es Dinámico)
            variant = self.env['product.product'].create({
                'product_tmpl_id': self.modelo_id.id,
                'product_template_attribute_value_ids': [(6, 0, template_attribute_values.ids)]
            })

        # 5. Insertar en la orden de venta
        self.env['sale.order.line'].create({
            'order_id': self.sale_order_id.id,
            'product_id': variant.id,
            'product_uom_qty': 1,
        })

        for acc_id in self.accesories_id:
            self.env['sale.order.line'].create({
                'order_id': self.sale_order_id.id,
                'product_id': acc_id.id,
                'product_uom_qty': 1,
            })

        return {'type': 'ir.actions.act_window_close'}