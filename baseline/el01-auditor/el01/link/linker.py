"""Claim-to-command linker (spec section 9, step 2): the linker agent proposes commands; code checks and runs them.

Per target table, the `linker` agent gets the table's verified claim cells, the paper pages that mention the table
(code finds them by its printed name), the README, every file of `reproduce_scripts/`, and the `--help` output of the
scripts those invoke (run by code in the audited env), plus read-only Read/Grep/Glob on a `git archive` snapshot of
the audited commit (copied in as ./repo). The repository's own commands win where they exist; the paper fills in what
they leave open (MatchDG: the LeNet data size, 1000 images per domain, has no repository command). It returns data steps,
per-cell steps (argv lists) with a parser, derived cells and unlinked cells. Code then checks:
  1. coverage: every verified card is in exactly one entry; linked and derived entries name one cell;
  2. every argv: `python <script> ...`, the script exists, no shell syntax, every option known to the script's own
     argparse parser (el01/link/argspec.py; unique abbreviations recorded), and the parser accepts the whole list;
  3. the dry run: data steps once (network only if audit.yaml `link.data_network`), then each cell's steps with
     `--epochs 1 --n_runs 1` in a worktree at the repair loop's run head. Steps before a cell's last step try the
     `link.dry_run_epochs` ladder (1, then 5) when a later step fails. Cells with the same commands share one dry run.
     Chains run one at a time: commands in one worktree share output paths (robustdg: mmd, coral, c-mmd, c-coral
     write the same result directory and model file, and train.py:202-203 creates that directory with an
     exists-then-makedirs race), so parallel dry runs fail at random;
  4. the parser spec on the 1-epoch log of its step (el01/link/parser_spec.py): one block per run, the declared match
     count, a number with its line.
A table whose answer code rejects is asked again, with the previous answer and code's findings (the failing step and
its traceback), up to audit.yaml `link.max_calls_per_table` calls, as the repair agent is asked again after a failure.
Output: audits/<id>/links.json; prompts and answers in audits/<id>/link/; run directories in audits/<id>/runs/link/."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Callable, Optional

from el01.config import AuditConfig, Paths
from el01.env.builder import venv_python
from el01.extract.claims import load_claims, load_docs, slug
from el01.ingest.repo import ensure_clone, git, resolve, snapshot, tree_id
from el01.link import argspec, parser_spec
from el01.llm.backend import AGENT_TOOLS, LLM, Request
from el01.repair.agent import normalise, traceback_text
from el01.run.classify import classify
from el01.run.runner import Job, run_jobs
from el01.run.worktrees import ensure_worktree

LLM_DIR = Path(__file__).resolve().parent.parent / "llm"
SCHEMA = json.loads((LLM_DIR / "schemas" / "links.json").read_text())
AGENT = "linker"
MAX_TURNS = 40
SHELL_RE = re.compile(r"^(?:[<>|&;]|\d?>>?|&&|\|\||2>&1)$|[$`]")
INVOKE_RE = re.compile(r"\bpython3?\s+([\w./-]+\.py)\b")


class LinkError(RuntimeError):
    pass


def _h(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()[:8]


def _safe_name(s: str) -> str:
    return re.sub(r"[^\w.-]+", "_", s).strip("_") or "step"


# ---- context ----------------------------------------------------------------------------------------------------

@dataclass
class Ctx:
    paths: Paths
    cfg: AuditConfig
    repo: Path
    base: str          # the audited commit (snapshot the agent reads)
    snap: Path
    head: str          # the run head for dry runs
    branch: Optional[str]
    head_why: str
    wt: Path
    py: Path
    audit_dir: Path
    ev: Path           # audits/<id>/link/
    runs: Path         # audits/<id>/runs/link/
    llm: LLM
    echo: Callable[[str], None]

    def rel(self, p: Path) -> str:
        return Path(p).relative_to(self.audit_dir).as_posix()


def run_head(paths: Paths, cfg: AuditConfig, repo: Path) -> tuple[str, Optional[str], str]:
    """The repair loop's last run head: (sha, branch, why). Without a repair record: the audited commit."""
    rp = paths.audit_dir(cfg.id) / "repair.json"
    if not rp.exists():
        return resolve(repo, cfg.repo.commit), None, "no repair record (audits/<id>/repair.json): the audited commit"
    rep = json.loads(rp.read_text())
    last = next((r for r in reversed(rep.get("runs", [])) if r.get("ok")), None)
    if last is None:
        raise LinkError(f"the repair loop never ran the smoke command (verdict {rep.get('verdict')!r}): nothing to link "
                        f"commands against")
    sha = last["head"]
    branch = next((b for b, s in rep.get("branches", {}).items() if s == sha), None)
    return sha, branch, (f"the repair loop's last successful run head ({branch or sha[:7]}): the audited commit plus "
                         f"its repairs" + (" and the missing-domain hypothesis branch the loop ran on"
                                           if branch and branch != "el01/repair" else ""))


