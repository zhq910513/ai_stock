from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException

from hot_candidates_model_service.logic import (
    DEFAULT_ENTRY_BASIS,
    DEFAULT_TARGET_RETURN,
    DEFAULT_TARGET_WINDOW_DAYS,
    HOT_MODEL_VERSION,
    build_candidate_source_analysis,
    build_hot_candidate_distortion_report,
    build_hot_candidate_v1_contract,
    utc_run_id,
)
from hot_candidates_model_service.pipeline import run_hot_full_pipeline
from hot_candidates_model_service.production import (
    build_hot_case_build_result,
    build_hot_score_compute_result,
    build_hot_release_gate_result,
    build_hot_buy_point_result,
    build_hot_outcome_mature_result,
    build_hot_evolution_build_result,
    build_hot_failure_analysis_result,
)
from hot_candidates_model_service.phase6 import (
    build_bulk_observations,
    build_hot_cycle_day_feature,
    build_hot_execution_feature_snapshot,
    build_versioned_teacher_calibration,
)
from hot_candidates_model_service.calibration import (
    build_hot_research_sample_pool_record,
    build_hot_teacher_calibration_report,
)
from hot_candidates_model_service.research import (
    HOT_MODEL_REFINED_VERSION,
    build_hot_evolution_sample,
    build_hot_observation_snapshot,
    build_hot_research_contract,
)
from hot_candidates_model_service.schemas import (
    HotCandidateDistortionReportRequest,
    HotCandidateEvolutionSampleRequest,
    HotCandidateObservationRequest,
    HotCandidatePipelineRunRequest,
    HotCandidateScoreRequest,
    HotBulkObservationRequest,
    HotCalibrationVersionRequest,
    HotFeatureBuildRequest,
    HotProductionPayloadRequest,
    HotResearchSamplePoolRequest,
    HotTeacherCalibrationReportRequest,
    ModelServiceResponse,
)


router = APIRouter(tags=["hot-candidates-model"])


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


def _build_jarvis_payload(analysis: dict[str, Any], contract: dict[str, Any] | None) -> dict[str, Any]:
    hot_contract = contract or {}
    item = hot_contract.get("candidate_item") or {}
    feature = hot_contract.get("feature_matrix") or {}
    current = hot_contract.get("analysis") or {}
    return _jsonable(
        {
            "schema_version": "jarvis_model_payload_v1",
            "model_name": "hot_candidates",
            "model_version": HOT_MODEL_VERSION,
            "symbol": item.get("symbol") or analysis.get("symbol_snapshot"),
            "name": item.get("name") or analysis.get("name_snapshot"),
            "business_objective": {
                "target_return": str(DEFAULT_TARGET_RETURN),
                "target_window_days": DEFAULT_TARGET_WINDOW_DAYS,
                "entry_basis": DEFAULT_ENTRY_BASIS,
                "sellability_rule": "A_SHARE_T_PLUS_1",
            },
            "current_result": {
                "state": current.get("state") or analysis.get("state"),
                "score": current.get("hot_score"),
                "teacher_probability": item.get("p_limit_up"),
                "evidence_completeness": feature.get("evidence_completeness"),
            },
            "score_breakdown": {
                "teacher_prior_score": feature.get("teacher_prior_score"),
                "local_confirmation_score": feature.get("local_confirmation_score"),
                "tradability_adjustment_score": feature.get("tradability_adjustment_score"),
                "upside_space_score": feature.get("upside_space_score"),
                "overheating_failure_risk": feature.get("overheating_failure_risk"),
            },
            "positive_factors": current.get("main_positive_factors") or analysis.get("main_positive_factors") or [],
            "negative_factors": current.get("main_negative_factors") or analysis.get("main_negative_factors") or [],
            "hard_block_reasons": current.get("hard_block_reasons") or analysis.get("hard_block_reasons") or [],
            "source_gap_codes": current.get("source_gap_codes") or feature.get("feature_gap_codes") or [],
            "evidence_refs": current.get("evidence_refs") or analysis.get("evidence_refs") or [],
            "guardrails": {
                "jarvis_can_mutate_scores": False,
                "jarvis_can_mutate_state": False,
                "jarvis_can_mutate_labels": False,
                "requires_structured_evidence": True,
            },
        }
    )


