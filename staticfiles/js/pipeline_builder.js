/**
 * Pipeline Builder for ROI Generation Logic
 * 
 * This component provides a visual interface for building operation pipelines
 * that define how derived structures are generated from autosegmented structures.
 */

class PipelineBuilder {
    constructor(containerId, options = {}) {
        this.container = document.getElementById(containerId);
        this.options = {
            availableStructures: options.availableStructures || [],
            onPipelineChange: options.onPipelineChange || (() => {}),
            ...options
        };
        
        this.operations = [];
        this.operationCounter = 0;
        
        // Define available operation types
        this.operationTypes = {
            'expand': {
                name: 'Expand (Margin)',
                description: 'Expand structure by specified margin',
                icon: '⊕',
                color: 'blue',
                requiresStructures: true,
                allowMultiple: false,
                parameters: [
                    { name: 'margin_mm', label: 'Margin (mm)', type: 'number', default: 5.0, min: 0, step: 0.5 },
                    { name: 'kernel_type', label: 'Kernel Type', type: 'select', default: 'ball', options: ['ball', 'box', 'cross'] }
                ]
            },
            'contract': {
                name: 'Contract (Negative Margin)',
                description: 'Contract structure by specified margin',
                icon: '⊖',
                color: 'red',
                requiresStructures: true,
                allowMultiple: false,
                parameters: [
                    { name: 'margin_mm', label: 'Margin (mm)', type: 'number', default: 3.0, min: 0, step: 0.5 },
                    { name: 'kernel_type', label: 'Kernel Type', type: 'select', default: 'ball', options: ['ball', 'box', 'cross'] }
                ]
            },
            'union': {
                name: 'Union (Combine)',
                description: 'Combine multiple structures',
                icon: '∪',
                color: 'green',
                requiresStructures: true,
                allowMultiple: true,
                parameters: []
            },
            'intersection': {
                name: 'Intersection (Overlap)',
                description: 'Keep only overlapping region',
                icon: '∩',
                color: 'purple',
                requiresStructures: true,
                allowMultiple: true,
                parameters: []
            },
            'subtract': {
                name: 'Subtract (Remove)',
                description: 'Remove structures from result',
                icon: '−',
                color: 'orange',
                requiresStructures: true,
                allowMultiple: true,
                parameters: [
                    { name: 'margin_mm', label: 'Additional Margin (mm)', type: 'number', default: 0, min: 0, step: 0.5 }
                ]
            },
            'crop_to_boundary': {
                name: 'Crop to Boundary',
                description: 'Limit to boundary structure',
                icon: '⊏',
                color: 'indigo',
                requiresStructures: true,
                allowMultiple: false,
                parameters: []
            },
            'smooth': {
                name: 'Smooth Surface',
                description: 'Smooth structure boundaries',
                icon: '≈',
                color: 'teal',
                requiresStructures: false,
                parameters: [
                    { name: 'smoothing_mm', label: 'Smoothing (mm)', type: 'number', default: 2.0, min: 0, step: 0.5 },
                    { name: 'iterations', label: 'Iterations', type: 'number', default: 1, min: 1, step: 1 }
                ]
            },
            'fill_holes': {
                name: 'Fill Holes',
                description: 'Fill internal cavities',
                icon: '●',
                color: 'gray',
                requiresStructures: false,
                parameters: []
            },
            'remove_small_components': {
                name: 'Remove Small Components',
                description: 'Remove disconnected pieces',
                icon: '⊗',
                color: 'pink',
                requiresStructures: false,
                parameters: [
                    { name: 'min_size_mm3', label: 'Min Size (mm³)', type: 'number', default: 100.0, min: 0, step: 10 }
                ]
            },
            'keep_largest': {
                name: 'Keep Largest Component',
                description: 'Keep only main structure',
                icon: '◉',
                color: 'yellow',
                requiresStructures: false,
                parameters: []
            }
        };
        
        this.init();
    }
    
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
        // Add operation button
        document.getElementById('addOperationBtn').addEventListener('click', () => {
            this.showOperationSelector();
        });
        
