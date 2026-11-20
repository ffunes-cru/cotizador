# Puesta en marcha y ajustes

Guía del **Administrador del Configurador**: dejar el cotizador listo para cotizar y ajustar cómo se comporta.

## Puesta en marcha

1. **Monedas**: activar las monedas de la matriz (por ejemplo USD) y cargar sus tasas, aunque la compañía
   trabaje en otra (por ejemplo ARS). *Contabilidad › Configuración › Monedas*.
2. **Lista de precios** en la moneda en que se cotiza, y elegirla como *Lista de Precios de Cotizaciones*
   (abajo).
3. **Permisos**: dar *Administrador del Configurador* a quien mantiene la matriz (*Ajustes › Usuarios*,
   sección *Configurador de Sembradoras*), y armar los concesionarios y los niveles (abajo).
4. **Importar la matriz**: [Mantener la matriz](matriz.md).
5. **Planes de pago**: cargar las plantillas (*Plantillas Planes de Pago*).
6. **Tienda**: publicar las máquinas, configurar el captcha (*Ajustes › Sitio web*) y elegir el modo de la
   tienda.

## Niveles de usuario

Qué ve y edita cada nivel: [Guía de uso › Niveles de usuario](index.md#niveles-de-usuario).

1. **Concesionarios**: uno por *equipo de ventas* (*CRM › Configuración › Equipos de ventas*, o *Ventas ›
   Configuración › Equipos de ventas*). En cada uno:
   - **Líder del equipo**: el usuario del concesionario;
   - **Miembros**: sus vendedores;
   - **Supervisor de Zona**: el supervisor de la zona del concesionario. Los equipos con el mismo supervisor
     forman su zona; la lista de equipos se puede agrupar por supervisor.
2. **Nivel de cada usuario** (*Ajustes › Usuarios*, sección *Ventas*):

   | Nivel | *Ventas* | *Nivel Comercial (Cotizador)* |
   |---|---|---|
   | Vendedor | Usuario: solo sus documentos | *Vendedor (solo lo suyo)*, sin elegir otro |
   | Líder de concesionario | Usuario: solo sus documentos | Líder de Concesionario |
   | Supervisor de zona | Usuario: solo sus documentos | Supervisor de Zona |
   | Gerencia | Usuario: todos los documentos (o Administrador) | *Vendedor (solo lo suyo)*, sin elegir otro |

Un líder ve lo de todos los equipos que lidera, y un supervisor, lo de todos los que supervisa: no hace falta
un usuario por zona.

3. **Concesionarios (usuarios externos):** al invitar a alguien con un correo que no es de Crucianelli, su usuario
   queda como *Usuario externo (concesionario)* (*Ajustes › Usuarios*, *Origen del Usuario*). Un externo ve:
   - solo los clientes de su concesionario (los que cargan él o sus compañeros, y los de las cotizaciones de su
     concesionario), no la base de clientes de Crucianelli ni los de otros concesionarios;
   - ninguna cuenta bancaria;
   - nada sin vendedor que no sea de su concesionario (por ejemplo, las solicitudes de la tienda web).

   Al cargar un cliente, el formulario le pide solo razón social, CUIT, correo, teléfono, localidad y provincia, y no
   lo deja repetir un CUIT de su concesionario. Si el mismo cliente trabaja con dos concesionarios, cada uno tiene su
   ficha: para verlo unificado, agrupar el *Análisis de ventas* por **CUIT**.

   Para que un concesionario vea un cliente de la base: cotizarle con ese cliente y ese concesionario, o agregar el
   concesionario en el cliente (pestaña *Ventas y compras*, *Concesionarios*). Los dominios del personal se
   configuran en el parámetro del sistema `cotizador.dominios_internos` (por defecto `crucianelli.com`, separados por
   coma). Detalle: [Seguridad › Usuarios externos](../seguridad.md#usuarios-externos-concesionarios).

## Ajustes

*Ajustes › Ventas › Cotizador de Sembradoras*.

| Ajuste | Qué controla |
|---|---|
| **Lista de Precios de Cotizaciones** | Lista, y por lo tanto moneda, de las cotizaciones de máquinas: las que nacen del CRM y de la web, y las creadas a mano al configurar la primera máquina. Vacía: la lista habitual del cliente. |
| **Impuesto de Maquinaria** | Impuesto de máquinas y accesorios cotizados con el configurador. Vacío: el de cada producto. |
| **Plan de Pago Obligatorio** | No deja confirmar una cotización sin plan de pago. |
| **Modo Silencioso** | El configurador del vendedor muestra solo el subtotal de los accesorios por cantidad, sin el precio por unidad. |
| **Modo de la Tienda Online** | *Solicitar Cotización* (sin pago online, todo va al CRM) o *Comercio Electrónico Estándar* (carrito para lo que no es máquina). Ver [Tienda](tienda.md#modo-de-la-tienda). |
| **Aceptación de Cotizaciones en el Portal** | Modo con que nacen las cotizaciones: *Habilitado por el Vendedor*, *Solo el Vendedor* o *Estándar Odoo*. Ver [Cotizar › Aceptación](cotizar.md#5-aceptación-del-cliente). |
| **Condiciones Generales Predeterminadas** | Texto del pie de las cotizaciones nuevas. |
| **Protección del Formulario de Solicitud Web** | Solicitudes por IP y por email o teléfono por hora (0 = sin límite) y segundos mínimos para completar el formulario. Avisa si falta configurar el captcha. |

En cada producto:

| Dato | Dónde | Qué controla |
|---|---|---|
| *Moneda del Cotizador* | Ficha de máquinas y accesorios | Moneda de sus precios de matriz. La fija el importador. |
| *Modelo de Máquina* | Ficha de accesorios | Máquina a la que pertenece el accesorio. |
| *Atributo de Cantidad* | Categoría de producto | Los accesorios de la categoría van por cantidad, según ese atributo. |
| *Cantidad (Cotizador)* | Valor de atributo | El número de ese valor (`16 Líneas` → 16). |

## Problemas frecuentes

| Qué pasa | Por qué | Qué hacer |
|---|---|---|
| Las cotizaciones salen en la moneda de la compañía y no en la de la matriz | No hay *Lista de Precios de Cotizaciones*, o la cotización ya tenía productos. | Elegir la lista en los ajustes; en una cotización ya cargada, cambiar la lista y *Actualizar precios*. |
| No aparece una moneda para elegir | Está inactiva. | Activarla y cargar su tasa. |
| El análisis dice "está en USD, pero la moneda de los precios elegida es …" | Moneda equivocada en el importador. | Elegir la moneda de la planilla. |
| "pertenece al modelo … y no puede usarse en una configuración de …" | Se usó el accesorio de otra máquina. | Cada máquina tiene sus accesorios: crear o importar el de esta. |
| "The number of variants to generate is above allowed limit" al importar | La máquina tiene más de 1000 configuraciones. | Pedir que suban el parámetro `product.dynamic_variant_limit` ([Operación técnica](../operacion.md)). |
| Todas las solicitudes web dan "espere" | El servidor no ve la IP real de los visitantes. | Problema de configuración del servidor ([Operación técnica](../operacion.md#problemas-comunes)). |
| La consulta BCRA da error | La API del BCRA no responde. | Reintentar más tarde. |
