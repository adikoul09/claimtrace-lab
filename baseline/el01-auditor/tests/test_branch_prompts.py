"""The branch writer is not led to the spike's branches: its prompts (templates and every rendered MatchDG prompt)
name no F-number, audit branch, patch file or spike branch label, and F2's prompt does not name either reading."""
import json
import re
from pathlib import Path

from el01.branch import writer as W
from el01.config import AuditConfig, Paths
from el01.extract.claims import load_claims

FORBIDDEN = [r"\bF\d\b", r"audit/", r"hypotheses", r"valloss", r"\bh\d+b?\b", r"spike", r"bundle", r"golden"]


def _bad(text):
    return [p for p in FORBIDDEN if re.search(p, text, re.I)]


def test_templates_clean():
    for name in ("branch_writer", "branch_harness"):
        assert _bad((W.LLM_DIR / "prompts" / f"{name}.md").read_text()) == [], name


def test_rendered_prompts_clean():
    p = Paths.make()
    cfg = AuditConfig.for_audit(p, "matchdg")
    claims = {t["target"]: t for t in load_claims(p, "matchdg")["tables"]}
    links = json.loads((p.audit_dir("matchdg") / "links.json").read_text())
    for f in W.load_findings(p, cfg, skip=("F1",)):
        pr = W.writer_prompt(cfg, f, claims[f.table], links)
        assert _bad(pr) == [], f.id
        if f.id == "F2":
            assert not re.search(r"cross.?entropy|objective", pr, re.I)


def test_recorded_writer_prompts_clean():
    root = Path(__file__).resolve().parent.parent
    for rec in sorted((root / ".cache" / "llm" / "branch_writer").glob("*.json")):
        assert _bad(json.loads(rec.read_text())["request"]["prompt"]) == [], rec.name
