from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from scheduler_service.hot_plan import HOT_CANDIDATES_TASKS, hot_plan, validate_hot_plan_contract
from scheduler_service.three_model_plan import THREE_MODEL_SCHEDULER_VERSION, THREE_MODEL_TASKS, three_model_plan, validate_three_model_plan_contract
from scheduler_service.orchestrator import HotWorkflowOrchestrator
from scheduler_service.live_dispatch import HotLiveDispatcher
from scheduler_service.three_model_dispatch import (
    LIVE_DISPATCH_SAMPLE_TASKS,
    OwnerEndpointRegistry,
    ThreeModelLiveDispatcher,
    build_live_dispatch_sample_payload,
    model_payload_requirements,
    preflight_model_dispatch_payload,
)
from scheduler_service.three_model_materializer import materialize_three_model_day
from scheduler_service.docs_sync import validate_scheduler_docs_sync
from scheduler_service.runtime import runtime
from scheduler_service.source_schedule import (
    EXPLICIT_MODEL_STAGE_CANDIDATE_SOURCE,
    SOURCE_SCHEDULE_REGISTRY_VERSION,
    SOURCE_TIME_WHEEL_VERSION,
    T_RELAY_LIMIT_EVENT_STAGE_CANDIDATE_SOURCE,
    materialize_source_fetch_schedule,
    source_schedule_registry,
    validate_source_schedule_registry,
)

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


class TemporarySourceFetchRequest(BaseModel):
    requesting_service: str
    source_table_name: str
    canonical_fields: list[str] = Field(default_factory=list)
    symbols: list[str] = Field(default_factory=list)
    trade_date: date | None = None
    start_date: date | None = None
    end_date: date | None = None
    trigger_type: str = "model_adhoc_request"
    priority: str = "research"
    model_code: str | None = None
    model_phase: str | None = None
    callback_url: str | None = None
    idempotency_key: str | None = None
    dry_run: bool = True


class SourceScheduleCatchUpRequest(BaseModel):
    trading_day: date
    symbols: list[str] = Field(default_factory=list)
    include_one_time: bool = False
    schedule_codes: list[str] = Field(default_factory=list)
    schedule_groups: list[str] = Field(default_factory=list)
    source_table_names: list[str] = Field(default_factory=list)
    run_slots: list[str] = Field(default_factory=list)
    allow_ths_paid_probability_fetch: bool = False
    allow_ths_paid_probability_deadline_guard: bool = False
    dispatch_immediately: bool = False
    dry_run: bool = True
    force_resubmit: bool = False
    catch_up_run_id: str | None = None
    max_instances: int = Field(default=50, ge=1, le=1000)


class ArchiveObsoleteSourceDeadLettersRequest(BaseModel):
    task_code: str = "source.minute.auction_snapshot"
    source_table_name: str = "source.auction_snapshot_v1"
    legacy_canonical_fields: list[str] = Field(
        default_factory=lambda: ["price", "volume", "amount", "captured_at", "provider_definition"]
    )
    replacement_canonical_fields: list[str] = Field(
        default_factory=lambda: ["virtual_open_price", "matched_volume", "matched_amount", "event_time"]
    )
    reason: str = "auction snapshot scheduler contract replaced by canonical source fields"
    dry_run: bool = True
    max_tasks: int = Field(default=500, ge=1, le=1000)


class ReclassifySourceDuplicateSuccessesRequest(BaseModel):
    task_code: str | None = "source.minute.auction_snapshot"
    source_table_name: str | None = "source.auction_snapshot_v1"
    reason: str = "source submit accepted duplicate no-op; source facts verified through source/source_lineage"
    dry_run: bool = True
    max_tasks: int = Field(default=500, ge=1, le=1000)


class ModelScheduleCatchUpRequest(BaseModel):
    trading_day: date
    task_codes: list[str] = Field(default_factory=list)
    owner_services: list[str] = Field(default_factory=list)
    run_slots: list[str] = Field(default_factory=list)
    include_research_intraday: bool | None = None
    dispatch_immediately: bool = False
    dry_run: bool = True
    force_resubmit: bool = False
    catch_up_run_id: str | None = None
    max_instances: int = Field(default=50, ge=1, le=1000)


class ModelPayloadPreflightRequest(BaseModel):
    task_code: str
    payload: dict[str, Any] = Field(default_factory=dict)


