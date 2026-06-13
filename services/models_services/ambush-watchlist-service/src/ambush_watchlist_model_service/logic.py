from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any


DRAGON_MODEL_VERSION = "ambush_watchlist_effective_turn_v1_1"
DRAGON_WINDOWS = (20, 30, 40, 60, 90, 120)
MIN_DAILY_COMPLETENESS = Decimal("0.95")
MIN_AVG_AMOUNT_20D = Decimal("30000000")
EVIDENCE_LEVEL_CAPS: dict[str, Decimal] = {
    "L0_VALLEY_WATCH": Decimal("0"),
    "L1_EFFECTIVE_TURN": Decimal("59"),
    "L2_FILTER_PASSED": Decimal("69"),
    "L3_DEEP_CONFIRMED": Decimal("82"),
    "L4_DRAGON_READY": Decimal("100"),
}
P0_SOURCE_GAP_CODES = {
    "daily_bar_missing",
    "daily_bar_incomplete",
    "daily_bar_completeness_missing",
    "trading_calendar_missing",
    "daily_bar_completeness_below_l4",
    "effective_turn_candidate_missing",
}
L4_BLOCKING_SOURCE_GAP_CODES = P0_SOURCE_GAP_CODES | {
    "moneyflow_missing",
    "deep_capital_probe_missing",
    "market_context_missing",
    "false_reversal_risk_missing",
    "distance_from_trough_missing",
    "dragon_priority_score_missing",
}


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _bar_amount(bar: dict[str, Any]) -> Decimal | None:
    amount = _decimal(bar.get("amount"))
    if amount is not None:
        return amount
    close_price = _decimal(bar.get("close_price"))
    volume = _decimal(bar.get("volume"))
    if close_price is None or volume is None:
        return None
    return close_price * volume


def _float(value: Any, default: float = 0.0) -> float:
    numeric = _decimal(value)
    return float(numeric) if numeric is not None else default


def _score(value: float | Decimal | int | None) -> Decimal:
    if value is None or not math.isfinite(float(value)):
        return Decimal("0.000000")
    numeric = max(0.0, min(100.0, float(value)))
    return Decimal(str(numeric)).quantize(Decimal("0.000001"))


def _weighted_score(parts: list[tuple[Decimal, Decimal | None]]) -> Decimal | None:
    usable = [(weight, value) for weight, value in parts if value is not None]
    if not usable:
        return None
    weight_sum = sum(weight for weight, _ in usable)
    if weight_sum <= 0:
        return None
    return _score(sum(weight * value for weight, value in usable) / weight_sum)


def _ratio(value: float | Decimal | int | None) -> Decimal | None:
    if value is None or not math.isfinite(float(value)):
        return None
    return Decimal(str(float(value))).quantize(Decimal("0.000001"))


def _pct(value: float | Decimal | int | None) -> Decimal:
    if value is None or not math.isfinite(float(value)):
        return Decimal("0.000000")
    return Decimal(str(float(value) * 100.0)).quantize(Decimal("0.000001"))


def _date_value(value: Any) -> date | None:
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


def _as_date(value: Any, fallback: date) -> date:
    return _date_value(value) or fallback


def _close_strength(bar: dict[str, Any]) -> float:
    high = _float(bar.get("high_price"), math.nan)
    low = _float(bar.get("low_price"), math.nan)
    close = _float(bar.get("close_price"), math.nan)
    span = high - low
    if not math.isfinite(span) or span <= 0:
        return 0.0
    return max(0.0, min(1.0, (close - low) / span))


def _upper_shadow_ratio(bar: dict[str, Any]) -> float:
    high = _float(bar.get("high_price"), math.nan)
    low = _float(bar.get("low_price"), math.nan)
    open_price = _float(bar.get("open_price"), math.nan)
    close = _float(bar.get("close_price"), math.nan)
    span = high - low
    if not all(math.isfinite(value) for value in (high, low, open_price, close)) or span <= 0:
        return 1.0
    return max(0.0, high - max(open_price, close)) / span


def _volume_ratio_at(bars: list[dict[str, Any]], index: int) -> float | None:
    volumes = [_float(bar.get("volume"), math.nan) for bar in bars]
    if index < 0 or index >= len(volumes) or not math.isfinite(volumes[index]):
        return None
    baseline_values = [value for value in volumes[max(0, index - 20) : max(0, index - 5)] if math.isfinite(value) and value > 0]
    if not baseline_values:
        baseline_values = [value for value in volumes[max(0, index - 10) : index] if math.isfinite(value) and value > 0]
    if not baseline_values:
        return None
    baseline = sum(baseline_values) / len(baseline_values)
    return volumes[index] / baseline if baseline > 0 else None


def _trading_day_distance(bars: list[dict[str, Any]], anchor_day: date, as_of_trading_day: date) -> int:
    day_values = [_as_date(bar.get("trading_day"), as_of_trading_day) for bar in bars]
    if anchor_day not in day_values:
        return max(0, (as_of_trading_day - anchor_day).days)
    return max(0, len(day_values) - 1 - day_values.index(anchor_day))


def _evidence_refs_from_bars(bars: list[dict[str, Any]], limit: int = 12) -> list[Any]:
    refs: list[Any] = []
    for bar in bars:
        raw_payload_id = bar.get("raw_payload_id")
        if raw_payload_id in (None, ""):
            continue
        ref: Any
        try:
            ref = int(raw_payload_id)
        except (TypeError, ValueError):
            ref = str(raw_payload_id)
        if ref not in refs:
            refs.append(ref)
    return refs[-limit:]


def _mean(values: list[float]) -> float | None:
    clean = [value for value in values if math.isfinite(value)]
    if not clean:
        return None
    return sum(clean) / len(clean)


def _std(values: list[float]) -> float:
    clean = [value for value in values if math.isfinite(value)]
    if len(clean) < 2:
        return 0.0
    avg = sum(clean) / len(clean)
    return math.sqrt(sum((value - avg) ** 2 for value in clean) / len(clean))


def _linear_slope(values: list[float]) -> float:
    clean = [value for value in values if math.isfinite(value)]
    if len(clean) < 2:
        return 0.0
    n = len(clean)
    xs = list(range(n))
    x_avg = (n - 1) / 2.0
    y_avg = sum(clean) / n
    denom = sum((x - x_avg) ** 2 for x in xs)
    if denom <= 0:
        return 0.0
    return sum((x - x_avg) * (clean[x] - y_avg) for x in xs) / denom


def _resample(values: list[float], size: int = 24) -> list[float]:
    clean = [value for value in values if math.isfinite(value)]
    if not clean:
        return []
    if len(clean) == 1:
        return [clean[0]] * size
    result: list[float] = []
    last = len(clean) - 1
    for index in range(size):
        pos = index * last / (size - 1)
        left = int(math.floor(pos))
        right = int(math.ceil(pos))
        if left == right:
            result.append(clean[left])
        else:
            weight = pos - left
            result.append(clean[left] * (1.0 - weight) + clean[right] * weight)
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


