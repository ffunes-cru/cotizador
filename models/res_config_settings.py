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
    cotizador_condiciones_generales_default = fields.Text(
        string='Condiciones Generales Predeterminadas',
        help='Texto constante estándar de condiciones comerciales que se incluirá automáticamente en todas las nuevas cotizaciones.',
    )

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
