/**
 * Pipeline Builder for ROI Generation Logic
 *
 * A visual interface for building operation pipelines that define how derived
 * structures are generated from autosegmented structures.
 *
 * The available operations are driven by the shared structure-operation
 * catalog (see dicom_handler/utils/structure_generation/operation_catalog.py)
 * so the SAME operators are offered as in Rule-Based Segmentation. The catalog
 * is passed in via `options.catalog`; each operation declares its
 * `structure_roles` (which structures it consumes) and its `parameters`.
 */

// Literal Tailwind classes per accent color. Kept as a static map (rather than
// building class names at runtime) so the Tailwind JIT scanner detects them.
const OP_COLOR_STYLES = {
    red:     { card: "border-red-200",     pick: "hover:border-red-500 hover:bg-red-50" },
    blue:    { card: "border-blue-200",    pick: "hover:border-blue-500 hover:bg-blue-50" },
    green:   { card: "border-green-200",   pick: "hover:border-green-500 hover:bg-green-50" },
    purple:  { card: "border-purple-200",  pick: "hover:border-purple-500 hover:bg-purple-50" },
    orange:  { card: "border-orange-200",  pick: "hover:border-orange-500 hover:bg-orange-50" },
    cyan:    { card: "border-cyan-200",    pick: "hover:border-cyan-500 hover:bg-cyan-50" },
    indigo:  { card: "border-indigo-200",  pick: "hover:border-indigo-500 hover:bg-indigo-50" },
    teal:    { card: "border-teal-200",    pick: "hover:border-teal-500 hover:bg-teal-50" },
    violet:  { card: "border-violet-200",  pick: "hover:border-violet-500 hover:bg-violet-50" },
    amber:   { card: "border-amber-200",   pick: "hover:border-amber-500 hover:bg-amber-50" },
    rose:    { card: "border-rose-200",    pick: "hover:border-rose-500 hover:bg-rose-50" },
    sky:     { card: "border-sky-200",     pick: "hover:border-sky-500 hover:bg-sky-50" },
    gray:    { card: "border-gray-200",    pick: "hover:border-gray-500 hover:bg-gray-50" },
    pink:    { card: "border-pink-200",    pick: "hover:border-pink-500 hover:bg-pink-50" },
    yellow:  { card: "border-yellow-200",  pick: "hover:border-yellow-500 hover:bg-yellow-50" },
    lime:    { card: "border-lime-200",    pick: "hover:border-lime-500 hover:bg-lime-50" },
    emerald: { card: "border-emerald-200", pick: "hover:border-emerald-500 hover:bg-emerald-50" },
    fuchsia: { card: "border-fuchsia-200", pick: "hover:border-fuchsia-500 hover:bg-fuchsia-50" },
};
function opColorStyle(color) {
    return OP_COLOR_STYLES[color] || OP_COLOR_STYLES.gray;
}

class PipelineBuilder {
    constructor(containerId, options = {}) {
        this.container = document.getElementById(containerId);
        this.options = {
            availableStructures: options.availableStructures || [],
            catalog: options.catalog || [],
            onPipelineChange: options.onPipelineChange || (() => {}),
            ...options
        };

        this.operations = [];
        this.operationCounter = 0;

        // Operations whose primary input is the running (previous) result
        // rather than an explicitly-selected structure. For these, the
        // "source" role is not part of the serialized `structures` list.
        this.chainSourceOps = new Set([
            "smooth", "gaussian_smooth", "fill_holes", "remove_small_components",
            "keep_largest", "keep_n_largest", "close_gaps", "remove_protrusions",
            "crop_to_boundary"
        ]);

        this.init();
    }

    // ------------------------------------------------------------------
    // Catalog helpers
    // ------------------------------------------------------------------

    _opSpec(type) {
        return this.options.catalog.find((s) => s.id === type) || null;
    }