def _build_distortion_jarvis_payload(report: dict[str, Any]) -> dict[str, Any]:
    return _jsonable(
        {
            "schema_version": "jarvis_model_payload_v1",
            "model_name": "hot_candidates",
            "model_version": HOT_MODEL_VERSION,
            "business_objective": {
                "target_return": str(DEFAULT_TARGET_RETURN),
                "target_window_days": DEFAULT_TARGET_WINDOW_DAYS,
                "entry_basis": DEFAULT_ENTRY_BASIS,
                "sellability_rule": "A_SHARE_T_PLUS_1",
            },
            "current_result": {
                "status": report.get("status"),
                "learning_gate": report.get("learning_gate"),
                "sample_counts": report.get("sample_counts"),
            },
            "score_breakdown": report.get("probability_bucket_performance") or {},
            "source_gap_codes": report.get("warning_codes") or [],
            "evidence_refs": [],
            "guardrails": {
                "jarvis_can_mutate_scores": False,
                "jarvis_can_mutate_state": False,
                "jarvis_can_mutate_labels": False,
                "requires_structured_evidence": True,
            },
        }
    )


@router.get("/health")
@router.get("/healthz")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "hot-candidates-model-service"}


@router.get("/readyz")
def ready() -> dict[str, str]:
    return {"status": "ready", "service": "hot-candidates-model-service"}


@router.post("/score", response_model=ModelServiceResponse)
def score_hot_candidate(payload: HotCandidateScoreRequest) -> ModelServiceResponse:
    run_id = payload.run_id or utc_run_id("hot-candidates")
    as_of_time = payload.as_of_time_utc or datetime.now(timezone.utc)
    try:
        analysis = build_candidate_source_analysis(
            payload.row,
            candidate_source="hot_candidates",
            target_return=DEFAULT_TARGET_RETURN,
            target_window_days=DEFAULT_TARGET_WINDOW_DAYS,
            entry_basis=DEFAULT_ENTRY_BASIS,
            run_id=run_id,
        )
        contract = build_hot_candidate_v1_contract(analysis, as_of_time_utc=as_of_time)
        research_contract = build_hot_research_contract(
            payload.row,
            legacy_analysis=analysis,
            legacy_contract=contract,
            as_of_time_utc=as_of_time,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"hot_candidates scoring failed: {exc}") from exc
    contract_gaps: list[str] = []
    if contract is None:
        contract_gaps.append("hot_candidate_v1_contract_not_generated")
    return ModelServiceResponse(
        model_name="hot_candidates",
        model_version=HOT_MODEL_VERSION,
        structured_output=_jsonable({"analysis": analysis, "contract": contract, "research_contract": research_contract}),
        jarvis_payload=_build_jarvis_payload(analysis, contract),
        contract_gaps=contract_gaps,
    )


@router.post("/distortion-report", response_model=ModelServiceResponse)
def hot_candidate_distortion_report(payload: HotCandidateDistortionReportRequest) -> ModelServiceResponse:
    try:
        report = build_hot_candidate_distortion_report(
            payload.analyses,
            payload.labels,
            trade_date=payload.trade_date,
            min_learning_samples=payload.min_learning_samples,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"hot_candidates distortion report failed: {exc}") from exc
    return ModelServiceResponse(
        model_name="hot_candidates",
        model_version=HOT_MODEL_VERSION,
        structured_output=_jsonable({"report": report}),
        jarvis_payload=_build_distortion_jarvis_payload(report),
        contract_gaps=list(report.get("warning_codes") or []),
    )


