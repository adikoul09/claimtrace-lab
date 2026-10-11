import type { AgentOrigin, AgentStatus } from "@/lib/types";
import type { EdgeKind } from "./lineage";

export const STATUS_STYLE: Record<AgentStatus, string> = {
  active: "bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300",
  retired: "bg-neutral-200 text-neutral-700 dark:bg-neutral-800 dark:text-neutral-300",
  merged: "bg-slate-200 text-slate-700 dark:bg-slate-800 dark:text-slate-300", // purple is reserved for spawned
};

export const ORIGIN_STYLE: Record<AgentOrigin, string> = {
  seed: "border-neutral-300 text-neutral-600 dark:border-neutral-700 dark:text-neutral-400",
  spawned: "border-purple-400 text-purple-700 dark:border-purple-500 dark:text-purple-300", // brand accent
  refined: "border-sky-400 text-sky-700 dark:border-sky-600 dark:text-sky-400",
};

/** Edge colours (SVG strokes), shared by the graph and its legend. */
export const EDGE_STYLE: Record<EdgeKind, { stroke: string; dash?: string; label: string }> = {
  parent: { stroke: "#0ea5e9", label: "refined from" },
  spawned: { stroke: "#a855f7", dash: "6 4", label: "spawned by" },
  merged: { stroke: "#94a3b8", dash: "2 3", label: "merged into" },
};
