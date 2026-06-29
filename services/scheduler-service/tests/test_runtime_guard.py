from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from scheduler_service.runtime import DEFAULT_MARKET_TZ, SCHEDULER_RUNTIME_VERSION, SchedulerRuntime
from scheduler_service.task_store import SchedulerSQLiteTaskStore


class FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, Any], text: str = "") -> None:
        self.status_code = status_code
        self.payload = payload
        self.text = text

    def json(self) -> dict[str, Any]:
        return self.payload


class FakeListResponse(FakeResponse):
    def __init__(self, status_code: int, payload: list[dict[str, Any]], text: str = "") -> None:
        self.status_code = status_code
        self.payload = payload
        self.text = text

    def json(self) -> list[dict[str, Any]]:
        return self.payload


class ReadyInspectorClient:
    def __init__(self) -> None:
        self.gets: list[tuple[str, float]] = []
        self.posts: list[tuple[str, dict[str, Any], float]] = []

    def get(self, url: str, *, timeout: float) -> FakeResponse:
        self.gets.append((url, timeout))
        return FakeResponse(200, {"status": "ready", "service": "data-inspector-service"})

    def post(self, url: str, *, json: dict[str, Any], timeout: float) -> FakeResponse:
        self.posts.append((url, json, timeout))
        return FakeResponse(
            201,
            {
                "run_id": "startup-1",
                "status": "ready",
                "p0_gap_count": 0,
                "p1_gap_count": 0,
            },
        )


class DelayedInspectorClient(ReadyInspectorClient):
    def __init__(self) -> None:
        super().__init__()
        self.fail_first_get = True

    def get(self, url: str, *, timeout: float) -> FakeResponse:
        self.gets.append((url, timeout))
        if self.fail_first_get:
            self.fail_first_get = False
            return FakeResponse(503, {"status": "not_ready"}, text="not ready")
        return FakeResponse(200, {"status": "ready", "service": "data-inspector-service"})


class SourceRowsClient(ReadyInspectorClient):
    def get(self, url: str, *, timeout: float) -> FakeResponse:
        self.gets.append((url, timeout))
        if "/source/rows?" in url and "source.limit_event_v1" in url:
            return FakeListResponse(
                200,
                [
                    {
                        "symbol": "000048.SZ",
                        "values": {
                            "limit_event_type": "t_board_limit_up",
                            "is_break_limit": True,
                            "close_on_limit_flag": True,
                        },
                    },
                    {
                        "symbol": "000751.SZ",
                        "values": {
                            "limit_event_type": "limit_up",
                            "is_break_limit": False,
                            "close_on_limit_flag": True,
                        },
                    },
                ],
            )
        return super().get(url, timeout=timeout)


class SourceSubmitClient(ReadyInspectorClient):
    def post(self, url: str, *, json: dict[str, Any], timeout: float) -> FakeResponse:
        self.posts.append((url, json, timeout))
        if url.endswith("/source/fetch/submit"):
            return FakeResponse(
                200,
                {
                    "fetch_batch_id": "batch-recovered-stale-running",
                    "queue_name": "normal_daily_ingest_queue",
                    "status": "queued",
                },
            )
        return super().post(url, json=json, timeout=timeout)


def test_runtime_guard_requires_background_data_inspector_and_startup_guard() -> None:
    client = ReadyInspectorClient()
    runtime = SchedulerRuntime(
        client=client,
        guard_mode="legacy_data_inspector",
        data_inspector_base_url="http://data-inspector:8025",
        poll_seconds=1,
        request_timeout_seconds=1,
        startup_guard_max_subjects=1,
        source_time_wheel_enabled=False,
        task_store=SchedulerSQLiteTaskStore(),
    )

    runtime.run_startup_cycle()
    snapshot = runtime.ready_snapshot()

    assert snapshot["status"] == "ready"
    assert snapshot["runtime_version"] == SCHEDULER_RUNTIME_VERSION
    assert snapshot["checks"]["background_loop"]["status"] == "ready"
    assert snapshot["checks"]["data_inspector"]["status"] == "ready"
    assert snapshot["checks"]["startup_guard"]["status"] == "ready"
    assert snapshot["checks"]["startup_guard"]["run_id"] == "startup-1"
    assert client.gets[0][0] == "http://data-inspector:8025/readyz"
    assert client.posts[0][0] == "http://data-inspector:8025/inspection-runs"
    assert client.posts[0][1]["scope"] == "startup_guard"
    assert client.posts[0][1]["as_of_trading_day"] == "2026-06-12"
    assert client.posts[0][1]["persist"] is True
    assert client.posts[0][1]["max_subjects"] == 1


