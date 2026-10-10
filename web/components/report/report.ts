// Pure helpers for the Report tab: the paper's claims next to our measured values (SPEC §7.5).
// The UI computes no verdicts: they come from experiments.verdicts, written by the Analyst (code).
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
const isObj = (x: unknown): x is Record<string, unknown> => typeof x === "object" && x !== null && !Array.isArray(x);

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

export type Verdict = { verdict: string; note: string | null };

const norm = (v: string) => v.trim().toLowerCase().replace(/[\s-]+/g, "_");

/** experiments.verdicts → claim id → verdict. Accepts [{claim_id|claim, verdict, note|reason}] or
 *  {claim_id: verdict | {verdict, note|reason}}. */
export function readVerdicts(json: unknown): Map<string, Verdict> {
  const out = new Map<string, Verdict>();
  const add = (id: unknown, v: unknown) => {
    const card = isObj(v) ? v : { verdict: v };
    if (typeof id !== "string" || typeof card.verdict !== "string") return;
    const note = card.note ?? card.reason;
    out.set(id, { verdict: norm(card.verdict), note: typeof note === "string" ? note : null });
  };
  if (Array.isArray(json)) {
    for (const v of json) if (isObj(v)) add(v.claim_id ?? v.claim, v);
  } else if (isObj(json)) {
    for (const [id, v] of Object.entries(json)) add(id, v);
  }
  return out;
}

export type Tone = "good" | "warning" | "critical" | "neutral";
const LABELS: Record<string, { label: string; tone: Tone }> = {
  reproduced: { label: "Reproduced", tone: "good" },
  partially_reproduced: { label: "Partially reproduced", tone: "warning" },
  not_reproduced: { label: "Not reproduced", tone: "critical" },
  not_runnable: { label: "Not runnable", tone: "neutral" },
};
export const verdictLabel = (v: string) => LABELS[v] ?? { label: v, tone: "neutral" as Tone };

type ExpRow = { id: string; label: string; created_at: string; config: unknown; margin: number | null; verdicts: unknown };
type MetricRow = { experiment_id: string; name: string; step: number; value: number; log_line: number };

export type ReportRow = {
  claim: Claim;
  model: string;
  experimentId: string;
  experimentLabel: string;
  margin: number | null;
  /** Every final_<model> value the run logged (one per seed), in log order. */
  ours: Point[];
  verdict: Verdict | null;
};

/** One row per (experiment, mapped claim), oldest experiment first; claims no experiment targets are untested.
 *  The mapping is experiments.config.claim_map = {model: claim_id}; our value is METRIC final_<model>. */
export function buildReport(
  claims: Claim[],
  experiments: ExpRow[],
  metrics: MetricRow[],
): { rows: ReportRow[]; untested: Claim[] } {
  const byId = new Map(claims.map((c) => [c.id, c]));
  const rows: ReportRow[] = [];
  const sorted = [...experiments].sort((a, b) => Date.parse(a.created_at) - Date.parse(b.created_at));
  for (const e of sorted) {
    const map = isObj(e.config) ? e.config.claim_map : null;
    if (!isObj(map)) continue;
    const verdicts = readVerdicts(e.verdicts);
    for (const [model, claimId] of Object.entries(map)) {
      const claim = typeof claimId === "string" ? byId.get(claimId) : undefined;
      if (!claim) continue;
      const ours = metrics
        .filter((m) => m.experiment_id === e.id && m.name === `final_${model}`)
        .sort((a, b) => a.log_line - b.log_line)
        .map((m) => ({
          step: m.step,
          value: typeof m.value === "number" && Number.isFinite(m.value) ? m.value : null,
          text: String(m.value),
          log_line: m.log_line,
        }));
      rows.push({
        claim,
        model,
        experimentId: e.id,
        experimentLabel: e.label,
        margin: e.margin,
        ours,
        verdict: verdicts.get(claim.id) ?? null,
      });
    }
  }
  const tested = new Set(rows.map((r) => r.claim.id));
  return { rows, untested: claims.filter((c) => !tested.has(c.id)) };
}
