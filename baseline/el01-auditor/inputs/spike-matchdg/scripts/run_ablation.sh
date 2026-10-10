#!/usr/bin/env bash
# Usage: run_ablation.sh <worktree_dir> <outdir> [methods...]
set -u
WT=$1; OUT=$2; shift 2
METHODS=${@:-erm rand perf}
cd "$WT"
mkdir -p "$OUT"
git rev-parse HEAD > "$OUT/commit.txt"
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
../.venv/bin/python data_gen_syn.py > "$OUT/datagen.log" 2>&1
COMMON="--dataset slab --model_name slab --batch_size 128 --lr 0.1 --epochs 100 --out_classes 2 --train_domains 0.0 0.10 --test_domains ${TD:-1.0} --slab_data_dim 2 --slab_noise 0.1 --n_runs 10 ${EXTRA:-}"
declare -A M
M[erm]="--method_name erm_match --match_case 0.0 --penalty_ws 0.0"
M[rand]="--method_name erm_match --match_case 0.0 --penalty_ws 1.0"
M[perf]="--method_name erm_match --match_case 1.0 --penalty_ws 1.0"
for m in $METHODS; do
  s=$(date +%s)
  ../.venv/bin/python train.py $COMMON ${M[$m]} > "$OUT/train_$m.log" 2>&1
  echo "$m done in $(( $(date +%s) - s ))s" >> "$OUT/progress.txt"
done
echo ALL_DONE >> "$OUT/progress.txt"
