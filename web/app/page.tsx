import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";
import { supabase } from "@/lib/supabase";
import type { Project } from "@/lib/types";
import { NewResearchForm } from "@/components/live/new-research-form";
import { projectBadge } from "@/components/live/project-badge";
import { groupProjects, projectStatusLabel, projectTitle, type PaperTitles } from "@/components/live/labels";

export const metadata: Metadata = {
  title: { absolute: "ClaimTrace Lab · Projects" }, // the layout's template only applies to routes below it
  description: "Start a reproduction of an arXiv paper and follow the reference run, live runs and precomputed audits.",
};

export default function Home() {
  return (
    <>
      <p className="mb-4 text-sm text-neutral-600 dark:text-neutral-400">
        Checks whether a paper&apos;s claims hold up by re-running them, with an AI agent team that improves itself.
      </p>
      <div className="mb-6">
        <NewResearchForm />
      </div>
      <h1 className="mb-4 text-lg font-semibold">Projects</h1>
      <Suspense fallback={<p className="text-sm text-neutral-500">Loading…</p>}>
        <ProjectList />
      </Suspense>
    </>
  );
}

async function ProjectList() {
  const db = supabase();
  const [{ data, error }, { data: papers }] = await Promise.all([
    db.from("projects").select("id,title,arxiv_id,status,created_at").order("created_at", { ascending: false }),
    db.from("papers").select("project_id,arxiv_id,title"),
  ]);
  const titles: PaperTitles = { byProject: {}, byArxiv: {} };
  for (const r of (papers ?? []) as { project_id: string; arxiv_id: string; title: string | null }[]) {
    if (!r.title) continue;
    titles.byProject[r.project_id] = r.title;
    titles.byArxiv[r.arxiv_id] ??= r.title;
  }

  if (error) return <p className="text-sm text-red-600">Could not load projects: {error.message}</p>;
  const projects = (data ?? []) as Pick<Project, "id" | "title" | "arxiv_id" | "status" | "created_at">[];
  if (projects.length === 0) return <p className="text-sm text-neutral-500">No projects yet.</p>;

  const { main, other } = groupProjects(projects);
  return (
    <>
      {main.length === 0 ? (
        <p className="text-sm text-neutral-500">No live, reference or precomputed projects yet.</p>
      ) : (
        <ProjectRows projects={main} titles={titles} />
      )}
      {other.length > 0 && (
        <details className="mt-4">
          <summary className="min-h-11 cursor-pointer py-2 text-sm font-semibold">
            Other runs ({other.length})
            <span className="ml-1 font-normal text-neutral-500">tests and stopped runs</span>
          </summary>
          <ProjectRows projects={other} titles={titles} />
        </details>
      )}
    </>
  );
}

function ProjectRows({
  projects,
  titles,
}: {
  projects: Pick<Project, "id" | "title" | "arxiv_id" | "status">[];
  titles: PaperTitles;
}) {
  return (
    <ul className="divide-y divide-neutral-200 dark:divide-neutral-800">
      {projects.map((p) => {
        const badge = projectBadge(p.status);
        return (
          <li key={p.id}>
            <Link href={`/p/${p.id}?tab=live`} className="block py-3 hover:underline">
              <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span className="min-w-0 break-words font-medium">{projectTitle(p, titles)}</span>
                {badge && (
                  <span className={badge.className} title={badge.title}>
                    {badge.label}
                  </span>
                )}
              </span>
              <span className="text-xs text-neutral-500">
                {[p.arxiv_id && `arXiv ${p.arxiv_id}`, !badge && projectStatusLabel(p.status)]
                  .filter(Boolean)
                  .join(" · ")}
              </span>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
