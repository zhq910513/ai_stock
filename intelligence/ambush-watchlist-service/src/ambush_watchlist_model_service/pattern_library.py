from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable


AMBUSH_PATTERN_LIBRARY_VERSION = "ambush_valley_pattern_library_v1_0"
AMBUSH_FORMULA_VERSION = "ambush_formula_governance_v1_0"
SIGNATURE_VECTOR_SIZE = 24
P0_REQUIRED_BAR_FIELDS = (
    "trading_day",
    "open_price",
    "high_price",
    "low_price",
    "close_price",
    "volume",
    "amount",
)
ADJUSTED_FIELD_GROUPS = (
    ("adjusted_open_price", "adjusted_high_price", "adjusted_low_price", "adjusted_close_price"),
    ("adj_open", "adj_high", "adj_low", "adj_close"),
    ("open_adj", "high_adj", "low_adj", "close_adj"),
)


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _float(value: Any, default: float = math.nan) -> float:
    numeric = _decimal(value)
    return float(numeric) if numeric is not None else default


def _score(value: float | Decimal | int | None) -> Decimal:
    if value is None or not math.isfinite(float(value)):
        return Decimal("0.000000")
    return Decimal(str(max(0.0, min(100.0, float(value))))).quantize(Decimal("0.000001"))


def _ratio(value: float | Decimal | int | None) -> Decimal | None:
    if value is None or not math.isfinite(float(value)):
        return None
    return Decimal(str(float(value))).quantize(Decimal("0.000001"))


def _pct(value: float | Decimal | int | None) -> Decimal | None:
    if value is None or not math.isfinite(float(value)):
        return None
    return Decimal(str(float(value) * 100.0)).quantize(Decimal("0.000001"))


def _as_date(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _json_hash(payload: dict[str, Any]) -> str:
    dumped = json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str)
    return hashlib.sha256(dumped.encode("utf-8")).hexdigest()


def _sorted_bars(bars: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        [bar for bar in bars if not bar.get("is_partial")],
        key=lambda item: str(item.get("trading_day") or ""),
    )


def _bars_until(bars: Iterable[dict[str, Any]], as_of_trading_day: date) -> list[dict[str, Any]]:
    rows = _sorted_bars(bars)
    return [row for row in rows if (_as_date(row.get("trading_day")) or as_of_trading_day) <= as_of_trading_day]


def _mean(values: Iterable[float]) -> float | None:
    clean = [value for value in values if math.isfinite(value)]
    if not clean:
        return None
    return sum(clean) / len(clean)


def _std(values: Iterable[float]) -> float:
    clean = [value for value in values if math.isfinite(value)]
    if len(clean) < 2:
        return 0.0
    avg = sum(clean) / len(clean)
    return math.sqrt(sum((value - avg) ** 2 for value in clean) / len(clean))


def _linear_slope(values: Iterable[float]) -> float:
    clean = [value for value in values if math.isfinite(value)]
    if len(clean) < 2:
        return 0.0
    n = len(clean)
    x_avg = (n - 1) / 2.0
    y_avg = sum(clean) / n
    denom = sum((x - x_avg) ** 2 for x in range(n))
    if denom <= 0:
        return 0.0
    return sum((x - x_avg) * (clean[x] - y_avg) for x in range(n)) / denom


def _returns(values: list[float]) -> list[float]:
    result: list[float] = []
    for previous, current in zip(values, values[1:], strict=False):
        if math.isfinite(previous) and math.isfinite(current) and previous > 0:
            result.append((current - previous) / previous)
    return result


def _normalize(values: list[float]) -> list[float]:
    clean = [value for value in values if math.isfinite(value)]
    if not clean:
        return []
    low = min(clean)
    high = max(clean)
    span = high - low
    if span <= 0:
        return [0.5 for _ in clean]
    return [(value - low) / span for value in clean]


def _resample(values: list[float], size: int = SIGNATURE_VECTOR_SIZE) -> list[float]:
    clean = [value for value in values if math.isfinite(value)]
    if not clean:
        return []
    if len(clean) == 1:
        return [clean[0]] * size
    result: list[float] = []
    last = len(clean) - 1
    for index in range(size):
        position = index * last / (size - 1)
        left = int(math.floor(position))
        right = int(math.ceil(position))
        if left == right:
            result.append(clean[left])
            continue
        weight = position - left
        result.append(clean[left] * (1.0 - weight) + clean[right] * weight)
    return result


