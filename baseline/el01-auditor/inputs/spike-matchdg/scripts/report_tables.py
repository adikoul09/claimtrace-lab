"""Renders the report's tables from grades.json and epochs.json, so no number in the report is typed by hand.
Usage: report_tables.py <template.md> <out.md>   (replaces {{TABLE_NAME}} placeholders)"""
import json, sys
from pathlib import Path

R = Path("/home/claude/spike/runs")
g = json.loads((R / "grades.json").read_text())
ep = json.loads((R / "epochs.json").read_text())
N = {"erm": "ERM", "rand": "RandMatch", "perf": "PerfMatch", "mmd": "MMD", "coral": "CORAL", "dann": "DANN",
     "c-mmd": "C-MMD", "c-coral": "C-CORAL", "c-dann": "CDANN"}

def f(v, sign=False, d=1):
    s = (f"{v:+.{d}f}" if sign else f"{v:.{d}f}")
    return s.replace("-", "−")

def ci(a, d=1):
    return f"{f(a[0], d=d)} to {f(a[1], d=d)}"

def setup_short(st):
    """'yes: F1, F2' or 'no', from the setup flag computed by verdicts.setup_flag."""
    if not st["differs"]: return "no"
    ids = []
    for r in st["reasons"]:
        if r.split()[0] not in ids: ids.append(r.split()[0])
    return "yes: " + ", ".join(ids)

def setup_notes(items):
    """Bulleted reasons and notes for each claim, so every 'setup differs' can be traced to its rule."""
    out = []
    for name, v in items:
        st = v["setup"]
        out.append(f"- **{name}**: " + ("; ".join(st["reasons"]) if st["reasons"] else "no reason (nothing filled, no Holm-surviving effect)")
                   + (f". Notes: {'; '.join(st['notes'])}." if st["notes"] else "."))
    return "\n".join(out)

def verdicts():
    rows = ["| Claim (Table 1, target accuracy) | Paper | Ours | Δ (95% CI) | 90% CI inside ±margin? | Tightest margin the data supports | Verdict | Setup differs |",
            "|---|---|---|---|---|---|---|---|"]
    for k, v in g["absolute"].items():
        eq = "yes" if -v["margin"] < v["ci90"][0] and v["ci90"][1] < v["margin"] else "no"
        rows.append(f"| {N[k]} | {v['paper']['mean']:.1f} ± {v['paper']['sd']:.2f} | {v['ours']['mean']:.1f} ± {v['ours']['sd']:.2f} | "
                    f"{f(v['delta'], True)} ({ci(v['ci95'])}) | {eq} (±{v['margin']:.2f}) | ±{v['min_margin_for_equivalence']:.1f} | {v['label']} | {setup_short(v['setup'])} |")
    return "\n".join(rows)

def relative():
    rows = ["| Claim | Paper gap | Our gap, paired (95% CI) | Our gap − paper gap (95% CI, both uncertainties) | Verdict | Setup differs |", "|---|---|---|---|---|---|"]
    lab = {"perf_vs_erm": "PerfMatch (oracle) beats ERM", "perf_vs_rand": "PerfMatch (oracle) beats RandMatch"}
    for k, v in g["relative"].items():
        rows.append(f"| {lab[k]} | {f(v['paper_gap'], True)} | {f(v['ours_gap'], True)} ({ci(v['ours_ci95'])}) | "
                    f"{f(v['gap_difference'], True)} ({ci(v['gap_difference_ci95'])}) | {v['label']} | {setup_short(v['setup'])} |")
    return "\n".join(rows)

REL_NAMES = {"perf_vs_erm": "PerfMatch beats ERM", "perf_vs_rand": "PerfMatch beats RandMatch"}
def t1_setup():
    return setup_notes([(N[k], v) for k, v in g["absolute"].items()] + [(REL_NAMES[k], v) for k, v in g["relative"].items()])

