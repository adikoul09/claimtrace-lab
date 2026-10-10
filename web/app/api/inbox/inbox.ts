// Pure logic behind POST /api/inbox (T31): a journal email forwarded by n8n becomes one email_received event.
// Email content is only stored and shown as text: never executed, never sent to an LLM.

const FIELD_MAX = 300;
const BODY_MAX = 50_000;
const POINTS_MAX = 30;
const POINT_MAX = 500;

/** Constant-time check of the x-inbox-secret header. No secret configured → always false. */
export function checkInboxSecret(header: string | null | undefined, secret: string | undefined): boolean {
  if (!header || !secret || header.length !== secret.length) return false;
  let diff = 0;
  for (let i = 0; i < secret.length; i++) diff |= header.charCodeAt(i) ^ secret.charCodeAt(i);
  return diff === 0;
}

// New-style arXiv ids (YYMM.NNNN or YYMM.NNNNN), optional version; not part of a longer number.
const ARXIV_ID = /(?<![\d.])(\d{4}\.\d{4,5})(?:v\d+)?(?![\d.]*\d)/g;

/** arXiv ids (without version) in the subject, then the body, first occurrence each. */
export function findArxivIds(subject: string, body: string): string[] {
  const ids = [...`${subject}\n${body}`.matchAll(ARXIV_ID)].map((m) => m[1]);
  return [...new Set(ids)];
}

// "- x", "* x", "1. x", "2) x": the marker must be followed by whitespace and some text.
const POINT = /^(?:[-*]|\d+[.)])\s+(\S.*)$/;

/** The body's bullet and numbered lines, trimmed and without their markers. */
export function extractPoints(body: string): string[] {
  const points: string[] = [];
  for (const raw of body.split(/\r?\n/)) {
    const m = POINT.exec(raw.trim());
    if (m) points.push(m[1].trim().slice(0, POINT_MAX));
    if (points.length === POINTS_MAX) break;
  }
  return points;
}

export type InboxEvent = {
  type: "email_received";
  message: string;
  reason: string;
  data: { from: string; subject: string; received_at: string | null; points: string[] };
};

type Refusal = { ok: false; status: number; error: string };

export function planInboxEvent(
  body: Record<string, unknown>,
): { ok: true; event: InboxEvent; arxivIds: string[] } | Refusal {
  const { from, subject, body: text, received_at } = body;
  if (typeof from !== "string" || !from.trim()) return { ok: false, status: 400, error: "from is required" };
  if (typeof subject !== "string") return { ok: false, status: 400, error: "subject must be a string" };
  if (typeof text !== "string") return { ok: false, status: 400, error: "body must be a string" };
  if (text.length > BODY_MAX) return { ok: false, status: 413, error: `body is longer than ${BODY_MAX} characters` };

  let received: string | null = null;
  if (received_at !== undefined && received_at !== null && received_at !== "") {
    const t = typeof received_at === "string" ? Date.parse(received_at) : NaN;
    if (Number.isNaN(t)) return { ok: false, status: 400, error: "received_at is not a date" };
    received = new Date(t).toISOString();
  }

  const subj = subject.trim().slice(0, FIELD_MAX);
  return {
    ok: true,
    arxivIds: findArxivIds(subj, text),
    event: {
      type: "email_received",
      message: subj || "(no subject)",
      reason: "journal email via n8n",
      data: { from: from.trim().slice(0, FIELD_MAX), subject: subj, received_at: received, points: extractPoints(text) },
    },
  };
}
