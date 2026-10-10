// The project's stage strip: Reading paper → … → Report, each done / running / failed / not started, derived by code
// from the project's tasks (capability + status). When a stage has no task (e.g. the reference run was done by
// scripts), stored results count as evidence, and a finished later stage means the earlier ones were done.

import { capabilityLabel } from "../../../components/live/labels.ts";

export type StageState = "done" | "running" | "failed" | "not started";
export type Stage = {
  id: string;
  label: string;
  state: StageState;
  /** Plain-language reason, for a failed stage. */
  reason: string | null;
  /** The step that failed, when the stage has more than one ("Set up environment" in Writing code). */
  failedStep: string | null;
  /** The raw error behind the reason. */
  detail: string | null;
  /** How a done stage was known when no task of it finished. */
  note: string | null;
  /** Done without a finished task of its own: from stored results, or because a later stage finished. */
  inferred: "results" | "later" | null;
};

export type StageInput = {
  projectStatus: string;
  tasks: {
    id: string;
    capability: string;
    status: string;
    created_at: string;
    scale: string | null; // input.scale for run tasks
    whatif: string | null; // input.whatif_of: what-if tasks are not main stages
    error: string | null; // output.error
  }[];
  /** task_failed events: their reason is the error when the task output has none. */
  failures: { task_id: string | null; reason: string }[];
  claims: number; // papers.claims for this project
  sortedClaims: number; // claims tagged runnable / not_runnable (ANY-1)
  experiments: { status: string; scale: string | null; graded: boolean; branch: boolean }[];
};

type Def = {
  id: string;
  label: string;
  match: (t: StageInput["tasks"][number]) => boolean;
  evidence: (i: StageInput) => string | null;
  /** The step whose finishing finishes the stage (default: any of its steps). */
  finishes?: (t: StageInput["tasks"][number]) => boolean;
};

const caps = (...c: string[]) => (t: { capability: string }) => c.includes(t.capability);
const mainExps = (i: StageInput) => i.experiments.filter((e) => !e.branch);
const FINAL = new Set(["reference", "precomputed", "done"]);

const STAGES: Def[] = [
  {
    id: "reading",
    label: "Reading paper",
    match: caps("read_paper", "extract_claims", "extract_settings"),
    evidence: (i) => (i.claims > 0 ? `${i.claims} claims stored from the paper` : null),
  },
  {
    id: "sorting",
    label: "Sorting claims",
    // No task of its own: ANY-1's triage runs inside read_paper and tags papers.claims[i].runnable.
    match: () => false,
    evidence: (i) => (i.sortedClaims > 0 ? `${i.sortedClaims} claims tagged runnable or not` : null),
  },
  { id: "designing", label: "Designing", match: caps("design_experiment"), evidence: () => null },
  { id: "code", label: "Writing code", match: caps("write_code", "setup_env"), evidence: () => null },
  {
    id: "smoke",
    label: "Smoke test",
    match: (t) => t.capability === "run" && t.scale === "smoke",
    evidence: (i) => (mainExps(i).some((e) => e.status === "done" && e.scale === "smoke") ? "a smoke run finished" : null),
  },
  {
    id: "training",
    label: "Training",
    // A run without a scale is a full run (the reference runs predate input.scale).
    match: (t) => t.capability === "budget" || (t.capability === "run" && t.scale !== "smoke"),
    // The budget step alone does not finish training: the full run must.
    finishes: (t) => t.capability === "run",
    evidence: (i) =>
      mainExps(i).some((e) => e.status === "done" && e.scale !== "smoke") ? "a full run finished" : null,
  },
  {
    id: "grading",
    label: "Grading",
    match: caps("compare", "explain_diff"),
    evidence: (i) => (mainExps(i).some((e) => e.graded) ? "the Analyst's verdicts are stored" : null),
  },
  {
    id: "report",
    label: "Report",
    match: caps("write_report", "write_notes"),
    evidence: (i) =>
      FINAL.has(i.projectStatus) && mainExps(i).some((e) => e.graded) ? "the report is built from the stored verdicts" : null,
  },
];

