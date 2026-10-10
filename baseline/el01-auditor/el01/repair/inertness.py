"""Inertness check for a compatibility repair (spec section 4): a test, not a claim.

  1. Without the patch: the final repaired code with only this repair reverted runs the smoke command. If it runs,
     the metric lines of both runs must be identical (with/without comparison).
  2. If it crashes without the patch (the usual case), trace a short training run with the patch: the smoke command
     with `--epochs 5` (as the spike's trace_opacus.py run), counting every call into the libraries the patch names
     and every execution of the statements the patch put under a new condition. Inert = 0 calls and 0 executions.
A repair that fails, or that names neither a library nor a guarded statement, is not inert. Every count cites the
log line it was printed on (rule 3)."""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

from el01.repair.policy import guarded_statements, parse_unified_diff
from el01.run.runner import Job, run_jobs

TRACE_SCRIPT = Path(__file__).resolve().parent.parent / "run" / "trace.py"
TRACE_EPOCHS = "5"
METRIC_RE = re.compile(r"(?i)(acc|accuracy|loss|auc|f1|error)\b.*\d|\d.*\b(acc|accuracy|loss|auc)\b")
TIMING_RE = re.compile(r"(?i)\b(real|user|sys|time|seconds|elapsed)\b")


def metric_lines(log: Path) -> list[tuple[int, str]]:
    """(line number, text) of every line that reports a metric with a number; timing lines are left out."""
    out = []
    for n, line in enumerate(Path(log).read_text(errors="replace").splitlines(), 1):
        if METRIC_RE.search(line) and not TIMING_RE.search(line):
            out.append((n, line.strip()))
    return out


def patch_libraries(diff: str, root: Path) -> tuple[list[str], list[str]]:
    """Third-party top-level packages that the changed lines use as `name.attr`, where `name` is imported in that
    file; plus every module of those packages the file imports (imported before tracing starts)."""
    stdlib = set(getattr(sys, "stdlib_module_names", ()))
    libs, pre = set(), set()
    for f in parse_unified_diff(diff):
        p = Path(root) / f.path
        if not p.is_file() or p.suffix != ".py":
            continue
        try:
            tree = ast.parse(p.read_bytes())
        except SyntaxError:
            continue
        bound: dict[str, str] = {}      # name used in code -> top-level package
        modules: dict[str, set] = {}    # top-level package -> modules imported from it
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    top = a.name.split(".")[0]
                    bound[a.asname or top] = top
                    modules.setdefault(top, set()).add(a.name)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                top = node.module.split(".")[0]
                modules.setdefault(top, set()).add(node.module)
                for a in node.names:
                    bound[a.asname or a.name] = top
                    modules[top].add(f"{node.module}.{a.name}")
        used = {m.group(1) for _, l in f.added + f.removed for m in re.finditer(r"\b([A-Za-z_]\w*)\s*\.", l)}
        for name in used:
            top = bound.get(name)
            if not top or top in stdlib or (Path(root) / f"{top}.py").exists() or (Path(root) / top).is_dir():
                continue
            libs.add(top)
            pre |= {m for m in modules.get(top, ()) if m != top}
    return sorted(libs), sorted(pre)


def map_lines(stmts: list[dict], root: Path) -> list[str]:
    """file:line of each guarded statement in the code at `root` (nearest line with the same text)."""
    out = []
    for s in stmts:
        p = Path(root) / s["file"]
        if not p.is_file():
            continue
        src = p.read_text(errors="replace").splitlines()
        cands = [k for k, l in enumerate(src, 1) if l.strip() == s["text"]]
        if cands:
            out.append(f"{s['file']}:{min(cands, key=lambda k: abs(k - s['line']))}")
    return out


def _cite(log: Path, prefix: str) -> int | None:
    for n, line in enumerate(Path(log).read_text(errors="replace").splitlines(), 1):
        if line.startswith(prefix):
            return n
    return None


