-- Model 3 / ambush_watchlist Phase 3 + Phase 4 closure.
-- Additive only. Does not modify locked hot_candidates or candidate_memory schemas.

CREATE SCHEMA IF NOT EXISTS decision_ambush;

CREATE TABLE IF NOT EXISTS decision_ambush.deep_confirmation_pool_v1 (
    deep_confirmation_id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    instrument_id BIGINT,
    trade_date DATE NOT NULL,
    calculated_at TIMESTAMPTZ NOT NULL,
    phase3_version TEXT NOT NULL,
    formula_version TEXT NOT NULL,
    deep_state TEXT NOT NULL,
    l2_structure_score NUMERIC(12, 6),
    l3_capital_volume_score NUMERIC(12, 6),
    l4_environment_score NUMERIC(12, 6),
    moneyflow_repair_score NUMERIC(12, 6),
    sector_market_support_score NUMERIC(12, 6),
    tradability_score NUMERIC(12, 6),
    false_rebound_risk NUMERIC(12, 6),
    deep_confirmation_score NUMERIC(12, 6),
    ambush_score NUMERIC(12, 6),
    block_reason_codes_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    research_only_reason_codes_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    source_gap_codes_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    evidence_refs_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    formula_governance_json JSONB NOT NULL,
    payload_hash TEXT NOT NULL UNIQUE
);

CREATE INDEX IF NOT EXISTS idx_deep_confirmation_pool_symbol_date_v1
    ON decision_ambush.deep_confirmation_pool_v1(symbol, trade_date DESC);

