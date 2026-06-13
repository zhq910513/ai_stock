from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from itertools import count
from uuid import uuid4
from typing import Any

from source_data_service.adapters.base import stable_json_hash
from source_data_service.gap_detector import build_repair_plan
from source_data_service.fetch_persistence import (
    durable_build_triggers_if_enabled,
    durable_fetch_batch_if_enabled,
    durable_fetch_job_if_enabled,
    durable_queue_counts_if_enabled,
    durable_queue_summary_if_enabled,
    find_existing_job_item_id_if_enabled,
    load_active_state_if_enabled,
    persist_batch_if_enabled,
    persist_build_trigger_if_enabled,
    persist_callback_if_enabled,
    persist_job_if_enabled,
    queue_persistence_summary,
)
from source_data_service.models import (
    CallbackEventType,
    FetchBatchCancelRequest,
    FetchCallbackDispatchRequest,
    FetchCallbackDispatchResult,
    FetchJobHeartbeatRequest,
    FetchLeaseMaintenanceResult,
    FetchBackupPlan,
    FetchBatchStatus,
    FetchBatchStatusOut,
    FetchCallbackEventOut,
    FetchJobCompleteRequest,
    FetchJobLeaseOut,
    FetchJobLeaseRequest,
    FetchJobStatus,
    FetchJobStatusOut,
    FetchQueuePersistenceStatusOut,
    FetchQueueSummaryOut,
    FetchQueueSummaryRow,
    FetchPlanOut,
    FetchPlanRequest,
    FetchPlannedJob,
    FetchPriority,
    FetchQueueName,
    FetchStrategy,
    FetchSubmitRequest,
    FetchSubmitResult,
    FetchTriggerType,
    Provider,
    ProviderConcurrencyRuntimeStatus,
    ProviderRateLimitPolicy,
    SourceBuildTriggerOut,
    SourceGapRequest,
)
from source_data_service.provider_registry import get_api_spec, list_source_requirements
from source_data_service.provider_runtime import list_provider_status


# Provider/API-level policies are deliberately conservative for free public data.
# They protect the source-data-service from self-inflicted provider bans and keep
# release-gate-critical fetches ahead of historical backfills.
_RATE_LIMIT_POLICIES: dict[tuple[Provider, str], ProviderRateLimitPolicy] = {}
_DEFAULT_PROVIDER_LIMITS: dict[Provider, tuple[int, int, str]] = {
    Provider.BAOSTOCK: (4, 120, "BaoStock is free but should be protected by low symbol-level concurrency."),
    Provider.AKSHARE: (3, 60, "AKShare public webpage adapters can be rate-limited; keep concurrency low."),
    Provider.TUSHARE: (2, 60, "Tushare depends on token/integral frequency; respect per-account limits."),
    Provider.EASTMONEY: (4, 90, "EastMoney public endpoints should use bounded parallelism."),
    Provider.TENCENT: (3, 90, "Tencent quote endpoints are public; use bounded parallelism."),
    Provider.SINA: (2, 60, "Sina quote endpoints are public; use bounded parallelism."),
    Provider.CNINFO: (2, 30, "Announcement APIs favor stability over speed."),
    Provider.INTERNAL: (8, 600, "Internal build tasks can run with higher local concurrency."),
}
_API_POLICY_OVERRIDES: dict[tuple[Provider, str], tuple[int, int, str]] = {
    (Provider.AKSHARE, "stock_fund_flow_individual_realtime"): (1, 30, "Moneyflow endpoint is unstable under concurrency; serialize it."),
    (Provider.AKSHARE, "stock_zh_a_disclosure_report_cninfo"): (1, 20, "Disclosure endpoint should be serialized to avoid anti-crawling failures."),
    (Provider.BAOSTOCK, "query_history_k_data_plus_daily_raw"): (4, 120, "Symbol-level history fetch can use bounded parallelism."),
    (Provider.BAOSTOCK, "query_history_k_data_plus_daily_qfq"): (4, 120, "Adjusted history fetch can use bounded parallelism."),
}

_BATCH_COUNTER = count(1)
_JOB_COUNTER = count(1)
_CALLBACK_COUNTER = count(1)


@dataclass
class BatchRecord:
    fetch_batch_id: str
    fetch_plan_id: str
    source_table_name: str
    trigger_type: FetchTriggerType
    priority: FetchPriority
    queue_name: FetchQueueName
    callback_url: str | None
    status: FetchBatchStatus
    created_at: datetime
    updated_at: datetime
    operator_notes: list[str] = field(default_factory=list)


_BATCHES: dict[str, BatchRecord] = {}
_JOBS: dict[str, FetchJobStatusOut] = {}
_REQUEST_HASH_TO_JOB: dict[str, str] = {}
_CALLBACKS: list[FetchCallbackEventOut] = []
_BUILD_TRIGGERS: list[SourceBuildTriggerOut] = []
_IDEMPOTENCY_TO_BATCH: dict[str, str] = {}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _hydrate_active_state_from_persistence() -> None:
    batches, jobs = load_active_state_if_enabled()
    for batch in batches:
        if batch.fetch_batch_id not in _BATCHES:
            _BATCHES[batch.fetch_batch_id] = BatchRecord(
                fetch_batch_id=batch.fetch_batch_id,
                fetch_plan_id=batch.fetch_plan_id,
                source_table_name=batch.source_table_name,
                trigger_type=batch.trigger_type,
                priority=batch.priority,
                queue_name=batch.queue_name,
                callback_url=batch.callback_url,
                status=batch.status,
                created_at=batch.created_at,
                updated_at=batch.updated_at,
                operator_notes=batch.operator_notes,
            )
    for job in jobs:
        if job.job_item_id not in _JOBS:
            _JOBS[job.job_item_id] = job
            _REQUEST_HASH_TO_JOB[job.request_hash] = job.job_item_id


