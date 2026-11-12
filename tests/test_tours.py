from odoo.tests import HttpCase, tagged

from .common import MATRIX_CSV, find_config, import_matrix


@tagged('post_install', '-at_install')
class TestTours(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import_matrix(cls.env, MATRIX_CSV)
        cls.template = cls.env.ref('cotizador_import.modelo_pionera')
        cls.env['ir.config_parameter'].sudo().set_param('cotizador.quote_min_seconds', 0)

    def test_configurator_tour(self):
        order = self.env['sale.order'].create({'partner_id': self.env['res.partner'].create({'name': 'Cliente Tour'}).id})
        self.start_tour(f'/odoo/sales/{order.id}', 'cotizador_configurator_tour', login='admin')
        self.assertEqual(order.order_line.filtered('display_type').mapped('cotizador_section'), ['maquina', 'equipamiento'])
        self.assertEqual(sorted(order.order_line.product_id.mapped('name')), ['Kit Grueso', 'Monitor', 'Pionera'])

    def test_website_quote_tour(self):
        self.template.write({'sale_ok': True, 'is_published': True})
        self.start_tour(self.template.website_url, 'cotizador_website_quote_tour', login=None)
        lead = self.env['crm.lead'].search([('email_from', '=', 'tour@example.com')])
        self.assertEqual(lead.cotizador_config_id, find_config(self.env, 'Pionera', '16 Lineas', '52 cm'))
