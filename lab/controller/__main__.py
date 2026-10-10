"""uv run python -m lab.controller [--once] [--interval S] [--project ID]"""
import argparse
import sys

from lab.controller.loop import Controller
from lab.controller.rules import TICK_S


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="ClaimTrace Lab meta-controller")
    ap.add_argument("--once", action="store_true", help="run start-up and one tick, then exit")
    ap.add_argument("--interval", type=float, default=TICK_S)
    ap.add_argument("--project", help="act only on this project id (tests and demos)")
    ap.add_argument("--apply-step-floors", action="store_true",
                    help="raise active agents below their max_steps floor now, then exit")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # event text has arrows; Windows consoles are cp1252
    c = Controller(project_id=a.project)
    if a.apply_step_floors:
        print("raised:", c.apply_step_floors() or "none")
        return
    if a.once:
        c.startup()
        c.tick()
        return
    try:
        c.serve(a.interval)
    except KeyboardInterrupt:
        print("[controller] stopping", flush=True)


if __name__ == "__main__":
    main()
