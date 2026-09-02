from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from fastapi import APIRouter, HTTPException

from candidate_memory_model_service.logic import (
    DEFAULT_ENTRY_BASIS,
    DEFAULT_TARGET_RETURN,
    DEFAULT_TARGET_WINDOW_DAYS,
    build_candidate_memory_contract,
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
    utc_run_id,
)
from candidate_memory_model_service.phase2 import (
    build_active_case_registry,
    build_matched_control_uplift,
    build_ttl_calibration,
    bulk_observe_active_cases,
    standardize_event_signal_features,
)
from candidate_memory_model_service.phase3 import (
    build_due_observation_plan,
    build_feature_readiness_audit,
    build_model_schedule_contract,
    build_pre_limitup_signal_analysis,
)

from candidate_memory_model_service.phase4 import (
    build_multi_day_replay_validation,
    build_phase4_acceptance_check,
    build_pre_signal_threshold_calibration,
    build_source_feature_snapshot,
    build_stage_persistence_plan,
)

from candidate_memory_model_service.phase5 import (
    build_memory_closure_pipeline,
    build_memory_failure_attribution,
    build_model_version_shadow_evaluation,
    build_phase5_final_acceptance,
)
from candidate_memory_model_service.schemas import (
    CandidateMemoryProductionRequest,
    CandidateMemoryScoreRequest,
    ModelServiceResponse,
)


router = APIRouter(tags=["candidate-memory-model"])


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


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


def _build_jarvis_payload(contract: dict[str, Any]) -> dict[str, Any]:
    return _jsonable(
        {
            "schema_version": "jarvis_model_payload_v1",
            "model_name": "candidate_memory",
            "model_version": MEMORY_MODEL_VERSION,
            "symbol": contract.get("symbol"),
            "business_objective": {
                "target_return": str(DEFAULT_TARGET_RETURN),
                "target_window_days": DEFAULT_TARGET_WINDOW_DAYS,
                "entry_basis": DEFAULT_ENTRY_BASIS,
                "sellability_rule": "A_SHARE_T_PLUS_1",
                "model_positioning": "historical_hot_candidate_pre_signal_and_up_reason_research",
            },
            "current_result": {
                "state": contract.get("memory_state") or contract.get("release_gate_state") or contract.get("status"),
                "score": contract.get("memory_hit_8pct_score") or contract.get("pre_signal_score") or contract.get("activation_quality_score"),
                "memory_entity_id": contract.get("memory_entity_id"),
                "memory_signal_id": contract.get("memory_signal_id"),
            },
            "score_breakdown": contract.get("score_breakdown") or {},
            "positive_factors": contract.get("main_positive_factors") or contract.get("pre_signal_types") or contract.get("trigger_reason_codes") or [],
            "negative_factors": contract.get("main_negative_factors") or contract.get("hard_block_reasons") or [],
            "hard_block_reasons": contract.get("hard_block_reasons") or contract.get("block_reasons") or [],
            "source_gap_codes": contract.get("source_gap_codes") or contract.get("warning_codes") or [],
            "evidence_refs": contract.get("evidence_refs") or contract.get("ex_ante_event_refs") or [],
            "guardrails": {
                "jarvis_can_mutate_scores": False,
                "jarvis_can_mutate_state": False,
                "jarvis_can_mutate_labels": False,
                "requires_structured_evidence": True,
                "ex_ante_evidence_only_for_scoring": True,
                "new_signal_id_required_per_activation": True,
            },
        }
    )


def _response(output_key: str, output: dict[str, Any]) -> ModelServiceResponse:
    gaps = list(output.get("source_gap_codes") or output.get("warning_codes") or [])
    return ModelServiceResponse(
        model_name="candidate_memory",
        model_version=MEMORY_MODEL_VERSION,
        structured_output=_jsonable({output_key: output}),
        jarvis_payload=_build_jarvis_payload(output),
        contract_gaps=gaps,
    )


def _run_stage(
    payload: CandidateMemoryProductionRequest,
    stage_name: str,
    output_key: str,
    fn: Callable[..., dict[str, Any]],
) -> ModelServiceResponse:
    run_id = payload.run_id or utc_run_id(stage_name)
    as_of_time = payload.as_of_time_utc or datetime.now(timezone.utc)
    try:
        output = fn(payload.row, as_of_time_utc=as_of_time, run_id=run_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"candidate_memory {stage_name} failed: {exc}") from exc
    return _response(output_key, output)


@router.get("/health")
@router.get("/healthz")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "candidate-memory-model-service"}


