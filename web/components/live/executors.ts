// Pure helper for the header's executor status dots (PLAN T13).

/** Workers heartbeat every 10 s (SPEC §8); after 30 s without one, the dot goes grey. */
export const STALE_AFTER_S = 30;

export type ExecutorState = "idle" | "busy" | "stale";

export function executorState(
  e: { busy: boolean; last_heartbeat: string | null },
  now = Date.now(),
): ExecutorState {
  if (!e.last_heartbeat || now - Date.parse(e.last_heartbeat) > STALE_AFTER_S * 1000) return "stale";
  return e.busy ? "busy" : "idle";
}
