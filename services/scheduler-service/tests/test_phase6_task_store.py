from __future__ import annotations

from datetime import datetime, timezone

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
