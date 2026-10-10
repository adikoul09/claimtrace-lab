"""The fixed tool set (SPEC §2.2). Agents can call only these, and only the ones their agents row grants.

File tools act inside the run's working directory (a folder under runs/); any path that resolves outside it is
refused. `run` reuses the executor's sandbox: allowlisted environment (no keys), own process group, hard timeout.
A ToolError's message goes back to the model as the observation, so it can correct itself."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from lab.db import ROOT, emit

FIXED_TOOLS = ("fetch_paper", "fetch_repo", "read_file", "write_file", "list_dir", "make_env", "run",
               "query_memory", "emit")

# One line per tool for the agent's system prompt.
TOOL_DOCS = {
    "fetch_paper": 'fetch_paper {"arxiv_id": str}: download the arXiv PDF, save paper.txt (text with "--- page N ---" markers) in the run dir',
    "fetch_repo": 'fetch_repo {"url": str, "commit": str?}: clone a repository into the run dir',
    "read_file": 'read_file {"path": str}: read a text file in the run dir (long files are cut at 20000 chars)',
    "write_file": 'write_file {"path": str, "content": str}: write a text file in the run dir',
    "list_dir": 'list_dir {"path": str}: list a folder in the run dir ("." for the top)',
    "make_env": 'make_env {"requirements": str}: create a venv in the run dir from pinned requirements',
    "run": 'run {"cmd": str, "timeout_s": int}: run a command in the run dir, no network, no secrets; returns exit code and output tail',
    "query_memory": 'query_memory {"tags": [str]}: lessons from earlier projects with any of these tags',
    "emit": 'emit {"event": str, "reason": str}: record a note on the live event stream',
}

# Argument schemas, so a structured-output model can fill them (it leaves undeclared properties out).
_S, _I = {"type": "string"}, {"type": "integer"}
TOOL_PARAMS = {
    "fetch_paper": {"arxiv_id": _S},
    "fetch_repo": {"url": _S, "commit": _S},
    "read_file": {"path": _S},
    "write_file": {"path": _S, "content": _S},
    "list_dir": {"path": _S},
    "make_env": {"requirements": _S},
    "run": {"cmd": _S, "timeout_s": _I},
    "query_memory": {"tags": {"type": "array", "items": _S}},
    "emit": {"event": _S, "reason": _S},
}

RUNS = ROOT / "runs"
READ_LIMIT = 20_000
RUN_TAIL = 4_000
RUN_MAX_TIMEOUT_S = 1200


class ToolError(Exception):
    pass


class ToolBox:
    def __init__(self, workdir: Path, allowed, runs_root: Path = RUNS, db=None, project_id=None, agent_id=None,
                 task_id=None):
        bad = sorted(set(allowed) - set(FIXED_TOOLS))
        if bad:
            raise ToolError(f"{bad} are not in the fixed tool set {list(FIXED_TOOLS)}")
        root, wd = Path(runs_root).resolve(), Path(workdir).resolve()
        if wd == root or not wd.is_relative_to(root):
            raise ToolError(f"the run dir must be a folder inside {root}, got {wd}")
        wd.mkdir(parents=True, exist_ok=True)
        self.workdir, self.allowed, self.runs_root = wd, list(allowed), root
        self.db, self.project_id, self.agent_id, self.task_id = db, project_id, agent_id, task_id

    def call(self, name: str, args: dict) -> str:
        if name not in self.allowed:
            raise ToolError(f"tool {name!r} is not allowed for this agent; allowed: {self.allowed}")
        try:
            return getattr(self, f"_{name}")(**(args or {}))
        except TypeError as e:
            raise ToolError(f"bad arguments for {name}: {e}") from None

    def _path(self, path: str) -> Path:
        p = Path(path)
        target = (p if p.is_absolute() else self.workdir / p).resolve()
        if not target.is_relative_to(self.workdir):
            raise ToolError(f"{path!r} is outside the run dir")
        return target

    # -- file tools ---------------------------------------------------------------------------------------------------
    def _read_file(self, path: str) -> str:
        p = self._path(path)
        if not p.is_file():
            raise ToolError(f"no such file: {path}")
        text = p.read_text(encoding="utf-8", errors="replace")
        return text if len(text) <= READ_LIMIT else text[:READ_LIMIT] + f"\n[cut at {READ_LIMIT} of {len(text)} chars]"

    def _write_file(self, path: str, content: str) -> str:
        p = self._path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"wrote {p.relative_to(self.workdir).as_posix()} ({len(content)} chars)"

    def _list_dir(self, path: str = ".") -> str:
        p = self._path(path)
        if not p.is_dir():
            raise ToolError(f"no such folder: {path}")
        return "\n".join(f"{c.name}/" if c.is_dir() else c.name for c in sorted(p.iterdir())) or "(empty)"

    # -- run ----------------------------------------------------------------------------------------------------------
    def _run(self, cmd, timeout_s: int = 120) -> str:
        from lab.executor.worker import child_env, kill_tree, resolve_argv, start

        timeout_s = min(float(timeout_s), RUN_MAX_TIMEOUT_S)
        argv = resolve_argv(cmd, sys.executable)
        try:
            p = start(argv, self.workdir, child_env(sys.executable))
        except OSError as e:
            raise ToolError(f"could not start {argv[0]!r}: {e}") from None
        timer = threading.Timer(timeout_s, kill_tree, args=(p,))
        timer.start()
        try:
            out = p.stdout.read()
            code = p.wait()
        finally:
            timer.cancel()
        return f"exit code {code}\n{out[-RUN_TAIL:]}"

    # -- memory and events --------------------------------------------------------------------------------------------
    def _query_memory(self, tags) -> str:
        tags = [tags] if isinstance(tags, str) else list(tags)
        rows = self.db.table("lessons").select("id,kind,text,tags,times_applied").overlaps("tags", tags) \
            .order("times_applied", desc=True).limit(10).execute().data
        return json.dumps(rows, ensure_ascii=False) if rows else "no lessons with these tags"

    def _emit(self, event: str, reason: str) -> str:
        # Fixed type: an agent can add notes to the stream but cannot forge system events such as task_finished.
        emit(self.db, "agent_note", event, reason, project_id=self.project_id, agent_id=self.agent_id,
             task_id=self.task_id)
        return "recorded"

    # -- paper, repo, env ---------------------------------------------------------------------------------------------
    def _fetch_paper(self, arxiv_id: str) -> str:
        try:
            from lab.agents.paper import fetch_paper
        except ImportError:
            raise ToolError("fetch_paper is not available yet") from None
        info = fetch_paper(arxiv_id, self.workdir, db=self.db, project_id=self.project_id)
        return (f"saved paper.txt: {info['title']!r}, {info['pages']} pages, {info['chars']} chars; "
                f"read it with read_file")

    def _fetch_repo(self, url: str, commit: str | None = None) -> str:
        check_repo_url(url)
        dest = self._path("repo")
        if dest.exists():
            raise ToolError("repo/ already exists in the run dir; it is cloned once per run")
        info = clone(url, dest, commit=commit or None)
        (self.workdir / "repo.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
        return f"cloned {url} at {info['commit']} into repo/ (recorded in repo.json)"

    def _make_env(self, requirements: str) -> str:
        check_requirements(requirements)  # before writing anything, so the agent sees the problem first
        (self.workdir / "requirements.txt").write_text(requirements, encoding="utf-8")
        env = make_env(requirements, Path(self.runs_root) / "envs")
        (self.workdir / "env.json").write_text(json.dumps(env.as_dict(), indent=2), encoding="utf-8")
        how = "reused the cached env" if env.cached else f"built in {env.seconds:.0f} s"
        return (f"env ready: {env.key} ({how}); python: {env.python}\n"
                f"run scripts with python as usual; the run step uses this env.\n{env.log[-1500:]}")


# -- environments (SPEC §2.2 make_env; ported from baseline el01 env builder: pinned, isolated, no robustdg defaults) --
ENV_TIMEOUT_S = 1800
INDEX_OPTIONS = ("--index-url", "--extra-index-url", "-i")
PIN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(\[[A-Za-z0-9,._-]+\])?==[A-Za-z0-9.+!_-]+$")


@dataclass
class Env:
    key: str
    python: str
    cached: bool
    seconds: float
    tool: str
    log: str = ""

    def as_dict(self) -> dict:
        return {"key": self.key, "python": self.python, "cached": self.cached, "seconds": round(self.seconds, 1),
                "tool": self.tool}


def check_requirements(text: str) -> tuple[list[str], list[str]]:
    """Code check before install: every package is pinned with ==; the only options are https package indexes.
    Returns (sorted package lines, option lines)."""
    pkgs, opts, bad = [], [], []
    for raw in (text or "").splitlines():
        line = raw.split(" #")[0].split("\t#")[0].strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("-"):
            parts = line.replace("=", " ", 1).split() if line.startswith("--") else line.split()
            if len(parts) == 2 and parts[0] in INDEX_OPTIONS and parts[1].startswith("https://"):
                opts.append(f"{'--index-url' if parts[0] == '-i' else parts[0]} {parts[1]}")
            else:
                bad.append(f"{line!r}: only --index-url/--extra-index-url with an https URL are allowed")
        elif not PIN_RE.match(line.replace(" ", "")):
            bad.append(f"{line!r}: must be pinned as name==version (no ranges, wildcards, paths or VCS URLs)")
        else:
            pkgs.append(line.replace(" ", ""))
    if bad:
        raise ToolError("requirements must be pinned and use only https indexes:\n" + "\n".join(bad))
    return sorted(pkgs, key=str.lower), opts


def env_key(text: str) -> str:
    pkgs, opts = check_requirements(text)
    canon = "\n".join([f"python {sys.version_info.major}.{sys.version_info.minor}", *sorted(opts), *pkgs])
    return hashlib.sha256(canon.encode()).hexdigest()[:12]


def venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def run_proc(argv: list[str], cwd: Path, env: dict, timeout_s: float) -> tuple[int | None, str]:
    """Start with the executor's Windows-safe start; kill the tree on timeout. Returns (exit code or None, output)."""
    from lab.executor.worker import kill_tree, start

    try:
        p = start(argv, cwd, env)
    except OSError as e:
        raise ToolError(f"could not start {argv[0]!r}: {e}") from None
    timed_out = threading.Event()
    timer = threading.Timer(timeout_s, lambda: (timed_out.set(), kill_tree(p)))
    timer.start()
    try:
        out = p.stdout.read()
        code = p.wait()
    finally:
        timer.cancel()
    return (None if timed_out.is_set() else code), out


