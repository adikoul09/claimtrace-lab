"""Wall-clock time of each run set, from file timestamps: the run script writes commit.txt when it starts and appends
ALL_DONE to progress.txt when its last job ends. Only run sets that ran alone on the machine are reported as measured;
the slab run sets overlapped one another, so their wall-clock is not separable. Writes runs/wallclock.json."""
import json, os
from datetime import datetime, timezone
from pathlib import Path
R = Path("/home/claude/spike/runs")
ALONE = ["matchdg_lenet", "matchdg_lenet_confirm", "h7_no_flip"]   # nothing else was training while these ran
out = {}
for name in ALONE:
    d = R / name
    if not ((d / "progress.txt").exists() and "ALL_DONE" in (d / "progress.txt").read_text()): continue
    t0, t1 = os.path.getmtime(d / "commit.txt"), os.path.getmtime(d / "progress.txt")
    jobs = [l for l in (d / "progress.txt").read_text().splitlines() if " in " in l]
    out[name] = {"start_utc": datetime.fromtimestamp(t0, timezone.utc).isoformat(timespec="seconds"),
                 "end_utc": datetime.fromtimestamp(t1, timezone.utc).isoformat(timespec="seconds"),
                 "wall_minutes": round((t1 - t0) / 60, 1), "jobs": len(jobs),
                 "job_minutes_sum": round(sum(int(l.split(" in ")[1].rstrip("s")) for l in jobs) / 60, 1)}
(R / "wallclock.json").write_text(json.dumps(out, indent=1)); print(json.dumps(out, indent=1))
