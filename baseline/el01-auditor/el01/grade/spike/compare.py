"""Compare our outputs with the spike's copies: cited-log path normalisation and an exact, typed JSON diff."""
import math
import re

_PREFIXES = ("/home/claude/spike/runs/", "runs/", "logs/")
_BARE = re.compile(r"[^/\s]+/[^/\s]+\.log")


def normalise_path(s):
    """A cited log, in any of the spike's forms, as `logs/<run>/<file>`:
    /home/claude/spike/runs/<run>/<f> (metrics, grades), runs/<run>/<f> (grades_f7), <run>/<f> (epochs.json),
    and our own logs/<run>/<f>. Other values are returned unchanged."""
    if not isinstance(s, str) or not s.endswith(".log"):
        return s
    for pre in _PREFIXES:
        if s.startswith(pre):
            return "logs/" + s[len(pre):]
    return "logs/" + s if _BARE.fullmatch(s) else s


def normalise_paths(x):
    if isinstance(x, dict):
        return {k: normalise_paths(v) for k, v in x.items()}
    if isinstance(x, list):
        return [normalise_paths(v) for v in x]
    return normalise_path(x)


def json_diff(expected, got, path="$", limit=50, _out=None):
    """Every JSON path where `got` differs from `expected` (types included: 1 vs 1.0 vs True all differ; NaN equals NaN)."""
    out = [] if _out is None else _out
    if len(out) >= limit:
        return out
    if isinstance(expected, dict) and isinstance(got, dict):
        for k in sorted(set(expected) | set(got), key=str):
            if k not in got:
                out.append(f"{path}.{k}: missing in ours")
            elif k not in expected:
                out.append(f"{path}.{k}: not in the spike's copy")
            else:
                json_diff(expected[k], got[k], f"{path}.{k}", limit, out)
    elif isinstance(expected, list) and isinstance(got, list):
        if len(expected) != len(got):
            out.append(f"{path}: length {len(expected)} in the spike's copy, {len(got)} in ours")
        else:
            for i, (a, b) in enumerate(zip(expected, got)):
                json_diff(a, b, f"{path}[{i}]", limit, out)
    elif type(expected) is not type(got):
        out.append(f"{path}: spike {expected!r:.80} ({type(expected).__name__}), ours {got!r:.80} ({type(got).__name__})")
    elif isinstance(expected, float) and math.isnan(expected) and math.isnan(got):
        pass
    elif expected != got:
        out.append(f"{path}: spike {expected!r:.80}, ours {got!r:.80}")
    return out
