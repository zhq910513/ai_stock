from __future__ import annotations

from datetime import datetime, time, timezone
from typing import Any

from source_data_service.gap_detector import build_repair_plan
from source_data_service.models import (
    ModelCoverageCheckRequest,
    ModelCoverageCheckResult,
    ModelCoverageFieldStatus,
    ModelSourceRequirement,
    Provider,
    ReleasePreflightRequest,
    ReleasePreflightResult,
    RequiredLevel,
    SourceFreshnessSla,
    SourceFreshnessStatusRequest,
    SourceFreshnessStatusResult,
    SourceFreshnessStatusRow,
    SourceGapRequest,
    SourceStoragePolicy,
)
from source_data_service.source_repository import list_source_rows


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


FRESHNESS_SLA: list[SourceFreshnessSla] = [
    SourceFreshnessSla(
        source_table_name="source.daily_bar_v1",
        canonical_field_name="close_price",
        frequency="daily",
        market_phase="after_close",
        expected_available_time="15:35",
        latest_acceptable_time="16:30",
        used_by_models=["hot_candidates", "candidate_memory", "ambush_watchlist"],
        required_for_release_gate=True,
        stale_after_minutes=60,
        late_policy="block_official_release",
        fallback_policy="use backup daily raw provider and rebuild source.daily_bar_v1",
        comment="Raw unadjusted close is P0 for real performance calculation, limit status and buy-point evaluation.",
    ),
    SourceFreshnessSla(
        source_table_name="source.adjusted_daily_bar_v1",
        canonical_field_name="adjusted_close",
        frequency="daily",
        market_phase="after_close",
        expected_available_time="15:45",
        latest_acceptable_time="17:00",
        used_by_models=["candidate_memory", "ambush_watchlist"],
        required_for_release_gate=True,
        stale_after_minutes=90,
        late_policy="block_official_release",
        fallback_policy="use qfq backup provider and mark adjustment audit required",
        comment="Adjusted close is P0 for model-three pattern library and historical memory observation.",
    ),
    SourceFreshnessSla(
        source_table_name="source.trade_status_v1",
        canonical_field_name="is_tradable",
        frequency="daily",
        market_phase="preopen_and_after_close",
        expected_available_time="09:10",
        latest_acceptable_time="09:20",
        used_by_models=["hot_candidates", "candidate_memory", "ambush_watchlist"],
        required_for_release_gate=True,
        stale_after_minutes=20,
        late_policy="block_official_release",
        fallback_policy="use exchange/trade calendar backup and block symbols with unknown status",
        comment="Unknown suspension/ST/delisting risk must block official signals instead of being treated as tradable.",
    ),
    SourceFreshnessSla(
        source_table_name="source.stock_moneyflow_daily_v1",
        canonical_field_name="net_mf_amount",
        frequency="daily",
        market_phase="after_close",
        expected_available_time="16:15",
        latest_acceptable_time="18:00",
        used_by_models=["hot_candidates", "candidate_memory", "ambush_watchlist"],
        required_for_release_gate=False,
        stale_after_minutes=180,
        late_policy="degrade",
        fallback_policy="degrade model explanation and mark moneyflow evidence gap",
        comment="Free moneyflow has provider口径差异；缺失时降级，不阻断 P0 release。",
    ),
]


STORAGE_POLICIES: list[SourceStoragePolicy] = [
    SourceStoragePolicy(
        table_name="raw_baostock.query_history_k_data_plus_daily_raw_v1",
        table_layer="raw",
        partition_key="trade_date",
        partition_granularity="monthly",
        retention_hot_days=90,
        archive_enabled=True,
        archive_target="minio://ai-stock-raw-archive/baostock/history_k_daily_raw/",
        required_indexes=["(symbol, trade_date)", "(request_hash)", "(captured_at)", "UNIQUE(provider, api_name, symbol, trade_date, frequency, adjustflag)"],
        expected_daily_rows=5500,
        expected_total_rows_1y=1_350_000,
        expected_total_rows_10y=13_500_000,
        comment="A 股全市场日线原接口表，必须分区和幂等写入，历史 payload 冷归档。",
    ),
    SourceStoragePolicy(
        table_name="source.daily_bar_v1",
        table_layer="source",
        partition_key="trade_date",
        partition_granularity="monthly",
        retention_hot_days=3650,
        archive_enabled=False,
        required_indexes=["UNIQUE(symbol, trade_date)", "(trade_date)", "(source_quality_status)", "(available_at)"],
        expected_daily_rows=5500,
        expected_total_rows_1y=1_350_000,
        expected_total_rows_10y=13_500_000,
        comment="模型正式读取的未复权日K标准事实表，热数据长期保留。",
    ),
    SourceStoragePolicy(
        table_name="governance.source_lineage_v1",
        table_layer="governance",
        partition_key="build_batch_id",
        partition_granularity="monthly",
        retention_hot_days=365,
        archive_enabled=True,
        archive_target="minio://ai-stock-lineage-archive/source_lineage/",
        required_indexes=["(source_table_name, source_pk, canonical_field_name)", "(provider, api_name, request_hash)", "(build_batch_id)"],
        expected_daily_rows=120_000,
        expected_total_rows_1y=30_000_000,
        expected_total_rows_10y=300_000_000,
        comment="血缘可能比行情表更大，生产上只对 P0/P1、异常、修复和主备冲突字段保留字段级明细。",
    ),
]


