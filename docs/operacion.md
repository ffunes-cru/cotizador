# Operación

## Puesta en marcha

1. Instalar el módulo (`-i cotizador`) o actualizarlo (`-u cotizador`) y reiniciar el servidor.
2. **Monedas**: activar las monedas de la matriz (p. ej. USD) y cargar sus tasas, aunque la compañía esté en
   otra (p. ej. ARS).
3. **Lista de precios** en la moneda en que se quiere cotizar y elegirla como *Lista de Precios de
   Cotizaciones* (abajo).
4. **Permisos**: dar el grupo *Administrador del Configurador* a quien administra la matriz.
5. **Importar la matriz** (*Ventas › Configuración › Configurador Sembradoras › Importar
   Configuraciones*) eligiendo la *Moneda de los Precios*. Ver [Importador](importador.md).
6. **Tienda**: publicar las máquinas, configurar el captcha (*Ajustes › Sitio web*) y elegir el modo de la
   tienda.
7. **Planes de pago**: cargar las plantillas (*Plantillas Planes de Pago*).

## Ajustes

*Ajustes › Ventas › Cotizador de Sembradoras*.

### De la compañía

| Ajuste | Campo | Qué controla |
|---|---|---|
| Impuesto de Maquinaria | `res.company.cotizador_tax_id` | Impuesto de máquinas y accesorios cotizados con el configurador. Vacío: los impuestos de cada producto. |
| Lista de Precios de Cotizaciones | `res.company.cotizador_pricelist_id` | Lista (y moneda) de las cotizaciones de máquinas: las creadas desde el CRM y la web, y las creadas a mano al configurar la primera máquina. Vacía: la lista habitual del cliente. |

### Parámetros del sistema

También visibles en *Ajustes › Técnico › Parámetros del sistema*.

