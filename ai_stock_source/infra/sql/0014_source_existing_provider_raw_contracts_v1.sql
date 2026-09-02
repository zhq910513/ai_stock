-- Raw-interface contracts migrated from legacy market-data-service.
-- These keep existing public provider capabilities discoverable while adapters
-- are migrated behind source-data-service in later DS phases.

CREATE SCHEMA IF NOT EXISTS raw_eastmoney;
CREATE SCHEMA IF NOT EXISTS raw_tencent;
CREATE SCHEMA IF NOT EXISTS raw_sohu;
CREATE SCHEMA IF NOT EXISTS raw_baidu;
CREATE SCHEMA IF NOT EXISTS raw_sina;
CREATE SCHEMA IF NOT EXISTS raw_cninfo;

CREATE TABLE IF NOT EXISTS raw_eastmoney.quote_snapshot_v1 (
    raw_id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'eastmoney',
    api_name TEXT NOT NULL DEFAULT 'quote_snapshot',
    request_params_json JSONB NOT NULL,
    response_schema_hash TEXT,
    response_row_hash TEXT,
    batch_id TEXT,
    biz_key TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ,
    provider_symbol TEXT,
    provider_market TEXT,
    last_price NUMERIC,
    open_price NUMERIC,
    high_price NUMERIC,
    low_price NUMERIC,
    prev_close_price NUMERIC,
    volume NUMERIC,
    amount NUMERIC,
    turnover_rate NUMERIC,
    change_amount NUMERIC,
    change_pct NUMERIC,
    raw_row_json JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_eastmoney.daily_bars_v1 (
    raw_id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'eastmoney',
    api_name TEXT NOT NULL DEFAULT 'daily_bars',
    request_params_json JSONB NOT NULL,
    response_schema_hash TEXT,
    response_row_hash TEXT,
    batch_id TEXT,
    biz_key TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ,
    symbol TEXT,
    trade_date DATE NOT NULL,
    adjustment_mode TEXT,
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
    UNIQUE (symbol, trade_date, adjustment_mode, batch_id)
);

CREATE TABLE IF NOT EXISTS raw_eastmoney.minute_bars_v1 (
    raw_id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'eastmoney',
    api_name TEXT NOT NULL DEFAULT 'minute_bars',
    request_params_json JSONB NOT NULL,
    response_schema_hash TEXT,
    response_row_hash TEXT,
    batch_id TEXT,
    biz_key TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ,
    symbol TEXT,
    bar_time TIMESTAMPTZ NOT NULL,
    open_price NUMERIC,
    close_price NUMERIC,
    high_price NUMERIC,
    low_price NUMERIC,
    volume NUMERIC,
    amount NUMERIC,
    raw_row_json JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_eastmoney.moneyflow_stock_series_v1 (
    raw_id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'eastmoney',
    api_name TEXT NOT NULL DEFAULT 'moneyflow_stock_series',
    request_params_json JSONB NOT NULL,
    response_schema_hash TEXT,
    response_row_hash TEXT,
    batch_id TEXT,
    biz_key TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ,
    symbol TEXT,
    trade_date DATE,
    main_net_inflow NUMERIC,
    super_large_net_inflow NUMERIC,
    large_net_inflow NUMERIC,
    medium_net_inflow NUMERIC,
    small_net_inflow NUMERIC,
    raw_row_json JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_eastmoney.moneyflow_stock_rank_v1 (
    raw_id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'eastmoney',
    api_name TEXT NOT NULL DEFAULT 'moneyflow_stock_rank',
    request_params_json JSONB NOT NULL,
    response_schema_hash TEXT,
    response_row_hash TEXT,
    batch_id TEXT,
    biz_key TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ,
    symbol TEXT,
    stock_name TEXT,
    net_inflow NUMERIC,
    pct_chg NUMERIC,
    amount NUMERIC,
    raw_row_json JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_eastmoney.moneyflow_board_rank_v1 (
    raw_id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'eastmoney',
    api_name TEXT NOT NULL DEFAULT 'moneyflow_board_rank',
    request_params_json JSONB NOT NULL,
    response_schema_hash TEXT,
    response_row_hash TEXT,
    batch_id TEXT,
    biz_key TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ,
    board_code TEXT,
    board_name TEXT,
    net_inflow NUMERIC,
    pct_chg NUMERIC,
    amount NUMERIC,
    raw_row_json JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_eastmoney.stock_board_profile_v1 (
    raw_id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'eastmoney',
    api_name TEXT NOT NULL DEFAULT 'stock_board_profile',
    request_params_json JSONB NOT NULL,
    response_schema_hash TEXT,
    response_row_hash TEXT,
    batch_id TEXT,
    biz_key TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ,
    symbol TEXT,
    industry_name TEXT,
    region_name TEXT,
    concept_names TEXT,
    raw_row_json JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_eastmoney.theme_memberships_v1 (
    raw_id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'eastmoney',
    api_name TEXT NOT NULL DEFAULT 'theme_memberships',
    request_params_json JSONB NOT NULL,
    response_schema_hash TEXT,
    response_row_hash TEXT,
    batch_id TEXT,
    biz_key TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ,
    theme_code TEXT,
    symbol TEXT,
    stock_name TEXT,
    raw_row_json JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_eastmoney.billboard_trades_v1 (
    raw_id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'eastmoney',
    api_name TEXT NOT NULL DEFAULT 'billboard_trades',
    request_params_json JSONB NOT NULL,
    response_schema_hash TEXT,
    response_row_hash TEXT,
    batch_id TEXT,
    biz_key TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ,
    symbol TEXT,
    trade_date DATE,
    net_amount NUMERIC,
    reason_text TEXT,
    raw_row_json JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_tencent.daily_bars_v1 (LIKE raw_eastmoney.daily_bars_v1 INCLUDING ALL);

CREATE TABLE IF NOT EXISTS raw_sohu.daily_bars_v1 (
    raw_id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'sohu',
    api_name TEXT NOT NULL DEFAULT 'daily_bars',
    request_params_json JSONB NOT NULL,
    request_hash TEXT,
    response_schema_hash TEXT,
    response_row_hash TEXT,
    batch_id TEXT,
    biz_key TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ,
    symbol TEXT,
    trade_date DATE NOT NULL,
    adjustment_mode TEXT,
    open_price NUMERIC,
    close_price NUMERIC,
    high_price NUMERIC,
    low_price NUMERIC,
    volume NUMERIC,
    amount NUMERIC,
    pct_chg NUMERIC,
    change_amount NUMERIC,
    turnover_rate NUMERIC,
    provider_definition TEXT,
    raw_row_json JSONB NOT NULL,
    UNIQUE (symbol, trade_date, adjustment_mode, batch_id)
);

CREATE TABLE IF NOT EXISTS raw_tencent.auction_snapshot_v1 (
    raw_id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'tencent',
    api_name TEXT NOT NULL DEFAULT 'auction_snapshot',
    request_params_json JSONB NOT NULL,
    response_schema_hash TEXT,
    response_row_hash TEXT,
    batch_id TEXT,
    biz_key TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ,
    symbol TEXT,
    auction_price NUMERIC,
    auction_volume NUMERIC,
    auction_amount NUMERIC,
    raw_row_json JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_sina.auction_snapshot_v1 (LIKE raw_tencent.auction_snapshot_v1 INCLUDING ALL);

CREATE TABLE IF NOT EXISTS raw_cninfo.disclosure_direct_v1 (
    raw_id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'cninfo',
    api_name TEXT NOT NULL DEFAULT 'cninfo_disclosure_direct',
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

CREATE TABLE IF NOT EXISTS raw_baidu.finance_news_feed_v1 (
    raw_id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'baidu',
    api_name TEXT NOT NULL DEFAULT 'finance_news_feed',
    request_params_json JSONB NOT NULL,
    request_hash TEXT,
    response_schema_hash TEXT,
    response_row_hash TEXT,
    batch_id TEXT,
    biz_key TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ,
    provider_news_id TEXT,
    symbol TEXT,
    title TEXT NOT NULL,
    source_name TEXT,
    published_at TIMESTAMPTZ,
    event_type TEXT,
    url TEXT,
    tags_json JSONB,
    stock_refs_json JSONB,
    raw_row_json JSONB NOT NULL,
    UNIQUE (provider_news_id, batch_id)
);

CREATE INDEX IF NOT EXISTS idx_raw_eastmoney_daily_symbol_date ON raw_eastmoney.daily_bars_v1 (symbol, trade_date, adjustment_mode);
CREATE INDEX IF NOT EXISTS idx_raw_sohu_daily_symbol_date ON raw_sohu.daily_bars_v1 (symbol, trade_date, adjustment_mode);
CREATE INDEX IF NOT EXISTS idx_raw_sohu_daily_request_hash ON raw_sohu.daily_bars_v1 (request_hash);
CREATE INDEX IF NOT EXISTS idx_raw_eastmoney_moneyflow_symbol_date ON raw_eastmoney.moneyflow_stock_series_v1 (symbol, trade_date);
CREATE INDEX IF NOT EXISTS idx_raw_cninfo_disclosure_symbol_time ON raw_cninfo.disclosure_direct_v1 (symbol, published_at);
CREATE INDEX IF NOT EXISTS idx_raw_baidu_news_symbol_time ON raw_baidu.finance_news_feed_v1 (symbol, published_at);
CREATE INDEX IF NOT EXISTS idx_raw_baidu_news_id ON raw_baidu.finance_news_feed_v1 (provider_news_id);
CREATE INDEX IF NOT EXISTS idx_raw_baidu_news_request_hash ON raw_baidu.finance_news_feed_v1 (request_hash);
