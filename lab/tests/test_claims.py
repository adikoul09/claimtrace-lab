"""T05: paper text, verbatim quote checks, claim and setting checks, Reader extraction (offline). The page texts are
PyMuPDF's own output for arXiv 1503.02531, section 3, with its line breaks and the "ﬁ" ligature."""
import json

import pytest

from lab import llm as llm_mod
from lab.agents import paper
from lab.llm import LLM
from lab.tests.test_runtime import FakeDB

PAGE3 = ("3\nPreliminary experiments on MNIST\nTo see how well distillation works, we trained a single large neural "
         "net with two hidden layers\nof 1200 rectiﬁed linear hidden units on all 60,000 training cases. The net was "
         "strongly regularized\nusing dropout and weight-constraints as described in [5]. Dropout can be viewed as a "
         "way of training\nan exponentially large ensemble of models that share weights. In addition, the input "
         "images were\n3\n")
PAGE4 = ("jittered by up to two pixels in any direction. This net achieved 67 test errors whereas a smaller\nnet with "
         "two hidden layers of 800 rectiﬁed linear hidden units and no regularization achieved 146\nerrors. But if the "
         "smaller net was regularized solely by adding the additional task of matching the soft\ntargets produced by "
         "the large net at a temperature of 20, it achieved 74 test errors. This shows that\n")
PAGES = {3: PAGE3, 4: PAGE4}


def claim(value, quote, page=4, **kw):
    return {"quote": quote, "page": page, "table_or_section": "3 Preliminary experiments on MNIST",
            "metric": "test errors", "value": value, "unit": "errors", "direction": "lower_is_better",
            "whose": "baseline", **kw}


# ---- page text and quotes -----------------------------------------------------------------------------------------

def test_render_and_parse_pages_round_trip():
    text = paper.render(["first page\n", "second page"])
    assert paper.parse_pages(text) == {1: "first page", 2: "second page"}


def test_locate_ignores_line_breaks_and_ligatures():
    hit = paper.locate(PAGE3, "two hidden layers of 1200 rectified linear hidden units")
    assert hit == "two hidden layers\nof 1200 rectiﬁed linear hidden units".replace("\n", " ")


def test_locate_rejects_a_paraphrase():
    assert paper.locate(PAGE4, "The large net got 67 errors on the test set") is None


def test_numbers_reads_thousands_separators_and_decimals():
    assert paper.numbers("all 60,000 training cases, 98.6% correct, layer [5], 146\nerrors") == [60000, 98.6, 5, 146]


# ---- claims -------------------------------------------------------------------------------------------------------

def test_claim_with_value_in_its_quote_is_valid():
    c = paper.check_claim(claim(67, "This net achieved 67 test errors"), PAGES)
    assert c["valid"] and c["checks"] == {"quote_found": True, "value_in_quote": True}
    assert c["page"] == 4 and c["quote"] == "This net achieved 67 test errors"


def test_claim_quote_across_a_line_break_is_found():
    c = paper.check_claim(claim(146, "no regularization achieved 146 errors"), PAGES)
    assert c["valid"]


def test_claim_whose_value_is_not_in_the_quote_is_invalid():
    c = paper.check_claim(claim(76, "This net achieved 67 test errors"), PAGES)
    assert not c["valid"] and c["checks"]["value_in_quote"] is False
    assert "76" in c["problems"][0]


def test_claim_quote_not_in_the_paper_is_invalid():
    c = paper.check_claim(claim(67, "The teacher made 67 errors"), PAGES)
    assert not c["valid"] and c["checks"]["quote_found"] is False


def test_claim_on_the_wrong_page_is_moved_to_where_code_found_it():
    c = paper.check_claim(claim(74, "at a temperature of 20, it achieved 74 test errors", page=3), PAGES)
    assert c["valid"] and c["page"] == 4
    assert "page 3" in c["note"]


def test_claims_get_ids_from_code():
    out = paper.check_claims([claim(67, "This net achieved 67 test errors"),
                              claim(74, "it achieved 74 test errors")], PAGES)
    assert [c["id"] for c in out] == ["c1", "c2"]


# ---- settings -----------------------------------------------------------------------------------------------------

def test_setting_numbers_must_appear_in_its_quote():
    ok = paper.check_setting({"key": "hidden_units", "applies_to": "teacher", "value": "2 x 1200",
                              "quote": "two hidden layers of 1200 rectified linear hidden units", "page": 3}, PAGES)
    bad = paper.check_setting({"key": "hidden_units", "applies_to": "teacher", "value": "2 x 1500",
                               "quote": "two hidden layers of 1200 rectified linear hidden units", "page": 3}, PAGES)
    assert ok["valid"]
    assert not bad["valid"] and "1500" in bad["problems"][0]


def test_setting_number_words_count_as_numbers():
    s = paper.check_setting({"key": "augmentation", "applies_to": "teacher", "value": "jitter up to 2 pixels",
                             "quote": "jittered by up to two pixels in any direction", "page": 4}, PAGES)
    assert s["valid"]


def test_quote_across_a_page_break_is_found_on_its_first_page():
    # Page 3 ends "...the input images were\n3\n" (3 is the page number); the sentence ends on page 4.
    s = paper.check_setting({"key": "augmentation", "applies_to": "teacher", "value": "jitter up to 2 pixels",
                             "quote": "In addition, the input images were jittered by up to two pixels in any "
                                      "direction.", "page": 3}, PAGES)
    assert s["valid"] and s["page"] == 3
    assert s["quote"] == "In addition, the input images were jittered by up to two pixels in any direction."
    assert "pages 3-4" in s["note"]


