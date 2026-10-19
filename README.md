# Cotizador de Sembradoras (Odoo 19)

Cotizador de maquinaria agrícola configurable para Odoo 19:
- matriz de ingeniería de configuraciones válidas por máquina;
- accesorios con reglas y equipamiento estándar;
- configurador visual en el backend;
- configurador paso a paso en la tienda online, con solicitud de cotización;
- cascada de totales con descuentos y toma de usados;
- planes de pago, integración con CRM y consulta crediticia BCRA.

- **Autor:** Franco Funes · **Licencia:** AGPL-3
- **Depende de:** `sale`, `sale_crm`, `crm`, `portal`, `website_sale`, `base_import_module`

## Contenido

| Área | Qué hace | Dónde |
|---|---|---|
| Matriz de ingeniería | Configuraciones válidas (combinación de atributos + precio) y, por configuración, accesorios con precio, reglas y marca *Estándar*. | `models/sembradora_config*.py` |
| Importador CSV | Carga y actualiza la matriz completa. Ver **[doc/IMPORTADOR.md](doc/IMPORTADOR.md)**. | `models/sembradora_import_wizard.py` |
| Configurador visual (OWL) | Botón *Configurar* en la cotización: modelo → atributos → accesorios (grupos de opción única como botones de radio, con la diferencia de precio). | `static/src/components/configurador/` |
| Studio / Asistente de Precios / Teamcenter | Edición masiva de configuraciones, precios y códigos de ingeniería. | `static/src/components/configurador_studio/`, `price_wizard/`, `models/engineering_code_wizard.py` |
| Tienda online | Configurador secuencial en la ficha de la máquina y formulario *Solicitar Cotización*. | `controllers/main.py`, `views/website_sale_templates.xml`, `static/src/js/` |
| Cotización | Secciones Máquina / Equipamiento / Accesorios; cascada SUB TOTAL → IVA → descuentos → usados → saldo; planes de pago; reporte PDF; modos de firma en el portal. | `models/sale_order_inherit.py`, `report/` |
| CRM | Equipo cotizado y configuración solicitada en la oportunidad, botón *Crear Cotización*, ingreso esperado sincronizado, ganada al confirmar. | `models/crm_lead_inherit.py` |

## Datos del módulo

- Categorías **Máquina** (`cotizador.cat_maquina`) y **Accesorio** (`cotizador.cat_accesorio_base`).
  Un producto es máquina o accesorio si está en esa categoría o en una subcategoría (`is_maquina`,
  `is_accesorio`). Se pueden renombrar.
- Un producto de servicio por tipo de plan de pago (`cotizador.product_plan_<tipo>`).
- **Accesorios por modelo**: cada accesorio pertenece a una máquina (*Modelo de Máquina* en la ficha)
  y solo se usa en configuraciones de esa máquina. El importador crea un producto por modelo aunque
  el nombre se repita.
- Lo que crea el importador queda identificado con xmlids `cotizador_import.*`
  (ver [doc/IMPORTADOR.md §7](doc/IMPORTADOR.md)).

## Configuración

1. **Permisos** (*Ajustes › Usuarios › Configurador de Sembradoras*):
   - **Administrador del Configurador**: configuraciones, precios, accesorios, reglas, descripciones y
     plantillas de planes de pago; importador, Studio, Asistente de Precios y Teamcenter.
   - Usuarios internos (vendedores): leen la matriz y cotizan con el configurador.
   - Al instalar solo `admin` recibe el grupo.
2. **Ajustes › Ventas › Cotizador de Sembradoras**:
   - **Precios del Configurador**:
     - *Impuesto de Maquinaria*: impuesto de máquinas y accesorios. Si está vacío, se usan los
       impuestos de cada producto.
     - *Lista de Precios de Cotizaciones*: para las cotizaciones de máquinas, del backend y de la web.
       Una cotización creada a mano pasa a esta lista al configurar su primera máquina, si todavía
       no tiene productos. Si ya tiene, conserva su lista y los precios se convierten a su moneda.
   - **Protección del Formulario de Solicitud Web**:
     - límites por hora, por IP y por email/teléfono (0 = sin límite);
     - tiempo mínimo para completar el formulario;
     - aviso si no hay captcha configurado.
   - Plan de pago obligatorio, modo silencioso, modo de la tienda (solo cotización / eCommerce),
     aceptación en el portal y condiciones generales.
