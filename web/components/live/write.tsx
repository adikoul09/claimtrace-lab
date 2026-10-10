"use client";

// Shared bits for the passcode-gated write forms: JSON POST, login state and the passcode form.
import { useEffect, useState } from "react";

/** POST JSON; resolves to the parsed body on success, or throws Error(message from the route). */
export async function post<T = Record<string, unknown>>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const j = (await res.json().catch(() => ({}))) as T & { error?: string };
  if (!res.ok) throw new Error(j.error ?? `request failed (${res.status})`);
  return j;
}

/** null while checking, then whether the DEMO_PASSCODE cookie is valid. */
export function useAuthed(): [boolean | null, (v: boolean) => void] {
  const [authed, setAuthed] = useState<boolean | null>(null);
  useEffect(() => {
    fetch("/api/login")
      .then((r) => r.json())
      .then((j: { authed?: boolean }) => setAuthed(!!j.authed))
      .catch(() => setAuthed(false));
  }, []);
  return [authed, setAuthed];
}

export function PasscodeForm({ onDone, why }: { onDone: () => void; why: string }) {
  const [passcode, setPasscode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <form
      className="rounded-lg border border-neutral-200 p-3 dark:border-neutral-800"
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        setError(null);
        try {
          await post("/api/login", { passcode });
          onDone();
        } catch (err) {
          setError((err as Error).message);
        } finally {
          setBusy(false);
        }
      }}
    >
      <label htmlFor="passcode" className="block text-sm font-medium">
        Demo passcode
      </label>
      <p className="text-xs text-neutral-500">{why}</p>
      <div className="mt-2 flex gap-2">
        <input
          id="passcode"
          type="password"
          autoComplete="current-password"
          value={passcode}
          onChange={(e) => setPasscode(e.target.value)}
          className="min-h-11 min-w-0 flex-1 rounded border border-neutral-300 bg-transparent px-3 text-base dark:border-neutral-700"
        />
        <button
          type="submit"
          disabled={busy || !passcode}
          className="min-h-11 rounded bg-neutral-900 px-4 text-sm font-medium text-white disabled:opacity-50 dark:bg-neutral-100 dark:text-neutral-900"
        >
          {busy ? "…" : "Log in"}
        </button>
      </div>
      {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
    </form>
  );
}
