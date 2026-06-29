from __future__ import annotations

from fastapi import FastAPI, HTTPException

from source_data_service import __version__
from source_data_service.gap_detector import build_repair_plan, diagnose_gap, resolve_lineage_plan
from source_data_service.models import (
    AcceptanceRunOut,
    AcceptanceRunPersistRequest,
    FetchBatchCancelRequest,
    FetchCallbackDispatchRequest,
    FetchCallbackDispatchResult,
    FetchJobCompleteRequest,
    FetchJobHeartbeatRequest,
    FetchJobLeaseOut,
    FetchJobLeaseRequest,
    FetchJobStatusOut,
    FetchLeaseMaintenanceResult,
    FetchQueuePersistenceStatusOut,
    FetchQueueSummaryOut,
    FetchWorkerRunOnceRequest,
    FetchWorkerRunOnceResult,
    FetchPlanOut,
    FetchPlanRequest,
    FetchSubmitRequest,
    FetchSubmitResult,
    FetchBatchStatusOut,
    FetchCallbackEventOut,
    HealthOut,
    LineageResolveRequest,
    LineageResolveResult,
    MultiSourceQualityCheckRequest,
    MultiSourceQualityCheckResult,
    ProbeRequest,
    ProbeResult,
    Provider,
    ProviderRuntimeStatus,
    RawFetchRequest,
    RawFetchResult,
    QualityValidationRequest,
    QualityValidationResult,
    ReadinessMatrixOut,
    RepairRouteOut,
    SourceBuildPlan,
    SourceBuildTriggerOut,
    SourceBuildPlanRequest,
    SourceProbeMatrixOut,
    ReadinessOut,
    ReadinessRequest,
    ReadinessResult,
    SourceFieldContract,
    SourceGapDiagnosis,
    SourceGapRepairPlan,
    SourceGapRequest,
    RawIngestResult,
    RawRepositoryStatusOut,
    SourceBuildExecuteRequest,
    SourceBuildExecutionResult,
    SourceBuildWorkerRunOnceRequest,
    SourceBuildWorkerRunOnceResult,
    SourceCanonicalRowOut,
    SourceLineageRecordOut,
    SourceFreshnessSla,
    SourceFreshnessStatusRequest,
    SourceFreshnessStatusResult,
    SourceStoragePolicy,
    ModelSourceRequirement,
    ModelCoverageCheckRequest,
    ModelCoverageCheckResult,
    ReleasePreflightRequest,
    ReleasePreflightResult,
    ProductionReadinessReport,
    ThsPaidProbabilityBatchStatus,
    ThsPaidProbabilityCookieStatus,
    ThsPaidProbabilityCookieUpdateRequest,
    ThsPaidProbabilityFetchCurrentBatchRequest,
    ThsPaidProbabilityFetchCurrentBatchResult,
    ThsPaidProbabilityProbeRequest,
    ThsPaidProbabilityProbeResult,
)
from source_data_service.acceptance_evidence import (
    get_acceptance_run,
    list_acceptance_runs,
    persist_acceptance_run,
)
from source_data_service.probe import list_probe_results, run_probe
from source_data_service.provider_registry import (
    get_api_spec,
    list_api_specs,
    list_field_contracts,
    list_source_requirements,
)
from source_data_service.provider_runtime import execute_provider_fetch, list_provider_status, provider_summary
from source_data_service.source_repository import (
    ingest_raw_fetch_result,
    repository_status,
    execute_source_build_trigger,
    run_source_build_worker_once,
    list_build_results,
    list_lineage_records,
    list_source_rows,
)
from source_data_service.operational_governance import (
    list_freshness_sla,
    check_freshness,
    list_storage_policies,
    list_model_requirements,
    check_model_coverage,
    preflight_release,
)
from source_data_service.production_readiness import build_production_readiness_report
from source_data_service.source_build import (
    build_probe_matrix,
    build_readiness_matrix,
    build_repair_routes,
    build_source_plan,
    validate_raw_rows,
)
from source_data_service.multi_source_quality import check_multi_source_quality
from source_data_service.fetch_orchestrator import (
    build_fetch_plan,
    cancel_fetch_batch,
    complete_fetch_job,
    dispatch_callback_events,
    get_fetch_batch,
    get_fetch_job,
    heartbeat_fetch_job,
    lease_fetch_jobs,
    list_dead_letter_jobs,
    list_callback_events,
    list_provider_concurrency_status,
    list_source_build_triggers,
    list_rate_limit_policies,
    queue_persistence_status,
    queue_summary,
    requeue_expired_leases,
    submit_fetch_batch,
)
from source_data_service.worker_executor import run_worker_once
from source_data_service.ths_paid_credentials import cookie_status, save_active_cookie
from source_data_service.ths_paid_probability import deadline_check, evaluate_batch_status, fetch_current_batch, probe_cookie

