import json

from markupsafe import Markup

from odoo import api, fields, models
from odoo.http import request
from odoo.tools import ormcache


def _in_category(categ, root):
    """True si `categ` es `root` o una de sus subcategorías."""
    return bool(categ and root and (categ.parent_path or '').startswith(root.parent_path or '\0'))


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    is_maquina = fields.Boolean(
        string="Es Máquina",
        compute="_compute_cotizador_kind",
        store=True,
        help="El producto está en la categoría Máquina (o una subcategoría): es una máquina configurable."
    )
    is_accesorio = fields.Boolean(
        string="Es Accesorio",
        compute="_compute_cotizador_kind",
        store=True,
        help="El producto está en la categoría Accesorio (o una subcategoría)."
    )
    available_attribute_value_ids = fields.Many2many(
        'product.attribute.value',
        string="Valores de Atributos Disponibles",
        compute="_compute_available_attributes",
        help="Todos los valores de atributo disponibles para configurar en esta máquina."
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

    @api.depends('categ_id', 'categ_id.parent_path')
    def _compute_cotizador_kind(self):
        # Durante la instalación el campo se calcula antes de cargar los datos del módulo
        cat_maquina = self.env.ref('cotizador.cat_maquina', raise_if_not_found=False)
        cat_accesorio = self.env.ref('cotizador.cat_accesorio_base', raise_if_not_found=False)
        for tmpl in self:
            tmpl.is_maquina = _in_category(tmpl.categ_id, cat_maquina)
            tmpl.is_accesorio = _in_category(tmpl.categ_id, cat_accesorio)

    @api.depends('attribute_line_ids', 'attribute_line_ids.attribute_id', 'attribute_line_ids.value_ids')
    def _compute_available_attributes(self):
        for tmpl in self:
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
            matching_rules = [
                rule for rule in self.description_line_ids
                if rule.value_ids and set(rule.value_ids.ids).issubset(selected_set)
            ]
            if matching_rules:
                # Ordenar: primero las que requieren más atributos (más específicas), luego por secuencia
                matching_rules.sort(key=lambda r: (-len(r.value_ids), r.sequence))
                if matching_rules[0].description:
                    return matching_rules[0].description

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
        configs = self.env['sembradora.config.rel'].sudo().search([('modelo_id', '=', self.id)])
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
        # Precios con la lista de precios de la sesión web (mismas reglas que el resto de la tienda)
        pricelist = request.pricelist
        currency = pricelist.currency_id or request.website.currency_id
        configs_data = [{
            'id': c.id,
            'name': c.name,
            'price': pricelist._get_product_price(
                self._with_matrix_price(c.price), 1.0, currency=currency,
            ) if c.price else 0.0,
            'val_ids': c.value_ids.ids,
        } for c in configs]
        json_data = json.dumps({
            'template_id': self.id,
            'template_name': self.name,
            'steps': steps,
            'configs': configs_data,
            'currency_symbol': f"{currency.name} {currency.symbol}",
        }).replace('</', r'<\/')
        return Markup(json_data)

    # -------------------------------------------------------------------------
    #  Índice de configuraciones (cacheado; se invalida al escribir la matriz)
    # -------------------------------------------------------------------------

    @api.model
    @ormcache('tmpl_id')
    def _cotizador_config_index(self, tmpl_id):
        """((config_id, frozenset(value_ids), price), ...) de las configuraciones de una máquina."""
        configs = self.env['sembradora.config.rel'].sudo().search([('modelo_id', '=', tmpl_id)])
        return tuple((c.id, frozenset(c.value_ids.ids), c.price) for c in configs)

    def _cotizador_find_config(self, value_ids):
        """Configuración cuya combinación es exactamente `value_ids` (o vacío)."""
        self.ensure_one()
        value_ids = frozenset(value_ids)
        for config_id, config_values, _price in self._cotizador_config_index(self.id):
            if config_values == value_ids:
                return self.env['sembradora.config.rel'].sudo().browse(config_id)
        return self.env['sembradora.config.rel']

    def _is_combination_possible(self, combination, parent_combination=None, ignore_no_variant=False):
        """
        Para máquinas configurables, una combinación (completa o parcial) es posible solo si
        alguna configuración de la matriz de ingeniería la contiene.
        """
        self.ensure_one()
        index = self._cotizador_config_index(self.id) if self.is_maquina else ()
        if not index:
            return super()._is_combination_possible(
                combination, parent_combination=parent_combination, ignore_no_variant=ignore_no_variant
            )
        val_ids = set(combination.product_attribute_value_id.ids)
        return any(val_ids <= config_values for _id, config_values, _price in index)

    # -------------------------------------------------------------------------
    #  Precios: el precio de lista de máquinas y accesorios es el de la matriz (en la
    #  moneda de la matriz de la compañía). Se engancha en _price_compute, que es la base
    #  de TODAS las reglas de listas de precios de Odoo (tienda, portal y backend): las
    #  reglas, conversiones de moneda y descuentos son los nativos.
    #
    #  Contexto `cotizador_matrix_price = (modelo, id, precio)`: precio de matriz explícito
    #  para ese registro (configuración elegida, precio del accesorio en una configuración).
    # -------------------------------------------------------------------------

    def _with_matrix_price(self, price):
        self.ensure_one()
        return self.with_context(cotizador_matrix_price=(self._name, self.id, price))

    def _get_product_price_context(self, combination):
        """En la tienda, una combinación sin variante creada se cotiza con su configuración."""
        res = super()._get_product_price_context(combination)
        if self.is_maquina:
            config = self._cotizador_find_config(combination.product_attribute_value_id.ids)
            if config:
                res['cotizador_matrix_price'] = (self._name, self.id, config.price)
        return res

    def _cotizador_convert_matrix_price(self, price, uom=None, currency=None, company=None, date=False):
        """Convierte un precio de la matriz a la UdM y moneda pedidas (o la del producto)."""
        self.ensure_one()
        company = company or self.env.company
        if uom:
            price = self.uom_id._compute_price(price, uom)
        return company.cotizador_matrix_currency_id._convert(
            price, currency or self.currency_id, company, date or fields.Date.context_today(self), round=False,
        )

    def _cotizador_matrix_list_price(self):
        """Precio de matriz de la plantilla: el del contexto o, para máquinas, el "desde"."""
        self.ensure_one()
        model, res_id, price = self.env.context.get('cotizador_matrix_price') or (None, None, None)
        if (model, res_id) == (self._name, self.id):
            return price
        if self.is_maquina:
            prices = [price for _id, _values, price in self._cotizador_config_index(self.id) if price]
            return min(prices) if prices else None
        return None

    def _price_compute(self, price_type, uom=None, currency=None, company=None, date=False):
        prices = super()._price_compute(price_type, uom=uom, currency=currency, company=company, date=date)
        if price_type == 'list_price':
            for tmpl in self:
                price = tmpl._cotizador_matrix_list_price()
                if price is not None:
                    prices[tmpl.id] = tmpl._cotizador_convert_matrix_price(price, uom, currency, company, date)
        return prices


class ProductProduct(models.Model):
    _inherit = 'product.product'

    def _with_matrix_price(self, price):
        self.ensure_one()
        return self.with_context(cotizador_matrix_price=(self._name, self.id, price))

    def _cotizador_matrix_list_price(self):
        """Precio de matriz de la variante: el del contexto o el de su configuración (máquinas)."""
        self.ensure_one()
        model, res_id, price = self.env.context.get('cotizador_matrix_price') or (None, None, None)
        if (model, res_id) == (self._name, self.id):
            return price
        if self.is_maquina:
            config = self.product_tmpl_id._cotizador_find_config(
                self.product_template_attribute_value_ids.product_attribute_value_id.ids
            )
            return config.price if config else None
        return None

    def _price_compute(self, price_type, uom=None, currency=None, company=None, date=False):
        prices = super()._price_compute(price_type, uom=uom, currency=currency, company=company, date=date)
        if price_type == 'list_price':
            for product in self:
                price = product._cotizador_matrix_list_price()
                if price is not None:
                    prices[product.id] = product.product_tmpl_id._cotizador_convert_matrix_price(
                        price, uom, currency, company, date,
                    )
        return prices


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
