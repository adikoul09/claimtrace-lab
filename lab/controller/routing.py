"""Routing (SPEC §3.4, §8; docs/CONTRACTS.md §1): which executor caps a task needs, which executors are alive, which
running tasks are stale.

Every task gets non-empty required_caps: claim_task() hands a task to any worker whose caps contain them, so empty
caps would let any worker take anything.
  agent          every agent step (the worker runs the agent runtime)
  smoke / train  smoke runs / full-budget runs
  controller     the controller's own `plan` tasks; no worker has this cap
  host:<name>    every worker advertises its own; once a project's first run is claimed, its later tasks carry the
                 claiming executor's host cap, so the run folder, venv and data stay on one machine
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from lab.controller.rules import STALE_HEARTBEAT_S
from lab.schemas import CAPABILITIES

CONTROLLER_NAME = "controller"
CONTROLLER_CAP = "controller"
AGENT_CAP = "agent"


def required_caps(capability: str, scale: Optional[str] = None) -> list[str]:
    if capability == "plan":
        return [CONTROLLER_CAP]
    if capability not in CAPABILITIES:
        raise ValueError(f"unknown capability {capability!r}")
    if capability == "run":
        return ["train"] if scale == "full" else ["smoke"]
    return [AGENT_CAP]


def host_pin(project_tasks: list[dict]) -> Optional[str]:
    """host:<executor> of the project's first claimed run task, or None before any run was claimed."""
    runs = [t for t in project_tasks if t.get("capability") == "run" and t.get("executor") and t.get("started_at")]
    if not runs:
        return None
    return "host:" + min(runs, key=lambda t: t["started_at"])["executor"]


def with_pin(caps: list[str], pin: Optional[str]) -> list[str]:
    return caps + [pin] if pin and pin not in caps else list(caps)


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
