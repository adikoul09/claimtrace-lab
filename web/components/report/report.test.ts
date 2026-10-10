import { test } from "node:test";
import assert from "node:assert/strict";
import { buildReport, diffText, latestNotes, parseClaims, readVerdicts, runStats, splitClaimRows, verdictLabel, type ExpRow } from "./report.ts";
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

// docs/CONTRACTS.md §5: a list, one item per claim; relative claims are "<method>_vs_<baseline>" items.
const CONTRACT = [
  { claim_id: "c7", verdict: "partially reproduced", ours: 80, paper: 67, margin: 10, note: "(1 seed) c7 better than c8 still holds", log_line: 186 },
  { claim_id: "c8", verdict: "reproduced", ours: 143, paper: 146, margin: 10, note: "(1 seed)", log_line: 280 },
  { claim_id: "c9", verdict: "not runnable", ours: null, paper: 74, margin: 10, note: "no METRIC line", log_line: null },
  { claim_id: "c7_vs_c8", verdict: "partially reproduced", ours: 63, paper: 79, margin: 10, note: "(1 seed) gap smaller than reported" },
];

test("readVerdicts reads the CONTRACTS.md list: seed note joins the label, relative items split out", () => {
  const g = readVerdicts(CONTRACT);
  assert.deepEqual([...g.cards.keys()], ["c7", "c8", "c9"]);
  const c7 = g.cards.get("c7")!;
  assert.deepEqual([c7.verdict, c7.label, c7.why, c7.ours, c7.log_line, c7.margin], [
    "partially_reproduced",
    "Partially reproduced (1 seed)",
    "c7 better than c8 still holds",
    80,
    186,
    10,
  ]);
  assert.deepEqual([g.cards.get("c8")!.label, g.cards.get("c8")!.why], ["Reproduced (1 seed)", null]);
  assert.equal(g.cards.get("c9")!.ours, null);
  assert.deepEqual(g.relative.map((r) => [r.claim, r.method, r.baseline, r.paper_gap, r.ours_gap, r.label]), [
    ["c7 beats c8", "c7", "c8", 79, 63, "Partially reproduced (1 seed) gap smaller than reported"],
  ]);
});

test("buildReport uses the item's margin and takes the explanation from the graded event", () => {
  const claims = parseClaims([claim("c7", 67), claim("c8", 146), claim("c9", 74)]);
  const d = buildReport({
    claims,
    experiments: [exp("e", { margin: null, verdicts: CONTRACT })],
    metrics: [],
    graded: [
      { experiment_id: "e", ts: "2026-10-10T10:00:00Z", explanation: { text: "old", accepted: true, problems: [] } },
      { experiment_id: "e", ts: "2026-10-10T11:00:00Z", explanation: { text: "Teacher 80 vs 67.", accepted: true, problems: [] } },
      { experiment_id: "other", ts: "2026-10-10T12:00:00Z", explanation: { text: "no", accepted: true, problems: [] } },
    ],
  });
  assert.deepEqual(d.rows.map((r) => [r.claim.id, r.margin, r.ours.map((p) => p.log_line)]), [
    ["c7", 10, [186]],
    ["c8", 10, [280]],
    ["c9", 10, []],
  ]);
  assert.equal(d.graded[0].explanation?.text, "Teacher 80 vs 67.");
  assert.deepEqual(d.graded[0].relative[0].lines, [
    { exp: "e", line: 186 },
    { exp: "e", line: 280 },
  ]);
});

