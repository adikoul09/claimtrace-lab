"""Deterministic metric extraction: every number is tied to a log file and line number."""
import json, re, sys, statistics as st
from pathlib import Path

def parse_train(path):
    lines = Path(path).read_text().splitlines()
    runs, cur, last = [], None, None
    for i, l in enumerate(lines, 1):
        m = re.match(r"^Run (\d+)", l)
        if m:
            if cur is not None and last: runs.append(last)
            cur, last = int(m.group(1)), None
        m = re.search(r"Current Best Epoch:\s+(\d+)\s+with Test Accuracy:\s+([\d.]+)", l)
        if m: last = {"seed_run": cur, "best_epoch": int(m.group(1)), "target_acc": float(m.group(2)), "line": i}
        m = re.search(r"Final Test Accuracy \(Source Validation\) ([\d.]+) ([\d.]+)", l)
        if m: final = {"mean": float(m.group(1)), "sd": float(m.group(2)), "line": i}
    if last: runs.append(last)
    vals = [r["target_acc"] for r in runs]
    return {"log": str(path), "n": len(vals), "per_seed": runs,
            "mean": round(st.mean(vals), 2), "sd_pop": round(st.pstdev(vals), 2), "sd_sample": round(st.stdev(vals), 2),
            "code_reported": final}

def parse_eval(path):
    lines = Path(path).read_text().splitlines()
    out = {}
    for i, l in enumerate(lines, 1):
        m = re.match(r"^(\d)\s+:\s+([\d.]+)\s+([\d.]+)", l)
        if m: out[f"source_{int(m.group(1))+1}"] = {"mean": round(float(m.group(2)), 2), "sd": round(float(m.group(3)), 2), "log": str(path), "line": i}
    return out

if __name__ == "__main__":
    d = Path(sys.argv[1])
    res = {"commit": (d/"commit.txt").read_text().strip() if (d/"commit.txt").exists() else None}
    for f in sorted(d.glob("train_*.log")):
        try: res.setdefault(f.stem[6:], {})["target"] = parse_train(f)
        except Exception as e: res.setdefault(f.stem[6:], {})["error"] = repr(e)
    for f in sorted(d.glob("eval_*.log")):
        res.setdefault(f.stem[5:], {}).update(parse_eval(f))
    (d/"metrics.json").write_text(json.dumps(res, indent=1))
    for k, v in res.items():
        if k == "commit": continue
        t = v.get("target", {})
        print(f"{k:8s} target {t.get('mean')} sd_pop {t.get('sd_pop')} n={t.get('n')} | code says {t.get('code_reported',{}).get('mean')} ± {t.get('code_reported',{}).get('sd')} | src1 {v.get('source_1',{}).get('mean')} src2 {v.get('source_2',{}).get('mean')}")
