from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class DragonWindowFeatureRequest(BaseModel):
    symbol: str
    bars: list[dict[str, Any]] = Field(default_factory=list)
    window_days: int
    as_of_trading_day: date
    as_of_time: datetime | None = None


class DragonAllWindowsRequest(BaseModel):
    symbol: str
    bars: list[dict[str, Any]] = Field(default_factory=list)
    as_of_trading_day: date
    as_of_time: datetime | None = None


class DragonL2Request(BaseModel):
    instrument: dict[str, Any] = Field(default_factory=dict)
    best_feature: dict[str, Any] | None = None
    bars: list[dict[str, Any]] = Field(default_factory=list)
    as_of_trading_day: date


class ValleyWatchRequest(BaseModel):
    instrument: dict[str, Any] = Field(default_factory=dict)
    bars: list[dict[str, Any]] = Field(default_factory=list)
    as_of_trading_day: date
    as_of_time: datetime | None = None


class EffectiveTurnRequest(BaseModel):
    instrument: dict[str, Any] = Field(default_factory=dict)
    valley_watch: dict[str, Any] | None = None
    bars: list[dict[str, Any]] = Field(default_factory=list)
    as_of_trading_day: date
    as_of_time: datetime | None = None
    snapshot_type: Literal["close_confirmed", "intraday_estimated"] = "close_confirmed"


class PoolTransitionAuditRequest(BaseModel):
    instrument: dict[str, Any] = Field(default_factory=dict)
    valley_watch: dict[str, Any]
    effective_turn_candidate: dict[str, Any]
    as_of_time: datetime | None = None
    created_by_job: str = "ambush_pool_transition_job"


class DragonDeepAnalysisRequest(BaseModel):
    instrument: dict[str, Any] = Field(default_factory=dict)
    best_feature: dict[str, Any]
    l2_candidate: dict[str, Any]
    effective_turn_candidate: dict[str, Any] | None = None
    bars: list[dict[str, Any]] = Field(default_factory=list)
    stock_rank: dict[str, Any] | None = None
    theme_ranks: list[dict[str, Any]] = Field(default_factory=list)
    news_context: dict[str, Any] | None = None
    market_context: dict[str, Any] | None = None
    as_of_trading_day: date
    as_of_time: datetime | None = None


class ModelServiceResponse(BaseModel):
    model_name: Literal["ambush_watchlist"]
    model_version: str
    structured_output: dict[str, Any]
    jarvis_payload: dict[str, Any]
    contract_gaps: list[str] = Field(default_factory=list)


class SourceCapabilityAuditRequest(BaseModel):
    provider: str = "unknown"
    bars: list[dict[str, Any]] = Field(default_factory=list)
    weekly_bars: list[dict[str, Any]] = Field(default_factory=list)
    instruments: list[dict[str, Any]] = Field(default_factory=list)
    checked_at: datetime | None = None


class ShapeSignatureRequest(BaseModel):
    symbol: str
    bars: list[dict[str, Any]] = Field(default_factory=list)
    as_of_trading_day: date
    window_days: int = 60
    prefer_adjusted: bool = True


class PatternPrototypeMatchRequest(BaseModel):
    current_signature: dict[str, Any] | None = None
    symbol: str | None = None
    bars: list[dict[str, Any]] = Field(default_factory=list)
    as_of_trading_day: date | None = None
    window_days: int = 60
    prototypes: list[dict[str, Any]] = Field(default_factory=list)
    top_k: int = 5


class HistoricalValleySampleLabelRequest(BaseModel):
    symbol: str
    bars: list[dict[str, Any]] = Field(default_factory=list)
    anchor_day: date
    market_bars: list[dict[str, Any]] = Field(default_factory=list)
    sector_bars: list[dict[str, Any]] = Field(default_factory=list)
    pre_window_days: int = 60
    label_window_days: int = 20


class ThreeChannelRecallRequest(BaseModel):
    instrument: dict[str, Any] = Field(default_factory=dict)
    bars: list[dict[str, Any]] = Field(default_factory=list)
    as_of_trading_day: date
    prototypes: list[dict[str, Any]] = Field(default_factory=list)
    market_context: dict[str, Any] | None = None


