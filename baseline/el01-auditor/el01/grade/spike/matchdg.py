"""MatchDG findings (spec F1-F6) and the branches that test them, as data. Copied from the frozen verdicts_v2.py, where
they are module constants; rules 2.1 takes them as arguments. tests/test_rules_equivalence.py checks the two copies
and golden/findings.json agree."""

FINDINGS = {
    "F1": {"what": "target domain p = 1.0 never generated", "kind": "code omission"},
    "F2": {"what": "model selection: validation loss (paper) vs accuracy (code)", "kind": "difference"},
    "F3": {"what": "optimizer: plain SGD (paper) vs momentum 0.9 + Nesterov (code)", "kind": "paper omission"},
    "F4": {"what": "matching weight ramps from about 0 (code), no schedule in paper", "kind": "paper omission"},
    "F5": {"what": "DANN/CDANN learning rate 0.1 (paper) vs 0.01 (code)", "kind": "difference"},
    "F6": {"what": "hyperparameters ranked by target accuracy (code) vs source validation (paper)", "kind": "difference"},
}
BRANCH_FINDINGS = {
    "naive_target_0.9_3m": ["F1"], "h_select_valloss": ["F2"], "h_select_valloss_total": ["F2"],
    "h_omission_plain_sgd": ["F3"], "h_plain_sgd_1000ep": ["F3"], "h_combined": ["F2", "F3"],
    "h_omission_constant_penalty": ["F4"], "h_dann_lr": ["F5"],
}
SHORT = {"naive_target_0.9_3m": "h3", "h_select_valloss": "h1", "h_select_valloss_total": "h1b",
         "h_omission_plain_sgd": "h2", "h_plain_sgd_1000ep": "h2 at 1000 epochs", "h_combined": "h1+h2",
         "h_omission_constant_penalty": "h4", "h_dann_lr": "h6"}
