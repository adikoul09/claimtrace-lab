// Home list line for a finished live run, counted by code from its experiments' verdicts with the Report tab's rule:
// each claim (and claim-vs-claim comparison) once, from the latest reproduction experiment that graded it;
// what-if branches (parent_id or config.whatif) change a setting on purpose and do not count.
import { readVerdicts } from "../report/report.ts";

type ExpLike = { id: string; created_at: string; parent_id: string | null; config: unknown; verdicts: unknown };

const ORDER = ["reproduced", "partially_reproduced", "not_reproduced", "not_runnable"];

export function runSummary(experiments: ExpLike[]): string {
  const latest = new Map<string, string>();
  const sorted = [...experiments].sort((a, b) => Date.parse(a.created_at) - Date.parse(b.created_at));
  for (const e of sorted) {
    const cfg = e.config && typeof e.config === "object" ? (e.config as Record<string, unknown>) : {};
    if (e.parent_id || cfg.whatif) continue;
    const g = readVerdicts(e.verdicts);
    for (const c of g.cards.values()) latest.set(c.claim_id, c.verdict);
    for (const r of g.relative) latest.set(`${r.method}_vs_${r.baseline}`, r.verdict);
  }
  const counts = new Map<string, number>();
  for (const v of latest.values()) counts.set(v, (counts.get(v) ?? 0) + 1);
  const kinds = [...ORDER, ...[...counts.keys()].filter((k) => !ORDER.includes(k))].filter((k) => counts.get(k));
  const parts = kinds.map((k) => `${counts.get(k)} ${k.replace(/_/g, " ")}`);
  return ["Run end to end by the agents", ...(parts.length ? parts : ["no claims graded yet"])].join(" · ");
}
