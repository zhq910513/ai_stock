from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

TASK_STORE_VERSION = "scheduler_task_store_v1"

TASK_STORE_DDL = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS task_instance_v1 (
    task_instance_id TEXT PRIMARY KEY,
    task_code TEXT NOT NULL,
    owner_service TEXT NOT NULL,
    biz_key TEXT NOT NULL,
    scheduled_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    retry_count INTEGER NOT NULL DEFAULT 0,
    next_retry_at TEXT,
    idempotency_key TEXT NOT NULL UNIQUE,
    input_hash TEXT NOT NULL,
    output_hash TEXT,
    error_code TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_task_due ON task_instance_v1(status, scheduled_at);
CREATE TABLE IF NOT EXISTS task_lease_v1 (
    task_instance_id TEXT PRIMARY KEY,
    lease_owner TEXT NOT NULL,
    lease_until TEXT NOT NULL,
    acquired_at TEXT NOT NULL,
    FOREIGN KEY(task_instance_id) REFERENCES task_instance_v1(task_instance_id)
);
CREATE TABLE IF NOT EXISTS task_dead_letter_v1 (
    dead_letter_id TEXT PRIMARY KEY,
    task_instance_id TEXT NOT NULL,
    task_code TEXT NOT NULL,
    owner_service TEXT NOT NULL,
    error_code TEXT NOT NULL,
    error_message TEXT,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS task_run_log_v1 (
    task_run_log_id TEXT PRIMARY KEY,
    task_instance_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    status TEXT NOT NULL,
    message TEXT,
    event_time TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}'
);
"""


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    return value


def _json(value: Any) -> str:
    return json.dumps(_jsonable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _stable_hash(payload: dict[str, Any], prefix: str) -> str:
    encoded = _json(payload)
    return f"{prefix}-{hashlib.sha256(encoded.encode('utf-8')).hexdigest()[:24]}"


def _parse(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = value
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class TaskLeaseResult:
    contract_kind: str
    task_store_version: str
    task_instance_id: str
    acquired: bool
    lease_owner: str | None
    lease_until: datetime | None
    message: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.lease_until:
            payload["lease_until"] = self.lease_until.isoformat()
        return payload


class SchedulerSQLiteTaskStore:
    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self.db_path = str(db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(TASK_STORE_DDL)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def enqueue(
        self,
        *,
        task_code: str,
        owner_service: str,
        biz_key: str,
        scheduled_at: datetime,
        payload: dict[str, Any],
    ) -> str:
        idempotency_key = _stable_hash(
            {"task_code": task_code, "owner_service": owner_service, "biz_key": biz_key, "scheduled_at": scheduled_at},
            "task-idem",
        )
        task_instance_id = _stable_hash({"idempotency_key": idempotency_key}, "task")
        now = datetime.now(timezone.utc).isoformat()
        input_hash = _stable_hash(payload, "task-input")
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO task_instance_v1 (task_instance_id, task_code, owner_service, biz_key,
                    scheduled_at, status, idempotency_key, input_hash, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)
                """,
                (task_instance_id, task_code, owner_service, biz_key, scheduled_at.isoformat(), idempotency_key, input_hash, now, now),
            )
        return task_instance_id

    def due_tasks(self, *, now: datetime, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT * FROM task_instance_v1
            WHERE status IN ('pending', 'retry_ready')
              AND scheduled_at <= ?
            ORDER BY scheduled_at ASC
            LIMIT ?
            """,
            (now.isoformat(), int(limit)),
        ).fetchall()
        return [dict(row) for row in rows]

    def acquire_lease(self, task_instance_id: str, *, lease_owner: str, now: datetime, lease_seconds: int = 60) -> TaskLeaseResult:
        lease_until = now + timedelta(seconds=lease_seconds)
        with self.transaction() as conn:
            task = conn.execute("SELECT * FROM task_instance_v1 WHERE task_instance_id = ?", (task_instance_id,)).fetchone()
            if not task:
                return TaskLeaseResult(TASK_STORE_VERSION, TASK_STORE_VERSION, task_instance_id, False, None, None, "task_not_found")
            existing = conn.execute("SELECT * FROM task_lease_v1 WHERE task_instance_id = ?", (task_instance_id,)).fetchone()
            if existing and _parse(existing["lease_until"]) > now:
                return TaskLeaseResult(TASK_STORE_VERSION, TASK_STORE_VERSION, task_instance_id, False, existing["lease_owner"], _parse(existing["lease_until"]), "lease_held")
            conn.execute(
                """
                INSERT OR REPLACE INTO task_lease_v1 (task_instance_id, lease_owner, lease_until, acquired_at)
                VALUES (?, ?, ?, ?)
                """,
                (task_instance_id, lease_owner, lease_until.isoformat(), now.isoformat()),
            )
            conn.execute(
                "UPDATE task_instance_v1 SET status = 'running', started_at = COALESCE(started_at, ?), updated_at = ? WHERE task_instance_id = ?",
                (now.isoformat(), now.isoformat(), task_instance_id),
            )
            self._log(conn, task_instance_id, "lease_acquired", "running", f"lease_owner={lease_owner}", {})
        return TaskLeaseResult(TASK_STORE_VERSION, TASK_STORE_VERSION, task_instance_id, True, lease_owner, lease_until, "lease_acquired")

    def mark_success(self, task_instance_id: str, *, output: dict[str, Any]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.transaction() as conn:
            conn.execute(
                "UPDATE task_instance_v1 SET status='success', finished_at=?, output_hash=?, updated_at=? WHERE task_instance_id=?",
                (now, _stable_hash(output, "task-output"), now, task_instance_id),
            )
            conn.execute("DELETE FROM task_lease_v1 WHERE task_instance_id=?", (task_instance_id,))
            self._log(conn, task_instance_id, "finished", "success", "task completed", output)

    def mark_failure(self, task_instance_id: str, *, error_code: str, error_message: str, max_retries: int = 3) -> None:
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat()
        with self.transaction() as conn:
            task = conn.execute("SELECT * FROM task_instance_v1 WHERE task_instance_id=?", (task_instance_id,)).fetchone()
            if not task:
                return
            retry_count = int(task["retry_count"] or 0) + 1
            if retry_count > max_retries:
                status = "dead_letter"
                next_retry = None
                dead_id = _stable_hash({"task_instance_id": task_instance_id, "error": error_code, "time": now}, "dead")
                conn.execute(
                    """
                    INSERT OR REPLACE INTO task_dead_letter_v1 (dead_letter_id, task_instance_id, task_code, owner_service,
                        error_code, error_message, payload_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (dead_id, task_instance_id, task["task_code"], task["owner_service"], error_code, error_message, _json(dict(task)), now),
                )
            else:
                status = "retry_ready"
                next_retry = (now_dt + timedelta(seconds=30 * retry_count)).isoformat()
            conn.execute(
                """
                UPDATE task_instance_v1 SET status=?, retry_count=?, next_retry_at=?, error_code=?, updated_at=?
                WHERE task_instance_id=?
                """,
                (status, retry_count, next_retry, error_code, now, task_instance_id),
            )
            conn.execute("DELETE FROM task_lease_v1 WHERE task_instance_id=?", (task_instance_id,))
            self._log(conn, task_instance_id, "failed", status, error_message, {"error_code": error_code})

    def table_count(self, table: str) -> int:
        return int(self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    def _log(self, conn: sqlite3.Connection, task_instance_id: str, event_type: str, status: str, message: str, payload: dict[str, Any]) -> None:
        event_time = datetime.now(timezone.utc)
        log_id = f"task-log-{uuid4().hex}"
        conn.execute(
            """
            INSERT INTO task_run_log_v1 (task_run_log_id, task_instance_id, event_type, status, message, event_time, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (log_id, task_instance_id, event_type, status, message, event_time.isoformat(), _json(payload)),
        )