    _legacyTypeMap() {
        // Operation ids used by pipelines saved before the shared catalog.
        // They resolve to a canonical op, with a sign for margin (contract
        // was a positive distance; the canonical margin op is signed).
        return {
            expand: { type: 'margin', sign: 1 },
            contract: { type: 'margin', sign: -1 },
            margin_uniform: { type: 'margin', sign: 1 },
            anisotropic_margin: { type: 'margin', sign: 1 },
        };
    }

    _isChainSource(op, role) {
        return role.name === "source" && this.chainSourceOps.has(op.type);
    }

    // ------------------------------------------------------------------
    // Lifecycle
    // ------------------------------------------------------------------

    init() {
        this.render();
    }

    render() {
        this.container.innerHTML = `
            <div class="pipeline-builder">
                <!-- Operations Pipeline -->
                <div class="mb-4">
                    <div class="flex justify-between items-center mb-3">
                        <label class="block text-sm font-semibold text-gray-700">
                            <span class="text-blue-600">1.</span> Operations Pipeline
                        </label>
                        <button type="button" id="addOperationBtn" class="inline-flex items-center px-3 py-1.5 text-xs font-medium text-white bg-primary-600 hover:bg-primary-700 rounded-md transition-colors">
                            <svg class="w-4 h-4 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/>
                            </svg>
                            Add Operation
                        </button>
                    </div>

                    <div id="operationsList" class="space-y-3 min-h-[100px] p-4 bg-gray-50 rounded-lg border-2 border-dashed border-gray-300">
                        <div class="text-center text-gray-400 text-sm py-8" id="emptyState">
                            No operations added yet. Click "Add Operation" to start building your pipeline.
                        </div>
                    </div>
                </div>

                <!-- JSON Preview -->
                <div class="mb-4">
                    <label class="block text-sm font-semibold text-gray-700 mb-2">
                        <span class="text-blue-600">2.</span> Generated JSON
                        <button type="button" id="copyJsonBtn" class="ml-2 text-xs text-primary-600 hover:text-primary-800">
                            <svg class="w-3 h-3 inline" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"/>
                            </svg>
                            Copy
                        </button>
                    </label>
                    <pre id="jsonPreview" class="p-3 bg-gray-900 text-green-400 rounded-lg text-xs font-mono overflow-x-auto max-h-48 overflow-y-auto">{}</pre>
                </div>

                <!-- Hidden field for form submission -->
                <input type="hidden" id="pipelineJsonField" name="roi_generation_logic">
            </div>
        `;

        this.attachEventListeners();
        this.updateJsonPreview();
    }

    attachEventListeners() {
        document.getElementById('addOperationBtn').addEventListener('click', () => {
            this.showOperationSelector();
        });

        document.getElementById('copyJsonBtn').addEventListener('click', () => {
            const json = document.getElementById('jsonPreview').textContent;
            navigator.clipboard.writeText(json).then(() => {
                this.showToast('JSON copied to clipboard!');
            });
        });
    }

    // ------------------------------------------------------------------
    // Operation picker
    // ------------------------------------------------------------------

