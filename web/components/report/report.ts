// Pure helpers for the Report tab (SPEC §7.5, §6, §10). The screen and the Markdown export both render the
// ReportData built here, so they cannot disagree. The UI computes no verdicts: they come from experiments.verdicts,
// written by the Analyst (code). The only arithmetic here is differences and sums of stored, logged values.
import type { Point } from "../exp/experiments";
import { deriveStages } from "../../app/p/[id]/stages.ts";

export type Claim = {
  id: string;
  quote: string;
  page: number | null;
  table_or_section: string;
  metric: string;
  value: number;
  unit: string;
  direction: string;
  whose: string;
  model: string;
  valid: boolean;
  /** ANY-1 (lab/agents/triage.py): papers.claims[i].runnable {status, reason}; null until the Reader tags it. */
  runnable: { runnable: boolean; reason: string | null } | null;
};

function runnableTag(r: unknown): Claim["runnable"] {
  if (!isObj(r) || (r.status !== "runnable" && r.status !== "not_runnable")) return null;
  return { runnable: r.status === "runnable", reason: typeof r.reason === "string" && r.reason ? r.reason : null };
}

const str = (x: unknown) => (typeof x === "string" ? x : "");
const num = (x: unknown) => (typeof x === "number" && Number.isFinite(x) ? x : null);
const isObj = (x: unknown): x is Record<string, unknown> => typeof x === "object" && x !== null && !Array.isArray(x);
const ms = (ts: string) => Date.parse(ts);

/** papers.claims → cards with an id and a numeric value; anything else is dropped. */
export function parseClaims(json: unknown): Claim[] {
  if (!Array.isArray(json)) return [];
  return json.filter(isObj).flatMap((c) =>
    typeof c.id === "string" && typeof c.value === "number"
      ? [
          {
            id: c.id,
            quote: str(c.quote),
            page: typeof c.page === "number" ? c.page : null,
            table_or_section: str(c.table_or_section),
            metric: str(c.metric),
            value: c.value,
            unit: str(c.unit),
            direction: str(c.direction),
            whose: str(c.whose),
            model: str(c.model),
            valid: c.valid !== false,
            runnable: runnableTag(c.runnable),
          },
        ]
      : [],
  );
}

// ---- verdicts ------------------------------------------------------------------------------------------------------

/** One graded claim, as lab/agents/analyst.py writes it in experiments.verdicts.claims. */
export type VerdictCard = {
  claim_id: string;
  verdict: string; // normalised: reproduced | partially_reproduced | not_reproduced | not_runnable
  label: string; // as written, e.g. "Partially reproduced (1 seed)"
  why: string | null;
  ours: number | null;
  paper: number | null;
  unit: string | null;
  delta: number | null;
  log_line: number | null;
  metric_name: string | null;
  model: string | null;
  margin: number | null;
  /** "1 seed" when the verdict says it rests on fewer than 3 seeds, else null. */
  seedNote: string | null;
};
export type RelativeVerdict = {
  claim: string;
  method: string;
  baseline: string;
  paper_gap: number | null;
  ours_gap: number | null;
  verdict: string;
  label: string;
  seedNote: string | null;
  sizeNote: string | null;
};
/** "a better than b" in the paper, and whether our numbers keep that order (the Analyst's relations). */
export type Relation = { a: string; b: string; holds: boolean };
export type Explanation = { text: string | null; accepted: boolean; problems: string[] };
export type DiffLabel = "scale" | "omission" | "difference" | "same";
export type SettingsDiffRow = {
  key: string;
  paper: string | null;
  ours: string | null;
  label: DiffLabel | null;
  rawLabel: string;
  quote: string | null;
  page: number | null;
  config_key: string | null;
  reason: string | null;
  /** The model the paper's value is for ("teacher"), null when it applies to all. */
  applies_to: string | null;
};
export type Grade = {
  cards: Map<string, VerdictCard>;
  relative: RelativeVerdict[];
  explanation: Explanation | null;
  marginNote: string | null;
  seeds: number | null;
  rules: string | null;
  settingsDiff: SettingsDiffRow[];
  relations: Relation[];
};

