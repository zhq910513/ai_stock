from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from candidate_memory_model_service.research_v1 import (
    MEMORY_MODEL_VERSION,
    build_pre_signal_window,
    detect_pre_signal_case,
)

PHASE2_SCHEMA_VERSION = "candidate_memory_phase2_v1"
DEFAULT_OBSERVE_BATCH_LIMIT = 1000
MIN_MATCHED_SAMPLE_COUNT = 10
MIN_TTL_CALIBRATION_SAMPLE_COUNT = 20


def utc_run_id(prefix: str = "candidate-memory-phase2") -> str:
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
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


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


def _mean_decimal(values: list[Decimal]) -> Decimal | None:
    clean = [item for item in values if item is not None]
    if not clean:
        return None
    return sum(clean) / Decimal(len(clean))


def _pct(num: int | Decimal, den: int | Decimal) -> Decimal | None:
    den_dec = Decimal(den)
    if den_dec <= 0:
        return None
    return (Decimal(num) / den_dec * Decimal("100")).quantize(Decimal("0.000001"))


def _event_visibility(event: dict[str, Any], decision_time: datetime) -> tuple[str, str | None]:
    available_at = _dt(event.get("available_at") or event.get("captured_at") or event.get("published_at"))
    if available_at is None:
        return "not_visible", "missing_available_at"
    if available_at > decision_time:
        return "post_hoc", "future_available_at"
    return "ex_ante", None


def standardize_event_signal_features(row: dict[str, Any], *, as_of_time_utc: datetime | None = None, run_id: str | None = None) -> dict[str, Any]:
    """Normalize raw events into ex-ante/post-hoc signal features for candidate_memory.

    This function deliberately does not write business truth. It returns typed feature facts that can be stored
    in decision_memory.memory_event_signal_feature_v1. Production scoring may only use ex_ante rows.
    """

    decision_time = as_of_time_utc or datetime.now(timezone.utc)
    run_id = run_id or utc_run_id("memory-events")
    raw_events = row.get("events") or row.get("news_events") or row.get("announcements") or []
    if not isinstance(raw_events, list):
        raw_events = []
    features: list[dict[str, Any]] = []
    gaps: list[str] = []
    dedup_seen: set[str] = set()
    for event in raw_events:
        if not isinstance(event, dict):
            continue
        event_id = str(event.get("event_id") or event.get("id") or _stable_hash(event)[:16])
        dedup_key = str(event.get("dedup_hash") or event.get("title") or event_id)
        is_duplicate = dedup_key in dedup_seen
        dedup_seen.add(dedup_key)
        visibility, reason = _event_visibility(event, decision_time)
        if reason == "missing_available_at":
            gaps.append("source_gap:event_missing_available_at")
        if reason == "future_available_at":
            gaps.append("source_gap:event_future_available_at")
        relevance = _score(event.get("relevance_score") or event.get("symbol_relevance_score")) or Decimal("50")
        reliability = _score(event.get("source_reliability") or event.get("source_reliability_score") or event.get("reliability_score")) or Decimal("50")
        novelty = _score(event.get("novelty_score")) or Decimal("50")
        strength = _score(event.get("importance_score") or event.get("catalyst_strength_score")) or Decimal("50")
        if is_duplicate:
            novelty = min(novelty, Decimal("20"))
        freshness = Decimal("50")
        available_at = _dt(event.get("available_at") or event.get("published_at") or event.get("captured_at"))
        if available_at is not None:
            age_minutes = max(Decimal("0"), Decimal(str((decision_time - available_at).total_seconds())) / Decimal("60"))
            if age_minutes <= Decimal("30"):
                freshness = Decimal("90")
            elif age_minutes <= Decimal("180"):
                freshness = Decimal("75")
            elif age_minutes <= Decimal("1440"):
                freshness = Decimal("55")
            else:
                freshness = Decimal("35")
        catalyst_score = _clip100(
            relevance * Decimal("0.25")
            + reliability * Decimal("0.20")
            + novelty * Decimal("0.20")
            + strength * Decimal("0.20")
            + freshness * Decimal("0.15")
        )
        feature = {
            "feature_id": f"evtfeat-{row.get('memory_entity_id') or row.get('symbol')}-{event_id}",
            "memory_entity_id": row.get("memory_entity_id"),
            "symbol": str(row.get("symbol") or event.get("symbol") or "").zfill(6),
            "feature_time": decision_time,
            "event_id": event_id,
            "event_time": _dt(event.get("event_time")),
            "published_at": _dt(event.get("published_at")),
            "available_at": available_at,
            "captured_at": _dt(event.get("captured_at")),
            "source": event.get("source"),
            "event_type": event.get("event_type") or "event",
            "theme_tags": list(event.get("theme_tags") or []),
            "relevance_score": relevance,
            "source_reliability_score": reliability,
            "novelty_score": novelty,
            "freshness_score": freshness,
            "catalyst_strength_score": strength,
            "event_catalyst_score": catalyst_score,
            "visibility_class": visibility,
            "is_duplicate": is_duplicate,
            "excluded_from_pre_signal_score": visibility != "ex_ante",
            "guardrails": {
                "available_at_required": True,
                "post_hoc_event_not_eligible_for_pre_signal": True,
                "duplicate_news_penalizes_novelty": True,
            },
        }
        feature["feature_hash"] = _stable_hash(feature)
        features.append(feature)
    ex_ante_count = sum(1 for feature in features if feature["visibility_class"] == "ex_ante")
    post_hoc_count = sum(1 for feature in features if feature["visibility_class"] == "post_hoc")
    result = {
        "schema_version": "candidate_memory_event_signal_feature_batch_v1",
        "run_id": run_id,
        "model_version": MEMORY_MODEL_VERSION,
        "memory_entity_id": row.get("memory_entity_id"),
        "symbol": str(row.get("symbol") or "").zfill(6),
        "decision_time": decision_time,
        "features": features,
        "ex_ante_event_count": ex_ante_count,
        "post_hoc_event_count": post_hoc_count,
        "excluded_event_count": len(features) - ex_ante_count,
        "source_gap_codes": sorted(set(gaps)),
        "guardrails": {
            "production_scoring_uses_ex_ante_features_only": True,
            "available_at_later_than_decision_time_is_post_hoc": True,
            "missing_available_at_cannot_be_ex_ante": True,
        },
    }
    result["batch_hash"] = _stable_hash(result)
    return _jsonable(result)


