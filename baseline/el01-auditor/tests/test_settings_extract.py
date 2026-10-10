"""Settings extraction: answer schemas, evidence checks (code citations, paper quotes) and agreement between runs."""
from pathlib import Path

from el01.extract import settings as S
from el01.ingest.pdf_text import Doc


def snap(tmp_path: Path) -> Path:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text("\n".join([
        "import torch",                                  # 1
        "def make(x):",                                  # 2
        "    y = crop(x)",                               # 3
        "    z = rotate(y, 15)",                         # 4
        "    return z",                                  # 5
    ]) + "\n")
    (tmp_path / ".el01-snapshot").write_text("sha\n")
    return tmp_path


def test_answer_schema_covers_every_key():
    for side in ("paper", "code"):
        s = S.answer_schema(side)
        assert s["properties"]["settings"]["required"] == S.KEYS and len(S.KEYS) == 25
        assert set(S.V2_KEYS) == {"data.preprocessing.resize", "data.preprocessing.normalization", "data.augmentation",
                                  "data.domain_transform", "train.model_selection_data"}
    assert "commands" in S.answer_schema("code")["properties"]
    assert "commands" not in S.answer_schema("paper")["properties"]


def test_code_citations(tmp_path):
    root = snap(tmp_path)
    ok = S.check_code_item(root, {"file": "repo/pkg/a.py", "lines": "3-4", "code": "y = crop(x)\n  z = rotate(y, 15)"})
    assert ok["ok"] and ok["file"] == "pkg/a.py" and ok["lines"] == [3, 4]
    assert S.check_code_item(root, {"file": "pkg/a.py", "lines": "2-5", "code": "def make(x): ... return z"})["ok"]
    moved = S.check_code_item(root, {"file": "pkg/a.py", "lines": "1", "code": "z = rotate(y, 15)"})
    assert not moved["ok"] and moved["near"] == [4, 4]
    assert S.check_code_item(root, {"file": "pkg/b.py", "lines": "1", "code": "x"})["problem"] == \
        "no such file in the snapshot"
    assert S.check_code_item(root, {"file": "../etc/passwd", "lines": "1", "code": "x"})["ok"] is False
    assert S.check_code_item(root, {"file": ".el01-snapshot", "lines": "1", "code": "sha"})["ok"] is False
    assert "outside" in S.check_code_item(root, {"file": "pkg/a.py", "lines": "9", "code": "x"})["problem"]
    assert S.check_code_item(root, {"file": "pkg/a.py", "lines": "three", "code": "x"})["ok"] is False
    multi = S.check_code_item(root, {"file": "pkg/a.py", "lines": "1, 4-5", "code": "import torch ... return z"})
    assert multi["ok"] and multi["ranges"] == [[1, 1], [4, 5]] and multi["lines"] == [1, 5]
    # the pieces must be on the cited ranges, in order: line 3 is not cited
    assert not S.check_code_item(root, {"file": "pkg/a.py", "lines": "1, 4-5", "code": "y = crop(x)"})["ok"]
    assert not S.check_code_item(root, {"file": "pkg/a.py", "lines": "4-5, 1", "code": "import torch ... return z"})["ok"]


def test_paper_quotes_and_statuses(tmp_path):
    docs = {"main": Doc("main", tmp_path / "m.pdf", tmp_path / "m.txt", "0" * 64,
                        {1: "We train with SGD, batch size 128.", 2: "No augmentation is used."})}
    assert S.check_paper_item(docs, {"doc": "main", "page": 1, "quote": "with SGD, batch"})["ok"]
    moved = S.check_paper_item(docs, {"doc": "main", "page": 1, "quote": "No augmentation is used."})
    assert moved["ok"] and moved["page"] == 2 and moved["note"]
    assert not S.check_paper_item(docs, {"doc": "main", "page": 1, "quote": "Adam"})["ok"]
    ans = {"settings": {"optim.name": {"value": "sgd", "evidence": [{"doc": "main", "page": 1, "quote": "SGD"},
                                                                    {"doc": "main", "page": 1, "quote": "Adam"}]},
                        "train.batch_size": {"value": 128, "evidence": []},
                        "data.augmentation": {"value": [], "evidence": [
                            {"doc": "main", "page": 2, "quote": "No augmentation is used."}]}}}
    c = S.check_answer("paper", ans, docs=docs)
    st = {k: v["status"] for k, v in c["settings"].items()}
    assert st["optim.name"] == "partly" and st["train.batch_size"] == "no evidence"
    assert st["data.augmentation"] == "verified" and st["optim.lr"] == "null"
    assert c["evidence"]["items"] == 3 and c["evidence"]["items_ok"] == 2


def test_agreement_ignores_wording():
    def run(**kv):
        return {k: {"value": kv.get(k.replace(".", "__"))} for k in S.KEYS}
    a = run(optim__lr={"erm": 0.1, "dann": 0.01}, train__model_selection="best_val_accuracy: argmax of val acc",
            model__architecture="LeNet-5", data__augmentation=[{"ops": ["Random Crop"], "methods": ["MatchDG"],
                                                               "relative_to_domain_transform": "after",
                                                               "applies_to": []}])
    b = run(optim__lr={"ERM": "0.10", "DANN": 0.01}, train__model_selection="best_val_accuracy",
            model__architecture="lenet 5", data__augmentation=[{"ops": ["random_crop"], "methods": ["matchdg_ctr"],
                                                               "relative_to_domain_transform": "after",
                                                               "applies_to": []}],
            optim__momentum=0.9)
    ag = S.agreement(a, b)["per_key"]
    assert ag["optim.lr"] == "same" and ag["train.model_selection"] == "same"
    assert ag["model.architecture"] == "same" and ag["data.augmentation"] == "same"
    assert ag["optim.momentum"] == "one_null" and ag["optim.name"] == "both_null"
    b["optim.lr"]["value"] = {"erm": 0.1, "dann": 0.1}
    assert S.agreement(a, b)["per_key"]["optim.lr"] == "differ"


def test_table_index(tmp_path):
    docs = {"supplement": Doc("supplement", tmp_path / "s.pdf", tmp_path / "s.txt", "0" * 64,
                              {9: "text\nTable 8. Hyper parameter selection details. More.\nrows",
                               10: "Table 9: Phase 1 training details for all\nthe datasets. Next sentence."})}
    assert S.table_index(docs).splitlines() == [
        "- Table 8 (supplement, page 9): Hyper parameter selection details",
        "- Table 9 (supplement, page 10): Phase 1 training details for all the datasets"]
