"use client";

// Notes tab (SPEC §10): the project's research notes in Markdown. An edited copy in Storage (notes/<project id>.md)
// wins; otherwise the Reporter's latest write_notes output (CONTRACTS.md §4). Shown as plain text with its line
// breaks kept (no Markdown renderer in the stack). Editing needs the demo passcode (PUT /api/projects/<id>/notes).
import { useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import { PasscodeForm, useAuthed } from "@/components/live/write";
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

async function saveNotes(projectId: string, markdown: string): Promise<void> {
  const res = await fetch(`/api/projects/${projectId}/notes`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ markdown }),
  });
  const j = (await res.json().catch(() => ({}))) as { error?: string };
  if (!res.ok) throw new Error(j.error ?? `request failed (${res.status})`);
}

const button =
  "min-h-11 rounded border border-neutral-300 px-4 text-sm hover:bg-neutral-50 disabled:opacity-50 dark:border-neutral-700 dark:hover:bg-neutral-900";

export function NotesView({ projectId }: { projectId: string }) {
  const [state, setState] = useState<State>({ status: "loading" });
  const [draft, setDraft] = useState<string | null>(null); // null: not editing
  const [authed, setAuthed] = useAuthed();
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let cancelled = false;
    loadNotes(projectId)
      .then((s) => !cancelled && setState(s))
      .catch((e: Error) => !cancelled && setState({ status: "error", message: e.message }));
    return () => {
      cancelled = true;
    };
  }, [projectId, reload]);

  const save = async () => {
    if (draft === null) return;
    setSaving(true);
    setSaveError(null);
    try {
      await saveNotes(projectId, draft);
      setDraft(null);
      setReload((n) => n + 1);
    } catch (e) {
      setSaveError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <section aria-labelledby="notes-heading" className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="notes-heading" className="text-sm font-semibold">
          Research notes
        </h2>
        {draft === null && (state.status === "ok" || state.status === "none") && (
          <button type="button" className={button} onClick={() => setDraft(state.status === "ok" ? state.text : "")}>
            Edit
          </button>
        )}
      </div>

      {draft !== null ? (
        authed === null ? (
          <p className="text-sm text-neutral-500">Checking login…</p>
        ) : !authed ? (
          <PasscodeForm onDone={() => setAuthed(true)} why="Editing the notes needs the demo passcode." />
        ) : (
          <div className="space-y-2">
            <label htmlFor="notes-editor" className="block text-xs text-neutral-500">
              Markdown. Saving replaces the notes shown here; the Reporter&apos;s own output is kept on its task.
            </label>
            <textarea
              id="notes-editor"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              rows={18}
              className="w-full rounded-lg border border-neutral-300 bg-transparent p-3 font-mono text-base leading-6 sm:text-sm dark:border-neutral-700"
            />
            {saveError && <p className="text-sm text-red-600">Could not save: {saveError}</p>}
            <div className="flex gap-2">
              <button
                type="button"
                onClick={save}
                disabled={saving || !draft.trim()}
                className="min-h-11 rounded bg-neutral-900 px-4 text-sm font-medium text-white disabled:opacity-50 dark:bg-neutral-100 dark:text-neutral-900"
              >
                {saving ? "Saving…" : "Save"}
              </button>
              <button type="button" className={button} disabled={saving} onClick={() => (setDraft(null), setSaveError(null))}>
                Cancel
              </button>
            </div>
          </div>
        )
      ) : (
        <>
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
        </>
      )}
    </section>
  );
}
