from __future__ import annotations

from source_data_service.models import Provider, RepairApiPlan, SourceGapRepairPlan, SourceGapRequest
from source_data_service.provider_registry import build_provider_code, format_date_for_provider, get_api_spec, get_requirement


def _date_range_params(request: SourceGapRequest, provider: Provider) -> dict[str, str]:
    start = request.start_date or request.trade_date
    end = request.end_date or request.trade_date or request.start_date
    if not start or not end:
        return {}
    if provider == Provider.BAOSTOCK:
        return {"start_date": format_date_for_provider(start, provider), "end_date": format_date_for_provider(end, provider)}
    return {"start_date": format_date_for_provider(start, provider), "end_date": format_date_for_provider(end, provider)}


def _build_params(provider: Provider, api_name: str, request: SourceGapRequest) -> dict[str, object]:
    symbol = request.symbol or "000759.SZ"
    code = build_provider_code(symbol, provider)
    date_params = _date_range_params(request, provider)
    if provider == Provider.BAOSTOCK:
        if api_name == "query_stock_basic":
            return {"code": code}
        if api_name == "query_all_stock":
            return {"day": request.trade_date.isoformat() if request.trade_date else (request.start_date.isoformat() if request.start_date else None)}
        if api_name == "query_trade_dates":
            return date_params
        if api_name == "query_history_k_data_plus_daily_qfq":
            return {
                "code": code,
                "fields": "date,code,open,high,low,close,preclose,volume,amount,adjustflag,turn,tradestatus,pctChg,isST",
                **date_params,
                "frequency": "d",
                "adjustflag": "2",
            }
        if api_name == "query_history_k_data_plus_daily_raw":
            return {
                "code": code,
                "fields": "date,code,open,high,low,close,preclose,volume,amount,adjustflag,turn,tradestatus,pctChg,isST",
                **date_params,
                "frequency": "d",
                "adjustflag": "3",
            }
        if api_name == "query_adjust_factor":
            return {"code": code, **date_params}
        if api_name == "query_stock_industry":
            return {"date": request.trade_date.isoformat() if request.trade_date else None}
    if provider == Provider.AKSHARE:
        ak_code = build_provider_code(symbol, provider)
        if api_name == "stock_zh_a_hist_daily_qfq":
            return {"symbol": ak_code, "period": "daily", **date_params, "adjust": "qfq"}
        if api_name == "stock_zh_a_hist_daily_raw":
            return {"symbol": ak_code, "period": "daily", **date_params, "adjust": ""}
        if api_name == "stock_fund_flow_individual_realtime":
            return {"symbol": "即时"}
        if api_name == "stock_zh_a_disclosure_report_cninfo":
            return {"symbol": ak_code, "market": "沪深京", **date_params}
        if api_name == "stock_board_industry_hist_em":
            return {"symbol": "行业待映射", "adjust": ""}
    if provider == Provider.TUSHARE:
        ts_code = build_provider_code(symbol, provider)
        if api_name in {"daily", "adj_factor", "moneyflow"}:
            return {"ts_code": ts_code, **date_params}
        if api_name == "stock_basic":
            return {"exchange": "", "list_status": "L", "fields": "ts_code,symbol,name,area,industry,market,exchange,list_status,list_date,delist_date,is_hs"}
        if api_name == "trade_cal":
            return {"exchange": "SSE", **date_params}
        if api_name == "stk_limit":
            trade_date = request.trade_date or request.start_date
            return {"trade_date": trade_date.strftime("%Y%m%d") if trade_date else None}
    if provider == Provider.INTERNAL:
        return {"source_table": request.source_table_name, "symbol": symbol, **date_params}
    return {"symbol": symbol, **date_params}


def build_repair_plan(request: SourceGapRequest) -> SourceGapRepairPlan:
    req = get_requirement(request.source_table_name, request.canonical_field_name)
    primary_provider = request.provider_hint or req.primary_provider
    primary_api_name = req.primary_api_name
    primary_spec = get_api_spec(primary_provider, primary_api_name) if primary_provider != Provider.INTERNAL else None
    primary = RepairApiPlan(
        provider=primary_provider,
        api_name=primary_api_name,
        raw_table_name=primary_spec.raw_table_name if primary_spec else f"source_build.{primary_api_name}",
        params=_build_params(primary_provider, primary_api_name, request),
        reason=f"primary repair for {request.source_table_name}.{request.canonical_field_name}",
        priority=10,
    )
    backups: list[RepairApiPlan] = []
    if req.backup_provider and req.backup_api_name:
        spec = get_api_spec(req.backup_provider, req.backup_api_name) if req.backup_provider != Provider.INTERNAL else None
        backups.append(
            RepairApiPlan(
                provider=req.backup_provider,
                api_name=req.backup_api_name,
                raw_table_name=spec.raw_table_name if spec else f"source_build.{req.backup_api_name}",
                params=_build_params(req.backup_provider, req.backup_api_name, request),
                reason=f"backup repair for {request.source_table_name}.{request.canonical_field_name}",
                priority=20,
            )
        )
    return SourceGapRepairPlan(
        source_table_name=request.source_table_name,
        canonical_field_name=request.canonical_field_name,
        symbol=request.symbol,
        trade_date=request.trade_date,
        primary_repair=primary,
        backup_repairs=backups,
    )


