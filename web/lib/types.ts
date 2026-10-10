// Row types mirroring supabase/migrations/001_init.sql (SPEC §11).
// Timestamps arrive as ISO strings; jsonb columns as unknown JSON.

export type Json = string | number | boolean | null | Json[] | { [k: string]: Json };

export type AgentStatus = "active" | "retired" | "merged";
export type AgentOrigin = "seed" | "spawned" | "refined";
export type TaskStatus =
  | "queued"
  | "running"
  | "awaiting_approval"
  | "done"
  | "failed"
  | "rejected";
export type LlmMode = "live" | "replay";

export interface Project {
  id: string;
  title: string;
  arxiv_id: string | null;
  repo_url: string | null;
  budget_cpu_min: number;
  status: string;
  tags: string[];
  created_at: string;
}

export interface Paper {
  id: string;
  project_id: string;
  arxiv_id: string;
  title: string | null;
  pdf_path: string | null;
  text_path: string | null;
  claims: Json;
  settings: Json;
  created_at: string;
}

export interface Agent {
  id: string;
  name: string;
  role_prompt: string;
  capabilities: string[];
  tools: string[];
  budget: { max_tokens: number; max_cpu_s: number; max_steps: number };
  version: number;
  parent_id: string | null;
  status: AgentStatus;
  merged_into: string | null;
  origin: AgentOrigin;
  origin_reason: string;
  created_by_task: string | null;
  created_at: string;
}

export interface Task {
  id: string;
  project_id: string | null;
  parent_task_id: string | null;
  capability: string;
  required_caps: string[];
  agent_id: string | null;
  executor: string | null;
  status: TaskStatus;
  requires_approval: boolean;
  decision: "approve" | "reject" | "redirect" | null;
  decision_note: string | null;
  input: Json;
  output: Json | null;
  acceptance: Json | null;
  tokens: number;
  cpu_seconds: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface Experiment {
  id: string;
  project_id: string;
  parent_id: string | null;
  label: string;
  config: Json;
  changed_key: string | null;
  budget_reason: string | null;
  margin: number | null;
  status: string;
  executor: string | null;
  verdicts: Json | null;
  pruned_reason: string | null;
  log_path: string | null;
  created_at: string;
}

export interface Metric {
  id: string;
  experiment_id: string;
  step: number;
  name: string;
  value: number;
  log_line: number;
  ts: string;
}

export interface Event {
  id: string;
  project_id: string | null;
  agent_id: string | null;
  task_id: string | null;
  type: string;
  message: string;
  reason: string;
  data: Json;
  ts: string;
}

export interface Reward {
  id: string;
  agent_id: string;
  task_id: string;
  outcome: number;
  cost_norm: number;
  feedback: number;
  reward: number;
  ts: string;
}

export interface Lesson {
  id: string;
  project_id: string | null;
  kind: "failure_fix" | "setting_mattered" | "budget" | "agent_choice";
  text: string;
  tags: string[];
  evidence_event_id: string;
  times_applied: number;
  created_at: string;
}

export interface Executor {
  name: string;
  caps: string[];
  busy: boolean;
  last_heartbeat: string | null;
}

export interface LlmCall {
  id: string;
  agent_id: string | null;
  task_id: string | null;
  model: string;
  tokens_in: number;
  tokens_out: number;
  mode: LlmMode;
  cache_key: string | null;
  ts: string;
}
