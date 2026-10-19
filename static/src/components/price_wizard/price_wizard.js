/**
 * @file
 * Asistente de Precios (acción cliente `cotizador_price_wizard`).
 *
 * Edición masiva de precios de la matriz de una máquina, para el Administrador del
 * Configurador. Pasos (`state.step`): 'select_model' → 'select_type' → una de las tres
 * pantallas de edición:
 *   - 'edit_base': precio de cada configuración;
 *   - 'edit_acc_global': accesorios de cantidad por atributo; un precio por accesorio que se
 *     aplica a todas las configuraciones de la máquina;
 *   - 'edit_acc_specific': precio de cada línea de accesorio, agrupable por valores de atributo
 *     (un precio por grupo).
 *
 * Los cambios quedan pendientes (resaltados) hasta *Guardar Cambios* (o Ctrl+S). El ajuste
 * masivo (porcentaje, sumar monto o fijar precio) se aplica a las filas filtradas.
 * Servidor: `cotizador.price.wizard.service` (models/price_wizard_service.py).
 * Plantilla: price_wizard.xml (`cotizador.PriceWizardTemplate`).
 */

import { registry } from "@web/core/registry";
import { Component, useState, onWillStart, onWillDestroy } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

/**
 * Componente OWL del Asistente de Precios.
 *
 * Cambios pendientes: `baseChanges` (id de configuración → precio), `accGlobalChanges`
 * (id de accesorio → precio) y `accSpecificChanges` (id de línea → precio).
 */
export class CotizadorPriceWizard extends Component {
    static template = "cotizador.PriceWizardTemplate";

    /** Inicializa servicios y estado, carga las máquinas y registra los atajos Ctrl+S (guardar) y Esc (cerrar modal). */
    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");

        this.state = useState({
            step: "select_model", // 'select_model' | 'select_type' | 'edit_base' | 'edit_acc_global' | 'edit_acc_specific'
            models: [],
            selectedModel: null,
            loading: false,
            saving: false,

            // Pagination limit
            pageSize: 80,

            // Base configs
            baseAttributes: [],
            baseConfigs: [],
            baseSearch: "",
            baseAttrFilters: {}, // attr_id -> selected value_name
            baseChanges: {}, // config_id -> new_price
            basePage: 1,

            // Accessories
            accAttributes: [],
            accGlobal: [],
            accSpecific: [],
            accSearch: "",
            accAttrFilters: {}, // attr_id -> selected value_name
            accGlobalChanges: {}, // product_id -> new_price
            accSpecificChanges: {}, // line_id -> new_price
            accGlobalPage: 1,
            accSpecificPage: 1,

            // Grouping for specific accessories
            accEnableGrouping: true,
            accGroupByAttrIds: [], // array of attr_id
            activeGroupModal: null, // group object when popup is open

            // Bulk Adjustment Tool
            showBulkModal: false,
            bulkType: "percent", // 'percent' | 'fixed_add' | 'fixed_set'
            bulkValue: 0.0,
        });

        onWillStart(async () => {
            await this.loadModels();
        });

        const handleKeyDown = (ev) => {
            if ((ev.ctrlKey || ev.metaKey) && ev.key === "s") {
                ev.preventDefault();
                if (this.state.step === "edit_base" && this.baseChangesCount > 0) {
                    this.saveBasePrices();
                } else if (this.state.step === "edit_acc_global" && this.accGlobalChangesCount > 0) {
                    this.saveAccGlobalPrices();
                } else if (this.state.step === "edit_acc_specific" && this.accSpecificChangesCount > 0) {
                    this.saveAccSpecificPrices();
                }
            } else if (ev.key === "Escape") {
                if (this.state.activeGroupModal) {
                    this.closeGroupModal();
                } else if (this.state.showBulkModal) {
                    this.closeBulkModal();
                }
            }
        };

