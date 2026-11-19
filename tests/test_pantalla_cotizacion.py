"""@file
Pantalla de la cotización (issue #3): botones de la cabecera, firma del cliente en el menú de
acciones, columna Cantidad y planes de pago a imprimir."""
from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import MATRIX_CSV, CotizadorCase

## Botones de la cabecera que ordena el cotizador, por (name, id) del botón estándar.
BOTONES = {
    ('action_preview_sale_order', None): 'Vista previa',
    ('action_quotation_send', 'quotation_send_primary'): 'Enviar',
    ('action_quotation_send', 'quotation_send'): 'Enviar',
    ('print_quotation', None): 'Imprimir',
    ('action_quotation_send', 'send_proforma_primary'): 'Generar Factura Proforma',
    ('action_quotation_send', 'send_proforma'): 'Generar Factura Proforma',
    ('action_confirm', 'action_confirm'): 'Confirmar Pedido',
    ('action_confirm', None): 'Confirmar Pedido',
    ('action_cancel', None): 'Cancelar',
}


@tagged('post_install', '-at_install')
class TestPantallaCotizacion(CotizadorCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._import(MATRIX_CSV)
        cls.monitor = cls._imported('acc_pionera_monitor')
        cls.plan = cls.env['cotizador.plan.pago.template'].create({
            'name': 'Cheques', 'tipo': 'cheques',
            'line_ids': [Command.create({'plan_cheques': '30-60-90', 'descuento': 5})],
        })

    def test_orden_de_la_cabecera(self):
        """Vista previa, Enviar, Imprimir, Generar Factura Proforma, Confirmar Pedido, Cancelar.

        Odoo tiene dos Enviar, dos Proforma y dos Confirmar (uno por estado): van juntos. Los
        botones con `string` traen el texto pedido; Vista previa, Enviar, Imprimir y Cancelar
        conservan el estándar traducido.
        """
        arch = self.env.ref('sale.view_order_form')._get_combined_arch()
        orden, textos = [], {}
        for button in arch.xpath('//header/button'):
            clave = BOTONES.get((button.get('name'), button.get('id')))
            if clave:
                textos[clave] = button.get('string')
                if not orden or orden[-1] != clave:
                    orden.append(clave)
        self.assertEqual(orden, ['Vista previa', 'Enviar', 'Imprimir', 'Generar Factura Proforma',
                                 'Confirmar Pedido', 'Cancelar'])
        self.assertEqual(textos['Generar Factura Proforma'], 'Generar Factura Proforma')
        self.assertEqual(textos['Confirmar Pedido'], 'Confirmar Pedido')
        self.assertFalse(arch.xpath("//header/button[@name='action_enable_portal_confirmation']"))

    def test_controles_de_lineas(self):
        """Cotizar Equipo, Añadir Equipo Usado y Añadir Descuento, resaltados en verde."""
        arch = self.env.ref('sale.view_order_form')._get_combined_arch()
        for control in arch.xpath("//field[@name='order_line']//control"):
            botones = control.xpath('button')
            self.assertEqual([b.get('string') for b in botones],
                             ['Cotizar Equipo', 'Añadir Equipo Usado', 'Añadir Descuento'])
            self.assertTrue(all("btn-success" in b.get("class") for b in botones))

    def _firma(self, order, accion):
        self.env.ref(f'cotizador.action_server_{accion}_portal_confirmation').with_context(
            active_model='sale.order', active_id=order.id, active_ids=order.ids).run()

    def test_firma_del_cliente_desde_el_menu_de_acciones(self):
        order = self._order(portal_confirmation_mode='salesman_enables')
        self._firma(order, 'enable')
        self.assertTrue(order.portal_confirmation_allowed)
        self.assertIn('habilitado', order.message_ids[0].body)
        with self.assertRaisesRegex(UserError, 'ya está habilitada'):
            self._firma(order, 'enable')
        self._firma(order, 'disable')
        self.assertFalse(order.portal_confirmation_allowed)
        with self.assertRaisesRegex(UserError, 'no está habilitada'):
            self._firma(order, 'disable')

    def test_firma_del_cliente_solo_en_cotizaciones_habilitadas_por_el_vendedor(self):
        """El menú de acciones se ve siempre: el método rechaza lo que el botón ocultaba."""
        solo_vendedor = self._order(portal_confirmation_mode='salesman_only')
        with self.assertRaisesRegex(UserError, 'Habilitado por el vendedor'):
            self._firma(solo_vendedor, 'enable')
        cancelada = self._order(portal_confirmation_mode='salesman_enables')
        cancelada.state = 'cancel'
        with self.assertRaisesRegex(UserError, 'borrador o enviada'):
            self._firma(cancelada, 'enable')
        self.assertFalse(solo_vendedor.portal_confirmation_allowed or cancelada.portal_confirmation_allowed)

    def test_columna_cantidad_solo_si_alguna_linea_no_va_de_a_uno(self):
        order = self._order(order_line=[
            Command.create({'display_type': 'line_section', 'name': 'Accesorios', 'product_uom_qty': 0}),
            Command.create({'product_id': self.monitor.id, 'product_uom_qty': 1}),
        ])
        self.assertFalse(order.cotizador_muestra_cantidad)
        order.order_line.filtered('product_id').product_uom_qty = 16
        self.assertTrue(order.cotizador_muestra_cantidad)

    def test_planes_a_imprimir_arrancan_vacios(self):
        """Sin planes tildados, el PDF no lleva la hoja de planes; con planes, solo esos."""
        order = self._order(order_line=[Command.create({'product_id': self.monitor.id})])
        self.assertFalse(order.plan_pago_line_ids)
        self.assertEqual(order.with_context(discard_logo_check=True).print_quotation()['context']['print_planes_mode'], 'none')
        Report = self.env['ir.actions.report']
        for reporte in ('sale.action_report_saleorder', 'cotizador.action_report_cotizacion_planes'):
            html = str(Report._render_qweb_html(reporte, order.ids)[0])
            self.assertNotIn('Planes de Pago Disponibles', html, reporte)

        order.plan_pago_line_ids = self.plan.line_ids
        self.assertEqual(order.with_context(discard_logo_check=True).print_quotation()['context']['print_planes_mode'], 'filtered')
        html = str(Report._render_qweb_html('cotizador.action_report_cotizacion_planes', order.ids)[0])
        self.assertIn('Planes de Pago Disponibles', html)
        self.assertIn('30-60-90', html)

    def test_buscar_mas_planes_agrupados_por_plantilla(self):
        """Issue #9: "Buscar más..." de Planes de Pago a Imprimir abre las opciones agrupadas por plantilla."""
        arch = self.env.ref('sale.view_order_form')._get_combined_arch()
        campo = arch.xpath("//field[@name='plan_pago_line_ids']")[0]
        self.assertIn("'search_default_agrupar_plantilla': 1", campo.get('context'))
        self.assertIn("('template_id.active', '=', True)", campo.get('domain'))

        views = self.env['cotizador.plan.pago.template.line'].get_views([(False, 'list'), (False, 'search')])['views']
        self.assertIn('name="agrupar_plantilla"', views['search']['arch'])
        self.assertIn('expand="1"', views['list']['arch'])
        # Las plantillas archivadas no se ofrecen
        archivada = self.env['cotizador.plan.pago.template'].create({
            'name': 'Vieja', 'tipo': 'cheques', 'active': False,
            'line_ids': [Command.create({'plan_cheques': 'vieja', 'descuento': 1})],
        })
        ofrecidas = self.env['cotizador.plan.pago.template.line'].search([('template_id.active', '=', True)])
        self.assertIn(self.plan.line_ids, ofrecidas)
        self.assertNotIn(archivada.with_context(active_test=False).line_ids, ofrecidas)