def build_active_case_registry(row: dict[str, Any], *, as_of_time_utc: datetime | None = None, run_id: str | None = None) -> dict[str, Any]:
    decision_time = as_of_time_utc or datetime.now(timezone.utc)
    run_id = run_id or utc_run_id("memory-registry")
    memory_entity_id = row.get("memory_entity_id") or row.get("entity_id")
    symbol = str(row.get("symbol") or "").zfill(6)
    status = str(row.get("memory_status") or "observing")
    tracking_pool = str(row.get("tracking_pool") or "memory_observation_pool")
    priority = int(row.get("priority_level") or 50)
    close_reason = None
    if status in {"expired_closed", "invalidated", "closed"}:
        frequency = 86_400
        close_reason = status
        priority = 0
    elif row.get("activation_case_id") or row.get("activation_status") == "activation_ready":
        tracking_pool = "activation_case_pool"
        frequency = 180
        priority = max(priority, 95)
    elif row.get("pre_signal_case_id") or row.get("pre_signal_status") == "pre_signal_detected":
        tracking_pool = "pre_signal_case_pool"
        frequency = 300
        priority = max(priority, 90)
    elif status in {"valuable", "near_expiry"}:
        frequency = 900
        priority = max(priority, 70)
    elif status in {"decaying", "expired_but_researchable"}:
        frequency = 3600
        priority = min(priority, 40)
    else:
        frequency = 1800
    budget_class = row.get("budget_class") or ("high" if priority >= 90 else "normal" if priority >= 50 else "low")
    next_observe_at = _dt(row.get("next_observe_at")) or decision_time + timedelta(seconds=frequency)
    result = {
        "schema_version": "candidate_memory_active_case_registry_v1",
        "run_id": run_id,
        "model_version": MEMORY_MODEL_VERSION,
        "memory_entity_id": memory_entity_id,
        "symbol": symbol,
        "tracking_pool": tracking_pool,
        "priority_level": priority,
        "next_observe_at": next_observe_at,
        "last_observe_at": _dt(row.get("last_observe_at")),
        "observe_frequency_seconds": frequency,
        "memory_status": status,
        "budget_class": budget_class,
        "close_reason": close_reason,
        "updated_at": decision_time,
        "guardrails": {
            "registry_is_scheduler_projection_not_training_truth": True,
            "observation_truth_remains_append_only": True,
            "frequency_depends_on_memory_state": True,
        },
    }
    result["registry_hash"] = _stable_hash(result)
    return _jsonable(result)


