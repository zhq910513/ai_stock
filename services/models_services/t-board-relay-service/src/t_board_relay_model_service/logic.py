from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from t_board_relay_model_service.config import (
    FEATURE_VERSION,
    MODEL_CODE,
    MODEL_VERSION,
    RULE_VERSION,
    TBoardRelayRuleConfig,
    get_rule_config,
)


def utc_run_id(prefix: str = "t-board-relay") -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}"


def jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [jsonable(item) for item in value]
    return value


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return None
    if isinstance(value, (int, float, Decimal)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y"}:
            return True
        if normalized in {"false", "0", "no", "n"}:
            return False
    return None


def _first(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return None


def _q(value: Decimal | None, places: str = "0.000001") -> Decimal | None:
    if value is None:
        return None
    return value.quantize(Decimal(places), rounding=ROUND_HALF_UP)


def _ratio(numerator: Decimal | None, denominator: Decimal | None) -> Decimal | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return _q(numerator / denominator, "0.00000001")


def _score(value: Decimal | None, multiplier: Decimal = Decimal("100")) -> Decimal | None:
    if value is None:
        return None
    return _q(max(Decimal("0"), min(Decimal("100"), value * multiplier)), "0.01")


def _contract_response(output_key: str, result: dict[str, Any], gaps: list[str]) -> dict[str, Any]:
    return {
        "model_name": MODEL_CODE,
        "model_version": MODEL_VERSION,
        "structured_output": {
            output_key: jsonable(result),
            "rule_config": jsonable(get_rule_config().__dict__),
        },
        "jarvis_payload": build_jarvis_payload(result, gaps),
        "contract_gaps": sorted(set(gaps)),
    }


def build_jarvis_payload(result: dict[str, Any], gaps: list[str]) -> dict[str, Any]:
    return jsonable(
        {
            "schema_version": "jarvis_model_payload_v1",
            "model_name": MODEL_CODE,
            "model_version": MODEL_VERSION,
            "symbol": result.get("canonical_symbol") or result.get("symbol"),
            "business_objective": {
                "model_positioning": "T-board three-day relay behavior research",
                "sellability_rule": "A_SHARE_T_PLUS_1",
                "not_a_trading_system": True,
            },
            "current_result": {
                "state": result.get("candidate_status")
                or result.get("entry_trigger_status")
                or result.get("post_entry_status")
                or result.get("day3_action")
                or result.get("outcome_label"),
                "score": result.get("relay_consensus_score")
                or result.get("seal_commitment_score")
                or result.get("control_failure_score"),
            },
            "score_breakdown": {
                "seal_commitment_score": result.get("seal_commitment_score"),
                "disagreement_absorption_score": result.get("disagreement_absorption_score"),
                "relay_consensus_score": result.get("relay_consensus_score"),
                "fake_seal_trap_risk_score": result.get("fake_seal_trap_risk_score"),
                "control_failure_score": result.get("control_failure_score"),
            },
            "source_gap_codes": sorted(set(gaps)),
            "guardrails": {
                "jarvis_can_mutate_scores": False,
                "jarvis_can_mutate_state": False,
                "jarvis_can_mutate_labels": False,
                "can_place_order": False,
                "dominant_capital_intent_is_hypothesis_only": True,
                "requires_source_or_dynamic_feature_evidence": True,
            },
        }
    )


def _day1_candidate_id(row: dict[str, Any], symbol: str | None, trade_date: str | None) -> str:
    existing = _first(row, "day1_candidate_id", "candidate_id")
    if existing:
        return str(existing)
    return f"tbr-day1-{symbol or 'UNKNOWN'}-{trade_date or 'UNKNOWN'}"


def build_day1_candidate(row: dict[str, Any], *, trade_date: str | None = None, config: TBoardRelayRuleConfig | None = None) -> dict[str, Any]:
    config = config or get_rule_config()
    symbol = _first(row, "canonical_symbol", "symbol")
    row_trade_date = str(_first(row, "trade_date", "trading_day", "day1_trade_date") or trade_date or "")

    open_price = _decimal(_first(row, "open_price", "open"))
    high_price = _decimal(_first(row, "high_price", "high"))
    low_price = _decimal(_first(row, "low_price", "low"))
    close_price = _decimal(_first(row, "close_price", "close"))
    pre_close_price = _decimal(_first(row, "pre_close_price", "pre_close"))
    up_limit_price = _decimal(_first(row, "up_limit_price", "limit_up_price"))
    float_market_cap = _decimal(_first(row, "float_market_cap", "float_mcap"))
    limit_open_count = _decimal(_first(row, "limit_open_count", "open_board_count"))
    close_on_limit_flag = _bool(_first(row, "close_on_limit_flag"))
    is_one_word_limit = _bool(_first(row, "is_one_word_limit", "is_one_word_board"))

    gaps: list[str] = []
    if not symbol:
        gaps.append("source_gap:instrument_identity")
    if None in {open_price, high_price, low_price, close_price}:
        gaps.append("source_gap:daily_bar_missing")
    if up_limit_price is None:
        gaps.append("source_gap:limit_price_missing")
    if float_market_cap is None:
        gaps.append("source_gap:float_market_cap_missing")
    if limit_open_count is None:
        gaps.append("source_gap:limit_event_missing")
    if close_on_limit_flag is None:
        gaps.append("source_gap:close_on_limit_flag_missing")
    if is_one_word_limit is None:
        gaps.append("source_gap:one_word_limit_flag_missing")

    final_seal = _decimal(_first(row, "final_seal_order_amount"))
    max_seal = _decimal(_first(row, "max_seal_order_amount"))
    avg_seal = _decimal(_first(row, "avg_seal_order_amount_after_reseal", "avg_reseal_order_amount"))
    if final_seal is None:
        gaps.append("source_gap:seal_order_snapshot_missing")

    final_ratio = _ratio(final_seal, float_market_cap)
    max_ratio = _ratio(max_seal, float_market_cap)
    avg_ratio = _ratio(avg_seal, float_market_cap)
    float_pass = (
        float_market_cap is not None
        and config.day1_float_market_cap_min <= float_market_cap <= config.day1_float_market_cap_max
    )
    strict_t_board = (
        open_price is not None
        and high_price is not None
        and low_price is not None
        and close_price is not None
        and up_limit_price is not None
        and limit_open_count is not None
        and close_on_limit_flag is True
        and is_one_word_limit is False
        and open_price == up_limit_price
        and high_price == up_limit_price
        and close_price == up_limit_price
        and low_price < up_limit_price
        and limit_open_count >= 1
    )

    seal_score = _score(final_ratio, Decimal("10000"))
    if seal_score is not None and close_on_limit_flag:
        seal_score = min(Decimal("100"), seal_score + Decimal("12"))
    open_minutes = _decimal(_first(row, "total_open_board_minutes")) or Decimal("0")
    drawdown = _decimal(_first(row, "max_open_board_drawdown_pct")) or Decimal("0")
    reseal_speed = _decimal(_first(row, "reseal_speed_seconds")) or Decimal("600")
    disagreement_score = max(
        Decimal("0"),
        min(Decimal("100"), Decimal("82") - open_minutes * Decimal("0.9") - drawdown * Decimal("200") - reseal_speed / Decimal("30")),
    )
    fake_risk = None
    if seal_score is not None:
        fake_risk = max(Decimal("0"), min(Decimal("100"), Decimal("100") - ((seal_score + disagreement_score) / Decimal("2"))))

    if gaps and any(gap in gaps for gap in {
        "source_gap:instrument_identity",
        "source_gap:daily_bar_missing",
        "source_gap:limit_price_missing",
        "source_gap:float_market_cap_missing",
        "source_gap:limit_event_missing",
        "source_gap:close_on_limit_flag_missing",
        "source_gap:one_word_limit_flag_missing",
    }):
        status = "data_blocked"
        reject_reason = "p0_source_gap"
    elif not strict_t_board:
        status = "rejected"
        reject_reason = "not_t_board"
    elif not float_pass:
        status = "rejected"
        reject_reason = "float_market_cap_out_of_range"
    else:
        status = "qualified"
        reject_reason = None

    if status == "qualified":
        if seal_score is not None and seal_score >= 78 and fake_risk is not None and fake_risk <= 25:
            intent = "TRUE_RELAY_INTENT"
        elif disagreement_score >= 70:
            intent = "WASH_AND_RESEAL"
        elif fake_risk is not None and fake_risk >= 70:
            intent = "FAKE_SEAL_RISK"
        else:
            intent = "WEAK_RESEAL"
    elif status == "data_blocked":
        intent = "DATA_INSUFFICIENT"
    else:
        intent = "DISTRIBUTION_SUSPECTED"

    return {
        "day1_candidate_id": _day1_candidate_id(row, str(symbol) if symbol else None, row_trade_date),
        "canonical_symbol": symbol,
        "stock_name": _first(row, "stock_name", "name"),
        "trade_date": row_trade_date or None,
        "open_price": open_price,
        "high_price": high_price,
        "low_price": low_price,
        "close_price": close_price,
        "pre_close_price": pre_close_price,
        "up_limit_price": up_limit_price,
        "is_t_board": strict_t_board,
        "is_one_word_limit": is_one_word_limit,
        "limit_open_count": limit_open_count,
        "close_on_limit_flag": close_on_limit_flag,
        "first_open_board_time": _first(row, "first_open_board_time"),
        "last_reseal_time": _first(row, "last_reseal_time"),
        "total_open_board_minutes": _first(row, "total_open_board_minutes"),
        "max_open_board_drawdown_pct": _first(row, "max_open_board_drawdown_pct"),
        "float_market_cap": float_market_cap,
        "float_market_cap_pass": float_pass,
        "float_market_cap_min_config": config.day1_float_market_cap_min,
        "float_market_cap_max_config": config.day1_float_market_cap_max,
        "final_seal_order_amount": final_seal,
        "max_seal_order_amount": max_seal,
        "avg_seal_order_amount_after_reseal": avg_seal,
        "final_seal_to_float_mcap_ratio": final_ratio,
        "max_seal_to_float_mcap_ratio": max_ratio,
        "avg_reseal_to_float_mcap_ratio": avg_ratio,
        "seal_commitment_score": _q(seal_score, "0.01"),
        "disagreement_absorption_score": _q(disagreement_score, "0.01"),
        "fake_seal_trap_risk_score": _q(fake_risk, "0.01"),
        "day1_capital_intent_hypothesis": intent,
        "candidate_status": status,
        "reject_reason": reject_reason,
        "model_version": MODEL_VERSION,
        "feature_version": FEATURE_VERSION,
        "rule_version": RULE_VERSION,
        "source_gap_codes": sorted(set(gaps)),
    }


def build_day1_scan(rows: list[dict[str, Any]], *, trade_date: str | None = None) -> dict[str, Any]:
    candidates = [build_day1_candidate(row, trade_date=trade_date) for row in rows]
    return {
        "contract_kind": "t_board_day1_scan_v1",
        "model_code": MODEL_CODE,
        "trade_date": trade_date,
        "candidate_count": len(candidates),
        "qualified_count": sum(1 for item in candidates if item["candidate_status"] == "qualified"),
        "data_blocked_count": sum(1 for item in candidates if item["candidate_status"] == "data_blocked"),
        "candidates": candidates,
    }


def _market_context_status(payload: dict[str, Any]) -> str:
    explicit = _first(payload, "market_context_status")
    if explicit:
        return str(explicit)
    acceleration = _decimal(_first(payload, "market_return_acceleration_rolling", "index_acceleration_rolling"))
    limit_ratio = _decimal(_first(payload, "limit_up_ratio_rolling"))
    moneyflow = _decimal(_first(payload, "market_net_moneyflow_rolling"))
    if acceleration is None and limit_ratio is None and moneyflow is None:
        return "data_degraded"
    if (acceleration is not None and acceleration < 0) and (limit_ratio is not None and limit_ratio < Decimal("0.01")):
        return "weak"
    if moneyflow is not None and moneyflow > 0 and acceleration is not None and acceleration >= 0:
        return "supportive"
    return "neutral"


def build_day2_watch(payload: dict[str, Any]) -> dict[str, Any]:
    config = get_rule_config()
    symbol = _first(payload, "canonical_symbol", "symbol")
    last_price = _decimal(_first(payload, "last_price_at_watch", "last_price", "last_price_at_trigger"))
    up_limit_price = _decimal(_first(payload, "up_limit_price"))
    distance = _decimal(_first(payload, "distance_to_up_limit_pct", "day2_distance_to_up_limit_pct"))
    if distance is None and last_price is not None and up_limit_price not in (None, Decimal("0")):
        distance = _q((up_limit_price - last_price) / up_limit_price, "0.000001")
    gaps: list[str] = []
    if distance is None:
        gaps.append("source_gap:minute_bar_or_realtime_quote_missing")
    if up_limit_price is None:
        gaps.append("source_gap:limit_price_missing")
    if not payload.get("dynamic_feature_bundle") and not payload.get("dynamic_feature_run_id"):
        gaps.append("source_gap:dynamic_feature_bundle_missing")

    near_limit = distance is not None and distance <= config.day2_near_limit_threshold_pct
    market_status = _market_context_status(payload)
    watch_status = "near_limit_reached" if near_limit else "rolling_watch"
    if gaps and "source_gap:minute_bar_or_realtime_quote_missing" in gaps:
        watch_status = "data_blocked"
    monitor_check_time = _first(payload, "monitor_check_time", "trigger_time")
    first_qualified_monitor_time = _first(payload, "first_qualified_monitor_time")

    return {
        "contract_kind": "t_board_day2_watch_snapshot_v1",
        "day2_watch_snapshot_id": _first(payload, "day2_watch_snapshot_id") or utc_run_id("tbr-watch"),
        "day1_candidate_id": _first(payload, "day1_candidate_id"),
        "canonical_symbol": symbol,
        "day2_trade_date": _first(payload, "day2_trade_date", "trade_date"),
        "as_of_time": _first(payload, "as_of_time", "as_of_time_utc"),
        "watch_window_start_time": _first(payload, "watch_window_start_time", "day2_monitor_window_start_time") or config.day2_monitor_window_start_time,
        "watch_window_end_time": _first(payload, "watch_window_end_time", "day2_monitor_window_end_time") or config.day2_monitor_window_end_time,
        "monitor_interval_minutes": _first(payload, "monitor_interval_minutes") or config.day2_monitor_interval_minutes,
        "monitor_check_time": monitor_check_time,
        "first_qualified_monitor_time": first_qualified_monitor_time,
        "last_price_at_watch": last_price,
        "up_limit_price": up_limit_price,
        "distance_to_up_limit_pct": distance,
        "near_limit_flag": near_limit,
        "day2_near_limit_quality_score": _decimal(_first(payload, "day2_near_limit_quality_score")),
        "day2_price_push_mode": _first(payload, "day2_price_push_mode") or "unknown",
        "market_context_status": market_status,
        "market_return_acceleration_rolling": _decimal(_first(payload, "market_return_acceleration_rolling")),
        "limit_up_ratio_rolling": _decimal(_first(payload, "limit_up_ratio_rolling")),
        "market_net_moneyflow_rolling": _decimal(_first(payload, "market_net_moneyflow_rolling")),
        "watch_status": watch_status,
        "source_gap_codes": sorted(set(gaps)),
        "dynamic_feature_run_id": _first(payload, "dynamic_feature_run_id"),
    }


def _standard_order_side(payload: dict[str, Any]) -> str:
    explicit = _first(payload, "order_consumption_side")
    if explicit:
        return str(explicit).upper()
    buy_sweep = _decimal(_first(payload, "aggressive_buy_sweep_amount", "ask_consumed_by_buy_amount"))
    sell_hit = _decimal(_first(payload, "aggressive_sell_hit_bid_amount", "bid_consumed_by_sell_amount"))
    if buy_sweep is not None and buy_sweep > 0 and (sell_hit is None or buy_sweep >= sell_hit):
        return "ASK"
    if sell_hit is not None and sell_hit > 0:
        return "BID"
    return "UNKNOWN"


def _has_positive_amount(value: Decimal | None) -> bool:
    return value is not None and value > 0


def build_day2_trigger(payload: dict[str, Any]) -> dict[str, Any]:
    watch = payload.get("watch_snapshot") or build_day2_watch(payload)
    candidate = payload.get("day1_candidate") or {}
    candidate_status = _first(candidate, "candidate_status") or _first(payload, "day1_candidate_status") or "qualified"
    market_status = _first(watch, "market_context_status") or _market_context_status(payload)
    raw_label = _first(payload, "order_consumption_raw_label") or "ROLLING_NEAR_LIMIT_CHECK"
    side = _standard_order_side(payload)
    amount = _decimal(_first(payload, "order_consumption_amount", "aggressive_buy_sweep_amount", "bid_consumed_by_sell_amount"))
    speed = _decimal(_first(payload, "order_consumption_speed", "ask_absorption_speed_near_limit", "bid_replenish_speed_after_consumed"))
    absorption_score = _decimal(_first(payload, "near_limit_order_absorption_score"))
    p0_order_book_complete = _bool(_first(payload, "p0_order_book_complete"))
    p0_trade_tick_complete = _bool(_first(payload, "p0_trade_tick_complete"))
    if p0_order_book_complete is None:
        p0_order_book_complete = amount is not None or side != "UNKNOWN"
    if p0_trade_tick_complete is None:
        p0_trade_tick_complete = amount is not None

    gaps: list[str] = list(watch.get("source_gap_codes") or [])
    if not p0_order_book_complete:
        gaps.append("source_gap:order_book_snapshot_missing")
    if not p0_trade_tick_complete:
        gaps.append("source_gap:trade_tick_missing")
    if absorption_score is None:
        gaps.append("source_gap:near_limit_order_absorption_missing")

    near_limit = bool(watch.get("near_limit_flag"))
    ask_sweep_confirmed = side == "ASK" and _has_positive_amount(amount)
    bid_pressure_failed = side == "BID" and _has_positive_amount(amount)

    if candidate_status != "qualified":
        status = "not_triggered"
        reason = "day1_not_qualified"
    elif not near_limit:
        status = "not_triggered"
        reason = "day2_not_near_limit_rolling_5m"
    elif bid_pressure_failed:
        status = "not_triggered"
        reason = "day2_bid_pressure_hit_buy_orders"
    elif not ask_sweep_confirmed:
        status = "data_blocked"
        reason = "day2_ask_sweep_confirmation_missing"
    else:
        status = "triggered"
        reason = None

    relay_score_seed = Decimal("0")
    relay_score_seed += Decimal("55") if near_limit else Decimal("0")
    relay_score_seed += min(Decimal("35"), absorption_score or Decimal("0")) * Decimal("0.7")
    relay_score_seed += {"supportive": Decimal("25"), "neutral": Decimal("15"), "data_degraded": Decimal("5"), "weak": Decimal("0")}.get(str(market_status), Decimal("5"))
    relay_score = max(Decimal("0"), min(Decimal("100"), relay_score_seed))
    trigger_time = (
        _first(payload, "trigger_time")
        or watch.get("first_qualified_monitor_time")
        or watch.get("monitor_check_time")
        or _first(payload, "as_of_time")
    )

    return {
        "contract_kind": "t_board_day2_entry_trigger_v1",
        "entry_trigger_id": _first(payload, "entry_trigger_id") or utc_run_id("tbr-entry"),
        "day1_candidate_id": _first(payload, "day1_candidate_id") or _first(candidate, "day1_candidate_id"),
        "canonical_symbol": _first(payload, "canonical_symbol", "symbol") or _first(candidate, "canonical_symbol"),
        "day2_trade_date": _first(payload, "day2_trade_date", "trade_date"),
        "trigger_time": trigger_time,
        "last_price_at_trigger": _decimal(_first(payload, "last_price_at_trigger", "last_price_at_watch", "last_price")),
        "up_limit_price": watch.get("up_limit_price"),
        "distance_to_up_limit_pct": watch.get("distance_to_up_limit_pct"),
        "near_limit_flag": near_limit,
        "monitor_interval_minutes": watch.get("monitor_interval_minutes"),
        "first_qualified_monitor_time": watch.get("first_qualified_monitor_time"),
        "order_consumption_raw_label": raw_label,
        "order_consumption_side": side,
        "order_consumption_amount": amount,
        "order_consumption_speed": speed,
        "near_limit_order_absorption_score": absorption_score,
        "order_consumption_interpretation": "bullish" if side == "ASK" else "bearish" if side == "BID" else "unknown",
        "entry_price": _decimal(_first(payload, "entry_price", "last_price_at_trigger", "last_price")),
        "entry_price_method": _first(payload, "entry_price_method") or "rolling_5m_near_limit_price",
        "relay_consensus_score": _q(relay_score, "0.01"),
        "market_context_status": market_status,
        "entry_trigger_status": status,
        "not_trigger_reason": reason,
        "source_gap_codes": sorted(set(gaps)),
        "dynamic_feature_run_id": _first(payload, "dynamic_feature_run_id"),
    }


def build_post_entry_monitor(payload: dict[str, Any]) -> dict[str, Any]:
    opened = _bool(_first(payload, "post_entry_board_opened"))
    close_on_limit = _bool(_first(payload, "close_on_limit_flag", "day2_close_on_limit_flag"))
    gaps: list[str] = []
    if opened is None:
        gaps.append("source_gap:post_entry_board_monitor_missing")
    if close_on_limit is None:
        gaps.append("source_gap:close_on_limit_flag_missing")

    if opened is True:
        status = "FAILED_AFTER_OPEN"
        outcome = "day2_board_open_after_entry_failed"
        control_failure = Decimal("100")
    elif opened is None:
        status = "DATA_INSUFFICIENT"
        outcome = "data_blocked"
        control_failure = None
    elif close_on_limit is True:
        status = "SEALED_TO_CLOSE"
        outcome = "day2_entry_success_sealed_to_close"
        control_failure = Decimal("0")
    else:
        status = "WEAK_SEAL_TO_CLOSE"
        outcome = "day2_entry_weak_close_not_limit"
        control_failure = Decimal("65")

    return {
        "contract_kind": "t_board_post_entry_monitor_v1",
        "post_entry_monitor_id": _first(payload, "post_entry_monitor_id") or utc_run_id("tbr-monitor"),
        "entry_trigger_id": _first(payload, "entry_trigger_id"),
        "canonical_symbol": _first(payload, "canonical_symbol", "symbol"),
        "day2_trade_date": _first(payload, "day2_trade_date", "trade_date"),
        "entry_time": _first(payload, "entry_time", "trigger_time"),
        "entry_price": _decimal(_first(payload, "entry_price")),
        "up_limit_price": _decimal(_first(payload, "up_limit_price")),
        "post_entry_board_opened": opened,
        "first_board_open_time_after_entry": _first(payload, "first_board_open_time_after_entry"),
        "time_from_entry_to_first_open_seconds": _decimal(_first(payload, "time_from_entry_to_first_open_seconds")),
        "board_open_count_after_entry": _decimal(_first(payload, "board_open_count_after_entry")),
        "lowest_price_after_entry": _decimal(_first(payload, "lowest_price_after_entry")),
        "max_drawdown_after_entry": _decimal(_first(payload, "max_drawdown_after_entry")),
        "close_price": _decimal(_first(payload, "close_price")),
        "close_on_limit_flag": close_on_limit,
        "final_seal_order_amount": _decimal(_first(payload, "final_seal_order_amount")),
        "final_seal_to_float_mcap_ratio": _decimal(_first(payload, "final_seal_to_float_mcap_ratio")),
        "control_failure_score": control_failure,
        "post_entry_status": status,
        "outcome_label": outcome,
        "source_gap_codes": sorted(set(gaps)),
        "hard_rule": "post_entry_board_opened_any_time_before_close_is_failed",
    }


def build_day3_exit_decision(payload: dict[str, Any]) -> dict[str, Any]:
    open_limit = _bool(_first(payload, "day3_open_limit_up_flag"))
    tail_limit = _bool(_first(payload, "day3_tail_limit_up_flag", "tail_limit_up_flag"))
    gaps: list[str] = []
    if open_limit is None:
        gaps.append("source_gap:day3_open_price_missing")
    if tail_limit is None:
        gaps.append("source_gap:day3_tail_price_missing")

    if gaps:
        action = "data_blocked"
        reason = "p0_day3_open_or_tail_price_missing"
    elif open_limit:
        action = "hold_open_limit"
        reason = "day3_open_limit_up"
    elif tail_limit is False:
        action = "exit_tail_no_limit"
        reason = "day3_tail_no_limit"
    else:
        action = "research_hold_tail_limit"
        reason = "tail_limit_recovered_without_open_limit"

    return {
        "contract_kind": "t_board_day3_exit_decision_v1",
        "day3_decision_id": _first(payload, "day3_decision_id") or utc_run_id("tbr-day3"),
        "entry_trigger_id": _first(payload, "entry_trigger_id"),
        "canonical_symbol": _first(payload, "canonical_symbol", "symbol"),
        "day3_trade_date": _first(payload, "day3_trade_date", "trade_date"),
        "open_price": _decimal(_first(payload, "open_price", "day3_open_price")),
        "up_limit_price": _decimal(_first(payload, "up_limit_price", "day3_up_limit_price")),
        "day3_open_limit_up_flag": open_limit,
        "day3_open_seal_order_amount": _decimal(_first(payload, "day3_open_seal_order_amount")),
        "day3_open_seal_to_float_mcap_ratio": _decimal(_first(payload, "day3_open_seal_to_float_mcap_ratio")),
        "day3_open_seal_quality_score": _decimal(_first(payload, "day3_open_seal_quality_score")),
        "tail_window_start_time": _first(payload, "tail_window_start_time") or "14:40:00",
        "tail_window_end_time": _first(payload, "tail_window_end_time") or "14:55:00",
        "tail_price": _decimal(_first(payload, "tail_price")),
        "tail_limit_up_flag": tail_limit,
        "tail_distance_to_limit_pct": _decimal(_first(payload, "tail_distance_to_limit_pct")),
        "day3_action": action,
        "action_reason": reason,
        "source_gap_codes": sorted(set(gaps)),
    }


def build_game_hypothesis(stage: str, related: dict[str, Any]) -> dict[str, Any]:
    state = related.get("post_entry_status") or related.get("entry_trigger_status") or related.get("candidate_status") or related.get("day3_action")
    if stage == "day2_post_entry" and state == "FAILED_AFTER_OPEN":
        intent = "abandon"
        label = "control_failed"
    elif stage == "day2_pre_entry" and state == "triggered":
        intent = "relay"
        label = "consensus_acceleration"
    elif stage == "day1" and related.get("candidate_status") == "qualified":
        intent = "wash"
        label = "disagreement_to_consensus"
    elif stage == "day3" and related.get("day3_action") == "exit_tail_no_limit":
        intent = "abandon"
        label = "exit_required"
    else:
        intent = "unknown"
        label = "fake_strength" if related.get("fake_seal_trap_risk_score") and Decimal(str(related["fake_seal_trap_risk_score"])) >= 70 else "unknown"
    return {
        "contract_kind": "t_board_game_hypothesis_snapshot_v1",
        "game_hypothesis_id": utc_run_id("tbr-game"),
        "canonical_symbol": related.get("canonical_symbol"),
        "trade_date": related.get("trade_date") or related.get("day2_trade_date") or related.get("day3_trade_date"),
        "stage": stage,
        "related_entity_id": related.get("day1_candidate_id") or related.get("entry_trigger_id") or related.get("day3_decision_id"),
        "dominant_capital_intent": intent,
        "retail_following_strength": "unknown",
        "sell_pressure_state": "unknown",
        "seal_commitment_state": "strong" if related.get("seal_commitment_score") and Decimal(str(related["seal_commitment_score"])) >= 70 else "unknown",
        "market_emotion_state": related.get("market_context_status") or "unknown",
        "game_state_label": label,
        "evidence_json": jsonable(related),
        "confidence_level": "medium" if label != "unknown" else "low",
    }


def build_outcome_label(payload: dict[str, Any]) -> dict[str, Any]:
    monitor = payload.get("post_entry_monitor") or {}
    day3 = payload.get("day3_decision") or {}
    if monitor.get("post_entry_board_opened") is True:
        label = "day2_board_open_after_entry_failed"
        reason = "post_entry_board_opened"
    elif monitor.get("post_entry_status") == "SEALED_TO_CLOSE" and day3.get("day3_open_limit_up_flag") is True:
        label = "t_board_relay_strong_success"
        reason = "day2_sealed_to_close_and_day3_open_limit"
    elif day3.get("day3_action") == "exit_tail_no_limit":
        label = "day3_tail_no_limit_exit"
        reason = "day3_tail_no_limit"
    elif monitor.get("post_entry_status") == "SEALED_TO_CLOSE":
        label = "day2_entry_success_sealed_to_close"
        reason = "day2_sealed_to_close"
    else:
        label = "data_blocked"
        reason = "missing_monitor_or_day3_decision"

    return {
        "contract_kind": "t_board_outcome_label_v1",
        "outcome_label_id": _first(payload, "outcome_label_id") or utc_run_id("tbr-outcome"),
        "entry_trigger_id": _first(payload, "entry_trigger_id") or monitor.get("entry_trigger_id") or day3.get("entry_trigger_id"),
        "day1_candidate_id": _first(payload, "day1_candidate_id"),
        "canonical_symbol": _first(payload, "canonical_symbol", "symbol") or monitor.get("canonical_symbol") or day3.get("canonical_symbol"),
        "day1_trade_date": _first(payload, "day1_trade_date"),
        "day2_trade_date": monitor.get("day2_trade_date") or _first(payload, "day2_trade_date"),
        "day3_trade_date": day3.get("day3_trade_date") or _first(payload, "day3_trade_date"),
        "entry_price": _decimal(_first(payload, "entry_price")) or monitor.get("entry_price"),
        "entry_time": _first(payload, "entry_time") or monitor.get("entry_time"),
        "day2_post_entry_board_opened": monitor.get("post_entry_board_opened"),
        "day2_close_on_limit_flag": monitor.get("close_on_limit_flag"),
        "day3_open_limit_up_flag": day3.get("day3_open_limit_up_flag"),
        "day3_tail_limit_up_flag": day3.get("tail_limit_up_flag"),
        "day3_action": day3.get("day3_action"),
        "max_return_after_entry": _decimal(_first(payload, "max_return_after_entry")),
        "max_drawdown_after_entry": monitor.get("max_drawdown_after_entry") or _decimal(_first(payload, "max_drawdown_after_entry")),
        "close_return_day2": _decimal(_first(payload, "close_return_day2")),
        "close_return_day3": _decimal(_first(payload, "close_return_day3")),
        "outcome_label": label,
        "label_reason": reason,
        "label_version": "t_board_outcome_label_v1",
        "source_gap_codes": sorted(set((monitor.get("source_gap_codes") or []) + (day3.get("source_gap_codes") or []))),
    }


def response_for_day1_scan(rows: list[dict[str, Any]], trade_date: str | None) -> dict[str, Any]:
    scan = build_day1_scan(rows, trade_date=trade_date)
    gaps = [gap for item in scan["candidates"] for gap in item.get("source_gap_codes", [])]
    return _contract_response("day1_scan", scan, gaps)


def response_for_day2_watch(payload: dict[str, Any]) -> dict[str, Any]:
    watch = build_day2_watch(payload)
    return _contract_response("day2_watch_snapshot", watch, watch.get("source_gap_codes") or [])


def response_for_day2_trigger(payload: dict[str, Any]) -> dict[str, Any]:
    trigger = build_day2_trigger(payload)
    trigger["game_hypothesis"] = build_game_hypothesis("day2_pre_entry", trigger)
    return _contract_response("day2_entry_trigger", trigger, trigger.get("source_gap_codes") or [])


def response_for_post_entry_monitor(payload: dict[str, Any]) -> dict[str, Any]:
    monitor = build_post_entry_monitor(payload)
    monitor["game_hypothesis"] = build_game_hypothesis("day2_post_entry", monitor)
    return _contract_response("post_entry_monitor", monitor, monitor.get("source_gap_codes") or [])


def response_for_day3_exit(payload: dict[str, Any]) -> dict[str, Any]:
    decision = build_day3_exit_decision(payload)
    decision["game_hypothesis"] = build_game_hypothesis("day3", decision)
    return _contract_response("day3_exit_decision", decision, decision.get("source_gap_codes") or [])


def response_for_outcome(payload: dict[str, Any]) -> dict[str, Any]:
    outcome = build_outcome_label(payload)
    return _contract_response("outcome_label", outcome, outcome.get("source_gap_codes") or [])
