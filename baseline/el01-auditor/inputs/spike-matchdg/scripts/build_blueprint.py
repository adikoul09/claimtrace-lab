"""Fills the blueprint template with tables and charts rendered from grades.json, grades_lenet.json and run_counts.json,
so no number on the page is typed by hand. Usage: build_blueprint.py <template.html> <out.html>"""
import json, sys
from pathlib import Path

R = Path("/home/claude/spike/runs"); C = Path("/home/claude/spike/charts"); D = Path("/home/claude/spike/docs")
g = json.loads((R / "grades.json").read_text())
gl = json.loads((R / "matchdg_lenet" / "grades_lenet.json").read_text())
_lc = R / "matchdg_lenet_confirm" / "grades_lenet_confirm.json"
glc = json.loads(_lc.read_text()) if _lc.exists() else None
cnt = json.loads((R / "run_counts.json").read_text())
links = json.loads((D / "links.json").read_text())
N = {"erm": "ERM", "rand": "RandMatch", "perf": "PerfMatch", "mmd": "MMD", "coral": "CORAL", "dann": "DANN",
     "c-mmd": "C-MMD", "c-coral": "C-CORAL", "c-dann": "CDANN", "matchdg": "MatchDG"}

def f(v, sign=False, d=1):
    return (f"{v:+.{d}f}" if sign else f"{v:.{d}f}").replace("-", "−")
def ci(a, d=1): return f"{f(a[0], d=d)} to {f(a[1], d=d)}"
CLS = {"Reproduced": "c-ok", "Partially reproduced": "c-warn", "Not reproduced": "c-bad", "Inconclusive": "c-na"}
def chip(v):
    """v: a grade dict (uses its verdict for colour and its label for text) or a plain verdict string."""
    if isinstance(v, str): return f'<span class="chip {CLS[v]}">{v}</span>'
    return f'<span class="chip {CLS[v["verdict"]]}">{v["label"]}</span>'
SH = {"Reproduced": ("R", "c-ok"), "Inconclusive": ("I", "c-na"), "Not reproduced": ("N", "c-bad")}
def mini(v):
    t, c = SH[v]; return f'<span class="chip sm {c}" title="{v}">{t}</span>'
def setup_cell(st):
    if not st["differs"]:
        return '<span class="muted">no</span>'
    ids = []
    for r in st["reasons"]:
        if r.split()[0] not in ids: ids.append(r.split()[0])
    tip = "; ".join(st["reasons"]).replace('"', "'")
    return f'<span title="{tip}">yes: {", ".join(ids)}</span>'

def t11_table(gx):
    dom = ["0", "15", "30", "45", "60", "75"]
    head = "<thead><tr><th>Method</th>" + "".join(f"<th>{d}°</th>" for d in dom) + "<th>Average</th></tr></thead>"
    body = []
    for k, label in (("erm", "ERM"), ("rand", "RandMatch"), ("matchdg", "<b>MatchDG</b> <span class=\"muted\">paper's method</span>"), ("perf", "PerfMatch <span class=\"muted\">oracle</span>")):
        c = gx["cells"][k]; a = gx["average"][k]
        tds = "".join(f'<td class="num">{c[d]["ours"]["mean"]:.1f}<span class="muted"> / {c[d]["paper"]["mean"]:.1f}</span> {mini(c[d]["verdict"])}</td>' for d in dom)
        body.append(f'<tr><td>{label}</td>{tds}<td class="num">{a["ours"]["mean"]:.1f}<span class="muted"> / {a["paper"]["mean"]:.1f}</span> {mini(a["verdict"])}</td></tr>')
    return head + "<tbody>" + "".join(body) + "</tbody>"