test("a NULL metric value (NaN or inf in the log, migration 003) shows as non-finite", () => {
  const d = buildReport({
    claims: parseClaims([claim("c9", 74)]),
    experiments: [exp("e", { config: { claim_map: { distilled: "c9" } } })],
    metrics: [metric("e", "final_distilled", null, 300)],
  });
  assert.deepEqual(d.rows[0].ours.map((p) => [p.text, p.value]), [["non-finite", null]]);
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
  assert.ok(md.includes("| Partially reproduced: ours 80 vs paper 67 (gap 13, over the margin of 10 errors). 1 seed. |"));
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

test("latestNotes picks the newest done write_notes task's markdown (CONTRACTS.md §4)", () => {
  const t = (id: string, capability: string, status: string, finished_at: string | null, output: unknown) => ({
    id,
    capability,
    status,
    finished_at,
    output,
  });
  const out = latestNotes([
    t("a", "write_notes", "done", "2026-10-10T10:00:00Z", { markdown: "# old" }),
    t("b", "write_notes", "done", "2026-10-10T12:00:00Z", { markdown: "# new" }),
    t("c", "write_notes", "failed", "2026-10-10T13:00:00Z", { markdown: "# broken" }),
    t("d", "write_report", "done", "2026-10-10T14:00:00Z", { markdown: "# report" }),
    t("e", "write_notes", "done", "2026-10-10T15:00:00Z", { answer: "no markdown field" }),
  ]);
  assert.deepEqual(out, { taskId: "b", markdown: "# new" });
  assert.equal(latestNotes([]), null);
});

const tally = (d: ReturnType<typeof buildReport>) => d.authenticity.rows.map((r) => [r.label, r.count, r.seeds]);

test("authenticity counts each graded claim once, with the seed note the verdicts carry", () => {
  const d = buildReport({ claims: [], experiments: [exp("v2", { verdicts: ANALYST })], metrics: [] });
  assert.deepEqual(tally(d), [
    ["Reproduced", 1, "1 seed"],
    ["Partially reproduced", 2, "1 seed"],
    ["Not reproduced", 0, null],
  ]);
  assert.deepEqual([d.authenticity.total, d.authenticity.claims, d.authenticity.comparisons], [3, 2, 1]);
  assert.deepEqual(d.authenticity.sources, [{ id: "v2", label: "exp v2" }]);
});

test("authenticity takes each claim's latest reproduction verdict and ignores what-if branches", () => {
  const branch = [{ claim_id: "c8", verdict: "not reproduced", ours: 300, paper: 146, margin: 10, note: "(1 seed)", log_line: 9 }];
  const d = buildReport({
    claims: [],
    experiments: [
      exp("v2", { verdicts: ANALYST, created_at: "2026-10-10T10:00:00Z" }),
      exp("v3", { verdicts: CONTRACT, created_at: "2026-10-10T11:00:00Z" }),
      exp("b1", { verdicts: branch, parent_id: "v3", changed_key: "lr", created_at: "2026-10-10T12:00:00Z" }),
      exp("w1", { verdicts: branch, config: { whatif: { task_id: "t" } }, created_at: "2026-10-10T12:00:00Z" }),
    ],
    metrics: [],
  });
  assert.deepEqual(tally(d), [
    ["Reproduced", 1, "1 seed"],
    ["Partially reproduced", 2, "1 seed"],
    ["Not reproduced", 0, null],
    ["Not runnable", 1, null],
  ]);
  assert.deepEqual(d.authenticity.sources.map((s) => s.id), ["v3"]);
});

test("authenticity says how many of a verdict are single-seed when seeds differ, and is empty before grading", () => {
  const mixed = [
    { claim_id: "c1", verdict: "reproduced", ours: 1, paper: 1, margin: 1, note: "within margin", log_line: 1 },
    { claim_id: "c2", verdict: "reproduced", ours: 1, paper: 1, margin: 1, note: "(1 seed)", log_line: 2 },
  ];
  const d = buildReport({ claims: [], experiments: [exp("v", { verdicts: mixed })], metrics: [] });
  assert.deepEqual(tally(d)[0], ["Reproduced", 2, "1 with 1 seed"]);
  const none = buildReport({ claims: [], experiments: [exp("v")], metrics: [] });
  assert.equal(none.authenticity.total, 0);
  assert.deepEqual(tally(none).map((r) => r[1]), [0, 0, 0]);
});

test("reportMarkdown opens with the claim authenticity counts", () => {
  const d = buildReport({ claims: [], experiments: [exp("v2", { verdicts: ANALYST })], metrics: [] });
  const md = reportMarkdown({ id: "p", title: "T", arxiv_id: null }, d, "http://x");
  assert.ok(md.indexOf("## Claim authenticity") < md.indexOf("## Claims vs ours"));
  assert.match(md, /\| Partially reproduced \| 2 \(1 seed\) \|/);
  assert.match(md, /3 graded claims \(2 results, 1 comparison\)/);
});

// The real v2 grading (experiment 3ce597c1): c7 teacher, c8 hard-label student, c9 distilled student.
const V2 = {
  seeds: 1,
  claims: [
    { claim_id: "c7", ours: 80, paper: 67, delta: 13, margin: 10, unit: "errors", verdict: "Partially reproduced", label: "Partially reproduced (1 seed)", why: "|13| > margin 10; holds: c7 better than c8, c7 better than c9", log_line: 186, model: "teacher_test_errors" },
    { claim_id: "c8", ours: 143, paper: 146, delta: -3, margin: 10, unit: "errors", verdict: "Reproduced", label: "Reproduced (1 seed)", why: "|-3| <= margin 10", log_line: 280, model: "student_hard_test_errors" },
    { claim_id: "c9", ours: 96, paper: 74, delta: 22, margin: 10, unit: "errors", verdict: "Partially reproduced", label: "Partially reproduced (1 seed)", why: "|22| > margin 10; holds: c7 better than c9, c9 better than c8", log_line: 374, model: "student_distilled_test_errors" },
  ],
  relative: [{ claim: "c9 beats c8", method: "c9", baseline: "c8", paper_gap: 72, ours_gap: 47, verdict: "Partially reproduced", label: "Partially reproduced (gap smaller than reported) (1 seed)", size_note: "gap smaller than reported" }],
  relations: [
    { a: "c7", b: "c8", holds: true, relation: "c7 better than c8" },
    { a: "c7", b: "c9", holds: true, relation: "c7 better than c9" },
    { a: "c9", b: "c8", holds: true, relation: "c9 better than c8" },
  ],
};
const V2_CLAIMS = [
  claim("c7", 67, { model: "Large neural net (1200 units/layer)" }),
  claim("c8", 146, { model: "Small net (800 units/layer)" }),
  claim("c9", 74, { model: "Distilled small net (800 units/layer)" }),
];
const numbers = (s: string) => (s.match(/\d+(\.\d+)?/g) ?? []).map(Number);

test("each partially or not reproduced claim gets a why sentence from the verdict's own numbers", () => {
  const d = buildReport({ claims: parseClaims(V2_CLAIMS), experiments: [exp("v2", { verdicts: V2 })], metrics: [] });
  const why = new Map(d.rows.map((r) => [r.claim.id, r.explain]));
  assert.equal(
    why.get("c9"),
    "Partially reproduced: ours 96 vs paper 74 (gap 22, over the margin of 10 errors), but the paper's direction holds (Distilled small net 96 < Small net 143). 1 seed.",
  );
  assert.equal(
    why.get("c7"),
    "Partially reproduced: ours 80 vs paper 67 (gap 13, over the margin of 10 errors), but the paper's direction holds (Large neural net 80 < Small net 143; Large neural net 80 < Distilled small net 96). 1 seed.",
  );
  assert.equal(why.get("c8"), null, "a reproduced claim needs no why");
  assert.equal(
    d.graded[0].relative[0].explain,
    "Partially reproduced: our gap 47 vs the paper's 72 (gap smaller than reported). 1 seed.",
  );
});

test("every number in a why sentence appears in the verdict or claim data", () => {
  const broken = structuredClone(V2);
  broken.claims[2] = { ...broken.claims[2], ours: 150, delta: 76, verdict: "Not reproduced", label: "Not reproduced (1 seed)" };
  broken.relations[2] = { ...broken.relations[2], holds: false };
  for (const verdicts of [V2, broken]) {
    const d = buildReport({ claims: parseClaims(V2_CLAIMS), experiments: [exp("v2", { verdicts })], metrics: [] });
    const data = new Set(numbers(JSON.stringify(verdicts) + JSON.stringify(V2_CLAIMS)).map(Math.abs));
    const sentences = [...d.rows.map((r) => r.explain), ...d.graded.flatMap((g) => g.relative.map((r) => r.explain))];
    assert.ok(sentences.filter(Boolean).length >= 2);
    for (const s of sentences) for (const n of numbers(s ?? "")) assert.ok(data.has(n), `${n} in "${s}" is not in the data`);
  }
  const d = buildReport({ claims: parseClaims(V2_CLAIMS), experiments: [exp("v2", { verdicts: broken })], metrics: [] });
  assert.equal(
    d.rows.find((r) => r.claim.id === "c9")!.explain,
    "Not reproduced: ours 150 vs paper 74 (gap 76, over the margin of 10 errors), and the paper's direction does not hold (Distilled small net 150 > Small net 143). 1 seed.",
  );
});

test("a why sentence leaves out what the verdict does not say (contract list: no relations, no delta)", () => {
  const d = buildReport({
    claims: parseClaims(V2_CLAIMS),
    experiments: [exp("v3", { verdicts: [{ claim_id: "c9", verdict: "not reproduced", ours: 96, paper: 74, margin: 10, note: "(1 seed)", log_line: 374 }] })],
    metrics: [],
  });
  assert.equal(d.rows[0].explain, "Not reproduced: ours 96 vs paper 74. 1 seed.");
});

// docs/CONTRACTS.md §5b: experiments.config.why, as lab/agents/why.py writes it.
const WHY = {
  config_log_line: 12,
  labels: { "scale reduction (budget)": 1, same: 1 },
  settings_diff: [
    { key: "epochs", setting_id: "s4", applies_to: "all", paper: "3000 epochs", quote: "trained for 3000 epochs", page: 3,
      paper_numbers: [3000], our_key: "epochs", ours: 5, our_numbers: [5], label: "scale reduction (budget)",
      why: "the budget step chose 5 to fit the project's CPU cap", also: [], branch_effects: [] },
    { key: "architecture", setting_id: "s1", applies_to: "teacher", paper: "2 hidden layers of 1200", quote: "q", page: 4,
      paper_numbers: [2, 1200], our_key: "teacher.hidden", ours: [1200, 1200], our_numbers: [1200], label: "difference",
      why: "different numbers", also: ["student.hidden"], branch_effects: [] },
  ],
};

test("buildReport reads the settings diff from config.why (CONTRACTS §5b), with our CONFIG line", () => {
  const d = buildReport({
    claims: [],
    experiments: [exp("v2", { config: { why: WHY }, verdicts: { claims: [], settings_diff: [{ key: "old", label: "same" }] } })],
    metrics: [],
  });
  assert.equal(d.settingsDiff?.configLogLine, 12);
  assert.deepEqual(
    d.settingsDiff?.rows.map((r) => [r.key, r.label, r.paper, r.ours, r.config_key, r.reason, r.applies_to]),
    [
      ["epochs", "scale", "3000 epochs", "5", "epochs", "the budget step chose 5 to fit the project's CPU cap", null],
      ["architecture", "difference", "2 hidden layers of 1200", "[1200,1200]", "teacher.hidden", "different numbers", "teacher"],
    ],
  );
});

test("buildReport falls back to verdicts.settings_diff when config.why has no rows", () => {
  const d = buildReport({
    claims: [],
    experiments: [exp("v2", { config: { why: { settings_diff: [] } }, verdicts: { claims: [], settings_diff: [{ key: "old", label: "same" }] } })],
    metrics: [],
  });
  assert.deepEqual(d.settingsDiff?.rows.map((r) => r.key), ["old"]);
  assert.equal(d.settingsDiff?.configLogLine, null);
});

test("parseClaims reads ANY-1's runnable tag (papers.claims[i].runnable) and leaves it null when absent", () => {
  const out = parseClaims([
    claim("c1", 60.8, { runnable: { status: "not_runnable", reason: "needs GPU: 2000 hours on a cluster", facts: {} } }),
    claim("c2", 67, { runnable: { status: "runnable", reason: "MNIST is public and small" } }),
    claim("c3", 74),
    claim("c4", 1, { runnable: { status: "maybe" } }),
  ]);
  assert.deepEqual(out.map((c) => c.runnable), [
    { runnable: false, reason: "needs GPU: 2000 hours on a cluster" },
    { runnable: true, reason: "MNIST is public and small" },
    null,
    null,
  ]);
});

test("splitClaimRows keeps graded and measured rows, and moves rows with no verdict and no value to planned", () => {
  const d = buildReport({
    claims: parseClaims(V2_CLAIMS),
    experiments: [
      exp("v2", { verdicts: V2, created_at: "2026-10-10T10:00:00Z" }),
      exp("plan", { config: { claim_map: { teacher: "c7", hard: "c8" } }, created_at: "2026-10-11T10:00:00Z" }),
      exp("ran", { config: { claim_map: { distilled: "c9" } }, created_at: "2026-10-11T11:00:00Z" }),
    ],
    metrics: [metric("ran", "final_distilled", 95, 40)],
  });
  const { shown, planned } = splitClaimRows(d.rows);
  assert.deepEqual(shown.map((r) => `${r.experimentId}:${r.claim.id}`), ["v2:c7", "v2:c8", "v2:c9", "ran:c9"]);
  assert.deepEqual(planned.map((r) => `${r.experimentId}:${r.claim.id}`), ["plan:c7", "plan:c8"]);
  const md = reportMarkdown({ id: "p", title: "T", arxiv_id: null }, d, "http://x");
  assert.match(md, /### Planned, not run yet \(2\)/);
  assert.ok(md.indexOf("ran:c9") === -1 && md.indexOf("[95](http://x/logs/ran#L40)") < md.indexOf("### Planned, not run yet"));
});
