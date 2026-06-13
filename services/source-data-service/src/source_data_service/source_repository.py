from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from source_data_service.adapters.base import stable_json_hash
from source_data_service.fetch_orchestrator import get_fetch_job, list_source_build_triggers
from source_data_service.fetch_persistence import (
    configured_database_url,
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
from source_data_service.provider_registry import get_api_spec
from source_data_service.source_build import validate_raw_rows
from source_data_service.models import QualityValidationRequest
from source_data_service.settings import settings
from source_data_service.postgres_repository import PostgresRawSourceRepository


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
    if not value:
        return None
    text = str(value)
    if text.startswith("sz."):
        return f"{text[3:]}.SZ"
    if text.startswith("sh."):
        return f"{text[3:]}.SH"
    if text.endswith(".SZ") or text.endswith(".SH"):
        return text
    if len(text) == 6 and text.startswith(("0", "3")):
        return f"{text}.SZ"
    if len(text) == 6 and text.startswith("6"):
        return f"{text}.SH"
    return text


def _extract_symbol(row: dict[str, Any], request_params: dict[str, Any]) -> str | None:
    return _normalize_symbol(
        row.get("code")
        or row.get("代码")
        or row.get("ts_code")
        or request_params.get("code")
        or request_params.get("symbol")
        or request_params.get("ts_code")
    )


def _extract_trade_date(row: dict[str, Any], request_params: dict[str, Any]) -> str | None:
    value = row.get("date") or row.get("日期") or row.get("trade_date") or request_params.get("trade_date") or request_params.get("day")
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
    return candidates


def _decimal_str(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except Exception:
        return None


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
}


def _build_values(provider: Provider, api_name: str, source_table_name: str, row: dict[str, Any], canonical_fields: list[str]) -> tuple[dict[str, Any], list[str]]:
    mapping = CANONICAL_FIELD_MAP.get((provider, api_name, source_table_name), {})
    values: dict[str, Any] = {}
    warnings: list[str] = []
    fields = canonical_fields or list(mapping.keys())
    for canonical in fields:
        raw_field = mapping.get(canonical)
        if not raw_field:
            warnings.append(f"no build mapping for {provider.value}.{api_name} -> {source_table_name}.{canonical}")
            continue
        if raw_field not in row:
            warnings.append(f"raw field {raw_field!r} missing for canonical field {canonical}")
            continue
        value = row.get(raw_field)
        numeric = _decimal_str(value)
        values[canonical] = numeric if numeric is not None else value
    return values, warnings


def execute_source_build_trigger(request: SourceBuildExecuteRequest) -> SourceBuildExecutionResult:
    started = utcnow()
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
        raw_rows = _candidate_raw_rows(
            job.request_hash,
            job.provider,
            job.api_name,
            source_table_name,
            job.symbol,
            str(job.trade_date) if job.trade_date else None,
        )
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
        q = validate_raw_rows(QualityValidationRequest(provider=provider, api_name=api_name, rows=[row]))
        quality_issue_count += q.issue_count
        if request.require_raw_quality_pass and not q.build_allowed:
            errors.extend(issue.message for issue in q.issues)
            continue
        values, row_warnings = _build_values(provider, api_name, source_table_name, row, job.canonical_fields if job else [])
        warnings.extend(row_warnings)
        if not values:
            continue
        symbol = raw.get("symbol") or _extract_symbol(row, raw.get("request_params", {}))
        trade_date = raw.get("trade_date") or _extract_trade_date(row, raw.get("request_params", {}))
        source_pk = f"{symbol}|{trade_date}" if symbol and trade_date else stable_json_hash({"source_table_name": source_table_name, "raw_id": raw["raw_id"]})
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


def _build_trigger_key(trigger: Any) -> tuple[str, str, str, str, str]:
    return (
        trigger.job_item_id or "",
        trigger.source_table_name,
        trigger.symbol or "",
        str(trigger.trade_date or ""),
        trigger.build_scope,
    )


def run_source_build_worker_once(request: SourceBuildWorkerRunOnceRequest) -> SourceBuildWorkerRunOnceResult:
    results: list[SourceBuildExecutionResult] = []
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


def list_source_rows(source_table_name: str | None = None, symbol: str | None = None, trade_date: str | None = None) -> list[SourceCanonicalRowOut]:
    if repository_backend() == "postgres" and _PG_REPO.ready and source_table_name:
        try:
            pg_rows = _PG_REPO.read_source_rows(source_table_name=source_table_name, symbol=symbol, trade_date=trade_date)
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
