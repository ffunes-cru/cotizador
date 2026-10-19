# Guía del Proyecto: Cotizador Crucianelli (Módulo Odoo 19)

Este archivo proporciona todo el contexto técnico, arquitectónico y operativo necesario para que cualquier agente de IA continúe el desarrollo y mantenimiento del módulo **`cotizador`**.

---

## 1. Información General y Entorno

- **Ruta del Módulo:** `/home/user/odoo/addons/cotizador`
- **Versión de Odoo:** 19.0 (Python 3.13 / PostgreSQL)
- **Base de Datos de Pruebas Principal:** `test3` (secundaria: `test4`)
- **Comando de Actualización (CLI):**
  ```bash
  python3 /home/user/odoo/odoo-bin -u cotizador -d test3 --stop-after-init
  ```
- **Comando para Iniciar Servidor:**
  ```bash
  python3 /home/user/odoo/odoo-bin -d test3
  ```

> [!IMPORTANT]
> **Reinicio de Procesos de Odoo:** Al modificar archivos Python (`.py`), los procesos en segundo plano **no recargan el código automáticamente**. Siempre verifica con `ps aux | grep odoo` si existe un proceso activo, detenlo (`kill <pid>`), corre el upgrade y reinícialo.

---

## 2. Arquitectura del Módulo y Componentes Clave

El módulo extiende y conecta tres pilares principales en Odoo:
1. **Cotizaciones y Ventas (`sale.order`, `sale.order.line`)**
2. **CRM Comercial (`crm.lead`)**
3. **Tienda Online / eCommerce y Portal del Cliente (`website_sale`, portal)**

### A. Cascada Financiera de Totales y Descuentos Comerciales
Ubicación: `models/sale_order_inherit.py`, `views/views.xml`, `report/report_cotizacion_planes.xml`
- **Campos calculados en cascada:**
  - `amount_subtotal_productos`: Precio de lista base.
  - `amount_iva_productos`: IVA (impuesto de maquinaria configurado en Ajustes).
  - `amount_total_base`: Subtotal + IVA.
  - `amount_descuentos`: Suma de descuentos (se muestra en **negativo y rojo**).
  - `amount_total_con_descuentos`: Total base - descuentos.
  - `amount_usados`: Valor de canje por toma de maquinaria usada (en **negativo y rojo**).
  - `amount_saldo_cancelar`: Total final a pagar.
- **Wizards dedicados:**
  - `cotizador.descuento.wizard`: Maneja descuentos porcentuales o de monto fijo agrupados bajo la sección `Descuentos`. Intercepta las llamadas estándar de Odoo para evitar duplicación de botones o conflictos con el descuento por ítem.
  - `cotizador.equipo.usado.wizard`: Permite cotizar y agregar la toma de usados.

### B. Condiciones Comerciales y Planes de Pago
Ubicación: `models/res_config_settings.py`, `models/res_users_inherit.py`, `views/plan_pago_views.xml`
- **Condiciones Generales Constantes:** Campo `condiciones_generales` en `sale.order`, configurable globalmente en *Ajustes > Ventas > Cotizador de Sembradoras*. Se imprime al pie del reporte PDF y en el portal web.
- **Planes de Pago Filtrados:** Permite asociar plantillas de planes a usuarios vendedores (`res.users`) o seleccionar planes específicos por cotización (`plan_pago_line_ids`). Ofrece 3 acciones de impresión PDF en el menú *Imprimir* (Con planes filtrados, Con todos los planes, Sin planes).

### C. Integración con CRM (`crm.lead`)
Ubicación: `models/crm_lead_inherit.py`, `models/sale_order_inherit.py`, `views/crm_lead_view.xml`
- **Equipo Cotizado (`equipo_cotizado_id`):** Vincula el modelo de máquina (`is_maquina`: categoría `cotizador.cat_maquina` o subcategoría) tanto en la cotización como en el Lead/Oportunidad, disponible en la ficha y en la creación rápida del Kanban.
- **Sincronización:** Al cotizar, actualiza `expected_revenue` con `amount_saldo_cancelar`. Al confirmar la venta (`action_confirm`), marca la oportunidad como Ganada (`is_won = True`).
- **Tarjeta Kanban:** Diseñada siguiendo el estándar de Odoo con 5 datos prioritarios: Empresa, Equipo cotizado (ícono tractor), Monto en verde, Líder de equipo y Concesionario (avatar de usuario).

