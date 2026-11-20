"""@file
Usuarios externos (concesionarios): ven solo los clientes de su concesionario, nada sin vendedor de otros equipos y
ninguna cuenta bancaria (auditoría de seguridad 11/2026, security/cotizador_security.xml `rule_externo_*`)."""
from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestVisibilidadExternos(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.grupo_externo = cls.env.ref('cotizador.group_usuario_externo')

        def usuario(login, *grupos):
            return new_test_user(cls.env, login=login, groups=','.join(('base.group_user',) + grupos))

        cls.lider_a = usuario('lider@conce-a.com.ar', 'cotizador.group_lider_concesionario')
        cls.vendedor_a = usuario('vendedor@conce-a.com.ar', 'sales_team.group_sale_salesman')
        cls.lider_b = usuario('lider@conce-b.com.ar', 'cotizador.group_lider_concesionario')
        cls.interno = usuario('vendedor@crucianelli.com', 'sales_team.group_sale_salesman')
        Team = cls.env['crm.team']
        cls.equipo_a = Team.create({'name': 'Concesionario A', 'user_id': cls.lider_a.id,
                                    'member_ids': [Command.set(cls.vendedor_a.ids)]})
        cls.equipo_b = Team.create({'name': 'Concesionario B', 'user_id': cls.lider_b.id})
        # Base de clientes cargada por Crucianelli (la copia de SAP), con una cuenta bancaria
        cls.cliente_sap = cls.env['res.partner'].create({
            'name': 'Cliente de la base de Crucianelli', 'is_company': True, 'vat': '20123456789', 'street': 'Ruta 8 km 1'})
        cls.cuenta = cls.env['res.partner.bank'].create({'partner_id': cls.cliente_sap.id, 'acc_number': '0000003100000000000001'})

    def _ve(self, usuario, registro):
        return bool(registro.with_user(usuario).search_count([('id', '=', registro.id)]))

    # --- Quién es externo ---------------------------------------------------------------------------------------

    def test_externos_por_dominio_del_correo(self):
        for externo in (self.lider_a, self.vendedor_a, self.lider_b):
            self.assertIn(self.grupo_externo, externo.group_ids, externo.login)
        self.assertNotIn(self.grupo_externo, self.interno.group_ids)
        admin = new_test_user(self.env, login='admin@gmail.com', groups='base.group_user,base.group_system')
        self.assertNotIn(self.grupo_externo, admin.group_ids, 'a un administrador nunca se lo marca')
        sin_correo = self.env['res.users'].create({'name': 'Sin correo', 'login': 'sin_correo'})
        self.assertNotIn(self.grupo_externo, sin_correo.group_ids)

        self.env['ir.config_parameter'].sudo().set_param('cotizador.dominios_internos', 'crucianelli.com, @conce-c.com.ar')
        self.assertNotIn(self.grupo_externo, new_test_user(self.env, login='x@conce-c.com.ar').group_ids)

    def test_quitar_el_grupo_a_mano_se_respeta(self):
        self.vendedor_a.write({'group_ids': [Command.unlink(self.grupo_externo.id)]})
        self.vendedor_a.write({'group_ids': [Command.link(self.env.ref('sales_team.group_sale_salesman').id)]})
        self.assertNotIn(self.grupo_externo, self.vendedor_a.group_ids)
        # Cambiar el correo vuelve a evaluar
        self.interno.login = 'vendedor@gmail.com'
        self.assertIn(self.grupo_externo, self.interno.group_ids)

    def test_portal_que_pasa_a_interno(self):
        portal = new_test_user(self.env, login='cliente@campo.com.ar', groups='base.group_portal')
        self.assertNotIn(self.grupo_externo, portal.group_ids)
        portal.write({'group_ids': [Command.unlink(self.env.ref('base.group_portal').id),
                                    Command.link(self.env.ref('base.group_user').id)]})
        self.assertIn(self.grupo_externo, portal.group_ids)

    # --- Contactos ----------------------------------------------------------------------------------------------

    def test_la_base_de_crucianelli_no_la_ven_los_externos(self):
        for externo in (self.lider_a, self.vendedor_a, self.lider_b):
            self.assertFalse(self._ve(externo, self.cliente_sap), externo.login)
        self.assertTrue(self._ve(self.interno, self.cliente_sap))

    def test_el_cliente_que_carga_un_externo_es_de_su_concesionario(self):
        cliente = self.env['res.partner'].with_user(self.vendedor_a).create({'name': 'Cliente de A', 'is_company': True})
        self.assertEqual(cliente.sudo().cotizador_concesionario_ids, self.equipo_a)
        self.assertTrue(self._ve(self.vendedor_a, cliente))
        self.assertTrue(self._ve(self.lider_a, cliente), 'el líder ve los clientes de sus vendedores')
        self.assertFalse(self._ve(self.lider_b, cliente))
        self.assertTrue(self._ve(self.interno, cliente))
        # Los contactos de ese cliente lo heredan
        contacto = self.env['res.partner'].with_user(self.lider_a).create({'name': 'Encargado', 'parent_id': cliente.id})
        self.assertTrue(self._ve(self.vendedor_a, contacto))
        self.assertFalse(self._ve(self.lider_b, contacto))

    def test_ve_al_personal_y_a_la_empresa(self):
        """Lo que aparece en sus cotizaciones (vendedor, seguidores, empresa) tiene que poder leerse."""
        visibles = self.env['res.partner'].with_user(self.lider_b).search([('id', 'in', (
            self.interno.partner_id | self.lider_a.partner_id | self.env.company.partner_id).ids)])
        self.assertEqual(len(visibles), 3)

    def test_un_externo_no_se_queda_con_clientes_ajenos(self):
        """Odoo no verifica la lectura al escribir un many2one: sin el control, poner un cliente ajeno en una
        cotización lo compartiría con su concesionario."""
        Order = self.env['sale.order'].with_user(self.lider_b)
        with self.assertRaises(AccessError):
            Order.create({'partner_id': self.cliente_sap.id})
        propia = Order.create({'partner_id': self.env['res.partner'].with_user(self.lider_b).create({'name': 'De B'}).id})
        with self.assertRaises(AccessError):
            propia.write({'partner_id': self.cliente_sap.id})
        with self.assertRaises(AccessError):
            self.env['res.partner'].with_user(self.lider_b).create({'name': 'Hijo', 'parent_id': self.cliente_sap.id})
        self.assertFalse(self.cliente_sap.cotizador_concesionario_ids)

    def test_un_externo_no_cambia_los_concesionarios(self):
        cliente = self.env['res.partner'].with_user(self.lider_a).create({'name': 'Cliente de A'})
        with self.assertRaises(AccessError):
            cliente.with_user(self.lider_a).write({'cotizador_concesionario_ids': [Command.link(self.equipo_b.id)]})
        with self.assertRaises(AccessError):
            self.env['res.partner'].with_user(self.lider_a).create({
                'name': 'Otro', 'cotizador_concesionario_ids': [Command.link(self.equipo_b.id)]})

    def test_una_cotizacion_de_crucianelli_comparte_el_cliente_con_su_concesionario(self):
        self.assertFalse(self._ve(self.lider_a, self.cliente_sap))
        self.env['sale.order'].create({'partner_id': self.cliente_sap.id, 'user_id': self.vendedor_a.id,
                                       'team_id': self.equipo_a.id})
        self.assertTrue(self._ve(self.lider_a, self.cliente_sap))
        self.assertTrue(self._ve(self.vendedor_a, self.cliente_sap))
        self.assertFalse(self._ve(self.lider_b, self.cliente_sap))

    def test_el_externo_abre_su_cotizacion(self):
        cliente = self.env['res.partner'].with_user(self.vendedor_a).create({'name': 'Cliente de A'})
        orden = self.env['sale.order'].with_user(self.vendedor_a).create({'partner_id': cliente.id})
        datos = orden.with_user(self.vendedor_a).web_read({
            'partner_id': {'fields': {'display_name': {}}}, 'partner_invoice_id': {'fields': {'display_name': {}}},
            'user_id': {'fields': {'display_name': {}}}, 'team_id': {'fields': {'display_name': {}}},
            'company_id': {'fields': {'display_name': {}}}, 'lider_equipo_id': {'fields': {'display_name': {}}},
        })[0]
        self.assertEqual(datos['partner_id']['display_name'], 'Cliente de A')
        self.assertEqual(datos['team_id']['id'], self.equipo_a.id)

    # --- Cuentas bancarias, cotizaciones y oportunidades sin vendedor -------------------------------------------------

    def test_cuentas_bancarias(self):
        for externo in (self.lider_a, self.vendedor_a):
            self.assertFalse(self.env['res.partner.bank'].with_user(externo).search_count([]), externo.login)
        self.assertTrue(self._ve(self.interno, self.cuenta))

    def test_sin_vendedor_solo_de_su_concesionario(self):
        """La tienda web crea cotizaciones sin vendedor: la regla estándar se las mostraría a cualquier vendedor."""
        web = self.env['sale.order'].create({'partner_id': self.cliente_sap.id, 'user_id': False})
        self.assertFalse(web.user_id)
        self.assertFalse(self._ve(self.vendedor_a, web))
        self.assertFalse(self._ve(self.lider_b, web))
        self.assertTrue(self._ve(self.interno, web), 'el personal de Crucianelli sigue viéndolas')
        self.assertFalse(self.env['sale.order.line'].with_user(self.vendedor_a).search_count([('order_id', '=', web.id)]))

        sin_vendedor_de_a = self.env['sale.order'].create({'partner_id': self.cliente_sap.id, 'user_id': False,
                                                           'team_id': self.equipo_a.id})
        self.assertTrue(self._ve(self.lider_a, sin_vendedor_de_a))
        self.assertFalse(self._ve(self.lider_b, sin_vendedor_de_a))

        lead = self.env['crm.lead'].create({'name': 'Solicitud web', 'user_id': False, 'team_id': False})
        self.assertFalse(self._ve(self.vendedor_a, lead))
        self.assertTrue(self._ve(self.interno, lead))

    # --- Migración ---------------------------------------------------------------------------------------------------

    def test_migracion_datos_anteriores(self):
        """Antes de la regla: usuarios sin marcar y clientes sin concesionario."""
        orden = self.env['sale.order'].create({'partner_id': self.cliente_sap.id, 'user_id': self.lider_b.id,
                                               'team_id': self.equipo_b.id})
        self.cliente_sap.cotizador_concesionario_ids = False
        self.lider_b.write({'group_ids': [Command.unlink(self.grupo_externo.id)]})

        self.assertEqual(self.env['res.users'].search([('share', '=', False)])._cotizador_marcar_externos(), self.lider_b)
        self.assertGreaterEqual(self.env['res.partner']._cotizador_compartir_existentes(), 1)
        self.assertEqual(self.cliente_sap.cotizador_concesionario_ids, orden.team_id)
        self.assertTrue(self._ve(self.lider_b, self.cliente_sap))