def make_ctx(paths: Paths, cfg: AuditConfig, llm: LLM, echo: Callable[[str], None]) -> Ctx:
    repo = ensure_clone(cfg.repo.url, paths.repos / Path(cfg.repo.url.rstrip("/")).name.removesuffix(".git"))
    base = resolve(repo, cfg.repo.commit)
    head, branch, why = run_head(paths, cfg, repo)
    py = venv_python(paths.envs / cfg.id)
    if not py.exists():
        raise LinkError(f"{py} is missing: run `el01 env build {cfg.id}` first")
    wt, _ = ensure_worktree(repo, head, paths.worktrees / cfg.id / "link")
    audit_dir = paths.audit_dir(cfg.id)
    return Ctx(paths, cfg, repo, base, snapshot(repo, base, paths.workspace / "snapshots" / cfg.id), head, branch,
               why, wt, py.absolute(), audit_dir, audit_dir / "link", audit_dir / "runs" / "link", llm, echo)


def invoked_scripts(texts: list[str], root: Path) -> list[str]:
    """Scripts that the README / reproduce scripts run as `python <script>.py`, in order of first mention."""
    out = []
    for t in texts:
        for m in INVOKE_RE.finditer(t):
            s = m.group(1).removeprefix("./")
            if s not in out and (root / s).is_file():
                out.append(s)
    return out


def repo_texts(snap: Path) -> tuple[str, list[tuple[str, str]]]:
    readme = next((p for p in sorted(snap.iterdir()) if p.name.lower().startswith("readme")), None)
    rs = snap / "reproduce_scripts"
    scripts = [(p.relative_to(snap).as_posix(), p.read_text(errors="replace"))
               for p in sorted(rs.rglob("*")) if p.is_file()] if rs.is_dir() else []
    return (readme.read_text(errors="replace") if readme else "(no README)"), scripts


def cells_block(table: dict) -> str:
    lines = [f"Caption (page {table['page']} of the {table['doc']} document): {table['caption'].get('text')}",
             f"Metric: {table['metric'].get('name')} ({table['metric'].get('unit')}), {table['metric'].get('split')}; "
             f"aggregation: {table['aggregation'].get('kind')}, spread: {table['aggregation'].get('spread')}, "
             f"runs: {table['aggregation'].get('n_runs')}"]
    by_row: dict[str, list[dict]] = {}
    for c in table["cards"]:
        if c["valid"]:
            by_row.setdefault(c["source"]["row"], []).append(c)
    for row, cards in by_row.items():
        c0 = cards[0]
        prov = "numbers taken from other work" if c0["provenance"] == "cited" else "numbers from this paper's runs"
        lines.append(f"- row {row!r} (role: {c0['role']}; {prov}):")
        lines += [f"    {c['claim_id']}" for c in cards]
    return "\n".join(lines)


def helps_block(specs: dict[str, dict]) -> str:
    out = []
    for s, spec in specs.items():
        if not spec["argparse"]:
            out.append(f"--- python {s} --help ---\n({s} defines no command-line options)")
            continue
        note = (f"(`python {s} --help` fails at this commit with {spec['help_error']}: a help string has an unescaped "
                f"%. Below is the same parser's help with those % signs escaped by code.)\n") if spec.get("help_error") else ""
        out.append(f"--- python {s} --help ---\n{note}```\n{spec['help'].rstrip()}\n```")
    return "\n\n".join(out)


def paper_passages(table: dict, docs: dict) -> str:
    """Every page of either document that mentions the table by its printed name ("Table 1" is not "Table 11")."""
    pat = re.compile(rf"\b{re.escape(table['table'])}\b")
    out = [f"=== {n} [page {p}] ===\n{t.rstrip()}" for n, d in docs.items() for p, t in sorted(d.pages.items())
           if pat.search(t)]
    return "\n\n".join(out) or "(none)"


