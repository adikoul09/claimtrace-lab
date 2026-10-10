"""Data-step check: run a table's data steps (links.json) on two commits, each in a clean worktree, and compare every
file they produce (sha256). A branch or harness change to a data step must leave the baseline's files byte-identical;
new files are allowed and listed. This is the check that shows h0's coupling (PROGRESS.md, Phase 3): appending a value
to the generator's list shifts the random stream of every later file."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from el01.env.builder import venv_python
from el01.run.runner import Job, run_jobs
from el01.run.worktrees import ensure_worktree


def _untracked(wt: Path) -> dict[str, str]:
    p = subprocess.run(["git", "-C", str(wt), "ls-files", "--others", "-z"], capture_output=True, text=True,
                       check=True)
    out = {}
    for rel in sorted(x for x in p.stdout.split("\0") if x):
        out[rel] = hashlib.sha256((wt / rel).read_bytes()).hexdigest()
    return out


def produce(ctx, table: str, sha: str, name: str) -> dict:
    """Run the data steps of `table` at `sha` in a clean worktree; {"files": {path: sha256}, "jobs": [...]}"""
    links = ctx.links
    t = next(x for x in links["tables"] if x["target"] == table)
    wt, sha = ensure_worktree(ctx.repo, sha, ctx.paths.worktrees / ctx.cfg.id / "datacheck" / name)
    subprocess.run(["git", "-C", str(wt), "clean", "-ffdxq"], check=True)
    run_dir = ctx.paths.audit_dir(ctx.cfg.id) / "runs" / "datacheck" / name
    if run_dir.exists():
        import shutil
        shutil.rmtree(run_dir)
    jobs = [Job(f"data{i}_{s['name']}", wt, s["argv"], network=ctx.cfg.link.data_network)
            for i, s in enumerate(t.get("data_steps") or [])]
    res = run_jobs(run_dir, jobs, max_parallel=1, python=venv_python(ctx.paths.envs / ctx.cfg.id))
    return {"commit": sha, "files": _untracked(wt),
            "jobs": [{"name": j.name, "argv": list(j.argv), "exit_code": res["status"][j.name]["exit_code"],
                      "log": ctx.rel(run_dir / j.log_name)} for j in jobs]}


def compare(a: dict, b: dict) -> dict:
    fa, fb = a["files"], b["files"]
    same = sorted(k for k in fa if k in fb and fa[k] == fb[k])
    changed = sorted(k for k in fa if k in fb and fa[k] != fb[k])
    return {"same": len(same), "changed": changed, "only_baseline": sorted(set(fa) - set(fb)),
            "new": sorted(set(fb) - set(fa))}


def data_step_check(ctx, table: str, base_sha: str, sha: str, name: str) -> dict:
    cache = getattr(ctx, "_data_base", None)
    if cache is None:
        cache = ctx._data_base = {}
    if (table, base_sha) not in cache:
        cache[(table, base_sha)] = produce(ctx, table, base_sha, "baseline")
    a = cache[(table, base_sha)]
    b = produce(ctx, table, sha, name)
    c = compare(a, b)
    bad = [j for j in a["jobs"] + b["jobs"] if j["exit_code"] != 0]
    ok = not bad and not c["changed"] and not c["only_baseline"]
    reason = ("data step failed: " + ", ".join(j["log"] for j in bad) if bad else
              f"{len(c['changed'])} of the baseline's files change and {len(c['only_baseline'])} disappear "
              f"(e.g. {(c['changed'] + c['only_baseline'])[0]})" if not ok else
              f"the baseline's {c['same']} files are byte-identical; {len(c['new'])} new")
    return {"pass": ok, "reason": reason, **c, "changed_count": len(c["changed"]), "new_count": len(c["new"]),
            "baseline_jobs": a["jobs"], "jobs": b["jobs"]}
