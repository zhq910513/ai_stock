from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class HotCandidateScoreRequest(BaseModel):
    row: dict[str, Any] = Field(default_factory=dict)
    as_of_time_utc: datetime | None = None
    run_id: str | None = None


class HotCandidateDistortionReportRequest(BaseModel):
    analyses: list[dict[str, Any]] = Field(default_factory=list)
    labels: list[dict[str, Any]] = Field(default_factory=list)
    trade_date: date | None = None
    min_learning_samples: int = Field(default=120, ge=1)


class ModelServiceResponse(BaseModel):
    model_name: Literal["hot_candidates"]
    model_version: str
    structured_output: dict[str, Any]
    jarvis_payload: dict[str, Any]
    contract_gaps: list[str] = Field(default_factory=list)


class HotCandidateObservationRequest(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)
    as_of_time_utc: datetime | None = None
    run_id: str | None = None


class HotCandidateEvolutionSampleRequest(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)
    as_of_time_utc: datetime | None = None
    run_id: str | None = None


class HotCandidatePipelineRunRequest(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)
    as_of_time_utc: datetime | None = None
    run_id: str | None = None


class HotTeacherCalibrationReportRequest(BaseModel):
    samples: list[dict[str, Any]] = Field(default_factory=list)
    calibration_version: str = "hot_teacher_calibration_v1_generated"
    min_bucket_samples: int = Field(default=30, ge=1)
    min_total_samples: int = Field(default=120, ge=1)
    as_of_time_utc: datetime | None = None


class HotResearchSamplePoolRequest(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)
    as_of_time_utc: datetime | None = None


class HotBulkObservationRequest(BaseModel):
    active_cases: list[dict[str, Any]] = Field(default_factory=list)
    as_of_time_utc: datetime | None = None


class HotCalibrationVersionRequest(BaseModel):
    samples: list[dict[str, Any]] = Field(default_factory=list)
    calibration_version: str = "hot_teacher_calibration_v2_candidate"
    training_window_start: str
    training_window_end: str
    calibration_cutoff_time: datetime | None = None
    min_bucket_samples: int = Field(default=30, ge=1)
    min_total_samples: int = Field(default=120, ge=1)


class HotFeatureBuildRequest(BaseModel):
    rows: list[dict[str, Any]] = Field(default_factory=list)
    calc_stage: str = "open_5m_confirmed"
    as_of_time_utc: datetime | None = None


class HotProductionPayloadRequest(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)
    as_of_time_utc: datetime | None = None
    run_id: str | None = None


class HotProductionRowsRequest(BaseModel):
    rows: list[dict[str, Any]] = Field(default_factory=list)
    as_of_time_utc: datetime | None = None
    run_id: str | None = None
