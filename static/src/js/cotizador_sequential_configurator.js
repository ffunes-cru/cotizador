/** @odoo-module **/

import { Interaction } from '@web/public/interaction';
import { registry } from '@web/core/registry';

function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

export class CotizadorSequentialConfigurator extends Interaction {
    static selector = '#cotizador_sequential_wizard';

    setup() {
        const dataScript = this.el.querySelector('#cotizador_config_data');
        if (!dataScript) {
            return;
        }

        let rawText = (dataScript.textContent || dataScript.innerHTML || '').trim();
        if (!rawText) {
            return;
        }

        // Decodificar entidades HTML si fueron escapadas por QWeb
        if (rawText.includes('&quot;') || rawText.includes('&#34;') || rawText.includes('&amp;')) {
            rawText = rawText
                .replace(/&quot;|&#34;/g, '"')
                .replace(/&amp;/g, '&')
                .replace(/&lt;/g, '<')
                .replace(/&gt;/g, '>');
        }

        try {
            this.configData = JSON.parse(rawText);
        } catch (e) {
            console.error('[Cotizador] Error crítico al parsear JSON:', e);
            return;
        }

        this.steps = this.configData.steps || [];
        this.configs = this.configData.configs || [];
        this.currencySymbol = this.configData.currency_symbol || '$';
        this.templateName = this.configData.template_name || '';

        this.selectedValues = {}; // { stepIndex: val_id }
        this.selectedPtavs = {};  // { stepIndex: ptav_id }
        this.selectedNames = {};  // { stepIndex: val_name }
        this.currentStep = 0;
        this.isCompleted = false;

        // Elementos DOM dentro del widget
        this.stepBadge = this.el.querySelector('#cotizador_step_badge');
        this.progressBar = this.el.querySelector('#cotizador_progress_bar');
        this.chipsContainer = this.el.querySelector('#cotizador_selected_chips');
        this.activeStepContainer = this.el.querySelector('#cotizador_active_step_container');
        this.summaryBox = this.el.querySelector('#cotizador_summary_box');
        this.upcomingContainer = this.el.querySelector('#cotizador_upcoming_steps');
        this.btnPrev = this.el.querySelector('#btn_cotizador_prev');
        this.btnReset = this.el.querySelector('#btn_cotizador_reset');

        // Botones externos en la ficha de producto
        this.btnSolicitar = document.getElementById('btn_solicitar_cotizacion');
        this.btnAddToCart = document.getElementById('add_to_cart');
        this.actionNotice = document.getElementById('cotizador_action_notice');
        this.actionNoticeText = document.getElementById('cotizador_action_notice_text');

        if (this.btnReset) {
            this.btnReset.addEventListener('click', (e) => {
                e.preventDefault();
                this.resetConfig();
            });
        }

        if (this.btnPrev) {
            this.btnPrev.addEventListener('click', (e) => {
                e.preventDefault();
                if (this.currentStep > 0) {
                    this.goToStep(this.currentStep - 1);
                }
            });
        }

        this.render();
    }

    formatOptionName(stepIndex, name) {
        if (!name) return '';
        const stepName = (this.steps[stepIndex]?.name || '').toLowerCase();
        const trimmed = String(name).trim();

        if (stepName.includes('distancia')) {
            return trimmed.toLowerCase().includes('cm') ? trimmed : `${trimmed} cm`;
        }
        if (stepName.includes('cantidad') || stepName.includes('líneas') || stepName.includes('lineas')) {
            return trimmed.toLowerCase().includes('línea') || trimmed.toLowerCase().includes('linea')
                ? trimmed
                : `${trimmed} Líneas`;
        }
        if (stepName.includes('tecnolog')) {
            if (trimmed.toUpperCase() === 'PP') return 'Precision Planting (PP)';
            return trimmed;
        }
        return trimmed;
    }

    formatMoney(amount) {
        return this.currencySymbol + ' ' + (amount || 0).toLocaleString('es-AR', {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
        });
    }

    getMatchingConfigs(currentSelections) {
        const selValIds = Object.values(currentSelections);
        if (!selValIds.length) {
            return this.configs;
        }
        return this.configs.filter(c => {
            const configVals = new Set(c.val_ids);
            return selValIds.every(vId => configVals.has(vId));
        });
    }

    selectValue(stepIndex, valId, ptavId, valName) {
        this.selectedValues[stepIndex] = valId;
        this.selectedPtavs[stepIndex] = ptavId;
        this.selectedNames[stepIndex] = valName;

        if (stepIndex + 1 < this.steps.length) {
            this.currentStep = stepIndex + 1;
            this.isCompleted = false;
        } else {
            this.isCompleted = true;
        }

        this.render();
    }

    goToStep(stepIndex) {
        for (let k = stepIndex; k < this.steps.length; k++) {
            delete this.selectedValues[k];
            delete this.selectedPtavs[k];
            delete this.selectedNames[k];
        }
        this.currentStep = stepIndex;
        this.isCompleted = false;
        this.render();
    }

    resetConfig() {
        this.selectedValues = {};
        this.selectedPtavs = {};
        this.selectedNames = {};
        this.currentStep = 0;
        this.isCompleted = false;
        this.render();
    }

    render() {
        if (!this.steps.length) {
            if (this.activeStepContainer) {
                this.activeStepContainer.innerHTML = '<div class="alert alert-secondary py-3 px-3">Este producto no cuenta con especificaciones configurables.</div>';
            }
            return;
        }

        if (!this.configs.length) {
            if (this.activeStepContainer) {
                this.activeStepContainer.innerHTML = '<div class="alert alert-info py-3 px-3"><i class="fa fa-info-circle me-1"></i> Este modelo no cuenta con combinaciones de ingeniería registradas en el sistema. Puede solicitar la cotización directamente con nuestros asesores comerciales.</div>';
            }
            if (this.btnSolicitar) {
                this.btnSolicitar.removeAttribute('disabled');
                this.btnSolicitar.classList.remove('disabled', 'opacity-50');
            }
            if (this.actionNotice) {
                this.actionNotice.classList.add('d-none');
            }
            return;
        }

        const totalSteps = this.steps.length;

        // 1. Barra de progreso y Badge
        const progressPct = this.isCompleted
            ? 100
            : Math.round(((this.currentStep + 1) / totalSteps) * 100);

        if (this.progressBar) {
            this.progressBar.style.width = `${progressPct}%`;
        }
        if (this.stepBadge) {
            if (this.isCompleted) {
                this.stepBadge.className = 'badge rounded-pill bg-success text-white px-3 py-1 fw-bold';
                this.stepBadge.innerHTML = '<i class="fa fa-check me-1"></i> 100% Configurado';
            } else {
                this.stepBadge.className = 'badge rounded-pill bg-danger-subtle text-danger border border-danger-subtle px-3 py-1 fw-semibold';
                this.stepBadge.textContent = `Paso ${this.currentStep + 1} de ${totalSteps}`;
            }
        }

        // 2. Fila de Especificaciones Seleccionadas (Chips compactos)
        const selectedCount = Object.keys(this.selectedValues).length;
        if (this.chipsContainer) {
            if (selectedCount > 0) {
                this.chipsContainer.classList.remove('d-none');
                let chipsHtml = '<span class="text-muted small align-self-center me-1 fw-semibold"><i class="fa fa-check-circle text-success me-1"></i>Elegido:</span>';
                for (let i = 0; i < selectedCount; i++) {
                    const stepName = escapeHtml(this.steps[i]?.name || `Paso ${i + 1}`);
                    const optLabel = escapeHtml(this.formatOptionName(i, this.selectedNames[i]));
                    chipsHtml += `
                        <button type="button" class="cotizador-chip" data-step-idx="${i}" title="Haga clic para modificar">
                            <span class="cotizador-chip-label text-muted me-1">${stepName}:</span>
                            <strong class="text-dark">${optLabel}</strong>
                            <i class="fa fa-pencil text-muted ms-1 small"></i>
                        </button>
                    `;
                }
                this.chipsContainer.innerHTML = chipsHtml;
                this.chipsContainer.querySelectorAll('.cotizador-chip').forEach(chip => {
                    chip.addEventListener('click', () => {
                        const stepIdx = parseInt(chip.getAttribute('data-step-idx'));
                        this.goToStep(stepIdx);
                    });
                });
            } else {
                this.chipsContainer.classList.add('d-none');
                this.chipsContainer.innerHTML = '';
            }
        }

        // 3. Botón Paso Anterior
        if (this.btnPrev) {
            if (this.currentStep > 0 && !this.isCompleted) {
                this.btnPrev.classList.remove('d-none');
            } else {
                this.btnPrev.classList.add('d-none');
            }
        }

        // 4. Contenido del Paso Activo vs Resumen Completo
        if (this.isCompleted) {
            // OCULTAR paso activo y próximos pasos
            if (this.activeStepContainer) {
                this.activeStepContainer.innerHTML = '';
                this.activeStepContainer.classList.add('d-none');
            }
            if (this.upcomingContainer) {
                this.upcomingContainer.innerHTML = '';
                this.upcomingContainer.classList.add('d-none');
            }

            // MOSTRAR Resumen
            const finalConfigs = this.getMatchingConfigs(this.selectedValues);
            const matchingConfig = finalConfigs[0] || null;

            if (this.summaryBox && matchingConfig) {
                this.summaryBox.classList.remove('d-none');
                this.summaryBox.innerHTML = `
                    <div class="cotizador-summary-card shadow-sm">
                        <div class="d-flex align-items-center mb-2">
                            <span class="badge bg-success px-2 py-1 me-2">
                                <i class="fa fa-check-circle me-1"></i> Configuración Lista
                            </span>
                        </div>
                        <h5 class="fw-bold text-dark mb-1">${escapeHtml(matchingConfig.name)}</h5>
                        <div class="d-flex justify-content-between align-items-baseline mt-3 pt-2 border-top border-success-subtle">
                            <span class="text-muted small">Precio de Lista Base:</span>
                            <span class="fs-4 fw-bold text-success">${escapeHtml(this.formatMoney(matchingConfig.price))}</span>
                        </div>
                    </div>
                `;
            }

            // Habilitar botón de cotización
            if (this.btnSolicitar) {
                this.btnSolicitar.removeAttribute('disabled');
                this.btnSolicitar.classList.remove('disabled', 'opacity-50');
            }
            if (this.btnAddToCart) {
                this.btnAddToCart.classList.remove('disabled', 'opacity-50');
                this.btnAddToCart.style.pointerEvents = '';
            }
            if (this.actionNotice && this.actionNoticeText) {
                this.actionNotice.className = 'alert alert-success py-2 px-3 small d-flex align-items-center mb-2';
                this.actionNoticeText.innerHTML = '<i class="fa fa-check-circle me-2 fs-6"></i><strong>¡Configuración lista!</strong> Haga clic en el botón inferior para solicitar su presupuesto oficial.';
            }

            // Sincronizar variantes y modal
            if (matchingConfig) {
                if (matchingConfig.val_ids) {
                    matchingConfig.val_ids.forEach(vId => {
                        const radio = document.querySelector(`input.js_variant_change[data-attribute-value-id="${vId}"]`);
                        if (radio) {
                            radio.checked = true;
                        }
                    });
                    const checkedRadio = document.querySelector('input.js_variant_change:checked');
                    if (checkedRadio) {
                        checkedRadio.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                }
                const modalConfigId = document.querySelector('#modal_solicitar_cotizacion input[name="config_id"]');
                if (modalConfigId) {
                    modalConfigId.value = matchingConfig.id;
                }
                const modalSummary = document.getElementById('modal_config_summary_text');
                if (modalSummary) {
                    modalSummary.innerHTML = `<strong>${escapeHtml(matchingConfig.name)}</strong><br/><span class="text-muted small">Precio base: ${escapeHtml(this.formatMoney(matchingConfig.price))}</span>`;
                }
            }

        } else {
            // ESTADO ACTIVO (Paso actual)
            if (this.summaryBox) {
                this.summaryBox.classList.add('d-none');
            }
            if (this.activeStepContainer) {
                this.activeStepContainer.classList.remove('d-none');

                const currentStepObj = this.steps[this.currentStep];
                const availableConfigs = this.getMatchingConfigs(this.selectedValues);

                // Obtener opciones válidas
                const validValIds = new Set();
                availableConfigs.forEach(c => {
                    c.val_ids.forEach(vId => validValIds.add(vId));
                });
                const validOptions = currentStepObj.values.filter(v => validValIds.has(v.val_id));

                let optionsHtml = '';
                validOptions.forEach(opt => {
                    const formatted = this.formatOptionName(this.currentStep, opt.name);

                    // Calcular rango de precios resultante si el usuario selecciona esta opción
                    const simulatedSelections = { ...this.selectedValues, [this.currentStep]: opt.val_id };
                    const matchingConfigsForOpt = this.getMatchingConfigs(simulatedSelections);
                    const prices = matchingConfigsForOpt
                        .map(c => c.price)
                        .filter(p => typeof p === 'number' && !isNaN(p) && p > 0);

                    let priceStr = '';
                    if (prices.length > 0) {
                        const minPrice = Math.min(...prices);
                        const maxPrice = Math.max(...prices);
                        const minStr = Math.round(minPrice).toLocaleString('es-AR');
                        const maxStr = Math.round(maxPrice).toLocaleString('es-AR');
                        if (minPrice === maxPrice) {
                            priceStr = `(${this.currencySymbol} ${minStr})`;
                        } else {
                            priceStr = `(${this.currencySymbol} ${minStr} - ${this.currencySymbol} ${maxStr})`;
                        }
                    }

                    optionsHtml += `
                        <button type="button" 
                                class="cotizador-option-card text-start" 
                                data-val-id="${opt.val_id}" 
                                data-ptav-id="${opt.ptav_id}" 
                                data-val-name="${escapeHtml(opt.name)}">
                            <span class="cotizador-option-name">${escapeHtml(formatted)}</span>
                            ${priceStr ? `<span class="cotizador-option-price">${escapeHtml(priceStr)}</span>` : ''}
                        </button>
                    `;
                });

                this.activeStepContainer.innerHTML = `
                    <div class="mb-3">
                        <div class="cotizador-step-title">
                            Seleccione ${escapeHtml(currentStepObj.name)}
                        </div>
                        <div class="cotizador-step-subtitle">
                            ${validOptions.length} ${validOptions.length === 1 ? 'opción compatible' : 'opciones compatibles'} de ingeniería Crucianelli
                        </div>
                    </div>
                    <div class="cotizador-options-grid">
                        ${optionsHtml}
                    </div>
                `;

                this.activeStepContainer.querySelectorAll('.cotizador-option-card').forEach(btn => {
                    btn.addEventListener('click', (e) => {
                        e.stopPropagation();
                        const valId = parseInt(btn.getAttribute('data-val-id'));
                        const ptavId = parseInt(btn.getAttribute('data-ptav-id'));
                        const valName = btn.getAttribute('data-val-name');
                        this.selectValue(this.currentStep, valId, ptavId, valName);
                    });
                });
            }

            // Próximos pasos sutiles
            if (this.upcomingContainer) {
                const upcoming = [];
                for (let s = this.currentStep + 1; s < totalSteps; s++) {
                    upcoming.push(`${s + 1}. ${escapeHtml(this.steps[s].name)}`);
                }
                if (upcoming.length > 0) {
                    this.upcomingContainer.classList.remove('d-none');
                    this.upcomingContainer.innerHTML = `
                        <div class="text-muted small">
                            <i class="fa fa-angle-double-right me-1"></i>Próximos pasos: <strong class="text-dark">${upcoming.join('  ·  ')}</strong>
                        </div>
                    `;
                } else {
                    this.upcomingContainer.classList.add('d-none');
                    this.upcomingContainer.innerHTML = '';
                }
            }

            // Deshabilitar botón cotización
            if (this.btnSolicitar) {
                this.btnSolicitar.setAttribute('disabled', 'disabled');
                this.btnSolicitar.classList.add('disabled', 'opacity-50');
            }
            if (this.btnAddToCart) {
                this.btnAddToCart.classList.add('disabled', 'opacity-50');
                this.btnAddToCart.style.pointerEvents = 'none';
            }
            if (this.actionNotice && this.actionNoticeText) {
                this.actionNotice.className = 'alert alert-warning py-2 px-3 small d-flex align-items-center mb-2';
                this.actionNoticeText.innerHTML = `<i class="fa fa-exclamation-circle me-2 fs-6"></i>Complete el <strong>Paso ${this.currentStep + 1} de ${totalSteps}</strong> (${escapeHtml(this.steps[this.currentStep].name)}) para habilitar la cotización.`;
            }
        }
    }
}

registry
    .category('public.interactions')
    .add('cotizador.sequential_configurator', CotizadorSequentialConfigurator);