const ACTIVE = new Set(["queued", "running", "awaiting_approval"]);
const FAILED = new Set(["failed", "rejected"]);

const RULES: [RegExp, string][] = [
  [/429|resource_exhausted|quota|rate.?limit/i, "The AI service's usage limit was reached, so the agent could not answer."],
  [/max_tokens|token.{0,20}(cap|limit|allowance)|output cap/i, "The agent used up its token allowance before it could answer."],
  [/timed? ?out|timeout/i, "The step ran out of time."],
  [/no space left|out of memory|memoryerror|killed/i, "The machine ran out of memory or disk."],
  [/code check/i, "The written code failed its automatic check."],
  [/\b(KeyError|TypeError|ValueError|AttributeError|IndexError|NameError|Traceback)\b/, "A bug in the lab's own code stopped this step."],
];

/** One short sentence a researcher can read; the raw error stays in `detail`. */
export function plainReason(raw: string | null | undefined): string {
  const text = (raw ?? "").trim();
  if (!text) return "The step failed without recording why.";
  for (const [re, plain] of RULES) if (re.test(text)) return plain;
  // Unknown: the first clause, capitalised and short (stage reasons like "no public data: …" are already plain).
  const first = text.split(/(?<=[.!?])\s|\n/)[0].slice(0, 140).replace(/[.\s]+$/, "");
  if (!first) return "The step failed without recording why.";
  return `${first[0].toUpperCase()}${first.slice(1)}.`;
}

export function deriveStages(input: StageInput): Stage[] {
  const tasks = input.tasks.filter((t) => !t.whatif);
  const failedReason = new Map(input.failures.flatMap((f) => (f.task_id ? [[f.task_id, f.reason] as const] : [])));

  const stages: Stage[] = STAGES.map((d) => {
    const mine = tasks.filter(d.match).sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at));
    const base = { id: d.id, label: d.label, reason: null, failedStep: null, detail: null, note: null, inferred: null };
    // A stage can have several steps (write_code then setup_env; budget then the full run). Each step is done if
    // one of its tasks finished; the stage is done when every step it has started is done and its finishing step is.
    const steps = new Map<string, typeof mine>();
    for (const t of mine) steps.set(t.capability, [...(steps.get(t.capability) ?? []), t]);
    const stepDone = (ts: typeof mine) => ts.some((t) => t.status === "done");
    const open = [...steps.values()].filter((ts) => !stepDone(ts));
    if (mine.some((t) => ACTIVE.has(t.status) && !stepDone(steps.get(t.capability)!))) return { ...base, state: "running" };
    const finished = mine.some((t) => t.status === "done" && (d.finishes?.(t) ?? true));
    if (!open.length && finished) return { ...base, state: "done" };
    const evidence = d.evidence(input);
    if (evidence) return { ...base, state: "done", note: evidence, inferred: "results" };
    const failed = open.flat().filter((t) => FAILED.has(t.status));
    if (!failed.length && mine.some((t) => t.status === "done")) return { ...base, state: "running" }; // next step pending
    if (failed.length) {
      const last = failed[0];
      const raw = last.error ?? failedReason.get(last.id) ?? (last.status === "rejected" ? "rejected by a researcher" : null);
      const tries = failed.length > 1 ? ` Tried ${failed.length} times.` : "";
      const failedStep = steps.size > 1 ? capabilityLabel(last.capability) : null;
      return { ...base, state: "failed", reason: plainReason(raw) + tries, failedStep, detail: raw };
    }
    return { ...base, state: "not started" };
  });

  // A later stage finished, so every earlier one was done (perhaps outside the task queue, or after a failed try).
  const lastDone = stages.map((s) => s.state).lastIndexOf("done");
  for (let i = 0; i < lastDone; i++)
    if (stages[i].state !== "done" && stages[i].state !== "running") stages[i] = {
        ...stages[i],
        state: "done",
        reason: null,
        failedStep: null,
        detail: null,
        note: "a later stage finished with its result",
        inferred: "later",
      };
  return stages;
}
