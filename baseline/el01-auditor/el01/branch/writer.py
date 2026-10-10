"""Branch-patch writer (spec section 6, step 1; section 9, step 3): one HYPOTHESIS branch per finding and reading.

For each numbered finding in audits/<id>/extraction_score.json (the checker's mapping of the settings diff to
F-numbers; findings without a number get no branch, and the baseline's own findings, audit.yaml
`ablation.baseline_findings`, are already in the baseline):
  1. The finding's values and evidence come from the first pairing where the checker found it with verified evidence
     (settings_diff.json for the values, settings.json for the quotes and citations, verified items only).
  2. The `branch_writer` agent (Read/Grep/Glob on a snapshot of the baseline, as ./repo) answers with one reading, or
     one per reading when the paper's words admit several implementations, each as search/replace edits.
  3. Code renders each reading's edits as git's unified diff on the baseline and rejects: edits that do not apply,
     comments in added lines, files outside the run path (the entry points, the modules they import, and the files the
     finding's code evidence cites). Then it commits `HYPOTHESIS(Fn): <setting>: <paper value> instead of <code
     value>` on `el01/h-Fn` (or `el01/h-Fn.<k>` per reading) off the baseline.
  4. Self-check (selfcheck.py): the code extractor on the branch snapshot vs on the baseline snapshot (same replicate);
     a branch that touches a data step's script also gets the data-step check (datacheck.py), reported only.
  5. A rejected reading is asked again with code's findings, at most `RETRIES` times; then it is "branch not written".
Evidence: audits/<id>/branches.json, audits/<id>/branches/<Fn>/ (prompts, answers, patches, self-checks)."""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import tokenize
from dataclasses import dataclass, field
from pathlib import Path
from string import Template
from typing import Callable, Optional

from el01.branch import selfcheck as sc
from el01.config import AuditConfig, Paths
from el01.extract import settings as S
from el01.extract.claims import load_claims
from el01.ingest.repo import GitError, ensure_clone, resolve, snapshot, tree_id
from el01.llm.backend import AGENT_TOOLS, LLM, Request
from el01.repair.agent import apply_edits, run_path
from el01.repair.policy import parse_unified_diff

LLM_DIR = Path(__file__).resolve().parent.parent / "llm"
SCHEMA = json.loads((LLM_DIR / "schemas" / "branch.json").read_text())
AGENT = "branch_writer"
MAX_TURNS = 40
RETRIES = 2              # calls after the first, per reading
SELFCHECK_REPLICATE = 1
AUTHOR = {"GIT_AUTHOR_NAME": "EL-01 branch writer", "GIT_AUTHOR_EMAIL": "el01-branch@localhost",
          "GIT_COMMITTER_NAME": "EL-01 branch writer", "GIT_COMMITTER_EMAIL": "el01-branch@localhost"}
TABLE_KEYS = {"table1": "Table 1", "table11": "Suppl. Table 11"}
KIND_TEXT = {
    "difference": "Kind: difference. The paper states one value; the code uses another.",
    "paper omission": "Kind: paper omission. The code has this step or value; the paper describes the method without "
                      "it. The paper's version is the method without the code's extra step (for a value, the plain "
                      "form the paper's description implies).",
    "code omission": "Kind: code omission. The paper states it; the code does not have it.",
}


class BranchError(RuntimeError):
    pass


def _git(cwd: Path, *args: str, input: Optional[str] = None, check: bool = True) -> subprocess.CompletedProcess:
    p = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, input=input,
                       env={**os.environ, **AUTHOR})
    if check and p.returncode != 0:
        raise GitError(f"git {' '.join(args)} (in {cwd}): {p.stderr.strip() or p.stdout.strip()}")
    return p


def scratch(repo: Path, path: Path, ref: str) -> Path:
    path = Path(path)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        _git(repo, "worktree", "prune")
        _git(repo, "worktree", "add", "--detach", str(path), ref)
    _git(path, "checkout", "--detach", "--force", ref)
    _git(path, "reset", "--hard", ref)
    _git(path, "clean", "-fdq")
    return path


