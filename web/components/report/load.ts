// Loads everything the Report shows, for the Report tab (browser) and the Markdown export (server route) alike,
// so both render the same data. Read-only: works with the anon key.
import type { SupabaseClient } from "@supabase/supabase-js";
import {
  buildReport,
  parseClaims,
  type EventRow,
  type ExpRow,
  type LlmRow,
  type MetricRow,
  type ProjectRow,
  type ReportData,
  type TaskRow,
} from "./report";

export type ReportProject = ProjectRow & { tags: string[] };
export type ReportBundle = { project: ReportProject | null; hasPaper: boolean; data: ReportData };

const EXP_COLS = "id,label,created_at,config,margin,verdicts,parent_id,changed_key,status,pruned_reason";
const TASK_COLS = "id,capability,status,created_at,finished_at";
const CHUNK = 100;

function check<T>(r: { data: T | null; error: { message: string } | null }): T {
  if (r.error) throw new Error(r.error.message);
  return r.data as T;
}

async function llmFor(db: SupabaseClient, taskIds: string[]): Promise<LlmRow[]> {
  const out: LlmRow[] = [];
  for (let i = 0; i < taskIds.length; i += CHUNK)
    out.push(
      ...check(
        await db.from("llm_calls").select("task_id,tokens_in,tokens_out").in("task_id", taskIds.slice(i, i + CHUNK)),
      ),
    );
  return out;
}

async function runRows(db: SupabaseClient, projectId: string) {
  const [tasks, events] = await Promise.all([
    db.from("tasks").select(TASK_COLS).eq("project_id", projectId),
    db.from("events").select("id,type,message,ts").eq("project_id", projectId).eq("type", "lesson_applied"),
  ]);
  const t = check(tasks) as TaskRow[];
  return { tasks: t, events: check(events) as EventRow[], llm: await llmFor(db, t.map((x) => x.id)) };
}

export async function loadReport(db: SupabaseClient, projectId: string): Promise<ReportBundle> {
  const [p, paper, exps, run] = await Promise.all([
    db.from("projects").select("id,title,arxiv_id,created_at,status,tags").eq("id", projectId).maybeSingle(),
    db.from("papers").select("claims").eq("project_id", projectId).maybeSingle(),
    db.from("experiments").select(EXP_COLS).eq("project_id", projectId),
    runRows(db, projectId),
  ]);
  const project = check(p) as ReportProject | null;
  const experiments = check(exps) as ExpRow[];
  const paperRow = check(paper) as { claims: unknown } | null;

  const metrics: MetricRow[] = experiments.length
    ? check(
        await db
          .from("metrics")
          .select("experiment_id,name,step,value,log_line")
          .in("experiment_id", experiments.map((e) => e.id))
          .like("name", "final\\_%")
          .limit(5000),
      )
    : [];

  // Memory effect: the newest earlier real (non-test) project of the same paper is "run 1".
  let previous = null;
  if (project?.arxiv_id) {
    const prev = check(
      await db
        .from("projects")
        .select("id,title,arxiv_id,created_at,status")
        .eq("arxiv_id", project.arxiv_id)
        .neq("status", "test")
        .lt("created_at", project.created_at)
        .order("created_at", { ascending: false })
        .limit(1),
    ) as ProjectRow[];
    if (prev[0]) previous = { project: prev[0], ...(await runRows(db, prev[0].id)) };
  }

  const data = buildReport({
    claims: parseClaims(paperRow?.claims),
    experiments,
    metrics,
    memory: project ? { project, ...run, previous } : undefined,
  });
  return { project, hasPaper: paperRow !== null, data };
}
