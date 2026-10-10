// POST /api/projects/<id>/whatif {question} (SPEC §7.4, §12): queues a design_whatif task for the Designer.
import type { NextRequest } from "next/server";
import { planWhatIf } from "@/app/approvals/approvals";
import { guardWrite, isUuid, reply } from "@/app/approvals/server";

export async function POST(req: NextRequest, ctx: RouteContext<"/api/projects/[id]/whatif">) {
  const { id } = await ctx.params;
  if (!isUuid(id)) return reply(400, { error: "not a project id" });
  const g = await guardWrite(req);
  if (g instanceof Response) return g;
  const { db, body } = g;

  const plan = planWhatIf(id, body);
  if (!plan.ok) return reply(plan.status, { error: plan.error });

  const { data: project, error: pErr } = await db.from("projects").select("id").eq("id", id).maybeSingle();
  if (pErr) return reply(502, { error: "could not load the project" });
  if (!project) return reply(404, { error: "no such project" });

  const { data: task, error } = await db.from("tasks").insert(plan.task).select("id").single();
  if (error || !task) return reply(502, { error: "could not queue the what-if" });

  await db.from("events").insert({
    project_id: id,
    task_id: task.id,
    type: "whatif_asked",
    message: `what-if: ${plan.task.input.question}`,
    reason: "asked by a researcher; queued a design_whatif task for the Designer (3–4 one-change branches)",
    data: { question: plan.task.input.question },
  });
  return reply(201, { task });
}
