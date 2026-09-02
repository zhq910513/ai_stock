from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException

from ambush_watchlist_model_service.logic import (
    DRAGON_MODEL_VERSION,
    build_deep_analysis,
    build_l2_candidate,
    build_effective_turn_candidate,
    build_pool_transition_audit,
    calculate_valley_watch_candidate,
    calculate_all_window_features,
    calculate_dragon_window_feature,
)
from ambush_watchlist_model_service.phase2 import (
    AMBUSH_PHASE2_VERSION,
    build_phase2_effective_turn_anchor,
    build_phase2_pool_transition_audit,
    build_phase2_valley_turn_pipeline,
    build_phase2_valley_watch_pool,
)
from ambush_watchlist_model_service.phase3 import (
    AMBUSH_FINAL_LOCK_VERSION,
    AMBUSH_PHASE3_VERSION,
    AMBUSH_PHASE4_VERSION,
    build_ambush_lock_candidate_report,
    build_phase3_deep_confirmation,
    build_phase3_pipeline,
    build_phase3_release_gate,
    build_phase4_failure_attribution,
    build_phase4_observation_snapshot,
    build_phase4_outcome_label,
)
from ambush_watchlist_model_service.pattern_library import (
    AMBUSH_PATTERN_LIBRARY_VERSION,
    audit_source_capability,
    build_shape_signature,
    build_three_channel_recall,
    label_historical_valley_sample,
    match_pattern_prototypes,
)
from ambush_watchlist_model_service.schemas import (
    DragonAllWindowsRequest,
    DragonDeepAnalysisRequest,
    DragonL2Request,
    DragonWindowFeatureRequest,
    HistoricalValleySampleLabelRequest,
    EffectiveTurnRequest,
    ModelServiceResponse,
    PatternPrototypeMatchRequest,
    AmbushLockCandidateRequest,
    Phase2EffectiveTurnRequest,
    Phase2PipelineRequest,
    Phase2PoolTransitionRequest,
    Phase2ValleyWatchRequest,
    Phase3DeepConfirmationRequest,
    Phase3PipelineRequest,
    Phase3ReleaseGateRequest,
    Phase4FailureAttributionRequest,
    Phase4ObservationRequest,
    Phase4OutcomeRequest,
    PoolTransitionAuditRequest,
    ShapeSignatureRequest,
    SourceCapabilityAuditRequest,
    ThreeChannelRecallRequest,
    ValleyWatchRequest,
)


router = APIRouter(tags=["ambush-watchlist-model"])


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


def _build_jarvis_payload(result: dict[str, Any]) -> dict[str, Any]:
    return _jsonable(
        {
            "schema_version": "jarvis_model_payload_v1",
            "model_name": "ambush_watchlist",
            "model_version": DRAGON_MODEL_VERSION,
            "symbol": result.get("symbol"),
            "business_objective": {
                "target_return": "0.08",
                "target_window_days": [5, 10, 20, 30],
                "entry_basis": "open_5m_vwap",
                "sellability_rule": "A_SHARE_T_PLUS_1",
            },
            "current_result": {
                "state": result.get("dragon_state"),
                "score": result.get("dragon_priority_score") or result.get("dragon_head_score"),
                "evidence_level": result.get("evidence_level"),
                "best_shape_window": result.get("best_shape_window"),
            },
            "score_breakdown": {
                "liquidity_tradability_score": result.get("liquidity_tradability_score"),
                "capital_probe_score": result.get("capital_probe_score"),
                "decline_maturity_score": result.get("decline_maturity_score"),
                "bottom_stabilization_score": result.get("bottom_stabilization_score"),
                "early_turn_up_score": result.get("early_turn_up_score"),
                "sector_context_score": result.get("sector_context_score"),
                "news_event_score": result.get("news_event_score"),
                "market_context_score": result.get("market_context_score"),
                "breakout_readiness_score": result.get("breakout_readiness_score"),
                "upside_room_score": result.get("upside_room_score"),
                "false_reversal_risk": result.get("false_reversal_risk"),
                "evidence_gap_penalty": result.get("evidence_gap_penalty"),
                "dragon_priority_score": result.get("dragon_priority_score"),
            },
            "positive_factors": result.get("main_positive_factors") or [],
            "negative_factors": result.get("main_negative_factors") or [],
            "source_gap_codes": result.get("source_gap_codes") or [],
            "data_quality": {
                "source_gap_codes": result.get("source_gap_codes") or [],
                "source_gap_count": result.get("source_gap_count"),
                "source_gap_p0_count": result.get("source_gap_p0_count"),
            },
            "next_confirmation_conditions": result.get("next_confirmation_conditions") or [],
            "invalidation_conditions": result.get("invalidation_conditions") or [],
            "evidence_refs": result.get("evidence_refs") or [],
            "guardrails": {
                "jarvis_can_mutate_scores": False,
                "jarvis_can_mutate_state": False,
                "jarvis_can_mutate_labels": False,
                "requires_structured_evidence": True,
            },
        }
    )


