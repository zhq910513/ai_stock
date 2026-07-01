from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
import time

from fastapi.testclient import TestClient

from source_data_service.api import app
import source_data_service.fetch_orchestrator as fetch_orchestrator
import source_data_service.source_repository as source_repository
import source_data_service.worker_executor as worker_executor
from source_data_service.gap_detector import build_repair_plan
from source_data_service.fetch_orchestrator import build_fetch_plan
from source_data_service.models import CallbackEventType, FetchCallbackEventOut, FetchPlanRequest, FetchPriority, FetchStrategy, FetchTriggerType, FetchUniverseScope, FetchWorkerRunOnceRequest, Provider, QualityStatus, RawFetchResult, RawRow, ReleasePreflightRequest, SourceBuildExecuteRequest, SourceCanonicalRowOut, SourceGapRequest, SourceLineageRecordOut
import source_data_service.operational_governance as operational_governance
import source_data_service.ths_paid_probability as ths_paid_probability
from source_data_service.postgres_repository import (
    _date_or_none,
    _durable_raw_row_payload,
    _extract_code as _pg_extract_code,
    _extract_trade_date as _pg_extract_trade_date,
    _normalize_symbol as _pg_normalize_symbol,
    _raw_row_matches_requested_identity,
    _source_identity_from_record,
    _source_lineage_identity,
    _source_lineage_lock_key,
    _source_payload_and_key,
)
from source_data_service.provider_registry import get_api_spec, list_api_specs, list_source_requirements
from source_data_service.provider_runtime import adapter_implemented
from source_data_service.resilience import CircuitBreaker, CircuitOpenError
from source_data_service.source_repository import _build_values, _canonical_fields_for_source_build, _extract_symbol, execute_source_build_trigger, ingest_raw_fetch_result
from source_data_service.symbol_rules import is_a_share_symbol, normalize_symbol


def test_api_registry_contains_free_primary_sources() -> None:
    specs = list_api_specs()
    names = {(item.provider.value, item.api_name) for item in specs}
    assert ("baostock", "query_history_k_data_plus_daily_raw") in names
    assert ("baostock", "query_history_k_data_plus_daily_qfq") in names
    assert ("akshare", "stock_zh_a_hist_daily_qfq") in names
    assert ("baidu", "finance_news_feed") in names
    assert ("ths", "limit_up_pool") in names
    assert ("eastmoney", "stock_universe") in names
    assert ("eastmoney", "auction_snapshot") in names
    assert ("eastmoney", "northbound_summary") in names
    assert ("eastmoney", "lpr_rates") in names
    assert ("tencent", "quote_snapshot") in names
    assert ("tencent", "minute_bars") in names
    assert ("sina", "auction_snapshot") in names
    assert ("coingecko", "simple_price") in names
    assert ("yahoo", "chart") in names
    assert ("jin10", "public_flash") in names
    assert ("tushare", "daily") in names


def test_a_share_symbol_rules_include_stock_segments_and_exclude_index_funds() -> None:
    assert normalize_symbol("sz.302132") == "302132.SZ"
    assert normalize_symbol("bj.920001") == "920001.BJ"
    assert is_a_share_symbol("600000.SH")
    assert is_a_share_symbol("688001.SH")
    assert is_a_share_symbol("000001.SZ")
    assert is_a_share_symbol("302132.SZ")
    assert is_a_share_symbol("920001.BJ")
    assert not is_a_share_symbol("000001.SH")
    assert not is_a_share_symbol("399001.SZ")
    assert not is_a_share_symbol("510050.SH")
    assert not is_a_share_symbol("159001.SZ")


def test_api_spec_declares_raw_table_and_targets() -> None:
    spec = get_api_spec(Provider.BAOSTOCK, "query_history_k_data_plus_daily_qfq")
    assert spec.raw_table_name == "raw_baostock.query_history_k_data_plus_daily_qfq_v1"
    assert "source.adjusted_daily_bar_v1" in spec.canonical_targets
    assert "adjustflag" in spec.response_fields


def test_ths_paid_probability_contract_is_registered_without_cookie_params() -> None:
    spec = get_api_spec(Provider.THS, "paid_limit_up_probability")

    assert spec.raw_table_name == "raw_ths.paid_limit_up_probability_v1"
    assert spec.canonical_targets == ["source.ths_paid_limit_up_probability_v1"]
    assert spec.requires_token is True
    assert spec.is_free is False
    assert set(spec.request_template) == {"date", "stock_code", "credential_version"}
    serialized = str(spec.request_template).lower()
    assert "cookie" not in serialized
    assert "userid" not in serialized
    assert adapter_implemented(Provider.THS, "paid_limit_up_probability")


def test_ths_paid_probability_request_params_reference_credential_version_only(monkeypatch) -> None:
    monkeypatch.setattr(ths_paid_probability, "active_credential_version", lambda: "ths_paid_version_for_test")

    params = ths_paid_probability.provider_request_params("002971.SZ", date(2026, 6, 18))

    assert params == {
        "date": "20260618",
        "stock_code": "002971",
        "credential_version": "ths_paid_version_for_test",
    }
    serialized = str(params).lower()
    assert "cookie" not in serialized
    assert "userid" not in serialized
    assert "user" not in serialized.replace("source", "")


