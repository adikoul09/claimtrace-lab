"""The one interface for LLM calls (CLAUDE.md: google-genai only through here).

  LLM_PROVIDER   elevate: the Elevate gateway (OpenAI-compatible chat completions, Azure-style responses) at
                 LLM_BASE_URL; gemini: Google, the fallback. The key is LLM_API_KEY either way.
  LLM_MODE       live (default): every call goes to the provider and the response is cached
                 replay: answers only from the cache of real recorded calls; a miss raises ReplayMiss
  LLM_MODEL_FAST / LLM_MODEL_SMART   what the aliases "fast" and "smart" mean (elevate: gpt-5-mini / gpt-5.6-luna;
                 gemini: gemini-flash-latest for both, the only tier with free quota)

Elevate rules: stream=false, text only; a request body over 48 KB is refused before sending; the output cap
(reasoning included) is 1-4000 tokens, default 3000 for "smart" and 1500 otherwise (gpt-* send it as
max_completion_tokens, deepseek-v4-pro as max_tokens); 429 waits Retry-After and retries; 403 means the quota is gone
(event llm_quota_exhausted, no retry); a content-filtered request gets an llm_filtered event and is not retried.
Live elevate calls stop for the day once llm_calls holds DAILY_TOKEN_CAP live tokens since 05:30 IST (event
llm_daily_cap).

Every answered call writes one llm_calls row (agent_id, task_id, model, tokens_in, tokens_out, total_tokens, request_id,
mode, cache_key). A
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
import re
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

from lab.db import ROOT, client, emit, setting

CACHE_DIR = ROOT / ".cache" / "llm"
DEFAULT_MODEL = "gemini-flash-latest"
DEFAULT_MODELS = {"gemini": {"fast": DEFAULT_MODEL, "smart": DEFAULT_MODEL},
                  "elevate": {"fast": "gpt-5-mini", "smart": "gpt-5.6-luna"}}
MODES = ("live", "replay")
RETRY_CODES = (429, 500, 503)  # rate limit and transient overload
RETRY_WAIT_S = (2, 6, 18)

ELEVATE_URL = "https://elevate1-0.vercel.app/api/ai"
MAX_REQUEST_BYTES = 48_000
OUTPUT_CAP = (1, 4000)
DEFAULT_OUTPUT = {"smart": 3000, "fast": 1500}
RETRY_429 = 3
RETRY_AFTER_MAX_S = 120
HTTP_TIMEOUT_S = 300
HTTP_TRANSPORT = None              # tests put an httpx.MockTransport here
DAILY_TOKEN_CAP = 700_000
DAY_START_UTC = timedelta(0)       # 05:30 IST is 00:00 UTC


class LLMError(RuntimeError):
    usage: Optional[dict] = None  # set when the provider answered and billed tokens, but the answer was unusable


class LLMEventError(LLMError):
    """A provider error the controller should see on the live event stream."""
    event = "llm_error"


class LLMQuotaExhausted(LLMEventError):
    event = "llm_quota_exhausted"


class LLMFiltered(LLMEventError):
    event = "llm_filtered"


def scrub(text: str, *secrets: Optional[str]) -> str:
    for s in secrets:
        if s:
            text = text.replace(s, "***")
    return re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._\-]+", r"\1***", text)


def day_start(now: datetime) -> datetime:
    """Start of the Elevate quota day (05:30 IST) containing `now`, in UTC."""
    start = now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) + DAY_START_UTC
    return start if start <= now else start - timedelta(days=1)


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
    max_output: Optional[int] = None        # output cap incl. reasoning (elevate); None: the alias default

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
            raise LLMEventError(scrub(f"gemini call failed: {type(e).__name__}: {e}", key)) from None
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


def parse_json(text: str) -> object:
    """A JSON answer from a text-only model: tolerate code fences and prose around one object."""
    t = text.strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", t, re.S)
    if m:
        t = m.group(1)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        i, j = t.find("{"), t.rfind("}")
        if 0 <= i < j:
            return json.loads(t[i:j + 1])
        raise


def _filtered(data) -> bool:
    err = data.get("error") if isinstance(data, dict) else None
    if not isinstance(err, dict):
        return False
    inner = err.get("innererror") or {}
    codes = f"{err.get('code')} {inner.get('code')}"
    return "content_filter" in codes or "ResponsibleAIPolicyViolation" in codes


def _elevate(req: Request, model: str) -> dict:
    import httpx

    key = setting("LLM_API_KEY")
    if not key:
        raise LLMError("LLM_PROVIDER=elevate needs LLM_API_KEY (env or .env)")
    url = setting("LLM_BASE_URL", ELEVATE_URL)
    system = req.system
    if req.schema is not None:
        system = (system + "\n\n" if system else "") + (
            "Answer with one JSON object only, no prose and no code fences, matching this JSON schema:\n"
            + json.dumps(req.schema, ensure_ascii=False))
    messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": req.prompt}]
    cap = min(max(int(req.max_output if req.max_output is not None else DEFAULT_OUTPUT["fast"]), OUTPUT_CAP[0]),
              OUTPUT_CAP[1])
    payload = {"model": model, "messages": messages, "stream": False,
               ("max_tokens" if model.startswith("deepseek") else "max_completion_tokens"): cap}
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    if len(data) > MAX_REQUEST_BYTES:
        raise LLMError(f"request is {len(data) / 1000:.1f} KB; the gateway limit is 48 KB, so it was not sent")
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    n429 = n5xx = 0
    with httpx.Client(transport=HTTP_TRANSPORT, timeout=HTTP_TIMEOUT_S) as c:
        while True:
            try:
                r = c.post(url, content=data, headers=headers)
            except httpx.HTTPError as e:
                if n5xx < len(RETRY_WAIT_S):
                    time.sleep(RETRY_WAIT_S[n5xx])
                    n5xx += 1
                    continue
                raise LLMEventError(scrub(f"elevate call failed: {type(e).__name__}: {e}", key)) from None
            rid = r.headers.get("X-Elevate-Request-Id")
            try:
                body = r.json()
            except ValueError:
                body = None
            if r.status_code == 429 and n429 < RETRY_429:
                try:
                    wait = float(r.headers.get("Retry-After") or 10)
                except ValueError:
                    wait = 10.0
                time.sleep(min(max(wait, 0.0), RETRY_AFTER_MAX_S))
                n429 += 1
                continue
            if r.status_code == 403:
                raise LLMQuotaExhausted(f"elevate returned 403 (quota exhausted; not retried), request id {rid}: "
                                        f"{scrub(r.text, key)}")
            if r.status_code == 400 and _filtered(body):
                raise LLMFiltered(f"elevate filtered the request (content filter; not retried), request id {rid}: "
                                  f"{scrub(r.text, key)}")
            if r.status_code in (500, 502, 503, 504) and n5xx < len(RETRY_WAIT_S):
                time.sleep(RETRY_WAIT_S[n5xx])
                n5xx += 1
                continue
            if r.status_code != 200:
                raise LLMEventError(f"elevate returned HTTP {r.status_code}, request id {rid}: {scrub(r.text, key)}")
            break

    u = (body or {}).get("usage") or {}
    total = int(u.get("total_tokens") or 0)
    tin = min(int(u.get("prompt_tokens") or 0), total)
    usage = {"tokens_in": tin, "tokens_out": total - tin, "total_tokens": total, "request_id": rid}

    def spent(exc: LLMError) -> LLMError:
        exc.usage = usage  # the tokens were billed; LLM.call still logs them
        return exc

    choice = ((body or {}).get("choices") or [{}])[0]
    text = (choice.get("message") or {}).get("content") or ""
    finish = choice.get("finish_reason")
    if finish == "content_filter":
        raise spent(LLMFiltered(f"elevate filtered the answer (finish_reason content_filter; not retried), "
                                f"request id {rid}"))
    if not text and finish == "length":
        raise spent(LLMError(f"the {cap}-token output cap (reasoning included) ran out before any answer, "
                             f"request id {rid}"))
    if req.schema is not None:
        try:
            output = parse_json(text)
        except json.JSONDecodeError:
            raise spent(LLMError(f"elevate returned non-JSON for a schema call: {text[:300]!r}")) from None
    else:
        output = text
    return {"output": output, "text": text, **usage, "models": [(body or {}).get("model") or model]}


PROVIDERS: dict[str, Callable[[Request, str], dict]] = {"gemini": _gemini, "elevate": _elevate}


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
            alias: setting(f"LLM_MODEL_{alias.upper()}", DEFAULT_MODELS.get(self.provider, {}).get(alias))
            for alias in ("fast", "smart")}

    def model_for(self, alias: str) -> str:
        if alias in ("fast", "smart"):
            m = self.models.get(alias)
            if not m:
                raise LLMError(f"LLM_MODEL_{alias.upper()} is not set")
            return m
        return alias

    def tokens_today(self) -> int:
        """Live tokens in llm_calls since the start of the quota day (05:30 IST), over all processes."""
        since = day_start(datetime.now(timezone.utc)).isoformat()
        total, page, start = 0, 1000, 0
        while True:
            rows = self.db.table("llm_calls").select("tokens_in,tokens_out").eq("mode", "live").gte("ts", since) \
                .range(start, start + page - 1).execute().data
            total += sum((r.get("tokens_in") or 0) + (r.get("tokens_out") or 0) for r in rows)
            if len(rows) < page:
                return total
            start += page

    def _event(self, type_: str, message: str, reason: str, agent_id, task_id, data: Optional[dict] = None) -> None:
        try:
            emit(self.db, type_, message, scrub(reason, setting("LLM_API_KEY")), agent_id=agent_id, task_id=task_id,
                 data=data)
        except Exception as e:  # an event that cannot be written must not hide the LLM error
            print(f"[llm] could not write {type_} event: {type(e).__name__}", flush=True)

    def call(self, req: Request, agent_id: Optional[str] = None, task_id: Optional[str] = None) -> Response:
        model = self.model_for(req.model)
        key = req.key_for(model)
        if self.mode == "replay":
            rec = self.cache.get(req.agent, key) or self.cache.find_request(req)
            if rec is None:
                raise ReplayMiss(f"no recorded response for agent {req.agent!r} (key {key[:12]}); "
                                 f"run with LLM_MODE=live to make this call")
        else:
            used = self.tokens_today() if self.provider == "elevate" else 0  # the cap is the gateway's quota
            if used > DAILY_TOKEN_CAP:
                msg = (f"daily LLM token cap reached: {used} live tokens since 05:30 IST, cap {DAILY_TOKEN_CAP}; "
                       f"live call refused (replay still works)")
                self._event("llm_daily_cap", f"LLM call refused for {req.agent}", msg, agent_id, task_id,
                            {"tokens_today": used, "cap": DAILY_TOKEN_CAP})
                raise LLMError(msg)
            cap = req.max_output if req.max_output is not None else \
                DEFAULT_OUTPUT.get(req.model, DEFAULT_OUTPUT["fast"])
            t0 = time.monotonic()
            try:
                r = PROVIDERS[self.provider](replace(req, max_output=cap), model)
            except Exception as e:  # every provider error reaches the event stream in full, keys scrubbed
                text = scrub(str(e) if isinstance(e, LLMError) else f"{type(e).__name__}: {e}", setting("LLM_API_KEY"))
                self._event(getattr(e, "event", "llm_error"), f"LLM call failed for {req.agent} ({self.provider} "
                            f"{model})", text, agent_id, task_id, {"provider": self.provider, "model": model})
                if getattr(e, "usage", None):  # billed tokens count toward the daily cap even without an answer
                    self._log_call({"agent_id": agent_id, "task_id": task_id, "model": model, "mode": self.mode,
                                    "cache_key": key, **e.usage})
                if isinstance(e, LLMError):
                    raise
                raise LLMError(text) from None
            rec = {"key": key, "agent": req.agent, "provider": self.provider, "model": model,
                   "created_utc": utc_now(),
                   "request": {"system": req.system, "prompt": req.prompt, "schema": req.schema,
                               "inputs": req.inputs},
                   "response": {"output": r["output"], "text": r["text"], "tokens_in": r["tokens_in"],
                                "tokens_out": r["tokens_out"], "models": r["models"],
                                "total_tokens": r.get("total_tokens", r["tokens_in"] + r["tokens_out"]),
                                "request_id": r.get("request_id"),
                                "wall_seconds": round(time.monotonic() - t0, 1)}}
            self.cache.put(req.agent, key, rec)
        resp = rec["response"]
        out = Response(resp["output"], rec.get("key", key), self.mode, rec.get("model", model), resp["tokens_in"],
                       resp["tokens_out"], rec)
        self._log_call({"agent_id": agent_id, "task_id": task_id, "model": out.model, "tokens_in": out.tokens_in,
                        "tokens_out": out.tokens_out, "mode": self.mode, "cache_key": out.key,
                        "total_tokens": resp.get("total_tokens", out.tokens_in + out.tokens_out),
                        "request_id": resp.get("request_id")})
        return out

    GATEWAY_COLUMNS = ("total_tokens", "request_id")  # added by migration 002
    _has_gateway_columns = True

    def _log_call(self, row: dict) -> None:
        if not LLM._has_gateway_columns:
            row = {k: v for k, v in row.items() if k not in self.GATEWAY_COLUMNS}
        try:
            self.db.table("llm_calls").insert(row).execute()
        except Exception as e:
            if not any(c in str(e) for c in self.GATEWAY_COLUMNS):
                raise
            LLM._has_gateway_columns = False
            print("[llm] llm_calls lacks total_tokens/request_id: apply migration 002; logging without them",
                  flush=True)
            self.db.table("llm_calls").insert({k: v for k, v in row.items()
                                               if k not in self.GATEWAY_COLUMNS}).execute()