def _build_limited_jarvis_payload(scene: str, result: dict[str, Any]) -> dict[str, Any]:
    return _jsonable(
        {
            "schema_version": "jarvis_model_payload_v1",
            "model_name": "ambush_watchlist",
            "model_version": DRAGON_MODEL_VERSION,
            "scene": scene,
            "symbol": result.get("symbol"),
            "current_result": result,
            "guardrails": {
                "jarvis_can_mutate_scores": False,
                "jarvis_can_mutate_state": False,
                "jarvis_can_explain_moneyflow": scene not in {
                    "jarvis.ambush.valley_watch_explain.v1",
                    "jarvis.ambush.effective_turn_candidate_explain.v1",
                },
                "jarvis_can_explain_news": scene not in {
                    "jarvis.ambush.valley_watch_explain.v1",
                    "jarvis.ambush.effective_turn_candidate_explain.v1",
                },
                "jarvis_can_give_buy_advice": False,
            },
        }
    )


@router.get("/health")
@router.get("/healthz")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "ambush-watchlist-model-service"}


@router.get("/readyz")
def ready() -> dict[str, str]:
    return {"status": "ready", "service": "ambush-watchlist-model-service"}


@router.post("/ambush/source-capability-audit")
def ambush_source_capability_audit(payload: SourceCapabilityAuditRequest) -> dict[str, Any]:
    try:
        result = audit_source_capability(
            provider=payload.provider,
            bars=payload.bars,
            weekly_bars=payload.weekly_bars,
            instruments=payload.instruments,
            checked_at=payload.checked_at or datetime.now(timezone.utc),
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"ambush source capability audit failed: {exc}") from exc
    return _jsonable(result)


@router.post("/ambush/shape-signature")
def ambush_shape_signature(payload: ShapeSignatureRequest) -> dict[str, Any]:
    try:
        result = build_shape_signature(
            symbol=payload.symbol,
            bars=payload.bars,
            as_of_trading_day=payload.as_of_trading_day,
            window_days=payload.window_days,
            prefer_adjusted=payload.prefer_adjusted,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"ambush shape signature failed: {exc}") from exc
    return _jsonable(result)


@router.post("/ambush/pattern-prototype-match")
def ambush_pattern_prototype_match(payload: PatternPrototypeMatchRequest) -> dict[str, Any]:
    try:
        signature = payload.current_signature
        if signature is None:
            if payload.symbol is None or payload.as_of_trading_day is None:
                raise ValueError("symbol and as_of_trading_day are required when current_signature is omitted")
            signature = build_shape_signature(
                symbol=payload.symbol,
                bars=payload.bars,
                as_of_trading_day=payload.as_of_trading_day,
                window_days=payload.window_days,
            )
        signature.setdefault("pattern_library_version", AMBUSH_PATTERN_LIBRARY_VERSION)
        result = match_pattern_prototypes(
            current_signature=signature,
            prototypes=payload.prototypes,
            top_k=payload.top_k,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"ambush pattern prototype match failed: {exc}") from exc
    return _jsonable(result)


@router.post("/ambush/historical-valley-sample-label")
def ambush_historical_valley_sample_label(payload: HistoricalValleySampleLabelRequest) -> dict[str, Any]:
    try:
        result = label_historical_valley_sample(
            symbol=payload.symbol,
            bars=payload.bars,
            anchor_day=payload.anchor_day,
            market_bars=payload.market_bars,
            sector_bars=payload.sector_bars,
            pre_window_days=payload.pre_window_days,
            label_window_days=payload.label_window_days,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"ambush historical sample label failed: {exc}") from exc
    return _jsonable(result)


