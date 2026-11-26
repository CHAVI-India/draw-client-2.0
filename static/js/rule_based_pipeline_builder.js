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
    RING: "Ring / Shell",
    OVERLAP: "Overlap",
    EXPAND_SUBTRACT: "Expand & Subtract",
    AVOID_MARGIN: "Avoid with Margin",
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

  const CLEANUP_OPERATIONS = {
    SMOOTH_STRUCTURE: { label: "Smooth Surface", params: ["smoothing_mm", "iterations"] },
    GAUSSIAN_SMOOTH: { label: "Gaussian Smooth", params: ["sigma_mm", "threshold"] },
    FILL_HOLES: { label: "Fill Holes", params: ["fully_connected"] },
    REMOVE_SMALL_COMPONENTS: { label: "Remove Small Components", params: ["min_size_mm3"] },
    KEEP_LARGEST_COMPONENT: { label: "Keep Largest Component", params: [] },
    KEEP_N_LARGEST_COMPONENT: { label: "Keep N Largest Components", params: ["n"] },
    CLOSE_GAPS: { label: "Close Gaps", params: ["gap_size_mm"] },
    REMOVE_PROTRUSIONS: { label: "Remove Protrusions", params: ["protrusion_size_mm"] },
  };

  function uuidv4() {
    return "10000000-1000-4000-8000-100000000000".replace(/[018]/g, (c) =>
      (c ^ (crypto.getRandomValues(new Uint8Array(1))[0] & (15 >> (c / 4)))).toString(16)
    );
  }

  // Build a {value: label} map from the backend's RULE_TYPE_CHOICES
  // (an array of [value, label] pairs). Returns null when absent/empty so the
  // caller can fall back to the built-in list.
  function buildRuleTypeMap(pairs) {
    if (!Array.isArray(pairs) || pairs.length === 0) return null;
    const map = {};
    for (const pair of pairs) {
      const [value, label] = pair;
      if (value != null) map[value] = label != null ? label : value;
    }
    return Object.keys(map).length ? map : null;
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
      // Prefer the backend-provided rule types (single source of truth);
      // fall back to the built-in list if none were supplied.
      this.ruleTypes = buildRuleTypeMap(this.options.ruleTypes) || RULE_TYPES;
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
                ${Object.entries(this.ruleTypes)
                  .map(([key, label]) => `<option value="${key}">${label}</option>`)
                  .join("")}
              </select>
              <button type="button" id="rbs-add-rule" class="inline-flex items-center h-10 px-3 border border-transparent text-sm font-medium rounded-md text-white bg-primary-600 hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary-500">
                + Add Rule
              </button>
            </div>
          </div>
          <div id="rbs-rules-list" class="space-y-3"></div>
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
        config: this._normalizeRuleConfig(
          rule.rule_type,
          rule.config || this._defaultConfig(rule.rule_type)
        ),
      };
      return normalized;
    }

    _normalizeRuleConfig(ruleType, config) {
      // Convert legacy margin-like configs (variant/uniform_mm or x/y/z) onto
      // the six-directional form so previously-saved rules keep working.
      if (!config) return config;
      const prefix = {
        MARGIN: "margin",
        RING: "thickness",
        EXPAND_SUBTRACT: "distance",
        AVOID_MARGIN: "margin",
      }[ruleType];
      if (!prefix) return config;
      const keys = ["l", "r", "a", "p", "h", "f"];
      if (keys.some((k) => config[`${prefix}_${k}_mm`] !== undefined && config[`${prefix}_${k}_mm`] !== null)) {
        return config;
      }
      const hasLegacy =
        config[`${prefix}_mm`] !== undefined ||
        config[`${prefix}_x_mm`] !== undefined ||
        config[`${prefix}_y_mm`] !== undefined ||
        config[`${prefix}_z_mm`] !== undefined;
      if (!hasLegacy) return config;
      let directional;
      if (config.variant === "ANISOTROPIC" && (config[`${prefix}_x_mm`] !== undefined || config[`${prefix}_y_mm`] !== undefined || config[`${prefix}_z_mm`] !== undefined)) {
        const x = config[`${prefix}_x_mm`] || 0,
              y = config[`${prefix}_y_mm`] || 0,
              z = config[`${prefix}_z_mm`] || 0;
        directional = { h: x, f: x, a: y, p: y, l: z, r: z };
      } else {
        const m = config[`${prefix}_mm`] || 0;
        directional = { l: m, r: m, a: m, p: m, h: m, f: m };
      }
      const out = {};
      for (const k of Object.keys(config)) {
        if (k === "variant" || k === "kernel_type" || k === `${prefix}_mm` ||
            k === `${prefix}_x_mm` || k === `${prefix}_y_mm` || k === `${prefix}_z_mm`) {
          continue;
        }
        out[k] = config[k];
      }
      for (const k of keys) out[`${prefix}_${k}_mm`] = directional[k];
      return out;
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
            source: "",
            margin_l_mm: 0.0,
            margin_r_mm: 0.0,
            margin_a_mm: 0.0,
            margin_p_mm: 0.0,
            margin_h_mm: 0.0,
            margin_f_mm: 0.0,
          };
        case "CROP":
          return { source: "", boundaries: [""] };
        case "CLEANUP":
          return { operation: "SMOOTH_STRUCTURE", source: "", smoothing_mm: 2.0, iterations: 1 };
        case "RING":
          return {
            source: "",
            thickness_l_mm: 0.0,
            thickness_r_mm: 0.0,
            thickness_a_mm: 0.0,
            thickness_p_mm: 0.0,
            thickness_h_mm: 0.0,
            thickness_f_mm: 0.0,
          };
        case "OVERLAP":
          return { source: "", others: [""] };
        case "EXPAND_SUBTRACT":
          return {
            source: "",
            subtract: "",
            distance_l_mm: 0.0,
            distance_r_mm: 0.0,
            distance_a_mm: 0.0,
            distance_p_mm: 0.0,
            distance_h_mm: 0.0,
            distance_f_mm: 0.0,
          };
        case "AVOID_MARGIN":
          return {
            source: "",
            avoid: "",
            margin_l_mm: 0.0,
            margin_r_mm: 0.0,
            margin_a_mm: 0.0,
            margin_p_mm: 0.0,
            margin_h_mm: 0.0,
            margin_f_mm: 0.0,
          };
        default:
          return {};
      }
    }

    addRule(ruleType) {
      const rule = this._normalizeRule({ rule_type: ruleType });
      this.state.rules.push(rule);
      this._setEditing(rule.tempId);
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

      // Guard: block a move that would place a dependent ROI above the rule
      // that produces the structure it references (a forward reference).
      const trial = this.state.rules.slice();
      const [moved] = trial.splice(idx, 1);
      trial.splice(newIdx, 0, moved);
      const violations = this._validateRuleOrder(trial);
      if (violations.length > 0) {
        this._showMoveBlocked(
          `Can't move that rule: ${violations[0]}`
        );
        return;
      }

      this.state.rules.splice(idx, 1);
      this.state.rules.splice(newIdx, 0, moved);
      this._renderRulesList();
    }

    _showMoveBlocked(message) {
      // Transient banner explaining why a move was blocked.
      let box = this.container.querySelector("#rbs-move-blocked");
      if (!box) {
        box = document.createElement("div");
        box.id = "rbs-move-blocked";
        box.className =
          "hidden rounded-md bg-amber-50 border border-amber-200 p-3 text-sm text-amber-800";
        box.setAttribute("role", "alert");
        const list = this.container.querySelector("#rbs-rules-list");
        list.parentNode.insertBefore(box, list);
      }
      box.textContent = message;
      box.classList.remove("hidden");
      box.scrollIntoView({ behavior: "smooth", block: "center" });
      clearTimeout(this._moveBlockedTimer);
      this._moveBlockedTimer = setTimeout(() => {
        box.classList.add("hidden");
      }, 6000);
    }

    // Collect the structure names a rule references as INPUTS (mirrors the
    // server-side _collect_required_structure_names).
    _collectRequiredStructureNames(rule) {
      const names = new Set();
      const cfg = rule.config || {};
      const rt = rule.rule_type;
      const add = (n) => {
        if (n) names.add(n);
      };
      if (rt === "BOOLEAN") {
        this._collectBooleanOperandNames(cfg, names);
      } else if (rt === "INTENSITY") {
        if (cfg.seed_type === "STRUCTURE") add(cfg.seed_roi);
        add(cfg.boundary_roi);
      } else if (rt === "MARGIN" || rt === "CLEANUP" || rt === "RING") {
        add(cfg.source);
      } else if (rt === "CROP") {
        add(cfg.source);
        (cfg.boundaries || []).forEach(add);
      } else if (rt === "OVERLAP") {
        add(cfg.source);
        (cfg.others || []).forEach(add);
      } else if (rt === "EXPAND_SUBTRACT") {
        add(cfg.source);
        add(cfg.subtract);
      } else if (rt === "AVOID_MARGIN") {
        add(cfg.source);
        add(cfg.avoid);
      }
      return [...names];
    }

    _collectBooleanOperandNames(node, names) {
      if (node && node.operation) {
        (node.operands || []).forEach((op) => this._collectBooleanOperandNames(op, names));
      } else if (node && node.name) {
        names.add(node.name);
      }
    }

    // Return forward-reference violations for an ordered rule list: a rule may
    // not reference a structure produced by the same or a later rule.
    _validateRuleOrder(rules) {
      const violations = [];
      const producedBy = {};
      rules.forEach((r, i) => {
        const n = (r.name || "").trim();
        if (n) producedBy[n] = i;
      });
      rules.forEach((rule, i) => {
        for (const required of this._collectRequiredStructureNames(rule)) {
          const srcIdx = producedBy[required];
          if (srcIdx !== undefined && srcIdx >= i) {
            violations.push(
              `rule '${rule.name || i + 1}' references '${required}', which is produced by rule ${
                srcIdx + 1
              }` +
                (srcIdx === i ? " (itself)" : " (a later step)") +
                ". The producing rule must come first."
            );
          }
        }
      });
      return violations;
    }

    editRule(tempId) {
      const rule = this.state.rules.find((r) => r.tempId === tempId);
      if (!rule) return;
      this._setEditing(tempId);
    }

    _setEditing(tempId) {
      this.editingRuleId = tempId;
      this._renderRulesList();
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
          const isEditing = rule.tempId === this.editingRuleId;
          const inlineEditor = isEditing
            ? `\n              <div class="mt-3 border-t border-gray-200 pt-3">${this._renderRuleEditorContent(rule)}</div>`
            : "";
          return `
            <div class="bg-white border rounded-md p-3 shadow-sm ${isEditing ? "ring-2 ring-primary-500" : ""}" data-temp-id="${rule.tempId}">
              <div class="flex items-start justify-between">
              <div class="flex items-start space-x-3">
                <div class="cursor-move text-gray-400 hover:text-gray-600" title="Drag to reorder">
                  <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 8h16M4 16h16"></path></svg>
                </div>
                <div>
                  <div class="flex items-center space-x-2">
                    <span class="text-xs font-mono text-gray-500">${index + 1}</span>
                    <span class="font-medium">${this._escapeHtml(rule.name || "Unnamed")}</span>
                    <span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-blue-100 text-blue-800">${this.ruleTypes[rule.rule_type] || rule.rule_type}</span>
                    <span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${rule.output_action === "CREATE_NEW" ? "bg-green-100 text-green-800" : "bg-yellow-100 text-yellow-800"}">${rule.output_action === "CREATE_NEW" ? "Create" : "Replace"}</span>
                  </div>
                  <div class="text-sm text-gray-600 mt-1">${this._escapeHtml(summary)}</div>
                </div>
              </div>
              <div class="flex items-center space-x-1">
                <button type="button" class="rbs-move-up p-1 text-gray-500 hover:text-gray-700 disabled:opacity-40" title="Move up" ${isEditing || index === 0 ? "disabled" : ""}>
                  <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 15l7-7 7 7"></path></svg>
                </button>
                <button type="button" class="rbs-move-down p-1 text-gray-500 hover:text-gray-700 disabled:opacity-40" title="Move down" ${isEditing || index === this.state.rules.length - 1 ? "disabled" : ""}>
                  <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"></path></svg>
                </button>
                <button type="button" class="rbs-edit-rule p-1 text-blue-600 hover:text-blue-800" title="Edit">
                  <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"></path></svg>
                </button>
                <button type="button" class="rbs-delete-rule p-1 text-red-600 hover:text-red-800" title="Delete">
                  <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>
                </button>
              </div>
              </div>${inlineEditor}
            </div>
          `;
        })
        .join("");

      this._attachRuleListEvents();
      if (this.editingRuleId) {
        const editing = this.state.rules.find((r) => r.tempId === this.editingRuleId);
        if (editing) this._attachRuleEditorEvents(editing);
      }
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
        case "MARGIN": {
          const labels = { l: "L", r: "R", a: "A", p: "P", h: "S", f: "I" };
          const dirs = ["l", "r", "a", "p", "h", "f"].filter((k) => cfg[`margin_${k}_mm`]);
          if (!dirs.length) return `No margin on ${cfg.source}`;
          const parts = dirs
            .map((k) => `${labels[k]} ${cfg[`margin_${k}_mm`] > 0 ? "+" : ""}${cfg[`margin_${k}_mm`]}mm`)
            .join(", ");
          return `Margin on ${cfg.source}: ${parts}`;
        }
        case "CROP":
          return `Crop ${cfg.source} to ${cfg.boundaries.join(", ")}`;
        case "CLEANUP":
          return `${CLEANUP_OPERATIONS[cfg.operation].label} on ${cfg.source}`;
        case "RING":
          return this._summarizeDirectional(cfg, "thickness", `Ring around ${cfg.source}`);
        case "OVERLAP": {
          const n = (cfg.others || []).length;
          return `Overlap ${cfg.source} with ${n} structure(s)`;
        }
        case "EXPAND_SUBTRACT": {
          const d = this._summarizeDirectionalValues(cfg, "distance");
          return d ? `Expand ${cfg.source} by ${d}, subtract ${cfg.subtract}` : `No expansion on ${cfg.source}, subtract ${cfg.subtract}`;
        }
        case "AVOID_MARGIN": {
          const d = this._summarizeDirectionalValues(cfg, "margin");
          return d ? `Avoid ${cfg.avoid} by ${d} from ${cfg.source}` : `No avoidance margin around ${cfg.avoid} from ${cfg.source}`;
        }
        case "EMPTY":
          return "Empty ROI";
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

    _renderRuleEditorContent(rule) {
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
        case "RING":
          configHtml = this._renderRingEditor(rule.config);
          break;
        case "OVERLAP":
          configHtml = this._renderOverlapEditor(rule.config);
          break;
        case "EXPAND_SUBTRACT":
          configHtml = this._renderExpandSubtractEditor(rule.config);
          break;
        case "AVOID_MARGIN":
          configHtml = this._renderAvoidMarginEditor(rule.config);
          break;
        case "EMPTY":
          configHtml = `<p class="text-sm text-gray-500">Creates an empty (zero-voxel) ROI. No input structure or parameters are required.</p>`;
          break;
      }

      return `
        <div class="space-y-4">
          <div class="flex justify-between items-center">
            <h4 class="font-semibold">Edit Rule: ${this._escapeHtml(rule.name || "Unnamed")}</h4>
            <button type="button" id="rbs-close-editor" class="text-gray-500 hover:text-gray-700">
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
            </button>
          </div>
          <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label class="block text-sm font-medium text-gray-700">Output ROI Name</label>
              <input type="text" id="rbs-rule-name" value="${this._escapeHtml(rule.name)}" class="mt-1 block w-full border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm px-3 py-2" maxlength="${this._roiNameMaxLength()}">
            </div>
            <div>
              <label class="block text-sm font-medium text-gray-700">Output Action</label>
              <select id="rbs-rule-output-action" class="mt-1 block w-full border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm px-3 py-2">
                <option value="CREATE_NEW" ${rule.output_action === "CREATE_NEW" ? "selected" : ""}>Create new ROI</option>
                <option value="REPLACE_EXISTING" ${rule.output_action === "REPLACE_EXISTING" ? "selected" : ""}>Replace existing ROI</option>
                <option value="INTERMEDIATE" ${rule.output_action === "INTERMEDIATE" ? "selected" : ""}>Intermediate (not exported)</option>
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

    }

    _attachRuleEditorEvents(rule) {
      this.container.querySelector("#rbs-close-editor").addEventListener("click", () => this._hideEditor());
      this.container.querySelector("#rbs-cancel-edit").addEventListener("click", () => this._hideEditor());
      this.container.querySelector("#rbs-save-rule").addEventListener("click", () => this._saveCurrentRule());
      this._attachConfigEventListeners(rule.rule_type);
    }

    _hideEditor() {
      this._setEditing(null);
    }

    _saveCurrentRule() {
      const rule = this.state.rules.find((r) => r.tempId === this.editingRuleId);
      if (!rule) return;

      const newName = this.container.querySelector("#rbs-rule-name").value.trim();
      if (!newName) {
        alert("Output ROI name is required");
        return;
      }
      const maxLen = this._roiNameMaxLength();
      if (newName.length > maxLen) {
        alert(
          `Output ROI name '${newName}' is too long (${newName.length} characters); the maximum is ${maxLen} characters.`
        );
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
      const dirs = [
        ["l", "Left"], ["r", "Right"], ["a", "Anterior"],
        ["p", "Posterior"], ["h", "Superior (Head)"], ["f", "Inferior (Feet)"],
      ];
      const inputs = dirs.map(
        ([k, label]) => `
          <div>
            <label class="block text-sm font-medium text-gray-700">${label} (mm)</label>
            <input type="number" step="any" id="rbs-margin-${k}" value="${config[`margin_${k}_mm`] ?? 0}" class="mt-1 block w-full border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm px-3 py-2">
          </div>`
      ).join("");
      return `
        <div class="space-y-4">
          <div>
            <label class="block text-sm font-medium text-gray-700">Source Structure</label>
            ${this._renderStructureSelect("rbs-margin-source", config.source)}
          </div>
          <div class="rounded-md bg-amber-50 border border-amber-200 px-3 py-2 text-xs text-amber-800 leading-relaxed">
            Set a margin in millimetres for each direction. A <b>positive</b> value
            expands (grows) the structure toward that side; a <b>negative</b> value
            contracts (shrinks) it. Leave at 0 to leave that side unchanged.
          </div>
          <div class="grid grid-cols-2 gap-3">${inputs}</div>
        </div>
      `;
    }

    // Summary fragment for the non-zero directions of a six-directional
    // config, e.g. "L 5mm, R 3mm". Returns null when no direction is set.
    _summarizeDirectionalValues(cfg, prefix) {
      const labels = { l: "L", r: "R", a: "A", p: "P", h: "S", f: "I" };
      const dirs = ["l", "r", "a", "p", "h", "f"].filter((k) => cfg[`${prefix}_${k}_mm`]);
      if (!dirs.length) return null;
      return dirs.map((k) => `${labels[k]} ${cfg[`${prefix}_${k}_mm`]}mm`).join(", ");
    }

    _summarizeDirectional(cfg, prefix, prefixLabel) {
      const d = this._summarizeDirectionalValues(cfg, prefix);
      return d ? `${prefixLabel}: ${d}` : `${prefixLabel} (no thickness set)`;
    }

    // Six per-direction number inputs, ids `${idPrefix}-${k}`.
    _directionalInputGrid(idPrefix, prefix, cfg) {
      const dirs = [
        ["l", "Left"], ["r", "Right"], ["a", "Anterior"],
        ["p", "Posterior"], ["h", "Superior (Head)"], ["f", "Inferior (Feet)"],
      ];
      const inputs = dirs.map(
        ([k, label]) => `
          <div>
            <label class="block text-sm font-medium text-gray-700">${label} (mm)</label>
            <input type="number" step="any" min="0" id="${idPrefix}-${k}" value="${cfg[`${prefix}_${k}_mm`] ?? 0}"
                   class="mt-1 block w-full border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm px-3 py-2">
          </div>`
      ).join("");
      return `<div class="grid grid-cols-2 gap-3">${inputs}</div>`;
    }

    _directionalHelpBox(expandWord) {
      return `
        <div class="rounded-md bg-amber-50 border border-amber-200 px-3 py-2 text-xs text-amber-800 leading-relaxed">
          Set a distance in millimetres for each direction. A value expands
          (${expandWord}) the structure toward that side; leave at <b>0</b> to
          leave that side unchanged. Set the same value in all six directions
          for a uniform margin.
        </div>`;
    }

    _renderRingEditor(config) {
      return `
        <div class="space-y-4">
          <div>
            <label class="block text-sm font-medium text-gray-700">Source Structure</label>
            ${this._renderStructureSelect("rbs-ring-source", config.source)}
          </div>
          ${this._directionalHelpBox("thicken")}
          <div class="rounded-md border border-gray-200 px-3 py-2 text-xs text-gray-600">
            The source structure itself is removed — the result is a shell of the
            given thickness around it.
          </div>
          ${this._directionalInputGrid("rbs-ring", "thickness", config)}
        </div>
      `;
    }

    _renderOverlapEditor(config) {
      const othersHtml = (config.others || [])
        .map(
          (name, idx) => `
          <div class="flex items-center space-x-2 rbs-overlap-other">
            ${this._renderStructureSelect("rbs-overlap-other-" + idx, name, true, "rbs-overlap-other-select")}
            <button type="button" class="rbs-remove-overlap text-red-600 hover:text-red-800" title="Remove structure">×</button>
          </div>
        `)
        .join("");

      return `
        <div class="space-y-4">
          <div>
            <label class="block text-sm font-medium text-gray-700">Source Structure</label>
            ${this._renderStructureSelect("rbs-overlap-source", config.source)}
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-700">Overlapping Structures</label>
            <div id="rbs-overlap-others" class="space-y-2 mt-1">${othersHtml}</div>
            <button type="button" id="rbs-add-overlap-other" class="mt-2 text-sm text-primary-600 hover:text-primary-800">+ Add structure</button>
          </div>
        </div>
      `;
    }

    _renderExpandSubtractEditor(config) {
      return `
        <div class="space-y-4">
          <div>
            <label class="block text-sm font-medium text-gray-700">Structure to Expand</label>
            ${this._renderStructureSelect("rbs-es-source", config.source)}
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-700">Structure to Subtract</label>
            ${this._renderStructureSelect("rbs-es-subtract", config.subtract, true)}
          </div>
          ${this._directionalHelpBox("expand")}
          ${this._directionalInputGrid("rbs-es", "distance", config)}
        </div>
      `;
    }

    _renderAvoidMarginEditor(config) {
      return `
        <div class="space-y-4">
          <div>
            <label class="block text-sm font-medium text-gray-700">Structure to Keep</label>
            ${this._renderStructureSelect("rbs-am-source", config.source)}
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-700">Structure to Avoid</label>
            ${this._renderStructureSelect("rbs-am-avoid", config.avoid, true)}
          </div>
          ${this._directionalHelpBox("expand")}
          ${this._directionalInputGrid("rbs-am", "margin", config)}
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
      if (params.includes("n")) {
        html += `
          <label class="block text-sm font-medium text-gray-700">Keep (N)</label>
          <input type="number" step="1" id="rbs-cleanup-n" value="${config.n || 1}" class="mt-1 block w-full border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm px-3 py-2">
        `;
      }
      if (params.includes("gap_size_mm")) {
        html += `
          <label class="block text-sm font-medium text-gray-700">Gap Size (mm)</label>
          <input type="number" step="any" id="rbs-cleanup-gap-size-mm" value="${config.gap_size_mm || 2.0}" class="mt-1 block w-full border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm px-3 py-2">
        `;
      }
      if (params.includes("protrusion_size_mm")) {
        html += `
          <label class="block text-sm font-medium text-gray-700">Protrusion Size (mm)</label>
          <input type="number" step="any" id="rbs-cleanup-protrusion-size-mm" value="${config.protrusion_size_mm || 2.0}" class="mt-1 block w-full border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm px-3 py-2">
        `;
      }
      return html;
    }

    _renderStructureSelect(id, value, allowEmpty = false, className = "") {
      // Free-text structure entry: an <input> with a <datalist> of suggestions.
      // Suggestions come from (a) ROIs generated by earlier rules and (b) the
      // available structures (persisted catalog / live sample). The user may
      // also type any custom name (e.g. a structure that exists only in the
      // target RTStruct).
      const currentIndex = this.state.rules.findIndex((r) => r.tempId === this.editingRuleId);
      const suggestions = [];
      if (currentIndex > 0) {
        for (let i = 0; i < currentIndex; i++) {
          const r = this.state.rules[i];
          if (r.name) {
            suggestions.push({ value: r.name, label: `${r.name} (generated)` });
          }
        }
      }
      for (const s of this.availableStructures) {
        suggestions.push({ value: s.value, label: s.label || s.value });
      }

      const datalistId = id + "-datalist";
      const optionsHtml = suggestions
        .map(
          (s) =>
            `<option value="${this._escapeHtml(s.value)}">${this._escapeHtml(s.label)}</option>`
        )
        .join("");

      const placeholder = allowEmpty
        ? "Select or type a structure name"
        : "Structure name (select or type)";

      return `
        <input type="text" id="${id}" list="${datalistId}"
          value="${this._escapeHtml(value || "")}"
          class="${className} mt-1 block w-full border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 text-sm px-3 py-2"
          placeholder="${placeholder}" autocomplete="off" spellcheck="false">
        <datalist id="${datalistId}">${optionsHtml}</datalist>
      `;
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
    _attachOverlapRemoveListeners() {
      this.container.querySelectorAll(".rbs-remove-overlap").forEach((btn) => {
        btn.onclick = () => btn.closest(".rbs-overlap-other").remove();
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
          cfg.source = this.container.querySelector("#rbs-margin-source").value;
          for (const k of ["l", "r", "a", "p", "h", "f"]) {
            cfg[`margin_${k}_mm`] =
              parseFloat(this.container.querySelector(`#rbs-margin-${k}`).value) || 0;
          }
          break;
        case "CROP":
          cfg.source = this.container.querySelector("#rbs-crop-source").value;
          cfg.boundaries = [];
          this.container.querySelectorAll(".rbs-crop-boundary-select").forEach((select) => {
            if (select.value) cfg.boundaries.push(select.value);
          });
          break;
        case "RING":
          cfg.source = this._getValue("#rbs-ring-source");
          for (const k of ["l", "r", "a", "p", "h", "f"]) {
            cfg[`thickness_${k}_mm`] =
              parseFloat(this._getValue(`#rbs-ring-${k}`)) || 0;
          }
          break;
        case "OVERLAP":
          cfg.source = this._getValue("#rbs-overlap-source");
          cfg.others = [];
          this.container.querySelectorAll(".rbs-overlap-other-select").forEach((select) => {
            if (select.value) cfg.others.push(select.value);
          });
          break;
        case "EXPAND_SUBTRACT":
          cfg.source = this._getValue("#rbs-es-source");
          cfg.subtract = this._getValue("#rbs-es-subtract");
          for (const k of ["l", "r", "a", "p", "h", "f"]) {
            cfg[`distance_${k}_mm`] = parseFloat(this._getValue(`#rbs-es-${k}`)) || 0;
          }
          delete cfg.variant;
          delete cfg.kernel_type;
          delete cfg.distance_mm;
          delete cfg.distance_x_mm;
          delete cfg.distance_y_mm;
          delete cfg.distance_z_mm;
          break;
        case "AVOID_MARGIN":
          cfg.source = this._getValue("#rbs-am-source");
          cfg.avoid = this._getValue("#rbs-am-avoid");
          for (const k of ["l", "r", "a", "p", "h", "f"]) {
            cfg[`margin_${k}_mm`] = parseFloat(this._getValue(`#rbs-am-${k}`)) || 0;
          }
          delete cfg.variant;
          delete cfg.kernel_type;
          delete cfg.margin_mm;
          delete cfg.margin_x_mm;
          delete cfg.margin_y_mm;
          delete cfg.margin_z_mm;
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
          cfg.n = parseInt(this._getValue("#rbs-cleanup-n")) || null;
          cfg.gap_size_mm = parseFloat(this._getValue("#rbs-cleanup-gap-size-mm")) || null;
          cfg.protrusion_size_mm = parseFloat(this._getValue("#rbs-cleanup-protrusion-size-mm")) || null;
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

      if (ruleType === "RING") {
        // Six-directional ring thickness; nothing to wire up.
      }
      if (ruleType === "OVERLAP") {
        this.container.querySelector("#rbs-add-overlap-other").addEventListener("click", () => {
          const othersDiv = this.container.querySelector("#rbs-overlap-others");
          const div = document.createElement("div");
          div.className = "flex items-center space-x-2 rbs-overlap-other";
          div.innerHTML = `
            ${this._renderStructureSelect("rbs-overlap-other-" + Date.now(), "", true, "rbs-overlap-other-select")}
            <button type="button" class="rbs-remove-overlap text-red-600 hover:text-red-800" title="Remove structure">×</button>
          `;
          othersDiv.appendChild(div);
          this._attachOverlapRemoveListeners();
        });
        this._attachOverlapRemoveListeners();
      }
      if (ruleType === "EXPAND_SUBTRACT") {
        // Six-directional distances; nothing to wire up.
      }
      if (ruleType === "AVOID_MARGIN") {
        // Six-directional margins; nothing to wire up.
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
      // Event delegation: the root element is (re)created every time the editor
      // re-renders, so we attach ONE delegated listener here and never re-attach
      // when operands are added/removed/converted. The previous implementation
      // re-attached click handlers to buttons that were already listening after
      // every add/convert, so the number of handlers (and therefore the number
      // of rows appended per click) multiplied on each click.
      if (rootElement.dataset.rbsDelegated === "true") return;
      rootElement.dataset.rbsDelegated = "true";

      rootElement.addEventListener("click", (e) => {
        if (e.target.closest(".rbs-add-operand")) {
          this._addBooleanOperand(e, false);
        } else if (e.target.closest(".rbs-add-group")) {
          this._addBooleanOperand(e, true);
        } else if (e.target.closest(".rbs-remove-operand")) {
          this._removeBooleanOperand(e);
        } else if (e.target.closest(".rbs-convert-to-group")) {
          this._convertToGroup(e);
        }
      });

      // "change" events bubble, so delegate the operation-select change too.
      rootElement.addEventListener("change", (e) => {
        if (e.target.classList && e.target.classList.contains("rbs-boolean-op")) {
          const node = e.target.closest(".rbs-boolean-node, .rbs-boolean-operand");
          if (node) node.dataset.operation = e.target.value;
        }
      });
    }

    _addBooleanOperand(e, isGroup) {
      const container = e.target.closest(".rbs-boolean-node, .rbs-boolean-operand");
      const children = container && container.querySelector(":scope > .rbs-boolean-children");
      if (!children) return;
      const emptyMsg = children.querySelector(".rbs-boolean-empty-msg");
      if (emptyMsg) emptyMsg.remove();
      const index = children.children.length;
      const operand = isGroup ? { operation: "UNION", operands: [] } : { name: "" };
      const wrapper = document.createElement("div");
      wrapper.innerHTML = this._renderBooleanOperand(operand, index);
      children.appendChild(wrapper.firstElementChild);
      // No re-attach: the delegated listeners on the root already cover the new
      // operand's buttons, including a group's nested add/remove controls.
    }

    _removeBooleanOperand(e) {
      const operand = e.target.closest(".rbs-boolean-operand");
      if (!operand) return;
      const children = operand.parentElement;
      operand.remove();
      if (children && children.children.length === 0) {
        children.innerHTML = `<div class="text-sm text-gray-500 italic p-2 rbs-boolean-empty-msg">No operands. Add structures or groups below.</div>`;
      }
    }

    _convertToGroup(e) {
      const operand = e.target.closest(".rbs-boolean-operand");
      if (!operand) return;
      const groupConfig = { operation: "UNION", operands: [{ name: "" }] };
      const wrapper = document.createElement("div");
      wrapper.innerHTML = this._renderBooleanOperand(groupConfig, parseInt(operand.dataset.index));
      operand.replaceWith(wrapper.firstElementChild);
      // No re-attach: delegation covers the new group's controls.
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
      div.textContent = String(text ?? "");
      // Also escape quotes so the result is safe inside HTML attribute values
      // (used for free-text structure names, which may contain quotes).
      return div.innerHTML.replace(/"/g, "&quot;").replace(/'/g, "&#39;");
    }

    setAvailableStructures(structures) {
      this.availableStructures = structures || [];
      this._renderRulesList();
    }

    getRules() {
      return this.state.rules.map((r) => ({ ...r }));
    }

    _roiNameMaxLength() {
      const raw = this.container.getAttribute("data-roi-name-max-length");
      const n = parseInt(raw, 10);
      return Number.isFinite(n) && n > 0 ? n : 54;
    }

    validate() {
      // Mirror the server-side _validate_pipeline_rules name checks so the
      // user sees problems before the form is submitted (the server is still
      // the source of truth; this only improves the experience).
      const errors = [];
      const maxLen = this._roiNameMaxLength();
      const firstSeen = new Map();
      this.state.rules.forEach((rule, idx) => {
        const name = (rule.name || "").trim();
        const label = `Rule ${idx + 1}`;
        if (!name) {
          errors.push(`${label}: an output ROI name is required.`);
        } else if (name.length > maxLen) {
          errors.push(
            `${label}: output ROI name '${name}' is too long (${name.length} characters); the maximum is ${maxLen} characters.`
          );
        } else if (firstSeen.has(name)) {
          errors.push(
            `Output ROI name '${name}' is used more than once (rules ${firstSeen.get(name) + 1} and ${idx + 1}). Names must be unique.`
          );
        } else {
          firstSeen.set(name, idx);
        }

        // Required input: a source-based rule must reference a structure.
        const reqErr = this._requiredInputError(rule);
        if (reqErr) {
          errors.push(
            `${label}${name ? ` ('${name}')` : ""}: ${reqErr}.`
          );
        }
      });

      // Ordering: no rule may reference a ROI produced by the same or a later
      // rule (forward reference). Mirrors the server-side check.
      const orderViolations = this._validateRuleOrder(this.state.rules);
      for (const v of orderViolations) {
        errors.push(`Ordering: ${v}`);
      }

      return errors;
    }

    _requiredInputError(rule) {
      // Mirror the server-side `_required_input_error` so the user sees a
      // missing input before the form is submitted.
      const cfg = rule.config || {};
      const has = (v) => !!(v || "").trim();
      switch (rule.rule_type) {
        case "MARGIN":
        case "CLEANUP":
        case "RING":
          return has(cfg.source) ? null : `needs a source structure (${rule.rule_type})`;
        case "CROP":
          if (!has(cfg.source)) return "needs a source structure (Crop)";
          if (!(cfg.boundaries || []).some(has))
            return "needs at least one boundary structure (Crop)";
          return null;
        case "OVERLAP":
          if (!has(cfg.source)) return "needs a source structure (Overlap)";
          if (!(cfg.others || []).some(has))
            return "needs at least one other structure (Overlap)";
          return null;
        case "EXPAND_SUBTRACT":
          if (!has(cfg.source)) return "needs a source structure (Expand & Subtract)";
          if (!has(cfg.subtract)) return "needs a subtract structure (Expand & Subtract)";
          return null;
        case "AVOID_MARGIN":
          if (!has(cfg.source)) return "needs a source structure (Avoid-with-Margin)";
          if (!has(cfg.avoid)) return "needs an avoid structure (Avoid-with-Margin)";
          return null;
        case "INTENSITY":
          if (cfg.seed_type === "STRUCTURE" && !has(cfg.seed_roi))
            return "needs a seed structure (Intensity)";
          if (cfg.seed_type === "BOUNDARY" && !has(cfg.boundary_roi))
            return "needs a boundary structure (Intensity)";
          return null;
        default:
          return null;
      }
    }

    showValidationErrors(errors) {
      this.clearValidationErrors();
      if (!errors.length) return;
      const box = document.createElement("div");
      box.id = "rbs-validation-errors";
      box.className = "rounded-md bg-red-50 border border-red-200 p-4 mb-4";
      box.setAttribute("role", "alert");
      box.innerHTML = `
        <div class="text-sm font-medium text-red-800">Please fix the following before saving:</div>
        <ul class="mt-2 text-sm text-red-700 list-disc list-inside space-y-1">
          ${errors.map((e) => `<li>${this._escapeHtml(e)}</li>`).join("")}
        </ul>
      `;
      this.container.insertBefore(box, this.container.firstChild);
      box.scrollIntoView({ behavior: "smooth", block: "center" });
    }

    clearValidationErrors() {
      const box = this.container.querySelector("#rbs-validation-errors");
      if (box) box.remove();
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
        // Persist the structure snapshot (names + colors + types) so the
        // pipeline's structure inputs can be re-populated when edited later.
        structures: this.availableStructures.map((s) => ({
          name: s.value,
          color: s.color || null,
          roi_type: s.roi_type || null,
        })),
      };
    }
  }

  window.RuleBasedPipelineBuilder = RuleBasedPipelineBuilder;
})();