def _new_id(prefix: str) -> str:
    # UUID ids avoid collisions after process restarts; integer counters are kept
    # only for backwards compatibility with already-created in-memory tests.
    return f"{prefix}_{uuid4().hex[:20]}"


def _policy_for(provider: Provider, api_name: str) -> ProviderRateLimitPolicy:
    if (provider, api_name) in _RATE_LIMIT_POLICIES:
        return _RATE_LIMIT_POLICIES[(provider, api_name)]
    concurrency, rpm, comment = _API_POLICY_OVERRIDES.get(
        (provider, api_name),
        _DEFAULT_PROVIDER_LIMITS.get(provider, (2, 30, "Default conservative provider policy.")),
    )
    spec = None
    try:
        spec = get_api_spec(provider, api_name)
    except Exception:
        pass
    policy = ProviderRateLimitPolicy(
        provider=provider,
        api_name=api_name,
        max_concurrency=concurrency,
        requests_per_minute=rpm,
        min_interval_ms=max(0, int(60000 / rpm)) if rpm else 0,
        timeout_ms=int((spec.timeout_seconds if spec else 12.0) * 1000),
        max_retry_count=2,
        retry_backoff_policy="exponential",
        circuit_breaker_enabled=True,
        circuit_open_seconds=60,
        priority_weight=spec.priority if spec else 100,
        enabled=True,
        comment=comment,
    )
    _RATE_LIMIT_POLICIES[(provider, api_name)] = policy
    return policy


def list_rate_limit_policies(provider: Provider | None = None) -> list[ProviderRateLimitPolicy]:
    # Ensure known policies exist for all registered APIs.
    for req in list_source_requirements():
        _policy_for(req.primary_provider, req.primary_api_name)
        if req.backup_provider and req.backup_api_name:
            _policy_for(req.backup_provider, req.backup_api_name)
    policies = list(_RATE_LIMIT_POLICIES.values())
    if provider:
        policies = [item for item in policies if item.provider == provider]
    return sorted(policies, key=lambda item: (item.provider.value, item.api_name))


def _queue_for(priority: FetchPriority, trigger_type: FetchTriggerType) -> FetchQueueName:
    if trigger_type == FetchTriggerType.PROVIDER_PROBE:
        return FetchQueueName.PROVIDER_PROBE_QUEUE
    if trigger_type == FetchTriggerType.DATA_INSPECTION_GAP_REPAIR:
        return FetchQueueName.REPAIR_QUEUE
    if priority == FetchPriority.P0_URGENT_RELEASE or trigger_type == FetchTriggerType.MODEL_RELEASE_PREFLIGHT:
        return FetchQueueName.URGENT_RELEASE_GATE_QUEUE
    if priority == FetchPriority.P2_BACKFILL or trigger_type == FetchTriggerType.MANUAL_BACKFILL:
        return FetchQueueName.BACKFILL_QUEUE
    if priority == FetchPriority.RESEARCH:
        return FetchQueueName.RESEARCH_QUEUE
    return FetchQueueName.NORMAL_DAILY_INGEST_QUEUE


def _strategy_for(request: FetchPlanRequest, job_count: int) -> FetchStrategy:
    if request.prefer_batch and not request.symbols:
        return FetchStrategy.FULL_MARKET_BATCH
    if request.prefer_batch and request.trade_date and job_count == 1:
        return FetchStrategy.API_BATCH_BY_DATE
    if len(request.symbols) > 1 or job_count > 1:
        return FetchStrategy.SYMBOL_PARALLEL
    return FetchStrategy.SINGLE_REQUEST


def _source_date(request: FetchPlanRequest):
    return request.trade_date or request.start_date


def _gap_request_for(request: FetchPlanRequest, field_name: str, symbol: str | None) -> SourceGapRequest:
    return SourceGapRequest(
        source_table_name=request.source_table_name,
        canonical_field_name=field_name,
        symbol=symbol,
        trade_date=request.trade_date,
        start_date=request.start_date,
        end_date=request.end_date,
    )


def _job_hash(provider: Provider, api_name: str, params: dict[str, Any], raw_table_name: str) -> str:
    return stable_json_hash(
        {"provider": provider.value, "api_name": api_name, "raw_table_name": raw_table_name, "params": params}
    )


