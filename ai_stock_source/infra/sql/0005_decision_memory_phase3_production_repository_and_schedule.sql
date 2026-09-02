-- Candidate Memory Phase 3 additions.
-- Adds production repository/scheduler-v2 contract tables and freshness/readiness audits.
-- Scheduler/governance tables store orchestration metadata only; model truth remains in decision_memory.*.

CREATE SCHEMA IF NOT EXISTS decision_memory;
CREATE SCHEMA IF NOT EXISTS governance;

CREATE TABLE IF NOT EXISTS governance.source_feature_watermark_v1 (
  watermark_id TEXT PRIMARY KEY,
  source_schema TEXT NOT NULL,
  fact_name TEXT NOT NULL,
  provider TEXT NOT NULL,
  symbol TEXT,
  theme_code TEXT,
  watermark_time TIMESTAMPTZ NOT NULL,
  freshness_sla_seconds INTEGER NOT NULL,
  freshness_status TEXT NOT NULL,
  captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  payload_hash TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_governance_watermark_unique
ON governance.source_feature_watermark_v1(source_schema, fact_name, provider, COALESCE(symbol, ''), COALESCE(theme_code, ''));

CREATE INDEX IF NOT EXISTS idx_governance_watermark_fact_symbol
ON governance.source_feature_watermark_v1(fact_name, symbol, watermark_time DESC);

CREATE TABLE IF NOT EXISTS governance.model_schedule_contract_v1 (
  contract_id TEXT PRIMARY KEY,
  model_code TEXT NOT NULL,
  model_version TEXT NOT NULL,
  declared_at TIMESTAMPTZ NOT NULL,
  contract_state TEXT NOT NULL,
  stages_json JSONB NOT NULL,
  frequency_matrix_json JSONB NOT NULL,
  contract_hash TEXT NOT NULL,
  UNIQUE(model_code, model_version, contract_hash)
);

CREATE TABLE IF NOT EXISTS decision_memory.memory_feature_readiness_audit_v1 (
  audit_id TEXT PRIMARY KEY,
  memory_entity_id TEXT,
  symbol TEXT,
  stage_code TEXT NOT NULL,
  decision_time TIMESTAMPTZ NOT NULL,
  readiness_state TEXT NOT NULL,
  feature_details_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  hard_block_reasons_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  warning_codes_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  audit_hash TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_feature_readiness_entity_time
ON decision_memory.memory_feature_readiness_audit_v1(memory_entity_id, decision_time DESC);

CREATE TABLE IF NOT EXISTS decision_memory.memory_due_observation_plan_v1 (
  plan_id TEXT PRIMARY KEY,
  planned_at TIMESTAMPTZ NOT NULL,
  due_case_count INTEGER NOT NULL,
  skipped_count INTEGER NOT NULL,
  plan_payload_json JSONB NOT NULL,
  plan_hash TEXT NOT NULL
);

-- PostgreSQL partitioning recommendations for large deployments:
--   decision_memory.memory_observation_snapshot_v1: RANGE partition by observe_time, daily/monthly depending volume.
--   decision_memory.memory_event_signal_feature_v1: RANGE partition by feature_time.
--   decision_memory.memory_pre_limitup_signal_analysis_v1: RANGE partition by next_limit_up_date when large.
-- Phase 3 keeps base DDL portable; scheduler v2 migration should create child partitions per deployment scale.
