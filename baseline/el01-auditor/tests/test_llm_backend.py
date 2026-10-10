"""LLM backend: cache keys, replay, the usage log, and the `claude -p` call (against a fake `claude` script)."""
import json
import os
import stat
import sys

import pytest

from el01.llm.backend import AGENT_TOOLS, LLM, ReplayMiss, Request, claude_argv
from el01.llm.cache import cache_key

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}


def test_cache_key_stable_and_sensitive():
    k = cache_key("a", "p", SCHEMA, "sonnet", {"x": "1", "y": "2"})
    assert k == cache_key("a", "p", SCHEMA, "sonnet", {"y": "2", "x": "1"})
    for other in (cache_key("b", "p", SCHEMA, "sonnet", {"x": "1", "y": "2"}),
                  cache_key("a", "p ", SCHEMA, "sonnet", {"x": "1", "y": "2"}),
                  cache_key("a", "p", None, "sonnet", {"x": "1", "y": "2"}),
                  cache_key("a", "p", SCHEMA, "opus", {"x": "1", "y": "2"}),
                  cache_key("a", "p", SCHEMA, "sonnet", {"x": "1", "y": "3"})):
        assert other != k


def test_replay_miss_is_an_error_and_logged(tmp_path):
    llm = LLM("replay", cache_dir=tmp_path / "c", usage_log=tmp_path / "u.jsonl")
    with pytest.raises(ReplayMiss, match="--llm live"):
        llm.call(Request("t", "hello", SCHEMA))
    (line,) = [json.loads(l) for l in (tmp_path / "u.jsonl").read_text().splitlines()]
    assert line["cache"] == "miss" and line["backend"] == "replay" and line["error"]


FAKE = r'''#!{py}
import json, os, sys
args = sys.argv[1:]
if args == ["--version"]:
    print("9.9.9 (Claude Code)"); sys.exit(0)
prompt = sys.stdin.read()
with open(os.environ["FAKE_CLAUDE_LOG"], "a") as f:
    f.write(json.dumps({{"argv": args, "cwd": os.getcwd(), "prompt": prompt,
                        "repo": sorted(os.listdir("repo")) if os.path.isdir("repo") else None,
                        "api_key": "ANTHROPIC_API_KEY" in os.environ}}) + "\n")
print(json.dumps({{"type": "result", "subtype": "success", "is_error": False, "result": '{{"ok": true}}',
                  "structured_output": {{"ok": True}}, "usage": {{"input_tokens": 3, "output_tokens": 5}},
                  "total_cost_usd": 0.01, "duration_ms": 12, "num_turns": 2,
                  "modelUsage": {{"claude-sonnet-5-5": {{}}}}, "session_id": "s"}}))
'''


@pytest.fixture
def fake_claude(tmp_path, monkeypatch):
    exe = tmp_path / "claude"
    exe.write_text(FAKE.format(py=sys.executable))
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "calls.jsonl"
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(log))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-reach-the-cli")
    return exe, log


def test_claude_cli_call_cache_and_replay(tmp_path, fake_claude):
    exe, log = fake_claude
    repo = tmp_path / "snap"
    repo.mkdir()
    (repo / "train.py").write_text("print(1)\n")
    req = Request("repair", "fix it", SCHEMA, "sonnet", {"repo_tree": "abc"}, AGENT_TOOLS, repo_copy=repo,
                  max_turns=7)
    llm = LLM("claude_cli", cache_dir=tmp_path / "c", usage_log=tmp_path / "u.jsonl", claude=str(exe))
    r = llm.call(req)
    assert r.output == {"ok": True} and r.cache == "miss"
    (call,) = [json.loads(l) for l in log.read_text().splitlines()]
    assert call["prompt"] == "fix it" and call["repo"] == ["train.py"] and call["api_key"] is False
    assert os.path.basename(call["cwd"]).startswith("el01-agent-") and not os.path.exists(call["cwd"])
    a = call["argv"]
    for flag in ("-p", "--no-session-persistence", "--safe-mode", "--restricted", "--strict-mcp-config"):
        assert flag in a
    assert a[a.index("--model") + 1] == "sonnet" and a[a.index("--max-turns") + 1] == "7"
    assert a[a.index("--tools") + 1] == "Read,Grep,Glob" == a[a.index("--allowedTools") + 1]
    assert json.loads(a[a.index("--json-schema") + 1]) == SCHEMA
    assert a[a.index("--output-format") + 1] == "json"
    # the second call is a cache hit, also in replay mode: no new subprocess
    assert llm.call(req).cache == "hit"
    replay = LLM("replay", cache_dir=tmp_path / "c", usage_log=tmp_path / "u.jsonl")
    assert replay.call(req).output == {"ok": True}
    assert len(log.read_text().splitlines()) == 1
    lines = [json.loads(l) for l in (tmp_path / "u.jsonl").read_text().splitlines()]
    assert [l["cache"] for l in lines] == ["miss", "hit", "hit"]
    assert lines[0]["cli_version"] == "9.9.9" and lines[0]["total_cost_usd"] == 0.01
    assert lines[0]["models"] == ["claude-sonnet-5-5"] and lines[0]["usage"]["output_tokens"] == 5
    rec = json.loads(next((tmp_path / "c" / "repair").glob("*.json")).read_text())
    assert rec["request"]["prompt"] == "fix it" and rec["backend"] == "claude_cli"


def test_tool_less_argv():
    a = claude_argv(Request("x", "p"))
    assert a[a.index("--tools") + 1] == "" and "--allowedTools" not in a and "--json-schema" not in a


def test_spend_cap_refuses_a_live_call(tmp_path):
    import json as _json
    from el01.llm.backend import LLM, LLMError, Request
    from el01.llm.budget import Cap, spent
    log = tmp_path / "usage.jsonl"
    log.write_text(_json.dumps({"tag": "phase6", "cache": "miss", "total_cost_usd": 11.8}) + "\n" +
                   _json.dumps({"tag": "phase5", "cache": "miss", "total_cost_usd": 9.0}) + "\n" +
                   _json.dumps({"tag": "phase6", "cache": "hit", "total_cost_usd": 3.0}) + "\n")
    assert spent(log, "phase6") == 11.8
    llm = LLM("claude_cli", cache_dir=tmp_path / "c", usage_log=log, claude="/nonexistent/claude", tag="phase6",
              guard=Cap(log, 12.0, "phase6"))
    with pytest.raises(LLMError, match="spend cap"):
        llm.call(Request(agent="code_extractor", prompt="p"))
