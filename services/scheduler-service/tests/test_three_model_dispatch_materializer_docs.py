from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import scheduler_service.api as scheduler_api
from scheduler_service.docs_sync import validate_scheduler_docs_sync
from scheduler_service.main import app
from scheduler_service.three_model_dispatch import (
    LIVE_DISPATCH_SAMPLE_TASKS,
    OFFICIAL_RELEASE_GATE_TASKS,
    OwnerEndpointRegistry,
    RESEARCH_PAYLOAD_ASSEMBLER_CONTRACT,
    ThreeModelLiveDispatcher,
    build_live_dispatch_sample_payload,
    preflight_model_dispatch_payload,
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


class ResearchAssemblyResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self.payload = payload
        self.text = ""

    def json(self):
        return self.payload


class ResearchAssemblyClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls = []

    def post(self, url, *, json, timeout):
        self.calls.append((url, json, timeout))
        return ResearchAssemblyResponse(200, self.payload)


def assembled_payload(payload: dict, *, source_preflight: bool = False) -> dict:
    assembled = {
        **payload,
        "payload_assembly_contract": RESEARCH_PAYLOAD_ASSEMBLER_CONTRACT,
        "payload_assembly_status": "assembled_research_payload",
        "payload_assembly_source": "research-service",
    }
    if source_preflight:
        assembled["source_preflight"] = {
            "can_release_official_signal": True,
            "coverage_status": "passed",
            "freshness_status": "passed",
            "blocking_reasons": [],
        }
    return assembled


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
        payload=assembled_payload(
            {"trading_day": "2026-06-12", "as_of_time_utc": "2026-06-12T08:05:00Z", "run_id": "memory-run-1"},
            source_preflight=True,
        ),
    )
    ambush_result = dispatcher.dispatch(
        "ambush.phase3.release_gate.close",
        payload=assembled_payload({"trading_day": "2026-06-12"}, source_preflight=True),
    )

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

    result = dispatcher.dispatch(
        "hot.release_gate.preopen",
        payload=assembled_payload(
            {"symbol": "000001", "as_of_time_utc": "2026-06-12T01:29:40Z"},
            source_preflight=True,
        ),
    )

    assert result.accepted is True
    assert result.url == "http://hot:8031/production/release-gate/evaluate"
    body = client.calls[0][1]
    assert body["payload"]["symbol"] == "000001"
    assert body["payload"]["_scheduler_context"]["is_official_publish"] is True
    assert body["as_of_time_utc"] == "2026-06-12T01:29:40Z"
    assert "as_of_time_utc" not in body["payload"]
    assert body["run_id"] == "hot.release_gate.preopen"


def test_source_fetch_task_dispatches_to_source_submit_contract() -> None:
    client = FakeClient()
    registry = OwnerEndpointRegistry.from_mapping({"source-data-service": "http://source:8041"})
    dispatcher = ThreeModelLiveDispatcher(registry, client=client)

    result = dispatcher.dispatch(
        "source.auction.collect.0915_0925",
        payload={
            "run_id": "auction-window-1",
            "source_table_name": "source.auction_snapshot_v1",
            "canonical_fields": ["symbol", "auction_price", "available_at"],
            "symbols": ["000063.SZ"],
            "trade_date": "2026-06-12",
            "trigger_type": "scheduled",
            "priority": "P0_urgent_release",
        },
    )

    assert result.accepted is True
    assert result.url == "http://source:8041/source/fetch/submit"
    body = client.calls[0][1]
    assert body["source_table_name"] == "source.auction_snapshot_v1"
    assert body["request_source"] == "scheduler-service"
    assert body["idempotency_key"] == "source.auction.collect.0915_0925:2026-06-12"
    assert "run_id" not in body
    assert "_scheduler_context" not in body


