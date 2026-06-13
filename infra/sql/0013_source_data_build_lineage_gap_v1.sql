-- Canonical source tables, lineage, gap detection and repair tasks.
-- Models read source.* only. raw_* is provider-owned evidence and never used directly by models.

CREATE SCHEMA IF NOT EXISTS source;
CREATE SCHEMA IF NOT EXISTS governance;

CREATE TABLE IF NOT EXISTS governance.source_table_requirement_v1 (
    source_table_name TEXT NOT NULL,
    canonical_field_name TEXT NOT NULL,
    required_level TEXT NOT NULL,
    used_by_models JSONB NOT NULL DEFAULT '[]'::jsonb,
    required_for_online BOOLEAN NOT NULL DEFAULT FALSE,
    required_for_backtest BOOLEAN NOT NULL DEFAULT TRUE,
    minimum_coverage_rate NUMERIC NOT NULL DEFAULT 0.99,
    primary_provider TEXT NOT NULL,
    primary_api_name TEXT NOT NULL,
    backup_provider TEXT,
    backup_api_name TEXT,
    repair_raw_table_name TEXT NOT NULL,
    description TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source_table_name, canonical_field_name)
);

CREATE TABLE IF NOT EXISTS governance.provider_field_mapping_v1 (
    provider TEXT NOT NULL,
    api_name TEXT NOT NULL,
    raw_table_name TEXT NOT NULL,
    raw_field_name TEXT NOT NULL,
    canonical_table_name TEXT NOT NULL,
    canonical_field_name TEXT NOT NULL,
    unit_transform TEXT,
    dtype_transform TEXT,
    null_policy TEXT NOT NULL DEFAULT 'preserve_null',
    mapping_status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (provider, api_name, raw_field_name, canonical_table_name, canonical_field_name)
);

