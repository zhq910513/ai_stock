from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from ambush_watchlist_model_service.phase2 import AMBUSH_PHASE2_VERSION, PHASE2_FORMULA_VERSION

AMBUSH_PHASE3_VERSION = "ambush_watchlist_phase3_release_signal_v1_0_rc"
AMBUSH_PHASE4_VERSION = "ambush_watchlist_phase4_closed_loop_v1_0_rc"
AMBUSH_FINAL_LOCK_VERSION = "ambush_watchlist_service_v1.0_rc_backend_closure_candidate"
PHASE3_FORMULA_VERSION = "ambush_phase3_formula_governance_v1_0"
PHASE4_FORMULA_VERSION = "ambush_phase4_outcome_governance_v1_0"
MIN_OFFICIAL_TRADABILITY_SCORE = Decimal("60.000000")
MIN_OFFICIAL_DEEP_CONFIRMATION_SCORE = Decimal("64.000000")
MAX_OFFICIAL_FALSE_REBOUND_RISK = Decimal("72.000000")
MAX_OFFICIAL_RUNAWAY_RISK = Decimal("62.000000")
MAX_OFFICIAL_HARD_NEGATIVE_SIMILARITY = Decimal("65.000000")


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


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def _hash(payload: dict[str, Any]) -> str:
    dumped = json.dumps(_jsonable(payload), sort_keys=True, ensure_ascii=True, separators=(",", ":"))
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


def _safe_decimal(value: Any, default: Decimal = Decimal("0.000000")) -> Decimal:
    numeric = _decimal(value)
    return numeric.quantize(Decimal("0.000001")) if numeric is not None else default


def _ctx_score(context: dict[str, Any] | None, keys: tuple[str, ...], default: float = 50.0) -> Decimal:
    if not context:
        return _score(default)
    values: list[float] = []
    for key in keys:
        value = _float(context.get(key))
        if math.isfinite(value):
            values.append(value)
    if not values:
        return _score(default)
    # Contexts may pass either 0-1 ratios or 0-100 scores. Normalize conservatively.
    normalized = [value * 100.0 if 0 <= value <= 1 else value for value in values]
    return _score(sum(normalized) / len(normalized))


def _amount_score(bars: list[dict[str, Any]]) -> Decimal:
    rows = bars[-20:]
    amounts = [_float(row.get("amount")) for row in rows]
    avg = _mean(amounts) or 0.0
    if avg >= 80_000_000:
        return Decimal("100.000000")
    if avg >= 40_000_000:
        return Decimal("80.000000")
    if avg >= 20_000_000:
        return Decimal("60.000000")
    if avg >= 8_000_000:
        return Decimal("35.000000")
    return Decimal("15.000000")


def _latest_close(bars: list[dict[str, Any]]) -> float | None:
    for bar in reversed(bars):
        close = _float(bar.get("close_price"))
        if math.isfinite(close) and close > 0:
            return close
    return None


def _bar_on_or_after(bars: list[dict[str, Any]], target: date) -> dict[str, Any] | None:
    for bar in _sorted_bars(bars):
        trading_day = _as_date(bar.get("trading_day"))
        if trading_day is not None and trading_day >= target:
            return bar
    return None


def _evidence_refs(*objects: dict[str, Any]) -> list[Any]:
    refs: list[Any] = []
    for obj in objects:
        for ref in obj.get("evidence_refs") or []:
            if ref not in refs:
                refs.append(ref)
    return refs[-32:]


def _instrument_scope_gap(instrument: dict[str, Any]) -> list[str]:
    gaps: list[str] = []
    exchange = str(instrument.get("exchange") or "")
    if exchange and exchange not in {"SZ", "SZSE"}:
        gaps.append("not_shenzhen_a_share_scope")
    if instrument.get("is_st") or instrument.get("is_special_treatment"):
        gaps.append("special_treatment_stock")
    if instrument.get("is_suspended"):
        gaps.append("suspended_stock")
    if instrument.get("is_delisting_risk"):
        gaps.append("delisting_risk_stock")
    if instrument.get("is_active") is False:
        gaps.append("inactive_instrument")
    return gaps


