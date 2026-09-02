-- 0026_research_model_payload_assembly_audit_v1.sql
-- Purpose: append-only audit for research_model_payload_assembler_v1.
-- The table records model owner payload assembly evidence only. It does not
-- write model decisions, scores, release gates, buy points, outcomes, labels,
-- source facts, raw rows or provider results.

CREATE SCHEMA IF NOT EXISTS governance;

CREATE TABLE IF NOT EXISTS governance.research_model_payload_assembly_audit_v1 (
    assembly_id TEXT PRIMARY KEY,
    task_code TEXT NOT NULL,
    owner_service TEXT NOT NULL,
    model_code TEXT NOT NULL,
    model_phase TEXT,
    symbol TEXT,
    trade_date DATE NOT NULL,
    payload_assembly_contract TEXT NOT NULL DEFAULT 'research_model_payload_assembler_v1',
    payload_assembly_status TEXT NOT NULL,
    gap_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
    source_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    upstream_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    payload_hash TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_research_payload_assembly_contract_v1 CHECK (
        payload_assembly_contract = 'research_model_payload_assembler_v1'
    ),
    CONSTRAINT ck_research_payload_assembly_status_v1 CHECK (
        payload_assembly_status IN ('assembled_research_payload', 'blocked_data_gap')
    )
);

CREATE INDEX IF NOT EXISTS idx_research_payload_assembly_task_day_v1
    ON governance.research_model_payload_assembly_audit_v1 (task_code, trade_date DESC, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_research_payload_assembly_symbol_day_v1
    ON governance.research_model_payload_assembly_audit_v1 (symbol, trade_date DESC, created_at DESC)
    WHERE symbol IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_research_payload_assembly_status_v1
    ON governance.research_model_payload_assembly_audit_v1 (payload_assembly_status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_research_payload_assembly_hash_v1
    ON governance.research_model_payload_assembly_audit_v1 (payload_hash);

COMMENT ON TABLE governance.research_model_payload_assembly_audit_v1 IS
'Append-only audit for research-service model owner payload assembly; not a model fact or source fact table.';
COMMENT ON COLUMN governance.research_model_payload_assembly_audit_v1.payload IS
'Assembled owner business payload or blocked gap payload. Must not contain raw provider rows or sample payload substitutions.';
