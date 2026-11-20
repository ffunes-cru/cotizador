"""@file
Usuarios externos: los usuarios internos que no son de Crucianelli (concesionarios y sus vendedores).

Se marcan con el grupo *Usuario externo (concesionario)* (`cotizador.group_usuario_externo`), que activa las reglas
`rule_externo_*`. El grupo se agrega solo al crear un usuario interno, o al cambiarle el correo, si su dominio no es
de Crucianelli (parámetro `cotizador.dominios_internos`); se puede cambiar a mano en la ficha del usuario. Nunca se
quita solo.
"""
from odoo import SUPERUSER_ID, Command, api, models

## Dominios del personal de Crucianelli si el parámetro `cotizador.dominios_internos` no está definido.
DOMINIOS_INTERNOS = 'crucianelli.com'


class ResUsers(models.Model):
    """Usuario (`res.users`): externo o personal de Crucianelli."""
    _inherit = 'res.users'

    def _cotizador_es_externo(self):
        """El usuario tiene el grupo *Usuario externo (concesionario)*.

        @return bool.
        """
        self.ensure_one()
        return self.has_group('cotizador.group_usuario_externo')

    def _cotizador_concesionarios(self):
        """Concesionarios del usuario: los equipos que lidera o de los que es miembro.

        @return crm.team (sudo).
        """
        self.ensure_one()
        Team = self.env['crm.team'].sudo()
        miembro = self.env['crm.team.member'].sudo().search([('user_id', '=', self.id)]).crm_team_id
        return miembro | Team.search([('user_id', '=', self.id)])

    def _cotizador_correo_es_interno(self):
        """El correo del usuario (el login, o el email si el login no es un correo) es de Crucianelli.

        Un usuario sin correo (el administrador, OdooBot) cuenta como interno.

        @return bool.
        """
        self.ensure_one()
        direccion = self.login if '@' in (self.login or '') else self.email or ''
        if '@' not in direccion:
            return True
        dominios = self.env['ir.config_parameter'].sudo().get_param('cotizador.dominios_internos', DOMINIOS_INTERNOS)
        permitidos = {d.strip().lower().lstrip('@') for d in dominios.split(',') if d.strip()}
        return direccion.rsplit('@', 1)[1].strip().lower() in permitidos

    def _cotizador_marcar_externos(self):
        """Agrega el grupo de usuario externo a los usuarios internos con correo de otro dominio.

        No toca a los administradores (Ajustes), al superusuario ni a los usuarios de portal.

        @return Los usuarios marcados.
        """
        grupo = self.env.ref('cotizador.group_usuario_externo')
        marcar = self.filtered(lambda u: u.id != SUPERUSER_ID and not u.share
                               and not u.has_group('base.group_system')
                               and grupo not in u.group_ids
                               and not u._cotizador_correo_es_interno())
        if marcar:
            marcar.sudo().write({'group_ids': [Command.link(grupo.id)]})
        return marcar

    @api.model_create_multi
    def create(self, vals_list):
        """Crea usuarios y marca como externos a los internos de otro dominio.

        @param vals_list Lista de diccionarios de valores.
        @return Los usuarios creados.
        """
        users = super().create(vals_list)
        users._cotizador_marcar_externos()
        return users

    def write(self, vals):
        """Escribe y, si cambia el correo o el usuario pasa de portal a interno, lo marca como externo si corresponde.

        Cambiar los grupos de un usuario interno no lo vuelve a marcar: quitarle el grupo a mano se respeta.

        @param vals Valores a escribir.
        @return True.
        """
        eran_portal = self.filtered('share') if 'group_ids' in vals else self.browse()
        res = super().write(vals)
        if {'login', 'email'} & set(vals):
            self._cotizador_marcar_externos()
        elif eran_portal:
            eran_portal.filtered(lambda u: not u.share)._cotizador_marcar_externos()
        return res