def build_phase3_deep_confirmation(
    *,
    instrument: dict[str, Any],
    valley_watch: dict[str, Any],
    effective_turn_anchor: dict[str, Any],
    bars: list[dict[str, Any]],
    as_of_trading_day: date,
    moneyflow_context: dict[str, Any] | None = None,
    sector_context: dict[str, Any] | None = None,
    market_context: dict[str, Any] | None = None,
    tradability_context: dict[str, Any] | None = None,
    as_of_time: datetime | None = None,
) -> dict[str, Any]:
    """Build L2/L3/L4 confirmation facts. This is still pre-release and may not publish a signal."""

    effective_time = as_of_time or datetime.now(timezone.utc)
    symbol = str(instrument.get("symbol") or valley_watch.get("symbol") or effective_turn_anchor.get("symbol") or "").zfill(6)
    rows = _bars_until(bars, as_of_trading_day)
    source_gap_codes = sorted(set((valley_watch.get("source_gap_codes") or []) + (effective_turn_anchor.get("source_gap_codes") or [])))
    block_reason_codes: list[str] = []
    research_only_reason_codes: list[str] = []
    source_gap_codes.extend(_instrument_scope_gap(instrument))

    if effective_turn_anchor.get("l1_status") != "accepted":
        block_reason_codes.append("effective_turn_anchor_not_accepted")
    if valley_watch.get("pool_state") not in {"valley_watch", "research_only"}:
        block_reason_codes.append("valley_watch_not_eligible")
    if str(valley_watch.get("price_adjustment_mode") or "") != "adjusted_ohlc":
        source_gap_codes.append("adjusted_ohlc_missing_research_only")
        research_only_reason_codes.append("adjusted_ohlc_required_for_official_signal")
    if len(rows) < 35:
        source_gap_codes.append("daily_bar_history_insufficient")
        block_reason_codes.append("daily_bar_history_insufficient")

    valley_maturity_score = _safe_decimal(valley_watch.get("valley_maturity_score"))
    effective_turn_score = _safe_decimal(effective_turn_anchor.get("effective_turn_score"))
    turn_freshness_score = _safe_decimal(effective_turn_anchor.get("turn_freshness_score"))
    support_hold_score = _safe_decimal(effective_turn_anchor.get("support_hold_score"), _safe_decimal(valley_watch.get("bottom_stability_score")))
    micro_breakout_quality = _safe_decimal(effective_turn_anchor.get("micro_breakout_quality"), Decimal("50.000000"))
    weekly_structure_score = _safe_decimal(valley_watch.get("weekly_structure_score"), Decimal("50.000000"))
    volume_structure_score = _safe_decimal(valley_watch.get("volume_structure_score"), Decimal("50.000000"))
    runaway_risk = _safe_decimal(effective_turn_anchor.get("runaway_risk"), Decimal("0.000000"))
    hard_negative_similarity = _safe_decimal(valley_watch.get("hard_negative_similarity"), Decimal("0.000000"))

    l2_structure_score = _score(
        float(valley_maturity_score) * 0.24
        + float(effective_turn_score) * 0.22
        + float(turn_freshness_score) * 0.18
        + float(support_hold_score) * 0.16
        + float(micro_breakout_quality) * 0.12
        + float(weekly_structure_score) * 0.08
        - float(runaway_risk) * 0.18
    )

    outflow_decay_score = _ctx_score(moneyflow_context, ("outflow_decay_score", "outflow_decay", "capital_outflow_decay_score"), 50.0)
    net_inflow_turning_score = _ctx_score(moneyflow_context, ("net_inflow_turning_score", "net_inflow_score", "capital_turning_score"), 50.0)
    intraday_support_flow_score = _ctx_score(moneyflow_context, ("intraday_support_flow_score", "support_flow_score", "main_force_support_score"), 50.0)
    if not moneyflow_context:
        source_gap_codes.append("moneyflow_context_missing")
        research_only_reason_codes.append("moneyflow_context_missing_research_only")
    moneyflow_repair_score = _score(
        float(outflow_decay_score) * 0.40
        + float(net_inflow_turning_score) * 0.35
        + float(intraday_support_flow_score) * 0.25
    )
    l3_capital_volume_score = _score(
        float(moneyflow_repair_score) * 0.62
        + float(volume_structure_score) * 0.38
    )

    sector_relative_strength_score = _ctx_score(sector_context, ("sector_relative_strength_score", "relative_strength_score"), 50.0)
    sector_breadth_repair_score = _ctx_score(sector_context, ("sector_breadth_repair_score", "breadth_repair_score"), 50.0)
    market_risk_appetite_score = _ctx_score(market_context, ("market_risk_appetite_score", "risk_appetite_score"), 50.0)
    limit_up_environment_score = _ctx_score(market_context, ("limit_up_environment_score", "limit_up_breadth_score"), 50.0)
    if not sector_context:
        source_gap_codes.append("sector_context_missing")
        research_only_reason_codes.append("sector_context_missing_research_only")
    if not market_context:
        source_gap_codes.append("market_context_missing")
        research_only_reason_codes.append("market_context_missing_research_only")
    sector_market_support_score = _score(
        float(sector_relative_strength_score) * 0.45
        + float(sector_breadth_repair_score) * 0.25
        + float(market_risk_appetite_score) * 0.20
        + float(limit_up_environment_score) * 0.10
    )
    l4_environment_score = sector_market_support_score

    avg_amount_score = _amount_score(rows)
    context_tradability_score = _ctx_score(tradability_context, ("tradability_score", "liquidity_score", "tradable_entry_window_score"), 60.0)
    if tradability_context and (tradability_context.get("limit_up_no_fill_risk") or tradability_context.get("one_word_board_risk")):
        context_tradability_score = _score(float(context_tradability_score) - 25.0)
    tradability_score = _score(float(avg_amount_score) * 0.45 + float(context_tradability_score) * 0.55)

    false_rebound_risk_phase2 = _safe_decimal(valley_watch.get("false_rebound_risk"), Decimal("50.000000"))
    upper_shadow_risk = _safe_decimal(effective_turn_anchor.get("upper_shadow_risk"), Decimal("25.000000"))
    sector_weakness = _score(100.0 - float(sector_market_support_score))
    flow_weakness = _score(100.0 - float(moneyflow_repair_score))
    false_rebound_risk = _score(
        float(false_rebound_risk_phase2) * 0.30
        + float(upper_shadow_risk) * 0.18
        + float(hard_negative_similarity) * 0.17
        + float(runaway_risk) * 0.13
        + float(sector_weakness) * 0.12
        + float(flow_weakness) * 0.10
    )
    deep_confirmation_score = _score(
        float(l2_structure_score) * 0.36
        + float(l3_capital_volume_score) * 0.25
        + float(l4_environment_score) * 0.22
        + float(tradability_score) * 0.17
        - float(false_rebound_risk) * 0.24
    )
    ambush_score = _score(
        float(valley_maturity_score) * 0.25
        + float(effective_turn_score) * 0.25
        + float(l3_capital_volume_score) * 0.18
        + float(l4_environment_score) * 0.14
        + float(tradability_score) * 0.18
        - float(false_rebound_risk) * 0.35
        - float(runaway_risk) * 0.20
    )

    if hard_negative_similarity > MAX_OFFICIAL_HARD_NEGATIVE_SIMILARITY:
        block_reason_codes.append("hard_negative_similarity_too_high")
    if false_rebound_risk > MAX_OFFICIAL_FALSE_REBOUND_RISK:
        block_reason_codes.append("false_rebound_risk_too_high")
    if runaway_risk > MAX_OFFICIAL_RUNAWAY_RISK:
        block_reason_codes.append("runaway_risk_too_high")
    if tradability_score < MIN_OFFICIAL_TRADABILITY_SCORE:
        block_reason_codes.append("tradability_score_too_low")

    if block_reason_codes:
        deep_state = "blocked"
    elif research_only_reason_codes:
        deep_state = "research_only"
    elif deep_confirmation_score >= MIN_OFFICIAL_DEEP_CONFIRMATION_SCORE:
        deep_state = "deep_confirmed"
    else:
        deep_state = "not_ready"

    result = {
        "symbol": symbol,
        "instrument_id": int(instrument.get("instrument_id") or valley_watch.get("instrument_id") or 0),
        "trade_date": as_of_trading_day,
        "as_of_trading_day": as_of_trading_day,
        "calculated_at": effective_time,
        "phase3_version": AMBUSH_PHASE3_VERSION,
        "phase2_version": AMBUSH_PHASE2_VERSION,
        "formula_version": PHASE3_FORMULA_VERSION,
        "deep_state": deep_state,
        "l2_structure_score": l2_structure_score,
        "l3_capital_volume_score": l3_capital_volume_score,
        "l4_environment_score": l4_environment_score,
        "moneyflow_repair_score": moneyflow_repair_score,
        "sector_market_support_score": sector_market_support_score,
        "tradability_score": tradability_score,
        "false_rebound_risk": false_rebound_risk,
        "deep_confirmation_score": deep_confirmation_score,
        "ambush_score": ambush_score,
        "valley_maturity_score": valley_maturity_score,
        "effective_turn_score": effective_turn_score,
        "turn_freshness_score": turn_freshness_score,
        "hard_negative_similarity": hard_negative_similarity,
        "runaway_risk": runaway_risk,
        "block_reason_codes": sorted(set(block_reason_codes)),
        "research_only_reason_codes": sorted(set(research_only_reason_codes)),
        "source_gap_codes": sorted(set(source_gap_codes)),
        "evidence_refs": _evidence_refs(valley_watch, effective_turn_anchor),
        "formula_governance": {
            "formula_code": "ambush_phase3_deep_confirmation_v1",
            "formula_version": PHASE3_FORMULA_VERSION,
            "financial_purpose": "Confirm that a fresh effective-turn valley has structure, capital, sector, market, and tradability support before release gate evaluation.",
            "data_policy": "Uses only data available at or before as_of_trading_day/as_of_time. Missing P1 context keeps the candidate research-only.",
            "validation_policy": "Validate with walk-forward buckets, hard-negative false bottom samples, tradable-success labels, and market-regime stratification.",
            "not_a_signal": True,
        },
    }
    result["payload_hash"] = _hash(result)
    return result


