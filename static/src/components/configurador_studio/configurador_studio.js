/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useState, onWillStart, useRef } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

export class CotizadorConfiguratorStudio extends Component {
    static template = "cotizador.ConfiguradorStudioTemplate";

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.action = useService("action");
        this.rootRef = useRef("root");
        this.treeCanvasRef = useRef("treeCanvas");

        // Context / Params iniciales
        const initModelId =
            (this.props.action && this.props.action.context && this.props.action.context.default_modelo_id) ||
            (this.props.action && this.props.action.params && this.props.action.params.modelo_id) ||
            null;

        this.state = useState({
            loading: true,
            loadingModel: false,
            models: [],
            selectedModelId: initModelId,
            modelData: null,

            // Desplegable de KPIs superiores (por defecto colapsado para máximo espacio)
            showKpis: false,

            // Ruta de navegación activa en el árbol: array de value_ids [val0, val1, ...]
            treePath: [],

            // Ocultar opciones con 0% activas (por defecto true)
            hideZeroPercent: true,

            // Edición rápida de precio en la hoja del árbol
            isEditingLeafPrice: false,
            leafEditingPrice: 0,

            // Edición rápida de código de ingeniería (Teamcenter) en la hoja del árbol
            isEditingLeafExtId: false,
            leafEditingExtId: "",

            // Campos para nueva configuración desde hoja inactiva
            leafNewPrice: 0,
            leafNewExtId: "",

            // Modal: Habilitar Rama Completa (masivo)
            showBranchModal: false,
            branchPartialValueIds: [],
            branchLabel: "",
            branchMissingCount: 0,
            branchBasePrice: 0,

            // Modal: Asistente Nueva Configuración (cabecera)
            showNewConfigWizardModal: false,
            wizardSelectedValues: {}, // attr_id -> val_id
            wizardPrice: 0,
            wizardExtId: "",
        });