def test_three_model_live_dispatch_adapts_t_board_payload_contract() -> None:
    client = FakeClient()
    registry = OwnerEndpointRegistry.from_mapping({"t-board-relay-service": "http://tboard:8034"})
    dispatcher = ThreeModelLiveDispatcher(registry, client=client)

    result = dispatcher.dispatch(
        "t_relay.day2.trigger.rolling_5m",
        payload=assembled_payload(
            {
                "run_id": "t-relay-trigger-run",
                "as_of_time_utc": "2026-06-12T01:35:00Z",
                "day1_candidate_id": "tbr-day1-000759.SZ-2026-06-12",
                "day1_candidate_status": "rejected",
                "canonical_symbol": "000759.SZ",
                "day2_trade_date": "2026-06-12",
                "trigger_time": "09:35:00",
                "last_price_at_trigger": "5.78",
                "up_limit_price": "5.83",
                "distance_to_up_limit_pct": "0.008576",
                "market_context_status": "neutral",
                "p0_order_book_complete": True,
                "p0_trade_tick_complete": True,
                "aggressive_buy_sweep_amount": "121998001",
                "order_consumption_amount": "121998001",
            }
        ),
    )

    assert result.accepted is True
    assert result.url == "http://tboard:8034/t-board-relay/day2/trigger-check"
    body = client.calls[0][1]
    assert sorted(body.keys()) == ["as_of_time_utc", "payload", "run_id"]
    assert body["payload"]["canonical_symbol"] == "000759.SZ"
    assert body["payload"]["_scheduler_context"]["is_official_publish"] is False


def test_model_payload_preflight_blocks_scheduler_gap_and_sample_payloads() -> None:
    gap_payload = {
        "scheduler_payload_status": "blocked_payload_assembly_required",
        "source_gap_codes": ["scheduler_payload_assembly_required"],
    }
    gap_result = preflight_model_dispatch_payload("hot.release_gate.preopen", gap_payload)
    assert gap_result.valid is False
    assert "payload_assembly_required_gap_present" in gap_result.failure_codes

    sample_payload = build_live_dispatch_sample_payload("hot.release_gate.preopen")
    sample_result = preflight_model_dispatch_payload("hot.release_gate.preopen", sample_payload)
    assert sample_result.valid is False
    assert "sample_payload_marker_present" in sample_result.failure_codes

    client = FakeClient()
    registry = OwnerEndpointRegistry.from_mapping({"hot-candidates-service": "http://hot:8031"})
    dispatcher = ThreeModelLiveDispatcher(registry, client=client)
    with pytest.raises(RuntimeError, match="model payload preflight failed"):
        dispatcher.dispatch("hot.release_gate.preopen", payload=sample_payload)
    assert client.calls == []


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

    t_board_body = ThreeModelLiveDispatcher.request_body_for(tasks["t_relay.day1.scan.close"], build_live_dispatch_sample_payload("t_relay.day1.scan.close"))
    assert sorted(t_board_body.keys()) == ["as_of_time_utc", "rows", "run_id", "trade_date"]
    assert t_board_body["rows"][0]["symbol"] == "000759.SZ"


def test_live_dispatch_sample_api_exposes_scheduler_payload_and_owner_preview() -> None:
    client = TestClient(app)
    response = client.get("/scheduler/live-dispatch/sample/hot.release_gate.preopen")

    assert response.status_code == 200
    body = response.json()
    assert body["contract_kind"] == "scheduler_live_dispatch_sample_v1"
    assert body["task_code"] == "hot.release_gate.preopen"
    assert body["scheduler_trigger_payload"]["row"]["instrument_id"] == 63
    assert body["owner_request_body_preview"]["payload"]["row"]["symbol"] == "000063.SZ"

    snapshot_response = client.get("/scheduler/live-dispatch/sample/t_relay.observation.monitor.snapshot_5m")
    assert snapshot_response.status_code == 200
    snapshot_body = snapshot_response.json()
    assert snapshot_body["owner_endpoint_path"] == "/t-board-relay/observation-monitor/snapshot"
    assert snapshot_body["owner_request_body_preview"]["payload"]["monitor_interval_minutes"] == 5

    result_response = client.get("/scheduler/live-dispatch/sample/t_relay.live_result.compute_30m")
    assert result_response.status_code == 200
    result_body = result_response.json()
    assert result_body["owner_endpoint_path"] == "/t-board-relay/observation-monitor/snapshot"
    assert result_body["owner_request_body_preview"]["payload"]["monitor_interval_minutes"] == 30
    assert result_body["owner_request_body_preview"]["payload"]["result_kind"] == "model_result_30m"


