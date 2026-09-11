/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useState, onWillStart, onWillDestroy } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

export class CotizadorPriceWizard extends Component {
    static template = "cotizador.PriceWizardTemplate";

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

    formatPrice(val) {
        if (val === undefined || val === null || isNaN(val)) return "0,00";
        return new Intl.NumberFormat("es-AR", {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        }).format(val);
    }

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

    selectModel(model) {
        this.state.selectedModel = model;
        this.state.step = "select_type";
    }

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

    openBulkModal() {
        this.state.bulkType = "percent";
        this.state.bulkValue = 0.0;
        this.state.showBulkModal = true;
    }

    closeBulkModal() {
        this.state.showBulkModal = false;
    }

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

    onBaseAttrFilterChange(attrId, ev) {
        const val = ev.target.value;
        if (val) {
            this.state.baseAttrFilters[attrId] = val;
        } else {
            delete this.state.baseAttrFilters[attrId];
        }
        this.state.basePage = 1;
    }

    onBaseSearchInput(ev) {
        this.state.baseSearch = ev.target.value;
        this.state.basePage = 1;
    }

    resetBaseFilters() {
        this.state.baseSearch = "";
        this.state.baseAttrFilters = {};
        this.state.basePage = 1;
    }

    get hasActiveBaseFilters() {
        return (
            this.state.baseSearch.trim() !== "" ||
            Object.keys(this.state.baseAttrFilters).length > 0
        );
    }

    onBasePriceChange(configId, ev) {
        const val = this.parsePrice(ev.target.value);
        this.state.baseChanges[configId] = val;
        ev.target.value = this.formatPrice(val);
    }

    getBasePriceFormatted(cfg) {
        const val = cfg.id in this.state.baseChanges ? this.state.baseChanges[cfg.id] : cfg.price;
        return this.formatPrice(val);
    }

    isBasePriceChanged(cfg) {
        return cfg.id in this.state.baseChanges && this.state.baseChanges[cfg.id] !== cfg.price;
    }

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
    get baseTotalPages() {
        return Math.ceil(this.filteredBaseConfigs.length / this.state.pageSize) || 1;
    }

    get paginatedBaseConfigs() {
        const start = (this.state.basePage - 1) * this.state.pageSize;
        return this.filteredBaseConfigs.slice(start, start + this.state.pageSize);
    }

    get basePagerInfo() {
        const total = this.filteredBaseConfigs.length;
        if (total === 0) return "0 / 0";
        const start = (this.state.basePage - 1) * this.state.pageSize + 1;
        const end = Math.min(this.state.basePage * this.state.pageSize, total);
        return `${start}-${end} / ${total}`;
    }

    prevBasePage() {
        if (this.state.basePage > 1) {
            this.state.basePage--;
        }
    }

    nextBasePage() {
        if (this.state.basePage < this.baseTotalPages) {
            this.state.basePage++;
        }
    }

    get baseChangesCount() {
        let count = 0;
        for (const cfg of this.state.baseConfigs) {
            if (this.isBasePriceChanged(cfg)) {
                count++;
            }
        }
        return count;
    }

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

    onAccGlobalSearchInput(ev) {
        this.state.accSearch = ev.target.value;
        this.state.accGlobalPage = 1;
    }

    onAccGlobalPriceChange(productId, ev) {
        const val = this.parsePrice(ev.target.value);
        this.state.accGlobalChanges[productId] = val;
        ev.target.value = this.formatPrice(val);
    }

    getAccGlobalPriceFormatted(acc) {
        const val =
            acc.product_id in this.state.accGlobalChanges
                ? this.state.accGlobalChanges[acc.product_id]
                : acc.price;
        return this.formatPrice(val);
    }

    isAccGlobalPriceChanged(acc) {
        return (
            acc.product_id in this.state.accGlobalChanges &&
            this.state.accGlobalChanges[acc.product_id] !== acc.price
        );
    }

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
    get accGlobalTotalPages() {
        return Math.ceil(this.filteredAccGlobal.length / this.state.pageSize) || 1;
    }

    get paginatedAccGlobal() {
        const start = (this.state.accGlobalPage - 1) * this.state.pageSize;
        return this.filteredAccGlobal.slice(start, start + this.state.pageSize);
    }

    get accGlobalPagerInfo() {
        const total = this.filteredAccGlobal.length;
        if (total === 0) return "0 / 0";
        const start = (this.state.accGlobalPage - 1) * this.state.pageSize + 1;
        const end = Math.min(this.state.accGlobalPage * this.state.pageSize, total);
        return `${start}-${end} / ${total}`;
    }

    prevAccGlobalPage() {
        if (this.state.accGlobalPage > 1) {
            this.state.accGlobalPage--;
        }
    }

    nextAccGlobalPage() {
        if (this.state.accGlobalPage < this.accGlobalTotalPages) {
            this.state.accGlobalPage++;
        }
    }

