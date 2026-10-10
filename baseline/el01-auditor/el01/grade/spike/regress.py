"""MatchDG as the regression test. Port of the spike's scripts/regression.py.
Re-derives every MatchDG output from the raw logs and compares it with the golden outputs in <spike>/golden/: the
hand-built claim tables (Table 1 and Table 11 paper values), the hand-built settings diff (F1-F6), and every verdict,
number and "setup differs" flag the graders produce. Any change to parsers, graders, extractors or the diff must leave
this at 0 mismatches before it ships.
Added in the port: file checks. Each regenerated per-run metrics file, epochs.json, grades*.json and the extraction
score must equal the spike's copy after cited-log paths are normalised to logs/<run>/<file>.
There is no --update: golden/ lives in read-only inputs/ and changes only after a reviewed rule change."""
import json
from datetime import datetime, timezone

from el01.diff import settings_diff as xd
from el01.grade.parse import parse_epochs_all, parse_run_dir
from el01.grade.spike import table1, table11
from el01.grade.spike.compare import json_diff, normalise_paths
from el01.grade.spike.f7 import BRANCH_RUN as F7_RUN, grade_f7
from el01.grade.spike.matchdg import FINDINGS

RUNSETS = {"first": "matchdg_lenet", "confirm": "matchdg_lenet_confirm"}
# Our grade outputs and the spike's file for each.
GRADE_FILES = {"table1": "grades.json", "table11_first": "grades_lenet.json",
               "table11_confirm": "grades_lenet_confirm.json", "f7": "grades_f7.json"}


def roundtrip(x):
    """What a reader of the written JSON file sees (int keys become strings, tuples become lists)."""
    return json.loads(json.dumps(x, default=str))


def all_done(d):
    p = d / "progress.txt"
    return p.exists() and "ALL_DONE" in p.read_text()


def parse_all(paths):
    """Parse every run directory and the per-epoch traces. In the spike these were runs/<run>/metrics.json and
    runs/epochs.json; here they are returned as they would read back from disk."""
    metrics = {d.name: parse_run_dir(d, paths.cite)
               for d in sorted(p for p in paths.logs.iterdir() if p.is_dir() and list(p.glob("train_*.log")))}
    ep, skipped = parse_epochs_all(paths.logs, paths.cite)
    return {"metrics": roundtrip(metrics), "epochs": roundtrip(ep), "epochs_skipped": skipped}


def grade_all(paths, parsed, rules=None):
    """Table 1, Table 11 (each finished run set) and F7 (when its branch run finished)."""
    out = {"table1": roundtrip(table1.grade_table1(parsed["metrics"], parsed["epochs"], rules))}
    for name, run in RUNSETS.items():
        if all_done(paths.logs / run):
            out[f"table11_{name}"] = roundtrip(table11.grade_table11(paths.logs / run, paths.cite, rules))
    if all_done(paths.logs / F7_RUN):
        out["f7"] = roundtrip(grade_f7(parsed["metrics"], paths.logs, rules))
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
    return {"table1_target": {k: {"mean": v["mean"], "sd": v["sd"], "n": v["n"]} for k, v in table1.PAPER.items()},
            "table11": {m: {str(d): {"mean": a, "sd": b} for d, (a, b) in zip(table11.DOMAINS, rows)} for m, rows in table11.PAPER.items()},
            "table11_average": table11.PAPER_AVG}


def check_extraction(paths):
    """Extractor outputs (when present) must recover the golden claim values and the golden findings."""
    P, C = xd.load_outputs(paths.extraction_outputs)
    res = {}
    for n, d in P.items():
        r, tot, _ = xd.claim_score(d); res[f"claims/{n}"] = {"ok": r == tot, "got": f"{r}/{tot}"}
    for (pn, p), (cn, c) in ((a, b) for a in P.items() for b in C.items()):
        fs = xd.diff(xd.settings(p), xd.settings(c))
        hit = {g: fn(fs) for g, fn in xd.GROUND_TRUTH.items()}
        res[f"findings/{pn} x {cn}"] = {"ok": all(hit.values()), "got": f"{sum(hit.values())}/{len(hit)}", "missed": [g for g, h in hit.items() if not h]}
    return res


def our_files(parsed, out, paths):
    """{the spike's file, relative to <spike>/: our regenerated content} for every file we regenerate."""
    files = {f"metrics/{run}.json": m for run, m in parsed["metrics"].items()}
    files["metrics/epochs.json"] = parsed["epochs"]
    for key, name in GRADE_FILES.items():
        if key in out: files[f"metrics/{name}"] = out[key]
    files["extraction/score.json"] = roundtrip(xd.score_report(paths.extraction_outputs))
    return files


def check_files(paths, parsed, out):
    """Our regenerated files vs the spike's copies, after path normalisation. Files the spike did not keep (for
    example metrics for matchdg_lenet) are listed as not compared."""
    checked, missing, mism = [], [], []
    for rel, ours in our_files(parsed, out, paths).items():
        f = paths.spike / rel
        if not f.exists():
            missing.append(rel); continue
        checked.append(rel)
        d = json_diff(normalise_paths(json.loads(f.read_text())), normalise_paths(ours))
        if d: mism.append({"file": rel, "differences": d})
    return {"checked": checked, "not_in_spike": missing, "mismatches": mism}


def run_regression(paths):
    """The full check. Returns the report (the spike's runs/regression.json fields, plus the file checks)."""
    parsed = parse_all(paths)
    out = grade_all(paths, parsed)
    flat = flatten(out)
    gold = json.loads((paths.golden / "verdicts.json").read_text())
    mism = [{"key": k, "golden": gold.get(k), "now": flat.get(k)} for k in sorted(set(gold) | set(flat)) if gold.get(k) != flat.get(k)]
    gc = json.loads((paths.golden / "claims.json").read_text())
    if gc != json.loads(json.dumps(golden_claims())): mism.append({"key": "claims", "golden": "golden/claims.json", "now": "grader paper tables differ"})
    gf = json.loads((paths.golden / "findings.json").read_text())
    if gf != FINDINGS: mism.append({"key": "findings", "golden": "golden/findings.json", "now": "FINDINGS differ"})
    ext = check_extraction(paths)
    mism += [{"key": k, "golden": "all recovered", "now": v} for k, v in ext.items() if not v["ok"]]
    labels = [v["label"] for k, v in gold.items() if "label" in v]
    files = check_files(paths, parsed, out)
    return {"when": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "graded_items_checked": len(gold),
            "verdict_labels_checked": len(labels), "extraction_checks": len(ext), "mismatches": mism,
            "file_checks": len(files["checked"]), "files_not_in_spike": files["not_in_spike"],
            "file_mismatches": files["mismatches"], "pass": not mism and not files["mismatches"]}
