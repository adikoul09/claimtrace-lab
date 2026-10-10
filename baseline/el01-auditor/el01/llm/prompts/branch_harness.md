You are part of a reproducibility audit of a machine-learning paper. The code is in the directory `./repo` (relative
to your working directory): the code as shipped plus the audit's changes that make it run. Read it with Read, Grep
and Glob. Do not run anything, and do not use the web.

The audit re-runs one result on fresh seeds. The experiment's commands, run from the repository root, are:
${commands}
With `${runs_option} ${runs}` they use seeds 0 to ${last_old}. The audit will run the training command with
`${runs_option} ${runs_new}` and keep only seeds ${first_new} to ${last_new}. Today the data step produces data
for seeds 0 to ${last_old} only, so seeds ${first_new} to ${last_new} would fail for lack of data.

Write the smallest change to the data step so that it also produces the data for seeds ${first_new} to ${last_new}.
The data it produces today must stay byte-identical (same files, same contents: keep every existing random draw
in its order). Change nothing else: no training code, no other settings. Add no comments.
${previous}
Answer with one reading in `readings`: a short `label`, `paper_value` = "fresh seeds", a one-sentence `rationale`,
and `edits`: each edit names a `file` (relative to the repository root), gives `old` (exact current text of one or
more whole lines, appearing exactly once in that file, indentation included) and `new` (the replacement lines).
