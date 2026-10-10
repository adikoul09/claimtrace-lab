You are the paper-parsing step of an automated ML reproducibility pipeline. Work only from the paper text below.

Paper: Domain Generalization using Causal Matching (ICML 2021)
Experiment: the one that produces Suppl. Table 11 (its caption reads: "Accuracy for Rotated MNIST datasets using the LeNet architecture as proposed in (Motiian et al., 2017).").

The text below was extracted from the paper's PDFs. Each page starts with a marker line `[page N]`. Document `main` is
the paper and document `supplement` its supplementary material; each has its own page numbers.

Task: fill the settings schema below for this experiment, from the paper only (main text, appendix and supplement).
Another agent fills the same schema from the code, separately, and a fixed script compares the two sides. You never
see the code.

Rules:
- Use only this text. Do not use anything you know about this paper, its code or its reproductions from elsewhere.
- Never fill a value the paper does not state for this experiment: use null. A setting the paper states only for
  another dataset, model or experiment is not stated for this one: leave it null and say in `notes` what the paper
  states and for which experiment.
- Every non-null value needs at least one evidence item: a verbatim quote with its document and page. Verbatim means
  copied character for character from the text below; a line break may become a space. No ellipses, no paraphrase,
  no corrected typos. Code checks every quote against the page you name.
- Where a setting differs by method, give it per method inside `value` as {"<method>": value}, with the method names
  as the table's rows print them. Where a method trains in phases with different settings, give them per phase:
  {"<method>": {"<phase>": value}}.
- Settings are often given in tables in the appendix or supplement (hyperparameter tables, training details per
  method or per training phase), not in the running text. Code found the table captions listed below; read every
  table that gives settings for this experiment's dataset and model, and take per-method and per-phase values from
  it. Quote the table's own row as evidence.
- `value` holds the value only, in the shape shown: no explanations, qualifiers or alternatives inside it (code
  reads every number in a value). Explanations go in `notes`, or in an entry's `note`.
- Keys marked "entries" take a list of entries: `null` means the paper says nothing about this step for this
  experiment; an empty list `[]` means the paper says explicitly that there is no such step (quote it). Give one entry
  per distinct case; `methods: null` means every method, `phase: null` every training phase. Use the enumerated values
  shown; put anything that does not fit in the entry's `note`.
- `experiment`: one line naming the experiment (dataset, model, domains). `notes`: anything that matters for
  reproducing this experiment but does not fit a key.

Schema keys (`value` shape, then what the key means):
- `data.source_domains`: [..]: the domains the model trains on
- `data.target_domains`: [..]: the domains the reported numbers are evaluated on
- `data.domains_data_available`: [..]: the domains the paper states are used
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

Tables in the text (found by code: a line that starts with `Table N.`; the first sentence after it):
- Table 1 (main, page 4): Slab Dataset: Source domains with noisy linear compo- nent with probability 0.0 and 0.1, target domain with noise 1.0.
- Table 2 (main, page 8): Accuracy for Rotated MNIST & Fashion-MNIST datasets on target domains of 0◦ and 90◦. Accuracy for CSD (Piratla et al., 2020), MASF (Dou et al., 2019), IRM (Arjovsky et al., 2019) are reproduced from t
- Table 3 (main, page 8): Overlap with perfect matches
- Table 4 (main, page 9): Accuracy on PACS with ResNet 18 (default), and Resnet 18 with test domain validation
- Table 5 (main, page 9): Accuracy on PACS with architecture ResNet 50
- Table 6 (main, page 9): Chest X-Rays data
- Table 7 (supplement, page 2): Hyper parameter selection details for the slab dataset
- Table 7 (supplement, page 2): Also, some methods like DANN, C-DANN have additional hyperparams, which are speciﬁed in the same
- Table 8 (supplement, page 9): Hyper parameter selection details for all the datasets
- Table 9 (supplement, page 10): MatchDG Phase 1 training details for all the datasets.We did not do hyper parameter tuning as we did for other methods, hence we mention the default value for each hyper parameter that we used
- Table 10 (supplement, page 11): Optimal values for hyper parameters on PACS. Batch Size (16), Weight Decay (0.0005) was consistent across different cases
- Table 13 (supplement, page 11): For both Rotated & Fashion MNIST, we observe that the approaches that contain a higher proportion of per-
- Table 11 (supplement, page 12): Accuracy for Rotated MNIST datasets using the LeNet architecture as proposed in (Motiian et al., 2017)
- Table 12 (supplement, page 12): Accuracy for Rotated MNIST datasets using the DomainBed setup as proposed in (Gulrajani & Lopez-Paz, 2020)
- Table 13 (supplement, page 12): Accuracy results using a fraction of perfect matches during training
- Table 14 (supplement, page 13): Mean rank, Top-10 overlap, and overlap metrics for the matches learnt in the classiﬁcation phase (Phase 2), when trained
- Table 15 (supplement, page 13): Metrics computed at MatchDG (Phase 1) for Fashion- MNIST dataset with 2K and 10K sample size used for training.
- Table 16 (supplement, page 13): Overlap with perfect matches, top-10 overlap and the mean rank for perfect matches for Iterative and Non Iterative
- Table 17 (supplement, page 15): Accuracy on PACS with ResNet 18 (default, top row set), Resnet 18 with test domain validation (middle row set), and ResNet 50 (bottom row set)
- Table 18 (supplement, page 16): Accuracy results on the PACS dataset trained with Alexnet (default, top row set), and Alexnet with test domain validation (bottom row set)

=== document: main === (text of mahajan21b.pdf, sha256 c9d9f8a4fc7fabd12534630f3268a3dff52eae611eefbebd501f78718ca07c21, extracted with pypdf 6.19.0: 12 pages)
=== document: supplement === (text of mahajan21b-supp.pdf, sha256 2726d78e4d55150c7c208bb37195545ccc32338edff04e9919f1325b94530e67, extracted with pypdf 6.19.0: 19 pages)
