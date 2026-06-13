-- 0019_source_data_operational_closure_v1.sql
-- DS-6: raw real-write, source build execution, lineage closure,
-- freshness SLA, storage policy and model coverage preflight.
-- This migration does not add model-owned semantics into source tables.

CREATE SCHEMA IF NOT EXISTS governance;
CREATE SCHEMA IF NOT EXISTS source;

CREATE TABLE IF NOT EXISTS governance.raw_interface_write_audit_v1 (
    raw_write_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    api_name TEXT NOT NULL,
    raw_table_name TEXT NOT NULL,
    request_hash TEXT,
    response_schema_hash TEXT,
    ingested_row_count INTEGER NOT NULL DEFAULT 0,
    duplicate_row_count INTEGER NOT NULL DEFAULT 0,
    rejected_row_count INTEGER NOT NULL DEFAULT 0,
    raw_write_status TEXT NOT NULL,
    quality_status TEXT NOT NULL DEFAULT 'not_checked',
    warnings_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE governance.raw_interface_write_audit_v1 IS 'DS-6 raw 原接口真实写入审计；每次 provider API 返回结果入库后记录行数、schema_hash、request_hash、重复/拒绝数量。';
COMMENT ON COLUMN governance.raw_interface_write_audit_v1.request_hash IS '同 provider/api/params 的幂等识别键；重复补采不得产生重复 raw 行。';
COMMENT ON COLUMN governance.raw_interface_write_audit_v1.response_schema_hash IS '接口返回字段结构哈希；变化时必须阻断 source build 并检查字段映射。';

CREATE INDEX IF NOT EXISTS idx_raw_interface_write_audit_lookup_v1
    ON governance.raw_interface_write_audit_v1 (provider, api_name, raw_table_name, request_hash, created_at DESC);

CREATE TABLE IF NOT EXISTS governance.source_build_execution_result_v1 (
    build_execution_id TEXT PRIMARY KEY,
    trigger_id TEXT NOT NULL,
    fetch_batch_id TEXT,
    job_item_id TEXT,
    source_table_name TEXT NOT NULL,
    build_batch_id TEXT NOT NULL,
    status TEXT NOT NULL,
    raw_row_count INTEGER NOT NULL DEFAULT 0,
    source_row_count INTEGER NOT NULL DEFAULT 0,
    lineage_row_count INTEGER NOT NULL DEFAULT 0,
    quality_issue_count INTEGER NOT NULL DEFAULT 0,
    errors_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    warnings_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ NOT NULL
);
COMMENT ON TABLE governance.source_build_execution_result_v1 IS 'source build 真实执行结果；每次从 raw_* 构建 source.* 必须记录 raw/source/lineage 行数和失败原因。';
COMMENT ON COLUMN governance.source_build_execution_result_v1.build_batch_id IS '写入 source.* 和 governance.source_lineage_v1 的统一批次号，用于回滚、审计和覆盖度证明。';
CREATE INDEX IF NOT EXISTS idx_source_build_execution_result_trigger_v1
    ON governance.source_build_execution_result_v1 (trigger_id, status, finished_at DESC);
CREATE INDEX IF NOT EXISTS idx_source_build_execution_result_table_batch_v1
    ON governance.source_build_execution_result_v1 (source_table_name, build_batch_id);

CREATE TABLE IF NOT EXISTS governance.source_canonical_write_audit_v1 (
    source_write_id TEXT PRIMARY KEY,
    source_table_name TEXT NOT NULL,
    source_pk TEXT NOT NULL,
    symbol TEXT,
    trade_date DATE,
    canonical_fields TEXT[] NOT NULL,
    provider TEXT,
    api_name TEXT,
    raw_table_name TEXT,
    request_hash TEXT,
    build_batch_id TEXT NOT NULL,
    source_quality_status TEXT NOT NULL,
    available_at TIMESTAMPTZ,
    captured_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE governance.source_canonical_write_audit_v1 IS 'source 标准事实表写入审计；模型只允许消费 source.*，每行 source 写入必须可追溯到 raw/provider/API。';
COMMENT ON COLUMN governance.source_canonical_write_audit_v1.available_at IS '数据对模型可见时间；release_gate 必须校验 available_at <= decision_time，防止未来函数。';
CREATE INDEX IF NOT EXISTS idx_source_canonical_write_lookup_v1
    ON governance.source_canonical_write_audit_v1 (source_table_name, symbol, trade_date, build_batch_id);

CREATE TABLE IF NOT EXISTS governance.source_freshness_sla_v1 (
    source_table_name TEXT NOT NULL,
    canonical_field_name TEXT NOT NULL,
    frequency TEXT NOT NULL,
    market_phase TEXT NOT NULL,
    expected_available_time TEXT NOT NULL,
    latest_acceptable_time TEXT NOT NULL,
    timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
    used_by_models TEXT[] NOT NULL,
    required_for_release_gate BOOLEAN NOT NULL DEFAULT false,
    stale_after_minutes INTEGER NOT NULL,
    late_policy TEXT NOT NULL,
    fallback_policy TEXT NOT NULL,
    comment TEXT NOT NULL,
    PRIMARY KEY (source_table_name, canonical_field_name, market_phase)
);
COMMENT ON TABLE governance.source_freshness_sla_v1 IS 'source 字段及时性 SLA；定义每个模型关键字段何时必须到达、晚到/过期时阻断还是降级。';
COMMENT ON COLUMN governance.source_freshness_sla_v1.late_policy IS 'block_official_release/degrade/research_only；P0 字段晚到必须阻断 official release。';

CREATE TABLE IF NOT EXISTS governance.source_freshness_status_v1 (
    freshness_check_id TEXT PRIMARY KEY,
    source_table_name TEXT NOT NULL,
    canonical_field_name TEXT NOT NULL,
    symbol TEXT,
    trade_date DATE NOT NULL,
    freshness_status TEXT NOT NULL,
    latest_data_available_at TIMESTAMPTZ,
    stale_after_minutes INTEGER NOT NULL,
    affected_models TEXT[] NOT NULL,
    blocking_release_gate BOOLEAN NOT NULL,
    reason TEXT NOT NULL,
    checked_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE governance.source_freshness_status_v1 IS 'source 字段运行时新鲜度检查结果；模型 release_gate 前必须读取该结果或调用 preflight。';
CREATE INDEX IF NOT EXISTS idx_source_freshness_status_lookup_v1
    ON governance.source_freshness_status_v1 (source_table_name, canonical_field_name, symbol, trade_date, checked_at DESC);

CREATE TABLE IF NOT EXISTS governance.source_storage_policy_v1 (
    table_name TEXT PRIMARY KEY,
    table_layer TEXT NOT NULL,
    partition_key TEXT NOT NULL,
    partition_granularity TEXT NOT NULL,
    retention_hot_days INTEGER NOT NULL,
    archive_enabled BOOLEAN NOT NULL DEFAULT false,
    archive_target TEXT,
    required_indexes TEXT[] NOT NULL,
    expected_daily_rows INTEGER NOT NULL,
    expected_total_rows_1y BIGINT NOT NULL,
    expected_total_rows_10y BIGINT NOT NULL,
    comment TEXT NOT NULL
);
COMMENT ON TABLE governance.source_storage_policy_v1 IS '数据量级和物理治理策略；声明 raw/source/lineage 的分区、索引、冷热归档和十年容量预估。';
COMMENT ON COLUMN governance.source_storage_policy_v1.expected_total_rows_10y IS '十年规模预估；模型三历史图库和血缘表必须按该规模设计索引与归档。';

CREATE TABLE IF NOT EXISTS governance.model_source_requirement_v1 (
    model_code TEXT NOT NULL,
    model_phase TEXT NOT NULL,
    source_table_name TEXT NOT NULL,
    canonical_field_name TEXT NOT NULL,
    required_level TEXT NOT NULL,
    required_for_official_signal BOOLEAN NOT NULL,
    required_for_backtest BOOLEAN NOT NULL,
    required_for_research BOOLEAN NOT NULL,
    degrade_policy TEXT NOT NULL,
    minimum_symbol_coverage_rate NUMERIC(8,6) NOT NULL,
    minimum_date_coverage_rate NUMERIC(8,6) NOT NULL,
    minimum_field_coverage_rate NUMERIC(8,6) NOT NULL,
    comment TEXT NOT NULL,
    PRIMARY KEY (model_code, model_phase, source_table_name, canonical_field_name)
);
COMMENT ON TABLE governance.model_source_requirement_v1 IS '三大模型分阶段 source 字段覆盖度要求；release_gate、观察、回测、研究阶段必须分别定义阻断/降级策略。';
COMMENT ON COLUMN governance.model_source_requirement_v1.degrade_policy IS 'block/degrade/ignore_for_online/research_only；P0 official 字段不得静默降级。';
CREATE INDEX IF NOT EXISTS idx_model_source_requirement_phase_v1
    ON governance.model_source_requirement_v1 (model_code, model_phase, required_level);

CREATE TABLE IF NOT EXISTS governance.model_source_coverage_status_v1 (
    coverage_check_id TEXT PRIMARY KEY,
    model_code TEXT NOT NULL,
    model_phase TEXT NOT NULL,
    trade_date DATE NOT NULL,
    universe_size INTEGER NOT NULL,
    p0_field_count INTEGER NOT NULL,
    p0_passed_field_count INTEGER NOT NULL,
    p1_field_count INTEGER NOT NULL,
    p1_passed_field_count INTEGER NOT NULL,
    coverage_status TEXT NOT NULL,
    blocking_fields TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    degraded_fields TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    checked_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE governance.model_source_coverage_status_v1 IS '模型运行前 source 覆盖度检查结果；blocked 时禁止模型发布 official signal。';
CREATE INDEX IF NOT EXISTS idx_model_source_coverage_status_lookup_v1
    ON governance.model_source_coverage_status_v1 (model_code, model_phase, trade_date, checked_at DESC);

CREATE TABLE IF NOT EXISTS governance.model_release_preflight_v1 (
    preflight_id TEXT PRIMARY KEY,
    model_code TEXT NOT NULL,
    model_phase TEXT NOT NULL,
    trade_date DATE NOT NULL,
    can_release_official_signal BOOLEAN NOT NULL,
    coverage_status TEXT NOT NULL,
    freshness_status TEXT NOT NULL,
    blocking_reasons_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    degraded_reasons_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    repair_actions_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    checked_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE governance.model_release_preflight_v1 IS '模型 release_gate 前置检查结果；覆盖度、新鲜度、修复动作必须在模型调度前固化。';
CREATE INDEX IF NOT EXISTS idx_model_release_preflight_lookup_v1
    ON governance.model_release_preflight_v1 (model_code, model_phase, trade_date, checked_at DESC);

-- Operational guardrails for Codex and production operators:
-- 1. Models must not read raw_* tables directly.
-- 2. raw provider fetch -> raw ingest -> raw quality -> source build -> lineage -> coverage/freshness preflight is mandatory.
-- 3. If source-data-service Docker is healthy, ordinary model/service iterations must not stop or restart it.
-- 4. P0 official model release is blocked when coverage_status='blocked' or freshness_status='blocked'.
