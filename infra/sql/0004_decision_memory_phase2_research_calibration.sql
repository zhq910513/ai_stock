-- Candidate Memory Phase 2 additions.
-- Extends candidate_memory from a pre-signal skeleton into a persistence/calibration/research chain.
-- The scheduler and source layers remain generic; model truth remains in decision_memory.*.

CREATE SCHEMA IF NOT EXISTS decision_memory;
CREATE SCHEMA IF NOT EXISTS source;

-- Lightweight source relationship layer required by candidate_memory pre-signal/up-reason research.
-- These tables are source facts / relationship facts, not model truth.
CREATE TABLE IF NOT EXISTS source.stock_theme_link_v1 (
  symbol TEXT NOT NULL,
  theme_code TEXT NOT NULL,
  theme_name TEXT,
  relation_strength_score NUMERIC(12,6),
  provider TEXT NOT NULL,
  event_time TIMESTAMPTZ NOT NULL,
  available_at TIMESTAMPTZ NOT NULL,
  captured_at TIMESTAMPTZ NOT NULL,
  source_payload_hash TEXT NOT NULL,
  PRIMARY KEY(symbol, theme_code, provider, event_time)
);

CREATE TABLE IF NOT EXISTS source.event_entity_link_v1 (
  event_id TEXT NOT NULL,
  symbol TEXT,
  theme_code TEXT,
  entity_type TEXT NOT NULL,
  relevance_score NUMERIC(12,6),
  provider TEXT NOT NULL,
  event_time TIMESTAMPTZ NOT NULL,
  published_at TIMESTAMPTZ,
  available_at TIMESTAMPTZ NOT NULL,
  captured_at TIMESTAMPTZ NOT NULL,
  link_payload_hash TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_source_event_entity_link_unique
ON source.event_entity_link_v1(event_id, entity_type, COALESCE(symbol, ''), COALESCE(theme_code, ''), provider);

CREATE INDEX IF NOT EXISTS idx_source_event_entity_available
ON source.event_entity_link_v1(available_at DESC, symbol, theme_code);

CREATE TABLE IF NOT EXISTS decision_memory.memory_matched_control_uplift_v1 (
  uplift_id TEXT PRIMARY KEY,
  segment_key TEXT NOT NULL,
  evaluated_at TIMESTAMPTZ NOT NULL,
  hot_entered_sample_count INTEGER NOT NULL,
  matched_control_sample_count INTEGER NOT NULL,
  hot_entered_next_limit_up_rate NUMERIC(12,6),
  matched_control_next_limit_up_rate NUMERIC(12,6),
  uplift_rate_pct NUMERIC(12,6),
  hot_entered_avg_time_to_limit_up_days NUMERIC(12,6),
  matched_control_avg_time_to_limit_up_days NUMERIC(12,6),
  research_state TEXT NOT NULL,
  hard_block_reasons_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  uplift_hash TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_matched_control_segment_time
ON decision_memory.memory_matched_control_uplift_v1(segment_key, evaluated_at DESC);

CREATE TABLE IF NOT EXISTS decision_memory.memory_event_signal_feature_batch_v1 (
  batch_id TEXT PRIMARY KEY,
  memory_entity_id TEXT,
  symbol TEXT NOT NULL,
  decision_time TIMESTAMPTZ NOT NULL,
  ex_ante_event_count INTEGER NOT NULL DEFAULT 0,
  post_hoc_event_count INTEGER NOT NULL DEFAULT 0,
  excluded_event_count INTEGER NOT NULL DEFAULT 0,
  source_gap_codes_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  feature_batch_payload_json JSONB NOT NULL,
  batch_hash TEXT NOT NULL
);

-- For large deployments, partition these by observe_time/decision_time:
--   decision_memory.memory_observation_snapshot_v1 by month/day on observe_time.
--   decision_memory.memory_event_signal_feature_v1 by day/week on feature_time.
--   source.event_entity_link_v1 by month on available_at.
-- Phase 2 intentionally keeps the DDL compatible with single-node local validation; Phase scheduler v2 will introduce partitions.
