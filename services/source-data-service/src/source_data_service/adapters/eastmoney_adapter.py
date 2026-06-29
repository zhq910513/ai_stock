from __future__ import annotations

from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from source_data_service.adapters.base import ProviderAdapter
from source_data_service.models import Provider, RawFetchResult


EASTMONEY_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
    "Referer": "https://quote.eastmoney.com/",
    "Accept": "application/json,text/plain,*/*",
    "Connection": "close",
}

EASTMONEY_UNIVERSE_SEGMENTS = {
    "main_sh": {"fs": "m:1+t:2", "exchange": "SH", "board": "main_sh"},
    "main_sz": {"fs": "m:0+t:6", "exchange": "SZ", "board": "main_sz"},
    "chinext": {"fs": "m:0+t:80", "exchange": "SZ", "board": "chinext"},
    "star": {"fs": "m:1+t:23", "exchange": "SH", "board": "star"},
    "bse": {"fs": "m:0+t:81+s:2048", "exchange": "BJ", "board": "bse"},
}


def _secid_from_symbol(value: str) -> str:
    text = str(value).strip()
    if "." in text and text.split(".", 1)[0] in {"0", "1"}:
        return text
    code = text.split(".")[0].lower().removeprefix("sz").removeprefix("sh")[:6]
    market = "1" if code.startswith(("5", "6", "9")) else "0"
    return f"{market}.{code}"


def _symbol_from_secid(secid: str) -> str | None:
    try:
        market, code = str(secid).split(".", 1)
    except ValueError:
        return None
    suffix = "SH" if market == "1" else "SZ"
    return f"{code[:6]}.{suffix}"


def _date_text(value: Any) -> str | None:
    if value in (None, "", "-", "--"):
        return None
    text = str(value).strip()
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return text


def _num(value: Any) -> str | None:
    if value in (None, "", "-", "--"):
        return None
    try:
        return str(Decimal(str(value).replace(",", "")))
    except (InvalidOperation, ValueError):
        return None


def _event_time(value: Any, *, fallback_date: str | None = None) -> str:
    china_tz = timezone(timedelta(hours=8))
    text = str(value or "").strip()
    if len(text) == 14 and text.isdigit():
        return datetime(
            int(text[:4]),
            int(text[4:6]),
            int(text[6:8]),
            int(text[8:10]),
            int(text[10:12]),
            int(text[12:14]),
            tzinfo=china_tz,
        ).isoformat()
    if fallback_date:
        if len(text) == 5 and text.count(":") == 1:
            time_part = f"{text}:00"
        elif len(text) == 8 and text.count(":") == 2:
            time_part = text
        else:
            time_part = "15:00:00"
        return f"{fallback_date}T{time_part}+08:00"
    return datetime.now(china_tz).isoformat()


def _eastmoney_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
    import requests

    last_error: Exception | None = None
    endpoints = (
        url,
        url.replace("https://push2.eastmoney.com/", "https://push2delay.eastmoney.com/"),
        url.replace("https://push2his.eastmoney.com/", "https://push2delay.eastmoney.com/"),
    )
    seen: set[str] = set()
    for endpoint in endpoints:
        if endpoint in seen:
            continue
        seen.add(endpoint)
        for attempt in range(3):
            try:
                response = requests.get(endpoint, params=params, headers=EASTMONEY_HEADERS, timeout=15)
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise RuntimeError("eastmoney returned non-object json")
                return payload
            except Exception as exc:  # noqa: BLE001 - provider instability becomes probe evidence
                last_error = exc
                if attempt < 2:
                    import time

                    time.sleep(0.8 + attempt)
    raise RuntimeError(f"eastmoney request failed: {last_error}") from last_error


