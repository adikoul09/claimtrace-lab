// Plain-language labels for codes stored in the DB (capabilities, statuses, budgets), so the UI shows no raw codes.

/** "claims_extracted" → "Claims extracted". */
export function humanize(code: string): string {
  const s = code.replace(/_/g, " ").trim();
  return s ? s[0].toUpperCase() + s.slice(1) : s;
}

const WORD: Record<string, string> = {
  cpu: "CPU",
  llm: "LLM",
  envbuilder: "env builder",
  whatif: "what-if",
  requeued: "re-queued",
};
const words = (code: string, sep: RegExp) => humanize(code.split(sep).map((w) => WORD[w] ?? w).join(" "));

/** "reader-v13" (version 13) → "Reader · version 13". */
export function agentLabel(a: { name: string; version: number }): string {
  return `${words(a.name.replace(/-v\d+$/, ""), /[-_]/)} · version ${a.version}`;
}

/** "task_requeued" → "Task re-queued"; "llm_daily_cap" → "LLM daily cap". */
export function eventTypeLabel(type: string): string {
  return words(type, /_/);
}

const CAPABILITY: Record<string, string> = {
  plan: "Plan",
  read_paper: "Read the paper",
  extract_claims: "Extract claims",
  extract_settings: "Extract settings",
  design_experiment: "Design the experiment",
  budget: "Set the budget",
  write_code: "Write code",
  setup_env: "Set up environment",
  run: "Run",
  debug: "Debug",
  compare: "Compare results",
  explain_diff: "Explain the difference",
  design_whatif: "Design what-if",
  write_report: "Write the report",
  write_notes: "Write notes",
};

export function capabilityLabel(c: string): string {
  return CAPABILITY[c] ?? humanize(c);
}

export function statusLabel(s: string): string {
  return humanize(s);
}

/** tasks.input.budget as people read it: "up to 5 CPU-min · 20,000 tokens". */
export function budgetLabel(b: Record<string, unknown>): string | null {
  const parts: string[] = [];
  for (const [k, v] of Object.entries(b)) {
    if (k === "max_cpu_s" && typeof v === "number") parts.push(`up to ${+(v / 60).toFixed(1)} CPU-min`);
    else if (k === "max_tokens" && typeof v === "number")
      parts.push(v === 0 ? "no AI tokens" : `${v.toLocaleString("en-US")} tokens`);
    else parts.push(`${humanize(k).toLowerCase()} ${String(v)}`);
  }
  return parts.length ? parts.join(" · ") : null;
}

// Home list: what a visitor should see first (the reference run, live runs, precomputed audits) vs. everything else.
const OTHER = new Set(["test", "plan_failed", "blocked", "stopped"]);

/** Main list (finished live runs first, then the reference run) and "Other runs" (test and failed), else in order. */
export function groupProjects<P extends { status: string }>(projects: P[]): { main: P[]; other: P[] } {
  const rank = (p: P) => (p.status === "done" ? 0 : p.status === "reference" ? 1 : 2);
  return {
    main: projects.filter((p) => !OTHER.has(p.status)).sort((a, b) => rank(a) - rank(b)),
    other: projects.filter((p) => OTHER.has(p.status)),
  };
}

const PROJECT_STATUS: Record<string, string> = {
  new: "Starting",
  planning: "Planning",
  running: "Running",
  done: "Finished",
  blocked: "Stopped: needs attention",
  plan_failed: "Stopped: the plan failed",
  stopped: "Stopped by a researcher",
  test: "Test run",
  reference: "Reference run",
  precomputed: "Precomputed",
};

export function projectStatusLabel(s: string): string {
  return PROJECT_STATUS[s] ?? humanize(s);
}

export type PaperTitles = { byProject: Record<string, string>; byArxiv: Record<string, string> };

/** The paper's title (from papers) for real runs; test runs keep their own name, which says what was tested. */
export function projectTitle(
  p: { id: string; title: string; arxiv_id: string | null; status: string },
  titles: PaperTitles,
): string {
  if (p.status === "test") return p.title;
  return titles.byProject[p.id] ?? (p.arxiv_id ? titles.byArxiv[p.arxiv_id] : undefined) ?? p.title;
}
