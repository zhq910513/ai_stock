from __future__ import annotations

from pathlib import Path

SQL = Path("infra/sql/0020_source_data_production_readiness_v1.sql").read_text(encoding="utf-8")


def test_ds7_acceptance_tables_are_declared() -> None:
    for table in [
        "governance.source_data_acceptance_run_v1",
        "governance.source_data_acceptance_check_v1",
    ]:
        assert table in SQL


def test_ds7_acceptance_tables_have_operator_evidence_fields() -> None:
    for token in [
        "version_label",
        "require_postgres",
        "require_real_provider_probe",
        "can_lock_candidate",
        "blocking_reasons_json",
        "warning_reasons_json",
        "evidence_json",
        "operator_action",
    ]:
        assert token in SQL


def test_ds7_acceptance_tables_are_commented_and_indexed() -> None:
    for token in [
        "COMMENT ON TABLE governance.source_data_acceptance_run_v1",
        "COMMENT ON TABLE governance.source_data_acceptance_check_v1",
        "idx_source_data_acceptance_run_status_v1",
        "idx_source_data_acceptance_check_status_v1",
    ]:
        assert token in SQL
