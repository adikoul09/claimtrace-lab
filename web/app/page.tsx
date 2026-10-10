import Link from "next/link";
import { Suspense } from "react";
import { supabase } from "@/lib/supabase";
import type { Project } from "@/lib/types";
import { NewResearchForm } from "@/components/live/new-research-form";
import { projectBadge } from "@/components/live/project-badge";
import { groupProjects, statusLabel } from "@/components/live/labels";

export default function Home() {
  return (
    <>
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
  const { data, error } = await supabase()
    .from("projects")
    .select("id,title,arxiv_id,status,created_at")
    .order("created_at", { ascending: false });

  if (error) return <p className="text-sm text-red-600">Could not load projects: {error.message}</p>;
  const projects = (data ?? []) as Pick<Project, "id" | "title" | "arxiv_id" | "status" | "created_at">[];
  if (projects.length === 0) return <p className="text-sm text-neutral-500">No projects yet.</p>;

  const { main, other } = groupProjects(projects);
  return (
    <>
      {main.length === 0 ? (
        <p className="text-sm text-neutral-500">No live, reference or precomputed projects yet.</p>
      ) : (
        <ProjectRows projects={main} />
      )}
      {other.length > 0 && (
        <details className="mt-4">
          <summary className="min-h-11 cursor-pointer py-2 text-sm font-semibold">
            Other runs <span className="font-normal text-neutral-500">({other.length} test or failed)</span>
          </summary>
          <ProjectRows projects={other} />
        </details>
      )}
    </>
  );
}

function ProjectRows({ projects }: { projects: Pick<Project, "id" | "title" | "arxiv_id" | "status">[] }) {
  return (
    <ul className="divide-y divide-neutral-200 dark:divide-neutral-800">
      {projects.map((p) => {
        const badge = projectBadge(p.status);
        return (
          <li key={p.id}>
            <Link href={`/p/${p.id}?tab=live`} className="block py-3 hover:underline">
              <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span className="min-w-0 break-words font-medium">{p.title}</span>
                {badge && (
                  <span className={badge.className} title={badge.title}>
                    {badge.label}
                  </span>
                )}
              </span>
              <span className="text-xs text-neutral-500">
                {p.arxiv_id ? `arXiv ${p.arxiv_id} · ` : ""}
                {statusLabel(p.status)}
              </span>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