@router.post("/observe", response_model=ModelServiceResponse)
def observe_hot_candidate(payload: HotCandidateObservationRequest) -> ModelServiceResponse:
    as_of_time = payload.as_of_time_utc or datetime.now(timezone.utc)
    try:
        observation = build_hot_observation_snapshot(payload.payload, as_of_time_utc=as_of_time)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"hot_candidates observation failed: {exc}") from exc
    return ModelServiceResponse(
        model_name="hot_candidates",
        model_version=HOT_MODEL_REFINED_VERSION,
        structured_output=_jsonable({"observation": observation}),
        jarvis_payload={},
        contract_gaps=list(observation.get("deviation_reason_codes") or []),
    )


@router.post("/evolution-sample", response_model=ModelServiceResponse)
def hot_candidate_evolution_sample(payload: HotCandidateEvolutionSampleRequest) -> ModelServiceResponse:
    as_of_time = payload.as_of_time_utc or datetime.now(timezone.utc)
    try:
        sample = build_hot_evolution_sample(payload.payload, as_of_time_utc=as_of_time)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"hot_candidates evolution sample failed: {exc}") from exc
    return ModelServiceResponse(
        model_name="hot_candidates",
        model_version=HOT_MODEL_REFINED_VERSION,
        structured_output=_jsonable({"evolution_sample": sample}),
        jarvis_payload={},
        contract_gaps=[],
    )


@router.post("/pipeline/run", response_model=ModelServiceResponse)
def hot_candidate_pipeline_run(payload: HotCandidatePipelineRunRequest) -> ModelServiceResponse:
    as_of_time = payload.as_of_time_utc or datetime.now(timezone.utc)
    request_payload = dict(payload.payload or {})
    if payload.run_id:
        request_payload["run_id"] = payload.run_id
    try:
        pipeline = run_hot_full_pipeline(request_payload, as_of_time_utc=as_of_time)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"hot_candidates full pipeline failed: {exc}") from exc
    gaps: list[str] = []
    source_audit = (((pipeline.get("research_contract") or {}).get("source_visibility_audit") or {}))
    gaps.extend(source_audit.get("hard_block_codes") or [])
    gaps.extend(source_audit.get("warning_codes") or [])
    return ModelServiceResponse(
        model_name="hot_candidates",
        model_version=HOT_MODEL_REFINED_VERSION,
        structured_output=_jsonable({"pipeline": pipeline}),
        jarvis_payload={},
        contract_gaps=sorted(set(gaps)),
    )


@router.post("/research-pool/classify", response_model=ModelServiceResponse)
def hot_candidate_research_pool_classify(payload: HotResearchSamplePoolRequest) -> ModelServiceResponse:
    as_of_time = payload.as_of_time_utc or datetime.now(timezone.utc)
    try:
        record = build_hot_research_sample_pool_record(payload.payload, generated_at=as_of_time)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"hot_candidates research pool classification failed: {exc}") from exc
    return ModelServiceResponse(
        model_name="hot_candidates",
        model_version=HOT_MODEL_REFINED_VERSION,
        structured_output=_jsonable({"research_pool_record": record}),
        jarvis_payload={},
        contract_gaps=[] if record.get("should_track") else list(record.get("tracking_reason_codes") or []),
    )


@router.post("/teacher-calibration/report", response_model=ModelServiceResponse)
def hot_teacher_calibration_report(payload: HotTeacherCalibrationReportRequest) -> ModelServiceResponse:
    as_of_time = payload.as_of_time_utc or datetime.now(timezone.utc)
    try:
        report = build_hot_teacher_calibration_report(
            payload.samples,
            calibration_version=payload.calibration_version,
            min_bucket_samples=payload.min_bucket_samples,
            min_total_samples=payload.min_total_samples,
            generated_at=as_of_time,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"hot_candidates teacher calibration report failed: {exc}") from exc
    return ModelServiceResponse(
        model_name="hot_candidates",
        model_version=HOT_MODEL_REFINED_VERSION,
        structured_output=_jsonable({"teacher_calibration_report": report}),
        jarvis_payload={},
        contract_gaps=list(report.get("warning_codes") or []),
    )


