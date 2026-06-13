BEGIN;

CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

-- Running upgrade  -> 0001_current_baseline

CREATE SCHEMA IF NOT EXISTS raw;

CREATE SCHEMA IF NOT EXISTS core;

CREATE SCHEMA IF NOT EXISTS market;

CREATE SCHEMA IF NOT EXISTS news;

CREATE SCHEMA IF NOT EXISTS decision;

CREATE SCHEMA IF NOT EXISTS explain;

DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace WHERE n.nspname = 'core' AND t.typname = 'provider_enum') THEN CREATE TYPE core.provider_enum AS ENUM ('THS', 'EASTMONEY', 'BAIDU', 'SINA', 'TENCENT', 'COINGECKO', 'YAHOO', 'JIN10', 'SYSTEM', 'MANUAL'); END IF; END $$;;

DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace WHERE n.nspname = 'core' AND t.typname = 'instrument_status_enum') THEN CREATE TYPE core.instrument_status_enum AS ENUM ('active', 'halted', 'delisted', 'unknown'); END IF; END $$;;

DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace WHERE n.nspname = 'core' AND t.typname = 'board_enum') THEN CREATE TYPE core.board_enum AS ENUM ('main_sh', 'main_sz', 'chinext', 'star', 'bse', 'other'); END IF; END $$;;

DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace WHERE n.nspname = 'market' AND t.typname = 'trade_status_enum') THEN CREATE TYPE market.trade_status_enum AS ENUM ('pre_open', 'auction_open', 'auction_freeze', 'pre_continuous', 'continuous_am', 'mid_break', 'continuous_pm', 'after_close', 'closed', 'unknown'); END IF; END $$;;

DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace WHERE n.nspname = 'market' AND t.typname = 'theme_type_enum') THEN CREATE TYPE market.theme_type_enum AS ENUM ('industry', 'concept', 'style', 'region', 'other'); END IF; END $$;;

DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace WHERE n.nspname = 'market' AND t.typname = 'candidate_batch_status_enum') THEN CREATE TYPE market.candidate_batch_status_enum AS ENUM ('draft_created', 'awaiting_paid_prior', 'production_submitted', 'contract_failed', 'evidence_collecting', 'preopen_ready', 'open_observing', 'outcome_pending', 'evaluated', 'superseded'); END IF; END $$;;

DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace WHERE n.nspname = 'market' AND t.typname = 'cross_market_asset_class_enum') THEN CREATE TYPE market.cross_market_asset_class_enum AS ENUM ('equity_index', 'crypto_spot', 'crypto_global', 'fx', 'volatility_index', 'commodity', 'macro_proxy', 'other'); END IF; END $$;;

DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace WHERE n.nspname = 'news' AND t.typname = 'event_type_enum') THEN CREATE TYPE news.event_type_enum AS ENUM ('macro', 'policy', 'regulatory', 'earnings', 'guidance', 'mna', 'supply_chain', 'industry', 'company', 'crypto', 'us_market', 'commodity', 'capital_flow', 'rumor', 'other'); END IF; END $$;;

DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace WHERE n.nspname = 'news' AND t.typname = 'market_scope_enum') THEN CREATE TYPE news.market_scope_enum AS ENUM ('symbol', 'theme', 'market_cn', 'market_global', 'mixed'); END IF; END $$;;

DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace WHERE n.nspname = 'news' AND t.typname = 'direction_enum') THEN CREATE TYPE news.direction_enum AS ENUM ('positive', 'negative', 'neutral', 'risk_on', 'risk_off', 'mixed', 'unknown'); END IF; END $$;;

DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace WHERE n.nspname = 'news' AND t.typname = 'entity_type_enum') THEN CREATE TYPE news.entity_type_enum AS ENUM ('instrument', 'theme', 'market', 'crypto', 'global_asset'); END IF; END $$;;

DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace WHERE n.nspname = 'decision' AND t.typname = 'run_type_enum') THEN CREATE TYPE decision.run_type_enum AS ENUM ('overnight_baseline', 'preopen_refresh', 'auction_recheck', 'event_recheck', 'manual_refresh'); END IF; END $$;;

DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace WHERE n.nspname = 'decision' AND t.typname = 'run_status_enum') THEN CREATE TYPE decision.run_status_enum AS ENUM ('queued', 'running', 'succeeded', 'failed', 'partial'); END IF; END $$;;

DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace WHERE n.nspname = 'decision' AND t.typname = 'version_status_enum') THEN CREATE TYPE decision.version_status_enum AS ENUM ('draft', 'active', 'frozen', 'superseded', 'expired'); END IF; END $$;;

DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace WHERE n.nspname = 'decision' AND t.typname = 'item_state_enum') THEN CREATE TYPE decision.item_state_enum AS ENUM ('active', 'watch', 'challenged', 'suppressed', 'replaced', 'expired'); END IF; END $$;;

DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace WHERE n.nspname = 'decision' AND t.typname = 'reason_type_enum') THEN CREATE TYPE decision.reason_type_enum AS ENUM ('event', 'auction', 'moneyflow', 'rule', 'manual', 'model_refresh', 'timeout_degrade', 'other'); END IF; END $$;;

CREATE TABLE core.instrument_master (
    instrument_id BIGSERIAL NOT NULL, 
    symbol VARCHAR(16) NOT NULL, 
    exchange VARCHAR(8) NOT NULL, 
    board core.board_enum NOT NULL, 
    name VARCHAR(64) NOT NULL, 
    provider_symbol VARCHAR(32) NOT NULL, 
    trading_rule_profile VARCHAR(64) NOT NULL, 
    list_date DATE, 
    delist_date DATE, 
    limit_pct NUMERIC(12, 6), 
    is_st BOOLEAN, 
    lot_size INTEGER, 
    currency VARCHAR(8) DEFAULT 'CNY' NOT NULL, 
    status core.instrument_status_enum DEFAULT 'active'::core.instrument_status_enum NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_instrument_master PRIMARY KEY (instrument_id)
);

CREATE UNIQUE INDEX uq_instrument_symbol_exchange ON core.instrument_master (symbol, exchange);

CREATE INDEX idx_instrument_board_status ON core.instrument_master (board, status);

CREATE INDEX idx_instrument_provider_symbol ON core.instrument_master (provider_symbol);

CREATE INDEX idx_instrument_name ON core.instrument_master (name);

CREATE TABLE core.trading_calendar (
    trading_day DATE NOT NULL, 
    market_code VARCHAR(16) DEFAULT 'CN_A' NOT NULL, 
    is_open BOOLEAN NOT NULL, 
    prev_trading_day DATE, 
    next_trading_day DATE, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_trading_calendar PRIMARY KEY (trading_day)
);

CREATE TABLE decision.cross_market_feature_snapshot (
    snapshot_id BIGSERIAL NOT NULL, 
    trading_day DATE NOT NULL, 
    as_of_time TIMESTAMP WITH TIME ZONE NOT NULL, 
    feature_set_version VARCHAR(32) NOT NULL, 
    features_json JSONB NOT NULL, 
    data_quality NUMERIC(12, 6), 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_cross_market_feature_snapshot PRIMARY KEY (snapshot_id)
);

CREATE UNIQUE INDEX uq_cross_market_feature_snapshot ON decision.cross_market_feature_snapshot (trading_day, as_of_time, feature_set_version);

CREATE INDEX idx_cross_market_feature_snapshot_day ON decision.cross_market_feature_snapshot (trading_day, as_of_time);

CREATE TABLE decision.recommendation_version (
    version_id BIGSERIAL NOT NULL, 
    run_id BIGINT NOT NULL, 
    version_no INTEGER NOT NULL, 
    generated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    effective_from TIMESTAMP WITH TIME ZONE, 
    effective_to TIMESTAMP WITH TIME ZONE, 
    status decision.version_status_enum DEFAULT 'draft'::decision.version_status_enum NOT NULL, 
    freeze_reason VARCHAR(64), 
    weight_profile_id BIGINT, 
    is_published BOOLEAN DEFAULT false NOT NULL, 
    objective_horizon_days INTEGER, 
    objective_target_return_pct NUMERIC(12, 6), 
    objective_entry_basis VARCHAR(32), 
    objective_profile_scope VARCHAR(96), 
    objective_applied_profile_scope VARCHAR(96), 
    objective_used_fallback_profile BOOLEAN, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_recommendation_version PRIMARY KEY (version_id)
);

CREATE UNIQUE INDEX uq_recommendation_version_no ON decision.recommendation_version (run_id, version_no);

CREATE INDEX idx_recommendation_version_status ON decision.recommendation_version (status, generated_at);

CREATE TABLE decision.recommendation_calibration_report (
    report_id BIGSERIAL NOT NULL, 
    version_id BIGINT NOT NULL, 
    evaluation_window_days INTEGER NOT NULL, 
    entry_basis VARCHAR(32) DEFAULT 'open_5m_vwap' NOT NULL, 
    target_return_pct NUMERIC(12, 6), 
    sample_size INTEGER NOT NULL, 
    evaluated_items INTEGER NOT NULL, 
    target_hits INTEGER NOT NULL, 
    missed_alpha_count INTEGER DEFAULT '0' NOT NULL, 
    false_positive_count INTEGER DEFAULT '0' NOT NULL, 
    validated_pick_count INTEGER DEFAULT '0' NOT NULL, 
    neutral_count INTEGER DEFAULT '0' NOT NULL, 
    avg_max_return_pct NUMERIC(12, 6), 
    avg_close_return_pct NUMERIC(12, 6), 
    avg_max_drawdown_pct NUMERIC(12, 6), 
    report_status VARCHAR(24) DEFAULT 'pending' NOT NULL, 
    suggestion_json JSONB, 
    generated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_recommendation_calibration_report PRIMARY KEY (report_id)
);

CREATE UNIQUE INDEX uq_recommendation_calibration_report_version_window ON decision.recommendation_calibration_report (version_id, evaluation_window_days, entry_basis, target_return_pct) NULLS NOT DISTINCT;

CREATE INDEX idx_recommendation_calibration_report_status ON decision.recommendation_calibration_report (report_status, generated_at);

CREATE TABLE decision.recommendation_rolling_calibration_report (
    report_id BIGSERIAL NOT NULL, 
    profile_scope VARCHAR(96) DEFAULT 'global' NOT NULL, 
    trading_day_anchor DATE NOT NULL, 
    lookback_trading_days INTEGER NOT NULL, 
    evaluation_window_days INTEGER NOT NULL, 
    entry_basis VARCHAR(32) DEFAULT 'open_5m_vwap' NOT NULL, 
    target_return_pct NUMERIC(12, 6), 
    version_count INTEGER NOT NULL, 
    sample_size INTEGER NOT NULL, 
    evaluated_items INTEGER NOT NULL, 
    target_hits INTEGER NOT NULL, 
    missed_alpha_count INTEGER NOT NULL, 
    false_positive_count INTEGER NOT NULL, 
    validated_pick_count INTEGER NOT NULL, 
    neutral_count INTEGER NOT NULL, 
    avg_max_return_pct NUMERIC(12, 6), 
    avg_close_return_pct NUMERIC(12, 6), 
    avg_max_drawdown_pct NUMERIC(12, 6), 
    report_status VARCHAR(32) NOT NULL, 
    suggestion_json JSONB, 
    generated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_recommendation_rolling_calibration_report PRIMARY KEY (report_id)
);

CREATE INDEX idx_rec_rolling_calibration_report_status ON decision.recommendation_rolling_calibration_report (profile_scope, report_status, generated_at);

CREATE UNIQUE INDEX uq_rec_rolling_calibration_report_anchor ON decision.recommendation_rolling_calibration_report (profile_scope, trading_day_anchor, lookback_trading_days, evaluation_window_days, entry_basis, target_return_pct) NULLS NOT DISTINCT;

CREATE TABLE decision.weight_profile (
    weight_profile_id BIGSERIAL NOT NULL, 
    profile_name VARCHAR(64) NOT NULL, 
    profile_scope VARCHAR(96) DEFAULT 'global' NOT NULL, 
    profile_status VARCHAR(16) DEFAULT 'draft' NOT NULL, 
    source_report_id BIGINT, 
    source_rolling_report_id BIGINT, 
    weights_json JSONB NOT NULL, 
    constraints_json JSONB, 
    notes TEXT, 
    activated_at TIMESTAMP WITH TIME ZONE, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_weight_profile PRIMARY KEY (weight_profile_id)
);

CREATE UNIQUE INDEX uq_weight_profile_name ON decision.weight_profile (profile_name);

CREATE INDEX idx_weight_profile_active_scope ON decision.weight_profile (profile_scope, profile_status, activated_at);

CREATE TABLE decision.dynamic_feature_run (
    run_id BIGSERIAL NOT NULL, 
    scope VARCHAR(32) NOT NULL, 
    as_of_trading_day DATE NOT NULL, 
    as_of_time TIMESTAMP WITH TIME ZONE NOT NULL, 
    feature_set_version VARCHAR(48) NOT NULL, 
    status VARCHAR(24) DEFAULT 'running' NOT NULL, 
    requested_subject_count INTEGER DEFAULT '0' NOT NULL, 
    computed_subject_count INTEGER DEFAULT '0' NOT NULL, 
    snapshot_count INTEGER DEFAULT '0' NOT NULL, 
    source_gap_count INTEGER DEFAULT '0' NOT NULL, 
    window_seconds_json JSONB NOT NULL, 
    run_contract_json JSONB, 
    started_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    finished_at TIMESTAMP WITH TIME ZONE, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_dynamic_feature_run PRIMARY KEY (run_id)
);

CREATE INDEX idx_dynamic_feature_run_status ON decision.dynamic_feature_run (status, started_at);

CREATE INDEX idx_dynamic_feature_run_scope_day ON decision.dynamic_feature_run (scope, as_of_trading_day, started_at);

CREATE TABLE decision.hot_candidate_teacher_distortion_report_v1 (
    report_id BIGSERIAL NOT NULL, 
    scope VARCHAR(32) NOT NULL, 
    business_date DATE, 
    window_trading_days INTEGER, 
    model_version VARCHAR(48) NOT NULL, 
    evaluated_count INTEGER NOT NULL, 
    high_score_failure_count INTEGER NOT NULL, 
    low_score_success_count INTEGER NOT NULL, 
    learning_gate VARCHAR(32) NOT NULL, 
    report_json JSONB NOT NULL, 
    generated_at_utc TIMESTAMP WITH TIME ZONE NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_hot_candidate_teacher_distortion_report_v1 PRIMARY KEY (report_id)
);

CREATE INDEX idx_hot_teacher_distortion_report_v1_scope ON decision.hot_candidate_teacher_distortion_report_v1 (scope, business_date, generated_at_utc);

CREATE TABLE decision.model_feature_usage (
    usage_id BIGSERIAL NOT NULL, 
    model_name VARCHAR(48) NOT NULL, 
    model_version VARCHAR(48) NOT NULL, 
    feature_code VARCHAR(96) NOT NULL, 
    feature_role VARCHAR(32) NOT NULL, 
    feature_source VARCHAR(96), 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_model_feature_usage PRIMARY KEY (usage_id)
);

CREATE UNIQUE INDEX uq_model_feature_usage ON decision.model_feature_usage (model_name, model_version, feature_code);

CREATE TABLE decision.model_performance_metric_v1 (
    metric_id BIGSERIAL NOT NULL, 
    model_name VARCHAR(48) NOT NULL, 
    model_version VARCHAR(48) NOT NULL, 
    scope VARCHAR(32) NOT NULL, 
    scope_ref VARCHAR(128), 
    metric_date DATE, 
    metric_code VARCHAR(96) NOT NULL, 
    metric_value NUMERIC(20, 8), 
    sample_count INTEGER DEFAULT '0' NOT NULL, 
    included_label_status VARCHAR(24) DEFAULT 'evaluated' NOT NULL, 
    metric_status VARCHAR(32) NOT NULL, 
    metric_json JSONB, 
    generated_at_utc TIMESTAMP WITH TIME ZONE NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_model_performance_metric_v1 PRIMARY KEY (metric_id), 
    CONSTRAINT ck_model_performance_metric_v1_evaluated_only CHECK (included_label_status = 'evaluated')
);

CREATE UNIQUE INDEX uq_model_performance_metric_v1 ON decision.model_performance_metric_v1 (model_name, model_version, scope, scope_ref, metric_code) NULLS NOT DISTINCT;

CREATE TABLE decision.candidate_memory_job_run (
    run_id BIGSERIAL NOT NULL, 
    job_name VARCHAR(96) NOT NULL, 
    model_version VARCHAR(64) DEFAULT 'candidate_memory_v1' NOT NULL, 
    run_stage VARCHAR(48) NOT NULL, 
    as_of_trading_day DATE, 
    as_of_time_utc TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    status VARCHAR(32) NOT NULL, 
    input_count INTEGER DEFAULT '0' NOT NULL, 
    success_count INTEGER DEFAULT '0' NOT NULL, 
    failed_count INTEGER DEFAULT '0' NOT NULL, 
    skipped_count INTEGER DEFAULT '0' NOT NULL, 
    error_code VARCHAR(96), 
    error_message TEXT, 
    run_payload JSONB DEFAULT '{}'::jsonb NOT NULL, 
    started_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    finished_at TIMESTAMP WITH TIME ZONE, 
    CONSTRAINT pk_candidate_memory_job_run PRIMARY KEY (run_id), 
    CONSTRAINT ck_candidate_memory_job_run_status_allowed CHECK (status IN ('running','success','partial','failed','skipped')), 
    CONSTRAINT ck_candidate_memory_job_run_counts_non_negative CHECK (input_count >= 0 AND success_count >= 0 AND failed_count >= 0 AND skipped_count >= 0)
);

CREATE INDEX idx_candidate_memory_job_run_stage ON decision.candidate_memory_job_run (job_name, run_stage, started_at);

CREATE TABLE decision.candidate_memory_state_transition_audit_v1 (
    transition_id BIGSERIAL NOT NULL, 
    symbol TEXT NOT NULL, 
    from_state TEXT NOT NULL, 
    to_state TEXT NOT NULL, 
    transition_time TIMESTAMP WITH TIME ZONE NOT NULL, 
    transition_reason TEXT NOT NULL, 
    trigger_feature_snapshot JSONB NOT NULL, 
    evidence_refs BIGINT[], 
    model_version TEXT NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_candidate_memory_state_transition_audit_v1 PRIMARY KEY (transition_id)
);

CREATE INDEX idx_cm_transition_audit_symbol_time ON decision.candidate_memory_state_transition_audit_v1 (symbol, transition_time);

CREATE INDEX idx_cm_transition_audit_state ON decision.candidate_memory_state_transition_audit_v1 (from_state, to_state);

CREATE UNIQUE INDEX uq_cm_transition_audit_identity ON decision.candidate_memory_state_transition_audit_v1 (symbol, transition_time, from_state, to_state, model_version);

CREATE TABLE decision.candidate_memory_performance_metric_v1 (
    metric_id BIGSERIAL NOT NULL, 
    as_of_trading_day DATE NOT NULL, 
    model_version VARCHAR(64) DEFAULT 'candidate_memory_v1' NOT NULL, 
    label_profile_version VARCHAR(64) DEFAULT 'candidate_memory_label_v1' NOT NULL, 
    metric_scope VARCHAR(48) NOT NULL, 
    window_scope VARCHAR(48) NOT NULL, 
    bucket_type VARCHAR(48), 
    bucket_value VARCHAR(96), 
    included_label_status VARCHAR(32) DEFAULT 'evaluated' NOT NULL, 
    sample_count INTEGER DEFAULT '0' NOT NULL, 
    minimum_sample_count INTEGER NOT NULL, 
    metric_status VARCHAR(32) NOT NULL, 
    memory_top1_hit_rate NUMERIC(12, 6), 
    memory_top3_hit_rate NUMERIC(12, 6), 
    memory_top5_hit_rate NUMERIC(12, 6), 
    delayed_follow_through_rate NUMERIC(12, 6), 
    second_wave_success_rate NUMERIC(12, 6), 
    slow_trend_value_rate NUMERIC(12, 6), 
    memory_invalidated_rate NUMERIC(12, 6), 
    risk_before_memory_hit_rate NUMERIC(12, 6), 
    avg_return NUMERIC(12, 6), 
    median_return NUMERIC(12, 6), 
    max_drawdown NUMERIC(12, 6), 
    coverage_rate NUMERIC(12, 6), 
    blocked_rate NUMERIC(12, 6), 
    metric_payload JSONB DEFAULT '{}'::jsonb NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_candidate_memory_performance_metric_v1 PRIMARY KEY (metric_id), 
    CONSTRAINT ck_candidate_memory_performance_metric_v1_evaluated_only CHECK (included_label_status = 'evaluated'), 
    CONSTRAINT ck_candidate_memory_performance_metric_v1_sample_counts_nonneg CHECK (sample_count >= 0 AND minimum_sample_count >= 0), 
    CONSTRAINT ck_candidate_memory_performance_metric_v1_metric_status_allowed CHECK (metric_status IN ('ready','insufficient_samples','source_degraded','blocked_drift'))
);

CREATE UNIQUE INDEX uq_candidate_memory_performance_metric ON decision.candidate_memory_performance_metric_v1 (as_of_trading_day, model_version, label_profile_version, metric_scope, window_scope, bucket_type, bucket_value) NULLS NOT DISTINCT;

CREATE TABLE decision.ambush_turn_freshness_bucket_metric_v1 (
    metric_id BIGSERIAL NOT NULL, 
    metric_date DATE NOT NULL, 
    bucket_code TEXT NOT NULL, 
    sample_count INTEGER NOT NULL, 
    limit_up_rate_pct NUMERIC(12, 6), 
    hit_8pct_rate_pct NUMERIC(12, 6), 
    realizable_hit_before_risk_rate_pct NUMERIC(12, 6), 
    risk_before_hit_rate_pct NUMERIC(12, 6), 
    avg_mfe_pct NUMERIC(12, 6), 
    avg_mae_pct NUMERIC(12, 6), 
    avg_return_1d_pct NUMERIC(12, 6), 
    avg_return_3d_pct NUMERIC(12, 6), 
    avg_return_5d_pct NUMERIC(12, 6), 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_ambush_turn_freshness_bucket_metric_v1 PRIMARY KEY (metric_id)
);

CREATE UNIQUE INDEX uq_ambush_turn_freshness_bucket_metric_v1_identity ON decision.ambush_turn_freshness_bucket_metric_v1 (metric_date, bucket_code);

CREATE TABLE decision.ambush_rank_regret_analysis_v1 (
    analysis_id BIGSERIAL NOT NULL, 
    trade_date DATE NOT NULL, 
    rank_a_symbol TEXT NOT NULL, 
    rank_b_symbol TEXT NOT NULL, 
    rank_a_no INTEGER NOT NULL, 
    rank_b_no INTEGER NOT NULL, 
    rank_a_return_pct NUMERIC(12, 6), 
    rank_b_return_pct NUMERIC(12, 6), 
    rank_a_hit_limit_up BOOLEAN, 
    rank_b_hit_limit_up BOOLEAN, 
    rank_a_first_risk_ts TIMESTAMP WITH TIME ZONE, 
    rank_b_first_risk_ts TIMESTAMP WITH TIME ZONE, 
    rank_a_feature_snapshot JSONB NOT NULL, 
    rank_b_feature_snapshot JSONB NOT NULL, 
    feature_delta_json JSONB NOT NULL, 
    suspected_misrank_reason TEXT[], 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_ambush_rank_regret_analysis_v1 PRIMARY KEY (analysis_id)
);

CREATE INDEX idx_ambush_rank_regret_analysis_v1_trade_date ON decision.ambush_rank_regret_analysis_v1 (trade_date, rank_a_no, rank_b_no);

CREATE TABLE decision.research_feature_snapshot_v1 (
    feature_snapshot_id BIGSERIAL NOT NULL, 
    business_model TEXT NOT NULL, 
    model_version TEXT NOT NULL, 
    model_version_tag VARCHAR(96), 
    feature_version TEXT NOT NULL, 
    symbol TEXT NOT NULL, 
    trade_date DATE NOT NULL, 
    as_of_time TIMESTAMP WITH TIME ZONE NOT NULL, 
    tick_timestamp TIMESTAMP WITH TIME ZONE, 
    calc_timestamp TIMESTAMP WITH TIME ZONE, 
    captured_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    feature_json JSONB NOT NULL, 
    feature_group_json JSONB, 
    feature_gap_codes TEXT[], 
    input_evidence_refs BIGINT[], 
    source_quality_json JSONB DEFAULT '{}'::jsonb NOT NULL, 
    fill_state_json JSONB DEFAULT '{}'::jsonb NOT NULL, 
    payload_hash TEXT NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_research_feature_snapshot_v1 PRIMARY KEY (feature_snapshot_id), 
    CONSTRAINT ck_research_feature_snapshot_v1_nofut CHECK (captured_at <= as_of_time)
);

CREATE INDEX idx_research_feature_snapshot_day ON decision.research_feature_snapshot_v1 (business_model, trade_date, as_of_time);

CREATE UNIQUE INDEX uq_research_feature_snapshot_v1 ON decision.research_feature_snapshot_v1 (business_model, model_version, feature_version, symbol, trade_date, as_of_time);

CREATE TABLE decision.golden_research_dataset_v1 (
    dataset_id BIGSERIAL NOT NULL, 
    dataset_version TEXT NOT NULL, 
    business_model TEXT NOT NULL, 
    sample_id TEXT NOT NULL, 
    symbol TEXT NOT NULL, 
    trade_date DATE NOT NULL, 
    batch_id BIGINT, 
    sample_source TEXT NOT NULL, 
    sample_state TEXT, 
    rank_no INTEGER, 
    score NUMERIC(12, 6), 
    model_version TEXT NOT NULL, 
    feature_version TEXT, 
    label_version TEXT, 
    as_of_time TIMESTAMP WITH TIME ZONE NOT NULL, 
    decision_snapshot_id BIGINT, 
    feature_snapshot_id BIGINT, 
    evidence_snapshot_ids BIGINT[], 
    label_id BIGINT, 
    label_status TEXT, 
    result_class TEXT, 
    data_completeness_status TEXT NOT NULL, 
    source_gap_codes TEXT[], 
    payload_hash TEXT NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_golden_research_dataset_v1 PRIMARY KEY (dataset_id)
);

CREATE INDEX idx_golden_research_dataset_v1_symbol ON decision.golden_research_dataset_v1 (symbol, trade_date);

CREATE UNIQUE INDEX uq_golden_research_dataset_v1_sample ON decision.golden_research_dataset_v1 (dataset_version, business_model, sample_id);

CREATE INDEX idx_golden_research_dataset_v1_trade_model ON decision.golden_research_dataset_v1 (dataset_version, business_model, trade_date);

CREATE TABLE decision.research_outcome_truth_check_v1 (
    check_id BIGSERIAL NOT NULL, 
    dataset_version TEXT NOT NULL, 
    business_model TEXT NOT NULL, 
    model_version TEXT NOT NULL, 
    sample_id TEXT NOT NULL, 
    symbol TEXT NOT NULL, 
    batch_id BIGINT, 
    label_id BIGINT, 
    label_table TEXT NOT NULL, 
    entry_price_type TEXT, 
    label_purpose TEXT, 
    label_status TEXT, 
    result_class TEXT, 
    path_resolution TEXT, 
    has_entry_price BOOLEAN NOT NULL, 
    has_minute_path BOOLEAN NOT NULL, 
    has_first_hit_ts BOOLEAN NOT NULL, 
    has_first_risk_ts BOOLEAN NOT NULL, 
    has_first_sellable_day BOOLEAN NOT NULL, 
    is_tradeable BOOLEAN, 
    is_realizable BOOLEAN, 
    is_path_order_valid BOOLEAN, 
    check_status TEXT NOT NULL, 
    violation_codes TEXT[], 
    checked_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_research_outcome_truth_check_v1 PRIMARY KEY (check_id)
);

CREATE INDEX idx_research_outcome_truth_status ON decision.research_outcome_truth_check_v1 (dataset_version, business_model, check_status, checked_at);

CREATE UNIQUE INDEX uq_research_outcome_truth_check_v1 ON decision.research_outcome_truth_check_v1 (dataset_version, business_model, model_version, sample_id, label_id) NULLS NOT DISTINCT;

CREATE TABLE decision.research_rank_regret_v1 (
    regret_id BIGSERIAL NOT NULL, 
    dataset_version TEXT NOT NULL, 
    business_model TEXT NOT NULL, 
    model_version TEXT NOT NULL, 
    trade_date DATE NOT NULL, 
    rank_a_symbol TEXT NOT NULL, 
    rank_b_symbol TEXT NOT NULL, 
    rank_a_no INTEGER NOT NULL, 
    rank_b_no INTEGER NOT NULL, 
    rank_a_score NUMERIC(12, 6), 
    rank_b_score NUMERIC(12, 6), 
    rank_a_state TEXT, 
    rank_b_state TEXT, 
    rank_a_result_class TEXT, 
    rank_b_result_class TEXT, 
    rank_a_return_pct NUMERIC(12, 6), 
    rank_b_return_pct NUMERIC(12, 6), 
    rank_a_mfe_pct NUMERIC(12, 6), 
    rank_b_mfe_pct NUMERIC(12, 6), 
    rank_a_mae_pct NUMERIC(12, 6), 
    rank_b_mae_pct NUMERIC(12, 6), 
    rank_a_hit_success BOOLEAN, 
    rank_b_hit_success BOOLEAN, 
    rank_a_feature_snapshot JSONB NOT NULL, 
    rank_b_feature_snapshot JSONB NOT NULL, 
    feature_delta_json JSONB NOT NULL, 
    regret_type TEXT NOT NULL, 
    suspected_misrank_reason TEXT[], 
    regret_status TEXT DEFAULT 'pending' NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_research_rank_regret_v1 PRIMARY KEY (regret_id)
);

CREATE INDEX idx_research_rank_regret_v1_day ON decision.research_rank_regret_v1 (dataset_version, business_model, trade_date, rank_a_no);

CREATE TABLE decision.model_effectiveness_report_v1 (
    report_id BIGSERIAL NOT NULL, 
    dataset_version TEXT NOT NULL, 
    business_model TEXT NOT NULL, 
    model_version TEXT NOT NULL, 
    report_date DATE NOT NULL, 
    sample_start_date DATE NOT NULL, 
    sample_end_date DATE NOT NULL, 
    evaluated_count INTEGER NOT NULL, 
    top1_realizable_rate_pct NUMERIC(12, 6), 
    top3_realizable_rate_pct NUMERIC(12, 6), 
    top5_realizable_rate_pct NUMERIC(12, 6), 
    avg_return_pct NUMERIC(12, 6), 
    median_return_pct NUMERIC(12, 6), 
    max_drawdown_pct NUMERIC(12, 6), 
    risk_before_hit_rate_pct NUMERIC(12, 6), 
    buy_day_hit_not_sellable_rate_pct NUMERIC(12, 6), 
    spike_reversal_rate_pct NUMERIC(12, 6), 
    baseline_name TEXT, 
    baseline_realizable_rate_pct NUMERIC(12, 6), 
    excess_realizable_rate_pct NUMERIC(12, 6), 
    model_health_status TEXT NOT NULL, 
    key_findings JSONB, 
    open_questions JSONB, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_model_effectiveness_report_v1 PRIMARY KEY (report_id)
);

CREATE INDEX idx_model_effectiveness_report_v1_health ON decision.model_effectiveness_report_v1 (dataset_version, business_model, model_health_status);

CREATE UNIQUE INDEX uq_model_effectiveness_report_v1 ON decision.model_effectiveness_report_v1 (dataset_version, business_model, model_version, report_date);

CREATE TABLE decision.ambush_turn_timing_bucket_report_v1 (
    report_id BIGSERIAL NOT NULL, 
    dataset_version TEXT NOT NULL, 
    trade_date DATE NOT NULL, 
    model_version TEXT NOT NULL, 
    bucket_code TEXT NOT NULL, 
    sample_count INTEGER NOT NULL, 
    avg_next_1d_return_pct NUMERIC(12, 6), 
    avg_next_3d_return_pct NUMERIC(12, 6), 
    avg_next_5d_return_pct NUMERIC(12, 6), 
    hit_8pct_rate_pct NUMERIC(12, 6), 
    realizable_hit_before_risk_rate_pct NUMERIC(12, 6), 
    risk_before_hit_rate_pct NUMERIC(12, 6), 
    limit_up_rate_pct NUMERIC(12, 6), 
    spike_reversal_rate_pct NUMERIC(12, 6), 
    avg_mfe_pct NUMERIC(12, 6), 
    avg_mae_pct NUMERIC(12, 6), 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_ambush_turn_timing_bucket_report_v1 PRIMARY KEY (report_id)
);

CREATE UNIQUE INDEX uq_ambush_turn_timing_bucket_report_v1 ON decision.ambush_turn_timing_bucket_report_v1 (dataset_version, trade_date, model_version, bucket_code);

CREATE INDEX idx_ambush_turn_timing_bucket_report_v1_bucket ON decision.ambush_turn_timing_bucket_report_v1 (dataset_version, bucket_code);

CREATE TABLE decision.research_ablation_experiment_v1 (
    experiment_id BIGSERIAL NOT NULL, 
    experiment_code TEXT NOT NULL, 
    business_model TEXT NOT NULL, 
    baseline_model_version TEXT NOT NULL, 
    test_model_version TEXT NOT NULL, 
    experiment_name TEXT NOT NULL, 
    experiment_type TEXT NOT NULL, 
    changed_features TEXT[], 
    changed_weights JSONB, 
    changed_rules JSONB, 
    sample_start_date DATE NOT NULL, 
    sample_end_date DATE NOT NULL, 
    min_sample_count INTEGER NOT NULL, 
    primary_metric TEXT NOT NULL, 
    risk_metric TEXT NOT NULL, 
    status TEXT DEFAULT 'created' NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    completed_at TIMESTAMP WITH TIME ZONE, 
    CONSTRAINT pk_research_ablation_experiment_v1 PRIMARY KEY (experiment_id), 
    CONSTRAINT uq_research_ablation_experiment_v1_experiment_code UNIQUE (experiment_code)
);

CREATE INDEX idx_research_ablation_experiment_status ON decision.research_ablation_experiment_v1 (business_model, status);

CREATE TABLE decision.opportunity_queue_feedback_v1 (
    feedback_id BIGSERIAL NOT NULL, 
    trade_date DATE NOT NULL, 
    business_model TEXT NOT NULL, 
    signal_state TEXT, 
    rolling_window_days INTEGER NOT NULL, 
    evaluated_count INTEGER NOT NULL, 
    topn_hit_rate_pct NUMERIC(12, 6), 
    topn_realizable_rate_pct NUMERIC(12, 6), 
    risk_before_hit_rate_pct NUMERIC(12, 6), 
    avg_return_pct NUMERIC(12, 6), 
    max_drawdown_pct NUMERIC(12, 6), 
    baseline_hit_rate_pct NUMERIC(12, 6), 
    excess_hit_rate_pct NUMERIC(12, 6), 
    recommended_weight_adjustment NUMERIC(12, 6), 
    model_health_status TEXT NOT NULL, 
    feedback_reason TEXT[], 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_opportunity_queue_feedback_v1 PRIMARY KEY (feedback_id)
);

CREATE INDEX idx_opportunity_queue_feedback_business_model ON decision.opportunity_queue_feedback_v1 (business_model, trade_date, model_health_status);

CREATE UNIQUE INDEX uq_opportunity_queue_feedback_v1 ON decision.opportunity_queue_feedback_v1 (trade_date, business_model, signal_state, rolling_window_days) NULLS NOT DISTINCT;

