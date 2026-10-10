"""F7 (SciCoQA row 67): does the horizontal flip in the augmented Rotated MNIST copy move MatchDG's Table 11 numbers?
Port of the spike's scripts/grade_f7.py.
On the audited path the flipped copy is used only by MatchDG's contrastive phase, which saves the epoch whose model best
matches validation images to their augmented copies (train.py:217-218, utils/helper.py:173-175, algorithms/match_dg.py:263-266).
Branch audit/h7-no-flip removes the flips and keeps every random crop (same random draws); training and test data are
byte-identical. Paired by (test domain, run) against the Table 11 confirmation run (same MNIST subsets 3-5, seeds 30-50).
Rule, fixed before the branch runs: primary test = the six-domain average, paired by run, 95% t CI; cells = paired t-tests,
Holm across the six cells. F7 is a "setup differs" reason for a MatchDG Table 11 claim only if its effect survives
(primary CI excludes 0 for the average and the relative claims; Holm for a cell)."""
from pathlib import Path

from el01.grade.effects import holm, paired_test
from el01.grade.parse import ctr_epochs
from el01.grade.spike.rules_adapter import legacy_rules

BASE_RUN, BRANCH_RUN = "matchdg_lenet_confirm", "h7_no_flip"
DOM = ["0", "15", "30", "45", "60", "75"]


def grade_f7(metrics, logs_dir, rules=None):
    """metrics: {run name: metrics.json content}. logs_dir: the run directories (contrastive-phase logs are read there).
    Returns the grades_f7.json content."""
    rules = rules or legacy_rules()
    BASE, BR = Path(logs_dir) / BASE_RUN, Path(logs_dir) / BRANCH_RUN
    test = lambda xs, ys: paired_test(xs, ys, rules.paired)

    def per_run(run, dom):
        if run not in metrics: raise FileNotFoundError(run)  # the spike read runs/<run>/metrics.json
        t = metrics[run][f"matchdg_{dom}"]["target"]
        return {r["seed_run"]: (r["target_acc"], r["line"]) for r in t["per_seed"]}, t["log"]

    out = {"finding": "F7", "branch": "audit/h7-no-flip", "baseline": "matchdg_lenet_confirm", "cells": {}, "missing": []}
    b_avg, h_avg, ps = {}, {}, []
    for d in DOM:
        try:
            b, blog = per_run(BASE_RUN, d); h, hlog = per_run(BRANCH_RUN, d)
        except (KeyError, FileNotFoundError):
            out["missing"].append(d); continue
        runs = sorted(set(b) & set(h))
        xs = [h[r][0] for r in runs]; ys = [b[r][0] for r in runs]
        eff, ci, p = test(xs, ys); ps.append(p)
        for r in runs:
            b_avg.setdefault(r, []).append(b[r][0]); h_avg.setdefault(r, []).append(h[r][0])
        out["cells"][d] = {"runs": runs, "base": ys, "branch": xs, "base_log": blog, "branch_log": hlog,
                           "base_lines": [b[r][1] for r in runs], "branch_lines": [h[r][1] for r in runs],
                           "effect": round(eff, 2), "ci95": [round(c, 2) for c in ci], "p": round(p, 4),
                           "ctr_epoch_base": ctr_epochs(BASE / f"train_matchdg_ctr_{d}.log"),
                           "ctr_epoch_branch": ctr_epochs(BR / f"train_matchdg_ctr_{d}.log") if (BR / f"train_matchdg_ctr_{d}.log").exists() else {}}
    for d, a in zip(list(out["cells"]), holm(ps)):
        c = out["cells"][d]; c["p_holm"] = round(a, 4); c["survives_holm"] = bool(a < 0.05)
        c["same_ctr_epoch"] = sum(1 for r in c["runs"] if c["ctr_epoch_base"].get(r, {}).get("epoch") == c["ctr_epoch_branch"].get(r, {}).get("epoch"))
    if not out["missing"]:
        runs = sorted(b_avg)
        xs = [sum(h_avg[r]) / len(DOM) for r in runs]; ys = [sum(b_avg[r]) / len(DOM) for r in runs]
        eff, ci, p = test(xs, ys)
        out["average"] = {"base": [round(y, 2) for y in ys], "branch": [round(x, 2) for x in xs], "effect": round(eff, 2),
                          "ci95": [round(c, 2) for c in ci], "p": round(p, 4), "excludes_zero": bool(ci[0] > 0 or ci[1] < 0)}
        out["setup_reason_for"] = (["MatchDG six-domain average", "MatchDG relative claims"] if out["average"]["excludes_zero"] else []) + \
                                  [f"MatchDG {d}°" for d, c in out["cells"].items() if c["survives_holm"]]
    return out
