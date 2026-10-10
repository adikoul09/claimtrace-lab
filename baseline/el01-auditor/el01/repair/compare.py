"""Compare the repair agent's commits with reference commits (the acceptance check of Phase 3).

The reference commits are arguments (`--ours`, `--hypothesis`), never constants of the code under test.
  - commits: each reference commit is matched with the agent commit that changes the same files and removes the same
    original lines. Levels: `identical` (same lines removed, same new text up to trailing whitespace), `same lines`
    (same lines removed, different new text), `different`.
  - runs: the smoke command (train + eval) on the agent's final branch and on the reference hypothesis commit; and on
    `el01/repair` and the last reference repair with the test domain set to a value the shipped generator builds.
    Both run on this machine, now. Metric lines must be identical; every compared number cites its log line."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Callable, Optional

from el01.config import AuditConfig, Paths
from el01.env.builder import venv_python
from el01.ingest.repo import resolve
from el01.repair.inertness import metric_lines
from el01.repair.policy import parse_unified_diff


def _show(repo: Path, sha: str) -> str:
    from el01.repair.agent import _git
    return _git(repo, "show", "--format=", "--no-color", sha).stdout


def _subject(repo: Path, sha: str) -> str:
    from el01.repair.agent import _git
    return _git(repo, "show", "-s", "--format=%s", sha).stdout.strip()


def diff_signature(diff: str) -> dict:
    files = parse_unified_diff(diff)
    return {"files": sorted(f.path for f in files),
            "removed": sorted(f"{f.path}:{n}" for f in files for n, _ in f.removed),
            "removed_text": sorted(f"{f.path}:{l.rstrip()}" for f in files for _, l in f.removed),
            "added_text": sorted(f"{f.path}:{l.rstrip()}" for f in files for _, l in f.added)}


def equivalence(ours: dict, agent: dict) -> str:
    if ours["files"] != agent["files"] or ours["removed"] != agent["removed"]:
        return "different"
    norm = lambda xs: sorted(" ".join(x.split()) for x in xs)  # whitespace-insensitive
    return "identical" if norm(ours["added_text"]) == norm(agent["added_text"]) else "same lines"


def _match(repo: Path, refs: list[str], agent: list[dict]) -> list[dict]:
    sigs = [(a, diff_signature(_show(repo, a["commit"]))) for a in agent]
    out = []
    for ref in refs:
        sha = resolve(repo, ref)
        sig = diff_signature(_show(repo, sha))
        best = None
        for a, s in sigs:
            level = equivalence(sig, s)
            rank = {"identical": 2, "same lines": 1, "different": 0}[level]
            if best is None or rank > best[0]:
                best = (rank, level, a, s)
        row = {"ours": sha, "ours_subject": _subject(repo, sha), "ours_files": sig["files"],
               "ours_removed": sig["removed"]}
        if best is None or best[0] == 0:
            row.update({"agent": None, "level": "different", "equivalent": False})
        else:
            _, level, a, s = best
            row.update({"agent": a["commit"], "agent_subject": _subject(repo, a["commit"]), "agent_files": s["files"],
                        "agent_removed": s["removed"], "level": level, "equivalent": True})
        out.append(row)
    return out


def _with_test_domain(cmd: list[str], value: str) -> list[str]:
    cmd = list(cmd)
    if "--test_domains" in cmd:
        i = cmd.index("--test_domains") + 1
        j = i
        while j < len(cmd) and not cmd[j].startswith("--"):
            j += 1
        cmd[i:j] = [value]
    return cmd


def _run_pair(ctx, label: str, agent_ref: str, our_ref: str, command=None, eval_command=None) -> dict:
    from el01.repair.agent import _remove_worktree, run_smoke
    runs = {}
    for who, ref in (("agent", agent_ref), ("ours", our_ref)):
        sha = resolve(ctx.repo, ref)
        run_dir = ctx.runs_dir / label / who
        run = run_smoke(ctx, run_dir, sha, f"cmp-{label}-{who}-{sha[:7]}", command, eval_command)
        _remove_worktree(ctx.repo, run.pop("_wt"))
        lines = {}
        for j in run["jobs"]:
            if j["name"] != "datagen":
                lines[j["name"]] = [{"log": j["log"], "line": n, "text": t}
                                    for n, t in metric_lines(ctx.audit_dir / j["log"])]
        runs[who] = {"ref": ref, "commit": sha, "ok": run["ok"], "jobs": run["jobs"], "metric_lines": lines,
                     "failure": None if run["failure"] is None else
                     {k: run["failure"].get(k) for k in ("class", "location", "log", "log_line")}}
    a, o = runs["agent"], runs["ours"]
    same = a["ok"] and o["ok"] and all(
        [x["text"] for x in a["metric_lines"].get(k, [])] == [x["text"] for x in o["metric_lines"].get(k, [])]
        for k in set(a["metric_lines"]) | set(o["metric_lines"]))
    finals = {}
    for who in ("agent", "ours"):
        finals[who] = [f"{x['text']}  ({x['log']}:{x['line']})" for k in runs[who]["metric_lines"]
                       for x in runs[who]["metric_lines"][k] if "Final" in x["text"] or "Per Domain" in x["text"]]
    n = {who: sum(len(v) for v in runs[who]["metric_lines"].values()) for who in runs}
    return {"label": label, "command": command, "runs": runs, "both_ran": a["ok"] and o["ok"],
            "metric_lines_identical": same, "metric_lines_compared": n, "final_lines": finals}


def compare(paths: Paths, cfg: AuditConfig, ours: list[str], hypothesis: Optional[str], test_domain: Optional[str],
            echo: Callable[[str], None] = print) -> dict:
    from el01.repair.agent import Ctx
    audit_dir = paths.audit_dir(cfg.id)
    rec = json.loads((audit_dir / "repair.json").read_text())
    repo = paths.repos / Path(cfg.repo.url.rstrip("/")).name.removesuffix(".git")
    ctx = Ctx(paths, cfg, repo, audit_dir, audit_dir / "repair", audit_dir / "runs" / "repair_compare",
              paths.worktrees / cfg.id / "compare", paths.worktrees / cfg.id / "repair-git",
              venv_python(paths.envs / cfg.id), None, echo, [])
    if ctx.runs_dir.exists():  # each comparison is a fresh measurement; never mix it with an earlier one
        shutil.rmtree(ctx.runs_dir)
    out = {"audit": cfg.id, "agent_verdict": rec["verdict"], "agent_branches": rec.get("branches"),
           "repair_count": {"agent": len(rec["repairs"]), "ours": len(ours),
                            "equal": len(rec["repairs"]) == len(ours)},
           "repairs": _match(repo, ours, rec["repairs"]), "hypothesis": None, "runs": [],
           "inertness": [{"repair": i["repair"], "verdict": i["verdict"], "summary": i["summary"]}
                         for i in rec.get("inertness", [])]}
    loop_hyps = [h for h in rec["hypotheses"] if h.get("run_by_loop")]
    if hypothesis:
        out["hypothesis"] = _match(repo, [hypothesis], loop_hyps)[0]
        out["hypothesis"]["agent_finding"] = next((h["finding"] for h in loop_hyps
                                                   if h["commit"] == out["hypothesis"]["agent"]), None)
    final_branch = loop_hyps[-1]["branch"] if loop_hyps else "el01/repair"
    if hypothesis:
        echo(f"smoke run: {final_branch} vs {hypothesis[:7]}")
        out["runs"].append(_run_pair(ctx, "final", final_branch, hypothesis))
    if ours and test_domain is not None:
        echo(f"smoke run, test domain {test_domain}: el01/repair vs {ours[-1][:7]}")
        out["runs"].append(_run_pair(ctx, f"repairs_test_{test_domain}", "el01/repair", ours[-1],
                                     _with_test_domain(cfg.smoke.command, test_domain),
                                     _with_test_domain(cfg.smoke.eval, test_domain) if cfg.smoke.eval else None))
    out["pass"] = (out["repair_count"]["equal"] and all(r["equivalent"] for r in out["repairs"])
                   and (out["hypothesis"] is None or out["hypothesis"]["equivalent"])
                   and all(r["both_ran"] and r["metric_lines_identical"] for r in out["runs"])
                   and all(i["verdict"] == "inert" for i in out["inertness"]))
    (audit_dir / "repair" / "compare.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    return out
