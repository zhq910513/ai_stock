from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Protocol

import httpx

from scheduler_service.hot_plan import HOT_CANDIDATES_TASKS, ScheduledTask

HOT_LIVE_DISPATCH_VERSION = "hot_live_dispatch_v1"


class DispatchHttpClient(Protocol):
    def post(self, url: str, *, json: dict[str, Any], timeout: float) -> Any: ...


@dataclass(frozen=True)
class OwnerEndpoint:
    owner_service: str
    base_url: str


@dataclass(frozen=True)
class LiveDispatchResult:
    contract_kind: str
    dispatcher_version: str
    task_code: str
    task_kind: str
    owner_service: str
    url: str
    status_code: int
    accepted: bool
    append_only: bool
    official_publish: bool
    dispatched_at: datetime
    response_preview: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["dispatched_at"] = self.dispatched_at.isoformat()
        return payload


class OwnerEndpointRegistry:
    def __init__(self, endpoints: list[OwnerEndpoint] | None = None) -> None:
        self._endpoints = {endpoint.owner_service: endpoint.base_url.rstrip("/") for endpoint in endpoints or []}

    @classmethod
    def from_mapping(cls, mapping: dict[str, str]) -> "OwnerEndpointRegistry":
        return cls([OwnerEndpoint(owner_service=k, base_url=v) for k, v in mapping.items()])

    def resolve(self, owner_service: str) -> str:
        endpoint = self._endpoints.get(owner_service)
        if not endpoint:
            raise RuntimeError(f"missing live endpoint for owner service: {owner_service}")
        return endpoint


class HotLiveDispatcher:
    """Dispatches real scheduler tasks to owner service endpoints.

    It protects the architecture rules: source collection cannot publish official model
    facts, observation/outcome/evolution tasks must be append-only, and every live call
    must be tied to a real owner endpoint rather than silently fabricating success.
    """

    def __init__(self, registry: OwnerEndpointRegistry, client: DispatchHttpClient | None = None) -> None:
        self.registry = registry
        self.client = client or httpx.Client()
        self.tasks: dict[str, ScheduledTask] = {task.task_code: task for task in HOT_CANDIDATES_TASKS}

    def _path_for(self, task: ScheduledTask) -> str:
        if task.task_kind == "source_collect":
            return "/source/facts/collect"
        if task.task_kind == "model_compute":
            return "/production/scores/compute"
        if task.task_kind == "release_gate":
            return "/production/release-gate/evaluate"
        if task.task_kind == "buy_point":
            return "/production/buy-point/evaluate"
        if task.task_kind == "observation":
            return "/production/observations/bulk"
        if task.task_kind == "outcome":
            return "/production/outcomes/mature"
        if task.task_kind == "evolution":
            return "/production/evolution/build"
        return "/healthz"

    def dispatch(self, task_code: str, *, payload: dict[str, Any]) -> LiveDispatchResult:
        task = self.tasks.get(task_code)
        if task is None:
            raise ValueError(f"unknown hot task: {task_code}")
        if task.task_kind == "source_collect" and task.is_official_publish:
            raise RuntimeError("source collection cannot publish official model facts")
        if task.task_kind in {"observation", "outcome", "evolution"} and not task.append_only:
            raise RuntimeError(f"{task.task_kind} task must be append-only")
        base_url = self.registry.resolve(task.owner_service)
        url = f"{base_url}{self._path_for(task)}"
        request_payload = {
            "task_code": task.task_code,
            "task_kind": task.task_kind,
            "owner_service": task.owner_service,
            "append_only": task.append_only,
            "is_official_publish": task.is_official_publish,
            "payload": payload,
        }
        response = self.client.post(url, json=request_payload, timeout=20.0)
        status_code = int(getattr(response, "status_code", 0))
        try:
            body = response.json()
        except Exception:  # noqa: BLE001
            body = {"text": str(getattr(response, "text", ""))[:500]}
        accepted = 200 <= status_code < 300
        return LiveDispatchResult(
            contract_kind="hot_live_dispatch_result_v1",
            dispatcher_version=HOT_LIVE_DISPATCH_VERSION,
            task_code=task.task_code,
            task_kind=task.task_kind,
            owner_service=task.owner_service,
            url=url,
            status_code=status_code,
            accepted=accepted,
            append_only=task.append_only,
            official_publish=task.is_official_publish,
            dispatched_at=datetime.now(timezone.utc),
            response_preview=body if isinstance(body, dict) else {"response": body},
        )