def _build_observation_for_case(case: dict[str, Any], observe_time: datetime, run_id: str, observe_seq: int) -> dict[str, Any]:
    window = build_pre_signal_window(case, as_of_time_utc=observe_time, run_id=run_id)
    pre_case = detect_pre_signal_case({**case, "feature_window": window}, as_of_time_utc=observe_time, run_id=run_id)
    memory_value = _decimal(window.get("memory_value_score"))
    pre_signal = _decimal(window.get("pre_signal_score"))
    fake_risk = _decimal(window.get("fake_activation_risk_score"))
    status = str(case.get("memory_status") or "observing")
    expectation_state = "pre_signal_detected" if pre_case.get("status") == "pre_signal_detected" else "watch_only" if pre_case.get("status") == "watch_only" else "normal_observation"
    memory_entity_id = case.get("memory_entity_id") or f"mem-{case.get('symbol')}-{observe_seq}"
    observation = {
        "observation_id": f"memobs-{memory_entity_id}-{observe_time.strftime('%Y%m%d%H%M%S')}-{observe_seq}",
        "memory_entity_id": memory_entity_id,
        "symbol": str(case.get("symbol") or "").zfill(6),
        "observe_seq": _int(case.get("observe_seq")) or observe_seq,
        "observe_time": observe_time,
        "data_as_of": _dt(case.get("data_as_of")) or observe_time,
        "latest_price": _decimal(case.get("latest_price") or case.get("close_price")),
        "return_since_first_selected_pct": _decimal(case.get("return_since_first_selected_pct")),
        "distance_to_first_high_pct": _decimal(case.get("distance_to_first_high_pct")),
        "memory_value_score": memory_value,
        "pre_signal_score": pre_signal,
        "fake_activation_risk_score": fake_risk,
        "expectation_state": expectation_state,
        "deviation_reason_codes": list(window.get("fake_activation_reasons") or []) + list(window.get("source_gap_codes") or []),
        "feature_hash": window.get("feature_hash"),
        "pre_signal_case": pre_case,
        "guardrails": {
            "observation_is_append_only": True,
            "latest_state_is_projection_only": True,
            "post_hoc_events_excluded_from_pre_signal_score": True,
        },
    }
    observation["observation_hash"] = _stable_hash(observation)
    latest_state = {
        "memory_entity_id": memory_entity_id,
        "symbol": observation["symbol"],
        "latest_observe_time": observe_time,
        "memory_status": status,
        "memory_value_score": memory_value,
        "pre_signal_score": pre_signal,
        "activation_quality_score": None,
        "fake_activation_risk_score": fake_risk,
        "latest_state_payload": {
            "expectation_state": expectation_state,
            "pre_signal_case_id": pre_case.get("pre_signal_case_id"),
            "pre_signal_status": pre_case.get("status"),
        },
        "updated_at": observe_time,
    }
    registry_input = {**case, "last_observe_at": observe_time, "memory_status": status}
    registry_input.pop("next_observe_at", None)
    if pre_case.get("status") == "pre_signal_detected":
        registry_input["pre_signal_case_id"] = pre_case.get("pre_signal_case_id")
        registry_input["pre_signal_status"] = "pre_signal_detected"
    registry_update = build_active_case_registry(registry_input, as_of_time_utc=observe_time, run_id=run_id)
    return {
        "observation": observation,
        "latest_state": latest_state,
        "registry_update": registry_update,
        "pre_signal_case": pre_case,
    }


