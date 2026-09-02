from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import quote

from source_data_service.adapters.base import ProviderAdapter
from source_data_service.models import Provider, RawFetchResult


YAHOO_CHART_ENDPOINT = "https://query1.finance.yahoo.com/v8/finance/chart"
YAHOO_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
    "Accept": "application/json",
}
DEFAULT_SYMBOLS = {
    "^NDX": ("NASDAQ100", "Nasdaq 100", "equity_index", "USD"),
    "^HSI": ("HSI", "Hang Seng Index", "equity_index", "HKD"),
    "^SOX": ("SOX", "PHLX Semiconductor Index", "equity_index", "USD"),
    "^VIX": ("VIX", "CBOE Volatility Index", "volatility_index", "USD"),
    "USDCNH=X": ("USDCNH", "USD/CNH", "fx", "CNH"),
}


def _json(url: str, params: dict[str, Any]) -> dict[str, Any]:
    import requests

    response = requests.get(url, params=params, headers=YAHOO_HEADERS, timeout=20)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("yahoo chart returned non-object json")
    return payload


def _num(value: Any) -> Decimal | None:
    if value in (None, "", "-", "--"):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _num_text(value: Any) -> str | None:
    parsed = _num(value)
    return str(parsed) if parsed is not None else None


def _pct_change(last_value: Decimal | None, previous_value: Decimal | None) -> str | None:
    if last_value is None or previous_value in (None, Decimal("0")):
        return None
    return str(((last_value - previous_value) / previous_value) * Decimal("100"))


def _symbols(params: dict[str, Any]) -> list[str]:
    raw = params.get("symbols") or params.get("symbol") or ",".join(DEFAULT_SYMBOLS.keys())
    if isinstance(raw, str):
        return [item.strip() for item in raw.split(",") if item.strip()]
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    return list(DEFAULT_SYMBOLS.keys())


def _symbol_meta(symbol: str) -> tuple[str, str, str, str | None]:
    if symbol in DEFAULT_SYMBOLS:
        return DEFAULT_SYMBOLS[symbol]
    code = symbol.replace("^", "").replace("=", "_").replace("-", "_").upper()
    return code, symbol, "other", None


def _chart_row(symbol: str, params: dict[str, Any]) -> dict[str, Any] | None:
    endpoint = f"{YAHOO_CHART_ENDPOINT}/{quote(symbol, safe='')}"
    payload = _json(
        endpoint,
        {
            "interval": str(params.get("interval") or "1d"),
            "range": str(params.get("range") or params.get("range_window") or "1mo"),
            "includePrePost": "false",
            "events": "div,splits",
        },
    )
    chart = payload.get("chart") if isinstance(payload.get("chart"), dict) else {}
    results = chart.get("result") if isinstance(chart.get("result"), list) else []
    if not results or not isinstance(results[0], dict):
        return None
    result = results[0]
    meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}
    indicators = result.get("indicators") if isinstance(result.get("indicators"), dict) else {}
    quote_items = indicators.get("quote") if isinstance(indicators.get("quote"), list) else []
    quote_row = quote_items[0] if quote_items and isinstance(quote_items[0], dict) else {}
    timestamps = result.get("timestamp") if isinstance(result.get("timestamp"), list) else []
    closes = quote_row.get("close") if isinstance(quote_row.get("close"), list) else []
    valid: list[tuple[int, Decimal]] = []
    for ts, close in zip(timestamps, closes):
        parsed = _num(close)
        if parsed is not None:
            valid.append((int(ts), parsed))
    last_ts = valid[-1][0] if valid else None
    last_close = valid[-1][1] if valid else None
    previous_close = valid[-2][1] if len(valid) >= 2 else (_num(meta.get("chartPreviousClose")) or _num(meta.get("previousClose")))
    last_price = _num(meta.get("regularMarketPrice")) or last_close
    asset_code, asset_name, asset_class, default_currency = _symbol_meta(symbol)
    quote_currency = str(meta.get("currency") or default_currency or "").upper() or None
    observed_at = datetime.fromtimestamp(last_ts, tz=timezone.utc).isoformat() if last_ts else None
    return {
        "provider_symbol": symbol,
        "asset_code": asset_code,
        "asset_name": str(meta.get("shortName") or meta.get("longName") or asset_name),
        "asset_class": asset_class,
        "quote_currency": quote_currency,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "observed_at": observed_at,
        "last_price": str(last_price) if last_price is not None else None,
        "change_pct": _pct_change(last_price, previous_close),
        "previous_close": str(previous_close) if previous_close is not None else None,
        "exchange_name": meta.get("exchangeName"),
        "market_state": meta.get("marketState"),
        "instrument_type": meta.get("instrumentType"),
        "raw_provider_row": result,
    }


def _chart_rows(params: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    for symbol in _symbols(params):
        try:
            row = _chart_row(symbol, params)
            if row is not None:
                rows.append(row)
        except Exception as exc:  # noqa: BLE001 - partial provider failures remain audit facts
            errors[symbol] = str(exc)
    if not rows and errors:
        raise RuntimeError(f"yahoo chart returned no usable rows; errors={errors}")
    for row in rows:
        row["errors_json"] = errors
    return rows


class YahooAdapter(ProviderAdapter):
    provider = Provider.YAHOO

    def fetch(self, api_name: str, params: dict[str, Any], *, dry_run: bool = False) -> RawFetchResult:
        if dry_run:
            return self.build_result(api_name, params, [], dry_run=True, warning="dry_run: provider not called")
        if api_name == "chart":
            return self.build_result(api_name, params, _chart_rows(params))
        raise KeyError(f"unsupported yahoo api: {api_name}")
