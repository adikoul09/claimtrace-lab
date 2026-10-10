"""T16: lifecycle rules (SPEC §4.1 refine, §4.2 retire, §4.4 merge). Code decides; events carry the numbers."""
import pytest

from lab.controller import lifecycle
from lab.controller.rules import MERGE_OVERLAP, MIN_SCORED, RETIRE_BELOW


def agent(id_, name, caps, version=1, status="active", max_tokens=20_000, tools=("read_file", "emit")):
    return {"id": id_, "name": name, "capabilities": list(caps), "tools": list(tools), "status": status,
            "version": version, "role_prompt": f"You are {name}.", "budget": {"max_tokens": max_tokens,
                                                                                "max_cpu_s": 60, "max_steps": 5}}


def rewards(agent_id, values):
    return [{"agent_id": agent_id, "task_id": f"{agent_id}-t{i}", "reward": v, "ts": f"2026-10-10T10:0{i}:00Z"}
            for i, v in enumerate(values)]


def test_thresholds_are_the_spec_values():
    assert (RETIRE_BELOW, MERGE_OVERLAP, MIN_SCORED) == (0.35, 0.8, 3)


# ---- 4.2 retire ---------------------------------------------------------------------------------------------------

def test_retire_when_the_mean_of_the_last_three_is_below_the_threshold():
    a = [agent("a", "reader-v1", ["read_paper"]), agent("b", "designer-v1", ["design_experiment"])]
    r = rewards("a", [0.9, 0.3, 0.3, 0.3]) + rewards("b", [0.3, 0.9, 0.3])
    out = lifecycle.retire_candidates(a, r)
    assert [c.agent["id"] for c in out] == ["a"]
    assert "0.30" in out[0].reason and "0.35" in out[0].reason and "3" in out[0].reason


def test_no_retire_with_fewer_than_three_scored_tasks_or_when_inactive():
    a = [agent("a", "x-v1", ["run"]), agent("b", "y-v1", ["run"], status="retired")]
    assert lifecycle.retire_candidates(a, rewards("a", [0.0, 0.0]) + rewards("b", [0, 0, 0])) == []


def test_mean_exactly_at_the_threshold_is_kept():
    assert lifecycle.retire_candidates([agent("a", "x-v1", ["run"])], rewards("a", [0.35, 0.35, 0.35])) == []


# ---- 4.4 merge ----------------------------------------------------------------------------------------------------

def test_overlap_is_shared_tags_over_all_tags():
    assert lifecycle.overlap(["a", "b", "c", "d", "e"], ["a", "b", "c", "d", "e", "f"]) == pytest.approx(5 / 6)
    assert lifecycle.overlap(["a", "b"], ["a"]) == pytest.approx(0.5)


def test_merge_the_lower_scored_of_two_overlapping_agents():
    caps = ["compare", "explain_diff", "write_report", "write_notes", "budget"]
    a = [agent("a", "analyst-v1", caps), agent("b", "analyst2-v1", caps + ["design_whatif"], tools=("run",))]
    r = rewards("a", [0.9, 0.8, 0.7]) + rewards("b", [0.5, 0.6, 0.5])
    out = lifecycle.merge_candidates(a, r)
    assert len(out) == 1
    m = out[0]
    assert m.winner["id"] == "a" and m.loser["id"] == "b"
    assert "0.83" in m.reason and "0.80" in m.reason
    row = lifecycle.merged_version(m.winner, m.loser, m.reason)
    assert set(row["capabilities"]) == set(caps) | {"design_whatif"}
    assert set(row["tools"]) == {"read_file", "emit", "run"}
    assert row["name"] == "analyst-v2" and row["version"] == 2 and row["parent_id"] == "a"
    assert row["origin"] == "refined"


def test_no_merge_below_the_overlap_or_without_three_scored_tasks_each():
    a = [agent("a", "a-v1", ["x", "y"]), agent("b", "b-v1", ["x", "z"])]
    assert lifecycle.merge_candidates(a, rewards("a", [1, 1, 1]) + rewards("b", [0, 0, 0])) == []
    same = [agent("a", "a-v1", ["x"]), agent("b", "b-v1", ["x"])]
    assert lifecycle.merge_candidates(same, rewards("a", [1, 1, 1]) + rewards("b", [0, 0])) == []


