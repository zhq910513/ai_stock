-- 0017_source_data_concurrent_fetch_orchestration_v1.sql
-- Purpose: production-grade producer/consumer raw-interface fetch orchestration
-- for source-data-service. This migration records provider/API concurrency
-- policy, durable fetch batches, durable job items, callbacks, provider runtime
-- status and source-build triggers. It lets data-inspector-service repair the
-- exact missing field by enqueueing the exact provider API/raw table request
-- without losing task state.

CREATE SCHEMA IF NOT EXISTS governance;

CREATE TABLE IF NOT EXISTS governance.provider_rate_limit_policy_v1 (
    provider TEXT NOT NULL,
    api_name TEXT NOT NULL,
    max_concurrency INTEGER NOT NULL CHECK (max_concurrency > 0),
    requests_per_minute INTEGER CHECK (requests_per_minute IS NULL OR requests_per_minute > 0),
    min_interval_ms INTEGER NOT NULL DEFAULT 0 CHECK (min_interval_ms >= 0),
    timeout_ms INTEGER NOT NULL DEFAULT 12000 CHECK (timeout_ms >= 100),
    max_retry_count INTEGER NOT NULL DEFAULT 2 CHECK (max_retry_count >= 0),
    retry_backoff_policy TEXT NOT NULL DEFAULT 'exponential',
    circuit_breaker_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    circuit_open_seconds INTEGER NOT NULL DEFAULT 60 CHECK (circuit_open_seconds > 0),
    priority_weight INTEGER NOT NULL DEFAULT 100 CHECK (priority_weight > 0),
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    comment TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (provider, api_name)
);

COMMENT ON TABLE governance.provider_rate_limit_policy_v1 IS
'Provider/API-level concurrency and rate-limit policy. It prevents unbounded stock-by-stock fetch loops from delaying P0 model data or banning free public providers.';
COMMENT ON COLUMN governance.provider_rate_limit_policy_v1.max_concurrency IS
'Max concurrent in-flight jobs for this provider API. Concurrency must be conservative for free public providers.';
COMMENT ON COLUMN governance.provider_rate_limit_policy_v1.requests_per_minute IS
'Optional upper request rate; NULL means manually controlled by max_concurrency/min_interval_ms only.';
COMMENT ON COLUMN governance.provider_rate_limit_policy_v1.circuit_breaker_enabled IS
'When true, repeated provider failures open circuit and force callers to use backup routes instead of crashing source-data-service.';

CREATE TABLE IF NOT EXISTS governance.raw_fetch_batch_v1 (
    fetch_batch_id TEXT PRIMARY KEY,
    fetch_plan_id TEXT NOT NULL,
    request_source TEXT NOT NULL,
    trigger_type TEXT NOT NULL,
    priority TEXT NOT NULL,
    queue_name TEXT NOT NULL,
    source_table_name TEXT NOT NULL,
    canonical_fields TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    trade_date DATE,
    date_range_start DATE,
    date_range_end DATE,
    symbol_count INTEGER NOT NULL DEFAULT 0 CHECK (symbol_count >= 0),
    job_count INTEGER NOT NULL DEFAULT 0 CHECK (job_count >= 0),
    status TEXT NOT NULL,
    callback_url TEXT,
    operator_notes JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by TEXT
);

COMMENT ON TABLE governance.raw_fetch_batch_v1 IS
'Durable producer-side fetch batch. Covers scheduled periodic ingest, data-inspection gap repair, model ad-hoc requests, release preflight, manual backfill and provider probes.';
COMMENT ON COLUMN governance.raw_fetch_batch_v1.trigger_type IS
'scheduled_periodic, data_inspection_gap_repair, model_adhoc_request, model_release_preflight, manual_backfill, provider_probe, or operator_manual.';
COMMENT ON COLUMN governance.raw_fetch_batch_v1.queue_name IS
'Priority queue name. P0 release-gate data must use urgent_release_gate_queue and must not wait behind research/backfill jobs.';

CREATE TABLE IF NOT EXISTS governance.raw_fetch_job_item_v1 (
    job_item_id TEXT PRIMARY KEY,
    fetch_batch_id TEXT NOT NULL REFERENCES governance.raw_fetch_batch_v1(fetch_batch_id),
    provider TEXT NOT NULL,
    api_name TEXT NOT NULL,
    raw_table_name TEXT NOT NULL,
    request_params_json JSONB NOT NULL,
    request_hash TEXT NOT NULL,
    source_table_name TEXT NOT NULL,
    canonical_fields TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    symbol TEXT,
    trade_date DATE,
    date_range_start DATE,
    date_range_end DATE,
    priority TEXT NOT NULL,
    queue_name TEXT NOT NULL,
    status TEXT NOT NULL,
    worker_id TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    backup_of_job_item_id TEXT,
    next_retry_at TIMESTAMPTZ,
    lease_expires_at TIMESTAMPTZ,
    last_error_code TEXT,
    last_error_message TEXT,
    raw_request_hash TEXT,
    raw_response_schema_hash TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (provider, api_name, raw_table_name, request_hash)
);

