from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from source_data_service import __version__
from source_data_service.fetch_persistence import configured_database_url, psycopg_available
from source_data_service.models import (
    AcceptanceCheckEvidence,
    AcceptanceRunOut,
    AcceptanceRunPersistRequest,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _json_value(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        return json.loads(value)
    return value


def _connect():  # pragma: no cover - runtime Postgres evidence path
    db_url = configured_database_url()
    if not db_url:
        raise RuntimeError("database URL is not configured")
    try:
        import psycopg
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("psycopg is required for acceptance evidence persistence") from exc
    return psycopg.connect(db_url)


def _not_persisted_out(request: AcceptanceRunPersistRequest, *, note: str) -> AcceptanceRunOut:
    now = _utcnow()
    return AcceptanceRunOut(
        acceptance_run_id=request.acceptance_run_id or f"acceptance_{uuid4().hex[:20]}",
        version_label=request.version_label or f"source_data_acceptance/{__version__}",
        base_url=request.base_url,
        dry_run_provider=request.dry_run_provider,
        require_postgres=request.require_postgres,
        require_real_provider_probe=request.require_real_provider_probe,
        status=request.status,
        can_lock_candidate=request.can_lock_candidate,
        blocking_reasons=request.blocking_reasons,
        warning_reasons=request.warning_reasons,
        started_at=request.started_at or now,
        finished_at=request.finished_at or now,
        checks=request.checks,
        persisted=False,
        note=note,
    )


def persist_acceptance_run(request: AcceptanceRunPersistRequest) -> AcceptanceRunOut:
    """Persist one DS-7 HTTP-only acceptance run into governance evidence tables."""

    if not configured_database_url() or not psycopg_available():
        return _not_persisted_out(
            request,
            note="Postgres evidence store is unavailable; run was accepted by API but not persisted.",
        )

    now = _utcnow()
    acceptance_run_id = request.acceptance_run_id or f"acceptance_{uuid4().hex[:20]}"
    version_label = request.version_label or f"source_data_acceptance/{__version__}"
    started_at = request.started_at or now
    finished_at = request.finished_at or now

    with _connect() as conn:  # pragma: no cover - requires runtime Postgres
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO governance.source_data_acceptance_run_v1 (
                    acceptance_run_id, version_label, base_url, require_postgres,
                    require_real_provider_probe, status, can_lock_candidate,
                    blocking_reasons_json, warning_reasons_json, started_at, finished_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s)
                ON CONFLICT (acceptance_run_id) DO UPDATE SET
                    version_label = EXCLUDED.version_label,
                    base_url = EXCLUDED.base_url,
                    require_postgres = EXCLUDED.require_postgres,
                    require_real_provider_probe = EXCLUDED.require_real_provider_probe,
                    status = EXCLUDED.status,
                    can_lock_candidate = EXCLUDED.can_lock_candidate,
                    blocking_reasons_json = EXCLUDED.blocking_reasons_json,
                    warning_reasons_json = EXCLUDED.warning_reasons_json,
                    finished_at = EXCLUDED.finished_at
                """,
                (
                    acceptance_run_id,
                    version_label,
                    request.base_url,
                    request.require_postgres,
                    request.require_real_provider_probe,
                    request.status,
                    request.can_lock_candidate,
                    _json(request.blocking_reasons),
                    _json(request.warning_reasons),
                    started_at,
                    finished_at,
                ),
            )
            for check in request.checks:
                cur.execute(
                    """
                    INSERT INTO governance.source_data_acceptance_check_v1 (
                        acceptance_run_id, check_code, status, required_for_lock,
                        evidence_json, operator_action, checked_at
                    ) VALUES (%s,%s,%s,%s,%s::jsonb,%s,%s)
                    ON CONFLICT (acceptance_run_id, check_code) DO UPDATE SET
                        status = EXCLUDED.status,
                        required_for_lock = EXCLUDED.required_for_lock,
                        evidence_json = EXCLUDED.evidence_json,
                        operator_action = EXCLUDED.operator_action,
                        checked_at = EXCLUDED.checked_at
                    """,
                    (
                        acceptance_run_id,
                        check.check_code,
                        check.status,
                        check.required_for_lock,
                        _json(check.evidence),
                        check.operator_action,
                        check.checked_at,
                    ),
                )
        conn.commit()

    return AcceptanceRunOut(
        acceptance_run_id=acceptance_run_id,
        version_label=version_label,
        base_url=request.base_url,
        dry_run_provider=request.dry_run_provider,
        require_postgres=request.require_postgres,
        require_real_provider_probe=request.require_real_provider_probe,
        status=request.status,
        can_lock_candidate=request.can_lock_candidate,
        blocking_reasons=request.blocking_reasons,
        warning_reasons=request.warning_reasons,
        started_at=started_at,
        finished_at=finished_at,
        checks=request.checks,
        persisted=True,
        note="acceptance run and check evidence persisted to governance.source_data_acceptance_*",
    )


def list_acceptance_runs(limit: int = 20) -> list[AcceptanceRunOut]:
    if not configured_database_url() or not psycopg_available():
        return []
    with _connect() as conn:  # pragma: no cover - requires runtime Postgres
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    acceptance_run_id, version_label, base_url, require_postgres,
                    require_real_provider_probe, status, can_lock_candidate,
                    blocking_reasons_json, warning_reasons_json, started_at, finished_at
                FROM governance.source_data_acceptance_run_v1
                ORDER BY started_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
    return [_run_from_row(row, checks=[]) for row in rows]


def get_acceptance_run(acceptance_run_id: str) -> AcceptanceRunOut | None:
    if not configured_database_url() or not psycopg_available():
        return None
    with _connect() as conn:  # pragma: no cover - requires runtime Postgres
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    acceptance_run_id, version_label, base_url, require_postgres,
                    require_real_provider_probe, status, can_lock_candidate,
                    blocking_reasons_json, warning_reasons_json, started_at, finished_at
                FROM governance.source_data_acceptance_run_v1
                WHERE acceptance_run_id = %s
                """,
                (acceptance_run_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            cur.execute(
                """
                SELECT check_code, status, required_for_lock, evidence_json, operator_action, checked_at
                FROM governance.source_data_acceptance_check_v1
                WHERE acceptance_run_id = %s
                ORDER BY checked_at, check_code
                """,
                (acceptance_run_id,),
            )
            check_rows = cur.fetchall()
    checks = [
        AcceptanceCheckEvidence(
            check_code=check[0],
            status=check[1],
            required_for_lock=check[2],
            evidence=_json_value(check[3], {}),
            operator_action=check[4],
            checked_at=check[5],
        )
        for check in check_rows
    ]
    return _run_from_row(row, checks=checks)


def _run_from_row(row: Any, *, checks: list[AcceptanceCheckEvidence]) -> AcceptanceRunOut:
    return AcceptanceRunOut(
        acceptance_run_id=row[0],
        version_label=row[1],
        base_url=row[2],
        require_postgres=row[3],
        require_real_provider_probe=row[4],
        status=row[5],
        can_lock_candidate=row[6],
        blocking_reasons=_json_value(row[7], []),
        warning_reasons=_json_value(row[8], []),
        started_at=row[9],
        finished_at=row[10],
        checks=checks,
        persisted=True,
        note="loaded from governance.source_data_acceptance_*",
    )