def test_an_agent_merges_at_most_once_per_pass():
    caps = ["x"]
    a = [agent("a", "a-v1", caps), agent("b", "b-v1", caps), agent("c", "c-v1", caps)]
    r = rewards("a", [0.9] * 3) + rewards("b", [0.6] * 3) + rewards("c", [0.5] * 3)
    out = lifecycle.merge_candidates(a, r)
    ids = [x for m in out for x in (m.winner["id"], m.loser["id"])]
    assert len(ids) == len(set(ids))


# ---- 4.1 refine ---------------------------------------------------------------------------------------------------

def done(tid, agent_id, outcome=None, status="done"):
    return {"id": tid, "agent_id": agent_id, "status": status, "capability": "write_code",
            "output": {"outcome": outcome} if outcome else {"agent_status": "finished"}}


def test_refine_on_a_failed_acceptance_check_or_a_thumbs_down():
    a = [agent("a", "implementer-v1", ["write_code"]), agent("b", "reader-v1", ["read_paper"])]
    tasks = [done("t1", "a", outcome="failed"), done("t2", "b"), done("t3", "b", outcome="passed")]
    out = lifecycle.refine_triggers(a, tasks, {"t3": "down"}, already=set())
    got = {(t.agent["id"], t.task["id"]) for t in out}
    assert got == {("a", "t1"), ("b", "t3")}
    reasons = {t.task["id"]: t.reason for t in out}
    assert "acceptance check" in reasons["t1"] and "👎" in reasons["t3"]


def test_refine_skips_code_only_agents_inactive_agents_and_done_refinements():
    a = [agent("r", "runner-v1", ["run"], max_tokens=0), agent("x", "old-v1", ["write_code"], status="retired"),
         agent("i", "implementer-v1", ["write_code"])]
    tasks = [done("t1", "r", outcome="failed"), done("t2", "x", outcome="failed"), done("t3", "i", outcome="failed")]
    assert lifecycle.refine_triggers(a, tasks, {}, already={("i", "t3")}) == []


def test_one_refinement_per_agent_per_pass():
    a = [agent("i", "implementer-v1", ["write_code"])]
    tasks = [done("t1", "i", outcome="failed"), done("t2", "i", outcome="failed")]
    assert len(lifecycle.refine_triggers(a, tasks, {}, already=set())) == 1


def test_refined_version_keeps_tools_caps_budget_and_links_the_parent():
    old = agent("i", "implementer-v1", ["write_code"], version=1)
    row = lifecycle.refined_version(old, "You are implementer. Lesson: pin torch.", "t1 failed its check", "t1")
    assert row["name"] == "implementer-v2" and row["version"] == 2 and row["parent_id"] == "i"
    assert row["origin"] == "refined" and row["created_by_task"] == "t1"
    assert row["capabilities"] == old["capabilities"] and row["tools"] == old["tools"]
    assert row["budget"] == old["budget"] and row["role_prompt"].endswith("pin torch.")


def test_refined_prompt_must_keep_a_debuggers_repair_policy():
    from lab.controller.spawn import REPAIR_POLICY
    old = agent("d", "debugger-v1", ["debug"])
    old["role_prompt"] = "You fix crashes." + REPAIR_POLICY
    row = lifecycle.refined_version(old, "You fix crashes better.", "r", "t")
    assert REPAIR_POLICY.strip() in row["role_prompt"]


def test_an_empty_refined_prompt_is_refused():
    with pytest.raises(ValueError):
        lifecycle.refined_version(agent("i", "i-v1", ["x"]), "  ", "r", "t")


def test_version_names():
    assert lifecycle.next_name("reader-v1", 1) == "reader-v2"
    assert lifecycle.next_name("crash-debugger-2-v3", 3) == "crash-debugger-2-v4"
    assert lifecycle.next_name("odd", 1) == "odd-v2"


def test_code_only_agents_are_exempt_from_retire():
    a = [agent("r", "runner-v1", ["run"], max_tokens=0), agent("i", "implementer-v1", ["write_code"])]
    r = rewards("r", [0.3, 0.3, 0.3]) + rewards("i", [0.3, 0.3, 0.3])
    assert [c.agent["id"] for c in lifecycle.retire_candidates(a, r)] == ["i"]
