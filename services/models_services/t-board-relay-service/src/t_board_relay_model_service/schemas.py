from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class TBoardRelayRequest(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)
    row: dict[str, Any] = Field(default_factory=dict)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    trade_date: date | None = None
    as_of_time_utc: datetime | None = None
    run_id: str | None = None
    mode: str = "production"
    model_version: str | None = None
    feature_version: str | None = None


class ModelServiceResponse(BaseModel):
    model_name: Literal["t_board_relay"]
    model_version: str
    structured_output: dict[str, Any]
    jarvis_payload: dict[str, Any]
    contract_gaps: list[str] = Field(default_factory=list)

