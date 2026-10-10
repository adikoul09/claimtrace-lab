-- ClaimTrace Lab 002: Elevate gateway usage on llm_calls. Paste into the Supabase SQL editor. Safe to re-run.
-- total_tokens: the gateway's usage.total_tokens; request_id: its X-Elevate-Request-Id header (for support queries).
-- Until this runs, lab/llm.py logs calls without these two columns.

begin;

alter table llm_calls add column if not exists total_tokens integer;
alter table llm_calls add column if not exists request_id   text;

-- The daily token counter (live calls since 05:30 IST = 00:00 UTC) reads this range on every live call.
create index if not exists llm_calls_live_ts_idx on llm_calls (ts) where mode = 'live';

commit;
