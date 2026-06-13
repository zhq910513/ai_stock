from __future__ import annotations

from pathlib import Path

SQL = Path("infra/sql/0011_scheduler_three_model_dispatch_v1.sql").read_text()


def test_scheduler_three_model_dispatch_sql_is_additive_and_governance_only() -> None:
    required = [
        "governance.owner_endpoint_registry_v1",
        "governance.task_definition_registry_v1",
        "governance.task_materialization_audit_v1",
        "governance.scheduler_docs_sync_audit_v1",
    ]
    for table_name in required:
        assert f"CREATE TABLE IF NOT EXISTS {table_name}" in SQL
    assert "DROP TABLE" not in SQL.upper()
    assert "ALTER TABLE decision_hot" not in SQL
    assert "ALTER TABLE decision_memory" not in SQL
    assert "ALTER TABLE decision_ambush" not in SQL


def test_scheduler_three_model_dispatch_sql_records_doc_and_idempotency_contracts() -> None:
    assert "idempotency_seed VARCHAR(192) NOT NULL" in SQL
    assert "docs_sync_version VARCHAR(96) NOT NULL" in SQL
    assert "missing_tokens_json JSONB NOT NULL DEFAULT '[]'::jsonb" in SQL
    assert "live_dispatch_version VARCHAR(96)" in SQL
