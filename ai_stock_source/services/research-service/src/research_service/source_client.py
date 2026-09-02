from __future__ import annotations

from datetime import date, datetime
from typing import Any, Protocol

import httpx


class SourcePreflightClient(Protocol):
    def release_preflight(
        self,
        *,
        model_code: str,
        model_phase: str,
        trade_date: date,
        symbols: list[str],
        decision_time: datetime | None,
    ) -> dict[str, Any]: ...


class HttpSourceDataClient:
    def __init__(self, base_url: str, timeout_seconds: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def release_preflight(
        self,
        *,
        model_code: str,
        model_phase: str,
        trade_date: date,
        symbols: list[str],
        decision_time: datetime | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model_code": model_code,
            "model_phase": model_phase,
            "trade_date": trade_date.isoformat(),
            "symbols": symbols,
        }
        if decision_time is not None:
            payload["decision_time"] = decision_time.isoformat()
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(f"{self.base_url}/source/release/preflight", json=payload)
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict):
            raise RuntimeError("source preflight returned non-object payload")
        return body
