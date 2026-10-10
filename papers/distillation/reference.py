"""B0: distillation reference run (Hinton, Vinyals & Dean 2015, arXiv 1503.02531, section 3).

Trains three MLPs on MNIST on CPU and reports test errors out of 10,000:
  teacher            2x1200 ReLU, dropout + max-norm, inputs jittered by up to 2 px  (paper: 67)
  student_hard       2x800 ReLU, no regularisation, hard labels                       (paper: 146)
  student_distilled  2x800 ReLU, soft targets from the teacher at T=20                (paper: 74)

The paper does not state the optimizer, learning rate, batch size, epochs, dropout
rates, max-norm value or the hard/soft loss weights; the values below are ours.

v2 (after results_full.json, where the distilled student hit a NaN loss in epoch 1 and predicted one class,
9020 errors): the distilled student uses lr 0.03 and gradient-norm clipping at 5.0, and every model stops at its first
non-finite loss with the epoch and step logged. The teacher checkpoint is saved under runs/ so a student can be
retrained alone.

Usage: python papers/distillation/reference.py [--quick] [--only MODEL ...] [--teacher-ckpt PATH]
  --only student_distilled --teacher-ckpt runs/distillation/teacher_full_seed0.pt   retrain one student, no teacher
"""

import argparse
import json
import math
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torchvision import datasets

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent

PAPER = {
    "arxiv": "1503.02531",
    "section": "3 Preliminary experiments on MNIST",
    "teacher_test_errors": 67,
    "student_hard_test_errors": 146,
    "student_distilled_test_errors": 74,
    "temperature": 20,
}

# Epochs per model. The paper trains to convergence and does not give a count.
EPOCHS = {
    "quick": {"teacher": 12, "student_hard": 8, "student_distilled": 8},
    "full": {"teacher": 60, "student_hard": 30, "student_distilled": 30},
}

MEAN, STD = 0.1307, 0.3081
BATCH = 128
MODELS = ("teacher", "student_hard", "student_distilled")
# lr 0.1 left the dropout teacher at 488 errors after 3 epochs; 0.03 gave 252 after 2.
# v2: the distilled student diverged at 0.1 (the T^2-scaled soft loss gives ~T times larger logit gradients).
LR = {"teacher": 0.03, "student_hard": 0.1, "student_distilled": 0.03}
GRAD_CLIP = {"student_distilled": 5.0}  # max L2 norm of all gradients, per step (v2)
MOMENTUM = 0.9
MAX_NORM = 3.5  # per-unit L2 bound on incoming weights (teacher only)
DROPOUT_IN, DROPOUT_HID = 0.2, 0.5
JITTER = 2
T = PAPER["temperature"]
SOFT_WEIGHT = 0.9  # paper: "considerably lower weight" on the hard-label objective

LOG = []  # every METRIC line printed, in order
V2_CHANGES = [
    {"setting": "lr.student_distilled", "from": 0.1, "to": LR["student_distilled"],
     "why": "results_full.json: NaN loss in epoch 1 at lr 0.1, 9020 test errors (one class predicted)"},
    {"setting": "grad_clip_norm.student_distilled", "from": None, "to": GRAD_CLIP["student_distilled"],
     "why": "same divergence; the soft loss is scaled by T^2 = 400"},
    {"setting": "nan_guard", "from": None, "to": "stop at the first non-finite loss",
     "why": "v1 kept training 30 epochs on NaN weights; now the epoch and step are logged and training stops"},
]


def metric(name, value, step):
    line = f"METRIC {name}={value} step={step}"
    print(line, flush=True)
    LOG.append(line)
    return line


class MLP(nn.Module):
    def __init__(self, hidden, p_in=0.0, p_hid=0.0):
        super().__init__()
        self.fc1 = nn.Linear(784, hidden)
        self.fc2 = nn.Linear(hidden, hidden)
        self.fc3 = nn.Linear(hidden, 10)
        self.p_in, self.p_hid = p_in, p_hid

    def forward(self, x):
        x = ((x - MEAN) / STD).flatten(1)
        x = F.dropout(x, self.p_in, self.training)
        x = F.dropout(F.relu(self.fc1(x)), self.p_hid, self.training)
        x = F.dropout(F.relu(self.fc2(x)), self.p_hid, self.training)
        return self.fc3(x)

    def apply_max_norm(self, c):
        with torch.no_grad():
            for layer in (self.fc1, self.fc2, self.fc3):
                layer.weight.copy_(torch.renorm(layer.weight, 2, 0, c))


