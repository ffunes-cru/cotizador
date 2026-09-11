/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useState, onWillStart, onWillDestroy } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { offlineDB } from "./offline_db";

export class CotizadorConfigurator extends Component {
    static template = "cotizador.ConfiguradorTemplate";

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.action = useService("action");

        // Obtener el ID de la orden de venta desde params o context (si viene desde sale.order)
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

            // Conectividad y Modo Offline
            isOnline: navigator.onLine,
            isOfflineMode: !navigator.onLine || !this.orderId,
            syncingCatalog: false,
            syncingQuotes: false,
            lastSyncDate: null,
            pendingQuotesCount: 0,
            showSyncCenter: false,
            offlineQuotesList: [],

            // Gestión de Cliente en Modo Offline / Standalone
            partnerQuery: "",
            cachedPartners: [],
            selectedPartner: null,
            isCreatingNewPartner: false,
            clientName: "",
            clientVat: "",
            clientPhone: "",
            clientEmail: "",

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

            // Diálogo de Confirmación de Cotización Guardada Offline
            showOfflineSavedModal: false,
            lastSavedQuote: null,
        });

        // Eventos de conectividad en vivo
        this._handleOnline = () => this._onConnectivityChange(true);
        this._handleOffline = () => this._onConnectivityChange(false);
        window.addEventListener("online", this._handleOnline);
        window.addEventListener("offline", this._handleOffline);

        onWillDestroy(() => {
            window.removeEventListener("online", this._handleOnline);
            window.removeEventListener("offline", this._handleOffline);
        });

        onWillStart(async () => {
            await this.loadInitialData();
            await this.checkOfflineStatus();
        });
    }

    // --- Control de Conectividad ---

    async _onConnectivityChange(online) {
        this.state.isOnline = online;
        if (online) {
            this.notification.add(_t("Conexión a internet restablecida."), { type: "info" });
            await this.checkOfflineStatus();
        } else {
            this.state.isOfflineMode = true;
            this.notification.add(_t("Sin conexión. Conmutando a modo offline local."), { type: "warning" });
        }
    }

    async checkOfflineStatus() {
        try {
            const lastSync = await offlineDB.getLastSyncDate();
            this.state.lastSyncDate = lastSync ? new Date(lastSync).toLocaleString("es-AR") : null;
            const pending = await offlineDB.getPendingQuotes();
            this.state.pendingQuotesCount = pending.length;
            this.state.offlineQuotesList = await offlineDB.getAllQuotes();
            this.state.cachedPartners = await offlineDB.searchPartners("");
        } catch (e) {
            console.error("Error al consultar IndexedDB:", e);
        }
    }

    toggleMobileSummary() {
        this.state.showMobileSummary = !this.state.showMobileSummary;
    }

    closeMobileSummary() {
        this.state.showMobileSummary = false;
    }

    toggleSyncCenter() {
        this.state.showSyncCenter = !this.state.showSyncCenter;
        if (this.state.showSyncCenter) {
            this.checkOfflineStatus();
        }
    }

    // --- Carga Inicial (Híbrida Online / Offline) ---

    async loadInitialData() {
        this.state.loading = true;
        try {
            if (!this.orderId) {
                const urlParams = new URLSearchParams(window.location.search);
                this.orderId = urlParams.get("id") ? parseInt(urlParams.get("id")) : null;
            }

            // Si hay conexión y viene con orden de venta, cargamos normalmente desde Odoo
            if (this.orderId && this.state.isOnline) {
                const data = await this.orm.call(
                    "cotizador.configurator.service",
                    "get_initial_data",
                    [this.orderId]
                );
                this.state.order = data.order || {};
                this.state.models = data.models || [];
                this.state.isOfflineMode = false;

                // Si nunca sincronizó el catálogo local, descargarlo de fondo
                const hasLocalCatalog = await offlineDB.getCatalogPackage();
                if (!hasLocalCatalog) {
                    this.downloadOfflineCatalog(false);
                }
            } else {
                // Modo Offline o Cotización sin orden previa abierta
                this.state.isOfflineMode = true;
                await this.loadFromLocalIndexedDB();
            }
        } catch (error) {
            console.warn("Fallo en RPC online, conmutando a catálogo local:", error);
            this.state.isOfflineMode = true;
            await this.loadFromLocalIndexedDB();
        } finally {
            this.state.loading = false;
        }
    }

    async loadFromLocalIndexedDB() {
        const pkg = await offlineDB.getCatalogPackage();
        if (pkg && pkg.models && pkg.models.length > 0) {
            this.state.models = pkg.models;
            this.cachedPackage = pkg;
        } else {
            // Si está online pero no tenía datos, intentamos descargarlos
            if (this.state.isOnline) {
                await this.downloadOfflineCatalog(true);
            } else {
                this.notification.add(
                    _t("No hay catálogo descargado en este dispositivo. Conéctese una vez a internet para descargarlo."),
                    { type: "danger" }
                );
            }
        }
    }

    // --- Sincronización de Catálogo Offline ---

    async downloadOfflineCatalog(notify = true) {
        if (!this.state.isOnline) {
            this.notification.add(_t("Se requiere conexión a internet para actualizar el catálogo."), {
                type: "warning",
            });
            return;
        }

        this.state.syncingCatalog = true;
        try {
            const pkg = await this.orm.call(
                "cotizador.configurator.service",
                "get_full_offline_package",
                []
            );

            await offlineDB.saveCatalogPackage(pkg);
            await offlineDB.savePartners(pkg.partners || []);
            this.cachedPackage = pkg;
            this.state.models = pkg.models || [];

            await this.checkOfflineStatus();

            if (notify) {
                this.notification.add(
                    _t("Catálogo offline y lista de contactos actualizados en este dispositivo."),
                    { type: "success" }
                );
            }
        } catch (error) {
            console.error("Error al descargar paquete offline:", error);
            if (notify) {
                this.notification.add(_t("Error al descargar el catálogo offline."), { type: "danger" });
            }
        } finally {
            this.state.syncingCatalog = false;
        }
    }

    // --- Búsqueda y Selección de Clientes en Modo Offline ---

    setCreateNewPartner(isNew) {
        this.state.isCreatingNewPartner = isNew;
        if (isNew) {
            this.clearSelectedPartner();
        }
    }

    async onSearchPartnerInput(ev) {
        const query = ev.target.value;
        this.state.partnerQuery = query;
        this.state.cachedPartners = await offlineDB.searchPartners(query);
    }

    selectPartner(partner) {
        this.state.selectedPartner = partner;
        this.state.clientName = partner.name;
        this.state.clientVat = partner.vat || "";
        this.state.clientPhone = partner.phone || "";
        this.state.clientEmail = partner.email || "";
        this.state.partnerQuery = "";
        this.state.cachedPartners = [];
        this.state.isCreatingNewPartner = false;
    }

    async clearSelectedPartner() {
        this.state.selectedPartner = null;
        this.state.clientName = "";
        this.state.clientVat = "";
        this.state.clientPhone = "";
        this.state.clientEmail = "";
        this.state.partnerQuery = "";
        this.state.cachedPartners = await offlineDB.searchPartners("");
    }

    // --- Formato de Moneda ---

    formatCurrency(amount) {
        if (amount === undefined || amount === null || isNaN(amount)) return "$ 0,00";
        return (
            "$ " +
            Number(amount).toLocaleString("es-AR", {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2,
            })
        );
    }

    // --- Filtros de Modelos ---

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
            let matrixData = null;

            // Si estamos en modo offline o sin red, leemos del paquete local
            if (this.state.isOfflineMode || !this.state.isOnline) {
                if (!this.cachedPackage) {
                    this.cachedPackage = await offlineDB.getCatalogPackage();
                }
                matrixData =
                    this.cachedPackage &&
                    this.cachedPackage.matrix_by_model &&
                    this.cachedPackage.matrix_by_model[model.id];
            } else {
                matrixData = await this.orm.call(
                    "cotizador.configurator.service",
                    "get_model_matrix",
                    [model.id]
                );
            }

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

    goToModelSelection() {
        this.state.step = "select_model";
    }

    goToAttributes() {
        if (this.state.selectedModel) {
            this.state.step = "configure_attributes";
        }
    }

    goToAccessories() {
        if (this.state.configFinalized && this.state.matchingConfig) {
            this.state.step = "select_accessories";
        }
    }

    // --- Paso 2: Selección de Atributos y Matriz ---

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

        // Ordenamiento natural (ej: 9, 10, 12, 14... en vez de orden desordenado)
        results.sort((a, b) =>
            a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: "base" })
        );

        return results;
    }

    get activeTreeIndex() {
        const idx = this.state.attributes.findIndex((a) => !this.state.selectedValues[a.id]);
        return idx === -1 ? this.state.attributes.length : idx;
    }

    getSelectedValueName(attrId) {
        const valId = this.state.selectedValues[attrId];
        if (!valId) return null;
        const attr = this.state.attributes.find((a) => a.id === attrId);
        if (!attr) return null;
        const val = attr.values.find((v) => v.id === valId);
        return val ? val.name : null;
    }

    editAttributeNode(attrIndex) {
        for (let i = attrIndex; i < this.state.attributes.length; i++) {
            delete this.state.selectedValues[this.state.attributes[i].id];
        }
        this._evaluateSequentialAttributes();
    }

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

    // --- Paso 3: Accesorios ---

    async loadAccessories(configId) {
        this.state.loadingAccessories = true;
        try {
            let data = null;

            if (this.state.isOfflineMode || !this.state.isOnline) {
                if (!this.cachedPackage) {
                    this.cachedPackage = await offlineDB.getCatalogPackage();
                }
                data =
                    this.cachedPackage &&
                    this.cachedPackage.accessories_by_config &&
                    this.cachedPackage.accessories_by_config[configId];
            } else {
                data = await this.orm.call(
                    "cotizador.configurator.service",
                    "get_config_accessories",
                    [configId]
                );
            }

            this.state.accessories = (data && data.accessories) || [];
            this.state.selectedAccessories = {};

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

    get filteredAccessories() {
        let list = this.state.accessories;
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

    setActiveCategory(cat) {
        this.state.activeCategory = cat;
    }

    toggleAccessory(lineId) {
        const acc = this.state.accessories.find((a) => a.line_id === lineId);
        if (!acc || acc.is_locked) return;

        this.state.selectedAccessories[lineId] = !this.state.selectedAccessories[lineId];

        this._evaluateAccessoryRules();
        this._recalculateAccessoriesTotal();
    }

    _evaluateAccessoryRules() {
        const ruleState = {};

        for (const acc of this.state.accessories) {
            if (!acc.rules || !acc.rules.length) continue;
            for (const rule of acc.rules) {
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

    get selectedAccessoriesList() {
        return this.state.accessories.filter(
            (a) => this.state.selectedAccessories[a.line_id]
        );
    }

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

    // --- Confirmación y Guardado (Online u Offline) ---

    async confirmConfiguration() {
        if (!this.state.matchingConfig) {
            this.notification.add(
                _t("Debe completar la configuración de la sembradora antes de confirmar."),
                { type: "warning" }
            );
            return;
        }

        // Si estamos en modo offline o sin orden abierta, guardamos en IndexedDB
        if (this.state.isOfflineMode || !this.orderId) {
            await this.saveQuoteOffline();
            return;
        }

        // Modo Online tradicional con orden de venta activa en Odoo
        this.state.saving = true;
        try {
            const selectedAccsData = this.selectedAccessoriesList.map((acc) => ({
                product_id: acc.product_id,
                quantity: acc.quantity,
                price_unit: acc.price_unit,
                subtotal: acc.subtotal,
            }));

            const result = await this.orm.call(
                "cotizador.configurator.service",
                "confirm_configuration",
                [],
                {
                    order_id: this.orderId,
                    config_id: this.state.matchingConfig.id,
                    selected_accessories: selectedAccsData,
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
                _t("Ocurrió un error al guardar en Odoo. Puede guardarla como cotización offline."),
                { type: "danger" }
            );
        } finally {
            this.state.saving = false;
        }
    }

    // --- Guardado Local en IndexedDB (Offline) ---

    async saveQuoteOffline() {
        const clientNameFinal =
            (this.state.selectedPartner && this.state.selectedPartner.name) ||
            this.state.clientName.trim() ||
            "Productor Sin Registrar";

        const quote = {
            uuid: "OFF-" + Date.now().toString(36).toUpperCase() + "-" + Math.random().toString(36).substring(2, 5).toUpperCase(),
            created_at: new Date().toISOString(),
            partner_id: this.state.selectedPartner ? this.state.selectedPartner.id : null,
            client_name: clientNameFinal,
            client_vat: this.state.clientVat.trim(),
            client_phone: this.state.clientPhone.trim(),
            client_email: this.state.clientEmail.trim(),
            model_id: this.state.selectedModel.id,
            model_name: this.state.selectedModel.name,
            model_code: this.state.selectedModel.default_code || "",
            config_id: this.state.matchingConfig.id,
            specs: this.selectedAttributesSummary,
            accessories: this.selectedAccessoriesList.map((a) => ({
                product_id: a.product_id,
                product_name: a.product_name,
                quantity: a.quantity,
                price_unit: a.price_unit,
                subtotal: a.subtotal,
            })),
            base_price: this.state.basePrice,
            accessories_total: this.state.accessoriesTotal,
            total_price: this.state.totalPrice,
            status: "pending",
        };

        try {
            await offlineDB.saveOfflineQuote(quote);

            // Si es un cliente nuevo ingresado manualmente, guardarlo también en la lista local de contactos
            if (!this.state.selectedPartner && this.state.clientName.trim()) {
                const newPartnerLocal = {
                    id: "local_" + Date.now(),
                    name: clientNameFinal,
                    vat: this.state.clientVat.trim(),
                    phone: this.state.clientPhone.trim(),
                    email: this.state.clientEmail.trim(),
                };
                await offlineDB.savePartners([newPartnerLocal]);
            }

            this.state.lastSavedQuote = quote;
            this.state.showOfflineSavedModal = true;
            await this.checkOfflineStatus();

            this.notification.add(
                _t("Cotización guardada exitosamente en el dispositivo (Modo Offline)."),
                { type: "success" }
            );
        } catch (e) {
            console.error("Error al guardar cotización en IndexedDB:", e);
            this.notification.add(_t("No se pudo guardar la cotización en la memoria local."), {
                type: "danger",
            });
        }
    }

    async deleteOfflineQuote(uuid) {
        try {
            await offlineDB.deleteQuote(uuid);
            await this.checkOfflineStatus();
            this.notification.add(_t("Cotización eliminada del almacenamiento local."), {
                type: "info",
            });
        } catch (e) {
            console.error("Error al eliminar cotización local:", e);
        }
    }

    closeOfflineSavedModal() {
        this.state.showOfflineSavedModal = false;
    }

    startNewOfflineQuote() {
        this.state.showOfflineSavedModal = false;
        this.state.step = "select_model";
        this.state.selectedModel = null;
        this.state.selectedValues = {};
        this.state.matchingConfig = null;
        this.state.configFinalized = false;
        this.state.accessories = [];
        this.state.selectedAccessories = {};
        this.state.basePrice = 0.0;
        this.state.accessoriesTotal = 0.0;
        this.state.totalPrice = 0.0;
        this.clearSelectedPartner();
    }

    // --- Sincronización de Cotizaciones Offline con Odoo ---

    async syncPendingQuotes() {
        if (!this.state.isOnline) {
            this.notification.add(
                _t("No hay conexión a internet. Espere a tener señal para sincronizar con Odoo."),
                { type: "warning" }
            );
            return;
        }

        const pending = await offlineDB.getPendingQuotes();
        if (pending.length === 0) {
            this.notification.add(_t("No hay cotizaciones pendientes de subir a Odoo."), {
                type: "info",
            });
            return;
        }

        this.state.syncingQuotes = true;
        try {
            const results = await this.orm.call(
                "cotizador.configurator.service",
                "sync_offline_quotes",
                [],
                { quotes: pending }
            );

            let successCount = 0;
            for (const res of results) {
                if (res.success) {
                    await offlineDB.markQuoteSynced(res.uuid, res.order_id, res.order_name);
                    successCount++;
                }
            }

            await this.checkOfflineStatus();

            this.notification.add(
                _t(`Se sincronizaron con éxito ${successCount} de ${pending.length} cotizaciones a Odoo.`),
                { type: "success" }
            );
        } catch (error) {
            console.error("Error al sincronizar cotizaciones offline:", error);
            this.notification.add(_t("Error al sincronizar las cotizaciones con Odoo."), {
                type: "danger",
            });
        } finally {
            this.state.syncingQuotes = false;
        }
    }

    // --- Compartir Resumen (WhatsApp / Texto) ---

    generateWhatsAppText(quote) {
        if (!quote) quote = this.state.lastSavedQuote;
        if (!quote) return "";

        const specsText = (quote.specs || [])
            .map((s) => `• ${s.attr_name}: ${s.value_name}`)
            .join("\n");

        const accsText = (quote.accessories || [])
            .map((a) => `• ${a.product_name} (x${a.quantity}): ${this.formatCurrency(a.subtotal)}`)
            .join("\n");

        let msg = `🚜 *COTIZACIÓN DE SEMBRADORA*\n`;
        msg += `Cliente: *${quote.client_name}*\n`;
        if (quote.client_vat) msg += `CUIT: ${quote.client_vat}\n`;
        msg += `Fecha: ${new Date(quote.created_at).toLocaleDateString("es-AR")}\n\n`;
        msg += `*MODELO:* ${quote.model_name}\n\n`;
        if (specsText) msg += `*Especificaciones:*\n${specsText}\n\n`;
        if (accsText) msg += `*Accesorios:*\n${accsText}\n\n`;
        msg += `*Precio Base:* ${this.formatCurrency(quote.base_price)}\n`;
        if (quote.accessories_total > 0) {
            msg += `*Total Accesorios:* ${this.formatCurrency(quote.accessories_total)}\n`;
        }
        msg += `*TOTAL ESTIMADO:* *${this.formatCurrency(quote.total_price)}*\n`;
        msg += `_(IVA 10.5% a liquidar en facturación)_\n\n`;
        msg += `Cotización Ref: ${quote.uuid}`;

        return msg;
    }

    async copyWhatsAppText(quote) {
        const text = this.generateWhatsAppText(quote);
        try {
            await navigator.clipboard.writeText(text);
            this.notification.add(_t("Resumen copiado al portapapeles para enviar por WhatsApp."), {
                type: "success",
            });
        } catch (e) {
            console.error("Error al copiar texto:", e);
        }
    }

    async closeAndReturn() {
        if (this.orderId && this.state.isOnline) {
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

CotizadorConfigurator.template = "cotizador.ConfiguradorTemplate";

registry.category("actions").add("cotizador_configurator", CotizadorConfigurator);