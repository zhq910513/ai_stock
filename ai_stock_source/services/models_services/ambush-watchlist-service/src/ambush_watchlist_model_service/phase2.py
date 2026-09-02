from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from ambush_watchlist_model_service.pattern_library import (
    AMBUSH_FORMULA_VERSION,
    AMBUSH_PATTERN_LIBRARY_VERSION,
)

AMBUSH_PHASE2_VERSION = "ambush_watchlist_phase2_valley_turn_v1_0_rc"
PHASE2_FORMULA_VERSION = "ambush_phase2_formula_governance_v1_0"
MIN_DAILY_COMPLETENESS = Decimal("0.95")
MIN_AMOUNT_20D = Decimal("20000000")
OFFICIAL_EXCHANGES = {"SZ", "SZSE"}
OFFICIAL_ASSET_TYPES = {"A_SHARE", "CN_A_SHARE"}
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


def _hash(payload: dict[str, Any]) -> str:
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


def _returns(closes: list[float]) -> list[float]:
    result: list[float] = []
    for previous, current in zip(closes, closes[1:], strict=False):
        if math.isfinite(previous) and math.isfinite(current) and previous > 0:
            result.append((current - previous) / previous)
    return result


def _safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
    if not math.isfinite(numerator) or not math.isfinite(denominator) or abs(denominator) <= 1e-12:
        return default
    return numerator / denominator


def _adjusted_group(rows: list[dict[str, Any]]) -> tuple[str, ...] | None:
    for group in ADJUSTED_FIELD_GROUPS:
        if all(any(row.get(field) not in (None, "") for row in rows) for field in group):
            return group
    return None


def _price_arrays(rows: list[dict[str, Any]], *, prefer_adjusted: bool = True) -> tuple[dict[str, list[float]], dict[str, Any]]:
    adjusted_group = _adjusted_group(rows)
    use_adjusted = prefer_adjusted and adjusted_group is not None
    if use_adjusted and adjusted_group is not None:
        open_field, high_field, low_field, close_field = adjusted_group
        mode = "adjusted_ohlc"
    else:
        open_field, high_field, low_field, close_field = "open_price", "high_price", "low_price", "close_price"
        mode = "raw_ohlc_research_only" if prefer_adjusted else "raw_ohlc"
    opens = [_float(row.get(open_field)) for row in rows]
    highs = [_float(row.get(high_field)) for row in rows]
    lows = [_float(row.get(low_field)) for row in rows]
    closes = [_float(row.get(close_field)) for row in rows]
    volumes = [_float(row.get("volume")) for row in rows]
    amounts = [_float(row.get("amount")) for row in rows]
    close_positions: list[float] = []
    upper_shadows: list[float] = []
    lower_shadows: list[float] = []
    for open_price, high, low, close in zip(opens, highs, lows, closes, strict=False):
        span = high - low
        if not all(math.isfinite(value) for value in (open_price, high, low, close)) or span <= 0:
            close_positions.append(math.nan)
            upper_shadows.append(math.nan)
            lower_shadows.append(math.nan)
            continue
        close_positions.append((close - low) / span)
        upper_shadows.append((high - max(open_price, close)) / span)
        lower_shadows.append((min(open_price, close) - low) / span)
    return (
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
            "amount": amounts,
            "close_position": close_positions,
            "upper_shadow_ratio": upper_shadows,
            "lower_shadow_ratio": lower_shadows,
        },
        {
            "price_adjustment_mode": mode,
            "adjusted_ohlc_available": adjusted_group is not None,
            "price_fields": {"open": open_field, "high": high_field, "low": low_field, "close": close_field},
        },
    )


def _volume_ratio(volumes: list[float], index: int) -> float | None:
    if index < 0 or index >= len(volumes) or not math.isfinite(volumes[index]):
        return None
    baseline = [value for value in volumes[max(0, index - 20) : max(0, index - 5)] if math.isfinite(value) and value > 0]
    if not baseline:
        baseline = [value for value in volumes[max(0, index - 10) : index] if math.isfinite(value) and value > 0]
    avg = _mean(baseline)
    if avg is None or avg <= 0:
        return None
    return volumes[index] / avg


def _consecutive_up_days(closes: list[float]) -> int:
    count = 0
    for previous, current in zip(reversed(closes[:-1]), reversed(closes[1:]), strict=False):
        if math.isfinite(previous) and math.isfinite(current) and current > previous:
            count += 1
            continue
        break
    return count


def _evidence_refs(rows: list[dict[str, Any]], limit: int = 16) -> list[Any]:
    refs: list[Any] = []
    for row in rows:
        value = row.get("raw_payload_id")
        if value in (None, ""):
            continue
        ref: Any
        try:
            ref = int(value)
        except (TypeError, ValueError):
            ref = str(value)
        if ref not in refs:
            refs.append(ref)
    return refs[-limit:]


def _instrument_gap_codes(instrument: dict[str, Any]) -> list[str]:
    gaps: list[str] = []
    exchange = str(instrument.get("exchange") or "")
    asset_type = str(instrument.get("asset_type") or "A_SHARE")
    if exchange and exchange not in OFFICIAL_EXCHANGES:
        gaps.append("not_shenzhen_a_share_scope")
    if asset_type not in OFFICIAL_ASSET_TYPES:
        gaps.append("not_a_share_scope")
    if instrument.get("is_st") or instrument.get("is_special_treatment"):
        gaps.append("special_treatment_stock")
    if instrument.get("is_suspended"):
        gaps.append("suspended_stock")
    if instrument.get("is_delisting_risk"):
        gaps.append("delisting_risk_stock")
    if instrument.get("is_active") is False:
        gaps.append("inactive_instrument")
    return gaps


