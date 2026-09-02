from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from hot_candidates_model_service.hot_lifecycle import resolve_hot_cycle

HOT_RESEARCH_CONTRACT_VERSION = "hot_candidates_lifecycle_research_v1"
HOT_MODEL_REFINED_VERSION = "hot_candidates_v2_lifecycle"
DEFAULT_OFFICIAL_SCORE_THRESHOLD = Decimal("60")
DEFAULT_CALIBRATION_SCORE_THRESHOLD = Decimal("50")
MIN_CALIBRATION_SAMPLE_COUNT = 120


def _decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    if value in (None, ""):
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return default


def _optional_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _score01(value: Any) -> Decimal:
    value_decimal = _decimal(value)
    if value_decimal > 1:
        value_decimal = value_decimal / Decimal("100")
    if value_decimal < 0:
        return Decimal("0")
    if value_decimal > 1:
        return Decimal("1")
    return value_decimal


def _score100(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    value_decimal = _decimal(value)
    if value_decimal <= 1:
        value_decimal = value_decimal * Decimal("100")
    if value_decimal < 0 or value_decimal > 100:
        return None
    return value_decimal.quantize(Decimal("0.000001"))


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value.quantize(Decimal("0.000001")))
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    return value


def _stable_hash(payload: dict[str, Any], prefix: str) -> str:
    encoded = json.dumps(_jsonable(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{prefix}-{hashlib.sha256(encoded.encode('utf-8')).hexdigest()[:24]}"


def _parse_time(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _text(value: Any, default: str = "") -> str:
    if value in (None, ""):
        return default
    return str(value)


def _probability_bucket(value: Any) -> str:
    pct = _score01(value) * Decimal("100")
    if pct >= Decimal("90"):
        return "p90_100"
    if pct >= Decimal("80"):
        return "p80_90"
    if pct >= Decimal("70"):
        return "p70_80"
    if pct >= Decimal("60"):
        return "p60_70"
    if pct >= Decimal("50"):
        return "p50_60"
    if pct >= Decimal("40"):
        return "p40_50"
    return "p00_40"


def _positive_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return False
    return str(value).strip().lower() in {"true", "1", "yes", "y", "是", "yup"}


def _latest_bar(row: dict[str, Any]) -> dict[str, Any]:
    bars = [item for item in list(row.get("daily_bars") or []) if isinstance(item, dict)]
    if not bars:
        return {}
    return sorted(bars, key=lambda item: str(item.get("trading_day") or ""))[-1]


def infer_board_count(row: dict[str, Any]) -> int:
    for key in ("consecutive_board_count", "board_count", "limit_up_stage", "limit_up_days"):
        parsed = _positive_int(row.get(key))
        if parsed is not None:
            return parsed
    latest = _latest_bar(row)
    parsed = _positive_int(latest.get("consecutive_board_count") or latest.get("board_count"))
    return parsed or 0


def infer_limit_state(row: dict[str, Any]) -> dict[str, Any]:
    latest = _latest_bar(row)
    is_limit_up = _boolish(row.get("is_limit_up")) or _boolish(latest.get("is_limit_up"))
    one_word = _boolish(row.get("is_one_word_limit")) or _boolish(latest.get("is_one_word_limit"))
    t_shape = _boolish(row.get("is_t_shape_limit")) or _boolish(latest.get("is_t_shape_limit"))
    opened_times = _positive_int(row.get("opened_times") or latest.get("opened_times"))
    limit_opened = _boolish(row.get("is_opened_limit")) or bool(opened_times and opened_times > 0)
    break_board = _boolish(row.get("break_board_flag")) or _boolish(latest.get("break_board_flag"))
    relimit = _boolish(row.get("relimit_after_break_flag")) or _boolish(latest.get("relimit_after_break_flag"))
    return {
        "is_limit_up": is_limit_up,
        "is_one_word_limit": one_word,
        "is_t_shape_limit": t_shape,
        "is_opened_limit": limit_opened,
        "opened_times": opened_times,
        "break_board_flag": break_board,
        "relimit_after_break_flag": relimit,
    }


def infer_lifecycle_stage(row: dict[str, Any]) -> str:
    explicit = row.get("hot_lifecycle_stage") or row.get("lifecycle_stage")
    if explicit:
        return str(explicit)
    board_count = infer_board_count(row)
    limit_state = infer_limit_state(row)
    if limit_state["relimit_after_break_flag"]:
        return "relimit_after_break"
    if limit_state["break_board_flag"]:
        return "board_break_divergence"
    if board_count >= 3:
        return "high_board_overheat"
    if board_count >= 2:
        return "consecutive_board_continuation"
    if board_count == 1 or limit_state["is_limit_up"]:
        return "first_board_confirmation"
    return "new_hot_ignition"


def infer_cycle_start_date(row: dict[str, Any]) -> str:
    return _text(
        row.get("cycle_start_date")
        or row.get("first_seen_trade_date")
        or row.get("first_candidate_trade_date")
        or row.get("trade_date")
        or row.get("trading_day")
        or row.get("as_of_trading_day"),
        "unknown",
    )


def build_hot_cycle_identity(row: dict[str, Any]) -> dict[str, Any]:
    symbol = _text(row.get("symbol") or row.get("symbol_snapshot"), "").zfill(6)
    lifecycle_stage = infer_lifecycle_stage(row)
    board_count = infer_board_count(row)
    limit_state = infer_limit_state(row)
    trade_date = _text(row.get("trade_date") or row.get("trading_day") or row.get("as_of_trading_day"), "unknown")
    resolution = resolve_hot_cycle(row, symbol=symbol, trade_date=trade_date, lifecycle_stage=lifecycle_stage)
    payload = {
        "symbol": symbol,
        "cycle_start_date": resolution.cycle_start_date,
        "primary_theme": row.get("primary_theme") or row.get("theme") or row.get("primary_concept"),
        "primary_catalyst_id": row.get("primary_catalyst_id") or row.get("news_event_id"),
    }
    return {
        "contract_kind": "hot_cycle_identity_v1",
        "hot_cycle_id": resolution.hot_cycle_id,
        "symbol": symbol,
        "stock_name": row.get("name") or row.get("name_snapshot") or row.get("name_at_snapshot"),
        "cycle_start_date": resolution.cycle_start_date,
        "cycle_start_reason": row.get("cycle_start_reason") or "ths_candidate_or_hot_signal_seen",
        "lifecycle_stage": lifecycle_stage,
        "board_count": board_count,
        "limit_state": limit_state,
        "primary_theme": payload.get("primary_theme"),
        "primary_catalyst_id": payload.get("primary_catalyst_id"),
        "cycle_resolution": resolution.to_dict(),
    }


def build_hot_decision_case(row: dict[str, Any], *, as_of_time_utc: datetime) -> dict[str, Any]:
    cycle = build_hot_cycle_identity(row)
    trade_date = _text(row.get("trade_date") or row.get("trading_day") or row.get("as_of_trading_day"), "unknown")
    candidate_id = row.get("candidate_id")
    batch_id = row.get("batch_id")
    payload = {
        "hot_cycle_id": cycle["hot_cycle_id"],
        "candidate_id": candidate_id,
        "batch_id": batch_id,
        "symbol": cycle["symbol"],
        "trade_date": trade_date,
        "decision_time": as_of_time_utc.isoformat(),
    }
    return {
        "contract_kind": "hot_decision_case_v1",
        "hot_case_id": row.get("hot_case_id") or _stable_hash(payload, "hot-case"),
        "hot_cycle_id": cycle["hot_cycle_id"],
        "batch_id": batch_id,
        "candidate_id": candidate_id,
        "instrument_id": row.get("instrument_id"),
        "symbol": cycle["symbol"],
        "stock_name": cycle.get("stock_name"),
        "trade_date": trade_date,
        "decision_time": as_of_time_utc,
        "lifecycle_stage_at_decision": cycle["lifecycle_stage"],
        "board_count_at_decision": cycle["board_count"],
        "case_status": "initial_decision_built",
    }


def build_teacher_calibration(row: dict[str, Any], legacy_contract: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = _score01(row.get("p_limit_up"))
    bucket = _probability_bucket(raw)
    calibration = row.get("teacher_calibration") if isinstance(row.get("teacher_calibration"), dict) else {}
    bucket_payload = calibration.get(bucket) if isinstance(calibration.get(bucket), dict) else calibration
    sample_count = _positive_int(bucket_payload.get("sample_count")) or 0
    realized = _optional_decimal(bucket_payload.get("realized_rate") or bucket_payload.get("bucket_realized_rate"))
    if realized is not None and realized > 1:
        realized = realized / Decimal("100")
    if realized is not None and sample_count >= MIN_CALIBRATION_SAMPLE_COUNT:
        calibrated = max(Decimal("0"), min(Decimal("1"), realized))
        status = "historically_calibrated"
        reliability = "sample_supported"
    else:
        calibrated = raw
        status = "raw_prior_used_sample_insufficient"
        reliability = "sample_insufficient"
    return {
        "contract_kind": "hot_teacher_probability_calibration_v1",
        "teacher_prior_raw": raw,
        "teacher_prior_calibrated": calibrated,
        "teacher_probability_bucket": bucket,
        "calibration_status": status,
        "teacher_reliability_level": reliability,
        "calibration_sample_count": sample_count,
        "bucket_realized_rate": realized,
        "calibration_source": bucket_payload.get("source") or "decision_hot.hot_teacher_calibration_v1",
    }


def _feature_score(contract: dict[str, Any] | None, key: str) -> Decimal | None:
    feature = (contract or {}).get("feature_matrix") if isinstance((contract or {}).get("feature_matrix"), dict) else {}
    direct = _score100(feature.get(key))
    if direct is not None:
        return direct
    payload = feature.get("feature_payload_json") if isinstance(feature.get("feature_payload_json"), dict) else {}
    return _score100(payload.get(key))


def _row_auction_confirmation_score(row: dict[str, Any]) -> Decimal | None:
    auction = row.get("auction_snapshot") if isinstance(row.get("auction_snapshot"), dict) else {}
    if not auction:
        return None
    matched = _optional_decimal(auction.get("matched_amount")) or Decimal("0")
    imbalance = _optional_decimal(auction.get("imbalance_ratio")) or Decimal("0")
    price = _optional_decimal(auction.get("auction_price") or auction.get("virtual_open_price"))
    previous_close = _optional_decimal(row.get("previous_close"))
    score = Decimal("40")
    if matched >= Decimal("10000000"):
        score += Decimal("15")
    if matched >= Decimal("30000000"):
        score += Decimal("10")
    if imbalance > 0:
        score += min(Decimal("20"), imbalance * Decimal("40"))
    if price is not None and previous_close is not None and previous_close > 0:
        gap_pct = (price / previous_close - 1) * Decimal("100")
        if gap_pct >= Decimal("8"):
            score -= Decimal("18")
        elif gap_pct >= Decimal("3"):
            score += Decimal("5")
        elif gap_pct < Decimal("0"):
            score -= Decimal("12")
    return max(Decimal("0"), min(Decimal("100"), score)).quantize(Decimal("0.000001"))


def _row_capital_follow_score(row: dict[str, Any]) -> Decimal | None:
    rank = row.get("stock_rank") if isinstance(row.get("stock_rank"), dict) else {}
    candidates = [
        rank.get("main_net_inflow_pct_rank"),
        rank.get("large_order_net_inflow_pct_rank"),
        rank.get("super_large_order_net_inflow_pct_rank"),
    ]
    vals = [_score01(item) * Decimal("100") for item in candidates if item not in (None, "")]
    if not vals:
        return None
    return (sum(vals) / Decimal(len(vals))).quantize(Decimal("0.000001"))


def build_stage_scores(row: dict[str, Any], legacy_contract: dict[str, Any] | None) -> dict[str, Any]:
    teacher = build_teacher_calibration(row, legacy_contract)
    teacher_score = teacher["teacher_prior_calibrated"] * Decimal("100")
    capital = _feature_score(legacy_contract, "capital_follow_through_score") or _row_capital_follow_score(row)
    auction = _feature_score(legacy_contract, "auction_confirmation_score") or _row_auction_confirmation_score(row)
    local = _feature_score(legacy_contract, "local_confirmation_score")
    tradability = _feature_score(legacy_contract, "tradability_adjustment_score")
    upside = _feature_score(legacy_contract, "upside_space_score")
    overheat = _feature_score(legacy_contract, "overheating_failure_risk")

    def clamp(value: Decimal) -> Decimal:
        return max(Decimal("0"), min(Decimal("100"), value)).quantize(Decimal("0.000001"))

    lifecycle = infer_lifecycle_stage(row)
    pre_parts = [teacher_score]
    if capital is not None:
        pre_parts.append(capital)
    if upside is not None:
        pre_parts.append(upside)
    pre_auction_score = clamp(sum(pre_parts) / Decimal(len(pre_parts)))

    auction_confirmed_score = None
    if all(item is not None for item in (auction, capital, local, tradability, upside, overheat)):
        if lifecycle in {"new_hot_ignition", "first_board_confirmation"}:
            weights = (Decimal("0.28"), Decimal("0.24"), Decimal("0.18"), Decimal("0.16"), Decimal("0.14"), Decimal("0.26"))
        elif lifecycle in {"consecutive_board_continuation", "high_board_overheat"}:
            weights = (Decimal("0.18"), Decimal("0.28"), Decimal("0.16"), Decimal("0.22"), Decimal("0.16"), Decimal("0.42"))
        else:
            weights = (Decimal("0.22"), Decimal("0.26"), Decimal("0.18"), Decimal("0.18"), Decimal("0.16"), Decimal("0.34"))
        w_teacher, w_auction, w_capital, w_tradability, w_upside, w_overheat = weights
        auction_confirmed_score = clamp(
            w_teacher * teacher_score
            + w_auction * auction
            + w_capital * capital
            + w_tradability * tradability
            + w_upside * upside
            - w_overheat * overheat
        )
        # Teacher high but auction weak is a production downgrade, not merely a warning.
        if teacher_score >= Decimal("65") and auction < Decimal("45"):
            auction_confirmed_score = clamp(auction_confirmed_score - Decimal("15"))

    open_5m_state = row.get("open_5m_vwap_state") or row.get("vwap_state")
    open_5m_score = auction_confirmed_score
    if auction_confirmed_score is not None and open_5m_state:
        state = str(open_5m_state).lower()
        if "lost" in state or "below" in state or "break" in state:
            open_5m_score = clamp(auction_confirmed_score - Decimal("15"))
        elif "support" in state or "above" in state or "held" in state:
            open_5m_score = clamp(auction_confirmed_score + Decimal("5"))

    official_score = open_5m_score if open_5m_score is not None else auction_confirmed_score
    return {
        "contract_kind": "hot_stage_score_matrix_v2_stage_specific",
        "score_model_version": HOT_MODEL_REFINED_VERSION,
        "pre_auction_score": pre_auction_score,
        "auction_confirmed_score": auction_confirmed_score,
        "open_5m_confirmed_score": open_5m_score,
        "official_hot_score": official_score,
        "score_inputs": {
            "teacher_prior_calibrated_score": teacher_score,
            "capital_follow_through_score": capital,
            "auction_confirmation_score": auction,
            "local_confirmation_score": local,
            "tradability_adjustment_score": tradability,
            "upside_space_score": upside,
            "overheating_failure_risk": overheat,
            "open_5m_vwap_state": open_5m_state,
            "lifecycle_stage": lifecycle,
            "stage_specific_weighting_enabled": True,
        },
    }


def build_release_gate(row: dict[str, Any], legacy_contract: dict[str, Any] | None, stage_scores: dict[str, Any]) -> dict[str, Any]:
    analysis = (legacy_contract or {}).get("analysis") if isinstance((legacy_contract or {}).get("analysis"), dict) else {}
    hard_blocks = list(analysis.get("hard_block_reasons") or [])
    source_gaps = list(analysis.get("source_gap_codes") or [])
    official_score = stage_scores.get("official_hot_score")
    lifecycle_stage = infer_lifecycle_stage(row)
    limit_state = infer_limit_state(row)
    block_reasons: list[str] = [str(item) for item in hard_blocks]
    warning_reasons: list[str] = []
    signal_stage = "watch_only"
    eligibility = "not_eligible"

    if source_gaps:
        warning_reasons.extend(str(item) for item in source_gaps if "source_gap" in str(item))
    if official_score is None:
        warning_reasons.append("official_score_incomplete")
    if lifecycle_stage == "high_board_overheat":
        warning_reasons.append("high_board_overheat_requires_execution_gate")
    if limit_state.get("is_one_word_limit"):
        warning_reasons.append("one_word_limit_no_fill_risk")
    if limit_state.get("relimit_after_break_flag"):
        warning_reasons.append("relimit_after_break_requires_stage_specific_validation")

    if block_reasons:
        status = "blocked"
        allowed = False
    elif official_score is None:
        status = "watch"
        allowed = False
        eligibility = "watch_only"
    elif official_score >= DEFAULT_OFFICIAL_SCORE_THRESHOLD and "one_word_limit_no_fill_risk" not in warning_reasons:
        status = "passed"
        allowed = True
        signal_stage = "official_signal"
        eligibility = "official_candidate"
    elif official_score >= DEFAULT_CALIBRATION_SCORE_THRESHOLD:
        status = "calibration_only"
        allowed = False
        signal_stage = "calibration_signal"
        eligibility = "calibration_only"
    else:
        status = "watch"
        allowed = False
        signal_stage = "research_sample"
        eligibility = "watch_only"

    return {
        "contract_kind": "hot_release_gate_decision_v1",
        "gate_version": "hot_release_gate_v2_lifecycle",
        "gate_status": status,
        "official_signal_allowed": allowed,
        "recommendation_eligibility": eligibility,
        "signal_stage": signal_stage,
        "block_reasons": sorted(set(block_reasons)),
        "warning_reasons": sorted(set(warning_reasons)),
        "required_evidence_status": "blocked" if block_reasons else "usable_with_warnings" if warning_reasons else "complete",
    }


def build_initial_decision_snapshot(
    row: dict[str, Any],
    *,
    as_of_time_utc: datetime,
    legacy_analysis: dict[str, Any],
    legacy_contract: dict[str, Any] | None,
    decision_case: dict[str, Any],
    teacher_calibration: dict[str, Any],
    stage_scores: dict[str, Any],
    release_gate: dict[str, Any],
) -> dict[str, Any]:
    snapshot_payload = {
        "hot_case_id": decision_case["hot_case_id"],
        "decision_time": as_of_time_utc.isoformat(),
        "feature_matrix": (legacy_contract or {}).get("feature_matrix"),
        "stage_scores": stage_scores,
        "release_gate": release_gate,
    }
    return {
        "contract_kind": "hot_initial_decision_snapshot_v1",
        "initial_snapshot_id": _stable_hash(snapshot_payload, "hot-init"),
        "hot_case_id": decision_case["hot_case_id"],
        "hot_cycle_id": decision_case["hot_cycle_id"],
        "decision_time": as_of_time_utc,
        "model_version": HOT_MODEL_REFINED_VERSION,
        "legacy_model_version": (legacy_contract or {}).get("analysis", {}).get("model_version"),
        "first_score": stage_scores.get("official_hot_score"),
        "first_lifecycle_stage": decision_case["lifecycle_stage_at_decision"],
        "first_teacher_prior_raw": teacher_calibration["teacher_prior_raw"],
        "first_teacher_prior_calibrated": teacher_calibration["teacher_prior_calibrated"],
        "first_release_gate_status": release_gate["gate_status"],
        "is_immutable_first_decision": True,
        "feature_hash": ((legacy_contract or {}).get("feature_matrix") or {}).get("feature_hash"),
        "score_hash": ((legacy_contract or {}).get("analysis") or {}).get("score_hash"),
        "positive_factors": (legacy_contract or {}).get("analysis", {}).get("main_positive_factors") or legacy_analysis.get("main_positive_factors") or [],
        "negative_factors": (legacy_contract or {}).get("analysis", {}).get("main_negative_factors") or legacy_analysis.get("main_negative_factors") or [],
    }


def build_persistence_plan() -> dict[str, Any]:
    return {
        "contract_kind": "decision_hot_persistence_plan_v1",
        "source_layer": [
            "source.instrument_master_v1",
            "source.trade_calendar_v1",
            "source.daily_bar_v1",
            "source.minute_bar_v1",
            "source.realtime_quote_v1",
            "source.auction_snapshot_v1",
            "source.moneyflow_stock_snapshot_v1",
            "source.sector_snapshot_v1",
            "source.market_regime_snapshot_v1",
            "source.news_event_v1",
            "source.data_quality_finding_v1",
        ],
        "decision_hot_tables": [
            "decision_hot.hot_cycle_v1",
            "decision_hot.hot_cycle_day_snapshot_v1",
            "decision_hot.hot_decision_case_v1",
            "decision_hot.hot_evidence_snapshot_v1",
            "decision_hot.hot_feature_matrix_v1",
            "decision_hot.hot_score_fact_v1",
            "decision_hot.hot_release_gate_audit_v1",
            "decision_hot.hot_signal_fact_v1",
            "decision_hot.hot_buy_point_v1",
            "decision_hot.hot_observation_snapshot_v1",
            "decision_hot.hot_outcome_label_v1",
            "decision_hot.hot_failure_attribution_v1",
            "decision_hot.hot_first_output_distortion_analysis_v1",
            "decision_hot.hot_evolution_sample_v1",
            "decision_hot.hot_model_version_evaluation_v1",
        ],
        "hard_rules": [
            "source.* only stores market facts and available_at/captured_at lineage",
            "decision_hot.* never shares business truth tables with memory or ambush models",
            "initial decision snapshot is immutable and append-only",
            "second and later observations are append-only and feed evolution samples",
            "latest read model is display-only and never becomes training truth",
        ],
    }


def build_hot_research_contract(
    row: dict[str, Any],
    *,
    legacy_analysis: dict[str, Any],
    legacy_contract: dict[str, Any] | None,
    as_of_time_utc: datetime | None = None,
) -> dict[str, Any]:
    now = as_of_time_utc or datetime.now(timezone.utc)
    cycle = build_hot_cycle_identity(row)
    decision_case = build_hot_decision_case(row, as_of_time_utc=now)
    teacher_calibration = build_teacher_calibration(row, legacy_contract)
    stage_scores = build_stage_scores(row, legacy_contract)
    release_gate = build_release_gate(row, legacy_contract, stage_scores)
    initial = build_initial_decision_snapshot(
        row,
        as_of_time_utc=now,
        legacy_analysis=legacy_analysis,
        legacy_contract=legacy_contract,
        decision_case=decision_case,
        teacher_calibration=teacher_calibration,
        stage_scores=stage_scores,
        release_gate=release_gate,
    )
    return _jsonable(
        {
            "contract_kind": HOT_RESEARCH_CONTRACT_VERSION,
            "model_version": HOT_MODEL_REFINED_VERSION,
            "hot_cycle": cycle,
            "hot_decision_case": decision_case,
            "teacher_calibration": teacher_calibration,
            "stage_scores": stage_scores,
            "release_gate": release_gate,
            "initial_decision_snapshot": initial,
            "persistence_plan": build_persistence_plan(),
        }
    )


def build_hot_observation_snapshot(payload: dict[str, Any], *, as_of_time_utc: datetime | None = None) -> dict[str, Any]:
    now = as_of_time_utc or datetime.now(timezone.utc)
    hot_case_id = _text(payload.get("hot_case_id") or payload.get("case_id"), "unknown-hot-case")
    hot_cycle_id = _text(payload.get("hot_cycle_id"), "unknown-hot-cycle")
    observe_seq = _positive_int(payload.get("observe_seq")) or 1
    ref = _optional_decimal(payload.get("reference_entry_price"))
    latest = _optional_decimal(payload.get("latest_price"))
    high = _optional_decimal(payload.get("high_since_entry") or payload.get("max_price_since_entry"))
    low = _optional_decimal(payload.get("low_since_entry") or payload.get("min_price_since_entry"))
    target = _optional_decimal(payload.get("target_price"))
    invalidation = _optional_decimal(payload.get("invalidation_price"))
    return_pct = ((latest / ref - 1) * 100).quantize(Decimal("0.000001")) if ref and latest and ref > 0 else None
    mfe_pct = ((high / ref - 1) * 100).quantize(Decimal("0.000001")) if ref and high and ref > 0 else None
    mae_pct = ((low / ref - 1) * 100).quantize(Decimal("0.000001")) if ref and low and ref > 0 else None
    first_event_type = "none"
    if target and high and high >= target:
        first_event_type = "target_hit_or_touched"
    if invalidation and low and low <= invalidation and first_event_type == "none":
        first_event_type = "invalidation_hit_or_touched"
    expectation_state = "data_insufficient"
    deviation_codes: list[str] = []
    if return_pct is not None:
        if first_event_type == "target_hit_or_touched":
            expectation_state = "direction_confirmed"
        elif first_event_type == "invalidation_hit_or_touched":
            expectation_state = "direction_contradicted"
            deviation_codes.append("invalidation_hit_before_target")
        elif return_pct >= Decimal("3"):
            expectation_state = "on_track"
        elif return_pct <= Decimal("-3"):
            expectation_state = "materially_weaker_than_expected"
            deviation_codes.append("post_entry_drawdown_expanded")
        else:
            expectation_state = "slightly_weaker_than_expected" if return_pct < 0 else "on_track"
    for key, code in (
        ("vwap_lost_after_entry", "vwap_lost_after_entry"),
        ("sector_cooling_after_signal", "sector_cooling_after_signal"),
        ("moneyflow_reversed", "moneyflow_reversed"),
        ("open_overheat_confirmed", "open_overheat_confirmed"),
    ):
        if _boolish(payload.get(key)):
            deviation_codes.append(code)
    snapshot_payload = {
        "hot_case_id": hot_case_id,
        "observe_seq": observe_seq,
        "observe_time": now.isoformat(),
        "latest_price": latest,
        "return_pct": return_pct,
    }
    return _jsonable(
        {
            "contract_kind": "hot_observation_snapshot_v1",
            "observation_id": _stable_hash(snapshot_payload, "hot-observe"),
            "hot_case_id": hot_case_id,
            "hot_cycle_id": hot_cycle_id,
            "observe_seq": observe_seq,
            "observe_time": now,
            "data_as_of": _parse_time(payload.get("data_as_of")) or now,
            "observe_stage": payload.get("observe_stage") or "intraday_review",
            "latest_price": latest,
            "reference_entry_price": ref,
            "return_from_reference_pct": return_pct,
            "mfe_pct": mfe_pct,
            "mae_pct": mae_pct,
            "first_event_type": first_event_type,
            "expectation_state": expectation_state,
            "deviation_reason_codes": sorted(set(deviation_codes)),
            "support_strength_score": _score100(payload.get("support_strength_score")),
            "contradiction_score": _score100(payload.get("contradiction_score")),
            "freshness_status": payload.get("freshness_status") or "unknown",
            "quality_status": payload.get("quality_status") or "unknown",
            "sequence_no": _positive_int(payload.get("sequence_no")) or observe_seq,
            "append_only": True,
        }
    )


def build_hot_evolution_sample(payload: dict[str, Any], *, as_of_time_utc: datetime | None = None) -> dict[str, Any]:
    now = as_of_time_utc or datetime.now(timezone.utc)
    observation = payload.get("observation") if isinstance(payload.get("observation"), dict) else {}
    outcome = payload.get("outcome_label") if isinstance(payload.get("outcome_label"), dict) else {}
    initial = payload.get("initial_decision_snapshot") if isinstance(payload.get("initial_decision_snapshot"), dict) else {}
    direction = _text(outcome.get("direction_outcome"), "direction_pending")
    execution = _text(outcome.get("execution_outcome"), "execution_pending")
    lifecycle = _text(initial.get("first_lifecycle_stage") or payload.get("lifecycle_stage_at_decision"), "unknown")
    deviation_codes = list(observation.get("deviation_reason_codes") or [])
    sample_type = "mature_unclassified"
    correction_direction = "hold_current_rules"
    if direction == "direction_success" and execution in {"execution_missed", "no_fill_opportunity"}:
        sample_type = "direction_success_execution_missed"
        correction_direction = "adjust_buy_point_or_execution_gate"
    elif direction == "direction_failed" and "vwap_lost_after_entry" in deviation_codes:
        sample_type = "vwap_lost_failure"
        correction_direction = "increase_open_5m_vwap_constraint"
    elif direction == "direction_failed" and lifecycle == "high_board_overheat":
        sample_type = "high_board_overheat_failure"
        correction_direction = "tighten_high_board_release_gate"
    elif direction == "direction_failed":
        sample_type = "model_or_environment_failure_requires_bucket_review"
        correction_direction = "bucket_level_failure_attribution_required"
    elif direction == "direction_success":
        sample_type = "validated_success"
        correction_direction = "preserve_or_reinforce_matching_bucket"
    sample_payload = {
        "hot_case_id": payload.get("hot_case_id") or observation.get("hot_case_id"),
        "sample_type": sample_type,
        "direction": direction,
        "execution": execution,
        "created_at": now.isoformat(),
    }
    return _jsonable(
        {
            "contract_kind": "hot_evolution_sample_v1",
            "evolution_sample_id": _stable_hash(sample_payload, "hot-evo"),
            "hot_case_id": payload.get("hot_case_id") or observation.get("hot_case_id"),
            "hot_cycle_id": payload.get("hot_cycle_id") or observation.get("hot_cycle_id"),
            "source_observation_id": observation.get("observation_id"),
            "sample_type": sample_type,
            "lifecycle_stage_at_decision": lifecycle,
            "outcome_label": direction,
            "execution_label": execution,
            "deviation_reason_codes": deviation_codes,
            "correction_direction": correction_direction,
            "recommended_adjustment_json": {
                "do_not_mutate_production_model_online": True,
                "requires_shadow_run_before_activation": True,
                "candidate_adjustment": correction_direction,
            },
            "sample_weight": payload.get("sample_weight") or "1.0",
            "maturity_status": outcome.get("label_maturity_status") or "pending_or_unknown",
            "created_at": now,
        }
    )
