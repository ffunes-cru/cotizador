# -*- coding: utf-8 -*-
from odoo import models, fields, api


class CrmLeadInherit(models.Model):
    _inherit = 'crm.lead'

    def _sync_expected_revenue_from_orders(self):
        """Actualiza el expected_revenue de la oportunidad tomando el monto de la última cotización o pedido."""
        for lead in self:
            active_orders = lead.order_ids.filtered(lambda o: o.state != 'cancel')
            if active_orders:
                confirmed = active_orders.filtered(lambda o: o.state in ('sale', 'done'))
                if confirmed:
                    target_order = confirmed.sorted(lambda o: (o.date_order or o.create_date or fields.Datetime.now()), reverse=True)[0]
                else:
                    target_order = active_orders.sorted(lambda o: (o.date_order or o.create_date or fields.Datetime.now()), reverse=True)[0]

                company_currency = lead.company_currency or self.env.company.currency_id
                amount = target_order.currency_id._convert(
                    target_order.amount_untaxed,
                    company_currency,
                    target_order.company_id,
                    target_order.date_order or fields.Date.today()
                )
                lead.expected_revenue = amount

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