| Parámetro | Por defecto | Qué controla |
|---|---|---|
| `cotizador.ecommerce_mode` | `quote_only` | `quote_only`: la tienda solo recibe solicitudes de cotización (sin checkout ni pago). `ecommerce`: carrito estándar para los productos que no son máquinas. |
| `cotizador.portal_confirmation_mode` | `salesman_enables` | Modo de aceptación de cotizaciones en el portal (ver [Flujos](flujos.md#aceptación-en-el-portal)). |
| `cotizador.plan_pago_required` | desactivado | Exige plan de pago para confirmar. |
| `cotizador.modo_silencioso` | desactivado | *Modo Silencioso*: el configurador del vendedor no muestra el precio por unidad ("$ 10 c/u") de los accesorios que van por cantidad (p. ej. 16 sensores), solo su subtotal. |
| `cotizador.quote_rate_limit_ip` | 5 | Solicitudes anónimas por IP y por hora (0 = sin límite). |
| `cotizador.quote_rate_limit_contact` | 3 | Solicitudes anónimas por email o teléfono y por hora. |
| `cotizador.quote_min_seconds` | 3 | Segundos mínimos entre abrir la página y enviar el formulario. |
| `product.dynamic_variant_limit` (de Odoo) | 1000 | Máximo de variantes que Odoo crea de una vez: tiene que ser mayor que la cantidad de configuraciones de la máquina más grande. |
| `cotizador.condiciones_generales_default` | ver `DEFAULT_CONDICIONES_GENERALES` | Texto de condiciones generales de las cotizaciones nuevas. |

### En cada producto

| Campo | Dónde | Qué controla |
|---|---|---|
| *Moneda del Cotizador* | Ficha de máquinas y accesorios | Moneda de sus precios de matriz. La fija el importador. |
| *Modelo de Máquina* | Ficha de accesorios | Máquina a la que pertenece el accesorio. |
| *Atributo de Cantidad* | Categoría de producto | Accesorios de la categoría que se cotizan por el número del valor de ese atributo. |
| *Cantidad (Cotizador)* | Valor de atributo | El número que multiplica a esos accesorios (`16 Líneas` → 16). |

## Menús del administrador

*Ventas › Configuración › Configurador Sembradoras*: Configurador Studio, Asistente de Precios, Importar
Configuraciones, Códigos de Ingeniería (Teamcenter), Reglas de Accesorios, Matriz Base (Datos Raw),
Accesorios por Configuración y Plantillas Planes de Pago.

## Comandos frecuentes

Desde la carpeta de Odoo (`odoo_sv/odoo`), con el entorno virtual:

```bash
# Actualizar el módulo después de cambiar código (y reiniciar el servidor)
.venv/bin/python odoo-bin -d <base> -u cotizador --stop-after-init

# Tests del módulo, en una base de prueba (nunca la de producción)
.venv/bin/python odoo-bin -d <base_de_prueba> -i cotizador --test-tags /cotizador --stop-after-init --http-port 8299

# Un solo test
.venv/bin/python odoo-bin -d <base_de_prueba> --test-tags /cotizador:TestConfigurator.test_confirm_sections_and_choice_rules --stop-after-init --http-port 8299

# Regenerar docs/referencia.md (el test test_documentacion falla si quedó desactualizado)
.venv/bin/python odoo-bin shell -d <base_de_prueba> --no-http <<< "from odoo.addons.cotizador.tools.documentacion import escribir; escribir(env)"

# Documentación del código (HTML en docs/api/html/index.html), desde la carpeta del módulo
doxygen docs/Doxyfile

# Sitio de la documentación con buscador (site/index.html), desde la carpeta del módulo; no necesita Odoo.
# Primero Doxygen, así el sitio incluye el código. Con `mkdocs serve` en vez de `build` se recarga solo.
doxygen docs/Doxyfile
uvx --with mkdocs-material==9.6.14 --with mkdocs-include-markdown-plugin==7.1.5 mkdocs build

# Complejidad ciclomática (regenera docs/mantenibilidad.md), desde la carpeta del módulo; no necesita Odoo
uv run --no-project --with lizard==1.25.0 python tools/complejidad.py
```

- Los tours de navegador necesitan Chrome y el paquete `websocket-client` en el entorno virtual
  (`uv pip install --python .venv/bin/python websocket-client`); si faltan, Odoo los omite sin fallar.
- `-i` sobre un módulo ya instalado **no** lo actualiza: para código nuevo usar `-u`.

## Problemas comunes

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| `no existe la columna ... cotizador_...` al arrancar | Código nuevo sobre una base sin actualizar. | Detener el servidor, `-u cotizador`, volver a arrancar. |
| La cotización sale en la moneda de la compañía y no en la de la matriz | La cotización ya tenía productos al configurar, o no hay *Lista de Precios de Cotizaciones*. | Elegir la lista en los ajustes; en una cotización ya cargada, cambiar la lista y actualizar precios. |
| No aparece una moneda para elegir | La moneda está inactiva. | Activarla y cargar su tasa. |
| El análisis del importador dice "está en USD, pero la moneda de los precios elegida es …" | Moneda equivocada en el importador. | Elegir la moneda del archivo. |
| Una combinación no se puede elegir en la tienda | No está en la matriz. | Habilitarla en el Studio o en el CSV. |
| "pertenece al modelo … y no puede usarse en una configuración de …" | Se quiso usar el accesorio de otra máquina. | Cada máquina tiene sus accesorios: crear (o importar) el de esta máquina. |
| El límite de solicitudes bloquea a todos | Odoo detrás de un proxy sin `--proxy-mode`. | Arrancar con `--proxy-mode`. |
| La consulta BCRA da error | La API no responde (o bloquea la IP del servidor). | Reintentar más tarde; el error nunca se muestra como "sin deudas". |
| "The number of variants to generate is above allowed limit" al importar | La máquina tiene más de 1000 configuraciones (límite de Odoo para crear variantes de una vez). | Subir el parámetro `product.dynamic_variant_limit` y volver a importar. |
| "La máquina … no tiene variante para …" al cotizar | Atributos que no están en modo *Siempre* o una configuración incompleta. | Revisar el modo de los atributos y que la configuración tenga un valor de cada atributo. |
| Los tours aparecen como *skipped* | Falta Chrome o `websocket-client`. | Instalarlos. |

## Ver también

- [Recetas](recetas.md) · [Pendientes](pendientes.md)
- [Configurar monedas (Odoo)](https://www.odoo.com/documentation/19.0/applications/finance/accounting/get_started/multi_currency.html)
