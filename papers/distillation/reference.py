"""B0: distillation reference run (Hinton, Vinyals & Dean 2015, arXiv 1503.02531, section 3).

Trains three MLPs on MNIST on CPU and reports test errors out of 10,000:
  teacher            2x1200 ReLU, dropout + max-norm, inputs jittered by up to 2 px  (paper: 67)
  student_hard       2x800 ReLU, no regularisation, hard labels                       (paper: 146)
  student_distilled  2x800 ReLU, soft targets from the teacher at T=20                (paper: 74)

The paper does not state the optimizer, learning rate, batch size, epochs, dropout
rates, max-norm value or the hard/soft loss weights; the values below are ours.

Usage: python papers/distillation/reference.py [--quick]
"""

import argparse
import json
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
# lr 0.1 left the dropout teacher at 488 errors after 3 epochs; 0.03 gave 252 after 2.
LR = {"teacher": 0.03, "student_hard": 0.1, "student_distilled": 0.1}
MOMENTUM = 0.9
MAX_NORM = 3.5  # per-unit L2 bound on incoming weights (teacher only)
DROPOUT_IN, DROPOUT_HID = 0.2, 0.5
JITTER = 2
T = PAPER["temperature"]
SOFT_WEIGHT = 0.9  # paper: "considerably lower weight" on the hard-label objective

LOG = []  # every METRIC line printed, in order


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
    history = []
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
            opt.zero_grad(set_to_none=True)
            loss.backward()
            opt.step()
            sched.step()
            if regularise:
                model.apply_max_norm(MAX_NORM)
            loss_sum += loss.item() * len(idx)
        errs = test_errors(model, *test_xy)
        elapsed = time.perf_counter() - t0
        lines = [metric(f"{name}_train_loss", round(loss_sum / n, 5), epoch),
                 metric(f"{name}_test_errors", errs, epoch)]
        history.append({"epoch": epoch, "train_loss": round(loss_sum / n, 5), "test_errors": errs,
                        "elapsed_s": round(elapsed, 1), "log_lines": lines})
        print(f"  [{name}] epoch {epoch}/{epochs}  loss {loss_sum / n:.4f}  "
              f"test errors {errs}/10000  {elapsed:.0f}s", flush=True)
    return history, time.perf_counter() - t0


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--quick", action="store_true", help="reduced epochs; target <=15 min on CPU")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--data-dir", default=str(ROOT / "data"))
    ap.add_argument("--out", default=str(HERE / "results.json"))
    args = ap.parse_args()

    mode = "quick" if args.quick else "full"
    epochs = EPOCHS[mode]
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    gen = torch.Generator().manual_seed(args.seed)
    run_start = time.perf_counter()

    print(f"B0 distillation reference | mode={mode} seed={args.seed} torch={torch.__version__} "
          f"threads={torch.get_num_threads()} | epochs={epochs}", flush=True)
    train_xy, test_xy = load_mnist(args.data_dir)
    print(f"MNIST: {len(train_xy[0])} train, {len(test_xy[0])} test", flush=True)

    results = {}

    print("\n== teacher: 2x1200 ReLU, dropout + max-norm + jitter ==", flush=True)
    teacher = MLP(1200, DROPOUT_IN, DROPOUT_HID)
    hist, secs = train("teacher", teacher, epochs["teacher"], train_xy, test_xy, gen, regularise=True)
    results["teacher"] = (hist, secs)

    print("\n== student_hard: 2x800 ReLU, no regularisation, hard labels ==", flush=True)
    student = MLP(800)
    hist, secs = train("student_hard", student, epochs["student_hard"], train_xy, test_xy, gen)
    results["student_hard"] = (hist, secs)

    print(f"\n== student_distilled: 2x800 ReLU, soft targets T={T} ==", flush=True)
    t0 = time.perf_counter()
    soft_logits = logits_of(teacher, train_xy[0])
    distilled = MLP(800)
    hist, secs = train("student_distilled", distilled, epochs["student_distilled"], train_xy, test_xy,
                       gen, soft_logits=soft_logits)
    results["student_distilled"] = (hist, time.perf_counter() - t0)

    total_s = time.perf_counter() - run_start
    print("\n== summary (test errors /10,000; one seed) ==", flush=True)
    models = {}
    for i, name in enumerate(("teacher", "student_hard", "student_distilled"), start=1):
        hist, secs = results[name]
        errs = hist[-1]["test_errors"]
        paper = PAPER[f"{name}_test_errors"]
        err_line = metric(f"final_{name}_test_errors", errs, i)
        wall_line = metric(f"final_{name}_wall_s", round(secs, 1), i)
        print(f"  {name:<18} ours {errs:>4}   paper {paper:>4}   diff {errs - paper:+5d}   "
              f"wall {secs:6.1f}s  ({epochs[name]} epochs)", flush=True)
        models[name] = {
            "test_errors": errs, "paper_test_errors": paper, "diff": errs - paper,
            "epochs": epochs[name], "wall_clock_s": round(secs, 1),
            "log_lines": {"test_errors": err_line, "wall_clock_s": wall_line},
            "history": hist,
        }
    total_line = metric("total_wall_s", round(total_s, 1), 0)
    gap_hard = models["student_hard"]["test_errors"]
    gap_dist = models["student_distilled"]["test_errors"]
    print(f"  distilled < hard-label: {gap_dist < gap_hard} ({gap_dist} vs {gap_hard})  "
          f"total wall {total_s:.1f}s", flush=True)

    out = {
        "paper": PAPER,
        "mode": mode,
        "seed": args.seed,
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "environment": {"python": sys.version.split()[0], "torch": torch.__version__,
                        "platform": platform.platform(), "machine": platform.machine(),
                        "threads": torch.get_num_threads()},
        "settings": {
            "batch": BATCH, "optimizer": "SGD", "lr": LR, "momentum": MOMENTUM,
            "quick_epochs_note": "cut to fit <=15 min on CPU; paper trains to convergence",
            "lr_schedule": "linear decay to 0", "normalise": [MEAN, STD],
            "teacher": {"hidden": [1200, 1200], "dropout_input": DROPOUT_IN,
                        "dropout_hidden": DROPOUT_HID, "max_norm": MAX_NORM, "jitter_px": JITTER},
            "student_hard": {"hidden": [800, 800], "regularisation": "none"},
            "student_distilled": {"hidden": [800, 800], "temperature": T,
                                  "soft_weight": SOFT_WEIGHT, "hard_weight": round(1 - SOFT_WEIGHT, 2),
                                  "soft_loss": "KL(teacher_T || student_T) * T^2",
                                  "transfer_set": "MNIST train (60,000), no jitter"},
        },
        "models": models,
        "distilled_beats_hard": gap_dist < gap_hard,
        "total_wall_clock_s": round(total_s, 1),
        "total_log_line": total_line,
        "metric_log": LOG,
    }
    Path(args.out).write_text(json.dumps(out, indent=2) + "\n")
    print(f"\nwrote {Path(args.out).resolve()}", flush=True)


if __name__ == "__main__":
    main()
