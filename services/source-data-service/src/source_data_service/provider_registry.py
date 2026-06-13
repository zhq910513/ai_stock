from __future__ import annotations

from datetime import date
from typing import Any

from source_data_service.models import FieldMappingSpec, Provider, ProviderApiSpec, RequiredLevel, SourceFieldContract, SourceTableRequirement


def _api(
    provider: Provider,
    api_name: str,
    api_function: str,
    raw_table: str,
    frequency: str,
    request_template: dict[str, Any],
    request_required: list[str],
    response_fields: list[str],
    canonical_targets: list[str],
    *,
    is_free: bool = True,
    requires_token: bool = False,
    priority: int = 100,
    request_optional: list[str] | None = None,
    rate_limit_note: str | None = None,
) -> ProviderApiSpec:
    return ProviderApiSpec(
        provider=provider,
        api_name=api_name,
        api_function=api_function,
        raw_table_name=raw_table,
        frequency=frequency,
        request_template=request_template,
        request_required_fields=request_required,
        request_optional_fields=request_optional or [],
        response_fields=response_fields,
        canonical_targets=canonical_targets,
        is_free=is_free,
        requires_token=requires_token,
        priority=priority,
        rate_limit_note=rate_limit_note,
    )


API_SPECS: list[ProviderApiSpec] = [
    _api(
        Provider.BAOSTOCK,
        "query_all_stock",
        "bs.query_all_stock",
        "raw_baostock.query_all_stock_v1",
        "daily",
        {"day": "YYYY-MM-DD"},
        ["day"],
        ["code", "tradeStatus", "code_name"],
        ["source.stock_universe_daily_v1", "source.trade_status_v1"],
        priority=10,
    ),
    _api(
        Provider.BAOSTOCK,
        "query_stock_basic",
        "bs.query_stock_basic",
        "raw_baostock.query_stock_basic_v1",
        "on_demand",
        {"code": "sz.000759"},
        ["code"],
        ["code", "code_name", "ipoDate", "outDate", "type", "status"],
        ["source.stock_master_v1"],
        priority=10,
    ),
    _api(
        Provider.BAOSTOCK,
        "query_trade_dates",
        "bs.query_trade_dates",
        "raw_baostock.query_trade_dates_v1",
        "calendar",
        {"start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD"},
        ["start_date", "end_date"],
        ["calendar_date", "is_trading_day"],
        ["source.trade_calendar_v1"],
        priority=10,
    ),
    _api(
        Provider.BAOSTOCK,
        "query_history_k_data_plus_daily_raw",
        "bs.query_history_k_data_plus",
        "raw_baostock.query_history_k_data_plus_daily_raw_v1",
        "daily",
        {
            "code": "sz.000759",
            "fields": "date,code,open,high,low,close,preclose,volume,amount,adjustflag,turn,tradestatus,pctChg,isST",
            "start_date": "YYYY-MM-DD",
            "end_date": "YYYY-MM-DD",
            "frequency": "d",
            "adjustflag": "3",
        },
        ["code", "start_date", "end_date"],
        ["date", "code", "open", "high", "low", "close", "preclose", "volume", "amount", "adjustflag", "turn", "tradestatus", "pctChg", "isST"],
        ["source.daily_bar_v1", "source.trade_status_v1"],
        priority=10,
    ),
    _api(
        Provider.BAOSTOCK,
        "query_history_k_data_plus_daily_qfq",
        "bs.query_history_k_data_plus",
        "raw_baostock.query_history_k_data_plus_daily_qfq_v1",
        "daily",
        {
            "code": "sz.000759",
            "fields": "date,code,open,high,low,close,preclose,volume,amount,adjustflag,turn,tradestatus,pctChg,isST",
            "start_date": "YYYY-MM-DD",
            "end_date": "YYYY-MM-DD",
            "frequency": "d",
            "adjustflag": "2",
        },
        ["code", "start_date", "end_date"],
        ["date", "code", "open", "high", "low", "close", "preclose", "volume", "amount", "adjustflag", "turn", "tradestatus", "pctChg", "isST"],
        ["source.adjusted_daily_bar_v1"],
        priority=10,
    ),
    _api(
        Provider.BAOSTOCK,
        "query_adjust_factor",
        "bs.query_adjust_factor",
        "raw_baostock.query_adjust_factor_v1",
        "on_demand",
        {"code": "sz.000001", "start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD"},
        ["code", "start_date", "end_date"],
        ["code", "dividOperateDate", "foreAdjustFactor", "backAdjustFactor", "adjustFactor"],
        ["source.adjustment_factor_v1"],
        priority=10,
    ),
    _api(
        Provider.BAOSTOCK,
        "query_stock_industry",
        "bs.query_stock_industry",
        "raw_baostock.query_stock_industry_v1",
        "weekly",
        {"date": "YYYY-MM-DD"},
        ["date"],
        ["updateDate", "code", "code_name", "industry", "industryClassification"],
        ["source.stock_board_membership_v1"],
        priority=30,
    ),
    _api(
        Provider.AKSHARE,
        "stock_zh_a_spot_em",
        "ak.stock_zh_a_spot_em",
        "raw_akshare.stock_zh_a_spot_em_v1",
        "intraday_snapshot",
        {},
        [],
        ["序号", "代码", "名称", "最新价", "涨跌幅", "涨跌额", "成交量", "成交额", "振幅", "最高", "最低", "今开", "昨收", "量比", "换手率", "总市值", "流通市值"],
        ["source.stock_universe_daily_v1", "source.quote_snapshot_v1"],
        priority=40,
        rate_limit_note="Public webpage backed API; use as backup or current snapshot source.",
    ),
    _api(
        Provider.AKSHARE,
        "stock_zh_a_hist_daily_raw",
        "ak.stock_zh_a_hist",
        "raw_akshare.stock_zh_a_hist_daily_raw_v1",
        "daily",
        {"symbol": "000759", "period": "daily", "start_date": "YYYYMMDD", "end_date": "YYYYMMDD", "adjust": ""},
        ["symbol", "start_date", "end_date"],
        ["日期", "开盘", "收盘", "最高", "最低", "成交量", "成交额", "振幅", "涨跌幅", "涨跌额", "换手率"],
        ["source.daily_bar_v1"],
        priority=20,
    ),
    _api(
        Provider.AKSHARE,
        "stock_zh_a_hist_daily_qfq",
        "ak.stock_zh_a_hist",
        "raw_akshare.stock_zh_a_hist_daily_qfq_v1",
        "daily",
        {"symbol": "000759", "period": "daily", "start_date": "YYYYMMDD", "end_date": "YYYYMMDD", "adjust": "qfq"},
        ["symbol", "start_date", "end_date"],
        ["日期", "开盘", "收盘", "最高", "最低", "成交量", "成交额", "振幅", "涨跌幅", "涨跌额", "换手率"],
        ["source.adjusted_daily_bar_v1"],
        priority=20,
    ),
    _api(
        Provider.AKSHARE,
        "stock_board_industry_name_em",
        "ak.stock_board_industry_name_em",
        "raw_akshare.stock_board_industry_name_em_v1",
        "intraday_snapshot",
        {},
        [],
        ["排名", "板块名称", "板块代码", "最新价", "涨跌额", "涨跌幅", "总市值", "换手率", "上涨家数", "下跌家数", "领涨股票", "领涨股票-涨跌幅"],
        ["source.board_master_v1", "source.board_intraday_snapshot_v1"],
        priority=30,
    ),
    _api(
        Provider.AKSHARE,
        "stock_board_industry_cons_em",
        "ak.stock_board_industry_cons_em",
        "raw_akshare.stock_board_industry_cons_em_v1",
        "intraday_snapshot",
        {"symbol": "小金属"},
        ["symbol"],
        ["序号", "代码", "名称", "最新价", "涨跌幅", "涨跌额", "成交量", "成交额", "振幅", "最高", "最低", "今开", "昨收", "换手率"],
        ["source.stock_board_membership_v1"],
        priority=30,
    ),
    _api(
        Provider.AKSHARE,
        "stock_board_industry_hist_em",
        "ak.stock_board_industry_hist_em",
        "raw_akshare.stock_board_industry_hist_em_v1",
        "daily",
        {"symbol": "小金属", "adjust": ""},
        ["symbol"],
        ["日期", "开盘", "收盘", "最高", "最低", "涨跌幅", "涨跌额", "成交量", "成交额", "振幅", "换手率"],
        ["source.board_daily_bar_v1"],
        priority=30,
    ),
    _api(
        Provider.AKSHARE,
        "stock_fund_flow_individual_realtime",
        "ak.stock_fund_flow_individual",
        "raw_akshare.stock_fund_flow_individual_realtime_v1",
        "intraday_snapshot",
        {"symbol": "即时"},
        [],
        ["序号", "股票代码", "股票简称", "最新价", "涨跌幅", "换手率", "流入资金", "流出资金", "净额", "成交额", "大单流入"],
        ["source.stock_moneyflow_daily_v1", "source.stock_moneyflow_snapshot_v1"],
        priority=40,
    ),
    _api(
        Provider.AKSHARE,
        "index_zh_a_hist",
        "ak.index_zh_a_hist",
        "raw_akshare.index_zh_a_hist_v1",
        "daily",
        {"symbol": "399006", "period": "daily", "start_date": "YYYYMMDD", "end_date": "YYYYMMDD"},
        ["symbol", "start_date", "end_date"],
        ["日期", "开盘", "收盘", "最高", "最低", "成交量", "成交额", "振幅", "涨跌幅", "涨跌额", "换手率"],
        ["source.index_daily_bar_v1"],
        priority=20,
    ),
    _api(
        Provider.AKSHARE,
        "stock_zh_a_disclosure_report_cninfo",
        "ak.stock_zh_a_disclosure_report_cninfo",
        "raw_akshare.stock_zh_a_disclosure_report_cninfo_v1",
        "on_demand",
        {"symbol": "000759", "market": "沪深京", "start_date": "YYYYMMDD", "end_date": "YYYYMMDD"},
        ["symbol", "start_date", "end_date"],
        ["代码", "简称", "公告标题", "公告时间", "公告类型", "公告链接"],
        ["source.event_news_v1", "source.announcement_event_v1"],
        priority=60,
    ),

    _api(
        Provider.TUSHARE,
        "trade_cal",
        "pro.trade_cal",
        "raw_tushare.trade_cal_v1",
        "calendar",
        {"exchange": "SSE", "start_date": "YYYYMMDD", "end_date": "YYYYMMDD"},
        ["start_date", "end_date"],
        ["exchange", "cal_date", "is_open", "pretrade_date"],
        ["source.trade_calendar_v1"],
        is_free=False,
        requires_token=True,
        priority=80,
    ),
    _api(
        Provider.TUSHARE,
        "daily",
        "pro.daily",
        "raw_tushare.daily_v1",
        "daily",
        {"ts_code": "000759.SZ", "start_date": "YYYYMMDD", "end_date": "YYYYMMDD"},
        ["ts_code", "start_date", "end_date"],
        ["ts_code", "trade_date", "open", "high", "low", "close", "pre_close", "change", "pct_chg", "vol", "amount"],
        ["source.daily_bar_v1"],
        is_free=False,
        requires_token=True,
        priority=80,
    ),
    _api(
        Provider.TUSHARE,
        "stock_basic",
        "pro.stock_basic",
        "raw_tushare.stock_basic_v1",
        "on_demand",
        {"exchange": "", "list_status": "L", "fields": "ts_code,symbol,name,area,industry,market,exchange,list_status,list_date,delist_date,is_hs"},
        [],
        ["ts_code", "symbol", "name", "area", "industry", "market", "exchange", "list_status", "list_date", "delist_date", "is_hs"],
        ["source.stock_master_v1"],
        is_free=False,
        requires_token=True,
        priority=80,
    ),
    _api(
        Provider.TUSHARE,
        "adj_factor",
        "pro.adj_factor",
        "raw_tushare.adj_factor_v1",
        "daily",
        {"ts_code": "000759.SZ", "start_date": "YYYYMMDD", "end_date": "YYYYMMDD"},
        ["ts_code", "start_date", "end_date"],
        ["ts_code", "trade_date", "adj_factor"],
        ["source.adjustment_factor_v1"],
        is_free=False,
        requires_token=True,
        priority=80,
    ),
    _api(
        Provider.TUSHARE,
        "moneyflow",
        "pro.moneyflow",
        "raw_tushare.moneyflow_v1",
        "daily",
        {"ts_code": "000759.SZ", "start_date": "YYYYMMDD", "end_date": "YYYYMMDD"},
        ["ts_code", "start_date", "end_date"],
        ["ts_code", "trade_date", "buy_sm_vol", "buy_sm_amount", "sell_sm_vol", "sell_sm_amount", "buy_md_vol", "buy_md_amount", "sell_md_vol", "sell_md_amount", "buy_lg_vol", "buy_lg_amount", "sell_lg_vol", "sell_lg_amount", "buy_elg_vol", "buy_elg_amount", "sell_elg_vol", "sell_elg_amount", "net_mf_vol", "net_mf_amount"],
        ["source.stock_moneyflow_daily_v1"],
        is_free=False,
        requires_token=True,
        priority=80,
    ),
    _api(
        Provider.TUSHARE,
        "stk_limit",
        "pro.stk_limit",
        "raw_tushare.stk_limit_v1",
        "daily",
        {"trade_date": "YYYYMMDD"},
        ["trade_date"],
        ["ts_code", "trade_date", "pre_close", "up_limit", "down_limit"],
        ["source.limit_price_v1"],
        is_free=False,
        requires_token=True,
        priority=80,
    ),
]