def source():
    rows = ["| Method | Source 1 (p = 0.0) | Source 2 (p = 0.1) | Target (p = 1.0) | Epoch picked (median) | Target at last epoch |", "|---|---|---|---|---|---|"]
    for k, v in g["absolute"].items():
        s = ep["paper_target_1.0"][k]["summary"]
        rows.append(f"| {N[k]} | {v['source'].get('source_1', float('nan')):.1f} | {v['source'].get('source_2', float('nan')):.1f} | "
                    f"{v['ours']['mean']:.1f} | {s['selected_epoch_median']:g} | {s['last_target_acc']:.1f} |")
    return "\n".join(rows)

def effects():
    rows = ["| Branch | Method | Branch mean | Effect vs baseline (95% CI) | Holm-adjusted p | Epoch picked (median) | Source val. acc. at that epoch |",
            "|---|---|---|---|---|---|---|"]
    for br, d in g["effects"].items():
        for k in ("perf", "rand", "erm", "dann", "c-dann"):
            if k not in d: continue
            x = d[k]
            mark = "survives" if x["survives_holm"] else ("CI excludes 0, not after Holm" if x["detectable"] else "no detectable effect")
            rows.append(f"| {d['label']} | {N[k]} | {x['branch_mean']:.1f} | {f(x['effect'], True)} ({ci(x['ci'])}) | "
                        f"{x['p_holm']:.1e} ({mark}) | {x['selected_epoch_median']:g} | {x['source_val_acc']:.1f} |")
    for k, x in g["confirmation"].items():
        rows.append(f"| h1 confirmation, fresh seeds 10–19 vs their own baseline | {N[k]} | {x['branch_mean']:.1f} | "
                    f"{f(x['effect'], True)} ({ci(x['ci'])}) | {x['p']:.1e} (pre-specified, not in Holm family) | {x['selected_epoch_median']:g} | |")
    return "\n".join(rows)

def baseline_selection():
    rows = ["| Method | Epoch picked by the code's rule (median) | Target at that epoch | Target at last epoch |", "|---|---|---|---|"]
    for k, x in g["selection"].items():
        rows.append(f"| {N[k]} | {x['selected_epoch_median']:g} | {x['selected_target']:.1f} | {x['last_epoch_target']:.1f} |")
    return "\n".join(rows)

def tuning():
    rows = ["| Method | λ | Source val. acc. (seeds 0–2) | Target (seeds 0–2) | Target (10 seeds) |", "|---|---|---|---|---|"]
    for k, d in g["tuning_h5"].items():
        for lam in ("0.1", "1.0", "10.0"):
            x = d["grid"][lam]
            rows.append(f"| {N[k]} | {lam} | {x['source_val_acc_first3']:.2f} | {x['target_first3']:.1f} | {x['target_10']:.1f} |")
    return "\n".join(rows)

T = {"VERDICTS": verdicts, "RELATIVE": relative, "SOURCE": source, "EFFECTS": effects, "SELECTION": baseline_selection, "TUNING": tuning}

# ---- MatchDG itself: Suppl. Table 11 (Rotated MNIST, LeNet), two run sets ----
# first: MNIST subsets 0-2, rule v1 (margin = paper sd) pre-registered, 1-point floor declared after the run.
# confirm: fresh subsets 3-5, rule v2 with the 1-point floor pre-registered (runs/matchdg_lenet_confirm/PREREGISTERED.txt).
L = Path("/home/claude/spike/runs/matchdg_lenet/grades_lenet.json")
gl = json.loads(L.read_text()) if L.exists() else None
LC = Path("/home/claude/spike/runs/matchdg_lenet_confirm/grades_lenet_confirm.json")
glc = json.loads(LC.read_text()) if LC.exists() else None
SETS = {"first": gl, "confirm": glc}
LN = {"erm": "ERM", "rand": "RandMatch", "matchdg": "**MatchDG** (the paper's method)", "perf": "PerfMatch (oracle)"}
DOM = ["0", "15", "30", "45", "60", "75"]
SHORTV = {"Reproduced": "R", "Inconclusive": "I", "Not reproduced": "N", "Partially reproduced": "P"}
REL11 = {"matchdg_vs_erm": "MatchDG beats ERM", "matchdg_vs_rand": "MatchDG beats RandMatch", "perf_vs_matchdg": "PerfMatch (oracle) beats MatchDG"}