    showOperationSelector() {
        const catalog = this.options.catalog;
        if (!catalog.length) {
            this.showToast('Operation catalog is unavailable', 'error');
            return;
        }

        // Group operations by category for a tidy picker.
        const groups = {};
        catalog.forEach((op) => {
            (groups[op.category] = groups[op.category] || []).push(op);
        });

        const groupsHtml = Object.entries(groups).map(([category, ops]) => `
            <div class="mb-4">
                <div class="text-xs uppercase tracking-wide text-gray-400 font-semibold mb-2">${this._escapeHtml(category)}</div>
                <div class="grid grid-cols-2 gap-3">
                    ${ops.map((op) => `
                        <button type="button" class="operation-type-btn text-left p-4 border-2 border-gray-200 rounded-lg ${opColorStyle(op.color).pick} transition-all" data-type="${op.id}">
                            <div class="flex items-start">
                                <span class="text-3xl mr-3">${op.icon}</span>
                                <div class="flex-1">
                                    <div class="font-semibold text-gray-900">${this._escapeHtml(op.name)}</div>
                                    <div class="text-xs text-gray-500 mt-1">${this._escapeHtml(op.description)}</div>
                                </div>
                            </div>
                        </button>
                    `).join('')}
                </div>
            </div>
        `).join('');

        const modal = document.createElement('div');
        modal.className = 'fixed inset-0 bg-gray-600 bg-opacity-50 overflow-y-auto h-full w-full z-50';
        modal.innerHTML = `
            <div class="relative top-20 mx-auto p-6 border w-full max-w-3xl shadow-lg rounded-lg bg-white max-h-[80vh] overflow-y-auto">
                <div class="flex justify-between items-center mb-4">
                    <h3 class="text-lg font-semibold text-gray-900">Select Operation Type</h3>
                    <button class="close-modal text-gray-400 hover:text-gray-500">
                        <svg class="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                        </svg>
                    </button>
                </div>
                ${groupsHtml}
            </div>
        `;

        document.body.appendChild(modal);

        modal.querySelector('.close-modal').addEventListener('click', () => {
            document.body.removeChild(modal);
        });
        modal.addEventListener('click', (e) => {
            if (e.target === modal) document.body.removeChild(modal);
        });
        modal.querySelectorAll('.operation-type-btn').forEach((btn) => {
            btn.addEventListener('click', (e) => {
                const type = e.currentTarget.dataset.type;
                document.body.removeChild(modal);
                this.addOperation(type);
            });
        });
    }

    addOperation(type) {
        const spec = this._opSpec(type);
        if (!spec) {
            this.showToast(`Unknown operation: ${type}`, 'error');
            return;
        }
        const operation = { id: ++this.operationCounter, type: type, roleValues: {}, parameters: {} };
        spec.parameters.forEach((param) => {
            if (param.default !== undefined) operation.parameters[param.name] = param.default;
        });
        this.operations.push(operation);
        this.renderOperations();
        this.updateJsonPreview();
    }

    // ------------------------------------------------------------------
    // Operation cards
    // ------------------------------------------------------------------

    renderOperations() {
        const container = document.getElementById('operationsList');
        if (!container) return;

        if (this.operations.length === 0) {
            container.innerHTML = '<div class="text-center text-gray-400 text-sm py-8">No operations added yet. Click "Add Operation" to start building your pipeline.</div>';
            return;
        }

        const html = this.operations.map((op, index) => {
            const spec = this._opSpec(op.type);
            if (!spec) return '';
            return `
                <div class="operation-card bg-white border-2 ${opColorStyle(spec.color).card} rounded-lg p-4 shadow-sm" data-op-id="${op.id}">
                    <div class="flex items-start justify-between mb-3">
                        <div class="flex items-center">
                            <span class="text-2xl mr-3">${spec.icon}</span>
                            <div>
                                <div class="font-semibold text-gray-900">${index + 1}. ${this._escapeHtml(spec.name)}</div>
                                <div class="text-xs text-gray-500">${this._escapeHtml(spec.description)}</div>
                            </div>
                        </div>
                        <div class="flex gap-2">
                            ${index > 0 ? `<button type="button" class="move-up-btn text-gray-400 hover:text-gray-600" data-op-id="${op.id}" title="Move up">
                                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 15l7-7 7 7"/></svg>
                            </button>` : ''}
                            ${index < this.operations.length - 1 ? `<button type="button" class="move-down-btn text-gray-400 hover:text-gray-600" data-op-id="${op.id}" title="Move down">
                                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/></svg>
                            </button>` : ''}
                            <button type="button" class="delete-op-btn text-red-400 hover:text-red-600" data-op-id="${op.id}" title="Remove">
                                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg>
                            </button>
                        </div>
                    </div>

                    ${this._renderStructureRoles(op, spec)}
                    ${this._renderParameters(op, spec)}
                </div>
            `;
        }).join('');

        container.innerHTML = html;
        this._attachOperationListeners();
    }

