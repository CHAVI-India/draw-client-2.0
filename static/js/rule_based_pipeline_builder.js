/**
 * Rule-based segmentation pipeline builder.
 *
 * This module provides a UI for creating and editing reusable segmentation
 * pipelines. It supports boolean rules with nested groups, intensity range
 * rules, margin rules, crop rules, and cleanup rules.
 *
 * The builder serializes the pipeline to JSON and stores it in a hidden form
 * field named `pipeline_data` before the form is submitted.
 */
(function () {
  "use strict";

  const RULE_TYPES = {
    BOOLEAN: "Boolean Expression",
    INTENSITY: "Intensity Range",
    MARGIN: "Margin",
    CROP: "Crop to Boundary",
    CLEANUP: "Cleanup / Refinement",
  };

  const BOOLEAN_OPERATIONS = {
    UNION: "Union",
    INTERSECTION: "Intersection",
    SUBTRACT: "Subtract",
    XOR: "Exclusive OR",
  };

  const ROI_TYPES = [
    "EXTERNAL", "PTV", "CTV", "GTV", "TREATED_VOLUME", "IRRAD_VOLUME",
    "OAR", "BOLUS", "AVOIDANCE", "ORGAN", "MARKER", "REGISTRATION",
    "ISOCENTER", "CONTRAST_AGENT", "CAVITY", "BRACHY_CHANNEL",
    "BRACHY_ACCESSORY", "BRACHY_SRC_APP", "BRACHY_CHNL_SHLD", "SUPPORT",
    "FIXATION", "DOSE_REGION", "CONTROL", "DOSE_MEASUREMENT",
  ];

  const MARGIN_KERNELS = [
    { value: "ball", label: "Ball" },
    { value: "box", label: "Box" },
    { value: "cross", label: "Cross" },
  ];

  const CLEANUP_OPERATIONS = {
    SMOOTH_STRUCTURE: { label: "Smooth Surface", params: ["smoothing_mm", "iterations"] },
    GAUSSIAN_SMOOTH: { label: "Gaussian Smooth", params: ["sigma_mm", "threshold"] },
    FILL_HOLES: { label: "Fill Holes", params: ["fully_connected"] },
    REMOVE_SMALL_COMPONENTS: { label: "Remove Small Components", params: ["min_size_mm3"] },
    KEEP_LARGEST_COMPONENT: { label: "Keep Largest Component", params: [] },
  };

  function uuidv4() {
    return "10000000-1000-4000-8000-100000000000".replace(/[018]/g, (c) =>
      (c ^ (crypto.getRandomValues(new Uint8Array(1))[0] & (15 >> (c / 4)))).toString(16)
    );
  }

  class RuleBasedPipelineBuilder {
    constructor(containerId, options) {
      this.container = document.getElementById(containerId);
      if (!this.container) {
        throw new Error(`Builder container #${containerId} not found`);
      }

      this.options = options || {};
      this.existingRules = this.options.existingRules || [];
      this.availableStructures = this.options.availableStructures || [];
      this.sampleRtstructUrl = this.options.sampleRtstructUrl || null;

      this.state = {
        rules: this.existingRules.map((r) => this._normalizeRule(r)),
      };

      this._init();
    }

    _init() {
      this.container.innerHTML = `
        <div class="space-y-4">
          <div class="flex flex-col sm:flex-row sm:justify-between sm:items-center gap-3">
            <h3 class="text-lg font-semibold">Pipeline Rules</h3>
            <div class="flex items-center gap-2">
              <label for="rbs-add-rule-type" class="text-sm font-medium text-gray-700 whitespace-nowrap">Operation</label>
              <select id="rbs-add-rule-type" class="form-select h-10 px-3 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500">
                ${Object.entries(RULE_TYPES)
                  .map(([key, label]) => `<option value="${key}">${label}</option>`)
                  .join("")}
              </select>
              <button type="button" id="rbs-add-rule" class="inline-flex items-center h-10 px-3 border border-transparent text-sm font-medium rounded-md text-white bg-primary-600 hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary-500">
                + Add Rule
              </button>
            </div>
          </div>
          <div id="rbs-rules-list" class="space-y-3"></div>
          <div id="rbs-rule-editor" class="hidden border rounded-md p-4 bg-gray-50"></div>
        </div>
      `;

      this.container.querySelector("#rbs-add-rule").addEventListener("click", () => {
        const type = this.container.querySelector("#rbs-add-rule-type").value;
        this.addRule(type);
      });

      this._renderRulesList();
    }

    _normalizeRule(rule) {
      const normalized = {
        tempId: rule.tempId || uuidv4(),
        rule_type: rule.rule_type,
        name: rule.name || "",
        output_action: rule.output_action || "CREATE_NEW",
        output_color: rule.output_color || "#FFFF00",
        output_roi_type: rule.output_roi_type || "ORGAN",
        config: rule.config || this._defaultConfig(rule.rule_type),
      };
      return normalized;
    }

    _defaultConfig(ruleType) {
      switch (ruleType) {
        case "BOOLEAN":
          return { operation: "UNION", operands: [] };
        case "INTENSITY":
          return {
            seed_type: "IMAGE",
            seed_roi: "",
            boundary_roi: "",
            modality_hint: "CT",
            ranges: [{ min: -1000, max: -400 }],
          };
        case "MARGIN":
          return {
            variant: "UNIFORM",
            source: "",
            margin_mm: 5.0,
            margin_x_mm: 0.0,
            margin_y_mm: 0.0,
            margin_z_mm: 0.0,
            kernel_type: "ball",
          };
        case "CROP":
          return { source: "", boundaries: [""] };
        case "CLEANUP":
          return { operation: "SMOOTH_STRUCTURE", source: "", smoothing_mm: 2.0, iterations: 1 };
        default:
          return {};
      }
    }

    addRule(ruleType) {
      const rule = this._normalizeRule({ rule_type: ruleType });
      this.state.rules.push(rule);
      this._renderRulesList();
      this.editRule(rule.tempId);
    }

    deleteRule(tempId) {
      this.state.rules = this.state.rules.filter((r) => r.tempId !== tempId);
      this._hideEditor();
      this._renderRulesList();
    }

    moveRule(tempId, direction) {
      const idx = this.state.rules.findIndex((r) => r.tempId === tempId);
      if (idx === -1) return;
      const newIdx = idx + direction;
      if (newIdx < 0 || newIdx >= this.state.rules.length) return;
      const [moved] = this.state.rules.splice(idx, 1);
      this.state.rules.splice(newIdx, 0, moved);
      this._renderRulesList();
    }

    editRule(tempId) {
      const rule = this.state.rules.find((r) => r.tempId === tempId);
      if (!rule) return;
      this.editingRuleId = tempId;
      this._renderRuleEditor(rule);
    }

    _renderRulesList() {
      const list = this.container.querySelector("#rbs-rules-list");
      if (this.state.rules.length === 0) {
        list.innerHTML = `
          <div class="text-center text-gray-500 py-8 border-2 border-dashed border-gray-300 rounded-md">
            No rules yet. Click "Add Rule" to create one.
          </div>
        `;
        return;
      }

      list.innerHTML = this.state.rules
        .map((rule, index) => {
          const summary = this._summarizeRule(rule);
          return `
            <div class="bg-white border rounded-md p-3 shadow-sm flex items-start justify-between" data-temp-id="${rule.tempId}">
              <div class="flex items-start space-x-3">
                <div class="cursor-move text-gray-400 hover:text-gray-600" title="Drag to reorder">
                  <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 8h16M4 16h16"></path></svg>
                </div>
                <div>
                  <div class="flex items-center space-x-2">
                    <span class="text-xs font-mono text-gray-500">${index + 1}</span>
                    <span class="font-medium">${this._escapeHtml(rule.name || "Unnamed")}</span>
                    <span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-blue-100 text-blue-800">${RULE_TYPES[rule.rule_type]}</span>
                    <span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${rule.output_action === "CREATE_NEW" ? "bg-green-100 text-green-800" : "bg-yellow-100 text-yellow-800"}">${rule.output_action === "CREATE_NEW" ? "Create" : "Replace"}</span>
                  </div>
                  <div class="text-sm text-gray-600 mt-1">${this._escapeHtml(summary)}</div>
                </div>
              </div>
              <div class="flex items-center space-x-1">
                <button type="button" class="rbs-move-up p-1 text-gray-500 hover:text-gray-700" title="Move up" ${index === 0 ? "disabled" : ""}>
                  <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 15l7-7 7 7"></path></svg>
                </button>
                <button type="button" class="rbs-move-down p-1 text-gray-500 hover:text-gray-700" title="Move down" ${index === this.state.rules.length - 1 ? "disabled" : ""}>
                  <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"></path></svg>
                </button>
                <button type="button" class="rbs-edit-rule p-1 text-blue-600 hover:text-blue-800" title="Edit">
                  <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"></path></svg>
                </button>
                <button type="button" class="rbs-delete-rule p-1 text-red-600 hover:text-red-800" title="Delete">
                  <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>
                </button>
              </div>
            </div>
          `;
        })
        .join("");

      this._attachRuleListEvents();
    }

    _attachRuleListEvents() {
      const list = this.container.querySelector("#rbs-rules-list");
      list.querySelectorAll(".rbs-move-up").forEach((btn) => {
        btn.addEventListener("click", (e) => {
          const tempId = e.currentTarget.closest("[data-temp-id]").dataset.tempId;
          this.moveRule(tempId, -1);
        });
      });
      list.querySelectorAll(".rbs-move-down").forEach((btn) => {
        btn.addEventListener("click", (e) => {
          const tempId = e.currentTarget.closest("[data-temp-id]").dataset.tempId;
          this.moveRule(tempId, 1);
        });
      });
      list.querySelectorAll(".rbs-edit-rule").forEach((btn) => {
        btn.addEventListener("click", (e) => {
          const tempId = e.currentTarget.closest("[data-temp-id]").dataset.tempId;
          this.editRule(tempId);
        });
      });
      list.querySelectorAll(".rbs-delete-rule").forEach((btn) => {
        btn.addEventListener("click", (e) => {
          const tempId = e.currentTarget.closest("[data-temp-id]").dataset.tempId;
          if (confirm("Delete this rule?")) {
            this.deleteRule(tempId);
          }
        });
      });
    }

    _summarizeRule(rule) {
      const cfg = rule.config;
      switch (rule.rule_type) {
        case "BOOLEAN":
          return this._summarizeBooleanNode(cfg);
        case "INTENSITY":
          return `Intensity ranges: ${cfg.ranges.map((r) => `${r.min} to ${r.max}`).join(", ")}`;
        case "MARGIN":
          return cfg.variant === "UNIFORM"
            ? `${cfg.margin_mm >= 0 ? "Expand" : "Contract"} ${cfg.source} by ${Math.abs(cfg.margin_mm)} mm (${cfg.kernel_type})`
            : `Anisotropic margin on ${cfg.source}: [${cfg.margin_x_mm}, ${cfg.margin_y_mm}, ${cfg.margin_z_mm}] mm`;
        case "CROP":
          return `Crop ${cfg.source} to ${cfg.boundaries.join(", ")}`;
        case "CLEANUP":
          return `${CLEANUP_OPERATIONS[cfg.operation].label} on ${cfg.source}`;
        default:
          return "";
      }
    }

    _summarizeBooleanNode(node) {
      if (!node.operation) return this._escapeHtml(node.name || "");
      const opLabels = { UNION: "∪", INTERSECTION: "∩", SUBTRACT: "−", XOR: "⊕" };
      const operandSummaries = node.operands
        .map((op) => (op.operation ? `(${this._summarizeBooleanNode(op)})` : op.name))
        .join(` ${opLabels[node.operation] || node.operation} `);
      return operandSummaries;
    }

    _renderRuleEditor(rule) {
      const editor = this.container.querySelector("#rbs-rule-editor");
      editor.classList.remove("hidden");

      let configHtml = "";
      switch (rule.rule_type) {
        case "BOOLEAN":
          configHtml = this._renderBooleanEditor(rule.config);
          break;
        case "INTENSITY":
          configHtml = this._renderIntensityEditor(rule.config);
          break;
        case "MARGIN":
          configHtml = this._renderMarginEditor(rule.config);
          break;
        case "CROP":
          configHtml = this._renderCropEditor(rule.config);
          break;
        case "CLEANUP":
          configHtml = this._renderCleanupEditor(rule.config);
          break;
      }

      editor.innerHTML = `
        <div class="space-y-4">
          <div class="flex justify-between items-center">
            <h4 class="font-semibold">Edit Rule</h4>
            <button type="button" id="rbs-close-editor" class="text-gray-500 hover:text-gray-700">
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
            </button>
          </div>
          <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label class="block text-sm font-medium text-gray-700">Output ROI Name</label>
              <input type="text" id="rbs-rule-name" value="${this._escapeHtml(rule.name)}" class="mt-1 block w-full border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm px-3 py-2" maxlength="16">
            </div>
            <div>
              <label class="block text-sm font-medium text-gray-700">Output Action</label>
              <select id="rbs-rule-output-action" class="mt-1 block w-full border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm px-3 py-2">
                <option value="CREATE_NEW" ${rule.output_action === "CREATE_NEW" ? "selected" : ""}>Create new ROI</option>
                <option value="REPLACE_EXISTING" ${rule.output_action === "REPLACE_EXISTING" ? "selected" : ""}>Replace existing ROI</option>
              </select>
            </div>
            <div>
              <label class="block text-sm font-medium text-gray-700">Color (RGB hex)</label>
              <input type="color" id="rbs-rule-color" value="${this._escapeHtml(rule.output_color)}" class="mt-1 block w-full border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm px-3 py-2 h-10">
            </div>
            <div>
              <label class="block text-sm font-medium text-gray-700">ROI Type</label>
              <select id="rbs-rule-roi-type" class="mt-1 block w-full border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm px-3 py-2">
                ${ROI_TYPES.map((t) => `<option value="${t}" ${rule.output_roi_type === t ? "selected" : ""}>${t}</option>`).join("")}
              </select>
            </div>
          </div>
          <div id="rbs-rule-config">${configHtml}</div>
          <div class="flex justify-end space-x-2">
            <button type="button" id="rbs-cancel-edit" class="px-4 py-2 border border-gray-300 rounded-md text-sm font-medium text-gray-700 hover:bg-gray-50">Cancel</button>
            <button type="button" id="rbs-save-rule" class="px-4 py-2 border border-transparent rounded-md text-sm font-medium text-white bg-primary-600 hover:bg-primary-700">Save Rule</button>
          </div>
        </div>
      `;

      editor.querySelector("#rbs-close-editor").addEventListener("click", () => this._hideEditor());
      editor.querySelector("#rbs-cancel-edit").addEventListener("click", () => this._hideEditor());
      editor.querySelector("#rbs-save-rule").addEventListener("click", () => this._saveCurrentRule());

      this._attachConfigEventListeners(rule.rule_type);
    }

    _hideEditor() {
      this.editingRuleId = null;
      const editor = this.container.querySelector("#rbs-rule-editor");
      if (editor) editor.classList.add("hidden");
    }

    _saveCurrentRule() {
      const rule = this.state.rules.find((r) => r.tempId === this.editingRuleId);
      if (!rule) return;

      const newName = this.container.querySelector("#rbs-rule-name").value.trim();
      if (!newName) {
        alert("Output ROI name is required");
        return;
      }

      const duplicate = this.state.rules.find((r) => r.tempId !== this.editingRuleId && r.name === newName);
      if (duplicate) {
        alert(`Output ROI name '${newName}' is already used by another rule. Names must be unique.`);
        return;
      }

      rule.name = newName;
      rule.output_action = this.container.querySelector("#rbs-rule-output-action").value;
      rule.output_color = this.container.querySelector("#rbs-rule-color").value;
      rule.output_roi_type = this.container.querySelector("#rbs-rule-roi-type").value;

      this._collectConfigFromEditor(rule);

      this._hideEditor();
      this._renderRulesList();
    }

    _renderBooleanEditor(config) {
      return `
        <div class="space-y-2">
          <label class="block text-sm font-medium text-gray-700">Boolean Expression</label>
          <div id="rbs-boolean-root" class="rbs-boolean-node border border-gray-200 rounded-md p-3 bg-white" data-node-type="operation" data-operation="${config.operation || 'UNION'}">
            <div class="flex items-center space-x-2 mb-2">
              <span class="text-sm text-gray-600">Operation</span>
              ${this._renderOperationSelect(config.operation || "UNION", "rbs-boolean-op")}
            </div>
            ${this._renderBooleanNodeChildren(config, true)}
          </div>
        </div>
      `;
    }

    _renderBooleanNodeChildren(config, isRoot = false) {
      const hasOperands = config.operands && config.operands.length > 0;
      const childrenHtml = hasOperands
        ? config.operands.map((op, idx) => this._renderBooleanOperand(op, idx)).join("")
        : `<div class="text-sm text-gray-500 italic p-2 rbs-boolean-empty-msg">No operands. Add structures or groups below.</div>`;
      return `
        <div class="rbs-boolean-children ${isRoot ? '' : 'pl-4 border-l-2 border-gray-200'} space-y-2">
          ${childrenHtml}
        </div>
        <div class="rbs-boolean-add-controls mt-2 flex flex-wrap gap-2">
          <button type="button" class="rbs-add-operand inline-flex items-center px-2 py-1 border border-transparent text-xs font-medium rounded text-primary-700 bg-primary-100 hover:bg-primary-200">
            + Add structure
          </button>
          <button type="button" class="rbs-add-group inline-flex items-center px-2 py-1 border border-transparent text-xs font-medium rounded text-blue-700 bg-blue-100 hover:bg-blue-200">
            + Add group
          </button>
        </div>
      `;
    }

    _renderBooleanOperand(operand, index) {
      const isGroup = !!operand.operation;
      const header = isGroup
        ? `<span class="text-xs font-semibold text-gray-600">Group</span>`
        : `<span class="text-xs font-semibold text-gray-600">Structure</span>`;

      const content = isGroup
        ? `
          <div class="flex items-center space-x-2 mb-1">
            ${this._renderOperationSelect(operand.operation || "UNION", "rbs-boolean-op")}
            <button type="button" class="rbs-remove-operand text-xs text-red-600 hover:text-red-800">Remove group</button>
          </div>
          ${this._renderBooleanNodeChildren(operand, false)}
        `
        : `
          <div class="flex items-center space-x-2">
            ${this._renderStructureSelect("rbs-boolean-operand-" + index, operand.name || "", false, "rbs-boolean-roi")}
            <button type="button" class="rbs-convert-to-group text-xs text-primary-600 hover:text-primary-800">Group</button>
            <button type="button" class="rbs-remove-operand text-xs text-red-600 hover:text-red-800">Remove</button>
          </div>
        `;

      return `
        <div class="rbs-boolean-operand bg-white border rounded-md p-2 ${isGroup ? 'border-blue-200 bg-blue-50' : 'border-gray-200'}" data-index="${index}" data-operation="${operand.operation || ''}">
          <div class="flex justify-between items-center mb-1">
            ${header}
          </div>
          ${content}
        </div>
      `;
    }

    _renderOperationSelect(selectedValue, className) {
      return `
        <select class="${className} border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm px-3 py-2">
          ${Object.entries(BOOLEAN_OPERATIONS).map(([key, label]) => `<option value="${key}" ${key === selectedValue ? "selected" : ""}>${label}</option>`).join("")}
        </select>
      `;
    }

    _renderIntensityEditor(config) {
      const rangesHtml = config.ranges
        .map(
          (r, idx) => `
          <div class="flex items-center space-x-2 rbs-intensity-range">
            <input type="number" step="any" class="rbs-range-min border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm px-3 py-2 w-32" value="${r.min}" placeholder="Min">
            <span>to</span>
            <input type="number" step="any" class="rbs-range-max border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm px-3 py-2 w-32" value="${r.max}" placeholder="Max">
            <button type="button" class="rbs-remove-range text-red-600 hover:text-red-800" title="Remove range">×</button>
          </div>
        `
        )
        .join("");

      return `
        <div class="space-y-4">
          <div>
            <label class="block text-sm font-medium text-gray-700">Seed Region</label>
            <select id="rbs-intensity-seed-type" class="mt-1 block w-full border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm px-3 py-2">
              <option value="IMAGE" ${config.seed_type === "IMAGE" ? "selected" : ""}>Full image</option>
              <option value="STRUCTURE" ${config.seed_type === "STRUCTURE" ? "selected" : ""}>Structure</option>
              <option value="BOUNDARY" ${config.seed_type === "BOUNDARY" ? "selected" : ""}>Boundary structure</option>
            </select>
          </div>
          <div id="rbs-intensity-seed-selector" class="${config.seed_type === "IMAGE" ? "hidden" : ""}">
            <label class="block text-sm font-medium text-gray-700">Structure</label>
            ${this._renderStructureSelect("rbs-intensity-seed-roi", config.seed_roi)}
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-700">Boundary (optional)</label>
            ${this._renderStructureSelect("rbs-intensity-boundary-roi", config.boundary_roi, true)}
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-700">Intensity Ranges</label>
            <div id="rbs-intensity-ranges" class="space-y-2 mt-1">${rangesHtml}</div>
            <button type="button" id="rbs-add-range" class="mt-2 text-sm text-primary-600 hover:text-primary-800">+ Add range</button>
          </div>
        </div>
      `;
    }

    _renderMarginEditor(config) {
      return `
        <div class="space-y-4">
          <div>
            <label class="block text-sm font-medium text-gray-700">Variant</label>
            <select id="rbs-margin-variant" class="mt-1 block w-full border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm px-3 py-2">
              <option value="UNIFORM" ${config.variant === "UNIFORM" ? "selected" : ""}>Uniform</option>
              <option value="ANISOTROPIC" ${config.variant === "ANISOTROPIC" ? "selected" : ""}>Anisotropic</option>
            </select>
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-700">Source Structure</label>
            ${this._renderStructureSelect("rbs-margin-source", config.source)}
          </div>
          <div id="rbs-margin-uniform" class="${config.variant !== "UNIFORM" ? "hidden" : ""}">
            <label class="block text-sm font-medium text-gray-700">Margin (mm) — negative to contract</label>
            <input type="number" step="any" id="rbs-margin-mm" value="${config.margin_mm}" class="mt-1 block w-full border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm px-3 py-2">
            <label class="block text-sm font-medium text-gray-700 mt-2">Kernel</label>
            <select id="rbs-margin-kernel" class="mt-1 block w-full border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm px-3 py-2">
              ${MARGIN_KERNELS.map((k) => `<option value="${k.value}" ${config.kernel_type === k.value ? "selected" : ""}>${k.label}</option>`).join("")}
            </select>
          </div>
          <div id="rbs-margin-anisotropic" class="${config.variant !== "ANISOTROPIC" ? "hidden" : ""}">
            <label class="block text-sm font-medium text-gray-700">Margin X (mm)</label>
            <input type="number" step="any" id="rbs-margin-x" value="${config.margin_x_mm}" class="mt-1 block w-full border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm px-3 py-2">
            <label class="block text-sm font-medium text-gray-700 mt-2">Margin Y (mm)</label>
            <input type="number" step="any" id="rbs-margin-y" value="${config.margin_y_mm}" class="mt-1 block w-full border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm px-3 py-2">
            <label class="block text-sm font-medium text-gray-700 mt-2">Margin Z (mm)</label>
            <input type="number" step="any" id="rbs-margin-z" value="${config.margin_z_mm}" class="mt-1 block w-full border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm px-3 py-2">
          </div>
        </div>
      `;
    }

    _renderCropEditor(config) {
      const boundariesHtml = config.boundaries
        .map(
          (b, idx) => `
          <div class="flex items-center space-x-2 rbs-crop-boundary">
            ${this._renderStructureSelect("rbs-crop-boundary-" + idx, b, true, "rbs-crop-boundary-select")}
            <button type="button" class="rbs-remove-boundary text-red-600 hover:text-red-800" title="Remove boundary">×</button>
          </div>
        `
        )
        .join("");

      return `
        <div class="space-y-4">
          <div>
            <label class="block text-sm font-medium text-gray-700">Source Structure</label>
            ${this._renderStructureSelect("rbs-crop-source", config.source)}
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-700">Boundaries</label>
            <div id="rbs-crop-boundaries" class="space-y-2 mt-1">${boundariesHtml}</div>
            <button type="button" id="rbs-add-boundary" class="mt-2 text-sm text-primary-600 hover:text-primary-800">+ Add boundary</button>
          </div>
        </div>
      `;
    }

    _renderCleanupEditor(config) {
      const op = CLEANUP_OPERATIONS[config.operation];
      return `
        <div class="space-y-4">
          <div>
            <label class="block text-sm font-medium text-gray-700">Operation</label>
            <select id="rbs-cleanup-operation" class="mt-1 block w-full border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm px-3 py-2">
              ${Object.entries(CLEANUP_OPERATIONS)
                .map(([key, info]) => `<option value="${key}" ${config.operation === key ? "selected" : ""}>${info.label}</option>`)
                .join("")}
            </select>
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-700">Source Structure</label>
            ${this._renderStructureSelect("rbs-cleanup-source", config.source)}
          </div>
          <div id="rbs-cleanup-params">
            ${this._renderCleanupParams(config)}
          </div>
        </div>
      `;
    }

    _renderCleanupParams(config) {
      const params = CLEANUP_OPERATIONS[config.operation].params;
      let html = "";
      if (params.includes("smoothing_mm")) {
        html += `
          <label class="block text-sm font-medium text-gray-700">Smoothing (mm)</label>
          <input type="number" step="any" id="rbs-cleanup-smoothing-mm" value="${config.smoothing_mm || 2.0}" class="mt-1 block w-full border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm px-3 py-2">
        `;
      }
      if (params.includes("iterations")) {
        html += `
          <label class="block text-sm font-medium text-gray-700 mt-2">Iterations</label>
          <input type="number" step="1" id="rbs-cleanup-iterations" value="${config.iterations || 1}" class="mt-1 block w-full border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm px-3 py-2">
        `;
      }
      if (params.includes("sigma_mm")) {
        html += `
          <label class="block text-sm font-medium text-gray-700">Sigma (mm)</label>
          <input type="number" step="any" id="rbs-cleanup-sigma-mm" value="${config.sigma_mm || 1.0}" class="mt-1 block w-full border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm px-3 py-2">
        `;
      }
      if (params.includes("threshold")) {
        html += `
          <label class="block text-sm font-medium text-gray-700 mt-2">Threshold</label>
          <input type="number" step="any" id="rbs-cleanup-threshold" value="${config.threshold || 0.5}" class="mt-1 block w-full border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm px-3 py-2">
        `;
      }
      if (params.includes("min_size_mm3")) {
        html += `
          <label class="block text-sm font-medium text-gray-700">Min Size (mm³)</label>
          <input type="number" step="any" id="rbs-cleanup-min-size" value="${config.min_size_mm3 || 100.0}" class="mt-1 block w-full border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm px-3 py-2">
        `;
      }
      if (params.includes("fully_connected")) {
        html += `
          <label class="flex items-center mt-2">
            <input type="checkbox" id="rbs-cleanup-fully-connected" class="rounded border-gray-300 text-primary-600 shadow-sm" ${config.fully_connected ? "checked" : ""}>
            <span class="ml-2 text-sm text-gray-700">Fully connected</span>
          </label>
        `;
      }
      return html;
    }

    _renderStructureSelect(id, value, allowEmpty = false, className = "") {
      const currentIndex = this.state.rules.findIndex(r => r.tempId === this.editingRuleId);
      const priorOutputs = [];
      if (currentIndex > 0) {
        for (let i = 0; i < currentIndex; i++) {
          const r = this.state.rules[i];
          if (r.name) {
            priorOutputs.push({ value: r.name, label: `${r.name} (generated)`, kind: "generated" });
          }
        }
      }

      let optionsHtml = "";
      if (priorOutputs.length > 0) {
        optionsHtml += `<optgroup label="Generated by earlier rules">`;
        optionsHtml += priorOutputs
          .map((s) => `<option value="${this._escapeHtml(s.value)}" ${s.value === value ? "selected" : ""}>${this._escapeHtml(s.label)}</option>`)
          .join("");
        optionsHtml += `</optgroup>`;
      }
      if (this.availableStructures.length > 0) {
        optionsHtml += `<optgroup label="From sample RTStruct">`;
        optionsHtml += this.availableStructures
          .map((s) => `<option value="${this._escapeHtml(s.value)}" ${s.value === value ? "selected" : ""}>${this._escapeHtml(s.label)}</option>`)
          .join("");
        optionsHtml += `</optgroup>`;
      }

      return `
        <select id="${id}" class="${className} mt-1 block w-full border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm px-3 py-2">
          ${allowEmpty ? `<option value="">-- Select --</option>` : ""}
          ${optionsHtml}
        </select>
      `;
    }

    _attachConfigEventListeners(ruleType) {
      if (ruleType === "INTENSITY") {
        this.container.querySelector("#rbs-add-range").addEventListener("click", () => {
          const rangesDiv = this.container.querySelector("#rbs-intensity-ranges");
          const div = document.createElement("div");
          div.className = "flex items-center space-x-2 rbs-intensity-range";
          div.innerHTML = `
            <input type="number" step="any" class="rbs-range-min border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm px-3 py-2 w-32" placeholder="Min">
            <span>to</span>
            <input type="number" step="any" class="rbs-range-max border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm px-3 py-2 w-32" placeholder="Max">
            <button type="button" class="rbs-remove-range text-red-600 hover:text-red-800" title="Remove range">×</button>
          `;
          rangesDiv.appendChild(div);
          this._attachRangeRemoveListeners();
        });
        this._attachRangeRemoveListeners();

        const seedType = this.container.querySelector("#rbs-intensity-seed-type");
        seedType.addEventListener("change", () => {
          const selector = this.container.querySelector("#rbs-intensity-seed-selector");
          selector.classList.toggle("hidden", seedType.value === "IMAGE");
        });
      }

      if (ruleType === "MARGIN") {
        const variant = this.container.querySelector("#rbs-margin-variant");
        variant.addEventListener("change", () => {
          const isUniform = variant.value === "UNIFORM";
          this.container.querySelector("#rbs-margin-uniform").classList.toggle("hidden", !isUniform);
          this.container.querySelector("#rbs-margin-anisotropic").classList.toggle("hidden", isUniform);
        });
      }

      if (ruleType === "CROP") {
        this.container.querySelector("#rbs-add-boundary").addEventListener("click", () => {
          const boundariesDiv = this.container.querySelector("#rbs-crop-boundaries");
          const div = document.createElement("div");
          div.className = "flex items-center space-x-2 rbs-crop-boundary";
          div.innerHTML = `
            ${this._renderStructureSelect("rbs-crop-boundary-" + Date.now(), "", true, "rbs-crop-boundary-select")}
            <button type="button" class="rbs-remove-boundary text-red-600 hover:text-red-800" title="Remove boundary">×</button>
          `;
          boundariesDiv.appendChild(div);
          this._attachBoundaryRemoveListeners();
        });
        this._attachBoundaryRemoveListeners();
      }

      if (ruleType === "CLEANUP") {
        this.container.querySelector("#rbs-cleanup-operation").addEventListener("change", () => {
          const op = this.container.querySelector("#rbs-cleanup-operation").value;
          this.container.querySelector("#rbs-cleanup-params").innerHTML = this._renderCleanupParams({ operation: op });
        });
      }
    }

    _attachRangeRemoveListeners() {
      this.container.querySelectorAll(".rbs-remove-range").forEach((btn) => {
        btn.onclick = () => btn.closest(".rbs-intensity-range").remove();
      });
    }

    _attachBoundaryRemoveListeners() {
      this.container.querySelectorAll(".rbs-remove-boundary").forEach((btn) => {
        btn.onclick = () => btn.closest(".rbs-crop-boundary").remove();
      });
    }

    _collectConfigFromEditor(rule) {
      let cfg = rule.config;
      switch (rule.rule_type) {
        case "BOOLEAN": {
          const root = this.container.querySelector("#rbs-boolean-root");
          rule.config = this._serializeBooleanNode(root);
          return;
        }
        case "INTENSITY":
          cfg.seed_type = this.container.querySelector("#rbs-intensity-seed-type").value;
          cfg.seed_roi = this.container.querySelector("#rbs-intensity-seed-roi")?.value || "";
          cfg.boundary_roi = this.container.querySelector("#rbs-intensity-boundary-roi")?.value || "";
          cfg.ranges = [];
          this.container.querySelectorAll(".rbs-intensity-range").forEach((div) => {
            const min = parseFloat(div.querySelector(".rbs-range-min").value);
            const max = parseFloat(div.querySelector(".rbs-range-max").value);
            if (!isNaN(min) && !isNaN(max)) {
              cfg.ranges.push({ min, max });
            }
          });
          break;
        case "MARGIN":
          cfg.variant = this.container.querySelector("#rbs-margin-variant").value;
          cfg.source = this.container.querySelector("#rbs-margin-source").value;
          cfg.margin_mm = parseFloat(this.container.querySelector("#rbs-margin-mm").value) || 0;
          cfg.margin_x_mm = parseFloat(this.container.querySelector("#rbs-margin-x").value) || 0;
          cfg.margin_y_mm = parseFloat(this.container.querySelector("#rbs-margin-y").value) || 0;
          cfg.margin_z_mm = parseFloat(this.container.querySelector("#rbs-margin-z").value) || 0;
          cfg.kernel_type = this.container.querySelector("#rbs-margin-kernel").value;
          break;
        case "CROP":
          cfg.source = this.container.querySelector("#rbs-crop-source").value;
          cfg.boundaries = [];
          this.container.querySelectorAll(".rbs-crop-boundary-select").forEach((select) => {
            if (select.value) cfg.boundaries.push(select.value);
          });
          break;
        case "CLEANUP":
          cfg.operation = this.container.querySelector("#rbs-cleanup-operation").value;
          cfg.source = this.container.querySelector("#rbs-cleanup-source").value;
          cfg.smoothing_mm = parseFloat(this._getValue("#rbs-cleanup-smoothing-mm")) || null;
          cfg.iterations = parseInt(this._getValue("#rbs-cleanup-iterations")) || null;
          cfg.min_size_mm3 = parseFloat(this._getValue("#rbs-cleanup-min-size")) || null;
          cfg.sigma_mm = parseFloat(this._getValue("#rbs-cleanup-sigma-mm")) || null;
          cfg.threshold = parseFloat(this._getValue("#rbs-cleanup-threshold")) || null;
          const fullyConnected = this.container.querySelector("#rbs-cleanup-fully-connected");
          cfg.fully_connected = fullyConnected ? fullyConnected.checked : null;
          break;
      }
    }

    _getValue(selector) {
      const el = this.container.querySelector(selector);
      return el ? el.value : "";
    }

    _attachConfigEventListeners(ruleType) {
      if (ruleType === "BOOLEAN") {
        this._attachBooleanEditorListeners(this.container.querySelector("#rbs-boolean-root"));
      }
      if (ruleType === "INTENSITY") {
        this.container.querySelector("#rbs-add-range").addEventListener("click", () => {
          const rangesDiv = this.container.querySelector("#rbs-intensity-ranges");
          const div = document.createElement("div");
          div.className = "flex items-center space-x-2 rbs-intensity-range";
          div.innerHTML = `
            <input type="number" step="any" class="rbs-range-min border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm px-3 py-2 w-32" placeholder="Min">
            <span>to</span>
            <input type="number" step="any" class="rbs-range-max border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm px-3 py-2 w-32" placeholder="Max">
            <button type="button" class="rbs-remove-range text-red-600 hover:text-red-800" title="Remove range">×</button>
          `;
          rangesDiv.appendChild(div);
          this._attachRangeRemoveListeners();
        });
        this._attachRangeRemoveListeners();

        const seedType = this.container.querySelector("#rbs-intensity-seed-type");
        seedType.addEventListener("change", () => {
          const selector = this.container.querySelector("#rbs-intensity-seed-selector");
          selector.classList.toggle("hidden", seedType.value === "IMAGE");
        });
      }

      if (ruleType === "MARGIN") {
        const variant = this.container.querySelector("#rbs-margin-variant");
        variant.addEventListener("change", () => {
          const isUniform = variant.value === "UNIFORM";
          this.container.querySelector("#rbs-margin-uniform").classList.toggle("hidden", !isUniform);
          this.container.querySelector("#rbs-margin-anisotropic").classList.toggle("hidden", isUniform);
        });
      }

      if (ruleType === "CROP") {
        this.container.querySelector("#rbs-add-boundary").addEventListener("click", () => {
          const boundariesDiv = this.container.querySelector("#rbs-crop-boundaries");
          const div = document.createElement("div");
          div.className = "flex items-center space-x-2 rbs-crop-boundary";
          div.innerHTML = `
            ${this._renderStructureSelect("rbs-crop-boundary-" + Date.now(), "", true, "rbs-crop-boundary-select")}
            <button type="button" class="rbs-remove-boundary text-red-600 hover:text-red-800" title="Remove boundary">×</button>
          `;
          boundariesDiv.appendChild(div);
          this._attachBoundaryRemoveListeners();
        });
        this._attachBoundaryRemoveListeners();
      }

      if (ruleType === "CLEANUP") {
        this.container.querySelector("#rbs-cleanup-operation").addEventListener("change", () => {
          const op = this.container.querySelector("#rbs-cleanup-operation").value;
          this.container.querySelector("#rbs-cleanup-params").innerHTML = this._renderCleanupParams({ operation: op });
        });
      }
    }

    _attachBooleanEditorListeners(rootElement) {
      if (!rootElement) return;

      rootElement.querySelectorAll(".rbs-boolean-op").forEach((select) => {
        select.addEventListener("change", (e) => {
          const node = e.target.closest(".rbs-boolean-node, .rbs-boolean-operand");
          if (node) node.dataset.operation = e.target.value;
        });
      });

      const addOperand = (e, isGroup) => {
        const container = e.target.closest(".rbs-boolean-node, .rbs-boolean-operand");
        const children = container.querySelector(":scope > .rbs-boolean-children");
        if (!children) return;
        const emptyMsg = children.querySelector(".rbs-boolean-empty-msg");
        if (emptyMsg) emptyMsg.remove();
        const index = children.children.length;
        const operandHtml = isGroup
          ? this._renderBooleanOperand({ operation: "UNION", operands: [] }, index)
          : this._renderBooleanOperand({ name: "" }, index);
        const wrapper = document.createElement("div");
        wrapper.innerHTML = operandHtml;
        children.appendChild(wrapper.firstElementChild);
        this._attachBooleanEditorListeners(container);
      };

      rootElement.querySelectorAll(".rbs-add-operand").forEach((btn) => {
        btn.addEventListener("click", (e) => addOperand(e, false));
      });

      rootElement.querySelectorAll(".rbs-add-group").forEach((btn) => {
        btn.addEventListener("click", (e) => addOperand(e, true));
      });

      rootElement.querySelectorAll(".rbs-remove-operand").forEach((btn) => {
        btn.addEventListener("click", (e) => {
          const operand = e.target.closest(".rbs-boolean-operand");
          const children = operand.parentElement;
          operand.remove();
          if (children && children.children.length === 0) {
            children.innerHTML = `<div class="text-sm text-gray-500 italic p-2 rbs-boolean-empty-msg">No operands. Add structures or groups below.</div>`;
          }
        });
      });

      rootElement.querySelectorAll(".rbs-convert-to-group").forEach((btn) => {
        btn.addEventListener("click", (e) => {
          const operand = e.target.closest(".rbs-boolean-operand");
          const groupConfig = { operation: "UNION", operands: [{ name: "" }] };
          const newHtml = this._renderBooleanOperand(groupConfig, parseInt(operand.dataset.index));
          const wrapper = document.createElement("div");
          wrapper.innerHTML = newHtml;
          operand.replaceWith(wrapper.firstElementChild);
          this._attachBooleanEditorListeners(rootElement);
        });
      });
    }

    _serializeBooleanNode(element) {
      const childrenContainer = element.querySelector(":scope > .rbs-boolean-children");
      const operation = element.dataset.operation || "UNION";
      const operands = [];

      if (childrenContainer) {
        childrenContainer.querySelectorAll(":scope > .rbs-boolean-operand").forEach((operand) => {
          const isGroup = operand.querySelector(":scope > .rbs-boolean-children") !== null;
          if (isGroup) {
            operands.push(this._serializeBooleanNode(operand));
          } else {
            const select = operand.querySelector(".rbs-boolean-roi");
            operands.push({ name: select ? select.value : "" });
          }
        });
      }

      return { operation, operands };
    }

    _escapeHtml(text) {
      const div = document.createElement("div");
      div.textContent = text;
      return div.innerHTML;
    }

    setAvailableStructures(structures) {
      this.availableStructures = structures || [];
      this._renderRulesList();
      if (this.editingRuleId) {
        const rule = this.state.rules.find((r) => r.tempId === this.editingRuleId);
        if (rule) this._renderRuleEditor(rule);
      }
    }

    getRules() {
      return this.state.rules.map((r) => ({ ...r }));
    }

    serialize() {
      return {
        rules: this.state.rules.map((r) => ({
          rule_type: r.rule_type,
          name: r.name,
          output_action: r.output_action,
          output_color: r.output_color,
          output_roi_type: r.output_roi_type,
          config: r.config,
        })),
      };
    }
  }

  window.RuleBasedPipelineBuilder = RuleBasedPipelineBuilder;
})();
