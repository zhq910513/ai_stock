from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from scheduler_service.hot_plan import HOT_CANDIDATES_TASKS, hot_plan, validate_hot_plan_contract
from scheduler_service.three_model_plan import THREE_MODEL_TASKS, three_model_plan, validate_three_model_plan_contract
from scheduler_service.orchestrator import HotWorkflowOrchestrator
from scheduler_service.live_dispatch import HotLiveDispatcher
from scheduler_service.three_model_dispatch import (
    OFFICIAL_RELEASE_GATE_TASKS,
    OwnerEndpointRegistry,
    ThreeModelLiveDispatcher,
    build_live_dispatch_sample_payload,
)
from scheduler_service.three_model_materializer import materialize_three_model_day
from scheduler_service.docs_sync import validate_scheduler_docs_sync
from scheduler_service.runtime import runtime

router = APIRouter(tags=["scheduler"])


class TriggerRequest(BaseModel):
    task_code: str
    dry_run: bool = True
    payload: dict[str, Any] = Field(default_factory=dict)
    owner_endpoints: dict[str, str] = Field(
        default_factory=dict,
        description="Required for non-dry-run live dispatch. Example: {'hot-candidates-service':'http://hot-candidates-service:8031'}",
    )


class TriggerResponse(BaseModel):
    task_code: str
    dry_run: bool
    accepted: bool
    triggered_at: datetime
    owner_service: str
    writes_to: list[str]
    reads_from: list[str]
    message: str


@router.get("/health")
@router.get("/healthz")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "scheduler-service"}


@router.get("/readyz")
def ready() -> JSONResponse:
    payload = runtime.ready_snapshot()
    payload["hot_pipeline_tasks"] = len(HOT_CANDIDATES_TASKS)
    payload["three_model_tasks"] = len(THREE_MODEL_TASKS)
    return JSONResponse(payload, status_code=200 if payload["status"] == "ready" else 503)


@router.get("/scheduler/status")
def scheduler_status() -> dict[str, Any]:
    runtime_status = runtime.ready_snapshot()
    return {
        "status": "running_contract_mode" if runtime_status["status"] == "ready" else "runtime_not_ready",
        "service": "scheduler-service",
        "scheduler_version": "scheduler_three_model_service_v1.0_rc_dispatch_candidate",
        "hot_pipeline_tasks": len(HOT_CANDIDATES_TASKS),
        "three_model_tasks": len(THREE_MODEL_TASKS),
        "runtime": runtime_status,
        "hard_rules": [
            "high frequency source collection does not publish official model facts",
            "release gate is the only official signal promotion path",
            "observations are append-only and never overwrite initial decisions",
            "offline evolution never mutates production weights directly",
        ],
    }


@router.get("/scheduler/runtime/status")
def scheduler_runtime_status() -> dict[str, Any]:
    return runtime.ready_snapshot()


@router.get("/scheduler/plan/hot-candidates")
def get_hot_candidates_plan() -> dict[str, Any]:
    return {"plan_version": "hot_candidates_scheduler_plan_v1", "tasks": hot_plan()}


@router.get("/scheduler/validate/hot-candidates")
def validate_hot_candidates_plan() -> dict[str, Any]:
    return validate_hot_plan_contract()


@router.get("/scheduler/plan/three-models")
def get_three_models_plan() -> dict[str, Any]:
    return {"plan_version": "three_model_scheduler_design_v1", "tasks": three_model_plan()}


@router.get("/scheduler/validate/three-models")
def validate_three_models_plan() -> dict[str, Any]:
    return validate_three_model_plan_contract()


@router.get("/scheduler/materialize/three-models")
def materialize_three_models(trading_day: date, include_research_intraday: bool = False) -> dict[str, Any]:
    return materialize_three_model_day(
        trading_day=trading_day,
        include_research_intraday=include_research_intraday,
    )


