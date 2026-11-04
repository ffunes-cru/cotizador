"""@file
Productos del cotizador: máquinas, accesorios, precios de matriz y descripción paramétrica.

- Una plantilla es **máquina** o **accesorio** según su categoría (`cotizador.cat_maquina`,
  `cotizador.cat_accesorio_base` o subcategorías).
- **Precios**: el precio de lista de máquinas y accesorios es el de la matriz, en la *Moneda del
  Cotizador* de cada producto. Se engancha en `_price_compute`, base de todas las listas de
  precios de Odoo: reglas, conversión de moneda y descuentos son los nativos.
- **Combinaciones**: una máquina solo admite las combinaciones de su matriz
  (`_is_combination_possible`), leídas de un índice en caché (`_cotizador_config_index`).
"""
import json

from markupsafe import Markup

from odoo import api, fields, models
from odoo.http import request
from odoo.tools import ormcache


def _in_category(categ, root):
    """Indica si una categoría es `root` o cuelga de ella, usando `parent_path` (sin consultas).

    @param categ product.category a evaluar (puede ser vacío).
    @param root product.category raíz (puede ser vacío durante la instalación).
    @return True si `categ` es `root` o una de sus subcategorías.
    """
    return bool(categ and root and (categ.parent_path or '').startswith(root.parent_path or '\0'))


