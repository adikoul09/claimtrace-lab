"""Grader for diff-guided ablations (spec section 6): branch - baseline, paired by seed, 95% CI and paired t-test;
Holm across all exploratory effects in the audit; confirmation on fresh seeds as a separate pre-specified test; the
combined branch reported next to the sum of its parts.

Port of the spike's grade.py (`effect`, `holm`, ALPHA, `survives_holm`, `detectable`, the selection summary per
effect, the confirmation block), via el01/grade/spike/table1.py. Nothing statistical is new: the effect function and
the Holm correction are el01/grade/effects.py, and `paired` comes from the rules module in use. What differs from
grade.py is only where the inputs come from: the pre-registered plan (prereg.py) names the arms, methods, seeds and
the family, instead of MatchDG constants. Values are paired by seed number, and every value keeps its log and line.

One guard (not a statistics change): a branch whose per-seed differences are all equal has se = 0, for which
effects.effect() (as grade.py) returns p = 0.0, i.e. a certain Holm survivor. The grader refuses such an effect
instead of reporting it; how to grade it is Lead's call."""
from __future__ import annotations

import statistics as st

from el01.grade.effects import effect as _effect, holm
from el01.grade.parse import summary
from el01.grade.spike.rules_adapter import legacy_rules

ALPHA = 0.05
RULE = ("Effect = branch - baseline on the target metric, paired by seed number: mean difference, 95% t CI and "
        "paired t-test p (el01/grade/effects.effect, from the spike's grade.py; `paired` from the rules module). "
        "Holm correction at alpha 0.05 across all exploratory effects in the audit (el01/grade/effects.holm); "
        "an effect is named only if it survives. The largest Holm-surviving effect is re-run on fresh seeds as a "
        "separate pre-specified test (no Holm). The top two branches combined are reported next to the sum of their "
        "single effects (no interaction test). A zero-variance difference (se = 0) is refused, not graded.")


class AblationError(RuntimeError):
    pass


def _by_seed(target: dict) -> dict[int, dict]:
    return {r["seed_run"]: r for r in target["per_seed"]}


def paired_values(branch: dict, base: dict, seeds: list[int]) -> list[dict]:
    """[{seed, branch: {value, log, line}, baseline: {...}}] for the graded seeds; both sides must have every seed."""
    b, a = _by_seed(branch), _by_seed(base)
    missing = [s for s in seeds if s not in b or s not in a]
    if missing:
        raise AblationError(f"seeds {missing} missing (branch {branch['log']}, baseline {base['log']})")
    return [{"seed": s, "branch": {"value": b[s]["target_acc"], "log": branch["log"], "line": b[s]["line"]},
             "baseline": {"value": a[s]["target_acc"], "log": base["log"], "line": a[s]["line"]}} for s in seeds]


def _selection(ep: dict, target: dict, seeds: list[int]) -> dict:
    """parse_epochs numbers runs by position; the training log's `Run N` lines give the seed of each position."""
    runs = [r["seed_run"] for r in target["per_seed"]]
    if len(runs) != len(ep["per_seed"]):
        raise AblationError(f"{ep['log']}: {len(ep['per_seed'])} per-epoch traces for {len(runs)} runs")
    rows = [r for n, r in zip(runs, ep["per_seed"]) if n in set(seeds)]
    s = summary(rows)
    return {"selected_epoch_median": s["selected_epoch_median"], "source_val_acc": s["source_val_acc"],
            "last_epoch_target": s["last_target_acc"], "last_epoch_source_val": s["last_source_val_acc"]}


def _target(metrics: dict, arm: str, method: str) -> dict:
    t = ((metrics.get(arm) or {}).get(method) or {}).get("target")
    if t is None:
        err = ((metrics.get(arm) or {}).get(method) or {}).get("error")
        raise AblationError(f"no parsed target values for {arm}/{method}" + (f" ({err})" if err else ""))
    return t


def one_effect(plan: dict, metrics: dict, epochs: dict, arm: str, method: str, rules) -> dict:
    seeds = plan["seeds_graded"]
    base = plan["baseline"]
    branch = _target(metrics, arm, method)
    rows = paired_values(branch, _target(metrics, base, method), seeds)
    xs = [r["branch"]["value"] for r in rows]
    ys = [r["baseline"]["value"] for r in rows]
    diffs = [x - y for x, y in zip(xs, ys)]
    if len(set(diffs)) <= 1:
        raise AblationError(f"{arm}/{method}: every per-seed difference is {diffs[0]:+.2f} (se = 0); grade.py's "
                            f"effect() would give p = 0. Refused: ask Lead how to grade it")
    e = _effect(xs, ys, rules.paired)
    out = {"branch_mean": round(st.mean(xs), 2), "base_mean": round(st.mean(ys), 2), **e}
    if arm in epochs and method in epochs[arm]:
        out.update(_selection(epochs[arm][method], branch, seeds))
    out["per_seed"] = rows
    return out


