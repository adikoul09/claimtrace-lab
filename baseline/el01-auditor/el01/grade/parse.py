"""Deterministic metric extraction: every number is tied to a log file and line number.

Port of the spike's scripts/parse_runs.py (parse_train, parse_eval, the run-directory loop), scripts/parse_epochs.py
(epochs, summary, the all-runs loop) and the contrastive-checkpoint reader of scripts/grade_f7.py. Regexes, rounding and
error handling are unchanged. The only difference: a cited log is `cite(path)` (by default `logs/<run>/<file>`, see
`Paths.cite`) instead of the spike's absolute `/home/claude/spike/runs/...` path, and nothing is written here."""
import re
import statistics as st
from pathlib import Path


def parse_train(path, cite=str):
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
    return {"log": cite(path), "n": len(vals), "per_seed": runs,
            "mean": round(st.mean(vals), 2), "sd_pop": round(st.pstdev(vals), 2), "sd_sample": round(st.stdev(vals), 2),
            "code_reported": final}


def parse_eval(path, cite=str):
    lines = Path(path).read_text().splitlines()
    out = {}
    for i, l in enumerate(lines, 1):
        m = re.match(r"^(\d)\s+:\s+([\d.]+)\s+([\d.]+)", l)
        if m: out[f"source_{int(m.group(1))+1}"] = {"mean": round(float(m.group(2)), 2), "sd": round(float(m.group(3)), 2), "log": cite(path), "line": i}
    return out


def parse_run_dir(d, cite=str):
    """One run directory -> the spike's metrics.json content (returned, not written)."""
    d = Path(d)
    res = {"commit": (d/"commit.txt").read_text().strip() if (d/"commit.txt").exists() else None}
    for f in sorted(d.glob("train_*.log")):
        try: res.setdefault(f.stem[6:], {})["target"] = parse_train(f, cite)
        except Exception as e: res.setdefault(f.stem[6:], {})["error"] = repr(e)
    for f in sorted(d.glob("eval_*.log")):
        res.setdefault(f.stem[5:], {}).update(parse_eval(f, cite))
    return res


def epochs(path):
    """Per-epoch trace of one training log: which epoch the code's selection rule picked, and source accuracy there."""
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


def parse_epochs_all(runs_dir, cite=str):
    """Every run directory -> the spike's epochs.json content, plus the logs skipped (no per-epoch trace, e.g. the
    contrastive phase of MatchDG). Returned, not written."""
    allres, skipped = {}, []
    for d in sorted(p for p in Path(runs_dir).iterdir() if p.is_dir()):
        for f in sorted(d.glob("train_*.log")):
            try:
                rows = epochs(f)
            except Exception as e:
                skipped.append({"log": cite(f), "error": repr(e)}); continue
            allres.setdefault(d.name, {})[f.stem[6:]] = {"log": cite(f), "summary": summary(rows), "per_seed": rows}
    return allres, skipped


def ctr_epochs(path):
    """MatchDG contrastive-phase checkpoint per run: the last 'Current Best Epoch ... TopK Overlap' line before the next
    run starts (from grade_f7.py)."""
    out, cur, last = {}, None, None
    for i, l in enumerate(Path(path).read_text().splitlines(), 1):
        m = re.match(r"^Run (\d+)", l)
        if m:
            if cur is not None and last: out[cur] = last
            cur, last = int(m.group(1)), None
        m = re.search(r"Current Best Epoch:\s+(\d+)\s+with TopK Overlap:\s+([\d.]+)", l)
        if m: last = {"epoch": int(m.group(1)), "topk_overlap": float(m.group(2)), "line": i}
    if cur is not None and last: out[cur] = last
    return out
