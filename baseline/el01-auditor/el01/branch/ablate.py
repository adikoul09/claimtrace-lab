"""Ablation runs (spec section 6, steps 2-5): baseline and branches on the same seeds, graded by el01/grade/ablation.py.

Run sets, each pre-registered (el01/grade/prereg.py) and committed before it starts:
  exploratory   the baseline and every written branch of the table, seeds 0..n-1 (audit.yaml seeds). Which methods a
                branch runs is decided by code before the pre-registration: the methods whose linked train command,
                traced for 2 epochs and 1 run (el01/run/trace.py), executes a line the branch added. A method the
                patch never reaches would give identical numbers (se = 0), which grade.py's effect() calls p = 0.
  confirm       the largest Holm-surviving effect of the exploratory set (code picks it), re-run on fresh seeds
                n..2n-1: the train command with --n_runs 2n on the branch and the baseline, each with an AUDIT(harness)
                commit whose data step also makes seeds n..2n-1 (data for seeds 0..n-1 byte-identical, checked);
                graded alone, on seeds n..2n-1; runs 0..n-1 are compared with the exploratory runs (determinism).
  interaction   the top two branches of different findings (largest Holm-surviving |effect|) cherry-picked into one
                commit, seeds 0..n-1, against the exploratory set's baseline runs; its effects join the exploratory
                Holm family; reported next to the sum of the two single effects (no interaction test).
Runs: one worktree per arm (workspace/worktrees/<id>/ablation/<set>/<arm>); the data step runs first in each; jobs that
share method_name and train domains in one worktree run one at a time (runner groups); up to audit.yaml's jobs.
Logs: audits/<id>/runs/ablation/<set>/<arm>/train_<method>.log (git-ignored); grades: audits/<id>/ablation/."""
from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Optional

from el01.branch import writer as W
from el01.config import AuditConfig, Paths
from el01.env.builder import venv_python
from el01.grade import ablation as G
from el01.grade import prereg as P
from el01.grade.parse import parse_epochs_all, parse_run_dir
from el01.grade.spike.rules_adapter import legacy_rules
from el01.ingest.repo import ensure_clone, resolve, tree_id
from el01.repair.policy import parse_unified_diff
from el01.run.runner import Job, run_jobs
from el01.run.worktrees import ensure_worktree

TRACE_SCRIPT = Path(__file__).resolve().parent.parent / "run" / "trace.py"
REACH_EPOCHS = "2"
BASELINE = "baseline"


class AblateError(RuntimeError):
    pass


def slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")


def _opt(argv: list[str], opt: str, value: str) -> list[str]:
    argv = list(argv)
    if opt in argv:
        argv[argv.index(opt) + 1] = value
    else:
        argv += [opt, value]
    return argv


def table_methods(links: dict, table: str) -> dict[str, dict]:
    """method key -> {label, train argv, group}: the train step of each row's linked cells (rows share one command)."""
    t = next(x for x in links["tables"] if x["target"] == table)
    out = {}
    for c in t["cells"]:
        if c["status"] != "linked":
            continue
        label = c["claim_ids"][0].split("|")[1]
        train = next((s for s in c["steps"] if s["name"] == "train"), None)
        if train is None or slug(label) in out:
            continue
        ns = train.get("namespace") or {}
        out[slug(label)] = {"label": label, "train": list(train["argv"]),
                            "group": f"{ns.get('method_name')}|{ns.get('train_domains')}"}
    return out


def data_steps(links: dict, table: str) -> list[list[str]]:
    t = next(x for x in links["tables"] if x["target"] == table)
    return [list(s["argv"]) for s in t.get("data_steps") or []]


# ---- reach: which methods execute the lines a branch added ----------------------------------------------------------

_HEADERS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Import, ast.ImportFrom)


def statement_lines(source: str, added: set[int]) -> list[int]:
    """The first line of the innermost statement around each added line. Def/class headers and imports are skipped:
    they run at import time, whether or not the code path is used."""
    tree = ast.parse(source)
    stmts = [n for n in ast.walk(tree) if isinstance(n, ast.stmt)]
    out = set()
    for n in added:
        around = [s for s in stmts if s.lineno <= n <= (s.end_lineno or s.lineno)]
        if not around:
            continue
        s = min(around, key=lambda s: (s.end_lineno or s.lineno) - s.lineno)
        if isinstance(s, _HEADERS):
            continue
        out.add(s.lineno)
    return sorted(out)


