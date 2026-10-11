"""Seed averaging in the Analyst (HoO-B): a claim is graded on the mean over the project's experiments that map it with
the same config except the seed, and c3-vs-c2 is graded across experiments when both exist."""
import pytest

from lab.agents import analyst

BASE = "python train.py --data-dir ../../data --epochs 15 --subset 0"


def exp(id_, seed, cmap, extra="", status="done", whatif=None):
    cfg = {"cmd": f"{BASE} --seed {seed}{extra}", "claim_map": cmap}
    if whatif:
        cfg["whatif"] = whatif
    return {"id": id_, "status": status, "config": cfg}


DIST = {"teacher_mlp_compact": "c1", "distilled_student_mlp": "c3"}
HARD = {"teacher_mlp_compact": "c2"}


def test_the_config_key_ignores_only_the_seed():
    assert analyst.config_key({"cmd": f"{BASE} --seed 0"}) == analyst.config_key({"cmd": f"{BASE} --seed 7"})
    assert analyst.config_key({"cmd": f"{BASE} --seed 0"}) != \
        analyst.config_key({"cmd": f"{BASE} --seed 0 --set temperature=2"})
    assert analyst.config_key({}) is None


def test_the_seed_group_is_done_non_whatif_runs_of_the_same_config():
    me = exp("a", 0, DIST)
    exps = [me, exp("b", 1, DIST), exp("c", 2, DIST), exp("d", 3, DIST, status="failed"),
            exp("e", 4, DIST, whatif={"task_id": "w"}), exp("f", 0, DIST, extra=" --set temperature=2"),
            exp("g", 0, HARD, extra=" --set hidden_units.teacher=128")]
    assert [e["id"] for e in analyst.seed_group(me, exps)] == ["a", "b", "c"]


def test_pool_is_mean_and_sample_sd():
    p = analyst.pool([233, 230, 225])
    assert p["n"] == 3 and p["mean"] == pytest.approx(229.3333, abs=1e-3) and p["sd"] == pytest.approx(4.0415, abs=1e-3)
    assert analyst.pool([227]) == {"n": 1, "mean": 227, "sd": None, "values": [227]}


def test_comparable_groups_differ_only_by_seed_and_hidden_units():
    a = {"cmd": f"{BASE} --seed 0"}
    assert analyst.base_key(a) == analyst.base_key({"cmd": f"{BASE} --seed 2 --set hidden_units.teacher=128"})
    assert analyst.base_key(a) != analyst.base_key({"cmd": f"{BASE} --seed 0 --set temperature=2"})


CLAIMS = [{"id": "c1", "value": 67, "metric": "test errors", "unit": "errors", "direction": "lower_is_better",
           "whose": "oracle"},
          {"id": "c2", "value": 146, "metric": "test errors", "unit": "errors", "direction": "lower_is_better",
           "whose": "baseline"},
          {"id": "c3", "value": 74, "metric": "test errors", "unit": "errors", "direction": "lower_is_better",
           "whose": "method"}]


def test_cross_experiment_ordering_uses_both_groups_means():
    rows = analyst.cross_relative(CLAIMS, {"c3": analyst.pool([233, 230, 225])},
                                  {"c2": analyst.pool([261, 244, 200])}, margin=10)
    r = rows[0]
    assert r["claim"] == "c3 beats c2" and r["method"] == "c3" and r["baseline"] == "c2"
    assert r["ours_gap"] == pytest.approx(5.6667, abs=1e-3) and r["paper_gap"] == 72
    assert r["verdict"] == "Partially reproduced" and r["n"] == {"c3": 3, "c2": 3}
    worse = analyst.cross_relative(CLAIMS, {"c3": analyst.pool([255])}, {"c2": analyst.pool([227])}, margin=10)
    assert worse[0]["verdict"] == "Not reproduced"


def test_a_seed_averaged_row_says_n_seeds_and_carries_mean_and_sd():
    g = analyst.grade(CLAIMS, DIST, {"teacher_mlp_compact": {"value": 205, "log_line": 94},
                                     "distilled_student_mlp": {"value": 229.3333, "log_line": 95}}, 10, seeds=3)
    analyst.annotate_seeds(g, {"c1": analyst.pool([208, 206, 201]), "c3": analyst.pool([233, 230, 225])})
    c3 = next(r for r in g["claims"] if r["claim_id"] == "c3")
    assert c3["label"].endswith("(3 seeds)") and c3["n_seeds"] == 3 and c3["values"] == [233, 230, 225]
    item = next(i for i in analyst.verdict_items(g) if i["claim_id"] == "c3")
    assert item["n_seeds"] == 3 and item["sd"] == pytest.approx(4.0415, abs=1e-3)
    assert item["note"].startswith("(3 seeds: mean 229.3333 ± 4.0415 over 233, 230, 225)")
