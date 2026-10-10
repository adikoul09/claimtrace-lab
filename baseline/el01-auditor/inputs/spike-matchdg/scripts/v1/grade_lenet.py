"""Grader for the MatchDG audit proper: Suppl. Table 11 (Rotated MNIST, LeNet, leave-one-domain-out).
Written and hashed before the runs finished (runs/matchdg_lenet/PREREGISTERED.txt). Same rules as the slab table:
absolute cells by equivalence (margin = the paper's sd for that cell), relative claims by direction plus size with the
paper's uncertainty included. No LLM is involved in any number or verdict here."""
import json, math, sys
from pathlib import Path
from scipy import stats

sys.path.insert(0, str(Path(__file__).parent))
from parse_runs import parse_train
from grade import absolute_verdict, relative_verdict, holm, sample_sd

R = Path("/home/claude/spike/runs/matchdg_lenet")
DOMAINS = [0, 15, 30, 45, 60, 75]
METHODS = ["erm", "rand", "matchdg", "perf"]
NAMES = {"erm": "ERM", "rand": "RandMatch", "matchdg": "MatchDG", "perf": "PerfMatch (oracle)"}
# Table 11, mean (sd). The number of seeds is not stated in the paper; we assume 3, the code's default n_runs.
N_PAPER = 3
PAPER = {
    "erm":     [(88.2, 1.0), (98.6, 0.5), (97.7, 0.6), (97.5, 0.3), (97.0, 0.1), (85.6, 2.1)],
    "rand":    [(91.0, 0.9), (99.7, 0.2), (99.6, 0.1), (99.4, 0.1), (99.7, 0.1), (93.1, 1.1)],
    "matchdg": [(93.0, 0.5), (99.5, 0.3), (99.9, 0.1), (99.4, 0.1), (99.7, 0.3), (93.3, 1.1)],
    "perf":    [(96.5, 0.6), (99.1, 0.3), (99.2, 0.3), (98.6, 0.7), (98.6, 1.0), (94.9, 1.8)],
}
PAPER_AVG = {"erm": 94.1, "rand": 97.1, "matchdg": 97.4, "perf": 97.8}
# Prior work rows of Table 11 (copied from other papers; we cannot re-run them). Best per column, with its name.
PRIOR = {"CCSA": [84.6, 95.6, 94.6, 82.9, 94.8, 82.1], "D-MTAE": [82.5, 96.3, 93.4, 78.6, 94.2, 80.5],
         "LabelGrad": [89.7, 97.8, 98.0, 97.1, 96.6, 92.1], "DAN": [86.7, 98.0, 97.8, 97.4, 96.9, 89.1],
         "CrossGrad": [88.3, 98.6, 98.0, 97.7, 97.7, 91.4], "DIVA": [93.5, 99.3, 99.1, 99.2, 99.3, 93.0]}
# Relative claims, on the six-domain average, paired by run index (run r uses data subset r in every method).
RELATIVE = [("matchdg", "erm"), ("matchdg", "rand"), ("perf", "matchdg")]
# Text claim (Suppl. A.4): "RandMatch and MatchDG outperform prior work on all the domains except the test domain 0".
# Rule: "above" if our 95% CI lower bound > the best prior-work number in that column; "below" if the upper bound is
# under it; else "not separable". The 0-degree column ("competitive with DIVA") has no margin, so it is reported, not graded.

def paper_avg_sd(m):
    # sd of a seed's six-domain average if domains are independent: sqrt(sum sd_d^2) / 6
    return math.sqrt(sum(s**2 for _, s in PAPER[m])) / 6

def runs(m, d):
    f = R / f"train_{m}_{d}.log"
    try:
        return parse_train(f) if f.exists() else None
    except Exception:  # run still in progress (no final line yet)
        return None

def summary(vals):
    n = len(vals); mu = sum(vals) / n
    return {"mean": round(mu, 2), "sd_pop": round(math.sqrt(sum((v - mu)**2 for v in vals) / n), 2), "n": n}

