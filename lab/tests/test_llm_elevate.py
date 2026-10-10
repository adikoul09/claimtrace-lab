"""lab/llm.py: the Elevate gateway provider (OpenAI-compatible, Azure-style responses) and the daily token cap.
No network: an httpx.MockTransport stands in for the gateway."""
import json
from datetime import datetime, timezone

import httpx
import pytest

from lab import llm as llm_mod
from lab.llm import LLM, LLMError, LLMFiltered, LLMQuotaExhausted, Request
from lab.tests.test_runtime import FakeDB

URL = "https://elevate1-0.vercel.app/api/ai"
MODELS = {"fast": "gpt-5-mini", "smart": "gpt-5.6-luna"}


def ok(content, total=120, prompt=100, finish="stop", rid="req-1"):
    return httpx.Response(200, headers={"X-Elevate-Request-Id": rid}, json={
        "choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": finish,
                     "content_filter_results": {"hate": {"filtered": False, "severity": "safe"}}}],
        "usage": {"prompt_tokens": prompt, "completion_tokens": total - prompt, "total_tokens": total}})


@pytest.fixture
def gateway(monkeypatch, tmp_path):
    """Install a scripted gateway; returns (sent requests, make_llm)."""
    sent = []

    def install(*responses):
        it = iter(responses)

        def handler(request):
            sent.append(request)
            return next(it)
        monkeypatch.setattr(llm_mod, "HTTP_TRANSPORT", httpx.MockTransport(handler))
        monkeypatch.setattr(llm_mod.time, "sleep", lambda s: sent.append(("sleep", s)))
        values = {"LLM_API_KEY": "sk-test-secret", "LLM_BASE_URL": URL}
        monkeypatch.setattr(llm_mod, "setting", lambda name, default=None: values.get(name, default))
        db = FakeDB()
        llm = LLM(mode="live", provider="elevate", cache_dir=tmp_path, db=db, models=MODELS)
        monkeypatch.setattr(llm, "tokens_today", lambda: 0)
        return llm, db
    return sent, install


def body(r):
    return json.loads(r.content)


def test_request_shape_for_gpt_models(gateway):
    sent, install = gateway
    llm, db = install(ok("hello"))
    out = llm.call(Request(agent="a", system="sys", prompt="hi", model="fast"))
    r = sent[0]
    assert str(r.url) == URL and r.method == "POST"
    assert r.headers["authorization"] == "Bearer sk-test-secret"
    b = body(r)
    assert b["model"] == "gpt-5-mini" and b["stream"] is False
    assert b["messages"] == [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]
    assert b["max_completion_tokens"] == 1500 and "max_tokens" not in b
    assert out.output == "hello" and out.tokens_in + out.tokens_out == 120


def test_smart_default_cap_and_clipping(gateway):
    sent, install = gateway
    llm, _ = install(ok("a"), ok("b"), ok("c"))
    llm.call(Request(agent="a", prompt="1", model="smart"))
    llm.call(Request(agent="a", prompt="2", model="smart", max_output=99_999))
    llm.call(Request(agent="a", prompt="3", model="smart", max_output=0))
    assert [body(r)["max_completion_tokens"] for r in sent] == [3000, 4000, 1]


def test_deepseek_uses_max_tokens(gateway):
    sent, install = gateway
    llm, _ = install(ok("x"))
    llm.call(Request(agent="a", prompt="p", model="deepseek-v4-pro"))
    b = body(sent[0])
    assert b["max_tokens"] == 1500 and "max_completion_tokens" not in b


def test_schema_answers_are_parsed_from_text_even_in_fences(gateway):
    sent, install = gateway
    llm, _ = install(ok('```json\n{"a": 1}\n```'))
    out = llm.call(Request(agent="a", prompt="p", schema={"type": "object"}))
    assert out.output == {"a": 1}
    assert '"type": "object"' in body(sent[0])["messages"][0]["content"]


def test_llm_calls_row_keeps_total_tokens_and_request_id(gateway):
    sent, install = gateway
    llm, db = install(ok("x", total=321, rid="abc-123"))
    llm.call(Request(agent="a", prompt="p"), agent_id="ag", task_id="t")
    row = db.rows["llm_calls"][-1]
    assert row["total_tokens"] == 321 and row["request_id"] == "abc-123" and row["mode"] == "live"


def test_requests_over_48_kb_are_refused_before_sending(gateway):
    sent, install = gateway
    llm, _ = install()
    with pytest.raises(LLMError, match="48"):
        llm.call(Request(agent="a", prompt="x" * 50_000))
    assert sent == []


def test_429_waits_retry_after_then_retries(gateway):
    sent, install = gateway
    llm, _ = install(httpx.Response(429, headers={"Retry-After": "7"}, json={"error": "slow down"}), ok("done"))
    assert llm.call(Request(agent="a", prompt="p")).output == "done"
    assert ("sleep", 7.0) in sent


def test_403_stops_with_a_quota_event_and_no_retry(gateway):
    sent, install = gateway
    llm, db = install(httpx.Response(403, json={"error": "quota exhausted"}))
    with pytest.raises(LLMQuotaExhausted):
        llm.call(Request(agent="a", prompt="p"), task_id="t1")
    assert len([r for r in sent if not isinstance(r, tuple)]) == 1
    ev = [e for e in db.rows["events"] if e["type"] == "llm_quota_exhausted"]
    assert ev and ev[0]["task_id"] == "t1" and "403" in ev[0]["reason"]


