"""T04: LLM wrapper (replay cache, llm_calls logging), fixed tool set, generic agent runtime. All offline: a scripted
provider stands in for the model and an in-memory table store stands in for Supabase."""
import json
from pathlib import Path

import pytest

from lab import llm as llm_mod
from lab.agents import runtime, tools
from lab.llm import LLM, LLMError, ReplayMiss, Request


class FakeDB:
    """Just enough of the supabase client for inserts and simple selects: db.table(t).insert(row).execute().data."""

    def __init__(self):
        self.rows: dict[str, list[dict]] = {}

    def table(self, name):
        return _Query(self, name)


class _Query:
    def __init__(self, db, name):
        self.db, self.name, self.op, self.payload = db, name, "select", None

    def insert(self, row):
        self.op, self.payload = "insert", row
        return self

    def select(self, *_):
        return self

    def overlaps(self, *_):
        return self

    def order(self, *_, **__):
        return self

    def limit(self, *_):
        return self

    def execute(self):
        store = self.db.rows.setdefault(self.name, [])
        if self.op == "insert":
            rows = self.payload if isinstance(self.payload, list) else [self.payload]
            store.extend(rows)
            return type("R", (), {"data": rows})()
        return type("R", (), {"data": list(store)})()


def scripted(outputs, tokens=(100, 20)):
    """A provider that answers with the given outputs in order, each costing `tokens` (in, out)."""
    it = iter(outputs)

    def provider(req, model):
        out = next(it)
        return {"output": out, "text": json.dumps(out), "tokens_in": tokens[0], "tokens_out": tokens[1],
                "models": [model]}
    return provider


@pytest.fixture
def fake_provider(monkeypatch):
    def install(outputs, tokens=(100, 20)):
        monkeypatch.setitem(llm_mod.PROVIDERS, "fake", scripted(outputs, tokens))
    return install


def agent_row(tools_=("read_file", "emit"), **budget):
    return {"id": None, "name": "test-agent", "role_prompt": "You are a test agent.", "tools": list(tools_),
            "budget": {"max_tokens": 10_000, "max_cpu_s": 60, "max_steps": 5, **budget}}


# ---- lab/llm.py -------------------------------------------------------------------------------------------------

def test_cache_key_depends_on_prompt_schema_model_and_inputs():
    base = Request(agent="a", prompt="p", schema={"type": "object"}, inputs={"f": "1"})
    assert base.key_for("m") == Request(agent="a", prompt="p", schema={"type": "object"}, inputs={"f": "1"}).key_for("m")
    assert base.key_for("m") != base.key_for("m2")
    assert base.key_for("m") != Request(agent="a", prompt="q", schema={"type": "object"}, inputs={"f": "1"}).key_for("m")
    assert base.key_for("m") != Request(agent="a", prompt="p", schema=None, inputs={"f": "1"}).key_for("m")
    assert base.key_for("m") != Request(agent="a", prompt="p", schema={"type": "object"}, inputs={"f": "2"}).key_for("m")


def test_live_call_is_cached_and_logged_to_llm_calls(tmp_path, fake_provider):
    fake_provider([{"answer": 42}], tokens=(300, 40))
    db = FakeDB()
    client = LLM(mode="live", provider="fake", cache_dir=tmp_path, db=db, models={"fast": "fake-fast"})
    resp = client.call(Request(agent="a", prompt="p", schema={"type": "object"}), agent_id="ag-1", task_id="t-1")
    assert resp.output == {"answer": 42} and resp.mode == "live"
    assert (resp.tokens_in, resp.tokens_out) == (300, 40)
    assert (tmp_path / "a" / f"{resp.key}.json").exists()
    assert db.rows["llm_calls"] == [{"agent_id": "ag-1", "task_id": "t-1", "model": "fake-fast", "tokens_in": 300,
                                     "tokens_out": 40, "mode": "live", "cache_key": resp.key}]


def test_replay_returns_the_recorded_response_and_logs_mode_replay(tmp_path, fake_provider):
    fake_provider([{"answer": 42}], tokens=(300, 40))
    req = Request(agent="a", prompt="p")
    LLM(mode="live", provider="fake", cache_dir=tmp_path, db=FakeDB(), models={"fast": "fake-fast"}).call(req)
    db = FakeDB()
    resp = LLM(mode="replay", provider="fake", cache_dir=tmp_path, db=db, models={"fast": "fake-fast"}).call(req)
    assert resp.output == {"answer": 42} and resp.mode == "replay"
    assert db.rows["llm_calls"][0]["mode"] == "replay"
    assert (db.rows["llm_calls"][0]["tokens_in"], db.rows["llm_calls"][0]["tokens_out"]) == (300, 40)


