// Pure helpers for the log viewer and its server route.

/** Lines numbered from 1 exactly as the worker numbers them (one per stdout line). */
export function splitLog(text: string): string[] {
  if (!text) return [];
  const lines = text.split("\n").map((l) => l.replace(/\r$/, ""));
  if (lines[lines.length - 1] === "") lines.pop(); // the worker ends the file with a newline
  return lines;
}

/** "#L12" → 12; anything else → null. */
export function lineFromHash(hash: string): number | null {
  const m = /^#L([1-9]\d*)$/.exec(hash);
  return m ? Number(m[1]) : null;
}

/** experiments.log_path "logs/<name>.log" → the object name in the private `logs` bucket, or null. */
export function logObject(logPath: string | null): string | null {
  const m = /^logs\/([A-Za-z0-9_-]+\.log)$/.exec(logPath ?? "");
  return m ? m[1] : null;
}

export const isUuid = (s: string) =>
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(s);
