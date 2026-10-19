"""@file
Asistente de solo lectura con el informe de la Central de Deudores del BCRA.

Lo crea y abre sale.order.action_ver_bcra_wizard() con los datos de
bcra_service.consultar_bcra_completo().
"""
from odoo import fields, models

## Situaciones crediticias del BCRA (selection de deuda y peor situación).
SITUACIONES = [
    ('1', '1 - Normal'),
    ('2', '2 - Con Seguimiento Especial'),
    ('3', '3 - Con Problemas'),
    ('4', '4 - Alto Riesgo de Insolvencia'),
    ('5', '5 - Irrecuperable'),
    ('6', '6 - Irrecuperable Técnica'),
]


def _default_currency(wizard):
    """Pesos argentinos: el BCRA informa los montos en ARS, sea cual sea la moneda de la compañía.

    @param wizard Registro (vacío) del asistente que pide el valor por defecto.
    @return res.currency ARS.
    """
    return wizard.env.ref('base.ARS')


class CotizadorBcraWizard(models.TransientModel):
    """Informe crediticio de un cliente (`cotizador.bcra.wizard`), con sus deudas y cheques."""
    _name = 'cotizador.bcra.wizard'
    _description = 'Consulta Situación Crediticia BCRA'

    partner_id = fields.Many2one('res.partner', string="Cliente", readonly=True)
    cuit = fields.Char(string="CUIT", readonly=True)
    denominacion = fields.Char(string="Denominación Oficial BCRA", readonly=True)
    consulta_fecha = fields.Datetime(string="Fecha Consulta", default=fields.Datetime.now, readonly=True)
    tiene_deuda = fields.Boolean(string="Tiene Deuda", readonly=True)
    peor_situacion = fields.Selection(SITUACIONES, string="Peor Situación", readonly=True)
    monto_total = fields.Monetary(string="Total Deuda Financiera", currency_field='currency_id', readonly=True)
    currency_id = fields.Many2one('res.currency', string="Moneda", default=_default_currency, readonly=True)
    alerta_mensaje = fields.Text(string="Mensaje de Situación", readonly=True)

    deuda_ids = fields.One2many('cotizador.bcra.wizard.deuda', 'wizard_id', string="Deudas Bancarias", readonly=True)
    cheque_ids = fields.One2many('cotizador.bcra.wizard.cheque', 'wizard_id', string="Cheques Rechazados", readonly=True)


class CotizadorBcraWizardDeuda(models.TransientModel):
    """Deuda con una entidad financiera en el último período informado."""
    _name = 'cotizador.bcra.wizard.deuda'
    _description = 'Línea de Deuda BCRA (Wizard)'
    _order = 'situacion desc, monto desc'

    wizard_id = fields.Many2one('cotizador.bcra.wizard', string="Wizard", ondelete='cascade')
    periodo = fields.Char(string="Período")
    entidad = fields.Char(string="Entidad Financiera")
    situacion = fields.Selection(SITUACIONES, string="Situación")
    monto = fields.Monetary(string="Monto ($)", currency_field='currency_id')
    currency_id = fields.Many2one(related='wizard_id.currency_id', string="Moneda", readonly=True)
    dias_atraso = fields.Integer(string="Días Atraso")
    observaciones = fields.Char(string="Observaciones")


class CotizadorBcraWizardCheque(models.TransientModel):
    """Cheque rechazado informado por el BCRA."""
    _name = 'cotizador.bcra.wizard.cheque'
    _description = 'Línea de Cheque Rechazado BCRA (Wizard)'
    _order = 'fecha_rechazo desc'

    wizard_id = fields.Many2one('cotizador.bcra.wizard', string="Wizard", ondelete='cascade')
    nro_cheque = fields.Char(string="Nº Cheque")
    fecha_rechazo = fields.Date(string="Fecha Rechazo")
    monto = fields.Monetary(string="Monto ($)", currency_field='currency_id')
    currency_id = fields.Many2one(related='wizard_id.currency_id', string="Moneda", readonly=True)
    causal = fields.Char(string="Causal")
    estado = fields.Char(string="Estado")
