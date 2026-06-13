from __future__ import annotations

from pathlib import Path

SQL = Path("infra/sql/0015_source_data_reliability_hardening_v1.sql").read_text(encoding="utf-8")


def test_reliability_hardening_adds_field_contract_and_availability_tables() -> None:
    for table in [
        "governance.source_field_contract_v1",
        "governance.provider_api_availability_v1",
        "governance.raw_ingest_batch_v1",
        "governance.source_canonical_build_rule_v1",
    ]:
        assert table in SQL


def test_reliability_hardening_documents_critical_fields_with_comments() -> None:
    required_comments = [
        "COMMENT ON TABLE source.daily_bar_v1",
        "COMMENT ON COLUMN source.daily_bar_v1.available_at",
        "COMMENT ON TABLE source.adjusted_daily_bar_v1",
        "COMMENT ON COLUMN source.adjusted_daily_bar_v1.adjusted_close",
        "COMMENT ON TABLE source.trade_status_v1",
        "COMMENT ON TABLE source.limit_price_v1",
        "COMMENT ON TABLE governance.source_gap_v1",
        "COMMENT ON TABLE governance.source_repair_task_v1",
    ]
    for item in required_comments:
        assert item in SQL


def test_reliability_hardening_indexes_lineage_and_contract_lookup() -> None:
    for index_name in [
        "idx_source_lineage_lookup_v1",
        "idx_source_field_contract_required_v1",
        "idx_provider_api_availability_latest_v1",
        "idx_raw_ingest_batch_api_status_v1",
    ]:
        assert index_name in SQL


def test_reliability_hardening_preserves_raw_first_and_available_at_guardrail() -> None:
    lowered = SQL.lower()
    assert "models must not read raw_* tables directly" in lowered
    assert "available_at must be <= model decision" in lowered
    assert "never use adjusted prices for real trade execution" in lowered
