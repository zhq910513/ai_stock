from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "infra" / "sql" / "0005_decision_memory_phase3_production_repository_and_schedule.sql").read_text(encoding="utf-8")


def test_phase3_sql_adds_governance_watermarks_and_schedule_contract_without_model_truth() -> None:
    assert "CREATE TABLE IF NOT EXISTS governance.source_feature_watermark_v1" in SQL
    assert "CREATE TABLE IF NOT EXISTS governance.model_schedule_contract_v1" in SQL
    assert "CREATE TABLE IF NOT EXISTS decision_memory.memory_feature_readiness_audit_v1" in SQL
    assert "CREATE TABLE IF NOT EXISTS decision_memory.memory_due_observation_plan_v1" in SQL
    assert "scheduler/governance tables store orchestration metadata only" in SQL.lower()
    assert "model truth remains in decision_memory" in SQL.lower()
