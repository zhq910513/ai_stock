-- Expand source-data-service raw contracts for public providers migrated from
-- the legacy candidate/market/news services. These tables are raw-interface
-- contracts only; source canonical writes still require quality/build/lineage.

CREATE SCHEMA IF NOT EXISTS raw_ths;
CREATE SCHEMA IF NOT EXISTS raw_coingecko;
CREATE SCHEMA IF NOT EXISTS raw_yahoo;
CREATE SCHEMA IF NOT EXISTS raw_jin10;
CREATE SCHEMA IF NOT EXISTS raw_tencent;
CREATE SCHEMA IF NOT EXISTS raw_eastmoney;

ALTER TABLE IF EXISTS raw_eastmoney.quote_snapshot_v1 ADD COLUMN IF NOT EXISTS request_hash TEXT;
ALTER TABLE IF EXISTS raw_eastmoney.daily_bars_v1 ADD COLUMN IF NOT EXISTS request_hash TEXT;
ALTER TABLE IF EXISTS raw_eastmoney.minute_bars_v1 ADD COLUMN IF NOT EXISTS request_hash TEXT;
ALTER TABLE IF EXISTS raw_tencent.auction_snapshot_v1 ADD COLUMN IF NOT EXISTS request_hash TEXT;
ALTER TABLE IF EXISTS raw_tencent.daily_bars_v1 ADD COLUMN IF NOT EXISTS request_hash TEXT;
ALTER TABLE IF EXISTS raw_sina.auction_snapshot_v1 ADD COLUMN IF NOT EXISTS request_hash TEXT;

