-- source-data-service DS-1 raw-interface first schema.
-- Principle: one provider API -> one raw interface table. Models never read raw_*.

CREATE SCHEMA IF NOT EXISTS raw_baostock;
CREATE SCHEMA IF NOT EXISTS raw_akshare;
CREATE SCHEMA IF NOT EXISTS raw_tushare;
CREATE SCHEMA IF NOT EXISTS raw_eastmoney;
CREATE SCHEMA IF NOT EXISTS raw_baidu;
CREATE SCHEMA IF NOT EXISTS source;
CREATE SCHEMA IF NOT EXISTS governance;

CREATE TABLE IF NOT EXISTS governance.provider_api_registry_v1 (
    provider TEXT NOT NULL,
    api_name TEXT NOT NULL,
    api_function TEXT NOT NULL,
    raw_table_name TEXT NOT NULL,
    request_template_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    response_fields_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    canonical_targets_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    frequency TEXT NOT NULL,
    is_free BOOLEAN NOT NULL DEFAULT TRUE,
    requires_token BOOLEAN NOT NULL DEFAULT FALSE,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    priority INTEGER NOT NULL DEFAULT 100,
    supports_repair BOOLEAN NOT NULL DEFAULT TRUE,
    rate_limit_note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (provider, api_name)
);

CREATE TABLE IF NOT EXISTS governance.raw_ingest_batch_v1 (
    batch_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    api_name TEXT NOT NULL,
    raw_table_name TEXT NOT NULL,
    request_params_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    request_hash TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'running',
    error_code TEXT,
    error_message TEXT,
    row_count INTEGER NOT NULL DEFAULT 0
);

-- Raw table common convention:
-- raw_id, provider, api_name, request_params_json, request_hash, response_schema_hash,
-- response_row_hash, batch_id, biz_key, captured_at, available_at, raw_row_json.

CREATE TABLE IF NOT EXISTS raw_baostock.query_all_stock_v1 (
    raw_id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'baostock',
    api_name TEXT NOT NULL DEFAULT 'query_all_stock',
    request_params_json JSONB NOT NULL,
    response_schema_hash TEXT,
    response_row_hash TEXT,
    batch_id TEXT,
    biz_key TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ,
    day DATE,
    code TEXT,
    trade_status TEXT,
    code_name TEXT,
    raw_row_json JSONB NOT NULL,
    UNIQUE (day, code, batch_id)
);

CREATE TABLE IF NOT EXISTS raw_baostock.query_stock_basic_v1 (
    raw_id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'baostock',
    api_name TEXT NOT NULL DEFAULT 'query_stock_basic',
    request_params_json JSONB NOT NULL,
    response_schema_hash TEXT,
    response_row_hash TEXT,
    batch_id TEXT,
    biz_key TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ,
    code TEXT NOT NULL,
    code_name TEXT,
    ipo_date DATE,
    out_date DATE,
    security_type TEXT,
    status TEXT,
    raw_row_json JSONB NOT NULL,
    UNIQUE (code, batch_id)
);

CREATE TABLE IF NOT EXISTS raw_baostock.query_trade_dates_v1 (
    raw_id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'baostock',
    api_name TEXT NOT NULL DEFAULT 'query_trade_dates',
    request_params_json JSONB NOT NULL,
    response_schema_hash TEXT,
    response_row_hash TEXT,
    batch_id TEXT,
    biz_key TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ,
    calendar_date DATE NOT NULL,
    is_trading_day BOOLEAN NOT NULL,
    raw_row_json JSONB NOT NULL,
    UNIQUE (calendar_date, batch_id)
);

CREATE TABLE IF NOT EXISTS raw_baostock.query_history_k_data_plus_daily_raw_v1 (
    raw_id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'baostock',
    api_name TEXT NOT NULL DEFAULT 'query_history_k_data_plus_daily_raw',
    request_params_json JSONB NOT NULL,
    response_schema_hash TEXT,
    response_row_hash TEXT,
    batch_id TEXT,
    biz_key TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ,
    trade_date DATE NOT NULL,
    code TEXT NOT NULL,
    open_price NUMERIC,
    high_price NUMERIC,
    low_price NUMERIC,
    close_price NUMERIC,
    pre_close_price NUMERIC,
    volume NUMERIC,
    amount NUMERIC,
    adjustflag TEXT NOT NULL DEFAULT '3',
    turnover_rate NUMERIC,
    trade_status TEXT,
    pct_chg NUMERIC,
    is_st BOOLEAN,
    raw_row_json JSONB NOT NULL,
    UNIQUE (code, trade_date, adjustflag, batch_id)
);