CREATE TABLE decision.research_cohort_performance_v1 (
    cohort_id BIGSERIAL NOT NULL, 
    business_model TEXT NOT NULL, 
    model_version TEXT NOT NULL, 
    cohort_date DATE NOT NULL, 
    cohort_type TEXT NOT NULL, 
    cohort_key TEXT NOT NULL, 
    cohort_value TEXT NOT NULL, 
    sample_count INTEGER NOT NULL, 
    evaluated_count INTEGER NOT NULL, 
    hit_8pct_rate_pct NUMERIC(12, 6), 
    realizable_hit_before_risk_rate_pct NUMERIC(12, 6), 
    risk_before_hit_rate_pct NUMERIC(12, 6), 
    buy_day_hit_not_sellable_rate_pct NUMERIC(12, 6), 
    spike_reversal_rate_pct NUMERIC(12, 6), 
    avg_return_pct NUMERIC(12, 6), 
    median_return_pct NUMERIC(12, 6), 
    avg_mfe_pct NUMERIC(12, 6), 
    avg_mae_pct NUMERIC(12, 6), 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_research_cohort_performance_v1 PRIMARY KEY (cohort_id)
);

CREATE UNIQUE INDEX uq_research_cohort_performance_v1 ON decision.research_cohort_performance_v1 (business_model, model_version, cohort_date, cohort_type, cohort_key, cohort_value);

CREATE INDEX idx_research_cohort_performance_lookup ON decision.research_cohort_performance_v1 (business_model, cohort_type, cohort_date);

CREATE TABLE decision.dragon_window_feature_v1 (
    feature_id BIGSERIAL NOT NULL, 
    as_of_trading_day DATE NOT NULL, 
    symbol TEXT NOT NULL, 
    window_days INTEGER NOT NULL, 
    trough_trading_day DATE, 
    trough_position_ratio NUMERIC(12, 6), 
    drawdown_from_window_high NUMERIC(12, 6), 
    distance_from_trough NUMERIC(12, 6), 
    decline_maturity_score NUMERIC(12, 6), 
    bottom_stabilization_score NUMERIC(12, 6), 
    early_turn_up_score NUMERIC(12, 6), 
    sqrt_right_match_score NUMERIC(12, 6), 
    v_left_bottom_match_score NUMERIC(12, 6), 
    dragon_shape_score NUMERIC(12, 6), 
    false_reversal_risk_pre NUMERIC(12, 6), 
    pass_l1_gate BOOLEAN NOT NULL, 
    block_reasons TEXT[], 
    feature_hash TEXT NOT NULL, 
    captured_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    as_of_time TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_dragon_window_feature_v1 PRIMARY KEY (feature_id)
);

CREATE UNIQUE INDEX uq_dragon_window_feature_v1_day_symbol_window ON decision.dragon_window_feature_v1 (as_of_trading_day, symbol, window_days);

CREATE INDEX idx_dragon_window_feature_v1_l1 ON decision.dragon_window_feature_v1 (as_of_trading_day, pass_l1_gate, dragon_shape_score);

CREATE TABLE decision.dragon_l2_candidate_pool_v1 (
    l2_candidate_id BIGSERIAL NOT NULL, 
    as_of_trading_day DATE NOT NULL, 
    symbol TEXT NOT NULL, 
    best_shape_window INTEGER NOT NULL, 
    dragon_shape_score NUMERIC(12, 6) NOT NULL, 
    l2_status TEXT NOT NULL, 
    block_reasons TEXT[], 
    warning_reasons TEXT[], 
    avg_amount_20d NUMERIC(20, 2), 
    avg_turnover_20d NUMERIC(12, 6), 
    daily_data_completeness NUMERIC(12, 6), 
    liquidity_check TEXT, 
    data_quality_check TEXT, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_dragon_l2_candidate_pool_v1 PRIMARY KEY (l2_candidate_id)
);

CREATE UNIQUE INDEX uq_dragon_l2_candidate_pool_v1_day_symbol ON decision.dragon_l2_candidate_pool_v1 (as_of_trading_day, symbol);

CREATE INDEX idx_dragon_l2_candidate_pool_v1_status ON decision.dragon_l2_candidate_pool_v1 (as_of_trading_day, l2_status, dragon_shape_score);

CREATE TABLE decision.dragon_deep_analysis_v1 (
    analysis_id BIGSERIAL NOT NULL, 
    as_of_trading_day DATE NOT NULL, 
    symbol TEXT NOT NULL, 
    model_version TEXT NOT NULL, 
    dragon_state TEXT NOT NULL, 
    dragon_head_score NUMERIC(12, 6), 
    best_shape_window INTEGER, 
    decline_maturity_score NUMERIC(12, 6), 
    bottom_stabilization_score NUMERIC(12, 6), 
    early_turn_up_score NUMERIC(12, 6), 
    dragon_shape_score NUMERIC(12, 6), 
    mild_capital_probe_score NUMERIC(12, 6), 
    liquidity_tradability_score NUMERIC(12, 6), 
    sector_context_score NUMERIC(12, 6), 
    capital_probe_score NUMERIC(12, 6), 
    news_event_score NUMERIC(12, 6), 
    market_context_score NUMERIC(12, 6), 
    breakout_readiness_score NUMERIC(12, 6), 
    upside_room_score NUMERIC(12, 6), 
    false_reversal_risk NUMERIC(12, 6), 
    evidence_gap_penalty NUMERIC(12, 6), 
    market_defensive_headwind BOOLEAN, 
    major_negative_event BOOLEAN, 
    source_gap_count INTEGER DEFAULT '0' NOT NULL, 
    source_gap_p0_count INTEGER DEFAULT '0' NOT NULL, 
    source_gap_codes TEXT[], 
    main_positive_factors JSONB, 
    main_negative_factors JSONB, 
    next_confirmation_conditions JSONB, 
    invalidation_conditions JSONB, 
    evidence_refs BIGINT[], 
    score_hash TEXT NOT NULL, 
    as_of_time TIMESTAMP WITH TIME ZONE NOT NULL, 
    captured_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    is_active BOOLEAN DEFAULT true NOT NULL, 
    CONSTRAINT pk_dragon_deep_analysis_v1 PRIMARY KEY (analysis_id)
);

CREATE UNIQUE INDEX uq_dragon_deep_analysis_v1_current ON decision.dragon_deep_analysis_v1 (as_of_trading_day, symbol, model_version) WHERE is_active = true;

CREATE UNIQUE INDEX uq_dragon_deep_analysis_v1_identity ON decision.dragon_deep_analysis_v1 (as_of_trading_day, symbol, model_version, as_of_time);

CREATE INDEX idx_dragon_deep_analysis_v1_state_score ON decision.dragon_deep_analysis_v1 (as_of_trading_day, dragon_state, dragon_head_score);

CREATE TABLE decision.dragon_outcome_label_v1 (
    label_id BIGSERIAL NOT NULL, 
    symbol TEXT NOT NULL, 
    signal_trading_day DATE NOT NULL, 
    dragon_state_at_signal TEXT NOT NULL, 
    entry_trading_day DATE, 
    first_sellable_trading_day DATE, 
    open_5m_vwap NUMERIC(18, 6), 
    target_price NUMERIC(18, 6), 
    risk_price NUMERIC(18, 6), 
    first_hit_ts TIMESTAMP WITH TIME ZONE, 
    first_risk_ts TIMESTAMP WITH TIME ZONE, 
    dragon_turn_up_success BOOLEAN, 
    bottoming_only_no_follow BOOLEAN, 
    false_reversal_failure BOOLEAN, 
    support_break_invalidated BOOLEAN, 
    slow_trend_follow_through BOOLEAN, 
    risk_before_dragon_hit BOOLEAN, 
    max_favorable_excursion NUMERIC(12, 6), 
    max_adverse_excursion NUMERIC(12, 6), 
    days_to_hit INTEGER, 
    result_class TEXT, 
    label_status TEXT NOT NULL, 
    path_resolution TEXT NOT NULL, 
    label_matured_at TIMESTAMP WITH TIME ZONE, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_dragon_outcome_label_v1 PRIMARY KEY (label_id)
);

CREATE UNIQUE INDEX uq_dragon_outcome_label_v1_symbol_signal ON decision.dragon_outcome_label_v1 (symbol, signal_trading_day);

CREATE INDEX idx_dragon_outcome_label_v1_status ON decision.dragon_outcome_label_v1 (label_status, result_class, signal_trading_day);

CREATE TABLE decision.notification_delivery_log (
    delivery_id BIGSERIAL NOT NULL, 
    delivery_key VARCHAR(128) NOT NULL, 
    alert_type VARCHAR(64) NOT NULL, 
    channel VARCHAR(32) DEFAULT 'email' NOT NULL, 
    scheduled_date DATE NOT NULL, 
    checkpoint_label VARCHAR(16) NOT NULL, 
    analysis_trading_day DATE, 
    status VARCHAR(64) NOT NULL, 
    message_id VARCHAR(255), 
    attempt_count INTEGER DEFAULT '1' NOT NULL, 
    last_attempt_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    sent_at TIMESTAMP WITH TIME ZONE, 
    detail_json JSONB, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_notification_delivery_log PRIMARY KEY (delivery_id)
);

CREATE UNIQUE INDEX uq_notification_delivery_key ON decision.notification_delivery_log (delivery_key);

CREATE INDEX idx_notification_delivery_day ON decision.notification_delivery_log (alert_type, scheduled_date, checkpoint_label);

CREATE INDEX idx_notification_delivery_status ON decision.notification_delivery_log (status, last_attempt_at);

CREATE TABLE decision.data_inspection_domain_contract (
    contract_id BIGSERIAL NOT NULL, 
    domain_code VARCHAR(64) NOT NULL, 
    business_line VARCHAR(128) NOT NULL, 
    target_table VARCHAR(96) NOT NULL, 
    grain VARCHAR(24) NOT NULL, 
    required_level VARCHAR(24) NOT NULL, 
    default_severity VARCHAR(8) NOT NULL, 
    freshness_sla_seconds INTEGER, 
    lookback_days INTEGER, 
    blocks_scoring BOOLEAN DEFAULT false NOT NULL, 
    blocks_publish BOOLEAN DEFAULT false NOT NULL, 
    replay_safe BOOLEAN DEFAULT true NOT NULL, 
    provider_lineage_required BOOLEAN DEFAULT true NOT NULL, 
    contract_json JSONB, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_data_inspection_domain_contract PRIMARY KEY (contract_id)
);

CREATE UNIQUE INDEX uq_data_inspection_domain_contract ON decision.data_inspection_domain_contract (business_line, domain_code);

CREATE TABLE decision.data_inspection_run (
    run_id BIGSERIAL NOT NULL, 
    scope VARCHAR(128) NOT NULL, 
    as_of_trading_day DATE NOT NULL, 
    lookback_days INTEGER NOT NULL, 
    status VARCHAR(24) DEFAULT 'running' NOT NULL, 
    requested_subject_count INTEGER DEFAULT '0' NOT NULL, 
    inspected_subject_count INTEGER DEFAULT '0' NOT NULL, 
    gap_count INTEGER DEFAULT '0' NOT NULL, 
    p0_gap_count INTEGER DEFAULT '0' NOT NULL, 
    p1_gap_count INTEGER DEFAULT '0' NOT NULL, 
    run_contract_json JSONB, 
    started_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    finished_at TIMESTAMP WITH TIME ZONE, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_data_inspection_run PRIMARY KEY (run_id)
);

CREATE INDEX idx_data_inspection_run_scope_day ON decision.data_inspection_run (scope, as_of_trading_day, started_at);

CREATE TABLE decision.dim_model (
    model_code TEXT NOT NULL, 
    model_name TEXT NOT NULL, 
    model_type TEXT NOT NULL, 
    owner_service TEXT NOT NULL, 
    description TEXT, 
    is_active BOOLEAN DEFAULT true NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_dim_model PRIMARY KEY (model_code)
);

CREATE TABLE decision.dim_buy_point_type (
    buy_point_type_code TEXT NOT NULL, 
    applicable_source_models TEXT[] NOT NULL, 
    buy_point_name TEXT NOT NULL, 
    buy_point_family TEXT NOT NULL, 
    default_window_start TIME WITHOUT TIME ZONE, 
    default_window_end TIME WITHOUT TIME ZONE, 
    requires_intraday_data BOOLEAN DEFAULT true NOT NULL, 
    description TEXT, 
    is_active BOOLEAN DEFAULT true NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_dim_buy_point_type PRIMARY KEY (buy_point_type_code)
);

CREATE INDEX idx_dim_buy_point_type_family ON decision.dim_buy_point_type (buy_point_family, is_active);

CREATE TABLE decision.dim_outcome_label (
    label_code TEXT NOT NULL, 
    label_family TEXT NOT NULL, 
    label_name TEXT NOT NULL, 
    applies_to_models TEXT[] NOT NULL, 
    is_success_label BOOLEAN NOT NULL, 
    is_failure_label BOOLEAN NOT NULL, 
    requires_minute_path BOOLEAN DEFAULT true NOT NULL, 
    description TEXT, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_dim_outcome_label PRIMARY KEY (label_code)
);

CREATE INDEX idx_dim_outcome_label_family ON decision.dim_outcome_label (label_family);

CREATE TABLE decision.dim_evidence_source (
    source_code TEXT NOT NULL, 
    source_name TEXT NOT NULL, 
    source_family TEXT NOT NULL, 
    is_required_for_official BOOLEAN DEFAULT false NOT NULL, 
    description TEXT, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_dim_evidence_source PRIMARY KEY (source_code)
);

CREATE INDEX idx_dim_evidence_source_family ON decision.dim_evidence_source (source_family);

CREATE TABLE decision.dim_experiment (
    experiment_id BIGSERIAL NOT NULL, 
    experiment_code TEXT NOT NULL, 
    experiment_name TEXT NOT NULL, 
    target_model TEXT NOT NULL, 
    target_component TEXT NOT NULL, 
    baseline_version TEXT NOT NULL, 
    test_version TEXT NOT NULL, 
    changed_features TEXT[], 
    changed_rules JSONB, 
    changed_weights JSONB, 
    sample_start_date DATE, 
    sample_end_date DATE, 
    min_sample_count INTEGER, 
    status TEXT DEFAULT 'created' NOT NULL, 
    created_by TEXT, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_dim_experiment PRIMARY KEY (experiment_id), 
    CONSTRAINT uq_dim_experiment_experiment_code UNIQUE (experiment_code)
);

CREATE TABLE decision.snapshot_feature_vector (
    feature_snapshot_id BIGSERIAL NOT NULL, 
    model_code TEXT NOT NULL, 
    model_version TEXT NOT NULL, 
    symbol TEXT NOT NULL, 
    trade_date DATE NOT NULL, 
    as_of_time TIMESTAMP WITH TIME ZONE NOT NULL, 
    feature_schema_version TEXT NOT NULL, 
    feature_json JSONB NOT NULL, 
    feature_hash TEXT NOT NULL, 
    source_evidence_snapshot_ids BIGINT[], 
    source_gap_codes TEXT[], 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_snapshot_feature_vector PRIMARY KEY (feature_snapshot_id)
);

CREATE UNIQUE INDEX uq_snapshot_feature_vector_identity ON decision.snapshot_feature_vector (model_code, model_version, symbol, trade_date, as_of_time, feature_hash);

CREATE INDEX idx_feature_snapshot_hash ON decision.snapshot_feature_vector (feature_hash);

CREATE TABLE decision.snapshot_decision_context (
    decision_snapshot_id BIGSERIAL NOT NULL, 
    owner_service TEXT NOT NULL, 
    model_code TEXT NOT NULL, 
    model_version TEXT NOT NULL, 
    symbol TEXT NOT NULL, 
    trade_date DATE NOT NULL, 
    as_of_time TIMESTAMP WITH TIME ZONE NOT NULL, 
    feature_snapshot_id BIGINT, 
    evidence_snapshot_ids BIGINT[], 
    config_hash TEXT NOT NULL, 
    input_hash TEXT NOT NULL, 
    output_hash TEXT NOT NULL, 
    decision_type TEXT NOT NULL, 
    decision_result JSONB NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_snapshot_decision_context PRIMARY KEY (decision_snapshot_id)
);

CREATE TABLE decision.fact_model_signal_v1 (
    signal_id BIGSERIAL NOT NULL, 
    model_code VARCHAR(64) NOT NULL, 
    model_version VARCHAR(64) NOT NULL, 
    signal_date DATE NOT NULL, 
    selected_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    tick_timestamp TIMESTAMP WITH TIME ZONE, 
    calc_timestamp TIMESTAMP WITH TIME ZONE, 
    model_version_tag VARCHAR(96), 
    symbol VARCHAR(16) NOT NULL, 
    stock_name VARCHAR(64), 
    source_stage VARCHAR(64), 
    rank_no INTEGER, 
    model_score NUMERIC(18, 10), 
    model_state VARCHAR(64), 
    selected_reason_codes JSONB DEFAULT '[]'::jsonb NOT NULL, 
    risk_reason_codes JSONB DEFAULT '[]'::jsonb NOT NULL, 
    evidence_gap_codes JSONB DEFAULT '[]'::jsonb NOT NULL, 
    feature_snapshot_id BIGINT, 
    source_quality_json JSONB DEFAULT '{}'::jsonb NOT NULL, 
    fill_state_json JSONB DEFAULT '{}'::jsonb NOT NULL, 
    tenant_id VARCHAR(64), 
    user_id VARCHAR(64), 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_fact_model_signal_v1 PRIMARY KEY (signal_id)
);

CREATE UNIQUE INDEX uq_fact_model_signal_v1_identity ON decision.fact_model_signal_v1 (model_code, model_version, signal_date, symbol, source_stage) NULLS NOT DISTINCT;

CREATE INDEX idx_fact_model_signal_v1_symbol_date ON decision.fact_model_signal_v1 (symbol, signal_date);

CREATE INDEX idx_fact_model_signal_v1_model_date ON decision.fact_model_signal_v1 (model_code, signal_date);

CREATE TABLE decision.fact_candidate_memory_entity_v1 (
    memory_entity_id BIGSERIAL NOT NULL, 
    symbol VARCHAR(16) NOT NULL, 
    stock_name VARCHAR(64), 
    first_model_code VARCHAR(64) DEFAULT 'hot_candidates' NOT NULL, 
    first_signal_id BIGINT, 
    first_signal_date DATE NOT NULL, 
    first_selected_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    first_rank_no INTEGER, 
    original_hot_score NUMERIC(10, 4), 
    original_ths_probability NUMERIC(8, 4), 
    original_local_confirm_score NUMERIC(10, 4), 
    memory_status VARCHAR(64) NOT NULL, 
    ttl_start_date DATE NOT NULL, 
    ttl_end_date DATE NOT NULL, 
    ttl_total_days INTEGER NOT NULL, 
    ttl_remaining_days INTEGER, 
    memory_age_days INTEGER, 
    memory_decay_score NUMERIC(10, 4), 
    last_memory_score NUMERIC(10, 4), 
    last_evaluated_at TIMESTAMP WITH TIME ZONE, 
    invalidation_reason_codes JSONB DEFAULT '[]'::jsonb NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_fact_candidate_memory_entity_v1 PRIMARY KEY (memory_entity_id)
);

CREATE UNIQUE INDEX uq_memory_entity_v1_symbol_first ON decision.fact_candidate_memory_entity_v1 (symbol, first_signal_date, first_model_code);

CREATE TABLE decision.ambush_near_miss_watch_v1 (
    near_miss_id BIGSERIAL NOT NULL, 
    valley_watch_id BIGINT, 
    trade_date DATE NOT NULL, 
    symbol VARCHAR(16) NOT NULL, 
    stock_name VARCHAR(64), 
    primary_trough_date DATE, 
    valley_watch_score NUMERIC(10, 4), 
    missing_anchor_condition_codes JSONB DEFAULT '[]'::jsonb NOT NULL, 
    failed_condition_detail JSONB DEFAULT '{}'::jsonb NOT NULL, 
    near_miss_score NUMERIC(10, 4), 
    next_watch_condition VARCHAR(128), 
    high_frequency_watch_flag BOOLEAN DEFAULT true NOT NULL, 
    next_scan_priority VARCHAR(32) DEFAULT 'high' NOT NULL, 
    later_transition_signal_id BIGINT, 
    later_limit_up_flag BOOLEAN DEFAULT false NOT NULL, 
    later_target_hit_flag BOOLEAN DEFAULT false NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_ambush_near_miss_watch_v1 PRIMARY KEY (near_miss_id)
);

CREATE UNIQUE INDEX uq_ambush_near_miss_watch_v1_day_symbol ON decision.ambush_near_miss_watch_v1 (trade_date, symbol);

CREATE TABLE decision.ambush_deep_confirm_signal_v1 (
    deep_confirm_id BIGSERIAL NOT NULL, 
    effective_turn_id BIGINT NOT NULL, 
    trade_date DATE NOT NULL, 
    symbol VARCHAR(16) NOT NULL, 
    stock_name VARCHAR(64), 
    l2_basic_filter_status VARCHAR(64), 
    l3_deep_confirm_status VARCHAR(64), 
    l4_startup_rank_status VARCHAR(64), 
    early_turn_up_score NUMERIC(10, 4), 
    upside_room_score NUMERIC(10, 4), 
    mild_capital_probe_score NUMERIC(10, 4), 
    sector_context_score NUMERIC(10, 4), 
    news_event_score NUMERIC(10, 4), 
    market_context_score NUMERIC(10, 4), 
    tradability_score NUMERIC(10, 4), 
    false_rebound_risk_score NUMERIC(10, 4), 
    dragon_priority_score NUMERIC(10, 4), 
    evidence_level VARCHAR(64), 
    source_gap_codes JSONB DEFAULT '[]'::jsonb NOT NULL, 
    main_positive_factors JSONB DEFAULT '[]'::jsonb NOT NULL, 
    main_negative_factors JSONB DEFAULT '[]'::jsonb NOT NULL, 
    confirmed_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    evidence_available_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_ambush_deep_confirm_signal_v1 PRIMARY KEY (deep_confirm_id), 
    CONSTRAINT ck_ambush_deep_confirm_signal_v1_nofut CHECK (evidence_available_at <= confirmed_at)
);

CREATE UNIQUE INDEX uq_ambush_deep_confirm_v1_turn ON decision.ambush_deep_confirm_signal_v1 (effective_turn_id);

CREATE TABLE decision.model_signal_fact (
    signal_id BIGSERIAL NOT NULL, 
    model_code VARCHAR(64) NOT NULL, 
    symbol VARCHAR(16) NOT NULL, 
    stock_name VARCHAR(64), 
    exchange VARCHAR(16), 
    signal_date DATE NOT NULL, 
    selected_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    decision_time TIMESTAMP WITH TIME ZONE NOT NULL, 
    tick_timestamp TIMESTAMP WITH TIME ZONE, 
    calc_timestamp TIMESTAMP WITH TIME ZONE, 
    model_version VARCHAR(64) NOT NULL, 
    model_version_tag VARCHAR(96), 
    model_score NUMERIC(18, 10), 
    signal_stage VARCHAR(32) NOT NULL, 
    release_gate_status VARCHAR(32) NOT NULL, 
    release_gate_reason_codes JSONB DEFAULT '[]'::jsonb NOT NULL, 
    is_official_signal BOOLEAN DEFAULT false NOT NULL, 
    is_research_only BOOLEAN DEFAULT false NOT NULL, 
    frozen_fact_version VARCHAR(64) DEFAULT '20260606_v1' NOT NULL, 
    first_model_score NUMERIC(18, 10), 
    first_release_gate_status VARCHAR(32), 
    first_valid_reference_entry_price NUMERIC(18, 8), 
    first_valid_buy_point_id BIGINT, 
    frozen_reference_price NUMERIC(18, 8), 
    source_quality_json JSONB DEFAULT '{}'::jsonb NOT NULL, 
    fill_state_json JSONB DEFAULT '{}'::jsonb NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_model_signal_fact PRIMARY KEY (signal_id), 
    CONSTRAINT ck_model_signal_fact_model_code_allowed CHECK (model_code IN ('hot_candidates','candidate_memory','ambush_watchlist')), 
    CONSTRAINT ck_model_signal_fact_model_score_range CHECK (model_score IS NULL OR (model_score >= 0 AND model_score <= 100)), 
    CONSTRAINT ck_model_signal_fact_first_model_score_range CHECK (first_model_score IS NULL OR (first_model_score >= 0 AND first_model_score <= 100)), 
    CONSTRAINT ck_model_signal_fact_signal_stage_allowed CHECK (signal_stage IN ('observation_sample','research_sample','calibration_signal','official_signal')), 
    CONSTRAINT ck_model_signal_fact_release_gate_allowed CHECK (release_gate_status IN ('passed','blocked','research_only','pending')), 
    CONSTRAINT ck_model_signal_fact_official_requires_passed_gate CHECK (NOT is_official_signal OR (signal_stage = 'official_signal' AND release_gate_status = 'passed')), 
    CONSTRAINT ck_model_signal_fact_research_only_not_official CHECK (NOT is_research_only OR signal_stage IN ('observation_sample','research_sample','calibration_signal')), 
    CONSTRAINT ck_model_signal_fact_first_entry_positive CHECK (first_valid_reference_entry_price IS NULL OR first_valid_reference_entry_price > 0), 
    CONSTRAINT ck_model_signal_fact_frozen_reference_positive CHECK (frozen_reference_price IS NULL OR frozen_reference_price > 0)
);

CREATE INDEX idx_model_signal_fact_model_date ON decision.model_signal_fact (model_code, signal_date);

CREATE INDEX idx_model_signal_fact_symbol_date ON decision.model_signal_fact (model_code, symbol, signal_date);

CREATE INDEX idx_model_signal_fact_stage_gate ON decision.model_signal_fact (signal_stage, release_gate_status);

CREATE TABLE decision.fact_data_inspection_run_v1 (
    inspection_run_id BIGSERIAL NOT NULL, 
    scope VARCHAR(128) NOT NULL, 
    business_date DATE NOT NULL, 
    started_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    finished_at TIMESTAMP WITH TIME ZONE, 
    status VARCHAR(32) NOT NULL, 
    inspected_count INTEGER DEFAULT '0' NOT NULL, 
    p0_count INTEGER DEFAULT '0' NOT NULL, 
    p1_count INTEGER DEFAULT '0' NOT NULL, 
    p2_count INTEGER DEFAULT '0' NOT NULL, 
    info_count INTEGER DEFAULT '0' NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_fact_data_inspection_run_v1 PRIMARY KEY (inspection_run_id)
);

CREATE INDEX idx_data_inspection_run_v1_scope_date ON decision.fact_data_inspection_run_v1 (scope, business_date);

CREATE TABLE decision.fact_data_availability_audit_v1 (
    availability_audit_id BIGSERIAL NOT NULL, 
    model_code VARCHAR(64) NOT NULL, 
    signal_id BIGINT, 
    source_table VARCHAR(128) NOT NULL, 
    source_record_id BIGINT, 
    symbol VARCHAR(16), 
    evidence_name VARCHAR(128), 
    event_time TIMESTAMP WITH TIME ZONE, 
    available_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    decision_time TIMESTAMP WITH TIME ZONE NOT NULL, 
    future_leakage_flag BOOLEAN DEFAULT false NOT NULL, 
    audit_reason VARCHAR(256), 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_fact_data_availability_audit_v1 PRIMARY KEY (availability_audit_id)
);

CREATE INDEX idx_data_availability_v1_signal ON decision.fact_data_availability_audit_v1 (signal_id, evidence_name, future_leakage_flag);

CREATE TABLE decision.audit_state_transition (
    transition_id BIGSERIAL NOT NULL, 
    model_code TEXT NOT NULL, 
    model_version TEXT NOT NULL, 
    symbol TEXT NOT NULL, 
    trade_date DATE NOT NULL, 
    from_state TEXT, 
    to_state TEXT, 
    transition_status TEXT NOT NULL, 
    transition_reason_codes TEXT[], 
    failed_condition_codes TEXT[], 
    condition_gap_json JSONB, 
    feature_snapshot_id BIGINT, 
    evidence_snapshot_ids BIGINT[], 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_audit_state_transition PRIMARY KEY (transition_id)
);

CREATE INDEX idx_state_transition_symbol ON decision.audit_state_transition (symbol, trade_date, model_code);

CREATE TABLE decision.audit_model_execution_handoff (
    handoff_audit_id BIGSERIAL NOT NULL, 
    signal_id BIGINT, 
    execution_signal_id BIGINT, 
    source_model TEXT NOT NULL, 
    source_signal_type TEXT NOT NULL, 
    symbol TEXT NOT NULL, 
    trade_date DATE NOT NULL, 
    handoff_status TEXT NOT NULL, 
    handoff_reason_codes TEXT[], 
    blocked_reason_codes TEXT[], 
    allowed_buy_point_types TEXT[], 
    feature_snapshot_id BIGINT, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_audit_model_execution_handoff PRIMARY KEY (handoff_audit_id)
);

CREATE INDEX idx_audit_model_execution_handoff_symbol ON decision.audit_model_execution_handoff (symbol, trade_date);

CREATE TABLE decision.audit_recompute (
    recompute_id BIGSERIAL NOT NULL, 
    model_code TEXT NOT NULL, 
    symbol TEXT NOT NULL, 
    trade_date DATE NOT NULL, 
    original_model_version TEXT, 
    recompute_model_version TEXT NOT NULL, 
    trigger_source TEXT NOT NULL, 
    trigger_reason TEXT NOT NULL, 
    changed_fields TEXT[], 
    original_result_hash TEXT, 
    recompute_result_hash TEXT, 
    recompute_status TEXT NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_audit_recompute PRIMARY KEY (recompute_id)
);

CREATE TABLE decision.audit_config_change (
    config_audit_id BIGSERIAL NOT NULL, 
    config_domain TEXT NOT NULL, 
    target_code TEXT NOT NULL, 
    old_config_hash TEXT, 
    new_config_hash TEXT NOT NULL, 
    changed_by TEXT, 
    change_reason TEXT NOT NULL, 
    related_experiment_id BIGINT, 
    approved_by TEXT, 
    approved_at TIMESTAMP WITH TIME ZONE, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_audit_config_change PRIMARY KEY (config_audit_id)
);

CREATE TABLE decision.execution_model_signal_v1 (
    signal_id TEXT NOT NULL, 
    business_model TEXT NOT NULL, 
    model_version TEXT NOT NULL, 
    model_version_tag VARCHAR(96), 
    signal_source TEXT NOT NULL, 
    symbol TEXT NOT NULL, 
    trade_date DATE NOT NULL, 
    batch_id BIGINT, 
    signal_time TIMESTAMP WITH TIME ZONE NOT NULL, 
    tick_timestamp TIMESTAMP WITH TIME ZONE, 
    calc_timestamp TIMESTAMP WITH TIME ZONE, 
    signal_state TEXT NOT NULL, 
    signal_score NUMERIC(18, 10), 
    rank_no INTEGER, 
    evidence_level TEXT, 
    entry_reference_price NUMERIC(18, 8), 
    target_price NUMERIC(18, 8), 
    risk_price NUMERIC(18, 8), 
    source_snapshot_id BIGINT, 
    source_quality_json JSONB DEFAULT '{}'::jsonb NOT NULL, 
    fill_state_json JSONB DEFAULT '{}'::jsonb NOT NULL, 
    payload_hash TEXT NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_execution_model_signal_v1 PRIMARY KEY (signal_id)
);

CREATE INDEX idx_execution_model_signal_v1_model_date ON decision.execution_model_signal_v1 (business_model, trade_date);

CREATE TABLE decision.execution_buy_point_snapshot_v1 (
    buy_point_id BIGSERIAL NOT NULL, 
    signal_id TEXT NOT NULL, 
    business_model TEXT NOT NULL, 
    model_version TEXT NOT NULL, 
    model_version_tag VARCHAR(96), 
    strategy_version TEXT NOT NULL, 
    symbol TEXT NOT NULL, 
    trade_date DATE NOT NULL, 
    as_of_time TIMESTAMP WITH TIME ZONE NOT NULL, 
    tick_timestamp TIMESTAMP WITH TIME ZONE, 
    calc_timestamp TIMESTAMP WITH TIME ZONE, 
    candidate_buy_time TIMESTAMP WITH TIME ZONE NOT NULL, 
    candidate_buy_window TEXT NOT NULL, 
    estimated_exec_price NUMERIC(18, 8), 
    exec_price_type TEXT NOT NULL, 
    buy_timing_score NUMERIC(18, 10), 
    alpha_retention_score NUMERIC(18, 10), 
    vwap_position_score NUMERIC(18, 10), 
    pullback_quality_score NUMERIC(18, 10), 
    volume_confirmation_score NUMERIC(18, 10), 
    liquidity_score NUMERIC(18, 10), 
    risk_reward_score NUMERIC(18, 10), 
    market_context_score NUMERIC(18, 10), 
    overheat_penalty NUMERIC(18, 10), 
    breakdown_risk_penalty NUMERIC(18, 10), 
    stale_data_penalty NUMERIC(18, 10), 
    fill_probability NUMERIC(18, 10), 
    expected_slippage_bps NUMERIC(18, 10), 
    risk_reward_ratio NUMERIC(18, 10), 
    current_price NUMERIC(18, 8), 
    intraday_vwap NUMERIC(18, 8), 
    vwap_deviation_pct NUMERIC(18, 10), 
    recent_volume_ratio NUMERIC(18, 10), 
    remaining_upside_pct NUMERIC(18, 10), 
    downside_to_risk_pct NUMERIC(18, 10), 
    buy_point_status TEXT NOT NULL, 
    block_reason_codes TEXT[], 
    source_gap_codes TEXT[], 
    data_freshness_status TEXT NOT NULL, 
    evidence_snapshot_ids BIGINT[], 
    source_quality_json JSONB DEFAULT '{}'::jsonb NOT NULL, 
    fill_state_json JSONB DEFAULT '{}'::jsonb NOT NULL, 
    payload_hash TEXT NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_execution_buy_point_snapshot_v1 PRIMARY KEY (buy_point_id)
);

CREATE UNIQUE INDEX uq_execution_buy_point_snapshot_v1_identity ON decision.execution_buy_point_snapshot_v1 (signal_id, strategy_version, candidate_buy_time);

CREATE INDEX idx_execution_buy_point_snapshot_v1_status ON decision.execution_buy_point_snapshot_v1 (business_model, trade_date, buy_point_status);

CREATE TABLE decision.execution_buy_point_outcome_label_v1 (
    label_id BIGSERIAL NOT NULL, 
    buy_point_id BIGINT NOT NULL, 
    signal_id TEXT NOT NULL, 
    business_model TEXT NOT NULL, 
    strategy_version TEXT NOT NULL, 
    model_version_tag VARCHAR(96), 
    symbol TEXT NOT NULL, 
    trade_date DATE NOT NULL, 
    simulated_entry_time TIMESTAMP WITH TIME ZONE NOT NULL, 
    tick_timestamp TIMESTAMP WITH TIME ZONE, 
    calc_timestamp TIMESTAMP WITH TIME ZONE, 
    simulated_entry_price NUMERIC(18, 8), 
    entry_price_type TEXT NOT NULL, 
    first_hit_ts TIMESTAMP WITH TIME ZONE, 
    first_risk_ts TIMESTAMP WITH TIME ZONE, 
    future_max_return_1d NUMERIC(18, 10), 
    future_max_return_3d NUMERIC(18, 10), 
    future_max_return_5d NUMERIC(18, 10), 
    future_min_drawdown_1d NUMERIC(18, 10), 
    future_min_drawdown_3d NUMERIC(18, 10), 
    future_min_drawdown_5d NUMERIC(18, 10), 
    mfe_1d NUMERIC(18, 10), 
    mfe_3d NUMERIC(18, 10), 
    mfe_5d NUMERIC(18, 10), 
    mae_1d NUMERIC(18, 10), 
    mae_3d NUMERIC(18, 10), 
    mae_5d NUMERIC(18, 10), 
    risk_before_hit BOOLEAN, 
    realizable_hit_before_risk BOOLEAN, 
    buy_day_hit_not_sellable BOOLEAN, 
    spike_reversal BOOLEAN, 
    label_status TEXT NOT NULL, 
    path_resolution TEXT NOT NULL, 
    source_quality_json JSONB DEFAULT '{}'::jsonb NOT NULL, 
    fill_state_json JSONB DEFAULT '{}'::jsonb NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_execution_buy_point_outcome_label_v1 PRIMARY KEY (label_id)
);

