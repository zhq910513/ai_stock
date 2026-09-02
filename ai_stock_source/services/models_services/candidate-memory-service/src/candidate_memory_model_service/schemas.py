from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class CandidateMemoryScoreRequest(BaseModel):
    row: dict[str, Any] = Field(default_factory=dict)
    as_of_time_utc: datetime | None = None
    run_id: str | None = None


class CandidateMemoryProductionRequest(BaseModel):
    row: dict[str, Any] = Field(default_factory=dict)
    as_of_time_utc: datetime | None = None
    run_id: str | None = None


class ModelServiceResponse(BaseModel):
    model_name: Literal["candidate_memory"]
    model_version: str
    structured_output: dict[str, Any]
    jarvis_payload: dict[str, Any]
    contract_gaps: list[str] = Field(default_factory=list)