CREATE TABLE IF NOT EXISTS raw_baostock.query_history_k_data_plus_daily_qfq_v1 (
    LIKE raw_baostock.query_history_k_data_plus_daily_raw_v1 INCLUDING ALL
);

CREATE TABLE IF NOT EXISTS raw_baostock.query_history_k_data_plus_daily_hfq_v1 (
    LIKE raw_baostock.query_history_k_data_plus_daily_raw_v1 INCLUDING ALL
);

CREATE TABLE IF NOT EXISTS raw_baostock.query_adjust_factor_v1 (
    raw_id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'baostock',
    api_name TEXT NOT NULL DEFAULT 'query_adjust_factor',
    request_params_json JSONB NOT NULL,
    response_schema_hash TEXT,
    response_row_hash TEXT,
    batch_id TEXT,
    biz_key TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ,
    code TEXT NOT NULL,
    divid_operate_date DATE,
    fore_adjust_factor NUMERIC,
    back_adjust_factor NUMERIC,
    adjust_factor NUMERIC,
    raw_row_json JSONB NOT NULL,
    UNIQUE (code, divid_operate_date, batch_id)
);

CREATE TABLE IF NOT EXISTS raw_baostock.query_stock_industry_v1 (
    raw_id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'baostock',
    api_name TEXT NOT NULL DEFAULT 'query_stock_industry',
    request_params_json JSONB NOT NULL,
    response_schema_hash TEXT,
    response_row_hash TEXT,
    batch_id TEXT,
    biz_key TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ,
    update_date DATE,
    code TEXT NOT NULL,
    code_name TEXT,
    industry TEXT,
    industry_classification TEXT,
    raw_row_json JSONB NOT NULL,
    UNIQUE (update_date, code, industry_classification, batch_id)
);

