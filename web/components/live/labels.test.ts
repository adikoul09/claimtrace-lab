import { test } from "node:test";
import assert from "node:assert/strict";
import {
  agentLabel,
  budgetLabel,
  eventTypeLabel,
  capabilityLabel,
  groupProjects,
  humanize,
  projectStatusLabel,
  projectTitle,
  statusLabel,
} from "./labels.ts";

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

test("home list: the reference run first, then live and precomputed; test and failed ones under Other runs", () => {
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
    ["ref", "r", "pre", "d"],
  );
  assert.deepEqual(
    other.map((x) => x.id),
    ["t", "f", "b", "s"],
  );
});

test("project statuses read as plain words", () => {
  assert.equal(projectStatusLabel("blocked"), "Stopped: needs attention");
  assert.equal(projectStatusLabel("plan_failed"), "Stopped: the plan failed");
  assert.equal(projectStatusLabel("stopped"), "Stopped by a researcher");
  assert.equal(projectStatusLabel("running"), "Running");
  assert.equal(projectStatusLabel("done"), "Finished");
  assert.equal(projectStatusLabel("new"), "Starting");
  assert.equal(projectStatusLabel("something_else"), "Something else");
});

test("projectTitle shows the paper's title instead of an arXiv id, but keeps test runs' own names", () => {
  const titles = { byProject: { p1: "Distilling the Knowledge in a Neural Network" }, byArxiv: { "1503.02531": "Distilling the Knowledge in a Neural Network" } };
  assert.equal(
    projectTitle({ id: "p1", title: "arXiv 1503.02531", arxiv_id: "1503.02531", status: "blocked" }, titles),
    "Distilling the Knowledge in a Neural Network",
  );
  assert.equal(
    projectTitle({ id: "ref", title: "Distillation (arXiv 1503.02531): full reference run", arxiv_id: "1503.02531", status: "reference" }, titles),
    "Distilling the Knowledge in a Neural Network",
  );
  assert.equal(
    projectTitle({ id: "t", title: "T07 controller test (Distillation)", arxiv_id: "1503.02531", status: "test" }, titles),
    "T07 controller test (Distillation)",
  );
  assert.equal(
    projectTitle({ id: "n", title: "arXiv 2401.00001", arxiv_id: "2401.00001", status: "new" }, titles),
    "arXiv 2401.00001",
  );
});

test("agents read as role and version, not the raw name", () => {
  assert.equal(agentLabel({ name: "reader-v13", version: 13 }), "Reader · version 13");
  assert.equal(agentLabel({ name: "cpu-experiment-designer-v2", version: 2 }), "CPU experiment designer · version 2");
  assert.equal(agentLabel({ name: "envbuilder-v1", version: 1 }), "Env builder · version 1");
});

test("event types read as plain words, with the usual spellings", () => {
  assert.equal(eventTypeLabel("task_requeued"), "Task re-queued");
  assert.equal(eventTypeLabel("llm_daily_cap"), "LLM daily cap");
  assert.equal(eventTypeLabel("whatif_waiting"), "What-if waiting");
  assert.equal(eventTypeLabel("claims_extracted"), "Claims extracted");
});