def build_prompt(ctx: Ctx, table: dict, specs: dict[str, dict], docs: dict) -> str:
    readme, scripts = repo_texts(ctx.snap)
    reproduce = "\n\n".join(f"--- {p} ---\n````\n{t.rstrip()}\n````" for p, t in scripts) or "(none)"
    return Template((LLM_DIR / "prompts" / f"{AGENT}.md").read_text()).substitute(
        title=ctx.cfg.paper.title, repo_url=ctx.cfg.repo.url, table=table["target"], cells=cells_block(table),
        passages=paper_passages(table, docs), readme=readme.rstrip(), reproduce=reproduce, helps=helps_block(specs))


# ---- checks -----------------------------------------------------------------------------------------------------

def argv_problems(argv: list, root: Path) -> list[str]:
    if not argv or len(argv) < 2:
        return ["argv needs `python` and a script"]
    out = []
    if argv[0] not in ("python", "python3"):
        out.append(f"argv starts with {argv[0]!r}, not python")
    if not (root / argv[1]).is_file():
        out.append(f"no script {argv[1]!r} in the repository")
    shell = [t for t in argv if SHELL_RE.search(t)]
    if shell:
        out.append(f"shell syntax in argv: {shell}")
    return out


def dry_argv(argv: list[str], spec: dict, lk, epochs: int) -> list[str]:
    tail = list(argv[2:])
    opts = argspec.option_strings(spec) if spec.get("argparse") else set()
    if lk.epochs_option and lk.epochs_option in opts:
        tail = argspec.set_option(tail, lk.epochs_option, str(epochs))
    if lk.runs_option and lk.runs_option in opts:
        tail = argspec.set_option(tail, lk.runs_option, "1")
    return list(argv[:2]) + tail


def dest_of(spec: dict, option: Optional[str]) -> Optional[str]:
    return next((a["dest"] for a in spec.get("actions", []) if option in a["option_strings"]), None) if option else None


class Probes:
    """One argparse probe per script (in the dry-run worktree), with every argument list it must judge."""

    def __init__(self, ctx: Ctx):
        self.ctx, self.specs, self.results = ctx, {}, {}

    def run(self, wanted: dict[str, set[tuple]]) -> None:
        for script, tails in wanted.items():
            tails = sorted(tails)
            spec = argspec.probe(self.ctx.py, self.ctx.wt, script, tails)
            self.specs[script] = spec
            for t, r in zip(tails, spec["results"]):
                self.results[(script, t)] = r

    def check(self, argv: list[str]) -> dict:
        script, tail = argv[1], tuple(argv[2:])
        spec = self.specs[script]
        r = self.results.get((script, tail))
        unknown, abbrev = argspec.option_check(spec, tail) if spec["argparse"] else ([], {})
        return {"problems": argspec.check_command(spec, tail, r), "abbreviations": abbrev,
                "namespace": (r or {}).get("namespace") if (r or {}).get("ok") else None}


