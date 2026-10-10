// GET /api/projects/<id>/notes → the project's research notes (Markdown) as text/markdown, or 404 if none yet.
// Notes live in the private Storage bucket `notes` as <project id>.md (written by the Reporter, editable in the UI),
// so they are read here with the service key, which never reaches the browser.
import { createClient } from "@supabase/supabase-js";
import { isUuid } from "@/app/logs/log-lines";

const NOTES_BUCKET = "notes";

const reply = (status: number, body: string) =>
  new Response(body, { status, headers: { "content-type": "text/markdown; charset=utf-8", "cache-control": "no-store" } });

export async function GET(_req: Request, ctx: RouteContext<"/api/projects/[id]/notes">) {
  const { id } = await ctx.params;
  if (!isUuid(id)) return reply(400, "Not a project id.");
  const url = process.env.SUPABASE_URL ?? process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!url || !key) return reply(503, "Notes storage is not configured on this server (SUPABASE_SERVICE_ROLE_KEY).");
  const db = createClient(url, key, { auth: { persistSession: false } });
  // A missing bucket or object both mean: no notes written yet.
  const { data, error } = await db.storage.from(NOTES_BUCKET).download(`${id}.md`);
  if (error || !data) return reply(404, "");
  return reply(200, await data.text());
}