class ProductTemplate(models.Model):
    """Plantilla de producto (`product.template`) extendida para máquinas y accesorios."""
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
    cotizador_currency_id = fields.Many2one(
        'res.currency',
        string="Moneda del Cotizador",
        required=True,
        default=lambda self: self.env.company.currency_id,
        help="Moneda de los precios de la matriz de este producto: los de sus configuraciones (máquina) "
             "o los de sus líneas de accesorio (accesorio). El importador la fija con la moneda elegida al importar."
    )
    cotizador_modelo_id = fields.Many2one(
        'product.template',
        string="Modelo de Máquina",
        index=True,
        domain=[('is_maquina', '=', True)],
        help="Máquina a la que pertenece este accesorio. Cada accesorio es de un único modelo: "
             "solo puede usarse en configuraciones de esa máquina."
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
        """Calcula `is_maquina` / `is_accesorio` a partir de la categoría.

        Durante la instalación se calcula antes de que existan las categorías del módulo
        (por eso `raise_if_not_found=False`).
        """
        cat_maquina = self.env.ref('cotizador.cat_maquina', raise_if_not_found=False)
        cat_accesorio = self.env.ref('cotizador.cat_accesorio_base', raise_if_not_found=False)
        for tmpl in self:
            tmpl.is_maquina = _in_category(tmpl.categ_id, cat_maquina)
            tmpl.is_accesorio = _in_category(tmpl.categ_id, cat_accesorio)

    @api.constrains('cotizador_modelo_id')
    def _check_cotizador_modelo(self):
        """Al cambiar el modelo de un accesorio, sus líneas deben seguir siendo de ese modelo.

        @throws ValidationError Ver SembradoraConfigAccessoryLine._check_product_modelo().
        """
        lines = self.env['sembradora.config.accessory.line'].search([('product_id.product_tmpl_id', 'in', self.ids)])
        lines._check_product_modelo()

    @api.depends('attribute_line_ids', 'attribute_line_ids.attribute_id', 'attribute_line_ids.value_ids')
    def _compute_available_attributes(self):
        """Valores de las líneas de atributo (dominio de las reglas de descripción)."""
        for tmpl in self:
            tmpl.available_attribute_value_ids = tmpl.attribute_line_ids.mapped('value_ids')

    def get_config_description(self, value_ids):
        """Descripción HTML de una combinación según las reglas de *Descripción Paramétrica*.

        1. Candidatas: reglas cuyos valores son subconjunto de `value_ids`.
        2. Gana la más específica (más valores) y, a igualdad, la de menor secuencia.
        3. Sin candidata: `description_default` o, si está vacía, `description_sale`.

        @param value_ids product.attribute.value de la combinación.
        @return HTML (o texto vacío).
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

    def action_open_engineering_wizard(self):
        """Botón *Códigos Teamcenter* de la ficha de la máquina.

        @return Acción que abre engineering.code.wizard para este modelo.
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'engineering.code.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_modelo_id': self.id},
        }

    def get_sequential_configurator_json(self):
        """Datos del configurador paso a paso de la ficha de producto en la tienda.

        Lo llama la plantilla `cotizador.product_sequential_configurator` y lo lee
        static/src/js/cotizador_sequential_configurator.js. Los precios pasan por la lista de
        precios de la sesión web. Lee la matriz con sudo (el visitante no tiene acceso).

        @return Markup con un JSON `{template_id, template_name, steps, configs, currency_symbol}`
                (`</` escapado para poder incrustarlo en un `<script>`), o `"{}"` si no es máquina.
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

    @api.model
    @ormcache('tmpl_id')
    def _cotizador_config_index(self, tmpl_id):
        """Índice en caché de las configuraciones de una máquina.

        Lo usan la tienda (combinaciones posibles y precio "desde") y la búsqueda de
        configuración por combinación. Se invalida con `registry.clear_cache()` al crear,
        modificar o borrar configuraciones.

        @param tmpl_id Id de la plantilla de la máquina.
        @return Tupla de `(config_id, frozenset(value_ids), price)`.
        """
        configs = self.env['sembradora.config.rel'].sudo().search([('modelo_id', '=', tmpl_id)])
        return tuple((c.id, frozenset(c.value_ids.ids), c.price) for c in configs)

    def _cotizador_find_config(self, value_ids):
        """Busca la configuración de esta máquina con exactamente esos valores.

        @param value_ids Ids de product.attribute.value.
        @return sembradora.config.rel (con sudo), o vacío si no existe.
        """
        self.ensure_one()
        value_ids = frozenset(value_ids)
        for config_id, config_values, _price in self._cotizador_config_index(self.id):
            if config_values == value_ids:
                return self.env['sembradora.config.rel'].sudo().browse(config_id)
        return self.env['sembradora.config.rel']

    def _is_combination_possible(self, combination, parent_combination=None, ignore_no_variant=False):
        """Una combinación (completa o parcial) de una máquina es posible solo si alguna
        configuración de la matriz la contiene. Las máquinas sin matriz y los demás productos
        usan la regla estándar de Odoo.

        @param combination product.template.attribute.value elegidos.
        @param parent_combination Combinación del producto padre (estándar de Odoo).
        @param ignore_no_variant Estándar de Odoo.
        @return True si la combinación es posible.
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
    #  Variantes: una por configuración de la matriz, creadas de antemano
    # -------------------------------------------------------------------------

    def _create_variant_ids(self):
        """Sincroniza las variantes con las combinaciones posibles (estándar de Odoo).

        Con el contexto `cotizador_skip_variants` no hace nada: el importador lo usa para no
        generar variantes mientras crea atributos y configuraciones, y sincroniza al final.

        @return True.
        """
        if self.env.context.get('cotizador_skip_variants'):
            return True
        return super()._create_variant_ids()

    def _cotizador_sync_variants(self):
        """Crea, reactiva o quita las variantes de máquinas para que coincidan con su matriz.

        Con sudo: la matriz la edita el Administrador del Configurador, que no necesariamente
        puede crear productos; la escritura de la configuración ya fue autorizada.
        """
        machines = self.filtered('is_maquina')
        if machines and not self.env.context.get('cotizador_skip_variants'):
            machines.sudo()._create_variant_ids()

    def _filter_combinations_impossible_by_config(self, combination_tuples, ignore_no_variant=False):
        """Para una máquina con matriz, solo son posibles las combinaciones de sus configuraciones.

        Es el filtro que usa Odoo al crear variantes con atributos "Siempre": así cada máquina
        tiene exactamente una variante por configuración, creada al importar o al habilitar la
        combinación, y se archiva o borra al quitarla de la matriz.

        @param combination_tuples Iterable de combinaciones (tuplas de product.template.attribute.value).
        @param ignore_no_variant Estándar de Odoo.
        @return Generador de las combinaciones posibles.
        """
        index = self._cotizador_config_index(self.id) if self.is_maquina else ()
        if index:
            valid = {values for _id, values, _price in index}
            value_of = {ptav.id: ptav.product_attribute_value_id.id
                        for ptav in self.attribute_line_ids.product_template_value_ids}
            combination_tuples = (
                combination for combination in combination_tuples
                if frozenset(value_of.get(ptav.id) for ptav in combination) in valid
            )
        return super()._filter_combinations_impossible_by_config(combination_tuples, ignore_no_variant=ignore_no_variant)

    # -------------------------------------------------------------------------
    #  Precios de matriz. Contexto `cotizador_matrix_price = (modelo, id, precio)`: precio de
    #  matriz explícito para ESE registro (la configuración elegida, o el precio del accesorio
    #  en una configuración). Cualquier otro registro del mismo cálculo no lo toma.
    # -------------------------------------------------------------------------

    def _with_matrix_price(self, price):
        """Fija el precio de matriz de esta plantilla para los cálculos de lista de precios.

        @param price Precio en la Moneda del Cotizador del producto.
        @return La plantilla con el contexto `cotizador_matrix_price`.
        """
        self.ensure_one()
        return self.with_context(cotizador_matrix_price=(self._name, self.id, price))

    def _get_product_price_context(self, combination):
        """En la tienda, una combinación de máquina sin variante creada se cotiza con el precio
        de su configuración.

        @param combination product.template.attribute.value elegidos.
        @return dict de contexto de precio (estándar de Odoo, más `cotizador_matrix_price`).
        """
        res = super()._get_product_price_context(combination)
        if self.is_maquina:
            config = self._cotizador_find_config(combination.product_attribute_value_id.ids)
            if config:
                res['cotizador_matrix_price'] = (self._name, self.id, config.price)
        return res

    def _cotizador_convert_matrix_price(self, price, uom=None, currency=None, company=None, date=False):
        """Convierte un precio de matriz a la unidad de medida y moneda pedidas.

        @param price Precio en la Moneda del Cotizador del producto.
        @param uom Unidad de medida destino (opcional).
        @param currency Moneda destino; por defecto la moneda del producto (de la compañía).
        @param company Compañía de la tasa de cambio; por defecto la actual.
        @param date Fecha de la tasa de cambio; por defecto hoy.
        @return Precio convertido, sin redondear.
        """
        self.ensure_one()
        company = company or self.env.company
        if uom:
            price = self.uom_id._compute_price(price, uom)
        return self.cotizador_currency_id._convert(
            price, currency or self.currency_id, company, date or fields.Date.context_today(self), round=False,
        )

    def _cotizador_matrix_list_price(self):
        """Precio de matriz de la plantilla.

        @return El del contexto si es para esta plantilla; si no, para máquinas el de su
                configuración más barata ("desde"); `None` si no hay precio de matriz.
        """
        self.ensure_one()
        model, res_id, price = self.env.context.get('cotizador_matrix_price') or (None, None, None)
        if (model, res_id) == (self._name, self.id):
            return price
        if self.is_maquina:
            prices = [price for _id, _values, price in self._cotizador_config_index(self.id) if price]
            return min(prices) if prices else None
        return None

    def _price_compute(self, price_type, uom=None, currency=None, company=None, date=False):
        """Reemplaza el precio de lista por el de matriz cuando lo hay.

        @param price_type Campo de precio pedido; solo se modifica `list_price`.
        @param uom Unidad de medida destino.
        @param currency Moneda destino.
        @param company Compañía de la conversión.
        @param date Fecha de la conversión.
        @return dict {id de plantilla: precio}.
        """
        prices = super()._price_compute(price_type, uom=uom, currency=currency, company=company, date=date)
        if price_type == 'list_price':
            for tmpl in self:
                price = tmpl._cotizador_matrix_list_price()
                if price is not None:
                    prices[tmpl.id] = tmpl._cotizador_convert_matrix_price(price, uom, currency, company, date)
        return prices