        // Copy JSON button
        document.getElementById('copyJsonBtn').addEventListener('click', () => {
            const json = document.getElementById('jsonPreview').textContent;
            navigator.clipboard.writeText(json).then(() => {
                this.showToast('JSON copied to clipboard!');
            });
        });
    }
    
    showOperationSelector() {
        const modal = document.createElement('div');
        modal.className = 'fixed inset-0 bg-gray-600 bg-opacity-50 overflow-y-auto h-full w-full z-50';
        modal.innerHTML = `
            <div class="relative top-20 mx-auto p-6 border w-full max-w-3xl shadow-lg rounded-lg bg-white">
                <div class="flex justify-between items-center mb-4">
                    <h3 class="text-lg font-semibold text-gray-900">Select Operation Type</h3>
                    <button class="close-modal text-gray-400 hover:text-gray-500">
                        <svg class="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                        </svg>
                    </button>
                </div>
                
                <div class="grid grid-cols-2 gap-3">
                    ${Object.entries(this.operationTypes).map(([key, op]) => `
                        <button type="button" class="operation-type-btn text-left p-4 border-2 border-gray-200 rounded-lg hover:border-${op.color}-500 hover:bg-${op.color}-50 transition-all" data-type="${key}">
                            <div class="flex items-start">
                                <span class="text-3xl mr-3">${op.icon}</span>
                                <div class="flex-1">
                                    <div class="font-semibold text-gray-900">${op.name}</div>
                                    <div class="text-xs text-gray-500 mt-1">${op.description}</div>
                                </div>
                            </div>
                        </button>
                    `).join('')}
                </div>
            </div>
        `;
        
        document.body.appendChild(modal);
        
        // Close modal handlers
        modal.querySelector('.close-modal').addEventListener('click', () => {
            document.body.removeChild(modal);
        });
        
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                document.body.removeChild(modal);
            }
        });
        
        // Operation type selection
        modal.querySelectorAll('.operation-type-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const type = e.currentTarget.dataset.type;
                document.body.removeChild(modal);
                this.addOperation(type);
            });
        });
    }
    
    addOperation(type) {
        const opDef = this.operationTypes[type];
        const operation = {
            id: ++this.operationCounter,
            type: type,
            structures: opDef.requiresStructures ? [] : null,
            parameters: {}
        };
        
        // Set default parameters
        opDef.parameters.forEach(param => {
            if (param.default !== undefined) {
                operation.parameters[param.name] = param.default;
            }
        });
        
        this.operations.push(operation);
        this.renderOperations();
        this.updateJsonPreview();
    }
    
    renderOperations() {
        const container = document.getElementById('operationsList');
        if (!container) {
            console.error('operationsList container not found');
            return;
        }
        
        const emptyState = document.getElementById('emptyState');
        
        if (this.operations.length === 0) {
            if (emptyState) {
                emptyState.classList.remove('hidden');
            }
            container.innerHTML = '<div class="text-center text-gray-400 text-sm py-8">No operations added yet. Click "Add Operation" to start building your pipeline.</div>';
            return;
        }
        
        if (emptyState) {
            emptyState.classList.add('hidden');
        }
        
        const operationsHtml = this.operations.map((op, index) => {
            const opDef = this.operationTypes[op.type];
            return `
                <div class="operation-card bg-white border-2 border-${opDef.color}-200 rounded-lg p-4 shadow-sm" data-op-id="${op.id}">
                    <div class="flex items-start justify-between mb-3">
                        <div class="flex items-center">
                            <span class="text-2xl mr-3">${opDef.icon}</span>
                            <div>
                                <div class="font-semibold text-gray-900">${index + 1}. ${opDef.name}</div>
                                <div class="text-xs text-gray-500">${opDef.description}</div>
                            </div>
                        </div>
                        <div class="flex gap-2">
                            ${index > 0 ? `<button type="button" class="move-up-btn text-gray-400 hover:text-gray-600" data-op-id="${op.id}">
                                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 15l7-7 7 7"/>
                                </svg>
                            </button>` : ''}
                            ${index < this.operations.length - 1 ? `<button type="button" class="move-down-btn text-gray-400 hover:text-gray-600" data-op-id="${op.id}">
                                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
                                </svg>
                            </button>` : ''}
                            <button type="button" class="delete-op-btn text-red-400 hover:text-red-600" data-op-id="${op.id}">
                                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
                                </svg>
                            </button>
                        </div>
                    </div>
                    
                    ${opDef.requiresStructures ? `
                        <div class="mt-3 pt-3 border-t border-gray-200">
                            <label class="block text-xs font-medium text-gray-700 mb-2">
                                Apply to Structure(s): <span class="text-red-500">*</span>
                            </label>
                            ${this.renderStructureSelector(op, opDef)}
                        </div>
                    ` : ''}
                    
                    ${opDef.parameters.length > 0 ? `
                        <div class="space-y-2 mt-3 pt-3 border-t border-gray-200">
                            ${opDef.parameters.map(param => this.renderParameter(op, param)).join('')}
                        </div>
                    ` : ''}
                </div>
            `;
        }).join('');
        
        container.innerHTML = operationsHtml;
        
        // Attach event listeners for operation controls
        container.querySelectorAll('.delete-op-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const opId = parseInt(e.currentTarget.dataset.opId);
                this.deleteOperation(opId);
            });
        });
        
        container.querySelectorAll('.move-up-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const opId = parseInt(e.currentTarget.dataset.opId);
                this.moveOperation(opId, -1);
            });
        });
        
        container.querySelectorAll('.move-down-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const opId = parseInt(e.currentTarget.dataset.opId);
                this.moveOperation(opId, 1);
            });
        });
        
        // Attach parameter change listeners
        container.querySelectorAll('.param-input').forEach(input => {
            input.addEventListener('change', (e) => {
                const opId = parseInt(e.target.dataset.opId);
                const paramName = e.target.dataset.paramName;
                const operation = this.operations.find(o => o.id === opId);
                
                if (operation) {
                    let value = e.target.value;
                    if (e.target.type === 'number') {
                        value = parseFloat(value);
                    }
                    operation.parameters[paramName] = value;
                    this.updateJsonPreview();
                }
            });
        });
        
        // Attach structure selection listeners (checkboxes)
        container.querySelectorAll('.structure-checkbox').forEach(checkbox => {
            checkbox.addEventListener('change', (e) => {
                const opId = parseInt(e.target.dataset.opId);
                const structureValue = e.target.value;
                const operation = this.operations.find(o => o.id === opId);
                
                if (operation && operation.structures !== null) {
                    if (e.target.checked) {
                        if (!operation.structures.includes(structureValue)) {
                            operation.structures.push(structureValue);
                        }
                    } else {
                        operation.structures = operation.structures.filter(s => s !== structureValue);
                    }
                    this.updateJsonPreview();
                }
            });
        });
        
        // Attach structure selection listeners (dropdown)
        container.querySelectorAll('.structure-select').forEach(select => {
            select.addEventListener('change', (e) => {
                const opId = parseInt(e.target.dataset.opId);
                const structureValue = e.target.value;
                const operation = this.operations.find(o => o.id === opId);
                
                if (operation && operation.structures !== null) {
                    operation.structures = structureValue ? [structureValue] : [];
                    this.updateJsonPreview();
                }
            });
        });
    }
    
    renderStructureSelector(operation, opDef) {
        if (opDef.allowMultiple) {
            // Checkboxes for multiple selection
            return `
                <div class="grid grid-cols-2 gap-2">
                    ${this.options.availableStructures.map(s => `
                        <label class="flex items-center space-x-2 text-xs">
                            <input type="checkbox" 
                                   class="structure-checkbox rounded border-gray-300 text-primary-600 focus:ring-primary-500" 
                                   value="${s.value}"
                                   data-op-id="${operation.id}"
                                   ${operation.structures && operation.structures.includes(s.value) ? 'checked' : ''}>
                            <span>${s.label}</span>
                        </label>
                    `).join('')}
                </div>
            `;
        } else {
            // Single select dropdown
            return `
                <select class="structure-select w-full px-2 py-1 text-xs border border-gray-300 rounded focus:ring-1 focus:ring-primary-500"
                        data-op-id="${operation.id}">
                    <option value="">-- Select Structure --</option>
                    ${this.options.availableStructures.map(s => 
                        `<option value="${s.value}" ${operation.structures && operation.structures[0] === s.value ? 'selected' : ''}>${s.label}</option>`
                    ).join('')}
                </select>
            `;
        }
    }
    
    renderParameter(operation, param) {
        const value = operation.parameters[param.name] || param.default || '';
        
        if (param.type === 'number') {
            return `
                <div class="flex items-center justify-between">
                    <label class="text-xs font-medium text-gray-700">${param.label}:</label>
                    <input type="number" 
                           class="param-input w-24 px-2 py-1 text-xs border border-gray-300 rounded focus:ring-1 focus:ring-primary-500"
                           data-op-id="${operation.id}"
                           data-param-name="${param.name}"
                           value="${value}"
                           min="${param.min || 0}"
                           step="${param.step || 1}"
                           ${param.required ? 'required' : ''}>
                </div>
            `;
        } else if (param.type === 'select') {
            return `
                <div class="flex items-center justify-between">
                    <label class="text-xs font-medium text-gray-700">${param.label}:</label>
                    <select class="param-input w-32 px-2 py-1 text-xs border border-gray-300 rounded focus:ring-1 focus:ring-primary-500"
                            data-op-id="${operation.id}"
                            data-param-name="${param.name}"
                            ${param.required ? 'required' : ''}>
                        ${param.options.map(opt => 
                            `<option value="${opt}" ${value === opt ? 'selected' : ''}>${opt}</option>`
                        ).join('')}
                    </select>
                </div>
            `;
        }
        
        return '';
    }
    
    deleteOperation(opId) {
        this.operations = this.operations.filter(op => op.id !== opId);
        this.renderOperations();
        this.updateJsonPreview();
    }
    
    moveOperation(opId, direction) {
        const index = this.operations.findIndex(op => op.id === opId);
        if (index === -1) return;
        
        const newIndex = index + direction;
        if (newIndex < 0 || newIndex >= this.operations.length) return;
        
        // Swap operations
        [this.operations[index], this.operations[newIndex]] = 
        [this.operations[newIndex], this.operations[index]];
        
        this.renderOperations();
        this.updateJsonPreview();
    }
    
    updateJsonPreview() {
        const pipeline = {
            operations: this.operations.map(op => {
                const opData = {
                    type: op.type
                };
                
                // Add structures if operation requires them
                if (op.structures !== null) {
                    opData.structures = op.structures;
                }
                
                // Add parameters if they exist
                if (Object.keys(op.parameters).length > 0) {
                    opData.parameters = op.parameters;
                }
                
                return opData;
            })
        };
        
        const jsonString = JSON.stringify(pipeline, null, 2);
        document.getElementById('jsonPreview').textContent = jsonString;
        document.getElementById('pipelineJsonField').value = jsonString;
        
        // Call callback
        this.options.onPipelineChange(pipeline);
    }
    
    loadFromJson(jsonString) {
        try {
            const pipeline = JSON.parse(jsonString);
            
            // Load operations
            this.operations = [];
            this.operationCounter = 0;
            
            if (pipeline.operations && Array.isArray(pipeline.operations)) {
                pipeline.operations.forEach(op => {
                    const opDef = this.operationTypes[op.type];
                    if (!opDef) {
                        console.warn(`Unknown operation type: ${op.type}`);
                        return;
                    }
                    
                    const operation = {
                        id: ++this.operationCounter,
                        type: op.type,
                        structures: op.structures || (opDef.requiresStructures ? [] : null),
                        parameters: op.parameters || {}
                    };
                    this.operations.push(operation);
                });
            }
            
            this.renderOperations();
            this.updateJsonPreview();
        } catch (e) {
            console.error('Failed to load pipeline from JSON:', e);
            this.showToast('Error loading pipeline', 'error');
        }
    }
    
    showToast(message, type = 'success') {
        const toast = document.createElement('div');
        toast.className = `fixed bottom-4 right-4 px-4 py-2 rounded-lg shadow-lg text-white z-50 ${
            type === 'success' ? 'bg-green-500' : 'bg-red-500'
        }`;
        toast.textContent = message;
        document.body.appendChild(toast);
        
        setTimeout(() => {
            toast.remove();
        }, 3000);
    }
}

// Export for use in templates
window.PipelineBuilder = PipelineBuilder;
