You are the repository-analysis step of an automated ML reproducibility pipeline. Work only from the code, by reading
it. The repository, exactly as shipped at the audited commit and without its git history, is in the directory `./repo`
(relative to your working directory). Read it with Read, Grep and Glob.

Repository: https://github.com/microsoft/robustdg
Experiment: the one the associated paper reports in Table 1, whose caption reads: "Table 1. Slab Dataset: Source domains with noisy linear compo- nent with probability 0.0 and 0.1, target domain with noise 1.0."
Its columns: Source 1, Source 2, Target.
Its rows that the paper's own runs produce (use these names for methods): ERM, DANN, MMD, CORAL, RandMatch, CDANN, C-MMD, C-CORAL, PerfMatch.

Steps:
1. Find the command(s) the repository provides to reproduce this experiment (reproduce scripts, README, docs,
   notebooks), including the steps that prepare its data.
2. Trace what those commands actually do, statically: argument values and defaults; which data the data-preparation
   code produces versus which domains the commands ask for; how each domain is made from the base data;
   preprocessing (resizing, normalization); any random transforms applied to the data, in which order relative to the
   domain transform, and every split and use that reads the transformed data (training, validation, model selection,
   evaluation), per method and training phase; the model; how the optimizer is constructed (type, momentum, nesterov,
   lr, weight decay, any schedule); the training loop and every loss term with its weight and how that weight changes
   across epochs; how the reported epoch or checkpoint is chosen and which data that choice reads, in every training
   phase; how hyperparameters are chosen, if the repository has tuning scripts, and which data that choice reads; the
   number of seeds and how seeds are set; the metric, and how results are aggregated across seeds, including what
   spread is printed.
3. Fill the schema below for this experiment from the code only.

Rules:
- Read only files under ./repo. Do not use the web and do not look for the paper. Do not run anything.
- Evidence for each non-null value: one or more items {file, lines, code}: `file` is the path relative to the
  repository root (without `repo/`), `lines` the line or line range as the Read tool numbers them ("42" or "34-35"),
  and `code` the code on those lines, copied verbatim (inside a range you may skip lines with "..."). Code checks
  every item against the file.
- Use null only when the code genuinely does not determine the value.
- Where a setting differs by method, give it per method inside `value` as {"<method>": value}. Where a method trains
  in phases with different settings, give them per phase: {"<method>": {"<phase>": value}}.
- `value` holds the value only, in the shape shown: no explanations, qualifiers or alternatives inside it (code
  reads every number in a value). Explanations go in `notes`, or in an entry's `note`.
- Keys marked "entries" take a list of entries: `[]` means the code has no such step for this experiment (cite where
  the data is built); give one entry per distinct case; `methods: null` means every method, `phase: null` every
  training phase. Use the enumerated values shown; put anything that does not fit in the entry's `note`.
- Report what the code does, even where it looks like a mistake, and say so in `notes`.
- `commands`: each command you traced and where the repository gives it (path:line). `experiment`: one line naming
  the experiment (dataset, model, domains). `notes`: anything that matters for reproducing this experiment but does
  not fit a key.

Schema keys (`value` shape, then what the key means):
- `data.source_domains`: [..]: the domains the model trains on
- `data.target_domains`: [..]: the domains the reported numbers are evaluated on
- `data.domains_data_available`: [..]: the domains for which data actually exists in the repository or is produced by its scripts
- `data.train_samples_per_domain`: 0: training examples per domain
- `data.val_samples_per_domain`: 0: validation examples per domain
- `data.generation_params`: {"name": value}: parameters of the data generation (synthetic data, subsets)
- `model.architecture`: "..": the model
- `optim.name`: "sgd | adam | ..": the optimizer
- `optim.momentum`: 0.0: 0.0 means plain SGD with no momentum; null means the source does not say
- `optim.nesterov`: false: Nesterov momentum
- `optim.lr`: 0.0: the learning rate
- `optim.lr_schedule`: "constant | step(..) | ..": how the learning rate changes over training
- `optim.weight_decay`: 0.0: weight decay
- `train.batch_size`: 0: batch size
- `train.epochs`: 0: number of training epochs
- `train.model_selection`: "best_val_accuracy | min_val_loss | min_val_objective | last_epoch | test_domain_validation | other: ..": how the reported epoch or checkpoint is chosen
- `loss.terms`: [{"name": "..", "weight": 0.0, "weight_schedule": "constant | linear_ramp_from_0 | .."}]: one entry per term in the training objective (e.g. cross-entropy, a penalty), with its weight and how the weight changes over training
- `eval.n_seeds`: 0: number of runs (seeds) behind each reported number
- `eval.metric`: "..": what the reported numbers measure
- `eval.aggregation`: "mean_sd_over_seeds | mean_se_over_seeds | best_of_n | single_run | ..": how the reported numbers aggregate the runs, including what the printed spread is (standard deviation or standard error); give it per reported quantity as {"<quantity>": value} where it differs
- `data.preprocessing.resize`: entries [{height, width, methods: [..], note}]: resizing of the inputs before they reach the model
- `data.preprocessing.normalization`: entries [{kind: none|mean_std|scale_0_1|other, mean: [..], std: [..], methods: [..], note}]: normalization of the inputs (e.g. subtracting a mean and dividing by a standard deviation)
- `data.augmentation`: entries [{ops: [..], relative_to_domain_transform: before|after|no_domain_transform|unknown, applies_to: [{split: train|val|test, domains: source|target|all, use: training|validation|model_selection|evaluation, methods: [..], phase}], note}]: random transforms applied to the data, on the fly or as a stored augmented copy: what they are (snake_case names, in the order applied), whether they come before or after the transform that makes each domain, and every split and use that reads the augmented data (training, validation, model selection, evaluation), per method and training phase
- `data.domain_transform`: entries [{kind: rotation|other_geometric|photometric|feature_noise|label_noise|correlation_strength|source_dataset|other, domains: [..], params, direction: counterclockwise|clockwise|not_applicable|unknown, methods: [..], note}]: how each domain is made from the base data, including the direction (sign) of a rotation. `kind` names the mechanism, not what the source calls it: rotation = inputs rotated by a per-domain angle; other_geometric = translation, scaling, shear; photometric = colour, brightness, contrast, texture or style; feature_noise = a per-domain fraction or level of an input feature is replaced or perturbed by noise; label_noise = a per-domain fraction of labels is corrupted; correlation_strength = examples are sampled so that an attribute co-occurs with the label at a per-domain rate; source_dataset = each domain is a different dataset, site or collection. Describe the details in `params`
- `train.model_selection_data`: entries [{use: checkpoint|hyperparameter_tuning, split: train|val|test|other, domains: source|target|source_and_target|unknown, version: plain|augmented|other, metric, methods: [..], phase, note}]: the data each selection step reads: the choice of the reported epoch or checkpoint (use checkpoint) and the choice of hyperparameters (use hyperparameter_tuning): which split, of which domains, and which version of it (plain or augmented), per method and training phase
