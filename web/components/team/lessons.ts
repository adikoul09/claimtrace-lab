// Pure helpers for the Team tab's Lessons panel (SPEC §6).

const IMPORT_LABEL = /^imported from round 0 audit\s*[:\-–—]?\s*/i;

/**
 * Round 0 lessons (MatchDG F1–F9) are imported, not learned here, and must say so (SPEC §6).
 * The schema has no source column, so the contract is: tag `round0`, or text starting "Imported from Round 0 audit".
 */
export function isImported(lesson: { tags: string[]; text: string }): boolean {
  return lesson.tags.some((t) => t.toLowerCase() === "round0") || IMPORT_LABEL.test(lesson.text);
}

/** The lesson text without the import label (the badge shows it instead). */
export function lessonText(lesson: { text: string }): string {
  return lesson.text.replace(IMPORT_LABEL, "");
}

/** Most applied first, then newest. */
export function sortLessons<T extends { times_applied: number; created_at: string }>(lessons: T[]): T[] {
  return [...lessons].sort(
    (a, b) => b.times_applied - a.times_applied || Date.parse(b.created_at) - Date.parse(a.created_at),
  );
}
