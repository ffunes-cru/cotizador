/** @odoo-module **/

import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";

/**
 * Formulario "Solicitar Cotización": pide al servidor un token firmado con la hora de
 * apertura de la página. El servidor rechaza envíos sin token, con token vencido o enviados
 * más rápido de lo que tarda una persona (ver controllers/main.py::_check_form_token).
 */
export class CotizadorQuoteForm extends Interaction {
    static selector = "form[data-cotizador-quote-form]";

    async willStart() {
        this.token = await this.waitFor(rpc("/cotizador/form_token"));
    }

    start() {
        this.el.querySelector("input[name='cotizador_form_token']").value = this.token;
    }
}

registry.category("public.interactions").add("cotizador.quote_form", CotizadorQuoteForm);
