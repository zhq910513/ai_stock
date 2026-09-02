from __future__ import annotations

from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
import re
from typing import Any

from source_data_service.adapters.base import ProviderAdapter
from source_data_service.models import Provider, RawFetchResult


TENCENT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
    "Referer": "https://gu.qq.com/",
}
ASIA_SHANGHAI = timezone(timedelta(hours=8))


def _provider_code(value: str) -> str:
    text = str(value).strip()
    lowered = text.lower()
    if lowered.startswith(("sz", "sh")) and len(lowered) == 8:
        return lowered
    code = text.split(".")[0]
    suffix = text.split(".")[1].upper() if "." in text else ""
    if suffix == "SH" or code.startswith(("5", "6", "9")):
        return f"sh{code[:6]}"
    return f"sz{code[:6]}"


def _canonical_symbol(provider_code: str) -> str:
    text = provider_code.lower()
    code = text[2:8] if text.startswith(("sz", "sh")) else text[:6]
    if text.startswith("sh") or code.startswith(("5", "6", "9")):
        return f"{code}.SH"
    return f"{code}.SZ"


def _request_json(url: str, params: dict[str, str]) -> dict[str, Any]:
    import requests

    last_error: Exception | None = None
    endpoints = (
        url,
        url.replace("https://web.ifzq.gtimg.cn/", "https://proxy.finance.qq.com/ifzqgtimg/"),
    )
    for endpoint in endpoints:
        for attempt in range(3):
            try:
                response = requests.get(endpoint, params=params, headers=TENCENT_HEADERS, timeout=15)
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise RuntimeError("tencent daily bars returned non-object json")
                return payload
            except Exception as exc:  # noqa: BLE001 - provider instability is returned as structured probe evidence
                last_error = exc
                if attempt < 2:
                    import time

                    time.sleep(0.8 + attempt)
    raise RuntimeError(f"tencent daily bars request failed: {last_error}") from last_error


def _request_text(url: str, params: dict[str, str]) -> str:
    import requests

    response = requests.get(url, params=params, headers=TENCENT_HEADERS, timeout=10)
    response.raise_for_status()
    return response.content.decode(response.encoding or "gb18030", errors="replace")


def _date_text(value: Any) -> str:
    text = str(value or "")
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return text


def _event_time(value: Any, *, fallback_date: str | None = None) -> str | None:
    text = str(value or "").strip()
    if len(text) == 14 and text.isdigit():
        try:
            return datetime.strptime(text, "%Y%m%d%H%M%S").replace(tzinfo=ASIA_SHANGHAI).isoformat()
        except ValueError:
            return None
    if len(text) == 12 and text.isdigit():
        try:
            return datetime.strptime(text, "%Y%m%d%H%M").replace(tzinfo=ASIA_SHANGHAI).isoformat()
        except ValueError:
            return None
    if fallback_date and len(text) == 4 and text.isdigit():
        return f"{fallback_date}T{text[:2]}:{text[2:4]}:00+08:00"
    return None


def _extract_amount_from_quote(qt: list[Any], trade_date: str) -> str | None:
    if not qt:
        return None
    quote_time = str(qt[30]) if len(qt) > 30 else ""
    if quote_time and quote_time[:8] != trade_date.replace("-", ""):
        return None
    composite = str(qt[35]) if len(qt) > 35 else ""
    parts = composite.split("/")
    if len(parts) >= 3 and parts[2]:
        return parts[2]
    if len(qt) > 57 and qt[57] not in (None, ""):
        try:
            return str(float(qt[57]) * 10000)
        except Exception:
            return None
    return None


def _volume_from_hands(value: Any) -> str | None:
    parsed = _num_text(value, zero_is_none=True)
    if parsed is None:
        return None
    return str(Decimal(parsed) * Decimal("100"))


def _num_text(value: Any, *, zero_is_none: bool = False) -> str | None:
    if value in (None, "", "-", "--"):
        return None
    try:
        parsed = Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return None
    if zero_is_none and parsed == 0:
        return None
    return str(parsed)


