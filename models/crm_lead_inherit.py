# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
import logging

_logger = logging.getLogger(__name__)



class CrmLeadInherit(models.Model):
    _inherit = 'crm.lead'

    equipo_cotizado_id = fields.Many2one(
        'product.template',
        string='Equipo (Sembradora/Ferti)',
        domain="['|', ('categ_id.name', 'ilike', 'Maquina'), ('categ_id.complete_name', 'ilike', 'Maquina')]",
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

    @api.depends('team_id', 'team_id.user_id')
    def _compute_lider_equipo_id(self):
        for lead in self:
            if not lead.lider_equipo_id and lead.team_id and lead.team_id.user_id:
                lead.lider_equipo_id = lead.team_id.user_id

    def _sync_expected_revenue_from_orders(self):
        """Actualiza el expected_revenue de la oportunidad tomando el monto de la última cotización o pedido y sincroniza el equipo."""
        for lead in self:
            active_orders = lead.order_ids.filtered(lambda o: o.state != 'cancel')
            if active_orders:
                confirmed = active_orders.filtered(lambda o: o.state in ('sale', 'done'))
                if confirmed:
                    target_order = confirmed.sorted(lambda o: (o.date_order or o.create_date or fields.Datetime.now()), reverse=True)[0]
                else:
                    target_order = active_orders.sorted(lambda o: (o.date_order or o.create_date or fields.Datetime.now()), reverse=True)[0]

                company_currency = lead.company_currency or self.env.company.currency_id
                # Tomar saldo a cancelar si existe, sino amount_total o amount_untaxed
                monto_origen = target_order.amount_saldo_cancelar if hasattr(target_order, 'amount_saldo_cancelar') and target_order.amount_saldo_cancelar else target_order.amount_total
                amount = target_order.currency_id._convert(
                    monto_origen,
                    company_currency,
                    target_order.company_id,
                    target_order.date_order or fields.Date.today()
                )
                lead.expected_revenue = amount

                # Sincronizar equipo cotizado si la orden tiene una máquina
                maquina_lines = target_order.order_line.filtered(
                    lambda l: l.product_id and l.product_id.product_tmpl_id.categ_id.name == 'Maquina'
                )
                if maquina_lines:
                    lead.equipo_cotizado_id = maquina_lines[0].product_id.product_tmpl_id

    @api.model_create_multi
    def create(self, vals_list):
        leads = super().create(vals_list)
        for lead in leads:
            if lead.order_ids:
                lead._sync_expected_revenue_from_orders()
        return leads

    def write(self, vals):
        res = super().write(vals)
        if 'order_ids' in vals:
            self._sync_expected_revenue_from_orders()
        return res
