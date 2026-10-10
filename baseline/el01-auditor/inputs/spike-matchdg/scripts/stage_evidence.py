"""Stages the evidence files that are published next to the blueprint page (and copied into the evidence repo),
plus manifest.json for the page's evidence browser. Usage: stage_evidence.py <out_dir>"""
import hashlib, json, shutil, sys
from pathlib import Path
S = Path("/home/claude/spike"); R = S / "runs"; E = S / "evidence"
out = Path(sys.argv[1]); ev = out / "evidence"
if ev.exists(): shutil.rmtree(ev)
ev.mkdir(parents=True)
groups = {"Report and grades": [], "Patches and branches": [], "Extraction test": [], "Regression (golden outputs)": [], "Raw logs": [], "Parsed metrics": [], "Scripts and environment": []}
def put(src, rel, group, label=None):
    dst = ev / rel; dst.parent.mkdir(parents=True, exist_ok=True); shutil.copy(src, dst)
    if group: groups[group].append({"path": f"evidence/{rel}", "label": label or rel, "sha256": hashlib.sha256(dst.read_bytes()).hexdigest()})
put(E / "README.md", "README.md", "Report and grades", "report (README.md)")
for f in ("grades.json", "epochs.json", "run_counts.json"): put(R / f, f"metrics/{f}", "Report and grades")
put(R / "matchdg_lenet" / "grades_lenet.json", "metrics/grades_lenet.json", "Report and grades")
C11 = R / "matchdg_lenet_confirm" / "grades_lenet_confirm.json"
if C11.exists(): put(C11, "metrics/grades_lenet_confirm.json", "Report and grades")
F7 = R / "h7_no_flip" / "grades_f7.json"
if F7.exists(): put(F7, "metrics/grades_f7.json", "Report and grades", "metrics/grades_f7.json (F7 branch test, SciCoQA row 67)")
F7D = R / "h7_no_flip" / "data_check.json"
if F7D.exists(): put(F7D, "metrics/f7_data_check.json", "Report and grades", "metrics/f7_data_check.json (F7 branch changes only the flips)")
F7P = R / "h7_no_flip" / "grade_f7.preregistered.py"
if F7P.exists(): put(F7P, "scripts/preregistered/grade_f7.py", "Scripts and environment", "scripts/preregistered/grade_f7.py (as hashed before the F7 runs)")
for f in ("wallclock.json", "selection_traces.json"):
    if (R / f).exists(): put(R / f, f"metrics/{f}", "Report and grades")
put(R / "grades.v1.json", "metrics/v1/grades.json", "Report and grades", "metrics/v1/grades.json (rules version 1)")
put(R / "matchdg_lenet" / "grades_lenet.v1.json", "metrics/v1/grades_lenet.json", "Report and grades", "metrics/v1/grades_lenet.json (rules version 1)")
for f in sorted((S / "golden").glob("*.json")): put(f, f"golden/{f.name}", "Regression (golden outputs)")
if (R / "regression.json").exists(): put(R / "regression.json", "golden/last_check.json", "Regression (golden outputs)", "golden/last_check.json (last regression run)")
for f in ("branches.txt", "repairs.patch", "hypotheses.patch"): put(E / f, f"patches/{f}", "Patches and branches")
for f in ("prompts.md", "schema.md", "score.json"): put(E / "extraction" / f, f"extraction/{f}", "Extraction test")
for f in sorted((E / "extraction" / "outputs").glob("*.json")): put(f, f"extraction/outputs/{f.name}", "Extraction test")
for f in sorted(R.glob("*.log")): put(f, f"logs/{f.name}", "Raw logs")
for d in sorted(p for p in R.iterdir() if p.is_dir()):
    for f in sorted(list(d.glob("*.log")) + list(d.glob("*.txt"))): put(f, f"logs/{d.name}/{f.name}", "Raw logs")
    if (d / "metrics.json").exists(): put(d / "metrics.json", f"metrics/{d.name}.json", "Parsed metrics")
for f in sorted(list((S / "scripts").glob("*.py")) + list((S / "scripts").glob("*.sh"))): put(f, f"scripts/{f.name}", "Scripts and environment")
for f in sorted((S / "scripts" / "v1").glob("*.py")): put(f, f"scripts/v1/{f.name}", "Scripts and environment", f"scripts/v1/{f.name} (rules version 1)")
put(E / "requirements-pinned.txt", "env/requirements-pinned.txt", "Scripts and environment")
# Trace: Table 1 target accuracy, each seed's value and the log line it was parsed from
m = json.loads((R / "paper_target_1.0" / "metrics.json").read_text())
names = {"erm": "ERM", "rand": "RandMatch", "perf": "PerfMatch", "mmd": "MMD", "coral": "CORAL", "dann": "DANN", "c-mmd": "C-MMD", "c-coral": "C-CORAL", "c-dann": "CDANN"}
trace = []
for k, n in names.items():
    t = m[k]["target"]
    trace.append({"label": n, "mean": f'{t["mean"]:.1f}', "log": f"evidence/logs/paper_target_1.0/{Path(t['log']).name}",
                  "seeds": [{"v": f'{s["target_acc"]:.1f}', "line": s["line"]} for s in t["per_seed"]]})
manifest = {"groups": [{"name": k, "files": v} for k, v in groups.items() if v], "trace": trace}
(ev / "manifest.json").write_text(json.dumps(manifest, indent=1))
print("manifest sha256", hashlib.sha256((ev / "manifest.json").read_bytes()).hexdigest())
files = [p for p in ev.rglob("*") if p.is_file()]
print(len(files), "files,", round(sum(p.stat().st_size for p in files) / 1e6, 1), "MB")