def _moneyflow_stock_series_rows(params: dict[str, Any]) -> list[dict[str, Any]]:
    secid = _secid_from_symbol(str(params.get("secid") or params.get("symbol") or "0.000063"))
    lmt = int(params.get("lmt") or params.get("count") or 120)
    payload = _eastmoney_json(
        "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get",
        {
            "lmt": str(lmt),
            "klt": str(params.get("klt") or "101"),
            "secid": secid,
            "fields1": "f1,f2,f3,f7",
            "fields2": "f51,f52,f53,f54,f55,f56",
        },
    )
    data = payload.get("data") or {}
    klines = data.get("klines") or []
    if not isinstance(klines, list):
        raise RuntimeError("eastmoney moneyflow_stock_series returned invalid klines payload")
    symbol = _symbol_from_secid(secid)
    rows: list[dict[str, Any]] = []
    for line in klines:
        parts = str(line).split(",")
        if len(parts) < 6:
            continue
        trade_date = _date_text(parts[0])
        if not trade_date:
            continue
        rows.append(
            {
                "date": trade_date,
                "symbol": symbol,
                "secid": secid,
                "main_net_inflow": parts[1],
                "super_large_net_inflow": parts[2],
                "large_net_inflow": parts[3],
                "medium_net_inflow": parts[4],
                "small_net_inflow": parts[5],
                "provider_definition": "eastmoney_fflow_kline_get:f51=date,f52=main,f53=super_large,f54=large,f55=medium,f56=small",
            }
        )
    start_date = _date_text(params.get("start_date") or params.get("beg"))
    end_date = _date_text(params.get("end_date") or params.get("end"))
    if start_date:
        rows = [row for row in rows if str(row["date"]) >= start_date]
    if end_date:
        rows = [row for row in rows if str(row["date"]) <= end_date]
    return rows


def _quote_snapshot_rows(params: dict[str, Any]) -> list[dict[str, Any]]:
    secid = _secid_from_symbol(str(params.get("secid") or params.get("symbol") or "0.000759"))
    fields = (
        "f19,f20,f31,f32,f39,f40,f43,f44,f45,f46,f47,f48,f57,f58,"
        "f60,f86,f116,f117,f168,f169,f170"
    )
    payload = _eastmoney_json(
        "https://push2.eastmoney.com/api/qt/stock/get",
        {"secid": secid, "fields": fields, "fltt": "2", "invt": "2"},
    )
    data = payload.get("data") or {}
    if not isinstance(data, dict) or not data:
        return []
    symbol = _symbol_from_secid(secid)
    provider_market, provider_symbol = secid.split(".", 1)
    trade_date = _date_text(params.get("trade_date") or params.get("start_date") or params.get("end_date"))
    if trade_date is None and data.get("f86"):
        trade_date = _date_text(str(data.get("f86"))[:8])
    row = {
        **{key: data.get(key) for key in fields.split(",")},
        "symbol": symbol,
        "secid": secid,
        "provider_symbol": provider_symbol,
        "provider_market": provider_market,
        "trade_date": trade_date,
        "event_time": _event_time(data.get("f86"), fallback_date=trade_date),
        "last_price": _num(data.get("f43")),
        "high_price": _num(data.get("f44")),
        "low_price": _num(data.get("f45")),
        "open_price": _num(data.get("f46")),
        "volume": _num(data.get("f47")),
        "amount": _num(data.get("f48")),
        "prev_close_price": _num(data.get("f60")),
        "total_market_cap": _num(data.get("f116")),
        "float_market_cap": _num(data.get("f117")),
        "turnover_rate": _num(data.get("f168")),
        "change_amount": _num(data.get("f169")),
        "change_pct": _num(data.get("f170")),
    }
    return [row]