3. **Captcha**: active *reCAPTCHA* o *Cloudflare Turnstile* en *Ajustes › Sitio web*. El formulario lo
   usa automáticamente (acción `cotizador_quote`).
4. **Proxy inverso**: detrás de nginx o Apache, arranque Odoo con `--proxy-mode`. Si no, todas las
   solicitudes parecen venir de la misma IP y el límite por IP bloquea a todos.

## Precios

- **Base: la matriz.** El precio de la configuración (máquina) y el de la línea de accesorio de esa
  configuración son el *precio de lista* para Odoo (`_price_compute`), en la **Moneda del Cotizador**
  del producto (campo de la ficha; la fija el importador). La moneda de la compañía puede ser otra
  (p. ej. ARS con la matriz en USD). Por
  eso las reglas de listas de precios, la conversión de moneda y los descuentos nativos se aplican
  igual en la tienda, en el configurador y en la cotización.
- **Listado de la tienda.** Sin combinación elegida, la máquina muestra su configuración más barata
  ("desde").
- **Precio 0.** Un accesorio con precio 0 en la configuración se cotiza sin cargo; no se usa el
  precio de venta del producto.
- **Cantidad dinámica.** Para accesorios con *Calc_param*, la cantidad es el número guardado en el
  valor del atributo (ver el doc del importador, §5).
- **Opción única (`:u`).** Cada opción se cotiza a su precio completo; el configurador muestra la
  diferencia con el estándar.
- **Rendimiento.** Las configuraciones por máquina se leen de un índice en caché que se invalida al
  modificar la matriz.

## Solicitud de cotización web

- **Visitante anónimo**: se crea **solo un lead** del CRM, con los datos de contacto, la configuración
  elegida y su equipamiento estándar. No se crea contacto ni cotización. El vendedor convierte el lead
  con el asistente estándar de Odoo (vincular a un cliente existente o crear uno) y usa
  **Crear Cotización**. El visitante ve una página de confirmación sin enlaces a documentos.
- **Cliente logueado**: oportunidad y cotización a su nombre, y se lo lleva a ella en el portal.
- **Máquinas**: la configuración elegida es obligatoria.
- **Protecciones**:
  - CSRF, campo trampa (honeypot) y captcha;
  - **token firmado** con la hora de apertura del formulario: rechaza bots sin JavaScript, envíos
    instantáneos y tokens vencidos;
  - límites por hora y escape de todo texto ingresado;
  - la IP queda registrada en el lead.
- **Portal**: `/my/quotes` muestra solo cotizaciones enviadas.
- **Modo "Solo cotización"**: bloquea el checkout y el pago.

## Desarrollo

```bash
# Actualizar el módulo
.venv/bin/python odoo-bin -d <base> -u cotizador --stop-after-init
# Tests del módulo (unitarios, HTTP y tours de navegador)
.venv/bin/python odoo-bin -d <base_de_prueba> -i cotizador --test-tags /cotizador --stop-after-init
```

Los tours necesitan Chrome y el paquete Python `websocket-client`; sin ellos Odoo los **omite**
(*skipped*) sin fallar.

Contexto técnico para agentes de IA: [GEMINI.md](GEMINI.md).

## Problemas conocidos

Pendientes. Al resolver uno, quítelo de esta lista.

1. **Planes de pago en la cascada de totales (a confirmar).** La línea del plan se cotiza como
   `total × %` al momento de elegirlo y cuenta dentro de SUB TOTAL:
   - si después cambian las líneas, el importe del plan queda desactualizado;
   - un plan con descuento (% negativo) no aparece en "Total Descuentos".

   Hay que confirmar la regla comercial antes de cambiarlo.
2. **La cantidad de un valor de atributo no se recalcula al renombrarlo.** El importador la toma del
   número del valor. Si se renombra el valor en Odoo (p. ej. `16 Líneas` → `18 Líneas`), hay que
   corregir a mano el campo *Cantidad (Cotizador)*, o volver a importar.
3. **En la tienda no se eligen accesorios.** La solicitud web incluye la máquina y su equipamiento
   estándar; los opcionales se agregan al armar la cotización desde el CRM.