def _weekly_structure_score(weekly_bars: list[dict[str, Any]], as_of_trading_day: date) -> tuple[Decimal | None, Decimal, list[str], dict[str, Any]]:
    rows = _bars_until(weekly_bars, as_of_trading_day)[-16:]
    if len(rows) < 8:
        return None, Decimal("0.000000"), ["weekly_context_missing"], {}
    channels, metadata = _price_arrays(rows, prefer_adjusted=True)
    highs = channels["high"]
    lows = channels["low"]
    closes = channels["close"]
    if not all(math.isfinite(value) and value > 0 for value in highs + lows + closes):
        return None, Decimal("0.000000"), ["weekly_context_invalid"], {}
    max_high = max(highs)
    min_low = min(lows)
    weekly_drawdown = (max_high - min_low) / max_high if max_high > 0 else 0.0
    drawdown_maturity = _score((weekly_drawdown - 0.08) / 0.32 * 100.0)
    log_closes = [math.log(value) for value in closes if value > 0]
    slope_4 = _linear_slope(log_closes[-4:])
    slope_12 = _linear_slope(log_closes[-12:]) if len(log_closes) >= 12 else _linear_slope(log_closes)
    slope_repair = _score(50.0 + (slope_4 - slope_12) * 3500.0)
    returns = _returns(closes)
    rv_short = _std(returns[-4:]) if len(returns) >= 4 else 0.0
    rv_long = _std(returns[-12:]) if len(returns) >= 12 else _std(returns)
    volatility_compression = _score(100.0 if rv_long > 0 and rv_short < rv_long else 45.0)
    support_stability = _score(100.0 if min(lows[-4:]) >= min_low * 0.985 else 35.0)
    score = _score(
        float(drawdown_maturity) * 0.35
        + float(slope_repair) * 0.30
        + float(volatility_compression) * 0.20
        + float(support_stability) * 0.15
    )
    bear_pressure = _score(max(0.0, -slope_12) * 5000.0)
    return score, bear_pressure, ([] if metadata["adjusted_ohlc_available"] else ["weekly_adjusted_ohlc_missing"]), {
        "weekly_drawdown_pct": _pct(weekly_drawdown),
        "weekly_slope_4w": _ratio(slope_4),
        "weekly_slope_12w": _ratio(slope_12),
        "weekly_slope_repair_score": slope_repair,
        "weekly_volatility_compression_score": volatility_compression,
        "weekly_support_stability_score": support_stability,
    }


def _select_valley_window(
    *,
    bars: list[dict[str, Any]],
    as_of_trading_day: date,
    window_days: int,
) -> tuple[list[dict[str, Any]], dict[str, list[float]], dict[str, Any], list[str]]:
    rows = _bars_until(bars, as_of_trading_day)[-window_days:]
    source_gap_codes: list[str] = []
    required_count = math.ceil(window_days * float(MIN_DAILY_COMPLETENESS))
    if len(rows) < required_count:
        source_gap_codes.append("daily_bar_incomplete")
    channels, metadata = _price_arrays(rows, prefer_adjusted=True)
    if not metadata["adjusted_ohlc_available"]:
        source_gap_codes.append("adjusted_ohlc_missing_research_only")
    required = channels["open"] + channels["high"] + channels["low"] + channels["close"]
    if not rows or not all(math.isfinite(value) and value > 0 for value in required):
        source_gap_codes.append("price_channel_invalid")
    return rows, channels, metadata, source_gap_codes