def test_runtime_guard_retries_startup_guard_after_data_inspector_becomes_ready() -> None:
    client = DelayedInspectorClient()
    runtime = SchedulerRuntime(
        client=client,
        guard_mode="legacy_data_inspector",
        data_inspector_base_url="http://data-inspector:8025",
        poll_seconds=1,
        request_timeout_seconds=1,
        startup_guard_max_subjects=1,
        source_time_wheel_enabled=False,
        task_store=SchedulerSQLiteTaskStore(),
    )

    runtime.run_startup_cycle()
    first = runtime.ready_snapshot()
    runtime.run_startup_cycle()
    second = runtime.ready_snapshot()

    assert first["status"] == "not_ready"
    assert first["checks"]["data_inspector"]["status"] == "not_ready"
    assert first["checks"]["startup_guard"]["status"] == "not_started"
    assert second["status"] == "ready"
    assert len(client.posts) == 1


def test_source_schedule_catch_up_resolves_t_relay_candidates_from_limit_events() -> None:
    client = SourceRowsClient()
    runtime = SchedulerRuntime(
        client=client,
        poll_seconds=1,
        request_timeout_seconds=1,
        source_time_wheel_enabled=False,
        task_store=SchedulerSQLiteTaskStore(),
    )

    result = runtime.catch_up_source_schedule(
        trading_day=datetime(2026, 6, 22).date(),
        schedule_groups=["t_relay_day1_candidate_facts"],
        dry_run=True,
        max_instances=20,
    )

    assert result["selected_count"] == 12
    assert result["stage_candidate_sources"]["t_relay_limit_event_t_board"]["symbols"] == ["000048.SZ"]
    assert all(instance["request_body"]["symbols"] == ["000048.SZ"] for instance in result["instances"])
    assert not any("000063.SZ" in instance["request_body"]["symbols"] for instance in result["instances"])
    assert any("/source/rows?source_table_name=source.limit_event_v1" in url for url, _ in client.gets)


def test_source_time_wheel_recovers_expired_running_before_dispatch() -> None:
    client = SourceSubmitClient()
    store = SchedulerSQLiteTaskStore()
    now = datetime(2026, 6, 26, 1, 0, tzinfo=timezone.utc)
    task_id = store.enqueue(
        task_code="source.minute.realtime_quote",
        owner_service="source-data-service",
        biz_key="stale-running-source-task",
        scheduled_at=now,
        payload={
            "source_table_name": "source.realtime_quote_v1",
            "canonical_fields": ["last_price"],
            "trigger_type": "scheduled_periodic",
            "priority": "P1_normal",
            "request_source": "scheduler-service",
        },
    )
    store.acquire_lease(task_id, lease_owner="scheduler-source-time-wheel", now=now, lease_seconds=1)
    runtime = SchedulerRuntime(
        client=client,
        guard_mode="legacy_data_inspector",
        poll_seconds=1,
        request_timeout_seconds=1,
        source_time_wheel_enabled=True,
        source_time_wheel_live_submit=True,
        source_time_wheel_lateness_seconds=0,
        model_time_wheel_enabled=False,
        task_store=store,
    )

    result = runtime.run_source_time_wheel_once(now=now + timedelta(seconds=120))

    assert result["status"] == "ready"
    assert result["details"]["recovered_expired_running_count"] == 1
    assert result["details"]["recovered_expired_running"][0]["task_instance_id"] == task_id
    assert result["details"]["dispatched"][0]["task_instance_id"] == task_id
    assert result["details"]["status_counts"]["success"] >= 1
    assert any(post[0] == "http://source-data-service:8041/source/fetch/submit" for post in client.posts)


def test_readyz_blocks_source_task_store_dead_letter() -> None:
    client = ReadyInspectorClient()
    store = SchedulerSQLiteTaskStore()
    now = datetime(2026, 6, 26, 1, 0, tzinfo=timezone.utc)
    task_id = store.enqueue(
        task_code="source.minute.auction_snapshot",
        owner_service="source-data-service",
        biz_key="auction-dead-letter",
        scheduled_at=now,
        payload={"source_table_name": "source.auction_snapshot_v1"},
    )
    store.acquire_lease(task_id, lease_owner="scheduler-source-time-wheel", now=now)
    for _ in range(4):
        store.mark_failure(task_id, error_code="source_fetch_submit_failed", error_message="boom", max_retries=3)
    runtime = SchedulerRuntime(
        client=client,
        guard_mode="legacy_data_inspector",
        poll_seconds=1,
        request_timeout_seconds=1,
        source_time_wheel_enabled=False,
        model_time_wheel_enabled=False,
        task_store=store,
    )

    runtime.run_startup_cycle()
    snapshot = runtime.ready_snapshot()

    assert snapshot["status"] == "not_ready"
    source_health = snapshot["checks"]["task_store"]["source"]
    assert source_health["status"] == "not_ready"
    assert source_health["status_counts"]["dead_letter"] == 1
    assert "dead_letter" in source_health["blocking_statuses"]


