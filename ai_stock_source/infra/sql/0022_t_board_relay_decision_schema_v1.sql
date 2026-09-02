CREATE SCHEMA IF NOT EXISTS decision_t_relay;
CREATE SCHEMA IF NOT EXISTS research_t_relay;

CREATE TABLE IF NOT EXISTS decision_t_relay.t_board_day1_candidate_v1 (
    day1_candidate_pk BIGSERIAL PRIMARY KEY,
    day1_candidate_id TEXT NOT NULL,
    canonical_symbol TEXT,
    stock_name TEXT,
    trade_date DATE,
    candidate_status TEXT NOT NULL,
    reject_reason TEXT,
    is_t_board BOOLEAN,
    float_market_cap NUMERIC,
    float_market_cap_pass BOOLEAN,
    seal_commitment_score NUMERIC,
    disagreement_absorption_score NUMERIC,
    fake_seal_trap_risk_score NUMERIC,
    source_gap_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
    run_id TEXT,
    model_version TEXT NOT NULL,
    feature_version TEXT,
    rule_version TEXT,
    request_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    result_payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_t_board_day1_candidate_symbol_day
    ON decision_t_relay.t_board_day1_candidate_v1(canonical_symbol, trade_date);
CREATE INDEX IF NOT EXISTS idx_t_board_day1_candidate_status
    ON decision_t_relay.t_board_day1_candidate_v1(candidate_status, created_at DESC);

CREATE TABLE IF NOT EXISTS decision_t_relay.t_board_day2_watch_snapshot_v1 (
    day2_watch_pk BIGSERIAL PRIMARY KEY,
    day2_watch_snapshot_id TEXT NOT NULL,
    day1_candidate_id TEXT,
    canonical_symbol TEXT,
    day2_trade_date DATE,
    as_of_time TIMESTAMPTZ,
    watch_status TEXT NOT NULL,
    near_limit_flag BOOLEAN,
    distance_to_up_limit_pct NUMERIC,
    market_context_status TEXT,
    dynamic_feature_run_id TEXT,
    source_gap_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
    run_id TEXT,
    model_version TEXT NOT NULL,
    feature_version TEXT,
    request_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    result_payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_t_board_day2_watch_symbol_day
    ON decision_t_relay.t_board_day2_watch_snapshot_v1(canonical_symbol, day2_trade_date, as_of_time);

CREATE TABLE IF NOT EXISTS decision_t_relay.t_board_day2_entry_trigger_v1 (
    entry_trigger_pk BIGSERIAL PRIMARY KEY,
    entry_trigger_id TEXT NOT NULL,
    day1_candidate_id TEXT,
    canonical_symbol TEXT,
    day2_trade_date DATE,
    trigger_time TEXT,
    entry_trigger_status TEXT NOT NULL,
    not_trigger_reason TEXT,
    near_limit_flag BOOLEAN,
    order_consumption_side TEXT,
    order_consumption_amount NUMERIC,
    near_limit_order_absorption_score NUMERIC,
    relay_consensus_score NUMERIC,
    market_context_status TEXT,
    dynamic_feature_run_id TEXT,
    source_gap_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
    run_id TEXT,
    model_version TEXT NOT NULL,
    feature_version TEXT,
    request_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    result_payload JSONB NOT NULL,
    game_hypothesis_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_t_board_day2_trigger_symbol_day
    ON decision_t_relay.t_board_day2_entry_trigger_v1(canonical_symbol, day2_trade_date, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_t_board_day2_trigger_status
    ON decision_t_relay.t_board_day2_entry_trigger_v1(entry_trigger_status, created_at DESC);

CREATE TABLE IF NOT EXISTS decision_t_relay.t_board_post_entry_monitor_v1 (
    post_entry_monitor_pk BIGSERIAL PRIMARY KEY,
    post_entry_monitor_id TEXT NOT NULL,
    entry_trigger_id TEXT,
    canonical_symbol TEXT,
    day2_trade_date DATE,
    post_entry_status TEXT NOT NULL,
    outcome_label TEXT,
    post_entry_board_opened BOOLEAN,
    close_on_limit_flag BOOLEAN,
    control_failure_score NUMERIC,
    source_gap_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
    run_id TEXT,
    model_version TEXT NOT NULL,
    feature_version TEXT,
    request_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    result_payload JSONB NOT NULL,
    game_hypothesis_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_t_board_post_entry_symbol_day
    ON decision_t_relay.t_board_post_entry_monitor_v1(canonical_symbol, day2_trade_date, created_at DESC);

CREATE TABLE IF NOT EXISTS decision_t_relay.t_board_day3_exit_decision_v1 (
    day3_decision_pk BIGSERIAL PRIMARY KEY,
    day3_decision_id TEXT NOT NULL,
    entry_trigger_id TEXT,
    canonical_symbol TEXT,
    day3_trade_date DATE,
    day3_action TEXT NOT NULL,
    action_reason TEXT,
    day3_open_limit_up_flag BOOLEAN,
    tail_limit_up_flag BOOLEAN,
    source_gap_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
    run_id TEXT,
    model_version TEXT NOT NULL,
    feature_version TEXT,
    request_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    result_payload JSONB NOT NULL,
    game_hypothesis_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_t_board_day3_exit_symbol_day
    ON decision_t_relay.t_board_day3_exit_decision_v1(canonical_symbol, day3_trade_date, created_at DESC);

CREATE TABLE IF NOT EXISTS decision_t_relay.t_board_outcome_label_v1 (
    outcome_label_pk BIGSERIAL PRIMARY KEY,
    outcome_label_id TEXT NOT NULL,
    entry_trigger_id TEXT,
    day1_candidate_id TEXT,
    canonical_symbol TEXT,
    day1_trade_date DATE,
    day2_trade_date DATE,
    day3_trade_date DATE,
    outcome_label TEXT NOT NULL,
    label_reason TEXT,
    label_version TEXT NOT NULL,
    source_gap_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
    run_id TEXT,
    model_version TEXT NOT NULL,
    feature_version TEXT,
    request_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    result_payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_t_board_outcome_symbol_day
    ON decision_t_relay.t_board_outcome_label_v1(canonical_symbol, day2_trade_date, created_at DESC);

CREATE TABLE IF NOT EXISTS decision_t_relay.t_board_game_hypothesis_snapshot_v1 (
    game_hypothesis_pk BIGSERIAL PRIMARY KEY,
    game_hypothesis_id TEXT NOT NULL,
    canonical_symbol TEXT,
    trade_date DATE,
    stage TEXT NOT NULL,
    related_entity_id TEXT,
    dominant_capital_intent TEXT,
    game_state_label TEXT,
    confidence_level TEXT,
    evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    related_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    run_id TEXT,
    model_version TEXT NOT NULL,
    feature_version TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_t_board_game_hypothesis_symbol_day
    ON decision_t_relay.t_board_game_hypothesis_snapshot_v1(canonical_symbol, trade_date, stage, created_at DESC);

CREATE TABLE IF NOT EXISTS decision_t_relay.t_board_observation_monitor_snapshot_v1 (
    observation_snapshot_pk BIGSERIAL PRIMARY KEY,
    observation_snapshot_id TEXT NOT NULL,
    day1_candidate_id TEXT,
    entry_trigger_id TEXT,
    canonical_symbol TEXT,
    stock_name TEXT,
    trade_date DATE,
    day_index INTEGER,
    as_of_time TIMESTAMPTZ,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    monitor_interval_minutes INTEGER NOT NULL DEFAULT 5,
    observation_status TEXT NOT NULL,
    current_stage TEXT,
    current_conclusion TEXT,
    key_reason TEXT,
    risk_tip TEXT,
    next_observation TEXT,
    model_score NUMERIC,
    model_score_label TEXT,
    score_state TEXT,
    model_score_version TEXT,
    relay_strength_label TEXT,
    day1_trade_date DATE,
    day2_trade_date DATE,
    day2_trigger_time TEXT,
    day3_trade_date DATE,
    latest_snapshot_time TIMESTAMPTZ,
    last_monitor_at TEXT,
    monitoring_summary TEXT,
    data_gap_count INTEGER NOT NULL DEFAULT 0,
    data_gap_labels JSONB NOT NULL DEFAULT '[]'::jsonb,
    warning_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
    run_id TEXT,
    model_version TEXT NOT NULL,
    score_version TEXT,
    request_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    result_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_t_board_observation_monitor_symbol_time
    ON decision_t_relay.t_board_observation_monitor_snapshot_v1(canonical_symbol, trade_date, as_of_time DESC);
CREATE INDEX IF NOT EXISTS idx_t_board_observation_monitor_candidate_time
    ON decision_t_relay.t_board_observation_monitor_snapshot_v1(day1_candidate_id, captured_at DESC);
CREATE INDEX IF NOT EXISTS idx_t_board_observation_monitor_score
    ON decision_t_relay.t_board_observation_monitor_snapshot_v1(model_score DESC, captured_at DESC);

CREATE TABLE IF NOT EXISTS research_t_relay.t_board_research_sample_v1 (
    research_sample_pk BIGSERIAL PRIMARY KEY,
    sample_id TEXT NOT NULL,
    canonical_symbol TEXT,
    trade_date DATE,
    stage TEXT NOT NULL,
    sample_status TEXT NOT NULL,
    source_gap_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
    decision_ref JSONB NOT NULL DEFAULT '{}'::jsonb,
    research_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_t_board_research_sample_symbol_day
    ON research_t_relay.t_board_research_sample_v1(canonical_symbol, trade_date, stage, created_at DESC);
