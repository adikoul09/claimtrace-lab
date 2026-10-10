"use client";

// Report tab (SPEC §10): claims vs ours with the Analyst's verdicts, why results differ (settings diff, branch
// effects), the memory effect, and a Markdown export of exactly this data. Each of our numbers links to its log line;
// each paper number shows its quote and page. No verdict is computed here.
import { useEffect, useRef, useState } from "react";
import { supabase } from "@/lib/supabase";
import type { Metric } from "@/lib/types";
import { retry } from "../exp/experiments";
import { loadReport, type ReportBundle } from "./load";
import { authenticitySummary, DIFF_TEXT, memoryRows, TEXT } from "./markdown";
import { isPrecomputed, PRECOMPUTED_LABEL } from "./precomputed";
import {
  verdictLabel,
  type Authenticity,
  type BranchEffect,
  type Claim,
  type GradedExp,
  type ReportData,
  type ReportRow,
  type Tone,
} from "./report";

const TONE: Record<Tone, string> = {
  good: "bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300",
  warning: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
  critical: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
  neutral: "bg-neutral-200 text-neutral-700 dark:bg-neutral-800 dark:text-neutral-300",
};
const ICON: Record<Tone, string> = { good: "✓", warning: "≈", critical: "✗", neutral: "–" };
const DIFF_TONE: Record<string, Tone> = { scale: "warning", omission: "neutral", difference: "critical", same: "good" };
const RELOAD_MS = 1500;

const LogLink = ({ exp, line, children }: { exp: string; line: number; children: React.ReactNode }) => (
  <a href={`/logs/${exp}#L${line}`} className="underline decoration-neutral-400 underline-offset-2" title={`log line ${line}`}>
    {children}
  </a>
);

const Muted = ({ children }: { children: React.ReactNode }) => <p className="text-sm text-neutral-500">{children}</p>;

const Th = ({ children, right }: { children?: React.ReactNode; right?: boolean }) => (
  <th className={`py-1.5 pr-2 font-medium ${right ? "text-right" : ""}`}>{children}</th>
);

/** Wide tables scroll inside their own box on a phone; the page itself never scrolls sideways. */
function Table({ head, children, wide }: { head: React.ReactNode; children: React.ReactNode; wide?: boolean }) {
  return (
    <div className="-mx-4 overflow-x-auto px-4">
      <table className={`w-full text-left text-sm ${wide ? "min-w-[34rem]" : ""}`}>
        <thead className="text-xs text-neutral-500">
          <tr className="border-b border-neutral-200 dark:border-neutral-800">{head}</tr>
        </thead>
        <tbody className="divide-y divide-neutral-200 align-top dark:divide-neutral-800">{children}</tbody>
      </table>
    </div>
  );
}

