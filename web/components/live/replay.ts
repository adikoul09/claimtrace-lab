// Replay labelling (SPEC §14.5): replayed LLM calls are real cached calls, and the UI always says so.

/** True while the newest llm_calls row was served from the replay cache (LLM_MODE=replay). */
export function isReplaying(latest: { mode: string } | null): boolean {
  return latest?.mode === "replay";
}

/** Events that came from an LLM call carry its mode in data.mode (lab/llm.py). */
export function eventIsReplay(data: unknown): boolean {
  return !!data && typeof data === "object" && !Array.isArray(data) && (data as { mode?: unknown }).mode === "replay";
}
