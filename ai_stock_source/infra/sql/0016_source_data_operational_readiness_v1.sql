-- DS-3 operational readiness schema for source-data-service.
-- Purpose: make provider probing, raw quality checks, canonical source build and
-- repair routing auditable before any model consumes source.* facts.

CREATE SCHEMA IF NOT EXISTS governance;

CREATE TABLE IF NOT EXISTS governance.provider_probe_matrix_v1 (
    provider TEXT NOT NULL,
    api_name TEXT NOT NULL,
    raw_table_name TEXT NOT NULL,
    sample_params_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    expected_fields_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    canonical_targets_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    dry_run_supported BOOLEAN NOT NULL DEFAULT TRUE,
    real_probe_required BOOLEAN NOT NULL DEFAULT TRUE,
    last_probe_status TEXT NOT NULL DEFAULT 'not_run',
    last_probe_at TIMESTAMPTZ,
    last_row_count INTEGER,
    last_missing_fields_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    last_response_schema_hash TEXT,
    readiness_note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (provider, api_name)
);

COMMENT ON TABLE governance.provider_probe_matrix_v1 IS
'Operational probe matrix. Every registered provider API should have a sample request, expected fields and latest probe status before it can be promoted as source primary or backup.';
COMMENT ON COLUMN governance.provider_probe_matrix_v1.raw_table_name IS
'One-interface-one-table destination. Probe success does not write source.* directly; raw rows must be ingested first.';
COMMENT ON COLUMN governance.provider_probe_matrix_v1.last_response_schema_hash IS
'Observed response schema hash. Changes require provider_field_mapping_v1 and source build rule review before source promotion.';

CREATE TABLE IF NOT EXISTS governance.raw_quality_check_result_v1 (
    check_id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL,
    api_name TEXT NOT NULL,
    raw_table_name TEXT NOT NULL,
    request_hash TEXT,
    response_schema_hash TEXT,
    checked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    row_count INTEGER NOT NULL DEFAULT 0,
    issue_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    warning_count INTEGER NOT NULL DEFAULT 0,
    build_allowed BOOLEAN NOT NULL DEFAULT FALSE,
    issues_json JSONB NOT NULL DEFAULT '[]'::jsonb
);

COMMENT ON TABLE governance.raw_quality_check_result_v1 IS
'Raw interface quality gate result. Canonical source build must not proceed when build_allowed=false.';
COMMENT ON COLUMN governance.raw_quality_check_result_v1.issues_json IS
'Row-level schema, OHLC, volume/amount, type and unit issues. Severe errors force source_quality_status=rejected/gap/suspect.';

CREATE TABLE IF NOT EXISTS governance.source_build_batch_v1 (
    build_batch_id TEXT PRIMARY KEY,
    source_table_name TEXT NOT NULL,
    build_rule_version TEXT NOT NULL,
    source_pk_range_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    triggered_by TEXT NOT NULL DEFAULT 'manual_or_scheduler',
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'running',
    input_raw_batches_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    output_row_count INTEGER NOT NULL DEFAULT 0,
    lineage_row_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT
);

ALTER TABLE governance.source_build_batch_v1
    ADD COLUMN IF NOT EXISTS build_rule_version TEXT NOT NULL DEFAULT 'source_build_rule_v1';
ALTER TABLE governance.source_build_batch_v1
    ADD COLUMN IF NOT EXISTS source_pk_range_json JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE governance.source_build_batch_v1
    ADD COLUMN IF NOT EXISTS triggered_by TEXT NOT NULL DEFAULT 'manual_or_scheduler';
ALTER TABLE governance.source_build_batch_v1
    ADD COLUMN IF NOT EXISTS input_raw_batches_json JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE governance.source_build_batch_v1
    ADD COLUMN IF NOT EXISTS output_row_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE governance.source_build_batch_v1
    ADD COLUMN IF NOT EXISTS lineage_row_count INTEGER NOT NULL DEFAULT 0;

COMMENT ON TABLE governance.source_build_batch_v1 IS
'Canonical source build execution batch. It records the raw batches used, generated source row count and lineage row count.';
COMMENT ON COLUMN governance.source_build_batch_v1.input_raw_batches_json IS
'Raw ingest batch IDs consumed by this canonical build. This is required for exact replay and rollback.';
COMMENT ON COLUMN governance.source_build_batch_v1.lineage_row_count IS
'Number of governance.source_lineage_v1 rows written. P0 builds should write lineage for every canonical field.';

CREATE TABLE IF NOT EXISTS governance.source_readiness_evidence_v1 (
    evidence_id BIGSERIAL PRIMARY KEY,
    source_table_name TEXT NOT NULL,
    canonical_field_name TEXT NOT NULL,
    provider TEXT NOT NULL,
    api_name TEXT NOT NULL,
    raw_table_name TEXT NOT NULL,
    evidence_type TEXT NOT NULL,
    evidence_status TEXT NOT NULL,
    coverage_rate NUMERIC,
    sample_start_date DATE,
    sample_end_date DATE,
    sample_symbol_count INTEGER,
    observed_row_count INTEGER,
    observed_missing_count INTEGER,
    response_schema_hash TEXT,
    evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    checked_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE governance.source_readiness_evidence_v1 IS
'Field-level readiness evidence. A source field is not production-ready merely because a provider is registered; it needs probe, coverage, quality and cross-provider evidence.';
COMMENT ON COLUMN governance.source_readiness_evidence_v1.evidence_type IS
'Examples: provider_probe, raw_quality, coverage_scan, cross_provider_compare, source_build, lineage_check.';
COMMENT ON COLUMN governance.source_readiness_evidence_v1.evidence_status IS
'passed/blocked/research_only/suspect. Official model releases can only use fields whose P0 evidence passed.';

CREATE TABLE IF NOT EXISTS governance.source_field_repair_route_v1 (
    source_table_name TEXT NOT NULL,
    canonical_field_name TEXT NOT NULL,
    required_level TEXT NOT NULL,
    primary_provider TEXT NOT NULL,
    primary_api_name TEXT NOT NULL,
    primary_raw_table_name TEXT NOT NULL,
    backup_provider TEXT,
    backup_api_name TEXT,
    backup_raw_table_name TEXT,
    online_policy TEXT NOT NULL,
    used_by_models_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    route_version TEXT NOT NULL DEFAULT 'source_field_repair_route_v1',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source_table_name, canonical_field_name, route_version)
);

COMMENT ON TABLE governance.source_field_repair_route_v1 IS
'Fast lookup table for data-inspector-service. Given a missing source table/field, this table tells which provider API/raw table to call first and which backup to use.';
COMMENT ON COLUMN governance.source_field_repair_route_v1.online_policy IS
'required/degradable/research_only. Required missing fields block official model release until repaired and rebuilt.';

CREATE INDEX IF NOT EXISTS idx_provider_probe_matrix_status_v1
    ON governance.provider_probe_matrix_v1 (last_probe_status, provider, api_name);

CREATE INDEX IF NOT EXISTS idx_raw_quality_build_allowed_v1
    ON governance.raw_quality_check_result_v1 (build_allowed, provider, api_name, checked_at DESC);

CREATE INDEX IF NOT EXISTS idx_source_build_batch_status_v1
    ON governance.source_build_batch_v1 (source_table_name, status, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_source_readiness_field_v1
    ON governance.source_readiness_evidence_v1 (source_table_name, canonical_field_name, evidence_type, checked_at DESC);

CREATE INDEX IF NOT EXISTS idx_source_field_repair_route_lookup_v1
    ON governance.source_field_repair_route_v1 (source_table_name, canonical_field_name, enabled);