def check_answer(ctx: Ctx, table: dict, ans: dict) -> dict:
    """Structure and coverage checks, before any probe. Returns the table's link record (cells not yet run)."""
    valid_ids = [c["claim_id"] for c in table["cards"] if c["valid"]]
    cards = {c["claim_id"]: c for c in table["cards"]}
    parsers = {p["name"]: p for p in ans.get("parsers") or []}
    seen: dict[str, int] = {}
    cells, problems = [], []
    for e in ans.get("cells") or []:
        ids = list(e.get("claim_ids") or [])
        for i in ids:
            seen[i] = seen.get(i, 0) + 1
        status = e.get("status")
        cp = []
        unknown = [i for i in ids if i not in cards]
        if unknown:
            cp.append(f"unknown claim ids {unknown}")
        if status in ("linked", "derived") and len(ids) != 1:
            cp.append(f"a {status} entry must name exactly one cell, it names {len(ids)}")
        rec = {"claim_ids": ids, "status": status, "evidence": e.get("evidence"), "reason": e.get("reason"),
               "steps": [], "parser": e.get("parser"), "derived_from": e.get("derived_from") or [],
               "derived_op": e.get("derived_op"), "problems": cp}
        if status == "linked":
            names = [s.get("name") for s in e.get("steps") or []]
            if not names:
                cp.append("no steps")
            if len(set(map(_safe_name, names))) != len(names):
                cp.append(f"step names not unique: {names}")
            for s in e.get("steps") or []:
                rec["steps"].append({"name": s.get("name"), "argv": list(s.get("argv") or []),
                                     "problems": argv_problems(list(s.get("argv") or []), ctx.wt)})
            p = parsers.get(e.get("parser") or "")
            if p is None:
                cp.append(f"no parser named {e.get('parser')!r}")
            elif p.get("step") not in names:
                cp.append(f"parser {p['name']!r} reads step {p.get('step')!r}, which this cell does not run")
        elif status == "derived":
            if e.get("derived_op") != "mean":
                cp.append(f"derived_op {e.get('derived_op')!r}")
            bad = [i for i in rec["derived_from"] if i not in cards]
            if bad or not rec["derived_from"]:
                cp.append(f"derived_from names unknown cells {bad}" if bad else "derived_from is empty")
        elif status != "unlinked":
            cp.append(f"status {status!r}")
        cells.append(rec)
    missing = [i for i in valid_ids if i not in seen]
    twice = [i for i, n in seen.items() if n > 1]
    if missing:
        problems.append(f"{len(missing)} verified cells not in any entry: {missing}")
    if twice:
        problems.append(f"cells in more than one entry: {twice}")
    for i in (c["claim_id"] for c in table["cards"] if not c["valid"]):
        if i not in seen:
            cells.append({"claim_ids": [i], "status": "not_linked", "reason": "the claim card failed verification",
                          "steps": [], "parser": None, "derived_from": [], "derived_op": None, "problems": [],
                          "evidence": None})
    pspecs = []
    for p in ans.get("parsers") or []:
        rec = {k: p.get(k) for k in parser_spec.FIELDS}
        rec["evidence"] = p.get("evidence")
        try:
            parser_spec.compile_spec(rec)
            rec["problems"] = []
        except parser_spec.SpecError as e:
            rec["problems"] = [str(e)]
        pspecs.append(rec)
    data = [{"name": d.get("name"), "argv": list(d.get("argv") or []), "evidence": d.get("evidence"),
             "problems": argv_problems(list(d.get("argv") or []), ctx.wt)} for d in ans.get("data_steps") or []]
    return {"data_steps": data, "parsers": pspecs, "cells": cells, "problems": problems, "notes": ans.get("notes")}


def ladder_for(cell: dict, lk) -> list[int]:
    return list(lk.dry_run_epochs) if len(cell["steps"]) > 1 else list(lk.dry_run_epochs[:1])


def plan_dry(cell: dict, specs: dict, lk, rung: int) -> list[list[str]]:
    n = len(cell["steps"])
    return [dry_argv(s["argv"], specs[s["argv"][1]], lk, lk.dry_run_epochs[0] if k == n - 1 else rung)
            for k, s in enumerate(cell["steps"])]


def probe_all(ctx: Ctx, tables: list[dict]) -> Probes:
    """Probe each script once with every argv it must judge (as given, and the dry-run variants)."""
    pr = Probes(ctx)
    first: dict[str, set] = {}
    for t in tables:
        for d in t["data_steps"]:
            if not d["problems"]:
                first.setdefault(d["argv"][1], set()).add(tuple(d["argv"][2:]))
        for c in t["cells"]:
            for s in c["steps"]:
                if not s["problems"]:
                    first.setdefault(s["argv"][1], set()).add(tuple(s["argv"][2:]))
    # the dry-run variants need each script's options, so probe in two rounds (the second only adds candidates)
    pr.run(first)
    wanted = {k: set(v) for k, v in first.items()}
    for t in tables:
        for c in t["cells"]:
            if c["steps"] and all(not s["problems"] for s in c["steps"]):
                for rung in ladder_for(c, ctx.cfg.link):
                    for argv in plan_dry(c, pr.specs, ctx.cfg.link, rung):
                        wanted[argv[1]].add(tuple(argv[2:]))
    pr.run({k: v for k, v in wanted.items() if v != first[k]})
    return pr


# ---- dry runs ---------------------------------------------------------------------------------------------------

def _job(ctx: Ctx, run_dir: Path, name: str, argv: list[str], network: bool = False) -> dict:
    j = Job(_safe_name(name), ctx.wt, argv, network=network)
    res = run_jobs(run_dir, [j], max_parallel=1, wall_minutes=ctx.cfg.budget.max_wall_minutes, python=ctx.py)
    st = res["status"][j.name]
    return {"name": name, "argv": argv, "status": st["status"], "exit_code": st["exit_code"],
            "seconds": st["seconds"], "network": network, "log": ctx.rel(run_dir / j.log_name)}


