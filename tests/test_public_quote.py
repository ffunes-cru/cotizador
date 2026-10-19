import time

from odoo import http
from odoo.tests import HttpCase, new_test_user, tagged

from odoo.addons.cotizador.controllers.main import FORM_TOKEN_SCOPE
from odoo.tools.misc import hmac as hmac_sign

from .common import MATRIX_CSV, import_matrix


@tagged('post_install', '-at_install')
class TestPublicQuote(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import_matrix(cls.env, MATRIX_CSV)
        cls.config = cls.env.ref('cotizador_import.cfg_pionera_001')
        cls.template = cls.config.modelo_id
        cls.template.write({'sale_ok': True, 'is_published': True})
        params = cls.env['ir.config_parameter'].sudo()
        params.set_param('cotizador.quote_min_seconds', 0)
        params.set_param('cotizador.quote_rate_limit_contact', 2)

    def setUp(self):
        super().setUp()
        self.authenticate(None, None)  # sesión de visitante anónimo

    def _token(self, age=10):
        timestamp = str(int(time.time()) - age)
        return f"{timestamp}.{hmac_sign(self.env(su=True), FORM_TOKEN_SCOPE, timestamp)}"

    def _post(self, **extra):
        data = {
            'csrf_token': http.Request.csrf_token(self),
            'cotizador_form_token': self._token(),
            'product_template_id': self.template.id,
            'config_id': self.config.id,
            'contact_name': 'Visitante',
            'email': 'visitante@example.com',
            **extra,
        }
        return self.url_open('/cotizador/solicitar_cotizacion', data=data, allow_redirects=False)

    def test_anonymous_request_creates_only_a_lead(self):
        orders_before = self.env['sale.order'].search_count([])
        partners_before = self.env['res.partner'].search_count([])
        response = self._post()
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers['Location'].endswith('/cotizador/solicitud_recibida'))

        lead = self.env['crm.lead'].search([('email_from', '=', 'visitante@example.com')])
        self.assertEqual(len(lead), 1)
        self.assertFalse(lead.partner_id)
        self.assertEqual(lead.cotizador_config_id, self.config)
        self.assertTrue(lead.cotizador_request_ip)
        self.assertIn('Kit Fino', lead.description)  # equipamiento estándar listado
        self.assertEqual(self.env['sale.order'].search_count([]), orders_before)
        self.assertEqual(self.env['res.partner'].search_count([]), partners_before)

        # Límite por contacto (2/hora en este test)
        self._post()
        self.assertIn('quote_error=rate_limit', self._post().headers['Location'])

    def test_form_token_required(self):
        for token in ('', 'abc.def', self._token(age=10 * 3600)):
            self.assertIn('quote_error=captcha', self._post(cotizador_form_token=token).headers['Location'])
        self.env['ir.config_parameter'].sudo().set_param('cotizador.quote_min_seconds', 60)
        self.assertIn('quote_error=captcha', self._post().headers['Location'])  # enviado demasiado rápido

    def test_machine_requires_its_configuration(self):
        for config_id in ('', '999999', 'x'):
            self.assertIn('quote_error=invalid', self._post(config_id=config_id).headers['Location'])
        self.assertIn('quote_error=invalid', self._post(email='').headers['Location'])

    def test_logged_in_customer_gets_quotation(self):
        portal = new_test_user(self.env, 'cliente_portal', groups='base.group_portal')
        self.authenticate('cliente_portal', 'cliente_portal')
        response = self._post()
        self.assertIn('/my/orders/', response.headers['Location'])
        order = self.env['sale.order'].search([('partner_id', '=', portal.partner_id.id)])
        self.assertEqual(order.opportunity_id.cotizador_config_id, self.config)
        self.assertEqual(sorted(order.order_line.product_id.mapped('name')), ['Kit Fino', 'Monitor', 'Pionera'])

    def test_quote_only_blocks_checkout(self):
        self.env['ir.config_parameter'].sudo().set_param('cotizador.ecommerce_mode', 'quote_only')
        for url in ('/shop/checkout', '/shop/payment'):
            response = self.url_open(url, allow_redirects=False)
            self.assertEqual(response.status_code, 303, url)
            self.assertTrue(response.headers['Location'].endswith('/shop'), url)

    def test_thank_you_page(self):
        response = self.url_open('/cotizador/solicitud_recibida')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Solicitud de cotización recibida', response.text)