class BlockedInspectorClient(ReadyInspectorClient):
    def post(self, url: str, *, json: dict[str, Any], timeout: float) -> FakeResponse:
        self.posts.append((url, json, timeout))
        return FakeResponse(
            201,
            {
                "run_id": "startup-blocked",
                "status": "blocked",
                "p0_gap_count": 1,
                "p1_gap_count": 2,
            },
            text='{"status":"blocked","p0_gap_count":1,"p1_gap_count":2}',
        )


class CurrentClosureClient:
    def __init__(
        self,
        *,
        preflight_blocked: bool = False,
        preflight_blocking_reasons: list[str] | None = None,
        preflight_coverage_status: str | None = None,
        preflight_freshness_status: str | None = None,
        inspection_blocked: bool = False,
        blocked_scope: str = "startup_guard",
        core_closure_self_gap_only: bool = False,
        unreachable_models: set[str] | None = None,
    ) -> None:
        self.preflight_blocked = preflight_blocked
        self.preflight_blocking_reasons = preflight_blocking_reasons
        self.preflight_coverage_status = preflight_coverage_status
        self.preflight_freshness_status = preflight_freshness_status
        self.inspection_blocked = inspection_blocked
        self.blocked_scope = blocked_scope
        self.core_closure_self_gap_only = core_closure_self_gap_only
        self.unreachable_models = unreachable_models or set()
        self.gets: list[tuple[str, float]] = []
        self.posts: list[tuple[str, dict[str, Any], float]] = []

    def get(self, url: str, *, timeout: float) -> FakeResponse:
        self.gets.append((url, timeout))
        model_hosts = {
            "hot_candidates": "hot-candidates-service",
            "candidate_memory": "candidate-memory-service",
            "ambush_watchlist": "ambush-watchlist-service",
            "t_board_relay": "t-board-relay-service",
        }
        for model_code, host in model_hosts.items():
            if model_code in self.unreachable_models and host in url:
                raise OSError("Name or service not known")
        if "/inspection-runs/latest?scope=" in url:
            blocked = self.inspection_blocked and f"scope={self.blocked_scope}" in url
            if self.core_closure_self_gap_only and "scope=core_closure" in url:
                blocked = True
            return FakeResponse(
                200,
                {
                    "run_id": "latest-inspection",
                    "as_of_trading_day": "2026-06-12",
                    "status": "blocked" if blocked else "ready",
                    "gap_count": 1 if blocked else 0,
                    "p0_gap_count": 1 if blocked else 0,
                    "p1_gap_count": 0,
                    "finished_at": "2026-06-14T00:00:00Z",
                },
            )
        if "/inspection-gaps?run_id=latest-inspection" in url:
            return FakeResponse(
                200,
                {
                    "response": [
                        {
                            "domain_code": "scheduler_ready" if self.core_closure_self_gap_only else "source_lineage_presence",
                            "severity": "P0",
                        }
                    ]
                },
            )
        if url.endswith("/readyz"):
            return FakeResponse(200, {"status": "ready"})
        if "/source/ops/production-readiness" in url:
            return FakeResponse(200, {"status": "passed", "can拍板": True})
        if url.endswith("/source/fetch/queues/summary"):
            return FakeResponse(
                200,
                {
                    "rows": [
                        {"queue_name": "urgent_release_gate_queue", "leased_count": 0, "dead_letter_count": 0},
                        {"queue_name": "normal_daily_ingest_queue", "leased_count": 0, "dead_letter_count": 0},
                    ]
                },
            )
        return FakeResponse(404, {"status": "not_found"}, text="not found")

    def post(self, url: str, *, json: dict[str, Any], timeout: float) -> FakeResponse:
        self.posts.append((url, json, timeout))
        if url.endswith("/inspection-runs"):
            return FakeResponse(
                201,
                {
                    "run_id": "current-startup",
                    "status": "ready",
                    "p0_gap_count": 0,
                    "p1_gap_count": 0,
                },
            )
        blocked = self.preflight_blocked and json["model_code"] == "hot_candidates"
        blocking_reasons = (
            self.preflight_blocking_reasons
            if self.preflight_blocking_reasons is not None
            else ["source.trade_status_v1.is_tradable"]
        )
        return FakeResponse(
            200,
            {
                "can_release_official_signal": not blocked,
                "coverage_status": self.preflight_coverage_status or ("blocked" if blocked else "passed"),
                "freshness_status": self.preflight_freshness_status or ("blocked" if blocked else "passed"),
                "blocking_reasons": blocking_reasons if blocked else [],
                "degraded_reasons": [],
            },
        )


