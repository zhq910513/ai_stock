from __future__ import annotations

from source_data_service.models import Provider, RepairApiPlan, SourceGapRepairPlan, SourceGapRequest
from source_data_service.provider_registry import build_provider_code, format_date_for_provider, get_api_spec, get_requirement


def _require_symbol(provider: Provider, api_name: str, request: SourceGapRequest) -> str:
    if request.symbol:
        return request.symbol
    raise ValueError(
        f"{provider.value}.{api_name} requires symbol; use universe_scope=full_a_share to expand symbols first"
    )


def _date_range_params(request: SourceGapRequest, provider: Provider) -> dict[str, str]:
    start = request.start_date or request.trade_date
    end = request.end_date or request.trade_date or request.start_date
    if not start or not end:
        return {}
    if provider == Provider.BAOSTOCK:
        return {"start_date": format_date_for_provider(start, provider), "end_date": format_date_for_provider(end, provider)}
    return {"start_date": format_date_for_provider(start, provider), "end_date": format_date_for_provider(end, provider)}


def _build_params(provider: Provider, api_name: str, request: SourceGapRequest) -> dict[str, object]:
    symbol = request.symbol
    code = build_provider_code(symbol, provider) if symbol else ""
    date_params = _date_range_params(request, provider)
    if provider == Provider.BAOSTOCK:
        if api_name == "query_stock_basic":
            return {"code": code}
        if api_name == "query_all_stock":
            return {"day": request.trade_date.isoformat() if request.trade_date else (request.start_date.isoformat() if request.start_date else None)}
        if api_name == "query_trade_dates":
            return date_params
        if api_name == "query_history_k_data_plus_daily_qfq":
            symbol = _require_symbol(provider, api_name, request)
            code = build_provider_code(symbol, provider)
            return {
                "code": code,
                "fields": "date,code,open,high,low,close,preclose,volume,amount,adjustflag,turn,tradestatus,pctChg,isST",
                **date_params,
                "frequency": "d",
                "adjustflag": "2",
            }
        if api_name == "query_history_k_data_plus_daily_raw":
            if request.source_table_name == "source.index_daily_bar_v1" and not request.symbol:
                symbol = "399006.SZ"
            else:
                symbol = _require_symbol(provider, api_name, request)
            code = build_provider_code(symbol, provider)
            fields = "date,code,open,high,low,close,preclose,volume,amount,adjustflag,turn,tradestatus,pctChg,isST"
            if request.source_table_name == "source.index_daily_bar_v1":
                fields = "date,code,open,high,low,close,preclose,volume,amount,pctChg"
            return {
                "code": code,
                "fields": fields,
                **date_params,
                "frequency": "d",
                "adjustflag": "3",
            }
        if api_name == "query_adjust_factor":
            symbol = _require_symbol(provider, api_name, request)
            code = build_provider_code(symbol, provider)
            return {"code": code, **date_params}
        if api_name == "query_stock_industry":
            return {"date": request.trade_date.isoformat() if request.trade_date else None}
    if provider == Provider.AKSHARE:
        if api_name == "stock_zh_a_hist_daily_qfq":
            symbol = _require_symbol(provider, api_name, request)
            ak_code = build_provider_code(symbol, provider)
            return {"symbol": ak_code, "period": "daily", **date_params, "adjust": "qfq"}
        if api_name == "stock_zh_a_hist_daily_raw":
            symbol = _require_symbol(provider, api_name, request)
            ak_code = build_provider_code(symbol, provider)
            return {"symbol": ak_code, "period": "daily", **date_params, "adjust": ""}
        if api_name == "stock_fund_flow_individual_realtime":
            return {"symbol": "即时"}
        if api_name == "stock_zh_a_disclosure_report_cninfo":
            symbol = _require_symbol(provider, api_name, request)
            ak_code = build_provider_code(symbol, provider)
            return {"symbol": ak_code, "market": "沪深京", **date_params}
        if api_name == "stock_board_industry_hist_em":
            return {"symbol": "行业待映射", "adjust": ""}
    if provider == Provider.TENCENT:
        if request.source_table_name == "source.index_daily_bar_v1" and not request.symbol:
            tencent_symbol = "399006.SZ"
        else:
            tencent_symbol = _require_symbol(provider, api_name, request)
        provider_code = build_provider_code(tencent_symbol, provider)
        adjustment = "qfq" if request.source_table_name == "source.adjusted_daily_bar_v1" else "raw"
        return {
            "provider_code": provider_code,
            "period": "day",
            **date_params,
            "count": 10,
            "adjustment": adjustment,
        }
    if provider == Provider.SOHU:
        symbol = _require_symbol(provider, api_name, request)
        provider_code = build_provider_code(symbol, provider)
        return {
            "provider_code": provider_code,
            **date_params,
            "period": "d",
        }
    if provider == Provider.EASTMONEY:
        if api_name == "stock_universe":
            if not symbol:
                return {"pageSize": 200, "pageNumber": 1, "max_pages_per_segment": 20}
            code6 = symbol.split(".", 1)[0]
            segment_name = "main_sz"
            if symbol.endswith(".SH"):
                segment_name = "star" if code6.startswith("688") else "main_sh"
            elif symbol.endswith(".BJ") or code6.startswith(("8", "4")):
                segment_name = "bse"
            elif code6.startswith("3"):
                segment_name = "chinext"
            return {"segment_name": segment_name, "pageSize": 200, "pageNumber": 1, "max_pages_per_segment": 20}
        if api_name == "moneyflow_stock_series":
            symbol = _require_symbol(provider, api_name, request)
            secid = build_provider_code(symbol, provider)
            params: dict[str, object] = {"secid": secid, "lmt": 120}
            params.update(date_params)
            return params
        if api_name == "minute_bars":
            symbol = _require_symbol(provider, api_name, request)
            secid = build_provider_code(symbol, provider)
            params = {"secid": secid, "ndays": 1}
            params.update(date_params)
            if request.trade_date:
                params["trade_date"] = request.trade_date.isoformat()
            return params
        if api_name == "trade_details":
            symbol = _require_symbol(provider, api_name, request)
            secid = build_provider_code(symbol, provider)
            params = {"secid": secid, "pos": "-0"}
            params.update(date_params)
            if request.trade_date:
                params["trade_date"] = request.trade_date.isoformat()
            return params
        if api_name == "quote_snapshot":
            symbol = _require_symbol(provider, api_name, request)
            secid = build_provider_code(symbol, provider)
            params = {"secid": secid}
            params.update(date_params)
            if request.trade_date:
                params["trade_date"] = request.trade_date.isoformat()
            return params
        if api_name == "auction_snapshot":
            symbol = _require_symbol(provider, api_name, request)
            secid = build_provider_code(symbol, provider)
            params = {"secid": secid}
            params.update(date_params)
            if request.trade_date:
                params["trade_date"] = request.trade_date.isoformat()
            return params
        if api_name == "daily_bars":
            symbol = _require_symbol(provider, api_name, request)
            secid = build_provider_code(symbol, provider)
            start = request.start_date or request.trade_date
            end = request.end_date or request.trade_date or request.start_date
            return {
                "secid": secid,
                "beg": start.strftime("%Y%m%d") if start else "20260612",
                "end": end.strftime("%Y%m%d") if end else "20260612",
                "klt": "101",
                "fqt": "0",
            }
        if api_name in {"northbound_summary", "lpr_rates"}:
            return {"pageSize": 20, "pageNumber": 1}
        symbol = _require_symbol(provider, api_name, request)
        secid = build_provider_code(symbol, provider)
        return {"secid": secid, **date_params}
    if provider == Provider.THS:
        if api_name == "paid_limit_up_probability":
            from source_data_service.ths_paid_credentials import active_credential_version

            symbol = _require_symbol(provider, api_name, request)
            trade_date = request.trade_date or request.start_date
            return {
                "date": trade_date.strftime("%Y%m%d") if trade_date else None,
                "stock_code": symbol[:6],
                "credential_version": active_credential_version() or "missing_credential",
            }
        if api_name == "limit_up_pool":
            params: dict[str, object] = {"limit": 50, "fetch_all_pages": True}
            if request.trade_date:
                params["trade_date"] = request.trade_date.isoformat()
            return params
        if api_name in {"market_state_overview", "wind_vane_stock"}:
            params = {}
            if request.trade_date:
                params["trade_date"] = request.trade_date.isoformat()
            return params
        if api_name in {"stock_concepts", "stock_focusday"}:
            symbol = _require_symbol(provider, api_name, request)
            return {"symbol": symbol[:6]}
        return {}
    if provider == Provider.BAIDU:
        return {"rn": 20, "pn": 0, "type": "all", "tag": "all"}
    if provider == Provider.JIN10:
        return {"channel": "-8200", "vip": 0}
    if provider == Provider.COINGECKO:
        return {"ids": "bitcoin,ethereum", "vs_currency": "usd"}
    if provider == Provider.YAHOO:
        return {"symbols": "^NDX,^HSI,^SOX,^VIX,USDCNH=X", "range": "1mo", "interval": "1d"}
    if provider == Provider.TUSHARE:
        if api_name in {"daily", "adj_factor", "moneyflow", "daily_basic"}:
            symbol = _require_symbol(provider, api_name, request)
            ts_code = build_provider_code(symbol, provider)
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
        try:
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
        except ValueError as exc:
            if "requires symbol" not in str(exc):
                raise
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
