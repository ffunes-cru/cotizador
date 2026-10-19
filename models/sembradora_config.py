from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

MANAGER_GROUP = 'cotizador.group_cotizador_manager'


def check_configurator_manager(env):
    """Studio, Asistente de Precios y demás herramientas de la matriz: solo administradores."""
    if not env.user.has_group(MANAGER_GROUP):
        raise AccessError(env._("Solo el grupo Administrador del Configurador puede usar esta herramienta."))


def validate_rule_set(lines):
    """
    Valida la coherencia de reglas y equipamiento estándar de UNA configuración.
    La usan el importador (sobre el CSV, antes de escribir) y la restricción del modelo.

    :param lines: iterable de dicts ``{'name', 'is_standard', 'is_trigger', 'rules'}`` donde
        ``rules`` es una lista de tuplas ``(clave, tipo, nombre)`` con tipo en
        ``exclusion`` / ``inclusion`` / ``choice``.
    :return: lista de mensajes de error (vacía si es coherente).
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

    price = fields.Float(string="Precio de Configuración",
                         help="En la moneda de la matriz de la compañía (Ajustes › Ventas).")
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
        for reg in self:
            # .mapped('name') extrae todos los nombres de los valores y los une con comas
            attrs = ", ".join(reg.value_ids.mapped('name'))
            reg.name = f"{reg.modelo_id.name}: {attrs}"

    # El índice cacheado de configuraciones (product.template._cotizador_config_index)
    # depende de modelo, combinación y precio.
    @api.model_create_multi
    def create(self, vals_list):
        self.env.registry.clear_cache()
        return super().create(vals_list)

    def write(self, vals):
        if {'modelo_id', 'value_ids', 'price'} & vals.keys():
            self.env.registry.clear_cache()
        return super().write(vals)

    def unlink(self):
        self.env.registry.clear_cache()
        return super().unlink()

    @api.constrains('modelo_id', 'value_ids')
    def _check_unique_combination(self):
        for config in self:
            duplicate = self.search([
                ('modelo_id', '=', config.modelo_id.id), ('id', '!=', config.id),
            ]).filtered(lambda c: c.value_ids == config.value_ids)
            if duplicate:
                raise ValidationError(self.env._(
                    "Ya existe una configuración de %(modelo)s con la misma combinación (%(other)s).",
                    modelo=config.modelo_id.name, other=duplicate[0].ext_id or duplicate[0].name,
                ))

    @api.constrains('accessory_line_ids', 'value_ids')
    def _check_accessories(self):
        """Reglas coherentes y, para accesorios de cantidad dinámica, el atributo presente."""
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
        """Líneas de accesorio en el formato de validate_rule_set."""
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
        """
        Calcula cantidad y precio unitario (en moneda de la matriz) de cada accesorio.

        Cantidad:
          1. ``quantity`` explícita (> 0) en la línea de accesorio.
          2. Si la categoría del accesorio tiene *Atributo de Cantidad* (lo fija el importador a
             partir de ``Calc_param``): la *Cantidad* guardada en el valor de ese atributo de la
             configuración (``product.attribute.value.cotizador_qty``).
          3. Resto → 1.

        Precio unitario: el de la línea (matriz por configuración); si es 0, el de lista del producto.

        :return: list of dicts, uno por ``sembradora.config.accessory.line``.
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
                quantity = value_by_attr[qty_attribute].cotizador_qty
            else:
                quantity = 1.0
            price_unit = line.price or product.list_price
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
        """Accesorios que arrancan seleccionados: el equipamiento estándar (coherente por restricción)."""
        self.ensure_one()
        return self.accessory_line_ids.filtered('is_standard')

    def _check_accessory_selection(self, acc_lines):
        """Valida una selección de accesorios contra las reglas de exclusión/inclusión."""
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

    def _get_or_create_variant(self):
        """Devuelve (o crea) la variante product.product que corresponde a esta configuración."""
        self.ensure_one()
        tmpl = self.modelo_id
        ptavs = self.env['product.template.attribute.value'].search([
            ('product_tmpl_id', '=', tmpl.id),
            ('product_attribute_value_id', 'in', self.value_ids.ids),
        ])
        variant = tmpl._get_variant_for_combination(ptavs) or tmpl._create_product_variant(ptavs)
        if not variant:
            # Atributos en modo 'always' cuya variante no fue generada (o combinación excluida
            # en la plantilla): se crea igual porque la matriz de ingeniería es la fuente de verdad.
            # sudo: igual que _create_product_variant, los vendedores no crean productos.
            variant = self.env['product.product'].sudo().create({
                'product_tmpl_id': tmpl.id,
                'product_template_attribute_value_ids': [(6, 0, ptavs._without_no_variant_attributes().ids)],
            })
        return variant

    def _sync_variant_code(self):
        """Copia ext_id (código de ingeniería) a la referencia interna de la variante, si existe."""
        for config in self.filtered('ext_id'):
            ptavs = self.env['product.template.attribute.value'].search([
                ('product_tmpl_id', '=', config.modelo_id.id),
                ('product_attribute_value_id', 'in', config.value_ids.ids),
            ])
            variant = config.modelo_id._get_variant_for_combination(ptavs)
            if variant:
                variant.sudo().default_code = config.ext_id

    def _get_variant_description(self):
        """Texto de la línea de la máquina: modelo + atributos visibles en descripción."""
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