const norm = (v: string) => v.trim().toLowerCase().replace(/[\s-]+/g, "_");

const SEEDS = /^\((\d+ seeds?)\)\s*/;
const LABEL_SEEDS = /\((\d+ seeds?)\)\s*$/;

function card(id: unknown, v: unknown): VerdictCard | null {
  const c = isObj(v) ? v : { verdict: v };
  if (typeof id !== "string" || typeof c.verdict !== "string") return null;
  const raw = c.why ?? c.note ?? c.reason;
  let why = typeof raw === "string" ? raw : null;
  let label = typeof c.label === "string" ? c.label : verdictLabel(norm(c.verdict)).label;
  // CONTRACTS.md §5: with fewer than 3 seeds the note starts with "(1 seed)"; it belongs with the verdict.
  const seeds = typeof c.label === "string" || !why ? null : SEEDS.exec(why);
  const seedNote = seeds?.[1] ?? LABEL_SEEDS.exec(label)?.[1] ?? null;
  if (seeds && why) {
    label += ` (${seeds[1]})`;
    why = why.slice(seeds[0].length) || null;
  }
  return {
    claim_id: id,
    verdict: norm(c.verdict),
    label,
    why,
    ours: num(c.ours),
    paper: num(c.paper),
    unit: typeof c.unit === "string" ? c.unit : null,
    delta: num(c.delta),
    log_line: num(c.log_line),
    metric_name: typeof c.metric_name === "string" ? c.metric_name : null,
    model: typeof c.model === "string" ? c.model : null,
    margin: num(c.margin),
    seedNote,
  };
}

export function parseExplanation(e: unknown): Explanation | null {
  if (!isObj(e)) return null;
  return {
    text: typeof e.text === "string" && e.text ? e.text : null,
    accepted: e.accepted === true,
    problems: Array.isArray(e.problems) ? e.problems.filter((p): p is string => typeof p === "string") : [],
  };
}

const DIFF_LABELS: [RegExp, DiffLabel][] = [
  [/scale/, "scale"],
  [/omi(t|ss)/, "omission"],
  [/diff/, "difference"],
  [/same/, "same"],
];

function settingsDiff(json: unknown): SettingsDiffRow[] {
  if (!Array.isArray(json)) return [];
  return json.filter(isObj).flatMap((r) => {
    if (typeof r.key !== "string") return [];
    const raw = str(r.label);
    const text = (x: unknown) =>
      x === null || x === undefined ? null : typeof x === "object" ? JSON.stringify(x) : String(x);
    const scope = str(r.applies_to);
    return [
      {
        key: r.key,
        paper: text(r.paper),
        ours: text(r.ours),
        label: DIFF_LABELS.find(([re]) => re.test(raw.toLowerCase()))?.[1] ?? null,
        rawLabel: raw,
        quote: typeof r.quote === "string" ? r.quote : null,
        page: num(r.page),
        // CONTRACTS §5b (lab/agents/why.py) names them our_key and why; the earlier proposal config_key and reason.
        config_key: typeof r.our_key === "string" ? r.our_key : typeof r.config_key === "string" ? r.config_key : null,
        reason: typeof r.why === "string" ? r.why : typeof r.reason === "string" ? r.reason : null,
        applies_to: scope && scope.toLowerCase() !== "all" ? scope : null,
      },
    ];
  });
}

// Differences first, then budget cuts, then matches, then what the paper does not say (stable within each).
const LABEL_ORDER: (DiffLabel | null)[] = ["difference", "scale", "same", "omission", null];
const labelRank = (r: SettingsDiffRow) => LABEL_ORDER.indexOf(r.label);

/** experiments.verdicts → Grade. The contract (docs/CONTRACTS.md §5) is a list, one item per claim, relative claims as
 *  "<method>_vs_<baseline>" items whose ours/paper are gaps. Still read as fallbacks: the Analyst's object
 *  {claims: [...], relative, explanation, ...} and the old {claim_id: verdict | {verdict, note}} dict. */