def build_fetch_plan(request: FetchPlanRequest) -> FetchPlanOut:
    requirements = [item for item in list_source_requirements(request.source_table_name)]
    if request.canonical_fields:
        requirements = [item for item in requirements if item.canonical_field_name in request.canonical_fields]
    if not requirements:
        raise KeyError(f"no source requirements for {request.source_table_name} fields={request.canonical_fields}")

    symbols = request.symbols or [None]
    queue_name = _queue_for(request.priority, request.trigger_type)
    grouped: dict[str, FetchPlannedJob] = {}
    field_by_hash: dict[str, set[str]] = {}

    for requirement in requirements:
        for symbol in symbols:
            gap_request = _gap_request_for(request, requirement.canonical_field_name, symbol)
            repair = build_repair_plan(gap_request)
            primary = repair.primary_repair
            request_hash = _job_hash(primary.provider, primary.api_name, primary.params, primary.raw_table_name)
            policy = _policy_for(primary.provider, primary.api_name)
            if request_hash not in grouped:
                grouped[request_hash] = FetchPlannedJob(
                    provider=primary.provider,
                    api_name=primary.api_name,
                    raw_table_name=primary.raw_table_name,
                    request_params=primary.params,
                    request_hash=request_hash,
                    source_table_name=request.source_table_name,
                    canonical_fields=[],
                    symbol=symbol,
                    trade_date=request.trade_date,
                    date_range_start=request.start_date,
                    date_range_end=request.end_date,
                    priority=request.priority,
                    queue_name=queue_name,
                    estimated_timeout_ms=policy.timeout_ms,
                    backup_plans=[
                        FetchBackupPlan(
                            provider=backup.provider,
                            api_name=backup.api_name,
                            raw_table_name=backup.raw_table_name,
                            request_params=backup.params,
                            reason=backup.reason,
                        )
                        for backup in repair.backup_repairs
                    ],
                )
                field_by_hash[request_hash] = set()
            field_by_hash[request_hash].add(requirement.canonical_field_name)

    jobs: list[FetchPlannedJob] = []
    for request_hash, job in grouped.items():
        job.canonical_fields = sorted(field_by_hash[request_hash])
        jobs.append(job)

    policies_by_key: dict[tuple[Provider, str], ProviderRateLimitPolicy] = {}
    for job in jobs:
        policies_by_key[(job.provider, job.api_name)] = _policy_for(job.provider, job.api_name)
        for backup in job.backup_plans:
            policies_by_key[(backup.provider, backup.api_name)] = _policy_for(backup.provider, backup.api_name)
    max_parallel = max((policy.max_concurrency for policy in policies_by_key.values()), default=1)
    estimated_runtime_seconds = round((len(jobs) / max_parallel) * 1.5, 2)
    fetch_plan_id = "plan_" + stable_json_hash(request.model_dump(mode="json"))[:16]
    strategy = _strategy_for(request, len(jobs))
    operator_notes = [
        "Producer-consumer fetch plan only; model services must not call provider APIs directly.",
        "Primary raw-interface jobs are queued first; backup jobs are created only when primary jobs fail.",
        "Every raw fetch must pass quality validation before source build and source_lineage writes.",
    ]
    if strategy == FetchStrategy.SYMBOL_PARALLEL:
        operator_notes.append("Symbol-level requests must obey provider/API concurrency limits; never launch unbounded threads.")
    if request.trigger_type == FetchTriggerType.MODEL_RELEASE_PREFLIGHT:
        operator_notes.append("Release preflight P0 fetches must not be delayed behind backfill or research queues.")

    return FetchPlanOut(
        fetch_plan_id=fetch_plan_id,
        source_table_name=request.source_table_name,
        trigger_type=request.trigger_type,
        priority=request.priority,
        strategy=strategy,
        queue_name=queue_name,
        job_count=len(jobs),
        deduplicated_job_count=len(jobs),
        symbols_count=len(request.symbols),
        estimated_runtime_seconds=estimated_runtime_seconds,
        jobs=jobs,
        rate_limit_policies=sorted(policies_by_key.values(), key=lambda item: (item.provider.value, item.api_name)),
        operator_notes=operator_notes,
    )


def _add_callback(
    *,
    fetch_batch_id: str,
    event_type: CallbackEventType,
    payload: dict[str, Any],
    job_item_id: str | None = None,
    callback_url: str | None = None,
) -> None:
    status = "pending" if callback_url else "skipped_no_callback"
    event = FetchCallbackEventOut(
        callback_event_id=_new_id("callback"),
        fetch_batch_id=fetch_batch_id,
        job_item_id=job_item_id,
        event_type=event_type,
        callback_url=callback_url,
        payload=payload,
        delivery_status=status,
        created_at=_utcnow(),
    )
    _CALLBACKS.append(event)
    persist_callback_if_enabled(event)


