"""Classify the first failure of a run from its log: the last Python traceback, read by code.

Classes (checked in this order):
  no GPU                     CUDA / NVIDIA driver messages, e.g. "Torch not compiled with CUDA enabled"
  missing attribute or API   AttributeError, or ImportError "cannot import name"
  missing path               FileNotFoundError on an absolute path outside the worktree and the workspace
  missing data               FileNotFoundError on a relative path or a path inside the worktree or the workspace
  other                      anything else (including ModuleNotFoundError, which the env builder should have prevented)
Every location keeps its log line (rule 3). For path errors the string literal the missing path starts with is looked
up in the source (AST), so a hard-coded path is reported where it is written, not only where `open()` raised."""
from __future__ import annotations

import ast
import glob
import re
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Optional, Sequence

TB_START = "Traceback (most recent call last):"
FRAME_RE = re.compile(r'^\s*File "(?P<file>[^"]+)", line (?P<line>\d+)(, in (?P<func>.+))?$')
EXC_RE = re.compile(r"^(?P<type>[A-Za-z_][\w.]*)(: ?(?P<msg>.*))?$")
GPU_RE = re.compile(r"Found no NVIDIA driver|Torch not compiled with CUDA enabled|no CUDA-capable device|CUDA driver|"
                    r"CUDA error|cuda runtime error|No CUDA GPUs are available|CUDA is not available|"
                    r"Attempting to deserialize object on a CUDA device", re.I)
MISSING_FILE_RE = re.compile(r"No such file or directory: ['\"](?P<path>.+?)['\"]\s*$")
PATH_ERRORS = {"FileNotFoundError", "IsADirectoryError", "NotADirectoryError"}


@dataclass
class Frame:
    file: str                 # as printed in the log
    line: int
    func: str
    log_line: int
    repo_file: Optional[str]  # repo-relative posix path, if the frame is in the audited code


@dataclass
class Traceback:
    frames: list[Frame]
    exc_type: str
    message: str
    log_line: int             # line of the exception message
    start_line: int           # line of "Traceback (most recent call last):"


def _rel(file: str, roots: Sequence[str]) -> Optional[str]:
    win = "\\" in file
    P = PureWindowsPath if win else PurePosixPath
    f = P(file)
    if file.startswith("<"):  # <frozen importlib._bootstrap>, <string>, <stdin>
        return None
    if not f.is_absolute():
        return f.as_posix()
    for r in roots:
        try:
            return f.relative_to(P(r)).as_posix()
        except ValueError:
            continue
    return None


def last_traceback(lines: list[str], roots: Sequence[str] = ()) -> Optional[Traceback]:
    """The last traceback in the log (with chained exceptions, the one raised last). Line numbers are 1-based."""
    starts = [i for i, l in enumerate(lines) if l.strip() == TB_START]
    if not starts:
        return None
    i, frames = starts[-1] + 1, []
    while i < len(lines):
        m = FRAME_RE.match(lines[i])
        if m:
            frames.append(Frame(m["file"], int(m["line"]), (m["func"] or "").strip(), i + 1, _rel(m["file"], roots)))
        elif lines[i] and not lines[i][0].isspace():
            e = EXC_RE.match(lines[i].strip())
            if e:
                return Traceback(frames, e["type"], (e["msg"] or "").strip(), i + 1, starts[-1] + 1)
            return Traceback(frames, "Unknown", lines[i].strip(), i + 1, starts[-1] + 1)
        i += 1
    return Traceback(frames, "Unknown", "", len(lines), starts[-1] + 1)


def path_literal(source: Path, missing: str, before_line: Optional[int] = None) -> Optional[dict]:
    """The longest path-like string constant in `source` that the missing path starts with (or contains)."""
    try:
        tree = ast.parse(source.read_bytes())
    except (OSError, SyntaxError, ValueError):
        return None
    best = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            s = node.value
            if len(s) < 2 or not ("/" in s or "\\" in s) or s not in missing:
                continue
            key = (missing.startswith(s), len(s), -(abs((before_line or node.lineno) - node.lineno)))
            if best is None or key > best[0]:
                best = (key, {"line": node.lineno, "literal": s})
    return best[1] if best else None


def _inside(path: str, dirs: Sequence[Path]) -> bool:
    p = Path(path)
    for d in dirs:
        for base in {Path(d), Path(d).resolve()}:
            try:
                p.relative_to(base)
                return True
            except ValueError:
                continue
    return False


def classify(log: Path, log_roots: Sequence[str], source_root: Path, inside: Sequence[Path] = ()) -> Optional[dict]:
    """Classify the last traceback of `log`.

    log_roots    how the repo's root is spelled in the log's frames (the worktree path, or e.g. the spike's
                 /home/claude/spike/robustdg); frames under it are the audited code
    source_root  where the same code is on this machine (to look up string literals)
    inside       folders that count as "ours" for path errors (the worktree, the workspace)
    Returns None if the log has no traceback."""
    lines = Path(log).read_text(errors="replace").splitlines()
    roots = [str(r) for r in log_roots] + [str(Path(r).resolve()) for r in log_roots if Path(r).exists()]
    tb = last_traceback(lines, roots)
    if tb is None:
        return None
    exc, msg = tb.exc_type.rsplit(".", 1)[-1], tb.message
    repo_frames = [f for f in tb.frames if f.repo_file]
    raised = repo_frames[-1] if repo_frames else (tb.frames[-1] if tb.frames else None)
    out = {"class": "other", "rule": "no rule matched", "exception": tb.exc_type, "message": msg,
           "log_line": tb.log_line, "traceback_line": tb.start_line,
           "raised_at": ({"file": raised.repo_file or raised.file, "line": raised.line, "func": raised.func,
                          "log_line": raised.log_line} if raised else None),
           "origin": None, "frames": [asdict(f) for f in tb.frames]}
    m = MISSING_FILE_RE.search(msg)
    if GPU_RE.search(msg):
        out.update({"class": "no GPU", "rule": "CUDA / NVIDIA driver message"})
    elif exc == "AttributeError" or (exc == "ImportError" and "cannot import name" in msg):
        out.update({"class": "missing attribute or API", "rule": f"{exc}"})
    elif exc in PATH_ERRORS or (exc in ("OSError", "IOError") and m):
        missing = m["path"] if m else msg
        out["missing_path"] = missing
        absolute = PurePosixPath(missing).is_absolute() or PureWindowsPath(missing).is_absolute()
        ours = list(inside) + [Path(r) for r in log_roots]
        if absolute and not _inside(missing, ours):
            out.update({"class": "missing path",
                        "rule": f"{exc} on an absolute path outside the worktree and the workspace"})
        else:
            out.update({"class": "missing data",
                        "rule": f"{exc} on a {'path inside the worktree or the workspace' if absolute else 'relative path'}"})
        for f in reversed(repo_frames):  # innermost audited frame first
            lit = path_literal(Path(source_root) / f.repo_file, missing, f.line)
            if lit:
                out["origin"] = {"file": f.repo_file, **lit}
                break
        name = PurePosixPath(missing.replace("\\", "/")).name
        hits = sorted(p.relative_to(source_root).as_posix() for p in Path(source_root).rglob(glob.escape(name))) if name else []
        out["same_name_in_worktree"] = hits[:5]
    loc = out["origin"] or out["raised_at"]
    out["location"] = f"{loc['file']}:{loc['line']}" if loc else None
    return out
