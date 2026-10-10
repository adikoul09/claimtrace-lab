"""How a step's task input is filled from the outputs of earlier steps (docs/CONTRACTS.md §3), and what a decision
does to an awaiting task (§6). Pure functions; loop.py does the reads and writes."""
from __future__ import annotations

from typing import Optional

from lab.schemas import PlanStep

DATA_DIR = "../../data"            # from runs/<project_id>/ to the repo's data/ folder on every executor
SMOKE_ARGS = {"epochs": 1, "subset": 5000, "seed": 0}
DECISION_STATUS = {"approve": "queued", "reject": "rejected", "redirect": "rejected"}


def status_after(decision: str) -> str:
    return DECISION_STATUS[decision]


def _latest_done(tasks: list[dict]) -> Optional[dict]:
    done = [t for t in tasks if t.get("status") == "done"]
    return max(done, key=lambda t: t.get("created_at") or "") if done else None


def done_by_step(step_tasks: list[dict], before: int) -> dict[int, dict]:
    """step index -> its latest done task, for steps before `before`."""
    out = {}
    for i in range(before):
        t = _latest_done([t for t in step_tasks if (t.get("input") or {}).get("step") == i])
        if t:
            out[i] = t
    return out


def upstream(steps: list[PlanStep], step_tasks: list[dict], i: int, debugs: list[dict] = ()) -> dict[str, str]:
    """{capability: task_id} of the latest done task of each earlier step; a later step of the same capability wins,
    so at `compare` the `run` entry is the full run. Includes the latest done `debug` task, if any."""
    up = {steps[j].capability: t["id"] for j, t in sorted(done_by_step(step_tasks, i).items())}
    d = _latest_done(list(debugs))
    if d:
        up["debug"] = d["id"]
    return up


def _output_of(steps, step_tasks, i, capability) -> dict:
    found = [t for j, t in sorted(done_by_step(step_tasks, i).items()) if steps[j].capability == capability]
    return (found[-1].get("output") or {}) if found else {}


def run_input(steps: list[PlanStep], step_tasks: list[dict], debugs: list[dict], i: int,
              workdir: str) -> tuple[dict, list[str]]:
    """The worker fields of run step i, plus `experiment` (the experiments row to create). Problems list what an
    earlier step did not provide; nothing is invented to fill a gap."""
    step, problems = steps[i], []
    code = _output_of(steps, step_tasks, i, "write_code")
    env = _output_of(steps, step_tasks, i, "setup_env")
    design = _output_of(steps, step_tasks, i, "design_experiment")
    files, requirements = code.get("files"), env.get("requirements")
    for d in sorted([d for d in debugs if d.get("status") == "done"], key=lambda d: d.get("created_at") or ""):
        out = d.get("output") or {}
        files = out.get("files") or files
        requirements = out.get("requirements") or requirements
    if not (files or {}).get("train.py"):
        problems.append("no train.py: the write_code step's output has no files['train.py']")
    if not requirements:
        problems.append("no requirements: the setup_env step's output has no requirements")

    config = dict(design.get("config") or {})
    budget_reason = None
    if step.scale == "full":
        b = _output_of(steps, step_tasks, i, "budget")
        missing = [k for k in ("epochs", "subset") if b.get(k) is None]
        if missing:
            problems.append(f"the budget step's output has no {' or '.join(missing)}")
        seeds = b.get("seeds") or [0]
        args = {"epochs": b.get("epochs"), "subset": b.get("subset"), "seed": seeds[0]}
        config["budget"] = {"epochs": b.get("epochs"), "subset": b.get("subset"), "seeds": seeds}
        budget_reason = b.get("reason")
    else:
        args = dict(SMOKE_ARGS)
    cmd = (f"python train.py --data-dir {DATA_DIR} --epochs {args['epochs']} --subset {args['subset']} "
           f"--seed {args['seed']}")
    config.update({"scale": step.scale, "cmd": cmd})
    return {"cmd": cmd, "cwd": workdir, "files": files, "requirements": requirements, "network": True,
            "network_reason": "dataset download if this executor lacks it",
            "experiment": {"label": step.title, "config": config, "margin": design.get("margin"),
                           "budget_reason": budget_reason}}, problems