def t11_rel():
    lab = {"matchdg_vs_erm": "MatchDG beats ERM", "matchdg_vs_rand": "MatchDG beats RandMatch", "perf_vs_matchdg": "PerfMatch (oracle) beats MatchDG"}
    rows = []
    for k, v in gl["relative"].items():
        r = f'<tr><td>{lab[k]}</td><td class="num">{f(v["paper_gap"], True)}</td><td class="num">{f(v["ours_gap"], True, 2)} <span class="muted">({ci(v["ours_ci95"], 2)})</span> {chip(v)}</td>'
        if glc:
            w = glc["relative"][k]
            r += f'<td class="num">{f(w["ours_gap"], True, 2)} <span class="muted">({ci(w["ours_ci95"], 2)})</span> {chip(w)}</td>'
        rows.append(r + "</tr>")
    return "".join(rows)

def t11_summary():
    def cnt(gx, fld, v): return sum(1 for c in [c for d in gx["cells"].values() for c in d.values()] + list(gx["average"].values()) if c[fld] == v)
    def row(name, gx, fld, margin, when, strong=False):
        b = (lambda x: f"<b>{x}</b>") if strong else (lambda x: x)
        return (f'<tr><td>{b(name)}</td><td>{margin}</td><td>{b(when)}</td><td class="num">{cnt(gx, fld, "Reproduced")}</td>'
                f'<td class="num">{cnt(gx, fld, "Inconclusive")}</td><td class="num">{cnt(gx, fld, "Not reproduced")}</td><td>{chip(gx["relative"]["matchdg_vs_erm"])}</td></tr>')
    rows = [row("First run, MNIST subsets 0–2", gl, "verdict_paper_sd_only", "paper's sd", "before the run"),
            row("First run, MNIST subsets 0–2", gl, "verdict", "max(paper's sd, 1 point)", "after the run")]
    if glc: rows.append(row("Confirmation, fresh subsets 3–5", glc, "verdict", "max(paper's sd, 1 point)", "before the run", True))
    return "".join(rows)

def t1_verdicts():
    rows = []
    for k, v in g["absolute"].items():
        name = N[k] + (' <span class="muted">oracle</span>' if k == "perf" else "")
        rows.append(f'<tr><td>{name}</td><td class="num">{v["paper"]["mean"]:.1f} ± {v["paper"]["sd"]:.2f}</td><td class="num">{v["ours"]["mean"]:.1f} ± {v["ours"]["sd"]:.2f}</td>'
                    f'<td class="num">{f(v["delta"], True)} <span class="muted">({ci(v["ci95"])})</span></td><td class="num">±{v["min_margin_for_equivalence"]:.1f} <span class="muted">vs ±{v["margin"]:.2f}</span></td><td>{chip(v)}</td><td>{setup_cell(v["setup"])}</td></tr>')
    return "".join(rows)

def t1_relative():
    lab = {"perf_vs_erm": "PerfMatch (oracle) beats ERM <span class=\"muted\">\"out-of-domain accuracy is now 78%\", p. 4</span>",
           "perf_vs_rand": "PerfMatch (oracle) beats RandMatch"}
    rows = []
    for k, v in g["relative"].items():
        rows.append(f'<tr><td>{lab[k]}</td><td class="num">{f(v["paper_gap"], True)}</td><td class="num">{f(v["ours_gap"], True)} <span class="muted">({ci(v["ours_ci95"])})</span></td>'
                    f'<td class="num">{f(v["gap_difference"], True)} <span class="muted">({ci(v["gap_difference_ci95"])})</span></td><td>{chip(v)}</td><td>{setup_cell(v["setup"])}</td></tr>')
    return "".join(rows)

def effects_table():
    rows = []
    for br, d in g["effects"].items():
        for k in ("perf", "rand", "erm", "dann", "c-dann"):
            if k not in d: continue
            x = d[k]
            mark = "survives Holm" if x["survives_holm"] else ("CI excludes 0, not after Holm" if x["detectable"] else "no detectable effect")
            rows.append(f'<tr><td>{d["label"]}</td><td>{N[k]}</td><td class="num">{x["branch_mean"]:.1f}</td><td class="num">{f(x["effect"], True)} <span class="muted">({ci(x["ci"])})</span></td>'
                        f'<td>{mark}</td><td class="num">{x["selected_epoch_median"]:g}</td><td class="num">{x["source_val_acc"]:.1f}</td></tr>')
    for k, x in g["confirmation"].items():
        rows.append(f'<tr><td>h1 confirmation, fresh seeds 10–19</td><td>{N[k]}</td><td class="num">{x["branch_mean"]:.1f}</td><td class="num">{f(x["effect"], True)} <span class="muted">({ci(x["ci"])})</span></td>'
                    f'<td>pre-specified test</td><td class="num">{x["selected_epoch_median"]:g}</td><td class="num"></td></tr>')
    return "".join(rows)