export function ReportView({ projectId }: { projectId: string }) {
  const [bundle, setBundle] = useState<ReportBundle | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0); // bumped by the Retry button
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => {
    const db = supabase();
    let cancelled = false;
    const load = () =>
      retry(() => loadReport(db, projectId))
        .then((b) => {
          if (cancelled) return;
          setBundle(b);
          setError(null);
        })
        .catch((e: Error) => {
          if (!cancelled) setError(e.message);
        });
    // Verdicts, final values, runs and applied lessons can land while the tab is open: reload once things settle.
    const soon = () => {
      clearTimeout(timer.current);
      timer.current = setTimeout(load, RELOAD_MS);
    };
    const project = `project_id=eq.${projectId}`;
    const channel = db
      .channel(`report-${projectId}`)
      .on("postgres_changes", { event: "*", schema: "public", table: "experiments", filter: project }, soon)
      .on("postgres_changes", { event: "*", schema: "public", table: "tasks", filter: project }, soon)
      .on("postgres_changes", { event: "INSERT", schema: "public", table: "events", filter: project }, soon)
      .on("postgres_changes", { event: "INSERT", schema: "public", table: "metrics" }, (p) => {
        if ((p.new as Metric).name.startsWith("final_")) soon();
      })
      .subscribe();
    load();
    return () => {
      cancelled = true;
      clearTimeout(timer.current);
      db.removeChannel(channel);
    };
  }, [projectId, attempt]);

  const retryButton = (
    <button type="button" onClick={() => (setError(null), setAttempt((n) => n + 1))} className="underline">
      Retry
    </button>
  );
  if (!bundle)
    return error ? (
      <p className="text-sm text-red-600">
        Could not load the report: {error} {retryButton}
      </p>
    ) : (
      <Muted>Loading report…</Muted>
    );
  const { data, hasPaper, project } = bundle;

  return (
    <section aria-labelledby="report-heading" className="space-y-8">
      {error && (
        <p className="text-sm text-red-600">
          Could not refresh the report: {error} {retryButton}
        </p>
      )}
      {isPrecomputed(project) && (
        <p className="rounded border border-amber-400 bg-amber-50 px-2 py-1 text-xs font-medium text-amber-800 dark:border-amber-700 dark:bg-amber-900/30 dark:text-amber-300">
          {PRECOMPUTED_LABEL}: loaded from stored results, not a live run.
        </p>
      )}

      <div className="space-y-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 id="report-heading" className="text-sm font-semibold">
            Claim authenticity
          </h2>
          <a
            href={`/api/projects/${projectId}/report.md`}
            download
            className="rounded border border-neutral-300 px-2 py-1 text-xs hover:bg-neutral-50 dark:border-neutral-700 dark:hover:bg-neutral-900"
          >
            Export Markdown
          </a>
        </div>
        <AuthenticityTiles a={data.authenticity} />
      </div>

      <div className="space-y-3">
        <h2 className="text-sm font-semibold">Claims vs ours</h2>
        <p className="text-xs text-neutral-500">{TEXT.claimsIntro}</p>
        {!hasPaper ? (
          <Muted>{TEXT.noPaper}</Muted>
        ) : data.rows.length === 0 ? (
          <Muted>{TEXT.noRows}</Muted>
        ) : (
          <ClaimsTable rows={data.rows} />
        )}
        <Comparisons graded={data.graded} />
      </div>

      <div className="space-y-2">
        {data.graded.map((g) => (
          <Collapsed key={g.experimentId} title="Grading detail" hint={g.experimentLabel}>
            <Graded g={g} />
          </Collapsed>
        ))}
        <Collapsed title="Why it differs" hint={whyHint(data)}>
          <WhyItDiffers data={data} />
        </Collapsed>
        <Collapsed title="Memory effect" hint={data.memory?.previous ? "vs the previous run" : "first run of this paper"}>
          <MemoryEffect memory={data.memory} />
        </Collapsed>
        {hasPaper && data.untested.length > 0 && (
          <Collapsed title="Other claims in the paper" hint={`${data.untested.length}, not run`}>
            <UntestedClaims claims={data.untested} />
          </Collapsed>
        )}
      </div>
    </section>
  );
}

const OursValues = ({ r }: { r: ReportRow }) =>
  r.ours.length === 0 ? (
    <span className="text-xs text-neutral-500">{TEXT.notMeasured}</span>
  ) : (
    <>
      {r.ours.map((p, i) => (
        <span key={p.log_line}>
          {i > 0 && ", "}
          <LogLink exp={r.experimentId} line={p.log_line}>
            {p.text}
          </LogLink>
        </span>
      ))}
    </>
  );

const Spread = ({ r }: { r: ReportRow }) => (
  <>
    {r.delta !== null && `Δ ${r.delta > 0 ? "+" : ""}${r.delta}`}
    {r.delta !== null && r.margin !== null && " "}
    {r.margin !== null && `± ${r.margin}`}
  </>
);

const VerdictCell = ({ r }: { r: ReportRow }) =>
  r.verdict ? (
    <>
      <Badge tone={verdictLabel(r.verdict.verdict).tone}>{r.verdict.label}</Badge>
      {r.explain && <p className="mt-1 break-words text-sm">{r.explain}</p>}
      {r.verdict.why && (
        <details className="mt-1 text-xs">
          <summary className="cursor-pointer text-neutral-500">Grading rule</summary>
          <p className="mt-1 break-words font-mono text-neutral-500">{r.verdict.why}</p>
        </details>
      )}
    </>
  ) : (
    <span className="text-xs text-neutral-500">{TEXT.notGraded}</span>
  );

