"""What-if fan-out sequencing (SPEC §7.4, docs/CONTRACTS.md §5b). B2's handlers design the branches and rank them;
the controller only creates the tasks in order:

  design_whatif done  →  one smoke run per branch (experiments row = branch.experiment as given)
  every branch smoke done or failed  →  one compare with input.whatif_task_id (the ranking)
  ranking done with an extend  →  the full run of that branch, requires_approval (awaiting_approval)
  extend run done  →  one compare with input.extend_experiment_id (graded like a reproduction)

Every task the controller creates for a what-if carries input.whatif_of = the design_whatif task id (its "family").
Pure functions; loop.py does the reads and writes."""
from __future__ import annotations

from typing import Optional

from lab.controller.rules import RUN_TIMEOUT_FLOOR_S

WAITING = ("queued", "running", "awaiting_approval")
EXPERIMENT_COLUMNS = ("label", "parent_id", "changed_key", "margin", "config", "budget_reason")


def _latest(tasks: list[dict]) -> Optional[dict]:
    return max(tasks, key=lambda t: t.get("created_at") or "") if tasks else None


def role(t: dict) -> Optional[str]:
    inp = t.get("input") or {}
    if t.get("capability") == "run":
        return "extend" if inp.get("extend_of") else "branch" if inp.get("branch_id") else None
    if t.get("capability") in ("compare", "explain_diff"):
        return "final" if inp.get("extend_experiment_id") else "rank" if inp.get("whatif_task_id") else None
    return None


def next_action(w: dict, family: list[dict]) -> tuple[str, object]:
    """("branches", [branch]) | ("rank", None) | ("extend", extend) | ("final", extend run) | ("wait", None) |
    ("finished", reason)"""
    branches = (w.get("output") or {}).get("branches") or []
    if not branches:
        return "finished", "the what-if produced no branches"
    by_role: dict[str, list[dict]] = {}
    for t in family:
        by_role.setdefault(role(t) or "", []).append(t)
    runs = {}
    for t in sorted(by_role.get("branch", []), key=lambda t: t.get("created_at") or ""):
        runs[t["input"]["branch_id"]] = t
    missing = [b for b in branches if b["id"] not in runs]
    if missing:
        return "branches", missing
    if any(t["status"] in WAITING for t in runs.values()):
        return "wait", None

    rank = _latest(by_role.get("rank", []))
    if rank is None:
        return "rank", None
    if rank["status"] in WAITING:
        return "wait", None
    if rank["status"] != "done":
        return "finished", f"the ranking compare {rank['status']}: " \
                           f"{(rank.get('output') or {}).get('error') or 'no detail recorded'}"
    extend = (rank.get("output") or {}).get("extend")
    if not extend:
        return "finished", "no branch was extended: every effect was inside the noise or its smoke run failed"

    ext = _latest(by_role.get("extend", []))
    if ext is None:
        return "extend", extend
    if ext["status"] in WAITING:
        return "wait", None
    if ext["status"] == "rejected":
        return "finished", f"the extended run was rejected by a researcher ({ext.get('decision') or 'reject'})" + \
                           (f": {ext['decision_note']}" if ext.get("decision_note") else "")
    if ext["status"] == "failed":
        out = ext.get("output") or {}
        return "finished", f"the extended run failed: {out.get('error_signature') or out.get('error') or 'no detail'}"

    fin = _latest(by_role.get("final", []))
    if fin is None:
        return "final", ext
    if fin["status"] in WAITING:
        return "wait", None
    return "finished", f"the extended branch {extend.get('branch_id')} ({extend.get('key')}={extend.get('value')}) " \
                       f"was graded ({fin['status']})"


def ready_problem(upstream: dict, tasks_by_id: dict[str, dict]) -> Optional[str]:
    """Why a what-if cannot start yet (None when it can): it branches from the reproduction's finished full run."""
    full = tasks_by_id.get(upstream.get("run") or "")
    if not full or full.get("status") != "done" or (full.get("input") or {}).get("scale") != "full":
        return "the reproduction has no finished full run to branch from yet"
    return None


def experiment_row(experiment: dict, project_id: str) -> dict:
    return {"project_id": project_id, **{k: experiment[k] for k in EXPERIMENT_COLUMNS if k in experiment},
            "status": "planned"}


def _code(parent_full: dict) -> dict:
    inp = parent_full.get("input") or {}
    return {"files": inp.get("files"), "requirements": inp.get("requirements")}


def branch_input(branch: dict, experiment_id: str, parent_full: dict, parent_smoke: Optional[dict],
                 whatif_id: str) -> dict:
    timeout = ((parent_smoke or {}).get("input") or {}).get("timeout_s") or RUN_TIMEOUT_FLOOR_S
    return {"title": f"what-if {branch['id']}: {branch['key']}={branch['value']} (smoke)",
            "label": f"what-if {branch['id']} smoke", "scale": "smoke", "cmd": branch["cmd"], "cwd": branch["cwd"],
            **_code(parent_full), "experiment_id": experiment_id, "timeout_s": max(timeout, RUN_TIMEOUT_FLOOR_S),
            "network": True, "network_reason": "dataset download if this executor lacks it", "whatif_of": whatif_id,
            "branch_id": branch["id"]}


def extend_input(extend: dict, experiment_id: str, parent_full: dict, whatif_id: str, rank_id: str) -> dict:
    timeout = (parent_full.get("input") or {}).get("timeout_s") or RUN_TIMEOUT_FLOOR_S
    return {"title": f"what-if {extend['branch_id']}: {extend['key']}={extend['value']} (full)",
            "label": f"what-if {extend['branch_id']} full", "scale": "full", "cmd": extend["cmd"],
            "cwd": extend["cwd"], **_code(parent_full), "experiment_id": experiment_id,
            "timeout_s": max(timeout, RUN_TIMEOUT_FLOOR_S), "network": True,
            "network_reason": "dataset download if this executor lacks it", "whatif_of": whatif_id,
            "branch_id": extend["branch_id"], "extend_of": rank_id, "reason": extend.get("reason")}


def rank_input(w: dict, workdir: str) -> dict:
    return {"goal": "Rank the what-if branches by code against the parent smoke run; prune effects inside the noise "
                    "and propose the branch to extend.",
            "title": "rank what-if branches", "whatif_task_id": w["id"], "whatif_of": w["id"], "workdir": workdir,
            "upstream": {**((w.get("input") or {}).get("upstream") or {}), "design_whatif": w["id"]}}


def final_input(w: dict, ext: dict, workdir: str) -> dict:
    return {"goal": "Grade the extended what-if branch like a reproduction.", "title": "grade the extended branch",
            "extend_experiment_id": ext["input"]["experiment_id"], "whatif_of": w["id"], "workdir": workdir,
            "upstream": {**((w.get("input") or {}).get("upstream") or {}), "design_whatif": w["id"],
                         "run": ext["id"]}}
