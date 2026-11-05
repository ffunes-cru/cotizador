"""@file
Matriz de ingeniería: configuraciones válidas de cada máquina y las reglas de sus accesorios.

Una **configuración** (`sembradora.config.rel`) es una combinación completa de valores de
atributo de una máquina (p. ej. Pionera · 16 Líneas · 52 cm) con su precio y sus accesorios
compatibles. Solo las combinaciones que existen en la matriz se pueden cotizar o elegir en la
tienda (product.template._is_combination_possible()).
"""
from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import SQL


def validate_rule_set(lines):
    """Valida la coherencia de reglas y equipamiento estándar de UNA configuración.

    La usan el importador (sobre el CSV, antes de escribir) y la restricción
    SembradoraConfigRel._check_accessories(), así las dos aplican exactamente lo mismo:

    - un miembro de un grupo de opción única no tiene otras reglas;
    - cada grupo de opción única tiene exactamente un ESTANDAR;
    - un grupo de exclusión tiene como máximo un ESTANDAR;
    - un ESTANDAR de un grupo de inclusión tiene su habilitante también ESTANDAR (o es el habilitante).

    @param lines Iterable de dicts `{'name', 'is_standard', 'is_trigger', 'rules'}`, donde
           `rules` es una lista de tuplas `(clave, tipo, nombre)`; `clave` identifica el grupo
           (id de la regla o `(nombre, tipo)` en el CSV) y `tipo` es `exclusion`, `inclusion` o `choice`.
    @return Lista de mensajes de error; vacía si el conjunto es coherente.
    """
    lines = list(lines)
    errors = []
    groups = {}
    for line in lines:
        rule_types = {rtype for _key, rtype, _name in line['rules']}
        if 'choice' in rule_types and len(line['rules']) > 1:
            errors.append(
                f"'{line['name']}' pertenece a un grupo de opción única (:u) y no puede tener otras reglas."
            )
        for key, rtype, name in line['rules']:
            groups.setdefault(key, (rtype, name, []))[2].append(line)

    for rtype, name, members in groups.values():
        standards = [m for m in members if m['is_standard']]
        if rtype == 'choice' and len(standards) != 1:
            errors.append(
                f"El grupo de opción única '{name}' debe tener exactamente un accesorio ESTANDAR "
                f"(tiene {len(standards)})."
            )
        elif rtype == 'exclusion' and len(standards) > 1:
            errors.append(
                f"El grupo de exclusión '{name}' tiene más de un accesorio ESTANDAR: "
                f"{', '.join(m['name'] for m in standards)}. Use un grupo de opción única (:u)."
            )
        elif rtype == 'inclusion':
            trigger_is_standard = any(m['is_trigger'] and m['is_standard'] for m in members)
            for member in standards:
                if not member['is_trigger'] and not trigger_is_standard:
                    errors.append(
                        f"'{member['name']}' es ESTANDAR pero depende del grupo de inclusión '{name}', "
                        f"cuyo accesorio habilitante (:it) no es ESTANDAR."
                    )
    return errors


