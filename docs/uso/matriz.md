# Mantener la matriz

Guía del **Administrador del Configurador**. Todo está en *Ventas › Configuración › Configurador Sembradoras*.

La matriz se mantiene en la **planilla de configuraciones** (Excel, Google Sheets o una planilla de Odoo) y se
carga con el importador. Cambiar algo a mano en Odoo sirve para una corrección puntual, pero **la próxima
importación de esa máquina lo pisa**: el cambio tiene que estar también en la planilla.

## Importar la planilla

*Importar Configuraciones*:

1. **Origen**: *Archivos CSV o Excel* (subir el `.xlsx` o el CSV) o *Planilla de Odoo* (elegir la planilla).
2. **Moneda de los Precios**: la moneda de la planilla, por ejemplo USD.
3. **Hojas a importar**: marcar las hojas de las máquinas que se quieren cargar. Solo esas se tocan.
4. **📊 Analizar**. No cambia nada; muestra:
   - los **errores**, con hoja, fila y columna. Con errores no aparece *Importar*: corregir la planilla y usar
     *Cargar otros archivos*;
   - **lo que va a cambiar** en cada máquina: configuraciones nuevas, modificadas y que se borran, accesorios
     nuevos y archivados. Lo que se borra aparece en rojo;
   - las **filas de datos ocultas** que no se leyeron;
   - **Matriz leída (CSV)**, para descargar y revisar lo que se leyó.
5. **Revisar** antes de seguir: si una máquina que no cambió muestra configuraciones que se borran, algo de la
   planilla no coincide con lo cargado. No importar hasta entender por qué.
6. **📥 Importar**. Escribe todo junto: si algo falla no queda nada a medias. El detalle de los cambios queda
   en el historial (chatter) de cada máquina.

**Cada máquina importada queda igual a su hoja.** Lo que no está en la hoja se borra (configuraciones) o se
archiva (accesorios, porque pueden estar en cotizaciones viejas). Las máquinas de hojas no marcadas no se
tocan. Para dar de baja una máquina entera, archivarla.

### Cuidados con la planilla

- **Lo oculto no se lee**: las filas y columnas ocultas son para cálculos auxiliares. Una fila de datos oculta
  por error borra esa configuración (el análisis la lista).
- **Una máquina, una hoja marcada**: si hay una copia de la hoja (`Copia de Domina`), no marcarla junto con la
  original.
- **Códigos con ceros a la izquierda** (`001`): dar a la columna formato de texto, o el `001` se lee como `1`.
- **Archivos generados por programas** (exportaciones): abrirlos y guardarlos en Excel, LibreOffice o Google
  Sheets antes de importar; si no, las fórmulas no tienen valor y el análisis lo avisa.
- **Desde Google Sheets**: *Archivo › Descargar › Microsoft Excel (.xlsx)*.
- **Planilla de Odoo**: para empezar, subir el Excel desde *Planillas*. Las fórmulas se calculan al analizar e
  incluyen los cambios que alguien esté haciendo en ese momento. Una hoja nueva o renombrada aparece en la
  lista después de cerrar la planilla.

El formato completo (encabezados, filas TIPO, CALC PARAM y REGLAS, variantes de accesorios, mensajes de error)
está en [Formato de la planilla](../importador.md).

## Corregir a mano

| Menú | Para qué |
|---|---|
| *Matriz Base (Datos Raw)* | Las configuraciones de cada máquina con su precio y descripción. |
| *Accesorios por Configuración* | El precio de un accesorio en cada configuración, si es estándar y su cantidad fija. |
| *Reglas de Accesorios* | Grupos de excluyentes, de "requiere otro" y de opción única. Las creadas a mano no las borra el importador. |

Odoo valida al guardar que el equipamiento estándar siga siendo una elección posible (por ejemplo, que un grupo
de opción única tenga exactamente un estándar).

## Descripciones técnicas

En la ficha de la máquina, pestaña *Descripción Paramétrica*, se cargan textos que dependen de la configuración.
Cada regla tiene sus **Atributos Requeridos** (los valores para los que vale) y su texto; si varias aplican a
una configuración, gana la más específica. Si ninguna aplica, se usa la *Descripción General de Respaldo*.

## Códigos de ingeniería (Teamcenter)

*Códigos de Ingeniería (Teamcenter)* asigna a cada configuración su código de Teamcenter, que queda como
referencia interna del producto:

1. Elegir la máquina y **Generar Plantilla Espejo**: un Excel con una fila por configuración.
2. Ingeniería completa la columna `CODIGO_INGENIERIA_TEAMCENTER`.
3. Subir el archivo y **Analizar y Simular Coincidencias**: muestra qué código va a cada configuración, sin
   cambiar nada.
4. **Aplicar Códigos en Firme**.

## Planes de pago

*Plantillas Planes de Pago*: cada plantilla es un tipo de plan (canje de cereal, cheques, documentos, crédito
bancario) con sus opciones; cada opción tiene su descuento o recargo en porcentaje. El vendedor elige una opción
en la cotización y el PDF imprime la hoja de planes con el saldo de cada una.
