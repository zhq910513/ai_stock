from __future__ import annotations

from source_data_service.fetch_orchestrator import complete_fetch_job, heartbeat_fetch_job, lease_fetch_jobs, list_source_build_triggers
from source_data_service.models import (
    FetchJobCompleteRequest,
    FetchJobHeartbeatRequest,
    FetchJobLeaseRequest,
    FetchPriority,
    FetchWorkerRunOnceRequest,
    FetchWorkerRunOnceResult,
    SourceBuildWorkerRunOnceRequest,
)
from source_data_service.fetch_persistence import persist_worker_heartbeat_if_enabled
from source_data_service.provider_runtime import execute_provider_fetch
from source_data_service.source_repository import ingest_raw_fetch_result, run_source_build_worker_once


def _source_build_trigger_budget(max_jobs: int) -> int:
    return max(10, min(100, max_jobs * 10))


def run_worker_once(request: FetchWorkerRunOnceRequest) -> FetchWorkerRunOnceResult:
    """Run one bounded producer/consumer worker cycle.

    This endpoint is intentionally small and deterministic: a worker leases jobs,
    performs the exact provider/raw-interface request, then completes the job.
    It supports dry_run_provider=True so production can validate queue semantics
    without calling external providers. Real provider calls should be enabled only
    after API credentials, rate limits and provider readiness are confirmed.
    """

    lease = lease_fetch_jobs(
        FetchJobLeaseRequest(
            worker_id=request.worker_id,
            max_jobs=request.max_jobs,
            providers=request.providers,
            queue_names=request.queue_names,
            lease_seconds=request.lease_seconds,
        )
    )
    persist_worker_heartbeat_if_enabled(
        worker_id=request.worker_id,
        queue_names=[queue.value for queue in request.queue_names] if request.queue_names else [],
        providers=[provider.value for provider in request.providers] if request.providers else [],
        status="busy" if lease.jobs else "alive",
        note="worker_cycle_start",
        current_job_item_id=lease.jobs[0].job_item_id if lease.jobs else None,
    )
    succeeded = 0
    failed = 0
    errors: list[str] = []
    before_triggers = len(list_source_build_triggers())
    processed_job_ids: list[str] = []
    if not lease.jobs and not request.dry_run_provider:
        build = run_source_build_worker_once(
            SourceBuildWorkerRunOnceRequest(
                worker_id=f"{request.worker_id}-source-build-idle",
                max_triggers=_source_build_trigger_budget(request.max_jobs),
                dry_run=False,
            )
        )
        for result_item in build.results:
            errors.extend(result_item.errors)
            errors.extend(result_item.warnings)
    for job in lease.jobs:
        processed_job_ids.append(job.job_item_id)
        persist_worker_heartbeat_if_enabled(
            worker_id=request.worker_id,
            queue_names=[queue.value for queue in request.queue_names] if request.queue_names else [],
            providers=[provider.value for provider in request.providers] if request.providers else [],
            current_job_item_id=job.job_item_id,
            status="busy",
            note=f"processing:{job.job_item_id}",
        )
        try:
            # Backup plans are orchestration metadata, not provider parameters.
            params = dict(job.request_params)
            params.pop("__backup_plans", None)
            heartbeat_fetch_job(
                job.job_item_id,
                FetchJobHeartbeatRequest(
                    worker_id=request.worker_id,
                    extend_lease_seconds=max(request.lease_seconds, 60),
                    worker_note="provider_fetch_start",
                ),
            )
            result = execute_provider_fetch(
                provider=job.provider,
                api_name=job.api_name,
                params=params,
                dry_run=request.dry_run_provider,
            )
            is_success = result.error is None or request.complete_on_structured_provider_error
            completion_error = result.error
            has_backup_plan = bool(job.request_params.get("__backup_plans")) if isinstance(job.request_params, dict) else False
            requires_rows = job.priority in {FetchPriority.P0_URGENT_RELEASE, FetchPriority.P1_NORMAL_INGEST}
            if is_success and not request.dry_run_provider and result.row_count == 0 and (has_backup_plan or requires_rows):
                is_success = False
                completion_error = "provider returned zero rows; backup required"
                errors.append(f"{job.job_item_id}: {completion_error}")
            if is_success and not request.dry_run_provider:
                ingest = ingest_raw_fetch_result(result)
                if ingest.rejected_row_count or ingest.raw_write_status == "rejected":
                    is_success = False
                    completion_error = f"raw ingest rejected: {'; '.join(ingest.warnings)}"
                    errors.append(f"{job.job_item_id}: {completion_error}")
            complete_fetch_job(
                job.job_item_id,
                FetchJobCompleteRequest(
                    worker_id=request.worker_id,
                    success=is_success,
                    row_count=result.row_count,
                    error_code=None if is_success else "provider_structured_error",
                    error_message=None if is_success else completion_error,
                    raw_request_hash=result.request_hash,
                    raw_response_schema_hash=result.response_schema_hash,
                ),
            )
            if is_success:
                succeeded += 1
                if not request.dry_run_provider:
                    build = run_source_build_worker_once(
                        SourceBuildWorkerRunOnceRequest(
                            worker_id=f"{request.worker_id}-source-build",
                            max_triggers=10,
                            dry_run=False,
                        )
                    )
                    for result_item in build.results:
                        errors.extend(result_item.errors)
                        errors.extend(result_item.warnings)
            else:
                failed += 1
                errors.append(f"{job.job_item_id}: {completion_error}")
        except Exception as exc:  # pragma: no cover - defensive path
            failed += 1
            errors.append(f"{job.job_item_id}: {exc}")
            try:
                complete_fetch_job(
                    job.job_item_id,
                    FetchJobCompleteRequest(
                        worker_id=request.worker_id,
                        success=False,
                        error_code="worker_exception",
                        error_message=str(exc),
                    ),
                )
            except Exception as complete_exc:
                errors.append(f"{job.job_item_id}: failed to complete after exception: {complete_exc}")
        finally:
            persist_worker_heartbeat_if_enabled(
                worker_id=request.worker_id,
                queue_names=[queue.value for queue in request.queue_names] if request.queue_names else [],
                providers=[provider.value for provider in request.providers] if request.providers else [],
                current_job_item_id=job.job_item_id,
                status="alive" if not lease.jobs else "busy",
                note=f"completed:{job.job_item_id}",
            )
    after_triggers = len(list_source_build_triggers())
    persist_worker_heartbeat_if_enabled(
        worker_id=request.worker_id,
        queue_names=[queue.value for queue in request.queue_names] if request.queue_names else [],
        providers=[provider.value for provider in request.providers] if request.providers else [],
        current_job_item_id=None,
        status="alive",
        note="worker_cycle_complete",
    )
    return FetchWorkerRunOnceResult(
        worker_id=request.worker_id,
        leased_count=lease.leased_count,
        succeeded_count=succeeded,
        failed_count=failed,
        generated_build_trigger_count=max(0, after_triggers - before_triggers),
        job_ids=processed_job_ids,
        errors=errors,
    )
