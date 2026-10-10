// Home-list badge for projects that are not live runs of the lab (SPEC §14: never pass them off as live).

export type ProjectBadge = { label: string; title: string; className: string };

const PILL = "rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide";

const BADGES: Record<string, ProjectBadge> = {
  precomputed: {
    label: "Precomputed",
    title: "Loaded from the Round 0 audit's saved results, not run by the lab",
    className: `${PILL} border-violet-400 bg-violet-50 text-violet-800 dark:bg-violet-950/40 dark:text-violet-300`,
  },
  reference: {
    label: "Reference",
    title: "The paper's reference script run by hand (papers/), the yardstick for the lab's runs",
    className: `${PILL} border-sky-400 bg-sky-50 text-sky-800 dark:bg-sky-950/40 dark:text-sky-300`,
  },
};

export function projectBadge(status: string): ProjectBadge | null {
  return BADGES[status] ?? null;
}
