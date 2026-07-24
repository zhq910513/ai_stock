from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from scheduler_service.api import router
from scheduler_service.runtime import SchedulerRuntime
from scheduler_service.source_schedule import (
    EXPLICIT_MODEL_STAGE_CANDIDATE_SOURCE,
    RESEARCH_PAYLOAD_REQUIRED_SOURCE_TABLES,
    due_source_fetch_instances,
    materialize_source_fetch_schedule,
    source_schedule_registry,
    validate_source_schedule_registry,
)
from scheduler_service.task_store import SchedulerSQLiteTaskStore


class FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, Any], text: str = "") -> None:
        self.status_code = status_code
        self.payload = payload
        self.text = text

    def json(self) -> dict[str, Any]:
        return self.payload


class SourceSubmitClient:
    def __init__(self) -> None:
        self.posts: list[tuple[str, dict[str, Any], float]] = []

    def get(self, url: str, *, timeout: float) -> FakeResponse:
        return FakeResponse(200, {"status": "ready"})

    def post(self, url: str, *, json: dict[str, Any], timeout: float) -> FakeResponse:
        self.posts.append((url, json, timeout))
        return FakeResponse(
            200,
            {
                "fetch_batch_id": "batch-source-time-wheel",
                "fetch_plan_id": "plan-source-time-wheel",
                "status": "queued",
                "queue_name": "urgent_release_gate_queue",
                "submitted_job_count": 1,
                "skipped_duplicate_count": 0,
                "callback_registered": False,
                "producer_ack": "accepted",
            },
        )


class FailingSourceSubmitClient(SourceSubmitClient):
    def post(self, url: str, *, json: dict[str, Any], timeout: float) -> FakeResponse:
        self.posts.append((url, json, timeout))
        return FakeResponse(503, {"status": "not_ready"}, text="source not ready")


class TimeoutSourceSubmitClient(SourceSubmitClient):
    def post(self, url: str, *, json: dict[str, Any], timeout: float) -> FakeResponse:
        self.posts.append((url, json, timeout))
        raise TimeoutError("source submit timed out")


class DuplicateSourceSubmitClient(SourceSubmitClient):
    def post(self, url: str, *, json: dict[str, Any], timeout: float) -> FakeResponse:
        self.posts.append((url, json, timeout))
        return FakeResponse(
            200,
            {
                "fetch_batch_id": "batch-source-duplicate",
                "fetch_plan_id": "plan-source-time-wheel",
                "status": "succeeded",
                "queue_name": "urgent_release_gate_queue",
                "submitted_job_count": 0,
                "skipped_duplicate_count": 1,
                "callback_registered": False,
                "producer_ack": "accepted_and_persisted_to_queue_contract",
            },
        )


def test_source_schedule_registry_is_complete_and_source_only() -> None:
    validation = validate_source_schedule_registry()

    assert validation["valid"] is True
    assert validation["schedule_count"] >= 14
    assert "minute_auction" in validation["groups"]
    assert "daily_close" in validation["groups"]
    assert "daily_preopen" in validation["groups"]
    assert "t_relay_day1_window" in validation["groups"]
    assert validation["provider_or_raw_violations"] == []
    assert validation["missing_research_payload_tables"] == []
    assert set(validation["research_payload_required_source_tables"]) == set(RESEARCH_PAYLOAD_REQUIRED_SOURCE_TABLES)
    scheduled_tables = {item["source_table_name"] for item in source_schedule_registry()}
    assert "source.limit_price_v1" in scheduled_tables
    assert "source.limit_event_v1" in scheduled_tables
    assert "source.ths_paid_limit_up_probability_v1" in scheduled_tables
    by_code = {item["schedule_code"]: item for item in source_schedule_registry()}
    paid_fetch = by_code["source.daily.ths_paid_probability_fetch"]
    paid_guard = by_code["source.daily.ths_paid_probability_deadline_guard"]
    assert by_code["source.daily.close_bars"]["symbol_scope"] == "full_a_share"
    assert by_code["source.minute.minute_bar"]["symbol_scope"] == "configured_symbols"
    assert by_code["source.window.t_relay_trade_tick"]["symbol_scope"] == "stage_candidates"
    assert paid_fetch["frequency"] == "daily 15:20,16:05,18:00,20:30 until next trading day 09:00"
    assert paid_fetch["owner_endpoint_path"] == "/source/ths/paid-probability/fetch-current-batch"
    assert paid_guard["frequency"] == "daily 09:01 checks unresolved candidate batches after their next trading day 09:00 deadline"
    assert paid_guard["owner_endpoint_path"] == "/source/ths/paid-probability/deadline-check"