def _valley_metrics(
    *,
    rows: list[dict[str, Any]],
    channels: dict[str, list[float]],
) -> dict[str, Any]:
    highs = channels["high"]
    lows = channels["low"]
    closes = channels["close"]
    volumes = channels["volume"]
    amounts = channels["amount"]
    close_positions = channels["close_position"]
    upper_shadows = channels["upper_shadow_ratio"]
    max_high = max(highs)
    trough_index = min(range(len(lows)), key=lambda idx: lows[idx])
    trough_low = lows[trough_index]
    today_close = closes[-1]
    drawdown = _safe_divide(max_high - trough_low, max_high)
    distance_from_low = _safe_divide(today_close - trough_low, trough_low)
    trough_age_days = len(rows) - 1 - trough_index
    trough_position_ratio = _safe_divide(float(trough_index), max(1.0, float(len(rows) - 1)))

    drawdown_depth_score = _score((drawdown - 0.08) / 0.32 * 100.0)
    drawdown_duration_score = _score(min(100.0, trough_position_ratio / 0.72 * 100.0))
    valley_depth_score = _score(float(drawdown_depth_score) * 0.60 + float(drawdown_duration_score) * 0.40)

    log_closes = [math.log(value) for value in closes if value > 0]
    slope_20 = _linear_slope(log_closes[-20:]) if len(log_closes) >= 20 else _linear_slope(log_closes)
    slope_5 = _linear_slope(log_closes[-5:]) if len(log_closes) >= 5 else _linear_slope(log_closes)
    downtrend_deceleration_score = _score(50.0 + (slope_5 - slope_20) * 3500.0)

    post_lows = lows[trough_index:]
    post_closes = closes[trough_index:]
    local_low_points: list[float] = []
    for idx in range(1, len(post_lows) - 1):
        if post_lows[idx] <= post_lows[idx - 1] and post_lows[idx] <= post_lows[idx + 1]:
            local_low_points.append(post_lows[idx])
    higher_low_count = sum(
        1 for prev, cur in zip(local_low_points, local_low_points[1:], strict=False) if cur >= prev * 1.005
    )
    no_new_low_score = _score(100.0 if min(post_lows) >= trough_low * 0.985 else 20.0)
    support_hold_score = _score(sum(1 for value in post_lows if value >= trough_low * 0.985) / max(1, len(post_lows)) * 100.0)
    higher_low_score = _score(70.0 + min(30.0, higher_low_count * 10.0)) if local_low_points else _score(55.0)
    break_low_penalty = _score(100.0 if min(lows[-3:]) < trough_low * 0.985 else 0.0)
    support_stability_score = _score(
        float(no_new_low_score) * 0.40
        + float(higher_low_score) * 0.35
        + float(support_hold_score) * 0.25
        - float(break_low_penalty) * 0.40
    )

    returns = _returns(closes)
    rv10 = _std(returns[-10:]) if len(returns) >= 10 else _std(returns)
    rv40 = _std(returns[-40:]) if len(returns) >= 40 else _std(returns)
    volatility_ratio = _safe_divide(rv10, rv40, default=1.0)
    volatility_compression_score = _score((1.20 - volatility_ratio) / 0.70 * 100.0)

    avg_volume_20 = _mean([value for value in volumes[-20:] if math.isfinite(value) and value > 0])
    avg_volume_5 = _mean([value for value in volumes[-5:] if math.isfinite(value) and value > 0])
    volume_compression_ratio = _safe_divide(avg_volume_5 or 0.0, avg_volume_20 or 0.0, default=1.0)
    volume_exhaustion_score = _score((1.15 - volume_compression_ratio) / 0.65 * 100.0)
    today_volume_ratio = _safe_divide(volumes[-1], avg_volume_20 or 0.0, default=1.0)
    mild_recovery_score = _score(100.0 if 0.85 <= today_volume_ratio <= 2.50 else 45.0)
    abnormal_spike_risk = _score((today_volume_ratio - 2.80) / 2.20 * 100.0)
    volume_structure_score = _score(
        float(volume_exhaustion_score) * 0.45
        + float(mild_recovery_score) * 0.35
        - float(abnormal_spike_risk) * 0.30
    )

    close_position_today = close_positions[-1]
    upper_shadow_today = upper_shadows[-1]
    weak_close_risk = _score((1.0 - close_position_today) * 100.0 if math.isfinite(close_position_today) else 100.0)
    upper_shadow_risk = _score(upper_shadow_today * 100.0 if math.isfinite(upper_shadow_today) else 100.0)
    volume_spike_weak_close = _score(today_volume_ratio * float(weak_close_risk) / 2.5)
    average_amount_20 = Decimal(str(_mean([value for value in amounts[-20:] if math.isfinite(value) and value > 0]) or 0.0))
    liquidity_risk = _score(100.0 if average_amount_20 < MIN_AMOUNT_20D else 0.0)
    break_low_frequency = _score(100.0 if min(lows[-5:]) < trough_low * 0.985 else 0.0)

    return {
        "trough_index": trough_index,
        "primary_trough_day": _as_date(rows[trough_index].get("trading_day")),
        "primary_trough_low": Decimal(str(trough_low)).quantize(Decimal("0.000001")),
        "primary_trough_age_days": trough_age_days,
        "trough_position_ratio": _ratio(trough_position_ratio),
        "drawdown_pct": _pct(drawdown),
        "distance_from_low_pct": _pct(distance_from_low),
        "valley_depth_score": valley_depth_score,
        "drawdown_depth_score": drawdown_depth_score,
        "drawdown_duration_score": drawdown_duration_score,
        "downtrend_deceleration_score": downtrend_deceleration_score,
        "support_stability_score": support_stability_score,
        "support_hold_score": support_hold_score,
        "higher_low_score": higher_low_score,
        "break_low_penalty": break_low_penalty,
        "volatility_compression_score": volatility_compression_score,
        "volatility_ratio": _ratio(volatility_ratio),
        "volume_structure_score": volume_structure_score,
        "volume_exhaustion_score": volume_exhaustion_score,
        "mild_recovery_score": mild_recovery_score,
        "abnormal_spike_risk": abnormal_spike_risk,
        "today_volume_ratio": _ratio(today_volume_ratio),
        "weak_close_risk": weak_close_risk,
        "upper_shadow_risk": upper_shadow_risk,
        "volume_spike_weak_close": volume_spike_weak_close,
        "liquidity_risk": liquidity_risk,
        "break_low_frequency": break_low_frequency,
        "average_amount_20": average_amount_20.quantize(Decimal("0.000001")),
        "close_position_today": _ratio(close_position_today),
        "consecutive_up_days": _consecutive_up_days(closes),
    }