CREATE TABLE IF NOT EXISTS raw_akshare.stock_zh_a_spot_em_v1 (
    raw_id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'akshare',
    api_name TEXT NOT NULL DEFAULT 'stock_zh_a_spot_em',
    request_params_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    response_schema_hash TEXT,
    response_row_hash TEXT,
    batch_id TEXT,
    biz_key TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ,
    code TEXT NOT NULL,
    name TEXT,
    last_price NUMERIC,
    change_pct NUMERIC,
    change_amount NUMERIC,
    volume NUMERIC,
    amount NUMERIC,
    amplitude NUMERIC,
    high_price NUMERIC,
    low_price NUMERIC,
    open_price NUMERIC,
    prev_close_price NUMERIC,
    volume_ratio NUMERIC,
    turnover_rate NUMERIC,
    total_market_value NUMERIC,
    float_market_value NUMERIC,
    raw_row_json JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_akshare.stock_zh_a_hist_daily_raw_v1 (
    raw_id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'akshare',
    api_name TEXT NOT NULL DEFAULT 'stock_zh_a_hist_daily_raw',
    request_params_json JSONB NOT NULL,
    response_schema_hash TEXT,
    response_row_hash TEXT,
    batch_id TEXT,
    biz_key TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ,
    symbol TEXT NOT NULL,
    trade_date DATE NOT NULL,
    open_price NUMERIC,
    close_price NUMERIC,
    high_price NUMERIC,
    low_price NUMERIC,
    volume NUMERIC,
    amount NUMERIC,
    amplitude NUMERIC,
    pct_chg NUMERIC,
    change_amount NUMERIC,
    turnover_rate NUMERIC,
    adjust TEXT NOT NULL DEFAULT '',
    raw_row_json JSONB NOT NULL,
    UNIQUE (symbol, trade_date, adjust, batch_id)
);

CREATE TABLE IF NOT EXISTS raw_akshare.stock_zh_a_hist_daily_qfq_v1 (
    LIKE raw_akshare.stock_zh_a_hist_daily_raw_v1 INCLUDING ALL
);

CREATE TABLE IF NOT EXISTS raw_akshare.stock_zh_a_hist_daily_hfq_v1 (
    LIKE raw_akshare.stock_zh_a_hist_daily_raw_v1 INCLUDING ALL
);

CREATE TABLE IF NOT EXISTS raw_akshare.stock_zh_a_hist_weekly_raw_v1 (
    LIKE raw_akshare.stock_zh_a_hist_daily_raw_v1 INCLUDING ALL
);

CREATE TABLE IF NOT EXISTS raw_akshare.stock_board_industry_name_em_v1 (
    raw_id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'akshare',
    api_name TEXT NOT NULL DEFAULT 'stock_board_industry_name_em',
    request_params_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    response_schema_hash TEXT,
    response_row_hash TEXT,
    batch_id TEXT,
    biz_key TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ,
    board_code TEXT,
    board_name TEXT NOT NULL,
    last_price NUMERIC,
    change_amount NUMERIC,
    change_pct NUMERIC,
    total_market_value NUMERIC,
    turnover_rate NUMERIC,
    rise_count INTEGER,
    fall_count INTEGER,
    leader_name TEXT,
    leader_change_pct NUMERIC,
    raw_row_json JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_akshare.stock_board_industry_cons_em_v1 (
    raw_id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'akshare',
    api_name TEXT NOT NULL DEFAULT 'stock_board_industry_cons_em',
    request_params_json JSONB NOT NULL,
    response_schema_hash TEXT,
    response_row_hash TEXT,
    batch_id TEXT,
    biz_key TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ,
    board_name TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT,
    last_price NUMERIC,
    change_pct NUMERIC,
    change_amount NUMERIC,
    volume NUMERIC,
    amount NUMERIC,
    amplitude NUMERIC,
    high_price NUMERIC,
    low_price NUMERIC,
    open_price NUMERIC,
    prev_close_price NUMERIC,
    turnover_rate NUMERIC,
    raw_row_json JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_akshare.stock_board_industry_hist_em_v1 (
    raw_id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'akshare',
    api_name TEXT NOT NULL DEFAULT 'stock_board_industry_hist_em',
    request_params_json JSONB NOT NULL,
    response_schema_hash TEXT,
    response_row_hash TEXT,
    batch_id TEXT,
    biz_key TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ,
    board_name TEXT NOT NULL,
    trade_date DATE NOT NULL,
    open_price NUMERIC,
    close_price NUMERIC,
    high_price NUMERIC,
    low_price NUMERIC,
    pct_chg NUMERIC,
    change_amount NUMERIC,
    volume NUMERIC,
    amount NUMERIC,
    amplitude NUMERIC,
    turnover_rate NUMERIC,
    raw_row_json JSONB NOT NULL,
    UNIQUE (board_name, trade_date, batch_id)
);

CREATE TABLE IF NOT EXISTS raw_akshare.stock_fund_flow_individual_realtime_v1 (
    raw_id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'akshare',
    api_name TEXT NOT NULL DEFAULT 'stock_fund_flow_individual_realtime',
    request_params_json JSONB NOT NULL,
    response_schema_hash TEXT,
    response_row_hash TEXT,
    batch_id TEXT,
    biz_key TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ,
    code TEXT NOT NULL,
    name TEXT,
    last_price NUMERIC,
    change_pct NUMERIC,
    turnover_rate NUMERIC,
    inflow_amount NUMERIC,
    outflow_amount NUMERIC,
    net_amount NUMERIC,
    amount NUMERIC,
    large_order_inflow NUMERIC,
    raw_row_json JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_akshare.index_zh_a_hist_v1 (
    raw_id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'akshare',
    api_name TEXT NOT NULL DEFAULT 'index_zh_a_hist',
    request_params_json JSONB NOT NULL,
    response_schema_hash TEXT,
    response_row_hash TEXT,
    batch_id TEXT,
    biz_key TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ,
    index_code TEXT NOT NULL,
    trade_date DATE NOT NULL,
    open_price NUMERIC,
    close_price NUMERIC,
    high_price NUMERIC,
    low_price NUMERIC,
    volume NUMERIC,
    amount NUMERIC,
    amplitude NUMERIC,
    pct_chg NUMERIC,
    change_amount NUMERIC,
    turnover_rate NUMERIC,
    raw_row_json JSONB NOT NULL,
    UNIQUE (index_code, trade_date, batch_id)
);

CREATE TABLE IF NOT EXISTS raw_akshare.stock_zh_a_disclosure_report_cninfo_v1 (
    raw_id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'akshare',
    api_name TEXT NOT NULL DEFAULT 'stock_zh_a_disclosure_report_cninfo',
    request_params_json JSONB NOT NULL,
    response_schema_hash TEXT,
    response_row_hash TEXT,
    batch_id TEXT,
    biz_key TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ,
    symbol TEXT,
    short_name TEXT,
    title TEXT,
    published_at TIMESTAMPTZ,
    event_type TEXT,
    url TEXT,
    raw_row_json JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_tushare.stock_basic_v1 (
    raw_id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'tushare',
    api_name TEXT NOT NULL DEFAULT 'stock_basic',
    request_params_json JSONB NOT NULL,
    response_schema_hash TEXT,
    response_row_hash TEXT,
    batch_id TEXT,
    biz_key TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ,
    ts_code TEXT NOT NULL,
    symbol TEXT,
    name TEXT,
    area TEXT,
    industry TEXT,
    market TEXT,
    exchange TEXT,
    list_status TEXT,
    list_date DATE,
    delist_date DATE,
    is_hs TEXT,
    raw_row_json JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_tushare.trade_cal_v1 (
    raw_id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'tushare',
    api_name TEXT NOT NULL DEFAULT 'trade_cal',
    request_params_json JSONB NOT NULL,
    response_schema_hash TEXT,
    response_row_hash TEXT,
    batch_id TEXT,
    biz_key TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ,
    exchange TEXT,
    cal_date DATE NOT NULL,
    is_open BOOLEAN,
    pretrade_date DATE,
    raw_row_json JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_tushare.daily_v1 (
    raw_id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'tushare',
    api_name TEXT NOT NULL DEFAULT 'daily',
    request_params_json JSONB NOT NULL,
    response_schema_hash TEXT,
    response_row_hash TEXT,
    batch_id TEXT,
    biz_key TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ,
    ts_code TEXT NOT NULL,
    trade_date DATE NOT NULL,
    open_price NUMERIC,
    high_price NUMERIC,
    low_price NUMERIC,
    close_price NUMERIC,
    pre_close_price NUMERIC,
    change_amount NUMERIC,
    pct_chg NUMERIC,
    vol NUMERIC,
    amount_k NUMERIC,
    raw_row_json JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_tushare.adj_factor_v1 (
    raw_id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'tushare',
    api_name TEXT NOT NULL DEFAULT 'adj_factor',
    request_params_json JSONB NOT NULL,
    response_schema_hash TEXT,
    response_row_hash TEXT,
    batch_id TEXT,
    biz_key TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ,
    ts_code TEXT NOT NULL,
    trade_date DATE NOT NULL,
    adj_factor NUMERIC,
    raw_row_json JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_tushare.moneyflow_v1 (
    raw_id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'tushare',
    api_name TEXT NOT NULL DEFAULT 'moneyflow',
    request_params_json JSONB NOT NULL,
    response_schema_hash TEXT,
    response_row_hash TEXT,
    batch_id TEXT,
    biz_key TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ,
    ts_code TEXT NOT NULL,
    trade_date DATE NOT NULL,
    net_mf_amount NUMERIC,
    raw_row_json JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_tushare.stk_limit_v1 (
    raw_id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'tushare',
    api_name TEXT NOT NULL DEFAULT 'stk_limit',
    request_params_json JSONB NOT NULL,
    response_schema_hash TEXT,
    response_row_hash TEXT,
    batch_id TEXT,
    biz_key TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ,
    ts_code TEXT NOT NULL,
    trade_date DATE NOT NULL,
    pre_close NUMERIC,
    up_limit NUMERIC,
    down_limit NUMERIC,
    raw_row_json JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_raw_baostock_daily_raw_code_date ON raw_baostock.query_history_k_data_plus_daily_raw_v1 (code, trade_date);
CREATE INDEX IF NOT EXISTS idx_raw_baostock_daily_qfq_code_date ON raw_baostock.query_history_k_data_plus_daily_qfq_v1 (code, trade_date);
CREATE INDEX IF NOT EXISTS idx_raw_akshare_daily_raw_symbol_date ON raw_akshare.stock_zh_a_hist_daily_raw_v1 (symbol, trade_date);
CREATE INDEX IF NOT EXISTS idx_raw_akshare_daily_qfq_symbol_date ON raw_akshare.stock_zh_a_hist_daily_qfq_v1 (symbol, trade_date);
