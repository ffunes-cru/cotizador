# Seguridad

## Quién puede qué

| Acción | Visitante | Cliente portal | Vendedor (usuario interno) | Administrador del Configurador |
|---|---|---|---|---|
| Ver la matriz en la tienda (combinaciones y precios de su lista) | ✔ | ✔ | ✔ | ✔ |
| Pedir cotización desde la tienda | ✔ (solo lead, con límites) | ✔ (oportunidad + cotización) | ✔ | ✔ |
| Leer configuraciones, accesorios, reglas, planes | — | — | ✔ | ✔ |
| Cotizar con el configurador, descuentos, usados, plan de pago, BCRA | — | — | ✔ (en las cotizaciones que puede editar según su [nivel](#niveles-comerciales-concesionario-zona-gerencia)) | ✔ |
| Modificar la matriz, reglas, descripciones y planes de pago | — | — | — | ✔ |
| Importador, Teamcenter | — | — | — | ✔ |

El grupo *Administrador del Configurador* (`cotizador.group_cotizador_manager`) incluye a *Ventas / Usuario:
solo sus documentos*. Al instalar lo reciben `admin` y el superusuario; los demás se asignan en *Ajustes ›
Usuarios › Configurador de Sembradoras*. La matriz de permisos completa está en la
[referencia](referencia.md#permisos-por-modelo).

## Niveles comerciales (concesionario, zona, gerencia)

Pedido en el issue #1. Se apoya en el estándar de Ventas y agrega solo lo que falta:

- **Concesionario = equipo de ventas** (`crm.team`): el líder estándar (`user_id`) es el usuario del concesionario
  y los miembros, sus vendedores. Se agrega `cotizador_supervisor_id` (*Supervisor de Zona*,
  `models/crm_team.py`): la zona son los equipos con el mismo supervisor.
- **Grupos**: los estándar de Ventas (*solo sus documentos*, *todos los documentos*, *administrador*) más el
  privilegio *Nivel Comercial (Cotizador)* con dos grupos, que implican *solo sus documentos*:
  `cotizador.group_lider_concesionario` y `cotizador.group_supervisor_zona`.
- **Reglas** (`security/cotizador_security.xml`): Odoo combina con OR las reglas de los grupos del usuario, así
  que las nuevas **amplían** la regla estándar "solo sus documentos" (`user_id` = el usuario, o vacío).

| Grupo | Modelos | Dominio | Permisos |
|---|---|---|---|
| Líder de Concesionario | `sale.order`, `sale.report`, `crm.lead`, `crm.activity.report` | `team_id.user_id = usuario` | Todos |
| | `sale.order.line` | `order_id.team_id.user_id = usuario` | Todos |
| Supervisor de Zona | `sale.order`, `sale.report`, `crm.lead`, `crm.activity.report` | `team_id.cotizador_supervisor_id = usuario` | Solo lectura |
| | `sale.order.line` | `order_id.team_id.cotizador_supervisor_id = usuario` | Solo lectura |

En la cotización, *Concesionario* (`sale.order.lider_equipo_id`) es el líder del equipo del vendedor, relacionado y
guardado (`team_id.user_id`) para filtrar y agrupar; el equipo lo calcula Odoo a partir del vendedor. El supervisor
escribe solo lo suyo por la regla estándar. Al asignar una cotización (cambiar *Vendedor*), Odoo
controla el permiso **antes** de escribir, cuando todavía es suya; desde ahí queda en solo lectura. La
oportunidad la actualiza `sale.order._sync_with_crm()` con `sudo()`, porque en ese momento deja de ser del
supervisor. Los contactos y las facturas los restringe la sección siguiente, solo para usuarios externos.
Tests: `tests/test_niveles_usuario.py`.

## Usuarios externos (concesionarios)

Auditoría de seguridad de 11/2026. Los concesionarios y sus vendedores son usuarios **internos** que no son de
Crucianelli: sin esto veían todos los contactos (la base copiada de SAP y los clientes de otros concesionarios),
sus cuentas bancarias y las cotizaciones sin vendedor, como las de la tienda web.

- **Quién es externo:** el grupo *Usuario externo (concesionario)* (`cotizador.group_usuario_externo`, privilegio
  *Origen del Usuario (Cotizador)*). Se asigna solo al crear un usuario interno, al cambiarle el correo o al pasarlo
  de portal a interno, si su correo (el login, o el email si el login no es un correo) no es de un dominio de
  `cotizador.dominios_internos` (por defecto `crucianelli.com`). Nunca a un administrador (Ajustes) ni al
  superusuario. Se puede quitar a mano y se respeta; nunca se quita solo (`models/res_users.py`).
- **De quién es cada cliente:** `res.partner.cotizador_concesionario_ids` (*Concesionarios*, pestaña *Ventas y
  compras*, solo visible para el personal). Va en el contacto comercial; sus contactos hijos lo heredan. Se completa
  solo: con los concesionarios de un externo que crea el cliente, y con el equipo de cada cotización u oportunidad
  en la que aparece (`models/res_partner.py`). Un externo no lo puede cambiar, y solo comparte clientes que ya ve:
  Odoo no verifica la lectura al escribir un many2one (por ejemplo, el cliente de una cotización por RPC).
- **Alta de clientes:** el formulario de contacto le muestra a un externo solo razón social, CUIT, correo, teléfono,
  localidad y provincia (`view_partner_form_cotizador_externo`; minimización de datos). Es solo la vista: el servidor
  no rechaza otros campos, porque flujos estándar como convertir una oportunidad copian la dirección al cliente.
- **CUIT repetido:** un externo no puede cargar (ni cambiar a) un CUIT que ya tiene un cliente de sus concesionarios;
  el error dice cuál es (`_cotizador_check_cuit_repetido()`). Si el CUIT es de otro concesionario o de la base de
  Crucianelli, **no se le avisa**, porque sería revelar que ese cliente existe: carga su propia ficha. Por eso un
  cliente puede tener varias fichas; el *Análisis de ventas* agrupa por **CUIT** (`sale.report.cotizador_cuit`, sin
  guiones) para verlo unificado (`models/sale_report.py`).
- **Reglas** (`rule_externo_*`): son **globales**, porque las de grupo se suman con OR a las estándar y no podrían
  restringir. Su dominio es `[(1, '=', 1)]` para quien no es externo.

| Modelo | Un externo ve |
|---|---|
| `res.partner` | Los clientes de sus concesionarios (como líder o miembro del equipo) y sus contactos; los que creó; los usuarios internos (aparecen como vendedor o seguidor), la empresa y su propia empresa. **No** ve la base de Crucianelli ni los clientes de otros concesionarios. |
| `res.partner.bank` | Ninguna cuenta bancaria. |
| `sale.order`, `sale.order.line`, `sale.report`, `crm.lead` | Lo que ya le permiten sus grupos, salvo lo que **no tiene vendedor** y no es de sus concesionarios. |
| `account.move`, `account.move.line` | Lo que ya le permiten sus grupos, salvo las facturas sin vendedor. |

Lo que queda visible y es aceptado: los nombres y correos de trabajo de los usuarios internos, incluidos los de
otros concesionarios, y el directorio público de empleados (`hr.employee.public`: nombre, puesto, departamento).

Datos anteriores (migración 19.0.2.2.0): marca a los externos y asigna cada cliente a los concesionarios de sus
cotizaciones y oportunidades; el resto de los contactos queda solo para el personal. Tests:
`tests/test_visibilidad_externos.py` (reglas, CUIT, formulario, análisis por CUIT) y `tests/test_externos_rpc.py`: entra
como cada concesionario con usuario y contraseña, llama por JSON-RPC a las vías del navegador (listas, autocompletar,
agrupar, abrir por id, chatter, análisis de ventas) y verifica que no aparezca nada del otro. No depende de cómo
estén escritas las reglas: si un cambio deja un hueco en alguna de esas vías, falla.

## Las tres capas

1. **Permisos de acceso** (`security/ir.model.access.csv`): los usuarios internos tienen solo lectura de la
   matriz (configuraciones, líneas, reglas, descripciones, plantillas de planes); el administrador, todo.
   El importador y Teamcenter solo son accesibles al administrador.
2. **Servicio RPC**: el del configurador no tiene tabla ni permisos propios; corre con los permisos del
   vendedor (lee la matriz, escribe en su cotización), así que no puede hacer nada que el vendedor no pueda.
3. **Menús y botones** con `groups=`: solo ocultan. Nunca son la única protección.

`sudo()` se usa solo después de validar y en puntos acotados: la tienda (lectura de la matriz para el
visitante, creación del lead y de la cotización web), el importador (crea productos, atributos y
categorías) y la creación de la variante de una configuración.

## El formulario público de solicitud

Es la única entrada sin sesión que escribe datos. Protecciones, en orden
(`controllers/main.py`, `solicitar_cotizacion`):

| Capa | Contra qué | Dónde se configura |
|---|---|---|
| Token CSRF | Envíos desde otros sitios. | Estándar de Odoo. |
| Campo trampa (honeypot) | Bots que completan todos los campos. | — |
| Captcha (reCAPTCHA v3 / Turnstile) | Bots. | *Ajustes › Sitio web*. Sin captcha configurado la verificación pasa: los ajustes del cotizador lo avisan. |
| Token firmado del formulario | Bots sin JavaScript, envíos instantáneos, tokens viejos (más de 2 h). | *Tiempo mínimo para completar el formulario* (`cotizador.quote_min_seconds`). |
| Validación de datos | Solicitudes sin contacto o con una configuración de otra máquina. | — |
| Límites por hora (solo anónimos) | Abuso desde una IP o con un mismo email/teléfono. | `cotizador.quote_rate_limit_ip`, `cotizador.quote_rate_limit_contact` (0 = sin límite). |
| Escape de todo el texto | Inyección de HTML en el lead. | — |

- **Proxy inverso**: detrás de nginx/Apache Odoo debe arrancar con `--proxy-mode`; si no, todas las
  solicitudes parecen venir de la IP del proxy y el límite por IP bloquea a todos.
- El visitante anónimo no recibe enlaces a documentos: solo una página de confirmación.

## Pago online en modo "Solo cotización"

Se bloquean todas las entradas al pago de un carrito: páginas de checkout y de pago (redirigen a /shop),
*express checkout* y creación de la transacción (`/shop/payment/transaction/<id>`, dan error). El pago de
una cotización desde el portal lo decide el modo de aceptación (`_has_to_be_paid`).

## Datos externos

- **BCRA**: HTTPS con verificación del certificado; sin credenciales. Un error de la API se informa como
  error, nunca como "sin deudas".
- **Teamcenter**: los códigos se escriben con SQL **parametrizado** (nunca texto concatenado).

## Diagnóstico de errores de acceso

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| Un vendedor no puede guardar un cambio en una configuración | Los vendedores solo leen la matriz. | Lo hace un administrador. |
| El vendedor no ve el menú del configurador | Menús restringidos al administrador. | Es lo esperado; el configurador se abre desde la cotización (*Configurar*). |
| Un líder no ve las cotizaciones de un vendedor suyo | La cotización no tiene ese concesionario (equipo), o el usuario no es el *Líder del equipo*, o no tiene el nivel *Líder de Concesionario*. | Revisar el campo *Concesionario* de la cotización y el equipo de ventas. |
| Un supervisor no ve un concesionario | El equipo no tiene a ese usuario como *Supervisor de Zona*, o el usuario no tiene ese nivel. | Completar el supervisor en el equipo de ventas. |
| El supervisor no puede editar una cotización que creó | La asignó a otro vendedor: desde ahí la ve en solo lectura. | Lo esperado (issue #1). La edita el concesionario o gerencia. |
| Un concesionario no encuentra un cliente que existe | Es de la base de Crucianelli o de otro concesionario: los externos ven solo los suyos. | Si corresponde que lo atienda, crear la cotización con ese cliente y su concesionario (el cliente pasa a ser visible para él), o agregar el concesionario en el campo *Concesionarios* del cliente. |
| Un empleado de Crucianelli ve solo algunos clientes | Su usuario quedó marcado como *Usuario externo* (correo de otro dominio). | Quitarle el grupo en *Ajustes › Usuarios* (*Origen del Usuario*), o agregar su dominio a `cotizador.dominios_internos`. |

## Ver también

- [Conceptos de Odoo › Grupos, permisos y reglas](odoo.md#grupos-permisos-de-acceso-y-reglas)
- [Operación](operacion.md)
