"""Inertness trace (port of spike-matchdg/scripts/trace_opacus.py), generalised to any library and any patched lines.

Runs a script of the audited repo in the audited env and counts, during the real run:
  - every Python call into the named libraries (sys.setprofile), excluding module bodies (`<module>`, import time);
  - every execution of the named source lines (sys.settrace, line events in those files only).
The libraries and their submodules are imported first, so that only runtime calls are counted, as the spike did.

This file is executed by the audited interpreter (e.g. Python 3.9), so it uses the standard library only:
  python trace.py --out trace.json --lib opacus [--preimport opacus.x] [--line algorithms/algo.py:277] -- train.py <args>
The working directory must be the repo root. The JSON result is written even if the script crashes."""
import argparse
import collections
import importlib
import json
import os
import runpy
import sys
import traceback


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--lib", action="append", default=[], help="top-level package whose calls are counted")
    ap.add_argument("--preimport", action="append", default=[], help="module imported before tracing starts")
    ap.add_argument("--line", action="append", default=[], help="repo-relative file:line whose executions are counted")
    ap.add_argument("script", nargs=argparse.REMAINDER)
    a = ap.parse_args(argv)
    script = [s for s in a.script if s != "--"]
    if not script:
        ap.error("no script given")

    preimported = {}
    for mod in list(a.lib) + list(a.preimport):
        try:
            importlib.import_module(mod)
            preimported[mod] = "imported"
        except Exception as e:  # a submodule the installed version does not have
            preimported[mod] = "%s: %s" % (type(e).__name__, e)

    libdirs = {}
    for lib in a.lib:
        m = sys.modules.get(lib)
        paths = list(getattr(m, "__path__", []) or []) if m else []
        if m is not None and not paths and getattr(m, "__file__", None):
            paths = [os.path.dirname(m.__file__)]
        libdirs[lib] = [os.path.realpath(p) + os.sep for p in paths] or [os.sep + lib + os.sep]

    targets = collections.defaultdict(set)  # realpath -> {line}
    for spec in a.line:
        f, _, n = spec.rpartition(":")
        targets[os.path.realpath(f)].add(int(n))

    calls = collections.Counter()
    module_bodies = collections.Counter()
    hits = collections.Counter()
    path_cache = {}

    def lib_of(filename):
        r = path_cache.get(filename)
        if r is None:
            real = os.path.realpath(filename) if not filename.startswith("<") else filename
            r = ""
            for lib, dirs in libdirs.items():
                if any(real.startswith(d) for d in dirs):
                    r = lib
                    break
            path_cache[filename] = r
        return r

    def prof(frame, event, arg):
        if event != "call":
            return
        code = frame.f_code
        lib = lib_of(code.co_filename)
        if lib:
            name = "%s:%s" % (os.path.relpath(os.path.realpath(code.co_filename),
                                              os.path.dirname(libdirs[lib][0].rstrip(os.sep))), code.co_name)
            (module_bodies if code.co_name == "<module>" else calls)[name] += 1

    real_cache = {}

    def global_trace(frame, event, arg):
        fn = frame.f_code.co_filename
        real = real_cache.get(fn)
        if real is None:
            real = real_cache[fn] = os.path.realpath(fn) if not fn.startswith("<") else fn
        lines = targets.get(real)
        if not lines:
            return None
        rel = os.path.relpath(real)

        def local(frame, event, arg):
            if event == "line" and frame.f_lineno in lines:
                hits["%s:%d" % (rel, frame.f_lineno)] += 1
            return local
        return local

    sys.argv = list(script)
    sys.path.insert(0, os.getcwd())
    outcome, exc = "completed", None
    sys.setprofile(prof)
    if targets:
        sys.settrace(global_trace)
    try:
        runpy.run_path(script[0], run_name="__main__")
    except SystemExit as e:
        if e.code not in (None, 0):
            outcome, exc = "exited", "SystemExit(%r)" % (e.code,)
    except BaseException as e:
        outcome, exc = "crashed", "".join(traceback.format_exception_only(type(e), e)).strip()
        traceback.print_exc()
    finally:
        sys.settrace(None)
        sys.setprofile(None)
        res = {"script": script, "libs": a.lib, "lib_dirs": {k: [d for d in v] for k, v in libdirs.items()},
               "preimported": preimported, "outcome": outcome, "exception": exc,
               "lib_calls_total": sum(calls.values()), "lib_calls": calls.most_common(50),
               "lib_module_bodies_total": sum(module_bodies.values()),
               "lib_module_bodies": module_bodies.most_common(50),
               "lines": sorted(a.line), "line_hits": {s: hits.get(s, 0) for s in
                                                      ["%s:%d" % (os.path.relpath(f), n)
                                                       for f, ns in targets.items() for n in sorted(ns)]},
               "python": sys.version.split()[0]}
        with open(a.out, "w") as f:
            json.dump(res, f, indent=1)
        print("TRACE_LIB_CALLS_TOTAL", res["lib_calls_total"])
        for k, v in calls.most_common(20):
            print("TRACE_LIB_CALL", v, k)
        for k, v in res["line_hits"].items():
            print("TRACE_LINE_HITS", v, k)
    return 0 if outcome == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