@router.post("/ambush/three-channel-recall", response_model=ModelServiceResponse)
def ambush_three_channel_recall(payload: ThreeChannelRecallRequest) -> ModelServiceResponse:
    try:
        result = build_three_channel_recall(
            instrument=payload.instrument,
            bars=payload.bars,
            as_of_trading_day=payload.as_of_trading_day,
            prototypes=payload.prototypes,
            market_context=payload.market_context,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"ambush three-channel recall failed: {exc}") from exc
    return ModelServiceResponse(
        model_name="ambush_watchlist",
        model_version=DRAGON_MODEL_VERSION,
        structured_output=_jsonable({"recall": result}),
        jarvis_payload=_build_limited_jarvis_payload("jarvis.ambush.three_channel_recall_explain.v1", result),
        contract_gaps=list(result.get("source_gap_codes") or []),
    )


@router.post("/dragon/window-feature")
def dragon_window_feature(payload: DragonWindowFeatureRequest) -> dict[str, Any]:
    try:
        result = calculate_dragon_window_feature(
            symbol=payload.symbol,
            bars=payload.bars,
            window_days=payload.window_days,
            as_of_trading_day=payload.as_of_trading_day,
            as_of_time=payload.as_of_time or datetime.now(timezone.utc),
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"dragon window feature failed: {exc}") from exc
    return _jsonable(result)


@router.post("/dragon/window-features")
def dragon_all_window_features(payload: DragonAllWindowsRequest) -> dict[str, Any]:
    try:
        results = calculate_all_window_features(
            symbol=payload.symbol,
            bars=payload.bars,
            as_of_trading_day=payload.as_of_trading_day,
            as_of_time=payload.as_of_time or datetime.now(timezone.utc),
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"dragon all-window feature failed: {exc}") from exc
    return {"model_version": DRAGON_MODEL_VERSION, "items": _jsonable(results)}


@router.post("/ambush/valley-watch", response_model=ModelServiceResponse)
def ambush_valley_watch(payload: ValleyWatchRequest) -> ModelServiceResponse:
    try:
        result = calculate_valley_watch_candidate(
            instrument=payload.instrument,
            bars=payload.bars,
            as_of_trading_day=payload.as_of_trading_day,
            as_of_time=payload.as_of_time or datetime.now(timezone.utc),
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"ambush valley watch failed: {exc}") from exc
    result = result or {"trade_date": payload.as_of_trading_day, "valley_status": "data_blocked", "source_gap_codes": ["valley_watch_not_detected"]}
    return ModelServiceResponse(
        model_name="ambush_watchlist",
        model_version=DRAGON_MODEL_VERSION,
        structured_output=_jsonable({"valley_watch": result}),
        jarvis_payload=_build_limited_jarvis_payload("jarvis.ambush.valley_watch_explain.v1", result),
        contract_gaps=list(result.get("source_gap_codes") or []),
    )


@router.post("/ambush/effective-turn-candidate", response_model=ModelServiceResponse)
def ambush_effective_turn_candidate(payload: EffectiveTurnRequest) -> ModelServiceResponse:
    try:
        result = build_effective_turn_candidate(
            instrument=payload.instrument,
            valley_watch=payload.valley_watch,
            bars=payload.bars,
            as_of_trading_day=payload.as_of_trading_day,
            as_of_time=payload.as_of_time or datetime.now(timezone.utc),
            snapshot_type=payload.snapshot_type,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"ambush effective turn failed: {exc}") from exc
    result = result or {
        "trade_date": payload.as_of_trading_day,
        "symbol": payload.instrument.get("symbol"),
        "l1_status": "rejected",
        "reject_reason_codes": ["no_effective_turn_anchor"],
        "source_gap_codes": [],
    }
    return ModelServiceResponse(
        model_name="ambush_watchlist",
        model_version=DRAGON_MODEL_VERSION,
        structured_output=_jsonable({"effective_turn_candidate": result}),
        jarvis_payload=_build_limited_jarvis_payload("jarvis.ambush.effective_turn_candidate_explain.v1", result),
        contract_gaps=list(result.get("source_gap_codes") or []),
    )


