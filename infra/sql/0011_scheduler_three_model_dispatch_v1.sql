BEGIN;

CREATE SCHEMA IF NOT EXISTS governance;

-- Scheduler v1.1 additions for three-model dispatch/materialization/documentation sync.
-- Governance-only metadata: no model business truth is stored here.
CREATE TABLE IF NOT EXISTS governance.owner_endpoint_registry_v1 (
    owner_service VARCHAR(128) PRIMARY KEY,
    base_url TEXT NOT NULL,
    environment VARCHAR(64) NOT NULL DEFAULT 'local',
    health_path VARCHAR(256) NOT NULL DEFAULT '/healthz',
    live_dispatch_version VARCHAR(96),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS governance.task_definition_registry_v1 (
    task_code VARCHAR(128) PRIMARY KEY,
    task_kind VARCHAR(64) NOT NULL,
    owner_service VARCHAR(128) NOT NULL,
    dispatch_path VARCHAR(256) NOT NULL,
    schedule_hint TEXT NOT NULL,
    frequency_hint TEXT NOT NULL,
    is_official_publish BOOLEAN NOT NULL DEFAULT FALSE,
    append_only BOOLEAN NOT NULL DEFAULT TRUE,
    reads_from_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    writes_to_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    scheduler_version VARCHAR(96) NOT NULL,
    live_dispatch_version VARCHAR(96),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_governance_task_definition_owner ON governance.task_definition_registry_v1(owner_service, task_kind);

CREATE TABLE IF NOT EXISTS governance.task_materialization_audit_v1 (
    materialization_id VARCHAR(128) PRIMARY KEY,
    trading_day DATE NOT NULL,
    task_code VARCHAR(128) NOT NULL,
    owner_service VARCHAR(128) NOT NULL,
    run_slot VARCHAR(64) NOT NULL,
    scheduled_at TIMESTAMPTZ NOT NULL,
    scheduled_at_local TEXT NOT NULL,
    biz_key VARCHAR(192) NOT NULL,
    idempotency_seed VARCHAR(192) NOT NULL,
    is_official_publish BOOLEAN NOT NULL DEFAULT FALSE,
    append_only BOOLEAN NOT NULL DEFAULT TRUE,
    materializer_version VARCHAR(96) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (task_code, trading_day, run_slot)
);
CREATE INDEX IF NOT EXISTS idx_governance_task_materialization_due ON governance.task_materialization_audit_v1(trading_day, scheduled_at);
CREATE INDEX IF NOT EXISTS idx_governance_task_materialization_official ON governance.task_materialization_audit_v1(is_official_publish, trading_day);

CREATE TABLE IF NOT EXISTS governance.scheduler_docs_sync_audit_v1 (
    docs_sync_audit_id VARCHAR(128) PRIMARY KEY,
    docs_sync_version VARCHAR(96) NOT NULL,
    scheduler_version VARCHAR(96) NOT NULL,
    materializer_version VARCHAR(96) NOT NULL,
    live_dispatch_version VARCHAR(96) NOT NULL,
    valid BOOLEAN NOT NULL,
    missing_docs_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    missing_tokens_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    official_publish_tasks_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    checked_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMIT;