def _source_pk_from_request(request: SourceGapRequest) -> str:
    if request.symbol and request.trade_date:
        return f"{request.symbol}|{request.trade_date.isoformat()}"
    if request.symbol:
        return request.symbol
    if request.trade_date:
        return request.trade_date.isoformat()
    return "<source_pk_required>"


def diagnose_gap(request: SourceGapRequest):
    from source_data_service.models import SourceGapDiagnosis

    req = get_requirement(request.source_table_name, request.canonical_field_name)
    plan = build_repair_plan(request)
    if req.required_level.value == "P0" and req.required_for_online:
        online_impact = "block_online"
    elif req.required_level.value == "research_only":
        online_impact = "research_only"
    else:
        online_impact = "degrade"
    rebuild_steps = [
        f"Fetch raw interface: {plan.primary_repair.provider.value}.{plan.primary_repair.api_name} -> {plan.primary_repair.raw_table_name}",
        "Persist raw rows with request_hash, response_schema_hash, response_row_hash, captured_at and raw_row_json",
        f"Run source build for {request.source_table_name} using active provider_field_mapping_v1",
        "Write/refresh governance.source_lineage_v1 for every rebuilt canonical field",
        "Re-run source readiness and cross-provider diff checks before model scheduling",
    ]
    checklist = [
        "Do not write provider rows directly into decision_* model tables",
        "Verify available_at <= model decision_time before enabling online model usage",
        "If primary provider fails, use backup repair plan without restarting source-data-service",
        "If raw schema hash changes, mark probe_result.schema_pass=false until mapping is reviewed",
    ]
    return SourceGapDiagnosis(
        source_table_name=request.source_table_name,
        canonical_field_name=request.canonical_field_name,
        required_level=req.required_level,
        affected_models=req.used_by_models,
        required_for_online=req.required_for_online,
        required_for_backtest=req.required_for_backtest,
        minimum_coverage_rate=req.minimum_coverage_rate,
        primary_repair=plan.primary_repair,
        backup_repairs=plan.backup_repairs,
        rebuild_steps=rebuild_steps,
        lineage_lookup={
            "source_table_name": request.source_table_name,
            "canonical_field_name": request.canonical_field_name,
            "source_pk": _source_pk_from_request(request),
            "expected_governance_table": "governance.source_lineage_v1",
        },
        operator_checklist=checklist,
        online_impact=online_impact,
    )


def resolve_lineage_plan(request):
    from source_data_service.models import LineageResolveResult

    req = get_requirement(request.source_table_name, request.canonical_field_name)
    source_pk = request.source_pk
    if not source_pk:
        if request.symbol and request.trade_date:
            source_pk = f"{request.symbol}|{request.trade_date.isoformat()}"
        elif request.symbol:
            source_pk = request.symbol
        else:
            source_pk = "<source_pk_required>"
    raw_tables = [req.repair_raw_table_name]
    provider_apis = [f"{req.primary_provider.value}.{req.primary_api_name}"]
    expected_fields: list[str] = []
    try:
        primary_spec = get_api_spec(req.primary_provider, req.primary_api_name) if req.primary_provider != Provider.INTERNAL else None
        if primary_spec:
            expected_fields.extend(primary_spec.response_fields)
    except Exception:
        pass
    if req.backup_provider and req.backup_api_name:
        try:
            spec = get_api_spec(req.backup_provider, req.backup_api_name) if req.backup_provider != Provider.INTERNAL else None
            raw_tables.append(spec.raw_table_name if spec else f"source_build.{req.backup_api_name}")
            provider_apis.append(f"{req.backup_provider.value}.{req.backup_api_name}")
            if spec:
                expected_fields.extend(spec.response_fields)
        except Exception:
            provider_apis.append(f"{req.backup_provider.value}.{req.backup_api_name}")
    query_hint = (
        "SELECT * FROM governance.source_lineage_v1 "
        f"WHERE source_table_name = '{request.source_table_name}' "
        f"AND canonical_field_name = '{request.canonical_field_name}' "
        f"AND source_pk = '{source_pk}';"
    )
    return LineageResolveResult(
        source_table_name=request.source_table_name,
        canonical_field_name=request.canonical_field_name,
        source_pk=source_pk,
        lineage_query_hint=query_hint,
        candidate_raw_tables=raw_tables,
        candidate_provider_apis=provider_apis,
        expected_raw_fields=sorted(set(expected_fields)),
    )