def _safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
    if not math.isfinite(numerator) or not math.isfinite(denominator) or abs(denominator) <= 1e-12:
        return default
    return numerator / denominator


def _field_presence(rows: list[dict[str, Any]], field_name: str) -> tuple[int, Decimal]:
    present = sum(1 for row in rows if row.get(field_name) not in (None, ""))
    rate = Decimal(present) / Decimal(max(1, len(rows)))
    return present, rate.quantize(Decimal("0.000001"))


def _adjusted_group(rows: list[dict[str, Any]]) -> tuple[str, ...] | None:
    for group in ADJUSTED_FIELD_GROUPS:
        if all(any(row.get(field) not in (None, "") for row in rows) for field in group):
            return group
    return None


def _price_channels(rows: list[dict[str, Any]], *, prefer_adjusted: bool = True) -> tuple[dict[str, list[float]], dict[str, Any]]:
    adjusted_group = _adjusted_group(rows)
    use_adjusted = prefer_adjusted and adjusted_group is not None
    if use_adjusted and adjusted_group is not None:
        open_field, high_field, low_field, close_field = adjusted_group
        price_adjustment_mode = "adjusted_ohlc"
    else:
        open_field, high_field, low_field, close_field = "open_price", "high_price", "low_price", "close_price"
        price_adjustment_mode = "raw_ohlc_research_only" if prefer_adjusted else "raw_ohlc"
    opens = [_float(row.get(open_field)) for row in rows]
    highs = [_float(row.get(high_field)) for row in rows]
    lows = [_float(row.get(low_field)) for row in rows]
    closes = [_float(row.get(close_field)) for row in rows]
    typical_prices = [
        (high + low + close) / 3.0 if all(math.isfinite(v) for v in (high, low, close)) else math.nan
        for high, low, close in zip(highs, lows, closes, strict=False)
    ]
    volumes = [_float(row.get("volume")) for row in rows]
    amounts = [_float(row.get("amount")) for row in rows]
    turnover = [_float(row.get("turnover_rate")) for row in rows]
    body_ratio: list[float] = []
    upper_shadow_ratio: list[float] = []
    lower_shadow_ratio: list[float] = []
    close_position: list[float] = []
    for open_price, high_price, low_price, close_price in zip(opens, highs, lows, closes, strict=False):
        span = high_price - low_price
        if not all(math.isfinite(v) for v in (open_price, high_price, low_price, close_price)) or span <= 0:
            body_ratio.append(math.nan)
            upper_shadow_ratio.append(math.nan)
            lower_shadow_ratio.append(math.nan)
            close_position.append(math.nan)
            continue
        body_ratio.append(abs(close_price - open_price) / span)
        upper_shadow_ratio.append((high_price - max(open_price, close_price)) / span)
        lower_shadow_ratio.append((min(open_price, close_price) - low_price) / span)
        close_position.append((close_price - low_price) / span)
    metadata = {
        "price_adjustment_mode": price_adjustment_mode,
        "price_fields": {
            "open": open_field,
            "high": high_field,
            "low": low_field,
            "close": close_field,
        },
        "adjusted_ohlc_available": adjusted_group is not None,
    }
    return (
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "typical_price": typical_prices,
            "volume": volumes,
            "amount": amounts,
            "turnover_rate": turnover,
            "body_ratio": body_ratio,
            "upper_shadow_ratio": upper_shadow_ratio,
            "lower_shadow_ratio": lower_shadow_ratio,
            "close_position": close_position,
        },
        metadata,
    )