def trace_lines(wt: Path, diff: str) -> list[str]:
    lines = []
    for f in parse_unified_diff(diff):
        added = {n for n, _ in f.added}
        if not added or not f.path.endswith(".py") or not (wt / f.path).is_file():
            continue
        lines += [f"{f.path}:{n}" for n in statement_lines((wt / f.path).read_text(), added)]
    return lines


def _git_out(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


def _fresh_worktree(repo: Path, sha: str, dest: Path) -> Path:
    wt, _ = ensure_worktree(repo, sha, dest)
    subprocess.run(["git", "-C", str(wt), "clean", "-ffdxq"], check=True)
    return wt


def reach(ctx, arm: str, sha: str, methods: dict, table: str) -> dict:
    """{method: {hits, lines, exit_code, log}} for one branch: a 2-epoch, 1-run traced train run per method."""
    diff = _git_out(ctx.repo, "diff", "--no-color", ctx.base, sha)
    wt = _fresh_worktree(ctx.repo, sha, ctx.wt_root / "reach" / arm)
    lines = trace_lines(wt, diff)
    run_dir = ctx.runs_root / "reach" / arm
    if run_dir.exists():
        shutil.rmtree(run_dir)
    data = [Job(f"data{i}", wt, a, network=ctx.cfg.link.data_network) for i, a in enumerate(data_steps(ctx.links, table))]
    run_jobs(run_dir / "data", data, max_parallel=1, python=ctx.py)
    jobs = []
    for m, d in methods.items():
        cmd = _opt(_opt(d["train"], "--epochs", REACH_EPOCHS), "--n_runs", "1")
        argv = ["python", str(TRACE_SCRIPT), "--out", str(run_dir / f"{m}.trace.json")]
        for l in lines:
            argv += ["--line", l]
        jobs.append(Job(f"reach_{m}", wt, argv + ["--", *cmd[1:]], group=d["group"]))
    res = run_jobs(run_dir, jobs, max_parallel=ctx.jobs, python=ctx.py)
    out = {}
    for m in methods:
        t = run_dir / f"{m}.trace.json"
        r = json.loads(t.read_text()) if t.exists() else {}
        hits = sum((r.get("line_hits") or {}).values())
        out[m] = {"hits": hits, "reached": hits > 0, "outcome": r.get("outcome"),
                  "exit_code": res["status"][f"reach_{m}"]["exit_code"],
                  "log": ctx.rel(run_dir / f"reach_{m}.log")}
    return {"lines": lines, "methods": out}


# ---- context --------------------------------------------------------------------------------------------------------

class Ctx:
    def __init__(self, paths: Paths, cfg: AuditConfig, table: str, echo: Callable[[str], None]):
        if cfg.ablation is None:
            raise AblateError(f"audits/{cfg.id}/audit.yaml has no `ablation:` block")
        self.paths, self.cfg, self.table, self.echo = paths, cfg, table, echo
        self.audit_dir = paths.audit_dir(cfg.id)
        self.repo = ensure_clone(cfg.repo.url, paths.repos / Path(cfg.repo.url.rstrip("/")).name.removesuffix(".git"))
        self.base = resolve(self.repo, cfg.ablation.baseline)
        self.links = json.loads((self.audit_dir / "links.json").read_text())
        self.out_dir = self.audit_dir / "ablation"
        self.runs_root = self.audit_dir / "runs" / "ablation"
        self.wt_root = paths.worktrees / cfg.id / "ablation"
        self.py = venv_python(paths.envs / cfg.id)
        self.jobs = cfg.budget.jobs
        target = next((t for t in cfg.targets if t.table == table), None)
        if target is None:
            raise AblateError(f"{table!r} is not a target in audit.yaml")
        self.seeds = target.seeds
        self.floor = {target.metric.name: target.metric.floor, "unit": target.metric.unit}

    def rel(self, p: Path) -> str:
        return Path(p).relative_to(self.audit_dir).as_posix()


def written_branches(ctx: Ctx) -> list[dict]:
    rec = json.loads((ctx.audit_dir / "branches.json").read_text())
    out = []
    for f in rec["findings"]:
        for r in f["readings"]:
            if r["status"] == "written" and f["table"] == ctx.table:
                out.append({"arm": r["branch"].split("/")[-1], "ref": r["branch"], "finding": f["finding"],
                            "label": r["label"], "message": r["message"]})
    return out


def _arm(ctx: Ctx, ref: str, sha: str, methods: list[str], mt: dict, n_runs: int, **kw) -> dict:
    return {"ref": ref, "commit": sha, "tree": tree_id(ctx.repo, sha), "methods": methods,
            "commands": {m: _opt(mt[m]["train"], "--n_runs", str(n_runs)) for m in methods}, **kw}


# ---- plans ----------------------------------------------------------------------------------------------------------

def plan_exploratory(ctx: Ctx) -> dict:
    mt = table_methods(ctx.links, ctx.table)
    arms, fam, notes = {}, [], {}
    for b in written_branches(ctx):
        sha = resolve(ctx.repo, b["ref"])
        ctx.echo(f"  reach {b['arm']} ({b['finding']}, {b['label']}): tracing {len(mt)} methods")
        r = reach(ctx, b["arm"], sha, mt, ctx.table)
        failed = [m for m, x in r["methods"].items() if x["exit_code"] != 0]
        if failed:
            raise AblateError(f"reach trace failed for {b['arm']}: {', '.join(failed)} "
                              f"({r['methods'][failed[0]]['log']})")
        ms = [m for m, x in r["methods"].items() if x["reached"]]
        notes[b["arm"]] = {"lines": r["lines"], "methods": r["methods"]}
        ctx.echo(f"    traced lines {', '.join(r['lines']) or '(none)'}; reached: {', '.join(ms) or 'none'}")
        if not ms:
            continue
        arms[b["arm"]] = _arm(ctx, b["ref"], sha, ms, mt, ctx.seeds, finding=b["finding"], label=b["label"],
                              message=b["message"])
        fam += [[b["arm"], m] for m in ms]
    used = sorted({m for a in arms.values() for m in a["methods"]}, key=list(mt).index)
    arms = {BASELINE: _arm(ctx, ctx.cfg.ablation.baseline, ctx.base, used, mt, ctx.seeds, label="baseline"), **arms}
    return {"kind": "exploratory", "table": ctx.table, "baseline": BASELINE, "seeds": list(range(ctx.seeds)),
            "seeds_graded": list(range(ctx.seeds)), "arms": arms, "family": fam,
            "family_note": "Holm across this set's effects and those of any later interaction set of this audit "
                           "(all exploratory effects in the audit)",
            "not_measured": {a: "no linked train command executes a line the branch added (2-epoch trace)"
                             for a, n in notes.items() if a not in arms},
            "reach": notes}


def harness(ctx: Ctx, llm, echo) -> dict:
    """AUDIT(harness) on the baseline: the data step also makes seeds n..2n-1; checked byte for byte."""
    from el01.branch.datacheck import data_step_check
    out_dir = ctx.out_dir / "harness"
    out_dir.mkdir(parents=True, exist_ok=True)
    rec_file = out_dir / "harness.json"
    name = "el01/harness"
    n = ctx.seeds
    wctx = _writer_ctx(ctx, llm, echo)
    prompt_vars = dict(commands=W.commands_text(ctx.links, ctx.table), runs_option="--n_runs", runs=n,
                       last_old=n - 1, runs_new=2 * n, first_new=n, last_new=2 * n - 1)
    from string import Template
    tmpl = Template((W.LLM_DIR / "prompts" / "branch_harness.md").read_text())
    attempts, previous = [], ""
    for attempt in range(1, W.RETRIES + 2):
        from el01.llm.backend import AGENT_TOOLS, Request
        from el01.ingest.repo import snapshot
        req = Request(agent=W.AGENT, prompt=tmpl.substitute(previous=previous, **prompt_vars), schema=W.SCHEMA,
                      model=ctx.cfg.llm.model, inputs={"repo_tree": tree_id(ctx.repo, ctx.base)}, tools=AGENT_TOOLS,
                      repo_copy=snapshot(ctx.repo, ctx.base, ctx.paths.workspace / "snapshots" / ctx.cfg.id),
                      max_turns=W.MAX_TURNS)
        r = W._call(wctx, req, out_dir / f"call_{attempt}")
        reading = (r["output"].get("readings") or [{}])[0]
        diff, errors = W.render(ctx.repo, wctx.wt, ctx.base, reading.get("edits") or [])
        a = {"attempt": attempt, "call": r["call"], "pass": False}
        if errors:
            a["reason"] = "the edits do not apply: " + "; ".join(errors)
        else:
            (out_dir / f"attempt{attempt}.patch").write_text(diff)
            a["patch"] = ctx.rel(out_dir / f"attempt{attempt}.patch")
            data = set(x[1] for x in data_steps(ctx.links, ctx.table) if len(x) > 1)
            files = {x.path for x in parse_unified_diff(diff)}
            comments = W.added_comments(diff, W._new_file_text(ctx.repo, wctx.wt, ctx.base, diff))
            if files - data:
                a["reason"] = f"the change touches files other than the data step: {', '.join(sorted(files - data))}"
            elif comments:
                a["reason"] = f"added lines carry comments ({', '.join(comments)})"
            else:
                sha = W.commit_patch(wctx.wt, ctx.base, diff,
                                     f"AUDIT(harness): data for seeds {n}-{2 * n - 1} (fresh seeds for the "
                                     f"confirmation run); data for seeds 0-{n - 1} unchanged")
                dc = data_step_check(wctx, ctx.table, ctx.base, sha, f"harness-{attempt}")
                a["data_step"] = {k: dc[k] for k in ("pass", "reason", "same", "changed_count", "new_count")}
                if dc["pass"] and dc["new_count"] > 0:
                    subprocess.run(["git", "-C", str(ctx.repo), "branch", "-f", name, sha], check=True)
                    a.update(**{"pass": True, "commit": sha, "tree": tree_id(ctx.repo, sha),
                                "reason": dc["reason"]})
                else:
                    a["reason"] = dc["reason"] if not dc["pass"] else "the data step makes no new files"
        echo(f"  harness attempt {attempt}: {'pass' if a['pass'] else 'REJECTED'}: {a['reason']}")
        attempts.append(a)
        if a["pass"]:
            break
        previous = W.previous_text("fresh seeds", [{"reason": a["reason"]}])
    rec = {"branch": name if attempts[-1]["pass"] else None, "attempts": attempts}
    rec_file.write_text(json.dumps(rec, indent=1, default=str) + "\n")
    if not attempts[-1]["pass"]:
        raise AblateError(f"no harness commit passed its data check: {attempts[-1]['reason']}")
    return attempts[-1]


def _writer_ctx(ctx: Ctx, llm, echo):
    from el01.extract.claims import load_claims
    claims = load_claims(ctx.paths, ctx.cfg.id)
    return W.Ctx(ctx.paths, ctx.cfg, llm, ctx.repo, ctx.cfg.ablation.baseline, ctx.base, ctx.out_dir,
                 ctx.paths.worktrees / ctx.cfg.id / "branch-git", echo, {t["target"]: t for t in claims["tables"]},
                 ctx.links, None, set())


def _branch_on(ctx: Ctx, name: str, base: str, commits: list[str], message: Optional[str] = None) -> str:
    wt = W.scratch(ctx.repo, ctx.paths.worktrees / ctx.cfg.id / "branch-git", base)
    sha = W.cherry_pick(wt, base, commits, message)
    subprocess.run(["git", "-C", str(ctx.repo), "branch", "-f", name, sha], check=True)
    return sha


def plan_confirm(ctx: Ctx, llm, echo) -> dict:
    g = json.loads((ctx.out_dir / "grades_exploratory.json").read_text())
    pick = G.largest(g)
    if pick is None:
        raise AblateError("no exploratory effect survives Holm: nothing to confirm")
    arm, method = pick
    explo = P.load(ctx.audit_dir, "exploratory")["plan"]
    h = harness(ctx, llm, echo)
    mt = table_methods(ctx.links, ctx.table)
    a = explo["arms"][arm]
    br = _branch_on(ctx, f"el01/confirm-{arm}", h["commit"], [a["commit"]])
    n = ctx.seeds
    arms = {"confirm-baseline": _arm(ctx, "el01/harness", h["commit"], [method], mt, 2 * n, label="baseline + harness"),
            f"confirm-{arm}": _arm(ctx, f"el01/confirm-{arm}", br, [method], mt, 2 * n, label=a.get("label"),
                                   finding=a.get("finding"), confirms=[arm, method])}
    return {"kind": "confirmation", "table": ctx.table, "baseline": "confirm-baseline",
            "seeds": list(range(2 * n)), "seeds_graded": list(range(n, 2 * n)), "arms": arms,
            "family": [[f"confirm-{arm}", method]],
            "family_note": "a separate pre-specified test of the largest Holm-surviving exploratory effect "
                           f"({arm}/{method}, {g['effects'][arm][method]['effect']:+.2f}); no Holm; seeds "
                           f"{n}-{2 * n - 1} graded, seeds 0-{n - 1} compared with the exploratory runs",
            "picked": {"arm": arm, "method": method, "rule": "largest |effect| among Holm survivors"}}


def plan_interaction(ctx: Ctx) -> dict:
    g = json.loads((ctx.out_dir / "grades_exploratory.json").read_text())
    explo = P.load(ctx.audit_dir, "exploratory")["plan"]
    finding_of = {a: x.get("finding") for a, x in explo["arms"].items()}
    two = G.top_two(g, finding_of)
    if len(two) < 2:
        raise AblateError("fewer than two findings have a Holm-surviving effect: no interaction check")
    a, b = two
    methods = [m for m in explo["arms"][a]["methods"] if m in explo["arms"][b]["methods"]]
    if not methods:
        raise AblateError(f"{a} and {b} share no method")
    fa, fb = finding_of[a], finding_of[b]
    name = f"el01/h-{fa}+{fb}"
    sha = _branch_on(ctx, name, ctx.base, [explo["arms"][a]["commit"], explo["arms"][b]["commit"]],
                     f"HYPOTHESIS({fa}+{fb}): interaction check: {a} + {b} (top two Holm-surviving branches)")
    mt = table_methods(ctx.links, ctx.table)
    arm = f"h-{fa}+{fb}"
    return {"kind": "interaction", "table": ctx.table, "baseline": BASELINE, "baseline_from": "exploratory",
            "seeds": list(range(ctx.seeds)), "seeds_graded": list(range(ctx.seeds)),
            "arms": {arm: _arm(ctx, name, sha, methods, mt, ctx.seeds, label=f"{a} + {b}", finding=f"{fa}+{fb}",
                               parts=[a, b])},
            "family": [[arm, m] for m in methods],
            "family_note": "joins the exploratory Holm family; reported next to the sum of the single effects "
                           "(no interaction test)",
            "picked": {"arms": two, "rule": "the two arms of different findings with the largest Holm-surviving "
                                            "|effect|"}}


def write_prereg(ctx: Ctx, run_set: str, plan: dict) -> dict:
    plan = {"run_set": run_set, **plan}
    run_dir = ctx.runs_root / run_set
    return P.write(ctx.paths.root, ctx.audit_dir, run_set, plan, ctx.floor, G.RULE, run_dir, ctx.cfg.id)


# ---- runs -----------------------------------------------------------------------------------------------------------

def run_set(ctx: Ctx, name: str) -> dict:
    run_dir = ctx.runs_root / name
    rec = P.check(ctx.paths.root, ctx.audit_dir, name, run_dir)   # refuses an uncommitted or stale pre-registration
    plan = rec["plan"]
    mt = table_methods(ctx.links, ctx.table)
    data_jobs, train_jobs = [], []
    for arm, a in plan["arms"].items():
        if arm == plan["baseline"] and plan.get("baseline_from"):
            continue
        wt = _fresh_worktree(ctx.repo, a["commit"], ctx.wt_root / name / arm)
        (run_dir / arm).mkdir(parents=True, exist_ok=True)
        (run_dir / arm / "commit.txt").write_text(a["commit"] + "\n")
        (run_dir / arm / "tree.txt").write_text(a["tree"] + "\n")
        for i, argv in enumerate(data_steps(ctx.links, ctx.table)):
            data_jobs.append(Job(f"{arm}__data{i}", wt, argv, log=f"{arm}/data{i}.log",
                                 network=ctx.cfg.link.data_network))
        for m in a["methods"]:
            train_jobs.append(Job(f"{arm}__{m}", wt, a["commands"][m], seeds=len(plan["seeds"]),
                                  log=f"{arm}/train_{m}.log", group=f"{arm}|{mt[m]['group']}"))
    ctx.echo(f"  {name}: data steps for {len(data_jobs)} arm(s), then {len(train_jobs)} training jobs "
             f"(up to {ctx.jobs} at a time)")
    budget = dict(max_parallel=ctx.jobs, wall_minutes=ctx.cfg.budget.max_wall_minutes, python=ctx.py, echo=ctx.echo)
    r1 = run_jobs(run_dir, data_jobs, **budget)
    if r1["failed"]:
        raise AblateError(f"data step failed: {r1['failed']}")
    r2 = run_jobs(run_dir, train_jobs, **budget)
    if r2["failed"] or r2["not_started"]:
        raise AblateError(f"training jobs failed or not run: {r2['failed'] + r2['not_started']}")
    return {"run_dir": ctx.rel(run_dir), "jobs": len(train_jobs),
            "seconds": {j: r2["status"][j]["seconds"] for j in r2["status"]}}


def parse_set(ctx: Ctx, name: str) -> tuple[dict, dict]:
    run_dir = ctx.runs_root / name
    cite = ctx.rel
    metrics = {d.name: parse_run_dir(d, cite) for d in sorted(p for p in run_dir.iterdir() if p.is_dir())
               if list(d.glob("train_*.log"))}
    ep, skipped = parse_epochs_all(run_dir, cite)
    return metrics, ep


def grade_sets(ctx: Ctx, rules=None) -> dict:
    """Grade every finished run set: exploratory (alone, for the picks), the audit-wide exploratory family
    (exploratory + interaction), the confirmation, and the interaction report."""
    rules = rules or legacy_rules()
    out = {"rule": G.RULE, "rules_version": rules.RULES_VERSION, "table": ctx.table}
    plans, metrics, epochs = {}, {}, {}
    for name in ("exploratory", "interaction", "confirm"):
        if not (ctx.runs_root / name).exists() or not (P.prereg_files(ctx.audit_dir, name)[0]).exists():
            continue
        rec = P.check(ctx.paths.root, ctx.audit_dir, name, ctx.runs_root / name)
        plans[name] = {"run_set": name, **rec["plan"]}
        metrics[name], epochs[name] = parse_set(ctx, name)
    if "exploratory" not in plans:
        raise AblateError("the exploratory run set has not run")
    for name in ("interaction",):
        if name in plans and plans[name].get("baseline_from"):
            src = plans[name]["baseline_from"]
            metrics[name][plans[name]["baseline"]] = metrics[src][plans[src]["baseline"]]
            epochs[name][plans[name]["baseline"]] = epochs[src][plans[src]["baseline"]]
    alone = G.grade_family([plans["exploratory"]], metrics, epochs, rules)
    (ctx.out_dir).mkdir(parents=True, exist_ok=True)
    (ctx.out_dir / "grades_exploratory.json").write_text(json.dumps(alone, indent=1) + "\n")
    fam_plans = [plans["exploratory"]] + ([plans["interaction"]] if "interaction" in plans else [])
    out["exploratory"] = G.grade_family(fam_plans, metrics, epochs, rules)
    out["exploratory"]["run_sets"] = [p["run_set"] for p in fam_plans]
    out["not_measured"] = plans["exploratory"].get("not_measured")
    if "confirm" in plans:
        p = plans["confirm"]
        out["confirmation"] = G.grade_confirmation(p, metrics["confirm"], epochs["confirm"], rules)
        out["confirmation"]["picked"] = p["picked"]
        out["confirmation"]["determinism"] = determinism(p, metrics["confirm"], plans["exploratory"],
                                                         metrics["exploratory"])
    if "interaction" in plans:
        p = plans["interaction"]
        arm = next(iter(p["arms"]))
        out["interaction"] = {"arm": arm, "parts": p["arms"][arm]["parts"], "picked": p["picked"],
                              "methods": G.interaction_report(out["exploratory"]["effects"][arm],
                                                              out["exploratory"]["effects"], p["arms"][arm]["parts"])}
    (ctx.out_dir / "grades.json").write_text(json.dumps(out, indent=1) + "\n")
    return out


def determinism(conf: dict, cm: dict, explo: dict, em: dict) -> dict:
    """Seeds 0..n-1 of the confirmation runs against the exploratory runs of the same code (per seed, equal or not)."""
    out = {}
    for arm, a in conf["arms"].items():
        src = explo["baseline"] if arm == conf["baseline"] else (a.get("confirms") or [None])[0]
        for m in a["methods"]:
            x = (cm.get(arm, {}).get(m) or {}).get("target")
            y = (em.get(src, {}).get(m) or {}).get("target")
            if not x or not y:
                continue
            ys = {r["seed_run"]: r["target_acc"] for r in y["per_seed"]}
            pairs = [(r["seed_run"], r["target_acc"], ys.get(r["seed_run"])) for r in x["per_seed"]
                     if r["seed_run"] in ys]
            out[f"{arm}/{m}"] = {"compared_with": f"exploratory {src}/{m}", "seeds": len(pairs),
                                 "equal": sum(a == b for _, a, b in pairs)}
    return out
