from __future__ import annotations

import math
import time
from typing import Any

from source_data_service.adapters.base import ProviderAdapter, dataframe_to_rows
from source_data_service.models import Provider, RawFetchResult


EASTMONEY_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
    "Referer": "https://quote.eastmoney.com/",
}


def _eastmoney_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
    import requests

    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = requests.get(url, params=params, headers=EASTMONEY_HEADERS, timeout=15)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise RuntimeError("eastmoney fallback returned non-object json")
            return data
        except Exception as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(1.0 + attempt)
    raise RuntimeError(f"eastmoney fallback request failed: {last_error}") from last_error


def _eastmoney_paginated_diff(url: str, params: dict[str, Any], *, max_pages: int | None = None) -> list[dict[str, Any]]:
    first = _eastmoney_json(url, params)
    data = first.get("data") or {}
    diff = data.get("diff") or []
    if not isinstance(diff, list):
        raise RuntimeError("eastmoney fallback returned invalid diff payload")
    rows = [dict(item) for item in diff if isinstance(item, dict)]
    total = int(data.get("total") or len(rows))
    page_size = max(len(rows), 1)
    total_pages = max(math.ceil(total / page_size), 1)
    if max_pages is not None:
        total_pages = min(total_pages, max(max_pages, 1))
    for page in range(2, total_pages + 1):
        page_params = dict(params)
        page_params["pn"] = str(page)
        time.sleep(1.0)
        payload = _eastmoney_json(url, page_params)
        page_data = payload.get("data") or {}
        page_diff = page_data.get("diff") or []
        if not isinstance(page_diff, list):
            raise RuntimeError("eastmoney fallback returned invalid paginated diff payload")
        rows.extend(dict(item) for item in page_diff if isinstance(item, dict))
    return rows