def audit_source_capability(
    *,
    provider: str,
    bars: list[dict[str, Any]],
    weekly_bars: list[dict[str, Any]] | None = None,
    instruments: list[dict[str, Any]] | None = None,
    checked_at: datetime | None = None,
) -> dict[str, Any]:
    """Validate data coverage before any formal ambush calculation.

    This is intentionally conservative. Missing adjusted OHLC does not make historical
    research impossible, but it blocks official pattern-library and online scoring use.
    """

    effective_time = checked_at or datetime.now(timezone.utc)
    rows = _sorted_bars(bars)
    weekly_rows = _sorted_bars(weekly_bars or [])
    field_audits: list[dict[str, Any]] = []
    source_gap_codes: list[str] = []
    for field_name in P0_REQUIRED_BAR_FIELDS:
        present_count, rate = _field_presence(rows, field_name)
        usable = rate >= Decimal("0.980000")
        if not usable:
            source_gap_codes.append(f"{field_name}_coverage_below_required")
        field_audits.append(
            {
                "data_domain": "daily_bar",
                "field_name": field_name,
                "frequency": "1d",
                "present_count": present_count,
                "total_count": len(rows),
                "coverage_rate": rate,
                "missing_rate": (Decimal("1") - rate).quantize(Decimal("0.000001")),
                "usable_for_pattern_library": usable,
                "usable_for_online_scoring": usable,
            }
        )
    adjusted_group = _adjusted_group(rows)
    adjustment_supported = adjusted_group is not None or any(row.get("adjustment_factor") not in (None, "") for row in rows)
    if adjusted_group is None:
        source_gap_codes.append("adjusted_ohlc_missing")
    available_at_count, available_at_rate = _field_presence(rows, "available_at")
    if available_at_rate < Decimal("0.980000"):
        source_gap_codes.append("available_at_missing_or_incomplete")
    trading_days = [_as_date(row.get("trading_day")) for row in rows]
    trading_days = [value for value in trading_days if value is not None]
    history_start_date = min(trading_days) if trading_days else None
    history_end_date = max(trading_days) if trading_days else None
    unique_symbols = {str(row.get("symbol") or "") for row in rows if row.get("symbol") not in (None, "")}
    requested_symbols = {str(item.get("symbol") or "") for item in (instruments or []) if item.get("symbol") not in (None, "")}
    if requested_symbols:
        symbol_coverage_rate = Decimal(len(unique_symbols & requested_symbols)) / Decimal(len(requested_symbols))
    else:
        symbol_coverage_rate = Decimal("1") if unique_symbols or rows else Decimal("0")
    weekly_supported = bool(weekly_rows) or len(rows) >= 80
    if not weekly_supported:
        source_gap_codes.append("weekly_context_not_available")
    usable_for_pattern_library = (
        bool(rows)
        and all(item["usable_for_pattern_library"] for item in field_audits)
        and adjusted_group is not None
        and weekly_supported
    )
    usable_for_online_scoring = usable_for_pattern_library and available_at_rate >= Decimal("0.980000")
    quality_status = "ready" if usable_for_online_scoring else "research_only" if rows else "blocked"
    if not rows:
        source_gap_codes.append("daily_bar_missing")
    result = {
        "provider": provider,
        "checked_at": effective_time,
        "history_start_date": history_start_date,
        "history_end_date": history_end_date,
        "daily_bar_count": len(rows),
        "weekly_bar_count": len(weekly_rows),
        "symbol_coverage_rate": symbol_coverage_rate.quantize(Decimal("0.000001")),
        "available_at_supported": available_at_rate >= Decimal("0.980000"),
        "available_at_coverage_rate": available_at_rate,
        "adjustment_supported": adjustment_supported,
        "adjusted_ohlc_supported": adjusted_group is not None,
        "weekly_context_supported": weekly_supported,
        "usable_for_pattern_library": usable_for_pattern_library,
        "usable_for_online_scoring": usable_for_online_scoring,
        "quality_status": quality_status,
        "source_gap_codes": sorted(set(source_gap_codes)),
        "field_audits": field_audits,
        "formula_governance": {
            "rule_code": "ambush_source_capability_audit_v1",
            "rule_version": AMBUSH_FORMULA_VERSION,
            "hard_rule": "official scoring requires adjusted OHLC, P0 daily OHLCV coverage >= 98%, weekly context, and available_at coverage >= 98%",
        },
    }
    result["payload_hash"] = _json_hash(result)
    return result


