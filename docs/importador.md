# Importador CSV de Configuraciones de Sembradora

Wizard `sembradora.import.wizard` (`models/sembradora_import_wizard.py`).
Carga la **matriz de ingeniería**: configuraciones válidas de cada máquina y su precio, accesorios
compatibles con su precio, reglas entre accesorios y equipamiento estándar.

Lee **CSV** con el formato de este documento (§2) y **planillas** (§11): archivos Excel (`.xlsx`) y,
con el módulo `cotizador_spreadsheet`, planillas de Odoo. Las planillas tienen el diseño de la
**planilla de configuraciones** (la que se trabaja a mano, §11.1), que el importador convierte a este CSV.

**Menú:** *Ventas › Configuración › Configurador Sembradoras › Importar Configuraciones*
**Permisos:** grupo *Configurador de Sembradoras / Administrador del Configurador*.

---

## 1. Flujo

1. **Cargar** uno o varios CSV o Excel (se procesan juntos, como un solo archivo), o elegir una
   **Planilla de Odoo** (§11.4), y la **Moneda de los Precios** (§6). De las planillas, marcar en
   **Hojas a importar** las hojas con las máquinas a cargar (§11).
2. **📊 Analizar**: valida **todo** el archivo y muestra:
   - la lista completa de **errores**, con archivo y línea (en una planilla, hoja, fila y columna).
     Si hay alguno, el botón *Importar* no aparece: corrija el archivo y use *Cargar otros archivos*;
   - si se leyó una planilla, la **Matriz leída (CSV)**: lo que se leyó, en el formato del CSV, para
     revisarlo (§11.3);
   - si no hay errores, **lo que va a cambiar** (§7.1): una tabla por máquina y, desplegable, el
     detalle de cada configuración nueva, modificada o que se borra, de cada accesorio nuevo,
     archivado o reactivado, y de los valores de atributo que se agregan o quitan. Si se va a borrar
     alguna configuración, lo avisa en rojo.
3. **📥 Importar**: vuelve a validar y escribe todo en una sola transacción (si algo falla no queda
   nada a medio importar). Al terminar muestra el mismo detalle como **cambios aplicados** y lo deja
   en el **chatter de cada máquina** que cambió: es el historial de importaciones.

El análisis no escribe nada. La importación usa exactamente los archivos analizados.

**Cada máquina del archivo queda igual al CSV** (§7.1). Las máquinas que no están en el archivo no se
tocan: se puede importar el CSV de una sola máquina sin afectar a las demás.

---

## 2. Columnas

Codificación UTF-8 (con o sin BOM; si falla, Latin-1). Separador coma; use comillas para valores con
coma (`"USD $248.866,00"`). Los nombres de columna distinguen mayúsculas.

| Columna | Obligatoria | Uso |
|---|---|---|
| `Modelo` | Sí | Nombre de la máquina. |
| `Tipo_Item` | Sí | `BASE`, `OPCIONAL` o `ESTANDAR` (§3). Se aceptan minúsculas y acentos (`Estándar`). |
| `Precio_Base` | En `BASE` | Precio de la máquina en esta configuración (§6). |
| `Nombre_Item` | En accesorios | Nombre del accesorio, propio del modelo (§7). |
| `Precio_Item` | En accesorios | Precio unitario del accesorio en **esta** configuración (§6). |
| `Calc_param` | No | Columna de atributo que define la **cantidad** del accesorio (§5). |
| `Reglas` | No | Reglas entre accesorios (§4). |
| `Descripcion` | No | En `BASE`: descripción de la configuración (si falta, se calcula con la *Descripción Paramétrica* del modelo). |
| `ATR_<Atributo>` | — | **Atributos de la máquina** (§2.1). |

**Cualquier otra columna es un error.** Así una columna mal escrita no se convierte en un atributo.

### 2.1 Columnas de atributos (`ATR_`)

- El nombre del atributo es lo que sigue a `ATR_`, con `_` reemplazado por espacio:
  `ATR_Cantidad_de_Lineas` → atributo **Cantidad de Lineas**.
- El orden de las columnas define el orden de los pasos del configurador.
- Los valores se leen de la fila `BASE`. Un modelo usa las columnas que tienen valor en alguna de sus
  configuraciones (otros modelos del mismo archivo pueden dejarlas vacías). En las filas de accesorio
  estas columnas se ignoran.