def claims11(gx):
    return [c for d in gx["cells"].values() for c in d.values()] + list(gx["average"].values())

def count11(gx, verdict, field="verdict", scope="all"):
    cs = [c for d in gx["cells"].values() for c in d.values()] if scope == "cells" else list(gx["average"].values()) if scope == "avg" else claims11(gx)
    return sum(1 for c in cs if c[field] == verdict)

def t11_cells_of(gx, both=False):
    rows = ["| Method | " + " | ".join(f"{d}°" for d in DOM) + " | Average |", "|---|" + "---|" * 7]
    def cell(c):
        v = f"{SHORTV[c['verdict_paper_sd_only']]}, {SHORTV[c['verdict']]}" if both else SHORTV[c["verdict"]]
        return f"{c['ours']['mean']:.1f} / {c['paper']['mean']:.1f} {v}"
    for m, name in LN.items():
        c = gx["cells"].get(m, {}); a = gx["average"].get(m)
        rows.append(f"| {name} | " + " | ".join(cell(c[d]) if d in c else "running" for d in DOM) + f" | {cell(a) if a else 'running'} |")
    return "\n".join(rows)

def t11_cells(): return t11_cells_of(glc) if glc else "Confirmation runs in progress."
def t11_cells_first(): return t11_cells_of(gl, both=True)

def t11_summary():
    rows = ["| Run | Margin | Margin declared | Reproduced | Inconclusive | Not reproduced | MatchDG beats ERM |", "|---|---|---|---|---|---|---|"]
    def row(name, gx, field, margin, when, rel):
        rows.append(f"| {name} | {margin} | {when} | {count11(gx, 'Reproduced', field)} | {count11(gx, 'Inconclusive', field)} | "
                    f"{count11(gx, 'Not reproduced', field)} | {rel} |")
    row("First, MNIST subsets 0–2", gl, "verdict_paper_sd_only", "paper's sd", "before the run", gl["relative"]["matchdg_vs_erm"]["label"])
    row("First, MNIST subsets 0–2", gl, "verdict", "max(paper's sd, 1 point)", "after the run", gl["relative"]["matchdg_vs_erm"]["label"])
    if glc: row("**Confirmation, fresh subsets 3–5**", glc, "verdict", "max(paper's sd, 1 point)", "**before the run**", glc["relative"]["matchdg_vs_erm"]["label"])
    return "\n".join(rows) + "\n\nCounts are over 28 claims: 24 cells and 4 six-domain averages."

