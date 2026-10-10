"use client";

// "New research" (SPEC §10 `/`): arXiv id, optional repo URL, budget → POST /api/projects, then open its Live tab.
import { useRouter } from "next/navigation";
import { useState } from "react";
import { PasscodeForm, post, useAuthed } from "./write";

export function NewResearchForm() {
  const router = useRouter();
  const [authed, setAuthed] = useAuthed();
  const [arxiv, setArxiv] = useState("");
  const [repo, setRepo] = useState("");
  const [budget, setBudget] = useState("20");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (authed === false)
    return <PasscodeForm onDone={() => setAuthed(true)} why="Needed to start new research." />;

  const field =
    "min-h-11 w-full rounded border border-neutral-300 bg-transparent px-3 text-base dark:border-neutral-700";
  return (
    <form
      aria-labelledby="new-research-heading"
      className="rounded-lg border border-neutral-200 p-3 dark:border-neutral-800"
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        setError(null);
        try {
          const { project } = await post<{ project: { id: string } }>("/api/projects", {
            arxiv_id: arxiv,
            repo_url: repo.trim() || undefined,
            budget_cpu_min: Number(budget),
          });
          router.push(`/p/${project.id}?tab=live`);
        } catch (err) {
          setError((err as Error).message);
          setBusy(false);
        }
      }}
    >
      <h2 id="new-research-heading" className="text-sm font-semibold">
        New research
      </h2>
      <div className="mt-2 grid gap-3 sm:grid-cols-[2fr_2fr_1fr]">
        <div>
          <label htmlFor="nr-arxiv" className="block text-xs text-neutral-500">
            arXiv ID or link
          </label>
          <input
            id="nr-arxiv"
            required
            placeholder="1503.02531"
            value={arxiv}
            onChange={(e) => setArxiv(e.target.value)}
            className={field}
          />
        </div>
        <div>
          <label htmlFor="nr-repo" className="block text-xs text-neutral-500">
            Repo URL (optional)
          </label>
          <input
            id="nr-repo"
            type="url"
            placeholder="https://github.com/…"
            value={repo}
            onChange={(e) => setRepo(e.target.value)}
            className={field}
          />
        </div>
        <div>
          <label htmlFor="nr-budget" className="block text-xs text-neutral-500">
            Budget (CPU-min)
          </label>
          <input
            id="nr-budget"
            type="number"
            inputMode="numeric"
            min={1}
            max={240}
            step={1}
            required
            value={budget}
            onChange={(e) => setBudget(e.target.value)}
            className={field}
          />
        </div>
      </div>
      <button
        type="submit"
        disabled={busy || authed === null || !arxiv.trim()}
        className="mt-3 min-h-11 w-full rounded bg-neutral-900 px-4 text-sm font-medium text-white disabled:opacity-50 sm:w-auto dark:bg-neutral-100 dark:text-neutral-900"
      >
        {busy ? "Creating…" : "Start research"}
      </button>
      {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
    </form>
  );
}
