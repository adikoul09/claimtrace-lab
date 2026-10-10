"""Plan progress: the plan is a linear list of steps; a step's task is created only when the step before it is done.

(tasks.status has no "waiting on a dependency" value, and claim_task() would hand out any queued row, so a step that
is not ready must not exist as a row yet.)"""
from __future__ import annotations

from typing import Optional

from lab.controller.rules import MAX_DEBUG_ATTEMPTS, MAX_STEP_ATTEMPTS

WAITING = ("queued", "running", "awaiting_approval")


def latest_per_step(step_tasks: list[dict]) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for t in sorted(step_tasks, key=lambda t: t.get("created_at") or ""):
        out[int(t["input"]["step"])] = t
    return out


def next_action(n_steps: int, step_tasks: list[dict]) -> tuple[str, Optional[int]]:
    """("create", i) | ("wait", None) | ("done", None) | ("failed", i) | ("rejected", i)"""
    latest = latest_per_step(step_tasks)
    if not latest:
        return ("create", 0) if n_steps else ("done", None)
    i = max(latest)
    status = latest[i]["status"]
    if status in WAITING:
        return ("wait", None)
    if status in ("failed", "rejected"):
        return (status, i)
    return ("create", i + 1) if i + 1 < n_steps else ("done", None)


def failure_action(attempts: list[dict], debugs: list[dict]) -> tuple[str, Optional[str]]:
    """After the latest attempt of a step failed: ("debug" | "wait" | "retry", None) or ("blocked", reason).

    attempts: the step's tasks; debugs: debug tasks of the project (input.failed_task_id says which failure each
    one answers). A crash (output.error_signature, extracted by code) gets a debug task before the retry
    (SPEC §7.2); any other failure is retried, and the assignment may spawn a new agent (SPEC §4.3b)."""
    attempts = sorted(attempts, key=lambda t: t.get("created_at") or "")
    if len(attempts) >= MAX_STEP_ATTEMPTS:
        return "blocked", f"the step failed {len(attempts)} times (limit {MAX_STEP_ATTEMPTS})"
    last = attempts[-1]
    if not (last.get("output") or {}).get("error_signature"):
        return "retry", None
    ds = sorted([d for d in debugs if (d.get("input") or {}).get("failed_task_id") == last["id"]],
                key=lambda d: d.get("created_at") or "")
    if not ds:
        return "debug", None
    status = ds[-1]["status"]
    if status in WAITING:
        return "wait", None
    if status == "done":
        return "retry", None
    if status == "rejected":
        return "blocked", "the debug task was rejected"
    if len(ds) >= MAX_DEBUG_ATTEMPTS:
        return "blocked", f"debugging failed {len(ds)} times (limit {MAX_DEBUG_ATTEMPTS})"
    return "debug", None
