"""Verdict rules, version 2.1: the generic grader's rules.

Same statistical functions as the frozen version 2 (`el01/grade/legacy/verdicts_v2.py`), copied unchanged: sample_sd,
welch, absolute_verdict, paired, relative_verdict, label, and the PRACTICAL_FLOOR default. The only difference is
`setup_flag()`: it takes the findings, the branch-to-finding map and the short branch names as arguments, instead of
reading MatchDG constants. tests/test_rules_equivalence.py requires identical outputs on every MatchDG input.
Any change to the statistics (margins, CI levels, the floor, the Holm correction) needs Lead's approval first."""
import math
from scipy import stats

RULES_VERSION = "2.1"
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


def setup_flag(methods, filled, applies, effects, names, retuned=(), *, findings, branch_findings, short):
    """"Setup differs" for one claim, by rule: (a) a code omission had to be filled to run the claim at all, or
    (b) a finding's branch has a Holm-surviving effect on a method the claim names. Findings that apply but were
    not tested on these methods, or were tested with no Holm-surviving effect, become notes.
    methods: method keys the claim names. filled: findings filled in the run that produced the claim.
    applies: {finding: [methods it applies to]}. effects: grades.json "effects" (empty when no branch was run).
    retuned: findings tested by re-tuning rather than by a paired branch (reported as a note).
    findings: {finding: {"what", "kind"}}. branch_findings: {branch: [findings it tests]}. short: {branch: short name}."""
    reasons, notes, moved, tested = [], [], set(), set()
    for f in filled:
        reasons.append(f"{f} filled: {findings[f]['what']} ({findings[f]['kind']})")
    for br, d in effects.items():
        for m in methods:
            x = d.get(m)
            if not isinstance(x, dict) or "survives_holm" not in x:
                continue
            for f in branch_findings.get(br, []):
                tested.add((f, m))
                if x["survives_holm"] and f not in filled and (f, m) not in moved:
                    moved.add((f, m))
                    eff = f"{x['effect']:+.1f}".replace("-", "\u2212")
                    reasons.append(f"{f} ({short.get(br, br)}) moves {names[m]} by {eff} points, survives Holm")
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