def run_data_steps(ctx: Ctx, tables: list[dict]) -> None:
    done: dict[tuple, dict] = {}
    for t in tables:
        for d in t["data_steps"]:
            if d["problems"]:
                d["dry_run"] = None
                continue
            key = tuple(d["argv"])
            if key not in done:
                rd = ctx.runs / "data" / f"{_safe_name(d['name'])}-{_h(d['argv'])}"
                done[key] = _job(ctx, rd, d["name"], d["argv"], network=ctx.cfg.link.data_network)
                ctx.echo(f"  data step {' '.join(d['argv'])}: {done[key]['status']} (exit {done[key]['exit_code']}) "
                         f"in {done[key]['seconds']}s -> {done[key]['log']}")
            d["dry_run"] = done[key]


def run_chain(ctx: Ctx, table_slug: str, cell: dict, specs: dict) -> dict:
    """Dry-run one cell's steps in order (the epoch ladder for the steps before the last). {"ok", "attempts"}."""
    lk = ctx.cfg.link
    attempts = []
    cslug = slug("-".join(cell["claim_ids"][0].split("|")[1:]))
    for rung in ladder_for(cell, lk):
        argvs = plan_dry(cell, specs, lk, rung)
        rd = ctx.runs / table_slug / f"{cslug}-{_h(argvs)}"
        att = {"earlier_steps_epochs": rung if len(argvs) > 1 else None, "run_dir": ctx.rel(rd), "jobs": [],
               "ok": False}
        for s, argv in zip(cell["steps"], argvs):
            j = _job(ctx, rd, s["name"], argv)
            att["jobs"].append(j)
            if j["exit_code"] != 0:
                break
        att["ok"] = all(j["exit_code"] == 0 for j in att["jobs"]) and len(att["jobs"]) == len(argvs)
        attempts.append(att)
        if att["ok"] or len(att["jobs"]) == 1:  # a failure in the first step: more epochs earlier cannot help
            break
    return {"ok": attempts[-1]["ok"], "attempts": attempts}


def check_parser(ctx: Ctx, cell: dict, probes: Probes, parsers: dict) -> None:
    """The cell's parser spec on the 1-epoch log of its step."""
    final = cell["dry_run"]["attempts"][-1]
    if not cell["dry_run"]["ok"]:
        bad = final["jobs"][-1]
        cell["problems"].append(f"dry run: step {bad['name']!r} {bad['status']} (exit {bad['exit_code']}), "
                                f"log {bad['log']}")
        return
    lk = ctx.cfg.link
    p = parsers[cell["parser"]]
    job = final["jobs"][[s["name"] for s in cell["steps"]].index(p["step"])]
    ns = probes.check(job["argv"])["namespace"] or {}
    spec = probes.specs[job["argv"][1]]
    rd, ed = dest_of(spec, lk.runs_option), dest_of(spec, lk.epochs_option)
    n_runs, epochs = (ns.get(rd) if rd else None), (ns.get(ed) if ed else None)
    v = parser_spec.validate(p, ctx.audit_dir / job["log"], n_runs, epochs, cite=ctx.rel)
    blocks = (v["parsed"] or {}).get("blocks") or []
    cell["parser_check"] = {"ok": v["ok"], "problems": v["problems"], "n_runs": n_runs, "epochs": epochs,
                            "values": [{"run": b["run"], "value": b["value"], "sd": b["sd"],
                                        "log": job["log"], "line": b["line"]} for b in blocks]}
    if not v["ok"]:
        cell["problems"].append(f"parser {p['name']!r} on {job['log']}: {'; '.join(v['problems'])}")


