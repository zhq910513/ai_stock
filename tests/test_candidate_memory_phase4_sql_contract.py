from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "infra" / "sql" / "0006_decision_memory_phase4_production_chain_acceptance.sql").read_text(encoding="utf-8")


def test_phase4_sql_adds_production_chain_acceptance_tables_and_boundaries() -> None:
    required = [
        "decision_memory.memory_source_feature_snapshot_v1",
        "decision_memory.memory_stage_persistence_plan_v1",
        "decision_memory.memory_pre_signal_threshold_calibration_v1",
        "decision_memory.memory_multi_day_replay_validation_v1",
        "governance.model_phase_acceptance_check_v1",
        "new_cycle_exclusion",
        "pre_signal_lead_days",
        "tradable_success",
        "direction_success_execution_missed",
    ]
    missing = [item for item in required if item not in SQL]
    assert missing == []
    assert "model truth remains in decision_memory" in SQL.lower()
    assert "scheduler/governance tables do not store model labels or scores" in SQL.lower()
    assert "partition" in SQL.lower()
