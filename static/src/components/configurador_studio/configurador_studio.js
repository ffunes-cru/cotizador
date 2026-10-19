/**
 * @file
 * Configurador Studio (acción cliente `cotizador_configurator_studio`).
 *
 * Editor visual de la matriz de UNA máquina, para el Administrador del Configurador. Se abre
 * desde el menú o con el botón *Configurador Studio* de la ficha de la máquina.
 *
 * La matriz se muestra como un **árbol de columnas**: una columna por atributo (en el orden de
 * la plantilla); elegir un valor abre la columna siguiente. Cada nodo muestra cuántas
 * configuraciones existen bajo esa rama sobre el total teórico. Al elegir todos los
 * atributos aparece la **hoja**: la configuración de esa combinación (precio y código editables,
 * o el botón para habilitarla).
 *
 * Servidor: `cotizador.studio.service` (models/studio_service.py).
 * Plantilla: configurador_studio.xml (`cotizador.ConfiguradorStudioTemplate`).
 */

import { registry } from "@web/core/registry";
import { Component, useState, onWillStart, useRef } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

/**
 * Componente OWL del Studio.
 *
 * Estado principal: `models`, `selectedModelId`, `modelData` (respuesta de
 * get_model_studio_data), `treePath` (ids de valor elegidos, uno por columna) y el estado de
 * la edición en la hoja y de los modales (rama completa y nueva configuración).
 */
export class CotizadorConfiguratorStudio extends Component {
    static template = "cotizador.ConfiguradorStudioTemplate";

    /** Inicializa servicios y estado; carga las máquinas y, si la acción trae una, su matriz. */
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

    /**
     * Carga la lista de máquinas con sus métricas.
     * @returns {Promise<void>}
     */
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

    /**
     * Elige una máquina y carga su matriz; reinicia el árbol.
     * @param modelId Id de la máquina.
     * @returns {Promise<void>}
     */
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

    /**
     * Cambio del selector de máquina.
     * @param ev Evento `change` del `<select>`.
     */
    onSelectModelChange(ev) {
        this.selectModel(parseInt(ev.target.value));
    }

    /** Muestra u oculta la franja de indicadores. */
    toggleKpis() {
        this.state.showKpis = !this.state.showKpis;
    }

    /**
     * Porcentaje de variantes o configuraciones con código de ingeniería.
     * @returns {number}
     */
    get codedPercentage() {
        if (!this.state.modelData || !this.state.modelData.total_variants) return 0;
        return Math.round((this.state.modelData.coded_variants / this.state.modelData.total_variants) * 100);
    }

    // -------------------------------------------------------------------------
    // NAVEGACIÓN EN ÁRBOL JERÁRQUICO (COLUMNAS INTERACTIVAS)
    // -------------------------------------------------------------------------

    /**
     * Elige un valor en una columna: corta el camino en ese nivel, agrega el valor y
     * desplaza el árbol hacia la nueva columna.
     * @param levelIndex Nivel (índice del atributo).
     * @param valueId Id del valor elegido.
     */
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

    /**
     * Vuelve a un nivel del árbol (miga de pan).
     * @param levelIndex Nivel al que se vuelve.
     */
    jumpToTreeLevel(levelIndex) {
        this.state.treePath = this.state.treePath.slice(0, levelIndex);
        this.state.isEditingLeafPrice = false;
        this.state.isEditingLeafExtId = false;
    }

    /** Vuelve a la raíz del árbol. */
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

    /** Muestra u oculta las ramas sin ninguna configuración. */
    toggleHideZeroPercent() {
        this.state.hideZeroPercent = !this.state.hideZeroPercent;
    }

    /**
     * Cobertura de una rama: configuraciones existentes sobre combinaciones posibles.
     * @param partialValueIds Ids de valor desde la raíz hasta la rama.
     * @returns {Object} {active, total, percent, missing}. `percent` es al menos 1 si hay alguna.
     */
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

    /**
     * Columnas a dibujar: una por nivel abierto y, si se eligieron todos los atributos,
     * la hoja con la configuración de esa combinación (o los datos para crearla).
     * @returns {Object[]} [{level, attribute, isLeafLevel, nodes, leafData}]
     */
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

    /**
     * Miga de pan del camino actual.
     * @returns {Object[]} [{level, attrName, valName, valId}]
     */
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

    /**
     * Texto de una combinación: nombres de los valores separados por " • ".
     * @param valIds Ids de valor.
     * @returns {string}
     */
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

    /**
     * Empieza a editar el precio de la hoja.
     * @param currentPrice Precio actual.
     */
    startEditLeafPrice(currentPrice) {
        this.state.isEditingLeafPrice = true;
        this.state.leafEditingPrice = currentPrice;
    }

    /** Cancela la edición del precio de la hoja. */
    cancelLeafPrice() {
        this.state.isEditingLeafPrice = false;
    }

    /**
     * Entrada del precio en edición.
     * @param ev Evento `input`.
     */
    onLeafEditingPriceInput(ev) {
        this.state.leafEditingPrice = ev.target.value;
    }

