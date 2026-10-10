"use client";

// Notes tab (SPEC §10): the project's research notes in Markdown, written by the Reporter and editable here.
// Shown as plain text with its line breaks kept (no Markdown renderer in the stack).
import { useEffect, useState } from "react";

type State = { status: "loading" } | { status: "none" } | { status: "ok"; text: string } | { status: "error"; message: string };

export function NotesView({ projectId }: { projectId: string }) {
  const [state, setState] = useState<State>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    fetch(`/api/projects/${projectId}/notes`, { cache: "no-store" })
      .then(async (res) => {
        const text = await res.text();
        if (cancelled) return;
        if (res.status === 404) setState({ status: "none" });
        else if (!res.ok) setState({ status: "error", message: text || `HTTP ${res.status}` });
        else setState({ status: "ok", text });
      })
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
        <article className="whitespace-pre-wrap break-words rounded-lg border border-neutral-200 p-3 font-mono text-sm leading-6 dark:border-neutral-800">
          {state.text}
        </article>
      )}
    </section>
  );
}
