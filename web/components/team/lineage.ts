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
  origin?: string;
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
    // A refined agent also records the task that triggered the refine; only a spawn is a "spawned by" edge.
    if (a.created_by_task && a.origin !== "refined") add("spawned", taskAgent[a.created_by_task], a.id);
  }
  return edges;
}

// --- refine chains: one node per role, its newest version (A1-TEAM) ---------------------------------------------

type ChainAgent = LineageAgent & { origin?: string; version?: number };
export type Chain = { id: string; root: string; head: string; members: string[] };

/**
 * Refine chains: a refined agent belongs to its parent's chain; a seed or spawned agent starts one.
 * Members are oldest version first; head is the newest. The chain id is its root's id.
 */
export function refineChains(agents: ChainAgent[]): { chainOf: Record<string, string>; chains: Record<string, Chain> } {
  const byId = new Map(agents.map((a) => [a.id, a]));
  const chainOf: Record<string, string> = {};
  const rootOf = (a: ChainAgent): string => {
    const seen = new Set<string>();
    let cur = a;
    while (cur.origin === "refined" && cur.parent_id && byId.has(cur.parent_id) && !seen.has(cur.id)) {
      seen.add(cur.id);
      cur = byId.get(cur.parent_id)!;
    }
    return cur.id;
  };
  const chains: Record<string, Chain> = {};
  for (const a of agents) {
    const root = rootOf(a);
    chainOf[a.id] = root;
    (chains[root] ??= { id: root, root, head: root, members: [] }).members.push(a.id);
  }
  const order = (id: string) => {
    const a = byId.get(id)!;
    return [a.version ?? 0, Date.parse(a.created_at)];
  };
  for (const c of Object.values(chains)) {
    c.members.sort((x, y) => order(x)[0] - order(y)[0] || order(x)[1] - order(y)[1]);
    c.head = c.members[c.members.length - 1];
  }
  return { chainOf, chains };
}

/**
 * Cards and scoreboard: each role's newest version (input order kept), the older versions (newest first within a
 * role, roles in input order), and for a role that was spawned, its spawned root (for the badge and its reason).
 */
export function latestPerRole<A extends ChainAgent>(
  agents: A[],
): { latest: A[]; older: A[]; spawnedRoot: Record<string, A | undefined> } {
  const { chainOf, chains } = refineChains(agents);
  const byId = new Map(agents.map((a) => [a.id, a]));
  const latest = agents.filter((a) => chains[chainOf[a.id]].head === a.id);
  const older = latest.flatMap((h) =>
    chains[chainOf[h.id]].members
      .filter((id) => id !== h.id)
      .reverse()
      .map((id) => byId.get(id)!),
  );
  const spawnedRoot: Record<string, A | undefined> = {};
  for (const h of latest) {
    const root = byId.get(chains[chainOf[h.id]].root)!;
    if (root.origin === "spawned") spawnedRoot[h.id] = root;
  }
  return { latest, older, spawnedRoot };
}

/** The graph to draw: each chain as its head unless expanded; edges moved onto what is shown, deduped. */
export function collapseLineage<A extends ChainAgent>(
  agents: A[],
  edges: LineageEdge[],
  expanded: Set<string>,
): { visible: A[]; edges: LineageEdge[]; chains: Record<string, Chain>; chainOf: Record<string, string> } {
  const { chainOf, chains } = refineChains(agents);
  const shown = (id: string) => (expanded.has(chainOf[id]) ? id : chains[chainOf[id]].head);
  const visible = agents.filter((a) => shown(a.id) === a.id);
  const out = new Map<string, LineageEdge>();
  for (const e of edges) {
    if (!(e.source in chainOf) || !(e.target in chainOf)) continue;
    const source = shown(e.source);
    const target = shown(e.target);
    if (source === target) continue;
    const id = `${e.kind}:${source}-${target}`;
    if (!out.has(id)) out.set(id, { id, source, target, kind: e.kind });
  }
  return { visible, edges: [...out.values()], chains, chainOf };
}

/** Grid position per agent: generation = longest edge path from a root; within it, oldest first. */
export function layoutLineage(
  agents: LineageAgent[],
  edges: LineageEdge[],
  maxCols = MAX_COLS,
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
  // Lay out each generation, wrapping at maxCols so the graph stays readable on a phone. Within a generation:
  // children in their parent's column order, then agents without children before those with them (so a parent
  // sits on the row nearest its children and no edge crosses a card), then oldest first.
  const byAge = [...agents].sort((a, b) => Date.parse(a.created_at) - Date.parse(b.created_at));
  const hasChildren = new Set(down.map((e) => e.source));
  const parentOf: Record<string, string> = {};
  for (const e of down) if (row[e.target] === row[e.source] + 1) parentOf[e.target] ??= e.source;
  const gens = [...new Set(Object.values(row))].sort((a, b) => a - b);
  const pos: Record<string, { row: number; col: number }> = {};
  let top = 0;
  for (const g of gens) {
    const key = (a: LineageAgent) => [
      parentOf[a.id] && pos[parentOf[a.id]] ? pos[parentOf[a.id]].col : -1,
      hasChildren.has(a.id) ? 1 : 0,
    ];
    const members = byAge
      .filter((a) => row[a.id] === g)
      .sort((a, b) => key(a)[0] - key(b)[0] || key(a)[1] - key(b)[1]); // stable: ties stay oldest first
    members.forEach((a, i) => {
      pos[a.id] = { row: top + Math.floor(i / maxCols), col: i % maxCols };
    });
    top += Math.ceil(members.length / maxCols);
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
