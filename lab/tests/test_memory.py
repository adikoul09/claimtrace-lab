"""T17: research memory (SPEC §6): retrieval by tag overlap, lesson proposals kept only with evidence, the Round 0
import, and the memory effect (run 2 vs run 1) computed by code."""
import pytest

from lab.controller import memory


def lesson(id_, tags, kind="failure_fix", text="t"):
    return {"id": id_, "tags": tags, "kind": kind, "text": text, "created_at": f"2026-10-10T10:00:0{id_[-1]}Z"}


# ---- read ---------------------------------------------------------------------------------------------------------

def test_match_ranks_by_tag_overlap_and_drops_non_matching():
    ls = [lesson("l1", ["mnist", "write_code"]), lesson("l2", ["mnist", "distillation", "write_code"]),
          lesson("l3", ["slab"])]
    got = memory.match(ls, ["mnist", "distillation", "write_code"], limit=5)
    assert [l["id"] for l in got] == ["l2", "l1"]
    assert memory.match(ls, ["mnist", "write_code"], limit=1)[0]["id"] in ("l1", "l2")


def test_tags_for_a_task_cover_domain_capability_and_error_signature():
    tags = memory.task_tags({"tags": ["MNIST", "distillation"]}, "debug", "ModuleNotFoundError:torchvision")
    assert set(tags) >= {"mnist", "distillation", "debug", "ModuleNotFoundError:torchvision", "ModuleNotFoundError"}


def test_lessons_block_lists_each_lesson_with_its_id():
    block = memory.lessons_block([lesson("l1", [], text="Pin torch."), lesson("l2", [], text="Check the rule.")])
    assert "[l1] Pin torch." in block and "[l2] Check the rule." in block
    assert memory.lessons_block([]) == ""


# ---- write --------------------------------------------------------------------------------------------------------

def test_proposals_are_kept_only_with_real_evidence_and_a_valid_kind():
    props = [{"text": "Pin torch 2.4 on CPU", "tags": ["setup_env"], "evidence_event_id": "e1", "kind": "failure_fix"},
             {"text": "made up", "tags": ["x"], "evidence_event_id": "nope", "kind": "failure_fix"},
             {"text": "bad kind", "tags": ["x"], "evidence_event_id": "e1", "kind": "vibes"},
             {"text": "  ", "tags": ["x"], "evidence_event_id": "e1", "kind": "budget"},
             {"text": "no tags", "tags": [], "evidence_event_id": "e2", "kind": "budget"}]
    kept, dropped = memory.check_proposals(props, {"e1", "e2"})
    assert [k["text"] for k in kept] == ["Pin torch 2.4 on CPU"]
    assert len(dropped) == 4 and any("evidence" in d for d in dropped) and any("kind" in d for d in dropped)


def test_at_most_three_lessons_are_kept():
    props = [{"text": f"l{i}", "tags": ["x", f"t{i}"], "evidence_event_id": "e", "kind": "budget"} for i in range(5)]
    kept, dropped = memory.check_proposals(props, {"e"})
    assert len(kept) == memory.MAX_LESSONS == 3 and len(dropped) == 2


def test_recovery_is_a_failed_attempt_followed_by_a_done_one():
    tasks = [{"id": "a", "status": "failed", "created_at": "1", "input": {"step": 4}},
             {"id": "b", "status": "done", "created_at": "2", "input": {"step": 4}},
             {"id": "c", "status": "done", "created_at": "3", "input": {"step": 5}}]
    assert memory.recoveries(tasks) == [(4, "a", "b")]


# ---- Round 0 import -----------------------------------------------------------------------------------------------

def test_round0_lessons_are_labelled_and_point_at_the_report():
    ls = memory.ROUND0_LESSONS
    assert [l["finding"] for l in ls] == [f"F{i}" for i in range(1, 9)]
    for l in ls:
        assert l["text"].startswith("Imported from Round 0 audit")
        assert l["kind"] in memory.KINDS and "round0" in l["tags"] and l["evidence"]


# ---- memory effect (R14) ------------------------------------------------------------------------------------------

def run(id_, status, created, finished):
    return {"id": id_, "capability": "run", "status": status, "created_at": created, "finished_at": finished}


def test_effect_counts_retries_time_to_first_result_and_tokens():
    p1 = {"created_at": "2026-10-10T10:00:00+00:00"}
    t1 = [run("r1", "failed", "2026-10-10T10:01:00+00:00", "2026-10-10T10:02:00+00:00"),
          run("r2", "failed", "2026-10-10T10:03:00+00:00", "2026-10-10T10:04:00+00:00"),
          run("r3", "done", "2026-10-10T10:05:00+00:00", "2026-10-10T10:10:00+00:00")]
    p2 = {"created_at": "2026-10-10T12:00:00+00:00"}
    t2 = [run("s1", "done", "2026-10-10T12:01:00+00:00", "2026-10-10T12:04:00+00:00")]
    e = memory.effect(p1, t1, 9000, p2, t2, 6000)
    assert e["run1"] == {"retries_before_first_success": 2, "seconds_to_first_result": 600.0, "llm_tokens": 9000}
    assert e["run2"] == {"retries_before_first_success": 0, "seconds_to_first_result": 240.0, "llm_tokens": 6000}
    assert e["delta"] == {"retries_before_first_success": -2, "seconds_to_first_result": -360.0, "llm_tokens": -3000}


