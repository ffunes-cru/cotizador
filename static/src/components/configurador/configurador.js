/**
 * @file
 * Configurador visual de sembradoras (acción cliente `cotizador_configurator`).
 *
 * Se abre con el botón *Configurar* de la cotización (sale.order.action_open_config_wizard).
 * Tres pasos, todo en el navegador salvo las llamadas al servicio
 * `cotizador.configurator.service` (models/configurator_service.py):
 *   1. **Modelo**: catálogo de máquinas (get_initial_data).
 *   2. **Atributos**: árbol secuencial filtrado con la matriz completa en memoria
 *      (get_model_matrix); cuando queda una sola configuración se cargan sus accesorios.
 *   3. **Accesorios**: estándar preseleccionados, grupos de opción única como radio y reglas de
 *      exclusión / inclusión (get_config_accessories); confirm_configuration agrega las líneas.
 *
 * Las reglas se aplican acá para guiar al vendedor, pero el servidor vuelve a validar todo
 * (sembradora.config.rel._check_accessory_selection) y recalcula los precios.
 * Plantilla: configurador.xml (`cotizador.ConfiguradorTemplate`).
 */

import { registry } from "@web/core/registry";
import { Component, useState, onWillStart, onMounted, onPatched, onWillDestroy, useRef, markup } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

/**
 * Componente OWL del configurador.
 *
 * Estado principal (`this.state`): `step` ('select_model' | 'configure_attributes' |
 * 'select_accessories'), `selectedModel`, `attributes`, `configs`, `selectedValues`
 * (id de atributo → id de valor), `matchingConfig`, `accessories`, `selectedAccessories`
 * (id de línea → bool) y los totales `basePrice`, `accessoriesTotal`, `totalPrice`.
 */
export class CotizadorConfigurator extends Component {
    static template = "cotizador.ConfiguradorTemplate";

    /**
     * Inicializa servicios y estado, carga los datos iniciales y ajusta los textos que
     * desbordan al montar, actualizar y redimensionar.
     */
    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.action = useService("action");
        this.rootRef = useRef("root");

        // Obtener el ID de la orden de venta desde params o context
        this.orderId =
            (this.props.action && this.props.action.params && this.props.action.params.order_id) ||
            (this.props.action && this.props.action.context && this.props.action.context.active_id) ||
            (this.props.action && this.props.action.context && this.props.action.context.default_sale_order_id) ||
            null;

        this.state = useState({
            loading: true,
            saving: false,
            loadingMatrix: false,
            loadingAccessories: false,
            order: { id: null, name: "", partner_name: "" },
            modoSilencioso: false,

            // Pasos: 'select_model' | 'configure_attributes' | 'select_accessories'
            step: "select_model",

            // Paso 1: Modelos
            models: [],
            searchModel: "",
            selectedModel: null,

            // Paso 2: Atributos y Matriz
            attributes: [],
            configs: [],
            selectedValues: {}, // attr_id -> value_id
            matchingConfig: null,
            configFinalized: false,

            // Paso 3: Accesorios
            accessories: [],
            accessoryCategories: [],
            activeCategory: "all",
            searchAccessory: "",
            selectedAccessories: {}, // line_id -> boolean
            lockReasons: {}, // line_id -> array of strings

            // Totales
            basePrice: 0.0,
            accessoriesTotal: 0.0,
            totalPrice: 0.0,

            // Modal / Drawer de Resumen en Móviles
            showMobileSummary: false,
            showDescriptionCollapse: false,
        });

        onWillStart(async () => {
            await this.loadInitialData();
        });

        onMounted(() => {
            this.updateTextScroll();
            this._handleResize = () => this.updateTextScroll();
            window.addEventListener("resize", this._handleResize);
        });

        onPatched(() => {
            this.updateTextScroll();
        });

