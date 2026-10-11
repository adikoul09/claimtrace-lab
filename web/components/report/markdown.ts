// The Report as Markdown (SPEC §10, §12). Built from the same ReportData the screen renders, with the same words,
// so the export matches the screen. Every number of ours links to its log line.
import { formatDuration } from "../exp/experiments.ts";
import { smokeLabel, splitClaimRows, type Authenticity, type ClaimTriage, type ReportData, type ReportRow, type RunStats } from "./report.ts";

/** Wording shared by the screen and the export. */
export const TEXT = {
  authenticityIntro:
    "Counted by code from the Analyst's verdicts: each claim once, from the latest reproduction run that graded it (what-if branches excluded).",
  noAuthenticity: "No claim has been graded yet.",
  claimsIntro:
    "Verdicts are computed by code (the Analyst) against the margin declared before the run. Every number of ours links to the log line that printed it.",
  noPaper: "No paper has been read for this project yet.",
  noRows: "No run has targeted a claim yet. Rows appear when a reproduction maps its models to claims.",
  planned: "Smoke checks and planned runs",
  plannedIntro:
    "Smoke checks are short runs that only prove the code works, so they are not graded; planned runs get a value and a verdict once they run.",
  noneGraded: "No claim has a value yet.",
  notGraded: "not graded yet",
  notMeasured: "not measured yet",
  settingsIntro: "Paper value vs ours for each setting, labelled scale (budget), omission (the paper does not say), difference or same.",
  noSettings: "Settings diff not computed yet.",
  branchesIntro: "Each what-if branch changes one setting; the effect is branch minus parent on each final value both runs logged.",
  noBranches: "No what-if branches yet.",
  memoryIntro: "Run 2 of the same paper against run 1: retries before the first successful run, time to the first result, and LLM tokens.",
  noMemory: "No finished earlier run to compare yet.",
  unfinishedPrevious: "Compared with the last earlier run instead, which did not finish.",
  explanationHidden: "Explanation not shown",
  precomputed: "Precomputed — Round 0 audit",
};

export const DIFF_TEXT: Record<string, string> = {
  scale: "scale reduction (budget)",
  omission: "paper omission",
  difference: "difference",
  same: "same",
};

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;
/** "3 graded claims (2 results, 1 comparison) from B0 full reference v2." */
export const authenticitySummary = (a: Authenticity) =>
  a.total === 0
    ? TEXT.noAuthenticity
    : `${plural(a.total, "graded claim", "graded claims")} (${plural(a.claims, "result", "results")}, ${plural(
        a.comparisons,
        "comparison",
        "comparisons",
      )}) from ${a.sources.map((s) => s.label).join(", ")}.`;
/** "2 (1 seed)" */
export const countText = (r: Authenticity["rows"][number]) => `${r.count}${r.seeds ? ` (${r.seeds})` : ""}`;

/** "18 can be checked on a laptop · 55 can't" (null until the claims carry ANY-1's runnable tags). */
export const triageSummary = (t: ClaimTriage) =>
  t.runnable + t.notRunnable === 0
    ? null
    : [`${t.runnable} can be checked on a laptop`, `${t.notRunnable} can't`, t.unsorted ? `${t.unsorted} not sorted yet` : null]
        .filter(Boolean)
        .join(" · ");
/** "36 no public data · 19 dataset too big" */
export const triageReasons = (t: ClaimTriage) =>
  t.reasons.length ? t.reasons.map((r) => `${r.count} ${r.reason}`).join(" · ") : null;

/** "vs previous run", "vs previous run (stopped at Designing)", or that there is none. */
export const memoryHint = (m: ReportData["memory"]) =>
  !m?.previous ? TEXT.noMemory : m.previousStop ? `vs previous run (${m.previousStop})` : "vs previous run";

export const memoryRows = (s: RunStats) => [
  [
    "Retries before the first successful run",
    s.failedBeforeFirstSuccess === null ? `no successful run yet (${s.failedRuns} failed)` : String(s.failedBeforeFirstSuccess),
  ],
  ["Time to the first result", s.secondsToFirstResult === null ? "—" : formatDuration(s.secondsToFirstResult)],
  ["LLM tokens", `${s.llmTokens.toLocaleString("en-US")} (${s.llmCalls} calls)`],
  ["Lessons applied", String(s.lessonsApplied.length)],
];

const cell = (s: string) => s.replace(/\|/g, "\\|").replace(/\s*\n\s*/g, " ");
const row = (cells: string[]) => `| ${cells.map(cell).join(" | ")} |`;
const table = (head: string[], body: string[][]) =>
  [row(head), row(head.map(() => "---")), ...body.map(row)].join("\n");

