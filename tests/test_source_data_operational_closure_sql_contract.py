from __future__ import annotations

from pathlib import Path

SQL = Path("infra/sql/0019_source_data_operational_closure_v1.sql").read_text(encoding="utf-8")


def test_ds6_operational_closure_tables_are_declared() -> None:
    required = [
        "governance.raw_interface_write_audit_v1",
        "governance.source_build_execution_result_v1",
        "governance.source_canonical_write_audit_v1",
        "governance.source_freshness_sla_v1",
        "governance.source_freshness_status_v1",
        "governance.source_storage_policy_v1",
        "governance.model_source_requirement_v1",
        "governance.model_source_coverage_status_v1",
        "governance.model_release_preflight_v1",
    ]
    for table in required:
        assert table in SQL


def test_ds6_tables_are_documented_for_operator_safety() -> None:
    for token in [
        "COMMENT ON TABLE governance.raw_interface_write_audit_v1",
        "COMMENT ON COLUMN governance.raw_interface_write_audit_v1.response_schema_hash",
        "COMMENT ON TABLE governance.source_build_execution_result_v1",
        "COMMENT ON COLUMN governance.source_canonical_write_audit_v1.available_at",
        "COMMENT ON TABLE governance.source_freshness_sla_v1",
        "COMMENT ON TABLE governance.source_storage_policy_v1",
        "COMMENT ON TABLE governance.model_source_requirement_v1",
        "COMMENT ON TABLE governance.model_release_preflight_v1",
    ]:
        assert token in SQL


def test_ds6_indexes_cover_repair_preflight_and_volume_paths() -> None:
    for index in [
        "idx_raw_interface_write_audit_lookup_v1",
        "idx_source_build_execution_result_trigger_v1",
        "idx_source_canonical_write_lookup_v1",
        "idx_source_freshness_status_lookup_v1",
        "idx_model_source_requirement_phase_v1",
        "idx_model_source_coverage_status_lookup_v1",
        "idx_model_release_preflight_lookup_v1",
    ]:
        assert index in SQL


def test_ds6_guardrails_keep_source_first_and_block_failed_preflight() -> None:
    lowered = SQL.lower()
    assert "models must not read raw_* tables directly" in lowered
    assert "raw provider fetch -> raw ingest -> raw quality -> source build -> lineage" in lowered
    assert "p0 official model release is blocked" in lowered
