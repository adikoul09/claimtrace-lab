"""Plan progress: the plan is a linear list of steps; a step's task is created only when the step before it is done.

(tasks.status has no "waiting on a dependency" value, and claim_task() would hand out any queued row, so a step that
is not ready must not exist as a row yet.)"""
from __future__ import annotations

from typing import Optional

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
