# Operación técnica

La puesta en marcha, los ajustes y los menús, contados para el administrador, están en la guía de uso:
[Puesta en marcha y ajustes](uso/administracion.md). Acá queda lo técnico: parámetros del sistema, comandos y
problemas del servidor.

## Parámetros del sistema

Los ajustes de *Ajustes › Ventas › Cotizador de Sembradoras* se guardan como parámetros del sistema, también
visibles en *Ajustes › Técnico › Parámetros del sistema*.

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

Los problemas de uso (monedas, listas de precios, mensajes del importador) están en la guía:
[Puesta en marcha y ajustes](uso/administracion.md#problemas-frecuentes) y [Cotizar](uso/cotizar.md#problemas-frecuentes).

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| `no existe la columna ... cotizador_...` al arrancar | Código nuevo sobre una base sin actualizar. | Detener el servidor, `-u cotizador`, volver a arrancar. |
| El límite de solicitudes bloquea a todos | Odoo detrás de un proxy sin `--proxy-mode`. | Arrancar con `--proxy-mode`. |
| "The number of variants to generate is above allowed limit" al importar | La máquina tiene más de 1000 configuraciones (límite de Odoo para crear variantes de una vez). | Subir el parámetro `product.dynamic_variant_limit` y volver a importar. |
| "La máquina … no tiene variante para …" al cotizar | Atributos que no están en modo *Siempre* o una configuración incompleta. | Revisar el modo de los atributos y que la configuración tenga un valor de cada atributo. |
| Los tours aparecen como *skipped* | Falta Chrome o `websocket-client`. | Instalarlos. |

## Ver también

- [Despliegue](despliegue.md) · [Recetas](recetas.md) · [Pendientes](pendientes.md)
