# Cotizador de Sembradoras (Odoo 19)

Módulo de Odoo 19 para cotizar maquinaria agrícola configurable de Crucianelli:

- **Matriz de ingeniería**: configuraciones válidas de cada máquina con su precio, accesorios compatibles,
  reglas entre accesorios y equipamiento estándar. Se carga y se actualiza por CSV, Excel o planillas de Odoo
  (módulo `cotizador_spreadsheet`), también con la planilla de configuraciones tal como se trabaja.
- **Configurador del vendedor** en la cotización y **configurador paso a paso en la tienda**, con
  solicitud de cotización al CRM.
- **Cotización** con secciones, cascada de totales (descuentos, toma de usados), planes de pago, modos de
  aceptación en el portal, reporte PDF y consulta crediticia al BCRA.
- Precios en la **moneda de cada producto**, pasados por las listas de precios de Odoo.

**Autor:** Franco Funes · **Licencia:** AGPL-3 ·
**Depende de:** `sale`, `sale_crm`, `crm`, `portal`, `website_sale`, `base_import_module`.

## Documentación

Leer en este orden. Los diagramas son [Mermaid](https://mermaid.js.org/): GitHub, GitLab, VS Code (con
*Markdown Preview Mermaid Support*) y el HTML de Doxygen los dibujan solos.

**Sitio con buscador**: los mismos documentos como sitio web, con búsqueda en todo el texto (p. ej.
`modo_silencioso` encuentra el parámetro y el campo) y el código de Doxygen enlazado en el menú. Ver
[Operación › Comandos frecuentes](docs/operacion.md#comandos-frecuentes).

| Documento | Para qué |
|---|---|
| [Conceptos](docs/conceptos.md) | El negocio en palabras simples, el glosario y un ejemplo completo. Empezar acá. |
| [Conceptos de Odoo](docs/odoo.md) | Las piezas de Odoo que usa el módulo (listas de precios, variantes, xmlids, permisos, OWL…), con enlaces a la documentación oficial. |
| [Arquitectura](docs/arquitectura.md) | Qué hace cada archivo, cómo viaja un pedido, cómo se calcula un precio y las decisiones de diseño. |
| [Flujos](docs/flujos.md) | De la solicitud a la venta, reglas de accesorios, cascada de totales, portal, tienda. |
| [Importador](docs/importador.md) | Formato del CSV y de la planilla de configuraciones, planillas, validaciones y errores frecuentes. |
| [Seguridad](docs/seguridad.md) | Quién puede qué, protecciones del formulario público y diagnóstico de errores de acceso. |
| [Operación](docs/operacion.md) | Puesta en marcha, ajustes, comandos y problemas comunes. |
| [Recetas](docs/recetas.md) | Paso a paso para los cambios más habituales y cómo documentar el código. |
| [Pendientes](docs/pendientes.md) | Problemas conocidos y decisiones abiertas, con su gravedad. |
| [Mantenibilidad](docs/mantenibilidad.md) | Complejidad ciclomática de cada función (generada), puntos críticos, mejoras priorizadas y reglas para el código nuevo. |
| [Referencia](docs/referencia.md) | **Generada** desde Odoo: modelos, campos, permisos, parámetros y quién llama a cada método. |
| Código (Doxygen) | Cada clase, función y parámetro documentado en el código. HTML navegable: `doxygen docs/Doxyfile` → `docs/api/html/index.html`. |

## Ramas y despliegue

| Rama | Contenido |
|---|---|
| `main` | Principal. Cada push corre los tests y se despliega en **staging**. |
| `poc/studio-precios` | Pruebas de concepto archivadas: *Configurador Studio* (editor visual de la matriz) y *Asistente de Precios* (ajustes de precio en bloque). No se mantienen; la matriz se edita con el importador. |

**Producción** se despliega con un tag de la versión del manifiesto sobre un commit de `main`
(`git tag v2.1.0 && git push origin v2.1.0`, o con la serie: `v19.0.2.1.0`). Ver `.github/workflows/ci.yml`.

## Inicio rápido

```bash
# Instalar o actualizar (y reiniciar el servidor)
.venv/bin/python odoo-bin -d <base> -u cotizador --stop-after-init

# Tests del módulo, en una base de prueba
.venv/bin/python odoo-bin -d <base_de_prueba> -i cotizador --test-tags /cotizador --stop-after-init --http-port 8299
```

Después de instalar: activar la moneda de la matriz, elegir la *Lista de Precios de Cotizaciones* e
importar la matriz (ver [Operación](docs/operacion.md#puesta-en-marcha)).

Opcional: `openpyxl` (plantilla Excel de Teamcenter, sin él se usa CSV; e importar .xlsx), Chrome y `websocket-client` para
los tours de navegador, `doxygen` para el HTML de la documentación del código.

## Licencia

AGPL-3.0 o posterior: software libre. Ver [`LICENSE`](LICENSE).