def test_legacy_runtime_guard_rejects_blocked_startup_inspection() -> None:
    client = BlockedInspectorClient()
    runtime = SchedulerRuntime(
        client=client,
        guard_mode="legacy_data_inspector",
        data_inspector_base_url="http://data-inspector:8025",
        poll_seconds=1,
        request_timeout_seconds=1,
        startup_guard_max_subjects=1,
        source_time_wheel_enabled=False,
    )

    runtime.run_startup_cycle()
    snapshot = runtime.ready_snapshot()

    assert snapshot["status"] == "not_ready"
    assert snapshot["checks"]["startup_guard"]["status"] == "failed"
    assert snapshot["checks"]["startup_guard"]["inspection_status"] == "blocked"
    assert snapshot["checks"]["startup_guard"]["p0_gap_count"] == 1


def test_current_closure_guard_requires_source_model_queue_and_preflight_ready() -> None:
    client = CurrentClosureClient()
    runtime = SchedulerRuntime(
        client=client,
        poll_seconds=1,
        request_timeout_seconds=1,
        source_time_wheel_enabled=False,
        task_store=SchedulerSQLiteTaskStore(),
    )

    runtime.run_startup_cycle()
    snapshot = runtime.ready_snapshot()

    assert snapshot["status"] == "ready"
    assert snapshot["checks"]["data_inspector"]["status"] == "ready"
    assert snapshot["checks"]["startup_guard"]["status"] == "ready"
    assert snapshot["checks"]["startup_guard"]["run_id"] == "current-startup"
    assert snapshot["checks"]["closure_guard"]["mode"] == "current_closure"
    assert snapshot["checks"]["closure_guard"]["status"] == "ready"
    latest_gets = [get for get, _ in client.gets if "/inspection-runs/latest" in get]
    assert latest_gets == [
        "http://data-inspector-service:8025/inspection-runs/latest?scope=startup_guard&as_of_trading_day=2026-06-12",
        "http://data-inspector-service:8025/inspection-runs/latest?scope=core_closure&as_of_trading_day=2026-06-12",
    ]
    preflight_posts = [post for post in client.posts if post[0].endswith("/source/release/preflight")]
    assert len(preflight_posts) == 5
    hot_post = next(post for post in preflight_posts if post[1]["model_code"] == "hot_candidates")
    assert hot_post[1]["decision_time"] == "2026-06-12T09:29:40+08:00"
    assert snapshot["checks"]["closure_guard"]["details"]["preflight"]["hot_candidates.preopen_release_gate"]["decision_time"] == "2026-06-12T09:29:40+08:00"
    t_board_posts = [post for post in preflight_posts if post[1]["model_code"] == "t_board_relay"]
    assert {post[1]["model_phase"] for post in t_board_posts} == {"day1_scan", "day2_trigger"}
    assert all(post[1]["symbols"] == ["000759.SZ"] for post in t_board_posts)


def test_current_closure_guard_skips_policy_disabled_model_readyz() -> None:
    client = CurrentClosureClient(unreachable_models={"hot_candidates", "candidate_memory", "ambush_watchlist", "t_board_relay"})
    runtime = SchedulerRuntime(
        client=client,
        poll_seconds=1,
        request_timeout_seconds=1,
        source_time_wheel_enabled=False,
        task_store=SchedulerSQLiteTaskStore(),
        required_model_services="none",
    )

    runtime.run_startup_cycle()
    snapshot = runtime.ready_snapshot()

    assert snapshot["status"] == "ready"
    models = snapshot["checks"]["closure_guard"]["details"]["models"]
    assert {code: detail["status"] for code, detail in models.items()} == {
        "hot_candidates": "disabled_by_policy",
        "candidate_memory": "disabled_by_policy",
        "ambush_watchlist": "disabled_by_policy",
        "t_board_relay": "disabled_by_policy",
    }
    assert all(detail["required"] is False for detail in models.values())
    model_gets = [url for url, _ in client.gets if "candidates-service" in url or "memory-service" in url or "watchlist-service" in url or "relay-service" in url]
    assert model_gets == []
    assert len([post for post in client.posts if post[0].endswith("/source/release/preflight")]) == 5


def test_current_closure_guard_rejects_required_model_unreachable() -> None:
    client = CurrentClosureClient(unreachable_models={"t_board_relay"})
    runtime = SchedulerRuntime(
        client=client,
        poll_seconds=1,
        request_timeout_seconds=1,
        source_time_wheel_enabled=False,
        task_store=SchedulerSQLiteTaskStore(),
        required_model_services="t_board_relay",
    )

    runtime.run_startup_cycle()
    snapshot = runtime.ready_snapshot()

    assert snapshot["status"] == "not_ready"
    assert snapshot["checks"]["closure_guard"]["status"] == "failed"
    assert "t_board_relay readyz not ready" in snapshot["checks"]["closure_guard"]["error"]
    assert snapshot["checks"]["closure_guard"]["details"]["models"]["hot_candidates"]["status"] == "disabled_by_policy"
    assert snapshot["checks"]["closure_guard"]["details"]["models"]["t_board_relay"]["required"] is True