def build_phase2_valley_watch_pool(
    *,
    instrument: dict[str, Any],
    bars: list[dict[str, Any]],
    as_of_trading_day: date,
    weekly_bars: list[dict[str, Any]] | None = None,
    recall_result: dict[str, Any] | None = None,
    pattern_match: dict[str, Any] | None = None,
    as_of_time: datetime | None = None,
    window_days: int = 60,
) -> dict[str, Any]:
    """Create a formal valley-watch-pool fact from Phase 1 recall and audited OHLCV features.

    This function is intentionally stricter than the earlier research helper in logic.py.
    All components have explicit financial purpose, data policy and formula governance metadata.
    """

    effective_time = as_of_time or datetime.now(timezone.utc)
    symbol = str(instrument.get("symbol") or "").zfill(6)
    source_gap_codes = _instrument_gap_codes(instrument)
    rows, channels, metadata, data_gaps = _select_valley_window(
        bars=bars,
        as_of_trading_day=as_of_trading_day,
        window_days=window_days,
    )
    source_gap_codes.extend(data_gaps)
    if "price_channel_invalid" in source_gap_codes or not rows:
        result = {
            "symbol": symbol,
            "as_of_trading_day": as_of_trading_day,
            "trade_date": as_of_trading_day,
            "pool_state": "data_blocked",
            "valley_status": "data_blocked",
            "source_gap_codes": sorted(set(source_gap_codes or ["daily_bar_missing"])),
            "block_reason_codes": ["p0_price_data_invalid"],
            "formula_version": PHASE2_FORMULA_VERSION,
            "calculated_at": effective_time,
        }
        result["payload_hash"] = _hash(result)
        return result

    metrics = _valley_metrics(rows=rows, channels=channels)
    weekly_score, weekly_bear_pressure, weekly_gaps, weekly_components = _weekly_structure_score(
        weekly_bars or [],
        as_of_trading_day,
    )
    source_gap_codes.extend(weekly_gaps)
    pattern_match = pattern_match or (recall_result or {}).get("pattern_match") or {}
    shape_edge = _decimal(pattern_match.get("shape_edge_score") or (recall_result or {}).get("shape_edge_score"))
    hard_negative_similarity = _decimal(pattern_match.get("hard_negative_similarity")) or Decimal("0")
    false_bottom_similarity = _decimal(pattern_match.get("false_bottom_similarity")) or Decimal("0")
    pattern_match_score = _score(shape_edge) if shape_edge is not None else None
    if pattern_match_score is None:
        source_gap_codes.append("pattern_match_missing")
        pattern_match_score = Decimal("0")

    weekly_score_for_calc = weekly_score if weekly_score is not None else Decimal("45")
    valley_maturity_score = _score(
        float(metrics["valley_depth_score"]) * 0.20
        + float(metrics["downtrend_deceleration_score"]) * 0.15
        + float(metrics["support_stability_score"]) * 0.15
        + float(metrics["volatility_compression_score"]) * 0.10
        + float(metrics["volume_structure_score"]) * 0.10
        + float(weekly_score_for_calc) * 0.15
        + float(pattern_match_score) * 0.15
    )
    false_rebound_risk = _score(
        float(weekly_bear_pressure) * 0.20
        + float(metrics["break_low_frequency"]) * 0.18
        + float(metrics["volume_spike_weak_close"]) * 0.18
        + float(metrics["upper_shadow_risk"]) * 0.15
        + float(false_bottom_similarity) * 0.12
        + float(hard_negative_similarity) * 0.10
        + float(metrics["liquidity_risk"]) * 0.07
    )

    block_reason_codes: list[str] = []
    research_only_reason_codes: list[str] = []
    drawdown_pct = metrics["drawdown_pct"] or Decimal("0")
    distance_from_low_pct = metrics["distance_from_low_pct"] or Decimal("999")
    if drawdown_pct < Decimal("8"):
        block_reason_codes.append("drawdown_not_deep_enough")
    if drawdown_pct > Decimal("55"):
        research_only_reason_codes.append("drawdown_too_deep_basic_risk_review_required")
    if distance_from_low_pct > Decimal("12"):
        block_reason_codes.append("too_far_from_primary_trough")
    if metrics["break_low_penalty"] >= Decimal("70"):
        block_reason_codes.append("support_recently_broken")
    if hard_negative_similarity >= Decimal("75") and (shape_edge is None or shape_edge < Decimal("25")):
        block_reason_codes.append("hard_negative_similarity_dominates")
    if false_rebound_risk >= Decimal("75"):
        block_reason_codes.append("false_rebound_risk_too_high")
    if metadata["price_adjustment_mode"] != "adjusted_ohlc":
        research_only_reason_codes.append("adjusted_ohlc_required_for_official_scoring")
    if "weekly_context_missing" in source_gap_codes:
        research_only_reason_codes.append("weekly_context_missing")
    if "pattern_match_missing" in source_gap_codes:
        research_only_reason_codes.append("pattern_match_missing")
    if any(code in source_gap_codes for code in ("not_shenzhen_a_share_scope", "not_a_share_scope", "special_treatment_stock", "suspended_stock", "delisting_risk_stock", "inactive_instrument")):
        block_reason_codes.append("instrument_scope_or_tradability_blocked")

    if any(code in source_gap_codes for code in ("daily_bar_incomplete", "price_channel_invalid")):
        pool_state = "data_blocked"
    elif block_reason_codes:
        pool_state = "valley_invalidated"
    elif valley_maturity_score >= Decimal("62") and false_rebound_risk <= Decimal("68"):
        pool_state = "research_only" if research_only_reason_codes else "valley_watch"
    else:
        pool_state = "not_qualified"

    result = {
        "symbol": symbol,
        "instrument_id": int(instrument.get("instrument_id") or 0),
        "as_of_trading_day": as_of_trading_day,
        "trade_date": as_of_trading_day,
        "calculated_at": effective_time,
        "phase2_version": AMBUSH_PHASE2_VERSION,
        "formula_version": PHASE2_FORMULA_VERSION,
        "pattern_library_version": pattern_match.get("pattern_library_version") or AMBUSH_PATTERN_LIBRARY_VERSION,
        "window_days": window_days,
        "pool_state": pool_state,
        "valley_status": pool_state,
        "primary_trough_day": metrics["primary_trough_day"],
        "primary_trough_low": metrics["primary_trough_low"],
        "primary_trough_age_days": metrics["primary_trough_age_days"],
        "drawdown_pct": metrics["drawdown_pct"],
        "distance_from_low_pct": metrics["distance_from_low_pct"],
        "price_adjustment_mode": metadata["price_adjustment_mode"],
        "valley_maturity_score": valley_maturity_score,
        "pattern_match_score": pattern_match_score,
        "weekly_structure_score": weekly_score,
        "false_rebound_risk": false_rebound_risk,
        "hard_negative_similarity": hard_negative_similarity,
        "false_bottom_similarity": false_bottom_similarity,
        "valley_components": {
            "valley_depth_score": metrics["valley_depth_score"],
            "drawdown_depth_score": metrics["drawdown_depth_score"],
            "drawdown_duration_score": metrics["drawdown_duration_score"],
            "downtrend_deceleration_score": metrics["downtrend_deceleration_score"],
            "support_stability_score": metrics["support_stability_score"],
            "volatility_compression_score": metrics["volatility_compression_score"],
            "volume_structure_score": metrics["volume_structure_score"],
            "weekly_structure_score": weekly_score,
            "pattern_match_score": pattern_match_score,
        },
        "risk_components": {
            "weekly_bear_pressure": weekly_bear_pressure,
            "break_low_frequency": metrics["break_low_frequency"],
            "volume_spike_weak_close": metrics["volume_spike_weak_close"],
            "upper_shadow_risk": metrics["upper_shadow_risk"],
            "false_bottom_similarity": false_bottom_similarity,
            "hard_negative_similarity": hard_negative_similarity,
            "liquidity_risk": metrics["liquidity_risk"],
        },
        "market_structure_context": weekly_components,
        "source_gap_codes": sorted(set(source_gap_codes)),
        "block_reason_codes": sorted(set(block_reason_codes)),
        "research_only_reason_codes": sorted(set(research_only_reason_codes)),
        "evidence_refs": _evidence_refs(rows),
        "formula_governance": {
            "formula_code": "ambush_phase2_valley_maturity_score_v1",
            "formula_version": PHASE2_FORMULA_VERSION,
            "financial_purpose": "Judge whether a low-valley structure is mature enough for observation before effective-turn detection.",
            "data_policy": "Official calculation requires adjusted OHLC for shape/structure; raw prices are research-only. Uses only bars with trading_day <= as_of_trading_day.",
            "validation_policy": "Must be validated by positive/hard-negative bucket tests, walk-forward replay, and later outcome calibration before release-gate promotion.",
            "not_a_signal": True,
        },
    }
    result["payload_hash"] = _hash(result)
    return result


