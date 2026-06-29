from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from source_data_service.models import (
    CallbackEventType,
    FetchBatchStatus,
    FetchBatchStatusOut,
    FetchCallbackEventOut,
    FetchJobStatus,
    FetchJobStatusOut,
    FetchPriority,
    FetchQueueName,
    FetchTriggerType,
    Provider,
    SourceBuildTriggerOut,
)
from source_data_service.settings import settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def psycopg_available() -> bool:
    try:  # pragma: no cover - depends on runtime image
        import psycopg  # noqa: F401
        return True
    except Exception:
        return False


def configured_database_url() -> str | None:
    # Docker compose passes AI_STOCK_DATABASE_URL while pydantic env_prefix covers
    # SOURCE_DATA_DATABASE_URL. Support both to avoid accidental non-durable runs.
    return settings.database_url or os.environ.get("AI_STOCK_DATABASE_URL")


@dataclass(frozen=True)
class QueuePersistenceSummary:
    backend: str
    durable: bool
    database_url_configured: bool
    driver_available: bool
    ready_for_production_queue: bool
    note: str


def queue_persistence_summary() -> QueuePersistenceSummary:
    backend = (settings.queue_backend or "memory").lower()
    db_url = configured_database_url()
    driver = psycopg_available()
    durable = backend == "postgres"
    ready = durable and bool(db_url) and driver
    if ready:
        note = "postgres durable queue configured; fetch jobs survive source-data-service restarts"
    elif backend == "postgres":
        note = "postgres queue requested but database URL or psycopg driver is unavailable"
    else:
        note = "memory queue is suitable only for local contract tests; production must use postgres"
    return QueuePersistenceSummary(
        backend="postgres" if backend == "postgres" else "memory",
        durable=durable,
        database_url_configured=bool(db_url),
        driver_available=driver,
        ready_for_production_queue=ready,
        note=note,
    )


