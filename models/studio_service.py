# Part of Crucianelli Cotizador Module
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class CotizadorStudioService(models.AbstractModel):
    _name = 'cotizador.studio.service'
    _description = 'Servicio Backend para Configurador Studio'

    @api.model
    def get_studio_overview(self):
        """Retorna la lista de modelos de máquinas y métricas globales."""
        MaquinaCategory = self.env['product.category'].search([('name', '=', 'Maquina')], limit=1)
        domain = [('categ_id', '=', MaquinaCategory.id)] if MaquinaCategory else [('is_maquina', '=', True)]

        templates = self.env['product.template'].search(domain, order='name asc')
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

        # 4. Catálogo de Accesorios para asignación
        acc_domain = [('categ_id.name', '=', 'Accesorio')]
        accessories = self.env['product.product'].search(acc_domain, order='name asc')
        accessories_data = []
        for a in accessories:
            accessories_data.append({
                'id': a.id,
                'name': a.name,
                'default_code': a.default_code or '',
                'list_price': a.list_price,
                'category_name': a.categ_id.name if a.categ_id else '',
            })

        # 5. Catálogo de Reglas de Inclusión/Exclusión
        rules = self.env['sembradora.accessory.rule'].search([], order='name asc')
        rules_data = [{
            'id': r.id,
            'name': r.name,
            'rule_type': r.rule_type,
            'display_name': r.display_name,
        } for r in rules]

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
            'accessories_catalog': accessories_data,
            'rules_catalog': rules_data,
        }

    @api.model
    def quick_update_config_price(self, config_id, new_price):
        """Actualización rápida de precio para una celda individual."""
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
        config = self.env['sembradora.config.rel'].browse(config_id)
        if not config.exists():
            raise UserError(_("La configuración no existe."))
        code = (new_code or '').strip()
        config.write({'ext_id': code})

        # Sincronización segura con product.product si la variante física existe
        try:
            ptavs = self.env['product.template.attribute.value'].search([
                ('product_tmpl_id', '=', config.modelo_id.id),
                ('product_attribute_value_id', 'in', config.value_ids.ids)
            ])
            if ptavs:
                variant = self.env['product.product'].search([
                    ('product_tmpl_id', '=', config.modelo_id.id),
                    ('product_template_attribute_value_ids', 'in', ptavs.ids)
                ]).filtered(lambda p: set(p.product_template_attribute_value_ids.ids) == set(ptavs.ids))
                if variant:
                    variant.write({'default_code': code})
        except Exception as e:
            _logger.warning("No se pudo sincronizar default_code en product.product: %s", e)

        return {'success': True, 'config_id': config_id, 'new_code': code}

    @api.model
    def batch_update_config_prices(self, config_ids, update_type, value):
        """
        Actualiza el precio de múltiples configuraciones simultáneamente.
        update_type: 'fixed', 'percentage', 'delta'
        """
        configs = self.env['sembradora.config.rel'].browse(config_ids)
        if not configs:
            raise UserError(_("No se seleccionaron configuraciones."))

        val = float(value)
        for c in configs:
            if update_type == 'fixed':
                new_price = val
            elif update_type == 'percentage':
                new_price = round(c.price * (1.0 + val / 100.0), 2)
            elif update_type == 'delta':
                new_price = round(c.price + val, 2)
            else:
                new_price = c.price
            c.price = max(0.0, new_price)

        return {'success': True, 'updated_count': len(configs)}

    @api.model
    def batch_assign_accessories(self, config_ids, accessory_ids, price_mode, fixed_price, rule_ids, is_trigger):
        """
        Vincula uno o más accesorios a una lista de configuraciones por lote.
        """
        configs = self.env['sembradora.config.rel'].browse(config_ids)
        if not configs:
            raise UserError(_("No se seleccionaron configuraciones."))

        acc_prods = self.env['product.product'].browse(accessory_ids)
        if not acc_prods:
            raise UserError(_("No se seleccionaron accesorios."))

        AccLine = self.env['sembradora.config.accessory.line']
        created_count = 0
        updated_count = 0

        for config in configs:
            for acc in acc_prods:
                existing_line = AccLine.search([
                    ('config_id', '=', config.id),
                    ('product_id', '=', acc.id)
                ], limit=1)

                price = float(fixed_price) if price_mode == 'fixed' else acc.list_price
                vals = {
                    'price': price,
                    'is_trigger': bool(is_trigger),
                }
                if rule_ids is not None:
                    vals['rule_ids'] = [(6, 0, rule_ids)]

                if existing_line:
                    existing_line.write(vals)
                    updated_count += 1
                else:
                    vals.update({
                        'config_id': config.id,
                        'product_id': acc.id,
                    })
                    AccLine.create(vals)
                    created_count += 1

        return {
            'success': True,
            'created_count': created_count,
            'updated_count': updated_count,
        }

    @api.model
    def delete_configuration(self, config_id):
        """Elimina una configuración individual."""
        cfg = self.env['sembradora.config.rel'].browse(config_id)
        if not cfg.exists():
            raise UserError(_("La configuración no existe."))
        cfg.unlink()
        return {'success': True, 'config_id': config_id}

    @api.model
    def batch_delete_configs(self, config_ids):
        """Elimina las configuraciones seleccionadas."""
        configs = self.env['sembradora.config.rel'].browse(config_ids)
        count = len(configs)
        configs.unlink()
        return {'success': True, 'deleted_count': count}

    @api.model
    def create_configuration(self, modelo_id, value_ids, price, ext_id=None):
        """
        Crea una nueva configuración en sembradora.config.rel para el modelo indicado.
        """
        tmpl = self.env['product.template'].browse(modelo_id)
        if not tmpl.exists():
            raise UserError(_("El modelo seleccionado no existe."))

        v_ids = [int(v) for v in value_ids if v]
        if not v_ids:
            raise UserError(_("Debe especificar los valores de atributos para la configuración."))

        # Validar duplicados
        existing = self.env['sembradora.config.rel'].search([('modelo_id', '=', modelo_id)])
        for cfg in existing:
            if set(cfg.value_ids.ids) == set(v_ids):
                raise UserError(_("Ya existe una configuración con esta combinación exacta de atributos (#%s).") % cfg.id)

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

        # Sincronización segura con product.product si la variante física existe
        if ext_id:
            try:
                ptavs = self.env['product.template.attribute.value'].search([
                    ('product_tmpl_id', '=', modelo_id),
                    ('product_attribute_value_id', 'in', v_ids)
                ])
                if ptavs:
                    variant = self.env['product.product'].search([
                        ('product_tmpl_id', '=', modelo_id),
                        ('product_template_attribute_value_ids', 'in', ptavs.ids)
                    ]).filtered(lambda p: set(p.product_template_attribute_value_ids.ids) == set(ptavs.ids))
                    if variant:
                        variant.write({'default_code': ext_id})
            except Exception as e:
                _logger.warning("No se pudo sincronizar default_code en product.product: %s", e)

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
