-- source-data-service DS-2 reliability hardening.
-- Goal: make every canonical source field auditable, repairable and documented.
-- This migration is additive. It does not alter locked model schemas.

CREATE SCHEMA IF NOT EXISTS governance;

CREATE TABLE IF NOT EXISTS governance.source_field_contract_v1 (
    source_table_name TEXT NOT NULL,
    canonical_field_name TEXT NOT NULL,
    required_level TEXT NOT NULL,
    data_type TEXT NOT NULL,
    unit TEXT,
    price_adjustment_mode TEXT NOT NULL DEFAULT 'not_price',
    time_semantics TEXT NOT NULL,
    used_by_models_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    primary_provider TEXT NOT NULL,
    primary_api_name TEXT NOT NULL,
    backup_provider TEXT,
    backup_api_name TEXT,
    raw_table_name TEXT NOT NULL,
    field_quality_rules_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    online_policy TEXT NOT NULL,
    comment TEXT NOT NULL,
    contract_version TEXT NOT NULL DEFAULT 'source_field_contract_v1',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source_table_name, canonical_field_name, contract_version)
);

COMMENT ON TABLE governance.source_field_contract_v1 IS
'Canonical source-field contract. One row explains one model-consumable source field: meaning, unit, adjustment mode, time semantics, provider API, backup API, quality rules and online usage policy.';
COMMENT ON COLUMN governance.source_field_contract_v1.source_table_name IS 'Canonical source table read by models, for example source.daily_bar_v1. Models must not read raw_* tables directly.';
COMMENT ON COLUMN governance.source_field_contract_v1.canonical_field_name IS 'Canonical field name inside the source table. Model-owned terms such as signal/score/outcome are forbidden here.';
COMMENT ON COLUMN governance.source_field_contract_v1.required_level IS 'P0/P1/P2/research_only. P0 online fields block official model release if missing or unusable.';
COMMENT ON COLUMN governance.source_field_contract_v1.price_adjustment_mode IS 'raw/qfq/hfq/not_price/mixed. Raw prices are for execution/limit checks; adjusted prices are for long-window structure and shape calculations.';
COMMENT ON COLUMN governance.source_field_contract_v1.time_semantics IS 'Explains event/trade time vs available_at/captured_at. available_at must be <= model decision time before online usage.';
COMMENT ON COLUMN governance.source_field_contract_v1.field_quality_rules_json IS 'Field-level validation rules such as OHLC invariants, non-negative volume/amount, unit normalization and lineage requirement.';
COMMENT ON COLUMN governance.source_field_contract_v1.online_policy IS 'required/degradable/research_only. Required fields block official signals; degradable fields reduce confidence; research_only fields cannot affect official release.';

CREATE TABLE IF NOT EXISTS governance.provider_api_availability_v1 (
    provider TEXT NOT NULL,
    api_name TEXT NOT NULL,
    checked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    adapter_implemented BOOLEAN NOT NULL DEFAULT FALSE,
    optional_package_available BOOLEAN,
    connectivity_status TEXT NOT NULL DEFAULT 'unknown',
    circuit_state TEXT NOT NULL DEFAULT 'closed',
    last_success_at TIMESTAMPTZ,
    last_failure_at TIMESTAMPTZ,
    last_error TEXT,
    observed_latency_ms INTEGER,
    observed_row_count INTEGER,
    response_schema_hash TEXT,
    PRIMARY KEY (provider, api_name, checked_at)
);

COMMENT ON TABLE governance.provider_api_availability_v1 IS
'Provider/API runtime availability snapshots. Used by readiness checks and operations; provider outages must not stop source-data-service itself.';
COMMENT ON COLUMN governance.provider_api_availability_v1.response_schema_hash IS 'Hash of observed response columns. A changed hash requires field mapping review before canonical source build.';

CREATE TABLE IF NOT EXISTS governance.raw_ingest_batch_v1 (
    batch_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    api_name TEXT NOT NULL,
    raw_table_name TEXT NOT NULL,
    request_params_json JSONB NOT NULL,
    request_hash TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'running',
    row_count INTEGER NOT NULL DEFAULT 0,
    response_schema_hash TEXT,
    error_message TEXT
);

COMMENT ON TABLE governance.raw_ingest_batch_v1 IS
'Raw provider API ingestion batch. Every real provider call should create or update one batch record, allowing exact replay and gap repair.';
COMMENT ON COLUMN governance.raw_ingest_batch_v1.request_hash IS 'Deterministic hash of provider/api/request parameters. Enables idempotent ingestion and duplicate protection.';
COMMENT ON COLUMN governance.raw_ingest_batch_v1.raw_table_name IS 'Target raw_<provider>.<api>_v1 table. One provider API writes to one raw table.';

CREATE TABLE IF NOT EXISTS governance.source_canonical_build_rule_v1 (
    source_table_name TEXT NOT NULL,
    canonical_field_name TEXT NOT NULL,
    build_rule_code TEXT NOT NULL,
    build_rule_version TEXT NOT NULL,
    primary_raw_table_name TEXT NOT NULL,
    backup_raw_table_names_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    transform_sql_hint TEXT,
    transform_python_hint TEXT,
    quality_gate_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source_table_name, canonical_field_name, build_rule_version)
);

