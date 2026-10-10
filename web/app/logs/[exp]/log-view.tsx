"use client";

// Line-numbered log (SPEC §10). #L<n> highlights and scrolls to line n; every number in the Report links here.
// While the run is still going the log is re-read every few seconds (the worker re-uploads it every 5 s).
import { useEffect, useState } from "react";
import { lineFromHash, splitLog } from "../log-lines";

const POLL_MS = 5000;

export function LogView({ exp }: { exp: string }) {
  const [lines, setLines] = useState<string[] | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [target, setTarget] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = async () => {
      try {
        const res = await fetch(`/api/logs/${exp}`, { cache: "no-store" });
        const text = await res.text();
        if (cancelled) return;
        if (!res.ok) {
          setError(text || `HTTP ${res.status}`);
        } else {
          setError(null);
          setLines(splitLog(text));
        }
        const live = res.headers.get("x-experiment-status") === "running";
        setRunning(live);
        if (live) timer = setTimeout(load, POLL_MS);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    };
    load();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [exp]);

  useEffect(() => {
    const read = () => setTarget(lineFromHash(window.location.hash));
    read();
    window.addEventListener("hashchange", read);
    return () => window.removeEventListener("hashchange", read);
  }, []);

  // Scroll once the target line exists (on load, and whenever the hash changes).
  const targetLoaded = target !== null && lines !== null && target <= lines.length;
  useEffect(() => {
    if (targetLoaded) document.getElementById(`L${target}`)?.scrollIntoView({ block: "center" });
  }, [target, targetLoaded]);

  return (
    <section aria-label="Log">
      <p className="mb-2 text-xs text-neutral-500">
        {lines === null ? "Loading log…" : `${lines.length} lines`}
        {running && " · run in progress, refreshing every 5 s"}
        {target !== null && lines !== null && !targetLoaded && ` · line ${target} is not in the log yet`}
      </p>
      {error && <p className="mb-3 text-sm text-red-600">Could not load the log: {error}</p>}
      {lines && lines.length > 0 && (
        <ol className="overflow-hidden rounded-lg border border-neutral-200 font-mono text-xs leading-5 dark:border-neutral-800">
          {lines.map((line, i) => {
            const n = i + 1;
            const hit = n === target;
            return (
              <li
                key={n}
                id={`L${n}`}
                className={`flex scroll-mt-16 ${
                  hit ? "bg-amber-100 dark:bg-amber-900/40" : "hover:bg-neutral-50 dark:hover:bg-neutral-900"
                }`}
              >
                <a
                  href={`#L${n}`}
                  aria-current={hit ? "location" : undefined}
                  className="w-12 shrink-0 select-none pr-2 text-right tabular-nums text-neutral-500 hover:underline"
                >
                  {n}
                </a>
                <code
                  className={`min-w-0 flex-1 whitespace-pre-wrap break-all pr-2 ${
                    line.startsWith("METRIC ") ? "font-semibold" : ""
                  }`}
                >
                  {line || " "}
                </code>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