def load_mnist(data_dir):
    train = datasets.MNIST(data_dir, train=True, download=True)
    test = datasets.MNIST(data_dir, train=False, download=True)
    prep = lambda d: (d.data.float() / 255.0, d.targets.clone())
    return prep(train), prep(test)


def jitter(x, gen):
    """Shift each 28x28 image by a random (dy, dx) in [-JITTER, JITTER], zero-filled."""
    b = x.shape[0]
    padded = F.pad(x, (JITTER,) * 4)
    dy = torch.randint(0, 2 * JITTER + 1, (b, 1, 1), generator=gen)
    dx = torch.randint(0, 2 * JITTER + 1, (b, 1, 1), generator=gen)
    rows = torch.arange(28).view(1, 28, 1) + dy
    cols = torch.arange(28).view(1, 1, 28) + dx
    return padded[torch.arange(b).view(b, 1, 1), rows, cols]


@torch.no_grad()
def test_errors(model, x, y):
    model.eval()
    wrong = sum((model(x[i:i + 1000]).argmax(1) != y[i:i + 1000]).sum().item()
                for i in range(0, len(x), 1000))
    return int(wrong)


@torch.no_grad()
def logits_of(model, x):
    model.eval()
    return torch.cat([model(x[i:i + 1000]) for i in range(0, len(x), 1000)])


def train(name, model, epochs, train_xy, test_xy, gen, soft_logits=None, regularise=False):
    x, y = train_xy
    n = len(x)
    steps_per_epoch = (n + BATCH - 1) // BATCH
    total = epochs * steps_per_epoch
    opt = torch.optim.SGD(model.parameters(), lr=LR[name], momentum=MOMENTUM)
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: 1 - s / total)
    clip = GRAD_CLIP.get(name)
    history, diverged = [], None
    t0 = time.perf_counter()
    for epoch in range(1, epochs + 1):
        model.train()
        perm = torch.randperm(n, generator=gen)
        loss_sum = 0.0
        for i in range(0, n, BATCH):
            idx = perm[i:i + BATCH]
            xb, yb = x[idx], y[idx]
            if regularise:
                xb = jitter(xb, gen)
            out = model(xb)
            hard = F.cross_entropy(out, yb)
            if soft_logits is None:
                loss = hard
            else:
                soft = F.kl_div(F.log_softmax(out / T, 1), F.softmax(soft_logits[idx] / T, 1),
                                reduction="batchmean") * T * T
                loss = SOFT_WEIGHT * soft + (1 - SOFT_WEIGHT) * hard
            if not math.isfinite(loss.item()):
                # Stop before the step, so the weights stay the last finite ones and test errors stay meaningful.
                diverged = {"epoch": epoch, "step": i // BATCH + 1, "loss": str(loss.item())}
                print(f"  [{name}] non-finite loss ({loss.item()}) at epoch {epoch}, step {i // BATCH + 1}: "
                      f"training stopped", flush=True)
                break
            opt.zero_grad(set_to_none=True)
            loss.backward()
            if clip:
                torch.nn.utils.clip_grad_norm_(model.parameters(), clip)
            opt.step()
            sched.step()
            if regularise:
                model.apply_max_norm(MAX_NORM)
            loss_sum += loss.item() * len(idx)
        errs = test_errors(model, *test_xy)
        elapsed = time.perf_counter() - t0
        if diverged:
            diverged["log_line"] = metric(f"{name}_diverged_epoch", epoch, epoch)
            diverged["test_errors_at_stop"] = errs
            diverged["test_errors_log_line"] = metric(f"{name}_test_errors", errs, epoch)
            break
        lines = [metric(f"{name}_train_loss", round(loss_sum / n, 5), epoch),
                 metric(f"{name}_test_errors", errs, epoch)]
        history.append({"epoch": epoch, "train_loss": round(loss_sum / n, 5), "test_errors": errs,
                        "elapsed_s": round(elapsed, 1), "log_lines": lines})
        print(f"  [{name}] epoch {epoch}/{epochs}  loss {loss_sum / n:.4f}  "
              f"test errors {errs}/10000  {elapsed:.0f}s", flush=True)
    return history, time.perf_counter() - t0, diverged


def save_teacher(model, path, meta):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"state_dict": model.state_dict(), "meta": meta}, path)
    print(f"saved teacher checkpoint {path}", flush=True)