def submit_fetch_batch(request: FetchSubmitRequest) -> FetchSubmitResult:
    if request.idempotency_key and request.idempotency_key in _IDEMPOTENCY_TO_BATCH:
        existing_batch_id = _IDEMPOTENCY_TO_BATCH[request.idempotency_key]
        existing = get_fetch_batch(existing_batch_id)
        return FetchSubmitResult(
            fetch_batch_id=existing.fetch_batch_id,
            fetch_plan_id=existing.fetch_plan_id,
            status=existing.status,
            queue_name=existing.queue_name,
            submitted_job_count=0,
            skipped_duplicate_count=existing.job_count,
            callback_registered=bool(existing.callback_url),
            producer_ack="duplicate_idempotency_key_returned_existing_batch",
        )
    plan_request = FetchPlanRequest(**request.model_dump(exclude={"auto_start", "idempotency_key"}))
    plan = build_fetch_plan(plan_request)
    now = _utcnow()
    fetch_batch_id = _new_id("fetch_batch")
    batch = BatchRecord(
        fetch_batch_id=fetch_batch_id,
        fetch_plan_id=plan.fetch_plan_id,
        source_table_name=plan.source_table_name,
        trigger_type=plan.trigger_type,
        priority=plan.priority,
        queue_name=plan.queue_name,
        callback_url=request.callback_url,
        status=FetchBatchStatus.QUEUED,
        created_at=now,
        updated_at=now,
        operator_notes=plan.operator_notes,
    )
    _BATCHES[fetch_batch_id] = batch
    persist_batch_if_enabled(_batch_status_out(fetch_batch_id), request_source=request.request_source)
    skipped = 0
    for planned in plan.jobs:
        existing_job_id = _REQUEST_HASH_TO_JOB.get(planned.request_hash)
        if not existing_job_id:
            existing_job_id = find_existing_job_item_id_if_enabled(
                planned.provider,
                planned.api_name,
                planned.raw_table_name,
                planned.request_hash,
            )
        if existing_job_id:
            _REQUEST_HASH_TO_JOB[planned.request_hash] = existing_job_id
            skipped += 1
            continue
        job_item_id = _new_id("fetch_job")
        _REQUEST_HASH_TO_JOB[planned.request_hash] = job_item_id
        _JOBS[job_item_id] = FetchJobStatusOut(
            job_item_id=job_item_id,
            fetch_batch_id=fetch_batch_id,
            provider=planned.provider,
            api_name=planned.api_name,
            raw_table_name=planned.raw_table_name,
            request_params=planned.request_params,
            request_hash=planned.request_hash,
            source_table_name=planned.source_table_name,
            canonical_fields=planned.canonical_fields,
            symbol=planned.symbol,
            trade_date=planned.trade_date,
            priority=planned.priority,
            queue_name=planned.queue_name,
            status=FetchJobStatus.QUEUED,
            created_at=now,
            updated_at=now,
        )
        # Store backup plans inside request_params so durable queues can reconstruct backup routing.
        _JOBS[job_item_id].request_params = dict(_JOBS[job_item_id].request_params)
        _JOBS[job_item_id].request_params["__backup_plans"] = [item.model_dump(mode="json") for item in planned.backup_plans]
        persist_job_if_enabled(_JOBS[job_item_id])
    _add_callback(
        fetch_batch_id=fetch_batch_id,
        event_type=CallbackEventType.BATCH_SUBMITTED,
        callback_url=request.callback_url,
        payload={"fetch_batch_id": fetch_batch_id, "submitted_job_count": len(plan.jobs) - skipped, "skipped_duplicate_count": skipped},
    )
    if request.idempotency_key:
        _IDEMPOTENCY_TO_BATCH[request.idempotency_key] = fetch_batch_id
    final_batch = get_fetch_batch(fetch_batch_id)
    batch.status = final_batch.status
    persist_batch_if_enabled(final_batch, request_source=request.request_source)
    return FetchSubmitResult(
        fetch_batch_id=fetch_batch_id,
        fetch_plan_id=plan.fetch_plan_id,
        status=final_batch.status,
        queue_name=plan.queue_name,
        submitted_job_count=len(plan.jobs) - skipped,
        skipped_duplicate_count=skipped,
        callback_registered=bool(request.callback_url),
        producer_ack="accepted_and_persisted_to_queue_contract",
    )


def _jobs_for_batch(fetch_batch_id: str) -> list[FetchJobStatusOut]:
    return [job for job in _JOBS.values() if job.fetch_batch_id == fetch_batch_id]


def _refresh_batch_status(fetch_batch_id: str) -> None:
    batch = _BATCHES[fetch_batch_id]
    jobs = _jobs_for_batch(fetch_batch_id)
    if not jobs:
        batch.status = FetchBatchStatus.SUCCEEDED
    elif any(job.status == FetchJobStatus.LEASED for job in jobs):
        batch.status = FetchBatchStatus.RUNNING
    elif any(job.status == FetchJobStatus.QUEUED for job in jobs):
        batch.status = FetchBatchStatus.QUEUED
    elif any(job.status == FetchJobStatus.FAILED for job in jobs):
        batch.status = FetchBatchStatus.COMPLETED_WITH_ERRORS
    elif all(job.status in {FetchJobStatus.SUCCEEDED, FetchJobStatus.SKIPPED_DUPLICATE} for job in jobs):
        batch.status = FetchBatchStatus.SUCCEEDED
    batch.updated_at = _utcnow()
    if batch.status in {FetchBatchStatus.SUCCEEDED, FetchBatchStatus.COMPLETED_WITH_ERRORS}:
        exists = any(
            event.fetch_batch_id == fetch_batch_id and event.event_type == CallbackEventType.BATCH_COMPLETED
            for event in _CALLBACKS
        )
        if not exists:
            _add_callback(
                fetch_batch_id=fetch_batch_id,
                event_type=CallbackEventType.BATCH_COMPLETED,
                callback_url=batch.callback_url,
                payload={"fetch_batch_id": fetch_batch_id, "status": batch.status.value},
            )
    try:
        persist_batch_if_enabled(_batch_status_out(fetch_batch_id))
    except Exception:
        # Persistence must never crash the liveness path. /source/fetch/persistence/status
        # exposes readiness if the durable backend is misconfigured.
        pass


