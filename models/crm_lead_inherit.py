"""@file
Oportunidades del CRM: máquina cotizada, configuración pedida en la web e ingreso esperado."""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class CrmLeadInherit(models.Model):
    """Lead / oportunidad (`crm.lead`) del cotizador.

    - Las solicitudes web guardan la configuración elegida (`cotizador_config_id`) y la IP.
    - *Crear Cotización* arma la cotización de esa configuración para el cliente del lead.
    - El ingreso esperado sigue a la última cotización o pedido, convertido a la moneda de la
      compañía (_sync_expected_revenue_from_orders()).
    """
    _inherit = 'crm.lead'

    equipo_cotizado_id = fields.Many2one(
        'product.template',
        string='Equipo (Sembradora/Ferti)',
        domain="[('is_maquina', '=', True)]",
        help='Modelo de máquina cotizada o de interés (categoría Máquina).',
        tracking=True,
    )
    lider_equipo_id = fields.Many2one(
        'res.users',
        string='Líder de Equipo',
        compute='_compute_lider_equipo_id',
        store=True,
        readonly=False,
        tracking=True,
        help='Líder o responsable del equipo de ventas.',
    )
    cotizador_config_id = fields.Many2one(
        'sembradora.config.rel',
        string='Configuración Solicitada',
        readonly=True,
        copy=False,
        help='Configuración elegida en la tienda online. "Crear Cotización" arma la cotización '
             'con esta máquina y su equipamiento estándar.',
    )
    cotizador_request_ip = fields.Char(
        string='IP de la Solicitud Web',
        readonly=True,
        copy=False,
        index='btree_not_null',
        help='IP desde la que se envió la solicitud de cotización en la tienda (control de abuso).',
    )

    @api.depends('team_id', 'team_id.user_id')
    def _compute_lider_equipo_id(self):
        """Propone como líder al jefe del equipo de ventas, si todavía no hay uno."""
        for lead in self:
            if not lead.lider_equipo_id and lead.team_id and lead.team_id.user_id:
                lead.lider_equipo_id = lead.team_id.user_id

    def _sync_expected_revenue_from_orders(self):
        """Recalcula el ingreso esperado y la máquina desde las cotizaciones de la oportunidad.

        Toma el último pedido confirmado o, si no hay, la última cotización no cancelada. El
        monto es el saldo a cancelar (o el total) convertido de la moneda de la orden a la de
        la compañía, con la tasa de la fecha de la orden.
        """
        for lead in self:
            active_orders = lead.order_ids.filtered(lambda o: o.state != 'cancel')
            if active_orders:
                confirmed = active_orders.filtered(lambda o: o.state in ('sale', 'done'))
                if confirmed:
                    target_order = confirmed.sorted(lambda o: (o.date_order or o.create_date or fields.Datetime.now()), reverse=True)[0]
                else:
                    target_order = active_orders.sorted(lambda o: (o.date_order or o.create_date or fields.Datetime.now()), reverse=True)[0]

                company_currency = lead.company_currency or self.env.company.currency_id
                monto_origen = target_order.amount_saldo_cancelar or target_order.amount_total
                amount = target_order.currency_id._convert(
                    monto_origen,
                    company_currency,
                    target_order.company_id,
                    target_order.date_order or fields.Date.today()
                )
                lead.expected_revenue = amount

                maquina = target_order._get_maquina_template()
                if maquina:
                    lead.equipo_cotizado_id = maquina

    @api.model_create_multi
    def create(self, vals_list):
        """Crea leads y sincroniza el ingreso esperado de los que ya traen cotizaciones.

        @param vals_list Lista de diccionarios de valores.
        @return Los leads creados.
        """
        leads = super().create(vals_list)
        for lead in leads:
            if lead.order_ids:
                lead._sync_expected_revenue_from_orders()
        return leads

    def write(self, vals):
        """Escribe y, si cambian las cotizaciones vinculadas, recalcula el ingreso esperado.

        @param vals Valores a escribir.
        @return True.
        """
        res = super().write(vals)
        if 'order_ids' in vals:
            self._sync_expected_revenue_from_orders()
        return res

    def action_cotizador_create_quotation(self):
        """Botón *Crear Cotización*: cotización de la configuración pedida en la web.

        Usa el cliente del lead y agrega la máquina con su equipamiento estándar.

        @return Acción que abre la cotización creada.
        @throws UserError Si el lead no tiene configuración o todavía no tiene cliente.
        """
        self.ensure_one()
        if not self.cotizador_config_id:
            raise UserError(_("Esta oportunidad no tiene una configuración solicitada."))
        if not self.partner_id:
            raise UserError(_(
                "Asigne primero el cliente (convierta el lead vinculándolo a un contacto existente "
                "o creando uno nuevo)."
            ))
        config = self.cotizador_config_id
        order = self.env['sale.order'].create({
            'partner_id': self.partner_id.id,
            'opportunity_id': self.id,
            'team_id': self.team_id.id,
            'user_id': self.user_id.id or self.env.uid,
            'origin': self.name,
            'equipo_cotizado_id': config.modelo_id.id,
        })
        order._cotizador_add_configuration(config, config._get_default_accessory_lines())
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'res_id': order.id,
            'view_mode': 'form',
            'target': 'current',
        }
