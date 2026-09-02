-- 0025_source_data_foundation_indexes_v1.sql
-- Purpose: first-launch source foundation read-path indexes. These indexes do
-- not change source facts, provider contracts, model scores, release gates or
-- scheduler behavior. They cover the shared table paths used by source
-- preflight, data-inspector startup/core closure, frontend read models and
-- model owner payload assembly.

CREATE SCHEMA IF NOT EXISTS source;
CREATE SCHEMA IF NOT EXISTS governance;

-- 0002 created the first trade calendar contract with legacy names
-- (trading_day/is_open/prev_trading_day). Keep that physical history intact,
-- but make the current source-data contract visible for first-launch builds.
ALTER TABLE source.trade_calendar_v1 ADD COLUMN IF NOT EXISTS calendar_date DATE;
ALTER TABLE source.trade_calendar_v1 ADD COLUMN IF NOT EXISTS is_trading_day BOOLEAN;
ALTER TABLE source.trade_calendar_v1 ADD COLUMN IF NOT EXISTS exchange TEXT DEFAULT 'SSE_SZSE';
ALTER TABLE source.trade_calendar_v1 ADD COLUMN IF NOT EXISTS pretrade_date DATE;
ALTER TABLE source.trade_calendar_v1 ADD COLUMN IF NOT EXISTS source_quality_status TEXT NOT NULL DEFAULT 'usable';
ALTER TABLE source.trade_calendar_v1 ADD COLUMN IF NOT EXISTS primary_provider TEXT;
ALTER TABLE source.trade_calendar_v1 ADD COLUMN IF NOT EXISTS backup_provider TEXT;
ALTER TABLE source.trade_calendar_v1 ADD COLUMN IF NOT EXISTS lineage_id TEXT;
ALTER TABLE source.trade_calendar_v1 ADD COLUMN IF NOT EXISTS build_batch_id TEXT;
ALTER TABLE source.trade_calendar_v1 ADD COLUMN IF NOT EXISTS captured_at TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE source.trade_calendar_v1 ADD COLUMN IF NOT EXISTS available_at TIMESTAMPTZ NOT NULL DEFAULT now();

-- P0 first-launch calendar and identity lookups.
CREATE INDEX IF NOT EXISTS idx_source_trade_calendar_open_pretrade_v1
    ON source.trade_calendar_v1 (is_trading_day, calendar_date, pretrade_date);
CREATE INDEX IF NOT EXISTS idx_source_stock_master_exchange_status_v1
    ON source.stock_master_v1 (exchange, list_status, symbol);
CREATE INDEX IF NOT EXISTS idx_source_stock_master_provider_symbol_v1
    ON source.stock_master_v1 (provider_symbol)
    WHERE provider_symbol IS NOT NULL;

-- Shared daily universe and source-row lookup paths.
CREATE INDEX IF NOT EXISTS idx_source_stock_universe_symbol_day_v1
    ON source.stock_universe_daily_v1 (symbol, trade_date DESC);
CREATE INDEX IF NOT EXISTS idx_source_stock_universe_day_status_v1
    ON source.stock_universe_daily_v1 (trade_date, is_tradable, trade_status, symbol);
CREATE INDEX IF NOT EXISTS idx_source_daily_bar_day_quality_v1
    ON source.daily_bar_v1 (trade_date, source_quality_status, symbol);
CREATE INDEX IF NOT EXISTS idx_source_daily_bar_available_v1
    ON source.daily_bar_v1 (available_at DESC, trade_date, symbol);
CREATE INDEX IF NOT EXISTS idx_source_adjusted_daily_day_quality_v1
    ON source.adjusted_daily_bar_v1 (trade_date, adjustment_mode, source_quality_status, symbol);
CREATE INDEX IF NOT EXISTS idx_source_trade_status_day_flags_v1
    ON source.trade_status_v1 (trade_date, is_tradable, is_suspended, is_st, symbol);

-- Limit-up and model-four read paths.
CREATE INDEX IF NOT EXISTS idx_source_limit_price_day_quality_v1
    ON source.limit_price_v1 (trade_date, source_quality_status, symbol);
CREATE INDEX IF NOT EXISTS idx_source_limit_event_day_type_close_v1
    ON source.limit_event_v1 (trade_date, limit_event_type, close_on_limit_flag, symbol);
CREATE INDEX IF NOT EXISTS idx_source_limit_event_symbol_day_v1
    ON source.limit_event_v1 (symbol, trade_date DESC, limit_event_type);
CREATE INDEX IF NOT EXISTS idx_source_realtime_quote_symbol_day_time_v1
    ON source.realtime_quote_v1 (symbol, trade_date, event_time DESC)
    WHERE trade_date IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_source_minute_bar_symbol_time_latest_v1
    ON source.minute_bar_v1 (symbol, bar_time DESC);
CREATE INDEX IF NOT EXISTS idx_source_trade_tick_symbol_day_time_v1
    ON source.trade_tick_v1 (symbol, trade_date, tick_time DESC);

-- P1/P2 shared context paths.
CREATE INDEX IF NOT EXISTS idx_source_moneyflow_day_quality_v1
    ON source.stock_moneyflow_daily_v1 (trade_date, source_quality_status, symbol);
CREATE INDEX IF NOT EXISTS idx_source_event_news_symbol_available_v1
    ON source.event_news_v1 (symbol, available_at DESC)
    WHERE symbol IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_source_event_news_type_time_v1
    ON source.event_news_v1 (event_type, published_at DESC);

-- Governance audit and queue paths used by readiness, repair and closure.
CREATE INDEX IF NOT EXISTS idx_source_lineage_duplicate_audit_v1
    ON governance.source_lineage_v1 (
        source_table_name,
        source_pk,
        canonical_field_name,
        provider,
        api_name,
        raw_table_name,
        raw_id
    );
CREATE INDEX IF NOT EXISTS idx_source_lineage_build_batch_v1
    ON governance.source_lineage_v1 (build_batch_id, source_table_name)
    WHERE build_batch_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_raw_fetch_job_release_due_v1
    ON governance.raw_fetch_job_item_v1 (queue_name, status, priority, created_at)
    WHERE queue_name = 'urgent_release_gate_queue';
CREATE INDEX IF NOT EXISTS idx_source_build_trigger_symbol_day_v1
    ON governance.source_build_trigger_v1 (source_table_name, symbol, trade_date, status);
CREATE INDEX IF NOT EXISTS idx_source_canonical_write_symbol_day_v1
    ON governance.source_canonical_write_audit_v1 (source_table_name, symbol, trade_date, created_at DESC);

COMMENT ON INDEX source.idx_source_trade_calendar_open_pretrade_v1 IS
'First-launch P0 calendar path for scheduler materialization, T+N labels and previous-trading-day lookup.';
COMMENT ON INDEX source.idx_source_limit_event_day_type_close_v1 IS
'Candidate-page and T-board relay day scan path for close-on-limit limit_up/t_board_limit_up events.';
COMMENT ON INDEX governance.idx_source_lineage_duplicate_audit_v1 IS
'Data-inspector source_lineage duplicate audit path; preserves append-only lineage while making duplicate observation cheap.';
