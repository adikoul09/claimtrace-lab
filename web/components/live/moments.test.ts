import { test } from "node:test";
import assert from "node:assert/strict";
import { isKeyMoment, keyMomentsByDefault, momentLabel } from "./moments.ts";

const ev = (type: string, message = "m") => ({ type, message });

test("key moments: agent spawned, refined, retired, lesson applied, budget hold, approval needed", () => {
  for (const t of ["agent_spawned", "agent_refined", "agent_retired", "lesson_applied", "llm_daily_cap", "budget_hold"])
    assert.equal(isKeyMoment(ev(t)), true, t);
  assert.equal(isKeyMoment(ev("task_assigned", "write code → implementer-v1 (awaits approval)")), true);
});

test("everything else is not a key moment", () => {
  for (const t of ["task_started", "task_assigned", "reward", "lesson_skipped", "paper_fetched", "llm_error"])
    assert.equal(isKeyMoment(ev(t)), false, t);
});

test("moments that have no event type of their own get a plain name", () => {
  assert.equal(momentLabel(ev("task_assigned", "run → runner-v1 (awaits approval)")), "Approval needed");
  assert.equal(momentLabel(ev("llm_daily_cap")), "Budget hold");
  assert.equal(momentLabel(ev("budget_hold")), "Budget hold");
  assert.equal(momentLabel(ev("agent_spawned")), null);
});

test("the filter starts on only for projects with more than 30 events", () => {
  assert.equal(keyMomentsByDefault(30), false);
  assert.equal(keyMomentsByDefault(31), true);
});

test("what-if moments count, with plain labels", () => {
  const cases: [string, string, string][] = [
    ["whatif_designed", "what-if: 3 one-change branches: …", "Branches proposed"],
    ["branch_pruned", "what-if b1 (temperature=2) pruned", "Branch pruned"],
    ["whatif_ranked", "ranked", "Branches ranked"],
    ["whatif_finished", "what-if finished: …", "What-if finished"],
    ["decision", "approved run", "Decision"],
  ];
  for (const [type, message, label] of cases) {
    assert.equal(isKeyMoment({ type, message }), true, type);
    if (type !== "decision") assert.equal(momentLabel({ type, message }), label, type);
  }
});

test("a decision event is labelled by what the researcher chose", () => {
  assert.equal(momentLabel({ type: "decision", message: "m", data: { decision: "approve" } }), "Approved");
  assert.equal(momentLabel({ type: "decision", message: "m", data: { decision: "reject" } }), "Rejected");
  assert.equal(momentLabel({ type: "decision", message: "m", data: { decision: "redirect" } }), "Redirected");
});
