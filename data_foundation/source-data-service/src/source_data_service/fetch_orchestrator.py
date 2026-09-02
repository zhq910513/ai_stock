from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from itertools import count
from uuid import uuid4
from typing import Any

from source_data_service.adapters.base import stable_json_hash
from source_data_service.gap_detector import build_repair_plan
from source_data_service.fetch_persistence import (
    durable_callback_events_if_enabled,
    build_trigger_exists_if_enabled,
    cancel_expired_daily_jobs_if_enabled,
    durable_build_triggers_if_enabled,
    durable_fetch_batch_if_enabled,
    durable_fetch_batch_id_by_idempotency_key_if_enabled,
    durable_fetch_job_if_enabled,
    durable_queue_counts_if_enabled,
    durable_queue_summary_if_enabled,
    find_existing_job_item_id_if_enabled,
    find_existing_job_item_ids_if_enabled,
    load_active_state_if_enabled,
    persist_batch_if_enabled,
    persist_build_trigger_if_enabled,
    persist_callback_if_enabled,
    persist_idempotency_key_if_enabled,
    persist_job_if_enabled,
    market_today as persistence_market_today,
    queue_persistence_summary,
    requeue_expired_leases_if_enabled,
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
    FetchUniverseScope,
    Provider,
    ProviderConcurrencyRuntimeStatus,
    ProviderRateLimitPolicy,
    SourceBuildTriggerOut,
    SourceGapRequest,
)
from source_data_service.provider_registry import get_api_spec, list_source_requirements
from source_data_service.provider_runtime import list_provider_status
from source_data_service.symbol_rules import is_a_share_symbol, normalize_symbol


# Provider/API-level policies are deliberately conservative for free public data.
# They protect the source-data-service from self-inflicted provider bans and keep
# release-gate-critical fetches ahead of historical backfills.
_RATE_LIMIT_POLICIES: dict[tuple[Provider, str], ProviderRateLimitPolicy] = {}
_FULL_A_SHARE_SOURCE_ROW_LIMIT = 20000
_SCHEDULER_LIFECYCLE_FANOUT_JOB_LIMIT = 200
_LIFECYCLE_MAINTENANCE_INTERVAL_SECONDS = 60
_LAST_LIFECYCLE_MAINTENANCE_AT: datetime | None = None