def _auction_snapshot_rows(params: dict[str, Any]) -> list[dict[str, Any]]:
    secid = _secid_from_symbol(str(params.get("secid") or params.get("symbol") or "0.000759"))
    fields = "f43,f46,f47,f48,f60,f86,f19,f20,f31,f32,f39,f40"
    payload = _eastmoney_json(
        "https://push2.eastmoney.com/api/qt/stock/get",
        {"secid": secid, "fields": fields, "fltt": "2", "invt": "2"},
    )
    data = payload.get("data") or {}
    if not isinstance(data, dict) or not data:
        return []
    trade_date = _date_text(params.get("trade_date") or params.get("start_date") or params.get("end_date"))
    if trade_date is None and data.get("f86"):
        trade_date = _date_text(str(data.get("f86"))[:8])
    provider_market, provider_symbol = secid.split(".", 1)
    return [
        {
            **{key: data.get(key) for key in fields.split(",")},
            "symbol": _symbol_from_secid(secid),
            "secid": secid,
            "provider_symbol": provider_symbol,
            "provider_market": provider_market,
            "trade_date": trade_date,
            "event_time": _event_time(data.get("f86"), fallback_date=trade_date),
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "price": _num(data.get("f43")) or _num(data.get("f46")),
            "volume": _num(data.get("f47")),
            "amount": _num(data.get("f48")),
            "prev_close_price": _num(data.get("f60")),
            "best_bid_price": _num(data.get("f19")) or _num(data.get("f31")),
            "best_bid_volume": _num(data.get("f20")) or _num(data.get("f32")),
            "best_ask_price": _num(data.get("f39")),
            "best_ask_volume": _num(data.get("f40")),
            "provider_definition": "eastmoney_stock_get:f43,last;f19/f20,bid1;f39/f40,ask1",
        }
    ]


def _daily_bars_rows(params: dict[str, Any]) -> list[dict[str, Any]]:
    secid = _secid_from_symbol(str(params.get("secid") or params.get("symbol") or "0.000759"))
    beg = str(params.get("beg") or params.get("start_date") or params.get("trade_date") or "20260612").replace("-", "")
    end = str(params.get("end") or params.get("end_date") or params.get("trade_date") or beg).replace("-", "")
    payload = _eastmoney_json(
        "https://push2his.eastmoney.com/api/qt/stock/kline/get",
        {
            "secid": secid,
            "beg": beg,
            "end": end,
            "klt": str(params.get("klt") or "101"),
            "fqt": str(params.get("fqt") or "0"),
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        },
    )
    data = payload.get("data") or {}
    klines = data.get("klines") or []
    if not isinstance(klines, list):
        raise RuntimeError("eastmoney daily_bars returned invalid klines payload")
    symbol = _symbol_from_secid(secid)
    rows: list[dict[str, Any]] = []
    for line in klines:
        parts = str(line).split(",")
        if len(parts) < 11:
            continue
        trade_date = _date_text(parts[0])
        close_price = _num(parts[2])
        change_amount = _num(parts[9])
        pre_close: str | None = None
        if close_price is not None and change_amount is not None:
            pre_close = str(Decimal(close_price) - Decimal(change_amount))
        rows.append(
            {
                "date": trade_date,
                "trade_date": trade_date,
                "symbol": symbol,
                "secid": secid,
                "open": _num(parts[1]),
                "close": close_price,
                "high": _num(parts[3]),
                "low": _num(parts[4]),
                "volume": _num(parts[5]),
                "amount": _num(parts[6]),
                "amplitude": _num(parts[7]),
                "pct_chg": _num(parts[8]),
                "change": change_amount,
                "pre_close": pre_close,
                "turnover": _num(parts[10]),
                "adjustment_mode": str(params.get("fqt") or "0"),
            }
        )
    return rows