@router.get("/scheduler/live-dispatch/sample/{task_code}")
def live_dispatch_sample(
    task_code: str,
    trading_day: date = date(2026, 6, 12),
    as_of_time_utc: str = "2026-06-13T03:10:00Z",
) -> dict[str, Any]:
    task = next((item for item in THREE_MODEL_TASKS if item.task_code == task_code), None)
    if task is None:
        raise HTTPException(status_code=404, detail=f"unknown scheduler task_code: {task_code}")
    try:
        payload = build_live_dispatch_sample_payload(
            task_code,
            trading_day=trading_day.isoformat(),
            as_of_time_utc=as_of_time_utc,
        )
        owner_body = ThreeModelLiveDispatcher.request_body_for(task, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "contract_kind": "scheduler_live_dispatch_sample_v1",
        "task_code": task.task_code,
        "owner_service": task.owner_service,
        "owner_endpoint_path": ThreeModelLiveDispatcher.path_for(task),
        "scheduler_trigger_payload": payload,
        "owner_request_body_preview": owner_body,
        "note": "Sample payload is contract-shaped for live-dispatch validation only; it is not market evidence.",
    }


@router.get("/scheduler/validate/live-dispatch-samples")
def validate_live_dispatch_samples() -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for task_code in OFFICIAL_RELEASE_GATE_TASKS:
        task = next((item for item in THREE_MODEL_TASKS if item.task_code == task_code), None)
        if task is None:
            rows.append({"task_code": task_code, "valid": False, "error": "missing task definition"})
            continue
        try:
            payload = build_live_dispatch_sample_payload(task_code)
            owner_body = ThreeModelLiveDispatcher.request_body_for(task, payload)
            rows.append(
                {
                    "task_code": task_code,
                    "owner_service": task.owner_service,
                    "owner_endpoint_path": ThreeModelLiveDispatcher.path_for(task),
                    "valid": True,
                    "scheduler_payload_keys": sorted(payload.keys()),
                    "owner_body_keys": sorted(owner_body.keys()),
                }
            )
        except Exception as exc:  # noqa: BLE001
            rows.append({"task_code": task_code, "owner_service": task.owner_service, "valid": False, "error": str(exc)})
    return {
        "contract_kind": "scheduler_live_dispatch_sample_validation_v1",
        "sample_version": "three_model_live_dispatch_sample_v1",
        "valid": all(row.get("valid") is True for row in rows),
        "rows": rows,
    }


@router.get("/scheduler/validate/docs-sync")
def validate_docs_sync(project_root: str = ".") -> dict[str, Any]:
    return validate_scheduler_docs_sync(project_root)


@router.post("/scheduler/trigger", response_model=TriggerResponse)
def trigger_task(request: TriggerRequest) -> TriggerResponse:
    task = next((item for item in THREE_MODEL_TASKS if item.task_code == request.task_code), None)
    if task is None:
        raise HTTPException(status_code=404, detail=f"unknown scheduler task_code: {request.task_code}")
    if not request.dry_run:
        if not request.owner_endpoints:
            raise HTTPException(
                status_code=409,
                detail="non-dry-run dispatch requires owner_endpoints so scheduler does not fabricate success",
            )
        try:
            registry = OwnerEndpointRegistry.from_mapping(request.owner_endpoints)
            result = ThreeModelLiveDispatcher(registry).dispatch(request.task_code, payload=request.payload)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"live dispatch failed: {exc}") from exc
        return TriggerResponse(
            task_code=task.task_code,
            dry_run=False,
            accepted=result.accepted,
            triggered_at=result.dispatched_at,
            owner_service=task.owner_service,
            writes_to=task.writes_to,
            reads_from=task.reads_from,
            message=f"live dispatch sent to {result.url}; status_code={result.status_code}",
        )
    return TriggerResponse(
        task_code=task.task_code,
        dry_run=True,
        accepted=True,
        triggered_at=datetime.now(timezone.utc),
        owner_service=task.owner_service,
        writes_to=task.writes_to,
        reads_from=task.reads_from,
        message="dry-run accepted; no source data or model fact was fabricated",
    )


@router.get("/scheduler/validate/hot-workflow")
def validate_hot_workflow() -> dict[str, Any]:
    return HotWorkflowOrchestrator().validate_full_chain()