def test_current_closure_guard_rejects_blocked_source_preflight() -> None:
    client = CurrentClosureClient(preflight_blocked=True)
    runtime = SchedulerRuntime(
        client=client,
        poll_seconds=1,
        request_timeout_seconds=1,
        source_time_wheel_enabled=False,
        task_store=SchedulerSQLiteTaskStore(),
    )

    runtime.run_startup_cycle()
    snapshot = runtime.ready_snapshot()

    assert snapshot["status"] == "not_ready"
    assert snapshot["checks"]["closure_guard"]["status"] == "failed"
    assert "source release preflight blocked" in snapshot["checks"]["closure_guard"]["error"]


def test_current_closure_guard_tolerates_historical_late_only_source_preflight_for_readyz() -> None:
    client = CurrentClosureClient(
        preflight_blocked=True,
        preflight_blocking_reasons=["source.daily_bar_v1.close_price:000063.SZ:late"],
        preflight_coverage_status="passed",
        preflight_freshness_status="blocked",
    )
    runtime = SchedulerRuntime(
        client=client,
        guard_trade_date="2000-01-03",
        poll_seconds=1,
        request_timeout_seconds=1,
        source_time_wheel_enabled=False,
        task_store=SchedulerSQLiteTaskStore(),
    )

    runtime.run_startup_cycle()
    snapshot = runtime.ready_snapshot()

    assert snapshot["status"] == "ready"
    assert snapshot["checks"]["closure_guard"]["status"] == "ready"
    detail = snapshot["checks"]["closure_guard"]["details"]["preflight"]["hot_candidates.preopen_release_gate"]
    assert detail["can_release_official_signal"] is False
    assert detail["blocking_reasons"] == ["source.daily_bar_v1.close_price:000063.SZ:late"]
    assert detail["historical_late_observed"] is True
    assert detail["ignored_for_readyz"] is True
    assert detail["official_release_preflight_still_blocked"] is True


def test_current_closure_guard_rejects_historical_missing_source_preflight() -> None:
    client = CurrentClosureClient(
        preflight_blocked=True,
        preflight_blocking_reasons=["source.daily_bar_v1.close_price:000063.SZ:missing"],
        preflight_coverage_status="passed",
        preflight_freshness_status="blocked",
    )
    runtime = SchedulerRuntime(
        client=client,
        guard_trade_date="2000-01-03",
        poll_seconds=1,
        request_timeout_seconds=1,
        source_time_wheel_enabled=False,
        task_store=SchedulerSQLiteTaskStore(),
    )

    runtime.run_startup_cycle()
    snapshot = runtime.ready_snapshot()

    assert snapshot["status"] == "not_ready"
    assert snapshot["checks"]["closure_guard"]["status"] == "failed"
    detail = snapshot["checks"]["closure_guard"]["details"]["preflight"]["hot_candidates.preopen_release_gate"]
    assert detail["ignored_for_readyz"] is False
    assert "source release preflight blocked" in snapshot["checks"]["closure_guard"]["error"]


def test_current_closure_guard_rejects_current_date_late_source_preflight() -> None:
    current_guard_date = datetime.now(ZoneInfo(DEFAULT_MARKET_TZ)).date().isoformat()
    client = CurrentClosureClient(
        preflight_blocked=True,
        preflight_blocking_reasons=["source.daily_bar_v1.close_price:000063.SZ:late"],
        preflight_coverage_status="passed",
        preflight_freshness_status="blocked",
    )
    runtime = SchedulerRuntime(
        client=client,
        guard_trade_date=current_guard_date,
        poll_seconds=1,
        request_timeout_seconds=1,
        source_time_wheel_enabled=False,
        task_store=SchedulerSQLiteTaskStore(),
    )

    runtime.run_startup_cycle()
    snapshot = runtime.ready_snapshot()

    assert snapshot["status"] == "not_ready"
    assert snapshot["checks"]["closure_guard"]["status"] == "failed"
    detail = snapshot["checks"]["closure_guard"]["details"]["preflight"]["hot_candidates.preopen_release_gate"]
    assert detail["historical_late_observed"] is False
    assert detail["ignored_for_readyz"] is False


def test_current_closure_guard_rejects_blocked_data_inspection() -> None:
    client = CurrentClosureClient(inspection_blocked=True)
    runtime = SchedulerRuntime(
        client=client,
        poll_seconds=1,
        request_timeout_seconds=1,
        source_time_wheel_enabled=False,
        task_store=SchedulerSQLiteTaskStore(),
    )

    runtime.run_startup_cycle()
    snapshot = runtime.ready_snapshot()

    assert snapshot["status"] == "not_ready"
    assert snapshot["checks"]["data_inspector"]["status"] == "ready"
    assert snapshot["checks"]["startup_guard"]["status"] == "ready"
    assert snapshot["checks"]["closure_guard"]["status"] == "failed"
    assert "data inspection startup_guard not ready" in snapshot["checks"]["closure_guard"]["error"]


