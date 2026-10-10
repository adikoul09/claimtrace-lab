"""The scripts' own argparse parsers judge commands: probing stops at the parse call, before any work."""
import sys
from pathlib import Path

from el01.link import argspec

TOY = '''import argparse
p = argparse.ArgumentParser()
p.add_argument('--dataset_name', type=str, default='rot_mnist')
p.add_argument('--epochs', type=int, default=15, help='0.x" x% correct')   # robustdg-style: --help crashes
p.add_argument('--n_runs', type=int, default=3)
p.add_argument('--train_domains', nargs='+', type=str, default=['15', '30'])
p.add_argument('--lr', type=float, default=0.01)
args = p.parse_args()
open('RAN', 'w').write('the script body ran')
'''


def toy(tmp_path: Path) -> Path:
    (tmp_path / "train.py").write_text(TOY)
    (tmp_path / "gen.py").write_text("import argparse\nopen('GEN', 'w').write('ran')\n")
    return tmp_path


def test_probe_stops_at_the_parser_and_judges_candidates(tmp_path):
    wt = toy(tmp_path)
    cands = [["--dataset", "slab", "--epochs", "100"],          # abbreviation, as robustdg's own scripts write it
             ["--epochs", "x"],                                 # bad type
             ["--epoch", "3", "--bogus", "1"],                  # abbreviation + unknown option
             ["--train_domains", "0.0", "0.10", "--lr", "0.1"]]
    spec = argspec.probe(Path(sys.executable), wt, "train.py", cands)
    assert not (wt / "RAN").exists()
    assert spec["argparse"] and "--dataset_name" in argspec.option_strings(spec)
    assert spec["help_error"].startswith("TypeError") and "--train_domains" in spec["help"]
    r0, r1, r2, r3 = spec["results"]
    assert r0["ok"] and r0["namespace"] == {"dataset_name": "slab", "epochs": 100, "lr": 0.01, "n_runs": 3,
                                            "train_domains": ["15", "30"]}
    assert argspec.option_check(spec, cands[0]) == ([], {"--dataset": "--dataset_name"})
    assert not r1["ok"] and "invalid int value" in r1["error"]
    assert argspec.check_command(spec, cands[2], r2)[0].startswith("unknown option '--bogus'")
    assert r3["namespace"]["train_domains"] == ["0.0", "0.10"] and r3["namespace"]["lr"] == 0.1  # str type kept


def test_script_without_a_parser_is_not_run(tmp_path):
    wt = toy(tmp_path)
    spec = argspec.probe(Path(sys.executable), wt, "gen.py", [[], ["--x", "1"]])
    assert not spec["argparse"] and not (wt / "GEN").exists()
    assert spec["results"][0]["ok"] and not spec["results"][1]["ok"]


def test_set_option_and_diff():
    a = ["--epochs", "100", "--train_domains", "0", "15", "--n_runs", "10"]
    assert argspec.set_option(a, "--epochs", "1") == ["--epochs", "1", "--train_domains", "0", "15", "--n_runs", "10"]
    assert argspec.set_option(["--lr", "-0.5"], "--lr", "1") == ["--lr", "1"]           # a negative value is a value
    assert argspec.set_option(["--x", "1"], "--n_runs", "1") == ["--x", "1", "--n_runs", "1"]
    assert argspec.diff_namespaces({"a": 1, "n_runs": 3}, {"a": 1, "n_runs": 10}, ignore=["n_runs"]) == {}
    assert argspec.diff_namespaces({"a": "0.1"}, {"a": "0.10"}) == {"a": ("0.1", "0.10")}
