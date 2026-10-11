"use client";

// Inbox tab (T31): every journal email n8n forwarded for this project (POST /api/inbox), newest first, over Realtime.
// While the panel is open its emails count as read (InboxBadge). Email text is shown as plain text only.
import { useEffect, useSyncExternalStore } from "react";
import { inboxEmail } from "@/components/live/inbox";
import { getLastRead, markRead, READ_EVENT, unreadCount } from "./inbox";
import { useProjectEmails } from "./use-emails";

function subscribeRead(onChange: () => void) {
  window.addEventListener(READ_EVENT, onChange);
  window.addEventListener("storage", onChange); // another tab marked read
  return () => {
    window.removeEventListener(READ_EVENT, onChange);
    window.removeEventListener("storage", onChange);
  };
}

/** This viewer's read mark for the project (null on the server and before anything was read). */
function useLastRead(projectId: string): string | null {
  return useSyncExternalStore(
    subscribeRead,
    () => getLastRead(projectId),
    () => null,
  );
}

export function InboxPanel({ projectId }: { projectId: string }) {
  const { emails, loaded, error } = useProjectEmails(projectId, "inbox-panel");
  const newest = emails[0]?.ts;

  useEffect(() => {
    if (newest) markRead(projectId, newest);
  }, [projectId, newest]);

  return (
    <section aria-labelledby="inbox-panel-heading">
      <h2 id="inbox-panel-heading" className="mb-3 text-sm font-semibold">
        Journal emails <span className="font-normal text-neutral-500">({emails.length})</span>
      </h2>
      {error && <p className="mb-3 text-sm text-red-600">Could not load emails: {error}</p>}
      {emails.length === 0 ? (
        !loaded ? (
          <p className="text-sm text-neutral-500">Loading…</p>
        ) : (
          !error && (
            <p className="text-sm text-neutral-500">
              No emails yet. Journal emails forwarded by n8n appear here as they arrive.
            </p>
          )
        )
      ) : (
        <ol className="space-y-3">
          {emails.map((e) => {
            const m = inboxEmail(e);
            if (!m) return null;
            return (
              <li
                key={e.id}
                className="rounded-md border border-neutral-200 p-3 text-sm dark:border-neutral-800"
              >
                <p className="break-words font-medium">{m.subject}</p>
                <div className="mt-0.5 flex flex-wrap gap-x-2 text-xs text-neutral-500">
                  <span className="min-w-0 break-all">from {m.from}</span>
                  <time dateTime={m.receivedAt} title={new Date(m.receivedAt).toISOString()} className="tabular-nums">
                    {new Date(m.receivedAt).toLocaleString()}
                  </time>
                </div>
                {m.points.length > 0 ? (
                  <ol className="mt-2 list-decimal space-y-0.5 pl-5">
                    {m.points.map((p, i) => (
                      <li key={i} className="break-words">
                        {p}
                      </li>
                    ))}
                  </ol>
                ) : (
                  <p className="mt-1 text-xs text-neutral-500">No bullet or numbered points found in the email.</p>
                )}
                <button
                  type="button"
                  disabled
                  title="Send to engine is not live yet (T33)"
                  className="mt-3 w-full rounded border border-neutral-300 px-3 py-1.5 text-xs text-neutral-500 sm:w-auto dark:border-neutral-700"
                >
                  Send to engine{" "}
                  <span className="ml-1 rounded bg-neutral-200 px-1 py-0.5 text-[10px] font-semibold uppercase dark:bg-neutral-800">
                    Next
                  </span>
                </button>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}

/** How many of the project's journal emails this viewer has not seen in the Inbox panel yet. */
export function useUnreadCount(projectId: string, channel: string): number {
  const { emails } = useProjectEmails(projectId, channel);
  return unreadCount(emails, useLastRead(projectId));
}

/** Unread journal emails for the project (count pill); hidden when there are none. For the Inbox tab's label. */
export function InboxBadge({ projectId }: { projectId: string }) {
  const n = useUnreadCount(projectId, "inbox-badge");
  if (n === 0) return null;
  return (
    <span
      key={n} // re-mount, so the pop plays again when the count changes
      className="ct-pop ml-1 inline-flex min-w-[1.25rem] items-center justify-center rounded-full bg-sky-600 px-1.5 text-[10px] font-semibold leading-5 text-white"
      aria-label={`${n} unread email${n === 1 ? "" : "s"}`}
    >
      {n > 99 ? "99+" : n}
    </span>
  );
}