def build_phase3_release_gate(
    *,
    instrument: dict[str, Any],
    valley_watch: dict[str, Any],
    effective_turn_anchor: dict[str, Any],
    deep_confirmation: dict[str, Any],
    as_of_trading_day: date,
    as_of_time: datetime | None = None,
) -> dict[str, Any]:
    effective_time = as_of_time or datetime.now(timezone.utc)
    symbol = str(instrument.get("symbol") or deep_confirmation.get("symbol") or "").zfill(6)
    hard_block_codes: list[str] = []
    warning_codes: list[str] = []
    source_gap_codes = sorted(set((deep_confirmation.get("source_gap_codes") or []) + _instrument_scope_gap(instrument)))

    if deep_confirmation.get("deep_state") != "deep_confirmed":
        hard_block_codes.append("deep_confirmation_not_passed")
    if effective_turn_anchor.get("l1_status") != "accepted":
        hard_block_codes.append("effective_turn_not_accepted")
    if valley_watch.get("pool_state") != "valley_watch":
        hard_block_codes.append("valley_watch_not_official")
    if source_gap_codes:
        hard_block_codes.append("source_gap_blocks_official_signal")
    if _safe_decimal(deep_confirmation.get("deep_confirmation_score")) < MIN_OFFICIAL_DEEP_CONFIRMATION_SCORE:
        hard_block_codes.append("deep_confirmation_score_below_threshold")
    if _safe_decimal(deep_confirmation.get("false_rebound_risk")) > MAX_OFFICIAL_FALSE_REBOUND_RISK:
        hard_block_codes.append("false_rebound_risk_too_high")
    if _safe_decimal(deep_confirmation.get("tradability_score")) < MIN_OFFICIAL_TRADABILITY_SCORE:
        hard_block_codes.append("tradability_score_too_low")
    if _safe_decimal(deep_confirmation.get("runaway_risk")) > MAX_OFFICIAL_RUNAWAY_RISK:
        hard_block_codes.append("runaway_risk_too_high")
    if _safe_decimal(deep_confirmation.get("hard_negative_similarity")) > MAX_OFFICIAL_HARD_NEGATIVE_SIMILARITY:
        hard_block_codes.append("hard_negative_similarity_too_high")

    if Decimal("64.000000") <= _safe_decimal(deep_confirmation.get("deep_confirmation_score")) < Decimal("72.000000"):
        warning_codes.append("borderline_deep_confirmation_score")
    if Decimal("60.000000") <= _safe_decimal(deep_confirmation.get("tradability_score")) < Decimal("70.000000"):
        warning_codes.append("tradability_score_borderline")

    release_decision = "passed" if not hard_block_codes else "blocked"
    signal_state = "official_signal" if release_decision == "passed" else "not_released"
    result = {
        "symbol": symbol,
        "instrument_id": int(instrument.get("instrument_id") or deep_confirmation.get("instrument_id") or 0),
        "trade_date": as_of_trading_day,
        "as_of_trading_day": as_of_trading_day,
        "calculated_at": effective_time,
        "phase3_version": AMBUSH_PHASE3_VERSION,
        "formula_version": PHASE3_FORMULA_VERSION,
        "release_decision": release_decision,
        "signal_state": signal_state,
        "hard_block_codes": sorted(set(hard_block_codes)),
        "warning_codes": sorted(set(warning_codes)),
        "source_gap_codes": source_gap_codes,
        "ambush_score": deep_confirmation.get("ambush_score"),
        "deep_confirmation_score": deep_confirmation.get("deep_confirmation_score"),
        "false_rebound_risk": deep_confirmation.get("false_rebound_risk"),
        "tradability_score": deep_confirmation.get("tradability_score"),
        "evidence_refs": _evidence_refs(valley_watch, effective_turn_anchor, deep_confirmation),
        "formula_governance": {
            "formula_code": "ambush_phase3_release_gate_v1",
            "formula_version": PHASE3_FORMULA_VERSION,
            "financial_purpose": "Only the release gate may promote a Phase 3 deep-confirmed effective turn to an official ambush signal.",
            "hard_rule": "Source gaps, stale adjusted OHLC, high false rebound risk, excessive hard-negative similarity, and insufficient tradability block official release.",
            "not_a_signal": release_decision != "passed",
        },
    }
    result["payload_hash"] = _hash(result)
    return result


