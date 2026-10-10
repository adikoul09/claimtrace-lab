"""Rule 2: the version 2 verdict rules are frozen, byte for byte."""
import hashlib

from el01.config import ROOT

FROZEN = "7721a4727c1636d8f8e3f9610897eee7ffc00d3c7d44d2542f99f0d66974a83d"
LEGACY = ROOT / "el01" / "grade" / "legacy" / "verdicts_v2.py"
SPIKE = ROOT / "inputs" / "spike-matchdg" / "scripts" / "verdicts.py"


def test_legacy_verdicts_hash():
    assert hashlib.sha256(LEGACY.read_bytes()).hexdigest() == FROZEN


def test_legacy_is_the_spike_file():
    assert LEGACY.read_bytes() == SPIKE.read_bytes()
