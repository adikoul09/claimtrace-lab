You are the claim-to-command linker of a reproducibility audit of a machine-learning paper. The paper's code, as
shipped at the audited commit, is in the directory `./repo` (relative to your working directory). You may read it with
Read, Grep and Glob; the README, the reproduce scripts and the scripts' `--help` output are also given below.

Paper: Domain Generalization using Causal Matching (ICML 2021)
Repository: https://github.com/microsoft/robustdg
Target: Suppl. Table 11

The claim cells of Suppl. Table 11. Code has checked every number against the paper's own table row:
Caption (page 12 of the supplement document): Accuracy for Rotated MNIST datasets using the LeNet architecture as proposed in (Motiian et al., 2017).
Metric: Accuracy (percent), each column is the target (test) domain rotation angle, with the remaining five domains as source training domains; aggregation: mean, spread: standard deviation in brackets over 3 runs (Average column has no spread), runs: 3
- row 'ERM' (role: baseline; numbers from this paper's runs):
    Table 11|ERM|0
    Table 11|ERM|15
    Table 11|ERM|30
    Table 11|ERM|45
    Table 11|ERM|60
    Table 11|ERM|75
    Table 11|ERM|Average
- row 'CCSA' (role: baseline; numbers taken from other work):
    Table 11|CCSA|0
    Table 11|CCSA|15
    Table 11|CCSA|30
    Table 11|CCSA|45
    Table 11|CCSA|60
    Table 11|CCSA|75
    Table 11|CCSA|Average
- row 'D-MTAE' (role: baseline; numbers taken from other work):
    Table 11|D-MTAE|0
    Table 11|D-MTAE|15
    Table 11|D-MTAE|30
    Table 11|D-MTAE|45
    Table 11|D-MTAE|60
    Table 11|D-MTAE|75
    Table 11|D-MTAE|Average
- row 'LabelGrad' (role: baseline; numbers taken from other work):
    Table 11|LabelGrad|0
    Table 11|LabelGrad|15
    Table 11|LabelGrad|30
    Table 11|LabelGrad|45
    Table 11|LabelGrad|60
    Table 11|LabelGrad|75
    Table 11|LabelGrad|Average
- row 'DAN' (role: baseline; numbers taken from other work):
    Table 11|DAN|0
    Table 11|DAN|15
    Table 11|DAN|30
    Table 11|DAN|45
    Table 11|DAN|60
    Table 11|DAN|75
    Table 11|DAN|Average
- row 'CrossGrad' (role: baseline; numbers taken from other work):
    Table 11|CrossGrad|0
    Table 11|CrossGrad|15
    Table 11|CrossGrad|30
    Table 11|CrossGrad|45
    Table 11|CrossGrad|60
    Table 11|CrossGrad|75
    Table 11|CrossGrad|Average
- row 'DIV A' (role: baseline; numbers taken from other work):
    Table 11|DIV A|0
    Table 11|DIV A|15
    Table 11|DIV A|30
    Table 11|DIV A|45
    Table 11|DIV A|60
    Table 11|DIV A|75
    Table 11|DIV A|Average
- row 'RandMatch' (role: baseline; numbers from this paper's runs):
    Table 11|RandMatch|0
    Table 11|RandMatch|15
    Table 11|RandMatch|30
    Table 11|RandMatch|45
    Table 11|RandMatch|60
    Table 11|RandMatch|75
    Table 11|RandMatch|Average
- row 'MatchDG' (role: method; numbers from this paper's runs):
    Table 11|MatchDG|0
    Table 11|MatchDG|15
    Table 11|MatchDG|30
    Table 11|MatchDG|45
    Table 11|MatchDG|60
    Table 11|MatchDG|75
    Table 11|MatchDG|Average
- row 'PerfMatch' (role: oracle; numbers from this paper's runs):
    Table 11|PerfMatch|0
    Table 11|PerfMatch|15
    Table 11|PerfMatch|30
    Table 11|PerfMatch|45
    Table 11|PerfMatch|60
    Table 11|PerfMatch|75
    Table 11|PerfMatch|Average

Task: for every claim cell, give the commands that produce its number, run from the repository root:
- `data_steps`: the commands that create the data the runs read (data generation, dataset preparation), run once
  before any cell. Include them even when the README does not mention them; find them in the repository.
- For a `linked` cell, `steps`: the commands in the order they run, each named (`train`, `eval`, or one name per
  phase when a method trains in phases). Include the evaluation step when the repository computes the number in a
  separate evaluation run. Steps that produce one row's numbers are usually the same for each of its cells.
- `parser`: the name of an entry in `parsers` that reads the cell's number from the log (stdout and stderr) of one of
  its steps. Code reads a log line by line; in each run block (or the whole log, if `run_start_regex` is null) it keeps
  the last line that matches `line_regex` (and whose `key_group` equals `key_value`, when given); `value_group` is the
  number and `sd_group` its spread, if printed. Declare how many matching lines a block has: once per epoch
  (`per_epoch`), or `count`. Read the print statements in the code to write the regex; give their path:line.
  The audit computes means, spreads and confidence intervals itself, from one number per run (seed). When a log
  prints the cell's number for each run, parse that per-run number (with `run_start_regex`), not a summary line the
  code prints over all runs. Use a whole-log line only when the code prints no per-run value, and say so in `notes`.
- `derived`: a cell the paper computes from other cells of the table (for example an average column): name them in
  `derived_from` and the operation in `derived_op`.
- `unlinked`: a cell this repository does not produce (for example numbers the paper took from other papers, or a
  method the repository does not implement); say why in `reason`.

Rules:
- Use the repository's own commands (the reproduce scripts, the README) wherever they cover a cell, with their
  arguments as written, even where they differ from the paper: differences are the audit's next step, not yours. Do
  not change any setting, add a "fix", or make a run cheaper. Code shortens the runs itself for its dry run.
- Where the repository gives no command or no value for something the paper states for this table (for example
  the data size of a setup the README shows only for another model), follow the paper pages below, and say in
  `notes` which values you took from the paper.
- Every `argv` is a list of tokens: `python`, then the script's path relative to the repository root, then its
  arguments. No shell syntax: no redirection, pipes, `&&`, `cd`, environment variables or output files.
- Every claim id above appears in exactly one entry of `cells`. A linked or derived entry has exactly one id.
- Code checks every option against the script's own argument parser and runs each command for one epoch and one run.

Paper pages that mention Suppl. Table 11 (found by code; text extracted from the PDFs, with `[page N]` markers):
=== supplement [page 7] ===
Domain Generalization using Causal Matching
Below we prove these results formally.
Proposition 3. The conditions enforced by domain-
invariant ( Φ(x) ⊥ ⊥D) or class-conditional domain-
invariant (Φ(x) ⊥ ⊥D|Y ) methods are not satisﬁed by
the causal representation XC. Thus, without additional
assumptions, the set of representations that satisfy any of
these conditions does not containXC, even asn→∞ .
Proof. As in the SCM from Figure 2(b), letXc represent an
unobserved high-level feature vector such that it is generated
based only on the objectO and that it leads to the optimal
classiﬁer in (1). From Sections 4.1 and 4.2, we know that
Xc ⊥ ⊥D|O and that xc = gxc(o). Following a similar
proof to Theorem 1 (Claim 1), we check whether Φ(x) =
xc satisﬁes the invariance conditions required by the two
methods.
1. Domain-invariant: The required condition for a rep-
resentation is that ΦDI(x) ⊥ ⊥D. But using the d-
separation criteria on the SCM in Figure 2(b), we ﬁnd
thatXc⁄⊥ ⊥D due to a path through ObjectO.
2. Class-conditional domain-invariant: The required
condition for a representation is that ΦCDI ⊥ ⊥D|Y .
However using the d-separation criteria on the SCM,
we ﬁnd that Xc⁄⊥ ⊥D|Y due to a path through Ob-
jectO that is not blocked by Y (nor by Ytrue if it is
observed).
Therefore, under the conditions proposed by these methods,
Xc or any function ofXc is not an optimal solution without
making any additional assumptions. Hence, even with inﬁ-
nite samples, a method optimizing for these conditions will
not retrieveXc.
C. Evaluation and implementation details
In this section we describe implementation details for our
proposed methods. We also discuss the evaluation pro-
tocol, including details about hyperparameters and cross-
validation.
C.1. Implementation details
For the implementation of ERM-PerfMatch in Eq. (3);
we use the cross-entropy loss forLd andl2 distance for dist
in Eq. (3). Similarly, we implement the ERM-RandMatch
with a match function Ω in Eq. (3) that randomly matches
data points across domains with the same class, For both
methods, we consider the representation Φ(x) to be the
last layer of the network. That is, we take h to be identity
function in Eq. (3) for simplicity. It is also possible to use
the second-last or any other previous layer as a representa-
tion, but the last layer performed well in our experiments.
Also, given a ﬁxed data point, the match function Ω could
select multiple data points as potential matches for it. In
this case we use Eq. (3) with stochastic matching, where
we randomly select one match out of the potential multiple
matches.
We use SGD to optimize the loss for all the datasets, with
details about learning rate, epochs, batch size, weight decay
etc. provided in the section C.3 ahead. For all the different
methods, we sample batches from the data matrix consisting
of data points matched across domains; hence we ensure
an equal number of data points from each source domain
in a batch. When training with MatchDG, the underlying
architecture for Phase 2 is kept the same for ERM,
RandMatch, PerfMatch for the respective task; with
the details mentioned below for each dataset. The details for
the Phase-1 architecture are speciﬁed in section C.3, Table 9.
Rotated MNIST & Fashion-MNIST.The datasets contain
rotations of grayscale MNIST handwritten digits and fashion
article images from 0◦ to 90◦ with an interval of 15◦ (Ghi-
fary et al., 2015), where each rotation angle represents a
domain and the task is to predict the class label. For Ta-
ble 2, we follow the setup in CSD (Piratla et al., 2020), we
report accuracy on 0◦ and 90◦ together as the test domain
and the rest as the train domains. We use 2, 000 and 10, 000
training samples from each domain for rotated MNIST and
Fashion-MNIST, and train models using Resnet-18 architec-
ture (without pre training). We choose this as our primary
setup and select 0◦ and 90◦ as our target domain, since these
are known to be the most difﬁcult domains to generalize (Pi-
ratla et al., 2020; Motiian et al., 2017).
Further, we also evaluate on other setups of Rotated MNIST
in prior works (Motiian et al., 2017; Gulrajani & Lopez-
Paz, 2020), which involve six domains (0◦, 15◦, 30◦, 45◦,
60◦, 75◦), and evaluate for each domain being the target
domains with the remaining ﬁve used as source domains.
We sample 1000 data points for each domain and evaluate
using the LeNet architecture (Table 11) as per the setup
proposed by (Motiian et al., 2017). Similarly, we sample
all the 70,000 images in MNIST and evaluate using the
custom architecture (Table 12) as per the setup proposed by
(Gulrajani & Lopez-Paz, 2020).
Another important distinction between different setups
above is the use of different digits for the source and the
target domains ((Piratla et al., 2020), (Gulrajani & Lopez-
Paz, 2020)), as opposed to the use of same digits across the
source and the target domains in setup of (Motiian et al.,
2017) which makes the task easier as it leaks information
about the target domains.
Finally, for all the different setups proposed above, we
create an additional validation set for each domain with

=== supplement [page 9] ===
Domain Generalization using Causal Matching
Table 8. Hyper parameter selection details for all the datasets. We mention the Optimal Value for each hyper parameter and the Range
used for grid search. We leave the optimal value for Epochs as blank since we do early stopping based on validation loss, with the total
number of epochs for model training speciﬁed in the Range column. For the dataset PACS, since the optimal values differ for different test
domains, we represent them separately in Table 10
Dataset Hyper Parameter Optimal Value Range
Rotated & Fashion MNIST
Table 2 (ResNet-18)
Total Epochs - 25
Learning Rate 0.01 [0.01]
Batch Size 16 [16]
Weight Decay 0.0005 [0.0005]
Match Penalty 0.1 [0.1, 1.0]
IRM Penalty 1.0 (RotMNIST); 0.05 (FashionMNIST) [0.05, 0.1, 0.5, 1.0, 5.0]
IRM Threshold 5 (RotMNIST), 0 (FashionMNIST) [0, 5, 15, 20]
Rotated MNIST
Table 11 (LeNet)
Total Epochs - 100
Learning Rate 0.01 [0.01]
Batch Size 16 [16]
Weight Decay 0.0005 [0.0005]
Match Penalty 1.0 [0.1, 1.0]
Rotated MNIST
Table 12 (DomainBed)
Total Epochs - 25
Learning Rate 0.01 [0.01]
Batch Size 128 [16, 32, 64, 128]
Weight Decay 0.0005 [0.0005]
Match Penalty 1.0 [0.1, 1.0]
PACS
Table 17, 18
(ResNet-18, ResNet-50, AlexNet)
Total Epochs - 50
Learning Rate Table 10 [0.01, 0.001, 0.0005]
Batch Size 16 [16]
Weight Decay 0.0005 [0.0005]
Match Penalty Table 10 [0.01, 0.1, 0.5, 1.0, 5.0]
Chest X-ray
Table 6 (DenseNet-121)
Total Epochs - 40
Learning Rate 0.001 [0.01, 0.001]
Batch Size 16 [16]
Weight Decay 0.0005 [0.0005]
Match Penalty 10.0 (RandMatch), 50.0 (MatchDG, MDGHybrid) [0.1, 1.0, 10.0, 50.0]
IRM Penalty 10.0 [0.1, 1.0, 10.0, 50.0]
IRM Threshold 5 [0, 5, 15, 20]
matches.
Overlap % : Percentage of matches (j, k) as per the perfect
match strategy Ω that are also consistent with the learnt
match strategy Ω
′
.
∑
Ω(j,k)=1;d⁄=d′ Ω
′
(j,k )∑
Ω(j,k)=1;d⁄=d′ 1 (24)
Top-10 Overlap % : Percentage of matches (j, k) as
per the perfect match strategy Ω that are among the Top-10
matches for the data point j w.r.t the learnt match strategy
Ω
′
i.e.S10
Ω′ (j)
∑
Ω(j,k)=1;d⁄=d′ 1 [k∈S10
Ω′ (j)]∑
Ω(j,k)=1;d⁄=d′ 1 (25)
Mean Rank : For the matches (j, k) as per the perfect match
strategy Ω, compute the mean rank for the data point j w.r.t
the learnt match strategy Ω
′
i.e.SΩ′ (j)
∑
Ω(j,k)=1;d⁄=d′Rank[k∈SΩ′ (j)]∑
Ω(j,k)=1;d⁄=d′ 1 (26)
C.3. HyperParameter Tuning
To select hyperparameters, prior works (Dou et al., 2019;
Carlucci et al., 2019; Li et al., 2018a) use leave-one-domain-
out validation, which means that the hyperparameters are
tuned after looking at data from the unseen domain. Such a
setup is violates the premise of the domain generalization
task that assumes that a model should have no access to the
test domain. Therefore, in this work, we construct a valida-
tion set using only the source domains and use it for hyper
parameter tuning. In the case of PACS, we already have ac-
cess to the validation indices for each domain and use them
to construct a validation set based on the source domains.
For Rotated & Fashion MINST, Chest X-ray datasets, we
create validation set for each source domain as described
in the section B.1 above. Hence, the model does not have

=== supplement [page 10] ===
Domain Generalization using Causal Matching
Table 9. MatchDG Phase 1 training details for all the datasets.We did not do hyper parameter tuning as we did for other methods, hence
we mention the default value for each hyper parameter that we used. Please note we still did early stopping, the Total Epochs in the table
reﬂects the max budget for training. The speciﬁc archiecture used for Phase 1 training is also mentioned for each dataset.
Dataset Hyper Parameter Default Value
Rotated & Fashion MNIST
Table 2, 11, 12
Total Epochs 50
Learning Rate 0.01
Batch Size 64 (Table 2), 512 (Table 11, Table 12)
Weight Decay 0.0005
τ 0.05
Architecture ResNet-18 (Table 2), LeNet (Table 11), Custom CNN (Table 12)
PACS
Table 17, 18
Total Epochs 50
Learning Rate 0.01
Batch Size 32
Weight Decay 0.0005
τ 0.05
Architecture ResNet-50
Chest X-ray
Table 6
Total Epochs 50
Learning Rate 0.01
Batch Size 32
Weight Decay 0.0005
τ 0.05
Architecture DenseNet-121
access to the data points from the target/test domains at the
time of training and validation.
We perform a grid search over pre-deﬁned values for each
hyper parameter and report the optimal values along with
the values used for grid search in Table 8. Further, we do
early stopping based on the validation accuracy on source
domains and use the models which obtain the best validation
accuracy.
For the case of MatchDG Phase-1, we do not perform grid
search and use default values for each hyper parameter (Ta-
ble 9). We still do early stopping for MatchDG Phase-
1, based on the metric Top-10 Overlap (Section B.2)
over the validation set of source domains. Since we require
perfect matches for the evaluation of the metric Top-10
Overlap, we create prefect matches using the self aug-
mentations (Section B.1) for each dataset.
C.4. Reproducing Results from Prior Work
MNIST and Fashion MNIST The results for MASF,
CSD, and IRM in Table 2 were computed using their code
which is available online 123 . The MASF code was hard-
coded to run for PACS dataset; which has 3 source domains
that gets divided into 2 meta train and 1 meta test domain.
Their code requires atleast 2 meta train domains; which
leads to an issue for only 2 source domains (30, 45). In
Table 2 when there are only 2 source domains; their code
1https://github.com/vihari/CSD
2https://github.com/biomedia-mira/masf
3https://github.com/facebookresearch/InvariantRiskMinimization
considers only 1 meta train domain. To resolve this issue;
we create a copy of the 1 meta train domain and thus run
MASF for source domains 30, 45 on MNIST.
The results for prior approaches in Table 11 are taken from
(Shankar et al., 2018), (Ilse et al., 2020). For the results
using DomainBed setup in Table 12, the results for prior
approaches are taken from (Gulrajani & Lopez-Paz, 2020).
PACS We did not generate results for the prior approaches
for PACS by developing or using existing implementations.
All the results for the prior approaches on PACS were taken
from the respective papers as speciﬁed in the Table 17, 18.
Chest X-ray The results for the prior approaches CSD,
IRM were generated using the implementations of both of
the methods available on github 1,3 .
D. Additional Evaluation on Rotated MNIST
and Fashion-MNIST
Here we present results for additional experiments on
Rotated MNIST and Fashion-MNIST datasets using
MatchDG.
D.1. Comparing MatchDG with prior work on the
LeNet Network
Table 11 compares the accuracy results for MatchDG
with prior work on the LeNet architecture (Motiian et al.,
2017). In this setup, there are six domains in total

=== supplement [page 12] ===
Domain Generalization using Causal Matching
Table 11. Accuracy for Rotated MNIST datasets using the LeNet architecture as proposed in (Motiian et al., 2017). The results for the
prior approaches CCSA (Motiian et al., 2017), D-MTAE (Ghifary et al., 2015), LabelGrad (Goodfellow et al., 2014), DAN (Ganin et al.,
2016), and CrossGrad (Shankar et al., 2018) are taken from Table 9 in (Shankar et al., 2018). The results for DIV A (Ilse et al., 2020) are
taken from the Table 1 in their paper.
Algorithm 0 15 30 45 60 75 Average
ERM 88.2 (1.0) 98.6 (0.5) 97.7 (0.6) 97.5 (0.3) 97.0 (0.1) 85.6 (2.1) 94.1
CCSA 84.6 95.6 94.6 82.9 94.8 82.1 89.1
D-MTAE 82.5 96.3 93.4 78.6 94.2 80.5 87.6
LabelGrad 89.7 97.8 98.0 97.1 96.6 92.1 95.2
DAN 86.7 98.0 97.8 97.4 96.9 89.1 94.3
CrossGrad 88.3 98.6 98.0 97.7 97.7 91.4 95.3
DIV A 93.5 (0.3) 99.3 (0.1) 99.1 (0.1) 99.2 (0.1) 99.3 (0.1) 93.0 (0.4) 97.2
RandMatch 91.0 (0.9) 99.7 (0.2) 99.6 (0.1) 99.4 (0.1) 99.7 (0.1) 93.1 (1.1) 97.1
MatchDG 93.0 (0.5) 99.5 (0.3) 99.9 (0.1) 99.4 (0.1) 99.7 (0.3) 93.3 (1.1) 97.4
PerfMatch 96.5 (0.6) 99.1 (0.3) 99.2 (0.3) 98.6 (0.7) 98.6 (1.0) 94.9 (1.8) 97.8
Table 12. Accuracy for Rotated MNIST datasets using the DomainBed setup as proposed in (Gulrajani & Lopez-Paz, 2020). The results
for the approaches IRM (Arjovsky et al., 2019), DRO (Sagawa et al., 2019), Mixup (Xu et al., 2019; Yan et al., 2020; Wang et al., 2020),
MLDG (Li et al., 2018a), CORAL (Sun & Saenko, 2016), MMD (Li et al., 2018b), DANN (Ganin et al., 2016), C-DANN (Li et al.,
2018d) are taken from (Gulrajani & Lopez-Paz, 2020).
Algorithm 0 15 30 45 60 75 Average
ERM 95.6 (0.1) 99.0 (0.1) 98.9 (0.0) 99.1 (0.1) 99.0 (0.0) 96.7 (0.2) 98.0
IRM 95.9 (0.2) 98.9 (0.0) 99.0 (0.0) 98.8 (0.1) 98.9 (0.1) 95.5 (0.3) 97.9
DRO 95.9 (0.1) 98.9 (0.0) 99.0 (0.1) 99.0 (0.0) 99.0 (0.0) 96.9 (0.1) 98.1
Mixup 96.1 (0.2) 99.1 (0.0) 98.9 (0.0) 99.0 (0.0) 99.0 (0.1) 96.6 (0.1) 98.1
MLDG 95.9 (0.2) 98.9 (0.1) 99.0 (0.0) 99.1 (0.0) 99.0 (0.0) 96.0 (0.2) 98.0
CORAL 95.7 (0.2) 99.0 (0.0) 99.1 (0.1) 99.1 (0.0) 99.0 (0.0) 96.7 (0.2) 98.1
MMD 96.6 (0.1) 98.9 (0.0) 98.9 (0.1) 99.1 (0.1) 99.0 (0.0) 96.2 (0.1) 98.1
DANN 95.6 (0.3) 98.9 (0.0) 98.9 (0.0) 99.0 (0.1) 98.9 (0.0) 95.9 (0.5) 97.9
C-DANN 96.0 (0.5) 98.8 (0.0) 99.0 (0.1) 99.1 (0.0) 98.9 (0.1) 96.5 (0.3) 98.0
RandMatch 95.4 (0.4) 98.2 (0.1) 97.9 (0.5) 98.5 (0.1) 98.1 (0.1) 94.3 (0.3) 97.1
MatchDG 95.9 (0.1) 98.4 (0.1) 98.6 (0.2) 98.9 (0.2) 98.7 (0.1) 95.1 (0.3) 97.6
Table 13. Accuracy results using a fraction of perfect matches
during training
MNIST Fashion-MNIST
RandMatch 93.4 (0.26) 77.0 (0.42)
Approx 25% 93.8 (0.48) 77.8 (0.79)
Approx 50% 94.0 (0.42) 78.0 (0.78)
Approx 75% 94.7 (0.14) 78.9 (0.31)
PerfMatch (100%) 96.0 (0.41) 81.6 (0.46)
MNIST and Fashion-MNIST datasets, MatchDG ob-
tains mean rank, Top 10 overlap and total overlap be-
tween ERM-PerfMatch and ERM-RandMatch. As the
Fashion-MNIST dataset is more complex than the digits
dataset, we observe that the mean rank with different train-
ing techniques is higher than the corresponding values for
the Rotated-MNIST dataset.
D.5. Matching metrics for Fashion-MNIST dataset
with 2000 training samples per domain
In the main text (Table 3), we computed matching metrics
for MatchDG (Phase 1) over the Fashion-MNIST dataset
with 10000 samples per domain. Here we compute the same
metrics for a smaller dataset with 2000 samples per domain.
We compute the metric for the default instantiation of Phase
1 of MatchDG initialized with random matches and com-
pare it to an oracle version of MatchDG initialized with
perfect matches. In addition, we compare the metrics for
matches generated using baseline ERM (last layer of the net-
work) in order to understand its effectiveness as a matching
strategy in Phase 1. Table 15 shows the metrics for Phase
1 of MatchDG with 2K images from the Fashion-MNIST
dataset, and reproduces the metrics for the 10K dataset from
Table 3 for ease of comparison. We observe that the mean
rank of perfect matches improves for the smaller dataset.
Similarly, the overlap and top-10 overlap also increase for

README (verbatim):
````
Toolkit for Building Robust ML models that generalize to unseen domains (RobustDG)
==================================================================================
`Divyat Mahajan <https://divyat09.github.io/>`_, 
`Shruti Tople <https://www.microsoft.com/en-us/research/people/shtople/>`_, 
`Amit Sharma <http://www.amitsharma.in>`_

`Privacy & Causal Learning (ICML 2020) <https://arxiv.org/abs/1909.12732>`_ | `MatchDG: Causal View of DG (ICML 2021) <http://proceedings.mlr.press/v139/mahajan21b.html>`_ | `Privacy & DG Connection paper <https://arxiv.org/abs/2110.03369>`_

For machine learning models to be reliable, they need to generalize to data
beyond the train distribution. In addition, ML models should be robust to
privacy attacks like membership inference and domain knowledge-based attacks like adversarial attacks.

To advance research in building robust and generalizable models, we are
releasing a toolkit for building and evaluating ML models, *RobustDG*. RobustDG contains implementations of domain
generalization algorithms and includes evaluation benchmarks based
on out-of-distribution accuracy and robustness to membership privacy attacks. We will be adding evaluation for adversarial attacks and more privacy attacks soon. 

It is easily extendable. Add your own DG algorithms and evaluate them on different benchmarks.


Installation
------------
To use the command-line interface of RobustDG, clone this repo and add the folder to your system's PATH (or alternatively, run the commands from the RobustDG root directory). 

**Load dataset**

Let's first load the rotatedMNIST dataset in a suitable format for the resnet18 architecture.

.. code:: shell

    python data/data_gen_mnist.py --dataset rot_mnist --model resnet18 --img_h 224 --img_w 224 --subset_size 2000

**Train and evaluate ML model**

The following commands would train and evalute the MatchDG method on the Rotated MNIST dataset.

.. code:: shell


    python train.py --dataset rot_mnist --method_name matchdg_ctr --match_case 0.0 --match_flag 1 --epochs 50 --batch_size 64 --pos_metric cos --match_func_aug_case 1
    
    python train.py --dataset rot_mnist --method_name matchdg_erm --penalty_ws 0.1 --match_case -1 --ctr_match_case 0.0 --ctr_match_flag 1 --ctr_match_interrupt 5 --ctr_model_name resnet18 --epochs 25
    
    python test.py --dataset rot_mnist --method_name matchdg_erm --penalty_ws 0.1 --match_case -1 --ctr_match_case 0.0 --ctr_match_flag 1 --ctr_match_interrupt 5 --ctr_model_name resnet18 --epochs 25 --test_metric acc
    
    python test.py --dataset rot_mnist --method_name matchdg_ctr --match_case 0.0 --match_flag 1 --pos_metric cos --test_metric match_score    


Demo
----

A quick introduction on how to use our repository can be accessed here in the `Getting Started notebook <https://github.com/microsoft/robustdg/blob/master/docs/notebooks/robustdg_getting_started.ipynb>`_.

If you are interested in reproducing results from the MatchDG paper, check out the `Reproducing results notebook <https://github.com/microsoft/robustdg/blob/master/docs/notebooks/reproduce_results.ipynb>`_. 

Roadmap
-------

* Support for more domain generalization algorithms like CSD and IRM. If you are an author of a DG algorithm and would like to contribute, please raise a  pull request `here <https://github.com/microsoft/robustdg/pulls>`_ or get in touch.

* More evaluation metrics based on adversarial attacks, privacy attacks like model inversion. If you'd like to see an evaluation metric implemented, please raise an issue `here <https://github.com/microsoft/robustdg/issues>`_.

Contributing
--------------

This project welcomes contributions and suggestions.  Most contributions require you to agree to a
Contributor License Agreement (CLA) declaring that you have the right to, and actually do, grant us
the rights to use your contribution. For details, visit https://cla.opensource.microsoft.com.

When you submit a pull request, a CLA bot will automatically determine whether you need to provide
a CLA and decorate the PR appropriately (e.g., status check, comment). Simply follow the instructions
provided by the bot. You will only need to do this once across all repos using our CLA.

This project has adopted the `Microsoft Open Source Code of Conduct <https://opensource.microsoft.com/codeofconduct/>`_.
For more information see the `Code of Conduct FAQ <https://opensource.microsoft.com/codeofconduct/faq/>`_ or
contact `opencode@microsoft.com <mailto:opencode@microsoft.com>`_ with any additional questions or comments.
````

Reproduce scripts (verbatim):
--- reproduce_scripts/cxray_plot.py ---
````
import os
import sys
import matplotlib
import matplotlib.pyplot as plt
import numpy as np

def get_base_dir(test_domain, dataset, metric):
    
    if metric == 'mia':
        res_dir= 'results/'+str(dataset)+'/privacy/' + str(test_domain) + '/'

    elif metric == 'privacy_entropy':
        res_dir= 'results/'+str(dataset)+'/privacy_entropy/' + str(test_domain) + '/'

    elif metric == 'privacy_loss_attack':
        res_dir= 'results/'+str(dataset)+'/privacy_loss/' + str(test_domain) + '/' 

    elif metric == 'attribute_attack':
        res_dir= 'results/'+str(dataset)+'/attribute_attack_' + data_case + '/'  + str(test_domain) + '/'  

    elif metric  == 'acc:train':
        res_dir= 'results/' + str(dataset) + '/acc_' + 'train' + '/' + str(test_domain) + '/'

    elif metric  == 'acc:test':
        res_dir= 'results/' + str(dataset) + '/acc_' + 'test' + '/' + str(test_domain) + '/'
        
    elif metric  == 'match_score:train':
        res_dir= 'results/' + str(dataset) + '/match_score_' + 'train' + '/' + str(test_domain) + '/'    

    elif metric  == 'match_score:test':
        res_dir= 'results/' + str(dataset) + '/match_score_' + 'test' + '/' + str(test_domain) + '/'    
        
    return res_dir

x=['ERM', 'Rand', 'MatchDG', 'CSD', 'IRM', 'Hybrid']
methods=['erm', 'rand', 'matchdg_erm', 'csd', 'irm', 'hybrid']
dataset= 'chestxray'

matplotlib.rcParams.update({'errorbar.capsize': 2})
fig, ax = plt.subplots(1, 3, figsize=(33, 8))
fontsize=35
fontsize_lgd= fontsize/1.2

# kaggle, nih, chex
for idx in range(3):
        
    marker_list = ['o', '^', '*']
    legend_list = ['RSNA', 'NIH', 'Chex']
    legend_count = 0
    for test_domain in ['kaggle', 'nih', 'chex']:

        metrics= ['acc:train', 'acc:test', 'privacy_loss_attack']

        acc_train=[]
        acc_train_err=[]

        acc_test=[]
        acc_test_err=[]

        mia=[]
        mia_err=[]

        entropy=[]
        entropy_err=[]

        loss=[]
        loss_err=[]

        rank_train=[]
        rank_train_err=[]

        rank_test=[]
        rank_test_err=[]

        for metric in metrics:
            for method in methods:

                res_dir= get_base_dir(test_domain, dataset, metric)

                f= open(res_dir+method+'.txt')
                data= f.readlines()
        #         print(data[-3].replace('\n', '').split(':')[-1].split(' '))
                mean= float(data[-3].replace('\n', '').split(':')[-1].split(' ')[-2])
                sd= float(data[-3].replace('\n', '').split(':')[-1].split(' ')[-1])

                if metric == 'acc:train':
                    acc_train.append(mean)
                    acc_train_err.append(sd)
                elif metric == 'acc:test':
                    acc_test.append(mean)
                    acc_test_err.append(sd)
                elif metric == 'mia':
                    mia.append(mean)
                    mia_err.append(sd)
                elif metric == 'privacy_entropy':
                    entropy.append(mean)
                    entropy_err.append(sd)
                elif metric == 'privacy_loss_attack':
                    loss.append(mean)
                    loss_err.append(sd)
                elif metric == 'match_score:train':
                    rank_train.append(mean)
                    rank_train_err.append(sd)
                elif metric == 'match_score:test':
                    rank_test.append(mean)
                    rank_test_err.append(sd)

        ax[idx].tick_params(labelsize=fontsize)
        ax[idx].set_xticklabels(x, rotation=25)
    
        if idx == 0:
            ax[idx].errorbar(x, acc_test, yerr=acc_test_err, label= legend_list[legend_count], marker= marker_list[legend_count], markersize= fontsize_lgd, linewidth=4, fmt='o--')
            ax[idx].set_ylabel('OOD Accuracy', fontsize=fontsize)

        if idx == 1:
            ax[idx].errorbar(x, loss, yerr=loss_err, label= legend_list[legend_count], marker= marker_list[legend_count], markersize= fontsize_lgd, linewidth=4, fmt='o--')
            ax[idx].set_ylabel('MI Attack Accuracy', fontsize=fontsize)

#         if idx == 2:
#     #         ax.errorbar(x, rank_train, yerr=rank_train_err, label='Train', fmt='o--', color='brown')
#             ax[idx].errorbar(x, rank_test, yerr=rank_test_err, label='Test', fmt='o--', color='green')
#     #         ax.set_xlabel('Models', fontsize=fontsize)
#             ax[idx].set_ylabel('Mean Rank of Perfect Match', fontsize=fontsize)
#             ax[idx].legend(fontsize=fontsize_lgd)

        if idx == 2:
            ax[idx].errorbar(x, np.array(acc_train) - np.array(acc_test), yerr=acc_train_err, label= legend_list[legend_count], marker= marker_list[legend_count], markersize= fontsize_lgd, linewidth=4, fmt='o--')
            ax[idx].set_ylabel('Train-Test Accuracy Gap ', fontsize=fontsize)
    
    
        legend_count+= 1 
    
save_dir= 'results/' + dataset+ '/plots/'    
if not os.path.exists(save_dir):
    os.makedirs(save_dir)        

lines, labels = fig.axes[-1].get_legend_handles_labels()    
lgd= fig.legend(lines, labels, loc="lower center", bbox_to_anchor=(0.5, -0.15), fontsize=fontsize, ncol=3)
    
plt.tight_layout()
plt.savefig(save_dir + 'privacy_' + str(dataset) + '.pdf', bbox_extra_artists=(lgd,), bbox_inches='tight', dpi=600)
````

--- reproduce_scripts/cxray_run.py ---
````
import os
import sys
import argparse

# Input Parsing
parser = argparse.ArgumentParser()
parser.add_argument('--metric', type=str, default='train', 
                    help='train: Train the models; acc: Evaluate the train/test accuracy; privacy_loss_attack: Evaluate the MI attack robustness; match_score: Evaluate the match function statistics; attribute_attack: Evalute the attribute attack robustness')
parser.add_argument('--data_case', type=str, default='test', 
                   help='train: Evaluate the acc/match_score metrics on the train dataset; test: Evaluate the acc/match_score metrics on the test dataset')
parser.add_argument('--test_domain', type=str, default='kaggle', 
                   help='nih; chex; kaggle')
args = parser.parse_args()

metric= args.metric
test_domain= args.test_domain
data_case= args.data_case

if metric == 'train':
    methods=['erm', 'irm', 'csd', 'rand', 'matchdg_ctr', 'matchdg_erm', 'hybrid']
else:
    methods=['erm', 'irm', 'csd', 'rand', 'matchdg_erm', 'hybrid']

domains= ['nih', 'chex', 'kaggle']
dataset= 'chestxray'

if metric == 'train':
    base_script= 'python train.py --dataset chestxray --out_classes 2 --perfect_match 0 --img_c 3 --pre_trained 1 --model_name densenet121 '
    res_dir= 'results/' + str(dataset) + '/train_logs/'    

elif metric == 'mia':
    base_script= 'python test.py --dataset chestxray --out_classes 2 --perfect_match 0 --img_c 3 --pre_trained 1 --model_name densenet121 --test_metric mia --mia_sample_size 200 --mia_logit 1 --batch_size 64 '
    res_dir= 'results/'+str(dataset)+'/privacy/' 

elif metric == 'privacy_entropy':
    base_script= 'python test.py --dataset chestxray --out_classes 2 --perfect_match 0 --img_c 3 --pre_trained 1 --model_name densenet121 --test_metric privacy_entropy --mia_sample_size 200 --batch_size 64 '
    res_dir= 'results/'+str(dataset)+'/privacy_entropy/'

elif metric == 'privacy_loss_attack':
    base_script= 'python test.py --dataset chestxray --out_classes 2 --perfect_match 0 --img_c 3 --pre_trained 1 --model_name densenet121 --test_metric privacy_loss_attack --mia_sample_size 200 --batch_size 64 '
    res_dir= 'results/'+str(dataset)+'/privacy_loss/'

elif metric  == 'acc':
    base_script= 'python test.py --dataset chestxray --out_classes 2 --perfect_match 0 --img_c 3 --pre_trained 1 --model_name densenet121 --test_metric acc ' + ' --acc_data_case ' + data_case
    res_dir= 'results/' + str(dataset) + '/acc_' + str(data_case) + '/'

elif metric  == 'per_domain_acc':
    base_script= 'python test.py --dataset chestxray --out_classes 2 --perfect_match 0 --img_c 3 --pre_trained 1 --model_name densenet121 --test_metric per_domain_acc --acc_data_case val '
    res_dir= 'results/' + str(dataset) + '/per_domin_acc/'
    
elif metric  == 'match_score':
    base_script= 'python test.py --dataset chestxray --out_classes 2 --perfect_match 0 --img_c 3 --pre_trained 1 --model_name densenet121 --test_metric match_score --match_func_aug_case 1' + ' --match_func_data_case ' + data_case
    res_dir= 'results/' + str(dataset) + '/match_score_' + data_case + '/'

elif metric  == 'feat_eval':
    base_script= 'python test.py --dataset chestxray --out_classes 2 --perfect_match 0 --img_c 3 --pre_trained 1 --model_name densenet121 --test_metric feat_eval --match_func_aug_case 1' + ' --match_func_data_case ' + data_case
    res_dir= 'results/' + str(dataset) + '/feat_eval_' + data_case + '/'

elif metric  == 'feat_eval_rand':
    base_script= 'python test.py --dataset chestxray --out_classes 2 --perfect_match 0 --img_c 3 --pre_trained 1 --model_name densenet121 --test_metric feat_eval --match_func_aug_case 1' + ' --match_func_data_case ' + data_case + ' --match_case 0.0 '
    res_dir= 'results/' + str(dataset) + '/feat_eval_rand_' + data_case + '/'
        
#Test Domain
curr_test_domain= test_domain
# curr_test_domain= test_domain + '_opp_trans'
# curr_test_domain= test_domain + '_trans'

res_dir=  res_dir+ curr_test_domain + '/'    
if not os.path.exists(res_dir):
    os.makedirs(res_dir)        
    
for method in methods:    

    if method == 'erm':
        script= base_script + ' --method_name erm_match --epochs 40  --lr 0.001 --match_case 0.0 --penalty_ws 0.0 '
        
    elif method == 'rand':
        script= base_script + ' --method_name erm_match --epochs 40  --lr 0.001 --match_case 0.0 --penalty_ws 10.0 '

    elif method == 'csd':
        script= base_script + ' --method_name csd --epochs 40  --lr 0.001 --match_case 0.0 --penalty_ws 0.0 --rep_dim 1024'
        
    elif method == 'irm':
        script= base_script + ' --method_name irm --epochs 40  --lr 0.001 --match_case 0.0 --penalty_irm 10.0 --penalty_s 5'
        
    elif method == 'matchdg_ctr':
        script= base_script + ' --method_name matchdg_ctr --epochs 50 --batch_size 32 --match_case 0.0 --match_flag 1  --pos_metric cos --match_func_aug_case 1 '

    elif method == 'matchdg_erm':
        script= base_script + ' --method_name matchdg_erm  --epochs 40 --lr 0.001  --match_case -1 --penalty_ws 50.0 --ctr_match_case 0.0 --ctr_match_flag 1 --ctr_match_interrupt 5 --ctr_model_name densenet121'

    elif method == 'hybrid':
        script= base_script + ' --method_name hybrid  --epochs 40 --lr 0.001  --match_case -1 --penalty_ws 1.0 --penalty_aug 50.0 --ctr_match_case 0.0 --ctr_match_flag 1 --ctr_match_interrupt 5 --ctr_model_name densenet121'    
    
    #To train and test on different domains (Out of Distribution Generalization)
    train_domains=''
    for d in domains:
        if d != test_domain:
            train_domains+= str(d) + '_trans' + ' '
    
    # To train and test on the same domains (In Distribution Generalization)
#     train_domains= curr_test_domain
            
    print('Metric', metric, ' Method: ', method, ' Train Domains: ', train_domains, ' Test Domains: ', curr_test_domain)
    script= script + ' --train_domains ' + train_domains + ' --test_domains ' + curr_test_domain
    
    #TODO: Won't be ideal to have this manually commented by user for the matchdg paper results
    # 5 seeds to formally define the trends for the privacy part
    script= script + ' --n_runs 5 '
    
    script= script + ' > ' + res_dir + str(method) + '.txt'
    os.system(script)
````

--- reproduce_scripts/mnist_mdg_ctr_run.py ---
````
import os
import argparse

# Input Parsing
parser = argparse.ArgumentParser()
parser.add_argument('--dataset', type=str, default='rot_mnist', 
                    help='Datasets: rot_mnist; fashion_mnist')
parser.add_argument('--iterative', type=int, default=1, 
                    help='Iterative updates to positive matches')
parser.add_argument('--perf_init', type=int, default=0, 
                    help='Positive matches Initialization to perfect matches')

args = parser.parse_args()
dataset= args.dataset
iterative= args.iterative
perf_init= args.perf_init

base_script= 'python train.py --epochs 50 --batch_size 64 --dataset ' + str(dataset)
script= base_script + '  --method_name matchdg_ctr --pos_metric cos --match_case ' +  str(perf_init) + ' --match_flag ' + str(iterative)
os.system(script)


#2) Script for evaluating the match function metrics
````

--- reproduce_scripts/mnist_plot.py ---
````
import os
import sys
import matplotlib
import matplotlib.pyplot as plt
import numpy as np

def get_base_dir(train_case, test_case, dataset, metric):
    
    if metric == 'mia':
        res_dir= 'results/'+str(dataset)+'/privacy/'

    elif metric == 'privacy_entropy':
        res_dir= 'results/'+str(dataset)+'/privacy_entropy/'

    elif metric == 'privacy_loss_attack':
        res_dir= 'results/'+str(dataset)+'/privacy_loss/'

    elif metric == 'attribute_attack':
        res_dir= 'results/'+str(dataset)+'/attribute_attack_' + data_case + '/'  

    elif metric  == 'acc:train':
        res_dir= 'results/' + str(dataset) + '/acc_' + 'train' + '/'

    elif metric  == 'acc:test':
        res_dir= 'results/' + str(dataset) + '/acc_' + 'test' + '/'
        
    elif metric  == 'match_score:train':
        res_dir= 'results/' + str(dataset) + '/match_score_' + 'train' + '/'

    elif metric  == 'match_score:test':
        res_dir= 'results/' + str(dataset) + '/match_score_' + 'test' + '/'

    elif metric  == 'feat_eval:train':
        res_dir= 'results/' + str(dataset) + '/feat_eval_' + 'train' + '/'

    elif metric  == 'feat_eval:test':
        res_dir= 'results/' + str(dataset) + '/feat_eval_' + 'test' + '/'
        
    #Train Domains 30, 45 case
    if train_case == 'train_abl_2':
        res_dir= res_dir[:-1] +'_30_45/'

    #Train Domains 30, 45, 60 case
    if train_case == 'train_abl_3':
        res_dir= res_dir[:-1] +'_30_45_60/'            

    #Test on 30, 45 angles instead of the standard 0, 90
    if test_case  == 'test_common':
        res_dir+= 'test_common_domains/'
        
    return res_dir

    
#rot_mnist, fashion_mnist, rot_mnist_spur
dataset=sys.argv[1]

# train_all, train_abl_3, train_abl_2
# train_case= sys.argv[2]

# test_diff, test_common
test_case=['test_diff']

matplotlib.rcParams.update({'errorbar.capsize': 2})
fig, ax = plt.subplots(1, 3, figsize=(33, 8))
fontsize=35
fontsize_lgd= fontsize/1.2
x=['ERM', 'Rand', 'MatchDG', 'CSD', 'IRM', 'Perf']
methods=['erm', 'rand', 'matchdg', 'csd', 'irm', 'perf']
# metrics= ['acc:train', 'acc:test', 'mia', 'privacy_entropy', 'privacy_loss_attack', 'match_score:train', 'match_score:test', 'feat_eval:train', 'feat_eval:test']

metrics= ['acc:train', 'acc:test', 'privacy_loss_attack', 'match_score:test']

for idx in range(3):
    
    marker_list = ['o', '^', '*']
    legend_count = 0
    for train_case in ['train_all', 'train_abl_3', 'train_abl_2']:

        acc_train=[]
        acc_train_err=[]

        acc_test=[]
        acc_test_err=[]

        mia=[]
        mia_err=[]

        entropy=[]
        entropy_err=[]

        loss=[]
        loss_err=[]

        rank_train=[]
        rank_train_err=[]

        rank_test=[]
        rank_test_err=[]

        feat_eval_train=[]
        feat_eval_train_err=[]

        feat_eval_test=[]
        feat_eval_test_err=[]

        for metric in metrics:
            for method in methods:

                res_dir= get_base_dir(train_case, test_case, dataset, metric)

                f= open(res_dir+method+'.txt')
                data= f.readlines()
        #         print(data[-3].replace('\n', '').split(':')[-1].split(' '))
                mean= float(data[-3].replace('\n', '').split(':')[-1].split(' ')[-2])
                sd= float(data[-3].replace('\n', '').split(':')[-1].split(' ')[-1])

                if metric == 'acc:train':
                    acc_train.append(mean)
                    acc_train_err.append(sd)
                elif metric == 'acc:test':
                    acc_test.append(mean)
                    acc_test_err.append(sd)
                elif metric == 'mia':
                    mia.append(mean)
                    mia_err.append(sd)
                elif metric == 'privacy_entropy':
                    entropy.append(mean)
                    entropy_err.append(sd)
                elif metric == 'privacy_loss_attack':
                    loss.append(mean)
                    loss_err.append(sd)
                elif metric == 'match_score:train':
                    rank_train.append(mean)
                    rank_train_err.append(sd)
                elif metric == 'match_score:test':
                    rank_test.append(mean)
                    rank_test_err.append(sd)
                elif metric == 'feat_eval:train':
                    feat_eval_train.append(mean)
                    feat_eval_train_err.append(sd)
                elif metric == 'feat_eval:test':
                    feat_eval_test.append(mean)
                    feat_eval_test_err.append(sd)

        if train_case == 'train_all':
            legend_label= '5 domains'
        elif train_case == 'train_abl_2':
            legend_label= '3 domains'
        elif train_case == 'train_abl_3':
            legend_label= '2 domains'
        
        ax[idx].tick_params(labelsize=fontsize)
        ax[idx].set_xticklabels(x, rotation=25) 
    
        if idx == 0:
            ax[idx].errorbar(x, acc_test, yerr=acc_test_err, label=legend_label, marker= marker_list[legend_count], markersize= fontsize_lgd, linewidth=4, fmt='o--')
            ax[idx].set_ylabel('OOD Accuracy', fontsize=fontsize)            
            
            
        if idx == 1:
            ax[idx].errorbar(x, loss, yerr=loss_err, label=legend_label, marker= marker_list[legend_count], markersize= fontsize_lgd, linewidth=4, fmt='o--')
            ax[idx].set_ylabel('MI Attack Accuracy', fontsize=fontsize)

        if idx == 2:
            ax[idx].errorbar(x, rank_test, yerr=rank_test_err, label=legend_label, marker= marker_list[legend_count], markersize= fontsize_lgd, linewidth=4, fmt='o--')
            ax[idx].set_ylabel('Mean Rank', fontsize=fontsize)

        if idx == 3:
            ax[idx].errorbar(x, np.array(acc_train) - np.array(acc_test), yerr=acc_train_err, marker= 's', markersize= fontsize_lgd, linewidth=4, fmt='o--')
            ax[idx].set_ylabel('Generalization Gap', fontsize=fontsize)
        
        legend_count+= 1 
    
save_dir= 'results/' + dataset+ '/plots/'
if not os.path.exists(save_dir):
    os.makedirs(save_dir)

lines, labels = fig.axes[-1].get_legend_handles_labels()    
lgd= fig.legend(lines, labels, loc="lower center", bbox_to_anchor=(0.5, -0.15), fontsize=fontsize, ncol=3)

plt.tight_layout()
plt.savefig(save_dir + 'privacy_' + str(dataset) + '.pdf', bbox_extra_artists=(lgd,), bbox_inches='tight', dpi=600)
````

--- reproduce_scripts/mnist_run.py ---
````
import os
import sys
import argparse

# Input Parsing
parser = argparse.ArgumentParser()
parser.add_argument('--dataset', type=str, default='rot_mnist', 
                    help='Datasets: rot_mnist; fashion_mnist; rot_mnist_spur')
parser.add_argument('--train_case', type=str, default='train_all', 
                    help='train_all: Train with all the 5 domains; train_abl_3: Train with 3 domains; train_abl_2: Train with 2 domains')
parser.add_argument('--metric', type=str, default='train', 
                    help='train: Train the models; acc: Evaluate the train/test accuracy; privacy_loss_attack: Evaluate the MI attack robustness; match_score: Evaluate the match function statistics; attribute_attack: Evalute the attribute attack robustness')
parser.add_argument('--data_case', type=str, default='test', 
                   help='train: Evaluate the acc/match_score metrics on the train dataset; test: Evaluate the acc/match_score metrics on the test dataset')
parser.add_argument('--data_aug', type=int, default=1, 
                   help='0: No data augmentation for fashion mnist; 1: Data augmentation for fashion mnist')

parser.add_argument('--methods', nargs='+', type=str, default=['erm', 'irm', 'csd', 'rand', 'perf', 'matchdg'], 
                    help='List of methods: erm, irm, csd, rand, approx_25, approx_50, approx_75, perf, matchdg')


parser.add_argument('--dp_noise', type=int, default=0, 
                    help='0: No DP noise; 1: Add DP noise')
parser.add_argument('--dp_epsilon', type=float, default=100.0, 
                    help='Epsilon value for Differential Privacy')
parser.add_argument('--dp_attach_opt', type=int, default=1, 
                    help='0: Infinite Epsilon; 1: Finite Epsilion')

args = parser.parse_args()


dataset= args.dataset
train_case= args.train_case
metric= args.metric
data_case= args.data_case
data_aug= args.data_aug
methods= args.methods

# test_diff, test_common
test_case=['test_diff']
    
if metric == 'train':
    if dataset in ['rot_mnist', 'rot_mnist_spur']:
        base_script= 'python train.py --dataset ' + str(dataset)
    elif dataset in ['fashion_mnist']:
        base_script= 'python train.py --dataset ' + str(dataset) + ' --mnist_aug ' + str(data_aug)
    res_dir= 'results/' + str(dataset) + '/train_logs' + '/'    

elif metric == 'mia':
    if dataset in ['rot_mnist', 'rot_mnist_spur']:
        base_script= 'python  test.py --test_metric mia --mia_logit 1 --mia_sample_size 2000 --batch_size 64 ' + ' --dataset ' + str(dataset)
        base_script= 'python  test.py --test_metric mia --mia_logit 1 --mia_sample_size 2000 --batch_size 64 ' + ' --dataset ' + str(dataset)

    res_dir= 'results/'+str(dataset)+'/privacy_clf/'

elif metric == 'privacy_entropy':
    if dataset in ['rot_mnist', 'rot_mnist_spur']:
        base_script= 'python  test.py --test_metric privacy_entropy --mia_sample_size 2000 --batch_size 64 ' + ' --dataset ' + str(dataset)
    elif dataset in ['fashion_mnist']:
        base_script= 'python  test.py --test_metric privacy_entropy --mia_sample_size 2000 --batch_size 64 ' + ' --dataset ' + str(dataset)

    res_dir= 'results/'+str(dataset)+'/privacy_entropy/'

elif metric == 'privacy_loss_attack':
    if dataset in ['rot_mnist', 'rot_mnist_spur']:
        base_script= 'python  test.py --test_metric privacy_loss_attack --mia_sample_size 2000 --batch_size 64 ' + ' --dataset ' + str(dataset)
    elif dataset in ['fashion_mnist']:
        base_script= 'python  test.py --test_metric privacy_loss_attack --mia_sample_size 2000 --batch_size 64 ' + ' --dataset ' + str(dataset)

    res_dir= 'results/'+str(dataset)+'/privacy_loss/'

elif metric == 'attribute_attack':
    base_script= 'python  test.py --test_metric attribute_attack --mia_logit 1 --batch_size 64 ' + ' --dataset ' + str(dataset) + ' --attribute_domain ' + data_case

    res_dir= 'results/'+str(dataset)+'/attribute_attack_' + data_case + '/'  

elif metric  == 'acc':
    base_script= 'python test.py --test_metric acc ' + ' --dataset ' + str(dataset) + ' --acc_data_case ' + data_case
    res_dir= 'results/' + str(dataset) + '/acc_' + str(data_case) + '/'

elif metric  == 'match_score':
    base_script= 'python test.py --test_metric match_score ' + ' --dataset ' + str(dataset) + ' --match_func_data_case ' + data_case
    res_dir= 'results/' + str(dataset) + '/match_score_' + data_case + '/'

elif metric  == 'feat_eval':
    base_script= 'python test.py --test_metric feat_eval ' + ' --dataset ' + str(dataset) + ' --match_func_data_case ' + data_case
    res_dir= 'results/' + str(dataset) + '/feat_eval_' + data_case + '/'

elif metric  == 'feat_eval_rand':
    base_script= 'python test.py --test_metric feat_eval ' + ' --dataset ' + str(dataset) + ' --match_func_data_case ' + data_case + ' --match_case 0.0 '
    res_dir= 'results/' + str(dataset) + '/feat_eval_rand_' + data_case + '/'
    
    
#Train Domains 30, 45 case
if train_case == 'train_abl_2':
    base_script+= ' --train_domains 30 45'
    res_dir= res_dir[:-1] +'_30_45/'

#Train Domains 30, 45, 60 case
if train_case == 'train_abl_3':
    base_script+= ' --train_domains 30 45 60'
    res_dir= res_dir[:-1] +'_30_45_60/'            

#Test on 30, 45 angles instead of the standard 0, 90
if test_case  == 'test_common':
    base_script += ' --test_domains 30 45'
    res_dir+= 'test_common_domains/'

    
#Differential Privacy
if args.dp_noise:
    base_script += ' --dp_noise ' + str(args.dp_noise) + ' --dp_epsilon ' + str(args.dp_epsilon) + ' --dp_attach_opt ' + str(args.dp_attach_opt) + ' ' 
    res_dir= res_dir[:-1] + '_epsilon_' + str(args.dp_epsilon) + '/'
    
if not os.path.exists(res_dir):
    os.makedirs(res_dir)        

#Dataset Specific Modification
if dataset == 'rot_mnist_spur':
    base_script+= ' --img_c 3 '        

for method in methods:
    case= res_dir + str(method)
    
    print('Metric', metric, 'Method: ', method, ' Train Domains: ', train_case)
 
    if method == 'erm':
        script= base_script + ' --method_name erm_match --penalty_ws 0.0 --match_case 0.0 --epochs 25 ' +  ' > ' + case + '.txt'           
        os.system(script)

    elif method == 'rand':
        if dataset == 'rot_mnist_spur':        
            script= base_script + ' --method_name erm_match --penalty_ws 10.0 --match_case 0.0 --epochs 25 '  +  ' > ' + case + '.txt'   
        else:
            script= base_script + ' --method_name erm_match --penalty_ws 0.1 --match_case 0.0 --epochs 25 ' +  ' > ' + case + '.txt'       
        os.system(script)

    elif method == 'approx_25':
        script= base_script + ' --method_name erm_match --penalty_ws 0.1 --match_case 0.25 --epochs 25 ' +  ' > ' + case + '.txt'
        os.system(script)

    elif method == 'approx_50':
        script= base_script + ' --method_name erm_match --penalty_ws 0.1 --match_case 0.50 --epochs 25 ' +  ' > ' + case + '.txt'
        os.system(script)

    elif method == 'approx_75':
        script= base_script + ' --method_name erm_match --penalty_ws 0.1 --match_case 0.75 --epochs 25 ' + ' > ' + case + '.txt'
        os.system(script)

    elif method == 'perf':
        if dataset == 'rot_mnist_spur':                   
            script= base_script + ' --method_name erm_match --penalty_ws 10.0 --match_case 1.0 --epochs 25 ' +  ' > ' + case + '.txt' 
        else:
            script= base_script + ' --method_name erm_match --penalty_ws 0.1 --match_case 1.0 --epochs 25 ' +  ' > ' + case + '.txt' 
        os.system(script)

    elif method == 'matchdg':
        if metric == 'train':
            script= base_script + ' --method_name matchdg_ctr --match_case 0.0 --match_flag 1 --epochs 50 --batch_size 64 --pos_metric cos  --match_func_aug_case 1 ' +  ' > ' + res_dir + 'matchdg_ctr' + '.txt'  
            os.system(script)
        
        script= base_script + ' --method_name matchdg_erm --penalty_ws 0.1 --match_case -1 --ctr_match_case 0.0 --ctr_match_flag 1 --ctr_match_interrupt 5 --ctr_model_name resnet18 --epochs 25 ' +  ' > ' + case + '.txt'           
        os.system(script)

    elif method == 'csd':
        script= base_script + ' --method_name csd --penalty_ws 0.0 --match_case 0.0 --rep_dim 512 --epochs 25 ' +  ' > ' + case + '.txt'
        os.system(script)

    elif method == 'irm':
        script= base_script + ' --method_name irm --match_case 0.0 --penalty_irm 1.0 --penalty_s 5 --epochs 25 ' + ' > ' + case + '.txt'
        os.system(script)
````

--- reproduce_scripts/pacs_run.py ---
````
import os
import sys

# Input Parsing
parser = argparse.ArgumentParser()
parser.add_argument('--method', type=str, default='hybrid', 
                    help='erm; rand; matchdg_ctr; matchdg_erm; hybrid')
parser.add_argument('--model', type=str, default='resnet18', 
                    help='alexnet; resnet18; resnet50')
args = parser.parse_args()

method= args.method
model= args.model
domains= ['photo', 'art_painting', 'cartoon', 'sketch']

if method == 'erm' or method == 'rand':
    base_script= 'python train.py --dataset pacs  --method_name erm_match --match_case 0.0 --test_metric acc --out_classes 7 --perfect_match 0 --img_c 3 --pre_trained 1 --epochs 50 --weight_decay 0.001 '

elif method == 'matchdg_ctr':
    base_script= 'python train.py --dataset pacs --method_name matchdg_ctr --match_case 0.0 --match_flag 1 --pos_metric cos --out_classes 7 --perfect_match 0 --img_c 3 --pre_trained 1 --epochs 50 --batch_size 32  --match_func_aug_case 1  '

elif method == 'matchdg_erm':
    base_script= 'python train.py --dataset pacs --method_name matchdg_erm --match_case -1 --ctr_match_case 0.0 --ctr_match_flag 1 --ctr_match_interrupt 5 --ctr_model_name resnet50 --out_classes 7 --perfect_match 0 --img_c 3 --pre_trained 1 --epochs 50 --weight_decay 0.001 '

elif method == 'hybrid':
    base_script= 'python train.py --dataset pacs --method_name hybrid --match_case -1 --ctr_match_case 0.0 --ctr_match_flag 1 --ctr_match_interrupt 5 --ctr_model_name resnet50 --out_classes 7 --perfect_match 0 --img_c 3 --pre_trained 1 --epochs 50 --weight_decay 0.001 '
    
    
for test_domain in domains:
    
    res_dir= 'results/pacs/logs/'+ test_domain + '/'
    if not os.path.exists(res_dir):
        os.makedirs(res_dir)
    
    train_domains=''
    for d in domains:
        if d != test_domain:
            train_domains+= str(d) + ' '
    print(train_domains)    
    
    if method == 'erm':        
        if model == 'resnet18':
            if test_domain == 'photo':
                lr= 0.001 
                penalty= 0.0
            elif test_domain == 'art_painting':
                lr= 0.01 
                penalty= 0.0
            elif test_domain == 'cartoon':
                lr= 0.01 
                penalty= 0.0
            elif test_domain == 'sketch':
                lr= 0.01 
                penalty= 0.0

        elif model == 'resnet50':
            if test_domain == 'photo':
                lr= 0.0005 
                penalty= 0.0
            elif test_domain == 'art_painting':
                lr= 0.01 
                penalty= 0.0
            elif test_domain == 'cartoon':
                lr= 0.01
                penalty= 0.0
            elif test_domain == 'sketch':
                lr= 0.01 
                penalty= 0.0

        elif model == 'alexnet':
            if test_domain == 'photo':
                lr= 0.0005 
                penalty= 0.0
            elif test_domain == 'art_painting':
                lr= 0.001 
                penalty= 0.0
            elif test_domain == 'cartoon':
                lr= 0.001
                penalty= 0.0
            elif test_domain == 'sketch':
                lr= 0.0005
                penalty= 0.0
                
    elif method == 'rand':        
        if model == 'resnet18':
            if test_domain == 'photo':
                lr= 0.001 
                penalty= 5.0
            elif test_domain == 'art_painting':
                lr= 0.01 
                penalty= 0.1
            elif test_domain == 'cartoon':
                lr= 0.001 
                penalty= 5.0
            elif test_domain == 'sketch':
                lr= 0.01 
                penalty= 0.5

        elif model == 'resnet50':
            if test_domain == 'photo':
                lr= 0.0005 
                penalty= 5.0
            elif test_domain == 'art_painting':
                lr= 0.01 
                penalty= 0.1
            elif test_domain == 'cartoon':
                lr= 0.01
                penalty= 0.01
            elif test_domain == 'sketch':
                lr= 0.01 
                penalty= 0.1            
                
        elif model == 'alexnet':
            if test_domain == 'photo':
                lr= 0.0005 
                penalty= 0.1
            elif test_domain == 'art_painting':
                lr= 0.001 
                penalty= 0.1
            elif test_domain == 'cartoon':
                lr= 0.001 
                penalty= 0.5
            elif test_domain == 'sketch':
                lr= 0.001 
                penalty= 0.5

    elif method == 'matchdg_erm':        
        if model == 'resnet18':
            if test_domain == 'photo':
                lr= 0.0005 
                penalty= 1.0
            elif test_domain == 'art_painting':
                lr= 0.001 
                penalty= 5.0
            elif test_domain == 'cartoon':
                lr= 0.001 
                penalty= 1.0
            elif test_domain == 'sketch':
                lr= 0.01 
                penalty= 0.5

        elif model == 'resnet50':
            if test_domain == 'photo':
                lr= 0.0005 
                penalty= 0.01
            elif test_domain == 'art_painting':
                lr= 0.001 
                penalty= 0.1
            elif test_domain == 'cartoon':
                lr= 0.001
                penalty= 0.01
            elif test_domain == 'sketch':
                lr= 0.0005
                penalty= 5.0    
                
        elif model == 'alexnet':
            if test_domain == 'photo':
                lr= 0.0005 
                penalty= 0.1
            elif test_domain == 'art_painting':
                lr= 0.001 
                penalty= 1.0
            elif test_domain == 'cartoon':
                lr= 0.001
                penalty= 1.0
            elif test_domain == 'sketch':
                lr= 0.001 
                penalty= 0.1

                
    elif method == 'hybrid':        
        if model == 'resnet18':
            if test_domain == 'photo':
                lr= 0.0005 
                penalty= 0.1
                penalty_aug= 0.1
            elif test_domain == 'art_painting':
                lr= 0.001 
                penalty= 0.01
                penalty_aug= 0.1
            elif test_domain == 'cartoon':
                lr= 0.001 
                penalty= 0.1
                penalty_aug= 0.1
            elif test_domain == 'sketch':
                lr= 0.01 
                penalty= 0.01
                penalty_aug= 0.1

        elif model == 'resnet50':
            if test_domain == 'photo':
                lr= 0.0005 
                penalty= 0.1
                penalty_aug= 0.1
            elif test_domain == 'art_painting':
                lr= 0.001 
                penalty= 0.01
                penalty_aug= 0.1
            elif test_domain == 'cartoon':
                lr= 0.0005
                penalty= 0.01
                penalty_aug= 0.1
            elif test_domain == 'sketch':
                lr= 0.001 
                penalty= 0.01
                penalty_aug= 0.1
                
        elif model == 'alexnet':
            if test_domain == 'photo':
                lr= 0.0005 
                penalty= 0.1
                penalty_aug= 0.1
            elif test_domain == 'art_painting':
                lr= 0.001 
                penalty= 0.01
                penalty_aug= 0.1
            elif test_domain == 'cartoon':
                lr= 0.001
                penalty= 0.01
                penalty_aug= 0.1
            elif test_domain == 'sketch':
                lr= 0.001 
                penalty= 0.01
                penalty_aug= 0.1
                
                
    if method == 'matchdg_ctr':
        script= base_script + ' --train_domains ' + train_domains + ' --test_domains ' + test_domain + ' --model_name ' + str(model)
    else:
        script= base_script + ' --train_domains ' + train_domains + ' --test_domains ' + test_domain + ' --lr ' + str(lr) + ' --penalty_ws ' + str(penalty) + ' --model_name ' + str(model)    
    
    #TODO: Add penalty_aug for hybrid method
    if method == 'hybrid':
        script= script + ' --penalty_aug ' + str(penalty_aug)
    
    #TOOD: Figure out the appropriate batch size
    if model == 'alexnet':
        script= script + ' --img_w 256 ' + ' --img_h 256 '
    
    save_dir= res_dir + str(method) + '_' + str(model) + '.txt'
    script= script + ' > ' + save_dir    
    os.system(script)
````

--- reproduce_scripts/reproduce_rmnist_domainbed.py ---
````
import os
import argparse

# Input Parsing
parser = argparse.ArgumentParser()
parser.add_argument('--methods', nargs='+', type=str, default=['rand', 'matchdg_ctr', 'matchdg_erm'], 
                    help='List of methods')

args = parser.parse_args()
methods= args.methods                    
domains= [0, 15, 30, 45, 60, 75]

for method in methods:
    
    if method == 'rand':
        base_script= 'python train.py --dataset rot_mnist --mnist_case domain_bed --method_name erm_match --perfect_match 0 --match_case 0.0 --penalty_ws 1.0 --epochs 25 --batch_size 128 --model_name domain_bed_mnist --img_h 28 --img_w 28 --total_matches_per_point 1000 '

    elif method == 'matchdg_ctr':
        base_script= 'python train.py --dataset rot_mnist --mnist_case domain_bed --method_name matchdg_ctr --perfect_match 0 --match_case 0.0 --match_flag 1 --epochs 50 --batch_size 512 --pos_metric cos --model_name domain_bed_mnist --img_h 28 --img_w 28 --match_func_aug_case 1 '

    elif method == 'matchdg_erm':
        base_script= 'python train.py --dataset rot_mnist --mnist_case domain_bed --method_name matchdg_erm --perfect_match 0 --match_case -1 --penalty_ws 1.0 --epochs 25 --batch_size 128 --ctr_match_case 0.0 --ctr_match_flag 1 --ctr_match_interrupt 5 --ctr_model_name domain_bed_mnist  --model_name domain_bed_mnist --img_h 28 --img_w 28 --total_matches_per_point 1000 '

    for test_domain in domains:

        train_domains=''
        for d in domains:
            if d != test_domain:
                train_domains+= str(d) + ' '
        print(train_domains)

        res_dir= 'results/rmnist_domain_bed/'
        if not os.path.exists(res_dir):
            os.makedirs(res_dir)

        script= base_script + ' --train_domains ' + str(train_domains) + ' --test_domains ' + str(test_domain) 
        script= script + ' > ' + res_dir + method + '_' + str(test_domain) + '.txt'

        print('Method: ', method, ' Test Domain: ', test_domain)
        os.system(script)
````

--- reproduce_scripts/reproduce_rmnist_lenet.py ---
````
import os
import argparse

# Input Parsing
parser = argparse.ArgumentParser()
parser.add_argument('--methods', nargs='+', type=str, default=['erm', 'rand', 'matchdg_ctr', 'matchdg_erm', 'perf'], 
                    help='List of methods')

args = parser.parse_args()
methods= args.methods                    
domains= [0, 15, 30, 45, 60, 75]

for method in methods:
                    
    if method == 'perf':
        base_script= 'python train.py --dataset rot_mnist --mnist_case lenet --method_name erm_match --match_case 1.0 --penalty_ws 1.0 --epochs 100 --model_name lenet --img_h 32 --img_w 32 '

    elif method == 'erm':
        base_script= 'python train.py --dataset rot_mnist --mnist_case lenet --method_name erm_match --match_case 0.0 --penalty_ws 0.0 --epochs 100 --model_name lenet --img_h 32 --img_w 32 '

    elif method == 'rand':
        base_script= 'python train.py --dataset rot_mnist --mnist_case lenet --method_name erm_match --match_case 0.0 --penalty_ws 1.0 --epochs 100 --model_name lenet --img_h 32 --img_w 32 --total_matches_per_point 100 '

    elif method == 'matchdg_ctr':
        base_script= 'python train.py --dataset rot_mnist --mnist_case lenet --method_name matchdg_ctr --match_case 0.0 --match_flag 1 --epochs 50 --batch_size 512 --pos_metric cos --model_name lenet --img_h 32 --img_w 32 --match_func_aug_case 1 '

    elif method == 'matchdg_erm':
        base_script= 'python train.py --dataset rot_mnist --mnist_case lenet --method_name matchdg_erm --match_case -1 --penalty_ws 1.0 --epochs 100 --ctr_match_case 0.0 --ctr_match_flag 1 --ctr_match_interrupt 5 --ctr_model_name lenet  --model_name lenet --img_h 32 --img_w 32 --total_matches_per_point 100 '

    for test_domain in domains:

        train_domains=''
        for d in domains:
            if d != test_domain:
                train_domains+= str(d) + ' '
        print(train_domains)

        res_dir= 'results/rmnist_lenet/'
        if not os.path.exists(res_dir):
            os.makedirs(res_dir)

        script= base_script + ' --train_domains ' + str(train_domains) + ' --test_domains ' + str(test_domain) 
        script= script + ' > ' + res_dir + method + '_' + str(test_domain) + '.txt'

        print('Method: ', method, ' Test Domain: ', test_domain)
        os.system(script)
````

--- reproduce_scripts/reproduce_slab.py ---
````
import os
import sys

'''
argv1: Allowed Values (train, evaluate)
'''

case= sys.argv[1]
methods=['erm', 'mmd', 'coral', 'dann', 'c-mmd', 'c-coral', 'c-dann', 'rand', 'perf']
total_seed= 10

if case == 'train':
    base_script= 'python train.py --dataset slab --model_name slab --batch_size 128 --lr 0.1 --epochs 100 --out_classes 2 --train_domains 0.0 0.10 --test_domains 1.0 --slab_data_dim 2 --slab_noise 0.1 ' + ' --n_runs ' + str(total_seed)

elif case == 'evaluate':
    base_script= 'python test.py --test_metric per_domain_acc --acc_data_case train --dataset slab --model_name slab --batch_size 128 --lr 0.1 --epochs 100 --out_classes 2 --train_domains 0.0 0.10 --test_domains 1.0 --slab_data_dim 2 --slab_noise 0.1 ' + ' --n_runs ' + str(total_seed)

    
res_dir= 'results/slab/logs/'
if not os.path.exists(res_dir):
    os.makedirs(res_dir)


for method in methods:
    
    if method == 'mmd':
        script= base_script + ' --method_name mmd --gaussian 1 --conditional 0 --penalty_ws 0.1 '

    elif method == 'c-mmd':
        script= base_script + ' --method_name mmd --gaussian 1 --conditional 1 --penalty_ws 0.1 '

    elif method == 'coral':
        script= base_script + ' --method_name mmd --gaussian 0 --conditional 0  --penalty_ws 0.1 '

    elif method == 'c-coral':    
        script= base_script + ' --method_name mmd --gaussian 0 --conditional 1  --penalty_ws 0.1 '

    elif method == 'dann':
        script= base_script + ' --method_name dann --conditional 0 --penalty_ws 0.01 --grad_penalty 0.1 --d_steps_per_g_step 4 '

    elif method == 'c-dann':
        script= base_script + ' --method_name dann --conditional 1 --penalty_ws 0.01 --grad_penalty 1.0 --d_steps_per_g_step 2 '

    elif method == 'erm':
        script= base_script + ' --method_name erm_match --match_case 0.0 --penalty_ws 0.0 '

    elif method == 'rand':
        script= base_script + ' --method_name erm_match --match_case 0.0 --penalty_ws 1.0 '

    elif method == 'perf':
        script= base_script + ' --method_name erm_match --match_case 1.0 --penalty_ws 1.0 '

    script= script + ' > ' + res_dir + str(method) + '.txt'
    os.system(script)
````

--- reproduce_scripts/slab-plot.py ---
````
import matplotlib
import matplotlib.pyplot as plt
import sys
import os
import numpy as np

slab_noise= float(sys.argv[1])
base_dir= 'results/slab/slab_noise_' + str(slab_noise) + '/'
methods=['erm', 'irm', 'csd', 'rand', 'perf', 'mask_linear']

# x=['ERM', 'IRM', 'CSD', 'Rand', 'MatchDG', 'Perf', 'Mask']
x=['ERM', 'IRM', 'CSD', 'Rand', 'Perf', 'Oracle']
matplotlib.rcParams.update({'errorbar.capsize': 2})
fig, ax = plt.subplots(1, 2, figsize=(24, 8))
fontsize=40
fontsize_lgd= fontsize/1.2
marker_list = ['o', '^', '*']
count= 0

for test_domain in [0.2, 0.9]:
        
    acc=[]
    acc_err=[]
    train_acc =[]
    train_acc_err =[]
    auc=[]
    auc_err=[]
    s_auc=[]
    s_auc_err=[]
    sc_auc=[]
    sc_auc_err=[]

    for method in methods:

        f= open(base_dir + method + '-auc-' + str(test_domain) + '.txt')
        data= f.readlines()
        acc.append( float( data[-4].replace('\n', '').split(' ')[-2] ))
        acc_err.append( float( data[-4].replace('\n', '').split(' ')[-1] ))
        auc.append( float( data[-3].replace('\n', '').split(' ')[-2] ))
        auc_err.append( float( data[-3].replace('\n', '').split(' ')[-1] ))
        s_auc.append( float( data[-2].replace('\n', '').split(' ')[-2] ))
        s_auc_err.append( float( data[-2].replace('\n', '').split(' ')[-1] ))
        sc_auc.append( float(data[-1].replace('\n', '').split(' ')[-2] ))
        sc_auc_err.append( float( data[-1].replace('\n', '').split(' ')[-1] ) )

        f= open(base_dir + method + '-train-auc-' + str(test_domain) + '.txt')
        data= f.readlines()
        train_acc.append( float( data[-4].replace('\n', '').split(' ')[-2] ))
        train_acc_err.append( float( data[-4].replace('\n', '').split(' ')[-1] ))
        
        
    #Privacy Metrics
    mia=[]
    mia_err=[]
    entropy=[]
    entropy_err=[]
    loss=[]
    loss_err=[]
    attribute=[]
    attribute_err=[]

        
    # eval_metrics= ['mi', 'entropy', 'loss', 'attribute']
    eval_metrics= ['loss']
    for metric in eval_metrics:
        for method in methods:
            f= open(base_dir+method+'-'+metric+ '-' + str(test_domain)+'.txt')
            data= f.readlines()

            mean= float(data[-3].replace('\n', '').split(' ')[-2])
            sd= float(data[-3].replace('\n', '').split(' ')[-1])

            if metric == 'mi':
                mia.append(mean)
                mia_err.append(sd)
            elif metric == 'entropy':
                entropy.append(mean)
                entropy_err.append(sd)
            elif metric == 'loss':
                loss.append(mean)
                loss_err.append(sd)
            elif metric == 'attribute':
                attribute.append(mean)
                attribute_err.append(sd)
    
    ax[count].tick_params(labelsize=fontsize)
    ax[count].set_xticklabels(x, rotation=25)
    
    ax[count].errorbar(x, acc, yerr=acc_err, marker= marker_list[0], markersize= fontsize_lgd, linewidth=4, fmt='o--', label='OOD Acc')
    ax[count].errorbar(x, s_auc, yerr=s_auc_err, marker= marker_list[1], markersize= fontsize_lgd, linewidth=4, fmt='o--', label='Stable Features (Linear-RAUC)')
    ax[count].errorbar(x, loss, yerr=loss_err, marker= marker_list[2], markersize= fontsize_lgd, linewidth=4, label='MI Attack Acc', fmt='o--')
    
#     gen_gap= np.array(train_acc) - np.array(acc)
#     ax[count].errorbar(x, gen_gap, yerr=0*gen_gap, marker= 's', markersize= fontsize_lgd, linewidth=4, fmt='o--', label='Generalization Gap')
    
    ax[count].set_ylabel('Metric Score', fontsize=fontsize)
    ax[count].set_title('Test Domain: ' + str(test_domain), fontsize=fontsize)
    
    count+=1
    
lines, labels = fig.axes[-1].get_legend_handles_labels()    
lgd= fig.legend(lines, labels, loc="lower center", bbox_to_anchor=(0.5, -0.15), fontsize=fontsize, ncol=4)

save_dir= 'results/slab/plots/'
if not os.path.exists(save_dir):
    os.makedirs(save_dir)

plt.tight_layout()
plt.savefig( save_dir + 'privacy_slab_' + str(slab_noise) + '.pdf', bbox_extra_artists=(lgd,), bbox_inches='tight',  dpi=600)
````

--- reproduce_scripts/slab-run.py ---
````
import os
import sys
import argparse

# Input Parsing
parser = argparse.ArgumentParser()
parser.add_argument('--case', type=str, default='train', 
                    help='Case: train; test')
parser.add_argument('--slab_noise', type=float, default=0.0, 
                    help='Probability of corrupting slab features')
parser.add_argument('--methods', nargs='+', type=str, default=['erm', 'irm', 'csd', 'rand', 'matchdg', 'perf', 'mask_linear'],
                    help='List of methods')

args = parser.parse_args()

case= args.case
slab_noise= args.slab_noise
methods= args.methods

metrics= ['train-auc', 'auc', 'loss']
total_seed= 3

if case == 'train':
    
    base_script= 'python train.py --dataset slab --model_name slab --batch_size 128 --lr 0.1 --epochs 100 --out_classes 2 --train_domains 0.0 0.10 --test_domains 0.90 --slab_data_dim 2 '
    
    base_script= base_script + ' --slab_noise ' + str(slab_noise) +  ' --n_runs ' + str(total_seed)    

    for method in methods:

        if method == 'erm':
            script= base_script + ' --method_name erm_match --match_case 0.0 --penalty_ws 0.0 '
        elif method == 'irm':
            script= base_script + ' --method_name irm --match_case 0.0 --penalty_irm 10.0 --penalty_s 2 '
        elif method == 'csd':
            script= base_script + ' --method_name csd --match_case 0.0 --penalty_ws 0.0 --rep_dim 100 '
        elif method == 'rand':
            script= base_script + ' --method_name erm_match --match_case 0.0 --penalty_ws 1.0  '
        elif method == 'perf':
            script= base_script + ' --method_name erm_match --match_case 1.0 --penalty_ws 1.0 '        
        elif method == 'mask_linear':
            script= base_script + ' --method_name mask_linear --match_case 0.0 --penalty_ws 0.0 '
        elif method == 'matchdg':
            #CTR Phase
            script = base_script + ' --method_name matchdg_ctr --batch_size 512 --match_case 0.0 --match_flag 1 --match_interrupt 5 --pos_metric cos '
            os.system(script)
            
            #ERM Phase
            script = base_script + ' --method_name matchdg_erm --match_case -1 --penalty_ws 1.0 --ctr_match_case 0.0 --ctr_match_flag 1 --ctr_match_interrupt 5 --ctr_model_name slab '            
            
        os.system(script)
        
elif case == 'test':    

    for metric in metrics:

        if metric == 'auc':
            base_script= 'python test_slab.py --train_domains 0.0 0.10 '

        if metric == 'train-auc':
            base_script= 'python test_slab.py --train_domains 0.0 0.10 --acc_data_case train '            
        elif metric == 'mi':
            base_script= 'python  test.py --test_metric mia --mia_logit 1 --mia_sample_size 400 --dataset slab --model_name slab --out_classes 2 --train_domains 0.0 0.10 '
        elif metric == 'entropy':
            base_script= 'python  test.py --test_metric privacy_entropy --mia_sample_size 400 --dataset slab --model_name slab --out_classes 2 --train_domains 0.0 0.10 '
        elif metric == 'loss':
            base_script= 'python  test.py --test_metric privacy_loss_attack --mia_sample_size 400 --dataset slab --model_name slab --out_classes 2 --train_domains 0.0 0.10 '
        elif metric == 'attribute':
            base_script= 'python  test.py --test_metric attribute_attack --mia_logit 1 --attribute_domain 0 --dataset slab --model_name slab --out_classes 2 --train_domains 0.0 0.10 '           

        base_script= base_script + ' --slab_noise ' + str(slab_noise) + ' --n_runs ' + str(total_seed)
        res_dir= 'results/slab/slab_noise_' + str(slab_noise) + '/'

        if not os.path.exists(res_dir):
            os.makedirs(res_dir)
            
        for method in methods:

            if method == 'erm':
                upd_script= base_script + ' --method_name erm_match --match_case 0.0 --penalty_ws 0.0 '
            elif method == 'irm':
                upd_script= base_script + ' --method_name irm --match_case 0.0 --penalty_irm 10.0 --penalty_s 2 '
            elif method == 'csd':
                upd_script= base_script + ' --method_name csd --match_case 0.0 --penalty_ws 0.0 --rep_dim 100 '
            elif method == 'rand':
                upd_script= base_script + ' --method_name erm_match --match_case 0.0 --penalty_ws 1.0  '
            elif method == 'perf':
                upd_script= base_script + ' --method_name erm_match --match_case 1.0 --penalty_ws 1.0 '        
            elif method == 'mask_linear':
                upd_script= base_script + ' --method_name mask_linear --match_case 0.0 --penalty_ws 0.0 '
                
            elif method == 'matchdg':
                upd_script = base_script + ' --method_name matchdg_erm --match_case -1 --penalty_ws 1.0 --ctr_match_case 0.0 --ctr_match_flag 1 --ctr_match_interrupt 5 --ctr_model_name slab '                
                
            for test_domain in [0.2, 0.9]:
                script= upd_script + ' --test_domains ' + str(test_domain) + ' > ' + res_dir + str(method) + '-' + str(metric) + '-' + str(test_domain) + '.txt'
                os.system(script)
````

--- reproduce_scripts/slab-tune.py ---
````
import os
import sys

'''
argv1: Method for which HParams need to be tuned (erm, rand, perf, mmd, coral, c-mmd, c-coral, dann, c-dann)
'''
method= sys.argv[1]
total_seed= 3

base_script= 'python train.py --dataset slab --model_name slab --batch_size 128 --lr 0.1 --epochs 100 --out_classes 2 --train_domains 0.0 0.10 --test_domains 1.0 --slab_data_dim 2 --slab_noise 0.1 ' + ' --n_runs ' + str(total_seed)

res_dir= 'results/slab/htune/'
if not os.path.exists(res_dir):
    os.makedirs(res_dir)

if method == 'mmd':
    base_script= base_script + ' --method_name mmd --gaussian 1 --conditional 0 '

elif method == 'c-mmd':
    base_script= base_script + ' --method_name mmd --gaussian 1 --conditional 1 '

elif method == 'coral':
    base_script= base_script + ' --method_name mmd --gaussian 0 --conditional 0 '
    
elif method == 'c-coral':    
    base_script= base_script + ' --method_name mmd --gaussian 0 --conditional 1 '

elif method == 'dann':
    base_script= base_script + ' --method_name dann --conditional 0 '

elif method == 'c-dann':
    base_script= base_script + ' --method_name dann --conditional 1 '

elif method == 'erm':
    script= base_script + ' --method_name erm_match --match_case 0.0 '
    
elif method == 'rand':
    script= base_script + ' --method_name erm_match --match_case 0.0 '
    
elif method == 'perf':
    script= base_script + ' --method_name erm_match --match_case 1.0 '
    
    
if method in ['erm']:
    penalty_glist= [0.0]    
elif method in ['rand', 'perf', 'mmd', 'coral', 'c-mmd', 'c-coral']:    
    penalty_glist= [0.1, 1.0, 10.0]    
elif method in ['dann', 'c-dann']:
    penalty_glist= [0.01, 0.1, 1.0, 10.0, 100.0]    

grad_penalty_glist= [0.01, 0.1, 1.0, 10.0]
disc_steps_glist= [1, 2, 4, 8]

# Train for different hyper configurations
if method in ['dann', 'c-dann']:    
    for penalty in penalty_glist:
        for grad_penalty in grad_penalty_glist:
            for disc_steps in disc_steps_glist:
                script= base_script + ' --penalty_ws ' + str(penalty) + ' --grad_penalty ' + str(grad_penalty) + ' --d_steps_per_g_step ' + str(disc_steps) 
                script= script + ' > ' + res_dir + str(method) + '_' + str(penalty) + '_' + str(grad_penalty) + '_' + str(disc_steps) + '.txt'
                os.system(script)

else:
    for penalty in penalty_glist:
        script= base_script + ' --penalty_ws ' + str(penalty) 
        script= script + ' > ' + res_dir + str(method) + '_' + str(penalty) + '.txt'
        os.system(script)

# Search over different hyper configurations and infer the best values
    
best_acc= -1
best_err= -1
best_case= ''

if method in ['dann', 'c-dann']:    
    for penalty in penalty_glist:
        for grad_penalty in grad_penalty_glist:
            for disc_steps in disc_steps_glist:
                f_name= res_dir + str(method) + '_' + str(penalty) + '_' + str(grad_penalty) + '_' + str(disc_steps) + '.txt'
                f= open(f_name)
                data= f.readlines()
                # Source validation accuracy
                mean= float(data[-4].replace('\n', '').split(' ')[-2])
                err= float(data[-4].replace('\n', '').split(' ')[-1])
                if mean > best_acc:
                    best_acc= mean
                    best_err= err
                    best_case= f_name
else:
    for penalty in penalty_glist:
        f_name= res_dir + str(method) + '_' + str(penalty) + '.txt'
        f= open(f_name)
        data= f.readlines()
        # Source validation accuracy
        mean= float(data[-4].replace('\n', '').split(' ')[-2])
        err= float(data[-4].replace('\n', '').split(' ')[-1])
        if mean > best_acc:
            best_acc= mean
            best_err= err
            best_case= f_name

print('Best Hparam for method: ', method, best_case)
print('Best Accuracy: ', best_acc, best_err)
````

`--help` of the scripts these commands run (run by code in the repository's environment):
--- python data/data_gen_mnist.py --help ---
```
usage: data_gen_mnist.py [-h] [--dataset DATASET] [--model MODEL]
                         [--data_size DATA_SIZE] [--subset_size SUBSET_SIZE]
                         [--img_w IMG_W] [--img_h IMG_H]
                         [--cmnist_permute CMNIST_PERMUTE]

optional arguments:
  -h, --help            show this help message and exit
  --dataset DATASET     Datasets: rot_mnist; fashion_mnist; rot_mnist_spur
  --model MODEL         Base Models: resnet18; lenet
  --data_size DATA_SIZE
  --subset_size SUBSET_SIZE
  --img_w IMG_W
  --img_h IMG_H
  --cmnist_permute CMNIST_PERMUTE
```

--- python train.py --help ---
(`python train.py --help` fails at this commit with TypeError: %c requires int or char: a help string has an unescaped %. Below is the same parser's help with those % signs escaped by code.)
```
usage: train.py [-h] [--dataset_name DATASET_NAME] [--method_name METHOD_NAME]
                [--model_name MODEL_NAME]
                [--train_domains TRAIN_DOMAINS [TRAIN_DOMAINS ...]]
                [--test_domains TEST_DOMAINS [TEST_DOMAINS ...]]
                [--out_classes OUT_CLASSES] [--img_c IMG_C] [--img_h IMG_H]
                [--img_w IMG_W] [--fc_layer FC_LAYER]
                [--match_layer MATCH_LAYER] [--pos_metric POS_METRIC]
                [--rep_dim REP_DIM] [--pre_trained PRE_TRAINED]
                [--perfect_match PERFECT_MATCH] [--opt OPT]
                [--weight_decay WEIGHT_DECAY] [--lr LR]
                [--batch_size BATCH_SIZE] [--epochs EPOCHS]
                [--penalty_s PENALTY_S] [--penalty_irm PENALTY_IRM]
                [--penalty_aug PENALTY_AUG] [--penalty_ws PENALTY_WS]
                [--penalty_diff_ctr PENALTY_DIFF_CTR] [--tau TAU]
                [--match_flag MATCH_FLAG] [--match_case MATCH_CASE]
                [--match_interrupt MATCH_INTERRUPT] [--ctr_abl CTR_ABL]
                [--match_abl MATCH_ABL] [--n_runs N_RUNS]
                [--n_runs_matchdg_erm N_RUNS_MATCHDG_ERM]
                [--ctr_model_name CTR_MODEL_NAME]
                [--ctr_match_layer CTR_MATCH_LAYER]
                [--ctr_match_flag CTR_MATCH_FLAG]
                [--ctr_match_case CTR_MATCH_CASE]
                [--ctr_match_interrupt CTR_MATCH_INTERRUPT]
                [--mnist_seed MNIST_SEED] [--retain RETAIN]
                [--cuda_device CUDA_DEVICE] [--os_env OS_ENV]
                [--dp_noise DP_NOISE] [--dp_epsilon DP_EPSILON]
                [--dp_attach_opt DP_ATTACH_OPT]
                [--d_steps_per_g_step D_STEPS_PER_G_STEP]
                [--grad_penalty GRAD_PENALTY] [--conditional CONDITIONAL]
                [--gaussian GAUSSIAN] [--slab_data_dim SLAB_DATA_DIM]
                [--slab_total_slabs SLAB_TOTAL_SLABS]
                [--slab_num_samples SLAB_NUM_SAMPLES]
                [--slab_noise SLAB_NOISE] [--mnist_case MNIST_CASE]
                [--mnist_aug MNIST_AUG]
                [--total_matches_per_point TOTAL_MATCHES_PER_POINT]
                [--test_metric TEST_METRIC] [--acc_data_case ACC_DATA_CASE]
                [--top_k TOP_K] [--match_func_aug_case MATCH_FUNC_AUG_CASE]
                [--match_func_data_case MATCH_FUNC_DATA_CASE]

optional arguments:
  -h, --help            show this help message and exit
  --dataset_name DATASET_NAME
                        Datasets: rot_mnist; fashion_mnist; pacs
  --method_name METHOD_NAME
                        Training Algorithm: erm_match; matchdg_ctr;
                        matchdg_erm
  --model_name MODEL_NAME
                        Architecture of the model to be trained
  --train_domains TRAIN_DOMAINS [TRAIN_DOMAINS ...]
                        List of train domains
  --test_domains TEST_DOMAINS [TEST_DOMAINS ...]
                        List of test domains
  --out_classes OUT_CLASSES
                        Total number of classes in the dataset
  --img_c IMG_C         Number of channels of the image in dataset
  --img_h IMG_H         Height of the image in dataset
  --img_w IMG_W         Width of the image in dataset
  --fc_layer FC_LAYER   ResNet architecture customization; 0: No fc_layer with
                        resnet; 1: fc_layer for classification with resnet
  --match_layer MATCH_LAYER
                        rep_match: Matching at an intermediate representation
                        level; logit_match: Matching at the logit level
  --pos_metric POS_METRIC
                        Cost to function to evaluate distance between two
                        representations; Options: l1; l2; cos
  --rep_dim REP_DIM     Representation dimension for contrsative learning
  --pre_trained PRE_TRAINED
                        0: No Pretrained Architecture; 1: Pretrained
                        Architecture
  --perfect_match PERFECT_MATCH
                        0: No perfect match known (PACS); 1: perfect match
                        known (MNIST)
  --opt OPT             Optimizer Choice: sgd; adam
  --weight_decay WEIGHT_DECAY
                        Weight Decay in SGD
  --lr LR               Learning rate for training the model
  --batch_size BATCH_SIZE
                        Batch size foe training the model
  --epochs EPOCHS       Total number of epochs for training the model
  --penalty_s PENALTY_S
                        Epoch threshold over which Matching Loss to be
                        optimised
  --penalty_irm PENALTY_IRM
                        Penalty weight for IRM invariant classifier loss
  --penalty_aug PENALTY_AUG
                        Penalty weight for Augmentation in Hybrid approach
                        loss
  --penalty_ws PENALTY_WS
                        Penalty weight for Matching Loss
  --penalty_diff_ctr PENALTY_DIFF_CTR
                        Penalty weight for Contrastive Loss
  --tau TAU             Temperature hyper param for NTXent contrastive loss
  --match_flag MATCH_FLAG
                        0: No Update to Match Strategy; 1: Updates to Match
                        Strategy
  --match_case MATCH_CASE
                        0: Random Match; 1: Perfect Match. 0.x" x% correct
                        Match
  --match_interrupt MATCH_INTERRUPT
                        Number of epochs before inferring the match strategy
  --ctr_abl CTR_ABL     0: Randomization til class level ; 1: Randomization
                        completely
  --match_abl MATCH_ABL
                        0: Randomization til class level ; 1: Randomization
                        completely
  --n_runs N_RUNS       Number of iterations to repeat the training process
  --n_runs_matchdg_erm N_RUNS_MATCHDG_ERM
                        Number of iterations to repeat training process for
                        matchdg_erm
  --ctr_model_name CTR_MODEL_NAME
                        (For matchdg_ctr phase) Architecture of the model to
                        be trained
  --ctr_match_layer CTR_MATCH_LAYER
                        (For matchdg_ctr phase) rep_match: Matching at an
                        intermediate representation level; logit_match:
                        Matching at the logit level
  --ctr_match_flag CTR_MATCH_FLAG
                        (For matchdg_ctr phase) 0: No Update to Match
                        Strategy; 1: Updates to Match Strategy
  --ctr_match_case CTR_MATCH_CASE
                        (For matchdg_ctr phase) 0: Random Match; 1: Perfect
                        Match. 0.x" x% correct Match
  --ctr_match_interrupt CTR_MATCH_INTERRUPT
                        (For matchdg_ctr phase) Number of epochs before
                        inferring the match strategy
  --mnist_seed MNIST_SEED
                        Change it between 0-6 for different subsets of Mnist
                        and Fashion Mnist dataset
  --retain RETAIN       0: Train from scratch in MatchDG Phase 2; 2: Finetune
                        from MatchDG Phase 1 in MatchDG is Phase 2
  --cuda_device CUDA_DEVICE
                        Select the cuda device by id among the avaliable
                        devices
  --os_env OS_ENV       0: Code execution on local server/machine; 1: Code
                        execution in docker/clusters
  --dp_noise DP_NOISE   0: No DP noise; 1: Add DP noise
  --dp_epsilon DP_EPSILON
                        Epsilon value for Differential Privacy
  --dp_attach_opt DP_ATTACH_OPT
                        0: Infinite Epsilon; 1: Finite Epsilion
  --d_steps_per_g_step D_STEPS_PER_G_STEP
  --grad_penalty GRAD_PENALTY
  --conditional CONDITIONAL
  --gaussian GAUSSIAN
  --slab_data_dim SLAB_DATA_DIM
                        Number of features in the slab dataset
  --slab_total_slabs SLAB_TOTAL_SLABS
  --slab_num_samples SLAB_NUM_SAMPLES
  --slab_noise SLAB_NOISE
  --mnist_case MNIST_CASE
                        MNIST Dataset Case: resnet18; lenet, domainbed
  --mnist_aug MNIST_AUG
                        MNIST Data Augmentation: 0 (MNIST, FMNIST Privacy
                        Evaluation); 1 (FMNIST)
  --total_matches_per_point TOTAL_MATCHES_PER_POINT
                        Multiple random matches
  --test_metric TEST_METRIC
                        Evaluation Metrics: acc; match_score, t_sne, mia
  --acc_data_case ACC_DATA_CASE
                        Dataset Train/Val/Test for the accuracy evaluation
                        metric
  --top_k TOP_K         Top K matches to consider for the match score
                        evaluation metric
  --match_func_aug_case MATCH_FUNC_AUG_CASE
                        0: Evaluate match func on train domains; 1: Evaluate
                        match func on self augmentations
  --match_func_data_case MATCH_FUNC_DATA_CASE
                        Dataset Train/Val/Test for the match score evaluation
                        metric
```

--- python test.py --help ---
(`python test.py --help` fails at this commit with TypeError: %c requires int or char: a help string has an unescaped %. Below is the same parser's help with those % signs escaped by code.)
```
usage: test.py [-h] [--dataset_name DATASET_NAME] [--method_name METHOD_NAME]
               [--model_name MODEL_NAME]
               [--train_domains TRAIN_DOMAINS [TRAIN_DOMAINS ...]]
               [--test_domains TEST_DOMAINS [TEST_DOMAINS ...]]
               [--out_classes OUT_CLASSES] [--img_c IMG_C] [--img_h IMG_H]
               [--img_w IMG_W] [--fc_layer FC_LAYER]
               [--match_layer MATCH_LAYER] [--pos_metric POS_METRIC]
               [--rep_dim REP_DIM] [--pre_trained PRE_TRAINED]
               [--perfect_match PERFECT_MATCH] [--opt OPT]
               [--weight_decay WEIGHT_DECAY] [--lr LR]
               [--batch_size BATCH_SIZE] [--epochs EPOCHS]
               [--penalty_s PENALTY_S] [--penalty_irm PENALTY_IRM]
               [--penalty_aug PENALTY_AUG] [--penalty_ws PENALTY_WS]
               [--penalty_diff_ctr PENALTY_DIFF_CTR] [--tau TAU]
               [--match_flag MATCH_FLAG] [--match_case MATCH_CASE]
               [--match_interrupt MATCH_INTERRUPT] [--ctr_abl CTR_ABL]
               [--match_abl MATCH_ABL] [--n_runs N_RUNS]
               [--n_runs_matchdg_erm N_RUNS_MATCHDG_ERM]
               [--ctr_model_name CTR_MODEL_NAME]
               [--ctr_match_layer CTR_MATCH_LAYER]
               [--ctr_match_flag CTR_MATCH_FLAG]
               [--ctr_match_case CTR_MATCH_CASE]
               [--ctr_match_interrupt CTR_MATCH_INTERRUPT]
               [--mnist_seed MNIST_SEED] [--retain RETAIN]
               [--cuda_device CUDA_DEVICE] [--os_env OS_ENV]
               [--dp_noise DP_NOISE] [--dp_epsilon DP_EPSILON]
               [--dp_attach_opt DP_ATTACH_OPT]
               [--d_steps_per_g_step D_STEPS_PER_G_STEP]
               [--grad_penalty GRAD_PENALTY] [--conditional CONDITIONAL]
               [--gaussian GAUSSIAN] [--slab_data_dim SLAB_DATA_DIM]
               [--slab_total_slabs SLAB_TOTAL_SLABS]
               [--slab_num_samples SLAB_NUM_SAMPLES] [--slab_noise SLAB_NOISE]
               [--mnist_case MNIST_CASE] [--mnist_aug MNIST_AUG]
               [--total_matches_per_point TOTAL_MATCHES_PER_POINT]
               [--test_metric TEST_METRIC] [--acc_data_case ACC_DATA_CASE]
               [--top_k TOP_K] [--match_func_aug_case MATCH_FUNC_AUG_CASE]
               [--match_func_data_case MATCH_FUNC_DATA_CASE]
               [--mia_batch_size MIA_BATCH_SIZE]
               [--mia_dnn_steps MIA_DNN_STEPS]
               [--mia_sample_size MIA_SAMPLE_SIZE] [--mia_logit MIA_LOGIT]
               [--attribute_domain ATTRIBUTE_DOMAIN] [--adv_eps ADV_EPS]
               [--logit_plot_path LOGIT_PLOT_PATH]

optional arguments:
  -h, --help            show this help message and exit
  --dataset_name DATASET_NAME
                        Datasets: rot_mnist; fashion_mnist; pacs
  --method_name METHOD_NAME
                        Training Algorithm: erm_match; matchdg_ctr;
                        matchdg_erm
  --model_name MODEL_NAME
                        Architecture of the model to be trained
  --train_domains TRAIN_DOMAINS [TRAIN_DOMAINS ...]
                        List of train domains
  --test_domains TEST_DOMAINS [TEST_DOMAINS ...]
                        List of test domains
  --out_classes OUT_CLASSES
                        Total number of classes in the dataset
  --img_c IMG_C         Number of channels of the image in dataset
  --img_h IMG_H         Height of the image in dataset
  --img_w IMG_W         Width of the image in dataset
  --fc_layer FC_LAYER   ResNet architecture customization; 0: No fc_layer with
                        resnet; 1: fc_layer for classification with resnet
  --match_layer MATCH_LAYER
                        rep_match: Matching at an intermediate representation
                        level; logit_match: Matching at the logit level
  --pos_metric POS_METRIC
                        Cost to function to evaluate distance between two
                        representations; Options: l1; l2; cos
  --rep_dim REP_DIM     Representation dimension for contrsative learning
  --pre_trained PRE_TRAINED
                        0: No Pretrained Architecture; 1: Pretrained
                        Architecture
  --perfect_match PERFECT_MATCH
                        0: No perfect match known (PACS); 1: perfect match
                        known (MNIST)
  --opt OPT             Optimizer Choice: sgd; adam
  --weight_decay WEIGHT_DECAY
                        Weight Decay in SGD
  --lr LR               Learning rate for training the model
  --batch_size BATCH_SIZE
                        Batch size foe training the model
  --epochs EPOCHS       Total number of epochs for training the model
  --penalty_s PENALTY_S
                        Epoch threshold over which Matching Loss to be
                        optimised
  --penalty_irm PENALTY_IRM
                        Penalty weight for IRM invariant classifier loss
  --penalty_aug PENALTY_AUG
                        Penalty weight for Augmentation in Hybrid approach
                        loss
  --penalty_ws PENALTY_WS
                        Penalty weight for Matching Loss
  --penalty_diff_ctr PENALTY_DIFF_CTR
                        Penalty weight for Contrastive Loss
  --tau TAU             Temperature hyper param for NTXent contrastive loss
  --match_flag MATCH_FLAG
                        0: No Update to Match Strategy; 1: Updates to Match
                        Strategy
  --match_case MATCH_CASE
                        0: Random Match; 1: Perfect Match. 0.x" x% correct
                        Match
  --match_interrupt MATCH_INTERRUPT
                        Number of epochs before inferring the match strategy
  --ctr_abl CTR_ABL     0: Randomization til class level ; 1: Randomization
                        completely
  --match_abl MATCH_ABL
                        0: Randomization til class level ; 1: Randomization
                        completely
  --n_runs N_RUNS       Number of iterations to repeat the training process
  --n_runs_matchdg_erm N_RUNS_MATCHDG_ERM
                        Number of iterations to repeat training process for
                        matchdg_erm
  --ctr_model_name CTR_MODEL_NAME
                        (For matchdg_ctr phase) Architecture of the model to
                        be trained
  --ctr_match_layer CTR_MATCH_LAYER
                        (For matchdg_ctr phase) rep_match: Matching at an
                        intermediate representation level; logit_match:
                        Matching at the logit level
  --ctr_match_flag CTR_MATCH_FLAG
                        (For matchdg_ctr phase) 0: No Update to Match
                        Strategy; 1: Updates to Match Strategy
  --ctr_match_case CTR_MATCH_CASE
                        (For matchdg_ctr phase) 0: Random Match; 1: Perfect
                        Match. 0.x" x% correct Match
  --ctr_match_interrupt CTR_MATCH_INTERRUPT
                        (For matchdg_ctr phase) Number of epochs before
                        inferring the match strategy
  --mnist_seed MNIST_SEED
                        Change it between 0-6 for different subsets of Mnist
                        and Fashion Mnist dataset
  --retain RETAIN       0: Train from scratch in MatchDG Phase 2; 2: Finetune
                        from MatchDG Phase 1 in MatchDG is Phase 2
  --cuda_device CUDA_DEVICE
                        Select the cuda device by id among the avaliable
                        devices
  --os_env OS_ENV       0: Code execution on local server/machine; 1: Code
                        execution in docker/clusters
  --dp_noise DP_NOISE   0: No DP noise; 1: Add DP noise
  --dp_epsilon DP_EPSILON
                        Epsilon value for Differential Privacy
  --dp_attach_opt DP_ATTACH_OPT
                        0: Infinite Epsilon; 1: Finite Epsilion
  --d_steps_per_g_step D_STEPS_PER_G_STEP
  --grad_penalty GRAD_PENALTY
  --conditional CONDITIONAL
  --gaussian GAUSSIAN
  --slab_data_dim SLAB_DATA_DIM
                        Number of features in the slab dataset
  --slab_total_slabs SLAB_TOTAL_SLABS
  --slab_num_samples SLAB_NUM_SAMPLES
  --slab_noise SLAB_NOISE
  --mnist_case MNIST_CASE
                        MNIST Dataset Case: resnet18; lenet, domainbed
  --mnist_aug MNIST_AUG
                        MNIST Data Augmentation: 0 (MNIST, FMNIST Privacy
                        Evaluation); 1 (FMNIST)
  --total_matches_per_point TOTAL_MATCHES_PER_POINT
                        Multiple random matches
  --test_metric TEST_METRIC
                        Evaluation Metrics: acc; match_score, t_sne, mia
  --acc_data_case ACC_DATA_CASE
                        Dataset Train/Val/Test for the accuracy evaluation
                        metric
  --top_k TOP_K         Top K matches to consider for the match score
                        evaluation metric
  --match_func_aug_case MATCH_FUNC_AUG_CASE
                        0: Evaluate match func on train domains; 1: Evaluate
                        match func on self augmentations
  --match_func_data_case MATCH_FUNC_DATA_CASE
                        Dataset Train/Val/Test for the match score evaluation
                        metric
  --mia_batch_size MIA_BATCH_SIZE
                        batch size
  --mia_dnn_steps MIA_DNN_STEPS
                        number of training steps
  --mia_sample_size MIA_SAMPLE_SIZE
                        number of samples from train/test dataset logits
  --mia_logit MIA_LOGIT
                        0: Softmax applied to logits; 1: No Softmax applied to
                        logits
  --attribute_domain ATTRIBUTE_DOMAIN
                        0: spur correlations as attribute; 1: domain as
                        attribute
  --adv_eps ADV_EPS     Epsilon ball dimension for PGD attacks
  --logit_plot_path LOGIT_PLOT_PATH
                        File name to save logit/loss plots
```

--- python test_slab.py --help ---
(`python test_slab.py --help` fails at this commit with TypeError: %c requires int or char: a help string has an unescaped %. Below is the same parser's help with those % signs escaped by code.)
```
usage: test_slab.py [-h] [--dataset_name DATASET_NAME]
                    [--method_name METHOD_NAME] [--model_name MODEL_NAME]
                    [--train_domains TRAIN_DOMAINS [TRAIN_DOMAINS ...]]
                    [--test_domains TEST_DOMAINS [TEST_DOMAINS ...]]
                    [--out_classes OUT_CLASSES] [--img_c IMG_C]
                    [--img_h IMG_H] [--img_w IMG_W] [--fc_layer FC_LAYER]
                    [--match_layer MATCH_LAYER] [--pos_metric POS_METRIC]
                    [--rep_dim REP_DIM] [--pre_trained PRE_TRAINED]
                    [--perfect_match PERFECT_MATCH] [--opt OPT]
                    [--weight_decay WEIGHT_DECAY] [--lr LR]
                    [--batch_size BATCH_SIZE] [--epochs EPOCHS]
                    [--penalty_s PENALTY_S] [--penalty_irm PENALTY_IRM]
                    [--penalty_aug PENALTY_AUG] [--penalty_ws PENALTY_WS]
                    [--penalty_diff_ctr PENALTY_DIFF_CTR] [--tau TAU]
                    [--match_flag MATCH_FLAG] [--match_case MATCH_CASE]
                    [--match_interrupt MATCH_INTERRUPT] [--ctr_abl CTR_ABL]
                    [--match_abl MATCH_ABL] [--n_runs N_RUNS]
                    [--n_runs_matchdg_erm N_RUNS_MATCHDG_ERM]
                    [--ctr_model_name CTR_MODEL_NAME]
                    [--ctr_match_layer CTR_MATCH_LAYER]
                    [--ctr_match_flag CTR_MATCH_FLAG]
                    [--ctr_match_case CTR_MATCH_CASE]
                    [--ctr_match_interrupt CTR_MATCH_INTERRUPT]
                    [--mnist_seed MNIST_SEED] [--retain RETAIN]
                    [--cuda_device CUDA_DEVICE] [--os_env OS_ENV]
                    [--dp_noise DP_NOISE] [--dp_epsilon DP_EPSILON]
                    [--d_steps_per_g_step D_STEPS_PER_G_STEP]
                    [--grad_penalty GRAD_PENALTY] [--conditional CONDITIONAL]
                    [--gaussian GAUSSIAN] [--slab_data_dim SLAB_DATA_DIM]
                    [--slab_total_slabs SLAB_TOTAL_SLABS]
                    [--slab_num_samples SLAB_NUM_SAMPLES]
                    [--slab_noise SLAB_NOISE] [--mnist_case MNIST_CASE]
                    [--mnist_aug MNIST_AUG]
                    [--total_matches_per_point TOTAL_MATCHES_PER_POINT]
                    [--test_metric TEST_METRIC]
                    [--acc_data_case ACC_DATA_CASE] [--top_k TOP_K]
                    [--match_func_aug_case MATCH_FUNC_AUG_CASE]
                    [--match_func_data_case MATCH_FUNC_DATA_CASE]
                    [--mia_batch_size MIA_BATCH_SIZE]
                    [--mia_dnn_steps MIA_DNN_STEPS]
                    [--mia_sample_size MIA_SAMPLE_SIZE]
                    [--mia_logit MIA_LOGIT]
                    [--attribute_domain ATTRIBUTE_DOMAIN] [--adv_eps ADV_EPS]
                    [--logit_plot_path LOGIT_PLOT_PATH]

optional arguments:
  -h, --help            show this help message and exit
  --dataset_name DATASET_NAME
                        Datasets: rot_mnist; fashion_mnist; pacs
  --method_name METHOD_NAME
                        Training Algorithm: erm_match; matchdg_ctr;
                        matchdg_erm
  --model_name MODEL_NAME
                        Architecture of the model to be trained
  --train_domains TRAIN_DOMAINS [TRAIN_DOMAINS ...]
                        List of train domains
  --test_domains TEST_DOMAINS [TEST_DOMAINS ...]
                        List of test domains
  --out_classes OUT_CLASSES
                        Total number of classes in the dataset
  --img_c IMG_C         Number of channels of the image in dataset
  --img_h IMG_H         Height of the image in dataset
  --img_w IMG_W         Width of the image in dataset
  --fc_layer FC_LAYER   ResNet architecture customization; 0: No fc_layer with
                        resnet; 1: fc_layer for classification with resnet
  --match_layer MATCH_LAYER
                        rep_match: Matching at an intermediate representation
                        level; logit_match: Matching at the logit level
  --pos_metric POS_METRIC
                        Cost to function to evaluate distance between two
                        representations; Options: l1; l2; cos
  --rep_dim REP_DIM     Representation dimension for contrsative learning
  --pre_trained PRE_TRAINED
                        0: No Pretrained Architecture; 1: Pretrained
                        Architecture
  --perfect_match PERFECT_MATCH
                        0: No perfect match known (PACS); 1: perfect match
                        known (MNIST)
  --opt OPT             Optimizer Choice: sgd; adam
  --weight_decay WEIGHT_DECAY
                        Weight Decay in SGD
  --lr LR               Learning rate for training the model
  --batch_size BATCH_SIZE
                        Batch size foe training the model
  --epochs EPOCHS       Total number of epochs for training the model
  --penalty_s PENALTY_S
                        Epoch threshold over which Matching Loss to be
                        optimised
  --penalty_irm PENALTY_IRM
                        Penalty weight for IRM invariant classifier loss
  --penalty_aug PENALTY_AUG
                        Penalty weight for Augmentation in Hybrid approach
                        loss
  --penalty_ws PENALTY_WS
                        Penalty weight for Matching Loss
  --penalty_diff_ctr PENALTY_DIFF_CTR
                        Penalty weight for Contrastive Loss
  --tau TAU             Temperature hyper param for NTXent contrastive loss
  --match_flag MATCH_FLAG
                        0: No Update to Match Strategy; 1: Updates to Match
                        Strategy
  --match_case MATCH_CASE
                        0: Random Match; 1: Perfect Match. 0.x" x% correct
                        Match
  --match_interrupt MATCH_INTERRUPT
                        Number of epochs before inferring the match strategy
  --ctr_abl CTR_ABL     0: Randomization til class level ; 1: Randomization
                        completely
  --match_abl MATCH_ABL
                        0: Randomization til class level ; 1: Randomization
                        completely
  --n_runs N_RUNS       Number of iterations to repeat the training process
  --n_runs_matchdg_erm N_RUNS_MATCHDG_ERM
                        Number of iterations to repeat training process for
                        matchdg_erm
  --ctr_model_name CTR_MODEL_NAME
                        (For matchdg_ctr phase) Architecture of the model to
                        be trained
  --ctr_match_layer CTR_MATCH_LAYER
                        (For matchdg_ctr phase) rep_match: Matching at an
                        intermediate representation level; logit_match:
                        Matching at the logit level
  --ctr_match_flag CTR_MATCH_FLAG
                        (For matchdg_ctr phase) 0: No Update to Match
                        Strategy; 1: Updates to Match Strategy
  --ctr_match_case CTR_MATCH_CASE
                        (For matchdg_ctr phase) 0: Random Match; 1: Perfect
                        Match. 0.x" x% correct Match
  --ctr_match_interrupt CTR_MATCH_INTERRUPT
                        (For matchdg_ctr phase) Number of epochs before
                        inferring the match strategy
  --mnist_seed MNIST_SEED
                        Change it between 0-6 for different subsets of Mnist
                        and Fashion Mnist dataset
  --retain RETAIN       0: Train from scratch in MatchDG Phase 2; 2: Finetune
                        from MatchDG Phase 1 in MatchDG is Phase 2
  --cuda_device CUDA_DEVICE
                        Select the cuda device by id among the avaliable
                        devices
  --os_env OS_ENV       0: Code execution on local server/machine; 1: Code
                        execution in docker/clusters
  --dp_noise DP_NOISE   0: No DP noise; 1: Add DP noise
  --dp_epsilon DP_EPSILON
                        Epsilon value for Differential Privacy
  --d_steps_per_g_step D_STEPS_PER_G_STEP
  --grad_penalty GRAD_PENALTY
  --conditional CONDITIONAL
  --gaussian GAUSSIAN
  --slab_data_dim SLAB_DATA_DIM
                        Number of features in the slab dataset
  --slab_total_slabs SLAB_TOTAL_SLABS
  --slab_num_samples SLAB_NUM_SAMPLES
  --slab_noise SLAB_NOISE
  --mnist_case MNIST_CASE
                        MNIST Dataset Case: resnet18; lenet, domainbed
  --mnist_aug MNIST_AUG
                        MNIST Data Augmentation: 0 (MNIST, FMNIST Privacy
                        Evaluation); 1 (FMNIST)
  --total_matches_per_point TOTAL_MATCHES_PER_POINT
                        Multiple random matches
  --test_metric TEST_METRIC
                        Evaluation Metrics: acc; match_score, t_sne, mia
  --acc_data_case ACC_DATA_CASE
                        Dataset Train/Val/Test for the accuracy evaluation
                        metric
  --top_k TOP_K         Top K matches to consider for the match score
                        evaluation metric
  --match_func_aug_case MATCH_FUNC_AUG_CASE
                        0: Evaluate match func on train domains; 1: Evaluate
                        match func on self augmentations
  --match_func_data_case MATCH_FUNC_DATA_CASE
                        Dataset Train/Val/Test for the match score evaluation
                        metric
  --mia_batch_size MIA_BATCH_SIZE
                        batch size
  --mia_dnn_steps MIA_DNN_STEPS
                        number of training steps
  --mia_sample_size MIA_SAMPLE_SIZE
                        number of samples from train/test dataset logits
  --mia_logit MIA_LOGIT
                        0: Softmax applied to logits; 1: No Softmax applied to
                        logits
  --attribute_domain ATTRIBUTE_DOMAIN
                        0: spur correlations as attribute; 1: domain as
                        attribute
  --adv_eps ADV_EPS     Epsilon ball dimension for PGD attacks
  --logit_plot_path LOGIT_PLOT_PATH
                        File name to save logit/loss plots
```
