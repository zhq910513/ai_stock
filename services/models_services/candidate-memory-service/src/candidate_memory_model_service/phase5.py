from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from candidate_memory_model_service.phase2 import build_matched_control_uplift, build_ttl_calibration
from candidate_memory_model_service.phase3 import build_feature_readiness_audit, build_model_schedule_contract, build_pre_limitup_signal_analysis
from candidate_memory_model_service.phase4 import (
    build_multi_day_replay_validation,
    build_pre_signal_threshold_calibration,
    build_source_feature_snapshot,
    build_stage_persistence_plan,
)
from candidate_memory_model_service.research_v1 import (
    MEMORY_MODEL_VERSION,
    build_evolution_sample,
    build_memory_entity,
    build_memory_seed,
    build_pre_signal_window,
    build_up_reason_attribution,
    detect_pre_signal_case,
    evaluate_activation_case,
    evaluate_buy_point,
    evaluate_release_gate,
    mature_outcome,
)

PHASE5_SCHEMA_VERSION = "candidate_memory_phase5_v1"
MIN_FINAL_ACCEPTANCE_SAMPLE_COUNT = 8


def utc_run_id(prefix: str = "candidate-memory-phase5") -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        numeric = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not numeric.is_finite():
        return None
    return numeric


def _score(value: Any, default: Decimal | None = None) -> Decimal | None:
    numeric = _decimal(value)
    if numeric is None:
        return default
    if numeric <= 1:
        numeric *= Decimal("100")
    if numeric < 0 or numeric > 100:
        return default
    return max(Decimal("0"), min(Decimal("100"), numeric)).quantize(Decimal("0.000001"))


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


def _is_true(value: Any) -> bool:
    return value is True or str(value).lower() in {"true", "1", "yes", "pass", "passed"}


def _sample_mature_before(sample: dict[str, Any], cutoff: datetime) -> bool:
    if sample.get("label_maturity_status") != "mature":
        return False
    matured_at = _dt(sample.get("matured_at") or sample.get("labeled_at"))
    return matured_at is not None and matured_at <= cutoff


