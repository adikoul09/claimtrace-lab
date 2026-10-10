// Research notes (SPEC §10): the edited copy lives in the private Storage bucket `notes` as <project id>.md.
export const NOTES_BUCKET = "notes";
export const NOTES_MAX_BYTES = 200_000;

export const notesObject = (projectId: string) => `${projectId}.md`;

/** Validate a PUT body {markdown}: the notes are stored exactly as written. */
export function planNotes(
  body: Record<string, unknown>,
): { ok: true; markdown: string } | { ok: false; status: number; error: string } {
  const md = body.markdown;
  if (typeof md !== "string") return { ok: false, status: 400, error: "send {markdown: string}" };
  if (!md.trim()) return { ok: false, status: 400, error: "the notes are empty" };
  const bytes = new TextEncoder().encode(md).length;
  if (bytes > NOTES_MAX_BYTES)
    return { ok: false, status: 413, error: `the notes are ${bytes} bytes; the limit is ${NOTES_MAX_BYTES}` };
  return { ok: true, markdown: md };
}
