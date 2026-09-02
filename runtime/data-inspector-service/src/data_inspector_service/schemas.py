from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


class DomainContractOut(BaseModel):
    domain_code: str
    business_line: str
    target_table: str
    grain: str
    required_level: str
    default_severity: str
    description: str
    blocks_scoring: bool = False
    blocks_publish: bool = False
    replay_safe: bool = True
    provider_lineage_required: bool = True


class InspectionRunCreate(BaseModel):
    scope: str = "startup_guard"
    as_of_trading_day: date | None = None
    as_of_time: datetime | None = None
    lookback_days: int = Field(default=20, ge=1, le=120)
    max_subjects: int = Field(default=100, ge=1, le=5000)
    symbols: list[str] = Field(default_factory=list)
    persist: bool | None = None


class InspectionGapOut(BaseModel):
    gap_id: int | None = None
    subject_id: int | None = None
    instrument_id: int | None = None
    symbol: str = "__service__"
    gap_type: str
    domain_code: str
    target_table: str
    severity: str
    trading_day: date | None = None
    gap_start_at: datetime | None = None
    gap_end_at: datetime | None = None
    missing_count: int = 0
    expected_count: int | None = None
    observed_count: int | None = None
    blocks_scoring: bool = False
    blocks_publish: bool = False
    replay_safe: bool = True
    provider_lineage_required: bool = False
    remediation_status: str = "pending"
    details: dict[str, Any] = Field(default_factory=dict)


class RemediationTaskOut(BaseModel):
    task_id: int | None = None
    gap_id: int | None = None
    action_type: str
    owner_service: str
    priority: str
    provider_candidates: list[str] = Field(default_factory=list)
    request_payload: dict[str, Any] = Field(default_factory=dict)
    status: str = "suggested"


class InspectionSubjectOut(BaseModel):
    subject_id: int | None = None
    instrument_id: int | None = None
    symbol: str
    scope: str
    expected_domain_count: int
    observed_domain_count: int
    missing_domain_count: int
    fine_time_gap_count: int = 0
    coarse_time_gap_count: int = 0
    inspection_status: str
    completeness_score: Decimal
    publish_due_expected_domain_count: int = 0
    publish_due_observed_domain_count: int = 0
    publish_due_missing_domain_count: int = 0
    publish_due_completeness_score: Decimal = Decimal("0.000000")
    publish_due_status: str = "unknown"
    publish_due_missing_domains: list[str] = Field(default_factory=list)
    missing_domains: list[str] = Field(default_factory=list)
    gap_count: int = 0
    p0_gap_count: int = 0
    p1_gap_count: int = 0
    summary: dict[str, Any] = Field(default_factory=dict)


class InspectionRunOut(BaseModel):
    contract_kind: str = "data_inspection_run_v2"
    inspection_version: str = "source_first_data_inspection_v1"
    run_id: int | None = None
    scope: str
    as_of_trading_day: date
    as_of_time: datetime | None = None
    lookback_days: int
    status: str
    requested_subject_count: int
    inspected_subject_count: int
    gap_count: int
    p0_gap_count: int
    p1_gap_count: int
    publish_due_completeness_score: Decimal = Decimal("0.000000")
    publish_due_average_completeness_score: Decimal = Decimal("0.000000")
    publish_due_status: str = "unknown"
    publish_due_blocking_subject_count: int = 0
    publish_due_ready_subject_count: int = 0
    publish_due_quarantined_subject_count: int = 0
    publish_due_publishable_subject_count: int = 0
    publish_due_missing_domain_count: int = 0
    started_at: datetime
    finished_at: datetime | None = None
    subjects: list[InspectionSubjectOut] = Field(default_factory=list)
    gaps: list[InspectionGapOut] = Field(default_factory=list)
    remediation_tasks: list[RemediationTaskOut] = Field(default_factory=list)
    warning_codes: list[str] = Field(default_factory=list)
    time_semantics: dict[str, Any] = Field(default_factory=dict)
    guardrails: dict[str, Any] = Field(default_factory=dict)


class InspectionGapRecordOut(BaseModel):
    gap_id: int
    run_id: int
    subject_id: int
    instrument_id: int | None = None
    symbol: str
    symbol_snapshot: str
    gap_type: str
    domain_code: str
    target_table: str
    severity: str
    trading_day: date | None = None
    gap_start_at: datetime | None = None
    gap_end_at: datetime | None = None
    missing_count: int
    expected_count: int | None = None
    observed_count: int | None = None
    blocks_scoring: bool
    blocks_publish: bool
    remediation_status: str
    details_json: dict[str, Any] = Field(default_factory=dict)
