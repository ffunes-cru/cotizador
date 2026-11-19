# Cotizar una máquina

Guía del vendedor: de la oportunidad a la cotización firmada.

## 1. Crear la cotización

Hay dos caminos:

- **Desde una oportunidad del CRM** que ya tiene una máquina elegida (por ejemplo, una solicitud de la tienda):
  botón **Crear Cotización**. La cotización nace con la máquina y su equipamiento estándar. Si la oportunidad
  todavía es un *lead* sin cliente, primero hay que convertirla con el botón estándar del CRM.
- **Desde cero**: *Ventas › Pedidos › Cotizaciones › Nuevo*, elegir el cliente y seguir con el paso 2.

Quien lleva la cotización es el **Vendedor** (pestaña *Otra información*). Con él, Odoo completa solo el equipo de
ventas y, junto al cliente, el **Concesionario**: el líder de ese equipo. Quién ve y quién edita cada cotización
depende de esos campos ([Niveles de usuario](index.md#niveles-de-usuario)).

## 2. Configurar el equipo

Botón **Configurar** (arriba a la derecha) o **Cotizar Equipo** (botón verde debajo de las líneas). Se abre el
configurador en tres pasos:

1. **Modelo**: la máquina.
2. **Configuración**: una opción de cada característica. Solo se ofrecen las combinaciones que existen en la
   matriz; si falta una, avisarle al administrador.
3. **Accesorios**: arrancan elegidos los del **equipamiento estándar**. Se agregan o quitan los demás:
   - en un grupo de **opción única** (botones de radio) siempre va uno; elegir otro reemplaza al estándar y se
     ve la diferencia de precio;
   - un accesorio **bloqueado** muestra el motivo: es excluyente con otro ya elegido, o requiere uno que no
     está elegido;
   - los accesorios **por cantidad** muestran cuántas unidades van (por ejemplo, un sensor por línea).

El resumen de la derecha muestra el total. **Añadir a la Cotización** carga las líneas en tres secciones:
*Máquina*, *Equipamiento* (estándar y opciones únicas) y *Accesorios*.

- Los precios son los de la matriz, en la moneda de la *Lista de Precios de Cotizaciones*. Si la cotización
  estaba vacía, pasa sola a esa lista.
- **Configurar otra vez agrega otra máquina**, no reemplaza la anterior. Para cambiar la configuración, borrar
  las líneas de la máquina anterior (sus tres secciones) y volver a configurar.

## 3. Descuentos, usados y plan de pago

Debajo de las líneas (botones verdes):

- **Añadir Descuento**: un **porcentaje** sobre el neto que dejan los descuentos anteriores (se aplican en
  cascada) o un **monto fijo** sin IVA. Se ve la base de cálculo y el descuento resultante antes de aplicarlo.
  Los descuentos en porcentaje se recalculan solos si después cambian las líneas.
- **Añadir Equipo Usado**: el equipo que el cliente entrega como parte de pago, con su descripción (marca,
  modelo, año, estado) y el monto acordado. Se resta al final, después del IVA.

Arriba a la derecha:

- **Planes de Pago**: lista las opciones de las plantillas con el **total simulado** de cada una. *Elegir
  Plan* aplica su recargo o descuento; *Limpiar Plan Seleccionado* lo quita. Va un plan por cotización.
- **Situación BCRA**: deudas y cheques rechazados del cliente según la Central de Deudores (necesita el CUIT
  del cliente). Al elegir un cliente con deudas aparece un aviso. Si la consulta falla se muestra el error,
  nunca "sin deudas".

### Cómo se calcula el total

| Renglón | Qué es |
|---|---|
| SUB TOTAL | Máquina, equipamiento, accesorios y otros productos, sin IVA. |
| Descuentos | Descuentos comerciales. |
| Plan de Pago | Recargo (+) o descuento (−) del plan, sobre el neto con descuentos. |
| SUB TOTAL NETO | La base del IVA. |
| IVA | Calculado después de descuentos y plan. |
| TOTAL | SUB TOTAL NETO + IVA. |
| Medios de pago (Usados) | Los usados tomados como pago. |
| **SALDO A CANCELAR** | Lo que paga el cliente. |

Ejemplo: 100.000 de neto con un descuento del 6 % quedan 94.000; con IVA del 10,5 % (9.870) el total es
103.870.

## 4. Imprimir y enviar

En la pestaña **Condiciones y Planes de Pago**:

- **Planes de Pago a Imprimir**: qué planes van en la hoja de planes del PDF, cada uno con su saldo estimado.
  Arranca vacío: se tildan solo los que se quieren imprimir; *Buscar más…* los muestra agrupados por plantilla.
  Sin ninguno, el PDF va sin hoja de planes. El menú *Imprimir* tiene además la cotización con todos los planes
  del catálogo.
- **Condiciones Generales Constantes**: el texto del pie; viene de los ajustes y se puede cambiar en cada
  cotización.

*Imprimir* o *Enviar* generan el PDF; la cotización pasa a *Enviada*. Los botones de arriba van en este orden:
*Vista previa*, *Enviar*, *Imprimir*, *Generar Factura Proforma*, *Confirmar Pedido* y *Cancelar*.

La columna **Cantidad** de las líneas aparece solo si alguna línea lleva más de una unidad (por ejemplo, un
sensor por línea), y muestra solo esas cantidades.

## 5. Aceptación del cliente

El cliente ve la cotización en el portal (`/my`). Si la puede firmar depende del modo de la cotización
(misma pestaña, *Aceptación y Firma en el Portal Web*):

| Modo | Qué ve el cliente |
|---|---|
| **Habilitado por el Vendedor** (el habitual) | Una propuesta preliminar, sin botón de firma, hasta que el vendedor usa **Habilitar Firma del Cliente** en el menú de acciones (⚙, junto al número de la cotización). *Revocar Firma del Cliente*, en el mismo menú, lo vuelve atrás. |
| **Solo el Vendedor** | Nunca puede firmar: la venta la confirma el vendedor. |
| **Estándar Odoo** | Firma y pago según la configuración de Ventas. |

Al **confirmar** (el vendedor, o el cliente al firmar) la cotización pasa a pedido de venta y la oportunidad,
a ganada. Si el administrador activó *Plan de Pago Obligatorio*, no se puede confirmar sin plan.

## Problemas frecuentes

| Qué pasa | Por qué | Qué hacer |
|---|---|---|
| No aparece la combinación que pide el cliente | No está en la matriz. | Pedirle al administrador que la agregue a la planilla y la importe. |
| Un accesorio no se puede elegir | Es excluyente con otro elegido, o requiere uno que falta. | Leer el motivo en el configurador. |
| "Crear Cotización" no aparece o da error en una oportunidad | La oportunidad no tiene máquina, o es un lead sin cliente. | Convertir el lead y elegir el cliente. |
| La cotización quedó en pesos y la matriz está en dólares | Ya tenía productos cuando se configuró la máquina. | Cambiar la lista de precios a la de cotizaciones y usar *Actualizar precios*. |
| No se puede guardar un cambio en una configuración o un accesorio | El vendedor solo lee la matriz. | Lo cambia el administrador. |
| No se puede confirmar: falta el plan de pago | *Plan de Pago Obligatorio* está activo. | Elegir un plan en *Planes de Pago*. |
