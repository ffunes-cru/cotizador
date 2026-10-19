from odoo import _, api, models
from odoo.exceptions import UserError

from .sembradora_config import check_configurator_manager


class CotizadorStudioService(models.AbstractModel):
    _name = 'cotizador.studio.service'
    _description = 'Servicio Backend para Configurador Studio'

    @api.model
    def get_studio_overview(self):
        """Retorna la lista de modelos de máquinas y métricas globales."""
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
            # Si el modelo utiliza variantes dinámicas o no tiene product.product pre-creados,
            # medimos códigos asignados directamente en sembradora.config.rel
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
        """Retorna la información completa de un modelo para el studio interactivo."""
        check_configurator_manager(self.env)
        tmpl = self.env['product.template'].browse(modelo_id)
        if not tmpl.exists():
            raise UserError(_("El modelo seleccionado no existe."))

        # 1. Atributos y Valores
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

        # 2. Configuraciones activas en sembradora.config.rel
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

        # 3. Métricas de Variantes Odoo con soporte para variantes dinámicas
        total_variants = self.env['product.product'].search_count([('product_tmpl_id', '=', tmpl.id)])
        coded_variants = self.env['product.product'].search_count([
            ('product_tmpl_id', '=', tmpl.id),
            ('default_code', '!=', False),
            ('default_code', '!=', '')
        ])

        # En PRD muchas máquinas usan create_variant = 'dynamic'. Si total_variants es 0,
        # calculamos el total teórico de combinaciones posibles a partir de sus atributos.
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

        # 4. Cantidad de accesorios del catálogo (se muestra como métrica en el Studio)
        accessories_count = self.env['product.product'].search_count([('is_accesorio', '=', True)])

        return {
            'modelo': {
                'id': tmpl.id,
                'name': tmpl.name,
                'default_code': tmpl.default_code or '',
                'list_price': tmpl.list_price,
            },
            'attributes': attributes_data,
            'configs': configs_data,
            'total_variants': total_variants,
            'coded_variants': coded_variants,
            'accessories_count': accessories_count,
        }

    @api.model
    def quick_update_config_price(self, config_id, new_price):
        """Actualización rápida de precio para una celda individual."""
        check_configurator_manager(self.env)
        config = self.env['sembradora.config.rel'].browse(config_id)
        if not config.exists():
            raise UserError(_("La configuración no existe."))
        config.write({'price': float(new_price)})
        return {'success': True, 'config_id': config_id, 'new_price': config.price}

    @api.model
    def quick_update_config_engineering_code(self, config_id, new_code):
        """
        Actualización rápida del código de ingeniería (Teamcenter / ID externo)
        para una configuración individual desde el Árbol de Columnas.
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
        """Elimina una configuración individual."""
        check_configurator_manager(self.env)
        cfg = self.env['sembradora.config.rel'].browse(config_id)
        if not cfg.exists():
            raise UserError(_("La configuración no existe."))
        cfg.unlink()
        return {'success': True, 'config_id': config_id}

    @api.model
    def create_configuration(self, modelo_id, value_ids, price, ext_id=None):
        """
        Crea una nueva configuración en sembradora.config.rel para el modelo indicado.
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
        """
        Genera en bloque todas las combinaciones faltantes bajo la rama especificada
        por partial_value_ids.
        """
        check_configurator_manager(self.env)
        import itertools

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

        created_count = 0
        ConfigRel = self.env['sembradora.config.rel']
        for combo in combinations:
            combo_set = set(combo)
            if combo_set in existing_combos:
                continue
            ext_id = f"CFG-{modelo_id}-" + "-".join(str(v) for v in sorted(combo))
            ConfigRel.create({
                'modelo_id': modelo_id,
                'value_ids': [(6, 0, combo)],
                'price': float(base_price or 0.0),
                'ext_id': ext_id,
            })
            existing_combos.append(combo_set)
            created_count += 1

        return {
            'success': True,
            'created_count': created_count,
        }