# Existing provider APIs migrated from the uploaded legacy market-data-service.
# These are registered as raw-interface contracts first. Real adapters are a DS-2
# migration task; until then they remain discoverable and can be wired without
# changing model code or source table contracts.
API_SPECS.extend([
    _api(
        Provider.EASTMONEY,
        "quote_snapshot",
        "EastmoneyMarketClient.fetch_quote_snapshot",
        "raw_eastmoney.quote_snapshot_v1",
        "intraday_snapshot",
        {"secid": "0.000759"},
        ["secid"],
        ["f43", "f44", "f45", "f46", "f47", "f48", "f60", "f168", "f169", "f170"],
        ["source.quote_snapshot_v1"],
        priority=50,
        rate_limit_note="Migrated contract from legacy market-data-service; adapter migration pending.",
    ),
    _api(
        Provider.EASTMONEY,
        "daily_bars",
        "EastmoneyMarketClient.fetch_daily_bars",
        "raw_eastmoney.daily_bars_v1",
        "daily",
        {"secid": "0.000759", "beg": "20200101", "end": "20260525", "klt": "101", "fqt": "1"},
        ["secid", "beg", "end"],
        ["date", "open", "close", "high", "low", "volume", "amount", "amplitude", "pct_chg", "change", "turnover"],
        ["source.daily_bar_v1", "source.adjusted_daily_bar_v1"],
        priority=55,
    ),
    _api(
        Provider.EASTMONEY,
        "minute_bars",
        "EastmoneyMarketClient.fetch_minute_bars",
        "raw_eastmoney.minute_bars_v1",
        "minute",
        {"secid": "0.000759", "ndays": 1},
        ["secid"],
        ["datetime", "open", "close", "high", "low", "volume", "amount"],
        ["source.minute_bar_v1"],
        priority=70,
    ),
    _api(
        Provider.EASTMONEY,
        "moneyflow_stock_series",
        "EastmoneyMarketClient.fetch_moneyflow_stock_series",
        "raw_eastmoney.moneyflow_stock_series_v1",
        "daily",
        {"secid": "0.000759", "lmt": 120},
        ["secid"],
        ["date", "main_net_inflow", "super_large_net_inflow", "large_net_inflow", "medium_net_inflow", "small_net_inflow"],
        ["source.stock_moneyflow_daily_v1"],
        priority=60,
    ),
    _api(
        Provider.EASTMONEY,
        "moneyflow_stock_rank",
        "EastmoneyMarketClient.fetch_moneyflow_stock_ranks",
        "raw_eastmoney.moneyflow_stock_rank_v1",
        "intraday_snapshot",
        {"rank_type": "today"},
        [],
        ["code", "name", "net_inflow", "pct_chg", "amount"],
        ["source.stock_moneyflow_snapshot_v1"],
        priority=65,
    ),
    _api(
        Provider.EASTMONEY,
        "moneyflow_board_rank",
        "EastmoneyMarketClient.fetch_moneyflow_board_ranks",
        "raw_eastmoney.moneyflow_board_rank_v1",
        "intraday_snapshot",
        {"board_type": "industry"},
        [],
        ["board_code", "board_name", "net_inflow", "pct_chg", "amount"],
        ["source.board_moneyflow_snapshot_v1"],
        priority=65,
    ),
    _api(
        Provider.EASTMONEY,
        "stock_board_profile",
        "EastmoneyMarketClient.fetch_stock_board_profile",
        "raw_eastmoney.stock_board_profile_v1",
        "on_demand",
        {"secid": "0.000759"},
        ["secid"],
        ["f127", "f128", "f129"],
        ["source.stock_board_membership_v1"],
        priority=70,
    ),
    _api(
        Provider.EASTMONEY,
        "theme_memberships",
        "EastmoneyMarketClient.fetch_theme_memberships",
        "raw_eastmoney.theme_memberships_v1",
        "on_demand",
        {"theme_code": "BK0000"},
        ["theme_code"],
        ["code", "market", "name"],
        ["source.stock_board_membership_v1"],
        priority=70,
    ),
    _api(
        Provider.EASTMONEY,
        "billboard_trades",
        "EastmoneyMarketClient.fetch_billboard_trades",
        "raw_eastmoney.billboard_trades_v1",
        "daily",
        {"trade_date": "20260525"},
        ["trade_date"],
        ["SECURITY_CODE", "TRADE_DATE", "BILLBOARD_NET_AMT", "EXPLAIN"],
        ["source.billboard_trade_v1"],
        priority=80,
    ),
    _api(
        Provider.TENCENT,
        "daily_bars",
        "TencentMarketClient.fetch_daily_bars",
        "raw_tencent.daily_bars_v1",
        "daily",
        {"provider_code": "sz000759", "lmt": 120, "adjustment": "qfq"},
        ["provider_code"],
        ["date", "open", "close", "high", "low", "volume"],
        ["source.daily_bar_v1", "source.adjusted_daily_bar_v1"],
        priority=75,
    ),
    _api(
        Provider.TENCENT,
        "auction_snapshot",
        "TencentAuctionClient.fetch_auction_snapshot",
        "raw_tencent.auction_snapshot_v1",
        "auction_snapshot",
        {"provider_code": "sz000759"},
        ["provider_code"],
        ["price", "volume", "amount", "captured_at"],
        ["source.auction_snapshot_v1"],
        priority=75,
    ),
    _api(
        Provider.SINA,
        "auction_snapshot",
        "SinaAuctionClient.fetch_auction_snapshot",
        "raw_sina.auction_snapshot_v1",
        "auction_snapshot",
        {"provider_code": "sz000759"},
        ["provider_code"],
        ["price", "volume", "amount", "captured_at"],
        ["source.auction_snapshot_v1"],
        priority=75,
    ),
    _api(
        Provider.CNINFO,
        "cninfo_disclosure_direct",
        "cninfo.disclosure.search",
        "raw_cninfo.disclosure_direct_v1",
        "on_demand",
        {"symbol": "000759", "start_date": "20250101", "end_date": "20260525"},
        ["symbol", "start_date", "end_date"],
        ["symbol", "short_name", "title", "published_at", "event_type", "url"],
        ["source.event_news_v1", "source.announcement_event_v1"],
        priority=90,
    ),
])


