import Link from "next/link";
import { Suspense } from "react";
import { ExperimentsView } from "@/components/exp/experiments-view";
import { InboxBadge, InboxPanel } from "@/components/inbox/inbox-panel";
import { projectStatusLabel, projectTitle } from "@/components/live/labels";
import { EventStream } from "@/components/live/event-stream";
import { NotesView } from "@/components/report/notes-view";
import { isPrecomputed, PRECOMPUTED_LABEL } from "@/components/report/precomputed";
import { ReportView } from "@/components/report/report-view";
import { TeamView } from "@/components/team/team-view";
import { supabase } from "@/lib/supabase";
import type { Project } from "@/lib/types";
import { CopyId } from "./copy-id";
import { StageStrip } from "./stage-strip";

// Report first: it opens on the answer (claim verdicts and why), the rest is detail.
const TABS = ["report", "experiments", "team", "inbox", "live", "notes"] as const;
type Tab = (typeof TABS)[number];
const LABEL: Record<Tab, string> = {
  report: "Report",
  experiments: "Experiments",
  team: "Team",
  inbox: "Inbox",
  live: "Live",
  notes: "Notes",
};

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
  const tab: Tab = TABS.includes(rawTab as Tab) ? (rawTab as Tab) : "report";

  const db = supabase();
  const { data: project } = await db.from("projects").select("*").eq("id", id).maybeSingle<Project>();
  // The heading is the paper's title (papers.title), from this project's paper or another run of the same arXiv id.
  const paperRows = (q: "project_id" | "arxiv_id", v: string | null | undefined) =>
    v ? db.from("papers").select("project_id,arxiv_id,title").eq(q, v) : Promise.resolve({ data: [] });
  const [own, sameArxiv] = await Promise.all([paperRows("project_id", project?.id), paperRows("arxiv_id", project?.arxiv_id)]);
  const titles = { byProject: {} as Record<string, string>, byArxiv: {} as Record<string, string> };
  const rows = [...(own.data ?? []), ...(sameArxiv.data ?? [])];
  for (const r of rows as { project_id: string; arxiv_id: string; title: string | null }[]) {
    if (!r.title) continue;
    titles.byProject[r.project_id] = r.title;
    titles.byArxiv[r.arxiv_id] ??= r.title;
  }

  return (
    <>
      <div className="mb-4 min-w-0">
        <h1 className="break-words text-lg font-semibold">{project ? projectTitle(project, titles) : "Unknown project"}</h1>
        <p className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-neutral-500">
          {project?.arxiv_id && (
            <a href={`https://arxiv.org/abs/${project.arxiv_id}`} className="underline" target="_blank" rel="noreferrer">
              arXiv {project.arxiv_id}
            </a>
          )}
          {project && <span>{projectStatusLabel(project.status)}</span>}
          <CopyId id={id} />
        </p>
        {isPrecomputed(project) && (
          <p className="mt-1 inline-block rounded border border-amber-400 bg-amber-50 px-1.5 py-0.5 text-xs font-medium text-amber-800 dark:border-amber-700 dark:bg-amber-900/30 dark:text-amber-300">
            {PRECOMPUTED_LABEL} · not a live run
          </p>
        )}
      </div>

      {project && <StageStrip projectId={id} />}

      <nav aria-label="Project views" className="-mx-4 mb-4 overflow-x-auto px-4">
        <ul className="flex gap-1 border-b border-neutral-200 text-sm dark:border-neutral-800">
          {TABS.map((t) => (
            <li key={t}>
              <Link
                href={`/p/${id}?tab=${t}`}
                aria-current={t === tab ? "page" : undefined}
                className={`block whitespace-nowrap px-3 py-2 ${
                  t === tab
                    ? "border-b-2 border-current font-semibold"
                    : "text-neutral-500 hover:text-current"
                }`}
              >
                {LABEL[t]}
                {t === "inbox" && <InboxBadge projectId={id} />}
              </Link>
            </li>
          ))}
        </ul>
      </nav>

      {tab === "inbox" ? (
        <InboxPanel projectId={id} />
      ) : tab === "live" ? (
        <EventStream projectId={id} />
      ) : tab === "team" ? (
        <TeamView />
      ) : tab === "experiments" ? (
        <ExperimentsView projectId={id} />
      ) : tab === "report" ? (
        <ReportView projectId={id} />
      ) : (
        <NotesView projectId={id} />
      )}
    </>
  );
}