    _renderStructureRoles(op, spec) {
        const roles = spec.structure_roles || [];
        if (!roles.length) return '';

        const rows = roles.map((role) => {
            if (this._isChainSource(op, role)) {
                return `
                    <div class="mt-2">
                        <label class="block text-xs font-medium text-gray-700 mb-1">${this._escapeHtml(role.label)}</label>
                        <div class="text-xs text-gray-400 italic">Uses the previous operation's result</div>
                    </div>`;
            }
            if (role.kind === 'multiple') {
                return `
                    <div class="mt-3 pt-3 border-t border-gray-200">
                        <label class="block text-xs font-medium text-gray-700 mb-2">${this._escapeHtml(role.label)}</label>
                        <div class="grid grid-cols-2 gap-2">
                            ${this.options.availableStructures.map((s) => `
                                <label class="flex items-center space-x-2 text-xs">
                                    <input type="checkbox" class="role-checkbox rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                                           value="${this._escapeAttr(s.value)}" data-op-id="${op.id}" data-role="${role.name}"
                                           ${(op.roleValues[role.name] || []).includes(s.value) ? 'checked' : ''}>
                                    <span>${this._escapeHtml(s.label)}</span>
                                </label>
                            `).join('')}
                        </div>
                    </div>`;
            }
            // single
            return `
                <div class="mt-3 pt-3 border-t border-gray-200">
                    <label class="block text-xs font-medium text-gray-700 mb-2">
                        ${this._escapeHtml(role.label)}${role.required ? ' <span class="text-red-500">*</span>' : ''}
                    </label>
                    <select class="role-select w-full px-2 py-1 text-xs border border-gray-300 rounded focus:ring-1 focus:ring-primary-500"
                            data-op-id="${op.id}" data-role="${role.name}">
                        <option value="">-- Select --</option>
                        ${this.options.availableStructures.map((s) =>
                            `<option value="${this._escapeAttr(s.value)}" ${(op.roleValues[role.name] || '') === s.value ? 'selected' : ''}>${this._escapeHtml(s.label)}</option>`
                        ).join('')}
                    </select>
                </div>`;
        }).join('');

        return rows;
    }

    _renderParameters(op, spec) {
        const params = (spec.parameters || []).filter((p) => this._paramVisible(op, p));
        if (!params.length) return '';
        const rows = params.map((param) => this._renderParam(op, param)).join('');
        return `<div class="space-y-2 mt-3 pt-3 border-t border-gray-200">${rows}</div>`;
    }

    _renderParam(op, param) {
        const value = op.parameters[param.name] !== undefined ? op.parameters[param.name] : (param.default ?? '');
        const dataAttrs = `data-op-id="${op.id}" data-param-name="${param.name}"`;
        const baseClass = 'param-input border border-gray-300 rounded focus:ring-1 focus:ring-primary-500';
        if (param.type === 'select') {
            return `
                <div class="flex items-center justify-between">
                    <label class="text-xs font-medium text-gray-700">${this._escapeHtml(param.label)}:</label>
                    <select ${dataAttrs} class="${baseClass} w-40 px-2 py-1 text-xs">
                        ${(param.options || []).map((opt) => `<option value="${this._escapeAttr(opt)}" ${value === opt ? 'selected' : ''}>${this._escapeHtml(opt)}</option>`).join('')}
                    </select>
                </div>`;
        }
        if (param.type === 'boolean') {
            return `
                <div class="flex items-center justify-between">
                    <label class="text-xs font-medium text-gray-700">${this._escapeHtml(param.label)}:</label>
                    <input type="checkbox" ${dataAttrs} class="${baseClass}" ${value ? 'checked' : ''}>
                </div>`;
        }
        // number (default)
        return `
            <div class="flex items-center justify-between">
                <label class="text-xs font-medium text-gray-700">${this._escapeHtml(param.label)}:</label>
                <input type="number" ${dataAttrs} class="${baseClass} w-28 px-2 py-1 text-xs" value="${value}" min="${param.min !== undefined ? param.min : 0}" step="${param.step !== undefined ? param.step : 1}">
            </div>`;
    }

    _paramVisible(op, param) {
        if (!param.show_when) return true;
        return Object.entries(param.show_when).every(([k, v]) => op.parameters[k] === v);
    }

