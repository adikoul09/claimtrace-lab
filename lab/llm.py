"""The one interface for LLM calls (CLAUDE.md: google-genai only through here).

  LLM_PROVIDER   gemini (only provider so far); the key is LLM_API_KEY
  LLM_MODE       live (default): every call goes to the provider and the response is cached
                 replay: answers only from the cache of real recorded calls; a miss raises ReplayMiss
  LLM_MODEL_FAST / LLM_MODEL_SMART   what the aliases "fast" and "smart" mean (default for both: gemini-flash-latest,
                 the only tier with free quota)

Every answered call writes one llm_calls row (agent_id, task_id, model, tokens_in, tokens_out, mode, cache_key). A
replayed call logs the token counts of the recorded call with mode 'replay', so budgets behave the same in both modes.

Ported from baseline/el01-auditor/el01/llm (cache.py, backend.py): same cache key (sha256 of agent, prompt, schema,
model and input hashes) and one JSON file per call under .cache/llm/<agent>/<key>.json holding the prompt next to the
response. Changed for Round 1: `claude -p` and the anthropic backend are gone; the usage log is the llm_calls table;
live mode does not answer from the cache, so 'live' in llm_calls always means a fresh call. Replay also finds a call
recorded under another model name (e.g. before a model rename) when system, prompt, schema and inputs are identical; it
is logged with the recorded model and key."""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from lab.db import ROOT, client, setting

CACHE_DIR = ROOT / ".cache" / "llm"
DEFAULT_MODEL = "gemini-flash-latest"
MODES = ("live", "replay")
RETRY_CODES = (429, 500, 503)  # rate limit and transient overload
RETRY_WAIT_S = (2, 6, 18)


class LLMError(RuntimeError):
    pass


class ReplayMiss(LLMError):
    pass


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def cache_key(agent: str, prompt: str, schema: Optional[dict], model: str, inputs: dict[str, str]) -> str:
    """inputs: name -> sha256 of anything the agent reads besides the prompt. Order-independent."""
    payload = json.dumps({"agent": agent, "prompt": prompt, "schema": schema, "model": model,
                          "inputs": sorted(inputs.items())}, sort_keys=True, ensure_ascii=False)
    return sha256_bytes(payload.encode("utf-8"))


@dataclass
class Request:
    agent: str                              # cache folder and llm_calls context, e.g. "reader-v1"
    prompt: str
    system: str = ""
    schema: Optional[dict] = None           # JSON schema of a structured answer; None for text
    model: str = "fast"                     # alias ("fast", "smart") or a model name
    inputs: dict[str, str] = field(default_factory=dict)

    def key_for(self, model: str) -> str:
        prompt = f"{self.system}\n\n{self.prompt}" if self.system else self.prompt
        return cache_key(self.agent, prompt, self.schema, model, self.inputs)


@dataclass
class Response:
    output: object                          # parsed JSON when a schema was given, else the text
    key: str
    mode: str                               # "live" or "replay"
    model: str
    tokens_in: int
    tokens_out: int
    record: dict


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# ---- providers: (req, model) -> {output, text, tokens_in, tokens_out, models} ---------------------------------------

def _gemini(req: Request, model: str) -> dict:
    from google import genai
    from google.genai import types

    key = setting("LLM_API_KEY")
    if not key:
        raise LLMError("LLM_PROVIDER=gemini needs LLM_API_KEY (env or .env)")
    config = types.GenerateContentConfig(system_instruction=req.system or None)
    if req.schema is not None:
        config.response_mime_type = "application/json"
        config.response_json_schema = req.schema
    from google.genai import errors

    for attempt in range(len(RETRY_WAIT_S) + 1):
        try:
            with genai.Client(api_key=key) as c:  # held open for the call; an unreferenced Client closes itself
                r = c.models.generate_content(model=model, contents=req.prompt, config=config)
            break
        except Exception as e:  # never let a key reach a log line
            if isinstance(e, errors.APIError) and e.code in RETRY_CODES and attempt < len(RETRY_WAIT_S):
                time.sleep(RETRY_WAIT_S[attempt])
                continue
            raise LLMError(f"gemini call failed: {type(e).__name__}: {str(e).replace(key, '***')[:800]}") from None
    text = r.text or ""
    if req.schema is not None:
        try:
            output = json.loads(text)
        except json.JSONDecodeError:
            raise LLMError(f"gemini returned non-JSON for a schema call: {text[:300]!r}") from None
    else:
        output = text
    u = r.usage_metadata
    return {"output": output, "text": text,
            "tokens_in": (u.prompt_token_count or 0) if u else 0,
            # thinking tokens are billed as output
            "tokens_out": ((u.candidates_token_count or 0) + (u.thoughts_token_count or 0)) if u else 0,
            "models": [r.model_version or model]}


