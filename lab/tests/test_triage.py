"""ANY-1: for any paper, code tags every claim runnable | not_runnable from facts the Reader extracted (the LLM states
facts only; these rules decide)."""
from lab.agents import reproduce as rp
from lab.agents import triage as tr


def claim(cid, value=1.0, model="net", whose="method"):
    return {"id": cid, "value": value, "model": model, "metric": "test errors", "unit": "errors",
            "direction": "lower_is_better", "whose": whose, "valid": True, "quote": f"{value}", "page": 4}


def exp(ids, **facts):
    return {"claim_ids": ids, **{k: None for k in tr.FACT_KEYS}, **facts}


def tags(claims, experiments, cap_min=20):
    return {c["id"]: c["runnable"] for c in tr.triage(claims, experiments, cap_min)}


def test_small_public_dataset_is_runnable_with_the_reason():
    t = tags([claim("c1")], [exp(["c1"], dataset="MNIST", dataset_public=True, train_examples=60000)])
    assert t["c1"]["status"] == "runnable" and "MNIST" in t["c1"]["reason"]
    assert t["c1"]["facts"]["dataset"] == "MNIST"


def test_private_dataset_is_not_runnable():
    t = tags([claim("c1")], [exp(["c1"], dataset="JFT (100 million images)", dataset_public=False)])
    assert t["c1"] == {**t["c1"], "status": "not_runnable"} and "no public data" in t["c1"]["reason"]


def test_too_big_dataset_is_not_runnable_with_its_numbers():
    t = tags([claim("c1"), claim("c2")],
             [exp(["c1"], dataset="speech", dataset_public=True, dataset_size_gb=500),
              exp(["c2"], dataset="speech", dataset_public=True, train_examples=700_000_000)])
    assert t["c1"]["status"] == t["c2"]["status"] == "not_runnable"
    assert "dataset too big" in t["c1"]["reason"] and "500" in t["c1"]["reason"]
    assert "700000000" in t["c2"]["reason"].replace(",", "")


def test_gpu_on_a_large_task_is_not_runnable_but_gpu_on_a_small_dataset_is():
    t = tags([claim("c1"), claim("c2")],
             [exp(["c1"], dataset="ImageNet", dataset_public=True, needs_gpu=True, hardware="8 GPUs"),
              exp(["c2"], dataset="MNIST", dataset_public=True, needs_gpu=True, hardware="one GPU")])
    assert t["c1"]["status"] == "not_runnable" and "needs GPU" in t["c1"]["reason"]
    assert t["c2"]["status"] == "runnable" and "small enough" in t["c2"]["reason"]


def test_compute_over_the_budget_is_not_runnable():
    t = tags([claim("c1"), claim("c2")],
             [exp(["c1"], dataset="CIFAR-10", dataset_public=True, gpu_hours=100),
              exp(["c2"], dataset="CIFAR-10", dataset_public=True, params_millions=300)], cap_min=20)
    assert t["c1"]["status"] == "not_runnable" and "compute over budget" in t["c1"]["reason"]
    assert t["c2"]["status"] == "not_runnable" and "300" in t["c2"]["reason"]


def test_no_public_code_does_not_block_and_unknown_facts_say_so():
    t = tags([claim("c1"), claim("c2")], [exp(["c1"], dataset="MNIST", dataset_public=True, code_public=False)])
    assert t["c1"]["status"] == "runnable" and "code" in t["c1"]["reason"]
    assert t["c2"]["status"] == "runnable" and "no blocker stated" in t["c2"]["reason"]


def test_designer_sees_only_runnable_claims_and_code_rejects_the_others():
    claims = tr.triage([claim("c1", 74), claim("c2", 25.0, model="JFT baseline")],
                       [exp(["c1"], dataset="MNIST", dataset_public=True),
                        exp(["c2"], dataset="JFT", dataset_public=False)], 20)
    goal = rp.designer_goal(claims, [], 20)
    assert "c1 |" in goal and "c2 |" not in goal
    try:
        rp.check_design({"experiment": "x", "models": [{"name": "m", "claim_id": "c2"}]}, claims)
        raise AssertionError("a not_runnable claim was accepted")
    except rp.StepError as e:
        assert "not runnable" in str(e) and "no public data" in str(e)