def _dtw_distance(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 999.0
    previous = [math.inf] * (len(right) + 1)
    previous[0] = 0.0
    for left_value in left:
        current = [math.inf] * (len(right) + 1)
        for j, right_value in enumerate(right, start=1):
            cost = abs(left_value - right_value)
            current[j] = cost + min(previous[j], current[j - 1], previous[j - 1])
        previous = current
    return previous[-1] / max(len(left), len(right))


def _template_score(values: list[float], kind: str) -> Decimal:
    path = _normalize(_resample(values))
    if len(path) < 3:
        return Decimal("0.000000")
    xs = [index / (len(path) - 1) for index in range(len(path))]
    if kind == "sqrt_right":
        template = [math.sqrt(x) for x in xs]
    else:
        template = [-math.sqrt(max(0.0, 1.0 - x)) for x in xs]
    template = _normalize(template)
    distance = _dtw_distance(path, template)
    return _score(100.0 * math.exp(-distance / 0.18))


def _hash_payload(payload: dict[str, Any]) -> str:
    dumped = json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str)
    return hashlib.sha256(dumped.encode("utf-8")).hexdigest()


def _sorted_bars(bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        [bar for bar in bars if not bar.get("is_partial")],
        key=lambda item: str(item.get("trading_day") or ""),
    )


def _returns(closes: list[float]) -> list[float]:
    result: list[float] = []
    for prev, current in zip(closes, closes[1:], strict=False):
        if prev > 0:
            result.append((current - prev) / prev)
    return result