@router.post("/ambush/pool-transition-audit", response_model=ModelServiceResponse)
def ambush_pool_transition_audit(payload: PoolTransitionAuditRequest) -> ModelServiceResponse:
    try:
        result = build_pool_transition_audit(
            instrument=payload.instrument,
            valley_watch=payload.valley_watch,
            effective_turn_candidate=payload.effective_turn_candidate,
            as_of_time=payload.as_of_time or datetime.now(timezone.utc),
            created_by_job=payload.created_by_job,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"ambush transition audit failed: {exc}") from exc
    result = result or {
        "symbol": payload.effective_turn_candidate.get("symbol"),
        "decision_result": "not_created",
        "reject_reason_codes": payload.effective_turn_candidate.get("reject_reason_codes") or [],
    }
    return ModelServiceResponse(
        model_name="ambush_watchlist",
        model_version=DRAGON_MODEL_VERSION,
        structured_output=_jsonable({"transition_audit": result}),
        jarvis_payload=_build_limited_jarvis_payload("jarvis.ambush.pool_transition_audit.v1", result),
        contract_gaps=[],
    )


@router.post("/dragon/l2-candidate")
def dragon_l2_candidate(payload: DragonL2Request) -> dict[str, Any] | None:
    try:
        result = build_l2_candidate(
            instrument=payload.instrument,
            best_feature=payload.best_feature,
            bars=payload.bars,
            as_of_trading_day=payload.as_of_trading_day,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"dragon L2 candidate failed: {exc}") from exc
    return _jsonable(result)


@router.post("/dragon/deep-analysis", response_model=ModelServiceResponse)
def dragon_deep_analysis(payload: DragonDeepAnalysisRequest) -> ModelServiceResponse:
    try:
        result = build_deep_analysis(
            instrument=payload.instrument,
            best_feature=payload.best_feature,
            l2_candidate=payload.l2_candidate,
            effective_turn_candidate=payload.effective_turn_candidate,
            bars=payload.bars,
            stock_rank=payload.stock_rank,
            theme_ranks=payload.theme_ranks,
            news_context=payload.news_context,
            market_context=payload.market_context,
            as_of_trading_day=payload.as_of_trading_day,
            as_of_time=payload.as_of_time or datetime.now(timezone.utc),
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"dragon deep analysis failed: {exc}") from exc
    return ModelServiceResponse(
        model_name="ambush_watchlist",
        model_version=DRAGON_MODEL_VERSION,
        structured_output=_jsonable({"analysis": result}),
        jarvis_payload=_build_jarvis_payload(result),
        contract_gaps=list(result.get("source_gap_codes") or []),
    )


@router.post("/ambush/phase2/valley-watch-pool", response_model=ModelServiceResponse)
def ambush_phase2_valley_watch_pool(payload: Phase2ValleyWatchRequest) -> ModelServiceResponse:
    try:
        result = build_phase2_valley_watch_pool(
            instrument=payload.instrument,
            bars=payload.bars,
            weekly_bars=payload.weekly_bars,
            recall_result=payload.recall_result,
            pattern_match=payload.pattern_match,
            as_of_trading_day=payload.as_of_trading_day,
            as_of_time=payload.as_of_time or datetime.now(timezone.utc),
            window_days=payload.window_days,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"ambush phase2 valley watch pool failed: {exc}") from exc
    return ModelServiceResponse(
        model_name="ambush_watchlist",
        model_version=AMBUSH_PHASE2_VERSION,
        structured_output=_jsonable({"valley_watch": result}),
        jarvis_payload=_build_limited_jarvis_payload("jarvis.ambush.phase2_valley_watch_pool.v1", result),
        contract_gaps=list(result.get("source_gap_codes") or []),
    )


@router.post("/ambush/phase2/effective-turn-anchor", response_model=ModelServiceResponse)
def ambush_phase2_effective_turn_anchor(payload: Phase2EffectiveTurnRequest) -> ModelServiceResponse:
    try:
        result = build_phase2_effective_turn_anchor(
            instrument=payload.instrument,
            bars=payload.bars,
            weekly_bars=payload.weekly_bars,
            valley_watch=payload.valley_watch,
            recall_result=payload.recall_result,
            pattern_match=payload.pattern_match,
            as_of_trading_day=payload.as_of_trading_day,
            as_of_time=payload.as_of_time or datetime.now(timezone.utc),
            window_days=payload.window_days,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"ambush phase2 effective turn anchor failed: {exc}") from exc
    return ModelServiceResponse(
        model_name="ambush_watchlist",
        model_version=AMBUSH_PHASE2_VERSION,
        structured_output=_jsonable({"effective_turn_anchor": result}),
        jarvis_payload=_build_limited_jarvis_payload("jarvis.ambush.phase2_effective_turn_anchor.v1", result),
        contract_gaps=list(result.get("source_gap_codes") or []),
    )