def commit_patch(wt: Path, base: str, diff: str, message: str) -> str:
    _git(wt, "checkout", "--detach", "--force", base)
    _git(wt, "reset", "--hard", base)
    _git(wt, "apply", "--check", "-", input=diff)
    _git(wt, "apply", "-", input=diff)
    _git(wt, "add", "-A")
    _git(wt, "commit", "-q", "-m", message)
    return _git(wt, "rev-parse", "HEAD").stdout.strip()


def cherry_pick(wt: Path, base: str, commits: list[str], message: Optional[str] = None) -> str:
    """`commits` replayed on `base` (squashed into one commit with `message` when given). Returns the new head."""
    _git(wt, "checkout", "--detach", "--force", base)
    for c in commits:
        p = _git(wt, "cherry-pick", "--no-commit" if message else "--allow-empty", c, check=False)
        if p.returncode != 0:
            _git(wt, "cherry-pick", "--abort", check=False)
            _git(wt, "reset", "--hard", base, check=False)
            raise GitError(f"cherry-pick {c[:7]} onto {base[:7]}: {p.stderr.strip() or p.stdout.strip()}")
    if message:
        _git(wt, "commit", "-q", "-m", message)
    return _git(wt, "rev-parse", "HEAD").stdout.strip()


def render(repo: Path, wt: Path, head: str, edits: list[dict]) -> tuple[str, list[str]]:
    scratch(repo, wt, head)
    errors = apply_edits(wt, edits)
    diff = "" if errors else _git(wt, "diff", "--no-color", "--no-ext-diff").stdout
    if not errors and not diff.strip():
        errors.append("the edits change nothing")
    _git(wt, "reset", "--hard", head)
    _git(wt, "clean", "-fdq")
    return diff, errors


# ---- code checks on a patch ----------------------------------------------------------------------------------------

def added_comments(diff: str, new_text: Callable[[str], Optional[str]]) -> list[str]:
    """file:line of every comment on an added line (Python files: tokenize the new file; others: a leading #)."""
    out = []
    for f in parse_unified_diff(diff):
        added = {n for n, _ in f.added}
        if not added:
            continue
        text = new_text(f.path)
        if f.path.endswith(".py") and text is not None:
            try:
                for tok in tokenize.generate_tokens(io.StringIO(text).readline):
                    if tok.type == tokenize.COMMENT and tok.start[0] in added:
                        out.append(f"{f.path}:{tok.start[0]}")
            except (tokenize.TokenError, IndentationError, SyntaxError):
                out += [f"{f.path}:{n}" for n, l in f.added if l.lstrip().startswith("#")]
        else:
            out += [f"{f.path}:{n}" for n, l in f.added if l.lstrip().startswith("#")]
    return out


def _new_file_text(repo: Path, wt: Path, head: str, diff: str) -> Callable[[str], Optional[str]]:
    scratch(repo, wt, head)
    _git(wt, "apply", "-", input=diff, check=False)
    texts = {}
    for f in parse_unified_diff(diff):
        p = wt / f.path
        texts[f.path] = p.read_text(errors="replace") if p.is_file() else None
    _git(wt, "reset", "--hard", head)
    _git(wt, "clean", "-fdq")
    return texts.get


# ---- findings -------------------------------------------------------------------------------------------------------

@dataclass
class Finding:
    id: str
    table: str                 # claims table name, e.g. "Table 1"
    what: str
    kind: str
    setting_ids: list[str]
    pairing: str
    entries: list[dict]        # the diff's findings for it in that pairing
    paper_evidence: list[dict]
    code_evidence: list[dict]
    also_in: list[str] = field(default_factory=list)

    @property
    def wanted(self) -> set:
        return sc.finding_settings(self.setting_ids)

    @property
    def keys(self) -> list[str]:
        return sorted({json.loads(s)[0] for s in self.setting_ids})

    def methods(self) -> Optional[list[str]]:
        ms = []
        for e in self.entries:
            m = e.get("method")
            if m in (None, "all"):
                return None
            ms += m if isinstance(m, list) else [m]
        return sorted(set(ms))


