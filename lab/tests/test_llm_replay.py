"""lab/llm.py: model defaults and replay of calls recorded under another model name."""
from lab.llm import LLM, DEFAULT_MODEL, Request
from lab.tests.test_runtime import FakeDB


def test_both_tiers_default_to_gemini_flash_latest(monkeypatch):
    monkeypatch.setattr("lab.llm.setting", lambda name, default=None: default)
    llm = LLM(mode="replay", db=FakeDB())
    assert DEFAULT_MODEL == "gemini-flash-latest"
    assert llm.model_for("fast") == llm.model_for("smart") == DEFAULT_MODEL


def test_replay_finds_a_call_recorded_under_an_older_model_name(tmp_path):
    db = FakeDB()
    req = Request(agent="reader-v1", system="sys", prompt="extract", schema={"type": "object"}, inputs={"pdf": "h"})
    old_key = req.key_for("gemini-3.8-flash")
    LLM(mode="replay", cache_dir=tmp_path, db=db, models={}).cache.put("reader-v1", old_key, {
        "key": old_key, "agent": "reader-v1", "model": "gemini-3.8-flash",
        "request": {"system": "sys", "prompt": "extract", "schema": {"type": "object"}, "inputs": {"pdf": "h"}},
        "response": {"output": {"claims": []}, "text": "{}", "tokens_in": 7, "tokens_out": 3}})

    llm = LLM(mode="replay", cache_dir=tmp_path, db=db, models={"fast": "gemini-flash-latest"})
    out = llm.call(req)
    assert out.output == {"claims": []} and out.mode == "replay"
    # logged honestly: the model and key of the recorded call, not the alias we asked for
    assert out.model == "gemini-3.8-flash" and out.key == old_key
    assert db.rows["llm_calls"][-1]["model"] == "gemini-3.8-flash"


def test_replay_does_not_match_a_different_prompt(tmp_path):
    import pytest
    from lab.llm import ReplayMiss

    db = FakeDB()
    llm = LLM(mode="replay", cache_dir=tmp_path, db=db, models={"fast": "m"})
    llm.cache.put("a", "k", {"key": "k", "agent": "a", "model": "old",
                             "request": {"system": "", "prompt": "other", "schema": None, "inputs": {}},
                             "response": {"output": "x", "text": "x", "tokens_in": 1, "tokens_out": 1}})
    with pytest.raises(ReplayMiss):
        llm.call(Request(agent="a", prompt="this"))
