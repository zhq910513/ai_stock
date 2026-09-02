-- 0027_research_model_execution_audit_v1.sql
-- Purpose: append-only audit for research_model_execution_v1.
-- Research-service assembles source-qualified payloads, calls model owner
-- services, and materializes owner outputs into decision schemas. It never
-- computes model scores itself and never reads raw provider tables.

CREATE SCHEMA IF NOT EXISTS governance;

ALTER TABLE IF EXISTS decision_memory.memory_entity_v1
    ALTER COLUMN memory_age_days DROP NOT NULL,
    ALTER COLUMN memory_age_days DROP DEFAULT;

CREATE TABLE IF NOT EXISTS governance.research_model_execution_audit_v1 (
    execution_id TEXT PRIMARY KEY,
    assembly_id TEXT,
    task_code TEXT NOT NULL,
    owner_service TEXT NOT NULL,
    model_code TEXT NOT NULL,
    model_phase TEXT,
    symbol TEXT,
    trade_date DATE NOT NULL,
    run_id TEXT NOT NULL,
    execution_contract TEXT NOT NULL DEFAULT 'research_model_execution_v1',
    payload_hash TEXT,
    owner_endpoint TEXT,
    owner_status_code INTEGER,
    execution_status TEXT NOT NULL,
    accepted BOOLEAN NOT NULL DEFAULT false,
    dispatch_allowed BOOLEAN NOT NULL DEFAULT false,
    owner_called BOOLEAN NOT NULL DEFAULT false,
    materialization_attempted BOOLEAN NOT NULL DEFAULT false,
    gap_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
    error_code TEXT,
    error_message TEXT,
    owner_request JSONB NOT NULL DEFAULT '{}'::jsonb,
    owner_response JSONB NOT NULL DEFAULT '{}'::jsonb,
    materialized_counts JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_research_model_execution_contract_v1 CHECK (
        execution_contract = 'research_model_execution_v1'
    ),
    CONSTRAINT ck_research_model_execution_status_v1 CHECK (
        execution_status IN (
            'blocked_data_gap',
            'owner_failed',
            'materialization_failed',
            'materialized',
            'materialized_with_gaps',
            'materialization_skipped'
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_research_model_execution_task_day_v1
    ON governance.research_model_execution_audit_v1 (task_code, trade_date DESC, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_research_model_execution_owner_status_v1
    ON governance.research_model_execution_audit_v1 (owner_service, execution_status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_research_model_execution_symbol_day_v1
    ON governance.research_model_execution_audit_v1 (symbol, trade_date DESC, created_at DESC)
    WHERE symbol IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_research_model_execution_payload_hash_v1
    ON governance.research_model_execution_audit_v1 (payload_hash)
    WHERE payload_hash IS NOT NULL;

COMMENT ON TABLE governance.research_model_execution_audit_v1 IS
'Append-only audit for research-service owner execution and materialization; score computation remains in model owner services.';
COMMENT ON COLUMN governance.research_model_execution_audit_v1.materialized_counts IS
'Decision/source table write counts by table name plus materializer gap codes when present.';
