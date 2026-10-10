// Which lessons the controller used or left out for one project (MEM-1, docs/CONTRACTS.md §6c), from its
// lesson_applied / lesson_skipped events. The rules live in lab/controller/memory.py; this only groups the events.
import { humanize } from "../live/labels.ts";

type EventLike = { id: string; type: string; ts: string; message: string; reason: string; data: unknown };

export type AppliedLesson = {
  lessonId: string;
  message: string; // the event's lesson text, for lessons no longer in the table
  uses: number;
  where: string[]; // "planner", "write_code task", ...
  tags: string[]; // the tags that matched
  rank: number | null; // best rank (1 = most relevant); null on events from before MEM-1
  eventId: string; // the first use, for "Open in Live"
};

export type SkippedLesson = { lessonId: string; message: string; reason: string; detail: string; eventId: string };

const obj = (d: unknown) => (d && typeof d === "object" && !Array.isArray(d) ? (d as Record<string, unknown>) : {});
const strs = (v: unknown) => (Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []);
const PREFIX = /^lesson (applied to|not used in) the [^:]+:\s*/;

/** Groups events (any order) per lesson: applied by lesson, skipped by lesson and reason; oldest first. */
export function lessonUse(events: EventLike[]): { applied: AppliedLesson[]; skipped: SkippedLesson[] } {
  const applied = new Map<string, AppliedLesson>();
  const skipped = new Map<string, SkippedLesson>();
  for (const e of [...events].sort((a, b) => Date.parse(a.ts) - Date.parse(b.ts))) {
    const d = obj(e.data);
    const id = typeof d.lesson_id === "string" ? d.lesson_id : null;
    if (!id) continue;
    const message = e.message.replace(PREFIX, "");
    if (e.type === "lesson_applied") {
      const a = applied.get(id) ?? { lessonId: id, message, uses: 0, where: [], tags: [], rank: null, eventId: e.id };
      a.uses += 1;
      if (typeof d.where === "string" && !a.where.includes(d.where)) a.where.push(d.where);
      for (const t of strs(d.tags)) if (!a.tags.includes(t)) a.tags.push(t);
      if (typeof d.rank === "number") a.rank = a.rank === null ? d.rank : Math.min(a.rank, d.rank);
      applied.set(id, a);
    } else if (e.type === "lesson_skipped") {
      const reason = typeof d.reason === "string" ? d.reason : "unknown";
      const key = `${id}:${reason}`;
      if (!skipped.has(key))
        skipped.set(key, {
          lessonId: id,
          message,
          reason,
          detail: typeof d.detail === "string" ? d.detail : e.reason,
          eventId: e.id,
        });
    }
  }
  return { applied: [...applied.values()], skipped: [...skipped.values()] };
}

const SKIP_REASON: Record<string, string> = {
  no_evidence: "No evidence event",
  other_paper: "From another paper",
  duplicate: "Duplicate of a lesson used more often",
  over_limit: "Over the limit of 5 per plan",
};

export function skipReasonLabel(code: string): string {
  return SKIP_REASON[code] ?? humanize(code);
}