    /**
     * Guarda el precio editado de una configuración.
     * @param configId Id de la configuración.
     * @returns {Promise<void>}
     */
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

    /**
     * Empieza a editar el código de ingeniería de la hoja.
     * @param currentExtId Código actual.
     */
    startEditLeafExtId(currentExtId) {
        this.state.isEditingLeafExtId = true;
        this.state.leafEditingExtId = currentExtId || "";
    }

    /** Cancela la edición del código de la hoja. */
    cancelLeafExtId() {
        this.state.isEditingLeafExtId = false;
    }

    /**
     * Entrada del código en edición.
     * @param ev Evento `input`.
     */
    onLeafEditingExtIdInput(ev) {
        this.state.leafEditingExtId = ev.target.value;
    }

    /**
     * Guarda el código de ingeniería de una configuración (y lo copia a la variante).
     * @param configId Id de la configuración.
     * @returns {Promise<void>}
     */
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

    /**
     * Entrada del precio de una configuración a crear.
     * @param ev Evento `input`.
     */
    onLeafNewPriceInput(ev) {
        this.state.leafNewPrice = ev.target.value;
    }

    /**
     * Entrada del código de una configuración a crear.
     * @param ev Evento `input`.
     */
    onLeafNewExtIdInput(ev) {
        this.state.leafNewExtId = ev.target.value;
    }

    /**
     * Habilita la combinación de la hoja: crea su configuración.
     * @param combo Ids de valor de la combinación.
     * @returns {Promise<void>}
     */
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

    /**
     * Deshabilita una combinación (borra la configuración), previa confirmación.
     * @param configId Id de la configuración.
     * @returns {Promise<void>}
     */
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

    /**
     * Abre el modal para habilitar todas las combinaciones faltantes de una rama.
     * @param combo Ids de valor de la rama.
     * @param valName Nombre del valor de la rama (para el título).
     * @param missingCount Combinaciones que se crearían.
     */
    openBranchCreateModal(combo, valName, missingCount) {
        this.state.branchPartialValueIds = combo;
        this.state.branchLabel = `${valName} (${this.getComboLabel(combo)})`;
        this.state.branchMissingCount = missingCount;
        this.state.branchBasePrice = (this.state.modelData.modelo && this.state.modelData.modelo.list_price) || 0;
        this.state.showBranchModal = true;
    }

    /** Cierra el modal de rama completa. */
    closeBranchCreateModal() {
        this.state.showBranchModal = false;
    }

    /**
     * Entrada del precio base de la rama.
     * @param ev Evento `input`.
     */
    onBranchBasePriceInput(ev) {
        this.state.branchBasePrice = ev.target.value;
    }

    /**
     * Crea en bloque las combinaciones faltantes de la rama con el precio base.
     * @returns {Promise<void>}
     */
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

    /** Abre el modal para crear una configuración eligiendo un valor por atributo. */
    openNewConfigWizard() {
        this.state.wizardSelectedValues = {};
        this.state.wizardPrice = (this.state.modelData && this.state.modelData.modelo && this.state.modelData.modelo.list_price) || 0;
        this.state.wizardExtId = "";
        this.state.showNewConfigWizardModal = true;
    }

    /** Cierra el modal de nueva configuración. */
    closeNewConfigWizard() {
        this.state.showNewConfigWizardModal = false;
    }

    /**
     * Elección de un valor en el modal de nueva configuración.
     * @param attrId Id del atributo.
     * @param ev Evento `change` del `<select>`.
     */
    onWizardValueChange(attrId, ev) {
        this.state.wizardSelectedValues[attrId] = parseInt(ev.target.value) || null;
    }

    /**
     * Entrada del precio en el modal de nueva configuración.
     * @param ev Evento `input`.
     */
    onWizardPriceInput(ev) {
        this.state.wizardPrice = ev.target.value;
    }

    /**
     * Entrada del código en el modal de nueva configuración.
     * @param ev Evento `input`.
     */
    onWizardExtIdInput(ev) {
        this.state.wizardExtId = ev.target.value;
    }

    /**
     * Crea la configuración del modal (exige un valor por atributo).
     * @returns {Promise<void>}
     */
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

    /** Abre el asistente de códigos Teamcenter para la máquina elegida. */
    openEngineeringWizard() {
        this.action.doAction("cotizador.action_engineering_code_wizard", {
            additionalContext: {
                default_modelo_id: this.state.selectedModelId,
            },
        });
    }

    /** Abre el importador CSV. */
    openImportWizard() {
        this.action.doAction("cotizador.action_sembradora_import_wizard");
    }

    /** Abre la lista estándar de configuraciones de la máquina (vista "Raw"). */
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

    /**
     * Formatea un importe en la Moneda del Cotizador de la máquina elegida, sin decimales.
     * @param amount Importe (number).
     * @returns {string}
     */
    formatCurrency(amount) {
        return new Intl.NumberFormat("es-AR", {
            style: "currency",
            currency: this.state.modelData.modelo.currency,
            maximumFractionDigits: 0,
        }).format(amount || 0);
    }
}

registry.category("actions").add("cotizador_configurator_studio", CotizadorConfiguratorStudio);