def load_teacher(path):
    ckpt = torch.load(path, map_location="cpu", weights_only=True)
    model = MLP(1200, DROPOUT_IN, DROPOUT_HID)
    model.load_state_dict(ckpt["state_dict"])
    return model, ckpt["meta"]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--quick", action="store_true", help="reduced epochs; target <=15 min on CPU")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--data-dir", default=str(ROOT / "data"))
    ap.add_argument("--out", default=str(HERE / "results.json"))
    ap.add_argument("--only", nargs="+", choices=MODELS, help="train only these models (default: all three)")
    ap.add_argument("--teacher-ckpt", help="saved here after the teacher trains; loaded from here when only students "
                                           "train (default runs/distillation/teacher_<mode>_seed<seed>.pt)")
    args = ap.parse_args()

    mode = "quick" if args.quick else "full"
    epochs = EPOCHS[mode]
    todo = [m for m in MODELS if m in (args.only or MODELS)]
    ckpt_path = Path(args.teacher_ckpt or ROOT / "runs" / "distillation" / f"teacher_{mode}_seed{args.seed}.pt")
    if "student_distilled" in todo and "teacher" not in todo and not ckpt_path.is_file():
        sys.exit(f"student_distilled needs a teacher: train it too, or pass --teacher-ckpt (missing: {ckpt_path})")
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    gen = torch.Generator().manual_seed(args.seed)
    run_start = time.perf_counter()

    print(f"B0 distillation reference v2 | mode={mode} seed={args.seed} torch={torch.__version__} "
          f"threads={torch.get_num_threads()} | models={todo} | epochs={epochs}", flush=True)
    train_xy, test_xy = load_mnist(args.data_dir)
    print(f"MNIST: {len(train_xy[0])} train, {len(test_xy[0])} test", flush=True)

    models, teacher, teacher_ckpt = {}, None, {"path": str(ckpt_path)}
    save = lambda complete: write_results(args, mode, todo, models, teacher_ckpt, run_start, complete)

    def record(name, step, hist, secs, diverged):
        errs = diverged["test_errors_at_stop"] if diverged else hist[-1]["test_errors"]
        paper = PAPER[f"{name}_test_errors"]
        err_line = metric(f"final_{name}_test_errors", errs, step)
        wall_line = metric(f"final_{name}_wall_s", round(secs, 1), step)
        models[name] = {
            "test_errors": errs, "paper_test_errors": paper, "diff": errs - paper,
            "epochs": epochs[name], "epochs_done": len(hist), "diverged": diverged, "wall_clock_s": round(secs, 1),
            "log_lines": {"test_errors": err_line, "wall_clock_s": wall_line},
            "history": hist,
        }
        save(complete=False)

    if "teacher" in todo:
        print("\n== teacher: 2x1200 ReLU, dropout + max-norm + jitter ==", flush=True)
        teacher = MLP(1200, DROPOUT_IN, DROPOUT_HID)
        hist, secs, div = train("teacher", teacher, epochs["teacher"], train_xy, test_xy, gen, regularise=True)
        if div:
            teacher_ckpt.update({"saved": False, "why_not": "the teacher diverged"})
        else:
            save_teacher(teacher, ckpt_path, {"mode": mode, "seed": args.seed, "epochs": epochs["teacher"],
                                              "test_errors": hist[-1]["test_errors"],
                                              "log_line": hist[-1]["log_lines"][1]})
            teacher_ckpt["saved"] = True
        record("teacher", 1, hist, secs, div)
    elif "student_distilled" in todo:
        teacher, meta = load_teacher(ckpt_path)
        errs = test_errors(teacher, *test_xy)
        line = metric("teacher_ckpt_test_errors", errs, 0)
        print(f"loaded teacher checkpoint {ckpt_path}: {errs}/10000 test errors (saved with {meta})", flush=True)
        teacher_ckpt.update({"loaded": True, "meta": meta, "test_errors": errs, "log_line": line})

    if "student_hard" in todo:
        print("\n== student_hard: 2x800 ReLU, no regularisation, hard labels ==", flush=True)
        student = MLP(800)
        hist, secs, div = train("student_hard", student, epochs["student_hard"], train_xy, test_xy, gen)
        record("student_hard", 2, hist, secs, div)

    if "student_distilled" in todo:
        print(f"\n== student_distilled: 2x800 ReLU, soft targets T={T}, lr {LR['student_distilled']}, "
              f"grad clip {GRAD_CLIP['student_distilled']} ==", flush=True)
        t0 = time.perf_counter()
        soft_logits = logits_of(teacher, train_xy[0])
        distilled = MLP(800)
        hist, _, div = train("student_distilled", distilled, epochs["student_distilled"], train_xy, test_xy,
                             gen, soft_logits=soft_logits)
        record("student_distilled", 3, hist, time.perf_counter() - t0, div)

    print("\n== summary (test errors /10,000; one seed) ==", flush=True)
    for name, m in models.items():
        note = f"  DIVERGED at epoch {m['diverged']['epoch']}" if m["diverged"] else ""
        print(f"  {name:<18} ours {m['test_errors']:>4}   paper {m['paper_test_errors']:>4}   "
              f"diff {m['diff']:+5d}   wall {m['wall_clock_s']:6.1f}s  ({m['epochs_done']}/{m['epochs']} epochs)"
              f"{note}", flush=True)
    out = save(complete=True)
    if out["distilled_beats_hard"] is not None:
        print(f"  distilled < hard-label: {out['distilled_beats_hard']} "
              f"({models['student_distilled']['test_errors']} vs {models['student_hard']['test_errors']})", flush=True)
    print(f"  total wall {out['total_wall_clock_s']:.1f}s\nwrote {Path(args.out).resolve()}", flush=True)