app = FastAPI(
    title="ai_stock source-data-service",
    version=__version__,
    description="Provider raw-interface first source data service for 神策中心.",
)


@app.get("/health", response_model=HealthOut)
@app.get("/healthz", response_model=HealthOut)
def health() -> HealthOut:
    # Liveness: never checks remote providers. Provider outages must not take the
    # service process down.
    return HealthOut(status="ok", service="source-data-service", version=__version__)


@app.get("/readyz", response_model=ReadinessOut)
def readyz() -> ReadinessOut:
    p0_count = sum(1 for item in list_source_requirements() if item.required_level.value == "P0")
    summary = provider_summary()
    status = "ready"
    note = "registry loaded; provider failures are isolated by adapter/circuit breaker"
    # If all API registry entries vanished, the service is not useful but still alive.
    if summary.get("registered_api_count", 0) == 0 or p0_count == 0:
        status = "degraded"
        note = "registry or P0 requirements missing"
    return ReadinessOut(
        status=status,
        service="source-data-service",
        version=__version__,
        provider_registry_count=summary.get("registered_api_count", 0),
        p0_requirement_count=p0_count,
        note=note,
    )


@app.get("/source/apis")
def list_registered_apis(provider: str | None = None):
    rows = list_api_specs()
    if provider:
        rows = [item for item in rows if item.provider.value == provider]
    return rows


@app.get("/source/apis/{provider}/{api_name}")
def get_registered_api(provider: str, api_name: str):
    try:
        return get_api_spec(Provider(provider), api_name)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/source/ths/paid-probability/cookie/status", response_model=ThsPaidProbabilityCookieStatus)
def ths_paid_probability_cookie_status() -> ThsPaidProbabilityCookieStatus:
    return cookie_status()


@app.put("/source/ths/paid-probability/cookie", response_model=ThsPaidProbabilityCookieStatus)
def ths_paid_probability_cookie_update(
    request: ThsPaidProbabilityCookieUpdateRequest,
) -> ThsPaidProbabilityCookieStatus:
    return save_active_cookie(user=request.user, userid=request.userid, updated_by=request.updated_by)


@app.post("/source/ths/paid-probability/probe", response_model=ThsPaidProbabilityProbeResult)
def ths_paid_probability_probe(request: ThsPaidProbabilityProbeRequest) -> ThsPaidProbabilityProbeResult:
    return probe_cookie(request)


@app.post("/source/ths/paid-probability/fetch-current-batch", response_model=ThsPaidProbabilityFetchCurrentBatchResult)
def ths_paid_probability_fetch_current_batch(
    request: ThsPaidProbabilityFetchCurrentBatchRequest,
) -> ThsPaidProbabilityFetchCurrentBatchResult:
    return fetch_current_batch(request)


@app.get("/source/ths/paid-probability/batch-status", response_model=ThsPaidProbabilityBatchStatus)
def ths_paid_probability_batch_status(trade_date: str | None = None) -> ThsPaidProbabilityBatchStatus:
    parsed_trade_date = None
    if trade_date:
        try:
            from datetime import date

            parsed_trade_date = date.fromisoformat(trade_date[:10])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="trade_date must be YYYY-MM-DD") from exc
    return evaluate_batch_status(parsed_trade_date, mark_deadline=True)


@app.post("/source/ths/paid-probability/deadline-check", response_model=ThsPaidProbabilityBatchStatus)
def ths_paid_probability_deadline_check(
    request: ThsPaidProbabilityFetchCurrentBatchRequest | None = None,
) -> ThsPaidProbabilityBatchStatus:
    return deadline_check(request.trade_date if request else None)


@app.get("/source/providers/status", response_model=list[ProviderRuntimeStatus])
def providers_status(provider: str | None = None):
    try:
        parsed = Provider(provider) if provider else None
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return list_provider_status(parsed)


