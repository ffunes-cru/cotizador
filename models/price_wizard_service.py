"""@file
Servicio RPC del Asistente de Precios (componente OWL `cotizador_price_wizard`).

Edición masiva de precios de la matriz de un modelo, en tres vistas:
- **precios base**: el precio de cada configuración;
- **accesorios globales**: accesorios de una subcategoría de *Accesorio* (los de cantidad por
  atributo); su precio se aplica a todas las configuraciones del modelo;
- **accesorios específicos**: el resto; precio por configuración (agrupable por atributos).

Los precios se escriben en la matriz, en la Moneda del Cotizador de cada producto; nunca en
el precio de venta del producto. Solo para el grupo Administrador del Configurador.
"""
from odoo import api, models

from .sembradora_config import check_configurator_manager


class CotizadorPriceWizardService(models.AbstractModel):
    """Servicio `cotizador.price.wizard.service` (sin tabla)."""
    _name = 'cotizador.price.wizard.service'
    _description = 'Servicio RPC para Asistente de Modificación de Precios'

    @api.model
    def get_models(self):
        """Máquinas para elegir en el asistente.

        @return Lista de dicts `{id, name, default_code, currency, config_count}`.
        @throws AccessError Si el usuario no es administrador del configurador.
        """
        check_configurator_manager(self.env)
        templates = self.env['product.template'].search([('is_maquina', '=', True)], order='name asc')
        
        config_count_by_model = {
            modelo.id: count for modelo, count in self.env['sembradora.config.rel']._read_group(
                [('modelo_id', 'in', templates.ids)], ['modelo_id'], ['__count'],
            )
        }

        return [{
            'id': t.id,
            'name': t.name,
            'default_code': t.default_code or '',
            'currency': t.cotizador_currency_id.name,
            'config_count': config_count_by_model.get(t.id, 0),
        } for t in templates]

    @api.model
    def get_base_configs_data(self, modelo_id):
        """Configuraciones de un modelo con sus precios, y los atributos para filtrar.

        @param modelo_id Id de la máquina.
        @return dict `{attributes: [{id, name, options}], configs: [{id, ext_id, name, price,
                attr_values, row_values}]}`.
        @throws AccessError Si el usuario no es administrador del configurador.
        """
        check_configurator_manager(self.env)
        configs = self.env['sembradora.config.rel'].search([
            ('modelo_id', '=', modelo_id)
        ], order='id asc')

        if not configs:
            return {
                'attributes': [],
                'configs': [],
            }

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
        """Guarda precios de configuraciones.

        @param updates Lista de dicts `{'id': id de configuración, 'price': nuevo precio}`.
        @return dict `{success, updated_count}`.
        @throws AccessError Si el usuario no es administrador del configurador.
        """
        check_configurator_manager(self.env)
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
        """Accesorios de las configuraciones de un modelo, separados en globales y específicos.

        Un accesorio es *global* si su categoría es hija directa de *Accesorio* (las categorías
        de cantidad que crea el importador); el resto es *específico*.

        @param modelo_id Id de la máquina.
        @return dict `{attributes, global_accessories: [{product_id, product_name, default_code,
                category_name, currency, price, configs_count}], specific_accessories:
                [{line_id, config_id, config_name, product_id, product_name, default_code,
                category_name, currency, price, attr_values}]}`. El precio de un global es el
                de su primera línea.
        @throws AccessError Si el usuario no es administrador del configurador.
        """
        check_configurator_manager(self.env)
        cat_base = self.env.ref('cotizador.cat_accesorio_base')

        configs = self.env['sembradora.config.rel'].search([('modelo_id', '=', modelo_id)], order='id asc')
        acc_lines = self.env['sembradora.config.accessory.line'].search([
            ('config_id', 'in', configs.ids)
        ])

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
            
            current_price = prod_lines[0].price

            if is_subcat:
                if prod.id not in global_acc_map:
                    global_acc_map[prod.id] = {
                        'product_id': prod.id,
                        'product_name': prod.name,
                        'default_code': prod.default_code or '',
                        'category_name': categ.name,
                        'currency': prod.cotizador_currency_id.name,
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
                        'currency': prod.cotizador_currency_id.name,
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
        """Fija el precio de accesorios globales en todas las configuraciones del modelo.

        @param modelo_id Id de la máquina.
        @param updates Lista de dicts `{'product_id': id del accesorio, 'price': nuevo precio}`.
        @return dict `{success, updated_count, updated_lines_count}`.
        @throws AccessError Si el usuario no es administrador del configurador.
        """
        check_configurator_manager(self.env)
        configs = self.env['sembradora.config.rel'].search([('modelo_id', '=', modelo_id)])
        AccLine = self.env['sembradora.config.accessory.line']

        updated_configs_count = 0
        for item in updates:
            prod_id = item['product_id']
            new_price = float(item.get('price', 0.0))
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
        """Guarda precios de líneas de accesorio puntuales.

        @param updates Lista de dicts `{'line_id': id de sembradora.config.accessory.line, 'price': nuevo precio}`.
        @return dict `{success, updated_count}`.
        @throws AccessError Si el usuario no es administrador del configurador.
        """
        check_configurator_manager(self.env)
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
