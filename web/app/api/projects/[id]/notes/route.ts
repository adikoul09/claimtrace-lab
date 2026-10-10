// GET /api/projects/<id>/notes → the project's edited research notes (Markdown) as text/markdown, or 404 if none yet.
// PUT /api/projects/<id>/notes {markdown} → saves them (demo passcode required) and writes a notes_edited event.
// Notes live in the private Storage bucket `notes` as <project id>.md, so both go through the service key, which
// never reaches the browser.
import type { NextRequest } from "next/server";
import { serviceSupabase } from "@/lib/supabase";
import { guardWrite, isUuid, reply } from "@/app/approvals/server";
import { NOTES_BUCKET, notesObject, planNotes } from "@/components/report/notes";

const text = (status: number, body: string) =>
  new Response(body, { status, headers: { "content-type": "text/markdown; charset=utf-8", "cache-control": "no-store" } });

export async function GET(_req: Request, ctx: RouteContext<"/api/projects/[id]/notes">) {
  const { id } = await ctx.params;
  if (!isUuid(id)) return text(400, "Not a project id.");
  const db = serviceSupabase();
  if (!db) return text(503, "Notes storage is not configured on this server (SUPABASE_SERVICE_ROLE_KEY).");
  // A missing bucket or object both mean: no notes edited yet.
  const { data, error } = await db.storage.from(NOTES_BUCKET).download(notesObject(id));
  if (error || !data) return text(404, "");
  return text(200, await data.text());
}

export async function PUT(req: NextRequest, ctx: RouteContext<"/api/projects/[id]/notes">) {
  const { id } = await ctx.params;
  if (!isUuid(id)) return reply(400, { error: "not a project id" });
  const g = await guardWrite(req);
  if (g instanceof Response) return g;
  const { db, body } = g;

  const plan = planNotes(body);
  if (!plan.ok) return reply(plan.status, { error: plan.error });

  const { data: project, error: pErr } = await db.from("projects").select("id").eq("id", id).maybeSingle();
  if (pErr) return reply(502, { error: "could not load the project" });
  if (!project) return reply(404, { error: "no such project" });

  const path = notesObject(id);
  const { error } = await db.storage
    .from(NOTES_BUCKET)
    .upload(path, new Blob([plan.markdown], { type: "text/markdown" }), { upsert: true, contentType: "text/markdown" });
  if (error)
    return /bucket not found/i.test(error.message)
      ? reply(503, { error: `the private Storage bucket '${NOTES_BUCKET}' does not exist yet` })
      : reply(502, { error: "could not save the notes" });

  const bytes = new TextEncoder().encode(plan.markdown).length;
  await db.from("events").insert({
    project_id: id,
    type: "notes_edited",
    message: `research notes edited (${bytes} bytes)`,
    reason: "edited by a researcher in the Notes tab; the edited copy replaces the Reporter's notes on screen",
    data: { bucket: NOTES_BUCKET, path, bytes },
  });
  return reply(200, { saved: true, bytes });
}
