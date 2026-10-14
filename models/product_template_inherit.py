from odoo import models, fields, api
from markupsafe import Markup


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    is_maquina = fields.Boolean(
        string="Es Máquina",
        compute="_compute_is_maquina",
        store=True,
        help="Indica si este producto pertenece a la categoría de máquinas configurables."
    )
    available_attribute_ids = fields.Many2many(
        'product.attribute',
        string="Atributos de la Máquina",
        compute="_compute_available_attributes",
        help="Atributos configurados en las líneas de variantes de esta máquina."
    )
    available_attribute_value_ids = fields.Many2many(
        'product.attribute.value',
        string="Valores de Atributos Disponibles",
        compute="_compute_available_attributes",
        help="Todos los valores de atributo disponibles para configurar en esta máquina."
    )
    description_attribute_id = fields.Many2one(
        'product.attribute',
        string="Atributo Rector (Opcional)",
        domain="[('id', 'in', available_attribute_ids)]",
        help="Atributo de referencia si desea categorizar por una característica principal."
    )
    description_line_ids = fields.One2many(
        'product.template.description.line',
        'product_tmpl_id',
        string="Reglas de Descripción Paramétrica"
    )
    description_default = fields.Html(
        string="Descripción por Defecto",
        sanitize_style=True,
        help="Descripción general de respaldo si la combinación configurada no coincide con ninguna regla específica."
    )

    @api.depends('categ_id', 'categ_id.name')
    def _compute_is_maquina(self):
        for tmpl in self:
            tmpl.is_maquina = bool(tmpl.categ_id and tmpl.categ_id.name == 'Maquina')

    @api.depends('attribute_line_ids', 'attribute_line_ids.attribute_id', 'attribute_line_ids.value_ids')
    def _compute_available_attributes(self):
        for tmpl in self:
            tmpl.available_attribute_ids = tmpl.attribute_line_ids.mapped('attribute_id')
            tmpl.available_attribute_value_ids = tmpl.attribute_line_ids.mapped('value_ids')

    def get_config_description(self, value_ids):
        """
        Retorna la descripción HTML correspondiente a la combinación de valores dada.
        Evalúa reglas con N atributos requeridos:
        1. Filtra reglas cuyos 'value_ids' sean subconjunto de los valores seleccionados.
        2. Ordena por mayor especificidad (cantidad de atributos requeridos) y luego secuencia.
        3. Si no hay coincidencia, retorna la descripción por defecto.
        """
        self.ensure_one()
        if self.description_line_ids and value_ids:
            selected_set = set(value_ids.ids)
            matching_rules = []
            for rule in self.description_line_ids:
                if rule.value_ids and set(rule.value_ids.ids).issubset(selected_set):
                    matching_rules.append(rule)

            if matching_rules:
                # Ordenar: primero las que requieren más atributos (más específicas), luego por secuencia
                matching_rules.sort(key=lambda r: (-len(r.value_ids), r.sequence))
                best_rule = matching_rules[0]
                if best_rule.description:
                    return best_rule.description

        return self.description_default or self.description_sale or ''

    def action_open_in_studio(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'cotizador_configurator_studio',
            'name': f'Studio: {self.name}',
            'context': {'default_modelo_id': self.id},
        }

    def action_open_engineering_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'engineering.code.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_modelo_id': self.id},
        }

    def get_sequential_configurator_json(self):
        """
        Retorna la matriz de pasos y combinaciones válidas en formato JSON
        para el configurador secuencial del portal/tienda web.
        """
        self.ensure_one()
        if not self.is_maquina:
            return "{}"
        import json
        configs = self.env['sembradora.config.rel'].search([('modelo_id', '=', self.id)])
        steps = []
        for ptal in self.attribute_line_ids:
            ptavs = ptal.product_template_value_ids._only_active()
            steps.append({
                'attribute_id': ptal.attribute_id.id,
                'name': ptal.attribute_id.name,
                'ptal_id': ptal.id,
                'values': [{
                    'val_id': ptav.product_attribute_value_id.id,
                    'ptav_id': ptav.id,
                    'name': ptav.name,
                } for ptav in ptavs]
            })
        configs_data = []
        for c in configs:
            configs_data.append({
                'id': c.id,
                'name': c.name,
                'price': c.price,
                'val_ids': c.value_ids.ids,
            })
        currency_sym = 'USD $' if self.is_maquina else (self.currency_id.symbol or '$')
        json_data = json.dumps({
            'template_id': self.id,
            'template_name': self.name,
            'steps': steps,
            'configs': configs_data,
            'currency_symbol': currency_sym,
        }).replace('</', r'<\/')
        return Markup(json_data)

    def _is_combination_possible(self, combination, parent_combination=None, ignore_no_variant=False):
        """
        Para máquinas configurables, restringe la posibilidad de combinaciones a aquellas
        que existan en sembradora.config.rel (ingeniería técnica).
        """
        self.ensure_one()
        if not self.is_maquina:
            return super()._is_combination_possible(
                combination, parent_combination=parent_combination, ignore_no_variant=ignore_no_variant
            )

        configs = self.env['sembradora.config.rel'].search([('modelo_id', '=', self.id)])
        if not configs:
            return super()._is_combination_possible(
                combination, parent_combination=parent_combination, ignore_no_variant=ignore_no_variant
            )

        val_ids = set(combination.mapped('product_attribute_value_id.id'))
        if val_ids:
            if not any(val_ids.issubset(set(c.value_ids.ids)) for c in configs):
                return False

        return True

    def _get_combination_info(
        self, combination=False, product_id=False, add_qty=1.0, uom_id=False, only_template=False,
    ):
        """
        Sobreescribe el cálculo de precios en eCommerce/web para que las máquinas
        tomen su precio base real desde sembradora.config.rel y no desde list_price genérico.
        Aplica reglas de lista de precios (porcentajes, fórmulas) sobre dicho precio base.
        """
        try:
            res = super()._get_combination_info(
                combination=combination, product_id=product_id, add_qty=add_qty, uom_id=uom_id, only_template=only_template
            )
        except Exception:
            res = {
                'price': self.list_price,
                'list_price': self.list_price,
                'has_discounted_price': False,
                'is_combination_possible': True,
                'product_id': product_id or False,
                'product_template_id': self.id,
                'display_name': self.display_name,
            }

        if not self.is_maquina:
            return res

        configs = self.env['sembradora.config.rel'].search([('modelo_id', '=', self.id)])
        if not configs:
            return res

        if only_template:
            prices = [c.price for c in configs if c.price]
            min_price = min(prices) if prices else self.list_price
            res['price'] = min_price
            res['list_price'] = min_price
            return res

        val_ids = set()
        if combination:
            val_ids = set(combination.mapped('product_attribute_value_id.id'))
        elif product_id:
            prod = self.env['product.product'].browse(product_id)
            if prod.exists():
                val_ids = set(prod.product_template_attribute_value_ids.mapped('product_attribute_value_id.id'))

        matching_config = False
        if val_ids:
            for c in configs:
                if set(c.value_ids.ids) == val_ids:
                    matching_config = c
                    break
            if not matching_config:
                for c in configs:
                    if val_ids.issubset(set(c.value_ids.ids)):
                        matching_config = c
                        break

        if matching_config and matching_config.price:
            base_price = matching_config.price
            final_price = base_price

            pricelist = False
            try:
                from odoo.http import request
                if hasattr(request, 'website') and request.website:
                    pricelist = request.website.get_current_pricelist()
            except Exception:
                pass

            if not pricelist:
                ctx_pl = self.env.context.get('pricelist')
                if ctx_pl:
                    pricelist = self.env['product.pricelist'].browse(ctx_pl)

            if pricelist and pricelist.exists():
                product = self.env['product.product'].browse(res.get('product_id')) if res.get('product_id') else False
                product_or_tmpl = product if (product and product.exists()) else self
                rules = pricelist._get_applicable_rules(product_or_tmpl, fields.Datetime.now())
                suitable_rule = self.env['product.pricelist.item']
                for rule in rules:
                    if rule._is_applicable_for(product_or_tmpl, add_qty or 1.0):
                        suitable_rule = rule
                        break
                if suitable_rule:
                    if suitable_rule.compute_price == 'percentage':
                        final_price = round(base_price - (base_price * (suitable_rule.percent_price / 100.0)), 2)
                    elif suitable_rule.compute_price == 'formula':
                        discount = suitable_rule.price_discount
                        final_price = round(base_price - (base_price * (discount / 100.0)) + suitable_rule.price_surcharge, 2)
                        if suitable_rule.price_min_margin:
                            final_price = max(final_price, base_price + suitable_rule.price_min_margin)
                        if suitable_rule.price_max_margin:
                            final_price = min(final_price, base_price + suitable_rule.price_max_margin)
                    elif suitable_rule.compute_price == 'fixed':
                        final_price = suitable_rule.fixed_price

            res['price'] = final_price
            res['list_price'] = base_price
            res['has_discounted_price'] = bool(final_price < base_price)
            res['is_combination_possible'] = True

        return res


