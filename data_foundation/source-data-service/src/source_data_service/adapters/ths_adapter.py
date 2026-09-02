from __future__ import annotations

import json
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from source_data_service.adapters.base import ProviderAdapter
from source_data_service.models import Provider, RawFetchResult
from source_data_service.ths_paid_credentials import active_cookie_values


THS_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
}
ASIA_SHANGHAI = timezone(timedelta(hours=8))
LIMIT_UP_POOL_ENDPOINT = "https://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool"
TRADE_STATUS_ENDPOINT = "https://data.10jqka.com.cn/dataapi/limit_up/trade_status"
ZHANGTING5_ENDPOINT = "https://eq.10jqka.com.cn/open/api/wencai/zhangting5.txt"
MARKET_STATE_OVERVIEW_ENDPOINT = "https://data.10jqka.com.cn/mobileapi/hotspot_focus/market_state/v1/overview"
WIND_VANE_ENDPOINT = "https://data.10jqka.com.cn/mobileapi/hotspot_focus/market_state/v1/get_wind_vane_stock"
HOT_BLOCK_ENDPOINT = "https://eq.10jqka.com.cn/pick/block/block_hotspot/hotspot/v1/hot_block_list"
MARKET_CAPITAL_ENDPOINT = "https://dq.10jqka.com.cn/fuyao/capital_flow/market_capital/v1/get"
STOCK_CONCEPT_ENDPOINT = "https://basic.10jqka.com.cn/basicapi/concept/stock_concept_list/"
STOCK_FOCUSDAY_ENDPOINT = "https://basic.10jqka.com.cn/api/stockph/focusday.php"
PAID_LIMIT_UP_PROBABILITY_ENDPOINT = "https://apigate.10jqka.com.cn/d/charge/limit_up/market/query/v1/stock/probability"
DEFAULT_LIMIT_UP_FIELD = (
    "199112,9001,330324,3475914,9002,133971,1968584,3475913,9003,9004,"
    "330329,9005,264648,199112,330325,9006,330323,9007,330328,9008,199113,"
    "133970,1968586,3475915,9009"
)


def _decode_json_response(content: bytes, charset: str | None) -> Any:
    candidates = [charset, "utf-8", "gb18030", "gbk"]
    seen: set[str] = set()
    for encoding in candidates:
        if not encoding:
            continue
        normalized = encoding.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        try:
            return json.loads(content.decode(normalized))
        except Exception:
            continue
    return json.loads(content.decode("utf-8", errors="replace"))


def _request_json(url: str, params: dict[str, Any] | None = None, *, referer: str = "https://data.10jqka.com.cn/ztzt/") -> Any:
    import requests

    headers = {**THS_HEADERS, "Referer": referer}
    response = requests.get(url, params=params or {}, headers=headers, timeout=15)
    response.raise_for_status()
    return _decode_json_response(response.content, response.encoding)