def _batch_status_out(fetch_batch_id: str) -> FetchBatchStatusOut:
    if fetch_batch_id not in _BATCHES:
        raise KeyError(f"unknown fetch_batch_id: {fetch_batch_id}")
    batch = _BATCHES[fetch_batch_id]
    jobs = _jobs_for_batch(fetch_batch_id)
    return FetchBatchStatusOut(
        fetch_batch_id=batch.fetch_batch_id,
        fetch_plan_id=batch.fetch_plan_id,
        source_table_name=batch.source_table_name,
        trigger_type=batch.trigger_type,
        priority=batch.priority,
        queue_name=batch.queue_name,
        status=batch.status,
        job_count=len(jobs),
        queued_count=sum(1 for job in jobs if job.status == FetchJobStatus.QUEUED),
        leased_count=sum(1 for job in jobs if job.status == FetchJobStatus.LEASED),
        succeeded_count=sum(1 for job in jobs if job.status == FetchJobStatus.SUCCEEDED),
        failed_count=sum(1 for job in jobs if job.status == FetchJobStatus.FAILED),
        skipped_duplicate_count=sum(1 for job in jobs if job.status == FetchJobStatus.SKIPPED_DUPLICATE),
        callback_url=batch.callback_url,
        created_at=batch.created_at,
        updated_at=batch.updated_at,
        operator_notes=batch.operator_notes,
    )


def get_fetch_batch(fetch_batch_id: str) -> FetchBatchStatusOut:
    durable = durable_fetch_batch_if_enabled(fetch_batch_id)
    if durable is not None:
        return durable
    if fetch_batch_id not in _BATCHES:
        raise KeyError(f"unknown fetch_batch_id: {fetch_batch_id}")
    _refresh_batch_status(fetch_batch_id)
    return _batch_status_out(fetch_batch_id)


def get_fetch_job(job_item_id: str) -> FetchJobStatusOut:
    durable = durable_fetch_job_if_enabled(job_item_id)
    if durable is not None:
        return durable
    if job_item_id not in _JOBS:
        raise KeyError(f"unknown job_item_id: {job_item_id}")
    return _JOBS[job_item_id]


def _get_fetch_job_for_update(job_item_id: str) -> FetchJobStatusOut:
    if job_item_id in _JOBS:
        return _JOBS[job_item_id]
    durable = durable_fetch_job_if_enabled(job_item_id)
    if durable is not None:
        _JOBS[job_item_id] = durable
        _REQUEST_HASH_TO_JOB[durable.request_hash] = durable.job_item_id
        return _JOBS[job_item_id]
    raise KeyError(f"unknown job_item_id: {job_item_id}")


def lease_fetch_jobs(request: FetchJobLeaseRequest) -> FetchJobLeaseOut:
    _hydrate_active_state_from_persistence()
    now = _utcnow()
    queue_filter = set(request.queue_names)
    provider_filter = set(request.providers)
    leased: list[FetchJobStatusOut] = []
    inflight_by_key: dict[tuple[Provider, str], int] = {}
    for job in _JOBS.values():
        if job.status == FetchJobStatus.LEASED:
            inflight_by_key[(job.provider, job.api_name)] = inflight_by_key.get((job.provider, job.api_name), 0) + 1
    candidates = sorted(
        [job for job in _JOBS.values() if job.status == FetchJobStatus.QUEUED],
        key=lambda item: (item.priority.value, item.created_at),
    )
    for job in candidates:
        if len(leased) >= request.max_jobs:
            break
        if queue_filter and job.queue_name not in queue_filter:
            continue
        if provider_filter and job.provider not in provider_filter:
            continue
        if job.next_retry_at and job.next_retry_at > now:
            continue
        policy = _policy_for(job.provider, job.api_name)
        key = (job.provider, job.api_name)
        if inflight_by_key.get(key, 0) >= policy.max_concurrency:
            continue
        job.status = FetchJobStatus.LEASED
        job.worker_id = request.worker_id
        job.attempt_count += 1
        job.lease_expires_at = now + timedelta(seconds=request.lease_seconds)
        job.updated_at = now
        inflight_by_key[key] = inflight_by_key.get(key, 0) + 1
        persist_job_if_enabled(job)
        leased.append(job)
        _add_callback(
            fetch_batch_id=job.fetch_batch_id,
            job_item_id=job.job_item_id,
            event_type=CallbackEventType.JOB_LEASED,
            callback_url=_BATCHES[job.fetch_batch_id].callback_url,
            payload={"job_item_id": job.job_item_id, "worker_id": request.worker_id},
        )
    for job in leased:
        _refresh_batch_status(job.fetch_batch_id)
    return FetchJobLeaseOut(worker_id=request.worker_id, leased_count=len(leased), jobs=leased)


