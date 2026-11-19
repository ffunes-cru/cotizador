"""Niveles de usuario (issue #1): vendedor, líder de concesionario, supervisor de zona y gerencia."""
from odoo.exceptions import AccessError
from odoo.tests import new_test_user, tagged

from .common import MATRIX_CSV, CotizadorCase


@tagged('post_install', '-at_install')
class TestNivelesUsuario(CotizadorCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._import(MATRIX_CSV)
        cls.pionera = cls._imported('modelo_pionera')

        def usuario(login, *grupos):
            return new_test_user(cls.env, login=login, groups=','.join(('base.group_user',) + grupos))

        cls.vendedor_a = usuario('vendedor_a', 'sales_team.group_sale_salesman')
        cls.vendedor_b = usuario('vendedor_b', 'sales_team.group_sale_salesman')
        cls.lider_a = usuario('lider_a', 'cotizador.group_lider_concesionario')
        cls.lider_b = usuario('lider_b', 'cotizador.group_lider_concesionario')
        # Supervisor y gerencia son personal de Crucianelli; vendedores y líderes, de los concesionarios (externos)
        cls.supervisor = usuario('supervisor@crucianelli.com', 'cotizador.group_supervisor_zona')
        cls.gerente = usuario('gerente@crucianelli.com', 'sales_team.group_sale_salesman_all_leads')

        Team = cls.env['crm.team']
        cls.conc_a = Team.create({'name': 'Concesionario A', 'user_id': cls.lider_a.id,
                                  'member_ids': [(6, 0, cls.vendedor_a.ids)],
                                  'cotizador_supervisor_id': cls.supervisor.id})
        cls.conc_b = Team.create({'name': 'Concesionario B', 'user_id': cls.lider_b.id,
                                  'member_ids': [(6, 0, cls.vendedor_b.ids)]})

        def cotizacion(usuario, equipo):
            return cls.env['sale.order'].create({'partner_id': cls.partner.id, 'pricelist_id': cls.pricelist.id,
                                                 'user_id': usuario.id, 'team_id': equipo.id})

        cls.cot_vendedor_a = cotizacion(cls.vendedor_a, cls.conc_a)
        cls.cot_lider_a = cotizacion(cls.lider_a, cls.conc_a)
        cls.cot_vendedor_b = cotizacion(cls.vendedor_b, cls.conc_b)
        cls.todas = cls.cot_vendedor_a | cls.cot_lider_a | cls.cot_vendedor_b

        def oportunidad(usuario, equipo):
            return cls.env['crm.lead'].create({'name': f'Oportunidad {usuario.login}', 'type': 'opportunity',
                                               'user_id': usuario.id, 'team_id': equipo.id})

        cls.op_vendedor_a = oportunidad(cls.vendedor_a, cls.conc_a)
        cls.op_vendedor_b = oportunidad(cls.vendedor_b, cls.conc_b)

    def _ve(self, usuario, registros):
        """Registros de `registros` que el usuario encuentra al buscar (aplica las reglas)."""
        return registros.with_user(usuario).search([('id', 'in', registros.ids)])

    def test_concesionario_es_el_lider_del_equipo_del_vendedor(self):
        self.assertEqual(self.cot_vendedor_a.lider_equipo_id, self.lider_a)
        # Odoo calcula el equipo a partir del vendedor: cambiar el vendedor cambia el concesionario
        cotizacion = self.env['sale.order'].create({'partner_id': self.partner.id, 'pricelist_id': self.pricelist.id,
                                                    'user_id': self.vendedor_a.id})
        self.assertEqual((cotizacion.team_id, cotizacion.lider_equipo_id), (self.conc_a, self.lider_a))
        cotizacion.user_id = self.vendedor_b
        self.assertEqual((cotizacion.team_id, cotizacion.lider_equipo_id), (self.conc_b, self.lider_b))
        concesionario_a = self.env['sale.order'].search([('lider_equipo_id', '=', self.lider_a.id)])
        self.assertIn(self.cot_vendedor_a, concesionario_a)
        self.assertNotIn(self.cot_vendedor_b, concesionario_a)

    def test_vendedor_solo_lo_suyo(self):
        self.assertEqual(self._ve(self.vendedor_a, self.todas), self.cot_vendedor_a)
        with self.assertRaises(AccessError):
            self.cot_lider_a.with_user(self.vendedor_a).read(['name'])

    def test_lider_todo_su_concesionario(self):
        self.assertEqual(self._ve(self.lider_a, self.todas), self.cot_vendedor_a | self.cot_lider_a)
        self.assertEqual(self._ve(self.lider_a, self.op_vendedor_a | self.op_vendedor_b), self.op_vendedor_a)
        # Edita lo de sus vendedores, también las líneas
        self.cot_vendedor_a.with_user(self.lider_a).write({'client_order_ref': 'REF-LIDER'})
        self.assertEqual(self.cot_vendedor_a.client_order_ref, 'REF-LIDER')
        self.op_vendedor_a.with_user(self.lider_a).write({'priority': '2'})
        with self.assertRaises(AccessError):
            self.cot_vendedor_b.with_user(self.lider_a).read(['name'])

    def test_supervisor_lee_su_zona_sin_editar(self):
        self.assertEqual(self._ve(self.supervisor, self.todas), self.cot_vendedor_a | self.cot_lider_a)
        self.assertEqual(self._ve(self.supervisor, self.op_vendedor_a | self.op_vendedor_b), self.op_vendedor_a)
        with self.assertRaises(AccessError):
            self.cot_vendedor_a.with_user(self.supervisor).write({'client_order_ref': 'X'})
        with self.assertRaises(AccessError):
            self.op_vendedor_a.with_user(self.supervisor).write({'priority': '2'})
        with self.assertRaises(AccessError):
            self.cot_vendedor_b.with_user(self.supervisor).read(['name'])

    def test_supervisor_crea_y_asigna_a_un_concesionario(self):
        Order = self.env['sale.order'].with_user(self.supervisor)
        propia = Order.create({'partner_id': self.partner.id, 'pricelist_id': self.pricelist.id,
                               'equipo_cotizado_id': self.pionera.id, 'team_id': self.conc_a.id})
        self.assertEqual(propia.user_id, self.supervisor)
        propia.write({'client_order_ref': 'MIA'})  # mientras es suya la edita
        oportunidad = propia.sudo().opportunity_id
        self.assertEqual(oportunidad.user_id, self.supervisor)

        # Asignarla al concesionario: pasa al líder y la oportunidad la sigue (sincronización con sudo)
        propia.write({'user_id': self.lider_a.id})
        self.assertEqual(oportunidad.user_id, self.lider_a)
        self.assertEqual(oportunidad.lider_equipo_id, self.lider_a)
        self.assertEqual(propia.lider_equipo_id, self.lider_a)  # Concesionario = líder del equipo del vendedor
        self.assertIn(propia, self._ve(self.lider_a, propia))
        # Desde ahí el supervisor solo la ve
        self.assertEqual(propia.with_user(self.supervisor).read(['client_order_ref'])[0]['client_order_ref'], 'MIA')
        with self.assertRaises(AccessError):
            propia.write({'client_order_ref': 'OTRA'})

    def test_cambio_de_concesionario_actualiza_la_oportunidad(self):
        cotizacion = self.env['sale.order'].create({
            'partner_id': self.partner.id, 'pricelist_id': self.pricelist.id, 'equipo_cotizado_id': self.pionera.id,
            'user_id': self.vendedor_a.id, 'team_id': self.conc_a.id})
        cotizacion.write({'team_id': self.conc_b.id, 'user_id': self.vendedor_b.id})
        self.assertEqual(cotizacion.opportunity_id.team_id, self.conc_b)
        self.assertEqual(cotizacion.opportunity_id.lider_equipo_id, self.lider_b)
        self.assertEqual(cotizacion.lider_equipo_id, self.lider_b)

    def test_gerencia_ve_todo(self):
        self.assertEqual(self._ve(self.gerente, self.todas), self.todas)
        self.cot_vendedor_b.with_user(self.gerente).write({'client_order_ref': 'GERENCIA'})