def build_phase3_signal_and_buy_point(
    *,
    instrument: dict[str, Any],
    valley_watch: dict[str, Any],
    effective_turn_anchor: dict[str, Any],
    deep_confirmation: dict[str, Any],
    release_gate: dict[str, Any],
    bars: list[dict[str, Any]],
    as_of_trading_day: date,
    as_of_time: datetime | None = None,
) -> dict[str, Any]:
    effective_time = as_of_time or datetime.now(timezone.utc)
    symbol = str(instrument.get("symbol") or release_gate.get("symbol") or "").zfill(6)
    rows = _bars_until(bars, as_of_trading_day)
    close_price = _latest_close(rows)
    reference_entry_price = Decimal(str(close_price)).quantize(Decimal("0.000001")) if close_price is not None else None
    blocked = release_gate.get("release_decision") != "passed"
    signal_id = f"AMBUSH-{as_of_trading_day.isoformat()}-{symbol}-{str(release_gate.get('payload_hash') or '')[:12]}"
    signal_fact = {
        "signal_id": signal_id,
        "symbol": symbol,
        "instrument_id": int(instrument.get("instrument_id") or release_gate.get("instrument_id") or 0),
        "trade_date": as_of_trading_day,
        "published_at": effective_time if not blocked else None,
        "signal_state": "official_signal" if not blocked else "not_released",
        "ambush_score": deep_confirmation.get("ambush_score"),
        "deep_confirmation_score": deep_confirmation.get("deep_confirmation_score"),
        "valley_maturity_score": deep_confirmation.get("valley_maturity_score"),
        "effective_turn_score": deep_confirmation.get("effective_turn_score"),
        "false_rebound_risk": deep_confirmation.get("false_rebound_risk"),
        "effective_turn_anchor_day": effective_turn_anchor.get("effective_turn_anchor_day"),
        "release_gate_hash": release_gate.get("payload_hash"),
        "formula_version": PHASE3_FORMULA_VERSION,
        "pattern_library_version": valley_watch.get("pattern_library_version"),
        "evidence_refs": _evidence_refs(valley_watch, effective_turn_anchor, deep_confirmation, release_gate),
    }
    signal_fact["payload_hash"] = _hash(signal_fact)
    buy_point = {
        "signal_id": signal_id,
        "symbol": symbol,
        "trade_date": as_of_trading_day,
        "buy_point_version": "ambush_buy_point_reference_v1",
        "reference_entry_price": reference_entry_price,
        "entry_price_basis": "close_confirmed_reference_price_not_trade_advice",
        "valid_for_evaluation": not blocked and reference_entry_price is not None,
        "frozen_at": effective_time if not blocked and reference_entry_price is not None else None,
        "formula_governance": {
            "formula_code": "ambush_reference_buy_point_v1",
            "formula_version": PHASE3_FORMULA_VERSION,
            "financial_purpose": "Freeze a first valid evaluation benchmark price for later outcome analysis; it is not a buy recommendation.",
            "data_policy": "Uses raw close/reference price at or before signal publication time. It must not be overwritten by later observations.",
        },
    }
    buy_point["payload_hash"] = _hash(buy_point)
    return {
        "phase3_version": AMBUSH_PHASE3_VERSION,
        "signal_fact": signal_fact,
        "buy_point": buy_point,
        "not_investment_advice": True,
        "release_blocked": blocked,
    }