def test_replay_miss_raises_and_never_calls_the_provider(tmp_path, monkeypatch):
    def boom(req, model):
        raise AssertionError("provider must not be called in replay mode")
    monkeypatch.setitem(llm_mod.PROVIDERS, "fake", boom)
    client = LLM(mode="replay", provider="fake", cache_dir=tmp_path, db=FakeDB(), models={"fast": "fake-fast"})
    with pytest.raises(ReplayMiss):
        client.call(Request(agent="a", prompt="never recorded"))


def test_unknown_provider_and_mode_are_rejected(tmp_path):
    with pytest.raises(LLMError):
        LLM(mode="live", provider="nope", cache_dir=tmp_path, db=FakeDB())
    with pytest.raises(LLMError):
        LLM(mode="sometimes", provider="gemini", cache_dir=tmp_path, db=FakeDB())


def test_model_alias_resolves_from_settings(tmp_path):
    client = LLM(mode="replay", provider="gemini", cache_dir=tmp_path, db=FakeDB(),
                 models={"fast": "g-flash", "smart": "g-pro"})
    assert client.model_for("fast") == "g-flash" and client.model_for("smart") == "g-pro"
    assert client.model_for("explicit-model") == "explicit-model"


# ---- lab/agents/tools.py ----------------------------------------------------------------------------------------

@pytest.fixture
def workdir(tmp_path):
    d = tmp_path / "runs" / "abc"
    d.mkdir(parents=True)
    (d / "notes.txt").write_text("hello", encoding="utf-8")
    (tmp_path / "runs" / "abcd").mkdir()
    (tmp_path / "runs" / "abcd" / "secret.txt").write_text("other run", encoding="utf-8")
    (tmp_path / ".env").write_text("LLM_API_KEY=x", encoding="utf-8")
    return d


def test_file_tools_work_inside_the_run_dir(workdir):
    box = tools.ToolBox(workdir, allowed=["read_file", "write_file", "list_dir"], runs_root=workdir.parent)
    assert box.call("read_file", {"path": "notes.txt"}) == "hello"
    box.call("write_file", {"path": "sub/out.txt", "content": "x"})
    assert (workdir / "sub" / "out.txt").read_text(encoding="utf-8") == "x"
    assert "notes.txt" in box.call("list_dir", {"path": "."})


@pytest.mark.parametrize("path", ["../abcd/secret.txt", "../../.env", "sub/../../abcd/secret.txt"])
def test_file_tools_cannot_leave_the_run_dir(workdir, path):
    box = tools.ToolBox(workdir, allowed=["read_file", "write_file", "list_dir"], runs_root=workdir.parent)
    with pytest.raises(tools.ToolError):
        box.call("read_file", {"path": path})
    with pytest.raises(tools.ToolError):
        box.call("write_file", {"path": path, "content": "x"})


def test_absolute_paths_outside_the_run_dir_are_refused(workdir):
    box = tools.ToolBox(workdir, allowed=["read_file", "list_dir"], runs_root=workdir.parent)
    with pytest.raises(tools.ToolError):
        box.call("read_file", {"path": str(workdir.parent / "abcd" / "secret.txt")})
    with pytest.raises(tools.ToolError):
        box.call("list_dir", {"path": str(workdir.parent)})


def test_tool_not_granted_to_the_agent_is_refused(workdir):
    box = tools.ToolBox(workdir, allowed=["read_file"], runs_root=workdir.parent)
    with pytest.raises(tools.ToolError, match="not allowed"):
        box.call("write_file", {"path": "x.txt", "content": "x"})


def test_tools_outside_the_fixed_set_cannot_be_granted(workdir):
    with pytest.raises(tools.ToolError, match="fixed tool set"):
        tools.ToolBox(workdir, allowed=["read_file", "shell"], runs_root=workdir.parent)


def test_fixed_set_matches_spec():
    assert set(tools.FIXED_TOOLS) == {"fetch_paper", "fetch_repo", "read_file", "write_file", "list_dir",
                                      "make_env", "run", "query_memory", "emit"}


def test_run_dir_must_be_inside_runs(tmp_path):
    with pytest.raises(tools.ToolError):
        tools.ToolBox(tmp_path, allowed=["read_file"], runs_root=tmp_path)
    with pytest.raises(tools.ToolError):
        tools.ToolBox(tmp_path / "elsewhere", allowed=["read_file"], runs_root=tmp_path / "runs")


# ---- lab/agents/runtime.py --------------------------------------------------------------------------------------