MODEL_REQUIREMENTS: list[ModelSourceRequirement] = [
    ModelSourceRequirement(
        model_code="hot_candidates",
        model_phase="preopen_release_gate",
        source_table_name="source.daily_bar_v1",
        canonical_field_name="close_price",
        required_level=RequiredLevel.P0,
        required_for_official_signal=True,
        required_for_backtest=True,
        required_for_research=True,
        degrade_policy="block",
        minimum_symbol_coverage_rate=0.995,
        minimum_date_coverage_rate=0.995,
        minimum_field_coverage_rate=0.995,
        comment="热点模型需要上一交易日未复权收盘价和真实行情口径。",
    ),
    ModelSourceRequirement(
        model_code="hot_candidates",
        model_phase="preopen_release_gate",
        source_table_name="source.trade_status_v1",
        canonical_field_name="is_tradable",
        required_level=RequiredLevel.P0,
        required_for_official_signal=True,
        required_for_backtest=True,
        required_for_research=True,
        degrade_policy="block",
        minimum_symbol_coverage_rate=0.999,
        minimum_date_coverage_rate=0.999,
        minimum_field_coverage_rate=0.999,
        comment="交易状态未知不能进入 official release。",
    ),
    ModelSourceRequirement(
        model_code="candidate_memory",
        model_phase="outcome_label",
        source_table_name="source.daily_bar_v1",
        canonical_field_name="close_price",
        required_level=RequiredLevel.P0,
        required_for_official_signal=True,
        required_for_backtest=True,
        required_for_research=True,
        degrade_policy="block",
        minimum_symbol_coverage_rate=0.995,
        minimum_date_coverage_rate=0.995,
        minimum_field_coverage_rate=0.995,
        comment="候选记忆模型观察和结果标签必须有完整价格路径。",
    ),
    ModelSourceRequirement(
        model_code="ambush_watchlist",
        model_phase="release_gate",
        source_table_name="source.adjusted_daily_bar_v1",
        canonical_field_name="adjusted_close",
        required_level=RequiredLevel.P0,
        required_for_official_signal=True,
        required_for_backtest=True,
        required_for_research=True,
        degrade_policy="block",
        minimum_symbol_coverage_rate=0.995,
        minimum_date_coverage_rate=0.995,
        minimum_field_coverage_rate=0.995,
        comment="模型三低谷图库、形态相似、抬头结构必须读取复权行情。",
    ),
    ModelSourceRequirement(
        model_code="ambush_watchlist",
        model_phase="release_gate",
        source_table_name="source.daily_bar_v1",
        canonical_field_name="close_price",
        required_level=RequiredLevel.P0,
        required_for_official_signal=True,
        required_for_backtest=True,
        required_for_research=True,
        degrade_policy="block",
        minimum_symbol_coverage_rate=0.995,
        minimum_date_coverage_rate=0.995,
        minimum_field_coverage_rate=0.995,
        comment="模型三真实交易状态、买点评估、涨跌停识别必须使用未复权真实价格。",
    ),
    ModelSourceRequirement(
        model_code="ambush_watchlist",
        model_phase="release_gate",
        source_table_name="source.stock_moneyflow_daily_v1",
        canonical_field_name="net_mf_amount",
        required_level=RequiredLevel.P1,
        required_for_official_signal=False,
        required_for_backtest=True,
        required_for_research=True,
        degrade_policy="degrade",
        minimum_symbol_coverage_rate=0.85,
        minimum_date_coverage_rate=0.85,
        minimum_field_coverage_rate=0.85,
        comment="资金流缺失可降级为 evidence_gap，不阻断模型三 P0 release。",
    ),
]


