-- Candidate Memory Phase 4 additions.
-- Completes the production-chain candidate: typed source feature snapshots, stage write audits,
-- replay validation, pre-signal threshold calibration, and phase acceptance records.
-- Model truth remains in decision_memory.*. Scheduler/governance tables do not store model labels or scores.
-- Acceptance checks include new_cycle_exclusion so full-new-cycle limit-ups are not counted as memory success.

CREATE SCHEMA IF NOT EXISTS decision_memory;
CREATE SCHEMA IF NOT EXISTS governance;
CREATE SCHEMA IF NOT EXISTS source;

CREATE TABLE IF NOT EXISTS decision_memory.memory_source_feature_snapshot_v1 (
  snapshot_id TEXT PRIMARY KEY,
  memory_entity_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  decision_time TIMESTAMPTZ NOT NULL,
  price_structure_feature_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  moneyflow_feature_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  sector_theme_feature_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  event_signal_feature_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  tradability_feature_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  feature_watermarks_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  source_gap_codes_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  snapshot_hash TEXT NOT NULL,
  UNIQUE(memory_entity_id, decision_time)
);

CREATE INDEX IF NOT EXISTS idx_memory_source_feature_entity_time
ON decision_memory.memory_source_feature_snapshot_v1(memory_entity_id, decision_time DESC);

CREATE TABLE IF NOT EXISTS decision_memory.memory_stage_persistence_plan_v1 (
  plan_id TEXT PRIMARY KEY,
  planned_at TIMESTAMPTZ NOT NULL,
  plan_state TEXT NOT NULL,
  planned_writes_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  skipped_stages_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  hard_block_reasons_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  plan_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decision_memory.memory_pre_signal_threshold_calibration_v1 (
  calibration_id TEXT PRIMARY KEY,
  model_version TEXT NOT NULL,
  calculated_at TIMESTAMPTZ NOT NULL,
  calibration_cutoff_time TIMESTAMPTZ NOT NULL,
  eligible_sample_count INTEGER NOT NULL,
  excluded_sample_count INTEGER NOT NULL,
  recommended_pre_signal_threshold NUMERIC(12,6),
  recommended_activation_threshold NUMERIC(12,6),
  bucket_reports_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  calibration_state TEXT NOT NULL,
  calibration_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decision_memory.memory_multi_day_replay_validation_v1 (
  replay_id TEXT PRIMARY KEY,
  memory_entity_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  replayed_at TIMESTAMPTZ NOT NULL,
  trading_day_count INTEGER NOT NULL,
  earliest_pre_signal_date DATE,
  first_activation_date DATE,
  next_limit_up_date DATE,
  pre_signal_lead_days INTEGER,
  outcome_label TEXT,
  tradable_success BOOLEAN NOT NULL DEFAULT false,
  direction_success_execution_missed BOOLEAN NOT NULL DEFAULT false,
  guardrail_violations_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  replay_state TEXT NOT NULL,
  replay_hash TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_replay_entity_time
ON decision_memory.memory_multi_day_replay_validation_v1(memory_entity_id, replayed_at DESC);

CREATE TABLE IF NOT EXISTS governance.model_phase_acceptance_check_v1 (
  acceptance_id TEXT PRIMARY KEY,
  model_code TEXT NOT NULL,
  model_version TEXT NOT NULL,
  phase_code TEXT NOT NULL,
  checked_at TIMESTAMPTZ NOT NULL,
  acceptance_state TEXT NOT NULL,
  checks_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  missing_checks_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  acceptance_hash TEXT NOT NULL,
  UNIQUE(model_code, model_version, phase_code, acceptance_hash)
);

-- Large-volume deployment recommendations:
--   decision_memory.memory_observation_snapshot_v1: RANGE partition by observe_time.
--   decision_memory.memory_source_feature_snapshot_v1: RANGE partition by decision_time.
--   decision_memory.memory_event_signal_feature_v1: RANGE partition by feature_time/available_at.
--   source.event_entity_link_v1 and source.news_event_v1: RANGE partition by available_at.
-- Phase 4 deliberately keeps base tables portable; scheduler v2 migrations should create child partitions
-- based on deployment data volume and provider frequency.
