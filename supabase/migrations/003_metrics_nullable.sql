-- ClaimTrace Lab 003: a METRIC line whose value is NaN or inf is stored with value NULL, keeping its log line
-- (a diverged run must stay visible and traceable). Paste into the Supabase SQL editor. Safe to re-run.
-- projects.status is free text, so the 'reference' status (precomputed / reference runs the controller never
-- touches) needs no schema change.

begin;

alter table metrics alter column value drop not null;

comment on column metrics.value is 'NULL when the METRIC line printed NaN or inf; log_line still points at it';
comment on column projects.status is
  'new | planning | running | done | blocked | stopped | plan_failed (controller); test | reference (never touched)';

commit;