def _num(fid: str) -> int:
    return int(fid[1:])


def load_findings(paths: Paths, cfg: AuditConfig, skip: tuple = ()) -> list[Finding]:
    d = paths.audit_dir(cfg.id)
    score = json.loads((d / "extraction_score.json").read_text())
    settings, diffs = S.load_settings(paths, cfg.id)
    st = {t["target"]: t for t in settings["tables"]}
    df = {t["target"]: t for t in diffs["tables"]}
    out: dict[str, Finding] = {}
    for tk, table in TABLE_KEYS.items():
        sec = score.get(tk)
        if not sec:
            continue
        for F in sorted(sec["summary"], key=_num):
            if F in skip:
                continue
            if F in out:
                out[F].also_in.append(table)
                continue
            pairing = next((p for p in sorted(sec["pairings"]) if sec["pairings"][p][F]["found"]
                            and sec["pairings"][p][F]["verified"]), None)
            if pairing is None:
                continue
            ids = sec["pairings"][pairing][F]["setting_ids"]
            entries = [f for f in df[table]["pairings"][pairing] if S.setting_id(f) in ids]
            pn, cn = [x.strip() for x in pairing.split(" x ")]
            runs = st[table]["runs"]
            keys = sorted({k for s in ids for k in sc.raw_keys(json.loads(s)[0])})
            pev = [{"key": k, **{f: ev.get(f) for f in ("doc", "page", "quote")}} for k in keys
                   for ev, c in zip(runs[pn]["settings"][k]["evidence"], runs[pn]["settings"][k]["checks"]) if c["ok"]]
            cev = [{"key": k, "file": c["file"], "lines": ev.get("lines"), "code": ev.get("code")} for k in keys
                   for ev, c in zip(runs[cn]["settings"][k]["evidence"], runs[cn]["settings"][k]["checks"]) if c["ok"]]
            out[F] = Finding(F, table, sec["summary"][F]["what"], sorted({f["kind"] for f in entries})[0], ids,
                             pairing, entries, pev, cev)
    return [out[k] for k in sorted(out, key=_num)]


# ---- prompts --------------------------------------------------------------------------------------------------------

def _describe(key: str) -> str:
    k = next((x for x in S.SCHEMA_V2["keys"] if x["key"] == key), None)
    return (k.get("describe_code") or k["describe"]) if k else ""


def _val(v) -> str:
    return json.dumps(v, ensure_ascii=False, default=str) if not isinstance(v, str) else v


def setting_text(f: Finding) -> str:
    lines = []
    for k in f.keys:
        base = k.removesuffix(".weight_schedule") if k == "loss.terms.weight_schedule" else k
        lines.append(f"- `{k}`: {_describe(base)}")
    rows: dict = {}
    for e in f.entries:
        m = e.get("method")
        m = ", ".join(m) if isinstance(m, list) else (m or "all")
        sig = (e["key"], _val(e.get("paper")) if "paper" in e else "not stated", _val(e.get("code")))
        rows.setdefault(sig, []).append(m)
    for (k, p, c), ms in rows.items():
        lines.append(f"  {k}, for {'; '.join(dict.fromkeys(ms))}: paper: {p}; code: {c}")
    return "\n".join(lines)


def evidence_text(items: list[dict], side: str) -> str:
    if not items:
        return "  (the paper does not state it)" if side == "paper" else "  (none)"
    if side == "paper":
        return "\n".join(f"  - [{e['doc']} p.{e['page']}] \"{' '.join(str(e['quote']).split())}\"" for e in items)
    return "\n".join(f"  - {e['file']}:{e['lines']}: {' '.join(str(e['code']).split())[:300]}" for e in items)