def build_memory_closure_pipeline(row: dict[str, Any], *, as_of_time_utc: datetime | None = None, run_id: str | None = None) -> dict[str, Any]:
    """Build a deterministic end-to-end candidate-memory research closure.

    This endpoint is intentionally a closure validator, not the production scheduler entry point. Each production
    stage keeps its separate endpoint and transaction boundary; this function proves the same ex-ante artifacts can
    flow from seed to mature outcome and evolution without mixing future evidence back into scoring.
    """
    decision_time = as_of_time_utc or datetime.now(timezone.utc)
    run_id = run_id or utc_run_id("memory-closure")

    source_feature = build_source_feature_snapshot(row, as_of_time_utc=decision_time, run_id=run_id)
    seed = build_memory_seed(row, as_of_time_utc=decision_time, run_id=run_id)
    entity = build_memory_entity({**row, "seed": seed}, as_of_time_utc=decision_time, run_id=run_id)
    entity_id = row.get("memory_entity_id") or entity.get("memory_entity_id")

    # Keep source feature snapshots typed, but pass the original ex-ante evidence into the scoring functions.
    stage_row = {**row, "memory_entity_id": entity_id}
    feature_readiness = build_feature_readiness_audit(
        {
            "stage_code": "activation_evaluate",
            "memory_entity_id": entity_id,
            "symbol": row.get("symbol"),
            "feature_watermarks": row.get("feature_watermarks") or {},
        },
        as_of_time_utc=decision_time,
        run_id=run_id,
    )
    feature_window = build_pre_signal_window(stage_row, as_of_time_utc=decision_time, run_id=run_id)
    pre_case = detect_pre_signal_case({**stage_row, "feature_window": feature_window}, as_of_time_utc=decision_time, run_id=run_id)
    activation = evaluate_activation_case(
        {**stage_row, "feature_window": feature_window, "pre_signal_case": pre_case},
        as_of_time_utc=decision_time,
        run_id=run_id,
    )
    release_gate = evaluate_release_gate({**stage_row, "activation_case": activation}, as_of_time_utc=decision_time, run_id=run_id)
    buy_point = evaluate_buy_point({**stage_row, "release_gate": release_gate}, as_of_time_utc=decision_time, run_id=run_id)

    outcome_input = {
        **stage_row,
        "memory_signal_id": row.get("memory_signal_id") or release_gate.get("memory_signal_id"),
        "activation_case_id": activation.get("activation_case_id"),
        "label_maturity_status": row.get("label_maturity_status"),
        "next_limit_up_hit": row.get("next_limit_up_hit"),
        "target_hit": row.get("target_hit"),
        "tradable_success": row.get("tradable_success"),
        "execution_success": row.get("execution_success"),
        "new_independent_cycle": row.get("new_independent_cycle"),
        "delayed_realization": row.get("delayed_realization"),
        "fake_activation_failure": row.get("fake_activation_failure"),
        "breakout_failed": row.get("breakout_failed"),
        "time_to_next_limit_up_days": row.get("time_to_next_limit_up_days"),
        "pre_signal_lead_days": row.get("pre_signal_lead_days"),
        "mfe_pct": row.get("mfe_pct"),
        "mae_pct": row.get("mae_pct"),
    }
    outcome = mature_outcome(outcome_input, as_of_time_utc=decision_time, run_id=run_id)
    up_reason = build_up_reason_attribution(
        {
            **stage_row,
            "memory_signal_id": outcome.get("memory_signal_id"),
            "pre_signal_reason_codes": activation.get("trigger_reason_codes") or feature_window.get("pre_signal_types"),
            "confirmed_up_reason_codes": row.get("confirmed_up_reason_codes") or [],
            "post_hoc_explanation_codes": row.get("post_hoc_explanation_codes") or [],
            "new_independent_cycle": outcome.get("outcome_label") == "new_independent_cycle",
            "reason_confidence_score": row.get("reason_confidence_score") or activation.get("activation_quality_score"),
        },
        as_of_time_utc=decision_time,
        run_id=run_id,
    )
    evolution = build_evolution_sample({**stage_row, "outcome": outcome}, as_of_time_utc=decision_time, run_id=run_id)
    persistence_plan = build_stage_persistence_plan(
        {
            "stage_outputs": {
                "memory_seed": seed,
                "memory_entity": entity,
                "source_feature_snapshot": source_feature,
                "pre_signal_case": pre_case,
                "activation_case": activation,
                "release_gate": release_gate,
                "buy_point": buy_point,
                "outcome_label": outcome,
                "up_reason_attribution": up_reason,
                "evolution_sample": evolution,
            }
        },
        as_of_time_utc=decision_time,
        run_id=run_id,
    )

    hard_blocks: list[str] = []
    if seed.get("seed_status") == "blocked":
        hard_blocks.append("seed_blocked")
    if feature_readiness.get("readiness_state") == "blocked":
        hard_blocks.extend(feature_readiness.get("hard_block_reasons") or [])
    if pre_case.get("status") not in {"pre_signal_detected", "watch_only"}:
        hard_blocks.append("pre_signal_not_detected")
    if release_gate.get("release_gate_state") != "official_signal_passed":
        hard_blocks.extend([f"release_block:{reason}" for reason in release_gate.get("hard_block_reasons") or ["not_passed"]])
    if buy_point.get("buy_point_state") != "buy_point_confirmed":
        hard_blocks.extend([f"buy_point_block:{reason}" for reason in buy_point.get("block_reasons") or ["not_confirmed"]])
    if outcome.get("label_maturity_status") != "mature":
        hard_blocks.append("outcome_not_mature")
    if evolution.get("evolution_state") != "ready_for_offline_evolution":
        hard_blocks.extend([f"evolution_block:{reason}" for reason in evolution.get("hard_block_reasons") or ["not_ready"]])
    if persistence_plan.get("plan_state") == "blocked":
        hard_blocks.extend([f"persistence_block:{reason}" for reason in persistence_plan.get("hard_block_reasons") or []])

    closure_state = "closed_ready_for_shadow_evaluation" if not hard_blocks else "blocked"
    result = {
        "schema_version": "candidate_memory_closure_pipeline_v1",
        "phase_schema_version": PHASE5_SCHEMA_VERSION,
        "run_id": run_id,
        "model_version": MEMORY_MODEL_VERSION,
        "memory_entity_id": entity_id,
        "memory_signal_id": release_gate.get("memory_signal_id"),
        "symbol": str(row.get("symbol") or entity.get("symbol") or "").zfill(6),
        "evaluated_at": decision_time,
        "closure_state": closure_state,
        "stage_states": {
            "seed_status": seed.get("seed_status"),
            "memory_status": entity.get("memory_status"),
            "feature_readiness_state": feature_readiness.get("readiness_state"),
            "pre_signal_status": pre_case.get("status"),
            "activation_status": activation.get("activation_status"),
            "release_gate_state": release_gate.get("release_gate_state"),
            "buy_point_state": buy_point.get("buy_point_state"),
            "outcome_label": outcome.get("outcome_label"),
            "evolution_state": evolution.get("evolution_state"),
            "persistence_plan_state": persistence_plan.get("plan_state"),
        },
        "outputs": {
            "source_feature_snapshot": source_feature,
            "memory_seed": seed,
            "memory_entity": entity,
            "feature_readiness_audit": feature_readiness,
            "pre_signal_feature_window": feature_window,
            "pre_signal_case": pre_case,
            "activation_case": activation,
            "release_gate": release_gate,
            "buy_point": buy_point,
            "outcome_label": outcome,
            "up_reason_attribution": up_reason,
            "evolution_sample": evolution,
            "stage_persistence_plan": persistence_plan,
        },
        "hard_block_reasons": sorted(set(hard_blocks)),
        "guardrails": {
            "closure_endpoint_is_not_production_scheduler": True,
            "each_stage_has_separate_production_endpoint": True,
            "future_or_post_hoc_events_excluded_from_pre_signal_score": True,
            "mature_outcome_required_for_evolution": True,
            "new_independent_cycle_not_counted_as_success": True,
            "buy_point_and_direction_outcome_are_separated": True,
        },
    }
    result["closure_hash"] = _stable_hash(result)
    return _jsonable(result)


