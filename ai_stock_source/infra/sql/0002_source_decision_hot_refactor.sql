BEGIN;

-- v2 refactor: clean source facts + independent hot model domain.
-- The source schema is model-agnostic. decision_hot is the only owner of hot model truth.
CREATE SCHEMA IF NOT EXISTS source;
CREATE SCHEMA IF NOT EXISTS decision_hot;
CREATE SCHEMA IF NOT EXISTS governance;

CREATE TABLE IF NOT EXISTS source.instrument_master_v1 (
    instrument_id BIGINT PRIMARY KEY,
    symbol VARCHAR(16) NOT NULL,
    exchange VARCHAR(16) NOT NULL,
    board VARCHAR(32),
    stock_name VARCHAR(96),
    list_date DATE,
    delist_date DATE,
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    is_st BOOLEAN NOT NULL DEFAULT false,
    is_risk_warning BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(symbol, exchange)
);

CREATE TABLE IF NOT EXISTS source.trade_calendar_v1 (
    trading_day DATE NOT NULL,
    market_code VARCHAR(16) NOT NULL DEFAULT 'CN_A',
    is_open BOOLEAN NOT NULL,
    prev_trading_day DATE,
    next_trading_day DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (trading_day, market_code)
);

CREATE TABLE IF NOT EXISTS source.daily_bar_v1 (
    source_daily_bar_id BIGSERIAL PRIMARY KEY,
    instrument_id BIGINT NOT NULL,
    symbol VARCHAR(16) NOT NULL,
    trading_day DATE NOT NULL,
    adjustment VARCHAR(16) NOT NULL DEFAULT 'qfq',
    open_price NUMERIC(18,6) NOT NULL,
    high_price NUMERIC(18,6) NOT NULL,
    low_price NUMERIC(18,6) NOT NULL,
    close_price NUMERIC(18,6) NOT NULL,
    volume NUMERIC(24,6),
    amount NUMERIC(24,6),
    turnover_rate NUMERIC(18,6),
    event_time TIMESTAMPTZ NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    provider VARCHAR(32) NOT NULL,
    provider_payload_id BIGINT,
    quality_status VARCHAR(32) NOT NULL DEFAULT 'usable',
    payload_hash VARCHAR(96),
    UNIQUE(instrument_id, trading_day, adjustment, provider)
);
CREATE INDEX IF NOT EXISTS idx_source_daily_bar_symbol_day ON source.daily_bar_v1(symbol, trading_day DESC);
CREATE INDEX IF NOT EXISTS idx_source_daily_bar_available ON source.daily_bar_v1(available_at);

CREATE TABLE IF NOT EXISTS source.minute_bar_v1 (
    source_minute_bar_id BIGSERIAL PRIMARY KEY,
    instrument_id BIGINT NOT NULL,
    symbol VARCHAR(16) NOT NULL,
    bar_time TIMESTAMPTZ NOT NULL,
    open_price NUMERIC(18,6) NOT NULL,
    high_price NUMERIC(18,6) NOT NULL,
    low_price NUMERIC(18,6) NOT NULL,
    close_price NUMERIC(18,6) NOT NULL,
    volume NUMERIC(24,6),
    amount NUMERIC(24,6),
    event_time TIMESTAMPTZ NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    provider VARCHAR(32) NOT NULL,
    provider_payload_id BIGINT,
    quality_status VARCHAR(32) NOT NULL DEFAULT 'usable',
    payload_hash VARCHAR(96),
    UNIQUE(instrument_id, bar_time, provider)
);
CREATE INDEX IF NOT EXISTS idx_source_minute_bar_symbol_time ON source.minute_bar_v1(symbol, bar_time DESC);
CREATE INDEX IF NOT EXISTS idx_source_minute_bar_time_brin ON source.minute_bar_v1 USING BRIN(bar_time);
-- Production partition note: source.minute_bar_v1 should be converted to RANGE partitioning by trading day once real provider volume is enabled.

CREATE TABLE IF NOT EXISTS source.realtime_quote_v1 (
    quote_id BIGSERIAL PRIMARY KEY,
    instrument_id BIGINT NOT NULL,
    symbol VARCHAR(16) NOT NULL,
    latest_price NUMERIC(18,6),
    bid_price NUMERIC(18,6),
    ask_price NUMERIC(18,6),
    high_price NUMERIC(18,6),
    low_price NUMERIC(18,6),
    volume NUMERIC(24,6),
    amount NUMERIC(24,6),
    event_time TIMESTAMPTZ NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    provider VARCHAR(32) NOT NULL,
    quality_status VARCHAR(32) NOT NULL DEFAULT 'usable',
    payload_hash VARCHAR(96)
);
CREATE INDEX IF NOT EXISTS idx_source_quote_symbol_time ON source.realtime_quote_v1(symbol, event_time DESC);
CREATE INDEX IF NOT EXISTS idx_source_quote_time_brin ON source.realtime_quote_v1 USING BRIN(event_time);
-- Production partition note: source.realtime_quote_v1 should be RANGE partitioned by event_time/hour or day for high-frequency feeds.

