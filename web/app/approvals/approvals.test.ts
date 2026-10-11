import { test } from "node:test";
import assert from "node:assert/strict";
import {
  demoToken,
  checkDemoToken,
  approvalTitle,
  decidedLabel,
  parseArxivId,
  planDecision,
  planFeedback,
  planProject,
  planWhatIf,
} from "./approvals.ts";

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

// --- new research and what-if ----------------------------------------------------------------------

test("parseArxivId accepts bare ids, prefixes and arxiv.org URLs", () => {
  assert.equal(parseArxivId("1503.02531"), "1503.02531");
  assert.equal(parseArxivId(" arXiv:1503.02531v2 "), "1503.02531v2");
  assert.equal(parseArxivId("https://arxiv.org/abs/1503.02531"), "1503.02531");
  assert.equal(parseArxivId("https://arxiv.org/pdf/1503.02531v1.pdf"), "1503.02531v1");
  assert.equal(parseArxivId("hep-th/9901001"), "hep-th/9901001");
});

test("parseArxivId rejects anything else", () => {
  assert.equal(parseArxivId("not a paper"), null);
  assert.equal(parseArxivId("https://example.com/abs/1503.02531"), null);
  assert.equal(parseArxivId(""), null);
});

test("planProject builds a 'new' project row the controller's intake will plan", () => {
  const p = planProject({ arxiv_id: "arXiv:1503.02531" });
  assert.ok(p.ok);
  assert.deepEqual(p.row, {
    title: "arXiv 1503.02531",
    arxiv_id: "1503.02531",
    repo_url: null,
    budget_cpu_min: 20,
    status: "new",
  });
});

test("planProject keeps an https repo URL and a budget in range, and refuses others", () => {
  const ok = planProject({ arxiv_id: "1503.02531", repo_url: "https://github.com/a/b", budget_cpu_min: 30 });
  assert.ok(ok.ok);
  assert.equal(ok.row.repo_url, "https://github.com/a/b");
  assert.equal(ok.row.budget_cpu_min, 30);
  assert.equal(planProject({ arxiv_id: "1503.02531", repo_url: "http://github.com/a/b" }).ok, false);
  assert.equal(planProject({ arxiv_id: "1503.02531", budget_cpu_min: 0 }).ok, false);
  assert.equal(planProject({ arxiv_id: "1503.02531", budget_cpu_min: 2.5 }).ok, false);
  assert.equal(planProject({ arxiv_id: "nope" }).ok, false);
});

test("planWhatIf queues a design_whatif task with controller caps until the controller prepares it", () => {
  const p = planWhatIf("p1", { question: "  What if T = 5?  " });
  assert.ok(p.ok);
  assert.deepEqual(p.task, {
    project_id: "p1",
    capability: "design_whatif",
    required_caps: ["controller"],
    status: "queued",
    input: { question: "What if T = 5?" },
  });
});

test("planWhatIf refuses an empty or over-long question", () => {
  assert.equal(planWhatIf("p1", { question: "  " }).ok, false);
  assert.equal(planWhatIf("p1", { question: "x".repeat(501) }).ok, false);
  assert.equal(planWhatIf("p1", {}).ok, false);
});

test("approvalTitle names an extend run plainly; other tasks use their title or capability", () => {
  assert.equal(
    approvalTitle({ capability: "run", input: { title: "what-if b2: temperature=2 (full)", extend_of: "r1" } }),
    "Extend the temperature = 2 branch to a full run",
  );
  assert.equal(
    approvalTitle({ capability: "run", input: { title: 'what-if b3: lr=0.01 (full)', extend_of: "r1" } }),
    "Extend the lr = 0.01 branch to a full run",
  );
  assert.equal(approvalTitle({ capability: "run", input: { title: "Run the full reproduction" } }), "Run the full reproduction");
  assert.equal(approvalTitle({ capability: "write_code", input: {} }), "Write code");
});

test("decidedLabel says what happened after a decision, following the task's status", () => {
  assert.equal(decidedLabel("approve", "queued"), "Approved · running");
  assert.equal(decidedLabel("approve", "running"), "Approved · running");
  assert.equal(decidedLabel("approve", "done"), "Approved · finished");
  assert.equal(decidedLabel("approve", "failed"), "Approved · the run failed");
  assert.equal(decidedLabel("reject", "rejected"), "Rejected");
  assert.equal(decidedLabel("redirect", "rejected"), "Redirected with your note");
});