def complete_fetch_job(job_item_id: str, request: FetchJobCompleteRequest) -> FetchJobStatusOut:
    job = _get_fetch_job_for_update(job_item_id)
    if job.worker_id and job.worker_id != request.worker_id:
        raise ValueError("worker_id does not own this job lease")
    now = _utcnow()
    job.updated_at = now
    job.lease_expires_at = None
    if request.success:
        job.status = FetchJobStatus.SUCCEEDED
        event_type = CallbackEventType.JOB_SUCCEEDED
        payload = {"job_item_id": job_item_id, "row_count": request.row_count, "request_hash": request.raw_request_hash or job.request_hash}
        existing_trigger = next(
            (
                trigger
                for trigger in list_source_build_triggers(job.fetch_batch_id)
                if trigger.job_item_id == job.job_item_id
                and trigger.source_table_name == job.source_table_name
                and trigger.symbol == job.symbol
                and trigger.trade_date == job.trade_date
                and trigger.status in {"queued", "running", "succeeded"}
            ),
            None,
        )
        if existing_trigger is None:
            trigger = SourceBuildTriggerOut(
                trigger_id=_new_id("source_build_trigger"),
                fetch_batch_id=job.fetch_batch_id,
                job_item_id=job.job_item_id,
                source_table_name=job.source_table_name,
                symbol=job.symbol,
                trade_date=job.trade_date,
                build_scope="symbol_date" if job.symbol and job.trade_date else "batch",
                status="queued",
                quality_check_required=True,
                lineage_required=True,
                created_at=now,
            )
            _BUILD_TRIGGERS.append(trigger)
            persist_build_trigger_if_enabled(trigger)
            _add_callback(
                fetch_batch_id=job.fetch_batch_id,
                job_item_id=job.job_item_id,
                event_type=CallbackEventType.SOURCE_BUILD_TRIGGER_CREATED,
                callback_url=_BATCHES[job.fetch_batch_id].callback_url,
                payload={"trigger_id": trigger.trigger_id, "source_table_name": trigger.source_table_name, "build_scope": trigger.build_scope},
            )
    else:
        job.status = FetchJobStatus.FAILED
        job.last_error_code = request.error_code or "provider_fetch_failed"
        job.last_error_message = request.error_message
        event_type = CallbackEventType.JOB_FAILED
        payload = {"job_item_id": job_item_id, "error_code": job.last_error_code, "error_message": job.last_error_message}
        backup_plans_raw = job.request_params.get("__backup_plans", []) if isinstance(job.request_params, dict) else []
        if backup_plans_raw:
            backup = backup_plans_raw[0]
            backup_request_hash = _job_hash(Provider(backup["provider"]), backup["api_name"], backup["request_params"], backup["raw_table_name"])
            backup_job_id = _new_id("fetch_job")
            _JOBS[backup_job_id] = FetchJobStatusOut(
                job_item_id=backup_job_id,
                fetch_batch_id=job.fetch_batch_id,
                provider=Provider(backup["provider"]),
                api_name=backup["api_name"],
                raw_table_name=backup["raw_table_name"],
                request_params=backup["request_params"],
                request_hash=backup_request_hash,
                source_table_name=job.source_table_name,
                canonical_fields=job.canonical_fields,
                symbol=job.symbol,
                trade_date=job.trade_date,
                priority=job.priority,
                queue_name=job.queue_name,
                status=FetchJobStatus.QUEUED,
                backup_of_job_item_id=job.job_item_id,
                created_at=now,
                updated_at=now,
            )
            persist_job_if_enabled(_JOBS[backup_job_id])
            _add_callback(
                fetch_batch_id=job.fetch_batch_id,
                job_item_id=backup_job_id,
                event_type=CallbackEventType.BACKUP_JOB_QUEUED,
                callback_url=_BATCHES[job.fetch_batch_id].callback_url,
                payload={"backup_job_item_id": backup_job_id, "failed_job_item_id": job.job_item_id},
            )
    persist_job_if_enabled(job)
    _add_callback(
        fetch_batch_id=job.fetch_batch_id,
        job_item_id=job.job_item_id,
        event_type=event_type,
        callback_url=_BATCHES[job.fetch_batch_id].callback_url,
        payload=payload,
    )
    _refresh_batch_status(job.fetch_batch_id)
    return job


def list_callback_events(fetch_batch_id: str | None = None) -> list[FetchCallbackEventOut]:
    rows = _CALLBACKS
    if fetch_batch_id:
        rows = [event for event in rows if event.fetch_batch_id == fetch_batch_id]
    return list(rows)


def list_provider_concurrency_status(provider: Provider | None = None) -> list[ProviderConcurrencyRuntimeStatus]:
    provider_status = {(row.provider, row.api_name): row for row in list_provider_status(provider) if row.api_name}
    rows: list[ProviderConcurrencyRuntimeStatus] = []
    for policy in list_rate_limit_policies(provider):
        key = (policy.provider, policy.api_name)
        queued = sum(1 for job in _JOBS.values() if job.provider == policy.provider and job.api_name == policy.api_name and job.status == FetchJobStatus.QUEUED)
        leased = sum(1 for job in _JOBS.values() if job.provider == policy.provider and job.api_name == policy.api_name and job.status == FetchJobStatus.LEASED)
        succeeded = sum(1 for job in _JOBS.values() if job.provider == policy.provider and job.api_name == policy.api_name and job.status == FetchJobStatus.SUCCEEDED)
        failed = sum(1 for job in _JOBS.values() if job.provider == policy.provider and job.api_name == policy.api_name and job.status == FetchJobStatus.FAILED)
        runtime = provider_status.get(key)
        circuit_state = runtime.circuit_state if runtime else "closed"
        if not policy.enabled:
            runtime_status = "disabled"
        elif circuit_state == "open":
            runtime_status = "circuit_open"
        elif leased >= policy.max_concurrency:
            runtime_status = "busy"
        else:
            runtime_status = "healthy"
        rows.append(
            ProviderConcurrencyRuntimeStatus(
                provider=policy.provider,
                api_name=policy.api_name,
                max_concurrency=policy.max_concurrency,
                current_inflight=leased,
                queued_count=queued,
                leased_count=leased,
                succeeded_count=succeeded,
                failed_count=failed,
                runtime_status=runtime_status,
                circuit_state=circuit_state,
                last_error=runtime.last_error if runtime else None,
            )
        )
    return rows


