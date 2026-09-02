from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

PayloadAssemblyStatus = Literal["assembled_research_payload", "blocked_data_gap"]
ExecutionStatus = Literal[
    "blocked_data_gap",
    "owner_failed",
    "materialization_failed",
    "materialized",
    "materialized_with_gaps",
    "materialization_skipped",
]


class ModelPayloadAssembleRequest(BaseModel):
    task_code: str
    trade_date: date
    symbol: str | None = None
    symbols: list[str] = Field(default_factory=list)
    as_of_time_utc: datetime | None = None
    decision_time: datetime | None = None
    run_id: str | None = None
    persist_audit: bool = True
    extra_context: dict[str, Any] = Field(default_factory=dict)

    @field_validator("task_code")
    @classmethod
    def task_code_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("task_code is required")
        return value

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str | None) -> str | None:
        return value.strip().upper() if value else value

    @field_validator("symbols")
    @classmethod
    def normalize_symbols(cls, value: list[str]) -> list[str]:
        return [item.strip().upper() for item in value if item.strip()]

    @model_validator(mode="after")
    def merge_symbol(self) -> "ModelPayloadAssembleRequest":
        if self.symbol and self.symbol not in self.symbols:
            self.symbols.insert(0, self.symbol)
        return self


class ModelExecutionRunRequest(ModelPayloadAssembleRequest):
    execution_id: str | None = None


class SourceRef(BaseModel):
    table_name: str
    symbol: str | None = None
    trade_date: str | None = None
    row_count: int
    source_quality_status: str | None = None
    available_at: str | None = None
    lineage_id: str | None = None
    build_batch_id: str | None = None


class ModelPayloadAssembleResponse(BaseModel):
    contract_kind: str = "research_model_payload_assembly_result_v1"
    payload_assembly_contract: str
    payload_assembly_status: PayloadAssemblyStatus
    payload_assembly_source: str
    task_code: str
    owner_service: str
    task_kind: str
    official_publish: bool
    model_code: str
    model_phase: str | None = None
    trade_date: str
    symbols: list[str]
    assembly_id: str
    payload_hash: str
    run_id: str
    as_of_time_utc: str | None = None
    gap_codes: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    source_refs: list[SourceRef] = Field(default_factory=list)
    upstream_refs: list[SourceRef] = Field(default_factory=list)
    source_preflight: dict[str, Any] | None = None
    payload: dict[str, Any]
    audit_persisted: bool = False
    checked_at: str


class RequirementResponse(BaseModel):
    contract_kind: str = "research_model_payload_requirements_v1"
    assembler_contract: str
    required_status: str
    task_count: int
    tasks: list[dict[str, Any]]
    hard_rules: list[str]


class ModelExecutionRunResponse(BaseModel):
    contract_kind: str = "research_model_execution_result_v1"
    execution_contract: str = "research_model_execution_v1"
    execution_id: str
    execution_status: ExecutionStatus
    accepted: bool
    dispatch_allowed: bool
    owner_called: bool
    materialization_attempted: bool
    task_code: str
    owner_service: str
    model_code: str
    model_phase: str | None = None
    symbol: str | None = None
    trade_date: str
    run_id: str
    payload_hash: str | None = None
    owner_endpoint: str | None = None
    owner_status_code: int | None = None
    owner_response: dict[str, Any] | None = None
    materialized_counts: dict[str, Any] = Field(default_factory=dict)
    gap_codes: list[str] = Field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None
    audit_persisted: bool = False
    assembly: ModelPayloadAssembleResponse
