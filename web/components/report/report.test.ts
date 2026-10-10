import { test } from "node:test";
import assert from "node:assert/strict";
import { buildReport, diffText, parseClaims, readVerdicts, runStats, verdictLabel, type ExpRow } from "./report.ts";
import { reportMarkdown, TEXT } from "./markdown.ts";

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

// Shaped like the Analyst's object on experiment 3ce597c1 (lab/agents/analyst.py).
const ANALYST = {
  rules: "SPEC §7.5 v1",
  seeds: 1,
  margin: 10,
  claims: [
    {
      claim_id: "c7",
      model: "teacher_test_errors",
      metric_name: "final_teacher_test_errors",
      paper: 67,
      ours: 80,
      delta: 13,
      log_line: 186,
      verdict: "Partially reproduced",
      label: "Partially reproduced (1 seed)",
      why: "|13| > margin 10; holds: c7 better than c8",
    },
    {
      claim_id: "c8",
      model: "student_hard_test_errors",
      metric_name: "final_student_hard_test_errors",
      paper: 146,
      ours: 143,
      delta: -3,
      log_line: 280,
      verdict: "Reproduced",
      label: "Reproduced (1 seed)",
      why: "|-3| <= margin 10",
    },
  ],
  relative: [
    { claim: "c7 beats c8", method: "c7", baseline: "c8", paper_gap: 79, ours_gap: 63, verdict: "Partially reproduced", label: "Partially reproduced (gap smaller than reported) (1 seed)" },
  ],
  relations: [],
  explanation: { text: null, accepted: false, problems: ["not requested"] },
  margin_note: "margin not set on the experiment; graded with the floor",
};

test("parseClaims keeps cards with an id and a numeric value, and tolerates junk", () => {
  const out = parseClaims([claim("c1", 67), claim("c2", "x"), { value: 3 }, null, claim("c3", 74, { valid: false })]);
  assert.deepEqual(out.map((c) => [c.id, c.value, c.valid]), [
    ["c1", 67, true],
    ["c3", 74, false],
  ]);
  assert.deepEqual(parseClaims(null), []);
});

test("readVerdicts reads the Analyst's object: cards, relative claims, explanation, margin note", () => {
  const g = readVerdicts(ANALYST);
  assert.deepEqual([...g.cards.keys()], ["c7", "c8"]);
  const c7 = g.cards.get("c7")!;
  assert.equal(c7.verdict, "partially_reproduced");
  assert.equal(c7.label, "Partially reproduced (1 seed)");
  assert.deepEqual([c7.ours, c7.delta, c7.log_line, c7.metric_name], [80, 13, 186, "final_teacher_test_errors"]);
  assert.equal(g.relative[0].verdict, "partially_reproduced");
  assert.deepEqual(g.explanation, { text: null, accepted: false, problems: ["not requested"] });
  assert.equal(g.marginNote, "margin not set on the experiment; graded with the floor");
  assert.equal(g.seeds, 1);
  assert.ok(!g.cards.has("rules"), "top-level keys are not claims");
});

test("readVerdicts still reads a bare list and the old {claim_id: verdict} dict", () => {
  assert.equal(readVerdicts([{ claim_id: "c7", verdict: "Not runnable" }]).cards.get("c7")?.verdict, "not_runnable");
  const old = readVerdicts({ c7: "reproduced", c8: { verdict: "Not reproduced", reason: "gap 40 > margin 10" } });
  assert.equal(old.cards.get("c7")?.label, "Reproduced");
  assert.equal(old.cards.get("c8")?.why, "gap 40 > margin 10");
  assert.equal(readVerdicts(null).cards.size, 0);
});

