# Cotizador de Sembradoras — guía para agentes de IA

La documentación del módulo está en `README.md` y `docs/`. Leer antes de cambiar código:

1. `docs/conceptos.md` — negocio, glosario y un ejemplo.
2. `docs/arquitectura.md` — mapa de archivos, cálculo de precios y decisiones de diseño.
3. `docs/flujos.md` y `docs/seguridad.md` — estados, reglas de accesorios, permisos y protecciones.
4. `docs/referencia.md` — generado: modelos, campos, permisos y quién llama a cada método.
5. `docs/pendientes.md` — lo que se sabe que está mal o falta decidir.
6. `docs/mantenibilidad.md` — complejidad de cada función y reglas para el código nuevo.

## Reglas al cambiar código

- **Nunca buscar ni decidir por nombres o valores escritos en el código.** Registros del módulo por xmlid
  (`env.ref('cotizador.cat_maquina')`), lo importado por xmlid `cotizador_import.*`, secciones por
  `cotizador_section`, monedas / impuestos / listas por campos de la compañía o del producto.
- **Sin compatibilidad hacia atrás**: todavía no hay datos de producción; los cambios de esquema se
  resuelven con `-u`, sin scripts de migración.
- La regla de negocio va en el modelo. Una máquina se agrega a una cotización solo con
  `sale.order._cotizador_add_configuration()`; los precios salen de `_price_compute` y la lista de
  precios, nunca del JavaScript.
- Las reglas de accesorios están en tres lugares que deben coincidir (`docs/recetas.md#cambiar-una-regla-de-accesorios`).
- Servicios RPC de administración: empezar con `check_configurator_manager(self.env)`.
- Texto del usuario hacia HTML: `markupsafe.escape` / `Markup`; en JS del sitio, `escapeHtml`.
- **Documentar todo en formato Doxygen** (`docs/recetas.md#documentar-código`): `@file`, docstring o bloque
  `/** */` en cada clase y función, `@param` por parámetro, `@return` si devuelve algo.
- **Complejidad ciclomática ≤ 10** en funciones nuevas y no hacer crecer las que ya pasan de 10
  (`docs/mantenibilidad.md#reglas-para-el-código-nuevo`).
- Al terminar: tests (`docs/operacion.md#comandos-frecuentes`), regenerar `docs/referencia.md` y `docs/mantenibilidad.md`, y actualizar
  el documento de `docs/` que corresponda en el mismo commit. `tests/test_documentacion.py` falla si falta
  documentación o la referencia quedó vieja.
- Odoo no recarga el código Python solo: detener el servidor, `-u cotizador`, volver a arrancar.
