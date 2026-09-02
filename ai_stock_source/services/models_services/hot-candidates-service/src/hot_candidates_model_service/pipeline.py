from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from hot_candidates_model_service.calibration import build_hot_research_sample_pool_record
from hot_candidates_model_service.logic import (
    DEFAULT_TARGET_RETURN,
    build_candidate_source_analysis,
    build_hot_candidate_v1_contract,
    utc_run_id,
)
from hot_candidates_model_service.research import (
    HOT_MODEL_REFINED_VERSION,
    build_hot_evolution_sample,
    build_hot_observation_snapshot,
    build_hot_research_contract,
)

HOT_PIPELINE_CONTRACT_VERSION = "hot_candidates_full_pipeline_v1"
HOT_BUY_POINT_ADAPTER_VERSION = "hot_candidates_buy_point_adapter_v1"
HOT_OUTCOME_LABEL_VERSION = "hot_outcome_label_v1"
HOT_FAILURE_ATTRIBUTION_VERSION = "hot_failure_attribution_v1"
HOT_DISTORTION_ANALYSIS_VERSION = "hot_first_output_distortion_analysis_v1"


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


def _boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return False
    return str(value).strip().lower() in {"true", "1", "yes", "y", "是"}


def _first_present(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _pct(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return value.quantize(Decimal("0.000001"))


def _price_ratio_pct(numerator: Decimal | None, denominator: Decimal | None) -> Decimal | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return _pct((numerator / denominator - 1) * Decimal("100"))


def build_hot_source_visibility_audit(row: dict[str, Any], *, decision_time: datetime) -> dict[str, Any]:
    """Audit whether source facts used by the hot model were visible at decision time.

    Missing available_at is not silently accepted as clean evidence: it is marked as a
    warning so data-inspector can force providers to backfill time lineage. Explicit
    future evidence is a hard block.
    """
    domains: list[tuple[str, Any, Any]] = []
    candidate_available_at = row.get("candidate_available_at") or row.get("batch_available_at") or row.get("p_limit_up_available_at")
    domains.append(("candidate_item", candidate_available_at, row.get("candidate_id")))
    domains.append(("teacher_prior", row.get("p_limit_up_available_at"), row.get("candidate_id")))

    auction = row.get("auction_snapshot") if isinstance(row.get("auction_snapshot"), dict) else None
    if auction:
        domains.append(("auction", auction.get("available_at"), auction.get("raw_payload_id")))
    stock_rank = row.get("stock_rank") if isinstance(row.get("stock_rank"), dict) else None
    if stock_rank:
        domains.append(("stock_moneyflow", stock_rank.get("available_at"), stock_rank.get("raw_payload_id")))
    market_regime = row.get("market_regime_context") or row.get("market_regime")
    if isinstance(market_regime, dict) and market_regime:
        domains.append(("market_regime", market_regime.get("available_at"), market_regime.get("snapshot_id")))
    for index, bar in enumerate([item for item in row.get("daily_bars") or [] if isinstance(item, dict)][-20:]):
        domains.append((f"daily_bar[{index}]", bar.get("available_at"), bar.get("raw_payload_id") or bar.get("lineage_id") or bar.get("build_batch_id") or bar.get("trading_day") or bar.get("trade_date")))
    future_evidence: list[dict[str, Any]] = []
    missing_available_at: list[dict[str, Any]] = []
    visible_evidence: list[dict[str, Any]] = []
    for domain, available_raw, source_pk in domains:
        if available_raw in (None, ""):
            missing_available_at.append({"domain": domain, "source_pk": source_pk})
            continue
        available = _parse_time(available_raw)
        if available is None:
            missing_available_at.append({"domain": domain, "source_pk": source_pk, "reason": "invalid_available_at"})
            continue
        item = {"domain": domain, "source_pk": source_pk, "available_at": available}
        if available > decision_time:
            future_evidence.append(item)
        else:
            visible_evidence.append(item)
    status = "usable"
    if future_evidence:
        status = "blocked_time_leakage"
    elif missing_available_at:
        status = "blocked_missing_available_at_lineage"
    return _jsonable(
        {
            "contract_kind": "hot_source_visibility_audit_v1",
            "decision_time": decision_time,
            "status": status,
            "visible_count": len(visible_evidence),
            "missing_available_at_count": len(missing_available_at),
            "future_evidence_count": len(future_evidence),
            "visible_evidence": visible_evidence[:20],
            "missing_available_at": missing_available_at[:50],
            "future_evidence": future_evidence[:20],
            "hard_block_codes": (["evidence_available_after_decision_time"] if future_evidence else []) + (["missing_available_at_lineage"] if missing_available_at else []),
            "warning_codes": [],
        }
    )


def _latest_daily_bar(row: dict[str, Any]) -> dict[str, Any]:
    bars = [item for item in row.get("daily_bars") or [] if isinstance(item, dict)]
    if not bars:
        return {}
    return sorted(bars, key=lambda item: str(item.get("trading_day") or ""))[-1]


def _reference_price_from_row(row: dict[str, Any], *, calculated_at: datetime) -> tuple[Decimal | None, str, dict[str, Any], list[str]]:
    """Return an official reference candidate only from stage-valid evidence.

    Production rule: latest_price / previous_close may be used for diagnostics, but they
    must never freeze the first official evaluation reference. Official freeze requires
    auction-confirmed or open-5m-confirmed evidence with available_at <= calculated_at.
    """
    auction = row.get("auction_snapshot") if isinstance(row.get("auction_snapshot"), dict) else {}
    open_5m_vwap = _optional_decimal(row.get("open_5m_vwap") or row.get("open_5m_vwap_price"))
    open_5m_available_at = _parse_time(row.get("open_5m_available_at") or row.get("open_5m_vwap_available_at"))
    auction_price = _optional_decimal(auction.get("auction_price") or auction.get("open_price") or auction.get("virtual_open_price"))
    auction_available_at = _parse_time(auction.get("available_at"))
    block_reasons: list[str] = []
    diagnostics = {
        "latest_price_seen_for_diagnostics_only": row.get("latest_price") or row.get("last_price"),
        "previous_close_seen_for_diagnostics_only": row.get("previous_close") or _latest_daily_bar(row).get("close_price"),
    }
    if open_5m_vwap and open_5m_vwap > 0:
        if open_5m_available_at is None:
            return None, "blocked", {"source": "open_5m_vwap", **diagnostics}, ["open_5m_missing_available_at"]
        if open_5m_available_at > calculated_at:
            return None, "blocked", {"source": "open_5m_vwap", "available_at": open_5m_available_at, **diagnostics}, ["open_5m_available_after_calc_time"]
        return open_5m_vwap, "open_5m_confirmed", {"source": "open_5m_vwap", "available_at": open_5m_available_at, **diagnostics}, []
    if auction_price and auction_price > 0:
        if auction_available_at is None:
            return None, "blocked", {"source": "auction_price", **diagnostics}, ["auction_missing_available_at"]
        if auction_available_at > calculated_at:
            return None, "blocked", {"source": "auction_price", "available_at": auction_available_at, **diagnostics}, ["auction_available_after_calc_time"]
        return auction_price, "auction_confirmed", {"source": "auction_price", "available_at": auction_available_at, **diagnostics}, []
    block_reasons.append("missing_official_reference_stage_evidence")
    return None, "blocked", {"source": "no_official_stage_reference", **diagnostics}, block_reasons

def build_hot_buy_point_decision(row: dict[str, Any], research_contract: dict[str, Any], *, calculated_at: datetime) -> dict[str, Any]:
    release_gate = research_contract.get("release_gate") or {}
    decision_case = research_contract.get("hot_decision_case") or {}
    hot_cycle = research_contract.get("hot_cycle") or {}
    lifecycle = decision_case.get("lifecycle_stage_at_decision") or hot_cycle.get("lifecycle_stage") or "unknown"
    reference, calc_stage, trace, stage_block_reasons = _reference_price_from_row(row, calculated_at=calculated_at)
    latest_bar = _latest_daily_bar(row)
    prev_close = _optional_decimal(row.get("previous_close") or latest_bar.get("close_price"))
    auction = row.get("auction_snapshot") if isinstance(row.get("auction_snapshot"), dict) else {}
    auction_price = _optional_decimal(auction.get("auction_price") or auction.get("open_price") or auction.get("virtual_open_price"))
    high_gap_pct = _price_ratio_pct(auction_price, prev_close)
    is_one_word = bool((hot_cycle.get("limit_state") or {}).get("is_one_word_limit"))
    status = "confirmed" if reference and release_gate.get("official_signal_allowed") else "blocked"
    block_reasons: list[str] = []
    if not release_gate.get("official_signal_allowed"):
        block_reasons.append("release_gate_not_passed")
    if reference is None:
        block_reasons.append("missing_reference_price")
    block_reasons.extend(stage_block_reasons)
    if is_one_word:
        status = "blocked"
        block_reasons.append("one_word_limit_no_fill")
    if lifecycle == "high_board_overheat" and not _boolish(row.get("high_board_execution_allowed")):
        status = "blocked"
        block_reasons.append("high_board_execution_risk")
    if high_gap_pct is not None and high_gap_pct >= Decimal("8") and lifecycle in {"high_board_overheat", "consecutive_board_continuation"}:
        status = "blocked"
        block_reasons.append("open_gap_overheated")
    if block_reasons:
        status = "blocked"
    target_return = _optional_decimal(row.get("target_return_pct")) or (DEFAULT_TARGET_RETURN * Decimal("100"))
    target_return_ratio = target_return / Decimal("100") if target_return > 1 else target_return
    invalidation_ratio = _optional_decimal(row.get("invalidation_return_pct"))
    if invalidation_ratio is None:
        invalidation_ratio = Decimal("-0.04")
    elif invalidation_ratio < -1:
        invalidation_ratio = invalidation_ratio / Decimal("100")
    target_price = (reference * (Decimal("1") + target_return_ratio)).quantize(Decimal("0.000001")) if reference else None
    invalidation_price = (reference * (Decimal("1") + invalidation_ratio)).quantize(Decimal("0.000001")) if reference else None
    low_band = (reference * Decimal("0.995")).quantize(Decimal("0.000001")) if reference else None
    high_band = (reference * Decimal("1.005")).quantize(Decimal("0.000001")) if reference else None
    buy_point_payload = {
        "hot_case_id": decision_case.get("hot_case_id"),
        "calc_stage": calc_stage,
        "reference_entry_price": reference,
        "calculated_at": calculated_at.isoformat(),
        "release_gate": release_gate,
    }
    return _jsonable(
        {
            "contract_kind": "hot_buy_point_decision_v1",
            "buy_point_id": _stable_hash(buy_point_payload, "hot-buy"),
            "hot_case_id": decision_case.get("hot_case_id"),
            "hot_cycle_id": decision_case.get("hot_cycle_id"),
            "adapter_code": "hot_candidates_buy_point_adapter",
            "adapter_version": HOT_BUY_POINT_ADAPTER_VERSION,
            "calc_stage": calc_stage,
            "reference_entry_price": reference,
            "entry_price_low": low_band,
            "entry_price_high": high_band,
            "target_price": target_price,
            "invalidation_price": invalidation_price,
            "risk_reward_ratio": "2.000000" if reference and invalidation_price and target_price else None,
            "buy_point_status": status,
            "block_reason": ";".join(sorted(set(block_reasons))) if block_reasons else None,
            "calculated_at": calculated_at,
            "data_as_of": _parse_time(row.get("data_as_of")) or calculated_at,
            "is_first_valid": status == "confirmed",
            "is_frozen_reference": status == "confirmed",
            "decision_trace_json": {
                "lifecycle_stage": lifecycle,
                "reference_source": trace,
                "high_gap_pct": high_gap_pct,
                "block_reasons": sorted(set(block_reasons)),
                "first_valid_reference_must_not_drift": True,
            },
        }
    )


def build_hot_signal_fact(research_contract: dict[str, Any], *, selected_at: datetime) -> dict[str, Any]:
    """Build the hot model's independent signal fact.

    This is intentionally model-domain-owned. It is not a shared model_signal table:
    governance registry may index it later, but the business truth remains here.
    """
    decision_case = research_contract.get("hot_decision_case") or {}
    release_gate = research_contract.get("release_gate") or {}
    initial = research_contract.get("initial_decision_snapshot") or {}
    stage_scores = research_contract.get("stage_scores") or {}
    signal_payload = {
        "hot_case_id": decision_case.get("hot_case_id"),
        "hot_cycle_id": decision_case.get("hot_cycle_id"),
        "decision_time": decision_case.get("decision_time"),
        "model_version": HOT_MODEL_REFINED_VERSION,
        "signal_stage": release_gate.get("signal_stage"),
    }
    signal_stage = release_gate.get("signal_stage") or "research_sample"
    official = bool(release_gate.get("official_signal_allowed"))
    return _jsonable(
        {
            "contract_kind": "hot_signal_fact_v1",
            "hot_signal_id": _stable_hash(signal_payload, "hot-signal"),
            "hot_case_id": decision_case.get("hot_case_id"),
            "hot_cycle_id": decision_case.get("hot_cycle_id"),
            "symbol": decision_case.get("symbol"),
            "stock_name": decision_case.get("stock_name"),
            "signal_date": decision_case.get("trade_date"),
            "selected_at": selected_at,
            "decision_time": decision_case.get("decision_time") or selected_at,
            "model_version": HOT_MODEL_REFINED_VERSION,
            "model_score": stage_scores.get("official_hot_score") or initial.get("first_score"),
            "signal_stage": signal_stage,
            "is_official_signal": official,
            "is_research_only": not official,
            "release_gate_status": release_gate.get("gate_status"),
            "release_gate_reason": sorted(set((release_gate.get("block_reasons") or []) + (release_gate.get("warning_reasons") or []))),
        }
    )


def build_hot_outcome_label(
    *,
    hot_case_id: str,
    buy_point: dict[str, Any],
    observations: list[dict[str, Any]],
    as_of_time_utc: datetime,
    trade_day_index: int | None = None,
) -> dict[str, Any]:
    reference = _optional_decimal(buy_point.get("reference_entry_price"))
    target = _optional_decimal(buy_point.get("target_price"))
    invalidation = _optional_decimal(buy_point.get("invalidation_price"))
    max_mfe: Decimal | None = None
    min_mae: Decimal | None = None
    first_target_at: datetime | None = None
    first_invalidation_at: datetime | None = None
    latest_return: Decimal | None = None
    for obs in observations:
        observe_time = _parse_time(obs.get("observe_time")) or as_of_time_utc
        mfe = _optional_decimal(obs.get("mfe_pct"))
        mae = _optional_decimal(obs.get("mae_pct"))
        ret = _optional_decimal(obs.get("return_from_reference_pct"))
        if mfe is not None and (max_mfe is None or mfe > max_mfe):
            max_mfe = mfe
        if mae is not None and (min_mae is None or mae < min_mae):
            min_mae = mae
        if ret is not None:
            latest_return = ret
        high = _optional_decimal(obs.get("high_since_entry") or obs.get("latest_price"))
        low = _optional_decimal(obs.get("low_since_entry") or obs.get("latest_price"))
        if first_target_at is None and target is not None and high is not None and high >= target:
            first_target_at = observe_time
        if first_invalidation_at is None and invalidation is not None and low is not None and low <= invalidation:
            first_invalidation_at = observe_time
        if obs.get("first_event_type") == "target_hit_or_touched" and first_target_at is None:
            first_target_at = observe_time
        if obs.get("first_event_type") == "invalidation_hit_or_touched" and first_invalidation_at is None:
            first_invalidation_at = observe_time
    first_event_type = "none"
    if first_target_at and first_invalidation_at:
        first_event_type = "target_first" if first_target_at <= first_invalidation_at else "invalidation_first"
    elif first_target_at:
        first_event_type = "target_first"
    elif first_invalidation_at:
        first_event_type = "invalidation_first"
    direction_outcome = "direction_pending"
    validation_status = "monitoring"
    if first_target_at:
        direction_outcome = "direction_success"
        validation_status = "target_hit"
    elif first_invalidation_at:
        direction_outcome = "direction_failed"
        validation_status = "invalidation_hit"
    elif trade_day_index is not None and trade_day_index >= 5 and max_mfe is not None and max_mfe < Decimal("8"):
        direction_outcome = "direction_failed"
        validation_status = "t5_not_hit"
    execution_outcome = "executable" if buy_point.get("buy_point_status") == "confirmed" else "buy_point_blocked"
    if buy_point.get("block_reason"):
        reason = str(buy_point.get("block_reason"))
        if "no_fill" in reason:
            execution_outcome = "no_fill_opportunity"
        elif "overheated" in reason:
            execution_outcome = "entry_too_high"
    path_outcome = "pending"
    if first_event_type == "target_first":
        path_outcome = "target_first"
    elif first_event_type == "invalidation_first":
        path_outcome = "invalidation_first"
    elif max_mfe is not None and max_mfe >= Decimal("6"):
        path_outcome = "mfe_near_target"
    elif latest_return is not None and latest_return < Decimal("-3"):
        path_outcome = "drawdown_expanded"
    label_payload = {"hot_case_id": hot_case_id, "label_version": HOT_OUTCOME_LABEL_VERSION, "as_of": as_of_time_utc.isoformat(), "status": validation_status}
    return _jsonable(
        {
            "contract_kind": HOT_OUTCOME_LABEL_VERSION,
            "outcome_id": _stable_hash(label_payload, "hot-outcome"),
            "hot_case_id": hot_case_id,
            "label_version": HOT_OUTCOME_LABEL_VERSION,
            "direction_outcome": direction_outcome,
            "execution_outcome": execution_outcome,
            "path_outcome": path_outcome,
            "environment_outcome": "not_evaluated",
            "data_outcome": "data_complete" if observations and reference else "data_insufficient",
            "validation_status": validation_status,
            "t5_status": "t5_hit" if first_target_at else "t5_not_mature" if trade_day_index is None or trade_day_index < 5 else "t5_not_hit",
            "t20_status": "t20_not_mature" if trade_day_index is None or trade_day_index < 20 else "t20_finalized",
            "first_target_hit_at": first_target_at,
            "first_invalidation_hit_at": first_invalidation_at,
            "first_event_type": first_event_type,
            "actual_days_to_target": trade_day_index if first_target_at and trade_day_index is not None else None,
            "mfe_pct": max_mfe,
            "mae_pct": min_mae,
            "max_return_pct": max_mfe,
            "max_drawdown_pct": min_mae,
            "label_maturity_status": "mature" if first_target_at or first_invalidation_at or (trade_day_index is not None and trade_day_index >= 5) else "pending",
        }
    )


def build_hot_failure_attribution(
    *,
    research_contract: dict[str, Any],
    buy_point: dict[str, Any],
    outcome: dict[str, Any],
    observations: list[dict[str, Any]],
    source_visibility_audit: dict[str, Any],
) -> dict[str, Any]:
    hot_case_id = (research_contract.get("hot_decision_case") or {}).get("hot_case_id", "unknown-hot-case")
    lifecycle = (research_contract.get("hot_decision_case") or {}).get("lifecycle_stage_at_decision", "unknown")
    deviation_codes = sorted({str(code) for obs in observations for code in (obs.get("deviation_reason_codes") or [])})
    primary = "not_failed"
    causality = "model_uncertain"
    secondary: list[str] = []
    if outcome.get("direction_outcome") not in {"direction_failed"} and outcome.get("execution_outcome") == "executable":
        causality = "not_failure"
    elif source_visibility_audit.get("status") == "blocked_time_leakage" or outcome.get("data_outcome") == "data_insufficient":
        causality = "data_quality_driven"
        primary = "data_quality_or_time_lineage_issue"
    elif outcome.get("execution_outcome") in {"buy_point_blocked", "no_fill_opportunity", "entry_too_high"}:
        causality = "execution_driven"
        primary = str(outcome.get("execution_outcome"))
    elif "sector_cooling_after_signal" in deviation_codes:
        causality = "sector_environment_driven"
        primary = "sector_cooling_after_signal"
    elif "vwap_lost_after_entry" in deviation_codes:
        causality = "execution_driven"
        primary = "vwap_lost_after_entry"
    elif lifecycle in {"high_board_overheat", "consecutive_board_continuation"} and outcome.get("direction_outcome") == "direction_failed":
        causality = "model_uncertain"
        primary = "possible_hot_lifecycle_overheat_under_penalized_requires_bucket_evidence"
    elif outcome.get("direction_outcome") == "direction_failed":
        causality = "model_uncertain"
        primary = "direction_failed_without_systematic_bucket_yet"
    if buy_point.get("block_reason"):
        secondary.extend(str(buy_point.get("block_reason")).split(";"))
    secondary.extend(deviation_codes)
    is_systematic = False
    return _jsonable(
        {
            "contract_kind": HOT_FAILURE_ATTRIBUTION_VERSION,
            "failure_attribution_id": _stable_hash({"hot_case_id": hot_case_id, "outcome": outcome.get("outcome_id")}, "hot-failure"),
            "hot_case_id": hot_case_id,
            "failure_causality_type": causality,
            "primary_failure_reason": primary,
            "secondary_failure_reasons": sorted(set(item for item in secondary if item)),
            "similar_case_bucket": lifecycle,
            "similar_case_count": None,
            "similar_case_failure_rate_pct": None,
            "is_systematic_pattern": is_systematic,
            "evidence_json": {
                "lifecycle_stage": lifecycle,
                "deviation_reason_codes": deviation_codes,
                "source_visibility_status": source_visibility_audit.get("status"),
                "buy_point_status": buy_point.get("buy_point_status"),
            },
        }
    )


def build_hot_first_output_distortion_analysis(
    *,
    research_contract: dict[str, Any],
    outcome: dict[str, Any],
    failure_attribution: dict[str, Any],
) -> dict[str, Any]:
    initial = research_contract.get("initial_decision_snapshot") or {}
    stage_scores = research_contract.get("stage_scores") or {}
    score_inputs = stage_scores.get("score_inputs") or {}
    distortion_type = "none"
    primary = None
    secondary: list[str] = []
    causality = failure_attribution.get("failure_causality_type")
    if causality == "data_quality_driven":
        distortion_type = "evidence_distortion"
        primary = failure_attribution.get("primary_failure_reason")
    elif causality == "execution_driven":
        distortion_type = "buy_point_distortion"
        primary = failure_attribution.get("primary_failure_reason")
    elif causality == "model_systematic":
        distortion_type = "weight_or_gate_distortion"
        primary = failure_attribution.get("primary_failure_reason")
    elif outcome.get("direction_outcome") == "direction_failed":
        distortion_type = "model_uncertain_distortion"
        primary = "sample_not_enough_for_systematic_judgement"
    recommended = {
        "do_not_mutate_production_model_online": True,
        "requires_bucket_level_review": distortion_type not in {"none", "buy_point_distortion"},
        "requires_buy_point_adapter_review": distortion_type == "buy_point_distortion",
    }
    return _jsonable(
        {
            "contract_kind": HOT_DISTORTION_ANALYSIS_VERSION,
            "distortion_analysis_id": _stable_hash({"hot_case_id": initial.get("hot_case_id"), "distortion_type": distortion_type, "outcome": outcome.get("outcome_id")}, "hot-distortion"),
            "hot_case_id": initial.get("hot_case_id"),
            "first_model_version": initial.get("model_version") or HOT_MODEL_REFINED_VERSION,
            "first_score": initial.get("first_score"),
            "first_lifecycle_stage": initial.get("first_lifecycle_stage"),
            "first_teacher_prior_raw": initial.get("first_teacher_prior_raw"),
            "first_teacher_prior_calibrated": initial.get("first_teacher_prior_calibrated"),
            "first_local_confirmation": score_inputs.get("local_confirmation_score"),
            "first_auction_confirmation": score_inputs.get("auction_confirmation_score"),
            "first_overheat_risk": score_inputs.get("overheating_failure_risk"),
            "final_outcome": outcome.get("direction_outcome"),
            "distortion_type": distortion_type,
            "primary_distortion_factor": primary,
            "secondary_distortion_factors": sorted(set(secondary + list(failure_attribution.get("secondary_failure_reasons") or []))),
            "is_systematic_pattern": failure_attribution.get("is_systematic_pattern") or False,
            "recommended_correction": recommended,
            "analysis_status": "complete" if outcome.get("label_maturity_status") == "mature" else "pending",
        }
    )


def run_hot_full_pipeline(payload: dict[str, Any], *, as_of_time_utc: datetime | None = None) -> dict[str, Any]:
    """Run the full hot model lifecycle in-process for validation and orchestration.

    This is not a substitute for persistence. It wires the same contracts together so
    scheduler/integration tests can prove the flow is coherent before any service writes
    database rows.
    """
    now = as_of_time_utc or datetime.now(timezone.utc)
    row = payload.get("row") if isinstance(payload.get("row"), dict) else payload
    run_id = payload.get("run_id") or utc_run_id("hot-pipeline")
    analysis = build_candidate_source_analysis(row, candidate_source="hot_candidates", run_id=run_id)
    legacy_contract = build_hot_candidate_v1_contract(analysis, as_of_time_utc=now)
    research = build_hot_research_contract(row, legacy_analysis=analysis, legacy_contract=legacy_contract, as_of_time_utc=now)
    source_visibility = build_hot_source_visibility_audit(row, decision_time=now)
    # Apply source visibility hard block after the legacy contract has been created so time-leakage
    # never becomes an official release in the refined contract.
    if source_visibility.get("hard_block_codes"):
        research["release_gate"]["gate_status"] = "blocked"
        research["release_gate"]["official_signal_allowed"] = False
        research["release_gate"]["recommendation_eligibility"] = "not_eligible"
        research["release_gate"]["signal_stage"] = "research_sample"
        research["release_gate"].setdefault("block_reasons", [])
        research["release_gate"]["block_reasons"] = sorted(set(research["release_gate"]["block_reasons"] + source_visibility["hard_block_codes"]))
    research["source_visibility_audit"] = source_visibility
    hot_signal = build_hot_signal_fact(research, selected_at=now)
    buy_point = build_hot_buy_point_decision(row, research, calculated_at=now)
    buy_point["hot_signal_id"] = hot_signal.get("hot_signal_id")
    observation_payloads = payload.get("observations") if isinstance(payload.get("observations"), list) else []
    observations: list[dict[str, Any]] = []
    for idx, item in enumerate(observation_payloads, start=1):
        if not isinstance(item, dict):
            continue
        merged = {
            "hot_case_id": research["hot_decision_case"]["hot_case_id"],
            "hot_cycle_id": research["hot_decision_case"]["hot_cycle_id"],
            "observe_seq": idx + 1,
            "reference_entry_price": buy_point.get("reference_entry_price"),
            "target_price": buy_point.get("target_price"),
            "invalidation_price": buy_point.get("invalidation_price"),
            **item,
        }
        obs_time = _parse_time(item.get("observe_time") or item.get("data_as_of")) or now
        observations.append(build_hot_observation_snapshot(merged, as_of_time_utc=obs_time))
    trade_day_index = payload.get("trade_day_index")
    if trade_day_index is not None:
        try:
            trade_day_index = int(trade_day_index)
        except (TypeError, ValueError):
            trade_day_index = None
    outcome = build_hot_outcome_label(
        hot_case_id=research["hot_decision_case"]["hot_case_id"],
        buy_point=buy_point,
        observations=observations,
        as_of_time_utc=now,
        trade_day_index=trade_day_index,
    )
    failure = build_hot_failure_attribution(
        research_contract=research,
        buy_point=buy_point,
        outcome=outcome,
        observations=observations,
        source_visibility_audit=source_visibility,
    )
    distortion = build_hot_first_output_distortion_analysis(research_contract=research, outcome=outcome, failure_attribution=failure)
    if outcome.get("label_maturity_status") == "mature":
        evolution = build_hot_evolution_sample(
            {
                "hot_case_id": research["hot_decision_case"]["hot_case_id"],
                "hot_cycle_id": research["hot_decision_case"]["hot_cycle_id"],
                "initial_decision_snapshot": research["initial_decision_snapshot"],
                "observation": observations[-1] if observations else {},
                "outcome_label": outcome,
                "failure_attribution": failure,
                "lifecycle_stage_at_decision": research["hot_decision_case"].get("lifecycle_stage_at_decision"),
            },
            as_of_time_utc=now,
        )
    else:
        evolution = {
            "contract_kind": "hot_evolution_sample_v1",
            "hot_case_id": research["hot_decision_case"]["hot_case_id"],
            "sample_type": "not_generated",
            "maturity_status": "blocked_outcome_not_mature",
            "recommended_adjustment_json": {"do_not_mutate_production_model_online": True},
        }
    research_pool = build_hot_research_sample_pool_record(
        {
            "research_contract": research,
            "hot_signal": hot_signal,
            "buy_point": buy_point,
            "observations": observations,
            "outcome_label": outcome,
            "failure_attribution": failure,
        },
        generated_at=now,
    )
    return _jsonable(
        {
            "contract_kind": HOT_PIPELINE_CONTRACT_VERSION,
            "run_id": run_id,
            "model_version": HOT_MODEL_REFINED_VERSION,
            "legacy_analysis": analysis,
            "legacy_contract": legacy_contract,
            "research_contract": research,
            "hot_signal": hot_signal,
            "buy_point": buy_point,
            "observations": observations,
            "outcome_label": outcome,
            "failure_attribution": failure,
            "first_output_distortion_analysis": distortion,
            "evolution_sample": evolution,
            "research_sample_pool": research_pool,
            "validation_summary": {
                "initial_decision_frozen": research["initial_decision_snapshot"].get("is_immutable_first_decision") is True,
                "observations_append_only": all(obs.get("append_only") for obs in observations),
                "official_release_allowed": research["release_gate"].get("official_signal_allowed"),
                "first_reference_frozen": buy_point.get("is_frozen_reference") is True,
                "outcome_maturity_status": outcome.get("label_maturity_status"),
                "model_mutation_online": False,
                "research_pool_append_only": research_pool.get("include_in_model_evolution") is True,
            },
        }
    )