def _request_paid_probability(params: dict[str, Any]) -> dict[str, Any]:
    import requests

    credential = active_cookie_values()
    if credential is None:
        raise RuntimeError("ths paid probability cookie is not configured")
    user_cookie, userid_cookie, _version = credential
    request_params = {
        "date": str(params.get("date") or params.get("trade_date") or "").replace("-", ""),
        "stock_code": str(params.get("stock_code") or params.get("code") or params.get("symbol") or "")[:6],
    }
    if len(request_params["date"]) != 8 or not request_params["date"].isdigit():
        raise RuntimeError("ths paid probability requires date=YYYYMMDD")
    if len(request_params["stock_code"]) != 6 or not request_params["stock_code"].isdigit():
        raise RuntimeError("ths paid probability requires stock_code as six digits")
    headers = {
        "Host": "apigate.10jqka.com.cn",
        "Accept": "*/*",
        "User-Agent": "IHexin/12.06.00 (iPhone; iOS 18.7.8; Scale/3.00)",
        "Accept-Language": "zh-Hans-CN;q=1, zh-Hant-HK;q=0.9, yue-Hant-CN;q=0.8, en-GB;q=0.7",
    }
    response = requests.get(
        PAID_LIMIT_UP_PROBABILITY_ENDPOINT,
        params=request_params,
        headers=headers,
        cookies={"user": user_cookie, "userid": userid_cookie},
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("ths paid probability returned non-object json")
    return payload


def _date_text(value: Any) -> str | None:
    if value in (None, "", "-", "--"):
        return None
    text = str(value).strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    return text


def _compact_date(value: Any) -> str | None:
    text = _date_text(value)
    return text.replace("-", "") if text else None


def _num_text(value: Any) -> str | None:
    if value in (None, "", "-", "--"):
        return None
    try:
        return str(Decimal(str(value).replace(",", "").replace("%", "").strip()))
    except (InvalidOperation, ValueError):
        return None


def _probability_text(value: Any) -> str:
    parsed = Decimal(str(value).replace("%", "").strip())
    if parsed < 0 or parsed > 100:
        raise RuntimeError("ths paid probability data is outside 0-100")
    return str(parsed)


def _int_value(value: Any) -> int | None:
    if value in (None, "", "-", "--"):
        return None
    try:
        return int(Decimal(str(value).replace(",", "")))
    except (InvalidOperation, ValueError):
        return None


def _bool_value(value: Any) -> bool | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n"}:
        return False
    return None


def _symbol_from_code(code: Any) -> str | None:
    text = str(code or "").strip()
    if len(text) != 6 or not text.isdigit():
        return None
    if text.startswith(("5", "6", "9")):
        return f"{text}.SH"
    if text.startswith(("0", "1", "2", "3")):
        return f"{text}.SZ"
    if text.startswith(("4", "8")):
        return f"{text}.BJ"
    return None


def _timestamp_to_iso(value: Any, trade_date: str | None) -> str | None:
    raw = _int_value(value)
    if raw is None or raw <= 0:
        return None
    if raw > 1_000_000_000_000:
        raw = raw // 1000
    if raw >= 946_684_800:
        return datetime.fromtimestamp(raw, tz=timezone.utc).isoformat()
    if trade_date and raw < 86400:
        base = datetime.combine(datetime.fromisoformat(trade_date).date(), time.min, tzinfo=ASIA_SHANGHAI)
        return (base + timedelta(seconds=raw)).isoformat()
    return None


def _limit_stage(high_days_value: Any) -> int | None:
    raw = _int_value(high_days_value)
    if raw is None:
        return None
    stage = raw >> 16 if raw >= 65536 else raw
    return stage if stage > 0 else None


def _limit_event_type(row: dict[str, Any]) -> str:
    open_count = _int_value(row.get("open_num")) or 0
    limit_type = str(row.get("limit_up_type") or "").upper()
    if open_count > 0 or "T" in limit_type:
        return "t_board_limit_up"
    return "limit_up"


def _limit_pool_page(params: dict[str, Any], page: int) -> dict[str, Any]:
    request_params = {
        "page": page,
        "limit": int(params.get("limit") or 50),
        "field": str(params.get("field") or DEFAULT_LIMIT_UP_FIELD),
    }
    if params.get("filter"):
        request_params["filter"] = str(params["filter"])
    payload = _request_json(LIMIT_UP_POOL_ENDPOINT, request_params, referer="https://data.10jqka.com.cn/ztzt/")
    if not isinstance(payload, dict):
        raise RuntimeError("ths limit_up_pool returned non-object json")
    status_code = payload.get("status_code")
    if status_code not in (0, "0", None):
        raise RuntimeError(f"ths limit_up_pool status={status_code} msg={payload.get('status_msg')}")
    return payload


def _limit_up_pool_rows(params: dict[str, Any]) -> list[dict[str, Any]]:
    first = _limit_pool_page(params, 1)
    data = first.get("data") if isinstance(first.get("data"), dict) else {}
    page_block = data.get("page") if isinstance(data, dict) and isinstance(data.get("page"), dict) else {}
    total_pages = int(page_block.get("count") or 1)
    rows = list(data.get("info") or []) if isinstance(data, dict) else []
    if bool(params.get("fetch_all_pages", True)) and total_pages > 1:
        for page_no in range(2, total_pages + 1):
            payload = _limit_pool_page(params, page_no)
            page_data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            rows.extend(list(page_data.get("info") or []))
    trade_date = _date_text(data.get("date") if isinstance(data, dict) else None)
    normalized: list[dict[str, Any]] = []
    for rank_no, raw_row in enumerate(rows, start=1):
        if not isinstance(raw_row, dict):
            continue
        code = str(raw_row.get("code") or "").strip()
        symbol = _symbol_from_code(code)
        if not code or not symbol:
            continue
        first_time = _timestamp_to_iso(raw_row.get("first_limit_up_time"), trade_date)
        last_time = _timestamp_to_iso(raw_row.get("last_limit_up_time"), trade_date)
        normalized.append(
            {
                "date": trade_date,
                "trade_date": trade_date,
                "code": code,
                "symbol": symbol,
                "provider_market": str(raw_row.get("market_type") or ""),
                "name": raw_row.get("name"),
                "rank_no": rank_no,
                "latest_price": _num_text(raw_row.get("latest")),
                "change_pct": _num_text(raw_row.get("change_rate")),
                "turnover_rate": _num_text(raw_row.get("turnover_rate")),
                "limit_up_type": raw_row.get("limit_up_type"),
                "reason_type": raw_row.get("reason_type"),
                "first_limit_up_time": first_time,
                "last_limit_up_time": last_time,
                "limit_open_count": _int_value(raw_row.get("open_num")),
                "open_num": _int_value(raw_row.get("open_num")),
                "order_volume": _num_text(raw_row.get("order_volume")),
                "order_amount": _num_text(raw_row.get("order_amount")),
                "float_market_cap": _num_text(raw_row.get("currency_value")),
                "total_market_cap": _num_text(raw_row.get("sum_market_value")),
                "is_again_limit": _bool_value(raw_row.get("is_again_limit")),
                "is_new": _bool_value(raw_row.get("is_new")),
                "high_days": raw_row.get("high_days"),
                "high_days_value": _int_value(raw_row.get("high_days_value")),
                "limit_up_stage": _limit_stage(raw_row.get("high_days_value")),
                "change_tag": raw_row.get("change_tag"),
                "time_preview_json": list(raw_row.get("time_preview") or []),
                "close_on_limit_flag": True,
                "is_one_word_board": (_int_value(raw_row.get("open_num")) or 0) == 0,
                "is_break_limit": (_int_value(raw_row.get("open_num")) or 0) > 0,
                "limit_event_type": _limit_event_type(raw_row),
                "raw_provider_row": raw_row,
            }
        )
    return normalized


def _single_payload_row(api_name: str, params: dict[str, Any], payload: Any, *, endpoint: str) -> list[dict[str, Any]]:
    captured_at = datetime.now(timezone.utc).isoformat()
    trade_date = _date_text(params.get("trade_date") or params.get("date"))
    return [
        {
            "endpoint": endpoint,
            "captured_at": captured_at,
            "payload_status": payload.get("status_code") if isinstance(payload, dict) else None,
            "date": trade_date,
            "trade_date": trade_date,
            "api_name": api_name,
            "payload_json": payload,
        }
    ]


def _zhangting5_rows(params: dict[str, Any]) -> list[dict[str, Any]]:
    payload = _request_json(ZHANGTING5_ENDPOINT, {}, referer="https://eq.10jqka.com.cn/hxapp/hqMarket/index.html")
    source_rows = payload if isinstance(payload, list) else []
    rows: list[dict[str, Any]] = []
    for rank_no, row in enumerate(source_rows, start=1):
        if not isinstance(row, dict):
            continue
        news = row.get("news") if isinstance(row.get("news"), dict) else {}
        code = str(row.get("code") or "").strip()
        rows.append(
            {
                "date": _date_text(params.get("trade_date") or params.get("date")),
                "code": code,
                "symbol": _symbol_from_code(code),
                "rank_no": rank_no,
                "provider_market": str(row.get("market_code") or ""),
                "name": row.get("name"),
                "change_pct": _num_text(row.get("rate")),
                "stage_text": row.get("jtjb"),
                "reason_title": news.get("title"),
                "reason_summary": news.get("summ"),
                "published_at_text": news.get("date"),
                "available_at": datetime.now(timezone.utc).isoformat(),
                "event_type": "limit_up_reason",
                "url": news.get("url") or None,
                "raw_provider_row": row,
            }
        )
    return rows


def _wind_vane_rows(params: dict[str, Any]) -> list[dict[str, Any]]:
    trade_date = _compact_date(params.get("trade_date") or params.get("date"))
    payload = _request_json(WIND_VANE_ENDPOINT, {"date": trade_date} if trade_date else {}, referer="https://data.10jqka.com.cn/mobile/limitup/v2/index.html")
    data = payload.get("data") if isinstance(payload, dict) and isinstance(payload.get("data"), dict) else {}
    rows: list[dict[str, Any]] = []
    for tab in list(data.get("tab_list") or []):
        if not isinstance(tab, dict):
            continue
        for rank_no, stock in enumerate(list(tab.get("stock_list") or []), start=1):
            if not isinstance(stock, dict):
                continue
            code = str(stock.get("stock_code") or "").strip()
            rows.append(
                {
                    "date": _date_text(trade_date),
                    "code": code,
                    "symbol": _symbol_from_code(code),
                    "tab_name": tab.get("tab_name"),
                    "rank_no": rank_no,
                    "name": stock.get("stock_name"),
                    "price": _num_text(stock.get("price")),
                    "change_pct": _num_text(stock.get("change")),
                    "reason": stock.get("reason"),
                    "raw_provider_row": stock,
                }
            )
    return rows


def _hot_block_rows(params: dict[str, Any]) -> list[dict[str, Any]]:
    payload = _request_json(
        HOT_BLOCK_ENDPOINT,
        {
            "type": str(params.get("type") or "con"),
            "field": str(params.get("field") or "zf"),
            "day_num": int(params.get("day_num") or 10),
            "block_num": int(params.get("block_num") or 4),
        },
        referer="https://eq.10jqka.com.cn/hxapp/hqMarket/index.html",
    )
    data = payload.get("data") if isinstance(payload, dict) and isinstance(payload.get("data"), dict) else {}
    rows: list[dict[str, Any]] = []
    for day_block in list(data.get("data_list") or []):
        if not isinstance(day_block, dict):
            continue
        block_date = _date_text(day_block.get("date"))
        for rank_no, block in enumerate(list(day_block.get("block_list") or []), start=1):
            if not isinstance(block, dict):
                continue
            info = block.get("info") if isinstance(block.get("info"), dict) else {}
            rows.append(
                {
                    "date": block_date,
                    "block_code": str(block.get("code") or ""),
                    "block_name": block.get("name"),
                    "rank_no": rank_no,
                    "provider_market": str(block.get("market") or ""),
                    "block_type": block.get("type"),
                    "change_pct": _num_text(info.get("zf")),
                    "raw_provider_row": block,
                }
            )
    return rows


def _stock_concept_rows(params: dict[str, Any]) -> list[dict[str, Any]]:
    symbol = str(params.get("symbol") or params.get("code") or "000759")[:6]
    payload = _request_json(STOCK_CONCEPT_ENDPOINT, {"code": symbol, "locale": "zh_CN"}, referer="https://basic.10jqka.com.cn/astockph/briefinfo/index.html")
    data = payload.get("data") if isinstance(payload, dict) else []
    rows: list[dict[str, Any]] = []
    for rank_no, row in enumerate(list(data or []), start=1):
        if not isinstance(row, dict):
            continue
        rows.append(
            {
                "symbol": _symbol_from_code(symbol),
                "code": symbol,
                "concept_id": str(row.get("concept_id") or ""),
                "concept_name": row.get("concept_name"),
                "rank_no": rank_no,
                "provider_market": str(row.get("market_id") or ""),
                "concept_explain": row.get("concept_explain"),
                "raw_provider_row": row,
            }
        )
    return rows


def _stock_focusday_rows(params: dict[str, Any]) -> list[dict[str, Any]]:
    symbol = str(params.get("symbol") or params.get("code") or "000759")[:6]
    payload = _request_json(STOCK_FOCUSDAY_ENDPOINT, {"code": symbol}, referer="https://basic.10jqka.com.cn/astockph/briefinfo/index.html")
    data = payload.get("data") if isinstance(payload, dict) and isinstance(payload.get("data"), dict) else {}
    now = data.get("now") if isinstance(data.get("now"), dict) else {}
    return [
        {
            "symbol": _symbol_from_code(symbol),
            "code": symbol,
            "rank": _int_value(data.get("rank")),
            "total": _int_value(data.get("total")),
            "description": data.get("desc"),
            "updated_at_text": now.get("update_time") or now.get("update"),
            "payload_json": payload,
        }
    ]


def _paid_limit_up_probability_rows(params: dict[str, Any]) -> list[dict[str, Any]]:
    payload = _request_paid_probability(params)
    status_code = payload.get("status_code")
    if status_code not in (0, "0"):
        raise RuntimeError(f"ths paid probability status={status_code} msg={payload.get('status_msg')}")
    probability = _probability_text(payload.get("data"))
    date_text = _date_text(params.get("date") or params.get("trade_date"))
    code = str(params.get("stock_code") or params.get("code") or "")[:6]
    symbol = _symbol_from_code(code)
    if not date_text or not symbol:
        raise RuntimeError("ths paid probability response cannot be normalized without date and symbol")
    return [
        {
            "date": date_text,
            "trade_date": date_text,
            "code": code,
            "stock_code": code,
            "symbol": symbol,
            "paid_limit_up_probability": probability,
            "status_code": int(status_code),
            "status_msg": payload.get("status_msg"),
            "credential_version": params.get("credential_version"),
            "endpoint": PAID_LIMIT_UP_PROBABILITY_ENDPOINT,
            "available_at": datetime.now(timezone.utc).isoformat(),
            "raw_provider_row": payload,
        }
    ]


class THSAdapter(ProviderAdapter):
    provider = Provider.THS

    def fetch(self, api_name: str, params: dict[str, Any], *, dry_run: bool = False) -> RawFetchResult:
        if dry_run:
            return self.build_result(api_name, params, [], dry_run=True, warning="dry_run: provider not called")
        if api_name == "limit_up_pool":
            return self.build_result(api_name, params, _limit_up_pool_rows(params))
        if api_name == "trade_status":
            payload = _request_json(TRADE_STATUS_ENDPOINT, {}, referer="https://data.10jqka.com.cn/mobile/limitup/v2/index.html")
            return self.build_result(api_name, params, _single_payload_row(api_name, params, payload, endpoint=TRADE_STATUS_ENDPOINT))
        if api_name == "zhangting5_reasons":
            return self.build_result(api_name, params, _zhangting5_rows(params))
        if api_name == "market_state_overview":
            trade_date = _compact_date(params.get("trade_date") or params.get("date"))
            payload = _request_json(MARKET_STATE_OVERVIEW_ENDPOINT, {"date": trade_date} if trade_date else {}, referer="https://data.10jqka.com.cn/mobile/limitup/v2/index.html")
            return self.build_result(api_name, params, _single_payload_row(api_name, params, payload, endpoint=MARKET_STATE_OVERVIEW_ENDPOINT))
        if api_name == "wind_vane_stock":
            return self.build_result(api_name, params, _wind_vane_rows(params))
        if api_name == "hot_block_list":
            return self.build_result(api_name, params, _hot_block_rows(params))
        if api_name == "market_capital":
            payload = _request_json(MARKET_CAPITAL_ENDPOINT, {}, referer="https://eq.10jqka.com.cn/hxapp/hqMarket/index.html")
            return self.build_result(api_name, params, _single_payload_row(api_name, params, payload, endpoint=MARKET_CAPITAL_ENDPOINT))
        if api_name == "stock_concepts":
            return self.build_result(api_name, params, _stock_concept_rows(params))
        if api_name == "stock_focusday":
            return self.build_result(api_name, params, _stock_focusday_rows(params))
        if api_name == "paid_limit_up_probability":
            return self.build_result(api_name, params, _paid_limit_up_probability_rows(params))
        raise KeyError(f"unsupported ths api: {api_name}")
