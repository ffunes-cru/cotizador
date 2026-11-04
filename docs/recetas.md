# Recetas

Cambios habituales, paso a paso. Al terminar cualquier cambio de código: tests, regenerar
[la referencia](referencia.md) (comando en [Operación](operacion.md#comandos-frecuentes)), actualizar el
documento de `docs/` que corresponda y commitear todo junto.

## Cambios que no requieren programar

Con el usuario *Administrador del Configurador*:

| Quiero… | Dónde |
|---|---|
| Cargar o actualizar la matriz: combinaciones nuevas, precios (también en bloque), accesorios y reglas | Editar el CSV y *Importar Configuraciones* ([formato](importador.md)): lo que ya existe se actualiza. |
| Quitar una combinación o un accesorio | Sacarlo del CSV e importar: la máquina queda igual al archivo (las configuraciones se borran, los accesorios se archivan). |
| Ver qué cambió en una importación | Chatter de la máquina: cada importación deja el detalle de lo que cambió. |
| Corregir un precio puntual | En el CSV. Editarlo en *Matriz Base* sirve como arreglo rápido, pero la próxima importación lo pisa. |
| Cargar códigos de Teamcenter | *Códigos de Ingeniería (Teamcenter)*. |
| Cambiar la moneda de una máquina o accesorio | Ficha del producto, *Moneda del Cotizador* (los precios de matriz se interpretan en la moneda nueva: revisarlos). |
| Texto técnico según los atributos | Ficha de la máquina, pestaña *Descripción Paramétrica*. |
| Ocultar un atributo en la descripción de la línea | Ficha del atributo, *Mostrar en Descripción*. |
| Planes de pago | *Plantillas Planes de Pago*; los favoritos de cada vendedor en su ficha de usuario. |
| Condiciones generales, modo de la tienda, aceptación en el portal, límites | *Ajustes › Ventas › Cotizador de Sembradoras*. |

## Agregar un accesorio a mano

1. Crear el producto en una categoría *Accesorio* (o una subcategoría de cantidad) con su *Modelo de
   Máquina* y su *Moneda del Cotizador*.
2. En cada configuración donde va (*Matriz Base*), agregar la línea con
   su precio, reglas y la marca *Estándar* si corresponde.
3. Si después se importa un CSV con el mismo nombre para esa máquina, el importador crea **otro** producto
   (reconoce solo lo que creó él). Conviene cargarlo por CSV desde el principio.

## Agregar una columna al importador

1. `FIXED_COLUMNS` en `models/sembradora_import_wizard.py`.
2. Leerla en `_parse()` (con su validación y mensaje con `where`).
3. Escribirla en el `_import_*` que corresponda.
4. Test en `tests/test_importer.py` (caso válido y error).
5. Documentarla en [importador.md](importador.md) (§2 y, si tiene errores nuevos, §10).

## Agregar un ajuste

1. Campo en `models/res_config_settings.py`: con `config_parameter='cotizador.<nombre>'` (parámetro) o
   `related='company_id.<campo>'` (si depende de la compañía; el campo va en `res_company.py`).
2. Mostrarlo en `views/res_config_settings_view.xml`.
3. Leerlo donde se usa: `env['ir.config_parameter'].sudo().get_param('cotizador.<nombre>', <defecto>)` o
   `company.<campo>`.
4. Documentarlo en [Operación](operacion.md#ajustes).

## Agregar una sección o un tipo de línea a la cotización

1. Valor nuevo en `cotizador_section` (`sale.order.line`, `models/sale_order_inherit.py`). Las secciones se
   identifican siempre por este campo, nunca por el texto.
2. Si la línea tiene que tratarse aparte en los totales, una marca booleana (como `is_descuento`) y su lugar
   en `_compute_totales_cotizador()`.
3. Si no tiene producto, sumarla a `_confirmation_error_message()`.
4. Mostrarla en `report/report_cotizacion_planes.xml` y `views/portal_templates.xml`.

## Cambiar una regla de accesorios

Las reglas viven en tres lugares que tienen que decir lo mismo (ver [Flujos](flujos.md#reglas-de-accesorios)):

1. `validate_rule_set()` (`models/sembradora_config.py`): coherencia del estándar; la usan la restricción y el importador.
2. `_check_accessory_selection()` (mismo archivo): validación de una selección al confirmar.
3. `_evaluateAccessoryRules()` / `selectChoice()` (`static/src/components/configurador/configurador.js`): guía en el navegador.

Tests en `tests/test_importer.py` (`test_rule_coherence_errors`) y `tests/test_configurator.py`.

## Cambiar cómo se calcula un precio

Todo pasa por `_price_compute` (`models/product_template_inherit.py`) y la lista de precios. No calcular
precios en el JavaScript ni en el controller: el servidor los recalcula al confirmar. Tests en
`tests/test_configurator.py` (`test_pricelist_applies_to_machine_and_accessories`,
`test_product_currency_and_tax_setting`, `test_quotation_pricelist_applied_when_configuring`).

## Documentar código

El código se documenta en formato **Doxygen**, en español. `tests/test_documentacion.py` falla si falta
algo (lo verifica `tools/documentacion.py`, que también dice exactamente qué falta).

**Python**: el archivo empieza con un docstring `@file`; cada clase y función tiene docstring; cada
parámetro, `@param`; si devuelve algo, `@return`; las excepciones que el usuario puede ver, `@throws`.
Las constantes de módulo llevan un comentario `##` arriba.

```python
## Prefijo de las columnas de atributo.
ATTRIBUTE_PREFIX = 'ATR_'


def first_number(text):
    """Primer número de un texto: '16 Líneas' → 16.0, '52,5 cm' → 52.5.

    @param text Texto (o None).
    @return El número, o None si no hay ninguno.
    """
```

**JavaScript**: el archivo empieza con un bloque `/** @file ... */`; cada clase, método y función tiene un
bloque `/** ... */` inmediatamente arriba, con `@param nombre` por parámetro y `@returns` si devuelve algo.

```js
/**
 * Formatea un importe con el símbolo de la moneda de la cotización.
 * @param amount Importe (number).
 * @returns {string}
 */
formatCurrency(amount) {
```

Qué escribir: **qué hace y por qué**, no cómo (eso lo dice el código). Mencionar quién lo llama si no es
obvio, las unidades y monedas de los importes, y las reglas de negocio que aplica.

HTML navegable de todo el código: `doxygen docs/Doxyfile` desde la carpeta del módulo, y abrir
`docs/api/html/index.html` (no se versiona).

## Actualizar la documentación

| Cambió… | Actualizar |
|---|---|
| Un modelo, campo, permiso o método público | Regenerar `docs/referencia.md`. |
| El formato del CSV o un error del importador | `docs/importador.md`. |
| Un ajuste o un menú | `docs/operacion.md`. |
| Un estado, una regla o un flujo | `docs/flujos.md`. |
| Un grupo, permiso o protección | `docs/seguridad.md`. |
| Se resolvió o apareció un problema conocido | `docs/pendientes.md`. |
