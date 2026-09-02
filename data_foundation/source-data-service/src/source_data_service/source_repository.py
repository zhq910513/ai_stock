from __future__ import annotations

import os
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from uuid import uuid4

from source_data_service.adapters.base import stable_json_hash
from source_data_service.fetch_orchestrator import get_fetch_job, list_source_build_triggers
from source_data_service.fetch_persistence import (
    configured_database_url,
    durable_build_trigger_if_enabled,
    durable_queued_build_triggers_if_enabled,
    psycopg_available,
    queue_persistence_summary,
    update_build_trigger_status_if_enabled,
)
from source_data_service.models import (
    Provider,
    QualityStatus,
    RawFetchResult,
    RawIngestResult,
    RawRepositoryStatusOut,
    SourceBuildExecuteRequest,
    SourceBuildExecutionResult,
    SourceBuildWorkerRunOnceRequest,
    SourceBuildWorkerRunOnceResult,
    SourceCanonicalRowOut,
    SourceLineageRecordOut,
)
from source_data_service.provider_registry import get_api_spec, list_source_requirements
from source_data_service.source_build import validate_raw_rows
from source_data_service.models import QualityValidationRequest
from source_data_service.settings import settings
from source_data_service.postgres_repository import PostgresRawSourceRepository
from source_data_service.symbol_rules import is_a_share_symbol, normalize_symbol


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# In-memory repository is intentionally deterministic for unit and contract tests.
# Production must run with SOURCE_DATA_QUEUE_BACKEND=postgres and persist raw/source
# writes through the SQL contracts. The same API surface is used in both modes so
# service callers do not depend on storage implementation details.
_RAW_ROWS: dict[str, dict[str, Any]] = {}
_SOURCE_ROWS: dict[str, SourceCanonicalRowOut] = {}
_LINEAGE_ROWS: list[SourceLineageRecordOut] = []
_BUILD_RESULTS: list[SourceBuildExecutionResult] = []
_RAW_REQUEST_INDEX: dict[str, list[str]] = {}
_PG_REPO = PostgresRawSourceRepository()
_DATE_GUARDED_SOURCE_TABLES = {
    "source.adjusted_daily_bar_v1",
    "source.auction_snapshot_v1",
    "source.daily_bar_v1",
    "source.limit_event_v1",
    "source.limit_price_v1",
    "source.minute_bar_v1",
    "source.realtime_quote_v1",
    "source.stock_moneyflow_daily_v1",
    "source.ths_paid_limit_up_probability_v1",
    "source.stock_universe_daily_v1",
    "source.trade_status_v1",
    "source.trade_tick_v1",
}
_SYMBOL_GUARDED_SOURCE_TABLES = {
    *_DATE_GUARDED_SOURCE_TABLES,
    "source.stock_master_v1",
}


def repository_backend() -> str:
    # Reuse queue backend for now so operators cannot accidentally run a durable
    # queue with non-durable raw/source writes.
    return "postgres" if (settings.queue_backend or "memory").lower() == "postgres" else "memory"


def repository_status() -> RawRepositoryStatusOut:
    backend = repository_backend()
    db_url = configured_database_url() or os.environ.get("AI_STOCK_DATABASE_URL")
    driver = psycopg_available()
    ready = backend == "postgres" and bool(db_url) and driver
    pg_counts: dict[str, int] = {}
    if ready and _PG_REPO.ready:
        try:
            pg_counts = _PG_REPO.repository_counts()
        except Exception:
            pg_counts = {}
    if ready:
        note = "postgres raw/source repository configured; raw rows, canonical source rows and lineage can be persisted"
    elif backend == "postgres":
        note = "postgres repository requested but database URL or psycopg driver is unavailable"
    else:
        note = "memory repository is for local contract tests only; production must use postgres"
    return RawRepositoryStatusOut(
        backend=backend,  # type: ignore[arg-type]
        durable_raw_writes=backend == "postgres",
        database_url_configured=bool(db_url),
        driver_available=driver,
        ready_for_production_raw_store=ready,
        raw_row_count=pg_counts.get("raw_row_count", len(_RAW_ROWS)),
        source_row_count=pg_counts.get("source_row_count", len(_SOURCE_ROWS)),
        lineage_row_count=pg_counts.get("lineage_row_count", len(_LINEAGE_ROWS)),
        build_result_count=pg_counts.get("build_result_count", len(_BUILD_RESULTS)),
        note=note,
    )


def _raw_id(provider: Provider, api_name: str, raw_table_name: str, request_hash: str | None, response_row_hash: str | None, row: dict[str, Any]) -> str:
    return stable_json_hash(
        {
            "provider": provider.value,
            "api_name": api_name,
            "raw_table_name": raw_table_name,
            "request_hash": request_hash,
            "response_row_hash": response_row_hash,
            "row": row,
        }
    )


def _normalize_symbol(value: str | None) -> str | None:
    return normalize_symbol(value)


def _extract_symbol(row: dict[str, Any], request_params: dict[str, Any]) -> str | None:
    return _normalize_symbol(
        row.get("symbol")
        or request_params.get("provider_code")
        or row.get("code")
        or row.get("代码")
        or row.get("ts_code")
        or request_params.get("symbol")
        or request_params.get("code")
        or request_params.get("ts_code")
        or row.get("secid")
        or request_params.get("secid")
    )


def _extract_trade_date(row: dict[str, Any], request_params: dict[str, Any]) -> str | None:
    value = (
        row.get("date")
        or row.get("日期")
        or row.get("trade_date")
        or row.get("calendar_date")
        or row.get("cal_date")
        or request_params.get("trade_date")
        or request_params.get("day")
    )
    if value is None:
        start = request_params.get("start_date")
        end = request_params.get("end_date")
        if start and start == end:
            value = start
    if value is None:
        return None
    text = str(value)
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return text


def _date_text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return text


def _requested_identity_mismatch(
    *,
    source_table_name: str,
    requested_symbol: str | None,
    requested_trade_date: Any,
    built_symbol: str | None,
    built_trade_date: Any,
    raw_id: Any,
) -> str | None:
    if source_table_name in _SYMBOL_GUARDED_SOURCE_TABLES and requested_symbol and built_symbol != requested_symbol:
        return (
            f"{source_table_name} raw row symbol {built_symbol or '<missing>'} "
            f"does not match requested symbol {requested_symbol}; raw_id={raw_id}"
        )
    requested_date = _date_text(requested_trade_date) if source_table_name in _DATE_GUARDED_SOURCE_TABLES else None
    built_date = _date_text(built_trade_date)
    if requested_date and built_date != requested_date:
        return (
            f"{source_table_name} raw row trade_date {built_date or '<missing>'} "
            f"does not match requested trade_date {requested_date}; raw_id={raw_id}"
        )
    return None