def test_ths_paid_probability_deadline_abandons_only_after_next_trade_9(monkeypatch) -> None:
    trade_date = date(2026, 6, 18)
    next_trade_date = date(2026, 6, 19)
    deadline = datetime(2026, 6, 19, 1, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(ths_paid_probability, "candidate_symbols", lambda _trade_date: ["002971.SZ"])
    monkeypatch.setattr(ths_paid_probability, "fetched_symbols", lambda _trade_date: set())
    monkeypatch.setattr(ths_paid_probability, "deadline_at", lambda _trade_date: (next_trade_date, deadline))
    monkeypatch.setattr(ths_paid_probability, "_read_persisted_status", lambda _trade_date: None)
    monkeypatch.setattr(ths_paid_probability, "_persist_status", lambda _status: None)
    monkeypatch.setattr(
        ths_paid_probability,
        "cookie_status",
        lambda: type("CookieStatus", (), {"status": "expired"})(),
    )

    before_deadline = ths_paid_probability.evaluate_batch_status(
        trade_date,
        now=deadline - timedelta(seconds=1),
    )
    after_deadline = ths_paid_probability.evaluate_batch_status(
        trade_date,
        now=deadline,
    )

    assert before_deadline.status == "cookie_expired"
    assert before_deadline.next_trade_date == next_trade_date
    assert after_deadline.status == "abandoned_no_probability_before_deadline"
    assert after_deadline.deadline_at == deadline


def test_ths_paid_probability_pending_probe_cookie_is_not_reported_expired(monkeypatch) -> None:
    trade_date = date(2026, 6, 18)
    next_trade_date = date(2026, 6, 19)
    deadline = datetime(2026, 6, 19, 1, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(ths_paid_probability, "candidate_symbols", lambda _trade_date: ["002971.SZ"])
    monkeypatch.setattr(ths_paid_probability, "fetched_symbols", lambda _trade_date: set())
    monkeypatch.setattr(ths_paid_probability, "deadline_at", lambda _trade_date: (next_trade_date, deadline))
    monkeypatch.setattr(ths_paid_probability, "_read_persisted_status", lambda _trade_date: None)
    monkeypatch.setattr(ths_paid_probability, "_persist_status", lambda _status: None)
    monkeypatch.setattr(
        ths_paid_probability,
        "cookie_status",
        lambda: type("CookieStatus", (), {"status": "pending_probe"})(),
    )

    before_deadline = ths_paid_probability.evaluate_batch_status(
        trade_date,
        now=deadline - timedelta(seconds=1),
    )
    after_deadline = ths_paid_probability.evaluate_batch_status(
        trade_date,
        now=deadline,
    )

    assert before_deadline.status == "fetching"
    assert before_deadline.cookie_status == "pending_probe"
    assert after_deadline.status == "abandoned_no_probability_before_deadline"
    assert "expired" not in (after_deadline.message or "").lower()


def test_requirements_for_p0_have_backup_provider() -> None:
    p0 = [item for item in list_source_requirements() if item.required_level.value == "P0"]
    assert p0
    paid_probability_exception = ("source.ths_paid_limit_up_probability_v1", "paid_limit_up_probability")
    assert all(
        item.backup_provider is not None
        or (item.source_table_name, item.canonical_field_name) == paid_probability_exception
        for item in p0
    )
    assert all(item.minimum_coverage_rate >= 0.9 for item in p0)
    daily_tables = {"source.daily_bar_v1", "source.adjusted_daily_bar_v1", "source.index_daily_bar_v1"}
    assert all(item.minimum_coverage_rate >= 0.995 for item in p0 if item.source_table_name in daily_tables)


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
    assert plan.backup_repairs[0].provider == Provider.TENCENT
    assert plan.backup_repairs[0].api_name == "daily_bars"
    assert plan.backup_repairs[0].params["provider_code"] == "sz000759"
    assert plan.backup_repairs[0].params["adjustment"] == "qfq"


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
    assert plan.backup_repairs[0].provider == Provider.TENCENT
    assert plan.backup_repairs[0].api_name == "daily_bars"
    assert plan.backup_repairs[0].params["provider_code"] == "sz000759"
    assert plan.backup_repairs[0].params["adjustment"] == "raw"


def test_gap_repair_plan_for_daily_amount_uses_sohu_historical_backup() -> None:
    plan = build_repair_plan(
        SourceGapRequest(
            source_table_name="source.daily_bar_v1",
            canonical_field_name="amount",
            symbol="000759.SZ",
            trade_date=date(2026, 5, 25),
        )
    )
    assert plan.primary_repair.provider == Provider.BAOSTOCK
    assert plan.primary_repair.api_name == "query_history_k_data_plus_daily_raw"
    assert plan.backup_repairs[0].provider == Provider.SOHU
    assert plan.backup_repairs[0].api_name == "daily_bars"
    assert plan.backup_repairs[0].raw_table_name == "raw_sohu.daily_bars_v1"
    assert plan.backup_repairs[0].params["provider_code"] == "cn_000759"
    assert plan.backup_repairs[0].params["start_date"] == "20260525"
    assert plan.backup_repairs[0].params["end_date"] == "20260525"


def test_fetch_plan_merges_daily_backup_plans_and_prioritizes_price_coverage() -> None:
    plan = build_fetch_plan(
        FetchPlanRequest(
            source_table_name="source.daily_bar_v1",
            canonical_fields=["amount", "close_price", "high_price", "low_price", "open_price", "volume"],
            symbols=["000759.SZ"],
            trade_date=date(2026, 6, 19),
            trigger_type=FetchTriggerType.SCHEDULED_PERIODIC,
            priority=FetchPriority.P1_NORMAL_INGEST,
            request_source="scheduler-service",
            dry_run=True,
        )
    )

    assert plan.job_count == 1
    backups = plan.jobs[0].backup_plans
    assert backups
    assert backups[0].provider == Provider.TENCENT
    assert backups[0].api_name == "daily_bars"
    assert any(item.provider == Provider.SOHU and item.api_name == "daily_bars" for item in backups)


def test_fetch_plan_full_a_share_daily_expands_source_universe_without_sample_fallback(monkeypatch) -> None:
    available = datetime(2026, 6, 22, 8, 0, tzinfo=timezone.utc)

    def fake_list_source_rows(source_table_name: str, trade_date: str | None = None):
        if source_table_name == "source.stock_universe_daily_v1" and trade_date == "2026-06-22":
            return [
                SourceCanonicalRowOut(
                    source_table_name="source.stock_universe_daily_v1",
                    source_pk="000063.SZ|2026-06-22",
                    symbol="000063.SZ",
                    trade_date=date(2026, 6, 22),
                    values={"is_tradable": True, "is_suspended": False, "is_delisting_risk": False, "trade_status": "交易"},
                    updated_at=available,
                ),
                SourceCanonicalRowOut(
                    source_table_name="source.stock_universe_daily_v1",
                    source_pk="000759.SZ|2026-06-22",
                    symbol="000759.SZ",
                    trade_date=date(2026, 6, 22),
                    values={"is_tradable": False, "is_suspended": True, "is_delisting_risk": False, "trade_status": "停牌"},
                    updated_at=available,
                ),
                SourceCanonicalRowOut(
                    source_table_name="source.stock_universe_daily_v1",
                    source_pk="000001.SH|2026-06-22",
                    symbol="000001.SH",
                    trade_date=date(2026, 6, 22),
                    values={"is_tradable": True, "trade_status": "1"},
                    updated_at=available,
                ),
                SourceCanonicalRowOut(
                    source_table_name="source.stock_universe_daily_v1",
                    source_pk="399001.SZ|2026-06-22",
                    symbol="399001.SZ",
                    trade_date=date(2026, 6, 22),
                    values={"is_tradable": True, "trade_status": "1"},
                    updated_at=available,
                ),
                SourceCanonicalRowOut(
                    source_table_name="source.stock_universe_daily_v1",
                    source_pk="510050.SH|2026-06-22",
                    symbol="510050.SH",
                    trade_date=date(2026, 6, 22),
                    values={"is_tradable": True, "trade_status": "1"},
                    updated_at=available,
                ),
            ]
        if source_table_name == "source.stock_master_v1":
            return []
        return []

    monkeypatch.setattr(fetch_orchestrator, "_list_source_rows", fake_list_source_rows)

    plan = build_fetch_plan(
        FetchPlanRequest(
            source_table_name="source.daily_bar_v1",
            canonical_fields=["close_price"],
            universe_scope=FetchUniverseScope.FULL_A_SHARE,
            trade_date=date(2026, 6, 22),
            trigger_type=FetchTriggerType.SCHEDULED_PERIODIC,
            priority=FetchPriority.P1_NORMAL_INGEST,
            request_source="scheduler-service",
            dry_run=True,
        )
    )

    assert plan.symbols_count == 1
    assert plan.strategy in {FetchStrategy.API_BATCH_BY_DATE, FetchStrategy.SINGLE_REQUEST}
    assert plan.jobs[0].symbol == "000063.SZ"
    assert plan.jobs[0].request_params["code"] == "sz.000063"
    assert all("000759" not in str(job.request_params) for job in plan.jobs)


def test_fetch_plan_full_a_share_stock_universe_keeps_market_batch() -> None:
    plan = build_fetch_plan(
        FetchPlanRequest(
            source_table_name="source.stock_universe_daily_v1",
            canonical_fields=["is_tradable", "trade_status"],
            universe_scope=FetchUniverseScope.FULL_A_SHARE,
            trade_date=date(2026, 6, 22),
            trigger_type=FetchTriggerType.SCHEDULED_PERIODIC,
            priority=FetchPriority.P1_NORMAL_INGEST,
            request_source="scheduler-service",
            dry_run=True,
        )
    )

    assert plan.strategy == FetchStrategy.FULL_MARKET_BATCH
    assert plan.symbols_count == 0
    assert plan.job_count == 1
    assert plan.jobs[0].symbol is None
    assert plan.jobs[0].api_name == "query_all_stock"
    assert plan.jobs[0].request_params["day"] == "2026-06-22"


def test_baostock_query_all_stock_builds_stock_universe_values() -> None:
    values, warnings = _build_values(
        Provider.BAOSTOCK,
        "query_all_stock",
        "source.stock_universe_daily_v1",
        {
            "code": "sz.000759",
            "code_name": "中百集团",
            "tradeStatus": "1",
        },
        ["is_tradable", "trade_status"],
    )

    assert warnings == []
    assert values["is_tradable"] is True
    assert values["trade_status"] == "1"
    assert values["stock_name"] == "中百集团"


def test_baostock_query_all_stock_builds_non_tradable_universe_values() -> None:
    values, warnings = _build_values(
        Provider.BAOSTOCK,
        "query_all_stock",
        "source.stock_universe_daily_v1",
        {
            "code": "sh.600000",
            "code_name": "浦发银行",
            "tradeStatus": "0",
        },
        ["is_tradable", "trade_status"],
    )

    assert warnings == []
    assert values["is_tradable"] is False
    assert values["trade_status"] == "0"
    assert values["stock_name"] == "浦发银行"


def test_baostock_query_all_stock_skips_non_a_share_universe_rows() -> None:
    for code in ("sh.000001", "sz.399001", "sh.510050", "sz.159001"):
        values, warnings = _build_values(
            Provider.BAOSTOCK,
            "query_all_stock",
            "source.stock_universe_daily_v1",
            {
                "code": code,
                "code_name": "non-a asset",
                "tradeStatus": "1",
            },
            ["is_tradable", "trade_status"],
        )
        assert values == {}
        assert warnings == []


def test_fetch_plan_stage_candidates_requires_explicit_symbols() -> None:
    try:
        build_fetch_plan(
            FetchPlanRequest(
                source_table_name="source.trade_tick_v1",
                canonical_fields=["price"],
                universe_scope=FetchUniverseScope.STAGE_CANDIDATES,
                trade_date=date(2026, 6, 22),
                trigger_type=FetchTriggerType.MODEL_RELEASE_PREFLIGHT,
                priority=FetchPriority.P0_URGENT_RELEASE,
                request_source="scheduler-service",
                dry_run=True,
            )
        )
    except ValueError as exc:
        assert "stage_candidates fetch requires explicit symbols" in str(exc)
    else:
        raise AssertionError("stage_candidates without symbols must be blocked")


def test_hot_preopen_preflight_uses_previous_trade_day_for_daily_bar(monkeypatch) -> None:
    captured: list[tuple[str, str | None, str | None]] = []

    def fake_list_source_rows(source_table_name: str, symbol: str | None = None, trade_date: str | None = None):
        captured.append((source_table_name, symbol, trade_date))
        available = datetime(2026, 6, 18, 8, 0, tzinfo=timezone.utc)
        if source_table_name == "source.trade_calendar_v1" and trade_date == "2026-06-19":
            return [
                SourceCanonicalRowOut(
                    source_table_name="source.trade_calendar_v1",
                    source_pk="2026-06-19",
                    symbol=None,
                    trade_date=date(2026, 6, 19),
                    values={"calendar_date": date(2026, 6, 19), "is_trading_day": True, "pretrade_date": date(2026, 6, 18)},
                    source_quality_status=QualityStatus.USABLE,
                    primary_provider=Provider.BAOSTOCK,
                    build_batch_id="build-calendar-test",
                    available_at=available,
                    captured_at=available,
                    updated_at=available,
                )
            ]
        if source_table_name == "source.daily_bar_v1" and symbol == "000063.SZ" and trade_date == "2026-06-18":
            return [
                SourceCanonicalRowOut(
                    source_table_name="source.daily_bar_v1",
                    source_pk="000063.SZ|2026-06-18",
                    symbol="000063.SZ",
                    trade_date=date(2026, 6, 18),
                    values={"close_price": 42.5},
                    source_quality_status=QualityStatus.USABLE,
                    primary_provider=Provider.TENCENT,
                    build_batch_id="build-daily-test",
                    available_at=available,
                    captured_at=available,
                    updated_at=available,
                )
            ]
        if source_table_name == "source.trade_status_v1" and symbol == "000063.SZ" and trade_date == "2026-06-19":
            return [
                SourceCanonicalRowOut(
                    source_table_name="source.trade_status_v1",
                    source_pk="000063.SZ|2026-06-19",
                    symbol="000063.SZ",
                    trade_date=date(2026, 6, 19),
                    values={"is_tradable": True},
                    source_quality_status=QualityStatus.USABLE,
                    primary_provider=Provider.BAOSTOCK,
                    build_batch_id="build-status-test",
                    available_at=available,
                    captured_at=available,
                    updated_at=available,
                )
            ]
        return []

    monkeypatch.setattr(operational_governance, "list_source_rows", fake_list_source_rows)

    result = operational_governance.preflight_release(
        ReleasePreflightRequest(
            model_code="hot_candidates",
            model_phase="preopen_release_gate",
            trade_date=date(2026, 6, 19),
            symbols=["000063.SZ"],
            decision_time=datetime(2026, 6, 19, 1, 29, 40, tzinfo=timezone.utc),
        )
    )

    assert result.can_release_official_signal is True
    assert ("source.daily_bar_v1", "000063.SZ", "2026-06-18") in captured
    assert ("source.daily_bar_v1", "000063.SZ", "2026-06-19") not in captured
    assert ("source.trade_status_v1", "000063.SZ", "2026-06-19") in captured


def test_limit_event_repair_uses_ths_public_limit_up_pool_primary() -> None:
    plan = build_repair_plan(
        SourceGapRequest(
            source_table_name="source.limit_event_v1",
            canonical_field_name="limit_open_count",
            symbol="000759.SZ",
            trade_date=date(2026, 6, 15),
        )
    )
    assert plan.primary_repair.provider == Provider.THS
    assert plan.primary_repair.api_name == "limit_up_pool"
    assert plan.primary_repair.raw_table_name == "raw_ths.limit_up_pool_v1"
    assert plan.primary_repair.params["fetch_all_pages"] is True
    assert plan.backup_repairs[0].provider == Provider.BAOSTOCK
    assert plan.backup_repairs[0].api_name == "query_history_k_data_plus_daily_raw"


def test_ths_limit_up_pool_builds_limit_event_fields() -> None:
    values, warnings = _build_values(
        Provider.THS,
        "limit_up_pool",
        "source.limit_event_v1",
        {
            "date": "2026-06-15",
            "code": "000759",
            "symbol": "000759.SZ",
            "limit_event_type": "t_board_limit_up",
            "is_one_word_board": False,
            "is_break_limit": True,
            "close_on_limit_flag": True,
            "limit_open_count": 3,
        },
        ["limit_event_type", "is_one_word_board", "is_break_limit", "close_on_limit_flag", "limit_open_count"],
    )
    assert warnings == []
    assert values == {
        "limit_event_type": "t_board_limit_up",
        "is_one_word_board": False,
        "is_break_limit": True,
        "close_on_limit_flag": True,
        "limit_open_count": 3.0,
    }


def test_ths_paid_probability_builds_source_values_without_cookie_material() -> None:
    values, warnings = _build_values(
        Provider.THS,
        "paid_limit_up_probability",
        "source.ths_paid_limit_up_probability_v1",
        {
            "date": "2026-06-18",
            "trade_date": "2026-06-18",
            "stock_code": "002971",
            "symbol": "002971.SZ",
            "paid_limit_up_probability": "39.02",
            "status_code": 0,
            "status_msg": "success",
            "credential_version": "ths_paid_test_version",
            "raw_provider_row": {"data": "39.02", "status_code": 0, "status_msg": "success"},
        },
        ["paid_limit_up_probability", "credential_version"],
    )

    assert warnings == []
    assert values["paid_limit_up_probability"] == 39.02
    assert values["credential_version"] == "ths_paid_test_version"
    serialized = str(values).lower()
    assert "cookie" not in serialized
    assert "userid" not in serialized
    assert "user_cookie" not in serialized


def test_durable_typed_raw_reader_exposes_ths_paid_probability_columns() -> None:
    captured_at = datetime(2026, 6, 29, 7, 21, 16, tzinfo=timezone.utc)
    row = _durable_raw_row_payload(
        {
            "raw_id": 1001,
            "provider": "ths",
            "api_name": "paid_limit_up_probability",
            "request_params_json": {
                "date": "20260629",
                "stock_code": "000521",
                "credential_version": "ths_paid_test_version",
            },
            "request_hash": "provider_hash",
            "response_schema_hash": "schema_hash",
            "response_row_hash": "row_hash",
            "trade_date": date(2026, 6, 29),
            "code": "000521",
            "stock_code": "000521",
            "symbol": "000521.SZ",
            "paid_limit_up_probability": "78.36",
            "status_code": 0,
            "status_msg": "success",
            "credential_version": "ths_paid_test_version",
            "available_at": captured_at,
            "captured_at": captured_at,
            "raw_provider_row": {"data": "78.36", "status_code": 0, "status_msg": "success"},
        },
        {
            "date": "20260629",
            "stock_code": "000521",
            "credential_version": "ths_paid_test_version",
        },
    )

    assert row["date"] == "20260629"
    assert row["trade_date"] == date(2026, 6, 29)
    assert row["symbol"] == "000521.SZ"
    assert row["paid_limit_up_probability"] == "78.36"
    assert row["status_code"] == 0
    assert row["raw_provider_row"]["status_msg"] == "success"
    values, warnings = _build_values(
        Provider.THS,
        "paid_limit_up_probability",
        "source.ths_paid_limit_up_probability_v1",
        row,
        ["paid_limit_up_probability"],
    )
    assert warnings == []
    assert values == {"paid_limit_up_probability": 78.36}
    serialized = str(row).lower()
    assert "cookie" not in serialized
    assert "userid" not in serialized


def test_legacy_public_provider_adapters_are_runtime_visible() -> None:
    assert adapter_implemented(Provider.THS, "limit_up_pool")
    assert adapter_implemented(Provider.EASTMONEY, "stock_universe")
    assert adapter_implemented(Provider.EASTMONEY, "auction_snapshot")
    assert adapter_implemented(Provider.EASTMONEY, "northbound_summary")
    assert adapter_implemented(Provider.EASTMONEY, "lpr_rates")
    assert adapter_implemented(Provider.TENCENT, "quote_snapshot")
    assert adapter_implemented(Provider.TENCENT, "minute_bars")
    assert adapter_implemented(Provider.SINA, "auction_snapshot")
    assert adapter_implemented(Provider.TENCENT, "auction_snapshot")
    assert adapter_implemented(Provider.COINGECKO, "simple_price")
    assert adapter_implemented(Provider.YAHOO, "chart")
    assert adapter_implemented(Provider.JIN10, "public_flash")


def test_gap_repair_plan_for_index_daily_close_uses_index_safe_baostock_fields() -> None:
    plan = build_repair_plan(
        SourceGapRequest(
            source_table_name="source.index_daily_bar_v1",
            canonical_field_name="close_price",
            symbol="399006.SZ",
            trade_date=date(2026, 6, 12),
        )
    )
    assert plan.primary_repair.provider == Provider.TENCENT
    assert plan.primary_repair.api_name == "daily_bars"
    assert plan.primary_repair.params["provider_code"] == "sz399006"
    assert plan.primary_repair.params["adjustment"] == "raw"
    assert plan.backup_repairs[0].provider == Provider.BAOSTOCK
    assert plan.backup_repairs[0].api_name == "query_history_k_data_plus_daily_raw"
    assert plan.backup_repairs[0].params["code"] == "sz.399006"
    assert "tradestatus" not in str(plan.backup_repairs[0].params["fields"])
    assert "adjustflag" not in str(plan.backup_repairs[0].params["fields"])


def test_gap_repair_plan_for_moneyflow_uses_eastmoney_series_contract() -> None:
    plan = build_repair_plan(
        SourceGapRequest(
            source_table_name="source.stock_moneyflow_daily_v1",
            canonical_field_name="main_net_inflow",
            symbol="000759.SZ",
            trade_date=date(2026, 6, 12),
        )
    )
    assert plan.primary_repair.provider == Provider.EASTMONEY
    assert plan.primary_repair.api_name == "moneyflow_stock_series"
    assert plan.primary_repair.raw_table_name == "raw_eastmoney.moneyflow_stock_series_v1"
    assert plan.primary_repair.params["secid"] == "0.000759"
    assert plan.primary_repair.params["start_date"] == "2026-06-12"
    assert plan.backup_repairs[0].provider == Provider.TUSHARE
    assert plan.backup_repairs[0].api_name == "moneyflow"
    assert plan.backup_repairs[0].params["ts_code"] == "000759.SZ"


def test_gap_repair_plan_for_event_news_uses_baidu_feed_contract() -> None:
    plan = build_repair_plan(
        SourceGapRequest(
            source_table_name="source.event_news_v1",
            canonical_field_name="published_at",
            symbol="000759.SZ",
            trade_date=date(2026, 6, 12),
        )
    )
    assert plan.primary_repair.provider == Provider.BAIDU
    assert plan.primary_repair.api_name == "finance_news_feed"
    assert plan.primary_repair.raw_table_name == "raw_baidu.finance_news_feed_v1"
    assert plan.primary_repair.params == {"rn": 20, "pn": 0, "type": "all", "tag": "all"}
    assert plan.backup_repairs[0].provider == Provider.CNINFO


def test_intraday_source_build_values_include_physical_identity_fields() -> None:
    minute_values, minute_warnings = _build_values(
        Provider.EASTMONEY,
        "minute_bars",
        "source.minute_bar_v1",
        {
            "bar_time": "2026-06-12T10:30:00+08:00",
            "event_time": "2026-06-12T10:30:00+08:00",
            "open": "5.82",
            "high": "5.83",
            "low": "5.81",
            "close": "5.83",
        },
        ["close_price"],
    )
    assert minute_warnings == []
    assert minute_values["close_price"] == 5.83
    assert minute_values["open_price"] == 5.82
    assert minute_values["bar_time"] == "2026-06-12T10:30:00+08:00"
    assert minute_values["event_time"] == "2026-06-12T10:30:00+08:00"

    tick_values, tick_warnings = _build_values(
        Provider.EASTMONEY,
        "trade_details",
        "source.trade_tick_v1",
        {
            "tick_time": "2026-06-12T10:30:01+08:00",
            "price": "5.83",
            "side_code": "1",
            "amount": "58300",
            "provider_sequence": 88,
        },
        ["price", "side_code"],
    )
    assert tick_warnings == []
    assert tick_values["price"] == 5.83
    assert tick_values["side_code"] == "1"
    assert tick_values["tick_time"] == "2026-06-12T10:30:01+08:00"
    assert tick_values["provider_sequence"] == 88


def test_baidu_raw_sql_contract_keeps_request_hash() -> None:
    from pathlib import Path

    sql_files = [
        Path("infra/sql/0014_source_existing_provider_raw_contracts_v1.sql"),
        Path("infra/sql/bootstrap_schema.sql"),
    ]
    for sql_file in sql_files:
        sql = sql_file.read_text(encoding="utf-8")
        table_start = sql.index("CREATE TABLE IF NOT EXISTS raw_baidu.finance_news_feed_v1")
        table_end = sql.index(");", table_start)
        table_sql = sql[table_start:table_end]
        assert "request_hash TEXT" in table_sql
        assert "response_schema_hash TEXT" in table_sql
        assert "response_row_hash TEXT" in table_sql
        assert "idx_raw_baidu_news_request_hash" in sql


def test_legacy_public_provider_sql_contracts_exist_in_incremental_and_bootstrap() -> None:
    from pathlib import Path

    files = [
        Path("infra/sql/0023_source_legacy_public_provider_expansion_v1.sql"),
        Path("infra/sql/bootstrap_schema.sql"),
    ]
    required = [
        "CREATE TABLE IF NOT EXISTS raw_ths.limit_up_pool_v1",
        "request_hash TEXT",
        "CREATE TABLE IF NOT EXISTS raw_coingecko.simple_price_v1",
        "CREATE TABLE IF NOT EXISTS raw_yahoo.chart_v1",
        "CREATE TABLE IF NOT EXISTS raw_jin10.public_flash_v1",
        "CREATE TABLE IF NOT EXISTS raw_eastmoney.stock_universe_v1",
        "CREATE TABLE IF NOT EXISTS raw_eastmoney.auction_snapshot_v1",
        "CREATE TABLE IF NOT EXISTS raw_eastmoney.northbound_summary_v1",
        "CREATE TABLE IF NOT EXISTS raw_eastmoney.lpr_rates_v1",
        "CREATE TABLE IF NOT EXISTS raw_tencent.quote_snapshot_v1",
        "CREATE TABLE IF NOT EXISTS raw_tencent.minute_bars_v1",
        "idx_raw_ths_limit_up_request_hash",
        "idx_raw_tencent_minute_request_hash",
        "idx_raw_eastmoney_stock_universe_request_hash",
        "idx_raw_eastmoney_lpr_date",
    ]
    for path in files:
        sql = path.read_text(encoding="utf-8")
        for snippet in required:
            assert snippet in sql


def test_ths_paid_probability_sql_contracts_exist_in_incremental_and_bootstrap() -> None:
    from pathlib import Path

    files = [
        Path("infra/sql/0028_ths_paid_probability_v1.sql"),
        Path("infra/sql/bootstrap_schema.sql"),
    ]
    required = [
        "CREATE TABLE IF NOT EXISTS governance.ths_paid_probability_cookie_v1",
        "CREATE TABLE IF NOT EXISTS raw_ths.paid_limit_up_probability_v1",
        "CREATE TABLE IF NOT EXISTS source.ths_paid_limit_up_probability_v1",
        "CREATE TABLE IF NOT EXISTS governance.ths_paid_probability_batch_status_v1",
        "paid_limit_up_probability NUMERIC(12,6)",
        "ck_raw_ths_paid_probability_no_cookie_params_v1",
        "ck_raw_ths_paid_probability_no_cookie_payload_v1",
        "ck_ths_paid_limit_up_probability_range_v1",
        "abandoned_no_probability_before_deadline",
    ]
    for path in files:
        sql = path.read_text(encoding="utf-8")
        for snippet in required:
            assert snippet in sql


def test_postgres_source_mapping_uses_index_code_physical_key() -> None:
    columns = [
        "index_code",
        "trade_date",
        "close_price",
        "pct_chg",
        "source_quality_status",
        "primary_provider",
        "build_batch_id",
        "captured_at",
        "available_at",
    ]
    row = SourceCanonicalRowOut(
        source_table_name="source.index_daily_bar_v1",
        source_pk="399006.SZ|2026-06-12",
        symbol="399006.SZ",
        trade_date=date(2026, 6, 12),
        values={"close_price": 3830.35, "pct_chg": -0.32},
        source_quality_status=QualityStatus.USABLE,
        primary_provider=Provider.TENCENT,
        build_batch_id="source_build_test",
        captured_at=datetime(2026, 6, 13, tzinfo=timezone.utc),
        available_at=datetime(2026, 6, 13, tzinfo=timezone.utc),
        updated_at=datetime(2026, 6, 13, tzinfo=timezone.utc),
    )
    payload, key_cols = _source_payload_and_key(row, columns)
    assert payload["index_code"] == "399006.SZ"
    assert "symbol" not in [c for c in columns if c in payload]
    assert key_cols == ["index_code", "trade_date"]
    source_pk, symbol, trade_date_value = _source_identity_from_record(
        "source.index_daily_bar_v1",
        {"index_code": "399006.SZ", "trade_date": date(2026, 6, 12), "close_price": 3830.35},
    )
    assert source_pk == "399006.SZ|2026-06-12"
    assert symbol == "399006.SZ"
    assert trade_date_value == date(2026, 6, 12)


def test_postgres_source_mapping_supports_current_trade_calendar_on_legacy_physical_table() -> None:
    captured = datetime(2026, 6, 12, 7, 30, tzinfo=timezone.utc)
    row = SourceCanonicalRowOut(
        source_table_name="source.trade_calendar_v1",
        source_pk="2026-06-12",
        symbol=None,
        trade_date=date(2026, 6, 12),
        values={
            "calendar_date": date(2026, 6, 12),
            "is_trading_day": True,
            "pretrade_date": date(2026, 6, 11),
        },
        source_quality_status=QualityStatus.USABLE,
        primary_provider=Provider.BAOSTOCK,
        build_batch_id="build_calendar_20260612",
        captured_at=captured,
        available_at=captured,
        updated_at=captured,
    )
    payload, key_cols = _source_payload_and_key(
        row,
        [
            "trading_day",
            "market_code",
            "is_open",
            "prev_trading_day",
            "calendar_date",
            "is_trading_day",
            "exchange",
            "pretrade_date",
            "source_quality_status",
            "primary_provider",
            "build_batch_id",
            "captured_at",
            "available_at",
        ],
    )
    assert key_cols == ["trading_day", "market_code"]
    assert payload["calendar_date"] == date(2026, 6, 12)
    assert payload["trading_day"] == date(2026, 6, 12)
    assert payload["is_trading_day"] is True
    assert payload["is_open"] is True
    assert payload["pretrade_date"] == date(2026, 6, 11)
    assert payload["prev_trading_day"] == date(2026, 6, 11)
    assert payload["market_code"] == "CN_A"
    assert payload["exchange"] == "SSE_SZSE"


def test_source_lineage_identity_is_logical_and_stable() -> None:
    lineage = SourceLineageRecordOut(
        lineage_id="lineage_random_a",
        source_table_name="source.adjusted_daily_bar_v1",
        source_pk="000063.SZ|2026-06-12",
        canonical_field_name="adjusted_close",
        provider=Provider.BAOSTOCK,
        api_name="query_history_k_data_plus_daily_qfq",
        raw_table_name="raw_baostock.query_history_k_data_plus_daily_qfq_v1",
        raw_id="11",
        request_hash="request_hash_a",
        response_row_hash="response_row_hash_a",
        build_batch_id="source_build_a",
        confidence_score=1.0,
        created_at=datetime(2026, 6, 14, tzinfo=timezone.utc),
    )
    repeated = lineage.model_copy(update={"lineage_id": "lineage_random_b", "build_batch_id": "source_build_b"})
    changed_field = lineage.model_copy(update={"canonical_field_name": "adjusted_open"})

    assert _source_lineage_identity(lineage) == _source_lineage_identity(repeated)
    assert _source_lineage_identity(lineage) != _source_lineage_identity(changed_field)
    assert "source_build_a" not in _source_lineage_lock_key(_source_lineage_identity(lineage))
    assert "lineage_random_a" not in _source_lineage_lock_key(_source_lineage_identity(lineage))


def test_postgres_raw_row_identity_filter_uses_provider_code_when_symbol_column_is_missing() -> None:
    target_request = {"code": "sz.000002", "start_date": "2026-06-12", "end_date": "2026-06-12"}
    other_request = {"code": "sz.000025", "start_date": "2026-06-12", "end_date": "2026-06-12"}
    row = {"date": "2026-06-12", "code": "sz.000002", "close": "8.10"}
    other_row = {"date": "2026-06-12", "code": "sz.000025", "close": "12.34"}

    raw_symbol = _pg_normalize_symbol(_pg_extract_code(row, target_request))
    raw_trade_date = _pg_extract_trade_date(row, target_request)
    other_symbol = _pg_normalize_symbol(_pg_extract_code(other_row, other_request))
    other_trade_date = _pg_extract_trade_date(other_row, other_request)

    assert _raw_row_matches_requested_identity(raw_symbol, raw_trade_date, "000002.SZ", _date_or_none("2026-06-12"))
    assert not _raw_row_matches_requested_identity(other_symbol, other_trade_date, "000002.SZ", _date_or_none("2026-06-12"))


def test_tencent_symbol_extraction_prefers_canonical_symbol_over_short_code() -> None:
    row = {
        "code": "000001",
        "provider_code": "sh000001",
        "symbol": "000001.SH",
        "date": "2026-06-12",
    }
    assert _extract_symbol(row, {"provider_code": "sh000001"}) == "000001.SH"
    assert _extract_symbol({"code": "000001"}, {"provider_code": "sh000001"}) == "000001.SH"
    assert _extract_symbol({}, {"provider_code": "sh000001"}) == "000001.SH"


def test_postgres_source_mapping_uses_legacy_daily_bar_unique_key() -> None:
    row = SourceCanonicalRowOut(
        source_table_name="source.daily_bar_v1",
        source_pk="000063.SZ|2026-06-12",
        symbol="000063.SZ",
        trade_date=date(2026, 6, 12),
        values={"open_price": 38.6, "high_price": 38.7, "low_price": 36.15, "close_price": 36.35},
        source_quality_status=QualityStatus.USABLE,
        primary_provider=Provider.TENCENT,
        build_batch_id="source_build_test",
        captured_at=datetime(2026, 6, 13, tzinfo=timezone.utc),
        available_at=datetime(2026, 6, 13, tzinfo=timezone.utc),
        updated_at=datetime(2026, 6, 13, tzinfo=timezone.utc),
    )
    payload, key_cols = _source_payload_and_key(
        row,
        [
            "source_daily_bar_id",
            "instrument_id",
            "symbol",
            "trading_day",
            "adjustment",
            "open_price",
            "high_price",
            "low_price",
            "close_price",
            "event_time",
            "available_at",
            "captured_at",
            "provider",
            "quality_status",
            "trade_date",
            "source_quality_status",
            "primary_provider",
            "build_batch_id",
        ],
        instrument_id=9476,
    )
    assert key_cols == ["instrument_id", "trading_day", "adjustment", "provider"]
    assert payload["instrument_id"] == 9476
    assert payload["trading_day"] == date(2026, 6, 12)
    assert payload["trade_date"] == date(2026, 6, 12)
    assert payload["adjustment"] == "raw"
    assert payload["provider"] == "tencent"
    assert payload["event_time"].hour == 15
    source_pk, symbol, trade_date_value = _source_identity_from_record(
        "source.daily_bar_v1",
        {"symbol": "000063.SZ", "trading_day": date(2026, 6, 12), "close_price": 36.35},
    )
    assert source_pk == "000063.SZ|2026-06-12"
    assert symbol == "000063.SZ"
    assert trade_date_value == date(2026, 6, 12)


def test_postgres_source_mapping_keeps_moneyflow_canonical_columns() -> None:
    columns = [
        "symbol",
        "trade_date",
        "main_net_inflow",
        "super_large_net_inflow",
        "large_net_inflow",
        "medium_net_inflow",
        "small_net_inflow",
        "provider_definition",
        "source_quality_status",
        "primary_provider",
        "backup_provider",
        "build_batch_id",
        "captured_at",
        "available_at",
    ]
    row = SourceCanonicalRowOut(
        source_table_name="source.stock_moneyflow_daily_v1",
        source_pk="000759.SZ|2026-06-12",
        symbol="000759.SZ",
        trade_date=date(2026, 6, 12),
        values={
            "main_net_inflow": 123456.78,
            "super_large_net_inflow": 20000,
            "large_net_inflow": 30000,
            "medium_net_inflow": 40000,
            "small_net_inflow": -10000,
            "provider_definition": "eastmoney_fflow_kline_get",
        },
        source_quality_status=QualityStatus.USABLE,
        primary_provider=Provider.EASTMONEY,
        build_batch_id="source_build_moneyflow",
        captured_at=datetime(2026, 6, 13, tzinfo=timezone.utc),
        available_at=datetime(2026, 6, 13, tzinfo=timezone.utc),
        updated_at=datetime(2026, 6, 13, tzinfo=timezone.utc),
    )
    payload, key_cols = _source_payload_and_key(row, columns)
    assert key_cols == ["symbol", "trade_date", "primary_provider"]
    assert payload["main_net_inflow"] == 123456.78
    assert payload["primary_provider"] == "eastmoney"
    assert payload["provider_definition"] == "eastmoney_fflow_kline_get"


def test_postgres_source_mapping_uses_event_id_for_event_news() -> None:
    columns = [
        "event_id",
        "symbol",
        "title",
        "event_type",
        "event_time",
        "published_at",
        "available_at",
        "captured_at",
        "provider",
        "url",
        "source_quality_status",
        "lineage_id",
        "build_batch_id",
    ]
    row = SourceCanonicalRowOut(
        source_table_name="source.event_news_v1",
        source_pk="baidu:news_0001",
        symbol="000759.SZ",
        trade_date=None,
        values={
            "title": "sample title",
            "event_type": "finance_news",
            "published_at": "2026-06-14T01:00:00+00:00",
            "available_at": datetime(2026, 6, 14, 1, 1, tzinfo=timezone.utc),
            "url": "https://example.test/news",
        },
        source_quality_status=QualityStatus.RESEARCH_ONLY,
        primary_provider=Provider.BAIDU,
        build_batch_id="source_build_news",
        captured_at=datetime(2026, 6, 14, 1, 1, tzinfo=timezone.utc),
        available_at=datetime(2026, 6, 14, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 6, 14, 1, 2, tzinfo=timezone.utc),
    )
    payload, key_cols = _source_payload_and_key(row, columns)
    assert key_cols == ["event_id"]
    assert payload["event_id"] == "baidu:news_0001"
    assert payload["provider"] == "baidu"
    assert payload["title"] == "sample title"
    source_pk, symbol, trade_date_value = _source_identity_from_record(
        "source.event_news_v1",
        {"event_id": "baidu:news_0001", "symbol": "000759.SZ", "title": "sample title"},
    )
    assert source_pk == "baidu:news_0001"
    assert symbol == "000759.SZ"
    assert trade_date_value is None


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


def test_probe_marks_baidu_event_news_as_research_only(monkeypatch) -> None:
    from source_data_service import probe as probe_module

    def fake_execute_provider_fetch(provider, api_name, params, dry_run=False):
        assert provider == Provider.BAIDU
        assert api_name == "finance_news_feed"
        return RawFetchResult(
            provider=Provider.BAIDU,
            api_name="finance_news_feed",
            raw_table_name="raw_baidu.finance_news_feed_v1",
            request_params=params,
            dry_run=dry_run,
            row_count=1,
            rows=[
                RawRow(
                    provider=Provider.BAIDU,
                    api_name="finance_news_feed",
                    raw_table_name="raw_baidu.finance_news_feed_v1",
                    request_params=params,
                    row={
                        "provider_news_id": "baidu_news_1",
                        "title": "sample",
                        "source_name": "BAIDU",
                        "published_at": "2026-06-14T01:00:00+00:00",
                        "available_at": "2026-06-14T01:01:00+00:00",
                        "event_type": "finance_news",
                        "url": "https://finance.baidu.com/news/1",
                        "symbol": "000759.SZ",
                        "tags_json": {},
                        "stock_refs_json": [],
                    },
                )
            ],
        )

    monkeypatch.setattr(probe_module, "execute_provider_fetch", fake_execute_provider_fetch)
    client = TestClient(app)
    resp = client.post(
        "/source/probe",
        json={
            "provider": "baidu",
            "api_name": "finance_news_feed",
            "sample_params": {"rn": 1, "pn": 0, "type": "all", "tag": "all"},
            "dry_run": False,
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["usable_for_source_table"] is True
    assert payload["usable_for_model_online"] is False
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


def test_legacy_market_provider_contracts_are_registered_with_partial_adapter_migration() -> None:
    specs = list_api_specs()
    names = {(item.provider.value, item.api_name) for item in specs}
    assert ("eastmoney", "daily_bars") in names
    assert ("eastmoney", "moneyflow_stock_series") in names
    assert ("eastmoney", "quote_snapshot") in names
    assert ("tencent", "auction_snapshot") in names
    client = TestClient(app)
    rows = client.get("/source/providers/status?provider=eastmoney").json()
    assert rows
    status_by_api = {row["api_name"]: row for row in rows}
    assert status_by_api["moneyflow_stock_series"]["adapter_implemented"] is True
    assert status_by_api["daily_bars"]["adapter_implemented"] is True
    assert status_by_api["quote_snapshot"]["adapter_implemented"] is True
    assert status_by_api["minute_bars"]["adapter_implemented"] is True
    assert status_by_api["trade_details"]["adapter_implemented"] is True
    from source_data_service.adapters import get_adapter

    dry_run = get_adapter(Provider.EASTMONEY).fetch("moneyflow_stock_series", {"secid": "0.000759"}, dry_run=True)
    assert dry_run.raw_table_name == "raw_eastmoney.moneyflow_stock_series_v1"
    assert dry_run.dry_run is True


def test_t_board_relay_source_contracts_are_registered() -> None:
    requirements = list_source_requirements()
    by_key = {(item.source_table_name, item.canonical_field_name): item for item in requirements}

    assert ("source.limit_price_v1", "up_limit_price") in by_key
    assert ("source.limit_event_v1", "limit_event_type") in by_key
    assert ("source.realtime_quote_v1", "float_market_cap") in by_key
    assert ("source.minute_bar_v1", "close_price") in by_key
    assert ("source.trade_tick_v1", "side_code") in by_key
    assert "t_board_relay" in by_key[("source.trade_tick_v1", "side_code")].used_by_models

    trade_spec = get_api_spec(Provider.EASTMONEY, "trade_details")
    assert trade_spec.raw_table_name == "raw_eastmoney.trade_details_v1"
    assert "source.trade_tick_v1" in trade_spec.canonical_targets


def test_auction_snapshot_source_contracts_and_build_mapping_are_registered() -> None:
    requirements = list_source_requirements("source.auction_snapshot_v1")
    by_field = {item.canonical_field_name: item for item in requirements}

    assert set(by_field) == {"virtual_open_price", "matched_volume", "matched_amount", "event_time"}
    assert by_field["virtual_open_price"].required_level.value == "P1"
    assert by_field["virtual_open_price"].primary_provider == Provider.EASTMONEY
    assert by_field["virtual_open_price"].backup_provider == Provider.TENCENT

    values, warnings = _build_values(
        Provider.EASTMONEY,
        "auction_snapshot",
        "source.auction_snapshot_v1",
        {
            "symbol": "000759.SZ",
            "trade_date": "2026-06-12",
            "event_time": "2026-06-12T01:24:30+00:00",
            "price": "5.43",
            "volume": "120000",
            "amount": "651600",
            "provider_definition": "eastmoney_stock_get",
        },
        ["virtual_open_price", "matched_volume", "matched_amount", "snapshot_time", "event_time"],
    )

    assert warnings == []
    assert values == {
        "virtual_open_price": 5.43,
        "matched_volume": 120000.0,
        "matched_amount": 651600.0,
        "snapshot_time": "2026-06-12T01:24:30+00:00",
        "event_time": "2026-06-12T01:24:30+00:00",
    }


def test_auction_snapshot_fetch_plan_and_postgres_payload_contract() -> None:
    plan = build_fetch_plan(
        FetchPlanRequest(
            source_table_name="source.auction_snapshot_v1",
            canonical_fields=["virtual_open_price", "matched_volume", "matched_amount", "event_time"],
            symbols=["000759.SZ"],
            trade_date=date(2026, 6, 12),
            trigger_type=FetchTriggerType.MODEL_RELEASE_PREFLIGHT,
            priority=FetchPriority.P0_URGENT_RELEASE,
            request_source="scheduler-service",
            dry_run=True,
        )
    )
    assert plan.job_count == 1
    job = plan.jobs[0]
    assert job.provider == Provider.EASTMONEY
    assert job.api_name == "auction_snapshot"
    assert job.raw_table_name == "raw_eastmoney.auction_snapshot_v1"
    assert set(job.canonical_fields) == {"virtual_open_price", "matched_volume", "matched_amount", "event_time"}
    assert job.backup_plans
    assert job.backup_plans[0].provider == Provider.TENCENT

    row = SourceCanonicalRowOut(
        source_table_name="source.auction_snapshot_v1",
        source_pk="000759.SZ|2026-06-12T01:24:30+00:00|eastmoney",
        symbol="000759.SZ",
        trade_date=date(2026, 6, 12),
        values={
            "virtual_open_price": 5.43,
            "matched_volume": 120000.0,
            "matched_amount": 651600.0,
            "snapshot_time": "2026-06-12T01:24:30+00:00",
            "event_time": "2026-06-12T01:24:30+00:00",
        },
        source_quality_status=QualityStatus.USABLE,
        primary_provider=Provider.EASTMONEY,
        build_batch_id="build-auction-test",
        captured_at=datetime(2026, 6, 12, 1, 24, 31, tzinfo=timezone.utc),
        available_at=datetime(2026, 6, 12, 1, 24, 31, tzinfo=timezone.utc),
        updated_at=datetime(2026, 6, 12, 1, 24, 31, tzinfo=timezone.utc),
    )
    payload, key_cols = _source_payload_and_key(
        row,
        [
            "instrument_id",
            "symbol",
            "trading_day",
            "snapshot_time",
            "virtual_open_price",
            "matched_amount",
            "matched_volume",
            "event_time",
            "available_at",
            "captured_at",
            "provider",
            "quality_status",
        ],
        instrument_id=123,
    )

    assert key_cols == ["instrument_id", "trading_day", "snapshot_time", "provider"]
    assert payload["instrument_id"] == 123
    assert payload["trading_day"] == date(2026, 6, 12)
    assert payload["provider"] == "eastmoney"
    assert payload["quality_status"] == "usable"
    assert payload["virtual_open_price"] == 5.43
    assert payload["matched_volume"] == 120000.0
    assert payload["matched_amount"] == 651600.0


def test_source_build_derives_limit_price_and_event_from_real_daily_bar() -> None:
    daily_row = {
        "date": "2026-06-12",
        "code": "sz.000759",
        "open": "5.29",
        "high": "5.83",
        "low": "5.16",
        "close": "5.83",
        "preclose": "5.30",
        "pctChg": "10.0",
        "isST": "0",
    }

    limit_values, limit_warnings = _build_values(
        Provider.BAOSTOCK,
        "query_history_k_data_plus_daily_raw",
        "source.limit_price_v1",
        daily_row,
        [],
    )
    event_values, event_warnings = _build_values(
        Provider.BAOSTOCK,
        "query_history_k_data_plus_daily_raw",
        "source.limit_event_v1",
        daily_row,
        [],
    )

    assert limit_warnings == []
    assert limit_values["pre_close_price"] == 5.3
    assert limit_values["up_limit_price"] == 5.83
    assert limit_values["limit_rule"] == "normal_10pct"
    assert event_warnings == []
    assert event_values["limit_event_type"] == "t_board_limit_up"
    assert event_values["is_one_word_board"] is False
    assert event_values["is_break_limit"] is True
    assert event_values["close_on_limit_flag"] is True
    assert event_values["limit_open_count"] == 1


def test_limit_price_build_uses_previous_daily_close_when_raw_preclose_missing(monkeypatch) -> None:
    available = datetime(2026, 6, 23, 8, 0, tzinfo=timezone.utc)

    def fake_list_source_rows(source_table_name: str, symbol: str | None = None, trade_date: str | None = None):
        if source_table_name == "source.trade_calendar_v1":
            return [
                SourceCanonicalRowOut(
                    source_table_name="source.trade_calendar_v1",
                    source_pk="2026-06-23",
                    trade_date=date(2026, 6, 23),
                    values={"pretrade_date": "2026-06-22"},
                    source_quality_status=QualityStatus.USABLE,
                    primary_provider=Provider.BAOSTOCK,
                    build_batch_id="build-calendar-test",
                    available_at=available,
                    updated_at=available,
                )
            ]
        if source_table_name == "source.daily_bar_v1" and symbol == "301580.SZ" and trade_date == "2026-06-22":
            return [
                SourceCanonicalRowOut(
                    source_table_name="source.daily_bar_v1",
                    source_pk="301580.SZ|2026-06-22",
                    symbol="301580.SZ",
                    trade_date=date(2026, 6, 22),
                    values={"close_price": 75.8},
                    source_quality_status=QualityStatus.USABLE,
                    primary_provider=Provider.BAOSTOCK,
                    build_batch_id="build-daily-test",
                    available_at=available,
                    updated_at=available,
                )
            ]
        return []

    monkeypatch.setattr(source_repository, "list_source_rows", fake_list_source_rows)
    row = source_repository._with_limit_price_preclose_source(
        {"symbol": "301580.SZ", "date": "2026-06-23", "close": "90.96"},
        "301580.SZ",
        "2026-06-23",
    )
    values, warnings = _build_values(
        Provider.TENCENT,
        "daily_bars",
        "source.limit_price_v1",
        row,
        ["up_limit_price"],
    )

    assert values == {
        "pre_close_price": 75.8,
        "up_limit_price": 90.96,
        "down_limit_price": 60.64,
        "limit_rule": "registration_20pct",
    }
    assert any("source.daily_bar_v1.close_price" in item for item in warnings)


def test_source_build_uses_trigger_table_fields_when_raw_job_is_reused() -> None:
    class ReusedJob:
        source_table_name = "source.limit_price_v1"
        canonical_fields = ["pre_close_price", "up_limit_price", "down_limit_price", "limit_rule"]

    fields = _canonical_fields_for_source_build(ReusedJob(), "source.limit_event_v1")

    assert {"limit_event_type", "is_one_word_board", "is_break_limit"} <= set(fields)
    assert "up_limit_price" not in fields


def test_source_build_expands_daily_bar_single_field_repair_to_full_physical_row() -> None:
    values, warnings = _build_values(
        Provider.BAOSTOCK,
        "query_history_k_data_plus_daily_raw",
        "source.daily_bar_v1",
        {
            "date": "2026-06-11",
            "code": "sz.000063",
            "open": "37.100000",
            "high": "38.200000",
            "low": "36.950000",
            "close": "37.810000",
            "preclose": "36.500000",
            "volume": "12345678",
            "amount": "456789012.34",
            "pctChg": "3.589041",
            "turn": "2.340000",
        },
        ["close_price"],
    )

    assert warnings == []
    assert values["open_price"] == 37.1
    assert values["high_price"] == 38.2
    assert values["low_price"] == 36.95
    assert values["close_price"] == 37.81
    assert values["pre_close_price"] == 36.5
    assert values["volume"] == 12345678.0
    assert values["amount"] == 456789012.34


def test_postgres_limit_event_mapping_uses_physical_primary_key() -> None:
    captured = datetime(2026, 6, 12, 7, 30, tzinfo=timezone.utc)
    row = SourceCanonicalRowOut(
        source_table_name="source.limit_event_v1",
        source_pk="000759.SZ|2026-06-12|t_board_limit_up",
        symbol="000759.SZ",
        trade_date=date(2026, 6, 12),
        values={
            "limit_event_type": "t_board_limit_up",
            "is_one_word_board": False,
            "is_break_limit": True,
        },
        source_quality_status=QualityStatus.USABLE,
        primary_provider=Provider.BAOSTOCK,
        build_batch_id="source_build_limit_event",
        captured_at=captured,
        available_at=captured,
        updated_at=captured,
    )
    payload, key_cols = _source_payload_and_key(
        row,
        [
            "symbol",
            "trade_date",
            "limit_event_type",
            "is_one_word_board",
            "is_break_limit",
            "source_quality_status",
            "primary_provider",
            "build_batch_id",
            "captured_at",
            "available_at",
        ],
    )

    assert key_cols == ["symbol", "trade_date", "limit_event_type"]
    source_pk, symbol, trade_date = _source_identity_from_record("source.limit_event_v1", payload)
    assert source_pk == "000759.SZ|2026-06-12|t_board_limit_up"
    assert symbol == "000759.SZ"
    assert trade_date == date(2026, 6, 12)


def test_postgres_source_mapping_supports_intraday_quote_minute_and_tick() -> None:
    captured = datetime(2026, 6, 12, 7, 30, tzinfo=timezone.utc)
    minute_row = SourceCanonicalRowOut(
        source_table_name="source.minute_bar_v1",
        source_pk="000759.SZ|2026-06-12T10:30:00+08:00",
        symbol="000759.SZ",
        trade_date=date(2026, 6, 12),
        values={
            "bar_time": "2026-06-12T10:30:00+08:00",
            "event_time": "2026-06-12T10:30:00+08:00",
            "open_price": 5.83,
            "high_price": 5.83,
            "low_price": 5.83,
            "close_price": 5.83,
        },
        source_quality_status=QualityStatus.USABLE,
        primary_provider=Provider.EASTMONEY,
        build_batch_id="source_build_intraday",
        captured_at=captured,
        available_at=captured,
        updated_at=captured,
    )
    minute_payload, minute_keys = _source_payload_and_key(
        minute_row,
        ["instrument_id", "symbol", "bar_time", "open_price", "high_price", "low_price", "close_price", "event_time", "available_at", "captured_at", "provider", "quality_status"],
        instrument_id=1001,
    )
    assert minute_keys == ["instrument_id", "bar_time", "provider"]
    assert minute_payload["provider"] == "eastmoney"
    assert minute_payload["bar_time"].isoformat() == "2026-06-12T10:30:00+08:00"

    quote_row = SourceCanonicalRowOut(
        source_table_name="source.realtime_quote_v1",
        source_pk="000759.SZ|2026-06-12T15:00:00+08:00",
        symbol="000759.SZ",
        trade_date=date(2026, 6, 12),
        values={"event_time": "2026-06-12T15:00:00+08:00", "latest_price": 5.83, "float_market_cap": 3822766125.75},
        source_quality_status=QualityStatus.USABLE,
        primary_provider=Provider.EASTMONEY,
        build_batch_id="source_build_quote",
        captured_at=captured,
        available_at=captured,
        updated_at=captured,
    )
    quote_payload, quote_keys = _source_payload_and_key(
        quote_row,
        ["instrument_id", "symbol", "latest_price", "event_time", "available_at", "captured_at", "provider", "quality_status", "float_market_cap"],
        instrument_id=1001,
    )
    assert quote_keys == ["instrument_id", "event_time", "provider"]
    assert quote_payload["latest_price"] == 5.83
    assert quote_payload["float_market_cap"] == 3822766125.75

    tick_row = SourceCanonicalRowOut(
        source_table_name="source.trade_tick_v1",
        source_pk="000759.SZ|2026-06-12T15:00:00+08:00|4041",
        symbol="000759.SZ",
        trade_date=date(2026, 6, 12),
        values={"tick_time": "2026-06-12T15:00:00+08:00", "price": 5.83, "side_code": "1", "provider_sequence": 4041},
        source_quality_status=QualityStatus.USABLE,
        primary_provider=Provider.EASTMONEY,
        build_batch_id="source_build_tick",
        captured_at=captured,
        available_at=captured,
        updated_at=captured,
    )
    tick_payload, tick_keys = _source_payload_and_key(
        tick_row,
        ["symbol", "trade_date", "tick_time", "price", "side_code", "provider_sequence", "provider", "source_quality_status"],
    )
    assert tick_keys == ["symbol", "tick_time", "provider", "provider_sequence"]
    assert tick_payload["provider"] == "eastmoney"


def test_baidu_finance_news_adapter_parses_public_feed(monkeypatch) -> None:
    import requests

    from source_data_service.adapters import get_adapter

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {
                "ResultCode": 0,
                "Result": {
                    "tabs": [
                        {
                            "type": "all",
                            "text": "全部",
                            "contents": [
                                {
                                    "news_id": "baidu_news_1",
                                    "title": "样例财经新闻",
                                    "source": "财联社",
                                    "publish_time": "1781398800",
                                    "third_url": "https://finance.baidu.com/news/1",
                                    "st_tags_arr": ["000759", "not_stock"],
                                    "queue": ["finance"],
                                    "feed_weight": 0.8,
                                    "bucket": "sample",
                                    "sort_trace": "trace",
                                }
                            ],
                        }
                    ]
                },
            }

    def fake_get(url, params, headers, timeout):
        assert url == "https://finance.pae.baidu.com/selfselect/news"
        assert params["rn"] == 5
        assert headers["Referer"] == "https://finance.baidu.com/"
        assert timeout == 15
        return FakeResponse()

    monkeypatch.setattr(requests, "get", fake_get)
    result = get_adapter(Provider.BAIDU).fetch(
        "finance_news_feed",
        {"rn": 5, "pn": 0, "type": "all", "tag": "all"},
        dry_run=False,
    )
    assert result.row_count == 1
    row = result.rows[0].row
    assert row["provider_news_id"] == "baidu_news_1"
    assert row["title"] == "样例财经新闻"
    assert row["symbol"] == "000759.SZ"
    assert row["event_type"] == "finance_news"
    assert row["stock_refs_json"][0]["exchange"] == "SZ"
    assert row["published_at"].startswith("2026-06-14T")


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
        ("source.index_daily_bar_v1", "open_price"),
        ("source.index_daily_bar_v1", "high_price"),
        ("source.index_daily_bar_v1", "low_price"),
        ("source.index_daily_bar_v1", "close_price"),
        ("source.index_daily_bar_v1", "volume"),
        ("source.index_daily_bar_v1", "amount"),
        ("source.stock_moneyflow_daily_v1", "main_net_inflow"),
        ("source.stock_moneyflow_daily_v1", "provider_definition"),
    }
    assert required <= names
    moneyflow = next(item for item in contracts if item.source_table_name == "source.stock_moneyflow_daily_v1" and item.canonical_field_name == "main_net_inflow")
    assert moneyflow.primary_provider == Provider.EASTMONEY
    assert moneyflow.primary_api_name == "moneyflow_stock_series"
    assert moneyflow.online_policy == "degradable"
    p0_online = [item for item in contracts if item.required_level.value == "P0" and item.online_policy == "required"]
    assert p0_online
    assert all(
        item.backup_provider is not None
        for item in p0_online
        if item.primary_provider.value != "internal"
        and not (
            item.source_table_name == "source.ths_paid_limit_up_probability_v1"
            and item.primary_api_name == "paid_limit_up_probability"
        )
    )
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


def test_raw_quality_validation_allows_valid_tencent_daily_row() -> None:
    client = TestClient(app)
    resp = client.post(
        "/source/quality/validate-raw",
        json={
            "provider": "tencent",
            "api_name": "daily_bars",
            "rows": [
                {
                    "date": "2026-06-12",
                    "code": "000063",
                    "provider_code": "sz000063",
                    "symbol": "000063.SZ",
                    "open": "38.600",
                    "close": "36.350",
                    "high": "38.700",
                    "low": "36.150",
                    "volume": "2614711.000",
                    "amount": "9702654430",
                    "adjustment_mode": "qfq",
                    "period": "day",
                    "pct_chg": "-5.04",
                }
            ],
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["build_allowed"] is True
    assert payload["error_count"] == 0


def _raw_fetch_result(provider: Provider, api_name: str, raw_table_name: str, params: dict[str, object], rows: list[dict[str, object]]) -> RawFetchResult:
    return RawFetchResult(
        provider=provider,
        api_name=api_name,
        raw_table_name=raw_table_name,
        request_params=params,
        dry_run=False,
        row_count=len(rows),
        rows=[
            RawRow(
                provider=provider,
                api_name=api_name,
                raw_table_name=raw_table_name,
                request_params=params,
                row=row,
            )
            for row in rows
        ],
    )


def test_sohu_daily_jsonp_parser_normalizes_amount_and_pct() -> None:
    from source_data_service.adapters import sohu_adapter

    payload = (
        'historySearchHandler([{"status":0,"hq":[["2026-06-12","38.60","36.35",'
        '"-1.46","-3.86%","36.15","38.70","2614711","970265.38","6.49%"]],'
        '"code":"cn_000063"}])'
    )
    rows = sohu_adapter._parse_jsonp(payload)
    monkey_rows = [{"status": item["status"], "hq": item["hq"], "code": item["code"]} for item in rows]
    assert monkey_rows[0]["code"] == "cn_000063"

    # Exercise the public row normalization contract without making a network call.
    original = sohu_adapter._request_daily_payload
    try:
        sohu_adapter._request_daily_payload = lambda _params: rows  # type: ignore[assignment]
        normalized = sohu_adapter._sohu_daily_rows({"provider_code": "cn_000063", "start_date": "20260612", "end_date": "20260612"})
    finally:
        sohu_adapter._request_daily_payload = original  # type: ignore[assignment]
    assert normalized == [
        {
            "date": "2026-06-12",
            "code": "000063",
            "provider_code": "cn_000063",
            "symbol": "000063.SZ",
            "open": "38.60",
            "close": "36.35",
            "change": "-1.46",
            "pct_chg": "-3.86",
            "low": "36.15",
            "high": "38.70",
            "volume": "261471100",
            "amount": "9702653800",
            "turnover_rate": "6.49",
            "adjustment_mode": "raw",
            "period": "day",
            "provider_definition": "sohu.hisHq:date,open,close,change,pct_chg,low,high,volume_hands,amount_wan_yuan,turnover_rate",
        }
    ]


def test_tencent_daily_rows_do_not_copy_current_quote_into_historical_amount_or_pct(monkeypatch) -> None:
    from source_data_service.adapters import tencent_adapter

    def fake_request_json(_url, _params):
        return {
            "code": 0,
            "data": {
                "sz000063": {
                    "day": [["2026-06-12", "38.600", "36.350", "38.700", "36.150", "2614711.000"]],
                    "qt": {"sz000063": [""] * 30 + ["20260615153933", "", "2.39", "", "", "37.22/1734932/6385605445"]},
                }
            },
        }

    monkeypatch.setattr(tencent_adapter, "_request_json", fake_request_json)
    rows = tencent_adapter._tencent_daily_rows(
        {
            "provider_code": "sz000063",
            "period": "day",
            "start_date": "2026-06-12",
            "end_date": "2026-06-12",
            "adjustment": "raw",
        }
    )
    assert rows[0]["amount"] is None
    assert rows[0]["pct_chg"] is None


def test_multi_source_quality_check_passes_baostock_tencent_sohu_daily_with_field_level_backups(monkeypatch) -> None:
    from source_data_service import multi_source_quality

    def fake_execute_provider_fetch(*, provider, api_name, params, dry_run=False):
        assert dry_run is False
        if provider == Provider.BAOSTOCK:
            return _raw_fetch_result(
                provider,
                api_name,
                "raw_baostock.query_history_k_data_plus_daily_raw_v1",
                params,
                [
                    {
                        "date": "2026-06-12",
                        "code": "sz.000063",
                        "open": "38.60",
                        "high": "38.70",
                        "low": "36.15",
                        "close": "36.35",
                        "preclose": "38.28",
                        "volume": "261471100",
                        "amount": "9702654430",
                        "adjustflag": "3",
                        "turn": "4.1",
                        "tradestatus": "1",
                        "pctChg": "-5.04",
                        "isST": "0",
                    }
                ],
            )
        if provider == Provider.TENCENT:
            return _raw_fetch_result(
                provider,
                api_name,
                "raw_tencent.daily_bars_v1",
                params,
                [
                    {
                        "date": "2026-06-12",
                        "code": "000063",
                        "provider_code": "sz000063",
                        "symbol": "000063.SZ",
                        "open": "38.600",
                        "close": "36.350",
                        "high": "38.700",
                        "low": "36.150",
                        "volume": "2614711.000",
                        "amount": None,
                        "adjustment_mode": "raw",
                        "period": "day",
                        "pct_chg": None,
                    }
                ],
            )
        return _raw_fetch_result(
            provider,
            api_name,
            "raw_sohu.daily_bars_v1",
            params,
            [
                {
                    "date": "2026-06-12",
                    "code": "000063",
                    "provider_code": "cn_000063",
                    "symbol": "000063.SZ",
                    "open": "38.600",
                    "close": "36.350",
                    "high": "38.700",
                    "low": "36.150",
                    "volume": "261471100",
                    "amount": "9702654430",
                    "turnover_rate": "4.1",
                    "adjustment_mode": "raw",
                    "period": "day",
                    "pct_chg": "-5.04",
                }
            ],
        )

    monkeypatch.setattr(multi_source_quality, "execute_provider_fetch", fake_execute_provider_fetch)

    client = TestClient(app)
    resp = client.post(
        "/source/quality/multi-source/check",
        json={
            "source_table_name": "source.daily_bar_v1",
            "canonical_fields": ["open_price", "close_price", "volume", "amount", "pct_chg"],
            "symbol": "000063.SZ",
            "trade_date": "2026-06-12",
            "include_backup": True,
            "dry_run": False,
        },
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "passed"
    assert payload["usable_provider_count"] == 3
    assert payload["blocked_field_count"] == 0
    providers = {item["provider"]: item for item in payload["provider_evidence"]}
    assert providers["baostock"]["target_row_found"] is True
    assert providers["tencent"]["target_row_found"] is True
    assert providers["sohu"]["target_row_found"] is True
    volume = next(item for item in payload["comparisons"] if item["canonical_field_name"] == "volume")
    assert volume["baseline_value"] == "261471100"
    assert volume["compared_value"] == "261471100"
    assert volume["status"] == "passed"
    amount = next(item for item in payload["comparisons"] if item["canonical_field_name"] == "amount")
    assert amount["compared_provider"] == "sohu"
    assert amount["status"] == "passed"
    pct_chg = next(item for item in payload["comparisons"] if item["canonical_field_name"] == "pct_chg")
    assert pct_chg["compared_provider"] == "sohu"
    assert pct_chg["status"] == "passed"


def test_multi_source_quality_check_blocks_when_target_date_row_missing(monkeypatch) -> None:
    from source_data_service import multi_source_quality

    def fake_execute_provider_fetch(*, provider, api_name, params, dry_run=False):
        if provider == Provider.BAOSTOCK:
            return _raw_fetch_result(
                provider,
                api_name,
                "raw_baostock.query_history_k_data_plus_daily_raw_v1",
                params,
                [
                    {
                        "date": "2026-06-11",
                        "code": "sz.000063",
                        "open": "38.60",
                        "high": "38.70",
                        "low": "36.15",
                        "close": "36.35",
                        "volume": "1",
                        "amount": "1",
                    }
                ],
            )
        return _raw_fetch_result(
            provider,
            api_name,
            "raw_tencent.daily_bars_v1",
            params,
            [
                {
                    "date": "2026-06-12",
                    "code": "000063",
                    "provider_code": "sz000063",
                    "symbol": "000063.SZ",
                    "open": "38.60",
                    "close": "36.35",
                    "high": "38.70",
                    "low": "36.15",
                    "volume": "1",
                    "amount": "1",
                    "adjustment_mode": "raw",
                    "period": "day",
                }
            ],
        )

    monkeypatch.setattr(multi_source_quality, "execute_provider_fetch", fake_execute_provider_fetch)

    client = TestClient(app)
    resp = client.post(
        "/source/quality/multi-source/check",
        json={
            "source_table_name": "source.daily_bar_v1",
            "canonical_fields": ["close_price"],
            "symbol": "000063.SZ",
            "trade_date": "2026-06-12",
            "include_backup": True,
            "dry_run": False,
        },
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "blocked"
    assert payload["usable_provider_count"] == 1
    assert payload["provider_evidence"][0]["target_row_found"] is False
    assert "target symbol/trade_date row not found" in payload["provider_evidence"][0]["warning"]
    assert payload["blocking_reasons"] == ["close_price:fewer than two usable provider results"]


def test_multi_source_quality_check_blocks_provider_price_divergence(monkeypatch) -> None:
    from source_data_service import multi_source_quality

    def fake_execute_provider_fetch(*, provider, api_name, params, dry_run=False):
        close = "36.35" if provider == Provider.BAOSTOCK else "37.10"
        if provider == Provider.BAOSTOCK:
            return _raw_fetch_result(
                provider,
                api_name,
                "raw_baostock.query_history_k_data_plus_daily_raw_v1",
                params,
                [
                    {
                        "date": "2026-06-12",
                        "code": "sz.000063",
                        "open": "38.60",
                        "high": "38.70",
                        "low": "36.15",
                        "close": close,
                        "volume": "261471100",
                        "amount": "9702654430",
                    }
                ],
            )
        return _raw_fetch_result(
            provider,
            api_name,
            "raw_tencent.daily_bars_v1",
            params,
            [
                {
                    "date": "2026-06-12",
                    "code": "000063",
                    "provider_code": "sz000063",
                    "symbol": "000063.SZ",
                    "open": "38.60",
                    "close": close,
                    "high": "38.70",
                    "low": "36.15",
                    "volume": "2614711",
                    "amount": "9702654430",
                    "adjustment_mode": "raw",
                    "period": "day",
                }
            ],
        )

    monkeypatch.setattr(multi_source_quality, "execute_provider_fetch", fake_execute_provider_fetch)

    client = TestClient(app)
    resp = client.post(
        "/source/quality/multi-source/check",
        json={
            "source_table_name": "source.daily_bar_v1",
            "canonical_fields": ["close_price"],
            "symbol": "000063.SZ",
            "trade_date": "2026-06-12",
            "include_backup": True,
            "dry_run": False,
        },
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "blocked"
    assert payload["blocked_field_count"] == 1
    comparison = payload["comparisons"][0]
    assert comparison["canonical_field_name"] == "close_price"
    assert comparison["absolute_diff"] == "0.75"
    assert comparison["reason"] == "provider values diverged beyond tolerance"


def test_multi_source_quality_check_passes_tencent_baostock_index_daily(monkeypatch) -> None:
    from source_data_service import multi_source_quality

    def fake_execute_provider_fetch(*, provider, api_name, params, dry_run=False):
        if provider == Provider.TENCENT:
            return _raw_fetch_result(
                provider,
                api_name,
                "raw_tencent.daily_bars_v1",
                params,
                [
                    {
                        "date": "2026-06-12",
                        "code": "399006",
                        "provider_code": "sz399006",
                        "symbol": "399006.SZ",
                        "open": "3837.440",
                        "close": "3834.700",
                        "high": "3849.520",
                        "low": "3808.150",
                        "volume": "213802842.000",
                        "amount": "338252175171",
                        "adjustment_mode": "raw",
                        "period": "day",
                        "pct_chg": "-0.34",
                    }
                ],
            )
        return _raw_fetch_result(
            provider,
            api_name,
            "raw_baostock.query_history_k_data_plus_daily_raw_v1",
            params,
            [
                {
                    "date": "2026-06-12",
                    "code": "sz.399006",
                    "open": "3837.44",
                    "high": "3849.52",
                    "low": "3808.15",
                    "close": "3834.70",
                    "preclose": "3847.78",
                    "volume": "21380284200",
                    "amount": "338252175171",
                    "pctChg": "-0.34",
                }
            ],
        )

    monkeypatch.setattr(multi_source_quality, "execute_provider_fetch", fake_execute_provider_fetch)

    client = TestClient(app)
    resp = client.post(
        "/source/quality/multi-source/check",
        json={
            "source_table_name": "source.index_daily_bar_v1",
            "canonical_fields": ["open_price", "high_price", "low_price", "close_price", "volume", "amount", "pct_chg"],
            "symbol": "399006.SZ",
            "trade_date": "2026-06-12",
            "include_backup": True,
            "dry_run": False,
        },
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "passed"
    assert payload["usable_provider_count"] == 2
    providers = {item["provider"]: item for item in payload["provider_evidence"]}
    assert providers["tencent"]["target_row_found"] is True
    assert providers["baostock"]["target_row_found"] is True
    volume = next(item for item in payload["comparisons"] if item["canonical_field_name"] == "volume")
    assert volume["baseline_value"] == "21380284200"
    assert volume["compared_value"] == "21380284200"


def test_tencent_adapter_parses_qfq_daily_rows(monkeypatch) -> None:
    from source_data_service.adapters import tencent_adapter

    def fake_request_json(url, params):
        assert "fqkline" in url
        assert params["param"] == "sz000063,day,2026-06-12,2026-06-12,10,qfq"
        return {
            "code": 0,
            "data": {
                "sz000063": {
                    "qfqday": [["2026-06-12", "38.600", "36.350", "38.700", "36.150", "2614711.000"]],
                    "qt": {
                        "sz000063": [
                            *[""] * 30,
                            "20260612150000",
                            "",
                            "-5.04",
                            "",
                            "",
                            "36.35/2614711/9702654430",
                        ]
                    },
                }
            },
        }

    monkeypatch.setattr(tencent_adapter, "_request_json", fake_request_json)
    result = tencent_adapter.TencentAdapter().fetch(
        "daily_bars",
        {
            "provider_code": "sz000063",
            "period": "day",
            "start_date": "2026-06-12",
            "end_date": "2026-06-12",
            "count": 10,
            "adjustment": "qfq",
        },
    )
    assert result.row_count == 1
    row = result.rows[0].row
    assert row["provider_code"] == "sz000063"
    assert row["symbol"] == "000063.SZ"
    assert row["close"] == "36.350"
    assert row["amount"] is None
    assert row["pct_chg"] is None
    assert row["adjustment_mode"] == "qfq"


def test_eastmoney_adapter_parses_moneyflow_stock_series(monkeypatch) -> None:
    from source_data_service.adapters import eastmoney_adapter

    def fake_eastmoney_json(url, params):
        assert "fflow/kline/get" in url
        assert params["secid"] == "0.000759"
        return {
            "data": {
                "klines": [
                    "2026-06-11,1000,200,300,400,100",
                    "2026-06-12,123456.78,20000,30000,40000,33456.78",
                ]
            }
        }

    monkeypatch.setattr(eastmoney_adapter, "_eastmoney_json", fake_eastmoney_json)
    result = eastmoney_adapter.EastMoneyAdapter().fetch(
        "moneyflow_stock_series",
        {"secid": "0.000759", "start_date": "2026-06-12", "end_date": "2026-06-12", "lmt": 120},
    )

    assert result.row_count == 1
    row = result.rows[0].row
    assert row["date"] == "2026-06-12"
    assert row["symbol"] == "000759.SZ"
    assert row["secid"] == "0.000759"
    assert row["main_net_inflow"] == "123456.78"
    assert row["provider_definition"].startswith("eastmoney_fflow_kline_get")


def test_source_build_maps_eastmoney_moneyflow_rows_to_canonical_values() -> None:
    row = {
        "date": "2026-06-12",
        "symbol": "000759.SZ",
        "secid": "0.000759",
        "main_net_inflow": "123456.78",
        "super_large_net_inflow": "20000",
        "large_net_inflow": "30000",
        "medium_net_inflow": "40000",
        "small_net_inflow": "33456.78",
        "provider_definition": "eastmoney_fflow_kline_get",
    }
    values, warnings = _build_values(
        Provider.EASTMONEY,
        "moneyflow_stock_series",
        "source.stock_moneyflow_daily_v1",
        row,
        ["main_net_inflow", "provider_definition"],
    )
    assert warnings == []
    assert values["main_net_inflow"] == 123456.78
    assert values["provider_definition"] == "eastmoney_fflow_kline_get"


def test_baostock_adapter_serializes_provider_calls(monkeypatch) -> None:
    from source_data_service.adapters.baostock_adapter import BaoStockAdapter

    active_calls = 0
    max_active_calls = 0

    def fake_fetch_locked(self, api_name, params):
        nonlocal active_calls, max_active_calls
        active_calls += 1
        max_active_calls = max(max_active_calls, active_calls)
        time.sleep(0.05)
        active_calls -= 1
        return _raw_fetch_result(Provider.BAOSTOCK, api_name, "raw_baostock.query_history_k_data_plus_daily_raw_v1", params, [])

    monkeypatch.setattr(BaoStockAdapter, "_fetch_locked", fake_fetch_locked)
    adapter = BaoStockAdapter()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(adapter.fetch, "query_history_k_data_plus_daily_raw", {"code": "sz.000063", "start_date": "2026-06-12", "end_date": "2026-06-12"}),
            executor.submit(adapter.fetch, "query_history_k_data_plus_daily_qfq", {"code": "sz.000063", "start_date": "2026-06-12", "end_date": "2026-06-12"}),
        ]
        results = [future.result() for future in futures]

    assert [item.provider for item in results] == [Provider.BAOSTOCK, Provider.BAOSTOCK]
    assert max_active_calls == 1


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
    assert all(row["provider"] in {"baostock", "akshare", "tushare", "eastmoney", "tencent", "sohu", "ths"} for row in required)
    assert any(row["provider"] == "tencent" and row["api_name"] == "daily_bars" for row in required)
    assert any(row["provider"] == "sohu" and row["api_name"] == "daily_bars" for row in required)
    assert any(row["provider"] == "eastmoney" and row["api_name"] == "quote_snapshot" for row in required)
    assert any(row["provider"] == "eastmoney" and row["api_name"] == "minute_bars" for row in required)
    assert any(row["provider"] == "eastmoney" and row["api_name"] == "trade_details" for row in required)
    assert not any(
        row["provider"] == "akshare"
        and row["api_name"] in {"stock_zh_a_hist_daily_raw", "stock_zh_a_hist_daily_qfq", "index_zh_a_hist", "stock_zh_a_spot_em"}
        and row["real_probe_required"]
        for row in probe.json()["rows"]
    )
    assert not any(row["provider"] == "eastmoney" and row["api_name"] == "daily_bars" and row["real_probe_required"] for row in probe.json()["rows"])
    assert not any(row["provider"] in {"sina", "cninfo"} and row["real_probe_required"] for row in probe.json()["rows"])
    routes = client.get("/source/repair-routes")
    assert routes.status_code == 200
    rows = routes.json()["rows"]
    assert any(row["source_table_name"] == "source.daily_bar_v1" and row["canonical_field_name"] == "close_price" for row in rows)
    assert any(
        row["source_table_name"] == "source.stock_moneyflow_daily_v1"
        and row["canonical_field_name"] == "main_net_inflow"
        and row["primary_provider"] == "eastmoney"
        and row["primary_api_name"] == "moneyflow_stock_series"
        for row in rows
    )


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


def test_worker_zero_row_real_fetch_queues_backup_job(monkeypatch) -> None:
    from source_data_service import worker_executor

    client = TestClient(app)

    def fake_execute_provider_fetch(provider, api_name, params, dry_run):
        return RawFetchResult(
            provider=provider,
            api_name=api_name,
            raw_table_name=get_api_spec(provider, api_name).raw_table_name,
            request_params=params,
            dry_run=dry_run,
            row_count=0,
            rows=[],
            request_hash="raw-empty-minute-000764",
            response_schema_hash="schema-empty-minute-v1",
        )

    monkeypatch.setattr(worker_executor, "execute_provider_fetch", fake_execute_provider_fetch)
    submit = client.post(
        "/source/fetch/submit",
        json={
            "source_table_name": "source.minute_bar_v1",
            "canonical_fields": ["close_price"],
            "symbols": ["000764.SZ"],
            "trade_date": "2026-05-29",
            "trigger_type": "model_release_preflight",
            "priority": "P0_urgent_release",
            "request_source": "hot-candidates-service",
            "dry_run": True,
        },
    )
    assert submit.status_code == 200
    batch_id = submit.json()["fetch_batch_id"]

    run = client.post(
        "/source/fetch/worker/run-once",
        json={
            "worker_id": "worker-empty-minute",
            "max_jobs": 1,
            "providers": ["eastmoney"],
            "queue_names": ["urgent_release_gate_queue"],
            "dry_run_provider": False,
        },
    )
    assert run.status_code == 200
    assert run.json()["failed_count"] == 1
    callbacks = client.get(f"/source/fetch/callbacks?fetch_batch_id={batch_id}").json()
    assert any(event["event_type"] == "backup_job_queued" for event in callbacks)

    backup_event = next(event for event in callbacks if event["event_type"] == "backup_job_queued")
    backup_job_id = backup_event["payload"]["backup_job_item_id"]
    run_backup = client.post(
        "/source/fetch/worker/run-once",
        json={
            "worker_id": "worker-empty-minute-backup",
            "max_jobs": 1,
            "providers": ["tencent"],
            "queue_names": ["urgent_release_gate_queue"],
            "dry_run_provider": False,
        },
    )
    assert run_backup.status_code == 200
    assert run_backup.json()["failed_count"] == 1
    backup_status = client.get(f"/source/fetch/jobs/{backup_job_id}").json()
    assert backup_status["status"] == "failed"
    assert backup_status["backup_of_job_item_id"]
    pull_again = client.post(
        "/source/fetch/worker/pull",
        json={
            "worker_id": "worker-empty-minute-backup-again",
            "max_jobs": 1,
            "providers": ["tencent"],
            "queue_names": ["urgent_release_gate_queue"],
        },
    ).json()
    assert all(job["job_item_id"] != backup_job_id for job in pull_again["jobs"])


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
    assert any(event["event_type"] == "job_heartbeat" for event in callbacks)
    assert any(event["event_type"] == "source_build_trigger_created" for event in callbacks)


def test_idle_fetch_worker_drains_queued_source_build_triggers() -> None:
    saved_batches = dict(fetch_orchestrator._BATCHES)
    saved_jobs = dict(fetch_orchestrator._JOBS)
    saved_request_hash = dict(fetch_orchestrator._REQUEST_HASH_TO_JOB)
    saved_callbacks = list(fetch_orchestrator._CALLBACKS)
    saved_build_triggers = list(fetch_orchestrator._BUILD_TRIGGERS)
    saved_idempotency = dict(fetch_orchestrator._IDEMPOTENCY_TO_BATCH)
    saved_raw_rows = dict(source_repository._RAW_ROWS)
    saved_source_rows = dict(source_repository._SOURCE_ROWS)
    saved_lineage_rows = list(source_repository._LINEAGE_ROWS)
    saved_build_results = list(source_repository._BUILD_RESULTS)
    saved_raw_request_index = dict(source_repository._RAW_REQUEST_INDEX)
    try:
        fetch_orchestrator._BATCHES.clear()
        fetch_orchestrator._JOBS.clear()
        fetch_orchestrator._REQUEST_HASH_TO_JOB.clear()
        fetch_orchestrator._CALLBACKS.clear()
        fetch_orchestrator._BUILD_TRIGGERS.clear()
        fetch_orchestrator._IDEMPOTENCY_TO_BATCH.clear()
        source_repository._RAW_ROWS.clear()
        source_repository._SOURCE_ROWS.clear()
        source_repository._LINEAGE_ROWS.clear()
        source_repository._BUILD_RESULTS.clear()
        source_repository._RAW_REQUEST_INDEX.clear()

        client = TestClient(app)
        submit = client.post(
            "/source/fetch/submit",
            json={
                "source_table_name": "source.daily_bar_v1",
                "canonical_fields": ["close_price"],
                "symbols": ["000774.SZ"],
                "trade_date": "2026-07-06",
                "trigger_type": "model_release_preflight",
                "priority": "P0_urgent_release",
                "request_source": "scheduler-service",
                "dry_run": True,
            },
        )
        assert submit.status_code == 200
        batch_id = submit.json()["fetch_batch_id"]
        pull = client.post(
            "/source/fetch/worker/pull",
            json={"worker_id": "worker-idle-build-setup", "max_jobs": 1, "queue_names": ["urgent_release_gate_queue"]},
        )
        assert pull.status_code == 200
        job = pull.json()["jobs"][0]
        request_hash = "raw-request-000774-idle-build"
        complete = client.post(
            f"/source/fetch/jobs/{job['job_item_id']}/complete",
            json={
                "worker_id": "worker-idle-build-setup",
                "success": True,
                "row_count": 1,
                "raw_request_hash": request_hash,
                "raw_response_schema_hash": "schema-000774-idle-build",
            },
        )
        assert complete.status_code == 200
        triggers = client.get(f"/source/build/triggers?fetch_batch_id={batch_id}").json()
        assert len(triggers) == 1
        assert triggers[0]["status"] == "queued"

        ingest = ingest_raw_fetch_result(
            RawFetchResult(
                provider=Provider(job["provider"]),
                api_name=job["api_name"],
                raw_table_name=job["raw_table_name"],
                request_params=job["request_params"],
                dry_run=False,
                row_count=1,
                request_hash=request_hash,
                response_schema_hash="schema-000774-idle-build",
                rows=[
                    RawRow(
                        provider=Provider(job["provider"]),
                        api_name=job["api_name"],
                        raw_table_name=job["raw_table_name"],
                        request_params=job["request_params"],
                        row={
                            "date": "2026-07-06",
                            "code": "sz.000774",
                            "open": "10.00",
                            "high": "10.50",
                            "low": "9.90",
                            "close": "10.20",
                            "preclose": "9.80",
                            "volume": "120000",
                            "amount": "1234567.89",
                            "pctChg": "4.08",
                            "turn": "1.23",
                            "tradestatus": "1",
                        },
                        request_hash=request_hash,
                        response_schema_hash="schema-000774-idle-build",
                        response_row_hash="row-000774-idle-build",
                        batch_id=batch_id,
                        available_at=datetime(2026, 7, 6, 7, 45, tzinfo=timezone.utc),
                    )
                ],
            )
        )
        assert ingest.raw_write_status.startswith("accepted")

        result = worker_executor.run_worker_once(
            FetchWorkerRunOnceRequest(worker_id="worker-idle-build", max_jobs=50, dry_run_provider=False)
        )

        assert result.leased_count == 0
        assert result.succeeded_count == 0
        assert result.failed_count == 0
        build_results = client.get("/source/build/results").json()
        assert any(item["trigger_id"] == triggers[0]["trigger_id"] and item["status"] == "succeeded" for item in build_results)
        rows = client.get(
            "/source/rows?source_table_name=source.daily_bar_v1&symbol=000774.SZ&trade_date=2026-07-06"
        ).json()
        assert rows
        assert rows[0]["values"]["close_price"] == 10.2
        lineage = client.get(
            "/source/lineage/records?source_table_name=source.daily_bar_v1&source_pk=000774.SZ|2026-07-06"
        ).json()
        assert any(row["canonical_field_name"] == "close_price" for row in lineage)
    finally:
        fetch_orchestrator._BATCHES.clear()
        fetch_orchestrator._BATCHES.update(saved_batches)
        fetch_orchestrator._JOBS.clear()
        fetch_orchestrator._JOBS.update(saved_jobs)
        fetch_orchestrator._REQUEST_HASH_TO_JOB.clear()
        fetch_orchestrator._REQUEST_HASH_TO_JOB.update(saved_request_hash)
        fetch_orchestrator._CALLBACKS.clear()
        fetch_orchestrator._CALLBACKS.extend(saved_callbacks)
        fetch_orchestrator._BUILD_TRIGGERS.clear()
        fetch_orchestrator._BUILD_TRIGGERS.extend(saved_build_triggers)
        fetch_orchestrator._IDEMPOTENCY_TO_BATCH.clear()
        fetch_orchestrator._IDEMPOTENCY_TO_BATCH.update(saved_idempotency)
        source_repository._RAW_ROWS.clear()
        source_repository._RAW_ROWS.update(saved_raw_rows)
        source_repository._SOURCE_ROWS.clear()
        source_repository._SOURCE_ROWS.update(saved_source_rows)
        source_repository._LINEAGE_ROWS.clear()
        source_repository._LINEAGE_ROWS.extend(saved_lineage_rows)
        source_repository._BUILD_RESULTS.clear()
        source_repository._BUILD_RESULTS.extend(saved_build_results)
        source_repository._RAW_REQUEST_INDEX.clear()
        source_repository._RAW_REQUEST_INDEX.update(saved_raw_request_index)


def test_source_build_fails_when_raw_trade_date_differs_from_requested_job_date() -> None:
    client = TestClient(app)
    submit = client.post(
        "/source/fetch/submit",
        json={
            "source_table_name": "source.adjusted_daily_bar_v1",
            "canonical_fields": ["adjusted_close"],
            "symbols": ["000997.SZ"],
            "trade_date": "2026-06-19",
            "trigger_type": "provider_probe",
            "priority": "P1_normal_ingest",
            "request_source": "source-data-service-test",
            "dry_run": True,
        },
    )
    assert submit.status_code == 200
    batch_id = submit.json()["fetch_batch_id"]
    pull = client.post(
        "/source/fetch/worker/pull",
        json={"worker_id": "worker-date-guard", "max_jobs": 1, "providers": ["baostock"], "queue_names": ["provider_probe_queue"]},
    )
    assert pull.status_code == 200
    job = pull.json()["jobs"][0]
    raw_request_hash = f"raw-request-date-guard-{job['job_item_id']}"
    complete = client.post(
        f"/source/fetch/jobs/{job['job_item_id']}/complete",
        json={
            "worker_id": "worker-date-guard",
            "success": True,
            "row_count": 1,
            "raw_request_hash": raw_request_hash,
            "raw_response_schema_hash": "schema-date-guard",
        },
    )
    assert complete.status_code == 200
    ingest = ingest_raw_fetch_result(
        RawFetchResult(
            provider=Provider.BAOSTOCK,
            api_name="query_history_k_data_plus_daily_qfq",
            raw_table_name="raw_baostock.query_history_k_data_plus_daily_qfq_v1",
            request_params={
                "code": "sz.000997",
                "start_date": "2026-06-19",
                "end_date": "2026-06-19",
                "frequency": "d",
                "adjustflag": "2",
            },
            dry_run=False,
            row_count=1,
            request_hash=raw_request_hash,
            response_schema_hash="schema-date-guard",
            rows=[
                RawRow(
                    provider=Provider.BAOSTOCK,
                    api_name="query_history_k_data_plus_daily_qfq",
                    raw_table_name="raw_baostock.query_history_k_data_plus_daily_qfq_v1",
                    request_params={
                        "code": "sz.000997",
                        "start_date": "2026-06-19",
                        "end_date": "2026-06-19",
                        "frequency": "d",
                        "adjustflag": "2",
                    },
                    row={
                        "date": "2026-06-18",
                        "code": "sz.000997",
                        "open": "10.0",
                        "high": "10.2",
                        "low": "9.9",
                        "close": "10.1",
                    },
                    request_hash=raw_request_hash,
                    response_schema_hash="schema-date-guard",
                    response_row_hash="row-date-guard",
                    batch_id=batch_id,
                    available_at=datetime(2026, 6, 19, 7, 45, tzinfo=timezone.utc),
                )
            ],
        )
    )
    assert ingest.raw_write_status.startswith("accepted")
    triggers = client.get(f"/source/build/triggers?fetch_batch_id={batch_id}").json()
    trigger = next(item for item in triggers if item["job_item_id"] == job["job_item_id"])

    result = execute_source_build_trigger(
        SourceBuildExecuteRequest(trigger_id=trigger["trigger_id"], worker_id="worker-date-guard-build")
    )

    assert result.status == "failed"
    assert result.source_row_count == 0
    assert any("does not match requested trade_date 2026-06-19" in item for item in result.errors)


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


def test_fetch_job_completion_persists_raw_hashes_in_job_status() -> None:
    client = TestClient(app)
    submit = client.post(
        "/source/fetch/submit",
        json={
            "source_table_name": "source.daily_bar_v1",
            "canonical_fields": ["close_price"],
            "symbols": ["000811.SZ"],
            "trade_date": "2026-05-26",
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
        json={"worker_id": "worker-raw-hash", "max_jobs": 1, "queue_names": ["normal_daily_ingest_queue"]},
    )
    assert pull.status_code == 200
    job_id = pull.json()["jobs"][0]["job_item_id"]
    complete = client.post(
        f"/source/fetch/jobs/{job_id}/complete",
        json={
            "worker_id": "worker-raw-hash",
            "success": True,
            "row_count": 1,
            "raw_request_hash": "raw_request_hash_contract_test",
            "raw_response_schema_hash": "raw_schema_hash_contract_test",
        },
    )
    assert complete.status_code == 200
    assert complete.json()["raw_request_hash"] == "raw_request_hash_contract_test"
    assert complete.json()["raw_response_schema_hash"] == "raw_schema_hash_contract_test"

    status = client.get(f"/source/fetch/jobs/{job_id}")
    assert status.status_code == 200
    assert status.json()["raw_request_hash"] == "raw_request_hash_contract_test"
    assert status.json()["raw_response_schema_hash"] == "raw_schema_hash_contract_test"

    callbacks = client.get(f"/source/fetch/callbacks?fetch_batch_id={batch_id}").json()
    succeeded = [event for event in callbacks if event["event_type"] == "job_succeeded"]
    assert succeeded
    assert succeeded[-1]["payload"]["raw_request_hash"] == "raw_request_hash_contract_test"
    assert succeeded[-1]["payload"]["raw_response_schema_hash"] == "raw_schema_hash_contract_test"


def test_fetch_callbacks_endpoint_reads_durable_outbox(monkeypatch) -> None:
    from source_data_service import fetch_orchestrator

    event = FetchCallbackEventOut(
        callback_event_id="callback_pg_worker_job_succeeded",
        fetch_batch_id="fetch_batch_pg_callbacks",
        job_item_id="fetch_job_pg_worker",
        event_type=CallbackEventType.JOB_SUCCEEDED,
        callback_url=None,
        payload={
            "job_item_id": "fetch_job_pg_worker",
            "raw_request_hash": "pg_raw_request_hash",
            "raw_response_schema_hash": "pg_raw_schema_hash",
        },
        delivery_status="skipped_no_callback",
        created_at=datetime(2026, 6, 15, tzinfo=timezone.utc),
    )

    def fake_durable_callbacks(fetch_batch_id=None, *, pending_only=False, limit=1000):
        assert fetch_batch_id == "fetch_batch_pg_callbacks"
        assert pending_only is False
        return [event]

    monkeypatch.setattr(fetch_orchestrator, "durable_callback_events_if_enabled", fake_durable_callbacks)
    client = TestClient(app)
    response = client.get("/source/fetch/callbacks?fetch_batch_id=fetch_batch_pg_callbacks")

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["event_type"] == "job_succeeded"
    assert payload[0]["payload"]["raw_request_hash"] == "pg_raw_request_hash"
    assert payload[0]["payload"]["raw_response_schema_hash"] == "pg_raw_schema_hash"


def test_fetch_callback_dispatch_uses_durable_pending_outbox(monkeypatch) -> None:
    from source_data_service import fetch_orchestrator

    event = FetchCallbackEventOut(
        callback_event_id="callback_pg_pending_no_url",
        fetch_batch_id="fetch_batch_pg_dispatch",
        job_item_id="fetch_job_pg_dispatch",
        event_type=CallbackEventType.JOB_SUCCEEDED,
        callback_url=None,
        payload={"job_item_id": "fetch_job_pg_dispatch"},
        delivery_status="pending",
        created_at=datetime(2026, 6, 15, tzinfo=timezone.utc),
    )
    persisted: list[FetchCallbackEventOut] = []

    def fake_durable_callbacks(fetch_batch_id=None, *, pending_only=False, limit=1000):
        assert fetch_batch_id is None
        assert pending_only is True
        assert limit == 5
        return [event]

    monkeypatch.setattr(fetch_orchestrator, "durable_callback_events_if_enabled", fake_durable_callbacks)
    monkeypatch.setattr(fetch_orchestrator, "persist_callback_if_enabled", lambda item: persisted.append(item))
    client = TestClient(app)
    response = client.post("/source/fetch/callbacks/dispatch", json={"max_events": 5, "dry_run": True})

    assert response.status_code == 200
    assert response.json()["attempted_count"] == 1
    assert response.json()["skipped_count"] == 1
    assert persisted[0].delivery_status == "skipped_no_callback"


def test_worker_pull_hydrates_durable_batch_for_queued_job_after_restart(monkeypatch) -> None:
    from source_data_service import fetch_orchestrator
    from source_data_service.models import (
        FetchBatchStatus,
        FetchBatchStatusOut,
        FetchJobLeaseRequest,
        FetchJobStatus,
        FetchJobStatusOut,
        FetchQueueName,
    )

    now = datetime(2026, 6, 20, tzinfo=timezone.utc)
    batch = FetchBatchStatusOut(
        fetch_batch_id="fetch_batch_restart_hydrate",
        fetch_plan_id="fetch_plan_restart_hydrate",
        source_table_name="source.daily_bar_v1",
        trigger_type=FetchTriggerType.SCHEDULED_PERIODIC,
        priority=FetchPriority.P1_NORMAL_INGEST,
        queue_name=FetchQueueName.NORMAL_DAILY_INGEST_QUEUE,
        status=FetchBatchStatus.COMPLETED_WITH_ERRORS,
        job_count=1,
        queued_count=1,
        leased_count=0,
        succeeded_count=0,
        failed_count=0,
        skipped_duplicate_count=0,
        callback_url="http://scheduler-service:8023/callback/source-fetch",
        created_at=now,
        updated_at=now,
        operator_notes=["durable batch was not active but still owns queued repair job"],
    )
    job = FetchJobStatusOut(
        job_item_id="fetch_job_restart_hydrate",
        fetch_batch_id=batch.fetch_batch_id,
        provider=Provider.BAOSTOCK,
        api_name="query_history_k_data_plus_daily_raw",
        raw_table_name="raw_baostock.query_history_k_data_plus_daily_raw_v1",
        request_params={"code": "sz.000760", "date": "2026-05-28"},
        request_hash="restart-hydrate-request-hash",
        source_table_name=batch.source_table_name,
        canonical_fields=["close_price"],
        symbol="000760.SZ",
        trade_date=date(2026, 5, 28),
        priority=FetchPriority.P1_NORMAL_INGEST,
        queue_name=FetchQueueName.NORMAL_DAILY_INGEST_QUEUE,
        status=FetchJobStatus.QUEUED,
        created_at=now,
        updated_at=now,
    )

    saved_batches = dict(fetch_orchestrator._BATCHES)
    saved_jobs = dict(fetch_orchestrator._JOBS)
    saved_request_hash = dict(fetch_orchestrator._REQUEST_HASH_TO_JOB)
    saved_callbacks = list(fetch_orchestrator._CALLBACKS)
    try:
        fetch_orchestrator._BATCHES.clear()
        fetch_orchestrator._JOBS.clear()
        fetch_orchestrator._REQUEST_HASH_TO_JOB.clear()
        fetch_orchestrator._CALLBACKS.clear()
        fetch_orchestrator._JOBS[job.job_item_id] = job.model_copy(
            update={
                "status": FetchJobStatus.FAILED,
                "last_error_code": "stale_worker_memory",
                "updated_at": now - timedelta(minutes=5),
            }
        )

        monkeypatch.setattr(fetch_orchestrator, "load_active_state_if_enabled", lambda: ([], [job]))
        monkeypatch.setattr(
            fetch_orchestrator,
            "durable_fetch_batch_if_enabled",
            lambda fetch_batch_id: batch if fetch_batch_id == batch.fetch_batch_id else None,
        )
        monkeypatch.setattr(fetch_orchestrator, "persist_job_if_enabled", lambda _job: None)
        monkeypatch.setattr(fetch_orchestrator, "persist_batch_if_enabled", lambda _batch: None)
        monkeypatch.setattr(fetch_orchestrator, "persist_callback_if_enabled", lambda _event: None)

        lease = fetch_orchestrator.lease_fetch_jobs(
            FetchJobLeaseRequest(
                worker_id="worker-after-restart",
                max_jobs=1,
                queue_names=[FetchQueueName.NORMAL_DAILY_INGEST_QUEUE],
            )
        )

        assert lease.leased_count == 1
        assert lease.jobs[0].job_item_id == job.job_item_id
        assert lease.jobs[0].status == FetchJobStatus.LEASED
        assert fetch_orchestrator._BATCHES[batch.fetch_batch_id].callback_url == batch.callback_url
        leased_events = [
            event for event in fetch_orchestrator._CALLBACKS if event.event_type == CallbackEventType.JOB_LEASED
        ]
        assert leased_events
        assert leased_events[-1].callback_url == batch.callback_url
    finally:
        fetch_orchestrator._BATCHES.clear()
        fetch_orchestrator._BATCHES.update(saved_batches)
        fetch_orchestrator._JOBS.clear()
        fetch_orchestrator._JOBS.update(saved_jobs)
        fetch_orchestrator._REQUEST_HASH_TO_JOB.clear()
        fetch_orchestrator._REQUEST_HASH_TO_JOB.update(saved_request_hash)
        fetch_orchestrator._CALLBACKS.clear()
        fetch_orchestrator._CALLBACKS.extend(saved_callbacks)


def test_requeue_expired_leases_uses_durable_jobs_after_restart(monkeypatch) -> None:
    from source_data_service import fetch_orchestrator
    from source_data_service.models import (
        FetchBatchStatus,
        FetchBatchStatusOut,
        FetchJobStatus,
        FetchJobStatusOut,
        FetchQueueName,
    )

    now = datetime(2026, 6, 20, tzinfo=timezone.utc)
    batch = FetchBatchStatusOut(
        fetch_batch_id="fetch_batch_restart_lease_maintenance",
        fetch_plan_id="fetch_plan_restart_lease_maintenance",
        source_table_name="source.minute_bar_v1",
        trigger_type=FetchTriggerType.SCHEDULED_PERIODIC,
        priority=FetchPriority.P1_NORMAL_INGEST,
        queue_name=FetchQueueName.NORMAL_DAILY_INGEST_QUEUE,
        status=FetchBatchStatus.RUNNING,
        job_count=1,
        queued_count=1,
        leased_count=0,
        succeeded_count=0,
        failed_count=0,
        skipped_duplicate_count=0,
        callback_url="http://scheduler-service:8023/callback/source-fetch",
        created_at=now,
        updated_at=now,
    )
    requeued_job = FetchJobStatusOut(
        job_item_id="fetch_job_restart_lease_maintenance",
        fetch_batch_id=batch.fetch_batch_id,
        provider=Provider.EASTMONEY,
        api_name="minute_bars",
        raw_table_name="raw_eastmoney.minute_bars_v1",
        request_params={"symbol": "000063.SZ", "date": "2026-06-12"},
        request_hash="restart-lease-maintenance-request-hash",
        source_table_name=batch.source_table_name,
        canonical_fields=["close_price"],
        symbol="000063.SZ",
        trade_date=date(2026, 6, 12),
        priority=FetchPriority.P1_NORMAL_INGEST,
        queue_name=FetchQueueName.NORMAL_DAILY_INGEST_QUEUE,
        status=FetchJobStatus.QUEUED,
        next_retry_at=now,
        created_at=now,
        updated_at=now,
    )

    saved_batches = dict(fetch_orchestrator._BATCHES)
    saved_jobs = dict(fetch_orchestrator._JOBS)
    saved_request_hash = dict(fetch_orchestrator._REQUEST_HASH_TO_JOB)
    saved_callbacks = list(fetch_orchestrator._CALLBACKS)
    try:
        fetch_orchestrator._BATCHES.clear()
        fetch_orchestrator._JOBS.clear()
        fetch_orchestrator._REQUEST_HASH_TO_JOB.clear()
        fetch_orchestrator._CALLBACKS.clear()

        monkeypatch.setattr(fetch_orchestrator, "requeue_expired_leases_if_enabled", lambda _now: [requeued_job])
        monkeypatch.setattr(
            fetch_orchestrator,
            "durable_fetch_batch_if_enabled",
            lambda fetch_batch_id: batch if fetch_batch_id == batch.fetch_batch_id else None,
        )
        monkeypatch.setattr(fetch_orchestrator, "persist_batch_if_enabled", lambda _batch: None)
        monkeypatch.setattr(fetch_orchestrator, "persist_callback_if_enabled", lambda _event: None)

        result = fetch_orchestrator.requeue_expired_leases()

        assert result.requeued_count == 1
        assert result.expired_job_ids == [requeued_job.job_item_id]
        assert fetch_orchestrator._JOBS[requeued_job.job_item_id].status == FetchJobStatus.QUEUED
        requeued_events = [
            event for event in fetch_orchestrator._CALLBACKS if event.event_type == CallbackEventType.JOB_REQUEUED
        ]
        assert requeued_events
        assert requeued_events[-1].callback_url == batch.callback_url
    finally:
        fetch_orchestrator._BATCHES.clear()
        fetch_orchestrator._BATCHES.update(saved_batches)
        fetch_orchestrator._JOBS.clear()
        fetch_orchestrator._JOBS.update(saved_jobs)
        fetch_orchestrator._REQUEST_HASH_TO_JOB.clear()
        fetch_orchestrator._REQUEST_HASH_TO_JOB.update(saved_request_hash)
        fetch_orchestrator._CALLBACKS.clear()
        fetch_orchestrator._CALLBACKS.extend(saved_callbacks)


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


def test_ds6_moneyflow_raw_ingest_source_build_lineage() -> None:
    client = TestClient(app)
    submit = client.post(
        "/source/fetch/submit",
        json={
            "source_table_name": "source.stock_moneyflow_daily_v1",
            "canonical_fields": ["main_net_inflow", "provider_definition"],
            "symbols": ["000759.SZ"],
            "trade_date": "2026-06-12",
            "trigger_type": "data_inspection_gap_repair",
            "priority": "P1_normal_ingest",
            "request_source": "data-inspector-service",
            "dry_run": True,
        },
    )
    assert submit.status_code == 200
    batch_id = submit.json()["fetch_batch_id"]
    pull = client.post(
        "/source/fetch/worker/pull",
        json={"worker_id": "worker-moneyflow", "max_jobs": 1, "queue_names": ["repair_queue"]},
    )
    assert pull.status_code == 200
    job = pull.json()["jobs"][0]
    assert job["provider"] == "eastmoney"
    assert job["api_name"] == "moneyflow_stock_series"
    assert job["request_params"]["secid"] == "0.000759"
    request_hash = job["request_hash"]
    raw_row = {
        "date": "2026-06-12",
        "symbol": "000759.SZ",
        "secid": "0.000759",
        "main_net_inflow": "123456.78",
        "super_large_net_inflow": "20000",
        "large_net_inflow": "30000",
        "medium_net_inflow": "40000",
        "small_net_inflow": "33456.78",
        "provider_definition": "eastmoney_fflow_kline_get",
    }
    ingest = client.post(
        "/source/raw/ingest-result",
        json={
            "provider": "eastmoney",
            "api_name": "moneyflow_stock_series",
            "raw_table_name": "raw_eastmoney.moneyflow_stock_series_v1",
            "request_params": job["request_params"],
            "dry_run": False,
            "row_count": 1,
            "request_hash": request_hash,
            "response_schema_hash": "schema_eastmoney_moneyflow_v1",
            "rows": [
                {
                    "provider": "eastmoney",
                    "api_name": "moneyflow_stock_series",
                    "raw_table_name": "raw_eastmoney.moneyflow_stock_series_v1",
                    "request_params": job["request_params"],
                    "row": raw_row,
                    "request_hash": request_hash,
                    "response_schema_hash": "schema_eastmoney_moneyflow_v1",
                    "response_row_hash": "row_moneyflow_000759_20260612",
                }
            ],
        },
    )
    assert ingest.status_code == 200
    assert ingest.json()["raw_write_status"] == "accepted"
    done = client.post(
        f"/source/fetch/jobs/{job['job_item_id']}/complete",
        json={"worker_id": "worker-moneyflow", "success": True, "row_count": 1, "raw_request_hash": request_hash},
    )
    assert done.status_code == 200
    triggers = client.get(f"/source/build/triggers?fetch_batch_id={batch_id}").json()
    assert triggers
    execute = client.post(
        f"/source/build/triggers/{triggers[0]['trigger_id']}/execute",
        json={"trigger_id": triggers[0]["trigger_id"], "worker_id": "builder-moneyflow"},
    )
    assert execute.status_code == 200
    payload = execute.json()
    assert payload["status"] == "succeeded"
    assert payload["source_row_count"] == 1
    assert payload["lineage_row_count"] >= 2
    rows = client.get(
        "/source/rows?source_table_name=source.stock_moneyflow_daily_v1&symbol=000759.SZ&trade_date=2026-06-12"
    ).json()
    assert rows
    assert rows[0]["values"]["main_net_inflow"] == 123456.78
    lineage = client.get(
        "/source/lineage/records?source_table_name=source.stock_moneyflow_daily_v1&source_pk=000759.SZ|2026-06-12"
    ).json()
    assert any(row["canonical_field_name"] == "main_net_inflow" and row["provider"] == "eastmoney" for row in lineage)


def test_ds6_trade_calendar_raw_ingest_source_build_lineage_with_pretrade() -> None:
    client = TestClient(app)
    submit = client.post(
        "/source/fetch/submit",
        json={
            "source_table_name": "source.trade_calendar_v1",
            "canonical_fields": ["is_trading_day", "pretrade_date"],
            "start_date": "2026-07-01",
            "end_date": "2026-07-03",
            "trigger_type": "manual_backfill",
            "priority": "P2_backfill",
            "request_source": "source-data-service-test",
            "dry_run": True,
        },
    )
    assert submit.status_code == 200
    batch_id = submit.json()["fetch_batch_id"]
    pull = client.post(
        "/source/fetch/worker/pull",
        json={"worker_id": "worker-calendar", "max_jobs": 1, "providers": ["baostock"], "queue_names": ["backfill_queue"]},
    )
    assert pull.status_code == 200
    job = pull.json()["jobs"][0]
    assert job["api_name"] == "query_trade_dates"
    request_hash = job["request_hash"]
    rows = [
        {"calendar_date": "2026-07-01", "is_trading_day": "1"},
        {"calendar_date": "2026-07-02", "is_trading_day": "1"},
        {"calendar_date": "2026-07-03", "is_trading_day": "0"},
    ]
    ingest = client.post(
        "/source/raw/ingest-result",
        json={
            "provider": "baostock",
            "api_name": "query_trade_dates",
            "raw_table_name": "raw_baostock.query_trade_dates_v1",
            "request_params": job["request_params"],
            "dry_run": False,
            "row_count": len(rows),
            "request_hash": request_hash,
            "response_schema_hash": "schema_trade_calendar_v1",
            "rows": [
                {
                    "provider": "baostock",
                    "api_name": "query_trade_dates",
                    "raw_table_name": "raw_baostock.query_trade_dates_v1",
                    "request_params": job["request_params"],
                    "row": row,
                    "request_hash": request_hash,
                    "response_schema_hash": "schema_trade_calendar_v1",
                    "response_row_hash": f"row_calendar_{row['calendar_date']}",
                }
                for row in rows
            ],
        },
    )
    assert ingest.status_code == 200
    assert ingest.json()["raw_write_status"] == "accepted"
    done = client.post(
        f"/source/fetch/jobs/{job['job_item_id']}/complete",
        json={"worker_id": "worker-calendar", "success": True, "row_count": len(rows), "raw_request_hash": request_hash},
    )
    assert done.status_code == 200
    triggers = client.get(f"/source/build/triggers?fetch_batch_id={batch_id}").json()
    assert triggers
    execute = client.post(
        f"/source/build/triggers/{triggers[0]['trigger_id']}/execute",
        json={"trigger_id": triggers[0]["trigger_id"], "worker_id": "builder-calendar"},
    )
    assert execute.status_code == 200
    payload = execute.json()
    assert payload["status"] == "succeeded"
    assert payload["source_row_count"] == 3
    assert payload["lineage_row_count"] >= 6
    built = client.get("/source/rows?source_table_name=source.trade_calendar_v1&trade_date=2026-07-02").json()
    assert built
    assert built[0]["source_pk"] == "2026-07-02"
    assert built[0]["values"]["is_trading_day"] is True
    assert built[0]["values"]["pretrade_date"] == "2026-07-01"
    lineage = client.get("/source/lineage/records?source_table_name=source.trade_calendar_v1&source_pk=2026-07-02").json()
    assert any(row["canonical_field_name"] == "pretrade_date" and row["provider"] == "baostock" for row in lineage)


def test_ds6_stock_master_raw_ingest_source_build_lineage() -> None:
    client = TestClient(app)
    submit = client.post(
        "/source/fetch/submit",
        json={
            "source_table_name": "source.stock_master_v1",
            "canonical_fields": ["stock_name", "ipo_date", "delist_date", "list_status"],
            "symbols": ["000764.SZ"],
            "trigger_type": "manual_backfill",
            "priority": "P2_backfill",
            "request_source": "source-data-service-test",
            "dry_run": True,
        },
    )
    assert submit.status_code == 200
    batch_id = submit.json()["fetch_batch_id"]
    pull = client.post(
        "/source/fetch/worker/pull",
        json={"worker_id": "worker-stock-master", "max_jobs": 1, "providers": ["baostock"], "queue_names": ["backfill_queue"]},
    )
    assert pull.status_code == 200
    job = pull.json()["jobs"][0]
    assert job["api_name"] == "query_stock_basic"
    request_hash = job["request_hash"]
    raw_row = {
        "code": "sz.000764",
        "code_name": "测试主数据",
        "ipoDate": "1998-01-05",
        "outDate": "",
        "type": "1",
        "status": "1",
    }
    ingest = client.post(
        "/source/raw/ingest-result",
        json={
            "provider": "baostock",
            "api_name": "query_stock_basic",
            "raw_table_name": "raw_baostock.query_stock_basic_v1",
            "request_params": job["request_params"],
            "dry_run": False,
            "row_count": 1,
            "request_hash": request_hash,
            "response_schema_hash": "schema_stock_master_v1",
            "rows": [
                {
                    "provider": "baostock",
                    "api_name": "query_stock_basic",
                    "raw_table_name": "raw_baostock.query_stock_basic_v1",
                    "request_params": job["request_params"],
                    "row": raw_row,
                    "request_hash": request_hash,
                    "response_schema_hash": "schema_stock_master_v1",
                    "response_row_hash": "row_stock_master_000764",
                }
            ],
        },
    )
    assert ingest.status_code == 200
    assert ingest.json()["raw_write_status"] == "accepted"
    done = client.post(
        f"/source/fetch/jobs/{job['job_item_id']}/complete",
        json={"worker_id": "worker-stock-master", "success": True, "row_count": 1, "raw_request_hash": request_hash},
    )
    assert done.status_code == 200
    triggers = client.get(f"/source/build/triggers?fetch_batch_id={batch_id}").json()
    assert triggers
    execute = client.post(
        f"/source/build/triggers/{triggers[0]['trigger_id']}/execute",
        json={"trigger_id": triggers[0]["trigger_id"], "worker_id": "builder-stock-master"},
    )
    assert execute.status_code == 200
    payload = execute.json()
    assert payload["status"] == "succeeded"
    assert payload["source_row_count"] == 1
    assert payload["lineage_row_count"] >= 4
    rows = client.get("/source/rows?source_table_name=source.stock_master_v1&symbol=000764.SZ").json()
    assert rows
    assert rows[0]["source_pk"] == "000764.SZ"
    assert rows[0]["values"]["stock_name"] == "测试主数据"
    assert rows[0]["values"]["ipo_date"] == "1998-01-05"
    assert rows[0]["values"]["list_status"] == "1"
    lineage = client.get("/source/lineage/records?source_table_name=source.stock_master_v1&source_pk=000764.SZ").json()
    assert any(row["canonical_field_name"] == "stock_name" and row["provider"] == "baostock" for row in lineage)


def test_gap_repair_plan_for_quote_and_minute_use_public_intraday_backups() -> None:
    quote_plan = build_repair_plan(
        SourceGapRequest(
            source_table_name="source.realtime_quote_v1",
            canonical_field_name="latest_price",
            symbol="000759.SZ",
            trade_date=date(2026, 6, 12),
        )
    )
    assert quote_plan.primary_repair.provider == Provider.EASTMONEY
    assert quote_plan.primary_repair.api_name == "quote_snapshot"
    assert quote_plan.primary_repair.params["secid"] == "0.000759"
    assert quote_plan.backup_repairs[0].provider == Provider.TENCENT
    assert quote_plan.backup_repairs[0].api_name == "quote_snapshot"
    assert quote_plan.backup_repairs[0].params["provider_code"] == "sz000759"

    minute_plan = build_repair_plan(
        SourceGapRequest(
            source_table_name="source.minute_bar_v1",
            canonical_field_name="close_price",
            symbol="000759.SZ",
            trade_date=date(2026, 6, 12),
        )
    )
    assert minute_plan.primary_repair.provider == Provider.EASTMONEY
    assert minute_plan.primary_repair.api_name == "minute_bars"
    assert minute_plan.backup_repairs[0].provider == Provider.TENCENT
    assert minute_plan.backup_repairs[0].api_name == "minute_bars"
    assert minute_plan.backup_repairs[0].params["provider_code"] == "sz000759"


def test_gap_repair_plan_for_stock_master_uses_eastmoney_universe_backup() -> None:
    plan = build_repair_plan(
        SourceGapRequest(
            source_table_name="source.stock_master_v1",
            canonical_field_name="stock_name",
            symbol="000759.SZ",
        )
    )
    assert plan.primary_repair.provider == Provider.BAOSTOCK
    assert plan.primary_repair.api_name == "query_stock_basic"
    assert plan.backup_repairs[0].provider == Provider.EASTMONEY
    assert plan.backup_repairs[0].api_name == "stock_universe"
    assert plan.backup_repairs[0].params["segment_name"] == "main_sz"
    assert plan.backup_repairs[0].params["max_pages_per_segment"] == 20


def test_tencent_intraday_build_mappings_are_available() -> None:
    quote_values, quote_warnings = _build_values(
        Provider.TENCENT,
        "quote_snapshot",
        "source.realtime_quote_v1",
        {
            "last_price": "5.95",
            "open_price": "5.88",
            "high_price": "6.15",
            "low_price": "5.87",
            "prev_close_price": "5.83",
            "volume": "113714500",
            "amount": "681685345",
            "event_time": "2026-06-15T16:14:51+08:00",
        },
        ["latest_price", "event_time"],
    )
    assert quote_warnings == []
    assert quote_values["latest_price"] == 5.95
    assert quote_values["event_time"] == "2026-06-15T16:14:51+08:00"

    minute_values, minute_warnings = _build_values(
        Provider.TENCENT,
        "minute_bars",
        "source.minute_bar_v1",
        {
            "bar_time": "2026-06-15T09:30:00+08:00",
            "event_time": "2026-06-15T09:30:00+08:00",
            "open": "5.86",
            "high": "5.89",
            "low": "5.86",
            "close": "5.88",
            "volume": "28876",
            "amount": "16979088.00",
        },
        ["close_price", "bar_time", "event_time"],
    )
    assert minute_warnings == []
    assert minute_values["close_price"] == 5.88
    assert minute_values["bar_time"] == "2026-06-15T09:30:00+08:00"


def test_ds6_baidu_news_raw_ingest_source_build_lineage() -> None:
    client = TestClient(app)
    submit = client.post(
        "/source/fetch/submit",
        json={
            "source_table_name": "source.event_news_v1",
            "canonical_fields": ["published_at"],
            "trigger_type": "data_inspection_gap_repair",
            "priority": "research",
            "request_source": "data-inspector-service",
            "dry_run": True,
        },
    )
    assert submit.status_code == 200
    batch_id = submit.json()["fetch_batch_id"]
    pull = client.post(
        "/source/fetch/worker/pull",
        json={"worker_id": "worker-baidu-news", "max_jobs": 1, "providers": ["baidu"], "queue_names": ["repair_queue"]},
    )
    assert pull.status_code == 200
    job = pull.json()["jobs"][0]
    assert job["provider"] == "baidu"
    assert job["api_name"] == "finance_news_feed"
    assert {key: job["request_params"][key] for key in ("rn", "pn", "type", "tag")} == {"rn": 20, "pn": 0, "type": "all", "tag": "all"}
    assert job["request_params"]["__backup_plans"][0]["provider"] == "cninfo"
    request_hash = job["request_hash"]
    raw_row = {
        "provider_news_id": "baidu_news_source_build_1",
        "title": "百度财经样例新闻",
        "source_name": "BAIDU",
        "published_at": "2026-06-14T01:00:00+00:00",
        "available_at": "2026-06-14T01:01:00+00:00",
        "event_type": "finance_news",
        "url": "https://finance.baidu.com/news/source-build-1",
        "symbol": "000759.SZ",
        "tags_json": {"st_tags_arr": ["000759"]},
        "stock_refs_json": [{"symbol": "000759.SZ", "provider_symbol": "000759", "exchange": "SZ"}],
    }
    ingest = client.post(
        "/source/raw/ingest-result",
        json={
            "provider": "baidu",
            "api_name": "finance_news_feed",
            "raw_table_name": "raw_baidu.finance_news_feed_v1",
            "request_params": job["request_params"],
            "dry_run": False,
            "row_count": 1,
            "request_hash": request_hash,
            "response_schema_hash": "schema_baidu_news_v1",
            "rows": [
                {
                    "provider": "baidu",
                    "api_name": "finance_news_feed",
                    "raw_table_name": "raw_baidu.finance_news_feed_v1",
                    "request_params": job["request_params"],
                    "row": raw_row,
                    "request_hash": request_hash,
                    "response_schema_hash": "schema_baidu_news_v1",
                    "response_row_hash": "row_baidu_news_source_build_1",
                }
            ],
        },
    )
    assert ingest.status_code == 200
    assert ingest.json()["raw_write_status"] == "accepted"
    done = client.post(
        f"/source/fetch/jobs/{job['job_item_id']}/complete",
        json={"worker_id": "worker-baidu-news", "success": True, "row_count": 1, "raw_request_hash": request_hash},
    )
    assert done.status_code == 200
    triggers = client.get(f"/source/build/triggers?fetch_batch_id={batch_id}").json()
    assert triggers
    execute = client.post(
        f"/source/build/triggers/{triggers[0]['trigger_id']}/execute",
        json={"trigger_id": triggers[0]["trigger_id"], "worker_id": "builder-baidu-news"},
    )
    assert execute.status_code == 200
    payload = execute.json()
    assert payload["status"] == "succeeded"
    assert payload["source_row_count"] == 1
    assert payload["lineage_row_count"] >= 5
    rows = client.get("/source/rows?source_table_name=source.event_news_v1&symbol=000759.SZ").json()
    assert any(row["source_pk"] == "baidu:baidu_news_source_build_1" for row in rows)
    built = next(row for row in rows if row["source_pk"] == "baidu:baidu_news_source_build_1")
    assert built["values"]["title"] == "百度财经样例新闻"
    lineage = client.get(
        "/source/lineage/records?source_table_name=source.event_news_v1&source_pk=baidu:baidu_news_source_build_1"
    ).json()
    assert any(row["canonical_field_name"] == "title" and row["provider"] == "baidu" for row in lineage)


def test_trade_status_source_build_derives_canonical_booleans_from_baostock_raw() -> None:
    client = TestClient(app)
    submit = client.post(
        "/source/fetch/submit",
        json={
            "source_table_name": "source.trade_status_v1",
            "canonical_fields": ["is_tradable", "is_suspended", "is_st", "raw_status"],
            "symbols": ["000762.SZ"],
            "trade_date": "2026-05-29",
            "trigger_type": "model_release_preflight",
            "priority": "P0_urgent_release",
            "request_source": "hot-candidates-service",
            "dry_run": True,
        },
    )
    assert submit.status_code == 200
    batch_id = submit.json()["fetch_batch_id"]
    pull = client.post(
        "/source/fetch/worker/pull",
        json={"worker_id": "worker-trade-status", "max_jobs": 1, "queue_names": ["urgent_release_gate_queue"]},
    )
    assert pull.status_code == 200
    job = pull.json()["jobs"][0]
    request_hash = job["request_hash"]
    raw_row = {
        "date": "2026-05-29",
        "code": "sz.000762",
        "open": "10.00",
        "high": "10.20",
        "low": "9.90",
        "close": "10.10",
        "preclose": "10.00",
        "volume": "100000",
        "amount": "1010000",
        "adjustflag": "3",
        "turn": "1.2",
        "tradestatus": "1",
        "pctChg": "1.00",
        "isST": "0",
    }
    ingest = client.post(
        "/source/raw/ingest-result",
        json={
            "provider": "baostock",
            "api_name": "query_history_k_data_plus_daily_raw",
            "raw_table_name": "raw_baostock.query_history_k_data_plus_daily_raw_v1",
            "request_params": job["request_params"],
            "dry_run": False,
            "row_count": 1,
            "request_hash": request_hash,
            "response_schema_hash": "schema_trade_status_v1",
            "rows": [
                {
                    "provider": "baostock",
                    "api_name": "query_history_k_data_plus_daily_raw",
                    "raw_table_name": "raw_baostock.query_history_k_data_plus_daily_raw_v1",
                    "request_params": job["request_params"],
                    "row": raw_row,
                    "request_hash": request_hash,
                    "response_schema_hash": "schema_trade_status_v1",
                    "response_row_hash": "row_trade_status_000762_20260529",
                }
            ],
        },
    )
    assert ingest.status_code == 200
    assert ingest.json()["raw_write_status"] == "accepted"
    done = client.post(
        f"/source/fetch/jobs/{job['job_item_id']}/complete",
        json={"worker_id": "worker-trade-status", "success": True, "row_count": 1, "raw_request_hash": request_hash},
    )
    assert done.status_code == 200
    triggers = client.get(f"/source/build/triggers?fetch_batch_id={batch_id}").json()
    assert triggers
    execute = client.post(
        f"/source/build/triggers/{triggers[0]['trigger_id']}/execute",
        json={"trigger_id": triggers[0]["trigger_id"], "worker_id": "builder-trade-status"},
    )
    assert execute.status_code == 200
    payload = execute.json()
    assert payload["status"] == "succeeded"
    assert payload["lineage_row_count"] >= 4
    rows = client.get(
        "/source/rows?source_table_name=source.trade_status_v1&symbol=000762.SZ&trade_date=2026-05-29"
    ).json()
    assert rows
    assert rows[0]["values"]["is_tradable"] is True
    assert rows[0]["values"]["is_suspended"] is False
    assert rows[0]["values"]["is_st"] is False
    assert rows[0]["values"]["raw_status"] == "1"
    lineage = client.get(
        "/source/lineage/records?source_table_name=source.trade_status_v1&source_pk=000762.SZ|2026-05-29"
    ).json()
    assert any(row["canonical_field_name"] == "is_tradable" for row in lineage)


def test_trade_status_source_build_derives_tradable_from_tencent_daily_bar_without_st_fill() -> None:
    values, warnings = _build_values(
        Provider.TENCENT,
        "daily_bars",
        "source.trade_status_v1",
        {
            "date": "2026-06-24",
            "symbol": "002051.SZ",
            "open": "12.58",
            "high": "13.63",
            "low": "12.41",
            "close": "13.63",
            "volume": "843088",
        },
        ["is_tradable", "is_suspended", "is_st", "raw_status"],
    )

    assert values["is_tradable"] is True
    assert values["is_suspended"] is False
    assert values["raw_status"] == "daily_bar_present"
    assert "is_st" not in values
    assert any("is_st" in item for item in warnings)


def test_duplicate_raw_job_submit_creates_new_source_build_trigger_for_reused_source_table() -> None:
    client = TestClient(app)
    raw_submit = client.post(
        "/source/fetch/submit",
        json={
            "source_table_name": "source.daily_bar_v1",
            "canonical_fields": ["close_price"],
            "symbols": ["000763.SZ"],
            "trade_date": "2026-05-29",
            "trigger_type": "model_release_preflight",
            "priority": "P0_urgent_release",
            "request_source": "source-data-service-test",
            "dry_run": True,
        },
    )
    assert raw_submit.status_code == 200
    pull = client.post(
        "/source/fetch/worker/pull",
        json={"worker_id": "worker-duplicate-raw", "max_jobs": 1, "queue_names": ["urgent_release_gate_queue"]},
    )
    assert pull.status_code == 200
    raw_job = pull.json()["jobs"][0]
    complete = client.post(
        f"/source/fetch/jobs/{raw_job['job_item_id']}/complete",
        json={
            "worker_id": "worker-duplicate-raw",
            "success": True,
            "row_count": 1,
            "raw_request_hash": "raw-request-000763-daily",
            "raw_response_schema_hash": "schema-000763-daily",
        },
    )
    assert complete.status_code == 200

    trade_submit = client.post(
        "/source/fetch/submit",
        json={
            "source_table_name": "source.trade_status_v1",
            "canonical_fields": ["is_tradable"],
            "symbols": ["000763.SZ"],
            "trade_date": "2026-05-29",
            "trigger_type": "model_release_preflight",
            "priority": "P0_urgent_release",
            "request_source": "hot-candidates-service",
            "dry_run": True,
        },
    )
    assert trade_submit.status_code == 200
    payload = trade_submit.json()
    assert payload["submitted_job_count"] == 0
    assert payload["skipped_duplicate_count"] == 1
    triggers = client.get(f"/source/build/triggers?fetch_batch_id={payload['fetch_batch_id']}").json()
    assert triggers
    assert triggers[0]["source_table_name"] == "source.trade_status_v1"
    assert triggers[0]["job_item_id"] == raw_job["job_item_id"]


def test_active_duplicate_raw_jobs_create_alias_triggers_after_completion() -> None:
    client = TestClient(app)
    symbols = ["000771.SZ", "000772.SZ"]
    trade_submit = client.post(
        "/source/fetch/submit",
        json={
            "source_table_name": "source.trade_status_v1",
            "canonical_fields": ["is_tradable"],
            "symbols": symbols,
            "universe_scope": "stage_candidates",
            "trade_date": "2026-07-03",
            "trigger_type": "model_release_preflight",
            "priority": "P0_urgent_release",
            "request_source": "scheduler-service",
            "dry_run": True,
        },
    )
    assert trade_submit.status_code == 200
    pull = client.post(
        "/source/fetch/worker/pull",
        json={"worker_id": "worker-active-duplicate", "max_jobs": 2, "providers": ["baostock"], "queue_names": ["urgent_release_gate_queue"]},
    )
    assert pull.status_code == 200
    leased_jobs = pull.json()["jobs"]
    assert {job["symbol"] for job in leased_jobs} == set(symbols)

    daily_submit = client.post(
        "/source/fetch/submit",
        json={
            "source_table_name": "source.daily_bar_v1",
            "canonical_fields": ["close_price"],
            "symbols": symbols,
            "universe_scope": "stage_candidates",
            "trade_date": "2026-07-03",
            "trigger_type": "model_release_preflight",
            "priority": "P0_urgent_release",
            "request_source": "scheduler-service",
            "dry_run": True,
        },
    )
    assert daily_submit.status_code == 200
    daily_payload = daily_submit.json()
    assert daily_payload["submitted_job_count"] == 0
    assert daily_payload["skipped_duplicate_count"] == 2
    assert client.get(f"/source/build/triggers?fetch_batch_id={daily_payload['fetch_batch_id']}").json() == []

    for job in leased_jobs:
        status = client.get(f"/source/fetch/jobs/{job['job_item_id']}").json()
        aliases = status["request_params"].get("__source_build_aliases", [])
        assert any(
            alias["fetch_batch_id"] == daily_payload["fetch_batch_id"]
            and alias["source_table_name"] == "source.daily_bar_v1"
            for alias in aliases
        )
        complete = client.post(
            f"/source/fetch/jobs/{job['job_item_id']}/complete",
            json={
                "worker_id": "worker-active-duplicate",
                "success": True,
                "row_count": 1,
                "raw_request_hash": f"raw-request-{job['symbol']}-active-duplicate",
                "raw_response_schema_hash": f"schema-{job['symbol']}-active-duplicate",
            },
        )
        assert complete.status_code == 200

    triggers = client.get(f"/source/build/triggers?fetch_batch_id={daily_payload['fetch_batch_id']}").json()
    assert len(triggers) == 2
    assert {trigger["symbol"] for trigger in triggers} == set(symbols)
    assert {trigger["source_table_name"] for trigger in triggers} == {"source.daily_bar_v1"}
    assert {trigger["build_scope"] for trigger in triggers} == {"symbol_date"}


def test_duplicate_market_batch_uses_planned_identity_for_source_build_trigger() -> None:
    client = TestClient(app)
    legacy_submit = client.post(
        "/source/fetch/submit",
        json={
            "source_table_name": "source.stock_universe_daily_v1",
            "canonical_fields": ["is_tradable", "trade_status"],
            "symbols": ["000063.SZ"],
            "trade_date": "2026-07-02",
            "trigger_type": "scheduled_periodic",
            "priority": "P1_normal_ingest",
            "request_source": "source-data-service-test",
            "dry_run": True,
        },
    )
    assert legacy_submit.status_code == 200
    pull = client.post(
        "/source/fetch/worker/pull",
        json={"worker_id": "worker-duplicate-universe-legacy", "max_jobs": 1, "queue_names": ["normal_daily_ingest_queue"]},
    )
    assert pull.status_code == 200
    legacy_job = pull.json()["jobs"][0]
    assert legacy_job["symbol"] == "000063.SZ"
    complete = client.post(
        f"/source/fetch/jobs/{legacy_job['job_item_id']}/complete",
        json={
            "worker_id": "worker-duplicate-universe-legacy",
            "success": True,
            "row_count": 1,
            "raw_request_hash": "raw-request-universe-20260702",
            "raw_response_schema_hash": "schema-universe-20260702",
        },
    )
    assert complete.status_code == 200

    full_market_submit = client.post(
        "/source/fetch/submit",
        json={
            "source_table_name": "source.stock_universe_daily_v1",
            "canonical_fields": ["is_tradable", "trade_status", "is_st", "is_suspended", "is_delisting_risk"],
            "universe_scope": "full_a_share",
            "trade_date": "2026-07-02",
            "trigger_type": "scheduled_periodic",
            "priority": "P1_normal_ingest",
            "request_source": "scheduler-service",
            "dry_run": False,
            "prefer_batch": True,
        },
    )

    assert full_market_submit.status_code == 200
    payload = full_market_submit.json()
    assert payload["submitted_job_count"] == 0
    assert payload["skipped_duplicate_count"] == 1
    triggers = client.get(f"/source/build/triggers?fetch_batch_id={payload['fetch_batch_id']}").json()
    assert len(triggers) == 1
    assert triggers[0]["job_item_id"] == legacy_job["job_item_id"]
    assert triggers[0]["source_table_name"] == "source.stock_universe_daily_v1"
    assert triggers[0]["build_scope"] == "batch"
    assert triggers[0]["symbol"] is None
    assert triggers[0]["trade_date"] == "2026-07-02"

    ingest = ingest_raw_fetch_result(
        RawFetchResult(
            provider=Provider(legacy_job["provider"]),
            api_name=legacy_job["api_name"],
            raw_table_name=legacy_job["raw_table_name"],
            request_params=legacy_job["request_params"],
            dry_run=False,
            row_count=2,
            request_hash="raw-request-universe-20260702",
            response_schema_hash="schema-universe-20260702",
            rows=[
                RawRow(
                    provider=Provider(legacy_job["provider"]),
                    api_name=legacy_job["api_name"],
                    raw_table_name=legacy_job["raw_table_name"],
                    request_params=legacy_job["request_params"],
                    row={"date": "2026-07-02", "code": "sh.600000", "code_name": "stock-a", "tradeStatus": "1", "isST": "0"},
                    request_hash="raw-request-universe-20260702",
                    response_schema_hash="schema-universe-20260702",
                    response_row_hash="row-universe-a-share",
                    batch_id=legacy_submit.json()["fetch_batch_id"],
                    available_at=datetime(2026, 7, 2, 1, 20, tzinfo=timezone.utc),
                ),
                RawRow(
                    provider=Provider(legacy_job["provider"]),
                    api_name=legacy_job["api_name"],
                    raw_table_name=legacy_job["raw_table_name"],
                    request_params=legacy_job["request_params"],
                    row={"date": "2026-07-02", "code": "sh.000001", "code_name": "index-a", "tradeStatus": "1", "isST": "0"},
                    request_hash="raw-request-universe-20260702",
                    response_schema_hash="schema-universe-20260702",
                    response_row_hash="row-universe-index",
                    batch_id=legacy_submit.json()["fetch_batch_id"],
                    available_at=datetime(2026, 7, 2, 1, 20, tzinfo=timezone.utc),
                ),
            ],
        )
    )
    assert ingest.raw_write_status.startswith("accepted")
    first_build = execute_source_build_trigger(
        SourceBuildExecuteRequest(trigger_id=triggers[0]["trigger_id"], worker_id="builder-duplicate-universe-first")
    )
    assert first_build.status == "succeeded"
    assert first_build.source_row_count == 1

    rebuild_submit = client.post(
        "/source/fetch/submit",
        json={
            "source_table_name": "source.stock_universe_daily_v1",
            "canonical_fields": ["is_tradable", "trade_status", "is_st", "is_suspended", "is_delisting_risk"],
            "universe_scope": "full_a_share",
            "trade_date": "2026-07-02",
            "trigger_type": "scheduled_periodic",
            "priority": "P1_normal_ingest",
            "request_source": "scheduler-service",
            "dry_run": False,
            "prefer_batch": True,
        },
    )
    assert rebuild_submit.status_code == 200
    rebuild_payload = rebuild_submit.json()
    assert rebuild_payload["fetch_batch_id"] != payload["fetch_batch_id"]
    assert rebuild_payload["submitted_job_count"] == 0
    assert rebuild_payload["skipped_duplicate_count"] == 1
    rebuild_triggers = client.get(f"/source/build/triggers?fetch_batch_id={rebuild_payload['fetch_batch_id']}").json()
    assert len(rebuild_triggers) == 1
    assert rebuild_triggers[0]["job_item_id"] == legacy_job["job_item_id"]
    assert rebuild_triggers[0]["build_scope"] == "batch"
    assert rebuild_triggers[0]["symbol"] is None

    build_worker = client.post(
        "/source/build/worker/run-once",
        json={
            "worker_id": "builder-duplicate-universe-rebuild",
            "max_triggers": 10,
            "source_table_names": ["source.stock_universe_daily_v1"],
            "dry_run": True,
        },
    )
    assert build_worker.status_code == 200
    worker_payload = build_worker.json()
    assert any(result["trigger_id"] == rebuild_triggers[0]["trigger_id"] for result in worker_payload["results"])


def test_duplicate_failed_raw_job_requeues_backup_for_new_source_table() -> None:
    client = TestClient(app)
    first = client.post(
        "/source/fetch/submit",
        json={
            "source_table_name": "source.daily_bar_v1",
            "canonical_fields": ["close_price"],
            "symbols": ["000766.SZ"],
            "trade_date": "2026-05-29",
            "trigger_type": "model_release_preflight",
            "priority": "P0_urgent_release",
            "request_source": "source-data-service-test",
            "dry_run": True,
        },
    )
    assert first.status_code == 200
    pull_primary = client.post(
        "/source/fetch/worker/pull",
        json={"worker_id": "worker-duplicate-failed-primary", "max_jobs": 1, "providers": ["baostock"], "queue_names": ["urgent_release_gate_queue"]},
    )
    assert pull_primary.status_code == 200
    primary_job = pull_primary.json()["jobs"][0]
    fail_primary = client.post(
        f"/source/fetch/jobs/{primary_job['job_item_id']}/complete",
        json={
            "worker_id": "worker-duplicate-failed-primary",
            "success": False,
            "error_code": "provider_timeout",
            "error_message": "primary provider timeout",
        },
    )
    assert fail_primary.status_code == 200
    assert fail_primary.json()["status"] == "failed"

    pull_backup = client.post(
        "/source/fetch/worker/pull",
        json={"worker_id": "worker-duplicate-failed-backup", "max_jobs": 1, "providers": ["tencent"], "queue_names": ["urgent_release_gate_queue"]},
    )
    assert pull_backup.status_code == 200
    backup_job = pull_backup.json()["jobs"][0]
    fail_backup = client.post(
        f"/source/fetch/jobs/{backup_job['job_item_id']}/complete",
        json={
            "worker_id": "worker-duplicate-failed-backup",
            "success": False,
            "error_code": "provider_timeout",
            "error_message": "backup provider timeout",
        },
    )
    assert fail_backup.status_code == 200
    assert fail_backup.json()["status"] == "failed"

    trade_submit = client.post(
        "/source/fetch/submit",
        json={
            "source_table_name": "source.trade_status_v1",
            "canonical_fields": ["is_tradable"],
            "symbols": ["000766.SZ"],
            "trade_date": "2026-05-29",
            "trigger_type": "model_release_preflight",
            "priority": "P0_urgent_release",
            "request_source": "hot-candidates-service",
            "dry_run": True,
        },
    )
    assert trade_submit.status_code == 200
    payload = trade_submit.json()
    assert payload["submitted_job_count"] == 1
    assert payload["skipped_duplicate_count"] == 0
    callbacks = client.get(f"/source/fetch/callbacks?fetch_batch_id={payload['fetch_batch_id']}").json()
    assert any(event["event_type"] == "backup_job_queued" and event["payload"].get("reused_existing_job") for event in callbacks)

    requeued = client.get(f"/source/fetch/jobs/{backup_job['job_item_id']}").json()
    assert requeued["status"] == "queued"
    aliases = requeued["request_params"].get("__source_build_aliases", [])
    assert any(
        item["fetch_batch_id"] == payload["fetch_batch_id"]
        and item["source_table_name"] == "source.trade_status_v1"
        for item in aliases
    )

    pull_requeued = client.post(
        "/source/fetch/worker/pull",
        json={"worker_id": "worker-duplicate-failed-backup-retry", "max_jobs": 1, "providers": ["tencent"], "queue_names": ["urgent_release_gate_queue"]},
    )
    assert pull_requeued.status_code == 200
    assert pull_requeued.json()["leased_count"] == 1
    assert pull_requeued.json()["jobs"][0]["job_item_id"] == backup_job["job_item_id"]
    complete_requeued = client.post(
        f"/source/fetch/jobs/{backup_job['job_item_id']}/complete",
        json={
            "worker_id": "worker-duplicate-failed-backup-retry",
            "success": True,
            "row_count": 1,
            "raw_request_hash": "raw-request-000766-tencent-daily",
            "raw_response_schema_hash": "schema-000766-tencent-daily",
        },
    )
    assert complete_requeued.status_code == 200
    triggers = client.get(f"/source/build/triggers?fetch_batch_id={payload['fetch_batch_id']}").json()
    assert any(
        trigger["source_table_name"] == "source.trade_status_v1"
        and trigger["job_item_id"] == backup_job["job_item_id"]
        for trigger in triggers
    )


def test_duplicate_failed_backup_for_same_source_table_does_not_requeue_loop() -> None:
    client = TestClient(app)
    first = client.post(
        "/source/fetch/submit",
        json={
            "source_table_name": "source.daily_bar_v1",
            "canonical_fields": ["close_price"],
            "symbols": ["000767.SZ"],
            "trade_date": "2026-05-29",
            "trigger_type": "model_release_preflight",
            "priority": "P0_urgent_release",
            "request_source": "source-data-service-test",
            "dry_run": True,
        },
    )
    assert first.status_code == 200
    pull_primary = client.post(
        "/source/fetch/worker/pull",
        json={"worker_id": "worker-same-source-primary", "max_jobs": 1, "providers": ["baostock"], "queue_names": ["urgent_release_gate_queue"]},
    )
    assert pull_primary.status_code == 200
    primary_job = pull_primary.json()["jobs"][0]
    fail_primary = client.post(
        f"/source/fetch/jobs/{primary_job['job_item_id']}/complete",
        json={
            "worker_id": "worker-same-source-primary",
            "success": False,
            "error_code": "provider_timeout",
            "error_message": "primary provider timeout",
        },
    )
    assert fail_primary.status_code == 200

    pull_backup = client.post(
        "/source/fetch/worker/pull",
        json={"worker_id": "worker-same-source-backup", "max_jobs": 1, "providers": ["tencent"], "queue_names": ["urgent_release_gate_queue"]},
    )
    assert pull_backup.status_code == 200
    backup_job = pull_backup.json()["jobs"][0]
    fail_backup = client.post(
        f"/source/fetch/jobs/{backup_job['job_item_id']}/complete",
        json={
            "worker_id": "worker-same-source-backup",
            "success": False,
            "error_code": "provider_timeout",
            "error_message": "backup provider timeout",
        },
    )
    assert fail_backup.status_code == 200
    assert fail_backup.json()["status"] == "failed"

    duplicate_same_source = client.post(
        "/source/fetch/submit",
        json={
            "source_table_name": "source.daily_bar_v1",
            "canonical_fields": ["close_price"],
            "symbols": ["000767.SZ"],
            "trade_date": "2026-05-29",
            "trigger_type": "model_release_preflight",
            "priority": "P0_urgent_release",
            "request_source": "source-data-service-test",
            "dry_run": True,
        },
    )
    assert duplicate_same_source.status_code == 200
    payload = duplicate_same_source.json()
    assert payload["submitted_job_count"] == 0
    assert payload["skipped_duplicate_count"] == 1

    terminal_backup = client.get(f"/source/fetch/jobs/{backup_job['job_item_id']}").json()
    assert terminal_backup["status"] == "failed"
    callbacks = client.get(f"/source/fetch/callbacks?fetch_batch_id={payload['fetch_batch_id']}").json()
    assert not any(
        event["event_type"] == "backup_job_queued"
        and event["payload"].get("backup_job_item_id") == backup_job["job_item_id"]
        for event in callbacks
    )


def test_duplicate_unusable_success_queues_backup_in_new_batch() -> None:
    client = TestClient(app)
    first = client.post(
        "/source/fetch/submit",
        json={
            "source_table_name": "source.minute_bar_v1",
            "canonical_fields": ["close_price"],
            "symbols": ["000765.SZ"],
            "trade_date": "2026-05-29",
            "trigger_type": "model_release_preflight",
            "priority": "P0_urgent_release",
            "request_source": "hot-candidates-service",
            "dry_run": True,
        },
    )
    assert first.status_code == 200
    pull = client.post(
        "/source/fetch/worker/pull",
        json={"worker_id": "worker-duplicate-empty", "max_jobs": 1, "providers": ["eastmoney"], "queue_names": ["urgent_release_gate_queue"]},
    )
    assert pull.status_code == 200
    primary_job = pull.json()["jobs"][0]
    complete = client.post(
        f"/source/fetch/jobs/{primary_job['job_item_id']}/complete",
        json={"worker_id": "worker-duplicate-empty", "success": True, "row_count": 0},
    )
    assert complete.status_code == 200
    assert complete.json()["status"] == "succeeded"

    second = client.post(
        "/source/fetch/submit",
        json={
            "source_table_name": "source.minute_bar_v1",
            "canonical_fields": ["close_price"],
            "symbols": ["000765.SZ"],
            "trade_date": "2026-05-29",
            "trigger_type": "model_release_preflight",
            "priority": "P0_urgent_release",
            "request_source": "hot-candidates-service",
            "dry_run": True,
        },
    )
    assert second.status_code == 200
    payload = second.json()
    assert payload["submitted_job_count"] == 1
    assert payload["skipped_duplicate_count"] == 0
    callbacks = client.get(f"/source/fetch/callbacks?fetch_batch_id={payload['fetch_batch_id']}").json()
    assert any(event["event_type"] == "backup_job_queued" for event in callbacks)

    pull_backup = client.post(
        "/source/fetch/worker/pull",
        json={"worker_id": "worker-duplicate-empty-backup", "max_jobs": 1, "providers": ["tencent"], "queue_names": ["urgent_release_gate_queue"]},
    ).json()
    assert pull_backup["leased_count"] == 1
    backup_job = pull_backup["jobs"][0]
    assert backup_job["backup_of_job_item_id"] == primary_job["job_item_id"]

    complete_backup = client.post(
        f"/source/fetch/jobs/{backup_job['job_item_id']}/complete",
        json={"worker_id": "worker-duplicate-empty-backup", "success": True, "row_count": 0},
    )
    assert complete_backup.status_code == 200
    assert complete_backup.json()["status"] == "succeeded"
    assert complete_backup.json()["raw_request_hash"] is None

    third = client.post(
        "/source/fetch/submit",
        json={
            "source_table_name": "source.minute_bar_v1",
            "canonical_fields": ["close_price"],
            "symbols": ["000765.SZ"],
            "trade_date": "2026-05-29",
            "trigger_type": "model_release_preflight",
            "priority": "P0_urgent_release",
            "request_source": "hot-candidates-service",
            "dry_run": True,
        },
    )
    assert third.status_code == 200
    third_payload = third.json()
    assert third_payload["submitted_job_count"] == 1
    third_callbacks = client.get(f"/source/fetch/callbacks?fetch_batch_id={third_payload['fetch_batch_id']}").json()
    assert any(event["event_type"] == "backup_job_queued" and event["payload"].get("reused_existing_job") for event in third_callbacks)

    requeued = client.get(f"/source/fetch/jobs/{backup_job['job_item_id']}").json()
    assert requeued["status"] == "queued"
    pull_requeued = client.post(
        "/source/fetch/worker/pull",
        json={"worker_id": "worker-duplicate-empty-backup-retry", "max_jobs": 1, "providers": ["tencent"], "queue_names": ["urgent_release_gate_queue"]},
    ).json()
    assert pull_requeued["leased_count"] == 1
    assert pull_requeued["jobs"][0]["job_item_id"] == backup_job["job_item_id"]


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
    requirement_rows = requirements.json()
    assert any(row["source_table_name"] == "source.adjusted_daily_bar_v1" for row in requirement_rows)
    moneyflow_requirement = next(
        row
        for row in requirement_rows
        if row["source_table_name"] == "source.stock_moneyflow_daily_v1"
        and row["canonical_field_name"] == "main_net_inflow"
    )
    assert moneyflow_requirement["required_level"] == "P1"
    assert moneyflow_requirement["degrade_policy"] == "degrade"
    assert moneyflow_requirement["required_for_official_signal"] is False
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
    assert freshness.json()["rows"][0]["freshness_status"] == "fresh"
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


def test_ds7_acceptance_script_uses_settled_daily_probe_dates() -> None:
    import importlib.util
    from pathlib import Path

    path = Path("scripts/source_data_acceptance.py")
    spec = importlib.util.spec_from_file_location("source_data_acceptance", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    today = date(2026, 6, 17)
    baostock_daily = {
        "provider": "baostock",
        "api_name": "query_history_k_data_plus_daily_raw",
        "sample_params": {
            "code": "sz.000759",
            "start_date": "YYYY-MM-DD",
            "end_date": "YYYY-MM-DD",
        },
    }
    params = module.materialize_probe_params(baostock_daily, "2026-06-17", today=today)
    assert params["start_date"] == "2026-06-16"
    assert params["end_date"] == "2026-06-16"

    sohu_daily = {
        "provider": "sohu",
        "api_name": "daily_bars",
        "sample_params": {
            "provider_code": "cn_000063",
            "start_date": "YYYYMMDD",
            "end_date": "YYYYMMDD",
        },
    }
    sohu_params = module.materialize_probe_params(sohu_daily, "2026-06-14", today=today)
    assert sohu_params["start_date"] == "20260612"
    assert sohu_params["end_date"] == "20260612"

    minute = {
        "provider": "tencent",
        "api_name": "minute_bars",
        "sample_params": {"provider_code": "sz000759", "trade_date": "YYYY-MM-DD"},
    }
    minute_params = module.materialize_probe_params(minute, "2026-06-17", today=today)
    assert minute_params["trade_date"] == "2026-06-17"
    historical_minute_params = module.materialize_probe_params(minute, "2026-06-12", today=today)
    assert historical_minute_params["trade_date"] == "2026-06-17"


def test_ds7_acceptance_real_probe_summary_accepts_recent_readiness_evidence() -> None:
    import importlib.util
    from pathlib import Path

    path = Path("scripts/source_data_acceptance.py")
    spec = importlib.util.spec_from_file_location("source_data_acceptance", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    failed_probe = [
        {
            "provider": "tencent",
            "api_name": "minute_bars",
            "raw_table_name": "raw_tencent.minute_bars_v1",
            "row_count": 0,
            "usable_for_source_table": False,
            "reject_reason": "missing expected fields",
        }
    ]
    readiness = {
        "status": "passed",
        "checks": [
            {
                "check_code": "real_provider_probe_evidence",
                "evidence": {"all_required_probes_usable": True, "probe_evidence_ttl_hours": 72},
            }
        ],
    }
    summary = module.summarize_real_provider_probe(failed_probe, readiness)
    assert summary["status"] == "passed"
    assert summary["immediate_status"] == "blocked"
    assert summary["immediate_failed"][0]["provider"] == "tencent"

    blocked = module.summarize_real_provider_probe(failed_probe, {"status": "blocked", "checks": []})
    assert blocked["status"] == "blocked"


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


def test_eastmoney_minute_event_time_accepts_hour_minute_text() -> None:
    from source_data_service.adapters.eastmoney_adapter import _event_time

    assert _event_time("09:30", fallback_date="2026-06-12") == "2026-06-12T09:30:00+08:00"


def test_eastmoney_minute_rows_use_each_trend_datetime(monkeypatch) -> None:
    from source_data_service.adapters import eastmoney_adapter

    monkeypatch.setattr(
        eastmoney_adapter,
        "_eastmoney_json",
        lambda _url, _params: {
            "data": {
                "trends": [
                    "2026-06-12 09:30,5.29,5.29,5.29,5.29,14930,7897970.00,5.290",
                    "2026-06-12 14:59,5.83,5.83,5.83,5.83,0,0.00,5.439",
                ]
            }
        },
    )

    rows = eastmoney_adapter._minute_bars_rows(
        {"secid": "0.000759", "start_date": "2026-06-12", "end_date": "2026-06-12"}
    )

    assert rows[0]["bar_time"] == "2026-06-12T09:30:00+08:00"
    assert rows[1]["bar_time"] == "2026-06-12T14:59:00+08:00"
