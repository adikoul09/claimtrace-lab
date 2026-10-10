"""Paired effects and the Holm correction, from the spike's grade.py (effect, holm) and grade_f7.py (test, holm; the two
holm functions are the same algorithm). `paired` comes from the rules module in use, so a grade never mixes rule versions."""
from scipy import stats


def effect(xs, ys, paired):
    """Ablation effect: xs - ys on the same seeds (paired), 95% CI and paired t-test p-value."""
    mean, se, n = paired(xs, ys)
    t = stats.t.ppf(0.975, n - 1)
    p = 2 * stats.t.sf(abs(mean / se), n - 1) if se > 0 else 0.0
    return {"effect": round(mean, 2), "ci": [round(mean - t * se, 2), round(mean + t * se, 2)], "p": p}


def paired_test(xs, ys, paired):
    """grade_f7.py's test(): (mean, [lo, hi] 95% CI, p). A zero-variance difference gives p = 1 if the mean is 0, else 0."""
    mean, se, n = paired(xs, ys)
    if se == 0: return mean, [mean, mean], 1.0 if mean == 0 else 0.0
    t = stats.t.ppf(0.975, n - 1); p = 2 * stats.t.sf(abs(mean / se), n - 1)
    return mean, [mean - t * se, mean + t * se], p


def holm(pvals):
    order = sorted(range(len(pvals)), key=lambda i: pvals[i])
    m = len(pvals); adj = [0.0] * m; running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * pvals[i]))
        adj[i] = running
    return adj
