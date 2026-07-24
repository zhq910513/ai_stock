from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scheduler_service.task_store import SchedulerSQLiteTaskStore


def test_task_store_idempotent_enqueue_lease_success_and_dead_letter() -> None:
    store = SchedulerSQLiteTaskStore()
    now = datetime(2026, 6, 8, 1, 25, tzinfo=timezone.utc)
    task_id = store.enqueue(
        task_code="hot.observe.intraday",
        owner_service="hot-candidates-service",
        biz_key="hot-case-1",
        scheduled_at=now,
        payload={"hot_case_id": "hot-case-1"},
    )
    duplicate = store.enqueue(
        task_code="hot.observe.intraday",
        owner_service="hot-candidates-service",
        biz_key="hot-case-1",
        scheduled_at=now,
        payload={"hot_case_id": "hot-case-1"},
    )
    assert duplicate == task_id
    assert store.table_count("task_instance_v1") == 1
    due = store.due_tasks(now=now, limit=10)
    assert len(due) == 1
    assert store.payload_for(due[0]) == {"hot_case_id": "hot-case-1"}
    lease = store.acquire_lease(task_id, lease_owner="worker-a", now=now)
    assert lease.acquired is True
    lease2 = store.acquire_lease(task_id, lease_owner="worker-b", now=now)
    assert lease2.acquired is False
    store.mark_success(task_id, output={"ok": True})
    assert store.table_count("task_run_log_v1") >= 2

    failed_task = store.enqueue(
        task_code="hot.evolution.offline",
        owner_service="hot-candidates-service",
        biz_key="evo-1",
        scheduled_at=now,
        payload={"job": "evo"},
    )
    store.acquire_lease(failed_task, lease_owner="worker-a", now=now)
    for _ in range(4):
        store.mark_failure(failed_task, error_code="owner_unavailable", error_message="boom", max_retries=3)
    assert store.table_count("task_dead_letter_v1") == 1
    counts = store.status_counts(owner_services=("hot-candidates-service",))
    assert counts["success"] == 1
    assert counts["dead_letter"] == 1
    assert store.due_tasks(now=now, owner_service="source-data-service") == []
    assert len(store.due_tasks(now=now, owner_services=("hot-candidates-service",))) == 0


def test_task_store_terminal_non_success_is_not_retried() -> None:
    store = SchedulerSQLiteTaskStore()
    now = datetime(2026, 6, 8, 7, 35, tzinfo=timezone.utc)
    task_id = store.enqueue(
        task_code="ambush.phase3.release_gate.close",
        owner_service="ambush-watchlist-service",
        biz_key="ambush-release-1",
        scheduled_at=now,
        payload={"symbol": "000063.SZ"},
    )

    lease = store.acquire_lease(task_id, lease_owner="scheduler-model-time-wheel", now=now)
    assert lease.acquired is True
    store.mark_terminal(
        task_id,
        status="blocked_data_gap",
        output={"execution_status": "blocked_data_gap", "gap_codes": ["source_gap:upstream_missing"]},
        error_code="model_blocked_data_gap",
        message="research execution terminal non-success",
    )

    counts = store.status_counts(owner_services=("ambush-watchlist-service",))
    assert counts["blocked_data_gap"] == 1
    assert store.table_count("task_dead_letter_v1") == 0
    assert store.due_tasks(now=now, owner_services=("ambush-watchlist-service",)) == []


