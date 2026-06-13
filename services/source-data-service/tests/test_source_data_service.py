from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from source_data_service.api import app
from source_data_service.gap_detector import build_repair_plan
from source_data_service.models import Provider, SourceGapRequest
from source_data_service.provider_registry import get_api_spec, list_api_specs, list_source_requirements
from source_data_service.resilience import CircuitBreaker, CircuitOpenError


def test_api_registry_contains_free_primary_sources() -> None:
    specs = list_api_specs()
    names = {(item.provider.value, item.api_name) for item in specs}
    assert ("baostock", "query_history_k_data_plus_daily_raw") in names
    assert ("baostock", "query_history_k_data_plus_daily_qfq") in names
    assert ("akshare", "stock_zh_a_hist_daily_qfq") in names
    assert ("tushare", "daily") in names


def test_api_spec_declares_raw_table_and_targets() -> None:
    spec = get_api_spec(Provider.BAOSTOCK, "query_history_k_data_plus_daily_qfq")
    assert spec.raw_table_name == "raw_baostock.query_history_k_data_plus_daily_qfq_v1"
    assert "source.adjusted_daily_bar_v1" in spec.canonical_targets
    assert "adjustflag" in spec.response_fields


def test_requirements_for_p0_have_backup_provider() -> None:
    p0 = [item for item in list_source_requirements() if item.required_level.value == "P0"]
    assert p0
    assert all(item.backup_provider is not None for item in p0)
    assert all(item.minimum_coverage_rate >= 0.995 for item in p0)


def test_gap_repair_plan_for_adjusted_close_targets_exact_interfaces() -> None:
    plan = build_repair_plan(
        SourceGapRequest(
            source_table_name="source.adjusted_daily_bar_v1",
            canonical_field_name="adjusted_close",
            symbol="000759.SZ",
            trade_date=date(2026, 5, 25),
        )
    )
    assert plan.primary_repair.provider == Provider.BAOSTOCK
    assert plan.primary_repair.api_name == "query_history_k_data_plus_daily_qfq"
    assert plan.primary_repair.params["code"] == "sz.000759"
    assert plan.primary_repair.params["adjustflag"] == "2"
    assert plan.backup_repairs[0].provider == Provider.AKSHARE
    assert plan.backup_repairs[0].api_name == "stock_zh_a_hist_daily_qfq"
    assert plan.backup_repairs[0].params["adjust"] == "qfq"


def test_gap_repair_plan_for_daily_close_uses_raw_price_not_qfq() -> None:
    plan = build_repair_plan(
        SourceGapRequest(
            source_table_name="source.daily_bar_v1",
            canonical_field_name="close_price",
            symbol="000759.SZ",
            trade_date=date(2026, 5, 25),
        )
    )
    assert plan.primary_repair.api_name == "query_history_k_data_plus_daily_raw"
    assert plan.primary_repair.params["adjustflag"] == "3"
    assert plan.backup_repairs[0].api_name == "stock_zh_a_hist_daily_raw"
    assert plan.backup_repairs[0].params["adjust"] == ""


def test_circuit_breaker_opens_and_recovers() -> None:
    breaker = CircuitBreaker(failure_threshold=2, recovery_seconds=0)
    breaker.record_failure()
    breaker.before_call()
    breaker.record_failure()
    # recovery_seconds=0 means next before_call closes circuit immediately.
    breaker.before_call()
    assert breaker.failure_count == 0


def test_circuit_breaker_blocks_before_recovery() -> None:
    breaker = CircuitBreaker(failure_threshold=1, recovery_seconds=999)
    breaker.record_failure()
    try:
        breaker.before_call()
    except CircuitOpenError:
        pass
    else:  # pragma: no cover
        raise AssertionError("breaker should be open")


def test_fastapi_registry_and_repair_endpoints() -> None:
    client = TestClient(app)
    assert client.get("/health").json()["status"] == "ok"
    apis = client.get("/source/apis").json()
    assert any(item["raw_table_name"] == "raw_baostock.query_history_k_data_plus_daily_qfq_v1" for item in apis)
    repair = client.post(
        "/source/gaps/repair-plan",
        json={
            "source_table_name": "source.adjusted_daily_bar_v1",
            "canonical_field_name": "adjusted_close",
            "symbol": "000759.SZ",
            "trade_date": "2026-05-25",
        },
    )
    assert repair.status_code == 200
    assert repair.json()["primary_repair"]["raw_table_name"] == "raw_baostock.query_history_k_data_plus_daily_qfq_v1"


