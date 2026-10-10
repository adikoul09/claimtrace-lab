"use client";

// Toast when a journal email arrives for this project while the page is open (T31). Mounted once per project page
// (by the header), so it shows on every tab.
import { useEffect, useRef, useState } from "react";
import { inboxEmail } from "@/components/live/inbox";
import type { Event } from "@/lib/types";
import { useProjectEmails } from "./use-emails";

const SHOW_MS = 8000;

export function InboxToast({ projectId }: { projectId: string }) {
  const [toast, setToast] = useState<{ id: string; subject: string; from: string; points: number } | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useProjectEmails(projectId, "inbox-toast", (e: Event) => {
    const m = inboxEmail(e);
    if (!m) return;
    setToast({ id: e.id, subject: m.subject, from: m.from, points: m.points.length });
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setToast(null), SHOW_MS);
  });

  useEffect(() => () => clearTimeout(timer.current), []);

  if (!toast) return null;
  return (
    <div
      role="status"
      aria-live="polite"
      className="fixed inset-x-4 bottom-4 z-50 rounded-md border border-sky-300 bg-white p-3 text-sm shadow-lg sm:left-auto sm:right-4 sm:w-96 dark:border-sky-800 dark:bg-neutral-900"
    >
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <p className="text-xs font-semibold text-sky-800 dark:text-sky-300">New journal email</p>
          <p className="mt-0.5 break-words font-medium">{toast.subject}</p>
          <p className="mt-0.5 break-all text-xs text-neutral-500">
            from {toast.from} · {toast.points} point{toast.points === 1 ? "" : "s"}
          </p>
        </div>
        <button
          type="button"
          onClick={() => setToast(null)}
          aria-label="Dismiss"
          className="rounded px-1.5 text-neutral-500 hover:bg-neutral-100 dark:hover:bg-neutral-800"
        >
          ×
        </button>
      </div>
    </div>
  );
}
