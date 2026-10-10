// Plain-language labels for codes stored in the DB (capabilities, statuses, budgets), so the UI shows no raw codes.

/** "claims_extracted" → "Claims extracted". */
export function humanize(code: string): string {
  const s = code.replace(/_/g, " ").trim();
  return s ? s[0].toUpperCase() + s.slice(1) : s;
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
    else if (k === "max_tokens" && typeof v === "number") parts.push(`${v.toLocaleString("en-US")} tokens`);
    else parts.push(`${humanize(k).toLowerCase()} ${String(v)}`);
  }
  return parts.length ? parts.join(" · ") : null;
}

// Home list: what a visitor should see first (live runs, the reference run, precomputed audits) vs. everything else.
const OTHER = new Set(["test", "plan_failed", "blocked", "stopped"]);

/** Splits projects into the main list and "Other runs" (test and failed), keeping the given order in each. */
export function groupProjects<P extends { status: string }>(projects: P[]): { main: P[]; other: P[] } {
  return {
    main: projects.filter((p) => !OTHER.has(p.status)),
    other: projects.filter((p) => OTHER.has(p.status)),
  };
}
