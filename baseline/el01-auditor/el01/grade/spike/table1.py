"""Deterministic grader for the MatchDG slab audit (paper Table 1). Port of the spike's scripts/grade.py.
Inputs: per-run metrics (parse.parse_run_dir) and epochs (parse.parse_epochs_all), as the spike read them from
runs/<run>/metrics.json and runs/epochs.json. Output: the grades.json content.
No LLM is involved in any number or verdict here. Verdict rules come from the injected `rules` (default: version 2)."""
from el01.grade.effects import effect as _effect, holm
from el01.grade.spike.rules_adapter import legacy_rules

# Paper: Mahajan et al., "Domain Generalization using Causal Matching", ICML 2021, Table 1 (slab),
# "Mean and standard deviation over 10 different seed values for each method". Target column.
PAPER = {
    "erm":  {"mean": 57.6, "sd": 6.58, "n": 10},
    "rand": {"mean": 59.5, "sd": 3.50, "n": 10},
    "perf": {"mean": 77.8, "sd": 6.01, "n": 10},
    "mmd":  {"mean": 62.9, "sd": 5.01, "n": 10},
    "coral": {"mean": 63.1, "sd": 5.86, "n": 10},
    "dann": {"mean": 53.0, "sd": 1.41, "n": 10},
    "c-mmd": {"mean": 58.9, "sd": 3.43, "n": 10},
    "c-coral": {"mean": 64.7, "sd": 4.69, "n": 10},  # was mistyped as 6.01 in our hand table; caught by the blind extraction
    "c-dann": {"mean": 55.9, "sd": 2.47, "n": 10},
}
NAMES = {"erm": "ERM", "rand": "RandMatch", "perf": "PerfMatch", "mmd": "MMD", "coral": "CORAL", "dann": "DANN",
         "c-mmd": "C-MMD", "c-coral": "C-CORAL", "c-dann": "CDANN"}
# Relative claims (Sec 3.2): PerfMatch, the oracle that matches on the true stable feature, beats the others.
RELATIVE = [("perf", "erm"), ("perf", "rand")]
# Which findings apply to which methods (spec F1-F6). F1 had to be filled to run Table 1 at all.
ALL = list(PAPER)
APPLIES = {"F1": ALL, "F2": ALL, "F3": ALL, "F4": ["rand", "perf"], "F5": ["dann", "c-dann"], "F6": ["rand", "perf"]}
FILLED = ["F1"]
ALPHA = 0.05

# Exploratory branches, each compared with the baseline (paper_target_1.0) on seeds 0-9.
BRANCHES = [
    ("h_select_valloss", "h1: select by validation cross-entropy (one reading of the paper)"),
    ("h_select_valloss_total", "h1b: select by full validation objective (the other reading)"),
    ("h_omission_plain_sgd", "h2: plain SGD, as the paper states"),
    ("h_plain_sgd_1000ep", "h2 diagnostic: plain SGD for 1000 epochs"),
    ("h_combined", "h1 + h2 together"),
    ("naive_target_0.9_3m", "h3: evaluate on p = 0.9, the domain the code generates"),
    ("h_omission_constant_penalty", "h4: constant matching weight (code ramps it from 0)"),
    ("h_dann_lr", "h6: DANN and CDANN at lr 0.1, as the paper states (code hard-codes 0.01)"),
]
SKIP = {("h_select_valloss_total", "erm")}  # ERM has no matching penalty, so h1b is h1 for ERM; tested once only


def per_seed(m):
    return [r["target_acc"] for r in m["target"]["per_seed"]]


