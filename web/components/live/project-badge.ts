// Home-list badge: finished live runs, and projects that are not live runs of the lab (SPEC §14: never pass those
// off as live).

export type ProjectBadge = { label: string; title: string; className: string };

const PILL = "rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide";

const BADGES: Record<string, ProjectBadge> = {
  done: {
    label: "Live run",
    title: "Run end to end by the agents on this lab's machines; every number comes from its logs",
    className: `${PILL} border-green-500 bg-green-50 text-green-800 dark:bg-green-950/40 dark:text-green-300`,
  },
  precomputed: {
    label: "Precomputed",
    title: "Loaded from the Round 0 audit's saved results, not run by the lab",
    className: `${PILL} border-violet-400 bg-violet-50 text-violet-800 dark:bg-violet-950/40 dark:text-violet-300`,
  },
  reference: {
    label: "Reference run",
    title: "The paper's reference script run by hand (papers/), the yardstick for the lab's runs",
    className: `${PILL} border-sky-400 bg-sky-50 text-sky-800 dark:bg-sky-950/40 dark:text-sky-300`,
  },
};

export function projectBadge(status: string): ProjectBadge | null {
  return BADGES[status] ?? null;
}