export function reportMarkdown(
  project: { id: string; title: string; arxiv_id: string | null; precomputed?: boolean },
  d: ReportData,
  base: string,
  hasPaper = true,
): string {
  const log = (exp: string, line: number, text: string) => `[${text}](${base}/logs/${exp}#L${line})`;
  const out: string[] = [`# Report: ${project.title}`];
  out.push(
    [project.arxiv_id ? `arXiv ${project.arxiv_id}` : null, `project ${project.id}`, project.precomputed ? TEXT.precomputed : null]
      .filter(Boolean)
      .join(" · "),
  );

  out.push("## Claim authenticity", TEXT.authenticityIntro, authenticitySummary(d.authenticity));
  if (d.authenticity.total)
    out.push(table(["Verdict", "Claims"], d.authenticity.rows.map((r) => [r.label, countText(r)])));

  const claimsTable = (rows: ReportRow[]) =>
    table(
      ["Claim", "Paper", "Ours", "Verdict"],
      rows.map((r) => [
        `${r.claim.id} ${r.claim.model} · ${r.claim.metric} (${r.claim.whose}) — ${r.experimentLabel}`,
        `${r.claim.value} ${r.claim.unit} (p. ${r.claim.page ?? "?"})`,
        (r.ours.length ? r.ours.map((p) => log(r.experimentId, p.log_line, p.text)).join(", ") : TEXT.notMeasured) +
          (r.delta !== null ? ` (Δ ${r.delta > 0 ? "+" : ""}${r.delta})` : "") +
          (r.margin !== null ? ` ± ${r.margin}` : ""),
        r.verdict ? (r.explain ?? r.verdict.label + (r.verdict.why ? `: ${r.verdict.why}` : "")) : (smokeLabel(r) ?? TEXT.notGraded),
      ]),
    );

  out.push("## Claims vs ours", TEXT.claimsIntro);
  if (!hasPaper) out.push(TEXT.noPaper);
  else if (!d.rows.length) out.push(TEXT.noRows);
  else {
    const { shown, planned } = splitClaimRows(d.rows);
    out.push(shown.length ? claimsTable(shown) : TEXT.noneGraded);
    if (planned.length) out.push(`### ${TEXT.planned} (${planned.length})`, TEXT.plannedIntro, claimsTable(planned));
  }

  for (const g of d.graded) {
    out.push(`### ${g.experimentLabel}`);
    if (g.relative.length)
      out.push(
        table(
          ["Relative claim", "Paper gap", "Our gap", "Verdict"],
          g.relative.map((r) => [
            r.claim,
            r.paper_gap === null ? "—" : String(r.paper_gap),
            (r.ours_gap === null ? "—" : String(r.ours_gap)) +
              (r.lines.length ? ` (from ${r.lines.map((l) => log(l.exp, l.line, `L${l.line}`)).join(", ")})` : ""),
            r.explain ?? r.label,
          ]),
        ),
      );
    if (g.explanation?.accepted && g.explanation.text) out.push(g.explanation.text);
    else if (g.explanation) out.push(`${TEXT.explanationHidden}: ${g.explanation.problems.join("; ") || "none written"}.`);
    if (g.marginNote) out.push(`Note: ${g.marginNote}`);
  }

  out.push("## Why it differs", "### Settings diff", TEXT.settingsIntro);
  if (!d.settingsDiff) out.push(TEXT.noSettings);
  else
    out.push(
      table(
        ["Setting", "Paper", "Ours", "Label", "Source"],
        d.settingsDiff.rows.map((s) => [
          s.key + (s.applies_to ? ` (for ${s.applies_to})` : ""),
          s.paper ?? "not stated",
          s.ours === null
            ? "—"
            : d.settingsDiff!.configLogLine !== null
              ? log(d.settingsDiff!.experimentId, d.settingsDiff!.configLogLine, s.ours)
              : s.ours,
          (s.label ? DIFF_TEXT[s.label] : s.rawLabel) + (s.reason ? `: ${s.reason}` : ""),
          (s.quote ? `"${s.quote}" (p. ${s.page ?? "?"})` : "") + (s.config_key ? ` · config ${s.config_key}` : ""),
        ]),
      ),
    );

  out.push("### Branch effects", TEXT.branchesIntro);
  if (!d.branches.length) out.push(TEXT.noBranches);
  else
    out.push(
      table(
        ["Branch", "Metric", "Parent", "Branch value", "Effect", "Status"],
        d.branches.map((b) => [
          `Δ ${b.key} — ${b.branchLabel}`,
          b.metric || "—",
          b.parent ? log(b.parentId, b.parent.log_line, b.parent.text) : "—",
          b.branch ? log(b.branchId, b.branch.log_line, b.branch.text) : "—",
          b.effect ?? "—",
          b.status + (b.prunedReason ? `: ${b.prunedReason}` : ""),
        ]),
      ),
    );

  out.push("## Memory effect", TEXT.memoryIntro);
  if (!d.memory?.previous) out.push(TEXT.noMemory);
  else {
    if (d.memory.previousStop) out.push(`${TEXT.noMemory} ${TEXT.unfinishedPrevious} (${d.memory.previousStop})`);
    const cur = memoryRows(d.memory.current);
    const prev = memoryRows(d.memory.previous);
    out.push(table(["", "This run", `Previous run (${d.memory.previous.title})`], cur.map(([k, v], i) => [k, v, prev[i][1]])));
  }
  if (d.memory?.current.lessonsApplied.length)
    out.push(d.memory.current.lessonsApplied.map((e) => `- Lesson applied: ${e.message}`).join("\n"));

  if (hasPaper && d.triage.total) {
    out.push(`## All claims in the paper (${d.triage.total})`);
    for (const line of [triageSummary(d.triage), triageReasons(d.triage)]) if (line) out.push(line);
    out.push(
      d.triage.ordered
        .map(
          (c) =>
            `- ${c.id} ${c.model} · ${c.metric}: ${c.value} ${c.unit} (p. ${c.page ?? "?"})${c.valid ? "" : " — failed code check"}` +
            (c.runnable ? ` — ${c.runnable.runnable ? "runnable" : "not runnable"}${c.runnable.reason ? `: ${c.runnable.reason}` : ""}` : ""),
        )
        .join("\n"),
    );
  }
  return out.join("\n\n") + "\n";
}