export function readVerdicts(json: unknown): Grade {
  const g: Grade = {
    cards: new Map(),
    relative: [],
    explanation: null,
    marginNote: null,
    seeds: null,
    rules: null,
    settingsDiff: [],
    relations: [],
  };
  const addAll = (list: unknown[]) => {
    for (const v of list) if (isObj(v)) {
      const c = card(v.claim_id ?? v.claim, v);
      if (!c) continue;
      const vs = /^(.+)_vs_(.+)$/.exec(c.claim_id);
      if (vs)
        g.relative.push({
          claim: `${vs[1]} beats ${vs[2]}`,
          method: vs[1],
          baseline: vs[2],
          paper_gap: num(v.paper),
          ours_gap: c.ours,
          verdict: c.verdict,
          label: c.label + (c.why ? ` ${c.why}` : ""),
          seedNote: c.seedNote,
          sizeNote: c.why,
        });
      else g.cards.set(c.claim_id, c);
    }
  };
  if (Array.isArray(json)) {
    addAll(json);
  } else if (isObj(json) && Array.isArray(json.claims)) {
    addAll(json.claims);
    g.relative = (Array.isArray(json.relative) ? json.relative : []).filter(isObj).flatMap((r) =>
      typeof r.verdict === "string"
        ? [
            {
              seedNote: typeof r.label === "string" ? (LABEL_SEEDS.exec(r.label)?.[1] ?? null) : null,
              sizeNote: typeof r.size_note === "string" ? r.size_note : null,
              claim: str(r.claim),
              method: str(r.method),
              baseline: str(r.baseline),
              paper_gap: num(r.paper_gap),
              ours_gap: num(r.ours_gap),
              verdict: norm(r.verdict),
              label: typeof r.label === "string" ? r.label : r.verdict,
            },
          ]
        : [],
    );
    g.explanation = parseExplanation(json.explanation);
    g.marginNote = typeof json.margin_note === "string" ? json.margin_note : null;
    g.seeds = num(json.seeds);
    // The Analyst's object states its seed count once; a verdict on fewer than 3 seeds carries it.
    if (g.seeds !== null && g.seeds < 3) {
      const note = `${g.seeds} seed${g.seeds === 1 ? "" : "s"}`;
      for (const c of g.cards.values()) c.seedNote ??= note;
      for (const r of g.relative) r.seedNote ??= note;
    }
    g.rules = typeof json.rules === "string" ? json.rules : null;
    g.settingsDiff = settingsDiff(json.settings_diff);
    g.relations = (Array.isArray(json.relations) ? json.relations : []).filter(isObj).flatMap((r) =>
      typeof r.a === "string" && typeof r.b === "string" && typeof r.holds === "boolean"
        ? [{ a: r.a, b: r.b, holds: r.holds }]
        : [],
    );
  } else if (isObj(json)) {
    for (const [id, v] of Object.entries(json)) {
      const c = card(id, v);
      if (c) g.cards.set(c.claim_id, c);
    }
  }
  return g;
}

export type Tone = "good" | "warning" | "critical" | "neutral";
const LABELS: Record<string, { label: string; tone: Tone }> = {
  reproduced: { label: "Reproduced", tone: "good" },
  partially_reproduced: { label: "Partially reproduced", tone: "warning" },
  not_reproduced: { label: "Not reproduced", tone: "critical" },
  not_runnable: { label: "Not runnable", tone: "neutral" },
};
export const verdictLabel = (v: string) => LABELS[v] ?? { label: v, tone: "neutral" as Tone };

// ---- the report ----------------------------------------------------------------------------------------------------

export type ExpRow = {
  id: string;
  label: string;
  created_at: string;
  config: unknown;
  margin: number | null;
  verdicts: unknown;
  parent_id: string | null;
  changed_key: string | null;
  status: string;
  pruned_reason: string | null;
};
export type MetricRow = { experiment_id: string; name: string; step: number; value: number | null; log_line: number };
/** From a `graded` event's data: grading detail lives there under the contract (CONTRACTS.md §5). */
export type GradedEvent = { experiment_id: string; ts: string; explanation: unknown };
export type TaskRow = { id: string; capability: string; status: string; created_at: string; finished_at: string | null };
export type LlmRow = { task_id: string | null; tokens_in: number; tokens_out: number };
export type EventRow = { id: string; type: string; message: string; ts: string };
export type ProjectRow = { id: string; title: string; arxiv_id: string | null; created_at: string; status: string };

