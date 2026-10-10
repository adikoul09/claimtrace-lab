"""Run as shipped: the smoke command at the audited commit, unmodified, in the date-pinned env; classify the failure.

Two run directories, because data is fetched or generated in its own step (spec section 4, "Data handling"):
  audits/<id>/runs/shipped_data/   the repo's own data generation (audit.yaml smoke.data)
  audits/<id>/runs/shipped/        the smoke command (audit.yaml smoke.command), e.g. ERM with 1 seed
The classified failure goes to runs/shipped/failure.json, and a summary that cites log lines (relative to the audit
folder) to audits/<id>/run_as_shipped.json."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from el01.config import AuditConfig, Paths
from el01.env.builder import build_env, parse_lock, venv_python
from el01.ingest.repo import ensure_clone, resolve
from el01.run.classify import classify
from el01.run.runner import Job, run_jobs
from el01.run.worktrees import ensure_worktree


def _job_summary(audit_dir: Path, run_dir: Path, job: Job, st: dict) -> dict:
    return {"command": list(job.argv), "seeds": job.seeds, "status": st["status"], "exit_code": st["exit_code"],
            "seconds": st["seconds"], "start_utc": st["start_utc"], "end_utc": st["end_utc"],
            "log": (run_dir / job.log_name).relative_to(audit_dir).as_posix()}


def run_shipped(paths: Paths, cfg: AuditConfig, echo: Callable[[str], None] = print) -> dict:
    if cfg.smoke is None:
        raise ValueError(f"audits/{cfg.id}/audit.yaml has no smoke command")
    env = build_env(paths, cfg, echo=lambda s: None)  # cached unless the plan changed
    repo = ensure_clone(cfg.repo.url, paths.repos / Path(cfg.repo.url.rstrip("/")).name.removesuffix(".git"))
    sha = resolve(repo, cfg.repo.commit)
    wt, _ = ensure_worktree(repo, sha, paths.worktrees / cfg.id / "shipped")
    py = venv_python(paths.envs / cfg.id)
    audit_dir = paths.audit_dir(cfg.id)
    budget = dict(max_parallel=cfg.budget.jobs, wall_minutes=cfg.budget.max_wall_minutes, python=py, echo=echo)
    freeze = parse_lock("\n".join(env["freeze"]))
    summary = {"audit": cfg.id, "repo": cfg.repo.url, "commit": sha,
               "env": {"python": env["python"]["installed"], "torch": freeze.get("torch"), "numpy": freeze.get("numpy"),
                       "plan_hash": env["plan_hash"], "report": "env.json"},
               "data_step": None}

    if cfg.smoke.data:
        data_dir = audit_dir / "runs" / "shipped_data"
        job = Job("datagen", wt, cfg.smoke.data)
        res = run_jobs(data_dir, [job], **budget)
        summary["data_step"] = _job_summary(audit_dir, data_dir, job, res["status"]["datagen"])

    run_dir = audit_dir / "runs" / "shipped"
    job = Job(cfg.smoke.name, wt, cfg.smoke.command, seeds=cfg.smoke.seeds)
    res = run_jobs(run_dir, [job], **budget)
    st = res["status"][job.name]
    summary["run"] = _job_summary(audit_dir, run_dir, job, st)
    failure = None
    if st["status"] != "done":
        failure = classify(run_dir / job.log_name, log_roots=[str(wt)], source_root=wt, inside=[wt, paths.workspace])
        if failure is None:
            failure = {"class": "other", "rule": "non-zero exit without a Python traceback", "location": None}
        failure["log"] = summary["run"]["log"]
        (run_dir / "failure.json").write_text(json.dumps(failure, indent=1))
    summary["outcome"] = "ran" if failure is None else "failed"
    summary["failure"] = None if failure is None else {
        k: failure.get(k) for k in ("class", "rule", "exception", "message", "location", "origin", "raised_at",
                                    "missing_path", "same_name_in_worktree", "log", "log_line", "traceback_line")}
    (audit_dir / "run_as_shipped.json").write_text(json.dumps(summary, indent=1))
    return summary