        onWillStart(async () => {
            await this.loadOverview();
            if (this.state.selectedModelId) {
                await this.selectModel(this.state.selectedModelId);
            }
        });
    }

    // -------------------------------------------------------------------------
    // CARGA DE DATOS DEL MODELO
    // -------------------------------------------------------------------------

    async loadOverview() {
        this.state.loading = true;
        try {
            const result = await this.orm.call(
                "cotizador.studio.service",
                "get_studio_overview",
                []
            );
            this.state.models = result || [];
            if (!this.state.selectedModelId && this.state.models.length > 0) {
                await this.selectModel(this.state.models[0].id);
            }
        } catch (error) {
            this.notification.add(_t("Error al cargar modelos: ") + error.message, { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    async selectModel(modelId) {
        this.state.loadingModel = true;
        this.state.selectedModelId = modelId;
        this.state.treePath = [];
        this.state.isEditingLeafPrice = false;
        this.state.isEditingLeafExtId = false;

        try {
            const data = await this.orm.call(
                "cotizador.studio.service",
                "get_model_studio_data",
                [modelId]
            );
            this.state.modelData = data;
        } catch (error) {
            this.notification.add(_t("Error al cargar datos del modelo: ") + error.message, { type: "danger" });
        } finally {
            this.state.loadingModel = false;
        }
    }

    onSelectModelChange(ev) {
        this.selectModel(parseInt(ev.target.value));
    }

    toggleKpis() {
        this.state.showKpis = !this.state.showKpis;
    }

    get codedPercentage() {
        if (!this.state.modelData || !this.state.modelData.total_variants) return 0;
        return Math.round((this.state.modelData.coded_variants / this.state.modelData.total_variants) * 100);
    }

    // -------------------------------------------------------------------------
    // NAVEGACIÓN EN ÁRBOL JERÁRQUICO (COLUMNAS INTERACTIVAS)
    // -------------------------------------------------------------------------

    selectTreeNode(levelIndex, valueId) {
        const newPath = this.state.treePath.slice(0, levelIndex);
        newPath.push(valueId);
        this.state.treePath = newPath;
        this.state.isEditingLeafPrice = false;
        this.state.isEditingLeafExtId = false;

        // Auto-scroll horizontal suave para enfocar la nueva columna abierta a la derecha
        setTimeout(() => {
            if (this.treeCanvasRef && this.treeCanvasRef.el) {
                this.treeCanvasRef.el.scrollTo({
                    left: this.treeCanvasRef.el.scrollWidth,
                    behavior: "smooth",
                });
            }
        }, 60);
    }

    jumpToTreeLevel(levelIndex) {
        this.state.treePath = this.state.treePath.slice(0, levelIndex);
        this.state.isEditingLeafPrice = false;
        this.state.isEditingLeafExtId = false;
    }

    resetTreePath() {
        this.state.treePath = [];
        this.state.isEditingLeafPrice = false;
        this.state.isEditingLeafExtId = false;
        setTimeout(() => {
            if (this.treeCanvasRef && this.treeCanvasRef.el) {
                this.treeCanvasRef.el.scrollTo({ left: 0, behavior: "smooth" });
            }
        }, 50);
    }

    toggleHideZeroPercent() {
        this.state.hideZeroPercent = !this.state.hideZeroPercent;
    }

    getNodeStats(partialValueIds) {
        if (!this.state.modelData || !this.state.modelData.configs || !this.state.modelData.attributes) {
            return { active: 0, total: 0, percent: 0, missing: 0 };
        }
        const configs = this.state.modelData.configs;
        const attrs = this.state.modelData.attributes;

        // Configuraciones activas que contienen todos los IDs de esta ruta parcial
        const active = configs.filter((c) =>
            partialValueIds.every((vid) => c.value_ids.includes(vid))
        ).length;

        // Combinaciones totales posibles bajo esta rama
        const coveredAttrCount = partialValueIds.length;
        let total = 1;
        for (let i = coveredAttrCount; i < attrs.length; i++) {
            total *= (attrs[i].values.length || 1);
        }

        const percent = active === 0 ? 0 : Math.max(1, Math.round((active / total) * 100));
        const missing = Math.max(0, total - active);
        return { active, total, percent, missing };
    }

    get treeColumns() {
        if (!this.state.modelData || !this.state.modelData.attributes) return [];
        const attrs = this.state.modelData.attributes;
        if (attrs.length === 0) return [];

        const columns = [];
        const currentPath = this.state.treePath;
        const maxAttrLevel = Math.min(currentPath.length, attrs.length - 1);
        const hasAnyConfigs = Boolean(this.state.modelData.configs && this.state.modelData.configs.length > 0);

        // 1. Columnas de Atributos (de 0 a maxAttrLevel)
        for (let lvl = 0; lvl <= maxAttrLevel; lvl++) {
            const attr = attrs[lvl];
            const parentPath = currentPath.slice(0, lvl);

            let nodes = attr.values.map((val) => {
                const currentCombo = [...parentPath, val.id];
                const isSelected = currentPath[lvl] === val.id;
                const stats = this.getNodeStats(currentCombo);

                return {
                    id: val.id,
                    name: val.name,
                    attrId: attr.id,
                    attrName: attr.name,
                    combo: currentCombo,
                    isSelected,
                    stats,
                };
            });

            // Si está activo ocultar 0% y el modelo tiene configuraciones, filtrar las ramas en 0%
            if (this.state.hideZeroPercent && hasAnyConfigs) {
                nodes = nodes.filter((n) => n.stats.active > 0);
            }

            columns.push({
                level: lvl,
                attribute: attr,
                isLeafLevel: false,
                nodes,
            });
        }

        // 2. Columna Final de Configuración (Hoja)
        // Se despliega cuando se han seleccionado TODOS los N atributos
        if (currentPath.length === attrs.length && attrs.length > 0) {
            const leafCombo = [...currentPath];
            const matchedConfig = this.state.modelData.configs.find((c) =>
                c.value_ids.length === leafCombo.length &&
                leafCombo.every((vid) => c.value_ids.includes(vid))
            ) || null;

            const defaultPrice = (this.state.modelData.modelo && this.state.modelData.modelo.list_price) || 0;

            columns.push({
                level: attrs.length,
                isLeafLevel: true,
                leafData: {
                    combo: leafCombo,
                    label: this.getComboLabel(leafCombo),
                    exists: Boolean(matchedConfig),
                    config: matchedConfig,
                    defaultPrice: defaultPrice,
                },
                nodes: [],
            });
        }

        return columns;
    }

    get treeBreadcrumbs() {
        if (!this.state.modelData || !this.state.modelData.attributes) return [];
        const attrs = this.state.modelData.attributes;
        const crumbs = [];

        for (let i = 0; i < this.state.treePath.length; i++) {
            const valId = this.state.treePath[i];
            const attr = attrs[i];
            if (!attr) continue;
            const val = attr.values.find((v) => v.id === valId);
            if (val) {
                crumbs.push({
                    level: i,
                    attrName: attr.name,
                    valName: val.name,
                    valId: val.id,
                });
            }
        }
        return crumbs;
    }

    getComboLabel(valIds) {
        if (!this.state.modelData || !this.state.modelData.attributes) return "";
        const names = [];
        for (const vid of valIds) {
            for (const attr of this.state.modelData.attributes) {
                const val = attr.values.find((v) => v.id === vid);
                if (val) {
                    names.push(val.name);
                    break;
                }
            }
        }
        return names.join(" • ");
    }

    // -------------------------------------------------------------------------
    // EDICIÓN DE PRECIO Y CÓDIGO DE INGENIERÍA EN HOJA
    // -------------------------------------------------------------------------

    startEditLeafPrice(currentPrice) {
        this.state.isEditingLeafPrice = true;
        this.state.leafEditingPrice = currentPrice;
    }

    cancelLeafPrice() {
        this.state.isEditingLeafPrice = false;
    }

    onLeafEditingPriceInput(ev) {
        this.state.leafEditingPrice = ev.target.value;
    }

    async saveLeafPrice(configId) {
        const newPrice = parseFloat(this.state.leafEditingPrice) || 0;
        try {
            await this.orm.call(
                "cotizador.studio.service",
                "quick_update_config_price",
                [configId, newPrice]
            );
            const cfg = this.state.modelData.configs.find((c) => c.id === configId);
            if (cfg) {
                cfg.price = newPrice;
            }
            this.state.isEditingLeafPrice = false;
            this.notification.add(_t("Precio actualizado correctamente."), { type: "success" });
        } catch (error) {
            this.notification.add(_t("Error al actualizar precio: ") + error.message, { type: "danger" });
        }
    }

    startEditLeafExtId(currentExtId) {
        this.state.isEditingLeafExtId = true;
        this.state.leafEditingExtId = currentExtId || "";
    }

    cancelLeafExtId() {
        this.state.isEditingLeafExtId = false;
    }

    onLeafEditingExtIdInput(ev) {
        this.state.leafEditingExtId = ev.target.value;
    }

    async saveLeafExtId(configId) {
        const newCode = (this.state.leafEditingExtId || "").trim();
        try {
            await this.orm.call(
                "cotizador.studio.service",
                "quick_update_config_engineering_code",
                [configId, newCode]
            );
            const cfg = this.state.modelData.configs.find((c) => c.id === configId);
            if (cfg) {
                cfg.ext_id = newCode;
            }
            this.state.isEditingLeafExtId = false;
            this.notification.add(_t("Código de ingeniería actualizado correctamente."), { type: "success" });
        } catch (error) {
            this.notification.add(_t("Error al actualizar código: ") + error.message, { type: "danger" });
        }
    }

    onLeafNewPriceInput(ev) {
        this.state.leafNewPrice = ev.target.value;
    }

    onLeafNewExtIdInput(ev) {
        this.state.leafNewExtId = ev.target.value;
    }

    async submitQuickCreateLeaf(combo) {
        const defaultPrice = (this.state.modelData.modelo && this.state.modelData.modelo.list_price) || 0;
        const price = parseFloat(this.state.leafNewPrice) || defaultPrice;
        const extId = (this.state.leafNewExtId || "").trim();

        try {
            const res = await this.orm.call(
                "cotizador.studio.service",
                "create_configuration",
                [
                    this.state.selectedModelId,
                    combo,
                    price,
                    extId || null,
                ]
            );
            if (res && res.success && res.config) {
                this.state.modelData.configs.push(res.config);
                this.state.leafNewPrice = 0;
                this.state.leafNewExtId = "";
                this.notification.add(
                    _t("¡Configuración creada y habilitada exitosamente para cotizar!"),
                    { type: "success" }
                );
            }
        } catch (error) {
            this.notification.add(_t("Error al crear configuración: ") + error.message, { type: "danger" });
        }
    }

    async deleteSingleConfig(configId) {
        if (!confirm(_t("¿Está seguro de eliminar esta configuración de la matriz comercial?"))) {
            return;
        }
        try {
            await this.orm.call(
                "cotizador.studio.service",
                "delete_configuration",
                [configId]
            );
            this.state.modelData.configs = this.state.modelData.configs.filter((c) => c.id !== configId);
            this.notification.add(_t("Configuración eliminada exitosamente."), { type: "info" });
        } catch (error) {
            this.notification.add(_t("Error al eliminar configuración: ") + error.message, { type: "danger" });
        }
    }

    // -------------------------------------------------------------------------
    // MODAL DE HABILITACIÓN MASIVA DE RAMA
    // -------------------------------------------------------------------------

    openBranchCreateModal(combo, valName, missingCount) {
        this.state.branchPartialValueIds = combo;
        this.state.branchLabel = `${valName} (${this.getComboLabel(combo)})`;
        this.state.branchMissingCount = missingCount;
        this.state.branchBasePrice = (this.state.modelData.modelo && this.state.modelData.modelo.list_price) || 0;
        this.state.showBranchModal = true;
    }

    closeBranchCreateModal() {
        this.state.showBranchModal = false;
    }

    onBranchBasePriceInput(ev) {
        this.state.branchBasePrice = ev.target.value;
    }

    async submitBranchCreate() {
        const price = parseFloat(this.state.branchBasePrice) || 0;
        try {
            const res = await this.orm.call(
                "cotizador.studio.service",
                "batch_create_branch_configurations",
                [
                    this.state.selectedModelId,
                    this.state.branchPartialValueIds,
                    price,
                ]
            );
            if (res && res.success) {
                this.notification.add(
                    _t(`Se crearon y habilitaron ${res.created_count} configuraciones para la rama seleccionada.`),
                    { type: "success" }
                );
                this.closeBranchCreateModal();
                await this.selectModel(this.state.selectedModelId);
            }
        } catch (error) {
            this.notification.add(_t("Error al generar configuraciones: ") + error.message, { type: "danger" });
        }
    }

    // -------------------------------------------------------------------------
    // MODAL ASISTENTE "+ NUEVA CONFIGURACIÓN" (CABECERA)
    // -------------------------------------------------------------------------

    openNewConfigWizard() {
        this.state.wizardSelectedValues = {};
        this.state.wizardPrice = (this.state.modelData && this.state.modelData.modelo && this.state.modelData.modelo.list_price) || 0;
        this.state.wizardExtId = "";
        this.state.showNewConfigWizardModal = true;
    }

    closeNewConfigWizard() {
        this.state.showNewConfigWizardModal = false;
    }

    onWizardValueChange(attrId, ev) {
        this.state.wizardSelectedValues[attrId] = parseInt(ev.target.value) || null;
    }

    onWizardPriceInput(ev) {
        this.state.wizardPrice = ev.target.value;
    }

    onWizardExtIdInput(ev) {
        this.state.wizardExtId = ev.target.value;
    }

    async submitNewConfigWizard() {
        const attrs = (this.state.modelData && this.state.modelData.attributes) || [];
        const valIds = [];
        for (const attr of attrs) {
            const valId = this.state.wizardSelectedValues[attr.id];
            if (!valId) {
                this.notification.add(_t(`Por favor seleccione una opción para '${attr.name}'`), { type: "warning" });
                return;
            }
            valIds.push(valId);
        }

        const price = parseFloat(this.state.wizardPrice) || 0;
        try {
            const res = await this.orm.call(
                "cotizador.studio.service",
                "create_configuration",
                [
                    this.state.selectedModelId,
                    valIds,
                    price,
                    this.state.wizardExtId || null,
                ]
            );
            if (res && res.success && res.config) {
                this.state.modelData.configs.push(res.config);
                this.notification.add(_t("Nueva configuración creada exitosamente."), { type: "success" });
                this.closeNewConfigWizard();
            }
        } catch (error) {
            this.notification.add(_t("Error al crear configuración: ") + error.message, { type: "danger" });
        }
    }

    // -------------------------------------------------------------------------
    // ACCIONES DE CABECERA Y NAVEGACIÓN
    // -------------------------------------------------------------------------

    openEngineeringWizard() {
        this.action.doAction("cotizador.action_engineering_code_wizard", {
            additionalContext: {
                default_modelo_id: this.state.selectedModelId,
            },
        });
    }

    openImportWizard() {
        this.action.doAction("cotizador.action_sembradora_import_wizard");
    }

    openLegacyRawView() {
        this.action.doAction({
            name: _t("Configuraciones Base (Raw)"),
            type: "ir.actions.act_window",
            res_model: "sembradora.config.rel",
            view_mode: "list,form",
            domain: [["modelo_id", "=", this.state.selectedModelId]],
            context: { default_modelo_id: this.state.selectedModelId },
        });
    }

    formatCurrency(amount) {
        return new Intl.NumberFormat("es-AR", {
            style: "currency",
            currency: "ARS",
            maximumFractionDigits: 0,
        }).format(amount || 0);
    }
}

registry.category("actions").add("cotizador_configurator_studio", CotizadorConfiguratorStudio);
