-- 0018_source_data_durable_queue_worker_v1.sql
-- Purpose: DS-5 production hardening for source-data-service queue durability.
-- It adds idempotency, worker heartbeat, dead-letter audit and operational
-- indexes around the producer/consumer raw fetch queue introduced in 0017.

CREATE SCHEMA IF NOT EXISTS governance;

CREATE TABLE IF NOT EXISTS governance.raw_fetch_idempotency_key_v1 (
    idempotency_key TEXT PRIMARY KEY,
    fetch_batch_id TEXT NOT NULL REFERENCES governance.raw_fetch_batch_v1(fetch_batch_id),
    request_source TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE governance.raw_fetch_idempotency_key_v1 IS
'Producer-side idempotency registry. Repeated scheduler/data-inspector/model requests with the same key must return the original fetch_batch_id instead of creating duplicate provider calls.';
COMMENT ON COLUMN governance.raw_fetch_idempotency_key_v1.request_hash IS
'Stable hash of source_table, fields, symbols, date range, trigger type and request source used for audit and duplicate detection.';

CREATE TABLE IF NOT EXISTS governance.raw_fetch_worker_heartbeat_v1 (
    worker_id TEXT PRIMARY KEY,
    worker_role TEXT NOT NULL DEFAULT 'source-fetch-worker',
    queue_names TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    providers TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    current_job_item_id TEXT,
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    status TEXT NOT NULL DEFAULT 'alive',
    note TEXT
);

COMMENT ON TABLE governance.raw_fetch_worker_heartbeat_v1 IS
'Worker heartbeat table. Operators use it to detect stalled consumers before leases expire and to audit which worker processed source raw-interface jobs.';
COMMENT ON COLUMN governance.raw_fetch_worker_heartbeat_v1.current_job_item_id IS
'Current job leased by the worker, if any. The job itself remains the source of truth in raw_fetch_job_item_v1.';

CREATE TABLE IF NOT EXISTS governance.raw_fetch_dead_letter_v1 (
    dead_letter_id TEXT PRIMARY KEY,
    job_item_id TEXT NOT NULL REFERENCES governance.raw_fetch_job_item_v1(job_item_id),
    fetch_batch_id TEXT NOT NULL REFERENCES governance.raw_fetch_batch_v1(fetch_batch_id),
    provider TEXT NOT NULL,
    api_name TEXT NOT NULL,
    raw_table_name TEXT NOT NULL,
    request_params_json JSONB NOT NULL,
    request_hash TEXT NOT NULL,
    final_error_code TEXT NOT NULL,
    final_error_message TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    backup_attempted BOOLEAN NOT NULL DEFAULT FALSE,
    operator_action_required BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at TIMESTAMPTZ,
    resolution_note TEXT
);

COMMENT ON TABLE governance.raw_fetch_dead_letter_v1 IS
'Dead-letter audit for provider raw-interface fetch jobs that exhausted retries and backup routes. No failed job should disappear silently.';
COMMENT ON COLUMN governance.raw_fetch_dead_letter_v1.operator_action_required IS
'When true, source readiness or model release preflight must not ignore this failed job if it affects P0/P1 fields.';

ALTER TABLE governance.raw_fetch_callback_event_v1
    ADD COLUMN IF NOT EXISTS next_delivery_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_attempted_at TIMESTAMPTZ;

COMMENT ON COLUMN governance.raw_fetch_callback_event_v1.next_delivery_at IS
'Next scheduled callback delivery time for outbox retry. This prevents status callbacks from being lost during downstream outages.';
COMMENT ON COLUMN governance.raw_fetch_callback_event_v1.last_attempted_at IS
'Last callback delivery attempt time.';

CREATE INDEX IF NOT EXISTS idx_raw_fetch_idempotency_batch_v1
    ON governance.raw_fetch_idempotency_key_v1 (fetch_batch_id);
CREATE INDEX IF NOT EXISTS idx_raw_fetch_worker_status_seen_v1
    ON governance.raw_fetch_worker_heartbeat_v1 (status, last_seen_at);
CREATE INDEX IF NOT EXISTS idx_raw_fetch_dead_letter_batch_v1
    ON governance.raw_fetch_dead_letter_v1 (fetch_batch_id, created_at);
CREATE INDEX IF NOT EXISTS idx_raw_fetch_dead_letter_provider_v1
    ON governance.raw_fetch_dead_letter_v1 (provider, api_name, created_at);
CREATE INDEX IF NOT EXISTS idx_raw_fetch_callback_delivery_due_v1
    ON governance.raw_fetch_callback_event_v1 (delivery_status, next_delivery_at, created_at);
