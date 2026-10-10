// POST /api/inbox {from, subject, body, received_at} (T31): n8n forwards a journal email; we store one
// email_received event on the project it names (arXiv id in the subject or body), else on the newest project.
// Auth is the x-inbox-secret header (INBOX_WEBHOOK_SECRET), not the demo passcode cookie.
import type { NextRequest } from "next/server";
import { reply } from "@/app/approvals/server";
import { serviceSupabase } from "@/lib/supabase";
import { checkInboxSecret, planInboxEvent } from "./inbox";

export async function POST(req: NextRequest) {
  if (!checkInboxSecret(req.headers.get("x-inbox-secret"), process.env.INBOX_WEBHOOK_SECRET))
    return reply(401, { error: "missing or wrong x-inbox-secret" });
  if (!req.headers.get("content-type")?.startsWith("application/json"))
    return reply(415, { error: "send JSON (content-type: application/json)" });
  const db = serviceSupabase();
  if (!db) return reply(503, { error: "writes are not configured on this server (SUPABASE_SERVICE_ROLE_KEY)" });

  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return reply(400, { error: "body is not valid JSON" });
  }
  if (!body || typeof body !== "object" || Array.isArray(body)) return reply(400, { error: "body must be an object" });

  const plan = planInboxEvent(body as Record<string, unknown>);
  if (!plan.ok) return reply(plan.status, { error: plan.error });

  // The ids are digits and one dot (findArxivIds), so they are safe inside the PostgREST filter.
  let project: { id: string } | null = null;
  if (plan.arxivIds.length) {
    const filter = plan.arxivIds.flatMap((id) => [`arxiv_id.eq.${id}`, `arxiv_id.like.${id}v*`]).join(",");
    const { data } = await db.from("projects").select("id").or(filter).order("created_at", { ascending: false }).limit(1);
    project = data?.[0] ?? null;
  }
  if (!project) {
    const { data } = await db.from("projects").select("id").order("created_at", { ascending: false }).limit(1);
    project = data?.[0] ?? null;
  }
  if (!project) return reply(404, { error: "there is no project to attach the email to" });

  const { data: event, error } = await db
    .from("events")
    .insert({ ...plan.event, project_id: project.id })
    .select("id")
    .single();
  if (error || !event) return reply(502, { error: "could not store the email" });
  return reply(201, { event_id: event.id, project_id: project.id, points: plan.event.data.points.length });
}