def list_freshness_sla(source_table_name: str | None = None) -> list[SourceFreshnessSla]:
    rows = FRESHNESS_SLA
    if source_table_name:
        rows = [row for row in rows if row.source_table_name == source_table_name]
    return rows


def list_storage_policies(table_name: str | None = None) -> list[SourceStoragePolicy]:
    rows = STORAGE_POLICIES
    if table_name:
        rows = [row for row in rows if row.table_name == table_name]
    return rows


def list_model_requirements(model_code: str | None = None, model_phase: str | None = None) -> list[ModelSourceRequirement]:
    rows = MODEL_REQUIREMENTS
    if model_code:
        rows = [row for row in rows if row.model_code == model_code]
    if model_phase:
        rows = [row for row in rows if row.model_phase == model_phase]
    return rows


def _coverage_for(req: ModelSourceRequirement, symbols: list[str], trade_date: str) -> ModelCoverageFieldStatus:
    universe = symbols or []
    missing: list[str] = []
    covered = 0
    if universe:
        for symbol in universe:
            rows = list_source_rows(req.source_table_name, symbol=symbol, trade_date=trade_date)
            has_value = any(row.values.get(req.canonical_field_name) is not None for row in rows)
            if has_value:
                covered += 1
            else:
                missing.append(symbol)
    else:
        rows = list_source_rows(req.source_table_name, trade_date=trade_date)
        covered = 1 if any(row.values.get(req.canonical_field_name) is not None for row in rows) else 0
        missing = [] if covered else ["<universe_not_supplied>"]
        universe = ["<any>"]
    rate = covered / max(len(universe), 1)
    if rate >= req.minimum_symbol_coverage_rate:
        status = "passed"
    elif req.degrade_policy == "block" and req.required_for_official_signal:
        status = "blocked"
    elif req.degrade_policy == "research_only":
        status = "research_only"
    else:
        status = "degraded"
    repair_hint = None
    if missing:
        try:
            plan = build_repair_plan(SourceGapRequest(source_table_name=req.source_table_name, canonical_field_name=req.canonical_field_name, symbol=missing[0], trade_date=trade_date))  # type: ignore[arg-type]
            repair_hint = {"provider": plan.primary_repair.provider.value, "api_name": plan.primary_repair.api_name, "raw_table_name": plan.primary_repair.raw_table_name, "params": plan.primary_repair.params}
        except Exception:
            repair_hint = None
    return ModelCoverageFieldStatus(
        source_table_name=req.source_table_name,
        canonical_field_name=req.canonical_field_name,
        required_level=req.required_level,
        required_for_official_signal=req.required_for_official_signal,
        coverage_rate=rate,
        covered_symbol_count=covered,
        missing_symbol_count=len(missing),
        status=status,  # type: ignore[arg-type]
        missing_symbols=missing,
        repair_route_hint=repair_hint,
    )


def check_model_coverage(request: ModelCoverageCheckRequest) -> ModelCoverageCheckResult:
    reqs = [r for r in list_model_requirements(request.model_code, request.model_phase) if r.required_level in set(request.required_levels)]
    rows = [_coverage_for(req, request.symbols, str(request.trade_date)) for req in reqs]
    blocking = [f"{r.source_table_name}.{r.canonical_field_name}" for r in rows if r.status == "blocked"]
    degraded = [f"{r.source_table_name}.{r.canonical_field_name}" for r in rows if r.status == "degraded"]
    if blocking:
        status = "blocked"
    elif degraded:
        status = "degraded"
    elif not rows:
        status = "research_only"
    else:
        status = "passed"
    p0 = [r for r in rows if r.required_level == RequiredLevel.P0]
    p1 = [r for r in rows if r.required_level == RequiredLevel.P1]
    return ModelCoverageCheckResult(
        model_code=request.model_code,
        model_phase=request.model_phase,
        trade_date=request.trade_date,
        universe_size=len(request.symbols),
        p0_field_count=len(p0),
        p0_passed_field_count=sum(1 for r in p0 if r.status == "passed"),
        p1_field_count=len(p1),
        p1_passed_field_count=sum(1 for r in p1 if r.status == "passed"),
        coverage_status=status,  # type: ignore[arg-type]
        blocking_fields=blocking,
        degraded_fields=degraded,
        rows=rows,
        checked_at=utcnow(),
    )