def bulk_observe_active_cases(row: dict[str, Any], *, as_of_time_utc: datetime | None = None, run_id: str | None = None) -> dict[str, Any]:
    observe_time = as_of_time_utc or datetime.now(timezone.utc)
    run_id = run_id or utc_run_id("memory-bulk-observe")
    active_cases = row.get("active_cases") or []
    if not isinstance(active_cases, list):
        active_cases = []
    limit = min(_int(row.get("limit")) or DEFAULT_OBSERVE_BATCH_LIMIT, DEFAULT_OBSERVE_BATCH_LIMIT)
    due_cases: list[dict[str, Any]] = []
    skipped = 0
    for case in active_cases:
        if not isinstance(case, dict):
            skipped += 1
            continue
        next_observe_at = _dt(case.get("next_observe_at"))
        if next_observe_at is not None and next_observe_at > observe_time and not row.get("force"):
            skipped += 1
            continue
        due_cases.append(case)
        if len(due_cases) >= limit:
            break
    outputs = [_build_observation_for_case(case, observe_time, run_id, idx + 1) for idx, case in enumerate(due_cases)]
    observations = [item["observation"] for item in outputs]
    latest_states = [item["latest_state"] for item in outputs]
    registry_updates = [item["registry_update"] for item in outputs]
    pre_signal_cases = [item["pre_signal_case"] for item in outputs if item["pre_signal_case"].get("status") == "pre_signal_detected"]
    result = {
        "schema_version": "candidate_memory_bulk_observation_result_v1",
        "run_id": run_id,
        "model_version": MEMORY_MODEL_VERSION,
        "observe_time": observe_time,
        "input_active_case_count": len(active_cases),
        "due_case_count": len(due_cases),
        "skipped_case_count": skipped,
        "observation_count": len(observations),
        "latest_state_count": len(latest_states),
        "registry_update_count": len(registry_updates),
        "pre_signal_detected_count": len(pre_signal_cases),
        "observations": observations,
        "latest_states": latest_states,
        "registry_updates": registry_updates,
        "pre_signal_cases": pre_signal_cases,
        "guardrails": {
            "bulk_observation_is_append_only": True,
            "latest_state_is_not_training_truth": True,
            "max_batch_size_enforced": DEFAULT_OBSERVE_BATCH_LIMIT,
            "dynamic_frequency_updates_registry": True,
        },
    }
    result["batch_hash"] = _stable_hash(result)
    return _jsonable(result)


def _hit_rate(samples: list[dict[str, Any]]) -> Decimal | None:
    if not samples:
        return None
    hit_count = sum(1 for sample in samples if sample.get("next_limit_up_hit") or sample.get("target_hit"))
    return _pct(hit_count, len(samples))


def _avg_days(samples: list[dict[str, Any]], key: str) -> Decimal | None:
    values = [Decimal(value) for sample in samples if (value := _int(sample.get(key))) is not None]
    return _mean_decimal(values)


def build_matched_control_uplift(row: dict[str, Any], *, as_of_time_utc: datetime | None = None, run_id: str | None = None) -> dict[str, Any]:
    decision_time = as_of_time_utc or datetime.now(timezone.utc)
    run_id = run_id or utc_run_id("memory-matched-control")
    hot_samples = [sample for sample in row.get("hot_entered_samples", []) if isinstance(sample, dict)]
    control_samples = [sample for sample in row.get("matched_control_samples", []) if isinstance(sample, dict)]
    segment_key = str(row.get("segment_key") or "all")
    hot_rate = _hit_rate(hot_samples)
    control_rate = _hit_rate(control_samples)
    uplift = None
    if hot_rate is not None and control_rate is not None:
        uplift = (hot_rate - control_rate).quantize(Decimal("0.000001"))
    hot_time = _avg_days(hot_samples, "time_to_next_limit_up_days")
    control_time = _avg_days(control_samples, "time_to_next_limit_up_days")
    hard_blocks: list[str] = []
    if len(hot_samples) < MIN_MATCHED_SAMPLE_COUNT or len(control_samples) < MIN_MATCHED_SAMPLE_COUNT:
        hard_blocks.append("matched_control_sample_insufficient")
    result = {
        "schema_version": "candidate_memory_matched_control_uplift_v1",
        "run_id": run_id,
        "model_version": MEMORY_MODEL_VERSION,
        "segment_key": segment_key,
        "evaluated_at": decision_time,
        "hot_entered_sample_count": len(hot_samples),
        "matched_control_sample_count": len(control_samples),
        "hot_entered_next_limit_up_rate": hot_rate,
        "matched_control_next_limit_up_rate": control_rate,
        "uplift_rate_pct": uplift,
        "hot_entered_avg_time_to_limit_up_days": hot_time,
        "matched_control_avg_time_to_limit_up_days": control_time,
        "research_state": "valid" if not hard_blocks else "sample_insufficient",
        "hard_block_reasons": hard_blocks,
        "guardrails": {
            "compares_against_matched_controls_not_whole_market": True,
            "controls_should_match_sector_size_turnover_volatility_market_regime": True,
            "uplift_valid_only_when_sample_gate_passed": True,
        },
    }
    result["uplift_hash"] = _stable_hash(result)
    return _jsonable(result)