CREATE TABLE IF NOT EXISTS decision_ambush.ambush_feature_matrix_v1 (
    feature_matrix_id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    trade_date DATE NOT NULL,
    feature_time TIMESTAMPTZ NOT NULL,
    available_at TIMESTAMPTZ,
    formula_version TEXT NOT NULL,
    pattern_library_version TEXT,
    feature_json JSONB NOT NULL,
    source_gap_codes_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    payload_hash TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS decision_ambush.ambush_score_fact_v1 (
    score_fact_id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    trade_date DATE NOT NULL,
    calculated_at TIMESTAMPTZ NOT NULL,
    formula_version TEXT NOT NULL,
    valley_maturity_score NUMERIC(12, 6),
    effective_turn_score NUMERIC(12, 6),
    l2_structure_score NUMERIC(12, 6),
    l3_capital_volume_score NUMERIC(12, 6),
    l4_environment_score NUMERIC(12, 6),
    false_rebound_risk NUMERIC(12, 6),
    tradability_score NUMERIC(12, 6),
    ambush_score NUMERIC(12, 6),
    source_gap_codes_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    formula_governance_json JSONB NOT NULL,
    payload_hash TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS decision_ambush.ambush_release_gate_audit_v1 (
    release_gate_id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    instrument_id BIGINT,
    trade_date DATE NOT NULL,
    calculated_at TIMESTAMPTZ NOT NULL,
    phase3_version TEXT NOT NULL,
    formula_version TEXT NOT NULL,
    release_decision TEXT NOT NULL,
    signal_state TEXT NOT NULL,
    ambush_score NUMERIC(12, 6),
    deep_confirmation_score NUMERIC(12, 6),
    false_rebound_risk NUMERIC(12, 6),
    tradability_score NUMERIC(12, 6),
    hard_block_codes_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    warning_codes_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    source_gap_codes_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    evidence_refs_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    formula_governance_json JSONB NOT NULL,
    payload_hash TEXT NOT NULL UNIQUE
);

CREATE INDEX IF NOT EXISTS idx_ambush_release_gate_symbol_date_v1
    ON decision_ambush.ambush_release_gate_audit_v1(symbol, trade_date DESC);

CREATE TABLE IF NOT EXISTS decision_ambush.ambush_signal_fact_v1 (
    signal_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    instrument_id BIGINT,
    trade_date DATE NOT NULL,
    published_at TIMESTAMPTZ,
    signal_state TEXT NOT NULL,
    ambush_score NUMERIC(12, 6),
    deep_confirmation_score NUMERIC(12, 6),
    valley_maturity_score NUMERIC(12, 6),
    effective_turn_score NUMERIC(12, 6),
    false_rebound_risk NUMERIC(12, 6),
    effective_turn_anchor_day DATE,
    release_gate_hash TEXT,
    formula_version TEXT NOT NULL,
    pattern_library_version TEXT,
    evidence_refs_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    payload_hash TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS decision_ambush.ambush_buy_point_v1 (
    buy_point_id BIGSERIAL PRIMARY KEY,
    signal_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    trade_date DATE NOT NULL,
    buy_point_version TEXT NOT NULL,
    reference_entry_price NUMERIC(18, 6),
    entry_price_basis TEXT NOT NULL,
    valid_for_evaluation BOOLEAN NOT NULL DEFAULT FALSE,
    frozen_at TIMESTAMPTZ,
    formula_governance_json JSONB NOT NULL,
    payload_hash TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS decision_ambush.ambush_observation_snapshot_v1 (
    observation_id BIGSERIAL PRIMARY KEY,
    signal_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    trade_date DATE NOT NULL,
    as_of_trading_day DATE NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    phase4_version TEXT NOT NULL,
    formula_version TEXT NOT NULL,
    reference_entry_price NUMERIC(18, 6),
    mfe_pct NUMERIC(12, 6),
    mae_pct NUMERIC(12, 6),
    close_return_pct NUMERIC(12, 6),
    observation_state TEXT NOT NULL,
    append_only BOOLEAN NOT NULL DEFAULT TRUE,
    formula_governance_json JSONB NOT NULL,
    payload_hash TEXT NOT NULL UNIQUE
);

CREATE INDEX IF NOT EXISTS idx_ambush_observation_signal_date_v1
    ON decision_ambush.ambush_observation_snapshot_v1(signal_id, as_of_trading_day DESC);

CREATE TABLE IF NOT EXISTS decision_ambush.ambush_latest_state_v1 (
    signal_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    trade_date DATE NOT NULL,
    latest_as_of_trading_day DATE NOT NULL,
    latest_observation_state TEXT NOT NULL,
    latest_mfe_pct NUMERIC(12, 6),
    latest_mae_pct NUMERIC(12, 6),
    updated_at TIMESTAMPTZ NOT NULL,
    source_observation_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decision_ambush.ambush_outcome_label_v1 (
    outcome_id BIGSERIAL PRIMARY KEY,
    signal_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    trade_date DATE NOT NULL,
    maturity_days INT NOT NULL,
    maturity_day DATE NOT NULL,
    labeled_at TIMESTAMPTZ NOT NULL,
    phase4_version TEXT NOT NULL,
    formula_version TEXT NOT NULL,
    outcome_label TEXT NOT NULL,
    direction_success BOOLEAN NOT NULL,
    tradable_success BOOLEAN NOT NULL,
    structure_success BOOLEAN NOT NULL,
    mfe_pct NUMERIC(12, 6),
    mae_pct NUMERIC(12, 6),
    close_return_pct NUMERIC(12, 6),
    append_only BOOLEAN NOT NULL DEFAULT TRUE,
    formula_governance_json JSONB NOT NULL,
    payload_hash TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS decision_ambush.ambush_failure_attribution_v1 (
    attribution_id BIGSERIAL PRIMARY KEY,
    signal_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    trade_date DATE NOT NULL,
    attributed_at TIMESTAMPTZ NOT NULL,
    phase4_version TEXT NOT NULL,
    outcome_label TEXT NOT NULL,
    primary_failure_reasons_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    release_gate_hash TEXT,
    evolution_action TEXT NOT NULL,
    append_only BOOLEAN NOT NULL DEFAULT TRUE,
    formula_governance_json JSONB NOT NULL,
    payload_hash TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS decision_ambush.ambush_evolution_sample_v1 (
    evolution_sample_id BIGSERIAL PRIMARY KEY,
    signal_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    trade_date DATE NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    source_outcome_hash TEXT NOT NULL,
    source_attribution_hash TEXT,
    evolution_action TEXT NOT NULL,
    sample_payload_json JSONB NOT NULL,
    append_only BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS decision_ambush.ambush_formula_version_evaluation_v1 (
    evaluation_id BIGSERIAL PRIMARY KEY,
    formula_version TEXT NOT NULL,
    pattern_library_version TEXT,
    evaluation_window_start DATE NOT NULL,
    evaluation_window_end DATE NOT NULL,
    market_regime TEXT,
    bucket_metrics_json JSONB NOT NULL,
    hard_negative_metrics_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    walk_forward_metrics_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    recommendation TEXT NOT NULL,
    evaluated_at TIMESTAMPTZ NOT NULL
);
