from __future__ import annotations

from fastapi.testclient import TestClient

from scheduler_service.main import app
from scheduler_service.three_model_plan import THREE_MODEL_SCHEDULER_VERSION, validate_three_model_plan_contract


def test_three_model_plan_exposes_all_release_gate_publishers() -> None:
    body = TestClient(app).get("/scheduler/plan/three-models").json()
    assert body["plan_version"] == THREE_MODEL_SCHEDULER_VERSION
    tasks = {item["task_code"]: item for item in body["tasks"]}
    task_codes = set(tasks)
    assert "hot.release_gate.preopen" in task_codes
    assert "memory.release_gate.close" in task_codes
    assert "ambush.phase3.release_gate.close" in task_codes
    assert "t_relay.day1.scan.close" in task_codes
    assert "t_relay.day2.trigger.rolling_5m" in task_codes
    assert "t_relay.observation.monitor.snapshot_5m" in task_codes
    assert "t_relay.live_result.compute_30m" in task_codes
    assert tasks["t_relay.observation.monitor.snapshot_5m"]["append_only"] is True
    assert tasks["t_relay.observation.monitor.snapshot_5m"]["writes_to"] == [
        "decision_t_relay.t_board_observation_monitor_snapshot_v1"
    ]
    assert tasks["t_relay.live_result.compute_30m"]["append_only"] is True
    assert tasks["t_relay.live_result.compute_30m"]["writes_to"] == [
        "decision_t_relay.t_board_observation_monitor_snapshot_v1"
    ]
    publishers = [item["task_code"] for item in body["tasks"] if item["is_official_publish"]]
    assert publishers == ["hot.release_gate.preopen", "memory.release_gate.close", "ambush.phase3.release_gate.close"]
    assert not any(item["is_official_publish"] for item in body["tasks"] if item["task_code"].startswith("t_relay."))
    source_tasks = [item for item in body["tasks"] if item["task_code"].startswith("source.")]
    assert source_tasks
    assert all(item["owner_service"] == "source-data-service" for item in source_tasks)
    assert all("source-data-service:/source/fetch/submit" in item["reads_from"] for item in source_tasks)
    assert not any(any(source.startswith("provider.") for source in item["reads_from"]) for item in body["tasks"])
    assert not any(item["owner_service"] == "execution-timing-service" for item in body["tasks"])
    assert tasks["memory.pre_signal.scan"]["writes_to"] == [
        "decision_memory.memory_pre_signal_case_v1",
        "decision_memory.memory_score_fact_v1",
    ]
    assert tasks["memory.release_gate.close"]["reads_from"] == [
        "decision_memory.memory_pre_signal_case_v1",
        "decision_memory.memory_score_fact_v1",
    ]
    assert not any(
        "decision_memory.pre_signal_case_v1" in table
        for item in body["tasks"]
        for table in item["reads_from"] + item["writes_to"]
    )


def test_three_model_plan_validation_enforces_guardrails() -> None:
    validation = validate_three_model_plan_contract()
    assert validation["valid"] is True
    assert validation["source_publish_violations"] == []
    assert validation["append_only_violations"] == []
    assert validation["direct_cross_model_write_violations"] == []
    assert validation["provider_read_violations"] == []
    assert validation["raw_read_violations"] == []
    assert validation["source_wildcard_violations"] == []
    assert validation["source_read_schedule_violations"] == []
    assert validation["source_orchestration_violations"] == []
    assert validation["missing_current_owner_violations"] == []