/** Phones get one card per claim; wider screens get the table. Same data and links in both. */
function ClaimsTable({ rows }: { rows: ReportRow[] }) {
  return (
    <>
      <ul className="divide-y divide-neutral-200 sm:hidden dark:divide-neutral-800">
        {rows.map((r) => (
          <li key={`${r.experimentId}:${r.claim.id}`} className="space-y-1.5 py-3 text-sm">
            <div className="break-words font-medium">
              {r.claim.model} <span className="font-normal text-neutral-500">· {r.claim.metric}</span>
            </div>
            <div className="break-words text-xs text-neutral-500">
              <span className="font-mono">{r.claim.id}</span> · {r.claim.whose} · {r.experimentLabel}
            </div>
            <dl className="grid grid-cols-2 gap-2 tabular-nums">
              <div>
                <dt className="text-xs text-neutral-500">Paper</dt>
                <dd>
                  {r.claim.value} <span className="text-xs text-neutral-500">{r.claim.unit}</span>
                </dd>
              </div>
              <div>
                <dt className="text-xs text-neutral-500">Ours</dt>
                <dd>
                  <OursValues r={r} /> <span className="text-xs text-neutral-500"><Spread r={r} /></span>
                </dd>
              </div>
            </dl>
            <div>
              <VerdictCell r={r} />
            </div>
            <Quote claim={r.claim} />
          </li>
        ))}
      </ul>
      <div className="hidden sm:block">
        <ClaimsGrid rows={rows} />
      </div>
    </>
  );
}

function ClaimsGrid({ rows }: { rows: ReportRow[] }) {
  return (
    <Table
      head={
        <>
          <Th>Claim</Th>
          <Th right>Paper</Th>
          <Th right>Ours</Th>
          <Th>Verdict</Th>
        </>
      }
    >
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
            <OursValues r={r} />
            <div className="whitespace-nowrap text-xs text-neutral-500">
              <Spread r={r} />
            </div>
          </td>
          <td className="py-2">
            <VerdictCell r={r} />
          </td>
        </tr>
      ))}
    </Table>
  );
}

function Graded({ g }: { g: GradedExp }) {
  return (
    <div className="space-y-2">
      {g.rules && <p className="break-words text-xs text-neutral-500">Rules: {g.rules}</p>}
      {g.relative.length > 0 && (
        <Table
          head={
            <>
              <Th>Relative claim</Th>
              <Th right>Paper gap</Th>
              <Th right>Our gap</Th>
              <Th>Verdict</Th>
            </>
          }
        >
          {g.relative.map((r) => (
            <tr key={r.claim}>
              <td className="py-2 pr-2 font-mono text-xs">{r.claim}</td>
              <td className="py-2 pr-2 text-right tabular-nums">{r.paper_gap ?? "—"}</td>
              <td className="py-2 pr-2 text-right tabular-nums">
                {r.ours_gap ?? "—"}
                {r.lines.length > 0 && (
                  <div className="whitespace-nowrap text-xs text-neutral-500">
                    from{" "}
                    {r.lines.map((l, i) => (
                      <span key={l.line}>
                        {i > 0 && ", "}
                        <LogLink exp={l.exp} line={l.line}>
                          L{l.line}
                        </LogLink>
                      </span>
                    ))}
                  </div>
                )}
              </td>
              <td className="py-2">
                <Badge tone={verdictLabel(r.verdict).tone}>{r.label}</Badge>
              </td>
            </tr>
          ))}
        </Table>
      )}
      {g.explanation?.accepted && g.explanation.text ? (
        <p className="whitespace-pre-wrap break-words text-sm">{g.explanation.text}</p>
      ) : (
        g.explanation && (
          <p className="text-xs text-neutral-500">
            {TEXT.explanationHidden}: {g.explanation.problems.join("; ") || "none written"}.
          </p>
        )
      )}
      {g.marginNote && <p className="break-words text-xs text-neutral-500">Note: {g.marginNote}</p>}
    </div>
  );
}