        onWillDestroy(() => {
            if (this._handleResize) {
                window.removeEventListener("resize", this._handleResize);
            }
        });
    }

    /**
     * Marca los textos `.o-scroll-text` que no entran en su caja para animarlos (CSS
     * `--scroll-offset`). Corre 50 ms después del render.
     */
    updateTextScroll() {
        if (!this.rootRef || !this.rootRef.el) return;
        setTimeout(() => {
            if (!this.rootRef || !this.rootRef.el) return;
            const scrollElements = this.rootRef.el.querySelectorAll(".o-scroll-text");
            for (const el of scrollElements) {
                const content = el.querySelector(".o-scroll-text-content") || el;
                const overflow = content.scrollWidth - el.clientWidth;
                if (overflow > 2) {
                    el.style.setProperty("--scroll-offset", `-${overflow + 14}px`);
                    el.classList.add("is-overflowing");
                } else {
                    el.classList.remove("is-overflowing");
                    el.style.removeProperty("--scroll-offset");
                }
            }
        }, 50);
    }

    /** Abre o cierra el resumen inferior en pantallas chicas. */
    toggleMobileSummary() {
        this.state.showMobileSummary = !this.state.showMobileSummary;
        if (this.state.showMobileSummary) {
            this.updateTextScroll();
        }
    }

    /** Cierra el resumen inferior en pantallas chicas. */
    closeMobileSummary() {
        this.state.showMobileSummary = false;
    }

    // --- Carga Inicial de Datos desde Odoo ---

    /**
     * Carga la cotización y el catálogo de máquinas. El id de la cotización viene de la
     * acción o, si se recargó la página, de la URL.
     * @returns {Promise<void>}
     */
    async loadInitialData() {
        this.state.loading = true;
        try {
            if (!this.orderId) {
                const urlParams = new URLSearchParams(window.location.search);
                this.orderId = urlParams.get("id") ? parseInt(urlParams.get("id")) : null;
            }

            if (!this.orderId) {
                this.notification.add(
                    _t("No se encontró una orden de venta activa para vincular la configuración."),
                    { type: "danger" }
                );
                return;
            }

            const data = await this.orm.call(
                "cotizador.configurator.service",
                "get_initial_data",
                [this.orderId]
            );
            this.state.order = data.order || {};
            this.state.models = data.models || [];
            this.state.modoSilencioso = Boolean(data.modo_silencioso);
        } catch (error) {
            console.error("Error al cargar datos iniciales del configurador:", error);
            this.notification.add(
                _t("Error al conectar con Odoo para cargar el catálogo."),
                { type: "danger" }
            );
        } finally {
            this.state.loading = false;
        }
    }

    // --- Formato de Moneda ---

    /**
     * Formatea un importe con el símbolo de la moneda de la cotización y formato es-AR.
     * @param amount Importe (number); vacío o NaN se muestra como 0,00.
     * @returns {string} P. ej. "USD $ 1.234,50".
     */
    formatCurrency(amount) {
        const symbol = this.state.order.currency_symbol || "$";
        if (amount === undefined || amount === null || isNaN(amount)) return `${symbol} 0,00`;
        return (
            `${symbol} ` +
            Number(amount).toLocaleString("es-AR", {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2,
            })
        );
    }

    // --- Filtros de Modelos ---

    /**
     * Máquinas que coinciden con la búsqueda (nombre o referencia).
     * @returns {Object[]}
     */
    get filteredModels() {
        const q = (this.state.searchModel || "").trim().toLowerCase();
        if (!q) return this.state.models;
        return this.state.models.filter(
            (m) =>
                m.name.toLowerCase().includes(q) ||
                (m.default_code && m.default_code.toLowerCase().includes(q))
        );
    }

    // --- Paso 1: Selección de Modelo ---

    /**
     * Paso 1 → 2: elige una máquina, reinicia la selección y carga su matriz.
     * @param model Máquina de `state.models` ({id, name, ...}).
     * @returns {Promise<void>}
     */
    async selectModel(model) {
        this.state.selectedModel = model;
        this.state.loadingMatrix = true;
        this.state.selectedValues = {};
        this.state.matchingConfig = null;
        this.state.configFinalized = false;
        this.state.accessories = [];
        this.state.selectedAccessories = {};
        this.state.basePrice = 0.0;
        this.state.accessoriesTotal = 0.0;
        this.state.totalPrice = 0.0;

        try {
            const matrixData = await this.orm.call(
                "cotizador.configurator.service",
                "get_model_matrix",
                [model.id, this.orderId]
            );

            if (!matrixData) {
                throw new Error("No se encontraron datos de configuración para este modelo.");
            }

            this.state.attributes = matrixData.attributes || [];
            this.state.configs = matrixData.configs || [];
            this.state.step = "configure_attributes";

            this._evaluateSequentialAttributes();
        } catch (error) {
            console.error("Error al cargar matriz del modelo:", error);
            this.notification.add(_t("Error al obtener la configuración del modelo."), {
                type: "danger",
            });
        } finally {
            this.state.loadingMatrix = false;
        }
    }

    /** Vuelve al paso 1 (conserva la selección hasta elegir otra máquina). */
    goToModelSelection() {
        this.state.step = "select_model";
    }

    /** Vuelve al paso 2 si hay una máquina elegida. */
    goToAttributes() {
        if (this.state.selectedModel) {
            this.state.step = "configure_attributes";
        }
    }

    /** Avanza al paso 3 si la combinación ya corresponde a una configuración. */
    goToAccessories() {
        if (this.state.configFinalized && this.state.matchingConfig) {
            this.state.step = "select_accessories";
        }
    }

    // --- Paso 2: Selección de Atributos y Matriz en Árbol Dinámico ---

    /**
     * Valores de un atributo del árbol con su disponibilidad, según lo elegido en los
     * atributos anteriores.
     * @param attrIndex Posición del atributo en `state.attributes`.
     * @returns {Object[]} Valores con `isAvailable`, `isSelected` y `matchCount` (configuraciones
     *          que quedan), ordenados con orden natural ("9" antes que "10").
     */
    getAvailableValuesForAttribute(attrIndex) {
        const currentAttr = this.state.attributes[attrIndex];
        if (!currentAttr) return [];

        let validConfigs = this.state.configs;
        for (let i = 0; i < attrIndex; i++) {
            const prevAttr = this.state.attributes[i];
            const chosenValId = this.state.selectedValues[prevAttr.id];
            if (chosenValId) {
                validConfigs = validConfigs.filter((c) => c.value_ids.includes(chosenValId));
            }
        }

        const validValIds = new Set();
        for (const cfg of validConfigs) {
            for (const vid of cfg.value_ids) {
                validValIds.add(vid);
            }
        }

        const results = currentAttr.values.map((val) => {
            const isAvailable = validValIds.has(val.id);
            const isSelected = this.state.selectedValues[currentAttr.id] === val.id;

            const matchCount = isAvailable
                ? validConfigs.filter((c) => c.value_ids.includes(val.id)).length
                : 0;

            return {
                ...val,
                isAvailable,
                isSelected,
                matchCount,
            };
        });

        // Ordenamiento natural numérico (ej: 9, 10, 12, 14, 16...)
        results.sort((a, b) =>
            a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: "base" })
        );

        return results;
    }

    /**
     * Posición del primer atributo sin elegir (o la cantidad de atributos si están todos).
     * @returns {number}
     */
    get activeTreeIndex() {
        const idx = this.state.attributes.findIndex((a) => !this.state.selectedValues[a.id]);
        return idx === -1 ? this.state.attributes.length : idx;
    }

    /**
     * Nombre del valor elegido para un atributo.
     * @param attrId Id del atributo.
     * @returns {string|null}
     */
    getSelectedValueName(attrId) {
        const valId = this.state.selectedValues[attrId];
        if (!valId) return null;
        const attr = this.state.attributes.find((a) => a.id === attrId);
        if (!attr) return null;
        const val = attr.values.find((v) => v.id === valId);
        return val ? val.name : null;
    }

    /**
     * Reabre un atributo del árbol: borra lo elegido desde esa posición en adelante.
     * @param attrIndex Posición del atributo en `state.attributes`.
     */
    editAttributeNode(attrIndex) {
        for (let i = attrIndex; i < this.state.attributes.length; i++) {
            delete this.state.selectedValues[this.state.attributes[i].id];
        }
        this._evaluateSequentialAttributes();
    }

    /**
     * Elige (o deselecciona, si ya estaba) un valor y borra lo elegido en los atributos
     * siguientes.
     * @param attrId Id del atributo.
     * @param valueId Id del valor.
     */
    selectAttributeValue(attrId, valueId) {
        const attrIndex = this.state.attributes.findIndex((a) => a.id === attrId);
        if (attrIndex === -1) return;

        if (this.state.selectedValues[attrId] === valueId) {
            delete this.state.selectedValues[attrId];
        } else {
            this.state.selectedValues[attrId] = valueId;
        }

        for (let i = attrIndex + 1; i < this.state.attributes.length; i++) {
            delete this.state.selectedValues[this.state.attributes[i].id];
        }

        this._evaluateSequentialAttributes();
    }

    /**
     * Autocompleta los atributos que tienen un único valor posible y, si la combinación
     * completa corresponde a una sola configuración, la fija y carga sus accesorios; si no,
     * limpia configuración, precios y accesorios.
     * @returns {Promise<void>}
     */
    async _evaluateSequentialAttributes() {
        let changed = false;

        for (let i = 0; i < this.state.attributes.length; i++) {
            const attr = this.state.attributes[i];
            const currentSelection = this.state.selectedValues[attr.id];

            if (!currentSelection) {
                const availableVals = this.getAvailableValuesForAttribute(i).filter(
                    (v) => v.isAvailable
                );
                if (availableVals.length === 1) {
                    this.state.selectedValues[attr.id] = availableVals[0].id;
                    changed = true;
                } else {
                    break;
                }
            }
        }

        let validConfigs = this.state.configs;
        const selectedValIds = Object.values(this.state.selectedValues);

        for (const vid of selectedValIds) {
            validConfigs = validConfigs.filter((c) => c.value_ids.includes(vid));
        }

        const allAttrsSelected = this.state.attributes.every(
            (a) => this.state.selectedValues[a.id]
        );

        if (allAttrsSelected && validConfigs.length === 1) {
            const finalConfig = validConfigs[0];
            this.state.configFinalized = true;
            this.state.matchingConfig = finalConfig;
            this.state.basePrice = finalConfig.price;
            this.state.totalPrice = this.state.basePrice + this.state.accessoriesTotal;

            await this.loadAccessories(finalConfig.id);
        } else {
            this.state.configFinalized = false;
            this.state.matchingConfig = null;
            this.state.basePrice = 0.0;
            this.state.totalPrice = 0.0;
            this.state.accessories = [];
            this.state.selectedAccessories = {};
        }

        if (changed && !this.state.configFinalized) {
            this._evaluateSequentialAttributes();
        }
    }

    // --- Paso 3: Accesorios Compatibles ---

    /**
     * Carga los accesorios de la configuración, preselecciona el equipamiento estándar
     * y aplica las reglas.
     * @param configId Id de la configuración (sembradora.config.rel).
     * @returns {Promise<void>}
     */
    async loadAccessories(configId) {
        this.state.loadingAccessories = true;
        try {
            const data = await this.orm.call(
                "cotizador.configurator.service",
                "get_config_accessories",
                [configId, this.orderId]
            );

            this.state.accessories = (data && data.accessories) || [];
            if (data && data.description && this.state.matchingConfig) {
                this.state.matchingConfig.description = data.description;
            }
            // Equipamiento estándar: llega preseleccionado desde el servidor
            this.state.selectedAccessories = Object.fromEntries(
                this.state.accessories.map((acc) => [acc.line_id, Boolean(acc.selected)])
            );

            const cats = new Set();
            for (const acc of this.state.accessories) {
                if (acc.category_name) {
                    cats.add(acc.category_name);
                }
            }
            this.state.accessoryCategories = Array.from(cats);
            this.state.activeCategory = "all";

            this._evaluateAccessoryRules();
            this._recalculateAccessoriesTotal();
        } catch (error) {
            console.error("Error al cargar accesorios:", error);
            this.notification.add(_t("Error al obtener accesorios de la configuración."), {
                type: "danger",
            });
        } finally {
            this.state.loadingAccessories = false;
        }
    }

    /**
     * Grupos de opción única, con la opción estándar primero.
     * @returns {Object[]} [{id, name, options}]
     */
    get choiceGroups() {
        const groups = new Map();
        for (const acc of this.state.accessories) {
            if (!acc.choice_group_id) continue;
            if (!groups.has(acc.choice_group_id)) {
                groups.set(acc.choice_group_id, { id: acc.choice_group_id, name: acc.choice_group_name, options: [] });
            }
            groups.get(acc.choice_group_id).options.push(acc);
        }
        for (const group of groups.values()) {
            group.options.sort((a, b) => Number(b.is_standard) - Number(a.is_standard));
        }
        return [...groups.values()];
    }

    /**
     * Diferencia de precio de una opción respecto de la estándar de su grupo.
     * @param delta Diferencia (number).
     * @returns {string} "+ USD $ 30,00", "− USD $ 20,00" o "Sin diferencia".
     */
    formatDelta(delta) {
        if (!delta) return _t("Sin diferencia");
        return `${delta > 0 ? "+" : "−"} ${this.formatCurrency(Math.abs(delta))}`;
    }

    /**
     * Opción única: elige `acc` y deselecciona las demás opciones de su grupo. Una opción
     * bloqueada por una exclusión (otro accesorio elegido del mismo grupo de exclusión) no se
     * puede elegir; la elegida nunca se bloquea, así que el grupo siempre tiene una.
     * @param acc Accesorio miembro de un grupo (`choice_group_id`).
     */
    selectChoice(acc) {
        if (acc.is_locked) return;
        for (const other of this.state.accessories) {
            if (other.choice_group_id === acc.choice_group_id) {
                this.state.selectedAccessories[other.line_id] = other.line_id === acc.line_id;
            }
        }
        this._evaluateAccessoryRules();
        this._recalculateAccessoriesTotal();
    }

    /**
     * Accesorios sueltos (fuera de los grupos de opción única) filtrados por categoría y
     * búsqueda.
     * @returns {Object[]}
     */
    get filteredAccessories() {
        // Los grupos de opción única se muestran aparte (choiceGroups)
        let list = this.state.accessories.filter((a) => !a.choice_group_id);
        if (this.state.activeCategory !== "all") {
            list = list.filter((a) => a.category_name === this.state.activeCategory);
        }
        const q = (this.state.searchAccessory || "").trim().toLowerCase();
        if (q) {
            list = list.filter(
                (a) =>
                    a.product_name.toLowerCase().includes(q) ||
                    (a.default_code && a.default_code.toLowerCase().includes(q))
            );
        }
        return list;
    }

    /**
     * Filtra los accesorios por categoría.
     * @param cat Nombre de la categoría, o "all".
     */
    setActiveCategory(cat) {
        this.state.activeCategory = cat;
    }

    /**
     * Agrega o quita un accesorio (si no está bloqueado por una regla). En un grupo de
     * opción única equivale a elegirlo.
     * @param lineId Id de la línea de accesorio.
     */
    toggleAccessory(lineId) {
        const acc = this.state.accessories.find((a) => a.line_id === lineId);
        if (!acc || acc.is_locked) return;
        if (acc.choice_group_id) {
            return this.selectChoice(acc);
        }

        this.state.selectedAccessories[lineId] = !this.state.selectedAccessories[lineId];

        this._evaluateAccessoryRules();
        this._recalculateAccessoriesTotal();
    }

    /**
     * Aplica las reglas de exclusión e inclusión a la selección actual.
     *
     * - Exclusión: con un miembro elegido, los demás del grupo quedan bloqueados. Vale también
     *   para las opciones de un grupo de opción única que están en una exclusión: la alternativa
     *   bloqueada no se puede elegir (selectChoice).
     * - Inclusión: sin habilitante elegido, los demás miembros quedan bloqueados y se deseleccionan.
     * - Opción única: se maneja en selectChoice (siempre hay una elegida).
     *
     * Deja en cada accesorio `is_locked` y `lock_reason`.
     */
    _evaluateAccessoryRules() {
        const ruleState = {};

        for (const acc of this.state.accessories) {
            if (!acc.rules || !acc.rules.length) continue;
            for (const rule of acc.rules) {
                if (rule.rule_type === "choice") continue; // ver selectChoice
                const rid = rule.id;
                if (!ruleState[rid]) {
                    ruleState[rid] = {
                        rule,
                        selected_lines: [],
                        all_lines: [],
                        triggers: [],
                        non_triggers: [],
                    };
                }
                ruleState[rid].all_lines.push(acc);
                if (this.state.selectedAccessories[acc.line_id]) {
                    ruleState[rid].selected_lines.push(acc);
                }
                if (acc.is_trigger) {
                    ruleState[rid].triggers.push(acc);
                } else {
                    ruleState[rid].non_triggers.push(acc);
                }
            }
        }

        const lockReasons = {};

        for (const [rid, state] of Object.entries(ruleState)) {
            const rule = state.rule;

            if (rule.rule_type === "exclusion") {
                if (state.selected_lines.length > 0) {
                    for (const acc of state.all_lines) {
                        if (!this.state.selectedAccessories[acc.line_id]) {
                            if (!lockReasons[acc.line_id]) lockReasons[acc.line_id] = [];
                            lockReasons[acc.line_id].push(`Excluido por: ${rule.name}`);
                        }
                    }
                }
            } else if (rule.rule_type === "inclusion") {
                const triggerSelected = state.triggers.some(
                    (t) => this.state.selectedAccessories[t.line_id]
                );
                if (!triggerSelected) {
                    for (const acc of state.non_triggers) {
                        if (!lockReasons[acc.line_id]) lockReasons[acc.line_id] = [];
                        lockReasons[acc.line_id].push(`Requiere seleccionar: ${rule.name}`);
                        if (this.state.selectedAccessories[acc.line_id]) {
                            this.state.selectedAccessories[acc.line_id] = false;
                        }
                    }
                }
            }
        }

        for (const acc of this.state.accessories) {
            const reasons = lockReasons[acc.line_id] || [];
            acc.is_locked = reasons.length > 0;
            acc.lock_reason = reasons.join(" • ");
        }

        this.state.lockReasons = lockReasons;
    }

    /** Recalcula el total de accesorios elegidos y el total general. */
    _recalculateAccessoriesTotal() {
        let total = 0.0;
        for (const acc of this.state.accessories) {
            if (this.state.selectedAccessories[acc.line_id]) {
                total += acc.subtotal;
            }
        }
        this.state.accessoriesTotal = total;
        this.state.totalPrice = (this.state.basePrice || 0.0) + total;
    }

    /**
     * Accesorios elegidos.
     * @returns {Object[]}
     */
    get selectedAccessoriesList() {
        return this.state.accessories.filter(
            (a) => this.state.selectedAccessories[a.line_id]
        );
    }

    /**
     * Atributos elegidos, en orden, para el resumen.
     * @returns {Object[]} [{attr_id, attr_name, value_id, value_name}]
     */
    get selectedAttributesSummary() {
        const summary = [];
        for (const attr of this.state.attributes) {
            const valId = this.state.selectedValues[attr.id];
            if (valId) {
                const val = attr.values.find((v) => v.id === valId);
                if (val) {
                    summary.push({
                        attr_id: attr.id,
                        attr_name: attr.name,
                        value_id: val.id,
                        value_name: val.name,
                    });
                }
            }
        }
        return summary;
    }

    /**
     * Descripción HTML de la configuración elegida (ya sanitizada por el servidor).
     * @returns {Markup|null}
     */
    get activeDescription() {
        if (this.state.matchingConfig && this.state.matchingConfig.description) {
            return markup(this.state.matchingConfig.description);
        }
        return null;
    }

    /** Expande o contrae la descripción técnica. */
    toggleDescriptionCollapse() {
        this.state.showDescriptionCollapse = !this.state.showDescriptionCollapse;
    }

    // --- Confirmación y Guardado en Odoo sale.order ---

    /**
     * Envía la configuración y las líneas de accesorio elegidas; el servidor valida,
     * calcula precios y agrega las líneas a la cotización. Al terminar vuelve a la cotización.
     * @returns {Promise<void>}
     */
    async confirmConfiguration() {
        if (!this.state.matchingConfig) {
            this.notification.add(
                _t("Debe completar la configuración de la sembradora antes de confirmar."),
                { type: "warning" }
            );
            return;
        }

        this.state.saving = true;
        try {
            // Precios y cantidades se recalculan en el servidor: solo enviamos las líneas elegidas
            const result = await this.orm.call(
                "cotizador.configurator.service",
                "confirm_configuration",
                [],
                {
                    order_id: this.orderId,
                    config_id: this.state.matchingConfig.id,
                    selected_line_ids: this.selectedAccessoriesList.map((acc) => acc.line_id),
                }
            );

            if (result.success) {
                this.notification.add(
                    _t("¡Sembradora y accesorios añadidos con éxito a la cotización!"),
                    { type: "success" }
                );
                await this.closeAndReturn();
            }
        } catch (error) {
            console.error("Error al confirmar configuración en Odoo:", error);
            this.notification.add(
                error?.data?.message ||
                    _t("Ocurrió un error al guardar las líneas en la cotización de Odoo."),
                { type: "danger" }
            );
        } finally {
            this.state.saving = false;
        }
    }

    /**
     * Vuelve al formulario de la cotización (o a la página anterior si no hay cotización).
     * @returns {Promise<void>}
     */
    async closeAndReturn() {
        if (this.orderId) {
            await this.action.doAction({
                type: "ir.actions.act_window",
                res_model: "sale.order",
                res_id: this.orderId,
                views: [[false, "form"]],
                target: "current",
            });
        } else {
            window.history.back();
        }
    }
}

registry.category("actions").add("cotizador_configurator", CotizadorConfigurator);
