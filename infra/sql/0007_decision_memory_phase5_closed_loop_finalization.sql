-- Candidate Memory Phase 5: closed-loop finalization and RC acceptance.
-- This migration is additive. It preserves the boundary that model truth remains in decision_memory.*;
-- scheduler/governance tables do not store model labels or scores.

CREATE SCHEMA IF NOT EXISTS decision_memory;
CREATE SCHEMA IF NOT EXISTS governance;

CREATE TABLE IF NOT EXISTS decision_memory.memory_closure_pipeline_v1 (
  closure_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  model_version TEXT NOT NULL,
  memory_entity_id TEXT NOT NULL,
  memory_signal_id TEXT,
  symbol TEXT NOT NULL,
  evaluated_at TIMESTAMPTZ NOT NULL,
  closure_state TEXT NOT NULL,
  stage_states_json JSONB NOT NULL,
  hard_block_reasons_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  closure_payload_json JSONB NOT NULL,
  closure_hash TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_memory_closure_entity_time_v1
  ON decision_memory.memory_closure_pipeline_v1(memory_entity_id, evaluated_at DESC);

CREATE TABLE IF NOT EXISTS decision_memory.memory_up_reason_attribution_v1 (
  attribution_id TEXT PRIMARY KEY,
  memory_signal_id TEXT,
  memory_entity_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  attributed_at TIMESTAMPTZ NOT NULL,
  primary_up_reason TEXT NOT NULL,
  pre_signal_reason_codes_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  confirmed_up_reason_codes_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  post_hoc_explanation_codes_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  reason_confidence_score NUMERIC(12,6),
  attribution_payload_json JSONB NOT NULL,
  attribution_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decision_memory.memory_failure_attribution_v1 (
  failure_attribution_id TEXT PRIMARY KEY,
  memory_signal_id TEXT,
  memory_entity_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  attributed_at TIMESTAMPTZ NOT NULL,
  failure_type TEXT NOT NULL,
  failure_reason_codes_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  model_failure_class TEXT NOT NULL,
  outcome_label TEXT,
  attribution_payload_json JSONB NOT NULL,
  attribution_hash TEXT NOT NULL
);

ALTER TABLE decision_memory.memory_failure_attribution_v1
  ADD COLUMN IF NOT EXISTS attributed_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS ix_memory_failure_attr_entity_v1
  ON decision_memory.memory_failure_attribution_v1(memory_entity_id, attributed_at DESC);

CREATE TABLE IF NOT EXISTS decision_memory.memory_evolution_sample_v1 (
  evolution_sample_id TEXT PRIMARY KEY,
  memory_signal_id TEXT,
  memory_entity_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL,
  evolution_state TEXT NOT NULL,
  evolution_labels_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  outcome_hash TEXT,
  sample_payload_json JSONB NOT NULL,
  evolution_hash TEXT NOT NULL,
  CONSTRAINT ck_memory_evolution_ready_or_blocked_v1 CHECK (evolution_state IN ('ready_for_offline_evolution','blocked'))
);

CREATE INDEX IF NOT EXISTS ix_memory_evolution_entity_created_v1
  ON decision_memory.memory_evolution_sample_v1(memory_entity_id, created_at DESC);

CREATE TABLE IF NOT EXISTS decision_memory.memory_model_version_shadow_evaluation_v1 (
  evaluation_id TEXT PRIMARY KEY,
  baseline_model_version TEXT NOT NULL,
  candidate_model_version TEXT NOT NULL,
  evaluated_at TIMESTAMPTZ NOT NULL,
  evaluation_cutoff_time TIMESTAMPTZ NOT NULL,
  eligible_sample_count INTEGER NOT NULL,
  candidate_hit_rate_pct NUMERIC(12,6),
  baseline_hit_rate_pct NUMERIC(12,6),
  evaluation_state TEXT NOT NULL,
  hard_block_reasons_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  evaluation_payload_json JSONB NOT NULL,
  evaluation_hash TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_memory_shadow_eval_version_v1
  ON decision_memory.memory_model_version_shadow_evaluation_v1(candidate_model_version, evaluated_at DESC);

CREATE TABLE IF NOT EXISTS governance.model_phase_final_acceptance_v1 (
  acceptance_id TEXT PRIMARY KEY,
  model_code TEXT NOT NULL,
  phase_code TEXT NOT NULL,
  evaluated_at TIMESTAMPTZ NOT NULL,
  acceptance_state TEXT NOT NULL,
  passed_checks_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  missing_or_failed_checks_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  acceptance_payload_json JSONB NOT NULL,
  acceptance_hash TEXT NOT NULL
);

-- Guardrail notes for contract tests and reviewers:
-- ex_ante_message_guardrail: available_at <= decision_time evidence only can feed pre_signal_score.
-- mature_outcome_only_evolution: pending outcome cannot create memory_evolution_sample_v1.
-- new_independent_cycle_exclusion: new independent cycles are excluded from candidate-memory official success.
-- shadow_evaluation_required_before_version_promotion: candidate version promotion requires mature ex-ante samples.
-- partition recommendation: partition memory_observation_snapshot_v1 and source high-frequency facts by trade date / event time.