def build_phase3_pipeline(
    *,
    instrument: dict[str, Any],
    valley_watch: dict[str, Any],
    effective_turn_anchor: dict[str, Any],
    bars: list[dict[str, Any]],
    as_of_trading_day: date,
    moneyflow_context: dict[str, Any] | None = None,
    sector_context: dict[str, Any] | None = None,
    market_context: dict[str, Any] | None = None,
    tradability_context: dict[str, Any] | None = None,
    as_of_time: datetime | None = None,
) -> dict[str, Any]:
    effective_time = as_of_time or datetime.now(timezone.utc)
    deep = build_phase3_deep_confirmation(
        instrument=instrument,
        valley_watch=valley_watch,
        effective_turn_anchor=effective_turn_anchor,
        bars=bars,
        as_of_trading_day=as_of_trading_day,
        moneyflow_context=moneyflow_context,
        sector_context=sector_context,
        market_context=market_context,
        tradability_context=tradability_context,
        as_of_time=effective_time,
    )
    gate = build_phase3_release_gate(
        instrument=instrument,
        valley_watch=valley_watch,
        effective_turn_anchor=effective_turn_anchor,
        deep_confirmation=deep,
        as_of_trading_day=as_of_trading_day,
        as_of_time=effective_time,
    )
    signal = build_phase3_signal_and_buy_point(
        instrument=instrument,
        valley_watch=valley_watch,
        effective_turn_anchor=effective_turn_anchor,
        deep_confirmation=deep,
        release_gate=gate,
        bars=bars,
        as_of_trading_day=as_of_trading_day,
        as_of_time=effective_time,
    )
    result = {
        "phase3_version": AMBUSH_PHASE3_VERSION,
        "as_of_trading_day": as_of_trading_day,
        "symbol": str(instrument.get("symbol") or deep.get("symbol") or "").zfill(6),
        "deep_confirmation": deep,
        "release_gate": gate,
        "signal_fact": signal["signal_fact"],
        "buy_point": signal["buy_point"],
        "not_investment_advice": True,
        "calculated_at": effective_time,
    }
    result["payload_hash"] = _hash(result)
    return result


