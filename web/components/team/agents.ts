// Pure helpers for the Team tab: apply Realtime changes to the agent list and order it.

type Row = { id: string; status: string; created_at: string };

export type AgentChange<T> =
  | { eventType: "INSERT" | "UPDATE"; new: T; old: Partial<T> }
  | { eventType: "DELETE"; new: Partial<T>; old: Partial<T> };

const STATUS_ORDER: Record<string, number> = { active: 0, retired: 1, merged: 2 };

/** Apply one postgres_changes payload: upsert by id on INSERT/UPDATE, drop by id on DELETE. */
export function applyAgentChange<T extends Row>(current: T[], change: AgentChange<T>): T[] {
  if (change.eventType === "DELETE") return current.filter((a) => a.id !== change.old.id);
  const row = change.new;
  return current.some((a) => a.id === row.id)
    ? current.map((a) => (a.id === row.id ? row : a))
    : [...current, row];
}

/** Active first, then retired, then merged; oldest first within a status. */
export function sortAgents<T extends Row>(agents: T[]): T[] {
  return [...agents].sort(
    (a, b) =>
      (STATUS_ORDER[a.status] ?? 9) - (STATUS_ORDER[b.status] ?? 9) ||
      Date.parse(a.created_at) - Date.parse(b.created_at),
  );
}
