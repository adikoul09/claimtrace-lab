# Inertness check for REPAIR(compat) 45e7771: count every Python call into opacus during a real run.
import sys, runpy, collections
import opacus, opacus.dp_model_inspector, opacus.utils.module_modification  # import first so only runtime calls are counted
calls = collections.Counter()
def prof(frame, event, arg):
    if event == "call":
        f = frame.f_code.co_filename
        if "/opacus/" in f:
            calls[f"{f.split('site-packages/')[-1]}:{frame.f_code.co_name}"] += 1
sys.setprofile(prof)
sys.argv = ["train.py"] + sys.argv[1:]
sys.path.insert(0, ".")
try:
    runpy.run_path("train.py", run_name="__main__")
finally:
    sys.setprofile(None)
    print("OPACUS_CALLS_TOTAL", sum(calls.values()))
    for k, v in calls.most_common(20): print("OPACUS_CALL", v, k)