def dry_runs(ctx: Ctx, tables: list[dict], probes: Probes) -> None:
    """Cells with the same commands (e.g. one row's columns) share one dry run; each checks its own parser on it.
    One chain at a time (see the module docstring: shared output paths and a makedirs race in robustdg)."""
    run_data_steps(ctx, tables)
    for t in tables:
        if any(d.get("dry_run") is None or d["dry_run"]["exit_code"] != 0 for d in t["data_steps"]):
            t["problems"].append("a data step did not run: no cell dry runs")
            continue
        parsers = {p["name"]: p for p in t["parsers"] if not p["problems"]}
        todo = [c for c in t["cells"] if c["status"] == "linked" and not c["problems"]
                and all(not s["problems"] for s in c["steps"]) and c["parser"] in parsers]
        groups: dict[tuple, list[dict]] = {}
        for c in todo:
            groups.setdefault(tuple(tuple(s["argv"]) for s in c["steps"]), []).append(c)

        def do(group: list[dict]) -> None:
            res = run_chain(ctx, t["slug"], group[0], probes.specs)
            for c in group:
                c["dry_run"] = {**res, "shared_by": [g["claim_ids"][0] for g in group]}
                check_parser(ctx, c, probes, parsers)

        ctx.echo(f"  {t['target']}: dry runs of {len(todo)} cells: {len(groups)} distinct command chains, one at a "
                 f"time")
        for g in groups.values():
            do(g)


# ---- the whole step ---------------------------------------------------------------------------------------------

def finish_cell(cell: dict, probes: Probes) -> None:
    for s in cell["steps"]:
        if not s["problems"]:
            r = probes.check(s["argv"])
            s["problems"] += r["problems"]
            s["abbreviations"] = r["abbreviations"]
            s["namespace"] = r["namespace"]
    for s in cell["steps"]:
        cell["problems"] += [f"step {s['name']!r}: {p}" for p in s["problems"]]


def evaluate(ctx: Ctx, tables: list[dict], dry_run: bool) -> Probes:
    """Probe every command, then (optionally) dry-run everything from a clean start; set each cell's validity."""
    probes = probe_all(ctx, tables)
    for t in tables:
        for d in t["data_steps"]:
            if not d["problems"]:
                r = probes.check(d["argv"])
                d["problems"] += r["problems"]
                d["abbreviations"], d["namespace"] = r["abbreviations"], r["namespace"]
        for c in t["cells"]:
            finish_cell(c, probes)
    if dry_run:
        # a clean start: earlier dry runs leave checkpoints (a stale MatchDG contrastive checkpoint would let the second
        # phase start without its first phase) and data from other data commands in the worktree
        if ctx.runs.exists():
            shutil.rmtree(ctx.runs)
        git(ctx.wt, "clean", "-ffdxq")
        dry_runs(ctx, tables, probes)
    for t in tables:
        pnames = {p["name"]: p for p in t["parsers"]}
        for c in t["cells"]:
            if c["status"] == "linked" and c["parser"] in pnames:
                # per_run: one number per run, so the grader computes mean, spread and CIs itself; aggregate: only
                # the audited code's own summary over runs is printed
                c["values"] = "per_run" if pnames[c["parser"]].get("run_start_regex") else "aggregate"
        linked_ok = {c["claim_ids"][0] for c in t["cells"] if c["status"] == "linked" and not c["problems"]
                     and (not dry_run or (c.get("dry_run") or {}).get("ok"))}
        for c in t["cells"]:
            if c["status"] == "derived":
                bad = [i for i in c["derived_from"] if i not in linked_ok]
                if bad:
                    c["problems"].append(f"derived from cells that are not validly linked: {bad}")
            c["valid"] = c["status"] in ("linked", "derived") and not c["problems"] and \
                (c["status"] != "linked" or not dry_run or (c.get("dry_run") or {}).get("ok", False))
        t["counts"] = {k: sum(c["status"] == k for c in t["cells"]) for k in ("linked", "derived", "unlinked",
                                                                              "not_linked")}
        t["counts"]["valid"] = sum(c.get("valid", False) for c in t["cells"])
        t["counts"]["cells_covered"] = sum(len(c["claim_ids"]) for c in t["cells"])
    return probes


def table_ok(t: dict) -> bool:
    return not t["problems"] and all(not d["problems"] and (d.get("dry_run") or {"exit_code": 0})["exit_code"] == 0
                                     for d in t["data_steps"]) \
        and all(c["valid"] for c in t["cells"] if c["status"] in ("linked", "derived"))


def _subs(ctx: Ctx) -> list[tuple[str, str]]:
    env_dir = ctx.py.parent.parent
    home = None
    cfgfile = env_dir / "pyvenv.cfg"
    if cfgfile.exists():
        for line in cfgfile.read_text().splitlines():
            if line.split("=")[0].strip() == "home":
                home = str(Path(line.split("=", 1)[1].strip()).parent)
    return [(str(ctx.wt) + os.sep, ""), (str(ctx.wt.resolve()) + os.sep, ""), (str(env_dir) + os.sep, "<env>/"),
            (str(env_dir.resolve()) + os.sep, "<env>/")] + ([(home + os.sep, "<python>/")] if home else [])