def _detect_horizontal_compression_breakout(
    rows: list[dict[str, Any]],
    channels: dict[str, list[float]],
    trough_index: int,
) -> dict[str, Any] | None:
    highs = channels["high"]
    lows = channels["low"]
    closes = channels["close"]
    volumes = channels["volume"]
    close_positions = channels["close_position"]
    today_index = len(rows) - 1
    trough_age = today_index - trough_index
    if trough_age < 7 or trough_age > 15:
        return None
    trough_low = lows[trough_index]
    today_close = closes[-1]
    post_trough_return = _safe_divide(today_close - trough_low, trough_low)
    if post_trough_return > 0.12:
        return None
    compression_start = max(trough_index + 1, today_index - 8)
    compression_highs = highs[compression_start:today_index]
    compression_lows = lows[compression_start:today_index]
    if len(compression_highs) < 4:
        return None
    compression_low = min(compression_lows)
    compression_high = max(compression_highs)
    compression_range = _safe_divide(compression_high - compression_low, compression_low)
    volume_ratio = _volume_ratio(volumes, today_index)
    if (
        compression_range <= 0.08
        and today_close > compression_high * 0.995
        and volume_ratio is not None
        and 1.05 <= volume_ratio <= 2.80
        and close_positions[-1] >= 0.62
        and lows[-1] >= trough_low * 0.985
    ):
        return {
            "anchor_index": today_index,
            "anchor_type": "horizontal_compression_breakout",
            "compression_start_day": _as_date(rows[compression_start].get("trading_day")),
            "compression_range_pct": _pct(compression_range),
            "volume_ratio": volume_ratio,
        }
    return None