CREATE TABLE IF NOT EXISTS governance.source_build_batch_v1 (
    build_batch_id TEXT PRIMARY KEY,
    source_table_name TEXT NOT NULL,
    build_version TEXT NOT NULL,
    input_watermark_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'running',
    row_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS source.stock_master_v1 (
    symbol TEXT PRIMARY KEY,
    provider_symbol TEXT,
    stock_name TEXT,
    exchange TEXT,
    market TEXT,
    list_status TEXT,
    ipo_date DATE,
    delist_date DATE,
    security_type TEXT,
    primary_provider TEXT NOT NULL,
    backup_provider TEXT,
    source_quality_status TEXT NOT NULL DEFAULT 'usable',
    lineage_id TEXT,
    build_batch_id TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS source.stock_universe_daily_v1 (
    trade_date DATE NOT NULL,
    symbol TEXT NOT NULL,
    stock_name TEXT,
    trade_status TEXT,
    is_tradable BOOLEAN,
    is_st BOOLEAN,
    source_quality_status TEXT NOT NULL DEFAULT 'usable',
    primary_provider TEXT NOT NULL,
    lineage_id TEXT,
    build_batch_id TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (trade_date, symbol)
);

CREATE TABLE IF NOT EXISTS source.trade_calendar_v1 (
    calendar_date DATE PRIMARY KEY,
    is_trading_day BOOLEAN NOT NULL,
    exchange TEXT NOT NULL DEFAULT 'SSE_SZSE',
    pretrade_date DATE,
    source_quality_status TEXT NOT NULL DEFAULT 'usable',
    primary_provider TEXT NOT NULL,
    backup_provider TEXT,
    lineage_id TEXT,
    build_batch_id TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS source.daily_bar_v1 (
    symbol TEXT NOT NULL,
    trade_date DATE NOT NULL,
    open_price NUMERIC,
    high_price NUMERIC,
    low_price NUMERIC,
    close_price NUMERIC,
    pre_close_price NUMERIC,
    volume NUMERIC,
    amount NUMERIC,
    pct_chg NUMERIC,
    turnover_rate NUMERIC,
    source_quality_status TEXT NOT NULL DEFAULT 'usable',
    primary_provider TEXT NOT NULL,
    backup_provider TEXT,
    lineage_id TEXT,
    build_batch_id TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, trade_date)
);

ALTER TABLE source.daily_bar_v1
    ADD COLUMN IF NOT EXISTS trade_date DATE;
ALTER TABLE source.daily_bar_v1
    ADD COLUMN IF NOT EXISTS pre_close_price NUMERIC;
ALTER TABLE source.daily_bar_v1
    ADD COLUMN IF NOT EXISTS pct_chg NUMERIC;
ALTER TABLE source.daily_bar_v1
    ADD COLUMN IF NOT EXISTS source_quality_status TEXT NOT NULL DEFAULT 'usable';
ALTER TABLE source.daily_bar_v1
    ADD COLUMN IF NOT EXISTS primary_provider TEXT;
ALTER TABLE source.daily_bar_v1
    ADD COLUMN IF NOT EXISTS backup_provider TEXT;
ALTER TABLE source.daily_bar_v1
    ADD COLUMN IF NOT EXISTS lineage_id TEXT;
ALTER TABLE source.daily_bar_v1
    ADD COLUMN IF NOT EXISTS build_batch_id TEXT;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'source'
          AND table_name = 'daily_bar_v1'
          AND column_name = 'trading_day'
    ) THEN
        EXECUTE 'UPDATE source.daily_bar_v1 SET trade_date = trading_day WHERE trade_date IS NULL';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'source'
          AND table_name = 'daily_bar_v1'
          AND column_name = 'provider'
    ) THEN
        EXECUTE 'UPDATE source.daily_bar_v1 SET primary_provider = provider WHERE primary_provider IS NULL';
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS source.adjusted_daily_bar_v1 (
    symbol TEXT NOT NULL,
    trade_date DATE NOT NULL,
    adjustment_mode TEXT NOT NULL DEFAULT 'qfq',
    adjusted_open NUMERIC,
    adjusted_high NUMERIC,
    adjusted_low NUMERIC,
    adjusted_close NUMERIC,
    volume NUMERIC,
    amount NUMERIC,
    adjustment_source TEXT,
    source_quality_status TEXT NOT NULL DEFAULT 'usable',
    primary_provider TEXT NOT NULL,
    backup_provider TEXT,
    lineage_id TEXT,
    build_batch_id TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, trade_date, adjustment_mode)
);

CREATE TABLE IF NOT EXISTS source.adjustment_factor_v1 (
    symbol TEXT NOT NULL,
    effective_date DATE NOT NULL,
    adjustment_factor NUMERIC,
    fore_adjust_factor NUMERIC,
    back_adjust_factor NUMERIC,
    source_quality_status TEXT NOT NULL DEFAULT 'usable',
    primary_provider TEXT NOT NULL,
    backup_provider TEXT,
    lineage_id TEXT,
    build_batch_id TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, effective_date)
);

CREATE TABLE IF NOT EXISTS source.weekly_bar_v1 (
    symbol TEXT NOT NULL,
    week_start_date DATE NOT NULL,
    week_end_date DATE NOT NULL,
    adjustment_mode TEXT NOT NULL DEFAULT 'raw',
    open_price NUMERIC,
    high_price NUMERIC,
    low_price NUMERIC,
    close_price NUMERIC,
    volume NUMERIC,
    amount NUMERIC,
    source_quality_status TEXT NOT NULL DEFAULT 'usable',
    build_batch_id TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, week_end_date, adjustment_mode)
);

CREATE TABLE IF NOT EXISTS source.trade_status_v1 (
    symbol TEXT NOT NULL,
    trade_date DATE NOT NULL,
    is_tradable BOOLEAN,
    is_suspended BOOLEAN,
    is_st BOOLEAN,
    is_delisting_risk BOOLEAN,
    raw_status TEXT,
    source_quality_status TEXT NOT NULL DEFAULT 'usable',
    primary_provider TEXT NOT NULL,
    backup_provider TEXT,
    lineage_id TEXT,
    build_batch_id TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, trade_date)
);

