"""Scaling lever check: a branch that only changes the checkpoint-selection rule should train exactly like the baseline.
Compares the per-epoch trace (training accuracy, validation accuracy, test accuracy for every seed and epoch) of each
selection-rule branch with the baseline's. If they are identical, such branches need no retraining: log every candidate
selection metric once and pick the checkpoint after the fact. Writes runs/selection_traces.json."""
import json, re
from pathlib import Path
R = Path("/home/claude/spike/runs")
SEL = {"h_select_valloss": "paper_target_1.0", "h_select_valloss_total": "paper_target_1.0", "confirm_select_valloss": "confirm_base"}
def trace(p): return [l.strip() for l in p.read_text().splitlines() if re.match(r"\s*Accuracy:\s+(val|test)", l) or l.startswith("Train Acc Env")]
out = {"checks": [], "selection_runs": 0}
for br, base in SEL.items():
    for f in sorted((R / br).glob("train_*.log")):
        b = R / base / f.name
        if not b.exists(): continue
        x, y = trace(f), trace(b)
        out["checks"].append({"branch": br, "baseline": base, "log": f.name, "lines": len(x), "identical": x == y})
    out["selection_runs"] += json.loads((R / "run_counts.json").read_text())["slab"][br]["runs"]
out["all_identical"] = all(c["identical"] for c in out["checks"])
(R / "selection_traces.json").write_text(json.dumps(out, indent=1))
print(out["all_identical"], len(out["checks"]), sum(c["lines"] for c in out["checks"]), out["selection_runs"])