def write_results(args, mode, todo, models, teacher_ckpt, run_start, complete):
    """Written after every model, so a timeout or a crash keeps the models that finished."""
    total_s = time.perf_counter() - run_start
    both = "student_hard" in models and "student_distilled" in models
    out = {
        "paper": PAPER,
        "version": 2,
        "mode": mode,
        "seed": args.seed,
        "models_trained": todo,
        "complete": complete,
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "environment": {"python": sys.version.split()[0], "torch": torch.__version__,
                        "platform": platform.platform(), "machine": platform.machine(),
                        "threads": torch.get_num_threads()},
        "settings": {
            "batch": BATCH, "optimizer": "SGD", "lr": LR, "momentum": MOMENTUM, "grad_clip_norm": GRAD_CLIP,
            "nan_guard": "a model stops at its first non-finite loss, before that step; epoch and step are logged",
            "changes_from_v1": V2_CHANGES,
            "quick_epochs_note": "cut to fit <=15 min on CPU; paper trains to convergence",
            "lr_schedule": "linear decay to 0", "normalise": [MEAN, STD],
            "teacher": {"hidden": [1200, 1200], "dropout_input": DROPOUT_IN,
                        "dropout_hidden": DROPOUT_HID, "max_norm": MAX_NORM, "jitter_px": JITTER},
            "student_hard": {"hidden": [800, 800], "regularisation": "none"},
            "student_distilled": {"hidden": [800, 800], "temperature": T, "lr": LR["student_distilled"],
                                  "grad_clip_norm": GRAD_CLIP["student_distilled"],
                                  "soft_weight": SOFT_WEIGHT, "hard_weight": round(1 - SOFT_WEIGHT, 2),
                                  "soft_loss": "KL(teacher_T || student_T) * T^2",
                                  "transfer_set": "MNIST train (60,000), no jitter"},
        },
        "teacher_checkpoint": teacher_ckpt,
        "models": models,
        "distilled_beats_hard": (models["student_distilled"]["test_errors"] < models["student_hard"]["test_errors"]
                                 if both else None),
        "total_wall_clock_s": round(total_s, 1),
    }
    if complete:
        out["total_log_line"] = metric("total_wall_s", round(total_s, 1), 0)
    out["metric_log"] = LOG
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2) + "\n")
    return out


if __name__ == "__main__":
    main()