def make_env(requirements: str, envs_root: Path, timeout_s: float = ENV_TIMEOUT_S) -> Env:
    """One venv per requirements hash under envs_root/<key>/venv, reused once built. `uv` when it is on PATH,
    otherwise `python -m venv` + pip. The install step has the network; the run step does not."""
    from lab.executor.worker import child_env

    pkgs, opts = check_requirements(requirements)
    key = env_key(requirements)
    root = Path(envs_root) / key
    venv, marker = root / "venv", root / "ok.json"
    if marker.is_file():
        meta = json.loads(marker.read_text(encoding="utf-8"))
        return Env(key, str(venv_python(venv)), True, 0.0, meta.get("tool", "?"), "cached")
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)  # a half-built env from a failed or killed attempt
    root.mkdir(parents=True)
    (root / "requirements.txt").write_text("\n".join([*opts, *pkgs]) + "\n", encoding="utf-8")
    uv = shutil.which("uv")
    py = venv_python(venv)
    if uv:
        tool = "uv"
        steps = [[uv, "venv", str(venv), "--python", sys.executable]]
        if pkgs:
            steps.append([uv, "pip", "install", "--python", str(py), "-r", str(root / "requirements.txt")])
    else:
        tool = "venv+pip"
        steps = [[sys.executable, "-m", "venv", str(venv)]]
        if pkgs:
            steps.append([str(py), "-m", "pip", "install", "--disable-pip-version-check", "--no-input",
                          "-r", str(root / "requirements.txt")])
    env = child_env(sys.executable, network=True)
    t0, log = time.monotonic(), []
    for argv in steps:
        left = timeout_s - (time.monotonic() - t0)
        code, out = run_proc(argv, root, env, max(left, 1))
        log.append(f"$ {' '.join(Path(a).name if i == 0 else a for i, a in enumerate(argv))}\n{out[-3000:]}")
        if code != 0:
            shutil.rmtree(root, ignore_errors=True)
            why = "timed out" if code is None else f"exit code {code}"
            raise ToolError(f"make_env failed ({why}):\n" + "\n".join(log)[-RUN_TAIL:])
    secs = time.monotonic() - t0
    marker.write_text(json.dumps({"tool": tool, "seconds": round(secs, 1), "packages": pkgs, "options": opts}),
                      encoding="utf-8")
    return Env(key, str(py), False, secs, tool, "\n".join(log))


