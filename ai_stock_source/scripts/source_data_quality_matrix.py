#!/usr/bin/env python3
"""Run repeatable source-data multi-source quality checks through HTTP only.

The script calls source-data-service /source/quality/multi-source/check for a
matrix of source tables, symbols and trade dates. It never imports provider
adapters and never calls BaoStock, AKShare, Tencent, Sohu, Tushare,
EastMoney or CNINFO directly.
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from typing import Any


DEFAULT_SYMBOLS = ("000063.SZ",)

TABLE_FIELD_PRESETS: dict[str, tuple[str, list[str]]] = {
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


def default_trade_date(today: date | None = None) -> str:
    current = today or date.today()
    offset = 1
    if current.weekday() == 5:
        offset = 1
    elif current.weekday() == 6:
        offset = 2
    elif current.weekday() == 0:
        offset = 3
    return (current - timedelta(days=offset)).isoformat()


def request_json(
    method: str,
    base_url: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: float = 120.0,
) -> Any:
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - operator-provided internal URL
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed: HTTP {exc.code}: {detail}") from exc
    except Exception as exc:
        raise RuntimeError(f"{method} {path} failed: {exc}") from exc


def parse_csv_values(values: list[str] | None, default: tuple[str, ...]) -> list[str]:
    if not values:
        return list(default)
    parsed: list[str] = []
    for item in values:
        parsed.extend(part.strip() for part in item.split(",") if part.strip())
    return list(dict.fromkeys(parsed))


def parse_table_specs(values: list[str] | None) -> list[tuple[str, list[str]]]:
    requested = values or ["daily", "adjusted"]
    specs: list[tuple[str, list[str]]] = []
    for item in requested:
        key = item.strip()
        if key not in TABLE_FIELD_PRESETS:
            allowed = ", ".join(sorted(TABLE_FIELD_PRESETS))
            raise ValueError(f"unsupported --table {key!r}; allowed: {allowed}")
        specs.append(TABLE_FIELD_PRESETS[key])
    deduped: dict[str, list[str]] = {}
    for table_name, fields in specs:
        deduped.setdefault(table_name, fields)
    return list(deduped.items())


def compact_provider_evidence(result: dict[str, Any]) -> list[dict[str, Any]]:
    evidence = []
    for item in result.get("provider_evidence", []):
        evidence.append(
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
        )
    return evidence


def compact_comparisons(result: dict[str, Any], *, include_passed: bool) -> list[dict[str, Any]]:
    comparisons = []
    for item in result.get("comparisons", []):
        if not include_passed and item.get("status") == "passed":
            continue
        comparisons.append(
            {
                "canonical_field_name": item.get("canonical_field_name"),
                "status": item.get("status"),
                "baseline_provider": item.get("baseline_provider"),
                "compared_provider": item.get("compared_provider"),
                "baseline_value": item.get("baseline_value"),
                "compared_value": item.get("compared_value"),
                "absolute_diff": item.get("absolute_diff"),
                "relative_diff": item.get("relative_diff"),
                "absolute_tolerance": item.get("absolute_tolerance"),
                "relative_tolerance": item.get("relative_tolerance"),
                "reason": item.get("reason"),
            }
        )
    return comparisons


def compact_result(result: dict[str, Any], *, include_passed: bool) -> dict[str, Any]:
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
        "provider_evidence": compact_provider_evidence(result),
        "comparisons": compact_comparisons(result, include_passed=include_passed),
    }


def run_matrix(args: argparse.Namespace) -> dict[str, Any]:
    symbols = parse_csv_values(args.symbol, DEFAULT_SYMBOLS)
    trade_dates = parse_csv_values(args.trade_date, (default_trade_date(),))
    table_specs = parse_table_specs(args.table)
    entries: list[dict[str, Any]] = []

    if args.require_ready:
        health = request_json("GET", args.base_url, "/healthz", timeout=args.timeout)
        ready = request_json("GET", args.base_url, "/readyz", timeout=args.timeout)
        if health.get("status") not in {"ok", "ready"} or ready.get("status") not in {"ready", "ok"}:
            raise RuntimeError(f"source-data-service is not ready: health={health}, ready={ready}")

    for trade_date_text in trade_dates:
        for symbol in symbols:
            for table_name, fields in table_specs:
                payload = {
                    "source_table_name": table_name,
                    "canonical_fields": fields,
                    "symbol": symbol,
                    "trade_date": trade_date_text,
                    "include_backup": args.include_backup,
                    "dry_run": args.dry_run,
                }
                result = request_json(
                    "POST",
                    args.base_url,
                    "/source/quality/multi-source/check",
                    payload,
                    timeout=args.timeout,
                )
                entries.append(compact_result(result, include_passed=args.verbose_evidence))

    passed = sum(1 for item in entries if item.get("status") == "passed")
    warning = sum(1 for item in entries if item.get("status") == "warning")
    blocked = sum(1 for item in entries if item.get("status") == "blocked")
    required_failed = [
        f"{item.get('source_table_name')}|{item.get('symbol')}|{item.get('trade_date')}|{item.get('status')}"
        for item in entries
        if item.get("status") == "blocked" or (item.get("status") == "warning" and not args.allow_warning)
    ]
    return {
        "contract_kind": "source_data_quality_matrix_v1",
        "base_url": args.base_url,
        "symbols": symbols,
        "trade_dates": trade_dates,
        "table_count": len(table_specs),
        "entry_count": len(entries),
        "passed_count": passed,
        "warning_count": warning,
        "blocked_count": blocked,
        "required_failed": required_failed,
        "status": "passed" if not required_failed else "blocked",
        "started_at": args.started_at,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "entries": entries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run source-data multi-source quality matrix checks")
    parser.add_argument("--base-url", default="http://127.0.0.1:8041")
    parser.add_argument("--symbol", action="append", help="Symbol or comma-separated symbols; default: 000063.SZ")
    parser.add_argument("--trade-date", action="append", help="Trade date or comma-separated trade dates; default: latest weekday sample")
    parser.add_argument("--table", action="append", help="daily, adjusted/qfq, or full source table name; default: daily + adjusted")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--dry-run", action="store_true", default=False)
    parser.add_argument("--no-include-backup", dest="include_backup", action="store_false", default=True)
    parser.add_argument("--allow-warning", action="store_true", default=False)
    parser.add_argument("--require-ready", action="store_true", default=True)
    parser.add_argument("--no-require-ready", dest="require_ready", action="store_false")
    parser.add_argument("--verbose-evidence", action="store_true", default=False)
    args = parser.parse_args()
    args.started_at = datetime.now(timezone.utc).isoformat()

    try:
        report = run_matrix(args)
    except Exception as exc:  # noqa: BLE001 - operator evidence should keep unexpected failures
        report = {
            "contract_kind": "source_data_quality_matrix_v1",
            "base_url": args.base_url,
            "status": "blocked",
            "required_failed": ["exception"],
            "error": str(exc),
            "started_at": args.started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0 if report.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