def eff(br, k):
    x = g["effects"][br][k]; return f"{f(x['effect'], True)}"

import hashlib, html as _h
def t1_setup_html():
    REL = {"perf_vs_erm": "PerfMatch beats ERM", "perf_vs_rand": "PerfMatch beats RandMatch"}
    items = [(N[k], v) for k, v in g["absolute"].items()] + [(REL[k], v) for k, v in g["relative"].items()]
    lis = []
    for name, v in items:
        st = v["setup"]
        lis.append(f'<li><b>{name}</b>: {_h.escape("; ".join(st["reasons"]) or "no reason")}'
                   + (f'<span class="muted">. Notes: {_h.escape("; ".join(st["notes"]))}</span>' if st["notes"] else "") + "</li>")
    return '<ul class="setup-list">' + "".join(lis) + "</ul>"
def candidates_html():
    P = D / "candidates.json"
    if not P.exists(): return ""
    c = json.loads(P.read_text())
    rows = "".join(f'<tr><td><b>{_h.escape(x["title"])}</b><br><span class="muted">{_h.escape(x["venue"])}</span></td><td>{_h.escape(x["why"])}</td>'
                   f'<td>{_h.escape(x["table"])}</td><td>{_h.escape(x["runtime"])}</td><td>{_h.escape(x["risk"])}</td></tr>' for x in c["picks"])
    back = f'<p class="note">Backups: {_h.escape("; ".join(b["title"] for b in c.get("backups", [])))}.</p>' if c.get("backups") else ""
    return ('<h3 class="sub">Second-paper candidates</h3><p class="col muted">Picked from SciCoQA rows. The team stays blind to each row\'s discrepancy text until after the run.</p>'
            '<div class="tbl"><table><thead><tr><th>Paper</th><th>Why</th><th>Audit target</th><th>CPU runtime</th><th>Main risk</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div>{back}')
OUTDIR = Path(sys.argv[2]).parent
MAN = OUTDIR / "evidence" / "manifest.json"
EVIDENCE_SHA = hashlib.sha256(MAN.read_bytes()).hexdigest() if MAN.exists() else "(stage the evidence first)"
FREEZE = links.get("freeze_note", "A tag in a public fork of microsoft/robustdg (<span class=\"mono\">round0-submission</span>) will freeze the same files.")
sys.path.insert(0, str(Path(__file__).parent))
from report_tables import regression as _regression

def t11_oneline():
    gx = glc or gl
    allc = [c for d in gx["cells"].values() for c in d.values()] + list(gx["average"].values())
    k = {v: sum(1 for c in allc if c["verdict"] == v) for v in ("Reproduced", "Inconclusive", "Not reproduced")}
    mx = max(abs(c["delta"]) for d in gx["cells"].values() for c in d.values())
    run = "In a re-run on fresh data with the rule fixed beforehand" if glc else "In our first run"
    return (f"{run}, {k['Reproduced']} of 28 numbers are Reproduced within max(paper's sd, 1 point), {k['Inconclusive']} Inconclusive and "
            f"{k['Not reproduced']} Not reproduced; every cell is within {mx:.1f} points of the paper.")
def regression_short():
    P = R / "regression.json"
    if not P.exists(): return "not run yet"
    x = json.loads(P.read_text()); return f"{x['verdict_labels_checked']} verdicts re-derived from raw logs, {len(x['mismatches'])} mismatches"