@app.get("/source/requirements")
def list_requirements(source_table_name: str | None = None):
    return list_source_requirements(source_table_name)


@app.post("/source/raw/fetch", response_model=RawFetchResult)
def fetch_raw_interface(request: RawFetchRequest) -> RawFetchResult:
    try:
        # Structured errors are returned in RawFetchResult.error; the HTTP service
        # stays alive so caller can immediately use backup repair plans.
        return execute_provider_fetch(
            provider=request.provider,
            api_name=request.api_name,
            params=request.params,
            dry_run=request.dry_run,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/source/probe", response_model=ProbeResult)
def probe_provider_api(request: ProbeRequest) -> ProbeResult:
    return run_probe(request)


@app.get("/source/probe/results")
def source_probe_results(provider: str | None = None, api_name: str | None = None, limit: int = 50):
    return list_probe_results(provider=provider, api_name=api_name, limit=limit)


@app.get("/source/repository/status", response_model=RawRepositoryStatusOut)
def source_repository_status() -> RawRepositoryStatusOut:
    return repository_status()


@app.post("/source/raw/ingest-result", response_model=RawIngestResult)
def source_raw_ingest_result(result: RawFetchResult) -> RawIngestResult:
    return ingest_raw_fetch_result(result)


@app.get("/source/ops/production-readiness", response_model=ProductionReadinessReport)
def source_ops_production_readiness(require_postgres: bool = True, require_real_provider_probe: bool = False) -> ProductionReadinessReport:
    return build_production_readiness_report(require_postgres=require_postgres, require_real_provider_probe=require_real_provider_probe)


@app.post("/source/ops/acceptance-runs", response_model=AcceptanceRunOut)
def source_ops_acceptance_run_persist(request: AcceptanceRunPersistRequest) -> AcceptanceRunOut:
    return persist_acceptance_run(request)


@app.get("/source/ops/acceptance-runs", response_model=list[AcceptanceRunOut])
def source_ops_acceptance_runs(limit: int = 20) -> list[AcceptanceRunOut]:
    return list_acceptance_runs(limit=limit)


@app.get("/source/ops/acceptance-runs/{acceptance_run_id}", response_model=AcceptanceRunOut)
def source_ops_acceptance_run_get(acceptance_run_id: str) -> AcceptanceRunOut:
    run = get_acceptance_run(acceptance_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"acceptance run not found: {acceptance_run_id}")
    return run


@app.get("/source/rows", response_model=list[SourceCanonicalRowOut])
def source_rows(source_table_name: str | None = None, symbol: str | None = None, trade_date: str | None = None) -> list[SourceCanonicalRowOut]:
    return list_source_rows(source_table_name=source_table_name, symbol=symbol, trade_date=trade_date)


@app.get("/source/lineage/records", response_model=list[SourceLineageRecordOut])
def source_lineage_records(source_table_name: str | None = None, source_pk: str | None = None, canonical_field_name: str | None = None) -> list[SourceLineageRecordOut]:
    return list_lineage_records(source_table_name=source_table_name, source_pk=source_pk, canonical_field_name=canonical_field_name)


@app.get("/source/contracts", response_model=list[SourceFieldContract])
def list_contracts(source_table_name: str | None = None):
    return list_field_contracts(source_table_name)


@app.get("/source/contracts/{source_table_name:path}", response_model=list[SourceFieldContract])
def list_contracts_for_table(source_table_name: str):
    return list_field_contracts(source_table_name)




@app.get("/source/readiness/matrix", response_model=ReadinessMatrixOut)
def readiness_matrix() -> ReadinessMatrixOut:
    return build_readiness_matrix()


@app.get("/source/probe/matrix", response_model=SourceProbeMatrixOut)
def probe_matrix() -> SourceProbeMatrixOut:
    return build_probe_matrix()


@app.get("/source/repair-routes", response_model=RepairRouteOut)
def repair_routes() -> RepairRouteOut:
    return build_repair_routes()


@app.get("/source/providers/runtime-status")
def provider_concurrency_runtime_status(provider: str | None = None):
    try:
        parsed = Provider(provider) if provider else None
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return list_provider_concurrency_status(parsed)


@app.get("/source/fetch/rate-limit-policies")
def fetch_rate_limit_policies(provider: str | None = None):
    try:
        parsed = Provider(provider) if provider else None
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return list_rate_limit_policies(parsed)


@app.post("/source/fetch/plan", response_model=FetchPlanOut)
def fetch_plan(request: FetchPlanRequest) -> FetchPlanOut:
    try:
        return build_fetch_plan(request)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/source/fetch/submit", response_model=FetchSubmitResult)
def fetch_submit(request: FetchSubmitRequest) -> FetchSubmitResult:
    try:
        return submit_fetch_batch(request)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/source/fetch/worker/pull", response_model=FetchJobLeaseOut)
def fetch_worker_pull(request: FetchJobLeaseRequest) -> FetchJobLeaseOut:
    return lease_fetch_jobs(request)


@app.get("/source/fetch/batches/{fetch_batch_id}", response_model=FetchBatchStatusOut)
def fetch_batch_status(fetch_batch_id: str) -> FetchBatchStatusOut:
    try:
        return get_fetch_batch(fetch_batch_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/source/fetch/jobs/{job_item_id}", response_model=FetchJobStatusOut)
def fetch_job_status(job_item_id: str) -> FetchJobStatusOut:
    try:
        return get_fetch_job(job_item_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/source/fetch/jobs/{job_item_id}/complete", response_model=FetchJobStatusOut)
def fetch_job_complete(job_item_id: str, request: FetchJobCompleteRequest) -> FetchJobStatusOut:
    try:
        return complete_fetch_job(job_item_id, request)
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/source/fetch/callbacks", response_model=list[FetchCallbackEventOut])
def fetch_callbacks(fetch_batch_id: str | None = None) -> list[FetchCallbackEventOut]:
    return list_callback_events(fetch_batch_id)


@app.post("/source/fetch/callbacks/dispatch", response_model=FetchCallbackDispatchResult)
def fetch_callbacks_dispatch(request: FetchCallbackDispatchRequest) -> FetchCallbackDispatchResult:
    return dispatch_callback_events(request)


@app.get("/source/fetch/persistence/status", response_model=FetchQueuePersistenceStatusOut)
def fetch_persistence_status() -> FetchQueuePersistenceStatusOut:
    return queue_persistence_status()


@app.get("/source/fetch/queues/summary", response_model=FetchQueueSummaryOut)
def fetch_queues_summary() -> FetchQueueSummaryOut:
    return queue_summary()


@app.post("/source/fetch/maintenance/requeue-expired-leases", response_model=FetchLeaseMaintenanceResult)
def fetch_requeue_expired_leases() -> FetchLeaseMaintenanceResult:
    return requeue_expired_leases()


@app.get("/source/fetch/dead-letter", response_model=list[FetchJobStatusOut])
def fetch_dead_letter_jobs() -> list[FetchJobStatusOut]:
    return list_dead_letter_jobs()


@app.post("/source/fetch/batches/{fetch_batch_id}/cancel", response_model=FetchBatchStatusOut)
def fetch_batch_cancel(fetch_batch_id: str, request: FetchBatchCancelRequest) -> FetchBatchStatusOut:
    try:
        return cancel_fetch_batch(fetch_batch_id, request)
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/source/fetch/jobs/{job_item_id}/heartbeat", response_model=FetchJobStatusOut)
def fetch_job_heartbeat(job_item_id: str, request: FetchJobHeartbeatRequest) -> FetchJobStatusOut:
    try:
        return heartbeat_fetch_job(job_item_id, request)
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/source/fetch/worker/run-once", response_model=FetchWorkerRunOnceResult)
def fetch_worker_run_once(request: FetchWorkerRunOnceRequest) -> FetchWorkerRunOnceResult:
    return run_worker_once(request)


@app.get("/source/build/triggers", response_model=list[SourceBuildTriggerOut])
def source_build_triggers(fetch_batch_id: str | None = None) -> list[SourceBuildTriggerOut]:
    return list_source_build_triggers(fetch_batch_id)


@app.post("/source/build/triggers/{trigger_id}/execute", response_model=SourceBuildExecutionResult)
def source_build_trigger_execute(trigger_id: str, request: SourceBuildExecuteRequest | None = None) -> SourceBuildExecutionResult:
    req = request or SourceBuildExecuteRequest(trigger_id=trigger_id)
    if req.trigger_id != trigger_id:
        raise HTTPException(status_code=409, detail="trigger_id path and body mismatch")
    try:
        return execute_source_build_trigger(req)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/source/build/worker/run-once", response_model=SourceBuildWorkerRunOnceResult)
def source_build_worker_run_once(request: SourceBuildWorkerRunOnceRequest) -> SourceBuildWorkerRunOnceResult:
    return run_source_build_worker_once(request)


@app.get("/source/build/results", response_model=list[SourceBuildExecutionResult])
def source_build_results() -> list[SourceBuildExecutionResult]:
    return list_build_results()


@app.post("/source/build/plan", response_model=SourceBuildPlan)
def source_build_plan(request: SourceBuildPlanRequest) -> SourceBuildPlan:
    try:
        return build_source_plan(request)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/source/quality/validate-raw", response_model=QualityValidationResult)
def validate_raw_quality(request: QualityValidationRequest) -> QualityValidationResult:
    try:
        return validate_raw_rows(request)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/source/quality/multi-source/check", response_model=MultiSourceQualityCheckResult)
def validate_multi_source_quality(request: MultiSourceQualityCheckRequest) -> MultiSourceQualityCheckResult:
    try:
        return check_multi_source_quality(request)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/source/freshness/sla", response_model=list[SourceFreshnessSla])
def source_freshness_sla(source_table_name: str | None = None) -> list[SourceFreshnessSla]:
    return list_freshness_sla(source_table_name)


@app.post("/source/freshness/status/check", response_model=SourceFreshnessStatusResult)
def source_freshness_status_check(request: SourceFreshnessStatusRequest) -> SourceFreshnessStatusResult:
    return check_freshness(request)


@app.get("/source/storage/policies", response_model=list[SourceStoragePolicy])
def source_storage_policies(table_name: str | None = None) -> list[SourceStoragePolicy]:
    return list_storage_policies(table_name)


@app.get("/source/models/requirements", response_model=list[ModelSourceRequirement])
def source_model_requirements(model_code: str | None = None, model_phase: str | None = None) -> list[ModelSourceRequirement]:
    return list_model_requirements(model_code, model_phase)


@app.post("/source/models/coverage/check", response_model=ModelCoverageCheckResult)
def source_model_coverage_check(request: ModelCoverageCheckRequest) -> ModelCoverageCheckResult:
    return check_model_coverage(request)


@app.post("/source/release/preflight", response_model=ReleasePreflightResult)
def source_release_preflight(request: ReleasePreflightRequest) -> ReleasePreflightResult:
    return preflight_release(request)


@app.post("/source/gaps/repair-plan", response_model=SourceGapRepairPlan)
def build_gap_repair_plan(request: SourceGapRequest) -> SourceGapRepairPlan:
    try:
        return build_repair_plan(request)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/source/gaps/diagnose", response_model=SourceGapDiagnosis)
def diagnose_source_gap(request: SourceGapRequest) -> SourceGapDiagnosis:
    try:
        return diagnose_gap(request)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/source/lineage/resolve", response_model=LineageResolveResult)
def resolve_source_lineage(request: LineageResolveRequest) -> LineageResolveResult:
    try:
        return resolve_lineage_plan(request)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/source/readiness/evaluate", response_model=ReadinessResult)
def evaluate_readiness(request: ReadinessRequest) -> ReadinessResult:
    rows = list_source_requirements(request.source_table_name)
    if not rows:
        raise HTTPException(status_code=404, detail=f"no source requirements for {request.source_table_name}")
    p0 = [item for item in rows if item.required_level.value == "P0"]
    blockers = []
    for item in p0:
        if not item.backup_provider or not item.backup_api_name:
            blockers.append(f"missing backup provider for {item.canonical_field_name}")
        if item.minimum_coverage_rate < 0.995:
            blockers.append(f"P0 coverage threshold too low for {item.canonical_field_name}")
    readiness = "passed" if not blockers else "blocked"
    if not p0 and rows:
        readiness = "research_only"
    return ReadinessResult(
        source_table_name=request.source_table_name,
        required_field_count=len(rows),
        p0_field_count=len(p0),
        fields_with_backup_count=sum(1 for item in rows if item.backup_provider),
        readiness_status=readiness,
        blocking_reasons=blockers,
    )
