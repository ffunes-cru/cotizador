# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging
import re

_logger = logging.getLogger(__name__)


class CotizadorConfiguratorService(models.AbstractModel):
    _name = 'cotizador.configurator.service'
    _description = 'Servicio RPC para el Configurador Visual de Sembradoras'

    @api.model
    def get_initial_data(self, order_id):
        """Retorna información de la orden de venta y catálogo de modelos disponibles."""
        order = self.env['sale.order'].browse(order_id)
        if not order.exists():
            raise UserError(_("La cotización solicitada no existe o no se pudo encontrar."))

        cat_maquina = self.env['product.category'].search([('name', '=', 'Maquina')], limit=1)
        domain = [('categ_id', '=', cat_maquina.id)] if cat_maquina else []
        templates = self.env['product.template'].search(domain, order='name asc')

        # Conteo de configuraciones por modelo
        configs = self.env['sembradora.config.rel'].read_group(
            domain=[('modelo_id', 'in', templates.ids)],
            fields=['modelo_id'],
            groupby=['modelo_id']
        )
        config_count_by_model = {c['modelo_id'][0]: c['modelo_id_count'] for c in configs}

        models_data = []
        for t in templates:
            models_data.append({
                'id': t.id,
                'name': t.name,
                'default_code': t.default_code or '',
                'config_count': config_count_by_model.get(t.id, 0),
                'description': t.description_sale or '',
                'has_image': bool(t.image_128),
                'image_url': f'/web/image/product.template/{t.id}/image_512' if t.image_128 else False,
            })

        modo_silencioso = self.env['ir.config_parameter'].sudo().get_param(
            'cotizador.modo_silencioso', default='False'
        ) == 'True'

        return {
            'order': {
                'id': order.id,
                'name': order.name,
                'partner_id': order.partner_id.id if order.partner_id else False,
                'partner_name': order.partner_id.name if order.partner_id else '',
                'state': order.state,
            },
            'models': models_data,
            'modo_silencioso': modo_silencioso,
        }

    @api.model
    def get_model_matrix(self, modelo_id):
        """
        Retorna la matriz completa de configuraciones y atributos para un modelo.
        Permite que el cliente OWL navegue y filtre la matriz en memoria a 0ms de latencia.
        """
        modelo = self.env['product.template'].browse(modelo_id)
        if not modelo.exists():
            raise UserError(_("El modelo seleccionado no existe."))

        configs = self.env['sembradora.config.rel'].search([
            ('modelo_id', '=', modelo_id)
        ], order='id asc')

        if not configs:
            return {
                'model': {
                    'id': modelo.id,
                    'name': modelo.name,
                    'default_code': modelo.default_code or '',
                },
                'attributes': [],
                'configs': [],
            }

        # Recolectar atributos involucrados
        all_val_ids = set()
        for cfg in configs:
            for v in cfg.value_ids:
                all_val_ids.add(v.id)

        values = self.env['product.attribute.value'].browse(list(all_val_ids))
        attr_ids = values.mapped('attribute_id')

        # Ordenar atributos según la secuencia definida en las líneas de atributo del template del modelo
        model_attr_order = {
            line.attribute_id.id: i
            for i, line in enumerate(modelo.attribute_line_ids.sorted('sequence'))
        }
        sorted_attrs = sorted(
            attr_ids,
            key=lambda a: (model_attr_order.get(a.id, 999), a.sequence or 999, a.id)
        )

        attributes_data = []
        for attr in sorted_attrs:
            attr_values = values.filtered(lambda v: v.attribute_id.id == attr.id).sorted('sequence')
            attributes_data.append({
                'id': attr.id,
                'name': attr.name,
                'show_in_description': getattr(attr, 'show_in_description', True),
                'show_incompatible_alternatives': getattr(attr, 'show_incompatible_alternatives', True),
                'values': [{
                    'id': v.id,
                    'name': v.name,
                } for v in attr_values]
            })

        # Mapear configuraciones válidas
        configs_data = [{
            'id': c.id,
            'value_ids': c.value_ids.ids,
            'price': c.price or 0.0,
            'description': c.description or '',
        } for c in configs]

        return {
            'model': {
                'id': modelo.id,
                'name': modelo.name,
                'default_code': modelo.default_code or '',
                'has_image': bool(modelo.image_128),
                'image_url': f'/web/image/product.template/{modelo.id}/image_512' if modelo.image_128 else False,
            },
            'attributes': attributes_data,
            'configs': configs_data,
        }

    def _extraer_factor(self, value_names, keywords):
        """Extrae el primer número encontrado en los valores cuyos atributos coinciden con keywords."""
        for vname in value_names:
            numeros = re.findall(r'\d+\.?\d*', vname)
            if numeros:
                try:
                    return float(numeros[0])
                except (ValueError, TypeError):
                    pass
        return 1.0

    @api.model
    def get_config_accessories(self, config_id):
        """
        Retorna la lista de accesorios compatibles para la configuración seleccionada,
        con cantidades dinámicas y precios calculados según las reglas comerciales.
        """
        config = self.env['sembradora.config.rel'].browse(config_id)
        if not config.exists():
            raise UserError(_("La configuración seleccionada no existe."))

        acc_lines = config.accessory_line_ids
        cat_lineas = self.env.ref('cotizador.cat_accesorio_cantidad_lineas', raise_if_not_found=False)
        cat_distancia = self.env.ref('cotizador.cat_accesorio_distancia_lineas', raise_if_not_found=False)
        cat_por_maquina = self.env.ref('cotizador.cat_accesorio_por_maquina', raise_if_not_found=False)

        # Mapeo de valores de atributos de esta configuración
        attr_val_map = {
            v.attribute_id.name.strip().lower(): v.name
            for v in config.value_ids
        }

        # Extraer factores dinámicos
        def get_factor_by_names(names):
            for name in names:
                if name in attr_val_map:
                    nums = re.findall(r'\d+\.?\d*', attr_val_map[name])
                    if nums:
                        return float(nums[0])
            return 1.0

        def get_int_factor(attr_name):
            val = attr_val_map.get(attr_name.strip().lower(), '')
            nums = re.findall(r'\d+', val)
            return int(nums[0]) if nums else 1

        factor_lineas = get_factor_by_names([
            'cantidad de líneas', 'cantidad de lineas', 'cantidad lineas', 'cantidad de líneas:'
        ])
        factor_distancia = get_factor_by_names([
            'distancia entre líneas', 'distancia entre lineas', 'distancia de lineas', 'espaciamiento'
        ])
        factor_keeton = get_int_factor('Keeton')
        factor_cuerpos = get_int_factor('Cuerpos')

        accessories_data = []
        for acc_line in acc_lines:
            prod = acc_line.product_id
            cat = prod.categ_id

            # Si la línea tiene cantidad explícita configurada > 0, se prioriza
            if acc_line.quantity and acc_line.quantity > 0:
                cantidad = acc_line.quantity
                precio_unitario = acc_line.price or prod.list_price
            elif cat_lineas and cat == cat_lineas:
                precio_unitario = prod.list_price
                cantidad = factor_lineas
            elif cat_distancia and cat == cat_distancia:
                precio_unitario = prod.list_price
                cantidad = factor_distancia
            elif cat_por_maquina and cat == cat_por_maquina:
                precio_unitario = prod.list_price
                cantidad = 1.0
            elif cat.id == 9:  # Ruedas / Keeton
                precio_unitario = acc_line.price
                cantidad = factor_keeton
            elif cat.id == 8:  # Cuerpos
                precio_unitario = acc_line.price
                cantidad = factor_cuerpos
            else:
                precio_unitario = acc_line.price if acc_line.price else prod.list_price
                cantidad = 1.0

            # Reglas de exclusión/inclusión
            rules_data = []
            is_inclusion_locked = False
            for rule in acc_line.rule_ids:
                rules_data.append({
                    'id': rule.id,
                    'name': rule.name,
                    'rule_type': rule.rule_type,
                })
                if rule.rule_type == 'inclusion' and not acc_line.is_trigger:
                    is_inclusion_locked = True

            subtotal = round(precio_unitario * cantidad, 2)
            accessories_data.append({
                'line_id': acc_line.id,
                'product_id': prod.id,
                'product_name': prod.name,
                'default_code': prod.default_code or '',
                'category_id': cat.id if cat else False,
                'category_name': cat.name if cat else _('Otros Accesorios'),
                'has_image': bool(prod.image_128),
                'image_url': f'/web/image/product.product/{prod.id}/image_128' if prod.image_128 else False,
                'price_unit': round(precio_unitario, 2),
                'quantity': cantidad,
                'subtotal': subtotal,
                'is_trigger': bool(acc_line.is_trigger),
                'rules': rules_data,
                'is_locked': is_inclusion_locked,
                'is_inclusion_locked': is_inclusion_locked,
                'selected': False,
            })

        return {
            'config_id': config.id,
            'base_price': config.price or 0.0,
            'description': config.description or '',
            'accessories': accessories_data,
        }

    @api.model
    def confirm_configuration(self, order_id, config_id, selected_accessories=None):
        """
        Confirma la selección y crea en la orden de venta:
        1. La variante de producto configurada en la sección 'Variante de Configuracion'.
        2. Los accesorios seleccionados en la sección 'Accesorios'.
        """
        if selected_accessories is None:
            selected_accessories = []

        order = self.env['sale.order'].browse(order_id)
        if not order.exists():
            raise UserError(_("La orden de venta #%s no existe.") % order_id)

        config = self.env['sembradora.config.rel'].browse(config_id)
        if not config.exists():
            raise UserError(_("La configuración seleccionada no existe."))

        modelo = config.modelo_id
        valores_seleccionados = config.value_ids

        # 1. Buscar o crear la variante product.product exacta
        domain = [('product_tmpl_id', '=', modelo.id)]
        for val in valores_seleccionados:
            domain.append(('product_template_attribute_value_ids.product_attribute_value_id', '=', val.id))

        variant = self.env['product.product'].search(domain, limit=1)
        if not variant:
            template_attribute_values = self.env['product.template.attribute.value'].search([
                ('product_tmpl_id', '=', modelo.id),
                ('product_attribute_value_id', 'in', valores_seleccionados.ids)
            ])
            variant = self.env['product.product'].create({
                'product_tmpl_id': modelo.id,
                'product_template_attribute_value_ids': [(6, 0, template_attribute_values.ids)],
                'list_price': config.price,
            })

        # Construir descripción de la máquina
        detalle_variante = f"{modelo.name}"
        lineas_detalle = []
        for val in valores_seleccionados:
            attr = val.attribute_id
            show = getattr(attr, 'show_in_description', True)
            if show:
                lineas_detalle.append(f"• {attr.name}: {val.name}")
        if lineas_detalle:
            detalle_variante += "\n" + "\n".join(lineas_detalle)

        # Impuesto IVA 10.5% (estándar para maquinaria agrícola en Argentina)
        tax_105 = self.env['account.tax'].search([
            ('type_tax_use', '=', 'sale'),
            ('amount', '=', 10.5)
        ], limit=1)
        tax_commands = [(6, 0, [tax_105.id])] if tax_105 else False

        # 2. Crear sección 'Variante de Configuracion'
        order.env['sale.order.line'].create({
            'order_id': order.id,
            'name': 'Variante de Configuracion',
            'display_type': 'line_section',
        })

        # 3. Crear línea de la máquina con su precio base
        order.env['sale.order.line'].create({
            'order_id': order.id,
            'product_id': variant.id,
            'product_uom_qty': 1.0,
            'name': detalle_variante,
            'price_unit': config.price or 0.0,
            'tax_ids': tax_commands,
        })

        # 4. Crear sección y líneas de accesorios seleccionados si existen
        if selected_accessories:
            order.env['sale.order.line'].create({
                'order_id': order.id,
                'name': 'Accesorios',
                'display_type': 'line_section',
            })

            for acc in selected_accessories:
                prod_id = acc.get('product_id')
                qty = float(acc.get('quantity', 1.0))
                price_u = float(acc.get('price_unit', 0.0))
                order.env['sale.order.line'].create({
                    'order_id': order.id,
                    'product_id': prod_id,
                    'product_uom_qty': qty,
                    'price_unit': price_u,
                    'tax_ids': tax_commands,
                })

        # Sincronización automática de CRM
        if order.opportunity_id:
            order.opportunity_id._sync_expected_revenue_from_orders()

        return {
            'success': True,
            'order_id': order.id,
            'order_name': order.name,
        }