def commands_text(links: dict, table: str) -> str:
    t = next(x for x in links["tables"] if x["target"] == table)
    seen = []
    for s in t.get("data_steps") or []:
        seen.append(" ".join(s["argv"]))
    for c in t["cells"]:
        for s in c.get("steps") or []:
            if s["name"] == "train" or (s["name"] not in ("eval",) and c["status"] == "linked"):
                line = " ".join(s["argv"])
                if line not in seen:
                    seen.append(line)
    return "\n".join(f"    {x}" for x in seen)


def writer_prompt(cfg: AuditConfig, f: Finding, table: dict, links: dict, previous: str = "") -> str:
    e = S.experiment_of(table)
    return Template((LLM_DIR / "prompts" / "branch_writer.md").read_text()).substitute(
        title=cfg.paper.title, table=e["table"], caption=e["caption"], commands=commands_text(links, f.table),
        setting=setting_text(f), kind=KIND_TEXT.get(f.kind, f"Kind: {f.kind}."),
        paper_evidence=evidence_text(f.paper_evidence, "paper"), code_evidence=evidence_text(f.code_evidence, "code"),
        previous=previous)


def previous_text(label: str, attempts: list[dict]) -> str:
    lines = ["", f"Your earlier answers for the reading \"{label}\" were rejected by the audit's checks:"]
    for a in attempts:
        lines.append(f"- {a['reason']}")
        if a.get("patch_text"):
            lines.append("  the patch was:")
            lines += [f"    {l}" for l in a["patch_text"].splitlines()[:80]]
    lines.append("Write this one reading again (exactly one reading in `readings`), fixing what was rejected.")
    return "\n".join(lines) + "\n"


def code_value_text(f: Finding) -> str:
    vals = []
    for e in f.entries:
        v = e.get("code")
        if v is not None and _val(v) not in vals:
            vals.append(_val(v))
    return " / ".join(vals)[:120]


def commit_message(f: Finding, paper_value: str) -> str:
    keys = "+".join(f.keys)
    return f"HYPOTHESIS({f.id}): {keys}: {' '.join(paper_value.split())[:120]} instead of {code_value_text(f)}"


# ---- the loop -------------------------------------------------------------------------------------------------------

@dataclass
class Ctx:
    paths: Paths
    cfg: AuditConfig
    llm: LLM
    repo: Path
    base_ref: str
    base: str                  # baseline sha
    out_dir: Path              # audits/<id>/branches/
    wt: Path                   # scratch worktree
    echo: Callable[[str], None]
    tables: dict
    links: dict
    allowed: Optional[set]
    data_scripts: set
    baselines: dict = field(default_factory=dict)   # table -> checked baseline answer

    def rel(self, p: Path) -> str:
        return Path(p).relative_to(self.paths.audit_dir(self.cfg.id)).as_posix()


