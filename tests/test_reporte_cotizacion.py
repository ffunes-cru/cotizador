"""@file
Cantidad y Concesionario fuera del formulario (issue #10): PDF, portal y tarjeta del celular. La columna Cantidad
aparece solo si alguna línea no va de a 1, y el Concesionario es el mismo campo que en el formulario."""
from lxml import html as lxml_html

from odoo.tests import HttpCase, new_test_user, tagged

from .common import MATRIX_CSV, CotizadorCase, find_config, import_matrix


@tagged('post_install', '-at_install')
class TestReporteCotizacion(CotizadorCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._import(MATRIX_CSV)
        cls.config = cls._config('Pionera', '16 Lineas', '52 cm')
        cls.lider = new_test_user(cls.env, login='lider_reporte', name='Líder Reporte',
                                  groups='base.group_user,cotizador.group_lider_concesionario')
        cls.equipo = cls.env['crm.team'].create({'name': 'Concesionario Reporte', 'user_id': cls.lider.id})

    def _cotizacion(self, *accesorios, **vals):
        order = self._order(**vals)
        lineas = {line.product_id.name: line for line in self.config.accessory_line_ids}
        elegidas = self.env['sembradora.config.accessory.line'].union(*(lineas[n] for n in accesorios))
        self.env['cotizador.configurator.service'].confirm_configuration(order.id, self.config.id, elegidas.ids)
        return order

    def _pdf(self, order):
        """El HTML del reporte (el mismo que se convierte a PDF), parseado."""
        contenido = self.env['ir.actions.report']._render_qweb_html(
            'cotizador.action_report_cotizacion_planes', order.ids)[0]
        return lxml_html.fromstring(contenido)

    def _tabla(self, documento):
        return documento.xpath("//table[contains(@class, 'o_main_table')]")[0]

    def test_sin_columna_cantidad_si_todo_va_de_a_uno(self):
        tabla = self._tabla(self._pdf(self._cotizacion('Monitor', 'Kit Fino')))
        self.assertEqual([th.text_content().strip() for th in tabla.xpath('.//th')],
                         ['Descripción', 'Precio Unitario', 'Subtotal'])
        self.assertIn('width: 62%', tabla.xpath('.//th')[0].get('style'))
        secciones = tabla.xpath(".//tr[contains(@class, 'o_line_section')]/td")
        self.assertTrue(secciones)
        self.assertEqual({td.get('colspan') for td in secciones}, {'3'})
        self.assertTrue(all(len(tr.xpath('td')) == 3 for tr in tabla.xpath('.//tbody/tr[not(@class)]')))

    def test_cantidad_solo_en_las_lineas_que_no_van_de_a_uno(self):
        """Un sensor por línea (×16): aparece la columna, con la cantidad solo en esa línea."""
        tabla = self._tabla(self._pdf(self._cotizacion('Monitor', 'Sensor', 'Kit Fino')))
        self.assertEqual([th.text_content().strip() for th in tabla.xpath('.//th')],
                         ['Descripción', 'Cantidad', 'Precio Unitario', 'Subtotal'])
        self.assertEqual({td.get('colspan') for td in tabla.xpath(".//tr[contains(@class, 'o_line_section')]/td")},
                         {'4'})
        cantidades = {}
        for tr in tabla.xpath('.//tbody/tr[not(@class)]'):
            celdas = tr.xpath('td')
            nombre = celdas[0].xpath('.//div')[0].text_content().split()[0]   # primera línea, en negrita
            cantidades[nombre] = celdas[1].text_content().strip()
        self.assertEqual(cantidades['Sensor'], '16.00')
        self.assertEqual(cantidades['Monitor'], '')
        self.assertEqual(cantidades['Pionera'], '')

    def test_concesionario_es_el_lider_del_equipo(self):
        """Como el campo del formulario (lider_equipo_id): sin líder no cae al vendedor."""
        con_lider = self._pdf(self._cotizacion('Monitor', 'Kit Fino', team_id=self.equipo.id)).text_content()
        self.assertIn('Concesionario', con_lider)
        self.assertNotIn('LIDER EQUIPO', con_lider)
        self.assertIn('Líder Reporte', con_lider)

        sin_equipo = self._cotizacion('Monitor', 'Kit Fino')
        sin_equipo.team_id = False
        self.assertFalse(sin_equipo.lider_equipo_id)
        meta = self._pdf(sin_equipo).xpath("//div[@class='meta-label'][normalize-space()='Concesionario']"
                                           "/following-sibling::div[@class='meta-val']")[0]
        self.assertEqual(meta.text_content().strip(), '-')

    def test_tarjeta_del_celular_muestra_cantidad_solo_si_no_va_de_a_uno(self):
        arch = self.env.ref('sale.view_order_form')._get_combined_arch()
        bloque = arch.xpath("//field[@name='order_line']//kanban//field[@name='product_uom_qty']/..")[0]
        self.assertEqual(bloque.get('t-if'), 'record.product_uom_qty.raw_value !== 1')


@tagged('post_install', '-at_install')
class TestPortalCantidad(HttpCase):
    """La cotización en el portal (/my/orders/<id>): Cantidad con la misma regla que el formulario y el PDF."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import_matrix(cls.env, MATRIX_CSV)
        cls.config = find_config(cls.env, 'Pionera', '16 Lineas', '52 cm')
        cls.partner = cls.env['res.partner'].create({'name': 'Cliente Portal'})

    def _tabla(self, *accesorios):
        order = self.env['sale.order'].create({'partner_id': self.partner.id})
        lineas = {line.product_id.name: line for line in self.config.accessory_line_ids}
        elegidas = self.env['sembradora.config.accessory.line'].union(*(lineas[n] for n in accesorios))
        self.env['cotizador.configurator.service'].confirm_configuration(order.id, self.config.id, elegidas.ids)
        respuesta = self.url_open(order.get_portal_url())
        self.assertEqual(respuesta.status_code, 200)
        return lxml_html.fromstring(respuesta.content).xpath("//table[@id='sales_order_table']")[0]

    def assertSeccionesAlineadas(self, tabla):
        """El nombre de cada sección ocupa todas las columnas menos la del total, haya o no columna Cantidad."""
        columnas = len(tabla.xpath('.//thead//th'))
        self.assertEqual({td.get('colspan') for td in tabla.xpath(".//td[@name='td_section_name']")},
                         {str(columnas - 1)})

    def test_sin_columna_cantidad_si_todo_va_de_a_uno(self):
        tabla = self._tabla('Monitor', 'Kit Fino')
        self.assertFalse(tabla.xpath(".//th[@id='product_qty_header']"))
        self.assertFalse(tabla.xpath(".//td[@name='td_product_quantity']"))
        self.assertSeccionesAlineadas(tabla)

    def test_cantidad_solo_en_las_lineas_que_no_van_de_a_uno(self):
        tabla = self._tabla('Monitor', 'Sensor', 'Kit Fino')
        self.assertTrue(tabla.xpath(".//th[@id='product_qty_header']"))
        cantidades = [td.text_content().split() for td in tabla.xpath(".//td[@name='td_product_quantity']")]
        self.assertEqual([c for c in cantidades if c], [['16.00', 'Units']])
        self.assertSeccionesAlineadas(tabla)
