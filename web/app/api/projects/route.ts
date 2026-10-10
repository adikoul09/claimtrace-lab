// POST /api/projects {arxiv_id, repo_url?, budget_cpu_min?} (SPEC §12).
// Inserts a 'new' project; the controller's intake queues its plan task.
import type { NextRequest } from "next/server";
import { planProject } from "@/app/approvals/approvals";
import { guardWrite, reply } from "@/app/approvals/server";

export async function POST(req: NextRequest) {
  const g = await guardWrite(req);
  if (g instanceof Response) return g;
  const { db, body } = g;

  const plan = planProject(body);
  if (!plan.ok) return reply(plan.status, { error: plan.error });

  const { data: project, error } = await db.from("projects").insert(plan.row).select("id,title").single();
  if (error || !project) return reply(502, { error: "could not create the project" });

  const r = plan.row;
  await db.from("events").insert({
    project_id: project.id,
    type: "project_created",
    message: `new research: ${r.title}`,
    reason:
      `created on the New research form: arXiv ${r.arxiv_id}, budget ${r.budget_cpu_min} CPU-min` +
      (r.repo_url ? `, repo ${r.repo_url}` : ", no repo (the Implementer writes the code)"),
    data: r,
  });
  return reply(201, { project });
}