@router.get("/readyz")
def ready() -> dict[str, str]:
    return {"status": "ready", "service": "candidate-memory-model-service"}


@router.post("/score", response_model=ModelServiceResponse)
def score_candidate_memory(payload: CandidateMemoryScoreRequest) -> ModelServiceResponse:
    # Compatibility endpoint for the older score contract. Production stages below are the formal chain.
    run_id = payload.run_id or utc_run_id("candidate-memory")
    as_of_time = payload.as_of_time_utc or datetime.now(timezone.utc)
    try:
        contract = build_candidate_memory_contract(
            payload.row,
            as_of_time_utc=as_of_time,
            run_id=run_id,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"candidate_memory scoring failed: {exc}") from exc
    return ModelServiceResponse(
        model_name="candidate_memory",
        model_version=MEMORY_MODEL_VERSION,
        structured_output=_jsonable({"contract": contract}),
        jarvis_payload=_build_jarvis_payload(contract),
        contract_gaps=list(contract.get("source_gap_codes") or []),
    )


@router.post("/production/seed/build", response_model=ModelServiceResponse)
def production_seed_build(payload: CandidateMemoryProductionRequest) -> ModelServiceResponse:
    return _run_stage(payload, "memory-seed", "memory_seed", build_memory_seed)


@router.post("/production/entity/build", response_model=ModelServiceResponse)
def production_entity_build(payload: CandidateMemoryProductionRequest) -> ModelServiceResponse:
    return _run_stage(payload, "memory-entity", "memory_entity", build_memory_entity)


@router.post("/production/pre-signal/window", response_model=ModelServiceResponse)
def production_pre_signal_window(payload: CandidateMemoryProductionRequest) -> ModelServiceResponse:
    return _run_stage(payload, "memory-pre-signal-window", "pre_signal_feature_window", build_pre_signal_window)


@router.post("/production/pre-signal/detect", response_model=ModelServiceResponse)
def production_pre_signal_detect(payload: CandidateMemoryProductionRequest) -> ModelServiceResponse:
    return _run_stage(payload, "memory-pre-signal-detect", "pre_signal_case", detect_pre_signal_case)


@router.post("/production/activation/evaluate", response_model=ModelServiceResponse)
def production_activation_evaluate(payload: CandidateMemoryProductionRequest) -> ModelServiceResponse:
    return _run_stage(payload, "memory-activation", "activation_case", evaluate_activation_case)


@router.post("/production/release-gate/evaluate", response_model=ModelServiceResponse)
def production_release_gate(payload: CandidateMemoryProductionRequest) -> ModelServiceResponse:
    return _run_stage(payload, "memory-release-gate", "release_gate", evaluate_release_gate)


@router.post("/production/buy-point/evaluate", response_model=ModelServiceResponse)
def production_buy_point(payload: CandidateMemoryProductionRequest) -> ModelServiceResponse:
    return _run_stage(payload, "memory-buy-point", "buy_point", evaluate_buy_point)


@router.post("/production/outcomes/mature", response_model=ModelServiceResponse)
def production_outcome_mature(payload: CandidateMemoryProductionRequest) -> ModelServiceResponse:
    return _run_stage(payload, "memory-outcome", "outcome_label", mature_outcome)


@router.post("/production/up-reason/build", response_model=ModelServiceResponse)
def production_up_reason(payload: CandidateMemoryProductionRequest) -> ModelServiceResponse:
    return _run_stage(payload, "memory-up-reason", "up_reason_attribution", build_up_reason_attribution)


@router.post("/production/evolution/build", response_model=ModelServiceResponse)
def production_evolution(payload: CandidateMemoryProductionRequest) -> ModelServiceResponse:
    return _run_stage(payload, "memory-evolution", "evolution_sample", build_evolution_sample)


@router.post("/production/events/standardize", response_model=ModelServiceResponse)
def production_events_standardize(payload: CandidateMemoryProductionRequest) -> ModelServiceResponse:
    return _run_stage(payload, "memory-events", "event_signal_feature_batch", standardize_event_signal_features)


@router.post("/production/registry/upsert", response_model=ModelServiceResponse)
def production_registry_upsert(payload: CandidateMemoryProductionRequest) -> ModelServiceResponse:
    return _run_stage(payload, "memory-registry", "active_case_registry", build_active_case_registry)


@router.post("/production/observations/bulk", response_model=ModelServiceResponse)
def production_observations_bulk(payload: CandidateMemoryProductionRequest) -> ModelServiceResponse:
    return _run_stage(payload, "memory-bulk-observe", "bulk_observation_result", bulk_observe_active_cases)


