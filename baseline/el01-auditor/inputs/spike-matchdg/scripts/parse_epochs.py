"""Per-epoch trace for every run: which epoch each selection rule picked, and source accuracy there.
Every value carries its log file and line number. No numbers are typed by hand."""
import json, re, statistics as st
from pathlib import Path

RUNS = Path("/home/claude/spike/runs")

def epochs(path):
    lines = Path(path).read_text().splitlines()
    runs, cur = [], None
    for i, l in enumerate(lines, 1):
        if re.match(r"^Run (\d+)", l):
            cur = {"epochs": {}, "best": None}; runs.append(cur); ep = {}
            continue
        if cur is None: continue
        m = re.match(r"^Train Acc Env :\s+([\d.]+)", l)
        if m: ep = {"train_acc": float(m.group(1)), "train_line": i}
        m = re.match(r"^Done Training for epoch:\s+(\d+)", l)
        if m: ep["epoch"] = int(m.group(1)); cur["epochs"][ep["epoch"]] = ep
        m = re.match(r"^ Accuracy:\s+val ([\d.]+)", l)
        if m: ep["val_acc"] = float(m.group(1)); ep["val_line"] = i
        m = re.match(r"^ Accuracy:\s+test ([\d.]+)", l)
        if m: ep["test_acc"] = float(m.group(1))
        m = re.match(r"^ Loss:\s+val ([\d.]+)", l)
        if m: ep["val_loss"] = float(m.group(1))
        m = re.search(r"Current Best Epoch:\s+(\d+)\s+with Test Accuracy:\s+([\d.]+)", l)
        if m: cur["best"] = {"epoch": int(m.group(1)), "target_acc": float(m.group(2)), "line": i}
    out = []
    for s, r in enumerate(runs):
        b = r["best"]; e = r["epochs"][b["epoch"]]; last = r["epochs"][max(r["epochs"])]
        out.append({"seed_run": s, "selected_epoch": b["epoch"], "target_acc": b["target_acc"], "best_line": b["line"],
                    "source_val_acc": e["val_acc"], "source_val_line": e["val_line"], "train_acc": round(e["train_acc"], 2),
                    "last_epoch": last["epoch"], "last_train_acc": round(last["train_acc"], 2), "last_source_val_acc": last["val_acc"],
                    "last_target_acc": last["test_acc"]})
    return out

def summary(rows):
    f = lambda k: round(st.mean(r[k] for r in rows), 2)
    return {"n": len(rows), "selected_epoch_median": st.median(r["selected_epoch"] for r in rows),
            "selected_epoch_min": min(r["selected_epoch"] for r in rows), "selected_epoch_max": max(r["selected_epoch"] for r in rows),
            "target_acc": f("target_acc"), "source_val_acc": f("source_val_acc"), "train_acc": f("train_acc"),
            "last_train_acc": f("last_train_acc"), "last_source_val_acc": f("last_source_val_acc"), "last_target_acc": f("last_target_acc")}

if __name__ == "__main__":
    allres = {}
    for d in sorted(p for p in RUNS.iterdir() if p.is_dir()):
        for f in sorted(d.glob("train_*.log")):
            try:
                rows = epochs(f)
            except Exception as e:
                print("skip", f, repr(e)); continue
            allres.setdefault(d.name, {})[f.stem[6:]] = {"log": f"{d.name}/{f.name}", "summary": summary(rows), "per_seed": rows}
    (RUNS / "epochs.json").write_text(json.dumps(allres, indent=1))
    print(f"{'branch':24s} {'meth':6s} {'sel.ep med [min-max]':22s} {'target':>7s} {'src val':>7s} {'train':>7s} | last: {'train':>6s} {'srcval':>6s} {'target':>6s}")
    for br, d in allres.items():
        for m, v in d.items():
            s = v["summary"]
            print(f"{br:24s} {m:6s} {s['selected_epoch_median']:>5} [{s['selected_epoch_min']}-{s['selected_epoch_max']}]{'':10s} {s['target_acc']:7.1f} {s['source_val_acc']:7.1f} {s['train_acc']:7.1f} | {s['last_train_acc']:12.1f} {s['last_source_val_acc']:6.1f} {s['last_target_acc']:6.1f}")
