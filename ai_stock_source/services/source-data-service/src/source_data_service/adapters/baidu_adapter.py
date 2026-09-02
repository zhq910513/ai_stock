from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from source_data_service.adapters.base import ProviderAdapter
from source_data_service.models import Provider, RawFetchResult


BAIDU_FINANCE_NEWS_ENDPOINT = "https://finance.pae.baidu.com/selfselect/news"
BAIDU_FINANCE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
    "Referer": "https://finance.baidu.com/",
    "Accept": "application/json,text/plain,*/*",
}
ASIA_SHANGHAI = ZoneInfo("Asia/Shanghai")


def _published_at_from_epoch(value: Any) -> str | None:
    if value in (None, "", "-", "--"):
        return None
    try:
        return datetime.fromtimestamp(int(str(value)), tz=ASIA_SHANGHAI).astimezone(timezone.utc).isoformat()
    except Exception:
        return None


def _canonical_a_share_symbol(code: str) -> str | None:
    text = str(code).strip()
    if len(text) != 6 or not text.isdigit():
        return None
    if text.startswith("6"):
        return f"{text}.SH"
    if text.startswith(("0", "3")):
        return f"{text}.SZ"
    if text.startswith(("4", "8", "9")):
        return f"{text}.BJ"
    return None


def _stock_refs(tags: list[Any]) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw_tag in tags:
        symbol = _canonical_a_share_symbol(str(raw_tag))
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        refs.append(
            {
                "symbol": symbol,
                "provider_symbol": symbol[:6],
                "exchange": symbol.split(".", 1)[1],
                "provider_market": "ab",
            }
        )
    return refs


def _request_json(params: dict[str, Any]) -> dict[str, Any]:
    import requests

    response = requests.get(BAIDU_FINANCE_NEWS_ENDPOINT, params=params, headers=BAIDU_FINANCE_HEADERS, timeout=15)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("baidu finance news feed returned non-object json")
    return payload


def _finance_news_rows(params: dict[str, Any]) -> list[dict[str, Any]]:
    request_params = {
        "rn": int(params.get("rn") or 20),
        "pn": int(params.get("pn") or 0),
        "type": str(params.get("type") or "all"),
        "tag": str(params.get("tag") or "all"),
    }
    payload = _request_json(request_params)
    result = payload.get("Result") or {}
    tabs = result.get("tabs") or []
    if not isinstance(tabs, list):
        raise RuntimeError("baidu finance news feed returned invalid Result.tabs")

    captured_at = datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []
    seen_news_ids: set[str] = set()
    for tab in tabs:
        if not isinstance(tab, dict):
            continue
        contents = tab.get("contents") or []
        if not isinstance(contents, list):
            continue
        tab_type = str(tab.get("type") or "")
        tab_text = str(tab.get("text") or "")
        for item in contents:
            if not isinstance(item, dict):
                continue
            provider_news_id = str(item.get("news_id") or "").strip()
            if provider_news_id and provider_news_id in seen_news_ids:
                continue
            if provider_news_id:
                seen_news_ids.add(provider_news_id)
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            raw_tags = [str(tag_value) for tag_value in list(item.get("st_tags_arr") or [])]
            queue = [str(queue_value) for queue_value in list(item.get("queue") or [])]
            refs = _stock_refs(raw_tags)
            rows.append(
                {
                    "provider_news_id": provider_news_id or None,
                    "title": title,
                    "source_name": str(item.get("source") or "BAIDU"),
                    "published_at": _published_at_from_epoch(item.get("publish_time")),
                    "available_at": captured_at,
                    "event_type": "finance_news",
                    "url": str(item.get("third_url") or item.get("loc") or "") or None,
                    "symbol": refs[0]["symbol"] if refs else None,
                    "tags_json": {
                        "tab_type": tab_type,
                        "tab_text": tab_text,
                        "st_tags_arr": raw_tags,
                        "queue": queue,
                        "feed_weight": item.get("feed_weight"),
                        "bucket": item.get("bucket"),
                        "sort_trace": item.get("sort_trace"),
                    },
                    "stock_refs_json": refs,
                }
            )
    return rows


class BaiduAdapter(ProviderAdapter):
    provider = Provider.BAIDU

    def fetch(self, api_name: str, params: dict[str, Any], *, dry_run: bool = False) -> RawFetchResult:
        if dry_run:
            return self.build_result(api_name, params, [], dry_run=True, warning="dry_run: provider not called")
        if api_name == "finance_news_feed":
            return self.build_result(api_name, params, _finance_news_rows(params))
        raise KeyError(f"unsupported baidu api: {api_name}")
