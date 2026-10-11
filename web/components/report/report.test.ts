import { test } from "node:test";
import assert from "node:assert/strict";
import { buildReport, claimTriage, diffText, latestNotes, parseAverages, parseClaims, previousStop, readVerdicts, runStats, smokeLabel, splitClaimRows, verdictLabel, type ExpRow } from "./report.ts";
import { reportMarkdown, TEXT, triageReasons, triageSummary } from "./markdown.ts";

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
    ["Not runnable", 0, null],
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
  assert.deepEqual(tally(none).map((r) => r[1]), [0, 0, 0, 0], "four tiles, all zero before grading");
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
      ["architecture", "difference", "2 hidden layers of 1200", "[1200,1200]", "teacher.hidden", "different numbers", "teacher"],
      ["epochs", "scale", "3000 epochs", "5", "epochs", "the budget step chose 5 to fit the project's CPU cap", null],
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
  assert.match(md, /### Smoke checks and planned runs \(2\)/);
  assert.ok(md.indexOf("ran:c9") === -1 && md.indexOf("[95](http://x/logs/ran#L40)") < md.indexOf("### Smoke checks and planned runs"));
});

test("claimTriage counts runnable and not, top reasons first, and lists runnable claims first", () => {
  const tag = (status: string, reason: string) => ({ runnable: { status, reason } });
  const claims = parseClaims([
    claim("c1", 1, tag("not_runnable", "no public data: speech data is not public")),
    claim("c2", 2, tag("runnable", "MNIST is public and small")),
    claim("c3", 3, tag("not_runnable", "dataset too big: JFT has 100000000 training examples")),
    claim("c4", 4, tag("not_runnable", "no public data: JFT is not public")),
    claim("c5", 5),
    claim("c6", 6, tag("runnable", "MNIST is public and small")),
  ]);
  const t = claimTriage(claims);
  assert.deepEqual([t.total, t.runnable, t.notRunnable, t.unsorted], [6, 2, 3, 1]);
  assert.deepEqual(t.reasons, [
    { reason: "no public data", count: 2 },
    { reason: "dataset too big", count: 1 },
  ]);
  assert.deepEqual(t.ordered.map((c) => c.id), ["c2", "c6", "c1", "c4", "c3", "c5"]);
  assert.equal(triageSummary(t), "2 can be checked on a laptop · 3 can't · 1 not sorted yet");
  assert.equal(triageReasons(t), "2 no public data · 1 dataset too big");
  const none = claimTriage(parseClaims([claim("c1", 1)]));
  assert.deepEqual([triageSummary(none), triageReasons(none)], [null, null]);
});

