// POST /api/tasks/<id>/feedback {value: up | down} (SPEC §9, §12).
// Writes a 'feedback' event; lab/controller/reward.py reads the newest one per task and rescores the reward.
import type { NextRequest } from "next/server";
import { planFeedback } from "@/app/approvals/approvals";
import { guardWrite, isUuid, reply, TASK_FIELDS } from "@/app/approvals/server";

export async function POST(req: NextRequest, ctx: RouteContext<"/api/tasks/[id]/feedback">) {
  const { id } = await ctx.params;
  if (!isUuid(id)) return reply(400, { error: "not a task id" });
  const g = await guardWrite(req);
  if (g instanceof Response) return g;
  const { db, body } = g;

  const { data: task, error } = await db.from("tasks").select(TASK_FIELDS).eq("id", id).maybeSingle();
  if (error) return reply(502, { error: "could not load the task" });
  if (!task) return reply(404, { error: "no such task" });

  const plan = planFeedback(task, body);
  if (!plan.ok) return reply(plan.status, { error: plan.error });

  const { error: evErr } = await db.from("events").insert(plan.event);
  if (evErr) return reply(502, { error: "could not save the feedback" });
  return reply(200, { ok: true });
}
