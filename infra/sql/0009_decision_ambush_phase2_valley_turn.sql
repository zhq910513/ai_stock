-- Ambush Watchlist Phase 2: valley watch pool and effective-turn anchor.
-- Additive only. Does not modify locked hot_candidates or candidate_memory schemas.

CREATE SCHEMA IF NOT EXISTS decision_ambush;

CREATE TABLE IF NOT EXISTS decision_ambush.valley_watch_pool_v1 (
  valley_id TEXT PRIMARY KEY,
  symbol TEXT NOT NULL,
  instrument_id BIGINT,
  as_of_trading_day DATE NOT NULL,
  trade_date DATE NOT NULL,
  pool_state TEXT NOT NULL,
  valley_status TEXT NOT NULL,
  window_days INTEGER NOT NULL,
  primary_trough_day DATE,
  primary_trough_low NUMERIC(18,6),
  primary_trough_age_days INTEGER,
  drawdown_pct NUMERIC(12,6),
  distance_from_low_pct NUMERIC(12,6),
  price_adjustment_mode TEXT NOT NULL,
  pattern_library_version TEXT,
  formula_version TEXT NOT NULL,
  valley_maturity_score NUMERIC(12,6),
  pattern_match_score NUMERIC(12,6),
  weekly_structure_score NUMERIC(12,6),
  false_rebound_risk NUMERIC(12,6),
  hard_negative_similarity NUMERIC(12,6),
  false_bottom_similarity NUMERIC(12,6),
  valley_components_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  risk_components_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  market_structure_context_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  source_gap_codes_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  block_reason_codes_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  research_only_reason_codes_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  evidence_refs_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  formula_governance_json JSONB NOT NULL,
  payload_json JSONB NOT NULL,
  payload_hash TEXT NOT NULL,
  calculated_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT ck_valley_watch_pool_state_v1 CHECK (pool_state IN ('valley_watch','research_only','not_qualified','valley_invalidated','data_blocked')),
  UNIQUE(symbol, as_of_trading_day, formula_version)
);

CREATE INDEX IF NOT EXISTS ix_valley_watch_day_state_score_v1
  ON decision_ambush.valley_watch_pool_v1(as_of_trading_day DESC, pool_state, valley_maturity_score DESC);

CREATE INDEX IF NOT EXISTS ix_valley_watch_symbol_day_v1
  ON decision_ambush.valley_watch_pool_v1(symbol, as_of_trading_day DESC);

CREATE TABLE IF NOT EXISTS decision_ambush.effective_turn_anchor_v1 (
  turn_anchor_id TEXT PRIMARY KEY,
  valley_id TEXT,
  symbol TEXT NOT NULL,
  instrument_id BIGINT,
  as_of_trading_day DATE NOT NULL,
  trade_date DATE NOT NULL,
  l1_status TEXT NOT NULL,
  pool_target TEXT NOT NULL,
  anchor_type TEXT,
  effective_turn_anchor_day DATE,
  effective_turn_age_days INTEGER,
  primary_trough_day DATE,
  primary_trough_age_days INTEGER,
  post_turn_return_pct NUMERIC(12,6),
  post_trough_return_pct NUMERIC(12,6),
  consecutive_up_days INTEGER,
  close_strength NUMERIC(12,6),
  volume_ratio NUMERIC(12,6),
  turn_freshness_score NUMERIC(12,6),
  effective_turn_score NUMERIC(12,6),
  micro_breakout_quality NUMERIC(12,6),
  support_hold_score NUMERIC(12,6),
  gentle_volume_recovery_score NUMERIC(12,6),
  runaway_risk NUMERIC(12,6),
  upper_shadow_risk NUMERIC(12,6),
  compression_start_day DATE,
  compression_range_pct NUMERIC(12,6),
  price_adjustment_mode TEXT NOT NULL,
  formula_version TEXT NOT NULL,
  source_gap_codes_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  reject_reason_codes_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  evidence_refs_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  formula_governance_json JSONB NOT NULL,
  payload_json JSONB NOT NULL,
  payload_hash TEXT NOT NULL,
  calculated_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT ck_effective_turn_l1_status_v1 CHECK (l1_status IN ('accepted','backup_only','rejected')),
  CONSTRAINT ck_effective_turn_pool_target_v1 CHECK (pool_target IN ('effective_turn_pool','effective_turn_pool_research_only','remain_valley_watch_pool','none')),
  UNIQUE(symbol, as_of_trading_day, formula_version)
);