PROVIDERS: dict[str, Callable[[Request, str], dict]] = {"gemini": _gemini}


# ---- cache --------------------------------------------------------------------------------------------------------

class Cache:
    def __init__(self, root: Path):
        self.root = Path(root)

    def path(self, agent: str, key: str) -> Path:
        return self.root / agent / f"{key}.json"

    def get(self, agent: str, key: str) -> Optional[dict]:
        p = self.path(agent, key)
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def find_request(self, req: "Request") -> Optional[dict]:
        """A recorded call of this agent with the same system, prompt, schema and inputs, under any model."""
        want = {"system": req.system, "prompt": req.prompt, "schema": req.schema, "inputs": req.inputs}
        for p in sorted((self.root / req.agent).glob("*.json")):
            rec = json.loads(p.read_text(encoding="utf-8"))
            r = rec.get("request") or {}
            if {k: r.get(k, {} if k == "inputs" else None) for k in want} == want:
                return rec
        return None

    def put(self, agent: str, key: str, record: dict) -> Path:
        p = self.path(agent, key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(p)
        return p


# ---- client -------------------------------------------------------------------------------------------------------

class LLM:
    def __init__(self, mode: Optional[str] = None, provider: Optional[str] = None, cache_dir: Path = CACHE_DIR,
                 db=None, models: Optional[dict[str, str]] = None):
        self.mode = mode or setting("LLM_MODE", "live")
        self.provider = provider or setting("LLM_PROVIDER", "gemini")
        if self.mode not in MODES:
            raise LLMError(f"unknown LLM_MODE {self.mode!r}; use one of {MODES}")
        if self.mode == "live" and self.provider not in PROVIDERS:
            raise LLMError(f"unknown LLM_PROVIDER {self.provider!r}; available: {sorted(PROVIDERS)}")
        self.cache = Cache(cache_dir)
        self.db = db if db is not None else client()
        self.models = models if models is not None else {
            "fast": setting("LLM_MODEL_FAST", DEFAULT_MODEL), "smart": setting("LLM_MODEL_SMART", DEFAULT_MODEL)}

    def model_for(self, alias: str) -> str:
        if alias in ("fast", "smart"):
            m = self.models.get(alias)
            if not m:
                raise LLMError(f"LLM_MODEL_{alias.upper()} is not set")
            return m
        return alias

    def call(self, req: Request, agent_id: Optional[str] = None, task_id: Optional[str] = None) -> Response:
        model = self.model_for(req.model)
        key = req.key_for(model)
        if self.mode == "replay":
            rec = self.cache.get(req.agent, key) or self.cache.find_request(req)
            if rec is None:
                raise ReplayMiss(f"no recorded response for agent {req.agent!r} (key {key[:12]}); "
                                 f"run with LLM_MODE=live to make this call")
        else:
            t0 = time.monotonic()
            r = PROVIDERS[self.provider](req, model)
            rec = {"key": key, "agent": req.agent, "provider": self.provider, "model": model,
                   "created_utc": utc_now(),
                   "request": {"system": req.system, "prompt": req.prompt, "schema": req.schema,
                               "inputs": req.inputs},
                   "response": {"output": r["output"], "text": r["text"], "tokens_in": r["tokens_in"],
                                "tokens_out": r["tokens_out"], "models": r["models"],
                                "wall_seconds": round(time.monotonic() - t0, 1)}}
            self.cache.put(req.agent, key, rec)
        resp = rec["response"]
        out = Response(resp["output"], rec.get("key", key), self.mode, rec.get("model", model), resp["tokens_in"],
                       resp["tokens_out"], rec)
        self.db.table("llm_calls").insert({
            "agent_id": agent_id, "task_id": task_id, "model": out.model, "tokens_in": out.tokens_in,
            "tokens_out": out.tokens_out, "mode": self.mode, "cache_key": out.key}).execute()
        return out
