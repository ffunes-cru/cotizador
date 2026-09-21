from odoo import models, fields


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    cotizador_plan_pago_required = fields.Boolean(
        string='Plan de Pago Obligatorio',
        help='Si se activa, no se podrá confirmar una cotización sin tener un Plan de Pago seleccionado.',
        config_parameter='cotizador.plan_pago_required',
    )
    cotizador_use_legacy_wizard = fields.Boolean(
        string='Usar Configurador Clásico (Legacy)',
        help='Si se activa, el botón de configurar equipo abrirá el wizard estándar de Odoo en lugar de la nueva interfaz visual interactiva en OWL.',
        config_parameter='cotizador.use_legacy_wizard',
    )
    cotizador_modo_silencioso = fields.Boolean(
        string='Modo Silencioso (Configurador)',
        help='Oculta el precio unitario de los accesorios en el configurador interactivo, mostrando únicamente el precio total.',
        config_parameter='cotizador.modo_silencioso',
    )