    get accGlobalChangesCount() {
        let count = 0;
        for (const acc of this.state.accGlobal) {
            if (this.isAccGlobalPriceChanged(acc)) {
                count++;
            }
        }
        return count;
    }

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

    onAccAttrFilterChange(attrId, ev) {
        const val = ev.target.value;
        if (val) {
            this.state.accAttrFilters[attrId] = val;
        } else {
            delete this.state.accAttrFilters[attrId];
        }
        this.state.accSpecificPage = 1;
    }

    onAccSearchInput(ev) {
        this.state.accSearch = ev.target.value;
        this.state.accSpecificPage = 1;
    }

    resetAccFilters() {
        this.state.accSearch = "";
        this.state.accAttrFilters = {};
        this.state.accSpecificPage = 1;
    }

    get hasActiveAccFilters() {
        return (
            this.state.accSearch.trim() !== "" ||
            Object.keys(this.state.accAttrFilters).length > 0
        );
    }

    // Grouping Controls
    toggleGroupByAttr(attrId) {
        const idx = this.state.accGroupByAttrIds.indexOf(attrId);
        if (idx > -1) {
            this.state.accGroupByAttrIds.splice(idx, 1);
        } else {
            this.state.accGroupByAttrIds.push(attrId);
        }
        this.state.accSpecificPage = 1;
    }

    isAttrInGroupBy(attrId) {
        return this.state.accGroupByAttrIds.includes(attrId);
    }

    toggleEnableGrouping() {
        this.state.accEnableGrouping = !this.state.accEnableGrouping;
        this.state.accSpecificPage = 1;
    }

    // Popup Modal Controls
    openGroupModal(group) {
        this.state.activeGroupModal = group;
    }

    closeGroupModal() {
        this.state.activeGroupModal = null;
    }

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
    get accSpecificTotalPages() {
        const totalItems = this.state.accEnableGrouping
            ? this.groupedAccSpecific.length
            : this.filteredAccSpecific.length;
        return Math.ceil(totalItems / this.state.pageSize) || 1;
    }

    get paginatedGroupedAccSpecific() {
        const start = (this.state.accSpecificPage - 1) * this.state.pageSize;
        return this.groupedAccSpecific.slice(start, start + this.state.pageSize);
    }

    get paginatedAccSpecific() {
        const start = (this.state.accSpecificPage - 1) * this.state.pageSize;
        return this.filteredAccSpecific.slice(start, start + this.state.pageSize);
    }

    get accSpecificPagerInfo() {
        const total = this.state.accEnableGrouping
            ? this.groupedAccSpecific.length
            : this.filteredAccSpecific.length;
        if (total === 0) return "0 / 0";
        const start = (this.state.accSpecificPage - 1) * this.state.pageSize + 1;
        const end = Math.min(this.state.accSpecificPage * this.state.pageSize, total);
        return `${start}-${end} / ${total}`;
    }

    prevAccSpecificPage() {
        if (this.state.accSpecificPage > 1) {
            this.state.accSpecificPage--;
        }
    }

    nextAccSpecificPage() {
        if (this.state.accSpecificPage < this.accSpecificTotalPages) {
            this.state.accSpecificPage++;
        }
    }

    // Group Price Change
    onAccGroupPriceChange(group, ev) {
        const val = this.parsePrice(ev.target.value);
        for (const lineId of group.line_ids) {
            this.state.accSpecificChanges[lineId] = val;
        }
        ev.target.value = this.formatPrice(val);
    }

    getAccGroupPriceFormatted(group) {
        const firstLineId = group.line_ids[0];
        const val =
            firstLineId in this.state.accSpecificChanges
                ? this.state.accSpecificChanges[firstLineId]
                : group.original_price;
        return this.formatPrice(val);
    }

    isAccGroupPriceChanged(group) {
        const firstLineId = group.line_ids[0];
        return (
            firstLineId in this.state.accSpecificChanges &&
            this.state.accSpecificChanges[firstLineId] !== group.original_price
        );
    }

    // Individual Line Price Change
    onAccSpecificPriceChange(lineId, ev) {
        const val = this.parsePrice(ev.target.value);
        this.state.accSpecificChanges[lineId] = val;
        ev.target.value = this.formatPrice(val);
    }

    getAccSpecificPriceFormatted(line) {
        const val =
            line.line_id in this.state.accSpecificChanges
                ? this.state.accSpecificChanges[line.line_id]
                : line.price;
        return this.formatPrice(val);
    }

    isAccSpecificPriceChanged(line) {
        return (
            line.line_id in this.state.accSpecificChanges &&
            this.state.accSpecificChanges[line.line_id] !== line.price
        );
    }

    get accSpecificChangesCount() {
        let count = 0;
        for (const line of this.state.accSpecific) {
            if (this.isAccSpecificPriceChanged(line)) {
                count++;
            }
        }
        return count;
    }

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
