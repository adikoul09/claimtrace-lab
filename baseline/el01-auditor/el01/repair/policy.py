"""Repair policy (spec section 4): code, not the LLM, decides whether a patch is a repair or a hypothesis.

The LLM's class is advisory: the policy only ever escalates. A patch is a hypothesis if its added or removed lines
(never the unchanged context) show any of:
  number     a numeric literal added or removed ("changes any number used in training")
  data       a data-generation script is touched, or a changed line names data, split, domain or seed settings
  training   a changed line names the model, loss, optimizer, metric, model selection or the training schedule
  llm        the agent itself called it a hypothesis
Otherwise the class follows from the failure the patch answers: a missing path, no GPU or a missing import is an
environment repair (`env`); anything else, including a missing attribute or API, is a compatibility repair (`compat`),
which must then pass the inertness check. Every decision lists the rules that fired and the tokens that fired them."""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

# --- lexing changed lines (single lines; unbalanced brackets and docstring fragments are fine) ---------------------
STRING_RE = re.compile(r"""[rRbBuUfF]{0,2}("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')""")
TOKEN_RE = re.compile(r"""(?P<str>[rRbBuUfF]{0,2}(?:"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'))"""
                      r"""|(?P<comment>\#.*$)"""
                      r"""|(?P<num>(?<![\w.])(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?[jJ]?(?![\w]))"""
                      r"""|(?P<name>[A-Za-z_]\w*)""")
PY_KEYWORDS = {"False", "None", "True", "and", "as", "assert", "async", "await", "break", "class", "continue", "def",
               "del", "elif", "else", "except", "finally", "for", "from", "global", "if", "import", "in", "is",
               "lambda", "nonlocal", "not", "or", "pass", "raise", "return", "try", "while", "with", "yield", "self"}

# --- vocabularies (whole words of identifiers, split on '_' and camelCase) ------------------------------------------
DATA_WORDS = {"domain", "domains", "split", "splits", "seed", "seeds", "spur", "corr", "shuffle", "augment",
              "augmentation", "transform", "transforms", "flip", "crop", "rotate", "rotation", "rotations",
              "normalize", "subset", "subsets", "fold", "folds", "num_samples", "samples", "holdout"}
TRAINING_WORDS = {
    # optimizer and schedule
    "sgd", "adam", "adamw", "rmsprop", "adagrad", "optim", "optimizer", "optimizers", "lr", "learning", "momentum",
    "nesterov", "decay", "scheduler", "warmup", "epoch", "epochs", "batch", "iterations", "iters", "clip",
    # loss
    "loss", "losses", "criterion", "penalty", "entropy", "nll", "mse", "wasserstein", "contrastive", "margin",
    "tau", "temperature", "regularizer", "regularization",
    # model
    "model", "models", "layer", "layers", "linear", "conv", "hidden", "dropout", "forward", "relu", "activation",
    "architecture", "backbone", "classifier", "embedding", "weights", "pretrained",
    # metric and evaluation
    "acc", "accuracy", "metric", "metrics", "score", "auc", "f1", "precision", "recall",
    # model selection
    "best", "early", "stopping", "patience", "select", "selection", "checkpoint", "ckpt",
}
DATA_GEN_FILE_RE = re.compile(r"(^|/)(data_?gen\w*|gen\w*_data\w*|generate\w*|make_?data\w*|build_?data\w*|"
                              r"prepare\w*|preprocess\w*|download\w*|create_?data\w*)\.py$", re.I)
ENV_FAILURES = {"missing path", "no GPU", "missing data"}
IMPORT_EXC = {"ModuleNotFoundError", "ImportError"}


@dataclass
class FileDiff:
    path: str
    added: list[tuple[int, str]] = field(default_factory=list)    # (new line number, text)
    removed: list[tuple[int, str]] = field(default_factory=list)  # (old line number, text)


HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def parse_unified_diff(diff: str) -> list[FileDiff]:
    """Added and removed lines per file, with line numbers. Headers are read only between `diff --git` (or the first
    `--- `) and the first hunk, so a content line that starts with `---` is never taken for a header."""
    files: list[FileDiff] = []
    cur: Optional[FileDiff] = None
    in_header, remaining = True, 0
    old = new = 0
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            cur, in_header, remaining = None, True, 0
            continue
        if remaining <= 0 and line.startswith("--- "):
            path = line[4:].strip().split("\t")[0]
            cur, in_header = FileDiff(path[2:] if path.startswith("a/") else path), True
            continue
        if in_header and line.startswith("+++ ") and cur is not None:
            path = line[4:].strip().split("\t")[0]
            path = path[2:] if path.startswith("b/") else path
            if path != "/dev/null":  # a deleted file keeps its old path
                cur.path = path
            files.append(cur)
            in_header = False
            continue
        m = HUNK_RE.match(line)
        if m and cur is not None:
            old, new = int(m[1]), int(m[3])
            remaining = int(m[2] if m[2] is not None else 1) + int(m[4] if m[4] is not None else 1)
            in_header = False
            continue
        if cur is None or in_header or line.startswith("\\"):
            continue
        if line.startswith("+"):
            cur.added.append((new, line[1:]))
            new += 1
            remaining -= 1
        elif line.startswith("-"):
            cur.removed.append((old, line[1:]))
            old += 1
            remaining -= 1
        elif line.startswith(" ") or line == "":
            old += 1
            new += 1
            remaining -= 2
    return files


def lex(line: str) -> list[tuple[str, str]]:
    """(kind, value) for strings, numbers and identifiers; comments are dropped."""
    out = []
    for m in TOKEN_RE.finditer(line):
        kind = m.lastgroup
        if kind == "comment":
            break
        out.append((kind, m.group(kind)))
    return out


def words(identifier: str) -> list[str]:
    parts = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", identifier).lower().split("_")
    return [p for p in parts if p]


def _hits(names: list[str], vocab: set[str]) -> list[str]:
    hits = []
    for n in names:
        if n in PY_KEYWORDS:
            continue
        joined = n.lower()
        if joined in vocab or any(w in vocab for w in words(n)):
            hits.append(n)
    return sorted(set(hits))


def classify_patch(diff: str, failure_class: Optional[str], exception: Optional[str] = None,
                   llm_class: Optional[str] = None) -> dict:
    """Decide env / compat / hypothesis for a unified diff. Returns {"class", "llm_class", "rules", "basis"}."""
    rules = []
    files = parse_unified_diff(diff)
    for f in files:
        if DATA_GEN_FILE_RE.search(f.path):
            rules.append({"rule": "data", "why": f"touches a data-generation script: {f.path}"})
        add = Counter(t for _, l in f.added for t in lex(l))
        rem = Counter(t for _, l in f.removed for t in lex(l))
        changed_nums = sorted({v for (k, v) in (add - rem) + (rem - add) if k == "num"})
        if changed_nums:
            rules.append({"rule": "number", "why": f"{f.path}: numeric literal(s) added or removed: "
                                                   + ", ".join(changed_nums)})
        names = [v for (k, v) in list(add) + list(rem) if k == "name"]
        d = _hits(names, DATA_WORDS)
        if d:
            rules.append({"rule": "data", "why": f"{f.path}: changed lines name data settings: {', '.join(d)}"})
        t = _hits(names, TRAINING_WORDS)
        if t:
            rules.append({"rule": "training", "why": f"{f.path}: changed lines name model/loss/optimizer/metric/"
                                                     f"selection/schedule settings: {', '.join(t)}"})
    if llm_class == "hypothesis":
        rules.append({"rule": "llm", "why": "the agent classed the patch as a hypothesis"})
    if not files:
        rules.append({"rule": "empty", "why": "the patch changes no file"})
    if rules:
        cls = "hypothesis"
        basis = "; ".join(r["why"] for r in rules)
    elif failure_class in ENV_FAILURES or (failure_class == "other" and exception in IMPORT_EXC):
        cls = "env"
        basis = f"answers a '{failure_class}' failure ({exception}) and changes no data, training setting or number"
    else:
        cls = "compat"
        basis = (f"answers a '{failure_class}' failure ({exception}) and changes no data, training setting or "
                 f"number; needs the inertness check")
    return {"class": cls, "llm_class": llm_class, "rules": rules, "basis": basis,
            "files": [f.path for f in files]}


def guarded_statements(diff: str) -> list[dict]:
    """Statements the patch kept but moved under a new condition: an added line whose text equals a removed line's
    text (stripped) with more indentation. Returns [{"file", "line" (new numbering), "text"}]."""
    out = []
    for f in parse_unified_diff(diff):
        removed = {}
        for _, l in f.removed:
            removed.setdefault(l.strip(), len(l) - len(l.lstrip()))
        for n, l in f.added:
            s = l.strip()
            if s and s in removed and (len(l) - len(l.lstrip())) > removed[s]:
                out.append({"file": f.path, "line": n, "text": s})
    return out
