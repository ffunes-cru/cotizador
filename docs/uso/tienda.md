# Tienda y portal

Lo que ve el cliente en el sitio web y qué le llega al vendedor.

## Pedir una cotización en la tienda

En la ficha de una máquina, el cliente la configura **paso a paso**: modelo, cada característica y los
accesorios. Solo puede elegir combinaciones que existen en la matriz, con los mismos accesorios y reglas que
el configurador del vendedor. Al completar los pasos se habilita **Solicitar Cotización**, con un formulario
de contacto (nombre, empresa, email o teléfono, localidad y notas).

Qué se genera depende de si el cliente inició sesión:

| Cliente | Qué se crea | Qué hace el vendedor |
|---|---|---|
| **Sin sesión** (visitante) | Un **lead** en el CRM con la máquina pedida, el equipamiento estándar, sus datos y las notas. No se crea contacto ni cotización. | Revisar el lead, convertirlo en oportunidad con su cliente y usar *Crear Cotización* ([Cotizar](cotizar.md#1-crear-la-cotización)). |
| **Con sesión** (usuario del portal) | Una **oportunidad** a su nombre y una **cotización enviada** con la máquina y su equipamiento estándar. | Completar la cotización (accesorios, descuentos, plan) y, si corresponde, habilitar la firma. |

El formulario tiene protecciones contra envíos automáticos (captcha y límites por hora para los visitantes
sin sesión): un cliente que manda muchas solicitudes seguidas puede recibir un aviso de que espere.

## Modo de la tienda

Lo elige el administrador en los ajustes ([Puesta en marcha y ajustes](administracion.md#ajustes)):

| Modo | Máquinas | Otros productos | Pago online |
|---|---|---|---|
| **Solicitar Cotización** (el habitual) | Configurador y *Solicitar Cotización* | *Solicitar Cotización* | No: no hay carrito ni pago. |
| **Comercio Electrónico Estándar** | Configurador y *Solicitar Cotización* | Carrito normal | Sí, para los productos que no son máquinas. |

## El portal del cliente

En `/my` (*Sus cotizaciones*) el cliente ve sus cotizaciones con el equipo configurado, los descuentos, el plan
de pago, los usados, el saldo a cancelar y las condiciones comerciales. Si puede **aceptar y firmar** depende
del modo de la cotización ([Cotizar › Aceptación](cotizar.md#5-aceptación-del-cliente)); mientras no pueda, ve
la cotización como una propuesta y la leyenda "La confirmación oficial es realizada por su asesor comercial".