def _quote_time(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y%m%d%H%M%S").replace(tzinfo=ASIA_SHANGHAI).isoformat()
    except ValueError:
        return None


def _amount_from_tencent_fields(fields: list[str]) -> str | None:
    if len(fields) > 35 and fields[35]:
        pieces = fields[35].split("/")
        if len(pieces) >= 3:
            parsed = _num_text(pieces[2], zero_is_none=True)
            if parsed is not None:
                return parsed
    if len(fields) > 57:
        parsed = _num_text(fields[57], zero_is_none=True)
        if parsed is not None:
            return str(Decimal(parsed) * Decimal("10000"))
    return None


def _quote_fields(provider_code: str) -> tuple[str, list[str]]:
    text = _request_text(f"https://qt.gtimg.cn/q={provider_code}", {})
    match = re.search(rf'v_{re.escape(provider_code)}="([^"]*)"', text)
    if not match:
        raise RuntimeError(f"tencent quote payload missing quote variable for {provider_code}")
    fields = match.group(1).split("~")
    if len(fields) < 38:
        raise RuntimeError(f"tencent quote payload field count too small: {len(fields)}")
    return text, fields


def _tencent_quote_rows(params: dict[str, Any]) -> list[dict[str, Any]]:
    code = _provider_code(params.get("provider_code") or params.get("symbol") or "sz000759")
    text, fields = _quote_fields(code)
    trade_date = _date_text(fields[30][:8]) if len(fields) > 30 and fields[30] else _date_text(params.get("trade_date") or "")
    return [
        {
            "provider_code": code,
            "symbol": _canonical_symbol(code),
            "name": fields[1] if len(fields) > 1 else None,
            "trade_date": trade_date,
            "event_time": _event_time(fields[30]) if len(fields) > 30 else None,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "last_price": _num_text(fields[3], zero_is_none=True),
            "prev_close_price": _num_text(fields[4], zero_is_none=True),
            "open_price": _num_text(fields[5], zero_is_none=True),
            "high_price": _num_text(fields[33], zero_is_none=True) if len(fields) > 33 else None,
            "low_price": _num_text(fields[34], zero_is_none=True) if len(fields) > 34 else None,
            "volume": _volume_from_hands(fields[36]) if len(fields) > 36 else _volume_from_hands(fields[6] if len(fields) > 6 else None),
            "amount": _amount_from_tencent_fields(fields),
            "turnover_rate": _num_text(fields[38], zero_is_none=True) if len(fields) > 38 else None,
            "change_amount": _num_text(fields[31], zero_is_none=True) if len(fields) > 31 else None,
            "change_pct": _num_text(fields[32], zero_is_none=True) if len(fields) > 32 else None,
            "response_field_count": len(fields),
            "raw_text": text,
        }
    ]


def _tencent_daily_rows(params: dict[str, Any]) -> list[dict[str, Any]]:
    code = _provider_code(params.get("provider_code") or params.get("symbol") or "sz000063")
    period = str(params.get("period") or "day")
    start_date = _date_text(params.get("start_date") or "")
    end_date = _date_text(params.get("end_date") or "")
    count = str(params.get("count") or params.get("lmt") or 10)
    adjustment = str(params.get("adjustment") or params.get("adjust") or "").lower()
    use_adjusted_endpoint = adjustment in {"qfq", "hfq"}
    endpoint = (
        "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
        if use_adjusted_endpoint
        else "https://web.ifzq.gtimg.cn/appstock/app/kline/kline"
    )
    param = f"{code},{period},{start_date},{end_date},{count}"
    if use_adjusted_endpoint:
        param = f"{param},{adjustment}"
    payload = _request_json(endpoint, {"param": param})
    if payload.get("code") != 0:
        raise RuntimeError(f"tencent daily bars returned code={payload.get('code')} msg={payload.get('msg')}")
    node = (payload.get("data") or {}).get(code) or {}
    key_candidates = (
        f"{adjustment}{period}",
        f"{adjustment}day",
        period,
        "day",
    )
    lines: list[Any] = []
    for key in key_candidates:
        candidate = node.get(key)
        if isinstance(candidate, list):
            lines = candidate
            break
    qt = node.get("qt", {}).get(code, []) if isinstance(node.get("qt"), dict) else []
    symbol = _canonical_symbol(code)
    rows: list[dict[str, Any]] = []
    for item in lines:
        if not isinstance(item, list) or len(item) < 6:
            continue
        trade_date = _date_text(item[0])
        rows.append(
            {
                "date": trade_date,
                "code": code[2:8],
                "provider_code": code,
                "symbol": symbol,
                "open": item[1],
                "close": item[2],
                "high": item[3],
                "low": item[4],
                "volume": item[5],
                "amount": None,
                "adjustment_mode": adjustment or "raw",
                "period": period,
                "pct_chg": None,
            }
        )
    return rows


def _tencent_minute_rows(params: dict[str, Any]) -> list[dict[str, Any]]:
    code = _provider_code(params.get("provider_code") or params.get("symbol") or "sz000759")
    requested_trade_date = _date_text(params.get("trade_date") or params.get("start_date") or "")
    period = str(params.get("period") or params.get("klt") or "m1").lower()
    if period in {"1", "1m", "minute"}:
        period = "m1"
    if not period.startswith("m"):
        period = "m1"
    try:
        count = max(1, min(500, int(params.get("count") or params.get("lmt") or params.get("limit") or 320)))
    except (TypeError, ValueError):
        count = 320
    payload = _request_json(
        "https://ifzq.gtimg.cn/appstock/app/kline/mkline",
        {"param": f"{code},{period},,{count}"},
    )
    if payload.get("code") != 0:
        raise RuntimeError(f"tencent minute bars returned code={payload.get('code')} msg={payload.get('msg')}")
    node = (payload.get("data") or {}).get(code) or {}
    lines = (node.get(period) or node.get("m1") or []) if isinstance(node, dict) else []
    if not isinstance(lines, list):
        raise RuntimeError("tencent minute bars returned invalid data payload")
    rows: list[dict[str, Any]] = []
    for item in lines:
        if not isinstance(item, list) or len(item) < 6:
            continue
        minute_time = str(item[0])
        trade_date = _date_text(minute_time[:8])
        if requested_trade_date and trade_date != requested_trade_date:
            continue
        bar_time = _event_time(minute_time)
        rows.append(
            {
                "datetime": f"{trade_date} {minute_time[8:10]}:{minute_time[10:12]}:00" if trade_date and len(minute_time) == 12 else None,
                "date": trade_date,
                "trade_date": trade_date,
                "symbol": _canonical_symbol(code),
                "provider_code": code,
                "bar_time": bar_time,
                "event_time": bar_time,
                "open": _num_text(item[1]),
                "close": _num_text(item[2]),
                "high": _num_text(item[3]),
                "low": _num_text(item[4]),
                "volume": _num_text(item[5]),
                "amount": None,
                "provider_native_amount": _num_text(item[7]) if len(item) > 7 else None,
                "provider_definition": "tencent_mkline:m1 tuple datetime/open/close/high/low/volume/provider_native_amount; amount kept NULL until unit normalization",
            }
        )
    return rows


def _tencent_auction_rows(params: dict[str, Any]) -> list[dict[str, Any]]:
    code = _provider_code(params.get("provider_code") or params.get("symbol") or "sz000759")
    text = _request_text(f"https://qt.gtimg.cn/q={code}", {})
    match = re.search(rf'v_{re.escape(code)}="([^"]*)"', text)
    if not match:
        raise RuntimeError(f"tencent auction payload missing quote variable for {code}")
    fields = match.group(1).split("~")
    if len(fields) < 31:
        raise RuntimeError(f"tencent auction payload field count too small: {len(fields)}")
    event_time = _quote_time(fields[30])
    matched_volume = _num_text(fields[6], zero_is_none=True)
    if matched_volume is not None:
        matched_volume = str(Decimal(matched_volume) * Decimal("100"))
    bid_volume = _num_text(fields[10], zero_is_none=True)
    if bid_volume is not None:
        bid_volume = str(Decimal(bid_volume) * Decimal("100"))
    ask_volume = _num_text(fields[20], zero_is_none=True)
    if ask_volume is not None:
        ask_volume = str(Decimal(ask_volume) * Decimal("100"))
    return [
        {
            "provider_code": code,
            "symbol": _canonical_symbol(code),
            "name": fields[1] if len(fields) > 1 else None,
            "trade_date": fields[30][:8] if len(fields) > 30 and fields[30] else None,
            "event_time": event_time,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "price": _num_text(fields[3], zero_is_none=True) or _num_text(fields[5], zero_is_none=True),
            "volume": matched_volume,
            "amount": _amount_from_tencent_fields(fields),
            "best_bid_price": _num_text(fields[9], zero_is_none=True),
            "best_bid_volume": bid_volume,
            "best_ask_price": _num_text(fields[19], zero_is_none=True),
            "best_ask_volume": ask_volume,
            "response_field_count": len(fields),
            "raw_text": text,
        }
    ]


class TencentAdapter(ProviderAdapter):
    provider = Provider.TENCENT

    def fetch(self, api_name: str, params: dict[str, Any], *, dry_run: bool = False) -> RawFetchResult:
        if dry_run:
            return self.build_result(api_name, params, [], dry_run=True, warning="dry_run: provider not called")
        if api_name == "daily_bars":
            return self.build_result(api_name, params, _tencent_daily_rows(params))
        if api_name == "quote_snapshot":
            return self.build_result(api_name, params, _tencent_quote_rows(params))
        if api_name == "minute_bars":
            return self.build_result(api_name, params, _tencent_minute_rows(params))
        if api_name == "auction_snapshot":
            return self.build_result(api_name, params, _tencent_auction_rows(params))
        raise KeyError(f"unsupported tencent api: {api_name}")