export type ReportRow = {
  claim: Claim;
  model: string;
  metricName: string;
  experimentId: string;
  experimentLabel: string;
  margin: number | null;
  /** Our logged value(s) for this claim, each with its log line (one per seed). */
  ours: Point[];
  delta: number | null;
  verdict: VerdictCard | null;
  /** One plain sentence on why a claim is only partially or not reproduced (claimWhy), else null. */
  explain: string | null;
  /** Set when the row comes from a smoke run (config.scale "smoke"): its epoch count from config.cmd, if stated. */
  smoke: { epochs: number | null } | null;
};
export type GradedExp = {
  experimentId: string;
  experimentLabel: string;
  relative: (RelativeVerdict & { lines: { exp: string; line: number }[]; explain: string | null })[];
  explanation: Explanation | null;
  marginNote: string | null;
  seeds: number | null;
  rules: string | null;
};
export type BranchEffect = {
  key: string;
  branchId: string;
  branchLabel: string;
  parentId: string;
  parentLabel: string;
  status: string;
  prunedReason: string | null;
  metric: string;
  parent: Point | null;
  branch: Point | null;
  effect: string | null;
};
export type RunStats = {
  projectId: string;
  title: string;
  failedBeforeFirstSuccess: number | null; // null: no successful run yet
  failedRuns: number;
  secondsToFirstResult: number | null;
  llmTokens: number;
  llmCalls: number;
  lessonsApplied: EventRow[];
};
/** The headline: how many claims each verdict got, counted by code from the Analyst's verdicts. */
export type Authenticity = {
  rows: { verdict: string; label: string; tone: Tone; count: number; seeds: string | null }[];
  total: number;
  claims: number;
  comparisons: number;
  sources: { id: string; label: string }[];
};
export type ReportData = {
  authenticity: Authenticity;
  rows: ReportRow[];
  untested: Claim[];
  /** Every claim in the paper, sorted by whether it can run on a laptop (ANY-1 tags). */
  triage: ClaimTriage;
  graded: GradedExp[];
  /** configLogLine: the run's printed CONFIG line, where our values come from (config.why only). */
  settingsDiff: { experimentId: string; experimentLabel: string; rows: SettingsDiffRow[]; configLogLine: number | null } | null;
  branches: BranchEffect[];
  /** previousStop: where the earlier run stopped ("stopped at Designing"), null when it finished. */
  memory: { current: RunStats; previous: RunStats | null; previousStop: string | null } | null;
};

/** NaN or inf in the log is stored as NULL (CONTRACTS.md §5, migration 003). */
export const valueText = (v: unknown) => (v === null || v === undefined ? "non-finite" : String(v));
const point = (m: MetricRow): Point => ({
  step: m.step,
  value: num(m.value),
  text: valueText(m.value),
  log_line: m.log_line,
});
const finalName = (model: string) => (model.startsWith("final_") ? model : `final_${model}`);

function lastPoint(metrics: MetricRow[], exp: string, name: string): Point | null {
  const ps = metrics.filter((m) => m.experiment_id === exp && m.name === name).sort((a, b) => a.log_line - b.log_line);
  return ps.length ? point(ps[ps.length - 1]) : null;
}

const decimals = (t: string) => (/\.(\d+)$/.exec(t)?.[1].length ?? 0);
/** branch − parent, at the precision of the logged values; null if either is not a finite number. */
export function diffText(parent: Point, branch: Point): string | null {
  if (parent.value === null || branch.value === null) return null;
  const d = branch.value - parent.value;
  const s = d.toFixed(Math.max(decimals(parent.text), decimals(branch.text)));
  return d > 0 ? `+${s}` : s === "-0" ? "0" : s;
}

const STILL_GOING = new Set(["new", "planning", "running"]);

