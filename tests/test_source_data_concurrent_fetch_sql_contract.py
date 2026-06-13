from __future__ import annotations

from pathlib import Path

SQL = Path("infra/sql/0017_source_data_concurrent_fetch_orchestration_v1.sql").read_text(encoding="utf-8")


def test_concurrent_fetch_tables_are_declared() -> None:
    required = [
        "governance.provider_rate_limit_policy_v1",
        "governance.raw_fetch_batch_v1",
        "governance.raw_fetch_job_item_v1",
        "governance.raw_fetch_callback_event_v1",
        "governance.provider_runtime_status_v1",
        "governance.source_build_trigger_v1",
    ]
    for table in required:
        assert table in SQL


def test_concurrent_fetch_tables_have_comments_for_operator_usage() -> None:
    assert "COMMENT ON TABLE governance.provider_rate_limit_policy_v1" in SQL
    assert "COMMENT ON TABLE governance.raw_fetch_batch_v1" in SQL
    assert "COMMENT ON TABLE governance.raw_fetch_job_item_v1" in SQL
    assert "COMMENT ON TABLE governance.raw_fetch_callback_event_v1" in SQL
    assert "COMMENT ON TABLE governance.source_build_trigger_v1" in SQL
    assert "source_lineage_v1" in SQL


def test_fetch_jobs_have_idempotency_and_queue_indexes() -> None:
    assert "UNIQUE (provider, api_name, raw_table_name, request_hash)" in SQL
    assert "idx_raw_fetch_job_queue_status_v1" in SQL
    assert "idx_raw_fetch_job_lease_v1" in SQL
    assert "idx_raw_fetch_callback_batch_v1" in SQL