class SembradoraConfigRel(models.Model):
    """Configuración válida de una máquina (`sembradora.config.rel`).

    - `value_ids`: la combinación completa de valores de atributo (única por modelo).
    - `price`: precio de la máquina en la Moneda del Cotizador del modelo.
    - `accessory_line_ids`: accesorios compatibles, con su precio en esta configuración.
    - `ext_id`: código externo (ID del CSV o código de ingeniería de Teamcenter).

    Toda escritura de modelo, combinación o precio invalida el índice en caché
    product.template._cotizador_config_index().
    """
    _name = 'sembradora.config.rel'
    _description = 'Matriz de Configuraciones Permitidas'

    ext_id = fields.Char(string='ID Externo', readonly=False, index=True)
    modelo_id = fields.Many2one('product.template', string='Modelo', required=True,
                                domain=[('is_maquina', '=', True)])
    # Combinación completa de valores de atributo de esta configuración
    value_ids = fields.Many2many('product.attribute.value', string='Combinación Permitida')

    # Relación 1:N con accesorios (cada uno con su precio en esta configuración)
    accessory_line_ids = fields.One2many(
        'sembradora.config.accessory.line',
        'config_id',
        string='Accesorios con Precio')

    currency_id = fields.Many2one(related='modelo_id.cotizador_currency_id', string='Moneda')
    price = fields.Monetary(string="Precio de Configuración",
                            help="En la Moneda del Cotizador del modelo.")
    description = fields.Html(
        string="Descripción",
        compute="_compute_description",
        store=True,
        readonly=False,
        help="Descripción detallada de la configuración, calculada con las reglas de Descripción Paramétrica del modelo."
    )

    name = fields.Char(string="Configuración", compute="_compute_name", store=True)

    @api.depends(
        'modelo_id.description_line_ids.value_ids',
        'modelo_id.description_line_ids.sequence',
        'modelo_id.description_line_ids.description',
        'modelo_id.description_default',
        'value_ids'
    )
    def _compute_description(self):
        """Descripción según las reglas de *Descripción Paramétrica* del modelo.

        Si ninguna regla aplica se conserva la descripción existente (es editable a mano).
        """
        for reg in self:
            if reg.modelo_id:
                desc = reg.modelo_id.get_config_description(reg.value_ids)
                if desc:
                    reg.description = desc
                elif not reg.description:
                    reg.description = ''
            elif not reg.description:
                reg.description = ''

    @api.depends('modelo_id', 'value_ids')
    def _compute_name(self):
        """Nombre visible: "Modelo: valor1, valor2, …"."""
        for reg in self:
            attrs = ", ".join(reg.value_ids.mapped('name'))
            reg.name = f"{reg.modelo_id.name}: {attrs}"

    @api.model_create_multi
    def create(self, vals_list):
        """Crea configuraciones, invalida el índice en caché y crea sus variantes.

        @param vals_list Lista de diccionarios de valores.
        @return Las configuraciones creadas.
        """
        self.env.registry.clear_cache()
        configs = super().create(vals_list)
        configs.modelo_id._cotizador_sync_variants()
        return configs

    def write(self, vals):
        """Escribe; si cambian modelo, combinación o precio invalida el índice en caché, y si
        cambian modelo o combinación sincroniza las variantes.

        @param vals Valores a escribir.
        @return True.
        """
        if {'modelo_id', 'value_ids', 'price'} & vals.keys():
            self.env.registry.clear_cache()
        templates = self.modelo_id
        res = super().write(vals)
        if {'modelo_id', 'value_ids'} & vals.keys():
            (templates | self.modelo_id)._cotizador_sync_variants()
        return res

    def unlink(self):
        """Borra configuraciones (y sus líneas de accesorio), invalida el índice en caché y
        quita sus variantes (Odoo las archiva si ya se usaron en ventas).

        @return True.
        """
        self.env.registry.clear_cache()
        templates = self.modelo_id
        res = super().unlink()
        templates._cotizador_sync_variants()
        return res

    @api.constrains('modelo_id', 'value_ids')
    def _check_complete_combination(self):
        """Una configuración tiene exactamente un valor por cada atributo de su máquina.

        Es lo que necesita una variante: sin un valor por atributo no puede existir.

        @throws ValidationError Si falta un atributo, sobra uno que la máquina no tiene o hay
                dos valores del mismo atributo.
        """
        for config in self:
            template_attributes = config.modelo_id.attribute_line_ids.attribute_id
            attributes = config.value_ids.attribute_id
            if attributes != template_attributes or len(config.value_ids) != len(attributes):
                missing = template_attributes - attributes
                raise ValidationError(self.env._(
                    "%(config)s: la combinación debe tener un valor de cada atributo de %(modelo)s%(detail)s.",
                    config=config.name, modelo=config.modelo_id.name,
                    detail=f" (falta {', '.join(missing.mapped('name'))})" if missing else '',
                ))

    @api.constrains('modelo_id', 'value_ids')
    def _check_unique_combination(self):
        """Una combinación de valores aparece una sola vez por modelo.

        Una sola consulta compara las combinaciones en la base (antes era una búsqueda por
        configuración contra todas las de su modelo: cuadrático al importar miles).

        @throws ValidationError Si otra configuración del modelo tiene los mismos valores.
        """
        self.flush_model(['modelo_id', 'value_ids'])
        field = self._fields['value_ids']
        self.env.cr.execute(SQL(
            """
            WITH combos AS (
                SELECT c.id, c.modelo_id, array_agg(r.%(value)s ORDER BY r.%(value)s) AS vals
                  FROM sembradora_config_rel c
                  JOIN %(rel)s r ON r.%(config)s = c.id
                 WHERE c.modelo_id = ANY(%(models)s)
                 GROUP BY c.id, c.modelo_id
            )
            SELECT a.id, b.id
              FROM combos a
              JOIN combos b ON b.modelo_id = a.modelo_id AND b.vals = a.vals AND b.id <> a.id
             WHERE a.id = ANY(%(ids)s)
             LIMIT 1
            """,
            rel=SQL.identifier(field.relation), config=SQL.identifier(field.column1),
            value=SQL.identifier(field.column2), models=self.modelo_id.ids, ids=self.ids,
        ))
        row = self.env.cr.fetchone()
        if row:
            config, duplicate = self.browse(row[0]), self.browse(row[1])
            raise ValidationError(self.env._(
                "Ya existe una configuración de %(modelo)s con la misma combinación (%(other)s).",
                modelo=config.modelo_id.name, other=duplicate.ext_id or duplicate.name,
            ))

    @api.constrains('modelo_id')
    def _check_accessories_modelo(self):
        """Al cambiar el modelo, los accesorios deben seguir siendo de ese modelo.

        @throws ValidationError Ver SembradoraConfigAccessoryLine._check_product_modelo().
        """
        self.accessory_line_ids._check_product_modelo()

    @api.constrains('accessory_line_ids', 'value_ids')
    def _check_accessories(self):
        """Reglas coherentes (validate_rule_set()) y, para cada accesorio de cantidad dinámica,
        un valor del atributo de cantidad en la combinación.

        @throws ValidationError Con todos los errores de la configuración juntos.
        """
        for config in self:
            errors = validate_rule_set(config._rule_set_lines())
            config_attrs = config.value_ids.attribute_id
            for line in config.accessory_line_ids:
                qty_attribute = line.product_id.categ_id.cotizador_qty_attribute_id
                if qty_attribute and not line.quantity and qty_attribute not in config_attrs:
                    errors.append(
                        f"'{line.product_id.display_name}' se cotiza por '{qty_attribute.name}', "
                        f"pero la configuración no tiene valor para ese atributo."
                    )
            if errors:
                raise ValidationError(f"{config.name}:\n" + "\n".join(errors))

    def _rule_set_lines(self):
        """Convierte las líneas de accesorio al formato de validate_rule_set().

        @return Lista de dicts `{'name', 'is_standard', 'is_trigger', 'rules'}`.
        """
        self.ensure_one()
        return [{
            'name': line.product_id.display_name,
            'is_standard': line.is_standard,
            'is_trigger': line.is_trigger,
            'rules': [(rule.id, rule.rule_type, rule.name) for rule in line.rule_ids],
        } for line in self.accessory_line_ids]

    # -------------------------------------------------------------------------
    #  Lógica compartida por el configurador OWL, la solicitud web y el CRM
    # -------------------------------------------------------------------------

    def _get_accessory_offer(self):
        """Oferta de accesorios de la configuración: cantidad y precio de matriz de cada uno.

        Cantidad, en este orden:
          1. `quantity` explícita (> 0) de la línea;
          2. si la categoría del accesorio tiene *Atributo de Cantidad* (lo fija el importador
             desde `Calc_param`): el `cotizador_qty` del valor de ese atributo en la combinación;
          3. si no, 1.

        Precio unitario: el de la línea, en la Moneda del Cotizador del accesorio (0 = sin cargo).
        Todavía no pasa por la lista de precios: eso lo hace
        sale.order._cotizador_accessory_price().

        @return Lista de dicts, uno por línea de accesorio, con: `line`, `product`, `quantity`,
                `price_unit`, `subtotal`, `is_standard`, `selected` (= estándar), `is_trigger`,
                `choice_rule` (la regla de opción única, o vacío) e `is_inclusion_locked`
                (miembro no habilitante de una inclusión: arranca bloqueado).
        @throws UserError Si la categoría pide un atributo de cantidad que la combinación no tiene.
        """
        self.ensure_one()
        value_by_attr = {v.attribute_id: v for v in self.value_ids}
        offer = []
        for line in self.accessory_line_ids:
            product = line.product_id
            qty_attribute = product.categ_id.cotizador_qty_attribute_id
            if line.quantity > 0:
                quantity = line.quantity
            elif qty_attribute:
                if qty_attribute not in value_by_attr:
                    # Solo si la categoría cambió de atributo después de validar la configuración
                    raise UserError(self.env._(
                        "'%(acc)s' se cotiza por '%(attr)s', pero la configuración %(config)s no tiene ese atributo. "
                        "Revise el Atributo de Cantidad de la categoría '%(categ)s'.",
                        acc=product.display_name, attr=qty_attribute.name, config=self.name,
                        categ=product.categ_id.complete_name,
                    ))
                quantity = value_by_attr[qty_attribute].cotizador_qty
            else:
                quantity = 1.0
            price_unit = line.price
            offer.append({
                'line': line,
                'product': product,
                'quantity': quantity,
                'price_unit': round(price_unit, 2),
                'subtotal': round(price_unit * quantity, 2),
                'is_standard': line.is_standard,
                'selected': line.is_standard,
                'is_trigger': line.is_trigger,
                'choice_rule': line.rule_ids.filtered(lambda r: r.rule_type == 'choice'),
                # Un accesorio de una regla de inclusión que no es trigger empieza bloqueado
                'is_inclusion_locked': any(
                    r.rule_type == 'inclusion' for r in line.rule_ids
                ) and not line.is_trigger,
            })
        return offer

    def _get_default_accessory_lines(self):
        """Equipamiento estándar: las líneas que arrancan seleccionadas.

        Es una selección válida por construcción (restricción _check_accessories()).

        @return sembradora.config.accessory.line con `is_standard`.
        """
        self.ensure_one()
        return self.accessory_line_ids.filtered('is_standard')

    def _check_accessory_selection(self, acc_lines):
        """Valida una selección de accesorios contra las reglas de la configuración.

        Es la validación del servidor: el configurador OWL aplica las mismas reglas en el
        navegador, pero nunca se confía en él.

        @param acc_lines sembradora.config.accessory.line elegidas.
        @throws UserError Si hay líneas de otra configuración, un grupo de opción única sin
                exactamente una elegida, dos elegidas de una exclusión o un miembro de una
                inclusión sin su habilitante.
        """
        self.ensure_one()
        foreign = acc_lines - self.accessory_line_ids
        if foreign:
            raise UserError(self.env._(
                "Los accesorios %s no pertenecen a la configuración seleccionada.",
                ', '.join(foreign.mapped('product_id.name')),
            ))
        for rule in self.accessory_line_ids.rule_ids.filtered(lambda r: r.rule_type == 'choice'):
            chosen = acc_lines.filtered(lambda l: rule in l.rule_ids)
            if len(chosen) != 1:
                raise UserError(self.env._(
                    "Debe elegir exactamente una opción de '%(rule)s' (eligió %(count)s).",
                    rule=rule.name, count=len(chosen),
                ))
        for rule in acc_lines.rule_ids:
            in_rule = acc_lines.filtered(lambda l: rule in l.rule_ids)
            if rule.rule_type == 'exclusion' and len(in_rule) > 1:
                raise UserError(self.env._(
                    "Configuración inválida: ha seleccionado más de un accesorio del grupo de "
                    "exclusión '%(rule)s': %(accs)s.",
                    rule=rule.name, accs=', '.join(in_rule.mapped('product_id.name')),
                ))
            if rule.rule_type == 'inclusion' and not in_rule.filtered('is_trigger'):
                raise UserError(self.env._(
                    "Los accesorios %(accs)s requieren seleccionar el accesorio habilitante de '%(rule)s'.",
                    rule=rule.name, accs=', '.join(in_rule.mapped('product_id.name')),
                ))

    def _get_variant(self):
        """Variante (`product.product`) de la máquina para esta configuración.

        Las variantes se crean con la matriz (atributos "Siempre": una por configuración, ver
        product.template._filter_combinations_impossible_by_config()). Si falta, se vuelven a
        sincronizar las variantes de la máquina una vez (p. ej. una base anterior a este criterio).

        @return product.product de la configuración.
        @throws UserError Si la máquina no tiene variante para la combinación ni después de sincronizar.
        """
        self.ensure_one()
        tmpl = self.modelo_id

        def find():
            """@return La variante activa de la combinación, o vacío."""
            ptavs = self.env['product.template.attribute.value'].search([
                ('product_tmpl_id', '=', tmpl.id),
                ('product_attribute_value_id', 'in', self.value_ids.ids),
            ])
            return tmpl._get_variant_for_combination(ptavs)

        variant = find()
        if not variant:
            tmpl._cotizador_sync_variants()
            variant = find()
        if not variant:
            raise UserError(self.env._(
                "La máquina %(modelo)s no tiene variante para %(config)s. Revise que sus atributos estén en modo "
                "'Siempre' y que la combinación esté completa.",
                modelo=tmpl.name, config=self.name,
            ))
        return variant

    def _sync_variant_code(self):
        """Copia `ext_id` a la referencia interna (`default_code`) de la variante, si ya existe."""
        for config in self.filtered('ext_id'):
            ptavs = self.env['product.template.attribute.value'].search([
                ('product_tmpl_id', '=', config.modelo_id.id),
                ('product_attribute_value_id', 'in', config.value_ids.ids),
            ])
            variant = config.modelo_id._get_variant_for_combination(ptavs)
            if variant:
                variant.sudo().default_code = config.ext_id

    def _get_variant_description(self):
        """Descripción de la línea de la máquina en la cotización.

        @return Texto: el nombre del modelo y una línea "• Atributo: valor" por cada atributo
                con *Mostrar en Descripción*, en el orden de los atributos de la plantilla.
        """
        self.ensure_one()
        attr_order = {
            ptal.attribute_id.id: (ptal.sequence, ptal.id) for ptal in self.modelo_id.attribute_line_ids
        }
        values = self.value_ids.sorted(lambda v: attr_order.get(v.attribute_id.id, (999, v.attribute_id.id)))
        lines = [
            f"• {v.attribute_id.name}: {v.name}"
            for v in values
            if v.attribute_id.show_in_description
        ]
        return "\n".join([self.modelo_id.name, *lines])
