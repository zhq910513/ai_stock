from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

MEMORY_MODEL_VERSION = "candidate_memory_v1"
DEFAULT_TTL_DAYS = 30
PRE_SIGNAL_MIN_SCORE = Decimal("62")
ACTIVATION_MIN_SCORE = Decimal("68")
OFFICIAL_MIN_SCORE = Decimal("70")
MAX_FAKE_ACTIVATION_RISK = Decimal("58")


class MemoryContractError(ValueError):
    pass


def utc_run_id(prefix: str = "candidate-memory") -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        numeric = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not numeric.is_finite():
        return None
    return numeric


def _int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _score(value: Any, *, percent_input: bool = False) -> Decimal | None:
    numeric = _decimal(value)
    if numeric is None:
        return None
    if numeric <= 1 or percent_input:
        numeric *= Decimal("100")
    if numeric < 0 or numeric > 100:
        return None
    return _clip100(numeric)


def _clip100(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return max(Decimal("0"), min(Decimal("100"), value)).quantize(Decimal("0.000001"))


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def _stable_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(_jsonable(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _mean(values: list[Decimal]) -> Decimal | None:
    clean = [item for item in values if item is not None]
    if not clean:
        return None
    return sum(clean) / Decimal(len(clean))


def _daily_bars(row: dict[str, Any]) -> list[dict[str, Any]]:
    bars = row.get("daily_bars") or row.get("price_path") or []
    if not isinstance(bars, list):
        return []
    return sorted(
        [item for item in bars if isinstance(item, dict) and not item.get("is_partial")],
        key=lambda item: str(item.get("trading_day") or item.get("trade_date") or ""),
    )


def _close(bar: dict[str, Any]) -> Decimal | None:
    return _decimal(bar.get("close_price") or bar.get("close"))


def _high(bar: dict[str, Any]) -> Decimal | None:
    return _decimal(bar.get("high_price") or bar.get("high"))


def _low(bar: dict[str, Any]) -> Decimal | None:
    return _decimal(bar.get("low_price") or bar.get("low"))


def _amount(bar: dict[str, Any]) -> Decimal | None:
    amount = _decimal(bar.get("amount") or bar.get("turnover_amount"))
    if amount is not None:
        return amount
    close = _close(bar)
    volume = _decimal(bar.get("volume"))
    if close is None or volume is None:
        return None
    return close * volume


def _bar_valid(bar: dict[str, Any]) -> bool:
    o = _decimal(bar.get("open_price") or bar.get("open"))
    h = _high(bar)
    l = _low(bar)
    c = _close(bar)
    if any(value is None or value <= 0 for value in (o, h, l, c)):
        return False
    return h >= max(o, c) and l <= min(o, c) and h >= l


def _pct(current: Decimal | None, base: Decimal | None) -> Decimal | None:
    if current is None or base is None or base <= 0:
        return None
    return (current / base - Decimal("1")) * Decimal("100")


def _first_present(row: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        if row.get(key) not in (None, ""):
            return row.get(key)
    return None


def _is_available(evidence: dict[str, Any], decision_time: datetime) -> tuple[bool, str | None]:
    available_at = _dt(evidence.get("available_at") or evidence.get("captured_at") or evidence.get("published_at"))
    if available_at is None:
        return False, "missing_available_at"
    if available_at > decision_time:
        return False, "future_available_at"
    return True, None


def _split_events_by_time(row: dict[str, Any], decision_time: datetime) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    events = row.get("events") or row.get("news_events") or row.get("announcements") or []
    if not isinstance(events, list):
        return [], [], ["source_gap:events_not_list"]
    ex_ante: list[dict[str, Any]] = []
    post_hoc: list[dict[str, Any]] = []
    gaps: list[str] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        ok, reason = _is_available(event, decision_time)
        enriched = dict(event)
        enriched["time_visibility_status"] = "ex_ante" if ok else reason or "not_visible"
        if ok:
            ex_ante.append(enriched)
        else:
            post_hoc.append(enriched)
            if reason == "missing_available_at":
                gaps.append("source_gap:event_missing_available_at")
            elif reason == "future_available_at":
                gaps.append("source_gap:event_future_available_at")
    return ex_ante, post_hoc, sorted(set(gaps))


def _event_signal_score(events: list[dict[str, Any]]) -> tuple[Decimal, list[str], Decimal]:
    if not events:
        return Decimal("0"), [], Decimal("0")
    best_scores: list[Decimal] = []
    reason_codes: list[str] = []
    catalyst_strengths: list[Decimal] = []
    for event in events:
        relevance = _score(event.get("relevance_score") or event.get("symbol_relevance_score")) or Decimal("50")
        reliability = _score(event.get("source_reliability") or event.get("reliability_score")) or Decimal("50")
        novelty = _score(event.get("novelty_score")) or Decimal("50")
        importance = _score(event.get("importance_score") or event.get("catalyst_strength_score")) or Decimal("50")
        event_score = _clip100(relevance * Decimal("0.30") + reliability * Decimal("0.20") + novelty * Decimal("0.20") + importance * Decimal("0.30")) or Decimal("0")
        best_scores.append(event_score)
        catalyst_strengths.append(importance)
        event_type = str(event.get("event_type") or "event")
        if event_score >= 65:
            if event_type in {"policy", "industry_policy", "product_price_up", "company_announcement", "contract_order"}:
                reason_codes.append("theme_second_catalyst")
            elif event_type in {"sector_news", "industry_news", "theme_news"}:
                reason_codes.append("sector_resonance_return")
            else:
                reason_codes.append("event_catalyst_pre_signal")
    return max(best_scores), sorted(set(reason_codes)), _mean(catalyst_strengths) or Decimal("0")


def _moneyflow_signal(row: dict[str, Any]) -> tuple[Decimal | None, list[str]]:
    feature = row.get("moneyflow_feature") if isinstance(row.get("moneyflow_feature"), dict) else row
    delta_3d = _score(feature.get("moneyflow_delta_3d") or feature.get("moneyflow_delta_3d_score"))
    delta_5d = _score(feature.get("moneyflow_delta_5d") or feature.get("moneyflow_delta_5d_score"))
    turning = _score(feature.get("moneyflow_turning_point") or feature.get("moneyflow_turning_point_score"))
    outflow_decay = _score(feature.get("capital_outflow_decay_score"))
    intraday_support = _score(feature.get("intraday_support_flow_score"))
    values = [value for value in (delta_3d, delta_5d, turning, outflow_decay, intraday_support) if value is not None]
    if not values:
        return None, []
    score = _clip100(_mean(values))
    reasons: list[str] = []
    if score is not None and score >= 62:
        reasons.append("capital_memory_reactivation")
    if outflow_decay is not None and outflow_decay >= 65:
        reasons.append("capital_outflow_decay")
    if intraday_support is not None and intraday_support >= 65:
        reasons.append("intraday_support_flow")
    return score, sorted(set(reasons))


def _sector_theme_signal(row: dict[str, Any]) -> tuple[Decimal | None, list[str]]:
    feature = row.get("sector_theme_feature") if isinstance(row.get("sector_theme_feature"), dict) else row
    strength_delta_3d = _score(feature.get("sector_strength_delta_3d") or feature.get("sector_strength_delta_3d_score"))
    strength_delta_5d = _score(feature.get("sector_strength_delta_5d") or feature.get("sector_strength_delta_5d_score"))
    rank_change = _score(feature.get("relative_sector_rank_change") or feature.get("relative_sector_rank_change_score"))
    limitup_breadth = _score(feature.get("sector_limit_up_breadth_score"))
    theme_heat = _score(feature.get("theme_heat_recovery_score") or feature.get("theme_heat_delta_score"))
    leader = _score(feature.get("theme_leader_confirmation_score"))
    values = [value for value in (strength_delta_3d, strength_delta_5d, rank_change, limitup_breadth, theme_heat, leader) if value is not None]
    if not values:
        return None, []
    score = _clip100(_mean(values))
    reasons: list[str] = []
    if score is not None and score >= 62:
        reasons.append("sector_resonance_return")
    if theme_heat is not None and theme_heat >= 65:
        reasons.append("theme_second_catalyst")
    if leader is not None and leader >= 65:
        reasons.append("delayed_catch_up_realization")
    return score, sorted(set(reasons))


def _price_structure_signal(row: dict[str, Any], bars: list[dict[str, Any]]) -> tuple[dict[str, Decimal | None], list[str]]:
    feature = row.get("price_structure_feature") if isinstance(row.get("price_structure_feature"), dict) else {}
    explicit = {
        "platform_compression_score": _score(feature.get("platform_compression_score") or row.get("platform_compression_score")),
        "volatility_compression_score": _score(feature.get("volatility_compression_score") or row.get("volatility_compression_score")),
        "higher_low_score": _score(feature.get("higher_low_score") or row.get("higher_low_score")),
        "support_hold_score": _score(feature.get("support_hold_score") or row.get("support_hold_score")),
        "breakout_pressure_score": _score(feature.get("breakout_pressure_score") or row.get("breakout_pressure_score")),
        "pullback_health_score": _score(feature.get("pullback_health_score") or row.get("pullback_health_score")),
        "distance_to_previous_hot_high_score": _score(feature.get("distance_to_previous_hot_high_score") or row.get("distance_to_previous_hot_high_score")),
    }
    if not bars:
        return explicit, []
    closes = [_close(bar) for bar in bars]
    highs = [_high(bar) for bar in bars]
    lows = [_low(bar) for bar in bars]
    amounts = [_amount(bar) for bar in bars]
    if len(bars) >= 20 and all(value is not None for value in closes[-10:] + highs[-15:] + lows[-20:]):
        latest = closes[-1]
        prior_high = max(value for value in highs[-15:-1] if value is not None)
        recent_low = min(value for value in lows[-8:] if value is not None)
        base_low = min(value for value in lows[-20:-8] if value is not None)
        close_10 = closes[-11]
        if explicit["distance_to_previous_hot_high_score"] is None and latest is not None and prior_high is not None:
            distance_pct = (Decimal("1") - abs(latest / prior_high - Decimal("1"))) * Decimal("100")
            explicit["distance_to_previous_hot_high_score"] = _clip100(distance_pct)
        if explicit["higher_low_score"] is None and recent_low is not None and base_low is not None:
            explicit["higher_low_score"] = Decimal("75") if recent_low >= base_low * Decimal("1.02") else Decimal("45")
        if explicit["support_hold_score"] is None and recent_low is not None and close_10 is not None:
            explicit["support_hold_score"] = Decimal("75") if recent_low >= close_10 * Decimal("0.94") else Decimal("40")
        if explicit["breakout_pressure_score"] is None and latest is not None and prior_high is not None:
            explicit["breakout_pressure_score"] = Decimal("78") if latest >= prior_high * Decimal("0.985") else Decimal("55") if latest >= prior_high * Decimal("0.95") else Decimal("38")
        if explicit["platform_compression_score"] is None:
            recent_high = max(value for value in highs[-8:] if value is not None)
            recent_low_8 = min(value for value in lows[-8:] if value is not None)
            if latest is not None and latest > 0:
                band = (recent_high - recent_low_8) / latest
                explicit["platform_compression_score"] = Decimal("80") if band <= Decimal("0.08") else Decimal("60") if band <= Decimal("0.14") else Decimal("35")
        if explicit["volatility_compression_score"] is None and all(value is not None for value in amounts[-20:]):
            recent_amount = _mean([value for value in amounts[-5:] if value is not None])
            base_amount = _mean([value for value in amounts[-20:-5] if value is not None])
            if recent_amount is not None and base_amount is not None and base_amount > 0:
                ratio = recent_amount / base_amount
                explicit["volatility_compression_score"] = Decimal("70") if Decimal("0.70") <= ratio <= Decimal("1.35") else Decimal("45")
        if explicit["pullback_health_score"] is None and latest is not None and recent_low is not None:
            explicit["pullback_health_score"] = Decimal("74") if latest >= recent_low * Decimal("1.03") else Decimal("46")
    reasons: list[str] = []
    structure_avg = _mean([value for value in explicit.values() if value is not None])
    if structure_avg is not None and structure_avg >= 62:
        reasons.append("structure_repair_breakout")
    if explicit.get("platform_compression_score") is not None and explicit["platform_compression_score"] >= 65:
        reasons.append("platform_compression_breakout")
    if explicit.get("pullback_health_score") is not None and explicit["pullback_health_score"] >= 65:
        reasons.append("pullback_support_confirmed")
    return explicit, sorted(set(reasons))


def _fake_activation_risk(row: dict[str, Any], bars: list[dict[str, Any]], *, event_score: Decimal, moneyflow_score: Decimal | None, sector_score: Decimal | None) -> tuple[Decimal, list[str]]:
    explicit = _score(row.get("fake_activation_risk_score"))
    if explicit is not None:
        return explicit, ["fake_activation_explicit_high"] if explicit >= 65 else []
    risk = Decimal("30")
    reasons: list[str] = []
    if len(bars) >= 3:
        last = bars[-1]
        high = _high(last)
        close = _close(last)
        low = _low(last)
        amount_latest = _amount(last)
        amount_base = _mean([value for value in [_amount(bar) for bar in bars[-15:-3]] if value is not None]) if len(bars) >= 15 else None
        if high is not None and close is not None and low is not None and high > low:
            upper_shadow_ratio = (high - close) / (high - low)
            if upper_shadow_ratio >= Decimal("0.45"):
                risk += Decimal("20")
                reasons.append("upper_shadow_distribution")
        if amount_latest is not None and amount_base is not None and amount_base > 0 and amount_latest / amount_base >= Decimal("2.8"):
            risk += Decimal("15")
            reasons.append("abnormal_spike_risk")
    if moneyflow_score is not None and moneyflow_score < 45:
        risk += Decimal("15")
        reasons.append("moneyflow_not_confirmed")
    if sector_score is not None and sector_score < 45:
        risk += Decimal("10")
        reasons.append("sector_not_resonant")
    if event_score < 35 and row.get("requires_event_confirmation"):
        risk += Decimal("10")
        reasons.append("event_catalyst_absent")
    return _clip100(risk) or Decimal("100"), sorted(set(reasons))


def build_memory_seed(row: dict[str, Any], *, as_of_time_utc: datetime | None = None, run_id: str | None = None) -> dict[str, Any]:
    decision_time = as_of_time_utc or datetime.now(timezone.utc)
    run_id = run_id or utc_run_id("memory-seed")
    source_model = str(row.get("first_source_model") or row.get("source_model") or "hot_candidates")
    source_signal_id = row.get("first_source_signal_id") or row.get("hot_signal_id") or row.get("source_signal_id")
    symbol = str(row.get("symbol") or row.get("symbol_snapshot") or "").zfill(6)
    gaps: list[str] = []
    hard_blocks: list[str] = []
    if source_model != "hot_candidates":
        gaps.append("source_gap:unsupported_seed_source_model")
        hard_blocks.append("unsupported_seed_source_model")
    if not source_signal_id:
        gaps.append("source_gap:missing_first_source_signal_id")
        hard_blocks.append("missing_first_source_signal_id")
    if not symbol or symbol == "000000":
        gaps.append("source_gap:missing_symbol")
        hard_blocks.append("missing_symbol")
    if row.get("is_st") or row.get("is_suspended") or row.get("has_delisting_risk"):
        hard_blocks.append("untradable_or_risk_stock")
    first_outcome = str(row.get("first_outcome_label") or row.get("hot_outcome_label") or "unknown")
    research_tags = list(row.get("research_tags") or row.get("memory_seed_tags") or [])
    seed_reasons: list[str] = []
    allowed_outcomes = {
        "failed_but_high_mfe",
        "delayed_success",
        "direction_success_execution_missed",
        "blocked_but_track_later_success",
        "teacher_underestimated_success",
        "t20_delayed_success",
        "short_window_failed",
        "hot_direction_success",
    }
    if first_outcome in allowed_outcomes:
        seed_reasons.append(first_outcome)
    for tag in research_tags:
        if tag in allowed_outcomes or str(tag).startswith("memory_"):
            seed_reasons.append(str(tag))
    mfe = _decimal(row.get("first_mfe_pct") or row.get("mfe_pct"))
    if mfe is not None and mfe >= Decimal("5"):
        seed_reasons.append("high_mfe_research_value")
    if row.get("first_structure_invalidated") is True:
        hard_blocks.append("first_structure_invalidated")
    if row.get("data_quality_status") == "polluted":
        hard_blocks.append("source_data_polluted")
    priority = "high_priority_memory" if any(reason in seed_reasons for reason in {"delayed_success", "t20_delayed_success", "direction_success_execution_missed", "blocked_but_track_later_success"}) else "research_memory"
    if not seed_reasons and not hard_blocks:
        priority = "watch_memory"
        seed_reasons.append("historical_attention_memory")
    status = "blocked" if hard_blocks else "accepted"
    seed_id = row.get("memory_seed_id") or f"memseed-{source_model}-{source_signal_id or symbol}-{_stable_hash({'symbol': symbol, 'source_signal_id': source_signal_id})[:10]}"
    payload = {
        "schema_version": "candidate_memory_seed_v1",
        "run_id": run_id,
        "model_version": MEMORY_MODEL_VERSION,
        "memory_seed_id": seed_id,
        "symbol": symbol,
        "source_model": source_model,
        "first_source_signal_id": source_signal_id,
        "first_source_case_id": row.get("first_source_case_id") or row.get("hot_case_id"),
        "first_selected_date": row.get("first_selected_date") or row.get("selected_date") or row.get("trade_date"),
        "first_outcome_label": first_outcome,
        "seed_priority": priority,
        "seed_reasons": sorted(set(seed_reasons)),
        "seed_status": status,
        "hard_block_reasons": sorted(set(hard_blocks)),
        "source_gap_codes": sorted(set(gaps)),
        "created_at": decision_time,
    }
    payload["payload_hash"] = _stable_hash(payload)
    return _jsonable(payload)


def build_memory_entity(row: dict[str, Any], *, as_of_time_utc: datetime | None = None, run_id: str | None = None) -> dict[str, Any]:
    decision_time = as_of_time_utc or datetime.now(timezone.utc)
    run_id = run_id or utc_run_id("memory-entity")
    seed = row.get("seed") if isinstance(row.get("seed"), dict) else build_memory_seed(row, as_of_time_utc=decision_time, run_id=run_id)
    symbol = str(seed.get("symbol") or row.get("symbol") or "").zfill(6)
    cooling_days = _int(row.get("cooling_days_since_last_memory") or row.get("cooling_days"))
    prior_entity_status = str(row.get("prior_memory_status") or "")
    theme_changed = bool(row.get("theme_changed") or row.get("new_independent_theme"))
    ttl_days = _int(row.get("ttl_days") or row.get("base_ttl_days")) or DEFAULT_TTL_DAYS
    memory_age_days = _int(row.get("memory_age_days") or row.get("days_since_first_hot")) or 0
    if theme_changed or prior_entity_status in {"closed", "expired_closed", "invalidated"} or (cooling_days is not None and cooling_days >= ttl_days):
        merge_action = "create_new_entity"
    elif row.get("existing_memory_entity_id"):
        merge_action = "merge_existing_entity"
    else:
        merge_action = "create_new_entity"
    memory_entity_id = row.get("memory_entity_id") or row.get("existing_memory_entity_id") or f"memory-{symbol}-{str(seed.get('first_source_signal_id') or seed.get('memory_seed_id'))[-12:]}"
    decay_score = _clip100(Decimal("100") - Decimal(memory_age_days) * (Decimal("100") / Decimal(max(ttl_days, 1))))
    dynamic_ttl_adjustment = _int(row.get("dynamic_ttl_adjustment_days")) or 0
    ttl_effective_days = max(1, ttl_days + dynamic_ttl_adjustment)
    status = "observing"
    if seed.get("seed_status") == "blocked":
        status = "blocked_seed"
    elif memory_age_days > ttl_effective_days:
        status = "expired_but_researchable" if row.get("allow_expired_research") else "expired"
    elif decay_score is not None and decay_score < 25:
        status = "near_expiry"
    elif decay_score is not None and decay_score < 50:
        status = "decaying"
    entity = {
        "schema_version": "candidate_memory_entity_v1",
        "run_id": run_id,
        "model_version": MEMORY_MODEL_VERSION,
        "memory_entity_id": memory_entity_id,
        "memory_seed_id": seed.get("memory_seed_id"),
        "symbol": symbol,
        "name": row.get("name") or row.get("stock_name") or symbol,
        "first_source_model": seed.get("source_model"),
        "first_source_signal_id": seed.get("first_source_signal_id"),
        "first_source_case_id": seed.get("first_source_case_id"),
        "first_selected_date": seed.get("first_selected_date"),
        "first_outcome_label": seed.get("first_outcome_label"),
        "merge_action": merge_action,
        "memory_status": status,
        "base_ttl_days": ttl_days,
        "dynamic_ttl_adjustment_days": dynamic_ttl_adjustment,
        "ttl_effective_days": ttl_effective_days,
        "memory_age_days": memory_age_days,
        "decay_score": decay_score,
        "created_or_updated_at": decision_time,
        "guardrails": {
            "memory_entity_is_not_signal": True,
            "new_activation_requires_new_signal_id": True,
            "ttl_expiry_means_memory_explanatory_power_decay_not_stock_cannot_rise": True,
        },
    }
    entity["payload_hash"] = _stable_hash(entity)
    return _jsonable(entity)


def build_pre_signal_window(row: dict[str, Any], *, as_of_time_utc: datetime | None = None, run_id: str | None = None) -> dict[str, Any]:
    decision_time = as_of_time_utc or datetime.now(timezone.utc)
    run_id = run_id or utc_run_id("memory-pre-signal")
    bars = _daily_bars(row)
    source_gap_codes: list[str] = []
    hard_blocks: list[str] = []
    if len(bars) < 20:
        source_gap_codes.append("source_gap:daily_bar_20d")
    elif not all(_bar_valid(bar) for bar in bars[-20:]):
        source_gap_codes.append("source_gap:daily_ohlc_invalid")
    if row.get("price_source_available_at") and _dt(row.get("price_source_available_at")) and _dt(row.get("price_source_available_at")) > decision_time:
        hard_blocks.append("price_source_future_available_at")
    ex_ante_events, post_hoc_events, event_gaps = _split_events_by_time(row, decision_time)
    source_gap_codes.extend(event_gaps)
    event_score, event_reasons, catalyst_strength = _event_signal_score(ex_ante_events)
    moneyflow_score, moneyflow_reasons = _moneyflow_signal(row)
    sector_score, sector_reasons = _sector_theme_signal(row)
    structure_features, structure_reasons = _price_structure_signal(row, bars)
    structure_score = _mean([value for value in structure_features.values() if value is not None])
    fake_risk, fake_reasons = _fake_activation_risk(row, bars, event_score=event_score, moneyflow_score=moneyflow_score, sector_score=sector_score)
    market_score = _score(row.get("market_risk_appetite_score") or row.get("short_term_sentiment_score"))
    ttl_health = _score(row.get("ttl_health_score"))
    if ttl_health is None:
        ttl_remaining = _int(row.get("ttl_remaining_days"))
        ttl_effective = _int(row.get("ttl_effective_days") or row.get("ttl_days")) or DEFAULT_TTL_DAYS
        if ttl_remaining is not None:
            ttl_health = _clip100(Decimal(ttl_remaining) / Decimal(max(ttl_effective, 1)) * Decimal("100"))
    memory_value = _score(row.get("memory_value_score"))
    if memory_value is None:
        first_quality = _score(row.get("first_hot_quality_score") or row.get("first_model_score") or row.get("p_limit_up"), percent_input=True)
        decay = _score(row.get("decay_score")) or ttl_health
        memory_value = _clip100(_mean([value for value in (first_quality, decay, structure_score) if value is not None]) or Decimal("0"))
    evidence_scores = [score for score in (structure_score, moneyflow_score, sector_score, event_score, market_score) if score is not None]
    if not evidence_scores:
        pre_signal_score = None
        hard_blocks.append("missing_pre_signal_evidence")
    else:
        pre_signal_score = _clip100(
            (structure_score or Decimal("45")) * Decimal("0.25")
            + (moneyflow_score or Decimal("45")) * Decimal("0.25")
            + (sector_score or Decimal("45")) * Decimal("0.20")
            + event_score * Decimal("0.15")
            + (market_score or Decimal("50")) * Decimal("0.10")
            + (ttl_health or Decimal("50")) * Decimal("0.05")
            - fake_risk * Decimal("0.18")
        )
    pre_signal_types = sorted(set(structure_reasons + moneyflow_reasons + sector_reasons + event_reasons))
    feature_window = {
        "schema_version": "candidate_memory_pre_signal_feature_window_v1",
        "run_id": run_id,
        "model_version": MEMORY_MODEL_VERSION,
        "memory_entity_id": row.get("memory_entity_id"),
        "symbol": str(row.get("symbol") or "").zfill(6),
        "decision_time": decision_time,
        "lookback_windows_days": [1, 3, 5, 10],
        "memory_value_score": memory_value,
        "pre_signal_score": pre_signal_score,
        "structure_score": structure_score,
        "moneyflow_reactivation_score": moneyflow_score,
        "sector_resonance_return_score": sector_score,
        "event_freshness_relevance_score": event_score,
        "event_catalyst_strength_score": catalyst_strength,
        "market_risk_appetite_score": market_score,
        "ttl_health_score": ttl_health,
        "fake_activation_risk_score": fake_risk,
        "price_structure_features": structure_features,
        "pre_signal_types": pre_signal_types,
        "ex_ante_event_count": len(ex_ante_events),
        "post_hoc_event_count": len(post_hoc_events),
        "ex_ante_event_refs": [event.get("event_id") or event.get("id") or event.get("title") for event in ex_ante_events],
        "post_hoc_event_refs": [event.get("event_id") or event.get("id") or event.get("title") for event in post_hoc_events],
        "fake_activation_reasons": fake_reasons,
        "hard_block_reasons": sorted(set(hard_blocks)),
        "source_gap_codes": sorted(set(source_gap_codes)),
        "guardrails": {
            "uses_only_available_events_for_pre_signal": True,
            "post_hoc_events_excluded_from_pre_signal_score": True,
            "available_at_required_for_event_evidence": True,
        },
    }
    feature_window["feature_hash"] = _stable_hash(feature_window)
    return _jsonable(feature_window)


def detect_pre_signal_case(row: dict[str, Any], *, as_of_time_utc: datetime | None = None, run_id: str | None = None) -> dict[str, Any]:
    decision_time = as_of_time_utc or datetime.now(timezone.utc)
    run_id = run_id or utc_run_id("memory-pre-signal-case")
    window = row.get("feature_window") if isinstance(row.get("feature_window"), dict) else build_pre_signal_window(row, as_of_time_utc=decision_time, run_id=run_id)
    pre_signal_score = _decimal(window.get("pre_signal_score"))
    fake_risk = _decimal(window.get("fake_activation_risk_score")) or Decimal("100")
    hard_blocks = list(window.get("hard_block_reasons") or [])
    pre_signal_types = list(window.get("pre_signal_types") or [])
    if pre_signal_score is None:
        status = "blocked_data_gap"
    elif hard_blocks:
        status = "blocked_data_gap"
    elif pre_signal_score >= PRE_SIGNAL_MIN_SCORE and fake_risk <= MAX_FAKE_ACTIVATION_RISK and pre_signal_types:
        status = "pre_signal_detected"
    elif pre_signal_score >= Decimal("52"):
        status = "watch_only"
    else:
        status = "no_pre_signal"
    pre_signal_case_id = row.get("pre_signal_case_id") or f"pre-{row.get('memory_entity_id') or window.get('symbol')}-{_stable_hash({'window': window.get('feature_hash'), 'run_id': run_id})[:10]}"
    result = {
        "schema_version": "candidate_memory_pre_signal_case_v1",
        "run_id": run_id,
        "model_version": MEMORY_MODEL_VERSION,
        "pre_signal_case_id": pre_signal_case_id,
        "memory_entity_id": row.get("memory_entity_id") or window.get("memory_entity_id"),
        "symbol": window.get("symbol"),
        "detected_at": decision_time,
        "pre_signal_window_start": row.get("pre_signal_window_start"),
        "pre_signal_window_end": row.get("pre_signal_window_end"),
        "pre_signal_strength_score": pre_signal_score,
        "pre_signal_types": pre_signal_types,
        "fake_pre_signal_risk_score": fake_risk,
        "ex_ante_event_count": window.get("ex_ante_event_count"),
        "post_hoc_event_count": window.get("post_hoc_event_count"),
        "status": status,
        "feature_hash": window.get("feature_hash"),
        "hard_block_reasons": sorted(set(hard_blocks)),
        "source_gap_codes": window.get("source_gap_codes") or [],
        "guardrails": window.get("guardrails") or {},
    }
    result["case_hash"] = _stable_hash(result)
    return _jsonable(result)


def evaluate_activation_case(row: dict[str, Any], *, as_of_time_utc: datetime | None = None, run_id: str | None = None) -> dict[str, Any]:
    decision_time = as_of_time_utc or datetime.now(timezone.utc)
    run_id = run_id or utc_run_id("memory-activation")
    window = row.get("feature_window") if isinstance(row.get("feature_window"), dict) else build_pre_signal_window(row, as_of_time_utc=decision_time, run_id=run_id)
    pre_case = row.get("pre_signal_case") if isinstance(row.get("pre_signal_case"), dict) else detect_pre_signal_case({**row, "feature_window": window}, as_of_time_utc=decision_time, run_id=run_id)
    memory_value = _decimal(window.get("memory_value_score")) or Decimal("0")
    pre_signal = _decimal(window.get("pre_signal_score")) or Decimal("0")
    structure = _decimal(window.get("structure_score")) or Decimal("45")
    moneyflow = _decimal(window.get("moneyflow_reactivation_score")) or Decimal("45")
    sector = _decimal(window.get("sector_resonance_return_score")) or Decimal("45")
    event = _decimal(window.get("event_freshness_relevance_score")) or Decimal("0")
    ttl_value = _decimal(window.get("ttl_health_score"))
    ttl = ttl_value if ttl_value is not None else Decimal("50")
    fake_value = _decimal(window.get("fake_activation_risk_score"))
    fake = fake_value if fake_value is not None else Decimal("100")
    activation_quality = _clip100(
        memory_value * Decimal("0.15")
        + pre_signal * Decimal("0.25")
        + structure * Decimal("0.20")
        + moneyflow * Decimal("0.17")
        + sector * Decimal("0.13")
        + event * Decimal("0.05")
        + ttl * Decimal("0.05")
        - max(Decimal("0"), fake - Decimal("30")) * Decimal("0.18")
    )
    reasons = list(window.get("pre_signal_types") or [])
    hard_blocks = list(window.get("hard_block_reasons") or [])
    if pre_case.get("status") not in {"pre_signal_detected", "watch_only"}:
        hard_blocks.append("pre_signal_not_detected")
    if ttl < Decimal("20"):
        hard_blocks.append("ttl_expired_or_near_zero")
    if fake > MAX_FAKE_ACTIVATION_RISK:
        hard_blocks.append("fake_activation_risk_high")
    if activation_quality is None or activation_quality < ACTIVATION_MIN_SCORE:
        status = "activation_watch" if not hard_blocks else "activation_blocked"
    elif hard_blocks:
        status = "activation_blocked"
    else:
        status = "activation_ready"
    activation_case_id = row.get("activation_case_id") or f"act-{row.get('memory_entity_id') or window.get('symbol')}-{_stable_hash({'pre': pre_case.get('case_hash'), 'run_id': run_id})[:10]}"
    result = {
        "schema_version": "candidate_memory_activation_case_v1",
        "run_id": run_id,
        "model_version": MEMORY_MODEL_VERSION,
        "activation_case_id": activation_case_id,
        "pre_signal_case_id": pre_case.get("pre_signal_case_id"),
        "memory_entity_id": row.get("memory_entity_id") or window.get("memory_entity_id"),
        "symbol": window.get("symbol"),
        "activation_detected_at": decision_time,
        "activation_quality_score": activation_quality,
        "memory_value_score": memory_value,
        "pre_signal_score": pre_signal,
        "breakout_quality_score": structure,
        "moneyflow_reactivation_score": moneyflow,
        "sector_resonance_return_score": sector,
        "event_signal_score": event,
        "ttl_health_score": ttl,
        "fake_activation_risk_score": fake,
        "trigger_reason_codes": sorted(set(reasons)),
        "activation_status": status,
        "hard_block_reasons": sorted(set(hard_blocks)),
        "source_gap_codes": window.get("source_gap_codes") or [],
        "feature_hash": window.get("feature_hash"),
    }
    result["activation_hash"] = _stable_hash(result)
    return _jsonable(result)


def evaluate_release_gate(row: dict[str, Any], *, as_of_time_utc: datetime | None = None, run_id: str | None = None) -> dict[str, Any]:
    decision_time = as_of_time_utc or datetime.now(timezone.utc)
    run_id = run_id or utc_run_id("memory-release")
    activation = row.get("activation_case") if isinstance(row.get("activation_case"), dict) else evaluate_activation_case(row, as_of_time_utc=decision_time, run_id=run_id)
    blocks = list(activation.get("hard_block_reasons") or [])
    warnings = list(activation.get("source_gap_codes") or [])
    activation_score = _decimal(activation.get("activation_quality_score"))
    fake_value = _decimal(activation.get("fake_activation_risk_score"))
    fake = fake_value if fake_value is not None else Decimal("100")
    pre_signal = _decimal(activation.get("pre_signal_score")) or Decimal("0")
    moneyflow = _decimal(activation.get("moneyflow_reactivation_score")) or Decimal("0")
    sector = _decimal(activation.get("sector_resonance_return_score")) or Decimal("0")
    ttl_value = _decimal(activation.get("ttl_health_score"))
    ttl = ttl_value if ttl_value is not None else Decimal("0")
    if row.get("active_memory_signal_exists") or row.get("duplicate_active_signal"):
        blocks.append("duplicate_active_memory_signal")
    if row.get("memory_status") in {"expired", "closed", "invalidated"}:
        blocks.append("memory_entity_not_active")
    if ttl < Decimal("25"):
        blocks.append("ttl_not_healthy_for_official_signal")
    if pre_signal < PRE_SIGNAL_MIN_SCORE:
        blocks.append("pre_signal_score_below_gate")
    if activation_score is None or activation_score < OFFICIAL_MIN_SCORE:
        blocks.append("activation_quality_below_official_gate")
    if fake > MAX_FAKE_ACTIVATION_RISK:
        blocks.append("fake_activation_risk_above_gate")
    if moneyflow < Decimal("55") and sector < Decimal("55"):
        blocks.append("moneyflow_and_sector_both_not_confirmed")
    tradability = row.get("tradability_status") or row.get("is_tradable")
    if tradability in {"untradable", "suspended", False}:
        blocks.append("untradable")
    if row.get("data_time_hard_block"):
        blocks.append("data_time_contract_failed")
    gate_state = "official_signal_passed" if not blocks else "research_only_blocked"
    recommendation_eligibility = "official_candidate" if gate_state == "official_signal_passed" else "research_only_activation"
    signal_id = None
    if gate_state == "official_signal_passed":
        signal_id = row.get("memory_signal_id") or f"memsig-{activation.get('memory_entity_id') or activation.get('symbol')}-{decision_time.strftime('%Y%m%d%H%M%S')}-{_stable_hash({'activation': activation.get('activation_hash')})[:8]}"
    result = {
        "schema_version": "candidate_memory_release_gate_audit_v1",
        "run_id": run_id,
        "model_version": MEMORY_MODEL_VERSION,
        "memory_entity_id": activation.get("memory_entity_id"),
        "activation_case_id": activation.get("activation_case_id"),
        "memory_signal_id": signal_id,
        "symbol": activation.get("symbol"),
        "evaluated_at": decision_time,
        "release_gate_state": gate_state,
        "recommendation_eligibility": recommendation_eligibility,
        "activation_quality_score": activation_score,
        "pre_signal_score": pre_signal,
        "fake_activation_risk_score": fake,
        "hard_block_reasons": sorted(set(blocks)),
        "warning_codes": sorted(set(warnings)),
        "guardrails": {
            "requires_new_signal_id_per_activation": True,
            "memory_entity_id_is_never_signal_id": True,
            "hot_signal_id_is_never_reused": True,
            "official_success_rate_excludes_research_only": True,
        },
    }
    result["audit_hash"] = _stable_hash(result)
    return _jsonable(result)


def evaluate_buy_point(row: dict[str, Any], *, as_of_time_utc: datetime | None = None, run_id: str | None = None) -> dict[str, Any]:
    decision_time = as_of_time_utc or datetime.now(timezone.utc)
    run_id = run_id or utc_run_id("memory-buy-point")
    release = row.get("release_gate") if isinstance(row.get("release_gate"), dict) else evaluate_release_gate(row, as_of_time_utc=decision_time, run_id=run_id)
    entry_stage = row.get("entry_stage") or row.get("buy_point_stage")
    reference = _decimal(row.get("platform_upper_price") or row.get("pullback_confirm_price") or row.get("vwap_price") or row.get("reference_entry_price"))
    fake_risk = _decimal(release.get("fake_activation_risk_score")) or Decimal("100")
    blocks: list[str] = []
    if release.get("release_gate_state") != "official_signal_passed":
        blocks.append("release_gate_not_passed")
    if entry_stage not in {"breakout_confirmed_entry", "pullback_confirmed_entry", "pre_signal_waiting"}:
        blocks.append("unsupported_memory_buy_point_stage")
    if entry_stage == "pre_signal_waiting":
        blocks.append("waiting_for_breakout_or_pullback_confirmation")
    if reference is None or reference <= 0:
        blocks.append("missing_valid_reference_entry_price")
    if fake_risk > MAX_FAKE_ACTIVATION_RISK:
        blocks.append("fake_breakout_risk_high")
    if row.get("entry_too_late_after_signal"):
        blocks.append("entry_too_late_after_signal")
    state = "buy_point_confirmed" if not blocks else "buy_point_blocked" if "release_gate_not_passed" in blocks else "buy_point_waiting"
    result = {
        "schema_version": "candidate_memory_buy_point_v1",
        "run_id": run_id,
        "model_version": MEMORY_MODEL_VERSION,
        "memory_signal_id": release.get("memory_signal_id"),
        "memory_entity_id": release.get("memory_entity_id"),
        "activation_case_id": release.get("activation_case_id"),
        "symbol": release.get("symbol"),
        "evaluated_at": decision_time,
        "buy_point_state": state,
        "entry_stage": entry_stage,
        "reference_entry_price": reference if state == "buy_point_confirmed" else None,
        "diagnostic_reference_price": reference,
        "block_reasons": sorted(set(blocks)),
        "guardrails": {
            "first_valid_reference_price_freezes_outcome_baseline": True,
            "pre_signal_waiting_cannot_freeze_official_price": True,
            "latest_price_previous_close_cannot_freeze_memory_buy_point": True,
        },
    }
    result["buy_point_hash"] = _stable_hash(result)
    return _jsonable(result)


def mature_outcome(row: dict[str, Any], *, as_of_time_utc: datetime | None = None, run_id: str | None = None) -> dict[str, Any]:
    decision_time = as_of_time_utc or datetime.now(timezone.utc)
    run_id = run_id or utc_run_id("memory-outcome")
    maturity_status = row.get("label_maturity_status") or row.get("maturity_status")
    hard_blocks: list[str] = []
    if maturity_status != "mature":
        hard_blocks.append("outcome_not_mature")
    if not row.get("memory_signal_id"):
        hard_blocks.append("missing_memory_signal_id")
    hit = bool(row.get("next_limit_up_hit") or row.get("target_hit"))
    tradable_success = bool(row.get("tradable_success") or row.get("execution_success"))
    new_cycle = bool(row.get("new_independent_cycle"))
    delayed = bool(row.get("delayed_realization"))
    fake_failure = bool(row.get("fake_activation_failure")) or bool(row.get("breakout_failed"))
    if hard_blocks:
        outcome_label = "pending_or_blocked"
    elif new_cycle and hit:
        outcome_label = "new_independent_cycle"
    elif hit and delayed:
        outcome_label = "delayed_realization"
    elif hit:
        outcome_label = "second_wave_success"
    elif fake_failure:
        outcome_label = "fake_activation_failure"
    else:
        outcome_label = "second_wave_failed"
    direction_outcome = "success" if hit else "failed" if not hard_blocks else "pending"
    execution_outcome = "tradable_success" if tradable_success else "direction_success_execution_missed" if hit else "not_success"
    include_official_success_rate = bool(row.get("official_signal_pool", True)) and not new_cycle and not hard_blocks
    result = {
        "schema_version": "candidate_memory_outcome_label_v1",
        "run_id": run_id,
        "model_version": MEMORY_MODEL_VERSION,
        "memory_signal_id": row.get("memory_signal_id"),
        "memory_entity_id": row.get("memory_entity_id"),
        "activation_case_id": row.get("activation_case_id"),
        "symbol": str(row.get("symbol") or "").zfill(6),
        "labeled_at": decision_time,
        "label_maturity_status": maturity_status or "pending",
        "outcome_label": outcome_label,
        "direction_outcome": direction_outcome,
        "execution_outcome": execution_outcome,
        "next_limit_up_hit": hit,
        "time_to_next_limit_up_days": _int(row.get("time_to_next_limit_up_days")),
        "pre_signal_lead_days": _int(row.get("pre_signal_lead_days")),
        "time_from_first_hot_to_activation_days": _int(row.get("time_from_first_hot_to_activation_days")),
        "time_from_activation_to_target_days": _int(row.get("time_from_activation_to_target_days")),
        "mfe_pct": _decimal(row.get("mfe_pct")),
        "mae_pct": _decimal(row.get("mae_pct")),
        "new_independent_cycle": new_cycle,
        "include_official_success_rate": include_official_success_rate,
        "hard_block_reasons": sorted(set(hard_blocks)),
        "guardrails": {
            "new_independent_cycle_not_counted_as_memory_success": True,
            "pending_outcome_cannot_create_evolution_sample": True,
            "direction_success_separated_from_execution_success": True,
        },
    }
    result["outcome_hash"] = _stable_hash(result)
    return _jsonable(result)


def build_up_reason_attribution(row: dict[str, Any], *, as_of_time_utc: datetime | None = None, run_id: str | None = None) -> dict[str, Any]:
    decision_time = as_of_time_utc or datetime.now(timezone.utc)
    run_id = run_id or utc_run_id("memory-up-reason")
    pre_signal_reasons = list(row.get("pre_signal_reason_codes") or row.get("trigger_reason_codes") or [])
    confirmed = list(row.get("confirmed_up_reason_codes") or [])
    post_hoc = list(row.get("post_hoc_explanation_codes") or [])
    if row.get("new_independent_cycle"):
        confirmed.append("new_independent_cycle")
    primary = pre_signal_reasons[0] if pre_signal_reasons else confirmed[0] if confirmed else "unknown"
    result = {
        "schema_version": "candidate_memory_up_reason_attribution_v1",
        "run_id": run_id,
        "model_version": MEMORY_MODEL_VERSION,
        "memory_signal_id": row.get("memory_signal_id"),
        "memory_entity_id": row.get("memory_entity_id"),
        "symbol": str(row.get("symbol") or "").zfill(6),
        "attributed_at": decision_time,
        "primary_up_reason": primary,
        "pre_signal_reason_codes": sorted(set(pre_signal_reasons)),
        "confirmed_up_reason_codes": sorted(set(confirmed)),
        "post_hoc_explanation_codes": sorted(set(post_hoc)),
        "reason_confidence_score": _score(row.get("reason_confidence_score")) or Decimal("50"),
        "guardrails": {
            "pre_signal_reason_eligible_for_scoring": True,
            "confirmed_reason_for_research_only": True,
            "post_hoc_explanation_never_used_for_ex_ante_scoring": True,
        },
    }
    result["attribution_hash"] = _stable_hash(result)
    return _jsonable(result)


def build_evolution_sample(row: dict[str, Any], *, as_of_time_utc: datetime | None = None, run_id: str | None = None) -> dict[str, Any]:
    decision_time = as_of_time_utc or datetime.now(timezone.utc)
    run_id = run_id or utc_run_id("memory-evolution")
    outcome = row.get("outcome") if isinstance(row.get("outcome"), dict) else mature_outcome(row, as_of_time_utc=decision_time, run_id=run_id)
    blocks: list[str] = []
    if outcome.get("label_maturity_status") != "mature":
        blocks.append("outcome_not_mature")
    if outcome.get("outcome_label") == "new_independent_cycle":
        blocks.append("new_independent_cycle_not_model_success")
    labels: list[str] = []
    if not blocks:
        if outcome.get("outcome_label") == "delayed_realization":
            labels.append("ttl_or_hot_window_recalibration_candidate")
        if outcome.get("outcome_label") == "fake_activation_failure":
            labels.append("fake_activation_penalty_candidate")
        if outcome.get("pre_signal_lead_days") is not None and int(outcome.get("pre_signal_lead_days") or 0) >= 3:
            labels.append("pre_signal_effective_lead_candidate")
        if outcome.get("execution_outcome") == "direction_success_execution_missed":
            labels.append("buy_point_or_execution_candidate")
        if outcome.get("outcome_label") == "second_wave_success":
            labels.append("activation_rule_positive_sample")
    state = "blocked" if blocks else "ready_for_offline_evolution"
    result = {
        "schema_version": "candidate_memory_evolution_sample_v1",
        "run_id": run_id,
        "model_version": MEMORY_MODEL_VERSION,
        "memory_signal_id": outcome.get("memory_signal_id"),
        "memory_entity_id": outcome.get("memory_entity_id"),
        "symbol": outcome.get("symbol"),
        "created_at": decision_time,
        "evolution_state": state,
        "evolution_labels": sorted(set(labels)),
        "hard_block_reasons": sorted(set(blocks)),
        "outcome_hash": outcome.get("outcome_hash"),
        "guardrails": {
            "uses_mature_outcome_only": True,
            "single_case_does_not_auto_change_production_weights": True,
            "requires_offline_bucket_evaluation": True,
        },
    }
    result["evolution_hash"] = _stable_hash(result)
    return _jsonable(result)