    _attachOperationListeners() {
        const container = document.getElementById('operationsList');
        container.querySelectorAll('.delete-op-btn').forEach((btn) => {
            btn.addEventListener('click', (e) => this.deleteOperation(parseInt(e.currentTarget.dataset.opId)));
        });
        container.querySelectorAll('.move-up-btn').forEach((btn) => {
            btn.addEventListener('click', (e) => this.moveOperation(parseInt(e.currentTarget.dataset.opId), -1));
        });
        container.querySelectorAll('.move-down-btn').forEach((btn) => {
            btn.addEventListener('click', (e) => this.moveOperation(parseInt(e.currentTarget.dataset.opId), 1));
        });

        // Single-role selects
        container.querySelectorAll('.role-select').forEach((sel) => {
            sel.addEventListener('change', (e) => {
                const op = this._op(e.target.dataset.opId);
                if (op) { op.roleValues[e.target.dataset.role] = e.target.value; this.updateJsonPreview(); }
            });
        });
        // Multi-role checkboxes
        container.querySelectorAll('.role-checkbox').forEach((cb) => {
            cb.addEventListener('change', (e) => {
                const op = this._op(e.target.dataset.opId);
                if (!op) return;
                const role = e.target.dataset.role;
                op.roleValues[role] = op.roleValues[role] || [];
                if (e.target.checked) {
                    if (!op.roleValues[role].includes(e.target.value)) op.roleValues[role].push(e.target.value);
                } else {
                    op.roleValues[role] = op.roleValues[role].filter((v) => v !== e.target.value);
                }
                this.updateJsonPreview();
            });
        });
        // Parameters
        container.querySelectorAll('.param-input').forEach((input) => {
            input.addEventListener('change', (e) => {
                const op = this._op(e.target.dataset.opId);
                if (!op) return;
                const name = e.target.dataset.paramName;
                let value = e.target.value;
                if (e.target.type === 'checkbox') value = e.target.checked;
                else if (e.target.type === 'number') value = e.target.value === '' ? null : parseFloat(value);
                op.parameters[name] = value;
                // Re-render if this param drives other params' visibility (e.g. variant).
                if (this._drivesVisibility(op, name)) this.renderOperations();
                this.updateJsonPreview();
            });
        });
    }

    _drivesVisibility(op, paramName) {
        const spec = this._opSpec(op.type);
        if (!spec) return false;
        return spec.parameters.some((p) => p.show_when && paramName in p.show_when);
    }

    _op(opId) {
        // dataset values are strings; o.id is a number. Coerce so lookups from
        // DOM events (data-op-id) reliably match.
        const id = parseInt(opId, 10);
        return this.operations.find((o) => o.id === id);
    }

    // ------------------------------------------------------------------
    // Mutations
    // ------------------------------------------------------------------

    deleteOperation(opId) {
        this.operations = this.operations.filter((op) => op.id !== opId);
        this.renderOperations();
        this.updateJsonPreview();
    }

    moveOperation(opId, direction) {
        const index = this.operations.findIndex((op) => op.id === opId);
        if (index === -1) return;
        const newIndex = index + direction;
        if (newIndex < 0 || newIndex >= this.operations.length) return;
        [this.operations[index], this.operations[newIndex]] =
            [this.operations[newIndex], this.operations[index]];
        this.renderOperations();
        this.updateJsonPreview();
    }

    // ------------------------------------------------------------------
    // Serialization
    // ------------------------------------------------------------------

    _collectStructures(op, spec) {
        const structures = [];
        for (const role of spec.structure_roles || []) {
            if (this._isChainSource(op, role)) continue;
            const v = op.roleValues[role.name];
            if (v == null) continue;
            if (Array.isArray(v)) structures.push(...v.filter(Boolean));
            else if (v) structures.push(v);
        }
        return structures;
    }

