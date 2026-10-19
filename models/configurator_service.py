"""@file
Servicio RPC del configurador visual (componente OWL `cotizador_configurator`).

Flujo del componente (static/src/components/configurador/configurador.js):
get_initial_data() → el vendedor elige modelo → get_model_matrix() → elige atributos hasta una
configuración → get_config_accessories() → elige accesorios → confirm_configuration().

Los precios que devuelve son los que quedarán en la cotización (lista de precios y moneda de
la orden); confirm_configuration() los vuelve a calcular en el servidor.
"""
from odoo import _, api, models
from odoo.exceptions import UserError


class CotizadorConfiguratorService(models.AbstractModel):
    """Servicio `cotizador.configurator.service` (sin tabla; lo usan vendedores).

    Corre con los permisos del usuario: los vendedores leen la matriz (ACL de solo lectura) y
    escriben en sus cotizaciones.
    """
    _name = 'cotizador.configurator.service'
    _description = 'Servicio RPC para el Configurador Visual de Sembradoras'

    @api.model
    def get_initial_data(self, order_id):
        """Datos iniciales: la cotización y el catálogo de máquinas.

        @param order_id Id de la cotización (sale.order).
        @return dict `{order: {id, name, partner_id, partner_name, state, currency_symbol,
                tax_label}, models: [{id, name, default_code, config_count, description,
                has_image, image_url}], modo_silencioso}`.
        @throws UserError Si la cotización no existe.
        """
        order = self.env['sale.order'].browse(order_id)
        if not order.exists():
            raise UserError(_("La cotización solicitada no existe o no se pudo encontrar."))

        templates = self.env['product.template'].search([('is_maquina', '=', True)], order='name asc')

        # Conteo de configuraciones por modelo
        config_count_by_model = {
            modelo.id: count for modelo, count in self.env['sembradora.config.rel']._read_group(
                [('modelo_id', 'in', templates.ids)], ['modelo_id'], ['__count'],
            )
        }

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
                'currency_symbol': f"{order.currency_id.name} {order.currency_id.symbol}",
                'tax_label': order.company_id.cotizador_tax_id.name or '',
            },
            'models': models_data,
            'modo_silencioso': modo_silencioso,
        }

    @api.model
    def get_model_matrix(self, modelo_id, order_id):
        """Matriz completa de una máquina, para filtrarla en el navegador sin más llamadas.

        @param modelo_id Id de la máquina (product.template).
        @param order_id Id de la cotización: los precios salen con su lista de precios y moneda.
        @return dict `{model: {...}, attributes: [{id, name, show_in_description,
                show_incompatible_alternatives, values: [{id, name}]}], configs: [{id,
                value_ids, price, description}]}`. Los atributos siguen el orden de la plantilla.
        @throws UserError Si la máquina no existe.
        """
        modelo = self.env['product.template'].browse(modelo_id)
        if not modelo.exists():
            raise UserError(_("El modelo seleccionado no existe."))
        order = self.env['sale.order'].browse(order_id)

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

        all_val_ids = set()
        for cfg in configs:
            for v in cfg.value_ids:
                all_val_ids.add(v.id)

        values = self.env['product.attribute.value'].browse(list(all_val_ids))
        attr_ids = values.mapped('attribute_id')

        # Orden de los atributos: el de las líneas de atributo de la plantilla
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
                'show_in_description': attr.show_in_description,
                'show_incompatible_alternatives': attr.show_incompatible_alternatives,
                'values': [{
                    'id': v.id,
                    'name': v.name,
                } for v in attr_values]
            })

        configs_data = [{
            'id': c.id,
            'value_ids': c.value_ids.ids,
            'price': order._cotizador_machine_price(c),
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

    @api.model
    def get_config_accessories(self, config_id, order_id):
        """Accesorios de una configuración, con cantidad y precio como quedarán en la orden.

        @param config_id Id de la configuración (sembradora.config.rel).
        @param order_id Id de la cotización (lista de precios y moneda).
        @return dict `{config_id, base_price, description, accessories}`. Cada accesorio trae
                `line_id`, producto, categoría, imagen, `price_unit`, `quantity`, `subtotal`,
                `is_trigger`, `is_standard`, `selected` (= estándar), `rules`, `is_locked`, y
                para los grupos de opción única `choice_group_id`, `choice_group_name` y
                `price_delta` (diferencia de subtotal con el estándar del grupo).
        @throws UserError Si la configuración no existe.
        """
        config = self.env['sembradora.config.rel'].browse(config_id)
        if not config.exists():
            raise UserError(_("La configuración seleccionada no existe."))
        order = self.env['sale.order'].browse(order_id)

        offer = config._get_accessory_offer()
        for item in offer:
            item['order_price_unit'] = round(order._cotizador_accessory_price(item), 2)
            item['order_subtotal'] = round(item['order_price_unit'] * item['quantity'], 2)
        standard_subtotal = {
            item['choice_rule']: item['order_subtotal'] for item in offer if item['choice_rule'] and item['is_standard']
        }

        accessories_data = []
        for item in offer:
            acc_line, prod, choice = item['line'], item['product'], item['choice_rule']
            accessories_data.append({
                'line_id': acc_line.id,
                'product_id': prod.id,
                'product_name': prod.name,
                'default_code': prod.default_code or '',
                'category_id': prod.categ_id.id,
                'category_name': prod.categ_id.name,
                'has_image': bool(prod.image_128),
                'image_url': f'/web/image/product.product/{prod.id}/image_128' if prod.image_128 else False,
                'price_unit': item['order_price_unit'],
                'quantity': item['quantity'],
                'subtotal': item['order_subtotal'],
                'is_trigger': item['is_trigger'],
                'is_standard': item['is_standard'],
                'choice_group_id': choice.id,
                'choice_group_name': choice.name or '',
                'price_delta': round(item['order_subtotal'] - standard_subtotal[choice], 2) if choice else 0.0,
                'rules': [{
                    'id': rule.id,
                    'name': rule.name,
                    'rule_type': rule.rule_type,
                } for rule in acc_line.rule_ids],
                'is_locked': item['is_inclusion_locked'],
                'is_inclusion_locked': item['is_inclusion_locked'],
                'selected': item['selected'],
            })

        return {
            'config_id': config.id,
            'base_price': order._cotizador_machine_price(config),
            'description': config.description or '',
            'accessories': accessories_data,
        }

    @api.model
    def confirm_configuration(self, order_id, config_id, selected_line_ids=None):
        """Agrega a la cotización la máquina configurada y los accesorios elegidos.

        Valida la selección y recalcula precios y cantidades en el servidor
        (sale.order._cotizador_add_configuration()).

        @param order_id Id de la cotización.
        @param config_id Id de la configuración elegida.
        @param selected_line_ids Ids de sembradora.config.accessory.line elegidas.
        @return dict `{success: True, order_id, order_name}`.
        @throws UserError Si la cotización o la configuración no existen, o la selección viola las reglas.
        """
        order = self.env['sale.order'].browse(order_id)
        if not order.exists():
            raise UserError(_("La orden de venta #%s no existe.", order_id))

        config = self.env['sembradora.config.rel'].browse(config_id)
        if not config.exists():
            raise UserError(_("La configuración seleccionada no existe."))

        acc_lines = self.env['sembradora.config.accessory.line'].browse(selected_line_ids or []).exists()
        order._cotizador_add_configuration(config, acc_lines)

        return {
            'success': True,
            'order_id': order.id,
            'order_name': order.name,
        }
