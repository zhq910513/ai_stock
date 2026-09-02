from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from source_data_service.adapters.base import stable_json_hash
from source_data_service.fetch_persistence import configured_database_url, psycopg_available
from source_data_service.models import ThsPaidProbabilityCookieStatus


_MEMORY_CREDENTIAL: dict[str, Any] | None = None


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def credential_version(user: str, userid: str) -> str:
    return "ths_paid_" + stable_json_hash({"user": user, "userid": userid})[:16]


def mask_secret(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value)
    if len(text) <= 8:
        return "*" * len(text)
    return f"{text[:4]}...{text[-4:]}"


def _database_url() -> str | None:
    return configured_database_url()


def _connect():  # pragma: no cover - requires runtime Postgres
    database_url = _database_url()
    if not database_url or not psycopg_available():
        raise RuntimeError("postgres is not configured")
    import psycopg

    return psycopg.connect(database_url)


def postgres_ready() -> bool:
    return bool(_database_url()) and psycopg_available()


def _ensure_tables(conn: Any) -> None:  # pragma: no cover - requires runtime Postgres
    with conn.cursor() as cur:
        cur.execute("CREATE SCHEMA IF NOT EXISTS governance")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS governance.ths_paid_probability_cookie_v1 (
                credential_id BIGSERIAL PRIMARY KEY,
                credential_version TEXT NOT NULL UNIQUE,
                user_cookie TEXT NOT NULL,
                userid_cookie TEXT NOT NULL,
                user_masked TEXT NOT NULL,
                userid_masked TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending_probe',
                is_active BOOLEAN NOT NULL DEFAULT true,
                updated_by TEXT,
                last_checked_at TIMESTAMPTZ,
                last_success_at TIMESTAMPTZ,
                last_failure_at TIMESTAMPTZ,
                failure_reason TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT ck_ths_paid_probability_cookie_status_v1 CHECK (
                    status IN ('pending_probe','valid','expired','invalid')
                )
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_ths_paid_probability_cookie_active_v1
                ON governance.ths_paid_probability_cookie_v1 (is_active, updated_at DESC)
            """
        )


def save_active_cookie(*, user: str, userid: str, updated_by: str | None = None) -> ThsPaidProbabilityCookieStatus:
    global _MEMORY_CREDENTIAL
    now = utcnow()
    version = credential_version(user, userid)
    record = {
        "credential_version": version,
        "user_cookie": user,
        "userid_cookie": userid,
        "user_masked": mask_secret(user),
        "userid_masked": mask_secret(userid),
        "status": "pending_probe",
        "is_active": True,
        "updated_by": updated_by,
        "last_checked_at": None,
        "last_success_at": None,
        "last_failure_at": None,
        "failure_reason": None,
        "updated_at": now,
    }
    _MEMORY_CREDENTIAL = dict(record)
    if postgres_ready():
        with _connect() as conn:  # pragma: no cover - requires runtime Postgres
            _ensure_tables(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE governance.ths_paid_probability_cookie_v1
                       SET is_active = false, updated_at = %s
                     WHERE is_active = true
                       AND credential_version <> %s
                    """,
                    (now, version),
                )
                cur.execute(
                    """
                    INSERT INTO governance.ths_paid_probability_cookie_v1 (
                        credential_version, user_cookie, userid_cookie,
                        user_masked, userid_masked, status, is_active, updated_by,
                        last_checked_at, last_success_at, last_failure_at, failure_reason,
                        updated_at
                    )
                    VALUES (%s,%s,%s,%s,%s,'pending_probe',true,%s,NULL,NULL,NULL,NULL,%s)
                    ON CONFLICT (credential_version) DO UPDATE
                    SET user_cookie = EXCLUDED.user_cookie,
                        userid_cookie = EXCLUDED.userid_cookie,
                        user_masked = EXCLUDED.user_masked,
                        userid_masked = EXCLUDED.userid_masked,
                        status = 'pending_probe',
                        is_active = true,
                        updated_by = EXCLUDED.updated_by,
                        last_checked_at = NULL,
                        last_success_at = NULL,
                        last_failure_at = NULL,
                        failure_reason = NULL,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (version, user, userid, mask_secret(user), mask_secret(userid), updated_by, now),
                )
                conn.commit()
    return cookie_status()


def _row_to_record(row: Any) -> dict[str, Any]:
    keys = [
        "credential_version",
        "user_cookie",
        "userid_cookie",
        "user_masked",
        "userid_masked",
        "status",
        "last_checked_at",
        "last_success_at",
        "last_failure_at",
        "failure_reason",
    ]
    return dict(zip(keys, row, strict=True))


def active_cookie_record() -> dict[str, Any] | None:
    if postgres_ready():
        try:
            with _connect() as conn:  # pragma: no cover - requires runtime Postgres
                _ensure_tables(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT credential_version, user_cookie, userid_cookie,
                               user_masked, userid_masked, status,
                               last_checked_at, last_success_at, last_failure_at, failure_reason
                          FROM governance.ths_paid_probability_cookie_v1
                         WHERE is_active = true
                         ORDER BY updated_at DESC, credential_id DESC
                         LIMIT 1
                        """
                    )
                    row = cur.fetchone()
                    if row:
                        return _row_to_record(row)
        except Exception:
            pass
    return dict(_MEMORY_CREDENTIAL) if _MEMORY_CREDENTIAL else None