@router.post("/production/observations/bulk", response_model=ModelServiceResponse)
def hot_bulk_observations(payload: HotBulkObservationRequest) -> ModelServiceResponse:
    as_of_time = payload.as_of_time_utc or datetime.now(timezone.utc)
    try:
        observations = build_bulk_observations(payload.active_cases, as_of_time_utc=as_of_time)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"hot_candidates bulk observation failed: {exc}") from exc
    return ModelServiceResponse(
        model_name="hot_candidates",
        model_version=HOT_MODEL_REFINED_VERSION,
        structured_output=_jsonable({"observations": observations, "count": len(observations)}),
        jarvis_payload={},
        contract_gaps=[],
    )


@router.post("/production/features/build", response_model=ModelServiceResponse)
def hot_build_features(payload: HotFeatureBuildRequest) -> ModelServiceResponse:
    as_of_time = payload.as_of_time_utc or datetime.now(timezone.utc)
    features: list[dict[str, Any]] = []
    try:
        for row in payload.rows:
            features.append(build_hot_cycle_day_feature(row, calculated_at=as_of_time))
            features.append(build_hot_execution_feature_snapshot(row, calc_stage=payload.calc_stage, calculated_at=as_of_time))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"hot_candidates feature build failed: {exc}") from exc
    return ModelServiceResponse(
        model_name="hot_candidates",
        model_version=HOT_MODEL_REFINED_VERSION,
        structured_output=_jsonable({"features": features, "count": len(features)}),
        jarvis_payload={},
        contract_gaps=[],
    )


@router.post("/production/teacher-calibration/version", response_model=ModelServiceResponse)
def hot_teacher_calibration_version(payload: HotCalibrationVersionRequest) -> ModelServiceResponse:
    cutoff = payload.calibration_cutoff_time or datetime.now(timezone.utc)
    try:
        versioned = build_versioned_teacher_calibration(
            payload.samples,
            calibration_version=payload.calibration_version,
            training_window_start=payload.training_window_start,
            training_window_end=payload.training_window_end,
            cutoff_time=cutoff,
            min_bucket_samples=payload.min_bucket_samples,
            min_total_samples=payload.min_total_samples,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"hot_candidates calibration version failed: {exc}") from exc
    return ModelServiceResponse(
        model_name="hot_candidates",
        model_version=HOT_MODEL_REFINED_VERSION,
        structured_output=_jsonable({"calibration_version": versioned}),
        jarvis_payload={},
        contract_gaps=[] if versioned.get("can_activate") else [versioned.get("activation_status") or "sample_insufficient"],
    )


@router.post("/production/cases/build", response_model=ModelServiceResponse)
def hot_production_cases_build(payload: HotProductionPayloadRequest) -> ModelServiceResponse:
    as_of_time = payload.as_of_time_utc or datetime.now(timezone.utc)
    request_payload = dict(payload.payload or {})
    if payload.run_id:
        request_payload["run_id"] = payload.run_id
    try:
        result = build_hot_case_build_result(request_payload, as_of_time_utc=as_of_time)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"hot production cases build failed: {exc}") from exc
    audit = result.get("source_visibility_audit") or {}
    return ModelServiceResponse(model_name="hot_candidates", model_version=HOT_MODEL_REFINED_VERSION, structured_output=_jsonable({"case_build": result}), jarvis_payload={}, contract_gaps=sorted(set((audit.get("hard_block_codes") or []) + (audit.get("warning_codes") or []))))


@router.post("/production/scores/compute", response_model=ModelServiceResponse)
def hot_production_scores_compute(payload: HotProductionPayloadRequest) -> ModelServiceResponse:
    as_of_time = payload.as_of_time_utc or datetime.now(timezone.utc)
    request_payload = dict(payload.payload or {})
    if payload.run_id:
        request_payload["run_id"] = payload.run_id
    try:
        result = build_hot_score_compute_result(request_payload, as_of_time_utc=as_of_time)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"hot production scores compute failed: {exc}") from exc
    audit = result.get("source_visibility_audit") or {}
    return ModelServiceResponse(model_name="hot_candidates", model_version=HOT_MODEL_REFINED_VERSION, structured_output=_jsonable({"score_compute": result}), jarvis_payload={}, contract_gaps=sorted(set((audit.get("hard_block_codes") or []) + (audit.get("warning_codes") or []))))