def build_memory_failure_attribution(row: dict[str, Any], *, as_of_time_utc: datetime | None = None, run_id: str | None = None) -> dict[str, Any]:
    decision_time = as_of_time_utc or datetime.now(timezone.utc)
    run_id = run_id or utc_run_id("memory-failure")
    outcome = row.get("outcome") if isinstance(row.get("outcome"), dict) else mature_outcome(row, as_of_time_utc=decision_time, run_id=run_id)
    up_reason = row.get("up_reason_attribution") if isinstance(row.get("up_reason_attribution"), dict) else build_up_reason_attribution(row, as_of_time_utc=decision_time, run_id=run_id)
    hard_blocks: list[str] = []
    if outcome.get("label_maturity_status") != "mature":
        hard_blocks.append("outcome_not_mature")
    outcome_label = outcome.get("outcome_label")
    fake_risk = _score(row.get("fake_activation_risk_score"), Decimal("50")) or Decimal("50")
    ttl_health = _score(row.get("ttl_health_score"), Decimal("50")) or Decimal("50")
    pre_signal_lead_days = _int(outcome.get("pre_signal_lead_days") or row.get("pre_signal_lead_days"))
    direction_success = outcome.get("direction_outcome") == "success"
    execution_outcome = outcome.get("execution_outcome")
    if hard_blocks:
        failure_type = "pending"
        reason_codes = ["outcome_not_mature"]
        model_failure_class = "not_evaluable"
    elif outcome_label == "new_independent_cycle":
        failure_type = "excluded_new_independent_cycle"
        reason_codes = ["new_independent_cycle_not_memory_success"]
        model_failure_class = "excluded_from_memory_success"
    elif direction_success and execution_outcome == "direction_success_execution_missed":
        failure_type = "execution_missed"
        reason_codes = ["direction_success_execution_missed"]
        model_failure_class = "execution_driven"
    elif outcome_label == "fake_activation_failure" or fake_risk >= Decimal("65"):
        failure_type = "fake_activation"
        reason_codes = ["fake_activation_risk_underestimated"]
        model_failure_class = "model_uncertain_single_case"
    elif ttl_health < Decimal("25"):
        failure_type = "ttl_decay_failure"
        reason_codes = ["ttl_health_low_at_activation"]
        model_failure_class = "ttl_rule_candidate"
    elif pre_signal_lead_days is not None and pre_signal_lead_days <= 0:
        failure_type = "activation_too_late"
        reason_codes = ["pre_signal_not_early_enough"]
        model_failure_class = "activation_timing_candidate"
    elif outcome_label in {"second_wave_failed", "pending_or_blocked"}:
        failure_type = "second_wave_failed"
        reason_codes = ["activation_did_not_convert"]
        model_failure_class = "model_uncertain_single_case"
    else:
        failure_type = "not_failure"
        reason_codes = ["success_or_research_only"]
        model_failure_class = "not_failure"
    result = {
        "schema_version": "candidate_memory_failure_attribution_v1",
        "phase_schema_version": PHASE5_SCHEMA_VERSION,
        "run_id": run_id,
        "model_version": MEMORY_MODEL_VERSION,
        "memory_signal_id": outcome.get("memory_signal_id"),
        "memory_entity_id": outcome.get("memory_entity_id"),
        "symbol": outcome.get("symbol"),
        "attributed_at": decision_time,
        "failure_type": failure_type,
        "failure_reason_codes": sorted(set(reason_codes)),
        "model_failure_class": model_failure_class,
        "primary_up_reason": up_reason.get("primary_up_reason"),
        "outcome_label": outcome_label,
        "direction_outcome": outcome.get("direction_outcome"),
        "execution_outcome": execution_outcome,
        "hard_block_reasons": sorted(set(hard_blocks)),
        "guardrails": {
            "single_case_never_becomes_systematic_failure": True,
            "new_independent_cycle_excluded_from_memory_success": True,
            "direction_success_separated_from_execution_failure": True,
        },
    }
    result["attribution_hash"] = _stable_hash(result)
    return _jsonable(result)


