"""@file
Un concesionario no ve nada de otro, probado desde afuera: entra con usuario y contraseña y llama por JSON-RPC a los
mismos métodos que usa el navegador (listas, autocompletar, agrupar, abrir una ficha, mensajes).

No depende de cómo estén escritas las reglas (security/cotizador_security.xml): si alguien las cambia y deja un hueco
en alguna de estas vías, el test falla. Los datos del concesionario A llevan la marca SECRETO-A, y el test busca esa
marca en todo lo que le devuelve el servidor al concesionario B.
"""
import json

from odoo import Command
from odoo.tests import HttpCase, new_test_user, tagged
from odoo.tests.common import JsonRpcException

MARCA = 'SECRETO-A'


@tagged('post_install', '-at_install')
class TestExternosRpc(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        def usuario(login, *grupos):
            return new_test_user(cls.env, login=login, groups=','.join(('base.group_user',) + grupos))

        cls.lider_a = usuario('lider@conce-a.com.ar', 'cotizador.group_lider_concesionario')
        cls.vendedor_a = usuario('vendedor@conce-a.com.ar', 'sales_team.group_sale_salesman')
        cls.lider_b = usuario('lider@conce-b.com.ar', 'cotizador.group_lider_concesionario')
        cls.vendedor_b = usuario('vendedor@conce-b.com.ar', 'sales_team.group_sale_salesman')
        Team = cls.env['crm.team']
        Team.create({'name': 'Concesionario A', 'user_id': cls.lider_a.id, 'member_ids': [Command.set(cls.vendedor_a.ids)]})
        Team.create({'name': 'Concesionario B', 'user_id': cls.lider_b.id, 'member_ids': [Command.set(cls.vendedor_b.ids)]})

        # Lo que carga el concesionario A, como lo haría desde el navegador
        Partner = cls.env['res.partner'].with_user(cls.vendedor_a)
        cls.cliente_a = Partner.create({'name': f'{MARCA} Agro SA', 'is_company': True, 'vat': '30712345671',
                                        'email': 'secreto-a@agro.com.ar', 'city': f'{MARCA} Localidad'})
        cls.contacto_a = Partner.create({'name': f'{MARCA} Encargado', 'parent_id': cls.cliente_a.id})
        cls.cliente_a.with_user(cls.vendedor_a).message_post(body=f'{MARCA} nota sobre el cliente', message_type='comment')
        producto = cls.env['product.product'].create({'name': 'Sembradora', 'list_price': 100})
        cls.orden_a = cls.env['sale.order'].with_user(cls.vendedor_a).create({
            'partner_id': cls.cliente_a.id, 'note': f'{MARCA} condiciones',
            'order_line': [Command.create({'product_id': producto.id})]})
        cls.lead_a = cls.env['crm.lead'].with_user(cls.vendedor_a).create({
            'name': f'{MARCA} oportunidad', 'partner_id': cls.cliente_a.id})

    def _rpc(self, model, method, args=(), **kwargs):
        return self.make_jsonrpc_request(f'/web/dataset/call_kw/{model}/{method}', {
            'model': model, 'method': method, 'args': list(args), 'kwargs': kwargs})

    def _respuestas_de_busqueda(self):
        """Lo que ve el usuario autenticado por las vías de búsqueda del navegador."""
        nombre = {'display_name': {}}
        return {
            'contactos (lista)': self._rpc('res.partner', 'web_search_read', domain=[], specification={
                'display_name': {}, 'email': {}, 'vat': {}, 'city': {}, 'parent_id': nombre}),
            'contactos (autocompletar)': self._rpc('res.partner', 'name_search', name=MARCA),
            'contactos (autocompletar por CUIT)': self._rpc('res.partner', 'name_search', name='30712345671'),
            'contactos (agrupados)': self._rpc('res.partner', 'formatted_read_group', domain=[],
                                               groupby=['city'], aggregates=['__count']),
            'cotizaciones': self._rpc('sale.order', 'web_search_read', domain=[], specification={
                'display_name': {}, 'partner_id': nombre, 'note': {}}),
            'líneas de cotización': self._rpc('sale.order.line', 'web_search_read', domain=[], specification={
                'order_partner_id': nombre}),
            'oportunidades': self._rpc('crm.lead', 'web_search_read', domain=[], specification={
                'display_name': {}, 'partner_id': nombre}),
            'análisis de ventas': self._rpc('sale.report', 'formatted_read_group', domain=[],
                                            groupby=['partner_id', 'cotizador_cuit'], aggregates=['__count']),
            'mensajes': self._rpc('mail.message', 'search_read', domain=[('body', 'ilike', MARCA)],
                                  fields=['body', 'record_name']),
            'cuentas bancarias': self._rpc('res.partner.bank', 'search_read', domain=[], fields=['display_name']),
        }

    def test_otro_concesionario_no_ve_nada(self):
        for usuario in (self.lider_b, self.vendedor_b):
            self.authenticate(usuario.login, usuario.login)
            for via, respuesta in self._respuestas_de_busqueda().items():
                self.assertNotIn(MARCA, json.dumps(respuesta, ensure_ascii=False), f'{usuario.login} por {via}')

            # Abrir por id (un enlace pasado o un id adivinado) da error de acceso
            for model, record in (('res.partner', self.cliente_a), ('res.partner', self.contacto_a),
                                  ('sale.order', self.orden_a), ('crm.lead', self.lead_a)):
                with self.assertRaises(JsonRpcException, msg=f'{usuario.login} abre {model} {record.id}'):
                    self._rpc(model, 'web_read', [record.ids], specification={'display_name': {}})
            # El chatter del cliente no da error sin acceso: devuelve vacío
            mensajes = self.make_jsonrpc_request('/mail/thread/messages', {
                'thread_model': 'res.partner', 'thread_id': self.cliente_a.id})
            self.assertNotIn(MARCA, json.dumps(mensajes, ensure_ascii=False), f'{usuario.login} por el chatter')

    def test_control_su_concesionario_si_lo_ve(self):
        """Sin este control, el test anterior pasaría también si las llamadas no devolvieran nada."""
        for usuario in (self.lider_a, self.vendedor_a):
            self.authenticate(usuario.login, usuario.login)
            respuestas = self._respuestas_de_busqueda()
            for via in ('contactos (lista)', 'contactos (autocompletar)', 'contactos (autocompletar por CUIT)',
                        'cotizaciones', 'oportunidades', 'análisis de ventas', 'mensajes'):
                self.assertIn(MARCA, json.dumps(respuestas[via], ensure_ascii=False), f'{usuario.login} por {via}')
