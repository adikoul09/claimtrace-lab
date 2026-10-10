# EL-01 runner shim, macOS only (el01/run/runner.py puts this folder on PYTHONPATH of audited jobs).
# Start worker processes with "fork", the default on Linux, where research code is written and was run; Python on
# macOS defaults to "spawn", which re-imports the main script in every worker (e.g. each DataLoader worker) and fails
# for scripts without an `if __name__ == "__main__":` guard. An environment setting, not a code change.
import multiprocessing as _mp

try:
    _mp.set_start_method("fork")
except RuntimeError:  # already set by the program
    pass
