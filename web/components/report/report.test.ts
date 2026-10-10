import { test } from "node:test";
import assert from "node:assert/strict";
import { buildReport, parseClaims, readVerdicts, verdictLabel } from "./report.ts";

const claim = (id: string, value: unknown, extra: Record<string, unknown> = {}) => ({
  id,
  value,
  quote: `quote ${id}`,
  page: 4,
  table_or_section: "3 Preliminary experiments on MNIST",
  metric: "test errors",
  unit: "errors",
  direction: "lower_is_better",
  whose: "method",
  model: `model ${id}`,
  valid: true,
  ...extra,
});

test("parseClaims keeps cards with an id and a numeric value, and tolerates junk", () => {
  const out = parseClaims([claim("c1", 67), claim("c2", "x"), { value: 3 }, null, claim("c3", 74, { valid: false })]);
  assert.deepEqual(out.map((c) => [c.id, c.value, c.valid]), [
    ["c1", 67, true],
    ["c3", 74, false],
  ]);
  assert.deepEqual(parseClaims(null), []);
  assert.deepEqual(parseClaims({ c1: 1 }), []);
});

test("readVerdicts accepts a list of cards or an object keyed by claim id", () => {
  const fromList = readVerdicts([
    { claim_id: "c7", verdict: "Partially reproduced", note: "(1 seed)" },
    { claim: "c8", verdict: "not_runnable" },
    { verdict: "reproduced" },
  ]);
  assert.deepEqual(fromList.get("c7"), { verdict: "partially_reproduced", note: "(1 seed)" });
  assert.deepEqual(fromList.get("c8"), { verdict: "not_runnable", note: null });
  assert.equal(fromList.size, 2);

  const fromObject = readVerdicts({ c7: "reproduced", c8: { verdict: "Not reproduced", reason: "gap 40 > margin 10" } });
  assert.deepEqual(fromObject.get("c7"), { verdict: "reproduced", note: null });
  assert.deepEqual(fromObject.get("c8"), { verdict: "not_reproduced", note: "gap 40 > margin 10" });
  assert.equal(readVerdicts(null).size, 0);
});

test("verdictLabel names the four SPEC verdicts and passes unknown ones through", () => {
  assert.equal(verdictLabel("reproduced").label, "Reproduced");
  assert.equal(verdictLabel("partially_reproduced").label, "Partially reproduced");
  assert.equal(verdictLabel("not_reproduced").label, "Not reproduced");
  assert.equal(verdictLabel("not_runnable").label, "Not runnable");
  assert.equal(verdictLabel("weird").label, "weird");
});

const exp = (id: string, claim_map: unknown, extra: Record<string, unknown> = {}) => ({
  id,
  label: `exp ${id}`,
  created_at: "2026-10-10T10:00:00Z",
  config: { claim_map },
  margin: 10,
  verdicts: null,
  ...extra,
});
const metric = (id: string, experiment_id: string, name: string, value: unknown, log_line: number, step = 0) => ({
  id,
  experiment_id,
  name,
  value: value as number,
  log_line,
  step,
});

test("buildReport pairs each mapped claim with our final_<model> values and their log lines", () => {
  const claims = parseClaims([claim("c7", 67), claim("c8", 146), claim("c9", 74)]);
  const { rows, untested } = buildReport(
    claims,
    [exp("e1", { teacher: "c7", student_hard: "c8" }, { verdicts: [{ claim_id: "c7", verdict: "reproduced" }] })],
    [
      metric("m1", "e1", "final_teacher", 70, 120),
      metric("m2", "e1", "teacher_test_errors", 90, 100), // a curve point, not the final value
      metric("m3", "e2", "final_teacher", 1, 5), // another experiment
    ],
  );
  assert.deepEqual(
    rows.map((r) => [r.claim.id, r.model, r.experimentId, r.ours.map((p) => [p.text, p.log_line]), r.verdict?.verdict ?? null]),
    [
      ["c7", "teacher", "e1", [["70", 120]], "reproduced"],
      ["c8", "student_hard", "e1", [], null],
    ],
  );
  assert.equal(rows[0].margin, 10);
  assert.deepEqual(untested.map((c) => c.id), ["c9"]);
});

test("buildReport keeps every seed's value in log order and shows NaN as text", () => {
  const claims = parseClaims([claim("c9", 74)]);
  const { rows } = buildReport(claims, [exp("e1", { distilled: "c9" })], [
    metric("b", "e1", "final_distilled", "NaN", 300, 1),
    metric("a", "e1", "final_distilled", 80, 200, 0),
  ]);
  assert.deepEqual(rows[0].ours.map((p) => [p.text, p.value, p.log_line]), [
    ["80", 80, 200],
    ["NaN", null, 300],
  ]);
});

test("buildReport ignores experiments without a claim map and map entries for unknown claims", () => {
  const claims = parseClaims([claim("c7", 67)]);
  const { rows, untested } = buildReport(
    claims,
    [exp("smoke", undefined), exp("e1", { teacher: "c404" }), exp("e2", "not a map")],
    [],
  );
  assert.equal(rows.length, 0);
  assert.deepEqual(untested.map((c) => c.id), ["c7"]);
});
