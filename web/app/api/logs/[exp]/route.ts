// GET /api/logs/<experiment id> → the run's log as text/plain.
// The Storage `logs` bucket is private, so this server route reads it with the service key, which never reaches the
// browser. The object name comes from experiments.log_path (as the worker wrote it), checked against logs/<name>.log.
import { createClient } from "@supabase/supabase-js";
import { isUuid, logObject } from "@/app/logs/log-lines";

const LOG_BUCKET = "logs";

const reply = (status: number, message: string) =>
  new Response(message, { status, headers: { "content-type": "text/plain; charset=utf-8", "cache-control": "no-store" } });

export async function GET(_req: Request, ctx: RouteContext<"/api/logs/[exp]">) {
  const { exp } = await ctx.params;
  if (!isUuid(exp)) return reply(400, "Not an experiment id.");

  const url = process.env.SUPABASE_URL ?? process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!url || !key) return reply(503, "Log storage is not configured on this server (SUPABASE_SERVICE_ROLE_KEY).");
  const db = createClient(url, key, { auth: { persistSession: false } });

  const { data: row, error } = await db
    .from("experiments")
    .select("log_path,status")
    .eq("id", exp)
    .maybeSingle<{ log_path: string | null; status: string }>();
  if (error) return reply(502, "Could not look up the experiment.");
  if (!row) return reply(404, "No such experiment.");
  const object = logObject(row.log_path);
  if (!object) return reply(404, "This experiment has no log yet.");

  const { data: blob, error: dlError } = await db.storage.from(LOG_BUCKET).download(object);
  if (dlError || !blob) return reply(404, "The log has not been uploaded yet.");

  return new Response(blob.stream(), {
    headers: {
      "content-type": "text/plain; charset=utf-8",
      "cache-control": "no-store",
      "x-experiment-status": row.status,
    },
  });
}
