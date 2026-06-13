from pathlib import Path


def test_candidate_memory_sql_contains_independent_model_domain_tables() -> None:
    sql = Path("infra/sql/0003_decision_memory_model_v1.sql").read_text()
    required_tables = [
        "decision_memory.memory_seed_v1",
        "decision_memory.memory_entity_v1",
        "decision_memory.memory_initial_snapshot_v1",
        "decision_memory.memory_observation_snapshot_v1",
        "decision_memory.memory_price_structure_feature_v1",
        "decision_memory.memory_moneyflow_feature_v1",
        "decision_memory.memory_sector_theme_feature_v1",
        "decision_memory.memory_event_signal_feature_v1",
        "decision_memory.memory_pre_signal_feature_window_v1",
        "decision_memory.memory_pre_signal_case_v1",
        "decision_memory.memory_activation_case_v1",
        "decision_memory.memory_score_fact_v1",
        "decision_memory.memory_release_gate_audit_v1",
        "decision_memory.memory_signal_fact_v1",
        "decision_memory.memory_buy_point_v1",
        "decision_memory.memory_monitoring_snapshot_v1",
        "decision_memory.memory_outcome_label_v1",
        "decision_memory.memory_up_reason_attribution_v1",
        "decision_memory.memory_pre_limitup_signal_analysis_v1",
        "decision_memory.memory_failure_attribution_v1",
        "decision_memory.memory_evolution_sample_v1",
        "decision_memory.memory_ttl_calibration_v1",
        "decision_memory.memory_model_version_evaluation_v1",
        "decision_memory.memory_active_case_registry_v1",
        "decision_memory.memory_latest_state_v1",
    ]
    missing = [table for table in required_tables if table not in sql]
    assert missing == []
    sql_without_comments = "\n".join(line for line in sql.splitlines() if not line.strip().startswith("--"))
    assert "decision_hot." not in sql_without_comments
    assert "available_at TIMESTAMPTZ NOT NULL" in sql
    assert "post_hoc" in sql
    assert "uq_memory_active_signal_entity" in sql
    assert "idx_memory_active_due" in sql


def test_candidate_memory_phase2_sql_contains_source_relationship_and_uplift_tables() -> None:
    sql = Path("infra/sql/0004_decision_memory_phase2_research_calibration.sql").read_text()
    required = [
        "source.stock_theme_link_v1",
        "source.event_entity_link_v1",
        "decision_memory.memory_matched_control_uplift_v1",
        "decision_memory.memory_event_signal_feature_batch_v1",
        "available_at TIMESTAMPTZ NOT NULL",
        "feature_batch_payload_json JSONB NOT NULL",
        "uplift_rate_pct NUMERIC",
    ]
    missing = [item for item in required if item not in sql]
    assert missing == []
    assert "model truth remains in decision_memory" in sql
    assert "partition" in sql.lower()