CREATE TABLE IF NOT EXISTS raw_eastmoney.stock_universe_v1 (
    raw_id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'eastmoney',
    api_name TEXT NOT NULL DEFAULT 'stock_universe',
    request_params_json JSONB NOT NULL,
    request_hash TEXT,
    response_schema_hash TEXT,
    response_row_hash TEXT,
    batch_id TEXT,
    biz_key TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ,
    symbol TEXT,
    code TEXT,
    name TEXT,
    stock_name TEXT,
    secid TEXT,
    provider_symbol TEXT,
    provider_market TEXT,
    exchange TEXT,
    board TEXT,
    segment_name TEXT,
    trade_date DATE,
    list_date DATE,
    ipo_date DATE,
    list_status TEXT,
    delist_date DATE,
    rank_no INTEGER,
    provider_definition TEXT,
    raw_row_json JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_eastmoney.auction_snapshot_v1 (
    raw_id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'eastmoney',
    api_name TEXT NOT NULL DEFAULT 'auction_snapshot',
    request_params_json JSONB NOT NULL,
    request_hash TEXT,
    response_schema_hash TEXT,
    response_row_hash TEXT,
    batch_id TEXT,
    biz_key TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ,
    symbol TEXT,
    trade_date DATE,
    event_time TIMESTAMPTZ,
    secid TEXT,
    provider_symbol TEXT,
    provider_market TEXT,
    price NUMERIC,
    volume NUMERIC,
    amount NUMERIC,
    prev_close_price NUMERIC,
    best_bid_price NUMERIC,
    best_bid_volume NUMERIC,
    best_ask_price NUMERIC,
    best_ask_volume NUMERIC,
    provider_definition TEXT,
    raw_row_json JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_tencent.quote_snapshot_v1 (
    raw_id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'tencent',
    api_name TEXT NOT NULL DEFAULT 'quote_snapshot',
    request_params_json JSONB NOT NULL,
    request_hash TEXT,
    response_schema_hash TEXT,
    response_row_hash TEXT,
    batch_id TEXT,
    biz_key TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ,
    symbol TEXT,
    trade_date DATE,
    event_time TIMESTAMPTZ,
    provider_code TEXT,
    name TEXT,
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
    response_field_count INTEGER,
    raw_text TEXT,
    raw_row_json JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_tencent.minute_bars_v1 (
    raw_id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'tencent',
    api_name TEXT NOT NULL DEFAULT 'minute_bars',
    request_params_json JSONB NOT NULL,
    request_hash TEXT,
    response_schema_hash TEXT,
    response_row_hash TEXT,
    batch_id TEXT,
    biz_key TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ,
    symbol TEXT,
    trade_date DATE,
    bar_time TIMESTAMPTZ,
    event_time TIMESTAMPTZ,
    provider_code TEXT,
    open NUMERIC,
    high NUMERIC,
    low NUMERIC,
    close NUMERIC,
    volume NUMERIC,
    amount NUMERIC,
    provider_native_amount NUMERIC,
    provider_definition TEXT,
    raw_row_json JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_eastmoney.northbound_summary_v1 (
    raw_id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'eastmoney',
    api_name TEXT NOT NULL DEFAULT 'northbound_summary',
    request_params_json JSONB NOT NULL,
    request_hash TEXT,
    response_schema_hash TEXT,
    response_row_hash TEXT,
    batch_id TEXT,
    biz_key TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ,
    trade_date DATE,
    mutual_type TEXT,
    deal_amount NUMERIC,
    net_buy_amount NUMERIC,
    buy_amount NUMERIC,
    sell_amount NUMERIC,
    quota_balance_text TEXT,
    raw_provider_row JSONB,
    raw_row_json JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_eastmoney.lpr_rates_v1 (
    raw_id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'eastmoney',
    api_name TEXT NOT NULL DEFAULT 'lpr_rates',
    request_params_json JSONB NOT NULL,
    request_hash TEXT,
    response_schema_hash TEXT,
    response_row_hash TEXT,
    batch_id TEXT,
    biz_key TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ,
    asset_code TEXT,
    asset_name TEXT,
    trade_date DATE,
    last_price NUMERIC,
    rate_1y NUMERIC,
    rate_5y NUMERIC,
    extra_metrics_json JSONB,
    raw_provider_row JSONB,
    raw_row_json JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_ths.limit_up_pool_v1 (
    raw_id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'ths',
    api_name TEXT NOT NULL DEFAULT 'limit_up_pool',
    request_params_json JSONB NOT NULL,
    request_hash TEXT,
    response_schema_hash TEXT,
    response_row_hash TEXT,
    batch_id TEXT,
    biz_key TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ,
    symbol TEXT,
    trade_date DATE,
    code TEXT,
    provider_market TEXT,
    name TEXT,
    rank_no INTEGER,
    latest_price NUMERIC,
    change_pct NUMERIC,
    turnover_rate NUMERIC,
    limit_up_type TEXT,
    reason_type TEXT,
    first_limit_up_time TIMESTAMPTZ,
    last_limit_up_time TIMESTAMPTZ,
    limit_open_count NUMERIC,
    order_volume NUMERIC,
    order_amount NUMERIC,
    float_market_cap NUMERIC,
    total_market_cap NUMERIC,
    is_again_limit BOOLEAN,
    is_new BOOLEAN,
    high_days TEXT,
    high_days_value NUMERIC,
    limit_up_stage NUMERIC,
    close_on_limit_flag BOOLEAN,
    is_one_word_board BOOLEAN,
    is_break_limit BOOLEAN,
    limit_event_type TEXT,
    raw_row_json JSONB NOT NULL,
    UNIQUE (symbol, trade_date, limit_event_type, batch_id)
);

CREATE TABLE IF NOT EXISTS raw_ths.trade_status_v1 (
    raw_id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'ths',
    api_name TEXT NOT NULL DEFAULT 'trade_status',
    request_params_json JSONB NOT NULL,
    request_hash TEXT,
    response_schema_hash TEXT,
    response_row_hash TEXT,
    batch_id TEXT,
    biz_key TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ,
    trade_date DATE,
    endpoint TEXT,
    payload_status TEXT,
    payload_json JSONB,
    raw_row_json JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_ths.zhangting5_reasons_v1 (
    raw_id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'ths',
    api_name TEXT NOT NULL DEFAULT 'zhangting5_reasons',
    request_params_json JSONB NOT NULL,
    request_hash TEXT,
    response_schema_hash TEXT,
    response_row_hash TEXT,
    batch_id TEXT,
    biz_key TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ,
    symbol TEXT,
    trade_date DATE,
    code TEXT,
    provider_market TEXT,
    name TEXT,
    rank_no INTEGER,
    reason_title TEXT,
    reason_summary TEXT,
    published_at_text TEXT,
    event_type TEXT,
    url TEXT,
    raw_row_json JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_ths.market_state_overview_v1 (LIKE raw_ths.trade_status_v1 INCLUDING ALL);
ALTER TABLE IF EXISTS raw_ths.market_state_overview_v1 ALTER COLUMN api_name SET DEFAULT 'market_state_overview';

CREATE TABLE IF NOT EXISTS raw_ths.market_capital_v1 (LIKE raw_ths.trade_status_v1 INCLUDING ALL);
ALTER TABLE IF EXISTS raw_ths.market_capital_v1 ALTER COLUMN api_name SET DEFAULT 'market_capital';

CREATE TABLE IF NOT EXISTS raw_ths.wind_vane_stock_v1 (
    raw_id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'ths',
    api_name TEXT NOT NULL DEFAULT 'wind_vane_stock',
    request_params_json JSONB NOT NULL,
    request_hash TEXT,
    response_schema_hash TEXT,
    response_row_hash TEXT,
    batch_id TEXT,
    biz_key TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ,
    symbol TEXT,
    trade_date DATE,
    code TEXT,
    tab_name TEXT,
    rank_no INTEGER,
    name TEXT,
    price NUMERIC,
    change_pct NUMERIC,
    reason TEXT,
    raw_row_json JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_ths.hot_block_list_v1 (
    raw_id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'ths',
    api_name TEXT NOT NULL DEFAULT 'hot_block_list',
    request_params_json JSONB NOT NULL,
    request_hash TEXT,
    response_schema_hash TEXT,
    response_row_hash TEXT,
    batch_id TEXT,
    biz_key TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ,
    trade_date DATE,
    block_code TEXT,
    block_name TEXT,
    block_type TEXT,
    provider_market TEXT,
    rank_no INTEGER,
    change_pct NUMERIC,
    raw_row_json JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_ths.stock_concepts_v1 (
    raw_id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'ths',
    api_name TEXT NOT NULL DEFAULT 'stock_concepts',
    request_params_json JSONB NOT NULL,
    request_hash TEXT,
    response_schema_hash TEXT,
    response_row_hash TEXT,
    batch_id TEXT,
    biz_key TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ,
    symbol TEXT,
    code TEXT,
    concept_id TEXT,
    concept_name TEXT,
    rank_no INTEGER,
    provider_market TEXT,
    concept_explain TEXT,
    raw_row_json JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_ths.stock_focusday_v1 (
    raw_id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'ths',
    api_name TEXT NOT NULL DEFAULT 'stock_focusday',
    request_params_json JSONB NOT NULL,
    request_hash TEXT,
    response_schema_hash TEXT,
    response_row_hash TEXT,
    batch_id TEXT,
    biz_key TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ,
    symbol TEXT,
    code TEXT,
    rank NUMERIC,
    total NUMERIC,
    description TEXT,
    payload_json JSONB,
    raw_row_json JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_coingecko.simple_price_v1 (
    raw_id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'coingecko',
    api_name TEXT NOT NULL DEFAULT 'simple_price',
    request_params_json JSONB NOT NULL,
    request_hash TEXT,
    response_schema_hash TEXT,
    response_row_hash TEXT,
    batch_id TEXT,
    biz_key TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ,
    asset_id TEXT,
    asset_code TEXT,
    asset_name TEXT,
    asset_class TEXT,
    quote_currency TEXT,
    last_price NUMERIC,
    change_pct_24h NUMERIC,
    market_cap NUMERIC,
    volume_24h NUMERIC,
    raw_row_json JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_coingecko.global_market_v1 (
    raw_id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'coingecko',
    api_name TEXT NOT NULL DEFAULT 'global_market',
    request_params_json JSONB NOT NULL,
    request_hash TEXT,
    response_schema_hash TEXT,
    response_row_hash TEXT,
    batch_id TEXT,
    biz_key TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ,
    metric_code TEXT,
    asset_code TEXT,
    asset_class TEXT,
    quote_currency TEXT,
    last_price NUMERIC,
    market_cap NUMERIC,
    volume_24h NUMERIC,
    change_pct_24h NUMERIC,
    dominance_pct NUMERIC,
    updated_at TEXT,
    raw_row_json JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_yahoo.chart_v1 (
    raw_id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'yahoo',
    api_name TEXT NOT NULL DEFAULT 'chart',
    request_params_json JSONB NOT NULL,
    request_hash TEXT,
    response_schema_hash TEXT,
    response_row_hash TEXT,
    batch_id TEXT,
    biz_key TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ,
    provider_symbol TEXT,
    asset_code TEXT,
    asset_name TEXT,
    asset_class TEXT,
    quote_currency TEXT,
    observed_at TIMESTAMPTZ,
    last_price NUMERIC,
    change_pct NUMERIC,
    previous_close NUMERIC,
    exchange_name TEXT,
    market_state TEXT,
    instrument_type TEXT,
    raw_row_json JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_jin10.public_flash_v1 (
    raw_id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'jin10',
    api_name TEXT NOT NULL DEFAULT 'public_flash',
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
    body TEXT,
    source_name TEXT,
    published_at TIMESTAMPTZ,
    event_type TEXT,
    url TEXT,
    tags_json JSONB,
    stock_refs_json JSONB,
    raw_row_json JSONB NOT NULL,
    UNIQUE (provider_news_id, batch_id)
);

CREATE INDEX IF NOT EXISTS idx_raw_ths_limit_up_symbol_date ON raw_ths.limit_up_pool_v1 (symbol, trade_date, limit_event_type);
CREATE INDEX IF NOT EXISTS idx_raw_ths_limit_up_request_hash ON raw_ths.limit_up_pool_v1 (request_hash);
CREATE INDEX IF NOT EXISTS idx_raw_ths_zt5_symbol ON raw_ths.zhangting5_reasons_v1 (symbol, trade_date);
CREATE INDEX IF NOT EXISTS idx_raw_eastmoney_stock_universe_symbol ON raw_eastmoney.stock_universe_v1 (symbol, trade_date);
CREATE INDEX IF NOT EXISTS idx_raw_eastmoney_stock_universe_request_hash ON raw_eastmoney.stock_universe_v1 (request_hash);
CREATE INDEX IF NOT EXISTS idx_raw_eastmoney_auction_symbol_time ON raw_eastmoney.auction_snapshot_v1 (symbol, event_time);
CREATE INDEX IF NOT EXISTS idx_raw_eastmoney_auction_request_hash ON raw_eastmoney.auction_snapshot_v1 (request_hash);
CREATE INDEX IF NOT EXISTS idx_raw_tencent_quote_symbol_time ON raw_tencent.quote_snapshot_v1 (symbol, event_time);
CREATE INDEX IF NOT EXISTS idx_raw_tencent_quote_request_hash ON raw_tencent.quote_snapshot_v1 (request_hash);
CREATE INDEX IF NOT EXISTS idx_raw_tencent_minute_symbol_time ON raw_tencent.minute_bars_v1 (symbol, bar_time);
CREATE INDEX IF NOT EXISTS idx_raw_tencent_minute_request_hash ON raw_tencent.minute_bars_v1 (request_hash);
CREATE INDEX IF NOT EXISTS idx_raw_eastmoney_northbound_date ON raw_eastmoney.northbound_summary_v1 (trade_date);
CREATE INDEX IF NOT EXISTS idx_raw_eastmoney_lpr_date ON raw_eastmoney.lpr_rates_v1 (trade_date, asset_code);
CREATE INDEX IF NOT EXISTS idx_raw_coingecko_asset ON raw_coingecko.simple_price_v1 (asset_code, captured_at);
CREATE INDEX IF NOT EXISTS idx_raw_yahoo_asset ON raw_yahoo.chart_v1 (asset_code, observed_at);
CREATE INDEX IF NOT EXISTS idx_raw_jin10_news_time ON raw_jin10.public_flash_v1 (published_at);
CREATE INDEX IF NOT EXISTS idx_raw_jin10_news_request_hash ON raw_jin10.public_flash_v1 (request_hash);