def test_source_schedule_materializes_fetch_submit_contracts() -> None:
    result = materialize_source_fetch_schedule(
        trading_day=date(2026, 6, 12),
        symbols=["000063.SZ"],
        include_one_time=True,
    )

    assert any(item.schedule_code == "source.init.trade_calendar" for item in result)
    trade_calendar = next(item for item in result if item.schedule_code == "source.init.trade_calendar")
    assert trade_calendar.request_body["symbols"] == []
    assert trade_calendar.request_body["universe_scope"] == "explicit_symbols"
    auction = next(item for item in result if item.schedule_code == "source.minute.auction_snapshot")
    assert auction.request_body["source_table_name"] == "source.auction_snapshot_v1"
    assert auction.request_body["trigger_type"] == "model_release_preflight"
    assert auction.request_body["priority"] == "P0_urgent_release"
    assert auction.request_body["request_source"] == "scheduler-service"
    assert auction.request_body["symbols"] == ["000063.SZ"]
    assert auction.request_body["universe_scope"] == "explicit_symbols"
    assert auction.request_body["canonical_fields"] == [
        "virtual_open_price",
        "matched_volume",
        "matched_amount",
        "event_time",
    ]
    assert auction.request_body["idempotency_key"].startswith("scheduler:source.minute.auction_snapshot")
    auction_context = auction.request_body["orchestration_context"]
    assert auction_context["request_source"] == "scheduler-service"
    assert auction_context["schedule_code"] == "source.minute.auction_snapshot"
    assert auction_context["run_slot"] == "091500"
    assert auction_context["biz_key"] == "source.minute.auction_snapshot:2026-06-12:091500"
    assert auction_context["lifecycle_expires_at_local"] == "2026-06-12T09:25:00+08:00"
    minute_bars = [item for item in result if item.schedule_code == "source.minute.minute_bar"]
    assert [item.request_body["orchestration_context"]["run_slot"] for item in minute_bars[:2]] == ["093000", "093100"]
    assert minute_bars[0].request_body["idempotency_key"] != minute_bars[1].request_body["idempotency_key"]
    assert minute_bars[0].request_body["orchestration_context"]["lifecycle_expires_at_local"] == "2026-06-12T09:40:00+08:00"
    assert minute_bars[1].request_body["orchestration_context"]["lifecycle_expires_at_local"] == "2026-06-12T09:41:00+08:00"
    assert not auction.source_table_name.startswith("raw_")
    stock_master = next(item for item in result if item.schedule_code == "source.init.stock_master")
    limit_price = next(item for item in result if item.schedule_code == "source.daily.limit_price_preopen")
    limit_event = next(item for item in result if item.schedule_code == "source.window.limit_event_t_relay")
    assert stock_master.request_body["symbols"] == []
    assert stock_master.request_body["universe_scope"] == "full_a_share"
    assert limit_price.request_body["source_table_name"] == "source.limit_price_v1"
    assert limit_price.request_body["priority"] == "P0_urgent_release"
    assert limit_price.request_body["symbols"] == []
    assert limit_price.request_body["universe_scope"] == "full_a_share"
    assert limit_price.request_body["orchestration_context"]["lifecycle_expires_at_local"] == "2026-06-12T23:59:59+08:00"
    assert limit_event.request_body["source_table_name"] == "source.limit_event_v1"
    assert limit_event.request_body["trigger_type"] == "model_release_preflight"
    assert limit_event.request_body["symbols"] == []
    assert limit_event.request_body["universe_scope"] == "full_a_share"
    assert not any(item.schedule_code == "source.window.t_relay_trade_tick" for item in result)
    explicit_stage = materialize_source_fetch_schedule(
        trading_day=date(2026, 6, 12),
        stage_candidate_symbols_by_source={EXPLICIT_MODEL_STAGE_CANDIDATE_SOURCE: ["000063.SZ"]},
    )
    trade_tick = next(item for item in explicit_stage if item.schedule_code == "source.window.t_relay_trade_tick")
    assert trade_tick.request_body["symbols"] == ["000063.SZ"]
    assert trade_tick.request_body["universe_scope"] == "stage_candidates"
    paid_fetch = next(item for item in result if item.schedule_code == "source.daily.ths_paid_probability_fetch")
    paid_guard = next(item for item in result if item.schedule_code == "source.daily.ths_paid_probability_deadline_guard")
    assert paid_fetch.request_body["__source_endpoint_path"] == "/source/ths/paid-probability/fetch-current-batch"
    assert paid_fetch.request_body["source_table_name"] == "source.ths_paid_limit_up_probability_v1"
    assert paid_fetch.request_body["trade_date"] == "2026-06-12"
    assert paid_guard.request_body["__source_endpoint_path"] == "/source/ths/paid-probability/deadline-check"
    assert "trade_date" not in paid_guard.request_body