def test_action_schema_declares_the_granted_tools_arguments():
    # Gemini's structured output only fills declared properties; a bare {"type": "object"} comes back empty.
    args = runtime.action_schema(["read_file", "write_file"])["properties"]["args"]["properties"]
    assert set(args) == {"path", "content"}
    assert runtime.action_schema(["read_file", "write_file"])["properties"]["action"]["enum"] == \
        ["read_file", "write_file", "finish"]


def make_llm(tmp_path, db):
    return LLM(mode="live", provider="fake", cache_dir=tmp_path / "cache", db=db, models={"fast": "fake-fast"})


def events(db, type_=None):
    return [e for e in db.rows.get("events", []) if type_ is None or e["type"] == type_]


def test_agent_reads_a_file_and_finishes(workdir, fake_provider):
    fake_provider([
        {"action": "read_file", "args": {"path": "notes.txt"}, "reason": "need the file"},
        {"action": "finish", "answer": "The file says hello.", "reason": "done"},
    ])
    db = FakeDB()
    res = runtime.run_agent(agent_row(), "Summarise notes.txt", workdir, db=db,
                            runs_root=workdir.parent, llm=make_llm(workdir.parent, db))
    assert res.status == "finished" and res.answer == "The file says hello."
    assert res.steps == 2 and res.tokens == 240
    assert "hello" in res.transcript[0]["observation"]
    assert len(db.rows["llm_calls"]) == 2
    assert [e["type"] for e in events(db)] == ["agent_started", "agent_tool", "agent_finished"]
    assert all(e["reason"] for e in events(db))


def test_runtime_stops_at_max_steps(workdir, fake_provider):
    fake_provider([{"action": "list_dir", "args": {"path": "."}, "reason": "look"}] * 10)
    db = FakeDB()
    res = runtime.run_agent(agent_row(tools_=("list_dir",), max_steps=3), "loop", workdir, db=db,
                            runs_root=workdir.parent, llm=make_llm(workdir.parent, db))
    assert res.status == "stopped" and res.steps == 3
    stop = events(db, "agent_stopped")[0]
    assert "max_steps" in stop["reason"] and "3" in stop["reason"]


def test_runtime_stops_at_max_tokens(workdir, fake_provider):
    fake_provider([{"action": "list_dir", "args": {"path": "."}, "reason": "look"}] * 10, tokens=(400, 100))
    db = FakeDB()
    res = runtime.run_agent(agent_row(tools_=("list_dir",), max_tokens=1200), "loop", workdir, db=db,
                            runs_root=workdir.parent, llm=make_llm(workdir.parent, db))
    assert res.status == "stopped" and res.tokens == 1500 and res.steps == 3
    assert "max_tokens" in events(db, "agent_stopped")[0]["reason"]


def test_runtime_stops_at_max_cpu_s(workdir, fake_provider, monkeypatch):
    fake_provider([{"action": "list_dir", "args": {"path": "."}, "reason": "look"}] * 10)
    clock = iter(range(0, 1000, 25))  # every reading of the CPU clock advances 25 s
    monkeypatch.setattr(runtime, "cpu_clock", lambda: next(clock))
    db = FakeDB()
    res = runtime.run_agent(agent_row(tools_=("list_dir",), max_cpu_s=60), "loop", workdir, db=db,
                            runs_root=workdir.parent, llm=make_llm(workdir.parent, db))
    assert res.status == "stopped"
    assert "max_cpu_s" in events(db, "agent_stopped")[0]["reason"]


def test_disallowed_tool_is_reported_back_not_run(workdir, fake_provider):
    fake_provider([
        {"action": "write_file", "args": {"path": "x.txt", "content": "x"}, "reason": "try"},
        {"action": "finish", "answer": "ok", "reason": "done"},
    ])
    db = FakeDB()
    res = runtime.run_agent(agent_row(tools_=("read_file",)), "go", workdir, db=db,
                            runs_root=workdir.parent, llm=make_llm(workdir.parent, db))
    assert not (workdir / "x.txt").exists()
    assert "not allowed" in res.transcript[0]["observation"]
    assert res.status == "finished"


def test_llm_failure_ends_the_run_with_a_reason(workdir, tmp_path):
    db = FakeDB()
    client = LLM(mode="replay", provider="fake", cache_dir=tmp_path / "empty", db=db, models={"fast": "fake-fast"})
    res = runtime.run_agent(agent_row(), "go", workdir, db=db, runs_root=workdir.parent, llm=client)
    assert res.status == "failed"
    assert "ReplayMiss" in events(db, "agent_failed")[0]["reason"]
