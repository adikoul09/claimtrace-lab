-- ClaimTrace Lab: initial schema (T01). Data model from SPEC §11.
-- Paste into the Supabase SQL editor. Safe to re-run.
--
-- Access model:
--   anon ("publishable" key, used by the browser): SELECT only, via RLS policies.
--   service_role ("secret" key, server routes, controller, workers): bypasses RLS; does all writes.

begin;

-- ---------------------------------------------------------------------------
-- Enums
-- ---------------------------------------------------------------------------
do $$ begin
  create type agent_status as enum ('active', 'retired', 'merged');
exception when duplicate_object then null; end $$;

do $$ begin
  create type agent_origin as enum ('seed', 'spawned', 'refined');
exception when duplicate_object then null; end $$;

do $$ begin
  create type task_status as enum ('queued', 'running', 'awaiting_approval', 'done', 'failed', 'rejected');
exception when duplicate_object then null; end $$;

do $$ begin
  create type llm_mode as enum ('live', 'replay');
exception when duplicate_object then null; end $$;

-- ---------------------------------------------------------------------------
-- Tables
-- ---------------------------------------------------------------------------
create table if not exists projects (
  id             uuid primary key default gen_random_uuid(),
  title          text not null,
  arxiv_id       text,
  repo_url       text,
  budget_cpu_min integer not null default 20,
  status         text not null default 'new',
  tags           text[] not null default '{}',
  created_at     timestamptz not null default now()
);

create table if not exists papers (
  id         uuid primary key default gen_random_uuid(),
  project_id uuid not null unique references projects(id) on delete cascade,
  arxiv_id   text not null,
  title      text,
  pdf_path   text,
  text_path  text,
  claims     jsonb not null default '[]',
  settings   jsonb not null default '[]',
  created_at timestamptz not null default now()
);

-- Agents are data (SPEC §2). Tools must come from the fixed set (§2.2).
create table if not exists agents (
  id              uuid primary key default gen_random_uuid(),
  name            text not null unique,
  role_prompt     text not null,
  capabilities    text[] not null default '{}',
  tools           text[] not null default '{}',
  budget          jsonb not null default '{"max_tokens": 20000, "max_cpu_s": 300, "max_steps": 8}',
  version         integer not null default 1,
  parent_id       uuid references agents(id),
  status          agent_status not null default 'active',
  merged_into     uuid references agents(id),
  origin          agent_origin not null,
  origin_reason   text not null,
  created_by_task uuid,  -- FK to tasks added below (circular reference)
  created_at      timestamptz not null default now(),
  constraint agents_tools_fixed_set check (tools <@ array[
    'fetch_paper', 'fetch_repo', 'read_file', 'write_file', 'list_dir',
    'make_env', 'run', 'query_memory', 'emit']::text[]),
  constraint agents_merged_has_target check (status <> 'merged' or merged_into is not null)
);

create table if not exists tasks (
  id                uuid primary key default gen_random_uuid(),
  project_id        uuid references projects(id) on delete cascade,
  parent_task_id    uuid references tasks(id),
  capability        text not null,
  required_caps     text[] not null default '{}',
  agent_id          uuid references agents(id),
  executor          text,
  status            task_status not null default 'queued',
  requires_approval boolean not null default false,
  decision          text check (decision in ('approve', 'reject', 'redirect')),
  decision_note     text,
  input             jsonb not null default '{}',
  output            jsonb,
  acceptance        jsonb,
  tokens            integer not null default 0,
  cpu_seconds       double precision not null default 0,
  created_at        timestamptz not null default now(),
  started_at        timestamptz,
  finished_at       timestamptz
);

do $$ begin
  alter table agents add constraint agents_created_by_task_fkey
    foreign key (created_by_task) references tasks(id);
exception when duplicate_object then null; end $$;

create table if not exists experiments (
  id            uuid primary key default gen_random_uuid(),
  project_id    uuid not null references projects(id) on delete cascade,
  parent_id     uuid references experiments(id),
  label         text not null,
  config        jsonb not null default '{}',
  changed_key   text,               -- the one setting a what-if branch changes (§7.4)
  budget_reason text,
  margin        double precision,   -- declared before the run (§7.5)
  status        text not null default 'planned',
  executor      text,
  verdicts      jsonb,
  pruned_reason text,
  log_path      text,
  created_at    timestamptz not null default now()
);