def test_current_closure_guard_tolerates_core_closure_scheduler_self_gap_only() -> None:
    client = CurrentClosureClient(core_closure_self_gap_only=True)
    runtime = SchedulerRuntime(
        client=client,
        poll_seconds=1,
        request_timeout_seconds=1,
        source_time_wheel_enabled=False,
        task_store=SchedulerSQLiteTaskStore(),
    )

    runtime.run_startup_cycle()
    snapshot = runtime.ready_snapshot()

    assert snapshot["status"] == "ready"
    details = snapshot["checks"]["closure_guard"]["details"]["data_inspector"]
    assert details["latest_core_closure"]["self_dependency_ignored"] is True
    assert details["core_closure_p0_gap_codes"] == ["scheduler_ready"]


def test_current_closure_guard_rejects_core_closure_non_self_gap() -> None:
    client = CurrentClosureClient(inspection_blocked=True, blocked_scope="core_closure")
    runtime = SchedulerRuntime(client=client, poll_seconds=1, request_timeout_seconds=1, source_time_wheel_enabled=False)

    runtime.run_startup_cycle()
    snapshot = runtime.ready_snapshot()

    assert snapshot["status"] == "not_ready"
    assert snapshot["checks"]["closure_guard"]["status"] == "failed"
    assert "data inspection core_closure not ready" in snapshot["checks"]["closure_guard"]["error"]


def test_model_time_wheel_enqueues_due_model_tasks_without_live_dispatch_by_default() -> None:
    client = ReadyInspectorClient()
    runtime = SchedulerRuntime(
        client=client,
        guard_mode="legacy_data_inspector",
        poll_seconds=1,
        request_timeout_seconds=1,
        source_time_wheel_enabled=False,
        model_time_wheel_enabled=True,
        model_time_wheel_live_dispatch=False,
        model_time_wheel_lateness_seconds=60,
        task_store=SchedulerSQLiteTaskStore(),
    )

    result = runtime.run_model_time_wheel_once(now=datetime(2026, 6, 12, 1, 29, 40, tzinfo=timezone.utc))

    assert result["status"] == "ready"
    assert result["live_dispatch"] is False
    assert result["details"]["due_count"] >= 1
    assert result["details"]["enqueued_task_ids"]
    assert result["details"]["dispatched"] == []
    assert "live_dispatch_disabled" in result["details"]["skipped"]
    assert runtime.task_store.table_count("task_instance_v1") >= 1


def test_model_time_wheel_skips_policy_disabled_owner_tasks() -> None:
    client = ReadyInspectorClient()
    runtime = SchedulerRuntime(
        client=client,
        guard_mode="legacy_data_inspector",
        poll_seconds=1,
        request_timeout_seconds=1,
        source_time_wheel_enabled=False,
        model_time_wheel_enabled=True,
        model_time_wheel_live_dispatch=True,
        model_time_wheel_lateness_seconds=60,
        task_store=SchedulerSQLiteTaskStore(),
        required_model_services="none",
    )

    result = runtime.run_model_time_wheel_once(now=datetime(2026, 6, 12, 1, 26, 0, tzinfo=timezone.utc))

    assert result["status"] == "ready"
    assert result["details"]["due_count"] >= 1
    assert result["details"]["enqueued_task_ids"] == []
    assert result["details"]["dispatched"] == []
    assert result["details"]["research_execution"] == []
    assert result["details"]["status_counts"] == {}
    assert any(item["reason"] == "disabled_by_policy" for item in result["details"]["skipped"])
    assert runtime.task_store.table_count("task_instance_v1") == 0


class ResearchExecutionClient(ReadyInspectorClient):
    def __init__(self, *, blocked: bool = False) -> None:
        super().__init__()
        self.blocked = blocked

    def post(self, url: str, *, json: dict[str, Any], timeout: float) -> FakeResponse:
        self.posts.append((url, json, timeout))
        if url.endswith("/research/model-execution/run"):
            if self.blocked:
                return FakeResponse(
                    200,
                    {
                        "accepted": False,
                        "execution_status": "blocked_data_gap",
                        "execution_id": "exec-blocked",
                        "gap_codes": ["source_gap:daily_bar_missing"],
                    },
                )
            return FakeResponse(
                200,
                {
                    "accepted": True,
                    "execution_status": "materialized",
                    "execution_id": "exec-1",
                    "gap_codes": [],
                    "materialized_counts": {"decision_hot.hot_score_fact_v1": 1},
                },
            )
        return super().post(url, json=json, timeout=timeout)