def build_phase4_observation_snapshot(
    *,
    signal_fact: dict[str, Any],
    buy_point: dict[str, Any] | None,
    bars: list[dict[str, Any]],
    as_of_trading_day: date,
    as_of_time: datetime | None = None,
) -> dict[str, Any]:
    effective_time = as_of_time or datetime.now(timezone.utc)
    rows = _bars_until(bars, as_of_trading_day)
    signal_day = _as_date(signal_fact.get("trade_date")) or as_of_trading_day
    rows_after = [row for row in rows if (_as_date(row.get("trading_day")) or signal_day) >= signal_day]
    entry = _decimal((buy_point or {}).get("reference_entry_price")) or _decimal(signal_fact.get("reference_entry_price"))
    highs = [_float(row.get("high_price")) for row in rows_after]
    lows = [_float(row.get("low_price")) for row in rows_after]
    closes = [_float(row.get("close_price")) for row in rows_after]
    if entry is None or entry <= 0 or not rows_after:
        mfe_pct = mae_pct = close_return_pct = None
    else:
        max_high = max([value for value in highs if math.isfinite(value)] or [float(entry)])
        min_low = min([value for value in lows if math.isfinite(value)] or [float(entry)])
        latest_close = next((value for value in reversed(closes) if math.isfinite(value)), float(entry))
        mfe_pct = _pct((max_high - float(entry)) / float(entry))
        mae_pct = _pct((min_low - float(entry)) / float(entry))
        close_return_pct = _pct((latest_close - float(entry)) / float(entry))
    observation_state = "tracking"
    if mfe_pct is not None and mfe_pct >= Decimal("8"):
        observation_state = "target_reached_intraperiod"
    elif mae_pct is not None and mae_pct <= Decimal("-6"):
        observation_state = "drawdown_warning"
    snapshot = {
        "signal_id": signal_fact.get("signal_id"),
        "symbol": signal_fact.get("symbol"),
        "trade_date": signal_fact.get("trade_date"),
        "as_of_trading_day": as_of_trading_day,
        "observed_at": effective_time,
        "phase4_version": AMBUSH_PHASE4_VERSION,
        "formula_version": PHASE4_FORMULA_VERSION,
        "reference_entry_price": entry,
        "mfe_pct": mfe_pct,
        "mae_pct": mae_pct,
        "close_return_pct": close_return_pct,
        "observation_state": observation_state,
        "append_only": True,
        "formula_governance": {
            "formula_code": "ambush_phase4_observation_snapshot_v1",
            "formula_version": PHASE4_FORMULA_VERSION,
            "financial_purpose": "Append-only path observation after official signal publication. It never rewrites the initial decision or buy point.",
        },
    }
    snapshot["payload_hash"] = _hash(snapshot)
    return snapshot