import re as _re
from report_tables import f7_table as _f7_table, scaling as _scaling
def md_table_html(md):
    """A rendered markdown table (from report_tables) as HTML rows, so the page and the report share one source."""
    ls = [l for l in md.strip().splitlines() if l.startswith("|")]
    if len(ls) < 2: return f'<tbody><tr><td>{_h.escape(md)}</td></tr></tbody>'
    cells = lambda l: [c.strip() for c in l.strip("|").split("|")]
    b = lambda c: _re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", _h.escape(c))
    num = lambda c: bool(_re.match(r"^[−+\d.,]", c))
    head = "<thead><tr>" + "".join(f"<th>{b(c)}</th>" for c in cells(ls[0])) + "</tr></thead>"
    body = "".join("<tr>" + "".join(f'<td class="num">{b(c)}</td>' if num(c) else f"<td>{b(c)}</td>" for c in cells(l)) + "</tr>" for l in ls[2:])
    return head + "<tbody>" + body + "</tbody>"

lenet_secs = [int(l.split(" in ")[1].rstrip("s")) for l in (R / "matchdg_lenet" / "progress.txt").read_text().splitlines() if " in " in l]
V = {
    "T11_TABLE": t11_table(glc or gl), "T11_REL": t11_rel(), "T11_SUMMARY": t11_summary(),
    "T11_REL_HEAD": ('<th>Confirmation: our gap (95% CI), verdict</th>' if glc else ''), "T1_VERDICTS": t1_verdicts(), "T1_RELATIVE": t1_relative(), "EFFECTS_TABLE": effects_table(),
    "DOTS_SVG": (C / "dots.svg").read_text(), "DOTS_TABLE": (C / "dots_table.html").read_text(), "FOREST_SVG": (C / "forest.svg").read_text(),
    "T11_SVG": (C / "t11.svg").read_text() if (C / "t11.svg").exists() else "",
    "TOTAL_RUNS": str(cnt["totals"]["slab"]["runs"] + cnt["totals"]["lenet"]["runs"]),
    "TOTAL_MIN": str(cnt["totals"]["slab"]["minutes"] + cnt["totals"]["lenet"]["minutes"]),
    "SLAB_RUNS": str(cnt["totals"]["slab"]["runs"]), "LENET_RUNS": str(cnt["totals"]["lenet"]["runs"]),
    "N_EFFECTS": str(sum(1 for d in g["effects"].values() for x in d.values() if isinstance(x, dict) and "p_holm" in x)),
    "H1_PERF": eff("h_select_valloss", "perf"), "H2_PERF": eff("h_omission_plain_sgd", "perf"), "H12_PERF": eff("h_combined", "perf"),
    "H1B_PERF": eff("h_select_valloss_total", "perf"), "H2L_PERF": eff("h_plain_sgd_1000ep", "perf"),
    "H1C_PERF": f(g["confirmation"]["perf"]["effect"], True),
    "H3_RAND": f"{g['effects']['naive_target_0.9_3m']['rand']['branch_mean']:.1f}",
    "EVIDENCE_URL": links["evidence_url"], "EVIDENCE_LABEL": links["evidence_label"],
    "LENET_JOB": f"{min(lenet_secs)}–{max(lenet_secs)} s" if lenet_secs else "",
    "T1_SETUP_HTML": t1_setup_html(), "CANDIDATES_HTML": candidates_html(), "REGRESSION": _regression(),
    "EVIDENCE_SHA": EVIDENCE_SHA, "FREEZE_NOTE": FREEZE, "EVIDENCE_SHA16": EVIDENCE_SHA[:16],
    "SCALING_HTML": md_table_html(_scaling()), "F7_HTML": md_table_html(_f7_table()),
    "T11_ONELINE": t11_oneline(), "REGRESSION_SHORT": regression_short(), "TEAM": links.get("team", "(names pending)"),
}
s = Path(sys.argv[1]).read_text()
for k, v in V.items(): s = s.replace("{{" + k + "}}", v)
sys.path.insert(0, str(Path(__file__).parent))
from report_tables import inline
s = inline(s)
Path(sys.argv[2]).write_text(s)
import re
print("written", sys.argv[2], "unfilled:", sorted(set(re.findall(r"\{\{(\w+)\}\}", s))))