def test_model_time_wheel_live_dispatch_calls_research_execution_not_owner() -> None:
    client = ResearchExecutionClient()
    runtime = SchedulerRuntime(
        client=client,
        guard_mode="legacy_data_inspector",
        poll_seconds=1,
        request_timeout_seconds=1,
        source_time_wheel_enabled=False,
        model_time_wheel_enabled=True,
        model_time_wheel_live_dispatch=True,
        model_time_wheel_lateness_seconds=60,
        task_store=SchedulerSQLiteTaskStore(),
    )

    result = runtime.run_model_time_wheel_once(now=datetime(2026, 6, 12, 1, 26, 0, tzinfo=timezone.utc))

    assert result["status"] == "ready"
    assert result["details"]["research_execution"][0]["accepted"] is True
    assert result["details"]["research_execution"][0]["execution_status"] == "materialized"
    research_posts = [post for post in client.posts if post[0] == "http://research-service:8029/research/model-execution/run"]
    assert research_posts
    assert all(post[0] == "http://research-service:8029/research/model-execution/run" for post in client.posts)
    assert all(post[1]["symbol"] in {"000063.SZ", "000759.SZ"} for post in research_posts)
    assert "hot.score.auction_confirmed" in {post[1]["task_code"] for post in research_posts}
    assert not any("/production/" in post[0] for post in client.posts)


def test_t_relay_day1_model_catch_up_uses_limit_event_stage_candidates() -> None:
    client = SourceRowsClient()
    runtime = SchedulerRuntime(
        client=client,
        guard_mode="legacy_data_inspector",
        poll_seconds=1,
        request_timeout_seconds=1,
        source_time_wheel_enabled=False,
        model_time_wheel_enabled=True,
        task_store=SchedulerSQLiteTaskStore(),
        required_model_services="t_board_relay",
    )

    result = runtime.catch_up_model_schedule(
        trading_day=datetime(2026, 6, 22).date(),
        task_codes=["t_relay.day1.scan.close"],
        run_slots=["153000"],
        dry_run=True,
        max_instances=5,
        now=datetime(2026, 6, 22, 8, 0, 0, tzinfo=timezone.utc),
    )

    assert result["selected_count"] == 1
    payload = result["instances"][0]["scheduler_payload"]
    assert payload["symbol"] == "000048.SZ"
    assert payload["symbols"] == ["000048.SZ"]
    assert payload["source_gap_codes"] == []
    materialized = payload["_scheduler_materialized_instance"]
    assert materialized["stage_candidate_source"] == "t_relay_limit_event_t_board"
    assert materialized["stage_candidate_count"] == 1
    assert any("/source/rows?source_table_name=source.limit_event_v1" in url for url, _ in client.gets)


def test_t_relay_day1_model_time_wheel_blocks_empty_stage_candidates_before_research() -> None:
    client = ResearchExecutionClient()
    runtime = SchedulerRuntime(
        client=client,
        guard_mode="legacy_data_inspector",
        poll_seconds=1,
        request_timeout_seconds=1,
        source_time_wheel_enabled=False,
        model_time_wheel_enabled=True,
        model_time_wheel_live_dispatch=True,
        model_time_wheel_lateness_seconds=60,
        task_store=SchedulerSQLiteTaskStore(),
        required_model_services="t_board_relay",
    )

    result = runtime.run_model_time_wheel_once(now=datetime(2026, 6, 12, 7, 5, 0, tzinfo=timezone.utc))

    assert result["status"] == "ready"
    execution = result["details"]["research_execution"][0]
    assert execution["task_code"] == "t_relay.day1.scan.close"
    assert execution["execution_status"] == "blocked_data_gap"
    assert execution["accepted"] is False
    assert execution["completed"] is True
    assert execution["terminal_non_success"] is True
    assert execution["gap_codes"] == ["source_gap:t_relay_day1_stage_candidates_missing"]
    assert not any(post[0] == "http://research-service:8029/research/model-execution/run" for post in client.posts)
    assert runtime.task_store.status_counts(owner_services=("t-board-relay-service",))["blocked_data_gap"] == 1


def test_model_schedule_catch_up_dry_run_selects_observation_snapshot_slot() -> None:
    client = ReadyInspectorClient()
    runtime = SchedulerRuntime(
        client=client,
        guard_mode="legacy_data_inspector",
        poll_seconds=1,
        request_timeout_seconds=1,
        source_time_wheel_enabled=False,
        model_time_wheel_enabled=True,
        task_store=SchedulerSQLiteTaskStore(),
        required_model_services="t_board_relay",
    )
    checked_at = datetime(2026, 6, 24, 2, 15, 0, tzinfo=timezone.utc)

    result = runtime.catch_up_model_schedule(
        trading_day=datetime(2026, 6, 24).date(),
        task_codes=["t_relay.observation.monitor.snapshot_5m"],
        run_slots=["093500"],
        dry_run=True,
        max_instances=5,
        now=checked_at,
    )

    assert result["dry_run"] is True
    assert result["selected_count"] == 1
    instance = result["instances"][0]
    assert instance["task_code"] == "t_relay.observation.monitor.snapshot_5m"
    assert instance["run_slot"] == "093500"
    assert instance["effective_as_of_time_utc"] == "2026-06-24T02:15:00+00:00"
    materialized = instance["scheduler_payload"]["_scheduler_materialized_instance"]
    assert materialized["catch_up_run_id"].startswith("model-catchup-")
    assert materialized["captured_late"] is True
    assert materialized["original_scheduled_at"] == "2026-06-24T01:35:00+00:00"
    assert runtime.task_store.table_count("task_instance_v1") == 0