def test_live_dispatch_sample_validation_api_covers_official_release_gates() -> None:
    response = TestClient(app).get("/scheduler/validate/live-dispatch-samples")

    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is True
    assert body["sample_version"] == "three_model_live_dispatch_sample_v1"
    assert set(OFFICIAL_RELEASE_GATE_TASKS).issubset({row["task_code"] for row in body["rows"]})
    assert {row["task_code"] for row in body["rows"]} == set(LIVE_DISPATCH_SAMPLE_TASKS)


def test_model_payload_requirements_and_preflight_api_expose_hard_guard() -> None:
    client = TestClient(app)
    requirements = client.get("/scheduler/model-payload/requirements")
    assert requirements.status_code == 200
    req_body = requirements.json()
    assert req_body["preflight_version"] == "scheduler_model_payload_preflight_v1"
    assert req_body["assembler_contract"] == RESEARCH_PAYLOAD_ASSEMBLER_CONTRACT
    assert any(row["task_code"] == "hot.release_gate.preopen" for row in req_body["tasks"])

    preflight = client.post(
        "/scheduler/model-payload/preflight",
        json={
            "task_code": "hot.release_gate.preopen",
            "payload": {
                "scheduler_payload_status": "blocked_payload_assembly_required",
                "contract_gaps": ["scheduler_payload_assembly_required"],
            },
        },
    )
    assert preflight.status_code == 200
    body = preflight.json()
    assert body["valid"] is False
    assert "payload_assembly_required_gap_present" in body["failure_codes"]
    assert "source_preflight_not_passed" in body["failure_codes"]


