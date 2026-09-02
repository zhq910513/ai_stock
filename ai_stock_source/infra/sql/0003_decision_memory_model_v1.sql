-- Candidate memory model v1: historical hot candidate pre-signal and up-reason research domain.
-- Governance rule: decision_memory.* is independent from decision_hot.* and decision_ambush.*.
-- Source facts remain in source.*; this schema stores model-specific decisions, labels and evolution truth only.

CREATE SCHEMA IF NOT EXISTS decision_memory;

CREATE TABLE IF NOT EXISTS decision_memory.memory_seed_v1 (
  memory_seed_id TEXT PRIMARY KEY,
  source_model TEXT NOT NULL,
  first_source_signal_id TEXT NOT NULL,
  first_source_case_id TEXT,
  symbol TEXT NOT NULL,
  first_selected_date DATE,
  first_outcome_label TEXT,
  seed_priority TEXT NOT NULL,
  seed_reasons_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  seed_status TEXT NOT NULL,
  hard_block_reasons_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  source_gap_codes_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  created_at TIMESTAMPTZ NOT NULL,
  payload_hash TEXT NOT NULL,
  UNIQUE (source_model, first_source_signal_id)
);

CREATE TABLE IF NOT EXISTS decision_memory.memory_entity_v1 (
  memory_entity_id TEXT PRIMARY KEY,
  memory_seed_id TEXT NOT NULL REFERENCES decision_memory.memory_seed_v1(memory_seed_id),
  symbol TEXT NOT NULL,
  name TEXT,
  first_source_model TEXT NOT NULL,
  first_source_signal_id TEXT NOT NULL,
  first_source_case_id TEXT,
  first_selected_date DATE,
  first_outcome_label TEXT,
  memory_status TEXT NOT NULL,
  base_ttl_days INTEGER NOT NULL,
  dynamic_ttl_adjustment_days INTEGER NOT NULL DEFAULT 0,
  ttl_effective_days INTEGER NOT NULL,
  memory_age_days INTEGER NOT NULL DEFAULT 0,
  decay_score NUMERIC(12,6),
  merge_action TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  payload_hash TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_memory_entity_active_symbol_source
ON decision_memory.memory_entity_v1(symbol, first_source_model, first_source_signal_id)
WHERE memory_status IN ('observing','valuable','decaying','near_expiry','expired_but_researchable');

CREATE TABLE IF NOT EXISTS decision_memory.memory_initial_snapshot_v1 (
  memory_entity_id TEXT PRIMARY KEY REFERENCES decision_memory.memory_entity_v1(memory_entity_id),
  symbol TEXT NOT NULL,
  first_source_model TEXT NOT NULL,
  first_source_signal_id TEXT NOT NULL,
  first_selected_date DATE,
  first_model_score NUMERIC(12,6),
  first_teacher_probability NUMERIC(12,6),
  first_hot_lifecycle_stage TEXT,
  first_buy_point_state TEXT,
  first_mfe_pct NUMERIC(12,6),
  first_mae_pct NUMERIC(12,6),
  first_outcome_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
  first_failure_attribution_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  frozen_at TIMESTAMPTZ NOT NULL,
  snapshot_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decision_memory.memory_observation_snapshot_v1 (
  observation_id TEXT PRIMARY KEY,
  memory_entity_id TEXT NOT NULL REFERENCES decision_memory.memory_entity_v1(memory_entity_id),
  symbol TEXT NOT NULL,
  observe_seq BIGINT NOT NULL,
  observe_time TIMESTAMPTZ NOT NULL,
  data_as_of TIMESTAMPTZ NOT NULL,
  latest_price NUMERIC(20,6),
  return_since_first_selected_pct NUMERIC(12,6),
  distance_to_first_high_pct NUMERIC(12,6),
  memory_value_score NUMERIC(12,6),
  pre_signal_score NUMERIC(12,6),
  fake_activation_risk_score NUMERIC(12,6),
  expectation_state TEXT,
  deviation_reason_codes_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  feature_hash TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(memory_entity_id, observe_seq)
);

CREATE INDEX IF NOT EXISTS idx_memory_observation_entity_time
ON decision_memory.memory_observation_snapshot_v1(memory_entity_id, observe_time DESC);
CREATE INDEX IF NOT EXISTS brin_memory_observation_time
ON decision_memory.memory_observation_snapshot_v1 USING BRIN(observe_time);

CREATE TABLE IF NOT EXISTS decision_memory.memory_price_structure_feature_v1 (
  feature_id TEXT PRIMARY KEY,
  memory_entity_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  feature_time TIMESTAMPTZ NOT NULL,
  lookback_window_days INTEGER NOT NULL,
  platform_compression_score NUMERIC(12,6),
  volatility_compression_score NUMERIC(12,6),
  higher_low_score NUMERIC(12,6),
  support_hold_score NUMERIC(12,6),
  breakout_pressure_score NUMERIC(12,6),
  pullback_health_score NUMERIC(12,6),
  distance_to_previous_hot_high_score NUMERIC(12,6),
  source_watermark TIMESTAMPTZ NOT NULL,
  feature_hash TEXT NOT NULL,
  UNIQUE(memory_entity_id, feature_time, lookback_window_days)
);

CREATE TABLE IF NOT EXISTS decision_memory.memory_moneyflow_feature_v1 (
  feature_id TEXT PRIMARY KEY,
  memory_entity_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  feature_time TIMESTAMPTZ NOT NULL,
  moneyflow_delta_3d_score NUMERIC(12,6),
  moneyflow_delta_5d_score NUMERIC(12,6),
  moneyflow_turning_point_score NUMERIC(12,6),
  capital_outflow_decay_score NUMERIC(12,6),
  intraday_support_flow_score NUMERIC(12,6),
  source_watermark TIMESTAMPTZ NOT NULL,
  feature_hash TEXT NOT NULL,
  UNIQUE(memory_entity_id, feature_time)
);

CREATE TABLE IF NOT EXISTS decision_memory.memory_sector_theme_feature_v1 (
  feature_id TEXT PRIMARY KEY,
  memory_entity_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  feature_time TIMESTAMPTZ NOT NULL,
  sector_strength_delta_3d_score NUMERIC(12,6),
  sector_strength_delta_5d_score NUMERIC(12,6),
  relative_sector_rank_change_score NUMERIC(12,6),
  sector_limit_up_breadth_score NUMERIC(12,6),
  theme_heat_recovery_score NUMERIC(12,6),
  theme_leader_confirmation_score NUMERIC(12,6),
  source_watermark TIMESTAMPTZ NOT NULL,
  feature_hash TEXT NOT NULL,
  UNIQUE(memory_entity_id, feature_time)
);

CREATE TABLE IF NOT EXISTS decision_memory.memory_event_signal_feature_v1 (
  feature_id TEXT PRIMARY KEY,
  memory_entity_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  feature_time TIMESTAMPTZ NOT NULL,
  event_id TEXT,
  event_time TIMESTAMPTZ,
  published_at TIMESTAMPTZ,
  available_at TIMESTAMPTZ NOT NULL,
  captured_at TIMESTAMPTZ,
  source TEXT,
  event_type TEXT,
  theme_tags_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  relevance_score NUMERIC(12,6),
  source_reliability_score NUMERIC(12,6),
  novelty_score NUMERIC(12,6),
  catalyst_strength_score NUMERIC(12,6),
  visibility_class TEXT NOT NULL, -- ex_ante / confirmed / post_hoc
  source_payload_hash TEXT,
  feature_hash TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_event_feature_entity_time
ON decision_memory.memory_event_signal_feature_v1(memory_entity_id, feature_time DESC);

CREATE TABLE IF NOT EXISTS decision_memory.memory_pre_signal_feature_window_v1 (
  feature_window_id TEXT PRIMARY KEY,
  memory_entity_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  decision_time TIMESTAMPTZ NOT NULL,
  lookback_windows_json JSONB NOT NULL DEFAULT '[1,3,5,10]'::jsonb,
  memory_value_score NUMERIC(12,6),
  pre_signal_score NUMERIC(12,6),
  structure_score NUMERIC(12,6),
  moneyflow_reactivation_score NUMERIC(12,6),
  sector_resonance_return_score NUMERIC(12,6),
  event_freshness_relevance_score NUMERIC(12,6),
  market_risk_appetite_score NUMERIC(12,6),
  ttl_health_score NUMERIC(12,6),
  fake_activation_risk_score NUMERIC(12,6),
  ex_ante_event_count INTEGER NOT NULL DEFAULT 0,
  post_hoc_event_count INTEGER NOT NULL DEFAULT 0,
  pre_signal_types_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  hard_block_reasons_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  source_gap_codes_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  feature_hash TEXT NOT NULL,
  UNIQUE(memory_entity_id, decision_time)
);

CREATE TABLE IF NOT EXISTS decision_memory.memory_pre_signal_case_v1 (
  pre_signal_case_id TEXT PRIMARY KEY,
  memory_entity_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  detected_at TIMESTAMPTZ NOT NULL,
  pre_signal_window_start TIMESTAMPTZ,
  pre_signal_window_end TIMESTAMPTZ,
  pre_signal_strength_score NUMERIC(12,6),
  pre_signal_types_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  fake_pre_signal_risk_score NUMERIC(12,6),
  ex_ante_event_count INTEGER NOT NULL DEFAULT 0,
  post_hoc_event_count INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL,
  feature_hash TEXT NOT NULL,
  hard_block_reasons_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  source_gap_codes_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  case_hash TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_memory_pre_signal_active
ON decision_memory.memory_pre_signal_case_v1(memory_entity_id, status)
WHERE status IN ('pre_signal_detected','watch_only');

CREATE TABLE IF NOT EXISTS decision_memory.memory_activation_case_v1 (
  activation_case_id TEXT PRIMARY KEY,
  pre_signal_case_id TEXT REFERENCES decision_memory.memory_pre_signal_case_v1(pre_signal_case_id),
  memory_entity_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  activation_detected_at TIMESTAMPTZ NOT NULL,
  activation_quality_score NUMERIC(12,6),
  memory_value_score NUMERIC(12,6),
  pre_signal_score NUMERIC(12,6),
  breakout_quality_score NUMERIC(12,6),
  moneyflow_reactivation_score NUMERIC(12,6),
  sector_resonance_return_score NUMERIC(12,6),
  event_signal_score NUMERIC(12,6),
  ttl_health_score NUMERIC(12,6),
  fake_activation_risk_score NUMERIC(12,6),
  trigger_reason_codes_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  activation_status TEXT NOT NULL,
  hard_block_reasons_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  source_gap_codes_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  feature_hash TEXT,
  activation_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decision_memory.memory_score_fact_v1 (
  score_id TEXT PRIMARY KEY,
  memory_entity_id TEXT NOT NULL,
  activation_case_id TEXT,
  symbol TEXT NOT NULL,
  scored_at TIMESTAMPTZ NOT NULL,
  memory_value_score NUMERIC(12,6),
  pre_signal_score NUMERIC(12,6),
  activation_quality_score NUMERIC(12,6),
  reason_confidence_score NUMERIC(12,6),
  fake_activation_risk_score NUMERIC(12,6),
  model_version TEXT NOT NULL,
  feature_hash TEXT NOT NULL,
  score_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decision_memory.memory_release_gate_audit_v1 (
  release_gate_audit_id TEXT PRIMARY KEY,
  memory_entity_id TEXT NOT NULL,
  activation_case_id TEXT NOT NULL,
  memory_signal_id TEXT,
  symbol TEXT NOT NULL,
  evaluated_at TIMESTAMPTZ NOT NULL,
  release_gate_state TEXT NOT NULL,
  recommendation_eligibility TEXT NOT NULL,
  activation_quality_score NUMERIC(12,6),
  pre_signal_score NUMERIC(12,6),
  fake_activation_risk_score NUMERIC(12,6),
  hard_block_reasons_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  warning_codes_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  audit_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decision_memory.memory_signal_fact_v1 (
  memory_signal_id TEXT PRIMARY KEY,
  memory_entity_id TEXT NOT NULL,
  activation_case_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  published_at TIMESTAMPTZ NOT NULL,
  signal_status TEXT NOT NULL,
  signal_pool TEXT NOT NULL,
  model_version TEXT NOT NULL,
  release_gate_audit_hash TEXT NOT NULL,
  UNIQUE(memory_entity_id, activation_case_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_memory_active_signal_entity
ON decision_memory.memory_signal_fact_v1(memory_entity_id)
WHERE signal_status IN ('official_signal','buy_point_pending','buy_point_confirmed','monitoring');

CREATE TABLE IF NOT EXISTS decision_memory.memory_buy_point_v1 (
  memory_buy_point_id TEXT PRIMARY KEY,
  memory_signal_id TEXT NOT NULL REFERENCES decision_memory.memory_signal_fact_v1(memory_signal_id),
  memory_entity_id TEXT NOT NULL,
  activation_case_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  evaluated_at TIMESTAMPTZ NOT NULL,
  buy_point_state TEXT NOT NULL,
  entry_stage TEXT,
  reference_entry_price NUMERIC(20,6),
  diagnostic_reference_price NUMERIC(20,6),
  block_reasons_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  buy_point_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decision_memory.memory_monitoring_snapshot_v1 (
  monitoring_id TEXT PRIMARY KEY,
  memory_signal_id TEXT NOT NULL,
  memory_entity_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  observe_time TIMESTAMPTZ NOT NULL,
  latest_price NUMERIC(20,6),
  mfe_pct NUMERIC(12,6),
  mae_pct NUMERIC(12,6),
  first_event_type TEXT,
  path_state TEXT,
  snapshot_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decision_memory.memory_outcome_label_v1 (
  memory_signal_id TEXT PRIMARY KEY,
  memory_entity_id TEXT NOT NULL,
  activation_case_id TEXT,
  symbol TEXT NOT NULL,
  labeled_at TIMESTAMPTZ NOT NULL,
  label_maturity_status TEXT NOT NULL,
  outcome_label TEXT NOT NULL,
  direction_outcome TEXT NOT NULL,
  execution_outcome TEXT NOT NULL,
  next_limit_up_hit BOOLEAN NOT NULL DEFAULT false,
  time_to_next_limit_up_days INTEGER,
  pre_signal_lead_days INTEGER,
  time_from_first_hot_to_activation_days INTEGER,
  time_from_activation_to_target_days INTEGER,
  mfe_pct NUMERIC(12,6),
  mae_pct NUMERIC(12,6),
  new_independent_cycle BOOLEAN NOT NULL DEFAULT false,
  include_official_success_rate BOOLEAN NOT NULL DEFAULT false,
  hard_block_reasons_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  outcome_hash TEXT NOT NULL
);

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
  attribution_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decision_memory.memory_pre_limitup_signal_analysis_v1 (
  analysis_id TEXT PRIMARY KEY,
  memory_entity_id TEXT NOT NULL,
  memory_signal_id TEXT,
  symbol TEXT NOT NULL,
  next_limit_up_date DATE,
  lookback_window_days INTEGER NOT NULL,
  earliest_detected_pre_signal_at TIMESTAMPTZ,
  lead_days_before_limit_up INTEGER,
  pre_signal_types_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  pre_signal_strength_score NUMERIC(12,6),
  false_positive_rate_bucket NUMERIC(12,6),
  matched_failed_case_count INTEGER,
  matched_success_case_count INTEGER,
  primary_up_reason TEXT,
  secondary_up_reasons_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  analysis_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decision_memory.memory_failure_attribution_v1 (
  failure_id TEXT PRIMARY KEY,
  memory_signal_id TEXT NOT NULL,
  memory_entity_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  failure_class TEXT NOT NULL,
  failure_reason_codes_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  similar_case_count INTEGER,
  similar_case_failure_rate_pct NUMERIC(12,6),
  created_at TIMESTAMPTZ NOT NULL,
  failure_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decision_memory.memory_evolution_sample_v1 (
  evolution_sample_id TEXT PRIMARY KEY,
  memory_signal_id TEXT,
  memory_entity_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL,
  evolution_state TEXT NOT NULL,
  evolution_labels_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  hard_block_reasons_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  outcome_hash TEXT,
  evolution_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decision_memory.memory_ttl_calibration_v1 (
  calibration_id TEXT PRIMARY KEY,
  model_version TEXT NOT NULL,
  calibration_window_start DATE NOT NULL,
  calibration_window_end DATE NOT NULL,
  segment_key TEXT NOT NULL,
  mature_sample_count INTEGER NOT NULL,
  ttl_days INTEGER NOT NULL,
  realized_next_limit_up_rate NUMERIC(12,6),
  delayed_success_rate NUMERIC(12,6),
  ttl_too_short_count INTEGER NOT NULL DEFAULT 0,
  ttl_too_long_count INTEGER NOT NULL DEFAULT 0,
  activated_at TIMESTAMPTZ,
  is_active BOOLEAN NOT NULL DEFAULT false
);

CREATE TABLE IF NOT EXISTS decision_memory.memory_model_version_evaluation_v1 (
  evaluation_id TEXT PRIMARY KEY,
  model_version TEXT NOT NULL,
  evaluation_window_start DATE NOT NULL,
  evaluation_window_end DATE NOT NULL,
  official_sample_count INTEGER NOT NULL,
  second_wave_success_rate NUMERIC(12,6),
  fake_activation_failure_rate NUMERIC(12,6),
  avg_pre_signal_lead_days NUMERIC(12,6),
  tradable_success_rate NUMERIC(12,6),
  notes TEXT,
  created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS decision_memory.memory_active_case_registry_v1 (
  memory_entity_id TEXT PRIMARY KEY,
  symbol TEXT NOT NULL,
  tracking_pool TEXT NOT NULL,
  priority_level INTEGER NOT NULL DEFAULT 0,
  next_observe_at TIMESTAMPTZ NOT NULL,
  last_observe_at TIMESTAMPTZ,
  observe_frequency_seconds INTEGER NOT NULL,
  memory_status TEXT NOT NULL,
  budget_class TEXT NOT NULL DEFAULT 'normal',
  close_reason TEXT,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_memory_active_due
ON decision_memory.memory_active_case_registry_v1(memory_status, next_observe_at, priority_level DESC);

CREATE TABLE IF NOT EXISTS decision_memory.memory_latest_state_v1 (
  memory_entity_id TEXT PRIMARY KEY,
  symbol TEXT NOT NULL,
  latest_observe_time TIMESTAMPTZ,
  memory_status TEXT NOT NULL,
  memory_value_score NUMERIC(12,6),
  pre_signal_score NUMERIC(12,6),
  activation_quality_score NUMERIC(12,6),
  fake_activation_risk_score NUMERIC(12,6),
  latest_state_payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
