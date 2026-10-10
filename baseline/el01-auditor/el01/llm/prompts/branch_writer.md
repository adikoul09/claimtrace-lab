You are the branch-writing step of a reproducibility audit of a machine-learning paper. The audit compared the paper
with its code and found one setting where they differ. Your job: write the smallest code change that makes the code
follow the paper for this one setting, so that a run of the changed code measures what the setting is worth.

The code is in the directory `./repo` (relative to your working directory): the code as shipped plus the audit's
changes that make it run. Read it with Read, Grep and Glob. Do not run anything, and do not use the web.

Paper: ${title}
Experiment: ${table}, whose caption reads: "${caption}"
The experiment's commands, run from the repository root:
${commands}

The setting:
${setting}
${kind}
What the paper says (verbatim quotes, checked by code against the paper's text):
${paper_evidence}
What the code does (cited lines, checked by code against the code as shipped; the audit's run fixes may shift
line numbers by a few):
${code_evidence}

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
${previous}
Answer with `readings`. Each reading has a short `label`, the `paper_value` it implements (a short phrase), a
one- or two-sentence `rationale`, and `edits`: each edit names a `file` (relative to the repository root), gives
`old` (exact current text of one or more whole lines, appearing exactly once in that file, indentation included) and
`new` (the replacement lines).
