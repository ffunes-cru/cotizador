/**
 * @file
 * Formulario *Solicitar Cotización* de la tienda: completa el token anti-bots.
 *
 * Al cargar la página pide a `/cotizador/form_token` la hora de apertura firmada y la guarda en
 * el campo oculto `cotizador_form_token`. El servidor rechaza envíos sin token, con token
 * vencido o enviados más rápido de lo que tarda una persona
 * (controllers/main.py, CotizadorWebsiteController._check_form_token).
 */

import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";

/** Interacción del sitio web sobre `form[data-cotizador-quote-form]`. */
export class CotizadorQuoteForm extends Interaction {
    static selector = "form[data-cotizador-quote-form]";

    /**
     * Pide el token firmado antes de activar el formulario.
     * @returns {Promise<void>}
     */
    async willStart() {
        this.token = await this.waitFor(rpc("/cotizador/form_token"));
    }

    /** Copia el token al campo oculto del formulario. */
    start() {
        this.el.querySelector("input[name='cotizador_form_token']").value = this.token;
    }
}

registry.category("public.interactions").add("cotizador.quote_form", CotizadorQuoteForm);