@router.post("/production/matched-control/uplift", response_model=ModelServiceResponse)
def production_matched_control_uplift(payload: CandidateMemoryProductionRequest) -> ModelServiceResponse:
    return _run_stage(payload, "memory-matched-control", "matched_control_uplift", build_matched_control_uplift)


@router.post("/production/ttl-calibration/build", response_model=ModelServiceResponse)
def production_ttl_calibration(payload: CandidateMemoryProductionRequest) -> ModelServiceResponse:
    return _run_stage(payload, "memory-ttl-calibration", "ttl_calibration_report", build_ttl_calibration)


@router.post("/production/features/readiness", response_model=ModelServiceResponse)
def production_feature_readiness(payload: CandidateMemoryProductionRequest) -> ModelServiceResponse:
    return _run_stage(payload, "memory-feature-readiness", "feature_readiness_audit", build_feature_readiness_audit)


@router.post("/production/observations/due-plan", response_model=ModelServiceResponse)
def production_observation_due_plan(payload: CandidateMemoryProductionRequest) -> ModelServiceResponse:
    return _run_stage(payload, "memory-due-plan", "due_observation_plan", build_due_observation_plan)


@router.post("/production/pre-limitup/analyze", response_model=ModelServiceResponse)
def production_pre_limitup_analysis(payload: CandidateMemoryProductionRequest) -> ModelServiceResponse:
    return _run_stage(payload, "memory-pre-limitup-analysis", "pre_limitup_signal_analysis", build_pre_limitup_signal_analysis)


@router.post("/production/schedule/contract", response_model=ModelServiceResponse)
def production_schedule_contract(payload: CandidateMemoryProductionRequest) -> ModelServiceResponse:
    return _run_stage(payload, "memory-schedule-contract", "model_schedule_contract", build_model_schedule_contract)


@router.post("/production/source/features/build", response_model=ModelServiceResponse)
def production_source_features(payload: CandidateMemoryProductionRequest) -> ModelServiceResponse:
    return _run_stage(payload, "memory-source-features", "source_feature_snapshot", build_source_feature_snapshot)


@router.post("/production/persistence/plan", response_model=ModelServiceResponse)
def production_persistence_plan(payload: CandidateMemoryProductionRequest) -> ModelServiceResponse:
    return _run_stage(payload, "memory-persistence-plan", "stage_persistence_plan", build_stage_persistence_plan)


@router.post("/production/pre-signal/threshold-calibration", response_model=ModelServiceResponse)
def production_pre_signal_threshold_calibration(payload: CandidateMemoryProductionRequest) -> ModelServiceResponse:
    return _run_stage(payload, "memory-threshold-calibration", "pre_signal_threshold_calibration", build_pre_signal_threshold_calibration)


@router.post("/production/replay/multi-day", response_model=ModelServiceResponse)
def production_multi_day_replay(payload: CandidateMemoryProductionRequest) -> ModelServiceResponse:
    return _run_stage(payload, "memory-multi-day-replay", "multi_day_replay_validation", build_multi_day_replay_validation)


@router.post("/production/phase4/acceptance", response_model=ModelServiceResponse)
def production_phase4_acceptance(payload: CandidateMemoryProductionRequest) -> ModelServiceResponse:
    return _run_stage(payload, "memory-phase4-acceptance", "phase4_acceptance_check", build_phase4_acceptance_check)

@router.post("/production/closure/run", response_model=ModelServiceResponse)
def production_closure_run(payload: CandidateMemoryProductionRequest) -> ModelServiceResponse:
    return _run_stage(payload, "memory-closure", "closure_pipeline", build_memory_closure_pipeline)


@router.post("/production/failure-attribution/build", response_model=ModelServiceResponse)
def production_failure_attribution(payload: CandidateMemoryProductionRequest) -> ModelServiceResponse:
    return _run_stage(payload, "memory-failure-attribution", "failure_attribution", build_memory_failure_attribution)


@router.post("/production/model-version/shadow-evaluate", response_model=ModelServiceResponse)
def production_model_version_shadow_evaluate(payload: CandidateMemoryProductionRequest) -> ModelServiceResponse:
    return _run_stage(payload, "memory-shadow-evaluation", "model_version_shadow_evaluation", build_model_version_shadow_evaluation)


@router.post("/production/phase5/final-acceptance", response_model=ModelServiceResponse)
def production_phase5_final_acceptance(payload: CandidateMemoryProductionRequest) -> ModelServiceResponse:
    return _run_stage(payload, "memory-phase5-final-acceptance", "phase5_final_acceptance", build_phase5_final_acceptance)