REQS: list[SourceTableRequirement] = [
    SourceTableRequirement(
        source_table_name="source.daily_bar_v1",
        canonical_field_name="open_price",
        required_level=RequiredLevel.P0,
        used_by_models=["hot_candidates", "candidate_memory", "ambush_watchlist"],
        required_for_online=True,
        required_for_backtest=True,
        minimum_coverage_rate=0.995,
        primary_provider=Provider.BAOSTOCK,
        primary_api_name="query_history_k_data_plus_daily_raw",
        backup_provider=Provider.AKSHARE,
        backup_api_name="stock_zh_a_hist_daily_raw",
        repair_raw_table_name="raw_baostock.query_history_k_data_plus_daily_raw_v1",
        description="Unadjusted daily OHLC open price. Raw price is required for limit and tradability checks.",
    ),
    SourceTableRequirement(
        source_table_name="source.daily_bar_v1",
        canonical_field_name="close_price",
        required_level=RequiredLevel.P0,
        used_by_models=["hot_candidates", "candidate_memory", "ambush_watchlist"],
        required_for_online=True,
        required_for_backtest=True,
        minimum_coverage_rate=0.995,
        primary_provider=Provider.BAOSTOCK,
        primary_api_name="query_history_k_data_plus_daily_raw",
        backup_provider=Provider.AKSHARE,
        backup_api_name="stock_zh_a_hist_daily_raw",
        repair_raw_table_name="raw_baostock.query_history_k_data_plus_daily_raw_v1",
        description="Unadjusted daily close price.",
    ),
    SourceTableRequirement(
        source_table_name="source.adjusted_daily_bar_v1",
        canonical_field_name="adjusted_close",
        required_level=RequiredLevel.P0,
        used_by_models=["ambush_watchlist", "candidate_memory"],
        required_for_online=True,
        required_for_backtest=True,
        minimum_coverage_rate=0.995,
        primary_provider=Provider.BAOSTOCK,
        primary_api_name="query_history_k_data_plus_daily_qfq",
        backup_provider=Provider.AKSHARE,
        backup_api_name="stock_zh_a_hist_daily_qfq",
        repair_raw_table_name="raw_baostock.query_history_k_data_plus_daily_qfq_v1",
        description="Adjusted close for structure, shape, drawdown and low-valley pattern calculations.",
    ),
    SourceTableRequirement(
        source_table_name="source.trade_calendar_v1",
        canonical_field_name="is_trading_day",
        required_level=RequiredLevel.P0,
        used_by_models=["hot_candidates", "candidate_memory", "ambush_watchlist", "scheduler"],
        required_for_online=True,
        required_for_backtest=True,
        minimum_coverage_rate=1.0,
        primary_provider=Provider.BAOSTOCK,
        primary_api_name="query_trade_dates",
        backup_provider=Provider.TUSHARE,
        backup_api_name="trade_cal",
        repair_raw_table_name="raw_baostock.query_trade_dates_v1",
        description="Trading calendar used by scheduler and all model observation windows.",
    ),
    SourceTableRequirement(
        source_table_name="source.stock_master_v1",
        canonical_field_name="list_status",
        required_level=RequiredLevel.P0,
        used_by_models=["hot_candidates", "candidate_memory", "ambush_watchlist"],
        required_for_online=True,
        required_for_backtest=True,
        minimum_coverage_rate=1.0,
        primary_provider=Provider.BAOSTOCK,
        primary_api_name="query_stock_basic",
        backup_provider=Provider.TUSHARE,
        backup_api_name="stock_basic",
        repair_raw_table_name="raw_baostock.query_stock_basic_v1",
        description="Listing status, IPO date and delist date.",
    ),
    SourceTableRequirement(
        source_table_name="source.stock_moneyflow_daily_v1",
        canonical_field_name="main_net_inflow",
        required_level=RequiredLevel.P1,
        used_by_models=["hot_candidates", "candidate_memory", "ambush_watchlist"],
        required_for_online=False,
        required_for_backtest=True,
        minimum_coverage_rate=0.90,
        primary_provider=Provider.AKSHARE,
        primary_api_name="stock_fund_flow_individual_realtime",
        backup_provider=Provider.TUSHARE,
        backup_api_name="moneyflow",
        repair_raw_table_name="raw_akshare.stock_fund_flow_individual_realtime_v1",
        description="Moneyflow is confirmation/research data until provider stability is proven.",
    ),
    SourceTableRequirement(
        source_table_name="source.board_daily_bar_v1",
        canonical_field_name="close_price",
        required_level=RequiredLevel.P1,
        used_by_models=["hot_candidates", "candidate_memory", "ambush_watchlist"],
        required_for_online=False,
        required_for_backtest=True,
        minimum_coverage_rate=0.95,
        primary_provider=Provider.AKSHARE,
        primary_api_name="stock_board_industry_hist_em",
        backup_provider=Provider.INTERNAL,
        backup_api_name="source_build_board_daily_from_members",
        repair_raw_table_name="raw_akshare.stock_board_industry_hist_em_v1",
        description="Board/industry daily bar for relative sector strength.",
    ),
    SourceTableRequirement(
        source_table_name="source.event_news_v1",
        canonical_field_name="published_at",
        required_level=RequiredLevel.RESEARCH_ONLY,
        used_by_models=["hot_candidates", "candidate_memory", "ambush_watchlist"],
        required_for_online=False,
        required_for_backtest=True,
        minimum_coverage_rate=0.80,
        primary_provider=Provider.AKSHARE,
        primary_api_name="stock_zh_a_disclosure_report_cninfo",
        backup_provider=Provider.CNINFO,
        backup_api_name="cninfo_disclosure_direct",
        repair_raw_table_name="raw_akshare.stock_zh_a_disclosure_report_cninfo_v1",
        description="Announcement/event timing. Research-only until available_at is stable.",
    ),
]



