# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
import logging
from .bcra_service import consultar_bcra_completo, SITUACION_LABELS

_logger = logging.getLogger(__name__)

DEFAULT_CONDICIONES_GENERALES = """Condiciones Generales
Vigencia de esta cotización sujeta a cambios sin previo aviso
Valores expresados en Dólares Americanos, sin IVA
Tipos de Cambio: Banco Nación Argentina, Cotización Billete, Vendedor
Fijación de tipo de cambio: Fecha de efectiva recepción de la cobranza en fábrica y/o acreditación en cuenta de la empresa"""


class SaleOrderInherit(models.Model):
    _inherit = 'sale.order'

    # --- Condiciones Generales ---

    def _default_condiciones_generales(self):
        return self.env['ir.config_parameter'].sudo().get_param(
            'cotizador.condiciones_generales_default',
            DEFAULT_CONDICIONES_GENERALES
        )

    condiciones_generales = fields.Text(
        string='Condiciones Generales',
        default=_default_condiciones_generales,
        help='Condiciones comerciales constantes preconfiguradas que se imprimen al pie de la cotización.',
    )

    # --- Planes de Pago Filtrados ---

    def _default_plan_pago_line_ids(self):
        user_lines = self.env.user.plan_pago_template_line_ids
        if user_lines:
            return user_lines.ids
        return self.env['cotizador.plan.pago.template.line'].search([
            ('template_id.active', '=', True)
        ]).ids

    plan_pago_line_ids = fields.Many2many(
        'cotizador.plan.pago.template.line',
        'sale_order_cotizador_plan_pago_rel',
        'order_id',
        'plan_line_id',
        string='Planes de Pago a Imprimir',
        default=_default_plan_pago_line_ids,
        help='Seleccione qué planes de pago se imprimirán en la hoja de planes de pago de esta cotización.',
    )

    # --- Modalidad de Aceptación y Firma en Portal ---

    def _default_portal_confirmation_mode(self):
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
    equipo_cotizado_id = fields.Many2one(
        'product.template',
        string='Equipo Cotizado',
        domain="['|', ('categ_id.name', 'ilike', 'Maquina'), ('categ_id.complete_name', 'ilike', 'Maquina')]",
        compute='_compute_equipo_cotizado_id',
        store=True,
        readonly=False,
        help='Modelo de máquina cotizada (categoría Máquina).',
    )

    @api.depends('order_line.product_id')
    def _compute_equipo_cotizado_id(self):
        for order in self:
            maquina_lines = order.order_line.filtered(
                lambda l: l.product_id and (
                    'maquina' in (l.product_id.product_tmpl_id.categ_id.name or '').lower() or
                    'maquina' in (l.product_id.product_tmpl_id.categ_id.complete_name or '').lower() or
                    'máquina' in (l.product_id.product_tmpl_id.categ_id.name or '').lower() or
                    'máquina' in (l.product_id.product_tmpl_id.categ_id.complete_name or '').lower()
                )
            )
            if maquina_lines:
                order.equipo_cotizado_id = maquina_lines[0].product_id.product_tmpl_id
            elif not order.equipo_cotizado_id:
                order.equipo_cotizado_id = False

    # --- Totales Desglosados del Cotizador (Imagen 1) ---

    amount_subtotal_productos = fields.Monetary(
        string='SUB TOTAL',
        compute='_compute_totales_cotizador',
        currency_field='currency_id',
        store=True,
    )
    amount_iva_productos = fields.Monetary(
        string='IVA',
        compute='_compute_totales_cotizador',
        currency_field='currency_id',
        store=True,
    )
    amount_total_base = fields.Monetary(
        string='TOTAL',
        compute='_compute_totales_cotizador',
        currency_field='currency_id',
        store=True,
    )
    amount_descuentos = fields.Monetary(
        string='Total Descuentos',
        compute='_compute_totales_cotizador',
        currency_field='currency_id',
        store=True,
    )
    amount_total_con_descuentos = fields.Monetary(
        string='TOTAL CON DESCUENTOS',
        compute='_compute_totales_cotizador',
        currency_field='currency_id',
        store=True,
    )
    amount_usados = fields.Monetary(
        string='Medios de pago (Usados)',
        compute='_compute_totales_cotizador',
        currency_field='currency_id',
        store=True,
    )
    amount_saldo_cancelar = fields.Monetary(
        string='SALDO A CANCELAR',
        compute='_compute_totales_cotizador',
        currency_field='currency_id',
        store=True,
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
        'order_line.price_subtotal', 'order_line.price_tax', 'order_line.price_unit',
        'order_line.product_uom_qty', 'order_line.discount',
        'order_line.is_descuento', 'order_line.is_equipo_usado', 'order_line.display_type'
    )
    def _compute_totales_cotizador(self):
        for order in self:
            # 1. Líneas de productos (máquina base + accesorios)
            prod_lines = order.order_line.filtered(
                lambda l: not l.display_type and not l.is_descuento and not l.is_equipo_usado
            )
            subtotal = round(sum(l.price_unit * l.product_uom_qty for l in prod_lines), 2)
            iva = round(sum(l.price_tax for l in prod_lines), 2)
            total_base = round(subtotal + iva, 2)

            # 2. Descuentos comerciales (almacenados en negativo para visualización -$)
            desc_lines = order.order_line.filtered(lambda l: l.is_descuento)
            total_descuentos_abs = round(sum(abs(l.price_subtotal) for l in desc_lines), 2)
            total_descuentos = -total_descuentos_abs if total_descuentos_abs else 0.0
            total_con_desc = round(total_base - total_descuentos_abs, 2)

            # 3. Medios de pago (toma de usados, almacenados en negativo para visualización -$)
            usado_lines = order.order_line.filtered(lambda l: l.is_equipo_usado)
            total_usados_abs = round(sum(abs(l.price_subtotal) for l in usado_lines), 2)
            total_usados = -total_usados_abs if total_usados_abs else 0.0

            # 4. Saldo a Cancelar
            saldo = max(0.0, round(total_con_desc - total_usados_abs, 2))

            order.amount_subtotal_productos = subtotal
            order.amount_iva_productos = iva
            order.amount_total_base = total_base
            order.amount_descuentos = total_descuentos
            order.amount_total_con_descuentos = total_con_desc
            order.amount_usados = total_usados
            order.amount_saldo_cancelar = saldo

    @api.depends('order_line.is_descuento', 'order_line.is_equipo_usado')
    def _compute_lineas_especiales(self):
        for order in self:
            order.descuento_line_ids = order.order_line.filtered(lambda l: l.is_descuento)
            order.usado_line_ids = order.order_line.filtered(lambda l: l.is_equipo_usado)

    # --- BCRA Service ---

    @api.onchange('partner_id')
    def _onchange_partner_id_bcra(self):
        """Al seleccionar cliente, consulta en tiempo real al BCRA y emite alerta si posee deudas."""
        if self.partner_id and self.partner_id.vat:
            data = consultar_bcra_completo(self.partner_id.vat)
            if data and data.get('success') and data.get('tiene_deuda') and data.get('monto_total_deuda', 0.0) > 0:
                monto_total = data.get('monto_total_deuda', 0.0)
                peor_sit = data.get('peor_situacion') or '1'
                monto_fmt = f"{monto_total:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
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
        """Abre un wizard modal con el informe crediticio en tiempo real del BCRA."""
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
        """Sincroniza automáticamente la cotización con el CRM."""
        if self.env.context.get('skip_crm_sync'):
            return
        for order in self:
            modelo_maquina = order.equipo_cotizado_id
            if not modelo_maquina:
                maquina_lines = order.order_line.filtered(
                    lambda l: l.product_id and (
                        'maquina' in (l.product_id.product_tmpl_id.categ_id.name or '').lower() or
                        'maquina' in (l.product_id.product_tmpl_id.categ_id.complete_name or '').lower() or
                        'máquina' in (l.product_id.product_tmpl_id.categ_id.name or '').lower() or
                        'máquina' in (l.product_id.product_tmpl_id.categ_id.complete_name or '').lower()
                    )
                )
                modelo_maquina = maquina_lines[0].product_id.product_tmpl_id if maquina_lines else False
                if modelo_maquina and not order.equipo_cotizado_id:
                    order.equipo_cotizado_id = modelo_maquina.id
            monto = order.amount_saldo_cancelar if order.amount_saldo_cancelar else order.amount_total

            # Solo proceder si tiene partner asignado y máquina cotizada o monto
            if not order.partner_id:
                continue

            if not order.opportunity_id and modelo_maquina:
                initial_stage = self.env['crm.stage'].search([
                    ('is_won', '=', False),
                ], order='sequence asc', limit=1)

                lead_vals = {
                    'name': f"Cotización {order.name} - {order.partner_id.name}",
                    'partner_id': order.partner_id.id,
                    'user_id': order.user_id.id if order.user_id else self.env.uid,
                    'team_id': order.team_id.id if order.team_id else False,
                    'lider_equipo_id': order.team_id.user_id.id if order.team_id and order.team_id.user_id else False,
                    'equipo_cotizado_id': modelo_maquina.id,
                    'expected_revenue': monto,
                    'stage_id': initial_stage.id if initial_stage else False,
                }
                lead = self.env['crm.lead'].create(lead_vals)
                order.opportunity_id = lead.id
            elif order.opportunity_id:
                update_vals = {}
                if modelo_maquina and order.opportunity_id.equipo_cotizado_id != modelo_maquina:
                    update_vals['equipo_cotizado_id'] = modelo_maquina.id
                if order.partner_id and order.opportunity_id.partner_id != order.partner_id:
                    update_vals['partner_id'] = order.partner_id.id
                if order.user_id and order.opportunity_id.user_id != order.user_id:
                    update_vals['user_id'] = order.user_id.id
                if order.team_id and order.team_id.user_id and not order.opportunity_id.lider_equipo_id:
                    update_vals['lider_equipo_id'] = order.team_id.user_id.id
                if monto and order.opportunity_id.expected_revenue != monto:
                    update_vals['expected_revenue'] = monto
                if update_vals:
                    order.opportunity_id.write(update_vals)

    @api.onchange('equipo_cotizado_id')
    def _onchange_equipo_cotizado_id_pricelist(self):
        """Asigna automáticamente la lista de precios en USD si el equipo cotizado es una máquina."""
        if self.equipo_cotizado_id and self.equipo_cotizado_id.is_maquina:
            usd_pl = self.env['product.pricelist'].search([('currency_id.name', '=', 'USD')], limit=1)
            if usd_pl:
                self.pricelist_id = usd_pl.id

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('portal_confirmation_mode'):
                vals['portal_confirmation_mode'] = self.env['ir.config_parameter'].sudo().get_param(
                    'cotizador.portal_confirmation_mode', default='salesman_enables'
                )
            if vals.get('equipo_cotizado_id') and not vals.get('pricelist_id'):
                equipo = self.env['product.template'].browse(vals['equipo_cotizado_id'])
                if equipo.exists() and equipo.is_maquina:
                    usd_pl = self.env['product.pricelist'].search([('currency_id.name', '=', 'USD')], limit=1)
                    if usd_pl:
                        vals['pricelist_id'] = usd_pl.id
        orders = super().create(vals_list)
        for order in orders:
            order._sync_with_crm()
        return orders

    def write(self, vals):
        res = super().write(vals)
        if any(f in vals for f in ('amount_untaxed', 'amount_total', 'amount_saldo_cancelar', 'order_line', 'state', 'partner_id', 'user_id')):
            self._sync_with_crm()
        return res

    def action_enable_portal_confirmation(self):
        """Habilita la firma del cliente en el portal."""
        self.ensure_one()
        self.write({
            'portal_confirmation_allowed': True,
            'require_signature': True,
        })
        self.message_post(
            body=_("El asesor comercial ha <strong>habilitado</strong> la aceptación y firma online de esta cotización para el cliente en el portal."),
            message_type='notification',
            subtype_xmlid='mail.mt_note'
        )

    def action_disable_portal_confirmation(self):
        """Deshabilita la firma del cliente en el portal."""
        self.ensure_one()
        self.write({
            'portal_confirmation_allowed': False,
        })
        self.message_post(
            body=_("El asesor comercial ha <strong>deshabilitado</strong> la aceptación y firma online de esta cotización en el portal."),
            message_type='notification',
            subtype_xmlid='mail.mt_note'
        )

    def _has_to_be_signed(self):
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
        """Permite confirmar órdenes con líneas descriptivas del cotizador (descuentos, usados, planes)."""
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
        """Override para validar plan de pago y pasar oportunidad del CRM a Ganado."""
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

        # Al confirmar, pasar la oportunidad del CRM a Ganado
        won_stage = self.env['crm.stage'].search([('is_won', '=', True)], limit=1)
        for order in self:
            if order.opportunity_id:
                if won_stage:
                    order.opportunity_id.write({'stage_id': won_stage.id})
                elif hasattr(order.opportunity_id, 'action_set_won'):
                    order.opportunity_id.action_set_won()

        return res

    # --- Impresión de Cotizaciones (3 Opciones y Default) ---

    def action_print_todos_planes(self):
        """Imprime la cotización incluyendo todos los planes de pago del catálogo."""
        self.filtered(lambda s: s.state == 'draft').write({'state': 'sent'})
        report = self.env.ref('cotizador.action_report_cotizacion_planes', raise_if_not_found=False)
        return report.with_context(print_planes_mode='all').report_action(self)

    def action_print_planes_filtrados(self):
        """Imprime la cotización incluyendo únicamente los planes de pago filtrados en la orden."""
        self.filtered(lambda s: s.state == 'draft').write({'state': 'sent'})
        report = self.env.ref('cotizador.action_report_cotizacion_planes', raise_if_not_found=False)
        return report.with_context(print_planes_mode='filtered').report_action(self)

    def action_print_sin_planes(self):
        """Imprime la cotización omitiendo completamente la hoja de planes de pago."""
        self.filtered(lambda s: s.state == 'draft').write({'state': 'sent'})
        report = self.env.ref('cotizador.action_report_cotizacion_planes', raise_if_not_found=False)
        return report.with_context(print_planes_mode='none').report_action(self)

    def print_quotation(self):
        """Override del botón estándar de impresión de Odoo."""
        mode = 'filtered' if self.plan_pago_line_ids else 'all'
        report = self.env.ref('cotizador.action_report_cotizacion_planes', raise_if_not_found=False)
        if report:
            self.filtered(lambda s: s.state == 'draft').write({'state': 'sent'})
            return report.with_context(print_planes_mode=mode).report_action(self)
        return super().print_quotation()

    # --- Acciones y Asistentes ---

    def action_open_config_wizard(self):
        """Abre el configurador de sembradora (Visual OWL o Wizard Legacy según la configuración del sistema)."""
        order_id = self.id or self.env.context.get('active_id') or self.env.context.get('params', {}).get('id')
        use_legacy = self.env['ir.config_parameter'].sudo().get_param(
            'cotizador.use_legacy_wizard', default='False'
        )
        if use_legacy == 'True':
            return {
                'type': 'ir.actions.act_window',
                'name': 'Configurar Equipo (Legacy)',
                'res_model': 'sembradora.config.wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': {'default_sale_order_id': order_id},
            }

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
        """Abre el wizard para tomar un equipo usado como forma de pago."""
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
        """Abre el wizard para aplicar un descuento comercial."""
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
        """Sobrescribe la acción nativa de Odoo para abrir el wizard del Cotizador y evitar conflictos."""
        return self.action_open_descuento_wizard()


