"""@file
Equipo de ventas = concesionario, con su supervisor de zona (niveles de usuario, issue #1)."""
from odoo import fields, models


class CrmTeam(models.Model):
    """Equipo de ventas (`crm.team`): cada concesionario es un equipo. Su líder estándar (`user_id`) es el
    usuario del concesionario y sus miembros, los vendedores.

    El supervisor de zona es el "líder de los líderes": ve en solo lectura lo de todos los equipos que
    supervisa (reglas en security/cotizador_security.xml). La zona son los equipos con el mismo supervisor.
    """
    _inherit = 'crm.team'

    cotizador_supervisor_id = fields.Many2one(
        'res.users', string='Supervisor de Zona', tracking=True, check_company=True,
        domain=[('share', '=', False)],
        help='Usuario con el nivel Supervisor de Zona que ve, en solo lectura, las cotizaciones y '
             'oportunidades de este concesionario.',
    )
