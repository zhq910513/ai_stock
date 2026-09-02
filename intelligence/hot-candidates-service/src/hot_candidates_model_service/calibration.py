from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from hot_candidates_model_service.research import HOT_MODEL_REFINED_VERSION, infer_lifecycle_stage

HOT_RESEARCH_SAMPLE_POOL_VERSION = "hot_research_sample_pool_v1"
HOT_TEACHER_CALIBRATION_REPORT_VERSION = "hot_teacher_calibration_report_v1"
DEFAULT_MIN_BUCKET_SAMPLES = 30
DEFAULT_MIN_TOTAL_SAMPLES = 120


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
    numeric = _decimal(value)
    if numeric > 1:
        numeric = numeric / Decimal("100")
    if numeric < 0:
        return Decimal("0")
    if numeric > 1:
        return Decimal("1")
    return numeric.quantize(Decimal("0.000001"))


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


def _text(value: Any, default: str = "") -> str:
    if value in (None, ""):
        return default
    return str(value)


def _boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return False
    return str(value).strip().lower() in {"true", "1", "yes", "y", "是"}


def _is_success(direction_outcome: str) -> bool | None:
    if direction_outcome in {"direction_success", "direction_delayed_success"}:
        return True
    if direction_outcome in {"direction_failed", "structure_invalidated", "direction_contradicted"}:
        return False
    return None


def _extract_pipeline(sample: dict[str, Any]) -> dict[str, Any]:
    """Normalize flat rows or /pipeline/run outputs into one research sample row."""
    pipeline = sample.get("pipeline") if isinstance(sample.get("pipeline"), dict) else sample
    research = pipeline.get("research_contract") if isinstance(pipeline.get("research_contract"), dict) else {}
    decision_case = research.get("hot_decision_case") if isinstance(research.get("hot_decision_case"), dict) else {}
    cycle = research.get("hot_cycle") if isinstance(research.get("hot_cycle"), dict) else {}
    teacher = research.get("teacher_calibration") if isinstance(research.get("teacher_calibration"), dict) else {}
    release_gate = research.get("release_gate") if isinstance(research.get("release_gate"), dict) else {}
    stage_scores = research.get("stage_scores") if isinstance(research.get("stage_scores"), dict) else {}
    signal = pipeline.get("hot_signal") if isinstance(pipeline.get("hot_signal"), dict) else {}
    buy_point = pipeline.get("buy_point") if isinstance(pipeline.get("buy_point"), dict) else {}
    outcome = pipeline.get("outcome_label") if isinstance(pipeline.get("outcome_label"), dict) else {}
    failure = pipeline.get("failure_attribution") if isinstance(pipeline.get("failure_attribution"), dict) else {}
    observation = {}
    observations = pipeline.get("observations") if isinstance(pipeline.get("observations"), list) else []
    if observations and isinstance(observations[-1], dict):
        observation = observations[-1]

    raw_prior = _score01(
        sample.get("teacher_prior_raw")
        or sample.get("p_limit_up_raw")
        or sample.get("p_limit_up")
        or teacher.get("teacher_prior_raw")
    )
    calibrated = _score01(sample.get("teacher_prior_calibrated") or teacher.get("teacher_prior_calibrated") or raw_prior)
    lifecycle = _text(
        sample.get("lifecycle_stage")
        or sample.get("lifecycle_stage_at_decision")
        or decision_case.get("lifecycle_stage_at_decision")
        or cycle.get("lifecycle_stage"),
        "unknown",
    )
    if lifecycle == "unknown" and sample:
        lifecycle = infer_lifecycle_stage(sample)
    direction = _text(sample.get("direction_outcome") or outcome.get("direction_outcome"), "direction_pending")
    execution = _text(sample.get("execution_outcome") or outcome.get("execution_outcome"), "execution_pending")
    success = _is_success(direction)
    return {
        "hot_case_id": sample.get("hot_case_id") or decision_case.get("hot_case_id") or outcome.get("hot_case_id"),
        "hot_cycle_id": sample.get("hot_cycle_id") or decision_case.get("hot_cycle_id") or cycle.get("hot_cycle_id"),
        "symbol": sample.get("symbol") or decision_case.get("symbol") or cycle.get("symbol"),
        "trade_date": sample.get("trade_date") or decision_case.get("trade_date") or signal.get("signal_date"),
        "lifecycle_stage": lifecycle,
        "probability_bucket": sample.get("probability_bucket") or teacher.get("teacher_probability_bucket") or _probability_bucket(raw_prior),
        "teacher_prior_raw": raw_prior,
        "teacher_prior_calibrated": calibrated,
        "official_hot_score": _optional_decimal(sample.get("official_hot_score") or stage_scores.get("official_hot_score")),
        "release_gate_status": _text(sample.get("release_gate_status") or release_gate.get("gate_status"), "unknown"),
        "signal_stage": _text(sample.get("signal_stage") or release_gate.get("signal_stage") or signal.get("signal_stage"), "unknown"),
        "official_signal_allowed": _boolish(sample.get("official_signal_allowed") or release_gate.get("official_signal_allowed") or signal.get("is_official_signal")),
        "direction_outcome": direction,
        "execution_outcome": execution,
        "success": success,
        "mfe_pct": _optional_decimal(sample.get("mfe_pct") or outcome.get("mfe_pct") or observation.get("mfe_pct")),
        "mae_pct": _optional_decimal(sample.get("mae_pct") or outcome.get("mae_pct") or observation.get("mae_pct")),
        "market_regime_bucket": _text(sample.get("market_regime_bucket") or sample.get("market_state") or outcome.get("environment_outcome"), "all"),
        "sector_heat_bucket": _text(sample.get("sector_heat_bucket") or sample.get("sector_state"), "all"),
        "failure_causality_type": _text(sample.get("failure_causality_type") or failure.get("failure_causality_type"), "unknown"),
        "buy_point_status": _text(sample.get("buy_point_status") or buy_point.get("buy_point_status"), "unknown"),
        "block_reasons": list(release_gate.get("block_reasons") or []) + list(release_gate.get("warning_reasons") or []),
    }