def _detect_fresh_turn_anchor(rows: list[dict[str, Any]], channels: dict[str, list[float]], trough_index: int) -> dict[str, Any] | None:
    highs = channels["high"]
    lows = channels["low"]
    closes = channels["close"]
    volumes = channels["volume"]
    close_positions = channels["close_position"]
    upper_shadows = channels["upper_shadow_ratio"]
    trough_low = lows[trough_index]
    today_index = len(rows) - 1
    candidates: list[dict[str, Any]] = []
    for idx in range(max(trough_index + 1, today_index - 3), today_index + 1):
        if idx <= 0:
            continue
        close_t = closes[idx]
        prev_close = closes[idx - 1]
        if not all(math.isfinite(value) and value > 0 for value in (close_t, prev_close, lows[idx])):
            continue
        ma5 = _mean(closes[max(0, idx - 4) : idx + 1]) or close_t
        volume_ratio = _volume_ratio(volumes, idx)
        prior_high = max(highs[max(0, idx - 5) : idx]) if idx > 0 else close_t
        micro_breakout = close_t >= prior_high * 0.995
        effective_age = today_index - idx
        close_strength = close_positions[idx]
        if (
            close_t > prev_close
            and close_strength >= 0.60
            and close_t >= ma5 * 0.995
            and lows[idx] >= trough_low * 0.985
            and volume_ratio is not None
            and 0.80 <= volume_ratio <= 2.50
            and upper_shadows[idx] <= 0.35
        ):
            anchor_type = "first_turn_day" if idx - trough_index <= 2 else "second_turn_day"
            candidates.append(
                {
                    "anchor_index": idx,
                    "anchor_type": anchor_type,
                    "micro_breakout": micro_breakout,
                    "effective_turn_age_days": effective_age,
                    "volume_ratio": volume_ratio,
                    "close_strength": close_strength,
                }
            )
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item["micro_breakout"], -item["effective_turn_age_days"], item["close_strength"]))