def _req(
    source_table_name: str,
    canonical_field_name: str,
    required_level: RequiredLevel,
    used_by_models: list[str],
    required_for_online: bool,
    required_for_backtest: bool,
    minimum_coverage_rate: float,
    primary_provider: Provider,
    primary_api_name: str,
    backup_provider: Provider | None,
    backup_api_name: str | None,
    repair_raw_table_name: str,
    description: str,
) -> SourceTableRequirement:
    return SourceTableRequirement(
        source_table_name=source_table_name,
        canonical_field_name=canonical_field_name,
        required_level=required_level,
        used_by_models=used_by_models,
        required_for_online=required_for_online,
        required_for_backtest=required_for_backtest,
        minimum_coverage_rate=minimum_coverage_rate,
        primary_provider=primary_provider,
        primary_api_name=primary_api_name,
        backup_provider=backup_provider,
        backup_api_name=backup_api_name,
        repair_raw_table_name=repair_raw_table_name,
        description=description,
    )


ALL_MODELS = ["hot_candidates", "candidate_memory", "ambush_watchlist"]
AMBUSH_MEMORY = ["candidate_memory", "ambush_watchlist"]

# The initial DS-1 registry intentionally listed only representative fields. The
# production hardening pass expands this into a field-level contract matrix so
# every P0/P1 canonical field can be repaired back to a concrete provider API.
REQS.extend([
    _req("source.daily_bar_v1", "high_price", RequiredLevel.P0, ALL_MODELS, True, True, 0.995, Provider.BAOSTOCK, "query_history_k_data_plus_daily_raw", Provider.AKSHARE, "stock_zh_a_hist_daily_raw", "raw_baostock.query_history_k_data_plus_daily_raw_v1", "Unadjusted daily high. Required for true range, upper envelope, limit checks and K-line validation."),
    _req("source.daily_bar_v1", "low_price", RequiredLevel.P0, ALL_MODELS, True, True, 0.995, Provider.BAOSTOCK, "query_history_k_data_plus_daily_raw", Provider.AKSHARE, "stock_zh_a_hist_daily_raw", "raw_baostock.query_history_k_data_plus_daily_raw_v1", "Unadjusted daily low. Required for support break checks, true range, drawdown and tradability validation."),
    _req("source.daily_bar_v1", "pre_close_price", RequiredLevel.P0, ALL_MODELS, True, True, 0.995, Provider.BAOSTOCK, "query_history_k_data_plus_daily_raw", Provider.TUSHARE, "daily", "raw_baostock.query_history_k_data_plus_daily_raw_v1", "Previous close. Required for return, limit price calculation and anomaly validation."),
    _req("source.daily_bar_v1", "volume", RequiredLevel.P0, ALL_MODELS, True, True, 0.995, Provider.BAOSTOCK, "query_history_k_data_plus_daily_raw", Provider.AKSHARE, "stock_zh_a_hist_daily_raw", "raw_baostock.query_history_k_data_plus_daily_raw_v1", "Daily volume. Required for volume exhaustion, liquidity and tradability checks."),
    _req("source.daily_bar_v1", "amount", RequiredLevel.P0, ALL_MODELS, True, True, 0.995, Provider.BAOSTOCK, "query_history_k_data_plus_daily_raw", Provider.AKSHARE, "stock_zh_a_hist_daily_raw", "raw_baostock.query_history_k_data_plus_daily_raw_v1", "Daily turnover amount. Required for liquidity, average price and market breadth aggregation."),
    _req("source.daily_bar_v1", "pct_chg", RequiredLevel.P1, ALL_MODELS, False, True, 0.990, Provider.BAOSTOCK, "query_history_k_data_plus_daily_raw", Provider.AKSHARE, "stock_zh_a_hist_daily_raw", "raw_baostock.query_history_k_data_plus_daily_raw_v1", "Daily percentage return; can be recomputed from close/pre_close and is stored for cross-provider audit."),
    _req("source.daily_bar_v1", "turnover_rate", RequiredLevel.P1, ALL_MODELS, False, True, 0.950, Provider.BAOSTOCK, "query_history_k_data_plus_daily_raw", Provider.AKSHARE, "stock_zh_a_hist_daily_raw", "raw_baostock.query_history_k_data_plus_daily_raw_v1", "Turnover rate. Confirmation field; missing values must not be silently filled with zero."),
    _req("source.adjusted_daily_bar_v1", "adjusted_open", RequiredLevel.P0, AMBUSH_MEMORY, True, True, 0.995, Provider.BAOSTOCK, "query_history_k_data_plus_daily_qfq", Provider.AKSHARE, "stock_zh_a_hist_daily_qfq", "raw_baostock.query_history_k_data_plus_daily_qfq_v1", "Adjusted open for K-line geometry and shape signature. Not used for real trade execution."),
    _req("source.adjusted_daily_bar_v1", "adjusted_high", RequiredLevel.P0, AMBUSH_MEMORY, True, True, 0.995, Provider.BAOSTOCK, "query_history_k_data_plus_daily_qfq", Provider.AKSHARE, "stock_zh_a_hist_daily_qfq", "raw_baostock.query_history_k_data_plus_daily_qfq_v1", "Adjusted high for high-low envelope and volatility computation."),
    _req("source.adjusted_daily_bar_v1", "adjusted_low", RequiredLevel.P0, AMBUSH_MEMORY, True, True, 0.995, Provider.BAOSTOCK, "query_history_k_data_plus_daily_qfq", Provider.AKSHARE, "stock_zh_a_hist_daily_qfq", "raw_baostock.query_history_k_data_plus_daily_qfq_v1", "Adjusted low for support stability and low-valley shape matching."),
    _req("source.adjusted_daily_bar_v1", "volume", RequiredLevel.P1, AMBUSH_MEMORY, False, True, 0.990, Provider.BAOSTOCK, "query_history_k_data_plus_daily_qfq", Provider.AKSHARE, "stock_zh_a_hist_daily_qfq", "raw_baostock.query_history_k_data_plus_daily_qfq_v1", "Volume paired with adjusted price sequence. Volume remains raw units and is not price-adjusted."),
    _req("source.adjusted_daily_bar_v1", "amount", RequiredLevel.P1, AMBUSH_MEMORY, False, True, 0.990, Provider.BAOSTOCK, "query_history_k_data_plus_daily_qfq", Provider.AKSHARE, "stock_zh_a_hist_daily_qfq", "raw_baostock.query_history_k_data_plus_daily_qfq_v1", "Turnover amount paired with adjusted price sequence; used for liquidity and shape review."),
    _req("source.adjustment_factor_v1", "adjustment_factor", RequiredLevel.P0, AMBUSH_MEMORY, True, True, 0.995, Provider.BAOSTOCK, "query_adjust_factor", Provider.TUSHARE, "adj_factor", "raw_baostock.query_adjust_factor_v1", "Adjustment factor for ex-right/ex-dividend audit. Prevents false valley detection caused by corporate actions."),
    _req("source.stock_master_v1", "stock_name", RequiredLevel.P0, ALL_MODELS, True, True, 1.0, Provider.BAOSTOCK, "query_stock_basic", Provider.TUSHARE, "stock_basic", "raw_baostock.query_stock_basic_v1", "Security display name used for audit and operator review, not for scoring."),
    _req("source.stock_master_v1", "ipo_date", RequiredLevel.P0, ALL_MODELS, True, True, 1.0, Provider.BAOSTOCK, "query_stock_basic", Provider.TUSHARE, "stock_basic", "raw_baostock.query_stock_basic_v1", "IPO date. Required to avoid insufficient-history windows and new-stock special rules."),
    _req("source.stock_master_v1", "delist_date", RequiredLevel.P0, ALL_MODELS, True, True, 1.0, Provider.BAOSTOCK, "query_stock_basic", Provider.TUSHARE, "stock_basic", "raw_baostock.query_stock_basic_v1", "Delist date. Required to prevent survivorship bias and exclude invalid historical samples."),
    _req("source.stock_universe_daily_v1", "is_tradable", RequiredLevel.P0, ALL_MODELS, True, True, 0.995, Provider.BAOSTOCK, "query_all_stock", Provider.AKSHARE, "stock_zh_a_spot_em", "raw_baostock.query_all_stock_v1", "Daily tradability flag for universe filtering and hard blocks."),
    _req("source.stock_universe_daily_v1", "trade_status", RequiredLevel.P0, ALL_MODELS, True, True, 0.995, Provider.BAOSTOCK, "query_all_stock", Provider.AKSHARE, "stock_zh_a_spot_em", "raw_baostock.query_all_stock_v1", "Provider raw trading status normalized to canonical universe state."),
    _req("source.trade_status_v1", "is_tradable", RequiredLevel.P0, ALL_MODELS, True, True, 0.995, Provider.BAOSTOCK, "query_history_k_data_plus_daily_raw", Provider.TUSHARE, "daily", "raw_baostock.query_history_k_data_plus_daily_raw_v1", "Historical daily tradable flag derived from raw K-line trade status."),
    _req("source.trade_status_v1", "is_suspended", RequiredLevel.P0, ALL_MODELS, True, True, 0.995, Provider.BAOSTOCK, "query_history_k_data_plus_daily_raw", Provider.TUSHARE, "daily", "raw_baostock.query_history_k_data_plus_daily_raw_v1", "Historical suspension flag. Missing values block official release and force research-only mode."),
    _req("source.trade_status_v1", "is_st", RequiredLevel.P0, ALL_MODELS, True, True, 0.995, Provider.BAOSTOCK, "query_history_k_data_plus_daily_raw", Provider.TUSHARE, "stock_basic", "raw_baostock.query_history_k_data_plus_daily_raw_v1", "Historical ST flag. Required for exclusion and correct limit rule calculation."),
    _req("source.trade_status_v1", "is_delisting_risk", RequiredLevel.P0, ALL_MODELS, True, True, 0.995, Provider.BAOSTOCK, "query_stock_basic", Provider.TUSHARE, "stock_basic", "raw_baostock.query_stock_basic_v1", "Delisting-risk proxy. Free sources may be incomplete; failures are hard data quality warnings."),
    _req("source.trade_calendar_v1", "pretrade_date", RequiredLevel.P0, ["scheduler", *ALL_MODELS], True, True, 1.0, Provider.BAOSTOCK, "query_trade_dates", Provider.TUSHARE, "trade_cal", "raw_baostock.query_trade_dates_v1", "Previous trade date for scheduler materialization, observation windows and T+N labels."),
    _req("source.limit_price_v1", "up_limit_price", RequiredLevel.P0, ALL_MODELS, True, True, 0.995, Provider.INTERNAL, "source_build_limit_price_from_rules", Provider.TUSHARE, "stk_limit", "source_build.source_build_limit_price_from_rules", "Up-limit price computed from raw pre-close and trading rules; external source validates edge cases."),
    _req("source.limit_price_v1", "down_limit_price", RequiredLevel.P0, ALL_MODELS, True, True, 0.995, Provider.INTERNAL, "source_build_limit_price_from_rules", Provider.TUSHARE, "stk_limit", "source_build.source_build_limit_price_from_rules", "Down-limit price computed from raw pre-close and trading rules; external source validates edge cases."),
    _req("source.limit_price_v1", "limit_rule", RequiredLevel.P0, ALL_MODELS, True, True, 0.995, Provider.INTERNAL, "source_build_limit_price_from_rules", Provider.TUSHARE, "stk_limit", "source_build.source_build_limit_price_from_rules", "Applied price-limit rule, e.g. normal_10pct, st_5pct, chinext_20pct, new_stock_special."),
    _req("source.limit_event_v1", "limit_event_type", RequiredLevel.P1, ALL_MODELS, False, True, 0.950, Provider.INTERNAL, "source_build_limit_event_from_daily", Provider.TUSHARE, "stk_limit", "source_build.source_build_limit_event_from_daily", "Limit event classification derived from daily bar and limit price; external events validate board details."),
    _req("source.index_daily_bar_v1", "close_price", RequiredLevel.P0, ALL_MODELS, True, True, 0.995, Provider.AKSHARE, "index_zh_a_hist", Provider.EASTMONEY, "daily_bars", "raw_akshare.index_zh_a_hist_v1", "Index close for market regime and relative strength baseline."),
    _req("source.index_daily_bar_v1", "pct_chg", RequiredLevel.P1, ALL_MODELS, False, True, 0.990, Provider.AKSHARE, "index_zh_a_hist", Provider.EASTMONEY, "daily_bars", "raw_akshare.index_zh_a_hist_v1", "Index return; can be recomputed from close and stored for audit."),
    _req("source.board_master_v1", "board_name", RequiredLevel.P1, ALL_MODELS, False, True, 0.950, Provider.AKSHARE, "stock_board_industry_name_em", Provider.BAOSTOCK, "query_stock_industry", "raw_akshare.stock_board_industry_name_em_v1", "Board/industry name. Current public source may not be historically stable."),
    _req("source.stock_board_membership_v1", "board_name", RequiredLevel.P1, ALL_MODELS, False, True, 0.950, Provider.AKSHARE, "stock_board_industry_cons_em", Provider.BAOSTOCK, "query_stock_industry", "raw_akshare.stock_board_industry_cons_em_v1", "Stock-to-board membership. If only current snapshot is available, historical backtest must mark it research-only/current_snapshot."),
    _req("source.board_daily_bar_v1", "pct_chg", RequiredLevel.P1, ALL_MODELS, False, True, 0.950, Provider.AKSHARE, "stock_board_industry_hist_em", Provider.INTERNAL, "source_build_board_daily_from_members", "raw_akshare.stock_board_industry_hist_em_v1", "Board return used for relative sector strength and sector environment confirmation."),
    _req("source.stock_moneyflow_daily_v1", "provider_definition", RequiredLevel.P1, ALL_MODELS, False, True, 0.900, Provider.AKSHARE, "stock_fund_flow_individual_realtime", Provider.TUSHARE, "moneyflow", "raw_akshare.stock_fund_flow_individual_realtime_v1", "Moneyflow field definition/version. Required because providers define main flow differently."),
    _req("source.event_news_v1", "available_at", RequiredLevel.RESEARCH_ONLY, ALL_MODELS, False, True, 0.800, Provider.AKSHARE, "stock_zh_a_disclosure_report_cninfo", Provider.CNINFO, "cninfo_disclosure_direct", "raw_akshare.stock_zh_a_disclosure_report_cninfo_v1", "Earliest time the event was available to the system. Without this, event data cannot be used in online scoring."),
])

