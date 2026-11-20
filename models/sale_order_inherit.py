"""@file
Cotización (`sale.order`) y sus líneas: el núcleo comercial del cotizador.

- **Alta de una máquina configurada** (_cotizador_add_configuration()): secciones Máquina,
  Equipamiento y Accesorios, con precios de matriz pasados por la lista de precios de la orden.
- **Cascada de totales** (_compute_totales_cotizador()): SUB TOTAL → IVA → TOTAL → descuentos →
  usados → SALDO A CANCELAR.
- **CRM**: crea o actualiza la oportunidad y su ingreso esperado; ganada al confirmar.
- **Portal**: modos de aceptación (estándar, habilitada por el vendedor, solo el vendedor).
- **BCRA**: alerta al elegir cliente y botón *Situación BCRA*.
- **Impresión**: reporte con hoja de planes de pago; el menú *Imprimir* ofrece todos los planes,
  los elegidos o ninguno (un reporte por modo).
"""
from markupsafe import Markup

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .bcra_service import SITUACION_LABELS, consultar_bcra_completo, format_pesos

## Campos de línea que cambian el neto: al escribirlos se recalculan descuentos y plan de pago.
AFFECTS_ADJUSTMENTS = {
    'price_unit', 'product_uom_qty', 'discount', 'tax_ids', 'product_id', 'cotizador_pct',
    'display_type', 'is_descuento', 'is_plan_pago', 'is_equipo_usado', 'sequence',
}

## Campos de línea que cambian qué máquina o accesorio se cotiza: al escribirlos se validan las configuraciones.
AFFECTS_CONFIG = {'product_id', 'display_type', 'cotizador_section', 'sequence', 'order_id'}

## Texto por defecto de las condiciones generales (Ajustes › Ventas lo reemplaza).
DEFAULT_CONDICIONES_GENERALES = """Condiciones Generales
Vigencia de esta cotización sujeta a cambios sin previo aviso
Valores expresados en Dólares Americanos, sin IVA
Tipos de Cambio: Banco Nación Argentina, Cotización Billete, Vendedor
Fijación de tipo de cambio: Fecha de efectiva recepción de la cobranza en fábrica y/o acreditación en cuenta de la empresa"""


