// Pure helpers for the header's inbox card (T31): which project page we are on, and the email in an event.

const PROJECT_PATH = /^\/p\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(?:\/|$)/i;

export function projectIdFromPath(pathname: string | null): string | null {
  return pathname ? (PROJECT_PATH.exec(pathname)?.[1] ?? null) : null;
}

export type InboxEmail = { from: string; subject: string; receivedAt: string; points: string[] };

type EventLike = { type: string; message: string; ts: string; data: unknown };

/** The email an email_received event carries (written by POST /api/inbox), or null for any other event. */
export function inboxEmail(e: EventLike): InboxEmail | null {
  if (e.type !== "email_received") return null;
  const d = (e.data && typeof e.data === "object" ? e.data : {}) as Record<string, unknown>;
  const str = (v: unknown) => (typeof v === "string" && v.trim() ? v : null);
  return {
    from: str(d.from) ?? "unknown sender",
    subject: str(d.subject) ?? e.message,
    receivedAt: str(d.received_at) ?? e.ts,
    points: Array.isArray(d.points) ? d.points.filter((p): p is string => typeof p === "string") : [],
  };
}