test("readVerdicts normalises settings-diff labels", () => {
  const g = readVerdicts({
    claims: [],
    settings_diff: [
      { key: "epochs", paper: null, ours: 30, label: "scale reduction (budget)" },
      { key: "temperature", paper: "20", ours: "20", label: "same", quote: "T = 20", page: 3, config_key: "T" },
      { key: "lr", paper: null, ours: 0.1, label: "paper omission" },
      { key: "jitter", paper: "2 px", ours: "0", label: "Difference" },
      { nokey: true },
    ],
  });
  assert.deepEqual(g.settingsDiff.map((r) => [r.key, r.label, r.paper, r.ours]), [
    ["epochs", "scale", null, "30"],
    ["temperature", "same", "20", "20"],
    ["lr", "omission", null, "0.1"],
    ["jitter", "difference", "2 px", "0"],
  ]);
});

test("verdictLabel names the four SPEC verdicts and passes unknown ones through", () => {
  assert.equal(verdictLabel("partially_reproduced").label, "Partially reproduced");
  assert.equal(verdictLabel("weird").label, "weird");
});

const exp = (id: string, extra: Partial<ExpRow> = {}): ExpRow => ({
  id,
  label: `exp ${id}`,
  created_at: "2026-10-10T10:00:00Z",
  config: {},
  margin: 10,
  verdicts: null,
  parent_id: null,
  changed_key: null,
  status: "done",
  pruned_reason: null,
  ...extra,
});
const metric = (experiment_id: string, name: string, value: unknown, log_line: number, step = 0) => ({
  experiment_id,
  name,
  value: value as number,
  log_line,
  step,
});

test("buildReport takes graded rows from the verdict cards, with each value's log line", () => {
  const claims = parseClaims([claim("c7", 67), claim("c8", 146), claim("c9", 74)]);
  const d = buildReport({
    claims,
    experiments: [exp("v2", { verdicts: ANALYST })],
    metrics: [metric("v2", "final_teacher_test_errors", 80, 186)],
  });
  assert.deepEqual(
    d.rows.map((r) => [r.claim.id, r.metricName, r.ours.map((p) => [p.text, p.log_line]), r.delta, r.verdict?.label]),
    [
      ["c7", "final_teacher_test_errors", [["80", 186]], 13, "Partially reproduced (1 seed)"],
      ["c8", "final_student_hard_test_errors", [["143", 280]], -3, "Reproduced (1 seed)"],
    ],
  );
  assert.deepEqual(d.untested.map((c) => c.id), ["c9"]);
  assert.deepEqual(d.graded[0].relative[0].lines, [
    { exp: "v2", line: 186 },
    { exp: "v2", line: 280 },
  ]);
});

test("buildReport shows claim_map rows of an ungraded run with every seed's logged value", () => {
  const claims = parseClaims([claim("c9", 74)]);
  const d = buildReport({
    claims,
    experiments: [exp("e1", { config: { claim_map: { distilled: "c9", ghost: "c404" } } })],
    metrics: [metric("e1", "final_distilled", "NaN", 300, 1), metric("e1", "final_distilled", 80, 200, 0)],
  });
  assert.equal(d.rows.length, 1);
  assert.equal(d.rows[0].verdict, null);
  assert.deepEqual(d.rows[0].ours.map((p) => [p.text, p.value, p.log_line]), [
    ["80", 80, 200],
    ["NaN", null, 300],
  ]);
  assert.equal(d.graded.length, 0);
});

test("buildReport computes branch effects as branch minus parent on final values both logged", () => {
  const d = buildReport({
    claims: [],
    experiments: [
      exp("p"),
      exp("b", { parent_id: "p", changed_key: "temperature", created_at: "2026-10-10T11:00:00Z", status: "pruned", pruned_reason: "effect inside noise" }),
      exp("x", { parent_id: "p", changed_key: null }), // not a what-if branch
    ],
    metrics: [
      metric("p", "final_distilled", 96, 374),
      metric("p", "final_distilled_wall_s", 124.2, 375),
      metric("b", "final_distilled", 90, 50),
    ],
  });
  assert.deepEqual(
    d.branches.map((b) => [b.key, b.metric, b.parent?.log_line, b.branch?.log_line, b.effect, b.prunedReason]),
    [["temperature", "final_distilled", 374, 50, "-6", "effect inside noise"]],
  );
});