def _stock_zh_a_spot_em_fallback_rows(params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    url = "https://82.push2.eastmoney.com/api/qt/clist/get"
    request_params = {
        "pn": "1",
        "pz": "100",
        "po": "1",
        "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "fid": "f12",
        "fs": "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048",
        "fields": (
            "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f13,f14,f15,f16,f17,f18,"
            "f20,f21,f23,f24,f25,f22,f11,f62,f128,f136,f115,f152"
        ),
    }
    probe_params = params or {}
    probe_page_limit = probe_params.get("_probe_page_limit")
    max_pages = int(probe_page_limit) if probe_page_limit is not None else None
    if probe_page_limit is not None:
        request_params["pz"] = "1"
    rows = _eastmoney_paginated_diff(url, request_params, max_pages=max_pages)
    mapped: list[dict[str, Any]] = []
    for index, item in enumerate(rows, start=1):
        mapped.append(
            {
                "序号": index,
                "代码": item.get("f12"),
                "名称": item.get("f14"),
                "最新价": item.get("f2"),
                "涨跌幅": item.get("f3"),
                "涨跌额": item.get("f4"),
                "成交量": item.get("f5"),
                "成交额": item.get("f6"),
                "振幅": item.get("f7"),
                "最高": item.get("f15"),
                "最低": item.get("f16"),
                "今开": item.get("f17"),
                "昨收": item.get("f18"),
                "量比": item.get("f10"),
                "换手率": item.get("f8"),
                "市盈率-动态": item.get("f9"),
                "市净率": item.get("f23"),
                "总市值": item.get("f20"),
                "流通市值": item.get("f21"),
                "涨速": item.get("f22"),
                "5分钟涨跌": item.get("f11"),
                "60日涨跌幅": item.get("f24"),
                "年初至今涨跌幅": item.get("f25"),
            }
        )
    return mapped


def _index_zh_a_hist_fallback_rows(params: dict[str, Any]) -> list[dict[str, Any]]:
    symbol = str(params["symbol"])
    period_code = {"daily": "101", "weekly": "102", "monthly": "103"}[params.get("period", "daily")]
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    base_params = {
        "ut": "7eea3edcaed734bea9cbfc24409ed989",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": period_code,
        "fqt": "0",
        "beg": str(params["start_date"]),
        "end": str(params["end_date"]),
    }
    payload: dict[str, Any] | None = None
    for market_id in ("0", "1", "2", "47"):
        probe_params = dict(base_params)
        probe_params["secid"] = f"{market_id}.{symbol}"
        candidate = _eastmoney_json(url, probe_params)
        if candidate.get("data") and candidate["data"].get("klines"):
            payload = candidate
            break
    if payload is None:
        return []

    rows: list[dict[str, Any]] = []
    for line in payload["data"]["klines"]:
        parts = str(line).split(",")
        if len(parts) < 11:
            continue
        rows.append(
            {
                "日期": parts[0],
                "开盘": parts[1],
                "收盘": parts[2],
                "最高": parts[3],
                "最低": parts[4],
                "成交量": parts[5],
                "成交额": parts[6],
                "振幅": parts[7],
                "涨跌幅": parts[8],
                "涨跌额": parts[9],
                "换手率": parts[10],
            }
        )
    return rows


def _eastmoney_stock_market_ids(symbol: str) -> tuple[str, ...]:
    code = symbol.split(".")[0].strip().lower().removeprefix("sz").removeprefix("sh")
    if code.startswith("6"):
        return ("1", "0", "2")
    return ("0", "1", "2")


def _stock_zh_a_hist_fallback_rows(params: dict[str, Any]) -> list[dict[str, Any]]:
    symbol = str(params["symbol"])
    code = symbol.split(".")[0].strip().lower().removeprefix("sz").removeprefix("sh")
    period_code = {"daily": "101", "weekly": "102", "monthly": "103"}[params.get("period", "daily")]
    adjust = params.get("adjust", "")
    fqt = "1" if adjust == "qfq" else "0"
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    base_params = {
        "ut": "7eea3edcaed734bea9cbfc24409ed989",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": period_code,
        "fqt": fqt,
        "beg": str(params["start_date"]).replace("-", ""),
        "end": str(params["end_date"]).replace("-", ""),
    }
    payload: dict[str, Any] | None = None
    for market_id in _eastmoney_stock_market_ids(code):
        probe_params = dict(base_params)
        probe_params["secid"] = f"{market_id}.{code}"
        candidate = _eastmoney_json(url, probe_params)
        if candidate.get("data") and candidate["data"].get("klines"):
            payload = candidate
            break
    if payload is None:
        return []

    rows: list[dict[str, Any]] = []
    for line in payload["data"]["klines"]:
        parts = str(line).split(",")
        if len(parts) < 11:
            continue
        rows.append(
            {
                "日期": parts[0],
                "开盘": parts[1],
                "收盘": parts[2],
                "最高": parts[3],
                "最低": parts[4],
                "成交量": parts[5],
                "成交额": parts[6],
                "振幅": parts[7],
                "涨跌幅": parts[8],
                "涨跌额": parts[9],
                "换手率": parts[10],
                "股票代码": code,
            }
        )
    return rows


class AKShareAdapter(ProviderAdapter):
    provider = Provider.AKSHARE

    def fetch(self, api_name: str, params: dict[str, Any], *, dry_run: bool = False) -> RawFetchResult:
        if dry_run:
            return self.build_result(api_name, params, [], dry_run=True, warning="dry_run: provider not called")
        try:
            import akshare as ak  # type: ignore
        except Exception as exc:  # pragma: no cover - depends on optional provider
            raise RuntimeError("akshare package is not installed or cannot be imported") from exc

        if api_name == "stock_zh_a_spot_em":
            try:
                frame = ak.stock_zh_a_spot_em()
                return self.build_result(api_name, params, dataframe_to_rows(frame))
            except Exception:
                return self.build_result(api_name, params, _stock_zh_a_spot_em_fallback_rows(params))

        if api_name == "index_zh_a_hist":
            try:
                frame = ak.index_zh_a_hist(
                    symbol=params["symbol"],
                    period=params.get("period", "daily"),
                    start_date=params["start_date"],
                    end_date=params["end_date"],
                )
                return self.build_result(api_name, params, dataframe_to_rows(frame))
            except Exception:
                return self.build_result(api_name, params, _index_zh_a_hist_fallback_rows(params))

        if api_name in {"stock_zh_a_hist_daily_raw", "stock_zh_a_hist_daily_qfq"}:
            try:
                frame = ak.stock_zh_a_hist(
                    symbol=params["symbol"],
                    period=params.get("period", "daily"),
                    start_date=params["start_date"],
                    end_date=params["end_date"],
                    adjust=params.get("adjust", "qfq" if api_name.endswith("qfq") else ""),
                )
                return self.build_result(api_name, params, dataframe_to_rows(frame))
            except Exception:
                return self.build_result(api_name, params, _stock_zh_a_hist_fallback_rows(params))

        if api_name == "stock_zh_a_spot_em":
            frame = ak.stock_zh_a_spot_em()
        elif api_name == "stock_board_industry_name_em":
            frame = ak.stock_board_industry_name_em()
        elif api_name == "stock_board_industry_cons_em":
            frame = ak.stock_board_industry_cons_em(symbol=params["symbol"])
        elif api_name == "stock_board_industry_hist_em":
            frame = ak.stock_board_industry_hist_em(symbol=params["symbol"], adjust=params.get("adjust", ""))
        elif api_name == "stock_fund_flow_individual_realtime":
            frame = ak.stock_fund_flow_individual(symbol=params.get("symbol", "即时"))
        elif api_name == "index_zh_a_hist":
            frame = ak.index_zh_a_hist(
                symbol=params["symbol"],
                period=params.get("period", "daily"),
                start_date=params["start_date"],
                end_date=params["end_date"],
            )
        elif api_name == "stock_zh_a_disclosure_report_cninfo":
            frame = ak.stock_zh_a_disclosure_report_cninfo(
                symbol=params["symbol"],
                market=params.get("market", "沪深京"),
                start_date=params["start_date"],
                end_date=params["end_date"],
            )
        else:
            raise KeyError(f"unsupported akshare api: {api_name}")
        return self.build_result(api_name, params, dataframe_to_rows(frame))
