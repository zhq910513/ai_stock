from __future__ import annotations

from pathlib import Path

SQL = Path("infra/sql/0016_source_data_operational_readiness_v1.sql").read_text(encoding="utf-8")


def test_operational_readiness_tables_are_declared() -> None:
    required = [
        "governance.provider_probe_matrix_v1",
        "governance.raw_quality_check_result_v1",
        "governance.source_build_batch_v1",
        "governance.source_readiness_evidence_v1",
        "governance.source_field_repair_route_v1",
    ]
    for table in required:
        assert table in SQL


def test_operational_tables_are_documented_with_comments() -> None:
    assert "COMMENT ON TABLE governance.provider_probe_matrix_v1" in SQL
    assert "COMMENT ON TABLE governance.raw_quality_check_result_v1" in SQL
    assert "COMMENT ON TABLE governance.source_build_batch_v1" in SQL
    assert "COMMENT ON TABLE governance.source_readiness_evidence_v1" in SQL
    assert "COMMENT ON TABLE governance.source_field_repair_route_v1" in SQL


def test_repair_route_and_readiness_indexes_exist() -> None:
    assert "idx_source_field_repair_route_lookup_v1" in SQL
    assert "idx_source_readiness_field_v1" in SQL
    assert "idx_source_build_batch_status_v1" in SQL
