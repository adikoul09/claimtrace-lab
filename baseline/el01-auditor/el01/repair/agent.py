"""Repair loop (spec section 4 and 9, step 1): run the smoke command, and on failure let the repair agent propose a
patch; code classifies it, commits it and runs again.

  1. Run the data step and the smoke command (train, then eval) at the run head, in a fresh worktree.
  2. On failure, classify the last traceback (el01/run/classify.py).
  3. Missing data domain (decided by code: the missing file's name pattern exists for other values of exactly one
     field): the agent writes the data-generation patch, which is committed as `HYPOTHESIS(Fn)` on `el01/h-Fn`, never
     on `el01/repair`; the loop then runs on that branch.
  4. Otherwise the agent returns edits; code renders the unified diff, `policy.classify_patch` decides the class,
     `git apply --check` runs against `el01/repair`, and the patch is committed there as `REPAIR(env|compat): ...`.
     A patch the policy calls a hypothesis is never committed as a repair: it goes to its own `el01/h-Fn` branch, not
     run, and the agent is asked again.
  5. Stop when every smoke step exits 0, or after `max_attempts` repair attempts (agent calls in repair mode): the
     verdict is then *Not runnable*.
  6. Compatibility repairs then get the inertness check (el01/repair/inertness.py); a repair that fails it is moved
     off `el01/repair` to a hypothesis branch.
Evidence: audits/<id>/repair.json, audits/<id>/repair/ (patches, prompts, agent answers, inertness), and the run
directories audits/<id>/runs/repair/ (git-ignored)."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from string import Template
from typing import Callable, Optional

from el01.config import AuditConfig, Paths
from el01.env.builder import build_env, parse_lock, venv_python
from el01.env.imports import scan
from el01.ingest.repo import GitError, ensure_clone, git, resolve, snapshot, tree_id
from el01.llm.backend import AGENT_TOOLS, LLM, Request
from el01.repair.policy import classify_patch, parse_unified_diff
from el01.run.classify import classify
from el01.run.runner import Job, run_jobs, utc_now
from el01.run.worktrees import ensure_worktree

LLM_DIR = Path(__file__).resolve().parent.parent / "llm"
SCHEMA = json.loads((LLM_DIR / "schemas" / "repair.json").read_text())
AGENT = "repair"
REPAIR_BRANCH = "el01/repair"
AUTHOR = {"GIT_AUTHOR_NAME": "EL-01 repair agent", "GIT_AUTHOR_EMAIL": "el01-repair@localhost",
          "GIT_COMMITTER_NAME": "EL-01 repair agent", "GIT_COMMITTER_EMAIL": "el01-repair@localhost"}
WINDOW = 40          # lines of source on each side of a traceback frame
MAX_TURNS = 40       # agent turns per call (Read/Grep/Glob + the structured answer)
HYPOTHESIS_TRIES = 2  # agent calls for one missing data domain


class RepairError(RuntimeError):
    pass


# ---- git ------------------------------------------------------------------------------------------------------------

def _git(cwd: Path, *args: str, input: Optional[str] = None, check: bool = True) -> subprocess.CompletedProcess:
    env = {**os.environ, **AUTHOR}
    p = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, input=input, env=env)
    if check and p.returncode != 0:
        raise GitError(f"git {' '.join(args)} (in {cwd}): {p.stderr.strip() or p.stdout.strip()}")
    return p


def _branch_exists(repo: Path, name: str) -> bool:
    return _git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{name}", check=False).returncode == 0


def _scratch(repo: Path, path: Path, ref: str) -> Path:
    """A worktree for building commits: detached, reset to `ref`, no untracked files."""
    path = Path(path)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        _git(repo, "worktree", "prune")
        _git(repo, "worktree", "add", "--detach", str(path), ref)
    _git(path, "checkout", "--detach", "--force", ref)
    _git(path, "reset", "--hard", ref)
    _git(path, "clean", "-fdq")
    return path


def _commit_patch(scratch: Path, base: str, diff: str, message: str) -> str:
    """Apply `diff` on `base` (git apply --check first) and commit. Returns the new sha; raises GitError on failure."""
    _git(scratch, "checkout", "--detach", "--force", base)
    _git(scratch, "reset", "--hard", base)
    _git(scratch, "apply", "--check", "-", input=diff)
    _git(scratch, "apply", "-", input=diff)
    _git(scratch, "add", "-A")
    _git(scratch, "commit", "-q", "-m", message)
    return _git(scratch, "rev-parse", "HEAD").stdout.strip()


def _cherry_pick(scratch: Path, base: str, commits: list[str]) -> list[str]:
    """Replay `commits` on `base`, in order. Returns the new shas."""
    _git(scratch, "checkout", "--detach", "--force", base)
    out = []
    for c in commits:
        p = _git(scratch, "cherry-pick", "--allow-empty", c, check=False)
        if p.returncode != 0:
            _git(scratch, "cherry-pick", "--abort", check=False)
            raise GitError(f"cherry-pick {c[:7]} onto {base[:7]}: {p.stderr.strip() or p.stdout.strip()}")
        out.append(_git(scratch, "rev-parse", "HEAD").stdout.strip())
    return out


def _remove_worktree(repo: Path, wt: Path) -> None:
    _git(repo, "worktree", "remove", "--force", str(wt), check=False)
    if wt.exists():
        shutil.rmtree(wt, ignore_errors=True)
    _git(repo, "worktree", "prune", check=False)


# ---- edits -> unified diff ----------------------------------------------------------------------------------------

def apply_edits(root: Path, edits: list[dict]) -> list[str]:
    """Apply search/replace edits in `root`. `old` must occur exactly once (exactly, or line by line ignoring trailing
    whitespace). Returns error messages (empty if every edit applied)."""
    errors = []
    root = Path(root).resolve()
    for i, e in enumerate(edits, 1):
        rel = str(e.get("file", "")).strip().replace("\\", "/")
        for prefix in ("./", "repo/"):  # the agent sees the repository as ./repo
            if rel.startswith(prefix):
                rel = rel[len(prefix):]
        f = (root / rel).resolve()
        if not str(f).startswith(str(root) + os.sep) or not f.is_file():
            errors.append(f"edit {i}: file {e.get('file')!r} is not a file of the repository")
            continue
        text, old, new = f.read_text(), e.get("old", ""), e.get("new", "")
        if old and text.count(old) == 1:
            f.write_text(text.replace(old, new, 1))
            continue
        lines = text.splitlines(keepends=True)
        olines = [l.rstrip() for l in old.strip("\n").splitlines()]
        if not olines or not any(olines):
            errors.append(f"edit {i}: empty `old` text for {rel}")
            continue
        hits = [k for k in range(len(lines) - len(olines) + 1)
                if all(lines[k + j].rstrip() == olines[j] for j in range(len(olines)))]
        if len(hits) != 1:
            errors.append(f"edit {i}: the `old` text occurs {len(hits)} times in {rel} (must be exactly once)")
            continue
        k = hits[0]
        last_nl = lines[k + len(olines) - 1].endswith("\n")
        body = new.strip("\n")
        repl = (body + ("\n" if last_nl else "")) if body else ""
        lines[k:k + len(olines)] = [repl]
        f.write_text("".join(lines))
    return errors


def render_diff(repo: Path, scratch: Path, head: str, edits: list[dict]) -> tuple[str, list[str]]:
    """The unified diff (git's own) of `edits` applied at `head`, and any edit errors. The scratch tree is reset."""
    _scratch(repo, scratch, head)
    errors = apply_edits(scratch, edits)
    diff = "" if errors else _git(scratch, "diff", "--no-color", "--no-ext-diff").stdout
    if not errors and not diff.strip():
        errors.append("the edits change nothing")
    _git(scratch, "reset", "--hard", head)
    _git(scratch, "clean", "-fdq")
    return diff, errors


def run_path(worktree: Path, entry_points: list[str]) -> Optional[set[str]]:
    """Repo files the audited commands run: the entry points and the repo modules they import (AST scan, Phase 2).
    None when the audit lists no entry points (then the check is skipped)."""
    if not entry_points:
        return None
    return set(scan(Path(worktree), list(entry_points)).local_files) | set(entry_points)


def outside_run_path(diff: str, allowed: Optional[set[str]]) -> list[str]:
    if allowed is None:
        return []
    return sorted({f.path for f in parse_unified_diff(diff)} - allowed)


def first_location(diff: str) -> Optional[str]:
    """file:line of the first changed line, in the old file's numbering (as the spike's commit messages)."""
    for f in parse_unified_diff(diff):
        if f.removed:
            return f"{f.path}:{f.removed[0][0]}"
        if f.added:
            return f"{f.path}:{f.added[0][0]}"
    return None


def locations(diff: str) -> list[str]:
    out = []
    for f in parse_unified_diff(diff):
        nums = [n for n, _ in f.removed] or [n for n, _ in f.added]
        out.append(f"{f.path}:{nums[0]}" if nums else f.path)
    return out


# ---- the failure, as the agent sees it ----------------------------------------------------------------------------

NUM_RE = re.compile(r"\d+(?:\.\d+)?")


def missing_domain(failure: dict, worktree: Path, command: list[str]) -> Optional[dict]:
    """A missing data file whose name pattern exists for other values of exactly one numeric field."""
    if failure.get("class") != "missing data" or not failure.get("missing_path"):
        return None
    missing = failure["missing_path"]
    P = PureWindowsPath if "\\" in missing else PurePosixPath
    mp = P(missing)
    folder = Path(missing).parent if mp.is_absolute() else Path(worktree) / Path(*mp.parent.parts)
    if not folder.is_dir():
        return None
    texts, nums = NUM_RE.split(mp.name), NUM_RE.findall(mp.name)
    if not nums:
        return None
    sibs = []
    for f in sorted(folder.iterdir()):
        if NUM_RE.split(f.name) == texts:
            sibs.append((f.name, NUM_RE.findall(f.name)))
    if not sibs:
        return None
    gaps = [i for i in range(len(nums)) if float(nums[i]) not in {float(s[1][i]) for s in sibs}]
    if len(gaps) != 1:
        return None
    i = gaps[0]
    field = texts[i].strip("_-. ") or f"field {i + 1}"  # the name written before the value
    generated = sorted({float(s[1][i]) for s in sibs})
    flag = None
    def _num_eq(tok: str) -> bool:
        try:
            return float(tok) == float(nums[i])
        except ValueError:
            return False
    for same in (lambda t: t == nums[i], _num_eq):  # the exact spelling first, then the same number
        k = next((k for k, t in enumerate(command) if not t.startswith("-") and same(t)), None)
        if k is not None:
            j = k
            while j > 0 and not command[j].startswith("--"):
                j -= 1
            flag = command[j] if command[j].startswith("--") else None
            break
    rel_dir = mp.parent.as_posix() if not mp.is_absolute() else str(mp.parent)
    return {"field": field, "missing_value": nums[i], "generated_values": [f"{v:g}" for v in generated],
            "flag": flag, "missing": missing, "dir": rel_dir, "siblings": len(sibs),
            "examples": [s[0] for s in sibs if all(s[1][j] == nums[j] for j in range(len(nums)) if j != i)][:3]}


VOLATILE = [(re.compile(r"\b(pid\(?s?\)?\s*)\d+(\s*,\s*\d+)*"), r"\1N"),   # process ids
            (re.compile(r"\b0x[0-9a-fA-F]{6,}\b"), "0x..."),                   # memory addresses
            (re.compile(r"/(?:private/)?(?:tmp|var/folders)/[^\s'\"]+"), "<tmp>")]  # temporary paths


def normalise(text: str, subs: list[tuple[str, str]]) -> str:
    """Machine paths -> repo-relative / <env> / <python>; process ids, addresses, temp paths -> placeholders. The same
    failure then gives the same prompt on any machine and in any run (cache keys, rule 8)."""
    for a, b in subs:
        text = text.replace(a, b)
    for rx, rep in VOLATILE:
        text = rx.sub(rep, text)
    return text


def traceback_text(log: Path, failure: dict, subs: list[tuple[str, str]]) -> str:
    lines = Path(log).read_text(errors="replace").splitlines()
    return normalise("\n".join(lines[failure["traceback_line"] - 1: failure["log_line"]]), subs)


def source_windows(root: Path, failure: dict) -> str:
    seen, parts = set(), []
    locs = [(f["repo_file"], f["line"]) for f in failure.get("frames", []) if f.get("repo_file")]
    if failure.get("origin"):
        locs.append((failure["origin"]["file"], failure["origin"]["line"]))
    for rel, n in locs:
        if (rel, n) in seen:
            continue
        seen.add((rel, n))
        p = Path(root) / rel
        if not p.is_file():
            continue
        src = p.read_text(errors="replace").splitlines()
        lo, hi = max(1, n - WINDOW), min(len(src), n + WINDOW)
        body = "\n".join(f"{k:5d}{'>' if k == n else ' '} {src[k - 1]}" for k in range(lo, hi + 1))
        parts.append(f"--- {rel}:{n} (lines {lo}-{hi}) ---\n```\n{body}\n```")
    return "\n\n".join(parts) if parts else "(no frame in the repository)"


def _prompt(name: str, **kw) -> str:
    return Template((LLM_DIR / "prompts" / f"{name}.md").read_text()).substitute(**kw)


# ---- the loop -------------------------------------------------------------------------------------------------------

@dataclass
class Ctx:
    paths: Paths
    cfg: AuditConfig
    repo: Path
    audit_dir: Path
    out_dir: Path      # audits/<id>/repair/  (committed evidence)
    runs_dir: Path     # audits/<id>/runs/repair/
    wt_root: Path      # workspace/worktrees/<id>/repair/
    scratch: Path
    py: Path
    llm: LLM
    echo: Callable[[str], None]
    subs: list

    def rel(self, p: Path) -> str:
        return Path(p).relative_to(self.audit_dir).as_posix()


def _clean_previous(ctx: Ctx) -> None:
    for b in _git(ctx.repo, "for-each-ref", "--format=%(refname:short)", "refs/heads/el01/").stdout.split():
        _git(ctx.repo, "branch", "-D", b)
    if ctx.wt_root.exists():
        for wt in sorted(ctx.wt_root.iterdir()):
            _remove_worktree(ctx.repo, wt)
    for d in (ctx.runs_dir, ctx.out_dir):
        if d.exists():
            shutil.rmtree(d)
    for f in (ctx.audit_dir / "repair.json",):
        if f.exists():
            f.unlink()


def run_smoke(ctx: Ctx, run_dir: Path, head: str, wt_name: str, command: Optional[list[str]] = None,
              eval_command: Optional[list[str]] = None) -> dict:
    """Data step, then the smoke command and its eval, at `head` in a fresh worktree. Returns the run record.
    `command` / `eval_command` replace audit.yaml's smoke commands (used by the comparison runs)."""
    cfg = ctx.cfg
    wt, sha = ensure_worktree(ctx.repo, head, ctx.wt_root / wt_name)
    budget = dict(max_parallel=1, wall_minutes=cfg.budget.max_wall_minutes, python=ctx.py)
    rec = {"head": sha, "worktree": wt_name, "run_dir": ctx.rel(run_dir), "jobs": [], "ok": False, "failure": None}
    steps = []
    if cfg.smoke.data:
        steps.append((run_dir / "data", [Job("datagen", wt, cfg.smoke.data)]))
    jobs = [Job(cfg.smoke.name, wt, command or cfg.smoke.command, seeds=cfg.smoke.seeds)]
    if eval_command or cfg.smoke.eval:
        jobs.append(Job(cfg.smoke.eval_name, wt, eval_command or cfg.smoke.eval, seeds=cfg.smoke.seeds))
    steps.append((run_dir, jobs))
    for d, js in steps:
        res = run_jobs(d, js, **budget)
        for j in js:
            st = res["status"][j.name]
            rec["jobs"].append({"name": j.name, "command": list(j.argv), "status": st["status"],
                                "exit_code": st["exit_code"], "seconds": st["seconds"],
                                "log": ctx.rel(d / j.log_name)})
            ctx.echo(f"    {j.name}: {st['status']} (exit {st['exit_code']}) in {st['seconds']}s")
        bad = next((j for j in js if res["status"][j.name]["exit_code"] != 0), None)
        if bad is not None:
            log = d / bad.log_name
            f = classify(log, log_roots=[str(wt)], source_root=wt, inside=[wt, ctx.paths.workspace])
            if f is None:
                f = {"class": "other", "rule": "non-zero exit without a Python traceback", "exception": None,
                     "message": None, "location": None, "frames": [], "log_line": None, "traceback_line": None}
            f["log"] = ctx.rel(log)
            f["job"] = bad.name
            f["command"] = list(bad.argv)
            (d / "failure.json").write_text(json.dumps(f, indent=1))
            rec["failure"] = f
            rec["_wt"] = wt
            return rec
    rec["ok"] = True
    rec["_wt"] = wt
    return rec


def _failure_summary(f: Optional[dict]) -> Optional[dict]:
    if f is None:
        return None
    keys = ("class", "rule", "exception", "message", "location", "missing_path", "job", "log", "log_line",
            "traceback_line")
    out = {k: f.get(k) for k in keys if f.get(k) is not None}
    if f.get("raised_at"):
        out["raised_at"] = f"{f['raised_at']['file']}:{f['raised_at']['line']}"
    return out


def _ask(ctx: Ctx, n_call: int, mode: str, prompt: str, head: str) -> dict:
    snap = snapshot(ctx.repo, head, ctx.paths.workspace / "snapshots" / ctx.cfg.id)
    req = Request(agent=AGENT, prompt=prompt, schema=SCHEMA, model=ctx.cfg.llm.model,
                  inputs={"repo_tree": tree_id(ctx.repo, head)}, tools=AGENT_TOOLS, repo_copy=snap,
                  max_turns=MAX_TURNS)
    (ctx.out_dir / f"call_{n_call:02d}_{mode}.prompt.md").write_text(prompt)
    resp = ctx.llm.call(req)
    out = resp.output if isinstance(resp.output, dict) else {}
    meta = resp.record["response"]
    return {"answer": {"edits": out.get("edits", []), "class": out.get("class"), "rationale": out.get("rationale")},
            "cache": resp.cache, "key": resp.key, "backend": resp.backend,
            "usage": {"total_cost_usd": meta.get("total_cost_usd"), "num_turns": meta.get("num_turns"),
                      "models": meta.get("models")}}


def _previous(rejected: list[dict]) -> str:
    if not rejected:
        return ""
    lines = ["", "Earlier answers to this failure that the audit could not use:"]
    for r in rejected:
        lines.append(f"- {r['reason']}")
    lines.append("")
    return "\n".join(lines) + "\n"


def run_repair(paths: Paths, cfg: AuditConfig, llm: LLM, max_attempts: int = 5, restart: bool = False,
               echo: Callable[[str], None] = print, python: Optional[Path] = None) -> dict:
    """`python`: run the audited code with this interpreter instead of the date-pinned env (tests only)."""
    if cfg.smoke is None:
        raise ValueError(f"audits/{cfg.id}/audit.yaml has no smoke command")
    env = build_env(paths, cfg, echo=lambda s: None) if python is None else None
    repo = ensure_clone(cfg.repo.url, paths.repos / Path(cfg.repo.url.rstrip("/")).name.removesuffix(".git"))
    base = resolve(repo, cfg.repo.commit)
    audit_dir = paths.audit_dir(cfg.id)
    env_dir = paths.envs / cfg.id
    home = None
    cfgfile = env_dir / "pyvenv.cfg"
    if cfgfile.exists():
        for line in cfgfile.read_text().splitlines():
            if line.split("=")[0].strip() == "home":
                home = str(Path(line.split("=", 1)[1].strip()).parent)
    wt_root = paths.worktrees / cfg.id / "repair"
    subs = []
    ctx = Ctx(paths, cfg, repo, audit_dir, audit_dir / "repair", audit_dir / "runs" / "repair", wt_root,
              paths.worktrees / cfg.id / "repair-git", Path(python) if python else venv_python(env_dir), llm, echo,
              subs)

    if _branch_exists(repo, REPAIR_BRANCH) or (audit_dir / "repair.json").exists() or ctx.runs_dir.exists():
        if not restart:
            raise RepairError(f"a previous repair run exists ({REPAIR_BRANCH}, audits/{cfg.id}/repair.json or "
                              f"runs/repair/); pass --restart to delete it and start again from {base[:7]}")
        _clean_previous(ctx)
    ctx.out_dir.mkdir(parents=True, exist_ok=True)
    ctx.runs_dir.mkdir(parents=True, exist_ok=True)
    _scratch(repo, ctx.scratch, base)
    _git(repo, "branch", "-f", REPAIR_BRANCH, base)

    if env is not None:
        freeze = parse_lock("\n".join(env["freeze"]))
        env_rec = {"python": env["python"]["installed"], "torch": freeze.get("torch"), "plan_hash": env["plan_hash"]}
    else:
        env_rec = {"python": str(python), "note": "interpreter given by the caller (test)"}
    rec = {"audit": cfg.id, "repo": cfg.repo.url, "base_commit": base, "started_utc": utc_now(),
           "env": env_rec,
           "llm": {"backend": llm.mode, "model": cfg.llm.model, "cli_version": llm.cli_version,
                   "usage_log": "llm_usage.jsonl"},
           "max_attempts": max_attempts, "smoke": {"data": cfg.smoke.data, "command": cfg.smoke.command,
                                                   "eval": cfg.smoke.eval},
           "runs": [], "agent_calls": [], "repairs": [], "hypotheses": [], "inertness": [], "verdict": None}

    repair_head, run_head = base, base
    run_hyps: list[dict] = []      # hypotheses the loop runs on (missing data domains), in order
    n_run = n_call = repair_attempts = 0
    prev_wt: Optional[Path] = None
    last_ok: Optional[dict] = None
    last_commit_failure: Optional[str] = None

    def save():
        (audit_dir / "repair.json").write_text(json.dumps(rec, indent=1, ensure_ascii=False))

    def new_finding() -> str:
        return f"F{len(rec['hypotheses']) + 1}"

    def rebuild_hyps():
        nonlocal run_head
        head = repair_head
        if run_hyps:
            new = _cherry_pick(ctx.scratch, repair_head, [h["commit"] for h in run_hyps])
            for h, c in zip(run_hyps, new):
                h["commit"] = c
                _git(repo, "branch", "-f", h["branch"], c)
                rec_h = next(x for x in rec["hypotheses"] if x["finding"] == h["finding"])
                rec_h["commit"] = c
                rec_h["base"] = repair_head
            head = new[-1]
        run_head = head

    while True:
        n_run += 1
        run_dir = ctx.runs_dir / f"attempt_{n_run:02d}"
        echo(f"run {n_run} at {run_head[:7]}")
        run = run_smoke(ctx, run_dir, run_head, f"a{n_run:02d}-{run_head[:7]}")
        wt = run.pop("_wt")
        if prev_wt is not None and prev_wt != wt:
            _remove_worktree(repo, prev_wt)
        prev_wt = wt
        f = run["failure"]
        run["failure"] = _failure_summary(f)
        rec["runs"].append({"n": n_run, **run})
        save()
        if run["ok"]:
            last_ok = {"n": n_run, "head": run_head, "worktree": wt, "run_dir": run_dir}
            rec["verdict"] = "runs"
            echo(f"  runs: every smoke step exited 0")
            break
        echo(f"  failure: {f['class']} at {f.get('location')} ({f['exception']}: {(f.get('message') or '')[:120]})")
        ctx.subs[:] = [(str(wt) + os.sep, ""), (str(wt.resolve()) + os.sep, ""), (str(env_dir) + os.sep, "<env>/"),
                       (str(env_dir.resolve()) + os.sep, "<env>/")] + ([(home + os.sep, "<python>/")] if home else [])
        tb = traceback_text(audit_dir / f["log"], f, ctx.subs) if f.get("traceback_line") else "(no traceback)"
        windows = source_windows(wt, f)
        command = " ".join(f["command"])
        fkey = f"{f['class']}|{f.get('location')}|{f.get('exception')}"

        dom = missing_domain(f, wt, f["command"])
        if dom and not any(h.get("domain") == [dom["field"], dom["missing_value"]] for h in rec["hypotheses"]):
            echo(f"  missing data domain: {dom['field']} = {dom['missing_value']} "
                 f"(generated: {', '.join(dom['generated_values'])}) -> hypothesis branch, not a repair")
            rejected, done = [], False
            for _ in range(HYPOTHESIS_TRIES):
                n_call += 1
                prompt = _prompt("missing_domain", command=command, missing=dom["missing"],
                                 field=dom["field"], generated=", ".join(dom["generated_values"]),
                                 missing_value=dom["missing_value"],
                                 flag_note=f" (from its argument {dom['flag']})" if dom["flag"] else "",
                                 examples=", ".join(dom["examples"]) or "-",
                                 data_command=" ".join(cfg.smoke.data or ["(none)"]), previous=_previous(rejected))
                a = _ask(ctx, n_call, "hypothesis", prompt, run_head)
                call = {"n": n_call, "mode": "missing data domain", "run": n_run, "failure": fkey, **a}
                diff, errs = render_diff(repo, ctx.scratch, run_head, a["answer"]["edits"])
                if errs:
                    call["outcome"] = "rejected: " + "; ".join(errs)
                    rejected.append({"reason": "; ".join(errs)})
                    rec["agent_calls"].append(call)
                    save()
                    continue
                pol = classify_patch(diff, f["class"], f.get("exception"), "hypothesis")
                finding = new_finding()
                msg = (f"HYPOTHESIS({finding}): {a['answer']['rationale'].strip().rstrip('.')} "
                       f"({', '.join(locations(diff))})")
                try:
                    c = _commit_patch(ctx.scratch, run_head, diff, msg)
                except GitError as e:
                    call["outcome"] = f"rejected: {e}"
                    rejected.append({"reason": f"the patch does not apply: {e}"})
                    rec["agent_calls"].append(call)
                    save()
                    continue
                branch = f"el01/h-{finding}"
                _git(repo, "branch", "-f", branch, c)
                pfile = ctx.out_dir / f"{finding}-hypothesis.patch"
                pfile.write_text(diff)
                h = {"finding": finding, "branch": branch, "commit": c, "base": repair_head, "message": msg,
                     "patch": ctx.rel(pfile), "kind": "missing data domain", "domain": [dom["field"], dom["missing_value"]],
                     "detail": dom, "policy": pol, "run_by_loop": True, "call": n_call}
                rec["hypotheses"].append(h)
                run_hyps.append({"finding": finding, "branch": branch, "commit": c})
                call["outcome"] = f"committed {c[:7]} on {branch}"
                call["policy"] = pol
                rec["agent_calls"].append(call)
                (ctx.out_dir / f"call_{n_call:02d}_hypothesis.answer.json").write_text(json.dumps(call, indent=1))
                echo(f"  {msg[:110]}  -> {branch} {c[:7]}")
                run_head = c
                done = True
                save()
                break
            if not done:
                rec["verdict"] = "Not runnable"
                rec["verdict_reason"] = (f"the missing data domain {dom['field']} = {dom['missing_value']} could not "
                                         f"be generated in {HYPOTHESIS_TRIES} agent calls")
                break
            continue

        allowed = run_path(wt, cfg.env.entry_points)
        if last_commit_failure == fkey:
            note = [{"reason": f"the last committed repair did not remove this failure ({fkey})"}]
        else:
            note = []
        rejected, committed = list(note), False
        while repair_attempts < max_attempts:
            repair_attempts += 1
            n_call += 1
            prompt = _prompt("repair", command=command, failure_class=f["class"],
                             failure_rule=f["rule"], traceback=tb, windows=windows,
                             entry_points=", ".join(cfg.env.entry_points) or "(not listed)",
                             previous=_previous(rejected))
            echo(f"  repair attempt {repair_attempts}/{max_attempts} (agent call {n_call})")
            a = _ask(ctx, n_call, "repair", prompt, run_head)
            call = {"n": n_call, "mode": "repair", "attempt": repair_attempts, "run": n_run, "failure": fkey, **a}
            diff, errs = render_diff(repo, ctx.scratch, run_head, a["answer"]["edits"])
            outside = [] if errs else outside_run_path(diff, allowed)
            if errs:
                call["outcome"] = "rejected: " + "; ".join(errs)
                rejected.append({"reason": "; ".join(errs)})
            elif outside:
                call["outcome"] = "rejected: changes files the audited commands do not run: " + ", ".join(outside)
                rejected.append({"reason": "a patch that also changed files the audited commands never run ("
                                           + ", ".join(outside) + "); change only the entry points and the "
                                           "repository modules they import"})
                echo(f"  rejected: touches files outside the run path: {', '.join(outside)}")
            else:
                pol = classify_patch(diff, f["class"], f.get("exception"), a["answer"]["class"])
                call["policy"] = pol
                cls = pol["class"]
                if cls == "hypothesis":
                    finding = new_finding()
                    msg = (f"HYPOTHESIS({finding}): {a['answer']['rationale'].strip().rstrip('.')} "
                           f"({', '.join(locations(diff))})")
                    pfile = ctx.out_dir / f"{finding}-hypothesis.patch"
                    pfile.write_text(diff)
                    try:
                        c = _commit_patch(ctx.scratch, repair_head, diff, msg)
                    except GitError:
                        c = _commit_patch(ctx.scratch, run_head, diff, msg)
                    branch = f"el01/h-{finding}"
                    _git(repo, "branch", "-f", branch, c)
                    rec["hypotheses"].append({"finding": finding, "branch": branch, "commit": c, "message": msg,
                                              "patch": ctx.rel(pfile), "kind": "rejected repair", "policy": pol,
                                              "run_by_loop": False, "call": n_call})
                    call["outcome"] = f"not a repair (policy: hypothesis); kept as {branch} {c[:7]}, not run"
                    rejected.append({"reason": f"a patch that the audit classed as a hypothesis, not a repair "
                                               f"({pol['basis']}); propose a patch that only makes the code run"})
                    echo(f"  policy: hypothesis ({pol['basis'][:100]}) -> {branch}, not run")
                else:
                    loc = ", ".join(locations(diff))
                    msg = f"REPAIR({cls}): {a['answer']['rationale'].strip().rstrip('.')} ({loc})"
                    try:
                        c = _commit_patch(ctx.scratch, repair_head, diff, msg)
                    except GitError as e:
                        call["outcome"] = f"rejected: git apply --check failed on {REPAIR_BRANCH}: {e}"
                        rejected.append({"reason": "the patch does not apply to the repaired code without the "
                                                   "hypothesis branch; change only lines outside the data generation"})
                    else:
                        repair_head = c
                        _git(repo, "branch", "-f", REPAIR_BRANCH, c)
                        n_rep = len(rec["repairs"]) + 1
                        pfile = ctx.out_dir / f"{n_rep:02d}-repair-{cls}.patch"
                        pfile.write_text(diff)
                        rec["repairs"].append({"n": n_rep, "commit": c, "class": cls, "llm_class": a["answer"]["class"],
                                               "message": msg, "files": pol["files"], "locations": locations(diff),
                                               "patch": ctx.rel(pfile), "policy": pol, "call": n_call,
                                               "failure": _failure_summary(f), "run": n_run})
                        rebuild_hyps()
                        call["outcome"] = f"committed {c[:7]} on {REPAIR_BRANCH}"
                        echo(f"  {msg[:120]}  -> {c[:7]}")
                        committed = True
            rec["agent_calls"].append(call)
            (ctx.out_dir / f"call_{n_call:02d}_repair.answer.json").write_text(json.dumps(call, indent=1))
            save()
            if committed:
                break
        if not committed:
            rec["verdict"] = "Not runnable"
            rec["verdict_reason"] = f"still failing after {repair_attempts} repair attempts (limit {max_attempts})"
            echo(f"  Not runnable: {rec['verdict_reason']}")
            break
        last_commit_failure = fkey

    # ---- inertness of compatibility repairs ----------------------------------------------------------------------
    if rec["verdict"] == "runs":
        from el01.repair.inertness import check_inertness
        for r in [r for r in rec["repairs"] if r["class"] == "compat"]:
            res = check_inertness(ctx, r, last_ok)
            rec["inertness"].append(res)
            save()
            echo(f"  inertness of {r['commit'][:7]}: {res['verdict']} ({res['summary']})")
            if res["verdict"] != "inert":
                rec["verdict"] = "Not runnable"
                rec["verdict_reason"] = (f"compatibility repair {r['commit'][:7]} failed the inertness check; it is "
                                         f"a hypothesis, not a repair")
                _reclassify(ctx, rec, r, repair_head)
                break

    rec["branches"] = {b: _git(repo, "rev-parse", b).stdout.strip() for b in
                       _git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads/el01/").stdout.split()}
    rec["counts"] = {"runs": len(rec["runs"]), "agent_calls": len(rec["agent_calls"]),
                     "repair_attempts": repair_attempts, "repairs": len(rec["repairs"]),
                     "hypotheses": len(rec["hypotheses"]),
                     "cache_hits": sum(1 for c in rec["agent_calls"] if c["cache"] == "hit"),
                     "cache_misses": sum(1 for c in rec["agent_calls"] if c["cache"] == "miss"),
                     "cost_usd_recorded": round(sum((c["usage"].get("total_cost_usd") or 0)
                                                    for c in rec["agent_calls"]), 4)}
    rec["ended_utc"] = utc_now()
    save()
    return rec


def _reclassify(ctx: Ctx, rec: dict, r: dict, repair_head: str) -> None:
    """Move a compatibility repair that failed the inertness check off el01/repair, onto a hypothesis branch."""
    repo = ctx.repo
    chain = [x["commit"] for x in rec["repairs"]]
    i = chain.index(r["commit"])
    parent = _git(repo, "rev-parse", f"{r['commit']}^").stdout.strip()
    rest = _cherry_pick(ctx.scratch, parent, chain[i + 1:]) if chain[i + 1:] else []
    new_head = rest[-1] if rest else parent
    _git(repo, "branch", "-f", REPAIR_BRANCH, new_head)
    finding = f"F{len(rec['hypotheses']) + 1}"
    msg = r["message"].replace(f"REPAIR({r['class']})", f"HYPOTHESIS({finding})", 1)
    _scratch(repo, ctx.scratch, new_head)
    _git(ctx.scratch, "cherry-pick", "--no-commit", r["commit"])
    _git(ctx.scratch, "commit", "-q", "-m", msg)
    c = _git(ctx.scratch, "rev-parse", "HEAD").stdout.strip()
    branch = f"el01/h-{finding}"
    _git(repo, "branch", "-f", branch, c)
    r["reclassified_as"] = finding
    rec["hypotheses"].append({"finding": finding, "branch": branch, "commit": c, "message": msg,
                              "patch": r["patch"], "kind": "failed inertness check", "run_by_loop": False})
