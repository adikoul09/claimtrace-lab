# Extraction schema (shared by the paper parser and the repo analyzer)

Both sides describe ONE experiment in the same JSON shape so a plain script can diff them.
Use `null` when the source says nothing about a setting. Never guess a value the source does not give.
Every non-null value needs evidence: a verbatim quote (paper) or `file:line` plus the code line (repo).

```json
{
  "experiment": "short name of the experiment",
  "settings": {
    "data.source_domains":            {"value": [..], "evidence": ".."},
    "data.target_domains":            {"value": [..], "evidence": ".."},
    "data.domains_data_available":    {"value": [..], "evidence": ".."},
    "data.train_samples_per_domain":  {"value": 0, "evidence": ".."},
    "data.val_samples_per_domain":    {"value": 0, "evidence": ".."},
    "data.generation_params":         {"value": {"name": "value"}, "evidence": ".."},
    "model.architecture":             {"value": "..", "evidence": ".."},
    "optim.name":                     {"value": "sgd | adam | ..", "evidence": ".."},
    "optim.momentum":                 {"value": 0.0, "evidence": ".."},
    "optim.nesterov":                 {"value": false, "evidence": ".."},
    "optim.lr":                       {"value": 0.0, "evidence": ".."},
    "optim.lr_schedule":              {"value": "constant | step(..) | ..", "evidence": ".."},
    "optim.weight_decay":             {"value": 0.0, "evidence": ".."},
    "train.batch_size":               {"value": 0, "evidence": ".."},
    "train.epochs":                   {"value": 0, "evidence": ".."},
    "train.model_selection":          {"value": "best_val_accuracy | min_val_loss | min_val_objective | last_epoch | test_domain_validation | other: ..", "evidence": ".."},
    "loss.terms":                     {"value": [{"name": "..", "weight": 0.0, "weight_schedule": "constant | linear_ramp_from_0 | .."}], "evidence": ".."},
    "eval.n_seeds":                   {"value": 0, "evidence": ".."},
    "eval.metric":                    {"value": "..", "evidence": ".."},
    "eval.aggregation":               {"value": "mean_sd_over_seeds | best_of_n | single_run | ..", "evidence": ".."}
  },
  "notes": ["anything that matters for reproducing the experiment but does not fit a key above"]
}
```

Notes on keys:
- `data.domains_data_available`: the domains for which data actually exists or is produced by the provided scripts (repo side), or is stated to be used (paper side).
- `optim.momentum`: 0.0 means plain SGD with no momentum. `null` means the source does not say.
- `loss.terms`: one entry per term in the training objective (e.g. cross-entropy, a penalty), with its weight and how the weight changes over training.
- Methods: where a setting differs by method (e.g. a penalty weight), give it per method inside `value` as `{"method": value}`.
