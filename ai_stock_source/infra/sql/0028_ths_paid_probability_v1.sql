-- 0028_ths_paid_probability_v1.sql
-- Purpose: credentialed THS paid next-day probability source closure.
-- Cookie values are stored only in governance.ths_paid_probability_cookie_v1
-- and must never enter raw request_params_json, request_hash, raw_provider_row,
-- frontend responses, logs or documentation.

CREATE SCHEMA IF NOT EXISTS raw_ths;
CREATE SCHEMA IF NOT EXISTS source;
CREATE SCHEMA IF NOT EXISTS governance;

CREATE TABLE IF NOT EXISTS governance.ths_paid_probability_cookie_v1 (
    credential_id BIGSERIAL PRIMARY KEY,
    credential_version TEXT NOT NULL UNIQUE,
    user_cookie TEXT NOT NULL,
    userid_cookie TEXT NOT NULL,
    user_masked TEXT NOT NULL,
    userid_masked TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending_probe',
    is_active BOOLEAN NOT NULL DEFAULT true,
    updated_by TEXT,
    last_checked_at TIMESTAMPTZ,
    last_success_at TIMESTAMPTZ,
    last_failure_at TIMESTAMPTZ,
    failure_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_ths_paid_probability_cookie_status_v1 CHECK (
        status IN ('pending_probe','valid','expired','invalid')
    )
);

CREATE INDEX IF NOT EXISTS idx_ths_paid_probability_cookie_active_v1
    ON governance.ths_paid_probability_cookie_v1 (is_active, updated_at DESC);

CREATE TABLE IF NOT EXISTS raw_ths.paid_limit_up_probability_v1 (
    raw_id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'ths',
    api_name TEXT NOT NULL DEFAULT 'paid_limit_up_probability',
    request_params_json JSONB NOT NULL,
    request_hash TEXT,
    response_schema_hash TEXT,
    response_row_hash TEXT,
    batch_id TEXT,
    biz_key TEXT,
    trade_date DATE NOT NULL,
    code TEXT,
    stock_code TEXT,
    symbol TEXT NOT NULL,
    paid_limit_up_probability NUMERIC(12,6),
    status_code INTEGER,
    status_msg TEXT,
    credential_version TEXT,
    endpoint TEXT,
    available_at TIMESTAMPTZ,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    raw_provider_row JSONB NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT ck_raw_ths_paid_probability_range_v1 CHECK (
        paid_limit_up_probability IS NULL
        OR (paid_limit_up_probability >= 0 AND paid_limit_up_probability <= 100)
    ),
    CONSTRAINT ck_raw_ths_paid_probability_no_cookie_params_v1 CHECK (
        NOT (
            request_params_json ? 'user'
            OR request_params_json ? 'userid'
            OR request_params_json ? 'cookie'
            OR request_params_json ? 'cookies'
        )
    ),
    CONSTRAINT ck_raw_ths_paid_probability_no_cookie_payload_v1 CHECK (
        NOT (
            raw_provider_row ? 'user'
            OR raw_provider_row ? 'userid'
            OR raw_provider_row ? 'cookie'
            OR raw_provider_row ? 'cookies'
        )
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_raw_ths_paid_probability_response_hash_v1
    ON raw_ths.paid_limit_up_probability_v1 (request_hash, response_row_hash)
    WHERE request_hash IS NOT NULL AND response_row_hash IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_raw_ths_paid_probability_symbol_day_v1
    ON raw_ths.paid_limit_up_probability_v1 (symbol, trade_date DESC);

CREATE INDEX IF NOT EXISTS idx_raw_ths_paid_probability_request_hash_v1
    ON raw_ths.paid_limit_up_probability_v1 (request_hash);

CREATE TABLE IF NOT EXISTS source.ths_paid_limit_up_probability_v1 (
    symbol TEXT NOT NULL,
    trade_date DATE NOT NULL,
    paid_limit_up_probability NUMERIC(12,6) NOT NULL,
    source_quality_status TEXT NOT NULL DEFAULT 'usable',
    primary_provider TEXT NOT NULL DEFAULT 'ths',
    build_batch_id TEXT,
    captured_at TIMESTAMPTZ,
    available_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_ths_paid_limit_up_probability_v1 PRIMARY KEY (symbol, trade_date),
    CONSTRAINT ck_ths_paid_limit_up_probability_range_v1 CHECK (
        paid_limit_up_probability >= 0 AND paid_limit_up_probability <= 100
    )
);

CREATE INDEX IF NOT EXISTS idx_source_ths_paid_probability_day_quality_v1
    ON source.ths_paid_limit_up_probability_v1 (trade_date DESC, source_quality_status, symbol);

CREATE TABLE IF NOT EXISTS governance.ths_paid_probability_batch_status_v1 (
    trade_date DATE PRIMARY KEY,
    status TEXT NOT NULL,
    candidate_count INTEGER NOT NULL DEFAULT 0,
    fetched_count INTEGER NOT NULL DEFAULT 0,
    missing_symbols JSONB NOT NULL DEFAULT '[]'::jsonb,
    deadline_at TIMESTAMPTZ,
    next_trade_date DATE,
    cookie_status TEXT NOT NULL DEFAULT 'missing',
    message TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_ths_paid_probability_batch_status_v1 CHECK (
        status IN (
            'no_candidates',
            'pending_cookie',
            'fetching',
            'partial',
            'ready',
            'cookie_expired',
            'abandoned_no_probability_before_deadline'
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_ths_paid_probability_batch_status_updated_v1
    ON governance.ths_paid_probability_batch_status_v1 (status, updated_at DESC);

COMMENT ON TABLE governance.ths_paid_probability_cookie_v1 IS
'Active THS paid probability cookies. Values are DB/runtime-only secrets and are masked in every API/frontend response.';
COMMENT ON TABLE raw_ths.paid_limit_up_probability_v1 IS
'Raw THS paid next-day probability response. request_params_json stores only date, stock_code and credential_version reference, never cookie values.';
COMMENT ON TABLE source.ths_paid_limit_up_probability_v1 IS
'Canonical source fact for THS paid next-day limit-up probability. Missing facts block or abandon candidate batches after the next trading day 09:00 deadline.';
COMMENT ON TABLE governance.ths_paid_probability_batch_status_v1 IS
'Per candidate trade_date paid probability closure status and next-trading-day 09:00 abandonment guard.';
