"""The fixed tool set (SPEC §2.2). Agents can call only these, and only the ones their agents row grants.

File tools act inside the run's working directory (a folder under runs/); any path that resolves outside it is
refused. `run` reuses the executor's sandbox: allowlisted environment (no keys), own process group, hard timeout.
A ToolError's message goes back to the model as the observation, so it can correct itself."""
from __future__ import annotations

import json
import sys
import threading
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
        self.workdir, self.allowed = wd, list(allowed)
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
        raise ToolError("fetch_repo is not available yet")

    def _make_env(self, requirements: str) -> str:
        raise ToolError("make_env is not available yet")