test("the export lists all claims with the laptop summary", () => {
  const claims = parseClaims([
    claim("c1", 1, { runnable: { status: "not_runnable", reason: "no public data: x" } }),
    claim("c2", 2, { runnable: { status: "runnable", reason: "MNIST is public and small" } }),
  ]);
  const md = reportMarkdown({ id: "p", title: "T", arxiv_id: null }, buildReport({ claims, experiments: [], metrics: [] }), "http://x");
  assert.match(md, /## All claims in the paper \(2\)\n\n1 can be checked on a laptop · 1 can't\n\n1 no public data/);
  assert.ok(md.indexOf("- c2 ") < md.indexOf("- c1 "));
});

test("previousStop names where an unfinished earlier run stopped, and is null for a finished one", () => {
  const task = (capability: string, status: string) => ({ id: capability + status, capability, status, created_at: "2026-10-11T00:00:00Z", finished_at: null });
  assert.equal(previousStop("blocked", [task("plan", "done"), task("read_paper", "failed")]), "stopped at Reading paper");
  assert.equal(previousStop("blocked", [task("read_paper", "done"), task("design_experiment", "failed")]), "stopped at Designing");
  assert.equal(previousStop("running", [task("read_paper", "done"), task("write_code", "running")]), "still running, at Writing code");
  assert.equal(previousStop("done", [task("read_paper", "done")]), null);
});

test("ungraded smoke-run rows go with the planned rows, labelled as 1-epoch smoke checks", () => {
  const d = buildReport({
    claims: parseClaims(V2_CLAIMS),
    experiments: [
      exp("smoke", {
        config: { scale: "smoke", cmd: "python train.py --data-dir ../../data --epochs 1 --subset 5000 --seed 0", claim_map: { teacher: "c7" } },
        created_at: "2026-10-11T09:00:00Z",
      }),
      exp("v2", { verdicts: V2, created_at: "2026-10-11T10:00:00Z" }),
      exp("plan", { config: { claim_map: { hard: "c8" } }, created_at: "2026-10-11T11:00:00Z" }),
    ],
    metrics: [metric("smoke", "final_teacher", 1418, 12)],
  });
  const { shown, planned } = splitClaimRows(d.rows);
  assert.deepEqual(shown.map((r) => r.experimentId), ["v2", "v2", "v2"]);
  assert.deepEqual(planned.map((r) => r.experimentId), ["smoke", "plan"]);
  assert.equal(smokeLabel(planned[0]), "Smoke check (1 epoch, not graded)");
  assert.equal(smokeLabel(planned[1]), null);
  const md = reportMarkdown({ id: "p", title: "T", arxiv_id: null }, d, "http://x");
  assert.match(md, /### Smoke checks and planned runs \(2\)/);
  assert.ok(md.indexOf("[1418](http://x/logs/smoke#L12)") > md.indexOf("### Smoke checks and planned runs"));
  assert.match(md, /Smoke check \(1 epoch, not graded\)/);
});

test("the settings diff comes from the latest main reproduction, not a follow-up branch, with differences first", () => {
  const why = (ours: number) => ({
    config_log_line: 1,
    settings_diff: [
      { key: "optimizer", paper: null, ours: "adam", label: "paper omission", why: "our choice" },
      { key: "epochs", paper: "3000 epochs", ours, label: "scale reduction (budget)", why: "budget" },
      { key: "temperature", paper: "20", ours: 20, label: "same", why: "same" },
      { key: "hidden_units", paper: "1200 units", ours: 256, label: "difference", why: "different numbers" },
    ],
  });
  const d = buildReport({
    claims: [],
    experiments: [
      exp("main", { config: { why: why(7) }, created_at: "2026-10-11T10:00:00Z" }),
      exp("follow", { parent_id: "main", config: { why: why(15) }, created_at: "2026-10-11T11:00:00Z" }),
    ],
    metrics: [],
  });
  assert.equal(d.settingsDiff?.experimentId, "main");
  assert.deepEqual(d.settingsDiff?.rows.map((r) => r.key), ["hidden_units", "epochs", "temperature", "optimizer"]);
  assert.equal(d.settingsDiff?.rows[1].ours, "7");
});

// Fixture for B1's averaged regrade (field names to be confirmed by B; AVG_FIELDS maps them).
const AVERAGED = [
  { claim_id: "c1", verdict: "partially reproduced", mean: 81.3, spread: 2.1, seeds: 3, paper: 67, margin: 10, delta: 14.3, unit: "errors" },
  { claim_id: "c3", verdict: "reproduced", mean: 79.7, spread: 3.4, seeds: 3, paper: 74, margin: 10, delta: 5.7, unit: "errors" },
  { claim_id: "c3_vs_c2", verdict: "reproduced", mean: 18.3, spread: 4, seeds: 3, paper: 72, margin: 10, note: "distilled beats hard-target in all 3 seeds" },
];
const AVG_CLAIMS = [
  claim("c1", 67, { model: "Large neural net (1200 units/layer)" }),
  claim("c2", 146, { model: "Small net (800 units/layer)" }),
  claim("c3", 74, { model: "Distilled small net (800 units/layer)" }),
];

test("parseAverages reads mean ± spread over seeds and builds a plain why sentence from those numbers", () => {
  const a = parseAverages(AVERAGED, parseClaims(AVG_CLAIMS));
  assert.deepEqual(a.map((x) => [x.id, x.verdict, x.relative]), [
    ["c1", "partially_reproduced", false],
    ["c3", "reproduced", false],
    ["c3_vs_c2", "reproduced", true],
  ]);
  assert.equal(a[0].title, "Large neural net · test errors");
  assert.equal(
    a[0].why,
    "Partially reproduced: ours 81.3 ± 2.1 vs paper 67 over 3 seeds (gap 14.3, over the margin of 10 errors).",
  );
  assert.equal(a[1].why, "Reproduced: ours 79.7 ± 3.4 vs paper 74 over 3 seeds (gap 5.7, within the margin of 10 errors).");
  assert.equal(a[2].title, "Distilled small net beats Small net");
  assert.equal(a[2].why, "Reproduced: our gap 18.3 ± 4 vs the paper's 72 over 3 seeds (distilled beats hard-target in all 3 seeds).");
  assert.deepEqual(parseAverages(null, []), []);
});

test("averaged verdicts drive the headline counts, and the per-seed rows fold under Individual runs", () => {
  const d = buildReport({
    claims: parseClaims(AVG_CLAIMS),
    experiments: [exp("v2", { verdicts: [{ claim_id: "c1", verdict: "not reproduced", ours: 216, paper: 67, margin: 10, note: "(1 seed)", log_line: 4 }] })],
    metrics: [],
    averages: AVERAGED,
  });
  assert.deepEqual(d.authenticity.rows.slice(0, 3).map((r) => [r.label, r.count, r.seeds]), [
    ["Reproduced", 2, null],
    ["Partially reproduced", 1, null],
    ["Not reproduced", 0, null],
  ]);
  assert.equal(d.averages.length, 3);
  const md = reportMarkdown({ id: "p", title: "T", arxiv_id: null }, d, "http://x");
  assert.ok(md.indexOf("### Across 3 seeds") > md.indexOf("## Claim authenticity"));
  assert.ok(md.indexOf("### Across 3 seeds") < md.indexOf("## Claims vs ours"));
  assert.match(md, /### Individual runs \(1\)/);
});

test("the settings diff keeps only like-for-like rows the design links to (hide what code cannot compare)", () => {
  const rows = [
    { key: "architecture", setting_id: "s1", applies_to: "teacher", paper: "two hidden layers", ours: 256, our_key: "hidden_units.teacher", label: "difference" },
    { key: "hidden_units", setting_id: "s2", applies_to: "teacher", paper: "1200 units", ours: 256, our_key: "hidden_units.teacher", label: "difference" },
    { key: "data_subset", setting_id: "s8", applies_to: "teacher", paper: "all 60,000", ours: 0, our_key: "data_subset", label: "scale reduction (budget)" },
    { key: "regularisation", setting_id: "s31", applies_to: "student", paper: "matching soft targets", ours: 0, our_key: "dropout", label: "difference" },
    { key: "regularisation", setting_id: "s9", applies_to: "teacher", paper: "dropout", ours: 0.2, our_key: "dropout", label: "difference" },
    { key: "temperature", setting_id: "s35", applies_to: "student", paper: "20", ours: 20, our_key: "temperature", label: "same" },
    { key: "epochs", setting_id: null, applies_to: "teacher", paper: null, ours: 7, our_key: "epochs.teacher", label: "paper omission" },
    { key: "lr", setting_id: null, applies_to: "speech baseline", paper: null, ours: 0.001, our_key: "lr", label: "paper omission" },
    { key: "optimizer", setting_id: null, applies_to: "teacher", paper: null, ours: "adam", our_key: "optimizer", label: "paper omission" },
  ];
  const d = buildReport({
    claims: [],
    experiments: [exp("main", { config: { why: { settings_diff: rows }, design: { setting_ids: ["s1", "s2", "s8", "s9", "s31", "s35"] } } })],
    metrics: [],
  });
  assert.deepEqual(d.settingsDiff?.rows.map((r) => `${r.key}/${r.applies_to}`), [
    "hidden_units/teacher",
    "regularisation/teacher",
    "temperature/student",
    "epochs/teacher",
  ]);
});

// Graded runs of the same command with different seeds (42fb4944's shape).
const run = (id: string, cmd: string, items: [string, number][]) =>
  exp(id, {
    config: { cmd },
    verdicts: items.map(([c, ours]) => ({ claim_id: c, verdict: "partially reproduced", ours, paper: 70, margin: 10, note: "(1 seed)", log_line: 1 })),
  });
const E15 = "python train.py --epochs 15 --subset 0 --seed";
const SEED_CLAIMS = [
  claim("c9", 58.9, { model: "speech baseline", whose: "baseline" }), // another baseline in the paper, not run here
  claim("c1", 67, { model: "large neural net", whose: "method" }),
  claim("c2", 146, { model: "smaller net without regularization", whose: "baseline" }),
  claim("c3", 74, { model: "distilled smaller net", whose: "method" }),
];

test("seed summary: mean ± SD per claim over 3+ graded runs of the same command, computed from the rows", () => {
  const d = buildReport({
    claims: parseClaims(SEED_CLAIMS),
    experiments: [
      run("a0", `${E15} 0`, [["c1", 201], ["c3", 225]]),
      run("a1", `${E15} 1`, [["c1", 207], ["c3", 230]]),
      run("a2", `${E15} 2`, [["c1", 207], ["c3", 233]]),
      run("h0", `${E15} 0 --set hidden_units.teacher=128`, [["c2", 210]]),
      run("h1", `${E15} 1 --set hidden_units.teacher=128`, [["c2", 225]]),
      run("h2", `${E15} 2 --set hidden_units.teacher=128`, [["c2", 270]]),
      run("x0", "python train.py --epochs 7 --seed 0", [["c1", 216]]),
      run("x1", "python train.py --epochs 7 --seed 1", [["c1", 220]]),
    ],
    metrics: [],
  });
  const s = d.seedSummary!;
  assert.deepEqual(
    s.groups.map((g) => [g.label, g.claimId, g.n, g.mean.toFixed(1), g.sd.toFixed(1)]),
    [
      ["15 epochs", "c1", 3, "205.0", "3.5"],
      ["15 epochs", "c3", 3, "229.3", "4.0"],
      ["15 epochs, hidden_units.teacher=128", "c2", 3, "235.0", "31.2"],
    ],
  );
  assert.equal(s.note, "The difference between distilled smaller net and smaller net without regularization (5.7) is smaller than the smaller net without regularization seed spread (SD 31.2).");
});

test("seed summary is hidden when fewer than 3 seeds, and the note only appears when the numbers support it", () => {
  const two = buildReport({
    claims: parseClaims(SEED_CLAIMS),
    experiments: [run("a0", `${E15} 0`, [["c1", 1]]), run("a1", `${E15} 1`, [["c1", 2]])],
    metrics: [],
  });
  assert.equal(two.seedSummary, null);
  const tight = buildReport({
    claims: parseClaims(SEED_CLAIMS),
    experiments: [
      ...[0, 1, 2].map((i) => run(`d${i}`, `${E15} ${i}`, [["c3", 100 + i]])),
      ...[0, 1, 2].map((i) => run(`h${i}`, `${E15} ${i} --set hidden_units.teacher=128`, [["c2", 200 + i]])),
    ],
    metrics: [],
  });
  assert.equal(tight.seedSummary?.groups.length, 2);
  assert.equal(tight.seedSummary?.note, null, "a 100-error gap is not smaller than a 1-error spread");
});

test("a smoke what-if branch is compared with the parent's smoke run, never with the full run", () => {
  const wf = (key: string, value: number) => ({ scale: "smoke", whatif: { task_id: "w1", key, value } });
  const base = {
    claims: [],
    experiments: [
      exp("full", { config: { scale: "full" }, created_at: "2026-10-11T10:00:00Z" }),
      exp("smoke", { config: { scale: "smoke" }, created_at: "2026-10-11T09:00:00Z" }),
      exp("b1", { parent_id: "full", changed_key: "temperature", config: wf("temperature", 1), created_at: "2026-10-11T11:00:00Z" }),
    ],
    metrics: [metric("full", "final_teacher", 216, 40), metric("smoke", "final_teacher", 1418, 10), metric("b1", "final_teacher", 1300, 10)],
  };
  const d = buildReport({ ...base, whatifBaselines: { w1: "smoke" } });
  assert.deepEqual(d.branches.map((b) => [b.parentId, b.parent?.text, b.branch?.text, b.effect]), [["smoke", "1418", "1300", "-118"]]);
  const unknown = buildReport(base);
  assert.deepEqual(unknown.branches.map((b) => [b.parentId, b.effect, b.unmatched]), [["full", null, true]]);
  // A full-size branch whose parent is a smoke run never switches to the smoke baseline: not compared.
  const fullOnSmoke = buildReport({
    claims: [],
    experiments: [
      exp("smoke", { config: { scale: "smoke" } }),
      exp("f1", { parent_id: "smoke", changed_key: "temperature", config: { scale: "full", whatif: { task_id: "w1", key: "temperature", value: 1 } } }),
    ],
    metrics: [metric("smoke", "final_teacher", 1418, 10), metric("f1", "final_teacher", 216, 40)],
    whatifBaselines: { w1: "smoke" },
  });
  assert.deepEqual(fullOnSmoke.branches.map((b) => [b.parentId, b.effect, b.unmatched]), [["smoke", null, true]]);
});
