"""@file
La documentación del código y la referencia generada están al día."""
from odoo.tests import TransactionCase, tagged

from ..tools.documentacion import ARCHIVO, faltantes, generar


@tagged('post_install', '-at_install')
class TestDocumentacion(TransactionCase):
    """Ver tools/documentacion.py."""

    def test_codigo_documentado(self):
        """Todo módulo, clase, función y parámetro de Python y JavaScript está documentado."""
        errores = faltantes()
        self.assertFalse(errores, 'Falta documentación (formato Doxygen, ver docs/recetas.md):\n' + '\n'.join(errores))

    def test_referencia_actualizada(self):
        """docs/referencia.md refleja los modelos, permisos y puntos de entrada actuales."""
        self.assertEqual(
            ARCHIVO.read_text(encoding='utf-8'), generar(self.env),
            'docs/referencia.md está desactualizado: regenerarlo como indica tools/documentacion.py y commitearlo.')
