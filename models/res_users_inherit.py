# -*- coding: utf-8 -*-
from odoo import models, fields


class ResUsers(models.Model):
    _inherit = 'res.users'

    plan_pago_template_line_ids = fields.Many2many(
        'cotizador.plan.pago.template.line',
        'res_users_plan_pago_line_rel',
        'user_id',
        'plan_line_id',
        string='Planes de Pago Favoritos / Visibles',
        help='Seleccione qué planes de pago estarán visibles por defecto en las cotizaciones que genere este usuario.',
    )
