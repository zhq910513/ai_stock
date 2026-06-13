from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


MODEL_OWNED_FIELD_FRAGMENTS = (
    "score",
    "signal",
    "buy_point",
    "recommend",
    "outcome",
    "label",
    "success",
    "failure",
    "ambush",
    "hot_",
    "memory_",
)


class Provider(str, Enum):
    BAOSTOCK = "baostock"
    AKSHARE = "akshare"
    TUSHARE = "tushare"
    EASTMONEY = "eastmoney"
    TENCENT = "tencent"
    SINA = "sina"
    CNINFO = "cninfo"
    INTERNAL = "internal"


class SourceLayer(str, Enum):
    RAW_INTERFACE = "raw_interface"
    SOURCE_BUILD = "source_build"
    SOURCE_CANONICAL = "source"


class RequiredLevel(str, Enum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    RESEARCH_ONLY = "research_only"


class QualityStatus(str, Enum):
    USABLE = "usable"
    RESEARCH_ONLY = "research_only"
    GAP = "gap"
    SUSPECT = "suspect"
    STALE = "stale"
    REJECTED = "rejected"


class ProviderApiSpec(BaseModel):
    """One provider API contract.

    The raw table is part of the public data-source contract: one provider API
    writes to one raw interface table. Canonical source tables are built later
    from these raw tables through mapping, quality checks and lineage.
    """

    provider: Provider
    api_name: str
    api_function: str
    raw_table_name: str
    is_free: bool = True
    requires_token: bool = False
    frequency: str
    request_template: dict[str, Any]
    request_required_fields: list[str] = Field(default_factory=list)
    request_optional_fields: list[str] = Field(default_factory=list)
    response_fields: list[str]
    canonical_targets: list[str]
    rate_limit_note: str | None = None
    timeout_seconds: float = 12.0
    enabled: bool = True
    priority: int = 100
    supports_repair: bool = True

    @model_validator(mode="after")
    def reject_model_owned_raw_tables(self) -> "ProviderApiSpec":
        lowered = self.raw_table_name.lower()
        if any(fragment in lowered for fragment in ("decision_", "signal", "score")):
            raise ValueError("raw interface table must not contain model-owned semantics")
        return self


class FieldMappingSpec(BaseModel):
    provider: Provider
    api_name: str
    raw_table_name: str
    raw_field_name: str
    canonical_table_name: str
    canonical_field_name: str
    unit_transform: str | None = None
    dtype_transform: str | None = None
    null_policy: str = "preserve_null"
    mapping_status: Literal["active", "research_only", "pending"] = "active"

    @model_validator(mode="after")
    def reject_model_owned_canonical_fields(self) -> "FieldMappingSpec":
        field = self.canonical_field_name.lower()
        if any(fragment in field for fragment in MODEL_OWNED_FIELD_FRAGMENTS):
            raise ValueError(f"canonical source field has model-owned semantics: {self.canonical_field_name}")
        return self


class SourceTableRequirement(BaseModel):
    """Canonical source field requirement used by source readiness and repairs."""

    source_table_name: str
    canonical_field_name: str
    required_level: RequiredLevel
    used_by_models: list[str]
    required_for_online: bool
    required_for_backtest: bool
    minimum_coverage_rate: float = Field(ge=0, le=1)
    primary_provider: Provider
    primary_api_name: str
    backup_provider: Provider | None = None
    backup_api_name: str | None = None
    repair_raw_table_name: str
    description: str

    @model_validator(mode="after")
    def validate_backup_and_no_model_fields(self) -> "SourceTableRequirement":
        field = self.canonical_field_name.lower()
        if any(fragment in field for fragment in MODEL_OWNED_FIELD_FRAGMENTS):
            raise ValueError(f"source requirement field has model-owned semantics: {self.canonical_field_name}")
        if self.required_level in {RequiredLevel.P0, RequiredLevel.P1} and not self.backup_provider:
            raise ValueError(f"{self.source_table_name}.{self.canonical_field_name} requires backup provider")
        return self


class SourceFieldContract(BaseModel):
    """Human/audit readable contract for one canonical source field.

    This is intentionally more explicit than SourceTableRequirement. It documents
    the field's financial meaning, unit, adjustment policy, time semantics and
    repair chain so future Codex iterations cannot silently add ambiguous fields.
    """

    source_table_name: str
    canonical_field_name: str
    required_level: RequiredLevel
    data_type: str
    unit: str | None = None
    price_adjustment_mode: Literal["raw", "qfq", "hfq", "not_price", "mixed"] = "not_price"
    time_semantics: str
    used_by_models: list[str]
    primary_provider: Provider
    primary_api_name: str
    backup_provider: Provider | None = None
    backup_api_name: str | None = None
    raw_table_name: str
    field_quality_rules: list[str] = Field(default_factory=list)
    online_policy: Literal["required", "degradable", "research_only"] = "degradable"
    comment: str

    @model_validator(mode="after")
    def reject_model_owned_contract_fields(self) -> "SourceFieldContract":
        field = self.canonical_field_name.lower()
        if any(fragment in field for fragment in MODEL_OWNED_FIELD_FRAGMENTS):
            raise ValueError(f"source field contract has model-owned semantics: {self.canonical_field_name}")
        return self


class RawFetchRequest(BaseModel):
    provider: Provider
    api_name: str
    params: dict[str, Any]
    batch_id: str | None = None
    dry_run: bool = False


class RawRow(BaseModel):
    provider: Provider
    api_name: str
    raw_table_name: str
    request_params: dict[str, Any]
    row: dict[str, Any]
    captured_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    available_at: datetime | None = None
    request_hash: str | None = None
    response_schema_hash: str | None = None
    response_row_hash: str | None = None
    batch_id: str | None = None
    biz_key: str | None = None
    quality_status: QualityStatus = QualityStatus.USABLE


class RawFetchResult(BaseModel):
    provider: Provider
    api_name: str
    raw_table_name: str
    request_params: dict[str, Any]
    dry_run: bool
    row_count: int
    rows: list[RawRow] = Field(default_factory=list)
    request_hash: str | None = None
    response_schema_hash: str | None = None
    warning: str | None = None
    error: str | None = None


class SourceGapRequest(BaseModel):
    source_table_name: str
    canonical_field_name: str
    symbol: str | None = None
    trade_date: date | None = None
    start_date: date | None = None
    end_date: date | None = None
    provider_hint: Provider | None = None


class RepairApiPlan(BaseModel):
    provider: Provider
    api_name: str
    raw_table_name: str
    params: dict[str, Any]
    reason: str
    priority: int


class SourceGapRepairPlan(BaseModel):
    source_table_name: str
    canonical_field_name: str
    symbol: str | None = None
    trade_date: date | None = None
    primary_repair: RepairApiPlan
    backup_repairs: list[RepairApiPlan] = Field(default_factory=list)
    source_rebuild_required: bool = True


class SourceGapDiagnosis(BaseModel):
    """Full operator-facing diagnosis for a missing canonical source field."""

    source_table_name: str
    canonical_field_name: str
    required_level: RequiredLevel
    affected_models: list[str]
    required_for_online: bool
    required_for_backtest: bool
    minimum_coverage_rate: float
    primary_repair: RepairApiPlan
    backup_repairs: list[RepairApiPlan] = Field(default_factory=list)
    rebuild_steps: list[str]
    lineage_lookup: dict[str, Any]
    operator_checklist: list[str]
    online_impact: Literal["block_online", "degrade", "research_only"]


class LineageResolveRequest(BaseModel):
    source_table_name: str
    canonical_field_name: str
    source_pk: str | None = None
    symbol: str | None = None
    trade_date: date | None = None


class LineageResolveResult(BaseModel):
    source_table_name: str
    canonical_field_name: str
    source_pk: str
    lineage_query_hint: str
    candidate_raw_tables: list[str]
    candidate_provider_apis: list[str]
    expected_raw_fields: list[str]


class ProbeRequest(BaseModel):
    provider: Provider
    api_name: str
    sample_params: dict[str, Any]
    expected_fields: list[str] = Field(default_factory=list)
    dry_run: bool = False


class ProbeResult(BaseModel):
    provider: Provider
    api_name: str
    raw_table_name: str
    connectivity_pass: bool
    schema_pass: bool
    expected_fields: list[str]
    observed_fields: list[str]
    missing_fields: list[str]
    row_count: int
    usable_for_source_table: bool
    usable_for_model_online: bool
    usable_for_research_only: bool
    reject_reason: str | None = None


class ReadinessRequest(BaseModel):
    source_table_name: str


class ReadinessResult(BaseModel):
    source_table_name: str
    required_field_count: int
    p0_field_count: int
    fields_with_backup_count: int
    readiness_status: Literal["passed", "research_only", "blocked"]
    blocking_reasons: list[str]


class HealthOut(BaseModel):
    status: str
    service: str
    version: str


class ProviderRuntimeStatus(BaseModel):
    provider: Provider
    api_name: str | None = None
    adapter_implemented: bool
    optional_package_available: bool | None = None
    circuit_state: Literal["closed", "open"] = "closed"
    failure_count: int = 0
    recovery_seconds: int | None = None
    last_error: str | None = None


class ReadinessOut(BaseModel):
    status: Literal["ready", "degraded"]
    service: str
    version: str
    provider_registry_count: int
    p0_requirement_count: int
    note: str

class SourceBuildPlanRequest(BaseModel):
    source_table_name: str
    canonical_fields: list[str] = Field(default_factory=list)
    symbol: str | None = None
    trade_date: date | None = None
    start_date: date | None = None
    end_date: date | None = None


class SourceBuildStep(BaseModel):
    source_table_name: str
    canonical_field_name: str
    required_level: RequiredLevel
    primary_provider: Provider
    primary_api_name: str
    primary_raw_table_name: str
    backup_raw_table_names: list[str] = Field(default_factory=list)
    quality_gates: list[str] = Field(default_factory=list)
    lineage_required: bool = True
    build_rule_code: str
    rebuild_sql_hint: str


class SourceBuildPlan(BaseModel):
    source_table_name: str
    symbol: str | None = None
    trade_date: date | None = None
    start_date: date | None = None
    end_date: date | None = None
    step_count: int
    steps: list[SourceBuildStep]
    execution_order: list[str]


class QualityValidationRequest(BaseModel):
    provider: Provider
    api_name: str
    rows: list[dict[str, Any]]


class QualityCheckIssue(BaseModel):
    row_index: int
    field_name: str
    severity: Literal["error", "warning"]
    rule_code: str
    message: str


class QualityValidationResult(BaseModel):
    provider: Provider
    api_name: str
    raw_table_name: str
    row_count: int
    observed_fields: list[str]
    issue_count: int
    error_count: int
    warning_count: int
    build_allowed: bool
    issues: list[QualityCheckIssue]


class ReadinessMatrixRow(BaseModel):
    source_table_name: str
    p0_field_count: int
    p1_field_count: int
    total_field_count: int
    fields_with_backup_count: int
    readiness_status: Literal["passed", "research_only", "blocked"]
    blocking_reasons: list[str] = Field(default_factory=list)


class ReadinessMatrixOut(BaseModel):
    table_count: int
    rows: list[ReadinessMatrixRow]


class SourceProbeMatrixRow(BaseModel):
    provider: Provider
    api_name: str
    raw_table_name: str
    sample_params: dict[str, Any]
    expected_fields: list[str]
    canonical_targets: list[str]
    dry_run_supported: bool
    real_probe_required: bool
    readiness_note: str


class SourceProbeMatrixOut(BaseModel):
    api_count: int
    rows: list[SourceProbeMatrixRow]


class RepairRouteRow(BaseModel):
    source_table_name: str
    canonical_field_name: str
    required_level: RequiredLevel
    primary_provider: Provider
    primary_api_name: str
    primary_raw_table_name: str
    backup_provider: Provider | None = None
    backup_api_name: str | None = None
    online_policy: Literal["required", "degradable", "research_only"] = "degradable"
    used_by_models: list[str]


class RepairRouteOut(BaseModel):
    route_count: int
    rows: list[RepairRouteRow]

class FetchTriggerType(str, Enum):
    """Why a raw-interface fetch batch was created.

    The trigger type is part of the production audit trail. It determines queue
    priority and prevents model ad-hoc requests or historical backfills from
    stealing capacity from release-gate critical P0 data refreshes.
    """

    SCHEDULED_PERIODIC = "scheduled_periodic"
    DATA_INSPECTION_GAP_REPAIR = "data_inspection_gap_repair"
    MODEL_ADHOC_REQUEST = "model_adhoc_request"
    MODEL_RELEASE_PREFLIGHT = "model_release_preflight"
    MANUAL_BACKFILL = "manual_backfill"
    PROVIDER_PROBE = "provider_probe"
    OPERATOR_MANUAL = "operator_manual"


class FetchPriority(str, Enum):
    P0_URGENT_RELEASE = "P0_urgent_release"
    P1_NORMAL_INGEST = "P1_normal_ingest"
    P2_BACKFILL = "P2_backfill"
    RESEARCH = "research"


class FetchStrategy(str, Enum):
    FULL_MARKET_BATCH = "full_market_batch"
    SYMBOL_PARALLEL = "symbol_parallel"
    SINGLE_REQUEST = "single_request"
    API_BATCH_BY_DATE = "api_batch_by_date"


class FetchQueueName(str, Enum):
    URGENT_RELEASE_GATE_QUEUE = "urgent_release_gate_queue"
    NORMAL_DAILY_INGEST_QUEUE = "normal_daily_ingest_queue"
    REPAIR_QUEUE = "repair_queue"
    BACKFILL_QUEUE = "backfill_queue"
    RESEARCH_QUEUE = "research_queue"
    PROVIDER_PROBE_QUEUE = "provider_probe_queue"


class FetchJobStatus(str, Enum):
    PLANNED = "planned"
    QUEUED = "queued"
    LEASED = "leased"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED_DUPLICATE = "skipped_duplicate"
    CANCELLED = "cancelled"
    DEAD_LETTER = "dead_letter"


class FetchBatchStatus(str, Enum):
    PLANNED = "planned"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    CANCELLED = "cancelled"


class CallbackEventType(str, Enum):
    BATCH_SUBMITTED = "batch_submitted"
    JOB_LEASED = "job_leased"
    JOB_SUCCEEDED = "job_succeeded"
    JOB_FAILED = "job_failed"
    JOB_REQUEUED = "job_requeued"
    JOB_HEARTBEAT = "job_heartbeat"
    JOB_CANCELLED = "job_cancelled"
    BACKUP_JOB_QUEUED = "backup_job_queued"
    SOURCE_BUILD_TRIGGER_CREATED = "source_build_trigger_created"
    CALLBACK_DELIVERY_ATTEMPTED = "callback_delivery_attempted"
    BATCH_COMPLETED = "batch_completed"


class ProviderRateLimitPolicy(BaseModel):
    provider: Provider
    api_name: str
    max_concurrency: int = Field(ge=1)
    requests_per_minute: int | None = Field(default=None, ge=1)
    min_interval_ms: int = Field(default=0, ge=0)
    timeout_ms: int = Field(default=12000, ge=100)
    max_retry_count: int = Field(default=2, ge=0)
    retry_backoff_policy: str = "exponential"
    circuit_breaker_enabled: bool = True
    circuit_open_seconds: int = Field(default=60, ge=1)
    priority_weight: int = Field(default=100, ge=1)
    enabled: bool = True
    comment: str


class FetchPlanRequest(BaseModel):
    source_table_name: str
    canonical_fields: list[str] = Field(default_factory=list)
    symbols: list[str] = Field(default_factory=list)
    trade_date: date | None = None
    start_date: date | None = None
    end_date: date | None = None
    trigger_type: FetchTriggerType
    priority: FetchPriority
    request_source: str = "source-data-service"
    model_code: str | None = None
    model_phase: str | None = None
    dry_run: bool = True
    prefer_batch: bool = True
    callback_url: str | None = None


class FetchBackupPlan(BaseModel):
    provider: Provider
    api_name: str
    raw_table_name: str
    request_params: dict[str, Any]
    reason: str


class FetchPlannedJob(BaseModel):
    provider: Provider
    api_name: str
    raw_table_name: str
    request_params: dict[str, Any]
    request_hash: str
    source_table_name: str
    canonical_fields: list[str]
    symbol: str | None = None
    trade_date: date | None = None
    date_range_start: date | None = None
    date_range_end: date | None = None
    priority: FetchPriority
    queue_name: FetchQueueName
    estimated_timeout_ms: int
    backup_plans: list[FetchBackupPlan] = Field(default_factory=list)


class FetchPlanOut(BaseModel):
    fetch_plan_id: str
    source_table_name: str
    trigger_type: FetchTriggerType
    priority: FetchPriority
    strategy: FetchStrategy
    queue_name: FetchQueueName
    job_count: int
    deduplicated_job_count: int
    symbols_count: int
    estimated_runtime_seconds: float
    jobs: list[FetchPlannedJob]
    rate_limit_policies: list[ProviderRateLimitPolicy]
    operator_notes: list[str]


class FetchSubmitRequest(FetchPlanRequest):
    auto_start: bool = False
    idempotency_key: str | None = None


class FetchSubmitResult(BaseModel):
    fetch_batch_id: str
    fetch_plan_id: str
    status: FetchBatchStatus
    queue_name: FetchQueueName
    submitted_job_count: int
    skipped_duplicate_count: int
    callback_registered: bool
    producer_ack: str


class FetchJobLeaseRequest(BaseModel):
    worker_id: str
    max_jobs: int = Field(default=10, ge=1, le=100)
    providers: list[Provider] = Field(default_factory=list)
    queue_names: list[FetchQueueName] = Field(default_factory=list)
    lease_seconds: int = Field(default=60, ge=5, le=3600)


class FetchJobLeaseOut(BaseModel):
    worker_id: str
    leased_count: int
    jobs: list["FetchJobStatusOut"]


class FetchJobCompleteRequest(BaseModel):
    worker_id: str
    success: bool
    row_count: int = Field(default=0, ge=0)
    error_code: str | None = None
    error_message: str | None = None
    raw_request_hash: str | None = None
    raw_response_schema_hash: str | None = None


class FetchJobStatusOut(BaseModel):
    job_item_id: str
    fetch_batch_id: str
    provider: Provider
    api_name: str
    raw_table_name: str
    request_params: dict[str, Any]
    request_hash: str
    source_table_name: str
    canonical_fields: list[str]
    symbol: str | None = None
    trade_date: date | None = None
    priority: FetchPriority
    queue_name: FetchQueueName
    status: FetchJobStatus
    worker_id: str | None = None
    attempt_count: int = 0
    backup_of_job_item_id: str | None = None
    next_retry_at: datetime | None = None
    lease_expires_at: datetime | None = None
    last_error_code: str | None = None
    last_error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class FetchBatchStatusOut(BaseModel):
    fetch_batch_id: str
    fetch_plan_id: str
    source_table_name: str
    trigger_type: FetchTriggerType
    priority: FetchPriority
    queue_name: FetchQueueName
    status: FetchBatchStatus
    job_count: int
    queued_count: int
    leased_count: int
    succeeded_count: int
    failed_count: int
    skipped_duplicate_count: int
    callback_url: str | None = None
    created_at: datetime
    updated_at: datetime
    operator_notes: list[str] = Field(default_factory=list)


class FetchCallbackEventOut(BaseModel):
    callback_event_id: str
    fetch_batch_id: str
    job_item_id: str | None = None
    event_type: CallbackEventType
    callback_url: str | None = None
    payload: dict[str, Any]
    delivery_status: Literal["pending", "delivered", "skipped_no_callback", "failed"] = "pending"
    created_at: datetime


class ProviderConcurrencyRuntimeStatus(BaseModel):
    provider: Provider
    api_name: str
    max_concurrency: int
    current_inflight: int
    queued_count: int
    leased_count: int
    succeeded_count: int
    failed_count: int
    runtime_status: Literal["healthy", "busy", "rate_limited", "circuit_open", "disabled"]
    circuit_state: Literal["closed", "open"]
    last_error: str | None = None



class FetchQueuePersistenceStatusOut(BaseModel):
    backend: Literal["memory", "postgres"]
    durable: bool
    database_url_configured: bool
    driver_available: bool
    ready_for_production_queue: bool
    active_batch_count: int
    queued_job_count: int
    leased_job_count: int
    dead_letter_count: int
    note: str


class FetchQueueSummaryRow(BaseModel):
    queue_name: FetchQueueName
    queued_count: int
    leased_count: int
    succeeded_count: int
    failed_count: int
    dead_letter_count: int


class FetchQueueSummaryOut(BaseModel):
    rows: list[FetchQueueSummaryRow]


class FetchLeaseMaintenanceResult(BaseModel):
    requeued_count: int
    expired_job_ids: list[str]
    checked_at: datetime


class FetchJobHeartbeatRequest(BaseModel):
    worker_id: str
    extend_lease_seconds: int = Field(default=60, ge=5, le=3600)
    worker_note: str | None = None


class FetchBatchCancelRequest(BaseModel):
    reason: str
    operator: str = "operator"


class FetchCallbackDispatchRequest(BaseModel):
    max_events: int = Field(default=20, ge=1, le=200)
    dry_run: bool = True


class FetchCallbackDispatchResult(BaseModel):
    attempted_count: int
    delivered_count: int
    skipped_count: int
    failed_count: int
    dry_run: bool


class SourceBuildTriggerOut(BaseModel):
    trigger_id: str
    fetch_batch_id: str
    job_item_id: str | None = None
    source_table_name: str
    symbol: str | None = None
    trade_date: date | None = None
    build_scope: str
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"] = "queued"
    quality_check_required: bool = True
    lineage_required: bool = True
    created_at: datetime
    finished_at: datetime | None = None


class FetchWorkerRunOnceRequest(BaseModel):
    worker_id: str
    max_jobs: int = Field(default=5, ge=1, le=50)
    providers: list[Provider] = Field(default_factory=list)
    queue_names: list[FetchQueueName] = Field(default_factory=list)
    lease_seconds: int = Field(default=60, ge=5, le=3600)
    dry_run_provider: bool = True
    complete_on_structured_provider_error: bool = False


class FetchWorkerRunOnceResult(BaseModel):
    worker_id: str
    leased_count: int
    succeeded_count: int
    failed_count: int
    generated_build_trigger_count: int
    job_ids: list[str]
    errors: list[str] = Field(default_factory=list)


class RawRepositoryStatusOut(BaseModel):
    backend: Literal["memory", "postgres"]
    durable_raw_writes: bool
    database_url_configured: bool
    driver_available: bool
    ready_for_production_raw_store: bool
    raw_row_count: int
    source_row_count: int
    lineage_row_count: int
    build_result_count: int
    note: str


class RawIngestResult(BaseModel):
    provider: Provider
    api_name: str
    raw_table_name: str
    request_hash: str | None = None
    response_schema_hash: str | None = None
    ingested_row_count: int
    duplicate_row_count: int
    rejected_row_count: int
    raw_write_status: Literal["accepted", "accepted_with_warnings", "rejected"]
    quality_status: Literal["not_checked", "passed", "blocked"] = "not_checked"
    warnings: list[str] = Field(default_factory=list)


class SourceCanonicalRowOut(BaseModel):
    source_table_name: str
    source_pk: str
    symbol: str | None = None
    trade_date: date | None = None
    values: dict[str, Any]
    source_quality_status: QualityStatus = QualityStatus.USABLE
    primary_provider: Provider | None = None
    primary_api_name: str | None = None
    build_batch_id: str | None = None
    available_at: datetime | None = None
    captured_at: datetime | None = None
    updated_at: datetime


class SourceLineageRecordOut(BaseModel):
    lineage_id: str
    source_table_name: str
    source_pk: str
    canonical_field_name: str
    provider: Provider
    api_name: str
    raw_table_name: str
    raw_id: str | None = None
    request_hash: str | None = None
    response_row_hash: str | None = None
    build_batch_id: str
    confidence_score: float = Field(ge=0, le=1)
    created_at: datetime


class SourceBuildExecuteRequest(BaseModel):
    trigger_id: str
    worker_id: str = "source-build-worker"
    dry_run: bool = False
    require_raw_quality_pass: bool = True


class SourceBuildExecutionResult(BaseModel):
    trigger_id: str
    fetch_batch_id: str | None = None
    job_item_id: str | None = None
    source_table_name: str
    build_batch_id: str
    status: Literal["succeeded", "failed", "skipped_no_raw", "dry_run"]
    raw_row_count: int
    source_row_count: int
    lineage_row_count: int
    quality_issue_count: int
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    started_at: datetime
    finished_at: datetime


class SourceBuildWorkerRunOnceRequest(BaseModel):
    worker_id: str = "source-build-worker"
    max_triggers: int = Field(default=10, ge=1, le=100)
    source_table_names: list[str] = Field(default_factory=list)
    dry_run: bool = False


class SourceBuildWorkerRunOnceResult(BaseModel):
    worker_id: str
    leased_trigger_count: int
    succeeded_count: int
    failed_count: int
    skipped_count: int
    results: list[SourceBuildExecutionResult]


class SourceFreshnessSla(BaseModel):
    source_table_name: str
    canonical_field_name: str
    frequency: str
    market_phase: str
    expected_available_time: str
    latest_acceptable_time: str
    timezone: str = "Asia/Shanghai"
    used_by_models: list[str]
    required_for_release_gate: bool
    stale_after_minutes: int
    late_policy: Literal["block_official_release", "degrade", "research_only"]
    fallback_policy: str
    comment: str


class SourceFreshnessStatusRequest(BaseModel):
    source_table_name: str
    canonical_fields: list[str] = Field(default_factory=list)
    symbols: list[str] = Field(default_factory=list)
    trade_date: date
    decision_time: datetime | None = None


class SourceFreshnessStatusRow(BaseModel):
    source_table_name: str
    canonical_field_name: str
    symbol: str | None = None
    trade_date: date
    freshness_status: Literal["fresh", "late", "stale", "missing"]
    latest_data_available_at: datetime | None = None
    stale_after_minutes: int
    affected_models: list[str]
    blocking_release_gate: bool
    reason: str


class SourceFreshnessStatusResult(BaseModel):
    checked_at: datetime
    status: Literal["passed", "degraded", "blocked"]
    rows: list[SourceFreshnessStatusRow]
    blocking_reasons: list[str] = Field(default_factory=list)


class SourceStoragePolicy(BaseModel):
    table_name: str
    table_layer: Literal["raw", "source", "governance"]
    partition_key: str
    partition_granularity: Literal["daily", "monthly", "yearly", "none"]
    retention_hot_days: int
    archive_enabled: bool
    archive_target: str | None = None
    required_indexes: list[str]
    expected_daily_rows: int
    expected_total_rows_1y: int
    expected_total_rows_10y: int
    comment: str


class ModelSourceRequirement(BaseModel):
    model_code: str
    model_phase: str
    source_table_name: str
    canonical_field_name: str
    required_level: RequiredLevel
    required_for_official_signal: bool
    required_for_backtest: bool
    required_for_research: bool
    degrade_policy: Literal["block", "degrade", "ignore_for_online", "research_only"]
    minimum_symbol_coverage_rate: float = Field(ge=0, le=1)
    minimum_date_coverage_rate: float = Field(ge=0, le=1)
    minimum_field_coverage_rate: float = Field(ge=0, le=1)
    comment: str


class ModelCoverageCheckRequest(BaseModel):
    model_code: str
    model_phase: str
    trade_date: date
    symbols: list[str] = Field(default_factory=list)
    required_levels: list[RequiredLevel] = Field(default_factory=lambda: [RequiredLevel.P0, RequiredLevel.P1])


class ModelCoverageFieldStatus(BaseModel):
    source_table_name: str
    canonical_field_name: str
    required_level: RequiredLevel
    required_for_official_signal: bool
    coverage_rate: float
    covered_symbol_count: int
    missing_symbol_count: int
    status: Literal["passed", "degraded", "blocked", "research_only"]
    missing_symbols: list[str] = Field(default_factory=list)
    repair_route_hint: dict[str, Any] | None = None


class ModelCoverageCheckResult(BaseModel):
    model_code: str
    model_phase: str
    trade_date: date
    universe_size: int
    p0_field_count: int
    p0_passed_field_count: int
    p1_field_count: int
    p1_passed_field_count: int
    coverage_status: Literal["passed", "degraded", "blocked", "research_only"]
    blocking_fields: list[str] = Field(default_factory=list)
    degraded_fields: list[str] = Field(default_factory=list)
    rows: list[ModelCoverageFieldStatus]
    checked_at: datetime


class ReleasePreflightRequest(BaseModel):
    model_code: str
    model_phase: str
    trade_date: date
    symbols: list[str] = Field(default_factory=list)
    decision_time: datetime | None = None


class ReleasePreflightResult(BaseModel):
    model_code: str
    model_phase: str
    trade_date: date
    can_release_official_signal: bool
    coverage_status: Literal["passed", "degraded", "blocked", "research_only"]
    freshness_status: Literal["passed", "degraded", "blocked"]
    blocking_reasons: list[str] = Field(default_factory=list)
    degraded_reasons: list[str] = Field(default_factory=list)
    repair_actions: list[dict[str, Any]] = Field(default_factory=list)
    checked_at: datetime

class ProductionReadinessCheck(BaseModel):
    check_code: str
    status: Literal["passed", "warning", "blocked"]
    required_for拍板: bool = True
    evidence: dict[str, Any] = Field(default_factory=dict)
    operator_action: str | None = None


class ProductionReadinessReport(BaseModel):
    service: str = "source-data-service"
    version_label: str
    can拍板: bool
    status: Literal["passed", "blocked"]
    checked_at: datetime
    checks: list[ProductionReadinessCheck]
    blocking_reasons: list[str] = Field(default_factory=list)
    warning_reasons: list[str] = Field(default_factory=list)


class AcceptanceRunRequest(BaseModel):
    base_url: str = "http://127.0.0.1:8041"
    dry_run_provider: bool = True
    require_postgres: bool = True
    require_real_provider_probe: bool = False
    timeout_seconds: float = 8.0


class AcceptanceCheckEvidence(BaseModel):
    check_code: str
    status: Literal["passed", "warning", "blocked"]
    required_for_lock: bool = True
    evidence: dict[str, Any] = Field(default_factory=dict)
    operator_action: str | None = None
    checked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AcceptanceRunPersistRequest(BaseModel):
    acceptance_run_id: str | None = None
    version_label: str | None = None
    base_url: str = "http://127.0.0.1:8041"
    dry_run_provider: bool = True
    require_postgres: bool = True
    require_real_provider_probe: bool = False
    status: Literal["passed", "blocked"]
    can_lock_candidate: bool
    blocking_reasons: list[str] = Field(default_factory=list)
    warning_reasons: list[str] = Field(default_factory=list)
    checks: list[AcceptanceCheckEvidence] = Field(default_factory=list)
    started_at: datetime | None = None
    finished_at: datetime | None = None


class AcceptanceRunOut(BaseModel):
    acceptance_run_id: str
    version_label: str
    base_url: str
    dry_run_provider: bool = True
    require_postgres: bool = True
    require_real_provider_probe: bool = False
    status: Literal["passed", "blocked"]
    can_lock_candidate: bool
    blocking_reasons: list[str] = Field(default_factory=list)
    warning_reasons: list[str] = Field(default_factory=list)
    started_at: datetime
    finished_at: datetime | None = None
    checks: list[AcceptanceCheckEvidence] = Field(default_factory=list)
    persisted: bool = False
    note: str | None = None
