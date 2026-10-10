"""Builds the blueprint's data charts from metrics.json / grades.json (no hand-typed numbers except the paper's Table 1)."""
import json
from pathlib import Path

R = Path("/home/claude/spike/runs")
def m(run, k):
    t = json.loads((R / run / "metrics.json").read_text())[k]["target"]
    return t["mean"], t["sd_pop"]

def esc(s): return s.replace("&", "&amp;").replace("<", "&lt;")

PAPER = {"erm": (57.6, 6.58), "perf": (77.8, 6.01)}
DOT_ROWS = [
    ("Paper, Table 1", None),
    ("Code's settings", "paper_target_1.0"),
    ("Paper's rule as cross-entropy (h1)", "h_select_valloss"),
    ("Paper's rule as full objective (h1b)", "h_select_valloss_total"),
    ("Paper's optimizer, plain SGD (h2)", "h_omission_plain_sgd"),
    ("Plain SGD, 1000 epochs (check)", "h_plain_sgd_1000ep"),
]

def dot_rows():
    rows = []
    for label, run in DOT_ROWS:
        if run is None:
            rows.append((label, PAPER)); continue
        try:
            rows.append((label, {"erm": m(run, "erm"), "perf": m(run, "perf")}))
        except (KeyError, FileNotFoundError):
            pass
    return rows

def dot_chart(rows):
    W, x0, x1, top, step = 760, 250, 735, 46, 54
    lo, hi = 30, 100
    X = lambda v: x0 + (min(max(v, lo), hi) - lo) / (hi - lo) * (x1 - x0)
    H = top + step * len(rows) + 30
    o = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Target accuracy for ERM and PerfMatch under the paper\'s numbers, the code\'s settings and each reading of the paper\'s setup. PerfMatch stays far above ERM with the code\'s settings and with the full-objective reading of the selection rule; it falls to ERM\'s level with the cross-entropy reading and with plain SGD at 100 epochs.">']
    for v in range(lo, hi + 1, 10):
        o.append(f'<line x1="{X(v):.1f}" y1="{top-18}" x2="{X(v):.1f}" y2="{H-30}" class="grid"/>')
        o.append(f'<text x="{X(v):.1f}" y="{H-12}" text-anchor="middle" class="tl">{v}%</text>')
    o.append(f'<line x1="{X(50):.1f}" y1="{top-18}" x2="{X(50):.1f}" y2="{H-30}" class="ln-dash"/>')
    o.append(f'<text x="{X(50)+4:.1f}" y="{top-24}" class="tl">chance</text>')
    for i, (label, d) in enumerate(rows):
        y = top + i * step
        o.append(f'<text x="{x0-14}" y="{y+4}" text-anchor="end" class="t">{esc(label)}</text>')
        for k, off, cls, name in (("erm", -8, "s2", "ERM"), ("perf", 8, "s1", "PerfMatch")):
            mu, sd = d[k]
            yy = y + off
            o.append(f'<g><title>{name}, {esc(label)}: {mu:.1f} ± {sd:.2f}</title>'
                     f'<line x1="{X(mu-sd):.1f}" y1="{yy}" x2="{X(mu+sd):.1f}" y2="{yy}" class="wh {cls}"/>'
                     f'<circle cx="{X(mu):.1f}" cy="{yy}" r="5.5" class="dot {cls}"/>'
                     f'<rect x="{X(mu-sd)-4:.1f}" y="{yy-8}" width="{X(mu+sd)-X(mu-sd)+8:.1f}" height="16" fill="transparent"/></g>')
        e, p = d["erm"][0], d["perf"][0]
        o.append(f'<text x="{x1}" y="{y+4}" text-anchor="end" class="tl">gap {p-e:+.1f}</text>')
    o.append('</svg>')
    return "\n".join(o)

def fm(v, f="{:.1f}", sign=False):
    t = ("{:+.1f}" if sign else f).format(v)
    return t.replace("-", "\u2212")