### D. Tienda Online y Configurador Secuencial Web
Ubicación: `models/product_template_inherit.py`, `controllers/main.py`, `views/website_sale_templates.xml`, `static/src/js/cotizador_sequential_configurator.js`, `static/src/css/cotizador_sequential_configurator.css`
- **Modo eCommerce (`cotizador.ecommerce_mode`):** Por defecto en `quote_only`. Bloquea el checkout y pagos online tradicionales; en su lugar, se solicita cotización directa.
- **Matriz de Ingeniería (`sembradora.config.rel`):**
  - `_is_combination_possible()`: Restringe combinaciones web únicamente a configuraciones técnicamente válidas.
  - `_get_combination_info()`: Determina el precio base real desde la configuración técnica de sembradoras y aplica reglas de listas de precios si existieran.
- **Configurador Secuencial Interactivo (UX Frontend):**
  - Stepper paso a paso: Inicia con el Paso 1 activo. Al seleccionar una opción, el paso colapsa a un chip resumen editable y se activa el siguiente paso.
  - Filtrado dinámico: En cada paso posterior, sólo se muestran opciones compatibles con las selecciones anteriores.
  - Tarjetas compactas con rangos de precio de la lista de la sesión: `(USD $ 120.000 - USD $ 380.000)`.
  - Botón "Solicitar Cotización" deshabilitado hasta completar todos los pasos. Botón permanente "↺ Reiniciar Configuración (Paso 1)".
  - Modal con honeypot anti-bots y validación segura contra XSS e inyecciones.
  - Al solicitar la cotización: visitante anónimo → solo un lead del CRM con la configuración (`cotizador_config_id`); el vendedor lo convierte y usa *Crear Cotización*. Cliente logueado → oportunidad + `sale.order` en estado `sent`.

### E. Moneda y Precios
- Moneda de la matriz, impuesto de maquinaria y lista de precios de cotizaciones: campos de `res.company` (`cotizador_*`), editables en *Ajustes › Ventas*. Nada de buscar monedas, impuestos ni listas por nombre o valor.
- La matriz es el precio de lista de máquinas y accesorios vía `_price_compute` (contexto `cotizador_matrix_price`); las reglas de listas de precios son las nativas de Odoo.

### F. Portal del Cliente y Control de Firma (3 Modos Comerciales)
Ubicación: `views/portal_templates.xml`, `models/sale_order_inherit.py`, `controllers/main.py`
- **Visibilidad:**
  - Cotizaciones web se crean en estado `sent`.
  - En `/my` se incorporó una tarjeta estática permanente **"Sus cotizaciones"** con contador en tiempo real.
  - En la confirmación web se incluyen botones de navegación rápida ("Ver todas mis cotizaciones", "Ir a Mi Cuenta", "Volver a la Tienda").
- **Sistema de Control de Aceptación y Firma (3 Modos):**
  Parámetro `cotizador.portal_confirmation_mode` y campo `portal_confirmation_mode` en `sale.order`:
  1. **`standard` (Estándar Odoo):** El cliente puede firmar/pagar según la configuración nativa de Odoo.
  2. **`salesman_enables` (Habilitado por Vendedor - Predeterminado):** Toda cotización web nace como **propuesta preliminar** (`portal_confirmation_allowed = False`). El cliente ve el detalle y totales en USD pero el botón "Aceptar y Firmar" está oculto con un aviso de *Revisión Comercial*. Cuando el vendedor revisa y adapta la propuesta con el cliente, hace clic en **"Habilitar Firma del Cliente"** en la cabecera del presupuesto (o activa el toggle en la pestaña de Condiciones y Planes) para permitir la firma en la web. Puede revocarse con **"Revocar Firma del Cliente"**.
  3. **`salesman_only` (Solo el Vendedor):** El cliente nunca puede firmar ni aceptar en la web (aviso de *Presupuesto Informativo No Vinculante*). La venta sólo puede confirmarse internamente desde el backend.
  - Protección de seguridad en `_has_to_be_signed()` y `_has_to_be_paid()`, bloqueando también llamadas directas por API/POST.

