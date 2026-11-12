"""@file
Tests de la cascada de totales (descuentos sobre el neto, plan de pago), del precio de matriz
guardado en la línea y de las variantes creadas con la matriz."""
import base64

from odoo import Command
from odoo.tests import tagged

from .common import HEADER, MATRIX_CSV, CotizadorCase


@tagged('post_install', '-at_install')
class TestCascade(CotizadorCase):
    """Descuentos, plan de pago e IVA."""

    @classmethod
    def setUpClass(cls):
        """Matriz de ejemplo, IVA 10,5 % de maquinaria y una cotización con el equipamiento estándar."""
        super().setUpClass()
        cls._import(MATRIX_CSV)
        cls.config = cls._config('Pionera', '16 Lineas', '52 cm')
        cls.tax = cls.env['account.tax'].create({'name': 'IVA 10,5', 'amount': 10.5, 'type_tax_use': 'sale'})
        cls.env.company.cotizador_tax_id = cls.tax

    def _quote(self, lines=None):
        """@param lines Líneas de accesorio (por defecto, el estándar).
        @return Cotización con la Pionera 001 configurada (neto 1150)."""
        order = self._order()
        self.env['cotizador.configurator.service'].confirm_configuration(
            order.id, self.config.id, (lines or self.config._get_default_accessory_lines()).ids)
        return order

    def _discount(self, order, **vals):
        """@param order Cotización.
        @param vals Valores del asistente.
        @return La cotización."""
        self.env['cotizador.descuento.wizard'].create({'sale_order_id': order.id, **vals}).action_confirm()
        return order

    def test_discount_applies_to_net_and_vat_after(self):
        """100 % neto − 6 % = 94 %, y el IVA se calcula sobre ese neto."""
        order = self._discount(self._quote(), tipo_calculo='porcentaje', porcentaje=6)
        self.assertAlmostEqual(order.amount_subtotal_productos, 1150.0)
        self.assertAlmostEqual(order.amount_descuentos, -69.0)
        self.assertAlmostEqual(order.amount_subtotal_neto, 1081.0)
        self.assertAlmostEqual(order.amount_iva_productos, 1081 * 0.105, delta=0.02)  # redondeo por línea
        self.assertAlmostEqual(order.amount_total_base, order.amount_subtotal_neto + order.amount_iva_productos)
        self.assertAlmostEqual(order.amount_saldo_cancelar, order.amount_total)  # coincide con Odoo
        discount = order.order_line.filtered('is_descuento')
        self.assertEqual(discount.tax_ids, self.tax)

    def test_percentage_discounts_cascade_and_follow_the_lines(self):
        """Dos descuentos en cascada; si cambian los productos se recalculan."""
        order = self._discount(self._quote(), tipo_calculo='porcentaje', porcentaje=10)
        self._discount(order, tipo_calculo='porcentaje', porcentaje=5)
        self._discount(order, tipo_calculo='monto', monto_fijo=10)
        # 1150 − 115 = 1035; − 5 % = 1035 − 51,75; − 10 fijo
        self.assertAlmostEqual(order.amount_descuentos, -(115 + 51.75 + 10))
        machine = order.order_line.filtered(lambda l: l.product_id.is_maquina)
        machine.price_unit = 2000.0  # neto 2150
        self.assertAlmostEqual(order.amount_descuentos, -(215 + 96.75 + 10))

    def test_payment_plan_follows_the_lines_and_simulation_matches(self):
        """El plan se aplica sobre el neto con descuentos, se recalcula y la simulación coincide."""
        template = self.env['cotizador.plan.pago.template'].create({
            'name': 'Cheques', 'tipo': 'cheques',
            'line_ids': [Command.create({'plan_cheques': '30-60-90', 'descuento': -5})],
        })
        order = self._discount(self._quote(), tipo_calculo='porcentaje', porcentaje=10)
        expected = order._cotizador_simulate_plan(-5)
        template.line_ids.with_context(default_sale_order_id=order.id).action_select_line()
        plan = order.order_line.filtered(lambda l: l.is_plan_pago and not l.display_type)
        self.assertEqual(plan.tax_ids, self.tax)
        self.assertAlmostEqual(order.amount_plan_pago, -51.75)  # 5 % de 1035
        self.assertAlmostEqual(order.amount_saldo_cancelar, expected, delta=0.02)
        order.order_line.filtered(lambda l: l.product_id.is_maquina).price_unit = 2000.0
        self.assertAlmostEqual(order.amount_plan_pago, -96.75)  # 5 % de 1935

    def test_update_prices_keeps_special_lines(self):
        """*Actualizar precios* no pone en 0 descuentos ni usados."""
        order = self._discount(self._quote(), tipo_calculo='porcentaje', porcentaje=10)
        self.env['equipo.usado.wizard'].create({'sale_order_id': order.id, 'descripcion': 'Usado', 'monto': 100}).action_confirm()
        order.action_update_prices()
        self.assertAlmostEqual(order.amount_descuentos, -115.0)
        self.assertAlmostEqual(order.amount_usados, -100.0)
        self.assertAlmostEqual(order.amount_subtotal_productos, 1150.0)

    def test_accessory_keeps_matrix_price_when_quantity_changes(self):
        """Cambiar la cantidad de un accesorio no lo lleva al precio de venta del producto."""
        order = self._quote()
        monitor = order.order_line.filtered(lambda l: l.product_id.name == 'Monitor')
        monitor.product_uom_qty = 2
        self.assertAlmostEqual(monitor.price_unit, 100.0)
        order.action_update_prices()
        self.assertAlmostEqual(monitor.price_unit, 100.0)