test("diffText keeps the logged precision and signs increases", () => {
  const p = (text: string) => ({ step: 0, value: Number(text), text, log_line: 1 });
  assert.equal(diffText(p("0.1"), p("0.35")), "+0.25");
  assert.equal(diffText(p("80"), p("80")), "0");
  assert.equal(diffText(p("96"), { step: 0, value: null, text: "NaN", log_line: 2 }), null);
});

test("runStats counts failures before the first successful run, time to it, tokens and lessons", () => {
  const project = { id: "p", title: "run 2", arxiv_id: "1503.02531", created_at: "2026-10-10T10:00:00Z", status: "new" };
  const t = (id: string, status: string, finished_at: string | null, capability = "run") => ({
    id,
    capability,
    status,
    created_at: "2026-10-10T10:00:00Z",
    finished_at,
  });
  const s = runStats(
    project,
    [
      t("a", "failed", "2026-10-10T10:01:00Z"),
      t("b", "done", "2026-10-10T10:05:00Z"),
      t("c", "failed", "2026-10-10T10:09:00Z"),
      t("d", "done", "2026-10-10T10:00:30Z", "write_code"),
    ],
    [
      { task_id: "d", tokens_in: 1000, tokens_out: 200 },
      { task_id: "zzz", tokens_in: 5, tokens_out: 5 },
    ],
    [{ id: "e", type: "lesson_applied", message: "pin torchvision", ts: "2026-10-10T10:00:10Z" }],
  );
  assert.deepEqual(
    [s.failedBeforeFirstSuccess, s.failedRuns, s.secondsToFirstResult, s.llmTokens, s.llmCalls, s.lessonsApplied.length],
    [1, 2, 300, 1200, 1, 1],
  );
  const none = runStats(project, [t("a", "failed", "2026-10-10T10:01:00Z")], [], []);
  assert.equal(none.failedBeforeFirstSuccess, null);
});

test("reportMarkdown links each of our numbers to its log line and uses the screen's wording", () => {
  const claims = parseClaims([claim("c7", 67), claim("c8", 146), claim("c9", 74)]);
  const d = buildReport({ claims, experiments: [exp("v2", { verdicts: ANALYST })], metrics: [] });
  const md = reportMarkdown({ id: "p1", title: "Distillation", arxiv_id: "1503.02531" }, d, "https://x.test");
  assert.match(md, /^# Report: Distillation/);
  assert.ok(md.includes("[80](https://x.test/logs/v2#L186) (Δ +13) ± 10"));
  assert.ok(md.includes("[143](https://x.test/logs/v2#L280) (Δ -3) ± 10"));
  assert.ok(md.includes("Partially reproduced (1 seed): \\|13\\| > margin 10"));
  assert.ok(md.includes("(from [L186](https://x.test/logs/v2#L186), [L280](https://x.test/logs/v2#L280))"));
  assert.ok(md.includes(`${TEXT.explanationHidden}: not requested.`));
  assert.ok(md.includes(TEXT.noSettings) && md.includes(TEXT.noBranches) && md.includes(TEXT.noMemory));
  assert.ok(md.includes("- c9 model c9 · test errors: 74 errors (p. 4)"));
  // Every number in the claims table's "Ours" column is a log link.
  const ours = md.split("\n").filter((l) => l.startsWith("| c") && l.includes("(p. ")).map((l) => l.split(" | ")[2]);
  assert.equal(ours.length, 2);
  for (const o of ours) assert.match(o, /^\[\d+\]\(https:\/\/x\.test\/logs\/v2#L\d+\)/);
});

test("reportMarkdown escapes pipes so a quote cannot break the table", () => {
  const d = buildReport({
    claims: parseClaims([claim("c1", 5, { model: "a|b" })]),
    experiments: [exp("e", { config: { claim_map: { m: "c1" } } })],
    metrics: [],
  });
  const md = reportMarkdown({ id: "p", title: "t", arxiv_id: null }, d, "");
  assert.ok(md.includes("c1 a\\|b"));
});
