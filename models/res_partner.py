"""@file
Contactos por concesionario: los usuarios externos (concesionarios) ven solo los clientes de su concesionario.

La visibilidad la deciden las reglas `rule_externo_*` (security/cotizador_security.xml) con el campo
`cotizador_concesionario_ids` del contacto comercial. Un cliente pasa a ser de un concesionario cuando:

- lo crea un usuario externo (queda en los concesionarios de ese usuario), o
- aparece en una cotización u oportunidad de ese concesionario (sale.order / crm.lead: _cotizador_compartir_cliente()).

Los usuarios internos de Crucianelli ven todos los contactos, como antes.

Un usuario externo no puede cargar dos veces el mismo CUIT en su concesionario (_cotizador_check_cuit_repetido()). Si
el CUIT es de un cliente de otro concesionario o de la base de Crucianelli, no se le avisa: carga su propia ficha, y
los reportes de Crucianelli agrupan por CUIT (models/sale_report.py).
"""
import re

from odoo import Command, api, fields, models
from odoo.exceptions import AccessError, ValidationError


def _solo_digitos(cuit):
    """CUIT sin guiones, espacios ni prefijo de país, para comparar.

    @param cuit Texto del CUIT (`vat`), o False.
    @return str con los dígitos ('' si no hay).
    """
    return re.sub(r'\D', '', cuit or '')


class ResPartner(models.Model):
    """Contacto (`res.partner`) con los concesionarios que lo ven."""
    _inherit = 'res.partner'

    cotizador_concesionario_ids = fields.Many2many(
        'crm.team', 'res_partner_cotizador_concesionario_rel', 'partner_id', 'team_id',
        string='Concesionarios',
        help='Concesionarios (equipos de ventas) cuyos usuarios externos ven este cliente y sus contactos. '
             'Se completa solo: con el concesionario de quien lo crea, si es externo, y con el de cada cotización u '
             'oportunidad en la que aparece. El personal de Crucianelli ve todos los contactos.',
    )

    def _cotizador_es_externo(self):
        """El usuario actual es externo y no corre con sudo.

        @return bool.
        """
        return not self.env.su and self.env.user._cotizador_es_externo()

    @api.model_create_multi
    def create(self, vals_list):
        """Crea contactos; los de un usuario externo quedan en sus concesionarios.

        @param vals_list Lista de diccionarios de valores.
        @return Los contactos creados.
        @throws AccessError Si un usuario externo indica a mano los concesionarios.
        """
        externo = self._cotizador_es_externo()
        if externo:
            if any('cotizador_concesionario_ids' in vals for vals in vals_list):
                raise AccessError(self.env._('Solo el personal de Crucianelli asigna los concesionarios de un cliente.'))
            # Un contacto hijo hereda los concesionarios de su empresa: la empresa tiene que ser visible para él
            self.browse([vals['parent_id'] for vals in vals_list if vals.get('parent_id')]).check_access('read')
        partners = super().create(vals_list)
        if externo:
            partners._cotizador_compartir_con(self.env.user._cotizador_concesionarios())
            partners._cotizador_check_cuit_repetido()
        return partners

    def write(self, vals):
        """Escribe; un usuario externo no puede cambiar los concesionarios de un cliente.

        @param vals Valores a escribir.
        @return True.
        @throws AccessError Si un usuario externo cambia los concesionarios.
        @throws ValidationError Si un usuario externo pone un CUIT que su concesionario ya tiene cargado.
        """
        externo = self._cotizador_es_externo()
        if 'cotizador_concesionario_ids' in vals and externo:
            raise AccessError(self.env._('Solo el personal de Crucianelli asigna los concesionarios de un cliente.'))
        res = super().write(vals)
        if 'vat' in vals and externo:
            self._cotizador_check_cuit_repetido()
        return res

    def _cotizador_check_cuit_repetido(self):
        """Un usuario externo no carga dos veces el mismo CUIT en su concesionario.

        Solo compara con los clientes de sus concesionarios, que ya puede ver: no revela si el CUIT existe en otro
        concesionario o en la base de Crucianelli. Los contactos hijos no cuentan (copian el CUIT de su empresa).

        @throws ValidationError Con el cliente que ya tiene ese CUIT.
        """
        equipos = self.env.user._cotizador_concesionarios()
        nuevos = self.filtered(lambda p: not p.parent_id and _solo_digitos(p.vat))
        if not equipos or not nuevos:
            return
        existentes = self.sudo().search_fetch([
            ('id', 'not in', nuevos.ids), ('parent_id', '=', False), ('vat', '!=', False),
            ('cotizador_concesionario_ids', 'in', equipos.ids)], ['name', 'vat'])
        por_cuit = {_solo_digitos(p.vat): p for p in existentes}
        for partner in nuevos:
            repetido = por_cuit.get(_solo_digitos(partner.vat))
            if repetido:
                raise ValidationError(self.env._(
                    'Tu concesionario ya tiene un cliente con el CUIT %(cuit)s: «%(cliente)s». Buscalo y usá ese.',
                    cuit=partner.vat, cliente=repetido.name))
            por_cuit[_solo_digitos(partner.vat)] = partner

    def _cotizador_compartir_con(self, equipos):
        """Agrega concesionarios al contacto comercial de cada contacto (sus contactos hijos los heredan).

        Un usuario externo solo comparte contactos que ya puede leer: Odoo no verifica la lectura al escribir un
        many2one (p. ej. el cliente de una cotización por RPC), y sin este control podría quedarse con cualquiera.

        @param equipos crm.team a agregar.
        @throws AccessError Si un usuario externo comparte un contacto que no puede leer.
        """
        if not equipos or not self:
            return
        if self._cotizador_es_externo():
            self.check_access('read')
        for partner in self.commercial_partner_id:
            faltan = equipos - partner.sudo().cotizador_concesionario_ids
            if faltan:
                partner.sudo().write({'cotizador_concesionario_ids': [Command.link(t.id) for t in faltan]})

    @api.model
    def _cotizador_compartir_existentes(self):
        """Datos anteriores a la regla: cada cliente pasa a los concesionarios de sus cotizaciones y oportunidades.

        El resto de los contactos queda solo para el personal de Crucianelli. Lo usa la migración 19.0.2.2.0.

        @return Cantidad de clientes que quedaron con algún concesionario.
        """
        pares = set()
        for model in ('sale.order', 'crm.lead'):
            records = self.env[model].sudo().with_context(active_test=False).search(
                [('partner_id', '!=', False), ('team_id', '!=', False)])
            pares |= {(r.partner_id.commercial_partner_id.id, r.team_id.id) for r in records}
        Team = self.env['crm.team'].sudo()
        clientes = self.sudo().browse()
        for partner_id, team_id in pares:
            partner = self.sudo().browse(partner_id)
            partner._cotizador_compartir_con(Team.browse(team_id))
            clientes |= partner
        return len(clientes)