### G. Matriz de Ingeniería, Accesorios y Equipamiento Estándar
Ubicación: `models/sembradora_config.py`, `models/sembradora_config_acc_line.py`, `models/sembradora_import_wizard.py`
- **Importador CSV:** `doc/IMPORTADOR.md`. Columnas de atributo con prefijo `ATR_` (cualquier otra columna desconocida es error), sufijo de regla obligatorio, todo se valida antes de escribir. Identidad por xmlids propios `cotizador_import.*`: **nunca buscar por nombre**.
- **Lógica única de accesorios** en `sembradora.config.rel` (no duplicar en servicios/controladores):
  - `validate_rule_set()`: coherencia de reglas y estándar; la usan el importador y la restricción `_check_accessories`.
  - `_get_accessory_offer()`: cantidad (`product.category.cotizador_qty_attribute_id` → `product.attribute.value.cotizador_qty`) y precio unitario en moneda de la matriz.
  - `_get_default_accessory_lines()`: el equipamiento estándar. `_check_accessory_selection()`: valida la selección (exclusión, inclusión, opción única).
  - `_get_or_create_variant()`, `_get_variant_description()`, `_sync_variant_code()`.
- **Reglas:** `exclusion` (:e), `inclusion` (:i / :it) y `choice` (:u, opción única: exactamente uno elegido, arranca el ESTANDAR; en el configurador OWL se muestra como radio con la diferencia de precio).
- **Alta en la cotización:** `sale.order._cotizador_add_configuration(config, acc_lines)` (configurador OWL, CRM y web). Secciones con `sale.order.line.cotizador_section` (maquina / equipamiento / accesorios / descuentos / usados): nunca identificar secciones por su texto.
- **Índice cacheado** `product.template._cotizador_config_index` (ormcache); `sembradora.config.rel` limpia la caché al crear/escribir/borrar.
- **Permisos:** `cotizador.group_cotizador_manager` (*Administrador del Configurador*); los servicios de Studio y Asistente de Precios llaman `check_configurator_manager()`.
- **Formulario web:** captcha (`ir.http._verify_request_recaptcha_token('cotizador_quote')` + `data-captcha`), token firmado `/cotizador/form_token` (tiempo mínimo y vencimiento), límites por hora con `crm.lead.cotizador_request_ip`.
- **README.md** tiene la lista de *Problemas conocidos*: mantenerla al día.
- **Tests:** `tests/` (unitarios, HTTP y tours). Los tours necesitan `websocket-client` en el entorno; si falta, Odoo los omite.

---

## 3. Estructura de Directorios

```text
cotizador/
├── __init__.py
├── __manifest__.py
├── controllers/
│   ├── __init__.py
│   └── main.py                 # Rutas de cotización web, honeypot, portal overrides
├── data/
│   └── product_category_data.xml
├── models/
│   ├── __init__.py
│   ├── accessory_rule.py
│   ├── bcra_service.py
│   ├── crm_lead_inherit.py      # Lead Kanban, sincronización de máquinas
│   ├── product_template_inherit.py # Lógica de combinaciones y precios base de ingeniería
│   ├── res_config_settings.py   # Modos eCommerce y modos de confirmación portal
│   ├── res_users_inherit.py     # Filtro de planes de pago por vendedor
│   └── sale_order_inherit.py    # Cascada financiera, USD, control de firma, sync CRM
├── report/
│   └── report_cotizacion_planes.xml
├── security/
│   └── ir.model.access.csv
├── static/
│   └── src/
│       ├── css/
│       │   └── cotizador_sequential_configurator.css # Estilos del stepper y chips
│       └── js/
│           └── cotizador_sequential_configurator.js  # Lógica secuencial asistida en web
└── views/
    ├── portal_templates.xml     # Vistas de cotización en portal, tarjetas y badges
    ├── res_config_settings_view.xml # Panel de ajustes de ventas
    ├── views.xml                # Formulario sale.order con cascada, botones y pestañas
    └── website_sale_templates.xml # Ficha de producto web con wizard secuencial
```

---

## 4. Reglas de Desarrollo y Buenas Prácticas

1. **Nunca romper el estándar de Odoo sin herencia limpia:** Utilizar `super()` en modelos (`create`, `write`, `_has_to_be_signed`) y controladores.
2. **Seguridad Web:**
   - Todo campo de texto que ingrese desde el frontend o se postee en el chatter debe sanitizarse con `escape()` de `markupsafe`.
   - Mantener el campo honeypot en formularios web para mitigar bots.
3. **Validación de XMLs:** Antes de hacer upgrade, validar que no existan etiquetas mal cerradas con un script rápido de Python usando `xml.etree.ElementTree`.
4. **Verificación de Procesos:** Asegurarse de que el servidor esté corriendo con la base de datos correcta (`-d test3`) y que el puerto 8069 esté respondiendo.
