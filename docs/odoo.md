# Conceptos de Odoo usados en el módulo

Las piezas de Odoo que aparecen en esta documentación, explicadas con ejemplos del módulo. Cada sección
termina con el enlace a la documentación oficial de Odoo 19.

## Modelos, registros y campos

Un **modelo** es una tabla con su comportamiento en Python (`sembradora.config.rel`, `sale.order`). Un
**registro** es una fila. Los **campos** se declaran en la clase (`fields.Char`, `fields.Many2one`…). Toda
lectura y escritura pasa por el **ORM**, que aplica los permisos.

- `Many2one`: apunta a un registro (la máquina de una configuración). `One2many`: la lista inversa (las
  líneas de accesorio de una configuración). `Many2many`: varios con varios (los valores de una configuración).
- `Monetary`: importe con su moneda (`currency_field`). Los precios de la matriz son `Monetary` con la
  moneda del producto.
- `create`, `write` y `unlink` crean, modifican y **borran** registros.

Oficial: [ORM API](https://www.odoo.com/documentation/19.0/developer/reference/backend/orm.html)

## Herencia (`_inherit`)

El módulo agrega campos y comportamiento a modelos de Odoo sin copiarlos: `class X(models.Model):
_inherit = 'sale.order'` suma lo de la clase al modelo existente. Un método heredado llama a
`super()` para conservar lo estándar (p. ej. `_price_compute` agrega el precio de matriz y deja el resto
igual). Los campos que el módulo agrega a modelos de Odoo están en la
[referencia](referencia.md#campos-agregados-a-modelos-de-odoo).

Oficial: [Inheritance and extension](https://www.odoo.com/documentation/19.0/developer/reference/backend/orm.html#inheritance-and-extension)

## Modelos abstractos como servicio RPC

`cotizador.configurator.service`, `cotizador.studio.service` y `cotizador.price.wizard.service` son
`AbstractModel`: no tienen tabla, solo métodos que el JavaScript llama con `orm.call(modelo, método, args)`.
Como no tienen permisos de acceso propios, **cada método valida quién lo llama**
(`check_configurator_manager`) o se apoya en los permisos de los modelos que toca.

Oficial: [AbstractModel](https://www.odoo.com/documentation/19.0/developer/reference/backend/orm.html#odoo.models.AbstractModel) ·
[servicio ORM](https://www.odoo.com/documentation/19.0/developer/reference/frontend/services.html#orm-service)

## Asistentes (TransientModel)

El importador, Teamcenter, descuento, usado, plan de pago y BCRA son `TransientModel`: registros temporales
que Odoo borra solo. Se abren con una acción `target: 'new'` (ventana emergente). Un botón de un asistente lo
cierra salvo que devuelva una acción que lo reabra (por eso `_reopen()` en el importador).

Oficial: [Transient models](https://www.odoo.com/documentation/19.0/developer/reference/backend/orm.html#odoo.models.TransientModel)

## Variantes

Una plantilla (`product.template`) tiene líneas de atributo; cada combinación de valores es una variante
(`product.product`). El modo de creación de variantes es del atributo:

- **Siempre** (el que usa el cotizador): Odoo crea las variantes al guardar las líneas de atributo, una
  por combinación **posible**. Para decidir cuáles son posibles usa
  `_filter_combinations_impossible_by_config`; el módulo lo sobrescribe para que en una máquina solo sean
  posibles las combinaciones de su matriz. Resultado: una variante por configuración. Al agregar o
  quitar configuraciones se vuelven a sincronizar (`_cotizador_sync_variants`); una variante que ya se
  usó en ventas se archiva en lugar de borrarse.
- *Dinámico*: las variantes se crean al venderlas. El cotizador no lo usa.

Odoo limita la cantidad de variantes que crea de una vez (parámetro `product.dynamic_variant_limit`,
1000 por defecto): una máquina con más configuraciones necesita subirlo. Para elegir combinaciones en la
tienda Odoo pregunta `_is_combination_possible`; el módulo también responde con la matriz.

Oficial: [Product variants](https://www.odoo.com/documentation/19.0/applications/sales/sales/products_prices/products/variants.html)

## Listas de precios y `_price_compute`

Una **lista de precios** (`product.pricelist`) tiene una moneda y reglas (porcentajes, fórmulas, precios
fijos). Toda regla parte del **precio de lista** de un producto, que Odoo obtiene de `_price_compute` y
convierte a la moneda de la lista. El cotizador sobrescribe `_price_compute`: para máquinas y accesorios
devuelve el precio de la matriz (en la *Moneda del Cotizador* del producto). Así las reglas, la conversión
de moneda y los descuentos son los nativos en todos lados: tienda, portal y backend.

Como el precio de un accesorio depende de la configuración, se pasa en el contexto
(`_with_matrix_price(precio)` → contexto `cotizador_matrix_price`), que solo vale para ese producto.

Oficial: [Pricelists](https://www.odoo.com/documentation/19.0/applications/sales/sales/products_prices/prices/pricing.html) ·
[Multi-currency](https://www.odoo.com/documentation/19.0/applications/finance/accounting/get_started/multi_currency.html)

## Monedas y tasas

Cada compañía tiene una moneda; las demás se activan en *Contabilidad / Facturación › Configuración ›
Monedas* y tienen tasas por fecha. `moneda._convert(importe, otra_moneda, compañía, fecha)` convierte; si
las dos monedas son iguales la tasa es exactamente 1. Una moneda **inactiva** no se puede elegir ni usar en
una lista de precios.

Oficial: [Multi-currency system](https://www.odoo.com/documentation/19.0/applications/finance/accounting/get_started/multi_currency.html)

## Identificadores externos (xmlid)

Un registro puede tener un nombre estable `modulo.nombre` (`ir.model.data`), independiente de su nombre
visible. `env.ref('cotizador.cat_maquina')` lo encuentra aunque la categoría se renombre. El importador crea
xmlids propios (`cotizador_import.cfg_pionera_001`) para reencontrar lo que creó sin buscar por nombre.

Oficial: [Data Files](https://www.odoo.com/documentation/19.0/developer/reference/backend/data.html)

## Archivos de datos y noupdate

Los XML y CSV de `data/`, `security/`, `views/` y `report/` se cargan al instalar y se **vuelven a cargar
al actualizar** (`-u`). Lo que está en `<data noupdate="1">` (las categorías *Máquina* y *Accesorio*) se
carga solo al instalar: renombrarlas en Odoo no se pierde al actualizar. Un registro `noupdate` que se
quita del XML **no** se borra al actualizar (sí al desinstalar).

Oficial: [Data Files](https://www.odoo.com/documentation/19.0/developer/reference/backend/data.html)

## Grupos, permisos de acceso y reglas

- **Grupo** (`res.groups`): los permisos se dan a grupos. *Administrador del Configurador* incluye
  (`implied_ids`) a *Ventas / Usuario: solo sus documentos*.
- **Permisos de acceso** (`security/ir.model.access.csv`): por modelo y grupo, si se puede leer, escribir,
  crear y borrar. Ver la [matriz](referencia.md#permisos-por-modelo).
- **Reglas de registro** (`ir.rule`): qué registros. El módulo no define reglas propias; usa las de Ventas y
  CRM (p. ej. un vendedor ve sus cotizaciones).
- `groups="..."` en una vista o menú solo lo oculta: la seguridad real son los permisos y las validaciones
  de los métodos.

Oficial: [Security in Odoo](https://www.odoo.com/documentation/19.0/developer/reference/backend/security.html)

## Superusuario y sudo

`registro.sudo()` opera sin permisos ni reglas. El módulo lo usa en puntos acotados y siempre después de
validar: la tienda lee la matriz para el visitante anónimo y crea el lead; el importador crea productos y
atributos (solo lo puede abrir el administrador); la variante de una configuración la crea con sudo porque
los vendedores no crean productos.

Oficial: [sudo](https://www.odoo.com/documentation/19.0/developer/reference/backend/orm.html#odoo.models.Model.sudo)

## Decoradores de métodos

- `@api.depends(...)`: calcula un campo (los totales de la cotización, `is_maquina`).
- `@api.constrains(...)`: validación al guardar; si falla se cancela todo (reglas coherentes, accesorio del
  mismo modelo, combinación única).
- `@api.onchange(...)`: ayuda del formulario mientras se edita (alerta BCRA). **No** corre por RPC ni desde la
  web: nunca se usa para reglas.
- `@api.model_create_multi`: `create` que recibe una lista de valores.
- `@ormcache(...)`: guarda el resultado en memoria; se invalida con `registry.clear_cache()`. Lo usa el índice
  de configuraciones de cada máquina.

Oficial: [Method decorators](https://www.odoo.com/documentation/19.0/developer/reference/backend/orm.html#method-decorators)

## Parámetros del sistema y ajustes

`res.config.settings` es la pantalla de *Ajustes*. Un campo con `config_parameter='cotizador.x'` se guarda
en `ir.config_parameter` (visible en *Ajustes › Técnico › Parámetros del sistema*); uno *related* a la
compañía se guarda en la compañía. Ver [Operación](operacion.md#ajustes).

Oficial: [res.config.settings](https://www.odoo.com/documentation/19.0/developer/reference/backend/orm.html)

## Acciones cliente y componentes OWL

Una **acción cliente** (`ir.actions.client`, con un `tag`) abre un componente JavaScript en lugar de una
vista. El configurador, el Studio y el Asistente de Precios son componentes **OWL** registrados en
`registry.category("actions")` con su plantilla XML.

Oficial: [Client actions](https://www.odoo.com/documentation/19.0/developer/reference/backend/actions.html#client-actions-ir-actions-client) ·
[Owl components](https://www.odoo.com/documentation/19.0/developer/reference/frontend/owl_components.html)

## Sitio web: plantillas QWeb e interacciones

- **QWeb**: plantillas del servidor. El módulo hereda la ficha de producto de la tienda
  (`views/website_sale_templates.xml`) y la cotización del portal (`views/portal_templates.xml`).
- **Interacciones** (`@web/public/interaction`): JavaScript del sitio que se engancha a un selector CSS
  (`static selector`). El configurador paso a paso y el token del formulario son interacciones.

Oficial: [QWeb](https://www.odoo.com/documentation/19.0/developer/reference/frontend/qweb.html)

## Controllers y rutas

Un **controller** responde a URLs (`@http.route('/cotizador/solicitar_cotizacion', ...)`).
`auth='public'` permite visitantes sin sesión; `csrf=True` exige el token CSRF del formulario;
`type='jsonrpc'` es para llamadas desde JavaScript. Heredar un controller de Odoo y redefinir la ruta con
`@http.route()` reemplaza su comportamiento (así se bloquea el pago en modo "Solo cotización").

Oficial: [Web Controllers](https://www.odoo.com/documentation/19.0/developer/reference/backend/http.html)

## Captcha

Si en *Ajustes › Sitio web* está activo reCAPTCHA o Cloudflare Turnstile, el formulario con
`data-captcha="cotizador_quote"` agrega el token y el controller lo verifica con
`_verify_request_recaptcha_token`. Sin captcha configurado la verificación pasa siempre (por eso el aviso
en los ajustes del cotizador).

## Reportes PDF

`report/report_cotizacion_planes.xml` define una acción de reporte QWeb. Los botones de impresión pasan en
el contexto `print_planes_mode` (`all`, `filtered`, `none`) y la plantilla lo lee para decidir la hoja de
planes de pago.

Oficial: [QWeb Reports](https://www.odoo.com/documentation/19.0/developer/reference/backend/reports.html)

## Tests

- `TransactionCase`: test de Python; todo se deshace al terminar.
- `HttpCase`: además levanta el servidor web (`url_open`, `make_jsonrpc_request`) y corre **tours**
  (`start_tour`): un Chrome sin ventana que sigue pasos como un usuario. Necesita Chrome y el paquete
  `websocket-client`; si faltan, Odoo los **omite** sin fallar.
- `@tagged('post_install', '-at_install')`: corre después de instalar todos los módulos.

Oficial: [Testing Odoo](https://www.odoo.com/documentation/19.0/developer/reference/backend/testing.html)

## Actualización y migración

- `-i modulo` instala; si ya está instalado **no hace nada**. `-u modulo` actualiza: crea columnas y tablas
  nuevas y recarga los datos.
- Los scripts de `migrations/<versión>/` corren solo al actualizar a una versión mayor. Este módulo **no
  tiene**: todavía no hay datos de producción que adaptar.

Oficial: [Upgrade scripts](https://www.odoo.com/documentation/19.0/developer/reference/upgrades/upgrade_scripts.html) ·
[Command-line interface](https://www.odoo.com/documentation/19.0/developer/reference/cli.html)