@router.post("/ambush/phase2/pool-transition", response_model=ModelServiceResponse)
def ambush_phase2_pool_transition(payload: Phase2PoolTransitionRequest) -> ModelServiceResponse:
    try:
        result = build_phase2_pool_transition_audit(
            instrument=payload.instrument,
            valley_watch=payload.valley_watch,
            effective_turn_anchor=payload.effective_turn_anchor,
            as_of_time=payload.as_of_time or datetime.now(timezone.utc),
            created_by_job=payload.created_by_job,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"ambush phase2 pool transition failed: {exc}") from exc
    return ModelServiceResponse(
        model_name="ambush_watchlist",
        model_version=AMBUSH_PHASE2_VERSION,
        structured_output=_jsonable({"transition_audit": result}),
        jarvis_payload=_build_limited_jarvis_payload("jarvis.ambush.phase2_pool_transition.v1", result),
        contract_gaps=[],
    )


@router.post("/ambush/phase2/run", response_model=ModelServiceResponse)
def ambush_phase2_run(payload: Phase2PipelineRequest) -> ModelServiceResponse:
    try:
        result = build_phase2_valley_turn_pipeline(
            instrument=payload.instrument,
            bars=payload.bars,
            weekly_bars=payload.weekly_bars,
            recall_result=payload.recall_result,
            pattern_match=payload.pattern_match,
            as_of_trading_day=payload.as_of_trading_day,
            as_of_time=payload.as_of_time or datetime.now(timezone.utc),
            window_days=payload.window_days,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"ambush phase2 run failed: {exc}") from exc
    return ModelServiceResponse(
        model_name="ambush_watchlist",
        model_version=AMBUSH_PHASE2_VERSION,
        structured_output=_jsonable({"phase2": result}),
        jarvis_payload=_build_limited_jarvis_payload("jarvis.ambush.phase2_pipeline.v1", result),
        contract_gaps=list((result.get("valley_watch") or {}).get("source_gap_codes") or [])
        + list((result.get("effective_turn_anchor") or {}).get("source_gap_codes") or []),
    )


@router.post("/ambush/phase3/deep-confirmation", response_model=ModelServiceResponse)
def ambush_phase3_deep_confirmation(payload: Phase3DeepConfirmationRequest) -> ModelServiceResponse:
    try:
        result = build_phase3_deep_confirmation(
            instrument=payload.instrument,
            valley_watch=payload.valley_watch,
            effective_turn_anchor=payload.effective_turn_anchor,
            bars=payload.bars,
            moneyflow_context=payload.moneyflow_context,
            sector_context=payload.sector_context,
            market_context=payload.market_context,
            tradability_context=payload.tradability_context,
            as_of_trading_day=payload.as_of_trading_day,
            as_of_time=payload.as_of_time or datetime.now(timezone.utc),
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"ambush phase3 deep confirmation failed: {exc}") from exc
    return ModelServiceResponse(
        model_name="ambush_watchlist",
        model_version=AMBUSH_PHASE3_VERSION,
        structured_output=_jsonable({"deep_confirmation": result}),
        jarvis_payload=_build_limited_jarvis_payload("jarvis.ambush.phase3_deep_confirmation.v1", result),
        contract_gaps=list(result.get("source_gap_codes") or []),
    )


@router.post("/ambush/phase3/release-gate", response_model=ModelServiceResponse)
def ambush_phase3_release_gate(payload: Phase3ReleaseGateRequest) -> ModelServiceResponse:
    try:
        result = build_phase3_release_gate(
            instrument=payload.instrument,
            valley_watch=payload.valley_watch,
            effective_turn_anchor=payload.effective_turn_anchor,
            deep_confirmation=payload.deep_confirmation,
            as_of_trading_day=payload.as_of_trading_day,
            as_of_time=payload.as_of_time or datetime.now(timezone.utc),
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"ambush phase3 release gate failed: {exc}") from exc
    return ModelServiceResponse(
        model_name="ambush_watchlist",
        model_version=AMBUSH_PHASE3_VERSION,
        structured_output=_jsonable({"release_gate": result}),
        jarvis_payload=_build_limited_jarvis_payload("jarvis.ambush.phase3_release_gate.v1", result),
        contract_gaps=list(result.get("source_gap_codes") or []),
    )


