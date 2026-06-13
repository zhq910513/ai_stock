from __future__ import annotations

from fastapi.testclient import TestClient

from scheduler_service.main import app
from scheduler_service.three_model_plan import validate_three_model_plan_contract


def test_three_model_plan_exposes_all_release_gate_publishers() -> None:
    body = TestClient(app).get("/scheduler/plan/three-models").json()
    task_codes = {item["task_code"] for item in body["tasks"]}
    assert "hot.release_gate.preopen" in task_codes
    assert "memory.release_gate.close" in task_codes
    assert "ambush.phase3.release_gate.close" in task_codes
    publishers = [item["task_code"] for item in body["tasks"] if item["is_official_publish"]]
    assert publishers == ["hot.release_gate.preopen", "memory.release_gate.close", "ambush.phase3.release_gate.close"]


def test_three_model_plan_validation_enforces_guardrails() -> None:
    validation = validate_three_model_plan_contract()
    assert validation["valid"] is True
    assert validation["source_publish_violations"] == []
    assert validation["append_only_violations"] == []
    assert validation["direct_cross_model_write_violations"] == []
