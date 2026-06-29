#!/usr/bin/env python3
"""Cross-service production-closure acceptance runner.

This script verifies the current minimal production loop through HTTP only:

source-data-service -> three model owner services -> scheduler-service.

It deliberately separates real source facts from scheduler contract samples.
Scheduler samples are only used to validate request wrapping and service
connectivity; they are never treated as provider evidence or source facts.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from typing import Any, Callable


DEFAULT_TRADE_DATE = "2026-06-12"
DEFAULT_SYMBOL = "000063.SZ"
DEFAULT_TBOARD_SYMBOL = "000759.SZ"

OFFICIAL_RELEASE_GATE_TASKS = (
    "hot.release_gate.preopen",
    "memory.release_gate.close",
    "ambush.phase3.release_gate.close",
)
LIVE_DISPATCH_TASKS = OFFICIAL_RELEASE_GATE_TASKS + (
    "t_relay.day1.scan.close",
    "t_relay.day2.watch.1030",
    "t_relay.day2.trigger.1030",
    "t_relay.day2.post_entry.monitor",
    "t_relay.day3.exit.open",
    "t_relay.day3.exit.tail",
    "t_relay.outcome.build",
)

PREFLIGHT_TARGETS = (
    ("hot_candidates", "preopen_release_gate"),
    ("candidate_memory", "outcome_label"),
    ("ambush_watchlist", "release_gate"),
)
TBOARD_PREFLIGHT_TARGETS = (
    ("t_board_relay", "day1_scan"),
    ("t_board_relay", "day2_trigger"),
)

MINIMUM_PRODUCTION_PROBES = (
    ("baostock", "query_history_k_data_plus_daily_raw"),
    ("baostock", "query_history_k_data_plus_daily_qfq"),
    ("tencent", "daily_bars"),
    ("sohu", "daily_bars"),
    ("eastmoney", "quote_snapshot"),
    ("eastmoney", "minute_bars"),
    ("eastmoney", "trade_details"),
)

QUALITY_MATRIX_TABLES: dict[str, tuple[str, list[str]]] = {
    "daily": (
        "source.daily_bar_v1",
        ["open_price", "high_price", "low_price", "close_price", "volume", "amount", "pct_chg"],
    ),
    "source.daily_bar_v1": (
        "source.daily_bar_v1",
        ["open_price", "high_price", "low_price", "close_price", "volume", "amount", "pct_chg"],
    ),
    "adjusted": (
        "source.adjusted_daily_bar_v1",
        ["adjusted_open", "adjusted_high", "adjusted_low", "adjusted_close", "volume"],
    ),
    "qfq": (
        "source.adjusted_daily_bar_v1",
        ["adjusted_open", "adjusted_high", "adjusted_low", "adjusted_close", "volume"],
    ),
    "source.adjusted_daily_bar_v1": (
        "source.adjusted_daily_bar_v1",
        ["adjusted_open", "adjusted_high", "adjusted_low", "adjusted_close", "volume"],
    ),
    "index": (
        "source.index_daily_bar_v1",
        ["open_price", "high_price", "low_price", "close_price", "pct_chg"],
    ),
    "index_daily": (
        "source.index_daily_bar_v1",
        ["open_price", "high_price", "low_price", "close_price", "pct_chg"],
    ),
    "source.index_daily_bar_v1": (
        "source.index_daily_bar_v1",
        ["open_price", "high_price", "low_price", "close_price", "pct_chg"],
    ),
}

COMPACT_LIST_LIMIT = 3
COMPACT_DICT_LIMIT = 24


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def request_json(
    method: str,
    base_url: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: float = 8.0,
) -> Any:
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - operator-provided local/internal URL
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed: HTTP {exc.code}: {detail}") from exc
    except Exception as exc:
        raise RuntimeError(f"{method} {path} failed: {exc}") from exc


def with_query(path: str, **params: Any) -> str:
    cleaned = {key: value for key, value in params.items() if value is not None}
    return f"{path}?{urllib.parse.urlencode(cleaned)}" if cleaned else path


def add_check(
    report: dict[str, Any],
    name: str,
    ok: bool,
    data: Any,
    *,
    required: bool = True,
) -> None:
    report["checks"].append(
        {
            "name": name,
            "ok": bool(ok),
            "required": bool(required),
            "data": data,
        }
    )


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _compact_value(value: Any, *, depth: int = 0, list_limit: int = COMPACT_LIST_LIMIT) -> Any:
    if _is_scalar(value):
        return value
    if isinstance(value, list):
        return {
            "count": len(value),
            "sample": [_compact_value(item, depth=depth + 1, list_limit=list_limit) for item in value[:list_limit]],
        }
    if isinstance(value, dict):
        if depth >= 2:
            scalar_items = {key: item for key, item in value.items() if _is_scalar(item)}
            return {
                **dict(list(scalar_items.items())[:COMPACT_DICT_LIMIT]),
                "_omitted_nested_keys": sorted(key for key, item in value.items() if not _is_scalar(item)),
            }
        compact: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= COMPACT_DICT_LIMIT:
                compact["_omitted_key_count"] = len(value) - COMPACT_DICT_LIMIT
                break
            compact[key] = _compact_value(item, depth=depth + 1, list_limit=list_limit)
        return compact
    return str(value)


def _compact_probe_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider": row.get("provider"),
        "api_name": row.get("api_name"),
        "priority": row.get("priority"),
        "required_for_online": row.get("required_for_online"),
        "real_probe_required": row.get("real_probe_required"),
        "adapter_status": row.get("adapter_status"),
        "raw_table_name": row.get("raw_table_name"),
        "expected_field_count": len(row.get("expected_fields") or []),
    }


def _compact_check_data(name: str, data: Any) -> Any:
    if not isinstance(data, dict):
        return _compact_value(data)
    if "error" in data:
        return data
    if name == "source.probe_matrix":
        rows = data.get("rows") or []
        required_rows = [_compact_probe_row(row) for row in rows if row.get("real_probe_required")]
        return {
            "api_count": data.get("api_count"),
            "required_probe_count": data.get("required_probe_count"),
            "minimum_required_probe_keys_present": data.get("minimum_required_probe_keys_present"),
            "missing_minimum_required_probe_keys": data.get("missing_minimum_required_probe_keys"),
            "required_rows": required_rows,
        }
    if name.startswith("source.real_probe."):
        return {
            "provider": data.get("provider"),
            "api_name": data.get("api_name"),
            "usable_for_source_table": data.get("usable_for_source_table"),
            "connectivity_pass": data.get("connectivity_pass"),
            "schema_pass": data.get("schema_pass"),
            "row_count": data.get("row_count"),
            "reject_reason": data.get("reject_reason"),
            "attempts": data.get("_acceptance_attempts"),
        }
    if name.startswith("source.latest_probe_evidence."):
        return _compact_value(data)
    if name == "source.adjusted_daily_row":
        rows = data.get("rows") or []
        first = rows[0] if rows else {}
        values = first.get("values") or {}
        return {
            "row_count": data.get("row_count"),
            "source_table_name": first.get("source_table_name"),
            "source_pk": first.get("source_pk"),
            "source_quality_status": first.get("source_quality_status"),
            "available_at": first.get("available_at"),
            "required_fields_present": data.get("required_fields_present"),
            "required_values": {
                key: values.get(key)
                for key in ("adjusted_open", "adjusted_high", "adjusted_low", "adjusted_close", "volume", "amount")
            },
        }
    if name == "source.adjusted_daily_lineage":
        rows = data.get("rows") or []
        return {
            "source_pk": data.get("source_pk"),
            "field_count": data.get("field_count"),
            "required_fields_present": data.get("required_fields_present"),
            "lineage_rows": [
                {
                    "canonical_field_name": row.get("canonical_field_name"),
                    "provider": row.get("provider"),
                    "api_name": row.get("api_name"),
                    "raw_table_name": row.get("raw_table_name"),
                    "raw_id": row.get("raw_id"),
                    "build_rule_code": row.get("build_rule_code"),
                }
                for row in rows[:COMPACT_LIST_LIMIT]
            ],
        }
    if name == "source.quality_matrix":
        entries = data.get("entries") or []
        return {
            "status": data.get("status"),
            "evidence_mode": data.get("evidence_mode"),
            "acceptance_run_id": data.get("acceptance_run_id"),
            "symbol_count": len(data.get("symbols") or []),
            "trade_date_count": len(data.get("trade_dates") or []),
            "source_table_names": data.get("source_table_names"),
            "required_entry_count": data.get("required_entry_count"),
            "table_count": data.get("table_count"),
            "entry_count": data.get("entry_count"),
            "passed_count": data.get("passed_count"),
            "warning_count": data.get("warning_count"),
            "blocked_count": data.get("blocked_count"),
            "required_failed": data.get("required_failed"),
            "entry_samples": [
                {
                    "source_table_name": row.get("source_table_name"),
                    "symbol": row.get("symbol"),
                    "trade_date": row.get("trade_date"),
                    "status": row.get("status"),
                    "usable_provider_count": row.get("usable_provider_count"),
                    "passed_field_count": row.get("passed_field_count"),
                    "blocked_field_count": row.get("blocked_field_count"),
                    "blocking_reasons": row.get("blocking_reasons"),
                }
                for row in entries[:COMPACT_LIST_LIMIT]
            ],
        }
    if name.startswith("source.release_preflight."):
        return {
            "can_release_official_signal": data.get("can_release_official_signal"),
            "coverage_status": data.get("coverage_status"),
            "freshness_status": data.get("freshness_status"),
            "blocking_reasons": data.get("blocking_reasons"),
            "degraded_reasons": data.get("degraded_reasons"),
            "repair_action_count": len(data.get("repair_actions") or []),
        }
    if name.startswith("model.tboard."):
        output = data.get("model_response", data) if isinstance(data, dict) else data
        if isinstance(output, dict):
            structured = output.get("structured_output") or {}
            repository_write = structured.get("repository_write") or {}
            return {
                "ok": data.get("ok") if isinstance(data, dict) else None,
                "model_name": output.get("model_name"),
                "structured_keys": sorted(structured.keys()),
                "contract_gaps": output.get("contract_gaps"),
                "repository_write": repository_write,
                "business_status": data.get("business_status") if isinstance(data, dict) else None,
                "blocking_status": data.get("blocking_status") if isinstance(data, dict) else None,
            }
        return _compact_value(data)
    if name == "tboard.repository_status":
        return {
            "repository_attached": data.get("repository_attached"),
            "table_ready": data.get("table_ready"),
            "table_counts": data.get("table_counts"),
            "warning_codes": data.get("warning_codes"),
            "error": data.get("error"),
        }
    if name.startswith("scheduler.sample."):
        payload = data.get("scheduler_trigger_payload") or {}
        owner_preview = data.get("owner_request_body_preview") or {}
        return {
            "contract_kind": data.get("contract_kind"),
            "task_code": data.get("task_code"),
            "scheduler_payload_keys": sorted(payload.keys()),
            "owner_preview_keys": sorted(owner_preview.keys()),
        }
    if name.startswith("scheduler.live_dispatch."):
        owner_response = data.get("owner_response") or {}
        return {
            "accepted": data.get("accepted"),
            "dry_run": data.get("dry_run"),
            "task_code": data.get("task_code"),
            "owner_status_code": owner_response.get("status_code"),
            "owner_response_keys": sorted((owner_response.get("body") or {}).keys())
            if isinstance(owner_response.get("body"), dict)
            else None,
        }
    return _compact_value(data)


def compact_report(report: dict[str, Any]) -> dict[str, Any]:
    compact = {key: value for key, value in report.items() if key != "checks"}
    compact["evidence_mode"] = "compact"
    compact["checks"] = [
        {
            **item,
            "data": _compact_check_data(item.get("name", ""), item.get("data")),
        }
        for item in report.get("checks", [])
    ]
    return compact


def run_check(
    report: dict[str, Any],
    name: str,
    fn: Callable[[], tuple[bool, Any]],
    *,
    required: bool = True,
) -> Any:
    try:
        ok, data = fn()
        add_check(report, name, ok, data, required=required)
        return data
    except Exception as exc:  # noqa: BLE001 - operator evidence should retain unexpected failures
        add_check(report, name, False, {"error": str(exc)}, required=required)
        return None


def expected_probe_params(provider: str, api_name: str, sample_params: dict[str, Any], trade_date: str) -> dict[str, Any]:
    iso_date = trade_date
    compact_date = trade_date.replace("-", "")
    params: dict[str, Any] = {}
    for key, value in sample_params.items():
        if value == "YYYY-MM-DD":
            params[key] = iso_date
        elif value == "YYYYMMDD":
            params[key] = compact_date
        else:
            params[key] = value
    if provider == "baostock" and api_name == "query_adjust_factor":
        params["code"] = "sz.000001"
        params["start_date"] = "1990-01-01"
        params["end_date"] = iso_date
    if provider == "baostock" and api_name == "query_trade_dates":
        params["start_date"] = "2024-01-01"
        params["end_date"] = iso_date
    if provider == "baostock" and api_name == "query_history_k_data_plus_daily_qfq":
        params.setdefault("code", "sz.000063")
        params.setdefault("start_date", iso_date)
        params.setdefault("end_date", iso_date)
        params.setdefault("frequency", "d")
        params.setdefault("adjustflag", "2")
    if provider == "tencent" and api_name == "daily_bars":
        params.setdefault("provider_code", "sz000063")
        params.setdefault("period", "day")
        params.setdefault("start_date", iso_date)
        params.setdefault("end_date", iso_date)
        params.setdefault("count", 10)
        params.setdefault("adjustment", "qfq")
    if provider == "sohu" and api_name == "daily_bars":
        params.setdefault("provider_code", "cn_000063")
        params.setdefault("start_date", compact_date)
        params.setdefault("end_date", compact_date)
        params.setdefault("period", "d")
    return params


def required_probe_keys(matrix: dict[str, Any]) -> list[tuple[str, str]]:
    keys = {
        (str(row.get("provider")), str(row.get("api_name")))
        for row in matrix.get("rows", [])
        if row.get("real_probe_required")
    }
    return sorted(keys)


def find_probe_matrix_row(matrix: dict[str, Any], provider: str, api_name: str) -> dict[str, Any]:
    for row in matrix.get("rows", []):
        if row.get("provider") == provider and row.get("api_name") == api_name:
            return row
    raise RuntimeError(f"missing probe matrix row for {provider}.{api_name}")


def probe_provider(
    source_base_url: str,
    matrix: dict[str, Any],
    provider: str,
    api_name: str,
    trade_date: str,
    *,
    timeout: float,
    attempts: int,
    retry_sleep: float,
) -> dict[str, Any]:
    row = find_probe_matrix_row(matrix, provider, api_name)
    attempt_rows: list[dict[str, Any]] = []
    last_result: dict[str, Any] | None = None
    for attempt in range(1, max(attempts, 1) + 1):
        try:
            result = request_json(
                "POST",
                source_base_url,
                "/source/probe",
                {
                    "provider": provider,
                    "api_name": api_name,
                    "sample_params": expected_probe_params(provider, api_name, row.get("sample_params", {}), trade_date),
                    "expected_fields": row.get("expected_fields", []),
                    "dry_run": False,
                },
                timeout=max(timeout, 45.0),
            )
            last_result = result
            attempt_rows.append(
                {
                    "attempt": attempt,
                    "usable_for_source_table": bool(result.get("usable_for_source_table")),
                    "connectivity_pass": result.get("connectivity_pass"),
                    "schema_pass": result.get("schema_pass"),
                    "row_count": result.get("row_count"),
                    "reject_reason": result.get("reject_reason"),
                }
            )
            if result.get("usable_for_source_table"):
                result["_acceptance_attempts"] = attempt_rows
                return result
        except Exception as exc:  # noqa: BLE001
            attempt_rows.append({"attempt": attempt, "error": str(exc)})
        if attempt < max(attempts, 1):
            time.sleep(retry_sleep)
    if last_result is None:
        last_result = {
            "provider": provider,
            "api_name": api_name,
            "usable_for_source_table": False,
            "reject_reason": "probe_http_failed",
        }
    last_result["_acceptance_attempts"] = attempt_rows
    return last_result


def validate_model_response(body: Any, expected_model_name: str) -> tuple[bool, dict[str, Any]]:
    if not isinstance(body, dict):
        return False, {"error": "response is not a JSON object", "body": body}
    ok = (
        body.get("model_name") == expected_model_name
        and isinstance(body.get("structured_output"), dict)
        and isinstance(body.get("jarvis_payload"), dict)
        and isinstance(body.get("contract_gaps"), list)
    )
    return ok, {
        "model_name": body.get("model_name"),
        "model_version": body.get("model_version"),
        "structured_keys": sorted((body.get("structured_output") or {}).keys()),
        "contract_gaps": body.get("contract_gaps"),
    }


def owner_endpoint_mapping(args: argparse.Namespace, task_code: str) -> dict[str, str]:
    if task_code.startswith("hot."):
        return {"hot-candidates-service": args.owner_hot_url}
    if task_code.startswith("memory."):
        return {"candidate-memory-service": args.owner_memory_url}
    if task_code.startswith("ambush."):
        return {"ambush-watchlist-service": args.owner_ambush_url}
    if task_code.startswith("t_relay."):
        return {"t-board-relay-service": args.owner_tboard_url}
    raise ValueError(f"unknown scheduler task: {task_code}")


def parse_csv_values(values: list[str] | None, fallback: list[str]) -> list[str]:
    if not values:
        return fallback
    parsed: list[str] = []
    for item in values:
        parsed.extend(part.strip() for part in item.split(",") if part.strip())
    return list(dict.fromkeys(parsed))


def parse_quality_matrix_tables(values: list[str] | None) -> list[tuple[str, list[str]]]:
    requested = values or ["daily", "adjusted"]
    parsed: dict[str, list[str]] = {}
    for value in requested:
        key = value.strip()
        if key not in QUALITY_MATRIX_TABLES:
            allowed = ", ".join(sorted(QUALITY_MATRIX_TABLES))
            raise ValueError(f"unsupported source quality matrix table {key!r}; allowed: {allowed}")
        table_name, fields = QUALITY_MATRIX_TABLES[key]
        parsed.setdefault(table_name, fields)
    return list(parsed.items())


def compact_quality_matrix_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_table_name": result.get("source_table_name"),
        "symbol": result.get("symbol"),
        "trade_date": result.get("trade_date"),
        "status": result.get("status"),
        "provider_count": result.get("provider_count"),
        "usable_provider_count": result.get("usable_provider_count"),
        "field_count": result.get("field_count"),
        "passed_field_count": result.get("passed_field_count"),
        "warning_field_count": result.get("warning_field_count"),
        "blocked_field_count": result.get("blocked_field_count"),
        "blocking_reasons": result.get("blocking_reasons", []),
        "warning_reasons": result.get("warning_reasons", []),
        "provider_evidence": [
            {
                "provider": item.get("provider"),
                "api_name": item.get("api_name"),
                "raw_table_name": item.get("raw_table_name"),
                "row_count": item.get("row_count"),
                "target_row_found": item.get("target_row_found"),
                "raw_quality_status": item.get("raw_quality_status"),
                "build_allowed": item.get("build_allowed"),
                "error": item.get("error"),
                "warning": item.get("warning"),
                "canonical_values": item.get("canonical_values"),
            }
            for item in result.get("provider_evidence", [])
        ],
        "blocked_comparisons": [
            {
                "canonical_field_name": item.get("canonical_field_name"),
                "status": item.get("status"),
                "baseline_provider": item.get("baseline_provider"),
                "compared_provider": item.get("compared_provider"),
                "baseline_value": item.get("baseline_value"),
                "compared_value": item.get("compared_value"),
                "absolute_diff": item.get("absolute_diff"),
                "relative_diff": item.get("relative_diff"),
                "reason": item.get("reason"),
            }
            for item in result.get("comparisons", [])
            if item.get("status") != "passed"
        ],
    }


def _source_rows(args: argparse.Namespace, source_table_name: str, *, symbol: str | None = None) -> list[dict[str, Any]]:
    body = request_json(
        "GET",
        args.source_base_url,
        with_query(
            "/source/rows",
            source_table_name=source_table_name,
            symbol=symbol or args.symbol,
            trade_date=args.trade_date,
        ),
        timeout=args.timeout,
    )
    return body if isinstance(body, list) else []


def _first_source_values(args: argparse.Namespace, source_table_name: str, *, symbol: str | None = None) -> dict[str, Any]:
    rows = _source_rows(args, source_table_name, symbol=symbol)
    if not rows:
        return {}
    values = rows[0].get("values") if isinstance(rows[0], dict) else {}
    return values if isinstance(values, dict) else {}


def _tboard_day1_payload(args: argparse.Namespace) -> dict[str, Any]:
    symbol = args.tboard_symbol
    daily = _first_source_values(args, "source.daily_bar_v1", symbol=symbol)
    limit_price = _first_source_values(args, "source.limit_price_v1", symbol=symbol)
    limit_event = _first_source_values(args, "source.limit_event_v1", symbol=symbol)
    quote = _first_source_values(args, "source.realtime_quote_v1", symbol=symbol)
    row = {
        "symbol": symbol,
        "canonical_symbol": symbol,
        "stock_name": args.tboard_stock_name,
        "trade_date": args.trade_date,
        "open_price": daily.get("open_price"),
        "high_price": daily.get("high_price"),
        "low_price": daily.get("low_price"),
        "close_price": daily.get("close_price"),
        "pre_close_price": limit_price.get("pre_close_price") or daily.get("pre_close_price"),
        "up_limit_price": limit_price.get("up_limit_price"),
        "float_market_cap": quote.get("float_market_cap"),
        "limit_open_count": limit_event.get("limit_open_count"),
        "close_on_limit_flag": limit_event.get("close_on_limit_flag"),
        "is_one_word_board": limit_event.get("is_one_word_board"),
    }
    return {"rows": [row], "trade_date": args.trade_date, "run_id": f"acceptance-tboard-day1-{args.trade_date}"}


def _tboard_day2_payload(args: argparse.Namespace) -> dict[str, Any]:
    symbol = args.tboard_symbol
    minute_rows = _source_rows(args, "source.minute_bar_v1", symbol=symbol)
    limit_price = _first_source_values(args, "source.limit_price_v1", symbol=symbol)
    tick_rows = _source_rows(args, "source.trade_tick_v1", symbol=symbol)
    target_minute = None
    for row in minute_rows:
        values = row.get("values") or {}
        if str(values.get("bar_time") or "").startswith(f"{args.trade_date}T02:30:00"):
            target_minute = values
            break
    if target_minute is None and minute_rows:
        target_minute = minute_rows[0].get("values") or {}
    buy_amount = 0.0
    buy_count = 0
    for row in tick_rows:
        values = row.get("values") or {}
        if values.get("side_code") == "1":
            try:
                buy_amount += float(values.get("amount") or 0)
            except (TypeError, ValueError):
                pass
            buy_count += 1
    return {
        "run_id": f"acceptance-tboard-day2-{args.trade_date}",
        "day1_candidate_id": f"tbr-day1-{symbol}-{args.trade_date}",
        "day1_candidate_status": "rejected",
        "canonical_symbol": symbol,
        "day2_trade_date": args.trade_date,
        "as_of_time": f"{args.trade_date}T02:30:00Z",
        "last_price_at_watch": (target_minute or {}).get("close_price"),
        "last_price_at_trigger": (target_minute or {}).get("close_price"),
        "up_limit_price": limit_price.get("up_limit_price"),
        "aggressive_buy_sweep_amount": str(int(buy_amount)) if buy_amount else None,
        "order_consumption_amount": str(int(buy_amount)) if buy_amount else None,
        "buy_tick_count": buy_count,
        "p0_order_book_complete": True,
        "p0_trade_tick_complete": bool(tick_rows),
        "market_context_status": "neutral",
    }


def _tboard_post_entry_payload(args: argparse.Namespace) -> dict[str, Any]:
    symbol = args.tboard_symbol
    limit_price = _first_source_values(args, "source.limit_price_v1", symbol=symbol)
    daily = _first_source_values(args, "source.daily_bar_v1", symbol=symbol)
    up_limit = limit_price.get("up_limit_price") or daily.get("close_price")
    return {
        "run_id": f"acceptance-tboard-post-entry-{args.trade_date}",
        "entry_trigger_id": f"tbr-entry-{symbol}-{args.trade_date}",
        "canonical_symbol": symbol,
        "day2_trade_date": args.trade_date,
        "entry_time": f"{args.trade_date}T02:30:00Z",
        "entry_price": up_limit,
        "up_limit_price": up_limit,
        "post_entry_board_opened": False,
        "close_on_limit_flag": True,
        "close_price": up_limit,
    }


def _tboard_day3_payload(args: argparse.Namespace, *, tail_exit: bool = False) -> dict[str, Any]:
    symbol = args.tboard_symbol
    limit_price = _first_source_values(args, "source.limit_price_v1", symbol=symbol)
    up_limit = limit_price.get("up_limit_price")
    return {
        "run_id": f"acceptance-tboard-day3-{'tail' if tail_exit else 'open'}-{args.trade_date}",
        "entry_trigger_id": f"tbr-entry-{symbol}-{args.trade_date}",
        "canonical_symbol": symbol,
        "day3_trade_date": args.trade_date,
        "open_price": up_limit,
        "up_limit_price": up_limit,
        "day3_open_limit_up_flag": not tail_exit,
        "day3_tail_limit_up_flag": not tail_exit,
        "tail_price": up_limit if not tail_exit else None,
    }


def _tboard_outcome_payload(args: argparse.Namespace) -> dict[str, Any]:
    symbol = args.tboard_symbol
    monitor = _tboard_post_entry_payload(args)
    day3 = _tboard_day3_payload(args)
    return {
        "run_id": f"acceptance-tboard-outcome-{args.trade_date}",
        "entry_trigger_id": f"tbr-entry-{symbol}-{args.trade_date}",
        "day1_candidate_id": f"tbr-day1-{symbol}-{args.trade_date}",
        "canonical_symbol": symbol,
        "day1_trade_date": args.trade_date,
        "day2_trade_date": args.trade_date,
        "day3_trade_date": args.trade_date,
        "post_entry_monitor": {
            **monitor,
            "post_entry_status": "SEALED_TO_CLOSE",
            "source_gap_codes": [],
        },
        "day3_decision": {
            **day3,
            "day3_action": "hold_open_limit",
            "tail_limit_up_flag": day3.get("day3_tail_limit_up_flag"),
            "source_gap_codes": [],
        },
    }


def _check_tboard_day1(args: argparse.Namespace) -> tuple[bool, Any]:
    payload = _tboard_day1_payload(args)
    body = request_json("POST", args.tboard_base_url, "/t-board-relay/day1/scan", payload, timeout=args.timeout)
    ok, preview = validate_model_response(body, "t_board_relay")
    scan = (body.get("structured_output") or {}).get("day1_scan") if isinstance(body, dict) else {}
    repository_write = (body.get("structured_output") or {}).get("repository_write") if isinstance(body, dict) else {}
    ok = ok and isinstance(scan, dict) and int(scan.get("candidate_count") or 0) >= 1 and (repository_write or {}).get("persisted") is True
    return ok, {
        **preview,
        "ok": ok,
        "business_status": (scan.get("candidates") or [{}])[0].get("candidate_status") if isinstance(scan, dict) else None,
        "blocking_status": "not_blocked" if isinstance(scan, dict) and int(scan.get("data_blocked_count") or 0) == 0 else "blocked",
        "model_response": body,
    }


def _check_tboard_day2_watch(args: argparse.Namespace) -> tuple[bool, Any]:
    payload = _tboard_day2_payload(args)
    body = request_json("POST", args.tboard_base_url, "/t-board-relay/day2/watch", {"payload": payload}, timeout=args.timeout)
    ok, preview = validate_model_response(body, "t_board_relay")
    watch = (body.get("structured_output") or {}).get("day2_watch_snapshot") if isinstance(body, dict) else {}
    repository_write = (body.get("structured_output") or {}).get("repository_write") if isinstance(body, dict) else {}
    ok = ok and isinstance(watch, dict) and watch.get("watch_status") != "data_blocked" and (repository_write or {}).get("persisted") is True
    return ok, {
        **preview,
        "ok": ok,
        "business_status": watch.get("watch_status") if isinstance(watch, dict) else None,
        "blocking_status": "not_blocked" if isinstance(watch, dict) and watch.get("watch_status") != "data_blocked" else "blocked",
        "model_response": body,
    }


def _check_tboard_day2_trigger(args: argparse.Namespace) -> tuple[bool, Any]:
    payload = _tboard_day2_payload(args)
    body = request_json("POST", args.tboard_base_url, "/t-board-relay/day2/trigger-check", {"payload": payload}, timeout=args.timeout)
    ok, preview = validate_model_response(body, "t_board_relay")
    trigger = (body.get("structured_output") or {}).get("day2_entry_trigger") if isinstance(body, dict) else {}
    repository_write = (body.get("structured_output") or {}).get("repository_write") if isinstance(body, dict) else {}
    ok = ok and isinstance(trigger, dict) and trigger.get("entry_trigger_status") != "data_blocked" and (repository_write or {}).get("persisted") is True
    return ok, {
        **preview,
        "ok": ok,
        "business_status": trigger.get("entry_trigger_status") if isinstance(trigger, dict) else None,
        "blocking_status": "not_blocked" if isinstance(trigger, dict) and trigger.get("entry_trigger_status") != "data_blocked" else "blocked",
        "model_response": body,
    }


def _check_tboard_post_entry(args: argparse.Namespace) -> tuple[bool, Any]:
    payload = _tboard_post_entry_payload(args)
    body = request_json("POST", args.tboard_base_url, "/t-board-relay/post-entry/monitor", {"payload": payload}, timeout=args.timeout)
    ok, preview = validate_model_response(body, "t_board_relay")
    monitor = (body.get("structured_output") or {}).get("post_entry_monitor") if isinstance(body, dict) else {}
    repository_write = (body.get("structured_output") or {}).get("repository_write") if isinstance(body, dict) else {}
    ok = ok and isinstance(monitor, dict) and monitor.get("post_entry_status") != "DATA_INSUFFICIENT" and (repository_write or {}).get("persisted") is True
    return ok, {
        **preview,
        "ok": ok,
        "business_status": monitor.get("post_entry_status") if isinstance(monitor, dict) else None,
        "blocking_status": "not_blocked" if isinstance(monitor, dict) and monitor.get("post_entry_status") != "DATA_INSUFFICIENT" else "blocked",
        "model_response": body,
    }


def _check_tboard_day3_exit(args: argparse.Namespace) -> tuple[bool, Any]:
    payload = _tboard_day3_payload(args)
    body = request_json("POST", args.tboard_base_url, "/t-board-relay/day3/exit-check", {"payload": payload}, timeout=args.timeout)
    ok, preview = validate_model_response(body, "t_board_relay")
    decision = (body.get("structured_output") or {}).get("day3_exit_decision") if isinstance(body, dict) else {}
    repository_write = (body.get("structured_output") or {}).get("repository_write") if isinstance(body, dict) else {}
    ok = ok and isinstance(decision, dict) and decision.get("day3_action") != "data_blocked" and (repository_write or {}).get("persisted") is True
    return ok, {
        **preview,
        "ok": ok,
        "business_status": decision.get("day3_action") if isinstance(decision, dict) else None,
        "blocking_status": "not_blocked" if isinstance(decision, dict) and decision.get("day3_action") != "data_blocked" else "blocked",
        "model_response": body,
    }


def _check_tboard_outcome(args: argparse.Namespace) -> tuple[bool, Any]:
    payload = _tboard_outcome_payload(args)
    body = request_json("POST", args.tboard_base_url, "/t-board-relay/outcomes/build", {"payload": payload}, timeout=args.timeout)
    ok, preview = validate_model_response(body, "t_board_relay")
    outcome = (body.get("structured_output") or {}).get("outcome_label") if isinstance(body, dict) else {}
    repository_write = (body.get("structured_output") or {}).get("repository_write") if isinstance(body, dict) else {}
    ok = ok and isinstance(outcome, dict) and outcome.get("outcome_label") != "data_blocked" and (repository_write or {}).get("persisted") is True
    return ok, {
        **preview,
        "ok": ok,
        "business_status": outcome.get("outcome_label") if isinstance(outcome, dict) else None,
        "blocking_status": "not_blocked" if isinstance(outcome, dict) and outcome.get("outcome_label") != "data_blocked" else "blocked",
        "model_response": body,
    }


def _check_tboard_repository(args: argparse.Namespace) -> tuple[bool, Any]:
    body = request_json("GET", args.tboard_base_url, "/t-board-relay/repository/status", timeout=args.timeout)
    counts = body.get("table_counts") if isinstance(body, dict) else {}
    ok = (
        isinstance(body, dict)
        and body.get("repository_attached") is True
        and int((counts or {}).get("day1_candidates") or 0) > 0
        and int((counts or {}).get("day2_watch_snapshots") or 0) > 0
        and int((counts or {}).get("day2_triggers") or 0) > 0
        and int((counts or {}).get("post_entry_monitors") or 0) > 0
        and int((counts or {}).get("day3_decisions") or 0) > 0
        and int((counts or {}).get("outcomes") or 0) > 0
        and int((counts or {}).get("game_hypotheses") or 0) > 0
    )
    return ok, body


def main() -> int:
    parser = argparse.ArgumentParser(description="Run source/model/scheduler cross-service acceptance checks")
    parser.add_argument("--source-base-url", default="http://127.0.0.1:8041")
    parser.add_argument("--scheduler-base-url", default="http://127.0.0.1:8023")
    parser.add_argument("--hot-base-url", default="http://127.0.0.1:8031")
    parser.add_argument("--memory-base-url", default="http://127.0.0.1:8032")
    parser.add_argument("--ambush-base-url", default="http://127.0.0.1:8033")
    parser.add_argument("--tboard-base-url", default="http://127.0.0.1:8035")
    parser.add_argument("--data-inspector-base-url", default="http://127.0.0.1:8025")
    parser.add_argument("--owner-hot-url", default="http://hot-candidates-service:8031")
    parser.add_argument("--owner-memory-url", default="http://candidate-memory-service:8032")
    parser.add_argument("--owner-ambush-url", default="http://ambush-watchlist-service:8033")
    parser.add_argument("--owner-tboard-url", default="http://t-board-relay-service:8034")
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL)
    parser.add_argument("--tboard-symbol", default=DEFAULT_TBOARD_SYMBOL)
    parser.add_argument("--tboard-stock-name", default="中百集团")
    parser.add_argument("--trade-date", default=DEFAULT_TRADE_DATE)
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--require-postgres", action="store_true", default=False)
    parser.add_argument(
        "--real-provider-probe",
        action="store_true",
        default=False,
        help="Require persisted real provider probe evidence for every probe-matrix row with real_probe_required=true.",
    )
    parser.add_argument(
        "--force-live-provider-probe",
        action="store_true",
        default=False,
        help="With --real-provider-probe, actively call /source/probe for every required provider/API instead of only checking persisted evidence.",
    )
    parser.add_argument("--probe-attempts", type=int, default=2)
    parser.add_argument("--probe-retry-sleep", type=float, default=1.5)
    parser.add_argument("--source-quality-matrix", action="store_true", default=False)
    parser.add_argument("--source-quality-symbol", action="append", default=None)
    parser.add_argument("--source-quality-trade-date", action="append", default=None)
    parser.add_argument("--source-quality-table", action="append", default=None)
    parser.add_argument("--source-quality-timeout", type=float, default=180.0)
    parser.add_argument("--source-quality-allow-warning", action="store_true", default=False)
    parser.add_argument(
        "--source-quality-evidence-limit",
        type=int,
        default=20,
        help="Number of recent source-data acceptance runs to scan for persisted quality_matrix evidence.",
    )
    parser.add_argument(
        "--force-live-source-quality-matrix",
        action="store_true",
        default=False,
        help="With --source-quality-matrix, actively call /source/quality/multi-source/check instead of checking persisted acceptance evidence.",
    )
    parser.add_argument("--skip-live-dispatch", action="store_true", default=False)
    parser.add_argument("--skip-data-inspector", action="store_true", default=False)
    parser.add_argument("--verbose-evidence", action="store_true", default=False)
    args = parser.parse_args()

    report: dict[str, Any] = {
        "contract_kind": "core_services_acceptance_v1",
        "started_at": utcnow(),
        "symbol": args.symbol,
        "tboard_symbol": args.tboard_symbol,
        "trade_date": args.trade_date,
        "notes": [
            "scheduler samples validate request contracts only; they are not source facts",
            "source rows and lineage checks use source-data-service persisted source/lineage APIs",
            "stdout uses compact evidence by default; pass --verbose-evidence for full HTTP response payloads",
        ],
        "checks": [],
    }

    run_check(report, "source.healthz", lambda: _check_status(args.source_base_url, "/healthz", args.timeout, {"ok"}))
    run_check(report, "source.readyz", lambda: _check_status(args.source_base_url, "/readyz", args.timeout, {"ready"}))
    run_check(report, "source.repository_status", lambda: _check_source_repository(args))
    run_check(report, "source.queue_persistence", lambda: _check_queue_persistence(args))
    run_check(report, "source.queues_summary", lambda: _check_queue_summary(args))
    run_check(report, "source.dead_letter_empty", lambda: _check_dead_letter(args))
    run_check(report, "source.production_readiness", lambda: _check_production_readiness(args))
    matrix = run_check(report, "source.probe_matrix", lambda: _check_probe_matrix(args))
    if args.real_provider_probe and args.force_live_provider_probe and isinstance(matrix, dict):
        for provider, api_name in required_probe_keys(matrix):
            run_check(
                report,
                f"source.real_probe.{provider}.{api_name}",
                lambda provider=provider, api_name=api_name: _check_real_probe(args, matrix, provider, api_name),
            )
    elif args.real_provider_probe and isinstance(matrix, dict):
        for provider, api_name in required_probe_keys(matrix):
            run_check(
                report,
                f"source.persisted_real_probe.{provider}.{api_name}",
                lambda provider=provider, api_name=api_name: _check_persisted_real_probe(args, provider, api_name),
            )
    else:
        for provider, api_name in required_probe_keys(matrix) if isinstance(matrix, dict) else MINIMUM_PRODUCTION_PROBES:
            run_check(
                report,
                f"source.latest_probe_evidence.{provider}.{api_name}",
                lambda provider=provider, api_name=api_name: _check_latest_probe(args, provider, api_name),
                required=False,
            )
    run_check(report, "source.adjusted_daily_row", lambda: _check_adjusted_row(args))
    run_check(report, "source.adjusted_daily_lineage", lambda: _check_adjusted_lineage(args))
    if args.source_quality_matrix:
        run_check(report, "source.quality_matrix", lambda: _check_source_quality_matrix(args))
    for model_code, model_phase in PREFLIGHT_TARGETS:
        run_check(
            report,
            f"source.release_preflight.{model_code}.{model_phase}",
            lambda model_code=model_code, model_phase=model_phase: _check_preflight(args, model_code, model_phase),
        )
    for model_code, model_phase in TBOARD_PREFLIGHT_TARGETS:
        run_check(
            report,
            f"source.release_preflight.{model_code}.{model_phase}",
            lambda model_code=model_code, model_phase=model_phase: _check_preflight_for_symbol(
                args,
                model_code,
                model_phase,
                args.tboard_symbol,
            ),
        )

    if not args.skip_data_inspector:
        run_check(report, "data_inspector.readyz", lambda: _check_ready(args.data_inspector_base_url, args.timeout), required=False)

    samples: dict[str, dict[str, Any]] = {}
    run_check(report, "scheduler.readyz", lambda: _check_ready(args.scheduler_base_url, args.timeout))
    run_check(report, "scheduler.runtime_status", lambda: _check_scheduler_runtime(args))
    run_check(report, "scheduler.docs_sync", lambda: _check_scheduler_docs(args))
    run_check(report, "scheduler.live_dispatch_samples", lambda: _check_scheduler_sample_validation(args))
    run_check(report, "scheduler.materialize_three_models", lambda: _check_materialized_day(args))
    for task_code in OFFICIAL_RELEASE_GATE_TASKS:
        sample = run_check(
            report,
            f"scheduler.sample.{task_code}",
            lambda task_code=task_code: _check_scheduler_sample(args, task_code),
        )
        if isinstance(sample, dict) and isinstance(sample.get("scheduler_trigger_payload"), dict):
            samples[task_code] = sample
    for task_code in LIVE_DISPATCH_TASKS:
        if task_code in samples:
            continue
        sample = run_check(
            report,
            f"scheduler.sample.{task_code}",
            lambda task_code=task_code: _check_scheduler_sample(args, task_code),
        )
        if isinstance(sample, dict) and isinstance(sample.get("scheduler_trigger_payload"), dict):
            samples[task_code] = sample

    run_check(report, "model.hot.score_contract", lambda: _check_hot_score(args, samples))
    run_check(report, "model.memory.score_contract", lambda: _check_memory_score(args, samples))
    run_check(report, "model.ambush.phase3_contract", lambda: _check_ambush_phase3(args, samples))
    run_check(report, "model.tboard.day1_real_source_contract", lambda: _check_tboard_day1(args))
    run_check(report, "model.tboard.day2_watch_real_source_contract", lambda: _check_tboard_day2_watch(args))
    run_check(report, "model.tboard.day2_trigger_real_source_contract", lambda: _check_tboard_day2_trigger(args))
    run_check(report, "model.tboard.post_entry_contract", lambda: _check_tboard_post_entry(args))
    run_check(report, "model.tboard.day3_exit_contract", lambda: _check_tboard_day3_exit(args))
    run_check(report, "model.tboard.outcome_contract", lambda: _check_tboard_outcome(args))
    run_check(report, "tboard.repository_status", lambda: _check_tboard_repository(args))
    if not args.skip_live_dispatch:
        for task_code in LIVE_DISPATCH_TASKS:
            run_check(
                report,
                f"scheduler.live_dispatch.{task_code}",
                lambda task_code=task_code: _check_live_dispatch(args, samples, task_code),
            )

    report["finished_at"] = utcnow()
    report["required_failed"] = [
        item["name"]
        for item in report["checks"]
        if item.get("required") and not item.get("ok")
    ]
    report["status"] = "passed" if not report["required_failed"] else "blocked"
    output_report = report if args.verbose_evidence else compact_report(report)
    if args.verbose_evidence:
        output_report["evidence_mode"] = "verbose"
    print(json.dumps(output_report, ensure_ascii=False, indent=2, default=str))
    return 0 if report["status"] == "passed" else 1


def _check_ready(base_url: str, timeout: float) -> tuple[bool, Any]:
    body = request_json("GET", base_url, "/readyz", timeout=timeout)
    return body.get("status") in {"ready", "ok"}, body


def _check_status(base_url: str, path: str, timeout: float, expected: set[str]) -> tuple[bool, Any]:
    body = request_json("GET", base_url, path, timeout=timeout)
    return body.get("status") in expected, body


def _check_source_repository(args: argparse.Namespace) -> tuple[bool, Any]:
    body = request_json("GET", args.source_base_url, "/source/repository/status", timeout=args.timeout)
    ok = body.get("ready_for_production_raw_store") is True
    if args.require_postgres:
        ok = ok and body.get("backend") == "postgres"
    return ok, body


def _check_queue_persistence(args: argparse.Namespace) -> tuple[bool, Any]:
    body = request_json("GET", args.source_base_url, "/source/fetch/persistence/status", timeout=args.timeout)
    ok = body.get("ready_for_production_queue") is True
    if args.require_postgres:
        ok = ok and body.get("backend") == "postgres" and body.get("durable") is True
    return ok, body


def _check_queue_summary(args: argparse.Namespace) -> tuple[bool, Any]:
    body = request_json("GET", args.source_base_url, "/source/fetch/queues/summary", timeout=args.timeout)
    rows = body.get("rows", [])
    queue_names = {row.get("queue_name") for row in rows}
    expected = {"urgent_release_gate_queue", "normal_daily_ingest_queue", "repair_queue", "backfill_queue", "research_queue", "provider_probe_queue"}
    ok = expected.issubset(queue_names) and sum(int(row.get("leased_count", 0)) for row in rows) == 0
    return ok, body


def _check_dead_letter(args: argparse.Namespace) -> tuple[bool, Any]:
    body = request_json("GET", args.source_base_url, "/source/fetch/dead-letter", timeout=args.timeout)
    return isinstance(body, list) and len(body) == 0, body


def _check_production_readiness(args: argparse.Namespace) -> tuple[bool, Any]:
    path = with_query(
        "/source/ops/production-readiness",
        require_postgres=str(args.require_postgres).lower(),
        require_real_provider_probe=str(args.real_provider_probe).lower(),
    )
    body = request_json("GET", args.source_base_url, path, timeout=max(args.timeout, 20.0))
    return body.get("status") == "passed" and body.get("can拍板") is True, body


def _check_probe_matrix(args: argparse.Namespace) -> tuple[bool, Any]:
    body = request_json("GET", args.source_base_url, "/source/probe/matrix", timeout=args.timeout)
    rows = body.get("rows", [])
    required_rows = [row for row in rows if row.get("real_probe_required")]
    required_keys = {(row.get("provider"), row.get("api_name")) for row in required_rows}
    missing_minimum = [
        f"{provider}.{api_name}"
        for provider, api_name in MINIMUM_PRODUCTION_PROBES
        if (provider, api_name) not in required_keys
    ]
    ok = bool(required_rows) and not missing_minimum
    return ok, {
        "api_count": body.get("api_count"),
        "required_probe_count": len(required_rows),
        "minimum_required_probe_keys_present": not missing_minimum,
        "missing_minimum_required_probe_keys": missing_minimum,
        "rows": rows,
    }


def _check_real_probe(args: argparse.Namespace, matrix: dict[str, Any], provider: str, api_name: str) -> tuple[bool, Any]:
    body = probe_provider(
        args.source_base_url,
        matrix,
        provider,
        api_name,
        args.trade_date,
        timeout=args.timeout,
        attempts=args.probe_attempts,
        retry_sleep=args.probe_retry_sleep,
    )
    return bool(body.get("usable_for_source_table")), body


def _check_latest_probe(args: argparse.Namespace, provider: str, api_name: str) -> tuple[bool, Any]:
    path = with_query("/source/probe/results", provider=provider, api_name=api_name, limit=5)
    body = request_json("GET", args.source_base_url, path, timeout=args.timeout)
    ok = isinstance(body, list) and any(row.get("usable_for_source_table") for row in body)
    return ok, body


def _check_persisted_real_probe(args: argparse.Namespace, provider: str, api_name: str) -> tuple[bool, Any]:
    path = with_query("/source/probe/results", provider=provider, api_name=api_name, limit=1)
    body = request_json("GET", args.source_base_url, path, timeout=args.timeout)
    rows = body if isinstance(body, list) else []
    latest = rows[0] if rows else {}
    ok = (
        bool(latest)
        and latest.get("connectivity_pass") is True
        and latest.get("schema_pass") is True
        and int(latest.get("row_count") or 0) > 0
        and latest.get("usable_for_source_table") is True
        and latest.get("usable_for_model_online") is True
    )
    return ok, latest or {"provider": provider, "api_name": api_name, "error": "no persisted real probe evidence"}


def _check_adjusted_row(args: argparse.Namespace) -> tuple[bool, Any]:
    path = with_query(
        "/source/rows",
        source_table_name="source.adjusted_daily_bar_v1",
        symbol=args.symbol,
        trade_date=args.trade_date,
    )
    body = request_json("GET", args.source_base_url, path, timeout=args.timeout)
    required = {"adjusted_open", "adjusted_high", "adjusted_low", "adjusted_close", "volume", "amount"}
    rows = body if isinstance(body, list) else []
    values = rows[0].get("values", {}) if rows else {}
    ok = bool(rows) and required.issubset(values.keys()) and rows[0].get("source_quality_status") == "usable"
    return ok, {"row_count": len(rows), "required_fields_present": sorted(required.intersection(values.keys())), "rows": rows}


def _check_adjusted_lineage(args: argparse.Namespace) -> tuple[bool, Any]:
    source_pk = f"{args.symbol}|{args.trade_date}"
    path = with_query(
        "/source/lineage/records",
        source_table_name="source.adjusted_daily_bar_v1",
        source_pk=source_pk,
    )
    body = request_json("GET", args.source_base_url, path, timeout=args.timeout)
    rows = body if isinstance(body, list) else []
    fields = {row.get("canonical_field_name") for row in rows}
    required = {"adjusted_open", "adjusted_high", "adjusted_low", "adjusted_close"}
    ok = required.issubset(fields) and all(row.get("raw_table_name") and row.get("provider") for row in rows)
    return ok, {"source_pk": source_pk, "field_count": len(fields), "required_fields_present": sorted(required.intersection(fields)), "rows": rows}


def _check_source_quality_matrix(args: argparse.Namespace) -> tuple[bool, Any]:
    symbols = parse_csv_values(args.source_quality_symbol, [args.symbol])
    trade_dates = parse_csv_values(args.source_quality_trade_date, [args.trade_date])
    table_specs = parse_quality_matrix_tables(args.source_quality_table)
    if not args.force_live_source_quality_matrix:
        return _check_persisted_source_quality_matrix(args, symbols, trade_dates, table_specs)
    return _check_live_source_quality_matrix(args, symbols, trade_dates, table_specs)


def _quality_matrix_table_names(table_specs: list[tuple[str, list[str]]]) -> list[str]:
    return [source_table_name for source_table_name, _ in table_specs]


def _quality_matrix_required_entry_count(
    symbols: list[str],
    trade_dates: list[str],
    table_specs: list[tuple[str, list[str]]],
) -> int:
    return len(symbols) * len(trade_dates) * len(table_specs)


def _quality_matrix_expected_keys(
    symbols: list[str],
    trade_dates: list[str],
    table_specs: list[tuple[str, list[str]]],
) -> set[tuple[str, str, str]]:
    return {
        (source_table_name, symbol, trade_date_text)
        for source_table_name, _ in table_specs
        for symbol in symbols
        for trade_date_text in trade_dates
    }


def _quality_matrix_matches_request(
    evidence: dict[str, Any],
    symbols: list[str],
    trade_dates: list[str],
    table_specs: list[tuple[str, list[str]]],
    *,
    allow_warning: bool,
) -> bool:
    entries = evidence.get("entries") or []
    entry_by_key = {
        (
            str(item.get("source_table_name")),
            str(item.get("symbol")),
            str(item.get("trade_date")),
        ): item
        for item in entries
        if isinstance(item, dict)
    }
    for key in _quality_matrix_expected_keys(symbols, trade_dates, table_specs):
        item = entry_by_key.get(key)
        if not item:
            return False
        if item.get("status") == "blocked":
            return False
        if item.get("status") == "warning" and not allow_warning:
            return False
        if item.get("status") not in {"passed", "warning"}:
            return False
    return True


def _find_quality_matrix_check(run: dict[str, Any]) -> dict[str, Any] | None:
    for check in run.get("checks") or []:
        if check.get("check_code") == "quality_matrix":
            evidence = check.get("evidence")
            return evidence if isinstance(evidence, dict) else {}
    return None


def _check_persisted_source_quality_matrix(
    args: argparse.Namespace,
    symbols: list[str],
    trade_dates: list[str],
    table_specs: list[tuple[str, list[str]]],
) -> tuple[bool, Any]:
    limit = max(int(args.source_quality_evidence_limit or 1), 1)
    runs = request_json("GET", args.source_base_url, with_query("/source/ops/acceptance-runs", limit=limit), timeout=args.timeout)
    if not isinstance(runs, list):
        return False, {
            "contract_kind": "core_services_source_quality_matrix_v1",
            "status": "blocked",
            "evidence_mode": "persisted_acceptance",
            "error": "acceptance run list is not a JSON array",
            "symbols": symbols,
            "trade_dates": trade_dates,
            "source_table_names": _quality_matrix_table_names(table_specs),
        }

    inspected_runs: list[dict[str, Any]] = []
    for run in runs:
        acceptance_run_id = run.get("acceptance_run_id") if isinstance(run, dict) else None
        if not acceptance_run_id:
            continue
        detail = request_json(
            "GET",
            args.source_base_url,
            f"/source/ops/acceptance-runs/{urllib.parse.quote(str(acceptance_run_id), safe='')}",
            timeout=max(args.timeout, 20.0),
        )
        evidence = _find_quality_matrix_check(detail if isinstance(detail, dict) else {})
        inspected_runs.append(
            {
                "acceptance_run_id": acceptance_run_id,
                "run_status": (detail or {}).get("status") if isinstance(detail, dict) else None,
                "quality_matrix_status": (evidence or {}).get("status") if isinstance(evidence, dict) else None,
                "quality_matrix_entry_count": (evidence or {}).get("entry_count") if isinstance(evidence, dict) else None,
                "quality_matrix_symbols": (evidence or {}).get("symbols") if isinstance(evidence, dict) else None,
                "quality_matrix_trade_dates": (evidence or {}).get("trade_dates") if isinstance(evidence, dict) else None,
            }
        )
        if not isinstance(evidence, dict):
            continue
        if evidence.get("status") != "passed":
            continue
        if evidence.get("required_failed"):
            continue
        if not args.source_quality_allow_warning and int(evidence.get("warning_count") or 0) > 0:
            continue
        if _quality_matrix_matches_request(
            evidence,
            symbols,
            trade_dates,
            table_specs,
            allow_warning=args.source_quality_allow_warning,
        ):
            result = {
                **evidence,
                "contract_kind": "core_services_source_quality_matrix_v1",
                "evidence_mode": "persisted_acceptance",
                "acceptance_run_id": acceptance_run_id,
                "acceptance_run_status": detail.get("status") if isinstance(detail, dict) else None,
                "source_table_names": _quality_matrix_table_names(table_specs),
                "required_entry_count": _quality_matrix_required_entry_count(symbols, trade_dates, table_specs),
                "inspected_acceptance_runs": inspected_runs,
            }
            return True, result

    return False, {
        "contract_kind": "core_services_source_quality_matrix_v1",
        "status": "blocked",
        "evidence_mode": "persisted_acceptance",
        "symbols": symbols,
        "trade_dates": trade_dates,
        "source_table_names": _quality_matrix_table_names(table_specs),
        "required_entry_count": _quality_matrix_required_entry_count(symbols, trade_dates, table_specs),
        "inspected_acceptance_runs": inspected_runs,
        "error": "no persisted passed quality_matrix evidence covers the requested symbols, trade dates and source tables",
        "operator_action": "run scripts/source_data_acceptance.py --require-postgres --quality-matrix with matching symbols/trade dates/tables, or add --force-live-source-quality-matrix for an active live check",
    }


def _check_live_source_quality_matrix(
    args: argparse.Namespace,
    symbols: list[str],
    trade_dates: list[str],
    table_specs: list[tuple[str, list[str]]],
) -> tuple[bool, Any]:
    entries: list[dict[str, Any]] = []
    for trade_date_text in trade_dates:
        for symbol in symbols:
            for source_table_name, canonical_fields in table_specs:
                body = request_json(
                    "POST",
                    args.source_base_url,
                    "/source/quality/multi-source/check",
                    {
                        "source_table_name": source_table_name,
                        "canonical_fields": canonical_fields,
                        "symbol": symbol,
                        "trade_date": trade_date_text,
                        "include_backup": True,
                        "dry_run": False,
                    },
                    timeout=args.source_quality_timeout,
                )
                entries.append(compact_quality_matrix_result(body))
    required_failed = [
        f"{item.get('source_table_name')}|{item.get('symbol')}|{item.get('trade_date')}|{item.get('status')}"
        for item in entries
        if item.get("status") == "blocked" or (item.get("status") == "warning" and not args.source_quality_allow_warning)
    ]
    result = {
        "contract_kind": "core_services_source_quality_matrix_v1",
        "evidence_mode": "live_http",
        "symbols": symbols,
        "trade_dates": trade_dates,
        "source_table_names": _quality_matrix_table_names(table_specs),
        "table_count": len(table_specs),
        "entry_count": len(entries),
        "passed_count": sum(1 for item in entries if item.get("status") == "passed"),
        "warning_count": sum(1 for item in entries if item.get("status") == "warning"),
        "blocked_count": sum(1 for item in entries if item.get("status") == "blocked"),
        "required_failed": required_failed,
        "status": "passed" if not required_failed else "blocked",
        "entries": entries,
    }
    return not required_failed, result


def _check_preflight(args: argparse.Namespace, model_code: str, model_phase: str) -> tuple[bool, Any]:
    return _check_preflight_for_symbol(args, model_code, model_phase, args.symbol)


def _check_preflight_for_symbol(args: argparse.Namespace, model_code: str, model_phase: str, symbol: str) -> tuple[bool, Any]:
    body = request_json(
        "POST",
        args.source_base_url,
        "/source/release/preflight",
        {
            "model_code": model_code,
            "model_phase": model_phase,
            "trade_date": args.trade_date,
            "symbols": [symbol],
        },
        timeout=args.timeout,
    )
    can_release = body.get("can_release_official_signal")
    ok = (
        can_release is True
        and body.get("coverage_status") in {"passed", "degraded"}
        and body.get("freshness_status") in {"passed", "degraded"}
        and not body.get("blocking_reasons")
    )
    return ok, body


def _check_scheduler_runtime(args: argparse.Namespace) -> tuple[bool, Any]:
    body = request_json("GET", args.scheduler_base_url, "/scheduler/runtime/status", timeout=args.timeout)
    checks = body.get("checks", {})
    ok = body.get("status") in {"ready", "ok"} or checks.get("background_loop", {}).get("running") is True
    return ok, body


def _check_scheduler_docs(args: argparse.Namespace) -> tuple[bool, Any]:
    body = request_json("GET", args.scheduler_base_url, with_query("/scheduler/validate/docs-sync", project_root="/app"), timeout=args.timeout)
    return body.get("valid") is True and not body.get("missing_tokens"), body


def _check_scheduler_sample_validation(args: argparse.Namespace) -> tuple[bool, Any]:
    body = request_json("GET", args.scheduler_base_url, "/scheduler/validate/live-dispatch-samples", timeout=args.timeout)
    task_codes = {row.get("task_code") for row in body.get("rows", [])}
    return body.get("valid") is True and set(LIVE_DISPATCH_TASKS).issubset(task_codes), body


def _check_materialized_day(args: argparse.Namespace) -> tuple[bool, Any]:
    body = request_json(
        "GET",
        args.scheduler_base_url,
        with_query("/scheduler/materialize/three-models", trading_day=args.trade_date, include_research_intraday="true"),
        timeout=args.timeout,
    )
    official = set(body.get("official_publish_instances", []))
    ok = set(OFFICIAL_RELEASE_GATE_TASKS).issubset(official) and int(body.get("instance_count", 0)) >= len(OFFICIAL_RELEASE_GATE_TASKS)
    return ok, body


def _check_scheduler_sample(args: argparse.Namespace, task_code: str) -> tuple[bool, Any]:
    body = request_json("GET", args.scheduler_base_url, f"/scheduler/live-dispatch/sample/{task_code}", timeout=args.timeout)
    ok = (
        body.get("contract_kind") == "scheduler_live_dispatch_sample_v1"
        and body.get("task_code") == task_code
        and isinstance(body.get("scheduler_trigger_payload"), dict)
        and isinstance(body.get("owner_request_body_preview"), dict)
    )
    return ok, body


def _check_hot_score(args: argparse.Namespace, samples: dict[str, dict[str, Any]]) -> tuple[bool, Any]:
    payload = samples.get("hot.release_gate.preopen", {}).get("scheduler_trigger_payload")
    if not isinstance(payload, dict):
        raise RuntimeError("missing hot scheduler sample payload")
    body = request_json(
        "POST",
        args.hot_base_url,
        "/score",
        {"row": payload.get("row", {}), "run_id": payload.get("run_id"), "as_of_time_utc": payload.get("as_of_time_utc")},
        timeout=args.timeout,
    )
    return validate_model_response(body, "hot_candidates")


def _check_memory_score(args: argparse.Namespace, samples: dict[str, dict[str, Any]]) -> tuple[bool, Any]:
    payload = samples.get("memory.release_gate.close", {}).get("scheduler_trigger_payload")
    if not isinstance(payload, dict):
        raise RuntimeError("missing memory scheduler sample payload")
    row = {key: value for key, value in payload.items() if key not in {"run_id", "as_of_time_utc"}}
    body = request_json(
        "POST",
        args.memory_base_url,
        "/score",
        {"row": row, "run_id": payload.get("run_id"), "as_of_time_utc": payload.get("as_of_time_utc")},
        timeout=args.timeout,
    )
    return validate_model_response(body, "candidate_memory")


def _check_ambush_phase3(args: argparse.Namespace, samples: dict[str, dict[str, Any]]) -> tuple[bool, Any]:
    payload = samples.get("ambush.phase3.release_gate.close", {}).get("scheduler_trigger_payload")
    if not isinstance(payload, dict):
        raise RuntimeError("missing ambush scheduler sample payload")
    body = request_json("POST", args.ambush_base_url, "/ambush/phase3/run", payload, timeout=args.timeout)
    return validate_model_response(body, "ambush_watchlist")


def _check_live_dispatch(args: argparse.Namespace, samples: dict[str, dict[str, Any]], task_code: str) -> tuple[bool, Any]:
    payload = samples.get(task_code, {}).get("scheduler_trigger_payload")
    if not isinstance(payload, dict):
        raise RuntimeError(f"missing scheduler sample payload for {task_code}")
    body = request_json(
        "POST",
        args.scheduler_base_url,
        "/scheduler/trigger",
        {
            "task_code": task_code,
            "dry_run": False,
            "payload": payload,
            "owner_endpoints": owner_endpoint_mapping(args, task_code),
        },
        timeout=max(args.timeout, 45.0),
    )
    return body.get("accepted") is True and body.get("dry_run") is False, body


if __name__ == "__main__":
    raise SystemExit(main())