# Deduplicate by canonical source field while keeping the first explicit contract.
_seen_reqs: set[tuple[str, str]] = set()
_deduped_reqs: list[SourceTableRequirement] = []
for _item in REQS:
    _key = (_item.source_table_name, _item.canonical_field_name)
    if _key in _seen_reqs:
        continue
    _seen_reqs.add(_key)
    _deduped_reqs.append(_item)
REQS = _deduped_reqs


def _infer_data_type(field_name: str) -> str:
    if field_name.endswith("_date") or field_name in {"ipo_date", "delist_date", "pretrade_date"}:
        return "DATE"
    if field_name.startswith("is_") or field_name.endswith("_flag"):
        return "BOOLEAN"
    if any(token in field_name for token in ("price", "amount", "volume", "pct", "rate", "factor", "close", "open", "high", "low", "inflow")):
        return "NUMERIC"
    return "TEXT"


def _infer_unit(field_name: str) -> str | None:
    if "price" in field_name or field_name in {"adjusted_open", "adjusted_high", "adjusted_low", "adjusted_close"}:
        return "CNY/share"
    if "volume" in field_name:
        return "shares/provider native units; normalized during build"
    if "amount" in field_name or "inflow" in field_name:
        return "CNY/provider native units; normalized during build"
    if "pct" in field_name or "rate" in field_name:
        return "percent"
    return None


