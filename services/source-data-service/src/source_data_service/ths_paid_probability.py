from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from source_data_service.adapters.base import stable_json_hash
from source_data_service.fetch_orchestrator import submit_fetch_batch
from source_data_service.fetch_persistence import configured_database_url, psycopg_available
from source_data_service.models import (
    FetchPriority,
    FetchSubmitRequest,
    FetchTriggerType,
    Provider,
    ThsPaidProbabilityBatchStatus,
    ThsPaidProbabilityFetchCurrentBatchRequest,
    ThsPaidProbabilityFetchCurrentBatchResult,
    ThsPaidProbabilityProbeRequest,
    ThsPaidProbabilityProbeResult,
)
from source_data_service.provider_runtime import execute_provider_fetch
from source_data_service.source_repository import list_source_rows
from source_data_service.ths_paid_credentials import (
    active_credential_version,
    cookie_status,
    record_probe_result,
)


MARKET_TZ = ZoneInfo("Asia/Shanghai")
PAID_SOURCE_TABLE = "source.ths_paid_limit_up_probability_v1"
PAID_FIELD = "paid_limit_up_probability"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


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


def _ensure_status_table(conn: Any) -> None:  # pragma: no cover - requires runtime Postgres
    with conn.cursor() as cur:
        cur.execute("CREATE SCHEMA IF NOT EXISTS governance")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS governance.ths_paid_probability_batch_status_v1 (
                trade_date DATE PRIMARY KEY,
                status TEXT NOT NULL,
                candidate_count INTEGER NOT NULL DEFAULT 0,
                fetched_count INTEGER NOT NULL DEFAULT 0,
                missing_symbols JSONB NOT NULL DEFAULT '[]'::jsonb,
                deadline_at TIMESTAMPTZ,
                next_trade_date DATE,
                cookie_status TEXT NOT NULL DEFAULT 'missing',
                message TEXT,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT ck_ths_paid_probability_batch_status_v1 CHECK (
                    status IN (
                        'no_candidates',
                        'pending_cookie',
                        'fetching',
                        'partial',
                        'ready',
                        'cookie_expired',
                        'abandoned_no_probability_before_deadline'
                    )
                )
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_ths_paid_probability_batch_status_updated_v1
                ON governance.ths_paid_probability_batch_status_v1 (status, updated_at DESC)
            """
        )


def normalize_symbol(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    lower = text.lower()
    if lower.startswith("sz") and len(lower) == 8:
        return f"{lower[2:8]}.SZ"
    if lower.startswith("sh") and len(lower) == 8:
        return f"{lower[2:8]}.SH"
    if text.endswith((".SZ", ".SH")):
        return text
    code = text.split(".", 1)[0]
    if len(code) == 6 and code.startswith(("0", "3")):
        return f"{code}.SZ"
    if len(code) == 6 and code.startswith(("5", "6", "9")):
        return f"{code}.SH"
    return text


def stock_code(symbol: str | None) -> str | None:
    normalized = normalize_symbol(symbol)
    if not normalized:
        return None
    return normalized.split(".", 1)[0]


def provider_request_params(symbol: str, trade_date: date) -> dict[str, Any]:
    version = active_credential_version() or "missing_credential"
    return {
        "date": trade_date.strftime("%Y%m%d"),
        "stock_code": stock_code(symbol),
        "credential_version": version,
    }


def _date_from_any(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value)
    try:
        if len(text) == 8 and text.isdigit():
            return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
        return date.fromisoformat(text[:10])
    except Exception:
        return None


def _bool_value(value: Any) -> bool | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "t", "yes", "y"}:
        return True
    if text in {"0", "false", "f", "no", "n"}:
        return False
    return None


def _numeric_probability(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        parsed = Decimal(str(value).replace("%", "").strip())
    except (InvalidOperation, ValueError):
        return None
    if parsed < 0 or parsed > 100:
        return None
    return parsed


def _is_closed_limit_candidate(row: Any) -> bool:
    values = dict(getattr(row, "values", {}) or {})
    event_type = values.get("limit_event_type")
    close_flag = _bool_value(values.get("close_on_limit_flag"))
    return event_type in {"limit_up", "t_board_limit_up"} and close_flag is True


def _candidate_rows(trade_date: date | None = None) -> list[Any]:
    rows = list_source_rows("source.limit_event_v1", trade_date=trade_date.isoformat() if trade_date else None)
    return [row for row in rows if _is_closed_limit_candidate(row)]


def _candidate_trade_dates() -> list[date]:
    dates = sorted(
        {
            item.trade_date
            for item in _candidate_rows(None)
            if item.trade_date is not None
        }
    )
    return dates


def resolve_candidate_trade_date(trade_date: date | None = None) -> date | None:
    if trade_date:
        return trade_date
    dates = _candidate_trade_dates()
    return dates[-1] if dates else None


def candidate_symbols(trade_date: date) -> list[str]:
    symbols = {
        normalize_symbol(row.symbol)
        for row in _candidate_rows(trade_date)
        if normalize_symbol(row.symbol)
    }
    return sorted(symbols)


def _paid_rows(trade_date: date) -> list[Any]:
    return list_source_rows(PAID_SOURCE_TABLE, trade_date=trade_date.isoformat())


def fetched_symbols(trade_date: date) -> set[str]:
    ready: set[str] = set()
    for row in _paid_rows(trade_date):
        values = dict(getattr(row, "values", {}) or {})
        probability = _numeric_probability(values.get(PAID_FIELD))
        symbol = normalize_symbol(row.symbol)
        if symbol and probability is not None:
            ready.add(symbol)
    return ready


def _calendar_dates() -> list[tuple[date, bool]]:
    rows = list_source_rows("source.trade_calendar_v1")
    dates: list[tuple[date, bool]] = []
    for row in rows:
        values = dict(getattr(row, "values", {}) or {})
        calendar_date = _date_from_any(values.get("calendar_date") or row.trade_date)
        if calendar_date is None:
            continue
        is_trading_day = _bool_value(values.get("is_trading_day"))
        dates.append((calendar_date, is_trading_day is True))
    return sorted(set(dates))


def next_trade_date(candidate_trade_date: date) -> date | None:
    for calendar_date, is_trading_day in _calendar_dates():
        if calendar_date > candidate_trade_date and is_trading_day:
            return calendar_date
    probe = candidate_trade_date + timedelta(days=1)
    for _ in range(10):
        if probe.weekday() < 5:
            return probe
        probe += timedelta(days=1)
    return None


def deadline_at(candidate_trade_date: date) -> tuple[date | None, datetime | None]:
    next_day = next_trade_date(candidate_trade_date)
    if next_day is None:
        return None, None
    local_deadline = datetime.combine(next_day, time(hour=9), tzinfo=MARKET_TZ)
    return next_day, local_deadline.astimezone(timezone.utc)


def _read_persisted_status(trade_date: date) -> dict[str, Any] | None:
    if not postgres_ready():
        return None
    try:
        with _connect() as conn:  # pragma: no cover - requires runtime Postgres
            _ensure_status_table(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT trade_date, status, candidate_count, fetched_count, missing_symbols,
                           deadline_at, next_trade_date, cookie_status, message, updated_at
                      FROM governance.ths_paid_probability_batch_status_v1
                     WHERE trade_date = %s
                     LIMIT 1
                    """,
                    (trade_date,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return {
                    "trade_date": row[0],
                    "status": row[1],
                    "candidate_count": row[2],
                    "fetched_count": row[3],
                    "missing_symbols": row[4] or [],
                    "deadline_at": row[5],
                    "next_trade_date": row[6],
                    "cookie_status": row[7],
                    "message": row[8],
                    "updated_at": row[9],
                }
    except Exception:
        return None


def _persist_status(status: ThsPaidProbabilityBatchStatus) -> None:
    if not postgres_ready():
        return
    try:
        with _connect() as conn:  # pragma: no cover - requires runtime Postgres
            from psycopg.types.json import Jsonb

            _ensure_status_table(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO governance.ths_paid_probability_batch_status_v1 (
                        trade_date, status, candidate_count, fetched_count, missing_symbols,
                        deadline_at, next_trade_date, cookie_status, message, updated_at
                    )
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (trade_date) DO UPDATE
                    SET status = EXCLUDED.status,
                        candidate_count = EXCLUDED.candidate_count,
                        fetched_count = EXCLUDED.fetched_count,
                        missing_symbols = EXCLUDED.missing_symbols,
                        deadline_at = EXCLUDED.deadline_at,
                        next_trade_date = EXCLUDED.next_trade_date,
                        cookie_status = EXCLUDED.cookie_status,
                        message = EXCLUDED.message,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (
                        status.trade_date,
                        status.status,
                        status.candidate_count,
                        status.fetched_count,
                        Jsonb(status.missing_symbols),
                        status.deadline_at,
                        status.next_trade_date,
                        status.cookie_status,
                        status.message,
                        status.updated_at,
                    ),
                )
                conn.commit()
    except Exception:
        return


def evaluate_batch_status(
    trade_date: date | None = None,
    *,
    mark_deadline: bool = True,
    now: datetime | None = None,
) -> ThsPaidProbabilityBatchStatus:
    resolved_trade_date = resolve_candidate_trade_date(trade_date) or (trade_date or utcnow().astimezone(MARKET_TZ).date())
    candidates = candidate_symbols(resolved_trade_date)
    fetched = fetched_symbols(resolved_trade_date)
    missing = sorted(set(candidates) - fetched)
    next_day, deadline = deadline_at(resolved_trade_date)
    status_record = _read_persisted_status(resolved_trade_date)
    persisted_abandoned = status_record and status_record.get("status") == "abandoned_no_probability_before_deadline"
    current_cookie = cookie_status()
    status = "ready"
    message = "paid probability ready for all current candidates"
    checked_at = now or utcnow()
    if checked_at.tzinfo is None:
        checked_at = checked_at.replace(tzinfo=timezone.utc)
    cookie_failed_probe = current_cookie.status in {"expired", "invalid"}
    if not candidates:
        status = "no_candidates"
        message = "no closed limit-up candidates are visible for this trade date"
    elif persisted_abandoned:
        status = "abandoned_no_probability_before_deadline"
        message = status_record.get("message") or "candidate batch abandoned after next trading day 09:00 without paid probability"
        if not cookie_failed_probe and "cookies expired or paid probability" in message:
            message = "candidate batch abandoned after next trading day 09:00 because paid probability is still missing"
    elif missing:
        deadline_passed = bool(deadline and checked_at >= deadline)
        if mark_deadline and deadline_passed:
            status = "abandoned_no_probability_before_deadline"
            if cookie_failed_probe:
                message = "candidate batch abandoned after next trading day 09:00 because THS paid probability probe failed"
            else:
                message = "candidate batch abandoned after next trading day 09:00 because paid probability is still missing"
        elif current_cookie.status == "missing":
            status = "pending_cookie"
            message = "paid probability requires THS login cookies"
        elif cookie_failed_probe:
            status = "cookie_expired"
            message = "paid probability requires fresh THS login cookies after a failed real probe"
        elif fetched:
            status = "partial"
            message = "paid probability is partially fetched; remaining rows stay blocked until source data arrives"
        else:
            status = "fetching"
            message = "paid probability fetch is pending through source-data-service queue"
    result = ThsPaidProbabilityBatchStatus(
        trade_date=resolved_trade_date,
        status=status,  # type: ignore[arg-type]
        candidate_count=len(candidates),
        fetched_count=len(fetched),
        missing_symbols=missing,
        deadline_at=deadline,
        next_trade_date=next_day,
        cookie_status=current_cookie.status,
        message=message,
        updated_at=checked_at,
    )
    _persist_status(result)
    return result


def probe_cookie(request: ThsPaidProbabilityProbeRequest) -> ThsPaidProbabilityProbeResult:
    if request.dry_run:
        return ThsPaidProbabilityProbeResult(ok=True, status="dry_run", trade_date=request.trade_date, symbol=request.symbol)
    status = cookie_status()
    if not status.configured:
        return ThsPaidProbabilityProbeResult(ok=False, status="missing", error_code="ths_paid_cookie_missing", error_message="THS paid probability cookies are not configured")
    trade_date = request.trade_date or resolve_candidate_trade_date(None)
    symbol = normalize_symbol(request.symbol)
    if not symbol and trade_date:
        symbols = candidate_symbols(trade_date)
        symbol = symbols[0] if symbols else None
    if trade_date is None or symbol is None:
        return ThsPaidProbabilityProbeResult(
            ok=False,
            status="invalid",
            credential_version=status.credential_version,
            trade_date=trade_date,
            symbol=symbol,
            error_code="ths_paid_probe_target_missing",
            error_message="no candidate trade_date/symbol is available for paid probability probe",
        )
    result = execute_provider_fetch(
        provider=Provider.THS,
        api_name="paid_limit_up_probability",
        params=provider_request_params(symbol, trade_date),
        dry_run=False,
    )
    if result.error or not result.rows:
        failure = result.error or result.warning or "THS paid probability probe returned no rows"
        record_probe_result(ok=False, failure_reason=failure)
        return ThsPaidProbabilityProbeResult(
            ok=False,
            status="expired",
            credential_version=status.credential_version,
            trade_date=trade_date,
            symbol=symbol,
            error_code="ths_paid_cookie_expired",
            error_message=failure,
        )
    probability = result.rows[0].row.get(PAID_FIELD)
    record_probe_result(ok=True)
    return ThsPaidProbabilityProbeResult(
        ok=True,
        status="valid",
        credential_version=status.credential_version,
        trade_date=trade_date,
        symbol=symbol,
        probability=str(probability) if probability is not None else None,
    )


def fetch_current_batch(
    request: ThsPaidProbabilityFetchCurrentBatchRequest,
) -> ThsPaidProbabilityFetchCurrentBatchResult:
    trade_date = resolve_candidate_trade_date(request.trade_date)
    if trade_date is None:
        return ThsPaidProbabilityFetchCurrentBatchResult(
            trade_date=None,
            submitted=False,
            batch_status=None,
            warnings=["no visible candidate trade_date; run source.limit_event_v1 first"],
        )
    status_before = evaluate_batch_status(trade_date)
    if status_before.status in {"no_candidates", "abandoned_no_probability_before_deadline", "ready"}:
        return ThsPaidProbabilityFetchCurrentBatchResult(
            trade_date=trade_date,
            submitted=False,
            batch_status=status_before,
            warnings=[status_before.message or "no fetch needed"],
        )
    requested_symbols = sorted({normalize_symbol(item) for item in request.symbols if normalize_symbol(item)})
    symbols = requested_symbols or status_before.missing_symbols
    if not symbols:
        return ThsPaidProbabilityFetchCurrentBatchResult(
            trade_date=trade_date,
            submitted=False,
            batch_status=status_before,
            warnings=["no missing symbols remain for paid probability fetch"],
        )
    probe = probe_cookie(ThsPaidProbabilityProbeRequest(trade_date=trade_date, symbol=symbols[0], dry_run=request.dry_run))
    if not probe.ok:
        status_after_probe = evaluate_batch_status(trade_date, mark_deadline=False)
        return ThsPaidProbabilityFetchCurrentBatchResult(
            trade_date=trade_date,
            submitted=False,
            batch_status=status_after_probe,
            probe=probe,
            warnings=[probe.error_message or "THS paid probability cookie probe failed"],
        )
    if request.dry_run:
        return ThsPaidProbabilityFetchCurrentBatchResult(
            trade_date=trade_date,
            submitted=False,
            batch_status=status_before,
            probe=probe,
            warnings=["dry_run=true: cookie probe passed but fetch batch was not submitted"],
        )
    idempotency_hash = stable_json_hash(
        {
            "trade_date": trade_date.isoformat(),
            "symbols": symbols,
            "credential_version": active_credential_version(),
        }
    )[:16]
    submitted = submit_fetch_batch(
        FetchSubmitRequest(
            source_table_name=request.source_table_name,
            canonical_fields=[PAID_FIELD],
            symbols=symbols,
            trade_date=trade_date,
            trigger_type=FetchTriggerType.SCHEDULED_PERIODIC,
            priority=FetchPriority.P0_URGENT_RELEASE,
            request_source=request.request_source,
            model_code="hot_candidates",
            model_phase="paid_probability_ingest",
            dry_run=False,
            prefer_batch=False,
            idempotency_key=f"ths_paid_probability:{trade_date.isoformat()}:{idempotency_hash}",
        )
    )
    status_after = evaluate_batch_status(trade_date, mark_deadline=False)
    return ThsPaidProbabilityFetchCurrentBatchResult(
        trade_date=trade_date,
        submitted=True,
        fetch_batch_id=submitted.fetch_batch_id,
        submitted_job_count=submitted.submitted_job_count,
        skipped_duplicate_count=submitted.skipped_duplicate_count,
        batch_status=status_after,
        probe=probe,
    )


def deadline_check(trade_date: date | None = None) -> ThsPaidProbabilityBatchStatus:
    if trade_date:
        return evaluate_batch_status(trade_date, mark_deadline=True)
    candidates = _candidate_trade_dates()
    if not candidates:
        return evaluate_batch_status(None, mark_deadline=True)
    now = utcnow()
    due_dates = []
    for candidate_date in candidates:
        _next_day, deadline = deadline_at(candidate_date)
        if deadline and now >= deadline:
            due_dates.append(candidate_date)
    target = due_dates[-1] if due_dates else candidates[-1]
    return evaluate_batch_status(target, mark_deadline=True, now=now)
