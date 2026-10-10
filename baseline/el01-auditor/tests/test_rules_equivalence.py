"""Rule 2: rules.py (version 2.1) keeps the statistics of version 2 unchanged and gives identical outputs on every
MatchDG input; only setup_flag's signature differs (findings, branch map and short names are arguments)."""
import inspect
import itertools
import json

import pytest

from el01.grade import rules as v21
from el01.grade.legacy import verdicts_v2 as v2
from el01.grade.spike import matchdg, table1, table11
from el01.grade.spike.compare import json_diff
from el01.grade.spike.rules_adapter import rules_v21

STATS = ["sample_sd", "welch", "absolute_verdict", "paired", "relative_verdict", "label"]


@pytest.mark.parametrize("name", STATS)
def test_statistical_functions_are_source_identical(name):
    assert inspect.getsource(getattr(v21, name)) == inspect.getsource(getattr(v2, name))


def test_constants_and_versions():
    assert (v21.PRACTICAL_FLOOR, v21.VERDICTS, v21.ABSOLUTE_VERDICTS) == (v2.PRACTICAL_FLOOR, v2.VERDICTS, v2.ABSOLUTE_VERDICTS)
    assert v2.RULES_VERSION == 2 and v21.RULES_VERSION == "2.1"
    for name in ("FINDINGS", "BRANCH_FINDINGS", "SHORT"):
        assert not hasattr(v21, name), f"rules 2.1 must not carry MatchDG constants ({name})"


def test_matchdg_constants_match_legacy_and_golden(paths):
    assert matchdg.FINDINGS == v2.FINDINGS
    assert matchdg.BRANCH_FINDINGS == v2.BRANCH_FINDINGS
    assert matchdg.SHORT == v2.SHORT
    assert json.loads((paths.golden / "findings.json").read_text()) == matchdg.FINDINGS


def test_graders_give_identical_outputs(graded_legacy, graded_v21):
    assert set(graded_legacy) == set(graded_v21) == {"table1", "table11_first", "table11_confirm", "f7"}
    for key in graded_legacy:
        a, b = dict(graded_legacy[key]), dict(graded_v21[key])
        if "rules_version" in a:
            assert (a.pop("rules_version"), b.pop("rules_version")) == (2, "2.1")
        assert json_diff(a, b) == [], key


def test_setup_flag_identical_on_every_method_subset(graded_legacy):
    """Every subset (size 1-2) of the Table 1 and Table 11 methods, with and without the filled finding, the
    re-tuned finding and the Table 1 effects."""
    flag21 = rules_v21().setup_flag
    cases = []
    for names, applies, effects in ((table1.NAMES, table1.APPLIES, graded_legacy["table1"]["effects"]),
                                    (table11.NAMES, table11.APPLIES, {})):
        for r in (1, 2):
            for methods in itertools.combinations(names, r):
                for filled, retuned in itertools.product(([], ["F1"]), ((), ("F6",))):
                    cases.append((list(methods), filled, applies, effects, names, retuned))
    assert len(cases) > 100
    for methods, filled, applies, effects, names, retuned in cases:
        assert v2.setup_flag(methods, filled, applies, effects, names, retuned) == \
               flag21(methods, filled, applies, effects, names, retuned)
