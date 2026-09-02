from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from source_data_service.adapters.base import ProviderAdapter
from source_data_service.models import Provider, RawFetchResult


SIMPLE_PRICE_ENDPOINT = "https://api.coingecko.com/api/v3/simple/price"
GLOBAL_ENDPOINT = "https://api.coingecko.com/api/v3/global"
COINGECKO_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
    "Accept": "application/json",
}
KNOWN_COINS = {
    "bitcoin": ("BTC", "Bitcoin"),
    "ethereum": ("ETH", "Ethereum"),
    "solana": ("SOL", "Solana"),
    "dogecoin": ("DOGE", "Dogecoin"),
}


def _json(url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    import requests

    response = requests.get(url, params=params or {}, headers=COINGECKO_HEADERS, timeout=20)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("coingecko returned non-object json")
    return payload


def _num_text(value: Any) -> str | None:
    if value in (None, "", "-", "--"):
        return None
    try:
        return str(Decimal(str(value)))
    except (InvalidOperation, ValueError):
        return None


def _coin_code(coin_id: str) -> str:
    return KNOWN_COINS.get(coin_id, (coin_id.upper().replace("-", "_"), coin_id))[0]


def _coin_name(coin_id: str) -> str:
    return KNOWN_COINS.get(coin_id, (coin_id, coin_id.replace("-", " ").title()))[1]


def _ids(params: dict[str, Any]) -> list[str]:
    raw = params.get("ids") or params.get("asset_ids") or "bitcoin,ethereum"
    if isinstance(raw, str):
        return [item.strip().lower() for item in raw.split(",") if item.strip()]
    if isinstance(raw, list):
        return [str(item).strip().lower() for item in raw if str(item).strip()]
    return ["bitcoin", "ethereum"]


def _simple_price_rows(params: dict[str, Any]) -> list[dict[str, Any]]:
    ids = _ids(params)
    vs_currency = str(params.get("vs_currency") or "usd").lower()
    payload = _json(
        SIMPLE_PRICE_ENDPOINT,
        {
            "ids": ",".join(ids),
            "vs_currencies": vs_currency,
            "include_24hr_change": "true",
            "include_24hr_vol": "true",
            "include_market_cap": "true",
        },
    )
    captured_at = datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []
    for coin_id in ids:
        row = payload.get(coin_id)
        if not isinstance(row, dict):
            continue
        rows.append(
            {
                "asset_id": coin_id,
                "asset_code": _coin_code(coin_id),
                "asset_name": _coin_name(coin_id),
                "asset_class": "crypto_spot",
                "quote_currency": vs_currency.upper(),
                "captured_at": captured_at,
                "last_price": _num_text(row.get(vs_currency)),
                "change_pct_24h": _num_text(row.get(f"{vs_currency}_24h_change")),
                "market_cap": _num_text(row.get(f"{vs_currency}_market_cap")),
                "volume_24h": _num_text(row.get(f"{vs_currency}_24h_vol")),
                "raw_provider_row": row,
            }
        )
    return rows


def _global_rows(params: dict[str, Any]) -> list[dict[str, Any]]:
    vs_currency = str(params.get("vs_currency") or "usd").lower()
    payload = _json(GLOBAL_ENDPOINT)
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    total_market_cap = data.get("total_market_cap") if isinstance(data.get("total_market_cap"), dict) else {}
    total_volume = data.get("total_volume") if isinstance(data.get("total_volume"), dict) else {}
    market_cap_percentage = data.get("market_cap_percentage") if isinstance(data.get("market_cap_percentage"), dict) else {}
    captured_at = datetime.now(timezone.utc).isoformat()
    return [
        {
            "metric_code": "CRYPTO_TOTAL_MCAP",
            "asset_code": "CRYPTO_TOTAL_MCAP",
            "asset_class": "crypto_global",
            "quote_currency": vs_currency.upper(),
            "captured_at": captured_at,
            "market_cap": _num_text(total_market_cap.get(vs_currency)),
            "volume_24h": _num_text(total_volume.get(vs_currency)),
            "change_pct_24h": _num_text(data.get("market_cap_change_percentage_24h_usd")),
            "updated_at": data.get("updated_at"),
            "raw_provider_row": data,
        },
        {
            "metric_code": "BTC_DOMINANCE",
            "asset_code": "BTC_DOMINANCE",
            "asset_class": "crypto_global",
            "quote_currency": "PCT",
            "captured_at": captured_at,
            "last_price": _num_text(market_cap_percentage.get("btc")),
            "dominance_pct": _num_text(market_cap_percentage.get("btc")),
            "updated_at": data.get("updated_at"),
            "raw_provider_row": data,
        },
    ]


class CoinGeckoAdapter(ProviderAdapter):
    provider = Provider.COINGECKO

    def fetch(self, api_name: str, params: dict[str, Any], *, dry_run: bool = False) -> RawFetchResult:
        if dry_run:
            return self.build_result(api_name, params, [], dry_run=True, warning="dry_run: provider not called")
        if api_name == "simple_price":
            return self.build_result(api_name, params, _simple_price_rows(params))
        if api_name == "global_market":
            return self.build_result(api_name, params, _global_rows(params))
        raise KeyError(f"unsupported coingecko api: {api_name}")
