"""T18 controller sequencing (docs/CONTRACTS.md §5b): branch smoke runs → ranking compare → approval-gated extend run →
post-extend compare. Pure functions; no Supabase."""
import pytest

from lab.controller import whatif

WHATIF = {"id": "w1", "project_id": "p", "status": "done", "input": {"question": "q", "upstream": {"run": "full"}},
          "output": {"branches": [
              {"id": "b1", "key": "lr", "value": 0.1, "parent_value": 0.03, "reason": "r", "scale": "smoke",
               "cwd": "runs/p/whatif/w1-b1", "cmd": "python train.py --set lr=0.1",
               "experiment": {"label": "what-if b1", "parent_id": "e0", "changed_key": "lr", "margin": 10,
                              "config": {"claim_map": {"t": "c1"}, "whatif": {"task_id": "w1", "branch_id": "b1"}}}},
              {"id": "b2", "key": "T", "value": 5, "parent_value": 20, "reason": "r", "scale": "smoke",
               "cwd": "runs/p/whatif/w1-b2", "cmd": "python train.py --set T=5",
               "experiment": {"label": "what-if b2", "parent_id": "e0", "changed_key": "T", "margin": 10,
                              "config": {"whatif": {"task_id": "w1", "branch_id": "b2"}}}}],
              "parent_experiment_id": "e0"}}
FULL = {"id": "full", "status": "done", "input": {"files": {"train.py": "code"}, "requirements": "torch==2.4.0",
                                                   "timeout_s": 900, "scale": "full", "experiment_id": "e0"}}
SMOKE = {"id": "smoke", "status": "done", "input": {"timeout_s": 400, "scale": "smoke"}}


def branch_run(bid, status="done", ts="2026-10-10T10:00:00Z"):
    return {"id": f"run-{bid}", "capability": "run", "status": status, "created_at": ts,
            "input": {"whatif_of": "w1", "branch_id": bid, "scale": "smoke"}}


def rank(status="done", extend=None):
    return {"id": "rank", "capability": "compare", "status": status, "created_at": "2026-10-10T11:00:00Z",
            "input": {"whatif_of": "w1", "whatif_task_id": "w1"},
            "output": {"extend": extend, "ranking": [{"id": "b1", "decision": "extend"}]}}


EXTEND = {"branch_id": "b1", "key": "lr", "value": 0.1, "reason": "largest effect", "smoke_experiment_id": "eb1",
          "cwd": "runs/p/whatif/w1-b1", "scale": "full", "cmd": "python train.py --epochs 5 --set lr=0.1",
          "experiment": {"label": "what-if b1 (full)", "parent_id": "e0", "changed_key": "lr", "margin": 10,
                         "config": {"scale": "full", "whatif": {"task_id": "w1", "branch_id": "b1"}}}}


def ext_run(status="done"):
    return {"id": "ext", "capability": "run", "status": status, "created_at": "2026-10-10T12:00:00Z",
            "decision": "reject" if status == "rejected" else None, "decision_note": None,
            "input": {"whatif_of": "w1", "branch_id": "b1", "extend_of": "rank", "experiment_id": "eext",
                      "scale": "full"}, "output": {"error_signature": "RuntimeError:nan"} if status == "failed" else {}}


def final(status="done"):
    return {"id": "fin", "capability": "compare", "status": status, "created_at": "2026-10-10T13:00:00Z",
            "input": {"whatif_of": "w1", "extend_experiment_id": "eext"}, "output": {}}


# ---- the state machine --------------------------------------------------------------------------------------------

def test_first_every_branch_gets_a_smoke_run():
    kind, branches = whatif.next_action(WHATIF, [])
    assert kind == "branches" and [b["id"] for b in branches] == ["b1", "b2"]
    kind, branches = whatif.next_action(WHATIF, [branch_run("b1")])
    assert kind == "branches" and [b["id"] for b in branches] == ["b2"]   # only the missing one


def test_ranking_waits_for_every_branch_smoke():
    assert whatif.next_action(WHATIF, [branch_run("b1"), branch_run("b2", "running")]) == ("wait", None)
    assert whatif.next_action(WHATIF, [branch_run("b1"), branch_run("b2", "failed")]) == ("rank", None)


