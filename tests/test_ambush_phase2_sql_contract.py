from __future__ import annotations

from pathlib import Path

SQL = Path("infra/sql/0009_decision_ambush_phase2_valley_turn.sql").read_text()


def test_phase2_sql_is_additive_and_creates_expected_tables() -> None:
    required = [
        "decision_ambush.valley_watch_pool_v1",
        "decision_ambush.effective_turn_anchor_v1",
        "decision_ambush.effective_turn_pool_v1",
        "decision_ambush.ambush_pool_transition_audit_v1",
    ]
    for table_name in required:
        assert f"CREATE TABLE IF NOT EXISTS {table_name}" in SQL
    assert "DROP TABLE" not in SQL.upper()
    assert "ALTER TABLE decision_hot" not in SQL
    assert "ALTER TABLE decision_memory" not in SQL


def test_phase2_sql_records_formula_and_pattern_versions() -> None:
    assert "formula_version TEXT NOT NULL" in SQL
    assert "pattern_library_version TEXT" in SQL
    assert "price_adjustment_mode TEXT NOT NULL" in SQL
    assert "source_gap_codes_json JSONB" in SQL
    assert "formula_governance_json JSONB" in SQL
