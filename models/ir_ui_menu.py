"""@file
Menú de apps sin las que no se usan (issue #23).

- Usuarios externos (concesionarios): sin Empleados, Ausencias, Sitio web, Tableros ni Aplicaciones.
- Personal de Crucianelli: sin Ausencias, salvo quien la gestiona (*Ausencias / Encargado* o más).

Ocultar un menú solo ordena la pantalla: lo que un externo no puede leer lo deciden las reglas
(security/cotizador_security.xml y models/ir_rule.py). Los menús de módulos que no están instalados se ignoran.
"""
from odoo import models

## Apps que no ve un usuario externo.
MENUS_OCULTOS_EXTERNOS = (
    'hr.menu_hr_root',
    'hr_holidays.menu_hr_holidays_root',
    'website.menu_website_configuration',
    'spreadsheet_dashboard.spreadsheet_dashboard_menu_root',
    'base.menu_management',
)
## Ausencias: solo la ve quien tiene este grupo.
GRUPO_AUSENCIAS = 'hr_holidays.group_hr_holidays_user'
MENU_AUSENCIAS = 'hr_holidays.menu_hr_holidays_root'


class IrUiMenu(models.Model):
    """Menú (`ir.ui.menu`) con las apps ocultas según el usuario."""
    _inherit = 'ir.ui.menu'

    def _cotizador_menus_ocultos(self):
        """Apps que no se le muestran al usuario actual.

        @return Lista de xmlids de menús raíz.
        """
        user = self.env.user
        if user._cotizador_es_externo():
            return list(MENUS_OCULTOS_EXTERNOS)
        grupo = self.env.ref(GRUPO_AUSENCIAS, raise_if_not_found=False)
        if grupo and grupo not in user.all_group_ids:
            return [MENU_AUSENCIAS]
        return []

    def _load_menus_blacklist(self):
        """Menús que no se cargan en el cliente web: los de Odoo más las apps ocultas del usuario.

        Al no cargarse la raíz, tampoco se cargan sus submenús.

        @return Lista de ids de ir.ui.menu.
        """
        res = super()._load_menus_blacklist()
        for xmlid in self._cotizador_menus_ocultos():
            menu = self.env.ref(xmlid, raise_if_not_found=False)
            if menu:
                res.append(menu.id)
        return res