def build_phase2_effective_turn_anchor(
    *,
    instrument: dict[str, Any],
    bars: list[dict[str, Any]],
    as_of_trading_day: date,
    valley_watch: dict[str, Any] | None = None,
    weekly_bars: list[dict[str, Any]] | None = None,
    recall_result: dict[str, Any] | None = None,
    pattern_match: dict[str, Any] | None = None,
    as_of_time: datetime | None = None,
    window_days: int = 60,
) -> dict[str, Any]:
    effective_time = as_of_time or datetime.now(timezone.utc)
    symbol = str(instrument.get("symbol") or "").zfill(6)
    if valley_watch is None:
        valley_watch = build_phase2_valley_watch_pool(
            instrument=instrument,
            bars=bars,
            weekly_bars=weekly_bars or [],
            recall_result=recall_result,
            pattern_match=pattern_match,
            as_of_trading_day=as_of_trading_day,
            as_of_time=effective_time,
            window_days=window_days,
        )
    rows, channels, metadata, source_gap_codes = _select_valley_window(
        bars=bars,
        as_of_trading_day=as_of_trading_day,
        window_days=int(valley_watch.get("window_days") or window_days),
    )
    source_gap_codes.extend(valley_watch.get("source_gap_codes") or [])
    reject_reason_codes: list[str] = []
    if valley_watch.get("pool_state") not in {"valley_watch", "research_only"}:
        reject_reason_codes.append("valley_pool_state_not_eligible")
    if not rows or "price_channel_invalid" in source_gap_codes:
        reject_reason_codes.append("p0_price_data_invalid")
    if reject_reason_codes:
        result = {
            "symbol": symbol,
            "as_of_trading_day": as_of_trading_day,
            "trade_date": as_of_trading_day,
            "l1_status": "rejected",
            "pool_target": "remain_valley_watch_pool" if valley_watch.get("pool_state") == "valley_watch" else "none",
            "reject_reason_codes": sorted(set(reject_reason_codes)),
            "source_gap_codes": sorted(set(source_gap_codes)),
            "formula_version": PHASE2_FORMULA_VERSION,
            "calculated_at": effective_time,
        }
        result["payload_hash"] = _hash(result)
        return result

    metrics = _valley_metrics(rows=rows, channels=channels)
    trough_day = _as_date(valley_watch.get("primary_trough_day")) or metrics["primary_trough_day"]
    trough_index = next(
        (idx for idx, row in enumerate(rows) if _as_date(row.get("trading_day")) == trough_day),
        int(metrics["trough_index"]),
    )
    compression_anchor = _detect_horizontal_compression_breakout(rows, channels, trough_index)
    fresh_anchor = _detect_fresh_turn_anchor(rows, channels, trough_index)
    anchor = compression_anchor or fresh_anchor
    if anchor is None:
        reject_reason_codes.append("no_effective_turn_anchor")
        result = {
            "symbol": symbol,
            "instrument_id": int(instrument.get("instrument_id") or 0),
            "as_of_trading_day": as_of_trading_day,
            "trade_date": as_of_trading_day,
            "l1_status": "rejected",
            "pool_target": "remain_valley_watch_pool",
            "reject_reason_codes": reject_reason_codes,
            "source_gap_codes": sorted(set(source_gap_codes)),
            "primary_trough_day": trough_day,
            "formula_version": PHASE2_FORMULA_VERSION,
            "calculated_at": effective_time,
            "formula_governance": {
                "formula_code": "ambush_phase2_effective_turn_anchor_v1",
                "formula_version": PHASE2_FORMULA_VERSION,
                "financial_purpose": "Detect first/second effective turn or post-valley horizontal-compression breakout without using future bars.",
                "not_a_signal": True,
            },
        }
        result["payload_hash"] = _hash(result)
        return result

    highs = channels["high"]
    lows = channels["low"]
    closes = channels["close"]
    volumes = channels["volume"]
    close_positions = channels["close_position"]
    upper_shadows = channels["upper_shadow_ratio"]
    anchor_idx = int(anchor["anchor_index"])
    anchor_day = _as_date(rows[anchor_idx].get("trading_day")) or as_of_trading_day
    today_idx = len(rows) - 1
    effective_age = today_idx - anchor_idx
    trough_low = lows[trough_index]
    close_anchor = closes[anchor_idx]
    close_today = closes[-1]
    post_turn_return = _safe_divide(close_today - close_anchor, close_anchor)
    post_trough_return = _safe_divide(close_today - trough_low, trough_low)
    consecutive_up = _consecutive_up_days(closes)
    volume_ratio = anchor.get("volume_ratio") if anchor.get("volume_ratio") is not None else _volume_ratio(volumes, anchor_idx)
    close_strength = anchor.get("close_strength") if anchor.get("close_strength") is not None else close_positions[anchor_idx]
    support_not_broken = min(lows[trough_index:]) >= trough_low * 0.985
    upper_shadow_risk = _score(upper_shadows[anchor_idx] * 100.0 if math.isfinite(upper_shadows[anchor_idx]) else 100.0)
    micro_breakout_quality = _score(100.0 if anchor.get("micro_breakout") or anchor["anchor_type"] == "horizontal_compression_breakout" else 55.0)
    effective_age_score = _score({0: 70, 1: 100, 2: 95, 3: 70}.get(effective_age, 20))
    post_turn_room_score = _score(100.0 - post_turn_return / 0.06 * 100.0)
    close_strength_score = _score(close_strength * 100.0)
    gentle_volume_recovery_score = _score(100.0 if volume_ratio is not None and 0.80 <= volume_ratio <= 2.50 else 45.0)
    support_hold_score = _score(100.0 if support_not_broken else 20.0)
    runaway_risk = _score(
        max(0.0, post_trough_return - 0.08) / 0.12 * 60.0
        + max(0, consecutive_up - 3) / 5.0 * 40.0
    )
    turn_freshness_score = _score(
        float(effective_age_score) * 0.35
        + float(post_turn_room_score) * 0.25
        + float(close_strength_score) * 0.20
        + float(micro_breakout_quality) * 0.20
        - float(runaway_risk) * 0.30
    )
    effective_turn_score = _score(
        float(turn_freshness_score) * 0.35
        + float(micro_breakout_quality) * 0.20
        + float(close_strength_score) * 0.15
        + float(support_hold_score) * 0.15
        + float(gentle_volume_recovery_score) * 0.15
        - float(upper_shadow_risk) * 0.12
    )

    primary_trough_age_days = today_idx - trough_index
    compression_breakout = anchor["anchor_type"] == "horizontal_compression_breakout"
    if effective_age > 2 and not compression_breakout:
        reject_reason_codes.append("turn_not_fresh")
    if post_turn_return > 0.06:
        reject_reason_codes.append("post_turn_return_too_high")
    if post_trough_return > 0.16:
        reject_reason_codes.append("runaway_from_trough")
    if primary_trough_age_days > 8 and not compression_breakout:
        reject_reason_codes.append("late_rebound_without_compression_breakout")
    if not support_not_broken:
        reject_reason_codes.append("support_not_held")
    if upper_shadow_risk >= Decimal("55"):
        reject_reason_codes.append("upper_shadow_risk_high")
    if valley_watch.get("false_rebound_risk") is not None and _decimal(valley_watch.get("false_rebound_risk")) >= Decimal("75"):
        reject_reason_codes.append("false_rebound_risk_too_high")

    if reject_reason_codes:
        l1_status = "rejected"
        pool_target = "remain_valley_watch_pool"
    elif valley_watch.get("pool_state") == "research_only":
        l1_status = "backup_only"
        pool_target = "effective_turn_pool_research_only"
    elif effective_age <= 2 or compression_breakout:
        l1_status = "accepted"
        pool_target = "effective_turn_pool"
    else:
        l1_status = "backup_only"
        pool_target = "effective_turn_pool_research_only"

    result = {
        "symbol": symbol,
        "instrument_id": int(instrument.get("instrument_id") or 0),
        "as_of_trading_day": as_of_trading_day,
        "trade_date": as_of_trading_day,
        "calculated_at": effective_time,
        "phase2_version": AMBUSH_PHASE2_VERSION,
        "formula_version": PHASE2_FORMULA_VERSION,
        "price_adjustment_mode": metadata["price_adjustment_mode"],
        "l1_status": l1_status,
        "pool_target": pool_target,
        "anchor_type": anchor["anchor_type"],
        "effective_turn_anchor_day": anchor_day,
        "effective_turn_age_days": effective_age,
        "primary_trough_day": trough_day,
        "primary_trough_age_days": primary_trough_age_days,
        "post_turn_return_pct": _pct(post_turn_return),
        "post_trough_return_pct": _pct(post_trough_return),
        "consecutive_up_days": consecutive_up,
        "close_strength": _ratio(close_strength),
        "volume_ratio": _ratio(volume_ratio),
        "turn_freshness_score": turn_freshness_score,
        "effective_turn_score": effective_turn_score,
        "micro_breakout_quality": micro_breakout_quality,
        "support_hold_score": support_hold_score,
        "gentle_volume_recovery_score": gentle_volume_recovery_score,
        "runaway_risk": runaway_risk,
        "upper_shadow_risk": upper_shadow_risk,
        "compression_start_day": anchor.get("compression_start_day"),
        "compression_range_pct": anchor.get("compression_range_pct"),
        "reject_reason_codes": sorted(set(reject_reason_codes)),
        "source_gap_codes": sorted(set(source_gap_codes)),
        "evidence_refs": _evidence_refs(rows[max(0, trough_index - 3) :]),
        "formula_governance": {
            "formula_code": "ambush_phase2_effective_turn_anchor_v1",
            "formula_version": PHASE2_FORMULA_VERSION,
            "financial_purpose": "Promote a mature valley to effective-turn pool only when the first/second turn is fresh or a low-after-compression breakout resets the anchor.",
            "data_policy": "Uses only bars up to as_of_trading_day. Historical future rebound labels are not allowed here.",
            "validation_policy": "Validate with hard-negative lookalikes, late-runaway exclusion, and horizontal-compression success buckets.",
            "not_a_signal": True,
        },
    }
    result["payload_hash"] = _hash(result)
    return result


