"""Routing (SPEC §3.4, §8): which executor caps a task needs, which executors are alive, which running tasks are stale.

Every task gets non-empty required_caps: claim_task() hands a task to any worker whose caps contain them, so empty
caps would let any worker take anything.
  parse          LLM-only work on text (paper, design, analysis, report)
  train          work that writes or uses the run folder: code, environment, debug, runs (kept on the same machines)
  smoke / heavy  smoke runs / full-budget runs (only laptop-a has heavy)
  controller     the controller's own `plan` tasks; no worker has this cap
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from lab.controller.rules import STALE_HEARTBEAT_S
from lab.schemas import CAPABILITIES

CONTROLLER_NAME = "controller"
CONTROLLER_CAP = "controller"

RUNDIR_CAPABILITIES = ("write_code", "setup_env", "debug")


def required_caps(capability: str, scale: Optional[str] = None) -> list[str]:
    if capability == "plan":
        return [CONTROLLER_CAP]
    if capability not in CAPABILITIES:
        raise ValueError(f"unknown capability {capability!r}")
    if capability == "run":
        return ["train", "heavy"] if scale == "full" else ["smoke", "train"]
    if capability in RUNDIR_CAPABILITIES:
        return ["train"]
    return ["parse"]


def parse_ts(s: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def heartbeat_age(executor: Optional[dict], now: datetime) -> Optional[float]:
    ts = parse_ts(executor.get("last_heartbeat")) if executor else None
    return (now - ts).total_seconds() if ts else None


def is_live(executor: dict, now: datetime) -> bool:
    age = heartbeat_age(executor, now)
    return age is not None and age <= STALE_HEARTBEAT_S


def eligible(caps: list[str], executors: list[dict], now: datetime) -> list[dict]:
    """Live executors that have every cap, least capable first (light work prefers the light machine)."""
    ok = [e for e in executors if is_live(e, now) and set(caps) <= set(e.get("caps") or [])]
    return sorted(ok, key=lambda e: (len(e.get("caps") or []), bool(e.get("busy")), e["name"]))


def stale_tasks(tasks: list[dict], executors: list[dict], now: datetime) -> list[dict]:
    """Running tasks on a worker whose heartbeat is missing or older than STALE_HEARTBEAT_S, with the reason."""
    by_name = {e["name"]: e for e in executors}
    out = []
    for t in tasks:
        name = t.get("executor")
        if t.get("status") != "running" or not name or name == CONTROLLER_NAME:
            continue
        age = heartbeat_age(by_name.get(name), now)
        if age is None:
            reason = f"executor {name} has no heartbeat on record"
        elif age > STALE_HEARTBEAT_S:
            reason = f"executor {name} last heartbeat {age:.0f} s ago (limit {STALE_HEARTBEAT_S} s)"
        else:
            continue
        out.append({"task": t, "age_s": None if age is None else round(age, 1), "reason": reason})
    return out