def _infer_adjustment_mode(table_name: str, field_name: str) -> str:
    if table_name == "source.daily_bar_v1" or table_name == "source.limit_price_v1":
        return "raw" if "price" in field_name or field_name in {"open_price", "high_price", "low_price", "close_price", "pre_close_price"} else "not_price"
    if table_name == "source.adjusted_daily_bar_v1":
        return "qfq" if field_name.startswith("adjusted_") else "not_price"
    return "not_price"


def _online_policy(item: SourceTableRequirement) -> str:
    if item.required_level == RequiredLevel.RESEARCH_ONLY:
        return "research_only"
    if item.required_for_online and item.required_level == RequiredLevel.P0:
        return "required"
    return "degradable"


def _quality_rules(item: SourceTableRequirement) -> list[str]:
    field = item.canonical_field_name
    table = item.source_table_name
    rules = [
        "available_at must be <= model decision_time before any online model can use this field",
        "captured_at must be present; stale captured_at downgrades source_quality_status",
        "source_lineage_v1 must identify provider/api/raw_table/raw_id or build rule for this field",
    ]
    if table in {"source.daily_bar_v1", "source.adjusted_daily_bar_v1", "source.index_daily_bar_v1", "source.board_daily_bar_v1"}:
        rules.append("OHLC invariant: high >= max(open, close) and low <= min(open, close) when OHLC fields are present")
    if field in {"volume", "amount", "main_net_inflow"}:
        rules.append("numeric unit must be normalized; provider-native unit must remain traceable in raw_row_json")
    if table == "source.adjusted_daily_bar_v1":
        rules.append("adjusted price cannot be used for limit price or real execution checks")
    if table == "source.daily_bar_v1":
        rules.append("raw price must not be used for long-window shape similarity unless adjusted source is unavailable and research_only is set")
    return rules