class Phase2ValleyWatchRequest(BaseModel):
    instrument: dict[str, Any] = Field(default_factory=dict)
    bars: list[dict[str, Any]] = Field(default_factory=list)
    weekly_bars: list[dict[str, Any]] = Field(default_factory=list)
    recall_result: dict[str, Any] | None = None
    pattern_match: dict[str, Any] | None = None
    as_of_trading_day: date
    as_of_time: datetime | None = None
    window_days: int = 60


class Phase2EffectiveTurnRequest(BaseModel):
    instrument: dict[str, Any] = Field(default_factory=dict)
    bars: list[dict[str, Any]] = Field(default_factory=list)
    weekly_bars: list[dict[str, Any]] = Field(default_factory=list)
    valley_watch: dict[str, Any] | None = None
    recall_result: dict[str, Any] | None = None
    pattern_match: dict[str, Any] | None = None
    as_of_trading_day: date
    as_of_time: datetime | None = None
    window_days: int = 60


class Phase2PoolTransitionRequest(BaseModel):
    instrument: dict[str, Any] = Field(default_factory=dict)
    valley_watch: dict[str, Any]
    effective_turn_anchor: dict[str, Any]
    as_of_time: datetime | None = None
    created_by_job: str = "ambush_phase2_pool_transition_job"


class Phase2PipelineRequest(BaseModel):
    instrument: dict[str, Any] = Field(default_factory=dict)
    bars: list[dict[str, Any]] = Field(default_factory=list)
    weekly_bars: list[dict[str, Any]] = Field(default_factory=list)
    recall_result: dict[str, Any] | None = None
    pattern_match: dict[str, Any] | None = None
    as_of_trading_day: date
    as_of_time: datetime | None = None
    window_days: int = 60


class Phase3DeepConfirmationRequest(BaseModel):
    instrument: dict[str, Any] = Field(default_factory=dict)
    valley_watch: dict[str, Any]
    effective_turn_anchor: dict[str, Any]
    bars: list[dict[str, Any]] = Field(default_factory=list)
    moneyflow_context: dict[str, Any] | None = None
    sector_context: dict[str, Any] | None = None
    market_context: dict[str, Any] | None = None
    tradability_context: dict[str, Any] | None = None
    as_of_trading_day: date
    as_of_time: datetime | None = None


class Phase3ReleaseGateRequest(BaseModel):
    instrument: dict[str, Any] = Field(default_factory=dict)
    valley_watch: dict[str, Any]
    effective_turn_anchor: dict[str, Any]
    deep_confirmation: dict[str, Any]
    as_of_trading_day: date
    as_of_time: datetime | None = None


class Phase3PipelineRequest(BaseModel):
    instrument: dict[str, Any] = Field(default_factory=dict)
    valley_watch: dict[str, Any]
    effective_turn_anchor: dict[str, Any]
    bars: list[dict[str, Any]] = Field(default_factory=list)
    moneyflow_context: dict[str, Any] | None = None
    sector_context: dict[str, Any] | None = None
    market_context: dict[str, Any] | None = None
    tradability_context: dict[str, Any] | None = None
    as_of_trading_day: date
    as_of_time: datetime | None = None


class Phase4ObservationRequest(BaseModel):
    signal_fact: dict[str, Any]
    buy_point: dict[str, Any] | None = None
    bars: list[dict[str, Any]] = Field(default_factory=list)
    as_of_trading_day: date
    as_of_time: datetime | None = None


class Phase4OutcomeRequest(BaseModel):
    signal_fact: dict[str, Any]
    buy_point: dict[str, Any] | None = None
    bars: list[dict[str, Any]] = Field(default_factory=list)
    maturity_days: int = 20
    as_of_time: datetime | None = None


class Phase4FailureAttributionRequest(BaseModel):
    signal_fact: dict[str, Any]
    outcome_label: dict[str, Any]
    release_gate: dict[str, Any] | None = None
    deep_confirmation: dict[str, Any] | None = None
    as_of_time: datetime | None = None


class AmbushLockCandidateRequest(BaseModel):
    validation_summary: dict[str, Any] | None = None
    as_of_time: datetime | None = None