-- One row per `METRIC name=value step=N` line; log_line is its line number in log_path.
create table if not exists metrics (
  id            uuid primary key default gen_random_uuid(),
  experiment_id uuid not null references experiments(id) on delete cascade,
  step          integer not null,
  name          text not null,
  value         double precision not null,
  log_line      integer not null,
  ts            timestamptz not null default now()
);

-- Every decision writes an event with a reason.
create table if not exists events (
  id         uuid primary key default gen_random_uuid(),
  project_id uuid references projects(id) on delete cascade,
  agent_id   uuid references agents(id),
  task_id    uuid references tasks(id),
  type       text not null,
  message    text not null,
  reason     text not null,
  data       jsonb not null default '{}',
  ts         timestamptz not null default now()
);

-- Reward per task (SPEC §5); recomputed in place when feedback arrives.
create table if not exists rewards (
  id        uuid primary key default gen_random_uuid(),
  agent_id  uuid not null references agents(id),
  task_id   uuid not null unique references tasks(id) on delete cascade,
  outcome   double precision not null check (outcome in (0, 0.5, 1)),
  cost_norm double precision not null check (cost_norm between 0 and 1),
  feedback  double precision not null check (feedback in (0, 0.5, 1)),
  reward    double precision not null check (reward between 0 and 1),
  ts        timestamptz not null default now()
);

-- A lesson is kept only with evidence (SPEC §6).
create table if not exists lessons (
  id                uuid primary key default gen_random_uuid(),
  project_id        uuid references projects(id) on delete set null,
  kind              text not null check (kind in ('failure_fix', 'setting_mattered', 'budget', 'agent_choice')),
  text              text not null,
  tags              text[] not null default '{}',
  evidence_event_id uuid not null references events(id),
  times_applied     integer not null default 0,
  created_at        timestamptz not null default now()
);

create table if not exists executors (
  name           text primary key,
  caps           text[] not null default '{}',
  busy           boolean not null default false,
  last_heartbeat timestamptz
);

