"""The one interface for the product's own LLM calls (MASTER_PROMPT section 5).

Backends:
  replay         (default) answers only from the cache (.cache/llm/); a miss is an error that names `--llm live`
  claude_cli     `claude -p` as a subprocess (the Pro login; same quota as interactive use)
  anthropic_api  the `anthropic` SDK, only if ANTHROPIC_API_KEY is set; tool-less agents only

`--llm live` picks anthropic_api when ANTHROPIC_API_KEY is set, else claude_cli. Live backends still answer from the
cache first: quota is spent only on a miss, and every response is stored, so the same run replays at zero quota.

Every call appends one line to audits/<id>/llm_usage.jsonl: agent, backend, cache hit or miss, the usage token counts
and total_cost_usd of the recorded call, duration, CLI version, model alias and the model that answered."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from el01.llm.cache import Cache, cache_key

AGENT_TOOLS = ("Read", "Grep", "Glob")  # agents that read a repository get these, read-only
API_MODELS = {"sonnet": "claude-sonnet-5-5", "opus": "claude-opus-5-5", "fable": "claude-fable-5-1"}


class LLMError(RuntimeError):
    pass


class ReplayMiss(LLMError):
    pass


@dataclass
class Request:
    agent: str                              # e.g. "repair"
    prompt: str
    schema: Optional[dict] = None           # JSON schema of the structured answer
    model: str = "sonnet"                   # alias
    inputs: dict[str, str] = field(default_factory=dict)  # name -> sha256 / git tree id of what the agent can read
    tools: tuple[str, ...] = ()             # () = no tools; AGENT_TOOLS for repository readers
    add_dirs: tuple[Path, ...] = ()         # extra directories the tools may read
    repo_copy: Optional[Path] = None        # copied into the agent's working directory as ./repo (read-only use)
    max_turns: int = 1

    @property
    def key(self) -> str:
        return cache_key(self.agent, self.prompt, self.schema, self.model, self.inputs)


@dataclass
class Response:
    output: object                          # structured_output (dict) when a schema was given, else the text
    key: str
    backend: str
    cache: str                              # "hit" or "miss"
    record: dict                            # the cache record


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def claude_version(claude: str = "claude") -> Optional[str]:
    try:
        p = subprocess.run([claude, "--version"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return p.stdout.strip().split()[0] if p.returncode == 0 and p.stdout.strip() else None


def claude_argv(req: Request, claude: str = "claude") -> list[str]:
    """The `claude -p` command line. The prompt goes on stdin.

    --safe-mode            no CLAUDE.md, skills, plugins, hooks or MCP servers from this machine's configuration
    --restricted           no code-running tools; file tools confined to the working directory and --add-dir
    --strict-mcp-config    no MCP servers except --mcp-config (none given)
    The working directory is a fresh temporary folder (set by the caller), so no project CLAUDE.md is in reach; a
    repository snapshot is copied into it as ./repo, so prompts name no machine path."""
    argv = [claude, "-p", "--output-format", "json", "--model", req.model, "--max-turns", str(req.max_turns),
            "--no-session-persistence", "--safe-mode", "--restricted", "--strict-mcp-config",
            "--tools", ",".join(req.tools)]
    if req.tools:
        argv += ["--allowedTools", ",".join(req.tools)]
    for d in req.add_dirs:
        argv += ["--add-dir", str(d)]
    if req.schema is not None:
        argv += ["--json-schema", json.dumps(req.schema, separators=(",", ":"))]
    return argv


class LLM:
    def __init__(self, mode: str = "replay", cache_dir: Path = Path(".cache/llm"), usage_log: Optional[Path] = None,
                 claude: str = "claude", timeout_s: int = 1800, tag: Optional[str] = None, guard=None):
        if mode == "live":
            mode = "anthropic_api" if os.environ.get("ANTHROPIC_API_KEY") else "claude_cli"
        if mode not in ("replay", "claude_cli", "anthropic_api"):
            raise ValueError(f"unknown LLM backend {mode!r}")
        if mode == "anthropic_api" and not os.environ.get("ANTHROPIC_API_KEY"):
            raise LLMError("anthropic_api needs ANTHROPIC_API_KEY")
        self.mode, self.cache, self.usage_log = mode, Cache(cache_dir), usage_log
        self.claude, self.timeout_s = claude, timeout_s
        self.tag, self.guard = tag, guard  # tag: written on every usage line; guard(req): may refuse a live call
        self._cli_version: Optional[str] = None

    @property
    def cli_version(self) -> Optional[str]:
        if self._cli_version is None and self.mode == "claude_cli":
            self._cli_version = claude_version(self.claude)
        return self._cli_version

    def call(self, req: Request) -> Response:
        key = req.key
        t0 = time.monotonic()
        rec = self.cache.get(req.agent, key)
        if rec is not None:
            resp = Response(rec["response"]["output"], key, self.mode, "hit", rec)
        elif self.mode == "replay":
            self._log(req, key, "miss", None, time.monotonic() - t0, error="no recorded response")
            raise ReplayMiss(f"no recorded response for agent {req.agent!r} (key {key[:12]}); "
                             f"run with --llm live to make this call")
        else:
            if self.guard is not None:
                self.guard(req)
            rec = self._claude_cli(req, key) if self.mode == "claude_cli" else self._anthropic_api(req, key)
            self.cache.put(req.agent, key, rec)
            resp = Response(rec["response"]["output"], key, self.mode, "miss", rec)
        self._log(req, key, resp.cache, rec, time.monotonic() - t0)
        return resp

    # ---- backends -------------------------------------------------------------------------------------------------

    def _record(self, req: Request, key: str, backend: str, output, meta: dict) -> dict:
        return {"key": key, "agent": req.agent, "model": req.model, "backend": backend, "created_utc": utc_now(),
                "cli_version": self.cli_version if backend == "claude_cli" else None,
                "request": {"schema": req.schema, "inputs": req.inputs, "tools": list(req.tools),
                            "max_turns": req.max_turns, "prompt": req.prompt},
                "response": {"output": output, **meta}}

    def _claude_cli(self, req: Request, key: str) -> dict:
        if shutil.which(self.claude) is None and not Path(self.claude).exists():
            raise LLMError(f"{self.claude!r} not found on PATH")
        argv = claude_argv(req, self.claude)
        with tempfile.TemporaryDirectory(prefix="el01-agent-") as cwd:
            if req.repo_copy is not None:
                shutil.copytree(req.repo_copy, Path(cwd) / "repo", symlinks=True,
                                ignore=shutil.ignore_patterns(".el01-snapshot"))
            env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY",)}  # the Pro login, never a key
            t0 = time.monotonic()
            p = subprocess.run(argv, input=req.prompt, capture_output=True, text=True, cwd=cwd, env=env,
                               timeout=self.timeout_s)
            secs = round(time.monotonic() - t0, 1)
        try:
            out = json.loads(p.stdout)
        except json.JSONDecodeError:
            raise LLMError(f"claude -p exit {p.returncode}: not JSON: {p.stdout[-500:]!r} {p.stderr[-500:]!r}")
        if isinstance(out, list):  # stream-like list of events: the result is the last one
            out = next((e for e in reversed(out) if e.get("type") == "result"), out[-1])
        if p.returncode != 0 or out.get("is_error") or out.get("subtype") not in (None, "success"):
            raise LLMError(f"claude -p failed (exit {p.returncode}, subtype {out.get('subtype')}): "
                           f"{str(out.get('result') or p.stderr)[-800:]}")
        if req.schema is not None:
            output = out.get("structured_output")
            if output is None:
                raise LLMError("claude -p returned no structured_output for a schema call")
        else:
            output = out.get("result")
        meta = {"result_text": out.get("result"), "usage": out.get("usage"),
                "total_cost_usd": out.get("total_cost_usd"), "duration_ms": out.get("duration_ms"),
                "num_turns": out.get("num_turns"), "models": sorted((out.get("modelUsage") or {}).keys()),
                "session_id": out.get("session_id"), "permission_denials": out.get("permission_denials"),
                "wall_seconds": secs}
        return self._record(req, key, "claude_cli", output, meta)

    def _anthropic_api(self, req: Request, key: str) -> dict:
        if req.tools:
            raise LLMError("the anthropic_api backend runs tool-less agents only; use claude_cli for "
                           f"agent {req.agent!r}, which reads a repository")
        import anthropic  # optional extra `api`
        client = anthropic.Anthropic()
        kwargs = {}
        if req.schema is not None:
            kwargs["output_config"] = {"format": {"type": "json_schema", "schema": req.schema}}
        t0 = time.monotonic()
        msg = client.messages.create(model=API_MODELS.get(req.model, req.model), max_tokens=16000,
                                     messages=[{"role": "user", "content": req.prompt}], **kwargs)
        secs = round(time.monotonic() - t0, 1)
        if msg.stop_reason == "refusal":
            raise LLMError(f"the model declined (agent {req.agent!r})")
        text = next((b.text for b in msg.content if b.type == "text"), "")
        output = json.loads(text) if req.schema is not None else text
        meta = {"result_text": text, "usage": msg.usage.to_dict(), "total_cost_usd": None,
                "duration_ms": int(secs * 1000), "num_turns": 1, "models": [msg.model], "wall_seconds": secs}
        return self._record(req, key, "anthropic_api", output, meta)

    # ---- usage log ------------------------------------------------------------------------------------------------

    def _log(self, req: Request, key: str, cache: str, rec: Optional[dict], secs: float, error: str = None) -> None:
        if self.usage_log is None:
            return
        r = (rec or {}).get("response", {})
        line = {"utc": utc_now(), "agent": req.agent, "backend": self.mode, "cache": cache, "key": key,
                "model": req.model, "models": r.get("models"),
                "cli_version": (rec or {}).get("cli_version"), "recorded_backend": (rec or {}).get("backend"),
                "usage": r.get("usage"), "total_cost_usd": r.get("total_cost_usd"),
                "num_turns": r.get("num_turns"), "recorded_duration_ms": r.get("duration_ms"),
                "duration_s": round(secs, 2)}
        if self.tag:
            line["tag"] = self.tag
        if error:
            line["error"] = error
        self.usage_log.parent.mkdir(parents=True, exist_ok=True)
        with self.usage_log.open("a") as f:
            f.write(json.dumps(line) + "\n")