class SaleOrderInherit(models.Model):
    """Cotización / pedido (`sale.order`) del cotizador."""
    _inherit = 'sale.order'

    # --- Condiciones Generales ---

    def _default_condiciones_generales(self):
        """Condiciones generales configuradas, o DEFAULT_CONDICIONES_GENERALES.

        @return Texto.
        """
        return self.env['ir.config_parameter'].sudo().get_param(
            'cotizador.condiciones_generales_default',
            DEFAULT_CONDICIONES_GENERALES
        )

    condiciones_generales = fields.Text(
        string='Condiciones Generales',
        default=_default_condiciones_generales,
        help='Condiciones comerciales constantes preconfiguradas que se imprimen al pie de la cotización.',
    )

    # --- Planes de Pago a Imprimir ---

    # Arranca vacío: el vendedor tilda los que quiere imprimir (issue #3). Sin ninguno, el PDF va sin
    # hoja de planes.
    plan_pago_line_ids = fields.Many2many(
        'cotizador.plan.pago.template.line',
        'sale_order_cotizador_plan_pago_rel',
        'order_id',
        'plan_line_id',
        string='Planes de Pago a Imprimir',
        help='Planes que van en la hoja de planes de pago del PDF. Sin ninguno, el PDF no lleva esa hoja.',
    )

    # --- Modalidad de Aceptación y Firma en Portal ---

    def _default_portal_confirmation_mode(self):
        """Modo de aceptación configurado (`cotizador.portal_confirmation_mode`).

        @return Clave del modo.
        """
        return self.env['ir.config_parameter'].sudo().get_param(
            'cotizador.portal_confirmation_mode', default='salesman_enables'
        )

    portal_confirmation_mode = fields.Selection(
        selection=[
            ('standard', 'Estándar Odoo'),
            ('salesman_enables', 'Habilitado por el Vendedor'),
            ('salesman_only', 'Solo el Vendedor puede confirmar'),
        ],
        string='Modo de Aceptación Portal',
        default=_default_portal_confirmation_mode,
        required=True,
        tracking=True,
        help='Determina si el cliente puede firmar/aceptar esta cotización desde el portal web o si requiere habilitación del comercial.',
    )
    portal_confirmation_allowed = fields.Boolean(
        string='Firma del Cliente Habilitada',
        default=False,
        tracking=True,
        copy=False,
        help='Si el modo es "Habilitado por el Vendedor", active esta casilla para que el cliente pueda ver el botón "Aceptar y Firmar" en el portal web.',
    )

    # --- Equipo Cotizado (Categoría Máquina) ---
    lider_equipo_id = fields.Many2one(
        'res.users',
        string='Concesionario',
        related='team_id.user_id',
        store=True,
        help='Líder del equipo de ventas del vendedor: el usuario del concesionario. Odoo calcula el equipo '
             'a partir del vendedor, así que cambia solo al cambiar el vendedor.',
    )
    equipo_cotizado_id = fields.Many2one(
        'product.template',
        string='Equipo Cotizado',
        domain="[('is_maquina', '=', True)]",
        compute='_compute_equipo_cotizado_id',
        store=True,
        readonly=False,
        help='Modelo de máquina cotizada (categoría Máquina).',
    )

    def _get_maquina_template(self):
        """Máquina cotizada: la plantilla de la primera línea que es máquina.

        @return product.template, o vacío.
        """
        self.ensure_one()
        return self.order_line.product_id.product_tmpl_id.filtered('is_maquina')[:1]

    @api.depends('order_line.product_id')
    def _compute_equipo_cotizado_id(self):
        """Equipo cotizado = máquina de las líneas; sin máquina se conserva el elegido a mano."""
        for order in self:
            maquina = order._get_maquina_template()
            if maquina:
                order.equipo_cotizado_id = maquina
            elif not order.equipo_cotizado_id:
                order.equipo_cotizado_id = False

    # --- Cascada de totales del cotizador ---
    #
    #   SUB TOTAL (productos, neto)
    #   − descuentos comerciales (sobre el neto, en cascada)
    #   ± plan de pago (sobre el neto con descuentos)
    #   = SUB TOTAL NETO
    #   + IVA (de productos, descuentos y plan: el IVA se calcula sobre el neto con descuentos)
    #   = TOTAL
    #   − usados (medio de pago, sin IVA)
    #   = SALDO A CANCELAR

    amount_subtotal_productos = fields.Monetary(
        string='SUB TOTAL',
        compute='_compute_totales_cotizador',
        currency_field='currency_id',
        store=True,
        help='Neto de las líneas de producto (máquina, accesorios y otros productos), sin impuestos.',
    )
    amount_descuentos = fields.Monetary(
        string='Total Descuentos',
        compute='_compute_totales_cotizador',
        currency_field='currency_id',
        store=True,
        help='Descuentos comerciales sobre el neto (importe negativo).',
    )
    amount_plan_pago = fields.Monetary(
        string='Plan de Pago',
        compute='_compute_totales_cotizador',
        currency_field='currency_id',
        store=True,
        help='Recargo (positivo) o descuento (negativo) del plan de pago, sobre el neto con descuentos.',
    )
    amount_subtotal_neto = fields.Monetary(
        string='SUB TOTAL NETO',
        compute='_compute_totales_cotizador',
        currency_field='currency_id',
        store=True,
        help='SUB TOTAL con descuentos y plan de pago: la base del IVA.',
    )
    amount_iva_productos = fields.Monetary(
        string='IVA',
        compute='_compute_totales_cotizador',
        currency_field='currency_id',
        store=True,
        help='Impuestos de productos, descuentos y plan de pago.',
    )
    amount_total_base = fields.Monetary(
        string='TOTAL',
        compute='_compute_totales_cotizador',
        currency_field='currency_id',
        store=True,
        help='SUB TOTAL NETO + IVA.',
    )
    amount_usados = fields.Monetary(
        string='Medios de pago (Usados)',
        compute='_compute_totales_cotizador',
        currency_field='currency_id',
        store=True,
        help='Equipos usados tomados como parte de pago (importe negativo, sin IVA).',
    )
    amount_saldo_cancelar = fields.Monetary(
        string='SALDO A CANCELAR',
        compute='_compute_totales_cotizador',
        currency_field='currency_id',
        store=True,
        help='TOTAL − usados (nunca menor a 0).',
    )
    descuento_line_ids = fields.One2many(
        'sale.order.line',
        compute='_compute_lineas_especiales',
        string='Descuentos Aplicados',
    )
    usado_line_ids = fields.One2many(
        'sale.order.line',
        compute='_compute_lineas_especiales',
        string='Equipos Usados Tomados',
    )

    @api.depends(
        'order_line.price_subtotal', 'order_line.display_type', 'amount_tax',
        'order_line.is_descuento', 'order_line.is_equipo_usado', 'order_line.is_plan_pago',
    )
    def _compute_totales_cotizador(self):
        """Cascada de totales del cotizador (la del formulario, el portal y el reporte).

        Ver el comentario de la sección. Los importes de descuentos y usados quedan negativos.
        El IVA es el impuesto total de Odoo (`amount_tax`, con su redondeo): los usados no llevan
        impuestos, así que es exactamente el IVA de productos, descuentos y plan, y el SALDO
        coincide con el total de la orden y de la factura.
        """
        for order in self:
            lines = order.order_line.filtered(lambda l: not l.display_type)
            products = lines.filtered(lambda l: l._is_cotizador_product_line())
            discounts = lines.filtered('is_descuento')
            plans = lines.filtered('is_plan_pago')
            used = lines.filtered('is_equipo_usado')
            subtotal = sum(products.mapped('price_subtotal'))
            descuentos = sum(discounts.mapped('price_subtotal'))
            plan = sum(plans.mapped('price_subtotal'))
            neto = subtotal + descuentos + plan
            iva = order.amount_tax
            usados = sum(used.mapped('price_subtotal'))
            total = neto + iva
            round_ = order.currency_id.round
            order.amount_subtotal_productos = round_(subtotal)
            order.amount_descuentos = round_(descuentos)
            order.amount_plan_pago = round_(plan)
            order.amount_subtotal_neto = round_(neto)
            order.amount_iva_productos = round_(iva)
            order.amount_total_base = round_(total)
            order.amount_usados = round_(usados)
            order.amount_saldo_cancelar = max(0.0, round_(total + usados))

    def _cotizador_tax_groups(self, include_discounts=True):
        """Neto de la cotización agrupado por impuestos: la base de descuentos y planes.

        Un descuento o un plan se reparte en una línea por grupo de impuestos, así el IVA de
        cada alícuota se calcula sobre su propio neto con descuento.

        @param include_discounts Si True, resta del neto de cada grupo los descuentos ya cargados.
        @return dict {account.tax (recordset del grupo): neto}, solo grupos con neto distinto de 0.
        """
        self.ensure_one()
        groups = {}
        lines = self.order_line.filtered(lambda l: not l.display_type)
        relevant = lines.filtered(lambda l: l._is_cotizador_product_line())
        if include_discounts:
            relevant |= lines.filtered('is_descuento')
        for line in relevant:
            groups[line.tax_ids] = groups.get(line.tax_ids, 0.0) + line.price_subtotal
        return {taxes: net for taxes, net in groups.items() if not self.currency_id.is_zero(net)}

    def _cotizador_update_adjustments(self):
        """Recalcula los descuentos en porcentaje y el plan de pago sobre el neto actual.

        Se llama cada vez que cambian las líneas (sale.order.line create / write / unlink), así
        nunca quedan importes viejos. Orden: los descuentos en cascada (por secuencia), cada uno
        sobre el neto de su grupo de impuestos después de los anteriores; al final el plan de
        pago, sobre el neto con todos los descuentos. Los descuentos de monto fijo no cambian.
        Solo en cotizaciones (borrador o enviada).
        """
        for order in self.filtered(lambda o: o.state in ('draft', 'sent')):
            bases = {}
            for line in order.order_line.filtered(lambda l: not l.display_type and l._is_cotizador_product_line()):
                bases[line.tax_ids] = bases.get(line.tax_ids, 0.0) + line.price_subtotal
            adjustments = order.order_line.filtered(
                lambda l: not l.display_type and (l.is_descuento or l.is_plan_pago)
            ).sorted(lambda l: (l.is_plan_pago, l.sequence, l.id))
            for line in adjustments:
                base = bases.get(line.tax_ids, 0.0)
                if line.cotizador_pct:
                    sign = 1 if line.is_plan_pago else -1
                    price = order.currency_id.round(base * sign * line.cotizador_pct / 100)
                    if order.currency_id.compare_amounts(price, line.price_unit):
                        line.with_context(cotizador_skip_adjustments=True).price_unit = price
                bases[line.tax_ids] = base + line.price_unit * line.product_uom_qty

    def _recompute_prices(self):
        """*Actualizar precios*: además recalcula descuentos en porcentaje y plan de pago.

        Las líneas de descuento, usado y plan no toman precio de producto (ver
        sale.order.line._compute_price_unit()); el plan y los descuentos en porcentaje se
        recalculan sobre los precios nuevos.
        """
        super()._recompute_prices()
        self._cotizador_update_adjustments()

    def _cotizador_simulate_plan(self, pct):
        """Saldo a cancelar que tendría la cotización con un plan de pago de `pct` %.

        Lo usan la hoja de planes del reporte y el asistente de selección: aplica el porcentaje
        sobre el neto con descuentos de cada grupo de impuestos (sin el plan actual), le suma el
        IVA y resta los usados.

        @param pct Porcentaje del plan (negativo = descuento, positivo = recargo).
        @return Saldo estimado en la moneda de la cotización.
        """
        self.ensure_one()
        total = 0.0
        for taxes, net in self._cotizador_tax_groups().items():
            net_with_plan = net * (1 + pct / 100)
            total += taxes.compute_all(net_with_plan, currency=self.currency_id, handle_price_include=False)['total_included'] if taxes else net_with_plan
        return max(0.0, self.currency_id.round(total + self.amount_usados))

    cotizador_muestra_cantidad = fields.Boolean(
        string='Mostrar Cantidad',
        compute='_compute_cotizador_muestra_cantidad',
        help='Alguna línea tiene una cantidad distinta de 1 (p. ej. un accesorio por línea): solo '
             'entonces la lista de líneas muestra la columna Cantidad.',
    )

    @api.depends('order_line.product_uom_qty', 'order_line.display_type')
    def _compute_cotizador_muestra_cantidad(self):
        """La columna *Cantidad* se ve solo si alguna línea de producto no tiene cantidad 1."""
        for order in self:
            order.cotizador_muestra_cantidad = any(
                not line.display_type and line.product_uom_qty != 1 for line in order.order_line)

    @api.depends('order_line.is_descuento', 'order_line.is_equipo_usado')
    def _compute_lineas_especiales(self):
        """Listas de las líneas de descuento y de usados (para las pestañas de la vista)."""
        for order in self:
            order.descuento_line_ids = order.order_line.filtered(lambda l: l.is_descuento)
            order.usado_line_ids = order.order_line.filtered(lambda l: l.is_equipo_usado)

    # --- BCRA Service ---

    @api.onchange('partner_id')
    def _onchange_partner_id_bcra(self):
        """Al elegir un cliente con CUIT, consulta el BCRA y avisa si tiene deudas.

        Si la consulta falla no avisa nada (el detalle está en el botón *Situación BCRA*).

        @return Aviso de Odoo (`{'warning': {...}}`) si tiene deudas; si no, None.
        """
        if self.partner_id and self.partner_id.vat:
            data = consultar_bcra_completo(self.partner_id.vat)
            if data and data.get('success') and data.get('tiene_deuda') and data.get('monto_total_deuda', 0.0) > 0:
                monto_total = data.get('monto_total_deuda', 0.0)
                peor_sit = data.get('peor_situacion') or '1'
                monto_fmt = format_pesos(monto_total)
                peor_desc = SITUACION_LABELS.get(int(peor_sit), f"Situación {peor_sit}")
                return {
                    'warning': {
                        'title': _("⚠️ Alerta Crediticia - Central de Deudores BCRA"),
                        'message': _(
                            "El cliente '%s' (CUIT: %s) registra deudas informadas en el BCRA por un monto total de $ %s (%s).\n\n"
                            "Puede consultar el detalle completo haciendo clic en el botón 'Situación BCRA'."
                        ) % (self.partner_id.name, self.partner_id.vat or '', monto_fmt, peor_desc)
                    }
                }

    def action_ver_bcra_wizard(self):
        """Botón *Situación BCRA*: consulta el BCRA y abre el informe.

        @return Acción que abre cotizador.bcra.wizard.
        @throws UserError Si no hay cliente, no tiene CUIT o la consulta falla.
        """
        self.ensure_one()
        if not self.partner_id:
            raise UserError(_("Por favor seleccione primero un cliente."))
        if not self.partner_id.vat:
            raise UserError(_("El cliente seleccionado '%s' no tiene CUIT configurado.") % self.partner_id.name)

        data = consultar_bcra_completo(self.partner_id.vat)
        if not data or not data.get('success'):
            raise UserError(data.get('error', _('No se pudo obtener información desde la API del BCRA.')))

        deuda_commands = []
        for d in data.get('deudas', []):
            deuda_commands.append((0, 0, {
                'periodo': d.get('periodo'),
                'entidad': d.get('entidad'),
                'situacion': d.get('situacion'),
                'monto': d.get('monto'),
                'dias_atraso': d.get('dias_atraso'),
                'observaciones': d.get('observaciones'),
            }))

        cheque_commands = []
        for ch in data.get('cheques_rechazados', []):
            cheque_commands.append((0, 0, {
                'nro_cheque': ch.get('nro_cheque'),
                'fecha_rechazo': ch.get('fecha_rechazo'),
                'monto': ch.get('monto'),
                'causal': ch.get('causal'),
                'estado': ch.get('estado'),
            }))

        wizard = self.env['cotizador.bcra.wizard'].create({
            'partner_id': self.partner_id.id,
            'cuit': data.get('cuit') or self.partner_id.vat,
            'denominacion': data.get('denominacion') or self.partner_id.name,
            'tiene_deuda': data.get('tiene_deuda', False),
            'peor_situacion': data.get('peor_situacion') or ('1' if data.get('deudas') else False),
            'monto_total': data.get('monto_total_deuda', 0.0),
            'alerta_mensaje': data.get('mensaje_resumen', ''),
            'deuda_ids': deuda_commands,
            'cheque_ids': cheque_commands,
        })

        return {
            'name': _('Situación Crediticia BCRA - %s') % (self.partner_id.name),
            'type': 'ir.actions.act_window',
            'res_model': 'cotizador.bcra.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    # --- Sincronización Automática con Oportunidades del CRM ---

    def _sync_with_crm(self):
        """Mantiene la oportunidad del CRM al día con la cotización.

        - Cotización de una máquina sin oportunidad: crea una en la primera etapa no ganada.
        - Con oportunidad: copia cliente, vendedor, concesionario (equipo) y su líder, y recalcula el
          ingreso esperado con crm.lead._sync_expected_revenue_from_orders() (convertido a la moneda
          de la compañía, tomando la última cotización o pedido de la oportunidad).

        Corre con sudo: la oportunidad acompaña a la cotización, que el usuario ya pudo modificar. Sin
        sudo, un supervisor de zona que asigna su cotización a un concesionario no podría actualizar la
        oportunidad, que en ese momento deja de ser suya.

        Se omite con el contexto `skip_crm_sync` (la solicitud web arma la oportunidad aparte).
        """
        if self.env.context.get('skip_crm_sync'):
            return
        for order in self.sudo().filtered('partner_id'):
            lead = order.opportunity_id
            if not lead:
                maquina = order.equipo_cotizado_id or order._get_maquina_template()
                if not maquina:
                    continue
                initial_stage = self.env['crm.stage'].search([('is_won', '=', False)], order='sequence asc', limit=1)
                lead = order.env['crm.lead'].create({
                    'name': f"Cotización {order.name} - {order.partner_id.name}",
                    'partner_id': order.partner_id.id,
                    'user_id': order.user_id.id or self.env.uid,
                    'team_id': order.team_id.id,
                    'lider_equipo_id': order.team_id.user_id.id,
                    'equipo_cotizado_id': maquina.id,
                    'stage_id': initial_stage.id,
                })
                order.opportunity_id = lead
            elif update_vals := order._crm_lead_changes(lead):
                lead.write(update_vals)
            lead._sync_expected_revenue_from_orders()

    def _crm_lead_changes(self, lead):
        """Valores de la oportunidad que difieren de la cotización: cliente, vendedor, concesionario y su líder.

        @param lead crm.lead de la cotización.
        @return dict para `lead.write()` (vacío si no hay cambios).
        """
        self.ensure_one()
        vals = {}
        if lead.partner_id != self.partner_id:
            vals['partner_id'] = self.partner_id.id
        if self.user_id and lead.user_id != self.user_id:
            vals['user_id'] = self.user_id.id
        if self.team_id and lead.team_id != self.team_id:
            vals['team_id'] = self.team_id.id
            vals['lider_equipo_id'] = self.team_id.user_id.id
        elif self.team_id.user_id and not lead.lider_equipo_id:
            vals['lider_equipo_id'] = self.team_id.user_id.id
        return vals

    @api.onchange('equipo_cotizado_id')
    def _onchange_equipo_cotizado_id_pricelist(self):
        """Las cotizaciones de máquinas usan la lista de precios configurada en la compañía."""
        pricelist = self.company_id.cotizador_pricelist_id
        if self.equipo_cotizado_id.is_maquina and pricelist:
            self.pricelist_id = pricelist

    @api.model_create_multi
    def create(self, vals_list):
        """Crea cotizaciones con el modo de aceptación y, si es de máquina, la lista de precios
        de cotizaciones; después valida las configuraciones de sus líneas y sincroniza el CRM.

        @param vals_list Lista de diccionarios de valores.
        @return Las cotizaciones creadas.
        @throws ValidationError Si las líneas tienen una configuración inválida (issue #19).
        """
        for vals in vals_list:
            if not vals.get('portal_confirmation_mode'):
                vals['portal_confirmation_mode'] = self.env['ir.config_parameter'].sudo().get_param(
                    'cotizador.portal_confirmation_mode', default='salesman_enables'
                )
            if vals.get('equipo_cotizado_id') and not vals.get('pricelist_id'):
                equipo = self.env['product.template'].browse(vals['equipo_cotizado_id'])
                company = self.env['res.company'].browse(vals.get('company_id')) or self.env.company
                if equipo.is_maquina and company.cotizador_pricelist_id:
                    vals['pricelist_id'] = company.cotizador_pricelist_id.id
        con_lineas = any(vals.get('order_line') for vals in vals_list)
        orders = super(SaleOrderInherit, self.with_context(cotizador_skip_config_check=True)).create(vals_list)
        orders = orders.with_env(self.env)
        if con_lineas:
            orders._cotizador_check_configuraciones()
        for order in orders:
            order._sync_with_crm()
        orders._cotizador_compartir_cliente()
        return orders

    def write(self, vals):
        """Escribe, valida las configuraciones si cambian las líneas y sincroniza el CRM si cambian líneas,
        estado, cliente, vendedor o concesionario.

        Las líneas se validan una vez, al final: el formulario manda todos los cambios juntos, y en el medio la
        selección puede ser inválida (p. ej. al reemplazar la opción de un grupo de opción única).

        @param vals Valores a escribir.
        @return True.
        @throws ValidationError Si las líneas quedan con una configuración inválida (issue #19).
        """
        res = super(SaleOrderInherit, self.with_context(cotizador_skip_config_check=True)).write(vals)
        if 'order_line' in vals:
            self._cotizador_check_configuraciones()
        if any(f in vals for f in ('order_line', 'state', 'partner_id', 'user_id', 'team_id')):
            self._sync_with_crm()
        if any(f in vals for f in ('partner_id', 'user_id', 'team_id')):
            self._cotizador_compartir_cliente()
        return res

    def _cotizador_compartir_cliente(self):
        """El cliente de cada cotización pasa a ser visible para su concesionario (models/res_partner.py)."""
        for order in self:
            order.partner_id._cotizador_compartir_con(order.team_id)

    def _check_portal_confirmation_editable(self):
        """La firma online solo se habilita o revoca en cotizaciones en modo *Habilitado por el vendedor*.

        La acción está en el menú de acciones del formulario, que se ve en cualquier estado.

        @throws UserError Si la cotización ya es pedido o cancelada, o su modo es otro.
        """
        if self.state not in ('draft', 'sent'):
            raise UserError(_("La firma del cliente solo se habilita o revoca en cotizaciones (borrador o enviada)."))
        if self.portal_confirmation_mode != 'salesman_enables':
            raise UserError(_("Esta cotización no está en modo «Habilitado por el vendedor» "
                              "(pestaña Condiciones y Planes de Pago)."))

    def action_enable_portal_confirmation(self):
        """Acción del vendedor: habilita la aceptación y firma del cliente en el portal (con nota en el chatter).

        @throws UserError Ver _check_portal_confirmation_editable(), o si ya estaba habilitada.
        """
        self.ensure_one()
        self._check_portal_confirmation_editable()
        if self.portal_confirmation_allowed:
            raise UserError(_("La firma del cliente ya está habilitada."))
        self.write({
            'portal_confirmation_allowed': True,
            'require_signature': True,
        })
        self.message_post(
            body=Markup(_("El asesor comercial ha <strong>habilitado</strong> la aceptación y firma online de esta cotización para el cliente en el portal.")),
            message_type='notification',
            subtype_xmlid='mail.mt_note'
        )

    def action_disable_portal_confirmation(self):
        """Acción del vendedor: deshabilita la aceptación y firma del cliente en el portal (con nota en el chatter).

        @throws UserError Ver _check_portal_confirmation_editable(), o si no estaba habilitada.
        """
        self.ensure_one()
        self._check_portal_confirmation_editable()
        if not self.portal_confirmation_allowed:
            raise UserError(_("La firma del cliente no está habilitada."))
        self.write({
            'portal_confirmation_allowed': False,
        })
        self.message_post(
            body=Markup(_("El asesor comercial ha <strong>deshabilitado</strong> la aceptación y firma online de esta cotización en el portal.")),
            message_type='notification',
            subtype_xmlid='mail.mt_note'
        )

    def _has_to_be_signed(self):
        """El portal pide firma solo si el modo de aceptación lo permite.

        @return False en modo "Solo el vendedor" o "Habilitado por el vendedor" sin habilitar;
                si no, el valor estándar.
        """
        self.ensure_one()
        mode = self.portal_confirmation_mode or self.env['ir.config_parameter'].sudo().get_param(
            'cotizador.portal_confirmation_mode', default='salesman_enables'
        )
        if mode == 'salesman_only':
            return False
        if mode == 'salesman_enables' and not self.portal_confirmation_allowed:
            return False
        return super()._has_to_be_signed()

    def _has_to_be_paid(self):
        """El portal pide pago solo si el modo de aceptación lo permite.

        @return False en modo "Solo el vendedor" o "Habilitado por el vendedor" sin habilitar;
                si no, el valor estándar.
        """
        self.ensure_one()
        mode = self.portal_confirmation_mode or self.env['ir.config_parameter'].sudo().get_param(
            'cotizador.portal_confirmation_mode', default='salesman_enables'
        )
        if mode == 'salesman_only':
            return False
        if mode == 'salesman_enables' and not self.portal_confirmation_allowed:
            return False
        return super()._has_to_be_paid()

    def _confirmation_error_message(self):
        """Permite confirmar con las líneas sin producto del cotizador (descuentos, usados, planes).

        @return Mensaje de error, o False si se puede confirmar.
        """
        self.ensure_one()
        if self.state not in {'draft', 'sent'}:
            return _("Some orders are not in a state requiring confirmation.")
        if any(
            not line.display_type
            and not line.is_downpayment
            and not line.product_id
            and not line.is_descuento
            and not line.is_equipo_usado
            and not line.is_plan_pago
            for line in self.order_line
        ):
            return _("Some order lines are missing a product, you need to correct them before going further.")
        return False

    def action_confirm(self):
        """Confirma exigiendo plan de pago si está configurado, y marca ganada la oportunidad.

        @return Resultado estándar de la confirmación.
        @throws UserError Si el plan de pago es obligatorio y la cotización no tiene.
        """
        plan_pago_required = self.env['ir.config_parameter'].sudo().get_param(
            'cotizador.plan_pago_required', default='False'
        )
        if plan_pago_required == 'True':
            for order in self:
                tiene_plan_pago = order.order_line.filtered(lambda l: l.is_plan_pago)
                if not tiene_plan_pago:
                    raise UserError(
                        _("No se puede confirmar la orden '%s' porque no tiene un Plan de Pago seleccionado.\n"
                          "Por favor, agregue un Plan de Pago antes de confirmar.") % order.name
                    )

        res = super().action_confirm()

        won_stage = self.env['crm.stage'].search([('is_won', '=', True)], limit=1)
        for order in self:
            if order.opportunity_id:
                if won_stage:
                    order.opportunity_id.write({'stage_id': won_stage.id})
                else:
                    order.opportunity_id.action_set_won()

        return res

    # --- Impresión ---

    def _cotizador_print(self, mode):
        """Imprime el reporte del cotizador y pasa los borradores a *Enviada*.

        @param mode Hoja de planes de pago: `all` (todo el catálogo), `filtered` (los elegidos
               en la cotización) o `none` (sin hoja). El reporte lo lee del contexto `print_planes_mode`; el menú
               *Imprimir* tiene además un reporte por modo (report/report_cotizacion_planes.xml).
        @return Acción del reporte `cotizador.action_report_cotizacion_planes`.
        """
        self.filtered(lambda s: s.state == 'draft').write({'state': 'sent'})
        report = self.env.ref('cotizador.action_report_cotizacion_planes')
        return report.with_context(print_planes_mode=mode).report_action(self)

    def print_quotation(self):
        """Botón estándar *Imprimir*: los planes elegidos o, si no hay, sin hoja de planes.

        @return Acción del reporte.
        """
        return self._cotizador_print('filtered' if self.plan_pago_line_ids else 'none')

    # --- Alta de una configuración de sembradora en la cotización ---

    def _cotizador_price_date(self):
        """Fecha de las tasas de cambio y reglas de precio: la de la orden, o ahora.

        @return datetime.
        """
        return self.date_order or fields.Datetime.now()

    def _cotizador_machine_price(self, config):
        """Precio de la máquina de una configuración, como queda en esta orden.

        @param config sembradora.config.rel.
        @return Precio unitario en la moneda de la orden, con las reglas de su lista de precios.
        """
        self.ensure_one()
        return self.pricelist_id._get_product_price(
            config.modelo_id._with_matrix_price(config.price), 1.0,
            currency=self.currency_id, date=self._cotizador_price_date(),
        )

    def _cotizador_accessory_price(self, item):
        """Precio unitario de un accesorio, como queda en esta orden.

        @param item Ítem de sembradora.config.rel._get_accessory_offer() (usa `product`,
               `price_unit` y `quantity`; la cantidad cuenta para reglas por cantidad mínima).
        @return Precio unitario en la moneda de la orden, con las reglas de su lista de precios.
        """
        self.ensure_one()
        return self.pricelist_id._get_product_price(
            item['product']._with_matrix_price(item['price_unit']), item['quantity'],
            currency=self.currency_id, date=self._cotizador_price_date(),
        )

    def _cotizador_check_configuraciones(self):
        """Valida que las máquinas y accesorios de las cotizaciones sigan siendo una configuración válida (issue #19).

        Al agregar la máquina se valida la selección (_cotizador_add_configuration()), pero después las líneas se
        pueden editar: cambiar el producto de un accesorio, borrar la opción de un grupo de opción única o cambiar
        la variante de la máquina. Esto aplica las mismas reglas
        (sembradora.config.rel._check_accessory_selection()) a lo que quedó.

        Cada sección *Máquina* del cotizador abre un bloque: los accesorios que siguen son de la máquina del bloque.
        Los accesorios sin máquina arriba (una cotización de accesorios sueltos) no tienen configuración contra la
        cual validarse. Solo en borrador o enviada.

        @throws ValidationError Si la máquina no corresponde a ninguna configuración, si un accesorio no es de la
                configuración de su máquina o si la selección viola las reglas.
        """
        for order in self.filtered(lambda o: o.state in ('draft', 'sent')):
            bloques = []
            actual = None
            for line in order.order_line:
                if line.display_type:
                    if line.cotizador_section == 'maquina':
                        actual = None
                    continue
                tmpl = line.product_id.product_tmpl_id
                if tmpl.is_maquina:
                    actual = (line, [])
                    bloques.append(actual)
                elif tmpl.is_accesorio and actual is not None:
                    actual[1].append(line)
            for maquina, accesorios in bloques:
                order._cotizador_check_bloque(maquina, accesorios)

    def _cotizador_check_bloque(self, maquina, accesorios):
        """Valida una máquina de la cotización con los accesorios que tiene debajo.

        @param maquina sale.order.line de la máquina.
        @param accesorios Lista de sale.order.line de accesorios de esa máquina.
        @throws ValidationError Si la máquina no corresponde a ninguna configuración, si un accesorio no es de la
                configuración o si la selección viola las reglas.
        """
        variante = maquina.product_id
        config = variante.product_tmpl_id._cotizador_find_config(
            variante.product_template_attribute_value_ids.product_attribute_value_id.ids)
        if not config:
            raise ValidationError(self.env._(
                "La máquina «%(maq)s» no corresponde a ninguna configuración. Cotizala de nuevo con *Cotizar Equipo*.",
                maq=variante.display_name))
        linea_de = {l.product_id: l for l in config.accessory_line_ids}
        ajenos = [l.product_id.display_name for l in accesorios if l.product_id not in linea_de]
        if ajenos:
            raise ValidationError(self.env._(
                "%(accs)s no son accesorios de «%(maq)s».", accs=', '.join(ajenos), maq=variante.display_name))
        elegidas = self.env['sembradora.config.accessory.line'].sudo().union(
            *(linea_de[l.product_id] for l in accesorios))
        try:
            config._check_accessory_selection(elegidas)
        except UserError as error:
            raise ValidationError(self.env._("«%(maq)s»: %(error)s", maq=variante.display_name,
                                             error=error.args[0])) from error

    def _cotizador_add_configuration(self, config, acc_lines=None):
        """Agrega a la orden una máquina configurada y los accesorios elegidos.

        Es el único punto de alta (configurador OWL, Crear Cotización del CRM y solicitud web).
        Los precios se calculan en el servidor: precio de matriz → lista de precios y moneda de
        la orden. Si la orden todavía no tiene productos, pasa a la *Lista de Precios de
        Cotizaciones* de la compañía.

        Secciones (con `cotizador_section`):
          - Máquina: la variante de la configuración;
          - Equipamiento: estándar y la opción elegida de cada grupo de opción única;
          - Accesorios: el resto de lo elegido.

        Impuestos: el *Impuesto de Maquinaria* de la compañía o, si no hay, los del producto.

        @param config sembradora.config.rel elegida.
        @param acc_lines sembradora.config.accessory.line elegidas (opcional).
        @return sale.order.line creadas.
        @throws UserError Si la selección viola las reglas (ver
                sembradora.config.rel._check_accessory_selection()).
        """
        self.ensure_one()
        config.ensure_one()
        acc_lines = acc_lines or self.env['sembradora.config.accessory.line']
        config._check_accessory_selection(acc_lines)
        # Orden creada a mano (lista del cliente) que recibe su primera máquina: se pasa a la
        # lista de cotizaciones. Con productos ya cargados no se cambia (quedarían en otra moneda).
        pricelist = self.company_id.cotizador_pricelist_id
        if pricelist and self.pricelist_id != pricelist and not self.order_line.filtered(lambda l: not l.display_type):
            self.pricelist_id = pricelist

        tax = self.company_id.cotizador_tax_id
        # Sin impuesto configurado se usan los impuestos del producto (cálculo estándar de Odoo)
        tax_vals = {'tax_ids': [Command.set(tax.ids)]} if tax else {}
        variant = config._get_variant()

        vals_list = [
            {'order_id': self.id, 'name': _('Máquina'), 'display_type': 'line_section',
             'cotizador_section': 'maquina'},
            {
                'order_id': self.id,
                'product_id': variant.id,
                'product_uom_qty': 1.0,
                'name': config._get_variant_description(),
                'price_unit': self._cotizador_machine_price(config),
                'cotizador_matrix_price': config.price,
                'cotizador_matrix_priced': True,
                **tax_vals,
            },
        ]
        offer = [item for item in config._get_accessory_offer() if item['line'] in acc_lines]
        for section, label, items in (
            ('equipamiento', _('Equipamiento'), [i for i in offer if i['is_standard'] or i['choice_rule']]),
            ('accesorios', _('Accesorios'), [i for i in offer if not (i['is_standard'] or i['choice_rule'])]),
        ):
            if not items:
                continue
            vals_list.append({'order_id': self.id, 'name': label, 'display_type': 'line_section',
                              'cotizador_section': section})
            vals_list += [{
                'order_id': self.id,
                'product_id': item['product'].id,
                'product_uom_qty': item['quantity'],
                'price_unit': self._cotizador_accessory_price(item),
                'cotizador_matrix_price': item['price_unit'],
                'cotizador_matrix_priced': True,
                **tax_vals,
            } for item in items]

        lines = self.env['sale.order.line'].create(vals_list)
        if self.opportunity_id:
            self.opportunity_id._sync_expected_revenue_from_orders()
        return lines

    # --- Acciones y Asistentes ---

    def action_open_config_wizard(self):
        """Botón *Configurar*: abre el configurador visual sobre esta cotización.

        @return Acción cliente `cotizador_configurator` con `order_id`.
        """
        order_id = self.id or self.env.context.get('active_id') or self.env.context.get('params', {}).get('id')
        return {
            'type': 'ir.actions.client',
            'tag': 'cotizador_configurator',
            'target': 'current',
            'params': {
                'order_id': order_id,
            },
            'context': {
                'active_id': order_id,
                'default_sale_order_id': order_id,
            },
        }

    def action_open_plan_pago_wizard(self):
        """Botón de plan de pago: abre la selección con todas las opciones activas.

        @return Acción que abre cotizador.plan.pago.wizard.
        """
        self.ensure_one()
        templates = self.env['cotizador.plan.pago.template.line'].search([
            ('template_id.active', '=', True)
        ])
        lines = []
        for t in templates:
            lines.append((0, 0, {
                'template_line_id': t.id,
                'tipo': t.tipo,
                'name': t.name,
                'descuento': t.descuento,
            }))
        wizard = self.env['cotizador.plan.pago.wizard'].create({
            'sale_order_id': self.id,
            'wizard_line_ids': lines,
        })
        return {
            'name': 'Seleccionar Plan de Pago',
            'type': 'ir.actions.act_window',
            'res_model': 'cotizador.plan.pago.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_open_equipo_usado_wizard(self):
        """Abre el asistente para tomar un equipo usado como parte de pago.

        @return Acción que abre equipo.usado.wizard.
        @throws ValidationError Si la cotización todavía no se guardó.
        """
        order_id = self.id or self.env.context.get('active_id') or self.env.context.get('params', {}).get('id') or self.env.context.get('default_sale_order_id')
        if not order_id:
            raise ValidationError("No se pudo identificar la orden de venta activa. Por favor, guarde la cotización antes de continuar.")
        return {
            'type': 'ir.actions.act_window',
            'name': 'Añadir Equipo Usado',
            'res_model': 'equipo.usado.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_sale_order_id': order_id},
        }

    def action_open_descuento_wizard(self):
        """Abre el asistente de descuento comercial.

        @return Acción que abre cotizador.descuento.wizard.
        @throws ValidationError Si la cotización todavía no se guardó.
        """
        order_id = self.id or self.env.context.get('active_id') or self.env.context.get('params', {}).get('id') or self.env.context.get('default_sale_order_id')
        if not order_id:
            raise ValidationError("No se pudo identificar la orden de venta activa. Por favor, guarde la cotización antes de continuar.")
        return {
            'type': 'ir.actions.act_window',
            'name': 'Añadir Descuento Comercial',
            'res_model': 'cotizador.descuento.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_sale_order_id': order_id},
        }

    def action_open_discount_wizard(self):
        """El botón nativo de descuento de Odoo abre el descuento del cotizador.

        @return Acción que abre cotizador.descuento.wizard.
        """
        return self.action_open_descuento_wizard()


