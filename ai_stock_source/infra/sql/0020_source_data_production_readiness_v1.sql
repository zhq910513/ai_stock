-- 0020_source_data_production_readiness_v1.sql
-- DS-7: production readiness gate and acceptance evidence tables.
-- These tables are evidence stores for operator/CI acceptance runs. They do
-- not replace raw/source/lineage tables and do not contain model signals.

CREATE SCHEMA IF NOT EXISTS governance;

CREATE TABLE IF NOT EXISTS governance.source_data_acceptance_run_v1 (
    acceptance_run_id TEXT PRIMARY KEY,
    version_label TEXT NOT NULL,
    base_url TEXT NOT NULL,
    require_postgres BOOLEAN NOT NULL DEFAULT true,
    require_real_provider_probe BOOLEAN NOT NULL DEFAULT false,
    status TEXT NOT NULL,
    can_lock_candidate BOOLEAN NOT NULL DEFAULT false,
    blocking_reasons_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    warning_reasons_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ
);
COMMENT ON TABLE governance.source_data_acceptance_run_v1 IS 'DS-7 数据源上线验收运行记录；记录 Docker/Postgres/provider/队列/worker/source build/preflight 的整体验收结论。';
COMMENT ON COLUMN governance.source_data_acceptance_run_v1.can_lock_candidate IS '是否允许将 source-data-service 标记为可拍板候选；真实生产仍需保留 provider probe、raw/source/lineage 写入证据。';

CREATE TABLE IF NOT EXISTS governance.source_data_acceptance_check_v1 (
    acceptance_run_id TEXT NOT NULL REFERENCES governance.source_data_acceptance_run_v1(acceptance_run_id),
    check_code TEXT NOT NULL,
    status TEXT NOT NULL,
    required_for_lock BOOLEAN NOT NULL DEFAULT true,
    evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    operator_action TEXT,
    checked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (acceptance_run_id, check_code)
);
COMMENT ON TABLE governance.source_data_acceptance_check_v1 IS 'DS-7 数据源上线验收单项检查证据；每个检查都必须可读、可追溯、可复跑。';
COMMENT ON COLUMN governance.source_data_acceptance_check_v1.evidence_json IS '检查证据，例如 queue/repository/provider/readiness/coverage/preflight 的 HTTP 响应摘要。';

CREATE INDEX IF NOT EXISTS idx_source_data_acceptance_run_status_v1
    ON governance.source_data_acceptance_run_v1 (status, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_source_data_acceptance_check_status_v1
    ON governance.source_data_acceptance_check_v1 (check_code, status, checked_at DESC);

-- DS-6 compatibility hardening: every raw provider row and lineage record must
-- carry the exact request/response hashes needed for replay and audit. Older
-- raw tables created before DS-6 only had request_params_json plus response
-- hashes, so keep this idempotent ALTER inside 0020 to preserve the 0012~0020
-- bootstrap closure.
DO $$
DECLARE
    raw_table RECORD;
BEGIN
    FOR raw_table IN
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_type = 'BASE TABLE'
          AND table_schema LIKE 'raw\_%' ESCAPE '\'
    LOOP
        EXECUTE format(
            'ALTER TABLE %I.%I ADD COLUMN IF NOT EXISTS request_hash TEXT',
            raw_table.table_schema,
            raw_table.table_name
        );
    END LOOP;
END $$;

ALTER TABLE governance.source_lineage_v1
    ADD COLUMN IF NOT EXISTS request_hash TEXT,
    ADD COLUMN IF NOT EXISTS response_row_hash TEXT;

CREATE INDEX IF NOT EXISTS idx_source_lineage_request_hash_v1
    ON governance.source_lineage_v1 (request_hash)
    WHERE request_hash IS NOT NULL;

-- If a previous API/worker split left triggers queued or failed after a
-- successful durable build result was already written, the build result is the
-- authoritative audit fact.
UPDATE governance.source_build_trigger_v1 AS trigger
SET status = 'succeeded',
    finished_at = result.finished_at
FROM (
    SELECT trigger_id, MAX(finished_at) AS finished_at
    FROM governance.source_build_execution_result_v1
    WHERE status = 'succeeded'
    GROUP BY trigger_id
) AS result
WHERE trigger.trigger_id = result.trigger_id
  AND trigger.status <> 'succeeded';
