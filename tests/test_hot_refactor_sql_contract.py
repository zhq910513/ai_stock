from pathlib import Path


def test_hot_refactor_sql_contains_required_source_and_decision_hot_tables() -> None:
    sql = Path("infra/sql/0002_source_decision_hot_refactor.sql").read_text()
    required_tables = [
        "source.daily_bar_v1",
        "source.minute_bar_v1",
        "source.auction_snapshot_v1",
        "decision_hot.hot_cycle_v1",
        "decision_hot.hot_cycle_day_snapshot_v1",
        "decision_hot.hot_decision_case_v1",
        "decision_hot.hot_initial_decision_snapshot_v1",
        "decision_hot.hot_release_gate_audit_v1",
        "decision_hot.hot_signal_fact_v1",
        "decision_hot.hot_buy_point_v1",
        "decision_hot.hot_observation_snapshot_v1",
        "decision_hot.hot_outcome_label_v1",
        "decision_hot.hot_failure_attribution_v1",
        "decision_hot.hot_first_output_distortion_analysis_v1",
        "decision_hot.hot_evolution_sample_v1",
        "decision_hot.hot_teacher_calibration_v1",
        "decision_hot.hot_research_sample_pool_v1",
        "decision_hot.hot_active_case_registry_v1",
        "decision_hot.hot_case_latest_state_v1",
        "decision_hot.hot_cycle_day_feature_v1",
        "decision_hot.hot_intraday_feature_snapshot_v1",
        "decision_hot.hot_execution_feature_snapshot_v1",
        "decision_hot.hot_calibration_job_v1",
        "decision_hot.hot_teacher_calibration_version_v1",
        "decision_hot.hot_candidate_model_version_v1",
        "decision_hot.hot_shadow_run_result_v1",
        "governance.model_signal_registry_v1",
        "governance.task_instance_v1",
        "governance.task_lease_v1",
        "governance.task_dead_letter_v1",
        "governance.task_run_log_v1",
    ]
    missing = [table for table in required_tables if table not in sql]
    assert missing == []
    assert "CREATE TABLE IF NOT EXISTS decision_hot.hot_initial_decision_snapshot_v1" in sql
    assert "UNIQUE(hot_case_id, observe_seq)" in sql
    assert "uq_hot_first_frozen_reference" in sql
    assert "uq_hot_active_cycle_symbol" in sql
    assert "idx_hot_active_due" in sql
