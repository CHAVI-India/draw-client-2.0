/* Regression test: the boolean rule editor shows a live, plain-language
 * description of the expression (with brackets for groups) so any user can read
 * what the operation will produce. Run: node static/js/tests/boolean_preview_test.js */
const fs = require("fs");
const path = require("path");
const { JSDOM } = require(path.join(process.cwd(), "node_modules/jsdom"));
const assert = require("assert");

const SCRIPT = path.join(__dirname, "..", "rule_based_pipeline_builder.js");
const script = fs.readFileSync(SCRIPT, "utf8");

const dom = new JSDOM(
  `<!DOCTYPE html><html><body><div id="pipelineBuilder" data-roi-name-max-length="54"></div></body></html>`,
  { runScripts: "outside-only", pretendToBeVisual: true }
);
const { window } = dom;
if (!window.crypto || !window.crypto.getRandomValues) {
  window.crypto = {
    getRandomValues: (arr) => {
      for (let i = 0; i < arr.length; i++) arr[i] = Math.floor(Math.random() * 256);
      return arr;
    },
  };
}
window.confirm = () => true;
window.alert = () => {};
window.eval(script);
const Builder = window.RuleBasedPipelineBuilder;
assert.ok(Builder, "RuleBasedPipelineBuilder should be defined");

const structures = ["CTV", "Lung", "Spleen", "Body"].map((v) => ({ value: v, label: v, kind: "existing" }));
const ruleTypes = [["BOOLEAN", "Boolean Expression"], ["MARGIN", "Margin"]];

const builder = new Builder("pipelineBuilder", {
  existingRules: [], availableStructures: structures, ruleTypes,
});
const $ = (sel) => window.document.querySelector(sel);
const root = () => $("#rbs-boolean-root");
const previewText = () => $("#rbs-boolean-preview .rbs-boolean-preview-text");
const click = (el) => el.dispatchEvent(new window.Event("click", { bubbles: true }));
const change = (el) => el.dispatchEvent(new window.Event("change", { bubbles: true }));

// ---- Unit: the plain-language summarizer -------------------------------
const S = (node) => builder._summarizeBooleanPlain(node);
assert.strictEqual(
  S({ operation: "UNION", operands: [{ name: "CTV" }, { name: "Lung" }, { name: "Spleen" }] }),
  "CTV or Lung or Spleen"
);
assert.strictEqual(
  S({ operation: "INTERSECTION", operands: [{ name: "CTV" }, { name: "Lung" }] }),
  "CTV and Lung"
);
assert.strictEqual(
  S({ operation: "SUBTRACT", operands: [
    { name: "CTV" },
    { operation: "UNION", operands: [{ name: "Lung" }, { name: "Spleen" }] },
  ]}),
  "CTV minus (Lung or Spleen)"
);
assert.strictEqual(
  S({ operation: "XOR", operands: [{ name: "A" }, { name: "B" }] }),
  "A or B (but not both)"
);
assert.strictEqual(S({ operation: "UNION", operands: [] }), "(no structures yet)");
assert.strictEqual(S({ operation: "UNION", operands: [{ name: "" }] }), "(unselected)");

// ---- Integration: the live preview in the editor -----------------------
builder.addRule("BOOLEAN");
assert.ok(previewText(), "preview section should render");
assert.strictEqual(previewText().textContent, "(no structures yet)");

// Add three structures; the default root operation is UNION.
for (let i = 0; i < 3; i++) click(root().querySelector(".rbs-add-operand"));
const rois = root().querySelectorAll(".rbs-boolean-roi");
rois[0].value = "CTV"; change(rois[0]);
rois[1].value = "Lung"; change(rois[1]);
rois[2].value = "Spleen"; change(rois[2]);
assert.strictEqual(previewText().textContent, "CTV or Lung or Spleen");

// Switch the root operation to SUBTRACT -> "CTV minus Lung minus Spleen".
const opSelect = root().querySelector(".rbs-boolean-op");
opSelect.value = "SUBTRACT";
change(opSelect);
assert.strictEqual(previewText().textContent, "CTV minus Lung minus Spleen");

// Add a group and drop a structure inside it -> the group shows in brackets.
click(root().querySelector(".rbs-boolean-add-controls .rbs-add-group"));
const operands = root().querySelectorAll(".rbs-boolean-children > .rbs-boolean-operand");
const newGroup = operands[operands.length - 1];
// A fresh group has no operand yet; add one inside it, then name it.
click(newGroup.querySelector(".rbs-add-operand"));
const groupRoi = newGroup.querySelector(".rbs-boolean-roi");
groupRoi.value = "Body"; change(groupRoi);
assert.ok(
  /\(Body\)/.test(previewText().textContent),
  `group should appear in brackets; got: ${previewText().textContent}`
);

console.log("Boolean plain-language preview: ALL PASS");