def failure_excerpt(ctx: Ctx, log_rel: str) -> str:
    """The failing step's exception, where it was raised, and its traceback (machine paths normalised)."""
    log = ctx.audit_dir / log_rel
    f = classify(log, log_roots=[str(ctx.wt)], source_root=ctx.wt, inside=[ctx.wt, ctx.paths.workspace])
    if f and f.get("traceback_line"):
        tb = traceback_text(log, f, _subs(ctx)).splitlines()
        return "\n".join(tb[-12:])
    lines = [l for l in log.read_text(errors="replace").splitlines() if l.strip()]
    return normalise("\n".join(lines[-5:]), _subs(ctx)) or "(empty log)"


def feedback(ctx: Ctx, t: dict, ans: dict) -> str:
    """The previous answer and code's findings, grouped (one line per distinct problem, with the cells it hit)."""
    lines = [f"- {p}" for p in t["problems"]]
    for d in t["data_steps"]:
        lines += [f"- data step {d['name']!r} ({' '.join(d['argv'])}): {p}" for p in d["problems"]]
        dr = d.get("dry_run")
        if dr and dr["exit_code"] != 0:
            lines.append(f"- data step {d['name']!r} failed (exit {dr['exit_code']}):\n```\n"
                         f"{failure_excerpt(ctx, dr['log'])}\n```")
    groups: dict[str, list[str]] = {}
    for c in t["cells"]:
        if c["status"] not in ("linked", "derived") or c.get("valid"):
            continue
        dr = c.get("dry_run") or {}
        for p in c["problems"]:
            key = p
            if p.startswith("dry run:") and dr.get("attempts"):
                bad = dr["attempts"][-1]["jobs"][-1]
                key = (f"dry run of step {bad['name']!r} ({' '.join(bad['argv'])}) failed (exit {bad['exit_code']}):"
                       f"\n```\n{failure_excerpt(ctx, bad['log'])}\n```")
            groups.setdefault(key, []).append(c["claim_ids"][0])
    for key, ids in groups.items():
        lines.append(f"- {key}\n  cells: {', '.join(ids)}")
    return Template((LLM_DIR / "prompts" / "linker_feedback.md").read_text()).substitute(
        table=t["target"], answer=json.dumps(ans, indent=1, ensure_ascii=False), problems="\n".join(lines))


def _ask(ctx: Ctx, table: dict, prompt: str, name: str) -> tuple[dict, dict]:
    (ctx.ev / f"{name}.prompt.md").write_text(prompt)
    req = Request(agent=AGENT, prompt=prompt, schema=SCHEMA, model=ctx.cfg.llm.model,
                  inputs={"repo_tree": tree_id(ctx.repo, ctx.base)}, tools=AGENT_TOOLS, repo_copy=ctx.snap,
                  max_turns=MAX_TURNS)
    resp = ctx.llm.call(req)
    ans = resp.output if isinstance(resp.output, dict) else {}
    (ctx.ev / f"{name}.answer.json").write_text(json.dumps(ans, indent=1, ensure_ascii=False) + "\n")
    meta = resp.record["response"]
    return ans, {"key": resp.key, "cache": resp.cache, "backend": resp.backend,
                 "recorded_backend": resp.record.get("backend"), "cli_version": resp.record.get("cli_version"),
                 "total_cost_usd": meta.get("total_cost_usd"), "num_turns": meta.get("num_turns"),
                 "models": meta.get("models"), "prompt": f"link/{name}.prompt.md", "answer": f"link/{name}.answer.json"}