create table if not exists llm_calls (
  id         uuid primary key default gen_random_uuid(),
  agent_id   uuid references agents(id),
  task_id    uuid references tasks(id),
  model      text not null,
  tokens_in  integer not null default 0,
  tokens_out integer not null default 0,
  mode       llm_mode not null default 'live',
  cache_key  text,
  ts         timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- Indexes
-- ---------------------------------------------------------------------------
create index if not exists tasks_queued_idx       on tasks (created_at) where status = 'queued';
create index if not exists tasks_project_idx      on tasks (project_id);
create index if not exists experiments_project_idx on experiments (project_id);
create index if not exists metrics_experiment_idx on metrics (experiment_id, step);
create index if not exists events_project_ts_idx  on events (project_id, ts desc);
create index if not exists rewards_agent_ts_idx   on rewards (agent_id, ts desc);
create index if not exists lessons_tags_idx       on lessons using gin (tags);

-- ---------------------------------------------------------------------------
-- Row-level security: anon reads, only service_role writes
-- ---------------------------------------------------------------------------
do $$
declare t text;
begin
  foreach t in array array['projects', 'papers', 'agents', 'tasks', 'experiments', 'metrics',
                           'events', 'rewards', 'lessons', 'executors', 'llm_calls'] loop
    execute format('alter table %I enable row level security', t);
    execute format('drop policy if exists "public read" on %I', t);
    execute format('create policy "public read" on %I for select to anon, authenticated using (true)', t);
    -- Defence in depth: browser keys never write, even if a policy is added by mistake.
    execute format('revoke insert, update, delete, truncate on %I from anon, authenticated', t);
  end loop;
end $$;

-- ---------------------------------------------------------------------------
-- Realtime
-- ---------------------------------------------------------------------------
do $$
declare t text;
begin
  if not exists (select 1 from pg_publication where pubname = 'supabase_realtime') then
    create publication supabase_realtime;
  end if;
  foreach t in array array['events', 'metrics', 'tasks', 'agents', 'experiments'] loop
    if not exists (select 1 from pg_publication_tables
                   where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = t) then
      execute format('alter publication supabase_realtime add table public.%I', t);
    end if;
  end loop;
end $$;

-- ---------------------------------------------------------------------------
-- Queue: workers claim one queued task whose required_caps ⊆ caps (SPEC §8)
-- ---------------------------------------------------------------------------
create or replace function claim_task(executor_name text, caps text[])
returns setof tasks
language sql
set search_path = public
as $$
  update tasks t
     set status = 'running',
         executor = claim_task.executor_name,
         started_at = now()
   where t.id = (
           select q.id
             from tasks q
            where q.status = 'queued'
              and q.required_caps <@ claim_task.caps
            order by q.created_at
            limit 1
              for update skip locked)
     and t.status = 'queued'
  returning t.*;
$$;

revoke execute on function claim_task(text, text[]) from public, anon, authenticated;
grant execute on function claim_task(text, text[]) to service_role;

-- ---------------------------------------------------------------------------
-- Seed roster (SPEC §2.4). Deliberately no Debugger: the first failure spawns one.
-- ---------------------------------------------------------------------------
insert into agents (name, role_prompt, capabilities, tools, budget, origin, origin_reason) values
  ('reader-v1',
   'You are the Reader. Fetch the paper and extract (1) claims: {id, quote, page, table_or_section, metric, value, unit, direction, whose} and (2) settings: {key, value, quote, page}. Copy quotes verbatim; never invent a value that is not in a quote.',
   array['read_paper', 'extract_claims', 'extract_settings'],
   array['fetch_paper', 'read_file', 'query_memory', 'emit'],
   '{"max_tokens": 60000, "max_cpu_s": 120, "max_steps": 10}',
   'seed', 'Seed roster (SPEC §2.4)'),
  ('designer-v1',
   'You are the Designer. From the claims, settings and project budget, propose an experiment scale (epochs, subset, seeds) with a one-line reason, and for what-if questions propose 3-4 branches that each change exactly one setting.',
   array['design_experiment', 'budget', 'design_whatif'],
   array['read_file', 'query_memory', 'emit'],
   '{"max_tokens": 30000, "max_cpu_s": 60, "max_steps": 6}',
   'seed', 'Seed roster (SPEC §2.4)'),
  ('implementer-v1',
   'You are the Implementer. Write train.py in the run directory from the claims and settings. Print every metric as one line: METRIC name=value step=N. Do not change data, model, loss, optimizer, metric or model selection beyond what the settings say.',
   array['write_code'],
   array['read_file', 'write_file', 'list_dir', 'query_memory', 'emit'],
   '{"max_tokens": 60000, "max_cpu_s": 120, "max_steps": 12}',
   'seed', 'Seed roster (SPEC §2.4)'),
  ('envbuilder-v1',
   'You are the EnvBuilder. Write a minimal pinned requirements.txt for the run (CPU-only torch) and call make_env. uv does the install.',
   array['setup_env'],
   array['read_file', 'write_file', 'list_dir', 'make_env', 'query_memory', 'emit'],
   '{"max_tokens": 10000, "max_cpu_s": 600, "max_steps": 4}',
   'seed', 'Seed roster (SPEC §2.4)'),
  ('runner-v1',
   'Runner: code only, no LLM. Runs the given command in the run directory with a hard timeout and a stripped environment, and streams stdout.',
   array['run'],
   array['run', 'list_dir', 'emit'],
   '{"max_tokens": 0, "max_cpu_s": 1200, "max_steps": 1}',
   'seed', 'Seed roster (SPEC §2.4)'),
  ('analyst-v1',
   'You are the Analyst. Code has already graded the results. Explain why ours differs from the paper using ONLY the settings-diff and branch-effect tables you are given. Do not introduce any number that is not in those tables.',
   array['compare', 'explain_diff'],
   array['read_file', 'query_memory', 'emit'],
   '{"max_tokens": 30000, "max_cpu_s": 60, "max_steps": 6}',
   'seed', 'Seed roster (SPEC §2.4)'),
  ('reporter-v1',
   'You are the Reporter. Write the report and research notes in Markdown from stored results only, and propose at most 3 lessons per finished experiment, each {text, tags, evidence_event_id, kind}.',
   array['write_report', 'write_notes'],
   array['read_file', 'write_file', 'query_memory', 'emit'],
   '{"max_tokens": 40000, "max_cpu_s": 60, "max_steps": 8}',
   'seed', 'Seed roster (SPEC §2.4)')
on conflict (name) do nothing;

commit;