class ProductProduct(models.Model):
    """Variante (`product.product`): mismo cálculo de precio de matriz que la plantilla."""
    _inherit = 'product.product'

    def _with_matrix_price(self, price):
        """Fija el precio de matriz de esta variante para los cálculos de lista de precios.

        @param price Precio en la Moneda del Cotizador del producto.
        @return La variante con el contexto `cotizador_matrix_price`.
        """
        self.ensure_one()
        return self.with_context(cotizador_matrix_price=(self._name, self.id, price))

    def _cotizador_matrix_list_price(self):
        """Precio de matriz de la variante.

        @return El del contexto si es para esta variante; si no, para máquinas el de la
                configuración de su combinación; `None` si no hay precio de matriz.
        """
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
        """Reemplaza el precio de lista por el de matriz cuando lo hay.

        @param price_type Campo de precio pedido; solo se modifica `list_price`.
        @param uom Unidad de medida destino.
        @param currency Moneda destino.
        @param company Compañía de la conversión.
        @param date Fecha de la conversión.
        @return dict {id de variante: precio}.
        """
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
    """Regla de *Descripción Paramétrica* (`product.template.description.line`).

    Asocia un texto enriquecido a un conjunto de valores de atributo de una máquina. Ver
    ProductTemplate.get_config_description().
    """
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
        """Sugiere el nombre "valor1 + valor2" si está vacío."""
        if not self.name and self.value_ids:
            self.name = " + ".join(self.value_ids.mapped('name'))