@pytest.mark.parametrize("response", [
    ok("", finish="content_filter"),
    httpx.Response(400, json={"error": {"code": "content_filter", "message": "filtered by policy"}}),
])
def test_filtered_request_logs_an_event_and_is_not_retried(gateway, response):
    sent, install = gateway
    llm, db = install(response)
    with pytest.raises(LLMFiltered):
        llm.call(Request(agent="a", prompt="p"))
    assert len([r for r in sent if not isinstance(r, tuple)]) == 1
    assert [e for e in db.rows["events"] if e["type"] == "llm_filtered"]


def test_errors_never_contain_the_key(gateway):
    sent, install = gateway
    llm, db = install(httpx.Response(401, text="bad key sk-test-secret"))
    with pytest.raises(LLMError) as e:
        llm.call(Request(agent="a", prompt="p"))
    assert "sk-test-secret" not in str(e.value)
    assert all("sk-test-secret" not in json.dumps(ev) for ev in db.rows.get("events", []))


# ---- daily token cap ----------------------------------------------------------------------------------------------

def test_day_starts_at_0530_ist():
    assert llm_mod.day_start(datetime(2026, 10, 10, 3, 0, tzinfo=timezone.utc)) == \
        datetime(2026, 10, 10, 0, 0, tzinfo=timezone.utc)
    # 23:00 UTC is 04:30 IST the next day: still the same Elevate day
    assert llm_mod.day_start(datetime(2026, 10, 10, 23, 0, tzinfo=timezone.utc)) == \
        datetime(2026, 10, 10, 0, 0, tzinfo=timezone.utc)


def test_live_calls_above_the_daily_cap_are_refused_with_an_event(gateway, monkeypatch):
    sent, install = gateway
    llm, db = install(ok("x"))
    monkeypatch.setattr(llm, "tokens_today", lambda: 700_001)
    with pytest.raises(LLMError, match="700"):
        llm.call(Request(agent="a", prompt="p"))
    assert sent == []
    assert [e for e in db.rows["events"] if e["type"] == "llm_daily_cap"]


def test_replay_ignores_the_daily_cap(tmp_path, monkeypatch):
    db = FakeDB()
    llm = LLM(mode="replay", cache_dir=tmp_path, db=db, models=MODELS)
    req = Request(agent="a", prompt="p")
    llm.cache.put("a", req.key_for("gpt-5-mini"), {
        "key": "k", "agent": "a", "model": "gpt-5-mini",
        "request": {"system": "", "prompt": "p", "schema": None, "inputs": {}},
        "response": {"output": "cached", "text": "cached", "tokens_in": 1, "tokens_out": 1}})
    monkeypatch.setattr(llm, "tokens_today", lambda: 10**9)
    assert llm.call(req).output == "cached"


# ---- every provider error reaches the event stream in full, keys scrubbed -----------------------------------------

def test_any_provider_error_is_an_event_with_the_full_text_and_no_key(monkeypatch, tmp_path):
    long_detail = "x" * 3000

    def broken(req, model):
        raise RuntimeError(f"upstream said: key AIza-secret-123 rejected; Bearer abc.def; {long_detail}")

    monkeypatch.setitem(llm_mod.PROVIDERS, "broken", broken)
    monkeypatch.setattr(llm_mod, "setting", lambda name, default=None: {"LLM_API_KEY": "AIza-secret-123"}.get(name, default))
    db = FakeDB()
    llm = LLM(mode="live", provider="broken", cache_dir=tmp_path, db=db, models=MODELS)
    with pytest.raises(LLMError) as e:
        llm.call(Request(agent="a", prompt="p"), task_id="t9")
    ev = [x for x in db.rows["events"] if x["type"] == "llm_error"]
    assert ev and ev[0]["task_id"] == "t9"
    assert long_detail in ev[0]["reason"]                       # not cut
    assert "AIza-secret-123" not in ev[0]["reason"] and "abc.def" not in ev[0]["reason"]
    assert "AIza-secret-123" not in str(e.value)


# ---- a call that spent tokens is logged even when its answer is unusable ------------------------------------------

@pytest.mark.parametrize("response,schema", [
    (ok("", total=120, finish="length", rid="r-len"), None),                      # cap used up by reasoning
    (ok("not json at all", total=120, rid="r-json"), {"type": "object"}),           # schema call, no JSON
    (ok("", total=120, finish="content_filter", rid="r-filt"), None),              # answer filtered
], ids=["cap-used-up", "non-json", "filtered-answer"])
def test_spent_tokens_are_logged_when_the_answer_is_unusable(gateway, response, schema):
    sent, install = gateway
    llm, db = install(response)
    with pytest.raises(LLMError):
        llm.call(Request(agent="a", prompt="p", schema=schema), agent_id="ag", task_id="t")
    rows = db.rows.get("llm_calls", [])
    assert len(rows) == 1
    row = rows[0]
    assert (row["tokens_in"], row["tokens_out"], row["total_tokens"]) == (100, 20, 120)
    assert row["mode"] == "live" and row["task_id"] == "t" and row["request_id"].startswith("r-")


def test_a_refused_request_that_spent_nothing_writes_no_row(gateway):
    sent, install = gateway
    llm, db = install(httpx.Response(403, json={"error": "quota"}))
    with pytest.raises(LLMQuotaExhausted):
        llm.call(Request(agent="a", prompt="p"))
    assert db.rows.get("llm_calls", []) == []
