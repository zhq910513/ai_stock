from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True, slots=True)
class ServiceResult:
    ok: bool
    status_code: int
    data: dict[str, Any] | list[Any] | None = None
    error: str | None = None


class ServiceClient:
    def __init__(
        self,
        *,
        source_base_url: str,
        scheduler_base_url: str | None = None,
        hot_base_url: str | None = None,
        memory_base_url: str | None = None,
        ambush_base_url: str | None = None,
        t_board_base_url: str | None = None,
        timeout_seconds: float = 20.0,
    ) -> None:
        self.source_base_url = source_base_url.rstrip("/")
        self.scheduler_base_url = (scheduler_base_url or "").rstrip("/") or None
        self.model_base_urls = {
            "hot_candidates": (hot_base_url or "").rstrip("/") or None,
            "candidate_memory": (memory_base_url or "").rstrip("/") or None,
            "ambush_watchlist": (ambush_base_url or "").rstrip("/") or None,
            "t_board_relay": (t_board_base_url or "").rstrip("/") or None,
        }
        self.timeout_seconds = timeout_seconds

    def get_source(self, path: str, *, params: dict[str, Any] | None = None) -> ServiceResult:
        return self._request("GET", self.source_base_url, path, params=params)

    def post_source(self, path: str, payload: dict[str, Any]) -> ServiceResult:
        return self._request("POST", self.source_base_url, path, json=payload)

    def get_scheduler(self, path: str, *, params: dict[str, Any] | None = None) -> ServiceResult:
        if not self.scheduler_base_url:
            return ServiceResult(ok=False, status_code=0, error="scheduler base url is not configured")
        return self._request("GET", self.scheduler_base_url, path, params=params)

    def post_scheduler(self, path: str, payload: dict[str, Any]) -> ServiceResult:
        if not self.scheduler_base_url:
            return ServiceResult(ok=False, status_code=0, error="scheduler base url is not configured")
        return self._request("POST", self.scheduler_base_url, path, json=payload)

    def get_model_ready(self, model_code: str) -> ServiceResult:
        base_url = self.model_base_urls.get(model_code)
        if not base_url:
            return ServiceResult(ok=False, status_code=0, error=f"{model_code} base url is not configured")
        return self._request("GET", base_url, "/readyz")

    def _request(
        self,
        method: str,
        base_url: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> ServiceResult:
        url = f"{base_url}{path}"
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.request(method, url, params=params, json=json)
            try:
                data = response.json()
            except Exception:
                data = {"raw_text": response.text}
            return ServiceResult(
                ok=200 <= response.status_code < 300,
                status_code=response.status_code,
                data=data,
                error=None if 200 <= response.status_code < 300 else response.text,
            )
        except Exception as exc:
            return ServiceResult(ok=False, status_code=0, error=str(exc))
