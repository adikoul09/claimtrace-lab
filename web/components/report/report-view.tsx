"use client";

// Report tab (SPEC §10): the paper's claims next to our values and the Analyst's verdicts.
// Each of our numbers links to its log line; each paper number shows its quote and page. Nothing is computed here.
import { useEffect, useMemo, useState } from "react";
import { supabase } from "@/lib/supabase";
import type { Experiment, Metric, Paper } from "@/lib/types";
import { upsertRows } from "../exp/experiments";
import { buildReport, parseClaims, verdictLabel, type Claim, type ReportRow, type Tone } from "./report";

const TONE: Record<Tone, string> = {
  good: "bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300",
  warning: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
  critical: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
  neutral: "bg-neutral-200 text-neutral-700 dark:bg-neutral-800 dark:text-neutral-300",
};
const ICON: Record<Tone, string> = { good: "✓", warning: "≈", critical: "✗", neutral: "–" };

type ExpRow = Pick<Experiment, "id" | "label" | "created_at" | "config" | "margin" | "verdicts">;
const EXP_COLS = "id,label,created_at,config,margin,verdicts";

export function ReportView({ projectId }: { projectId: string }) {
  const [paper, setPaper] = useState<Pick<Paper, "title" | "arxiv_id" | "claims"> | null>(null);
  const [experiments, setExperiments] = useState<ExpRow[]>([]);
  const [metrics, setMetrics] = useState<Metric[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const db = supabase();
    const fail = (e: { message: string }) => setError(e.message);

    // Verdicts and final values can land while the tab is open. Metrics have no project_id: filtered at render.
    const channel = db
      .channel(`report-${projectId}`)
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "experiments", filter: `project_id=eq.${projectId}` },
        (p) => p.eventType !== "DELETE" && setExperiments((cur) => upsertRows(cur, [p.new as ExpRow])),
      )
      .on("postgres_changes", { event: "INSERT", schema: "public", table: "metrics" }, (p) => {
        const m = p.new as Metric;
        if (m.name.startsWith("final_")) setMetrics((cur) => upsertRows(cur, [m]));
      })
      .subscribe();

    Promise.all([
      db.from("papers").select("title,arxiv_id,claims").eq("project_id", projectId).maybeSingle(),
      db.from("experiments").select(EXP_COLS).eq("project_id", projectId),
    ]).then(async ([p, e]) => {
      if (p.error) fail(p.error);
      else setPaper(p.data);
      if (e.error) return fail(e.error);
      const rows = (e.data ?? []) as ExpRow[];
      setExperiments((cur) => upsertRows(rows, cur));
      if (rows.length) {
        const m = await db
          .from("metrics")
          .select("*")
          .in("experiment_id", rows.map((r) => r.id))
          .like("name", "final\\_%");
        if (m.error) fail(m.error);
        else setMetrics((cur) => upsertRows((m.data ?? []) as Metric[], cur));
      }
      setLoaded(true);
    });

    return () => {
      db.removeChannel(channel);
    };
  }, [projectId]);

  const claims = useMemo(() => parseClaims(paper?.claims), [paper]);
  const { rows, untested } = useMemo(() => buildReport(claims, experiments, metrics), [claims, experiments, metrics]);

  if (!loaded && !error) return <p className="text-sm text-neutral-500">Loading report…</p>;

  return (
    <section aria-labelledby="report-heading" className="space-y-6">
      <div>
        <h2 id="report-heading" className="text-sm font-semibold">
          Claims vs ours
        </h2>
        <p className="mt-0.5 text-xs text-neutral-500">
          Verdicts are computed by code (the Analyst) against the margin declared before the run. Every number of ours
          links to the log line that printed it.
        </p>
      </div>

      {error && <p className="text-sm text-red-600">Could not load the report: {error}</p>}

      {!paper ? (
        <p className="text-sm text-neutral-500">No paper has been read for this project yet.</p>
      ) : rows.length === 0 ? (
        <p className="text-sm text-neutral-500">
          No run has targeted a claim yet. Rows appear when a reproduction maps its models to claims.
        </p>
      ) : (
        <ClaimsTable rows={rows} />
      )}

      {paper && untested.length > 0 && <UntestedClaims claims={untested} />}
    </section>
  );
}

