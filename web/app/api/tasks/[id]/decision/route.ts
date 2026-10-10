// POST /api/tasks/<id>/decision {decision: approve | reject | redirect, note?} (SPEC §9, §12).
// Approve moves the task to 'queued', so an executor's claim_task() picks it up.
import type { NextRequest } from "next/server";
import { planDecision } from "@/app/approvals/approvals";
import { guardWrite, isUuid, reply, TASK_FIELDS } from "@/app/approvals/server";

export async function POST(req: NextRequest, ctx: RouteContext<"/api/tasks/[id]/decision">) {
  const { id } = await ctx.params;
  if (!isUuid(id)) return reply(400, { error: "not a task id" });
  const g = await guardWrite(req);
  if (g instanceof Response) return g;
  const { db, body } = g;

  const { data: task, error } = await db.from("tasks").select(TASK_FIELDS).eq("id", id).maybeSingle();
  if (error) return reply(502, { error: "could not load the task" });
  if (!task) return reply(404, { error: "no such task" });

  const plan = planDecision(task, body);
  if (!plan.ok) return reply(plan.status, { error: plan.error });

  // Only from awaiting_approval: two phones deciding at once cannot both win.
  const { data: moved, error: upErr } = await db
    .from("tasks")
    .update(plan.update)
    .eq("id", id)
    .eq("status", "awaiting_approval")
    .select("id,status,decision");
  if (upErr) return reply(502, { error: "could not save the decision" });
  if (!moved?.length) return reply(409, { error: "the task was decided or moved meanwhile" });

  const { error: evErr } = await db.from("events").insert(plan.event);
  if (evErr) return reply(502, { error: "decision saved, but its event could not be written" });
  return reply(200, { task: moved[0] });
}