def test_model_schedule_catch_up_enqueues_observation_snapshot_task() -> None:
    client = ReadyInspectorClient()
    store = SchedulerSQLiteTaskStore()
    runtime = SchedulerRuntime(
        client=client,
        guard_mode="legacy_data_inspector",
        poll_seconds=1,
        request_timeout_seconds=1,
        source_time_wheel_enabled=False,
        model_time_wheel_enabled=True,
        task_store=store,
        required_model_services="t_board_relay",
    )
    checked_at = datetime(2026, 6, 24, 2, 15, 0, tzinfo=timezone.utc)

    result = runtime.catch_up_model_schedule(
        trading_day=datetime(2026, 6, 24).date(),
        task_codes=["t_relay.observation.monitor.snapshot_5m"],
        run_slots=["093500"],
        dry_run=False,
        dispatch_immediately=False,
        catch_up_run_id="m4-snapshot-test",
        max_instances=5,
        now=checked_at,
    )

    assert result["selected_count"] == 1
    assert result["enqueued_task_ids"]
    assert result["dispatched"] == []
    assert store.status_counts(owner_services=("t-board-relay-service",))["pending"] == 1
    task = store.due_tasks(now=checked_at, owner_services=("t-board-relay-service",))[0]
    payload = store.payload_for(task)
    assert payload["run_id"] == "scheduler-catchup:m4-snapshot-test:t_relay.observation.monitor.snapshot_5m:2026-06-24:093500"
    assert payload["as_of_time_utc"] == "2026-06-24T02:15:00+00:00"
    assert payload["_scheduler_materialized_instance"]["catch_up_reason"] == "model_schedule_reconcile"


def test_model_schedule_catch_up_immediate_dispatch_calls_research_execution_only() -> None:
    client = ResearchExecutionClient()
    runtime = SchedulerRuntime(
        client=client,
        guard_mode="legacy_data_inspector",
        poll_seconds=1,
        request_timeout_seconds=1,
        source_time_wheel_enabled=False,
        model_time_wheel_enabled=True,
        task_store=SchedulerSQLiteTaskStore(),
        required_model_services="t_board_relay",
    )
    checked_at = datetime(2026, 6, 24, 2, 15, 0, tzinfo=timezone.utc)

    result = runtime.catch_up_model_schedule(
        trading_day=datetime(2026, 6, 24).date(),
        task_codes=["t_relay.observation.monitor.snapshot_5m"],
        run_slots=["093500"],
        dry_run=False,
        dispatch_immediately=True,
        catch_up_run_id="m4-snapshot-dispatch",
        max_instances=5,
        now=checked_at,
    )

    assert result["selected_count"] == 1
    assert result["research_execution"][0]["accepted"] is True
    research_posts = [post for post in client.posts if post[0] == "http://research-service:8029/research/model-execution/run"]
    assert len(research_posts) == 1
    body = research_posts[0][1]
    assert body["task_code"] == "t_relay.observation.monitor.snapshot_5m"
    assert body["symbol"] == "000759.SZ"
    assert body["as_of_time_utc"] == "2026-06-24T02:15:00+00:00"
    assert body["extra_context"]["scheduler_materialized_instance"]["captured_late"] is True
    assert not any("/t-board-relay/" in post[0] for post in client.posts)


def test_model_time_wheel_marks_research_execution_gap_as_terminal_blocked() -> None:
    client = ResearchExecutionClient(blocked=True)
    runtime = SchedulerRuntime(
        client=client,
        guard_mode="legacy_data_inspector",
        poll_seconds=1,
        request_timeout_seconds=1,
        source_time_wheel_enabled=False,
        model_time_wheel_enabled=True,
        model_time_wheel_live_dispatch=True,
        model_time_wheel_lateness_seconds=60,
        task_store=SchedulerSQLiteTaskStore(),
    )

    result = runtime.run_model_time_wheel_once(now=datetime(2026, 6, 12, 1, 26, 0, tzinfo=timezone.utc))

    assert result["status"] == "ready"
    assert result["error"] is None
    assert result["details"]["research_execution"][0]["execution_status"] == "blocked_data_gap"
    assert result["details"]["research_execution"][0]["accepted"] is False
    assert result["details"]["research_execution"][0]["completed"] is True
    assert result["details"]["research_execution"][0]["terminal_non_success"] is True
    assert result["details"]["status_counts"]["blocked_data_gap"] >= 1
    assert "retry_ready" not in result["details"]["status_counts"]
