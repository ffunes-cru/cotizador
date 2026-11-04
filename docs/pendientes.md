# Pendientes y problemas conocidos

Lo que se sabe que falta o que requiere una decisión. Al resolver un punto, quitarlo de esta lista (y
agregar su test). Incluye lo que dejó abierto la revisión de código de octubre de 2026.

Gravedad: **alta** = puede dar un resultado equivocado sin aviso; **media** = error en un caso
plausible o regla del proyecto incumplida; **baja** = detalle o mejora.

## Errores conocidos

| # | Gravedad | Tema | Detalle | Propuesta |
|---|---|---|---|---|
| 1 | media | Nombres y valores escritos en el código | **Teamcenter**: al cruzar por valores de atributo traduce con una tabla fija (`alias_map`: `0.52` → `52.5`, `PRECISION` → `NEUMATICO`…) y busca la columna del código por palabras sueltas (`CODIGO`, `COD`). La tabla solo conoce los valores del archivo para el que se escribió: un valor nuevo o escrito distinto no cruza, y un alias equivocado cruza con la variante que no es. **Se mantiene** hasta que vuelva la plantilla ya enviada a Ingeniería. **Tienda**: el configurador agrega "cm" o "Líneas" según el nombre del atributo y muestra "PP" como "Precision Planting (PP)" (no depende de la plantilla). | Teamcenter, cuando vuelva la plantilla: cruzar solo por `ID_Odoo` confirmado y la columna exacta, sin tabla de alias. Tienda: mostrar el nombre del valor tal cual (corregir los nombres en Odoo si hace falta). |
| 2 | baja | Cantidad del valor de atributo | El importador toma la cantidad del número del valor. Si se renombra el valor en Odoo (`16 Líneas` → `18 Líneas`) hay que corregir a mano *Cantidad (Cotizador)* o volver a importar. | Avisar en el formulario del valor. |
| 3 | baja | Productos no publicados | Un POST armado a mano puede pedir cotización de un producto no publicado en la tienda. | Exigir `is_published` (y ajustar los tests). |
| 4 | baja | `scripts/split_csv.py` | Agrupa por `ID_Configuracion` solamente; como los ids se repiten entre modelos, junta configuraciones de máquinas distintas en el mismo grupo (las filas no se separan, así que el resultado sigue siendo importable). | Agrupar por `Modelo` + `ID_Configuracion`. |

## Rendimiento

| # | Gravedad | Tema | Detalle | Propuesta |
|---|---|---|---|---|
| 5 | media | Importaciones grandes | `_check_unique_combination` busca todas las configuraciones del modelo por cada configuración creada: crece con el cuadrado (miles de configuraciones por modelo se notan). | Comparar contra el índice `_cotizador_config_index` o una sola consulta por lote. |
| 6 | baja | Alerta BCRA al elegir cliente | Hace dos consultas HTTP en el formulario (hasta 8 s cada una) mientras el vendedor espera. | Consultar en segundo plano o solo con el botón. |

## Funcionalidad que falta

| # | Tema | Detalle |
|---|---|---|
| 7 | Accesorios en la tienda | La solicitud web incluye la máquina y su equipamiento estándar; los opcionales se agregan al armar la cotización desde el CRM. |

## Resueltos en noviembre de 2026

- Quitar combinaciones por CSV: el importador deja cada máquina del archivo igual al CSV (borra las
  configuraciones que faltan, archiva los accesorios, ajusta los valores de atributo y borra las reglas
  sin uso), muestra el detalle antes de importar y lo deja en el chatter de cada máquina
  (`tests/test_import_mirror.py`).

## Resueltos en la revisión de octubre de 2026

Para referencia (cada uno tiene su test en `tests/test_review_fixes.py`, `tests/test_cascade_variants.py`
o `tests/test_public_quote.py`):

- Cascada: los descuentos se calculaban sobre el total con IVA y sus líneas no llevaban impuestos. Ahora
  descuentos y plan de pago van sobre el neto (una línea por grupo de impuestos) y el IVA se calcula
  después.
- Plan de pago: su importe quedaba viejo al cambiar las líneas y no se veía en la cascada. Ahora se
  recalcula solo y tiene su renglón; la hoja de planes del PDF usa el mismo cálculo.
- *Actualizar precios* ponía en 0 descuentos, usados y planes; cambiar la cantidad de un accesorio lo
  llevaba al precio de venta del producto. Ahora la línea guarda su precio de matriz.
- Importador: un atributo borrado dejaba identificadores de sus valores sin registro y la importación
  siguiente fallaba con "duplicate key … ir_model_data_module_name_uniq_index"; re-importar sobre
  configuraciones con accesorios compartidos (versión anterior) fallaba con "pertenece al modelo
  'ninguno'".
- Variantes: se creaban al cotizar (atributos dinámicos), y una plantilla de Teamcenter podía mezclar ids
  de variantes y de configuraciones. Ahora hay una variante por configuración, creada con la matriz, y el
  `ID_Odoo` se confirma con los valores de atributo.

- BCRA: un error de la API se mostraba como "sin deudas"; la conexión no verificaba el certificado TLS.
- CRM: el ingreso esperado se copiaba en la moneda de la cotización sin convertir y desde cualquier
  cotización guardada (no la última).
- Modo "Solo cotización": el express checkout y la creación de la transacción de pago seguían abiertos.
- Teamcenter: los códigos se escribían con SQL armado como texto.
- Un accesorio por cantidad cuya categoría cambió de atributo rompía el configurador con un error interno.
- Código muerto: tres métodos de impresión sin uso (el menú *Imprimir* usa un reporte por modo), código
  comentado del asistente de planes y de sus vistas, y anotaciones `@odoo-module` innecesarias.