CREATE TABLE IF NOT EXISTS source.limit_price_v1 (
    symbol TEXT NOT NULL,
    trade_date DATE NOT NULL,
    pre_close_price NUMERIC,
    up_limit_price NUMERIC,
    down_limit_price NUMERIC,
    limit_rule TEXT,
    source_quality_status TEXT NOT NULL DEFAULT 'usable',
    primary_provider TEXT NOT NULL DEFAULT 'internal',
    backup_provider TEXT,
    lineage_id TEXT,
    build_batch_id TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, trade_date)
);

CREATE TABLE IF NOT EXISTS source.limit_event_v1 (
    symbol TEXT NOT NULL,
    trade_date DATE NOT NULL,
    limit_event_type TEXT,
    is_one_word_board BOOLEAN,
    is_break_limit BOOLEAN,
    source_quality_status TEXT NOT NULL DEFAULT 'usable',
    primary_provider TEXT NOT NULL DEFAULT 'internal',
    backup_provider TEXT,
    lineage_id TEXT,
    build_batch_id TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, trade_date, limit_event_type)
);

CREATE TABLE IF NOT EXISTS source.index_daily_bar_v1 (
    index_code TEXT NOT NULL,
    trade_date DATE NOT NULL,
    open_price NUMERIC,
    high_price NUMERIC,
    low_price NUMERIC,
    close_price NUMERIC,
    volume NUMERIC,
    amount NUMERIC,
    pct_chg NUMERIC,
    source_quality_status TEXT NOT NULL DEFAULT 'usable',
    primary_provider TEXT NOT NULL,
    backup_provider TEXT,
    lineage_id TEXT,
    build_batch_id TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (index_code, trade_date)
);

CREATE TABLE IF NOT EXISTS source.board_master_v1 (
    board_code TEXT,
    board_name TEXT NOT NULL,
    board_type TEXT NOT NULL DEFAULT 'industry',
    provider TEXT NOT NULL,
    source_quality_status TEXT NOT NULL DEFAULT 'usable',
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (provider, board_name, board_type)
);

CREATE TABLE IF NOT EXISTS source.stock_board_membership_v1 (
    symbol TEXT NOT NULL,
    board_name TEXT NOT NULL,
    board_type TEXT NOT NULL DEFAULT 'industry',
    provider TEXT NOT NULL,
    effective_from DATE,
    effective_to DATE,
    membership_time_mode TEXT NOT NULL DEFAULT 'current_snapshot',
    source_quality_status TEXT NOT NULL DEFAULT 'research_only',
    lineage_id TEXT,
    build_batch_id TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, board_name, board_type, provider)
);

CREATE TABLE IF NOT EXISTS source.board_daily_bar_v1 (
    board_name TEXT NOT NULL,
    board_type TEXT NOT NULL DEFAULT 'industry',
    trade_date DATE NOT NULL,
    open_price NUMERIC,
    high_price NUMERIC,
    low_price NUMERIC,
    close_price NUMERIC,
    volume NUMERIC,
    amount NUMERIC,
    pct_chg NUMERIC,
    turnover_rate NUMERIC,
    source_quality_status TEXT NOT NULL DEFAULT 'usable',
    primary_provider TEXT NOT NULL,
    backup_provider TEXT,
    lineage_id TEXT,
    build_batch_id TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (board_name, board_type, trade_date)
);