def grade_table1(metrics, ep, rules=None):
    """metrics: {run name: metrics.json content}. ep: epochs.json content. Returns the grades.json content."""
    rules = rules or legacy_rules()
    absolute_verdict, relative_verdict, setup_flag, vlabel = rules.absolute_verdict, rules.relative_verdict, rules.setup_flag, rules.label
    effect = lambda branch, base: _effect(per_seed(branch), per_seed(base), rules.paired)
    load = metrics.get
    base = load("paper_target_1.0")
    out = {"rules_version": rules.RULES_VERSION, "practical_floor": rules.PRACTICAL_FLOOR,
           "rules": {"absolute": "Reproduced if the 90% Welch CI of (ours - paper) lies inside +-margin (TOST, alpha 0.05); "
                                 "Not reproduced if the 95% CI excludes 0 and equivalence fails; else Inconclusive. "
                                 "Margin = max(paper's sd, practical floor). Every Table 1 sd is above the floor, so the margin is the paper's sd, as in version 1.",
                     "relative": "Direction from our paired 95% CI; size from the 95% CI of (our gap - paper gap) including the paper's own uncertainty. "
                                 "Direction holds and size consistent: Reproduced; direction holds, size differs: Partially reproduced with a size note.",
                     "setup_differs": "A code omission had to be filled, or a finding's branch has a Holm-surviving effect on a method the claim names. "
                                      "Findings that apply but were not tested, or had no Holm-surviving effect, are notes.",
                     "effects": "Paired by seed, 95% CI; Holm correction over all exploratory effects; confirmation on fresh seeds is a separate pre-specified test."},
           "absolute": {}, "relative": {}, "effects": {}, "confirmation": {}, "selection": {}}
    for k, p in PAPER.items():
        if k in base and "target" in base[k]:
            ours = base[k]["target"]
            out["absolute"][k] = {"method": NAMES[k], "paper": p,
                                  "ours": {"mean": ours["mean"], "sd": ours["sd_pop"], "n": ours["n"]},
                                  "source": {s: base[k][s]["mean"] for s in ("source_1", "source_2") if s in base[k]},
                                  **absolute_verdict(ours, p, p["sd"])}
    for a, b in RELATIVE:
        out["relative"][f"{a}_vs_{b}"] = relative_verdict(per_seed(base[a]), per_seed(base[b]), PAPER[a], PAPER[b])
    fam = []
    for br, label in BRANCHES:
        m = load(br)
        if not m: continue
        for k in ("erm", "rand", "perf", "dann", "c-dann"):
            if k in m and "target" in m[k] and k in base and (br, k) not in SKIP:
                e = effect(m[k], base[k])
                s = ep[br][k]["summary"]
                out["effects"].setdefault(br, {"label": label})[k] = {
                    "branch_mean": m[k]["target"]["mean"], **e,
                    "selected_epoch_median": s["selected_epoch_median"], "source_val_acc": s["source_val_acc"],
                    "last_epoch_target": s["last_target_acc"], "last_epoch_source_val": s["last_source_val_acc"]}
                fam.append((br, k))
    adj = holm([out["effects"][br][k]["p"] for br, k in fam])
    for (br, k), a in zip(fam, adj):
        x = out["effects"][br][k]
        x["p_holm"] = a
        x["survives_holm"] = bool(a < ALPHA)
        x["detectable"] = bool(x["ci"][0] > 0 or x["ci"][1] < 0)
        x["p"] = float(f"{x['p']:.2e}"); x["p_holm"] = float(f"{a:.2e}")
    cb, cs = load("confirm_base"), load("confirm_select_valloss")
    for k in ("erm", "perf"):
        e = effect(cs[k], cb[k])
        out["confirmation"][k] = {"branch_mean": cs[k]["target"]["mean"], "base_mean": cb[k]["target"]["mean"],
                                  **e, "p": float(f"{e['p']:.2e}"),
                                  "selected_epoch_median": ep["confirm_select_valloss"][k]["summary"]["selected_epoch_median"]}
    for k in ("erm", "rand", "perf"):
        s = ep["paper_target_1.0"][k]["summary"]
        out["selection"][k] = {"selected_epoch_median": s["selected_epoch_median"], "selected_target": s["target_acc"],
                               "last_epoch_target": s["last_target_acc"]}
    # h5: re-tune the matching weight over the repo's own grid (slab-tune.py) by source-validation accuracy, as App. A.1
    # describes, and compare with the criterion slab-tune.py actually reads (target-domain test accuracy).
    g5 = {}
    for k in ("perf", "rand"):
        cand = {"1.0": ("paper_target_1.0", k)}
        for lam in ("0.1", "10.0"):
            cand[lam] = ("h5_lambda_grid", f"{k}_lambda_{lam}")
        rows = {}
        for lam, (run, key) in cand.items():
            e = ep[run][key]["summary"]; per = ep[run][key]["per_seed"]
            rows[lam] = {"source_val_acc_10": e["source_val_acc"], "target_10": e["target_acc"],
                         "source_val_acc_first3": round(sum(r["source_val_acc"] for r in per[:3]) / 3, 2),
                         "target_first3": round(sum(r["target_acc"] for r in per[:3]) / 3, 2)}
        g5[k] = {"grid": rows,
                 "chosen_by_source_val_3_seeds": max(rows, key=lambda l: rows[l]["source_val_acc_first3"]),
                 "chosen_by_target_3_seeds": max(rows, key=lambda l: rows[l]["target_first3"]),
                 "published_choice": "1.0"}
    out["tuning_h5"] = g5
    for k, v in out["absolute"].items():
        v["setup"] = setup_flag([k], FILLED, APPLIES, out["effects"], NAMES, retuned=("F6",)); v["label"] = vlabel(v)
    for key, v in out["relative"].items():
        a, b = key.split("_vs_")
        v["setup"] = setup_flag([a, b], FILLED, APPLIES, out["effects"], NAMES, retuned=("F6",)); v["label"] = vlabel(v)
    return out
