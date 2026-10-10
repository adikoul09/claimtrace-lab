// GET /api/projects/<id>/report.md → the Report as Markdown (SPEC §12). Same loader and wording as the Report tab.
import { isUuid } from "@/app/logs/log-lines";
import { loadReport } from "@/components/report/load";
import { reportMarkdown } from "@/components/report/markdown";
import { isPrecomputed } from "@/components/report/precomputed";
import { supabase } from "@/lib/supabase";

const text = (status: number, body: string, extra: Record<string, string> = {}) =>
  new Response(body, {
    status,
    headers: { "content-type": "text/markdown; charset=utf-8", "cache-control": "no-store", ...extra },
  });

export async function GET(req: Request, ctx: RouteContext<"/api/projects/[id]/report.md">) {
  const { id } = await ctx.params;
  if (!isUuid(id)) return text(400, "Not a project id.\n");
  let bundle;
  try {
    bundle = await loadReport(supabase(), id);
  } catch {
    return text(502, "Could not load the report.\n");
  }
  if (!bundle.project) return text(404, "No such project.\n");
  const md = reportMarkdown(
    { ...bundle.project, precomputed: isPrecomputed(bundle.project) },
    bundle.data,
    new URL(req.url).origin,
    bundle.hasPaper,
  );
  const slug = bundle.project.title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 60);
  return text(200, md, { "content-disposition": `attachment; filename="report-${slug || id}.md"` });
}
