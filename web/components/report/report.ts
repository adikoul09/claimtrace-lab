// Pure helpers for the Report tab (SPEC §7.5, §6, §10). The screen and the Markdown export both render the
// ReportData built here, so they cannot disagree. The UI computes no verdicts: they come from experiments.verdicts,
// written by the Analyst (code). The only arithmetic here is differences and sums of stored, logged values.
import type { Point } from "../exp/experiments";

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
};

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
  delta: number | null;
  log_line: number | null;
  metric_name: string | null;
  model: string | null;
};
export type RelativeVerdict = {
  claim: string;
  method: string;
  baseline: string;
  paper_gap: number | null;
  ours_gap: number | null;
  verdict: string;
  label: string;
};
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
};
export type Grade = {
  cards: Map<string, VerdictCard>;
  relative: RelativeVerdict[];
  explanation: Explanation | null;
  marginNote: string | null;
  seeds: number | null;
  rules: string | null;
  settingsDiff: SettingsDiffRow[];
};

const norm = (v: string) => v.trim().toLowerCase().replace(/[\s-]+/g, "_");

function card(id: unknown, v: unknown): VerdictCard | null {
  const c = isObj(v) ? v : { verdict: v };
  if (typeof id !== "string" || typeof c.verdict !== "string") return null;
  const why = c.why ?? c.note ?? c.reason;
  return {
    claim_id: id,
    verdict: norm(c.verdict),
    label: typeof c.label === "string" ? c.label : verdictLabel(norm(c.verdict)).label,
    why: typeof why === "string" ? why : null,
    ours: num(c.ours),
    delta: num(c.delta),
    log_line: num(c.log_line),
    metric_name: typeof c.metric_name === "string" ? c.metric_name : null,
    model: typeof c.model === "string" ? c.model : null,
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
    const text = (x: unknown) => (x === null || x === undefined ? null : String(x));
    return [
      {
        key: r.key,
        paper: text(r.paper),
        ours: text(r.ours),
        label: DIFF_LABELS.find(([re]) => re.test(raw.toLowerCase()))?.[1] ?? null,
        rawLabel: raw,
        quote: typeof r.quote === "string" ? r.quote : null,
        page: num(r.page),
        config_key: typeof r.config_key === "string" ? r.config_key : null,
        reason: typeof r.reason === "string" ? r.reason : null,
      },
    ];
  });
}

/** experiments.verdicts → Grade. The contract is the Analyst's object {claims: [card...], relative, explanation, ...};
 *  a bare list of cards and the older {claim_id: verdict | {verdict, note}} dict are still read. */
export function readVerdicts(json: unknown): Grade {
  const g: Grade = {
    cards: new Map(),
    relative: [],
    explanation: null,
    marginNote: null,
    seeds: null,
    rules: null,
    settingsDiff: [],
  };
  const addAll = (list: unknown[]) => {
    for (const v of list) if (isObj(v)) {
      const c = card(v.claim_id ?? v.claim, v);
      if (c) g.cards.set(c.claim_id, c);
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
    const e = json.explanation;
    if (isObj(e))
      g.explanation = {
        text: typeof e.text === "string" && e.text ? e.text : null,
        accepted: e.accepted === true,
        problems: Array.isArray(e.problems) ? e.problems.filter((p): p is string => typeof p === "string") : [],
      };
    g.marginNote = typeof json.margin_note === "string" ? json.margin_note : null;
    g.seeds = num(json.seeds);
    g.rules = typeof json.rules === "string" ? json.rules : null;
    g.settingsDiff = settingsDiff(json.settings_diff);
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
export type MetricRow = { experiment_id: string; name: string; step: number; value: number; log_line: number };
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
};
export type GradedExp = {
  experimentId: string;
  experimentLabel: string;
  relative: (RelativeVerdict & { lines: { exp: string; line: number }[] })[];
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
export type ReportData = {
  rows: ReportRow[];
  untested: Claim[];
  graded: GradedExp[];
  settingsDiff: { experimentId: string; experimentLabel: string; rows: SettingsDiffRow[] } | null;
  branches: BranchEffect[];
  memory: { current: RunStats; previous: RunStats | null } | null;
};

const point = (m: MetricRow): Point => ({
  step: m.step,
  value: num(m.value),
  text: String(m.value),
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
  memory?: {
    project: ProjectRow;
    tasks: TaskRow[];
    llm: LlmRow[];
    events: EventRow[];
    previous: { project: ProjectRow; tasks: TaskRow[]; llm: LlmRow[]; events: EventRow[] } | null;
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
        margin: e.margin,
        ours,
        delta: v?.delta ?? null,
        verdict: v,
      });
    }
    if (g.cards.size || g.relative.length || g.explanation) {
      graded.push({
        experimentId: e.id,
        experimentLabel: e.label,
        relative: g.relative.map((r) => ({
          ...r,
          lines: [r.method, r.baseline].flatMap((c) => (lineOf.has(c) ? [{ exp: e.id, line: lineOf.get(c)! }] : [])),
        })),
        explanation: g.explanation,
        marginNote: g.marginNote,
        seeds: g.seeds,
        rules: g.rules,
      });
    }
    if (g.settingsDiff.length) settings = { experimentId: e.id, experimentLabel: e.label, rows: g.settingsDiff };
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
    rows,
    untested: claims.filter((c) => !tested.has(c.id)),
    graded,
    settingsDiff: settings,
    branches,
    memory: mem
      ? {
          current: runStats(mem.project, mem.tasks, mem.llm, mem.events),
          previous: mem.previous
            ? runStats(mem.previous.project, mem.previous.tasks, mem.previous.llm, mem.previous.events)
            : null,
        }
      : null,
  };
}
