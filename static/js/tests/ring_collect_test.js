/* Regression test: the RING rule type must collect its source + thickness from
 * the editor (previously _collectConfigFromEditor had no RING case, so a RING
 * rule was always saved with source="" and crashed with KeyError: '' at run
 * time). Run: node static/js/tests/ring_collect_test.js */
const fs = require("fs");
const path = require("path");
const { JSDOM } = require(path.join(process.cwd(), "node_modules/jsdom"));
const assert = require("assert");

const SCRIPT = path.join(__dirname, "..", "rule_based_pipeline_builder.js");
const script = fs.readFileSync(SCRIPT, "utf8");

const dom = new JSDOM(
  `<!DOCTYPE html><html><body>
    <div id="pipelineBuilder" data-roi-name-max-length="54"></div>
    <div id="pipelineBuilder2" data-roi-name-max-length="54"></div>
  </body></html>`,
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

const structures = ["CTV", "PTV"].map((v) => ({ value: v, label: v, kind: "existing" }));
const ruleTypes = [
  ["MARGIN", "Margin"], ["CROP", "Crop to Boundary"], ["CLEANUP", "Cleanup / Refinement"],
  ["RING", "Ring / Shell"], ["OVERLAP", "Overlap"], ["EXPAND_SUBTRACT", "Expand & Subtract"],
  ["AVOID_MARGIN", "Avoid with Margin"],
];

const builder = new Builder("pipelineBuilder", {
  existingRules: [], availableStructures: structures, ruleTypes,
});
const $ = (sel) => window.document.querySelector(sel);

// ---- Create a RING rule; the editor should render a source select + 6 thickness fields ----
builder.addRule("RING");
assert.ok($("#rbs-ring-source"), "RING editor should render a source select");
assert.ok($("#rbs-ring-l"), "RING editor should render directional thickness inputs");

// Set a source + one directional thickness, then collect from the editor.
$("#rbs-ring-source").value = "CTV";
$("#rbs-ring-l").value = "5";
$("#rbs-rule-name").value = "RingCTV";
const rule = builder.state.rules[0];
builder._collectConfigFromEditor(rule);

assert.strictEqual(rule.config.source, "CTV", `source should be collected, got ${JSON.stringify(rule.config.source)}`);
assert.strictEqual(rule.config.thickness_l_mm, 5, `thickness_l_mm should be collected, got ${rule.config.thickness_l_mm}`);
assert.strictEqual(rule.config.thickness_r_mm, 0, "unset direction should default to 0");

// ---- Client-side _requiredInputError / validate() must flag a source-less RING ----
const missing = builder._requiredInputError({ rule_type: "RING", config: { source: "" } });
assert.ok(/needs a source structure/.test(missing), `expected a missing-source error, got: ${JSON.stringify(missing)}`);
const ok = builder._requiredInputError({ rule_type: "RING", config: { source: "CTV" } });
assert.strictEqual(ok, null, "a sourced RING rule should have no required-input error");

// ...and validate() must surface it for a rule in state.
builder.state.rules.push({ rule_type: "RING", name: "NoSrcRing", config: { source: "" } });
const errs = builder.validate();
assert.ok(
  errs.some((e) => /needs a source structure/i.test(e)),
  `validate() should flag a source-less RING rule, got: ${JSON.stringify(errs)}`
);

console.log("RING collect + validate regression: ALL PASS");