class SaleOrderLineInherit(models.Model):
    _inherit = 'sale.order.line'

    is_plan_pago = fields.Boolean(default=False)
    is_equipo_usado = fields.Boolean(default=False)
    is_descuento = fields.Boolean(default=False, string='Es Descuento Comercial')

    def action_open_config_wizard(self):
        """Delegación del botón del listado de líneas al sale.order padre."""
        order_id = False
        if self.order_id:
            order_id = self.order_id
        else:
            ctx = self.env.context
            parent_id = (
                ctx.get('default_sale_order_id') or
                ctx.get('order_id') or
                ctx.get('active_id') or 
                ctx.get('default_order_id') or 
                ctx.get('params', {}).get('id')
            )
            if parent_id:
                order_id = self.env['sale.order'].browse(parent_id)

        if not order_id:
            raise ValidationError("No se pudo identificar la orden de venta activa. Por favor, guarde la cotización antes de configurar.")

        return order_id.action_open_config_wizard()

    def action_open_equipo_usado_wizard(self):
        """Delegación del botón del listado de líneas al sale.order padre."""
        order_id = False
        if self.order_id:
            order_id = self.order_id
        else:
            ctx = self.env.context
            parent_id = (
                ctx.get('default_sale_order_id') or
                ctx.get('order_id') or
                ctx.get('active_id') or 
                ctx.get('default_order_id') or 
                ctx.get('params', {}).get('id')
            )
            if parent_id:
                order_id = self.env['sale.order'].browse(parent_id)

        if not order_id:
            raise ValidationError("No se pudo identificar la orden de venta activa. Por favor, guarde la cotización antes de continuar.")

        return order_id.action_open_equipo_usado_wizard()

    def action_open_descuento_wizard(self):
        """Delegación del botón del listado de líneas al sale.order padre."""
        order_id = False
        if self.order_id:
            order_id = self.order_id
        else:
            ctx = self.env.context
            parent_id = (
                ctx.get('default_sale_order_id') or
                ctx.get('order_id') or
                ctx.get('active_id') or 
                ctx.get('default_order_id') or 
                ctx.get('params', {}).get('id')
            )
            if parent_id:
                order_id = self.env['sale.order'].browse(parent_id)

        if not order_id:
            raise ValidationError("No se pudo identificar la orden de venta activa. Por favor, guarde la cotización antes de continuar.")

        return order_id.action_open_descuento_wizard()

    def action_open_discount_wizard(self):
        """Delegación del botón nativo de descuento al wizard del Cotizador."""
        return self.action_open_descuento_wizard()
