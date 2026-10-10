"""Deterministic grader for the MatchDG slab audit.
Inputs: metrics.json (parse_runs.py) and epochs.json (parse_epochs.py). Output: runs/grades.json.
No LLM is involved in any number or verdict here. Rules are fixed before the runs they grade."""
import json, math
from pathlib import Path
from scipy import stats

RUNS = Path("/home/claude/spike/runs")

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
# The settings diff found differences this experiment depends on, so a "Reproduced" here is "Reproduced, setup differs".
SETUP_DIFFERS = True
ALPHA = 0.05

def sample_sd(sd_pop, n):  # code and paper report population sd (np.std); convert for t-based intervals
    return sd_pop * math.sqrt(n / (n - 1))

def welch(m1, s1, n1, m2, s2, n2, level):
    v1, v2 = s1**2 / n1, s2**2 / n2
    se = math.sqrt(v1 + v2)
    df = (v1 + v2) ** 2 / (v1**2 / (n1 - 1) + v2**2 / (n2 - 1))
    t = stats.t.ppf(1 - (1 - level) / 2, df)
    d = m1 - m2
    return d, d - t * se, d + t * se

def absolute_verdict(ours, paper, delta):
    """Equivalence test (two one-sided tests, alpha 0.05 each = 90% CI inside +-delta) plus a difference test (95% CI).
    Reproduced: 90% CI inside +-delta. Not reproduced: 95% CI excludes 0 and equivalence fails. Else Inconclusive."""
    a = (ours["mean"], sample_sd(ours["sd_pop"], ours["n"]), ours["n"])
    b = (paper["mean"], sample_sd(paper["sd"], paper["n"]), paper["n"])
    d, lo95, hi95 = welch(*a, *b, 0.95)
    _, lo90, hi90 = welch(*a, *b, 0.90)
    equivalent = bool(-delta < lo90 and hi90 < delta)
    different = lo95 > 0 or hi95 < 0
    if equivalent:
        v = "Reproduced, setup differs" if SETUP_DIFFERS else "Reproduced"
    elif different:
        v = "Not reproduced"
    else:
        v = "Inconclusive"
    return {"delta": round(d, 2), "ci95": [round(lo95, 2), round(hi95, 2)], "ci90": [round(lo90, 2), round(hi90, 2)],
            "margin": delta, "min_margin_for_equivalence": round(max(abs(lo90), abs(hi90)), 2), "verdict": v}

def per_seed(m):
    return [r["target_acc"] for r in m["target"]["per_seed"]]

def paired(xs, ys):
    diffs = [x - y for x, y in zip(xs, ys)]
    n = len(diffs); mean = sum(diffs) / n; sd = stats.tstd(diffs); se = sd / math.sqrt(n)
    return mean, se, n

def relative_verdict(a, b, pa, pb):
    """Direction: our paired 95% CI for A - B. Size: CI for (our gap - paper's gap) with both uncertainties
    (paper's gap from its two reported sds, unpaired because the paper's pairing is unknown; Welch-Satterthwaite df)."""
    mean, se_o, n = paired(per_seed(a), per_seed(b))
    t = stats.t.ppf(0.975, n - 1)
    lo, hi = mean - t * se_o, mean + t * se_o
    paper_gap = pa["mean"] - pb["mean"]
    va, vb = sample_sd(pa["sd"], pa["n"])**2 / pa["n"], sample_sd(pb["sd"], pb["n"])**2 / pb["n"]
    vo = se_o**2
    se = math.sqrt(vo + va + vb)
    df = (vo + va + vb)**2 / (vo**2 / (n - 1) + va**2 / (pa["n"] - 1) + vb**2 / (pb["n"] - 1))
    tt = stats.t.ppf(0.975, df)
    g = mean - paper_gap
    glo, ghi = g - tt * se, g + tt * se
    direction = lo > 0
    if direction and glo <= 0 <= ghi:
        v = "Reproduced, setup differs" if SETUP_DIFFERS else "Reproduced"
    elif direction and glo > 0:
        v = ("Reproduced, setup differs" if SETUP_DIFFERS else "Reproduced") + " (gap larger than reported)"
    elif direction and ghi < 0:
        v = "Partially reproduced"
    elif ghi < 0:
        v = "Not reproduced"
    else:
        v = "Inconclusive"
    return {"ours_gap": round(mean, 2), "ours_ci95": [round(lo, 2), round(hi, 2)], "paper_gap": round(paper_gap, 2),
            "paper_gap_se": round(math.sqrt(va + vb), 2), "ours_gap_se": round(se_o, 2),
            "gap_difference": round(g, 2), "gap_difference_ci95": [round(glo, 2), round(ghi, 2)], "verdict": v}

def effect(branch, base):
    """Ablation effect: branch - baseline on the same seeds (paired), 95% CI and paired t-test p-value."""
    mean, se, n = paired(per_seed(branch), per_seed(base))
    t = stats.t.ppf(0.975, n - 1)
    p = 2 * stats.t.sf(abs(mean / se), n - 1) if se > 0 else 0.0
    return {"effect": round(mean, 2), "ci": [round(mean - t * se, 2), round(mean + t * se, 2)], "p": p}

def holm(pvals):
    order = sorted(range(len(pvals)), key=lambda i: pvals[i])
    m = len(pvals); adj = [0.0] * m; running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * pvals[i]))
        adj[i] = running
    return adj

def load(name, f="metrics.json"):
    p = RUNS / name / f
    return json.loads(p.read_text()) if p.exists() else None

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

if __name__ == "__main__":
    base = load("paper_target_1.0")
    ep = json.loads((RUNS / "epochs.json").read_text())
    out = {"rules": {"absolute": "Reproduced if the 90% Welch CI of (ours - paper) lies inside +-margin (TOST, alpha 0.05); "
                                 "Not reproduced if the 95% CI excludes 0 and equivalence fails; else Inconclusive. "
                                 "Margin = paper's reported sd, fixed before the runs.",
                     "relative": "Direction from our paired 95% CI; size from the 95% CI of (our gap - paper gap) including the paper's own uncertainty.",
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
        out["relative"][f"{a}_vs_{b}"] = relative_verdict(base[a], base[b], PAPER[a], PAPER[b])
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
    grid = load("h5_lambda_grid"); g5 = {}
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
    (RUNS / "grades.json").write_text(json.dumps(out, indent=1))
    for k, v in out["absolute"].items():
        print(f"{v['method']:9s} paper {v['paper']['mean']:5.1f} ours {v['ours']['mean']:5.1f}±{v['ours']['sd']:.2f}  d {v['delta']:+5.1f} 95% {v['ci95']} 90% {v['ci90']} margin {v['margin']} minδ {v['min_margin_for_equivalence']} -> {v['verdict']}")
    for k, v in out["relative"].items():
        print(k, v)
    for br, d in out["effects"].items():
        for k, x in d.items():
            if k == "label": continue
            print(f"{br:28s} {k:5s} {x['effect']:+6.1f} {x['ci']} p={x['p']:.1e} holm={x['p_holm']:.1e} {'*' if x['survives_holm'] else ' '} sel.ep {x['selected_epoch_median']} srcval {x['source_val_acc']} | last {x['last_epoch_target']}")
    print("confirmation", out["confirmation"])
    print("h5", json.dumps(out["tuning_h5"], indent=1))
