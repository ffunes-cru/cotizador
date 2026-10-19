"""@file
Servicio RPC del Configurador Studio (componente OWL `cotizador_configurator_studio`).

El Studio muestra la matriz de una máquina como un árbol de atributos (una columna por
atributo) y permite habilitar, deshabilitar y ponerle precio o código a cada configuración.
Solo para el grupo Administrador del Configurador.
"""
import itertools

from odoo import _, api, models
from odoo.exceptions import UserError

from .sembradora_config import check_configurator_manager


class CotizadorStudioService(models.AbstractModel):
    """Servicio `cotizador.studio.service` (sin tabla)."""
    _name = 'cotizador.studio.service'
    _description = 'Servicio Backend para Configurador Studio'

    @api.model
    def get_studio_overview(self):
        """Máquinas con sus métricas para el selector del Studio.

        @return Lista de dicts `{id, name, default_code, list_price, variants_count,
                configs_count, coded_variants_count, has_image}`. "Codificadas" = variantes con
                referencia interna o configuraciones con `ext_id`, lo que sea mayor.
        @throws AccessError Si el usuario no es administrador del configurador.
        """
        check_configurator_manager(self.env)
        templates = self.env['product.template'].search([('is_maquina', '=', True)], order='name asc')
        result = []
        for tmpl in templates:
            var_count = self.env['product.product'].search_count([('product_tmpl_id', '=', tmpl.id)])
            config_count = self.env['sembradora.config.rel'].search_count([('modelo_id', '=', tmpl.id)])
            coded_count = self.env['product.product'].search_count([
                ('product_tmpl_id', '=', tmpl.id),
                ('default_code', '!=', False),
                ('default_code', '!=', '')
            ])
            # Con variantes dinámicas puede no haber product.product: se cuentan también las configuraciones con código
            coded_configs = self.env['sembradora.config.rel'].search_count([
                ('modelo_id', '=', tmpl.id),
                ('ext_id', '!=', False),
                ('ext_id', '!=', '')
            ])
            coded_count = max(coded_count, coded_configs)

            result.append({
                'id': tmpl.id,
                'name': tmpl.name,
                'default_code': tmpl.default_code or '',
                'list_price': tmpl.list_price,
                'variants_count': var_count,
                'configs_count': config_count,
                'coded_variants_count': coded_count,
                'has_image': bool(tmpl.image_128),
            })
        return result

    @api.model
    def get_model_studio_data(self, modelo_id):
        """Matriz de una máquina para el árbol del Studio.

        @param modelo_id Id de la máquina.
        @return dict `{modelo: {id, name, default_code, list_price, currency}, attributes:
                [{id, name, sequence, values}], configs: [{id, ext_id, name, price, value_ids,
                values_by_attr, accessory_count}], total_variants, coded_variants,
                accessories_count}`. Sin variantes creadas, `total_variants` es el producto
                cartesiano teórico de los valores.
        @throws AccessError Si el usuario no es administrador del configurador.
        @throws UserError Si la máquina no existe.
        """
        check_configurator_manager(self.env)
        tmpl = self.env['product.template'].browse(modelo_id)
        if not tmpl.exists():
            raise UserError(_("El modelo seleccionado no existe."))

        ptals = tmpl.attribute_line_ids.sorted(lambda l: (l.sequence, l.id))
        attributes_data = []
        for ptal in ptals:
            values_data = []
            for val in ptal.value_ids.sorted(lambda v: (v.sequence, v.id)):
                values_data.append({
                    'id': val.id,
                    'name': val.name,
                })
            attributes_data.append({
                'id': ptal.attribute_id.id,
                'name': ptal.attribute_id.name,
                'sequence': ptal.sequence,
                'values': values_data,
            })

        configs = self.env['sembradora.config.rel'].search([
            ('modelo_id', '=', tmpl.id)
        ], order='id asc')

        configs_data = []
        for c in configs:
            val_names = {v.attribute_id.id: v.name for v in c.value_ids}
            configs_data.append({
                'id': c.id,
                'ext_id': c.ext_id or '',
                'name': c.name,
                'price': c.price,
                'value_ids': c.value_ids.ids,
                'values_by_attr': val_names,
                'accessory_count': len(c.accessory_line_ids),
            })

        total_variants = self.env['product.product'].search_count([('product_tmpl_id', '=', tmpl.id)])
        coded_variants = self.env['product.product'].search_count([
            ('product_tmpl_id', '=', tmpl.id),
            ('default_code', '!=', False),
            ('default_code', '!=', '')
        ])

        # Con variantes dinámicas puede no haber ninguna creada: total teórico de combinaciones
        theoretical_total = 1
        for ptal in ptals:
            theoretical_total *= (len(ptal.value_ids) or 1)

        coded_configs = self.env['sembradora.config.rel'].search_count([
            ('modelo_id', '=', tmpl.id),
            ('ext_id', '!=', False),
            ('ext_id', '!=', '')
        ])

        if total_variants == 0:
            total_variants = theoretical_total
        coded_variants = max(coded_variants, coded_configs)

        accessories_count = self.env['product.product'].search_count([('cotizador_modelo_id', '=', tmpl.id)])

        return {
            'modelo': {
                'id': tmpl.id,
                'name': tmpl.name,
                'default_code': tmpl.default_code or '',
                'list_price': tmpl.list_price,
                'currency': tmpl.cotizador_currency_id.name,
            },
            'attributes': attributes_data,
            'configs': configs_data,
            'total_variants': total_variants,
            'coded_variants': coded_variants,
            'accessories_count': accessories_count,
        }

    @api.model
    def quick_update_config_price(self, config_id, new_price):
        """Cambia el precio de una configuración (edición en la hoja del árbol).

        @param config_id Id de la configuración.
        @param new_price Nuevo precio, en la Moneda del Cotizador del modelo.
        @return dict `{success, config_id, new_price}`.
        @throws AccessError Si el usuario no es administrador del configurador.
        @throws UserError Si la configuración no existe.
        """
        check_configurator_manager(self.env)
        config = self.env['sembradora.config.rel'].browse(config_id)
        if not config.exists():
            raise UserError(_("La configuración no existe."))
        config.write({'price': float(new_price)})
        return {'success': True, 'config_id': config_id, 'new_price': config.price}

    @api.model
    def quick_update_config_engineering_code(self, config_id, new_code):
        """Cambia el código de ingeniería (`ext_id`) de una configuración y lo copia a la variante.

        @param config_id Id de la configuración.
        @param new_code Código nuevo (se recortan espacios; vacío lo borra).
        @return dict `{success, config_id, new_code}`.
        @throws AccessError Si el usuario no es administrador del configurador.
        @throws UserError Si la configuración no existe.
        """
        check_configurator_manager(self.env)
        config = self.env['sembradora.config.rel'].browse(config_id)
        if not config.exists():
            raise UserError(_("La configuración no existe."))
        code = (new_code or '').strip()
        config.write({'ext_id': code})

        config._sync_variant_code()

        return {'success': True, 'config_id': config_id, 'new_code': code}

    @api.model
    def delete_configuration(self, config_id):
        """Deshabilita una combinación: borra su configuración (y sus líneas de accesorio).

        @param config_id Id de la configuración.
        @return dict `{success, config_id}`.
        @throws AccessError Si el usuario no es administrador del configurador.
        @throws UserError Si la configuración no existe.
        """
        check_configurator_manager(self.env)
        cfg = self.env['sembradora.config.rel'].browse(config_id)
        if not cfg.exists():
            raise UserError(_("La configuración no existe."))
        cfg.unlink()
        return {'success': True, 'config_id': config_id}

    @api.model
    def create_configuration(self, modelo_id, value_ids, price, ext_id=None):
        """Habilita una combinación: crea su configuración.

        Sin `ext_id` se genera uno provisorio "<referencia del modelo o M<id>>-<ids de valores>".

        @param modelo_id Id de la máquina.
        @param value_ids Ids de los valores de atributo de la combinación.
        @param price Precio, en la Moneda del Cotizador del modelo.
        @param ext_id Código externo (opcional).
        @return dict `{success, config: {...}}` con la configuración en el formato de get_model_studio_data().
        @throws AccessError Si el usuario no es administrador del configurador.
        @throws UserError Si la máquina no existe o no hay valores.
        @throws ValidationError Si la combinación ya existe.
        """
        check_configurator_manager(self.env)
        tmpl = self.env['product.template'].browse(modelo_id)
        if not tmpl.exists():
            raise UserError(_("El modelo seleccionado no existe."))

        v_ids = [int(v) for v in value_ids if v]
        if not v_ids:
            raise UserError(_("Debe especificar los valores de atributos para la configuración."))

        if not ext_id:
            code_part = tmpl.default_code or f"M{modelo_id}"
            ext_id = f"{code_part}-" + "-".join(str(v) for v in sorted(v_ids))

        vals = {
            'modelo_id': modelo_id,
            'value_ids': [(6, 0, v_ids)],
            'price': float(price or 0.0),
            'ext_id': ext_id,
        }
        config = self.env['sembradora.config.rel'].create(vals)

        config._sync_variant_code()

        val_names = {v.attribute_id.id: v.name for v in config.value_ids}
        return {
            'success': True,
            'config': {
                'id': config.id,
                'ext_id': config.ext_id or '',
                'name': config.name,
                'price': config.price,
                'value_ids': config.value_ids.ids,
                'values_by_attr': val_names,
                'accessory_count': 0,
            }
        }

    @api.model
    def batch_create_branch_configurations(self, modelo_id, partial_value_ids, base_price):
        """Habilita en bloque todas las combinaciones que faltan bajo una rama del árbol.

        Combina los valores fijados de la rama con todos los valores de los atributos
        restantes; omite las combinaciones que ya existen. El `ext_id` de cada una es
        "CFG-<id del modelo>-<ids de valores>".

        @param modelo_id Id de la máquina.
        @param partial_value_ids Ids de los valores fijados en la rama.
        @param base_price Precio de las configuraciones nuevas.
        @return dict `{success, created_count}`.
        @throws AccessError Si el usuario no es administrador del configurador.
        @throws UserError Si la máquina no existe.
        """
        check_configurator_manager(self.env)

        tmpl = self.env['product.template'].browse(modelo_id)
        if not tmpl.exists():
            raise UserError(_("El modelo seleccionado no existe."))

        ptals = tmpl.attribute_line_ids.sorted(lambda l: (l.sequence, l.id))
        partial_values = self.env['product.attribute.value'].browse(partial_value_ids)
        covered_attr_ids = set(partial_values.mapped('attribute_id.id'))

        remaining_ptals = [line for line in ptals if line.attribute_id.id not in covered_attr_ids]

        if not remaining_ptals:
            combinations = [list(partial_value_ids)]
        else:
            remaining_value_options = [[val.id for val in line.value_ids] for line in remaining_ptals]
            cartesian = list(itertools.product(*remaining_value_options))
            combinations = [list(partial_value_ids) + list(comb) for comb in cartesian]

        existing = self.env['sembradora.config.rel'].search([('modelo_id', '=', modelo_id)])
        existing_combos = [set(cfg.value_ids.ids) for cfg in existing]

        vals_list = []
        for combo in combinations:
            combo_set = set(combo)
            if combo_set in existing_combos:
                continue
            vals_list.append({
                'modelo_id': modelo_id,
                'value_ids': [(6, 0, combo)],
                'price': float(base_price or 0.0),
                'ext_id': f"CFG-{modelo_id}-" + "-".join(str(v) for v in sorted(combo)),
            })
            existing_combos.append(combo_set)
        # Un solo create: las variantes de la máquina se sincronizan una vez
        self.env['sembradora.config.rel'].create(vals_list)

        return {
            'success': True,
            'created_count': len(vals_list),
        }