def check_inertness(ctx, r: dict, final: dict) -> dict:
    """`ctx`: the repair loop's context; `r`: the repair record; `final`: the last successful run."""
    from el01.repair.agent import _git, _remove_worktree, _scratch, run_smoke
    sha7 = r["commit"][:7]
    base_dir = ctx.runs_dir / f"inertness_{sha7}"
    res = {"repair": r["commit"], "class": r["class"], "message": r["message"], "without": None, "trace": None}
    diff = (ctx.audit_dir / r["patch"]).read_text()

    # 1. the final code without this repair
    _scratch(ctx.repo, ctx.scratch, final["head"])
    p = _git(ctx.scratch, "revert", "--no-edit", r["commit"], check=False)
    if p.returncode != 0:
        _git(ctx.scratch, "revert", "--abort", check=False)
        res["without"] = {"ran": False, "note": f"revert does not apply: {p.stderr.strip()[:300]}"}
    else:
        w = _git(ctx.scratch, "rev-parse", "HEAD").stdout.strip()
        run = run_smoke(ctx, base_dir / "without", w, f"inert-{sha7}-without")
        wt = run.pop("_wt")
        _remove_worktree(ctx.repo, wt)
        f = run["failure"]
        res["without"] = {"commit": w, "ran": run["ok"], "jobs": run["jobs"],
                          "failure": None if f is None else {k: f.get(k) for k in
                                                             ("class", "exception", "location", "log", "log_line")}}
        if run["ok"]:
            diffs = []
            for j in run["jobs"]:
                if j["name"] == "datagen":
                    continue
                a = metric_lines(final["run_dir"] / Path(j["log"]).name)
                b = metric_lines(ctx.audit_dir / j["log"])
                if [t for _, t in a] != [t for _, t in b]:
                    diffs.append(j["name"])
            res["method"] = "with/without comparison"
            res["verdict"] = "inert" if not diffs else "not inert"
            res["summary"] = ("runs without the patch; metric lines identical" if not diffs else
                              f"runs without the patch; metric lines differ in {', '.join(diffs)}")
            (ctx.out_dir / f"inertness_{sha7}.json").write_text(json.dumps(res, indent=1))
            return res

    # 2. trace a short run with the patch
    wt = Path(final["worktree"])
    libs, pre = patch_libraries(diff, wt)
    lines = map_lines(guarded_statements(diff), wt)
    cmd = list(ctx.cfg.smoke.command)
    if "--epochs" in cmd and cmd.index("--epochs") + 1 < len(cmd):
        cmd[cmd.index("--epochs") + 1] = TRACE_EPOCHS
    run_dir = base_dir / "trace"
    out = run_dir / "trace.json"
    argv = ["python", str(TRACE_SCRIPT), "--out", str(out)]
    for l in libs:
        argv += ["--lib", l]
    for m in pre:
        argv += ["--preimport", m]
    for l in lines:
        argv += ["--line", l]
    argv += ["--", *cmd[1:]]
    job = Job("trace", wt, argv)
    st = run_jobs(run_dir, [job], max_parallel=1, wall_minutes=ctx.cfg.budget.max_wall_minutes,
                  python=ctx.py)["status"]["trace"]
    log = run_dir / job.log_name
    t = json.loads(out.read_text()) if out.exists() else {}
    res["method"] = "trace of a short run with the patch"
    res["trace"] = {"command": cmd, "epochs": TRACE_EPOCHS if "--epochs" in cmd else None, "libs": libs,
                    "preimported": t.get("preimported"), "lines": lines, "exit_code": st["exit_code"],
                    "outcome": t.get("outcome"), "lib_calls_total": t.get("lib_calls_total"),
                    "lib_calls": t.get("lib_calls"), "lib_module_bodies_total": t.get("lib_module_bodies_total"),
                    "line_hits": t.get("line_hits"), "log": ctx.rel(log),
                    "log_line_lib_calls": _cite(log, "TRACE_LIB_CALLS_TOTAL"),
                    "log_line_line_hits": _cite(log, "TRACE_LINE_HITS")}
    calls = t.get("lib_calls_total")
    hits = sum((t.get("line_hits") or {}).values())
    if not libs and not lines:
        res["verdict"], res["summary"] = "not inert", "the patch names no library and guards no statement: not checkable"
    elif t.get("outcome") != "completed":
        res["verdict"], res["summary"] = "not inert", f"the traced run did not complete ({t.get('outcome') or 'no result'})"
    elif calls == 0 and hits == 0:
        res["verdict"] = "inert"
        res["summary"] = (f"{calls} calls into {', '.join(libs) or '-'} and {hits} executions of "
                          f"{', '.join(lines) or '-'} during a {TRACE_EPOCHS}-epoch run "
                          f"({ctx.rel(log)}:{res['trace']['log_line_lib_calls']})")
    else:
        res["verdict"] = "not inert"
        res["summary"] = f"{calls} calls into {', '.join(libs)}; {hits} executions of guarded statements"
    (ctx.out_dir / f"inertness_{sha7}.json").write_text(json.dumps(res, indent=1))
    return res