class ProductTemplateDescriptionLine(models.Model):
    _name = 'product.template.description.line'
    _description = 'Regla de Descripción Paramétrica por Combinación de Atributos'
    _order = 'sequence asc, id asc'

    product_tmpl_id = fields.Many2one(
        'product.template',
        string="Modelo de Máquina",
        required=True,
        ondelete='cascade',
        index=True
    )
    name = fields.Char(
        string="Nombre / Referencia",
        help="Ej: Leaf Mecánica, Leaf Neumática, Pionera..."
    )
    sequence = fields.Integer(
        string="Secuencia",
        default=10,
        help="Orden de evaluación y prioridad para desempatar reglas con igual cantidad de atributos."
    )
    value_ids = fields.Many2many(
        'product.attribute.value',
        'product_tmpl_desc_line_attr_val_rel',
        'line_id',
        'val_id',
        string="Valores de Atributo Requeridos",
        help="Seleccione uno o más valores que deben estar presentes en la variante para aplicar esta descripción (ej. LEAF + Mecánico)."
    )
    description = fields.Html(
        string="Descripción Técnica (Rich Text)",
        sanitize_style=True,
        required=True,
        help="Texto enriquecido que se mostrará en el configurador interactivo y en la cotización PDF."
    )

    @api.onchange('value_ids')
    def _onchange_value_ids_name(self):
        """Genera un nombre sugerido automáticamente si está vacío."""
        if not self.name and self.value_ids:
            self.name = " + ".join(self.value_ids.mapped('name'))