def check_freshness(request: SourceFreshnessStatusRequest) -> SourceFreshnessStatusResult:
    slas = [s for s in list_freshness_sla(request.source_table_name) if not request.canonical_fields or s.canonical_field_name in request.canonical_fields]
    checked = utcnow()
    rows: list[SourceFreshnessStatusRow] = []
    blockers: list[str] = []
    symbols = request.symbols or [None]
    for sla in slas:
        for symbol in symbols:
            source_rows = list_source_rows(sla.source_table_name, symbol=symbol, trade_date=str(request.trade_date)) if symbol else list_source_rows(sla.source_table_name, trade_date=str(request.trade_date))
            available_times = [row.available_at for row in source_rows if row.values.get(sla.canonical_field_name) is not None and row.available_at is not None]
            latest = max(available_times) if available_times else None
            if latest is None:
                status = "missing"
                reason = "no canonical source row or field value found"
            else:
                lag_minutes = max(0, int((checked - latest).total_seconds() // 60))
                if lag_minutes <= sla.stale_after_minutes:
                    status = "fresh"
                    reason = f"latest available_at age={lag_minutes}m within stale_after={sla.stale_after_minutes}m"
                else:
                    status = "stale"
                    reason = f"latest available_at age={lag_minutes}m exceeds stale_after={sla.stale_after_minutes}m"
            blocking = status in {"missing", "stale"} and sla.late_policy == "block_official_release"
            if blocking:
                blockers.append(f"{sla.source_table_name}.{sla.canonical_field_name}:{symbol or '<any>'}:{status}")
            rows.append(
                SourceFreshnessStatusRow(
                    source_table_name=sla.source_table_name,
                    canonical_field_name=sla.canonical_field_name,
                    symbol=symbol,
                    trade_date=request.trade_date,
                    freshness_status=status,  # type: ignore[arg-type]
                    latest_data_available_at=latest,
                    stale_after_minutes=sla.stale_after_minutes,
                    affected_models=sla.used_by_models,
                    blocking_release_gate=blocking,
                    reason=reason,
                )
            )
    overall = "blocked" if blockers else ("passed" if all(r.freshness_status == "fresh" for r in rows) else "degraded")
    return SourceFreshnessStatusResult(checked_at=checked, status=overall, rows=rows, blocking_reasons=blockers)  # type: ignore[arg-type]


def preflight_release(request: ReleasePreflightRequest) -> ReleasePreflightResult:
    coverage = check_model_coverage(
        ModelCoverageCheckRequest(
            model_code=request.model_code,
            model_phase=request.model_phase,
            trade_date=request.trade_date,
            symbols=request.symbols,
            required_levels=[RequiredLevel.P0, RequiredLevel.P1],
        )
    )
    # Check freshness for the P0/P1 fields used by this model phase.
    freshness_results = []
    for req in list_model_requirements(request.model_code, request.model_phase):
        freshness_results.append(
            check_freshness(
                SourceFreshnessStatusRequest(
                    source_table_name=req.source_table_name,
                    canonical_fields=[req.canonical_field_name],
                    symbols=request.symbols,
                    trade_date=request.trade_date,
                    decision_time=request.decision_time,
                )
            )
        )
    freshness_blockers = [reason for result in freshness_results for reason in result.blocking_reasons]
    freshness_status = "blocked" if freshness_blockers else ("passed" if all(r.status == "passed" for r in freshness_results) else "degraded")
    blocking = list(coverage.blocking_fields) + freshness_blockers
    degraded = list(coverage.degraded_fields)
    repair_actions: list[dict[str, Any]] = []
    for row in coverage.rows:
        if row.repair_route_hint and row.status in {"blocked", "degraded"}:
            repair_actions.append(row.repair_route_hint)
    return ReleasePreflightResult(
        model_code=request.model_code,
        model_phase=request.model_phase,
        trade_date=request.trade_date,
        can_release_official_signal=not blocking,
        coverage_status=coverage.coverage_status,
        freshness_status=freshness_status,  # type: ignore[arg-type]
        blocking_reasons=blocking,
        degraded_reasons=degraded,
        repair_actions=repair_actions,
        checked_at=utcnow(),
    )