def build_model_version_shadow_evaluation(row: dict[str, Any], *, as_of_time_utc: datetime | None = None, run_id: str | None = None) -> dict[str, Any]:
    decision_time = as_of_time_utc or datetime.now(timezone.utc)
    run_id = run_id or utc_run_id("memory-shadow-eval")
    cutoff = _dt(row.get("evaluation_cutoff_time") or row.get("calibration_cutoff_time")) or decision_time
    samples = list(row.get("mature_samples") or row.get("samples") or [])
    candidate_version = str(row.get("candidate_model_version") or f"{MEMORY_MODEL_VERSION}_candidate")
    baseline_version = str(row.get("baseline_model_version") or MEMORY_MODEL_VERSION)
    eligible: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for sample in samples:
        if not isinstance(sample, dict):
            continue
        reason = None
        if not _sample_mature_before(sample, cutoff):
            reason = "not_mature_before_cutoff"
        elif sample.get("outcome_label") == "new_independent_cycle" or sample.get("new_independent_cycle"):
            reason = "new_independent_cycle_excluded"
        elif sample.get("pre_signal_visible_before_activation") is False or sample.get("post_hoc_only_reason"):
            reason = "no_ex_ante_pre_signal"
        if reason:
            excluded.append({"sample_id": sample.get("sample_id"), "reason": reason})
        else:
            eligible.append(sample)
    def hit_rate(items: list[dict[str, Any]], score_key: str, threshold: Decimal) -> tuple[int, int, Decimal | None]:
        selected = [item for item in items if (_score(item.get(score_key), Decimal("0")) or Decimal("0")) >= threshold]
        if not selected:
            return 0, 0, None
        wins = [item for item in selected if item.get("outcome_label") in {"second_wave_success", "delayed_realization"} or item.get("next_limit_up_hit") is True]
        return len(selected), len(wins), (Decimal(len(wins)) / Decimal(len(selected)) * Decimal("100")).quantize(Decimal("0.000001"))
    candidate_threshold = _score(row.get("candidate_threshold"), Decimal("68")) or Decimal("68")
    baseline_threshold = _score(row.get("baseline_threshold"), Decimal("68")) or Decimal("68")
    candidate_selected, candidate_hits, candidate_hit_rate = hit_rate(eligible, "candidate_activation_score", candidate_threshold)
    baseline_selected, baseline_hits, baseline_hit_rate = hit_rate(eligible, "baseline_activation_score", baseline_threshold)
    uplift_report = build_matched_control_uplift(row, as_of_time_utc=decision_time, run_id=run_id) if (row.get("entered_group") or row.get("control_group")) else None
    candidate_beats_baseline = (
        candidate_hit_rate is not None
        and baseline_hit_rate is not None
        and candidate_hit_rate >= baseline_hit_rate
        and candidate_selected > 0
    )
    enough_samples = len(eligible) >= MIN_FINAL_ACCEPTANCE_SAMPLE_COUNT
    state = "ready_for_manual_promotion_review" if enough_samples and candidate_beats_baseline else "blocked_or_needs_more_samples"
    blocks: list[str] = []
    if not enough_samples:
        blocks.append("insufficient_mature_ex_ante_samples")
    if not candidate_beats_baseline:
        blocks.append("candidate_version_not_better_than_baseline")
    result = {
        "schema_version": "candidate_memory_model_version_shadow_evaluation_v1",
        "phase_schema_version": PHASE5_SCHEMA_VERSION,
        "run_id": run_id,
        "baseline_model_version": baseline_version,
        "candidate_model_version": candidate_version,
        "evaluated_at": decision_time,
        "evaluation_cutoff_time": cutoff,
        "eligible_sample_count": len(eligible),
        "excluded_sample_count": len(excluded),
        "candidate_selected_count": candidate_selected,
        "candidate_hit_count": candidate_hits,
        "candidate_hit_rate_pct": candidate_hit_rate,
        "baseline_selected_count": baseline_selected,
        "baseline_hit_count": baseline_hits,
        "baseline_hit_rate_pct": baseline_hit_rate,
        "evaluation_state": state,
        "hard_block_reasons": sorted(set(blocks)),
        "excluded_samples": excluded[:50],
        "matched_control_uplift": uplift_report,
        "guardrails": {
            "uses_mature_ex_ante_samples_only": True,
            "new_independent_cycle_excluded": True,
            "shadow_evaluation_required_before_version_promotion": True,
            "single_case_does_not_promote_model_version": True,
        },
    }
    result["evaluation_hash"] = _stable_hash(result)
    return _jsonable(result)


