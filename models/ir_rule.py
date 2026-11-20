"""@file
Usuarios externos (concesionarios): no ven nada de Ausencias (issue #23).

Ausencias (`hr_holidays`) no es dependencia del cotizador, así que no se le pueden escribir reglas en XML: el bloqueo
se aplica por nombre de modelo y solo tiene efecto si el módulo está instalado. Las demás reglas de externos están en
security/cotizador_security.xml (`rule_externo_*`).
"""
from odoo import models
from odoo.fields import Domain

## Modelos que un usuario externo no ve: el calendario de ausencias del personal y sus datos.
MODELOS_OCULTOS_EXTERNOS = frozenset({
    'hr.leave', 'hr.leave.allocation', 'hr.leave.report', 'hr.leave.report.calendar',
})


class IrRule(models.Model):
    """Reglas de acceso (`ir.rule`): para un externo, los modelos de MODELOS_OCULTOS_EXTERNOS quedan vacíos."""
    _inherit = 'ir.rule'

    def _compute_domain(self, model_name, mode="read"):
        """Dominio de acceso; para un usuario externo, ningún registro de los modelos ocultos.

        @param model_name Modelo.
        @param mode Operación (read, write, create, unlink).
        @return Domain.
        """
        domain = super()._compute_domain(model_name, mode)
        if model_name in MODELOS_OCULTOS_EXTERNOS and not self.env.su and self.env.user._cotizador_es_externo():
            return Domain.FALSE
        return domain