def test_task_store_recovers_expired_running_lease_to_retry_ready() -> None:
    store = SchedulerSQLiteTaskStore()
    now = datetime(2026, 6, 26, 1, 0, tzinfo=timezone.utc)
    task_id = store.enqueue(
        task_code="source.minute.realtime_quote",
        owner_service="source-data-service",
        biz_key="source-realtime-1",
        scheduled_at=now,
        payload={"source_table_name": "source.realtime_quote_v1"},
    )
    active_task_id = store.enqueue(
        task_code="source.minute.auction_snapshot",
        owner_service="source-data-service",
        biz_key="source-auction-active",
        scheduled_at=now,
        payload={"source_table_name": "source.auction_snapshot_v1"},
    )

    assert store.acquire_lease(task_id, lease_owner="worker-a", now=now, lease_seconds=1).acquired is True
    assert store.acquire_lease(active_task_id, lease_owner="worker-a", now=now, lease_seconds=300).acquired is True
    later = now + timedelta(seconds=120)

    assert store.due_tasks(now=later, owner_services=("source-data-service",)) == []
    recovered = store.recover_expired_running(
        now=later,
        owner_services=("source-data-service",),
    )

    assert [item["task_instance_id"] for item in recovered] == [task_id]
    counts = store.status_counts(owner_services=("source-data-service",))
    assert counts["retry_ready"] == 1
    assert counts["running"] == 1
    due = store.due_tasks(now=later, owner_services=("source-data-service",))
    assert [item["task_instance_id"] for item in due] == [task_id]
    assert store.acquire_lease(task_id, lease_owner="worker-b", now=later).acquired is True


def test_archive_obsolete_source_dead_letters_keeps_audit_and_only_matches_legacy_contract() -> None:
    store = SchedulerSQLiteTaskStore()
    now = datetime(2026, 6, 26, 1, 15, tzinfo=timezone.utc)
    obsolete_task = store.enqueue(
        task_code="source.minute.auction_snapshot",
        owner_service="source-data-service",
        biz_key="source.minute.auction_snapshot:2026-06-26:091500",
        scheduled_at=now,
        payload={
            "source_table_name": "source.auction_snapshot_v1",
            "canonical_fields": ["price", "volume", "amount", "captured_at", "provider_definition"],
        },
    )
    unrelated_task = store.enqueue(
        task_code="source.minute.realtime_quote",
        owner_service="source-data-service",
        biz_key="source.minute.realtime_quote:2026-06-26:093000",
        scheduled_at=now,
        payload={
            "source_table_name": "source.realtime_quote_v1",
            "canonical_fields": ["latest_price"],
        },
    )
    for task_id in (obsolete_task, unrelated_task):
        store.acquire_lease(task_id, lease_owner="scheduler-source-time-wheel", now=now)
        for _ in range(4):
            store.mark_failure(
                task_id,
                error_code="source_fetch_submit_failed",
                error_message="status_code=404",
                max_retries=3,
            )

    preview = store.archive_obsolete_source_dead_letters(
        task_code="source.minute.auction_snapshot",
        source_table_name="source.auction_snapshot_v1",
        legacy_canonical_fields=["price", "volume", "amount", "captured_at", "provider_definition"],
        replacement_canonical_fields=["virtual_open_price", "matched_volume", "matched_amount", "event_time"],
        reason="test obsolete auction source contract",
        dry_run=True,
    )

    assert preview["matched_count"] == 1
    assert preview["archived_count"] == 0
    assert store.status_counts(owner_services=("source-data-service",))["dead_letter"] == 2

    result = store.archive_obsolete_source_dead_letters(
        task_code="source.minute.auction_snapshot",
        source_table_name="source.auction_snapshot_v1",
        legacy_canonical_fields=["price", "volume", "amount", "captured_at", "provider_definition"],
        replacement_canonical_fields=["virtual_open_price", "matched_volume", "matched_amount", "event_time"],
        reason="test obsolete auction source contract",
        dry_run=False,
    )

    assert result["archived_count"] == 1
    counts = store.status_counts(owner_services=("source-data-service",))
    assert counts["obsolete_contract_replaced"] == 1
    assert counts["dead_letter"] == 1
    assert store.table_count("task_dead_letter_v1") == 2
    assert store.due_tasks(now=now, owner_services=("source-data-service",)) == []
    rows = store.conn.execute(
        "SELECT event_type, status FROM task_run_log_v1 WHERE task_instance_id=? ORDER BY rowid DESC LIMIT 1",
        (obsolete_task,),
    ).fetchall()
    assert rows[0]["event_type"] == "dead_letter_archived"
    assert rows[0]["status"] == "obsolete_contract_replaced"


