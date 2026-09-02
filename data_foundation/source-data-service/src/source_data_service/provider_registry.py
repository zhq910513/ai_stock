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
        "daily_basic",
        "pro.daily_basic",
        "raw_tushare.daily_basic_v1",
        "daily",
        {"ts_code": "000759.SZ", "start_date": "YYYYMMDD", "end_date": "YYYYMMDD", "fields": "ts_code,trade_date,float_mv,total_mv,turnover_rate,volume_ratio"},
        ["ts_code", "start_date", "end_date"],
        ["ts_code", "trade_date", "float_mv", "total_mv", "turnover_rate", "volume_ratio"],
        ["source.realtime_quote_v1"],
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
# These are registered as source-data-service raw-interface contracts. Public
# no-login adapters are implemented here; account/commercial sources remain
# explicit candidates until credentials, probes, raw/source/lineage and README
# contracts are completed.
API_SPECS.extend([
    _api(
        Provider.EASTMONEY,
        "stock_universe",
        "EastmoneyUniverseClient.fetch_stock_universe",
        "raw_eastmoney.stock_universe_v1",
        "daily",
        {"segment_name": "main_sz", "pageSize": 200, "pageNumber": 1, "max_pages_per_segment": 1},
        [],
        [
            "symbol",
            "code",
            "name",
            "stock_name",
            "secid",
            "provider_market",
            "exchange",
            "board",
            "segment_name",
            "trade_date",
            "list_date",
            "list_status",
        ],
        ["source.stock_master_v1"],
        priority=58,
        rate_limit_note="EastMoney public clist universe migrated from legacy instrument bootstrap; identity/listing backup only, not tradability or model-owned signal.",
    ),
    _api(
        Provider.EASTMONEY,
        "quote_snapshot",
        "EastmoneyMarketClient.fetch_quote_snapshot",
        "raw_eastmoney.quote_snapshot_v1",
        "intraday_snapshot",
        {"secid": "0.000759", "trade_date": "YYYY-MM-DD"},
        ["secid"],
        [
            "symbol",
            "trade_date",
            "event_time",
            "last_price",
            "open_price",
            "high_price",
            "low_price",
            "prev_close_price",
            "volume",
            "amount",
            "turnover_rate",
            "change_amount",
            "change_pct",
            "float_market_cap",
            "total_market_cap",
        ],
        ["source.realtime_quote_v1"],
        priority=50,
        rate_limit_note="EastMoney public quote endpoint; real-probed for model-four quote and float-market-cap evidence.",
    ),
    _api(
        Provider.EASTMONEY,
        "auction_snapshot",
        "EastmoneyMarketClient.fetch_auction_snapshot",
        "raw_eastmoney.auction_snapshot_v1",
        "auction_snapshot",
        {"secid": "0.000759", "trade_date": "YYYY-MM-DD"},
        ["secid"],
        [
            "symbol",
            "trade_date",
            "event_time",
            "price",
            "volume",
            "amount",
            "prev_close_price",
            "best_bid_price",
            "best_bid_volume",
            "best_ask_price",
            "best_ask_volume",
            "provider_definition",
        ],
        ["source.auction_snapshot_v1"],
        priority=62,
        rate_limit_note="EastMoney public quote depth fields; context/auction evidence only and never a model-owned signal.",
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
        ["datetime", "symbol", "trade_date", "bar_time", "open", "close", "high", "low", "volume", "amount"],
        ["source.minute_bar_v1"],
        priority=70,
    ),
    _api(
        Provider.EASTMONEY,
        "trade_details",
        "EastmoneyMarketClient.fetch_trade_details",
        "raw_eastmoney.trade_details_v1",
        "intraday_tick",
        {"secid": "0.000759", "trade_date": "YYYY-MM-DD", "pos": "-0"},
        ["secid"],
        ["time", "symbol", "trade_date", "tick_time", "price", "volume", "amount", "trade_count", "side_code", "side_label"],
        ["source.trade_tick_v1"],
        priority=70,
        rate_limit_note="EastMoney public trade details endpoint; side_code remains provider-native and must not be over-interpreted.",
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
        Provider.EASTMONEY,
        "northbound_summary",
        "EastmoneyDatacenter.fetch_northbound_summary",
        "raw_eastmoney.northbound_summary_v1",
        "daily",
        {"reportName": "RPT_MUTUAL_DEAL_HISTORY", "pageSize": 20, "pageNumber": 1},
        [],
        ["trade_date", "mutual_type", "deal_amount", "net_buy_amount", "buy_amount", "sell_amount", "quota_balance_text"],
        ["source.cross_market_context_v1"],
        priority=85,
        rate_limit_note="EastMoney public DataCenter northbound context; research/context only unless a canonical source contract is added.",
    ),
    _api(
        Provider.EASTMONEY,
        "lpr_rates",
        "EastmoneyDatacenter.fetch_lpr_rates",
        "raw_eastmoney.lpr_rates_v1",
        "monthly_macro",
        {"pageSize": 20, "pageNumber": 1},
        [],
        ["asset_code", "asset_name", "trade_date", "last_price", "rate_1y", "rate_5y", "extra_metrics_json"],
        ["source.cross_market_context_v1"],
        priority=85,
        rate_limit_note="EastMoney public DataCenter LPR context; macro research only and not an A-share provider fallback.",
    ),
    _api(
        Provider.TENCENT,
        "daily_bars",
        "TencentAdapter.fetch_daily_bars",
        "raw_tencent.daily_bars_v1",
        "daily",
        {"provider_code": "sz000063", "period": "day", "start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD", "count": 10, "adjustment": "qfq"},
        ["provider_code", "start_date", "end_date"],
        ["date", "code", "provider_code", "symbol", "open", "close", "high", "low", "volume", "amount", "adjustment_mode", "period", "pct_chg"],
        ["source.daily_bar_v1", "source.adjusted_daily_bar_v1", "source.index_daily_bar_v1"],
        priority=15,
        rate_limit_note="Public Tencent fqkline endpoint; real-probed as AKShare/EastMoney replacement for daily/qfq/index bars.",
    ),
    _api(
        Provider.TENCENT,
        "quote_snapshot",
        "TencentQuoteClient.fetch_quote_snapshot",
        "raw_tencent.quote_snapshot_v1",
        "intraday_snapshot",
        {"provider_code": "sz000759"},
        ["provider_code"],
        [
            "provider_code",
            "symbol",
            "trade_date",
            "event_time",
            "last_price",
            "open_price",
            "high_price",
            "low_price",
            "prev_close_price",
            "volume",
            "amount",
            "turnover_rate",
            "change_amount",
            "change_pct",
        ],
        ["source.realtime_quote_v1"],
        priority=68,
        rate_limit_note="Tencent public quote fallback; only source/research evidence after raw/source/lineage validation.",
    ),
    _api(
        Provider.TENCENT,
        "minute_bars",
        "TencentMinuteClient.fetch_minute_bars",
        "raw_tencent.minute_bars_v1",
        "minute",
        {"provider_code": "sz000759", "trade_date": "YYYY-MM-DD"},
        ["provider_code"],
        ["datetime", "symbol", "trade_date", "bar_time", "open", "close", "high", "low", "volume", "amount", "provider_native_amount", "provider_definition"],
        ["source.minute_bar_v1"],
        priority=72,
        rate_limit_note="Tencent public mkline minute fallback; OHLC/volume enter source.minute_bar_v1 after raw/source/lineage validation, provider_native_amount stays audit-only until unit normalization.",
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
        Provider.SOHU,
        "daily_bars",
        "SohuAdapter.fetch_daily_bars",
        "raw_sohu.daily_bars_v1",
        "daily",
        {"provider_code": "cn_000063", "start_date": "YYYYMMDD", "end_date": "YYYYMMDD", "period": "d"},
        ["provider_code", "start_date", "end_date"],
        [
            "date",
            "code",
            "provider_code",
            "symbol",
            "open",
            "close",
            "change",
            "pct_chg",
            "low",
            "high",
            "volume",
            "amount",
            "turnover_rate",
            "adjustment_mode",
            "period",
            "provider_definition",
        ],
        ["source.daily_bar_v1"],
        priority=16,
        rate_limit_note="Public Sohu hisHq endpoint; real-probed as individual-stock daily amount/pct_chg backup because Tencent kline does not carry historical target-date amount or pct_chg.",
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
        Provider.BAIDU,
        "finance_news_feed",
        "BaiduAdapter.fetch_news_feed",
        "raw_baidu.finance_news_feed_v1",
        "intraday_snapshot",
        {"rn": 20, "pn": 0, "type": "all", "tag": "all"},
        [],
        ["provider_news_id", "title", "source_name", "published_at", "available_at", "event_type", "url", "symbol", "tags_json", "stock_refs_json"],
        ["source.event_news_v1"],
        priority=35,
        rate_limit_note="Public Baidu Finance selfselect news feed; real-probed as research-only event/news evidence source.",
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


API_SPECS.extend([
    _api(
        Provider.THS,
        "limit_up_pool",
        "THSAdapter.fetch_limit_up_pool",
        "raw_ths.limit_up_pool_v1",
        "intraday_snapshot",
        {"page": 1, "limit": 50, "fetch_all_pages": True, "field": "default_public_limit_up_pool_fields"},
        [],
        [
            "date",
            "code",
            "symbol",
            "name",
            "latest_price",
            "change_pct",
            "turnover_rate",
            "limit_up_type",
            "reason_type",
            "first_limit_up_time",
            "last_limit_up_time",
            "limit_open_count",
            "order_volume",
            "order_amount",
            "float_market_cap",
            "total_market_cap",
            "is_again_limit",
            "is_new",
            "high_days",
            "high_days_value",
            "limit_up_stage",
            "close_on_limit_flag",
            "limit_event_type",
        ],
        ["source.limit_event_v1"],
        priority=8,
        rate_limit_note="THS public no-login limit-up pool. Preferred current-session limit-event fact source after real probe; dynamic Cookie/hexin-v interfaces remain forbidden.",
    ),
    _api(
        Provider.THS,
        "paid_limit_up_probability",
        "THSAdapter.fetch_paid_limit_up_probability",
        "raw_ths.paid_limit_up_probability_v1",
        "daily_after_limit_up_pool_until_next_trade_09",
        {"date": "YYYYMMDD", "stock_code": "000000", "credential_version": "active_db_reference"},
        ["date", "stock_code"],
        [
            "date",
            "trade_date",
            "code",
            "stock_code",
            "symbol",
            "paid_limit_up_probability",
            "status_code",
            "status_msg",
            "credential_version",
            "available_at",
            "raw_provider_row",
        ],
        ["source.ths_paid_limit_up_probability_v1"],
        is_free=False,
        requires_token=True,
        priority=7,
        rate_limit_note=(
            "THS paid probability is the only credentialed THS path. Cookie values are stored only in DB/runtime, "
            "never in request_params_json, request_hash, raw_provider_row, logs, docs or frontend responses."
        ),
    ),
    _api(
        Provider.THS,
        "trade_status",
        "THSAdapter.fetch_trade_status",
        "raw_ths.trade_status_v1",
        "intraday_snapshot",
        {},
        [],
        ["endpoint", "captured_at", "payload_status", "payload_json"],
        ["source.market_status_context_v1"],
        priority=35,
        rate_limit_note="THS public trade-status context; research/operations context only until source requirement is added.",
    ),
    _api(
        Provider.THS,
        "zhangting5_reasons",
        "THSAdapter.fetch_zhangting5_reasons",
        "raw_ths.zhangting5_reasons_v1",
        "intraday_snapshot",
        {},
        [],
        ["date", "code", "symbol", "name", "reason_title", "reason_summary", "url"],
        ["source.event_news_v1", "source.limit_reason_context_v1"],
        priority=36,
    ),
    _api(
        Provider.THS,
        "market_state_overview",
        "THSAdapter.fetch_market_state_overview",
        "raw_ths.market_state_overview_v1",
        "intraday_snapshot",
        {"trade_date": "YYYY-MM-DD"},
        [],
        ["endpoint", "captured_at", "payload_status", "payload_json"],
        ["source.market_breadth_context_v1"],
        priority=37,
    ),
    _api(
        Provider.THS,
        "wind_vane_stock",
        "THSAdapter.fetch_wind_vane_stock",
        "raw_ths.wind_vane_stock_v1",
        "intraday_snapshot",
        {"trade_date": "YYYY-MM-DD"},
        [],
        ["date", "code", "symbol", "tab_name", "name", "price", "change_pct", "reason"],
        ["source.market_hot_stock_context_v1"],
        priority=38,
    ),
    _api(
        Provider.THS,
        "hot_block_list",
        "THSAdapter.fetch_hot_block_list",
        "raw_ths.hot_block_list_v1",
        "intraday_snapshot",
        {"type": "con", "field": "zf", "day_num": 10, "block_num": 4},
        [],
        ["date", "block_code", "block_name", "rank_no", "change_pct"],
        ["source.board_intraday_snapshot_v1"],
        priority=39,
    ),
    _api(
        Provider.THS,
        "market_capital",
        "THSAdapter.fetch_market_capital",
        "raw_ths.market_capital_v1",
        "intraday_snapshot",
        {},
        [],
        ["endpoint", "captured_at", "payload_status", "payload_json"],
        ["source.market_moneyflow_context_v1"],
        priority=40,
    ),
    _api(
        Provider.THS,
        "stock_concepts",
        "THSAdapter.fetch_stock_concepts",
        "raw_ths.stock_concepts_v1",
        "on_demand",
        {"symbol": "000759"},
        ["symbol"],
        ["symbol", "code", "concept_id", "concept_name", "rank_no", "concept_explain"],
        ["source.stock_board_membership_v1"],
        priority=42,
    ),
    _api(
        Provider.THS,
        "stock_focusday",
        "THSAdapter.fetch_stock_focusday",
        "raw_ths.stock_focusday_v1",
        "on_demand",
        {"symbol": "000759"},
        ["symbol"],
        ["symbol", "code", "rank", "total", "description", "payload_json"],
        ["source.stock_attention_context_v1"],
        priority=43,
    ),
    _api(
        Provider.COINGECKO,
        "simple_price",
        "CoinGeckoAdapter.fetch_simple_price",
        "raw_coingecko.simple_price_v1",
        "intraday_snapshot",
        {"ids": "bitcoin,ethereum", "vs_currency": "usd"},
        [],
        ["asset_id", "asset_code", "asset_name", "last_price", "change_pct_24h", "market_cap", "volume_24h"],
        ["source.cross_market_context_v1"],
        priority=85,
        rate_limit_note="Context-only public crypto market source. Not an A-share P0 release gate.",
    ),
    _api(
        Provider.COINGECKO,
        "global_market",
        "CoinGeckoAdapter.fetch_global_market",
        "raw_coingecko.global_market_v1",
        "intraday_snapshot",
        {"vs_currency": "usd"},
        [],
        ["metric_code", "asset_code", "asset_class", "market_cap", "volume_24h", "dominance_pct"],
        ["source.cross_market_context_v1"],
        priority=86,
    ),
    _api(
        Provider.YAHOO,
        "chart",
        "YahooAdapter.fetch_chart",
        "raw_yahoo.chart_v1",
        "daily",
        {"symbols": "^NDX,^HSI,^SOX,^VIX,USDCNH=X", "range": "1mo", "interval": "1d"},
        [],
        ["provider_symbol", "asset_code", "asset_name", "last_price", "change_pct", "observed_at"],
        ["source.cross_market_context_v1"],
        priority=87,
    ),
    _api(
        Provider.JIN10,
        "public_flash",
        "Jin10Adapter.fetch_public_flash",
        "raw_jin10.public_flash_v1",
        "intraday_snapshot",
        {"channel": "-8200", "vip": 0},
        [],
        ["provider_news_id", "title", "source_name", "published_at", "available_at", "event_type", "url", "symbol"],
        ["source.event_news_v1"],
        priority=88,
        rate_limit_note="Jin10 public flash endpoint with static public headers; research-only context unless a future source requirement promotes it.",
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
        backup_provider=Provider.TENCENT,
        backup_api_name="daily_bars",
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
        backup_provider=Provider.TENCENT,
        backup_api_name="daily_bars",
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
        backup_provider=Provider.TENCENT,
        backup_api_name="daily_bars",
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
        primary_provider=Provider.EASTMONEY,
        primary_api_name="moneyflow_stock_series",
        backup_provider=Provider.TUSHARE,
        backup_api_name="moneyflow",
        repair_raw_table_name="raw_eastmoney.moneyflow_stock_series_v1",
        description="Daily main net moneyflow from EastMoney public stock fflow series. It is confirmation data and remains degradable until multi-source口径 is stable.",
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
        primary_provider=Provider.BAIDU,
        primary_api_name="finance_news_feed",
        backup_provider=Provider.CNINFO,
        backup_api_name="cninfo_disclosure_direct",
        repair_raw_table_name="raw_baidu.finance_news_feed_v1",
        description="Public finance news/event timing from Baidu Finance feed. Research-only until event classification and available_at coverage are stable.",
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
T_BOARD_RELAY = ["t_board_relay"]
ALL_MODELS_WITH_T_RELAY = [*ALL_MODELS, "t_board_relay"]
AMBUSH_MEMORY = ["candidate_memory", "ambush_watchlist"]

# The initial DS-1 registry intentionally listed only representative fields. The
# production hardening pass expands this into a field-level contract matrix so
# every P0/P1 canonical field can be repaired back to a concrete provider API.
REQS.extend([
    _req("source.daily_bar_v1", "high_price", RequiredLevel.P0, ALL_MODELS_WITH_T_RELAY, True, True, 0.995, Provider.BAOSTOCK, "query_history_k_data_plus_daily_raw", Provider.TENCENT, "daily_bars", "raw_baostock.query_history_k_data_plus_daily_raw_v1", "Unadjusted daily high. Required for true range, upper envelope, limit checks and K-line validation."),
    _req("source.daily_bar_v1", "low_price", RequiredLevel.P0, ALL_MODELS_WITH_T_RELAY, True, True, 0.995, Provider.BAOSTOCK, "query_history_k_data_plus_daily_raw", Provider.TENCENT, "daily_bars", "raw_baostock.query_history_k_data_plus_daily_raw_v1", "Unadjusted daily low. Required for support break checks, true range, drawdown and tradability validation."),
    _req("source.daily_bar_v1", "pre_close_price", RequiredLevel.P0, ALL_MODELS_WITH_T_RELAY, True, True, 0.995, Provider.BAOSTOCK, "query_history_k_data_plus_daily_raw", Provider.TENCENT, "daily_bars", "raw_baostock.query_history_k_data_plus_daily_raw_v1", "Previous close. Required for return, limit price calculation and anomaly validation."),
    _req("source.daily_bar_v1", "volume", RequiredLevel.P0, ALL_MODELS_WITH_T_RELAY, True, True, 0.995, Provider.BAOSTOCK, "query_history_k_data_plus_daily_raw", Provider.TENCENT, "daily_bars", "raw_baostock.query_history_k_data_plus_daily_raw_v1", "Daily volume. Required for volume exhaustion, liquidity and tradability checks."),
    _req("source.daily_bar_v1", "amount", RequiredLevel.P0, ALL_MODELS_WITH_T_RELAY, True, True, 0.995, Provider.BAOSTOCK, "query_history_k_data_plus_daily_raw", Provider.SOHU, "daily_bars", "raw_baostock.query_history_k_data_plus_daily_raw_v1", "Daily turnover amount. Required for liquidity, average price and market breadth aggregation; Sohu hisHq backup normalizes amount from ten-thousand CNY to CNY."),
    _req("source.daily_bar_v1", "pct_chg", RequiredLevel.P1, ALL_MODELS_WITH_T_RELAY, False, True, 0.990, Provider.BAOSTOCK, "query_history_k_data_plus_daily_raw", Provider.SOHU, "daily_bars", "raw_baostock.query_history_k_data_plus_daily_raw_v1", "Daily percentage return; Sohu hisHq backup supplies target-date pct_chg while Tencent kline does not expose historical pct_chg in the row payload."),
    _req("source.daily_bar_v1", "turnover_rate", RequiredLevel.P1, ALL_MODELS_WITH_T_RELAY, False, True, 0.950, Provider.BAOSTOCK, "query_history_k_data_plus_daily_raw", Provider.SOHU, "daily_bars", "raw_baostock.query_history_k_data_plus_daily_raw_v1", "Turnover rate. Confirmation field; Sohu hisHq backup supplies target-date turnover_rate and missing values must not be silently filled with zero."),
    _req("source.adjusted_daily_bar_v1", "adjusted_open", RequiredLevel.P0, AMBUSH_MEMORY, True, True, 0.995, Provider.BAOSTOCK, "query_history_k_data_plus_daily_qfq", Provider.TENCENT, "daily_bars", "raw_baostock.query_history_k_data_plus_daily_qfq_v1", "Adjusted open for K-line geometry and shape signature. Not used for real trade execution."),
    _req("source.adjusted_daily_bar_v1", "adjusted_high", RequiredLevel.P0, AMBUSH_MEMORY, True, True, 0.995, Provider.BAOSTOCK, "query_history_k_data_plus_daily_qfq", Provider.TENCENT, "daily_bars", "raw_baostock.query_history_k_data_plus_daily_qfq_v1", "Adjusted high for high-low envelope and volatility computation."),
    _req("source.adjusted_daily_bar_v1", "adjusted_low", RequiredLevel.P0, AMBUSH_MEMORY, True, True, 0.995, Provider.BAOSTOCK, "query_history_k_data_plus_daily_qfq", Provider.TENCENT, "daily_bars", "raw_baostock.query_history_k_data_plus_daily_qfq_v1", "Adjusted low for support stability and low-valley shape matching."),
    _req("source.adjusted_daily_bar_v1", "volume", RequiredLevel.P1, AMBUSH_MEMORY, False, True, 0.990, Provider.BAOSTOCK, "query_history_k_data_plus_daily_qfq", Provider.TENCENT, "daily_bars", "raw_baostock.query_history_k_data_plus_daily_qfq_v1", "Volume paired with adjusted price sequence. Volume remains raw units and is not price-adjusted."),
    _req("source.adjusted_daily_bar_v1", "amount", RequiredLevel.P1, AMBUSH_MEMORY, False, True, 0.990, Provider.BAOSTOCK, "query_history_k_data_plus_daily_qfq", Provider.TENCENT, "daily_bars", "raw_baostock.query_history_k_data_plus_daily_qfq_v1", "Turnover amount paired with adjusted price sequence; used for liquidity and shape review."),
    _req("source.adjustment_factor_v1", "adjustment_factor", RequiredLevel.P0, AMBUSH_MEMORY, True, True, 0.995, Provider.BAOSTOCK, "query_adjust_factor", Provider.TUSHARE, "adj_factor", "raw_baostock.query_adjust_factor_v1", "Adjustment factor for ex-right/ex-dividend audit. Prevents false valley detection caused by corporate actions."),
    _req("source.stock_master_v1", "stock_name", RequiredLevel.P0, ALL_MODELS, True, True, 1.0, Provider.BAOSTOCK, "query_stock_basic", Provider.EASTMONEY, "stock_universe", "raw_baostock.query_stock_basic_v1", "Security display name used for audit and operator review, not for scoring. EastMoney clist universe is the free identity backup after raw/source/lineage validation."),
    _req("source.stock_master_v1", "ipo_date", RequiredLevel.P0, ALL_MODELS, True, True, 1.0, Provider.BAOSTOCK, "query_stock_basic", Provider.EASTMONEY, "stock_universe", "raw_baostock.query_stock_basic_v1", "IPO date. Required to avoid insufficient-history windows and new-stock special rules. EastMoney clist f26 list_date is the free backup when BaoStock is unavailable."),
    _req("source.stock_master_v1", "delist_date", RequiredLevel.P0, ALL_MODELS, True, True, 1.0, Provider.BAOSTOCK, "query_stock_basic", Provider.TUSHARE, "stock_basic", "raw_baostock.query_stock_basic_v1", "Delist date. Required to prevent survivorship bias and exclude invalid historical samples."),
    _req("source.stock_universe_daily_v1", "is_tradable", RequiredLevel.P0, ALL_MODELS, True, True, 0.995, Provider.BAOSTOCK, "query_all_stock", Provider.BAOSTOCK, "query_history_k_data_plus_daily_raw", "raw_baostock.query_all_stock_v1", "Daily tradability flag for universe filtering and hard blocks. Backup uses BaoStock per-symbol daily K status because AKShare/EastMoney spot is not stable enough for the production probe gate."),
    _req("source.stock_universe_daily_v1", "trade_status", RequiredLevel.P0, ALL_MODELS, True, True, 0.995, Provider.BAOSTOCK, "query_all_stock", Provider.BAOSTOCK, "query_history_k_data_plus_daily_raw", "raw_baostock.query_all_stock_v1", "Provider raw trading status normalized to canonical universe state. Backup uses BaoStock per-symbol daily K status because AKShare/EastMoney spot is not stable enough for the production probe gate."),
    _req("source.trade_status_v1", "is_tradable", RequiredLevel.P0, ALL_MODELS_WITH_T_RELAY, True, True, 0.995, Provider.BAOSTOCK, "query_history_k_data_plus_daily_raw", Provider.TENCENT, "daily_bars", "raw_baostock.query_history_k_data_plus_daily_raw_v1", "Historical daily tradable flag derived from raw K-line trade status."),
    _req("source.trade_status_v1", "is_suspended", RequiredLevel.P0, ALL_MODELS_WITH_T_RELAY, True, True, 0.995, Provider.BAOSTOCK, "query_history_k_data_plus_daily_raw", Provider.TENCENT, "daily_bars", "raw_baostock.query_history_k_data_plus_daily_raw_v1", "Historical suspension flag. Missing values block official release and force research-only mode."),
    _req("source.trade_status_v1", "is_st", RequiredLevel.P0, ALL_MODELS_WITH_T_RELAY, True, True, 0.995, Provider.BAOSTOCK, "query_history_k_data_plus_daily_raw", Provider.TUSHARE, "stock_basic", "raw_baostock.query_history_k_data_plus_daily_raw_v1", "Historical ST flag. Required for exclusion and correct limit rule calculation."),
    _req("source.trade_status_v1", "is_delisting_risk", RequiredLevel.P0, ALL_MODELS_WITH_T_RELAY, True, True, 0.995, Provider.BAOSTOCK, "query_stock_basic", Provider.TUSHARE, "stock_basic", "raw_baostock.query_stock_basic_v1", "Delisting-risk proxy. Free sources may be incomplete; failures are hard data quality warnings."),
    _req("source.trade_calendar_v1", "pretrade_date", RequiredLevel.P0, ["scheduler", *ALL_MODELS], True, True, 1.0, Provider.BAOSTOCK, "query_trade_dates", Provider.TUSHARE, "trade_cal", "raw_baostock.query_trade_dates_v1", "Previous trade date for scheduler materialization, observation windows and T+N labels."),
    _req("source.limit_price_v1", "pre_close_price", RequiredLevel.P0, ALL_MODELS_WITH_T_RELAY, True, True, 0.995, Provider.BAOSTOCK, "query_history_k_data_plus_daily_raw", Provider.TENCENT, "daily_bars", "raw_baostock.query_history_k_data_plus_daily_raw_v1", "Previous close used by internal source build to compute exchange price limits."),
    _req("source.limit_price_v1", "up_limit_price", RequiredLevel.P0, ALL_MODELS_WITH_T_RELAY, True, True, 0.995, Provider.BAOSTOCK, "query_history_k_data_plus_daily_raw", Provider.TENCENT, "daily_bars", "raw_baostock.query_history_k_data_plus_daily_raw_v1", "Up-limit price computed from real raw pre-close and trading rules; external source validates edge cases."),
    _req("source.limit_price_v1", "down_limit_price", RequiredLevel.P0, ALL_MODELS_WITH_T_RELAY, True, True, 0.995, Provider.BAOSTOCK, "query_history_k_data_plus_daily_raw", Provider.TENCENT, "daily_bars", "raw_baostock.query_history_k_data_plus_daily_raw_v1", "Down-limit price computed from real raw pre-close and trading rules; external source validates edge cases."),
    _req("source.limit_price_v1", "limit_rule", RequiredLevel.P0, ALL_MODELS_WITH_T_RELAY, True, True, 0.995, Provider.BAOSTOCK, "query_history_k_data_plus_daily_raw", Provider.TENCENT, "daily_bars", "raw_baostock.query_history_k_data_plus_daily_raw_v1", "Applied price-limit rule, e.g. normal_10pct, st_5pct, chinext_20pct, new_stock_special."),
    _req("source.limit_event_v1", "limit_event_type", RequiredLevel.P0, T_BOARD_RELAY, True, True, 0.995, Provider.THS, "limit_up_pool", Provider.BAOSTOCK, "query_history_k_data_plus_daily_raw", "raw_ths.limit_up_pool_v1", "Limit event classification from THS public limit-up pool. BaoStock daily-bar derivation remains the backup when THS is unavailable."),
    _req("source.limit_event_v1", "is_one_word_board", RequiredLevel.P0, T_BOARD_RELAY, True, True, 0.995, Provider.THS, "limit_up_pool", Provider.BAOSTOCK, "query_history_k_data_plus_daily_raw", "raw_ths.limit_up_pool_v1", "One-word board flag from THS limit-up pool open count/type. Backup derives from raw OHLC and computed up-limit price."),
    _req("source.limit_event_v1", "is_break_limit", RequiredLevel.P0, T_BOARD_RELAY, True, True, 0.995, Provider.THS, "limit_up_pool", Provider.BAOSTOCK, "query_history_k_data_plus_daily_raw", "raw_ths.limit_up_pool_v1", "Break/T-board flag from THS limit-up open count. Backup derives from raw OHLC and computed up-limit price."),
    _req("source.limit_event_v1", "close_on_limit_flag", RequiredLevel.P0, T_BOARD_RELAY, True, True, 0.995, Provider.THS, "limit_up_pool", Provider.BAOSTOCK, "query_history_k_data_plus_daily_raw", "raw_ths.limit_up_pool_v1", "Close-on-limit flag from current THS limit-up pool membership. Backup uses daily close against computed up-limit price."),
    _req("source.limit_event_v1", "limit_open_count", RequiredLevel.P0, T_BOARD_RELAY, True, True, 0.995, Provider.THS, "limit_up_pool", Provider.BAOSTOCK, "query_history_k_data_plus_daily_raw", "raw_ths.limit_up_pool_v1", "Open-board count from THS public limit-up pool. Missing values must remain NULL; backup only approximates from daily bar behavior."),
    _req("source.ths_paid_limit_up_probability_v1", "paid_limit_up_probability", RequiredLevel.P0, ["hot_candidates"], True, True, 0.995, Provider.THS, "paid_limit_up_probability", None, None, "raw_ths.paid_limit_up_probability_v1", "Credentialed THS paid next-day limit-up probability. There is no valid backup source by design; missing or expired cookies block/abandon the candidate batch instead of fabricating a fallback."),
    _req("source.realtime_quote_v1", "latest_price", RequiredLevel.P0, T_BOARD_RELAY, True, True, 0.990, Provider.EASTMONEY, "quote_snapshot", Provider.TENCENT, "quote_snapshot", "raw_eastmoney.quote_snapshot_v1", "Latest quote for Day2 near-limit watch. Tencent quote snapshot is the public fallback after raw/source/lineage validation."),
    _req("source.realtime_quote_v1", "float_market_cap", RequiredLevel.P0, T_BOARD_RELAY, True, True, 0.950, Provider.EASTMONEY, "quote_snapshot", Provider.TUSHARE, "daily_basic", "raw_eastmoney.quote_snapshot_v1", "Float market cap from EastMoney quote snapshot. Missing values block model-four Day1 qualification."),
    _req("source.auction_snapshot_v1", "virtual_open_price", RequiredLevel.P1, ["hot_candidates"], False, True, 0.900, Provider.EASTMONEY, "auction_snapshot", Provider.TENCENT, "auction_snapshot", "raw_eastmoney.auction_snapshot_v1", "Auction virtual open price mapped from public quote snapshot price. It is degradable preopen context; provider raw price must not be exposed as a source field."),
    _req("source.auction_snapshot_v1", "matched_volume", RequiredLevel.P1, ["hot_candidates"], False, True, 0.900, Provider.EASTMONEY, "auction_snapshot", Provider.TENCENT, "auction_snapshot", "raw_eastmoney.auction_snapshot_v1", "Auction matched volume from public quote snapshot volume. Missing values remain NULL/gap and must not be filled with zero."),
    _req("source.auction_snapshot_v1", "matched_amount", RequiredLevel.P1, ["hot_candidates"], False, True, 0.900, Provider.EASTMONEY, "auction_snapshot", Provider.TENCENT, "auction_snapshot", "raw_eastmoney.auction_snapshot_v1", "Auction matched amount from public quote snapshot amount. Provider units remain traceable through raw_row_json and lineage."),
    _req("source.auction_snapshot_v1", "event_time", RequiredLevel.P1, ["hot_candidates"], False, True, 0.900, Provider.EASTMONEY, "auction_snapshot", Provider.TENCENT, "auction_snapshot", "raw_eastmoney.auction_snapshot_v1", "Auction event timestamp used by lineage and downstream freshness checks. It must come from provider/raw timing evidence, not a fabricated default."),
    _req("source.minute_bar_v1", "close_price", RequiredLevel.P0, T_BOARD_RELAY, True, True, 0.990, Provider.EASTMONEY, "minute_bars", Provider.TENCENT, "minute_bars", "raw_eastmoney.minute_bars_v1", "Intraday minute close for Day2 10:30 near-limit watch and post-entry board-open monitoring."),
    _req("source.minute_bar_v1", "high_price", RequiredLevel.P0, T_BOARD_RELAY, True, True, 0.990, Provider.EASTMONEY, "minute_bars", Provider.TENCENT, "minute_bars", "raw_eastmoney.minute_bars_v1", "Intraday minute high for board touch and recovery audit."),
    _req("source.minute_bar_v1", "low_price", RequiredLevel.P0, T_BOARD_RELAY, True, True, 0.990, Provider.EASTMONEY, "minute_bars", Provider.TENCENT, "minute_bars", "raw_eastmoney.minute_bars_v1", "Intraday minute low for board-open/failure audit."),
    _req("source.trade_tick_v1", "price", RequiredLevel.P0, T_BOARD_RELAY, True, True, 0.900, Provider.EASTMONEY, "trade_details", Provider.EASTMONEY, "minute_bars", "raw_eastmoney.trade_details_v1", "Provider trade-detail price used as public tick-like evidence for near-limit order consumption research."),
    _req("source.trade_tick_v1", "side_code", RequiredLevel.P0, T_BOARD_RELAY, True, True, 0.900, Provider.EASTMONEY, "trade_details", Provider.EASTMONEY, "minute_bars", "raw_eastmoney.trade_details_v1", "Provider-native side code. It is auditable evidence and must not be over-interpreted as full order-book depth."),
    _req("source.trade_tick_v1", "amount", RequiredLevel.P1, T_BOARD_RELAY, False, True, 0.900, Provider.EASTMONEY, "trade_details", Provider.EASTMONEY, "minute_bars", "raw_eastmoney.trade_details_v1", "Trade-detail amount derived from price * volume * 100 shares; used for absorption magnitude research."),
    _req("source.index_daily_bar_v1", "open_price", RequiredLevel.P1, ALL_MODELS, False, True, 0.990, Provider.TENCENT, "daily_bars", Provider.BAOSTOCK, "query_history_k_data_plus_daily_raw", "raw_tencent.daily_bars_v1", "Index open for market regime intraday context and relative strength review."),
    _req("source.index_daily_bar_v1", "high_price", RequiredLevel.P1, ALL_MODELS, False, True, 0.990, Provider.TENCENT, "daily_bars", Provider.BAOSTOCK, "query_history_k_data_plus_daily_raw", "raw_tencent.daily_bars_v1", "Index high for market regime envelope and volatility review."),
    _req("source.index_daily_bar_v1", "low_price", RequiredLevel.P1, ALL_MODELS, False, True, 0.990, Provider.TENCENT, "daily_bars", Provider.BAOSTOCK, "query_history_k_data_plus_daily_raw", "raw_tencent.daily_bars_v1", "Index low for market regime envelope and downside pressure review."),
    _req("source.index_daily_bar_v1", "close_price", RequiredLevel.P0, ALL_MODELS, True, True, 0.995, Provider.TENCENT, "daily_bars", Provider.BAOSTOCK, "query_history_k_data_plus_daily_raw", "raw_tencent.daily_bars_v1", "Index close for market regime and relative strength baseline."),
    _req("source.index_daily_bar_v1", "volume", RequiredLevel.P1, ALL_MODELS, False, True, 0.990, Provider.TENCENT, "daily_bars", Provider.BAOSTOCK, "query_history_k_data_plus_daily_raw", "raw_tencent.daily_bars_v1", "Index volume for market breadth and liquidity context; provider-native units must be normalized before canonical compare."),
    _req("source.index_daily_bar_v1", "amount", RequiredLevel.P1, ALL_MODELS, False, True, 0.990, Provider.TENCENT, "daily_bars", Provider.BAOSTOCK, "query_history_k_data_plus_daily_raw", "raw_tencent.daily_bars_v1", "Index turnover amount for market liquidity context and source quality audit."),
    _req("source.index_daily_bar_v1", "pct_chg", RequiredLevel.P1, ALL_MODELS, False, True, 0.990, Provider.TENCENT, "daily_bars", Provider.BAOSTOCK, "query_history_k_data_plus_daily_raw", "raw_tencent.daily_bars_v1", "Index return; can be recomputed from close and stored for audit."),
    _req("source.board_master_v1", "board_name", RequiredLevel.P1, ALL_MODELS, False, True, 0.950, Provider.AKSHARE, "stock_board_industry_name_em", Provider.BAOSTOCK, "query_stock_industry", "raw_akshare.stock_board_industry_name_em_v1", "Board/industry name. Current public source may not be historically stable."),
    _req("source.stock_board_membership_v1", "board_name", RequiredLevel.P1, ALL_MODELS, False, True, 0.950, Provider.AKSHARE, "stock_board_industry_cons_em", Provider.BAOSTOCK, "query_stock_industry", "raw_akshare.stock_board_industry_cons_em_v1", "Stock-to-board membership. If only current snapshot is available, historical backtest must mark it research-only/current_snapshot."),
    _req("source.board_daily_bar_v1", "pct_chg", RequiredLevel.P1, ALL_MODELS, False, True, 0.950, Provider.AKSHARE, "stock_board_industry_hist_em", Provider.INTERNAL, "source_build_board_daily_from_members", "raw_akshare.stock_board_industry_hist_em_v1", "Board return used for relative sector strength and sector environment confirmation."),
    _req("source.stock_moneyflow_daily_v1", "provider_definition", RequiredLevel.P1, ALL_MODELS, False, True, 0.900, Provider.EASTMONEY, "moneyflow_stock_series", Provider.TUSHARE, "moneyflow", "raw_eastmoney.moneyflow_stock_series_v1", "Moneyflow field definition/version. Required because providers define main flow differently."),
    _req("source.event_news_v1", "title", RequiredLevel.RESEARCH_ONLY, ALL_MODELS, False, True, 0.800, Provider.BAIDU, "finance_news_feed", Provider.CNINFO, "cninfo_disclosure_direct", "raw_baidu.finance_news_feed_v1", "Event/news headline from public feed. Required for audit display only; not a model-owned signal."),
    _req("source.event_news_v1", "event_type", RequiredLevel.RESEARCH_ONLY, ALL_MODELS, False, True, 0.800, Provider.BAIDU, "finance_news_feed", Provider.CNINFO, "cninfo_disclosure_direct", "raw_baidu.finance_news_feed_v1", "Provider-normalized event category such as finance_news or announcement. Research-only context."),
    _req("source.event_news_v1", "url", RequiredLevel.RESEARCH_ONLY, ALL_MODELS, False, True, 0.800, Provider.BAIDU, "finance_news_feed", Provider.CNINFO, "cninfo_disclosure_direct", "raw_baidu.finance_news_feed_v1", "Source URL for evidence audit. Missing URL must remain NULL."),
    _req("source.event_news_v1", "available_at", RequiredLevel.RESEARCH_ONLY, ALL_MODELS, False, True, 0.800, Provider.BAIDU, "finance_news_feed", Provider.CNINFO, "cninfo_disclosure_direct", "raw_baidu.finance_news_feed_v1", "Earliest time the event was available to the system. Without this, event data cannot be used as ex-ante online evidence."),
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
    if field_name.endswith("_time"):
        return "TIMESTAMPTZ"
    if field_name.startswith("is_") or field_name.endswith("_flag"):
        return "BOOLEAN"
    if any(token in field_name for token in ("price", "amount", "volume", "pct", "rate", "factor", "close", "open", "high", "low", "inflow", "probability")):
        return "NUMERIC"
    return "TEXT"


def _infer_unit(field_name: str) -> str | None:
    if "price" in field_name or field_name in {"adjusted_open", "adjusted_high", "adjusted_low", "adjusted_close"}:
        return "CNY/share"
    if "volume" in field_name:
        return "shares/provider native units; normalized during build"
    if "amount" in field_name or "inflow" in field_name:
        return "CNY/provider native units; normalized during build"
    if "pct" in field_name or "rate" in field_name or "probability" in field_name:
        return "percent"
    return None


def _infer_adjustment_mode(table_name: str, field_name: str) -> str:
    if table_name == "source.daily_bar_v1" or table_name == "source.limit_price_v1":
        return "raw" if "price" in field_name or field_name in {"open_price", "high_price", "low_price", "close_price", "pre_close_price"} else "not_price"
    if table_name == "source.auction_snapshot_v1":
        return "raw" if field_name.endswith("_price") else "not_price"
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
    if table == "source.ths_paid_limit_up_probability_v1":
        rules.append("paid_limit_up_probability must be parseable Decimal in [0,100]; missing values block the candidate batch")
        rules.append("active THS credential is referenced only by credential_version; cookie values must not enter request_params_json or raw_provider_row")
        rules.append("candidate batch is abandoned only after the next trading day 09:00 Asia/Shanghai deadline")
    if table == "source.auction_snapshot_v1":
        rules.append("snapshot_time and event_time must come from provider/raw timing evidence; restart catch-up must preserve distinct snapshot identities")
        rules.append("virtual_open_price, matched_volume and matched_amount must preserve NULL/gap when the provider omits auction fields")
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
    if provider == Provider.TENCENT:
        if symbol.upper().endswith(".SZ"):
            return f"sz{symbol[:6]}"
        if symbol.upper().endswith(".SH"):
            return f"sh{symbol[:6]}"
        if normalized.lower().startswith(("sz", "sh")) and len(normalized) >= 8:
            return normalized[:8].lower()
        if normalized.startswith(("000", "001", "002", "003", "300", "399")):
            return f"sz{normalized[:6]}"
        return f"sh{normalized[:6]}"
    if provider == Provider.SINA:
        code = normalized.removeprefix("SZ").removeprefix("SH")[:6]
        return f"sh{code}" if code.startswith(("5", "6", "9")) else f"sz{code}"
    if provider == Provider.SOHU:
        code = normalized.removeprefix("SZ").removeprefix("SH")[:6]
        return f"cn_{code}"
    if provider == Provider.EASTMONEY:
        if symbol.startswith(("0.", "1.")):
            return symbol
        code = normalized.removeprefix("SZ").removeprefix("SH")[:6]
        market = "1" if code.startswith(("5", "6", "9")) else "0"
        return f"{market}.{code}"
    if provider == Provider.THS:
        return normalized.removeprefix("SZ").removeprefix("SH")[:6]
    return normalized[:6]


def format_date_for_provider(value: date, provider: Provider) -> str:
    if provider in {Provider.AKSHARE, Provider.TUSHARE, Provider.SOHU}:
        return value.strftime("%Y%m%d")
    return value.isoformat()
