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
from datetime import date, datetime, timezone
from typing import Any


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


def materialize_probe_params(row: dict[str, Any], trade_date: str) -> dict[str, Any]:
    """Replace registry template placeholders with a concrete probe date."""

    iso_date = trade_date
    compact_date = trade_date.replace("-", "")
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
    if provider == "baostock" and api_name == "query_trade_dates":
        params["start_date"] = "2024-01-01"
        params["end_date"] = iso_date
    if provider == "akshare" and api_name == "index_zh_a_hist":
        params.setdefault("period", "daily")
    if provider == "akshare" and api_name == "stock_zh_a_spot_em":
        params["_probe_page_limit"] = 1
    return params


def run_probe_with_retries(
    base_url: str,
    row: dict[str, Any],
    trade_date: str,
    timeout: float,
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
                timeout=max(timeout, 30.0),
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
    parser.add_argument("--trade-date", default=str(date.today()))
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--require-postgres", action="store_true", default=False)
    parser.add_argument("--real-provider-probe", action="store_true", default=False)
    parser.add_argument("--probe-limit", type=int, default=3)
    parser.add_argument("--probe-retries", type=int, default=3)
    parser.add_argument("--probe-retry-sleep", type=float, default=1.5)
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
            rows = [r for r in matrix.get("rows", []) if r.get("real_probe_required")][: args.probe_limit]
            probe_results = []
            for row in rows:
                probe = run_probe_with_retries(
                    args.base_url,
                    row,
                    args.trade_date,
                    args.timeout,
                    args.probe_retries,
                    args.probe_retry_sleep,
                )
                probe_results.append(probe)
                time.sleep(0.5)
            add("real_provider_probe", all(p.get("usable_for_source_table") for p in probe_results), probe_results)
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