def test_reclassify_source_duplicate_successes_keeps_success_for_real_submit() -> None:
    store = SchedulerSQLiteTaskStore()
    now = datetime(2026, 6, 26, 1, 15, tzinfo=timezone.utc)
    duplicate_task = store.enqueue(
        task_code="source.minute.auction_snapshot",
        owner_service="source-data-service",
        biz_key="source.minute.auction_snapshot:2026-06-26:091530:catchup:repair",
        scheduled_at=now,
        payload={
            "source_table_name": "source.auction_snapshot_v1",
            "canonical_fields": ["virtual_open_price", "matched_volume", "matched_amount", "event_time"],
        },
    )
    real_submit_task = store.enqueue(
        task_code="source.minute.auction_snapshot",
        owner_service="source-data-service",
        biz_key="source.minute.auction_snapshot:2026-06-26:091500:catchup:repair",
        scheduled_at=now,
        payload={
            "source_table_name": "source.auction_snapshot_v1",
            "canonical_fields": ["virtual_open_price", "matched_volume", "matched_amount", "event_time"],
        },
    )

    store.mark_success(
        duplicate_task,
        output={"fetch_batch_id": "fetch_batch_duplicate", "submitted_job_count": 0, "skipped_duplicate_count": 2},
    )
    store.mark_success(
        real_submit_task,
        output={"fetch_batch_id": "fetch_batch_real", "submitted_job_count": 2, "skipped_duplicate_count": 0},
    )

    preview = store.reclassify_source_duplicate_successes(
        task_code="source.minute.auction_snapshot",
        source_table_name="source.auction_snapshot_v1",
        reason="test duplicate submit no-op",
        dry_run=True,
    )

    assert preview["matched_count"] == 1
    assert preview["reclassified_count"] == 0
    assert store.status_counts(owner_services=("source-data-service",))["success"] == 2

    result = store.reclassify_source_duplicate_successes(
        task_code="source.minute.auction_snapshot",
        source_table_name="source.auction_snapshot_v1",
        reason="test duplicate submit no-op",
        dry_run=False,
    )

    assert result["reclassified_count"] == 1
    counts = store.status_counts(owner_services=("source-data-service",))
    assert counts["source_duplicate_skipped"] == 1
    assert counts["success"] == 1
    logs = store.conn.execute(
        "SELECT event_type, status FROM task_run_log_v1 WHERE task_instance_id=? ORDER BY rowid DESC LIMIT 1",
        (duplicate_task,),
    ).fetchall()
    assert logs[0]["event_type"] == "source_duplicate_reclassified"
    assert logs[0]["status"] == "source_duplicate_skipped"