def build_phase2_pool_transition_audit(
    *,
    instrument: dict[str, Any],
    valley_watch: dict[str, Any],
    effective_turn_anchor: dict[str, Any],
    as_of_time: datetime | None = None,
    created_by_job: str = "ambush_phase2_pool_transition_job",
) -> dict[str, Any]:
    effective_time = as_of_time or datetime.now(timezone.utc)
    symbol = str(instrument.get("symbol") or valley_watch.get("symbol") or effective_turn_anchor.get("symbol") or "").zfill(6)
    can_transfer = valley_watch.get("pool_state") in {"valley_watch", "research_only"} and effective_turn_anchor.get("l1_status") in {"accepted", "backup_only"}
    if not can_transfer:
        decision_result = "not_created"
        to_pool = "none"
    elif effective_turn_anchor.get("l1_status") == "accepted" and valley_watch.get("pool_state") == "valley_watch":
        decision_result = "created"
        to_pool = "effective_turn_pool"
    else:
        decision_result = "research_only"
        to_pool = "effective_turn_pool_research_only"
    result = {
        "symbol": symbol,
        "instrument_id": int(instrument.get("instrument_id") or valley_watch.get("instrument_id") or 0),
        "from_pool": "valley_watch_pool",
        "to_pool": to_pool,
        "from_status": valley_watch.get("pool_state"),
        "to_status": effective_turn_anchor.get("l1_status"),
        "decision_result": decision_result,
        "trigger_event": "effective_turn_anchor_detected" if can_transfer else "effective_turn_anchor_not_eligible",
        "trigger_as_of_time": effective_time,
        "trigger_snapshot_type": "close_confirmed",
        "trigger_feature_json": {
            "as_of_trading_day": effective_turn_anchor.get("as_of_trading_day"),
            "effective_turn_anchor_day": effective_turn_anchor.get("effective_turn_anchor_day"),
            "anchor_type": effective_turn_anchor.get("anchor_type"),
            "turn_freshness_score": effective_turn_anchor.get("turn_freshness_score"),
            "effective_turn_score": effective_turn_anchor.get("effective_turn_score"),
            "reject_reason_codes": effective_turn_anchor.get("reject_reason_codes") or [],
        },
        "decision_rule_version": PHASE2_FORMULA_VERSION,
        "created_by_job": created_by_job,
        "evidence_refs": list(dict.fromkeys((valley_watch.get("evidence_refs") or []) + (effective_turn_anchor.get("evidence_refs") or []))),
        "calculated_at": effective_time,
        "formula_governance": {
            "formula_code": "ambush_phase2_pool_transition_audit_v1",
            "formula_version": PHASE2_FORMULA_VERSION,
            "financial_purpose": "Create an auditable fact when a stock moves from valley watch to effective-turn pool.",
            "not_a_signal": True,
        },
    }
    result["transition_hash"] = _hash(result)
    result["payload_hash"] = result["transition_hash"]
    return result


def build_phase2_valley_turn_pipeline(
    *,
    instrument: dict[str, Any],
    bars: list[dict[str, Any]],
    as_of_trading_day: date,
    weekly_bars: list[dict[str, Any]] | None = None,
    recall_result: dict[str, Any] | None = None,
    pattern_match: dict[str, Any] | None = None,
    as_of_time: datetime | None = None,
    window_days: int = 60,
) -> dict[str, Any]:
    effective_time = as_of_time or datetime.now(timezone.utc)
    valley = build_phase2_valley_watch_pool(
        instrument=instrument,
        bars=bars,
        weekly_bars=weekly_bars or [],
        recall_result=recall_result,
        pattern_match=pattern_match,
        as_of_trading_day=as_of_trading_day,
        as_of_time=effective_time,
        window_days=window_days,
    )
    turn = build_phase2_effective_turn_anchor(
        instrument=instrument,
        bars=bars,
        weekly_bars=weekly_bars or [],
        recall_result=recall_result,
        pattern_match=pattern_match,
        valley_watch=valley,
        as_of_trading_day=as_of_trading_day,
        as_of_time=effective_time,
        window_days=window_days,
    )
    transition = build_phase2_pool_transition_audit(
        instrument=instrument,
        valley_watch=valley,
        effective_turn_anchor=turn,
        as_of_time=effective_time,
    )
    return {
        "phase2_version": AMBUSH_PHASE2_VERSION,
        "formula_version": PHASE2_FORMULA_VERSION,
        "as_of_trading_day": as_of_trading_day,
        "symbol": str(instrument.get("symbol") or "").zfill(6),
        "valley_watch": valley,
        "effective_turn_anchor": turn,
        "transition_audit": transition,
        "not_a_signal": True,
        "calculated_at": effective_time,
    }
