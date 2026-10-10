"""The inertness tracer (port of trace_opacus.py) counts library calls and guarded-line executions."""
import json
import subprocess
import sys
from pathlib import Path

from el01.repair.inertness import TRACE_SCRIPT, map_lines, metric_lines, patch_libraries
from el01.repair.policy import guarded_statements

SCRIPT = '''import json, sys
import yaml
n = int(sys.argv[1])
for i in range(n):
    if i == 99:
        yaml.safe_load("a: 1")
print("Accuracy:", 50.0)
for i in range(n):
    json.dumps(i)
yaml.safe_dump({"a": n})
'''


def _trace(tmp_path, n):
    (tmp_path / "s.py").write_text(SCRIPT)
    out = tmp_path / "t.json"
    subprocess.run([sys.executable, str(TRACE_SCRIPT), "--out", str(out), "--lib", "yaml", "--line", "s.py:6",
                    "--", "s.py", str(n)], cwd=tmp_path, check=True, capture_output=True)
    return json.loads(out.read_text())


def test_counts_calls_and_lines(tmp_path):
    t = _trace(tmp_path, 3)
    assert t["outcome"] == "completed" and t["preimported"] == {"yaml": "imported"}
    assert t["line_hits"] == {"s.py:6": 0}
    assert t["lib_calls_total"] > 0  # safe_dump at the end runs inside yaml
    assert all(k.startswith("yaml/") for k, _ in t["lib_calls"])
    t = _trace(tmp_path, 100)
    assert t["line_hits"] == {"s.py:6": 1}


def test_crash_is_recorded(tmp_path):
    (tmp_path / "s.py").write_text("raise RuntimeError('boom')\n")
    out = tmp_path / "t.json"
    p = subprocess.run([sys.executable, str(TRACE_SCRIPT), "--out", str(out), "--", "s.py"], cwd=tmp_path,
                       capture_output=True)
    t = json.loads(out.read_text())
    assert p.returncode == 1 and t["outcome"] == "crashed" and "boom" in t["exception"]


def test_patch_libraries_and_lines(tmp_path):
    (tmp_path / "algo.py").write_text("import os\nimport yaml\nfrom json import dumps\n\ndef f(a):\n"
                                      "    import yaml.loader\n    if a.dp:\n        yaml.dump(1)\n"
                                      "    os.getcwd()\n")
    diff = ("--- a/algo.py\n+++ b/algo.py\n@@ -6,3 +6,4 @@\n     import yaml.loader\n-    yaml.dump(1)\n"
            "+    if a.dp:\n+        yaml.dump(1)\n     os.getcwd()\n")
    libs, pre = patch_libraries(diff, tmp_path)
    assert libs == ["yaml"] and pre == ["yaml.loader"]
    assert map_lines(guarded_statements(diff), tmp_path) == ["algo.py:8"]


def test_metric_lines(tmp_path):
    log = tmp_path / "x.log"
    log.write_text("Run 0\n Accuracy:  val 98.4\nreal\t0m6.029s\nFinal Test Accuracy (Source Validation) 60.1 0.0\n")
    assert metric_lines(log) == [(2, "Accuracy:  val 98.4"), (4, "Final Test Accuracy (Source Validation) 60.1 0.0")]
