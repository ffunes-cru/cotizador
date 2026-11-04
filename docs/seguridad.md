# Seguridad

## Quién puede qué

| Acción | Visitante | Cliente portal | Vendedor (usuario interno) | Administrador del Configurador |
|---|---|---|---|---|
| Ver la matriz en la tienda (combinaciones y precios de su lista) | ✔ | ✔ | ✔ | ✔ |
| Pedir cotización desde la tienda | ✔ (solo lead, con límites) | ✔ (oportunidad + cotización) | ✔ | ✔ |
| Leer configuraciones, accesorios, reglas, planes | — | — | ✔ | ✔ |
| Cotizar con el configurador, descuentos, usados, plan de pago, BCRA | — | — | ✔ (en sus cotizaciones, según Ventas) | ✔ |
| Modificar la matriz, reglas, descripciones y planes de pago | — | — | — | ✔ |
| Importador, Teamcenter | — | — | — | ✔ |

El grupo *Administrador del Configurador* (`cotizador.group_cotizador_manager`) incluye a *Ventas / Usuario:
solo sus documentos*. Al instalar lo reciben `admin` y el superusuario; los demás se asignan en *Ajustes ›
Usuarios › Configurador de Sembradoras*. La matriz de permisos completa está en la
[referencia](referencia.md#permisos-por-modelo).

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

## Ver también

- [Conceptos de Odoo › Grupos, permisos y reglas](odoo.md#grupos-permisos-de-acceso-y-reglas)
- [Operación](operacion.md)