class ModelPayloadAssemblePreflightRequest(BaseModel):
    task_code: str
    symbol: str | None = None
    symbols: list[str] = Field(default_factory=list)
    trade_date: date
    as_of_time_utc: datetime | None = None
    run_id: str | None = None
    persist_audit: bool = False
    extra_context: dict[str, Any] = Field(default_factory=dict)


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
    return {"plan_version": THREE_MODEL_SCHEDULER_VERSION, "tasks": three_model_plan()}


@router.get("/scheduler/validate/three-models")
def validate_three_models_plan() -> dict[str, Any]:
    return validate_three_model_plan_contract()


@router.get("/scheduler/materialize/three-models")
def materialize_three_models(trading_day: date, include_research_intraday: bool = False) -> dict[str, Any]:
    return materialize_three_model_day(
        trading_day=trading_day,
        include_research_intraday=include_research_intraday,
    )


@router.get("/scheduler/source-schedule/registry")
def get_source_schedule_registry() -> dict[str, Any]:
    return {
        "contract_kind": "scheduler_source_schedule_registry_v1",
        "registry_version": SOURCE_SCHEDULE_REGISTRY_VERSION,
        "source_fetch_endpoints": ["POST /source/fetch/plan", "POST /source/fetch/submit"],
        "schedules": source_schedule_registry(),
    }


@router.get("/scheduler/validate/source-schedule")
def validate_source_schedule() -> dict[str, Any]:
    return validate_source_schedule_registry()


@router.get("/scheduler/materialize/source-schedule")
def materialize_source_schedule(
    trading_day: date,
    symbols: str = "",
    include_one_time: bool = False,
) -> dict[str, Any]:
    parsed_symbols = [item.strip() for item in symbols.split(",") if item.strip()]
    instances = materialize_source_fetch_schedule(
        trading_day=trading_day,
        symbols=parsed_symbols,
        stage_candidate_symbols_by_source={
            EXPLICIT_MODEL_STAGE_CANDIDATE_SOURCE: parsed_symbols,
            T_RELAY_LIMIT_EVENT_STAGE_CANDIDATE_SOURCE: parsed_symbols,
        }
        if parsed_symbols
        else {},
        include_one_time=include_one_time,
    )
    return {
        "contract_kind": "scheduler_source_schedule_materialization_v1",
        "registry_version": SOURCE_SCHEDULE_REGISTRY_VERSION,
        "trading_day": trading_day.isoformat(),
        "symbols": parsed_symbols,
        "include_one_time": include_one_time,
        "instance_count": len(instances),
        "instances": [item.to_dict() for item in instances],
    }

@router.get("/scheduler/task-store/daily-summary")
def scheduler_task_store_daily_summary(
    trading_day: date,
    owner_service: str = "source-data-service",
    symbols: str = "",
    include_one_time: bool = False,
) -> dict[str, Any]:
    if owner_service != "source-data-service":
        raise HTTPException(status_code=409, detail="daily task-store summary currently supports source-data-service only")
    parsed_symbols = [item.strip() for item in symbols.split(",") if item.strip()]
    instances = materialize_source_fetch_schedule(
        trading_day=trading_day,
        symbols=parsed_symbols,
        stage_candidate_symbols_by_source={
            EXPLICIT_MODEL_STAGE_CANDIDATE_SOURCE: parsed_symbols,
            T_RELAY_LIMIT_EVENT_STAGE_CANDIDATE_SOURCE: parsed_symbols,
        }
        if parsed_symbols
        else {},
        include_one_time=include_one_time,
    )
    return runtime.task_store.daily_source_execution_summary(
        trading_day=trading_day,
        materialized_instances=[item.to_dict() for item in instances],
        now=datetime.now(timezone.utc),
        owner_service=owner_service,
    )

