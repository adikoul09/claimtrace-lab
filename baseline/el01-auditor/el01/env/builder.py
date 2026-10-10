"""Environment builder: the execution ladder (spec section 4), cheapest rung first.

  (a) results shipped in the repo   listed; matching them to claims needs claim cards (Phase 4), so not used yet
  (b) the repo's Dockerfile         detected and reported; not built in the prototype
  (c) a date-pinned uv environment  built here, in workspace/envs/<audit id>/

Rung (c):
  Python   audit.yaml override; else, if an eagerly imported framework is pinned with ==, the newest CPython that
           release has wheels for; else the newest CPython minor released at least 6 months before the commit date.
  Packages the entry points' imports (el01/env/imports.py): eager and lazy ones, with the version spec from the
           requirements file where it lists them; every addition and every listed-but-unimported entry is logged.
  Resolve  `uv pip compile` with UV_EXCLUDE_NEWER = commit time + 24 h. Eager packages must resolve. A lazy package
           is kept only if it resolves without changing any version in the eager lock; otherwise it is dropped,
           with uv's reason.
  Wheels   a locked version with no wheel for this interpreter and platform is bumped to the earliest later release
           that has one (`--exclude-newer-package`), logged. Installs are wheels only: nothing is built.
Outputs: workspace/envs/<id>/{requirements.in, lock.txt, freeze.txt, env.json} and audits/<id>/env.json."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import urllib.request
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

from el01.config import AuditConfig, Paths
from el01.env.imports import ScanResult, dist_for_module, module_for_dist, normalize, scan
from el01.ingest.repo import commit_date, ensure_clone, git, resolve, tracked_files
from el01.run.worktrees import ensure_worktree

BUILDER_VERSION = 1  # part of the plan hash: bump when the build logic changes

# x.y.0 release dates (python.org)
CPYTHON_RELEASES = {"3.6": date(2016, 12, 23), "3.7": date(2018, 6, 27), "3.8": date(2019, 10, 14),
                    "3.9": date(2020, 10, 5), "3.10": date(2021, 10, 4), "3.11": date(2022, 10, 24),
                    "3.12": date(2023, 10, 2), "3.13": date(2024, 10, 7), "3.14": date(2025, 10, 7)}
FRAMEWORKS = {"torch", "tensorflow", "tensorflow-gpu", "tensorflow-cpu", "jax", "jaxlib", "mxnet", "paddlepaddle"}

RESULT_DIRS = {"results", "result", "outputs", "output", "logs", "log", "checkpoints", "ckpt", "saved_models",
               "pretrained", "runs"}
RESULT_EXTS = {".csv", ".tsv", ".npy", ".npz", ".pkl", ".pickle", ".pt", ".pth", ".ckpt", ".h5", ".hdf5", ".log"}
DOCKER_RE = re.compile(r"(^|/)(Dockerfile[^/]*|[^/]+\.dockerfile|docker-compose[^/]*\.ya?ml|\.devcontainer/[^/]+)$", re.I)
ENV_SPEC_RE = re.compile(r"(^|/)(environment[^/]*\.ya?ml|setup\.py|setup\.cfg|pyproject\.toml|Pipfile|"
                         r"requirements[^/]*\.txt)$")
WHEEL_RE = re.compile(r"^(?P<name>.+?)-(?P<ver>[^-]+)(-(?P<build>\d[^-]*))?-(?P<py>[^-]+)-(?P<abi>[^-]+)-"
                      r"(?P<plat>[^-]+)\.whl$")
PRERELEASE_RE = re.compile(r"(a|b|rc|dev|alpha|beta)\d*", re.I)
LOCK_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;#]+)")


class EnvBuildError(RuntimeError):
    pass


# ---------------------------------------------------------------- Python version

def months_before(d: date, n: int) -> date:
    y, m = d.year, d.month - n
    while m <= 0:
        m, y = m + 12, y - 1
    return date(y, m, min(d.day, monthrange(y, m)[1]))


def python_by_date(day: date) -> tuple[str, str]:
    cutoff = months_before(day, 6)
    ok = [v for v, rel in CPYTHON_RELEASES.items() if rel <= cutoff]
    if not ok:
        raise EnvBuildError(f"no CPython in the table was released by {cutoff}")
    v = max(ok, key=lambda s: tuple(map(int, s.split("."))))
    return v, f"newest CPython minor released by {cutoff} (commit date {day} - 6 months): {v}.0 on {CPYTHON_RELEASES[v]}"


def max_python_from_filenames(filenames) -> Optional[str]:
    """Newest CPython a release has wheels for (from cpXY tags); None if a pure or abi3 wheel sets no upper bound."""
    best = None
    for f in filenames:
        m = WHEEL_RE.match(f)
        if not m:
            continue
        if "abi3" in m["abi"].split(".") or any(t.startswith("py") for t in m["py"].split(".")):
            return None
        for t in m["py"].split("."):
            mm = re.fullmatch(r"cp(\d)(\d+)", t)
            if mm:
                best = max(best or (0, 0), (int(mm[1]), int(mm[2])))
    return f"{best[0]}.{best[1]}" if best else None


# ---------------------------------------------------------------- wheel tags

@dataclass(frozen=True)
class Host:
    system: str                 # Darwin | Linux | Windows
    machine: str                # arm64 | x86_64 | aarch64 | AMD64 ...
    macos: tuple = (0, 0)

    @classmethod
    def current(cls) -> "Host":
        mac = platform.mac_ver()[0]
        return cls(platform.system(), platform.machine(),
                   tuple(int(x) for x in (mac.split(".") + ["0"])[:2]) if mac else (0, 0))


def _platform_ok(tag: str, h: Host) -> bool:
    if tag == "any":
        return True
    if h.system == "Darwin":
        m = re.fullmatch(r"macosx_(\d+)_(\d+)_(\w+)", tag)
        archs = {"arm64": {"arm64", "universal2"},
                 "x86_64": {"x86_64", "intel", "universal", "universal2", "fat64", "fat3"}}.get(h.machine, set())
        return bool(m) and m[3] in archs and (int(m[1]), int(m[2])) <= h.macos
    if h.system == "Linux":
        m = re.fullmatch(r"(manylinux1|manylinux2010|manylinux2014|manylinux_\d+_\d+)_(\w+)", tag)
        return bool(m) and m[2] == h.machine
    if h.system == "Windows":
        return tag == {"AMD64": "win_amd64", "ARM64": "win_arm64", "x86": "win32"}.get(h.machine)
    return False


def wheel_ok(filename: str, py: str, h: Host) -> bool:
    """Can this wheel install on CPython `py` (e.g. "3.9") on host `h`?"""
    m = WHEEL_RE.match(filename)
    if not m:
        return False
    maj, mnr = map(int, py.split(".")[:2])
    abis = m["abi"].split(".")
    py_ok = False
    for t in m["py"].split("."):
        if t in ("py3", f"py{maj}", f"py{maj}{mnr}"):
            py_ok = True
        mm = re.fullmatch(r"cp(\d)(\d+)", t)
        if mm and (int(mm[1]), int(mm[2])) == (maj, mnr):
            py_ok = True
        elif mm and "abi3" in abis and int(mm[1]) == maj and int(mm[2]) <= mnr:
            py_ok = True
    return py_ok and any(_platform_ok(p, h) for p in m["plat"].split("."))


# ---------------------------------------------------------------- PyPI metadata (fetch phase; cached on disk)

class PyPI:
    def __init__(self, cache: Path):
        self.cache = Path(cache)

    def _get(self, url: str, name: str) -> dict:
        p = self.cache / name
        if p.exists():
            return json.loads(p.read_text())
        req = urllib.request.Request(url, headers={"User-Agent": "el01-auditor (prototype)"})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read())
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data))
        return data

    def files(self, dist: str, version: str) -> list[dict]:
        return self._get(f"https://pypi.org/pypi/{normalize(dist)}/{version}/json",
                         f"{normalize(dist)}-{version}.json")["urls"]

    def releases(self, dist: str) -> dict[str, list[dict]]:
        return self._get(f"https://pypi.org/pypi/{normalize(dist)}/json", f"{normalize(dist)}.json")["releases"]

    def has_wheel(self, dist: str, version: str, py: str, h: Host) -> bool:
        return any(f["packagetype"] == "bdist_wheel" and wheel_ok(f["filename"], py, h) for f in self.files(dist, version))

    def next_wheel_release(self, dist: str, version: str, py: str, h: Host) -> Optional[tuple[str, str, str]]:
        """The earliest release after `version` with a usable wheel: (version, its upload date, cutoff for uv)."""
        rel = self.releases(dist)
        t0 = min((f["upload_time_iso_8601"] for f in rel.get(version, [])), default="")
        cands = []
        for v, fs in rel.items():
            fs = [f for f in fs if not f.get("yanked")]
            if not fs or PRERELEASE_RE.search(v):
                continue
            t = min(f["upload_time_iso_8601"] for f in fs)
            if t > t0 and any(f["packagetype"] == "bdist_wheel" and wheel_ok(f["filename"], py, h) for f in fs):
                last = max(datetime.fromisoformat(f["upload_time_iso_8601"].replace("Z", "+00:00")) for f in fs)
                cands.append((t, v, (last + timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")))
        if not cands:
            return None
        t, v, cutoff = min(cands)
        return v, t[:10], cutoff


# ---------------------------------------------------------------- requirements

@dataclass(frozen=True)
class Req:
    name: str      # normalised distribution name
    line: str      # the requirement as written (no comment)
    lineno: int

    @property
    def pinned(self) -> Optional[str]:
        m = re.fullmatch(r"[^=<>!~\s\[]+(\[[^\]]*\])?\s*==\s*([^\s,;]+)\s*(;.*)?", self.line)
        return m[2] if m else None


def parse_requirements(text: str) -> tuple[list[Req], list[str]]:
    reqs, unsupported = [], []
    for i, raw in enumerate(text.splitlines(), 1):
        line = raw.split(" #")[0].strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)", line)
        if line.startswith("-") or "://" in line or not m:
            unsupported.append(f"line {i}: {line}")
            continue
        reqs.append(Req(normalize(m[1]), line, i))
    return reqs, unsupported


def parse_lock(text: str) -> dict[str, str]:
    return {normalize(m[1]): m[2] for m in map(LOCK_RE.match, text.splitlines()) if m}


def compare_freeze(ours: dict[str, str], theirs: dict[str, str]) -> dict:
    return {"changed": [{"package": n, "ours": ours[n], "theirs": theirs[n]} for n in sorted(ours.keys() & theirs.keys())
                        if ours[n] != theirs[n]],
            "only_ours": [{"package": n, "version": ours[n]} for n in sorted(ours.keys() - theirs.keys())],
            "only_theirs": [{"package": n, "version": theirs[n]} for n in sorted(theirs.keys() - ours.keys())],
            "same": sum(1 for n in ours.keys() & theirs.keys() if ours[n] == theirs[n])}


# ---------------------------------------------------------------- ladder rungs (a) and (b)

def shipped_results(repo: Path, sha: str) -> list[dict]:
    out = []
    for f in tracked_files(repo, sha):
        parts, ext = f.split("/"), Path(f).suffix.lower()
        if any(p.lower() in RESULT_DIRS for p in parts[:-1]):
            out.append({"file": f, "why": "in a results-like folder"})
        elif ext in RESULT_EXTS:
            out.append({"file": f, "why": f"{ext} file"})
        elif ext == ".ipynb":
            try:
                nb = json.loads(git(repo, "show", f"{sha}:{f}"))
                n = sum(1 for c in nb.get("cells", []) if c.get("outputs"))
            except (ValueError, RuntimeError):
                n = 0
            if n:
                out.append({"file": f, "why": f"notebook with {n} cells of saved output"})
    return out


def docker_files(repo: Path, sha: str) -> list[str]:
    return [f for f in tracked_files(repo, sha) if DOCKER_RE.search(f)]


def env_spec_files(repo: Path, sha: str) -> list[str]:
    return [f for f in tracked_files(repo, sha) if ENV_SPEC_RE.search(f)]


# ---------------------------------------------------------------- uv

def venv_python(env_dir: Path) -> Path:
    return env_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


class Uv:
    def __init__(self, env_dir: Path, exclude_newer: str):
        self.exe = shutil.which("uv")
        if not self.exe:
            raise EnvBuildError("uv is not on PATH")
        self.env_dir, self.exclude_newer = env_dir, exclude_newer
        self.env = {k: v for k, v in os.environ.items()
                    if k not in ("VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT", "PYTHONPATH", "PYTHONHOME", "CONDA_PREFIX")}
        self.env.update(UV_EXCLUDE_NEWER=exclude_newer, NO_COLOR="1")

    def version(self) -> str:
        return self.run("--version").stdout.strip()

    def run(self, *args: str, excludes: Optional[dict] = None) -> subprocess.CompletedProcess:
        extra = [a for d, c in sorted((excludes or {}).items()) for a in ("--exclude-newer-package", f"{d}={c}")]
        cmd = [self.exe, *args] + (["--no-config", *extra] if args[0] != "--version" else [])
        return subprocess.run(cmd, cwd=self.env_dir.parent, env=self.env, capture_output=True, text=True)


def _uv_reason(stderr: str) -> str:
    lines = [l.strip() for l in stderr.splitlines() if l.strip() and not l.startswith(("Resolved", "Using"))]
    return " ".join(lines)[:700]


# ---------------------------------------------------------------- the build

@dataclass
class Entry:
    dist: str      # normalised distribution name
    line: str      # requirement line given to uv
    tier: str      # eager | lazy
    source: str    # where the entry comes from


def _plan_entries(sc: ScanResult, reqs: list[Req], extra: list[str]) -> tuple[list[Entry], dict]:
    by_module: dict[str, list[Req]] = {}
    for r in reqs:
        by_module.setdefault(module_for_dist(r.name), []).append(r)
    entries, log = [], {"added": [], "not_imported": [], "guarded": []}
    for mod in sorted(sc.third_party):
        tier = sc.tier(mod)
        first = min(sc.third_party[mod], key=lambda s: (("eager", "lazy", "guarded").index(s.tier), s.file, s.line))
        if tier == "guarded":
            log["guarded"].append({"module": mod, "site": str(first)})
            continue
        if mod in by_module:
            entries += [Entry(r.name, r.line, tier, f"requirements line {r.lineno}") for r in by_module[mod]]
        else:
            d = dist_for_module(mod)
            entries.append(Entry(d, d, tier, f"added: `{mod}` imported at {first}, not in the requirements file"))
            log["added"].append({"dist": d, "module": mod, "tier": tier, "site": str(first)})
    log["not_imported"] = [{"line": r.line, "lineno": r.lineno} for r in reqs if module_for_dist(r.name) not in sc.third_party]
    for x in extra:
        r = parse_requirements(x)[0][0]
        entries.append(Entry(r.name, r.line, "eager", "audit.yaml env.extra"))
        log["added"].append({"dist": r.name, "module": None, "tier": "eager", "site": "audit.yaml env.extra"})
    return entries, log


def _choose_python(cfg: AuditConfig, entries: list[Entry], cdate: datetime, pypi: PyPI) -> tuple[str, str]:
    if cfg.env.python:
        return cfg.env.python, "audit.yaml env.python override"
    pins = []
    for e in entries:
        v = Req(e.dist, e.line, 0).pinned
        if e.tier == "eager" and e.dist in FRAMEWORKS and v:
            top = max_python_from_filenames(f["filename"] for f in pypi.files(e.dist, v))
            if top:
                pins.append((top, f"{e.dist}=={v} (eagerly imported framework) has wheels up to CPython {top}"))
    if pins:
        top, why = min(pins, key=lambda p: tuple(map(int, p[0].split("."))))
        return top, why
    return python_by_date(cdate.date())


def build_env(paths: Paths, cfg: AuditConfig, rebuild: bool = False, echo: Callable[[str], None] = print) -> dict:
    repo = ensure_clone(cfg.repo.url, paths.repos / Path(cfg.repo.url.rstrip("/")).name.removesuffix(".git"))
    sha = resolve(repo, cfg.repo.commit)
    cdate = commit_date(repo, sha)
    wt, _ = ensure_worktree(repo, sha, paths.worktrees / cfg.id / "shipped")
    env_dir = paths.envs / cfg.id
    exclude_newer = (cdate + timedelta(days=1)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    pypi, host = PyPI(paths.envs / ".pypi"), Host.current()
    uv = Uv(env_dir, exclude_newer)
    env_dir.parent.mkdir(parents=True, exist_ok=True)

    ladder = {"a_shipped_results": {"candidates": shipped_results(repo, sha), "used": False,
                                    "note": "listed only: matching shipped results to claims needs claim cards (Phase 4)"},
              "b_dockerfile": {"found": docker_files(repo, sha), "built": False,
                               "note": "detected and reported only; the prototype does not build Docker images"},
              "other_env_specs": env_spec_files(repo, sha)}
    entry_points = cfg.env.entry_points or ([a for a in cfg.smoke.command if a.endswith(".py")][:1] if cfg.smoke else [])
    sc = scan(wt, entry_points)
    req_file = wt / cfg.env.requirements
    reqs, unsupported = parse_requirements(req_file.read_text()) if req_file.is_file() else ([], [])
    entries, log = _plan_entries(sc, reqs, cfg.env.extra)
    python, python_why = _choose_python(cfg, entries, cdate, pypi)

    plan = {"commit": sha, "python": python, "exclude_newer": exclude_newer, "uv": uv.version(),
            "entries": [(e.line, e.tier) for e in entries], "builder": BUILDER_VERSION, "host": [host.system, host.machine]}
    plan_hash = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
    old = env_dir / "env.json"
    if not rebuild and old.exists() and venv_python(env_dir).exists():
        prev = json.loads(old.read_text())
        if prev.get("plan_hash") == plan_hash and prev.get("status") == "built":
            echo(f"environment {env_dir} is up to date (plan {plan_hash[:12]}); --rebuild to rebuild")
            return prev | {"cached": True}

    report = {"audit": cfg.id, "repo": cfg.repo.url, "commit": sha, "commit_date": cdate.isoformat(),
              "exclude_newer": exclude_newer, "uv": plan["uv"], "host": plan["host"], "plan_hash": plan_hash,
              "ladder": ladder, "python": {"version": python, "rule": python_why},
              "requirements": {"file": cfg.env.requirements if req_file.is_file() else None,
                               "entries": [r.line for r in reqs], "unsupported": unsupported},
              "imports": sc.to_json(), "packages": {**log, "eager": [], "lazy_kept": [], "lazy_dropped": [],
                                                     "wheel_bumps": []},
              "status": "building"}

    def fail(msg: str):
        report.update(status="failed", error=msg, built_utc=_utc())
        _write_report(paths, cfg.id, env_dir, report)
        raise EnvBuildError(msg)

    echo(f"rung (a) shipped results: {len(ladder['a_shipped_results']['candidates'])} candidate file(s), not used")
    echo(f"rung (b) Dockerfile: {ladder['b_dockerfile']['found'] or 'none found'}")
    echo(f"rung (c) uv env: Python {python} ({python_why}); UV_EXCLUDE_NEWER={exclude_newer}")
    p = uv.run("venv", str(env_dir), "--python", python, "--managed-python", "--clear")
    if p.returncode != 0:
        fail(f"uv venv --python {python}: {_uv_reason(p.stderr)}")
    py = venv_python(env_dir)
    report["python"]["installed"] = subprocess.run([str(py), "-c", "import platform;print(platform.python_version())"],
                                                   capture_output=True, text=True).stdout.strip()

    excludes: dict[str, str] = {}
    bumps: list[dict] = []
    req_in = env_dir / "requirements.in"

    def compile_(es: list[Entry]) -> tuple[bool, dict, str, str]:
        """Resolve, then bump locked versions that have no usable wheel, until none is left."""
        while True:
            req_in.write_text("".join(f"{e.line}\n" for e in es))
            p = uv.run("pip", "compile", str(req_in), "--python", str(py), "--no-header", excludes=excludes)
            if p.returncode != 0:
                return False, {}, "", _uv_reason(p.stderr)
            versions = parse_lock(p.stdout)
            gaps = [(d, v) for d, v in sorted(versions.items()) if not pypi.has_wheel(d, v, report["python"]["installed"], host)]
            if not gaps:
                return True, versions, p.stdout, ""
            for d, v in gaps:
                nxt = None if d in excludes else pypi.next_wheel_release(d, v, report["python"]["installed"], host)
                if nxt is None:
                    return False, {}, "", f"{d}=={v} has no wheel for CPython {report['python']['installed']} on " \
                                          f"{host.system} {host.machine}, and no later release has one either"
                excludes[d] = nxt[2]
                bumps.append({"dist": d, "from": v, "to": nxt[0], "to_released": nxt[1], "exclude_newer_package": nxt[2],
                              "why": f"{d}=={v} has no wheel for CPython {report['python']['installed']} on "
                                     f"{host.system} {host.machine}; {nxt[0]} is the earliest release with one"})
                echo(f"  wheel gap: {d} {v} -> {nxt[0]} (released {nxt[1]})")

    eager = [e for e in entries if e.tier == "eager"]
    ok, eager_lock, lock_text, why = compile_(eager)
    if not ok:
        fail(f"eager packages do not resolve: {why}")
    echo(f"  eager: {', '.join(e.line for e in eager)} -> {len(eager_lock)} locked")
    kept, dropped = [], []
    for e in sorted((e for e in entries if e.tier == "lazy"), key=lambda e: e.dist):
        saved = (dict(excludes), list(bumps))
        ok, lock, text, why = compile_(eager + kept + [e])
        moved = [f"{d} {v} -> {lock[d]}" for d, v in eager_lock.items() if ok and lock.get(d) != v]
        if ok and not moved:
            kept.append(e)
            lock_text = text
            echo(f"  lazy kept: {e.line}")
        else:
            excludes.clear(); excludes.update(saved[0]); bumps[:] = saved[1]
            reason = why if not ok else f"would change the eager lock: {'; '.join(moved)}"
            dropped.append({"line": e.line, "source": e.source, "reason": reason})
            echo(f"  lazy dropped: {e.line}: {reason[:160]}")
    final = eager + kept
    req_in.write_text("".join(f"{e.line}  # {e.tier}; {e.source}\n" for e in final))
    (env_dir / "lock.txt").write_text(lock_text)
    report["packages"].update(eager=[{"line": e.line, "source": e.source} for e in eager],
                              lazy_kept=[{"line": e.line, "source": e.source} for e in kept],
                              lazy_dropped=dropped, wheel_bumps=bumps)

    p = uv.run("pip", "sync", str(env_dir / "lock.txt"), "--python", str(py), "--only-binary", ":all:", excludes=excludes)
    if p.returncode != 0:
        fail(f"uv pip sync: {_uv_reason(p.stderr)}")
    freeze = uv.run("pip", "freeze", "--python", str(py)).stdout
    (env_dir / "freeze.txt").write_text(freeze)
    report["freeze"] = freeze.splitlines()
    report["import_check"] = _import_check(py, sc)
    report.update(status="built", built_utc=_utc())
    _write_report(paths, cfg.id, env_dir, report)
    return report


IMPORT_CHECK = r"""
import importlib, importlib.util, json, sys
out = {}
for mod, tier in json.loads(sys.argv[1]):
    try:
        if tier == "eager":
            importlib.import_module(mod); out[mod] = "imported"
        else:
            out[mod] = "found" if importlib.util.find_spec(mod) else "missing"
    except Exception as e:
        out[mod] = f"error: {type(e).__name__}: {e}"[:300]
print(json.dumps(out))
"""


def _import_check(py: Path, sc: ScanResult) -> dict:
    """Eager modules are imported; lazy and guarded ones are only located (importing them may be slow or noisy)."""
    mods = [(m, sc.tier(m)) for m in sorted(sc.third_party)]
    env = {k: v for k, v in os.environ.items() if k not in ("VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME")}
    env.update(OMP_NUM_THREADS="1")
    p = subprocess.run([str(py), "-c", IMPORT_CHECK, json.dumps(mods)], capture_output=True, text=True, env=env,
                       cwd=py.parent)
    if p.returncode != 0:
        return {"error": p.stderr.strip()[-500:]}
    return json.loads(p.stdout.strip().splitlines()[-1])


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_report(paths: Paths, audit_id: str, env_dir: Path, report: dict) -> None:
    text = json.dumps(report, indent=1)
    env_dir.mkdir(parents=True, exist_ok=True)
    (env_dir / "env.json").write_text(text)
    (paths.audit_dir(audit_id) / "env.json").write_text(text)
