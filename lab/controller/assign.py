"""Assign (SPEC §3.3): the active agent with the capability and the highest rolling reward gets the task."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

from lab.controller.rules import NEUTRAL_REWARD, ROLLING_WINDOW


@dataclass
class Pick:
    agent: dict
    score: Optional[float]   # None: no scored task yet
    reason: str


def rolling_means(rewards: list[dict]) -> dict[str, float]:
    """agent_id -> mean reward over its last ROLLING_WINDOW scored tasks."""
    per: dict[str, list[dict]] = defaultdict(list)
    for r in rewards:
        per[r["agent_id"]].append(r)
    out = {}
    for agent_id, rows in per.items():
        last = sorted(rows, key=lambda r: r["ts"], reverse=True)[:ROLLING_WINDOW]
        out[agent_id] = sum(float(r["reward"]) for r in last) / len(last)
    return out


def pick_agent(agents: list[dict], capability: str, scores: dict[str, float]) -> Optional[Pick]:
    """None means a gap: no active agent has this capability."""
    cands = [a for a in agents if a.get("status") == "active" and capability in (a.get("capabilities") or [])]
    if not cands:
        return None
    best = max(cands, key=lambda a: (scores.get(a["id"], NEUTRAL_REWARD), a.get("version") or 1, a["name"]))
    score = scores.get(best["id"])
    why = (f"rolling reward {score:.2f}" if score is not None
           else f"no scored tasks yet (prior {NEUTRAL_REWARD:.2f})")
    n = len(cands)
    return Pick(best, score, f"{best['name']}: {why}; highest of {n} active agent{'s' if n > 1 else ''} "
                             f"with {capability}")