def queue_persistence_status() -> FetchQueuePersistenceStatusOut:
    summary = queue_persistence_summary()
    durable_counts = durable_queue_counts_if_enabled()
    active_batch_count = (
        durable_counts["active_batch_count"]
        if durable_counts
        else sum(
            1
            for batch in _BATCHES.values()
            if batch.status not in {FetchBatchStatus.SUCCEEDED, FetchBatchStatus.COMPLETED_WITH_ERRORS, FetchBatchStatus.CANCELLED}
            and _jobs_for_batch(batch.fetch_batch_id)
        )
    )
    queued_job_count = durable_counts["queued_job_count"] if durable_counts else sum(1 for job in _JOBS.values() if job.status == FetchJobStatus.QUEUED)
    leased_job_count = durable_counts["leased_job_count"] if durable_counts else sum(1 for job in _JOBS.values() if job.status == FetchJobStatus.LEASED)
    dead_letter_count = durable_counts["dead_letter_count"] if durable_counts else sum(1 for job in _JOBS.values() if job.status == FetchJobStatus.DEAD_LETTER)
    return FetchQueuePersistenceStatusOut(
        backend=summary.backend,  # type: ignore[arg-type]
        durable=summary.durable,
        database_url_configured=summary.database_url_configured,
        driver_available=summary.driver_available,
        ready_for_production_queue=summary.ready_for_production_queue,
        active_batch_count=active_batch_count,
        queued_job_count=queued_job_count,
        leased_job_count=leased_job_count,
        dead_letter_count=dead_letter_count,
        note=summary.note,
    )


def queue_summary() -> FetchQueueSummaryOut:
    durable_summary = durable_queue_summary_if_enabled()
    if durable_summary is not None:
        return FetchQueueSummaryOut(
            rows=[
                FetchQueueSummaryRow(
                    queue_name=queue_name,
                    queued_count=durable_summary.get(queue_name, {}).get("queued_count", 0),
                    leased_count=durable_summary.get(queue_name, {}).get("leased_count", 0),
                    succeeded_count=durable_summary.get(queue_name, {}).get("succeeded_count", 0),
                    failed_count=durable_summary.get(queue_name, {}).get("failed_count", 0),
                    dead_letter_count=durable_summary.get(queue_name, {}).get("dead_letter_count", 0),
                )
                for queue_name in FetchQueueName
            ]
        )
    rows: list[FetchQueueSummaryRow] = []
    for queue_name in FetchQueueName:
        jobs = [job for job in _JOBS.values() if job.queue_name == queue_name]
        rows.append(
            FetchQueueSummaryRow(
                queue_name=queue_name,
                queued_count=sum(1 for job in jobs if job.status == FetchJobStatus.QUEUED),
                leased_count=sum(1 for job in jobs if job.status == FetchJobStatus.LEASED),
                succeeded_count=sum(1 for job in jobs if job.status == FetchJobStatus.SUCCEEDED),
                failed_count=sum(1 for job in jobs if job.status == FetchJobStatus.FAILED),
                dead_letter_count=sum(1 for job in jobs if job.status == FetchJobStatus.DEAD_LETTER),
            )
        )
    return FetchQueueSummaryOut(rows=rows)


def requeue_expired_leases() -> FetchLeaseMaintenanceResult:
    now = _utcnow()
    expired: list[str] = []
    for job in _JOBS.values():
        if job.status == FetchJobStatus.LEASED and job.lease_expires_at and job.lease_expires_at <= now:
            job.status = FetchJobStatus.QUEUED
            job.worker_id = None
            job.lease_expires_at = None
            job.next_retry_at = now
            job.updated_at = now
            expired.append(job.job_item_id)
            persist_job_if_enabled(job)
            _add_callback(
                fetch_batch_id=job.fetch_batch_id,
                job_item_id=job.job_item_id,
                event_type=CallbackEventType.JOB_REQUEUED,
                callback_url=_BATCHES[job.fetch_batch_id].callback_url,
                payload={"job_item_id": job.job_item_id, "reason": "lease_expired"},
            )
            _refresh_batch_status(job.fetch_batch_id)
    return FetchLeaseMaintenanceResult(requeued_count=len(expired), expired_job_ids=expired, checked_at=now)


def heartbeat_fetch_job(job_item_id: str, request: FetchJobHeartbeatRequest) -> FetchJobStatusOut:
    job = _get_fetch_job_for_update(job_item_id)
    if job.status != FetchJobStatus.LEASED:
        raise ValueError("job is not leased")
    if job.worker_id != request.worker_id:
        raise ValueError("worker_id does not own this job lease")
    now = _utcnow()
    job.lease_expires_at = now + timedelta(seconds=request.extend_lease_seconds)
    job.updated_at = now
    persist_job_if_enabled(job)
    _add_callback(
        fetch_batch_id=job.fetch_batch_id,
        job_item_id=job.job_item_id,
        event_type=CallbackEventType.JOB_HEARTBEAT,
        callback_url=_BATCHES[job.fetch_batch_id].callback_url,
        payload={"job_item_id": job.job_item_id, "worker_id": request.worker_id, "worker_note": request.worker_note},
    )
    return job