def test_effect_without_a_successful_run_says_so():
    e = memory.effect({"created_at": "2026-10-10T10:00:00+00:00"}, [run("r", "failed", "x", "y")], 10,
                      {"created_at": "2026-10-10T10:00:00+00:00"}, [], 0)
    assert e["run1"]["seconds_to_first_result"] is None and e["delta"]["seconds_to_first_result"] is None


# ---- MEM-1: lesson policy -----------------------------------------------------------------------------------------

def L(id_, kind, tags, paper=None, applied=0, evidence="e", created="2026-10-10T10:00:00Z"):
    return {"id": id_, "kind": kind, "tags": tags, "paper": paper, "times_applied": applied,
            "evidence_event_id": evidence, "created_at": created, "text": f"lesson {id_}"}


def test_select_ranks_by_overlap_then_times_applied():
    ls = [L("a", "failure_fix", ["write_code"], applied=5),
          L("b", "failure_fix", ["write_code", "ModuleNotFoundError"], applied=0),
          L("c", "budget", ["write_code"], applied=9)]
    chosen, skipped = memory.select(ls, ["write_code", "ModuleNotFoundError"], "1503.02531", limit=5)
    assert [l["id"] for l in chosen] == ["b", "c", "a"]
    assert skipped == []


def test_setting_mattered_lessons_apply_only_to_the_same_paper():
    ls = [L("same", "setting_mattered", ["design_experiment"], paper="1503.02531"),
          L("other", "setting_mattered", ["design_experiment"], paper="round0:matchdg"),
          L("unknown", "setting_mattered", ["design_experiment"], paper=None),
          L("fix", "failure_fix", ["design_experiment"], paper="round0:matchdg")]
    chosen, skipped = memory.select(ls, ["design_experiment"], "1503.02531", limit=5)
    assert {l["id"] for l in chosen} == {"same", "fix"}             # failure_fix carries across papers
    assert {(l["id"], code) for l, code, _ in skipped} == {("other", "other_paper"), ("unknown", "other_paper")}


def test_duplicates_by_kind_and_tags_keep_the_most_applied():
    ls = [L("x1", "failure_fix", ["setup_env", "torch"], applied=1),
          L("x2", "failure_fix", ["torch", "setup_env"], applied=4),
          L("y", "budget", ["setup_env", "torch"], applied=0)]           # same tags, other kind: not a duplicate
    chosen, skipped = memory.select(ls, ["setup_env"], "p", limit=5)
    assert {l["id"] for l in chosen} == {"x2", "y"}
    assert [(l["id"], code) for l, code, _ in skipped] == [("x1", "duplicate")]


def test_at_most_limit_lessons_and_the_rest_are_skipped_over_limit():
    ls = [L(f"l{i}", "failure_fix", ["write_code", f"t{i}"], applied=i) for i in range(7)]
    chosen, skipped = memory.select(ls, ["write_code"], "p", limit=5)
    assert len(chosen) == 5 and [l["id"] for l in chosen] == ["l6", "l5", "l4", "l3", "l2"]
    assert {(l["id"], code) for l, code, _ in skipped} == {("l1", "over_limit"), ("l0", "over_limit")}


def test_lessons_without_evidence_are_never_used():
    chosen, skipped = memory.select([L("n", "failure_fix", ["write_code"], evidence=None)], ["write_code"], "p", 5)
    assert chosen == [] and skipped[0][1] == "no_evidence"


def test_paper_key_of_a_lesson():
    assert memory.paper_key({"tags": ["round0", "f2"], "project_id": None}, {}) == "round0:matchdg"
    assert memory.paper_key({"tags": ["x"], "project_id": "p1"}, {"p1": "1503.02531"}) == "1503.02531"
    assert memory.paper_key({"tags": ["x"], "project_id": None}, {}) is None


def test_a_proposal_duplicating_an_existing_lesson_is_dropped():
    existing = [{"id": "old", "kind": "failure_fix", "tags": ["torch", "setup_env"]}]
    props = [{"text": "pin torch", "tags": ["setup_env", "torch"], "evidence_event_id": "e1", "kind": "failure_fix"}]
    kept, dropped = memory.check_proposals(props, {"e1"}, existing=existing)
    assert kept == [] and "duplicate of lesson old" in dropped[0]
