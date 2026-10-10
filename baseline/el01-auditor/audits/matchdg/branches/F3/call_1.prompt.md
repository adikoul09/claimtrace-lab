You are the branch-writing step of a reproducibility audit of a machine-learning paper. The audit compared the paper
with its code and found one setting where they differ. Your job: write the smallest code change that makes the code
follow the paper for this one setting, so that a run of the changed code measures what the setting is worth.

The code is in the directory `./repo` (relative to your working directory): the code as shipped plus the audit's
changes that make it run. Read it with Read, Grep and Glob. Do not run anything, and do not use the web.

Paper: Domain Generalization using Causal Matching (ICML 2021)
Experiment: Table 1, whose caption reads: "Table 1. Slab Dataset: Source domains with noisy linear compo- nent with probability 0.0 and 0.1, target domain with noise 1.0."
The experiment's commands, run from the repository root:
    python data_gen_syn.py
    python train.py --dataset slab --model_name slab --batch_size 128 --lr 0.1 --epochs 100 --out_classes 2 --train_domains 0.0 0.10 --test_domains 1.0 --slab_data_dim 2 --slab_noise 0.1 --n_runs 10 --method_name erm_match --match_case 0.0 --penalty_ws 0.0
    python train.py --dataset slab --model_name slab --batch_size 128 --lr 0.1 --epochs 100 --out_classes 2 --train_domains 0.0 0.10 --test_domains 1.0 --slab_data_dim 2 --slab_noise 0.1 --n_runs 10 --method_name dann --conditional 0 --penalty_ws 0.01 --grad_penalty 0.1 --d_steps_per_g_step 4
    python train.py --dataset slab --model_name slab --batch_size 128 --lr 0.1 --epochs 100 --out_classes 2 --train_domains 0.0 0.10 --test_domains 1.0 --slab_data_dim 2 --slab_noise 0.1 --n_runs 10 --method_name mmd --gaussian 1 --conditional 0 --penalty_ws 0.1
    python train.py --dataset slab --model_name slab --batch_size 128 --lr 0.1 --epochs 100 --out_classes 2 --train_domains 0.0 0.10 --test_domains 1.0 --slab_data_dim 2 --slab_noise 0.1 --n_runs 10 --method_name mmd --gaussian 0 --conditional 0 --penalty_ws 0.1
    python train.py --dataset slab --model_name slab --batch_size 128 --lr 0.1 --epochs 100 --out_classes 2 --train_domains 0.0 0.10 --test_domains 1.0 --slab_data_dim 2 --slab_noise 0.1 --n_runs 10 --method_name erm_match --match_case 0.0 --penalty_ws 1.0
    python train.py --dataset slab --model_name slab --batch_size 128 --lr 0.1 --epochs 100 --out_classes 2 --train_domains 0.0 0.10 --test_domains 1.0 --slab_data_dim 2 --slab_noise 0.1 --n_runs 10 --method_name dann --conditional 1 --penalty_ws 0.01 --grad_penalty 1.0 --d_steps_per_g_step 2
    python train.py --dataset slab --model_name slab --batch_size 128 --lr 0.1 --epochs 100 --out_classes 2 --train_domains 0.0 0.10 --test_domains 1.0 --slab_data_dim 2 --slab_noise 0.1 --n_runs 10 --method_name mmd --gaussian 1 --conditional 1 --penalty_ws 0.1
    python train.py --dataset slab --model_name slab --batch_size 128 --lr 0.1 --epochs 100 --out_classes 2 --train_domains 0.0 0.10 --test_domains 1.0 --slab_data_dim 2 --slab_noise 0.1 --n_runs 10 --method_name mmd --gaussian 0 --conditional 1 --penalty_ws 0.1
    python train.py --dataset slab --model_name slab --batch_size 128 --lr 0.1 --epochs 100 --out_classes 2 --train_domains 0.0 0.10 --test_domains 1.0 --slab_data_dim 2 --slab_noise 0.1 --n_runs 10 --method_name erm_match --match_case 1.0 --penalty_ws 1.0

The setting:
- `optim.momentum`: 0.0 means plain SGD with no momentum; null means the source does not say
- `optim.nesterov`: Nesterov momentum
  optim.momentum, for ERM; MMD; CORAL; RandMatch; C-MMD; C-CORAL; PerfMatch: paper: not stated; code: 0.9
  optim.nesterov, for ERM; MMD; CORAL; RandMatch; C-MMD; C-CORAL; PerfMatch: paper: not stated; code: true
Kind: paper omission. The code has this step or value; the paper describes the method without it. The paper's version is the method without the code's extra step (for a value, the plain form the paper's description implies).
What the paper says (verbatim quotes, checked by code against the paper's text):
  (the paper does not state it)
What the code does (cited lines, checked by code against the code as shipped; the audit's run fixes may shift
line numbers by a few):
  - algorithms/algo.py:185: ], lr= self.args.lr, weight_decay= self.args.weight_decay, momentum= 0.9, nesterov=True )
  - algorithms/dann.py:47-51: self.gen_opt = torch.optim.SGD( (list(self.featurizer.parameters()) + list(self.classifier.parameters())), lr=self.initial_lr, weight_decay=5e-4)
  - algorithms/algo.py:185: ], lr= self.args.lr, weight_decay= self.args.weight_decay, momentum= 0.9, nesterov=True )
  - algorithms/dann.py:47-51: self.gen_opt = torch.optim.SGD( (list(self.featurizer.parameters()) + list(self.classifier.parameters())), lr=self.initial_lr, weight_decay=5e-4)

Rules:
- Change only this setting, and only where the experiment's commands reach it. Everything else must behave exactly
  as before: the same data, the same other settings, the same random-number draws in the same order (if your change
  calls code that draws random numbers, save the random state before and restore it after), and the same printed
  lines (you may print new lines, but do not remove or reword existing ones).
- The existing commands must run the paper's setting as they are: do not require a new command-line option.
- Add no comments, and no new files unless the change cannot be written without one.
- If the paper's words admit more than one implementation, and the implementations would select or train
  differently, give one reading per implementation (at most 3), each with its own complete edits. Otherwise give
  exactly one reading.

Answer with `readings`. Each reading has a short `label`, the `paper_value` it implements (a short phrase), a
one- or two-sentence `rationale`, and `edits`: each edit names a `file` (relative to the repository root), gives
`old` (exact current text of one or more whole lines, appearing exactly once in that file, indentation included) and
`new` (the replacement lines).