def calculate_dragon_window_feature(
    *,
    symbol: str,
    bars: list[dict[str, Any]],
    window_days: int,
    as_of_trading_day: date,
    as_of_time: datetime,
) -> dict[str, Any]:
    sorted_bars = _sorted_bars(bars)
    selected = sorted_bars[-window_days:]
    block_reasons: list[str] = []
    required_count = math.ceil(window_days * float(MIN_DAILY_COMPLETENESS))
    if len(selected) < required_count:
        block_reasons.append("blocked_daily_bar_incomplete")
    if window_days not in DRAGON_WINDOWS:
        block_reasons.append("blocked_invalid_window")

    highs = [_float(bar.get("high_price"), math.nan) for bar in selected]
    lows = [_float(bar.get("low_price"), math.nan) for bar in selected]
    opens = [_float(bar.get("open_price"), math.nan) for bar in selected]
    closes = [_float(bar.get("close_price"), math.nan) for bar in selected]
    valid_prices = all(math.isfinite(value) and value > 0 for value in opens + highs + lows + closes)
    if not valid_prices:
        block_reasons.append("blocked_price_data_invalid")

    base_payload: dict[str, Any] = {
        "as_of_trading_day": as_of_trading_day,
        "symbol": symbol,
        "window_days": window_days,
        "trough_trading_day": None,
        "trough_position_ratio": None,
        "drawdown_from_window_high": None,
        "distance_from_trough": None,
        "decline_maturity_score": None,
        "bottom_stabilization_score": None,
        "early_turn_up_score": None,
        "sqrt_right_match_score": None,
        "v_left_bottom_match_score": None,
        "dragon_shape_score": None,
        "false_reversal_risk_pre": None,
        "pass_l1_gate": False,
        "block_reasons": block_reasons,
        "captured_at": as_of_time,
        "as_of_time": as_of_time,
    }
    if block_reasons:
        base_payload["feature_hash"] = _hash_payload(base_payload)
        return base_payload

    max_high = max(highs)
    min_low = min(lows)
    span = max_high - min_low
    if span <= 0:
        base_payload["block_reasons"] = ["blocked_flat_price_range"]
        base_payload["feature_hash"] = _hash_payload(base_payload)
        return base_payload

    trough_idx = min(range(len(lows)), key=lambda index: lows[index])
    trough_price = lows[trough_idx]
    trough_position_ratio = trough_idx / window_days
    drawdown_from_window_high = (max_high - trough_price) / max_high if max_high > 0 else None
    close_today = closes[-1]
    distance_from_trough = (close_today - trough_price) / trough_price if trough_price > 0 else None

    if trough_position_ratio < 0.35 or trough_position_ratio > 0.92:
        block_reasons.append("blocked_invalid_trough_position")
    if drawdown_from_window_high is None or drawdown_from_window_high < 0.08 or drawdown_from_window_high > 0.45:
        block_reasons.append("blocked_invalid_drawdown_depth")
    if distance_from_trough is None or distance_from_trough < 0 or distance_from_trough > 0.25:
        block_reasons.append("blocked_overextended_from_trough")

    pre_trough = closes[: max(trough_idx, 1)]
    post_trough = closes[trough_idx:]
    early = pre_trough[: max(2, len(pre_trough) // 2)]
    late = pre_trough[max(0, len(pre_trough) // 2) :]
    slope_early = _linear_slope(early)
    slope_late = _linear_slope(late)
    pre_slope = _linear_slope(closes[max(0, trough_idx - 10) : max(trough_idx, 1)])
    post_slope = _linear_slope(post_trough)

    drawdown_depth_score = _score(((drawdown_from_window_high or 0) - 0.08) / 0.37 * 100.0)
    decline_duration_score = _score(min(100.0, trough_position_ratio / 0.70 * 100.0))
    downside_velocity_slowdown_score = _score(100.0 if slope_early < 0 and slope_late > slope_early else 50.0)
    lower_low_exhaustion_score = _score(100.0 if min(lows[trough_idx:]) >= trough_price * 0.985 else 20.0)
    support_proximity_score = _score(100.0 - min(100.0, max(0.0, (distance_from_trough or 0) / 0.25 * 100.0)))
    decline_maturity_score = _score(
        float(drawdown_depth_score) * 0.25
        + float(decline_duration_score) * 0.20
        + float(downside_velocity_slowdown_score) * 0.20
        + float(lower_low_exhaustion_score) * 0.20
        + float(support_proximity_score) * 0.15
    )

    post_lows = lows[trough_idx:]
    post_returns = _returns(post_trough)
    pre_returns = _returns(closes[: max(trough_idx + 1, 2)])
    no_new_low_score = _score(100.0 if min(post_lows) >= trough_price * 0.985 else 20.0)
    support_hold_score = _score(sum(1 for value in post_lows if value >= trough_price * 0.985) / len(post_lows) * 100.0)
    volatility_contraction_score = _score(100.0 if _std(post_returns) < _std(pre_returns) * 0.80 else 45.0)
    lower_shadow_support_score = _score(
        sum(1 for open_price, close_price in zip(opens[trough_idx:], closes[trough_idx:], strict=False) if close_price > open_price)
        / max(1, len(opens[trough_idx:]))
        * 100.0
    )
    close_lift_score = _score(max(0.0, (close_today - trough_price) / trough_price / 0.18 * 100.0))
    bottom_stabilization_score = _score(
        float(no_new_low_score) * 0.25
        + float(support_hold_score) * 0.20
        + float(volatility_contraction_score) * 0.20
        + float(lower_shadow_support_score) * 0.20
        + float(close_lift_score) * 0.15
    )

    ma5_today = _mean(closes[-5:]) or close_today
    ma5_yesterday = _mean(closes[-6:-1]) or ma5_today
    ma10_today = _mean(closes[-10:]) or ma5_today
    recent_swing_low = min(lows[-5:]) if len(lows) >= 5 else min(lows)
    predicted_downtrend = highs[0] + _linear_slope(highs[: max(trough_idx, 2)]) * (len(highs) - 1)
    slope_turn_positive_score = _score(100.0 if pre_slope < 0 <= post_slope else 50.0 + (post_slope - pre_slope) * 100.0)
    first_higher_low_score = _score(100.0 if recent_swing_low > trough_price * 1.01 else 30.0)
    short_ma_recovery_score = _score(100.0 if ma5_today > ma5_yesterday and close_today > ma5_today and ma5_today >= ma10_today * 0.98 else 30.0)
    downtrend_break_score = _score(100.0 if close_today > predicted_downtrend else 40.0)
    close_near_recent_high_score = _score((close_today - min(closes[-10:])) / max(0.000001, max(highs[-10:]) - min(closes[-10:])) * 100.0)
    early_turn_up_score = _score(
        float(slope_turn_positive_score) * 0.25
        + float(first_higher_low_score) * 0.20
        + float(short_ma_recovery_score) * 0.20
        + float(downtrend_break_score) * 0.20
        + float(close_near_recent_high_score) * 0.15
    )

    sqrt_right_match_score = _template_score(post_trough, "sqrt_right")
    v_left_bottom_match_score = _template_score(pre_trough, "v_left_bottom")
    piecewise_trend_turn_score = _score(100.0 if pre_slope < post_slope else 40.0)
    dragon_shape_score = _score(
        float(sqrt_right_match_score) * 0.50
        + float(v_left_bottom_match_score) * 0.30
        + float(piecewise_trend_turn_score) * 0.20
    )
    if dragon_shape_score < Decimal("55"):
        block_reasons.append("blocked_shape_score_below_threshold")

    trend_still_down = 100.0 if post_slope < 0 else 20.0
    upper_shadow_count = sum(
        1
        for high, open_price, close_price in zip(highs[-5:], opens[-5:], closes[-5:], strict=False)
        if high - max(open_price, close_price) > span * 0.08
    )
    false_reversal_risk_pre = _score(
        trend_still_down * 0.35
        + (100.0 - float(close_lift_score)) * 0.20
        + (100.0 if distance_from_trough and distance_from_trough > 0.18 else 20.0) * 0.20
        + (upper_shadow_count / 5.0 * 100.0) * 0.25
    )

    base_payload.update(
        {
            "trough_trading_day": selected[trough_idx].get("trading_day"),
            "trough_position_ratio": _ratio(trough_position_ratio),
            "drawdown_from_window_high": _ratio(drawdown_from_window_high),
            "distance_from_trough": _ratio(distance_from_trough),
            "decline_maturity_score": decline_maturity_score,
            "bottom_stabilization_score": bottom_stabilization_score,
            "early_turn_up_score": early_turn_up_score,
            "sqrt_right_match_score": sqrt_right_match_score,
            "v_left_bottom_match_score": v_left_bottom_match_score,
            "dragon_shape_score": dragon_shape_score,
            "false_reversal_risk_pre": false_reversal_risk_pre,
            "pass_l1_gate": not block_reasons,
            "block_reasons": block_reasons,
        }
    )
    base_payload["feature_hash"] = _hash_payload(base_payload)
    return base_payload


def calculate_all_window_features(
    *,
    symbol: str,
    bars: list[dict[str, Any]],
    as_of_trading_day: date,
    as_of_time: datetime | None = None,
) -> list[dict[str, Any]]:
    effective_time = as_of_time or datetime.now(timezone.utc)
    return [
        calculate_dragon_window_feature(
            symbol=symbol,
            bars=bars,
            window_days=window,
            as_of_trading_day=as_of_trading_day,
            as_of_time=effective_time,
        )
        for window in DRAGON_WINDOWS
    ]


def _window_metrics(
    *,
    bars: list[dict[str, Any]],
    window_days: int,
    as_of_trading_day: date,
) -> dict[str, Any] | None:
    sorted_bars = _sorted_bars(bars)
    selected = sorted_bars[-window_days:]
    required_count = math.ceil(window_days * float(MIN_DAILY_COMPLETENESS))
    if len(selected) < required_count:
        return None
    highs = [_float(bar.get("high_price"), math.nan) for bar in selected]
    lows = [_float(bar.get("low_price"), math.nan) for bar in selected]
    closes = [_float(bar.get("close_price"), math.nan) for bar in selected]
    if not all(math.isfinite(value) and value > 0 for value in highs + lows + closes):
        return None
    max_high = max(highs)
    trough_idx = min(range(len(lows)), key=lambda index: lows[index])
    trough_low = lows[trough_idx]
    today_close = closes[-1]
    if max_high <= 0 or trough_low <= 0:
        return None
    primary_trough_age_days = len(selected) - 1 - trough_idx
    rolling_drawdown = (max_high - trough_low) / max_high
    close_to_trough = (today_close - trough_low) / trough_low
    pre_trough_closes = closes[: max(trough_idx, 1)]
    early = pre_trough_closes[: max(2, len(pre_trough_closes) // 2)]
    late = pre_trough_closes[max(0, len(pre_trough_closes) // 2) :]
    slope_early = _linear_slope(early)
    slope_late = _linear_slope(late)
    post_lows = lows[trough_idx:]
    post_closes = closes[trough_idx:]
    post_returns = _returns(post_closes)
    pre_returns = _returns(closes[: max(trough_idx + 1, 2)])
    no_new_low = min(post_lows) >= trough_low * 0.985
    downside_velocity_slowdown_score = _score(100.0 if slope_early < 0 and slope_late > slope_early else 45.0)
    support_proximity_score = _score(100.0 - min(100.0, max(0.0, close_to_trough / 0.06 * 100.0)))
    bottom_area_stability_score = _score(
        (100.0 if no_new_low else 25.0) * 0.45
        + (sum(1 for value in post_lows if value >= trough_low * 0.985) / len(post_lows) * 100.0) * 0.35
        + (100.0 if _linear_slope(post_closes) >= -0.01 else 35.0) * 0.20
    )
    volatility_contraction_score = _score(
        100.0 if post_returns and pre_returns and _std(post_returns) < _std(pre_returns) * 0.80 else 45.0
    )
    drawdown_depth_score = _score((rolling_drawdown - 0.08) / 0.37 * 100.0)
    support_break_risk = _score(100.0 if min(lows[-3:]) < trough_low * 0.985 else 0.0)
    valley_watch_score = _score(
        float(drawdown_depth_score) * 0.30
        + float(downside_velocity_slowdown_score) * 0.25
        + float(bottom_area_stability_score) * 0.20
        + float(support_proximity_score) * 0.15
        + float(volatility_contraction_score) * 0.10
        - float(support_break_risk) * 0.25
    )
    return {
        "selected": selected,
        "window_days": window_days,
        "primary_trough_index": trough_idx,
        "primary_trough_day": _as_date(selected[trough_idx].get("trading_day"), as_of_trading_day),
        "primary_trough_low": Decimal(str(trough_low)).quantize(Decimal("0.000001")),
        "primary_trough_age_days": primary_trough_age_days,
        "close_to_trough_pct": _pct(close_to_trough),
        "rolling_drawdown_pct": _pct(rolling_drawdown),
        "downside_velocity_slowdown_score": downside_velocity_slowdown_score,
        "bottom_area_stability_score": bottom_area_stability_score,
        "volatility_contraction_score": volatility_contraction_score,
        "support_proximity_score": support_proximity_score,
        "support_break_risk": support_break_risk,
        "valley_watch_score": valley_watch_score,
        "daily_data_complete": len(selected) >= required_count,
        "support_not_broken": no_new_low,
    }


def calculate_valley_watch_candidate(
    *,
    instrument: dict[str, Any],
    bars: list[dict[str, Any]],
    as_of_trading_day: date,
    as_of_time: datetime | None = None,
) -> dict[str, Any] | None:
    effective_time = as_of_time or datetime.now(timezone.utc)
    symbol = str(instrument.get("symbol") or "").zfill(6)
    exchange = str(instrument.get("exchange") or "")
    asset_type = str(instrument.get("asset_type") or "A_SHARE")
    source_gap_codes: list[str] = []
    if not bars:
        source_gap_codes.append("daily_bar_missing")
    if instrument.get("has_trade_calendar") is False or instrument.get("trade_calendar_missing"):
        source_gap_codes.append("trading_calendar_missing")
    if exchange not in ("SZSE", "SZ") or asset_type != "A_SHARE" or instrument.get("is_active") is False:
        return None
    metrics = [
        _window_metrics(bars=bars, window_days=window, as_of_trading_day=as_of_trading_day)
        for window in DRAGON_WINDOWS
    ]
    candidates = [item for item in metrics if item is not None]
    if not candidates:
        return None
    best = max(candidates, key=lambda item: item["valley_watch_score"])
    invalidation_reason_codes: list[str] = []
    valley_reason_codes: list[str] = []
    if Decimal("8") <= best["rolling_drawdown_pct"] <= Decimal("45"):
        valley_reason_codes.append("drawdown_mature")
    else:
        invalidation_reason_codes.append("rolling_drawdown_out_of_range")
    if best["close_to_trough_pct"] <= Decimal("6"):
        valley_reason_codes.append("near_primary_trough")
    else:
        invalidation_reason_codes.append("too_far_from_primary_trough")
    if best["downside_velocity_slowdown_score"] >= Decimal("55"):
        valley_reason_codes.append("velocity_slowing")
    else:
        invalidation_reason_codes.append("downside_velocity_not_slowing")
    if best["support_not_broken"]:
        valley_reason_codes.append("support_not_broken")
    else:
        invalidation_reason_codes.append("support_broken")
    if not best["daily_data_complete"]:
        source_gap_codes.append("daily_bar_incomplete")
    if source_gap_codes:
        valley_status = "data_blocked"
    elif invalidation_reason_codes:
        valley_status = "valley_invalidated"
    else:
        valley_status = "valley_watch"
    result = {
        "trade_date": as_of_trading_day,
        "symbol": symbol,
        "instrument_id": int(instrument.get("instrument_id") or 0),
        "exchange": "SZSE",
        "board": instrument.get("board"),
        "as_of_time": effective_time,
        "best_window_days": int(best["window_days"]),
        "primary_trough_day": best["primary_trough_day"],
        "primary_trough_low": best["primary_trough_low"],
        "primary_trough_age_days": int(best["primary_trough_age_days"]),
        "close_to_trough_pct": best["close_to_trough_pct"],
        "rolling_drawdown_pct": best["rolling_drawdown_pct"],
        "downside_velocity_slowdown_score": best["downside_velocity_slowdown_score"],
        "bottom_area_stability_score": best["bottom_area_stability_score"],
        "volatility_contraction_score": best["volatility_contraction_score"],
        "valley_watch_score": best["valley_watch_score"],
        "valley_status": valley_status,
        "valley_reason_codes": valley_reason_codes,
        "invalidation_reason_codes": invalidation_reason_codes,
        "source_gap_codes": source_gap_codes,
        "evidence_refs": _evidence_refs_from_bars(best["selected"]),
    }
    result["payload_hash"] = _hash_payload(result)
    return result


def _base_breakout_candidate(
    selected: list[dict[str, Any]],
    *,
    trough_idx: int,
    trough_low: float,
) -> dict[str, Any] | None:
    today_idx = len(selected) - 1
    primary_trough_age_days = today_idx - trough_idx
    if primary_trough_age_days < 5 or primary_trough_age_days > 12:
        return None
    closes = [_float(bar.get("close_price"), math.nan) for bar in selected]
    highs = [_float(bar.get("high_price"), math.nan) for bar in selected]
    today_close = closes[-1]
    if not math.isfinite(today_close) or trough_low <= 0:
        return None
    post_trough_return = (today_close - trough_low) / trough_low
    compression_window = selected[max(trough_idx + 1, today_idx - 5) : today_idx]
    if len(compression_window) < 3 or post_trough_return > 0.08:
        return None
    compression_highs = [_float(bar.get("high_price"), math.nan) for bar in compression_window]
    compression_lows = [_float(bar.get("low_price"), math.nan) for bar in compression_window]
    if not all(math.isfinite(value) and value > 0 for value in compression_highs + compression_lows):
        return None
    compression_range_pct = (max(compression_highs) - min(compression_lows)) / max(compression_lows)
    volume_ratio_today = _volume_ratio_at(selected, today_idx)
    if (
        compression_range_pct <= 0.08
        and today_close > max(compression_highs) * 0.995
        and volume_ratio_today is not None
        and volume_ratio_today >= 1.10
        and _upper_shadow_ratio(selected[-1]) <= 0.05
    ):
        return {"anchor_index": today_idx, "shape_type": "base_breakout", "base_breakout_after_trough": True}
    return None


def _detect_effective_turn_anchor(
    *,
    selected: list[dict[str, Any]],
    trough_idx: int,
    trough_low: float,
) -> dict[str, Any] | None:
    today_idx = len(selected) - 1
    base_breakout = _base_breakout_candidate(selected, trough_idx=trough_idx, trough_low=trough_low)
    if base_breakout is not None:
        return base_breakout
    closes = [_float(bar.get("close_price"), math.nan) for bar in selected]
    lows = [_float(bar.get("low_price"), math.nan) for bar in selected]
    for idx in range(max(1, trough_idx + 1), len(selected)):
        close_t = closes[idx]
        prev_close = closes[idx - 1]
        low_t = lows[idx]
        if not all(math.isfinite(value) and value > 0 for value in (close_t, prev_close, low_t)):
            continue
        ma5_t = _mean(closes[max(0, idx - 4) : idx + 1]) or close_t
        volume_ratio = _volume_ratio_at(selected, idx)
        close_strength = _close_strength(selected[idx])
        post_turn_return = (closes[today_idx] - close_t) / close_t
        if (
            close_t > prev_close
            and close_strength >= 0.60
            and close_t >= ma5_t * 0.995
            and low_t >= trough_low * 0.985
            and volume_ratio is not None
            and volume_ratio >= 0.85
            and post_turn_return <= 0.06
        ):
            recent_low = min(lows[max(trough_idx, idx - 4) : idx + 1])
            shape_type = "first_rebound" if idx - trough_idx <= 2 else "second_turn"
            if shape_type == "second_turn" and recent_low < trough_low * 1.005:
                continue
            return {"anchor_index": idx, "shape_type": shape_type, "base_breakout_after_trough": False}
    return None


def build_effective_turn_candidate(
    *,
    instrument: dict[str, Any],
    valley_watch: dict[str, Any] | None,
    bars: list[dict[str, Any]],
    as_of_trading_day: date,
    as_of_time: datetime | None = None,
    snapshot_type: str = "close_confirmed",
) -> dict[str, Any] | None:
    effective_time = as_of_time or datetime.now(timezone.utc)
    symbol = str(instrument.get("symbol") or "").zfill(6)
    if valley_watch is None:
        valley_watch = calculate_valley_watch_candidate(
            instrument=instrument,
            bars=bars,
            as_of_trading_day=as_of_trading_day,
            as_of_time=effective_time,
        )
    if valley_watch is None:
        return None
    valley_status = str(valley_watch.get("valley_status") or "")
    if valley_status not in {"valley_watch", "transitioned"}:
        reject_reason_codes = ["data_blocked" if valley_status == "data_blocked" else "valley_status_not_eligible"]
        source_gap_codes = list(valley_watch.get("source_gap_codes") or [])
        if "daily_bar_missing" in source_gap_codes:
            reject_reason_codes = ["daily_bar_missing"]
        elif "daily_bar_incomplete" in source_gap_codes:
            reject_reason_codes = ["daily_bar_missing"]
        elif "trading_calendar_missing" in source_gap_codes:
            reject_reason_codes = ["trading_calendar_missing"]
        result = {
            "trade_date": as_of_trading_day,
            "symbol": symbol,
            "instrument_id": int(instrument.get("instrument_id") or valley_watch.get("instrument_id") or 0),
            "as_of_time": effective_time,
            "snapshot_type": snapshot_type,
            "l1_status": "rejected",
            "reject_reason_codes": reject_reason_codes,
            "source_gap_codes": source_gap_codes,
            "evidence_refs": valley_watch.get("evidence_refs") or [],
        }
        result["payload_hash"] = _hash_payload(result)
        return result
    window_days = int(valley_watch.get("best_window_days") or 120)
    sorted_bars = _sorted_bars(bars)
    selected = sorted_bars[-window_days:]
    if len(selected) < 2:
        return None
    lows = [_float(bar.get("low_price"), math.nan) for bar in selected]
    closes = [_float(bar.get("close_price"), math.nan) for bar in selected]
    trough_day = _as_date(valley_watch.get("primary_trough_day"), as_of_trading_day)
    trough_idx = next(
        (idx for idx, bar in enumerate(selected) if _as_date(bar.get("trading_day"), as_of_trading_day) == trough_day),
        min(range(len(lows)), key=lambda idx: lows[idx]),
    )
    trough_low = _float(valley_watch.get("primary_trough_low"), lows[trough_idx])
    anchor = _detect_effective_turn_anchor(selected=selected, trough_idx=trough_idx, trough_low=trough_low)
    reject_reason_codes: list[str] = []
    source_gap_codes: list[str] = []
    if anchor is None:
        reject_reason_codes.append("no_effective_turn_anchor")
        return None
    anchor_idx = int(anchor["anchor_index"])
    anchor_bar = selected[anchor_idx]
    anchor_day = _as_date(anchor_bar.get("trading_day"), as_of_trading_day)
    effective_turn_age_days = _trading_day_distance(selected, anchor_day, as_of_trading_day)
    primary_trough_age_days = len(selected) - 1 - trough_idx
    close_today = closes[-1]
    close_anchor = closes[anchor_idx]
    post_turn_return_pct = _pct((close_today - close_anchor) / close_anchor if close_anchor > 0 else None)
    post_trough_return_pct = _pct((close_today - trough_low) / trough_low if trough_low > 0 else None)
    close_strength = Decimal(str(_close_strength(anchor_bar))).quantize(Decimal("0.000001"))
    volume_ratio = _volume_ratio_at(selected, anchor_idx)
    if volume_ratio is None:
        source_gap_codes.append("volume_baseline_missing")
    support_not_broken = min(lows[trough_idx:]) >= trough_low * 0.985
    base_breakout = bool(anchor.get("base_breakout_after_trough"))
    if effective_turn_age_days > 3:
        reject_reason_codes.append("turn_not_fresh")
    if post_turn_return_pct > Decimal("6"):
        reject_reason_codes.append("post_turn_return_too_high")
    if close_strength < Decimal("0.60"):
        reject_reason_codes.append("weak_close_strength")
    if not support_not_broken:
        reject_reason_codes.append("support_not_held")
    if primary_trough_age_days > 5 and not base_breakout:
        reject_reason_codes.append("late_rebound_without_base_breakout")
    if not selected:
        reject_reason_codes.append("daily_bar_missing")
    effective_age_score_map = {0: 60, 1: 100, 2: 95, 3: 70, 4: 45, 5: 45}
    effective_turn_age_score = _score(effective_age_score_map.get(effective_turn_age_days, 10))
    post_turn_gain_room_score = _score(max(0.0, 100.0 - float(post_turn_return_pct) / 6.0 * 100.0))
    first_or_second_rebound_score = _score(100.0 if anchor["shape_type"] in ("first_rebound", "second_turn") else 90.0)
    anchor_quality_score = _score(float(close_strength) * 100.0)
    post_turn_return_penalty = _score(float(post_turn_return_pct) / 6.0 * 100.0)
    turn_freshness_score = _score(
        float(effective_turn_age_score) * 0.45
        + float(post_turn_gain_room_score) * 0.25
        + float(first_or_second_rebound_score) * 0.20
        + float(anchor_quality_score) * 0.10
    )
    low_support_hold_score = _score(100.0 if support_not_broken else 20.0)
    gentle_volume_recovery_score = _score(
        100.0 if volume_ratio is not None and 0.85 <= volume_ratio <= 2.50 else 45.0
    )
    primary_trough_age_penalty = _score(max(0, primary_trough_age_days - 5) / 7 * 100.0)
    post_trough_return_penalty = _score(max(0.0, float(post_trough_return_pct) - 8.0) / 12.0 * 100.0)
    resistance_proximity_penalty = _score(70.0 if post_trough_return_pct > Decimal("10") else 25.0)
    late_rebound_penalty = _score(
        float(primary_trough_age_penalty) * 0.40
        + float(post_trough_return_penalty) * 0.35
        + float(resistance_proximity_penalty) * 0.25
    )
    if base_breakout:
        late_rebound_penalty = _score(float(late_rebound_penalty) * 0.35)
    effective_turn_score = _score(
        float(turn_freshness_score) * 0.30
        + float(anchor_quality_score) * 0.25
        + float(anchor_quality_score) * 0.20
        + float(low_support_hold_score) * 0.15
        + float(gentle_volume_recovery_score) * 0.10
        - float(post_turn_return_penalty) * 0.20
    )
    if reject_reason_codes:
        l1_status = "rejected"
    elif effective_turn_age_days == 3:
        l1_status = "backup_only"
    elif effective_turn_age_days <= 2:
        l1_status = "accepted"
    else:
        l1_status = "rejected"
    result = {
        "valley_id": valley_watch.get("valley_id"),
        "trade_date": as_of_trading_day,
        "symbol": symbol,
        "instrument_id": int(instrument.get("instrument_id") or valley_watch.get("instrument_id") or 0),
        "as_of_time": effective_time,
        "snapshot_type": snapshot_type,
        "shape_type": str(anchor["shape_type"]),
        "effective_turn_anchor_day": anchor_day,
        "effective_turn_age_days": effective_turn_age_days,
        "primary_trough_day": trough_day,
        "primary_trough_age_days": primary_trough_age_days,
        "post_turn_return_pct": post_turn_return_pct,
        "post_trough_return_pct": post_trough_return_pct,
        "close_strength": close_strength,
        "volume_ratio": _ratio(volume_ratio),
        "base_breakout_after_trough": base_breakout,
        "effective_turn_score": effective_turn_score,
        "turn_freshness_score": turn_freshness_score,
        "late_rebound_penalty": late_rebound_penalty,
        "l1_status": l1_status,
        "reject_reason_codes": reject_reason_codes,
        "source_gap_codes": source_gap_codes,
        "evidence_refs": _evidence_refs_from_bars(selected[max(0, trough_idx - 2) :]),
    }
    result["payload_hash"] = _hash_payload(result)
    return result


def build_pool_transition_audit(
    *,
    instrument: dict[str, Any],
    valley_watch: dict[str, Any],
    effective_turn_candidate: dict[str, Any],
    as_of_time: datetime | None = None,
    created_by_job: str = "ambush_pool_transition_job",
) -> dict[str, Any] | None:
    if valley_watch.get("valley_status") not in {"valley_watch", "transitioned"}:
        return None
    if effective_turn_candidate.get("l1_status") not in ("accepted", "backup_only"):
        return None
    effective_time = as_of_time or effective_turn_candidate.get("as_of_time") or datetime.now(timezone.utc)
    return {
        "symbol": str(instrument.get("symbol") or effective_turn_candidate.get("symbol") or "").zfill(6),
        "instrument_id": int(instrument.get("instrument_id") or effective_turn_candidate.get("instrument_id") or 0),
        "from_pool": "valley_watch_pool",
        "to_pool": "effective_turn_pool",
        "from_status": valley_watch.get("valley_status") or "valley_watch",
        "to_status": effective_turn_candidate.get("l1_status"),
        "trigger_event": "effective_turn_anchor_detected",
        "trigger_as_of_time": effective_time,
        "trigger_snapshot_type": effective_turn_candidate.get("snapshot_type") or "close_confirmed",
        "trigger_feature_json": {
            "trade_date": effective_turn_candidate.get("trade_date"),
            "shape_type": effective_turn_candidate.get("shape_type"),
            "effective_turn_anchor_day": effective_turn_candidate.get("effective_turn_anchor_day"),
            "effective_turn_age_days": effective_turn_candidate.get("effective_turn_age_days"),
            "post_turn_return_pct": effective_turn_candidate.get("post_turn_return_pct"),
            "turn_freshness_score": effective_turn_candidate.get("turn_freshness_score"),
        },
        "decision_rule_version": DRAGON_MODEL_VERSION,
        "decision_result": effective_turn_candidate.get("l1_status"),
        "reject_reason_codes": effective_turn_candidate.get("reject_reason_codes") or [],
        "evidence_refs": effective_turn_candidate.get("evidence_refs") or valley_watch.get("evidence_refs") or [],
        "created_by_job": created_by_job,
    }


def select_best_l1_feature(features: list[dict[str, Any]]) -> dict[str, Any] | None:
    passed = [feature for feature in features if feature.get("pass_l1_gate")]
    if not passed:
        return None
    return max(passed, key=lambda item: Decimal(str(item.get("dragon_shape_score") or "0")))


def build_l2_candidate(
    *,
    instrument: dict[str, Any],
    best_feature: dict[str, Any] | None,
    bars: list[dict[str, Any]],
    as_of_trading_day: date,
) -> dict[str, Any] | None:
    if best_feature is None:
        return None
    sorted_bars = _sorted_bars(bars)
    recent_120_count = min(len(sorted_bars), 120)
    daily_data_completeness = Decimal(recent_120_count) / Decimal("120")
    recent_20 = sorted_bars[-20:]
    amount_values = [_bar_amount(bar) for bar in recent_20]
    turnover_values = [_decimal(bar.get("turnover_rate")) for bar in recent_20]
    valid_amounts = [value for value in amount_values if value is not None]
    valid_turnovers = [value for value in turnover_values if value is not None]
    avg_amount_20d = sum(valid_amounts) / Decimal(len(valid_amounts)) if valid_amounts else None
    avg_turnover_20d = sum(valid_turnovers) / Decimal(len(valid_turnovers)) if valid_turnovers else None

    block_reasons: list[str] = []
    warning_reasons: list[str] = []
    if instrument.get("is_suspended"):
        block_reasons.append("blocked_suspended")
    if instrument.get("is_delisting_risk"):
        block_reasons.append("blocked_delisting_risk")
    if instrument.get("is_st"):
        block_reasons.append("blocked_special_treatment")
    if instrument.get("trade_calendar_missing") or instrument.get("has_trade_calendar") is False:
        block_reasons.append("blocked_missing_trade_calendar")
    if instrument.get("adjustment_conflict") or any(bar.get("adjustment_conflict") for bar in sorted_bars):
        block_reasons.append("blocked_adjustment_conflict")
    if daily_data_completeness < MIN_DAILY_COMPLETENESS:
        block_reasons.append("blocked_daily_bar_incomplete")
    if avg_amount_20d is None or avg_amount_20d < MIN_AVG_AMOUNT_20D:
        block_reasons.append("blocked_low_liquidity")
    if best_feature.get("distance_from_trough") is not None and Decimal(str(best_feature["distance_from_trough"])) > Decimal("0.25"):
        block_reasons.append("blocked_overextended_from_trough")
    if str(instrument.get("price_limit_regime") or "") == "20cm":
        warning_reasons.append("warning_price_limit_regime_20cm")
    listing_days = instrument.get("listing_days")
    if listing_days is not None and int(listing_days) < 60:
        warning_reasons.append("warning_short_listing_history")

    return {
        "as_of_trading_day": as_of_trading_day,
        "symbol": str(instrument["symbol"]).zfill(6),
        "best_shape_window": int(best_feature.get("window_days") or best_feature.get("window") or 0),
        "dragon_shape_score": best_feature["dragon_shape_score"],
        "l2_status": "blocked" if block_reasons else "passed",
        "block_reasons": block_reasons,
        "warning_reasons": warning_reasons,
        "avg_amount_20d": avg_amount_20d.quantize(Decimal("0.01")) if avg_amount_20d is not None else None,
        "avg_turnover_20d": avg_turnover_20d.quantize(Decimal("0.000001")) if avg_turnover_20d is not None else None,
        "daily_data_completeness": daily_data_completeness.quantize(Decimal("0.000001")),
        "liquidity_check": "passed" if avg_amount_20d is not None and avg_amount_20d >= MIN_AVG_AMOUNT_20D else "blocked_low_liquidity",
        "data_quality_check": "passed" if daily_data_completeness >= MIN_DAILY_COMPLETENESS else "blocked_daily_bar_incomplete",
    }

def _normalized_context_score(value: Any) -> Decimal | None:
    numeric = _decimal(value)
    if numeric is None:
        return None
    if Decimal("0") <= numeric <= Decimal("1"):
        numeric *= Decimal("100")
    return _score(numeric)


def _context_score(context: dict[str, Any] | None, *keys: str) -> Decimal | None:
    if context is None:
        return None
    sources = [context]
    features = context.get("features")
    if isinstance(features, dict):
        sources.append(features)
    for key in keys:
        for source in sources:
            if key in source and source[key] not in (None, ""):
                score = _normalized_context_score(source[key])
                if score is not None:
                    return score
    return None


def _market_environment_score(context: dict[str, Any] | None) -> Decimal | None:
    score = _context_score(
        context,
        "market_environment_score",
        "market_context_score",
        "market_regime_score",
        "risk_appetite_score",
        "breadth_score",
    )
    if score is not None:
        return score
    features = context.get("features") if isinstance(context, dict) else None
    if not isinstance(features, dict):
        return None
    risk_regime = str(features.get("risk_regime") or features.get("market_regime") or "").lower()
    regime_scores = {
        "risk_on": Decimal("78"),
        "mixed": Decimal("55"),
        "neutral": Decimal("58"),
        "risk_off": Decimal("34"),
        "defensive": Decimal("30"),
    }
    if risk_regime in regime_scores:
        return _score(regime_scores[risk_regime])
    return None


def _context_sources(context: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(context, dict):
        return []
    sources = [context]
    features = context.get("features")
    if isinstance(features, dict):
        sources.append(features)
    return sources


def _context_decimal(context: dict[str, Any] | None, *keys: str) -> Decimal | None:
    for source in _context_sources(context):
        for key in keys:
            if key in source and source[key] not in (None, ""):
                value = _decimal(source[key])
                if value is not None:
                    return value
    return None


def _context_text(context: dict[str, Any] | None, *keys: str) -> str:
    for source in _context_sources(context):
        for key in keys:
            value = source.get(key)
            if value not in (None, ""):
                return str(value).strip().lower()
    return ""


def _market_defensive_headwind(context: dict[str, Any] | None) -> bool:
    regime = _context_text(context, "risk_regime", "market_regime", "regime")
    if regime != "defensive":
        return False
    down_count = _context_decimal(context, "breadth_down_count", "down_count", "decline_count")
    total_count = _context_decimal(context, "breadth_total_count", "total_count", "stock_count")
    if down_count is None or total_count is None or total_count <= 0:
        return False
    return (down_count / total_count) > Decimal("0.70")


def _has_major_negative_event(context: dict[str, Any] | None) -> bool:
    for source in _context_sources(context):
        if source.get("major_negative_event") is True:
            return True
        direction = str(source.get("event_direction") or source.get("direction") or "").strip().lower()
        impact_level = str(source.get("impact_level") or source.get("severity") or "").strip().lower()
        if direction in {"negative", "bearish"} and impact_level in {"high", "major", "critical"}:
            return True
    return False


def _build_deep_analysis_v11(
    *,
    instrument: dict[str, Any],
    best_feature: dict[str, Any],
    l2_candidate: dict[str, Any],
    effective_turn_candidate: dict[str, Any] | None = None,
    bars: list[dict[str, Any]],
    stock_rank: dict[str, Any] | None,
    theme_ranks: list[dict[str, Any]],
    news_context: dict[str, Any] | None = None,
    market_context: dict[str, Any] | None = None,
    as_of_trading_day: date,
    as_of_time: datetime | None = None,
) -> dict[str, Any]:
    effective_time = as_of_time or datetime.now(timezone.utc)
    symbol = str(instrument.get("symbol") or "").zfill(6)
    source_gap_codes: list[str] = []
    sorted_bars = _sorted_bars(bars)
    volumes = [_float(bar.get("volume"), math.nan) for bar in sorted_bars]
    amounts = [_float(_bar_amount(bar), math.nan) for bar in sorted_bars]
    recent_volume = _mean(volumes[-3:]) if len(volumes) >= 3 else None
    base_volume = _mean(volumes[-20:-5]) if len(volumes) >= 20 else None
    volume_ratio = recent_volume / base_volume if recent_volume is not None and base_volume and base_volume > 0 else None
    recent_amount = _mean(amounts[-3:]) if len(amounts) >= 3 else None
    base_amount = _mean(amounts[-20:-5]) if len(amounts) >= 20 else None

    capital_parts: list[tuple[Decimal, Decimal]] = []
    if volume_ratio is not None:
        capital_parts.append((Decimal("0.30"), _score(100.0 if 1.10 <= volume_ratio <= 2.50 else 45.0)))
        capital_parts.append((Decimal("0.20"), _score(70.0 if volume_ratio < 2.50 else 35.0)))
    if recent_amount is not None and base_amount is not None and base_amount > 0:
        capital_parts.append((Decimal("0.25"), _score(100.0 if recent_amount > base_amount else 45.0)))
    main_net_inflow = _decimal(stock_rank.get("main_net_inflow")) if stock_rank else None
    if main_net_inflow is None:
        source_gap_codes.append("moneyflow_missing")
    else:
        capital_parts.append((Decimal("0.15"), _score(75.0 if main_net_inflow > 0 else 45.0)))
    if l2_candidate.get("avg_turnover_20d") is not None:
        capital_parts.append((Decimal("0.10"), _score(65.0)))
    if capital_parts:
        weight_sum = sum(weight for weight, _ in capital_parts)
        capital_probe_score = _score(float(sum(weight * score for weight, score in capital_parts) / weight_sum))
    else:
        capital_probe_score = None
        source_gap_codes.append("deep_capital_probe_missing")

    if theme_ranks:
        best_rank = min(int(rank.get("rank_no") or 9999) for rank in theme_ranks)
        sector_context_score = _score(max(35.0, 100.0 - min(best_rank, 100) * 0.65))
    else:
        sector_context_score = None
        source_gap_codes.append("board_context_missing")
    news_event_score = _context_score(news_context, "news_event_score", "impact_score", "sentiment_score")
    if news_event_score is None:
        source_gap_codes.append("news_event_missing")
    major_negative_event = _has_major_negative_event(news_context)
    market_context_score = _market_environment_score(market_context)
    if market_context_score is None:
        source_gap_codes.append("market_context_missing")
    market_defensive_headwind = _market_defensive_headwind(market_context)

    distance = _decimal(best_feature.get("distance_from_trough"))
    if distance is None:
        source_gap_codes.append("distance_from_trough_missing")
        upside_room_score = None
    else:
        upside_room_score = _score(100.0 - float(distance) / 0.25 * 60.0)
    false_reversal_risk = _decimal(best_feature.get("false_reversal_risk_pre"))
    if false_reversal_risk is None:
        source_gap_codes.append("false_reversal_risk_missing")
    if volume_ratio is not None and volume_ratio > 4.0:
        false_reversal_risk = _score(float(false_reversal_risk or Decimal("100")) + 15.0)
    if market_defensive_headwind and false_reversal_risk is not None:
        false_reversal_risk = _score(float(false_reversal_risk) + 10.0)
    if major_negative_event and false_reversal_risk is not None:
        false_reversal_risk = _score(float(false_reversal_risk) + 20.0)
    l2_daily_completeness = _decimal(l2_candidate.get("daily_data_completeness"))
    if l2_daily_completeness is None:
        source_gap_codes.append("daily_bar_completeness_missing")
    elif l2_daily_completeness < MIN_DAILY_COMPLETENESS:
        source_gap_codes.append("daily_bar_completeness_below_l4")
    l2_liquidity_passed = l2_candidate.get("liquidity_check") == "passed"
    liquidity_tradability_score = _weighted_score(
        [
            (Decimal("0.65"), _score(100.0 if l2_liquidity_passed else 30.0)),
            (
                Decimal("0.35"),
                _score(float(min(Decimal("1"), l2_daily_completeness)) * 100.0)
                if l2_daily_completeness is not None
                else None,
            ),
        ]
    )
    early_turn_up_score = _decimal(best_feature.get("early_turn_up_score"))
    bottom_stabilization_score = _decimal(best_feature.get("bottom_stabilization_score"))
    decline_maturity_score = _decimal(best_feature.get("decline_maturity_score"))
    dragon_shape_score = _decimal(best_feature.get("dragon_shape_score"))
    turn_freshness_score = _decimal((effective_turn_candidate or {}).get("turn_freshness_score"))
    if turn_freshness_score is None:
        turn_freshness_score = early_turn_up_score
        source_gap_codes.append("turn_freshness_score_missing")
    late_rebound_penalty = _decimal((effective_turn_candidate or {}).get("late_rebound_penalty"))
    if late_rebound_penalty is None:
        late_rebound_penalty = Decimal("0")
        source_gap_codes.append("late_rebound_penalty_missing")
    breakout_readiness_score = _weighted_score(
        [
            (Decimal("0.45"), early_turn_up_score),
            (Decimal("0.25"), bottom_stabilization_score),
            (Decimal("0.30"), turn_freshness_score),
        ]
    )
    dragon_stage_score = _weighted_score(
        [
            (Decimal("0.35"), decline_maturity_score),
            (Decimal("0.35"), bottom_stabilization_score),
            (Decimal("0.30"), dragon_shape_score),
        ]
    )
    effective_status = (effective_turn_candidate or {}).get("l1_status")
    if not effective_status:
        source_gap_codes.append("effective_turn_candidate_missing")
    source_gap_count = len(source_gap_codes)
    source_gap_p0_count = sum(1 for code in source_gap_codes if code in P0_SOURCE_GAP_CODES)
    evidence_gap_penalty = _score(min(100.0, source_gap_count * 18.0))
    positive_score = _weighted_score(
        [
            (Decimal("0.18"), dragon_stage_score),
            (Decimal("0.18"), turn_freshness_score),
            (Decimal("0.20"), breakout_readiness_score),
            (Decimal("0.14"), capital_probe_score),
            (Decimal("0.10"), sector_context_score),
            (Decimal("0.10"), upside_room_score),
            (Decimal("0.10"), liquidity_tradability_score),
        ]
    )
    dragon_priority_score = None
    if positive_score is not None and false_reversal_risk is not None:
        dragon_priority_score = _score(
            float(positive_score)
            - float(false_reversal_risk) * 0.28
            - float(late_rebound_penalty) * 0.18
            - float(evidence_gap_penalty) * 0.12
        )
    else:
        source_gap_codes.append("dragon_priority_score_missing")
    source_gap_count = len(source_gap_codes)
    source_gap_p0_count = sum(1 for code in source_gap_codes if code in P0_SOURCE_GAP_CODES)
    l4_blocking_source_gap_count = sum(1 for code in source_gap_codes if code in L4_BLOCKING_SOURCE_GAP_CODES)

    if effective_status == "accepted" and l2_candidate.get("l2_status") == "passed":
        evidence_level = "L3_DEEP_CONFIRMED" if source_gap_p0_count == 0 else "L2_FILTER_PASSED"
    elif effective_status == "accepted":
        evidence_level = "L1_EFFECTIVE_TURN"
    elif effective_status == "backup_only":
        evidence_level = "L1_EFFECTIVE_TURN"
    else:
        evidence_level = "L1_EFFECTIVE_TURN"
    false_reversal_risk_for_gate = false_reversal_risk if false_reversal_risk is not None else Decimal("100")
    if l2_candidate.get("l2_status") != "passed" or false_reversal_risk_for_gate >= Decimal("70") or major_negative_event:
        dragon_state = "dragon_failed"
    elif (
        evidence_level == "L3_DEEP_CONFIRMED"
        and breakout_readiness_score is not None and breakout_readiness_score >= Decimal("70")
        and false_reversal_risk_for_gate <= Decimal("45")
        and upside_room_score is not None and upside_room_score >= Decimal("55")
        and liquidity_tradability_score is not None and liquidity_tradability_score >= Decimal("60")
        and source_gap_p0_count == 0
        and l4_blocking_source_gap_count == 0
        and not market_defensive_headwind
    ):
        evidence_level = "L4_DRAGON_READY"
        dragon_state = "dragon_ready"
    elif evidence_level == "L3_DEEP_CONFIRMED":
        dragon_state = "dragon_confirming"
    elif evidence_level == "L2_FILTER_PASSED":
        dragon_state = "dragon_turning_up"
    elif early_turn_up_score is not None and early_turn_up_score >= Decimal("65"):
        dragon_state = "dragon_turning_up"
    elif bottom_stabilization_score is not None and bottom_stabilization_score >= Decimal("60"):
        dragon_state = "dragon_bottoming"
    else:
        dragon_state = "dragon_expired"
    if dragon_priority_score is not None:
        dragon_priority_score = min(dragon_priority_score, EVIDENCE_LEVEL_CAPS[evidence_level]).quantize(Decimal("0.000001"))
    evidence_refs = _evidence_refs_from_bars(sorted_bars)
    positive_factors = ["低位结构已形成可观察基础", "有效抬头新鲜度纳入排序"]
    if capital_probe_score is not None:
        positive_factors.append("资金试探证据已纳入")
    if sector_context_score is not None:
        positive_factors.append("板块环境证据已纳入")
    negative_factors = list(l2_candidate.get("block_reasons") or [])
    if false_reversal_risk_for_gate >= Decimal("55"):
        negative_factors.append("假反弹风险偏高")
    if market_defensive_headwind:
        negative_factors.append("大盘防御态且下跌家数占比过高，禁止进入重点观察")
    if major_negative_event:
        negative_factors.append("存在重大负面事件")
    if source_gap_codes:
        negative_factors.append("存在深度证据缺口")
    payload = {
        "symbol": symbol,
        "trade_date": as_of_trading_day,
        "evidence_level": evidence_level,
        "dragon_state": dragon_state,
        "dragon_priority_score": str(dragon_priority_score) if dragon_priority_score is not None else None,
        "source_gap_codes": source_gap_codes,
        "source_gap_count": source_gap_count,
        "source_gap_p0_count": source_gap_p0_count,
    }
    return {
        "as_of_trading_day": as_of_trading_day,
        "trade_date": as_of_trading_day,
        "symbol": symbol,
        "instrument_id": int(instrument.get("instrument_id") or 0),
        "model_version": DRAGON_MODEL_VERSION,
        "evidence_level": evidence_level,
        "dragon_state": dragon_state,
        "dragon_head_score": dragon_priority_score,
        "dragon_priority_score": dragon_priority_score,
        "best_shape_window": int(best_feature.get("window_days") or best_feature.get("window") or 0),
        "decline_maturity_score": best_feature.get("decline_maturity_score"),
        "bottom_stabilization_score": best_feature.get("bottom_stabilization_score"),
        "early_turn_up_score": best_feature.get("early_turn_up_score"),
        "dragon_shape_score": best_feature.get("dragon_shape_score"),
        "mild_capital_probe_score": capital_probe_score,
        "liquidity_tradability_score": liquidity_tradability_score,
        "capital_probe_score": capital_probe_score,
        "sector_context_score": sector_context_score,
        "news_event_score": news_event_score,
        "market_context_score": market_context_score,
        "breakout_readiness_score": breakout_readiness_score,
        "upside_room_score": upside_room_score,
        "false_reversal_risk": false_reversal_risk,
        "evidence_gap_penalty": evidence_gap_penalty,
        "market_defensive_headwind": market_defensive_headwind,
        "major_negative_event": major_negative_event,
        "source_gap_codes": source_gap_codes,
        "source_gap_count": source_gap_count,
        "source_gap_p0_count": source_gap_p0_count,
        "main_positive_factors": positive_factors,
        "main_negative_factors": negative_factors,
        "next_confirmation_conditions": ["放量但不过热", "板块不退潮", "不跌破低点支撑"],
        "invalidation_conditions": ["跌破低点支撑", "假反弹风险升至70以上", "停牌或退市风险"],
        "evidence_refs": evidence_refs,
        "score_hash": _hash_payload(payload),
        "payload_hash": _hash_payload(payload),
        "as_of_time": effective_time,
        "captured_at": effective_time,
        "is_active": True,
    }


build_deep_analysis = _build_deep_analysis_v11