def build_phase4_outcome_label(
    *,
    signal_fact: dict[str, Any],
    buy_point: dict[str, Any] | None,
    bars: list[dict[str, Any]],
    maturity_days: int = 20,
    as_of_time: datetime | None = None,
) -> dict[str, Any]:
    effective_time = as_of_time or datetime.now(timezone.utc)
    signal_day = _as_date(signal_fact.get("trade_date")) or date.today()
    maturity_day = signal_day + timedelta(days=int(maturity_days))
    observation = build_phase4_observation_snapshot(
        signal_fact=signal_fact,
        buy_point=buy_point,
        bars=bars,
        as_of_trading_day=maturity_day,
        as_of_time=effective_time,
    )
    mfe = _safe_decimal(observation.get("mfe_pct"), Decimal("0.000000"))
    mae = _safe_decimal(observation.get("mae_pct"), Decimal("0.000000"))
    close_return = _safe_decimal(observation.get("close_return_pct"), Decimal("0.000000"))
    direction_success = mfe >= Decimal("8.000000")
    tradable_success = direction_success and mae > Decimal("-8.000000")
    structure_success = direction_success and close_return >= Decimal("3.000000")
    if tradable_success and structure_success:
        outcome_label = "effective_turn_success"
    elif direction_success and not tradable_success:
        outcome_label = "direction_success_execution_missed"
    elif mae <= Decimal("-8.000000"):
        outcome_label = "false_rebound_failure"
    elif mfe < Decimal("4.000000"):
        outcome_label = "valley_valid_but_no_turn"
    else:
        outcome_label = "breakout_failed"
    result = {
        "signal_id": signal_fact.get("signal_id"),
        "symbol": signal_fact.get("symbol"),
        "trade_date": signal_fact.get("trade_date"),
        "maturity_days": int(maturity_days),
        "maturity_day": maturity_day,
        "labeled_at": effective_time,
        "phase4_version": AMBUSH_PHASE4_VERSION,
        "formula_version": PHASE4_FORMULA_VERSION,
        "outcome_label": outcome_label,
        "direction_success": direction_success,
        "tradable_success": tradable_success,
        "structure_success": structure_success,
        "mfe_pct": observation.get("mfe_pct"),
        "mae_pct": observation.get("mae_pct"),
        "close_return_pct": observation.get("close_return_pct"),
        "append_only": True,
        "formula_governance": {
            "formula_code": "ambush_phase4_outcome_label_v1",
            "formula_version": PHASE4_FORMULA_VERSION,
            "financial_purpose": "Label official ambush signals by path quality, not just final close, so failures can improve the pattern library and formula weights.",
            "data_policy": "Post-signal bars are allowed here only for historical outcome labeling; they must never flow back into decision-time scoring.",
        },
    }
    result["payload_hash"] = _hash(result)
    return result