def test_probe_dry_run_does_not_call_provider() -> None:
    client = TestClient(app)
    resp = client.post(
        "/source/probe",
        json={
            "provider": "baostock",
            "api_name": "query_history_k_data_plus_daily_qfq",
            "sample_params": {"code": "sz.000759", "start_date": "2026-05-25", "end_date": "2026-05-25"},
            "dry_run": True,
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["connectivity_pass"] is True
    assert payload["usable_for_research_only"] is True


def test_readiness_endpoint_blocks_unknown_table_and_passes_daily() -> None:
    client = TestClient(app)
    ok = client.post("/source/readiness/evaluate", json={"source_table_name": "source.daily_bar_v1"})
    assert ok.status_code == 200
    assert ok.json()["readiness_status"] == "passed"
    missing = client.post("/source/readiness/evaluate", json={"source_table_name": "source.unknown"})
    assert missing.status_code == 404


def test_source_service_readyz_and_provider_status_do_not_call_remote_provider() -> None:
    client = TestClient(app)
    ready = client.get("/readyz")
    assert ready.status_code == 200
    assert ready.json()["status"] in {"ready", "degraded"}
    status = client.get("/source/providers/status?provider=baostock")
    assert status.status_code == 200
    rows = status.json()
    assert rows
    assert all(row["provider"] == "baostock" for row in rows)


def test_fetch_raw_returns_structured_provider_error_when_optional_package_missing() -> None:
    client = TestClient(app)
    resp = client.post(
        "/source/raw/fetch",
        json={
            "provider": "baostock",
            "api_name": "query_history_k_data_plus_daily_qfq",
            "params": {"code": "sz.000759", "start_date": "2026-05-25", "end_date": "2026-05-25"},
            "dry_run": False,
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["raw_table_name"] == "raw_baostock.query_history_k_data_plus_daily_qfq_v1"
    # In CI the optional provider may not be installed. The service must still
    # return a structured result rather than raising a 5xx or crashing.
    assert "error" in payload


def test_legacy_market_provider_contracts_are_registered_but_adapter_migration_pending() -> None:
    specs = list_api_specs()
    names = {(item.provider.value, item.api_name) for item in specs}
    assert ("eastmoney", "daily_bars") in names
    assert ("eastmoney", "quote_snapshot") in names
    assert ("tencent", "auction_snapshot") in names
    client = TestClient(app)
    rows = client.get("/source/providers/status?provider=eastmoney").json()
    assert rows
    assert any(row["adapter_implemented"] is False for row in rows)


def test_field_contracts_cover_expanded_p0_source_chain() -> None:
    from source_data_service.provider_registry import list_field_contracts

    contracts = list_field_contracts()
    names = {(item.source_table_name, item.canonical_field_name) for item in contracts}
    required = {
        ("source.daily_bar_v1", "high_price"),
        ("source.daily_bar_v1", "low_price"),
        ("source.daily_bar_v1", "pre_close_price"),
        ("source.adjusted_daily_bar_v1", "adjusted_high"),
        ("source.trade_status_v1", "is_suspended"),
        ("source.limit_price_v1", "up_limit_price"),
        ("source.index_daily_bar_v1", "close_price"),
    }
    assert required <= names
    p0_online = [item for item in contracts if item.required_level.value == "P0" and item.online_policy == "required"]
    assert p0_online
    assert all(item.backup_provider is not None for item in p0_online if item.primary_provider.value != "internal")
    assert all("available_at" in " ".join(item.field_quality_rules) for item in p0_online)


def test_gap_diagnosis_includes_rebuild_and_lineage_steps() -> None:
    client = TestClient(app)
    resp = client.post(
        "/source/gaps/diagnose",
        json={
            "source_table_name": "source.adjusted_daily_bar_v1",
            "canonical_field_name": "adjusted_high",
            "symbol": "000759.SZ",
            "trade_date": "2026-05-25",
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["online_impact"] == "block_online"
    assert payload["primary_repair"]["raw_table_name"] == "raw_baostock.query_history_k_data_plus_daily_qfq_v1"
    assert any("source_lineage_v1" in step for step in payload["rebuild_steps"])
    assert payload["lineage_lookup"]["source_pk"] == "000759.SZ|2026-05-25"


def test_lineage_resolve_explains_candidate_raw_tables() -> None:
    client = TestClient(app)
    resp = client.post(
        "/source/lineage/resolve",
        json={
            "source_table_name": "source.daily_bar_v1",
            "canonical_field_name": "high_price",
            "symbol": "000759.SZ",
            "trade_date": "2026-05-25",
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert "governance.source_lineage_v1" in payload["lineage_query_hint"]
    assert "raw_baostock.query_history_k_data_plus_daily_raw_v1" in payload["candidate_raw_tables"]
    assert "high" in payload["expected_raw_fields"] or "最高" in payload["expected_raw_fields"]


def test_raw_fetch_dry_run_returns_request_hash_for_idempotency() -> None:
    client = TestClient(app)
    resp = client.post(
        "/source/raw/fetch",
        json={
            "provider": "baostock",
            "api_name": "query_history_k_data_plus_daily_raw",
            "params": {"code": "sz.000759", "start_date": "2026-05-25", "end_date": "2026-05-25"},
            "dry_run": True,
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["request_hash"]
    assert payload["row_count"] == 0


def test_source_build_plan_explains_raw_inputs_quality_and_lineage() -> None:
    client = TestClient(app)
    resp = client.post(
        "/source/build/plan",
        json={
            "source_table_name": "source.adjusted_daily_bar_v1",
            "canonical_fields": ["adjusted_close", "adjusted_high"],
            "symbol": "000759.SZ",
            "trade_date": "2026-05-25",
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["step_count"] == 2
    assert all(step["primary_raw_table_name"] == "raw_baostock.query_history_k_data_plus_daily_qfq_v1" for step in payload["steps"])
    assert all(step["lineage_required"] is True for step in payload["steps"])
    assert any("source_lineage_v1" in item for item in payload["execution_order"])


def test_raw_quality_validation_blocks_bad_ohlc_before_source_build() -> None:
    client = TestClient(app)
    resp = client.post(
        "/source/quality/validate-raw",
        json={
            "provider": "baostock",
            "api_name": "query_history_k_data_plus_daily_raw",
            "rows": [
                {
                    "date": "2026-05-25",
                    "code": "sz.000759",
                    "open": "5.0",
                    "high": "4.9",
                    "low": "5.1",
                    "close": "5.0",
                    "preclose": "4.8",
                    "volume": "1000",
                    "amount": "5000",
                    "adjustflag": "3",
                    "turn": "1.2",
                    "tradestatus": "1",
                    "pctChg": "2.0",
                    "isST": "0",
                }
            ],
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["build_allowed"] is False
    assert payload["error_count"] >= 1
    assert any(issue["rule_code"] == "high_lt_low" for issue in payload["issues"])


def test_raw_quality_validation_allows_valid_akshare_daily_row() -> None:
    client = TestClient(app)
    resp = client.post(
        "/source/quality/validate-raw",
        json={
            "provider": "akshare",
            "api_name": "stock_zh_a_hist_daily_raw",
            "rows": [
                {
                    "日期": "2026-05-25",
                    "开盘": "5.0",
                    "收盘": "5.2",
                    "最高": "5.3",
                    "最低": "4.9",
                    "成交量": "10000",
                    "成交额": "52000",
                    "振幅": "8.0",
                    "涨跌幅": "4.0",
                    "涨跌额": "0.2",
                    "换手率": "2.0",
                }
            ],
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["build_allowed"] is True
    assert payload["error_count"] == 0


def test_readiness_matrix_probe_matrix_and_repair_routes_are_operator_ready() -> None:
    client = TestClient(app)
    matrix = client.get("/source/readiness/matrix")
    assert matrix.status_code == 200
    assert matrix.json()["table_count"] >= 3
    probe = client.get("/source/probe/matrix")
    assert probe.status_code == 200
    assert probe.json()["api_count"] >= 10
    required = [row for row in probe.json()["rows"] if row["real_probe_required"]]
    assert required
    assert all(row["provider"] in {"baostock", "akshare"} for row in required)
    assert not any(row["provider"] in {"eastmoney", "tencent", "sina", "cninfo"} and row["real_probe_required"] for row in probe.json()["rows"])
    routes = client.get("/source/repair-routes")
    assert routes.status_code == 200
    rows = routes.json()["rows"]
    assert any(row["source_table_name"] == "source.daily_bar_v1" and row["canonical_field_name"] == "close_price" for row in rows)


def test_fetch_plan_groups_multiple_fields_into_one_symbol_parallel_raw_job() -> None:
    client = TestClient(app)
    resp = client.post(
        "/source/fetch/plan",
        json={
            "source_table_name": "source.adjusted_daily_bar_v1",
            "canonical_fields": ["adjusted_close", "adjusted_high"],
            "symbols": ["000759.SZ", "000001.SZ"],
            "trade_date": "2026-05-25",
            "trigger_type": "model_release_preflight",
            "priority": "P0_urgent_release",
            "request_source": "ambush-watchlist-service",
            "model_code": "ambush_watchlist",
            "model_phase": "release_gate",
            "dry_run": True,
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["strategy"] == "symbol_parallel"
    assert payload["queue_name"] == "urgent_release_gate_queue"
    # 2 symbols * 1 deduped raw request each, not 2 symbols * 2 fields.
    assert payload["job_count"] == 2
    assert all(sorted(job["canonical_fields"]) == ["adjusted_close", "adjusted_high"] for job in payload["jobs"])
    assert any(policy["provider"] == "baostock" for policy in payload["rate_limit_policies"])


def test_fetch_submit_pull_complete_and_callback_status_are_persistent_in_service_memory() -> None:
    client = TestClient(app)
    submit = client.post(
        "/source/fetch/submit",
        json={
            "source_table_name": "source.daily_bar_v1",
            "canonical_fields": ["close_price", "high_price"],
            "symbols": ["000760.SZ"],
            "trade_date": "2026-05-28",
            "trigger_type": "data_inspection_gap_repair",
            "priority": "P0_urgent_release",
            "request_source": "data-inspector-service",
            "dry_run": True,
            "callback_url": "http://data-inspector-service:8050/callback/source-fetch",
        },
    )
    assert submit.status_code == 200
    batch_id = submit.json()["fetch_batch_id"]
    assert submit.json()["status"] == "queued"
    pull = client.post(
        "/source/fetch/worker/pull",
        json={"worker_id": "worker-a", "max_jobs": 1, "queue_names": ["repair_queue"]},
    )
    assert pull.status_code == 200
    assert pull.json()["leased_count"] == 1
    job_id = pull.json()["jobs"][0]["job_item_id"]
    batch_running = client.get(f"/source/fetch/batches/{batch_id}").json()
    assert batch_running["leased_count"] == 1
    done = client.post(
        f"/source/fetch/jobs/{job_id}/complete",
        json={"worker_id": "worker-a", "success": True, "row_count": 1},
    )
    assert done.status_code == 200
    assert done.json()["status"] == "succeeded"
    batch_done = client.get(f"/source/fetch/batches/{batch_id}").json()
    assert batch_done["status"] == "succeeded"
    callbacks = client.get(f"/source/fetch/callbacks?fetch_batch_id={batch_id}").json()
    event_types = {event["event_type"] for event in callbacks}
    assert {"batch_submitted", "job_leased", "job_succeeded", "batch_completed"} <= event_types


def test_failed_primary_fetch_queues_backup_job_without_losing_status() -> None:
    client = TestClient(app)
    submit = client.post(
        "/source/fetch/submit",
        json={
            "source_table_name": "source.adjusted_daily_bar_v1",
            "canonical_fields": ["adjusted_close"],
            "symbols": ["000759.SZ"],
            "trade_date": "2026-05-25",
            "trigger_type": "model_adhoc_request",
            "priority": "P1_normal_ingest",
            "request_source": "ambush-watchlist-service",
            "dry_run": True,
        },
    )
    batch_id = submit.json()["fetch_batch_id"]
    pull = client.post("/source/fetch/worker/pull", json={"worker_id": "worker-b", "max_jobs": 1}).json()
    job_id = pull["jobs"][0]["job_item_id"]
    failed = client.post(
        f"/source/fetch/jobs/{job_id}/complete",
        json={"worker_id": "worker-b", "success": False, "error_code": "timeout", "error_message": "provider timeout"},
    )
    assert failed.status_code == 200
    batch = client.get(f"/source/fetch/batches/{batch_id}").json()
    assert batch["queued_count"] == 1
    callbacks = client.get(f"/source/fetch/callbacks?fetch_batch_id={batch_id}").json()
    assert any(event["event_type"] == "backup_job_queued" for event in callbacks)
    pull_backup = client.post("/source/fetch/worker/pull", json={"worker_id": "worker-c", "max_jobs": 1}).json()
    assert pull_backup["leased_count"] == 1
    assert pull_backup["jobs"][0]["backup_of_job_item_id"] == job_id


def test_provider_runtime_status_exposes_concurrency_queue_counts() -> None:
    client = TestClient(app)
    resp = client.get("/source/providers/runtime-status?provider=baostock")
    assert resp.status_code == 200
    rows = resp.json()
    assert rows
    assert any(row["api_name"] == "query_history_k_data_plus_daily_raw" for row in rows)
    assert all(row["max_concurrency"] >= 1 for row in rows)


def test_ds5_persistence_status_queue_summary_and_idempotent_submit() -> None:
    client = TestClient(app)
    status = client.get("/source/fetch/persistence/status")
    assert status.status_code == 200
    payload = status.json()
    assert payload["backend"] in {"memory", "postgres"}
    assert "production" in payload["note"] or "postgres" in payload["note"]

    body = {
        "source_table_name": "source.daily_bar_v1",
        "canonical_fields": ["close_price"],
        "symbols": ["000759.SZ"],
        "trade_date": "2026-05-25",
        "trigger_type": "scheduled_periodic",
        "priority": "P1_normal_ingest",
        "request_source": "scheduler-service",
        "dry_run": True,
        "idempotency_key": "daily-bar-000759-20260525-once",
    }
    first = client.post("/source/fetch/submit", json=body)
    assert first.status_code == 200
    second = client.post("/source/fetch/submit", json=body)
    assert second.status_code == 200
    assert first.json()["fetch_batch_id"] == second.json()["fetch_batch_id"]
    assert second.json()["producer_ack"] == "duplicate_idempotency_key_returned_existing_batch"

    summary = client.get("/source/fetch/queues/summary")
    assert summary.status_code == 200
    assert any(row["queue_name"] == "normal_daily_ingest_queue" for row in summary.json()["rows"])


def test_ds5_worker_run_once_creates_source_build_trigger() -> None:
    client = TestClient(app)
    submit = client.post(
        "/source/fetch/submit",
        json={
            "source_table_name": "source.adjusted_daily_bar_v1",
            "canonical_fields": ["adjusted_close"],
            "symbols": ["000002.SZ"],
            "trade_date": "2026-05-27",
            "trigger_type": "provider_probe",
            "priority": "P1_normal_ingest",
            "request_source": "operator",
            "dry_run": True,
        },
    )
    assert submit.status_code == 200
    batch_id = submit.json()["fetch_batch_id"]
    run = client.post(
        "/source/fetch/worker/run-once",
        json={
            "worker_id": "worker-ds5",
            "max_jobs": 1,
            "queue_names": ["provider_probe_queue"],
            "dry_run_provider": True,
        },
    )
    assert run.status_code == 200
    payload = run.json()
    assert payload["leased_count"] == 1
    assert payload["succeeded_count"] == 1
    assert payload["generated_build_trigger_count"] >= 1
    triggers = client.get(f"/source/build/triggers?fetch_batch_id={batch_id}")
    assert triggers.status_code == 200
    assert triggers.json()
    callbacks = client.get(f"/source/fetch/callbacks?fetch_batch_id={batch_id}").json()
    assert any(event["event_type"] == "source_build_trigger_created" for event in callbacks)


def test_ds5_heartbeat_cancel_callbacks_and_maintenance_endpoints() -> None:
    client = TestClient(app)
    submit = client.post(
        "/source/fetch/submit",
        json={
            "source_table_name": "source.daily_bar_v1",
            "canonical_fields": ["close_price"],
            "symbols": ["000001.SZ"],
            "trade_date": "2026-05-26",
            "trigger_type": "operator_manual",
            "priority": "P1_normal_ingest",
            "request_source": "operator",
            "dry_run": True,
            "callback_url": "http://example.invalid/callback",
        },
    )
    batch_id = submit.json()["fetch_batch_id"]
    pull = client.post(
        "/source/fetch/worker/pull",
        json={"worker_id": "worker-heartbeat", "max_jobs": 1, "lease_seconds": 30},
    )
    assert pull.status_code == 200
    job_id = pull.json()["jobs"][0]["job_item_id"]
    heartbeat = client.post(
        f"/source/fetch/jobs/{job_id}/heartbeat",
        json={"worker_id": "worker-heartbeat", "extend_lease_seconds": 60, "worker_note": "still running"},
    )
    assert heartbeat.status_code == 200
    assert heartbeat.json()["lease_expires_at"] is not None
    dispatch = client.post("/source/fetch/callbacks/dispatch", json={"max_events": 5, "dry_run": True})
    assert dispatch.status_code == 200
    assert dispatch.json()["dry_run"] is True
    maintenance = client.post("/source/fetch/maintenance/requeue-expired-leases")
    assert maintenance.status_code == 200
    cancel = client.post(
        f"/source/fetch/batches/{batch_id}/cancel",
        json={"reason": "operator requested rollback", "operator": "qa"},
    )
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "cancelled"
    dead = client.get("/source/fetch/dead-letter")
    assert dead.status_code == 200


def test_ds6_raw_ingest_source_build_lineage_and_repository_status() -> None:
    client = TestClient(app)
    submit = client.post(
        "/source/fetch/submit",
        json={
            "source_table_name": "source.adjusted_daily_bar_v1",
            "canonical_fields": ["adjusted_open", "adjusted_high", "adjusted_low", "adjusted_close"],
            "symbols": ["000760.SZ"],
            "trade_date": "2026-05-28",
            "trigger_type": "data_inspection_gap_repair",
            "priority": "P0_urgent_release",
            "request_source": "data-inspector-service",
            "dry_run": True,
        },
    )
    assert submit.status_code == 200
    batch_id = submit.json()["fetch_batch_id"]
    pull = client.post("/source/fetch/worker/pull", json={"worker_id": "worker-ds6", "max_jobs": 1, "queue_names": ["repair_queue"]})
    assert pull.status_code == 200
    job = pull.json()["jobs"][0]
    request_hash = job["request_hash"]
    raw_row = {
        "date": "2026-05-28",
        "code": "sz.000760",
        "open": "5.10",
        "high": "5.50",
        "low": "5.00",
        "close": "5.42",
        "preclose": "4.93",
        "volume": "100000",
        "amount": "54200000",
        "adjustflag": "2",
        "turn": "3.2",
        "tradestatus": "1",
        "pctChg": "9.94",
        "isST": "0",
    }
    ingest = client.post(
        "/source/raw/ingest-result",
        json={
            "provider": "baostock",
            "api_name": "query_history_k_data_plus_daily_qfq",
            "raw_table_name": "raw_baostock.query_history_k_data_plus_daily_qfq_v1",
            "request_params": job["request_params"],
            "dry_run": False,
            "row_count": 1,
            "request_hash": request_hash,
            "response_schema_hash": "schema_qfq_v1",
            "rows": [
                {
                    "provider": "baostock",
                    "api_name": "query_history_k_data_plus_daily_qfq",
                    "raw_table_name": "raw_baostock.query_history_k_data_plus_daily_qfq_v1",
                    "request_params": job["request_params"],
                    "row": raw_row,
                    "request_hash": request_hash,
                    "response_schema_hash": "schema_qfq_v1",
                    "response_row_hash": "row_qfq_000760_20260528",
                }
            ],
        },
    )
    assert ingest.status_code == 200
    assert ingest.json()["raw_write_status"] == "accepted"
    done = client.post(f"/source/fetch/jobs/{job['job_item_id']}/complete", json={"worker_id": "worker-ds6", "success": True, "row_count": 1, "raw_request_hash": request_hash})
    assert done.status_code == 200
    triggers = client.get(f"/source/build/triggers?fetch_batch_id={batch_id}").json()
    assert triggers
    execute = client.post(f"/source/build/triggers/{triggers[0]['trigger_id']}/execute", json={"trigger_id": triggers[0]["trigger_id"], "worker_id": "builder-ds6"})
    assert execute.status_code == 200
    payload = execute.json()
    assert payload["status"] == "succeeded"
    assert payload["source_row_count"] == 1
    assert payload["lineage_row_count"] >= 4
    rows = client.get("/source/rows?source_table_name=source.adjusted_daily_bar_v1&symbol=000760.SZ&trade_date=2026-05-28").json()
    assert rows
    assert rows[0]["values"]["adjusted_close"] == 5.42
    lineage = client.get("/source/lineage/records?source_table_name=source.adjusted_daily_bar_v1&source_pk=000760.SZ|2026-05-28").json()
    assert any(row["canonical_field_name"] == "adjusted_close" for row in lineage)
    status = client.get("/source/repository/status").json()
    assert status["raw_row_count"] >= 1
    assert status["source_row_count"] >= 1
    assert status["lineage_row_count"] >= 1


def test_source_build_dry_run_does_not_mutate_trigger_or_duplicate_complete() -> None:
    client = TestClient(app)
    submit = client.post(
        "/source/fetch/submit",
        json={
            "source_table_name": "source.daily_bar_v1",
            "canonical_fields": ["close_price"],
            "symbols": ["000761.SZ"],
            "trade_date": "2026-05-29",
            "trigger_type": "operator_manual",
            "priority": "P1_normal_ingest",
            "request_source": "operator",
            "dry_run": True,
        },
    )
    assert submit.status_code == 200
    batch_id = submit.json()["fetch_batch_id"]
    pull = client.post(
        "/source/fetch/worker/pull",
        json={"worker_id": "worker-build-dry-run", "max_jobs": 1, "queue_names": ["normal_daily_ingest_queue"]},
    )
    assert pull.status_code == 200
    job_id = pull.json()["jobs"][0]["job_item_id"]
    done = client.post(
        f"/source/fetch/jobs/{job_id}/complete",
        json={"worker_id": "worker-build-dry-run", "success": True, "row_count": 0},
    )
    assert done.status_code == 200
    triggers = client.get(f"/source/build/triggers?fetch_batch_id={batch_id}").json()
    assert len(triggers) == 1
    trigger_id = triggers[0]["trigger_id"]
    dry = client.post(
        f"/source/build/triggers/{trigger_id}/execute",
        json={"trigger_id": trigger_id, "worker_id": "builder-dry-run", "dry_run": True},
    )
    assert dry.status_code == 200
    assert dry.json()["status"] == "dry_run"
    after_dry = client.get(f"/source/build/triggers?fetch_batch_id={batch_id}").json()
    assert after_dry[0]["status"] == "queued"

    duplicate_done = client.post(
        f"/source/fetch/jobs/{job_id}/complete",
        json={"worker_id": "worker-build-dry-run", "success": True, "row_count": 0},
    )
    assert duplicate_done.status_code == 200
    after_duplicate = client.get(f"/source/build/triggers?fetch_batch_id={batch_id}").json()
    assert len(after_duplicate) == 1


def test_ds6_freshness_storage_model_coverage_and_release_preflight_endpoints() -> None:
    client = TestClient(app)
    sla = client.get("/source/freshness/sla?source_table_name=source.adjusted_daily_bar_v1")
    assert sla.status_code == 200
    assert any(row["canonical_field_name"] == "adjusted_close" for row in sla.json())
    storage = client.get("/source/storage/policies")
    assert storage.status_code == 200
    assert any(row["table_name"] == "governance.source_lineage_v1" for row in storage.json())
    requirements = client.get("/source/models/requirements?model_code=ambush_watchlist&model_phase=release_gate")
    assert requirements.status_code == 200
    assert any(row["source_table_name"] == "source.adjusted_daily_bar_v1" for row in requirements.json())
    freshness = client.post(
        "/source/freshness/status/check",
        json={
            "source_table_name": "source.adjusted_daily_bar_v1",
            "canonical_fields": ["adjusted_close"],
            "symbols": ["000760.SZ"],
            "trade_date": "2026-05-28",
        },
    )
    assert freshness.status_code == 200
    assert freshness.json()["status"] in {"passed", "degraded", "blocked"}
    coverage = client.post(
        "/source/models/coverage/check",
        json={
            "model_code": "ambush_watchlist",
            "model_phase": "release_gate",
            "trade_date": "2026-05-28",
            "symbols": ["000760.SZ"],
            "required_levels": ["P0", "P1"],
        },
    )
    assert coverage.status_code == 200
    payload = coverage.json()
    assert payload["p0_field_count"] >= 2
    assert payload["coverage_status"] in {"passed", "degraded", "blocked"}
    preflight = client.post(
        "/source/release/preflight",
        json={
            "model_code": "ambush_watchlist",
            "model_phase": "release_gate",
            "trade_date": "2026-05-28",
            "symbols": ["000760.SZ"],
        },
    )
    assert preflight.status_code == 200
    preflight_payload = preflight.json()
    assert "can_release_official_signal" in preflight_payload
    # Daily raw close has not been built in this test chain, so official release
    # must remain blocked instead of silently passing with partial data.
    assert preflight_payload["can_release_official_signal"] is False
    assert preflight_payload["blocking_reasons"]


def test_ds7_production_readiness_gate_blocks_without_postgres_and_passes_contract_mode() -> None:
    client = TestClient(app)
    contract_mode = client.get("/source/ops/production-readiness?require_postgres=false&require_real_provider_probe=false")
    assert contract_mode.status_code == 200
    payload = contract_mode.json()
    assert payload["status"] == "passed"
    assert payload["can拍板"] is True
    assert any(check["check_code"] == "durable_queue_ready" for check in payload["checks"])

    strict = client.get("/source/ops/production-readiness?require_postgres=true&require_real_provider_probe=false")
    assert strict.status_code == 200
    strict_payload = strict.json()
    assert strict_payload["status"] in {"passed", "blocked"}
    if strict_payload["status"] == "blocked":
        assert any("durable" in reason or "Postgres" in reason or "postgres" in reason for reason in strict_payload["blocking_reasons"])


def test_ds7_acceptance_evidence_endpoint_exposes_persistence_status() -> None:
    client = TestClient(app)
    resp = client.post(
        "/source/ops/acceptance-runs",
        json={
            "base_url": "http://127.0.0.1:8041",
            "dry_run_provider": True,
            "require_postgres": True,
            "require_real_provider_probe": False,
            "status": "passed",
            "can_lock_candidate": True,
            "checks": [
                {
                    "check_code": "healthz",
                    "status": "passed",
                    "required_for_lock": True,
                    "evidence": {"status": "ok"},
                }
            ],
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["acceptance_run_id"].startswith("acceptance_")
    assert payload["status"] == "passed"
    assert payload["checks"][0]["check_code"] == "healthz"
    assert "persisted" in payload


def test_ds7_real_probe_readiness_uses_persisted_evidence_gate() -> None:
    client = TestClient(app)
    strict = client.get("/source/ops/production-readiness?require_postgres=false&require_real_provider_probe=true")
    assert strict.status_code == 200
    payload = strict.json()
    assert any(check["check_code"] == "real_provider_probe_evidence" for check in payload["checks"])
    if payload["status"] == "blocked":
        probe_check = next(check for check in payload["checks"] if check["check_code"] == "real_provider_probe_evidence")
        assert "required_probe_count" in probe_check["evidence"]


def test_ds7_acceptance_script_exists_and_documents_http_only_runner() -> None:
    from pathlib import Path

    path = Path("scripts/source_data_acceptance.py")
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "/source/ops/production-readiness" in text
    assert "/source/fetch/worker/run-once" in text
    assert "/source/ops/acceptance-runs" in text
    assert "--real-provider-probe" in text


def test_akshare_eastmoney_fallbacks_keep_probe_contract(monkeypatch) -> None:
    from source_data_service.adapters import akshare_adapter

    monkeypatch.setattr(
        akshare_adapter,
        "_eastmoney_paginated_diff",
        lambda _url, _params, **_kwargs: [
            {
                "f2": 12.67,
                "f3": 2.67,
                "f4": 0.33,
                "f5": 4710,
                "f6": 5941492.33,
                "f7": 4.46,
                "f8": 0.96,
                "f10": 0.52,
                "f12": "920992",
                "f14": "sample",
                "f15": 12.85,
                "f16": 12.3,
                "f17": 12.3,
                "f18": 12.34,
                "f20": 100,
                "f21": 80,
            }
        ],
    )
    spot = akshare_adapter._stock_zh_a_spot_em_fallback_rows()
    assert spot[0]["代码"] == "920992"
    assert {"序号", "代码", "名称", "最新价", "成交额", "换手率", "总市值", "流通市值"} <= set(spot[0])

    def fake_json(_url, params):
        if params.get("secid") == "0.399006":
            return {
                "data": {
                    "klines": [
                        "2024-05-28,1824.09,1806.25,1827.74,1805.65,134487619,190307684090.85,1.21,-1.35,-24.71,2.42"
                    ]
                }
            }
        return {"data": None}

    monkeypatch.setattr(akshare_adapter, "_eastmoney_json", fake_json)
    index_rows = akshare_adapter._index_zh_a_hist_fallback_rows(
        {"symbol": "399006", "period": "daily", "start_date": "20240528", "end_date": "20240528"}
    )
    assert index_rows[0]["日期"] == "2024-05-28"
    assert {"日期", "开盘", "收盘", "最高", "最低", "成交量", "成交额", "涨跌幅"} <= set(index_rows[0])

    stock_calls = []

    def fake_stock_json(_url, params):
        stock_calls.append(params)
        if params.get("secid") == "0.000759":
            return {
                "data": {
                    "klines": [
                        "2024-05-28,4.91,5.05,5.11,4.86,924261,462317440.00,5.09,2.43,0.12,4.31"
                    ]
                }
            }
        return {"data": None}

    monkeypatch.setattr(akshare_adapter, "_eastmoney_json", fake_stock_json)
    raw_rows = akshare_adapter._stock_zh_a_hist_fallback_rows(
        {"symbol": "000759", "period": "daily", "start_date": "20240528", "end_date": "20240528", "adjust": ""}
    )
    qfq_rows = akshare_adapter._stock_zh_a_hist_fallback_rows(
        {"symbol": "000759", "period": "daily", "start_date": "20240528", "end_date": "20240528", "adjust": "qfq"}
    )
    assert raw_rows[0]["日期"] == "2024-05-28"
    assert raw_rows[0]["股票代码"] == "000759"
    assert {"日期", "开盘", "收盘", "最高", "最低", "成交量", "成交额", "涨跌幅", "换手率"} <= set(raw_rows[0])
    assert qfq_rows[0]["收盘"] == "5.05"
    assert any(call["fqt"] == "0" for call in stock_calls)
    assert any(call["fqt"] == "1" for call in stock_calls)
