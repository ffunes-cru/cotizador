# Importador CSV de Configuraciones de Sembradora

Wizard `sembradora.import.wizard` (`models/sembradora_import_wizard.py`).
Carga la **matriz de ingeniería**: configuraciones válidas de cada máquina y su precio, accesorios
compatibles con su precio, reglas entre accesorios y equipamiento estándar.

**Menú:** *Ventas › Configuración › Configurador Sembradoras › Importar Configuraciones*
**Permisos:** grupo *Configurador de Sembradoras / Administrador del Configurador*.

---

## 1. Flujo

1. **Cargar** uno o varios CSV (se procesan juntos, como un solo archivo) y elegir la **Moneda de
   los Precios** (§6).
2. **📊 Analizar CSV**: valida **todo** el archivo y muestra:
   - la lista completa de **errores**, con archivo y línea. Si hay alguno, el botón *Importar* no
     aparece: corrija el CSV y use *Cargar otros archivos*;
   - cuántas configuraciones, modelos, atributos, accesorios y reglas ya existen y cuántas se crearán;
   - líneas de accesorio, estándar, grupos de opción única y atributos de cantidad.
3. **📥 Importar**: vuelve a validar y escribe todo en una sola transacción (si algo falla no queda
   nada a medio importar).

El análisis no escribe nada. La importación usa exactamente los archivos analizados.

---

## 2. Columnas

Codificación UTF-8 (con o sin BOM; si falla, Latin-1). Separador coma; use comillas para valores con
coma (`"USD $248.866,00"`). Los nombres de columna distinguen mayúsculas.

| Columna | Obligatoria | Uso |
|---|---|---|
| `ID_Configuracion` | Sí | Identificador de la configuración **dentro del modelo**. |
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
- Los valores se leen de la fila `BASE`. Una celda vacía significa que esa configuración no usa ese
  atributo. En las filas de accesorio estas columnas se ignoran.
- Los atributos se crean en modo de variantes *dinámico*.

---

## 3. Filas

Cada configuración es **una fila `BASE`** más una fila por accesorio, todas con el mismo
`Modelo` + `ID_Configuracion`.

| `Tipo_Item` | Significado |
|---|---|
| `BASE` | Atributos (`ATR_…`) y `Precio_Base` de la configuración. Exactamente una por configuración. |
| `OPCIONAL` | Accesorio compatible que el vendedor puede agregar. |
| `ESTANDAR` | Accesorio de **equipamiento estándar**: arranca **seleccionado**. |

Errores que detecta el análisis:
- configuración sin `BASE` o con dos;
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
| `:u` | **Opción única** | Siempre hay **exactamente uno** elegido (§4.1). |

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

### 4.2 Coherencia (son errores, no avisos)

| Regla | Error si… |
|---|---|
| `:u` | el grupo no tiene **exactamente un** `ESTANDAR` en la configuración. |
| `:u` | un accesorio del grupo tiene además otra regla. |
| `:e` | hay más de un `ESTANDAR` en el grupo (use `:u`). |
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

El importador **nunca busca por nombre**. Cada registro que crea queda registrado con un
identificador externo propio (módulo `cotizador_import`), armado con el texto del CSV:

| Registro | Identificador |
|---|---|
| Máquina | `cotizador_import.modelo_<modelo>` |
| Configuración | `cotizador_import.cfg_<modelo>_<id_configuracion>` |
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
- Registros creados **a mano** en Odoo no se reutilizan. Si existe una regla manual con el mismo
  nombre y tipo, la importación se detiene y pide renombrarla o eliminarla.

| Al re-importar… | Resultado |
|---|---|
| Configuración que está en el CSV | Se actualizan modelo, combinación, precio y descripción; sus líneas de accesorio se **reemplazan** por las del CSV. |
| Configuración que no está en el CSV | No se toca. |
| Productos, atributos, categorías, reglas | Se crean si faltan; nunca se borran. |
| `ID Externo` (código de ingeniería / Teamcenter) | Se fija al crear la configuración; después lo administra Studio / Teamcenter. |

---

## 8. Ejemplo

```csv
ID_Configuracion,Modelo,Tipo_Item,Precio_Base,Nombre_Item,Precio_Item,Calc_param,Reglas,Descripcion,ATR_Lineas,ATR_Distancia
001,Pionera,BASE,"USD $1.000,00",,,,,,16 Lineas,52 cm
001,Pionera,ESTANDAR,,Monitor,100,,Monitor:it,,,
001,Pionera,OPCIONAL,,Sensor,10,ATR_Lineas,Monitor:i,,,
001,Pionera,ESTANDAR,,Kit Fino,50,,Kit Siembra:u,,,
001,Pionera,OPCIONAL,,Kit Grueso,80,,Kit Siembra:u,,,
001,Pionera,OPCIONAL,,Kit Mixto,30,,Kit Siembra:u,,,
001,Pionera,OPCIONAL,,Cuchilla A,20,,Cuchillas:e,,,
001,Pionera,OPCIONAL,,Cuchilla B,25,,Cuchillas:e,,,
002,Pionera,BASE,2000,,,,,,18 Lineas,52 cm
002,Pionera,ESTANDAR,,Kit Fino,55,,Kit Siembra:u,,,
002,Pionera,OPCIONAL,,Kit Grueso,85,,Kit Siembra:u,,,
```

Configuración `Pionera / 001`:

- **Arrancan elegidos** *Monitor* y *Kit Fino*.
- *Sensor* está habilitado (el Monitor es su habilitante) y cotiza 16 × 10.
- *Kit Grueso* / *Kit Mixto* reemplazan al *Kit Fino* (+30 / −20).
- *Cuchilla A* y *B* son excluyentes entre sí.

Es el CSV que usan los tests (`tests/common.py`).

---

## 9. Archivos grandes

```bash
python3 scripts/split_csv.py matriz_completa.csv 150   # 150 configuraciones por archivo
```

(o `scripts/split_csv_gui.py`). Las partes se pueden cargar juntas en un mismo análisis.

---

## 10. Errores frecuentes

| Mensaje | Qué hacer |
|---|---|
| `columnas desconocidas …` | Renombrar las columnas de atributos con el prefijo `ATR_`, o quitar la columna. |
| `regla '…' inválida` | Agregar el sufijo: `Nombre:e`, `:i`, `:it`, `:u`. |
| `Calc_param '…' debe ser el nombre exacto de una columna` | Usar el encabezado completo, p. ej. `ATR_Cantidad_de_Lineas`. |
| `el valor '…' no contiene un número` | Los valores de un atributo de cantidad deben incluir el número (`16 Lineas`). |
| `debe tener exactamente un accesorio ESTANDAR` | Cada grupo `:u` necesita un único `ESTANDAR` por configuración. |
| `son indistinguibles para el importador` | Unificar la escritura de ese nombre en todo el CSV. |
| `regla … creada fuera del importador` | Renombrar o eliminar la regla manual con ese nombre y tipo. |
| `está en USD, pero la moneda de los precios elegida es …` | Elegir la moneda correcta en el importador, o separar los productos en otro archivo. |
