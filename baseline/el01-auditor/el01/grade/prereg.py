"""Pre-registration of a graded run set (rule 5).

Before a graded run set starts, `write` records in `audits/<id>/prereg/<run_set>.{json,txt}` (tracked in git) and in
the run directory's `PREREGISTERED.txt`:
  - the sha256 of every rule, grader and parser file (HASHED);
  - the run plan: the claims (table, methods) x seeds x arms (branch -> commit and git tree), the effect family;
  - the practical floor per metric (audit.yaml);
  - the UTC time, and the runs completed at that time (there must be none).
The file must then be committed (`committed`) before any job starts.

`check` is what the grader calls first: it refuses a run set with no pre-registration, one that is not committed, one
whose hashed files changed, a run directory whose PREREGISTERED.txt differs, an arm whose code is not the planned
tree, a log for an (arm, method) the plan does not list, or a job that started before the pre-registration."""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

HASHED = ["el01/grade/legacy/verdicts_v2.py", "el01/grade/rules.py", "el01/grade/effects.py",
          "el01/grade/ablation.py", "el01/grade/parse.py", "el01/grade/prereg.py"]
PREREG_TXT = "PREREGISTERED.txt"


class PreregError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def sha256_file(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def hashes(root: Path, files: list[str] = HASHED) -> dict[str, str]:
    return {f: sha256_file(Path(root) / f) for f in files}


def prereg_files(audit_dir: Path, run_set: str) -> tuple[Path, Path]:
    d = Path(audit_dir) / "prereg"
    return d / f"{run_set}.json", d / f"{run_set}.txt"


def completed_runs(run_dir: Path) -> list[str]:
    run_dir = Path(run_dir)
    if not run_dir.exists():
        return []
    return sorted(p.relative_to(run_dir).as_posix() for p in run_dir.rglob("*.log"))


def render_txt(rec: dict) -> str:
    plan = rec["plan"]
    lines = [f"Pre-registration of run set `{rec['run_set']}` (audit {rec['audit']}): {plan.get('kind')}, "
             f"{plan.get('table')}.",
             "Written before any run of this set started.",
             f"written: {rec['written_utc']}",
             f"rule: {rec['rule']}",
             f"practical floor: {json.dumps(rec['floor'])}",
             f"seeds run: {plan['seeds']}; seeds graded: {plan['seeds_graded']}",
             f"baseline arm: {plan['baseline']}",
             "arms (ref, commit, git tree, methods):"]
    for name, a in plan["arms"].items():
        lines.append(f"  {name}: {a.get('ref')} {a['commit'][:12]} tree {a['tree'][:12]} "
                     f"[{a.get('label') or ''}] methods {', '.join(a['methods'])}")
    lines.append(f"effect family ({len(plan['family'])} effects, branch - baseline, paired by seed): "
                 + "; ".join(f"{a}/{m}" for a, m in plan["family"]))
    if plan.get("family_note"):
        lines.append(f"family: {plan['family_note']}")
    lines.append("sha256 of the rule, grader and parser files:")
    lines += [f"{h}  {f}" for f, h in rec["hashes"].items()]
    lines.append("completed runs at this time:")
    lines += [f"  {r}" for r in rec["completed_runs"]] or ["(none)"]
    return "\n".join(lines) + "\n"


def write(root: Path, audit_dir: Path, run_set: str, plan: dict, floor: dict, rule: str, run_dir: Path,
          audit_id: str) -> dict:
    """Write the pre-registration. Refuses if any run of the set already produced a log."""
    done = completed_runs(run_dir)
    if done:
        raise PreregError(f"run set {run_set}: {len(done)} log(s) already exist in {run_dir} (e.g. {done[0]}); "
                          f"a pre-registration must come before any run")
    rec = {"run_set": run_set, "audit": audit_id, "written_utc": utc_now(), "rule": rule, "floor": floor,
           "hashes": hashes(root), "plan": plan, "completed_runs": done}
    jf, tf = prereg_files(audit_dir, run_set)
    jf.parent.mkdir(parents=True, exist_ok=True)
    jf.write_text(json.dumps(rec, indent=1) + "\n")
    txt = render_txt(rec)
    tf.write_text(txt)
    Path(run_dir).mkdir(parents=True, exist_ok=True)
    (Path(run_dir) / PREREG_TXT).write_text(txt)
    return rec


def committed(root: Path, path: Path) -> Optional[str]:
    """None if `path` is tracked in the repository at `root` and has no uncommitted change; else the reason."""
    root, path = Path(root), Path(path)
    rel = path.resolve().relative_to(root.resolve()).as_posix()
    p = subprocess.run(["git", "-C", str(root), "ls-files", "--error-unmatch", rel], capture_output=True, text=True)
    if p.returncode != 0:
        return f"{rel} is not committed"
    p = subprocess.run(["git", "-C", str(root), "diff", "--quiet", "HEAD", "--", rel], capture_output=True, text=True)
    if p.returncode != 0:
        return f"{rel} has uncommitted changes"
    return None


def load(audit_dir: Path, run_set: str) -> dict:
    jf, _ = prereg_files(audit_dir, run_set)
    if not jf.exists():
        raise PreregError(f"run set {run_set} has no pre-registration ({jf}): the grader refuses it")
    return json.loads(jf.read_text())


def check(root: Path, audit_dir: Path, run_set: str, run_dir: Path, require_commit: bool = True) -> dict:
    """The rule-5 check. Returns the pre-registration record; raises PreregError listing every problem."""
    rec = load(audit_dir, run_set)
    jf, tf = prereg_files(audit_dir, run_set)
    problems = []
    if require_commit:
        for f in (jf, tf):
            why = committed(root, f)
            if why:
                problems.append(why)
    now = hashes(root, list(rec["hashes"]))
    for f, h in rec["hashes"].items():
        if now[f] != h:
            problems.append(f"{f} changed since the pre-registration (sha256 {h[:12]} then, {now[f][:12]} now)")
    run_dir = Path(run_dir)
    copy = run_dir / PREREG_TXT
    if not copy.exists():
        problems.append(f"{copy} is missing")
    elif copy.read_text() != tf.read_text():
        problems.append(f"{copy} differs from {tf.name}")
    plan = rec["plan"]
    for name, a in plan["arms"].items():
        d = run_dir / name
        if not d.exists():
            continue
        tree = (d / "tree.txt").read_text().strip() if (d / "tree.txt").exists() else None
        if tree != a["tree"]:
            problems.append(f"arm {name}: code tree {tree} is not the planned {a['tree']}")
        for log in sorted(d.glob("train_*.log")):
            if log.stem[6:] not in a["methods"]:
                problems.append(f"arm {name}: {log.name} is not in the plan")
    for st in sorted((run_dir / ".jobs").glob("*.json")) if (run_dir / ".jobs").exists() else []:
        s = json.loads(st.read_text())
        if s.get("start_utc") and s["start_utc"] < rec["written_utc"]:
            problems.append(f"job {s['name']} started {s['start_utc']}, before the pre-registration "
                            f"({rec['written_utc']})")
    if problems:
        raise PreregError(f"run set {run_set}: " + "; ".join(problems))
    return rec