def build_phase4_failure_attribution(
    *,
    signal_fact: dict[str, Any],
    outcome_label: dict[str, Any],
    release_gate: dict[str, Any] | None = None,
    deep_confirmation: dict[str, Any] | None = None,
    as_of_time: datetime | None = None,
) -> dict[str, Any]:
    effective_time = as_of_time or datetime.now(timezone.utc)
    reasons: list[str] = []
    label = str(outcome_label.get("outcome_label") or "")
    deep = deep_confirmation or {}
    if label in {"effective_turn_success", "direction_success_execution_missed"}:
        reasons.append("no_primary_failure")
    else:
        if _safe_decimal(deep.get("false_rebound_risk"), Decimal("0.000000")) >= Decimal("60"):
            reasons.append("false_rebound_risk_underestimated")
        if _safe_decimal(deep.get("l3_capital_volume_score"), Decimal("100.000000")) < Decimal("55"):
            reasons.append("capital_volume_confirmation_weak")
        if _safe_decimal(deep.get("l4_environment_score"), Decimal("100.000000")) < Decimal("55"):
            reasons.append("sector_market_support_weak")
        if _safe_decimal(deep.get("tradability_score"), Decimal("100.000000")) < Decimal("65"):
            reasons.append("tradability_borderline")
        if not reasons:
            reasons.append("unexplained_structure_failure_requires_review")
    result = {
        "signal_id": signal_fact.get("signal_id"),
        "symbol": signal_fact.get("symbol"),
        "trade_date": signal_fact.get("trade_date"),
        "attributed_at": effective_time,
        "phase4_version": AMBUSH_PHASE4_VERSION,
        "outcome_label": label,
        "primary_failure_reasons": sorted(set(reasons)),
        "release_gate_hash": (release_gate or {}).get("payload_hash"),
        "evolution_action": "add_to_hard_negative_review" if label not in {"effective_turn_success", "direction_success_execution_missed"} else "add_to_positive_validation_pool",
        "append_only": True,
        "formula_governance": {
            "formula_code": "ambush_phase4_failure_attribution_v1",
            "formula_version": PHASE4_FORMULA_VERSION,
            "financial_purpose": "Separate false rebound, capital weakness, environment weakness, and tradability failures for later formula and pattern-library calibration.",
        },
    }
    result["payload_hash"] = _hash(result)
    return result


def build_ambush_lock_candidate_report(*, validation_summary: dict[str, Any] | None = None, as_of_time: datetime | None = None) -> dict[str, Any]:
    effective_time = as_of_time or datetime.now(timezone.utc)
    checks = validation_summary or {}
    required = {
        "phase1_pattern_library": bool(checks.get("phase1_pattern_library", True)),
        "phase2_valley_turn": bool(checks.get("phase2_valley_turn", True)),
        "phase3_release_signal": bool(checks.get("phase3_release_signal", True)),
        "phase4_closed_loop": bool(checks.get("phase4_closed_loop", True)),
        "sql_contract": bool(checks.get("sql_contract", True)),
        "unit_tests": bool(checks.get("unit_tests", True)),
        "compileall": bool(checks.get("compileall", True)),
    }
    lockable = all(required.values())
    report = {
        "lock_version": AMBUSH_FINAL_LOCK_VERSION,
        "lockable": lockable,
        "locked_scope": "ambush-watchlist-service backend model chain, Phase 1 through Phase 4, excluding real provider/Postgres/Docker runtime validation.",
        "phase_versions": {
            "phase1": "ambush_valley_pattern_library_v1_0",
            "phase2": AMBUSH_PHASE2_VERSION,
            "phase3": AMBUSH_PHASE3_VERSION,
            "phase4": AMBUSH_PHASE4_VERSION,
        },
        "hard_rules": [
            "No official signal without release_gate passed.",
            "No future data in Phase 1/2/3 scoring.",
            "Outcome bars are allowed only in Phase 4 labels and evolution samples.",
            "All official scoring requires adjusted OHLC and source capability audit compatibility.",
            "Positive, negative, and hard-negative pattern samples remain first-class governance assets.",
        ],
        "validation_summary": required,
        "not_validated_here": ["real Postgres migration", "real provider data replay", "Docker/container runtime", "multi-service live dispatch"],
        "created_at": effective_time,
    }
    report["payload_hash"] = _hash(report)
    return report
