"""The real command-line interface of a script under audit, read from its own argparse parser.

`probe(python, worktree, script, candidates)` runs the script in the audited environment under a small bootstrap that
replaces `ArgumentParser.parse_args` / `parse_known_args`: when the script reaches its parse call, the bootstrap
records the parser's actions and its help text (exactly what `--help` prints), parses each candidate argument list
with the script's own parser (its types, nargs, choices and defaults), writes JSON and exits before any of the
script's work runs. Only scripts whose source calls `parse_args` / `parse_known_args` are run; any other script takes
no flags. Code, not the linker, decides whether a command is valid:
  - every option token must be an option the parser defines, or an abbreviation that argparse resolves to exactly one
    of them (recorded as such);
  - the script's own parser must accept the whole list;
and two commands are the same when their parsed namespaces (defaults filled in, values converted by the script's own
types) are equal. Probing imports the script's modules (torch etc.), so it takes a few seconds per script."""
from __future__ import annotations

import ast
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Sequence

from el01.run.runner import job_env

BOOTSTRAP = r'''
import argparse, json, os, runpy, sys
OUT = os.environ["EL01_ARGSPEC_OUT"]
CANDIDATES = json.loads(os.environ["EL01_ARGSPEC_CANDIDATES"])
_orig_parse_known = argparse.ArgumentParser.parse_known_args

def _safe(v):
    try:
        json.dumps(v)
        return v
    except TypeError:
        return repr(v)

class _Bad(Exception):
    pass

def _dump(self, args=None, namespace=None):
    actions = []
    for a in self._actions:
        actions.append({"option_strings": list(a.option_strings), "dest": a.dest, "kind": type(a).__name__,
                        "type": getattr(a.type, "__name__", None) if a.type is not None else None,
                        "nargs": _safe(a.nargs), "default": _safe(a.default), "const": _safe(a.const),
                        "choices": _safe(list(a.choices)) if a.choices is not None else None,
                        "required": a.required})
    def error(message):
        raise _Bad(message)
    self.error = error
    results = []
    for cand in CANDIDATES:
        try:
            ns, extra = _orig_parse_known(self, list(cand))
            if extra:
                raise _Bad("unrecognized arguments: " + " ".join(extra))
            results.append({"ok": True, "namespace": {k: _safe(v) for k, v in sorted(vars(ns).items())}})
        except _Bad as e:
            results.append({"ok": False, "error": str(e)})
    try:
        help_text, help_error = self.format_help(), None
    except Exception as e:  # e.g. an unescaped % in a help string: `--help` itself crashes
        help_error = type(e).__name__ + ": " + str(e)
        import re
        fmt = self._get_formatter()
        for a in self._actions:
            if a.help:
                try:
                    fmt._expand_help(a)
                except Exception:
                    a.help = re.sub(r"%(?!\()", "%%", a.help)
        help_text = self.format_help()
    text = json.dumps({"prog": self.prog, "actions": actions, "help": help_text, "help_error": help_error,
                       "results": results})
    with open(OUT, "w") as f:
        f.write(text)
    sys.stdout.flush()
    os._exit(0)

argparse.ArgumentParser.parse_args = _dump
argparse.ArgumentParser.parse_known_args = _dump
script = sys.argv[1]
sys.argv = [script]
sys.path.insert(0, os.path.dirname(os.path.abspath(script)))
runpy.run_path(script, run_name="__main__")
'''


class ProbeError(RuntimeError):
    pass


def parses_args(source: str) -> bool:
    """Does the script call parse_args / parse_known_args anywhere?"""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    return any(isinstance(n, ast.Attribute) and n.attr in ("parse_args", "parse_known_args") for n in ast.walk(tree))


def probe(python: Path, worktree: Path, script: str, candidates: Sequence[Sequence[str]] = (),
          timeout: int = 300) -> dict:
    """{"script", "argparse": bool, "actions", "help", "results": [{"ok", "namespace" | "error"}]}."""
    src = Path(worktree) / script
    if not src.is_file():
        raise ProbeError(f"{script}: no such file in the worktree")
    if not parses_args(src.read_text(errors="replace")):
        return {"script": script, "argparse": False, "actions": [], "help": None,
                "results": [{"ok": not c, **({"namespace": {}} if not c else
                                             {"error": f"{script} defines no command-line options"})}
                            for c in candidates]}
    with tempfile.TemporaryDirectory(prefix="el01-argspec-") as tmp:
        out = Path(tmp) / "spec.json"
        env = job_env(python)
        env["EL01_ARGSPEC_OUT"] = str(out)
        env["EL01_ARGSPEC_CANDIDATES"] = json.dumps([list(c) for c in candidates])
        p = subprocess.run([str(python), "-c", BOOTSTRAP, script], cwd=worktree, env=env, capture_output=True,
                           text=True, timeout=timeout)
        if not out.exists() or not out.read_text():
            raise ProbeError(f"{script}: the script never reached its argument parser (exit {p.returncode}): "
                             f"{(p.stderr or p.stdout)[-1500:]}")
        spec = json.loads(out.read_text())
    spec.update(script=script, argparse=True)
    return spec


def option_strings(spec: dict) -> set[str]:
    return {o for a in spec["actions"] for o in a["option_strings"]}


def option_check(spec: dict, args: Sequence[str]) -> tuple[list[str], dict[str, str]]:
    """(unknown option tokens, {abbreviation: full option}). An abbreviation is a long option that is the prefix of
    exactly one option the parser defines (argparse's prefix matching, which the repo's own commands may rely on:
    robustdg writes `--dataset` for `--dataset_name`); an ambiguous or unmatched one is unknown."""
    known = option_strings(spec)
    unknown, abbrev = [], {}
    for tok in args:
        if tok.startswith("-") and len(tok) > 1 and not _is_number(tok):
            name = tok.split("=", 1)[0]
            if name in known:
                continue
            hits = sorted(o for o in known if o.startswith("--") and name.startswith("--") and o.startswith(name))
            if len(hits) == 1:
                abbrev[name] = hits[0]
            else:
                unknown.append(tok)
    return unknown, abbrev


def _is_number(tok: str) -> bool:
    try:
        float(tok)
        return True
    except ValueError:
        return False


def set_option(args: Sequence[str], option: str, value: str) -> list[str]:
    """`args` with `option` set to the single value `value` (replacing its values, or appended)."""
    out, i, found = [], 0, False
    args = list(args)
    while i < len(args):
        tok = args[i]
        if tok == option:
            out += [option, value]
            found = True
            i += 1
            while i < len(args) and not (args[i].startswith("-") and not _is_number(args[i])):
                i += 1
            continue
        if tok.startswith(option + "="):
            out.append(f"{option}={value}")
            found = True
            i += 1
            continue
        out.append(tok)
        i += 1
    return out if found else out + [option, value]


def diff_namespaces(a: dict, b: dict, ignore: Sequence[str] = ()) -> dict:
    """{dest: (a value, b value)} for every dest that differs, except `ignore`."""
    keys = sorted((set(a) | set(b)) - set(ignore))
    return {k: (a.get(k), b.get(k)) for k in keys if a.get(k) != b.get(k)}


def check_command(spec: dict, args: Sequence[str], result: Optional[dict]) -> list[str]:
    """Problems with one command (script arguments only), given its probe result."""
    unknown, _ = option_check(spec, args)
    problems = [f"unknown option {t!r}: {spec['script']}'s parser defines no such option" for t in unknown]
    if result is not None and not result.get("ok"):
        problems.append(f"{spec['script']}'s parser rejects it: {result.get('error')}")
    return problems
