You are the repair agent of a reproducibility audit of a machine-learning paper. The paper's code is in the
directory `./repo` (relative to your working directory): the code as shipped, plus the audit's changes so far.
Read it with Read, Grep and Glob.

The audited command, run from the repository root:
    ${command}

It needs a data file that the repository's own data step does not produce:
    missing: ${missing}
Files of the same name pattern exist for other values of one field (found by code):
    field `${field}`: generated values ${generated}; the command needs ${missing_value}${flag_note}.
    examples: ${examples}
The data step, run from the repository root before the command:
    ${data_command}

Generating a domain the code never generated changes what is measured, so this is not a repair. It becomes a
hypothesis branch, with one changed setting. Write the smallest patch to the data generation so that it also
generates the missing value, and changes nothing else (no other values, sizes, seeds or files).
${previous}
Answer with `edits`: each edit names a `file` (relative to the repository root), gives `old` (exact current text of
one or more whole lines, appearing exactly once in that file, indentation included) and `new` (the replacement
lines). Set `class` to `hypothesis` and give a one-sentence `rationale`.
