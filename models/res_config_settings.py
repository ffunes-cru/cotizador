from odoo import models, fields


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    cotizador_plan_pago_required = fields.Boolean(
        string='Plan de Pago Obligatorio',
        help='Si se activa, no se podrá confirmar una cotización sin tener un Plan de Pago seleccionado.',
        config_parameter='cotizador.plan_pago_required',
    )
    cotizador_modo_silencioso = fields.Boolean(
        string='Modo Silencioso (Configurador)',
        help='Oculta el precio unitario de los accesorios en el configurador interactivo, mostrando únicamente el precio total.',
        config_parameter='cotizador.modo_silencioso',
    )
    cotizador_ecommerce_mode = fields.Selection(
        selection=[
            ('quote_only', 'Solicitar Cotización (Sin pagos online, conecta a CRM)'),
            ('ecommerce', 'Comercio Electrónico Estándar (Carrito y pagos online)'),
        ],
        string='Modo de la Tienda Online',
        default='quote_only',
        help='Define si la tienda online permite solicitar cotizaciones directamente al CRM o si opera como un eCommerce con checkout y cobro.',
        config_parameter='cotizador.ecommerce_mode',
    )
    cotizador_portal_confirmation_mode = fields.Selection(
        selection=[
            ('standard', 'Estándar Odoo (Firma / Pago según configuración de Ventas)'),
            ('salesman_enables', 'Habilitado por el Vendedor (Propuesta preliminar; el asesor comercial habilita la firma)'),
            ('salesman_only', 'Solo el Vendedor puede confirmar (El cliente nunca puede aceptar/firmar desde el portal)'),
        ],
        string='Aceptación de Cotizaciones en el Portal',
        default='salesman_enables',
        help='Controla si el cliente puede aceptar y firmar sus cotizaciones desde la web, o si requiere validación del asesor comercial.',
        config_parameter='cotizador.portal_confirmation_mode',
    )
    cotizador_quote_rate_limit_ip = fields.Integer(
        string='Solicitudes web por IP (por hora)',
        default=5,
        help='Máximo de solicitudes de cotización anónimas desde una misma IP por hora. 0 = sin límite.',
        config_parameter='cotizador.quote_rate_limit_ip',
    )
    cotizador_quote_rate_limit_contact = fields.Integer(
        string='Solicitudes web por email/teléfono (por hora)',
        default=3,
        help='Máximo de solicitudes de cotización anónimas con el mismo email o teléfono por hora. 0 = sin límite.',
        config_parameter='cotizador.quote_rate_limit_contact',
    )
    cotizador_quote_min_seconds = fields.Integer(
        string='Tiempo mínimo para completar el formulario (segundos)',
        default=3,
        help='Una solicitud web enviada antes de este tiempo desde que se abrió la página se considera un bot.',
        config_parameter='cotizador.quote_min_seconds',
    )
    cotizador_captcha_configured = fields.Boolean(compute='_compute_cotizador_captcha_configured')
    cotizador_matrix_currency_id = fields.Many2one(
        related='company_id.cotizador_matrix_currency_id', readonly=False)
    cotizador_tax_id = fields.Many2one(related='company_id.cotizador_tax_id', readonly=False)
    cotizador_pricelist_id = fields.Many2one(related='company_id.cotizador_pricelist_id', readonly=False)
    cotizador_condiciones_generales_default = fields.Text(
        string='Condiciones Generales Predeterminadas',
        help='Texto constante estándar de condiciones comerciales que se incluirá automáticamente en todas las nuevas cotizaciones.',
    )

    def _compute_cotizador_captcha_configured(self):
        params = self.env['ir.config_parameter'].sudo()
        configured = bool(params.get_param('recaptcha_private_key') or params.get_param('cf.turnstile_secret_key'))
        for settings in self:
            settings.cotizador_captcha_configured = configured

    def set_values(self):
        super().set_values()
        self.env['ir.config_parameter'].sudo().set_param(
            'cotizador.condiciones_generales_default',
            self.cotizador_condiciones_generales_default or ''
        )

    def get_values(self):
        res = super().get_values()
        from .sale_order_inherit import DEFAULT_CONDICIONES_GENERALES
        val = self.env['ir.config_parameter'].sudo().get_param(
            'cotizador.condiciones_generales_default',
            default=DEFAULT_CONDICIONES_GENERALES
        )
        res['cotizador_condiciones_generales_default'] = val
        return res
