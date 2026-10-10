"""Verdict rules, version 2: the one place where verdict names, margins and the "setup differs" flag are decided.
Both graders (grade.py for Table 1, grade_lenet.py for Table 11) import from here, and every page renders `label()`,
so a verdict reads the same in the concept note, spec, report and blueprint. No LLM is involved in any verdict.

Changes from version 1 (scripts/v1/), after the final review:
- one verdict list: a relative claim whose direction holds but whose size differs is "Partially reproduced", with a
  size note ("gap larger than reported" or "gap smaller than reported"); "setup differs" is a flag, never part of a verdict;
- "setup differs" is computed by `setup_flag()` from a rule, not set by hand per table;
- the equivalence margin is max(paper's sd, PRACTICAL_FLOOR), declared before the runs it grades."""
import math
from scipy import stats

RULES_VERSION = 2
VERDICTS = ("Reproduced", "Partially reproduced", "Not reproduced", "Inconclusive")  # relative claims use all four
ABSOLUTE_VERDICTS = ("Reproduced", "Not reproduced", "Inconclusive")
# Smallest difference a reader would care about, in accuracy points. A user setting in the product, declared before
# the runs. 1 point = 10 of the 1,000 test images in a Rotated MNIST domain. Paper sds as small as 0.1 (one image)
# cannot be confirmed by any affordable number of runs, so without a floor well-behaved papers grade "Inconclusive".
PRACTICAL_FLOOR = 1.0


def sample_sd(sd_pop, n):  # code and paper report population sd (np.std); convert for t-based intervals
    return sd_pop * math.sqrt(n / (n - 1))


def welch(m1, s1, n1, m2, s2, n2, level):
    v1, v2 = s1**2 / n1, s2**2 / n2
    se = math.sqrt(v1 + v2)
    df = (v1 + v2) ** 2 / (v1**2 / (n1 - 1) + v2**2 / (n2 - 1))
    t = stats.t.ppf(1 - (1 - level) / 2, df)
    d = m1 - m2
    return d, d - t * se, d + t * se


def absolute_verdict(ours, paper, paper_sd, floor=PRACTICAL_FLOOR):
    """Equivalence (two one-sided tests, alpha 0.05 each = 90% CI inside +-margin) plus a difference test (95% CI).
    margin = max(paper's sd, floor). Reproduced: 90% CI inside +-margin. Not reproduced: 95% CI excludes 0 and
    equivalence fails. Else Inconclusive. Also reports the tightest margin the data would support."""
    margin = max(paper_sd, floor)
    a = (ours["mean"], sample_sd(ours["sd_pop"], ours["n"]), ours["n"])
    b = (paper["mean"], sample_sd(paper["sd"], paper["n"]), paper["n"])
    d, lo95, hi95 = welch(*a, *b, 0.95)
    _, lo90, hi90 = welch(*a, *b, 0.90)
    if -margin < lo90 and hi90 < margin:
        v = "Reproduced"
    elif lo95 > 0 or hi95 < 0:
        v = "Not reproduced"
    else:
        v = "Inconclusive"
    return {"delta": round(d, 2), "ci95": [round(lo95, 2), round(hi95, 2)], "ci90": [round(lo90, 2), round(hi90, 2)],
            "margin": round(margin, 2), "margin_source": "paper sd" if paper_sd >= floor else "practical floor",
            "min_margin_for_equivalence": round(max(abs(lo90), abs(hi90)), 2), "verdict": v, "size_note": None}


def paired(xs, ys):
    diffs = [x - y for x, y in zip(xs, ys)]
    n = len(diffs); mean = sum(diffs) / n; sd = stats.tstd(diffs); se = sd / math.sqrt(n)
    return mean, se, n


def relative_verdict(xa, xb, pa, pb):
    """A claim "A beats B". xa, xb: our per-seed values, paired by seed. pa, pb: paper {mean, sd, n}.
    Direction: our paired 95% CI for A - B lies above 0. Size: 95% CI of (our gap - paper's gap), with the paper's own
    uncertainty (unpaired, its pairing is unknown; Welch-Satterthwaite df).
    Reproduced: direction holds and the size CI contains 0. Partially reproduced: direction holds, size differs (note
    says which way). Not reproduced: direction not shown and our gap is significantly smaller. Else Inconclusive."""
    mean, se_o, n = paired(xa, xb)
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
    direction, note = lo > 0, None
    if direction and glo <= 0 <= ghi:
        v = "Reproduced"
    elif direction:
        v, note = "Partially reproduced", ("gap larger than reported" if glo > 0 else "gap smaller than reported")
    elif ghi < 0:
        v = "Not reproduced"
    else:
        v = "Inconclusive"
    return {"ours_gap": round(mean, 2), "ours_ci95": [round(lo, 2), round(hi, 2)], "paper_gap": round(paper_gap, 2),
            "paper_gap_se": round(math.sqrt(va + vb), 2), "ours_gap_se": round(se_o, 2),
            "gap_difference": round(g, 2), "gap_difference_ci95": [round(glo, 2), round(ghi, 2)],
            "verdict": v, "size_note": note}


