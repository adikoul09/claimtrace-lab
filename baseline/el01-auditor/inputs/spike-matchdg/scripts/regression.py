"""MatchDG as the regression test. Re-derives every MatchDG output from the raw inputs and compares it with the golden
outputs in golden/: the hand-built claim tables (Table 1 and Table 11 paper values), the hand-built settings diff
(F1-F6), and every verdict, number and "setup differs" flag the graders produce. Any change to the pipeline (parsers,
graders, extractors) must leave this at 0 mismatches before it ships.
Usage: regression.py            check, write runs/regression.json, exit 1 on any mismatch
       regression.py --update   rewrite golden/ from the current outputs (only after a reviewed rule change)"""
import json, os, subprocess, sys, tempfile
from datetime import datetime, timezone
from pathlib import Path

S = Path("/home/claude/spike"); R = S / "runs"; G = S / "golden"; PY = sys.executable
sys.path.insert(0, str(S / "scripts"))
import extraction_diff as xd
from grade import PAPER as T1_PAPER
from grade_lenet import PAPER as T11_PAPER, PAPER_AVG as T11_AVG, DOMAINS
from verdicts import FINDINGS

RUNSETS = {"first": R / "matchdg_lenet", "confirm": R / "matchdg_lenet_confirm"}

def grade_all(tmp):
    """Re-parse every log, then run both graders into tmp. Parsers rewrite metrics.json in place (deterministic)."""
    for d in sorted(p for p in R.iterdir() if p.is_dir() and list(p.glob("train_*.log")) and not p.name.startswith("matchdg_lenet")):
        subprocess.run([PY, str(S / "scripts/parse_runs.py"), str(d)], check=True, capture_output=True)
    subprocess.run([PY, str(S / "scripts/parse_epochs.py")], check=True, capture_output=True)
    subprocess.run([PY, str(S / "scripts/grade.py")], check=True, capture_output=True, env={**os.environ, "GRADES_OUT": str(tmp / "grades.json")})
    out = {"table1": json.loads((tmp / "grades.json").read_text())}
    for name, d in RUNSETS.items():
        if (d / "progress.txt").exists() and "ALL_DONE" in (d / "progress.txt").read_text():
            subprocess.run([PY, str(S / "scripts/grade_lenet.py"), str(d), str(tmp / f"t11_{name}.json")], check=True, capture_output=True)
            out[f"table11_{name}"] = json.loads((tmp / f"t11_{name}.json").read_text())
    h7 = R / "h7_no_flip" / "progress.txt"
    if h7.exists() and "ALL_DONE" in h7.read_text():
        subprocess.run([PY, str(S / "scripts/grade_f7.py"), str(tmp / "f7.json")], check=True, capture_output=True)
        out["f7"] = json.loads((tmp / "f7.json").read_text())
    return out

def pick(v, *keys):
    return {k: (v["setup"]["differs"] if k == "setup_differs" else v[k]) for k in keys if k == "setup_differs" or k in v}

def flatten(out):
    """Every graded claim and effect as one flat map: key -> the fields that must not change."""
    f = {}
    t1 = out["table1"]
    for k, v in t1["absolute"].items(): f[f"table1/absolute/{k}"] = pick(v, "label", "delta", "ci95", "ci90", "margin", "min_margin_for_equivalence", "setup_differs")
    for k, v in t1["relative"].items(): f[f"table1/relative/{k}"] = pick(v, "label", "ours_gap", "ours_ci95", "gap_difference_ci95", "setup_differs")
    for br, d in t1["effects"].items():
        for k, x in d.items():
            if isinstance(x, dict): f[f"table1/effect/{br}/{k}"] = pick(x, "effect", "ci", "p_holm", "survives_holm")
    for k, x in t1["confirmation"].items(): f[f"table1/confirmation/{k}"] = pick(x, "effect", "ci")
    for name in RUNSETS:
        gx = out.get(f"table11_{name}")
        if not gx: continue
        for m, cells in gx["cells"].items():
            for d, v in cells.items(): f[f"table11_{name}/cell/{m}/{d}"] = pick(v, "label", "verdict_paper_sd_only", "delta", "ci90", "margin", "min_margin_for_equivalence", "setup_differs")
        for m, v in gx["average"].items(): f[f"table11_{name}/average/{m}"] = pick(v, "label", "verdict_paper_sd_only", "delta", "ci90", "margin", "setup_differs")
        for k, v in gx["relative"].items(): f[f"table11_{name}/relative/{k}"] = pick(v, "label", "ours_gap", "ours_ci95", "gap_difference_ci95", "setup_differs")
        for m, d in gx["prior_work"].items():
            for dom, x in d.items(): f[f"table11_{name}/prior/{m}/{dom}"] = pick(x, "result", "ci95")
    if out.get("f7"):
        for d, c in out["f7"]["cells"].items(): f[f"f7/cell/{d}"] = pick(c, "effect", "ci95", "p_holm", "survives_holm", "same_ctr_epoch")
        f["f7/average"] = pick(out["f7"]["average"], "effect", "ci95", "excludes_zero")
    return f