if __name__ == "__main__":
    out = {"rules": {"absolute": "Per cell: Reproduced if the 90% Welch CI of (ours - paper) lies inside +-(paper's sd for that cell); "
                                 "Not reproduced if the 95% CI excludes 0 and equivalence fails; else Inconclusive. Paper n assumed 3.",
                     "average": "Six-domain average per run index; paper's sd for it derived as sqrt(sum sd_d^2)/6 (domains independent).",
                     "relative": "On the average, paired by run index; direction from our 95% CI, size from the CI of (our gap - paper gap).",
                     "prior_work": "Above if our 95% CI lower bound > best prior-work number in that column; below if upper < it; else not separable."},
           "cells": {}, "average": {}, "relative": {}, "prior_work": {}, "missing": []}
    per_run_avg = {}
    for m in METHODS:
        out["cells"][m] = {}
        cols = []
        for i, d in enumerate(DOMAINS):
            r = runs(m, d)
            if r is None or r["n"] == 0:
                out["missing"].append(f"{m}_{d}"); continue
            pm, ps = PAPER[m][i]
            v = absolute_verdict({"mean": r["mean"], "sd_pop": r["sd_pop"], "n": r["n"]}, {"mean": pm, "sd": ps, "n": N_PAPER}, ps)
            v.update({"paper": {"mean": pm, "sd": ps}, "ours": {"mean": r["mean"], "sd": r["sd_pop"], "n": r["n"]},
                      "per_seed": [x["target_acc"] for x in r["per_seed"]], "selected_epochs": [x["best_epoch"] for x in r["per_seed"]],
                      "log": r["log"]})
            out["cells"][m][str(d)] = v
            cols.append([x["target_acc"] for x in r["per_seed"]])
        if len(cols) == len(DOMAINS):
            n = min(len(c) for c in cols)
            per_run_avg[m] = [sum(c[k] for c in cols) / len(cols) for k in range(n)]
            ours = summary(per_run_avg[m])
            psd = paper_avg_sd(m)
            v = absolute_verdict(ours, {"mean": PAPER_AVG[m], "sd": psd, "n": N_PAPER}, psd)
            v.update({"paper": {"mean": PAPER_AVG[m], "sd_derived": round(psd, 2)}, "ours": ours, "per_run": [round(x, 2) for x in per_run_avg[m]]})
            out["average"][m] = v
    for a, b in RELATIVE:
        if a in per_run_avg and b in per_run_avg:
            ma = {"target": {"per_seed": [{"target_acc": x} for x in per_run_avg[a]]}}
            mb = {"target": {"per_seed": [{"target_acc": x} for x in per_run_avg[b]]}}
            pa = {"mean": PAPER_AVG[a], "sd": paper_avg_sd(a), "n": N_PAPER}
            pb = {"mean": PAPER_AVG[b], "sd": paper_avg_sd(b), "n": N_PAPER}
            v = relative_verdict(ma, mb, pa, pb)
            v["verdict"] = v["verdict"].replace(", setup differs", "")  # Table 11 settings match Tables 8-9 (see report)
            out["relative"][f"{a}_vs_{b}"] = v
    for m in ("rand", "matchdg"):
        out["prior_work"][m] = {}
        for i, d in enumerate(DOMAINS):
            c = out["cells"][m].get(str(d))
            if not c: continue
            best_name = max(PRIOR, key=lambda k: PRIOR[k][i]); best = PRIOR[best_name][i]
            xs = c["per_seed"]; n = len(xs); mu = sum(xs) / n
            se = stats.tstd(xs) / math.sqrt(n) if n > 1 else float("nan")
            t = stats.t.ppf(0.975, n - 1)
            lo, hi = mu - t * se, mu + t * se
            res = "reported, not graded (0°: 'competitive with DIVA' has no margin)" if d == 0 else \
                  ("above" if lo > best else ("below" if hi < best else "not separable"))
            out["prior_work"][m][str(d)] = {"ours_mean": round(mu, 2), "ci95": [round(lo, 2), round(hi, 2)],
                                            "best_prior": best, "best_prior_name": best_name, "result": res}
    (R / "grades_lenet.json").write_text(json.dumps(out, indent=1))
    for m in METHODS:
        print(NAMES[m], " ".join(f"{d}:{c['ours']['mean']:.1f}/{c['paper']['mean']}/{c['verdict'][:6]}" for d, c in out["cells"][m].items()))
    for m, v in out["average"].items(): print("avg", m, v["ours"], v["paper"], v["verdict"], v["min_margin_for_equivalence"])
    for k, v in out["relative"].items(): print(k, v["ours_gap"], v["ours_ci95"], v["paper_gap"], v["gap_difference_ci95"], v["verdict"])
    for m, d in out["prior_work"].items(): print("prior", m, {k: x["result"] for k, x in d.items()})
    print("missing:", out["missing"])
