// A precomputed project (T30: the MatchDG Round 0 audit loaded from the baseline's golden files) is never a live run
// and is always labelled as such (SPEC §14). Marked by projects.status = 'precomputed' or a 'precomputed' tag.
export const PRECOMPUTED_LABEL = "Precomputed — Round 0 audit";

export function isPrecomputed(p: { status?: string | null; tags?: string[] | null } | null | undefined): boolean {
  return !!p && (p.status === "precomputed" || (p.tags ?? []).includes("precomputed"));
}
