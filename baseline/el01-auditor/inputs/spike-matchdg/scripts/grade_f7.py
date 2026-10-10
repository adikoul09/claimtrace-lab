"""F7 (SciCoQA row 67): does the horizontal flip in the augmented Rotated MNIST copy move MatchDG's Table 11 numbers?
On the audited path the flipped copy is used only by MatchDG's contrastive phase, which saves the epoch whose model best
matches validation images to their augmented copies (train.py:217-218, utils/helper.py:173-175, algorithms/match_dg.py:263-266).
Branch audit/h7-no-flip removes the flips and keeps every random crop (same random draws); training and test data are
byte-identical. Paired by (test domain, run) against the Table 11 confirmation run (same MNIST subsets 3-5, seeds 30-50).
Rule, fixed before the branch runs: primary test = the six-domain average, paired by run, 95% t CI; cells = paired t-tests,
Holm across the six cells. F7 is a "setup differs" reason for a MatchDG Table 11 claim only if its effect survives
(primary CI excludes 0 for the average and the relative claims; Holm for a cell). Usage: grade_f7.py [out.json]"""
import json, math, re, sys
from pathlib import Path
from scipy import stats
sys.path.insert(0, str(Path(__file__).parent))
from verdicts import paired

R = Path("/home/claude/spike/runs"); BASE = R / "matchdg_lenet_confirm"; BR = R / "h7_no_flip"
DOM = ["0", "15", "30", "45", "60", "75"]

def per_run(d, dom):
    t = json.loads((d / "metrics.json").read_text())[f"matchdg_{dom}"]["target"]
    return {r["seed_run"]: (r["target_acc"], r["line"]) for r in t["per_seed"]}, t["log"]

def ctr_epochs(d, dom):
    """Contrastive-phase checkpoint per run: the last 'Current Best Epoch ... TopK Overlap' line before the next run starts."""
    out, cur, last = {}, None, None
    for i, l in enumerate((d / f"train_matchdg_ctr_{dom}.log").read_text().splitlines(), 1):
        m = re.match(r"^Run (\d+)", l)
        if m:
            if cur is not None and last: out[cur] = last
            cur, last = int(m.group(1)), None
        m = re.search(r"Current Best Epoch:\s+(\d+)\s+with TopK Overlap:\s+([\d.]+)", l)
        if m: last = {"epoch": int(m.group(1)), "topk_overlap": float(m.group(2)), "line": i}
    if cur is not None and last: out[cur] = last
    return out

def test(xs, ys):
    mean, se, n = paired(xs, ys)
    if se == 0: return mean, [mean, mean], 1.0 if mean == 0 else 0.0
    t = stats.t.ppf(0.975, n - 1); p = 2 * stats.t.sf(abs(mean / se), n - 1)
    return mean, [mean - t * se, mean + t * se], p

def holm(ps):
    order = sorted(range(len(ps)), key=lambda i: ps[i]); adj = [0.0] * len(ps); run = 0.0
    for k, i in enumerate(order):
        run = max(run, min(1.0, (len(ps) - k) * ps[i])); adj[i] = run
    return adj

if __name__ == "__main__":
    out = {"finding": "F7", "branch": "audit/h7-no-flip", "baseline": "matchdg_lenet_confirm", "cells": {}, "missing": []}
    b_avg, h_avg, ps = {}, {}, []
    for d in DOM:
        try:
            b, blog = per_run(BASE, d); h, hlog = per_run(BR, d)
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
                           "ctr_epoch_base": ctr_epochs(BASE, d), "ctr_epoch_branch": ctr_epochs(BR, d) if (BR / f"train_matchdg_ctr_{d}.log").exists() else {}}
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
    dst = Path(sys.argv[1]) if len(sys.argv) > 1 else BR / "grades_f7.json"
    dst.write_text(json.dumps(out, indent=1)); print(json.dumps({k: v for k, v in out.items() if k != "cells"}, indent=1))
    for d, c in out["cells"].items(): print(d, c["effect"], c["ci95"], c["p_holm"], "same ctr epoch", c["same_ctr_epoch"], "of", len(c["runs"]))
