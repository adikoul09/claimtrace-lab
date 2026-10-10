"""Counts training runs (one seed of one method = one run) and compute time, from the logs and progress files."""
import json, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from parse_runs import parse_train
R = Path("/home/claude/spike/runs")
out = {"slab": {}, "lenet": {}}
for d in sorted(p for p in R.iterdir() if p.is_dir()):
    group = "lenet" if d.name.startswith(("matchdg_lenet", "h7_")) else "slab"  # Rotated MNIST (LeNet) vs slab
    n = 0
    for f in sorted(d.glob("train_*.log")):
        try: n += parse_train(f)["n"]
        except Exception: pass
    secs = 0
    if (d / "progress.txt").exists():
        for l in (d / "progress.txt").read_text().splitlines():
            m = re.search(r"(?:done in|train|in) (\d+)s", l)
            if m: secs += int(m.group(1))
    out[group][d.name] = {"runs": n, "seconds": secs}
tot = {g: {"runs": sum(v["runs"] for v in d.values()), "minutes": round(sum(v["seconds"] for v in d.values()) / 60)} for g, d in out.items()}
out["totals"] = tot
(R / "run_counts.json").write_text(json.dumps(out, indent=1))
print(json.dumps(tot)); [print(k, v) for k, v in out["slab"].items()]
