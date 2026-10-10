"use client";

// One line under the header on a project page while it has unread journal emails: "New journal email · Open inbox".
// Nothing at all when everything is read (opening the Inbox tab marks it read, so the strip goes away there).
import Link from "next/link";
import { useUnreadCount } from "./inbox-panel";

export function InboxStrip({ projectId }: { projectId: string }) {
  const n = useUnreadCount(projectId, "inbox-strip");
  if (n === 0) return null;
  return (
    <Link
      href={`/p/${projectId}?tab=inbox`}
      className="mb-2 flex min-h-11 items-center gap-2 rounded-md border border-sky-300 bg-sky-50 px-3 text-sm text-sky-900 hover:underline dark:border-sky-800 dark:bg-sky-950/40 dark:text-sky-200"
    >
      <span className="inline-block h-2 w-2 shrink-0 rounded-full bg-sky-500" aria-hidden />
      <span className="min-w-0 truncate">
        New journal email{n > 1 ? `s (${n})` : ""} · <span className="font-semibold">Open inbox</span>
      </span>
    </Link>
  );
}