class SaleOrderLineInherit(models.Model):
    """Línea de cotización (`sale.order.line`) con las marcas del cotizador.

    `cotizador_section` identifica las secciones que crea el cotizador (nunca se identifican
    por su texto); `is_descuento`, `is_equipo_usado` e `is_plan_pago` marcan las líneas
    especiales que la cascada de totales trata aparte.
    """
    _inherit = 'sale.order.line'

    is_plan_pago = fields.Boolean(default=False, string='Es Plan de Pago')
    is_equipo_usado = fields.Boolean(default=False, string='Es Equipo Usado')
    is_descuento = fields.Boolean(default=False, string='Es Descuento Comercial')
    cotizador_section = fields.Selection([
        ('maquina', 'Máquina'),
        ('equipamiento', 'Equipamiento'),
        ('accesorios', 'Accesorios'),
        ('descuentos', 'Descuentos'),
        ('usados', 'Equipo Usado'),
    ], string='Sección del Cotizador', copy=True,
        help='Identifica las secciones que genera el cotizador (independiente del texto de la sección).')
    cotizador_matrix_price = fields.Float(
        string='Precio de Matriz',
        copy=True,
        help='Precio de matriz (en la Moneda del Cotizador del producto) con que se cotizó la máquina o el '
             'accesorio. Si Odoo recalcula el precio de la línea (cambio de cantidad, Actualizar precios), '
             'parte de este valor y le aplica la lista de precios y la moneda de la cotización.',
    )
    cotizador_matrix_priced = fields.Boolean(
        string='Con Precio de Matriz',
        copy=True,
        help='La línea la creó el cotizador con un precio de matriz (también cuando es 0, sin cargo).',
    )
    cotizador_pct = fields.Float(
        string='Porcentaje (Cotizador)',
        copy=True,
        help='Descuento comercial: porcentaje sobre el neto (0 = monto fijo). Plan de pago: recargo (+) o '
             'descuento (−) sobre el neto con descuentos. El importe se recalcula al cambiar las líneas.',
    )

    def _is_cotizador_product_line(self):
        """Línea de producto para la cascada: todo lo que no es sección, descuento, usado ni plan.

        @return True si es una línea de producto.
        """
        self.ensure_one()
        return not (self.display_type or self.is_descuento or self.is_equipo_usado or self.is_plan_pago)

    def _compute_price_unit(self):
        """Odoo no recalcula el precio de las líneas especiales del cotizador.

        Descuentos, usados y plan de pago no tienen precio de producto: su importe lo fija el
        asistente o sale.order._cotizador_update_adjustments().
        """
        special = self.filtered(lambda l: l.is_descuento or l.is_equipo_usado or l.is_plan_pago)
        super(SaleOrderLineInherit, self - special)._compute_price_unit()

    def _get_product_price_context(self):
        """Contexto de precio: con precio de matriz guardado, el precio de lista es ese.

        Así un recálculo de Odoo (cantidad, unidad, *Actualizar precios*) parte del precio de
        matriz cotizado y no del precio de venta del producto.

        @return dict de contexto para el cálculo de precio.
        """
        res = super()._get_product_price_context()
        if self.cotizador_matrix_priced and self.product_id:
            res['cotizador_matrix_price'] = ('product.product', self.product_id.id, self.cotizador_matrix_price)
        return res

    @api.model_create_multi
    def create(self, vals_list):
        """Crea líneas, recalcula descuentos en porcentaje y plan de pago, y valida las configuraciones de sus órdenes.

        @param vals_list Lista de diccionarios de valores.
        @return Las líneas creadas.
        @throws ValidationError Si la orden queda con una configuración inválida (sale.order._cotizador_check_configuraciones()).
        """
        lines = super().create(vals_list)
        if not self.env.context.get('cotizador_skip_adjustments'):
            lines.order_id._cotizador_update_adjustments()
        if not self.env.context.get('cotizador_skip_config_check'):
            lines.order_id._cotizador_check_configuraciones()
        return lines

    def write(self, vals):
        """Escribe; si cambia algo que afecta el neto, recalcula descuentos y plan de pago, y si cambia qué se
        cotiza, valida las configuraciones.

        @param vals Valores a escribir.
        @return True.
        @throws ValidationError Si la orden queda con una configuración inválida (sale.order._cotizador_check_configuraciones()).
        """
        res = super().write(vals)
        if not self.env.context.get('cotizador_skip_adjustments') and AFFECTS_ADJUSTMENTS & vals.keys():
            self.order_id._cotizador_update_adjustments()
        if not self.env.context.get('cotizador_skip_config_check') and AFFECTS_CONFIG & vals.keys():
            self.order_id._cotizador_check_configuraciones()
        return res

    def unlink(self):
        """Borra líneas, recalcula descuentos y plan de pago, y valida las configuraciones de sus órdenes.

        @return True.
        @throws ValidationError Si la orden queda con una configuración inválida (sale.order._cotizador_check_configuraciones()).
        """
        orders = self.order_id
        res = super().unlink()
        if not self.env.context.get('cotizador_skip_adjustments'):
            orders.exists()._cotizador_update_adjustments()
        if not self.env.context.get('cotizador_skip_config_check'):
            orders.exists()._cotizador_check_configuraciones()
        return res

    def _get_parent_order(self):
        """Orden de la línea o, si la línea aún no se guardó, la del contexto.

        @return sale.order.
        @throws ValidationError Si no se puede identificar la orden.
        """
        if self.order_id:
            return self.order_id
        ctx = self.env.context
        parent_id = (
            ctx.get('default_sale_order_id') or
            ctx.get('order_id') or
            ctx.get('active_id') or
            ctx.get('default_order_id') or
            ctx.get('params', {}).get('id')
        )
        if not parent_id:
            raise ValidationError(_("No se pudo identificar la orden de venta activa. Por favor, guarde la cotización antes de continuar."))
        return self.env['sale.order'].browse(parent_id)

    def action_open_config_wizard(self):
        """Botón de la lista de líneas: delega en la orden.

        @return Acción del configurador.
        """
        return self._get_parent_order().action_open_config_wizard()

    def action_open_equipo_usado_wizard(self):
        """Botón de la lista de líneas: delega en la orden.

        @return Acción del asistente de usados.
        """
        return self._get_parent_order().action_open_equipo_usado_wizard()

    def action_open_descuento_wizard(self):
        """Botón de la lista de líneas: delega en la orden.

        @return Acción del asistente de descuento.
        """
        return self._get_parent_order().action_open_descuento_wizard()

    def action_open_discount_wizard(self):
        """Botón nativo de descuento en la lista de líneas: descuento del cotizador.

        @return Acción del asistente de descuento.
        """
        return self.action_open_descuento_wizard()
