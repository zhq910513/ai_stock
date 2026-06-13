from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from scheduler_service.docs_sync import validate_scheduler_docs_sync
from scheduler_service.main import app
from scheduler_service.three_model_dispatch import (
    OFFICIAL_RELEASE_GATE_TASKS,
    OwnerEndpointRegistry,
    ThreeModelLiveDispatcher,
    build_live_dispatch_sample_payload,
)
from scheduler_service.three_model_plan import THREE_MODEL_TASKS
from scheduler_service.three_model_materializer import materialize_three_model_day


class FakeResponse:
    status_code = 200

    def json(self):
        return {"ok": True, "accepted": True}


class FakeClient:
    def __init__(self) -> None:
        self.calls = []

    def post(self, url, *, json, timeout):
        self.calls.append((url, json, timeout))
        return FakeResponse()


def test_three_model_live_dispatch_routes_memory_and_ambush_tasks_to_owner_endpoints() -> None:
    client = FakeClient()
    registry = OwnerEndpointRegistry.from_mapping(
        {
            "candidate-memory-service": "http://memory:8032",
            "ambush-watchlist-service": "http://ambush:8033",
        }
    )
    dispatcher = ThreeModelLiveDispatcher(registry, client=client)

    memory_result = dispatcher.dispatch(
        "memory.release_gate.close",
        payload={"trading_day": "2026-06-12", "as_of_time_utc": "2026-06-12T08:05:00Z", "run_id": "memory-run-1"},
    )
    ambush_result = dispatcher.dispatch("ambush.phase3.release_gate.close", payload={"trading_day": "2026-06-12"})

    assert memory_result.accepted is True
    assert memory_result.url == "http://memory:8032/production/release-gate/evaluate"
    assert ambush_result.accepted is True
    assert ambush_result.url == "http://ambush:8033/ambush/phase3/run"
    assert client.calls[0][1]["row"]["trading_day"] == "2026-06-12"
    assert client.calls[0][1]["row"]["_scheduler_context"]["is_official_publish"] is True
    assert client.calls[0][1]["as_of_time_utc"] == "2026-06-12T08:05:00Z"
    assert client.calls[0][1]["run_id"] == "memory-run-1"
    assert "as_of_time_utc" not in client.calls[0][1]["row"]
    assert "payload" not in client.calls[0][1]
    assert client.calls[1][1]["trading_day"] == "2026-06-12"
    assert client.calls[1][1]["_scheduler_context"]["is_official_publish"] is True
    assert "payload" not in client.calls[1][1]


def test_three_model_live_dispatch_adapts_hot_payload_contract() -> None:
    client = FakeClient()
    registry = OwnerEndpointRegistry.from_mapping({"hot-candidates-service": "http://hot:8031"})
    dispatcher = ThreeModelLiveDispatcher(registry, client=client)

    result = dispatcher.dispatch("hot.release_gate.preopen", payload={"symbol": "000001", "as_of_time_utc": "2026-06-12T01:29:40Z"})

    assert result.accepted is True
    assert result.url == "http://hot:8031/production/release-gate/evaluate"
    body = client.calls[0][1]
    assert body["payload"]["symbol"] == "000001"
    assert body["payload"]["_scheduler_context"]["is_official_publish"] is True
    assert body["as_of_time_utc"] == "2026-06-12T01:29:40Z"
    assert "as_of_time_utc" not in body["payload"]
    assert body["run_id"] == "hot.release_gate.preopen"


