import Link from "next/link";
import { Suspense } from "react";
import { supabase } from "@/lib/supabase";
import type { Project } from "@/lib/types";

export default function Home() {
  return (
    <>
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

  return (
    <ul className="divide-y divide-neutral-200 dark:divide-neutral-800">
      {projects.map((p) => (
        <li key={p.id}>
          <Link href={`/p/${p.id}?tab=live`} className="block py-3 hover:underline">
            <span className="block break-words font-medium">{p.title}</span>
            <span className="text-xs text-neutral-500">
              {p.arxiv_id ? `arXiv ${p.arxiv_id} · ` : ""}
              {p.status}
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}
