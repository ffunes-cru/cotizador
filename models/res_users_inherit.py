"""@file
Preferencias del vendedor para el cotizador."""
from odoo import fields, models


class ResUsers(models.Model):
    """Usuario (`res.users`): planes de pago que ve por defecto en sus cotizaciones.

    Ver sale.order._default_plan_pago_line_ids().
    """
    _inherit = 'res.users'

    plan_pago_template_line_ids = fields.Many2many(
        'cotizador.plan.pago.template.line',
        'res_users_plan_pago_line_rel',
        'user_id',
        'plan_line_id',
        string='Planes de Pago Favoritos / Visibles',
        help='Seleccione qué planes de pago estarán visibles por defecto en las cotizaciones que genere este usuario.',
    )