def test_due_source_instances_only_include_current_window_no_catch_up() -> None:
    due = due_source_fetch_instances(
        now=datetime(2026, 6, 12, 1, 15, tzinfo=timezone.utc),
        symbols=["000063.SZ"],
        lateness_seconds=60,
    )
    late = due_source_fetch_instances(
        now=datetime(2026, 6, 12, 8, 0, tzinfo=timezone.utc),
        symbols=["000063.SZ"],
        lateness_seconds=60,
    )

    assert any(item.schedule_code == "source.minute.auction_snapshot" for item in due)
    assert all(item.schedule_code != "source.minute.auction_snapshot" for item in late)


def test_runtime_source_schedule_catch_up_dry_run_does_not_submit() -> None:
    client = SourceSubmitClient()
    store = SchedulerSQLiteTaskStore()
    runtime = SchedulerRuntime(
        client=client,
        guard_mode="legacy_data_inspector",
        source_data_base_url="http://source-data-service:8041",
        source_time_wheel_symbols=["000063.SZ"],
        task_store=store,
        poll_seconds=1,
        request_timeout_seconds=1,
    )

    result = runtime.catch_up_source_schedule(
        trading_day=date(2026, 6, 22),
        schedule_codes=["source.daily.preopen_universe"],
        dispatch_immediately=True,
        dry_run=True,
        now=datetime(2026, 6, 22, 2, 0, tzinfo=timezone.utc),
    )

    assert result["contract_kind"] == "scheduler_source_schedule_catch_up_v1"
    assert result["dry_run"] is True
    assert result["selected_count"] == 1
    assert result["enqueued_task_ids"] == []
    assert client.posts == []
    request_body = result["instances"][0]["request_body"]
    assert request_body["source_table_name"] == "source.stock_universe_daily_v1"
    assert request_body["symbols"] == []
    assert request_body["universe_scope"] == "full_a_share"


def test_runtime_source_schedule_catch_up_submits_selected_official_instances() -> None:
    client = SourceSubmitClient()
    store = SchedulerSQLiteTaskStore()
    runtime = SchedulerRuntime(
        client=client,
        guard_mode="legacy_data_inspector",
        source_data_base_url="http://source-data-service:8041",
        source_time_wheel_symbols=["000063.SZ"],
        task_store=store,
        poll_seconds=1,
        request_timeout_seconds=1,
    )

    result = runtime.catch_up_source_schedule(
        trading_day=date(2026, 6, 22),
        schedule_codes=["source.daily.preopen_universe"],
        dispatch_immediately=True,
        dry_run=False,
        now=datetime(2026, 6, 22, 2, 0, tzinfo=timezone.utc),
    )

    assert result["dry_run"] is False
    assert result["selected_count"] == 1
    assert len(result["enqueued_task_ids"]) == 1
    assert len(result["dispatched"]) == 1
    url, payload, _timeout = client.posts[0]
    assert url == "http://source-data-service:8041/source/fetch/submit"
    assert payload["request_source"] == "scheduler-service"
    assert payload["trigger_type"] == "scheduled_periodic"
    assert payload["source_table_name"] == "source.stock_universe_daily_v1"
    assert payload["symbols"] == []
    assert payload["universe_scope"] == "full_a_share"
    assert result["dispatched"][0]["source_result_status"] == "submit_accepted_pending_source_build"