def _minute_bars_rows(params: dict[str, Any]) -> list[dict[str, Any]]:
    secid = _secid_from_symbol(str(params.get("secid") or params.get("symbol") or "0.000759"))
    payload = _eastmoney_json(
        "https://push2his.eastmoney.com/api/qt/stock/trends2/get",
        {
            "secid": secid,
            "fields1": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
            "ndays": str(params.get("ndays") or "1"),
            "iscr": "0",
            "iscca": "0",
        },
    )
    data = payload.get("data") or {}
    trends = data.get("trends") or []
    if not isinstance(trends, list):
        raise RuntimeError("eastmoney minute_bars returned invalid trends payload")
    symbol = _symbol_from_secid(secid)
    start_date = _date_text(params.get("start_date") or params.get("trade_date"))
    end_date = _date_text(params.get("end_date") or params.get("trade_date"))
    rows: list[dict[str, Any]] = []
    for line in trends:
        parts = str(line).split(",")
        if len(parts) < 7:
            continue
        dt_text = parts[0]
        trade_date = _date_text(dt_text[:10])
        if start_date and trade_date and trade_date < start_date:
            continue
        if end_date and trade_date and trade_date > end_date:
            continue
        bar_time = _event_time(dt_text[11:] if len(dt_text) > 11 else None, fallback_date=trade_date)
        rows.append(
            {
                "datetime": dt_text,
                "date": trade_date,
                "trade_date": trade_date,
                "symbol": symbol,
                "secid": secid,
                "bar_time": bar_time,
                "event_time": bar_time,
                "open": _num(parts[1]),
                "close": _num(parts[2]),
                "high": _num(parts[3]),
                "low": _num(parts[4]),
                "volume": _num(parts[5]),
                "amount": _num(parts[6]),
                "avg_price": _num(parts[7]) if len(parts) > 7 else None,
            }
        )
    return rows


def _trade_details_rows(params: dict[str, Any]) -> list[dict[str, Any]]:
    secid = _secid_from_symbol(str(params.get("secid") or params.get("symbol") or "0.000759"))
    payload = _eastmoney_json(
        "https://push2.eastmoney.com/api/qt/stock/details/get",
        {
            "secid": secid,
            "fields1": "f1,f2,f3,f4,f5",
            "fields2": "f51,f52,f53,f54,f55",
            "pos": str(params.get("pos") or "-0"),
            "iscca": "0",
        },
    )
    data = payload.get("data") or {}
    details = data.get("details") or []
    if not isinstance(details, list):
        raise RuntimeError("eastmoney trade_details returned invalid details payload")
    symbol = _symbol_from_secid(secid)
    trade_date = _date_text(params.get("trade_date") or params.get("start_date") or params.get("end_date"))
    rows: list[dict[str, Any]] = []
    for index, line in enumerate(details):
        parts = str(line).split(",")
        if len(parts) < 5:
            continue
        price = _num(parts[1])
        volume = _num(parts[2])
        amount: str | None = None
        if price is not None and volume is not None:
            amount = str(Decimal(price) * Decimal(volume) * Decimal("100"))
        side_code = str(parts[4])
        side_label = {"1": "buy_or_ask_taken", "2": "sell_or_bid_hit", "4": "auction_or_neutral"}.get(side_code, "provider_native_unknown")
        tick_time = _event_time(parts[0], fallback_date=trade_date)
        rows.append(
            {
                "time": parts[0],
                "date": trade_date,
                "trade_date": trade_date,
                "symbol": symbol,
                "secid": secid,
                "tick_time": tick_time,
                "price": price,
                "volume": volume,
                "amount": amount,
                "trade_count": _num(parts[3]),
                "side_code": side_code,
                "side_label": side_label,
                "provider_sequence": index,
            }
        )
    return rows


def _market_from_eastmoney_row(row: dict[str, Any]) -> str:
    value = str(row.get("f13") or row.get("MARKET") or "").strip()
    if value in {"0", "1"}:
        return value
    code = str(row.get("f12") or row.get("SECURITY_CODE") or "").strip()
    return "1" if code.startswith(("5", "6", "9")) else "0"


def _symbol_from_code_market(code: Any, market: Any = None) -> str | None:
    text = str(code or "").strip()[:6]
    if len(text) != 6:
        return None
    market_text = str(market or "").strip()
    suffix = "SH" if market_text == "1" or text.startswith(("5", "6", "9")) else "SZ"
    return f"{text}.{suffix}"


