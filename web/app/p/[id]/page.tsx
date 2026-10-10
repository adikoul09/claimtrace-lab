import Link from "next/link";
import { Suspense } from "react";
import { ExperimentsView } from "@/components/exp/experiments-view";
import { EventStream } from "@/components/live/event-stream";
import { TeamView } from "@/components/team/team-view";
import { supabase } from "@/lib/supabase";
import type { Project } from "@/lib/types";

const TABS = ["team", "live", "experiments", "report", "notes"] as const;
type Tab = (typeof TABS)[number];

export default function ProjectPage({ params, searchParams }: PageProps<"/p/[id]">) {
  return (
    <Suspense fallback={<p className="text-sm text-neutral-500">Loading…</p>}>
      <ProjectView params={params} searchParams={searchParams} />
    </Suspense>
  );
}

async function ProjectView({ params, searchParams }: PageProps<"/p/[id]">) {
  const { id } = await params;
  const { tab: rawTab } = await searchParams;
  const tab: Tab = TABS.includes(rawTab as Tab) ? (rawTab as Tab) : "live";

  const { data: project } = await supabase()
    .from("projects")
    .select("*")
    .eq("id", id)
    .maybeSingle<Project>();

  return (
    <>
      <div className="mb-4 min-w-0">
        <h1 className="break-words text-lg font-semibold">{project?.title ?? "Unknown project"}</h1>
        <p className="break-all font-mono text-xs text-neutral-500">
          {project?.arxiv_id ? `arXiv ${project.arxiv_id} · ` : ""}
          {id}
        </p>
      </div>

      <nav aria-label="Project views" className="-mx-4 mb-4 overflow-x-auto px-4">
        <ul className="flex gap-1 border-b border-neutral-200 text-sm dark:border-neutral-800">
          {TABS.map((t) => (
            <li key={t}>
              <Link
                href={`/p/${id}?tab=${t}`}
                aria-current={t === tab ? "page" : undefined}
                className={`block px-3 py-2 capitalize ${
                  t === tab
                    ? "border-b-2 border-current font-semibold"
                    : "text-neutral-500 hover:text-current"
                }`}
              >
                {t}
              </Link>
            </li>
          ))}
        </ul>
      </nav>

      {tab === "live" ? (
        <EventStream projectId={id} />
      ) : tab === "team" ? (
        <TeamView />
      ) : tab === "experiments" ? (
        <ExperimentsView projectId={id} />
      ) : (
        <p className="text-sm text-neutral-500">Not built yet (next).</p>
      )}
    </>
  );
}