def list_field_contracts(source_table_name: str | None = None) -> list[SourceFieldContract]:
    rows = list_source_requirements(source_table_name)
    contracts: list[SourceFieldContract] = []
    for item in rows:
        contracts.append(
            SourceFieldContract(
                source_table_name=item.source_table_name,
                canonical_field_name=item.canonical_field_name,
                required_level=item.required_level,
                data_type=_infer_data_type(item.canonical_field_name),
                unit=_infer_unit(item.canonical_field_name),
                price_adjustment_mode=_infer_adjustment_mode(item.source_table_name, item.canonical_field_name),
                time_semantics="event/trade date identifies market fact; available_at/captured_at identify data availability and ingestion time",
                used_by_models=item.used_by_models,
                primary_provider=item.primary_provider,
                primary_api_name=item.primary_api_name,
                backup_provider=item.backup_provider,
                backup_api_name=item.backup_api_name,
                raw_table_name=item.repair_raw_table_name,
                field_quality_rules=_quality_rules(item),
                online_policy=_online_policy(item),
                comment=item.description,
            )
        )
    return contracts


def list_api_specs() -> list[ProviderApiSpec]:
    return sorted(API_SPECS, key=lambda item: (item.provider.value, item.priority, item.api_name))


def get_api_spec(provider: Provider, api_name: str) -> ProviderApiSpec:
    for spec in API_SPECS:
        if spec.provider == provider and spec.api_name == api_name:
            return spec
    raise KeyError(f"provider api not registered: {provider.value}.{api_name}")