@router.post("/production/release-gate/evaluate", response_model=ModelServiceResponse)
def hot_production_release_gate_evaluate(payload: HotProductionPayloadRequest) -> ModelServiceResponse:
    as_of_time = payload.as_of_time_utc or datetime.now(timezone.utc)
    request_payload = dict(payload.payload or {})
    if payload.run_id:
        request_payload["run_id"] = payload.run_id
    try:
        result = build_hot_release_gate_result(request_payload, as_of_time_utc=as_of_time)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"hot production release gate failed: {exc}") from exc
    audit = result.get("source_visibility_audit") or {}
    return ModelServiceResponse(model_name="hot_candidates", model_version=HOT_MODEL_REFINED_VERSION, structured_output=_jsonable({"release_gate_result": result}), jarvis_payload={}, contract_gaps=sorted(set((audit.get("hard_block_codes") or []) + (audit.get("warning_codes") or []))))


@router.post("/production/buy-point/evaluate", response_model=ModelServiceResponse)
def hot_production_buy_point_evaluate(payload: HotProductionPayloadRequest) -> ModelServiceResponse:
    as_of_time = payload.as_of_time_utc or datetime.now(timezone.utc)
    request_payload = dict(payload.payload or {})
    if payload.run_id:
        request_payload["run_id"] = payload.run_id
    try:
        result = build_hot_buy_point_result(request_payload, as_of_time_utc=as_of_time)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"hot production buy point failed: {exc}") from exc
    audit = result.get("source_visibility_audit") or {}
    return ModelServiceResponse(model_name="hot_candidates", model_version=HOT_MODEL_REFINED_VERSION, structured_output=_jsonable({"buy_point_result": result}), jarvis_payload={}, contract_gaps=sorted(set((audit.get("hard_block_codes") or []) + (audit.get("warning_codes") or []))))


@router.post("/production/outcomes/mature", response_model=ModelServiceResponse)
def hot_production_outcomes_mature(payload: HotProductionPayloadRequest) -> ModelServiceResponse:
    as_of_time = payload.as_of_time_utc or datetime.now(timezone.utc)
    try:
        result = build_hot_outcome_mature_result(payload.payload or {}, as_of_time_utc=as_of_time)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"hot production outcome mature failed: {exc}") from exc
    return ModelServiceResponse(model_name="hot_candidates", model_version=HOT_MODEL_REFINED_VERSION, structured_output=_jsonable({"outcome_mature_result": result}), jarvis_payload={}, contract_gaps=[] if result.get("can_build_evolution_sample") else ["outcome_not_mature_for_evolution"])


@router.post("/production/evolution/build", response_model=ModelServiceResponse)
def hot_production_evolution_build(payload: HotProductionPayloadRequest) -> ModelServiceResponse:
    as_of_time = payload.as_of_time_utc or datetime.now(timezone.utc)
    try:
        result = build_hot_evolution_build_result(payload.payload or {}, as_of_time_utc=as_of_time)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"hot production evolution build failed: {exc}") from exc
    return ModelServiceResponse(model_name="hot_candidates", model_version=HOT_MODEL_REFINED_VERSION, structured_output=_jsonable({"evolution_build_result": result}), jarvis_payload={}, contract_gaps=[] if result.get("build_status") == "built" else [result.get("build_status") or "evolution_blocked"])


@router.post("/production/failure-analysis/build", response_model=ModelServiceResponse)
def hot_production_failure_analysis(payload: HotProductionPayloadRequest) -> ModelServiceResponse:
    as_of_time = payload.as_of_time_utc or datetime.now(timezone.utc)
    try:
        result = build_hot_failure_analysis_result(payload.payload or {}, as_of_time_utc=as_of_time)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"hot production failure analysis failed: {exc}") from exc
    return ModelServiceResponse(model_name="hot_candidates", model_version=HOT_MODEL_REFINED_VERSION, structured_output=_jsonable({"failure_analysis_result": result}), jarvis_payload={}, contract_gaps=[])