def test_daily_source_execution_summary_counts_completed_not_due_and_failed() -> None:
    store = SchedulerSQLiteTaskStore()
    day = datetime(2026, 7, 10, tzinfo=timezone.utc).date()
    due_time = datetime(2026, 7, 10, 1, 30, tzinfo=timezone.utc)
    future_time = datetime(2026, 7, 10, 8, 30, tzinfo=timezone.utc)
    completed_id = store.enqueue(
        task_code="source.minute.realtime_quote",
        owner_service="source-data-service",
        biz_key="source.minute.realtime_quote:2026-07-10:093000",
        scheduled_at=due_time,
        payload={"source_table_name": "source.realtime_quote_v1"},
    )
    failed_id = store.enqueue(
        task_code="source.daily.trade_status",
        owner_service="source-data-service",
        biz_key="source.daily.trade_status:2026-07-10:091000",
        scheduled_at=due_time,
        payload={"source_table_name": "source.trade_status_v1"},
    )
    store.mark_success(completed_id, output={"fetch_batch_id": "batch-ok", "status": "queued", "queue_name": "urgent_release_gate_queue", "submitted_job_count": 2, "skipped_duplicate_count": 0, "producer_ack": "accepted"})
    store.acquire_lease(failed_id, lease_owner="scheduler-source-time-wheel", now=due_time)
    store.mark_failure(failed_id, error_code="source_fetch_submit_failed", error_message="boom", max_retries=3)
    instances = [
        {
            "schedule_code": "source.minute.realtime_quote",
            "source_table_name": "source.realtime_quote_v1",
            "scheduled_at": due_time.isoformat(),
            "scheduled_at_local": "2026-07-10T09:30:00+08:00",
            "run_slot": "093000",
            "trading_day": "2026-07-10",
            "biz_key": "source.minute.realtime_quote:2026-07-10:093000",
            "request_body": {},
        },
        {
            "schedule_code": "source.daily.trade_status",
            "source_table_name": "source.trade_status_v1",
            "scheduled_at": due_time.isoformat(),
            "scheduled_at_local": "2026-07-10T09:10:00+08:00",
            "run_slot": "091000",
            "trading_day": "2026-07-10",
            "biz_key": "source.daily.trade_status:2026-07-10:091000",
            "request_body": {},
        },
        {
            "schedule_code": "source.daily.close_bars",
            "source_table_name": "source.daily_bar_v1",
            "scheduled_at": future_time.isoformat(),
            "scheduled_at_local": "2026-07-10T16:30:00+08:00",
            "run_slot": "163000",
            "trading_day": "2026-07-10",
            "biz_key": "source.daily.close_bars:2026-07-10:163000",
            "request_body": {},
        },
    ]

    summary = store.daily_source_execution_summary(
        trading_day=day,
        materialized_instances=instances,
        now=datetime(2026, 7, 10, 2, 0, tzinfo=timezone.utc),
    )

    assert summary["read_only"] is True
    assert summary["summary"]["planned_task_count"] == 3
    assert summary["summary"]["completed_task_count"] == 1
    assert summary["summary"]["failed_task_count"] == 1
    assert summary["summary"]["not_due_task_count"] == 1
    statuses = {row["source_table_name"]: row["execution_status"] for row in summary["tasks"]}
    assert statuses["source.realtime_quote_v1"] == "completed"
    assert statuses["source.trade_status_v1"] == "failed"
    assert statuses["source.daily_bar_v1"] == "not_due"


def test_daily_source_execution_summary_marks_expired_not_enqueued_closed() -> None:
    store = SchedulerSQLiteTaskStore()
    day = datetime(2026, 7, 10, tzinfo=timezone.utc).date()
    due_time = datetime(2026, 7, 10, 1, 30, tzinfo=timezone.utc)
    instances = [
        {
            "schedule_code": "source.minute.minute_bar",
            "schedule_group": "minute_intraday",
            "source_table_name": "source.minute_bar_v1",
            "scheduled_at": due_time.isoformat(),
            "scheduled_at_local": "2026-07-10T09:30:00+08:00",
            "run_slot": "093000",
            "trading_day": "2026-07-10",
            "biz_key": "source.minute.minute_bar:2026-07-10:093000",
            "request_body": {
                "orchestration_context": {
                    "lifecycle_expires_at_local": "2026-07-10T09:40:00+08:00",
                }
            },
        }
    ]

    summary = store.daily_source_execution_summary(
        trading_day=day,
        materialized_instances=instances,
        now=datetime(2026, 7, 10, 2, 0, tzinfo=timezone.utc),
    )

    assert summary["summary"]["planned_task_count"] == 1
    assert summary["summary"]["expired_closed_task_count"] == 1
    assert summary["summary"]["awaiting_dispatch_task_count"] == 0
    assert summary["summary"]["unfinished_task_count"] == 1
    row = summary["tasks"][0]
    assert row["task_status"] == "not_enqueued"
    assert row["execution_status"] == "expired_closed"
    assert row["lifecycle_expired"] is True
