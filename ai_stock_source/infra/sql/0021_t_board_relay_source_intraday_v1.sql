CREATE TABLE IF NOT EXISTS raw_eastmoney.trade_details_v1 (
    raw_id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'eastmoney',
    api_name TEXT NOT NULL DEFAULT 'trade_details',
    request_params_json JSONB NOT NULL,
    response_schema_hash TEXT,
    response_row_hash TEXT,
    batch_id TEXT,
    biz_key TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ,
    symbol TEXT,
    trade_date DATE,
    tick_time TIMESTAMPTZ NOT NULL,
    price NUMERIC,
    volume NUMERIC,
    amount NUMERIC,
    trade_count NUMERIC,
    side_code TEXT,
    side_label TEXT,
    provider_sequence INTEGER,
    raw_row_json JSONB NOT NULL,
    request_hash TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_raw_eastmoney_trade_details_hash
    ON raw_eastmoney.trade_details_v1(provider, api_name, request_hash, response_row_hash);
CREATE INDEX IF NOT EXISTS idx_raw_eastmoney_trade_details_symbol_time
    ON raw_eastmoney.trade_details_v1(symbol, tick_time);
CREATE INDEX IF NOT EXISTS idx_raw_eastmoney_trade_details_request_hash
    ON raw_eastmoney.trade_details_v1(request_hash);

ALTER TABLE raw_eastmoney.quote_snapshot_v1
    ADD COLUMN IF NOT EXISTS total_market_cap NUMERIC,
    ADD COLUMN IF NOT EXISTS float_market_cap NUMERIC,
    ADD COLUMN IF NOT EXISTS symbol TEXT,
    ADD COLUMN IF NOT EXISTS trade_date DATE,
    ADD COLUMN IF NOT EXISTS event_time TIMESTAMPTZ;

ALTER TABLE raw_eastmoney.minute_bars_v1
    ADD COLUMN IF NOT EXISTS trade_date DATE;

ALTER TABLE source.realtime_quote_v1
    ADD COLUMN IF NOT EXISTS trade_date DATE,
    ADD COLUMN IF NOT EXISTS open_price NUMERIC,
    ADD COLUMN IF NOT EXISTS prev_close_price NUMERIC,
    ADD COLUMN IF NOT EXISTS turnover_rate NUMERIC,
    ADD COLUMN IF NOT EXISTS change_amount NUMERIC,
    ADD COLUMN IF NOT EXISTS change_pct NUMERIC,
    ADD COLUMN IF NOT EXISTS total_market_cap NUMERIC,
    ADD COLUMN IF NOT EXISTS float_market_cap NUMERIC,
    ADD COLUMN IF NOT EXISTS source_quality_status TEXT NOT NULL DEFAULT 'usable',
    ADD COLUMN IF NOT EXISTS primary_provider TEXT,
    ADD COLUMN IF NOT EXISTS backup_provider TEXT,
    ADD COLUMN IF NOT EXISTS lineage_id TEXT,
    ADD COLUMN IF NOT EXISTS build_batch_id TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS uq_source_realtime_quote_symbol_time_provider
    ON source.realtime_quote_v1(instrument_id, event_time, provider);

CREATE UNIQUE INDEX IF NOT EXISTS uq_source_minute_bar_symbol_time_provider
    ON source.minute_bar_v1(instrument_id, bar_time, provider);

ALTER TABLE source.limit_event_v1
    ADD COLUMN IF NOT EXISTS close_on_limit_flag BOOLEAN,
    ADD COLUMN IF NOT EXISTS limit_open_count NUMERIC;

CREATE TABLE IF NOT EXISTS source.trade_tick_v1 (
    trade_tick_id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    trade_date DATE,
    tick_time TIMESTAMPTZ NOT NULL,
    price NUMERIC,
    volume NUMERIC,
    amount NUMERIC,
    trade_count NUMERIC,
    side_code TEXT,
    side_label TEXT,
    provider_sequence INTEGER NOT NULL DEFAULT 0,
    source_quality_status TEXT NOT NULL DEFAULT 'usable',
    primary_provider TEXT,
    backup_provider TEXT,
    provider TEXT NOT NULL,
    lineage_id TEXT,
    build_batch_id TEXT,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(symbol, tick_time, provider, provider_sequence)
);

CREATE INDEX IF NOT EXISTS idx_source_trade_tick_symbol_time
    ON source.trade_tick_v1(symbol, tick_time);
CREATE INDEX IF NOT EXISTS idx_source_trade_tick_trade_date
    ON source.trade_tick_v1(trade_date);