CREATE UNIQUE INDEX uq_execution_buy_point_outcome_label_v1_buy_point ON decision.execution_buy_point_outcome_label_v1 (buy_point_id);

CREATE TABLE decision.execution_strategy_performance_v1 (
    performance_id BIGSERIAL NOT NULL, 
    strategy_version TEXT NOT NULL, 
    business_model TEXT NOT NULL, 
    evaluation_date DATE NOT NULL, 
    rolling_window_days INTEGER NOT NULL, 
    evaluated_count INTEGER NOT NULL, 
    avg_buy_timing_score NUMERIC, 
    avg_return_1d NUMERIC, 
    avg_return_3d NUMERIC, 
    avg_return_5d NUMERIC, 
    realizable_hit_before_risk_rate_pct NUMERIC, 
    risk_before_hit_rate_pct NUMERIC, 
    spike_reversal_rate_pct NUMERIC, 
    avg_mfe_5d NUMERIC, 
    avg_mae_5d NUMERIC, 
    avg_slippage_bps NUMERIC, 
    best_window_code TEXT, 
    worst_window_code TEXT, 
    strategy_health_status TEXT NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_execution_strategy_performance_v1 PRIMARY KEY (performance_id)
);

CREATE UNIQUE INDEX uq_execution_strategy_performance_v1_identity ON decision.execution_strategy_performance_v1 (strategy_version, business_model, evaluation_date, rolling_window_days);

CREATE TABLE decision.dim_research_methodology (
    methodology_code TEXT NOT NULL, 
    methodology_name TEXT NOT NULL, 
    methodology_family TEXT NOT NULL, 
    methodology_goal TEXT NOT NULL, 
    financial_hypothesis TEXT NOT NULL, 
    applicable_models TEXT[] NOT NULL, 
    applicable_signal_types TEXT[] NOT NULL, 
    applicable_buy_point_types TEXT[], 
    required_features TEXT[] NOT NULL, 
    required_labels TEXT[] NOT NULL, 
    invalid_when TEXT[] NOT NULL, 
    risk_controls TEXT[] NOT NULL, 
    jarvis_explain_focus TEXT[] NOT NULL, 
    status TEXT DEFAULT 'active' NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_dim_research_methodology PRIMARY KEY (methodology_code), 
    CONSTRAINT ck_dim_research_methodology_hypothesis_req CHECK (length(btrim(financial_hypothesis)) > 0), 
    CONSTRAINT ck_dim_research_methodology_features_req CHECK (cardinality(required_features) > 0), 
    CONSTRAINT ck_dim_research_methodology_status_allowed CHECK (status IN ('active','inactive','deprecated'))
);

CREATE INDEX idx_research_methodology_family ON decision.dim_research_methodology (methodology_family, status);

CREATE TABLE explain.explanation_request (
    request_id BIGSERIAL NOT NULL, 
    queue_id VARCHAR(160), 
    replay_source_request_id BIGINT, 
    replay_source_queue_id VARCHAR(160), 
    replay_batch_id VARCHAR(96), 
    replay_reason TEXT, 
    execution_status VARCHAR(16) DEFAULT 'queued' NOT NULL, 
    persistence_source VARCHAR(32) DEFAULT 'workflow_service' NOT NULL, 
    target_type VARCHAR(32) NOT NULL, 
    target_id VARCHAR(64), 
    version_id BIGINT, 
    item_id BIGINT, 
    endpoint_path VARCHAR(256) NOT NULL, 
    request_query_json JSONB NOT NULL, 
    operator_mode VARCHAR(64), 
    priority VARCHAR(16), 
    task_contract_json JSONB, 
    source_lane VARCHAR(32), 
    source_evaluation_mode VARCHAR(32), 
    horizon_days INTEGER, 
    target_return_pct NUMERIC(12, 6), 
    entry_basis VARCHAR(32), 
    profile_scope VARCHAR(96), 
    target_hit BOOLEAN, 
    max_return_pct NUMERIC(12, 6), 
    error_detail TEXT, 
    executed_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_explanation_request PRIMARY KEY (request_id)
);

CREATE INDEX idx_explanation_request_version ON explain.explanation_request (version_id, executed_at);

CREATE INDEX idx_explanation_request_item ON explain.explanation_request (item_id, executed_at);

CREATE INDEX idx_explanation_request_status ON explain.explanation_request (execution_status, executed_at);

CREATE INDEX idx_explanation_request_replay_source_request ON explain.explanation_request (replay_source_request_id, executed_at);

CREATE INDEX idx_explanation_request_queue ON explain.explanation_request (queue_id, executed_at);

CREATE INDEX idx_explanation_request_replay_batch ON explain.explanation_request (replay_batch_id, executed_at);

CREATE INDEX idx_explanation_request_target ON explain.explanation_request (target_type, target_id, executed_at);

CREATE TABLE explain.jarvis_thread (
    thread_id VARCHAR(64) NOT NULL, 
    tenant_id VARCHAR(64) NOT NULL, 
    user_id VARCHAR(64) NOT NULL, 
    session_id VARCHAR(128), 
    user_role VARCHAR(64) NOT NULL, 
    permission_hash VARCHAR(128) NOT NULL, 
    page_code VARCHAR(128) NOT NULL, 
    route_code VARCHAR(128), 
    business_model VARCHAR(128), 
    subject_id VARCHAR(256), 
    visibility VARCHAR(32) DEFAULT 'private' NOT NULL, 
    title VARCHAR(256), 
    status VARCHAR(32) DEFAULT 'active' NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_jarvis_thread PRIMARY KEY (thread_id)
);

CREATE INDEX idx_jarvis_thread_subject ON explain.jarvis_thread (tenant_id, user_id, business_model, subject_id);

CREATE INDEX idx_jarvis_thread_user_page ON explain.jarvis_thread (tenant_id, user_id, page_code, updated_at DESC);

CREATE TABLE explain.jarvis_run (
    run_id VARCHAR(64) NOT NULL, 
    thread_id VARCHAR(64) NOT NULL, 
    tenant_id VARCHAR(64) NOT NULL, 
    user_id VARCHAR(64) NOT NULL, 
    session_id VARCHAR(128), 
    user_role VARCHAR(64) NOT NULL, 
    permission_hash VARCHAR(128) NOT NULL, 
    scenario_code VARCHAR(256) NOT NULL, 
    runtime_profile VARCHAR(128) NOT NULL, 
    model_name VARCHAR(128) NOT NULL, 
    reasoning_effort VARCHAR(32) NOT NULL, 
    prompt_bundle_hash VARCHAR(128), 
    prompt_version VARCHAR(64), 
    context_packet_id VARCHAR(64), 
    status VARCHAR(32) NOT NULL, 
    attempt_no INTEGER DEFAULT '1' NOT NULL, 
    parent_run_id VARCHAR(64), 
    client_request_id VARCHAR(128), 
    error_code VARCHAR(128), 
    error_message TEXT, 
    started_at TIMESTAMP WITH TIME ZONE, 
    completed_at TIMESTAMP WITH TIME ZONE, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_jarvis_run PRIMARY KEY (run_id)
);

CREATE INDEX idx_jarvis_run_status ON explain.jarvis_run (status, created_at DESC);

CREATE INDEX idx_jarvis_run_client_request ON explain.jarvis_run (tenant_id, user_id, client_request_id);

CREATE INDEX idx_jarvis_run_thread ON explain.jarvis_run (tenant_id, user_id, thread_id, created_at DESC);

CREATE TABLE explain.jarvis_message (
    message_id VARCHAR(64) NOT NULL, 
    tenant_id VARCHAR(64) NOT NULL, 
    user_id VARCHAR(64) NOT NULL, 
    session_id VARCHAR(128), 
    user_role VARCHAR(64) NOT NULL, 
    permission_hash VARCHAR(128) NOT NULL, 
    thread_id VARCHAR(64) NOT NULL, 
    run_id VARCHAR(64), 
    role VARCHAR(32) NOT NULL, 
    content TEXT NOT NULL, 
    content_json JSONB, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_jarvis_message PRIMARY KEY (message_id)
);

CREATE INDEX idx_jarvis_message_thread ON explain.jarvis_message (tenant_id, user_id, thread_id);

CREATE INDEX idx_jarvis_message_run ON explain.jarvis_message (tenant_id, user_id, run_id);

CREATE TABLE explain.jarvis_stream_event_log (
    event_id BIGSERIAL NOT NULL, 
    tenant_id VARCHAR(64) NOT NULL, 
    user_id VARCHAR(64) NOT NULL, 
    session_id VARCHAR(128), 
    user_role VARCHAR(64) NOT NULL, 
    permission_hash VARCHAR(128) NOT NULL, 
    run_id VARCHAR(64) NOT NULL, 
    event_type VARCHAR(128) NOT NULL, 
    event_payload JSONB NOT NULL, 
    sequence_no INTEGER NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_jarvis_stream_event_log PRIMARY KEY (event_id), 
    CONSTRAINT uq_jarvis_stream_event_log_run_sequence UNIQUE (run_id, sequence_no)
);

CREATE INDEX idx_jarvis_stream_event_run ON explain.jarvis_stream_event_log (tenant_id, user_id, run_id);

CREATE TABLE explain.jarvis_runtime_config (
    config_id BIGSERIAL NOT NULL, 
    profile_code VARCHAR(128) NOT NULL, 
    model_name VARCHAR(128) NOT NULL, 
    reasoning_effort VARCHAR(32) NOT NULL, 
    reasoning_summary VARCHAR(32), 
    stream_enabled BOOLEAN DEFAULT true NOT NULL, 
    max_output_tokens INTEGER NOT NULL, 
    temperature NUMERIC(4, 3) NOT NULL, 
    service_tier VARCHAR(32), 
    timeout_seconds INTEGER NOT NULL, 
    retry_policy JSONB NOT NULL, 
    allowed_roles JSONB NOT NULL, 
    is_active BOOLEAN DEFAULT true NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_jarvis_runtime_config PRIMARY KEY (config_id), 
    CONSTRAINT uq_jarvis_runtime_config_profile_code UNIQUE (profile_code)
);

CREATE TABLE explain.jarvis_prompt_registry (
    prompt_id BIGSERIAL NOT NULL, 
    prompt_code VARCHAR(256) NOT NULL, 
    business_model VARCHAR(128), 
    navigation_domain VARCHAR(128), 
    scenario_code VARCHAR(256) NOT NULL, 
    evidence_level VARCHAR(64), 
    prompt_role VARCHAR(64) NOT NULL, 
    prompt_version VARCHAR(64) NOT NULL, 
    prompt_text TEXT NOT NULL, 
    input_schema JSONB, 
    output_schema JSONB, 
    forbidden_rules JSONB, 
    is_active BOOLEAN DEFAULT true NOT NULL, 
    created_by VARCHAR(64), 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_jarvis_prompt_registry PRIMARY KEY (prompt_id), 
    CONSTRAINT uq_jarvis_prompt_registry_code_version UNIQUE (prompt_code, prompt_version)
);

CREATE INDEX idx_jarvis_prompt_registry_scenario ON explain.jarvis_prompt_registry (scenario_code, is_active);

CREATE TABLE explain.jarvis_context_packet (
    context_packet_id VARCHAR(64) NOT NULL, 
    tenant_id VARCHAR(64) NOT NULL, 
    user_id VARCHAR(64) NOT NULL, 
    session_id VARCHAR(128), 
    user_role VARCHAR(64) NOT NULL, 
    permission_hash VARCHAR(128) NOT NULL, 
    page_code VARCHAR(128) NOT NULL, 
    route_code VARCHAR(128), 
    scenario_code VARCHAR(256) NOT NULL, 
    business_model VARCHAR(128), 
    subject_id VARCHAR(256), 
    evidence_level VARCHAR(64), 
    allowed_explanation_scope JSONB NOT NULL, 
    forbidden_explanation_scope JSONB NOT NULL, 
    payload_json JSONB NOT NULL, 
    payload_hash VARCHAR(128) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_jarvis_context_packet PRIMARY KEY (context_packet_id)
);

CREATE INDEX idx_jarvis_context_packet_owner ON explain.jarvis_context_packet (tenant_id, user_id, created_at DESC);

CREATE INDEX idx_jarvis_context_packet_subject ON explain.jarvis_context_packet (tenant_id, user_id, business_model, subject_id);

CREATE TABLE explain.jarvis_explanation_result (
    explanation_id VARCHAR(64) NOT NULL, 
    tenant_id VARCHAR(64) NOT NULL, 
    user_id VARCHAR(64) NOT NULL, 
    session_id VARCHAR(128), 
    user_role VARCHAR(64) NOT NULL, 
    permission_hash VARCHAR(128) NOT NULL, 
    thread_id VARCHAR(64) NOT NULL, 
    run_id VARCHAR(64) NOT NULL, 
    context_packet_id VARCHAR(64) NOT NULL, 
    prompt_bundle_hash VARCHAR(128) NOT NULL, 
    runtime_profile VARCHAR(128) NOT NULL, 
    model_name VARCHAR(128) NOT NULL, 
    explanation_json JSONB NOT NULL, 
    explanation_text TEXT NOT NULL, 
    evidence_refs_used JSONB NOT NULL, 
    compliance_status VARCHAR(32) NOT NULL, 
    compliance_gap_codes JSONB, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_jarvis_explanation_result PRIMARY KEY (explanation_id)
);

CREATE INDEX idx_jarvis_explanation_result_run ON explain.jarvis_explanation_result (tenant_id, user_id, run_id);

CREATE INDEX idx_jarvis_explanation_result_compliance ON explain.jarvis_explanation_result (compliance_status, created_at DESC);

CREATE TABLE explain.jarvis_action_request (
    action_request_id VARCHAR(64) NOT NULL, 
    tenant_id VARCHAR(64) NOT NULL, 
    user_id VARCHAR(64) NOT NULL, 
    session_id VARCHAR(128), 
    user_role VARCHAR(64) NOT NULL, 
    permission_hash VARCHAR(128) NOT NULL, 
    source_run_id VARCHAR(64) NOT NULL, 
    action_code VARCHAR(128) NOT NULL, 
    action_payload JSONB NOT NULL, 
    approval_status VARCHAR(32) DEFAULT 'pending' NOT NULL, 
    execution_status VARCHAR(32) DEFAULT 'not_started' NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    approved_at TIMESTAMP WITH TIME ZONE, 
    executed_at TIMESTAMP WITH TIME ZONE, 
    CONSTRAINT pk_jarvis_action_request PRIMARY KEY (action_request_id)
);

CREATE INDEX idx_jarvis_action_request_owner ON explain.jarvis_action_request (tenant_id, user_id, created_at DESC);

CREATE INDEX idx_jarvis_action_request_run ON explain.jarvis_action_request (source_run_id, created_at DESC);

CREATE TABLE explain.system_audit_log (
    audit_id BIGSERIAL NOT NULL, 
    tenant_id VARCHAR(64) NOT NULL, 
    user_id VARCHAR(64) NOT NULL, 
    session_id VARCHAR(128), 
    user_role VARCHAR(64) NOT NULL, 
    permission_hash VARCHAR(128) NOT NULL, 
    audit_scope VARCHAR(128) NOT NULL, 
    event_code VARCHAR(128) NOT NULL, 
    source_run_id VARCHAR(64), 
    target_type VARCHAR(64), 
    target_id VARCHAR(128), 
    audit_payload JSONB NOT NULL, 
    audit_status VARCHAR(32) DEFAULT 'recorded' NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_system_audit_log PRIMARY KEY (audit_id)
);

CREATE INDEX idx_system_audit_log_owner ON explain.system_audit_log (tenant_id, user_id, created_at DESC);

CREATE INDEX idx_system_audit_log_scope ON explain.system_audit_log (audit_scope, event_code, created_at DESC);

CREATE TABLE explain.jarvis_token_usage (
    usage_id BIGSERIAL NOT NULL, 
    tenant_id VARCHAR(64) NOT NULL, 
    user_id VARCHAR(64) NOT NULL, 
    session_id VARCHAR(128), 
    user_role VARCHAR(64) NOT NULL, 
    permission_hash VARCHAR(128) NOT NULL, 
    run_id VARCHAR(64) NOT NULL, 
    runtime_profile VARCHAR(128) NOT NULL, 
    model_name VARCHAR(128) NOT NULL, 
    input_tokens INTEGER, 
    output_tokens INTEGER, 
    reasoning_tokens INTEGER, 
    cached_input_tokens INTEGER, 
    estimated_cost NUMERIC(18, 6), 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_jarvis_token_usage PRIMARY KEY (usage_id)
);

CREATE INDEX idx_jarvis_token_usage_run ON explain.jarvis_token_usage (tenant_id, user_id, run_id);

CREATE TABLE market.candidate_pool_snapshot (
    snapshot_id BIGSERIAL NOT NULL, 
    provider core.provider_enum NOT NULL, 
    ingest_mode VARCHAR(32) DEFAULT 'external_ths_model' NOT NULL, 
    source_model_name VARCHAR(64), 
    source_model_version VARCHAR(64), 
    trading_day DATE NOT NULL, 
    fetched_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    trade_status market.trade_status_enum DEFAULT 'unknown'::market.trade_status_enum NOT NULL, 
    page_no INTEGER, 
    page_size INTEGER, 
    total_items INTEGER, 
    total_pages INTEGER, 
    raw_payload_id BIGINT, 
    is_final BOOLEAN DEFAULT false NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_candidate_pool_snapshot PRIMARY KEY (snapshot_id)
);

CREATE INDEX idx_candidate_snapshot_provider_day ON market.candidate_pool_snapshot (provider, trading_day, fetched_at);

CREATE INDEX idx_candidate_snapshot_day ON market.candidate_pool_snapshot (trading_day, fetched_at);

CREATE TABLE market.market_breadth_snapshot (
    breadth_id BIGSERIAL NOT NULL, 
    provider core.provider_enum NOT NULL, 
    trading_day DATE NOT NULL, 
    captured_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    limit_up_num INTEGER, 
    limit_up_history_num INTEGER, 
    limit_up_rate NUMERIC(12, 6), 
    limit_up_open_num INTEGER, 
    limit_down_num INTEGER, 
    limit_down_history_num INTEGER, 
    limit_down_rate NUMERIC(12, 6), 
    limit_down_open_num INTEGER, 
    trade_status market.trade_status_enum DEFAULT 'unknown'::market.trade_status_enum NOT NULL, 
    raw_payload_id BIGINT, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_market_breadth_snapshot PRIMARY KEY (breadth_id)
);

CREATE INDEX idx_market_breadth_day ON market.market_breadth_snapshot (trading_day, captured_at);

CREATE TABLE market.theme_board (
    theme_id BIGSERIAL NOT NULL, 
    provider core.provider_enum NOT NULL, 
    provider_theme_code VARCHAR(32), 
    theme_type market.theme_type_enum NOT NULL, 
    theme_name VARCHAR(128) NOT NULL, 
    status VARCHAR(16) DEFAULT 'active' NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_theme_board PRIMARY KEY (theme_id)
);

CREATE INDEX idx_theme_board_name ON market.theme_board (theme_name);

CREATE UNIQUE INDEX uq_theme_board_provider_code ON market.theme_board (provider, provider_theme_code, theme_type);

CREATE TABLE market.northbound_summary (
    summary_id BIGSERIAL NOT NULL, 
    provider core.provider_enum NOT NULL, 
    trading_day DATE NOT NULL, 
    captured_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    direction VARCHAR(16) DEFAULT 'northbound' NOT NULL, 
    mutual_type VARCHAR(16), 
    mutual_type_name VARCHAR(32), 
    board_type VARCHAR(32), 
    index_code VARCHAR(32), 
    index_name VARCHAR(64), 
    fund_inflow NUMERIC(20, 2), 
    net_buy_amount NUMERIC(20, 2), 
    buy_amount NUMERIC(20, 2), 
    sell_amount NUMERIC(20, 2), 
    deal_amount NUMERIC(20, 2), 
    deal_count NUMERIC(20, 2), 
    quota_balance NUMERIC(20, 2), 
    quota_balance_text VARCHAR(64), 
    index_close_price NUMERIC(18, 4), 
    index_change_pct NUMERIC(12, 6), 
    lead_stock_code VARCHAR(32), 
    lead_stock_name VARCHAR(64), 
    lead_stock_change_pct NUMERIC(12, 6), 
    raw_payload_id BIGINT, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_northbound_summary PRIMARY KEY (summary_id)
);

CREATE INDEX idx_northbound_summary_day ON market.northbound_summary (trading_day, captured_at);

CREATE UNIQUE INDEX uq_northbound_summary_point ON market.northbound_summary (provider, trading_day, mutual_type, captured_at);

CREATE TABLE market.cross_market_asset (
    asset_id BIGSERIAL NOT NULL, 
    provider core.provider_enum NOT NULL, 
    asset_code VARCHAR(32) NOT NULL, 
    provider_asset_key VARCHAR(64), 
    asset_name VARCHAR(128) NOT NULL, 
    asset_class market.cross_market_asset_class_enum NOT NULL, 
    quote_currency VARCHAR(16), 
    metadata_json JSONB, 
    status VARCHAR(16) DEFAULT 'active' NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_cross_market_asset PRIMARY KEY (asset_id)
);

CREATE INDEX idx_cross_market_asset_class ON market.cross_market_asset (asset_class, asset_code);

CREATE UNIQUE INDEX uq_cross_market_asset_code ON market.cross_market_asset (provider, asset_code);

CREATE TABLE news.news_raw_item (
    raw_news_id BIGSERIAL NOT NULL, 
    source VARCHAR(32) NOT NULL, 
    provider core.provider_enum NOT NULL, 
    provider_news_id VARCHAR(64), 
    headline TEXT NOT NULL, 
    body TEXT, 
    url TEXT, 
    published_at TIMESTAMP WITH TIME ZONE, 
    fetched_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    author VARCHAR(128), 
    tags_json JSONB, 
    stock_refs_json JSONB, 
    raw_payload_id BIGINT, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_news_raw_item PRIMARY KEY (raw_news_id)
);

CREATE INDEX idx_news_raw_fetched ON news.news_raw_item (fetched_at);

CREATE UNIQUE INDEX uq_news_raw_source_id ON news.news_raw_item (provider, source, provider_news_id) WHERE provider_news_id IS NOT NULL;

CREATE INDEX idx_news_raw_published ON news.news_raw_item (published_at);

CREATE TABLE news.news_event (
    event_id UUID DEFAULT gen_random_uuid() NOT NULL, 
    source VARCHAR(32) NOT NULL, 
    event_type news.event_type_enum NOT NULL, 
    headline TEXT, 
    summary TEXT, 
    published_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    first_seen_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    importance_score NUMERIC(12, 6), 
    novelty_score NUMERIC(12, 6), 
    confidence_score NUMERIC(12, 6), 
    market_scope news.market_scope_enum DEFAULT 'mixed'::news.market_scope_enum NOT NULL, 
    direction news.direction_enum DEFAULT 'unknown'::news.direction_enum NOT NULL, 
    status VARCHAR(16) DEFAULT 'active' NOT NULL, 
    raw_ref_count INTEGER DEFAULT 1 NOT NULL, 
    cluster_key VARCHAR(128), 
    source_tier VARCHAR(16), 
    impact_level VARCHAR(16), 
    rule_hits_json JSONB, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_news_event PRIMARY KEY (event_id)
);

CREATE INDEX idx_news_event_published ON news.news_event (published_at);

CREATE INDEX idx_news_event_cluster ON news.news_event (cluster_key);

CREATE INDEX idx_news_event_type_scope ON news.news_event (event_type, market_scope);

CREATE TABLE news.news_source_observation (
    observation_id BIGSERIAL NOT NULL, 
    provider core.provider_enum NOT NULL, 
    logical_name VARCHAR(64) NOT NULL, 
    endpoint TEXT NOT NULL, 
    request_key TEXT, 
    requested_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    fetched_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    http_status INTEGER, 
    business_status VARCHAR(32) NOT NULL, 
    row_count INTEGER DEFAULT 0 NOT NULL, 
    accepted_count INTEGER DEFAULT 0 NOT NULL, 
    filtered_count INTEGER DEFAULT 0 NOT NULL, 
    empty_result BOOLEAN DEFAULT false NOT NULL, 
    degraded_reason TEXT, 
    payload_top_keys_json JSONB, 
    canonical_sample_json JSONB, 
    error_detail TEXT, 
    raw_payload_id BIGINT, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_news_source_observation PRIMARY KEY (observation_id)
);

CREATE INDEX idx_news_source_observation_provider ON news.news_source_observation (provider, logical_name, fetched_at);

CREATE TABLE raw.raw_payload (
    raw_payload_id BIGSERIAL NOT NULL, 
    provider core.provider_enum NOT NULL, 
    endpoint TEXT NOT NULL, 
    request_key TEXT, 
    http_status INTEGER, 
    fetched_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    payload_sha256 CHAR(64) NOT NULL, 
    payload_json JSONB NOT NULL, 
    payload_size INTEGER, 
    is_compressed BOOLEAN DEFAULT false NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_raw_payload PRIMARY KEY (raw_payload_id)
);

CREATE INDEX idx_raw_payload_fetched ON raw.raw_payload (provider, endpoint, fetched_at);

CREATE UNIQUE INDEX uq_raw_payload_sha ON raw.raw_payload (provider, endpoint, payload_sha256);

CREATE TABLE core.provider_symbol_map (
    map_id BIGSERIAL NOT NULL, 
    instrument_id BIGINT NOT NULL, 
    provider core.provider_enum NOT NULL, 
    provider_symbol VARCHAR(32) NOT NULL, 
    provider_market VARCHAR(32), 
    provider_extra JSONB, 
    is_primary BOOLEAN DEFAULT true NOT NULL, 
    effective_from TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    effective_to TIMESTAMP WITH TIME ZONE, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_provider_symbol_map PRIMARY KEY (map_id), 
    CONSTRAINT fk_provider_symbol_map_instrument_id_instrument_master FOREIGN KEY(instrument_id) REFERENCES core.instrument_master (instrument_id)
);

CREATE UNIQUE INDEX uq_provider_symbol_map ON core.provider_symbol_map (provider, provider_symbol, coalesce(provider_market, ''));

CREATE INDEX idx_provider_symbol_map_instrument ON core.provider_symbol_map (instrument_id, provider);

