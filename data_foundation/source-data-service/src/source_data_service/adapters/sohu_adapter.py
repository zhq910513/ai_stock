from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from source_data_service.adapters.base import ProviderAdapter
from source_data_service.models import Provider, RawFetchResult


SOHU_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
    "Referer": "https://q.stock.sohu.com/",
}


def _provider_code(value: str) -> str:
    text = str(value or "").strip()
    if text.startswith("cn_") and len(text) >= 9:
        return f"cn_{text[3:9]}"
    code = text.split(".")[0].removeprefix("sz").removeprefix("sh").removeprefix("SZ").removeprefix("SH")
    return f"cn_{code[:6]}"


def _canonical_symbol(provider_code: str) -> str:
    code = provider_code.removeprefix("cn_")[:6]
    if code.startswith(("5", "6", "9")):
        return f"{code}.SH"
    return f"{code}.SZ"


def _date_compact(value: Any) -> str:
    text = str(value or "").strip()
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        return text.replace("-", "")
    return text


def _clean_percent(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value).replace("%", "").strip()


def _decimal_text(value: Any, multiplier: Decimal | None = None) -> str | None:
    if value in (None, ""):
        return None
    try:
        parsed = Decimal(str(value).replace(",", "").replace("%", "").strip())
    except (InvalidOperation, ValueError):
        return None
    if multiplier is not None:
        parsed *= multiplier
    return format(parsed.normalize(), "f")


def _parse_jsonp(text: str) -> list[dict[str, Any]]:
    stripped = text.strip()
    match = re.match(r"^[^(]+\((.*)\)\s*;?$", stripped, flags=re.S)
    payload_text = match.group(1) if match else stripped
    payload = json.loads(payload_text)
    if not isinstance(payload, list):
        raise RuntimeError("sohu daily bars returned non-list jsonp payload")
    return [item for item in payload if isinstance(item, dict)]


def _request_daily_payload(params: dict[str, Any]) -> list[dict[str, Any]]:
    import requests

    provider_code = _provider_code(params.get("provider_code") or params.get("symbol") or "000063.SZ")
    start = _date_compact(params.get("start") or params.get("start_date") or params.get("trade_date") or "")
    end = _date_compact(params.get("end") or params.get("end_date") or params.get("trade_date") or start)
    query = {
        "code": provider_code,
        "start": start,
        "end": end,
        "stat": str(params.get("stat") or 1),
        "order": str(params.get("order") or "D"),
        "period": str(params.get("period") or "d"),
        "callback": str(params.get("callback") or "historySearchHandler"),
        "rt": str(params.get("rt") or "jsonp"),
    }
    response = requests.get("https://q.stock.sohu.com/hisHq", params=query, headers=SOHU_HEADERS, timeout=15)
    response.raise_for_status()
    return _parse_jsonp(response.text)


def _sohu_daily_rows(params: dict[str, Any]) -> list[dict[str, Any]]:
    payload = _request_daily_payload(params)
    rows: list[dict[str, Any]] = []
    for item in payload:
        provider_code = str(item.get("code") or _provider_code(params.get("provider_code") or params.get("symbol") or ""))
        symbol = _canonical_symbol(provider_code)
        status = item.get("status")
        if status not in (0, "0", None):
            continue
        for hq in item.get("hq") or []:
            if not isinstance(hq, list) or len(hq) < 9:
                continue
            rows.append(
                {
                    "date": hq[0],
                    "code": provider_code.removeprefix("cn_")[:6],
                    "provider_code": provider_code,
                    "symbol": symbol,
                    "open": hq[1],
                    "close": hq[2],
                    "change": hq[3] if len(hq) > 3 else None,
                    "pct_chg": _clean_percent(hq[4] if len(hq) > 4 else None),
                    "low": hq[5] if len(hq) > 5 else None,
                    "high": hq[6] if len(hq) > 6 else None,
                    "volume": _decimal_text(hq[7] if len(hq) > 7 else None, Decimal("100")),
                    "amount": _decimal_text(hq[8] if len(hq) > 8 else None, Decimal("10000")),
                    "turnover_rate": _clean_percent(hq[9] if len(hq) > 9 else None),
                    "adjustment_mode": "raw",
                    "period": "day",
                    "provider_definition": "sohu.hisHq:date,open,close,change,pct_chg,low,high,volume_hands,amount_wan_yuan,turnover_rate",
                }
            )
    return rows


class SohuAdapter(ProviderAdapter):
    provider = Provider.SOHU

    def fetch(self, api_name: str, params: dict[str, Any], *, dry_run: bool = False) -> RawFetchResult:
        if dry_run:
            return self.build_result(api_name, params, [], dry_run=True, warning="dry_run: provider not called")
        if api_name == "daily_bars":
            return self.build_result(api_name, params, _sohu_daily_rows(params))
        raise KeyError(f"unsupported sohu api: {api_name}")