function WhyItDiffers({ data }: { data: ReportData }) {
  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <h3 className="text-sm font-medium">Settings diff</h3>
        <p className="text-xs text-neutral-500">{TEXT.settingsIntro}</p>
        {data.settingsDiff ? <SettingsTable diff={data.settingsDiff} /> : <Muted>{TEXT.noSettings}</Muted>}
      </div>
      <div className="space-y-2">
        <h3 className="text-sm font-medium">Branch effects</h3>
        <p className="text-xs text-neutral-500">{TEXT.branchesIntro}</p>
        {data.branches.length ? <BranchTable rows={data.branches} /> : <Muted>{TEXT.noBranches}</Muted>}
      </div>
    </div>
  );
}

function SettingsTable({ diff }: { diff: NonNullable<ReportData["settingsDiff"]> }) {
  const { rows, experimentId, configLogLine } = diff;
  return (
    <Table
      wide
      head={
        <>
          <Th>Setting</Th>
          <Th>Paper</Th>
          <Th>Ours</Th>
          <Th>Label</Th>
        </>
      }
    >
      {rows.map((s, i) => (
        <tr key={`${s.key}:${s.config_key}:${i}`}>
          <td className="py-2 pr-2 font-mono text-xs">
            {s.key}
            {s.applies_to && <div className="text-neutral-500">for {s.applies_to}</div>}
            {s.config_key && <div className="text-neutral-500">config {s.config_key}</div>}
          </td>
          <td className="break-words py-2 pr-2">
            {s.paper ?? <span className="text-neutral-500">not stated</span>}
            {s.quote && (
              <details className="mt-1 text-xs">
                <summary className="cursor-pointer text-neutral-500">Quote, p. {s.page ?? "?"}</summary>
                <blockquote className="mt-1 border-l-2 border-neutral-300 pl-2 text-neutral-600 dark:border-neutral-700 dark:text-neutral-400">
                  {s.quote}
                </blockquote>
              </details>
            )}
          </td>
          <td className="break-words py-2 pr-2">
            {s.ours === null ? (
              "—"
            ) : configLogLine !== null ? (
              <LogLink exp={experimentId} line={configLogLine}>
                {s.ours}
              </LogLink>
            ) : (
              s.ours
            )}
          </td>
          <td className="py-2">
            <Badge tone={s.label ? DIFF_TONE[s.label] : "neutral"}>{s.label ? DIFF_TEXT[s.label] : s.rawLabel}</Badge>
            {s.reason && <p className="mt-1 break-words text-xs text-neutral-500">{s.reason}</p>}
          </td>
        </tr>
      ))}
    </Table>
  );
}

function BranchTable({ rows }: { rows: BranchEffect[] }) {
  return (
    <Table
      wide
      head={
        <>
          <Th>Branch</Th>
          <Th>Metric</Th>
          <Th right>Parent</Th>
          <Th right>Branch</Th>
          <Th right>Effect</Th>
          <Th>Status</Th>
        </>
      }
    >
      {rows.map((b) => (
        <tr key={`${b.branchId}:${b.metric}`}>
          <td className="py-2 pr-2">
            <span className="font-mono text-xs">Δ {b.key}</span>
            <div className="break-words text-xs text-neutral-500">{b.branchLabel}</div>
          </td>
          <td className="break-all py-2 pr-2 font-mono text-xs">{b.metric || "—"}</td>
          <td className="py-2 pr-2 text-right tabular-nums">
            {b.parent ? (
              <LogLink exp={b.parentId} line={b.parent.log_line}>
                {b.parent.text}
              </LogLink>
            ) : (
              "—"
            )}
          </td>
          <td className="py-2 pr-2 text-right tabular-nums">
            {b.branch ? (
              <LogLink exp={b.branchId} line={b.branch.log_line}>
                {b.branch.text}
              </LogLink>
            ) : (
              "—"
            )}
          </td>
          <td className="py-2 pr-2 text-right font-medium tabular-nums">{b.effect ?? "—"}</td>
          <td className="py-2 text-xs">
            {b.status}
            {b.prunedReason && <div className="break-words text-neutral-500">{b.prunedReason}</div>}
          </td>
        </tr>
      ))}
    </Table>
  );
}

