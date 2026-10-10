import pytest

from el01.config import Paths


@pytest.fixture(scope="session")
def paths():
    p = Paths.make()
    if not p.logs.is_dir():
        pytest.fail(f"{p.logs} is missing: extract inputs/spike-matchdg/logs.tar.gz there (Phase 0, step 4)")
    return p


@pytest.fixture(scope="session")
def parsed(paths):
    from el01.grade.spike.regress import parse_all
    return parse_all(paths)


@pytest.fixture(scope="session")
def graded_legacy(paths, parsed):
    from el01.grade.spike.regress import grade_all
    from el01.grade.spike.rules_adapter import legacy_rules
    return grade_all(paths, parsed, legacy_rules())


@pytest.fixture(scope="session")
def graded_v21(paths, parsed):
    from el01.grade.spike.regress import grade_all
    from el01.grade.spike.rules_adapter import rules_v21
    return grade_all(paths, parsed, rules_v21())