CREATE TABLE core.instrument_trading_rule (
    rule_id BIGSERIAL NOT NULL, 
    instrument_id BIGINT NOT NULL, 
    symbol VARCHAR(16) NOT NULL, 
    exchange VARCHAR(8) NOT NULL, 
    board core.board_enum NOT NULL, 
    trading_rule_profile VARCHAR(64) NOT NULL, 
    price_limit_regime VARCHAR(32) NOT NULL, 
    limit_pct NUMERIC(12, 6) NOT NULL, 
    is_st BOOLEAN DEFAULT false NOT NULL, 
    is_suspended BOOLEAN DEFAULT false NOT NULL, 
    is_delisting_risk BOOLEAN DEFAULT false NOT NULL, 
    listing_days INTEGER, 
    lot_size INTEGER DEFAULT '100' NOT NULL, 
    adjustment VARCHAR(16) DEFAULT 'qfq' NOT NULL, 
    source_provider core.provider_enum NOT NULL, 
    source_version VARCHAR(64) DEFAULT 'instrument_rule_v1' NOT NULL, 
    effective_from DATE NOT NULL, 
    effective_to DATE, 
    captured_at_utc TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_instrument_trading_rule PRIMARY KEY (rule_id), 
    CONSTRAINT ck_instrument_trading_rule_limit_pct_range CHECK (limit_pct > 0 AND limit_pct <= 0.30), 
    CONSTRAINT ck_instrument_trading_rule_lot_size_positive CHECK (lot_size > 0), 
    CONSTRAINT ck_instrument_trading_rule_effective_window_order CHECK (effective_to IS NULL OR effective_to >= effective_from), 
    CONSTRAINT fk_instrument_trading_rule_instrument_id_instrument_master FOREIGN KEY(instrument_id) REFERENCES core.instrument_master (instrument_id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX uq_instrument_trading_rule_window ON core.instrument_trading_rule (instrument_id, effective_from);

CREATE INDEX idx_instrument_trading_rule_symbol_window ON core.instrument_trading_rule (symbol, effective_from, effective_to);

CREATE TABLE decision.auction_feature_snapshot (
    snapshot_id BIGSERIAL NOT NULL, 
    instrument_id BIGINT NOT NULL, 
    trading_day DATE NOT NULL, 
    as_of_time TIMESTAMP WITH TIME ZONE NOT NULL, 
    feature_set_version VARCHAR(32) NOT NULL, 
    features_json JSONB NOT NULL, 
    data_quality NUMERIC(12, 6), 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_auction_feature_snapshot PRIMARY KEY (snapshot_id), 
    CONSTRAINT fk_auction_feature_snapshot_instrument_id_instrument_master FOREIGN KEY(instrument_id) REFERENCES core.instrument_master (instrument_id)
);

CREATE UNIQUE INDEX uq_auction_feature_snapshot ON decision.auction_feature_snapshot (instrument_id, trading_day, as_of_time, feature_set_version);

CREATE TABLE decision.recommendation_item (
    item_id BIGSERIAL NOT NULL, 
    version_id BIGINT NOT NULL, 
    instrument_id BIGINT NOT NULL, 
    provider VARCHAR(32), 
    provider_symbol VARCHAR(32), 
    provider_market VARCHAR(32), 
    rank_no INTEGER, 
    base_score NUMERIC(12, 6), 
    adjusted_score NUMERIC(12, 6), 
    confidence_score NUMERIC(12, 6), 
    state decision.item_state_enum DEFAULT 'active'::decision.item_state_enum NOT NULL, 
    thesis TEXT, 
    risk_flags JSONB, 
    decision_trace_json JSONB, 
    suggested_action VARCHAR(32), 
    position_bucket VARCHAR(16), 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_recommendation_item PRIMARY KEY (item_id), 
    CONSTRAINT fk_recommendation_item_version_id_recommendation_version FOREIGN KEY(version_id) REFERENCES decision.recommendation_version (version_id), 
    CONSTRAINT fk_recommendation_item_instrument_id_instrument_master FOREIGN KEY(instrument_id) REFERENCES core.instrument_master (instrument_id)
);

CREATE UNIQUE INDEX uq_recommendation_item_version_instrument ON decision.recommendation_item (version_id, instrument_id);

CREATE INDEX idx_recommendation_item_rank ON decision.recommendation_item (version_id, rank_no);

CREATE TABLE decision.candidate_state_transition (
    transition_id BIGSERIAL NOT NULL, 
    instrument_id BIGINT NOT NULL, 
    trading_day DATE NOT NULL, 
    from_state decision.item_state_enum, 
    to_state decision.item_state_enum NOT NULL, 
    reason_type decision.reason_type_enum NOT NULL, 
    reason_ref_id VARCHAR(128), 
    affected_version_id BIGINT, 
    changed_by VARCHAR(32) DEFAULT 'system' NOT NULL, 
    changed_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_candidate_state_transition PRIMARY KEY (transition_id), 
    CONSTRAINT fk_candidate_state_transition_instrument_id_instrument_master FOREIGN KEY(instrument_id) REFERENCES core.instrument_master (instrument_id)
);

CREATE INDEX idx_candidate_state_transition_version ON decision.candidate_state_transition (affected_version_id, changed_at);

CREATE INDEX idx_candidate_state_transition_day ON decision.candidate_state_transition (trading_day, instrument_id, changed_at);

CREATE TABLE decision.event_impact_log (
    impact_id BIGSERIAL NOT NULL, 
    event_id UUID NOT NULL, 
    entity_type news.entity_type_enum NOT NULL, 
    entity_id BIGINT NOT NULL, 
    impact_scope VARCHAR(32) NOT NULL, 
    impact_direction news.direction_enum NOT NULL, 
    impact_strength NUMERIC(12, 6), 
    affected_version_id BIGINT, 
    affected_item_id BIGINT, 
    action_taken VARCHAR(32), 
    logged_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_event_impact_log PRIMARY KEY (impact_id), 
    CONSTRAINT fk_event_impact_log_event_id_news_event FOREIGN KEY(event_id) REFERENCES news.news_event (event_id)
);

CREATE INDEX idx_event_impact_entity ON decision.event_impact_log (entity_type, entity_id, logged_at);

CREATE INDEX idx_event_impact_event ON decision.event_impact_log (event_id, logged_at);

CREATE TABLE decision.brain_subject_state (
    state_id BIGSERIAL NOT NULL, 
    instrument_id BIGINT, 
    symbol_snapshot VARCHAR(32) NOT NULL, 
    business_line VARCHAR(32) NOT NULL, 
    state VARCHAR(24) DEFAULT 'observe' NOT NULL, 
    priority_score NUMERIC(12, 6) DEFAULT '0' NOT NULL, 
    confidence_score NUMERIC(12, 6), 
    sampling_level VARCHAR(32) DEFAULT 'level1_watch' NOT NULL, 
    analysis_weight_multiplier NUMERIC(12, 6) DEFAULT '1' NOT NULL, 
    next_poll_at TIMESTAMP WITH TIME ZONE, 
    last_signal_at TIMESTAMP WITH TIME ZONE, 
    last_transition_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    reason_code VARCHAR(64), 
    evidence_json JSONB, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_brain_subject_state PRIMARY KEY (state_id), 
    CONSTRAINT fk_brain_subject_state_instrument_id_instrument_master FOREIGN KEY(instrument_id) REFERENCES core.instrument_master (instrument_id)
);

CREATE INDEX idx_brain_subject_state_instrument ON decision.brain_subject_state (instrument_id, business_line);

CREATE INDEX idx_brain_subject_state_next_poll ON decision.brain_subject_state (state, next_poll_at);

CREATE UNIQUE INDEX uq_brain_subject_state_line_symbol ON decision.brain_subject_state (business_line, symbol_snapshot);

CREATE TABLE decision.dynamic_feature_snapshot (
    snapshot_id BIGSERIAL NOT NULL, 
    run_id BIGINT, 
    instrument_id BIGINT, 
    symbol_snapshot VARCHAR(32) NOT NULL, 
    scope VARCHAR(32) NOT NULL, 
    trading_day DATE NOT NULL, 
    as_of_time TIMESTAMP WITH TIME ZONE NOT NULL, 
    window_seconds INTEGER NOT NULL, 
    feature_set_version VARCHAR(48) NOT NULL, 
    features_json JSONB NOT NULL, 
    source_gap_codes_json JSONB NOT NULL, 
    source_refs_json JSONB, 
    data_quality NUMERIC(12, 6), 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_dynamic_feature_snapshot PRIMARY KEY (snapshot_id), 
    CONSTRAINT fk_dynamic_feature_snapshot_run_id_dynamic_feature_run FOREIGN KEY(run_id) REFERENCES decision.dynamic_feature_run (run_id) ON DELETE CASCADE, 
    CONSTRAINT fk_dynamic_feature_snapshot_instrument_id_instrument_master FOREIGN KEY(instrument_id) REFERENCES core.instrument_master (instrument_id)
);

CREATE INDEX idx_dynamic_feature_snapshot_subject ON decision.dynamic_feature_snapshot (instrument_id, scope, trading_day, as_of_time);

CREATE INDEX idx_dynamic_feature_snapshot_scope_day ON decision.dynamic_feature_snapshot (scope, trading_day, window_seconds);

CREATE UNIQUE INDEX uq_dynamic_feature_snapshot_run_subject_window ON decision.dynamic_feature_snapshot (run_id, instrument_id, window_seconds, feature_set_version) NULLS NOT DISTINCT;

CREATE TABLE decision.ambush_scan_universe_v1 (
    universe_id BIGSERIAL NOT NULL, 
    as_of_trading_day DATE NOT NULL, 
    instrument_id BIGINT NOT NULL, 
    symbol TEXT NOT NULL, 
    name TEXT NOT NULL, 
    exchange TEXT NOT NULL, 
    asset_type TEXT NOT NULL, 
    board TEXT, 
    is_active BOOLEAN NOT NULL, 
    is_st BOOLEAN DEFAULT false NOT NULL, 
    is_suspended BOOLEAN DEFAULT false NOT NULL, 
    is_delisting_risk BOOLEAN DEFAULT false NOT NULL, 
    listing_days INTEGER, 
    price_limit_regime TEXT, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_ambush_scan_universe_v1 PRIMARY KEY (universe_id), 
    CONSTRAINT fk_ambush_scan_universe_v1_instrument_id FOREIGN KEY(instrument_id) REFERENCES core.instrument_master (instrument_id)
);

CREATE INDEX idx_ambush_scan_universe_v1_scope ON decision.ambush_scan_universe_v1 (as_of_trading_day, exchange, asset_type);

CREATE UNIQUE INDEX uq_ambush_scan_universe_v1_day_instrument ON decision.ambush_scan_universe_v1 (as_of_trading_day, instrument_id);

CREATE TABLE decision.ambush_valley_watch_pool_v1 (
    valley_id BIGSERIAL NOT NULL, 
    trade_date DATE NOT NULL, 
    symbol TEXT NOT NULL, 
    instrument_id BIGINT NOT NULL, 
    exchange TEXT NOT NULL, 
    board TEXT, 
    as_of_time TIMESTAMP WITH TIME ZONE NOT NULL, 
    best_window_days INTEGER NOT NULL, 
    primary_trough_day DATE NOT NULL, 
    primary_trough_low NUMERIC(18, 6) NOT NULL, 
    primary_trough_age_days INTEGER NOT NULL, 
    close_to_trough_pct NUMERIC(12, 6) NOT NULL, 
    rolling_drawdown_pct NUMERIC(12, 6) NOT NULL, 
    downside_velocity_slowdown_score NUMERIC(12, 6), 
    bottom_area_stability_score NUMERIC(12, 6), 
    volatility_contraction_score NUMERIC(12, 6), 
    valley_watch_score NUMERIC(12, 6), 
    valley_status TEXT NOT NULL, 
    valley_reason_codes TEXT[], 
    invalidation_reason_codes TEXT[], 
    source_gap_codes TEXT[], 
    evidence_refs JSONB DEFAULT '[]'::jsonb NOT NULL, 
    payload_hash TEXT NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_ambush_valley_watch_pool_v1 PRIMARY KEY (valley_id), 
    CONSTRAINT fk_ambush_valley_watch_pool_v1_instrument_id FOREIGN KEY(instrument_id) REFERENCES core.instrument_master (instrument_id)
);

CREATE INDEX idx_ambush_valley_watch_pool_v1_status ON decision.ambush_valley_watch_pool_v1 (trade_date, valley_status, valley_watch_score);

CREATE UNIQUE INDEX uq_ambush_valley_watch_pool_v1_trade_symbol ON decision.ambush_valley_watch_pool_v1 (trade_date, symbol);

CREATE TABLE decision.ambush_pool_transition_audit_v1 (
    transition_id BIGSERIAL NOT NULL, 
    symbol TEXT NOT NULL, 
    instrument_id BIGINT NOT NULL, 
    from_pool TEXT NOT NULL, 
    to_pool TEXT NOT NULL, 
    from_status TEXT, 
    to_status TEXT, 
    trigger_event TEXT NOT NULL, 
    trigger_as_of_time TIMESTAMP WITH TIME ZONE NOT NULL, 
    trigger_snapshot_type TEXT NOT NULL, 
    trigger_feature_json JSONB NOT NULL, 
    transition_time TIMESTAMP WITH TIME ZONE NOT NULL, 
    transition_reason TEXT NOT NULL, 
    trigger_feature_snapshot JSONB NOT NULL, 
    model_version TEXT NOT NULL, 
    decision_rule_version TEXT NOT NULL, 
    decision_result TEXT NOT NULL, 
    reject_reason_codes TEXT[], 
    evidence_refs JSONB DEFAULT '[]'::jsonb NOT NULL, 
    created_by_job TEXT NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_ambush_pool_transition_audit_v1 PRIMARY KEY (transition_id), 
    CONSTRAINT fk_ambush_pool_transition_audit_v1_instrument_id FOREIGN KEY(instrument_id) REFERENCES core.instrument_master (instrument_id)
);

CREATE INDEX idx_ambush_pool_transition_audit_v1_pool ON decision.ambush_pool_transition_audit_v1 (from_pool, to_pool, decision_result);

CREATE INDEX idx_ambush_pool_transition_audit_v1_symbol_time ON decision.ambush_pool_transition_audit_v1 (symbol, trigger_as_of_time);

CREATE TABLE decision.research_model_signal_snapshot_v1 (
    signal_id BIGSERIAL NOT NULL, 
    business_model TEXT NOT NULL, 
    model_version TEXT NOT NULL, 
    model_version_tag VARCHAR(96), 
    signal_version TEXT NOT NULL, 
    symbol TEXT NOT NULL, 
    instrument_id BIGINT, 
    name TEXT, 
    business_date DATE, 
    trade_date DATE NOT NULL, 
    as_of_time TIMESTAMP WITH TIME ZONE NOT NULL, 
    tick_timestamp TIMESTAMP WITH TIME ZONE, 
    calc_timestamp TIMESTAMP WITH TIME ZONE, 
    captured_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    source_batch_id BIGINT, 
    source_pool TEXT, 
    source_rank_no INTEGER, 
    model_score NUMERIC(18, 10), 
    model_rank INTEGER, 
    model_state TEXT, 
    evidence_level TEXT, 
    risk_level TEXT, 
    signal_type TEXT, 
    signal_stage TEXT, 
    main_positive_factors JSONB, 
    main_negative_factors JSONB, 
    hard_block_reasons TEXT[], 
    source_gap_codes TEXT[], 
    source_quality_json JSONB DEFAULT '{}'::jsonb NOT NULL, 
    fill_state_json JSONB DEFAULT '{}'::jsonb NOT NULL, 
    feature_snapshot_id BIGINT, 
    evidence_snapshot_ids BIGINT[], 
    payload_hash TEXT NOT NULL, 
    is_official BOOLEAN DEFAULT true NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_research_model_signal_snapshot_v1 PRIMARY KEY (signal_id), 
    CONSTRAINT ck_research_model_signal_snapshot_v1_nofut CHECK (captured_at <= as_of_time), 
    CONSTRAINT fk_research_signal_instrument FOREIGN KEY(instrument_id) REFERENCES core.instrument_master (instrument_id), 
    CONSTRAINT fk_research_signal_feature FOREIGN KEY(feature_snapshot_id) REFERENCES decision.research_feature_snapshot_v1 (feature_snapshot_id)
);

CREATE UNIQUE INDEX uq_research_signal_snapshot_v1 ON decision.research_model_signal_snapshot_v1 (business_model, model_version, symbol, trade_date, as_of_time, signal_version);

CREATE INDEX idx_research_signal_snapshot_rank ON decision.research_model_signal_snapshot_v1 (business_model, trade_date, model_rank);

CREATE TABLE decision.research_ablation_result_v1 (
    result_id BIGSERIAL NOT NULL, 
    experiment_id BIGINT NOT NULL, 
    evaluated_count INTEGER NOT NULL, 
    baseline_primary_metric NUMERIC(12, 6), 
    test_primary_metric NUMERIC(12, 6), 
    metric_delta NUMERIC(12, 6), 
    baseline_risk_metric NUMERIC(12, 6), 
    test_risk_metric NUMERIC(12, 6), 
    risk_delta NUMERIC(12, 6), 
    baseline_avg_return_pct NUMERIC(12, 6), 
    test_avg_return_pct NUMERIC(12, 6), 
    baseline_max_drawdown_pct NUMERIC(12, 6), 
    test_max_drawdown_pct NUMERIC(12, 6), 
    pass_status TEXT NOT NULL, 
    fail_reason TEXT[], 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_research_ablation_result_v1 PRIMARY KEY (result_id), 
    CONSTRAINT fk_research_ablation_result_experiment FOREIGN KEY(experiment_id) REFERENCES decision.research_ablation_experiment_v1 (experiment_id)
);

CREATE INDEX idx_research_ablation_result_experiment ON decision.research_ablation_result_v1 (experiment_id, created_at);

CREATE TABLE decision.data_inspection_subject (
    subject_id BIGSERIAL NOT NULL, 
    run_id BIGINT NOT NULL, 
    instrument_id BIGINT, 
    symbol_snapshot VARCHAR(32) NOT NULL, 
    scope VARCHAR(128) NOT NULL, 
    expected_domain_count INTEGER NOT NULL, 
    observed_domain_count INTEGER NOT NULL, 
    missing_domain_count INTEGER NOT NULL, 
    fine_time_gap_count INTEGER DEFAULT '0' NOT NULL, 
    coarse_time_gap_count INTEGER DEFAULT '0' NOT NULL, 
    inspection_status VARCHAR(24) NOT NULL, 
    completeness_score NUMERIC(12, 6) NOT NULL, 
    summary_json JSONB, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_data_inspection_subject PRIMARY KEY (subject_id), 
    CONSTRAINT fk_data_inspection_subject_run_id_data_inspection_run FOREIGN KEY(run_id) REFERENCES decision.data_inspection_run (run_id) ON DELETE CASCADE, 
    CONSTRAINT fk_data_inspection_subject_instrument_id_instrument_master FOREIGN KEY(instrument_id) REFERENCES core.instrument_master (instrument_id)
);

CREATE INDEX idx_data_inspection_subject_symbol ON decision.data_inspection_subject (symbol_snapshot, scope);

CREATE INDEX idx_data_inspection_subject_run ON decision.data_inspection_subject (run_id, completeness_score);

CREATE TABLE decision.dim_model_version (
    model_version_id BIGSERIAL NOT NULL, 
    model_code TEXT NOT NULL, 
    model_version TEXT NOT NULL, 
    config_hash TEXT NOT NULL, 
    code_commit_hash TEXT, 
    feature_schema_version TEXT, 
    label_schema_version TEXT, 
    effective_from TIMESTAMP WITH TIME ZONE NOT NULL, 
    effective_to TIMESTAMP WITH TIME ZONE, 
    is_active BOOLEAN DEFAULT true NOT NULL, 
    change_reason TEXT, 
    created_by TEXT, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_dim_model_version PRIMARY KEY (model_version_id), 
    CONSTRAINT fk_dim_model_version_model_code_dim_model FOREIGN KEY(model_code) REFERENCES decision.dim_model (model_code)
);

CREATE UNIQUE INDEX uq_dim_model_version_model_version ON decision.dim_model_version (model_code, model_version);

CREATE TABLE decision.dim_signal_type (
    signal_type_code TEXT NOT NULL, 
    source_model TEXT NOT NULL, 
    signal_name TEXT NOT NULL, 
    signal_stage TEXT NOT NULL, 
    can_handoff_to_execution BOOLEAN DEFAULT false NOT NULL, 
    default_ttl_minutes INTEGER, 
    description TEXT, 
    is_active BOOLEAN DEFAULT true NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_dim_signal_type PRIMARY KEY (signal_type_code), 
    CONSTRAINT fk_dim_signal_type_source_model_dim_model FOREIGN KEY(source_model) REFERENCES decision.dim_model (model_code)
);

CREATE INDEX idx_dim_signal_type_source ON decision.dim_signal_type (source_model, can_handoff_to_execution);

CREATE TABLE decision.dim_state (
    state_code TEXT NOT NULL, 
    owner_model TEXT NOT NULL, 
    state_name TEXT NOT NULL, 
    state_family TEXT NOT NULL, 
    is_terminal BOOLEAN DEFAULT false NOT NULL, 
    is_active BOOLEAN DEFAULT true NOT NULL, 
    description TEXT, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_dim_state PRIMARY KEY (state_code), 
    CONSTRAINT fk_dim_state_owner_model_dim_model FOREIGN KEY(owner_model) REFERENCES decision.dim_model (model_code)
);

CREATE INDEX idx_dim_state_owner ON decision.dim_state (owner_model, state_family);

CREATE TABLE decision.snapshot_evidence (
    evidence_snapshot_id BIGSERIAL NOT NULL, 
    evidence_source_code TEXT NOT NULL, 
    symbol TEXT, 
    trade_date DATE, 
    as_of_time TIMESTAMP WITH TIME ZONE NOT NULL, 
    captured_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    provider TEXT, 
    source_table TEXT, 
    source_primary_key TEXT, 
    payload_json JSONB NOT NULL, 
    payload_hash TEXT NOT NULL, 
    freshness_status TEXT NOT NULL, 
    source_gap_codes TEXT[], 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_snapshot_evidence PRIMARY KEY (evidence_snapshot_id), 
    CONSTRAINT fk_snapshot_evidence_source_code_dim_evidence FOREIGN KEY(evidence_source_code) REFERENCES decision.dim_evidence_source (source_code)
);

CREATE INDEX idx_snapshot_evidence_symbol_date ON decision.snapshot_evidence (symbol, trade_date);

CREATE INDEX idx_evidence_payload_hash ON decision.snapshot_evidence (payload_hash);

CREATE TABLE decision.fact_signal_feature_snapshot_v1 (
    feature_snapshot_id BIGSERIAL NOT NULL, 
    signal_id BIGINT, 
    snapshot_time TIMESTAMP WITH TIME ZONE NOT NULL, 
    tick_timestamp TIMESTAMP WITH TIME ZONE, 
    calc_timestamp TIMESTAMP WITH TIME ZONE, 
    model_version_tag VARCHAR(96), 
    observed_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    available_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    ingested_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    price_features_json JSONB DEFAULT '{}'::jsonb NOT NULL, 
    volume_features_json JSONB DEFAULT '{}'::jsonb NOT NULL, 
    auction_features_json JSONB DEFAULT '{}'::jsonb NOT NULL, 
    moneyflow_features_json JSONB DEFAULT '{}'::jsonb NOT NULL, 
    sector_features_json JSONB DEFAULT '{}'::jsonb NOT NULL, 
    news_features_json JSONB DEFAULT '{}'::jsonb NOT NULL, 
    market_features_json JSONB DEFAULT '{}'::jsonb NOT NULL, 
    risk_features_json JSONB DEFAULT '{}'::jsonb NOT NULL, 
    source_quality_json JSONB DEFAULT '{}'::jsonb NOT NULL, 
    fill_state_json JSONB DEFAULT '{}'::jsonb NOT NULL, 
    feature_schema_version VARCHAR(64) NOT NULL, 
    raw_payload_hash VARCHAR(128), 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_fact_signal_feature_snapshot_v1 PRIMARY KEY (feature_snapshot_id), 
    CONSTRAINT ck_fact_signal_feature_snapshot_v1_nofut CHECK (available_at <= snapshot_time), 
    CONSTRAINT fk_signal_feature_snapshot_v1_signal FOREIGN KEY(signal_id) REFERENCES decision.fact_model_signal_v1 (signal_id)
);

CREATE INDEX idx_signal_feature_snapshot_v1_signal ON decision.fact_signal_feature_snapshot_v1 (signal_id);

CREATE TABLE decision.fact_hot_signal_detail_v1 (
    hot_signal_detail_id BIGSERIAL NOT NULL, 
    signal_id BIGINT NOT NULL, 
    board_date DATE, 
    limit_up_stage INTEGER, 
    ths_limit_up_probability NUMERIC(8, 4), 
    teacher_probability_source VARCHAR(64) DEFAULT 'external_ths_model' NOT NULL, 
    teacher_probability_collected_at TIMESTAMP WITH TIME ZONE, 
    teacher_probability_available_at TIMESTAMP WITH TIME ZONE, 
    teacher_probability_bucket VARCHAR(32), 
    local_confirm_score NUMERIC(10, 4), 
    auction_status VARCHAR(64), 
    open_5m_vwap_status VARCHAR(64), 
    overheat_flag BOOLEAN DEFAULT false NOT NULL, 
    no_fill_flag BOOLEAN DEFAULT false NOT NULL, 
    limit_up_reason TEXT, 
    limit_up_reason_first_seen_at TIMESTAMP WITH TIME ZONE, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_fact_hot_signal_detail_v1 PRIMARY KEY (hot_signal_detail_id), 
    CONSTRAINT ck_fact_hot_signal_detail_v1_ths_range CHECK (ths_limit_up_probability IS NULL OR (ths_limit_up_probability >= 0 AND ths_limit_up_probability <= 100)), 
    CONSTRAINT fk_hot_signal_detail_v1_signal FOREIGN KEY(signal_id) REFERENCES decision.fact_model_signal_v1 (signal_id)
);

CREATE UNIQUE INDEX uq_hot_signal_detail_v1_signal ON decision.fact_hot_signal_detail_v1 (signal_id);

CREATE TABLE decision.fact_candidate_memory_signal_detail_v1 (
    memory_signal_detail_id BIGSERIAL NOT NULL, 
    signal_id BIGINT NOT NULL, 
    memory_entity_id BIGINT NOT NULL, 
    first_signal_date DATE NOT NULL, 
    reactivated_date DATE NOT NULL, 
    reactivated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    reactivation_from_state VARCHAR(64), 
    memory_age_days INTEGER, 
    ttl_remaining_days INTEGER, 
    memory_state VARCHAR(64), 
    memory_score NUMERIC(10, 4), 
    activation_strength_score NUMERIC(10, 4), 
    second_wave_trigger_code VARCHAR(64), 
    second_wave_trigger_detail JSONB DEFAULT '{}'::jsonb NOT NULL, 
    previous_high_price NUMERIC(12, 4), 
    breakout_price NUMERIC(12, 4), 
    pullback_hold_price NUMERIC(12, 4), 
    volume_reactivation_score NUMERIC(10, 4), 
    moneyflow_reactivation_score NUMERIC(10, 4), 
    sector_resonance_score NUMERIC(10, 4), 
    reactivation_available_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    reactivation_evidence_json JSONB DEFAULT '{}'::jsonb NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_fact_candidate_memory_signal_detail_v1 PRIMARY KEY (memory_signal_detail_id), 
    CONSTRAINT ck_fact_candidate_memory_signal_detail_v1_nofut CHECK (reactivation_available_at <= reactivated_at), 
    CONSTRAINT fk_memory_signal_detail_v1_signal FOREIGN KEY(signal_id) REFERENCES decision.fact_model_signal_v1 (signal_id), 
    CONSTRAINT fk_memory_signal_detail_v1_entity FOREIGN KEY(memory_entity_id) REFERENCES decision.fact_candidate_memory_entity_v1 (memory_entity_id)
);

CREATE UNIQUE INDEX uq_memory_signal_detail_v1_signal ON decision.fact_candidate_memory_signal_detail_v1 (signal_id);

CREATE TABLE decision.fact_candidate_memory_daily_state_v1 (
    memory_daily_state_id BIGSERIAL NOT NULL, 
    memory_entity_id BIGINT NOT NULL, 
    trade_date DATE NOT NULL, 
    memory_status VARCHAR(64) NOT NULL, 
    memory_age_days INTEGER, 
    ttl_remaining_days INTEGER, 
    memory_score NUMERIC(10, 4), 
    memory_decay_score NUMERIC(10, 4), 
    close_price NUMERIC(12, 4), 
    return_since_first_signal_pct NUMERIC(10, 4), 
    max_return_since_first_signal_pct NUMERIC(10, 4), 
    max_drawdown_since_first_signal_pct NUMERIC(10, 4), 
    state_reason_codes JSONB DEFAULT '[]'::jsonb NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_fact_candidate_memory_daily_state_v1 PRIMARY KEY (memory_daily_state_id), 
    CONSTRAINT fk_memory_daily_state_v1_entity FOREIGN KEY(memory_entity_id) REFERENCES decision.fact_candidate_memory_entity_v1 (memory_entity_id)
);

CREATE UNIQUE INDEX uq_memory_daily_state_v1_entity_day ON decision.fact_candidate_memory_daily_state_v1 (memory_entity_id, trade_date);

CREATE TABLE decision.fact_ambush_signal_detail_v1 (
    ambush_signal_detail_id BIGSERIAL NOT NULL, 
    signal_id BIGINT NOT NULL, 
    effective_turn_id BIGINT NOT NULL, 
    deep_confirm_id BIGINT, 
    valley_watch_id BIGINT, 
    near_miss_id BIGINT, 
    primary_trough_date DATE NOT NULL, 
    primary_trough_price NUMERIC(12, 4), 
    effective_turn_anchor_day DATE NOT NULL, 
    days_since_low_at_turn INTEGER, 
    effective_turn_age_days INTEGER, 
    turn_freshness_bucket VARCHAR(64), 
    shape_type VARCHAR(64), 
    valley_watch_score NUMERIC(10, 4), 
    effective_turn_score NUMERIC(10, 4), 
    dragon_priority_score NUMERIC(10, 4), 
    horizontal_breakout_recount_flag BOOLEAN DEFAULT false NOT NULL, 
    continuous_rebound_downgrade_flag BOOLEAN DEFAULT false NOT NULL, 
    late_rebound_penalty NUMERIC(10, 4), 
    release_gate_status VARCHAR(64) NOT NULL, 
    release_gate_reason_codes JSONB DEFAULT '[]'::jsonb NOT NULL, 
    snapshot_available_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_fact_ambush_signal_detail_v1 PRIMARY KEY (ambush_signal_detail_id), 
    CONSTRAINT fk_ambush_signal_detail_v1_signal FOREIGN KEY(signal_id) REFERENCES decision.fact_model_signal_v1 (signal_id)
);

CREATE UNIQUE INDEX uq_ambush_signal_detail_v1_signal ON decision.fact_ambush_signal_detail_v1 (signal_id);

CREATE TABLE decision.fact_buy_point_decision_v1 (
    buy_point_id BIGSERIAL NOT NULL, 
    signal_id BIGINT NOT NULL, 
    model_code VARCHAR(64) NOT NULL, 
    strategy_code VARCHAR(96) NOT NULL, 
    strategy_version VARCHAR(64) NOT NULL, 
    calc_stage VARCHAR(64) NOT NULL, 
    buy_point_status VARCHAR(64) NOT NULL, 
    calculated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    tick_timestamp TIMESTAMP WITH TIME ZONE, 
    calc_timestamp TIMESTAMP WITH TIME ZONE, 
    model_version_tag VARCHAR(96), 
    reference_entry_price NUMERIC(18, 8), 
    entry_price_low NUMERIC(18, 8), 
    entry_price_high NUMERIC(18, 8), 
    target_price NUMERIC(18, 8), 
    target_return_pct NUMERIC(18, 10), 
    invalidation_price NUMERIC(18, 8), 
    risk_reward_ratio NUMERIC(18, 10), 
    confidence_score NUMERIC(18, 10), 
    block_reason_codes JSONB DEFAULT '[]'::jsonb NOT NULL, 
    input_snapshot_json JSONB DEFAULT '{}'::jsonb NOT NULL, 
    decision_trace_json JSONB DEFAULT '{}'::jsonb NOT NULL, 
    source_quality_json JSONB DEFAULT '{}'::jsonb NOT NULL, 
    fill_state_json JSONB DEFAULT '{}'::jsonb NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_fact_buy_point_decision_v1 PRIMARY KEY (buy_point_id), 
    CONSTRAINT ck_fact_buy_point_decision_v1_positive_prices CHECK ((reference_entry_price IS NULL OR reference_entry_price > 0) AND (entry_price_low IS NULL OR entry_price_low > 0) AND (entry_price_high IS NULL OR entry_price_high > 0) AND (target_price IS NULL OR target_price > 0) AND (invalidation_price IS NULL OR invalidation_price > 0)), 
    CONSTRAINT ck_fact_buy_point_decision_v1_entry_range CHECK (reference_entry_price IS NULL OR entry_price_low IS NULL OR entry_price_high IS NULL OR (entry_price_low <= reference_entry_price AND reference_entry_price <= entry_price_high)), 
    CONSTRAINT fk_buy_point_decision_v1_signal FOREIGN KEY(signal_id) REFERENCES decision.fact_model_signal_v1 (signal_id)
);

CREATE INDEX idx_buy_point_decision_v1_signal ON decision.fact_buy_point_decision_v1 (signal_id, calculated_at);

CREATE INDEX idx_buy_point_decision_v1_due ON decision.fact_buy_point_decision_v1 (model_code, calc_stage, buy_point_status);

CREATE UNIQUE INDEX uq_buy_point_decision_v1_version ON decision.fact_buy_point_decision_v1 (signal_id, calc_stage, strategy_version, calculated_at);

CREATE TABLE decision.fact_signal_monitor_snapshot_v1 (
    snapshot_id BIGSERIAL NOT NULL, 
    signal_id BIGINT NOT NULL, 
    snapshot_time TIMESTAMP WITH TIME ZONE NOT NULL, 
    tick_timestamp TIMESTAMP WITH TIME ZONE, 
    calc_timestamp TIMESTAMP WITH TIME ZONE, 
    model_version_tag VARCHAR(96), 
    trade_date DATE NOT NULL, 
    freq_code VARCHAR(16) NOT NULL, 
    current_price NUMERIC(18, 8), 
    return_from_entry_pct NUMERIC(18, 10), 
    mfe_pct NUMERIC(18, 10), 
    mae_pct NUMERIC(18, 10), 
    vwap NUMERIC(18, 8), 
    volume NUMERIC(24, 8), 
    amount NUMERIC(24, 8), 
    buy_point_status VARCHAR(64), 
    verification_status VARCHAR(64), 
    directional_status VARCHAR(64), 
    entry_opportunity_status VARCHAR(64), 
    first_fillable_at TIMESTAMP WITH TIME ZONE, 
    first_fillable_price NUMERIC(18, 8), 
    execution_reference_price NUMERIC(18, 8), 
    execution_return_from_entry_pct NUMERIC(18, 10), 
    entry_opportunity_reason_codes JSONB DEFAULT '[]'::jsonb NOT NULL, 
    false_rebound_risk_score NUMERIC(18, 10), 
    distance_to_target_pct NUMERIC(18, 10), 
    distance_to_invalidation_pct NUMERIC(18, 10), 
    target_hit_flag BOOLEAN DEFAULT false NOT NULL, 
    invalidation_hit_flag BOOLEAN DEFAULT false NOT NULL, 
    sector_strength_score NUMERIC(18, 10), 
    market_breadth_score NUMERIC(18, 10), 
    moneyflow_strength_score NUMERIC(18, 10), 
    data_quality_status VARCHAR(64), 
    source_quality_json JSONB DEFAULT '{}'::jsonb NOT NULL, 
    fill_state_json JSONB DEFAULT '{}'::jsonb NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_fact_signal_monitor_snapshot_v1 PRIMARY KEY (snapshot_id), 
    CONSTRAINT fk_signal_monitor_snapshot_v1_signal FOREIGN KEY(signal_id) REFERENCES decision.fact_model_signal_v1 (signal_id)
);

CREATE UNIQUE INDEX uq_signal_monitor_snapshot_v1_time ON decision.fact_signal_monitor_snapshot_v1 (signal_id, snapshot_time, freq_code);

CREATE TABLE decision.fact_false_rebound_risk_v1 (
    risk_id BIGSERIAL NOT NULL, 
    signal_id BIGINT NOT NULL, 
    snapshot_time TIMESTAMP WITH TIME ZONE NOT NULL, 
    tick_timestamp TIMESTAMP WITH TIME ZONE, 
    calc_timestamp TIMESTAMP WITH TIME ZONE, 
    model_version_tag VARCHAR(96), 
    false_rebound_risk_score NUMERIC(18, 10) NOT NULL, 
    risk_level VARCHAR(32) NOT NULL, 
    risk_reason_codes JSONB DEFAULT '[]'::jsonb NOT NULL, 
    model_version VARCHAR(64) NOT NULL, 
    source_quality_json JSONB DEFAULT '{}'::jsonb NOT NULL, 
    fill_state_json JSONB DEFAULT '{}'::jsonb NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_fact_false_rebound_risk_v1 PRIMARY KEY (risk_id), 
    CONSTRAINT fk_false_rebound_risk_v1_signal FOREIGN KEY(signal_id) REFERENCES decision.fact_model_signal_v1 (signal_id)
);

CREATE UNIQUE INDEX uq_false_rebound_risk_v1_signal_time ON decision.fact_false_rebound_risk_v1 (signal_id, snapshot_time, model_version);

CREATE TABLE decision.fact_memory_false_reactivation_risk_v1 (
    risk_id BIGSERIAL NOT NULL, 
    signal_id BIGINT NOT NULL, 
    snapshot_time TIMESTAMP WITH TIME ZONE NOT NULL, 
    tick_timestamp TIMESTAMP WITH TIME ZONE, 
    calc_timestamp TIMESTAMP WITH TIME ZONE, 
    model_version_tag VARCHAR(96), 
    false_reactivation_risk_score NUMERIC(18, 10) NOT NULL, 
    risk_level VARCHAR(32) NOT NULL, 
    risk_reason_codes JSONB DEFAULT '[]'::jsonb NOT NULL, 
    model_version VARCHAR(64) NOT NULL, 
    source_quality_json JSONB DEFAULT '{}'::jsonb NOT NULL, 
    fill_state_json JSONB DEFAULT '{}'::jsonb NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_fact_memory_false_reactivation_risk_v1 PRIMARY KEY (risk_id), 
    CONSTRAINT fk_memory_false_reactivation_risk_v1_signal FOREIGN KEY(signal_id) REFERENCES decision.fact_model_signal_v1 (signal_id)
);

CREATE UNIQUE INDEX uq_memory_false_reactivation_v1_signal_time ON decision.fact_memory_false_reactivation_risk_v1 (signal_id, snapshot_time, model_version);

CREATE TABLE decision.fact_ambush_false_rebound_risk_v1 (
    risk_id BIGSERIAL NOT NULL, 
    signal_id BIGINT NOT NULL, 
    snapshot_time TIMESTAMP WITH TIME ZONE NOT NULL, 
    tick_timestamp TIMESTAMP WITH TIME ZONE, 
    calc_timestamp TIMESTAMP WITH TIME ZONE, 
    model_version_tag VARCHAR(96), 
    false_rebound_risk_score NUMERIC(18, 10) NOT NULL, 
    risk_level VARCHAR(32) NOT NULL, 
    risk_reason_codes JSONB DEFAULT '[]'::jsonb NOT NULL, 
    model_version VARCHAR(64) NOT NULL, 
    source_quality_json JSONB DEFAULT '{}'::jsonb NOT NULL, 
    fill_state_json JSONB DEFAULT '{}'::jsonb NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_fact_ambush_false_rebound_risk_v1 PRIMARY KEY (risk_id), 
    CONSTRAINT fk_ambush_false_rebound_risk_v1_signal FOREIGN KEY(signal_id) REFERENCES decision.fact_model_signal_v1 (signal_id)
);

CREATE UNIQUE INDEX uq_ambush_false_rebound_v1_signal_time ON decision.fact_ambush_false_rebound_risk_v1 (signal_id, snapshot_time, model_version);

CREATE TABLE decision.fact_signal_outcome_label_v1 (
    outcome_id BIGSERIAL NOT NULL, 
    signal_id BIGINT NOT NULL, 
    label_version VARCHAR(64) NOT NULL, 
    tick_timestamp TIMESTAMP WITH TIME ZONE, 
    calc_timestamp TIMESTAMP WITH TIME ZONE, 
    model_version_tag VARCHAR(96), 
    entry_price_basis VARCHAR(64) NOT NULL, 
    reference_entry_price NUMERIC(18, 8), 
    target_return_pct NUMERIC(18, 10) DEFAULT '8.0' NOT NULL, 
    target_price NUMERIC(18, 8), 
    invalidation_price NUMERIC(18, 8), 
    target_touch_flag BOOLEAN DEFAULT false NOT NULL, 
    first_target_touch_time TIMESTAMP WITH TIME ZONE, 
    invalidation_hit_flag BOOLEAN DEFAULT false NOT NULL, 
    first_invalidation_hit_time TIMESTAMP WITH TIME ZONE, 
    verification_status VARCHAR(64) NOT NULL, 
    actual_days_to_target INTEGER, 
    max_mfe_pct NUMERIC(18, 10), 
    max_mae_pct NUMERIC(18, 10), 
    failure_reason_codes JSONB DEFAULT '[]'::jsonb NOT NULL, 
    success_reason_codes JSONB DEFAULT '[]'::jsonb NOT NULL, 
    observation_end_date DATE, 
    source_quality_json JSONB DEFAULT '{}'::jsonb NOT NULL, 
    fill_state_json JSONB DEFAULT '{}'::jsonb NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_fact_signal_outcome_label_v1 PRIMARY KEY (outcome_id), 
    CONSTRAINT fk_signal_outcome_label_v1_signal FOREIGN KEY(signal_id) REFERENCES decision.fact_model_signal_v1 (signal_id)
);

CREATE UNIQUE INDEX uq_signal_outcome_label_v1_signal_version ON decision.fact_signal_outcome_label_v1 (signal_id, label_version);

CREATE TABLE decision.agg_signal_latest_state_v1 (
    signal_id BIGINT NOT NULL, 
    model_code VARCHAR(64) NOT NULL, 
    symbol VARCHAR(16) NOT NULL, 
    stock_name VARCHAR(64), 
    signal_date DATE NOT NULL, 
    tick_timestamp TIMESTAMP WITH TIME ZONE, 
    calc_timestamp TIMESTAMP WITH TIME ZONE, 
    model_version_tag VARCHAR(96), 
    selected_days INTEGER, 
    rank_no INTEGER, 
    model_score NUMERIC(18, 10), 
    model_state VARCHAR(64), 
    buy_point_status VARCHAR(64), 
    reference_entry_price NUMERIC(18, 8), 
    entry_price_low NUMERIC(18, 8), 
    entry_price_high NUMERIC(18, 8), 
    current_price NUMERIC(18, 8), 
    return_from_entry_pct NUMERIC(18, 10), 
    verification_status VARCHAR(64), 
    directional_status VARCHAR(64), 
    entry_opportunity_status VARCHAR(64), 
    first_fillable_at TIMESTAMP WITH TIME ZONE, 
    first_fillable_price NUMERIC(18, 8), 
    execution_reference_price NUMERIC(18, 8), 
    execution_return_from_entry_pct NUMERIC(18, 10), 
    entry_opportunity_reason_codes JSONB DEFAULT '[]'::jsonb NOT NULL, 
    actual_days_to_target INTEGER, 
    false_rebound_risk_score NUMERIC(18, 10), 
    false_rebound_risk_level VARCHAR(32), 
    data_collection_status VARCHAR(64), 
    latest_snapshot_time TIMESTAMP WITH TIME ZONE, 
    source_quality_json JSONB DEFAULT '{}'::jsonb NOT NULL, 
    fill_state_json JSONB DEFAULT '{}'::jsonb NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_agg_signal_latest_state_v1 PRIMARY KEY (signal_id), 
    CONSTRAINT fk_agg_signal_latest_state_v1_signal FOREIGN KEY(signal_id) REFERENCES decision.fact_model_signal_v1 (signal_id)
);

CREATE INDEX idx_latest_state_v1_model_date ON decision.agg_signal_latest_state_v1 (model_code, signal_date);

CREATE TABLE decision.hot_signal_ext (
    signal_id BIGINT NOT NULL, 
    candidate_batch_id BIGINT, 
    ths_rank_no INTEGER, 
    teacher_probability NUMERIC(18, 10), 
    teacher_probability_available_at TIMESTAMP WITH TIME ZONE, 
    teacher_probability_source VARCHAR(64), 
    teacher_probability_quality VARCHAR(16) DEFAULT 'missing' NOT NULL, 
    teacher_local_score_gap NUMERIC(18, 10), 
    auction_confirmation_strength NUMERIC(18, 10), 
    open_5m_vwap_strength NUMERIC(18, 10), 
    sector_heat_support NUMERIC(18, 10), 
    news_catalyst_support NUMERIC(18, 10), 
    limit_up_tradability_status VARCHAR(64), 
    teacher_overtrusted_flag BOOLEAN DEFAULT false NOT NULL, 
    teacher_underestimated_flag BOOLEAN DEFAULT false NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_hot_signal_ext PRIMARY KEY (signal_id), 
    CONSTRAINT ck_hot_signal_ext_teacher_probability_range CHECK (teacher_probability IS NULL OR (teacher_probability >= 0 AND teacher_probability <= 100)), 
    CONSTRAINT ck_hot_signal_ext_teacher_probability_quality_allowed CHECK (teacher_probability_quality IN ('valid','missing','invalid','late')), 
    CONSTRAINT ck_hot_signal_ext_missing_probability_marked CHECK (teacher_probability IS NOT NULL OR teacher_probability_quality = 'missing'), 
    CONSTRAINT fk_hot_signal_ext_signal FOREIGN KEY(signal_id) REFERENCES decision.model_signal_fact (signal_id)
);

CREATE INDEX idx_hot_signal_ext_batch_rank ON decision.hot_signal_ext (candidate_batch_id, ths_rank_no);

CREATE TABLE decision.memory_signal_ext (
    signal_id BIGINT NOT NULL, 
    memory_entity_id BIGINT NOT NULL, 
    first_signal_id BIGINT, 
    first_source_model VARCHAR(64), 
    first_selected_date DATE, 
    first_selected_at TIMESTAMP WITH TIME ZONE, 
    first_model_score NUMERIC(18, 10), 
    first_teacher_probability NUMERIC(18, 10), 
    reactivated_date DATE NOT NULL, 
    reactivated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    memory_age_trade_days INTEGER, 
    ttl_remaining_trade_days INTEGER, 
    decay_score NUMERIC(18, 10), 
    memory_state VARCHAR(64), 
    second_wave_trigger_code VARCHAR(64), 
    trigger_quality_level VARCHAR(32), 
    breakout_quality_score NUMERIC(18, 10), 
    pullback_health_score NUMERIC(18, 10), 
    moneyflow_reactivation_score NUMERIC(18, 10), 
    sector_resonance_return_score NUMERIC(18, 10), 
    fake_activation_risk_score NUMERIC(18, 10), 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_memory_signal_ext PRIMARY KEY (signal_id), 
    CONSTRAINT ck_memory_signal_ext_no_first_signal_reuse CHECK (first_signal_id IS NULL OR first_signal_id <> signal_id), 
    CONSTRAINT ck_memory_signal_ext_reactivation_after_first CHECK (first_selected_at IS NULL OR reactivated_at >= first_selected_at), 
    CONSTRAINT ck_memory_signal_ext_first_score_range CHECK (first_model_score IS NULL OR (first_model_score >= 0 AND first_model_score <= 100)), 
    CONSTRAINT ck_memory_signal_ext_first_teacher_probability_range CHECK (first_teacher_probability IS NULL OR (first_teacher_probability >= 0 AND first_teacher_probability <= 100)), 
    CONSTRAINT ck_memory_signal_ext_trigger_quality_allowed CHECK (trigger_quality_level IS NULL OR trigger_quality_level IN ('strong_trigger','medium_trigger','weak_trigger','suspected_fake_activation','data_insufficient')), 
    CONSTRAINT fk_memory_signal_ext_signal FOREIGN KEY(signal_id) REFERENCES decision.model_signal_fact (signal_id)
);

CREATE INDEX idx_memory_signal_ext_entity_day ON decision.memory_signal_ext (memory_entity_id, reactivated_date);

CREATE TABLE decision.ambush_signal_ext (
    signal_id BIGINT NOT NULL, 
    valley_watch_id BIGINT, 
    near_miss_id BIGINT, 
    effective_turn_anchor_day DATE, 
    primary_trough_date DATE, 
    turn_freshness_bucket VARCHAR(32), 
    anchor_age_trade_days INTEGER, 
    horizontal_breakout_recount_flag BOOLEAN DEFAULT false NOT NULL, 
    continuous_rebound_downgrade_flag BOOLEAN DEFAULT false NOT NULL, 
    ambush_release_gate_status VARCHAR(64), 
    false_rebound_risk_score NUMERIC(18, 10), 
    anchor_breakdown_risk_score NUMERIC(18, 10), 
    pullback_health_score NUMERIC(18, 10), 
    late_rebound_risk_score NUMERIC(18, 10), 
    missed_opportunity_flag BOOLEAN DEFAULT false NOT NULL, 
    near_miss_reason_codes JSONB DEFAULT '[]'::jsonb NOT NULL, 
    pool_transition_audit_id BIGINT, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_ambush_signal_ext PRIMARY KEY (signal_id), 
    CONSTRAINT ck_ambush_signal_ext_turn_freshness_bucket_allowed CHECK (turn_freshness_bucket IS NULL OR turn_freshness_bucket IN ('D1','D2','D3','D4_D5','D6_D8_CONTINUOUS','D6_D8_HORIZONTAL','D9_PLUS')), 
    CONSTRAINT ck_ambush_signal_ext_horizontal_recount_requires_audit CHECK (NOT horizontal_breakout_recount_flag OR pool_transition_audit_id IS NOT NULL), 
    CONSTRAINT fk_ambush_signal_ext_signal FOREIGN KEY(signal_id) REFERENCES decision.model_signal_fact (signal_id)
);

CREATE INDEX idx_ambush_signal_ext_anchor ON decision.ambush_signal_ext (effective_turn_anchor_day, turn_freshness_bucket);

CREATE TABLE decision.signal_buy_point (
    buy_point_id BIGSERIAL NOT NULL, 
    signal_id BIGINT NOT NULL, 
    model_code VARCHAR(64) NOT NULL, 
    adapter_code VARCHAR(64) NOT NULL, 
    buy_point_version VARCHAR(64) NOT NULL, 
    calc_stage VARCHAR(32) NOT NULL, 
    tick_timestamp TIMESTAMP WITH TIME ZONE, 
    calc_timestamp TIMESTAMP WITH TIME ZONE, 
    model_version_tag VARCHAR(96), 
    reference_entry_price NUMERIC(18, 8), 
    entry_price_low NUMERIC(18, 8), 
    entry_price_high NUMERIC(18, 8), 
    target_price NUMERIC(18, 8), 
    invalidation_price NUMERIC(18, 8), 
    risk_reward_ratio NUMERIC(18, 10), 
    buy_point_status VARCHAR(32) NOT NULL, 
    block_reason_codes JSONB DEFAULT '[]'::jsonb NOT NULL, 
    is_first_valid BOOLEAN DEFAULT false NOT NULL, 
    is_frozen_reference BOOLEAN DEFAULT false NOT NULL, 
    calculated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    data_as_of TIMESTAMP WITH TIME ZONE NOT NULL, 
    source_quality_json JSONB DEFAULT '{}'::jsonb NOT NULL, 
    fill_state_json JSONB DEFAULT '{}'::jsonb NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_signal_buy_point PRIMARY KEY (buy_point_id), 
    CONSTRAINT ck_signal_buy_point_adapter_code_allowed CHECK (adapter_code IN ('hot_candidates_buy_point_adapter','candidate_memory_buy_point_adapter','ambush_watchlist_buy_point_adapter')), 
    CONSTRAINT ck_signal_buy_point_calc_stage_allowed CHECK (calc_stage IN ('close_estimate','auction_confirmed','open_5m_vwap_adjusted','intraday_adjusted','shadow_research')), 
    CONSTRAINT ck_signal_buy_point_buy_point_status_allowed CHECK (buy_point_status IN ('valid','blocked','invalid','research_only')), 
    CONSTRAINT ck_signal_buy_point_positive_prices CHECK ((reference_entry_price IS NULL OR reference_entry_price > 0) AND (entry_price_low IS NULL OR entry_price_low > 0) AND (entry_price_high IS NULL OR entry_price_high > 0) AND (target_price IS NULL OR target_price > 0) AND (invalidation_price IS NULL OR invalidation_price > 0)), 
    CONSTRAINT ck_signal_buy_point_entry_range CHECK (reference_entry_price IS NULL OR entry_price_low IS NULL OR entry_price_high IS NULL OR (entry_price_low <= reference_entry_price AND reference_entry_price <= entry_price_high)), 
    CONSTRAINT ck_signal_buy_point_frozen_reference_valid CHECK (NOT is_frozen_reference OR (is_first_valid AND buy_point_status = 'valid' AND reference_entry_price > 0)), 
    CONSTRAINT ck_signal_buy_point_shadow_research_only CHECK (calc_stage <> 'shadow_research' OR (buy_point_status = 'research_only' AND NOT is_first_valid AND NOT is_frozen_reference)), 
    CONSTRAINT fk_signal_buy_point_signal FOREIGN KEY(signal_id) REFERENCES decision.model_signal_fact (signal_id)
);

CREATE UNIQUE INDEX uq_signal_buy_point_frozen_reference ON decision.signal_buy_point (signal_id) WHERE is_frozen_reference IS true;

CREATE INDEX idx_signal_buy_point_signal_time ON decision.signal_buy_point (signal_id, calculated_at);

CREATE INDEX idx_signal_buy_point_adapter_stage ON decision.signal_buy_point (adapter_code, calc_stage, buy_point_status);

CREATE TABLE decision.signal_monitoring_snapshot (
    snapshot_id BIGSERIAL NOT NULL, 
    signal_id BIGINT NOT NULL, 
    snapshot_time TIMESTAMP WITH TIME ZONE NOT NULL, 
    tick_timestamp TIMESTAMP WITH TIME ZONE, 
    calc_timestamp TIMESTAMP WITH TIME ZONE, 
    model_version_tag VARCHAR(96), 
    latest_price NUMERIC(18, 8), 
    return_from_reference_pct NUMERIC(18, 10), 
    mfe_pct NUMERIC(18, 10), 
    mae_pct NUMERIC(18, 10), 
    max_drawdown_pct NUMERIC(18, 10), 
    drawdown_from_peak_pct NUMERIC(18, 10), 
    entry_vwap_deviation_pct NUMERIC(18, 10), 
    atr_normalized_mae NUMERIC(18, 10), 
    vwap_position NUMERIC(18, 10), 
    volume_ratio NUMERIC(18, 10), 
    turnover_rate NUMERIC(18, 10), 
    moneyflow_state VARCHAR(64), 
    sector_state VARCHAR(64), 
    market_state VARCHAR(64), 
    news_state VARCHAR(64), 
    freshness_status VARCHAR(16) NOT NULL, 
    quality_status VARCHAR(16) NOT NULL, 
    sequence_no BIGINT NOT NULL, 
    idempotency_key VARCHAR(128) NOT NULL, 
    calculated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    data_as_of TIMESTAMP WITH TIME ZONE NOT NULL, 
    source_quality_json JSONB DEFAULT '{}'::jsonb NOT NULL, 
    fill_state_json JSONB DEFAULT '{}'::jsonb NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_signal_monitoring_snapshot PRIMARY KEY (snapshot_id), 
    CONSTRAINT ck_signal_monitoring_snapshot_sequence_positive CHECK (sequence_no > 0), 
    CONSTRAINT ck_signal_monitoring_snapshot_latest_price_positive CHECK (latest_price IS NULL OR latest_price > 0), 
    CONSTRAINT ck_signal_monitoring_snapshot_freshness_status_allowed CHECK (freshness_status IN ('fresh','delayed','stale','blocked')), 
    CONSTRAINT ck_signal_monitoring_snapshot_quality_status_allowed CHECK (quality_status IN ('usable','partial','blocked')), 
    CONSTRAINT fk_signal_monitoring_snapshot_signal FOREIGN KEY(signal_id) REFERENCES decision.model_signal_fact (signal_id)
);

CREATE UNIQUE INDEX uq_signal_monitoring_snapshot_time ON decision.signal_monitoring_snapshot (signal_id, snapshot_time);

CREATE UNIQUE INDEX uq_signal_monitoring_snapshot_sequence ON decision.signal_monitoring_snapshot (signal_id, sequence_no);

CREATE UNIQUE INDEX uq_signal_monitoring_snapshot_idempotency ON decision.signal_monitoring_snapshot (signal_id, idempotency_key);

CREATE TABLE decision.signal_outcome_label (
    outcome_label_id BIGSERIAL NOT NULL, 
    signal_id BIGINT NOT NULL, 
    label_version VARCHAR(64) NOT NULL, 
    validation_status VARCHAR(32) NOT NULL, 
    stage_t5_status VARCHAR(32), 
    stage_t20_status VARCHAR(32), 
    first_target_hit_at TIMESTAMP WITH TIME ZONE, 
    first_target_hit_trade_day DATE, 
    first_invalidation_hit_at TIMESTAMP WITH TIME ZONE, 
    first_invalidation_trade_day DATE, 
    actual_trade_days_to_target INTEGER, 
    actual_trade_days_to_invalidation INTEGER, 
    tick_timestamp TIMESTAMP WITH TIME ZONE, 
    calc_timestamp TIMESTAMP WITH TIME ZONE, 
    model_version_tag VARCHAR(96), 
    max_return_pct NUMERIC(18, 10), 
    max_drawdown_pct NUMERIC(18, 10), 
    mfe_pct NUMERIC(18, 10), 
    mae_pct NUMERIC(18, 10), 
    relative_market_return_pct NUMERIC(18, 10), 
    relative_sector_return_pct NUMERIC(18, 10), 
    failure_primary_reason VARCHAR(128), 
    failure_secondary_reason_codes JSONB DEFAULT '[]'::jsonb NOT NULL, 
    correction_tags JSONB DEFAULT '[]'::jsonb NOT NULL, 
    label_maturity_status VARCHAR(32) NOT NULL, 
    calculated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    source_quality_json JSONB DEFAULT '{}'::jsonb NOT NULL, 
    fill_state_json JSONB DEFAULT '{}'::jsonb NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_signal_outcome_label PRIMARY KEY (outcome_label_id), 
    CONSTRAINT ck_signal_outcome_label_validation_status_allowed CHECK (validation_status IN ('pending','success_within_5d','failed_after_5d','extended_tracking','delayed_success','delayed_success_after_5d','still_failed','structure_invalidated','invalid_untradable','invalid_data_gap','buy_point_blocked','missed_opportunity','data_insufficient')), 
    CONSTRAINT ck_signal_outcome_label_label_maturity_allowed CHECK (label_maturity_status IN ('immature','mature','blocked_by_data')), 
    CONSTRAINT ck_signal_outcome_label_target_days_nonnegative CHECK (actual_trade_days_to_target IS NULL OR actual_trade_days_to_target >= 0), 
    CONSTRAINT ck_signal_outcome_label_invalidation_days_nonnegative CHECK (actual_trade_days_to_invalidation IS NULL OR actual_trade_days_to_invalidation >= 0), 
    CONSTRAINT fk_signal_outcome_label_signal FOREIGN KEY(signal_id) REFERENCES decision.model_signal_fact (signal_id)
);

CREATE UNIQUE INDEX uq_signal_outcome_label_signal_version ON decision.signal_outcome_label (signal_id, label_version);

CREATE INDEX idx_signal_outcome_label_status ON decision.signal_outcome_label (validation_status, label_maturity_status);

CREATE TABLE decision.fact_data_inspection_finding_v1 (
    finding_id BIGSERIAL NOT NULL, 
    inspection_run_id BIGINT, 
    scope VARCHAR(128) NOT NULL, 
    model_code VARCHAR(64), 
    signal_id BIGINT, 
    symbol VARCHAR(16), 
    severity VARCHAR(16) NOT NULL, 
    finding_code VARCHAR(128) NOT NULL, 
    finding_title VARCHAR(256), 
    finding_detail JSONB DEFAULT '{}'::jsonb NOT NULL, 
    impact_area VARCHAR(128), 
    release_blocking_flag BOOLEAN DEFAULT false NOT NULL, 
    suggested_action VARCHAR(512), 
    first_seen_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    latest_seen_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    resolved_at TIMESTAMP WITH TIME ZONE, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_fact_data_inspection_finding_v1 PRIMARY KEY (finding_id), 
    CONSTRAINT fk_data_finding_v1_run FOREIGN KEY(inspection_run_id) REFERENCES decision.fact_data_inspection_run_v1 (inspection_run_id)
);

CREATE INDEX idx_data_finding_v1_signal ON decision.fact_data_inspection_finding_v1 (signal_id, severity, latest_seen_at);

CREATE INDEX idx_data_finding_v1_scope ON decision.fact_data_inspection_finding_v1 (scope, severity, latest_seen_at);

CREATE TABLE decision.dim_methodology_model_mapping (
    mapping_id BIGSERIAL NOT NULL, 
    methodology_code TEXT NOT NULL, 
    model_code TEXT NOT NULL, 
    signal_type_code TEXT, 
    methodology_role TEXT NOT NULL, 
    mapping_reason TEXT NOT NULL, 
    status TEXT DEFAULT 'active' NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_dim_methodology_model_mapping PRIMARY KEY (mapping_id), 
    CONSTRAINT uq_methodology_model_mapping UNIQUE (methodology_code, model_code, signal_type_code, methodology_role), 
    CONSTRAINT ck_dim_methodology_model_mapping_role_allowed CHECK (methodology_role IN ('primary','support','filter','risk','learning')), 
    CONSTRAINT fk_methodology_model_mapping_methodology FOREIGN KEY(methodology_code) REFERENCES decision.dim_research_methodology (methodology_code), 
    CONSTRAINT fk_methodology_model_mapping_model FOREIGN KEY(model_code) REFERENCES decision.dim_model (model_code)
);

CREATE INDEX idx_methodology_model_mapping_model ON decision.dim_methodology_model_mapping (model_code, signal_type_code);

CREATE TABLE decision.dim_methodology_buy_point_mapping (
    mapping_id BIGSERIAL NOT NULL, 
    methodology_code TEXT NOT NULL, 
    buy_point_type TEXT NOT NULL, 
    source_model TEXT, 
    methodology_role TEXT NOT NULL, 
    mapping_reason TEXT NOT NULL, 
    status TEXT DEFAULT 'active' NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_dim_methodology_buy_point_mapping PRIMARY KEY (mapping_id), 
    CONSTRAINT uq_methodology_buy_point_mapping UNIQUE (methodology_code, buy_point_type, source_model, methodology_role), 
    CONSTRAINT ck_dim_methodology_buy_point_mapping_role_allowed CHECK (methodology_role IN ('primary','support','filter','risk','learning')), 
    CONSTRAINT fk_methodology_buy_mapping_methodology FOREIGN KEY(methodology_code) REFERENCES decision.dim_research_methodology (methodology_code)
);

CREATE INDEX idx_methodology_buy_mapping_type ON decision.dim_methodology_buy_point_mapping (buy_point_type, source_model);

CREATE TABLE decision.dim_methodology_feature_requirement (
    requirement_id BIGSERIAL NOT NULL, 
    methodology_code TEXT NOT NULL, 
    feature_code TEXT NOT NULL, 
    feature_name TEXT NOT NULL, 
    feature_domain TEXT NOT NULL, 
    requirement_level TEXT NOT NULL, 
    lookback_window TEXT, 
    source_table TEXT, 
    source_field TEXT, 
    missing_policy TEXT DEFAULT 'block_ready' NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_dim_methodology_feature_requirement PRIMARY KEY (requirement_id), 
    CONSTRAINT uq_methodology_feature_requirement UNIQUE (methodology_code, feature_code), 
    CONSTRAINT ck_dim_methodology_feature_requirement_req_level CHECK (requirement_level IN ('required','recommended','optional')), 
    CONSTRAINT ck_dim_methodology_feature_requirement_missing_policy CHECK (missing_policy IN ('block_ready','degrade','observe_only')), 
    CONSTRAINT fk_methodology_feature_req_methodology FOREIGN KEY(methodology_code) REFERENCES decision.dim_research_methodology (methodology_code)
);

CREATE INDEX idx_methodology_feature_req_domain ON decision.dim_methodology_feature_requirement (feature_domain, requirement_level);

CREATE TABLE decision.dim_methodology_label_requirement (
    requirement_id BIGSERIAL NOT NULL, 
    methodology_code TEXT NOT NULL, 
    label_code TEXT NOT NULL, 
    label_name TEXT NOT NULL, 
    label_horizon TEXT NOT NULL, 
    label_basis TEXT NOT NULL, 
    requirement_level TEXT NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_dim_methodology_label_requirement PRIMARY KEY (requirement_id), 
    CONSTRAINT uq_methodology_label_requirement UNIQUE (methodology_code, label_code), 
    CONSTRAINT ck_dim_methodology_label_requirement_req_level CHECK (requirement_level IN ('required','recommended','optional')), 
    CONSTRAINT fk_methodology_label_req_methodology FOREIGN KEY(methodology_code) REFERENCES decision.dim_research_methodology (methodology_code)
);

CREATE TABLE decision.methodology_feature_coverage_report_v1 (
    report_id BIGSERIAL NOT NULL, 
    methodology_code TEXT NOT NULL, 
    model_code TEXT NOT NULL, 
    buy_point_type TEXT, 
    report_date DATE NOT NULL, 
    required_feature_count INTEGER NOT NULL, 
    available_feature_count INTEGER NOT NULL, 
    missing_required_features TEXT[] NOT NULL, 
    coverage_ratio NUMERIC NOT NULL, 
    official_research_ready BOOLEAN DEFAULT false NOT NULL, 
    sample_count INTEGER DEFAULT '0' NOT NULL, 
    coverage_status TEXT NOT NULL, 
    detail_json JSONB NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_methodology_feature_coverage_report_v1 PRIMARY KEY (report_id), 
    CONSTRAINT uq_methodology_feature_coverage UNIQUE (methodology_code, model_code, buy_point_type, report_date), 
    CONSTRAINT ck_methodology_feature_coverage_report_v1_ready_no_missing CHECK (NOT official_research_ready OR cardinality(missing_required_features) = 0), 
    CONSTRAINT fk_methodology_feature_coverage_methodology FOREIGN KEY(methodology_code) REFERENCES decision.dim_research_methodology (methodology_code)
);

CREATE INDEX idx_methodology_feature_coverage_date ON decision.methodology_feature_coverage_report_v1 (report_date, coverage_status);

CREATE TABLE decision.methodology_effectiveness_report_v1 (
    report_id BIGSERIAL NOT NULL, 
    methodology_code TEXT NOT NULL, 
    model_code TEXT NOT NULL, 
    source_signal_type TEXT, 
    buy_point_type TEXT, 
    report_date DATE NOT NULL, 
    dataset_version TEXT NOT NULL, 
    evaluated_sample_count INTEGER NOT NULL, 
    pending_sample_count INTEGER NOT NULL, 
    hit_count INTEGER NOT NULL, 
    miss_count INTEGER NOT NULL, 
    hit_rate NUMERIC, 
    avg_realized_return_pct NUMERIC, 
    sample_status TEXT NOT NULL, 
    effectiveness_status TEXT NOT NULL, 
    evidence_json JSONB NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_methodology_effectiveness_report_v1 PRIMARY KEY (report_id), 
    CONSTRAINT uq_methodology_effectiveness UNIQUE (methodology_code, model_code, source_signal_type, buy_point_type, report_date), 
    CONSTRAINT ck_methodology_effectiveness_report_v1_sample_status CHECK (sample_status IN ('sufficient','insufficient','pending')), 
    CONSTRAINT ck_methodology_effectiveness_report_v1_effect_status CHECK (effectiveness_status IN ('validated','insufficient_samples','watching','invalidated')), 
    CONSTRAINT ck_methodology_effectiveness_report_v1_no_fake_rate CHECK (evaluated_sample_count > 0 OR hit_rate IS NULL), 
    CONSTRAINT fk_methodology_effectiveness_methodology FOREIGN KEY(methodology_code) REFERENCES decision.dim_research_methodology (methodology_code)
);

CREATE INDEX idx_methodology_effectiveness_date ON decision.methodology_effectiveness_report_v1 (report_date, sample_status);

CREATE TABLE decision.dim_methodology_explain_template (
    template_id BIGSERIAL NOT NULL, 
    methodology_code TEXT NOT NULL, 
    scenario_code TEXT NOT NULL, 
    template_version TEXT NOT NULL, 
    required_context_keys TEXT[] NOT NULL, 
    prompt_template TEXT NOT NULL, 
    forbidden_claims TEXT[] NOT NULL, 
    status TEXT DEFAULT 'active' NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_dim_methodology_explain_template PRIMARY KEY (template_id), 
    CONSTRAINT uq_methodology_explain_template UNIQUE (methodology_code, scenario_code), 
    CONSTRAINT fk_methodology_explain_template_methodology FOREIGN KEY(methodology_code) REFERENCES decision.dim_research_methodology (methodology_code)
);

CREATE TABLE explain.explanation_output (
    output_id BIGSERIAL NOT NULL, 
    request_id BIGINT NOT NULL, 
    target_id VARCHAR(64), 
    explanation_kind VARCHAR(32), 
    explanation_mode VARCHAR(32), 
    audit_status VARCHAR(32), 
    audit_mode VARCHAR(32), 
    evidence_hash VARCHAR(128), 
    summary TEXT, 
    conclusion TEXT, 
    missing_evidence_json JSONB, 
    risks_json JSONB, 
    evaluation_scope_json JSONB, 
    explanation_task_json JSONB, 
    response_json JSONB NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_explanation_output PRIMARY KEY (output_id), 
    CONSTRAINT fk_explanation_output_request_id_explanation_request FOREIGN KEY(request_id) REFERENCES explain.explanation_request (request_id) ON DELETE CASCADE
);

CREATE INDEX idx_explanation_output_audit_status ON explain.explanation_output (audit_status, created_at);

CREATE UNIQUE INDEX uq_explanation_output_request ON explain.explanation_output (request_id);

CREATE TABLE explain.explanation_cache (
    cache_id BIGSERIAL NOT NULL, 
    target_type VARCHAR(32) NOT NULL, 
    target_id VARCHAR(64), 
    version_id BIGINT, 
    item_id BIGINT, 
    instrument_id BIGINT, 
    symbol_snapshot VARCHAR(32) NOT NULL, 
    business_line VARCHAR(32) NOT NULL, 
    explanation_version VARCHAR(64) NOT NULL, 
    numeric_fingerprint VARCHAR(128) NOT NULL, 
    tag_json JSONB NOT NULL, 
    short_text TEXT NOT NULL, 
    generated_by VARCHAR(32) DEFAULT 'jarvis' NOT NULL, 
    generation_status VARCHAR(24) DEFAULT 'generated' NOT NULL, 
    source_request_id BIGINT, 
    generated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_explanation_cache PRIMARY KEY (cache_id), 
    CONSTRAINT fk_explanation_cache_source_request_id_explanation_request FOREIGN KEY(source_request_id) REFERENCES explain.explanation_request (request_id)
);

CREATE INDEX idx_explanation_cache_symbol ON explain.explanation_cache (symbol_snapshot, business_line, generated_at);

CREATE INDEX idx_explanation_cache_target ON explain.explanation_cache (target_type, target_id, generated_at);

CREATE UNIQUE INDEX uq_explanation_cache_fingerprint ON explain.explanation_cache (business_line, symbol_snapshot, numeric_fingerprint);

CREATE TABLE market.candidate_pool_item (
    item_id BIGSERIAL NOT NULL, 
    snapshot_id BIGINT NOT NULL, 
    instrument_id BIGINT NOT NULL, 
    name_at_snapshot VARCHAR(64), 
    p_limit_up NUMERIC(12, 6), 
    p_limit_up_source VARCHAR(64), 
    p_limit_up_model_version VARCHAR(64), 
    limit_up_stage INTEGER, 
    latest_price NUMERIC(18, 4), 
    change_rate NUMERIC(12, 6), 
    turnover_rate NUMERIC(12, 6), 
    limit_up_type VARCHAR(32), 
    limit_up_reason VARCHAR(256), 
    first_limit_up_at TIMESTAMP WITH TIME ZONE, 
    last_limit_up_at TIMESTAMP WITH TIME ZONE, 
    limit_up_open_count INTEGER, 
    order_volume NUMERIC(20, 2), 
    order_amount NUMERIC(20, 2), 
    float_market_value NUMERIC(20, 2), 
    total_market_value NUMERIC(20, 2), 
    is_again_limit BOOLEAN, 
    is_new BOOLEAN, 
    high_days_text VARCHAR(32), 
    high_days_value INTEGER, 
    change_tag VARCHAR(32), 
    rank_no INTEGER, 
    raw_payload_id BIGINT, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_candidate_pool_item PRIMARY KEY (item_id), 
    CONSTRAINT fk_candidate_pool_item_snapshot_id_candidate_pool_snapshot FOREIGN KEY(snapshot_id) REFERENCES market.candidate_pool_snapshot (snapshot_id), 
    CONSTRAINT fk_candidate_pool_item_instrument_id_instrument_master FOREIGN KEY(instrument_id) REFERENCES core.instrument_master (instrument_id)
);

CREATE INDEX idx_candidate_item_rank ON market.candidate_pool_item (snapshot_id, rank_no);

CREATE INDEX idx_candidate_item_high_days ON market.candidate_pool_item (high_days_value);

CREATE INDEX idx_candidate_item_stage_probability ON market.candidate_pool_item (snapshot_id, limit_up_stage, p_limit_up);

CREATE UNIQUE INDEX uq_candidate_item_snapshot_instrument ON market.candidate_pool_item (snapshot_id, instrument_id);

CREATE INDEX idx_candidate_item_instrument ON market.candidate_pool_item (instrument_id, created_at);

CREATE TABLE market.candidate_membership_history (
    history_id BIGSERIAL NOT NULL, 
    instrument_id BIGINT NOT NULL, 
    trading_day DATE NOT NULL, 
    snapshot_id BIGINT, 
    candidate_flag BOOLEAN DEFAULT true NOT NULL, 
    candidate_rank INTEGER, 
    source VARCHAR(32) DEFAULT 'limitup_pool' NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_candidate_membership_history PRIMARY KEY (history_id), 
    CONSTRAINT fk_candidate_membership_history_instrument_id_instrument_master FOREIGN KEY(instrument_id) REFERENCES core.instrument_master (instrument_id), 
    CONSTRAINT fk_cand_mhist_snapshot_cand_snapshot FOREIGN KEY(snapshot_id) REFERENCES market.candidate_pool_snapshot (snapshot_id)
);

CREATE UNIQUE INDEX uq_candidate_membership_day ON market.candidate_membership_history (instrument_id, trading_day, source);

CREATE INDEX idx_candidate_membership_trading_day ON market.candidate_membership_history (trading_day);

CREATE TABLE market.candidate_batch (
    batch_id BIGSERIAL NOT NULL, 
    business_date DATE NOT NULL, 
    trade_date DATE NOT NULL, 
    source_model VARCHAR(64) DEFAULT 'external_ths_model' NOT NULL, 
    ingest_mode VARCHAR(32) DEFAULT 'external_ths_model' NOT NULL, 
    batch_status market.candidate_batch_status_enum DEFAULT 'draft_created'::market.candidate_batch_status_enum NOT NULL, 
    replacement_of_batch_id BIGINT, 
    superseded_by_batch_id BIGINT, 
    is_active BOOLEAN DEFAULT true NOT NULL, 
    submitted_at_utc TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    contract_audit_status VARCHAR(16) DEFAULT 'pending' NOT NULL, 
    contract_gap_codes TEXT[], 
    snapshot_id BIGINT NOT NULL, 
    provider core.provider_enum NOT NULL, 
    trading_day DATE NOT NULL, 
    batch_name VARCHAR(128), 
    notes TEXT, 
    created_by VARCHAR(32) DEFAULT 'system' NOT NULL, 
    production_submitted_at_utc TIMESTAMP WITH TIME ZONE, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_candidate_batch PRIMARY KEY (batch_id), 
    CONSTRAINT fk_candidate_batch_replacement_of_batch_id_candidate_batch FOREIGN KEY(replacement_of_batch_id) REFERENCES market.candidate_batch (batch_id), 
    CONSTRAINT fk_candidate_batch_superseded_by_batch_id_candidate_batch FOREIGN KEY(superseded_by_batch_id) REFERENCES market.candidate_batch (batch_id), 
    CONSTRAINT fk_cand_batch_snapshot_cand_snapshot FOREIGN KEY(snapshot_id) REFERENCES market.candidate_pool_snapshot (snapshot_id)
);

CREATE UNIQUE INDEX uq_candidate_batch_active_production ON market.candidate_batch (business_date, source_model, provider, ingest_mode) WHERE is_active = true AND ingest_mode = 'external_ths_model' AND batch_status IN ('production_submitted', 'evidence_collecting', 'preopen_ready', 'open_observing', 'outcome_pending', 'evaluated');

CREATE INDEX idx_candidate_batch_day_status ON market.candidate_batch (trading_day, batch_status, created_at);

CREATE INDEX idx_candidate_batch_contract_day_status ON market.candidate_batch (business_date, source_model, ingest_mode, batch_status);

CREATE INDEX idx_candidate_batch_snapshot ON market.candidate_batch (snapshot_id, created_at);

CREATE TABLE market.quote_snapshot (
    quote_id BIGSERIAL NOT NULL, 
    instrument_id BIGINT NOT NULL, 
    captured_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    trading_day DATE NOT NULL, 
    last_price NUMERIC(18, 4), 
    change_pct NUMERIC(12, 6), 
    change_amount NUMERIC(18, 4), 
    open_price NUMERIC(18, 4), 
    high_price NUMERIC(18, 4), 
    low_price NUMERIC(18, 4), 
    prev_close_price NUMERIC(18, 4), 
    volume NUMERIC(20, 2), 
    amount NUMERIC(20, 2), 
    turnover_rate NUMERIC(12, 6), 
    provider core.provider_enum NOT NULL, 
    raw_payload_id BIGINT, 
    is_partial BOOLEAN DEFAULT false NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_quote_snapshot PRIMARY KEY (quote_id), 
    CONSTRAINT fk_quote_snapshot_instrument_id_instrument_master FOREIGN KEY(instrument_id) REFERENCES core.instrument_master (instrument_id)
);

CREATE INDEX idx_quote_snapshot_day ON market.quote_snapshot (trading_day, captured_at);

CREATE UNIQUE INDEX uq_quote_snapshot_point ON market.quote_snapshot (instrument_id, provider, captured_at);

CREATE TABLE market.auction_snapshot (
    auction_id BIGSERIAL NOT NULL, 
    instrument_id BIGINT NOT NULL, 
    trading_day DATE NOT NULL, 
    captured_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    provider_quote_time TIMESTAMP WITH TIME ZONE, 
    auction_phase market.trade_status_enum NOT NULL, 
    virtual_open_price NUMERIC(18, 4), 
    matched_volume NUMERIC(20, 2), 
    matched_amount NUMERIC(20, 2), 
    unmatched_buy_volume NUMERIC(20, 2), 
    unmatched_sell_volume NUMERIC(20, 2), 
    imbalance_ratio NUMERIC(12, 6), 
    best_bid_price NUMERIC(18, 4), 
    best_ask_price NUMERIC(18, 4), 
    best_bid_volume NUMERIC(20, 2), 
    best_ask_volume NUMERIC(20, 2), 
    provider core.provider_enum NOT NULL, 
    raw_payload_id BIGINT, 
    is_final BOOLEAN DEFAULT false NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_auction_snapshot PRIMARY KEY (auction_id), 
    CONSTRAINT fk_auction_snapshot_instrument_id_instrument_master FOREIGN KEY(instrument_id) REFERENCES core.instrument_master (instrument_id)
);

CREATE UNIQUE INDEX uq_auction_snapshot_point ON market.auction_snapshot (instrument_id, provider, captured_at, auction_phase);

CREATE INDEX idx_auction_snapshot_day ON market.auction_snapshot (trading_day, captured_at);

CREATE INDEX idx_auction_snapshot_instrument_day ON market.auction_snapshot (instrument_id, trading_day, captured_at);

CREATE TABLE market.minute_bar (
    bar_id BIGSERIAL NOT NULL, 
    instrument_id BIGINT NOT NULL, 
    bar_ts TIMESTAMP WITH TIME ZONE NOT NULL, 
    trading_day DATE NOT NULL, 
    open_price NUMERIC(18, 4) NOT NULL, 
    high_price NUMERIC(18, 4) NOT NULL, 
    low_price NUMERIC(18, 4) NOT NULL, 
    close_price NUMERIC(18, 4) NOT NULL, 
    volume NUMERIC(20, 2), 
    amount NUMERIC(20, 2), 
    avg_price NUMERIC(18, 4), 
    provider core.provider_enum NOT NULL, 
    raw_payload_id BIGINT, 
    is_partial BOOLEAN DEFAULT false NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_minute_bar PRIMARY KEY (bar_id), 
    CONSTRAINT fk_minute_bar_instrument_id_instrument_master FOREIGN KEY(instrument_id) REFERENCES core.instrument_master (instrument_id)
);

CREATE INDEX idx_minute_bar_day ON market.minute_bar (trading_day, instrument_id, bar_ts);

CREATE UNIQUE INDEX uq_minute_bar_point ON market.minute_bar (instrument_id, provider, bar_ts);

CREATE TABLE market.daily_bar (
    bar_id BIGSERIAL NOT NULL, 
    instrument_id BIGINT NOT NULL, 
    trading_day DATE NOT NULL, 
    adjustment VARCHAR(8) DEFAULT 'qfq' NOT NULL, 
    open_price NUMERIC(18, 4) NOT NULL, 
    high_price NUMERIC(18, 4) NOT NULL, 
    low_price NUMERIC(18, 4) NOT NULL, 
    close_price NUMERIC(18, 4) NOT NULL, 
    volume NUMERIC(20, 2), 
    amount NUMERIC(20, 2), 
    change_pct NUMERIC(12, 6), 
    change_amount NUMERIC(18, 4), 
    turnover_rate NUMERIC(12, 6), 
    provider core.provider_enum NOT NULL, 
    raw_payload_id BIGINT, 
    is_partial BOOLEAN DEFAULT false NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_daily_bar PRIMARY KEY (bar_id), 
    CONSTRAINT fk_daily_bar_instrument_id_instrument_master FOREIGN KEY(instrument_id) REFERENCES core.instrument_master (instrument_id)
);

CREATE UNIQUE INDEX uq_daily_bar_point ON market.daily_bar (instrument_id, provider, trading_day, adjustment);

CREATE INDEX idx_daily_bar_day ON market.daily_bar (trading_day, instrument_id);

CREATE INDEX idx_daily_bar_provider_adjustment_day ON market.daily_bar (provider, adjustment, trading_day);

CREATE TABLE market.theme_membership (
    membership_id BIGSERIAL NOT NULL, 
    theme_id BIGINT NOT NULL, 
    instrument_id BIGINT NOT NULL, 
    provider core.provider_enum NOT NULL, 
    effective_from TIMESTAMP WITH TIME ZONE NOT NULL, 
    effective_to TIMESTAMP WITH TIME ZONE, 
    is_leader BOOLEAN, 
    weight_hint NUMERIC(12, 6), 
    raw_payload_id BIGINT, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_theme_membership PRIMARY KEY (membership_id), 
    CONSTRAINT fk_theme_membership_theme_id_theme_board FOREIGN KEY(theme_id) REFERENCES market.theme_board (theme_id), 
    CONSTRAINT fk_theme_membership_instrument_id_instrument_master FOREIGN KEY(instrument_id) REFERENCES core.instrument_master (instrument_id)
);

CREATE INDEX idx_theme_membership_instrument ON market.theme_membership (instrument_id, effective_to);

CREATE UNIQUE INDEX uq_theme_membership_period ON market.theme_membership (theme_id, instrument_id, effective_from);

CREATE TABLE market.moneyflow_stock_series (
    series_id BIGSERIAL NOT NULL, 
    instrument_id BIGINT NOT NULL, 
    trading_day DATE NOT NULL, 
    interval_type VARCHAR(8) NOT NULL, 
    main_net_inflow NUMERIC(20, 2), 
    super_large_net_inflow NUMERIC(20, 2), 
    large_net_inflow NUMERIC(20, 2), 
    medium_net_inflow NUMERIC(20, 2), 
    small_net_inflow NUMERIC(20, 2), 
    captured_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    provider core.provider_enum NOT NULL, 
    raw_payload_id BIGINT, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_moneyflow_stock_series PRIMARY KEY (series_id), 
    CONSTRAINT fk_moneyflow_stock_series_instrument_id_instrument_master FOREIGN KEY(instrument_id) REFERENCES core.instrument_master (instrument_id)
);

CREATE INDEX idx_moneyflow_stock_series_day ON market.moneyflow_stock_series (trading_day, captured_at);

CREATE UNIQUE INDEX uq_moneyflow_stock_series ON market.moneyflow_stock_series (instrument_id, provider, trading_day, interval_type);

CREATE TABLE market.moneyflow_stock_rank (
    rank_id BIGSERIAL NOT NULL, 
    trading_day DATE NOT NULL, 
    captured_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    instrument_id BIGINT NOT NULL, 
    rank_scope VARCHAR(16) DEFAULT 'all_market' NOT NULL, 
    rank_no INTEGER, 
    main_net_inflow NUMERIC(20, 2), 
    main_net_inflow_ratio NUMERIC(12, 6), 
    super_large_net_inflow NUMERIC(20, 2), 
    super_large_net_inflow_ratio NUMERIC(12, 6), 
    large_net_inflow NUMERIC(20, 2), 
    large_net_inflow_ratio NUMERIC(12, 6), 
    medium_net_inflow NUMERIC(20, 2), 
    medium_net_inflow_ratio NUMERIC(12, 6), 
    small_net_inflow NUMERIC(20, 2), 
    small_net_inflow_ratio NUMERIC(12, 6), 
    provider core.provider_enum NOT NULL, 
    raw_payload_id BIGINT, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_moneyflow_stock_rank PRIMARY KEY (rank_id), 
    CONSTRAINT fk_moneyflow_stock_rank_instrument_id_instrument_master FOREIGN KEY(instrument_id) REFERENCES core.instrument_master (instrument_id)
);

CREATE INDEX idx_moneyflow_stock_rank_day ON market.moneyflow_stock_rank (trading_day, rank_scope, rank_no);

CREATE UNIQUE INDEX uq_moneyflow_stock_rank ON market.moneyflow_stock_rank (provider, captured_at, rank_scope, instrument_id);

CREATE TABLE market.moneyflow_board_rank (
    rank_id BIGSERIAL NOT NULL, 
    theme_id BIGINT NOT NULL, 
    trading_day DATE NOT NULL, 
    captured_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    rank_no INTEGER, 
    main_net_inflow NUMERIC(20, 2), 
    change_pct NUMERIC(12, 6), 
    rise_count INTEGER, 
    fall_count INTEGER, 
    leader_name VARCHAR(64), 
    leader_change_pct NUMERIC(12, 6), 
    provider core.provider_enum NOT NULL, 
    raw_payload_id BIGINT, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_moneyflow_board_rank PRIMARY KEY (rank_id), 
    CONSTRAINT fk_moneyflow_board_rank_theme_id_theme_board FOREIGN KEY(theme_id) REFERENCES market.theme_board (theme_id)
);

CREATE UNIQUE INDEX uq_moneyflow_board_rank ON market.moneyflow_board_rank (provider, captured_at, theme_id);

CREATE INDEX idx_moneyflow_board_rank_day ON market.moneyflow_board_rank (trading_day, rank_no);

CREATE TABLE market.billboard_trade (
    trade_id BIGSERIAL NOT NULL, 
    instrument_id BIGINT NOT NULL, 
    provider core.provider_enum NOT NULL, 
    provider_trade_id VARCHAR(64), 
    trading_day DATE NOT NULL, 
    captured_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    security_code VARCHAR(16), 
    security_name VARCHAR(64), 
    market VARCHAR(16), 
    trade_market VARCHAR(64), 
    explain TEXT, 
    explanation TEXT, 
    close_price NUMERIC(18, 4), 
    change_rate NUMERIC(12, 6), 
    turnover_rate NUMERIC(12, 6), 
    buy_amount NUMERIC(20, 2), 
    sell_amount NUMERIC(20, 2), 
    net_amount NUMERIC(20, 2), 
    accum_amount NUMERIC(20, 2), 
    net_ratio NUMERIC(12, 6), 
    buy_times INTEGER, 
    sell_times INTEGER, 
    buy_count INTEGER, 
    sell_count INTEGER, 
    raw_payload_id BIGINT, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_billboard_trade PRIMARY KEY (trade_id), 
    CONSTRAINT fk_billboard_trade_instrument_id_instrument_master FOREIGN KEY(instrument_id) REFERENCES core.instrument_master (instrument_id)
);

CREATE UNIQUE INDEX uq_billboard_trade_provider_trade_id ON market.billboard_trade (provider, trading_day, provider_trade_id);

CREATE INDEX idx_billboard_trade_point ON market.billboard_trade (instrument_id, provider, trading_day, captured_at);

CREATE INDEX idx_billboard_trade_day ON market.billboard_trade (trading_day, net_amount);

CREATE INDEX idx_billboard_trade_instrument_day ON market.billboard_trade (instrument_id, trading_day);

CREATE TABLE market.cross_market_snapshot (
    snapshot_id BIGSERIAL NOT NULL, 
    asset_id BIGINT NOT NULL, 
    provider core.provider_enum NOT NULL, 
    trading_day DATE NOT NULL, 
    captured_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    quote_currency VARCHAR(16), 
    last_price NUMERIC(24, 8), 
    change_pct_24h NUMERIC(12, 6), 
    session_change_pct NUMERIC(12, 6), 
    market_cap NUMERIC(24, 2), 
    volume_24h NUMERIC(24, 2), 
    dominance_pct NUMERIC(12, 6), 
    open_interest NUMERIC(24, 2), 
    extra_metrics_json JSONB, 
    raw_payload_id BIGINT, 
    is_partial BOOLEAN DEFAULT false NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_cross_market_snapshot PRIMARY KEY (snapshot_id), 
    CONSTRAINT fk_cross_market_snapshot_asset_id_cross_market_asset FOREIGN KEY(asset_id) REFERENCES market.cross_market_asset (asset_id)
);

CREATE UNIQUE INDEX uq_cross_market_snapshot_point ON market.cross_market_snapshot (asset_id, provider, captured_at);

CREATE INDEX idx_cross_market_snapshot_day ON market.cross_market_snapshot (trading_day, captured_at);

CREATE INDEX idx_cross_market_snapshot_asset ON market.cross_market_snapshot (asset_id, captured_at);

CREATE TABLE news.event_entity_link (
    link_id BIGSERIAL NOT NULL, 
    event_id UUID NOT NULL, 
    entity_type news.entity_type_enum NOT NULL, 
    entity_id BIGINT NOT NULL, 
    relevance_score NUMERIC(12, 6), 
    impact_direction news.direction_enum DEFAULT 'unknown'::news.direction_enum NOT NULL, 
    impact_strength NUMERIC(12, 6), 
    linked_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_event_entity_link PRIMARY KEY (link_id), 
    CONSTRAINT fk_event_entity_link_event_id_news_event FOREIGN KEY(event_id) REFERENCES news.news_event (event_id)
);

CREATE INDEX idx_event_entity_lookup ON news.event_entity_link (entity_type, entity_id, linked_at);

CREATE UNIQUE INDEX uq_event_entity_link ON news.event_entity_link (event_id, entity_type, entity_id);

CREATE TABLE news.news_event_raw_ref (
    ref_id BIGSERIAL NOT NULL, 
    event_id UUID NOT NULL, 
    raw_news_id BIGINT NOT NULL, 
    relation_type VARCHAR(32) DEFAULT 'source' NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_news_event_raw_ref PRIMARY KEY (ref_id), 
    CONSTRAINT fk_news_event_raw_ref_event_id FOREIGN KEY(event_id) REFERENCES news.news_event (event_id), 
    CONSTRAINT fk_news_event_raw_ref_raw_news_id FOREIGN KEY(raw_news_id) REFERENCES news.news_raw_item (raw_news_id)
);

CREATE UNIQUE INDEX uq_news_event_raw_ref ON news.news_event_raw_ref (event_id, raw_news_id);

CREATE INDEX idx_news_event_raw_ref_raw ON news.news_event_raw_ref (raw_news_id);

CREATE TABLE news.news_event_impact_snapshot (
    impact_snapshot_id BIGSERIAL NOT NULL, 
    event_id UUID NOT NULL, 
    entity_type news.entity_type_enum NOT NULL, 
    entity_id BIGINT NOT NULL, 
    impact_level VARCHAR(16) NOT NULL, 
    impact_score NUMERIC(12, 6) NOT NULL, 
    source_score NUMERIC(12, 6), 
    entity_relevance NUMERIC(12, 6), 
    event_type_weight NUMERIC(12, 6), 
    direction_confidence NUMERIC(12, 6), 
    novelty_score NUMERIC(12, 6), 
    time_decay NUMERIC(12, 6), 
    market_confirmation NUMERIC(12, 6), 
    data_quality NUMERIC(12, 6), 
    risk_regime_adjustment NUMERIC(12, 6), 
    rule_hits_json JSONB, 
    reason_text TEXT, 
    computed_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_news_event_impact_snapshot PRIMARY KEY (impact_snapshot_id), 
    CONSTRAINT fk_news_event_impact_snapshot_event_id FOREIGN KEY(event_id) REFERENCES news.news_event (event_id)
);

CREATE INDEX idx_news_event_impact_entity ON news.news_event_impact_snapshot (entity_type, entity_id, computed_at);

CREATE UNIQUE INDEX uq_news_event_impact_snapshot ON news.news_event_impact_snapshot (event_id, entity_type, entity_id);

CREATE TABLE decision.recommendation_run (
    run_id BIGSERIAL NOT NULL, 
    trading_day DATE NOT NULL, 
    source_batch_id BIGINT, 
    run_type decision.run_type_enum NOT NULL, 
    started_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    finished_at TIMESTAMP WITH TIME ZONE, 
    status decision.run_status_enum DEFAULT 'queued'::decision.run_status_enum NOT NULL, 
    trigger_type VARCHAR(32) NOT NULL, 
    trigger_ref VARCHAR(128), 
    notes TEXT, 
    objective_horizon_days INTEGER, 
    objective_target_return_pct NUMERIC(12, 6), 
    objective_entry_basis VARCHAR(32), 
    objective_profile_scope VARCHAR(96), 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_recommendation_run PRIMARY KEY (run_id), 
    CONSTRAINT fk_recommendation_run_source_batch FOREIGN KEY(source_batch_id) REFERENCES market.candidate_batch (batch_id)
);

CREATE INDEX idx_recommendation_run_day ON decision.recommendation_run (trading_day, run_type, started_at);

CREATE INDEX idx_recommendation_run_source_batch ON decision.recommendation_run (source_batch_id, started_at);

CREATE TABLE decision.recommendation_outcome (
    outcome_id BIGSERIAL NOT NULL, 
    version_id BIGINT NOT NULL, 
    item_id BIGINT NOT NULL, 
    instrument_id BIGINT NOT NULL, 
    evaluation_window_days INTEGER NOT NULL, 
    entry_basis VARCHAR(32) DEFAULT 'open_5m_vwap' NOT NULL, 
    entry_trading_day DATE, 
    horizon_end_trading_day DATE, 
    entry_price NUMERIC(18, 4), 
    best_high_price NUMERIC(18, 4), 
    worst_low_price NUMERIC(18, 4), 
    close_price NUMERIC(18, 4), 
    max_return_pct NUMERIC(12, 6), 
    close_return_pct NUMERIC(12, 6), 
    max_drawdown_pct NUMERIC(12, 6), 
    cost_model_version VARCHAR(32), 
    cost_bps NUMERIC(12, 6), 
    slippage_bps NUMERIC(12, 6), 
    total_impact_bps NUMERIC(12, 6), 
    net_max_return_pct NUMERIC(12, 6), 
    net_close_return_pct NUMERIC(12, 6), 
    net_max_drawdown_pct NUMERIC(12, 6), 
    target_return_pct NUMERIC(12, 6), 
    target_hit BOOLEAN DEFAULT false NOT NULL, 
    target_hit_trading_day DATE, 
    net_target_hit BOOLEAN, 
    net_target_hit_trading_day DATE, 
    evaluation_status VARCHAR(16) DEFAULT 'pending' NOT NULL, 
    evaluated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    metrics_json JSONB, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_recommendation_outcome PRIMARY KEY (outcome_id), 
    CONSTRAINT fk_recommendation_outcome_version_id_recommendation_version FOREIGN KEY(version_id) REFERENCES decision.recommendation_version (version_id), 
    CONSTRAINT fk_recommendation_outcome_item_id_recommendation_item FOREIGN KEY(item_id) REFERENCES decision.recommendation_item (item_id), 
    CONSTRAINT fk_recommendation_outcome_instrument_id_instrument_master FOREIGN KEY(instrument_id) REFERENCES core.instrument_master (instrument_id)
);

CREATE UNIQUE INDEX uq_recommendation_outcome_item_window ON decision.recommendation_outcome (item_id, evaluation_window_days, entry_basis, target_return_pct) NULLS NOT DISTINCT;

CREATE INDEX idx_recommendation_outcome_instrument ON decision.recommendation_outcome (instrument_id, entry_trading_day);

CREATE INDEX idx_recommendation_outcome_version ON decision.recommendation_outcome (version_id, evaluation_status);

CREATE TABLE decision.brain_state_transition_log (
    transition_id BIGSERIAL NOT NULL, 
    state_id BIGINT, 
    instrument_id BIGINT, 
    symbol_snapshot VARCHAR(32) NOT NULL, 
    business_line VARCHAR(32) NOT NULL, 
    from_state VARCHAR(24), 
    to_state VARCHAR(24) NOT NULL, 
    reason_codes_json JSONB NOT NULL, 
    evidence_json JSONB, 
    changed_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_brain_state_transition_log PRIMARY KEY (transition_id), 
    CONSTRAINT fk_brain_state_transition_state_id_brain_subject_state FOREIGN KEY(state_id) REFERENCES decision.brain_subject_state (state_id) ON DELETE CASCADE, 
    CONSTRAINT fk_brain_state_transition_instrument_id_instrument_master FOREIGN KEY(instrument_id) REFERENCES core.instrument_master (instrument_id)
);

CREATE INDEX idx_brain_state_transition_symbol ON decision.brain_state_transition_log (symbol_snapshot, business_line, changed_at);

CREATE INDEX idx_brain_state_transition_state ON decision.brain_state_transition_log (to_state, changed_at);

CREATE TABLE decision.brain_push_event (
    push_event_id BIGSERIAL NOT NULL, 
    instrument_id BIGINT, 
    symbol_snapshot VARCHAR(32) NOT NULL, 
    business_line VARCHAR(32) NOT NULL, 
    trigger_type VARCHAR(64) NOT NULL, 
    trigger_reasons_json JSONB NOT NULL, 
    old_confidence_score NUMERIC(12, 6), 
    new_confidence_score NUMERIC(12, 6), 
    old_rank_no INTEGER, 
    new_rank_no INTEGER, 
    explanation_mode VARCHAR(32) NOT NULL, 
    explanation_cache_id BIGINT, 
    delivery_channel VARCHAR(32) DEFAULT 'websocket' NOT NULL, 
    delivery_status VARCHAR(24) DEFAULT 'queued' NOT NULL, 
    payload_json JSONB, 
    triggered_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_brain_push_event PRIMARY KEY (push_event_id), 
    CONSTRAINT fk_brain_push_event_instrument_id_instrument_master FOREIGN KEY(instrument_id) REFERENCES core.instrument_master (instrument_id), 
    CONSTRAINT fk_brain_push_event_explanation_cache_id_explanation_cache FOREIGN KEY(explanation_cache_id) REFERENCES explain.explanation_cache (cache_id)
);

CREATE INDEX idx_brain_push_event_delivery ON decision.brain_push_event (delivery_status, triggered_at);

CREATE INDEX idx_brain_push_event_symbol ON decision.brain_push_event (symbol_snapshot, business_line, triggered_at);

CREATE TABLE decision.dynamic_feature_latest (
    latest_id BIGSERIAL NOT NULL, 
    snapshot_id BIGINT, 
    instrument_id BIGINT, 
    symbol_snapshot VARCHAR(32) NOT NULL, 
    scope VARCHAR(32) NOT NULL, 
    trading_day DATE NOT NULL, 
    as_of_time TIMESTAMP WITH TIME ZONE NOT NULL, 
    window_seconds INTEGER NOT NULL, 
    feature_set_version VARCHAR(48) NOT NULL, 
    features_json JSONB NOT NULL, 
    source_gap_codes_json JSONB NOT NULL, 
    source_refs_json JSONB, 
    data_quality NUMERIC(12, 6), 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_dynamic_feature_latest PRIMARY KEY (latest_id), 
    CONSTRAINT fk_dynamic_feature_latest_snapshot_id_dynamic_feature_snapshot FOREIGN KEY(snapshot_id) REFERENCES decision.dynamic_feature_snapshot (snapshot_id) ON DELETE SET NULL, 
    CONSTRAINT fk_dynamic_feature_latest_instrument_id_instrument_master FOREIGN KEY(instrument_id) REFERENCES core.instrument_master (instrument_id)
);

CREATE INDEX idx_dynamic_feature_latest_symbol ON decision.dynamic_feature_latest (symbol_snapshot, scope, window_seconds);

CREATE UNIQUE INDEX uq_dynamic_feature_latest_subject_window ON decision.dynamic_feature_latest (scope, instrument_id, window_seconds, feature_set_version) NULLS NOT DISTINCT;

CREATE TABLE decision.hot_candidate_evidence_snapshot_v1 (
    snapshot_id BIGSERIAL NOT NULL, 
    batch_id BIGINT NOT NULL, 
    symbol VARCHAR(32) NOT NULL, 
    evidence_domain VARCHAR(64) NOT NULL, 
    dimension_role VARCHAR(32) NOT NULL, 
    dimension_status VARCHAR(32) NOT NULL, 
    as_of_time_utc TIMESTAMP WITH TIME ZONE NOT NULL, 
    captured_at_utc TIMESTAMP WITH TIME ZONE NOT NULL, 
    source_table VARCHAR(96) NOT NULL, 
    source_primary_key VARCHAR(128) NOT NULL, 
    source_version VARCHAR(64) NOT NULL, 
    payload_json JSONB NOT NULL, 
    source_gap_codes TEXT[], 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_hot_candidate_evidence_snapshot_v1 PRIMARY KEY (snapshot_id), 
    CONSTRAINT ck_hot_candidate_evidence_snapshot_v1_no_future CHECK (captured_at_utc <= as_of_time_utc), 
    CONSTRAINT ck_hot_candidate_evidence_snapshot_v1_dimension_role_allowed CHECK (dimension_role IN ('active','audit_only','future_calibration','label_only')), 
    CONSTRAINT ck_hot_candidate_evidence_snapshot_v1_dimension_status_allowed CHECK (dimension_status IN ('present','missing','deferred','future_label_only')), 
    CONSTRAINT fk_hot_candidate_evidence_snapshot_v1_batch_id_candidate_batch FOREIGN KEY(batch_id) REFERENCES market.candidate_batch (batch_id) ON DELETE CASCADE
);

CREATE INDEX idx_hot_candidate_evidence_snapshot_v1_symbol ON decision.hot_candidate_evidence_snapshot_v1 (symbol, evidence_domain, as_of_time_utc);

CREATE UNIQUE INDEX uq_hot_candidate_evidence_snapshot_v1_domain ON decision.hot_candidate_evidence_snapshot_v1 (batch_id, symbol, evidence_domain, as_of_time_utc);

CREATE TABLE decision.hot_candidate_feature_matrix_v1 (
    feature_matrix_id BIGSERIAL NOT NULL, 
    batch_id BIGINT NOT NULL, 
    symbol VARCHAR(32) NOT NULL, 
    model_version VARCHAR(48) NOT NULL, 
    as_of_time_utc TIMESTAMP WITH TIME ZONE NOT NULL, 
    teacher_prior_score NUMERIC(12, 6) NOT NULL, 
    local_confirmation_score NUMERIC(12, 6), 
    tradability_adjustment_score NUMERIC(12, 6), 
    upside_space_score NUMERIC(12, 6), 
    overheating_failure_risk NUMERIC(12, 6), 
    feature_gap_codes TEXT[], 
    feature_payload_json JSONB NOT NULL, 
    feature_hash VARCHAR(64) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_hot_candidate_feature_matrix_v1 PRIMARY KEY (feature_matrix_id), 
    CONSTRAINT ck_hot_candidate_feature_matrix_v1_teacher_prior_range CHECK (teacher_prior_score >= 0 AND teacher_prior_score <= 100), 
    CONSTRAINT ck_hot_candidate_feature_matrix_v1_local_confirm_range CHECK (local_confirmation_score IS NULL OR (local_confirmation_score >= 0 AND local_confirmation_score <= 100)), 
    CONSTRAINT ck_hot_candidate_feature_matrix_v1_tradability_range CHECK (tradability_adjustment_score IS NULL OR (tradability_adjustment_score >= 0 AND tradability_adjustment_score <= 100)), 
    CONSTRAINT ck_hot_candidate_feature_matrix_v1_upside_range CHECK (upside_space_score IS NULL OR (upside_space_score >= 0 AND upside_space_score <= 100)), 
    CONSTRAINT ck_hot_candidate_feature_matrix_v1_overheat_risk_range CHECK (overheating_failure_risk IS NULL OR (overheating_failure_risk >= 0 AND overheating_failure_risk <= 100)), 
    CONSTRAINT fk_hot_candidate_feature_matrix_v1_batch_id_candidate_batch FOREIGN KEY(batch_id) REFERENCES market.candidate_batch (batch_id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX uq_hot_candidate_feature_matrix_v1_snapshot ON decision.hot_candidate_feature_matrix_v1 (batch_id, symbol, model_version, as_of_time_utc);

CREATE INDEX idx_hot_candidate_feature_matrix_v1_hash ON decision.hot_candidate_feature_matrix_v1 (feature_hash);

CREATE TABLE decision.candidate_source_analysis_v1 (
    analysis_id BIGSERIAL NOT NULL, 
    batch_id BIGINT NOT NULL, 
    symbol VARCHAR(32) NOT NULL, 
    model_version VARCHAR(48) NOT NULL, 
    as_of_time_utc TIMESTAMP WITH TIME ZONE NOT NULL, 
    hot_score NUMERIC(12, 6), 
    state VARCHAR(24) NOT NULL, 
    main_positive_factors JSONB, 
    main_negative_factors JSONB, 
    hard_block_reasons TEXT[], 
    evidence_refs BIGINT[] NOT NULL, 
    source_gap_codes TEXT[], 
    score_hash VARCHAR(64) NOT NULL, 
    is_active BOOLEAN DEFAULT true NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_candidate_source_analysis_v1 PRIMARY KEY (analysis_id), 
    CONSTRAINT ck_candidate_source_analysis_v1_ck_hot_score_range CHECK (hot_score IS NULL OR (hot_score >= 0 AND hot_score <= 100)), 
    CONSTRAINT fk_candidate_source_analysis_v1_batch_id_candidate_batch FOREIGN KEY(batch_id) REFERENCES market.candidate_batch (batch_id) ON DELETE CASCADE
);

CREATE INDEX idx_candidate_source_analysis_v1_rank ON decision.candidate_source_analysis_v1 (batch_id, state, hot_score);

CREATE UNIQUE INDEX uq_candidate_source_analysis_v1_current ON decision.candidate_source_analysis_v1 (batch_id, symbol, model_version) WHERE is_active = true;

CREATE UNIQUE INDEX uq_candidate_source_analysis_v1_snapshot ON decision.candidate_source_analysis_v1 (batch_id, symbol, model_version, as_of_time_utc) WHERE is_active = true;

CREATE INDEX idx_candidate_source_analysis_v1_score_hash ON decision.candidate_source_analysis_v1 (score_hash);

CREATE TABLE decision.hit_8pct_outcome_label_v1 (
    label_id BIGSERIAL NOT NULL, 
    batch_id BIGINT NOT NULL, 
    symbol VARCHAR(32) NOT NULL, 
    entry_trading_day DATE NOT NULL, 
    first_sellable_trading_day DATE NOT NULL, 
    open_5m_vwap NUMERIC(18, 6), 
    target_price NUMERIC(18, 6), 
    risk_price NUMERIC(18, 6), 
    first_hit_ts TIMESTAMP WITH TIME ZONE, 
    first_risk_ts TIMESTAMP WITH TIME ZONE, 
    realizable_hit_before_risk BOOLEAN, 
    buy_day_hit_not_sellable BOOLEAN, 
    risk_before_hit BOOLEAN, 
    hit_after_risk BOOLEAN, 
    spike_reversal BOOLEAN, 
    max_favorable_excursion NUMERIC(12, 6), 
    max_adverse_excursion NUMERIC(12, 6), 
    days_to_realizable_hit INTEGER, 
    result_class VARCHAR(48), 
    label_status VARCHAR(24) NOT NULL, 
    path_resolution VARCHAR(16) NOT NULL, 
    outcome_payload_json JSONB, 
    label_matured_at_utc TIMESTAMP WITH TIME ZONE, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_hit_8pct_outcome_label_v1 PRIMARY KEY (label_id), 
    CONSTRAINT ck_hit_8pct_outcome_label_v1_status_ok CHECK (label_status IN ('pending','partial','missing','evaluated','superseded')), 
    CONSTRAINT ck_hit_8pct_outcome_label_v1_eval_has_result CHECK ((label_status = 'evaluated' AND result_class IS NOT NULL) OR (label_status IN ('pending','partial','missing') AND result_class IS NULL) OR label_status = 'superseded'), 
    CONSTRAINT ck_hit_8pct_outcome_label_v1_result_class_ok CHECK (result_class IS NULL OR result_class IN ('realizable_hit_before_risk','risk_before_hit','buy_day_hit_not_sellable','hit_after_risk','spike_reversal','no_hit_within_window','missing_path_data')), 
    CONSTRAINT ck_hit_8pct_outcome_label_v1_eval_minute CHECK (label_status <> 'evaluated' OR path_resolution = 'minute'), 
    CONSTRAINT ck_hit_8pct_outcome_label_v1_eval_open_5m_vwap_required CHECK (label_status <> 'evaluated' OR open_5m_vwap IS NOT NULL), 
    CONSTRAINT fk_hit_8pct_outcome_label_v1_batch_id_candidate_batch FOREIGN KEY(batch_id) REFERENCES market.candidate_batch (batch_id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX uq_hit_8pct_outcome_label_v1_symbol_profile ON decision.hit_8pct_outcome_label_v1 (batch_id, symbol, entry_trading_day);

CREATE INDEX idx_hit_8pct_outcome_label_v1_result ON decision.hit_8pct_outcome_label_v1 (label_status, result_class, realizable_hit_before_risk);

CREATE TABLE decision.ambush_effective_turn_candidate_v1 (
    turn_id BIGSERIAL NOT NULL, 
    valley_id BIGINT, 
    trade_date DATE NOT NULL, 
    symbol TEXT NOT NULL, 
    instrument_id BIGINT NOT NULL, 
    as_of_time TIMESTAMP WITH TIME ZONE NOT NULL, 
    snapshot_type TEXT NOT NULL, 
    shape_type TEXT NOT NULL, 
    effective_turn_anchor_day DATE NOT NULL, 
    effective_turn_age_days INTEGER NOT NULL, 
    primary_trough_day DATE NOT NULL, 
    primary_trough_age_days INTEGER NOT NULL, 
    post_turn_return_pct NUMERIC(12, 6) NOT NULL, 
    post_trough_return_pct NUMERIC(12, 6) NOT NULL, 
    close_strength NUMERIC(12, 6) NOT NULL, 
    volume_ratio NUMERIC(12, 6), 
    base_breakout_after_trough BOOLEAN DEFAULT false NOT NULL, 
    effective_turn_score NUMERIC(12, 6), 
    turn_freshness_score NUMERIC(12, 6), 
    late_rebound_penalty NUMERIC(12, 6), 
    l1_status TEXT NOT NULL, 
    reject_reason_codes TEXT[], 
    source_gap_codes TEXT[], 
    evidence_refs JSONB DEFAULT '[]'::jsonb NOT NULL, 
    payload_hash TEXT NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_ambush_effective_turn_candidate_v1 PRIMARY KEY (turn_id), 
    CONSTRAINT ck_ambush_effective_turn_candidate_v1_ck_aw_turn_acc_age CHECK (l1_status <> 'accepted' OR effective_turn_age_days <= 2), 
    CONSTRAINT ck_ambush_effective_turn_candidate_v1_ck_aw_turn_acc_ret CHECK (l1_status <> 'accepted' OR post_turn_return_pct <= 6), 
    CONSTRAINT fk_ambush_effective_turn_candidate_v1_valley_id FOREIGN KEY(valley_id) REFERENCES decision.ambush_valley_watch_pool_v1 (valley_id), 
    CONSTRAINT fk_ambush_effective_turn_candidate_v1_instrument_id FOREIGN KEY(instrument_id) REFERENCES core.instrument_master (instrument_id)
);

CREATE INDEX idx_ambush_effective_turn_candidate_v1_status ON decision.ambush_effective_turn_candidate_v1 (trade_date, l1_status, effective_turn_score);

CREATE UNIQUE INDEX uq_ambush_effective_turn_candidate_v1_identity ON decision.ambush_effective_turn_candidate_v1 (trade_date, symbol, effective_turn_anchor_day);

CREATE TABLE decision.research_outcome_label_v1 (
    label_id BIGSERIAL NOT NULL, 
    business_model TEXT NOT NULL, 
    model_version TEXT NOT NULL, 
    label_version TEXT NOT NULL, 
    signal_id BIGINT, 
    symbol TEXT NOT NULL, 
    trade_date DATE NOT NULL, 
    entry_price_type TEXT, 
    entry_price NUMERIC(18, 6), 
    label_purpose TEXT NOT NULL, 
    target_price NUMERIC(18, 6), 
    risk_price NUMERIC(18, 6), 
    first_hit_ts TIMESTAMP WITH TIME ZONE, 
    first_risk_ts TIMESTAMP WITH TIME ZONE, 
    first_sellable_trading_day DATE, 
    max_favorable_excursion NUMERIC(12, 6), 
    max_adverse_excursion NUMERIC(12, 6), 
    final_return_pct NUMERIC(12, 6), 
    realizable_hit_before_risk BOOLEAN, 
    buy_day_hit_not_sellable BOOLEAN, 
    risk_before_hit BOOLEAN, 
    hit_after_risk BOOLEAN, 
    spike_reversal BOOLEAN, 
    no_hit_within_window BOOLEAN, 
    model_specific_label TEXT, 
    result_class TEXT, 
    label_status TEXT NOT NULL, 
    exclude_reason TEXT, 
    path_resolution TEXT, 
    matured_at TIMESTAMP WITH TIME ZONE, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_research_outcome_label_v1 PRIMARY KEY (label_id), 
    CONSTRAINT ck_research_outcome_label_v1_eval_result CHECK (label_status <> 'evaluated' OR result_class IS NOT NULL), 
    CONSTRAINT ck_research_outcome_label_v1_official_entry CHECK (label_purpose <> 'official' OR entry_price_type IS NULL OR entry_price_type = 'open_5m_vwap'), 
    CONSTRAINT fk_research_outcome_signal FOREIGN KEY(signal_id) REFERENCES decision.research_model_signal_snapshot_v1 (signal_id)
);

CREATE INDEX idx_research_outcome_result ON decision.research_outcome_label_v1 (business_model, label_status, result_class);

CREATE UNIQUE INDEX uq_research_outcome_label_v1 ON decision.research_outcome_label_v1 (business_model, model_version, label_version, symbol, trade_date, entry_price_type, label_purpose) NULLS NOT DISTINCT;

CREATE TABLE decision.user_holding_watch (
    watch_id BIGSERIAL NOT NULL, 
    username VARCHAR(64) NOT NULL, 
    instrument_id BIGINT NOT NULL, 
    symbol_snapshot VARCHAR(32) NOT NULL, 
    version_id BIGINT, 
    item_id BIGINT, 
    status VARCHAR(16) DEFAULT 'active' NOT NULL, 
    source VARCHAR(32) DEFAULT 'operator_console' NOT NULL, 
    checked_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    unchecked_at TIMESTAMP WITH TIME ZONE, 
    last_alert_at TIMESTAMP WITH TIME ZONE, 
    last_alert_fingerprint VARCHAR(160), 
    last_risk_level VARCHAR(24), 
    notes_json JSONB, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_user_holding_watch PRIMARY KEY (watch_id), 
    CONSTRAINT fk_user_holding_watch_instrument_id_instrument_master FOREIGN KEY(instrument_id) REFERENCES core.instrument_master (instrument_id), 
    CONSTRAINT fk_user_holding_watch_version_id_recommendation_version FOREIGN KEY(version_id) REFERENCES decision.recommendation_version (version_id), 
    CONSTRAINT fk_user_holding_watch_item_id_recommendation_item FOREIGN KEY(item_id) REFERENCES decision.recommendation_item (item_id)
);

CREATE UNIQUE INDEX uq_user_holding_watch_active_user_instrument ON decision.user_holding_watch (username, instrument_id) WHERE status = 'active';

CREATE INDEX idx_user_holding_watch_user_status ON decision.user_holding_watch (username, status, updated_at);

CREATE INDEX idx_user_holding_watch_instrument ON decision.user_holding_watch (instrument_id, status);

CREATE TABLE decision.data_inspection_gap (
    gap_id BIGSERIAL NOT NULL, 
    run_id BIGINT NOT NULL, 
    subject_id BIGINT NOT NULL, 
    instrument_id BIGINT, 
    symbol_snapshot VARCHAR(32) NOT NULL, 
    gap_type VARCHAR(64) NOT NULL, 
    domain_code VARCHAR(64) NOT NULL, 
    target_table VARCHAR(96) NOT NULL, 
    severity VARCHAR(8) NOT NULL, 
    trading_day DATE, 
    gap_start_at TIMESTAMP WITH TIME ZONE, 
    gap_end_at TIMESTAMP WITH TIME ZONE, 
    missing_count INTEGER DEFAULT '0' NOT NULL, 
    expected_count INTEGER, 
    observed_count INTEGER, 
    blocks_scoring BOOLEAN DEFAULT false NOT NULL, 
    blocks_publish BOOLEAN DEFAULT false NOT NULL, 
    replay_safe BOOLEAN DEFAULT true NOT NULL, 
    provider_lineage_required BOOLEAN DEFAULT true NOT NULL, 
    remediation_status VARCHAR(96) DEFAULT 'pending' NOT NULL, 
    details_json JSONB, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_data_inspection_gap PRIMARY KEY (gap_id), 
    CONSTRAINT fk_data_inspection_gap_run_id_data_inspection_run FOREIGN KEY(run_id) REFERENCES decision.data_inspection_run (run_id) ON DELETE CASCADE, 
    CONSTRAINT fk_data_inspection_gap_subject_id_data_inspection_subject FOREIGN KEY(subject_id) REFERENCES decision.data_inspection_subject (subject_id) ON DELETE CASCADE, 
    CONSTRAINT fk_data_inspection_gap_instrument_id_instrument_master FOREIGN KEY(instrument_id) REFERENCES core.instrument_master (instrument_id)
);

CREATE INDEX idx_data_inspection_gap_run ON decision.data_inspection_gap (run_id, severity, gap_type);

CREATE INDEX idx_data_inspection_gap_symbol ON decision.data_inspection_gap (symbol_snapshot, domain_code, created_at);

CREATE TABLE decision.fact_model_signal (
    signal_id BIGSERIAL NOT NULL, 
    model_code TEXT NOT NULL, 
    model_version TEXT NOT NULL, 
    signal_type_code TEXT NOT NULL, 
    symbol TEXT NOT NULL, 
    trade_date DATE NOT NULL, 
    as_of_time TIMESTAMP WITH TIME ZONE NOT NULL, 
    source_state TEXT, 
    rank_no INTEGER, 
    score NUMERIC, 
    confidence_level TEXT, 
    feature_snapshot_id BIGINT, 
    evidence_snapshot_ids BIGINT[], 
    signal_reason_codes TEXT[], 
    source_gap_codes TEXT[], 
    payload_hash TEXT NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_fact_model_signal PRIMARY KEY (signal_id), 
    CONSTRAINT fk_fact_model_signal_model_code_dim_model FOREIGN KEY(model_code) REFERENCES decision.dim_model (model_code), 
    CONSTRAINT fk_fact_model_signal_type_dim_signal FOREIGN KEY(signal_type_code) REFERENCES decision.dim_signal_type (signal_type_code)
);

CREATE INDEX idx_fact_model_signal_model_date ON decision.fact_model_signal (model_code, trade_date);

CREATE UNIQUE INDEX uq_fact_model_signal_identity ON decision.fact_model_signal (model_code, model_version, signal_type_code, symbol, trade_date, as_of_time);

CREATE INDEX idx_fact_model_signal_symbol_date ON decision.fact_model_signal (symbol, trade_date);

CREATE TABLE decision.model_decision_review_read_model (
    read_model_id BIGSERIAL NOT NULL, 
    signal_id BIGINT NOT NULL, 
    model_code VARCHAR(64) NOT NULL, 
    stock_display VARCHAR(128) NOT NULL, 
    latest_price_display VARCHAR(64) DEFAULT '-' NOT NULL, 
    selected_date_display VARCHAR(64) DEFAULT '-' NOT NULL, 
    selected_days_display VARCHAR(64) DEFAULT '-' NOT NULL, 
    teacher_probability_display VARCHAR(64), 
    memory_state_display VARCHAR(128), 
    trigger_display VARCHAR(128), 
    model_score_display VARCHAR(64) DEFAULT '-' NOT NULL, 
    recommended_price_display VARCHAR(64) DEFAULT '-' NOT NULL, 
    return_from_reference_display VARCHAR(64) DEFAULT '-' NOT NULL, 
    verification_display VARCHAR(128) DEFAULT '-' NOT NULL, 
    risk_display VARCHAR(256) DEFAULT '���ݲ��㣬�ݲ��ж�' NOT NULL, 
    updated_display VARCHAR(128) DEFAULT '-' NOT NULL, 
    row_style VARCHAR(32) DEFAULT 'normal' NOT NULL, 
    snapshot_id BIGINT, 
    sequence_no BIGINT, 
    data_as_of TIMESTAMP WITH TIME ZONE, 
    calculated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    published_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    freshness_status VARCHAR(16) NOT NULL, 
    quality_status VARCHAR(16) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_model_decision_review_read_model PRIMARY KEY (read_model_id), 
    CONSTRAINT ck_model_decision_review_read_model_model_code_allowed CHECK (model_code IN ('hot_candidates','candidate_memory','ambush_watchlist')), 
    CONSTRAINT ck_model_decision_review_read_model_row_style_allowed CHECK (row_style IN ('normal','muted_today','hidden_default','blocked','stale')), 
    CONSTRAINT ck_model_decision_review_read_model_freshness_status_allowed CHECK (freshness_status IN ('fresh','delayed','stale','blocked')), 
    CONSTRAINT ck_model_decision_review_read_model_quality_status_allowed CHECK (quality_status IN ('usable','partial','blocked')), 
    CONSTRAINT ck_model_decision_review_read_model_stock_display_required CHECK (length(btrim(stock_display)) > 0), 
    CONSTRAINT fk_decision_review_read_model_signal FOREIGN KEY(signal_id) REFERENCES decision.fact_model_signal_v1 (signal_id), 
    CONSTRAINT fk_decision_review_read_model_snapshot FOREIGN KEY(snapshot_id) REFERENCES decision.fact_signal_monitor_snapshot_v1 (snapshot_id)
);

CREATE UNIQUE INDEX uq_decision_review_read_model_signal ON decision.model_decision_review_read_model (signal_id);

CREATE INDEX idx_decision_review_read_model_model_publish ON decision.model_decision_review_read_model (model_code, published_at);

CREATE INDEX idx_decision_review_read_model_row_style ON decision.model_decision_review_read_model (model_code, row_style);

CREATE TABLE explain.explanation_audit (
    audit_id BIGSERIAL NOT NULL, 
    request_id BIGINT NOT NULL, 
    output_id BIGINT NOT NULL, 
    audit_status VARCHAR(32) NOT NULL, 
    audit_mode VARCHAR(32), 
    audit_notes_json JSONB, 
    audit_findings_json JSONB, 
    pipeline_trace_json JSONB, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_explanation_audit PRIMARY KEY (audit_id), 
    CONSTRAINT fk_explanation_audit_request_id_explanation_request FOREIGN KEY(request_id) REFERENCES explain.explanation_request (request_id) ON DELETE CASCADE, 
    CONSTRAINT fk_explanation_audit_output_id_explanation_output FOREIGN KEY(output_id) REFERENCES explain.explanation_output (output_id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX uq_explanation_audit_output ON explain.explanation_audit (output_id);

CREATE INDEX idx_explanation_audit_status ON explain.explanation_audit (audit_status, created_at);

CREATE UNIQUE INDEX uq_explanation_audit_request ON explain.explanation_audit (request_id);

CREATE TABLE market.candidate_pool_item_trace_point (
    trace_id BIGSERIAL NOT NULL, 
    item_id BIGINT NOT NULL, 
    point_idx INTEGER NOT NULL, 
    metric_name VARCHAR(32) DEFAULT 'time_preview' NOT NULL, 
    metric_value NUMERIC(18, 6), 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_candidate_pool_item_trace_point PRIMARY KEY (trace_id), 
    CONSTRAINT fk_candidate_pool_item_trace_point_item_id_candidate_pool_item FOREIGN KEY(item_id) REFERENCES market.candidate_pool_item (item_id)
);

CREATE UNIQUE INDEX uq_candidate_trace_point ON market.candidate_pool_item_trace_point (item_id, metric_name, point_idx);

CREATE TABLE market.hot_candidate_item (
    candidate_id BIGSERIAL NOT NULL, 
    batch_id BIGINT NOT NULL, 
    instrument_id BIGINT NOT NULL, 
    symbol VARCHAR(32) NOT NULL, 
    name VARCHAR(64), 
    p_limit_up NUMERIC(12, 6), 
    p_limit_up_source VARCHAR(32) DEFAULT 'public_draft' NOT NULL, 
    limit_up_stage INTEGER, 
    source_rank_no INTEGER, 
    created_at_utc TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_hot_candidate_item PRIMARY KEY (candidate_id), 
    CONSTRAINT fk_hot_candidate_item_batch_id_candidate_batch FOREIGN KEY(batch_id) REFERENCES market.candidate_batch (batch_id) ON DELETE CASCADE, 
    CONSTRAINT fk_hot_candidate_item_instrument_id_instrument_master FOREIGN KEY(instrument_id) REFERENCES core.instrument_master (instrument_id), 
    CONSTRAINT ck_hot_candidate_item_ck_hot_candidate_item_probability_range CHECK (p_limit_up IS NULL OR (p_limit_up >= 0 AND p_limit_up <= 100)), 
    CONSTRAINT ck_hot_candidate_item_ck_hot_candidate_item_limit_up_stage CHECK (limit_up_stage IS NULL OR limit_up_stage IN (1, 2))
);

CREATE UNIQUE INDEX uq_hot_candidate_item_batch_instrument ON market.hot_candidate_item (batch_id, instrument_id);

CREATE INDEX idx_hot_candidate_item_symbol ON market.hot_candidate_item (symbol, batch_id);

CREATE TABLE market.candidate_submission_audit (
    submission_audit_id BIGSERIAL NOT NULL, 
    batch_id BIGINT NOT NULL, 
    submitted_by VARCHAR(32) DEFAULT 'system' NOT NULL, 
    submission_note TEXT, 
    item_count INTEGER NOT NULL, 
    included_item_count INTEGER NOT NULL, 
    frozen_payload JSONB NOT NULL, 
    production_submitted_at_utc TIMESTAMP WITH TIME ZONE NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_candidate_submission_audit PRIMARY KEY (submission_audit_id), 
    CONSTRAINT fk_cand_submission_audit_batch_candidate_batch FOREIGN KEY(batch_id) REFERENCES market.candidate_batch (batch_id)
);

CREATE UNIQUE INDEX uq_candidate_submission_audit_batch ON market.candidate_submission_audit (batch_id);

CREATE INDEX idx_candidate_submission_audit_submitted_at ON market.candidate_submission_audit (production_submitted_at_utc);

CREATE TABLE market.candidate_batch_supersession (
    supersession_id BIGSERIAL NOT NULL, 
    superseded_batch_id BIGINT NOT NULL, 
    replacement_batch_id BIGINT NOT NULL, 
    reason TEXT, 
    replaced_by VARCHAR(32) DEFAULT 'system' NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_candidate_batch_supersession PRIMARY KEY (supersession_id), 
    CONSTRAINT fk_cand_batch_supersession_superseded FOREIGN KEY(superseded_batch_id) REFERENCES market.candidate_batch (batch_id), 
    CONSTRAINT fk_cand_batch_supersession_replacement FOREIGN KEY(replacement_batch_id) REFERENCES market.candidate_batch (batch_id)
);

CREATE UNIQUE INDEX uq_candidate_batch_supersession_replacement ON market.candidate_batch_supersession (replacement_batch_id);

CREATE UNIQUE INDEX uq_candidate_batch_supersession_superseded ON market.candidate_batch_supersession (superseded_batch_id);

CREATE INDEX idx_candidate_batch_supersession_time ON market.candidate_batch_supersession (created_at);

CREATE TABLE decision.feature_snapshot (
    snapshot_id BIGSERIAL NOT NULL, 
    instrument_id BIGINT NOT NULL, 
    source_run_id BIGINT, 
    trading_day DATE NOT NULL, 
    snapshot_type VARCHAR(32) DEFAULT 'baseline' NOT NULL, 
    feature_set_version VARCHAR(32) NOT NULL, 
    features_json JSONB NOT NULL, 
    data_quality NUMERIC(12, 6), 
    as_of_time TIMESTAMP WITH TIME ZONE NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_feature_snapshot PRIMARY KEY (snapshot_id), 
    CONSTRAINT fk_feature_snapshot_instrument_id_instrument_master FOREIGN KEY(instrument_id) REFERENCES core.instrument_master (instrument_id), 
    CONSTRAINT fk_feature_snapshot_source_run_id_recommendation_run FOREIGN KEY(source_run_id) REFERENCES decision.recommendation_run (run_id)
);

CREATE INDEX idx_feature_snapshot_source_run ON decision.feature_snapshot (source_run_id, instrument_id, snapshot_type);

CREATE INDEX idx_feature_snapshot_day ON decision.feature_snapshot (trading_day, snapshot_type);

CREATE UNIQUE INDEX uq_feature_snapshot ON decision.feature_snapshot (instrument_id, trading_day, snapshot_type, feature_set_version, as_of_time);

CREATE TABLE decision.provider_health_snapshot (
    snapshot_id BIGSERIAL NOT NULL, 
    trading_day DATE NOT NULL, 
    run_id BIGINT NOT NULL, 
    version_id BIGINT, 
    provider core.provider_enum NOT NULL, 
    health_domain VARCHAR(64) NOT NULL, 
    health_status VARCHAR(16) DEFAULT 'healthy' NOT NULL, 
    detail_json JSONB, 
    captured_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_provider_health_snapshot PRIMARY KEY (snapshot_id), 
    CONSTRAINT fk_provider_health_snapshot_run_id_recommendation_run FOREIGN KEY(run_id) REFERENCES decision.recommendation_run (run_id), 
    CONSTRAINT fk_provider_health_snapshot_version_id_recommendation_version FOREIGN KEY(version_id) REFERENCES decision.recommendation_version (version_id)
);

CREATE INDEX idx_provider_health_snapshot_version ON decision.provider_health_snapshot (version_id, captured_at);

CREATE UNIQUE INDEX uq_provider_health_snapshot_run_domain ON decision.provider_health_snapshot (run_id, provider, health_domain);

CREATE TABLE decision.recommendation_case_review (
    review_id BIGSERIAL NOT NULL, 
    outcome_id BIGINT NOT NULL, 
    review_type VARCHAR(32) NOT NULL, 
    reviewer VARCHAR(32) DEFAULT 'system.auto_review' NOT NULL, 
    diagnosis_json JSONB NOT NULL, 
    weight_feedback_json JSONB, 
    reviewed_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_recommendation_case_review PRIMARY KEY (review_id), 
    CONSTRAINT fk_recommendation_case_review_outcome_id_recommendation_outcome FOREIGN KEY(outcome_id) REFERENCES decision.recommendation_outcome (outcome_id)
);

CREATE UNIQUE INDEX uq_recommendation_case_review_outcome ON decision.recommendation_case_review (outcome_id);

CREATE INDEX idx_recommendation_case_review_type ON decision.recommendation_case_review (review_type, reviewed_at);

CREATE TABLE decision.shadow_recommendation_outcome (
    shadow_outcome_id BIGSERIAL NOT NULL, 
    version_id BIGINT NOT NULL, 
    run_id BIGINT NOT NULL, 
    batch_id BIGINT NOT NULL, 
    candidate_id BIGINT NOT NULL, 
    instrument_id BIGINT NOT NULL, 
    decision_rank INTEGER, 
    selected_cutoff_rank INTEGER, 
    decision_score NUMERIC(12, 6), 
    confidence_score NUMERIC(12, 6), 
    selection_status VARCHAR(24) DEFAULT 'not_selected' NOT NULL, 
    evaluation_window_days INTEGER NOT NULL, 
    entry_basis VARCHAR(32) DEFAULT 'open_5m_vwap' NOT NULL, 
    entry_trading_day DATE, 
    horizon_end_trading_day DATE, 
    entry_price NUMERIC(18, 4), 
    best_high_price NUMERIC(18, 4), 
    worst_low_price NUMERIC(18, 4), 
    close_price NUMERIC(18, 4), 
    max_return_pct NUMERIC(12, 6), 
    close_return_pct NUMERIC(12, 6), 
    max_drawdown_pct NUMERIC(12, 6), 
    cost_model_version VARCHAR(32), 
    cost_bps NUMERIC(12, 6), 
    slippage_bps NUMERIC(12, 6), 
    total_impact_bps NUMERIC(12, 6), 
    net_max_return_pct NUMERIC(12, 6), 
    net_close_return_pct NUMERIC(12, 6), 
    net_max_drawdown_pct NUMERIC(12, 6), 
    target_return_pct NUMERIC(12, 6), 
    target_hit BOOLEAN DEFAULT false NOT NULL, 
    target_hit_trading_day DATE, 
    net_target_hit BOOLEAN, 
    net_target_hit_trading_day DATE, 
    evaluation_status VARCHAR(16) DEFAULT 'pending' NOT NULL, 
    evaluated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    metrics_json JSONB, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_shadow_recommendation_outcome PRIMARY KEY (shadow_outcome_id), 
    CONSTRAINT fk_shadow_rec_outcome_version FOREIGN KEY(version_id) REFERENCES decision.recommendation_version (version_id), 
    CONSTRAINT fk_shadow_rec_outcome_run FOREIGN KEY(run_id) REFERENCES decision.recommendation_run (run_id), 
    CONSTRAINT fk_shadow_rec_outcome_batch FOREIGN KEY(batch_id) REFERENCES market.candidate_batch (batch_id), 
    CONSTRAINT fk_shadow_rec_outcome_hot_candidate FOREIGN KEY(candidate_id) REFERENCES market.hot_candidate_item (candidate_id), 
    CONSTRAINT fk_shadow_rec_outcome_instr FOREIGN KEY(instrument_id) REFERENCES core.instrument_master (instrument_id)
);

CREATE INDEX idx_shadow_rec_outcome_instr ON decision.shadow_recommendation_outcome (instrument_id, entry_trading_day);

CREATE INDEX idx_shadow_rec_outcome_version ON decision.shadow_recommendation_outcome (version_id, evaluation_status);

CREATE UNIQUE INDEX uq_shadow_rec_outcome_version_item_window ON decision.shadow_recommendation_outcome (version_id, candidate_id, evaluation_window_days, entry_basis, target_return_pct) NULLS NOT DISTINCT;

CREATE TABLE decision.hot_candidate_explanation_event_ref (
    ref_id BIGSERIAL NOT NULL, 
    analysis_id BIGINT NOT NULL, 
    event_id UUID NOT NULL, 
    event_role VARCHAR(32) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_hot_candidate_explanation_event_ref PRIMARY KEY (ref_id), 
    CONSTRAINT fk_hot_candidate_explanation_event_ref_analysis_id FOREIGN KEY(analysis_id) REFERENCES decision.candidate_source_analysis_v1 (analysis_id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX uq_hot_candidate_explanation_event_ref ON decision.hot_candidate_explanation_event_ref (analysis_id, event_id);

CREATE TABLE decision.candidate_memory_entity (
    memory_id BIGSERIAL NOT NULL, 
    instrument_id BIGINT NOT NULL, 
    symbol VARCHAR(32) NOT NULL, 
    name_snapshot VARCHAR(64), 
    first_seen_trading_day DATE NOT NULL, 
    last_seen_trading_day DATE NOT NULL, 
    latest_batch_id BIGINT, 
    latest_candidate_id BIGINT, 
    appearance_count INTEGER DEFAULT '0' NOT NULL, 
    memory_age_days INTEGER, 
    ttl_stage VARCHAR(32), 
    memory_state VARCHAR(32) DEFAULT 'memory_watch' NOT NULL, 
    is_active BOOLEAN DEFAULT true NOT NULL, 
    source_gap_codes TEXT[] DEFAULT ARRAY[]::text[] NOT NULL, 
    current_positive_factors JSONB DEFAULT '[]'::jsonb NOT NULL, 
    current_negative_factors JSONB DEFAULT '[]'::jsonb NOT NULL, 
    current_hard_block_reasons TEXT[] DEFAULT ARRAY[]::text[] NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_candidate_memory_entity PRIMARY KEY (memory_id), 
    CONSTRAINT ck_candidate_memory_entity_appearance_count_non_negative CHECK (appearance_count >= 0), 
    CONSTRAINT ck_candidate_memory_entity_memory_age_days_non_negative CHECK (memory_age_days IS NULL OR memory_age_days >= 0), 
    CONSTRAINT ck_candidate_memory_entity_memory_state_allowed CHECK (memory_state IN ('memory_watch','memory_active','memory_reactivated','memory_decayed','memory_invalidated','blocked_data_gap')), 
    CONSTRAINT ck_candidate_memory_entity_ttl_stage_allowed CHECK (ttl_stage IS NULL OR ttl_stage IN ('strong','active','weak','expired')), 
    CONSTRAINT ck_candidate_memory_entity_seen_day_order CHECK (last_seen_trading_day >= first_seen_trading_day), 
    CONSTRAINT fk_candidate_memory_entity_instrument_id_instrument_master FOREIGN KEY(instrument_id) REFERENCES core.instrument_master (instrument_id), 
    CONSTRAINT fk_candidate_memory_entity_latest_batch FOREIGN KEY(latest_batch_id) REFERENCES market.candidate_batch (batch_id), 
    CONSTRAINT fk_candidate_memory_entity_latest_candidate FOREIGN KEY(latest_candidate_id) REFERENCES market.hot_candidate_item (candidate_id)
);

CREATE UNIQUE INDEX uq_candidate_memory_entity_active_instrument ON decision.candidate_memory_entity (instrument_id) WHERE is_active = true;

CREATE INDEX idx_candidate_memory_entity_state ON decision.candidate_memory_entity (memory_state, is_active, updated_at);

CREATE INDEX idx_candidate_memory_entity_symbol ON decision.candidate_memory_entity (symbol, is_active);

CREATE TABLE decision.cross_model_signal_lineage_v1 (
    lineage_id BIGSERIAL NOT NULL, 
    symbol TEXT NOT NULL, 
    first_signal_model TEXT NOT NULL, 
    first_signal_date DATE NOT NULL, 
    first_signal_id BIGINT, 
    hot_candidate_signal_id BIGINT, 
    memory_signal_id BIGINT, 
    ambush_signal_id BIGINT, 
    signal_sequence JSONB NOT NULL, 
    final_outcome_label_id BIGINT, 
    final_result_class TEXT, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_cross_model_signal_lineage_v1 PRIMARY KEY (lineage_id), 
    CONSTRAINT fk_cross_lineage_first_signal FOREIGN KEY(first_signal_id) REFERENCES decision.research_model_signal_snapshot_v1 (signal_id), 
    CONSTRAINT fk_cross_lineage_final_label FOREIGN KEY(final_outcome_label_id) REFERENCES decision.research_outcome_label_v1 (label_id)
);

CREATE INDEX idx_cross_model_signal_lineage_symbol ON decision.cross_model_signal_lineage_v1 (symbol, created_at);

CREATE UNIQUE INDEX uq_cross_model_signal_lineage_v1 ON decision.cross_model_signal_lineage_v1 (symbol, first_signal_date, first_signal_model);

CREATE TABLE decision.user_holding_risk_alert (
    alert_id BIGSERIAL NOT NULL, 
    watch_id BIGINT NOT NULL, 
    username VARCHAR(64) NOT NULL, 
    instrument_id BIGINT NOT NULL, 
    symbol_snapshot VARCHAR(32) NOT NULL, 
    version_id BIGINT, 
    item_id BIGINT, 
    risk_level VARCHAR(24) NOT NULL, 
    risk_codes_json JSONB NOT NULL, 
    confidence_score NUMERIC(12, 6), 
    alert_fingerprint VARCHAR(160) NOT NULL, 
    delivery_key VARCHAR(160) NOT NULL, 
    status VARCHAR(24) DEFAULT 'pending' NOT NULL, 
    message_id VARCHAR(255), 
    detail_json JSONB, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    sent_at TIMESTAMP WITH TIME ZONE, 
    CONSTRAINT pk_user_holding_risk_alert PRIMARY KEY (alert_id), 
    CONSTRAINT fk_user_holding_risk_alert_watch_id_user_holding_watch FOREIGN KEY(watch_id) REFERENCES decision.user_holding_watch (watch_id) ON DELETE CASCADE, 
    CONSTRAINT fk_user_holding_risk_alert_instrument_id_instrument_master FOREIGN KEY(instrument_id) REFERENCES core.instrument_master (instrument_id), 
    CONSTRAINT fk_user_holding_risk_alert_version_id_recommendation_version FOREIGN KEY(version_id) REFERENCES decision.recommendation_version (version_id), 
    CONSTRAINT fk_user_holding_risk_alert_item_id_recommendation_item FOREIGN KEY(item_id) REFERENCES decision.recommendation_item (item_id)
);

CREATE UNIQUE INDEX uq_user_holding_risk_alert_delivery_key ON decision.user_holding_risk_alert (delivery_key);

CREATE UNIQUE INDEX uq_user_holding_risk_alert_watch_fingerprint ON decision.user_holding_risk_alert (watch_id, alert_fingerprint);

CREATE INDEX idx_user_holding_risk_alert_user_status ON decision.user_holding_risk_alert (username, status, created_at);

CREATE TABLE decision.data_inspection_remediation_task (
    task_id BIGSERIAL NOT NULL, 
    run_id BIGINT NOT NULL, 
    gap_id BIGINT NOT NULL, 
    action_type VARCHAR(48) NOT NULL, 
    owner_service VARCHAR(48) NOT NULL, 
    priority VARCHAR(16) NOT NULL, 
    provider_candidates_json JSONB, 
    request_payload_json JSONB, 
    status VARCHAR(24) DEFAULT 'suggested' NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_data_inspection_remediation_task PRIMARY KEY (task_id), 
    CONSTRAINT fk_data_inspection_task_run_id_data_inspection_run FOREIGN KEY(run_id) REFERENCES decision.data_inspection_run (run_id) ON DELETE CASCADE, 
    CONSTRAINT fk_data_inspection_task_gap_id_data_inspection_gap FOREIGN KEY(gap_id) REFERENCES decision.data_inspection_gap (gap_id) ON DELETE CASCADE
);

CREATE INDEX idx_data_inspection_task_run ON decision.data_inspection_remediation_task (run_id, priority);

CREATE TABLE decision.fact_model_to_execution_signal (
    execution_signal_id BIGSERIAL NOT NULL, 
    signal_id BIGINT NOT NULL, 
    v1_signal_id BIGINT, 
    source_model TEXT NOT NULL, 
    source_model_version TEXT NOT NULL, 
    source_signal_type TEXT NOT NULL, 
    symbol TEXT NOT NULL, 
    trade_date DATE NOT NULL, 
    as_of_time TIMESTAMP WITH TIME ZONE NOT NULL, 
    signal_strength NUMERIC, 
    allowed_buy_point_types TEXT[] NOT NULL, 
    forbidden_buy_point_types TEXT[], 
    execution_signal_status TEXT DEFAULT 'created' NOT NULL, 
    handoff_reason_codes TEXT[] NOT NULL, 
    handoff_payload_hash TEXT NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_fact_model_to_execution_signal PRIMARY KEY (execution_signal_id), 
    CONSTRAINT fk_model_execution_signal_signal_id_fact_model FOREIGN KEY(signal_id) REFERENCES decision.fact_model_signal (signal_id), 
    CONSTRAINT fk_model_execution_signal_v1_signal_id FOREIGN KEY(v1_signal_id) REFERENCES decision.fact_model_signal_v1 (signal_id)
);

CREATE INDEX idx_execution_signal_source ON decision.fact_model_to_execution_signal (source_model, source_signal_type, trade_date);

CREATE UNIQUE INDEX uq_fact_model_to_execution_signal_signal ON decision.fact_model_to_execution_signal (signal_id);

CREATE INDEX idx_execution_signal_v1_signal ON decision.fact_model_to_execution_signal (v1_signal_id);

CREATE TABLE market.candidate_annotation_log (
    annotation_id BIGSERIAL NOT NULL, 
    candidate_id BIGINT NOT NULL, 
    field_name VARCHAR(64) NOT NULL, 
    old_value_json JSONB, 
    new_value_json JSONB, 
    reason TEXT, 
    operator VARCHAR(32) DEFAULT 'manual' NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_candidate_annotation_log PRIMARY KEY (annotation_id), 
    CONSTRAINT fk_cand_anno_log_hot_candidate_item FOREIGN KEY(candidate_id) REFERENCES market.hot_candidate_item (candidate_id) ON DELETE CASCADE
);

CREATE INDEX idx_candidate_annotation_log_candidate ON market.candidate_annotation_log (candidate_id, created_at);

CREATE TABLE decision.shadow_recommendation_case_review (
    shadow_review_id BIGSERIAL NOT NULL, 
    shadow_outcome_id BIGINT NOT NULL, 
    review_type VARCHAR(32) NOT NULL, 
    reviewer VARCHAR(32) DEFAULT 'system.auto_review' NOT NULL, 
    diagnosis_json JSONB NOT NULL, 
    weight_feedback_json JSONB, 
    reviewed_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_shadow_recommendation_case_review PRIMARY KEY (shadow_review_id), 
    CONSTRAINT fk_shadow_rec_review_outcome FOREIGN KEY(shadow_outcome_id) REFERENCES decision.shadow_recommendation_outcome (shadow_outcome_id)
);

CREATE UNIQUE INDEX uq_shadow_rec_review_outcome ON decision.shadow_recommendation_case_review (shadow_outcome_id);

CREATE INDEX idx_shadow_rec_review_type ON decision.shadow_recommendation_case_review (review_type, reviewed_at);

CREATE TABLE decision.candidate_memory_appearance (
    appearance_id BIGSERIAL NOT NULL, 
    memory_id BIGINT NOT NULL, 
    batch_id BIGINT NOT NULL, 
    candidate_id BIGINT NOT NULL, 
    instrument_id BIGINT NOT NULL, 
    symbol VARCHAR(32) NOT NULL, 
    name_snapshot VARCHAR(64), 
    candidate_trading_day DATE NOT NULL, 
    entry_trading_day DATE, 
    first_sellable_trading_day DATE NOT NULL, 
    p_limit_up NUMERIC(12, 6) NOT NULL, 
    p_limit_up_source VARCHAR(32) NOT NULL, 
    source_rank_no INTEGER, 
    limit_up_stage INTEGER NOT NULL, 
    source_hash VARCHAR(64) NOT NULL, 
    prior_hot_score NUMERIC(12, 6), 
    prior_state VARCHAR(32), 
    prior_risk_json JSONB DEFAULT '{}'::jsonb NOT NULL, 
    prior_evidence_completeness NUMERIC(12, 6), 
    source_analysis_id BIGINT, 
    evidence_refs BIGINT[] DEFAULT ARRAY[]::bigint[] NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_candidate_memory_appearance PRIMARY KEY (appearance_id), 
    CONSTRAINT ck_candidate_memory_appearance_p_limit_up_range CHECK (p_limit_up >= 0 AND p_limit_up <= 100), 
    CONSTRAINT ck_candidate_memory_appearance_prior_hot_score_range CHECK (prior_hot_score IS NULL OR (prior_hot_score >= 0 AND prior_hot_score <= 100)), 
    CONSTRAINT ck_candidate_memory_appearance_prior_ev_comp_range CHECK (prior_evidence_completeness IS NULL OR (prior_evidence_completeness >= 0 AND prior_evidence_completeness <= 1)), 
    CONSTRAINT ck_candidate_memory_appearance_cm_app_limit_up_stage CHECK (limit_up_stage IN (1, 2)), 
    CONSTRAINT ck_candidate_memory_appearance_cm_app_sellable_after_entry CHECK (entry_trading_day IS NULL OR first_sellable_trading_day > entry_trading_day), 
    CONSTRAINT fk_cm_app_memory FOREIGN KEY(memory_id) REFERENCES decision.candidate_memory_entity (memory_id) ON DELETE CASCADE, 
    CONSTRAINT fk_cm_app_batch FOREIGN KEY(batch_id) REFERENCES market.candidate_batch (batch_id), 
    CONSTRAINT fk_cm_app_candidate FOREIGN KEY(candidate_id) REFERENCES market.hot_candidate_item (candidate_id), 
    CONSTRAINT fk_cm_app_instrument FOREIGN KEY(instrument_id) REFERENCES core.instrument_master (instrument_id), 
    CONSTRAINT fk_cm_app_src_analysis FOREIGN KEY(source_analysis_id) REFERENCES decision.candidate_source_analysis_v1 (analysis_id) ON DELETE SET NULL
);

CREATE INDEX idx_candidate_memory_appearance_memory_day ON decision.candidate_memory_appearance (memory_id, candidate_trading_day);

CREATE UNIQUE INDEX uq_candidate_memory_appearance_batch_instrument ON decision.candidate_memory_appearance (batch_id, instrument_id);

CREATE UNIQUE INDEX uq_candidate_memory_appearance_batch_symbol ON decision.candidate_memory_appearance (batch_id, symbol);

CREATE OR REPLACE FUNCTION decision.enforce_candidate_memory_appearance_contract()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    b RECORD;
    i RECORD;
BEGIN
    SELECT source_model, ingest_mode, batch_status::text AS batch_status,
           contract_audit_status, is_active
      INTO b
      FROM market.candidate_batch
     WHERE batch_id = NEW.batch_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'candidate_memory appearance references missing batch_id=%', NEW.batch_id;
    END IF;

    IF b.source_model <> 'external_ths_model'
       OR b.ingest_mode <> 'external_ths_model'
       OR b.contract_audit_status <> 'passed'
       OR b.is_active IS DISTINCT FROM true
       OR b.batch_status IN ('draft_created','awaiting_paid_prior','contract_failed','superseded') THEN
        RAISE EXCEPTION 'candidate_memory only accepts audited active external_ths_model production batches, batch_id=%', NEW.batch_id;
    END IF;

    SELECT batch_id, instrument_id, symbol, name, p_limit_up,
           p_limit_up_source, limit_up_stage, source_rank_no
      INTO i
      FROM market.hot_candidate_item
     WHERE candidate_id = NEW.candidate_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'candidate_memory appearance references missing candidate_id=%', NEW.candidate_id;
    END IF;

    IF i.batch_id <> NEW.batch_id OR i.instrument_id <> NEW.instrument_id THEN
        RAISE EXCEPTION 'candidate_memory candidate lineage mismatch, candidate_id=% batch_id=%', NEW.candidate_id, NEW.batch_id;
    END IF;

    IF i.p_limit_up IS NULL OR i.p_limit_up_source = 'public_draft' THEN
        RAISE EXCEPTION 'candidate_memory rejects public_limitup_draft or missing paid THS probability, candidate_id=%', NEW.candidate_id;
    END IF;

    NEW.symbol := i.symbol;
    NEW.name_snapshot := i.name;
    NEW.p_limit_up := i.p_limit_up;
    NEW.p_limit_up_source := i.p_limit_up_source;
    NEW.limit_up_stage := i.limit_up_stage;
    NEW.source_rank_no := COALESCE(NEW.source_rank_no, i.source_rank_no);
    NEW.source_hash := COALESCE(
        NEW.source_hash,
        md5(CONCAT_WS('|', NEW.batch_id::text, NEW.candidate_id::text, i.symbol, i.p_limit_up::text, i.p_limit_up_source, i.limit_up_stage::text, COALESCE(i.source_rank_no::text, '')))
    );

    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_candidate_memory_appearance_contract
BEFORE INSERT OR UPDATE ON decision.candidate_memory_appearance
FOR EACH ROW EXECUTE FUNCTION decision.enforce_candidate_memory_appearance_contract();;

CREATE TABLE decision.candidate_memory_evidence_snapshot_v1 (
    snapshot_id BIGSERIAL NOT NULL, 
    memory_id BIGINT NOT NULL, 
    run_id BIGINT, 
    instrument_id BIGINT NOT NULL, 
    symbol VARCHAR(32) NOT NULL, 
    as_of_trading_day DATE NOT NULL, 
    as_of_time_utc TIMESTAMP WITH TIME ZONE NOT NULL, 
    captured_at_utc TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    evidence_version VARCHAR(64) DEFAULT 'candidate_memory_evidence_v1' NOT NULL, 
    evidence_domain VARCHAR(64) NOT NULL, 
    dimension_role VARCHAR(32) NOT NULL, 
    dimension_status VARCHAR(32) NOT NULL, 
    source_table VARCHAR(96) NOT NULL, 
    source_primary_key VARCHAR(128) NOT NULL, 
    source_version VARCHAR(64) NOT NULL, 
    payload_json JSONB DEFAULT '{}'::jsonb NOT NULL, 
    source_gap_codes TEXT[] DEFAULT ARRAY[]::text[] NOT NULL, 
    evidence_hash VARCHAR(64) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_candidate_memory_evidence_snapshot_v1 PRIMARY KEY (snapshot_id), 
    CONSTRAINT ck_candidate_memory_evidence_snapshot_v1_no_future_evidence CHECK (captured_at_utc <= as_of_time_utc), 
    CONSTRAINT ck_candidate_memory_evidence_snapshot_v1_dimension_role_allowed CHECK (dimension_role IN ('active','audit_only','future_calibration','label_only')), 
    CONSTRAINT ck_candidate_memory_evidence_snapshot_v1_dim_status_allowed CHECK (dimension_status IN ('present','missing','deferred','future_label_only')), 
    CONSTRAINT fk_candidate_memory_evidence_memory_id_candidate_memory_entity FOREIGN KEY(memory_id) REFERENCES decision.candidate_memory_entity (memory_id) ON DELETE CASCADE, 
    CONSTRAINT fk_candidate_memory_evidence_run_id_candidate_memory_job_run FOREIGN KEY(run_id) REFERENCES decision.candidate_memory_job_run (run_id) ON DELETE SET NULL, 
    CONSTRAINT fk_candidate_memory_evidence_instrument_id_instrument_master FOREIGN KEY(instrument_id) REFERENCES core.instrument_master (instrument_id)
);

CREATE INDEX idx_candidate_memory_evidence_domain ON decision.candidate_memory_evidence_snapshot_v1 (memory_id, evidence_domain, as_of_time_utc DESC);

CREATE UNIQUE INDEX uq_candidate_memory_evidence_hash ON decision.candidate_memory_evidence_snapshot_v1 (evidence_hash);

CREATE INDEX idx_candidate_memory_evidence_memory_time ON decision.candidate_memory_evidence_snapshot_v1 (memory_id, as_of_time_utc DESC);

CREATE TABLE decision.fact_execution_buy_point (
    buy_point_id BIGSERIAL NOT NULL, 
    execution_signal_id BIGINT NOT NULL, 
    signal_id BIGINT NOT NULL, 
    source_model TEXT NOT NULL, 
    source_signal_type TEXT NOT NULL, 
    source_model_version TEXT NOT NULL, 
    symbol TEXT NOT NULL, 
    trade_date DATE NOT NULL, 
    buy_point_type TEXT NOT NULL, 
    buy_point_window TEXT NOT NULL, 
    candidate_time TIMESTAMP WITH TIME ZONE NOT NULL, 
    estimated_exec_price NUMERIC, 
    exec_price_type TEXT, 
    buy_timing_score NUMERIC, 
    expected_net_value NUMERIC, 
    fill_probability NUMERIC, 
    expected_slippage_bps NUMERIC, 
    risk_reward_ratio NUMERIC, 
    downside_risk_score NUMERIC, 
    overheat_risk_score NUMERIC, 
    data_freshness_status TEXT NOT NULL, 
    buy_point_status TEXT NOT NULL, 
    scoring_detail_json JSONB NOT NULL, 
    scoring_hash TEXT NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_fact_execution_buy_point PRIMARY KEY (buy_point_id), 
    CONSTRAINT fk_execution_buy_point_execution_signal_id FOREIGN KEY(execution_signal_id) REFERENCES decision.fact_model_to_execution_signal (execution_signal_id), 
    CONSTRAINT fk_execution_buy_point_signal_id_fact_model FOREIGN KEY(signal_id) REFERENCES decision.fact_model_signal (signal_id), 
    CONSTRAINT fk_execution_buy_point_type_dim FOREIGN KEY(buy_point_type) REFERENCES decision.dim_buy_point_type (buy_point_type_code)
);

CREATE INDEX idx_buy_point_source_type ON decision.fact_execution_buy_point (source_model, buy_point_type, trade_date);

CREATE UNIQUE INDEX uq_fact_execution_buy_point_identity ON decision.fact_execution_buy_point (execution_signal_id, buy_point_type, candidate_time);

CREATE INDEX idx_buy_point_symbol_date ON decision.fact_execution_buy_point (symbol, trade_date);

CREATE TABLE decision.candidate_memory_feature_matrix_v1 (
    feature_id BIGSERIAL NOT NULL, 
    memory_id BIGINT NOT NULL, 
    snapshot_id BIGINT NOT NULL, 
    run_id BIGINT, 
    instrument_id BIGINT NOT NULL, 
    symbol VARCHAR(32) NOT NULL, 
    as_of_trading_day DATE NOT NULL, 
    as_of_time_utc TIMESTAMP WITH TIME ZONE NOT NULL, 
    model_version VARCHAR(64) DEFAULT 'candidate_memory_v1' NOT NULL, 
    feature_version VARCHAR(64) DEFAULT 'candidate_memory_feature_v1' NOT NULL, 
    memory_age_days INTEGER, 
    historical_candidate_quality NUMERIC(12, 6), 
    post_candidate_trend_quality NUMERIC(12, 6), 
    quiet_accumulation_score NUMERIC(12, 6), 
    second_wave_setup_score NUMERIC(12, 6), 
    upside_room_score NUMERIC(12, 6), 
    breakdown_failure_risk NUMERIC(12, 6), 
    structure_evidence_count INTEGER DEFAULT '0' NOT NULL, 
    compression_breakout BOOLEAN DEFAULT false NOT NULL, 
    reclaim_candidate_high BOOLEAN DEFAULT false NOT NULL, 
    reclaim_ma5_ma10 BOOLEAN DEFAULT false NOT NULL, 
    pullback_absorption BOOLEAN DEFAULT false NOT NULL, 
    capital_follow_improved BOOLEAN DEFAULT false NOT NULL, 
    p0_gap_codes TEXT[] DEFAULT ARRAY[]::text[] NOT NULL, 
    p1_gap_codes TEXT[] DEFAULT ARRAY[]::text[] NOT NULL, 
    p2_gap_codes TEXT[] DEFAULT ARRAY[]::text[] NOT NULL, 
    feature_gap_codes TEXT[] DEFAULT ARRAY[]::text[] NOT NULL, 
    source_gap_codes TEXT[] DEFAULT ARRAY[]::text[] NOT NULL, 
    evidence_refs BIGINT[] DEFAULT ARRAY[]::bigint[] NOT NULL, 
    feature_payload JSONB DEFAULT '{}'::jsonb NOT NULL, 
    feature_hash VARCHAR(64) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_candidate_memory_feature_matrix_v1 PRIMARY KEY (feature_id), 
    CONSTRAINT ck_candidate_memory_feature_matrix_v1_age_nonneg CHECK (memory_age_days IS NULL OR memory_age_days >= 0), 
    CONSTRAINT ck_candidate_memory_feature_matrix_v1_struct_count_nonneg CHECK (structure_evidence_count >= 0), 
    CONSTRAINT ck_candidate_memory_feature_matrix_v1_hist_quality_range CHECK (historical_candidate_quality IS NULL OR historical_candidate_quality BETWEEN 0 AND 100), 
    CONSTRAINT ck_candidate_memory_feature_matrix_v1_trend_quality_range CHECK (post_candidate_trend_quality IS NULL OR post_candidate_trend_quality BETWEEN 0 AND 100), 
    CONSTRAINT ck_candidate_memory_feature_matrix_v1_accum_score_range CHECK (quiet_accumulation_score IS NULL OR quiet_accumulation_score BETWEEN 0 AND 100), 
    CONSTRAINT ck_candidate_memory_feature_matrix_v1_wave_score_range CHECK (second_wave_setup_score IS NULL OR second_wave_setup_score BETWEEN 0 AND 100), 
    CONSTRAINT ck_candidate_memory_feature_matrix_v1_upside_score_range CHECK (upside_room_score IS NULL OR upside_room_score BETWEEN 0 AND 100), 
    CONSTRAINT ck_candidate_memory_feature_matrix_v1_breakdown_risk_range CHECK (breakdown_failure_risk IS NULL OR breakdown_failure_risk BETWEEN 0 AND 100), 
    CONSTRAINT fk_cm_feat_memory FOREIGN KEY(memory_id) REFERENCES decision.candidate_memory_entity (memory_id) ON DELETE CASCADE, 
    CONSTRAINT fk_cm_feat_snapshot FOREIGN KEY(snapshot_id) REFERENCES decision.candidate_memory_evidence_snapshot_v1 (snapshot_id) ON DELETE CASCADE, 
    CONSTRAINT fk_cm_feat_run FOREIGN KEY(run_id) REFERENCES decision.candidate_memory_job_run (run_id) ON DELETE SET NULL, 
    CONSTRAINT fk_cm_feat_instrument FOREIGN KEY(instrument_id) REFERENCES core.instrument_master (instrument_id)
);

CREATE UNIQUE INDEX uq_candidate_memory_feature_hash ON decision.candidate_memory_feature_matrix_v1 (feature_hash);

CREATE INDEX idx_candidate_memory_feature_memory_time ON decision.candidate_memory_feature_matrix_v1 (memory_id, as_of_time_utc DESC);

CREATE TABLE decision.fact_execution_buy_point_outcome (
    outcome_id BIGSERIAL NOT NULL, 
    buy_point_id BIGINT NOT NULL, 
    execution_signal_id BIGINT NOT NULL, 
    signal_id BIGINT NOT NULL, 
    source_model TEXT NOT NULL, 
    source_signal_type TEXT NOT NULL, 
    buy_point_type TEXT NOT NULL, 
    symbol TEXT NOT NULL, 
    trade_date DATE NOT NULL, 
    entry_time TIMESTAMP WITH TIME ZONE NOT NULL, 
    entry_price NUMERIC NOT NULL, 
    target_price NUMERIC, 
    risk_price NUMERIC, 
    first_hit_ts TIMESTAMP WITH TIME ZONE, 
    first_risk_ts TIMESTAMP WITH TIME ZONE, 
    max_favorable_excursion_pct NUMERIC, 
    max_adverse_excursion_pct NUMERIC, 
    hit_before_risk BOOLEAN, 
    risk_before_hit BOOLEAN, 
    no_fill BOOLEAN, 
    buy_window_failed BOOLEAN, 
    result_class TEXT, 
    label_status TEXT NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_fact_execution_buy_point_outcome PRIMARY KEY (outcome_id), 
    CONSTRAINT fk_buy_point_outcome_buy_point_id FOREIGN KEY(buy_point_id) REFERENCES decision.fact_execution_buy_point (buy_point_id), 
    CONSTRAINT fk_buy_point_outcome_execution_signal_id FOREIGN KEY(execution_signal_id) REFERENCES decision.fact_model_to_execution_signal (execution_signal_id), 
    CONSTRAINT fk_buy_point_outcome_signal_id_fact_model FOREIGN KEY(signal_id) REFERENCES decision.fact_model_signal (signal_id)
);

CREATE UNIQUE INDEX uq_fact_execution_buy_point_outcome_buy_point ON decision.fact_execution_buy_point_outcome (buy_point_id);

CREATE TABLE decision.fact_signal_methodology_mapping (
    mapping_id BIGSERIAL NOT NULL, 
    signal_id BIGINT, 
    execution_signal_id BIGINT, 
    buy_point_id BIGINT, 
    methodology_code TEXT NOT NULL, 
    methodology_role TEXT NOT NULL, 
    model_code TEXT NOT NULL, 
    signal_type_code TEXT, 
    buy_point_type TEXT, 
    symbol TEXT NOT NULL, 
    trade_date DATE NOT NULL, 
    as_of_time TIMESTAMP WITH TIME ZONE NOT NULL, 
    mapping_source TEXT NOT NULL, 
    mapping_reason_codes TEXT[] NOT NULL, 
    mapping_payload_hash TEXT NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_fact_signal_methodology_mapping PRIMARY KEY (mapping_id), 
    CONSTRAINT ck_fact_signal_methodology_mapping_has_subject CHECK (signal_id IS NOT NULL OR buy_point_id IS NOT NULL), 
    CONSTRAINT ck_fact_signal_methodology_mapping_role_allowed CHECK (methodology_role IN ('primary','support','filter','risk','learning')), 
    CONSTRAINT uq_signal_methodology_mapping_hash UNIQUE (mapping_payload_hash), 
    CONSTRAINT fk_signal_methodology_signal FOREIGN KEY(signal_id) REFERENCES decision.fact_model_signal (signal_id), 
    CONSTRAINT fk_signal_methodology_execution_signal FOREIGN KEY(execution_signal_id) REFERENCES decision.fact_model_to_execution_signal (execution_signal_id), 
    CONSTRAINT fk_signal_methodology_buy_point FOREIGN KEY(buy_point_id) REFERENCES decision.fact_execution_buy_point (buy_point_id), 
    CONSTRAINT fk_signal_methodology_methodology FOREIGN KEY(methodology_code) REFERENCES decision.dim_research_methodology (methodology_code)
);

CREATE INDEX idx_signal_methodology_buy_point ON decision.fact_signal_methodology_mapping (buy_point_id, methodology_code);

CREATE INDEX idx_signal_methodology_date ON decision.fact_signal_methodology_mapping (methodology_code, trade_date);

CREATE INDEX idx_signal_methodology_signal ON decision.fact_signal_methodology_mapping (signal_id, methodology_code);

CREATE TABLE decision.candidate_memory_analysis_v1 (
    analysis_id BIGSERIAL NOT NULL, 
    memory_id BIGINT NOT NULL, 
    feature_id BIGINT NOT NULL, 
    snapshot_id BIGINT NOT NULL, 
    run_id BIGINT, 
    instrument_id BIGINT NOT NULL, 
    symbol VARCHAR(32) NOT NULL, 
    as_of_trading_day DATE NOT NULL, 
    as_of_time_utc TIMESTAMP WITH TIME ZONE NOT NULL, 
    model_version VARCHAR(64) DEFAULT 'candidate_memory_v1' NOT NULL, 
    score_stage VARCHAR(32) DEFAULT 'final_daily' NOT NULL, 
    target_return NUMERIC(12, 6) DEFAULT '0.08' NOT NULL, 
    target_window_days INTEGER DEFAULT '5' NOT NULL, 
    entry_basis VARCHAR(32) DEFAULT 'open_5m_vwap' NOT NULL, 
    memory_state VARCHAR(32) NOT NULL, 
    publication_state VARCHAR(32) NOT NULL, 
    memory_hit_8pct_score NUMERIC(12, 6), 
    memory_age_days INTEGER, 
    appearance_count INTEGER NOT NULL, 
    latest_candidate_trading_day DATE NOT NULL, 
    historical_candidate_quality NUMERIC(12, 6), 
    post_candidate_trend_quality NUMERIC(12, 6), 
    quiet_accumulation_score NUMERIC(12, 6), 
    second_wave_setup_score NUMERIC(12, 6), 
    upside_room_score NUMERIC(12, 6), 
    breakdown_failure_risk NUMERIC(12, 6), 
    structure_evidence_count INTEGER DEFAULT '0' NOT NULL, 
    main_positive_factors JSONB DEFAULT '[]'::jsonb NOT NULL, 
    main_negative_factors JSONB DEFAULT '[]'::jsonb NOT NULL, 
    hard_block_reasons TEXT[] DEFAULT ARRAY[]::text[] NOT NULL, 
    source_gap_codes TEXT[] DEFAULT ARRAY[]::text[] NOT NULL, 
    confirmation_conditions JSONB DEFAULT '[]'::jsonb NOT NULL, 
    invalidation_conditions JSONB DEFAULT '[]'::jsonb NOT NULL, 
    evidence_refs BIGINT[] DEFAULT ARRAY[]::bigint[] NOT NULL, 
    feature_hash VARCHAR(64) NOT NULL, 
    score_hash VARCHAR(64) NOT NULL, 
    is_active BOOLEAN DEFAULT true NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_candidate_memory_analysis_v1 PRIMARY KEY (analysis_id), 
    CONSTRAINT ck_candidate_memory_analysis_v1_score_stage_ok CHECK (score_stage IN ('preopen','intraday','close','final_daily')), 
    CONSTRAINT ck_candidate_memory_analysis_v1_memory_state_ok CHECK (memory_state IN ('memory_watch','memory_active','memory_reactivated','memory_decayed','memory_invalidated','blocked_data_gap')), 
    CONSTRAINT ck_candidate_memory_analysis_v1_publication_ok CHECK (publication_state IN ('ready','warning','blocked','watch','invalidated')), 
    CONSTRAINT ck_candidate_memory_analysis_v1_hit_score_range CHECK (memory_hit_8pct_score IS NULL OR memory_hit_8pct_score BETWEEN 0 AND 100), 
    CONSTRAINT ck_candidate_memory_analysis_v1_memory_age_nonneg CHECK (memory_age_days IS NULL OR memory_age_days >= 0), 
    CONSTRAINT ck_candidate_memory_analysis_v1_hist_quality_range CHECK (historical_candidate_quality IS NULL OR historical_candidate_quality BETWEEN 0 AND 100), 
    CONSTRAINT ck_candidate_memory_analysis_v1_trend_quality_range CHECK (post_candidate_trend_quality IS NULL OR post_candidate_trend_quality BETWEEN 0 AND 100), 
    CONSTRAINT ck_candidate_memory_analysis_v1_accum_score_range CHECK (quiet_accumulation_score IS NULL OR quiet_accumulation_score BETWEEN 0 AND 100), 
    CONSTRAINT ck_candidate_memory_analysis_v1_wave_score_range CHECK (second_wave_setup_score IS NULL OR second_wave_setup_score BETWEEN 0 AND 100), 
    CONSTRAINT ck_candidate_memory_analysis_v1_upside_score_range CHECK (upside_room_score IS NULL OR upside_room_score BETWEEN 0 AND 100), 
    CONSTRAINT ck_candidate_memory_analysis_v1_breakdown_risk_range CHECK (breakdown_failure_risk IS NULL OR breakdown_failure_risk BETWEEN 0 AND 100), 
    CONSTRAINT ck_candidate_memory_analysis_v1_blocked_no_score CHECK (memory_state <> 'blocked_data_gap' OR memory_hit_8pct_score IS NULL), 
    CONSTRAINT ck_candidate_memory_analysis_v1_reactivated_evidence CHECK (memory_state <> 'memory_reactivated' OR (second_wave_setup_score IS NOT NULL AND breakdown_failure_risk IS NOT NULL AND second_wave_setup_score >= 70 AND breakdown_failure_risk < 45 AND memory_age_days IS NOT NULL AND memory_age_days >= 5 AND memory_age_days <= 20 AND structure_evidence_count >= 2)), 
    CONSTRAINT ck_candidate_memory_analysis_v1_invalidated_low_score CHECK (memory_state <> 'memory_invalidated' OR memory_hit_8pct_score IS NULL OR memory_hit_8pct_score < 70), 
    CONSTRAINT ck_candidate_memory_analysis_v1_high_risk_block CHECK (breakdown_failure_risk IS NULL OR breakdown_failure_risk < 70 OR memory_state <> 'memory_reactivated'), 
    CONSTRAINT fk_cm_analysis_memory FOREIGN KEY(memory_id) REFERENCES decision.candidate_memory_entity (memory_id) ON DELETE CASCADE, 
    CONSTRAINT fk_cm_analysis_feature FOREIGN KEY(feature_id) REFERENCES decision.candidate_memory_feature_matrix_v1 (feature_id), 
    CONSTRAINT fk_cm_analysis_snapshot FOREIGN KEY(snapshot_id) REFERENCES decision.candidate_memory_evidence_snapshot_v1 (snapshot_id), 
    CONSTRAINT fk_cm_analysis_run FOREIGN KEY(run_id) REFERENCES decision.candidate_memory_job_run (run_id) ON DELETE SET NULL, 
    CONSTRAINT fk_cm_analysis_instrument FOREIGN KEY(instrument_id) REFERENCES core.instrument_master (instrument_id)
);

CREATE INDEX idx_candidate_memory_analysis_symbol ON decision.candidate_memory_analysis_v1 (symbol, as_of_trading_day DESC);

CREATE UNIQUE INDEX uq_candidate_memory_analysis_active_objective ON decision.candidate_memory_analysis_v1 (memory_id, as_of_trading_day, score_stage, model_version, target_window_days, entry_basis, target_return) WHERE is_active = true;

CREATE INDEX idx_candidate_memory_analysis_rank ON decision.candidate_memory_analysis_v1 (as_of_trading_day, score_stage, memory_state, memory_hit_8pct_score DESC);

CREATE TABLE decision.candidate_memory_state_history (
    state_history_id BIGSERIAL NOT NULL, 
    memory_id BIGINT NOT NULL, 
    analysis_id BIGINT NOT NULL, 
    created_by_job_run_id VARCHAR(64) NOT NULL, 
    instrument_id BIGINT NOT NULL, 
    symbol VARCHAR(32) NOT NULL, 
    from_state VARCHAR(32), 
    to_state VARCHAR(32) NOT NULL, 
    transition_kind VARCHAR(32) DEFAULT 'normal' NOT NULL, 
    transition_time_utc TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    as_of_trading_day DATE NOT NULL, 
    transition_reason_codes TEXT[] NOT NULL, 
    evidence_refs BIGINT[] DEFAULT ARRAY[]::bigint[] NOT NULL, 
    transition_key VARCHAR(96) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_candidate_memory_state_history PRIMARY KEY (state_history_id), 
    CONSTRAINT ck_candidate_memory_state_history_to_state_allowed CHECK (to_state IN ('memory_watch','memory_active','memory_reactivated','memory_decayed','memory_invalidated','blocked_data_gap')), 
    CONSTRAINT ck_candidate_memory_state_history_from_state_allowed CHECK (from_state IS NULL OR from_state IN ('memory_watch','memory_active','memory_reactivated','memory_decayed','memory_invalidated','blocked_data_gap')), 
    CONSTRAINT ck_candidate_memory_state_history_reason_codes_required CHECK (cardinality(transition_reason_codes) > 0), 
    CONSTRAINT fk_cm_state_memory FOREIGN KEY(memory_id) REFERENCES decision.candidate_memory_entity (memory_id) ON DELETE CASCADE, 
    CONSTRAINT fk_cm_state_analysis FOREIGN KEY(analysis_id) REFERENCES decision.candidate_memory_analysis_v1 (analysis_id), 
    CONSTRAINT fk_cm_state_instrument FOREIGN KEY(instrument_id) REFERENCES core.instrument_master (instrument_id)
);

CREATE INDEX idx_candidate_memory_state_history_memory_time ON decision.candidate_memory_state_history (memory_id, transition_time_utc DESC);

CREATE UNIQUE INDEX uq_candidate_memory_state_history_key ON decision.candidate_memory_state_history (transition_key);

CREATE TABLE decision.candidate_memory_outcome_label_v1 (
    label_id BIGSERIAL NOT NULL, 
    memory_id BIGINT NOT NULL, 
    analysis_id BIGINT, 
    appearance_id BIGINT, 
    instrument_id BIGINT NOT NULL, 
    symbol VARCHAR(32) NOT NULL, 
    label_profile_version VARCHAR(64) DEFAULT 'candidate_memory_label_v1' NOT NULL, 
    label_kind VARCHAR(48) NOT NULL, 
    target_return NUMERIC(12, 6) DEFAULT '0.08' NOT NULL, 
    stop_loss_return NUMERIC(12, 6) DEFAULT '-0.04' NOT NULL, 
    label_window_days INTEGER NOT NULL, 
    entry_basis VARCHAR(32) DEFAULT 'open_5m_vwap' NOT NULL, 
    original_entry_trading_day DATE, 
    reactivation_trading_day DATE, 
    buy_trading_day DATE, 
    first_sellable_trading_day DATE, 
    window_end_trading_day DATE, 
    original_entry_open_5m_vwap NUMERIC(18, 6), 
    reactivation_entry_open_5m_vwap NUMERIC(18, 6), 
    evaluated_entry_price NUMERIC(18, 6), 
    target_price NUMERIC(18, 6), 
    risk_price NUMERIC(18, 6), 
    path_resolution VARCHAR(32), 
    minute_bar_completeness_pct NUMERIC(12, 6), 
    label_status VARCHAR(32) NOT NULL, 
    result_class VARCHAR(64), 
    intraday_hit_8pct BOOLEAN, 
    realizable_hit_8pct BOOLEAN, 
    realizable_hit_before_risk BOOLEAN, 
    buy_day_hit_not_sellable BOOLEAN, 
    delayed_follow_through BOOLEAN, 
    second_wave_success BOOLEAN, 
    slow_trend_value BOOLEAN, 
    risk_before_memory_hit BOOLEAN, 
    first_hit_ts TIMESTAMP WITH TIME ZONE, 
    first_risk_ts TIMESTAMP WITH TIME ZONE, 
    days_to_first_hit INTEGER, 
    days_to_realizable_hit INTEGER, 
    max_favorable_excursion NUMERIC(12, 6), 
    max_adverse_excursion NUMERIC(12, 6), 
    slow_trend_return NUMERIC(12, 6), 
    slow_trend_max_drawdown NUMERIC(12, 6), 
    memory_decayed_no_hit BOOLEAN, 
    memory_invalidated_breakdown BOOLEAN, 
    label_matured_at_utc TIMESTAMP WITH TIME ZONE, 
    source_gap_codes TEXT[] DEFAULT ARRAY[]::text[] NOT NULL, 
    model_evolution_label_pack_json JSONB DEFAULT '{}'::jsonb NOT NULL, 
    label_hash VARCHAR(64) NOT NULL, 
    superseded_by_label_id BIGINT, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    CONSTRAINT pk_candidate_memory_outcome_label_v1 PRIMARY KEY (label_id), 
    CONSTRAINT ck_candidate_memory_outcome_label_v1_window_days_ok CHECK (label_window_days IN (1,3,5,10,20,30)), 
    CONSTRAINT ck_candidate_memory_outcome_label_v1_status_ok CHECK (label_status IN ('pending','partial','missing','evaluated','superseded')), 
    CONSTRAINT ck_candidate_memory_outcome_label_v1_eval_has_result CHECK ((label_status = 'evaluated' AND result_class IS NOT NULL) OR (label_status IN ('pending','partial','missing') AND result_class IS NULL) OR label_status = 'superseded'), 
    CONSTRAINT ck_candidate_memory_outcome_label_v1_result_class_ok CHECK (result_class IS NULL OR result_class IN ('delayed_follow_through','second_wave_success','slow_trend_value','memory_decayed_no_hit','memory_invalidated_breakdown','risk_before_memory_hit','missing_path_data','buy_day_hit_not_sellable','no_hit_within_window')), 
    CONSTRAINT ck_candidate_memory_outcome_label_v1_eval_minute CHECK (label_status <> 'evaluated' OR path_resolution = 'minute'), 
    CONSTRAINT ck_candidate_memory_outcome_label_v1_minute_comp_range CHECK (minute_bar_completeness_pct IS NULL OR minute_bar_completeness_pct BETWEEN 0 AND 1), 
    CONSTRAINT ck_candidate_memory_outcome_label_v1_wave_react_vwap CHECK (result_class <> 'second_wave_success' OR reactivation_entry_open_5m_vwap IS NOT NULL), 
    CONSTRAINT ck_candidate_memory_outcome_label_v1_delayed_orig_vwap CHECK (result_class <> 'delayed_follow_through' OR original_entry_open_5m_vwap IS NOT NULL), 
    CONSTRAINT ck_candidate_memory_outcome_label_v1_risk_flag_required CHECK (result_class <> 'risk_before_memory_hit' OR risk_before_memory_hit IS TRUE), 
    CONSTRAINT fk_cm_label_memory FOREIGN KEY(memory_id) REFERENCES decision.candidate_memory_entity (memory_id) ON DELETE CASCADE, 
    CONSTRAINT fk_cm_label_analysis FOREIGN KEY(analysis_id) REFERENCES decision.candidate_memory_analysis_v1 (analysis_id) ON DELETE SET NULL, 
    CONSTRAINT fk_cm_label_appearance FOREIGN KEY(appearance_id) REFERENCES decision.candidate_memory_appearance (appearance_id) ON DELETE SET NULL, 
    CONSTRAINT fk_cm_label_instrument FOREIGN KEY(instrument_id) REFERENCES core.instrument_master (instrument_id), 
    CONSTRAINT fk_cm_label_superseded_by FOREIGN KEY(superseded_by_label_id) REFERENCES decision.candidate_memory_outcome_label_v1 (label_id)
);

CREATE INDEX idx_candidate_memory_label_status ON decision.candidate_memory_outcome_label_v1 (label_status, result_class, window_end_trading_day);

CREATE UNIQUE INDEX uq_candidate_memory_label_profile ON decision.candidate_memory_outcome_label_v1 (memory_id, label_profile_version, label_kind, entry_basis, target_return, stop_loss_return, label_window_days) WHERE label_status != 'superseded';

CREATE TABLE explain.candidate_memory_jarvis_explanation (
    explanation_id BIGSERIAL NOT NULL, 
    memory_id BIGINT NOT NULL, 
    analysis_id BIGINT, 
    label_id BIGINT, 
    prompt_mode VARCHAR(64) DEFAULT 'business_decision_translation' NOT NULL, 
    explanation_text TEXT NOT NULL, 
    used_evidence_refs JSONB NOT NULL, 
    source_gap_codes TEXT[] DEFAULT ARRAY[]::text[] NOT NULL, 
    generated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
    created_by VARCHAR(64) DEFAULT 'jarvis' NOT NULL, 
    CONSTRAINT pk_candidate_memory_jarvis_explanation PRIMARY KEY (explanation_id), 
    CONSTRAINT ck_candidate_memory_jarvis_explanation_used_refs_req CHECK (jsonb_typeof(used_evidence_refs) = 'array' AND jsonb_array_length(used_evidence_refs) > 0), 
    CONSTRAINT ck_candidate_memory_jarvis_explanation_safe_language CHECK (explanation_text !~ '(����|��׬|ȷ��׬Ǯ|ǿ������|��������|��֤����|�޷���)'), 
    CONSTRAINT fk_cm_jarvis_memory FOREIGN KEY(memory_id) REFERENCES decision.candidate_memory_entity (memory_id) ON DELETE CASCADE, 
    CONSTRAINT fk_cm_jarvis_analysis FOREIGN KEY(analysis_id) REFERENCES decision.candidate_memory_analysis_v1 (analysis_id) ON DELETE SET NULL, 
    CONSTRAINT fk_cm_jarvis_label FOREIGN KEY(label_id) REFERENCES decision.candidate_memory_outcome_label_v1 (label_id) ON DELETE SET NULL
);

CREATE INDEX idx_candidate_memory_jarvis_explanation_memory ON explain.candidate_memory_jarvis_explanation (memory_id, generated_at);

ALTER TABLE decision.recommendation_calibration_report ADD CONSTRAINT fk_rec_calibration_report_version FOREIGN KEY(version_id) REFERENCES decision.recommendation_version (version_id);

ALTER TABLE decision.recommendation_version ADD CONSTRAINT fk_recommendation_version_run_id_recommendation_run FOREIGN KEY(run_id) REFERENCES decision.recommendation_run (run_id);

ALTER TABLE decision.weight_profile ADD CONSTRAINT fk_weight_profile_source_rolling FOREIGN KEY(source_rolling_report_id) REFERENCES decision.recommendation_rolling_calibration_report (report_id);

ALTER TABLE decision.recommendation_version ADD CONSTRAINT fk_recommendation_version_weight_profile FOREIGN KEY(weight_profile_id) REFERENCES decision.weight_profile (weight_profile_id);

ALTER TABLE decision.weight_profile ADD CONSTRAINT fk_weight_profile_source_report FOREIGN KEY(source_report_id) REFERENCES decision.recommendation_calibration_report (report_id);

DO $$
DECLARE
    raw_table RECORD;
BEGIN
    FOR raw_table IN
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_type = 'BASE TABLE'
          AND table_schema LIKE 'raw\_%' ESCAPE '\'
    LOOP
        EXECUTE format(
            'ALTER TABLE %I.%I ADD COLUMN IF NOT EXISTS request_hash TEXT',
            raw_table.table_schema,
            raw_table.table_name
        );
    END LOOP;
END $$;

ALTER TABLE IF EXISTS governance.source_lineage_v1
    ADD COLUMN IF NOT EXISTS request_hash TEXT,
    ADD COLUMN IF NOT EXISTS response_row_hash TEXT;

DO $$
BEGIN
    IF to_regclass('governance.source_lineage_v1') IS NOT NULL THEN
        CREATE INDEX IF NOT EXISTS idx_source_lineage_request_hash_v1
            ON governance.source_lineage_v1 (request_hash)
            WHERE request_hash IS NOT NULL;
    END IF;
END $$;

DO $$
BEGIN
    IF to_regclass('governance.source_build_trigger_v1') IS NOT NULL
       AND to_regclass('governance.source_build_execution_result_v1') IS NOT NULL THEN
        UPDATE governance.source_build_trigger_v1 AS trigger
        SET status = 'succeeded',
            finished_at = result.finished_at
        FROM (
            SELECT trigger_id, MAX(finished_at) AS finished_at
            FROM governance.source_build_execution_result_v1
            WHERE status = 'succeeded'
            GROUP BY trigger_id
        ) AS result
        WHERE trigger.trigger_id = result.trigger_id
          AND trigger.status <> 'succeeded';
    END IF;
END $$;

INSERT INTO alembic_version (version_num) VALUES ('0001_current_baseline') RETURNING alembic_version.version_num;

COMMIT;