@tagged('post_install', '-at_install')
class TestVariants(CotizadorCase):
    """Una variante por configuración, creada con la matriz."""

    def test_one_variant_per_configuration(self):
        """Atributos "Siempre"; las variantes siguen a la matriz."""
        self._import(MATRIX_CSV)
        pionera = self._imported('modelo_pionera')
        self.assertEqual(self._imported('attr_lineas').create_variant, 'always')
        # 2 configuraciones (16 y 18 líneas a 52 cm) → 2 variantes, aunque el cartesiano también es 2
        self.assertEqual(len(pionera.product_variant_ids), 2)
        extra = self.env['product.attribute.value'].create({'name': '70 cm', 'attribute_id': self._imported('attr_distancia').id})
        pionera.attribute_line_ids.filtered(lambda l: l.attribute_id == extra.attribute_id).value_ids |= extra
        self.assertEqual(len(pionera.product_variant_ids), 2)  # 70 cm no está en la matriz
        config = self.env['sembradora.config.rel'].create({
            'modelo_id': pionera.id, 'price': 3000,
            'value_ids': [Command.set((self._imported('val_lineas_16_lineas') | extra).ids)],
        })
        self.assertEqual(len(pionera.product_variant_ids), 3)
        variant = config._get_variant()
        config.unlink()
        self.assertFalse(variant.exists() and variant.active)

    def test_incomplete_combination_is_an_error(self):
        """Cada configuración necesita un valor de cada atributo de la máquina."""
        csv_text = HEADER + "Pionera,BASE,1000,,,,,,16 Lineas,52 cm\nPionera,BASE,1200,,,,,,18 Lineas,\n"
        wizard = self._wizard(csv_text)
        self.assertTrue(wizard.has_errors)
        self.assertIn('no tiene valor en ATR_Distancia', wizard.analysis_summary)

    def test_teamcenter_id_is_confirmed_by_attributes(self):
        """Un ID de configuración de una plantilla anterior se resuelve a su variante."""
        self._import(MATRIX_CSV)
        config = self._config('Pionera', '16 Lineas', '52 cm')
        csv_text = ("ID_Odoo;Modelo;Lineas;Distancia;CODIGO_INGENIERIA_TEAMCENTER;Codigo_Actual_Odoo\n"
                    f"{config.id};Pionera;16 Lineas;52 cm;TC-001;\n")
        wizard = self.env['engineering.code.wizard'].create({
            'modelo_id': config.modelo_id.id,
            'import_file': base64.b64encode(csv_text.encode()),
            'import_filename': 'codigos.csv',
        })
        wizard.action_analyze_file()
        self.assertEqual(wizard.matched_count, 1)
        wizard.action_apply_codes()
        self.assertEqual(config._get_variant().default_code, 'TC-001')
