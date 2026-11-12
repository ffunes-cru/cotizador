"""@file
Tests de los arreglos de la revisión de código: BCRA, CRM, Teamcenter y cantidad por atributo."""
import json
import urllib.error
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.cotizador.models import bcra_service

from .common import MATRIX_CSV, CotizadorCase


class FakeResponse:
    """Respuesta HTTP mínima para simular la API del BCRA."""

    def __init__(self, payload):
        """@param payload dict que se devuelve como JSON."""
        self.payload = payload

    def read(self):
        """@return El JSON en bytes."""
        return json.dumps(self.payload).encode()

    def __enter__(self):
        """@return La respuesta."""
        return self

    def __exit__(self, *args):
        """@param args Excepción del bloque, si hubo."""
        return False


@tagged('post_install', '-at_install')
class TestBcra(CotizadorCase):
    """Cliente de la API del BCRA, sin red."""

    def test_api_error_is_never_no_debt(self):
        """Un error de red o HTTP 500 da success=False, nunca "sin deudas"."""
        for error in (urllib.error.URLError('sin red'),
                      urllib.error.HTTPError('u', 500, 'Error', {}, None)):
            with patch.object(bcra_service.urllib.request, 'urlopen', side_effect=error):
                result = bcra_service.consultar_bcra_completo('20-12345678-9')
            self.assertFalse(result['success'])
            self.assertIn('BCRA', result['error'])

    def test_404_means_no_records(self):
        """404 en las dos consultas: el CUIT no tiene registros."""
        error = urllib.error.HTTPError('u', 404, 'Not found', {}, None)
        with patch.object(bcra_service.urllib.request, 'urlopen', side_effect=error):
            result = bcra_service.consultar_bcra_completo('20123456789')
        self.assertTrue(result['success'])
        self.assertFalse(result['tiene_deuda'])

    def test_debts_are_parsed_in_pesos(self):
        """Montos en miles de pesos → pesos; peor situación y cheques."""
        responses = [
            FakeResponse({'status': 200, 'results': {'denominacion': 'CLIENTE SA', 'periodos': [
                {'periodo': '202609', 'entidades': [
                    {'entidad': 'BANCO A', 'situacion': 1, 'monto': 10.5},
                    {'entidad': 'BANCO B', 'situacion': 3, 'monto': 2, 'procesoJud': True},
                ]}]}}),
            FakeResponse({'status': 200, 'results': {'chequesRechazados': [{'nroCheque': 7, 'monto': 100}]}}),
        ]
        with patch.object(bcra_service.urllib.request, 'urlopen', side_effect=responses) as urlopen:
            result = bcra_service.consultar_bcra_completo('20123456789')
        self.assertTrue(urlopen.call_args.kwargs['context'].check_hostname)  # TLS verificado
        self.assertTrue(result['tiene_deuda'])
        self.assertEqual(result['monto_total_deuda'], 12500.0)
        self.assertEqual(result['peor_situacion'], '3')
        self.assertEqual(result['deudas'][0]['periodo'], '09/2026')
        self.assertEqual(result['deudas'][1]['observaciones'], 'Proceso Judicial')
        self.assertEqual(len(result['cheques_rechazados']), 1)


@tagged('post_install', '-at_install')
class TestReviewFixes(CotizadorCase):
    """CRM, Teamcenter y accesorios por cantidad."""

    @classmethod
    def setUpClass(cls):
        """Importa la matriz de ejemplo."""
        super().setUpClass()
        cls._import(MATRIX_CSV)
        cls.config = cls._config('Pionera', '16 Lineas', '52 cm')
        cls.service = cls.env['cotizador.configurator.service']

    def test_expected_revenue_in_company_currency(self):
        """El ingreso esperado de la oportunidad se convierte a la moneda de la compañía."""
        eur = self.env.ref('base.EUR')
        eur.active = True
        self.env['res.currency.rate'].create({'currency_id': eur.id, 'rate': 2.0, 'name': '2000-01-01'})
        pricelist_eur = self.env['product.pricelist'].create({'name': 'EUR', 'currency_id': eur.id})
        order = self._order(pricelist_id=pricelist_eur.id)
        self.service.confirm_configuration(order.id, self.config.id, self.config._get_default_accessory_lines().ids)
        order.write({'user_id': self.env.uid})  # dispara la sincronización con el CRM
        lead = order.opportunity_id
        self.assertTrue(lead)
        self.assertEqual(order.currency_id, eur)
        # 1150 USD de matriz = 2300 EUR en la orden; la oportunidad vuelve a USD (1 USD = 2 EUR)
        self.assertAlmostEqual(order.amount_subtotal_productos, 2300.0)
        self.assertAlmostEqual(lead.expected_revenue, order.amount_saldo_cancelar / 2)
        lead.expected_revenue = 0
        order.write({'user_id': self.env.uid})  # otra sincronización: sigue convertido
        self.assertEqual(order.currency_id, eur)
        self.assertAlmostEqual(lead.expected_revenue, order.amount_saldo_cancelar / 2)

    def test_engineering_codes_are_applied_with_parameters(self):
        """Los códigos se escriben tal cual, incluso con comillas."""
        variant = self.config._get_variant()
        wizard = self.env['engineering.code.wizard'].create({
            'modelo_id': self.config.modelo_id.id,
            'matched_data_json': json.dumps([{'product_id': variant.id, 'code': "AB'C; DROP"}]),
        })
        wizard.action_apply_codes()
        self.assertEqual(variant.default_code, "AB'C; DROP")

    def test_missing_qty_attribute_is_a_clear_error(self):
        """Si la categoría de cantidad cambia de atributo, el error es claro (no un KeyError)."""
        sensor_categ = self._imported('acc_pionera_sensor').categ_id
        other_attribute = self.env['product.attribute'].create({'name': 'Otro'})
        sensor_categ.cotizador_qty_attribute_id = other_attribute
        with self.assertRaisesRegex(UserError, "se cotiza por 'Otro'"):
            self.config._get_accessory_offer()
