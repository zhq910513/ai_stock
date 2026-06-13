from __future__ import annotations

from pathlib import Path


def test_ambush_phase1_sql_declares_independent_schema_and_pattern_tables() -> None:
    sql = Path("infra/sql/0008_decision_ambush_phase1_pattern_library.sql").read_text()
    assert "CREATE SCHEMA IF NOT EXISTS decision_ambush" in sql
    assert "governance.source_capability_audit_v1" in sql
    assert "decision_ambush.valley_pattern_sample_v1" in sql
    assert "decision_ambush.valley_shape_signature_v1" in sql
    assert "decision_ambush.valley_pattern_prototype_v1" in sql
    assert "decision_ambush.valley_pattern_match_result_v1" in sql
    assert "decision_ambush.ambush_recall_candidate_v1" in sql
    assert "decision_ambush.ambush_formula_registry_v1" in sql


def test_ambush_phase1_sql_preserves_positive_negative_and_hard_negative_contract() -> None:
    sql = Path("infra/sql/0008_decision_ambush_phase1_pattern_library.sql").read_text()
    assert "hard_negative_sample_count" in sql
    assert "hard_negative_flag" in sql
    assert "strong_positive" in sql
    assert "weak_positive" in sql
    assert "hard_negative" in sql
    assert "easy_negative" in sql
    assert "positive_valley_similarity" in sql
    assert "false_bottom_similarity" in sql
    assert "hard_negative_similarity" in sql
    assert "shape_edge_score" in sql


def test_ambush_phase1_sql_contains_formula_and_future_data_guardrails() -> None:
    sql = Path("infra/sql/0008_decision_ambush_phase1_pattern_library.sql").read_text()
    assert "formula_version" in sql
    assert "online recall and scoring must not" in sql
    assert "adjusted OHLC" in sql
    assert "raw OHLC without adjustment is research-only" in sql
    assert "Online matching stores TopK only" in sql
