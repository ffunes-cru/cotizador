from odoo import models, fields


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    cotizador_plan_pago_required = fields.Boolean(
        string='Plan de Pago Obligatorio',
        help='Si se activa, no se podrá confirmar una cotización sin tener un Plan de Pago seleccionado.',
        config_parameter='cotizador.plan_pago_required',
    )