/** Where an earlier run that did not finish got to, by the stage strip's rules ("stopped at Designing"). */
export function previousStop(status: string, tasks: TaskRow[]): string | null {
  if (status === "done") return null;
  const stages = deriveStages({
    projectStatus: status,
    tasks: tasks.map((t) => ({ ...t, scale: null, whatif: null, error: null })),
    failures: [],
    claims: 0,
    sortedClaims: 0,
    experiments: [],
  });
  // The stage that failed, else one still going, else the first after the last finished one.
  const lastDone = stages.map((s) => s.state).lastIndexOf("done");
  const at =
    stages.find((s) => s.state === "failed") ??
    stages.find((s) => s.state === "running" || s.state === "waiting") ??
    stages[Math.min(lastDone + 1, stages.length - 1)];
  return STILL_GOING.has(status) ? `still running, at ${at.label}` : `stopped at ${at.label}`;
}

/** Run statistics for the memory effect (SPEC §6, R14), from the project's own rows. */
export function runStats(project: ProjectRow, tasks: TaskRow[], llm: LlmRow[], events: EventRow[]): RunStats {
  const runs = tasks
    .filter((t) => t.capability === "run" && t.finished_at && (t.status === "done" || t.status === "failed"))
    .sort((a, b) => ms(a.finished_at!) - ms(b.finished_at!));
  const first = runs.find((t) => t.status === "done");
  const ids = new Set(tasks.map((t) => t.id));
  const mine = llm.filter((c) => c.task_id && ids.has(c.task_id));
  return {
    projectId: project.id,
    title: project.title,
    failedBeforeFirstSuccess: first ? runs.indexOf(first) : null,
    failedRuns: runs.filter((t) => t.status === "failed").length,
    secondsToFirstResult: first ? Math.round((ms(first.finished_at!) - ms(project.created_at)) / 1000) : null,
    llmTokens: mine.reduce((s, c) => s + (c.tokens_in ?? 0) + (c.tokens_out ?? 0), 0),
    llmCalls: mine.length,
    lessonsApplied: events.filter((e) => e.type === "lesson_applied"),
  };
}

export type ReportInput = {
  claims: Claim[];
  experiments: ExpRow[];
  metrics: MetricRow[];
  graded?: GradedEvent[];
  memory?: {
    project: ProjectRow;
    tasks: TaskRow[];
    llm: LlmRow[];
    events: EventRow[];
    previous: { project: ProjectRow; tasks: TaskRow[]; llm: LlmRow[]; events: EventRow[]; stop?: string | null } | null;
  };
};

/** Claims vs ours: one row per graded claim card, or per experiments.config.claim_map entry when not graded yet.
 *  Our value is the card's (with its log line) or else the final_<model> METRIC line(s). */
