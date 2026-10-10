"""The extractor prompts must not lead the agents to the known findings (Builder, 2026-10-04): no prompt we write names
`flip`, `data_gen_mnist`, `match_eval` or a finding number (F1, F7, ...). Only the acceptance checker
(el01/diff/spike.py) names them. Checked: both templates, the schema text and answer schemas, the prompts rendered for
MatchDG today, the saved prompts under audits/matchdg/settings/ and every recorded settings call in .cache/llm/.
The paper's own text is input, not instruction, and is left out (it describes flips for other datasets)."""
import json
import re

import pytest

from el01.config import AuditConfig, Paths
from el01.extract import settings as S

WORDS = re.compile(r"flip|data_gen_mnist|match_eval", re.I)
FNUM = re.compile(r"\bF\d+\b")


def leaks(text: str) -> list[str]:
    return sorted(set(WORDS.findall(text)) | set(FNUM.findall(text)))


def test_the_check_itself_catches_leaks():
    assert leaks("trace the horizontal Flip in data_gen_mnist.py (F7)") == ["F7", "Flip", "data_gen_mnist"]
    assert leaks("snake_case names; 0.0 means plain SGD; Table 11; lr 1e-4") == []


def test_templates_and_schema():
    for side in ("paper", "code"):
        assert leaks((S.LLM_DIR / "prompts" / f"{S.PROMPTS[side]}.md").read_text()) == [], side
        assert leaks(json.dumps(S.answer_schema(side))) == [], side
    assert leaks((S.EXTRACT_DIR / "schema_v2.json").read_text()) == []
    assert leaks(S.keys_block("paper")) == [] and leaks(S.keys_block("code")) == []


def test_rendered_saved_and_recorded_prompts():
    paths = Paths.make()
    cfg = AuditConfig.for_audit(paths, "matchdg")
    try:
        from el01.extract.claims import load_claims, load_docs
        tables = load_claims(paths, "matchdg")["tables"]
        docs = load_docs(paths, cfg)
    except FileNotFoundError:
        pytest.skip("no claims.json or no PDFs")
    for t in tables:
        assert leaks(S.code_prompt(cfg, t)) == [], t["target"]
        # the table index (captions found by code) stays in; the documents block is the paper's own text
        assert leaks(S.instructions(S.paper_prompt(cfg, t, docs))) == [], t["target"]
        assert leaks(S.instructions(S.paper_prompt(cfg, t, docs, "=== document: main ===\nflip F7\n"
                                                                 "=== end of document: main ===\n"))) == []
    saved = sorted((paths.audit_dir("matchdg") / "settings").rglob("*.prompt.md"))
    for p in saved:
        assert leaks(S.instructions(p.read_text())) == [], p.name
    for agent in S.AGENTS.values():
        for p in sorted((paths.root / ".cache" / "llm" / agent).glob("*.json")):
            rec = json.loads(p.read_text())
            if "Schema keys (`value` shape" not in rec["request"]["prompt"]:
                continue   # the paper extractor's claim-card calls share the agent name
            assert leaks(S.instructions(rec["request"]["prompt"])) == [], p.name
            assert leaks(json.dumps(rec["request"]["schema"])) == [], p.name