        window.addEventListener("keydown", handleKeyDown);
        onWillDestroy(() => {
            window.removeEventListener("keydown", handleKeyDown);
        });
    }

    // --- Helpers de Formateo de Precios (Miles con . y Decimales con ,) ---

    /**
     * Formatea un precio con punto de miles y coma decimal (es-AR).
     * @param val Precio (number).
     * @returns {string}
     */
    formatPrice(val) {
        if (val === undefined || val === null || isNaN(val)) return "0,00";
        return new Intl.NumberFormat("es-AR", {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        }).format(val);
    }

    /**
     * Interpreta un precio escrito por el usuario, con formato argentino o internacional
     * ("1.234,5", "1,234.5", "1234.5").
     * @param input Texto o número.
     * @returns {number} 0 si no es un número.
     */
    parsePrice(input) {
        if (typeof input === "number") return input;
        if (!input || !input.toString().trim()) return 0.0;
        let str = input.toString().trim();

        if (str.includes(".") && str.includes(",")) {
            if (str.lastIndexOf(",") > str.lastIndexOf(".")) {
                str = str.replace(/\./g, "").replace(",", ".");
            } else {
                str = str.replace(/,/g, "");
            }
        } else if (str.includes(",")) {
            str = str.replace(",", ".");
        } else if ((str.match(/\./g) || []).length > 1) {
            str = str.replace(/\./g, "");
        }

        const val = parseFloat(str);
        return isNaN(val) ? 0.0 : val;
    }

    /**
     * Carga las máquinas.
     * @returns {Promise<void>}
     */
    async loadModels() {
        this.state.loading = true;
        try {
            this.state.models = await this.orm.call(
                "cotizador.price.wizard.service",
                "get_models",
                []
            );
        } catch (error) {
            this.notification.add(_t("Error al cargar los modelos de sembradoras."), {
                type: "danger",
            });
        } finally {
            this.state.loading = false;
        }
    }

    /**
     * Elige una máquina y pasa a elegir qué editar.
     * @param model Máquina de `state.models`.
     */
    selectModel(model) {
        this.state.selectedModel = model;
        this.state.step = "select_type";
    }

    /** Vuelve a la elección de máquina descartando los cambios pendientes y los filtros. */
    goToModelSelection() {
        this.state.step = "select_model";
        this.state.selectedModel = null;
        this.state.baseChanges = {};
        this.state.accGlobalChanges = {};
        this.state.accSpecificChanges = {};
        this.state.baseSearch = "";
        this.state.accSearch = "";
        this.state.baseAttrFilters = {};
        this.state.accAttrFilters = {};
        this.state.basePage = 1;
        this.state.accGlobalPage = 1;
        this.state.accSpecificPage = 1;
        this.state.activeGroupModal = null;
        this.state.showBulkModal = false;
    }

    /** Vuelve a la elección de qué editar descartando los cambios pendientes y los filtros. */
    goToTypeSelection() {
        if (this.state.selectedModel) {
            this.state.step = "select_type";
            this.state.baseChanges = {};
            this.state.accGlobalChanges = {};
            this.state.accSpecificChanges = {};
            this.state.baseSearch = "";
            this.state.accSearch = "";
            this.state.baseAttrFilters = {};
            this.state.accAttrFilters = {};
            this.state.basePage = 1;
            this.state.accGlobalPage = 1;
            this.state.accSpecificPage = 1;
            this.state.activeGroupModal = null;
            this.state.showBulkModal = false;
        }
    }

    /** Vuelve un paso. */
    goBack() {
        if (this.state.step === "select_type") {
            this.goToModelSelection();
        } else if (
            this.state.step === "edit_base" ||
            this.state.step === "edit_acc_global" ||
            this.state.step === "edit_acc_specific"
        ) {
            this.goToTypeSelection();
        }
    }

    /**
     * Carga las configuraciones de la máquina y abre la edición de precios base.
     * @returns {Promise<void>}
     */
    async goToEditBase() {
        this.state.loading = true;
        this.state.baseChanges = {};
        this.state.baseSearch = "";
        this.state.baseAttrFilters = {};
        this.state.basePage = 1;
        this.state.showBulkModal = false;
        try {
            const data = await this.orm.call(
                "cotizador.price.wizard.service",
                "get_base_configs_data",
                [this.state.selectedModel.id]
            );
            this.state.baseAttributes = data.attributes || [];
            this.state.baseConfigs = data.configs || [];
            this.state.step = "edit_base";
        } catch (error) {
            this.notification.add(_t("Error al cargar las configuraciones base."), {
                type: "danger",
            });
        } finally {
            this.state.loading = false;
        }
    }

    /**
     * Carga los accesorios de la máquina y abre la pestaña de globales (o la de
     * específicos, si no hay globales).
     * @returns {Promise<void>}
     */
    async goToEditAccessories() {
        this.state.loading = true;
        this.state.accGlobalChanges = {};
        this.state.accSpecificChanges = {};
        this.state.accSearch = "";
        this.state.accAttrFilters = {};
        this.state.accGlobalPage = 1;
        this.state.accSpecificPage = 1;
        this.state.activeGroupModal = null;
        this.state.showBulkModal = false;
        try {
            const data = await this.orm.call(
                "cotizador.price.wizard.service",
                "get_accessory_data",
                [this.state.selectedModel.id]
            );
            this.state.accAttributes = data.attributes || [];
            this.state.accGlobal = data.global_accessories || [];
            this.state.accSpecific = data.specific_accessories || [];
            this.state.accGroupByAttrIds = (data.attributes || []).map((a) => a.id);
            this.state.accEnableGrouping = true;

            if (this.state.accGlobal.length > 0) {
                this.state.step = "edit_acc_global";
            } else {
                this.state.step = "edit_acc_specific";
            }
        } catch (error) {
            this.notification.add(_t("Error al cargar los accesorios del modelo."), {
                type: "danger",
            });
        } finally {
            this.state.loading = false;
        }
    }

    /**
     * Cambia de pestaña de accesorios limpiando búsqueda, filtros y páginas.
     * @param tab 'edit_acc_global' o 'edit_acc_specific'.
     */
    setAccTab(tab) {
        this.state.step = tab;
        this.state.accSearch = "";
        this.state.accAttrFilters = {};
        this.state.accGlobalPage = 1;
        this.state.accSpecificPage = 1;
        this.state.activeGroupModal = null;
        this.state.showBulkModal = false;
    }

    // --- Bulk Adjustment Modal & Execution ---

    /** Abre el ajuste masivo. */
    openBulkModal() {
        this.state.bulkType = "percent";
        this.state.bulkValue = 0.0;
        this.state.showBulkModal = true;
    }

    /** Cierra el ajuste masivo. */
    closeBulkModal() {
        this.state.showBulkModal = false;
    }

    /**
     * Aplica el ajuste masivo a las filas filtradas de la pantalla actual, como cambios
     * pendientes: porcentaje (redondeado a centavos), sumar monto o fijar precio (nunca negativo).
     */
    applyBulkAdjustment() {
        const val = parseFloat(this.state.bulkValue) || 0.0;
        if (val === 0.0 && this.state.bulkType !== "fixed_set") {
            this.closeBulkModal();
            return;
        }

        let updatedCount = 0;

        if (this.state.step === "edit_base") {
            for (const cfg of this.filteredBaseConfigs) {
                const currentPrice = cfg.id in this.state.baseChanges ? this.state.baseChanges[cfg.id] : cfg.price;
                let newPrice = currentPrice;
                if (this.state.bulkType === "percent") {
                    newPrice = Math.round((currentPrice * (1 + val / 100)) * 100) / 100;
                } else if (this.state.bulkType === "fixed_add") {
                    newPrice = Math.max(0, currentPrice + val);
                } else if (this.state.bulkType === "fixed_set") {
                    newPrice = Math.max(0, val);
                }
                this.state.baseChanges[cfg.id] = newPrice;
                updatedCount++;
            }
        } else if (this.state.step === "edit_acc_global") {
            for (const acc of this.filteredAccGlobal) {
                const currentPrice = acc.product_id in this.state.accGlobalChanges ? this.state.accGlobalChanges[acc.product_id] : acc.price;
                let newPrice = currentPrice;
                if (this.state.bulkType === "percent") {
                    newPrice = Math.round((currentPrice * (1 + val / 100)) * 100) / 100;
                } else if (this.state.bulkType === "fixed_add") {
                    newPrice = Math.max(0, currentPrice + val);
                } else if (this.state.bulkType === "fixed_set") {
                    newPrice = Math.max(0, val);
                }
                this.state.accGlobalChanges[acc.product_id] = newPrice;
                updatedCount++;
            }
        } else if (this.state.step === "edit_acc_specific") {
            for (const line of this.filteredAccSpecific) {
                const currentPrice = line.line_id in this.state.accSpecificChanges ? this.state.accSpecificChanges[line.line_id] : line.price;
                let newPrice = currentPrice;
                if (this.state.bulkType === "percent") {
                    newPrice = Math.round((currentPrice * (1 + val / 100)) * 100) / 100;
                } else if (this.state.bulkType === "fixed_add") {
                    newPrice = Math.max(0, currentPrice + val);
                } else if (this.state.bulkType === "fixed_set") {
                    newPrice = Math.max(0, val);
                }
                this.state.accSpecificChanges[line.line_id] = newPrice;
                updatedCount++;
            }
        }

        this.notification.add(
            _t(`Se aplicó el ajuste a ${updatedCount} elementos visibles. Presione Guardar Cambios para persistir.`),
            { type: "info" }
        );
        this.closeBulkModal();
    }

    // --- Base Configs Filters & Methods ---

    /**
     * Filtra configuraciones por el valor de un atributo.
     * @param attrId Id del atributo.
     * @param ev Evento `change` del `<select>` (valor vacío = sin filtro).
     */
    onBaseAttrFilterChange(attrId, ev) {
        const val = ev.target.value;
        if (val) {
            this.state.baseAttrFilters[attrId] = val;
        } else {
            delete this.state.baseAttrFilters[attrId];
        }
        this.state.basePage = 1;
    }

    /**
     * Búsqueda en configuraciones (nombre, código o valores).
     * @param ev Evento `input`.
     */
    onBaseSearchInput(ev) {
        this.state.baseSearch = ev.target.value;
        this.state.basePage = 1;
    }

    /** Quita búsqueda y filtros de configuraciones. */
    resetBaseFilters() {
        this.state.baseSearch = "";
        this.state.baseAttrFilters = {};
        this.state.basePage = 1;
    }

    /** @returns {boolean} Hay búsqueda o filtros de configuraciones. */
    get hasActiveBaseFilters() {
        return (
            this.state.baseSearch.trim() !== "" ||
            Object.keys(this.state.baseAttrFilters).length > 0
        );
    }

    /**
     * Registra el precio editado de una configuración y lo reformatea.
     * @param configId Id de la configuración.
     * @param ev Evento `change` del campo.
     */
    onBasePriceChange(configId, ev) {
        const val = this.parsePrice(ev.target.value);
        this.state.baseChanges[configId] = val;
        ev.target.value = this.formatPrice(val);
    }

    /**
     * Precio a mostrar (pendiente o actual).
     * @param cfg Configuración.
     * @returns {string}
     */
    getBasePriceFormatted(cfg) {
        const val = cfg.id in this.state.baseChanges ? this.state.baseChanges[cfg.id] : cfg.price;
        return this.formatPrice(val);
    }

    /**
     * @param cfg Configuración.
     * @returns {boolean} Tiene un precio pendiente distinto del guardado.
     */
    isBasePriceChanged(cfg) {
        return cfg.id in this.state.baseChanges && this.state.baseChanges[cfg.id] !== cfg.price;
    }

    /**
     * Configuraciones que pasan los filtros de atributo y la búsqueda.
     * @returns {Object[]}
     */
    get filteredBaseConfigs() {
        return this.state.baseConfigs.filter((cfg) => {
            for (const [attrIdStr, selectedVal] of Object.entries(this.state.baseAttrFilters)) {
                const attrId = parseInt(attrIdStr);
                if (cfg.attr_values && cfg.attr_values[attrId] !== selectedVal) {
                    return false;
                }
            }

            if (this.state.baseSearch.trim()) {
                const term = this.state.baseSearch.toLowerCase().trim();
                if (cfg.name.toLowerCase().includes(term)) return true;
                if (cfg.ext_id.toLowerCase().includes(term)) return true;
                for (const rv of cfg.row_values) {
                    if (rv.value.toLowerCase().includes(term)) return true;
                }
                return false;
            }

            return true;
        });
    }

    // Pagination for Base Configs
    /** @returns {number} Páginas de configuraciones. */
    get baseTotalPages() {
        return Math.ceil(this.filteredBaseConfigs.length / this.state.pageSize) || 1;
    }

    /** @returns {Object[]} Configuraciones de la página actual. */
    get paginatedBaseConfigs() {
        const start = (this.state.basePage - 1) * this.state.pageSize;
        return this.filteredBaseConfigs.slice(start, start + this.state.pageSize);
    }

    /** @returns {string} "desde-hasta / total". */
    get basePagerInfo() {
        const total = this.filteredBaseConfigs.length;
        if (total === 0) return "0 / 0";
        const start = (this.state.basePage - 1) * this.state.pageSize + 1;
        const end = Math.min(this.state.basePage * this.state.pageSize, total);
        return `${start}-${end} / ${total}`;
    }

    /** Página anterior de configuraciones. */
    prevBasePage() {
        if (this.state.basePage > 1) {
            this.state.basePage--;
        }
    }

    /** Página siguiente de configuraciones. */
    nextBasePage() {
        if (this.state.basePage < this.baseTotalPages) {
            this.state.basePage++;
        }
    }

    /** @returns {number} Configuraciones con precio pendiente. */
    get baseChangesCount() {
        let count = 0;
        for (const cfg of this.state.baseConfigs) {
            if (this.isBasePriceChanged(cfg)) {
                count++;
            }
        }
        return count;
    }

    /**
     * Guarda los precios pendientes de configuraciones.
     * @returns {Promise<void>}
     */
    async saveBasePrices() {
        const updates = [];
        for (const cfg of this.state.baseConfigs) {
            if (this.isBasePriceChanged(cfg)) {
                updates.push({
                    id: cfg.id,
                    price: this.state.baseChanges[cfg.id],
                });
            }
        }

        if (updates.length === 0) {
            this.notification.add(_t("No hay cambios de precios pendientes para guardar."), {
                type: "info",
            });
            return;
        }

        this.state.saving = true;
        try {
            const res = await this.orm.call(
                "cotizador.price.wizard.service",
                "save_base_prices",
                [updates]
            );
            if (res.success) {
                this.notification.add(
                    _t(`Se actualizaron exitosamente ${res.updated_count} precios de configuración base.`),
                    { type: "success" }
                );
                for (const u of updates) {
                    const cfg = this.state.baseConfigs.find((c) => c.id === u.id);
                    if (cfg) cfg.price = u.price;
                }
                this.state.baseChanges = {};
            }
        } catch (error) {
            this.notification.add(_t("Error al guardar los precios base."), {
                type: "danger",
            });
        } finally {
            this.state.saving = false;
        }
    }

    // --- Global Accessories Methods ---

    /**
     * Búsqueda en accesorios globales.
     * @param ev Evento `input`.
     */
    onAccGlobalSearchInput(ev) {
        this.state.accSearch = ev.target.value;
        this.state.accGlobalPage = 1;
    }

    /**
     * Registra el precio editado de un accesorio global y lo reformatea.
     * @param productId Id del accesorio.
     * @param ev Evento `change` del campo.
     */
    onAccGlobalPriceChange(productId, ev) {
        const val = this.parsePrice(ev.target.value);
        this.state.accGlobalChanges[productId] = val;
        ev.target.value = this.formatPrice(val);
    }

    /**
     * Precio a mostrar (pendiente o actual).
     * @param acc Accesorio global.
     * @returns {string}
     */
    getAccGlobalPriceFormatted(acc) {
        const val =
            acc.product_id in this.state.accGlobalChanges
                ? this.state.accGlobalChanges[acc.product_id]
                : acc.price;
        return this.formatPrice(val);
    }

    /**
     * @param acc Accesorio global.
     * @returns {boolean} Tiene un precio pendiente distinto del guardado.
     */
    isAccGlobalPriceChanged(acc) {
        return (
            acc.product_id in this.state.accGlobalChanges &&
            this.state.accGlobalChanges[acc.product_id] !== acc.price
        );
    }

    /**
     * Accesorios globales que coinciden con la búsqueda (nombre, categoría o código).
     * @returns {Object[]}
     */
    get filteredAccGlobal() {
        if (!this.state.accSearch.trim()) {
            return this.state.accGlobal;
        }
        const term = this.state.accSearch.toLowerCase().trim();
        return this.state.accGlobal.filter((acc) => {
            return (
                acc.product_name.toLowerCase().includes(term) ||
                acc.category_name.toLowerCase().includes(term) ||
                acc.default_code.toLowerCase().includes(term)
            );
        });
    }

    // Pagination for Global Accessories
    /** @returns {number} Páginas de accesorios globales. */
    get accGlobalTotalPages() {
        return Math.ceil(this.filteredAccGlobal.length / this.state.pageSize) || 1;
    }

    /** @returns {Object[]} Accesorios globales de la página actual. */
    get paginatedAccGlobal() {
        const start = (this.state.accGlobalPage - 1) * this.state.pageSize;
        return this.filteredAccGlobal.slice(start, start + this.state.pageSize);
    }

    /** @returns {string} "desde-hasta / total". */
    get accGlobalPagerInfo() {
        const total = this.filteredAccGlobal.length;
        if (total === 0) return "0 / 0";
        const start = (this.state.accGlobalPage - 1) * this.state.pageSize + 1;
        const end = Math.min(this.state.accGlobalPage * this.state.pageSize, total);
        return `${start}-${end} / ${total}`;
    }

    /** Página anterior de accesorios globales. */
    prevAccGlobalPage() {
        if (this.state.accGlobalPage > 1) {
            this.state.accGlobalPage--;
        }
    }

    /** Página siguiente de accesorios globales. */
    nextAccGlobalPage() {
        if (this.state.accGlobalPage < this.accGlobalTotalPages) {
            this.state.accGlobalPage++;
        }
    }

    /** @returns {number} Accesorios globales con precio pendiente. */
    get accGlobalChangesCount() {
        let count = 0;
        for (const acc of this.state.accGlobal) {
            if (this.isAccGlobalPriceChanged(acc)) {
                count++;
            }
        }
        return count;
    }

    /**
     * Guarda los precios pendientes de accesorios globales (cada uno en todas las
     * configuraciones de la máquina).
     * @returns {Promise<void>}
     */
    async saveAccGlobalPrices() {
        const updates = [];
        for (const acc of this.state.accGlobal) {
            if (this.isAccGlobalPriceChanged(acc)) {
                updates.push({
                    product_id: acc.product_id,
                    price: this.state.accGlobalChanges[acc.product_id],
                });
            }
        }

        if (updates.length === 0) {
            this.notification.add(_t("No hay cambios de precios pendientes para guardar."), {
                type: "info",
            });
            return;
        }

        this.state.saving = true;
        try {
            const res = await this.orm.call(
                "cotizador.price.wizard.service",
                "save_global_accessory_prices",
                [this.state.selectedModel.id, updates]
            );
            if (res.success) {
                this.notification.add(
                    _t(
                        `Se actualizaron ${res.updated_count} accesorios impactando en ${res.updated_lines_count} configuraciones del modelo.`
                    ),
                    { type: "success" }
                );
                for (const u of updates) {
                    const acc = this.state.accGlobal.find((a) => a.product_id === u.product_id);
                    if (acc) acc.price = u.price;
                }
                this.state.accGlobalChanges = {};
            }
        } catch (error) {
            this.notification.add(_t("Error al guardar los precios de accesorios."), {
                type: "danger",
            });
        } finally {
            this.state.saving = false;
        }
    }

    // --- Specific Accessories Filters, Grouping & Methods ---

    /**
     * Filtra líneas de accesorio por el valor de un atributo de su configuración.
     * @param attrId Id del atributo.
     * @param ev Evento `change` del `<select>` (valor vacío = sin filtro).
     */
    onAccAttrFilterChange(attrId, ev) {
        const val = ev.target.value;
        if (val) {
            this.state.accAttrFilters[attrId] = val;
        } else {
            delete this.state.accAttrFilters[attrId];
        }
        this.state.accSpecificPage = 1;
    }

    /**
     * Búsqueda en líneas de accesorio.
     * @param ev Evento `input`.
     */
    onAccSearchInput(ev) {
        this.state.accSearch = ev.target.value;
        this.state.accSpecificPage = 1;
    }

    /** Quita búsqueda y filtros de líneas de accesorio. */
    resetAccFilters() {
        this.state.accSearch = "";
        this.state.accAttrFilters = {};
        this.state.accSpecificPage = 1;
    }

    /** @returns {boolean} Hay búsqueda o filtros de líneas de accesorio. */
    get hasActiveAccFilters() {
        return (
            this.state.accSearch.trim() !== "" ||
            Object.keys(this.state.accAttrFilters).length > 0
        );
    }

    // Grouping Controls
    /**
     * Agrega o quita un atributo de la agrupación de líneas.
     * @param attrId Id del atributo.
     */
    toggleGroupByAttr(attrId) {
        const idx = this.state.accGroupByAttrIds.indexOf(attrId);
        if (idx > -1) {
            this.state.accGroupByAttrIds.splice(idx, 1);
        } else {
            this.state.accGroupByAttrIds.push(attrId);
        }
        this.state.accSpecificPage = 1;
    }

    /**
     * @param attrId Id del atributo.
     * @returns {boolean} El atributo se usa para agrupar.
     */
    isAttrInGroupBy(attrId) {
        return this.state.accGroupByAttrIds.includes(attrId);
    }

    /** Activa o desactiva la agrupación de líneas. */
    toggleEnableGrouping() {
        this.state.accEnableGrouping = !this.state.accEnableGrouping;
        this.state.accSpecificPage = 1;
    }

    // Popup Modal Controls
    /**
     * Muestra las configuraciones de un grupo.
     * @param group Grupo de groupedAccSpecific.
     */
    openGroupModal(group) {
        this.state.activeGroupModal = group;
    }

    /** Cierra la lista de configuraciones del grupo. */
    closeGroupModal() {
        this.state.activeGroupModal = null;
    }

    /**
     * Líneas de accesorio que pasan los filtros de atributo y la búsqueda.
     * @returns {Object[]}
     */
    get filteredAccSpecific() {
        return this.state.accSpecific.filter((line) => {
            for (const [attrIdStr, selectedVal] of Object.entries(this.state.accAttrFilters)) {
                const attrId = parseInt(attrIdStr);
                if (line.attr_values && line.attr_values[attrId] !== selectedVal) {
                    return false;
                }
            }

            if (this.state.accSearch.trim()) {
                const term = this.state.accSearch.toLowerCase().trim();
                if (line.product_name.toLowerCase().includes(term)) return true;
                if (line.config_name.toLowerCase().includes(term)) return true;
                if (line.category_name.toLowerCase().includes(term)) return true;
                return false;
            }

            return true;
        });
    }

    // Computed Grouped Data
    /**
     * Líneas agrupadas por accesorio, valores de los atributos de agrupación y precio
     * actual: cada grupo se edita con un solo precio.
     * @returns {Object[]} [{group_key, product_id, product_name, currency, original_price,
     *          group_attr_values, lines, line_ids}]
     */
    get groupedAccSpecific() {
        if (!this.state.accEnableGrouping) {
            return [];
        }

        const groupsMap = {};
        const selectedAttrIds = this.state.accGroupByAttrIds;

        for (const line of this.filteredAccSpecific) {
            const attrSegments = [];
            const groupAttrValues = [];

            for (const attr of this.state.accAttributes) {
                if (selectedAttrIds.includes(attr.id)) {
                    const val = (line.attr_values && line.attr_values[attr.id]) || "-";
                    attrSegments.push(`${attr.id}:${val}`);
                    groupAttrValues.push({
                        attr_id: attr.id,
                        attr_name: attr.name,
                        value: val,
                    });
                }
            }

            const groupKey = `${line.product_id}__${attrSegments.join("__")}__${line.price}`;

            if (!groupsMap[groupKey]) {
                groupsMap[groupKey] = {
                    group_key: groupKey,
                    product_id: line.product_id,
                    product_name: line.product_name,
                    default_code: line.default_code,
                    category_name: line.category_name,
                    currency: line.currency,
                    original_price: line.price,
                    group_attr_values: groupAttrValues,
                    lines: [],
                    line_ids: [],
                };
            }

            groupsMap[groupKey].lines.push(line);
            groupsMap[groupKey].line_ids.push(line.line_id);
        }

        return Object.values(groupsMap);
    }

    // Pagination for Specific Accessories (Grouped & Detailed)
    /** @returns {number} Páginas de líneas o de grupos. */
    get accSpecificTotalPages() {
        const totalItems = this.state.accEnableGrouping
            ? this.groupedAccSpecific.length
            : this.filteredAccSpecific.length;
        return Math.ceil(totalItems / this.state.pageSize) || 1;
    }

    /** @returns {Object[]} Grupos de la página actual. */
    get paginatedGroupedAccSpecific() {
        const start = (this.state.accSpecificPage - 1) * this.state.pageSize;
        return this.groupedAccSpecific.slice(start, start + this.state.pageSize);
    }

    /** @returns {Object[]} Líneas de la página actual. */
    get paginatedAccSpecific() {
        const start = (this.state.accSpecificPage - 1) * this.state.pageSize;
        return this.filteredAccSpecific.slice(start, start + this.state.pageSize);
    }

    /** @returns {string} "desde-hasta / total". */
    get accSpecificPagerInfo() {
        const total = this.state.accEnableGrouping
            ? this.groupedAccSpecific.length
            : this.filteredAccSpecific.length;
        if (total === 0) return "0 / 0";
        const start = (this.state.accSpecificPage - 1) * this.state.pageSize + 1;
        const end = Math.min(this.state.accSpecificPage * this.state.pageSize, total);
        return `${start}-${end} / ${total}`;
    }

    /** Página anterior de líneas o grupos. */
    prevAccSpecificPage() {
        if (this.state.accSpecificPage > 1) {
            this.state.accSpecificPage--;
        }
    }

    /** Página siguiente de líneas o grupos. */
    nextAccSpecificPage() {
        if (this.state.accSpecificPage < this.accSpecificTotalPages) {
            this.state.accSpecificPage++;
        }
    }

    // Group Price Change
    /**
     * Registra el mismo precio para todas las líneas de un grupo.
     * @param group Grupo de groupedAccSpecific.
     * @param ev Evento `change` del campo.
     */
    onAccGroupPriceChange(group, ev) {
        const val = this.parsePrice(ev.target.value);
        for (const lineId of group.line_ids) {
            this.state.accSpecificChanges[lineId] = val;
        }
        ev.target.value = this.formatPrice(val);
    }

    /**
     * Precio a mostrar del grupo (pendiente o actual).
     * @param group Grupo.
     * @returns {string}
     */
    getAccGroupPriceFormatted(group) {
        const firstLineId = group.line_ids[0];
        const val =
            firstLineId in this.state.accSpecificChanges
                ? this.state.accSpecificChanges[firstLineId]
                : group.original_price;
        return this.formatPrice(val);
    }

    /**
     * @param group Grupo.
     * @returns {boolean} Tiene un precio pendiente distinto del guardado.
     */
    isAccGroupPriceChanged(group) {
        const firstLineId = group.line_ids[0];
        return (
            firstLineId in this.state.accSpecificChanges &&
            this.state.accSpecificChanges[firstLineId] !== group.original_price
        );
    }

    // Individual Line Price Change
    /**
     * Registra el precio editado de una línea y lo reformatea.
     * @param lineId Id de la línea de accesorio.
     * @param ev Evento `change` del campo.
     */
    onAccSpecificPriceChange(lineId, ev) {
        const val = this.parsePrice(ev.target.value);
        this.state.accSpecificChanges[lineId] = val;
        ev.target.value = this.formatPrice(val);
    }

    /**
     * Precio a mostrar de una línea (pendiente o actual).
     * @param line Línea de accesorio.
     * @returns {string}
     */
    getAccSpecificPriceFormatted(line) {
        const val =
            line.line_id in this.state.accSpecificChanges
                ? this.state.accSpecificChanges[line.line_id]
                : line.price;
        return this.formatPrice(val);
    }

    /**
     * @param line Línea de accesorio.
     * @returns {boolean} Tiene un precio pendiente distinto del guardado.
     */
    isAccSpecificPriceChanged(line) {
        return (
            line.line_id in this.state.accSpecificChanges &&
            this.state.accSpecificChanges[line.line_id] !== line.price
        );
    }

    /** @returns {number} Líneas con precio pendiente. */
    get accSpecificChangesCount() {
        let count = 0;
        for (const line of this.state.accSpecific) {
            if (this.isAccSpecificPriceChanged(line)) {
                count++;
            }
        }
        return count;
    }

    /**
     * Guarda los precios pendientes de líneas de accesorio.
     * @returns {Promise<void>}
     */
    async saveAccSpecificPrices() {
        const updates = [];
        for (const line of this.state.accSpecific) {
            if (this.isAccSpecificPriceChanged(line)) {
                updates.push({
                    line_id: line.line_id,
                    price: this.state.accSpecificChanges[line.line_id],
                });
            }
        }

        if (updates.length === 0) {
            this.notification.add(_t("No hay cambios de precios pendientes para guardar."), {
                type: "info",
            });
            return;
        }

        this.state.saving = true;
        try {
            const res = await this.orm.call(
                "cotizador.price.wizard.service",
                "save_specific_accessory_prices",
                [updates]
            );
            if (res.success) {
                this.notification.add(
                    _t(`Se actualizaron ${res.updated_count} precios de accesorios específicos.`),
                    { type: "success" }
                );
                for (const u of updates) {
                    const line = this.state.accSpecific.find((l) => l.line_id === u.line_id);
                    if (line) line.price = u.price;
                }
                this.state.accSpecificChanges = {};
            }
        } catch (error) {
            this.notification.add(_t("Error al guardar los precios específicos."), {
                type: "danger",
            });
        } finally {
            this.state.saving = false;
        }
    }
}

registry.category("actions").add("cotizador_price_wizard", CotizadorPriceWizard);
