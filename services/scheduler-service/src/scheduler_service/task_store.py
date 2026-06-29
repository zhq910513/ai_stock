from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
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
    payload_json TEXT NOT NULL DEFAULT '{}',
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
        self._db_lock = threading.RLock()
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        with self._db_lock:
            self.conn.executescript(TASK_STORE_DDL)
            self._ensure_payload_column()
            self.conn.commit()

    def close(self) -> None:
        with self._db_lock:
            self.conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._db_lock:
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
                    scheduled_at, payload_json, status, idempotency_key, input_hash, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)
                """,
                (
                    task_instance_id,
                    task_code,
                    owner_service,
                    biz_key,
                    scheduled_at.isoformat(),
                    _json(payload),
                    idempotency_key,
                    input_hash,
                    now,
                    now,
                ),
            )
        return task_instance_id

    def due_tasks(
        self,
        *,
        now: datetime,
        limit: int = 100,
        owner_service: str | None = None,
        owner_services: tuple[str, ...] | None = None,
    ) -> list[dict[str, Any]]:
        filters: list[str] = []
        params: list[Any] = [now.isoformat(), now.isoformat()]
        if owner_service is not None:
            filters.append("owner_service = ?")
            params.append(owner_service)
        if owner_services is not None:
            owners = tuple(owner_services)
            if not owners:
                return []
            filters.append(f"owner_service IN ({','.join('?' for _ in owners)})")
            params.extend(owners)
        owner_clause = f" AND {' AND '.join(filters)}" if filters else ""
        params.append(int(limit))
        with self._db_lock:
            rows = self.conn.execute(
                f"""
                SELECT * FROM task_instance_v1
                WHERE (
                    status = 'pending'
                    OR (status = 'retry_ready' AND (next_retry_at IS NULL OR next_retry_at <= ?))
                )
                  AND scheduled_at <= ?
                  {owner_clause}
                ORDER BY scheduled_at ASC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        return [dict(row) for row in rows]

    def due_tasks_by_ids(
        self,
        *,
        task_instance_ids: list[str],
        now: datetime,
        owner_service: str | None = None,
    ) -> list[dict[str, Any]]:
        ids = [str(item).strip() for item in task_instance_ids if str(item).strip()]
        if not ids:
            return []
        params: list[Any] = [now.isoformat(), now.isoformat(), *ids]
        owner_clause = ""
        if owner_service is not None:
            owner_clause = " AND owner_service = ?"
            params.append(owner_service)
        placeholders = ",".join("?" for _ in ids)
        with self._db_lock:
            rows = self.conn.execute(
                f"""
                SELECT * FROM task_instance_v1
                WHERE (
                    status = 'pending'
                    OR (status = 'retry_ready' AND (next_retry_at IS NULL OR next_retry_at <= ?))
                )
                  AND scheduled_at <= ?
                  AND task_instance_id IN ({placeholders})
                  {owner_clause}
                ORDER BY scheduled_at ASC
                """,
                tuple(params),
            ).fetchall()
        return [dict(row) for row in rows]

    def expired_running_tasks(
        self,
        *,
        now: datetime,
        owner_services: tuple[str, ...] | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        params: list[Any] = [now.isoformat()]
        owner_clause = ""
        if owner_services is not None:
            owners = tuple(owner_services)
            if not owners:
                return []
            owner_clause = f" AND t.owner_service IN ({','.join('?' for _ in owners)})"
            params.extend(owners)
        params.append(int(limit))
        with self._db_lock:
            rows = self.conn.execute(
                f"""
                SELECT t.*, l.lease_owner, l.lease_until
                FROM task_instance_v1 t
                LEFT JOIN task_lease_v1 l ON l.task_instance_id = t.task_instance_id
                WHERE t.status = 'running'
                  AND (l.lease_until IS NULL OR l.lease_until <= ?)
                  {owner_clause}
                ORDER BY t.scheduled_at ASC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        return [dict(row) for row in rows]

    def expired_running_count(
        self,
        *,
        now: datetime,
        owner_services: tuple[str, ...] | None = None,
    ) -> int:
        params: list[Any] = [now.isoformat()]
        owner_clause = ""
        if owner_services is not None:
            owners = tuple(owner_services)
            if not owners:
                return 0
            owner_clause = f" AND t.owner_service IN ({','.join('?' for _ in owners)})"
            params.extend(owners)
        with self._db_lock:
            row = self.conn.execute(
                f"""
                SELECT COUNT(*) AS count
                FROM task_instance_v1 t
                LEFT JOIN task_lease_v1 l ON l.task_instance_id = t.task_instance_id
                WHERE t.status = 'running'
                  AND (l.lease_until IS NULL OR l.lease_until <= ?)
                  {owner_clause}
                """,
                tuple(params),
            ).fetchone()
        return int(row["count"] if row else 0)

    def recover_expired_running(
        self,
        *,
        now: datetime,
        owner_services: tuple[str, ...] | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        params: list[Any] = [now.isoformat()]
        owner_clause = ""
        if owner_services is not None:
            owners = tuple(owner_services)
            if not owners:
                return []
            owner_clause = f" AND t.owner_service IN ({','.join('?' for _ in owners)})"
            params.extend(owners)
        params.append(int(limit))
        with self.transaction() as conn:
            rows = conn.execute(
                f"""
                SELECT t.*, l.lease_owner, l.lease_until
                FROM task_instance_v1 t
                LEFT JOIN task_lease_v1 l ON l.task_instance_id = t.task_instance_id
                WHERE t.status = 'running'
                  AND (l.lease_until IS NULL OR l.lease_until <= ?)
                  {owner_clause}
                ORDER BY t.scheduled_at ASC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
            recovered = [dict(row) for row in rows]
            for row in recovered:
                task_instance_id = str(row["task_instance_id"])
                conn.execute(
                    """
                    UPDATE task_instance_v1
                    SET status='retry_ready', next_retry_at=?, updated_at=?
                    WHERE task_instance_id=? AND status='running'
                    """,
                    (now.isoformat(), now.isoformat(), task_instance_id),
                )
                conn.execute("DELETE FROM task_lease_v1 WHERE task_instance_id=?", (task_instance_id,))
                self._log(
                    conn,
                    task_instance_id,
                    "lease_recovered",
                    "retry_ready",
                    "expired running lease recovered for retry",
                    {
                        "previous_lease_owner": row.get("lease_owner"),
                        "previous_lease_until": row.get("lease_until"),
                    },
                )
        return recovered

    @staticmethod
    def payload_for(task_row: dict[str, Any]) -> dict[str, Any]:
        raw = task_row.get("payload_json") or "{}"
        try:
            payload = json.loads(str(raw))
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

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

    def mark_terminal(
        self,
        task_instance_id: str,
        *,
        status: str,
        output: dict[str, Any],
        message: str,
        error_code: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.transaction() as conn:
            conn.execute(
                """
                UPDATE task_instance_v1
                SET status=?, finished_at=?, output_hash=?, error_code=?, updated_at=?
                WHERE task_instance_id=?
                """,
                (status, now, _stable_hash(output, "task-output"), error_code, now, task_instance_id),
            )
            conn.execute("DELETE FROM task_lease_v1 WHERE task_instance_id=?", (task_instance_id,))
            self._log(conn, task_instance_id, "finished", status, message, output)

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

    def archive_obsolete_source_dead_letters(
        self,
        *,
        task_code: str,
        source_table_name: str,
        legacy_canonical_fields: list[str],
        replacement_canonical_fields: list[str],
        reason: str,
        dry_run: bool = True,
        limit: int = 500,
    ) -> dict[str, Any]:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        legacy_fields = [str(item) for item in legacy_canonical_fields if str(item)]
        legacy_field_set = set(legacy_fields)
        if not legacy_field_set:
            raise ValueError("legacy_canonical_fields must not be empty")
        replacement_fields = [str(item) for item in replacement_canonical_fields if str(item)]
        now = datetime.now(timezone.utc).isoformat()
        with self.transaction() as conn:
            rows = conn.execute(
                """
                SELECT
                    task_instance_v1.*,
                    task_dead_letter_v1.dead_letter_id,
                    task_dead_letter_v1.error_message AS dead_letter_error_message
                FROM task_instance_v1
                LEFT JOIN task_dead_letter_v1
                  ON task_dead_letter_v1.task_instance_id = task_instance_v1.task_instance_id
                WHERE task_instance_v1.status = 'dead_letter'
                  AND task_instance_v1.owner_service = 'source-data-service'
                  AND task_instance_v1.task_code = ?
                ORDER BY task_instance_v1.scheduled_at ASC
                LIMIT ?
                """,
                (task_code, int(limit)),
            ).fetchall()
            matched: list[dict[str, Any]] = []
            for row in rows:
                item = dict(row)
                payload = self.payload_for(item)
                fields = [str(value) for value in payload.get("canonical_fields") or []]
                if payload.get("source_table_name") != source_table_name:
                    continue
                if set(fields) != legacy_field_set:
                    continue
                matched.append(
                    {
                        "task_instance_id": item["task_instance_id"],
                        "dead_letter_id": item.get("dead_letter_id"),
                        "task_code": item["task_code"],
                        "biz_key": item["biz_key"],
                        "scheduled_at": item["scheduled_at"],
                        "legacy_canonical_fields": fields,
                        "replacement_canonical_fields": replacement_fields,
                        "error_code": item.get("error_code"),
                        "error_message": item.get("dead_letter_error_message"),
                    }
                )
            if dry_run:
                return {
                    "contract_kind": "scheduler_obsolete_source_dead_letter_archive_v1",
                    "dry_run": True,
                    "matched_count": len(matched),
                    "archived_count": 0,
                    "status": "preview",
                    "reason": reason,
                    "task_code": task_code,
                    "source_table_name": source_table_name,
                    "legacy_canonical_fields": legacy_fields,
                    "replacement_canonical_fields": replacement_fields,
                    "matched": matched,
                    "status_counts": self.status_counts(owner_services=("source-data-service",)),
                }
            for item in matched:
                output = {
                    "archive_status": "obsolete_contract_replaced",
                    "reason": reason,
                    "source_table_name": source_table_name,
                    "legacy_canonical_fields": item["legacy_canonical_fields"],
                    "replacement_canonical_fields": replacement_fields,
                    "dead_letter_id": item.get("dead_letter_id"),
                    "original_error_code": item.get("error_code"),
                    "original_error_message": item.get("error_message"),
                }
                conn.execute(
                    """
                    UPDATE task_instance_v1
                    SET status='obsolete_contract_replaced',
                        finished_at=COALESCE(finished_at, ?),
                        output_hash=?,
                        error_code='source_schedule_obsolete_contract_replaced',
                        updated_at=?
                    WHERE task_instance_id=?
                    """,
                    (
                        now,
                        _stable_hash(output, "task-output"),
                        now,
                        item["task_instance_id"],
                    ),
                )
                conn.execute("DELETE FROM task_lease_v1 WHERE task_instance_id=?", (item["task_instance_id"],))
                self._log(
                    conn,
                    item["task_instance_id"],
                    "dead_letter_archived",
                    "obsolete_contract_replaced",
                    "obsolete source schedule contract replaced; dead-letter audit retained",
                    output,
                )
            status_counts = self.status_counts(owner_services=("source-data-service",))
        return {
            "contract_kind": "scheduler_obsolete_source_dead_letter_archive_v1",
            "dry_run": False,
            "matched_count": len(matched),
            "archived_count": len(matched),
            "status": "archived",
            "reason": reason,
            "task_code": task_code,
            "source_table_name": source_table_name,
            "legacy_canonical_fields": legacy_fields,
            "replacement_canonical_fields": replacement_fields,
            "matched": matched,
            "status_counts": status_counts,
        }

    def reclassify_source_duplicate_successes(
        self,
        *,
        task_code: str | None = None,
        source_table_name: str | None = None,
        reason: str,
        dry_run: bool = True,
        limit: int = 500,
    ) -> dict[str, Any]:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        params: list[Any] = []
        task_clause = ""
        if task_code:
            task_clause = " AND task_code = ?"
            params.append(task_code)
        params.append(int(limit))
        now = datetime.now(timezone.utc).isoformat()
        with self.transaction() as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM task_instance_v1
                WHERE status = 'success'
                  AND owner_service = 'source-data-service'
                  {task_clause}
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
            matched: list[dict[str, Any]] = []
            for row in rows:
                item = dict(row)
                payload = self.payload_for(item)
                if source_table_name and payload.get("source_table_name") != source_table_name:
                    continue
                log = conn.execute(
                    """
                    SELECT payload_json
                    FROM task_run_log_v1
                    WHERE task_instance_id = ?
                      AND event_type = 'finished'
                      AND status = 'success'
                    ORDER BY event_time DESC
                    LIMIT 1
                    """,
                    (item["task_instance_id"],),
                ).fetchone()
                if not log:
                    continue
                try:
                    output = json.loads(str(log["payload_json"] or "{}"))
                except json.JSONDecodeError:
                    continue
                try:
                    submitted = int(output.get("submitted_job_count") or 0)
                    skipped = int(output.get("skipped_duplicate_count") or 0)
                except (TypeError, ValueError):
                    continue
                if submitted != 0 or skipped <= 0:
                    continue
                matched.append(
                    {
                        "task_instance_id": item["task_instance_id"],
                        "task_code": item["task_code"],
                        "biz_key": item["biz_key"],
                        "scheduled_at": item["scheduled_at"],
                        "source_table_name": payload.get("source_table_name"),
                        "fetch_batch_id": output.get("fetch_batch_id"),
                        "submitted_job_count": submitted,
                        "skipped_duplicate_count": skipped,
                    }
                )
            if dry_run:
                return {
                    "contract_kind": "scheduler_source_duplicate_success_reclassify_v1",
                    "dry_run": True,
                    "matched_count": len(matched),
                    "reclassified_count": 0,
                    "status": "preview",
                    "reason": reason,
                    "task_code": task_code,
                    "source_table_name": source_table_name,
                    "matched": matched,
                    "status_counts": self.status_counts(owner_services=("source-data-service",)),
                }
            for item in matched:
                output = {
                    "reclassify_status": "source_duplicate_skipped",
                    "reason": reason,
                    "source_table_name": item.get("source_table_name"),
                    "fetch_batch_id": item.get("fetch_batch_id"),
                    "submitted_job_count": item.get("submitted_job_count"),
                    "skipped_duplicate_count": item.get("skipped_duplicate_count"),
                }
                conn.execute(
                    """
                    UPDATE task_instance_v1
                    SET status='source_duplicate_skipped',
                        error_code='source_submit_duplicate_no_new_job',
                        output_hash=?,
                        updated_at=?
                    WHERE task_instance_id=?
                    """,
                    (
                        _stable_hash(output, "task-output"),
                        now,
                        item["task_instance_id"],
                    ),
                )
                self._log(
                    conn,
                    item["task_instance_id"],
                    "source_duplicate_reclassified",
                    "source_duplicate_skipped",
                    "source submit duplicate produced no new raw job; source fact must be verified in source/source_lineage",
                    output,
                )
            status_counts = self.status_counts(owner_services=("source-data-service",))
        return {
            "contract_kind": "scheduler_source_duplicate_success_reclassify_v1",
            "dry_run": False,
            "matched_count": len(matched),
            "reclassified_count": len(matched),
            "status": "reclassified",
            "reason": reason,
            "task_code": task_code,
            "source_table_name": source_table_name,
            "matched": matched,
            "status_counts": status_counts,
        }

    def table_count(self, table: str) -> int:
        with self._db_lock:
            return int(self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    def status_counts(self, *, owner_services: tuple[str, ...] | None = None) -> dict[str, int]:
        params: list[Any] = []
        owner_clause = ""
        if owner_services is not None:
            owners = tuple(owner_services)
            if not owners:
                return {}
            owner_clause = f" WHERE owner_service IN ({','.join('?' for _ in owners)})"
            params.extend(owners)
        with self._db_lock:
            rows = self.conn.execute(
                f"SELECT status, COUNT(*) AS count FROM task_instance_v1{owner_clause} GROUP BY status",
                tuple(params),
            ).fetchall()
        return {str(row["status"]): int(row["count"]) for row in rows}

    def _ensure_payload_column(self) -> None:
        columns = {
            str(row["name"])
            for row in self.conn.execute("PRAGMA table_info(task_instance_v1)").fetchall()
        }
        if "payload_json" not in columns:
            self.conn.execute("ALTER TABLE task_instance_v1 ADD COLUMN payload_json TEXT NOT NULL DEFAULT '{}'")

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