def build_hot_research_sample_pool_record(pipeline_or_sample: dict[str, Any], *, generated_at: datetime | None = None) -> dict[str, Any]:
    """Classify one hot case into official/calibration/blocked-track research pools.

    The record is a research contract, not a recommendation. Only official_signal_pool
    may count in formal success rate. Other pools exist to prevent selection bias and
    to let second-and-later observations improve future model versions.
    """
    now = generated_at or datetime.now(timezone.utc)
    item = _extract_pipeline(pipeline_or_sample)
    p_raw = item["teacher_prior_raw"]
    official_score = item.get("official_hot_score")
    direction = item["direction_outcome"]
    success = item["success"]
    reasons: list[str] = []
    if item["official_signal_allowed"]:
        pool = "official_signal_pool"
        reasons.append("release_gate_passed")
    elif item["signal_stage"] == "calibration_signal" or item["release_gate_status"] == "calibration_only":
        pool = "calibration_pool"
        reasons.append("calibration_signal_not_formal_recommendation")
    elif p_raw >= Decimal("0.70") or (official_score is not None and official_score >= Decimal("50")):
        pool = "blocked_but_track_pool"
        reasons.append("blocked_or_warning_sample_still_has_learning_value")
    else:
        pool = "research_watch_pool"
        reasons.append("non_official_observation_for_selection_bias_control")
    if p_raw >= Decimal("0.70") and success is False:
        pool = "teacher_distortion_pool"
        reasons.append("high_teacher_probability_failed")
    if p_raw <= Decimal("0.45") and success is True:
        pool = "teacher_distortion_pool"
        reasons.append("low_teacher_probability_succeeded")
    if "evidence_available_after_decision_time" in item["block_reasons"]:
        should_track = False
        reasons.append("time_leakage_sample_excluded_from_learning")
    else:
        should_track = True
    if pool == "official_signal_pool":
        frequency = "official_signal_monitoring_schedule"
    elif pool == "teacher_distortion_pool":
        frequency = "high_priority_research_schedule"
    elif pool == "blocked_but_track_pool":
        frequency = "research_tracking_schedule"
    else:
        frequency = "low_frequency_research_schedule"
    payload = {
        "hot_case_id": item.get("hot_case_id"),
        "pool": pool,
        "generated_at": now.isoformat(),
    }
    return _jsonable(
        {
            "contract_kind": HOT_RESEARCH_SAMPLE_POOL_VERSION,
            "pool_record_id": _stable_hash(payload, "hot-pool"),
            "hot_case_id": item.get("hot_case_id"),
            "hot_cycle_id": item.get("hot_cycle_id"),
            "symbol": item.get("symbol"),
            "trade_date": item.get("trade_date"),
            "lifecycle_stage": item["lifecycle_stage"],
            "probability_bucket": item["probability_bucket"],
            "teacher_prior_raw": item["teacher_prior_raw"],
            "official_hot_score": item.get("official_hot_score"),
            "release_gate_status": item["release_gate_status"],
            "signal_stage": item["signal_stage"],
            "tracking_pool": pool,
            "should_track": should_track,
            "tracking_frequency_hint": frequency,
            "tracking_reason_codes": sorted(set(reasons)),
            "include_in_official_success_rate": pool == "official_signal_pool",
            "include_in_teacher_calibration": should_track and item["success"] is not None,
            "include_in_model_evolution": should_track,
            "generated_at": now,
        }
    )


def _rate(n: int, d: int) -> Decimal | None:
    if d <= 0:
        return None
    return (Decimal(n) / Decimal(d)).quantize(Decimal("0.000001"))