class PostgresQueuePersistence:
    """Best-effort durable mirror for source fetch orchestration state.

    The HTTP service uses the same pydantic contracts as the memory queue. When
    SOURCE_DATA_QUEUE_BACKEND=postgres, writes are mirrored to Postgres tables so
    job/batch/callback state remains auditable and recoverable after restarts.
    The implementation intentionally keeps all SQL explicit and table-specific;
    generic JSON dumps are not enough for production operations and indexing.
    """

    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url or configured_database_url()

    def _connect(self):  # pragma: no cover - requires runtime Postgres
        if not self.database_url:
            raise RuntimeError("database URL is not configured")
        try:
            import psycopg
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("psycopg is required for postgres queue backend") from exc
        return psycopg.connect(self.database_url)

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, default=str)

    @staticmethod
    def _json_value(value: Any, default: Any) -> Any:
        if value is None:
            return default
        if isinstance(value, str):
            return json.loads(value)
        return value

    @staticmethod
    def _derive_batch_status(
        db_status: FetchBatchStatus,
        *,
        total_count: int,
        queued_count: int,
        leased_count: int,
        succeeded_count: int,
        failed_count: int,
        skipped_duplicate_count: int,
        cancelled_count: int,
        dead_letter_count: int,
    ) -> FetchBatchStatus:
        if db_status == FetchBatchStatus.CANCELLED or cancelled_count:
            return FetchBatchStatus.CANCELLED
        if leased_count:
            return FetchBatchStatus.RUNNING
        if queued_count:
            return FetchBatchStatus.QUEUED
        if failed_count or dead_letter_count:
            return FetchBatchStatus.COMPLETED_WITH_ERRORS
        if total_count == 0:
            return FetchBatchStatus.SUCCEEDED
        if succeeded_count + skipped_duplicate_count >= total_count:
            return FetchBatchStatus.SUCCEEDED
        return db_status

    def _batch_out_from_row(self, row: Any) -> FetchBatchStatusOut:
        db_status = FetchBatchStatus(row[6])
        total_count = int(row[9] or 0)
        queued_count = int(row[12] or 0)
        leased_count = int(row[13] or 0)
        succeeded_count = int(row[14] or 0)
        failed_count = int(row[15] or 0)
        skipped_duplicate_count = int(row[16] or 0)
        cancelled_count = int(row[17] or 0)
        dead_letter_count = int(row[18] or 0)
        status = self._derive_batch_status(
            db_status,
            total_count=total_count,
            queued_count=queued_count,
            leased_count=leased_count,
            succeeded_count=succeeded_count,
            failed_count=failed_count,
            skipped_duplicate_count=skipped_duplicate_count,
            cancelled_count=cancelled_count,
            dead_letter_count=dead_letter_count,
        )
        return FetchBatchStatusOut(
            fetch_batch_id=row[0],
            fetch_plan_id=row[1],
            source_table_name=row[2],
            trigger_type=FetchTriggerType(row[3]),
            priority=FetchPriority(row[4]),
            queue_name=FetchQueueName(row[5]),
            status=status,
            callback_url=row[7],
            operator_notes=self._json_value(row[8], []),
            job_count=total_count,
            created_at=row[10],
            updated_at=row[11],
            queued_count=queued_count,
            leased_count=leased_count,
            succeeded_count=succeeded_count,
            failed_count=failed_count + dead_letter_count,
            skipped_duplicate_count=skipped_duplicate_count,
        )

    def _job_out_from_row(self, row: Any) -> FetchJobStatusOut:
        return FetchJobStatusOut(
            job_item_id=row[0],
            fetch_batch_id=row[1],
            provider=Provider(row[2]),
            api_name=row[3],
            raw_table_name=row[4],
            request_params=self._json_value(row[5], {}),
            request_hash=row[6],
            source_table_name=row[7],
            canonical_fields=self._json_value(row[8], []),
            symbol=row[9],
            trade_date=row[10],
            priority=FetchPriority(row[11]),
            queue_name=FetchQueueName(row[12]),
            status=FetchJobStatus(row[13]),
            worker_id=row[14],
            attempt_count=row[15] or 0,
            backup_of_job_item_id=row[16],
            next_retry_at=row[17],
            lease_expires_at=row[18],
            last_error_code=row[19],
            last_error_message=row[20],
            raw_request_hash=row[21],
            raw_response_schema_hash=row[22],
            created_at=row[23],
            updated_at=row[24],
        )

    def upsert_batch(self, batch: FetchBatchStatusOut, *, request_source: str = "source-data-service") -> None:
        with self._connect() as conn:  # pragma: no cover
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO governance.raw_fetch_batch_v1 (
                        fetch_batch_id, fetch_plan_id, request_source, trigger_type,
                        priority, queue_name, source_table_name, status, callback_url,
                        operator_notes, job_count, created_at, updated_at
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s)
                    ON CONFLICT (fetch_batch_id) DO UPDATE SET
                        status = EXCLUDED.status,
                        job_count = EXCLUDED.job_count,
                        updated_at = EXCLUDED.updated_at,
                        finished_at = CASE WHEN EXCLUDED.status IN ('succeeded','completed_with_errors','cancelled') THEN EXCLUDED.updated_at ELSE governance.raw_fetch_batch_v1.finished_at END
                    """,
                    (
                        batch.fetch_batch_id,
                        batch.fetch_plan_id,
                        request_source,
                        batch.trigger_type.value,
                        batch.priority.value,
                        batch.queue_name.value,
                        batch.source_table_name,
                        batch.status.value,
                        batch.callback_url,
                        self._json(batch.operator_notes),
                        batch.job_count,
                        batch.created_at,
                        batch.updated_at,
                    ),
                )
            conn.commit()

    def upsert_job(self, job: FetchJobStatusOut) -> None:
        with self._connect() as conn:  # pragma: no cover
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO governance.raw_fetch_job_item_v1 (
                        job_item_id, fetch_batch_id, provider, api_name, raw_table_name,
                        request_params_json, request_hash, source_table_name, canonical_fields,
                        symbol, trade_date, priority, queue_name, status, worker_id,
                        attempt_count, backup_of_job_item_id, next_retry_at, lease_expires_at,
                        last_error_code, last_error_message, raw_request_hash, raw_response_schema_hash,
                        created_at, updated_at
                    ) VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (job_item_id) DO UPDATE SET
                        status = EXCLUDED.status,
                        worker_id = EXCLUDED.worker_id,
                        attempt_count = EXCLUDED.attempt_count,
                        next_retry_at = EXCLUDED.next_retry_at,
                        lease_expires_at = EXCLUDED.lease_expires_at,
                        last_error_code = EXCLUDED.last_error_code,
                        last_error_message = EXCLUDED.last_error_message,
                        raw_request_hash = COALESCE(EXCLUDED.raw_request_hash, governance.raw_fetch_job_item_v1.raw_request_hash),
                        raw_response_schema_hash = COALESCE(EXCLUDED.raw_response_schema_hash, governance.raw_fetch_job_item_v1.raw_response_schema_hash),
                        updated_at = EXCLUDED.updated_at,
                        finished_at = CASE WHEN EXCLUDED.status IN ('succeeded','failed','cancelled','dead_letter','skipped_duplicate') THEN EXCLUDED.updated_at ELSE governance.raw_fetch_job_item_v1.finished_at END
                    WHERE governance.raw_fetch_job_item_v1.updated_at IS NULL
                       OR EXCLUDED.updated_at >= governance.raw_fetch_job_item_v1.updated_at
                    """,
                    (
                        job.job_item_id,
                        job.fetch_batch_id,
                        job.provider.value,
                        job.api_name,
                        job.raw_table_name,
                        self._json(job.request_params),
                        job.request_hash,
                        job.source_table_name,
                        job.canonical_fields,
                        job.symbol,
                        job.trade_date,
                        job.priority.value,
                        job.queue_name.value,
                        job.status.value,
                        job.worker_id,
                        job.attempt_count,
                        job.backup_of_job_item_id,
                        job.next_retry_at,
                        job.lease_expires_at,
                        job.last_error_code,
                        job.last_error_message,
                        job.raw_request_hash,
                        job.raw_response_schema_hash,
                        job.created_at,
                        job.updated_at,
                    ),
                )
            conn.commit()

    def upsert_worker_heartbeat(
        self,
        *,
        worker_id: str,
        worker_role: str = "source-fetch-worker",
        queue_names: list[str] | None = None,
        providers: list[str] | None = None,
        current_job_item_id: str | None = None,
        status: str = "alive",
        note: str | None = None,
    ) -> None:
        with self._connect() as conn:  # pragma: no cover
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO governance.raw_fetch_worker_heartbeat_v1 (
                        worker_id, worker_role, queue_names, providers,
                        current_job_item_id, last_seen_at, status, note
                    ) VALUES (%s,%s,%s,%s,%s,now(),%s,%s)
                    ON CONFLICT (worker_id) DO UPDATE SET
                        worker_role = EXCLUDED.worker_role,
                        queue_names = EXCLUDED.queue_names,
                        providers = EXCLUDED.providers,
                        current_job_item_id = EXCLUDED.current_job_item_id,
                        last_seen_at = EXCLUDED.last_seen_at,
                        status = EXCLUDED.status,
                        note = EXCLUDED.note
                    """,
                    (
                        worker_id,
                        worker_role,
                        queue_names or [],
                        providers or [],
                        current_job_item_id,
                        status,
                        note,
                    ),
                )
            conn.commit()

    def insert_callback(self, event: FetchCallbackEventOut) -> None:
        with self._connect() as conn:  # pragma: no cover
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO governance.raw_fetch_callback_event_v1 (
                        callback_event_id, fetch_batch_id, job_item_id, event_type,
                        callback_url, payload_json, delivery_status, created_at
                    ) VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s,%s)
                    ON CONFLICT (callback_event_id) DO UPDATE SET
                        payload_json = EXCLUDED.payload_json,
                        delivery_status = EXCLUDED.delivery_status,
                        last_attempted_at = CASE
                            WHEN EXCLUDED.delivery_status IN ('delivered','failed','skipped_no_callback')
                            THEN now()
                            ELSE governance.raw_fetch_callback_event_v1.last_attempted_at
                        END,
                        delivered_at = CASE
                            WHEN EXCLUDED.delivery_status = 'delivered'
                            THEN now()
                            ELSE governance.raw_fetch_callback_event_v1.delivered_at
                        END
                    """,
                    (
                        event.callback_event_id,
                        event.fetch_batch_id,
                        event.job_item_id,
                        event.event_type.value,
                        event.callback_url,
                        self._json(event.payload),
                        event.delivery_status,
                        event.created_at,
                    ),
                )
            conn.commit()

    def read_callbacks(self, fetch_batch_id: str | None = None, *, pending_only: bool = False, limit: int = 1000) -> list[FetchCallbackEventOut]:
        with self._connect() as conn:  # pragma: no cover
            where: list[str] = []
            params: list[Any] = []
            if fetch_batch_id:
                where.append("fetch_batch_id = %s")
                params.append(fetch_batch_id)
            if pending_only:
                where.append("delivery_status = 'pending'")
            sql = """
                SELECT callback_event_id, fetch_batch_id, job_item_id, event_type,
                       callback_url, payload_json, delivery_status, created_at
                FROM governance.raw_fetch_callback_event_v1
            """
            if where:
                sql += " WHERE " + " AND ".join(where)
            sql += " ORDER BY created_at ASC, callback_event_id ASC LIMIT %s"
            params.append(limit)
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        return [
            FetchCallbackEventOut(
                callback_event_id=row[0],
                fetch_batch_id=row[1],
                job_item_id=row[2],
                event_type=CallbackEventType(row[3]),
                callback_url=row[4],
                payload=self._json_value(row[5], {}),
                delivery_status=row[6],
                created_at=row[7],
            )
            for row in rows
        ]

    def insert_build_trigger(self, trigger: SourceBuildTriggerOut) -> None:
        with self._connect() as conn:  # pragma: no cover
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO governance.source_build_trigger_v1 (
                        trigger_id, fetch_batch_id, job_item_id, source_table_name, symbol,
                        trade_date, build_scope, status, quality_check_required,
                        lineage_required, created_at, finished_at
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (trigger_id) DO NOTHING
                    """,
                    (
                        trigger.trigger_id,
                        trigger.fetch_batch_id,
                        trigger.job_item_id,
                        trigger.source_table_name,
                        trigger.symbol,
                        trigger.trade_date,
                        trigger.build_scope,
                        trigger.status,
                        trigger.quality_check_required,
                        trigger.lineage_required,
                        trigger.created_at,
                        trigger.finished_at,
                    ),
                )
            conn.commit()

    def update_build_trigger_status(self, trigger_id: str, status: str, finished_at: datetime | None = None) -> None:
        with self._connect() as conn:  # pragma: no cover
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE governance.source_build_trigger_v1
                    SET status = %s,
                        finished_at = %s
                    WHERE trigger_id = %s
                    """,
                    (status, finished_at, trigger_id),
                )
            conn.commit()

    def find_job_item_id_by_request(
        self,
        provider: Provider,
        api_name: str,
        raw_table_name: str,
        request_hash: str,
    ) -> str | None:
        with self._connect() as conn:  # pragma: no cover
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT job_item_id
                    FROM governance.raw_fetch_job_item_v1
                    WHERE provider = %s
                      AND api_name = %s
                      AND raw_table_name = %s
                      AND request_hash = %s
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (provider.value, api_name, raw_table_name, request_hash),
                )
                row = cur.fetchone()
                return str(row[0]) if row else None

    def queue_counts(self) -> dict[str, int]:
        with self._connect() as conn:  # pragma: no cover
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        COUNT(DISTINCT b.fetch_batch_id) FILTER (
                            WHERE b.status IN ('queued','running')
                              AND j.status IN ('queued','leased')
                        ) AS active_batch_count,
                        COUNT(j.job_item_id) FILTER (WHERE j.status = 'queued') AS queued_job_count,
                        COUNT(j.job_item_id) FILTER (WHERE j.status = 'leased') AS leased_job_count,
                        COUNT(j.job_item_id) FILTER (WHERE j.status = 'dead_letter') AS dead_letter_count
                    FROM governance.raw_fetch_batch_v1 b
                    LEFT JOIN governance.raw_fetch_job_item_v1 j
                        ON j.fetch_batch_id = b.fetch_batch_id
                    """
                )
                row = cur.fetchone()
        return {
            "active_batch_count": int(row[0] or 0),
            "queued_job_count": int(row[1] or 0),
            "leased_job_count": int(row[2] or 0),
            "dead_letter_count": int(row[3] or 0),
        }

    def queue_summary(self) -> dict[FetchQueueName, dict[str, int]]:
        with self._connect() as conn:  # pragma: no cover
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        queue_name,
                        COUNT(*) FILTER (WHERE status = 'queued') AS queued_count,
                        COUNT(*) FILTER (WHERE status = 'leased') AS leased_count,
                        COUNT(*) FILTER (WHERE status = 'succeeded') AS succeeded_count,
                        COUNT(*) FILTER (WHERE status = 'failed') AS failed_count,
                        COUNT(*) FILTER (WHERE status = 'dead_letter') AS dead_letter_count
                    FROM governance.raw_fetch_job_item_v1
                    GROUP BY queue_name
                    """
                )
                rows = cur.fetchall()
        summary: dict[FetchQueueName, dict[str, int]] = {}
        for row in rows:
            queue_name = FetchQueueName(row[0])
            summary[queue_name] = {
                "queued_count": int(row[1] or 0),
                "leased_count": int(row[2] or 0),
                "succeeded_count": int(row[3] or 0),
                "failed_count": int(row[4] or 0),
                "dead_letter_count": int(row[5] or 0),
            }
        return summary

    def get_batch(self, fetch_batch_id: str) -> FetchBatchStatusOut | None:
        with self._connect() as conn:  # pragma: no cover
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        b.fetch_batch_id,
                        b.fetch_plan_id,
                        b.source_table_name,
                        b.trigger_type,
                        b.priority,
                        b.queue_name,
                        b.status,
                        b.callback_url,
                        b.operator_notes,
                        GREATEST(b.job_count, COUNT(j.job_item_id)) AS job_count,
                        b.created_at,
                        b.updated_at,
                        COUNT(j.job_item_id) FILTER (WHERE j.status = 'queued') AS queued_count,
                        COUNT(j.job_item_id) FILTER (WHERE j.status = 'leased') AS leased_count,
                        COUNT(j.job_item_id) FILTER (WHERE j.status = 'succeeded') AS succeeded_count,
                        COUNT(j.job_item_id) FILTER (WHERE j.status = 'failed') AS failed_count,
                        COUNT(j.job_item_id) FILTER (WHERE j.status = 'skipped_duplicate') AS skipped_duplicate_count,
                        COUNT(j.job_item_id) FILTER (WHERE j.status = 'cancelled') AS cancelled_count,
                        COUNT(j.job_item_id) FILTER (WHERE j.status = 'dead_letter') AS dead_letter_count
                    FROM governance.raw_fetch_batch_v1 b
                    LEFT JOIN governance.raw_fetch_job_item_v1 j
                        ON j.fetch_batch_id = b.fetch_batch_id
                    WHERE b.fetch_batch_id = %s
                    GROUP BY
                        b.fetch_batch_id,
                        b.fetch_plan_id,
                        b.source_table_name,
                        b.trigger_type,
                        b.priority,
                        b.queue_name,
                        b.status,
                        b.callback_url,
                        b.operator_notes,
                        b.job_count,
                        b.created_at,
                        b.updated_at
                    """,
                    (fetch_batch_id,),
                )
                row = cur.fetchone()
                if not row:
                    return None
        batch = self._batch_out_from_row(row)
        if batch.status != FetchBatchStatus(row[6]):
            self.repair_batch_status(batch)
        return batch

    def get_job(self, job_item_id: str) -> FetchJobStatusOut | None:
        with self._connect() as conn:  # pragma: no cover
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        job_item_id,
                        fetch_batch_id,
                        provider,
                        api_name,
                        raw_table_name,
                        request_params_json,
                        request_hash,
                        source_table_name,
                        canonical_fields,
                        symbol,
                        trade_date,
                        priority,
                        queue_name,
                        status,
                        worker_id,
                        attempt_count,
                        backup_of_job_item_id,
                        next_retry_at,
                        lease_expires_at,
                        last_error_code,
                        last_error_message,
                        raw_request_hash,
                        raw_response_schema_hash,
                        created_at,
                        updated_at
                    FROM governance.raw_fetch_job_item_v1
                    WHERE job_item_id = %s
                    """,
                    (job_item_id,),
                )
                row = cur.fetchone()
        return self._job_out_from_row(row) if row else None

    def requeue_expired_leases(self, now: datetime) -> list[FetchJobStatusOut]:
        with self._connect() as conn:  # pragma: no cover
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        job_item_id,
                        fetch_batch_id,
                        provider,
                        api_name,
                        raw_table_name,
                        request_params_json,
                        request_hash,
                        source_table_name,
                        canonical_fields,
                        symbol,
                        trade_date,
                        priority,
                        queue_name,
                        status,
                        worker_id,
                        attempt_count,
                        backup_of_job_item_id,
                        next_retry_at,
                        lease_expires_at,
                        last_error_code,
                        last_error_message,
                        raw_request_hash,
                        raw_response_schema_hash,
                        created_at,
                        updated_at
                    FROM governance.raw_fetch_job_item_v1
                    WHERE status = 'leased'
                      AND lease_expires_at IS NOT NULL
                      AND lease_expires_at <= %s
                    ORDER BY lease_expires_at ASC, created_at ASC
                    FOR UPDATE
                    """,
                    (now,),
                )
                jobs = [self._job_out_from_row(row) for row in cur.fetchall()]
                for job in jobs:
                    cur.execute(
                        """
                        UPDATE governance.raw_fetch_job_item_v1
                        SET status = 'queued',
                            worker_id = NULL,
                            lease_expires_at = NULL,
                            next_retry_at = %s,
                            updated_at = %s
                        WHERE job_item_id = %s
                        """,
                        (now, now, job.job_item_id),
                    )
            conn.commit()
        return [
            job.model_copy(
                update={
                    "status": FetchJobStatus.QUEUED,
                    "worker_id": None,
                    "lease_expires_at": None,
                    "next_retry_at": now,
                    "updated_at": now,
                }
            )
            for job in jobs
        ]

    def repair_batch_status(self, batch: FetchBatchStatusOut) -> None:
        with self._connect() as conn:  # pragma: no cover
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE governance.raw_fetch_batch_v1
                    SET status = %s,
                        updated_at = %s,
                        finished_at = CASE
                            WHEN %s IN ('succeeded','completed_with_errors','cancelled')
                                THEN COALESCE(finished_at, %s)
                            ELSE finished_at
                        END
                    WHERE fetch_batch_id = %s
                    """,
                    (
                        batch.status.value,
                        utcnow(),
                        batch.status.value,
                        utcnow(),
                        batch.fetch_batch_id,
                    ),
                )
            conn.commit()

    def list_build_triggers(self, fetch_batch_id: str | None = None) -> list[SourceBuildTriggerOut]:
        where = []
        params: list[Any] = []
        if fetch_batch_id:
            where.append("fetch_batch_id = %s")
            params.append(fetch_batch_id)
        sql = """
            SELECT
                trigger_id,
                fetch_batch_id,
                job_item_id,
                source_table_name,
                symbol,
                trade_date,
                build_scope,
                status,
                quality_check_required,
                lineage_required,
                created_at,
                finished_at
            FROM governance.source_build_trigger_v1
        """
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at DESC LIMIT 1000"
        with self._connect() as conn:  # pragma: no cover
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        return [
            SourceBuildTriggerOut(
                trigger_id=row[0],
                fetch_batch_id=row[1],
                job_item_id=row[2],
                source_table_name=row[3],
                symbol=row[4],
                trade_date=row[5],
                build_scope=row[6],
                status=row[7],
                quality_check_required=row[8],
                lineage_required=row[9],
                created_at=row[10],
                finished_at=row[11],
            )
            for row in rows
        ]

    def load_active_state(self) -> tuple[list[FetchBatchStatusOut], list[FetchJobStatusOut]]:
        with self._connect() as conn:  # pragma: no cover
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        b.fetch_batch_id,
                        b.fetch_plan_id,
                        b.source_table_name,
                        b.trigger_type,
                        b.priority,
                        b.queue_name,
                        b.status,
                        b.callback_url,
                        b.operator_notes,
                        b.job_count,
                        b.created_at,
                        b.updated_at,
                        COUNT(j.job_item_id) FILTER (WHERE j.status = 'queued') AS queued_count,
                        COUNT(j.job_item_id) FILTER (WHERE j.status = 'leased') AS leased_count,
                        COUNT(j.job_item_id) FILTER (WHERE j.status = 'succeeded') AS succeeded_count,
                        COUNT(j.job_item_id) FILTER (WHERE j.status = 'failed') AS failed_count,
                        COUNT(j.job_item_id) FILTER (WHERE j.status = 'skipped_duplicate') AS skipped_duplicate_count,
                        COUNT(j.job_item_id) FILTER (WHERE j.status = 'cancelled') AS cancelled_count,
                        COUNT(j.job_item_id) FILTER (WHERE j.status = 'dead_letter') AS dead_letter_count
                    FROM governance.raw_fetch_batch_v1 b
                    LEFT JOIN governance.raw_fetch_job_item_v1 j
                        ON j.fetch_batch_id = b.fetch_batch_id
                    WHERE b.status IN ('queued','running')
                    GROUP BY
                        b.fetch_batch_id,
                        b.fetch_plan_id,
                        b.source_table_name,
                        b.trigger_type,
                        b.priority,
                        b.queue_name,
                        b.status,
                        b.callback_url,
                        b.operator_notes,
                        b.job_count,
                        b.created_at,
                        b.updated_at
                    ORDER BY b.created_at
                    LIMIT 200
                    """
                )
                batch_rows = cur.fetchall()
                cur.execute(
                    """
                    SELECT
                        job_item_id,
                        fetch_batch_id,
                        provider,
                        api_name,
                        raw_table_name,
                        request_params_json,
                        request_hash,
                        source_table_name,
                        canonical_fields,
                        symbol,
                        trade_date,
                        priority,
                        queue_name,
                        status,
                        worker_id,
                        attempt_count,
                        backup_of_job_item_id,
                        next_retry_at,
                        lease_expires_at,
                        last_error_code,
                        last_error_message,
                        raw_request_hash,
                        raw_response_schema_hash,
                        created_at,
                        updated_at
                    FROM governance.raw_fetch_job_item_v1
                    WHERE status = 'queued'
                    ORDER BY priority, created_at
                    LIMIT 500
                    """
                )
                job_rows = cur.fetchall()
        batches = [self._batch_out_from_row(row) for row in batch_rows]
        jobs = [self._job_out_from_row(row) for row in job_rows]
        return batches, jobs


_PG = PostgresQueuePersistence()


def persist_batch_if_enabled(batch: FetchBatchStatusOut, *, request_source: str = "source-data-service") -> None:
    summary = queue_persistence_summary()
    if summary.backend == "postgres" and summary.ready_for_production_queue:
        _PG.upsert_batch(batch, request_source=request_source)


def persist_job_if_enabled(job: FetchJobStatusOut) -> None:
    summary = queue_persistence_summary()
    if summary.backend == "postgres" and summary.ready_for_production_queue:
        _PG.upsert_job(job)


def persist_worker_heartbeat_if_enabled(
    *,
    worker_id: str,
    worker_role: str = "source-fetch-worker",
    queue_names: list[str] | None = None,
    providers: list[str] | None = None,
    current_job_item_id: str | None = None,
    status: str = "alive",
    note: str | None = None,
) -> None:
    summary = queue_persistence_summary()
    if summary.backend == "postgres" and summary.ready_for_production_queue:
        _PG.upsert_worker_heartbeat(
            worker_id=worker_id,
            worker_role=worker_role,
            queue_names=queue_names,
            providers=providers,
            current_job_item_id=current_job_item_id,
            status=status,
            note=note,
        )


def persist_callback_if_enabled(event: FetchCallbackEventOut) -> None:
    summary = queue_persistence_summary()
    if summary.backend == "postgres" and summary.ready_for_production_queue:
        _PG.insert_callback(event)


def durable_callback_events_if_enabled(fetch_batch_id: str | None = None, *, pending_only: bool = False, limit: int = 1000) -> list[FetchCallbackEventOut] | None:
    summary = queue_persistence_summary()
    if summary.backend == "postgres" and summary.ready_for_production_queue:
        return _PG.read_callbacks(fetch_batch_id, pending_only=pending_only, limit=limit)
    return None


def persist_build_trigger_if_enabled(trigger: SourceBuildTriggerOut) -> None:
    summary = queue_persistence_summary()
    if summary.backend == "postgres" and summary.ready_for_production_queue:
        _PG.insert_build_trigger(trigger)


def update_build_trigger_status_if_enabled(
    trigger_id: str,
    status: str,
    finished_at: datetime | None = None,
) -> None:
    summary = queue_persistence_summary()
    if summary.backend == "postgres" and summary.ready_for_production_queue:
        _PG.update_build_trigger_status(trigger_id, status, finished_at)


def find_existing_job_item_id_if_enabled(
    provider: Provider,
    api_name: str,
    raw_table_name: str,
    request_hash: str,
) -> str | None:
    summary = queue_persistence_summary()
    if summary.backend == "postgres" and summary.ready_for_production_queue:
        return _PG.find_job_item_id_by_request(provider, api_name, raw_table_name, request_hash)
    return None


def durable_queue_counts_if_enabled() -> dict[str, int] | None:
    summary = queue_persistence_summary()
    if summary.backend == "postgres" and summary.ready_for_production_queue:
        return _PG.queue_counts()
    return None


def durable_queue_summary_if_enabled() -> dict[FetchQueueName, dict[str, int]] | None:
    summary = queue_persistence_summary()
    if summary.backend == "postgres" and summary.ready_for_production_queue:
        return _PG.queue_summary()
    return None


def durable_fetch_batch_if_enabled(fetch_batch_id: str) -> FetchBatchStatusOut | None:
    summary = queue_persistence_summary()
    if summary.backend == "postgres" and summary.ready_for_production_queue:
        return _PG.get_batch(fetch_batch_id)
    return None


def durable_fetch_job_if_enabled(job_item_id: str) -> FetchJobStatusOut | None:
    summary = queue_persistence_summary()
    if summary.backend == "postgres" and summary.ready_for_production_queue:
        return _PG.get_job(job_item_id)
    return None


def requeue_expired_leases_if_enabled(now: datetime) -> list[FetchJobStatusOut] | None:
    summary = queue_persistence_summary()
    if summary.backend == "postgres" and summary.ready_for_production_queue:
        return _PG.requeue_expired_leases(now)
    return None


def durable_build_triggers_if_enabled(fetch_batch_id: str | None = None) -> list[SourceBuildTriggerOut] | None:
    summary = queue_persistence_summary()
    if summary.backend == "postgres" and summary.ready_for_production_queue:
        return _PG.list_build_triggers(fetch_batch_id)
    return None


def load_active_state_if_enabled() -> tuple[list[FetchBatchStatusOut], list[FetchJobStatusOut]]:
    summary = queue_persistence_summary()
    if summary.backend == "postgres" and summary.ready_for_production_queue:
        return _PG.load_active_state()
    return [], []