def test_runtime_source_schedule_duplicate_noop_is_terminal_audit_not_success() -> None:
    client = DuplicateSourceSubmitClient()
    store = SchedulerSQLiteTaskStore()
    runtime = SchedulerRuntime(
        client=client,
        guard_mode="legacy_data_inspector",
        task_store=store,
        poll_seconds=1,
        request_timeout_seconds=1,
    )

    result = runtime.catch_up_source_schedule(
        trading_day=date(2026, 6, 22),
        schedule_codes=["source.daily.preopen_universe"],
        dispatch_immediately=True,
        dry_run=False,
        force_resubmit=True,
        catch_up_run_id="duplicate-audit",
        now=datetime(2026, 6, 22, 2, 0, tzinfo=timezone.utc),
    )

    assert result["dispatched"][0]["source_result_status"] == "submit_duplicate_no_new_job"
    counts = store.status_counts(owner_services=("source-data-service",))
    assert counts["source_duplicate_skipped"] == 1
    assert "success" not in counts
    assert runtime.ready_snapshot()["checks"]["task_store"]["source"]["status"] == "ready"


def test_runtime_source_schedule_catch_up_force_resubmit_reconciles_existing_success() -> None:
    client = SourceSubmitClient()
    store = SchedulerSQLiteTaskStore()
    runtime = SchedulerRuntime(
        client=client,
        guard_mode="legacy_data_inspector",
        source_data_base_url="http://source-data-service:8041",
        task_store=store,
        poll_seconds=1,
        request_timeout_seconds=1,
    )

    first = runtime.catch_up_source_schedule(
        trading_day=date(2026, 6, 22),
        schedule_codes=["source.daily.preopen_universe"],
        dispatch_immediately=True,
        dry_run=False,
        now=datetime(2026, 6, 22, 2, 0, tzinfo=timezone.utc),
    )
    second = runtime.catch_up_source_schedule(
        trading_day=date(2026, 6, 22),
        schedule_codes=["source.daily.preopen_universe"],
        dispatch_immediately=True,
        dry_run=False,
        now=datetime(2026, 6, 22, 2, 1, tzinfo=timezone.utc),
    )
    forced = runtime.catch_up_source_schedule(
        trading_day=date(2026, 6, 22),
        schedule_codes=["source.daily.preopen_universe"],
        dispatch_immediately=True,
        dry_run=False,
        force_resubmit=True,
        catch_up_run_id="repair-universe",
        now=datetime(2026, 6, 22, 2, 2, tzinfo=timezone.utc),
    )

    assert len(first["dispatched"]) == 1
    assert second["dispatched"] == []
    assert len(forced["dispatched"]) == 1
    assert forced["instances"][0]["original_biz_key"] == "source.daily.preopen_universe:2026-06-22:090500"
    assert forced["instances"][0]["biz_key"].endswith(":catchup:repair-universe")
    assert client.posts[-1][1]["idempotency_key"].endswith(":catchup:repair-universe")


def test_runtime_source_schedule_catch_up_blocks_ths_paid_endpoints_without_explicit_allow() -> None:
    runtime = SchedulerRuntime(
        client=SourceSubmitClient(),
        guard_mode="legacy_data_inspector",
        task_store=SchedulerSQLiteTaskStore(),
        poll_seconds=1,
        request_timeout_seconds=1,
    )

    blocked = runtime.catch_up_source_schedule(
        trading_day=date(2026, 6, 22),
        schedule_codes=["source.daily.ths_paid_probability_fetch"],
        dry_run=True,
    )
    allowed = runtime.catch_up_source_schedule(
        trading_day=date(2026, 6, 22),
        schedule_codes=["source.daily.ths_paid_probability_fetch"],
        allow_ths_paid_probability_fetch=True,
        dry_run=True,
    )

    assert blocked["selected_count"] == 0
    assert blocked["excluded_count"] == 4
    assert {item["reason"] for item in blocked["excluded"]} == {
        "ths_paid_probability_fetch_requires_explicit_allow"
    }
    assert allowed["selected_count"] == 4
    assert all(
        item["request_body"]["__source_endpoint_path"] == "/source/ths/paid-probability/fetch-current-batch"
        for item in allowed["instances"]
    )