def build_shape_signature(
    *,
    symbol: str,
    bars: list[dict[str, Any]],
    as_of_trading_day: date,
    window_days: int = 60,
    prefer_adjusted: bool = True,
    signature_size: int = SIGNATURE_VECTOR_SIZE,
) -> dict[str, Any]:
    rows = _bars_until(bars, as_of_trading_day)
    selected = rows[-window_days:]
    source_gap_codes: list[str] = []
    if len(selected) < math.ceil(window_days * 0.95):
        source_gap_codes.append("daily_bar_incomplete")
    channels, metadata = _price_channels(selected, prefer_adjusted=prefer_adjusted)
    if prefer_adjusted and not metadata["adjusted_ohlc_available"]:
        source_gap_codes.append("adjusted_ohlc_missing_research_only")
    required_channels = ["open", "high", "low", "close", "typical_price", "volume"]
    for name in required_channels:
        if len([value for value in channels[name] if math.isfinite(value)]) < math.ceil(len(selected) * 0.95):
            source_gap_codes.append(f"{name}_channel_incomplete")
    close_path = _normalize(_resample(channels["close"], signature_size))
    typical_path = _normalize(_resample(channels["typical_price"], signature_size))
    high_path = _normalize(_resample(channels["high"], signature_size))
    low_path = _normalize(_resample(channels["low"], signature_size))
    volume_path = _normalize(_resample([math.log1p(max(0.0, value)) for value in channels["volume"]], signature_size))
    body_path = _normalize(_resample(channels["body_ratio"], signature_size))
    upper_shadow_path = _normalize(_resample(channels["upper_shadow_ratio"], signature_size))
    lower_shadow_path = _normalize(_resample(channels["lower_shadow_ratio"], signature_size))
    close_position_path = _normalize(_resample(channels["close_position"], signature_size))
    vector = (
        close_path
        + typical_path
        + high_path
        + low_path
        + volume_path
        + body_path
        + upper_shadow_path
        + lower_shadow_path
        + close_position_path
    )
    closes = channels["close"]
    lows = channels["low"]
    highs = channels["high"]
    valid_close = [value for value in closes if math.isfinite(value) and value > 0]
    valid_high = [value for value in highs if math.isfinite(value) and value > 0]
    valid_low = [value for value in lows if math.isfinite(value) and value > 0]
    if not valid_close or not valid_high or not valid_low:
        source_gap_codes.append("price_channel_invalid")
        trough_day = None
        drawdown_pct = None
        distance_from_low_pct = None
    else:
        trough_index = min(range(len(lows)), key=lambda idx: lows[idx] if math.isfinite(lows[idx]) else math.inf)
        trough_day = _as_date(selected[trough_index].get("trading_day")) if selected else None
        max_high = max(valid_high)
        trough_low = min(valid_low)
        drawdown_pct = _pct((max_high - trough_low) / max_high if max_high > 0 else None)
        distance_from_low_pct = _pct((valid_close[-1] - trough_low) / trough_low if trough_low > 0 else None)
    result = {
        "symbol": str(symbol).zfill(6),
        "as_of_trading_day": as_of_trading_day,
        "window_days": window_days,
        "signature_size": signature_size,
        "signature_version": "multi_channel_ohlcv_signature_v1",
        "price_adjustment_mode": metadata["price_adjustment_mode"],
        "price_fields": metadata["price_fields"],
        "official_scoring_allowed": not source_gap_codes,
        "source_gap_codes": sorted(set(source_gap_codes)),
        "trough_trading_day": trough_day,
        "drawdown_pct": drawdown_pct,
        "distance_from_low_pct": distance_from_low_pct,
        "channels": {
            "close_path": close_path,
            "typical_price_path": typical_path,
            "high_envelope_path": high_path,
            "low_envelope_path": low_path,
            "volume_path": volume_path,
            "body_ratio_path": body_path,
            "upper_shadow_path": upper_shadow_path,
            "lower_shadow_path": lower_shadow_path,
            "close_position_path": close_position_path,
        },
        "embedding_vector": [round(value, 8) for value in vector],
        "formula_governance": {
            "formula_code": "ambush_multi_channel_shape_signature_v1",
            "formula_version": AMBUSH_FORMULA_VERSION,
            "financial_purpose": "Represent low-valley daily K-line shape without using rendered pixels; preserve close path, price center, high-low envelope, candlestick geometry, and volume behavior.",
            "data_policy": "Use adjusted OHLC for shape; raw volume/amount remain unadjusted; raw price is research-only when adjusted OHLC is missing.",
            "future_data_policy": "Uses only bars up to as_of_trading_day.",
        },
    }
    result["signature_hash"] = _json_hash(result)
    return result