COMMENT ON TABLE governance.source_canonical_build_rule_v1 IS
'How canonical source fields are built from raw interface tables. The rule is intentionally separate from raw ingestion so data inspection can rebuild only affected fields.';
COMMENT ON COLUMN governance.source_canonical_build_rule_v1.quality_gate_json IS 'Build-time quality checks; failures must set source_quality_status to suspect/gap/rejected rather than silently filling values.';

-- Field-level source lineage should be queryable by table/field/key.
CREATE INDEX IF NOT EXISTS idx_source_lineage_lookup_v1
    ON governance.source_lineage_v1 (source_table_name, canonical_field_name, source_pk);

CREATE INDEX IF NOT EXISTS idx_source_field_contract_required_v1
    ON governance.source_field_contract_v1 (required_level, online_policy, source_table_name);

CREATE INDEX IF NOT EXISTS idx_provider_api_availability_latest_v1
    ON governance.provider_api_availability_v1 (provider, api_name, checked_at DESC);

CREATE INDEX IF NOT EXISTS idx_raw_ingest_batch_api_status_v1
    ON governance.raw_ingest_batch_v1 (provider, api_name, status, started_at DESC);

-- Representative comments on the most critical canonical fields. These comments
-- are intentionally repeated in README and source-data-service contracts.
COMMENT ON TABLE source.daily_bar_v1 IS
'Canonical unadjusted daily OHLCV fact table. Raw prices only: execution,涨跌停,可交易性 and true market facts. Long-window shape similarity should use source.adjusted_daily_bar_v1.';
COMMENT ON COLUMN source.daily_bar_v1.open_price IS 'Raw open price in CNY/share. Do not use as adjusted structure feature.';
COMMENT ON COLUMN source.daily_bar_v1.high_price IS 'Raw daily high. Must be >= open/close and >= low. Used for high-low envelope, true range and limit event validation.';
COMMENT ON COLUMN source.daily_bar_v1.low_price IS 'Raw daily low. Must be <= open/close and <= high. Used for support break, MAE and tradability validation.';
COMMENT ON COLUMN source.daily_bar_v1.close_price IS 'Raw close price. Used for actual return, limit/execution checks and cross-provider OHLC validation.';
COMMENT ON COLUMN source.daily_bar_v1.pre_close_price IS 'Raw previous close. Required for limit price calculation and pct_chg recomputation.';
COMMENT ON COLUMN source.daily_bar_v1.volume IS 'Provider-normalized daily volume. Must be non-negative; provider-native unit must remain traceable in raw_row_json.';
COMMENT ON COLUMN source.daily_bar_v1.amount IS 'Provider-normalized daily turnover amount. Must be non-negative; source build records unit transform.';
COMMENT ON COLUMN source.daily_bar_v1.available_at IS 'Earliest time this market fact was available to the system. Online models may only use records with available_at <= decision_time.';

COMMENT ON TABLE source.adjusted_daily_bar_v1 IS
'Canonical adjusted daily OHLCV fact table. Used for structure, drawdown, low-valley, shape signature and long-window research. Never use adjusted prices for real trade execution or limit checks.';
COMMENT ON COLUMN source.adjusted_daily_bar_v1.adjustment_mode IS 'qfq/hfq. Model three v1 uses qfq by default unless source capability audit promotes another policy.';
COMMENT ON COLUMN source.adjusted_daily_bar_v1.adjusted_close IS 'Adjusted close used for low-valley shape matching, drawdown and trend slope calculations.';
COMMENT ON COLUMN source.adjusted_daily_bar_v1.source_quality_status IS 'usable/research_only/gap/suspect/stale/rejected. Suspect adjusted prices must block official ambush release and stay research-only.';

COMMENT ON TABLE source.trade_status_v1 IS
'Canonical historical tradability/ST/suspension/delisting-risk facts. Missing P0 trade status blocks official model signals.';
COMMENT ON COLUMN source.trade_status_v1.is_st IS 'Historical ST flag. Required for exclusion and correct price limit rule.';
COMMENT ON COLUMN source.trade_status_v1.is_suspended IS 'Historical suspension flag. Suspended rows are not tradable and cannot enter official release.';
COMMENT ON COLUMN source.trade_status_v1.is_delisting_risk IS 'Delisting-risk proxy. Free sources may be incomplete; missing evidence must be visible in source_quality_status.';

COMMENT ON TABLE source.limit_price_v1 IS
'Canonical daily涨跌停 price table. Primary build is internal from raw pre_close and trading rules; external APIs validate edge cases.';
COMMENT ON COLUMN source.limit_price_v1.limit_rule IS 'Applied rule such as normal_10pct, st_5pct, chinext_20pct or new_stock_special. Rule choice must be auditable.';

COMMENT ON TABLE governance.source_gap_v1 IS
'Detected canonical source data gaps. Each gap should map to provider/api/raw_table/request_params so repair is precise and limited to missing evidence.';
COMMENT ON TABLE governance.source_repair_task_v1 IS
'Executable provider-level repair task generated from source_gap_v1. It must fetch raw interface rows first, then trigger source canonical rebuild.';