def _eastmoney_clist_rows(params: dict[str, Any]) -> list[dict[str, Any]]:
    payload = _eastmoney_json(
        "https://push2.eastmoney.com/api/qt/clist/get",
        {
            "fid": str(params.get("fid") or "f62"),
            "po": str(params.get("po") or "1"),
            "pz": str(params.get("pz") or 50),
            "pn": str(params.get("pn") or 1),
            "np": "1",
            "fltt": "2",
            "invt": "2",
            "fs": str(params.get("fs")),
            "fields": str(params.get("fields")),
        },
    )
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    diff = data.get("diff") if isinstance(data.get("diff"), list) else []
    return [row for row in diff if isinstance(row, dict)]


def _moneyflow_stock_rank_rows(params: dict[str, Any]) -> list[dict[str, Any]]:
    fs_map = {
        "all_market": "m:0+t:6,m:0+t:13,m:0+t:80,m:1+t:2,m:1+t:23",
        "szse_a": "m:0+t:6,m:0+t:13,m:0+t:80",
        "sse_a": "m:1+t:2,m:1+t:23",
        "chinext": "m:0+t:80",
    }
    rank_scope = str(params.get("rank_scope") or params.get("rank_type") or "all_market").lower()
    rows = _eastmoney_clist_rows(
        {
            **params,
            "fs": fs_map.get(rank_scope, fs_map["all_market"]),
            "fields": "f12,f13,f14,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87,f3,f6",
        }
    )
    captured_at = datetime.now(timezone.utc).isoformat()
    out: list[dict[str, Any]] = []
    for rank_no, row in enumerate(rows, start=1):
        code = str(row.get("f12") or "").strip()
        market = _market_from_eastmoney_row(row)
        out.append(
            {
                "code": code,
                "symbol": _symbol_from_code_market(code, market),
                "provider_market": market,
                "name": row.get("f14"),
                "rank_no": rank_no,
                "rank_scope": rank_scope,
                "captured_at": captured_at,
                "net_inflow": _num(row.get("f62")),
                "main_net_inflow": _num(row.get("f62")),
                "main_net_inflow_ratio": _num(row.get("f184")),
                "pct_chg": _num(row.get("f3")),
                "amount": _num(row.get("f6")),
                "super_large_net_inflow": _num(row.get("f66")),
                "large_net_inflow": _num(row.get("f72")),
                "medium_net_inflow": _num(row.get("f78")),
                "small_net_inflow": _num(row.get("f84")),
                "raw_provider_row": row,
            }
        )
    return out


def _moneyflow_board_rank_rows(params: dict[str, Any]) -> list[dict[str, Any]]:
    board_type = str(params.get("board_type") or params.get("theme_type") or "industry").lower()
    fs = "m:90+t:3" if board_type == "concept" else "m:90+t:2"
    rows = _eastmoney_clist_rows(
        {
            **params,
            "fs": fs,
            "fields": "f12,f13,f14,f62,f184,f3,f6",
        }
    )
    captured_at = datetime.now(timezone.utc).isoformat()
    out: list[dict[str, Any]] = []
    for rank_no, row in enumerate(rows, start=1):
        out.append(
            {
                "board_code": str(row.get("f12") or ""),
                "board_name": row.get("f14"),
                "board_type": board_type,
                "rank_no": rank_no,
                "captured_at": captured_at,
                "net_inflow": _num(row.get("f62")),
                "pct_chg": _num(row.get("f184")) or _num(row.get("f3")),
                "amount": _num(row.get("f6")),
                "raw_provider_row": row,
            }
        )
    return out


def _theme_membership_rows(params: dict[str, Any]) -> list[dict[str, Any]]:
    theme_code = str(params.get("theme_code") or params.get("provider_theme_code") or "BK0000")
    rows = _eastmoney_clist_rows(
        {
            **params,
            "fid": "f3",
            "fs": f"b:{theme_code}",
            "fields": "f12,f13,f14",
            "pz": int(params.get("pz") or 200),
        }
    )
    captured_at = datetime.now(timezone.utc).isoformat()
    out: list[dict[str, Any]] = []
    for rank_no, row in enumerate(rows, start=1):
        code = str(row.get("f12") or "").strip()
        market = _market_from_eastmoney_row(row)
        out.append(
            {
                "theme_code": theme_code,
                "code": code,
                "market": market,
                "symbol": _symbol_from_code_market(code, market),
                "name": row.get("f14"),
                "rank_no": rank_no,
                "captured_at": captured_at,
                "raw_provider_row": row,
            }
        )
    return out


