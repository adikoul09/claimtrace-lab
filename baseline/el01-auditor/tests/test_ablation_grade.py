"""The ablation grader is a port of grade.py: driven by a plan that lists the spike's own branches, methods and seeds,
it must give the spike's effects, Holm values and confirmation exactly (the plan below is the test's, not the code's)."""
import pytest

from el01.grade import ablation

SPIKE_ARMS = ["h_select_valloss", "h_select_valloss_total", "h_omission_plain_sgd", "h_plain_sgd_1000ep",
              "h_combined", "naive_target_0.9_3m", "h_omission_constant_penalty", "h_dann_lr"]
METHODS = ("erm", "rand", "perf", "dann", "c-dann")
SKIP = {("h_select_valloss_total", "erm")}


def _plan(parsed, run_set="spike"):
    m = parsed["metrics"]
    fam = [[a, k] for a in SPIKE_ARMS if m.get(a) for k in METHODS
           if k in m[a] and "target" in m[a][k] and k in m["paper_target_1.0"] and (a, k) not in SKIP]
    arms = {a: {"commit": m[a]["commit"] or "", "label": a, "methods": sorted({k for x, k in fam if x == a})}
            for a in SPIKE_ARMS if m.get(a)}
    arms["paper_target_1.0"] = {"commit": m["paper_target_1.0"]["commit"], "methods": list(METHODS)}
    return {"run_set": run_set, "baseline": "paper_target_1.0", "seeds": list(range(10)),
            "seeds_graded": list(range(10)), "arms": arms, "family": fam}


def test_effects_equal_the_spike(parsed, graded_legacy):
    plan = _plan(parsed)
    g = ablation.grade_family([plan], {"spike": parsed["metrics"]}, {"spike": parsed["epochs"]})
    want = graded_legacy["table1"]["effects"]
    assert g["family_size"] == 20 == sum(len([k for k in d if k != "label"]) for d in want.values())
    keys = ("branch_mean", "effect", "ci", "p", "p_holm", "survives_holm", "detectable", "selected_epoch_median",
            "source_val_acc", "last_epoch_target", "last_epoch_source_val")
    for arm, d in want.items():
        for k, x in d.items():
            if k == "label":
                continue
            got = g["effects"][arm][k]
            assert {f: got[f] for f in keys} == {f: x[f] for f in keys}, (arm, k)
            assert all(r["branch"]["log"].startswith(f"logs/{arm}/") and r["branch"]["line"] > 0
                       for r in got["per_seed"])


def test_confirmation_equals_the_spike(parsed, graded_legacy):
    m = parsed["metrics"]
    seeds = [r["seed_run"] for r in m["confirm_base"]["perf"]["target"]["per_seed"]]
    plan = {"run_set": "c", "baseline": "confirm_base", "seeds": seeds, "seeds_graded": seeds,
            "arms": {"confirm_select_valloss": {"commit": "", "methods": ["erm", "perf"]}},
            "family": [["confirm_select_valloss", "erm"], ["confirm_select_valloss", "perf"]]}
    g = ablation.grade_confirmation(plan, m, parsed["epochs"])
    for k, x in graded_legacy["table1"]["confirmation"].items():
        got = g["effects"]["confirm_select_valloss"][k]
        assert {f: got[f] for f in ("branch_mean", "base_mean", "effect", "ci", "p", "selected_epoch_median")} == \
               {f: x[f] for f in ("branch_mean", "base_mean", "effect", "ci", "p", "selected_epoch_median")}


def test_zero_variance_effect_is_refused(parsed):
    m = parsed["metrics"]
    plan = _plan(parsed)
    plan["family"] = [["paper_target_1.0", "perf"]]   # baseline against itself: every difference 0
    with pytest.raises(ablation.AblationError, match="se = 0"):
        ablation.grade_family([plan], {"spike": m}, {"spike": parsed["epochs"]})


def test_largest_and_top_two(parsed):
    g = ablation.grade_family([_plan(parsed)], {"spike": parsed["metrics"]}, {"spike": parsed["epochs"]})
    arm, method = ablation.largest(g, exclude_arms=("h_combined",))
    best = max(abs(x["effect"]) for a, d in g["effects"].items() if a != "h_combined"
               for k, x in d.items() if isinstance(x, dict) and x["survives_holm"])
    assert abs(g["effects"][arm][method]["effect"]) == best
    finding = {"h_select_valloss": "F2", "h_select_valloss_total": "F2", "h_omission_plain_sgd": "F3"}
    two = ablation.top_two(g, finding, exclude_arms=("h_combined", "h_plain_sgd_1000ep", "naive_target_0.9_3m"))
    assert len(two) == 2 and finding.get(two[0]) != finding.get(two[1])
