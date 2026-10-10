"use client";

// What-if input (SPEC §7.4): a free-text question → POST /api/projects/<id>/whatif.
// The resulting 'whatif_asked' event and the Designer's branches then show up in the stream below.
import { useState } from "react";
import { PasscodeForm, post, useAuthed } from "./write";

export function WhatIfForm({ projectId }: { projectId: string }) {
  const [authed, setAuthed] = useAuthed();
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);
  const [open, setOpen] = useState(false);

  if (!open)
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="min-h-11 rounded border border-neutral-300 px-3 text-sm font-medium dark:border-neutral-700"
      >
        Ask “what if?”
      </button>
    );

  if (authed === false) return <PasscodeForm onDone={() => setAuthed(true)} why="Needed to ask a what-if." />;

  return (
    <form
      className="rounded-lg border border-neutral-200 p-3 dark:border-neutral-800"
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        setError(null);
        setSent(false);
        try {
          await post(`/api/projects/${projectId}/whatif`, { question });
          setQuestion("");
          setSent(true);
        } catch (err) {
          setError((err as Error).message);
        } finally {
          setBusy(false);
        }
      }}
    >
      <label htmlFor="whatif" className="block text-sm font-medium">
        What if…?
      </label>
      <p className="text-xs text-neutral-500">
        The Designer proposes 3–4 branches, each changing one setting; they get smoke runs and the strongest one waits
        for your approval.
      </p>
      <textarea
        id="whatif"
        rows={2}
        maxLength={500}
        placeholder="What if the temperature were 5 instead of 20?"
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
        className="mt-2 w-full rounded border border-neutral-300 bg-transparent p-2 text-base dark:border-neutral-700"
      />
      <div className="mt-2 flex items-center gap-3">
        <button
          type="submit"
          disabled={busy || authed === null || !question.trim()}
          className="min-h-11 rounded bg-neutral-900 px-4 text-sm font-medium text-white disabled:opacity-50 dark:bg-neutral-100 dark:text-neutral-900"
        >
          {busy ? "Sending…" : "Ask"}
        </button>
        {sent && <span className="text-sm text-green-700 dark:text-green-400">Queued. Watch the events below.</span>}
      </div>
      {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
    </form>
  );
}