def list_source_requirements(source_table_name: str | None = None) -> list[SourceTableRequirement]:
    rows = REQS if source_table_name is None else [item for item in REQS if item.source_table_name == source_table_name]
    return sorted(rows, key=lambda item: (item.source_table_name, item.canonical_field_name))


def get_requirement(source_table_name: str, canonical_field_name: str) -> SourceTableRequirement:
    for item in REQS:
        if item.source_table_name == source_table_name and item.canonical_field_name == canonical_field_name:
            return item
    raise KeyError(f"source requirement not registered: {source_table_name}.{canonical_field_name}")


def build_provider_code(symbol: str, provider: Provider) -> str:
    normalized = symbol.replace(".", "").upper()
    if provider == Provider.BAOSTOCK:
        if symbol.upper().endswith(".SZ"):
            return f"sz.{symbol[:6]}"
        if symbol.upper().endswith(".SH"):
            return f"sh.{symbol[:6]}"
        if normalized.startswith(("000", "001", "002", "003", "300")):
            return f"sz.{normalized[:6]}"
        return f"sh.{normalized[:6]}"
    if provider == Provider.TUSHARE:
        if symbol.upper().endswith((".SZ", ".SH")):
            return symbol.upper()
        if normalized.startswith(("000", "001", "002", "003", "300")):
            return f"{normalized[:6]}.SZ"
        return f"{normalized[:6]}.SH"
    return normalized[:6]


def format_date_for_provider(value: date, provider: Provider) -> str:
    if provider in {Provider.AKSHARE, Provider.TUSHARE}:
        return value.strftime("%Y%m%d")
    return value.isoformat()