function ClaimsTable({ rows }: { rows: ReportRow[] }) {
  return (
    <div className="-mx-4 overflow-x-auto px-4">
      <table className="w-full min-w-[20rem] text-left text-sm">
        <thead className="text-xs text-neutral-500">
          <tr className="border-b border-neutral-200 dark:border-neutral-800">
            <th className="py-1.5 pr-2 font-medium">Claim</th>
            <th className="py-1.5 pr-2 text-right font-medium">Paper</th>
            <th className="py-1.5 pr-2 text-right font-medium">Ours</th>
            <th className="py-1.5 font-medium">Verdict</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-neutral-200 align-top dark:divide-neutral-800">
          {rows.map((r) => (
            <tr key={`${r.experimentId}:${r.claim.id}`}>
              <td className="py-2 pr-2">
                <div className="break-words font-medium">
                  {r.claim.model} <span className="font-normal text-neutral-500">· {r.claim.metric}</span>
                </div>
                <div className="mt-0.5 text-xs text-neutral-500">
                  <span className="font-mono">{r.claim.id}</span> · {r.claim.whose} ·{" "}
                  <span className="break-words">{r.experimentLabel}</span>
                </div>
                <Quote claim={r.claim} />
              </td>
              <td className="py-2 pr-2 text-right tabular-nums">
                <span title={`Quoted on page ${r.claim.page ?? "?"}`}>{r.claim.value}</span>
                <div className="text-xs text-neutral-500">{r.claim.unit}</div>
              </td>
              <td className="py-2 pr-2 text-right tabular-nums">
                {r.ours.length === 0 ? (
                  <span className="text-xs text-neutral-500">not measured yet</span>
                ) : (
                  <ul>
                    {r.ours.map((p) => (
                      <li key={p.log_line}>
                        <a
                          href={`/logs/${r.experimentId}#L${p.log_line}`}
                          className="underline decoration-neutral-400 underline-offset-2"
                          title={`METRIC final_${r.model}, log line ${p.log_line}`}
                        >
                          {p.text}
                        </a>
                      </li>
                    ))}
                  </ul>
                )}
                {r.margin !== null && <div className="text-xs text-neutral-500">± {r.margin}</div>}
              </td>
              <td className="py-2">
                {r.verdict ? (
                  <>
                    <VerdictBadge verdict={r.verdict.verdict} />
                    {r.verdict.note && <p className="mt-1 break-words text-xs text-neutral-500">{r.verdict.note}</p>}
                  </>
                ) : (
                  <span className="text-xs text-neutral-500">not graded yet</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function VerdictBadge({ verdict }: { verdict: string }) {
  const { label, tone } = verdictLabel(verdict);
  return (
    <span className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs font-medium ${TONE[tone]}`}>
      <span aria-hidden>{ICON[tone]}</span>
      {label}
    </span>
  );
}

function Quote({ claim: c }: { claim: Claim }) {
  return (
    <details className="mt-1 text-xs">
      <summary className="cursor-pointer text-neutral-500">
        Quote, p. {c.page ?? "?"}
        {c.table_or_section && `, ${c.table_or_section}`}
      </summary>
      <blockquote className="mt-1 break-words border-l-2 border-neutral-300 pl-2 text-neutral-600 dark:border-neutral-700 dark:text-neutral-400">
        {c.quote}
      </blockquote>
    </details>
  );
}

function UntestedClaims({ claims }: { claims: Claim[] }) {
  return (
    <div>
      <h3 className="text-sm font-semibold">
        Other claims in the paper <span className="font-normal text-neutral-500">({claims.length}, not run)</span>
      </h3>
      <ul className="mt-2 divide-y divide-neutral-200 text-sm dark:divide-neutral-800">
        {claims.map((c) => (
          <li key={c.id} className="py-2">
            <div className="flex flex-wrap items-baseline gap-x-2">
              <span className="font-mono text-xs text-neutral-500">{c.id}</span>
              <span className="break-words">
                {c.model} · {c.metric}
              </span>
              <span className="tabular-nums font-medium">
                {c.value} {c.unit}
              </span>
              {!c.valid && (
                <span className="rounded bg-red-100 px-1.5 py-0.5 text-xs text-red-800 dark:bg-red-900/40 dark:text-red-300">
                  failed code check
                </span>
              )}
            </div>
            <Quote claim={c} />
          </li>
        ))}
      </ul>
    </div>
  );
}
