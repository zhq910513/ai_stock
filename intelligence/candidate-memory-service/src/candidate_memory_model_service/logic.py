from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any


MEMORY_MODEL_VERSION = "candidate_memory_v1"
DEFAULT_ENTRY_BASIS = "open_5m_vwap"
DEFAULT_TARGET_RETURN = Decimal("0.08")
DEFAULT_TARGET_WINDOW_DAYS = 30
MIN_DAILY_LOOKBACK = 20


def utc_run_id(prefix: str = "candidate-memory") -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _score100(value: Any, *, percent_input: bool = False) -> Decimal | None:
    numeric = _decimal(value)
    if numeric is None:
        return None
    if percent_input and numeric <= 1:
        numeric *= Decimal("100")
    if not percent_input and numeric <= 1:
        numeric *= Decimal("100")
    if numeric < 0 or numeric > 100:
        return None
    return numeric.quantize(Decimal("0.000001"))


def _clip100(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return max(Decimal("0"), min(Decimal("100"), value)).quantize(Decimal("0.000001"))


def _ratio_score(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return _clip100(value * Decimal("100"))


def _stable_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(_jsonable(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


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


def _daily_bars(row: dict[str, Any]) -> list[dict[str, Any]]:
    bars = row.get("daily_bars") or row.get("price_path") or []
    return sorted(
        [item for item in bars if isinstance(item, dict) and not item.get("is_partial")],
        key=lambda item: str(item.get("trading_day") or ""),
    )


def _bar_has_valid_ohlc(bar: dict[str, Any]) -> bool:
    open_price = _decimal(bar.get("open_price") or bar.get("open"))
    high_price = _decimal(bar.get("high_price") or bar.get("high"))
    low_price = _decimal(bar.get("low_price") or bar.get("low"))
    close_price = _decimal(bar.get("close_price") or bar.get("close"))
    if any(value is None or not value.is_finite() or value <= 0 for value in (open_price, high_price, low_price, close_price)):
        return False
    return high_price >= max(open_price, close_price) and low_price <= min(open_price, close_price) and high_price >= low_price


def _recent_ohlc_gap_codes(bars: list[dict[str, Any]], *, required_days: int) -> list[str]:
    if len(bars) < required_days:
        return ["source_gap:daily_bar_20d"]
    if not all(_bar_has_valid_ohlc(bar) for bar in bars[-required_days:]):
        return ["source_gap:daily_ohlc_invalid"]
    return []


def _pct_return(current: Decimal, base: Decimal) -> Decimal | None:
    if base <= 0:
        return None
    return (current / base - Decimal("1")) * Decimal("100")


def _close_price(bar: dict[str, Any]) -> Decimal | None:
    return _decimal(bar.get("close_price") or bar.get("close"))


def _high_price(bar: dict[str, Any]) -> Decimal | None:
    return _decimal(bar.get("high_price") or bar.get("high"))


def _low_price(bar: dict[str, Any]) -> Decimal | None:
    return _decimal(bar.get("low_price") or bar.get("low"))


def _amount(bar: dict[str, Any]) -> Decimal | None:
    amount = _decimal(bar.get("amount"))
    if amount is not None:
        return amount
    close = _close_price(bar)
    volume = _decimal(bar.get("volume"))
    if close is None or volume is None:
        return None
    return close * volume


def _mean(values: list[Decimal]) -> Decimal | None:
    clean = [value for value in values if value is not None]
    if not clean:
        return None
    return sum(clean) / Decimal(len(clean))


def _historical_candidate_quality(row: dict[str, Any]) -> Decimal | None:
    prior = _score100(row.get("max_p_limit_up") or row.get("p_limit_up"), percent_input=True)
    if prior is None:
        return None
    prior_hot = _score100(row.get("latest_prior_hot_score") or row.get("max_prior_hot_score"))
    evidence = _score100(row.get("latest_prior_evidence_completeness") or row.get("max_prior_evidence_completeness"))
    weighted = prior * Decimal("0.65")
    weight_sum = Decimal("0.65")
    if prior_hot is not None:
        weighted += prior_hot * Decimal("0.25")
        weight_sum += Decimal("0.25")
    if evidence is not None:
        weighted += evidence * Decimal("0.10")
        weight_sum += Decimal("0.10")
    return _clip100(weighted / weight_sum)


def _post_candidate_trend_quality(bars: list[dict[str, Any]]) -> Decimal | None:
    if len(bars) < MIN_DAILY_LOOKBACK:
        return None
    closes = [_close_price(bar) for bar in bars]
    highs = [_high_price(bar) for bar in bars]
    lows = [_low_price(bar) for bar in bars]
    if any(value is None for value in closes[-10:] + highs[-10:] + lows[-10:]):
        return None
    latest = closes[-1]
    base_5 = closes[-6] if len(closes) > 5 else closes[0]
    base_10 = closes[-11] if len(closes) > 10 else closes[0]
    ma5 = _mean([value for value in closes[-5:] if value is not None])
    ma10 = _mean([value for value in closes[-10:] if value is not None])
    recent_5 = _pct_return(latest, base_5) or Decimal("0")
    recent_10 = _pct_return(latest, base_10) or Decimal("0")
    recent_high = max(value for value in highs[-10:] if value is not None)
    recent_low = min(value for value in lows[-10:] if value is not None)
    high_low_score = Decimal("70") if latest >= recent_low * Decimal("1.03") else Decimal("35")
    high_reclaim_score = Decimal("75") if latest >= recent_high * Decimal("0.97") else Decimal("45")
    ma_score = Decimal("75") if ma5 is not None and ma10 is not None and latest >= ma5 and ma5 >= ma10 * Decimal("0.98") else Decimal("45")
    momentum_score = _clip100(Decimal("50") + recent_5 * Decimal("2.5") + recent_10 * Decimal("1.2"))
    return _clip100(high_low_score * Decimal("0.25") + high_reclaim_score * Decimal("0.25") + ma_score * Decimal("0.25") + momentum_score * Decimal("0.25"))


def _rank_percentile(rank: dict[str, Any], *keys: str) -> Decimal | None:
    for key in keys:
        for suffix in ("_pct_rank", "_percentile"):
            score = _score100(rank.get(f"{key}{suffix}"), percent_input=True)
            if score is not None:
                return score
    return None


def _quiet_accumulation_score(row: dict[str, Any], bars: list[dict[str, Any]]) -> Decimal | None:
    stock_rank = row.get("stock_rank") if isinstance(row.get("stock_rank"), dict) else {}
    if not stock_rank:
        return None
    main = _rank_percentile(stock_rank, "main_net_inflow")
    large = _rank_percentile(stock_rank, "large_order_net_inflow", "large_net_inflow")
    super_large = _rank_percentile(stock_rank, "super_large_order_net_inflow", "super_large_net_inflow")
    flow_scores = [score for score in (main, large, super_large) if score is not None]
    flow_score = _mean(flow_scores)
    if flow_score is None:
        return None
    if len(bars) < 20:
        volume_dry_score = None
    else:
        recent_amount = _mean([value for value in [_amount(bar) for bar in bars[-5:]] if value is not None])
        base_amount = _mean([value for value in [_amount(bar) for bar in bars[-20:-5]] if value is not None])
        if recent_amount is None or base_amount is None or base_amount <= 0:
            volume_dry_score = None
        else:
            ratio = recent_amount / base_amount
            volume_dry_score = _clip100(Decimal("80") if ratio <= Decimal("0.85") else Decimal("60") if ratio <= Decimal("1.25") else Decimal("35"))
    if volume_dry_score is None:
        return flow_score
    return _clip100(flow_score * Decimal("0.65") + volume_dry_score * Decimal("0.35"))


def _second_wave_setup_score(bars: list[dict[str, Any]]) -> tuple[Decimal | None, int]:
    if len(bars) < MIN_DAILY_LOOKBACK:
        return None, 0
    closes = [_close_price(bar) for bar in bars]
    highs = [_high_price(bar) for bar in bars]
    lows = [_low_price(bar) for bar in bars]
    if any(value is None for value in closes[-10:] + highs[-10:] + lows[-10:]):
        return None, 0
    latest = closes[-1]
    prior_high = max(value for value in highs[-15:-1] if value is not None)
    recent_low = min(value for value in lows[-8:] if value is not None)
    ma5 = _mean([value for value in closes[-5:] if value is not None])
    ma10 = _mean([value for value in closes[-10:] if value is not None])
    evidence_count = 0
    score = Decimal("35")
    if latest >= prior_high * Decimal("0.985"):
        score += Decimal("20")
        evidence_count += 1
    if recent_low >= min(value for value in lows[-20:] if value is not None) * Decimal("1.02"):
        score += Decimal("15")
        evidence_count += 1
    if ma5 is not None and ma10 is not None and latest >= ma5 and ma5 >= ma10 * Decimal("0.98"):
        score += Decimal("15")
        evidence_count += 1
    if len(bars) >= 20:
        recent_amount = _mean([value for value in [_amount(bar) for bar in bars[-3:]] if value is not None])
        base_amount = _mean([value for value in [_amount(bar) for bar in bars[-20:-5]] if value is not None])
        if recent_amount is not None and base_amount is not None and base_amount > 0 and Decimal("1.05") <= recent_amount / base_amount <= Decimal("2.80"):
            score += Decimal("15")
            evidence_count += 1
    return _clip100(score), evidence_count


def _upside_room_score(bars: list[dict[str, Any]]) -> Decimal | None:
    if len(bars) < MIN_DAILY_LOOKBACK:
        return None
    latest = _close_price(bars[-1])
    highs = [_high_price(bar) for bar in bars[-20:]]
    lows = [_low_price(bar) for bar in bars[-20:]]
    if latest is None or any(value is None for value in highs + lows):
        return None
    high_20 = max(value for value in highs if value is not None)
    low_20 = min(value for value in lows if value is not None)
    if high_20 <= low_20:
        return None
    position = (latest - low_20) / (high_20 - low_20)
    return _clip100(Decimal("85") - position * Decimal("45"))


def _breakdown_failure_risk(bars: list[dict[str, Any]]) -> Decimal | None:
    if len(bars) < MIN_DAILY_LOOKBACK:
        return None
    latest = _close_price(bars[-1])
    lows = [_low_price(bar) for bar in bars[-10:]]
    highs = [_high_price(bar) for bar in bars[-5:]]
    closes = [_close_price(bar) for bar in bars[-5:]]
    if latest is None or any(value is None for value in lows + highs + closes):
        return None
    support = min(value for value in lows if value is not None)
    support_distance = (latest / support - Decimal("1")) * Decimal("100") if support > 0 else Decimal("0")
    weak_close_days = sum(1 for high, close in zip(highs, closes, strict=False) if high is not None and close is not None and close < high * Decimal("0.965"))
    risk = Decimal("35")
    if support_distance < Decimal("2"):
        risk += Decimal("20")
    if weak_close_days >= 3:
        risk += Decimal("20")
    recent_return = _pct_return(latest, _close_price(bars[-6]) or latest) or Decimal("0")
    if recent_return < Decimal("-6"):
        risk += Decimal("20")
    return _clip100(risk)


def _candidate_memory_batch_id(row: dict[str, Any]) -> Any:
    return row.get("latest_batch_id") or row.get("batch_id")


def _candidate_memory_candidate_id(row: dict[str, Any]) -> Any:
    return row.get("latest_candidate_id") or row.get("candidate_id")


def _candidate_memory_prior_source_values(row: dict[str, Any]) -> list[str]:
    values = [
        row.get("p_limit_up_source"),
        row.get("max_p_limit_up_source"),
        row.get("latest_p_limit_up_source"),
        row.get("prior_p_limit_up_source"),
    ]
    for event in row.get("appearance_events") or []:
        if isinstance(event, dict):
            values.append(event.get("p_limit_up_source"))
    return [str(value).strip().lower() for value in values if value not in (None, "")]


def _candidate_memory_has_paid_prior(row: dict[str, Any]) -> bool:
    prior = _score100(row.get("max_p_limit_up") or row.get("p_limit_up"), percent_input=True)
    if prior is None:
        return False
    sources = _candidate_memory_prior_source_values(row)
    if not sources:
        return False
    return any(
        source in {"paid_ths_prior", "ths_paid_model", "ths_paid_prior", "ths_paid_probability", "ths_paid"}
        or ("paid" in source and "public" not in source and "draft" not in source)
        for source in sources
    )


def build_candidate_memory_contract(
    row: dict[str, Any],
    *,
    as_of_time_utc: datetime | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    as_of_time = as_of_time_utc or datetime.now(timezone.utc)
    bars = _daily_bars(row)
    hard_blocks: list[str] = []
    source_gap_codes: list[str] = []
    if row.get("ingest_mode") == "public_limitup_draft":
        hard_blocks.append("public_limitup_draft_not_allowed")
    elif row.get("ingest_mode") != "external_ths_model":
        hard_blocks.append("invalid_candidate_ingest_mode")
    if _candidate_memory_batch_id(row) in (None, ""):
        hard_blocks.append("missing_production_candidate_batch")
    if _candidate_memory_candidate_id(row) in (None, ""):
        hard_blocks.append("missing_production_candidate_item")
    if row.get("contract_audit_status") != "passed":
        hard_blocks.append("contract_audit_not_passed")
    if not _candidate_memory_has_paid_prior(row):
        hard_blocks.append("missing_paid_ths_prior")
    if row.get("instrument_id") in (None, ""):
        hard_blocks.append("missing_instrument_identity")
    daily_path_gap_codes = _recent_ohlc_gap_codes(bars, required_days=MIN_DAILY_LOOKBACK)
    if daily_path_gap_codes:
        hard_blocks.append("missing_daily_price_path")
        source_gap_codes.extend(daily_path_gap_codes)
    if row.get("has_trade_calendar") is False or row.get("trade_calendar_missing") is True:
        hard_blocks.append("missing_trading_calendar")
    if row.get("stock_rank") in (None, ""):
        source_gap_codes.append("source_gap:moneyflow_stock_rank")
    for block in hard_blocks:
        source_gap_codes.append(f"source_gap:{block}")

    historical = _historical_candidate_quality(row)
    trend = _post_candidate_trend_quality(bars)
    accumulation = _quiet_accumulation_score(row, bars)
    second_wave, structure_evidence_count = _second_wave_setup_score(bars)
    upside = _upside_room_score(bars)
    breakdown = _breakdown_failure_risk(bars)
    score_inputs = {
        "historical_candidate_quality": historical,
        "post_candidate_trend_quality": trend,
        "quiet_accumulation_score": accumulation,
        "second_wave_setup_score": second_wave,
        "upside_room_score": upside,
        "breakdown_failure_risk": breakdown,
    }
    missing_scores = [key for key, value in score_inputs.items() if value is None]
    for key in missing_scores:
        source_gap_codes.append(f"source_gap:{key}")

    score: Decimal | None = None
    if not hard_blocks and not missing_scores:
        score = _clip100(
            Decimal("0.20") * historical
            + Decimal("0.25") * trend
            + Decimal("0.20") * accumulation
            + Decimal("0.20") * second_wave
            + Decimal("0.15") * upside
            - Decimal("0.30") * breakdown
        )

    memory_age_source = None
    for key in ("memory_age_days", "candidate_memory_age_days", "days_since_last_candidate"):
        if row.get(key) not in (None, ""):
            memory_age_source = row.get(key)
            break
    memory_age_days: int | None
    if memory_age_source is None:
        hard_blocks.append("missing_trading_calendar_memory_age")
        source_gap_codes.append("source_gap:missing_trading_calendar_memory_age")
        memory_age_days = None
    else:
        try:
            memory_age_days = int(memory_age_source)
        except (TypeError, ValueError):
            hard_blocks.append("invalid_trading_calendar_memory_age")
            source_gap_codes.append("source_gap:invalid_trading_calendar_memory_age")
            memory_age_days = None
        if memory_age_days is not None and memory_age_days < 0:
            hard_blocks.append("invalid_trading_calendar_memory_age")
            source_gap_codes.append("source_gap:invalid_trading_calendar_memory_age")
            memory_age_days = None
    if hard_blocks:
        score = None
    reactivation_age_ready = memory_age_days is not None and 5 <= memory_age_days <= 20
    if hard_blocks:
        state = "blocked_data_gap"
    elif missing_scores:
        state = "memory_watch"
    elif breakdown is not None and breakdown >= Decimal("70"):
        state = "memory_invalidated"
    elif (
        second_wave is not None
        and breakdown is not None
        and second_wave >= Decimal("70")
        and breakdown < Decimal("45")
        and reactivation_age_ready
        and structure_evidence_count >= 2
    ):
        state = "memory_reactivated"
    elif trend is not None and breakdown is not None and trend >= Decimal("60") and breakdown < Decimal("50"):
        state = "memory_active"
    elif memory_age_days is not None and memory_age_days > 30:
        state = "memory_decayed"
    else:
        state = "memory_watch"

    latest_candidate_trading_day = row.get("last_candidate_trading_day") or row.get("latest_candidate_trading_day") or row.get("trade_date")
    symbol = str(row.get("symbol") or row.get("symbol_snapshot") or "").zfill(6)
    positive_factors = []
    if historical is not None:
        positive_factors.append("历史候选来源有效")
    if second_wave is not None and second_wave >= Decimal("70"):
        positive_factors.append("二波结构证据增强")
    if accumulation is not None and accumulation >= Decimal("60"):
        positive_factors.append("缩量蓄势或资金承接改善")
    negative_factors = []
    if breakdown is not None and breakdown >= Decimal("55"):
        negative_factors.append("破位风险偏高")
    negative_factors.extend(source_gap_codes)

    feature_payload = {
        "model_version": MEMORY_MODEL_VERSION,
        "symbol": symbol,
        "memory_age_days": memory_age_days,
        "score_inputs": {key: str(value) if value is not None else None for key, value in score_inputs.items()},
        "structure_evidence_count": structure_evidence_count,
        "source_gap_codes": sorted(set(source_gap_codes)),
        "hard_block_reasons": sorted(set(hard_blocks)),
    }
    feature_hash = _stable_hash(feature_payload)
    score_hash = _stable_hash(
        {
            "feature_hash": feature_hash,
            "model_version": MEMORY_MODEL_VERSION,
            "state": state,
            "score": str(score) if score is not None else None,
        }
    )
    evidence_refs = list(row.get("evidence_refs") or [])
    evidence_refs.append(
        {
            "kind": "candidate_memory_input",
            "batch_id": row.get("batch_id"),
            "appearance_id": row.get("appearance_id"),
            "memory_id": row.get("memory_id"),
            "latest_candidate_trading_day": str(latest_candidate_trading_day or ""),
        }
    )
    return _jsonable(
        {
            "schema_version": "candidate_memory_contract_v1",
            "run_id": run_id,
            "model_version": MEMORY_MODEL_VERSION,
            "symbol": symbol,
            "name": row.get("name") or row.get("name_snapshot") or symbol,
            "as_of_time_utc": as_of_time,
            "memory_id": row.get("memory_id"),
            "appearance_count": int(row.get("appearance_count") or row.get("candidate_appearance_count") or 1),
            "latest_candidate_trading_day": latest_candidate_trading_day,
            "memory_age_days": memory_age_days,
            "memory_hit_8pct_score": score,
            "memory_state": state,
            "publication_state": "blocked" if state == "blocked_data_gap" else "ready" if score is not None else "warning",
            "score_breakdown": score_inputs,
            "structure_evidence_count": structure_evidence_count,
            "main_positive_factors": positive_factors,
            "main_negative_factors": sorted(set(negative_factors)),
            "hard_block_reasons": sorted(set(hard_blocks)),
            "source_gap_codes": sorted(set(source_gap_codes)),
            "evidence_refs": evidence_refs,
            "feature_payload_json": feature_payload,
            "feature_hash": feature_hash,
            "score_hash": score_hash,
            "guardrails": {
                "score_formula": "0.20*historical+0.25*trend+0.20*accumulation+0.20*second_wave+0.15*upside-0.30*breakdown",
                "uses_future_labels": False,
                "requires_production_candidate_lineage": True,
                "public_limitup_draft_allowed": False,
            },
        }
    )
