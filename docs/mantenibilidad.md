# Mantenibilidad

Estado del código medido con **complejidad ciclomática** función por función, con los puntos críticos
analizados y una lista priorizada de mejoras. La primera parte se escribe a mano; desde
*Resumen por área* el documento lo genera `tools/complejidad.py`.

## Qué se mide

### Complejidad ciclomática (CCN)

Es la cantidad de **caminos independientes** que tiene una función: 1 más uno por cada punto en que el
código se bifurca. Se usa porque se relaciona directamente con dos costos:

- **Entender**: cada bifurcación es un caso más que hay que tener en la cabeza al leer o cambiar la
  función.
- **Probar**: es la cantidad mínima de tests para recorrer todos los caminos. Una función con CCN 40
  necesita 40 casos para cubrirse entera; en la práctica, nadie los escribe.

La mide [lizard](https://github.com/terryyin/lizard) 1.25, igual para Python y JavaScript. Suma 1 por:

| Python | JavaScript |
|---|---|
| `if`, `elif`, `for`, `while`, `except`, `finally` | `if`, `for`, `while`, `catch`, `case` |
| `and`, `or` (también dentro de f-strings) | `&&`, `\|\|`, `??` (también dentro de `` `${…}` ``) |
| `if` y `for` de una comprensión; `x if c else y` | el ternario `c ? x : y` |

No suman: `else`, `with`, `return`, ni el encadenamiento opcional `?.` de JavaScript.

### Escala

| Rango | CCN | Lectura |
|:-:|--:|---|
| **A** | 1–5 | Simple. Se entiende de una lectura. |
| **B** | 6–10 | Bien estructurada. Es el techo para código nuevo. |
| **C** | 11–20 | Compleja. Aceptable si la complejidad es del problema (muchas validaciones), no de la forma. |
| **D** | 21–30 | Muy compleja. Cuesta cambiarla sin romper un caso; conviene dividirla. |
| **E** | 31–40 | Alarmante. |
| **F** | 41+ | Inmantenible en la práctica: nadie puede tener todos los caminos en la cabeza ni probarlos. |

Es la escala de McCabe que usan radon y SonarQube. Además se mide:

- **Líneas de código** (NLOC): líneas con código, sin comentarios ni líneas en blanco. Más de ~60 en una
  función suele indicar que hace varias cosas.
- **Parámetros**: más de 5 suele indicar que falta agrupar datos (un dict o un registro).

### Lo que la cifra no dice

- **Inflación por valores por defecto.** `x or ''` suma 1 aunque no sea una decisión de negocio. Por
  ejemplo, `plan_pago._compute_name` da 18, pero tiene 5 caminos reales; los otros 13 son `or ''` dentro
  de f-strings.
- **Funciones largas pero lineales.** Una función que arma HTML puede tener CCN bajo y 150 líneas: hay
  que mirar también las líneas de código.
- **Funciones anónimas.** En JavaScript cada callback (`forEach(x => …)`) se mide aparte de la función
  que lo contiene. La función que lo contiene "parece" más simple de lo que es.
- **No mide anidamiento ni nombres.** Dos funciones con el mismo CCN pueden leerse muy distinto.

## Estado general

**Saludable, con la deuda concentrada.** De 388 funciones, el 93 % está en A o B y la mediana es 2. Hay
10 funciones en D o F, en 7 archivos, y 17 en C. Todas las demás se entienden de una lectura.

Lo más importante: **el núcleo de precios y totales está en A–B**. Es el código cuyo error cuesta plata y
el que más se toca. Además, los tests lo recorren casi entero:

| Función | Qué hace | CCN | Cobertura |
|---|---|--:|--:|
| `product.template._price_compute` | Precio de matriz convertido a la moneda de la lista | 4 | 100 % |
| `sale.order._compute_totales_cotizador` | Cascada de totales | 2 | 100 % |
| `sale.order._cotizador_update_adjustments` | Recalcula descuentos y plan sobre el neto | 10 | 100 % |
| `sale.order._cotizador_tax_groups` | Base de cada grupo de impuestos | 5 | 100 % |
| `sale.order.line._compute_price_unit` | No pisa el precio de las líneas especiales | 3 | 100 % |
| `sembradora.config.rel._get_accessory_offer` | Accesorios y precios de una configuración | 8 | 94 % |
| `sembradora.config.rel._get_variant` | Variante de una configuración | 3 | 77 % |
| `product.template._filter_combinations_impossible_by_config` | Una variante por configuración | 8 | 100 % |

*Cobertura*: porcentaje de las líneas de la función que ejecutan los tests del módulo (`coverage.py`,
noviembre de 2026). En total, los tests recorren el 86 % de las líneas de Python del servidor. El
JavaScript no se mide; lo prueban los dos tours.

La complejidad alta está en los **bordes**: leer archivos (importador, Teamcenter), dibujar pantallas
(configurador de la tienda, asistentes) y validar el formulario público. Ahí un error se ve enseguida (un
mensaje, una pantalla que no dibuja), no es un importe equivocado en silencio.

### El riesgo real: complejo y sin tests

Una función compleja con tests se puede cambiar: si se rompe un caso, un test avisa. Una compleja
**sin** tests es donde un cambio rompe algo sin que nadie se entere. Cruzando las dos medidas (funciones C
o peor del servidor):

| Función | CCN | Cobertura | Qué hace |
|---|--:|--:|---|
| `sale.order.action_ver_bcra_wizard` | 11 | 6 % | Informe BCRA |
| `cotizador.plan.pago.template.line._compute_name` | 18 | 9 % | Nombre de una opción de plan |
| `cotizador.plan.pago.template.line.action_select_line` | 26 | 65 % | Agregar un plan a la cotización |

Las tres son de bajo riesgo: el informe BCRA solo muestra datos y las dos del plan de pago se reordenan
con la mejora 1 de la lista de abajo.

El hueco más grande eran el **Studio** (27 % de cobertura) y el **Asistente de Precios** (39 %), que
escribían la matriz y los precios casi sin tests. Eran pruebas de concepto: se sacaron de `dev` y `main`
(la matriz se edita con el importador CSV) y quedan archivados en la rama `poc/studio-precios`. Con ellos
se fueron unas 3.900 líneas.

Teamcenter estaba en esta tabla (plantilla 2 %, lectura del archivo 53 %) hasta que se escribió
`tests/test_teamcenter.py`: plantilla en Excel y CSV, ida y vuelta con Ingeniería, archivos parciales e
ids cruzados. El archivo pasó de 58 % a 87 %, y los tests encontraron un error: los mensajes de
`action_generate_template` fallaban con `UnboundLocalError` porque un bucle usaba `_` como variable.

## Puntos críticos

Las 10 funciones en rango D o F, de mayor a menor. Para cada una: por qué es compleja, qué riesgo tiene y
cómo bajarla. La cobertura es la de los tests del módulo (`tests/`) medida con `coverage.py`.

### F · `engineering.code.wizard.action_analyze_file` — CCN 57, 192 líneas

[models/engineering_code_wizard.py](../models/engineering_code_wizard.py#L271) · Teamcenter, paso 2.

**Por qué.** Hace cinco cosas en una función: arma los mapas de búsqueda (variantes y configuraciones por
id y por tupla de valores), detecta la columna del código y las de atributos, cruza cada fila (primero
por `ID_Odoo`, después por valores con la tabla de alias) y arma el informe HTML con f-strings. Solo el
informe suma ~10 caminos.

**Riesgo.** Medio. El cruce es la parte delicada: un cruce equivocado escribe el código de Teamcenter en
la variante que no es. El HTML interpola valores del archivo sin escapar; hoy los limpia el sanitizador
del campo `preview_html`, pero depende de él. La tabla de alias está en [Pendientes](pendientes.md) #1.
Cobertura: 90 %.

**Propuesta.** Dividir en `_lookup_maps()`, `_detect_columns(first_row)` y `_match_row(row, maps)`.
Pasar el informe a una plantilla QWeb (`ir.qweb._render`), que escapa sola. Cuando vuelva la plantilla
de Ingeniería y se quite la tabla de alias (Pendientes #1), `_match_row` queda en ~5. El cálculo de
`total_variants` por producto cartesiano de valores es del diseño anterior (variantes dinámicas) y se puede
borrar: hoy una máquina con configuraciones siempre tiene sus variantes.

### F · `render` (configurador de la tienda) — CCN 43, 182 líneas

[static/src/js/cotizador_sequential_configurator.js](../static/src/js/cotizador_sequential_configurator.js#L224)

**Por qué.** Redibuja todo el configurador paso a paso en una función: estados vacíos, barra de
progreso, chips de lo elegido, botón anterior, resumen final o paso activo (con el rango de precios de
cada opción), próximos pasos y habilitación de los botones. Unos 20 de los 43 caminos son
`if (this.elemento)`: verificar que cada nodo exista antes de tocarlo.

**Riesgo.** Bajo para los datos (el servidor revalida la configuración), alto para el mantenimiento:
cualquier cambio visual de la ficha pasa por esta función. El tour `cotizador_website_quote_tour` cubre el
camino feliz.

**Propuesta.** Dividir en `renderProgress()`, `renderChips()`, `renderSummary(config)`,
`renderStep()`, `renderUpcoming()` y `setQuoteEnabled(bool)`. Reemplazar los `if (this.x)` por
`this.x?.…` o exigir los nodos una vez en `setup()`. Mover el HTML a plantillas QWeb
(`renderToElement`). Resultado esperado: ninguna parte arriba de 8.

### F · `sembradora.import.wizard._parse` — CCN 42, 104 líneas

[models/sembradora_import_wizard.py](../models/sembradora_import_wizard.py#L183) · Importador.

**Por qué.** Valida encabezados y después recorre las filas tratando los tres tipos (BASE, OPCIONAL,
ESTANDAR) y las reglas en el mismo bucle. Cada validación es un camino. **Buena parte de la complejidad es
del problema**: el importador tiene que rechazar con un mensaje claro cada error posible del CSV.

**Riesgo.** Bajo: `tests/test_importer.py` la recorre en un 83 % y la función no escribe nada; un error se
ve en el análisis antes de importar.

**Propuesta.** Separar `_parse_header()`, `_parse_base_row()`, `_parse_accessory_row()` y
`_parse_rules(where, texto)`. La suma de caminos no baja, pero cada parte queda en B–C y se puede probar
sola. Prioridad baja.

### D · `cotizador.plan.pago.template.line.action_select_line` — CCN 26, 56 líneas

[models/plan_pago.py](../models/plan_pago.py#L101) · Plan de pago.

**Por qué.** Busca la cotización en tres lugares del contexto y arma la descripción con un `if/elif` por
tipo de plan, campo por campo con `or '-'` (la mitad del número). `_compute_name` (CCN 18, unas líneas
arriba) repite la misma cadena de `if/elif` con otros textos.

**Riesgo.** Bajo, pero agregar un tipo de plan obliga a tocar dos cadenas de `if/elif` y es fácil
olvidarse de una. Cobertura: 65 % (los tests usan un solo tipo de plan); `_compute_name`, 9 %.

**Propuesta.** Una sola tabla por tipo, `{tipo: [(etiqueta, campo), …]}`, que usen las dos funciones.
Agregar un tipo pasa a ser agregar una entrada. Las dos bajan a ~5.

### D · `sembradora.import.wizard._validate_parsed` — CCN 26, 45 líneas

[models/sembradora_import_wizard.py](../models/sembradora_import_wizard.py#L320) · Importador.

**Por qué / riesgo.** Una validación tras otra, sobre todos los archivos juntos. Complejidad del problema,
bien probada (cobertura 98 %).

**Propuesta.** Si se divide `_parse`, dividir también en `_validate_quantities()`,
`_validate_configs()` y `_validate_slugs()`. Prioridad baja.

### D · `faltantes_js` — CCN 25, 31 líneas

[tools/documentacion.py](../tools/documentacion.py#L150) · Verificador de documentación.

**Por qué / riesgo.** Lee JavaScript con expresiones regulares y busca el bloque `/** */` de cada
definición. Es una herramienta de desarrollo: si falla, falla un test, no producción.

**Propuesta.** Extraer `_bloque_doc_anterior(lineas, numero)`. Prioridad baja.

### D · `engineering.code.wizard._parse_input_file` — CCN 22, 37 líneas

[models/engineering_code_wizard.py](../models/engineering_code_wizard.py#L219) · Teamcenter.

**Por qué.** Dos formatos (Excel y CSV) en una función, con prueba de codificaciones y detección del
separador. Cobertura: 78 % (Excel y CSV).

**Propuesta.** `_rows_from_xlsx(bytes)` y `_rows_from_csv(bytes)`. El importador decodifica sus CSV por
su cuenta (`_read_files`): las dos lecturas se pueden unificar en una función del módulo.

### D · `_evaluateAccessoryRules` (configurador del vendedor) — CCN 22, 61 líneas

[static/src/components/configurador/configurador.js](../static/src/components/configurador/configurador.js#L607)

**Por qué.** Agrupa los accesorios por regla y después aplica exclusión e inclusión, todo en una función.

**Riesgo.** Bajo para los datos: `sale.order._cotizador_add_configuration()` vuelve a validar las reglas
en el servidor. Lo cubre el tour `cotizador_configurator_tour`.

**Propuesta.** `_groupAccessoriesByRule()` y un manejador por tipo de regla
(`_lockExcluded(state)`, `_lockUntriggered(state)`).

### D · `CotizadorWebsiteController.solicitar_cotizacion` — CCN 21, 39 líneas

[controllers/main.py](../controllers/main.py#L175) · Formulario público.

**Por qué.** Una cadena de guardas en orden (trampa para bots, captcha, token, datos, configuración,
límite de solicitudes), cada una con su salida. 6 de los 21 son el `or ''` de limpiar cada campo.

**Riesgo.** Bajo: se lee de arriba abajo y `tests/test_public_quote.py` prueba los rechazos (cobertura
84 %). El orden de las guardas importa (ver [Seguridad](seguridad.md)).

**Propuesta.** Extraer `_clean_contact(post)`, que devuelva los campos ya recortados. Prioridad baja:
la cadena de guardas es el estilo correcto para este caso.

### D · `engineering.code.wizard.action_generate_template` — CCN 21, 85 líneas

[models/engineering_code_wizard.py](../models/engineering_code_wizard.py#L76) · Teamcenter, paso 1.

**Por qué.** Tres orígenes de filas (variantes, configuraciones, producto cartesiano de valores) y dos
formatos de salida (Excel y CSV). Cobertura: 84 % (`tests/test_teamcenter.py`); lo único que los tests
no recorren son los dos orígenes del diseño anterior.

**Propuesta.** Los orígenes "configuraciones" y "producto cartesiano" son del diseño anterior: hoy cada
configuración tiene su variante, así que alcanza con las variantes. Borrarlos (sin compatibilidad hacia
atrás, ver [Arquitectura](arquitectura.md#decisiones-de-diseño-que-conviene-conocer)) y separar
`_write_xlsx()` / `_write_csv()` la deja en ~6.

### Rango C

Las 17 funciones C (lista completa más abajo) no necesitan cambios urgentes. Se repiten dos patrones:

- **Servicios RPC que arman el JSON de una pantalla** (`get_model_matrix`, `get_config_accessories`):
  recorren registros y deciden qué incluir. Se pueden dividir si crecen.
- **Inflación por `or`**: `_compute_name`, `_create_lead` (además tiene 11 parámetros: conviene pasarle un
  dict) y `_sync_with_crm`.

`sale.order._cotizador_add_configuration` (CCN 18) es la única C del núcleo: los tres caminos para cotizar
(configurador, CRM y tienda) terminan ahí. Los tests la recorren entera (100 %) y conviene que no crezca
más: lo nuevo, en funciones aparte.

## Mejoras priorizadas

Ordenadas por beneficio sobre esfuerzo. Todas tienen tests que las cubren: se pueden hacer sin miedo.

| # | Función | Cambio | Esfuerzo | CCN hoy → esperado |
|---|---|---|---|---|
| 1 | `action_select_line` + `_compute_name` | Una tabla de campos por tipo de plan | Bajo | 26 + 18 → ~5 + ~5 |
| 2 | `action_generate_template` | Borrar los orígenes del diseño anterior, separar Excel y CSV | Bajo | 21 → ~6 |
| 3 | `action_analyze_file` | Dividir en mapas, columnas y cruce; informe en QWeb | Medio | 57 → ninguna parte > 10 |
| 4 | `render` (tienda) | Una función por zona de la pantalla; `?.`; plantillas | Medio | 43 → ninguna parte > 8 |
| 5 | `_parse_input_file` | Excel y CSV aparte; una sola lectura de CSV con el importador | Bajo | 22 → ~8 |
| 6 | `_evaluateAccessoryRules` | Agrupar y un manejador por tipo de regla | Bajo | 22 → ~8 |
| 7 | `_parse` / `_validate_parsed` | Una función por tipo de fila y por grupo de validaciones | Medio | 42 / 26 → B–C cada parte |

Los puntos 3 y 5 conviene hacerlos junto con Pendientes #1 (la tabla de alias), cuando vuelva la
plantilla de Ingeniería.

## Reglas para el código nuevo

1. **CCN ≤ 10** (rango B) en toda función nueva. Si el problema pide más (una validación larga), dejar
   escrito por qué en el docstring.
2. **No hacer crecer una función C o peor**: lo nuevo, en una función aparte que se llame desde ahí.
3. **Una función, una tarea**: si el docstring necesita "y después…", son dos funciones.
4. **Tablas en vez de cadenas de `if/elif`** cuando se elige por un tipo (plan de pago, tipo de regla,
   tipo de ajuste).
5. **HTML en plantillas** (QWeb en Python y en JavaScript), no en f-strings: escapan solas y no suman
   caminos.
6. Al cambiar código, **regenerar este documento** y commitearlo junto.

## Regenerar

Desde la carpeta del módulo (no necesita Odoo ni una base):

```bash
uv run --no-project --with lizard==1.25.0 python tools/complejidad.py
```

Reescribe solo lo que está entre los marcadores `complejidad:inicio` y `complejidad:fin`; el análisis de
arriba se actualiza a mano. Si una función de la sección *Puntos críticos* cambia de
rango, corregir su texto. Las cifras de *Estado general* son de noviembre de 2026.

La cobertura de tests se mide aparte, en una base de prueba:

```bash
python -m coverage run --source=addons/cotizador --omit='*/tests/*,*/scripts/*' \
    odoo-bin -d <base_de_prueba> -i cotizador --test-tags /cotizador --stop-after-init --http-port 8299
python -m coverage report --show-missing
```

<!-- complejidad:inicio (generado por tools/complejidad.py, no editar a mano) -->

## Resumen por área

| Área | Funciones | Líneas de código | CCN promedio | CCN máxima | CCN > 10 | A | B | C | D | E | F |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| Servidor | 199 | 2673 | 5.5 | 57 | 21 | 142 | 36 | 13 | 6 | 0 | 2 |
| Navegador | 86 | 945 | 3.3 | 43 | 4 | 76 | 6 | 2 | 1 | 0 | 1 |
| Tests | 90 | 725 | 1.5 | 5 | 0 | 90 | 0 | 0 | 0 | 0 | 0 |
| Herramientas de escritorio | 13 | 218 | 3.4 | 12 | 2 | 11 | 0 | 2 | 0 | 0 | 0 |
| **Total** | 388 | 4561 | 4.0 | 57 | 27 | 319 | 42 | 17 | 7 | 0 | 3 |

## Funciones que requieren atención (CCN > 10)

Ordenadas de mayor a menor complejidad.

| CCN | Rango | Función | Ubicación | Líneas de código | Parámetros |
|--:|:-:|---|---|--:|--:|
| 57 | F | `action_analyze_file` | [models/engineering_code_wizard.py:271](../models/engineering_code_wizard.py#L271) | 192 | 1 |
| 43 | F | `render` | [static/src/js/cotizador_sequential_configurator.js:224](../static/src/js/cotizador_sequential_configurator.js#L224) | 182 | 0 |
| 42 | F | `_parse` | [models/sembradora_import_wizard.py:183](../models/sembradora_import_wizard.py#L183) | 104 | 2 |
| 26 | D | `action_select_line` | [models/plan_pago.py:101](../models/plan_pago.py#L101) | 56 | 1 |
| 26 | D | `_validate_parsed` | [models/sembradora_import_wizard.py:320](../models/sembradora_import_wizard.py#L320) | 45 | 2 |
| 25 | D | `faltantes_js` | [tools/documentacion.py:150](../tools/documentacion.py#L150) | 31 | 0 |
| 22 | D | `_parse_input_file` | [models/engineering_code_wizard.py:219](../models/engineering_code_wizard.py#L219) | 37 | 1 |
| 22 | D | `_evaluateAccessoryRules` | [static/src/components/configurador/configurador.js:607](../static/src/components/configurador/configurador.js#L607) | 61 | 0 |
| 21 | D | `solicitar_cotizacion` | [controllers/main.py:175](../controllers/main.py#L175) | 39 | 2 |
| 21 | D | `action_generate_template` | [models/engineering_code_wizard.py:76](../models/engineering_code_wizard.py#L76) | 85 | 1 |
| 20 | C | `validate_rule_set` | [models/sembradora_config.py:12](../models/sembradora_config.py#L12) | 33 | 1 |
| 18 | C | `_compute_name` | [models/plan_pago.py:87](../models/plan_pago.py#L87) | 12 | 1 |
| 18 | C | `_cotizador_add_configuration` | [models/sale_order_inherit.py:663](../models/sale_order_inherit.py#L663) | 47 | 3 |
| 16 | C | `_build_analysis_html` | [models/sembradora_import_wizard.py:490](../models/sembradora_import_wizard.py#L490) | 36 | 3 |
| 15 | C | `action_confirm` | [models/descuento_wizard.py:102](../models/descuento_wizard.py#L102) | 47 | 1 |
| 15 | C | `setup` | [static/src/js/cotizador_sequential_configurator.js:45](../static/src/js/cotizador_sequential_configurator.js#L45) | 51 | 0 |
| 14 | C | `get_model_matrix` | [models/configurator_service.py:81](../models/configurator_service.py#L81) | 62 | 3 |
| 13 | C | `get_config_accessories` | [models/configurator_service.py:163](../models/configurator_service.py#L163) | 47 | 3 |
| 13 | C | `_sync_with_crm` | [models/sale_order_inherit.py:419](../models/sale_order_inherit.py#L419) | 31 | 1 |
| 13 | C | `_detalle` | [tools/documentacion.py:299](../tools/documentacion.py#L299) | 18 | 1 |
| 12 | C | `_sync_expected_revenue_from_orders` | [models/crm_lead_inherit.py:56](../models/crm_lead_inherit.py#L56) | 21 | 1 |
| 12 | C | `run` | [scripts/split_csv_gui.py:48](../scripts/split_csv_gui.py#L48) | 43 | 1 |
| 12 | C | `formatOptionName` | [static/src/js/cotizador_sequential_configurator.js:125](../static/src/js/cotizador_sequential_configurator.js#L125) | 18 | 2 |
| 11 | C | `_create_lead` | [controllers/main.py:232](../controllers/main.py#L232) | 29 | 11 |
| 11 | C | `_parse_deudas` | [models/bcra_service.py:96](../models/bcra_service.py#L96) | 26 | 1 |
| 11 | C | `action_ver_bcra_wizard` | [models/sale_order_inherit.py:359](../models/sale_order_inherit.py#L359) | 47 | 1 |
| 11 | C | `split_sembradora_csv` | [scripts/split_csv.py:18](../scripts/split_csv.py#L18) | 37 | 3 |

## Por archivo

| Archivo | Funciones | Líneas de código | CCN promedio | CCN máxima | Peor rango | CCN > 10 |
|---|--:|--:|--:|--:|:-:|--:|
| [controllers/main.py](../controllers/main.py) | 16 | 155 | 4.2 | 21 | D | 2 |
| [models/bcra_service.py](../models/bcra_service.py) | 6 | 87 | 5.8 | 11 | C | 1 |
| [models/bcra_wizard.py](../models/bcra_wizard.py) | 1 | 2 | 1.0 | 1 | A | 0 |
| [models/configurator_service.py](../models/configurator_service.py) | 4 | 160 | 10.2 | 14 | C | 2 |
| [models/crm_lead_inherit.py](../models/crm_lead_inherit.py) | 5 | 62 | 5.2 | 12 | C | 1 |
| [models/descuento_wizard.py](../models/descuento_wizard.py) | 5 | 67 | 6.2 | 15 | C | 1 |
| [models/engineering_code_wizard.py](../models/engineering_code_wizard.py) | 6 | 367 | 18.7 | 57 | F | 3 |
| [models/equipo_usado_wizard.py](../models/equipo_usado_wizard.py) | 1 | 34 | 7.0 | 7 | B | 0 |
| [models/plan_pago.py](../models/plan_pago.py) | 4 | 77 | 12.0 | 26 | D | 2 |
| [models/product_category_inherit.py](../models/product_category_inherit.py) | 1 | 11 | 3.0 | 3 | A | 0 |
| [models/product_template_inherit.py](../models/product_template_inherit.py) | 22 | 172 | 3.8 | 10 | B | 0 |
| [models/res_config_settings.py](../models/res_config_settings.py) | 3 | 19 | 2.0 | 3 | A | 0 |
| [models/sale_order_inherit.py](../models/sale_order_inherit.py) | 45 | 466 | 3.9 | 18 | C | 3 |
| [models/sembradora_accessory_rule.py](../models/sembradora_accessory_rule.py) | 1 | 4 | 2.0 | 2 | A | 0 |
| [models/sembradora_config.py](../models/sembradora_config.py) | 18 | 219 | 4.6 | 20 | C | 1 |
| [models/sembradora_config_acc_line.py](../models/sembradora_config_acc_line.py) | 1 | 9 | 4.0 | 4 | A | 0 |
| [models/sembradora_import_wizard.py](../models/sembradora_import_wizard.py) | 26 | 429 | 6.7 | 42 | F | 3 |
| [scripts/split_csv.py](../scripts/split_csv.py) | 2 | 48 | 7.0 | 11 | C | 1 |
| [scripts/split_csv_gui.py](../scripts/split_csv_gui.py) | 11 | 170 | 2.7 | 12 | C | 1 |
| [static/src/components/configurador/configurador.js](../static/src/components/configurador/configurador.js) | 60 | 561 | 3.0 | 22 | D | 1 |
| [static/src/js/cotizador_quote_form.js](../static/src/js/cotizador_quote_form.js) | 2 | 6 | 1.0 | 1 | A | 0 |
| [static/src/js/cotizador_sequential_configurator.js](../static/src/js/cotizador_sequential_configurator.js) | 24 | 378 | 4.3 | 43 | F | 3 |
| [static/tests/tours/cotizador_tours.js](../static/tests/tours/cotizador_tours.js) | 2 | 24 | 1.0 | 1 | A | 0 |
| [tests/common.py](../tests/common.py) | 8 | 29 | 1.2 | 2 | A | 0 |
| [tests/test_cascade_variants.py](../tests/test_cascade_variants.py) | 11 | 95 | 1.3 | 2 | A | 0 |
| [tests/test_configurator.py](../tests/test_configurator.py) | 12 | 138 | 2.2 | 5 | A | 0 |
| [tests/test_documentacion.py](../tests/test_documentacion.py) | 2 | 7 | 1.0 | 1 | A | 0 |
| [tests/test_importer.py](../tests/test_importer.py) | 11 | 120 | 1.5 | 3 | A | 0 |
| [tests/test_public_quote.py](../tests/test_public_quote.py) | 11 | 80 | 1.4 | 2 | A | 0 |
| [tests/test_review_fixes.py](../tests/test_review_fixes.py) | 11 | 75 | 1.1 | 2 | A | 0 |
| [tests/test_teamcenter.py](../tests/test_teamcenter.py) | 19 | 142 | 1.7 | 5 | A | 0 |
| [tests/test_tours.py](../tests/test_tours.py) | 3 | 15 | 1.0 | 1 | A | 0 |
| [tools/complejidad.py](../tools/complejidad.py) | 11 | 100 | 4.0 | 8 | B | 0 |
| [tools/documentacion.py](../tools/documentacion.py) | 21 | 224 | 6.6 | 25 | D | 2 |
| [tools/mkdocs_hooks.py](../tools/mkdocs_hooks.py) | 2 | 9 | 2.5 | 3 | A | 0 |

## Todas las funciones

Por archivo y en orden de aparición. Las funciones anónimas de JavaScript (callbacks) se miden aparte de la función que las contiene.

<details><summary><code>controllers/main.py</code> — 16 funciones, CCN máxima 21</summary>

| Línea | Función | CCN | Rango | Líneas de código | Parámetros |
|--:|---|--:|:-:|--:|--:|
| [46](../controllers/main.py#L46) | `_to_int` | 3 | A | 5 | 1 |
| [58](../controllers/main.py#L58) | `_text_to_html` | 1 | A | 2 | 1 |
| [67](../controllers/main.py#L67) | `quote_only_mode` | 1 | A | 4 | 0 |
| [85](../controllers/main.py#L85) | `form_token` | 1 | A | 3 | 1 |
| [96](../controllers/main.py#L96) | `_check_form_token` | 4 | A | 9 | 2 |
| [113](../controllers/main.py#L113) | `_contact_domain` | 4 | A | 4 | 2 |
| [124](../controllers/main.py#L124) | `_is_rate_limited` | 6 | B | 12 | 4 |
| [148](../controllers/main.py#L148) | `_quote_error_redirect` | 2 | A | 2 | 3 |
| [163](../controllers/main.py#L163) | `solicitud_recibida` | 1 | A | 2 | 2 |
| [175](../controllers/main.py#L175) | `solicitar_cotizacion` | 21 | D | 39 | 2 |
| [232](../controllers/main.py#L232) | `_create_lead` | 11 | C | 29 | 11 |
| [281](../controllers/main.py#L281) | `_create_order` | 5 | A | 27 | 5 |
| [331](../controllers/main.py#L331) | `shop_checkout` | 2 | A | 4 | 3 |
| [343](../controllers/main.py#L343) | `shop_payment` | 2 | A | 4 | 2 |
| [354](../controllers/main.py#L354) | `process_express_checkout` | 2 | A | 5 | 5 |
| [374](../controllers/main.py#L374) | `shop_payment_transaction` | 2 | A | 4 | 4 |

</details>

<details><summary><code>models/bcra_service.py</code> — 6 funciones, CCN máxima 11</summary>

| Línea | Función | CCN | Rango | Líneas de código | Parámetros |
|--:|---|--:|:-:|--:|--:|
| [52](../models/bcra_service.py#L52) | `sanitize_cuit` | 3 | A | 5 | 1 |
| [64](../models/bcra_service.py#L64) | `format_pesos` | 1 | A | 2 | 1 |
| [73](../models/bcra_service.py#L73) | `_fetch_results` | 4 | A | 13 | 2 |
| [96](../models/bcra_service.py#L96) | `_parse_deudas` | 11 | C | 26 | 1 |
| [132](../models/bcra_service.py#L132) | `_parse_cheques` | 6 | B | 11 | 1 |
| [151](../models/bcra_service.py#L151) | `consultar_bcra_completo` | 10 | B | 30 | 1 |

</details>

<details><summary><code>models/bcra_wizard.py</code> — 1 funciones, CCN máxima 1</summary>

| Línea | Función | CCN | Rango | Líneas de código | Parámetros |
|--:|---|--:|:-:|--:|--:|
| [20](../models/bcra_wizard.py#L20) | `_default_currency` | 1 | A | 2 | 1 |

</details>

<details><summary><code>models/configurator_service.py</code> — 4 funciones, CCN máxima 14</summary>

| Línea | Función | CCN | Rango | Líneas de código | Parámetros |
|--:|---|--:|:-:|--:|--:|
| [25](../models/configurator_service.py#L25) | `get_initial_data` | 10 | B | 37 | 2 |
| [81](../models/configurator_service.py#L81) | `get_model_matrix` | 14 | C | 62 | 3 |
| [163](../models/configurator_service.py#L163) | `get_config_accessories` | 13 | C | 47 | 3 |
| [226](../models/configurator_service.py#L226) | `confirm_configuration` | 4 | A | 14 | 4 |

</details>

<details><summary><code>models/crm_lead_inherit.py</code> — 5 funciones, CCN máxima 12</summary>

| Línea | Función | CCN | Rango | Líneas de código | Parámetros |
|--:|---|--:|:-:|--:|--:|
| [50](../models/crm_lead_inherit.py#L50) | `_compute_lider_equipo_id` | 5 | A | 4 | 1 |
| [56](../models/crm_lead_inherit.py#L56) | `_sync_expected_revenue_from_orders` | 12 | C | 21 | 1 |
| [87](../models/crm_lead_inherit.py#L87) | `create` | 3 | A | 6 | 2 |
| [99](../models/crm_lead_inherit.py#L99) | `write` | 2 | A | 5 | 2 |
| [110](../models/crm_lead_inherit.py#L110) | `action_cotizador_create_quotation` | 4 | A | 26 | 1 |

</details>

<details><summary><code>models/descuento_wizard.py</code> — 5 funciones, CCN máxima 15</summary>

| Línea | Función | CCN | Rango | Líneas de código | Parámetros |
|--:|---|--:|:-:|--:|--:|
| [72](../models/descuento_wizard.py#L72) | `_compute_base_neto` | 3 | A | 4 | 1 |
| [79](../models/descuento_wizard.py#L79) | `_compute_monto_descuento` | 5 | A | 6 | 1 |
| [87](../models/descuento_wizard.py#L87) | `_inverse_monto_descuento` | 3 | A | 4 | 1 |
| [94](../models/descuento_wizard.py#L94) | `_onchange_nombre_sugerido` | 5 | A | 6 | 1 |
| [102](../models/descuento_wizard.py#L102) | `action_confirm` | 15 | C | 47 | 1 |

</details>

<details><summary><code>models/engineering_code_wizard.py</code> — 6 funciones, CCN máxima 57</summary>

| Línea | Función | CCN | Rango | Líneas de código | Parámetros |
|--:|---|--:|:-:|--:|--:|
| [76](../models/engineering_code_wizard.py#L76) | `action_generate_template` | 21 | D | 85 | 1 |
| [198](../models/engineering_code_wizard.py#L198) | `_clean_str` | 4 | A | 13 | 2 |
| [219](../models/engineering_code_wizard.py#L219) | `_parse_input_file` | 22 | D | 37 | 1 |
| [271](../models/engineering_code_wizard.py#L271) | `action_analyze_file` | 57 | F | 192 | 1 |
| [539](../models/engineering_code_wizard.py#L539) | `action_apply_codes` | 7 | B | 26 | 1 |
| [589](../models/engineering_code_wizard.py#L589) | `action_back_to_upload` | 1 | A | 14 | 1 |

</details>

<details><summary><code>models/equipo_usado_wizard.py</code> — 1 funciones, CCN máxima 7</summary>

| Línea | Función | CCN | Rango | Líneas de código | Parámetros |
|--:|---|--:|:-:|--:|--:|
| [39](../models/equipo_usado_wizard.py#L39) | `action_confirm` | 7 | B | 34 | 1 |

</details>

<details><summary><code>models/plan_pago.py</code> — 4 funciones, CCN máxima 26</summary>

| Línea | Función | CCN | Rango | Líneas de código | Parámetros |
|--:|---|--:|:-:|--:|--:|
| [87](../models/plan_pago.py#L87) | `_compute_name` | 18 | C | 12 | 1 |
| [101](../models/plan_pago.py#L101) | `action_select_line` | 26 | D | 56 | 1 |
| [214](../models/plan_pago.py#L214) | `_compute_total_simulado` | 3 | A | 4 | 1 |
| [220](../models/plan_pago.py#L220) | `action_select_line` | 1 | A | 5 | 1 |

</details>

<details><summary><code>models/product_category_inherit.py</code> — 1 funciones, CCN máxima 3</summary>

| Línea | Función | CCN | Rango | Líneas de código | Parámetros |
|--:|---|--:|:-:|--:|--:|
| [26](../models/product_category_inherit.py#L26) | `_check_cotizador_qty_attribute_unique` | 3 | A | 11 | 1 |

</details>

<details><summary><code>models/product_template_inherit.py</code> — 22 funciones, CCN máxima 10</summary>

| Línea | Función | CCN | Rango | Líneas de código | Parámetros |
|--:|---|--:|:-:|--:|--:|
| [21](../models/product_template_inherit.py#L21) | `_in_category` | 5 | A | 2 | 2 |
| [81](../models/product_template_inherit.py#L81) | `_compute_cotizador_kind` | 2 | A | 6 | 1 |
| [94](../models/product_template_inherit.py#L94) | `_check_cotizador_modelo` | 1 | A | 3 | 1 |
| [103](../models/product_template_inherit.py#L103) | `_compute_available_attributes` | 2 | A | 3 | 1 |
| [108](../models/product_template_inherit.py#L108) | `get_config_description` | 10 | B | 13 | 2 |
| [133](../models/product_template_inherit.py#L133) | `action_open_engineering_wizard` | 1 | A | 9 | 1 |
| [147](../models/product_template_inherit.py#L147) | `get_sequential_configurator_json` | 7 | B | 36 | 1 |
| [196](../models/product_template_inherit.py#L196) | `_cotizador_config_index` | 2 | A | 3 | 2 |
| [209](../models/product_template_inherit.py#L209) | `_cotizador_find_config` | 3 | A | 7 | 2 |
| [222](../models/product_template_inherit.py#L222) | `_is_combination_possible` | 4 | A | 9 | 4 |
| [245](../models/product_template_inherit.py#L245) | `_create_variant_ids` | 2 | A | 4 | 1 |
| [257](../models/product_template_inherit.py#L257) | `_cotizador_sync_variants` | 3 | A | 4 | 1 |
| [267](../models/product_template_inherit.py#L267) | `_filter_combinations_impossible_by_config` | 8 | B | 11 | 3 |
| [295](../models/product_template_inherit.py#L295) | `_with_matrix_price` | 1 | A | 3 | 2 |
| [304](../models/product_template_inherit.py#L304) | `_get_product_price_context` | 3 | A | 7 | 2 |
| [318](../models/product_template_inherit.py#L318) | `_cotizador_convert_matrix_price` | 5 | A | 8 | 6 |
| [336](../models/product_template_inherit.py#L336) | `_cotizador_matrix_list_price` | 7 | B | 9 | 1 |
| [351](../models/product_template_inherit.py#L351) | `_price_compute` | 4 | A | 8 | 6 |
| [374](../models/product_template_inherit.py#L374) | `_with_matrix_price` | 1 | A | 3 | 2 |
| [383](../models/product_template_inherit.py#L383) | `_cotizador_matrix_list_price` | 5 | A | 11 | 1 |
| [400](../models/product_template_inherit.py#L400) | `_price_compute` | 4 | A | 10 | 6 |
| [463](../models/product_template_inherit.py#L463) | `_onchange_value_ids_name` | 3 | A | 3 | 1 |

</details>

<details><summary><code>models/res_config_settings.py</code> — 3 funciones, CCN máxima 3</summary>

| Línea | Función | CCN | Rango | Líneas de código | Parámetros |
|--:|---|--:|:-:|--:|--:|
| [73](../models/res_config_settings.py#L73) | `_compute_cotizador_captcha_configured` | 3 | A | 5 | 1 |
| [80](../models/res_config_settings.py#L80) | `set_values` | 2 | A | 6 | 1 |
| [88](../models/res_config_settings.py#L88) | `get_values` | 1 | A | 8 | 1 |

</details>

<details><summary><code>models/sale_order_inherit.py</code> — 45 funciones, CCN máxima 18</summary>

| Línea | Función | CCN | Rango | Líneas de código | Parámetros |
|--:|---|--:|:-:|--:|--:|
| [41](../models/sale_order_inherit.py#L41) | `_default_condiciones_generales` | 1 | A | 5 | 1 |
| [59](../models/sale_order_inherit.py#L59) | `_default_plan_pago_line_ids` | 2 | A | 7 | 1 |
| [83](../models/sale_order_inherit.py#L83) | `_default_portal_confirmation_mode` | 1 | A | 4 | 1 |
| [123](../models/sale_order_inherit.py#L123) | `_get_maquina_template` | 1 | A | 3 | 1 |
| [132](../models/sale_order_inherit.py#L132) | `_compute_equipo_cotizado_id` | 4 | A | 7 | 1 |
| [223](../models/sale_order_inherit.py#L223) | `_compute_totales_cotizador` | 2 | A | 23 | 1 |
| [254](../models/sale_order_inherit.py#L254) | `_cotizador_tax_groups` | 5 | A | 10 | 2 |
| [273](../models/sale_order_inherit.py#L273) | `_cotizador_update_adjustments` | 10 | B | 16 | 1 |
| [298](../models/sale_order_inherit.py#L298) | `_recompute_prices` | 1 | A | 3 | 1 |
| [308](../models/sale_order_inherit.py#L308) | `_cotizador_simulate_plan` | 3 | A | 7 | 2 |
| [326](../models/sale_order_inherit.py#L326) | `_compute_lineas_especiales` | 2 | A | 4 | 1 |
| [335](../models/sale_order_inherit.py#L335) | `_onchange_partner_id_bcra` | 9 | B | 17 | 1 |
| [359](../models/sale_order_inherit.py#L359) | `action_ver_bcra_wizard` | 11 | C | 47 | 1 |
| [419](../models/sale_order_inherit.py#L419) | `_sync_with_crm` | 13 | C | 31 | 1 |
| [461](../models/sale_order_inherit.py#L461) | `_onchange_equipo_cotizado_id_pricelist` | 3 | A | 4 | 1 |
| [468](../models/sale_order_inherit.py#L468) | `create` | 9 | B | 15 | 2 |
| [490](../models/sale_order_inherit.py#L490) | `write` | 3 | A | 5 | 2 |
| [501](../models/sale_order_inherit.py#L501) | `action_enable_portal_confirmation` | 1 | A | 11 | 1 |
| [514](../models/sale_order_inherit.py#L514) | `action_disable_portal_confirmation` | 1 | A | 10 | 1 |
| [526](../models/sale_order_inherit.py#L526) | `_has_to_be_signed` | 5 | A | 10 | 1 |
| [542](../models/sale_order_inherit.py#L542) | `_has_to_be_paid` | 5 | A | 10 | 1 |
| [558](../models/sale_order_inherit.py#L558) | `_confirmation_error_message` | 9 | B | 15 | 1 |
| [578](../models/sale_order_inherit.py#L578) | `action_confirm` | 7 | B | 21 | 1 |
| [610](../models/sale_order_inherit.py#L610) | `_cotizador_print` | 1 | A | 4 | 2 |
| [622](../models/sale_order_inherit.py#L622) | `print_quotation` | 2 | A | 2 | 1 |
| [631](../models/sale_order_inherit.py#L631) | `_cotizador_price_date` | 2 | A | 2 | 1 |
| [638](../models/sale_order_inherit.py#L638) | `_cotizador_machine_price` | 1 | A | 6 | 2 |
| [650](../models/sale_order_inherit.py#L650) | `_cotizador_accessory_price` | 1 | A | 6 | 2 |
| [663](../models/sale_order_inherit.py#L663) | `_cotizador_add_configuration` | 18 | C | 47 | 3 |
| [739](../models/sale_order_inherit.py#L739) | `action_open_config_wizard` | 3 | A | 14 | 1 |
| [758](../models/sale_order_inherit.py#L758) | `action_open_plan_pago_wizard` | 2 | A | 25 | 1 |
| [788](../models/sale_order_inherit.py#L788) | `action_open_equipo_usado_wizard` | 5 | A | 12 | 1 |
| [806](../models/sale_order_inherit.py#L806) | `action_open_descuento_wizard` | 5 | A | 12 | 1 |
| [824](../models/sale_order_inherit.py#L824) | `action_open_discount_wizard` | 1 | A | 2 | 1 |
| [871](../models/sale_order_inherit.py#L871) | `_is_cotizador_product_line` | 4 | A | 3 | 1 |
| [879](../models/sale_order_inherit.py#L879) | `_compute_price_unit` | 3 | A | 3 | 1 |
| [888](../models/sale_order_inherit.py#L888) | `_get_product_price_context` | 3 | A | 5 | 1 |
| [902](../models/sale_order_inherit.py#L902) | `create` | 2 | A | 5 | 2 |
| [913](../models/sale_order_inherit.py#L913) | `write` | 3 | A | 5 | 2 |
| [924](../models/sale_order_inherit.py#L924) | `unlink` | 2 | A | 6 | 1 |
| [935](../models/sale_order_inherit.py#L935) | `_get_parent_order` | 7 | B | 14 | 1 |
| [955](../models/sale_order_inherit.py#L955) | `action_open_config_wizard` | 1 | A | 2 | 1 |
| [962](../models/sale_order_inherit.py#L962) | `action_open_equipo_usado_wizard` | 1 | A | 2 | 1 |
| [969](../models/sale_order_inherit.py#L969) | `action_open_descuento_wizard` | 1 | A | 2 | 1 |
| [976](../models/sale_order_inherit.py#L976) | `action_open_discount_wizard` | 1 | A | 2 | 1 |

</details>

<details><summary><code>models/sembradora_accessory_rule.py</code> — 1 funciones, CCN máxima 2</summary>

| Línea | Función | CCN | Rango | Líneas de código | Parámetros |
|--:|---|--:|:-:|--:|--:|
| [47](../models/sembradora_accessory_rule.py#L47) | `_compute_display_name` | 2 | A | 4 | 1 |

</details>

<details><summary><code>models/sembradora_config.py</code> — 18 funciones, CCN máxima 20</summary>

| Línea | Función | CCN | Rango | Líneas de código | Parámetros |
|--:|---|--:|:-:|--:|--:|
| [12](../models/sembradora_config.py#L12) | `validate_rule_set` | 20 | C | 33 | 1 |
| [109](../models/sembradora_config.py#L109) | `_compute_description` | 6 | B | 10 | 1 |
| [125](../models/sembradora_config.py#L125) | `_compute_name` | 2 | A | 4 | 1 |
| [132](../models/sembradora_config.py#L132) | `create` | 1 | A | 5 | 2 |
| [143](../models/sembradora_config.py#L143) | `write` | 3 | A | 8 | 2 |
| [158](../models/sembradora_config.py#L158) | `unlink` | 1 | A | 6 | 1 |
| [171](../models/sembradora_config.py#L171) | `_check_complete_combination` | 5 | A | 11 | 1 |
| [191](../models/sembradora_config.py#L191) | `_check_unique_combination` | 4 | A | 10 | 1 |
| [207](../models/sembradora_config.py#L207) | `_check_accessories_modelo` | 1 | A | 2 | 1 |
| [215](../models/sembradora_config.py#L215) | `_check_accessories` | 7 | B | 13 | 1 |
| [234](../models/sembradora_config.py#L234) | `_rule_set_lines` | 3 | A | 8 | 1 |
| [251](../models/sembradora_config.py#L251) | `_get_accessory_offer` | 8 | B | 36 | 1 |
| [308](../models/sembradora_config.py#L308) | `_get_default_accessory_lines` | 1 | A | 3 | 1 |
| [318](../models/sembradora_config.py#L318) | `_check_accessory_selection` | 9 | B | 28 | 2 |
| [357](../models/sembradora_config.py#L357) | `_get_variant` | 3 | A | 15 | 1 |
| [370](../models/sembradora_config.py#L370) | `_get_variant.find` | 1 | A | 6 | 0 |
| [390](../models/sembradora_config.py#L390) | `_sync_variant_code` | 3 | A | 9 | 1 |
| [401](../models/sembradora_config.py#L401) | `_get_variant_description` | 4 | A | 12 | 1 |

</details>

<details><summary><code>models/sembradora_config_acc_line.py</code> — 1 funciones, CCN máxima 4</summary>

| Línea | Función | CCN | Rango | Líneas de código | Parámetros |
|--:|---|--:|:-:|--:|--:|
| [57](../models/sembradora_config_acc_line.py#L57) | `_check_product_modelo` | 4 | A | 9 | 1 |

</details>

<details><summary><code>models/sembradora_import_wizard.py</code> — 26 funciones, CCN máxima 42</summary>

| Línea | Función | CCN | Rango | Líneas de código | Parámetros |
|--:|---|--:|:-:|--:|--:|
| [63](../models/sembradora_import_wizard.py#L63) | `_strip_accents` | 3 | A | 2 | 1 |
| [72](../models/sembradora_import_wizard.py#L72) | `slugify` | 1 | A | 2 | 1 |
| [81](../models/sembradora_import_wizard.py#L81) | `first_number` | 3 | A | 3 | 1 |
| [91](../models/sembradora_import_wizard.py#L91) | `price_currency_codes` | 2 | A | 2 | 1 |
| [100](../models/sembradora_import_wizard.py#L100) | `parse_price` | 9 | B | 17 | 1 |
| [162](../models/sembradora_import_wizard.py#L162) | `_read_files` | 7 | B | 14 | 1 |
| [183](../models/sembradora_import_wizard.py#L183) | `_parse` | 42 | F | 104 | 2 |
| [306](../models/sembradora_import_wizard.py#L306) | `_check_price_currency` | 3 | A | 6 | 4 |
| [320](../models/sembradora_import_wizard.py#L320) | `_validate_parsed` | 26 | D | 45 | 2 |
| [364](../models/sembradora_import_wizard.py#L364) | `_validate_parsed.check_slugs` | 3 | A | 7 | 2 |
| [392](../models/sembradora_import_wizard.py#L392) | `_xmlid_name` | 2 | A | 2 | 3 |
| [401](../models/sembradora_import_wizard.py#L401) | `_find` | 3 | A | 3 | 3 |
| [411](../models/sembradora_import_wizard.py#L411) | `_find_or_create` | 2 | A | 7 | 6 |
| [428](../models/sembradora_import_wizard.py#L428) | `_register_xmlid` | 2 | A | 8 | 4 |
| [452](../models/sembradora_import_wizard.py#L452) | `action_analyze` | 1 | A | 11 | 1 |
| [469](../models/sembradora_import_wizard.py#L469) | `action_back_to_upload` | 1 | A | 3 | 1 |
| [477](../models/sembradora_import_wizard.py#L477) | `_reopen` | 1 | A | 8 | 1 |
| [490](../models/sembradora_import_wizard.py#L490) | `_build_analysis_html` | 16 | C | 36 | 3 |
| [508](../models/sembradora_import_wizard.py#L508) | `_build_analysis_html.existing` | 3 | A | 3 | 4 |
| [550](../models/sembradora_import_wizard.py#L550) | `action_import` | 4 | A | 34 | 1 |
| [600](../models/sembradora_import_wizard.py#L600) | `_import_attributes` | 7 | B | 21 | 3 |
| [628](../models/sembradora_import_wizard.py#L628) | `_import_qty_categories` | 5 | A | 12 | 4 |
| [648](../models/sembradora_import_wizard.py#L648) | `_import_models` | 8 | B | 23 | 4 |
| [681](../models/sembradora_import_wizard.py#L681) | `_import_accessories` | 5 | A | 17 | 5 |
| [710](../models/sembradora_import_wizard.py#L710) | `_import_rules` | 4 | A | 12 | 3 |
| [731](../models/sembradora_import_wizard.py#L731) | `_import_configs` | 10 | B | 27 | 7 |

</details>

<details><summary><code>scripts/split_csv.py</code> — 2 funciones, CCN máxima 11</summary>

| Línea | Función | CCN | Rango | Líneas de código | Parámetros |
|--:|---|--:|:-:|--:|--:|
| [18](../scripts/split_csv.py#L18) | `split_sembradora_csv` | 11 | C | 37 | 3 |
| [66](../scripts/split_csv.py#L66) | `_write_chunk` | 3 | A | 11 | 5 |

</details>

<details><summary><code>scripts/split_csv_gui.py</code> — 11 funciones, CCN máxima 12</summary>

| Línea | Función | CCN | Rango | Líneas de código | Parámetros |
|--:|---|--:|:-:|--:|--:|
| [42](../scripts/split_csv_gui.py#L42) | `__init__` | 1 | A | 5 | 4 |
| [48](../scripts/split_csv_gui.py#L48) | `run` | 12 | C | 43 | 1 |
| [103](../scripts/split_csv_gui.py#L103) | `_write_chunk` | 3 | A | 11 | 5 |
| [117](../scripts/split_csv_gui.py#L117) | `__init__` | 1 | A | 5 | 1 |
| [123](../scripts/split_csv_gui.py#L123) | `init_ui` | 1 | A | 63 | 1 |
| [203](../scripts/split_csv_gui.py#L203) | `browse_file` | 3 | A | 7 | 1 |
| [211](../scripts/split_csv_gui.py#L211) | `browse_output` | 2 | A | 4 | 1 |
| [216](../scripts/split_csv_gui.py#L216) | `log` | 1 | A | 2 | 2 |
| [219](../scripts/split_csv_gui.py#L219) | `run_split` | 3 | A | 17 | 1 |
| [242](../scripts/split_csv_gui.py#L242) | `on_finished` | 2 | A | 8 | 3 |
| [252](../scripts/split_csv_gui.py#L252) | `main` | 1 | A | 5 | 0 |

</details>

<details><summary><code>static/src/components/configurador/configurador.js</code> — 60 funciones, CCN máxima 22</summary>

| Línea | Función | CCN | Rango | Líneas de código | Parámetros |
|--:|---|--:|:-:|--:|--:|
| [39](../static/src/components/configurador/configurador.js#L39) | `setup` | 10 | B | 43 | 0 |
| [93](../static/src/components/configurador/configurador.js#L93) | `(anónima)` | 1 | A | 3 | 0 |
| [97](../static/src/components/configurador/configurador.js#L97) | `(anónima)` | 1 | A | 5 | 0 |
| [99](../static/src/components/configurador/configurador.js#L99) | `this._handleResize` | 1 | A | 1 | 0 |
| [103](../static/src/components/configurador/configurador.js#L103) | `(anónima)` | 1 | A | 3 | 0 |
| [107](../static/src/components/configurador/configurador.js#L107) | `(anónima)` | 2 | A | 5 | 0 |
| [118](../static/src/components/configurador/configurador.js#L118) | `updateTextScroll` | 3 | A | 4 | 0 |
| [120](../static/src/components/configurador/configurador.js#L120) | `(anónima)` | 6 | B | 15 | 0 |
| [138](../static/src/components/configurador/configurador.js#L138) | `toggleMobileSummary` | 2 | A | 6 | 0 |
| [146](../static/src/components/configurador/configurador.js#L146) | `closeMobileSummary` | 1 | A | 3 | 0 |
| [157](../static/src/components/configurador/configurador.js#L157) | `loadInitialData` | 7 | B | 32 | 0 |
| [199](../static/src/components/configurador/configurador.js#L199) | `formatCurrency` | 5 | A | 11 | 1 |
| [217](../static/src/components/configurador/configurador.js#L217) | `get filteredModels` | 3 | A | 8 | 0 |
| [222](../static/src/components/configurador/configurador.js#L222) | `(anónima)` | 3 | A | 2 | 1 |
| [234](../static/src/components/configurador/configurador.js#L234) | `selectModel` | 5 | A | 33 | 1 |
| [273](../static/src/components/configurador/configurador.js#L273) | `goToModelSelection` | 1 | A | 3 | 0 |
| [278](../static/src/components/configurador/configurador.js#L278) | `goToAttributes` | 2 | A | 5 | 0 |
| [285](../static/src/components/configurador/configurador.js#L285) | `goToAccessories` | 3 | A | 5 | 0 |
| [300](../static/src/components/configurador/configurador.js#L300) | `getAvailableValuesForAttribute` | 6 | B | 23 | 1 |
| [309](../static/src/components/configurador/configurador.js#L309) | `(anónima)` | 1 | A | 1 | 1 |
| [320](../static/src/components/configurador/configurador.js#L320) | `(anónima)` | 2 | A | 13 | 1 |
| [325](../static/src/components/configurador/configurador.js#L325) | `(anónima)` | 1 | A | 1 | 1 |
| [338](../static/src/components/configurador/configurador.js#L338) | `(anónima)` | 1 | A | 1 | 2 |
| [348](../static/src/components/configurador/configurador.js#L348) | `get activeTreeIndex` | 2 | A | 4 | 0 |
| [349](../static/src/components/configurador/configurador.js#L349) | `(anónima)` | 1 | A | 1 | 1 |
| [358](../static/src/components/configurador/configurador.js#L358) | `getSelectedValueName` | 4 | A | 8 | 1 |
| [361](../static/src/components/configurador/configurador.js#L361) | `(anónima)` | 1 | A | 1 | 1 |
| [363](../static/src/components/configurador/configurador.js#L363) | `(anónima)` | 1 | A | 1 | 1 |
| [371](../static/src/components/configurador/configurador.js#L371) | `editAttributeNode` | 2 | A | 6 | 1 |
| [384](../static/src/components/configurador/configurador.js#L384) | `selectAttributeValue` | 4 | A | 13 | 2 |
| [385](../static/src/components/configurador/configurador.js#L385) | `(anónima)` | 1 | A | 1 | 1 |
| [407](../static/src/components/configurador/configurador.js#L407) | `_evaluateSequentialAttributes` | 9 | B | 44 | 0 |
| [416](../static/src/components/configurador/configurador.js#L416) | `(anónima)` | 1 | A | 1 | 1 |
| [431](../static/src/components/configurador/configurador.js#L431) | `(anónima)` | 1 | A | 1 | 1 |
| [435](../static/src/components/configurador/configurador.js#L435) | `(anónima)` | 1 | A | 1 | 1 |
| [468](../static/src/components/configurador/configurador.js#L468) | `loadAccessories` | 9 | B | 34 | 1 |
| [483](../static/src/components/configurador/configurador.js#L483) | `(anónima)` | 1 | A | 1 | 1 |
| [511](../static/src/components/configurador/configurador.js#L511) | `get choiceGroups` | 5 | A | 14 | 0 |
| [521](../static/src/components/configurador/configurador.js#L521) | `(anónima)` | 1 | A | 1 | 2 |
| [531](../static/src/components/configurador/configurador.js#L531) | `formatDelta` | 3 | A | 4 | 1 |
| [540](../static/src/components/configurador/configurador.js#L540) | `selectChoice` | 3 | A | 9 | 1 |
| [555](../static/src/components/configurador/configurador.js#L555) | `get filteredAccessories` | 4 | A | 14 | 0 |
| [557](../static/src/components/configurador/configurador.js#L557) | `(anónima)` | 1 | A | 1 | 1 |
| [559](../static/src/components/configurador/configurador.js#L559) | `(anónima)` | 1 | A | 1 | 1 |
| [565](../static/src/components/configurador/configurador.js#L565) | `(anónima)` | 3 | A | 2 | 1 |
| [576](../static/src/components/configurador/configurador.js#L576) | `setActiveCategory` | 1 | A | 3 | 1 |
| [585](../static/src/components/configurador/configurador.js#L585) | `toggleAccessory` | 4 | A | 10 | 1 |
| [586](../static/src/components/configurador/configurador.js#L586) | `(anónima)` | 1 | A | 1 | 1 |
| [607](../static/src/components/configurador/configurador.js#L607) | `_evaluateAccessoryRules` | 22 | D | 61 | 0 |
| [652](../static/src/components/configurador/configurador.js#L652) | `(anónima)` | 1 | A | 1 | 1 |
| [676](../static/src/components/configurador/configurador.js#L676) | `_recalculateAccessoriesTotal` | 4 | A | 10 | 0 |
| [691](../static/src/components/configurador/configurador.js#L691) | `get selectedAccessoriesList` | 1 | A | 5 | 0 |
| [693](../static/src/components/configurador/configurador.js#L693) | `(anónima)` | 1 | A | 1 | 1 |
| [701](../static/src/components/configurador/configurador.js#L701) | `get selectedAttributesSummary` | 4 | A | 18 | 0 |
| [706](../static/src/components/configurador/configurador.js#L706) | `(anónima)` | 1 | A | 1 | 1 |
| [724](../static/src/components/configurador/configurador.js#L724) | `get activeDescription` | 3 | A | 6 | 0 |
| [732](../static/src/components/configurador/configurador.js#L732) | `toggleDescriptionCollapse` | 1 | A | 3 | 0 |
| [743](../static/src/components/configurador/configurador.js#L743) | `confirmConfiguration` | 5 | A | 38 | 0 |
| [762](../static/src/components/configurador/configurador.js#L762) | `(anónima)` | 1 | A | 1 | 1 |
| [789](../static/src/components/configurador/configurador.js#L789) | `closeAndReturn` | 2 | A | 13 | 0 |

</details>

<details><summary><code>static/src/js/cotizador_quote_form.js</code> — 2 funciones, CCN máxima 1</summary>

| Línea | Función | CCN | Rango | Líneas de código | Parámetros |
|--:|---|--:|:-:|--:|--:|
| [23](../static/src/js/cotizador_quote_form.js#L23) | `willStart` | 1 | A | 3 | 0 |
| [28](../static/src/js/cotizador_quote_form.js#L28) | `start` | 1 | A | 3 | 0 |

</details>

<details><summary><code>static/src/js/cotizador_sequential_configurator.js</code> — 24 funciones, CCN máxima 43</summary>

| Línea | Función | CCN | Rango | Líneas de código | Parámetros |
|--:|---|--:|:-:|--:|--:|
| [25](../static/src/js/cotizador_sequential_configurator.js#L25) | `escapeHtml` | 3 | A | 9 | 1 |
| [45](../static/src/js/cotizador_sequential_configurator.js#L45) | `setup` | 15 | C | 51 | 0 |
| [100](../static/src/js/cotizador_sequential_configurator.js#L100) | `(anónima)` | 1 | A | 4 | 1 |
| [107](../static/src/js/cotizador_sequential_configurator.js#L107) | `(anónima)` | 2 | A | 6 | 1 |
| [125](../static/src/js/cotizador_sequential_configurator.js#L125) | `formatOptionName` | 12 | C | 18 | 2 |
| [150](../static/src/js/cotizador_sequential_configurator.js#L150) | `formatMoney` | 2 | A | 6 | 1 |
| [162](../static/src/js/cotizador_sequential_configurator.js#L162) | `getMatchingConfigs` | 2 | A | 7 | 1 |
| [167](../static/src/js/cotizador_sequential_configurator.js#L167) | `(anónima)` | 1 | A | 4 | 1 |
| [169](../static/src/js/cotizador_sequential_configurator.js#L169) | `(anónima)` | 1 | A | 1 | 1 |
| [180](../static/src/js/cotizador_sequential_configurator.js#L180) | `selectValue` | 2 | A | 12 | 4 |
| [199](../static/src/js/cotizador_sequential_configurator.js#L199) | `goToStep` | 2 | A | 10 | 1 |
| [211](../static/src/js/cotizador_sequential_configurator.js#L211) | `resetConfig` | 1 | A | 8 | 0 |
| [224](../static/src/js/cotizador_sequential_configurator.js#L224) | `render` | 43 | F | 182 | 0 |
| [284](../static/src/js/cotizador_sequential_configurator.js#L284) | `(anónima)` | 1 | A | 3 | 1 |
| [285](../static/src/js/cotizador_sequential_configurator.js#L285) | `(anónima)` | 1 | A | 4 | 0 |
| [356](../static/src/js/cotizador_sequential_configurator.js#L356) | `(anónima)` | 2 | A | 6 | 1 |
| [390](../static/src/js/cotizador_sequential_configurator.js#L390) | `(anónima)` | 1 | A | 3 | 1 |
| [391](../static/src/js/cotizador_sequential_configurator.js#L391) | `(anónima)` | 1 | A | 1 | 1 |
| [393](../static/src/js/cotizador_sequential_configurator.js#L393) | `(anónima)` | 1 | A | 1 | 1 |
| [396](../static/src/js/cotizador_sequential_configurator.js#L396) | `(anónima)` | 4 | A | 30 | 1 |
| [403](../static/src/js/cotizador_sequential_configurator.js#L403) | `(anónima)` | 1 | A | 1 | 1 |
| [404](../static/src/js/cotizador_sequential_configurator.js#L404) | `(anónima)` | 3 | A | 1 | 1 |
| [445](../static/src/js/cotizador_sequential_configurator.js#L445) | `(anónima)` | 1 | A | 3 | 1 |
| [446](../static/src/js/cotizador_sequential_configurator.js#L446) | `(anónima)` | 1 | A | 7 | 1 |

</details>

<details><summary><code>static/tests/tours/cotizador_tours.js</code> — 2 funciones, CCN máxima 1</summary>

| Línea | Función | CCN | Rango | Líneas de código | Parámetros |
|--:|---|--:|:-:|--:|--:|
| [16](../static/tests/tours/cotizador_tours.js#L16) | `steps` | 1 | A | 14 | 0 |
| [35](../static/tests/tours/cotizador_tours.js#L35) | `steps` | 1 | A | 10 | 0 |

</details>

<details><summary><code>tests/common.py</code> — 8 funciones, CCN máxima 2</summary>

| Línea | Función | CCN | Rango | Líneas de código | Parámetros |
|--:|---|--:|:-:|--:|--:|
| [22](../tests/common.py#L22) | `analyze_matrix` | 2 | A | 8 | 3 |
| [32](../tests/common.py#L32) | `import_matrix` | 1 | A | 5 | 3 |
| [42](../tests/common.py#L42) | `setUpClass` | 1 | A | 6 | 1 |
| [50](../tests/common.py#L50) | `_wizard` | 1 | A | 2 | 3 |
| [54](../tests/common.py#L54) | `_import` | 1 | A | 2 | 3 |
| [58](../tests/common.py#L58) | `_imported` | 1 | A | 2 | 2 |
| [61](../tests/common.py#L61) | `_order` | 1 | A | 2 | 2 |
| [64](../tests/common.py#L64) | `_lines` | 2 | A | 2 | 2 |

</details>

<details><summary><code>tests/test_cascade_variants.py</code> — 11 funciones, CCN máxima 2</summary>

| Línea | Función | CCN | Rango | Líneas de código | Parámetros |
|--:|---|--:|:-:|--:|--:|
| [17](../tests/test_cascade_variants.py#L17) | `setUpClass` | 1 | A | 6 | 1 |
| [25](../tests/test_cascade_variants.py#L25) | `_quote` | 2 | A | 5 | 2 |
| [33](../tests/test_cascade_variants.py#L33) | `_discount` | 1 | A | 3 | 3 |
| [40](../tests/test_cascade_variants.py#L40) | `test_discount_applies_to_net_and_vat_after` | 1 | A | 10 | 1 |
| [52](../tests/test_cascade_variants.py#L52) | `test_percentage_discounts_cascade_and_follow_the_lines` | 1 | A | 8 | 1 |
| [63](../tests/test_cascade_variants.py#L63) | `test_payment_plan_follows_the_lines_and_simulation_matches` | 2 | A | 14 | 1 |
| [79](../tests/test_cascade_variants.py#L79) | `test_update_prices_keeps_special_lines` | 1 | A | 7 | 1 |
| [88](../tests/test_cascade_variants.py#L88) | `test_accessory_keeps_matrix_price_when_quantity_changes` | 1 | A | 7 | 1 |
| [102](../tests/test_cascade_variants.py#L102) | `test_one_variant_per_configuration` | 2 | A | 16 | 1 |
| [121](../tests/test_cascade_variants.py#L121) | `test_incomplete_combination_is_an_error` | 1 | A | 5 | 1 |
| [128](../tests/test_cascade_variants.py#L128) | `test_teamcenter_id_is_confirmed_by_attributes` | 1 | A | 14 | 1 |

</details>

<details><summary><code>tests/test_configurator.py</code> — 12 funciones, CCN máxima 5</summary>

| Línea | Función | CCN | Rango | Líneas de código | Parámetros |
|--:|---|--:|:-:|--:|--:|
| [12](../tests/test_configurator.py#L12) | `setUpClass` | 1 | A | 5 | 1 |
| [18](../tests/test_configurator.py#L18) | `test_offer_and_defaults` | 3 | A | 12 | 1 |
| [32](../tests/test_configurator.py#L32) | `test_confirm_sections_and_choice_rules` | 5 | A | 24 | 1 |
| [60](../tests/test_configurator.py#L60) | `test_pricelist_applies_to_machine_and_accessories` | 5 | A | 13 | 1 |
| [77](../tests/test_configurator.py#L77) | `test_price_cache_invalidated_on_write` | 1 | A | 5 | 1 |
| [83](../tests/test_configurator.py#L83) | `test_product_currency_and_tax_setting` | 3 | A | 13 | 1 |
| [98](../tests/test_configurator.py#L98) | `test_quotation_pricelist_applied_when_configuring` | 3 | A | 19 | 1 |
| [123](../tests/test_configurator.py#L123) | `test_subtotal_consistent_with_line_discount` | 1 | A | 5 | 1 |
| [129](../tests/test_configurator.py#L129) | `test_rule_constraint_on_manual_edit` | 1 | A | 8 | 1 |
| [139](../tests/test_configurator.py#L139) | `test_permissions` | 1 | A | 14 | 1 |
| [154](../tests/test_configurator.py#L154) | `test_lead_create_quotation` | 1 | A | 9 | 1 |
| [164](../tests/test_configurator.py#L164) | `test_payment_plan_does_not_touch_product_price` | 1 | A | 11 | 1 |

</details>

<details><summary><code>tests/test_documentacion.py</code> — 2 funciones, CCN máxima 1</summary>

| Línea | Función | CCN | Rango | Líneas de código | Parámetros |
|--:|---|--:|:-:|--:|--:|
| [12](../tests/test_documentacion.py#L12) | `test_codigo_documentado` | 1 | A | 3 | 1 |
| [17](../tests/test_documentacion.py#L17) | `test_referencia_actualizada` | 1 | A | 4 | 1 |

</details>

<details><summary><code>tests/test_importer.py</code> — 11 funciones, CCN máxima 3</summary>

| Línea | Función | CCN | Rango | Líneas de código | Parámetros |
|--:|---|--:|:-:|--:|--:|
| [22](../tests/test_importer.py#L22) | `assertAnalysisError` | 1 | A | 6 | 4 |
| [29](../tests/test_importer.py#L29) | `test_parse_price` | 2 | A | 7 | 1 |
| [37](../tests/test_importer.py#L37) | `test_import_end_to_end` | 3 | A | 19 | 1 |
| [62](../tests/test_importer.py#L62) | `test_accessories_are_unique_per_model` | 1 | A | 12 | 1 |
| [77](../tests/test_importer.py#L77) | `test_price_currency_must_match` | 1 | A | 4 | 1 |
| [82](../tests/test_importer.py#L82) | `test_reimport_uses_xmlids_not_names` | 3 | A | 15 | 1 |
| [100](../tests/test_importer.py#L100) | `test_format_errors` | 1 | A | 11 | 1 |
| [112](../tests/test_importer.py#L112) | `test_rule_coherence_errors` | 1 | A | 13 | 1 |
| [130](../tests/test_importer.py#L130) | `test_manual_rule_with_same_name_blocks_import` | 1 | A | 5 | 1 |
| [136](../tests/test_importer.py#L136) | `test_orphan_identifier_is_reused` | 1 | A | 14 | 1 |
| [153](../tests/test_importer.py#L153) | `test_reimport_replaces_lines_with_accessories_of_another_criterion` | 1 | A | 14 | 1 |

</details>

<details><summary><code>tests/test_public_quote.py</code> — 11 funciones, CCN máxima 2</summary>

| Línea | Función | CCN | Rango | Líneas de código | Parámetros |
|--:|---|--:|:-:|--:|--:|
| [17](../tests/test_public_quote.py#L17) | `setUpClass` | 1 | A | 9 | 1 |
| [27](../tests/test_public_quote.py#L27) | `setUp` | 1 | A | 3 | 1 |
| [31](../tests/test_public_quote.py#L31) | `_token` | 1 | A | 3 | 2 |
| [35](../tests/test_public_quote.py#L35) | `_post` | 1 | A | 11 | 2 |
| [47](../tests/test_public_quote.py#L47) | `test_anonymous_request_creates_only_a_lead` | 1 | A | 16 | 1 |
| [67](../tests/test_public_quote.py#L67) | `test_form_token_required` | 2 | A | 5 | 1 |
| [73](../tests/test_public_quote.py#L73) | `test_machine_requires_its_configuration` | 2 | A | 4 | 1 |
| [78](../tests/test_public_quote.py#L78) | `test_logged_in_customer_gets_quotation` | 1 | A | 8 | 1 |
| [87](../tests/test_public_quote.py#L87) | `test_quote_only_blocks_checkout` | 2 | A | 6 | 1 |
| [94](../tests/test_public_quote.py#L94) | `test_thank_you_page` | 1 | A | 4 | 1 |
| [99](../tests/test_public_quote.py#L99) | `test_quote_only_mode_blocks_payment` | 2 | A | 11 | 1 |

</details>

<details><summary><code>tests/test_review_fixes.py</code> — 11 funciones, CCN máxima 2</summary>

| Línea | Función | CCN | Rango | Líneas de código | Parámetros |
|--:|---|--:|:-:|--:|--:|
| [18](../tests/test_review_fixes.py#L18) | `__init__` | 1 | A | 2 | 2 |
| [22](../tests/test_review_fixes.py#L22) | `read` | 1 | A | 2 | 1 |
| [26](../tests/test_review_fixes.py#L26) | `__enter__` | 1 | A | 2 | 1 |
| [30](../tests/test_review_fixes.py#L30) | `__exit__` | 1 | A | 2 | 2 |
| [39](../tests/test_review_fixes.py#L39) | `test_api_error_is_never_no_debt` | 2 | A | 7 | 1 |
| [48](../tests/test_review_fixes.py#L48) | `test_404_means_no_records` | 1 | A | 6 | 1 |
| [56](../tests/test_review_fixes.py#L56) | `test_debts_are_parsed_in_pesos` | 1 | A | 18 | 1 |
| [82](../tests/test_review_fixes.py#L82) | `setUpClass` | 1 | A | 5 | 1 |
| [89](../tests/test_review_fixes.py#L89) | `test_expected_revenue_in_company_currency` | 1 | A | 17 | 1 |
| [109](../tests/test_review_fixes.py#L109) | `test_engineering_codes_are_applied_with_parameters` | 1 | A | 8 | 1 |
| [119](../tests/test_review_fixes.py#L119) | `test_missing_qty_attribute_is_a_clear_error` | 1 | A | 6 | 1 |

</details>

<details><summary><code>tests/test_teamcenter.py</code> — 19 funciones, CCN máxima 5</summary>

| Línea | Función | CCN | Rango | Líneas de código | Parámetros |
|--:|---|--:|:-:|--:|--:|
| [25](../tests/test_teamcenter.py#L25) | `setUpClass` | 1 | A | 6 | 1 |
| [33](../tests/test_teamcenter.py#L33) | `_wizard` | 1 | A | 2 | 2 |
| [38](../tests/test_teamcenter.py#L38) | `_template_rows` | 5 | A | 6 | 2 |
| [50](../tests/test_teamcenter.py#L50) | `_fill_codes` | 2 | A | 8 | 3 |
| [65](../tests/test_teamcenter.py#L65) | `_upload` | 3 | A | 13 | 4 |
| [85](../tests/test_teamcenter.py#L85) | `_expected_rows` | 3 | A | 5 | 1 |
| [92](../tests/test_teamcenter.py#L92) | `test_excel_template_has_one_row_per_variant` | 1 | A | 8 | 1 |
| [102](../tests/test_teamcenter.py#L102) | `test_csv_template_without_openpyxl` | 1 | A | 9 | 1 |
| [113](../tests/test_teamcenter.py#L113) | `test_template_shows_current_code` | 2 | A | 7 | 1 |
| [122](../tests/test_teamcenter.py#L122) | `test_template_columns_follow_attribute_order` | 1 | A | 6 | 1 |
| [130](../tests/test_teamcenter.py#L130) | `test_model_without_attributes_is_an_error` | 1 | A | 7 | 1 |
| [139](../tests/test_teamcenter.py#L139) | `_round_trip` | 2 | A | 18 | 2 |
| [162](../tests/test_teamcenter.py#L162) | `test_round_trip_excel` | 1 | A | 2 | 1 |
| [166](../tests/test_teamcenter.py#L166) | `test_round_trip_csv` | 1 | A | 2 | 1 |
| [170](../tests/test_teamcenter.py#L170) | `test_regenerated_template_shows_applied_codes` | 2 | A | 6 | 1 |
| [178](../tests/test_teamcenter.py#L178) | `test_partial_file_and_unknown_rows` | 1 | A | 13 | 1 |
| [193](../tests/test_teamcenter.py#L193) | `test_id_of_another_variant_is_not_trusted` | 1 | A | 9 | 1 |
| [204](../tests/test_teamcenter.py#L204) | `test_back_to_upload_discards_simulation` | 2 | A | 10 | 1 |
| [216](../tests/test_teamcenter.py#L216) | `test_file_without_code_column_is_an_error` | 1 | A | 5 | 1 |

</details>

<details><summary><code>tests/test_tours.py</code> — 3 funciones, CCN máxima 1</summary>

| Línea | Función | CCN | Rango | Líneas de código | Parámetros |
|--:|---|--:|:-:|--:|--:|
| [10](../tests/test_tours.py#L10) | `setUpClass` | 1 | A | 5 | 1 |
| [16](../tests/test_tours.py#L16) | `test_configurator_tour` | 1 | A | 5 | 1 |
| [22](../tests/test_tours.py#L22) | `test_website_quote_tour` | 1 | A | 5 | 1 |

</details>

<details><summary><code>tools/complejidad.py</code> — 11 funciones, CCN máxima 8</summary>

| Línea | Función | CCN | Rango | Líneas de código | Parámetros |
|--:|---|--:|:-:|--:|--:|
| [46](../tools/complejidad.py#L46) | `rango` | 4 | A | 5 | 1 |
| [58](../tools/complejidad.py#L58) | `analizar` | 8 | B | 25 | 0 |
| [91](../tools/complejidad.py#L91) | `_enlace` | 1 | A | 2 | 1 |
| [100](../tools/complejidad.py#L100) | `_resumen` | 7 | B | 10 | 1 |
| [118](../tools/complejidad.py#L118) | `_tabla_areas` | 8 | B | 12 | 1 |
| [137](../tools/complejidad.py#L137) | `_tabla_atencion` | 4 | A | 9 | 1 |
| [153](../tools/complejidad.py#L153) | `_por_archivo` | 2 | A | 5 | 1 |
| [165](../tools/complejidad.py#L165) | `_tabla_archivos` | 2 | A | 9 | 1 |
| [181](../tools/complejidad.py#L181) | `_tabla_funciones` | 3 | A | 13 | 1 |
| [201](../tools/complejidad.py#L201) | `generar` | 2 | A | 3 | 1 |
| [211](../tools/complejidad.py#L211) | `escribir` | 3 | A | 7 | 0 |

</details>

<details><summary><code>tools/documentacion.py</code> — 21 funciones, CCN máxima 25</summary>

| Línea | Función | CCN | Rango | Líneas de código | Parámetros |
|--:|---|--:|:-:|--:|--:|
| [48](../tools/documentacion.py#L48) | `_archivos` | 5 | A | 6 | 2 |
| [62](../tools/documentacion.py#L62) | `_devuelve_valor` | 7 | B | 11 | 1 |
| [80](../tools/documentacion.py#L80) | `_faltantes_funcion_py` | 10 | B | 14 | 2 |
| [102](../tools/documentacion.py#L102) | `faltantes_python` | 9 | B | 16 | 0 |
| [136](../tools/documentacion.py#L136) | `_nombres_parametros_js` | 3 | A | 7 | 1 |
| [150](../tools/documentacion.py#L150) | `faltantes_js` | 25 | D | 31 | 0 |
| [190](../tools/documentacion.py#L190) | `faltantes` | 1 | A | 2 | 0 |
| [202](../tools/documentacion.py#L202) | `generar` | 10 | B | 33 | 1 |
| [242](../tools/documentacion.py#L242) | `escribir` | 1 | A | 3 | 1 |
| [252](../tools/documentacion.py#L252) | `_celda` | 2 | A | 2 | 1 |
| [261](../tools/documentacion.py#L261) | `_campos_propios` | 4 | A | 3 | 1 |
| [271](../tools/documentacion.py#L271) | `_diagrama` | 7 | B | 14 | 1 |
| [277](../tools/documentacion.py#L277) | `_diagrama.nodo` | 1 | A | 2 | 1 |
| [299](../tools/documentacion.py#L299) | `_detalle` | 13 | C | 18 | 1 |
| [324](../tools/documentacion.py#L324) | `_tabla_campos` | 5 | A | 7 | 1 |
| [338](../tools/documentacion.py#L338) | `_metodos_publicos` | 8 | B | 9 | 1 |
| [354](../tools/documentacion.py#L354) | `_llamadores` | 9 | B | 15 | 1 |
| [376](../tools/documentacion.py#L376) | `_llamadas_codigo` | 4 | A | 5 | 1 |
| [389](../tools/documentacion.py#L389) | `_puntos_de_entrada` | 4 | A | 8 | 2 |
| [405](../tools/documentacion.py#L405) | `_matriz_acceso` | 6 | B | 9 | 1 |
| [421](../tools/documentacion.py#L421) | `_parametros` | 4 | A | 9 | 1 |

</details>

<details><summary><code>tools/mkdocs_hooks.py</code> — 2 funciones, CCN máxima 3</summary>

| Línea | Función | CCN | Rango | Líneas de código | Parámetros |
|--:|---|--:|:-:|--:|--:|
| [13](../tools/mkdocs_hooks.py#L13) | `_rama` | 3 | A | 6 | 0 |
| [25](../tools/mkdocs_hooks.py#L25) | `on_page_markdown` | 2 | A | 3 | 4 |

</details>

<!-- complejidad:fin -->
