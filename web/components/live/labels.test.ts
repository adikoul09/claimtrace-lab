import { test } from "node:test";
import assert from "node:assert/strict";
import { budgetLabel, capabilityLabel, groupProjects, humanize, statusLabel } from "./labels.ts";

test("capabilities read as plain words; unknown ones are humanized", () => {
  assert.equal(capabilityLabel("design_whatif"), "Design what-if");
  assert.equal(capabilityLabel("setup_env"), "Set up environment");
  assert.equal(capabilityLabel("explain_diff"), "Explain the difference");
  assert.equal(capabilityLabel("some_new_cap"), "Some new cap");
});

test("statuses and codes read as plain words", () => {
  assert.equal(statusLabel("awaiting_approval"), "Awaiting approval");
  assert.equal(statusLabel("plan_failed"), "Plan failed");
  assert.equal(statusLabel("done"), "Done");
  assert.equal(humanize("claims_extracted"), "Claims extracted");
  assert.equal(humanize(""), "");
});

test("a task budget reads as CPU minutes and tokens, not raw keys", () => {
  assert.equal(budgetLabel({ max_cpu_s: 300, max_tokens: 20000 }), "up to 5 CPU-min · 20,000 tokens");
  assert.equal(budgetLabel({ max_cpu_s: 90 }), "up to 1.5 CPU-min");
  assert.equal(budgetLabel({ other: 1 }), "other 1");
  assert.equal(budgetLabel({}), null);
});

test("home list: reference, live and precomputed projects first; test and failed ones under Other runs", () => {
  const p = (id: string, status: string) => ({ id, status });
  const { main, other } = groupProjects([
    p("t", "test"),
    p("r", "running"),
    p("f", "plan_failed"),
    p("ref", "reference"),
    p("b", "blocked"),
    p("pre", "precomputed"),
    p("d", "done"),
    p("s", "stopped"),
  ]);
  assert.deepEqual(
    main.map((x) => x.id),
    ["r", "ref", "pre", "d"],
  );
  assert.deepEqual(
    other.map((x) => x.id),
    ["t", "f", "b", "s"],
  );
});