- Los atributos se crean en modo de variantes *Siempre*: cada configuración tiene su variante, creada al
  importar (ver [Conceptos de Odoo › Variantes](odoo.md#variantes)).
- **Cada configuración necesita un valor en cada columna `ATR_` que usa su modelo** (la variante necesita
  un valor por atributo). Una celda vacía en una columna que otras configuraciones del mismo modelo usan
  es un error.

---

## 3. Filas

Cada configuración es **una fila `BASE`** y, debajo, una fila por accesorio, con el mismo `Modelo`.
Un accesorio es de la fila `BASE` anterior.

| `Tipo_Item` | Significado |
|---|---|
| `BASE` | Atributos (`ATR_…`) y `Precio_Base` de la configuración. Exactamente una por configuración. |
| `OPCIONAL` | Accesorio compatible que el vendedor puede agregar. |
| `ESTANDAR` | Accesorio de **equipamiento estándar**: arranca **seleccionado**. |

Una configuración es su **combinación de atributos** dentro de su máquina (`Pionera` con `16 Lineas`
y `52 cm`): no hay columna de ID.

Errores que detecta el análisis:
- accesorio sin una fila `BASE` antes, o de otro modelo que esa `BASE`;
- `BASE` sin ningún valor `ATR_`;
- dos configuraciones del mismo modelo con la misma combinación de atributos;
- el mismo accesorio dos veces en una configuración;
- precios vacíos o que no son números;
- precios que indican otra moneda que la elegida (§6).

---

## 4. Reglas (`Reglas`)

Formato `Nombre:sufijo`; varias reglas se separan con `|`. **El sufijo es obligatorio.**

| Sufijo | Tipo | Comportamiento |
|---|---|---|
| `:e` | Exclusión | Como máximo **uno** del grupo. |
| `:et` | Exclusión | Igual que `:e`. |
| `:i` | Inclusión | Bloqueado hasta que se elija un habilitante del grupo. |
| `:it` | Inclusión (habilitante) | Elegirlo **habilita** a los `:i` del grupo. |
| `:u` | **Opción única** | Siempre hay **exactamente uno** elegido (§4.1). Se combina con `:e`. |

### 4.1 Opción única (`:u`): estándar con alternativas

```csv
001,Pionera,ESTANDAR,,Kit Fino,50,,Kit Siembra:u,,,
001,Pionera,OPCIONAL,,Kit Grueso,80,,Kit Siembra:u,,,
001,Pionera,OPCIONAL,,Kit Mixto,30,,Kit Siembra:u,,,
```

- El `ESTANDAR` del grupo arranca elegido; las `OPCIONAL` son sus **alternativas**.
- En el configurador el grupo se muestra con botones de radio. Elegir una alternativa deselecciona la
  opción anterior, y no se puede dejar el grupo vacío.
- Cada opción se cotiza a su precio completo. El configurador muestra la diferencia con el estándar
  (`+ USD $ 30,00`, `− USD $ 20,00`).
- En la cotización, la opción elegida va en la sección **Equipamiento**.
- Una opción puede estar **además en grupos de exclusión** (`|` separa reglas):

  ```csv
  001,Pionera,OPCIONAL,,Kit Mixto,30,,Kit Siembra:u|Cuchillas:e,,,
  001,Pionera,OPCIONAL,,Cuchilla A,20,,Cuchillas:e,,,
  ```

  Con la Cuchilla A elegida, el Kit Mixto queda bloqueado (y al revés). No puede estar en un grupo de
  inclusión (`:i`) ni en otra opción única.

### 4.2 Coherencia (son errores, no avisos)

| Regla | Error si… |
|---|---|
| `:u` | el grupo no tiene **exactamente un** `ESTANDAR` en la configuración. |
| `:u` | un accesorio del grupo está además en un grupo de inclusión (`:i` / `:it`) o en otra opción única (exclusión `:e` sí se permite). |
| `:e` | hay más de un `ESTANDAR` en el grupo, contando las opciones únicas que estén en él (use `:u`). |
| `:i` | un `ESTANDAR` no habilitante depende de un habilitante (`:it`) que no es `ESTANDAR`. |

Estas mismas validaciones se aplican al editar a mano la configuración en Odoo.

---

## 5. Cantidad dinámica (`Calc_param`)

Algunos accesorios se cotizan por unidad de un atributo (p. ej. un sensor **por línea**).

- `Calc_param` debe ser el **nombre exacto de una columna `ATR_`** del archivo, por ejemplo
  `ATR_Cantidad_de_Lineas`.
- Todos los valores de esa columna deben contener un número. El número se guarda en el valor del
  atributo (campo *Cantidad (Cotizador)*, editable en la ficha del atributo): `16 Líneas` → 16,
  `52,5 cm` → 52,5.
- El accesorio va a una subcategoría de *Accesorio* vinculada a ese atributo (campo *Atributo de
  Cantidad* de la categoría). Ese vínculo es lo único que usa el cálculo.
- **Cantidad cotizada** = número del valor de ese atributo en la configuración. Ejemplo:
  `Lineas = 16 Lineas`, `Precio_Item = 10` → 16 × 10 = 160.
- Un mismo accesorio de un modelo debe tener el mismo `Calc_param` en todas sus filas.
- La fila `BASE` de cada configuración que lo use debe tener valor en esa columna.

---

## 6. Precios

Todos los precios del CSV están en la **Moneda de los Precios** elegida en el importador (por
defecto, la de la compañía). Al importar se guarda como **Moneda del Cotizador** de cada modelo y
accesorio del CSV (campo de la ficha del producto, editable). Para cargar productos en monedas
distintas, impórtelos en archivos separados.

- Si un precio indica un código de moneda (`USD $1.000`), tiene que ser el elegido. Si no, es un
  **error**: evita cargar precios en USD como si fueran ARS.
- La moneda tiene que estar activa en Odoo para poder elegirla y para convertir.

El resto del texto (`$`, espacios) se descarta:

| CSV | Valor |
|---|---|
| `USD $248.866,00` | 248866,00 |
| `248866,5` | 248866,50 |
| `248.866` | 248866,00 (punto de miles) |
| `248866.00` / `248,866.00` | 248866,00 |
| vacío o texto | **error** |

**En la cotización y en la tienda**, máquina y accesorios pasan por la lista de precios de la
cotización (o de la sesión web), con sus reglas y la conversión de la Moneda del Cotizador de cada
producto a la moneda de la lista.

---

## 7. Identidad de los registros y re-importación

Una **configuración** es su combinación de atributos dentro de su máquina: se busca la de la máquina
con los mismos valores. Reordenar filas o agregar otras no la afecta, y una oportunidad que la pide la
conserva.

Para el resto, el importador **nunca busca por nombre**. Cada registro que crea queda registrado con
un identificador externo propio (módulo `cotizador_import`), armado con el texto del CSV:

| Registro | Identificador |
|---|---|
| Máquina | `cotizador_import.modelo_<modelo>` |
| Atributo / valor | `attr_<atributo>` / `val_<atributo>_<valor>` |
| Accesorio | `acc_<modelo>_<nombre>` |
| Categoría de cantidad | `qty_<atributo>` |
| Regla | `rule_<tipo>_<nombre>` |

(`<…>` en minúsculas, sin acentos, con `_` en lugar de espacios y símbolos.)

**Cada accesorio es propio de un modelo.** El mismo `Nombre_Item` en dos modelos crea **dos
productos** distintos, cada uno con su *Modelo de Máquina*. Un accesorio solo puede usarse en
configuraciones de su modelo (también al editar a mano).

Consecuencias:

- **Renombrar en Odoo** (máquina, accesorio, categoría…) no rompe nada: la re-importación encuentra
  el registro por su identificador y no crea duplicados.
- **Cambiar un nombre en el CSV** crea un registro nuevo (es otro identificador).
- Dos textos que solo difieren en acentos, mayúsculas o símbolos (`Kit-Fino` / `kit fino`) son un
  **error**: producirían el mismo identificador.
- Registros creados **a mano** en Odoo no se reutilizan, salvo las configuraciones (se buscan por
  combinación). Si existe una regla manual con el mismo nombre y tipo, la importación se detiene y
  pide renombrarla o eliminarla.
- **Registros borrados**: si se borra en Odoo algo que creó el importador, la próxima importación lo
  vuelve a crear. Puede quedar el identificador sin registro (al borrar un atributo, la base borra sus
  valores sin borrar sus identificadores); el importador lo reutiliza para el registro nuevo.

### 7.1 Re-importar: la máquina queda igual al CSV

Para cada máquina que está en el archivo:

| Al re-importar… | Resultado |
|---|---|
| Configuración que está en el CSV | Se actualizan precio y descripción, y sus líneas de accesorio se **reemplazan** por las del CSV, todo junto. |
| Configuración que **no** está en el CSV | **Se borra**, también si se creó a mano. Su variante se quita (o se archiva si ya se usó en ventas) y una oportunidad que la pedía queda sin configuración. |
| Accesorio de la máquina que ya no está en el CSV | **Se archiva** (no se borra: puede estar en cotizaciones). Si vuelve al CSV, se reactiva el mismo producto. |
| Valores de atributo de la máquina | Quedan **exactamente** los del CSV; un atributo "Siempre" que la máquina ya no usa se le quita. |
| Regla del importador que ya no está en el CSV | Se borra si ninguna máquina la usa. Las reglas creadas a mano no se tocan. |
| Atributos, valores y categorías de cantidad | Se crean si faltan; no se borran (pueden ser de otras máquinas). |

Las máquinas que no están en el archivo no se tocan. Para dar de baja una máquina entera, archivarla
en Odoo.

Ejemplo del detalle que muestra el análisis (y que queda en el chatter de la máquina):

```text
Pionera
  Configuraciones nuevas: 1          20 Lineas · 52 cm · 3.000,00
  Configuraciones modificadas: 1     16 Lineas · 52 cm: Precio: 1.000,00 → 1.100,00; Kit Fino: precio 50,00 → 60,00; − Cuchilla B
  Configuraciones que se borran: 1   Pionera: 18 Lineas, 52 cm
  Accesorios que se archivan: 1      Cuchilla B
  Valores de atributo: 2             Lineas: + 20 Lineas · Lineas: − 18 Lineas
```

En una configuración modificada, `+ accesorio` es una línea nueva, `− accesorio` una que se quita, y
`accesorio: …` un cambio de precio, de estándar, de habilitante o de reglas.

---

## 8. Ejemplo

```csv
Modelo,Tipo_Item,Precio_Base,Nombre_Item,Precio_Item,Calc_param,Reglas,Descripcion,ATR_Lineas,ATR_Distancia
Pionera,BASE,"USD $1.000,00",,,,,,16 Lineas,52 cm
Pionera,ESTANDAR,,Monitor,100,,Monitor:it,,,
Pionera,OPCIONAL,,Sensor,10,ATR_Lineas,Monitor:i,,,
Pionera,ESTANDAR,,Kit Fino,50,,Kit Siembra:u,,,
Pionera,OPCIONAL,,Kit Grueso,80,,Kit Siembra:u,,,
Pionera,OPCIONAL,,Kit Mixto,30,,Kit Siembra:u|Cuchillas:e,,,
Pionera,OPCIONAL,,Cuchilla A,20,,Cuchillas:e,,,
Pionera,OPCIONAL,,Cuchilla B,25,,Cuchillas:e,,,
Pionera,BASE,2000,,,,,,18 Lineas,52 cm
Pionera,ESTANDAR,,Kit Fino,55,,Kit Siembra:u,,,
Pionera,OPCIONAL,,Kit Grueso,85,,Kit Siembra:u,,,
```

Configuración Pionera de 16 líneas:

- **Arrancan elegidos** *Monitor* y *Kit Fino*.
- *Sensor* está habilitado (el Monitor es su habilitante) y cotiza 16 × 10.
- *Kit Grueso* / *Kit Mixto* reemplazan al *Kit Fino* (+30 / −20).
- *Cuchilla A*, *Cuchilla B* y *Kit Mixto* son excluyentes entre sí: con una cuchilla elegida, el
  Kit Mixto no se puede elegir.

Es el CSV que usan los tests (`tests/common.py`).

---

## 9. Archivos grandes

**No hace falta partir el archivo.** Odoo acepta archivos de hasta 128 MB (parámetro
`web.max_file_upload_size`); una máquina con miles de configuraciones ocupa unos pocos MB. Si la
subida falla con *413 Request Entity Too Large*, el límite es del proxy delante de Odoo (en nginx,
`client_max_body_size`, que por defecto es 1 MB), no del módulo.

Lo que sí cuenta es el **tiempo**: con workers, Odoo corta una petición a los `limit_time_real`
segundos (120 por defecto). Una configuración que no cambió no se reescribe, así que re-importar con
pocos cambios es rápido; la primera importación de una máquina grande es la más lenta. Si se corta,
subir `limit_time_real` en la configuración del servidor.

**Una máquina va entera en una misma importación.** El importador deja cada máquina igual al archivo
(§7.1): importarla en partes borraría, en cada importación, las configuraciones de las partes
anteriores.

---

## 10. Errores frecuentes

| Mensaje | Qué hacer |
|---|---|
| `columnas desconocidas …` | Renombrar las columnas de atributos con el prefijo `ATR_`, o quitar la columna. |
| `regla '…' inválida` | Agregar el sufijo: `Nombre:e`, `:i`, `:it`, `:u`. |
| `Calc_param '…' debe ser el nombre exacto de una columna` | Usar el encabezado completo, p. ej. `ATR_Cantidad_de_Lineas`. |
| `el valor '…' no contiene un número` | Los valores de un atributo de cantidad deben incluir el número (`16 Lineas`). |
| `debe tener exactamente un accesorio ESTANDAR` | Cada grupo `:u` necesita un único `ESTANDAR` por configuración. |
| `no tiene valor en ATR_…, que usan otras configuraciones` | Completar la celda: cada configuración necesita un valor de cada atributo de su máquina. |
| `son indistinguibles para el importador` | Unificar la escritura de ese nombre en todo el CSV. |
| `regla … creada fuera del importador` | Renombrar o eliminar la regla manual con ese nombre y tipo. |
| `está en USD, pero la moneda de los precios elegida es …` | Elegir la moneda correcta en el importador, o separar los productos en otro archivo. |
| `el accesorio no tiene una fila BASE antes` | Poner cada accesorio debajo de la `BASE` de su configuración (§3). |
| `la combinación … ya está en otra fila BASE` | Dos configuraciones del modelo con los mismos atributos: unificarlas o corregir un valor. |
| `marque las hojas a importar` | Marcar en *Hojas a importar* las hojas de las máquinas a cargar (§11). |
| `la hoja no tiene la fila de encabezados con 'Modelo' y 'PRECIO'` | Se marcó una hoja auxiliar: desmarcarla (§11). |
| `la fórmula no tiene valor calculado` | El .xlsx lo generó un programa que no calcula: abrirlo y guardarlo en Excel, LibreOffice o Google Sheets. |

---

## 11. Planillas: Excel y planillas de Odoo

Una planilla (`.xlsx` o planilla de Odoo) se lee **hoja por hoja**. Al cargarla, el asistente lista
sus hojas visibles en **Hojas a importar** y se importan **solo las marcadas** (un libro de una sola
hoja ya viene marcado). Un libro suele tener todas las máquinas, hojas auxiliares, copias y
exportaciones viejas: como cada máquina importada queda igual a su hoja (§7.1), se marca solo lo que
se quiere cargar. Una máquina no puede estar en dos hojas marcadas (p. ej. `Domina` y
`Copia de Domina`): sus configuraciones chocarían.

Cada hoja marcada tiene que ser una **planilla de configuraciones** (§11.1). Las hojas auxiliares
(costos, descripciones) no se marcan: sus valores llegan a las hojas de máquinas por las fórmulas.

De cada celda se toma el **valor calculado**: las fórmulas valen su resultado. Los precios se leen
como número; los textos (modelo, valores de atributo, variantes), como se ven en la celda.

**Lo oculto no se lee.** Las columnas y filas ocultas (a mano o por un filtro) son para cálculos
auxiliares: una columna oculta se saltea y una fila oculta cuenta como vacía (no da reglas, ni datos,
ni se repite hacia abajo). Como cada máquina queda igual a su hoja, una fila de **datos** oculta por
error borraría configuraciones: el análisis lista las filas de datos ocultas que no leyó, para
revisarlas antes de importar.

### 11.1 Planilla de configuraciones

Es la planilla de configuraciones tal como se trabaja: una fila por configuración (o varias, si suma
variantes de un accesorio) y una columna por accesorio. Reemplaza al script de Google Sheets que la
convertía al CSV. Código: `models/config_sheet.py`.

```text
      A            B          C           D (oculta)  E        F            G          H              I            J       K
 1    TIPO                                                     ESTANDAR                ESTANDAR
 2    CALC PARAM                                                            Lineas
 3    REGLAS                                                   Monitor:it   Monitor:i  Kit Siembra:u (H3:I3 combinadas)
 4    Modelo       Lineas     Distancia   Costo       PRECIO   Monitor      Sensor     Kit Fino       Kit Grueso   Tolva   PRECIO
 5    Pionera      16 Lineas  52 cm       999         1000     100          10         50             80           Chica   30
 6                                                                                                                 Grande  45
 7                 18 Lineas                          2000     100          -          55             85
```

- **Encabezado**: la fila (entre las primeras 50) que tiene `Modelo` y `PRECIO` (o `PRECIO BASE`).
  - Columnas **antes de PRECIO** (salvo Modelo): **atributos**. `Lineas` → `ATR_Lineas`.
  - Columnas **después de PRECIO**: **accesorios**, con el encabezado como nombre.
  - Las columnas y filas **ocultas** se ignoran: sirven para cálculos auxiliares (D en el ejemplo).
- **Filas sobre el encabezado**: datos de cada columna de accesorio, según la etiqueta de la
  columna A:
  - `TIPO…`: `ESTANDAR` marca equipamiento estándar; si no, es opcional.
  - `CALC…` o `…PARAM…`: el atributo de cantidad (§5), por su nombre (`Lineas`).
  - `REGLA…` o sin etiqueta: reglas (§4, con su sufijo). Ahí también se acepta `ESTANDAR` o el
    nombre de un atributo (cantidad).
  - Una regla en celdas **combinadas** vale para todas sus columnas (H3:I3 en el ejemplo).
- **Filas de datos**:
  - Una celda vacía **repite la de arriba** (fila 6: Pionera, 16 Lineas, 52 cm, 1000).
  - Cuando una fila escribe `Modelo` o `PRECIO`, los accesorios dejan de repetirse (fila 7).
  - Filas seguidas con el mismo modelo, precio y atributos son **una configuración**.
  - Las celdas combinadas valen en todas sus celdas.
- **Accesorios**: la celda es el **precio** en esa configuración; vacía, `-` o `0` = no lo tiene.
  - Si la columna siguiente se llama `PRECIO`, la celda es la **variante** y el precio va al lado:
    `Tolva` + `Chica` → accesorio **Tolva - Chica** (J y K en el ejemplo).
  - Un accesorio repetido con el mismo precio en una configuración se carga una vez.
- **Identidad**: cada configuración es su combinación (§3), así que agregar, quitar o reordenar filas
  no cambia las demás configuraciones.

El ejemplo da dos configuraciones de Pionera (16 y 18 líneas). La de 16 líneas trae Monitor y Kit
Fino estándar, Sensor por línea, Kit Grueso como alternativa y las opcionales Tolva - Chica y Tolva - Grande.

### 11.2 Cuidados

- **Códigos con ceros a la izquierda** (`001`): una planilla los convierte en número (`1`). Dar a la
  columna formato de texto, o escribirlos con un apóstrofo (`'001`).
- **`.xlsx` generados por programas** (exportaciones, scripts): necesitan los valores calculados de
  las fórmulas. Si no los tienen, el análisis lo avisa; abrir y guardar el archivo en Excel,
  LibreOffice o Google Sheets lo resuelve.
- Desde **Google Sheets**: *Archivo › Descargar › Microsoft Excel (.xlsx)* conserva columnas ocultas,
  celdas combinadas y valores calculados.

### 11.3 Matriz leída (CSV)

Al analizar una planilla, el asistente ofrece **Matriz leída (CSV)**: lo que se leyó, en el formato
del CSV. Sirve para revisar la conversión, y se puede volver a importar tal cual.

### 11.4 Planillas de Odoo

Con los módulos `cotizador_spreadsheet` y `spreadsheet_oca` (OCA), el importador tiene el origen
**Planilla de Odoo**: se elige la planilla en lugar de subir archivos. La planilla de configuraciones
se trabaja directamente en Odoo y se importa sin exportar nada.

- Las fórmulas se calculan en el navegador al analizar (un libro grande, con miles de fórmulas, tarda
  unos segundos). Se incluyen los cambios que alguien esté haciendo en ese momento, aunque todavía no
  haya cerrado la planilla.
- Los números se leen con **coma decimal** (`17,5`), cualquiera sea el idioma de la planilla o del
  usuario: es como los escribía Google Sheets, y el texto de un valor de atributo es parte de su
  identidad.
- La lista de hojas sale de la última versión guardada: una hoja agregada o renombrada aparece
  después de cerrar la planilla.
- Sirven las fórmulas de planilla (`SUM`, referencias entre hojas, etc.). Las funciones que leen
  datos de Odoo (`ODOO.LIST`, tablas dinámicas) no.
- Para empezar, una planilla de Excel o Google Sheets se sube como planilla de Odoo desde el menú
  *Planillas*. Tiene que haberse guardado en Excel, LibreOffice o Google Sheets: los `.xlsx` generados
  por programas (p. ej. la plantilla de códigos de Teamcenter) no se abren bien.

---

## Ver también

- [Conceptos](conceptos.md): configuración, accesorio, reglas y cantidad dinámica.
- [Recetas › Agregar una columna al importador](recetas.md#agregar-una-columna-al-importador).
- Código: `models/sembradora_import_wizard.py` (documentado en formato Doxygen).