def label(v):
    """The one display string for a verdict, used by every rendered page."""
    return v["verdict"] + (f" ({v['size_note']})" if v.get("size_note") else "")


# Findings from the settings diff (spec F1-F6) and the branches that test them.
FINDINGS = {
    "F1": {"what": "target domain p = 1.0 never generated", "kind": "code omission"},
    "F2": {"what": "model selection: validation loss (paper) vs accuracy (code)", "kind": "difference"},
    "F3": {"what": "optimizer: plain SGD (paper) vs momentum 0.9 + Nesterov (code)", "kind": "paper omission"},
    "F4": {"what": "matching weight ramps from about 0 (code), no schedule in paper", "kind": "paper omission"},
    "F5": {"what": "DANN/CDANN learning rate 0.1 (paper) vs 0.01 (code)", "kind": "difference"},
    "F6": {"what": "hyperparameters ranked by target accuracy (code) vs source validation (paper)", "kind": "difference"},
}
BRANCH_FINDINGS = {
    "naive_target_0.9_3m": ["F1"], "h_select_valloss": ["F2"], "h_select_valloss_total": ["F2"],
    "h_omission_plain_sgd": ["F3"], "h_plain_sgd_1000ep": ["F3"], "h_combined": ["F2", "F3"],
    "h_omission_constant_penalty": ["F4"], "h_dann_lr": ["F5"],
}
SHORT = {"naive_target_0.9_3m": "h3", "h_select_valloss": "h1", "h_select_valloss_total": "h1b",
         "h_omission_plain_sgd": "h2", "h_plain_sgd_1000ep": "h2 at 1000 epochs", "h_combined": "h1+h2",
         "h_omission_constant_penalty": "h4", "h_dann_lr": "h6"}


def setup_flag(methods, filled, applies, effects, names, retuned=()):
    """"Setup differs" for one claim, by rule: (a) a code omission had to be filled to run the claim at all, or
    (b) a finding's branch has a Holm-surviving effect on a method the claim names. Findings that apply but were
    not tested on these methods, or were tested with no Holm-surviving effect, become notes.
    methods: method keys the claim names. filled: findings filled in the run that produced the claim.
    applies: {finding: [methods it applies to]}. effects: grades.json "effects" (empty when no branch was run).
    retuned: findings tested by re-tuning rather than by a paired branch (reported as a note)."""
    reasons, notes, moved, tested = [], [], set(), set()
    for f in filled:
        reasons.append(f"{f} filled: {FINDINGS[f]['what']} ({FINDINGS[f]['kind']})")
    for br, d in effects.items():
        for m in methods:
            x = d.get(m)
            if not isinstance(x, dict) or "survives_holm" not in x:
                continue
            for f in BRANCH_FINDINGS.get(br, []):
                tested.add((f, m))
                if x["survives_holm"] and f not in filled and (f, m) not in moved:
                    moved.add((f, m))
                    eff = f"{x['effect']:+.1f}".replace("-", "\u2212")
                    reasons.append(f"{f} ({SHORT.get(br, br)}) moves {names[m]} by {eff} points, survives Holm")
    for f, ms in applies.items():
        if f in filled or any(g == f for g, _ in moved):
            continue
        rel = [m for m in methods if m in ms]
        if not rel:
            continue
        if f in retuned:
            notes.append(f"{f} tested by re-tuning (h5), not as a paired branch")
        elif all((f, m) in tested for m in rel):
            notes.append(f"{f} tested: no Holm-surviving effect")
        else:
            untested = [names[m] for m in rel if (f, m) not in tested]
            notes.append(f"{f} applies, not tested for {', '.join(untested)}")
    return {"differs": bool(reasons), "reasons": reasons, "notes": notes}
