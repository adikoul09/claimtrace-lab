// "Key moments" filter for the Live tab: the events that show the team changing and the researcher's gates.
// Budget hold and approval needed have no event type of their own; they are matched on what the controller writes.

const BUDGET_HOLD = new Set(["budget_hold", "llm_daily_cap"]); // budget_hold: B's token guard (PR #12)
const KEY_TYPES = new Set(["agent_spawned", "agent_refined", "agent_retired", "lesson_applied", ...BUDGET_HOLD]);
const AWAITS_APPROVAL = "(awaits approval)"; // lab/controller/loop.py: the task_assigned message of a gated task

type EventLike = { type: string; message: string };

const needsApproval = (e: EventLike) => e.type === "task_assigned" && e.message.includes(AWAITS_APPROVAL);

export function isKeyMoment(e: EventLike): boolean {
  return KEY_TYPES.has(e.type) || needsApproval(e);
}

/** A plain name for moments whose event type says something else (null: use the event type's label). */
export function momentLabel(e: EventLike): string | null {
  if (needsApproval(e)) return "Approval needed";
  if (BUDGET_HOLD.has(e.type)) return "Budget hold"; // new AI work pauses at the daily token cap
  return null;
}

export const KEY_MOMENTS_FROM = 30;

/** On by default once a project has more than KEY_MOMENTS_FROM events. */
export function keyMomentsByDefault(eventCount: number): boolean {
  return eventCount > KEY_MOMENTS_FROM;
}
