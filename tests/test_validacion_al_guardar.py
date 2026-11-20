"""@file
Al guardar, las máquinas y accesorios de una cotización siguen siendo una configuración válida (issue #19,
sale.order._cotizador_check_configuraciones())."""
from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import MATRIX_CSV, CotizadorCase


@tagged('post_install', '-at_install')
class TestValidacionAlGuardar(CotizadorCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._import(MATRIX_CSV)
        cls.config = cls._config('Pionera', '16 Lineas', '52 cm')
        cls.config_18 = cls._config('Pionera', '18 Lineas', '52 cm')
        cls.lineas = {line.product_id.name: line for line in cls.config.accessory_line_ids}

    def _cotizacion(self, *accesorios):
        """Cotización con la Pionera 16 líneas y los accesorios dados, agregada como lo hace el configurador."""
        order = self._order()
        order._cotizador_add_configuration(self.config, self.env['sembradora.config.accessory.line'].union(
            *(self.lineas[nombre] for nombre in accesorios)))
        return order

    def _linea(self, order, nombre):
        return order.order_line.filtered(lambda l: l.product_id.name == nombre)

    def test_reemplazar_la_opcion_desde_el_formulario(self):
        """El formulario manda juntos el borrado y el alta: en el medio el grupo queda sin opción, y no falla."""
        order = self._cotizacion('Monitor', 'Kit Fino')
        fino = self._linea(order, 'Kit Fino')
        grueso = self.lineas['Kit Grueso'].product_id
        order.write({'order_line': [Command.delete(fino.id), Command.create({'product_id': grueso.id})]})
        self.assertTrue(self._linea(order, 'Kit Grueso'))

    # Cada caso que falla usa su propia cotización: el ORM deja en caché el cambio rechazado.

    def test_borrar_la_opcion_de_un_grupo_de_opcion_unica(self):
        order = self._cotizacion('Monitor', 'Kit Fino')
        with self.assertRaisesRegex(ValidationError, 'exactamente una opción'):
            self._linea(order, 'Kit Fino').unlink()
        # Borrar un estándar que no es de un grupo sí se puede (en el configurador también se deselecciona)
        order = self._cotizacion('Monitor', 'Kit Fino')
        self._linea(order, 'Monitor').unlink()

    def test_cambiar_el_producto_de_un_accesorio(self):
        def cotizacion():
            return self._cotizacion('Monitor', 'Sensor', 'Kit Fino', 'Cuchilla A')

        with self.assertRaisesRegex(ValidationError, 'exclusión'):
            self._linea(cotizacion(), 'Kit Fino').product_id = self.lineas['Kit Mixto'].product_id.id
        with self.assertRaisesRegex(ValidationError, 'habilitante'):
            # Sin el Monitor, el Sensor queda sin su habilitante
            self._linea(self._cotizacion('Monitor', 'Sensor', 'Kit Fino'), 'Monitor').product_id = \
                self.lineas['Cuchilla A'].product_id.id
        order = cotizacion()
        with self.assertRaisesRegex(ValidationError, 'exclusión'):
            order.write({'order_line': [Command.create({'product_id': self.lineas['Cuchilla B'].product_id.id})]})

    def test_cambiar_la_variante_de_la_maquina(self):
        """La de 18 líneas no tiene Sensor: los accesorios quedan de otra configuración."""
        order = self._cotizacion('Monitor', 'Sensor', 'Kit Fino')
        with self.assertRaisesRegex(ValidationError, 'no son accesorios'):
            self._linea(order, 'Pionera').product_id = self.config_18._get_variant().id

        sin_sensor = self._cotizacion('Kit Fino')
        self._linea(sin_sensor, 'Pionera').product_id = self.config_18._get_variant().id

    def test_accesorios_sin_maquina(self):
        """Sin máquina arriba no hay configuración contra la cual validar: se permiten (accesorios sueltos)."""
        order = self._cotizacion('Monitor', 'Kit Fino')
        self._linea(order, 'Pionera').unlink()
        self._linea(order, 'Kit Fino').unlink()

    def test_varias_maquinas_por_cotizacion(self):
        """Cada sección Máquina abre un bloque: los accesorios se validan contra la máquina que tienen arriba."""
        order = self._cotizacion('Monitor', 'Kit Fino', 'Cuchilla A')
        order._cotizador_add_configuration(self.config, self.lineas['Kit Mixto'])
        self.assertEqual(len(order.order_line.filtered(lambda l: l.product_id.is_maquina)), 2)
        # La Cuchilla A del primer bloque no choca con el Kit Mixto del segundo; en el mismo bloque sí
        with self.assertRaisesRegex(ValidationError, 'exclusión'):
            order.write({'order_line': [Command.create({'product_id': self.lineas['Cuchilla B'].product_id.id})]})

    def test_duplicar_una_cotizacion(self):
        order = self._cotizacion('Monitor', 'Sensor', 'Kit Grueso', 'Cuchilla A')
        copia = order.copy()
        self.assertEqual(copia.order_line.product_id, order.order_line.product_id)

    def test_cotizacion_sin_maquinas_y_pedido_confirmado(self):
        otro = self.env['product.product'].create({'name': 'Repuesto'})
        order = self._order(order_line=[Command.create({'product_id': otro.id})])
        order.order_line.unlink()

        confirmada = self._cotizacion('Monitor', 'Kit Fino')
        confirmada.action_confirm()
        self._linea(confirmada, 'Monitor').product_uom_qty = 2  # fuera de borrador no se valida