def test_extend_after_the_ranking_then_the_final_compare():
    fam = [branch_run("b1"), branch_run("b2")]
    assert whatif.next_action(WHATIF, fam + [rank("running")]) == ("wait", None)
    assert whatif.next_action(WHATIF, fam + [rank(extend=EXTEND)]) == ("extend", EXTEND)
    assert whatif.next_action(WHATIF, fam + [rank(extend=EXTEND), ext_run("awaiting_approval")]) == ("wait", None)
    kind, ext = whatif.next_action(WHATIF, fam + [rank(extend=EXTEND), ext_run()])
    assert kind == "final" and ext["id"] == "ext"
    assert whatif.next_action(WHATIF, fam + [rank(extend=EXTEND), ext_run(), final("queued")]) == ("wait", None)
    kind, why = whatif.next_action(WHATIF, fam + [rank(extend=EXTEND), ext_run(), final()])
    assert kind == "finished" and "graded" in why


@pytest.mark.parametrize("family,words", [
    ([branch_run("b1"), branch_run("b2"), rank(extend=None)], "no branch"),
    ([branch_run("b1"), branch_run("b2"), rank("failed")], "ranking"),
    ([branch_run("b1"), branch_run("b2"), rank(extend=EXTEND), ext_run("rejected")], "rejected"),
    ([branch_run("b1"), branch_run("b2"), rank(extend=EXTEND), ext_run("failed")], "RuntimeError:nan"),
], ids=["nothing-to-extend", "ranking-failed", "extend-rejected", "extend-crashed"])
def test_the_what_if_finishes_with_a_reason(family, words):
    kind, why = whatif.next_action(WHATIF, family)
    assert kind == "finished" and words in why


def test_a_what_if_without_branches_finishes():
    kind, why = whatif.next_action({**WHATIF, "output": {"branches": []}}, [])
    assert kind == "finished" and "no branches" in why


# ---- task inputs --------------------------------------------------------------------------------------------------

def test_branch_experiment_row_is_the_branch_experiment_as_given():
    b = WHATIF["output"]["branches"][0]
    row = whatif.experiment_row(b["experiment"], "p")
    assert row == {"project_id": "p", "label": "what-if b1", "parent_id": "e0", "changed_key": "lr", "margin": 10,
                   "config": b["experiment"]["config"], "status": "planned"}


def test_branch_run_input_takes_code_and_env_from_the_reproductions_full_run():
    b = WHATIF["output"]["branches"][0]
    inp = whatif.branch_input(b, "exp-b1", FULL, SMOKE, "w1")
    assert inp["cmd"] == b["cmd"] and inp["cwd"] == b["cwd"] and inp["scale"] == "smoke"
    assert inp["files"] == {"train.py": "code"} and inp["requirements"] == "torch==2.4.0"
    assert inp["experiment_id"] == "exp-b1" and inp["timeout_s"] == 400 and inp["network"] is True
    assert inp["whatif_of"] == "w1" and inp["branch_id"] == "b1" and "whatif_task_id" not in inp


def test_extend_run_input_is_the_full_scale_branch():
    inp = whatif.extend_input(EXTEND, "exp-ext", FULL, "w1", "rank")
    assert inp["cmd"] == EXTEND["cmd"] and inp["scale"] == "full" and inp["timeout_s"] == 900
    assert inp["extend_of"] == "rank" and inp["branch_id"] == "b1" and inp["files"] == {"train.py": "code"}


def test_ranking_and_final_compare_inputs_follow_the_contract():
    r = whatif.rank_input(WHATIF, "runs/p")
    assert r["whatif_task_id"] == "w1" and r["whatif_of"] == "w1" and "extend_experiment_id" not in r
    assert r["upstream"]["design_whatif"] == "w1" and r["upstream"]["run"] == "full"
    f = whatif.final_input(WHATIF, ext_run(), "runs/p")
    assert f["extend_experiment_id"] == "eext" and "whatif_task_id" not in f and f["whatif_of"] == "w1"
    assert f["upstream"]["run"] == "ext"


def test_a_what_if_can_start_only_after_the_reproductions_full_run():
    assert whatif.ready_problem({"run": "full"}, {"full": FULL}) is None
    assert "full run" in whatif.ready_problem({}, {})
    assert "full run" in whatif.ready_problem({"run": "smoke"}, {"smoke": SMOKE})