CREATE TABLE IF NOT EXISTS source.auction_snapshot_v1 (
    auction_snapshot_id BIGSERIAL PRIMARY KEY,
    instrument_id BIGINT NOT NULL,
    symbol VARCHAR(16) NOT NULL,
    trading_day DATE NOT NULL,
    snapshot_time TIMESTAMPTZ NOT NULL,
    virtual_open_price NUMERIC(18,6),
    matched_amount NUMERIC(24,6),
    matched_volume NUMERIC(24,6),
    imbalance_ratio NUMERIC(18,6),
    limit_up_price NUMERIC(18,6),
    limit_down_price NUMERIC(18,6),
    event_time TIMESTAMPTZ NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    provider VARCHAR(32) NOT NULL,
    provider_payload_id BIGINT,
    quality_status VARCHAR(32) NOT NULL DEFAULT 'usable',
    payload_hash VARCHAR(96),
    UNIQUE(instrument_id, trading_day, snapshot_time, provider)
);
CREATE INDEX IF NOT EXISTS idx_source_auction_symbol_day_time ON source.auction_snapshot_v1(symbol, trading_day, snapshot_time DESC);

CREATE TABLE IF NOT EXISTS source.moneyflow_stock_snapshot_v1 (
    moneyflow_snapshot_id BIGSERIAL PRIMARY KEY,
    instrument_id BIGINT NOT NULL,
    symbol VARCHAR(16) NOT NULL,
    trading_day DATE NOT NULL,
    as_of_time TIMESTAMPTZ NOT NULL,
    main_net_inflow NUMERIC(24,6),
    large_order_net_inflow NUMERIC(24,6),
    super_large_order_net_inflow NUMERIC(24,6),
    main_net_inflow_pct_rank NUMERIC(18,6),
    large_order_net_inflow_pct_rank NUMERIC(18,6),
    super_large_order_net_inflow_pct_rank NUMERIC(18,6),
    available_at TIMESTAMPTZ NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    provider VARCHAR(32) NOT NULL,
    quality_status VARCHAR(32) NOT NULL DEFAULT 'usable',
    payload_hash VARCHAR(96),
    UNIQUE(instrument_id, as_of_time, provider)
);

CREATE TABLE IF NOT EXISTS source.sector_snapshot_v1 (
    sector_snapshot_id BIGSERIAL PRIMARY KEY,
    sector_code VARCHAR(64) NOT NULL,
    sector_name VARCHAR(128),
    sector_type VARCHAR(32),
    trading_day DATE NOT NULL,
    as_of_time TIMESTAMPTZ NOT NULL,
    heat_score NUMERIC(18,6),
    moneyflow_score NUMERIC(18,6),
    limit_up_count INTEGER,
    down_count INTEGER,
    available_at TIMESTAMPTZ NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    provider VARCHAR(32) NOT NULL,
    quality_status VARCHAR(32) NOT NULL DEFAULT 'usable',
    payload_hash VARCHAR(96),
    UNIQUE(sector_code, as_of_time, provider)
);

CREATE TABLE IF NOT EXISTS source.market_regime_snapshot_v1 (
    market_regime_snapshot_id BIGSERIAL PRIMARY KEY,
    market_code VARCHAR(32) NOT NULL DEFAULT 'CN_A',
    trading_day DATE NOT NULL,
    as_of_time TIMESTAMPTZ NOT NULL,
    breadth_score NUMERIC(18,6),
    risk_appetite_score NUMERIC(18,6),
    limit_up_count INTEGER,
    limit_down_count INTEGER,
    index_return_pct NUMERIC(18,6),
    available_at TIMESTAMPTZ NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    provider VARCHAR(32) NOT NULL,
    quality_status VARCHAR(32) NOT NULL DEFAULT 'usable',
    payload_hash VARCHAR(96),
    UNIQUE(market_code, as_of_time, provider)
);

CREATE TABLE IF NOT EXISTS source.news_event_v1 (
    news_event_id BIGSERIAL PRIMARY KEY,
    event_key VARCHAR(128),
    title TEXT NOT NULL,
    body TEXT,
    entity_type VARCHAR(32),
    entity_id VARCHAR(64),
    direction VARCHAR(32),
    impact_score NUMERIC(18,6),
    publish_time TIMESTAMPTZ NOT NULL,
    first_seen_at TIMESTAMPTZ NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    provider VARCHAR(32) NOT NULL,
    quality_status VARCHAR(32) NOT NULL DEFAULT 'usable',
    payload_hash VARCHAR(96)
);
CREATE INDEX IF NOT EXISTS idx_source_news_entity_time ON source.news_event_v1(entity_type, entity_id, publish_time DESC);