def ingest_raw_fetch_result(result: RawFetchResult) -> RawIngestResult:
    spec = get_api_spec(result.provider, result.api_name)
    warnings: list[str] = []
    duplicate = 0
    rejected = 0
    ingested = 0
    if result.raw_table_name != spec.raw_table_name:
        warnings.append(f"raw_table_name mismatch: expected {spec.raw_table_name}, got {result.raw_table_name}")
    row_payloads = [raw.row for raw in result.rows]
    quality_status = "not_checked"
    if row_payloads:
        quality = validate_raw_rows(QualityValidationRequest(provider=result.provider, api_name=result.api_name, rows=row_payloads))
        quality_status = "passed" if quality.build_allowed else "blocked"
        if not quality.build_allowed:
            rejected = len(row_payloads)
            return RawIngestResult(
                provider=result.provider,
                api_name=result.api_name,
                raw_table_name=spec.raw_table_name,
                request_hash=result.request_hash,
                response_schema_hash=result.response_schema_hash,
                ingested_row_count=0,
                duplicate_row_count=0,
                rejected_row_count=rejected,
                raw_write_status="rejected",
                quality_status="blocked",
                warnings=[issue.message for issue in quality.issues],
            )
    pg_inserted_rows: list[dict[str, Any]] = []
    if repository_backend() == "postgres" and _PG_REPO.ready and result.rows:
        try:
            pg_inserted_rows, pg_duplicate, pg_rejected = _PG_REPO.insert_raw_result(result)
            duplicate += pg_duplicate
            rejected += pg_rejected
        except Exception as exc:  # pragma: no cover - depends on runtime Postgres
            return RawIngestResult(
                provider=result.provider,
                api_name=result.api_name,
                raw_table_name=spec.raw_table_name,
                request_hash=result.request_hash,
                response_schema_hash=result.response_schema_hash,
                ingested_row_count=0,
                duplicate_row_count=duplicate,
                rejected_row_count=len(row_payloads),
                raw_write_status="rejected",
                quality_status="blocked",
                warnings=[f"postgres raw write failed: {exc}"],
            )
    pg_rows_by_hash = {
        str(row.get("response_row_hash")): row
        for row in pg_inserted_rows
        if row.get("response_row_hash")
    }
    for raw in result.rows:
        row = dict(raw.row)
        request_hash = raw.request_hash or result.request_hash
        response_row_hash = raw.response_row_hash or stable_json_hash(row)
        pg_row = pg_rows_by_hash.get(str(response_row_hash))
        raw_id = str(pg_row["raw_id"]) if pg_row and pg_row.get("raw_id") is not None else _raw_id(result.provider, result.api_name, spec.raw_table_name, request_hash, response_row_hash, row)
        if raw_id in _RAW_ROWS:
            duplicate += 1
            continue
        symbol = _extract_symbol(row, raw.request_params or result.request_params)
        trade_date = _extract_trade_date(row, raw.request_params or result.request_params)
        _RAW_ROWS[raw_id] = {
            "raw_id": raw_id,
            "provider": result.provider,
            "api_name": result.api_name,
            "raw_table_name": spec.raw_table_name,
            "request_params": raw.request_params or result.request_params,
            "request_hash": request_hash,
            "response_schema_hash": raw.response_schema_hash or result.response_schema_hash,
            "response_row_hash": response_row_hash,
            "row": row,
            "symbol": symbol,
            "trade_date": trade_date,
            "captured_at": raw.captured_at,
            "available_at": raw.available_at or raw.captured_at,
            "batch_id": raw.batch_id,
            "biz_key": raw.biz_key or (f"{symbol}|{trade_date}" if symbol and trade_date else None),
            "quality_status": raw.quality_status,
        }
        if request_hash:
            _RAW_REQUEST_INDEX.setdefault(request_hash, []).append(raw_id)
        ingested += 1
    status = "accepted" if not warnings else "accepted_with_warnings"
    ingest_out = RawIngestResult(
        provider=result.provider,
        api_name=result.api_name,
        raw_table_name=spec.raw_table_name,
        request_hash=result.request_hash,
        response_schema_hash=result.response_schema_hash,
        ingested_row_count=ingested if not pg_inserted_rows else max(ingested, len(pg_inserted_rows)),
        duplicate_row_count=duplicate,
        rejected_row_count=rejected,
        raw_write_status=status,  # type: ignore[arg-type]
        quality_status=quality_status,  # type: ignore[arg-type]
        warnings=warnings,
    )
    if repository_backend() == "postgres" and _PG_REPO.ready:
        try:
            _PG_REPO.insert_raw_write_audit(ingest_out)
        except Exception as exc:  # pragma: no cover - audit failure is surfaced but raw write remains accepted
            ingest_out.warnings.append(f"postgres raw write audit failed: {exc}")
    return ingest_out


def _candidate_raw_rows(job_request_hash: str | None, provider: Provider, api_name: str, source_table_name: str, symbol: str | None, trade_date: str | None) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    if job_request_hash and job_request_hash in _RAW_REQUEST_INDEX:
        candidates.extend(_RAW_ROWS[raw_id] for raw_id in _RAW_REQUEST_INDEX[job_request_hash] if raw_id in _RAW_ROWS)
    if not candidates:
        for raw in _RAW_ROWS.values():
            if raw["provider"] != provider or raw["api_name"] != api_name:
                continue
            if symbol and raw.get("symbol") != symbol:
                continue
            if trade_date and raw.get("trade_date") != trade_date:
                continue
            candidates.append(raw)
    if not candidates and repository_backend() == "postgres" and _PG_REPO.ready:
        try:
            candidates.extend(
                _PG_REPO.read_raw_rows(
                    provider=provider,
                    api_name=api_name,
                    raw_table_name=get_api_spec(provider, api_name).raw_table_name,
                    request_hash=job_request_hash,
                    symbol=symbol,
                    trade_date=trade_date,
                )
            )
        except Exception:
            pass
    return candidates


def _decimal_str(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except Exception:
        return None


def _preserve_raw_text_field(canonical_field_name: str) -> bool:
    if canonical_field_name in {"provider_definition", "event_type", "url", "title"}:
        return True
    return canonical_field_name.endswith("_code") or canonical_field_name.endswith("_label")


def _decimal_value(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).replace(",", ""))
    except Exception:
        return None