def cancel_fetch_batch(fetch_batch_id: str, request: FetchBatchCancelRequest) -> FetchBatchStatusOut:
    if fetch_batch_id not in _BATCHES:
        raise KeyError(f"unknown fetch_batch_id: {fetch_batch_id}")
    batch = _BATCHES[fetch_batch_id]
    now = _utcnow()
    cancelled_jobs = 0
    for job in _jobs_for_batch(fetch_batch_id):
        if job.status in {FetchJobStatus.QUEUED, FetchJobStatus.LEASED}:
            job.status = FetchJobStatus.CANCELLED
            job.last_error_code = "batch_cancelled"
            job.last_error_message = request.reason
            job.worker_id = None
            job.lease_expires_at = None
            job.updated_at = now
            cancelled_jobs += 1
            persist_job_if_enabled(job)
            _add_callback(
                fetch_batch_id=fetch_batch_id,
                job_item_id=job.job_item_id,
                event_type=CallbackEventType.JOB_CANCELLED,
                callback_url=batch.callback_url,
                payload={"job_item_id": job.job_item_id, "reason": request.reason, "operator": request.operator},
            )
    batch.status = FetchBatchStatus.CANCELLED
    batch.updated_at = now
    batch.operator_notes.append(f"cancelled_by={request.operator}; reason={request.reason}; cancelled_jobs={cancelled_jobs}")
    persist_batch_if_enabled(_batch_status_out(fetch_batch_id))
    return _batch_status_out(fetch_batch_id)


def list_dead_letter_jobs() -> list[FetchJobStatusOut]:
    # Dead-letter state is explicit for jobs moved there by maintenance and also
    # derived for failed jobs with no backup and exhausted attempts.
    dead: list[FetchJobStatusOut] = []
    for job in _JOBS.values():
        policy = _policy_for(job.provider, job.api_name)
        if job.status == FetchJobStatus.DEAD_LETTER:
            dead.append(job)
        elif job.status == FetchJobStatus.FAILED and job.attempt_count > policy.max_retry_count:
            dead.append(job)
    return dead


def mark_exhausted_failed_jobs_dead_letter() -> int:
    moved = 0
    for job in _JOBS.values():
        if job.status != FetchJobStatus.FAILED:
            continue
        policy = _policy_for(job.provider, job.api_name)
        if job.attempt_count <= policy.max_retry_count:
            continue
        backup_plans_raw = job.request_params.get("__backup_plans", []) if isinstance(job.request_params, dict) else []
        backup_exists = any(candidate.backup_of_job_item_id == job.job_item_id for candidate in _JOBS.values())
        if backup_plans_raw and backup_exists:
            continue
        job.status = FetchJobStatus.DEAD_LETTER
        job.updated_at = _utcnow()
        moved += 1
        persist_job_if_enabled(job)
        _add_callback(
            fetch_batch_id=job.fetch_batch_id,
            job_item_id=job.job_item_id,
            event_type=CallbackEventType.JOB_FAILED,
            callback_url=_BATCHES[job.fetch_batch_id].callback_url,
            payload={"job_item_id": job.job_item_id, "reason": "dead_letter_exhausted_retries"},
        )
    return moved


def list_source_build_triggers(fetch_batch_id: str | None = None) -> list[SourceBuildTriggerOut]:
    durable = durable_build_triggers_if_enabled(fetch_batch_id)
    if durable is not None:
        return durable
    rows = _BUILD_TRIGGERS
    if fetch_batch_id:
        rows = [row for row in rows if row.fetch_batch_id == fetch_batch_id]
    return list(rows)


def dispatch_callback_events(request: FetchCallbackDispatchRequest) -> FetchCallbackDispatchResult:
    # DS-5 implements an outbox contract. Real callback delivery is intentionally
    # behind a dry_run flag until downstream services expose stable callback APIs.
    pending = [event for event in _CALLBACKS if event.delivery_status == "pending"][: request.max_events]
    delivered = 0
    skipped = 0
    failed = 0
    for event in pending:
        if not event.callback_url:
            event.delivery_status = "skipped_no_callback"
            skipped += 1
        elif request.dry_run:
            # Dry-run proves the outbox is queryable without creating cross-service side effects.
            skipped += 1
        else:  # pragma: no cover - network side effect; validated in integration env
            try:
                import httpx

                with httpx.Client(timeout=3.0) as client:
                    response = client.post(event.callback_url, json=event.payload)
                    response.raise_for_status()
                event.delivery_status = "delivered"
                delivered += 1
            except Exception as exc:
                event.delivery_status = "failed"
                event.payload = dict(event.payload)
                event.payload["delivery_error"] = str(exc)
                failed += 1
        persist_callback_if_enabled(event)
    return FetchCallbackDispatchResult(
        attempted_count=len(pending),
        delivered_count=delivered,
        skipped_count=skipped,
        failed_count=failed,
        dry_run=request.dry_run,
    )
