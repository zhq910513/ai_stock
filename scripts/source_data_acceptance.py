#!/usr/bin/env python3
"""Source-data-service production acceptance runner.

This script is intentionally HTTP-only so it can be run from the host, a CI job,
or a one-off docker exec without importing service internals. It validates the
same chain operators need before locking the data-source service:

health -> readiness -> durable repository -> durable queue -> producer/consumer
-> callback/build trigger visibility -> production readiness gate.

Real provider probes are optional because they depend on server network and API
credentials. When --real-provider-probe is set, the script calls /source/probe
for probe-matrix rows and fails if any required probe is unusable.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from typing import Any


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


def request_json(method: str, base_url: str, path: str, payload: dict[str, Any] | None = None, timeout: float = 8.0) -> Any:
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


def default_probe_trade_date(today: date | None = None) -> str:
    """Use the latest weekday sample instead of a weekend that returns 0 rows."""

    current = today or date.today()
    return previous_weekday(current).isoformat()


def previous_weekday(current: date) -> date:
    offset = 1
    if current.weekday() == 5:  # Saturday
        offset = 1
    elif current.weekday() == 6:  # Sunday
        offset = 2
    elif current.weekday() == 0:  # Monday
        offset = 3
    return current - timedelta(days=offset)


def current_or_previous_weekday(current: date | None = None) -> str:
    today = current or date.today()
    if today.weekday() >= 5:
        return previous_weekday(today).isoformat()
    return today.isoformat()


def settled_daily_probe_trade_date(trade_date: str, today: date | None = None) -> str:
    """Return a settled daily-bar sample date; intraday probes may still use today."""

    current = today or date.today()
    latest_settled = previous_weekday(current)
    try:
        requested = date.fromisoformat(trade_date)
    except ValueError:
        return latest_settled.isoformat()
    if requested >= current:
        return latest_settled.isoformat()
    if requested.weekday() >= 5:
        return previous_weekday(requested).isoformat()
    return requested.isoformat()


def probe_trade_date_for_api(row: dict[str, Any], trade_date: str, today: date | None = None) -> str:
    api_name = str(row.get("api_name") or "")
    if api_name in {"minute_bars", "trade_details", "quote_snapshot"}:
        return current_or_previous_weekday(today)
    return trade_date


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
            raise ValueError(f"unsupported quality matrix table {key!r}; allowed: {allowed}")
        table_name, fields = QUALITY_MATRIX_TABLES[key]
        parsed.setdefault(table_name, fields)
    return list(parsed.items())


def compact_multi_source_quality_result(result: dict[str, Any]) -> dict[str, Any]:
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


def summarize_real_provider_probe(probe_results: list[dict[str, Any]], readiness: dict[str, Any]) -> dict[str, Any]:
    failed = [
        {
            "provider": item.get("provider"),
            "api_name": item.get("api_name"),
            "raw_table_name": item.get("raw_table_name"),
            "row_count": item.get("row_count"),
            "reject_reason": item.get("reject_reason"),
        }
        for item in probe_results
        if not item.get("usable_for_source_table")
    ]
    readiness_probe = next(
        (
            item
            for item in readiness.get("checks", [])
            if item.get("check_code") == "real_provider_probe_evidence"
        ),
        {},
    )
    readiness_passed = readiness.get("status") == "passed"
    immediate_passed = not failed
    return {
        "contract_kind": "source_data_acceptance_real_provider_probe_v1",
        "status": "passed" if immediate_passed or readiness_passed else "blocked",
        "immediate_status": "passed" if immediate_passed else "blocked",
        "immediate_failed": failed,
        "readiness_status": readiness.get("status"),
        "readiness_probe_evidence": readiness_probe.get("evidence", {}),
        "probe_results": probe_results,
    }


def run_quality_matrix(
    *,
    base_url: str,
    symbols: list[str],
    trade_dates: list[str],
    table_specs: list[tuple[str, list[str]]],
    timeout: float,
    allow_warning: bool,
) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for trade_date_text in trade_dates:
        for symbol in symbols:
            for source_table_name, canonical_fields in table_specs:
                result = request_json(
                    "POST",
                    base_url,
                    "/source/quality/multi-source/check",
                    {
                        "source_table_name": source_table_name,
                        "canonical_fields": canonical_fields,
                        "symbol": symbol,
                        "trade_date": trade_date_text,
                        "include_backup": True,
                        "dry_run": False,
                    },
                    timeout=timeout,
                )
                entries.append(compact_multi_source_quality_result(result))
    required_failed = [
        f"{item.get('source_table_name')}|{item.get('symbol')}|{item.get('trade_date')}|{item.get('status')}"
        for item in entries
        if item.get("status") == "blocked" or (item.get("status") == "warning" and not allow_warning)
    ]
    return {
        "contract_kind": "source_data_acceptance_quality_matrix_v1",
        "symbols": symbols,
        "trade_dates": trade_dates,
        "table_count": len(table_specs),
        "entry_count": len(entries),
        "passed_count": sum(1 for item in entries if item.get("status") == "passed"),
        "warning_count": sum(1 for item in entries if item.get("status") == "warning"),
        "blocked_count": sum(1 for item in entries if item.get("status") == "blocked"),
        "required_failed": required_failed,
        "status": "passed" if not required_failed else "blocked",
        "entries": entries,
    }


def materialize_probe_params(row: dict[str, Any], trade_date: str, today: date | None = None) -> dict[str, Any]:
    """Replace registry template placeholders with a concrete probe date."""

    iso_date = probe_trade_date_for_api(row, trade_date, today=today)
    compact_date = iso_date.replace("-", "")
    daily_iso_date = settled_daily_probe_trade_date(trade_date, today=today)
    daily_compact_date = daily_iso_date.replace("-", "")
    params: dict[str, Any] = {}
    for key, value in row.get("sample_params", {}).items():
        if value == "YYYY-MM-DD":
            params[key] = iso_date
        elif value == "YYYYMMDD":
            params[key] = compact_date
        else:
            params[key] = value

    provider = row.get("provider")
    api_name = row.get("api_name")
    if provider == "baostock" and api_name == "query_adjust_factor":
        params["code"] = "sz.000001"
        params["start_date"] = "1990-01-01"
        params["end_date"] = iso_date
    if provider == "baostock" and api_name == "query_all_stock":
        params["day"] = daily_iso_date
    if provider == "baostock" and api_name in {
        "query_history_k_data_plus_daily_raw",
        "query_history_k_data_plus_daily_qfq",
    }:
        params["start_date"] = daily_iso_date
        params["end_date"] = daily_iso_date
    if provider == "baostock" and api_name == "query_trade_dates":
        params["start_date"] = "2024-01-01"
        params["end_date"] = iso_date
    if provider == "akshare" and api_name == "index_zh_a_hist":
        params.setdefault("period", "daily")
    if provider == "akshare" and api_name == "stock_zh_a_spot_em":
        params["_probe_page_limit"] = 1
    if provider == "tencent" and api_name == "daily_bars":
        params.setdefault("provider_code", "sz000063")
        params.setdefault("period", "day")
        params["start_date"] = daily_iso_date
        params["end_date"] = daily_iso_date
        params.setdefault("count", 10)
        params.setdefault("adjustment", "qfq")
    if provider == "sohu" and api_name == "daily_bars":
        params.setdefault("provider_code", "cn_000063")
        params["start_date"] = daily_compact_date
        params["end_date"] = daily_compact_date
        params.setdefault("period", "d")
    return params


def run_probe_with_retries(
    base_url: str,
    row: dict[str, Any],
    trade_date: str,
    probe_timeout: float,
    max_attempts: int,
    retry_sleep: float,
) -> dict[str, Any]:
    attempts = max(max_attempts, 1)
    attempt_records: list[dict[str, Any]] = []
    last_probe: dict[str, Any] | None = None
    for attempt in range(1, attempts + 1):
        try:
            probe = request_json(
                "POST",
                base_url,
                "/source/probe",
                {
                    "provider": row["provider"],
                    "api_name": row["api_name"],
                    "sample_params": materialize_probe_params(row, trade_date),
                    "expected_fields": row["expected_fields"],
                    "dry_run": False,
                },
                timeout=probe_timeout,
            )
            last_probe = probe
            usable = bool(probe.get("usable_for_source_table"))
            attempt_records.append(
                {
                    "attempt": attempt,
                    "ok": usable,
                    "connectivity_pass": probe.get("connectivity_pass"),
                    "schema_pass": probe.get("schema_pass"),
                    "row_count": probe.get("row_count"),
                    "reject_reason": probe.get("reject_reason"),
                }
            )
            if usable:
                probe["_acceptance_attempts"] = attempt_records
                return probe
        except Exception as exc:
            attempt_records.append({"attempt": attempt, "ok": False, "error": str(exc)})
        if attempt < attempts:
            time.sleep(retry_sleep)

    if last_probe is not None:
        last_probe["_acceptance_attempts"] = attempt_records
        return last_probe
    return {
        "provider": row["provider"],
        "api_name": row["api_name"],
        "raw_table_name": row.get("raw_table_name"),
        "connectivity_pass": False,
        "schema_pass": False,
        "expected_fields": row.get("expected_fields", []),
        "observed_fields": [],
        "missing_fields": row.get("expected_fields", []),
        "row_count": 0,
        "usable_for_source_table": False,
        "usable_for_model_online": False,
        "usable_for_research_only": True,
        "reject_reason": attempt_records[-1].get("error") if attempt_records else "probe_failed",
        "_acceptance_attempts": attempt_records,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run source-data-service production acceptance checks")
    parser.add_argument("--base-url", default="http://127.0.0.1:8041")
    parser.add_argument("--symbol", default="000759.SZ")
    parser.add_argument("--trade-date", default=default_probe_trade_date())
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--require-postgres", action="store_true", default=False)
    parser.add_argument("--real-provider-probe", action="store_true", default=False)
    parser.add_argument("--probe-limit", type=int, default=0)
    parser.add_argument("--probe-timeout", type=float, default=120.0)
    parser.add_argument("--probe-retries", type=int, default=3)
    parser.add_argument("--probe-retry-sleep", type=float, default=1.5)
    parser.add_argument("--quality-matrix", action="store_true", default=False)
    parser.add_argument("--quality-matrix-symbol", action="append", default=None)
    parser.add_argument("--quality-matrix-trade-date", action="append", default=None)
    parser.add_argument("--quality-matrix-table", action="append", default=None)
    parser.add_argument("--quality-matrix-timeout", type=float, default=180.0)
    parser.add_argument("--quality-matrix-allow-warning", action="store_true", default=False)
    parser.add_argument("--dry-run-provider", action="store_true", default=True)
    args = parser.parse_args()

    started_at = datetime.now(timezone.utc)
    report: dict[str, Any] = {"base_url": args.base_url, "checks": []}

    def add(name: str, ok: bool, data: Any) -> None:
        report["checks"].append({"name": name, "ok": ok, "data": data})

    try:
        add("healthz", True, request_json("GET", args.base_url, "/healthz", timeout=args.timeout))
        add("readyz", True, request_json("GET", args.base_url, "/readyz", timeout=args.timeout))
        add("repository_status", True, request_json("GET", args.base_url, "/source/repository/status", timeout=args.timeout))
        add("queue_persistence", True, request_json("GET", args.base_url, "/source/fetch/persistence/status", timeout=args.timeout))
        add("repair_routes", True, request_json("GET", args.base_url, "/source/repair-routes", timeout=args.timeout))

        submit_payload = {
            "source_table_name": "source.adjusted_daily_bar_v1",
            "canonical_fields": ["adjusted_open", "adjusted_high", "adjusted_low", "adjusted_close"],
            "symbols": [args.symbol],
            "trade_date": args.trade_date,
            "trigger_type": "operator_manual",
            "priority": "P0_urgent_release",
            "request_source": "acceptance_script",
            "dry_run": True,
            "prefer_batch": False,
            "auto_start": False,
        }
        submit = request_json("POST", args.base_url, "/source/fetch/submit", submit_payload, timeout=args.timeout)
        add("fetch_submit", True, submit)
        worker = request_json(
            "POST",
            args.base_url,
            "/source/fetch/worker/run-once",
            {
                "worker_id": "acceptance-worker",
                "max_jobs": 5,
                "lease_seconds": 60,
                "dry_run_provider": args.dry_run_provider,
                "complete_on_structured_provider_error": False,
            },
            timeout=args.timeout,
        )
        add("fetch_worker_run_once", True, worker)
        add("queue_summary", True, request_json("GET", args.base_url, "/source/fetch/queues/summary", timeout=args.timeout))
        add("build_triggers", True, request_json("GET", args.base_url, "/source/build/triggers", timeout=args.timeout))
        build = request_json(
            "POST",
            args.base_url,
            "/source/build/worker/run-once",
            {"worker_id": "acceptance-build-worker", "max_triggers": 5, "dry_run": True},
            timeout=args.timeout,
        )
        add("source_build_worker_dry_run", True, build)
        readiness = request_json(
            "GET",
            args.base_url,
            f"/source/ops/production-readiness?require_postgres={str(args.require_postgres).lower()}&require_real_provider_probe=false",
            timeout=args.timeout,
        )
        add("production_readiness", readiness.get("status") == "passed", readiness)

        if args.real_provider_probe:
            matrix = request_json("GET", args.base_url, "/source/probe/matrix", timeout=args.timeout)
            required_rows = [r for r in matrix.get("rows", []) if r.get("real_probe_required")]
            rows = required_rows if args.probe_limit <= 0 else required_rows[: args.probe_limit]
            probe_results = []
            for row in rows:
                probe = run_probe_with_retries(
                    args.base_url,
                    row,
                    args.trade_date,
                    args.probe_timeout,
                    args.probe_retries,
                    args.probe_retry_sleep,
                )
                probe_results.append(probe)
                time.sleep(0.5)
            real_probe_readiness = request_json(
                "GET",
                args.base_url,
                (
                    "/source/ops/production-readiness"
                    f"?require_postgres={str(args.require_postgres).lower()}&require_real_provider_probe=true"
                ),
                timeout=args.timeout,
            )
            real_probe_summary = summarize_real_provider_probe(probe_results, real_probe_readiness)
            add("real_provider_probe", real_probe_summary.get("status") == "passed", real_probe_summary)

        if args.quality_matrix:
            quality_matrix = run_quality_matrix(
                base_url=args.base_url,
                symbols=parse_csv_values(args.quality_matrix_symbol, [args.symbol]),
                trade_dates=parse_csv_values(args.quality_matrix_trade_date, [args.trade_date]),
                table_specs=parse_quality_matrix_tables(args.quality_matrix_table),
                timeout=args.quality_matrix_timeout,
                allow_warning=args.quality_matrix_allow_warning,
            )
            add("quality_matrix", quality_matrix.get("status") == "passed", quality_matrix)
    except Exception as exc:
        add("exception", False, str(exc))

    ok = all(item["ok"] for item in report["checks"])
    evidence_payload = {
        "base_url": args.base_url,
        "dry_run_provider": args.dry_run_provider,
        "require_postgres": args.require_postgres,
        "require_real_provider_probe": args.real_provider_probe,
        "status": "passed" if ok else "blocked",
        "can_lock_candidate": ok,
        "blocking_reasons": [item["name"] for item in report["checks"] if not item["ok"]],
        "warning_reasons": [],
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "checks": [
            {
                "check_code": item["name"],
                "status": "passed" if item["ok"] else "blocked",
                "required_for_lock": True,
                "evidence": item["data"] if isinstance(item["data"], dict) else {"value": item["data"]},
            }
            for item in report["checks"]
        ],
    }
    try:
        evidence = request_json(
            "POST",
            args.base_url,
            "/source/ops/acceptance-runs",
            evidence_payload,
            timeout=args.timeout,
        )
        add(
            "acceptance_evidence_persisted",
            bool(evidence.get("persisted")) or not args.require_postgres,
            evidence,
        )
    except Exception as exc:
        add("acceptance_evidence_persisted", not args.require_postgres, str(exc))

    ok = all(item["ok"] for item in report["checks"])
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
