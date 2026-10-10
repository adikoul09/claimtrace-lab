// Pure helpers for the Inbox tab (T31): the project's journal emails and which of them this viewer has read.
// "Read" is per viewer and per browser: the newest email time seen when the panel was open, kept in localStorage
// with an in-memory copy, so it still works (for this page's lifetime) when storage is blocked.

type EventLike = { id: string; ts: string; type: string };

export const READ_EVENT = "ct-inbox-read"; // window event so a badge updates when a panel on the same page marks read

/** Adds email_received events to the list: newest first, each id once. */
export function mergeEmails<E extends EventLike>(cur: E[], incoming: E[]): E[] {
  const byId = new Map(cur.map((e) => [e.id, e]));
  for (const e of incoming) if (e.type === "email_received") byId.set(e.id, e);
  return [...byId.values()].sort((a, b) => Date.parse(b.ts) - Date.parse(a.ts));
}

export function unreadCount(emails: { ts: string }[], lastRead: string | null): number {
  const since = lastRead ? Date.parse(lastRead) : -Infinity;
  return emails.filter((e) => Date.parse(e.ts) > since).length;
}

type Storage = { getItem(k: string): string | null; setItem(k: string, v: string): void };

const memory = new Map<string, string>();
const key = (projectId: string) => `ct-inbox-read:${projectId}`;

/** The browser's localStorage, or null where reading it throws (blocked, sandboxed, server). */
export function browserStorage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

export function getLastRead(projectId: string, storage: Storage | null = browserStorage()): string | null {
  let stored: string | null = null;
  try {
    stored = storage?.getItem(key(projectId)) ?? null;
  } catch {}
  const mem = memory.get(projectId) ?? null;
  if (!stored) return mem;
  if (!mem) return stored;
  return Date.parse(mem) > Date.parse(stored) ? mem : stored;
}

/** Marks every email up to `ts` as read. Never moves the mark backwards. */
export function markRead(projectId: string, ts: string, storage: Storage | null = browserStorage()): void {
  const cur = getLastRead(projectId, storage);
  if (cur && Date.parse(cur) >= Date.parse(ts)) return;
  memory.set(projectId, ts);
  try {
    storage?.setItem(key(projectId), ts);
  } catch {}
  if (typeof window !== "undefined") window.dispatchEvent(new CustomEvent(READ_EVENT, { detail: projectId }));
}