def t11_counts():
    gx = glc or gl
    rows = ["| Method | Reproduced | Inconclusive | Not reproduced | Median tightest margin the data supports (points) |", "|---|---|---|---|---|"]
    for m, name in LN.items():
        c = list(gx["cells"].get(m, {}).values())
        k = [SHORTV[x["verdict"]] for x in c]
        mm = sorted(x["min_margin_for_equivalence"] for x in c)
        med = (mm[len(mm)//2] if len(mm) % 2 else (mm[len(mm)//2-1] + mm[len(mm)//2]) / 2) if mm else float("nan")
        rows.append(f"| {name} | {k.count('R')} | {k.count('I')} | {k.count('N')} | {med:.1f} |")
    return "\n".join(rows)

def t11_notrep():
    gx = glc or gl
    out = []
    for m, name in LN.items():
        for d, x in gx["cells"].get(m, {}).items():
            if x["verdict"] == "Not reproduced":
                out.append(f"| {name.replace('**','')} | {d}° | {x['paper']['mean']:.1f} ± {x['paper']['sd']:.1f} | {x['ours']['mean']:.1f} ± {x['ours']['sd']:.2f} | {f(x['delta'], True)} ({ci(x['ci95'])}) |")
    if not out: return "No cell is Not reproduced: every 95% CI of (ours − paper) contains 0."
    return "\n".join(["Cells outside the paper's range:", "", "| Method | Test domain | Paper | Ours | Δ (95% CI) |", "|---|---|---|---|---|"] + out)

def t11_avg_of(gx):
    rows = ["| Six-domain average | Paper | Ours, mean over 3 runs | Δ (95% CI) | Tightest margin the data supports | Margin used | Verdict |", "|---|---|---|---|---|---|---|"]
    for m, name in LN.items():
        a = gx["average"].get(m)
        if not a: continue
        rows.append(f"| {name} | {a['paper']['mean']:.1f} | {a['ours']['mean']:.2f} ± {a['ours']['sd_pop']:.2f} | {f(a['delta'], True, 2)} ({ci(a['ci95'], 2)}) | "
                    f"±{a['min_margin_for_equivalence']:.2f} | ±{a['margin']:.2f} ({a['margin_source']}) | {a['label']} |")
    return "\n".join(rows)
def t11_avg(): return t11_avg_of(glc or gl)
def t11_avg_first(): return t11_avg_of(gl)

def t11_rel():
    head = "| Claim (six-domain average) | Paper gap | First run: our gap (95% CI) | Verdict |" + (" Confirmation: our gap (95% CI) | Verdict |" if glc else "")
    rows = [head, "|---|---|---|---|" + ("---|---|" if glc else "")]
    for k, v in gl["relative"].items():
        r = f"| {REL11[k]} | {f(v['paper_gap'], True)} | {f(v['ours_gap'], True, 2)} ({ci(v['ours_ci95'], 2)}) | {v['label']} |"
        if glc:
            w = glc["relative"][k]; r += f" {f(w['ours_gap'], True, 2)} ({ci(w['ours_ci95'], 2)}) | {w['label']} |"
        rows.append(r)
    return "\n".join(rows)

def with_f7(k, v):
    """Add the F7 branch (graded by scripts/grade_f7.py) to a Table 11 claim that names MatchDG: a reason if its
    pre-registered test flags it (grades_f7.json setup_reason_for), else a "tested" note."""
    if not f7_ready() or "matchdg" not in k.split("_vs_"): return v
    v = json.loads(json.dumps(v)); st = v["setup"]
    if g7.get("setup_reason_for"):
        st["reasons"].append("F7 (h7) moves MatchDG: " + "; ".join(g7["setup_reason_for"])); st["differs"] = True
    else:
        st["notes"].append("F7 tested (h7, MatchDG only): no Holm-surviving effect")
    return v

def t11_setup():
    gx = glc or gl
    return setup_notes([(REL11[k], with_f7(k, v)) for k, v in gx["relative"].items()])

def t11_prior():
    gx = glc or gl
    rows = ["| Test domain | Best prior work in Table 11 | RandMatch, ours (95% CI) | MatchDG, ours (95% CI) |", "|---|---|---|---|"]
    for d in DOM:
        r, m = gx["prior_work"]["rand"].get(d), gx["prior_work"]["matchdg"].get(d)
        if not (r and m): continue
        cell = lambda x: f"{x['ours_mean']:.1f} ({ci(x['ci95'])}): {x['result'].split(' (')[0] if d != '0' else 'not graded'}"
        rows.append(f"| {d}° | {r['best_prior']:.1f} ({r['best_prior_name']}) | {cell(r)} | {cell(m)} |")
    return "\n".join(rows)

C = Path("/home/claude/spike/runs/run_counts.json")
cnt = json.loads(C.read_text()) if C.exists() else None
def total_runs(): return str(cnt["totals"]["slab"]["runs"] + cnt["totals"]["lenet"]["runs"])
def total_min(): return str(cnt["totals"]["slab"]["minutes"] + cnt["totals"]["lenet"]["minutes"])
def slab_runs(): return str(cnt["totals"]["slab"]["runs"])
def slab_min(): return str(cnt["totals"]["slab"]["minutes"])
def lenet_runs(): return str(cnt["totals"]["lenet"]["runs"])
def lenet_min(): return str(cnt["totals"]["lenet"]["minutes"])
def h2_long():
    d = g["effects"]["h_plain_sgd_1000ep"]
    return (f"PerfMatch {d['perf']['branch_mean']:.1f}, {f(d['perf']['effect'], True)} against the code's settings, 95% CI {ci(d['perf']['ci'])}; "
            f"ERM {d['erm']['branch_mean']:.1f}, {f(d['erm']['effect'], True)}, CI {ci(d['erm']['ci'])}")

def effects_compact():
    """Branch x method table: effect (95% CI), with a dagger when it survives Holm."""
    rows = ["| Branch | ERM | RandMatch | PerfMatch (oracle) | PerfMatch: epoch picked (median), source val. acc. |", "|---|---|---|---|---|"]
    for br, d in g["effects"].items():
        if br == "h_dann_lr": continue
        cell = lambda k: (f"{f(d[k]['effect'], True)} ({ci(d[k]['ci'])})" + (" ✓" if d[k]["survives_holm"] else "")) if k in d else \
            ("same as h1 (ERM has no matching term)" if (br, k) == ("h_select_valloss_total", "erm") else "not run")
        ep_ = f"{d['perf']['selected_epoch_median']:g}, {d['perf']['source_val_acc']:.1f}%" if "perf" in d else ""
        rows.append(f"| {d['label']} | {cell('erm')} | {cell('rand')} | {cell('perf')} | {ep_} |")
    x = g["confirmation"]
    rows.append(f"| h1 confirmation, fresh seeds 10–19 | {f(x['erm']['effect'], True)} ({ci(x['erm']['ci'])}) | not run | {f(x['perf']['effect'], True)} ({ci(x['perf']['ci'])}) | {x['perf']['selected_epoch_median']:g} |")
    return "\n".join(rows)

def verdicts_compact():
    rows = ["| Claim (Table 1, target accuracy) | Paper | Ours | Δ (95% CI) | Tightest margin the data supports | Verdict | Setup differs |", "|---|---|---|---|---|---|---|"]
    for k, v in g["absolute"].items():
        rows.append(f"| {N[k]}{' (oracle)' if k == 'perf' else ''} | {v['paper']['mean']:.1f} ± {v['paper']['sd']:.2f} | {v['ours']['mean']:.1f} ± {v['ours']['sd']:.2f} | "
                    f"{f(v['delta'], True)} ({ci(v['ci95'])}) | ±{v['min_margin_for_equivalence']:.1f} | {v['label']} | {setup_short(v['setup'])} |")
    return "\n".join(rows)

T.update({"T11_CELLS": t11_cells, "T11_CELLS_FIRST": t11_cells_first, "T11_SUMMARY": t11_summary, "T11_AVG_FIRST": t11_avg_first,
          "T11_SETUP": t11_setup, "T1_SETUP": t1_setup, "T11_COUNTS": t11_counts, "T11_NOTREP": t11_notrep, "T11_AVG": t11_avg, "T11_REL": t11_rel,
          "T11_PRIOR": t11_prior, "TOTAL_RUNS": total_runs, "TOTAL_MIN": total_min, "SLAB_RUNS": slab_runs, "SLAB_MIN": slab_min,
          "LENET_RUNS": lenet_runs, "LENET_MIN": lenet_min, "H2_LONG": h2_long, "EFFECTS_COMPACT": effects_compact,
          "VERDICTS_COMPACT": verdicts_compact})

import re
LINKS = json.loads(Path("/home/claude/spike/docs/links.json").read_text())
def lenet_job():
    P = Path("/home/claude/spike/runs/matchdg_lenet/progress.txt")
    ls = [l for l in P.read_text().splitlines() if " in " in l] if P.exists() else []
    a = [int(l.split(" in ")[1].rstrip("s")) for l in ls if not l.startswith("matchdg")]
    b = [int(l.split(" in ")[1].rstrip("s")) for l in ls if l.startswith("matchdg")]
    return (f"{min(a)}–{max(a)} s for ERM, RandMatch or PerfMatch; {min(b)}–{max(b)} s for MatchDG (both phases)" if a and b else "")
def regression():
    P = R / "regression.json"
    if not P.exists(): return "not run yet"
    x = json.loads(P.read_text())
    return (f"{x['verdict_labels_checked']} verdicts and {x['graded_items_checked'] - x['verdict_labels_checked']} other graded numbers re-derived from the raw logs, "
            f"plus {x['extraction_checks']} extraction checks: {len(x['mismatches'])} mismatches ({x['when'][:10]})")
CAND = Path("/home/claude/spike/docs/candidates.json")
def candidates_md():
    if not CAND.exists(): return ""
    c = json.loads(CAND.read_text())
    lines = ["**Second-paper candidates** (picked from SciCoQA rows; the team stays blind to the discrepancy text until after the run):", ""]
    for x in c["picks"]:
        lines.append(f"- **{x['title']}** ({x['venue']}). {x['why']} Audit target: {x['table']}. Runtime: {x['runtime']}. Main risk: {x['risk']}")
    if c.get("backups"): lines.append(f"- Backups: {'; '.join(b['title'] for b in c['backups'])}.")
    return "\n".join(lines)
def n_effects(): return str(sum(1 for d in g["effects"].values() for x in d.values() if isinstance(x, dict) and "p_holm" in x))
T.update({"REGRESSION": regression, "CANDIDATES_MD": candidates_md, "EVIDENCE_URL": lambda: LINKS["evidence_url"], "EVIDENCE_LABEL": lambda: LINKS["evidence_label"], "LENET_JOB": lenet_job, "N_EFFECTS": n_effects})

# ---- F7 (SciCoQA row 67) branch test and the scaling numbers ----
F7P = R / "h7_no_flip" / "grades_f7.json"
g7 = json.loads(F7P.read_text()) if F7P.exists() else None
WC = json.loads((R / "wallclock.json").read_text()) if (R / "wallclock.json").exists() else {}
STR = json.loads((R / "selection_traces.json").read_text()) if (R / "selection_traces.json").exists() else None
def _mean(xs): return sum(xs) / len(xs)
def f7_ready(): return bool(g7) and not g7.get("missing") and "average" in g7
def f7_table():
    if not f7_ready(): return "F7 branch runs in progress."
    rows = ["| Test domain | MatchDG, shipped data | MatchDG, no flips | Effect, paired by run (95% CI) | Holm p | Same contrastive-phase checkpoint |",
            "|---|---|---|---|---|---|"]
    for d, c in g7["cells"].items():
        e = "0.00 (all 3 runs identical)" if c["base"] == c["branch"] else f"{f(c['effect'], True, 2)} ({ci(c['ci95'], 2)})"
        rows.append(f"| {d}° | {_mean(c['base']):.1f} | {_mean(c['branch']):.1f} | {e} | {c['p_holm']:.2f} | {c['same_ctr_epoch']} of {len(c['runs'])} runs |")
    a = g7["average"]
    rows.append(f"| **Six-domain average** (primary test) | {_mean(a['base']):.2f} | {_mean(a['branch']):.2f} | {f(a['effect'], True, 2)} ({ci(a['ci95'], 2)}) | | |")
    return "\n".join(rows)
def scaling():
    rc = json.loads((R / "run_counts.json").read_text())
    def row(name, runs, secs, wall):
        return f"| {name} | {runs} | {round(secs / 60)} min | {wall} |"
    sl = rc["slab"]; le = rc["lenet"]
    rows = ["| Run set | Training runs | Single-thread compute | Wall-clock |", "|---|---|---|---|",
            row("Table 1 (slab): baseline, all branches, fresh-seed confirmation", sum(v["runs"] for v in sl.values()), sum(v["seconds"] for v in sl.values()),
                "not separable (run sets overlapped)")]
    for k, name in (("matchdg_lenet", "Table 11, first run"), ("matchdg_lenet_confirm", "Table 11, confirmation"), ("h7_no_flip", "F7 branch, MatchDG only")):
        if k in le:
            w = WC.get(k)
            rows.append(row(name, le[k]["runs"], le[k]["seconds"], f"{w['wall_minutes']:.1f} min ({w['jobs']} jobs, {'6' if k == 'h7_no_flip' else '4'} at a time)" if w else "not measured"))
    rows.append(f"| **Whole audit** | {rc['totals']['slab']['runs'] + rc['totals']['lenet']['runs']} | {rc['totals']['slab']['minutes'] + rc['totals']['lenet']['minutes']} min | |")
    return "\n".join(rows)
T.update({"F7_TABLE": f7_table, "SCALING": scaling})

def inline(s):
    """{{E:branch:method}} effect with CI; {{EB:branch:method}} effect only; {{M:branch:method}} branch mean;
    {{C:method}} confirmation effect with CI; {{A:method:field}} absolute grade field; {{R:key:field}} relative grade field;
    {{L:cell:method:domain:field}} Table 11 cell; {{LA:method:field}} Table 11 average; {{LR:key:field}} Table 11 relative."""
    def rep(m):
        parts = m.group(1).split(":"); t = parts[0]
        if t == "E": x = g["effects"][parts[1]][parts[2]]; return f"{f(x['effect'], True)} (95% CI {ci(x['ci'])})"
        if t == "EB": return f(g["effects"][parts[1]][parts[2]]["effect"], True)
        if t == "M": return f"{g['effects'][parts[1]][parts[2]]['branch_mean']:.1f}"
        if t == "EP": return f"{g['effects'][parts[1]][parts[2]]['selected_epoch_median']:g}"
        if t == "SV": return f"{g['effects'][parts[1]][parts[2]]['source_val_acc']:.1f}"
        if t == "C": x = g["confirmation"][parts[1]]; return f"{f(x['effect'], True)} (95% CI {ci(x['ci'])})"
        if t == "CB": return f(g["confirmation"][parts[1]]["effect"], True)
        if t == "N11":  # N11:set:field:verdict[:scope]  field = floor | sd
            gx = SETS[parts[1]]; fld = "verdict" if parts[2] == "floor" else "verdict_paper_sd_only"
            if gx is None: return "(pending)"
            return str(count11(gx, parts[3], fld, parts[4] if len(parts) > 4 else "all"))
        if t in ("CA", "CR", "CMAX"):
            if not glc: return "(confirmation pending)"
            if t == "CMAX": return f"{max(abs(c['delta']) for d in glc['cells'].values() for c in d.values()):.1f}"
            if t == "CA": v = glc["average"][parts[1]]; return {"ours": f"{v['ours']['mean']:.1f}", "paper": f"{v['paper']['mean']:.1f}", "verdict": v["label"], "tight": f"{v['min_margin_for_equivalence']:.2f}"}[parts[2]]
            v = glc["relative"][parts[1]]; return {"ours": f(v["ours_gap"], True, 2), "ci": f"{f(v['ours_ci95'][0], d=2)} to {f(v['ours_ci95'][1], d=2)}", "paper": f(v["paper_gap"], True), "verdict": v["label"]}[parts[2]]
        if t == "LA": v = gl["average"][parts[1]]; return {"ours": f"{v['ours']['mean']:.1f}", "paper": f"{v['paper']['mean']:.1f}", "delta": f(v["delta"], True, 2), "ci": ci(v["ci95"], 2) if False else f"{f(v['ci95'][0], d=2)} to {f(v['ci95'][1], d=2)}", "verdict": v["label"], "tight": f"{v['min_margin_for_equivalence']:.2f}"}[parts[2]]
        if t == "LR": v = gl["relative"][parts[1]]; return {"ours": f(v["ours_gap"], True, 2), "ci": f"{f(v['ours_ci95'][0], d=2)} to {f(v['ours_ci95'][1], d=2)}", "paper": f(v["paper_gap"], True), "verdict": v["label"], "diffci": f"{f(v['gap_difference_ci95'][0], d=2)} to {f(v['gap_difference_ci95'][1], d=2)}"}[parts[2]]
        if t == "L": v = gl["cells"][parts[1]][parts[2]]; return {"ours": f"{v['ours']['mean']:.1f}", "paper": f"{v['paper']['mean']:.1f}", "verdict": v["verdict"], "delta": f(v["delta"], True)}[parts[3]]
        if t == "WALLEST":
            rc = json.loads((R / "run_counts.json").read_text()); return str(round((rc["totals"]["slab"]["minutes"] + rc["totals"]["lenet"]["minutes"]) / 4))
        if t == "LMAX": return f"{max(abs(c['delta']) for d in gl['cells'].values() for c in d.values()):.1f}"
        if t == "LAVGMAX": return f"{max(abs(v['delta']) for v in gl['average'].values()):.2f}"
        if t in ("LPRIOR", "LPRIOR1"):  # LPRIOR: confirmation run when graded, else first run; LPRIOR1: first run
            ds = [f"{d}°" for d, x in ((glc or gl) if t == "LPRIOR" else gl)["prior_work"][parts[1]].items() if x["result"].startswith(parts[2])]
            return "none" if not ds else ds[0] if len(ds) == 1 else ", ".join(ds[:-1]) + " and " + ds[-1]
        if t == "WALL": return f"{WC[parts[1]]['wall_minutes']:.1f}"
        if t == "SEL": return str({"runs": STR["selection_runs"], "checks": len(STR["checks"]), "lines": f"{sum(c['lines'] for c in STR['checks']):,}",
                                   "identical": "identical" if STR["all_identical"] else "NOT identical"}[parts[1]])
        if t == "F7":
            if not f7_ready(): return "(F7 pending)"
            if parts[1] == "avg":
                a = g7["average"]; return {"effect": f(a["effect"], True, 2), "ci": ci(a["ci95"], 2), "base": f"{_mean(a['base']):.2f}", "branch": f"{_mean(a['branch']):.2f}"}[parts[2]]
            if parts[1] == "same":
                return f"{sum(c['same_ctr_epoch'] for c in g7['cells'].values())} of {sum(len(c['runs']) for c in g7['cells'].values())}"
            if parts[1] == "holm": return str(sum(1 for c in g7["cells"].values() if c["survives_holm"]))
            if parts[1] == "data":  # scripts/check_f7_data.py
                dc = json.loads((R / "h7_no_flip" / "data_check.json").read_text())
                return {"plain": f"{dc['plain_and_label_identical']} of {dc['plain_and_label_files']}", "aug": f"{dc['augmented_images']:,}",
                        "flip": f"{dc['flip_only']:,}", "unchanged": f"{dc['unchanged']:,}", "other": str(dc["other"])}[parts[2]]
            pr = [(c, i, str(r)) for c in g7["cells"].values() for i, r in enumerate(c["runs"])]
            same = [(c, i) for c, i, r in pr if c["ctr_epoch_base"][r]["epoch"] == c["ctr_epoch_branch"][r]["epoch"]]
            chg = [(c, i) for c, i, r in pr if c["ctr_epoch_base"][r]["epoch"] != c["ctr_epoch_branch"][r]["epoch"]]
            if parts[1] == "changed": return f"{len(chg)} of {len(pr)}"
            if parts[1] == "same_identical": return f"{sum(c['base'][i] == c['branch'][i] for c, i in same)} of {len(same)}"
            if parts[1] == "changed_moved": return f"{sum(c['base'][i] != c['branch'][i] for c, i in chg)} of {len(chg)}"
            if parts[1] == "maxrun": return f"{max(abs(c['branch'][i] - c['base'][i]) for c, i, _ in pr):.1f}"
            if parts[1] == "topk":
                k = "ctr_epoch_base" if parts[2] == "base" else "ctr_epoch_branch"
                return f"{_mean([c[k][r]['topk_overlap'] for c, _, r in pr]):.0f}"
            if parts[1] == "maxcell": return f"{max(abs(c['effect']) for c in g7['cells'].values()):.2f}"
        if t == "LCOUNT": return str(sum(1 for d in gl["cells"].values() for c in d.values() if c["verdict"] == parts[1]))
        raise KeyError(m.group(0))
    return re.sub(r"\{\{((?:E|EB|M|EP|SV|C|CB|LA|LR|L|LPRIOR1|LPRIOR|LCOUNT|N11|CA|CR|WALL|SEL|F7):[^}]+|LMAX|LAVGMAX|CMAX|WALLEST)\}\}", rep, s)

if __name__ == "__main__":
    s = Path(sys.argv[1]).read_text()
    for k, fn in T.items():
        if "{{" + k + "}}" in s: s = s.replace("{{" + k + "}}", fn())
    s = inline(s)
    Path(sys.argv[2]).write_text(s)
    left = re.findall(r"\{\{[^}]+\}\}", s)
    print("written", sys.argv[2], "unfilled:", left)