@router.post("/ambush/phase3/run", response_model=ModelServiceResponse)
def ambush_phase3_run(payload: Phase3PipelineRequest) -> ModelServiceResponse:
    try:
        result = build_phase3_pipeline(
            instrument=payload.instrument,
            valley_watch=payload.valley_watch,
            effective_turn_anchor=payload.effective_turn_anchor,
            bars=payload.bars,
            moneyflow_context=payload.moneyflow_context,
            sector_context=payload.sector_context,
            market_context=payload.market_context,
            tradability_context=payload.tradability_context,
            as_of_trading_day=payload.as_of_trading_day,
            as_of_time=payload.as_of_time or datetime.now(timezone.utc),
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"ambush phase3 run failed: {exc}") from exc
    return ModelServiceResponse(
        model_name="ambush_watchlist",
        model_version=AMBUSH_PHASE3_VERSION,
        structured_output=_jsonable({"phase3": result}),
        jarvis_payload=_build_limited_jarvis_payload("jarvis.ambush.phase3_pipeline.v1", result),
        contract_gaps=list((result.get("deep_confirmation") or {}).get("source_gap_codes") or []),
    )


@router.post("/ambush/phase4/observation", response_model=ModelServiceResponse)
def ambush_phase4_observation(payload: Phase4ObservationRequest) -> ModelServiceResponse:
    try:
        result = build_phase4_observation_snapshot(
            signal_fact=payload.signal_fact,
            buy_point=payload.buy_point,
            bars=payload.bars,
            as_of_trading_day=payload.as_of_trading_day,
            as_of_time=payload.as_of_time or datetime.now(timezone.utc),
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"ambush phase4 observation failed: {exc}") from exc
    return ModelServiceResponse(
        model_name="ambush_watchlist",
        model_version=AMBUSH_PHASE4_VERSION,
        structured_output=_jsonable({"observation": result}),
        jarvis_payload=_build_limited_jarvis_payload("jarvis.ambush.phase4_observation.v1", result),
        contract_gaps=[],
    )


@router.post("/ambush/phase4/outcome", response_model=ModelServiceResponse)
def ambush_phase4_outcome(payload: Phase4OutcomeRequest) -> ModelServiceResponse:
    try:
        result = build_phase4_outcome_label(
            signal_fact=payload.signal_fact,
            buy_point=payload.buy_point,
            bars=payload.bars,
            maturity_days=payload.maturity_days,
            as_of_time=payload.as_of_time or datetime.now(timezone.utc),
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"ambush phase4 outcome failed: {exc}") from exc
    return ModelServiceResponse(
        model_name="ambush_watchlist",
        model_version=AMBUSH_PHASE4_VERSION,
        structured_output=_jsonable({"outcome_label": result}),
        jarvis_payload=_build_limited_jarvis_payload("jarvis.ambush.phase4_outcome.v1", result),
        contract_gaps=[],
    )


@router.post("/ambush/phase4/failure-attribution", response_model=ModelServiceResponse)
def ambush_phase4_failure_attribution(payload: Phase4FailureAttributionRequest) -> ModelServiceResponse:
    try:
        result = build_phase4_failure_attribution(
            signal_fact=payload.signal_fact,
            outcome_label=payload.outcome_label,
            release_gate=payload.release_gate,
            deep_confirmation=payload.deep_confirmation,
            as_of_time=payload.as_of_time or datetime.now(timezone.utc),
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"ambush phase4 failure attribution failed: {exc}") from exc
    return ModelServiceResponse(
        model_name="ambush_watchlist",
        model_version=AMBUSH_PHASE4_VERSION,
        structured_output=_jsonable({"failure_attribution": result}),
        jarvis_payload=_build_limited_jarvis_payload("jarvis.ambush.phase4_failure_attribution.v1", result),
        contract_gaps=[],
    )


@router.post("/ambush/finalization/lock-candidate", response_model=ModelServiceResponse)
def ambush_finalization_lock_candidate(payload: AmbushLockCandidateRequest) -> ModelServiceResponse:
    try:
        result = build_ambush_lock_candidate_report(
            validation_summary=payload.validation_summary,
            as_of_time=payload.as_of_time or datetime.now(timezone.utc),
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"ambush lock candidate report failed: {exc}") from exc
    return ModelServiceResponse(
        model_name="ambush_watchlist",
        model_version=AMBUSH_FINAL_LOCK_VERSION,
        structured_output=_jsonable({"lock_candidate": result}),
        jarvis_payload=_build_limited_jarvis_payload("jarvis.ambush.final_lock_candidate.v1", result),
        contract_gaps=list(result.get("not_validated_here") or []),
    )