def dots_table(rows):
    return "".join(f'<tr><td>{esc(l)}</td><td class="num">{fm(d["erm"][0])} ± {d["erm"][1]:.2f}</td>'
                   f'<td class="num">{fm(d["perf"][0])} ± {d["perf"][1]:.2f}</td><td class="num">{fm(d["perf"][0]-d["erm"][0], sign=True)}</td></tr>'
                   for l, d in rows)

def forest(effects):
    """effects: list of (label, effect, lo, hi, filled, note)"""
    W, x0, x1, top, step = 760, 330, 735, 34, 28
    lo, hi = -40, 15
    X = lambda v: x0 + (v - lo) / (hi - lo) * (x1 - x0)
    H = top + step * len(effects) + 26
    o = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Effect of each hypothesis branch on target accuracy, in points, with 95% confidence intervals. Filled dots survive a Holm correction across all exploratory effects.">']
    for v in range(lo, 11, 10):
        o.append(f'<line x1="{X(v):.1f}" y1="{top-16}" x2="{X(v):.1f}" y2="{H-26}" class="{"axis0" if v == 0 else "grid"}"/>')
        o.append(f'<text x="{X(v):.1f}" y="{H-8}" text-anchor="middle" class="tl">{("+" if v>0 else ("−" if v<0 else "")) + str(abs(v))}</text>')
    for i, (label, e, a, b, filled, note) in enumerate(effects):
        y = top + i * step
        o.append(f'<text x="{x0-14}" y="{y+4}" text-anchor="end" class="ts">{esc(label)}</text>')
        o.append(f'<g><title>{esc(label)}: {e:+.1f} (95% CI {a:+.1f} to {b:+.1f}); {esc(note)}</title>'
                 f'<line x1="{X(max(a,lo)):.1f}" y1="{y}" x2="{X(min(b,hi)):.1f}" y2="{y}" class="wh fx"/>'
                 f'<circle cx="{X(e):.1f}" cy="{y}" r="5" class="{"dot fx" if filled else "dot-open"}"/>'
                 f'<rect x="{X(max(a,lo))-4:.1f}" y="{y-9}" width="{X(min(b,hi))-X(max(a,lo))+8:.1f}" height="18" fill="transparent"/></g>')
    o.append('</svg>')
    return "\n".join(o)

SHORT = {"h_select_valloss": "h1 cross-entropy rule", "h_select_valloss_total": "h1b full-objective rule",
         "h_omission_plain_sgd": "h2 plain SGD", "h_plain_sgd_1000ep": "h2 check, 1000 epochs",
         "h_combined": "h1 + h2", "naive_target_0.9_3m": "h3 target p = 0.9",
         "h_omission_constant_penalty": "h4 constant penalty weight"}
NAMES = {"erm": "ERM", "rand": "RandMatch", "perf": "PerfMatch"}

def forest_rows(g):
    rows = []
    for br, d in g["effects"].items():
        for k in ("perf", "rand", "erm"):
            if k in d:
                x = d[k]
                note = "survives Holm" if x["survives_holm"] else ("CI excludes 0, not after Holm" if x["detectable"] else "no detectable effect")
                rows.append((f"{SHORT[br]} · {NAMES[k]}", x["effect"], x["ci"][0], x["ci"][1], x["survives_holm"], note))
    for k in ("perf", "erm"):
        x = g["confirmation"][k]
        rows.append((f"h1 confirmation, fresh seeds · {NAMES[k]}", x["effect"], x["ci"][0], x["ci"][1], True, "pre-specified confirmation"))
    return rows

