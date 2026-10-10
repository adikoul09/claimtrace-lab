"use client";

// Notes tab (SPEC §10): the project's research notes in Markdown. An edited copy in Storage (notes/<project id>.md)
// wins; otherwise the Reporter's latest write_notes output (CONTRACTS.md §4). Shown as plain text with its line
// breaks kept (no Markdown renderer in the stack).
import { useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import { latestNotes } from "./report";

type State =
  | { status: "loading" }
  | { status: "none" }
  | { status: "ok"; text: string; source: string }
  | { status: "error"; message: string };

async function loadNotes(projectId: string): Promise<State> {
  const res = await fetch(`/api/projects/${projectId}/notes`, { cache: "no-store" });
  if (res.ok) return { status: "ok", text: await res.text(), source: "Edited notes" };
  if (res.status !== 404) return { status: "error", message: (await res.text()) || `HTTP ${res.status}` };
  const { data, error } = await supabase()
    .from("tasks")
    .select("id,capability,status,finished_at,output")
    .eq("project_id", projectId)
    .eq("capability", "write_notes")
    .eq("status", "done");
  if (error) return { status: "error", message: error.message };
  const notes = latestNotes(data ?? []);
  return notes
    ? { status: "ok", text: notes.markdown, source: `Written by the Reporter (task ${notes.taskId.slice(0, 8)})` }
    : { status: "none" };
}

export function NotesView({ projectId }: { projectId: string }) {
  const [state, setState] = useState<State>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    loadNotes(projectId)
      .then((s) => !cancelled && setState(s))
      .catch((e: Error) => !cancelled && setState({ status: "error", message: e.message }));
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  return (
    <section aria-labelledby="notes-heading" className="space-y-3">
      <h2 id="notes-heading" className="text-sm font-semibold">
        Research notes
      </h2>
      {state.status === "loading" && <p className="text-sm text-neutral-500">Loading notes…</p>}
      {state.status === "none" && (
        <p className="text-sm text-neutral-500">No notes yet. The Reporter writes them after an experiment finishes.</p>
      )}
      {state.status === "error" && <p className="text-sm text-red-600">Could not load the notes: {state.message}</p>}
      {state.status === "ok" && (
        <>
          <p className="text-xs text-neutral-500">{state.source}</p>
          <article className="whitespace-pre-wrap break-words rounded-lg border border-neutral-200 p-3 font-mono text-sm leading-6 dark:border-neutral-800">
            {state.text}
          </article>
        </>
      )}
    </section>
  );
}
