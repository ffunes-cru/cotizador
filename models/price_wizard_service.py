from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class CotizadorPriceWizardService(models.AbstractModel):
    _name = 'cotizador.price.wizard.service'
    _description = 'Servicio RPC para Asistente de Modificación de Precios'

    @api.model
    def get_models(self):
        """Retorna todos los modelos de sembradoras (product.template en categoría 'Maquina')."""
        cat_maquina = self.env['product.category'].search([('name', '=', 'Maquina')], limit=1)
        domain = [('categ_id', '=', cat_maquina.id)] if cat_maquina else []
        templates = self.env['product.template'].search(domain, order='name asc')
        
        # Contar configs por modelo
        configs = self.env['sembradora.config.rel'].read_group(
            domain=[('modelo_id', 'in', templates.ids)],
            fields=['modelo_id'],
            groupby=['modelo_id']
        )
        config_count_by_model = {c['modelo_id'][0]: c['modelo_id_count'] for c in configs}
        
        return [{
            'id': t.id,
            'name': t.name,
            'default_code': t.default_code or '',
            'config_count': config_count_by_model.get(t.id, 0),
        } for t in templates]

    @api.model
    def get_base_configs_data(self, modelo_id):
        """
        Retorna las configuraciones base para un modelo dado, incluyendo
        la lista ordenada de atributos dinámicos con sus valores disponibles para filtros.
        """
        configs = self.env['sembradora.config.rel'].search([
            ('modelo_id', '=', modelo_id)
        ], order='id asc')

        if not configs:
            return {
                'attributes': [],
                'configs': [],
            }

        # Recolectar todos los atributos involucrados en orden
        all_attr_ids = set()
        attr_values_map = {}  # attr_id -> set of value names

        for cfg in configs:
            for v in cfg.value_ids:
                all_attr_ids.add(v.attribute_id.id)
                attr_values_map.setdefault(v.attribute_id.id, set()).add(v.name)
        
        attributes = self.env['product.attribute'].browse(list(all_attr_ids)).sorted(key=lambda a: a.sequence or 0)
        attr_list = [{
            'id': a.id,
            'name': a.name,
            'options': sorted(list(attr_values_map.get(a.id, set()))),
        } for a in attributes]

        configs_data = []
        for cfg in configs:
            val_by_attr = {}
            for v in cfg.value_ids:
                val_by_attr[v.attribute_id.id] = v.name

            row_values = []
            for attr in attributes:
                row_values.append({
                    'attr_id': attr.id,
                    'value': val_by_attr.get(attr.id, '-'),
                })

            configs_data.append({
                'id': cfg.id,
                'ext_id': cfg.ext_id or '',
                'name': cfg.name or '',
                'price': cfg.price or 0.0,
                'attr_values': val_by_attr,
                'row_values': row_values,
            })

        return {
            'attributes': attr_list,
            'configs': configs_data,
        }

    @api.model
    def save_base_prices(self, updates):
        """
        Guarda las actualizaciones de precios base.
        updates: [{ 'id': config_id, 'price': new_price }]
        """
        ConfigRel = self.env['sembradora.config.rel']
        updated_count = 0
        for item in updates:
            cfg = ConfigRel.browse(item['id'])
            if cfg.exists():
                new_price = float(item.get('price', 0.0))
                cfg.write({'price': new_price})
                updated_count += 1

        return {
            'success': True,
            'updated_count': updated_count,
        }

    @api.model
    def get_accessory_data(self, modelo_id):
        """
        Retorna los accesorios disponibles en las configuraciones de este modelo,
        clasificados en:
        - global_accessories: Accesorios con subcategoría (ej. Cantidad de Líneas, Distancia, etc.)
        - specific_accessories: Accesorios de categoría base pura "Accesorio" (precio por configuración).
        - attributes: Lista de atributos y opciones del modelo para poder filtrar también.
        """
        cat_base = self.env.ref('cotizador.cat_accesorio_base', raise_if_not_found=False)
        if not cat_base:
            cat_base = self.env['product.category'].search([('name', '=', 'Accesorio')], limit=1)

        # Buscar todas las configs y accessory lines del modelo
        configs = self.env['sembradora.config.rel'].search([('modelo_id', '=', modelo_id)], order='id asc')
        acc_lines = self.env['sembradora.config.accessory.line'].search([
            ('config_id', 'in', configs.ids)
        ])

        # Recolectar atributos de las configs
        all_attr_ids = set()
        attr_values_map = {}
        config_attr_map = {}  # config_id -> {attr_id: val_name}

        for cfg in configs:
            val_by_attr = {}
            for v in cfg.value_ids:
                all_attr_ids.add(v.attribute_id.id)
                attr_values_map.setdefault(v.attribute_id.id, set()).add(v.name)
                val_by_attr[v.attribute_id.id] = v.name
            config_attr_map[cfg.id] = val_by_attr

        attributes = self.env['product.attribute'].browse(list(all_attr_ids)).sorted(key=lambda a: a.sequence or 0)
        attr_list = [{
            'id': a.id,
            'name': a.name,
            'options': sorted(list(attr_values_map.get(a.id, set()))),
        } for a in attributes]

        # Agrupar productos
        products = acc_lines.mapped('product_id')

        global_acc_map = {}
        specific_acc_list = []

        for prod in products:
            is_subcat = False
            categ = prod.categ_id
            
            if cat_base and categ and categ.id != cat_base.id and categ.parent_id.id == cat_base.id:
                is_subcat = True

            prod_lines = acc_lines.filtered(lambda l: l.product_id.id == prod.id)
            configs_count = len(prod_lines)
            
            current_price = prod_lines[0].price if prod_lines else prod.list_price

            if is_subcat:
                if prod.id not in global_acc_map:
                    global_acc_map[prod.id] = {
                        'product_id': prod.id,
                        'product_name': prod.name,
                        'default_code': prod.default_code or '',
                        'category_name': categ.name,
                        'price': current_price,
                        'configs_count': configs_count,
                    }
            else:
                for line in prod_lines:
                    specific_acc_list.append({
                        'line_id': line.id,
                        'config_id': line.config_id.id,
                        'config_name': line.config_id.name,
                        'product_id': prod.id,
                        'product_name': prod.name,
                        'default_code': prod.default_code or '',
                        'category_name': categ.name if categ else 'Accesorio',
                        'price': line.price,
                        'attr_values': config_attr_map.get(line.config_id.id, {}),
                    })

        return {
            'attributes': attr_list,
            'global_accessories': list(global_acc_map.values()),
            'specific_accessories': specific_acc_list,
        }

    @api.model
    def save_global_accessory_prices(self, modelo_id, updates):
        """
        Actualiza el precio de un accesorio con subcategoría para TODAS las
        configuraciones de ese modelo y actualiza el list_price del producto.
        updates: [{ 'product_id': prod_id, 'price': new_price }]
        """
        configs = self.env['sembradora.config.rel'].search([('modelo_id', '=', modelo_id)])
        AccLine = self.env['sembradora.config.accessory.line']
        Product = self.env['product.product']

        updated_configs_count = 0
        for item in updates:
            prod_id = item['product_id']
            new_price = float(item.get('price', 0.0))
            
            prod = Product.browse(prod_id)
            if prod.exists():
                prod.write({'list_price': new_price})

            lines = AccLine.search([
                ('config_id', 'in', configs.ids),
                ('product_id', '=', prod_id),
            ])
            if lines:
                lines.write({'price': new_price})
                updated_configs_count += len(lines)

        return {
            'success': True,
            'updated_count': len(updates),
            'updated_lines_count': updated_configs_count,
        }

    @api.model
    def save_specific_accessory_prices(self, updates):
        """
        Actualiza precios de accesorios específicos por configuración.
        updates: [{ 'line_id': acc_line_id, 'price': new_price }]
        """
        AccLine = self.env['sembradora.config.accessory.line']
        updated_count = 0
        for item in updates:
            line = AccLine.browse(item['line_id'])
            if line.exists():
                new_price = float(item.get('price', 0.0))
                line.write({'price': new_price})
                updated_count += 1

        return {
            'success': True,
            'updated_count': updated_count,
        }
