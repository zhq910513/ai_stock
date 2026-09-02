from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

LabelMode = Literal["as_of", "outcome_review"]
AllowedLabelMode = Literal["as_of", "outcome_review", "both"]


class ValleyChartCaseCreate(BaseModel):
    chart_case_id: str | None = None
    canonical_symbol: str = Field(min_length=3, max_length=32)
    stock_name: str | None = None
    case_trade_date: date
    case_source: str = Field(default="manual")
    case_status: str = Field(default="pending_labeling")
    label_mode_allowed: AllowedLabelMode = "both"
    as_of_date: date | None = None
    valley_low_date: date | None = None
    turn_anchor_date: date | None = None
    source_data_version: str | None = None
    model_version: str | None = None
    feature_version: str | None = None
    source_gap_codes: list[str] = Field(default_factory=list)
    dynamic_gap_codes: list[str] = Field(default_factory=list)
    daily_bar_payload: list[dict[str, Any]] = Field(default_factory=list)
    weekly_bar_payload: list[dict[str, Any]] = Field(default_factory=list)
    automatic_feature_payload: dict[str, Any] = Field(default_factory=dict)
    decision_ref: dict[str, Any] = Field(default_factory=dict)
    created_by: str | None = None

    @field_validator("canonical_symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()


class ValleyChartCaseOut(ValleyChartCaseCreate):
    chart_case_id: str
    created_at: datetime | None = None
    updated_at: datetime | None = None
    latest_label: dict[str, Any] | None = None
    review_status: str | None = None
    library_role: str | None = None


class ManualLabelCreate(BaseModel):
    manual_label_id: str | None = None
    labeler_id: str = Field(min_length=1, max_length=64)
    labeler_role: str | None = None
    label_mode: LabelMode
    valley_structure_label: str | None = None
    turn_timing_label: str | None = None
    sample_role_label: str | None = None
    outcome_label: str | None = None
    manual_label_confidence: Literal["high", "medium", "low"] = "medium"
    manual_label_note: str | None = None
    visible_feature_boundary: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, values: list[str]) -> list[str]:
        return [str(value).strip().upper() for value in values if str(value).strip()]


class ManualLabelOut(ManualLabelCreate):
    manual_label_id: str
    chart_case_id: str
    created_at: datetime | None = None
    tag_rows: list[dict[str, Any]] = Field(default_factory=list)


class TaxonomyOut(BaseModel):
    taxonomy_id: str
    tag_group: str
    tag_code: str
    tag_name: str
    tag_description: str | None = None
    allowed_label_mode: AllowedLabelMode
    is_positive_signal: bool
    is_negative_signal: bool
    is_hard_negative_signal: bool
    is_training_eligible: bool
    enabled: bool
    display_order: int = 100


class ReviewCreate(BaseModel):
    review_id: str | None = None
    manual_label_id: str | None = None
    reviewer_id: str = Field(min_length=1, max_length=64)
    review_status: Literal["approved", "rejected", "needs_discussion"]
    review_comment: str | None = None
    final_sample_role_label: str | None = None
    final_outcome_label: str | None = None
    final_label_confidence: Literal["high", "medium", "low"] | None = None


class ReviewOut(ReviewCreate):
    review_id: str
    chart_case_id: str
    created_at: datetime | None = None


class LibraryMemberCreate(BaseModel):
    library_member_id: str | None = None
    manual_label_id: str | None = None
    library_role: Literal["positive_prototype", "hard_negative", "missed_opportunity", "control", "research_only"]
    pattern_family: str | None = None
    training_split: Literal["train", "validation", "test", "review_only"] = "review_only"
    approved_by: str | None = None
    shape_signature_id: str | None = None
    feature_snapshot_id: str | None = None


class LibraryMemberOut(LibraryMemberCreate):
    library_member_id: str
    chart_case_id: str
    created_at: datetime | None = None
