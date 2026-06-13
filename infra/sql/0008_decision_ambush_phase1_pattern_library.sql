-- Ambush Watchlist Phase 1: low-valley pattern library and high-performance feature foundation.
-- Additive only. Does not modify locked hot_candidates or candidate_memory schemas.

CREATE SCHEMA IF NOT EXISTS decision_ambush;
CREATE SCHEMA IF NOT EXISTS governance;

CREATE TABLE IF NOT EXISTS governance.source_capability_audit_v1 (
  audit_id TEXT PRIMARY KEY,
  provider TEXT NOT NULL,
  data_domain TEXT NOT NULL,
  field_name TEXT NOT NULL,
  frequency TEXT NOT NULL,
  history_start_date DATE,
  history_end_date DATE,
  symbol_coverage_rate NUMERIC(12,6),
  date_coverage_rate NUMERIC(12,6),
  missing_rate NUMERIC(12,6),
  available_at_supported BOOLEAN NOT NULL DEFAULT false,
  adjustment_supported BOOLEAN NOT NULL DEFAULT false,
  quality_status TEXT NOT NULL,
  usable_for_pattern_library BOOLEAN NOT NULL DEFAULT false,
  usable_for_online_scoring BOOLEAN NOT NULL DEFAULT false,
  reject_reason TEXT,
  checked_at TIMESTAMPTZ NOT NULL,
  audit_payload_json JSONB NOT NULL,
  audit_hash TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_source_capability_provider_checked_v1
  ON governance.source_capability_audit_v1(provider, checked_at DESC);

CREATE TABLE IF NOT EXISTS decision_ambush.valley_pattern_library_version_v1 (
  library_version_id TEXT PRIMARY KEY,
  library_version TEXT NOT NULL UNIQUE,
  version_state TEXT NOT NULL,
  sample_start_date DATE,
  sample_end_date DATE,
  positive_sample_count INTEGER NOT NULL DEFAULT 0,
  weak_positive_sample_count INTEGER NOT NULL DEFAULT 0,
  hard_negative_sample_count INTEGER NOT NULL DEFAULT 0,
  easy_negative_sample_count INTEGER NOT NULL DEFAULT 0,
  prototype_count INTEGER NOT NULL DEFAULT 0,
  signature_version TEXT NOT NULL,
  formula_version TEXT NOT NULL,
  published_at TIMESTAMPTZ,
  activated_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  library_payload_json JSONB NOT NULL,
  library_hash TEXT NOT NULL,
  CONSTRAINT ck_valley_library_state_v1 CHECK (version_state IN ('draft','candidate','shadow_evaluating','active','superseded','rejected'))
);

CREATE INDEX IF NOT EXISTS ix_valley_library_state_v1
  ON decision_ambush.valley_pattern_library_version_v1(version_state, created_at DESC);

CREATE TABLE IF NOT EXISTS decision_ambush.valley_pattern_sample_v1 (
  sample_id TEXT PRIMARY KEY,
  library_version TEXT NOT NULL,
  symbol TEXT NOT NULL,
  stock_name TEXT,
  local_peak_day DATE,
  decline_start_day DATE,
  local_low_day DATE,
  valley_anchor_day DATE NOT NULL,
  compression_start_day DATE,
  turn_anchor_day DATE,
  confirmation_day DATE,
  window_start_date DATE NOT NULL,
  window_end_date DATE NOT NULL,
  pattern_type TEXT,
  sample_label TEXT NOT NULL,
  hard_negative_flag BOOLEAN NOT NULL DEFAULT false,
  direction_success BOOLEAN NOT NULL DEFAULT false,
  tradable_success BOOLEAN NOT NULL DEFAULT false,
  structure_success BOOLEAN NOT NULL DEFAULT false,
  rebound_quality_score NUMERIC(12,6),
  rebound_mfe_10d_pct NUMERIC(12,6),
  rebound_mfe_20d_pct NUMERIC(12,6),
  post_valley_max_drawdown_pct NUMERIC(12,6),
  relative_market_return_20d_pct NUMERIC(12,6),
  relative_sector_return_20d_pct NUMERIC(12,6),
  next_limit_up_flag BOOLEAN,
  time_to_next_limit_up INTEGER,
  tradable_entry_window_score NUMERIC(12,6),
  price_adjustment_mode TEXT NOT NULL,
  adjustment_version TEXT,
  sample_payload_json JSONB NOT NULL,
  sample_hash TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT ck_valley_sample_label_v1 CHECK (sample_label IN ('strong_positive','weak_positive','hard_negative','easy_negative','blocked'))
);

CREATE INDEX IF NOT EXISTS ix_valley_pattern_sample_symbol_anchor_v1
  ON decision_ambush.valley_pattern_sample_v1(symbol, valley_anchor_day DESC);

CREATE INDEX IF NOT EXISTS ix_valley_pattern_sample_label_v1
  ON decision_ambush.valley_pattern_sample_v1(library_version, sample_label, rebound_quality_score DESC);

CREATE TABLE IF NOT EXISTS decision_ambush.valley_shape_signature_v1 (
  signature_id TEXT PRIMARY KEY,
  library_version TEXT,
  sample_id TEXT,
  symbol TEXT NOT NULL,
  as_of_trading_day DATE NOT NULL,
  window_days INTEGER NOT NULL,
  signature_version TEXT NOT NULL,
  price_adjustment_mode TEXT NOT NULL,
  close_path_json JSONB NOT NULL,
  typical_price_path_json JSONB NOT NULL,
  high_envelope_path_json JSONB NOT NULL,
  low_envelope_path_json JSONB NOT NULL,
  volume_path_json JSONB NOT NULL,
  candlestick_geometry_json JSONB NOT NULL,
  embedding_vector_json JSONB NOT NULL,
  source_gap_codes_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  official_scoring_allowed BOOLEAN NOT NULL DEFAULT false,
  signature_hash TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_valley_shape_signature_symbol_day_v1
  ON decision_ambush.valley_shape_signature_v1(symbol, as_of_trading_day DESC, window_days);

CREATE TABLE IF NOT EXISTS decision_ambush.valley_pattern_prototype_v1 (
  prototype_id TEXT PRIMARY KEY,
  library_version TEXT NOT NULL,
  prototype_type TEXT NOT NULL,
  prototype_label TEXT NOT NULL,
  sample_count INTEGER NOT NULL,
  quality_score NUMERIC(12,6),
  embedding_vector_json JSONB NOT NULL,
  representative_sample_ids_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  prototype_payload_json JSONB NOT NULL,
  prototype_hash TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_valley_pattern_prototype_type_v1
  ON decision_ambush.valley_pattern_prototype_v1(library_version, prototype_type, quality_score DESC);

CREATE TABLE IF NOT EXISTS decision_ambush.valley_pattern_match_result_v1 (
  match_id TEXT PRIMARY KEY,
  library_version TEXT NOT NULL,
  symbol TEXT NOT NULL,
  as_of_trading_day DATE NOT NULL,
  window_days INTEGER NOT NULL,
  signature_hash TEXT NOT NULL,
  top_positive_prototype_id TEXT,
  positive_valley_similarity NUMERIC(12,6),
  top_false_bottom_prototype_id TEXT,
  false_bottom_similarity NUMERIC(12,6),
  top_hard_negative_prototype_id TEXT,
  hard_negative_similarity NUMERIC(12,6),
  shape_edge_score NUMERIC(12,6),
  top_matches_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  formula_version TEXT NOT NULL,
  match_payload_json JSONB NOT NULL,
  match_hash TEXT NOT NULL,
  calculated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_valley_pattern_match_symbol_day_v1
  ON decision_ambush.valley_pattern_match_result_v1(symbol, as_of_trading_day DESC, library_version);

CREATE TABLE IF NOT EXISTS decision_ambush.ambush_daily_window_feature_v1 (
  feature_id TEXT PRIMARY KEY,
  symbol TEXT NOT NULL,
  as_of_trading_day DATE NOT NULL,
  window_days INTEGER NOT NULL,
  price_adjustment_mode TEXT NOT NULL,
  drawdown_pct NUMERIC(12,6),
  downtrend_deceleration_score NUMERIC(12,6),
  support_stability_score NUMERIC(12,6),
  volatility_compression_score NUMERIC(12,6),
  volume_structure_score NUMERIC(12,6),
  valley_maturity_score NUMERIC(12,6),
  compression_breakout_score NUMERIC(12,6),
  source_gap_codes_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  formula_version TEXT NOT NULL,
  feature_payload_json JSONB NOT NULL,
  feature_hash TEXT NOT NULL,
  calculated_at TIMESTAMPTZ NOT NULL,
  UNIQUE(symbol, as_of_trading_day, window_days, formula_version)
);

CREATE INDEX IF NOT EXISTS ix_ambush_daily_feature_day_score_v1
  ON decision_ambush.ambush_daily_window_feature_v1(as_of_trading_day DESC, valley_maturity_score DESC);

CREATE TABLE IF NOT EXISTS decision_ambush.ambush_recall_candidate_v1 (
  recall_id TEXT PRIMARY KEY,
  symbol TEXT NOT NULL,
  as_of_trading_day DATE NOT NULL,
  recall_status TEXT NOT NULL,
  recall_channels_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  pattern_library_version TEXT,
  valley_maturity_score NUMERIC(12,6),
  compression_breakout_score NUMERIC(12,6),
  shape_edge_score NUMERIC(12,6),
  source_gap_codes_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  recall_payload_json JSONB NOT NULL,
  recall_hash TEXT NOT NULL,
  calculated_at TIMESTAMPTZ NOT NULL,
  CONSTRAINT ck_ambush_recall_status_v1 CHECK (recall_status IN ('recalled','not_recalled','blocked'))
);

CREATE INDEX IF NOT EXISTS ix_ambush_recall_day_status_v1
  ON decision_ambush.ambush_recall_candidate_v1(as_of_trading_day DESC, recall_status, valley_maturity_score DESC);

CREATE TABLE IF NOT EXISTS decision_ambush.ambush_formula_registry_v1 (
  formula_code TEXT NOT NULL,
  formula_version TEXT NOT NULL,
  formula_state TEXT NOT NULL,
  financial_purpose TEXT NOT NULL,
  input_data_contract_json JSONB NOT NULL,
  calculation_contract_json JSONB NOT NULL,
  validation_contract_json JSONB NOT NULL,
  limitation_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  activated_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY(formula_code, formula_version),
  CONSTRAINT ck_ambush_formula_state_v1 CHECK (formula_state IN ('research','shadow','active','retired','rejected'))
);

-- Guardrails:
-- 1. Historical sample labels may use post-anchor data, but online recall and scoring must not.
-- 2. Shape calculation uses adjusted OHLC; raw OHLC without adjustment is research-only.
-- 3. Online matching stores TopK only; full DTW precision is offline/shadow evaluation only.
-- 4. Positive and negative/hard-negative samples are mandatory for active library promotion.