def grade_family(plans: list[dict], metrics: dict, epochs: dict, rules=None) -> dict:
    """Exploratory effects of one or more run sets, Holm-corrected together. `metrics` / `epochs` are keyed by run
    set, then arm (parse_run_dir / parse_epochs_all of each arm directory)."""
    rules = rules or legacy_rules()
    out, fam = {}, []
    for plan in plans:
        rs = plan["run_set"]
        for arm, method in plan["family"]:
            x = one_effect(plan, metrics[rs], epochs.get(rs, {}), arm, method, rules)
            a = plan["arms"][arm]
            d = out.setdefault(arm, {"label": a.get("label"), "finding": a.get("finding"), "run_set": rs,
                                     "ref": a.get("ref"), "commit": a["commit"]})
            d[method] = x
            fam.append((arm, method))
    adj = holm([out[a][m]["p"] for a, m in fam])
    for (a, m), p_adj in zip(fam, adj):
        x = out[a][m]
        x["p_holm"] = p_adj
        x["survives_holm"] = bool(p_adj < ALPHA)
        x["detectable"] = bool(x["ci"][0] > 0 or x["ci"][1] < 0)
        x["p"] = float(f"{x['p']:.2e}")
        x["p_holm"] = float(f"{p_adj:.2e}")
    return {"rules_version": rules.RULES_VERSION, "alpha": ALPHA, "family_size": len(fam),
            "family": [list(f) for f in fam], "effects": out}


def largest(graded: dict, exclude_arms: tuple = ()) -> tuple[str, str] | None:
    """The (arm, method) with the largest |effect| among Holm survivors."""
    cands = [(abs(x["effect"]), a, m) for a, d in graded["effects"].items() if a not in exclude_arms
             for m, x in d.items() if isinstance(x, dict) and x.get("survives_holm")]
    return (max(cands)[1], max(cands)[2]) if cands else None


def top_two(graded: dict, finding_of: dict, exclude_arms: tuple = ()) -> list[str]:
    """The two arms of different findings with the largest Holm-surviving |effect| (each arm counted once)."""
    best = {}
    for a, d in graded["effects"].items():
        if a in exclude_arms:
            continue
        for m, x in d.items():
            if isinstance(x, dict) and x.get("survives_holm"):
                best[a] = max(best.get(a, 0.0), abs(x["effect"]))
    out, used = [], set()
    for a in sorted(best, key=lambda k: (-best[k], k)):
        if finding_of.get(a) in used:
            continue
        out.append(a)
        used.add(finding_of.get(a))
        if len(out) == 2:
            break
    return out


def grade_confirmation(plan: dict, metrics: dict, epochs: dict, rules=None) -> dict:
    """The pre-specified confirmation: one (arm, method) effect on fresh seeds, no Holm (as grade.py)."""
    rules = rules or legacy_rules()
    out = {}
    for arm, method in plan["family"]:
        x = one_effect(plan, metrics, epochs, arm, method, rules)
        x["p"] = float(f"{x['p']:.2e}")
        x["detectable"] = bool(x["ci"][0] > 0 or x["ci"][1] < 0)
        out.setdefault(arm, {"label": plan["arms"][arm].get("label"), "of": plan["arms"][arm].get("confirms")})[method] = x
    return {"rules_version": rules.RULES_VERSION, "seeds": plan["seeds_graded"], "effects": out}


def interaction_report(combined: dict, singles: dict, parts: list[str]) -> dict:
    """The combined branch's effect next to the sum of the single branches' effects, per method. Report only."""
    out = {}
    for m, x in combined.items():
        if not isinstance(x, dict):
            continue
        single = {p: (singles.get(p) or {}).get(m) for p in parts}
        row = {"combined": {k: x[k] for k in ("effect", "ci", "p_holm", "survives_holm") if k in x},
               "singles": {p: ({k: s[k] for k in ("effect", "ci")} if s else None) for p, s in single.items()}}
        if all(single.values()):
            row["sum_of_single_effects"] = round(sum(s["effect"] for s in single.values()), 2)
        out[m] = row
    return out