def test_unstated_setting_is_valid_with_no_quote():
    s = paper.check_setting({"key": "epochs", "applies_to": "all", "value": None, "quote": None, "page": None}, PAGES)
    assert s["valid"] and s["checks"] == {"stated": False}


def test_stated_setting_needs_a_quote():
    s = paper.check_setting({"key": "optimizer", "applies_to": "all", "value": "sgd", "quote": None, "page": None},
                            PAGES)
    assert not s["valid"]


# ---- reference comparison (B0 results.json "paper" block) ---------------------------------------------------------

REF = {"teacher_test_errors": 67, "student_hard_test_errors": 146, "student_distilled_test_errors": 74,
       "temperature": 20, "arxiv": "1503.02531", "section": "3"}


def test_reference_values_are_matched_to_valid_claims():
    claims = paper.check_claims([claim(67, "This net achieved 67 test errors"),
                                 claim(146, "no regularization achieved 146 errors"),
                                 claim(74, "it achieved 74 test errors")], PAGES)
    cmp = paper.compare_with_reference(claims, REF)
    assert cmp == {"teacher_test_errors": {"expected": 67, "claim_id": "c1"},
                   "student_hard_test_errors": {"expected": 146, "claim_id": "c2"},
                   "student_distilled_test_errors": {"expected": 74, "claim_id": "c3"}}


def test_reference_value_without_a_valid_claim_is_reported_missing():
    claims = paper.check_claims([claim(67, "This net achieved 67 test errors"),
                                 claim(146, "The small net made 146 errors")], PAGES)  # not a verbatim quote
    cmp = paper.compare_with_reference(claims, REF)
    assert cmp["student_hard_test_errors"]["claim_id"] is None
    assert cmp["student_distilled_test_errors"]["claim_id"] is None


# ---- Reader extraction --------------------------------------------------------------------------------------------

def test_extract_checks_what_the_model_returns(tmp_path, monkeypatch):
    answer = {"claims": [claim(67, "This net achieved 67 test errors", whose="oracle"),
                         claim(74, "it achieved 74 test errors", whose="method")],
              "settings": [{"key": "temperature", "applies_to": "distilled", "value": "20",
                            "quote": "at a temperature of 20", "page": 4},
                           {"key": "epochs", "applies_to": "all", "value": None, "quote": None, "page": None}]}
    seen = []

    def provider(req, model):
        part = list(req.schema["properties"])  # one part per call: claims, then settings
        seen.append({"prompt": req.prompt, "part": part, "max_output": req.max_output})
        out = {p: answer[p] for p in part}
        return {"output": out, "text": json.dumps(out), "tokens_in": 9000, "tokens_out": 800, "models": [model]}
    monkeypatch.setitem(llm_mod.PROVIDERS, "fake", provider)
    db = FakeDB()
    client = LLM(mode="live", provider="fake", cache_dir=tmp_path, db=db, models={"smart": "fake-pro"})
    agent = {"id": "ag-reader", "name": "reader-v1", "role_prompt": "You are the Reader."}

    out = paper.extract(paper.render([PAGE3, PAGE4], first=3), llm=client, agent=agent)

    # Live run: one call for claims and settings ran out of the gateway's output cap (4000 tokens, reasoning
    # included) before answering; each part now gets its own call at the cap.
    assert [s["part"] for s in seen] == [["claims"], ["settings"]]
    assert all(s["max_output"] == paper.READER_MAX_OUTPUT == 4000 for s in seen)
    assert all("--- page 4 ---" in s["prompt"] for s in seen)
    assert [c["valid"] for c in out["claims"]] == [True, True]
    assert [s["valid"] for s in out["settings"]] == [True, True]
    assert out["tokens"] == 2 * 9800
    assert db.rows["llm_calls"][0]["agent_id"] == "ag-reader"


def test_reader_system_is_code_first_and_settings_in_the_claims_answer_skip_the_second_call(tmp_path, monkeypatch):
    """Live run: a refined role prompt asked for file writes (no tools here) and the model answered empty; another
    returned claims and settings together, then the settings call overran the 4000-token cap."""
    both = {"claims": [claim(67, "This net achieved 67 test errors", whose="oracle")],
            "settings": [{"key": "temperature", "applies_to": "distilled", "value": "20",
                          "quote": "at a temperature of 20", "page": 4}]}
    calls = []

    def provider(req, model):
        calls.append(req)
        out = answers.pop(0)
        return {"output": out, "text": json.dumps(out), "tokens_in": 100, "tokens_out": 50, "models": [model]}
    monkeypatch.setitem(llm_mod.PROVIDERS, "fake", provider)
    client = LLM(mode="live", provider="fake", cache_dir=tmp_path, db=FakeDB(), models={"smart": "fake-pro"})
    agent = {"id": "ag", "name": "reader-v9", "role_prompt": "Write paper_summary.json with your findings."}
    text = paper.render([PAGE3, PAGE4], first=3)

    answers = [both]  # the claims answer already carries settings: one call only
    out = paper.extract(text, llm=client, agent=agent)
    assert len(calls) == 1 and [s["valid"] for s in out["settings"]] == [True]
    system = calls[0].system
    assert system.startswith(paper.READER_SYSTEM) and "no tools" in system
    assert system.index("Write paper_summary.json") > system.index("Additional guidance")

    calls.clear()
    answers = [{"claims": both["claims"]}, {"settings": both["settings"]}]  # no settings: a compact second call
    out = paper.extract(text, llm=client, agent=agent, arxiv_id="x2")
    assert len(calls) == 2 and "compact" in calls[1].prompt and list(calls[1].schema["properties"]) == ["settings"]
    assert out["tokens"] == 300