function MemoryEffect({ memory }: { memory: ReportData["memory"] }) {
  const prev = memory?.previous;
  return (
    <div className="space-y-2">
      <p className="text-xs text-neutral-500">{TEXT.memoryIntro}</p>
      {!memory || !prev ? (
        <Muted>{TEXT.noMemory}</Muted>
      ) : (
        <Table
          head={
            <>
              <Th />
              <Th right>This run</Th>
              <Th right>Previous run</Th>
            </>
          }
        >
          {memoryRows(memory.current).map(([k, v], i) => (
            <tr key={k}>
              <td className="py-2 pr-2">{k}</td>
              <td className="py-2 pr-2 text-right tabular-nums">{v}</td>
              <td className="py-2 text-right tabular-nums">{memoryRows(prev)[i][1]}</td>
            </tr>
          ))}
        </Table>
      )}
      {memory && memory.current.lessonsApplied.length > 0 && (
        <ul className="list-disc space-y-1 pl-5 text-sm">
          {memory.current.lessonsApplied.map((e) => (
            <li key={e.id} className="break-words">
              Lesson applied: {e.message}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** A closed section: its title and a one-line hint stay visible, the detail opens on tap. */
function Collapsed({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <details className="rounded-lg border border-neutral-200 dark:border-neutral-800">
      <summary className="flex min-h-11 cursor-pointer flex-wrap items-center gap-x-2 px-3 py-2">
        <span className="text-sm font-semibold">{title}</span>
        {hint && <span className="min-w-0 break-words text-xs text-neutral-500">{hint}</span>}
      </summary>
      <div className="border-t border-neutral-200 p-3 dark:border-neutral-800">{children}</div>
    </details>
  );
}

const whyHint = (d: ReportData) =>
  [
    d.settingsDiff ? `${d.settingsDiff.rows.length} settings compared` : "settings diff not computed yet",
    d.branches.length ? `${new Set(d.branches.map((b) => b.branchId)).size} what-if branches` : "no what-if branches yet",
  ].join(" · ");

/** Relative claims ("c9 beats c8") with their verdict and why, next to the claims they compare. */
function Comparisons({ graded }: { graded: GradedExp[] }) {
  const rows = graded.flatMap((g) => g.relative.map((r) => ({ ...r, exp: g.experimentId })));
  if (!rows.length) return null;
  return (
    <ul className="divide-y divide-neutral-200 border-t border-neutral-200 text-sm dark:divide-neutral-800 dark:border-neutral-800">
      {rows.map((r) => (
        <li key={`${r.exp}:${r.claim}`} className="space-y-1 py-3">
          <div className="font-medium">
            Comparison <span className="font-mono text-xs font-normal text-neutral-500">{r.claim}</span>
          </div>
          <Badge tone={verdictLabel(r.verdict).tone}>{r.label}</Badge>
          {r.explain && <p className="break-words">{r.explain}</p>}
        </li>
      ))}
    </ul>
  );
}

function AuthenticityTiles({ a }: { a: Authenticity }) {
  return (
    <>
      {a.total > 0 && (
        <ul className="grid grid-cols-3 gap-2 sm:grid-cols-4">
          {a.rows.map((r) => (
            <li key={r.verdict} className="rounded-lg border border-neutral-200 p-2 dark:border-neutral-800">
              <p className="text-2xl font-semibold tabular-nums">{r.count}</p>
              <Badge tone={r.tone}>{r.label}</Badge>
              {r.seeds && <p className="mt-1 text-xs text-neutral-500">({r.seeds})</p>}
            </li>
          ))}
        </ul>
      )}
      <p className="text-sm">{authenticitySummary(a)}</p>
      <p className="text-xs text-neutral-500">{TEXT.authenticityIntro}</p>
    </>
  );
}

function Badge({ tone, children }: { tone: Tone; children: React.ReactNode }) {
  return (
    <span className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs font-medium ${TONE[tone]}`}>
      <span aria-hidden>{ICON[tone]}</span>
      {children}
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
      <ul className="divide-y divide-neutral-200 text-sm dark:divide-neutral-800">
        {claims.map((c) => (
          <li key={c.id} className="py-2">
            <div className="flex flex-wrap items-baseline gap-x-2">
              <span className="font-mono text-xs text-neutral-500">{c.id}</span>
              <span className="break-words">
                {c.model} · {c.metric}
              </span>
              <span className="font-medium tabular-nums">
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