def test_source_schedule_catch_up_api_exposes_dry_run_preview() -> None:
    test_app = FastAPI()
    test_app.include_router(router)
    client = TestClient(test_app)

    response = client.post(
        "/scheduler/source-schedule/catch-up",
        json={
            "trading_day": "2099-06-22",
            "schedule_codes": ["source.daily.limit_price_preopen"],
            "dry_run": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["contract_kind"] == "scheduler_source_schedule_catch_up_v1"
    assert body["selected_count"] == 1
    assert body["instances"][0]["request_body"]["source_table_name"] == "source.limit_price_v1"
    assert body["instances"][0]["request_body"]["symbols"] == []
    assert body["instances"][0]["request_body"]["universe_scope"] == "full_a_share"


def test_runtime_source_time_wheel_dispatches_to_source_fetch_submit() -> None:
    client = SourceSubmitClient()
    store = SchedulerSQLiteTaskStore()
    runtime = SchedulerRuntime(
        client=client,
        guard_mode="legacy_data_inspector",
        source_data_base_url="http://source-data-service:8041",
        source_time_wheel_enabled=True,
        source_time_wheel_live_submit=True,
        source_time_wheel_symbols=["000063.SZ"],
        source_time_wheel_lateness_seconds=60,
        task_store=store,
        poll_seconds=1,
        request_timeout_seconds=1,
    )

    snapshot = runtime.run_source_time_wheel_once(now=datetime(2026, 6, 12, 1, 15, tzinfo=timezone.utc))

    assert snapshot["status"] == "ready"
    assert snapshot["details"]["due_count"] >= 1
    assert client.posts
    url, payload, _timeout = client.posts[0]
    assert url == "http://source-data-service:8041/source/fetch/submit"
    assert payload["request_source"] == "scheduler-service"
    assert payload["trigger_type"] in {"model_release_preflight", "scheduled_periodic"}
    assert snapshot["details"]["dispatched"][0]["source_result_status"] == "submit_accepted_pending_source_build"
    assert store.table_count("task_instance_v1") >= 1
    assert store.table_count("task_run_log_v1") >= 2


def test_runtime_source_time_wheel_dispatches_paid_probability_to_controlled_endpoint() -> None:
    client = SourceSubmitClient()
    store = SchedulerSQLiteTaskStore()
    runtime = SchedulerRuntime(
        client=client,
        guard_mode="legacy_data_inspector",
        source_data_base_url="http://source-data-service:8041",
        source_time_wheel_enabled=True,
        source_time_wheel_live_submit=True,
        source_time_wheel_symbols=["000063.SZ"],
        source_time_wheel_lateness_seconds=60,
        task_store=store,
        poll_seconds=1,
        request_timeout_seconds=1,
    )

    snapshot = runtime.run_source_time_wheel_once(now=datetime(2026, 6, 12, 7, 20, tzinfo=timezone.utc))

    assert snapshot["status"] == "ready"
    assert client.posts
    url, payload, _timeout = client.posts[0]
    assert url == "http://source-data-service:8041/source/ths/paid-probability/fetch-current-batch"
    assert payload["source_table_name"] == "source.ths_paid_limit_up_probability_v1"
    assert payload["request_source"] == "scheduler-service"
    assert "__source_endpoint_path" not in payload
    assert snapshot["details"]["dispatched"][0]["source_endpoint_path"] == "/source/ths/paid-probability/fetch-current-batch"


def test_runtime_source_time_wheel_blocks_on_submit_failure() -> None:
    client = FailingSourceSubmitClient()
    store = SchedulerSQLiteTaskStore()
    runtime = SchedulerRuntime(
        client=client,
        guard_mode="legacy_data_inspector",
        source_data_base_url="http://source-data-service:8041",
        source_time_wheel_enabled=True,
        source_time_wheel_live_submit=True,
        source_time_wheel_symbols=["000063.SZ"],
        source_time_wheel_lateness_seconds=60,
        task_store=store,
        poll_seconds=1,
        request_timeout_seconds=1,
    )

    snapshot = runtime.run_source_time_wheel_once(now=datetime(2026, 6, 12, 1, 15, tzinfo=timezone.utc))

    assert snapshot["status"] == "failed"
    assert "source fetch submit failed" in snapshot["error"]
    assert snapshot["details"]["dispatched"][0]["status_code"] == 503


def test_runtime_source_time_wheel_marks_submit_exception_without_stale_running() -> None:
    client = TimeoutSourceSubmitClient()
    store = SchedulerSQLiteTaskStore()
    runtime = SchedulerRuntime(
        client=client,
        guard_mode="legacy_data_inspector",
        source_data_base_url="http://source-data-service:8041",
        source_time_wheel_enabled=True,
        source_time_wheel_live_submit=True,
        source_time_wheel_symbols=["000063.SZ"],
        source_time_wheel_lateness_seconds=60,
        task_store=store,
        poll_seconds=1,
        request_timeout_seconds=1,
    )

    snapshot = runtime.run_source_time_wheel_once(now=datetime(2026, 6, 12, 1, 15, tzinfo=timezone.utc))

    assert snapshot["status"] == "failed"
    assert snapshot["details"]["dispatched"][0]["source_result_status"] == "submit_exception"
    assert snapshot["details"]["dispatched"][0]["status_code"] == 0
    counts = store.status_counts(owner_services=("source-data-service",))
    assert counts["retry_ready"] == 1
    assert counts.get("running", 0) == 0
def test_temporary_source_fetch_dry_run_and_reject_scheduled_periodic() -> None:
    test_app = FastAPI()
    test_app.include_router(router)
    client = TestClient(test_app)

    preview = client.post(
        "/scheduler/source-fetch/temporary",
        json={
            "requesting_service": "hot-candidates-service",
            "source_table_name": "source.minute_bar_v1",
            "canonical_fields": ["close_price"],
            "symbols": ["000063.SZ"],
            "trade_date": "2026-06-12",
            "trigger_type": "model_adhoc_request",
            "priority": "research",
            "dry_run": True,
        },
    )
    rejected = client.post(
        "/scheduler/source-fetch/temporary",
        json={
            "requesting_service": "hot-candidates-service",
            "source_table_name": "source.minute_bar_v1",
            "trigger_type": "scheduled_periodic",
        },
    )
    rejected_non_source = client.post(
        "/scheduler/source-fetch/temporary",
        json={
            "requesting_service": "hot-candidates-service",
            "source_table_name": "decision_hot.bad_table",
            "canonical_fields": ["close_price"],
            "trigger_type": "model_adhoc_request",
        },
    )
    rejected_missing_fields = client.post(
        "/scheduler/source-fetch/temporary",
        json={
            "requesting_service": "hot-candidates-service",
            "source_table_name": "source.minute_bar_v1",
            "trigger_type": "model_adhoc_request",
        },
    )

    assert preview.status_code == 200
    body = preview.json()
    assert body["owner_endpoint"] == "POST /source/fetch/submit"
    assert body["request_body_preview"]["request_source"] == "scheduler-service:hot-candidates-service"
    assert rejected.status_code == 409
    assert rejected_non_source.status_code == 409
    assert rejected_missing_fields.status_code == 409



def test_runtime_source_schedule_catch_up_excludes_expired_lifecycle_instances() -> None:
    runtime = SchedulerRuntime(
        client=SourceSubmitClient(),
        guard_mode="legacy_data_inspector",
        task_store=SchedulerSQLiteTaskStore(),
        poll_seconds=1,
        request_timeout_seconds=1,
    )

    expired = runtime.catch_up_source_schedule(
        trading_day=date(2026, 6, 12),
        schedule_codes=["source.minute.auction_snapshot"],
        dry_run=True,
        now=datetime(2026, 6, 12, 2, 0, tzinfo=timezone.utc),
        max_instances=100,
    )
    still_open_daily = runtime.catch_up_source_schedule(
        trading_day=date(2026, 6, 12),
        schedule_codes=["source.daily.limit_price_preopen"],
        dry_run=True,
        now=datetime(2026, 6, 12, 2, 0, tzinfo=timezone.utc),
        max_instances=100,
    )

    assert expired["selected_count"] == 0
    assert expired["excluded_count"] == 21
    assert {item["reason"] for item in expired["excluded"]} == {"lifecycle_expired"}
    assert still_open_daily["selected_count"] == 1
    assert still_open_daily["excluded_count"] == 0