export function buildReport(input: ReportInput): ReportData {
  const { claims, experiments, metrics } = input;
  const byId = new Map(claims.map((c) => [c.id, c]));
  const sorted = [...experiments].sort((a, b) => ms(a.created_at) - ms(b.created_at));
  const expById = new Map(sorted.map((e) => [e.id, e]));
  const rows: ReportRow[] = [];
  const graded: GradedExp[] = [];
  let settings: ReportData["settingsDiff"] = null;
  let settingsFromMain = false;

  for (const e of sorted) {
    const g = readVerdicts(e.verdicts);
    const map = isObj(e.config) && isObj(e.config.claim_map) ? e.config.claim_map : {};
    const pairs: [string, string][] = Object.entries(map).flatMap(([m, c]) => (typeof c === "string" ? [[m, c]] : []));
    for (const c of g.cards.values())
      if (!pairs.some(([, cid]) => cid === c.claim_id)) pairs.push([c.model ?? c.claim_id, c.claim_id]);

    const lineOf = new Map<string, number>();
    for (const [model, cid] of pairs) {
      const claim = byId.get(cid);
      if (!claim) continue;
      const v = g.cards.get(cid) ?? null;
      const metricName = v?.metric_name ?? finalName(model);
      const logged = metrics
        .filter((m) => m.experiment_id === e.id && m.name === metricName)
        .sort((a, b) => a.log_line - b.log_line)
        .map(point);
      const ours =
        v && v.ours !== null && v.log_line !== null && !logged.some((p) => p.log_line === v.log_line)
          ? [{ step: 0, value: v.ours, text: String(v.ours), log_line: v.log_line }]
          : logged;
      if (v?.log_line != null) lineOf.set(cid, v.log_line);
      rows.push({
        claim,
        model,
        metricName,
        experimentId: e.id,
        experimentLabel: e.label,
        margin: v?.margin ?? e.margin,
        ours,
        delta: v?.delta ?? null,
        verdict: v,
        smoke: smokeOf(e),
        explain: v ? claimWhy({ ...v, margin: v.margin ?? e.margin }, claim, g, (id) => shortName(byId.get(id), id)) : null,
      });
    }
    const latest = (input.graded ?? [])
      .filter((x) => x.experiment_id === e.id)
      .sort((a, b) => ms(b.ts) - ms(a.ts))[0];
    g.explanation ??= latest ? parseExplanation(latest.explanation) : null;
    if (g.cards.size || g.relative.length || g.explanation) {
      graded.push({
        experimentId: e.id,
        experimentLabel: e.label,
        relative: g.relative.map((r) => ({
          ...r,
          explain: relativeWhy(r),
          lines: [r.method, r.baseline].flatMap((c) => (lineOf.has(c) ? [{ exp: e.id, line: lineOf.get(c)! }] : [])),
        })),
        explanation: g.explanation,
        marginNote: g.marginNote,
        seeds: g.seeds,
        rules: g.rules,
      });
    }
    // CONTRACTS §5b: experiments.config.why.settings_diff; the older verdicts.settings_diff only when that is empty.
    // The main reproduction's diff wins over a follow-up branch's (which changes a setting on purpose).
    const why = isObj(e.config) && isObj(e.config.why) ? e.config.why : null;
    const whyRows = settingsDiff(why?.settings_diff);
    const diffRows = whyRows.length ? whyRows : g.settingsDiff;
    const branch = !!e.parent_id || (isObj(e.config) && !!e.config.whatif);
    if (diffRows.length && (!branch || !settingsFromMain))
      settings = {
        experimentId: e.id,
        experimentLabel: e.label,
        rows: [...diffRows].sort((a, b) => labelRank(a) - labelRank(b)),
        configLogLine: whyRows.length ? num(why?.config_log_line) : null,
      };
    if (diffRows.length && !branch) settingsFromMain = true;
  }

  // Authenticity: each claim's verdict from the latest reproduction experiment that graded it. What-if branches
  // (parent_id or config.whatif) change a setting on purpose, so their verdicts do not count.
  const latest = new Map<string, { verdict: string; seedNote: string | null; relative: boolean; exp: ExpRow }>();
  for (const e of sorted) {
    if (e.parent_id || (isObj(e.config) && e.config.whatif)) continue;
    const g = readVerdicts(e.verdicts);
    for (const c of g.cards.values()) latest.set(c.claim_id, { ...c, relative: false, exp: e });
    for (const r of g.relative) latest.set(`${r.method}_vs_${r.baseline}`, { ...r, relative: true, exp: e });
  }

  // Branch effects: each one-change branch against its parent, on every final_* metric both logged.
  const branches: BranchEffect[] = [];
  for (const e of sorted) {
    const parent = e.parent_id ? expById.get(e.parent_id) : undefined;
    if (!parent || !e.changed_key) continue;
    const names = [...new Set(metrics.filter((m) => m.experiment_id === parent.id).map((m) => m.name))]
      .filter((n) => n.startsWith("final_") && !n.endsWith("_wall_s") && n !== "final_total_wall_s");
    const base = {
      key: e.changed_key,
      branchId: e.id,
      branchLabel: e.label,
      parentId: parent.id,
      parentLabel: parent.label,
      status: e.status,
      prunedReason: e.pruned_reason,
    };
    if (!names.length) branches.push({ ...base, metric: "", parent: null, branch: null, effect: null });
    for (const n of names) {
      const p = lastPoint(metrics, parent.id, n);
      const b = lastPoint(metrics, e.id, n);
      branches.push({ ...base, metric: n, parent: p, branch: b, effect: p && b ? diffText(p, b) : null });
    }
  }

  const tested = new Set(rows.map((r) => r.claim.id));
  const mem = input.memory;
  return {
    authenticity: authenticity([...latest.values()]),
    rows,
    untested: claims.filter((c) => !tested.has(c.id)),
    triage: claimTriage(claims),
    graded,
    settingsDiff: settings,
    branches,
    memory: mem
      ? {
          current: runStats(mem.project, mem.tasks, mem.llm, mem.events),
          previous: mem.previous
            ? runStats(mem.previous.project, mem.previous.tasks, mem.previous.llm, mem.previous.events)
            : null,
          previousStop: mem.previous?.stop ?? null,
        }
      : null,
  };
}