COMMENT ON TABLE governance.raw_fetch_job_item_v1 IS
'Durable consumer-side fetch job item. One row equals one exact provider API/raw table request. Unique request_hash prevents duplicate provider calls and data confusion.';
COMMENT ON COLUMN governance.raw_fetch_job_item_v1.request_params_json IS
'Exact provider request parameters. Data-inspector-service repairs a missing field by replaying this provider/api/raw-table contract.';
COMMENT ON COLUMN governance.raw_fetch_job_item_v1.backup_of_job_item_id IS
'When primary provider fails, backup provider jobs point back to the failed primary job; task state is not lost.';
COMMENT ON COLUMN governance.raw_fetch_job_item_v1.lease_expires_at IS
'Consumer lease deadline. Expired leases can be requeued by a later worker without losing the original job.';

CREATE TABLE IF NOT EXISTS governance.raw_fetch_callback_event_v1 (
    callback_event_id TEXT PRIMARY KEY,
    fetch_batch_id TEXT NOT NULL REFERENCES governance.raw_fetch_batch_v1(fetch_batch_id),
    job_item_id TEXT,
    event_type TEXT NOT NULL,
    callback_url TEXT,
    payload_json JSONB NOT NULL,
    delivery_status TEXT NOT NULL DEFAULT 'pending',
    delivery_attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (delivery_attempt_count >= 0),
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    delivered_at TIMESTAMPTZ
);

COMMENT ON TABLE governance.raw_fetch_callback_event_v1 IS
'Callback/outbox event table for producer-consumer task status. Downstream services can track batch/job submitted, leased, succeeded, failed, backup queued and completed states.';
COMMENT ON COLUMN governance.raw_fetch_callback_event_v1.delivery_status IS
'pending, delivered, skipped_no_callback, or failed. This outbox avoids losing task status even if callback delivery is delayed.';

CREATE TABLE IF NOT EXISTS governance.provider_runtime_status_v1 (
    provider TEXT NOT NULL,
    api_name TEXT NOT NULL,
    runtime_status TEXT NOT NULL,
    current_inflight INTEGER NOT NULL DEFAULT 0 CHECK (current_inflight >= 0),
    queued_count INTEGER NOT NULL DEFAULT 0 CHECK (queued_count >= 0),
    leased_count INTEGER NOT NULL DEFAULT 0 CHECK (leased_count >= 0),
    succeeded_count INTEGER NOT NULL DEFAULT 0 CHECK (succeeded_count >= 0),
    failed_count INTEGER NOT NULL DEFAULT 0 CHECK (failed_count >= 0),
    avg_latency_ms_5m INTEGER,
    p95_latency_ms_5m INTEGER,
    circuit_state TEXT NOT NULL DEFAULT 'closed',
    circuit_open_until TIMESTAMPTZ,
    last_success_at TIMESTAMPTZ,
    last_failure_at TIMESTAMPTZ,
    last_error TEXT,
    checked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (provider, api_name)
);

COMMENT ON TABLE governance.provider_runtime_status_v1 IS
'Runtime health and queue pressure snapshot by provider API. It lets source-data-service route around rate-limited/degraded/circuit-open providers.';

CREATE TABLE IF NOT EXISTS governance.source_build_trigger_v1 (
    trigger_id TEXT PRIMARY KEY,
    fetch_batch_id TEXT NOT NULL REFERENCES governance.raw_fetch_batch_v1(fetch_batch_id),
    job_item_id TEXT REFERENCES governance.raw_fetch_job_item_v1(job_item_id),
    source_table_name TEXT NOT NULL,
    symbol TEXT,
    trade_date DATE,
    build_scope TEXT NOT NULL,
    status TEXT NOT NULL,
    quality_check_required BOOLEAN NOT NULL DEFAULT TRUE,
    lineage_required BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ
);

COMMENT ON TABLE governance.source_build_trigger_v1 IS
'Created after raw-interface fetch success. Source build must run quality gates first, then build source.* and write governance.source_lineage_v1 before models can consume fields.';

CREATE INDEX IF NOT EXISTS idx_raw_fetch_batch_status_queue_v1
    ON governance.raw_fetch_batch_v1 (status, queue_name, priority, created_at);
CREATE INDEX IF NOT EXISTS idx_raw_fetch_job_queue_status_v1
    ON governance.raw_fetch_job_item_v1 (status, queue_name, provider, api_name, priority, created_at);
CREATE INDEX IF NOT EXISTS idx_raw_fetch_job_symbol_date_v1
    ON governance.raw_fetch_job_item_v1 (source_table_name, symbol, trade_date);
CREATE INDEX IF NOT EXISTS idx_raw_fetch_job_lease_v1
    ON governance.raw_fetch_job_item_v1 (status, lease_expires_at);
CREATE INDEX IF NOT EXISTS idx_raw_fetch_callback_batch_v1
    ON governance.raw_fetch_callback_event_v1 (fetch_batch_id, created_at);
CREATE INDEX IF NOT EXISTS idx_provider_runtime_status_lookup_v1
    ON governance.provider_runtime_status_v1 (runtime_status, provider, api_name);
CREATE INDEX IF NOT EXISTS idx_source_build_trigger_status_v1
    ON governance.source_build_trigger_v1 (status, source_table_name, trade_date);
