"""Replay at zero quota: the prompts `el01 claims` and `el01 link` build today hit recorded responses, and the
committed links.json is what code makes of those recorded answers."""
import json

import pytest

from el01.config import AuditConfig, Paths
from el01.llm.cache import Cache


@pytest.fixture(scope="module")
def setup():
    paths = Paths.make()
    cfg = AuditConfig.for_audit(paths, "matchdg")
    if not (paths.audit_dir("matchdg") / "links.json").exists():
        pytest.skip("no links.json yet")
    from el01.extract.claims import load_docs
    try:
        docs = load_docs(paths, cfg)
    except FileNotFoundError:
        pytest.skip("MatchDG PDFs not downloaded")
    return paths, cfg, docs


def test_claims_prompts_hit_the_cache(setup):
    from el01.extract.claims import AGENT, MAX_TURNS, SCHEMA, build_prompt
    from el01.llm.backend import Request
    paths, cfg, docs = setup
    cache = Cache(paths.root / ".cache" / "llm")
    for t in cfg.targets:
        req = Request(agent=AGENT, prompt=build_prompt(cfg, t.table, docs), schema=SCHEMA, model=cfg.llm.model,
                      inputs={f"pdf:{n}": d.sha256 for n, d in docs.items()}, tools=(), max_turns=MAX_TURNS)
        assert cache.get(AGENT, req.key) is not None, t.table


def test_linker_prompts_hit_the_cache_and_answers_check_the_same(setup):
    from el01.extract.claims import load_claims
    from el01.ingest.repo import tree_id
    from el01.link import argspec, linker
    from el01.llm.backend import AGENT_TOOLS, Request
    paths, cfg, docs = setup
    try:
        ctx = linker.make_ctx(paths, cfg, None, lambda s: None)
    except linker.LinkError as e:
        pytest.skip(str(e))
    cache = Cache(paths.root / ".cache" / "llm")
    readme, scripts = linker.repo_texts(ctx.snap)
    help_specs = {s: argspec.probe(ctx.py, ctx.wt, s)
                  for s in linker.invoked_scripts([readme] + [t for _, t in scripts], ctx.wt)}
    committed = json.loads((paths.audit_dir("matchdg") / "links.json").read_text())
    for table, rec in zip(load_claims(paths, "matchdg")["tables"], committed["tables"]):
        def request(prompt):
            return Request(agent=linker.AGENT, prompt=prompt, schema=linker.SCHEMA, model=cfg.llm.model,
                           inputs={"repo_tree": tree_id(ctx.repo, ctx.base)}, tools=AGENT_TOOLS, repo_copy=ctx.snap,
                           max_turns=linker.MAX_TURNS)
        first = request(linker.build_prompt(ctx, table, help_specs, docs))       # rebuilt from scratch
        assert first.key == rec["calls"][0]["key"] and cache.get(linker.AGENT, first.key) is not None, table["target"]
        for call in rec["calls"][1:]:   # answers to code's findings: their prompts hold dry-run results
            saved = (paths.audit_dir("matchdg") / call["prompt"]).read_text()
            assert saved.startswith(first.prompt)
            req = request(saved)
            assert req.key == call["key"] and cache.get(linker.AGENT, req.key) is not None
        last = cache.get(linker.AGENT, rec["calls"][-1]["key"])
        again = linker.check_answer(ctx, table, last["response"]["output"])
        assert [(c["claim_ids"], c["status"], [s["argv"] for s in c["steps"]], c["parser"]) for c in again["cells"]] == \
               [(c["claim_ids"], c["status"], [s["argv"] for s in c["steps"]], c["parser"]) for c in rec["cells"]]
