"""Integration item 5: paper text sent to an agent stays under 40 KB per request and is never the whole PDF text:
code picks the relevant sections (abstract, setup, results tables) and drops references and related work."""
import pytest

from lab.agents import paper, runtime


def synthetic_paper() -> str:
    filler = "This paragraph discusses general motivation and history without any specifics at all.\n" * 120
    refs = "[12] A. Author. Some cited work. In Proceedings of a conference, 2012.\n" * 300
    return paper.render([
        "Distilling Things\nAbstract\nWe distill a large net into a small one and get 74 test errors.\n"
        "1\nIntroduction\n" + filler,
        "2\nRelated Work\n" + filler.replace("motivation", "prior art"),
        "3\nExperiments on MNIST\nWe trained a net with two hidden layers of 1200 units on 60,000 training cases. "
        "It achieved 67 test errors; a small net with 800 units achieved 146 test errors. Temperature 20, "
        "dropout, learning rate and batch size as in Table 1.\nTable 1: test errors 67 146 74\n",
        "4\nConclusion\nDistillation works.\nAcknowledgments\nWe thank people.\nReferences\n" + refs,
    ])


def test_selection_keeps_abstract_and_experiments_and_drops_references_and_related_work():
    text = synthetic_paper()
    sel, report = paper.select_sections(text, budget=6_000)
    assert "74 test errors" in sel and "60,000 training cases" in sel and "Table 1" in sel
    assert "Some cited work" not in sel and "prior art" not in sel
    assert len(sel.encode("utf-8")) <= 6_000
    assert "--- page 3 ---" in sel  # page markers stay, so quotes can be cited by page
    assert {"References", "2 Related Work"} <= set(report["dropped"])
    assert report["sent_bytes"] < report["total_bytes"]


def test_selection_never_sends_the_whole_text_even_when_it_would_fit():
    text = synthetic_paper()
    sel, _ = paper.select_sections(text, budget=10_000_000)
    assert len(sel) < len(text) and "Some cited work" not in sel


def test_sections_find_numbered_headings_split_across_lines():
    titles = [s["title"] for s in paper.sections(synthetic_paper())]
    assert titles[:6] == ["(front)", "Abstract", "1 Introduction", "2 Related Work", "3 Experiments on MNIST",
                          "4 Conclusion"]


def test_extract_refuses_a_request_over_the_limit():
    class NoCall:
        def call(self, *a, **k):
            raise AssertionError("the LLM must not be called")
    with pytest.raises(ValueError, match="40"):
        paper.check_request_size("x" * 41_000)


def test_runtime_prompt_is_trimmed_under_the_request_limit():
    big = "y" * 30_000
    transcript = [{"step": i, "action": "read_file", "args": {"path": "a"}, "observation": big} for i in range(1, 4)]
    prompt = runtime.step_prompt("goal", transcript)
    assert len(prompt.encode("utf-8")) <= runtime.MAX_PROMPT_BYTES
    assert "[cut]" in prompt


def test_claims_are_read_in_parts_and_merged_without_duplicates():
    """Live run: one claims answer for the whole excerpt overran the gateway's 4000-token output cap; the excerpt is
    read in parts of at most PART_BYTES, one compact claims call each, merged and de-duplicated by code."""
    body = ("We trained the network for many epochs and measured the test error on the held-out set with care. " * 30)
    text = paper.render([f"Abstract\nA result of 74 test errors.\n3\nExperiments on MNIST\n{body}\nTable 1: 67 errors",
                         f"4\nResults on speech\n{body}\nTable 2: 58.9% accuracy",
                         f"5\nAblations\n{body}\nTable 3: 61.1% accuracy"])
    calls = []

    class FakeLLM:
        def call(self, req, **kw):
            calls.append(req)
            if "settings" in req.schema["properties"]:
                out = {"settings": [{"key": "epochs", "applies_to": "all", "value": None, "quote": None, "page": None}]}
            else:  # every part also reports the abstract's claim: the duplicates must merge
                out = {"claims": [{"quote": "A result of 74 test errors.", "page": 1, "value": 74, "metric": "test errors",
                                   "unit": "errors", "direction": "lower_is_better", "whose": "method",
                                   "table_or_section": "Abstract", "model": "net"},
                                  {"quote": f"Table {len(calls)}", "page": len(calls), "value": len(calls),
                                   "metric": "x", "unit": "x", "direction": "lower_is_better", "whose": "method",
                                   "table_or_section": "t", "model": f"m{len(calls)}"}]}
            return type("R", (), {"output": out, "tokens_in": 10, "tokens_out": 5, "model": "m", "mode": "live",
                                  "key": "k"})()

    out = paper.extract(text, llm=FakeLLM(), agent={"name": "reader", "role_prompt": "x"})
    claim_calls = [r for r in calls if "claims" in r.schema["properties"]]
    assert len(claim_calls) >= 2 and len(calls) == len(claim_calls) + 1  # parts, then one settings call
    assert all(len(r.prompt.encode("utf-8")) < len(text.encode("utf-8")) for r in claim_calls)
    assert all("at most 20 words" in r.prompt and "page" in r.prompt for r in claim_calls)
    values = [c["value"] for c in out["claims"]]
    assert values.count(74) == 1 and len(values) == 1 + len(claim_calls)
    assert [c["id"] for c in out["claims"]] == [f"c{i}" for i in range(1, len(values) + 1)]
    assert out["tokens"] == 15 * len(calls)