// ---- why a claim is not fully reproduced (plain sentences, numbers only from the verdict) ---------------------------

const WHY_VERDICTS = new Set(["partially_reproduced", "not_reproduced"]);
/** "Distilled small net (800 units/layer)" → "Distilled small net". */
const shortName = (c: Claim | undefined, id: string) => c?.model.replace(/\s*\([^)]*\)/g, "").trim() || id;
const order = (a: number, b: number) => (a < b ? "<" : a > b ? ">" : "=");
const seedTail = (note: string | null) => (note ? ` ${note}.` : "");

/** "Partially reproduced: ours 96 vs paper 74 (gap 22, over the margin of 10 errors), but the paper's direction holds
 *  (Distilled small net 96 < Small net 143). 1 seed." Every number is one the verdict stores (ours, paper, |delta|,
 *  margin (the item's, else the experiment's), the other claims' ours); code only compares them. Parts the verdict does not carry are left out. */
export function claimWhy(v: VerdictCard, claim: Claim, g: Grade, name: (id: string) => string): string | null {
  if (!WHY_VERDICTS.has(v.verdict) || v.ours === null) return null;
  const unit = v.unit ?? claim.unit;
  let s = `${verdictLabel(v.verdict).label}: ours ${v.ours} vs paper ${v.paper ?? claim.value}`;
  if (v.delta !== null) {
    const gap = Math.abs(v.delta);
    s +=
      v.margin === null
        ? ` (gap ${gap})`
        : ` (gap ${gap}, ${gap > v.margin ? "over" : "within"} the margin of ${v.margin}${unit ? ` ${unit}` : ""})`;
  }
  const ours = (id: string) => (id === v.claim_id ? v.ours : (g.cards.get(id)?.ours ?? null));
  const mine = g.relations.filter((r) => (r.a === v.claim_id || r.b === v.claim_id) && ours(r.a) !== null && ours(r.b) !== null);
  const text = (r: Relation) => `${name(r.a)} ${ours(r.a)} ${order(ours(r.a)!, ours(r.b)!)} ${name(r.b)} ${ours(r.b)}`;
  const broken = mine.filter((r) => !r.holds);
  const held = mine.filter((r) => r.holds);
  // Lead with the orders where this claim is the better one (method over baseline), else any that involve it.
  const lead = held.some((r) => r.a === v.claim_id) ? held.filter((r) => r.a === v.claim_id) : held;
  if (broken.length) s += `, and the paper's direction does not hold (${broken.map(text).join("; ")})`;
  else if (lead.length) s += `, but the paper's direction holds (${lead.map(text).join("; ")})`;
  return `${s}.${seedTail(v.seedNote)}`;
}

/** "Partially reproduced: our gap 47 vs the paper's 72 (gap smaller than reported). 1 seed." */
export function relativeWhy(r: RelativeVerdict): string | null {
  if (!WHY_VERDICTS.has(r.verdict) || r.ours_gap === null || r.paper_gap === null) return null;
  const size = r.sizeNote ? ` (${r.sizeNote})` : "";
  return `${verdictLabel(r.verdict).label}: our gap ${r.ours_gap} vs the paper's ${r.paper_gap}${size}.${seedTail(r.seedNote)}`;
}

const HEADLINE = ["reproduced", "partially_reproduced", "not_reproduced"];