_DEFAULT_PROVIDER_LIMITS: dict[Provider, tuple[int, int, str]] = {
    Provider.BAOSTOCK: (4, 120, "BaoStock is free but should be protected by low symbol-level concurrency."),
    Provider.AKSHARE: (3, 60, "AKShare public webpage adapters can be rate-limited; keep concurrency low."),
    Provider.TUSHARE: (2, 60, "Tushare depends on token/integral frequency; respect per-account limits."),
    Provider.EASTMONEY: (4, 90, "EastMoney public endpoints should use bounded parallelism."),
    Provider.TENCENT: (3, 90, "Tencent quote endpoints are public; use bounded parallelism."),
    Provider.SOHU: (2, 60, "Sohu public historical K-line endpoint should use low bounded concurrency."),
    Provider.BAIDU: (2, 30, "Baidu Finance public news feed should use low concurrency for stable evidence capture."),
    Provider.SINA: (2, 60, "Sina quote endpoints are public; use bounded parallelism."),
    Provider.THS: (1, 30, "THS public endpoints must be serialized; login cookies are allowed only for paid_limit_up_probability through controlled credentials."),
    Provider.COINGECKO: (1, 20, "CoinGecko public API is context-only and quota-sensitive; keep probes serialized."),
    Provider.YAHOO: (1, 30, "Yahoo chart public endpoint is context-only; keep bounded request rate."),
    Provider.JIN10: (1, 20, "Jin10 public flash endpoint uses static public headers; serialize context probes."),
    Provider.CNINFO: (2, 30, "Announcement APIs favor stability over speed."),
    Provider.INTERNAL: (8, 600, "Internal build tasks can run with higher local concurrency."),
}
_API_POLICY_OVERRIDES: dict[tuple[Provider, str], tuple[int, int, str]] = {
    (Provider.AKSHARE, "stock_fund_flow_individual_realtime"): (1, 30, "Moneyflow endpoint is unstable under concurrency; serialize it."),
    (Provider.AKSHARE, "stock_zh_a_disclosure_report_cninfo"): (1, 20, "Disclosure endpoint should be serialized to avoid anti-crawling failures."),
    (Provider.BAIDU, "finance_news_feed"): (1, 20, "Baidu Finance news feed is a public evidence source; serialize probes and repairs."),
    (Provider.THS, "limit_up_pool"): (1, 20, "THS limit-up pool is the preferred limit-event fact source; serialize to avoid public endpoint throttling."),
    (Provider.THS, "paid_limit_up_probability"): (1, 12, "THS paid probability is credentialed and batch-critical; serialize and keep cookie values outside request params/logs."),
    (Provider.JIN10, "public_flash"): (1, 15, "Jin10 public flash should remain low-frequency research context."),
    (Provider.BAOSTOCK, "query_history_k_data_plus_daily_raw"): (12, 300, "Symbol-level history fetch can use bounded parallelism for daily repair bursts."),
    (Provider.BAOSTOCK, "query_history_k_data_plus_daily_qfq"): (12, 300, "Adjusted history fetch can use bounded parallelism for daily repair bursts."),
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
_SOURCE_BUILD_ALIASES_PARAM = "__source_build_aliases"
_ORCHESTRATION_CONTEXT_PARAM = "__orchestration_context"
_ACTIVE_DUPLICATE_ALIAS_STATUSES = {
    FetchJobStatus.QUEUED,
    FetchJobStatus.LEASED,
}
_PRIORITY_RANK: dict[FetchPriority, int] = {
    FetchPriority.P0_URGENT_RELEASE: 0,
    FetchPriority.P1_NORMAL_INGEST: 1,
    FetchPriority.P2_BACKFILL: 2,
    FetchPriority.RESEARCH: 3,
}
_QUEUE_RANK: dict[FetchQueueName, int] = {
    FetchQueueName.URGENT_RELEASE_GATE_QUEUE: 0,
    FetchQueueName.REPAIR_QUEUE: 1,
    FetchQueueName.NORMAL_DAILY_INGEST_QUEUE: 2,
    FetchQueueName.RESEARCH_QUEUE: 3,
    FetchQueueName.BACKFILL_QUEUE: 4,
    FetchQueueName.PROVIDER_PROBE_QUEUE: 5,
}
_TERMINAL_DUPLICATE_REPAIR_STATUSES = {
    FetchJobStatus.FAILED,
    FetchJobStatus.CANCELLED,
    FetchJobStatus.DEAD_LETTER,
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _orchestration_context(request: FetchPlanRequest) -> dict[str, Any]:
    context = request.orchestration_context if isinstance(request.orchestration_context, dict) else {}
    return {str(key): value for key, value in context.items() if str(key).strip()}


def _with_orchestration_context(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    request_params = dict(params)
    if context:
        request_params[_ORCHESTRATION_CONTEXT_PARAM] = dict(context)
    return request_params


def _hydrate_active_state_from_persistence(
    *,
    queue_names: list[FetchQueueName] | None = None,
    providers: list[Provider] | None = None,
) -> None:
    batches, jobs = load_active_state_if_enabled(
        queue_names=[item.value for item in queue_names] if queue_names else None,
        providers=[item.value for item in providers] if providers else None,
    )
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
        if job.fetch_batch_id not in _BATCHES:
            _ensure_batch_record(job.fetch_batch_id)
        existing_job = _JOBS.get(job.job_item_id)
        if existing_job is None or job.updated_at >= existing_job.updated_at:
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


def _strategy_for(request: FetchPlanRequest, job_count: int, symbols: list[str | None]) -> FetchStrategy:
    symbol_count = len([symbol for symbol in symbols if symbol])
    if request.prefer_batch and symbol_count == 0:
        return FetchStrategy.FULL_MARKET_BATCH
    if request.prefer_batch and request.trade_date and job_count == 1:
        return FetchStrategy.API_BATCH_BY_DATE
    if symbol_count > 1 or job_count > 1:
        return FetchStrategy.SYMBOL_PARALLEL
    return FetchStrategy.SINGLE_REQUEST


def _source_date(request: FetchPlanRequest) -> date | None:
    return request.trade_date or request.start_date or request.end_date


def _source_date_text(request: FetchPlanRequest) -> str | None:
    value = _source_date(request)
    return value.isoformat() if value else None


def _truthy(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value).strip().lower()
    if text in {"1", "true", "t", "yes", "y", "normal", "tradable", "trading", "listed", "l", "正常", "交易"}:
        return True
    if text in {"0", "false", "f", "no", "n", "suspended", "halted", "delisted", "d", "停牌", "暂停", "退市"}:
        return False
    return None


def _symbol_from_source_row(row: Any) -> str | None:
    symbol = getattr(row, "symbol", None)
    if symbol:
        return normalize_symbol(symbol)
    values = getattr(row, "values", None) or {}
    for key in ("symbol", "code", "ts_code", "stock_code"):
        value = values.get(key)
        if value:
            normalized = normalize_symbol(value)
            if normalized:
                return normalized
    return None


def _source_universe_row_usable(row: Any) -> bool:
    values = getattr(row, "values", None) or {}
    is_tradable = _truthy(values.get("is_tradable"))
    is_suspended = _truthy(values.get("is_suspended"))
    is_delisting_risk = _truthy(values.get("is_delisting_risk"))
    trade_status_flag = _truthy(values.get("trade_status"))
    trade_status = str(values.get("trade_status") or "").strip().lower()
    if is_tradable is False or is_suspended is True or is_delisting_risk is True or trade_status_flag is False:
        return False
    if trade_status in {"suspended", "halted", "delisted", "停牌", "暂停", "退市"}:
        return False
    return True


def _stock_master_row_usable(row: Any, as_of_date: date | None) -> bool:
    values = getattr(row, "values", None) or {}
    list_status = str(values.get("list_status") or "").strip().lower()
    if list_status in {"d", "delisted", "退市", "终止上市"}:
        return False
    delist_date = values.get("delist_date")
    if as_of_date and delist_date:
        try:
            if date.fromisoformat(str(delist_date)[:10]) <= as_of_date:
                return False
        except ValueError:
            return False
    return True


def _list_source_rows(source_table_name: str, trade_date: str | None = None, *, limit: int | None = 1000) -> list[Any]:
    from source_data_service.source_repository import list_source_rows

    return list_source_rows(source_table_name=source_table_name, trade_date=trade_date, limit=limit)


def _load_full_a_share_symbols(request: FetchPlanRequest) -> list[str]:
    source_date = _source_date(request)
    source_date_text = _source_date_text(request)
    if source_date_text is None:
        raise ValueError("full_a_share fetch requires trade_date or date range")

    universe_rows = _list_source_rows(
        source_table_name="source.stock_universe_daily_v1",
        trade_date=source_date_text,
        limit=_FULL_A_SHARE_SOURCE_ROW_LIMIT,
    )
    symbols = sorted(
        {
            symbol
            for row in universe_rows
            if _source_universe_row_usable(row)
            for symbol in [_symbol_from_source_row(row)]
            if symbol and is_a_share_symbol(symbol)
        }
    )
    if symbols:
        return symbols

    master_rows = _list_source_rows(source_table_name="source.stock_master_v1", limit=_FULL_A_SHARE_SOURCE_ROW_LIMIT)
    symbols = sorted(
        {
            symbol
            for row in master_rows
            if _stock_master_row_usable(row, source_date)
            for symbol in [_symbol_from_source_row(row)]
            if symbol and is_a_share_symbol(symbol)
        }
    )
    if symbols:
        return symbols

    raise ValueError("full_a_share universe has no source symbols; fetch source.stock_universe_daily_v1 first")


def _symbols_for_request(request: FetchPlanRequest) -> list[str | None]:
    if request.symbols:
        return list(request.symbols)
    if request.universe_scope == FetchUniverseScope.STAGE_CANDIDATES:
        raise ValueError("stage_candidates fetch requires explicit symbols from a model stage")
    if request.universe_scope == FetchUniverseScope.FULL_A_SHARE:
        if request.source_table_name in {
            "source.limit_event_v1",
            "source.stock_master_v1",
            "source.stock_universe_daily_v1",
        }:
            return [None]
        return _load_full_a_share_symbols(request)
    return [None]


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

    symbols = _symbols_for_request(request)
    queue_name = _queue_for(request.priority, request.trigger_type)
    grouped: dict[str, FetchPlannedJob] = {}
    field_by_hash: dict[str, set[str]] = {}
    backup_plan_by_hash: dict[str, dict[str, FetchBackupPlan]] = {}
    backup_fields_by_hash: dict[str, dict[str, set[str]]] = {}
    orchestration_context = _orchestration_context(request)

    for requirement in requirements:
        for symbol in symbols:
            gap_request = _gap_request_for(request, requirement.canonical_field_name, symbol)
            repair = build_repair_plan(gap_request)
            primary = repair.primary_repair
            primary_params = _with_orchestration_context(primary.params, orchestration_context)
            request_hash = _job_hash(primary.provider, primary.api_name, primary_params, primary.raw_table_name)
            policy = _policy_for(primary.provider, primary.api_name)
            if request_hash not in grouped:
                grouped[request_hash] = FetchPlannedJob(
                    provider=primary.provider,
                    api_name=primary.api_name,
                    raw_table_name=primary.raw_table_name,
                    request_params=primary_params,
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
                    backup_plans=[],
                )
                field_by_hash[request_hash] = set()
                backup_plan_by_hash[request_hash] = {}
                backup_fields_by_hash[request_hash] = {}
            field_by_hash[request_hash].add(requirement.canonical_field_name)
            for backup in repair.backup_repairs:
                backup_params = _with_orchestration_context(backup.params, orchestration_context)
                backup_plan = FetchBackupPlan(
                    provider=backup.provider,
                    api_name=backup.api_name,
                    raw_table_name=backup.raw_table_name,
                    request_params=backup_params,
                    reason=backup.reason,
                )
                backup_request_hash = _job_hash(
                    backup_plan.provider,
                    backup_plan.api_name,
                    backup_plan.request_params,
                    backup_plan.raw_table_name,
                )
                backup_plan_by_hash[request_hash][backup_request_hash] = backup_plan
                backup_fields_by_hash[request_hash].setdefault(backup_request_hash, set()).add(
                    requirement.canonical_field_name
                )

    jobs: list[FetchPlannedJob] = []
    for request_hash, job in grouped.items():
        job.canonical_fields = sorted(field_by_hash[request_hash])
        job.backup_plans = [
            backup_plan_by_hash[request_hash][backup_hash]
            for backup_hash in sorted(
                backup_plan_by_hash[request_hash],
                key=lambda item: (
                    -len(backup_fields_by_hash[request_hash].get(item, set())),
                    backup_plan_by_hash[request_hash][item].provider.value,
                    backup_plan_by_hash[request_hash][item].api_name,
                ),
            )
        ]
        jobs.append(job)

    policies_by_key: dict[tuple[Provider, str], ProviderRateLimitPolicy] = {}
    for job in jobs:
        policies_by_key[(job.provider, job.api_name)] = _policy_for(job.provider, job.api_name)
        for backup in job.backup_plans:
            policies_by_key[(backup.provider, backup.api_name)] = _policy_for(backup.provider, backup.api_name)
    max_parallel = max((policy.max_concurrency for policy in policies_by_key.values()), default=1)
    estimated_runtime_seconds = round((len(jobs) / max_parallel) * 1.5, 2)
    fetch_plan_id = "plan_" + stable_json_hash(request.model_dump(mode="json"))[:16]
    strategy = _strategy_for(request, len(jobs), symbols)
    operator_notes = [
        "Producer-consumer fetch plan only; model services must not call provider APIs directly.",
        "Primary raw-interface jobs are queued first; backup jobs are created only when primary jobs fail.",
        "Every raw fetch must pass quality validation before source build and source_lineage writes.",
    ]
    if strategy == FetchStrategy.SYMBOL_PARALLEL:
        operator_notes.append("Symbol-level requests must obey provider/API concurrency limits; never launch unbounded threads.")
    if request.trigger_type == FetchTriggerType.MODEL_RELEASE_PREFLIGHT:
        operator_notes.append("Release preflight P0 fetches must not be delayed behind backfill or research queues.")
    if request.universe_scope == FetchUniverseScope.FULL_A_SHARE:
        operator_notes.append("full_a_share scope is resolved from source.stock_universe_daily_v1/source.stock_master_v1; no sample symbol fallback is allowed.")
    if request.universe_scope == FetchUniverseScope.STAGE_CANDIDATES:
        operator_notes.append("stage_candidates scope must be supplied by upstream model-stage candidates; source-data-service does not invent candidates.")

    return FetchPlanOut(
        fetch_plan_id=fetch_plan_id,
        source_table_name=request.source_table_name,
        trigger_type=request.trigger_type,
        priority=request.priority,
        strategy=strategy,
        queue_name=queue_name,
        job_count=len(jobs),
        deduplicated_job_count=len(jobs),
        symbols_count=len([symbol for symbol in symbols if symbol]),
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


def _ensure_source_build_trigger(
    job: FetchJobStatusOut,
    *,
    fetch_batch_id: str,
    source_table_name: str,
    planned: FetchPlannedJob | None = None,
    symbol: str | None = None,
    trade_date: date | None = None,
) -> SourceBuildTriggerOut | None:
    trigger_symbol = planned.symbol if planned is not None else symbol if symbol is not None else job.symbol
    trigger_trade_date = planned.trade_date if planned is not None else trade_date if trade_date is not None else job.trade_date
    durable_existing = build_trigger_exists_if_enabled(
        fetch_batch_id=fetch_batch_id,
        job_item_id=job.job_item_id,
        source_table_name=source_table_name,
        symbol=trigger_symbol,
        trade_date=trigger_trade_date,
    )
    if durable_existing is True:
        return None
    if durable_existing is None:
        existing_trigger = next(
            (
                trigger
                for trigger in list_source_build_triggers()
                if trigger.fetch_batch_id == fetch_batch_id
                and trigger.job_item_id == job.job_item_id
                and trigger.source_table_name == source_table_name
                and trigger.symbol == trigger_symbol
                and trigger.trade_date == trigger_trade_date
                and trigger.status in {"queued", "running", "succeeded"}
            ),
            None,
        )
        if existing_trigger is not None:
            return None
    now = _utcnow()
    trigger = SourceBuildTriggerOut(
        trigger_id=_new_id("source_build_trigger"),
        fetch_batch_id=fetch_batch_id,
        job_item_id=job.job_item_id,
        source_table_name=source_table_name,
        symbol=trigger_symbol,
        trade_date=trigger_trade_date,
        build_scope="symbol_date" if trigger_symbol and trigger_trade_date else "batch",
        status="queued",
        quality_check_required=True,
        lineage_required=True,
        created_at=now,
    )
    _BUILD_TRIGGERS.append(trigger)
    persist_build_trigger_if_enabled(trigger)
    callback_url = _BATCHES[fetch_batch_id].callback_url if fetch_batch_id in _BATCHES else None
    _add_callback(
        fetch_batch_id=fetch_batch_id,
        job_item_id=job.job_item_id,
        event_type=CallbackEventType.SOURCE_BUILD_TRIGGER_CREATED,
        callback_url=callback_url,
        payload={"trigger_id": trigger.trigger_id, "source_table_name": trigger.source_table_name, "build_scope": trigger.build_scope},
    )
    return trigger


def _duplicate_idempotency_submit_result(fetch_batch_id: str) -> FetchSubmitResult:
    existing = get_fetch_batch(fetch_batch_id)
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


def _existing_idempotent_batch_id(idempotency_key: str | None) -> str | None:
    if not idempotency_key:
        return None
    existing_batch_id = _IDEMPOTENCY_TO_BATCH.get(idempotency_key)
    if existing_batch_id:
        return existing_batch_id
    existing_batch_id = durable_fetch_batch_id_by_idempotency_key_if_enabled(idempotency_key)
    if existing_batch_id:
        _IDEMPOTENCY_TO_BATCH[idempotency_key] = existing_batch_id
    return existing_batch_id


def submit_fetch_batch(request: FetchSubmitRequest) -> FetchSubmitResult:
    existing_batch_id = _existing_idempotent_batch_id(request.idempotency_key)
    if existing_batch_id:
        return _duplicate_idempotency_submit_result(existing_batch_id)
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
    if request.idempotency_key:
        idempotency_request_hash = stable_json_hash(request.model_dump(mode="json", exclude={"auto_start"}))
        persisted_batch_id = persist_idempotency_key_if_enabled(
            idempotency_key=request.idempotency_key,
            fetch_batch_id=fetch_batch_id,
            request_source=request.request_source,
            request_hash=idempotency_request_hash,
        ) or fetch_batch_id
        _IDEMPOTENCY_TO_BATCH[request.idempotency_key] = persisted_batch_id
        if persisted_batch_id != fetch_batch_id:
            return _duplicate_idempotency_submit_result(persisted_batch_id)
    skipped = 0
    submitted = 0
    durable_existing_jobs = find_existing_job_item_ids_if_enabled(
        [
            (planned.provider, planned.api_name, planned.raw_table_name, planned.request_hash)
            for planned in plan.jobs
        ]
    )
    for planned in plan.jobs:
        existing_job_id = _REQUEST_HASH_TO_JOB.get(planned.request_hash)
        durable_key = (planned.provider.value, planned.api_name, planned.raw_table_name, planned.request_hash)
        if not existing_job_id and durable_existing_jobs is not None:
            existing_job_id = durable_existing_jobs.get(durable_key)
        if not existing_job_id and durable_existing_jobs is None:
            existing_job_id = find_existing_job_item_id_if_enabled(
                planned.provider,
                planned.api_name,
                planned.raw_table_name,
                planned.request_hash,
            )
        if existing_job_id:
            _REQUEST_HASH_TO_JOB[planned.request_hash] = existing_job_id
            try:
                existing_job = _get_fetch_job_for_update(existing_job_id)
            except Exception:
                existing_job = None
            if existing_job and existing_job.status in {FetchJobStatus.SUCCEEDED, FetchJobStatus.SKIPPED_DUPLICATE}:
                duplicate_context = _planned_duplicate_job_context(existing_job, planned)
                if _requires_backup_after_unusable_success(duplicate_context):
                    backup_job = _queue_backup_job(
                        duplicate_context,
                        fetch_batch_id=fetch_batch_id,
                        now=now,
                        reason="duplicate_success_without_raw_hash",
                    )
                    if backup_job is not None:
                        submitted += 1
                        continue
                    _queue_planned_repair_attempt(
                        existing_job,
                        planned,
                        fetch_batch_id=fetch_batch_id,
                        now=now,
                        reason="duplicate_success_without_reusable_source_output",
                    )
                    submitted += 1
                    continue
                if _requires_repair_after_missing_source_output(existing_job, planned):
                    _queue_planned_repair_attempt(
                        existing_job,
                        planned,
                        fetch_batch_id=fetch_batch_id,
                        now=now,
                        reason="duplicate_success_without_target_source_row",
                    )
                    submitted += 1
                    continue
                else:
                    _ensure_source_build_trigger(
                        existing_job,
                        fetch_batch_id=fetch_batch_id,
                        source_table_name=planned.source_table_name,
                        planned=planned,
                    )
            elif existing_job and existing_job.status in _ACTIVE_DUPLICATE_ALIAS_STATUSES:
                _register_source_build_alias(
                    existing_job,
                    fetch_batch_id=fetch_batch_id,
                    source_table_name=planned.source_table_name,
                    symbol=planned.symbol,
                    trade_date=planned.trade_date,
                    canonical_fields=planned.canonical_fields,
                )
                _promote_queued_duplicate_if_higher_priority(
                    existing_job,
                    planned,
                    fetch_batch_id=fetch_batch_id,
                    now=now,
                )
            elif existing_job and existing_job.status in _TERMINAL_DUPLICATE_REPAIR_STATUSES:
                terminal_status = existing_job.status
                duplicate_context = _planned_duplicate_job_context(existing_job, planned)
                backup_job = _queue_backup_job(
                    duplicate_context,
                    fetch_batch_id=fetch_batch_id,
                    now=now,
                    reason=f"duplicate_{terminal_status.value}_existing_job",
                )
                if backup_job is not None:
                    submitted += 1
                    continue
                if not _backup_plans_for(duplicate_context):
                    if existing_job.backup_of_job_item_id and existing_job.source_table_name == planned.source_table_name:
                        skipped += 1
                        continue
                    _queue_planned_repair_attempt(
                        existing_job,
                        planned,
                        fetch_batch_id=fetch_batch_id,
                        now=now,
                        reason=f"duplicate_{terminal_status.value}_existing_job",
                    )
                    submitted += 1
                    continue
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
        submitted += 1
    if submitted == 0:
        batch.status = FetchBatchStatus.SUCCEEDED
        batch.updated_at = _utcnow()
        persist_batch_if_enabled(_batch_status_out(fetch_batch_id), request_source=request.request_source)
    _add_callback(
        fetch_batch_id=fetch_batch_id,
        event_type=CallbackEventType.BATCH_SUBMITTED,
        callback_url=request.callback_url,
        payload={"fetch_batch_id": fetch_batch_id, "submitted_job_count": submitted, "skipped_duplicate_count": skipped},
    )
    final_batch = get_fetch_batch(fetch_batch_id)
    batch.status = final_batch.status
    persist_batch_if_enabled(final_batch, request_source=request.request_source)
    return FetchSubmitResult(
        fetch_batch_id=fetch_batch_id,
        fetch_plan_id=plan.fetch_plan_id,
        status=final_batch.status,
        queue_name=plan.queue_name,
        submitted_job_count=submitted,
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
        return
    elif any(job.status == FetchJobStatus.LEASED for job in jobs):
        batch.status = FetchBatchStatus.RUNNING
    elif any(job.status == FetchJobStatus.QUEUED for job in jobs):
        batch.status = FetchBatchStatus.QUEUED
    elif any(job.status == FetchJobStatus.FAILED for job in jobs):
        batch.status = FetchBatchStatus.COMPLETED_WITH_ERRORS
    elif all(job.status == FetchJobStatus.CANCELLED for job in jobs):
        batch.status = FetchBatchStatus.CANCELLED
    elif all(job.status in {FetchJobStatus.SUCCEEDED, FetchJobStatus.SKIPPED_DUPLICATE, FetchJobStatus.CANCELLED} for job in jobs):
        batch.status = FetchBatchStatus.COMPLETED_WITH_ERRORS if any(job.status == FetchJobStatus.CANCELLED for job in jobs) else FetchBatchStatus.SUCCEEDED
    batch.updated_at = _utcnow()
    if batch.status in {FetchBatchStatus.SUCCEEDED, FetchBatchStatus.COMPLETED_WITH_ERRORS, FetchBatchStatus.CANCELLED}:
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
    existing = _JOBS.get(job_item_id)
    durable = durable_fetch_job_if_enabled(job_item_id)
    if durable is not None:
        if existing is None or durable.updated_at > existing.updated_at:
            _JOBS[job_item_id] = durable
            _REQUEST_HASH_TO_JOB[durable.request_hash] = durable.job_item_id
            return _JOBS[job_item_id]
    if job_item_id in _JOBS:
        return _JOBS[job_item_id]
    raise KeyError(f"unknown job_item_id: {job_item_id}")


def _callback_url_for_batch(fetch_batch_id: str) -> str | None:
    batch = _BATCHES.get(fetch_batch_id)
    return batch.callback_url if batch else None


def _ensure_batch_record(fetch_batch_id: str) -> BatchRecord | None:
    if fetch_batch_id in _BATCHES:
        return _BATCHES[fetch_batch_id]
    durable = durable_fetch_batch_if_enabled(fetch_batch_id)
    if durable is None:
        return None
    _BATCHES[fetch_batch_id] = BatchRecord(
        fetch_batch_id=durable.fetch_batch_id,
        fetch_plan_id=durable.fetch_plan_id,
        source_table_name=durable.source_table_name,
        trigger_type=durable.trigger_type,
        priority=durable.priority,
        queue_name=durable.queue_name,
        callback_url=durable.callback_url,
        status=durable.status,
        created_at=durable.created_at,
        updated_at=durable.updated_at,
        operator_notes=durable.operator_notes,
    )
    return _BATCHES[fetch_batch_id]


def _backup_plans_for(job: FetchJobStatusOut) -> list[dict]:
    if not isinstance(job.request_params, dict):
        return []
    plans = job.request_params.get("__backup_plans", [])
    return plans if isinstance(plans, list) else []


def _requires_backup_after_unusable_success(job: FetchJobStatusOut) -> bool:
    if job.status not in {FetchJobStatus.SUCCEEDED, FetchJobStatus.SKIPPED_DUPLICATE}:
        return False
    if not _backup_plans_for(job):
        return False
    return _job_missing_raw_audit_hashes(job)


def _requires_repair_after_missing_source_output(existing_job: FetchJobStatusOut, planned: FetchPlannedJob) -> bool:
    if not planned.symbol or not planned.trade_date:
        return False
    try:
        rows = _list_source_rows(
            source_table_name=planned.source_table_name,
            symbol=planned.symbol,
            trade_date=planned.trade_date.isoformat(),
            limit=1,
        )
    except Exception:
        return False
    if rows:
        return False
    trigger_exists = build_trigger_exists_if_enabled(
        fetch_batch_id=existing_job.fetch_batch_id,
        job_item_id=existing_job.job_item_id,
        source_table_name=planned.source_table_name,
        symbol=planned.symbol,
        trade_date=planned.trade_date,
    )
    if trigger_exists is True:
        return False
    if trigger_exists is None:
        for trigger in list_source_build_triggers(fetch_batch_id=existing_job.fetch_batch_id):
            if (
                trigger.job_item_id == existing_job.job_item_id
                and trigger.source_table_name == planned.source_table_name
                and trigger.symbol == planned.symbol
                and trigger.trade_date == planned.trade_date
                and trigger.status in {"queued", "running", "succeeded"}
            ):
                return False
    return True


def _job_missing_raw_audit_hashes(job: FetchJobStatusOut) -> bool:
    return not job.raw_request_hash or not job.raw_response_schema_hash


def _planned_duplicate_job_context(existing_job: FetchJobStatusOut, planned: FetchPlannedJob) -> FetchJobStatusOut:
    request_params = dict(existing_job.request_params) if isinstance(existing_job.request_params, dict) else {}
    request_params["__backup_plans"] = [item.model_dump(mode="json") for item in planned.backup_plans]
    return existing_job.model_copy(
        update={
            "request_params": request_params,
            "source_table_name": planned.source_table_name,
            "canonical_fields": planned.canonical_fields,
            "symbol": planned.symbol,
            "trade_date": planned.trade_date,
            "priority": planned.priority,
            "queue_name": planned.queue_name,
        }
    )


def _request_params_for_planned_job(planned: FetchPlannedJob) -> dict[str, Any]:
    request_params = dict(planned.request_params)
    if planned.backup_plans:
        request_params["__backup_plans"] = [item.model_dump(mode="json") for item in planned.backup_plans]
    return request_params


def _queue_planned_repair_attempt(
    existing_job: FetchJobStatusOut,
    planned: FetchPlannedJob,
    *,
    fetch_batch_id: str,
    now: datetime,
    reason: str,
) -> FetchJobStatusOut:
    repair_job_id = _new_id("fetch_job")
    request_params = _request_params_for_planned_job(planned)
    request_params["__repair_attempt_id"] = repair_job_id
    repair_request_hash = _job_hash(planned.provider, planned.api_name, request_params, planned.raw_table_name)
    _REQUEST_HASH_TO_JOB[repair_request_hash] = repair_job_id
    repair_job = FetchJobStatusOut(
        job_item_id=repair_job_id,
        fetch_batch_id=fetch_batch_id,
        provider=planned.provider,
        api_name=planned.api_name,
        raw_table_name=planned.raw_table_name,
        request_params=request_params,
        request_hash=repair_request_hash,
        source_table_name=planned.source_table_name,
        canonical_fields=planned.canonical_fields,
        symbol=planned.symbol,
        trade_date=planned.trade_date,
        priority=planned.priority,
        queue_name=planned.queue_name,
        status=FetchJobStatus.QUEUED,
        backup_of_job_item_id=existing_job.job_item_id,
        created_at=now,
        updated_at=now,
    )
    _JOBS[repair_job_id] = repair_job
    persist_job_if_enabled(repair_job)
    _add_callback(
        fetch_batch_id=fetch_batch_id,
        job_item_id=repair_job_id,
        event_type=CallbackEventType.JOB_REQUEUED,
        callback_url=_callback_url_for_batch(fetch_batch_id),
        payload={
            "job_item_id": repair_job_id,
            "reason": reason,
            "repair_attempt_for_job_item_id": existing_job.job_item_id,
            "existing_fetch_batch_id": existing_job.fetch_batch_id,
            "source_table_name": planned.source_table_name,
        },
    )
    if fetch_batch_id in _BATCHES:
        _refresh_batch_status(fetch_batch_id)
    return repair_job


def _alias_trade_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _register_source_build_alias(
    job: FetchJobStatusOut,
    *,
    fetch_batch_id: str,
    source_table_name: str,
    symbol: str | None = None,
    trade_date: date | None = None,
    canonical_fields: list[str] | None = None,
) -> None:
    if not fetch_batch_id or not source_table_name:
        return
    request_params = dict(job.request_params) if isinstance(job.request_params, dict) else {}
    aliases = request_params.get(_SOURCE_BUILD_ALIASES_PARAM, [])
    if not isinstance(aliases, list):
        aliases = []
    alias_symbol = symbol if symbol is not None else job.symbol
    alias_trade_date = trade_date if trade_date is not None else job.trade_date
    alias_fields = canonical_fields if canonical_fields is not None else job.canonical_fields
    alias: dict[str, Any] = {"fetch_batch_id": fetch_batch_id, "source_table_name": source_table_name}
    if alias_symbol:
        alias["symbol"] = alias_symbol
    if alias_trade_date:
        alias["trade_date"] = alias_trade_date.isoformat()
    if alias_fields:
        alias["canonical_fields"] = list(alias_fields)
    if any(
        item.get("fetch_batch_id") == fetch_batch_id
        and item.get("source_table_name") == source_table_name
        and item.get("symbol") == alias.get("symbol")
        and item.get("trade_date") == alias.get("trade_date")
        for item in aliases
        if isinstance(item, dict)
    ):
        return
    request_params[_SOURCE_BUILD_ALIASES_PARAM] = [*aliases, alias]
    job.request_params = request_params
    persist_job_if_enabled(job)


def _ensure_source_build_alias_triggers(job: FetchJobStatusOut) -> None:
    if not isinstance(job.request_params, dict):
        return
    aliases = job.request_params.get(_SOURCE_BUILD_ALIASES_PARAM, [])
    if not isinstance(aliases, list):
        return
    for alias in aliases:
        if not isinstance(alias, dict):
            continue
        fetch_batch_id = alias.get("fetch_batch_id")
        source_table_name = alias.get("source_table_name")
        if not isinstance(fetch_batch_id, str) or not isinstance(source_table_name, str):
            continue
        alias_symbol = alias.get("symbol") if isinstance(alias.get("symbol"), str) else None
        _ensure_batch_record(fetch_batch_id)
        _ensure_source_build_trigger(
            job,
            fetch_batch_id=fetch_batch_id,
            source_table_name=source_table_name,
            symbol=alias_symbol,
            trade_date=_alias_trade_date(alias.get("trade_date")),
        )


def _promote_queued_duplicate_if_higher_priority(
    job: FetchJobStatusOut,
    planned: FetchPlannedJob,
    *,
    fetch_batch_id: str,
    now: datetime,
) -> None:
    if job.status != FetchJobStatus.QUEUED:
        return
    priority_rank = _PRIORITY_RANK.get(job.priority, 99)
    planned_priority_rank = _PRIORITY_RANK.get(planned.priority, 99)
    queue_rank = _QUEUE_RANK.get(job.queue_name, 99)
    planned_queue_rank = _QUEUE_RANK.get(planned.queue_name, 99)
    if planned_priority_rank >= priority_rank and planned_queue_rank >= queue_rank:
        return

    previous_priority = job.priority
    previous_queue = job.queue_name
    if planned_priority_rank < priority_rank:
        job.priority = planned.priority
    if planned_queue_rank < queue_rank:
        job.queue_name = planned.queue_name
    job.next_retry_at = None
    job.updated_at = now
    persist_job_if_enabled(job)
    _add_callback(
        fetch_batch_id=job.fetch_batch_id,
        job_item_id=job.job_item_id,
        event_type=CallbackEventType.JOB_REQUEUED,
        callback_url=_callback_url_for_batch(job.fetch_batch_id),
        payload={
            "reason": "active_duplicate_promoted_for_higher_priority_alias",
            "alias_fetch_batch_id": fetch_batch_id,
            "alias_source_table_name": planned.source_table_name,
            "previous_priority": previous_priority.value,
            "new_priority": job.priority.value,
            "previous_queue_name": previous_queue.value,
            "new_queue_name": job.queue_name.value,
        },
    )


def _requeue_existing_backup_job(
    backup_job: FetchJobStatusOut,
    *,
    now: datetime,
    reason: str,
) -> FetchJobStatusOut:
    previous_status = backup_job.status
    _ensure_batch_record(backup_job.fetch_batch_id)
    backup_job.status = FetchJobStatus.QUEUED
    backup_job.worker_id = None
    backup_job.lease_expires_at = None
    backup_job.next_retry_at = now
    backup_job.updated_at = now
    persist_job_if_enabled(backup_job)
    _add_callback(
        fetch_batch_id=backup_job.fetch_batch_id,
        job_item_id=backup_job.job_item_id,
        event_type=CallbackEventType.JOB_REQUEUED,
        callback_url=_callback_url_for_batch(backup_job.fetch_batch_id),
        payload={
            "job_item_id": backup_job.job_item_id,
            "reason": reason,
            "requeued_from_status": previous_status.value,
        },
    )
    if backup_job.fetch_batch_id in _BATCHES:
        _refresh_batch_status(backup_job.fetch_batch_id)
    return backup_job


def _job_orchestration_context(job: FetchJobStatusOut) -> dict[str, Any]:
    params = job.request_params if isinstance(job.request_params, dict) else {}
    context = params.get(_ORCHESTRATION_CONTEXT_PARAM)
    return {str(key): value for key, value in context.items()} if isinstance(context, dict) else {}


def _scheduler_lifecycle_fanout_block_reason(
    job: FetchJobStatusOut,
    *,
    candidate_count: int,
) -> str | None:
    context = _job_orchestration_context(job)
    if str(context.get("request_source") or "") != "scheduler-service":
        return None
    if candidate_count <= _SCHEDULER_LIFECYCLE_FANOUT_JOB_LIMIT:
        return None
    schedule_code = str(context.get("schedule_code") or "unknown_schedule")
    lifecycle_expires_at = str(context.get("lifecycle_expires_at") or "")
    return (
        f"scheduler lifecycle fanout blocked for {schedule_code}: "
        f"{candidate_count} backup jobs exceeds limit {_SCHEDULER_LIFECYCLE_FANOUT_JOB_LIMIT}; "
        f"lifecycle_expires_at={lifecycle_expires_at or '<missing>'}; submit formal repair/backfill"
    )


def _queue_stock_universe_daily_fanout_backup_jobs(
    job: FetchJobStatusOut,
    *,
    fetch_batch_id: str,
    now: datetime,
    reason: str,
) -> int:
    if not (
        job.source_table_name == "source.stock_universe_daily_v1"
        and job.provider == Provider.BAOSTOCK
        and job.api_name == "query_all_stock"
        and job.symbol is None
        and job.trade_date is not None
    ):
        return 0

    universe_request = FetchPlanRequest(
        source_table_name="source.daily_bar_v1",
        canonical_fields=[],
        universe_scope=FetchUniverseScope.FULL_A_SHARE,
        trade_date=job.trade_date,
        trigger_type=FetchTriggerType.DATA_INSPECTION_GAP_REPAIR,
        priority=job.priority,
        request_source="source.stock_universe_daily_v1.fanout_backup",
        dry_run=True,
    )
    try:
        symbols = _load_full_a_share_symbols(universe_request)
    except Exception:
        return 0
    blocked_reason = _scheduler_lifecycle_fanout_block_reason(job, candidate_count=len(symbols))
    if blocked_reason:
        _add_callback(
            fetch_batch_id=fetch_batch_id,
            job_item_id=job.job_item_id,
            event_type=CallbackEventType.BACKUP_JOB_QUEUED,
            callback_url=_callback_url_for_batch(fetch_batch_id),
            payload={
                "fanout_backup_blocked": True,
                "source_table_name": job.source_table_name,
                "candidate_count": len(symbols),
                "limit": _SCHEDULER_LIFECYCLE_FANOUT_JOB_LIMIT,
                "reason": blocked_reason,
            },
        )
        return 0

    canonical_fields = sorted(set(job.canonical_fields or ["is_tradable", "trade_status"]))
    planned_by_hash: dict[str, tuple[Any, str]] = {}
    fields_by_hash: dict[str, set[str]] = {}
    for symbol in symbols:
        for field in canonical_fields:
            try:
                repair = build_repair_plan(
                    SourceGapRequest(
                        source_table_name=job.source_table_name,
                        canonical_field_name=field,
                        symbol=symbol,
                        trade_date=job.trade_date,
                    )
                )
            except Exception:
                continue
            for backup in repair.backup_repairs:
                backup_request_hash = _job_hash(
                    backup.provider,
                    backup.api_name,
                    backup.params,
                    backup.raw_table_name,
                )
                planned_by_hash.setdefault(backup_request_hash, (backup, symbol))
                fields_by_hash.setdefault(backup_request_hash, set()).add(field)

    queued = 0
    existing_hashes = {item.request_hash for item in _jobs_for_batch(fetch_batch_id)}
    for backup_request_hash in sorted(planned_by_hash):
        if backup_request_hash in existing_hashes:
            continue
        backup, symbol = planned_by_hash[backup_request_hash]
        backup_job_id = _new_id("fetch_job")
        backup_job = FetchJobStatusOut(
            job_item_id=backup_job_id,
            fetch_batch_id=fetch_batch_id,
            provider=backup.provider,
            api_name=backup.api_name,
            raw_table_name=backup.raw_table_name,
            request_params=dict(backup.params),
            request_hash=backup_request_hash,
            source_table_name=job.source_table_name,
            canonical_fields=sorted(fields_by_hash.get(backup_request_hash, set())) or canonical_fields,
            symbol=symbol,
            trade_date=job.trade_date,
            priority=job.priority,
            queue_name=job.queue_name,
            status=FetchJobStatus.QUEUED,
            backup_of_job_item_id=job.job_item_id,
            created_at=now,
            updated_at=now,
        )
        _REQUEST_HASH_TO_JOB[backup_request_hash] = backup_job_id
        _JOBS[backup_job_id] = backup_job
        persist_job_if_enabled(backup_job)
        _add_callback(
            fetch_batch_id=fetch_batch_id,
            job_item_id=backup_job_id,
            event_type=CallbackEventType.BACKUP_JOB_QUEUED,
            callback_url=_callback_url_for_batch(fetch_batch_id),
            payload={
                "backup_job_item_id": backup_job_id,
                "failed_job_item_id": job.job_item_id,
                "reason": reason,
                "fanout_backup": True,
                "source_table_name": job.source_table_name,
                "symbol": symbol,
            },
        )
        queued += 1
    if queued and fetch_batch_id in _BATCHES:
        _refresh_batch_status(fetch_batch_id)
    return queued


def _queue_backup_job(
    job: FetchJobStatusOut,
    *,
    fetch_batch_id: str,
    now: datetime,
    reason: str,
) -> FetchJobStatusOut | None:
    backup_plans_raw = _backup_plans_for(job)
    if not backup_plans_raw:
        return None
    backup = backup_plans_raw[0]
    remaining_backup_plans = backup_plans_raw[1:]
    backup_request_hash = _job_hash(
        Provider(backup["provider"]),
        backup["api_name"],
        backup["request_params"],
        backup["raw_table_name"],
    )
    backup_job_id = _REQUEST_HASH_TO_JOB.get(backup_request_hash) or find_existing_job_item_id_if_enabled(
        Provider(backup["provider"]),
        backup["api_name"],
        backup["raw_table_name"],
        backup_request_hash,
    )
    if backup_job_id:
        _REQUEST_HASH_TO_JOB[backup_request_hash] = backup_job_id
        try:
            backup_job = _get_fetch_job_for_update(backup_job_id)
        except Exception:
            return None
        if remaining_backup_plans:
            backup_job.request_params = dict(backup_job.request_params)
            backup_job.request_params["__backup_plans"] = remaining_backup_plans
            persist_job_if_enabled(backup_job)
        if backup_job.status in {FetchJobStatus.QUEUED, FetchJobStatus.LEASED}:
            _register_source_build_alias(
                backup_job,
                fetch_batch_id=fetch_batch_id,
                source_table_name=job.source_table_name,
                symbol=job.symbol,
                trade_date=job.trade_date,
                canonical_fields=job.canonical_fields,
            )
            return None
        if backup_job.status in {FetchJobStatus.SUCCEEDED, FetchJobStatus.SKIPPED_DUPLICATE} and not _job_missing_raw_audit_hashes(backup_job):
            _ensure_source_build_trigger(
                backup_job,
                fetch_batch_id=fetch_batch_id,
                source_table_name=job.source_table_name,
                symbol=job.symbol,
                trade_date=job.trade_date,
            )
            return None
        if backup_job.status in {
            FetchJobStatus.SUCCEEDED,
            FetchJobStatus.FAILED,
            FetchJobStatus.SKIPPED_DUPLICATE,
            FetchJobStatus.CANCELLED,
            FetchJobStatus.DEAD_LETTER,
        }:
            if (
                backup_job.status in {FetchJobStatus.FAILED, FetchJobStatus.CANCELLED, FetchJobStatus.DEAD_LETTER}
                and backup_job.backup_of_job_item_id
                and backup_job.source_table_name == job.source_table_name
            ):
                return None
            requeued = _requeue_existing_backup_job(
                backup_job,
                now=now,
                reason=f"{reason}:existing_backup_requeued",
            )
            _register_source_build_alias(
                requeued,
                fetch_batch_id=fetch_batch_id,
                source_table_name=job.source_table_name,
                symbol=job.symbol,
                trade_date=job.trade_date,
                canonical_fields=job.canonical_fields,
            )
            _add_callback(
                fetch_batch_id=fetch_batch_id,
                job_item_id=backup_job.job_item_id,
                event_type=CallbackEventType.BACKUP_JOB_QUEUED,
                callback_url=_callback_url_for_batch(fetch_batch_id),
                payload={
                    "backup_job_item_id": backup_job.job_item_id,
                    "failed_job_item_id": job.job_item_id,
                    "reason": reason,
                    "reused_existing_job": True,
                    "existing_fetch_batch_id": backup_job.fetch_batch_id,
                },
            )
            return requeued

    backup_job_id = _new_id("fetch_job")
    _REQUEST_HASH_TO_JOB[backup_request_hash] = backup_job_id
    backup_request_params = dict(backup["request_params"])
    if remaining_backup_plans:
        backup_request_params["__backup_plans"] = remaining_backup_plans
    _JOBS[backup_job_id] = FetchJobStatusOut(
        job_item_id=backup_job_id,
        fetch_batch_id=fetch_batch_id,
        provider=Provider(backup["provider"]),
        api_name=backup["api_name"],
        raw_table_name=backup["raw_table_name"],
        request_params=backup_request_params,
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
        fetch_batch_id=fetch_batch_id,
        job_item_id=backup_job_id,
        event_type=CallbackEventType.BACKUP_JOB_QUEUED,
        callback_url=_callback_url_for_batch(fetch_batch_id),
        payload={"backup_job_item_id": backup_job_id, "failed_job_item_id": job.job_item_id, "reason": reason},
    )
    return _JOBS[backup_job_id]


def _lease_candidate_base_key(job: FetchJobStatusOut) -> tuple[str, int, str, str, str]:
    trade_date_rank = -job.trade_date.toordinal() if job.trade_date is not None else 0
    return (job.priority.value, trade_date_rank, job.queue_name.value, job.provider.value, job.api_name)


def _lease_candidates_in_fair_order(jobs: list[FetchJobStatusOut]) -> list[FetchJobStatusOut]:
    buckets: dict[tuple[str, int, str, str, str], dict[str, list[FetchJobStatusOut]]] = {}
    for job in sorted(jobs, key=lambda item: (_lease_candidate_base_key(item), item.source_table_name, item.created_at)):
        base_key = _lease_candidate_base_key(job)
        source_key = job.source_table_name or ""
        buckets.setdefault(base_key, {}).setdefault(source_key, []).append(job)

    ordered: list[FetchJobStatusOut] = []
    for base_key in sorted(buckets):
        source_groups = buckets[base_key]
        source_keys = sorted(source_groups)
        while any(source_groups[source_key] for source_key in source_keys):
            for source_key in source_keys:
                group = source_groups[source_key]
                if group:
                    ordered.append(group.pop(0))
    return ordered


def lease_fetch_jobs(request: FetchJobLeaseRequest) -> FetchJobLeaseOut:
    queue_filter = set(request.queue_names)
    provider_filter = set(request.providers)
    _hydrate_active_state_from_persistence(
        queue_names=list(queue_filter) if queue_filter else None,
        providers=list(provider_filter) if provider_filter else None,
    )
    lease_maintenance = requeue_expired_leases()
    lifecycle_cancelled = _cancel_expired_daily_lifecycle_jobs()
    if lease_maintenance.requeued_count or lifecycle_cancelled:
        _hydrate_active_state_from_persistence(
            queue_names=list(queue_filter) if queue_filter else None,
            providers=list(provider_filter) if provider_filter else None,
        )
    now = _utcnow()
    leased: list[FetchJobStatusOut] = []
    inflight_by_key: dict[tuple[Provider, str], int] = {}
    for job in _JOBS.values():
        if job.status == FetchJobStatus.LEASED:
            inflight_by_key[(job.provider, job.api_name)] = inflight_by_key.get((job.provider, job.api_name), 0) + 1
    candidates = _lease_candidates_in_fair_order([job for job in _JOBS.values() if job.status == FetchJobStatus.QUEUED])
    for job in candidates:
        if len(leased) >= request.max_jobs:
            break
        if queue_filter and job.queue_name not in queue_filter:
            continue
        if provider_filter and job.provider not in provider_filter:
            continue
        if job.next_retry_at and job.next_retry_at > now:
            continue
        batch = _ensure_batch_record(job.fetch_batch_id)
        if batch is None:
            job.status = FetchJobStatus.DEAD_LETTER
            job.last_error_code = "fetch_batch_missing"
            job.last_error_message = f"fetch batch {job.fetch_batch_id} is missing while leasing"
            job.updated_at = now
            persist_job_if_enabled(job)
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
            callback_url=_callback_url_for_batch(job.fetch_batch_id),
            payload={"job_item_id": job.job_item_id, "worker_id": request.worker_id},
        )
    for job in leased:
        _refresh_batch_status(job.fetch_batch_id)
    return FetchJobLeaseOut(worker_id=request.worker_id, leased_count=len(leased), jobs=leased)


def complete_fetch_job(job_item_id: str, request: FetchJobCompleteRequest) -> FetchJobStatusOut:
    job = _get_fetch_job_for_update(job_item_id)
    if job.status == FetchJobStatus.CANCELLED:
        raise ValueError("job is cancelled")
    if job.worker_id and job.worker_id != request.worker_id:
        raise ValueError("worker_id does not own this job lease")
    now = _utcnow()
    job.updated_at = now
    job.worker_id = None
    job.lease_expires_at = None
    if request.success:
        job.status = FetchJobStatus.SUCCEEDED
        job.raw_request_hash = request.raw_request_hash
        job.raw_response_schema_hash = request.raw_response_schema_hash
        event_type = CallbackEventType.JOB_SUCCEEDED
        payload = {
            "job_item_id": job_item_id,
            "row_count": request.row_count,
            "request_hash": request.raw_request_hash or job.request_hash,
            "raw_request_hash": request.raw_request_hash,
            "raw_response_schema_hash": request.raw_response_schema_hash,
        }
        _ensure_source_build_trigger(job, fetch_batch_id=job.fetch_batch_id, source_table_name=job.source_table_name)
        _ensure_source_build_alias_triggers(job)
    else:
        job.status = FetchJobStatus.FAILED
        job.last_error_code = request.error_code or "provider_fetch_failed"
        job.last_error_message = request.error_message
        event_type = CallbackEventType.JOB_FAILED
        payload = {"job_item_id": job_item_id, "error_code": job.last_error_code, "error_message": job.last_error_message}
        backup_job = _queue_backup_job(job, fetch_batch_id=job.fetch_batch_id, now=now, reason=job.last_error_code)
        if backup_job is None and not _backup_plans_for(job):
            _queue_stock_universe_daily_fanout_backup_jobs(
                job,
                fetch_batch_id=job.fetch_batch_id,
                now=now,
                reason=job.last_error_code,
            )
    persist_job_if_enabled(job)
    _add_callback(
        fetch_batch_id=job.fetch_batch_id,
        job_item_id=job.job_item_id,
        event_type=event_type,
        callback_url=_callback_url_for_batch(job.fetch_batch_id),
        payload=payload,
    )
    _refresh_batch_status(job.fetch_batch_id)
    return job


def list_callback_events(fetch_batch_id: str | None = None) -> list[FetchCallbackEventOut]:
    durable = durable_callback_events_if_enabled(fetch_batch_id)
    if durable is not None:
        return durable
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


def _job_lifecycle_expires_at(job: FetchJobStatusOut) -> datetime | None:
    if not isinstance(job.request_params, dict):
        return None
    context = job.request_params.get(_ORCHESTRATION_CONTEXT_PARAM)
    if not isinstance(context, dict) or context.get("request_source") != "scheduler-service":
        return None
    value = context.get("lifecycle_expires_at")
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_daily_lifecycle_expirable(job: FetchJobStatusOut, market_day: date, now: datetime) -> bool:
    if job.status not in {FetchJobStatus.QUEUED, FetchJobStatus.LEASED}:
        return False
    lifecycle_expires_at = _job_lifecycle_expires_at(job)
    if lifecycle_expires_at is not None and lifecycle_expires_at <= now:
        return True
    return (
        job.trade_date is not None
        and job.trade_date < market_day
        and job.queue_name in {FetchQueueName.NORMAL_DAILY_INGEST_QUEUE, FetchQueueName.RESEARCH_QUEUE}
        and job.priority in {FetchPriority.P1_NORMAL_INGEST, FetchPriority.RESEARCH}
    )


def _cancel_expired_daily_lifecycle_jobs(*, force: bool = False) -> list[FetchJobStatusOut]:
    global _LAST_LIFECYCLE_MAINTENANCE_AT
    now = _utcnow()
    if (
        not force
        and _LAST_LIFECYCLE_MAINTENANCE_AT is not None
        and (now - _LAST_LIFECYCLE_MAINTENANCE_AT).total_seconds() < _LIFECYCLE_MAINTENANCE_INTERVAL_SECONDS
    ):
        return []
    _LAST_LIFECYCLE_MAINTENANCE_AT = now
    market_day = persistence_market_today(now)
    durable_cancelled = cancel_expired_daily_jobs_if_enabled(now=now, market_day=market_day)
    if durable_cancelled is not None:
        cancelled: list[FetchJobStatusOut] = []
        for job in durable_cancelled:
            _ensure_batch_record(job.fetch_batch_id)
            _JOBS[job.job_item_id] = job
            _REQUEST_HASH_TO_JOB[job.request_hash] = job.job_item_id
            cancelled.append(job)
        for fetch_batch_id in sorted({job.fetch_batch_id for job in cancelled if job.fetch_batch_id in _BATCHES}):
            _refresh_batch_status(fetch_batch_id)
        return cancelled

    cancelled = []
    for job in _JOBS.values():
        if not _is_daily_lifecycle_expirable(job, market_day, now):
            continue
        job.status = FetchJobStatus.CANCELLED
        job.worker_id = None
        job.lease_expires_at = None
        job.next_retry_at = None
        job.last_error_code = "expired_lifecycle"
        job.last_error_message = "daily lifecycle expired before worker completion; submit formal repair/backfill to rebuild"
        job.updated_at = now
        persist_job_if_enabled(job)
        cancelled.append(job)
    for fetch_batch_id in sorted({job.fetch_batch_id for job in cancelled if job.fetch_batch_id in _BATCHES}):
        _refresh_batch_status(fetch_batch_id)
    return cancelled


def requeue_expired_leases() -> FetchLeaseMaintenanceResult:
    now = _utcnow()
    durable_requeued = requeue_expired_leases_if_enabled(now)
    if durable_requeued is not None:
        expired: list[str] = []
        for job in durable_requeued:
            _ensure_batch_record(job.fetch_batch_id)
            _JOBS[job.job_item_id] = job
            _REQUEST_HASH_TO_JOB[job.request_hash] = job.job_item_id
            expired.append(job.job_item_id)
            _add_callback(
                fetch_batch_id=job.fetch_batch_id,
                job_item_id=job.job_item_id,
                event_type=CallbackEventType.JOB_REQUEUED,
                callback_url=_callback_url_for_batch(job.fetch_batch_id),
                payload={"job_item_id": job.job_item_id, "reason": "lease_expired"},
            )
            if job.fetch_batch_id in _BATCHES:
                _refresh_batch_status(job.fetch_batch_id)
        return FetchLeaseMaintenanceResult(requeued_count=len(expired), expired_job_ids=expired, checked_at=now)

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
                callback_url=_callback_url_for_batch(job.fetch_batch_id),
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
    durable_pending = durable_callback_events_if_enabled(pending_only=True, limit=request.max_events)
    pending = durable_pending if durable_pending is not None else [event for event in _CALLBACKS if event.delivery_status == "pending"][: request.max_events]
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