def link(paths: Paths, cfg: AuditConfig, llm: LLM, dry_run: bool = True, echo: Callable[[str], None] = print) -> dict:
    """Round 1 asks the linker for every table; while code rejects a table's answer and calls remain
    (audit.yaml `link.max_calls_per_table`), the next round asks again for that table with the previous answer and
    code's findings. Every round re-checks all tables from a clean start."""
    claims = load_claims(paths, cfg.id)
    docs = load_docs(paths, cfg)
    ctx = make_ctx(paths, cfg, llm, echo)
    if ctx.ev.exists():
        shutil.rmtree(ctx.ev)
    ctx.ev.mkdir(parents=True)
    readme, scripts = repo_texts(ctx.snap)
    invoked = invoked_scripts([readme] + [t for _, t in scripts], ctx.wt)
    help_specs = {s: argspec.probe(ctx.py, ctx.wt, s) for s in invoked}
    echo(f"run head for dry runs: {ctx.branch or ctx.head[:7]} ({ctx.head[:7]}); scripts with --help in the prompt: "
         f"{', '.join(invoked)}")
    answers: dict[str, dict] = {}
    calls: dict[str, list[dict]] = {}
    history: dict[str, list[dict]] = {}
    tables: list[dict] = []
    probes = None
    for rnd in range(1, cfg.link.max_calls_per_table + 1):
        todo = [tb for tb in claims["tables"] if rnd == 1 or not table_ok(next(t for t in tables
                                                                                if t["target"] == tb["target"]))]
        if not todo:
            break
        for tb in todo:
            s = slug(tb["target"])
            prompt = build_prompt(ctx, tb, help_specs, docs)
            if rnd > 1:
                prev = next(t for t in tables if t["target"] == tb["target"])
                prompt += feedback(ctx, prev, answers[s])
            echo(f"{tb['target']}: linker, call {rnd} ({llm.mode})")
            answers[s], call = _ask(ctx, tb, prompt, s if rnd == 1 else f"{s}.call{rnd}")
            calls.setdefault(s, []).append({"round": rnd, **call})
        tables = []
        for tb in claims["tables"]:
            s = slug(tb["target"])
            rec = check_answer(ctx, tb, answers[s])
            rec.update(target=tb["target"], table=tb["table"], slug=s, calls=calls[s], call=calls[s][-1])
            tables.append(rec)
        probes = evaluate(ctx, tables, dry_run)
        for t in tables:
            bad = [c for c in t["cells"] if c["status"] in ("linked", "derived") and not c["valid"]]
            history.setdefault(t["slug"], []).append(
                {"round": rnd, "call": len(calls[t["slug"]]), "ok": table_ok(t), "invalid_cells": len(bad),
                 "table_problems": list(t["problems"]),
                 "data_step_problems": [p for d in t["data_steps"] for p in d["problems"]] +
                                       [f"{d['name']} exit {d['dry_run']['exit_code']}" for d in t["data_steps"]
                                        if (d.get("dry_run") or {"exit_code": 0})["exit_code"] != 0]})
            echo(f"  round {rnd}, {t['target']}: linked {t['counts']['linked']}, derived {t['counts']['derived']}, "
                 f"unlinked entries {t['counts']['unlinked']}; valid {t['counts']['valid']}"
                 f"{'' if table_ok(t) else '; REJECTED by code'}")
            for p in t["problems"]:
                echo(f"    table problem: {p}")
            for c in bad[:5]:
                echo(f"    {c['claim_ids'][0]}: {c['problems'][0] if c['problems'] else 'not valid'}")
    for t in tables:
        t["rounds"] = history[t["slug"]]
    all_calls = [c for cs in calls.values() for c in cs]
    out = {"audit": cfg.id, "agent": AGENT, "model": cfg.llm.model, "base_commit": ctx.base,
           "run_head": {"sha": ctx.head, "branch": ctx.branch, "why": ctx.head_why},
           "dry_run": {"done": dry_run, "fresh": "runs/link/ removed and `git clean -ffdx` in the worktree first",
                       "epochs_option": cfg.link.epochs_option, "runs_option": cfg.link.runs_option,
                       "ladder": cfg.link.dry_run_epochs, "data_network": cfg.link.data_network,
                       "max_calls_per_table": cfg.link.max_calls_per_table},
           "help": {s: {"argparse": sp["argparse"], "help_error": sp.get("help_error")} for s, sp in help_specs.items()},
           "scripts": {s: {"argparse": sp["argparse"], "options": len(argspec.option_strings(sp)),
                           "help_error": sp.get("help_error")} for s, sp in probes.specs.items()},
           "tables": tables,
           "counts": {"agent_calls": len(all_calls), "cache_hits": sum(c["cache"] == "hit" for c in all_calls),
                      "cost_usd_recorded": round(sum(c["total_cost_usd"] or 0 for c in all_calls), 4),
                      "tables_ok": sum(table_ok(t) for t in tables)}}
    (ctx.audit_dir / "links.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    return out