def _stock_board_profile_rows(params: dict[str, Any]) -> list[dict[str, Any]]:
    secid = _secid_from_symbol(str(params.get("secid") or params.get("symbol") or "0.000759"))
    payload = _eastmoney_json(
        "https://push2.eastmoney.com/api/qt/stock/get",
        {"secid": secid, "fields": "f57,f58,f127,f128,f129", "fltt": "2", "invt": "2"},
    )
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    if not data:
        return []
    provider_market, provider_symbol = secid.split(".", 1)
    return [
        {
            "symbol": _symbol_from_secid(secid),
            "provider_symbol": provider_symbol,
            "provider_market": provider_market,
            "f127": data.get("f127"),
            "f128": data.get("f128"),
            "f129": data.get("f129"),
            "industry_name": data.get("f127"),
            "region_name": data.get("f128"),
            "concept_names": data.get("f129"),
            "raw_provider_row": data,
        }
    ]


def _stock_universe_rows(params: dict[str, Any]) -> list[dict[str, Any]]:
    segment_param = params.get("segment_name") or params.get("segment")
    if segment_param:
        segment_names = [str(segment_param)]
    else:
        segment_names = list(EASTMONEY_UNIVERSE_SEGMENTS)
    page_size = int(params.get("pageSize") or params.get("page_size") or params.get("pz") or 200)
    start_page = int(params.get("pageNumber") or params.get("page") or params.get("pn") or 1)
    max_pages = int(params.get("max_pages_per_segment") or 1)
    trade_date = _date_text(params.get("trade_date") or datetime.now(timezone(timedelta(hours=8))).date().isoformat())
    captured_at = datetime.now(timezone.utc).isoformat()
    out: list[dict[str, Any]] = []
    for segment_name in segment_names:
        segment = EASTMONEY_UNIVERSE_SEGMENTS.get(segment_name)
        if segment is None:
            raise KeyError(f"unsupported eastmoney stock_universe segment: {segment_name}")
        for offset in range(max_pages):
            rows = _eastmoney_clist_rows(
                {
                    **params,
                    "fid": "f12",
                    "po": "1",
                    "pz": page_size,
                    "pn": start_page + offset,
                    "fs": segment["fs"],
                    "fields": "f12,f13,f14,f26",
                }
            )
            if not rows:
                break
            for rank_no, row in enumerate(rows, start=1):
                code = str(row.get("f12") or "").strip()
                market = _market_from_eastmoney_row(row)
                if len(code) != 6:
                    continue
                out.append(
                    {
                        "symbol": _symbol_from_code_market(code, market),
                        "code": code,
                        "name": row.get("f14"),
                        "stock_name": row.get("f14"),
                        "secid": f"{market}.{code}",
                        "provider_symbol": code,
                        "provider_market": market,
                        "exchange": segment["exchange"],
                        "board": segment["board"],
                        "segment_name": segment_name,
                        "trade_date": trade_date,
                        "list_date": _date_text(row.get("f26")),
                        "ipo_date": _date_text(row.get("f26")),
                        "list_status": "L",
                        "delist_date": None,
                        "rank_no": rank_no + offset * page_size,
                        "captured_at": captured_at,
                        "provider_definition": "eastmoney_clist_stock_universe:f12=code,f13=market,f14=name,f26=list_date",
                        "raw_provider_row": row,
                    }
                )
    return out