def build_ttl_calibration(row: dict[str, Any], *, as_of_time_utc: datetime | None = None, run_id: str | None = None) -> dict[str, Any]:
    decision_time = as_of_time_utc or datetime.now(timezone.utc)
    run_id = run_id or utc_run_id("memory-ttl-calibration")
    cutoff_time = _dt(row.get("calibration_cutoff_time")) or decision_time
    outcomes = [sample for sample in row.get("mature_outcomes", []) if isinstance(sample, dict)]
    usable: list[dict[str, Any]] = []
    excluded = 0
    for sample in outcomes:
        labeled_at = _dt(sample.get("labeled_at") or sample.get("created_at") or sample.get("matured_at"))
        if sample.get("label_maturity_status") != "mature":
            excluded += 1
            continue
        if labeled_at is not None and labeled_at > cutoff_time:
            excluded += 1
            continue
        if sample.get("new_independent_cycle"):
            excluded += 1
            continue
        usable.append(sample)
    ttl_too_short = sum(1 for sample in usable if sample.get("outcome_label") in {"delayed_realization", "second_wave_success"} and bool(sample.get("ttl_expired_at_activation") or sample.get("ttl_expired_but_success")))
    ttl_too_long = sum(1 for sample in usable if sample.get("outcome_label") in {"fake_activation_failure", "second_wave_failed"} and (sample.get("ttl_remaining_days_at_activation") is not None and int(sample.get("ttl_remaining_days_at_activation") or 0) > 10))
    success = sum(1 for sample in usable if sample.get("outcome_label") in {"second_wave_success", "delayed_realization"})
    delayed = sum(1 for sample in usable if sample.get("outcome_label") == "delayed_realization")
    current_ttl = _int(row.get("current_ttl_days")) or 30
    suggested_adjustment = 0
    if usable:
        if ttl_too_short / len(usable) >= 0.15:
            suggested_adjustment += 5
        if ttl_too_long / len(usable) >= 0.20:
            suggested_adjustment -= 5
    hard_blocks: list[str] = []
    if len(usable) < MIN_TTL_CALIBRATION_SAMPLE_COUNT:
        hard_blocks.append("ttl_calibration_sample_insufficient")
    activation_state = "ready_for_review" if not hard_blocks else "sample_insufficient"
    result = {
        "schema_version": "candidate_memory_ttl_calibration_report_v1",
        "run_id": run_id,
        "model_version": MEMORY_MODEL_VERSION,
        "calibration_cutoff_time": cutoff_time,
        "segment_key": row.get("segment_key") or "all",
        "mature_sample_count": len(usable),
        "excluded_sample_count": excluded,
        "current_ttl_days": current_ttl,
        "suggested_ttl_days": max(5, current_ttl + suggested_adjustment),
        "ttl_adjustment_days": suggested_adjustment,
        "realized_next_limit_up_rate": _pct(success, len(usable)) if usable else None,
        "delayed_success_rate": _pct(delayed, len(usable)) if usable else None,
        "ttl_too_short_count": ttl_too_short,
        "ttl_too_long_count": ttl_too_long,
        "calibration_state": activation_state,
        "hard_block_reasons": hard_blocks,
        "guardrails": {
            "uses_mature_outcomes_only": True,
            "uses_cutoff_time_to_prevent_future_leakage": True,
            "new_independent_cycle_excluded_from_ttl_success": True,
            "calibration_report_does_not_auto_publish_model_version": True,
        },
    }
    result["calibration_hash"] = _stable_hash(result)
    return _jsonable(result)