# -- repositories (SPEC §2.2 fetch_repo) ---------------------------------------------------------------------------
REPO_TIMEOUT_S = 600
REPO_URL_RE = re.compile(r"^https://[A-Za-z0-9.-]+(:\d+)?/[A-Za-z0-9._~/-]+$")


def check_repo_url(url: str) -> None:
    if not isinstance(url, str) or not REPO_URL_RE.match(url.strip()):
        raise ToolError(f"{url!r}: only plain https repository URLs are allowed (e.g. https://github.com/org/repo)")


def clone(url: str, dest: Path, commit: str | None = None) -> dict:
    """git clone (no prompts, no hooks from the network) and check out `commit` if given. Returns {url, commit}."""
    from lab.executor.worker import child_env

    env = child_env(sys.executable, network=True)
    env["GIT_TERMINAL_PROMPT"] = "0"
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    git = shutil.which("git") or "git"
    code, out = run_proc([git, "clone", "--quiet", "--", url, str(dest)], dest.parent, env, REPO_TIMEOUT_S)
    if code != 0:
        raise ToolError(f"git clone failed (exit code {code}):\n{out[-RUN_TAIL:]}")
    if commit:
        code, out = run_proc([git, "-C", str(dest), "checkout", "--quiet", commit], dest.parent, env, 120)
        if code != 0:
            raise ToolError(f"git checkout {commit} failed:\n{out[-RUN_TAIL:]}")
    code, out = run_proc([git, "-C", str(dest), "rev-parse", "HEAD"], dest.parent, env, 60)
    return {"url": url, "requested_commit": commit, "commit": out.strip().splitlines()[-1] if code == 0 else None}
