import { test } from "node:test";
import assert from "node:assert/strict";
import { demoToken, checkDemoToken, planDecision, planFeedback } from "./approvals.ts";

const task = (status: string, over: Record<string, unknown> = {}) => ({
  id: "t1",
  project_id: "p1",
  agent_id: "a1",
  capability: "run",
  status,
  ...over,
});

// --- passcode cookie ---------------------------------------------------------------------------

test("the demo token checks out against the same passcode and not another", async () => {
  const token = await demoToken("open-sesame");
  assert.equal(await checkDemoToken(token, "open-sesame"), true);
  assert.equal(await checkDemoToken(token, "wrong"), false);
});

test("the token is not the passcode itself", async () => {
  assert.notEqual(await demoToken("open-sesame"), "open-sesame");
});

test("no passcode configured means every write is refused", async () => {
  assert.equal(await checkDemoToken(await demoToken("open-sesame"), ""), false);
  assert.equal(await checkDemoToken(undefined, "open-sesame"), false);
});

// --- decision ------------------------------------------------------------------------------------

test("approve queues an awaiting task so an executor can claim it", () => {
  const p = planDecision(task("awaiting_approval"), { decision: "approve" });
  assert.ok(p.ok);
  assert.deepEqual(p.update, { status: "queued", decision: "approve", decision_note: null });
  assert.equal(p.event.type, "decision");
  assert.equal(p.event.task_id, "t1");
  assert.match(p.event.reason, /approved/i);
});

test("reject stops the task, keeping the note as the reason", () => {
  const p = planDecision(task("awaiting_approval"), { decision: "reject", note: "too costly" });
  assert.ok(p.ok);
  assert.deepEqual(p.update, { status: "rejected", decision: "reject", decision_note: "too costly" });
  assert.match(p.event.reason, /too costly/);
});

test("redirect needs a note, and stores it for the controller to replan with", () => {
  assert.equal(planDecision(task("awaiting_approval"), { decision: "redirect" }).ok, false);
  const p = planDecision(task("awaiting_approval"), { decision: "redirect", note: "  try T=10  " });
  assert.ok(p.ok);
  assert.deepEqual(p.update, { status: "rejected", decision: "redirect", decision_note: "try T=10" });
});

test("a decision on a task that is not awaiting approval is a conflict", () => {
  const p = planDecision(task("running"), { decision: "approve" });
  assert.equal(p.ok, false);
  assert.equal(!p.ok && p.status, 409);
});

test("an unknown decision or an over-long note is a bad request", () => {
  const bad = planDecision(task("awaiting_approval"), { decision: "maybe" });
  assert.equal(!bad.ok && bad.status, 400);
  const long = planDecision(task("awaiting_approval"), { decision: "reject", note: "x".repeat(1001) });
  assert.equal(!long.ok && long.status, 400);
});

// --- feedback ------------------------------------------------------------------------------------

test("feedback on a finished task writes a feedback event the reward code reads (data.value)", () => {
  const p = planFeedback(task("done"), { value: "up" });
  assert.ok(p.ok);
  assert.equal(p.event.type, "feedback");
  assert.deepEqual(p.event.data, { value: "up" });
  assert.equal(p.event.agent_id, "a1");
  assert.equal(planFeedback(task("failed"), { value: "down" }).ok, true);
});

test("feedback on an unfinished task, or with an unknown value, is refused", () => {
  const running = planFeedback(task("running"), { value: "up" });
  assert.equal(!running.ok && running.status, 409);
  const bad = planFeedback(task("done"), { value: "meh" });
  assert.equal(!bad.ok && bad.status, 400);
});