def _first_value(row: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in row and row.get(name) not in (None, ""):
            return row.get(name)
    return None


def _limit_rule_for_symbol(symbol: str | None, row: dict[str, Any]) -> tuple[str, Decimal]:
    is_st = str(_first_value(row, "isST", "is_st") or "").strip().lower() in {"1", "true", "yes", "y"}
    code = str(symbol or _first_value(row, "symbol", "code", "secid") or "")
    if is_st:
        return "st_5pct", Decimal("0.05")
    if code.startswith(("300", "301", "688")):
        return "registration_20pct", Decimal("0.20")
    return "normal_10pct", Decimal("0.10")


def _round_price(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _usable_source_row(row: SourceCanonicalRowOut) -> bool:
    return row.source_quality_status == QualityStatus.USABLE or str(row.source_quality_status).lower() == QualityStatus.USABLE.value


def _source_row_close_price(row: SourceCanonicalRowOut) -> Decimal | None:
    return _decimal_value(row.values.get("close_price"))


def _previous_trading_day_from_calendar(trade_date: str) -> str | None:
    try:
        rows = list_source_rows("source.trade_calendar_v1", trade_date=trade_date)
    except Exception:
        return None
    for row in rows:
        calendar_date = _date_text(row.trade_date or row.values.get("calendar_date") or row.values.get("trading_day"))
        if calendar_date != trade_date:
            continue
        value = row.values.get("pretrade_date") or row.values.get("prev_trading_day")
        return _date_text(value)
    return None


def _latest_daily_close_before(symbol: str, trade_date: str) -> SourceCanonicalRowOut | None:
    try:
        target = date.fromisoformat(trade_date)
    except ValueError:
        return None
    try:
        rows = list_source_rows("source.daily_bar_v1", symbol=symbol)
    except Exception:
        return None
    candidates: list[SourceCanonicalRowOut] = []
    for row in rows:
        if not _usable_source_row(row) or _source_row_close_price(row) is None or row.trade_date is None:
            continue
        if row.trade_date < target:
            candidates.append(row)
    if not candidates:
        return None
    return max(candidates, key=lambda item: item.trade_date or date.min)


def _previous_daily_close_source_row(symbol: str | None, trade_date: Any) -> SourceCanonicalRowOut | None:
    normalized_symbol = _normalize_symbol(symbol)
    target_trade_date = _date_text(trade_date)
    if not normalized_symbol or not target_trade_date:
        return None
    previous_trade_date = _previous_trading_day_from_calendar(target_trade_date)
    if previous_trade_date:
        try:
            rows = list_source_rows("source.daily_bar_v1", symbol=normalized_symbol, trade_date=previous_trade_date)
        except Exception:
            rows = []
        for row in rows:
            if _usable_source_row(row) and _source_row_close_price(row) is not None:
                return row
    return _latest_daily_close_before(normalized_symbol, target_trade_date)


def _with_limit_price_preclose_source(row: dict[str, Any], symbol: str | None, trade_date: Any) -> dict[str, Any]:
    if _decimal_value(_first_value(row, "preclose", "pre_close", "pre_close_price", "prev_close_price")) is not None:
        return row
    source_row = _previous_daily_close_source_row(symbol, trade_date)
    if source_row is None:
        return row
    close_price = _source_row_close_price(source_row)
    if close_price is None:
        return row
    enriched = dict(row)
    enriched["_source_daily_prev_close_price"] = str(close_price)
    enriched["_source_daily_prev_close_trade_date"] = source_row.trade_date.isoformat() if source_row.trade_date else None
    enriched["_source_daily_prev_close_source_pk"] = source_row.source_pk
    enriched["_source_daily_prev_close_build_batch_id"] = source_row.build_batch_id
    return enriched


def _derived_limit_price_values(row: dict[str, Any], source_table_name: str, symbol: str | None) -> tuple[dict[str, Any], list[str]]:
    pre_close = _decimal_value(_first_value(row, "preclose", "pre_close", "pre_close_price", "prev_close_price"))
    warnings: list[str] = []
    if pre_close is None:
        pre_close = _decimal_value(row.get("_source_daily_prev_close_price"))
        if pre_close is not None:
            previous_trade_date = row.get("_source_daily_prev_close_trade_date")
            warnings.append(
                "raw pre_close field is missing; derived pre_close_price from "
                f"source.daily_bar_v1.close_price for previous trading day {previous_trade_date}"
            )
    if pre_close is None:
        return {}, ["raw pre_close field is missing; cannot derive limit price"]
    rule, pct = _limit_rule_for_symbol(symbol, row)
    return {
        "pre_close_price": float(pre_close),
        "up_limit_price": _round_price(pre_close * (Decimal("1") + pct)),
        "down_limit_price": _round_price(pre_close * (Decimal("1") - pct)),
        "limit_rule": rule,
    }, warnings


def _derived_limit_event_values(row: dict[str, Any], source_table_name: str, symbol: str | None) -> tuple[dict[str, Any], list[str]]:
    limit_values, warnings = _derived_limit_price_values(row, source_table_name, symbol)
    up_limit = _decimal_value(limit_values.get("up_limit_price"))
    open_v = _decimal_value(_first_value(row, "open", "open_price"))
    high_v = _decimal_value(_first_value(row, "high", "high_price"))
    low_v = _decimal_value(_first_value(row, "low", "low_price"))
    close_v = _decimal_value(_first_value(row, "close", "close_price"))
    if None in {up_limit, open_v, high_v, low_v, close_v}:
        return {}, warnings + ["OHLC or up_limit missing; cannot derive limit event"]
    assert up_limit is not None and open_v is not None and high_v is not None and low_v is not None and close_v is not None
    closed_on_limit = close_v >= up_limit
    touched_limit = high_v >= up_limit
    is_one_word = open_v >= up_limit and high_v >= up_limit and low_v >= up_limit and close_v >= up_limit
    is_break_limit = touched_limit and low_v < up_limit
    if not touched_limit:
        event_type = "none"
    elif closed_on_limit and is_break_limit:
        event_type = "t_board_limit_up"
    elif closed_on_limit:
        event_type = "limit_up"
    else:
        event_type = "limit_up_broken"
    return {
        "limit_event_type": event_type,
        "is_one_word_board": is_one_word,
        "is_break_limit": is_break_limit,
        "close_on_limit_flag": closed_on_limit,
        "limit_open_count": 1 if is_break_limit else 0,
    }, warnings


def _ths_limit_event_values(row: dict[str, Any], canonical_fields: list[str]) -> tuple[dict[str, Any], list[str]]:
    fields = [
        "limit_event_type",
        "is_one_word_board",
        "is_break_limit",
        "close_on_limit_flag",
        "limit_open_count",
    ]
    derived = {
        "limit_event_type": _first_value(row, "limit_event_type") or "limit_up",
        "is_one_word_board": _bool_value(_first_value(row, "is_one_word_board")),
        "is_break_limit": _bool_value(_first_value(row, "is_break_limit")),
        "close_on_limit_flag": _bool_value(_first_value(row, "close_on_limit_flag")),
        "limit_open_count": _decimal_str(_first_value(row, "limit_open_count", "open_num")),
    }
    if derived["is_one_word_board"] is None:
        open_count = _decimal_str(_first_value(row, "limit_open_count", "open_num"))
        derived["is_one_word_board"] = None if open_count is None else open_count == 0
    if derived["is_break_limit"] is None:
        open_count = _decimal_str(_first_value(row, "limit_open_count", "open_num"))
        derived["is_break_limit"] = None if open_count is None else open_count > 0
    if derived["close_on_limit_flag"] is None:
        derived["close_on_limit_flag"] = True
    values: dict[str, Any] = {}
    warnings: list[str] = []
    requested = canonical_fields or fields
    for field in requested:
        if field not in fields:
            continue
        value = derived.get(field)
        if value is None:
            warnings.append(f"raw THS limit_up_pool field for {field} is missing or unparseable")
            continue
        values[field] = value
    return values, warnings


def _trade_calendar_values(row: dict[str, Any], canonical_fields: list[str]) -> tuple[dict[str, Any], list[str]]:
    calendar_date = _date_text(_first_value(row, "calendar_date", "cal_date", "date", "trade_date"))
    derived = {
        "calendar_date": calendar_date,
        "is_trading_day": _bool_value(_first_value(row, "is_trading_day", "is_open")),
        "exchange": _first_value(row, "exchange") or "SSE_SZSE",
        "pretrade_date": _date_text(_first_value(row, "pretrade_date", "prev_trading_day", "_derived_pretrade_date")),
    }
    requested = set(canonical_fields or ["calendar_date", "is_trading_day", "exchange", "pretrade_date"])
    requested.add("calendar_date")
    requested.add("exchange")
    values: dict[str, Any] = {}
    warnings: list[str] = []
    for field in sorted(requested):
        if field not in derived:
            warnings.append(f"no build mapping for trade calendar canonical field {field}")
            continue
        value = derived[field]
        if value is None and field not in {"pretrade_date"}:
            warnings.append(f"raw trade calendar field for {field} is missing or unparseable")
            continue
        values[field] = value
    return values, warnings


def _stock_exchange_from_symbol(symbol: str | None) -> str | None:
    if not symbol:
        return None
    if symbol.endswith(".SZ"):
        return "SZ"
    if symbol.endswith(".SH"):
        return "SH"
    if symbol.endswith(".BJ"):
        return "BJ"
    return None


def _stock_master_values(row: dict[str, Any], canonical_fields: list[str]) -> tuple[dict[str, Any], list[str]]:
    symbol = _extract_symbol(row, {})
    provider_symbol = _first_value(row, "code", "ts_code", "provider_symbol", "symbol")
    derived = {
        "provider_symbol": provider_symbol,
        "stock_name": _first_value(row, "code_name", "name", "stock_name", "股票简称"),
        "ipo_date": _date_text(_first_value(row, "ipoDate", "list_date", "ipo_date")),
        "delist_date": _date_text(_first_value(row, "outDate", "delist_date")),
        "list_status": None if _first_value(row, "status", "list_status") in (None, "") else str(_first_value(row, "status", "list_status")),
        "security_type": None if _first_value(row, "type", "security_type") in (None, "") else str(_first_value(row, "type", "security_type")),
        "exchange": _first_value(row, "exchange") or _stock_exchange_from_symbol(symbol),
        "market": _first_value(row, "market") or "CN_A",
    }
    requested = set(canonical_fields or derived.keys())
    requested.update({"provider_symbol", "exchange", "market", "security_type"})
    values: dict[str, Any] = {}
    warnings: list[str] = []
    for field in sorted(requested):
        if field not in derived:
            warnings.append(f"no build mapping for stock master canonical field {field}")
            continue
        value = derived[field]
        if value is None and field in {"stock_name", "list_status"}:
            warnings.append(f"raw stock master field for {field} is missing or unparseable")
            continue
        values[field] = value
    return values, warnings


def _source_identity_for_build(
    source_table_name: str,
    symbol: str | None,
    trade_date: str | None,
    row: dict[str, Any],
    raw_id: Any,
    provider: Provider | None = None,
) -> tuple[str, str | None]:
    if source_table_name == "source.trade_calendar_v1":
        calendar_date = _date_text(_first_value(row, "calendar_date", "cal_date", "date", "trade_date") or trade_date)
        source_pk = calendar_date or stable_json_hash({"source_table_name": source_table_name, "raw_id": raw_id})
        return source_pk, calendar_date
    if source_table_name == "source.stock_master_v1":
        stock_symbol = symbol or _extract_symbol(row, {})
        source_pk = stock_symbol or stable_json_hash({"source_table_name": source_table_name, "raw_id": raw_id})
        return source_pk, None
    if source_table_name == "source.limit_event_v1":
        if _first_value(row, "limit_event_type"):
            values = {"limit_event_type": _first_value(row, "limit_event_type")}
        else:
            values, _warnings = _derived_limit_event_values(row, source_table_name, symbol)
        event_type = values.get("limit_event_type")
        source_pk = (
            f"{symbol}|{trade_date}|{event_type}"
            if symbol and trade_date and event_type
            else stable_json_hash({"source_table_name": source_table_name, "raw_id": raw_id})
        )
        return source_pk, trade_date
    if source_table_name == "source.minute_bar_v1":
        bar_time = _first_value(row, "bar_time", "event_time", "datetime")
        source_pk = f"{symbol}|{bar_time}" if symbol and bar_time else stable_json_hash({"source_table_name": source_table_name, "raw_id": raw_id})
        return source_pk, trade_date
    if source_table_name == "source.realtime_quote_v1":
        event_time = _first_value(row, "event_time")
        source_pk = f"{symbol}|{event_time}" if symbol and event_time else stable_json_hash({"source_table_name": source_table_name, "raw_id": raw_id})
        return source_pk, trade_date
    if source_table_name == "source.auction_snapshot_v1":
        snapshot_time = _first_value(row, "snapshot_time", "event_time")
        provider_value = provider.value if provider else _first_value(row, "provider")
        source_pk = (
            f"{symbol}|{snapshot_time}|{provider_value}"
            if symbol and snapshot_time and provider_value
            else stable_json_hash({"source_table_name": source_table_name, "raw_id": raw_id})
        )
        return source_pk, trade_date
    if source_table_name == "source.trade_tick_v1":
        tick_time = _first_value(row, "tick_time")
        sequence = _first_value(row, "provider_sequence")
        source_pk = f"{symbol}|{tick_time}|{sequence}" if symbol and tick_time else stable_json_hash({"source_table_name": source_table_name, "raw_id": raw_id})
        return source_pk, trade_date
    return (
        f"{symbol}|{trade_date}" if symbol and trade_date else stable_json_hash({"source_table_name": source_table_name, "raw_id": raw_id}),
        trade_date,
    )


def _bool_value(value: Any) -> bool | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "t", "yes", "y", "正常", "交易", "可交易"}:
        return True
    if text in {"0", "false", "f", "no", "n", "停牌", "暂停交易", "不可交易"}:
        return False
    return None


def _trade_status_values(row: dict[str, Any], canonical_fields: list[str]) -> tuple[dict[str, Any], list[str]]:
    fields = ["is_tradable", "is_suspended", "is_st", "raw_status"]
    raw_status = _first_value(row, "tradestatus", "tradeStatus", "trade_status")
    is_tradable = _bool_value(raw_status)
    is_st = _bool_value(_first_value(row, "isST", "is_st"))
    derived: dict[str, Any] = {
        "is_tradable": is_tradable,
        "is_suspended": None if is_tradable is None else not is_tradable,
        "is_st": is_st,
        "raw_status": None if raw_status in (None, "") else str(raw_status),
    }
    values: dict[str, Any] = {}
    warnings: list[str] = []
    for field in fields:
        if field not in derived:
            warnings.append(f"no build mapping for trade status canonical field {field}")
            continue
        if derived[field] is None:
            warnings.append(f"raw trade status field for {field} is missing or unparseable")
            continue
        values[field] = derived[field]
    return values, warnings


def _trade_status_from_daily_bar_values(row: dict[str, Any], canonical_fields: list[str]) -> tuple[dict[str, Any], list[str]]:
    fields = ["is_tradable", "is_suspended", "is_st", "raw_status"]
    open_price = _decimal_value(_first_value(row, "open", "open_price"))
    high_price = _decimal_value(_first_value(row, "high", "high_price"))
    low_price = _decimal_value(_first_value(row, "low", "low_price"))
    close_price = _decimal_value(_first_value(row, "close", "close_price"))
    volume = _decimal_value(_first_value(row, "volume", "vol"))
    warnings: list[str] = []
    if None in {open_price, high_price, low_price, close_price}:
        return {}, ["daily bar OHLC missing; cannot derive trade status"]
    if volume is None:
        return {}, ["daily bar volume missing; cannot derive trade status"]
    is_tradable = volume > Decimal("0")
    derived: dict[str, Any] = {
        "is_tradable": is_tradable,
        "is_suspended": not is_tradable,
        "is_st": _bool_value(_first_value(row, "isST", "is_st")),
        "raw_status": "daily_bar_present" if is_tradable else "daily_bar_zero_volume",
    }
    values: dict[str, Any] = {}
    for field in fields:
        if derived[field] is None:
            warnings.append(f"raw trade status field for {field} is missing or unparseable")
            continue
        values[field] = derived[field]
    return values, warnings


def _trade_status_delisting_risk_values(row: dict[str, Any], canonical_fields: list[str]) -> tuple[dict[str, Any], list[str]]:
    fields = list(dict.fromkeys(canonical_fields or ["is_delisting_risk"]))
    delist_date = _date_text(_first_value(row, "outDate", "out_date", "delist_date"))
    status_value = _first_value(row, "status", "list_status")
    status = str(status_value).strip().lower() if status_value not in (None, "") else ""
    if delist_date:
        risk: bool | None = True
    elif status in {"0", "d", "delisted", "??", "????"}:
        risk = True
    elif status in {"1", "l", "listed", "??"}:
        risk = False
    else:
        risk = None

    values: dict[str, Any] = {}
    warnings: list[str] = []
    for field in fields:
        if field != "is_delisting_risk":
            warnings.append(f"no build mapping for trade status stock-basic canonical field {field}")
            continue
        if risk is None:
            warnings.append("raw stock basic status/out_date is missing or unparseable for is_delisting_risk")
            continue
        values[field] = risk
    return values, warnings


def _stock_universe_daily_values(row: dict[str, Any], canonical_fields: list[str]) -> tuple[dict[str, Any], list[str]]:
    symbol = _extract_symbol(row, {})
    if symbol is None:
        return {}, ["stock universe row skipped: missing symbol"]
    if not is_a_share_symbol(symbol):
        return {}, []
    fields = ["stock_name", "trade_status", "is_tradable", "is_st"]
    raw_status = _first_value(row, "tradeStatus", "tradestatus", "trade_status")
    is_tradable = _bool_value(raw_status)
    is_st = _bool_value(_first_value(row, "isST", "is_st"))
    derived: dict[str, Any] = {
        "stock_name": _first_value(row, "code_name", "stock_name", "name"),
        "trade_status": None if raw_status in (None, "") else str(raw_status),
        "is_tradable": is_tradable,
        "is_st": is_st,
    }
    requested = set(canonical_fields or fields)
    requested.add("stock_name")
    values: dict[str, Any] = {}
    warnings: list[str] = []
    for field in sorted(requested):
        if field not in derived:
            warnings.append(f"no build mapping for stock universe canonical field {field}")
            continue
        value = derived[field]
        if value is None:
            if field in {"is_st", "stock_name"}:
                continue
            warnings.append(f"raw stock universe field for {field} is missing or unparseable")
            continue
        values[field] = value
    return values, warnings


def _stock_master_name_for_symbol(symbol: str | None) -> str | None:
    if not symbol:
        return None
    try:
        rows = list_source_rows("source.stock_master_v1", symbol=symbol, limit=10)
    except Exception:
        return None
    for row in rows:
        value = row.values.get("stock_name") if getattr(row, "values", None) else None
        if value not in (None, ""):
            return str(value)
    return None


def _stock_universe_daily_from_daily_bar_values(row: dict[str, Any], canonical_fields: list[str]) -> tuple[dict[str, Any], list[str]]:
    symbol = _extract_symbol(row, {})
    if symbol is None:
        return {}, ["stock universe daily backup row skipped: missing symbol"]
    if not is_a_share_symbol(symbol):
        return {}, []
    fields = ["stock_name", "trade_status", "is_tradable", "is_st"]
    raw_status = _first_value(row, "tradestatus", "tradeStatus", "trade_status")
    is_tradable = _bool_value(raw_status)
    is_st = _bool_value(_first_value(row, "isST", "is_st"))
    derived: dict[str, Any] = {
        "stock_name": _first_value(row, "code_name", "stock_name", "name") or _stock_master_name_for_symbol(symbol),
        "trade_status": None if raw_status in (None, "") else str(raw_status),
        "is_tradable": is_tradable,
        "is_st": is_st,
    }
    requested = set(canonical_fields or fields)
    requested.add("stock_name")
    values: dict[str, Any] = {}
    warnings: list[str] = []
    for field in sorted(requested):
        if field not in derived:
            warnings.append(f"no build mapping for stock universe daily backup canonical field {field}")
            continue
        value = derived[field]
        if value is None:
            if field in {"is_st", "stock_name"}:
                continue
            warnings.append(f"raw daily backup field for stock universe {field} is missing or unparseable")
            continue
        values[field] = value
    return values, warnings


def _prune_in_memory_stock_universe_non_a_share_rows(trade_date: str | date | None) -> int:
    if trade_date in (None, ""):
        return 0
    trade_date_text = str(trade_date)[:10]
    delete_keys = [
        key
        for key, row in _SOURCE_ROWS.items()
        if row.source_table_name == "source.stock_universe_daily_v1"
        and str(row.trade_date)[:10] == trade_date_text
        and not is_a_share_symbol(row.symbol)
    ]
    for key in delete_keys:
        del _SOURCE_ROWS[key]
    return len(delete_keys)


CANONICAL_FIELD_MAP: dict[tuple[Provider, str, str], dict[str, str]] = {
    (Provider.BAOSTOCK, "query_history_k_data_plus_daily_raw", "source.daily_bar_v1"): {
        "open_price": "open",
        "high_price": "high",
        "low_price": "low",
        "close_price": "close",
        "pre_close_price": "preclose",
        "volume": "volume",
        "amount": "amount",
        "pct_chg": "pctChg",
        "turnover_rate": "turn",
    },
    (Provider.BAOSTOCK, "query_history_k_data_plus_daily_qfq", "source.adjusted_daily_bar_v1"): {
        "adjusted_open": "open",
        "adjusted_high": "high",
        "adjusted_low": "low",
        "adjusted_close": "close",
        "volume": "volume",
        "amount": "amount",
    },
    (Provider.AKSHARE, "stock_zh_a_hist_daily_raw", "source.daily_bar_v1"): {
        "open_price": "开盘",
        "high_price": "最高",
        "low_price": "最低",
        "close_price": "收盘",
        "volume": "成交量",
        "amount": "成交额",
        "pct_chg": "涨跌幅",
        "turnover_rate": "换手率",
    },
    (Provider.AKSHARE, "stock_zh_a_hist_daily_qfq", "source.adjusted_daily_bar_v1"): {
        "adjusted_open": "开盘",
        "adjusted_high": "最高",
        "adjusted_low": "最低",
        "adjusted_close": "收盘",
        "volume": "成交量",
        "amount": "成交额",
    },
    (Provider.TENCENT, "daily_bars", "source.daily_bar_v1"): {
        "open_price": "open",
        "high_price": "high",
        "low_price": "low",
        "close_price": "close",
        "volume": "volume",
    },
    (Provider.TENCENT, "daily_bars", "source.adjusted_daily_bar_v1"): {
        "adjusted_open": "open",
        "adjusted_high": "high",
        "adjusted_low": "low",
        "adjusted_close": "close",
        "volume": "volume",
    },
    (Provider.SOHU, "daily_bars", "source.daily_bar_v1"): {
        "open_price": "open",
        "high_price": "high",
        "low_price": "low",
        "close_price": "close",
        "volume": "volume",
        "amount": "amount",
        "pct_chg": "pct_chg",
        "turnover_rate": "turnover_rate",
    },
    (Provider.TENCENT, "daily_bars", "source.index_daily_bar_v1"): {
        "open_price": "open",
        "high_price": "high",
        "low_price": "low",
        "close_price": "close",
        "volume": "volume",
        "amount": "amount",
        "pct_chg": "pct_chg",
    },
    (Provider.EASTMONEY, "stock_universe", "source.stock_master_v1"): {
        "stock_name": "stock_name",
        "ipo_date": "ipo_date",
        "list_status": "list_status",
        "delist_date": "delist_date",
        "exchange": "exchange",
        "board": "board",
    },
    (Provider.BAOSTOCK, "query_history_k_data_plus_daily_raw", "source.index_daily_bar_v1"): {
        "open_price": "open",
        "high_price": "high",
        "low_price": "low",
        "close_price": "close",
        "volume": "volume",
        "amount": "amount",
        "pct_chg": "pctChg",
    },
    (Provider.BAOSTOCK, "query_history_k_data_plus_daily_raw", "source.trade_status_v1"): {
        "raw_status": "tradestatus",
    },
    (Provider.TUSHARE, "daily", "source.daily_bar_v1"): {
        "open_price": "open",
        "high_price": "high",
        "low_price": "low",
        "close_price": "close",
        "pre_close_price": "pre_close",
        "volume": "vol",
        "amount": "amount",
        "pct_chg": "pct_chg",
    },
    (Provider.EASTMONEY, "moneyflow_stock_series", "source.stock_moneyflow_daily_v1"): {
        "main_net_inflow": "main_net_inflow",
        "super_large_net_inflow": "super_large_net_inflow",
        "large_net_inflow": "large_net_inflow",
        "medium_net_inflow": "medium_net_inflow",
        "small_net_inflow": "small_net_inflow",
        "provider_definition": "provider_definition",
    },
    (Provider.EASTMONEY, "quote_snapshot", "source.realtime_quote_v1"): {
        "latest_price": "last_price",
        "open_price": "open_price",
        "high_price": "high_price",
        "low_price": "low_price",
        "prev_close_price": "prev_close_price",
        "volume": "volume",
        "amount": "amount",
        "turnover_rate": "turnover_rate",
        "change_amount": "change_amount",
        "change_pct": "change_pct",
        "float_market_cap": "float_market_cap",
        "total_market_cap": "total_market_cap",
        "event_time": "event_time",
    },
    (Provider.TENCENT, "quote_snapshot", "source.realtime_quote_v1"): {
        "latest_price": "last_price",
        "open_price": "open_price",
        "high_price": "high_price",
        "low_price": "low_price",
        "prev_close_price": "prev_close_price",
        "volume": "volume",
        "amount": "amount",
        "turnover_rate": "turnover_rate",
        "change_amount": "change_amount",
        "change_pct": "change_pct",
        "event_time": "event_time",
    },
    (Provider.EASTMONEY, "auction_snapshot", "source.auction_snapshot_v1"): {
        "virtual_open_price": "price",
        "matched_volume": "volume",
        "matched_amount": "amount",
        "snapshot_time": "event_time",
        "event_time": "event_time",
    },
    (Provider.TENCENT, "auction_snapshot", "source.auction_snapshot_v1"): {
        "virtual_open_price": "price",
        "matched_volume": "volume",
        "matched_amount": "amount",
        "snapshot_time": "event_time",
        "event_time": "event_time",
    },
    (Provider.SINA, "auction_snapshot", "source.auction_snapshot_v1"): {
        "virtual_open_price": "price",
        "matched_volume": "volume",
        "matched_amount": "amount",
        "snapshot_time": "event_time",
        "event_time": "event_time",
    },
    (Provider.EASTMONEY, "minute_bars", "source.minute_bar_v1"): {
        "open_price": "open",
        "high_price": "high",
        "low_price": "low",
        "close_price": "close",
        "volume": "volume",
        "amount": "amount",
        "bar_time": "bar_time",
        "event_time": "event_time",
    },
    (Provider.TENCENT, "minute_bars", "source.minute_bar_v1"): {
        "open_price": "open",
        "high_price": "high",
        "low_price": "low",
        "close_price": "close",
        "volume": "volume",
        "amount": "amount",
        "bar_time": "bar_time",
        "event_time": "event_time",
    },
    (Provider.EASTMONEY, "trade_details", "source.trade_tick_v1"): {
        "tick_time": "tick_time",
        "price": "price",
        "volume": "volume",
        "amount": "amount",
        "trade_count": "trade_count",
        "side_code": "side_code",
        "side_label": "side_label",
        "provider_sequence": "provider_sequence",
    },
    (Provider.TUSHARE, "moneyflow", "source.stock_moneyflow_daily_v1"): {
        "main_net_inflow": "net_mf_amount",
        "provider_definition": "provider_definition",
    },
    (Provider.BAIDU, "finance_news_feed", "source.event_news_v1"): {
        "title": "title",
        "published_at": "published_at",
        "available_at": "available_at",
        "event_type": "event_type",
        "url": "url",
    },
    (Provider.JIN10, "public_flash", "source.event_news_v1"): {
        "title": "title",
        "published_at": "published_at",
        "available_at": "available_at",
        "event_type": "event_type",
        "url": "url",
    },
    (Provider.THS, "zhangting5_reasons", "source.event_news_v1"): {
        "title": "reason_title",
        "published_at": "published_at_text",
        "available_at": "available_at",
        "event_type": "event_type",
        "url": "url",
    },
    (Provider.THS, "paid_limit_up_probability", "source.ths_paid_limit_up_probability_v1"): {
        "paid_limit_up_probability": "paid_limit_up_probability",
        "credential_version": "credential_version",
        "provider_status_code": "status_code",
        "provider_status_msg": "status_msg",
    },
    (Provider.CNINFO, "cninfo_disclosure_direct", "source.event_news_v1"): {
        "title": "title",
        "published_at": "published_at",
        "available_at": "available_at",
        "event_type": "event_type",
        "url": "url",
    },
}


_FULL_ROW_SOURCE_BUILD_TABLES = {
    "source.adjusted_daily_bar_v1",
    "source.auction_snapshot_v1",
    "source.daily_bar_v1",
    "source.index_daily_bar_v1",
    "source.limit_price_v1",
}


def _source_build_fields(source_table_name: str, mapping: dict[str, str], canonical_fields: list[str]) -> list[str]:
    fields = list(dict.fromkeys(canonical_fields or list(mapping.keys())))
    if source_table_name not in _FULL_ROW_SOURCE_BUILD_TABLES or not fields:
        return fields
    for canonical in mapping.keys():
        if canonical not in fields:
            fields.append(canonical)
    return fields


def _auction_snapshot_values(row: dict[str, Any], canonical_fields: list[str]) -> tuple[dict[str, Any], list[str]]:
    field_sources: dict[str, tuple[str, ...]] = {
        "virtual_open_price": ("price", "auction_price"),
        "matched_volume": ("volume", "auction_volume"),
        "matched_amount": ("amount", "auction_amount"),
        "snapshot_time": ("snapshot_time", "event_time"),
        "event_time": ("event_time", "snapshot_time"),
    }
    fields = list(dict.fromkeys(canonical_fields or field_sources.keys()))
    values: dict[str, Any] = {}
    warnings: list[str] = []
    for canonical in fields:
        sources = field_sources.get(canonical)
        if not sources:
            warnings.append(f"no build mapping for source.auction_snapshot_v1.{canonical}")
            continue
        value = _first_value(row, *sources)
        if value is None:
            warnings.append(f"raw auction field for canonical field {canonical} is missing")
            continue
        if canonical in {"snapshot_time", "event_time"}:
            values[canonical] = value
            continue
        numeric = _decimal_str(value)
        if numeric is None:
            warnings.append(f"raw auction field for canonical field {canonical} is not numeric")
            continue
        values[canonical] = numeric
    return values, warnings


def _build_values(provider: Provider, api_name: str, source_table_name: str, row: dict[str, Any], canonical_fields: list[str]) -> tuple[dict[str, Any], list[str]]:
    if source_table_name == "source.trade_calendar_v1" and api_name in {"query_trade_dates", "trade_cal"}:
        return _trade_calendar_values(row, canonical_fields)
    if source_table_name == "source.stock_master_v1" and api_name in {"query_stock_basic", "stock_basic"}:
        return _stock_master_values(row, canonical_fields)
    if provider == Provider.BAOSTOCK and api_name == "query_all_stock" and source_table_name == "source.stock_universe_daily_v1":
        return _stock_universe_daily_values(row, canonical_fields)
    if provider == Provider.BAOSTOCK and api_name == "query_history_k_data_plus_daily_raw" and source_table_name == "source.stock_universe_daily_v1":
        return _stock_universe_daily_from_daily_bar_values(row, canonical_fields)
    if provider == Provider.BAOSTOCK and api_name == "query_history_k_data_plus_daily_raw" and source_table_name == "source.trade_status_v1":
        return _trade_status_values(row, canonical_fields)
    if source_table_name == "source.trade_status_v1" and (
        (provider == Provider.BAOSTOCK and api_name == "query_stock_basic")
        or (provider == Provider.TUSHARE and api_name == "stock_basic")
    ):
        return _trade_status_delisting_risk_values(row, canonical_fields)
    if provider == Provider.TENCENT and api_name == "daily_bars" and source_table_name == "source.trade_status_v1":
        return _trade_status_from_daily_bar_values(row, canonical_fields)
    if provider == Provider.THS and api_name == "limit_up_pool" and source_table_name == "source.limit_event_v1":
        return _ths_limit_event_values(row, canonical_fields)
    if source_table_name == "source.limit_price_v1" and api_name in {"query_history_k_data_plus_daily_raw", "daily_bars"}:
        symbol = _extract_symbol(row, {})
        values, warnings = _derived_limit_price_values(row, source_table_name, symbol)
        return values, warnings
    if source_table_name == "source.limit_event_v1" and api_name in {"query_history_k_data_plus_daily_raw", "daily_bars"}:
        symbol = _extract_symbol(row, {})
        values, warnings = _derived_limit_event_values(row, source_table_name, symbol)
        if canonical_fields:
            values = {key: value for key, value in values.items() if key in set(canonical_fields)}
        return values, warnings
    if source_table_name == "source.auction_snapshot_v1" and api_name == "auction_snapshot":
        return _auction_snapshot_values(row, canonical_fields)
    mapping = CANONICAL_FIELD_MAP.get((provider, api_name, source_table_name), {})
    values: dict[str, Any] = {}
    warnings: list[str] = []
    fields = _source_build_fields(source_table_name, mapping, canonical_fields)
    if source_table_name == "source.event_news_v1":
        fields = sorted(set(fields) | {"title", "published_at", "available_at", "event_type", "url"})
    if source_table_name == "source.minute_bar_v1":
        fields = sorted(
            set(fields)
            | {
                "bar_time",
                "event_time",
                "open_price",
                "high_price",
                "low_price",
                "close_price",
            }
        )
    if source_table_name == "source.trade_tick_v1":
        fields = sorted(set(fields) | {"tick_time", "provider_sequence"})
    for canonical in fields:
        raw_field = mapping.get(canonical)
        if not raw_field:
            warnings.append(f"no build mapping for {provider.value}.{api_name} -> {source_table_name}.{canonical}")
            continue
        if raw_field not in row:
            warnings.append(f"raw field {raw_field!r} missing for canonical field {canonical}")
            continue
        value = row.get(raw_field)
        if _preserve_raw_text_field(canonical):
            values[canonical] = value
        else:
            numeric = _decimal_str(value)
            values[canonical] = numeric if numeric is not None else value
    return values, warnings


def _canonical_fields_for_source_build(job: Any, source_table_name: str) -> list[str]:
    if job is None:
        return []
    if getattr(job, "source_table_name", source_table_name) == source_table_name:
        return list(getattr(job, "canonical_fields", []) or [])
    fields = [item.canonical_field_name for item in list_source_requirements(source_table_name)]
    return fields or list(getattr(job, "canonical_fields", []) or [])


def _with_trade_calendar_pretrade(raw_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def _calendar_sort_key(raw: dict[str, Any]) -> date:
        text = _date_text(_first_value(raw.get("row", {}), "calendar_date", "cal_date", "date", "trade_date") or raw.get("trade_date"))
        if not text:
            return date.max
        try:
            return date.fromisoformat(text)
        except ValueError:
            return date.max

    decorated: list[dict[str, Any]] = []
    previous_trading_day: date | None = None
    for raw in sorted(raw_rows, key=_calendar_sort_key):
        raw_copy = dict(raw)
        row_copy = dict(raw.get("row", {}))
        calendar_day = _calendar_sort_key(raw)
        row_copy["_derived_pretrade_date"] = previous_trading_day.isoformat() if previous_trading_day else None
        raw_copy["row"] = row_copy
        if calendar_day != date.max:
            raw_copy["trade_date"] = calendar_day.isoformat()
            if _bool_value(_first_value(row_copy, "is_trading_day", "is_open")) is True:
                previous_trading_day = calendar_day
        decorated.append(raw_copy)
    return decorated


def execute_source_build_trigger(request: SourceBuildExecuteRequest) -> SourceBuildExecutionResult:
    started = utcnow()
    trigger = durable_build_trigger_if_enabled(request.trigger_id)
    if trigger is None:
        trigger = next((item for item in list_source_build_triggers() if item.trigger_id == request.trigger_id), None)
    if trigger is None:
        raise KeyError(f"unknown source build trigger: {request.trigger_id}")
    if not request.dry_run:
        trigger.status = "running"
        update_build_trigger_status_if_enabled(trigger.trigger_id, "running")
    job = get_fetch_job(trigger.job_item_id) if trigger.job_item_id else None
    source_table_name = trigger.source_table_name
    build_batch_id = f"source_build_{uuid4().hex[:12]}"
    errors: list[str] = []
    warnings: list[str] = []
    source_count = 0
    lineage_count = 0
    quality_issue_count = 0
    raw_rows: list[dict[str, Any]] = []
    if job:
        trigger_symbol = str(trigger.symbol) if trigger.symbol else None
        trigger_trade_date = str(trigger.trade_date) if trigger.trade_date else None
        raw_rows = _candidate_raw_rows(
            job.raw_request_hash or job.request_hash,
            job.provider,
            job.api_name,
            source_table_name,
            trigger_symbol,
            trigger_trade_date,
        )
    if source_table_name == "source.trade_calendar_v1":
        raw_rows = _with_trade_calendar_pretrade(raw_rows)
    if not raw_rows:
        result = SourceBuildExecutionResult(
            trigger_id=request.trigger_id,
            fetch_batch_id=trigger.fetch_batch_id,
            job_item_id=trigger.job_item_id,
            source_table_name=source_table_name,
            build_batch_id=build_batch_id,
            status="dry_run" if request.dry_run else "skipped_no_raw",
            raw_row_count=0,
            source_row_count=0,
            lineage_row_count=0,
            quality_issue_count=0,
            warnings=[
                (
                    "dry_run=true: no raw rows found; trigger status was not changed"
                    if request.dry_run
                    else "no raw rows found for trigger/job request_hash; run raw ingest before source build"
                )
            ],
            started_at=started,
            finished_at=utcnow(),
        )
        if request.dry_run:
            return result
        _BUILD_RESULTS.append(result)
        trigger.status = "failed"
        trigger.finished_at = result.finished_at
        update_build_trigger_status_if_enabled(trigger.trigger_id, "failed", result.finished_at)
        return result
    if request.dry_run:
        result = SourceBuildExecutionResult(
            trigger_id=request.trigger_id,
            fetch_batch_id=trigger.fetch_batch_id,
            job_item_id=trigger.job_item_id,
            source_table_name=source_table_name,
            build_batch_id=build_batch_id,
            status="dry_run",
            raw_row_count=len(raw_rows),
            source_row_count=0,
            lineage_row_count=0,
            quality_issue_count=0,
            warnings=["dry_run=true: raw rows were located but source/lineage writes were not persisted"],
            started_at=started,
            finished_at=utcnow(),
        )
        return result
    for raw in raw_rows:
        provider = raw["provider"]
        api_name = raw["api_name"]
        row = raw["row"]
        symbol = raw.get("symbol") or _extract_symbol(row, raw.get("request_params", {}))
        trade_date = raw.get("trade_date") or _extract_trade_date(row, raw.get("request_params", {}))
        if source_table_name == "source.limit_price_v1":
            row = _with_limit_price_preclose_source(row, symbol, trade_date)
        q = validate_raw_rows(QualityValidationRequest(provider=provider, api_name=api_name, rows=[row]))
        quality_issue_count += q.issue_count
        if request.require_raw_quality_pass and not q.build_allowed:
            errors.extend(issue.message for issue in q.issues)
            continue
        canonical_fields = _canonical_fields_for_source_build(job, source_table_name)
        values, row_warnings = _build_values(provider, api_name, source_table_name, row, canonical_fields)
        warnings.extend(row_warnings)
        if not values:
            continue
        if source_table_name == "source.event_news_v1":
            event_id = row.get("provider_news_id") or row.get("event_id") or row.get("url")
            source_pk = f"{provider.value}:{event_id}" if event_id else stable_json_hash({"source_table_name": source_table_name, "raw_id": raw["raw_id"]})
        else:
            source_pk, trade_date = _source_identity_for_build(source_table_name, symbol, trade_date, row, raw["raw_id"], provider)
        mismatch = _requested_identity_mismatch(
            source_table_name=source_table_name,
            requested_symbol=getattr(trigger, "symbol", None),
            requested_trade_date=getattr(trigger, "trade_date", None),
            built_symbol=symbol,
            built_trade_date=trade_date,
            raw_id=raw["raw_id"],
        )
        if mismatch:
            errors.append(mismatch)
            continue
        existing = _SOURCE_ROWS.get(f"{source_table_name}|{source_pk}")
        merged = dict(existing.values) if existing else {}
        merged.update(values)
        out = SourceCanonicalRowOut(
            source_table_name=source_table_name,
            source_pk=source_pk,
            symbol=symbol,
            trade_date=trade_date,
            values=merged,
            source_quality_status=QualityStatus.USABLE if not q.error_count else QualityStatus.SUSPECT,
            primary_provider=provider,
            primary_api_name=api_name,
            build_batch_id=build_batch_id,
            available_at=raw.get("available_at"),
            captured_at=raw.get("captured_at"),
            updated_at=utcnow(),
        )
        _SOURCE_ROWS[f"{source_table_name}|{source_pk}"] = out
        source_count += 1
        for canonical_field in values.keys():
            lineage = SourceLineageRecordOut(
                lineage_id=f"lineage_{uuid4().hex[:12]}",
                source_table_name=source_table_name,
                source_pk=source_pk,
                canonical_field_name=canonical_field,
                provider=provider,
                api_name=api_name,
                raw_table_name=raw["raw_table_name"],
                raw_id=raw["raw_id"],
                request_hash=raw.get("request_hash"),
                response_row_hash=raw.get("response_row_hash"),
                build_batch_id=build_batch_id,
                confidence_score=1.0 if not q.error_count else 0.7,
                created_at=utcnow(),
            )
            _LINEAGE_ROWS.append(lineage)
            lineage_count += 1
        if repository_backend() == "postgres" and _PG_REPO.ready:
            try:
                row_lineage = [item for item in _LINEAGE_ROWS if item.build_batch_id == build_batch_id and item.source_pk == source_pk]
                _PG_REPO.upsert_source_row(out, row_lineage)
            except Exception as exc:  # pragma: no cover - depends on runtime Postgres
                errors.append(f"postgres source/lineage write failed: {exc}")
    if (
        source_table_name == "source.stock_universe_daily_v1"
        and source_count
        and not errors
        and getattr(trigger, "build_scope", None) == "batch"
        and not request.dry_run
    ):
        prune_date = getattr(trigger, "trade_date", None)
        pruned_count = _prune_in_memory_stock_universe_non_a_share_rows(prune_date)
        if repository_backend() == "postgres" and _PG_REPO.ready:
            try:
                pruned_count += _PG_REPO.prune_stock_universe_non_a_share_rows(prune_date)
            except Exception as exc:  # pragma: no cover - depends on runtime Postgres
                errors.append(f"postgres stock universe non-A prune failed: {exc}")
        if pruned_count:
            warnings.append(f"pruned {pruned_count} non-A-share rows from source.stock_universe_daily_v1 for {prune_date}")
    status = "succeeded" if source_count and not errors else "failed"
    result = SourceBuildExecutionResult(
        trigger_id=request.trigger_id,
        fetch_batch_id=trigger.fetch_batch_id,
        job_item_id=trigger.job_item_id,
        source_table_name=source_table_name,
        build_batch_id=build_batch_id,
        status=status,  # type: ignore[arg-type]
        raw_row_count=len(raw_rows),
        source_row_count=source_count,
        lineage_row_count=lineage_count,
        quality_issue_count=quality_issue_count,
        errors=errors,
        warnings=warnings,
        started_at=started,
        finished_at=utcnow(),
    )
    _BUILD_RESULTS.append(result)
    trigger.status = "succeeded" if result.status == "succeeded" else "failed"
    trigger.finished_at = result.finished_at
    update_build_trigger_status_if_enabled(trigger.trigger_id, trigger.status, result.finished_at)
    if repository_backend() == "postgres" and _PG_REPO.ready:
        try:
            _PG_REPO.insert_build_result(result)
        except Exception as exc:  # pragma: no cover
            result.warnings.append(f"postgres build result audit failed: {exc}")
    return result


def _build_trigger_key(trigger: Any) -> tuple[str, str, str, str, str, str]:
    return (
        trigger.fetch_batch_id or "",
        trigger.job_item_id or "",
        trigger.source_table_name,
        trigger.symbol or "",
        str(trigger.trade_date or ""),
        trigger.build_scope,
    )


def run_source_build_worker_once(request: SourceBuildWorkerRunOnceRequest) -> SourceBuildWorkerRunOnceResult:
    results: list[SourceBuildExecutionResult] = []
    durable_candidates = durable_queued_build_triggers_if_enabled(
        limit=request.max_triggers,
        source_table_names=request.source_table_names or None,
    )
    if durable_candidates is not None:
        candidates = durable_candidates
    else:
        triggers = list_source_build_triggers()
        build_results = list_build_results()
        already_processed = {
            item.trigger_id
            for item in build_results
            if item.status in {"succeeded", "failed", "dry_run", "skipped_no_raw"}
        }
        succeeded_trigger_ids = {item.trigger_id for item in build_results if item.status == "succeeded"}
        succeeded_keys = {
            _build_trigger_key(trigger)
            for trigger in triggers
            if trigger.status == "succeeded" or trigger.trigger_id in succeeded_trigger_ids
        }
        candidates = [
            t
            for t in triggers
            if t.status == "queued" and t.trigger_id not in already_processed and _build_trigger_key(t) not in succeeded_keys
        ]
        if request.source_table_names:
            candidates = [t for t in candidates if t.source_table_name in request.source_table_names]
        candidates = candidates[: request.max_triggers]
    for trigger in candidates:
        results.append(
            execute_source_build_trigger(
                SourceBuildExecuteRequest(trigger_id=trigger.trigger_id, worker_id=request.worker_id, dry_run=request.dry_run)
            )
        )
    return SourceBuildWorkerRunOnceResult(
        worker_id=request.worker_id,
        leased_trigger_count=len(candidates),
        succeeded_count=sum(1 for r in results if r.status == "succeeded"),
        failed_count=sum(1 for r in results if r.status == "failed"),
        skipped_count=sum(1 for r in results if r.status in {"skipped_no_raw", "dry_run"}),
        results=results,
    )

def list_source_rows(
    source_table_name: str | None = None,
    symbol: str | None = None,
    trade_date: str | None = None,
    limit: int | None = 1000,
) -> list[SourceCanonicalRowOut]:
    if repository_backend() == "postgres" and _PG_REPO.ready and source_table_name:
        try:
            pg_rows = _PG_REPO.read_source_rows(source_table_name=source_table_name, symbol=symbol, trade_date=trade_date, limit=limit)
            if pg_rows:
                return pg_rows
        except Exception:  # pragma: no cover - fall back to memory for diagnostics
            pass
    rows = list(_SOURCE_ROWS.values())
    if source_table_name:
        rows = [r for r in rows if r.source_table_name == source_table_name]
    if symbol:
        rows = [r for r in rows if r.symbol == symbol]
    if trade_date:
        rows = [r for r in rows if str(r.trade_date) == trade_date]
    return rows


def list_lineage_records(source_table_name: str | None = None, source_pk: str | None = None, canonical_field_name: str | None = None) -> list[SourceLineageRecordOut]:
    if repository_backend() == "postgres" and _PG_REPO.ready:
        try:
            pg_rows = _PG_REPO.read_lineage_records(source_table_name=source_table_name, source_pk=source_pk, canonical_field_name=canonical_field_name)
            if pg_rows:
                return pg_rows
        except Exception:  # pragma: no cover
            pass
    rows = list(_LINEAGE_ROWS)
    if source_table_name:
        rows = [r for r in rows if r.source_table_name == source_table_name]
    if source_pk:
        rows = [r for r in rows if r.source_pk == source_pk]
    if canonical_field_name:
        rows = [r for r in rows if r.canonical_field_name == canonical_field_name]
    return rows


def list_build_results() -> list[SourceBuildExecutionResult]:
    if repository_backend() == "postgres" and _PG_REPO.ready:
        try:
            return _PG_REPO.read_build_results()
        except Exception:  # pragma: no cover
            pass
    return list(_BUILD_RESULTS)
