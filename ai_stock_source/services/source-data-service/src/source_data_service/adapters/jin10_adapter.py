from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone, timedelta
from typing import Any

from source_data_service.adapters.base import ProviderAdapter
from source_data_service.models import Provider, RawFetchResult


JIN10_FLASH_ENDPOINT = "https://flash-api.jin10.com/get_flash_list"
JIN10_HEADERS = {
    "User-Agent": "ai-stock-source-data-service/1.0",
    "x-app-id": "bVBF4FyRTn5NJF5n",
    "x-version": "1.0.0",
}
ASIA_SHANGHAI = timezone(timedelta(hours=8))
ASHARE_RE = re.compile(r"(?<!\d)([034689]\d{5})(?!\d)")


def _json(params: dict[str, Any]) -> dict[str, Any]:
    import requests

    response = requests.get(JIN10_FLASH_ENDPOINT, params=params, headers=JIN10_HEADERS, timeout=15)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("jin10 public flash returned non-object json")
    return payload


def _parse_time(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt).replace(tzinfo=ASIA_SHANGHAI).astimezone(timezone.utc).isoformat()
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=ASIA_SHANGHAI)
        return parsed.astimezone(timezone.utc).isoformat()
    except ValueError:
        return None


def _fallback_id(published_at: str | None, title: str) -> str:
    digest = hashlib.sha1(f"{published_at or ''}|{title}".encode("utf-8")).hexdigest()[:24]
    return f"jin10:{digest}"


def _symbol(code: str) -> str | None:
    if code.startswith("6"):
        return f"{code}.SH"
    if code.startswith(("0", "3")):
        return f"{code}.SZ"
    if code.startswith(("4", "8", "9")):
        return f"{code}.BJ"
    return None


def _stock_refs(text: str) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    seen: set[str] = set()
    for match in ASHARE_RE.finditer(text):
        code = match.group(1)
        symbol = _symbol(code)
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        refs.append({"symbol": symbol, "provider_symbol": code, "exchange": symbol.split(".", 1)[1], "provider_market": "ab"})
    return refs


def _flash_rows(params: dict[str, Any]) -> list[dict[str, Any]]:
    request_params = {"channel": str(params.get("channel") or "-8200"), "vip": int(params.get("vip") or 0)}
    payload = _json(request_params)
    data = payload.get("data") if isinstance(payload.get("data"), list) else []
    available_at = datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in data:
        if not isinstance(row, dict):
            continue
        item = row.get("data") if isinstance(row.get("data"), dict) else {}
        content = str(item.get("content") or "").strip()
        title = str(item.get("title") or "").strip() or content
        if not title:
            continue
        published_at = _parse_time(row.get("time"))
        provider_news_id = str(row.get("id") or "").strip() or _fallback_id(published_at, title)
        if provider_news_id in seen:
            continue
        seen.add(provider_news_id)
        refs = _stock_refs(f"{title} {content}")
        rows.append(
            {
                "provider_news_id": provider_news_id,
                "title": title,
                "body": content or None,
                "source_name": str(item.get("source") or "JIN10"),
                "published_at": published_at,
                "available_at": available_at,
                "event_type": "jin10_flash",
                "url": str(item.get("source_link") or "") or None,
                "symbol": refs[0]["symbol"] if refs else None,
                "tags_json": {
                    "type": row.get("type"),
                    "important": row.get("important"),
                    "tags": row.get("tags") if isinstance(row.get("tags"), list) else [],
                    "channel": row.get("channel") if isinstance(row.get("channel"), list) else [],
                    "provider_business_status": payload.get("status"),
                    "provider_message": payload.get("message"),
                },
                "stock_refs_json": refs,
                "raw_provider_row": row,
            }
        )
    return rows


class Jin10Adapter(ProviderAdapter):
    provider = Provider.JIN10

    def fetch(self, api_name: str, params: dict[str, Any], *, dry_run: bool = False) -> RawFetchResult:
        if dry_run:
            return self.build_result(api_name, params, [], dry_run=True, warning="dry_run: provider not called")
        if api_name == "public_flash":
            return self.build_result(api_name, params, _flash_rows(params))
        raise KeyError(f"unsupported jin10 api: {api_name}")
