from __future__ import annotations

from fastapi.testclient import TestClient

from scheduler_service.main import app


def test_hot_plan_contains_release_gate_and_observation_tasks() -> None:
    body = TestClient(app).get("/scheduler/plan/hot-candidates").json()
    task_codes = {item["task_code"] for item in body["tasks"]}
    assert "hot.release_gate.preopen" in task_codes
    assert "hot.observe.intraday" in task_codes
    release_gate = next(item for item in body["tasks"] if item["task_code"] == "hot.release_gate.preopen")
    assert release_gate["is_official_publish"] is True
    source_tasks = [item for item in body["tasks"] if item["task_code"].startswith("source.")]
    assert source_tasks
    assert all(item["owner_service"] == "source-data-service" for item in source_tasks)
    assert all("source-data-service:/source/fetch/submit" in item["reads_from"] for item in source_tasks)
    assert not any(any(source.startswith("provider.") for source in item["reads_from"]) for item in body["tasks"])


def test_trigger_is_dry_run_and_refuses_fake_live_dispatch() -> None:
    client = TestClient(app)
    ok = client.post("/scheduler/trigger", json={"task_code": "hot.observe.intraday"})
    assert ok.status_code == 200
    assert ok.json()["dry_run"] is True
    refused = client.post("/scheduler/trigger", json={"task_code": "hot.observe.intraday", "dry_run": False})
    assert refused.status_code == 409


def test_hot_scheduler_plan_validation_enforces_single_release_publisher() -> None:
    from scheduler_service.hot_plan import validate_hot_plan_contract

    validation = validate_hot_plan_contract()
    assert validation["valid"] is True
    assert validation["official_publish_tasks"] == ["hot.release_gate.preopen"]
    assert validation["source_publish_violations"] == []
    assert validation["append_only_violations"] == []
    assert validation["provider_read_violations"] == []
    assert validation["raw_read_violations"] == []
    assert validation["source_wildcard_violations"] == []
    assert validation["source_orchestration_violations"] == []
