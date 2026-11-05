from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import new_test_user, tagged

from .common import MATRIX_CSV, CotizadorCase


@tagged('post_install', '-at_install')
class TestConfigurator(CotizadorCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._import(MATRIX_CSV)
        cls.config = cls._imported('cfg_pionera_001')
        cls.service = cls.env['cotizador.configurator.service']

    def test_offer_and_defaults(self):
        offer = {i['product'].name: i for i in self.config._get_accessory_offer()}
        self.assertEqual(offer['Sensor']['quantity'], 16.0)  # cantidad del valor "16 Lineas"
        self.assertEqual(offer['Sensor']['subtotal'], 160.0)
        self.assertEqual(self.config._get_default_accessory_lines().product_id.mapped('name'), ['Monitor', 'Kit Fino'])

        data = self.service.get_config_accessories(self.config.id, self._order().id)
        acc = {a['product_name']: a for a in data['accessories']}
        self.assertTrue(acc['Kit Fino']['selected'])
        self.assertEqual(acc['Kit Grueso']['choice_group_name'], 'Kit Siembra')
        self.assertEqual(acc['Kit Grueso']['price_delta'], 30.0)
        self.assertEqual(acc['Kit Mixto']['price_delta'], -20.0)
        self.assertEqual(acc['Monitor']['price_delta'], 0.0)

    def test_confirm_sections_and_choice_rules(self):
        lines = self._lines(self.config)
        order = self._order()
        # Opción única: exactamente una del grupo
        with self.assertRaisesRegex(UserError, 'exactamente una opción'):
            self.service.confirm_configuration(order.id, self.config.id, lines['Monitor'].ids)
        with self.assertRaisesRegex(UserError, 'exactamente una opción'):
            self.service.confirm_configuration(order.id, self.config.id,
                                               (lines['Kit Fino'] | lines['Kit Grueso']).ids)
        with self.assertRaisesRegex(UserError, 'exclusión'):
            self.service.confirm_configuration(order.id, self.config.id,
                                               (lines['Kit Fino'] | lines['Cuchilla A'] | lines['Cuchilla B']).ids)
        with self.assertRaisesRegex(UserError, 'habilitante'):
            self.service.confirm_configuration(order.id, self.config.id, (lines['Kit Fino'] | lines['Sensor']).ids)

        self.service.confirm_configuration(order.id, self.config.id, (
            lines['Monitor'] | lines['Sensor'] | lines['Kit Grueso'] | lines['Cuchilla A']).ids)
        sections = order.order_line.filtered('display_type')
        self.assertEqual(sections.mapped('cotizador_section'), ['maquina', 'equipamiento', 'accesorios'])
        # Orden de creación: Máquina, Equipamiento (estándar + opción elegida), Accesorios (resto)
        names = [l.name if l.display_type else l.product_id.name for l in order.order_line.sorted('id')]
        self.assertEqual(names, ['Máquina', 'Pionera', 'Equipamiento', 'Monitor', 'Kit Grueso',
                                 'Accesorios', 'Sensor', 'Cuchilla A'])
        by_name = {l.product_id.name: l for l in order.order_line if l.product_id}
        self.assertEqual(by_name['Pionera'].price_unit, 1000.0)
        self.assertEqual(by_name['Sensor'].product_uom_qty, 16.0)
        self.assertEqual(by_name['Kit Grueso'].price_unit, 80.0)

    def test_choice_option_in_exclusion_group(self):
        """Una alternativa de opción única puede estar en una exclusión: Kit Mixto excluye a las cuchillas."""
        lines = self._lines(self.config)
        order = self._order()
        with self.assertRaisesRegex(UserError, "exclusión 'Cuchillas'"):
            self.service.confirm_configuration(order.id, self.config.id, (
                lines['Monitor'] | lines['Kit Mixto'] | lines['Cuchilla A']).ids)
        # Otra alternativa con una cuchilla, o el Kit Mixto sin cuchillas, son válidas
        self.service.confirm_configuration(order.id, self.config.id, (
            lines['Monitor'] | lines['Kit Fino'] | lines['Cuchilla A']).ids)
        self.service.confirm_configuration(order.id, self.config.id, (lines['Monitor'] | lines['Kit Mixto']).ids)
        # Con una inclusión no: la deseleccionaría y dejaría el grupo sin opción
        with self.assertRaisesRegex(ValidationError, 'solo puede estar en grupos de exclusión'):
            lines['Kit Mixto'].rule_ids |= lines['Sensor'].rule_ids

    def test_pricelist_applies_to_machine_and_accessories(self):
        self.pricelist.item_ids = [Command.create({'compute_price': 'percentage', 'percent_price': 10})]
        order = self._order()
        matrix = self.service.get_model_matrix(self.config.modelo_id.id, order.id)
        self.assertEqual(sorted(c['price'] for c in matrix['configs']), [900.0, 1800.0])
        data = self.service.get_config_accessories(self.config.id, order.id)
        self.assertEqual({a['product_name']: a['price_unit'] for a in data['accessories']}['Kit Grueso'], 72.0)

        self.service.confirm_configuration(order.id, self.config.id,
                                           self.config._get_default_accessory_lines().ids)
        prices = {l.product_id.name: l.price_unit for l in order.order_line if l.product_id}
        self.assertEqual(prices, {'Pionera': 900.0, 'Monitor': 90.0, 'Kit Fino': 45.0})

        # Plantilla sin combinación: "desde" (la configuración más barata)
        tmpl = self.config.modelo_id
        self.assertAlmostEqual(self.pricelist._get_product_price(tmpl, 1.0, currency=self.usd), 900.0)

    def test_price_cache_invalidated_on_write(self):
        tmpl = self.config.modelo_id
        self.assertAlmostEqual(self.pricelist._get_product_price(tmpl, 1.0, currency=self.usd), 1000.0)
        self.config.price = 500.0
        self.assertAlmostEqual(self.pricelist._get_product_price(tmpl, 1.0, currency=self.usd), 500.0)

    def test_product_currency_and_tax_setting(self):
        eur = self.env.ref('base.EUR')
        eur.active = True
        self.env['res.currency.rate'].create({'currency_id': eur.id, 'rate': 2.0, 'name': '2000-01-01'})
        tax = self.env['account.tax'].create({'name': 'IVA Maquinaria', 'amount': 10.5, 'type_tax_use': 'sale'})
        self.env.company.cotizador_tax_id = tax
        lines = self._lines(self.config)
        (self.config.modelo_id | lines['Monitor'].product_id.product_tmpl_id).cotizador_currency_id = eur
        order = self._order()
        self.service.confirm_configuration(order.id, self.config.id, self.config._get_default_accessory_lines().ids)
        prices = {l.product_id.name: l.price_unit for l in order.order_line if l.product_id}
        # Cada producto en su moneda → USD de la orden (compañía en USD, 1 USD = 2 EUR)
        self.assertEqual(prices, {'Pionera': 500.0, 'Monitor': 50.0, 'Kit Fino': 50.0})
        self.assertEqual(order.order_line.filtered('product_id').tax_ids, tax)

    def test_quotation_pricelist_applied_when_configuring(self):
        # Cotización creada a mano con la lista habitual del cliente (otra moneda), sin productos:
        # al configurar pasa a la lista de cotizaciones y usa los importes de la matriz sin conversión
        eur = self.env.ref('base.EUR')
        eur.active = True
        self.env['res.currency.rate'].create({'currency_id': eur.id, 'rate': 2.0, 'name': '2000-01-01'})
        customer_pricelist = self.env['product.pricelist'].create({'name': 'Cliente EUR', 'currency_id': eur.id})
        self.env.company.cotizador_pricelist_id = self.pricelist
        defaults = self.config._get_default_accessory_lines().ids

        order = self._order(pricelist_id=customer_pricelist.id)
        self.service.confirm_configuration(order.id, self.config.id, defaults)
        self.assertEqual(order.pricelist_id, self.pricelist)
        self.assertEqual(order.currency_id, self.usd)
        self.assertEqual({l.product_id.name: l.price_unit for l in order.order_line if l.product_id},
                         {'Pionera': 1000.0, 'Monitor': 100.0, 'Kit Fino': 50.0})

        # Con productos ya cargados no se cambia la lista: se convierte a la moneda de la orden
        order = self._order(pricelist_id=customer_pricelist.id, order_line=[
            Command.create({'product_id': self.env.ref('cotizador.product_plan_cheques').id})])
        self.service.confirm_configuration(order.id, self.config.id, defaults)
        self.assertEqual(order.pricelist_id, customer_pricelist)
        machine = order.order_line.filtered(lambda l: l.product_id.is_maquina)
        self.assertAlmostEqual(machine.price_unit, 2000.0)

    def test_subtotal_consistent_with_line_discount(self):
        order = self._order()
        self.service.confirm_configuration(order.id, self.config.id, self.config._get_default_accessory_lines().ids)
        order.order_line.filtered(lambda l: l.product_id.is_maquina).discount = 10
        self.assertAlmostEqual(order.amount_subtotal_productos, 900.0 + 100.0 + 50.0)

    def test_rule_constraint_on_manual_edit(self):
        lines = self._lines(self.config)
        with self.assertRaisesRegex(ValidationError, 'exactamente un accesorio ESTANDAR'):
            self.config.write({'accessory_line_ids': [Command.update(lines['Kit Grueso'].id, {'is_standard': True})]})
        # Mover el estándar de un grupo en un solo guardado es válido
        self.config.write({'accessory_line_ids': [
            Command.update(lines['Kit Fino'].id, {'is_standard': False}),
            Command.update(lines['Kit Grueso'].id, {'is_standard': True}),
        ]})

    def test_permissions(self):
        salesman = new_test_user(self.env, 'vendedor', groups='sales_team.group_sale_salesman')
        manager = new_test_user(self.env, 'admin_cotizador', groups='cotizador.group_cotizador_manager')
        order = self._order(user_id=salesman.id).with_user(salesman)
        service = self.service.with_user(salesman)
        service.confirm_configuration(order.id, self.config.id, self.config._get_default_accessory_lines().ids)
        self.assertTrue(order.order_line)
        with self.assertRaises(AccessError):
            self.config.with_user(salesman).price = 1
        with self.assertRaises(AccessError):
            self.env['cotizador.plan.pago.template'].with_user(salesman).create({'name': 'X', 'tipo': 'cheques'})
        with self.assertRaises(AccessError):
            self.env['sembradora.import.wizard'].with_user(salesman).create({})
        self.config.with_user(manager).price = 1

    def test_lead_create_quotation(self):
        lead = self.env['crm.lead'].create({'name': 'Web', 'cotizador_config_id': self.config.id})
        with self.assertRaisesRegex(UserError, 'Asigne primero el cliente'):
            lead.action_cotizador_create_quotation()
        lead.partner_id = self.partner
        action = lead.action_cotizador_create_quotation()
        order = self.env['sale.order'].browse(action['res_id'])
        self.assertEqual(order.opportunity_id, lead)
        self.assertEqual(sorted(order.order_line.product_id.mapped('name')), ['Kit Fino', 'Monitor', 'Pionera'])

    def test_payment_plan_does_not_touch_product_price(self):
        template = self.env['cotizador.plan.pago.template'].create({
            'name': 'Cheques', 'tipo': 'cheques',
            'line_ids': [Command.create({'plan_cheques': '30-60-90', 'descuento': 5})],
        })
        order = self._order()
        self.service.confirm_configuration(order.id, self.config.id, self.config._get_default_accessory_lines().ids)
        template.line_ids.with_context(default_sale_order_id=order.id).action_select_line()
        plan_product = self.env.ref('cotizador.product_plan_cheques')
        self.assertEqual(plan_product.list_price, 0.0)
        self.assertIn(plan_product, order.order_line.product_id)
