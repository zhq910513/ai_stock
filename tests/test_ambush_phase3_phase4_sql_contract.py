from __future__ import annotations

from pathlib import Path

SQL = Path("infra/sql/0010_decision_ambush_phase3_phase4_finalization.sql").read_text()


def test_phase3_phase4_sql_is_additive_and_has_expected_tables() -> None:
    required = [
        "decision_ambush.deep_confirmation_pool_v1",
        "decision_ambush.ambush_feature_matrix_v1",
        "decision_ambush.ambush_score_fact_v1",
        "decision_ambush.ambush_release_gate_audit_v1",
        "decision_ambush.ambush_signal_fact_v1",
        "decision_ambush.ambush_buy_point_v1",
        "decision_ambush.ambush_observation_snapshot_v1",
        "decision_ambush.ambush_latest_state_v1",
        "decision_ambush.ambush_outcome_label_v1",
        "decision_ambush.ambush_failure_attribution_v1",
        "decision_ambush.ambush_evolution_sample_v1",
        "decision_ambush.ambush_formula_version_evaluation_v1",
    ]
    for table_name in required:
        assert f"CREATE TABLE IF NOT EXISTS {table_name}" in SQL
    assert "DROP TABLE" not in SQL.upper()
    assert "ALTER TABLE decision_hot" not in SQL
    assert "ALTER TABLE decision_memory" not in SQL


def test_phase3_phase4_sql_preserves_governance_and_append_only_fields() -> None:
    assert "formula_governance_json JSONB NOT NULL" in SQL
    assert "source_gap_codes_json JSONB" in SQL
    assert "append_only BOOLEAN NOT NULL DEFAULT TRUE" in SQL
    assert "release_decision TEXT NOT NULL" in SQL
    assert "signal_state TEXT NOT NULL" in SQL