def t11_chart(sets):
    """Six-domain average per method: paper (open diamond) vs each of our run sets (dot with 95% CI over runs).
    sets: [(grades_lenet dict, short label, css class, filled?)], drawn top to bottom within each method."""
    from scipy import stats
    import math
    names = [("erm", "ERM"), ("rand", "RandMatch"), ("matchdg", "MatchDG (the paper's method)"), ("perf", "PerfMatch (oracle)")]
    rows = []
    for k, label in names:
        marks = []
        for gx, slabel, cls, filled in sets:
            a = gx["average"].get(k)
            if not a: continue
            xs = a["per_run"]; n = len(xs); mu = sum(xs) / n
            sd = math.sqrt(sum((x - mu) ** 2 for x in xs) / (n - 1)); t = stats.t.ppf(0.975, n - 1)
            marks.append((slabel, cls, filled, mu, mu - t * sd / math.sqrt(n), mu + t * sd / math.sqrt(n), a["paper"]["mean"]))
        if marks: rows.append((label, marks))
    W, x0, x1, top, sub = 760, 250, 735, 40, 16
    step = 30 + sub * max(len(m) for _, m in rows)
    vals = [v for _, ms in rows for m in ms for v in (m[4], m[5], m[6])]
    lo = math.floor(min(vals)) - 1; hi = min(100, math.ceil(max(vals)) + 1)
    X = lambda v: x0 + (min(max(v, lo), hi) - lo) / (hi - lo) * (x1 - x0)
    H = top + step * len(rows) + 10
    o = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Six-domain average accuracy on Rotated MNIST with LeNet: the paper versus each of our runs (mean of 3 runs with 95% confidence interval), for ERM, RandMatch, MatchDG and PerfMatch.">']
    for v in range(lo, hi + 1):
        o.append(f'<line x1="{X(v):.1f}" y1="{top-18}" x2="{X(v):.1f}" y2="{H-24}" class="grid"/>')
        o.append(f'<text x="{X(v):.1f}" y="{H-6}" text-anchor="middle" class="tl">{v}%</text>')
    for i, (label, marks) in enumerate(rows):
        y0 = top + i * step
        yc = y0 + sub * (len(marks) - 1) / 2
        o.append(f'<text x="{x0-14}" y="{yc+4:.1f}" text-anchor="end" class="t">{esc(label)}</text>')
        pm = marks[0][6]
        o.append(f'<path d="M{X(pm):.1f},{yc-9:.1f} l9,9 l-9,9 l-9,-9 z" class="dmd"/>')
        for j, (slabel, cls, filled, mu, a, b, _) in enumerate(marks):
            y = y0 + j * sub
            dot = f'<circle cx="{X(mu):.1f}" cy="{y}" r="4.5" class="dot {cls}"/>' if filled else f'<circle cx="{X(mu):.1f}" cy="{y}" r="4" class="dot-open"/>'
            o.append(f'<g><title>{esc(label)}, {esc(slabel)}: ours {mu:.2f} (95% CI {a:.2f} to {b:.2f}); paper {pm:.1f}</title>'
                     f'<line x1="{X(a):.1f}" y1="{y}" x2="{X(b):.1f}" y2="{y}" class="wh {cls if filled else "fx"}"/>{dot}</g>')
    o.append('</svg>')
    return "\n".join(o)

if __name__ == "__main__":
    g = json.loads((R / "grades.json").read_text())
    rows = dot_rows()
    C = Path("/home/claude/spike/charts"); C.mkdir(exist_ok=True)
    (C / "dots.svg").write_text(dot_chart(rows))
    (C / "dots_table.html").write_text(dots_table(rows))
    fr = forest_rows(g)
    (C / "forest.svg").write_text(forest(fr))
    L = R / "matchdg_lenet" / "grades_lenet.json"
    LC = R / "matchdg_lenet_confirm" / "grades_lenet_confirm.json"
    sets = []
    if L.exists(): sets.append((json.loads(L.read_text()), "first run, MNIST subsets 0-2", "fx", False))
    if LC.exists(): sets.append((json.loads(LC.read_text()), "confirmation, fresh subsets 3-5", "s1", True))
    if sets: (C / "t11.svg").write_text(t11_chart(sets))
    print(len(rows), "dot rows,", len(fr), "effects")