CREATE TABLE IF NOT EXISTS source.stock_moneyflow_daily_v1 (
    symbol TEXT NOT NULL,
    trade_date DATE NOT NULL,
    main_net_inflow NUMERIC,
    super_large_net_inflow NUMERIC,
    large_net_inflow NUMERIC,
    medium_net_inflow NUMERIC,
    small_net_inflow NUMERIC,
    provider_definition TEXT,
    source_quality_status TEXT NOT NULL DEFAULT 'research_only',
    primary_provider TEXT NOT NULL,
    backup_provider TEXT,
    lineage_id TEXT,
    build_batch_id TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, trade_date, primary_provider)
);

CREATE TABLE IF NOT EXISTS source.event_news_v1 (
    event_id TEXT PRIMARY KEY,
    symbol TEXT,
    title TEXT NOT NULL,
    event_type TEXT,
    event_time TIMESTAMPTZ,
    published_at TIMESTAMPTZ,
    available_at TIMESTAMPTZ NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    provider TEXT NOT NULL,
    url TEXT,
    source_quality_status TEXT NOT NULL DEFAULT 'research_only',
    lineage_id TEXT,
    build_batch_id TEXT
);

CREATE TABLE IF NOT EXISTS governance.source_lineage_v1 (
    lineage_id TEXT NOT NULL,
    source_table_name TEXT NOT NULL,
    source_pk TEXT NOT NULL,
    canonical_field_name TEXT NOT NULL,
    provider TEXT NOT NULL,
    api_name TEXT NOT NULL,
    raw_table_name TEXT NOT NULL,
    raw_id BIGINT,
    batch_id TEXT,
    build_batch_id TEXT,
    confidence_score NUMERIC NOT NULL DEFAULT 1.0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (lineage_id, canonical_field_name, provider, api_name)
);

CREATE TABLE IF NOT EXISTS governance.source_gap_v1 (
    gap_id TEXT PRIMARY KEY,
    source_table_name TEXT NOT NULL,
    canonical_field_name TEXT NOT NULL,
    symbol TEXT,
    trade_date DATE,
    gap_type TEXT NOT NULL,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    repair_provider TEXT,
    repair_api_name TEXT,
    repair_params_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    repair_status TEXT NOT NULL DEFAULT 'pending',
    severity TEXT NOT NULL DEFAULT 'medium'
);

CREATE TABLE IF NOT EXISTS governance.source_repair_task_v1 (
    task_id TEXT PRIMARY KEY,
    gap_id TEXT REFERENCES governance.source_gap_v1(gap_id),
    provider TEXT NOT NULL,
    api_name TEXT NOT NULL,
    raw_table_name TEXT NOT NULL,
    request_params_json JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS governance.source_probe_run_v1 (
    probe_run_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    api_name TEXT NOT NULL,
    request_params_json JSONB NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'running'
);

CREATE TABLE IF NOT EXISTS governance.source_probe_result_v1 (
    probe_run_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    api_name TEXT NOT NULL,
    raw_table_name TEXT NOT NULL,
    connectivity_pass BOOLEAN NOT NULL,
    schema_pass BOOLEAN NOT NULL,
    expected_fields_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    observed_fields_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    missing_fields_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    row_count INTEGER NOT NULL DEFAULT 0,
    usable_for_source_table BOOLEAN NOT NULL DEFAULT FALSE,
    usable_for_model_online BOOLEAN NOT NULL DEFAULT FALSE,
    usable_for_research_only BOOLEAN NOT NULL DEFAULT TRUE,
    reject_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (probe_run_id, provider, api_name)
);

CREATE INDEX IF NOT EXISTS idx_source_daily_bar_symbol_date ON source.daily_bar_v1 (symbol, trade_date);
CREATE INDEX IF NOT EXISTS idx_source_adjusted_daily_bar_symbol_date ON source.adjusted_daily_bar_v1 (symbol, trade_date, adjustment_mode);
CREATE INDEX IF NOT EXISTS idx_source_gap_status ON governance.source_gap_v1 (repair_status, source_table_name, canonical_field_name);
CREATE INDEX IF NOT EXISTS idx_source_repair_task_status ON governance.source_repair_task_v1 (status, provider, api_name);
