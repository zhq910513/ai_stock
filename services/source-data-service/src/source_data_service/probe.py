from __future__ import annotations

import json
from uuid import uuid4
from typing import Any

from source_data_service.models import ProbeRequest, ProbeResult
from source_data_service.fetch_persistence import configured_database_url, psycopg_available
from source_data_service.provider_registry import get_api_spec
from source_data_service.provider_runtime import execute_provider_fetch


def _persist_probe_result(probe: ProbeResult) -> None:
    if not configured_database_url() or not psycopg_available():
        return
    try:  # pragma: no cover - runtime Postgres evidence path
        import psycopg

        with psycopg.connect(configured_database_url()) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO governance.source_probe_result_v1 (
                        probe_run_id, provider, api_name, raw_table_name,
                        connectivity_pass, schema_pass, expected_fields_json,
                        observed_fields_json, missing_fields_json, row_count,
                        usable_for_source_table, usable_for_model_online,
                        usable_for_research_only, reject_reason
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s,%s,%s,%s,%s)
                    """,
                    (
                        f"probe_{uuid4().hex[:20]}",
                        probe.provider.value,
                        probe.api_name,
                        probe.raw_table_name,
                        probe.connectivity_pass,
                        probe.schema_pass,
                        json.dumps(probe.expected_fields, ensure_ascii=False),
                        json.dumps(probe.observed_fields, ensure_ascii=False),
                        json.dumps(probe.missing_fields, ensure_ascii=False),
                        probe.row_count,
                        probe.usable_for_source_table,
                        probe.usable_for_model_online,
                        probe.usable_for_research_only,
                        probe.reject_reason,
                    ),
                )
            conn.commit()
    except Exception:
        return


def real_probe_evidence_summary(required_probes: list[tuple[str, str]]) -> dict[str, Any]:
    """Summarize latest persisted real probe evidence for production readiness."""

    summary: dict[str, Any] = {
        "required_probe_count": len(required_probes),
        "usable_probe_count": 0,
        "missing_probe_count": 0,
        "missing_required_probes": [],
        "all_required_probes_usable": False,
        "latest_results": [],
    }
    if not required_probes:
        summary["all_required_probes_usable"] = True
        return summary
    if not configured_database_url() or not psycopg_available():
        summary["missing_probe_count"] = len(required_probes)
        summary["missing_required_probes"] = [f"{provider}.{api_name}" for provider, api_name in required_probes]
        summary["note"] = "Postgres probe evidence store is unavailable."
        return summary
    try:  # pragma: no cover - runtime Postgres evidence path
        import psycopg

        latest_results: list[dict[str, Any]] = []
        usable_count = 0
        missing: list[str] = []
        with psycopg.connect(configured_database_url()) as conn:
            with conn.cursor() as cur:
                for provider, api_name in required_probes:
                    cur.execute(
                        """
                        SELECT provider, api_name, raw_table_name, connectivity_pass,
                               schema_pass, row_count, usable_for_source_table,
                               usable_for_model_online, usable_for_research_only,
                               reject_reason, created_at
                        FROM governance.source_probe_result_v1
                        WHERE provider = %s AND api_name = %s
                        ORDER BY created_at DESC
                        LIMIT 1
                        """,
                        (provider, api_name),
                    )
                    row = cur.fetchone()
                    if not row:
                        missing.append(f"{provider}.{api_name}")
                        continue
                    item = {
                        "provider": row[0],
                        "api_name": row[1],
                        "raw_table_name": row[2],
                        "connectivity_pass": row[3],
                        "schema_pass": row[4],
                        "row_count": row[5],
                        "usable_for_source_table": row[6],
                        "usable_for_model_online": row[7],
                        "usable_for_research_only": row[8],
                        "reject_reason": row[9],
                        "created_at": row[10].isoformat() if row[10] else None,
                    }
                    latest_results.append(item)
                    if row[3] and row[4] and int(row[5] or 0) > 0 and row[6] and row[7]:
                        usable_count += 1
                    else:
                        missing.append(f"{provider}.{api_name}")
        summary.update(
            {
                "usable_probe_count": usable_count,
                "missing_probe_count": len(missing),
                "missing_required_probes": missing,
                "all_required_probes_usable": usable_count == len(required_probes) and not missing,
                "latest_results": latest_results,
            }
        )
        return summary
    except Exception as exc:
        summary["missing_probe_count"] = len(required_probes)
        summary["missing_required_probes"] = [f"{provider}.{api_name}" for provider, api_name in required_probes]
        summary["note"] = f"failed to read source_probe_result_v1: {exc}"
        return summary


def list_probe_results(provider: str | None = None, api_name: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    if not configured_database_url() or not psycopg_available():
        return []
    where = []
    params: list[Any] = []
    if provider:
        where.append("provider = %s")
        params.append(provider)
    if api_name:
        where.append("api_name = %s")
        params.append(api_name)
    sql = """
        SELECT provider, api_name, raw_table_name, connectivity_pass, schema_pass,
               expected_fields_json, observed_fields_json, missing_fields_json,
               row_count, usable_for_source_table, usable_for_model_online,
               usable_for_research_only, reject_reason, created_at
        FROM governance.source_probe_result_v1
    """
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at DESC LIMIT %s"
    params.append(limit)
    try:  # pragma: no cover - runtime Postgres evidence path
        import psycopg

        with psycopg.connect(configured_database_url()) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        return [
            {
                "provider": row[0],
                "api_name": row[1],
                "raw_table_name": row[2],
                "connectivity_pass": row[3],
                "schema_pass": row[4],
                "expected_fields": row[5],
                "observed_fields": row[6],
                "missing_fields": row[7],
                "row_count": row[8],
                "usable_for_source_table": row[9],
                "usable_for_model_online": row[10],
                "usable_for_research_only": row[11],
                "reject_reason": row[12],
                "created_at": row[13],
            }
            for row in rows
        ]
    except Exception:
        return []


def run_probe(request: ProbeRequest) -> ProbeResult:
    spec = get_api_spec(request.provider, request.api_name)
    expected = request.expected_fields or spec.response_fields
    result = execute_provider_fetch(
        provider=request.provider,
        api_name=request.api_name,
        params=request.sample_params,
        dry_run=request.dry_run,
    )
    observed = sorted({key for row in result.rows for key in row.row.keys()})
    missing = [field for field in expected if field not in observed] if not request.dry_run else []
    schema_pass = bool(not missing or request.dry_run)
    connectivity_pass = result.error is None
    if result.error:
        probe = ProbeResult(
            provider=request.provider,
            api_name=request.api_name,
            raw_table_name=spec.raw_table_name,
            connectivity_pass=False,
            schema_pass=False,
            expected_fields=expected,
            observed_fields=observed,
            missing_fields=expected if not observed else missing,
            row_count=0,
            usable_for_source_table=False,
            usable_for_model_online=False,
            usable_for_research_only=True,
            reject_reason=result.error,
        )
        _persist_probe_result(probe)
        return probe
    probe = ProbeResult(
        provider=request.provider,
        api_name=request.api_name,
        raw_table_name=spec.raw_table_name,
        connectivity_pass=connectivity_pass,
        schema_pass=schema_pass,
        expected_fields=expected,
        observed_fields=observed,
        missing_fields=missing,
        row_count=result.row_count,
        usable_for_source_table=schema_pass and result.row_count > 0,
        usable_for_model_online=schema_pass and result.row_count > 0 and not request.dry_run,
        usable_for_research_only=request.dry_run or not schema_pass,
        reject_reason=None if schema_pass else "missing expected fields",
    )
    _persist_probe_result(probe)
    return probe
