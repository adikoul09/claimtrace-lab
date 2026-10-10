"use client";

// The project's id, kept off the page: a small button copies it (and its tooltip shows it).
import { useState } from "react";

export function CopyId({ id }: { id: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      title={`Project id ${id}`}
      onClick={() =>
        navigator.clipboard
          ?.writeText(id)
          .then(() => {
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          })
          .catch(() => {})
      }
      className="rounded border border-neutral-300 px-1.5 py-0.5 text-xs text-neutral-500 hover:text-current dark:border-neutral-700"
    >
      {copied ? "Copied" : "Copy ID"}
    </button>
  );
}