def active_cookie_values() -> tuple[str, str, str] | None:
    record = active_cookie_record()
    if not record:
        return None
    return str(record["user_cookie"]), str(record["userid_cookie"]), str(record["credential_version"])


def active_credential_version() -> str | None:
    record = active_cookie_record()
    return str(record["credential_version"]) if record else None


def cookie_status() -> ThsPaidProbabilityCookieStatus:
    record = active_cookie_record()
    if not record:
        return ThsPaidProbabilityCookieStatus(configured=False, status="missing")
    return ThsPaidProbabilityCookieStatus(
        configured=True,
        status=record.get("status") or "pending_probe",
        credential_version=record.get("credential_version"),
        user_masked=record.get("user_masked") or mask_secret(record.get("user_cookie")),
        userid_masked=record.get("userid_masked") or mask_secret(record.get("userid_cookie")),
        last_checked_at=record.get("last_checked_at"),
        last_success_at=record.get("last_success_at"),
        last_failure_at=record.get("last_failure_at"),
        failure_reason=record.get("failure_reason"),
    )


def record_probe_result(*, ok: bool, failure_reason: str | None = None) -> ThsPaidProbabilityCookieStatus:
    global _MEMORY_CREDENTIAL
    record = active_cookie_record()
    if not record:
        return ThsPaidProbabilityCookieStatus(configured=False, status="missing")
    now = utcnow()
    status = "valid" if ok else "expired"
    if _MEMORY_CREDENTIAL:
        _MEMORY_CREDENTIAL["status"] = status
        _MEMORY_CREDENTIAL["last_checked_at"] = now
        if ok:
            _MEMORY_CREDENTIAL["last_success_at"] = now
            _MEMORY_CREDENTIAL["failure_reason"] = None
        else:
            _MEMORY_CREDENTIAL["last_failure_at"] = now
            _MEMORY_CREDENTIAL["failure_reason"] = failure_reason
    if postgres_ready():
        with _connect() as conn:  # pragma: no cover - requires runtime Postgres
            _ensure_tables(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE governance.ths_paid_probability_cookie_v1
                       SET status = %s,
                           last_checked_at = %s,
                           last_success_at = CASE WHEN %s THEN %s ELSE last_success_at END,
                           last_failure_at = CASE WHEN %s THEN last_failure_at ELSE %s END,
                           failure_reason = CASE WHEN %s THEN NULL ELSE %s END,
                           updated_at = %s
                     WHERE is_active = true
                       AND credential_version = %s
                    """,
                    (
                        status,
                        now,
                        ok,
                        now,
                        ok,
                        now,
                        ok,
                        failure_reason,
                        now,
                        record["credential_version"],
                    ),
                )
                conn.commit()
    return cookie_status()
