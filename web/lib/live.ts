// Pure helpers for the Live tab and the header's live-data check.

const ms = (ts: string) => Date.parse(ts);

/** Merge incoming rows into a list: dedupe by id (incoming wins), newest-first, capped. */
export function mergeEvents<T extends { id: string; ts: string }>(
  current: T[],
  incoming: T[],
  limit = 200,
): T[] {
  const byId = new Map<string, T>();
  for (const e of current) byId.set(e.id, e);
  for (const e of incoming) byId.set(e.id, e);
  return [...byId.values()].sort((a, b) => ms(b.ts) - ms(a.ts)).slice(0, limit);
}

/** The later of two timestamps (either may be null). */
export function latestTs(a: string | null, b: string | null): string | null {
  if (!a) return b;
  if (!b) return a;
  return ms(b) > ms(a) ? b : a;
}

/** "5 s ago", "3 min ago", "2 h ago", "1 d ago", or "never". */
export function formatAgo(ts: string | null, now = Date.now()): string {
  if (!ts) return "never";
  const s = Math.max(0, Math.floor((now - ms(ts)) / 1000));
  if (s < 60) return `${s} s ago`;
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}