def _billboard_trade_rows(params: dict[str, Any]) -> list[dict[str, Any]]:
    trade_date = _date_text(params.get("trade_date") or params.get("date"))
    query: dict[str, Any] = {
        "sortColumns": "TRADE_DATE,SECURITY_CODE",
        "sortTypes": "-1,1",
        "pageSize": int(params.get("pz") or params.get("page_size") or 100),
        "pageNumber": int(params.get("pn") or params.get("page") or 1),
        "reportName": "RPT_DAILYBILLBOARD_DETAILSNEW",
        "columns": "ALL",
        "source": "WEB",
        "client": "WEB",
    }
    if trade_date:
        query["filter"] = f"(TRADE_DATE='{trade_date}')"
    payload = _eastmoney_json("https://datacenter-web.eastmoney.com/api/data/v1/get", query)
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    rows = result.get("data") if isinstance(result.get("data"), list) else []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = str(row.get("SECURITY_CODE") or "").strip()
        row_trade_date = _date_text(row.get("TRADE_DATE")) or trade_date
        market = _market_from_eastmoney_row(row)
        out.append(
            {
                "SECURITY_CODE": code,
                "TRADE_DATE": row_trade_date,
                "BILLBOARD_NET_AMT": _num(row.get("BILLBOARD_NET_AMT") or row.get("NET_BS_AMT")),
                "EXPLAIN": row.get("EXPLAIN"),
                "symbol": _symbol_from_code_market(code, market),
                "trade_date": row_trade_date,
                "net_amount": _num(row.get("BILLBOARD_NET_AMT") or row.get("NET_BS_AMT")),
                "reason_text": row.get("EXPLAIN"),
                "raw_provider_row": row,
            }
        )
    return out


def _eastmoney_datacenter_rows(params: dict[str, Any]) -> list[dict[str, Any]]:
    query = {
        "sortColumns": str(params.get("sortColumns") or params.get("sort_columns") or ""),
        "sortTypes": str(params.get("sortTypes") or params.get("sort_types") or "-1"),
        "pageSize": int(params.get("pageSize") or params.get("page_size") or params.get("pz") or 20),
        "pageNumber": int(params.get("pageNumber") or params.get("page") or params.get("pn") or 1),
        "reportName": str(params.get("reportName") or params.get("report_name")),
        "columns": str(params.get("columns") or "ALL"),
        "source": "WEB",
        "client": "WEB",
    }
    if params.get("filter"):
        query["filter"] = str(params["filter"])
    payload = _eastmoney_json("https://datacenter-web.eastmoney.com/api/data/v1/get", query)
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    rows = result.get("data") if isinstance(result.get("data"), list) else []
    return [row for row in rows if isinstance(row, dict)]


def _northbound_summary_rows(params: dict[str, Any]) -> list[dict[str, Any]]:
    rows = _eastmoney_datacenter_rows(
        {
            **params,
            "reportName": params.get("reportName") or "RPT_MUTUAL_DEAL_HISTORY",
            "sortColumns": params.get("sortColumns") or "TRADE_DATE",
            "sortTypes": params.get("sortTypes") or "-1",
            "pageSize": params.get("pageSize") or params.get("page_size") or 20,
        }
    )
    out: list[dict[str, Any]] = []
    for row in rows:
        trade_date = _date_text(row.get("TRADE_DATE") or row.get("HOLD_DATE") or row.get("TRADE_DATE_STR"))
        out.append(
            {
                "trade_date": trade_date,
                "mutual_type": row.get("MUTUAL_TYPE") or row.get("MARKET_TYPE"),
                "deal_amount": _num(row.get("DEAL_AMT") or row.get("ACCUM_DEAL_AMT") or row.get("BUY_AMT") or row.get("NET_BUY_AMT")),
                "net_buy_amount": _num(row.get("NET_BUY_AMT") or row.get("NET_BUY_AMOUNT") or row.get("NET_DEAL_AMT")),
                "buy_amount": _num(row.get("BUY_AMT")),
                "sell_amount": _num(row.get("SELL_AMT")),
                "quota_balance_text": row.get("QUOTA_BALANCE") or row.get("QUOTA_BALANCE_TEXT"),
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "raw_provider_row": row,
            }
        )
    return out


