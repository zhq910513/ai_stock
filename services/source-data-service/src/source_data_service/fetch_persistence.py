from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from math import ceil
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


_MARKET_TIMEZONE = timezone(timedelta(hours=8), name="Asia/Shanghai")
_FULL_A_DAILY_SOURCE_TABLES = {
    "source.adjusted_daily_bar_v1",
    "source.daily_bar_v1",
    "source.limit_price_v1",
    "source.stock_universe_daily_v1",
    "source.trade_status_v1",
}
_FULL_A_MIN_EXPECTED_SOURCE_ROWS = 5000
_FULL_A_MIN_COMPLETION_RATE = 0.995


def market_today(now: datetime | None = None) -> date:
    return (now or utcnow()).astimezone(_MARKET_TIMEZONE).date()


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
            return db_status
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

    def get_batch_id_by_idempotency_key(self, idempotency_key: str) -> str | None:
        with self._connect() as conn:  # pragma: no cover
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT fetch_batch_id
                    FROM governance.raw_fetch_idempotency_key_v1
                    WHERE idempotency_key = %s
                    """,
                    (idempotency_key,),
                )
                row = cur.fetchone()
        return str(row[0]) if row else None

    def upsert_idempotency_key(
        self,
        *,
        idempotency_key: str,
        fetch_batch_id: str,
        request_source: str,
        request_hash: str,
    ) -> str:
        with self._connect() as conn:  # pragma: no cover
            with conn.cursor() as cur:
                cur.execute(
                    """
                    WITH inserted AS (
                        INSERT INTO governance.raw_fetch_idempotency_key_v1 (
                            idempotency_key, fetch_batch_id, request_source, request_hash, created_at
                        ) VALUES (%s,%s,%s,%s,%s)
                        ON CONFLICT (idempotency_key) DO NOTHING
                        RETURNING fetch_batch_id
                    )
                    SELECT fetch_batch_id FROM inserted
                    UNION ALL
                    SELECT fetch_batch_id
                    FROM governance.raw_fetch_idempotency_key_v1
                    WHERE idempotency_key = %s
                    LIMIT 1
                    """,
                    (idempotency_key, fetch_batch_id, request_source, request_hash, utcnow(), idempotency_key),
                )
                row = cur.fetchone()
            conn.commit()
        return str(row[0]) if row else fetch_batch_id

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

    def find_job_item_ids_by_requests(
        self,
        requests: list[tuple[Provider, str, str, str]],
    ) -> dict[tuple[str, str, str, str], str]:
        if not requests:
            return {}
        payload = [
            {
                "provider": provider.value,
                "api_name": api_name,
                "raw_table_name": raw_table_name,
                "request_hash": request_hash,
            }
            for provider, api_name, raw_table_name, request_hash in requests
        ]
        with self._connect() as conn:  # pragma: no cover
            with conn.cursor() as cur:
                cur.execute(
                    """
                    WITH requested AS (
                        SELECT *
                        FROM jsonb_to_recordset(%s::jsonb) AS r(
                            provider text,
                            api_name text,
                            raw_table_name text,
                            request_hash text
                        )
                    ),
                    ranked AS (
                        SELECT
                            r.provider,
                            r.api_name,
                            r.raw_table_name,
                            r.request_hash,
                            j.job_item_id,
                            ROW_NUMBER() OVER (
                                PARTITION BY r.provider, r.api_name, r.raw_table_name, r.request_hash
                                ORDER BY j.created_at DESC
                            ) AS rn
                        FROM requested r
                        JOIN governance.raw_fetch_job_item_v1 j
                          ON j.provider = r.provider
                         AND j.api_name = r.api_name
                         AND j.raw_table_name = r.raw_table_name
                         AND j.request_hash = r.request_hash
                    )
                    SELECT provider, api_name, raw_table_name, request_hash, job_item_id
                    FROM ranked
                    WHERE rn = 1
                    """,
                    (self._json(payload),),
                )
                rows = cur.fetchall()
        return {
            (str(row[0]), str(row[1]), str(row[2]), str(row[3])): str(row[4])
            for row in rows
        }

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

    def cancel_expired_daily_jobs(self, *, now: datetime, market_today: date) -> list[FetchJobStatusOut]:
        lifecycle_message = (
            "daily lifecycle expired before worker completion; submit formal repair/backfill to rebuild"
        )
        with self._connect() as conn:  # pragma: no cover
            with conn.cursor() as cur:
                cur.execute(
                    """
                    WITH expired AS (
                        SELECT job.job_item_id
                        FROM governance.raw_fetch_job_item_v1 job
                        JOIN governance.raw_fetch_batch_v1 batch
                          ON batch.fetch_batch_id = job.fetch_batch_id
                        WHERE job.status IN ('queued','leased')
                          AND batch.request_source = 'scheduler-service'
                          AND batch.trigger_type IN ('scheduled_periodic','model_release_preflight')
                          AND (
                              (
                                  COALESCE(job.request_params_json #>> '{__orchestration_context,request_source}', '') = 'scheduler-service'
                                  AND COALESCE(job.request_params_json #>> '{__orchestration_context,lifecycle_expires_at}', '') <> ''
                                  AND (job.request_params_json #>> '{__orchestration_context,lifecycle_expires_at}')::timestamptz <= %s
                              )
                              OR (job.trade_date IS NOT NULL AND job.trade_date < %s)
                              OR (
                                  job.trade_date = %s
                                  AND COALESCE(job.request_params_json #>> '{__orchestration_context,lifecycle_expires_at}', '') = ''
                                  AND job.created_at <= %s - CASE
                                      WHEN job.source_table_name IN ('source.realtime_quote_v1','source.minute_bar_v1','source.trade_tick_v1','source.auction_snapshot_v1') THEN INTERVAL '10 minutes'
                                      WHEN job.source_table_name IN ('source.stock_universe_daily_v1','source.trade_status_v1','source.limit_price_v1') THEN INTERVAL '1 day'
                                      WHEN job.source_table_name = 'source.ths_paid_limit_up_probability_v1' THEN INTERVAL '4 hours'
                                      WHEN job.source_table_name IN ('source.daily_bar_v1','source.adjusted_daily_bar_v1','source.limit_event_v1','source.stock_moneyflow_daily_v1','source.event_news_v1') THEN INTERVAL '2 hours'
                                      ELSE INTERVAL '1 day'
                                  END
                              )
                          )
                        FOR UPDATE
                    )
                    UPDATE governance.raw_fetch_job_item_v1 job
                    SET status = 'cancelled',
                        worker_id = NULL,
                        lease_expires_at = NULL,
                        next_retry_at = NULL,
                        last_error_code = 'expired_lifecycle',
                        last_error_message = %s,
                        updated_at = %s,
                        finished_at = COALESCE(job.finished_at, %s)
                    FROM expired
                    WHERE job.job_item_id = expired.job_item_id
                    RETURNING
                        job.job_item_id,
                        job.fetch_batch_id,
                        job.provider,
                        job.api_name,
                        job.raw_table_name,
                        job.request_params_json,
                        job.request_hash,
                        job.source_table_name,
                        job.canonical_fields,
                        job.symbol,
                        job.trade_date,
                        job.priority,
                        job.queue_name,
                        job.status,
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
                        job.updated_at
                    """,
                    (
                        now,
                        market_today,
                        market_today,
                        now,
                        lifecycle_message,
                        now,
                        now,
                    ),
                )
                jobs = [self._job_out_from_row(row) for row in cur.fetchall()]
            conn.commit()
        return jobs

    def cancel_expired_build_triggers(self, *, now: datetime, market_today: date) -> list[SourceBuildTriggerOut]:
        running_expired_before = now - timedelta(hours=1)
        with self._connect() as conn:  # pragma: no cover
            with conn.cursor() as cur:
                cur.execute(
                    """
                    WITH expired AS (
                        SELECT trigger.trigger_id
                        FROM governance.source_build_trigger_v1 trigger
                        JOIN governance.raw_fetch_job_item_v1 job
                          ON job.job_item_id = trigger.job_item_id
                        JOIN governance.raw_fetch_batch_v1 batch
                          ON batch.fetch_batch_id = job.fetch_batch_id
                        WHERE trigger.trade_date IS NOT NULL
                          AND trigger.status IN ('queued','running')
                          AND batch.request_source = 'scheduler-service'
                          AND batch.trigger_type IN ('scheduled_periodic','model_release_preflight')
                          AND (
                              trigger.trade_date < %s
                              OR (job.status = 'cancelled' AND job.last_error_code = 'expired_lifecycle')
                          )
                          AND (
                              trigger.status = 'queued'
                              OR trigger.created_at <= %s
                              OR job.status = 'cancelled'
                          )
                          AND NOT EXISTS (
                              SELECT 1
                              FROM governance.source_build_execution_result_v1 result
                              WHERE result.trigger_id = trigger.trigger_id
                                AND result.status IN ('succeeded','failed','dry_run','skipped_no_raw')
                          )
                        FOR UPDATE
                    )
                    UPDATE governance.source_build_trigger_v1 trigger
                    SET status = 'cancelled',
                        finished_at = COALESCE(trigger.finished_at, %s)
                    FROM expired
                    WHERE trigger.trigger_id = expired.trigger_id
                    RETURNING
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
                        trigger.finished_at
                    """,
                    (
                        market_today,
                        running_expired_before,
                        now,
                    ),
                )
                rows = cur.fetchall()
            conn.commit()
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
                quality_check_required=bool(row[8]),
                lineage_required=bool(row[9]),
                created_at=row[10],
                finished_at=row[11],
            )
            for row in rows
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

    def get_build_trigger(self, trigger_id: str) -> SourceBuildTriggerOut | None:
        with self._connect() as conn:  # pragma: no cover
            with conn.cursor() as cur:
                cur.execute(
                    """
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
                    WHERE trigger_id = %s
                    """,
                    (trigger_id,),
                )
                row = cur.fetchone()
        if row is None:
            return None
        return SourceBuildTriggerOut(
            trigger_id=row[0],
            fetch_batch_id=row[1],
            job_item_id=row[2],
            source_table_name=row[3],
            symbol=row[4],
            trade_date=row[5],
            build_scope=row[6],
            status=row[7],
            quality_check_required=bool(row[8]),
            lineage_required=bool(row[9]),
            created_at=row[10],
            finished_at=row[11],
        )
    def build_trigger_exists(
        self,
        *,
        fetch_batch_id: str,
        job_item_id: str | None,
        source_table_name: str,
        symbol: str | None,
        trade_date: date | None,
    ) -> bool:
        with self._connect() as conn:  # pragma: no cover
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1
                    FROM governance.source_build_trigger_v1
                    WHERE fetch_batch_id = %s
                      AND job_item_id IS NOT DISTINCT FROM %s
                      AND source_table_name = %s
                      AND symbol IS NOT DISTINCT FROM %s
                      AND trade_date IS NOT DISTINCT FROM %s
                      AND status IN ('queued', 'running', 'succeeded')
                    LIMIT 1
                    """,
                    (fetch_batch_id, job_item_id, source_table_name, symbol, trade_date),
                )
                return cur.fetchone() is not None

    def list_queued_build_triggers(
        self,
        *,
        limit: int = 100,
        source_table_names: list[str] | None = None,
    ) -> list[SourceBuildTriggerOut]:
        params: list[Any] = []
        filters = ["trigger.status = 'queued'"]
        if source_table_names:
            filters.append("trigger.source_table_name = ANY(%s)")
            params.append(source_table_names)
        params.append(limit)
        sql = f"""
            SELECT
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
                trigger.finished_at
            FROM governance.source_build_trigger_v1 trigger
            WHERE {' AND '.join(filters)}
              AND NOT EXISTS (
                  SELECT 1
                  FROM governance.source_build_execution_result_v1 result
                  WHERE result.trigger_id = trigger.trigger_id
                    AND result.status IN ('succeeded', 'failed', 'dry_run', 'skipped_no_raw')
              )
            ORDER BY trigger.trade_date DESC NULLS LAST, trigger.created_at ASC
            LIMIT %s
        """
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
                quality_check_required=bool(row[8]),
                lineage_required=bool(row[9]),
                created_at=row[10],
                finished_at=row[11],
            )
            for row in rows
        ]
    def load_active_state(
        self,
        *,
        queue_names: list[str] | None = None,
        providers: list[str] | None = None,
        queued_limit: int = 500,
    ) -> tuple[list[FetchBatchStatusOut], list[FetchJobStatusOut]]:
        queue_filters = [str(item) for item in (queue_names or []) if str(item)]
        provider_filters = [str(item) for item in (providers or []) if str(item)]
        job_filters = ["status = 'queued'"]
        job_params: list[Any] = []
        if queue_filters:
            job_filters.append("queue_name = ANY(%s)")
            job_params.append(queue_filters)
        if provider_filters:
            job_filters.append("provider = ANY(%s)")
            job_params.append(provider_filters)
        job_params.append(max(1, min(int(queued_limit or 500), 5000)))
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
                    f"""
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
                    FROM (
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
                            updated_at,
                            ROW_NUMBER() OVER (
                                PARTITION BY priority, trade_date, queue_name, provider, api_name, source_table_name
                                ORDER BY created_at, job_item_id
                            ) AS source_table_rank
                        FROM governance.raw_fetch_job_item_v1
                        WHERE {' AND '.join(job_filters)}
                    ) ranked_jobs
                    ORDER BY priority, trade_date DESC NULLS LAST, source_table_rank, queue_name, provider, api_name, source_table_name, created_at
                    LIMIT %s
                    """,
                    job_params,
                )
                job_rows = cur.fetchall()
        batches = [self._batch_out_from_row(row) for row in batch_rows]
        jobs = [self._job_out_from_row(row) for row in job_rows]
        return batches, jobs

    @staticmethod
    def _quote_identifier(value: str) -> str:
        return '"' + str(value).replace('"', '""') + '"'

    def _columns_with_types(self, conn: Any, schema: str, table: str) -> dict[str, str]:  # pragma: no cover - requires runtime Postgres
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                """,
                (schema, table),
            )
            return {str(row[0]): str(row[1]) for row in cur.fetchall()}

    @staticmethod
    def _jsonable(value: Any) -> Any:
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, dict):
            return {str(k): PostgresQueuePersistence._jsonable(v) for k, v in value.items()}
        if isinstance(value, list):
            return [PostgresQueuePersistence._jsonable(item) for item in value]
        return value

    @staticmethod
    def _daily_table_bucket(tables: dict[str, dict[str, Any]], source_table_name: str) -> dict[str, Any]:
        return tables.setdefault(
            source_table_name,
            {
                "source_table_name": source_table_name,
                "raw_job_count": 0,
                "raw_succeeded_count": 0,
                "raw_active_count": 0,
                "raw_failed_count": 0,
                "raw_waiting_count": 0,
                "raw_cancelled_count": 0,
                "build_result_count": 0,
                "build_succeeded_count": 0,
                "build_failed_count": 0,
                "build_failure_audit_count": 0,
                "raw_row_count": 0,
                "source_row_count": 0,
                "lineage_row_count": 0,
                "gap_count": 0,
                "p0_gap_count": 0,
                "p1_gap_count": 0,
                "latest_raw_updated_at": None,
                "latest_build_finished_at": None,
                "latest_source_available_at": None,
                "latest_gap_detected_at": None,
                "failure_samples": [],
            },
        )

    @staticmethod
    def _max_time(*values: Any) -> Any:
        candidates = [value for value in values if value not in (None, "")]
        if not candidates:
            return None
        return max(candidates)

    @staticmethod
    def _daily_table_has_final_data_failure(item: dict[str, Any]) -> bool:
        raw_failed = int(item.get("raw_failed_count") or 0)
        raw_succeeded = int(item.get("raw_succeeded_count") or 0)
        raw_active = int(item.get("raw_active_count") or 0)
        raw_waiting = int(item.get("raw_waiting_count") or 0)
        build_succeeded = int(item.get("build_succeeded_count") or 0)
        build_failed = int(item.get("build_failed_count") or 0)
        source_rows = int(item.get("source_row_count") or 0)
        p0_gaps = int(item.get("p0_gap_count") or 0)
        if build_failed or p0_gaps:
            return True
        if raw_failed and not raw_succeeded and not build_succeeded and not source_rows and not raw_active and not raw_waiting:
            return True
        return False

    @staticmethod
    def _daily_table_coverage(item: dict[str, Any], *, universe_row_count: int = 0) -> dict[str, Any]:
        table = str(item.get("source_table_name") or "")
        if table not in _FULL_A_DAILY_SOURCE_TABLES:
            return {
                "coverage_required": False,
                "coverage_insufficient": False,
                "expected_source_row_count": None,
                "minimum_required_source_row_count": None,
                "actual_coverage_rate": None,
            }
        source_rows = int(item.get("source_row_count") or 0)
        if table == "source.stock_universe_daily_v1" and source_rows >= _FULL_A_MIN_EXPECTED_SOURCE_ROWS:
            expected_rows = source_rows
        else:
            expected_rows = max(int(universe_row_count or 0), _FULL_A_MIN_EXPECTED_SOURCE_ROWS)
        minimum_rows = ceil(expected_rows * _FULL_A_MIN_COMPLETION_RATE)
        actual_rate = round(source_rows / expected_rows, 6) if expected_rows else None
        return {
            "coverage_required": True,
            "coverage_insufficient": source_rows < minimum_rows,
            "expected_source_row_count": expected_rows,
            "minimum_required_source_row_count": minimum_rows,
            "actual_coverage_rate": actual_rate,
        }

    @staticmethod
    def _decorate_daily_table_status(item: dict[str, Any], *, universe_row_count: int = 0) -> dict[str, Any]:
        raw_failed = int(item.get("raw_failed_count") or 0)
        raw_active = int(item.get("raw_active_count") or 0)
        raw_waiting = int(item.get("raw_waiting_count") or 0)
        has_open_raw_work = bool(raw_active or raw_waiting)
        has_product = bool(int(item.get("source_row_count") or 0) or int(item.get("build_succeeded_count") or 0))
        build_failure_audit = int(item.get("build_failure_audit_count") or 0)
        raw_cancelled = int(item.get("raw_cancelled_count") or 0)
        coverage = PostgresQueuePersistence._daily_table_coverage(item, universe_row_count=universe_row_count)
        coverage_insufficient = bool(coverage["coverage_insufficient"] and has_product)
        terminal_coverage_insufficient = bool(coverage_insufficient and not has_open_raw_work)
        final_failed = PostgresQueuePersistence._daily_table_has_final_data_failure(item) or terminal_coverage_insufficient
        item.update(coverage)
        item["coverage_insufficient"] = coverage_insufficient
        item["final_data_failed"] = final_failed
        item["raw_failure_audit_only"] = bool(raw_failed and not final_failed)
        item["build_failure_audit_only"] = bool(build_failure_audit and not final_failed)
        if terminal_coverage_insufficient:
            item["data_asset_status"] = "coverage_insufficient"
        elif final_failed:
            item["data_asset_status"] = "failed"
        elif coverage_insufficient and has_open_raw_work:
            item["data_asset_status"] = "collecting"
        elif (raw_failed or build_failure_audit) and has_product:
            item["data_asset_status"] = "completed_with_provider_audit"
        elif has_product or int(item.get("raw_succeeded_count") or 0):
            item["data_asset_status"] = "completed"
        elif has_open_raw_work:
            item["data_asset_status"] = "collecting"
        elif raw_cancelled:
            item["data_asset_status"] = "expired_closed"
        else:
            item["data_asset_status"] = "no_activity"
        return item

    def _source_table_row_count(self, conn: Any, table_name: str, trade_date: date) -> tuple[int, Any]:  # pragma: no cover - requires runtime Postgres
        columns = self._columns_with_types(conn, "source", table_name)
        date_column = None
        for candidate in ("trade_date", "trading_day", "calendar_date", "day"):
            if candidate in columns:
                date_column = candidate
                break
        if date_column is None:
            for candidate in ("bar_time", "snapshot_time", "event_time", "captured_at", "available_at", "updated_at"):
                if candidate in columns:
                    date_column = candidate
                    break
        if date_column is None:
            return 0, None
        latest_column = None
        for candidate in ("available_at", "updated_at", "captured_at", date_column):
            if candidate in columns:
                latest_column = candidate
                break
        latest_expr = f"MAX({self._quote_identifier(latest_column)})" if latest_column else "NULL"
        qualified = f'{self._quote_identifier("source")}.{self._quote_identifier(table_name)}'
        quoted_date_col = self._quote_identifier(date_column)
        date_type = columns.get(date_column, "")
        if date_type == "date":
            where = f"{quoted_date_col} = %s"
            params = (trade_date,)
        else:
            next_day = trade_date + timedelta(days=1)
            where = f"{quoted_date_col} >= %s AND {quoted_date_col} < %s"
            params = (trade_date, next_day)
        completeness_sql = None
        if table_name in {"trade_status_v1", "source.trade_status_v1"}:
            required_fields = ["is_tradable", "is_suspended", "is_st", "is_delisting_risk"]
            if all(field in columns for field in required_fields):
                completeness_sql = " AND ".join(f"{self._quote_identifier(field)} IS NOT NULL" for field in required_fields)
        with conn.cursor() as cur:
            if completeness_sql:
                cur.execute(
                    f"SELECT COUNT(*) FILTER (WHERE {completeness_sql}) AS row_count, {latest_expr} AS latest_at FROM {qualified} WHERE {where}",
                    params,
                )
            else:
                cur.execute(
                    f"SELECT COUNT(*) AS row_count, {latest_expr} AS latest_at FROM {qualified} WHERE {where}",
                    params,
                )
            row = cur.fetchone()
        return int(row[0] or 0), row[1]

    def daily_data_summary(self, trade_date: date) -> dict[str, Any]:  # pragma: no cover - requires runtime Postgres
        if not self.database_url or not psycopg_available():
            return {
                "contract_kind": "source_daily_data_summary_v1",
                "read_only": True,
                "trade_date": trade_date.isoformat(),
                "generated_at": utcnow().isoformat(),
                "read_status": "postgres_unavailable",
                "summary": {},
                "tables": [],
                "failures": [],
            }
        tables: dict[str, dict[str, Any]] = {}
        failures: list[dict[str, Any]] = []
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT source_table_name, status, COUNT(*) AS count, MAX(updated_at) AS latest_updated_at
                    FROM governance.raw_fetch_job_item_v1
                    WHERE trade_date = %s
                       OR (trade_date IS NULL AND date_range_start <= %s AND date_range_end >= %s)
                    GROUP BY source_table_name, status
                    """,
                    (trade_date, trade_date, trade_date),
                )
                for source_table_name, status, count, latest_updated_at in cur.fetchall():
                    bucket = self._daily_table_bucket(tables, str(source_table_name or ""))
                    amount = int(count or 0)
                    bucket["raw_job_count"] += amount
                    status_text = str(status or "")
                    if status_text in {"succeeded", "skipped_duplicate"}:
                        bucket["raw_succeeded_count"] += amount
                    elif status_text in {"queued"}:
                        bucket["raw_waiting_count"] += amount
                    elif status_text in {"leased"}:
                        bucket["raw_active_count"] += amount
                    elif status_text in {"failed", "dead_letter"}:
                        bucket["raw_failed_count"] += amount
                    elif status_text == "cancelled":
                        bucket["raw_cancelled_count"] += amount
                    bucket["latest_raw_updated_at"] = self._max_time(bucket.get("latest_raw_updated_at"), latest_updated_at)

                cur.execute(
                    """
                    SELECT source_table_name, job_item_id, fetch_batch_id, provider, api_name, status,
                           last_error_code, last_error_message, symbol, updated_at
                    FROM governance.raw_fetch_job_item_v1
                    WHERE (trade_date = %s OR (trade_date IS NULL AND date_range_start <= %s AND date_range_end >= %s))
                      AND status IN ('failed','dead_letter')
                    ORDER BY updated_at DESC
                    LIMIT 200
                    """,
                    (trade_date, trade_date, trade_date),
                )
                for row in cur.fetchall():
                    item = {
                        "source_table_name": row[0],
                        "job_item_id": row[1],
                        "fetch_batch_id": row[2],
                        "provider": row[3],
                        "api_name": row[4],
                        "status": row[5],
                        "error_code": row[6],
                        "error_message": row[7],
                        "symbol": row[8],
                        "updated_at": row[9],
                    }
                    failures.append(item)
                    bucket = self._daily_table_bucket(tables, str(row[0] or ""))
                    if len(bucket["failure_samples"]) < 5:
                        bucket["failure_samples"].append(item)

                cur.execute(
                    """
                    WITH build_facts AS MATERIALIZED (
                        SELECT
                            result.source_table_name,
                            result.status,
                            COALESCE(result.raw_row_count, 0) AS raw_row_count,
                            COALESCE(result.source_row_count, 0) AS source_row_count,
                            COALESCE(result.lineage_row_count, 0) AS lineage_row_count,
                            result.finished_at,
                            trigger.symbol,
                            trigger.trade_date
                        FROM governance.source_build_execution_result_v1 result
                        JOIN governance.source_build_trigger_v1 trigger
                          ON trigger.trigger_id = result.trigger_id
                        WHERE trigger.trade_date = %s
                    ),
                    successful_identities AS (
                        SELECT
                            source_table_name,
                            COALESCE(symbol, '') AS symbol_key,
                            trade_date,
                            MAX(finished_at) AS latest_success_finished_at
                        FROM build_facts
                        WHERE status = 'succeeded'
                          AND COALESCE(source_row_count, 0) > 0
                        GROUP BY source_table_name, COALESCE(symbol, ''), trade_date
                    ),
                    bucketed AS (
                        SELECT
                            failed.source_table_name,
                            CASE
                                WHEN failed.status IN ('failed', 'skipped_no_raw')
                                 AND success.source_table_name IS NOT NULL
                                 AND (
                                     failed.finished_at IS NULL
                                     OR success.latest_success_finished_at IS NULL
                                     OR success.latest_success_finished_at >= failed.finished_at
                                 )
                                THEN 'recovered_failure'
                                ELSE failed.status
                            END AS status_bucket,
                            failed.raw_row_count,
                            failed.source_row_count,
                            failed.lineage_row_count,
                            failed.finished_at
                        FROM build_facts failed
                        LEFT JOIN successful_identities success
                          ON success.source_table_name = failed.source_table_name
                         AND success.symbol_key = COALESCE(failed.symbol, '')
                         AND success.trade_date = failed.trade_date
                    )
                    SELECT source_table_name, status_bucket, COUNT(*) AS count,
                           COALESCE(SUM(raw_row_count), 0) AS raw_rows,
                           COALESCE(SUM(source_row_count), 0) AS source_rows,
                           COALESCE(SUM(lineage_row_count), 0) AS lineage_rows,
                           MAX(finished_at) AS latest_finished_at
                    FROM bucketed
                    GROUP BY source_table_name, status_bucket
                    """,
                    (trade_date,),
                )
                for source_table_name, status, count, raw_rows, source_rows, lineage_rows, latest_finished_at in cur.fetchall():
                    bucket = self._daily_table_bucket(tables, str(source_table_name or ""))
                    amount = int(count or 0)
                    bucket["build_result_count"] += amount
                    status_text = str(status or "")
                    if status_text == "succeeded":
                        bucket["build_succeeded_count"] += amount
                    elif status_text in {"failed", "skipped_no_raw"}:
                        bucket["build_failed_count"] += amount
                    elif status_text == "recovered_failure":
                        bucket["build_failure_audit_count"] += amount
                    bucket["raw_row_count"] += int(raw_rows or 0)
                    bucket["source_row_count"] += int(source_rows or 0)
                    bucket["lineage_row_count"] += int(lineage_rows or 0)
                    bucket["latest_build_finished_at"] = self._max_time(bucket.get("latest_build_finished_at"), latest_finished_at)

                cur.execute(
                    """
                    SELECT source_table_name, severity, COUNT(*) AS count, MAX(detected_at) AS latest_detected_at
                    FROM governance.source_gap_v1
                    WHERE trade_date = %s
                    GROUP BY source_table_name, severity
                    """,
                    (trade_date,),
                )
                for source_table_name, severity, count, latest_detected_at in cur.fetchall():
                    bucket = self._daily_table_bucket(tables, str(source_table_name or ""))
                    amount = int(count or 0)
                    bucket["gap_count"] += amount
                    if str(severity or "").upper() == "P0":
                        bucket["p0_gap_count"] += amount
                    if str(severity or "").upper() == "P1":
                        bucket["p1_gap_count"] += amount
                    bucket["latest_gap_detected_at"] = self._max_time(bucket.get("latest_gap_detected_at"), latest_detected_at)

                cur.execute(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'source'
                      AND table_type = 'BASE TABLE'
                    ORDER BY table_name
                    """
                )
                source_tables = [str(row[0]) for row in cur.fetchall()]

            for table_name in source_tables:
                source_table_name = f"source.{table_name}"
                try:
                    row_count, latest_available_at = self._source_table_row_count(conn, table_name, trade_date)
                except Exception as exc:  # noqa: BLE001
                    bucket = self._daily_table_bucket(tables, source_table_name)
                    bucket["source_read_error"] = str(exc)
                    continue
                if row_count or source_table_name in tables:
                    bucket = self._daily_table_bucket(tables, source_table_name)
                    if source_table_name == "source.trade_status_v1":
                        bucket["source_row_count"] = row_count
                    else:
                        bucket["source_row_count"] = max(int(bucket.get("source_row_count") or 0), row_count)
                    bucket["latest_source_available_at"] = self._max_time(bucket.get("latest_source_available_at"), latest_available_at)

        universe_row_count = int(tables.get("source.stock_universe_daily_v1", {}).get("source_row_count") or 0)
        table_rows = [
            self._jsonable(self._decorate_daily_table_status(item, universe_row_count=universe_row_count))
            for item in tables.values()
            if item.get("source_table_name")
        ]
        table_rows.sort(key=lambda item: str(item.get("source_table_name") or ""))
        raw_job_count = sum(int(item.get("raw_job_count") or 0) for item in table_rows)
        raw_failed_jobs = sum(int(item.get("raw_failed_count") or 0) for item in table_rows)
        build_result_count = sum(int(item.get("build_result_count") or 0) for item in table_rows)
        build_failed_results = sum(int(item.get("build_failed_count") or 0) for item in table_rows)
        source_row_count = sum(int(item.get("source_row_count") or 0) for item in table_rows)
        latest_updates = [
            item.get("latest_raw_updated_at")
            or item.get("latest_build_finished_at")
            or item.get("latest_source_available_at")
            for item in table_rows
            if item.get("latest_raw_updated_at") or item.get("latest_build_finished_at") or item.get("latest_source_available_at")
        ]
        return {
            "contract_kind": "source_daily_data_summary_v1",
            "read_only": True,
            "trade_date": trade_date.isoformat(),
            "generated_at": utcnow().isoformat(),
            "read_status": "ok",
            "summary": {
                "raw_job_count": raw_job_count,
                "raw_succeeded_jobs": sum(int(item.get("raw_succeeded_count") or 0) for item in table_rows),
                "raw_active_jobs": sum(int(item.get("raw_active_count") or 0) for item in table_rows),
                "raw_waiting_jobs": sum(int(item.get("raw_waiting_count") or 0) for item in table_rows),
                "raw_failed_jobs": raw_failed_jobs,
                "raw_cancelled_jobs": sum(int(item.get("raw_cancelled_count") or 0) for item in table_rows),
                "expired_closed_table_count": sum(1 for item in table_rows if item.get("data_asset_status") == "expired_closed"),
                "coverage_insufficient_table_count": sum(1 for item in table_rows if item.get("data_asset_status") == "coverage_insufficient"),
                "build_result_count": build_result_count,
                "build_succeeded_results": sum(int(item.get("build_succeeded_count") or 0) for item in table_rows),
                "build_failed_results": build_failed_results,
                "build_failure_audit_results": sum(int(item.get("build_failure_audit_count") or 0) for item in table_rows),
                "source_row_count": source_row_count,
                "data_failed_table_count": sum(1 for item in table_rows if item.get("final_data_failed")),
                "raw_failed_table_count": sum(1 for item in table_rows if int(item.get("raw_failed_count") or 0)),
                "audit_warning_table_count": sum(1 for item in table_rows if item.get("raw_failure_audit_only") or item.get("build_failure_audit_only")),
                "data_produced_table_count": sum(1 for item in table_rows if item.get("data_asset_status") in {"completed", "completed_with_provider_audit"}),
                "latest_data_update_at": max(latest_updates) if latest_updates else None,
            },
            "tables": table_rows,
            "failures": self._jsonable(failures),
        }

_PG = PostgresQueuePersistence()
_BUILD_TRIGGER_LIFECYCLE_INTERVAL_SECONDS = 60
_LAST_BUILD_TRIGGER_LIFECYCLE_AT: datetime | None = None


def persist_batch_if_enabled(batch: FetchBatchStatusOut, *, request_source: str = "source-data-service") -> None:
    summary = queue_persistence_summary()
    if summary.backend == "postgres" and summary.ready_for_production_queue:
        _PG.upsert_batch(batch, request_source=request_source)


def durable_fetch_batch_id_by_idempotency_key_if_enabled(idempotency_key: str) -> str | None:
    summary = queue_persistence_summary()
    if summary.backend == "postgres" and summary.ready_for_production_queue:
        return _PG.get_batch_id_by_idempotency_key(idempotency_key)
    return None


def persist_idempotency_key_if_enabled(
    *,
    idempotency_key: str,
    fetch_batch_id: str,
    request_source: str,
    request_hash: str,
) -> str | None:
    summary = queue_persistence_summary()
    if summary.backend == "postgres" and summary.ready_for_production_queue:
        return _PG.upsert_idempotency_key(
            idempotency_key=idempotency_key,
            fetch_batch_id=fetch_batch_id,
            request_source=request_source,
            request_hash=request_hash,
        )
    return None


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


def find_existing_job_item_ids_if_enabled(
    requests: list[tuple[Provider, str, str, str]],
) -> dict[tuple[str, str, str, str], str] | None:
    summary = queue_persistence_summary()
    if summary.backend == "postgres" and summary.ready_for_production_queue:
        return _PG.find_job_item_ids_by_requests(requests)
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


def cancel_expired_daily_jobs_if_enabled(*, now: datetime, market_day: date) -> list[FetchJobStatusOut] | None:
    summary = queue_persistence_summary()
    if summary.backend == "postgres" and summary.ready_for_production_queue:
        return _PG.cancel_expired_daily_jobs(now=now, market_today=market_day)
    return None


def cancel_expired_build_triggers_if_enabled(*, now: datetime, market_day: date) -> list[SourceBuildTriggerOut] | None:
    summary = queue_persistence_summary()
    if summary.backend == "postgres" and summary.ready_for_production_queue:
        return _PG.cancel_expired_build_triggers(now=now, market_today=market_day)
    return None


def durable_build_triggers_if_enabled(fetch_batch_id: str | None = None) -> list[SourceBuildTriggerOut] | None:
    summary = queue_persistence_summary()
    if summary.backend == "postgres" and summary.ready_for_production_queue:
        return _PG.list_build_triggers(fetch_batch_id)
    return None


def durable_build_trigger_if_enabled(trigger_id: str) -> SourceBuildTriggerOut | None:
    summary = queue_persistence_summary()
    if summary.backend == "postgres" and summary.ready_for_production_queue:
        return _PG.get_build_trigger(trigger_id)
    return None

def build_trigger_exists_if_enabled(
    *,
    fetch_batch_id: str,
    job_item_id: str | None,
    source_table_name: str,
    symbol: str | None,
    trade_date: date | None,
) -> bool | None:
    summary = queue_persistence_summary()
    if summary.backend == "postgres" and summary.ready_for_production_queue:
        return _PG.build_trigger_exists(
            fetch_batch_id=fetch_batch_id,
            job_item_id=job_item_id,
            source_table_name=source_table_name,
            symbol=symbol,
            trade_date=trade_date,
        )
    return None


def durable_queued_build_triggers_if_enabled(
    *,
    limit: int = 100,
    source_table_names: list[str] | None = None,
) -> list[SourceBuildTriggerOut] | None:
    global _LAST_BUILD_TRIGGER_LIFECYCLE_AT
    summary = queue_persistence_summary()
    if summary.backend == "postgres" and summary.ready_for_production_queue:
        now = utcnow()
        if (
            _LAST_BUILD_TRIGGER_LIFECYCLE_AT is None
            or (now - _LAST_BUILD_TRIGGER_LIFECYCLE_AT).total_seconds() >= _BUILD_TRIGGER_LIFECYCLE_INTERVAL_SECONDS
        ):
            _PG.cancel_expired_build_triggers(now=now, market_today=market_today(now))
            _LAST_BUILD_TRIGGER_LIFECYCLE_AT = now
        return _PG.list_queued_build_triggers(limit=limit, source_table_names=source_table_names)
    return None


def durable_daily_data_summary_if_enabled(trade_date: date) -> dict[str, Any]:
    summary = queue_persistence_summary()
    if summary.backend == "postgres" and summary.ready_for_production_queue:
        return _PG.daily_data_summary(trade_date)
    return {
        "contract_kind": "source_daily_data_summary_v1",
        "read_only": True,
        "trade_date": trade_date.isoformat(),
        "generated_at": utcnow().isoformat(),
        "read_status": "postgres_unavailable",
        "summary": {},
        "tables": [],
        "failures": [],
        "persistence": summary.__dict__,
    }

def load_active_state_if_enabled(
    *,
    queue_names: list[str] | None = None,
    providers: list[str] | None = None,
) -> tuple[list[FetchBatchStatusOut], list[FetchJobStatusOut]]:
    summary = queue_persistence_summary()
    if summary.backend == "postgres" and summary.ready_for_production_queue:
        return _PG.load_active_state(queue_names=queue_names, providers=providers)
    return [], []
