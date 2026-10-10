"""Replay at zero quota: the settings prompts built today hit recorded responses, and code's checks, agreement and
diff over those recorded answers equal the committed settings.json and settings_diff.json."""
import json

import pytest

from el01.config import AuditConfig, Paths
from el01.extract import settings as S
from el01.llm.cache import Cache


@pytest.fixture(scope="module")
def setup():
    paths = Paths.make()
    cfg = AuditConfig.for_audit(paths, "matchdg")
    d = paths.audit_dir("matchdg")
    if not (d / "settings.json").exists():
        pytest.skip("no settings.json yet")
    from el01.extract.claims import load_claims, load_docs
    try:
        docs = load_docs(paths, cfg)
    except FileNotFoundError:
        pytest.skip("MatchDG PDFs not downloaded")
    repo, sha, snap = S.repo_and_snapshot(paths, cfg)
    settings, diffs = S.load_settings(paths, "matchdg")
    tables = {t["target"]: t for t in load_claims(paths, "matchdg")["tables"]}
    return paths, cfg, docs, repo, sha, snap, settings, diffs, tables


def test_prompts_hit_the_cache_and_checks_are_the_same(setup):
    paths, cfg, docs, repo, sha, snap, settings, diffs, tables = setup
    cache = Cache(paths.root / ".cache" / "llm")
    assert settings["repo"]["commit"] == sha
    for rec, drec in zip(settings["tables"], diffs["tables"]):
        table = tables[rec["target"]]
        runs = {}
        for name, r in rec["runs"].items():
            side, run = name.split("_run")
            req = (S.paper_request(cfg, table, docs, int(run)) if side == "paper"
                   else S.code_request(cfg, table, repo, sha, snap, int(run)))
            assert req.key == r["call"]["key"], name
            hit = cache.get(req.agent, req.key)
            assert hit is not None, name
            again = S.check_answer(side, hit["response"]["output"], snap=snap, docs=docs)
            assert json.loads(json.dumps(again["settings"])) == r["settings"], name
            assert again["evidence"] == r["evidence"], name
            runs[name] = again
        d = S.diff_pairings(runs)
        assert json.loads(json.dumps(d, default=str)) == {k: drec[k] for k in d}, rec["target"]