def _lpr_rate_rows(params: dict[str, Any]) -> list[dict[str, Any]]:
    rows = _eastmoney_datacenter_rows(
        {
            **params,
            "reportName": params.get("reportName") or "RPTA_WEB_RATE",
            "sortColumns": params.get("sortColumns") or "TRADE_DATE",
            "sortTypes": params.get("sortTypes") or "-1",
            "pageSize": params.get("pageSize") or params.get("page_size") or 20,
        }
    )
    out: list[dict[str, Any]] = []
    for row in rows:
        trade_date = _date_text(row.get("TRADE_DATE") or row.get("REPORT_DATE") or row.get("DATE"))
        rate_1y = _num(row.get("LPR1Y") or row.get("RATE_1") or row.get("RATE1"))
        rate_5y = _num(row.get("LPR5Y") or row.get("RATE_2") or row.get("RATE2"))
        if rate_1y is not None:
            out.append(
                {
                    "asset_code": "LPR_1Y",
                    "asset_name": "China LPR 1Y",
                    "trade_date": trade_date,
                    "last_price": rate_1y,
                    "rate_1y": rate_1y,
                    "rate_5y": rate_5y,
                    "extra_metrics_json": {"rate_1": rate_1y, "rate_2": rate_5y},
                    "captured_at": datetime.now(timezone.utc).isoformat(),
                    "raw_provider_row": row,
                }
            )
        if rate_5y is not None:
            out.append(
                {
                    "asset_code": "LPR_5Y",
                    "asset_name": "China LPR 5Y",
                    "trade_date": trade_date,
                    "last_price": rate_5y,
                    "rate_1y": rate_1y,
                    "rate_5y": rate_5y,
                    "extra_metrics_json": {"rate_1": rate_1y, "rate_2": rate_5y},
                    "captured_at": datetime.now(timezone.utc).isoformat(),
                    "raw_provider_row": row,
                }
            )
    return out


class EastMoneyAdapter(ProviderAdapter):
    provider = Provider.EASTMONEY

    def fetch(self, api_name: str, params: dict[str, Any], *, dry_run: bool = False) -> RawFetchResult:
        if dry_run:
            return self.build_result(api_name, params, [], dry_run=True, warning="dry_run: provider not called")
        if api_name == "stock_universe":
            return self.build_result(api_name, params, _stock_universe_rows(params))
        if api_name == "quote_snapshot":
            return self.build_result(api_name, params, _quote_snapshot_rows(params))
        if api_name == "auction_snapshot":
            return self.build_result(api_name, params, _auction_snapshot_rows(params))
        if api_name == "daily_bars":
            return self.build_result(api_name, params, _daily_bars_rows(params))
        if api_name == "minute_bars":
            return self.build_result(api_name, params, _minute_bars_rows(params))
        if api_name == "trade_details":
            return self.build_result(api_name, params, _trade_details_rows(params))
        if api_name == "moneyflow_stock_series":
            return self.build_result(api_name, params, _moneyflow_stock_series_rows(params))
        if api_name == "moneyflow_stock_rank":
            return self.build_result(api_name, params, _moneyflow_stock_rank_rows(params))
        if api_name == "moneyflow_board_rank":
            return self.build_result(api_name, params, _moneyflow_board_rank_rows(params))
        if api_name == "stock_board_profile":
            return self.build_result(api_name, params, _stock_board_profile_rows(params))
        if api_name == "theme_memberships":
            return self.build_result(api_name, params, _theme_membership_rows(params))
        if api_name == "billboard_trades":
            return self.build_result(api_name, params, _billboard_trade_rows(params))
        if api_name == "northbound_summary":
            return self.build_result(api_name, params, _northbound_summary_rows(params))
        if api_name == "lpr_rates":
            return self.build_result(api_name, params, _lpr_rate_rows(params))
        raise KeyError(f"unsupported eastmoney api: {api_name}")