def build_phase5_final_acceptance(row: dict[str, Any], *, as_of_time_utc: datetime | None = None, run_id: str | None = None) -> dict[str, Any]:
    decision_time = as_of_time_utc or datetime.now(timezone.utc)
    run_id = run_id or utc_run_id("memory-phase5-acceptance")
    checks = dict(row.get("checks") or {})
    required_checks = {
        "stage_endpoints_split",
        "postgres_stage_repository_contract",
        "source_typed_feature_contract",
        "due_case_registry_plan",
        "feature_watermark_hard_block",
        "ex_ante_message_guardrail",
        "pre_signal_chain",
        "release_gate_guardrails",
        "buy_point_direction_execution_split",
        "mature_outcome_only_evolution",
        "new_independent_cycle_exclusion",
        "failure_attribution",
        "ttl_calibration",
        "threshold_calibration",
        "matched_control_uplift",
        "multi_day_replay",
        "model_version_shadow_evaluation",
        "schedule_contract_ready_for_scheduler_v2",
    }
    missing = sorted(check for check in required_checks if not _is_true(checks.get(check)))
    closure = row.get("closure_pipeline") if isinstance(row.get("closure_pipeline"), dict) else None
    shadow = row.get("shadow_evaluation") if isinstance(row.get("shadow_evaluation"), dict) else None
    if closure and closure.get("closure_state") != "closed_ready_for_shadow_evaluation":
        missing.append("closure_pipeline_not_ready")
    if shadow and shadow.get("evaluation_state") != "ready_for_manual_promotion_review":
        missing.append("shadow_evaluation_not_ready")
    acceptance_state = "pass" if not missing else "blocked"
    result = {
        "schema_version": "candidate_memory_phase5_final_acceptance_v1",
        "phase_schema_version": PHASE5_SCHEMA_VERSION,
        "run_id": run_id,
        "model_version": MEMORY_MODEL_VERSION,
        "evaluated_at": decision_time,
        "acceptance_state": acceptance_state,
        "missing_or_failed_checks": sorted(set(missing)),
        "passed_checks": sorted(check for check in required_checks if _is_true(checks.get(check))),
        "acceptance_boundary": {
            "backend_model_closure_can_be_frozen_as_rc": acceptance_state == "pass",
            "requires_real_postgres_provider_scheduler_replay_for_online_final": True,
            "scheduler_v2_should_start_after_three_model_contracts": True,
        },
        "guardrails": {
            "code_rc_is_not_online_final_without_real_environment": True,
            "model_truth_stays_in_decision_memory_schema": True,
            "scheduler_governance_cannot_store_memory_scores_or_labels": True,
        },
    }
    result["acceptance_hash"] = _stable_hash(result)
    return _jsonable(result)