function authenticity(
  graded: { verdict: string; seedNote: string | null; relative: boolean; exp: ExpRow }[],
): Authenticity {
  const kinds = [...HEADLINE, ...new Set(graded.map((g) => g.verdict).filter((v) => !HEADLINE.includes(v)))];
  const rows = kinds.map((verdict) => {
    const these = graded.filter((g) => g.verdict === verdict);
    const notes = new Map<string, number>();
    for (const g of these) if (g.seedNote) notes.set(g.seedNote, (notes.get(g.seedNote) ?? 0) + 1);
    // "1 seed" when every one of them says so; "2 with 1 seed" when only some do.
    const seeds = [...notes].map(([n, k]) => (k === these.length ? n : `${k} with ${n}`)).join(", ") || null;
    return { verdict, ...verdictLabel(verdict), count: these.length, seeds };
  });
  const sources = new Map(graded.map((g) => [g.exp.id, { id: g.exp.id, label: g.exp.label }]));
  const comparisons = graded.filter((g) => g.relative).length;
  return { rows, total: graded.length, claims: graded.length - comparisons, comparisons, sources: [...sources.values()] };
}

export type ClaimTriage = {
  total: number;
  runnable: number;
  notRunnable: number;
  unsorted: number; // no runnable tag yet
  /** Why claims cannot run, by the reason's lead ("no public data", "dataset too big"), most common first. */
  reasons: { reason: string; count: number }[];
  /** Runnable first, then not runnable (by their reason's count), then unsorted; paper order within each. */
  ordered: Claim[];
};

export function claimTriage(claims: Claim[]): ClaimTriage {
  const lead = (c: Claim) => (c.runnable?.reason ?? "reason not given").split(":")[0].trim();
  const blocked = claims.filter((c) => c.runnable && !c.runnable.runnable);
  const counts = new Map<string, number>();
  for (const c of blocked) counts.set(lead(c), (counts.get(lead(c)) ?? 0) + 1);
  const reasons = [...counts]
    .map(([reason, count]) => ({ reason, count }))
    .sort((a, b) => b.count - a.count || a.reason.localeCompare(b.reason));
  const rank = new Map(reasons.map((r, i) => [r.reason, i]));
  const runnable = claims.filter((c) => c.runnable?.runnable);
  return {
    total: claims.length,
    runnable: runnable.length,
    notRunnable: blocked.length,
    unsorted: claims.filter((c) => !c.runnable).length,
    reasons,
    ordered: [
      ...runnable,
      ...blocked.map((c, i) => ({ c, i })).sort((a, b) => rank.get(lead(a.c))! - rank.get(lead(b.c))! || a.i - b.i).map((x) => x.c),
      ...claims.filter((c) => !c.runnable),
    ],
  };
}

function smokeOf(e: ExpRow): ReportRow["smoke"] {
  if (!isObj(e.config) || e.config.scale !== "smoke") return null;
  const m = typeof e.config.cmd === "string" ? /--epochs[ =](\d+)/.exec(e.config.cmd) : null;
  return { epochs: m ? Number(m[1]) : null };
}

/** "Smoke check (1 epoch, not graded)" for an ungraded smoke-run row, else null. */
export function smokeLabel(r: ReportRow): string | null {
  if (!r.smoke || r.verdict) return null;
  const n = r.smoke.epochs;
  return `Smoke check (${n === null ? "" : `${n} epoch${n === 1 ? "" : "s"}, `}not graded)`;
}

/** Claims vs ours: graded and measured rows to show, and the rest: rows of runs that are only planned (no verdict,
 *  no logged value yet) and ungraded smoke checks (a short run that only proves the code runs). */
export function splitClaimRows(rows: ReportRow[]): { shown: ReportRow[]; planned: ReportRow[] } {
  const planned = (r: ReportRow) => !r.verdict && (r.ours.length === 0 || r.smoke !== null);
  return { shown: rows.filter((r) => !planned(r)), planned: rows.filter(planned) };
}

/** The Reporter's latest notes: the newest done write_notes task's output.markdown (CONTRACTS.md §4). */
export function latestNotes(
  tasks: { id: string; capability: string; status: string; finished_at: string | null; output: unknown }[],
): { taskId: string; markdown: string } | null {
  const hit = tasks
    .filter((t) => t.capability === "write_notes" && t.status === "done" && t.finished_at)
    .sort((a, b) => ms(b.finished_at!) - ms(a.finished_at!))
    .find((t) => isObj(t.output) && typeof t.output.markdown === "string" && t.output.markdown);
  return hit ? { taskId: hit.id, markdown: (hit.output as { markdown: string }).markdown } : null;
}
