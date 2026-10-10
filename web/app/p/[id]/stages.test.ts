import { test } from "node:test";
import assert from "node:assert/strict";
import { deriveStages, plainReason, type StageInput } from "./stages.ts";

const t = (capability: string, status: string, extra: Partial<StageInput["tasks"][number]> = {}) => ({
  id: `${capability}-${status}-${Math.random()}`,
  capability,
  status,
  created_at: "2026-10-11T00:00:00Z",
  scale: null,
  whatif: null,
  error: null,
  ...extra,
});
const empty: StageInput = { projectStatus: "running", tasks: [], failures: [], claims: 0, sortedClaims: 0, experiments: [] };
const states = (i: StageInput) => deriveStages(i).map((s) => `${s.label}:${s.state}`);

test("a new project has eight stages, none started", () => {
  assert.deepEqual(states(empty), [
    "Reading paper:not started",
    "Sorting claims:not started",
    "Designing:not started",
    "Writing code:not started",
    "Smoke test:not started",
    "Training:not started",
    "Grading:not started",
    "Report:not started",
  ]);
});

test("a stage is done if any of its tasks finished, running if one is queued or running, else failed", () => {
  const s = deriveStages({
    ...empty,
    tasks: [
      t("read_paper", "failed"),
      t("read_paper", "done"),
      t("design_experiment", "failed"),
      t("design_experiment", "running"),
      t("run", "failed", { scale: "smoke" }),
    ],
    claims: 15,
  });
  assert.deepEqual(s.slice(0, 5).map((x) => x.state), ["done", "not started", "running", "not started", "failed"]);
  assert.equal(deriveStages({ ...empty, tasks: [t("write_code", "failed")] })[3].state, "failed");
});

test("what-if tasks do not move the main stages; runs split into smoke and training by scale", () => {
  const s = deriveStages({
    ...empty,
    tasks: [
      t("run", "done", { scale: "smoke" }),
      t("run", "failed", { scale: "full" }),
      t("compare", "running", { whatif: "w1" }),
    ],
  });
  assert.deepEqual([s[4].state, s[5].state, s[6].state], ["done", "failed", "not started"]);
});

test("the reference project is all done: stored results count, and a finished later stage implies the earlier ones", () => {
  const s = deriveStages({
    projectStatus: "reference",
    tasks: [t("run", "done"), t("design_experiment", "done"), t("write_code", "failed", { error: "429 RESOURCE_EXHAUSTED" })],
    failures: [],
    claims: 15,
    sortedClaims: 0,
    experiments: [{ status: "done", scale: null, graded: true, branch: false }],
  });
  assert.deepEqual(s.map((x) => x.state), Array(8).fill("done"));
  assert.match(s[3].note ?? "", /later stage/);
});

test("a failed stage carries a plain reason and the raw error, from the task or its task_failed event", () => {
  const task = t("read_paper", "failed", { id: "t1" });
  const s = deriveStages({
    ...empty,
    tasks: [task, t("read_paper", "failed", { id: "t0", created_at: "2026-10-10T00:00:00Z" })],
    failures: [{ task_id: "t1", reason: "LLMError: the 4000-token output cap (reasoning included) ran out before any answer" }],
  });
  assert.equal(s[0].state, "failed");
  assert.equal(s[0].reason, "The agent used up its token allowance before it could answer. Tried 2 times.");
  assert.match(s[0].detail ?? "", /4000-token output cap/);
});

test("plainReason turns common failures into plain words and keeps unknown ones short", () => {
  assert.equal(plainReason("gemini call failed: ClientError: 429 RESOURCE_EXHAUSTED. quota"), "The AI service's usage limit was reached, so the agent could not answer.");
  assert.equal(plainReason("agent stopped: max_tokens reached: 7966 of 4000 tokens used"), "The agent used up its token allowance before it could answer.");
  assert.equal(plainReason("KeyError: slice(None, 2000, None)"), "A bug in the lab's own code stopped this step.");
  assert.equal(plainReason("run timed out after 300 s"), "The step ran out of time.");
  assert.equal(plainReason("no public data: JFT is not public"), "No public data: JFT is not public.");
  assert.equal(plainReason(null), "The step failed without recording why.");
});

test("stages done without a task of their own say how they were inferred", () => {
  const s = deriveStages({
    projectStatus: "reference",
    tasks: [t("run", "done"), t("design_experiment", "done"), t("write_code", "failed")],
    failures: [],
    claims: 15,
    sortedClaims: 0,
    experiments: [{ status: "done", scale: null, graded: true, branch: false }],
  });
  assert.deepEqual(
    s.map((x) => `${x.label}:${x.inferred ?? "task"}`),
    [
      "Reading paper:results",
      "Sorting claims:later",
      "Designing:task",
      "Writing code:later",
      "Smoke test:later",
      "Training:task",
      "Grading:results",
      "Report:results",
    ],
  );
  assert.equal(deriveStages(empty)[0].inferred, null);
});

test("a stage with several steps is done only when each finished: setup failing after the code was written shows", () => {
  const code = (setup: string[]) =>
    deriveStages({ ...empty, tasks: [t("write_code", "done"), ...setup.map((s) => t("setup_env", s))] })[3];
  assert.equal(code(["failed", "failed", "running"]).state, "running");
  assert.equal(code(["failed", "failed", "failed"]).state, "failed");
  assert.equal(code(["failed", "failed", "failed"]).failedStep, "Set up environment");
  assert.equal(deriveStages({ ...empty, tasks: [t("write_code", "failed")] })[3].failedStep, null);
  assert.equal(code(["failed", "done"]).state, "done");
  assert.equal(code([]).state, "done");
});

test("Training is not done when only the budget step finished; it runs until the full run is done", () => {
  const training = (tasks: StageInput["tasks"]) => deriveStages({ ...empty, tasks })[5].state;
  assert.equal(training([t("budget", "done")]), "running");
  assert.equal(training([t("budget", "done"), t("run", "queued", { scale: "full" })]), "running");
  assert.equal(training([t("budget", "done"), t("run", "done", { scale: "full" })]), "done");
});
