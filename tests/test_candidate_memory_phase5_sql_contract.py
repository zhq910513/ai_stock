from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "infra" / "sql" / "0007_decision_memory_phase5_closed_loop_finalization.sql").read_text(encoding="utf-8")


def test_phase5_sql_adds_closed_loop_finalization_tables_and_guardrails() -> None:
    required = [
        "decision_memory.memory_closure_pipeline_v1",
        "decision_memory.memory_up_reason_attribution_v1",
        "decision_memory.memory_failure_attribution_v1",
        "decision_memory.memory_evolution_sample_v1",
        "decision_memory.memory_model_version_shadow_evaluation_v1",
        "governance.model_phase_final_acceptance_v1",
        "ex_ante_message_guardrail",
        "mature_outcome_only_evolution",
        "new_independent_cycle_exclusion",
        "shadow_evaluation_required_before_version_promotion",
    ]
    missing = [item for item in required if item not in SQL]
    assert missing == []
    assert "model truth remains in decision_memory" in SQL.lower()
    assert "scheduler/governance tables do not store model labels or scores" in SQL.lower()
    assert "partition" in SQL.lower()
