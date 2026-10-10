// Pure helpers for the Team lineage graph and scoreboard.

/** Same window as ROLLING_WINDOW in lab/controller/rules.py (SPEC §4.2). */
export const ROLLING_WINDOW = 3;
/** Graph columns per row before a generation wraps. */
const MAX_COLS = 4;

type LineageAgent = {
  id: string;
  parent_id: string | null;
  merged_into: string | null;
  created_by_task: string | null;
  created_at: string;
};
type RewardRow = { agent_id: string; reward: number; ts: string };

export type EdgeKind = "parent" | "merged" | "spawned";
export type LineageEdge = { id: string; source: string; target: string; kind: EdgeKind };

/**
 * parent → refined child; merged agent → the agent it merged into;
 * agent of the triggering task → spawned agent. taskAgent maps task id → that task's agent_id.
 * Edges whose ends are not both loaded are skipped.
 */
export function lineageEdges(
  agents: LineageAgent[],
  taskAgent: Record<string, string | null>,
): LineageEdge[] {
  const ids = new Set(agents.map((a) => a.id));
  const edges: LineageEdge[] = [];
  const add = (kind: EdgeKind, source: string | null | undefined, target: string) => {
    if (source && ids.has(source) && ids.has(target) && source !== target)
      edges.push({ id: `${kind}:${source}-${target}`, source, target, kind });
  };
  for (const a of agents) {
    add("parent", a.parent_id, a.id);
    if (a.merged_into) add("merged", a.id, a.merged_into);
    if (a.created_by_task) add("spawned", taskAgent[a.created_by_task], a.id);
  }
  return edges;
}

/** Grid position per agent: generation = longest edge path from a root; within it, oldest first. */
export function layoutLineage(
  agents: LineageAgent[],
  edges: LineageEdge[],
): Record<string, { row: number; col: number }> {
  const row: Record<string, number> = Object.fromEntries(agents.map((a) => [a.id, 0]));
  // Merge edges point "up" to the survivor, so they don't push rows down.
  const down = edges.filter((e) => e.kind !== "merged");
  // Bounded relaxation: at most one pass per agent, so a cycle cannot loop forever.
  for (let i = 0; i < agents.length; i++) {
    let changed = false;
    for (const e of down) {
      if (row[e.target] < row[e.source] + 1 && row[e.source] + 1 < agents.length) {
        row[e.target] = row[e.source] + 1;
        changed = true;
      }
    }
    if (!changed) break;
  }
  // Lay out each generation oldest first, wrapping at MAX_COLS so the graph stays readable on a phone.
  const byAge = [...agents].sort((a, b) => Date.parse(a.created_at) - Date.parse(b.created_at));
  const gens = [...new Set(Object.values(row))].sort((a, b) => a - b);
  const pos: Record<string, { row: number; col: number }> = {};
  let top = 0;
  for (const g of gens) {
    const members = byAge.filter((a) => row[a.id] === g);
    members.forEach((a, i) => {
      pos[a.id] = { row: top + Math.floor(i / MAX_COLS), col: i % MAX_COLS };
    });
    top += Math.ceil(members.length / MAX_COLS);
  }
  return pos;
}

/** Mean of the agent's last ROLLING_WINDOW rewards (newest first), or null if none are scored. */
export function rollingReward<R extends RewardRow>(
  rewards: R[],
  agentId: string,
): { mean: number; window: R[]; count: number } | null {
  const mine = rewards
    .filter((r) => r.agent_id === agentId)
    .sort((a, b) => Date.parse(b.ts) - Date.parse(a.ts));
  if (mine.length === 0) return null;
  const window = mine.slice(0, ROLLING_WINDOW);
  const mean = window.reduce((s, r) => s + Number(r.reward), 0) / window.length;
  return { mean, window, count: mine.length };
}

/** Agents ranked by rolling reward, highest first; unscored agents last, oldest first. */
export function scoreboard<A extends LineageAgent, R extends RewardRow>(
  agents: A[],
  rewards: R[],
) {
  return agents
    .map((agent) => ({ agent, rolling: rollingReward(rewards, agent.id) }))
    .sort(
      (a, b) =>
        (b.rolling?.mean ?? -1) - (a.rolling?.mean ?? -1) ||
        Date.parse(a.agent.created_at) - Date.parse(b.agent.created_at),
    );
}