def _vector_distance(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 999.0
    size = min(len(left), len(right))
    if size <= 0:
        return 999.0
    return math.sqrt(sum((left[i] - right[i]) ** 2 for i in range(size)) / size)


def _distance_to_similarity(distance: float, tau: float = 0.22) -> Decimal:
    return _score(100.0 * math.exp(-max(0.0, distance) / tau))


def match_pattern_prototypes(
    *,
    current_signature: dict[str, Any],
    prototypes: list[dict[str, Any]],
    top_k: int = 5,
) -> dict[str, Any]:
    vector = [float(value) for value in current_signature.get("embedding_vector") or []]
    matches: list[dict[str, Any]] = []
    for prototype in prototypes:
        proto_vector = prototype.get("embedding_vector") or prototype.get("signature_vector") or []
        try:
            proto_values = [float(value) for value in proto_vector]
        except (TypeError, ValueError):
            continue
        distance = _vector_distance(vector, proto_values)
        similarity = _distance_to_similarity(distance)
        prototype_type = str(prototype.get("prototype_type") or prototype.get("sample_label") or "unknown")
        matches.append(
            {
                "prototype_id": prototype.get("prototype_id"),
                "prototype_type": prototype_type,
                "sample_count": int(prototype.get("sample_count") or 1),
                "quality_score": _score(_float(prototype.get("quality_score"), 50.0)),
                "distance": Decimal(str(distance)).quantize(Decimal("0.000001")),
                "similarity": similarity,
            }
        )
    matches.sort(key=lambda item: (Decimal(str(item["similarity"])), Decimal(str(item["quality_score"]))), reverse=True)
    top_matches = matches[: max(1, top_k)]
    positive_matches = [m for m in matches if str(m["prototype_type"]).endswith("positive") or "positive" in str(m["prototype_type"])]
    false_matches = [m for m in matches if "negative" in str(m["prototype_type"]) or "false" in str(m["prototype_type"])]
    hard_negative_matches = [m for m in false_matches if "hard" in str(m["prototype_type"])]
    positive_similarity = max([Decimal(str(m["similarity"])) for m in positive_matches] or [Decimal("0")])
    false_bottom_similarity = max([Decimal(str(m["similarity"])) for m in false_matches] or [Decimal("0")])
    hard_negative_similarity = max([Decimal(str(m["similarity"])) for m in hard_negative_matches] or [Decimal("0")])
    shape_edge_score = _score(positive_similarity - false_bottom_similarity * Decimal("0.70") - hard_negative_similarity * Decimal("1.00"))
    result = {
        "symbol": current_signature.get("symbol"),
        "as_of_trading_day": current_signature.get("as_of_trading_day"),
        "pattern_library_version": current_signature.get("pattern_library_version") or AMBUSH_PATTERN_LIBRARY_VERSION,
        "signature_hash": current_signature.get("signature_hash"),
        "positive_valley_similarity": positive_similarity,
        "false_bottom_similarity": false_bottom_similarity,
        "hard_negative_similarity": hard_negative_similarity,
        "shape_edge_score": shape_edge_score,
        "top_matches": top_matches,
        "formula_governance": {
            "formula_code": "ambush_topk_pattern_match_v1",
            "formula_version": AMBUSH_FORMULA_VERSION,
            "financial_purpose": "Use positive and negative historical low-valley prototypes as shape prior; net score must penalize false-bottom and hard-negative similarity.",
            "performance_policy": "Online path uses precomputed embedding vectors and TopK matching; DTW is reserved for offline precision or TopK recheck.",
            "score_formula": "shape_edge_score = positive_similarity - 0.7 * false_bottom_similarity - 1.0 * hard_negative_similarity",
        },
    }
    result["payload_hash"] = _json_hash(result)
    return result


def label_historical_valley_sample(
    *,
    symbol: str,
    bars: list[dict[str, Any]],
    anchor_day: date,
    market_bars: list[dict[str, Any]] | None = None,
    sector_bars: list[dict[str, Any]] | None = None,
    pre_window_days: int = 60,
    label_window_days: int = 20,
) -> dict[str, Any]:
    rows = _sorted_bars(bars)
    dates = [_as_date(row.get("trading_day")) for row in rows]
    if anchor_day not in dates:
        return {
            "symbol": str(symbol).zfill(6),
            "anchor_day": anchor_day,
            "sample_label": "blocked",
            "source_gap_codes": ["anchor_day_not_found"],
            "formula_governance": {"formula_code": "ambush_historical_sample_label_v1", "formula_version": AMBUSH_FORMULA_VERSION},
        }
    anchor_index = dates.index(anchor_day)
    start_index = max(0, anchor_index - pre_window_days + 1)
    end_index = min(len(rows), anchor_index + label_window_days + 1)
    pre_rows = rows[start_index : anchor_index + 1]
    future_rows = rows[anchor_index + 1 : end_index]
    source_gap_codes: list[str] = []
    if len(pre_rows) < math.ceil(pre_window_days * 0.80):
        source_gap_codes.append("pre_window_incomplete")
    if len(future_rows) < math.ceil(label_window_days * 0.60):
        source_gap_codes.append("label_window_incomplete")
    channels, metadata = _price_channels(pre_rows + future_rows, prefer_adjusted=True)
    if not metadata["adjusted_ohlc_available"]:
        source_gap_codes.append("adjusted_ohlc_missing_research_only")
    pre_len = len(pre_rows)
    pre_close = channels["close"][:pre_len]
    pre_high = channels["high"][:pre_len]
    pre_low = channels["low"][:pre_len]
    future_high = channels["high"][pre_len:]
    future_low = channels["low"][pre_len:]
    future_close = channels["close"][pre_len:]
    anchor_close = pre_close[-1] if pre_close and math.isfinite(pre_close[-1]) else math.nan
    max_pre_high = max([value for value in pre_high if math.isfinite(value)] or [math.nan])
    min_pre_low = min([value for value in pre_low if math.isfinite(value)] or [math.nan])
    drawdown = _safe_divide(max_pre_high - min_pre_low, max_pre_high, math.nan)
    max_future_high = max([value for value in future_high if math.isfinite(value)] or [math.nan])
    min_future_low = min([value for value in future_low if math.isfinite(value)] or [math.nan])
    rebound_mfe = _safe_divide(max_future_high - anchor_close, anchor_close, math.nan)
    post_anchor_max_drawdown = _safe_divide(anchor_close - min_future_low, anchor_close, 0.0)
    persistence_days = 0
    for value in future_close:
        if math.isfinite(value) and math.isfinite(anchor_close) and value >= anchor_close * 1.03:
            persistence_days += 1
    market_return = _window_return(market_bars, anchor_day, label_window_days)
    sector_return = _window_return(sector_bars, anchor_day, label_window_days)
    own_return = (future_close[-1] - anchor_close) / anchor_close if future_close and anchor_close > 0 else None
    relative_market_return = own_return - market_return if own_return is not None and market_return is not None else None
    relative_sector_return = own_return - sector_return if own_return is not None and sector_return is not None else None
    drawdown_score = _score((drawdown - 0.08) / 0.32 * 100.0 if math.isfinite(drawdown) else None)
    mfe_score = _score((rebound_mfe - 0.08) / 0.22 * 100.0 if math.isfinite(rebound_mfe) else None)
    market_score = _score((relative_market_return or 0.0) / 0.15 * 100.0 if relative_market_return is not None else 50.0)
    sector_score = _score((relative_sector_return or 0.0) / 0.12 * 100.0 if relative_sector_return is not None else 50.0)
    persistence_score = _score(min(100.0, persistence_days / max(1, label_window_days // 4) * 100.0))
    drawdown_control_score = _score(100.0 - min(100.0, post_anchor_max_drawdown / 0.15 * 100.0))
    tradable_entry_window_score = _tradable_window_score(future_rows)
    rebound_quality_score = _score(
        float(mfe_score) * 0.25
        + float(market_score) * 0.20
        + float(sector_score) * 0.20
        + float(persistence_score) * 0.15
        + float(drawdown_control_score) * 0.10
        + float(tradable_entry_window_score) * 0.10
    )
    direction_success = rebound_mfe >= 0.12 if math.isfinite(rebound_mfe) else False
    tradable_success = tradable_entry_window_score >= Decimal("60")
    structure_success = persistence_score >= Decimal("40") and drawdown_control_score >= Decimal("45")
    if direction_success and tradable_success and structure_success and rebound_quality_score >= Decimal("70"):
        sample_label = "strong_positive"
    elif direction_success and rebound_quality_score >= Decimal("50"):
        sample_label = "weak_positive"
    elif drawdown_score >= Decimal("55") and rebound_quality_score < Decimal("45"):
        sample_label = "hard_negative"
    else:
        sample_label = "easy_negative"
    result = {
        "symbol": str(symbol).zfill(6),
        "anchor_day": anchor_day,
        "window_start_date": _as_date(pre_rows[0].get("trading_day")) if pre_rows else None,
        "window_end_date": _as_date(rows[end_index - 1].get("trading_day")) if rows and end_index > 0 else None,
        "pre_window_days": pre_window_days,
        "label_window_days": label_window_days,
        "price_adjustment_mode": metadata["price_adjustment_mode"],
        "sample_label": sample_label,
        "hard_negative_flag": sample_label == "hard_negative",
        "direction_success": direction_success,
        "tradable_success": tradable_success,
        "structure_success": structure_success,
        "drawdown_pct": _pct(drawdown) if math.isfinite(drawdown) else None,
        "rebound_mfe_pct": _pct(rebound_mfe) if math.isfinite(rebound_mfe) else None,
        "post_anchor_max_drawdown_pct": _pct(post_anchor_max_drawdown),
        "relative_market_return_pct": _pct(relative_market_return),
        "relative_sector_return_pct": _pct(relative_sector_return),
        "rebound_persistence_days": persistence_days,
        "tradable_entry_window_score": tradable_entry_window_score,
        "rebound_quality_score": rebound_quality_score,
        "source_gap_codes": sorted(set(source_gap_codes)),
        "formula_governance": {
            "formula_code": "ambush_historical_sample_label_v1",
            "formula_version": AMBUSH_FORMULA_VERSION,
            "financial_purpose": "Label positive, weak positive, hard negative, and easy negative low-valley samples using depth, relative rebound quality, persistence, drawdown control, and tradability.",
            "future_data_policy": "Future rows after anchor_day are allowed only for historical sample labeling; never for online scoring.",
        },
    }
    result["sample_hash"] = _json_hash(result)
    return result


def _window_return(bars: list[dict[str, Any]] | None, anchor_day: date, label_window_days: int) -> float | None:
    if not bars:
        return None
    rows = _sorted_bars(bars)
    dates = [_as_date(row.get("trading_day")) for row in rows]
    if anchor_day not in dates:
        return None
    idx = dates.index(anchor_day)
    end = min(len(rows) - 1, idx + label_window_days)
    channels, _ = _price_channels(rows[idx : end + 1], prefer_adjusted=True)
    closes = [value for value in channels["close"] if math.isfinite(value) and value > 0]
    if len(closes) < 2:
        return None
    return (closes[-1] - closes[0]) / closes[0]


def _tradable_window_score(future_rows: list[dict[str, Any]]) -> Decimal:
    if not future_rows:
        return Decimal("0.000000")
    blocked = 0
    valid = 0
    for row in future_rows[:5]:
        valid += 1
        if row.get("is_suspended") or row.get("is_limit_up_no_fill") or row.get("is_limit_down"):
            blocked += 1
    if valid == 0:
        return Decimal("0.000000")
    return _score(100.0 * (1.0 - blocked / valid))


def build_three_channel_recall(
    *,
    instrument: dict[str, Any],
    bars: list[dict[str, Any]],
    as_of_trading_day: date,
    prototypes: list[dict[str, Any]] | None = None,
    market_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Phase-1 recall entry point: shape, mathematical valley, and compression breakout.

    The function returns research-grade recall facts only. It does not publish an
    official signal and does not use any data after as_of_trading_day.
    """

    symbol = str(instrument.get("symbol") or "").zfill(6)
    signature = build_shape_signature(symbol=symbol, bars=bars, as_of_trading_day=as_of_trading_day, window_days=60)
    match_result = match_pattern_prototypes(current_signature=signature, prototypes=prototypes or [], top_k=5) if prototypes else None
    rows = _bars_until(bars, as_of_trading_day)
    selected = rows[-60:]
    source_gap_codes = list(signature.get("source_gap_codes") or [])
    channels, _ = _price_channels(selected, prefer_adjusted=True)
    closes = channels["close"]
    lows = channels["low"]
    highs = channels["high"]
    volumes = channels["volume"]
    valid_close = [value for value in closes if math.isfinite(value) and value > 0]
    if len(valid_close) < 30:
        source_gap_codes.append("insufficient_close_history")
        valley_maturity_score = Decimal("0.000000")
        compression_breakout_score = Decimal("0.000000")
    else:
        trough_idx = min(range(len(lows)), key=lambda idx: lows[idx] if math.isfinite(lows[idx]) else math.inf)
        max_high = max([value for value in highs if math.isfinite(value)] or [0.0])
        trough_low = min([value for value in lows if math.isfinite(value)] or [0.0])
        drawdown = (max_high - trough_low) / max_high if max_high > 0 else 0.0
        slope20 = _linear_slope([math.log(value) for value in valid_close[-20:] if value > 0])
        slope5 = _linear_slope([math.log(value) for value in valid_close[-5:] if value > 0])
        post_lows = lows[trough_idx:]
        support_not_broken = min([value for value in post_lows if math.isfinite(value)] or [0.0]) >= trough_low * 0.985 if trough_low > 0 else False
        rv10 = _std(_returns(valid_close[-10:]))
        rv40 = _std(_returns(valid_close[-40:]))
        volume5 = _mean(volumes[-5:]) or 0.0
        volume20 = _mean(volumes[-20:]) or 0.0
        drawdown_score = _score((drawdown - 0.08) / 0.32 * 100.0)
        deceleration_score = _score(100.0 if slope20 < 0 and slope5 > slope20 else 35.0)
        support_score = _score(100.0 if support_not_broken else 25.0)
        volatility_score = _score(100.0 if rv40 > 0 and rv10 < rv40 else 45.0)
        volume_score = _score(100.0 if volume20 > 0 and volume5 / volume20 <= 1.20 else 50.0)
        valley_maturity_score = _score(
            float(drawdown_score) * 0.25
            + float(deceleration_score) * 0.25
            + float(support_score) * 0.20
            + float(volatility_score) * 0.15
            + float(volume_score) * 0.15
        )
        compression_breakout_score = _compression_breakout_score(selected, channels)
    shape_score = Decimal(str(match_result.get("shape_edge_score"))) if match_result else Decimal("0")
    recall_channels: list[str] = []
    if match_result and shape_score >= Decimal("35"):
        recall_channels.append("shape_similarity_recall")
    if valley_maturity_score >= Decimal("60"):
        recall_channels.append("mathematical_valley_recall")
    if compression_breakout_score >= Decimal("65"):
        recall_channels.append("compression_breakout_recall")
    market_regime = str((market_context or {}).get("risk_regime") or (market_context or {}).get("market_regime") or "unknown")
    result = {
        "symbol": symbol,
        "as_of_trading_day": as_of_trading_day,
        "recall_status": "recalled" if recall_channels else "not_recalled",
        "recall_channels": recall_channels,
        "pattern_match": match_result,
        "shape_signature": signature,
        "valley_maturity_score": valley_maturity_score,
        "compression_breakout_score": compression_breakout_score,
        "market_regime": market_regime,
        "source_gap_codes": sorted(set(source_gap_codes)),
        "formula_governance": {
            "formula_code": "ambush_three_channel_recall_v1",
            "formula_version": AMBUSH_FORMULA_VERSION,
            "financial_purpose": "Recall candidates through shape prior, mathematically mature valley, and horizontal compression breakout without relying on a single channel.",
            "future_data_policy": "Uses only bars up to as_of_trading_day.",
            "not_a_signal": True,
        },
    }
    result["payload_hash"] = _json_hash(result)
    return result


def _compression_breakout_score(selected: list[dict[str, Any]], channels: dict[str, list[float]]) -> Decimal:
    if len(selected) < 12:
        return Decimal("0.000000")
    closes = channels["close"]
    highs = channels["high"]
    lows = channels["low"]
    volumes = channels["volume"]
    if not all(math.isfinite(v) and v > 0 for v in closes[-10:] + highs[-10:] + lows[-10:]):
        return Decimal("0.000000")
    base_high = max(highs[-8:-1])
    base_low = min(lows[-8:-1])
    base_range = (base_high - base_low) / base_low if base_low > 0 else 1.0
    breakout = closes[-1] > base_high * 0.995
    volume5 = _mean(volumes[-5:]) or 0.0
    volume20 = _mean(volumes[-20:]) or 0.0
    volume_recovery = volume20 > 0 and 0.90 <= volume5 / volume20 <= 2.50
    close_position = _safe_divide(closes[-1] - lows[-1], highs[-1] - lows[-1], 0.0)
    return _score(
        (100.0 if base_range <= 0.08 else max(0.0, 100.0 - base_range / 0.18 * 100.0)) * 0.35
        + (100.0 if breakout else 35.0) * 0.30
        + (100.0 if volume_recovery else 45.0) * 0.20
        + close_position * 100.0 * 0.15
    )