    updateJsonPreview() {
        const pipeline = {
            operations: this.operations.map((op) => {
                const spec = this._opSpec(op.type);
                const opData = { type: op.type };
                if (spec) {
                    const structures = this._collectStructures(op, spec);
                    if (structures.length) opData.structures = structures;
                }
                // Include only the parameters currently visible (per show_when),
                // dropping empty values. Hidden params (e.g. margin_mm when the
                // variant is ANISOTROPIC) are omitted.
                const params = {};
                if (spec) {
                    (spec.parameters || []).forEach((p) => {
                        if (!this._paramVisible(op, p)) return;
                        const v = (op.parameters || {})[p.name];
                        if (v !== null && v !== undefined && v !== '') params[p.name] = v;
                    });
                } else {
                    Object.entries(op.parameters || {}).forEach(([k, v]) => {
                        if (v !== null && v !== undefined && v !== '') params[k] = v;
                    });
                }
                if (Object.keys(params).length) opData.parameters = params;
                return opData;
            })
        };

        const jsonString = JSON.stringify(pipeline, null, 2);
        document.getElementById('jsonPreview').textContent = jsonString;
        document.getElementById('pipelineJsonField').value = jsonString;
        this.options.onPipelineChange(pipeline);
    }

    loadFromJson(jsonString) {
        if (!jsonString) return;
        try {
            const pipeline = JSON.parse(jsonString);
            this.operations = [];
            this.operationCounter = 0;

            (pipeline.operations || []).forEach((op) => {
                // Resolve legacy operation ids saved by earlier versions
                // (expand/contract -> signed margin).
                let type = op.type;
                let sign = 1;
                const legacy = this._legacyTypeMap()[op.type];
                if (legacy) { type = legacy.type; sign = legacy.sign; }
                const spec = this._opSpec(type);
                if (!spec) {
                    console.warn(`Unknown operation type in saved pipeline: ${op.type}`);
                    return;
                }
                // Start from the catalog's parameter defaults so show_when
                // filtering and round-trips are stable, then overlay the saved
                // values.
                const defaults = {};
                (spec.parameters || []).forEach((p) => {
                    if (p.default !== undefined) defaults[p.name] = p.default;
                });
                const operation = {
                    id: ++this.operationCounter,
                    type: type,
                    roleValues: {},
                    parameters: Object.assign({}, defaults, op.parameters || {})
                };
                // Legacy `contract` stored a positive margin_mm; the canonical
                // margin op is signed, so flip it to a negative (shrink) value.
                if (sign < 0) {
                    const mm = operation.parameters.margin_mm;
                    if (mm && mm > 0) operation.parameters.margin_mm = -mm;
                }
                // Map the flat `structures` array back onto roles (in catalog
                // order, skipping chain sources). A single role consumes one
                // entry; a multiple role consumes all remaining entries.
                const structures = op.structures || [];
                let i = 0;
                for (const role of spec.structure_roles || []) {
                    if (this._isChainSource(operation, role)) continue;
                    if (role.kind === 'multiple') {
                        operation.roleValues[role.name] = structures.slice(i);
                        i = structures.length;
                    } else {
                        operation.roleValues[role.name] = structures[i] || '';
                        i += 1;
                    }
                }
                this.operations.push(operation);
            });

            this.renderOperations();
            this.updateJsonPreview();
        } catch (e) {
            console.error('Failed to load pipeline from JSON:', e);
            this.showToast('Error loading pipeline', 'error');
        }
    }

    // ------------------------------------------------------------------
    // Utilities
    // ------------------------------------------------------------------

    _escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = String(str ?? '');
        return div.innerHTML
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    _escapeAttr(str) {
        return this._escapeHtml(str);
    }

    showToast(message, type = 'success') {
        const toast = document.createElement('div');
        toast.className = `fixed bottom-4 right-4 px-4 py-2 rounded-lg shadow-lg text-white z-50 ${
            type === 'success' ? 'bg-green-500' : 'bg-red-500'
        }`;
        toast.textContent = message;
        document.body.appendChild(toast);
        setTimeout(() => toast.remove(), 3000);
    }
}

// Export for use in templates
window.PipelineBuilder = PipelineBuilder;
