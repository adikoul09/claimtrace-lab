import { test } from "node:test";
import assert from "node:assert/strict";
import { runSummary } from "./run-summary.ts";

const exp = (id: string, created_at: string, verdicts: unknown, over: Record<string, unknown> = {}) => ({
  id,
  created_at,
  parent_id: null,
  config: {},
  verdicts,
  ...over,
});

test("runSummary counts each claim once, from the latest experiment that graded it (like the Report)", () => {
  const exps = [
    exp("main", "2026-10-10T10:00:00Z", [
      { claim_id: "c3", verdict: "partially reproduced" },
      { claim_id: "c3_vs_c2", verdict: "partially reproduced" },
    ]),
    exp("base", "2026-10-10T11:00:00Z", [{ claim_id: "c2", verdict: "not reproduced" }]),
    exp("seed1", "2026-10-10T12:00:00Z", [
      { claim_id: "c3", verdict: "partially reproduced" },
      { claim_id: "c3_vs_c2", verdict: "partially reproduced" },
    ]),
  ];
  assert.equal(runSummary(exps), "Run end to end by the agents · 2 partially reproduced · 1 not reproduced");
});

test("runSummary ignores what-if branches and says so when nothing is graded", () => {
  const exps = [
    exp("main", "2026-10-10T10:00:00Z", [{ claim_id: "c3", verdict: "reproduced" }]),
    exp("branch", "2026-10-10T11:00:00Z", [{ claim_id: "c3", verdict: "not reproduced" }], { parent_id: "main" }),
    exp("wi", "2026-10-10T12:00:00Z", [{ claim_id: "c3", verdict: "not reproduced" }], { config: { whatif: {} } }),
  ];
  assert.equal(runSummary(exps), "Run end to end by the agents · 1 reproduced");
  assert.equal(runSummary([exp("smoke", "2026-10-10T10:00:00Z", null)]), "Run end to end by the agents · no claims graded yet");
});