def test_official_release_gate_sample_payloads_match_owner_contracts() -> None:
    tasks = {task.task_code: task for task in THREE_MODEL_TASKS}

    for task_code in OFFICIAL_RELEASE_GATE_TASKS:
        payload = build_live_dispatch_sample_payload(task_code)
        body = ThreeModelLiveDispatcher.request_body_for(tasks[task_code], payload)
        assert "_scheduler_context" in str(body)

    hot_body = ThreeModelLiveDispatcher.request_body_for(tasks["hot.release_gate.preopen"], build_live_dispatch_sample_payload("hot.release_gate.preopen"))
    assert sorted(hot_body.keys()) == ["as_of_time_utc", "payload", "run_id"]
    assert hot_body["payload"]["row"]["instrument_id"] == 63
    assert "payload" not in hot_body["payload"]

    memory_body = ThreeModelLiveDispatcher.request_body_for(tasks["memory.release_gate.close"], build_live_dispatch_sample_payload("memory.release_gate.close"))
    assert sorted(memory_body.keys()) == ["as_of_time_utc", "row", "run_id"]
    assert memory_body["row"]["memory_id"] == "sample-memory-000063"
    assert "row" not in memory_body["row"]

    ambush_body = ThreeModelLiveDispatcher.request_body_for(tasks["ambush.phase3.release_gate.close"], build_live_dispatch_sample_payload("ambush.phase3.release_gate.close"))
    assert "payload" not in ambush_body
    assert ambush_body["instrument"]["exchange"] == "SZ"
    assert ambush_body["valley_watch"]["pool_state"] == "valley_watch"
    assert len(ambush_body["bars"]) >= 35


def test_live_dispatch_sample_api_exposes_scheduler_payload_and_owner_preview() -> None:
    client = TestClient(app)
    response = client.get("/scheduler/live-dispatch/sample/hot.release_gate.preopen")

    assert response.status_code == 200
    body = response.json()
    assert body["contract_kind"] == "scheduler_live_dispatch_sample_v1"
    assert body["task_code"] == "hot.release_gate.preopen"
    assert body["scheduler_trigger_payload"]["row"]["instrument_id"] == 63
    assert body["owner_request_body_preview"]["payload"]["row"]["symbol"] == "000063.SZ"


def test_live_dispatch_sample_validation_api_covers_official_release_gates() -> None:
    response = TestClient(app).get("/scheduler/validate/live-dispatch-samples")

    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is True
    assert body["sample_version"] == "three_model_live_dispatch_sample_v1"
    assert {row["task_code"] for row in body["rows"]} == set(OFFICIAL_RELEASE_GATE_TASKS)


def test_scheduler_trigger_supports_three_model_tasks_in_dry_run() -> None:
    client = TestClient(app)
    response = client.post(
        "/scheduler/trigger",
        json={"task_code": "ambush.phase3.release_gate.close", "dry_run": True, "payload": {"trading_day": "2026-06-12"}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is True
    assert body["owner_service"] == "ambush-watchlist-service"


def test_materialize_three_model_day_has_deterministic_official_publish_instances() -> None:
    plan = materialize_three_model_day(trading_day=date(2026, 6, 12), include_research_intraday=True)
    assert plan["contract_kind"] == "three_model_materialized_day_v1"
    assert "hot.release_gate.preopen" in plan["official_publish_instances"]
    assert "memory.release_gate.close" in plan["official_publish_instances"]
    assert "ambush.phase3.release_gate.close" in plan["official_publish_instances"]
    assert all(item["biz_key"].startswith(item["task_code"]) for item in plan["instances"])
    research = [item for item in plan["instances"] if item["run_slot"].startswith("research_")]
    assert research
    assert all(item["is_official_publish"] is False for item in research)


def test_materialize_api_exposes_three_model_day() -> None:
    response = TestClient(app).get("/scheduler/materialize/three-models", params={"trading_day": "2026-06-12"})
    assert response.status_code == 200
    body = response.json()
    assert body["trading_day"] == "2026-06-12"
    assert body["instance_count"] >= 20


def test_scheduler_documentation_sync_validation_matches_code() -> None:
    root = Path(__file__).resolve().parents[3]
    validation = validate_scheduler_docs_sync(root)
    assert validation["valid"] is True
    assert validation["missing_docs"] == []
    assert validation["missing_tokens"] == []