CREATE INDEX IF NOT EXISTS ix_effective_turn_day_status_score_v1
  ON decision_ambush.effective_turn_anchor_v1(as_of_trading_day DESC, l1_status, effective_turn_score DESC);

CREATE INDEX IF NOT EXISTS ix_effective_turn_symbol_anchor_v1
  ON decision_ambush.effective_turn_anchor_v1(symbol, effective_turn_anchor_day DESC);

CREATE TABLE IF NOT EXISTS decision_ambush.effective_turn_pool_v1 (
  pool_item_id TEXT PRIMARY KEY,
  symbol TEXT NOT NULL,
  valley_id TEXT,
  turn_anchor_id TEXT,
  as_of_trading_day DATE NOT NULL,
  pool_state TEXT NOT NULL,
  pool_entered_at TIMESTAMPTZ NOT NULL,
  anchor_type TEXT,
  effective_turn_anchor_day DATE,
  turn_freshness_score NUMERIC(12,6),
  effective_turn_score NUMERIC(12,6),
  valley_maturity_score NUMERIC(12,6),
  false_rebound_risk NUMERIC(12,6),
  next_required_confirmation_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  invalidation_conditions_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  source_gap_codes_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  formula_version TEXT NOT NULL,
  payload_json JSONB NOT NULL,
  payload_hash TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT ck_effective_turn_pool_state_v1 CHECK (pool_state IN ('active','research_only','invalidated','promoted_to_deep_confirmation','expired'))
);

CREATE INDEX IF NOT EXISTS ix_effective_turn_pool_day_state_score_v1
  ON decision_ambush.effective_turn_pool_v1(as_of_trading_day DESC, pool_state, effective_turn_score DESC);

CREATE TABLE IF NOT EXISTS decision_ambush.ambush_pool_transition_audit_v1 (
  transition_id TEXT PRIMARY KEY,
  symbol TEXT NOT NULL,
  instrument_id BIGINT,
  from_pool TEXT NOT NULL,
  to_pool TEXT NOT NULL,
  from_status TEXT,
  to_status TEXT,
  decision_result TEXT NOT NULL,
  trigger_event TEXT NOT NULL,
  trigger_as_of_time TIMESTAMPTZ NOT NULL,
  trigger_snapshot_type TEXT NOT NULL,
  trigger_feature_json JSONB NOT NULL,
  decision_rule_version TEXT NOT NULL,
  created_by_job TEXT NOT NULL,
  evidence_refs_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  formula_governance_json JSONB NOT NULL,
  payload_json JSONB NOT NULL,
  transition_hash TEXT NOT NULL,
  calculated_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT ck_ambush_transition_result_v1 CHECK (decision_result IN ('created','research_only','not_created'))
);

CREATE INDEX IF NOT EXISTS ix_ambush_transition_symbol_time_v1
  ON decision_ambush.ambush_pool_transition_audit_v1(symbol, trigger_as_of_time DESC);

-- Guardrails:
-- 1. Phase 2 remains pre-signal research/pool movement; it must not produce official release signals.
-- 2. effective_turn_anchor_v1 may only use data with trading_day <= as_of_trading_day.
-- 3. Missing adjusted OHLC or weekly context can enter research-only but cannot enter official effective_turn_pool.
-- 4. Hard-negative similarity and false-rebound risk are explicit blockers before deep confirmation.