CREATE TABLE IF NOT EXISTS source.source_fact_envelope_v1 (
    fact_key VARCHAR(128) PRIMARY KEY,
    source_domain VARCHAR(64) NOT NULL,
    source_table VARCHAR(128) NOT NULL,
    source_pk VARCHAR(128),
    provider VARCHAR(64) NOT NULL,
    symbol VARCHAR(16),
    instrument_id BIGINT,
    event_time TIMESTAMPTZ NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    quality_status VARCHAR(32) NOT NULL DEFAULT 'usable',
    payload_hash VARCHAR(96) NOT NULL,
    payload_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_source_fact_envelope_symbol_available ON source.source_fact_envelope_v1(symbol, available_at DESC);
CREATE INDEX IF NOT EXISTS idx_source_fact_envelope_domain_time ON source.source_fact_envelope_v1(source_domain, event_time DESC);

CREATE TABLE IF NOT EXISTS source.data_quality_finding_v1 (
    finding_id BIGSERIAL PRIMARY KEY,
    subject_type VARCHAR(64) NOT NULL,
    subject_id VARCHAR(128) NOT NULL,
    source_table VARCHAR(128),
    severity VARCHAR(16) NOT NULL,
    finding_code VARCHAR(128) NOT NULL,
    finding_message TEXT,
    event_time TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS decision_hot.hot_cycle_v1 (
    hot_cycle_id VARCHAR(64) PRIMARY KEY,
    symbol VARCHAR(16) NOT NULL,
    stock_name VARCHAR(96),
    cycle_start_date DATE,
    cycle_start_reason VARCHAR(128),
    cycle_end_date DATE,
    cycle_end_reason VARCHAR(128),
    latest_lifecycle_stage VARCHAR(64) NOT NULL,
    max_board_count INTEGER NOT NULL DEFAULT 0,
    max_return_pct NUMERIC(18,6),
    max_drawdown_pct NUMERIC(18,6),
    primary_theme VARCHAR(128),
    primary_catalyst_id VARCHAR(128),
    cycle_status VARCHAR(32) NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_hot_cycle_symbol_status ON decision_hot.hot_cycle_v1(symbol, cycle_status);

CREATE TABLE IF NOT EXISTS decision_hot.hot_cycle_day_snapshot_v1 (
    hot_cycle_day_id BIGSERIAL PRIMARY KEY,
    hot_cycle_id VARCHAR(64) NOT NULL REFERENCES decision_hot.hot_cycle_v1(hot_cycle_id),
    symbol VARCHAR(16) NOT NULL,
    trade_date DATE NOT NULL,
    is_candidate_today BOOLEAN NOT NULL DEFAULT false,
    p_limit_up_raw NUMERIC(18,6),
    is_limit_up BOOLEAN NOT NULL DEFAULT false,
    is_one_word_limit BOOLEAN NOT NULL DEFAULT false,
    is_t_shape_limit BOOLEAN NOT NULL DEFAULT false,
    is_opened_limit BOOLEAN NOT NULL DEFAULT false,
    limit_up_close_status VARCHAR(64),
    board_count INTEGER NOT NULL DEFAULT 0,
    consecutive_board_count INTEGER NOT NULL DEFAULT 0,
    break_board_flag BOOLEAN NOT NULL DEFAULT false,
    relimit_after_break_flag BOOLEAN NOT NULL DEFAULT false,
    open_price NUMERIC(18,6),
    close_price NUMERIC(18,6),
    high_price NUMERIC(18,6),
    low_price NUMERIC(18,6),
    limit_up_price NUMERIC(18,6),
    turnover_rate NUMERIC(18,6),
    volume_ratio NUMERIC(18,6),
    seal_amount NUMERIC(24,6),
    seal_strength_score NUMERIC(18,6),
    opened_times INTEGER,
    intraday_fade_score NUMERIC(18,6),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(hot_cycle_id, trade_date)
);

CREATE TABLE IF NOT EXISTS decision_hot.hot_decision_case_v1 (
    hot_case_id VARCHAR(64) PRIMARY KEY,
    hot_cycle_id VARCHAR(64) NOT NULL REFERENCES decision_hot.hot_cycle_v1(hot_cycle_id),
    batch_id BIGINT,
    candidate_id BIGINT,
    instrument_id BIGINT,
    symbol VARCHAR(16) NOT NULL,
    stock_name VARCHAR(96),
    trade_date DATE,
    decision_time TIMESTAMPTZ NOT NULL,
    lifecycle_stage_at_decision VARCHAR(64) NOT NULL,
    board_count_at_decision INTEGER NOT NULL DEFAULT 0,
    p_limit_up_raw NUMERIC(18,6),
    p_limit_up_calibrated NUMERIC(18,6),
    case_status VARCHAR(32) NOT NULL DEFAULT 'open',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(batch_id, candidate_id, trade_date)
);
CREATE INDEX IF NOT EXISTS idx_hot_case_symbol_day ON decision_hot.hot_decision_case_v1(symbol, trade_date DESC);

CREATE TABLE IF NOT EXISTS decision_hot.hot_evidence_snapshot_v1 (
    evidence_id BIGSERIAL PRIMARY KEY,
    hot_case_id VARCHAR(64) NOT NULL REFERENCES decision_hot.hot_decision_case_v1(hot_case_id),
    evidence_domain VARCHAR(64) NOT NULL,
    evidence_role VARCHAR(32) NOT NULL,
    evidence_status VARCHAR(32) NOT NULL,
    as_of_time TIMESTAMPTZ NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL,
    source_table VARCHAR(128),
    source_pk VARCHAR(128),
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    quality_status VARCHAR(32) NOT NULL DEFAULT 'unknown',
    gap_codes TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    payload_hash VARCHAR(96),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_hot_evidence_case_domain ON decision_hot.hot_evidence_snapshot_v1(hot_case_id, evidence_domain);

CREATE TABLE IF NOT EXISTS decision_hot.hot_feature_matrix_v1 (
    feature_matrix_id BIGSERIAL PRIMARY KEY,
    hot_case_id VARCHAR(64) NOT NULL REFERENCES decision_hot.hot_decision_case_v1(hot_case_id),
    model_version VARCHAR(64) NOT NULL,
    feature_stage VARCHAR(64) NOT NULL,
    as_of_time TIMESTAMPTZ NOT NULL,
    lifecycle_stage VARCHAR(64) NOT NULL,
    teacher_prior_raw NUMERIC(18,6),
    teacher_prior_calibrated NUMERIC(18,6),
    teacher_reliability_score NUMERIC(18,6),
    teacher_distortion_risk NUMERIC(18,6),
    auction_confirmation_score NUMERIC(18,6),
    capital_follow_through_score NUMERIC(18,6),
    local_confirmation_score NUMERIC(18,6),
    tradability_score NUMERIC(18,6),
    upside_space_score NUMERIC(18,6),
    overheat_risk_score NUMERIC(18,6),
    open_5m_vwap_state VARCHAR(64),
    feature_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    feature_hash VARCHAR(96) NOT NULL,
    gap_codes TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS decision_hot.hot_score_fact_v1 (
    score_id BIGSERIAL PRIMARY KEY,
    hot_case_id VARCHAR(64) NOT NULL REFERENCES decision_hot.hot_decision_case_v1(hot_case_id),
    model_version VARCHAR(64) NOT NULL,
    score_stage VARCHAR(64) NOT NULL,
    pre_auction_score NUMERIC(18,6),
    auction_confirmed_score NUMERIC(18,6),
    open_5m_confirmed_score NUMERIC(18,6),
    official_hot_score NUMERIC(18,6),
    scoring_state VARCHAR(32) NOT NULL,
    recommendation_eligibility VARCHAR(32) NOT NULL,
    main_positive_factors_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    main_negative_factors_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    hard_block_reasons_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    warning_reasons_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    score_hash VARCHAR(96) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS decision_hot.hot_initial_decision_snapshot_v1 (
    initial_snapshot_id VARCHAR(64) PRIMARY KEY,
    hot_case_id VARCHAR(64) NOT NULL REFERENCES decision_hot.hot_decision_case_v1(hot_case_id),
    hot_cycle_id VARCHAR(64) NOT NULL REFERENCES decision_hot.hot_cycle_v1(hot_cycle_id),
    decision_time TIMESTAMPTZ NOT NULL,
    model_version VARCHAR(64) NOT NULL,
    legacy_model_version VARCHAR(64),
    first_score NUMERIC(18,6),
    first_lifecycle_stage VARCHAR(64) NOT NULL,
    first_teacher_prior_raw NUMERIC(18,6),
    first_teacher_prior_calibrated NUMERIC(18,6),
    first_release_gate_status VARCHAR(32) NOT NULL,
    is_immutable_first_decision BOOLEAN NOT NULL DEFAULT true,
    feature_hash VARCHAR(96),
    score_hash VARCHAR(96),
    positive_factors_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    negative_factors_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    snapshot_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(hot_case_id, model_version, decision_time)
);
CREATE INDEX IF NOT EXISTS idx_hot_initial_case_time ON decision_hot.hot_initial_decision_snapshot_v1(hot_case_id, decision_time DESC);

CREATE TABLE IF NOT EXISTS decision_hot.hot_release_gate_audit_v1 (
    release_gate_id BIGSERIAL PRIMARY KEY,
    hot_case_id VARCHAR(64) NOT NULL REFERENCES decision_hot.hot_decision_case_v1(hot_case_id),
    score_id BIGINT,
    gate_version VARCHAR(64) NOT NULL,
    gate_time TIMESTAMPTZ NOT NULL,
    gate_status VARCHAR(32) NOT NULL,
    official_signal_allowed BOOLEAN NOT NULL DEFAULT false,
    signal_stage VARCHAR(32) NOT NULL,
    block_reasons_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    warning_reasons_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    required_evidence_status VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS decision_hot.hot_signal_fact_v1 (
    hot_signal_id VARCHAR(64) PRIMARY KEY,
    hot_case_id VARCHAR(64) NOT NULL REFERENCES decision_hot.hot_decision_case_v1(hot_case_id),
    hot_cycle_id VARCHAR(64) NOT NULL REFERENCES decision_hot.hot_cycle_v1(hot_cycle_id),
    symbol VARCHAR(16) NOT NULL,
    signal_date DATE,
    selected_at TIMESTAMPTZ NOT NULL,
    decision_time TIMESTAMPTZ NOT NULL,
    model_version VARCHAR(64) NOT NULL,
    model_score NUMERIC(18,6),
    signal_stage VARCHAR(32) NOT NULL,
    is_official_signal BOOLEAN NOT NULL DEFAULT false,
    is_research_only BOOLEAN NOT NULL DEFAULT true,
    release_gate_status VARCHAR(32) NOT NULL,
    release_gate_reason JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS decision_hot.hot_buy_point_v1 (
    buy_point_id VARCHAR(64) PRIMARY KEY,
    hot_signal_id VARCHAR(64) NOT NULL REFERENCES decision_hot.hot_signal_fact_v1(hot_signal_id),
    hot_case_id VARCHAR(64) NOT NULL REFERENCES decision_hot.hot_decision_case_v1(hot_case_id),
    hot_cycle_id VARCHAR(64) NOT NULL REFERENCES decision_hot.hot_cycle_v1(hot_cycle_id),
    adapter_code VARCHAR(96) NOT NULL,
    buy_point_version VARCHAR(64) NOT NULL,
    calc_stage VARCHAR(64) NOT NULL,
    reference_entry_price NUMERIC(18,6),
    entry_price_low NUMERIC(18,6),
    entry_price_high NUMERIC(18,6),
    target_price NUMERIC(18,6),
    invalidation_price NUMERIC(18,6),
    risk_reward_ratio NUMERIC(18,6),
    buy_point_status VARCHAR(32) NOT NULL,
    block_reason TEXT,
    calculated_at TIMESTAMPTZ NOT NULL,
    data_as_of TIMESTAMPTZ NOT NULL,
    is_first_valid BOOLEAN NOT NULL DEFAULT false,
    is_frozen_reference BOOLEAN NOT NULL DEFAULT false,
    input_snapshot_hash VARCHAR(96),
    decision_trace_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_hot_first_frozen_reference ON decision_hot.hot_buy_point_v1(hot_signal_id) WHERE is_frozen_reference;

CREATE TABLE IF NOT EXISTS decision_hot.hot_observation_snapshot_v1 (
    observation_id VARCHAR(64) PRIMARY KEY,
    hot_case_id VARCHAR(64) NOT NULL REFERENCES decision_hot.hot_decision_case_v1(hot_case_id),
    hot_cycle_id VARCHAR(64) NOT NULL REFERENCES decision_hot.hot_cycle_v1(hot_cycle_id),
    observe_seq INTEGER NOT NULL,
    observe_time TIMESTAMPTZ NOT NULL,
    data_as_of TIMESTAMPTZ NOT NULL,
    observe_stage VARCHAR(64) NOT NULL,
    latest_price NUMERIC(18,6),
    reference_entry_price NUMERIC(18,6),
    return_from_reference_pct NUMERIC(18,6),
    mfe_pct NUMERIC(18,6),
    mae_pct NUMERIC(18,6),
    first_event_type VARCHAR(64),
    expectation_state VARCHAR(64) NOT NULL,
    deviation_reason_codes TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    support_strength_score NUMERIC(18,6),
    contradiction_score NUMERIC(18,6),
    freshness_status VARCHAR(32) NOT NULL,
    quality_status VARCHAR(32) NOT NULL,
    sequence_no BIGINT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(hot_case_id, observe_seq)
);
CREATE INDEX IF NOT EXISTS idx_hot_observation_case_time ON decision_hot.hot_observation_snapshot_v1(hot_case_id, observe_time DESC);
CREATE INDEX IF NOT EXISTS idx_hot_observation_time_brin ON decision_hot.hot_observation_snapshot_v1 USING BRIN(observe_time);
-- Production partition note: decision_hot.hot_observation_snapshot_v1 should be RANGE partitioned by observe_time before full-market high-frequency tracking.

CREATE TABLE IF NOT EXISTS decision_hot.hot_outcome_label_v1 (
    outcome_id BIGSERIAL PRIMARY KEY,
    hot_case_id VARCHAR(64) NOT NULL REFERENCES decision_hot.hot_decision_case_v1(hot_case_id),
    hot_signal_id VARCHAR(64),
    label_version VARCHAR(64) NOT NULL,
    direction_outcome VARCHAR(64) NOT NULL,
    execution_outcome VARCHAR(64) NOT NULL,
    path_outcome VARCHAR(64),
    environment_outcome VARCHAR(64),
    data_outcome VARCHAR(64),
    validation_status VARCHAR(64) NOT NULL,
    t5_status VARCHAR(64),
    t20_status VARCHAR(64),
    first_target_hit_at TIMESTAMPTZ,
    first_target_hit_trade_day DATE,
    first_invalidation_hit_at TIMESTAMPTZ,
    first_event_type VARCHAR(64),
    actual_days_to_target INTEGER,
    mfe_pct NUMERIC(18,6),
    mae_pct NUMERIC(18,6),
    max_return_pct NUMERIC(18,6),
    max_drawdown_pct NUMERIC(18,6),
    relative_market_return_pct NUMERIC(18,6),
    relative_sector_return_pct NUMERIC(18,6),
    label_maturity_status VARCHAR(64) NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(hot_case_id, label_version)
);

CREATE TABLE IF NOT EXISTS decision_hot.hot_failure_attribution_v1 (
    failure_attribution_id BIGSERIAL PRIMARY KEY,
    hot_case_id VARCHAR(64) NOT NULL REFERENCES decision_hot.hot_decision_case_v1(hot_case_id),
    outcome_id BIGINT,
    failure_causality_type VARCHAR(64) NOT NULL,
    primary_failure_reason VARCHAR(128) NOT NULL,
    secondary_failure_reasons_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    similar_case_bucket VARCHAR(128),
    similar_case_count INTEGER,
    similar_case_failure_rate_pct NUMERIC(18,6),
    is_systematic_pattern BOOLEAN NOT NULL DEFAULT false,
    evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS decision_hot.hot_first_output_distortion_analysis_v1 (
    distortion_analysis_id BIGSERIAL PRIMARY KEY,
    hot_case_id VARCHAR(64) NOT NULL REFERENCES decision_hot.hot_decision_case_v1(hot_case_id),
    first_model_version VARCHAR(64) NOT NULL,
    first_score NUMERIC(18,6),
    first_lifecycle_stage VARCHAR(64),
    first_teacher_prior_raw NUMERIC(18,6),
    first_teacher_prior_calibrated NUMERIC(18,6),
    first_local_confirmation NUMERIC(18,6),
    first_auction_confirmation NUMERIC(18,6),
    first_overheat_risk NUMERIC(18,6),
    final_outcome VARCHAR(64),
    distortion_type VARCHAR(64) NOT NULL,
    primary_distortion_factor VARCHAR(128),
    secondary_distortion_factors JSONB NOT NULL DEFAULT '[]'::jsonb,
    is_systematic_pattern BOOLEAN NOT NULL DEFAULT false,
    similar_case_count INTEGER,
    similar_case_success_rate NUMERIC(18,6),
    recommended_correction JSONB NOT NULL DEFAULT '{}'::jsonb,
    analysis_status VARCHAR(32) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS decision_hot.hot_research_sample_pool_v1 (
    pool_record_id VARCHAR(64) PRIMARY KEY,
    hot_case_id VARCHAR(64) NOT NULL REFERENCES decision_hot.hot_decision_case_v1(hot_case_id),
    hot_cycle_id VARCHAR(64) REFERENCES decision_hot.hot_cycle_v1(hot_cycle_id),
    symbol VARCHAR(16),
    trade_date DATE,
    lifecycle_stage VARCHAR(64),
    probability_bucket VARCHAR(32),
    teacher_prior_raw NUMERIC(18,6),
    official_hot_score NUMERIC(18,6),
    release_gate_status VARCHAR(64),
    signal_stage VARCHAR(64),
    tracking_pool VARCHAR(64) NOT NULL,
    should_track BOOLEAN NOT NULL DEFAULT true,
    tracking_frequency_hint VARCHAR(128),
    tracking_reason_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
    include_in_official_success_rate BOOLEAN NOT NULL DEFAULT false,
    include_in_teacher_calibration BOOLEAN NOT NULL DEFAULT false,
    include_in_model_evolution BOOLEAN NOT NULL DEFAULT false,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS decision_hot.hot_teacher_calibration_v1 (
    calibration_id BIGSERIAL PRIMARY KEY,
    calibration_version VARCHAR(64) NOT NULL,
    lifecycle_stage VARCHAR(64) NOT NULL,
    probability_bucket VARCHAR(32) NOT NULL,
    market_regime_bucket VARCHAR(64) NOT NULL DEFAULT 'all',
    sector_heat_bucket VARCHAR(64) NOT NULL DEFAULT 'all',
    sample_count INTEGER NOT NULL,
    evaluated_count INTEGER NOT NULL,
    realized_hit_rate NUMERIC(18,6),
    brier_score NUMERIC(18,6),
    lift_vs_overall NUMERIC(18,6),
    can_activate BOOLEAN NOT NULL DEFAULT false,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(calibration_version, lifecycle_stage, probability_bucket, market_regime_bucket, sector_heat_bucket)
);

CREATE TABLE IF NOT EXISTS decision_hot.hot_evolution_sample_v1 (
    evolution_sample_id VARCHAR(64) PRIMARY KEY,
    hot_case_id VARCHAR(64) NOT NULL REFERENCES decision_hot.hot_decision_case_v1(hot_case_id),
    hot_cycle_id VARCHAR(64) NOT NULL REFERENCES decision_hot.hot_cycle_v1(hot_cycle_id),
    source_observation_id VARCHAR(64),
    sample_type VARCHAR(128) NOT NULL,
    lifecycle_stage_at_decision VARCHAR(64),
    feature_at_decision_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    observation_summary_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    outcome_label VARCHAR(64),
    execution_label VARCHAR(64),
    failure_reason VARCHAR(128),
    correction_direction VARCHAR(128),
    recommended_adjustment_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    sample_weight NUMERIC(18,6) NOT NULL DEFAULT 1,
    maturity_status VARCHAR(64) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS decision_hot.hot_model_version_evaluation_v1 (
    model_version_evaluation_id BIGSERIAL PRIMARY KEY,
    model_version VARCHAR(64) NOT NULL,
    evaluation_window_start DATE,
    evaluation_window_end DATE,
    lifecycle_stage VARCHAR(64) DEFAULT 'all',
    sample_count INTEGER NOT NULL,
    official_signal_count INTEGER NOT NULL,
    direction_success_rate NUMERIC(18,6),
    execution_success_rate NUMERIC(18,6),
    avg_mfe_pct NUMERIC(18,6),
    avg_mae_pct NUMERIC(18,6),
    relative_market_alpha_pct NUMERIC(18,6),
    relative_sector_alpha_pct NUMERIC(18,6),
    systematic_failure_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    version_status VARCHAR(32) NOT NULL DEFAULT 'candidate',
    generated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS governance.model_signal_registry_v1 (
    registry_id BIGSERIAL PRIMARY KEY,
    global_signal_id VARCHAR(96) NOT NULL UNIQUE,
    model_domain VARCHAR(64) NOT NULL,
    model_signal_id VARCHAR(96) NOT NULL,
    symbol VARCHAR(16) NOT NULL,
    signal_date DATE,
    is_official_signal BOOLEAN NOT NULL DEFAULT false,
    latest_status VARCHAR(64) NOT NULL DEFAULT 'unknown',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS governance.model_task_registry_v1 (
    task_id BIGSERIAL PRIMARY KEY,
    task_code VARCHAR(128) NOT NULL UNIQUE,
    model_domain VARCHAR(64),
    task_group VARCHAR(64) NOT NULL,
    schedule_hint VARCHAR(128),
    owner_service VARCHAR(128) NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT true,
    last_triggered_at TIMESTAMPTZ,
    last_status VARCHAR(64) DEFAULT 'never_run',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);


-- Phase 6 production compute tables. The model truth remains in decision_hot.*.
-- typed source tables are used for high-volume feature computation, while envelope is audit only.
CREATE UNIQUE INDEX IF NOT EXISTS uq_hot_active_cycle_symbol ON decision_hot.hot_cycle_v1(symbol) WHERE cycle_status = 'active';

CREATE TABLE IF NOT EXISTS decision_hot.hot_cycle_day_feature_v1 (
    feature_id VARCHAR(96) PRIMARY KEY,
    symbol VARCHAR(16) NOT NULL,
    trade_date DATE NOT NULL,
    is_limit_up BOOLEAN NOT NULL DEFAULT false,
    is_one_word_limit BOOLEAN NOT NULL DEFAULT false,
    is_t_shape_limit BOOLEAN NOT NULL DEFAULT false,
    is_opened_limit BOOLEAN NOT NULL DEFAULT false,
    board_count INTEGER NOT NULL DEFAULT 0,
    consecutive_board_count INTEGER NOT NULL DEFAULT 0,
    break_board_flag BOOLEAN NOT NULL DEFAULT false,
    relimit_after_break_flag BOOLEAN NOT NULL DEFAULT false,
    turnover_rate NUMERIC(18,6),
    volume_ratio NUMERIC(18,6),
    seal_amount NUMERIC(24,6),
    seal_strength_score NUMERIC(18,6),
    opened_times INTEGER,
    intraday_fade_score NUMERIC(18,6),
    open_price NUMERIC(18,6),
    high_price NUMERIC(18,6),
    low_price NUMERIC(18,6),
    close_price NUMERIC(18,6),
    calculated_at TIMESTAMPTZ NOT NULL,
    feature_hash VARCHAR(96) NOT NULL,
    UNIQUE(symbol, trade_date)
);

CREATE TABLE IF NOT EXISTS decision_hot.hot_intraday_feature_snapshot_v1 (
    feature_id VARCHAR(96) PRIMARY KEY,
    symbol VARCHAR(16) NOT NULL,
    snapshot_time TIMESTAMPTZ NOT NULL,
    latest_price NUMERIC(18,6),
    vwap_state VARCHAR(64),
    intraday_drawdown_pct NUMERIC(18,6),
    volume_ratio NUMERIC(18,6),
    moneyflow_state VARCHAR(64),
    sector_state VARCHAR(64),
    market_state VARCHAR(64),
    calculated_at TIMESTAMPTZ NOT NULL,
    feature_hash VARCHAR(96) NOT NULL,
    UNIQUE(symbol, snapshot_time)
);
CREATE INDEX IF NOT EXISTS idx_hot_intraday_feature_symbol_time ON decision_hot.hot_intraday_feature_snapshot_v1(symbol, snapshot_time DESC);

CREATE TABLE IF NOT EXISTS decision_hot.hot_execution_feature_snapshot_v1 (
    feature_id VARCHAR(96) PRIMARY KEY,
    hot_case_id VARCHAR(64) REFERENCES decision_hot.hot_decision_case_v1(hot_case_id),
    symbol VARCHAR(16) NOT NULL,
    calc_stage VARCHAR(64) NOT NULL,
    auction_price NUMERIC(18,6),
    auction_matched_amount NUMERIC(24,6),
    auction_imbalance_ratio NUMERIC(18,6),
    open_5m_vwap NUMERIC(18,6),
    entry_vs_vwap_deviation_pct NUMERIC(18,6),
    open_gap_pct NUMERIC(18,6),
    open_overheat_score NUMERIC(18,6),
    no_fill_risk_score NUMERIC(18,6),
    calculated_at TIMESTAMPTZ NOT NULL,
    feature_hash VARCHAR(96) NOT NULL,
    UNIQUE(hot_case_id, calc_stage)
);

CREATE TABLE IF NOT EXISTS decision_hot.hot_active_case_registry_v1 (
    hot_case_id VARCHAR(64) PRIMARY KEY REFERENCES decision_hot.hot_decision_case_v1(hot_case_id),
    hot_cycle_id VARCHAR(64) NOT NULL REFERENCES decision_hot.hot_cycle_v1(hot_cycle_id),
    tracking_pool VARCHAR(64) NOT NULL,
    priority_level INTEGER NOT NULL DEFAULT 0,
    next_observe_at TIMESTAMPTZ NOT NULL,
    last_observe_at TIMESTAMPTZ,
    observe_frequency_seconds INTEGER NOT NULL DEFAULT 300,
    case_status VARCHAR(32) NOT NULL DEFAULT 'active',
    close_reason VARCHAR(64),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_hot_active_due ON decision_hot.hot_active_case_registry_v1(case_status, next_observe_at, priority_level DESC);

CREATE TABLE IF NOT EXISTS decision_hot.hot_case_latest_state_v1 (
    hot_case_id VARCHAR(64) PRIMARY KEY REFERENCES decision_hot.hot_decision_case_v1(hot_case_id),
    hot_cycle_id VARCHAR(64) NOT NULL REFERENCES decision_hot.hot_cycle_v1(hot_cycle_id),
    latest_observation_id VARCHAR(64),
    latest_price NUMERIC(18,6),
    return_from_reference_pct NUMERIC(18,6),
    mfe_pct NUMERIC(18,6),
    mae_pct NUMERIC(18,6),
    first_event_type VARCHAR(64),
    expectation_state VARCHAR(64),
    freshness_status VARCHAR(32),
    quality_status VARCHAR(32),
    monitoring_status VARCHAR(64) NOT NULL DEFAULT 'monitoring',
    sequence_no BIGINT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS decision_hot.hot_calibration_job_v1 (
    calibration_job_id VARCHAR(96) PRIMARY KEY,
    calibration_version VARCHAR(96) NOT NULL,
    training_window_start DATE NOT NULL,
    training_window_end DATE NOT NULL,
    calibration_cutoff_time TIMESTAMPTZ NOT NULL,
    raw_sample_count INTEGER NOT NULL,
    mature_sample_count INTEGER NOT NULL,
    can_activate BOOLEAN NOT NULL DEFAULT false,
    activation_status VARCHAR(64) NOT NULL,
    report_json JSONB NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS decision_hot.hot_teacher_calibration_version_v1 (
    calibration_version VARCHAR(96) PRIMARY KEY,
    training_window_start DATE NOT NULL,
    training_window_end DATE NOT NULL,
    calibration_cutoff_time TIMESTAMPTZ NOT NULL,
    mature_sample_count INTEGER NOT NULL,
    min_total_samples INTEGER NOT NULL,
    activation_status VARCHAR(64) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT false,
    activated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS decision_hot.hot_candidate_model_version_v1 (
    candidate_model_version VARCHAR(96) PRIMARY KEY,
    base_model_version VARCHAR(96) NOT NULL,
    candidate_reason TEXT NOT NULL,
    generated_from_calibration_version VARCHAR(96),
    status VARCHAR(32) NOT NULL DEFAULT 'candidate',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS decision_hot.hot_shadow_run_result_v1 (
    shadow_run_id VARCHAR(96) PRIMARY KEY,
    candidate_model_version VARCHAR(96) NOT NULL,
    sample_count INTEGER NOT NULL,
    direction_success_rate NUMERIC(18,6),
    execution_success_rate NUMERIC(18,6),
    avg_mfe_pct NUMERIC(18,6),
    avg_mae_pct NUMERIC(18,6),
    validation_status VARCHAR(64) NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- DB-backed scheduler primitives: task execution is idempotent, leased, retryable and auditable.
CREATE TABLE IF NOT EXISTS governance.task_instance_v1 (
    task_instance_id VARCHAR(96) PRIMARY KEY,
    task_code VARCHAR(128) NOT NULL,
    owner_service VARCHAR(128) NOT NULL,
    biz_key VARCHAR(128) NOT NULL,
    scheduled_at TIMESTAMPTZ NOT NULL,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    retry_count INTEGER NOT NULL DEFAULT 0,
    next_retry_at TIMESTAMPTZ,
    idempotency_key VARCHAR(128) NOT NULL UNIQUE,
    input_hash VARCHAR(96) NOT NULL,
    output_hash VARCHAR(96),
    error_code VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_governance_task_due ON governance.task_instance_v1(status, scheduled_at);

CREATE TABLE IF NOT EXISTS governance.task_lease_v1 (
    task_instance_id VARCHAR(96) PRIMARY KEY REFERENCES governance.task_instance_v1(task_instance_id),
    lease_owner VARCHAR(128) NOT NULL,
    lease_until TIMESTAMPTZ NOT NULL,
    acquired_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS governance.task_dead_letter_v1 (
    dead_letter_id VARCHAR(96) PRIMARY KEY,
    task_instance_id VARCHAR(96) NOT NULL,
    task_code VARCHAR(128) NOT NULL,
    owner_service VARCHAR(128) NOT NULL,
    error_code VARCHAR(128) NOT NULL,
    error_message TEXT,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS governance.task_run_log_v1 (
    task_run_log_id VARCHAR(96) PRIMARY KEY,
    task_instance_id VARCHAR(96) NOT NULL,
    event_type VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    message TEXT,
    event_time TIMESTAMPTZ NOT NULL DEFAULT now(),
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb
);

COMMIT;