def _avg(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    return (sum(values) / Decimal(len(values))).quantize(Decimal("0.000001"))


def _brier(rows: list[dict[str, Any]], *, probability_key: str = "teacher_prior_raw") -> Decimal | None:
    errors: list[Decimal] = []
    for row in rows:
        success = row.get("success")
        if success is None:
            continue
        p = _score01(row.get(probability_key))
        y = Decimal("1") if success else Decimal("0")
        errors.append((p - y) ** 2)
    return _avg(errors)


def build_hot_teacher_calibration_report(
    samples: list[dict[str, Any]],
    *,
    calibration_version: str = "hot_teacher_calibration_v1_generated",
    min_bucket_samples: int = DEFAULT_MIN_BUCKET_SAMPLES,
    min_total_samples: int = DEFAULT_MIN_TOTAL_SAMPLES,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    now = generated_at or datetime.now(timezone.utc)
    normalized = [_extract_pipeline(item) for item in samples]
    evaluated = [item for item in normalized if item["success"] is not None]
    overall_hits = sum(1 for item in evaluated if item["success"] is True)
    overall_rate = _rate(overall_hits, len(evaluated))
    overall_brier = _brier(evaluated)
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for item in normalized:
        key = (
            item["lifecycle_stage"],
            item["probability_bucket"],
            item["market_regime_bucket"],
            item["sector_heat_bucket"],
        )
        groups.setdefault(key, []).append(item)
    rows: list[dict[str, Any]] = []
    for (stage, bucket, market_bucket, sector_bucket), group in sorted(groups.items()):
        group_evaluated = [item for item in group if item["success"] is not None]
        hit_count = sum(1 for item in group_evaluated if item["success"] is True)
        realized = _rate(hit_count, len(group_evaluated))
        avg_pred = _avg([_score01(item["teacher_prior_raw"]) for item in group_evaluated])
        brier = _brier(group_evaluated)
        lift = None
        if realized is not None and overall_rate is not None and overall_rate > 0:
            lift = (realized / overall_rate).quantize(Decimal("0.000001"))
        can_activate = len(group_evaluated) >= min_bucket_samples
        recommendation = "sample_insufficient_keep_raw_prior"
        if can_activate and realized is not None and avg_pred is not None:
            delta = realized - avg_pred
            if delta <= Decimal("-0.15"):
                recommendation = "down_calibrate_teacher_prior"
            elif delta >= Decimal("0.15"):
                recommendation = "up_calibrate_teacher_prior"
            else:
                recommendation = "teacher_prior_bucket_reliable"
        rows.append(
            _jsonable(
                {
                    "calibration_version": calibration_version,
                    "lifecycle_stage": stage,
                    "probability_bucket": bucket,
                    "market_regime_bucket": market_bucket,
                    "sector_heat_bucket": sector_bucket,
                    "sample_count": len(group),
                    "evaluated_count": len(group_evaluated),
                    "hit_count": hit_count,
                    "realized_hit_rate": realized,
                    "avg_predicted_probability": avg_pred,
                    "calibration_error": abs(realized - avg_pred).quantize(Decimal("0.000001")) if realized is not None and avg_pred is not None else None,
                    "brier_score": brier,
                    "lift_vs_overall": lift,
                    "can_activate": can_activate,
                    "recommended_action": recommendation,
                }
            )
        )
    high_teacher_failures = [item for item in evaluated if item["teacher_prior_raw"] >= Decimal("0.70") and item["success"] is False]
    low_teacher_successes = [item for item in evaluated if item["teacher_prior_raw"] <= Decimal("0.45") and item["success"] is True]
    execution_missed = [item for item in evaluated if item["direction_outcome"] in {"direction_success", "direction_delayed_success"} and item["execution_outcome"] in {"execution_missed", "no_fill_opportunity"}]
    warning_codes: list[str] = []
    if len(evaluated) < min_total_samples:
        warning_codes.append("teacher_calibration_total_sample_insufficient")
    if not rows:
        warning_codes.append("teacher_calibration_bucket_empty")
    return _jsonable(
        {
            "contract_kind": HOT_TEACHER_CALIBRATION_REPORT_VERSION,
            "calibration_version": calibration_version,
            "model_version": HOT_MODEL_REFINED_VERSION,
            "generated_at": now,
            "sample_counts": {
                "input_count": len(samples),
                "normalized_count": len(normalized),
                "evaluated_count": len(evaluated),
                "hit_count": overall_hits,
                "failure_count": max(len(evaluated) - overall_hits, 0),
                "official_signal_count": sum(1 for item in normalized if item["official_signal_allowed"]),
                "high_teacher_failure_count": len(high_teacher_failures),
                "low_teacher_success_count": len(low_teacher_successes),
                "direction_success_execution_missed_count": len(execution_missed),
            },
            "overall_metrics": {
                "overall_hit_rate": overall_rate,
                "overall_brier_score": overall_brier,
                "min_total_samples": min_total_samples,
                "min_bucket_samples": min_bucket_samples,
            },
            "bucket_calibrations": rows,
            "distortion_samples": {
                "high_teacher_failures": high_teacher_failures[:20],
                "low_teacher_successes": low_teacher_successes[:20],
                "direction_success_execution_missed": execution_missed[:20],
            },
            "activation_gate": {
                "can_activate_calibration": len(evaluated) >= min_total_samples and any(row.get("can_activate") for row in rows),
                "must_shadow_run_before_production": True,
                "do_not_mutate_online": True,
            },
            "warning_codes": warning_codes,
        }
    )