def golden_claims():
    return {"table1_target": {k: {"mean": v["mean"], "sd": v["sd"], "n": v["n"]} for k, v in T1_PAPER.items()},
            "table11": {m: {str(d): {"mean": a, "sd": b} for d, (a, b) in zip(DOMAINS, rows)} for m, rows in T11_PAPER.items()},
            "table11_average": T11_AVG}

def check_extraction():
    """Extractor outputs (when present) must recover the golden claim values and the golden findings."""
    B = S / "evidence" / "extraction" / "outputs"
    P = {f.stem: json.loads(f.read_text()) for f in sorted(B.glob("paper_run*.json"))}
    C = {f.stem: json.loads(f.read_text()) for f in sorted(B.glob("code_run*.json"))}
    res = {}
    for n, d in P.items():
        r, tot, _ = xd.claim_score(d); res[f"claims/{n}"] = {"ok": r == tot, "got": f"{r}/{tot}"}
    for (pn, p), (cn, c) in ((a, b) for a in P.items() for b in C.items()):
        fs = xd.diff(xd.settings(p), xd.settings(c))
        hit = {g: fn(fs) for g, fn in xd.GROUND_TRUTH.items()}
        res[f"findings/{pn} x {cn}"] = {"ok": all(hit.values()), "got": f"{sum(hit.values())}/{len(hit)}", "missed": [g for g, h in hit.items() if not h]}
    return res

if __name__ == "__main__":
    update = "--update" in sys.argv
    with tempfile.TemporaryDirectory() as t:
        flat = flatten(grade_all(Path(t)))
    if update:
        G.mkdir(exist_ok=True)
        (G / "verdicts.json").write_text(json.dumps(flat, indent=1, ensure_ascii=False))
        (G / "claims.json").write_text(json.dumps(golden_claims(), indent=1))
        (G / "findings.json").write_text(json.dumps({k: v for k, v in FINDINGS.items()}, indent=1))
        print("golden updated:", len(flat), "graded items")
        sys.exit(0)
    gold = json.loads((G / "verdicts.json").read_text())
    mism = [{"key": k, "golden": gold.get(k), "now": flat.get(k)} for k in sorted(set(gold) | set(flat)) if gold.get(k) != flat.get(k)]
    gc = json.loads((G / "claims.json").read_text())
    if gc != json.loads(json.dumps(golden_claims())): mism.append({"key": "claims", "golden": "golden/claims.json", "now": "grader paper tables differ"})
    ext = check_extraction()
    mism += [{"key": k, "golden": "all recovered", "now": v} for k, v in ext.items() if not v["ok"]]
    labels = [v["label"] for k, v in gold.items() if "label" in v]
    rep = {"when": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "graded_items_checked": len(gold),
           "verdict_labels_checked": len(labels), "extraction_checks": len(ext), "mismatches": mism, "pass": not mism}
    (R / "regression.json").write_text(json.dumps(rep, indent=1, ensure_ascii=False))
    print(f"{len(gold)} graded items ({len(labels)} verdicts) + {len(ext)} extraction checks: {len(mism)} mismatches")
    for m in mism[:20]: print(" ", m)
    sys.exit(1 if mism else 0)
