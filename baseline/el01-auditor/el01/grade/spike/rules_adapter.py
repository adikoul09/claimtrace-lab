"""One interface over the two rule modules, so a grader can run on either and the outputs can be compared.

legacy_rules(): the frozen version 2 (el01/grade/legacy/verdicts_v2.py). The MatchDG run sets pre-registered the sha256
of this file, so grading the spike uses it by default.
rules_v21(): version 2.1 (el01/grade/rules.py), with the MatchDG findings passed in."""
from functools import partial
from types import SimpleNamespace

from el01.grade import rules as v21
from el01.grade.legacy import verdicts_v2 as v2
from el01.grade.spike import matchdg

_FIELDS = ("RULES_VERSION", "PRACTICAL_FLOOR", "absolute_verdict", "relative_verdict", "paired", "sample_sd", "label")


def legacy_rules():
    return SimpleNamespace(**{k: getattr(v2, k) for k in _FIELDS}, setup_flag=v2.setup_flag)


def rules_v21(findings=None, branch_findings=None, short=None):
    flag = partial(v21.setup_flag,
                   findings=matchdg.FINDINGS if findings is None else findings,
                   branch_findings=matchdg.BRANCH_FINDINGS if branch_findings is None else branch_findings,
                   short=matchdg.SHORT if short is None else short)
    return SimpleNamespace(**{k: getattr(v21, k) for k in _FIELDS}, setup_flag=flag)
