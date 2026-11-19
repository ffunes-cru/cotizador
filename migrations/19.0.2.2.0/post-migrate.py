"""19.0.2.2.0: usuarios externos y clientes por concesionario (auditoría de seguridad 11/2026).

- Marca como externos a los usuarios internos con correo de otro dominio (res.users._cotizador_marcar_externos()).
- Cada cliente pasa a los concesionarios de sus cotizaciones y oportunidades; el resto de los contactos queda solo
  para el personal de Crucianelli (res.partner._cotizador_compartir_existentes()).
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    usuarios = env['res.users'].with_context(active_test=False).search([('share', '=', False)])
    marcados = usuarios._cotizador_marcar_externos()
    clientes = env['res.partner']._cotizador_compartir_existentes()
    _logger.info("Cotizador: %s usuario(s) marcados como externos; %s cliente(s) asignados a sus concesionarios",
                 len(marcados), clientes)