def _call(ctx: Ctx, req: Request, save: Path) -> dict:
    save.parent.mkdir(parents=True, exist_ok=True)
    save.with_suffix(".prompt.md").write_text(req.prompt)
    resp = ctx.llm.call(req)
    out = resp.output if isinstance(resp.output, dict) else {}
    save.with_suffix(".answer.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    meta = resp.record["response"]
    return {"output": out, "call": {"agent": req.agent, "key": resp.key, "cache": resp.cache, "backend": resp.backend,
                                    "total_cost_usd": meta.get("total_cost_usd"), "num_turns": meta.get("num_turns"),
                                    "prompt": ctx.rel(save.with_suffix(".prompt.md")),
                                    "answer": ctx.rel(save.with_suffix(".answer.json"))}}


def extract(ctx: Ctx, table: str, ref_sha: str, save: Path) -> dict:
    """The code extractor (Phase 5 prompt, replicate SELFCHECK_REPLICATE) on a snapshot of `ref_sha`, checked."""
    snap = snapshot(ctx.repo, ref_sha, ctx.paths.workspace / "snapshots" / ctx.cfg.id)
    req = S.code_request(ctx.cfg, ctx.tables[table], ctx.repo, ref_sha, snap, SELFCHECK_REPLICATE)
    r = _call(ctx, req, save)
    checked = S.check_answer("code", r["output"], snap=snap)
    return {"settings": checked["settings"], "evidence": checked["evidence"], "call": r["call"],
            "tree": tree_id(ctx.repo, ref_sha)}


def baseline_answer(ctx: Ctx, table: str) -> dict:
    if table not in ctx.baselines:
        ctx.echo(f"  self-check baseline: code extractor on {ctx.base_ref} ({table}), replicate {SELFCHECK_REPLICATE}")
        ctx.baselines[table] = extract(ctx, table, ctx.base, ctx.out_dir / "baseline" / S.slug(table) / "code_run1")
    return ctx.baselines[table]


def check_patch(ctx: Ctx, f: Finding, diff: str) -> list[str]:
    problems = []
    comments = added_comments(diff, _new_file_text(ctx.repo, ctx.wt, ctx.base, diff))
    if comments:
        problems.append(f"added lines carry comments ({', '.join(comments[:5])}); add no comments")
    if ctx.allowed is not None:
        allowed = ctx.allowed | {e["file"] for e in f.code_evidence}
        outside = sorted({x.path for x in parse_unified_diff(diff)} - allowed)
        if outside:
            problems.append(f"the patch changes files the experiment's commands do not run: {', '.join(outside)}")
    return problems


def write_reading(ctx: Ctx, f: Finding, name: str, reading: dict, attempt: int, fdir: Path) -> dict:
    """One attempt at one reading: diff, code checks, commit, self-check. Returns the attempt record."""
    rec = {"attempt": attempt, "label": reading.get("label"), "paper_value": reading.get("paper_value"),
           "rationale": reading.get("rationale"), "branch": name, "commit": None, "pass": False}
    diff, errors = render(ctx.repo, ctx.wt, ctx.base, reading.get("edits") or [])
    if errors:
        rec["reason"] = "the edits do not apply: " + "; ".join(errors)
        return rec
    stem = f"{name.split('/')[-1]}_attempt{attempt}"
    (fdir / f"{stem}.patch").write_text(diff)
    rec["patch"] = ctx.rel(fdir / f"{stem}.patch")
    rec["patch_text"] = diff
    problems = check_patch(ctx, f, diff)
    if problems:
        rec["reason"] = "; ".join(problems)
        return rec
    msg = commit_message(f, reading.get("paper_value") or reading.get("label") or "")
    sha = commit_patch(ctx.wt, ctx.base, diff, msg)
    _git(ctx.repo, "branch", "-f", name, sha)
    rec.update(commit=sha, message=msg, tree=tree_id(ctx.repo, sha))
    base = baseline_answer(ctx, f.table)
    br = extract(ctx, f.table, sha, fdir / f"{stem}_code_run1")
    rec["selfcheck_call"] = br["call"]
    verdict = sc.judge(diff, base["settings"], br["settings"], f.wanted)
    touched_data = sorted({x.path for x in parse_unified_diff(diff)} & ctx.data_scripts)
    if touched_data:
        from el01.branch.datacheck import data_step_check
        # reported, not gating: a branch on a data setting is meant to change data files; which of them the setting
        # should change is not something code can know (the harness check, which must change none, gates)
        verdict["data_step"] = data_step_check(ctx, f.table, ctx.base, sha, f"{f.id}-{attempt}")
    (fdir / f"{stem}_selfcheck.json").write_text(json.dumps(verdict, indent=1, default=str) + "\n")
    rec["selfcheck"] = ctx.rel(fdir / f"{stem}_selfcheck.json")
    rec["pass"] = verdict["pass"]
    rec["reason"] = verdict["reason"]
    rec["attributed"] = [{k: a[k] for k in ("key", "use", "via")} for a in verdict["attributed"]]
    rec["disagreement"] = [a["key"] + (f" ({a['use']})" if a["use"] else "") for a in verdict["disagreement"]]
    return rec


def write_finding(ctx: Ctx, f: Finding) -> dict:
    fdir = ctx.out_dir / f.id
    fdir.mkdir(parents=True, exist_ok=True)
    table = ctx.tables[f.table]
    req = lambda prompt: Request(agent=AGENT, prompt=prompt, schema=SCHEMA, model=ctx.cfg.llm.model,
                                 inputs={"repo_tree": tree_id(ctx.repo, ctx.base)}, tools=AGENT_TOOLS,
                                 repo_copy=snapshot(ctx.repo, ctx.base, ctx.paths.workspace / "snapshots" / ctx.cfg.id),
                                 max_turns=MAX_TURNS)
    ctx.echo(f"{f.id} ({f.table}): {f.what}")
    first = _call(ctx, req(writer_prompt(ctx.cfg, f, table, ctx.links)), fdir / "call_1")
    calls = [first["call"]]
    readings = (first["output"].get("readings") or [])[:3]
    out = {"finding": f.id, "table": f.table, "what": f.what, "kind": f.kind, "keys": f.keys,
           "setting_ids": f.setting_ids, "pairing": f.pairing, "also_in": f.also_in, "methods": f.methods(),
           "readings_proposed": [r.get("label") for r in readings], "readings": [], "calls": calls}
    if not readings:
        out["readings"].append({"label": None, "status": "branch not written", "reason": "the agent gave no reading"})
        return out
    n_call = 1
    for k, reading in enumerate(readings, 1):
        name = f"el01/h-{f.id}" if len(readings) == 1 else f"el01/h-{f.id}.{k}"
        attempts = []
        cur = reading
        for attempt in range(1, RETRIES + 2):
            a = write_reading(ctx, f, name, cur, attempt, fdir)
            ctx.echo(f"  {name} [{a.get('label')}] attempt {attempt}: {'pass' if a['pass'] else 'REJECTED'}: "
                     f"{a['reason']}" + (f" (extractor disagreement, not counted: {', '.join(a['disagreement'])})"
                                         if a.get("disagreement") else ""))
            attempts.append(a)
            if a["pass"] or attempt > RETRIES:
                break
            n_call += 1
            prompt = writer_prompt(ctx.cfg, f, table, ctx.links, previous_text(reading.get("label") or "", attempts))
            r = _call(ctx, req(prompt), fdir / f"call_{n_call}")
            calls.append(r["call"])
            cur = (r["output"].get("readings") or [{}])[0]
            cur = {**cur, "label": cur.get("label") or reading.get("label")}
        final = attempts[-1]
        if not final["pass"]:
            _git(ctx.repo, "branch", "-D", name, check=False)
        for a in attempts:
            a.pop("patch_text", None)
        out["readings"].append({"label": reading.get("label"), "branch": name if final["pass"] else None,
                                "status": "written" if final["pass"] else "branch not written",
                                "commit": final["commit"] if final["pass"] else None,
                                "tree": final.get("tree") if final["pass"] else None,
                                "message": final.get("message") if final["pass"] else None,
                                "paper_value": final.get("paper_value"), "attempts": attempts})
    return out


def _clean(ctx: Ctx, findings: list[str]) -> None:
    for b in _git(ctx.repo, "for-each-ref", "--format=%(refname:short)", "refs/heads/el01/").stdout.split():
        if any(b == f"el01/h-{F}" or b.startswith(f"el01/h-{F}.") for F in findings):
            _git(ctx.repo, "branch", "-D", b)
    if ctx.out_dir.exists():
        shutil.rmtree(ctx.out_dir)


def run_branches(paths: Paths, cfg: AuditConfig, llm: LLM, restart: bool = False, only: Optional[list[str]] = None,
                 echo: Callable[[str], None] = print) -> dict:
    if cfg.ablation is None:
        raise BranchError(f"audits/{cfg.id}/audit.yaml has no `ablation:` block (baseline branch)")
    audit_dir = paths.audit_dir(cfg.id)
    repo = ensure_clone(cfg.repo.url, paths.repos / Path(cfg.repo.url.rstrip("/")).name.removesuffix(".git"))
    base = resolve(repo, cfg.ablation.baseline)
    findings = load_findings(paths, cfg, skip=tuple(cfg.ablation.baseline_findings))
    if only:
        findings = [f for f in findings if f.id in only]
    claims = load_claims(paths, cfg.id)
    links = json.loads((audit_dir / "links.json").read_text())
    data_scripts = {s["argv"][1] for t in links["tables"] for s in t.get("data_steps") or [] if len(s["argv"]) > 1}
    wt = paths.worktrees / cfg.id / "branch-git"
    ctx = Ctx(paths, cfg, llm, repo, cfg.ablation.baseline, base, audit_dir / "branches", wt, echo,
              {t["target"]: t for t in claims["tables"]}, links,
              run_path(scratch(repo, wt, base), cfg.env.entry_points), data_scripts)
    existing = audit_dir / "branches.json"
    if existing.exists() or any(_git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/el01/h-{f.id}",
                                     check=False).returncode == 0 for f in findings):
        if not restart:
            raise BranchError("branches from an earlier run exist (audits/<id>/branches.json or el01/h-F* branches); "
                              "pass --restart to delete them and write them again")
        _clean(ctx, [f.id for f in load_findings(paths, cfg, skip=tuple(cfg.ablation.baseline_findings))])
    ctx.out_dir.mkdir(parents=True, exist_ok=True)
    rec = {"audit": cfg.id, "baseline": {"ref": cfg.ablation.baseline, "commit": base, "tree": tree_id(repo, base)},
           "baseline_findings": cfg.ablation.baseline_findings, "agent": AGENT, "model": cfg.llm.model,
           "llm": {"backend": llm.mode, "cli_version": llm.cli_version}, "retries_per_reading": RETRIES,
           "selfcheck": {"extractor": S.AGENTS["code"], "replicate": SELFCHECK_REPLICATE,
                         "rule": "exactly one changed setting, the finding's: diff_v2 (both directions) + canon, "
                                 "counted only where either run's evidence cites a patched line"},
           "findings": []}
    for f in findings:
        rec["findings"].append(write_finding(ctx, f))
        rec["baseline_selfcheck"] = {t: {"call": b["call"], "evidence": b["evidence"], "tree": b["tree"]}
                                     for t, b in ctx.baselines.items()}
        existing.write_text(json.dumps(rec, indent=1, ensure_ascii=False, default=str) + "\n")
    calls = [c for f in rec["findings"] for c in f["calls"]] + \
            [c.get("selfcheck_call") for f in rec["findings"] for r in f["readings"] for c in r.get("attempts", [])
             if c.get("selfcheck_call")] + [b["call"] for b in ctx.baselines.values()]
    rec["counts"] = {"agent_calls": len(calls), "cache_hits": sum(c["cache"] == "hit" for c in calls),
                     "cache_misses": sum(c["cache"] == "miss" for c in calls),
                     "cost_usd_recorded": round(sum(c.get("total_cost_usd") or 0 for c in calls), 4),
                     "written": sum(r["status"] == "written" for f in rec["findings"] for r in f["readings"]),
                     "not_written": sum(r["status"] != "written" for f in rec["findings"] for r in f["readings"])}
    existing.write_text(json.dumps(rec, indent=1, ensure_ascii=False, default=str) + "\n")
    return rec
