from __future__ import annotations

import re
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from source_data_service.adapters.base import ProviderAdapter
from source_data_service.models import Provider, RawFetchResult


SINA_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
    "Referer": "https://finance.sina.com.cn/",
    "Accept": "*/*",
}
SINA_AUCTION_ENDPOINT = "https://hq.sinajs.cn/list="
ASIA_SHANGHAI = timezone(timedelta(hours=8))


def _provider_code(value: Any) -> str:
    text = str(value or "").strip()
    lowered = text.lower()
    if lowered.startswith(("sz", "sh")) and len(lowered) >= 8:
        return lowered[:8]
    code = text.split(".")[0].removeprefix("SZ").removeprefix("SH").removeprefix("sz").removeprefix("sh")[:6]
    if code.startswith(("5", "6", "9")):
        return f"sh{code}"
    return f"sz{code}"


def _symbol(provider_code: str) -> str:
    code = provider_code[2:8] if provider_code.startswith(("sz", "sh")) else provider_code[:6]
    if provider_code.startswith("sh") or code.startswith(("5", "6", "9")):
        return f"{code}.SH"
    return f"{code}.SZ"


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


def _quote_time(date_part: str | None, time_part: str | None) -> str | None:
    if not date_part or not time_part:
        return None
    try:
        return datetime.strptime(f"{date_part} {time_part}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=ASIA_SHANGHAI).isoformat()
    except ValueError:
        return None


def _request_text(provider_code: str) -> str:
    import requests

    response = requests.get(f"{SINA_AUCTION_ENDPOINT}{provider_code}", headers=SINA_HEADERS, timeout=10)
    response.raise_for_status()
    if response.encoding:
        return response.text
    return response.content.decode("gb18030", errors="replace")


def _auction_rows(params: dict[str, Any]) -> list[dict[str, Any]]:
    provider_code = _provider_code(params.get("provider_code") or params.get("symbol") or "sz000759")
    text = _request_text(provider_code)
    match = re.search(rf'var hq_str_{re.escape(provider_code)}="([^"]*)"', text)
    if not match:
        raise RuntimeError(f"sina auction payload missing quote variable for {provider_code}")
    fields = match.group(1).split(",")
    if len(fields) < 32:
        raise RuntimeError(f"sina auction payload field count too small: {len(fields)}")
    event_time = _quote_time(fields[30], fields[31])
    return [
        {
            "provider_code": provider_code,
            "symbol": _symbol(provider_code),
            "name": fields[0],
            "trade_date": fields[30] or None,
            "event_time": event_time,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "price": _num_text(fields[3], zero_is_none=True) or _num_text(fields[1], zero_is_none=True),
            "volume": _num_text(fields[8], zero_is_none=True),
            "amount": _num_text(fields[9], zero_is_none=True),
            "best_bid_price": _num_text(fields[11], zero_is_none=True),
            "best_bid_volume": _num_text(fields[10], zero_is_none=True),
            "best_ask_price": _num_text(fields[21], zero_is_none=True),
            "best_ask_volume": _num_text(fields[20], zero_is_none=True),
            "response_field_count": len(fields),
            "raw_text": text,
        }
    ]


class SinaAdapter(ProviderAdapter):
    provider = Provider.SINA

    def fetch(self, api_name: str, params: dict[str, Any], *, dry_run: bool = False) -> RawFetchResult:
        if dry_run:
            return self.build_result(api_name, params, [], dry_run=True, warning="dry_run: provider not called")
        if api_name == "auction_snapshot":
            return self.build_result(api_name, params, _auction_rows(params))
        raise KeyError(f"unsupported sina api: {api_name}")
