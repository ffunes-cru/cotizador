/** @odoo-module **/

import { registry } from "@web/core/registry";

// Configurador visual: el estándar del grupo de opción única arranca elegido, elegir una
// alternativa lo reemplaza y la cotización queda con las secciones del cotizador.
registry.category("web_tour.tours").add("cotizador_configurator_tour", {
    steps: () => [
        { trigger: ".o_form_view button[name='action_open_config_wizard']", run: "click" },
        { trigger: ".model-card:contains('Pionera')", run: "click" },
        { trigger: ".tree-branch-pill:contains('16 Lineas')", run: "click" },
        { trigger: "button:contains('Paso Siguiente: Accesorios')", run: "click" },
        { trigger: ".o_cotizador_choice_option:contains('Kit Fino') input:checked" },
        { trigger: ".o_cotizador_choice_option:contains('Kit Grueso'):contains('+ USD')" },
        { trigger: ".o_cotizador_choice_option:contains('Kit Grueso') input", run: "click" },
        { trigger: ".o_cotizador_choice_option:contains('Kit Fino') input:not(:checked)" },
        { trigger: ".o_cotizador_choice_option:contains('Kit Grueso') input:checked" },
        { trigger: ".cotizador-summary-panel button:contains('Añadir a la Cotización'):enabled", run: "click" },
        { trigger: ".o_section_and_note_list_view tr.o_is_line_section:nth-child(1)" },
        { trigger: ".o_field_product_label_section_and_note_cell:contains('Kit Grueso')" },
    ],
});

// Tienda: configurar la máquina paso a paso y solicitar cotización como visitante anónimo.
// La página de confirmación solo aparece si el JS cargó el token firmado del formulario.
registry.category("web_tour.tours").add("cotizador_website_quote_tour", {
    steps: () => [
        { trigger: ".cotizador-option-card:contains('16 Lineas')", run: "click" },
        { trigger: ".cotizador-option-card:contains('52 cm')", run: "click" },
        { trigger: "#btn_solicitar_cotizacion:enabled", run: "click" },
        { trigger: "#modal_solicitar_cotizacion input[name='contact_name']", run: "edit Visitante Tour" },
        { trigger: "#modal_solicitar_cotizacion input[name='email']", run: "edit tour@example.com" },
        { trigger: "#modal_solicitar_cotizacion input[name='phone']", run: "edit 3415551234" },
        { trigger: "#modal_solicitar_cotizacion button[type='submit']", run: "click", expectUnloadPage: true },
        { trigger: "h1:contains('Solicitud de cotización recibida')" },
    ],
});
