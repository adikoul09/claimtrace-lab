"""Phase 6 acceptance: compare the written branches with reference branches (read-only), and read the ablation.

References are arguments (`--ref h1=audit/h-select-valloss ...`, `--ref-base audit/h-paper-target-1.0`), never
constants of the code under test. For each reference:
  - its change = the HYPOTHESIS commits between the reference base and the reference (AUDIT(harness) commits left
    out), squashed, as a diff; the same squash is applied onto our baseline in a scratch worktree (nothing is written to
    the reference branches);
  - diff level against each written branch: `identical` (same removed lines, same added text up to whitespace and
    comments), `same lines` (same files, same removed lines), `covers` (every line the reference removes, ours removes
    too), `different`;
  - behaviour: the methods the reference's change reaches (2-epoch trace, as the ablation's reach) each run 1 seed at
    full length on both commits; the per-epoch metric lines must be identical.
A branch is equivalent to a reference when its diff level is not `different` and the behaviour is identical on every
method the reference reaches. The ablation part reads audits/<id>/ablation/grades.json (code's numbers) and says
whether the named arm's effect for the named method is negative with a 95% CI that excludes 0 and survives Holm."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Optional

from el01.branch import ablate as A
from el01.branch import writer as W
from el01.config import AuditConfig, Paths
from el01.ingest.repo import resolve
from el01.repair.inertness import metric_lines
from el01.repair.policy import parse_unified_diff
from el01.run.runner import Job, run_jobs

COMMENT_RE = re.compile(r"\s+#.*$")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


def signature(diff: str) -> dict:
    files = parse_unified_diff(diff)
    norm = lambda l: " ".join(COMMENT_RE.sub("", l).split())
    return {"files": sorted(f.path for f in files),
            "removed": sorted(f"{f.path}:{n}" for f in files for n, _ in f.removed),
            "added": sorted(x for f in files for _, l in f.added if (x := norm(l)) and not x.startswith("#"))}


def level(ref: dict, ours: dict) -> str:
    if ref["removed"] == ours["removed"] and ref["added"] == ours["added"]:
        return "identical"
    if ref["files"] == ours["files"] and ref["removed"] == ours["removed"]:
        return "same lines"
    if ref["removed"] and set(ref["removed"]) <= set(ours["removed"]):
        return "covers"
    return "different"


def hypothesis_commits(repo: Path, base: str, ref: str) -> list[dict]:
    out = []
    for line in _git(repo, "log", "--reverse", "--format=%H %s", f"{base}..{ref}").splitlines():
        sha, subj = line.split(" ", 1)
        out.append({"commit": sha, "subject": subj, "used": subj.startswith("HYPOTHESIS")})
    return out


def behaviour(ctx: A.Ctx, name: str, sha: str, methods: list[str], mt: dict) -> dict:
    wt = A._fresh_worktree(ctx.repo, sha, ctx.wt_root / "compare" / name)
    run_dir = ctx.runs_root / "compare" / name
    if run_dir.exists():
        shutil.rmtree(run_dir)
    data = [Job(f"data{i}", wt, a, network=ctx.cfg.link.data_network)
            for i, a in enumerate(A.data_steps(ctx.links, ctx.table))]
    run_jobs(run_dir / "data", data, max_parallel=1, python=ctx.py)
    jobs = [Job(f"train_{m}", wt, A._opt(mt[m]["train"], "--n_runs", "1"), group=mt[m]["group"]) for m in methods]
    res = run_jobs(run_dir, jobs, max_parallel=ctx.jobs, python=ctx.py)
    return {m: {"log": ctx.rel(run_dir / f"train_{m}.log"), "exit_code": res["status"][f"train_{m}"]["exit_code"],
                "lines": [t for _, t in metric_lines(run_dir / f"train_{m}.log")]} for m in methods}


def compare_refs(paths: Paths, cfg: AuditConfig, refs: dict[str, str], ref_base: str, table: str,
                 echo: Callable[[str], None] = print) -> dict:
    ctx = A.Ctx(paths, cfg, table, echo)
    rec = json.loads((ctx.audit_dir / "branches.json").read_text())
    written = [{"branch": r["branch"], "finding": f["finding"], "label": r["label"], "commit": r["commit"],
                "selfcheck": r["attempts"][-1]["pass"], "table": f["table"]}
               for f in rec["findings"] for r in f["readings"] if r["status"] == "written"]
    mt = A.table_methods(ctx.links, table)
    rbase = resolve(ctx.repo, ref_base)
    ours = {w["branch"]: signature(_git(ctx.repo, "diff", "--no-color", ctx.base, w["commit"])) for w in written}
    runs: dict = {}
    out = {"ref_base": {"ref": ref_base, "commit": rbase}, "baseline": {"ref": cfg.ablation.baseline,
                                                                         "commit": ctx.base}, "refs": {}}
    for name, ref in refs.items():
        commits = hypothesis_commits(ctx.repo, rbase, ref)
        used = [c["commit"] for c in commits if c["used"]]
        # the squash of the HYPOTHESIS commits only, applied onto our baseline (scratch; the reference is not touched)
        sq = A._branch_on(ctx, f"el01/ref-{name}", ctx.base, used, f"reference {name}: {ref} (squashed, read-only)")
        sig = signature(_git(ctx.repo, "diff", "--no-color", ctx.base, sq))
        lv = {b: level(sig, s) for b, s in ours.items()}
        cands = [b for b, l in lv.items() if l != "different"]
        echo(f"{name} ({ref}): {len(used)} HYPOTHESIS commit(s); diff candidates: "
             f"{', '.join(f'{b} ({lv[b]})' for b in cands) or 'none'}")
        reach = A.reach(ctx, f"ref-{name}", sq, mt, table)
        reached = [m for m, x in reach["methods"].items() if x["reached"]]
        rows = []
        for b in cands:
            w = next(x for x in written if x["branch"] == b)
            if f"ref-{name}" not in runs:
                runs[f"ref-{name}"] = behaviour(ctx, f"ref-{name}", sq, reached, mt)
            key = b.split("/")[-1]
            have = runs.get(key, {})
            need = [m for m in reached if m not in have]
            if need:
                runs[key] = {**have, **behaviour(ctx, f"{key}-{name}", w["commit"], need, mt)}
            per = {m: {"identical": runs[f"ref-{name}"][m]["lines"] == runs[key][m]["lines"]
                                    and runs[key][m]["exit_code"] == 0,
                       "ref_log": runs[f"ref-{name}"][m]["log"], "ours_log": runs[key][m]["log"]} for m in reached}
            ok = bool(reached) and all(v["identical"] for v in per.values())
            rows.append({"branch": b, "finding": w["finding"], "label": w["label"], "diff_level": lv[b],
                         "behaviour": per, "behaviour_identical": ok, "selfcheck_pass": w["selfcheck"],
                         "equivalent": ok and w["selfcheck"]})
            echo(f"  {b} [{w['label']}]: diff {lv[b]}; behaviour on {', '.join(reached)}: "
                 f"{'identical' if ok else 'differs on ' + ', '.join(m for m, v in per.items() if not v['identical'])}"
                 f"; self-check {'pass' if w['selfcheck'] else 'FAIL'}")
        best = next((r for r in rows if r["equivalent"]), None)
        out["refs"][name] = {"ref": ref, "commits": commits, "signature": sig, "reached": reached,
                             "candidates": rows, "equivalent_branch": best["branch"] if best else None}
        subprocess.run(["git", "-C", str(ctx.repo), "branch", "-D", f"el01/ref-{name}"], capture_output=True)
    out["pass"] = all(v["equivalent_branch"] for v in out["refs"].values())
    return out


def effect_check(paths: Paths, cfg: AuditConfig, arm_branch: str, method: str) -> dict:
    g = json.loads((paths.audit_dir(cfg.id) / "ablation" / "grades.json").read_text())
    arm = arm_branch.split("/")[-1]
    x = (g["exploratory"]["effects"].get(arm) or {}).get(method)
    if x is None:
        return {"pass": False, "reason": f"no exploratory effect for {arm}/{method}"}
    ok = x["effect"] < 0 and x["ci"][1] < 0 and x["survives_holm"]
    return {"pass": ok, "arm": arm, "method": method, "effect": x["effect"], "ci": x["ci"], "p": x["p"],
            "p_holm": x["p_holm"], "survives_holm": x["survives_holm"], "family_size": g["exploratory"]["family_size"],
            "branch_mean": x["branch_mean"], "base_mean": x["base_mean"],
            "selected_epoch_median": x.get("selected_epoch_median"), "source_val_acc": x.get("source_val_acc"),
            "cites": [f"{r['branch']['log']}:{r['branch']['line']}" for r in x["per_seed"][:2]]}