@router.post("/scheduler/source-schedule/catch-up")
def catch_up_source_schedule(request: SourceScheduleCatchUpRequest) -> dict[str, Any]:
    try:
        return runtime.catch_up_source_schedule(
            trading_day=request.trading_day,
            symbols=request.symbols,
            include_one_time=request.include_one_time,
            schedule_codes=request.schedule_codes,
            schedule_groups=request.schedule_groups,
            source_table_names=request.source_table_names,
            run_slots=request.run_slots,
            allow_ths_paid_probability_fetch=request.allow_ths_paid_probability_fetch,
            allow_ths_paid_probability_deadline_guard=request.allow_ths_paid_probability_deadline_guard,
            dispatch_immediately=request.dispatch_immediately,
            dry_run=request.dry_run,
            force_resubmit=request.force_resubmit,
            catch_up_run_id=request.catch_up_run_id,
            max_instances=request.max_instances,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/scheduler/task-store/archive-obsolete-source-dead-letters")
def archive_obsolete_source_dead_letters(request: ArchiveObsoleteSourceDeadLettersRequest) -> dict[str, Any]:
    try:
        return runtime.task_store.archive_obsolete_source_dead_letters(
            task_code=request.task_code,
            source_table_name=request.source_table_name,
            legacy_canonical_fields=request.legacy_canonical_fields,
            replacement_canonical_fields=request.replacement_canonical_fields,
            reason=request.reason,
            dry_run=request.dry_run,
            limit=request.max_tasks,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/scheduler/task-store/reclassify-source-duplicate-successes")
def reclassify_source_duplicate_successes(request: ReclassifySourceDuplicateSuccessesRequest) -> dict[str, Any]:
    try:
        return runtime.task_store.reclassify_source_duplicate_successes(
            task_code=request.task_code,
            source_table_name=request.source_table_name,
            reason=request.reason,
            dry_run=request.dry_run,
            limit=request.max_tasks,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/scheduler/source-time-wheel/run-once")
def run_source_time_wheel_once() -> dict[str, Any]:
    return runtime.run_source_time_wheel_once()


@router.post("/scheduler/model-time-wheel/run-once")
def run_model_time_wheel_once() -> dict[str, Any]:
    return runtime.run_model_time_wheel_once()


@router.post("/scheduler/model-schedule/catch-up")
def catch_up_model_schedule(request: ModelScheduleCatchUpRequest) -> dict[str, Any]:
    try:
        return runtime.catch_up_model_schedule(
            trading_day=request.trading_day,
            task_codes=request.task_codes,
            owner_services=request.owner_services,
            run_slots=request.run_slots,
            include_research_intraday=request.include_research_intraday,
            dispatch_immediately=request.dispatch_immediately,
            dry_run=request.dry_run,
            force_resubmit=request.force_resubmit,
            catch_up_run_id=request.catch_up_run_id,
            max_instances=request.max_instances,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/scheduler/model-payload/requirements")
def get_model_payload_requirements() -> dict[str, Any]:
    return model_payload_requirements()


@router.post("/scheduler/model-payload/preflight")
def model_payload_preflight(request: ModelPayloadPreflightRequest) -> dict[str, Any]:
    return preflight_model_dispatch_payload(request.task_code, request.payload).to_dict()


@router.post("/scheduler/model-payload/assemble-preflight")
def model_payload_assemble_preflight(request: ModelPayloadAssemblePreflightRequest) -> dict[str, Any]:
    task = next((item for item in THREE_MODEL_TASKS if item.task_code == request.task_code), None)
    if task is None:
        raise HTTPException(status_code=404, detail=f"unknown scheduler task_code: {request.task_code}")
    symbols = request.symbols or ([request.symbol] if request.symbol else [])
    if not symbols:
        raise HTTPException(status_code=409, detail="assemble-preflight requires symbol or symbols")
    research_body: dict[str, Any] = {
        "task_code": request.task_code,
        "symbol": request.symbol or symbols[0],
        "symbols": symbols,
        "trade_date": request.trade_date.isoformat(),
        "persist_audit": request.persist_audit,
        "extra_context": request.extra_context,
    }
    if request.as_of_time_utc is not None:
        research_body["as_of_time_utc"] = request.as_of_time_utc.isoformat()
    if request.run_id:
        research_body["run_id"] = request.run_id
    response = runtime.client.post(
        f"{runtime.research_service_base_url}/research/model-payload/assemble",
        json=research_body,
        timeout=runtime.request_timeout_seconds,
    )
    status_code = int(getattr(response, "status_code", 0))
    try:
        assembly = response.json()
    except Exception:  # noqa: BLE001
        assembly = {"text": str(getattr(response, "text", ""))[:500]}
    if not 200 <= status_code < 300 or not isinstance(assembly, dict):
        raise HTTPException(status_code=502, detail={"status_code": status_code, "research_response": assembly})
    payload = assembly.get("payload")
    if not isinstance(payload, dict):
        payload = {}
    preflight = preflight_model_dispatch_payload(request.task_code, payload)
    dispatch_allowed = (
        assembly.get("payload_assembly_status") == "assembled_research_payload"
        and preflight.valid
    )
    owner_preview = None
    if dispatch_allowed:
        owner_preview = ThreeModelLiveDispatcher.request_body_for(task, payload)
    return {
        "contract_kind": "scheduler_research_payload_assemble_preflight_v1",
        "research_service_base_url": runtime.research_service_base_url,
        "research_status_code": status_code,
        "research_request": research_body,
        "assembly": assembly,
        "scheduler_preflight": preflight.to_dict(),
        "dispatch_allowed": dispatch_allowed,
        "owner_service": task.owner_service,
        "owner_endpoint": f"POST {ThreeModelLiveDispatcher.path_for(task)}",
        "owner_request_body_preview": owner_preview,
        "hard_rules": [
            "This endpoint does not dispatch owner services.",
            "research-service assembles facts; scheduler only preflights and previews owner wrapping.",
            "blocked_data_gap or failed scheduler preflight prevents owner dispatch.",
        ],
    }


@router.post("/scheduler/source-fetch/temporary")
def temporary_source_fetch(request: TemporarySourceFetchRequest) -> dict[str, Any]:
    if request.trigger_type == "scheduled_periodic":
        raise HTTPException(status_code=409, detail="temporary source fetch cannot use scheduled_periodic trigger_type")
    source_table_name = request.source_table_name.strip()
    if not source_table_name.startswith("source."):
        raise HTTPException(status_code=409, detail="temporary source fetch must target source.* tables")
    canonical_fields = [field.strip() for field in request.canonical_fields if field.strip()]
    if not canonical_fields:
        raise HTTPException(status_code=409, detail="temporary source fetch requires canonical_fields")
    request_source = f"scheduler-service:{request.requesting_service}"
    body: dict[str, Any] = {
        "source_table_name": source_table_name,
        "canonical_fields": canonical_fields,
        "symbols": request.symbols,
        "trigger_type": request.trigger_type,
        "priority": request.priority,
        "request_source": request_source,
        "dry_run": request.dry_run,
        "prefer_batch": True,
        "auto_start": False,
    }
    if request.trade_date is not None:
        body["trade_date"] = request.trade_date.isoformat()
    if request.start_date is not None:
        body["start_date"] = request.start_date.isoformat()
    if request.end_date is not None:
        body["end_date"] = request.end_date.isoformat()
    if request.model_code:
        body["model_code"] = request.model_code
    if request.model_phase:
        body["model_phase"] = request.model_phase
    if request.callback_url:
        body["callback_url"] = request.callback_url
    if request.idempotency_key:
        body["idempotency_key"] = request.idempotency_key
    else:
        date_slot = request.trade_date or request.start_date or request.end_date or date.today()
        body["idempotency_key"] = (
            f"temporary:{request.requesting_service}:{request.source_table_name}:{date_slot.isoformat()}"
        )
    if request.dry_run:
        return {
            "contract_kind": "scheduler_temporary_source_fetch_preview_v1",
            "source_time_wheel_version": SOURCE_TIME_WHEEL_VERSION,
            "dry_run": True,
            "owner_service": "source-data-service",
            "owner_endpoint": "POST /source/fetch/submit",
            "request_body_preview": body,
            "hard_rule": "Temporary fetch requests are explicit ad hoc source orchestration, not recurring schedules.",
        }
    response = runtime.client.post(
        f"{runtime.source_data_base_url}/source/fetch/submit",
        json=body,
        timeout=runtime.request_timeout_seconds,
    )
    status_code = int(getattr(response, "status_code", 0))
    try:
        payload = response.json()
    except Exception:  # noqa: BLE001
        payload = {"text": str(getattr(response, "text", ""))[:500]}
    if not 200 <= status_code < 300:
        raise HTTPException(status_code=502, detail={"status_code": status_code, "source_response": payload})
    return {
        "contract_kind": "scheduler_temporary_source_fetch_submit_v1",
        "dry_run": False,
        "owner_service": "source-data-service",
        "owner_endpoint": "POST /source/fetch/submit",
        "status_code": status_code,
        "source_response": payload,
    }


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
    for task_code in LIVE_DISPATCH_SAMPLE_TASKS:
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