def test_scheduler_assemble_preflight_accepts_research_service_payload(monkeypatch) -> None:
    payload = assembled_payload(
        {
            "symbol": "000063.SZ",
            "run_id": "research-hot-run",
            "as_of_time_utc": "2026-06-12T01:29:30Z",
        },
        source_preflight=True,
    )
    fake_client = ResearchAssemblyClient(
        {
            "payload_assembly_contract": RESEARCH_PAYLOAD_ASSEMBLER_CONTRACT,
            "payload_assembly_status": "assembled_research_payload",
            "payload_assembly_source": "research-service:research_model_payload_assembler_v1",
            "task_code": "hot.release_gate.preopen",
            "owner_service": "hot-candidates-service",
            "gap_codes": [],
            "payload": payload,
        }
    )
    monkeypatch.setattr(scheduler_api.runtime, "client", fake_client)
    monkeypatch.setattr(scheduler_api.runtime, "research_service_base_url", "http://research:8029")

    response = TestClient(app).post(
        "/scheduler/model-payload/assemble-preflight",
        json={
            "task_code": "hot.release_gate.preopen",
            "symbol": "000063.SZ",
            "trade_date": "2026-06-12",
            "as_of_time_utc": "2026-06-12T01:29:30Z",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["contract_kind"] == "scheduler_research_payload_assemble_preflight_v1"
    assert body["dispatch_allowed"] is True
    assert body["scheduler_preflight"]["valid"] is True
    assert body["owner_request_body_preview"]["payload"]["symbol"] == "000063.SZ"
    assert fake_client.calls[0][0] == "http://research:8029/research/model-payload/assemble"
    assert fake_client.calls[0][1]["persist_audit"] is False


def test_scheduler_assemble_preflight_blocks_research_data_gap(monkeypatch) -> None:
    payload = {
        "payload_assembly_contract": RESEARCH_PAYLOAD_ASSEMBLER_CONTRACT,
        "payload_assembly_status": "blocked_data_gap",
        "payload_assembly_source": "research-service:research_model_payload_assembler_v1",
        "source_gap_codes": ["source_gap:source_preflight_not_passed"],
        "contract_gaps": ["source_gap:source_preflight_not_passed"],
    }
    fake_client = ResearchAssemblyClient(
        {
            "payload_assembly_contract": RESEARCH_PAYLOAD_ASSEMBLER_CONTRACT,
            "payload_assembly_status": "blocked_data_gap",
            "payload_assembly_source": "research-service:research_model_payload_assembler_v1",
            "task_code": "t_relay.day1.scan.close",
            "owner_service": "t-board-relay-service",
            "gap_codes": ["source_gap:source_preflight_not_passed"],
            "payload": payload,
        }
    )
    monkeypatch.setattr(scheduler_api.runtime, "client", fake_client)
    monkeypatch.setattr(scheduler_api.runtime, "research_service_base_url", "http://research:8029")

    response = TestClient(app).post(
        "/scheduler/model-payload/assemble-preflight",
        json={
            "task_code": "t_relay.day1.scan.close",
            "symbol": "000759.SZ",
            "trade_date": "2026-06-12",
            "as_of_time_utc": "2026-06-12T07:05:00Z",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["dispatch_allowed"] is False
    assert body["owner_request_body_preview"] is None
    assert body["scheduler_preflight"]["valid"] is False
    assert "payload_assembly_status_not_ready" in body["scheduler_preflight"]["failure_codes"]


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

    t_board = client.post(
        "/scheduler/trigger",
        json={"task_code": "t_relay.day2.trigger.rolling_5m", "dry_run": True, "payload": {"canonical_symbol": "000759.SZ"}},
    )
    assert t_board.status_code == 200
    assert t_board.json()["owner_service"] == "t-board-relay-service"


def test_materialize_three_model_day_has_deterministic_official_publish_instances() -> None:
    plan = materialize_three_model_day(trading_day=date(2026, 6, 12), include_research_intraday=True)
    assert plan["contract_kind"] == "three_model_materialized_day_v1"
    assert "hot.release_gate.preopen" in plan["official_publish_instances"]
    assert "memory.release_gate.close" in plan["official_publish_instances"]
    assert "ambush.phase3.release_gate.close" in plan["official_publish_instances"]
    assert "t_relay.day1.scan.close" not in plan["official_publish_instances"]
    rolling_triggers = [item for item in plan["instances"] if item["task_code"] == "t_relay.day2.trigger.rolling_5m"]
    assert len(rolling_triggers) == 13
    assert {item["run_slot"] for item in rolling_triggers} >= {"093000", "093500", "103000"}
    post_entry_monitors = [item for item in plan["instances"] if item["task_code"] == "t_relay.day2.post_entry.monitor"]
    post_entry_slots = {item["run_slot"] for item in post_entry_monitors}
    assert len(post_entry_monitors) == 49
    assert post_entry_slots >= {"093500", "113000", "130000", "150000"}
    assert "123000" not in post_entry_slots
    day3_open_checks = [item for item in plan["instances"] if item["task_code"] == "t_relay.day3.exit.open"]
    day3_open_slots = {item["run_slot"] for item in day3_open_checks}
    assert len(day3_open_checks) == 26
    assert day3_open_slots >= {"092500", "093000", "113000"}
    day3_tail_checks = [item for item in plan["instances"] if item["task_code"] == "t_relay.day3.exit.tail"]
    day3_tail_slots = {item["run_slot"] for item in day3_tail_checks}
    assert len(day3_tail_checks) == 25
    assert day3_tail_slots >= {"130000", "144000", "145500", "150000"}
    assert "123000" not in day3_tail_slots
    observation_snapshots = [item for item in plan["instances"] if item["task_code"] == "t_relay.observation.monitor.snapshot_5m"]
    snapshot_slots = {item["run_slot"] for item in observation_snapshots}
    assert len(observation_snapshots) == 50
    assert snapshot_slots >= {"093000", "113000", "130000", "150000"}
    assert "123000" not in snapshot_slots
    assert observation_snapshots[0]["append_only"] is True
    live_results = [item for item in plan["instances"] if item["task_code"] == "t_relay.live_result.compute_30m"]
    live_result_slots = {item["run_slot"] for item in live_results}
    assert len(live_results) == 10
    assert live_result_slots >= {"093200", "100200", "130200", "150200"}
    assert all(item["append_only"] is True for item in live_results)
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
    assert validation["missing_owner_endpoint_rows"] == []
