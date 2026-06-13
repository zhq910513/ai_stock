from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

import httpx

from scheduler_service.hot_plan import ScheduledTask
from scheduler_service.three_model_plan import THREE_MODEL_TASKS

THREE_MODEL_LIVE_DISPATCH_VERSION = "three_model_live_dispatch_v1"
THREE_MODEL_LIVE_DISPATCH_SAMPLE_VERSION = "three_model_live_dispatch_sample_v1"
OFFICIAL_RELEASE_GATE_TASKS = (
    "hot.release_gate.preopen",
    "memory.release_gate.close",
    "ambush.phase3.release_gate.close",
)


class DispatchHttpClient(Protocol):
    def post(self, url: str, *, json: dict[str, Any], timeout: float) -> Any: ...


@dataclass(frozen=True)
class OwnerEndpoint:
    owner_service: str
    base_url: str


@dataclass(frozen=True)
class ThreeModelDispatchResult:
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


TASK_CODE_PATH_OVERRIDES: dict[str, str] = {
    # Hot candidates locked service endpoints.
    "hot.score.auction_confirmed": "/production/scores/compute",
    "hot.release_gate.preopen": "/production/release-gate/evaluate",
    "hot.buy_point.open_5m": "/production/buy-point/evaluate",
    "hot.observe.intraday": "/production/observations/bulk",
    "hot.outcome.t5_t20": "/production/outcomes/mature",
    "hot.evolution.offline": "/production/evolution/build",
    # Candidate memory locked service endpoints.
    "memory.seed.from_hot_signals": "/production/seed/build",
    "memory.pre_signal.scan": "/production/pre-signal/detect",
    "memory.release_gate.close": "/production/release-gate/evaluate",
    "memory.buy_point.next_session_reference": "/production/buy-point/evaluate",
    "memory.observe.outcome.evolution": "/production/outcomes/mature",
    # Ambush watchlist locked-candidate service endpoints.
    "ambush.source_capability.audit": "/ambush/source-capability-audit",
    "ambush.pattern_library.mine": "/ambush/historical-valley-sample-label",
    "ambush.phase2.valley_turn.close": "/ambush/phase2/run",
    "ambush.phase3.release_gate.close": "/ambush/phase3/run",
    "ambush.buy_point.reference": "/ambush/phase3/run",
    "ambush.observe.outcome.evolution": "/ambush/phase4/outcome",
}

DEFAULT_PATH_BY_KIND: dict[str, str] = {
    "source_collect": "/source/facts/collect",
    "model_compute": "/production/scores/compute",
    "release_gate": "/production/release-gate/evaluate",
    "buy_point": "/production/buy-point/evaluate",
    "observation": "/production/observations/bulk",
    "outcome": "/production/outcomes/mature",
    "evolution": "/production/evolution/build",
}


def _sample_bar_rows(trading_day: str) -> list[dict[str, Any]]:
    # Deterministic, contract-shaped bars for live-dispatch payload validation.
    # They are not market facts and must not be used as model evidence.
    dates = [
        "2026-04-22",
        "2026-04-23",
        "2026-04-24",
        "2026-04-27",
        "2026-04-28",
        "2026-04-29",
        "2026-04-30",
        "2026-05-06",
        "2026-05-07",
        "2026-05-08",
        "2026-05-11",
        "2026-05-12",
        "2026-05-13",
        "2026-05-14",
        "2026-05-15",
        "2026-05-18",
        "2026-05-19",
        "2026-05-20",
        "2026-05-21",
        "2026-05-22",
        "2026-05-25",
        "2026-05-26",
        "2026-05-27",
        "2026-05-28",
        "2026-05-29",
        "2026-06-01",
        "2026-06-02",
        "2026-06-03",
        "2026-06-04",
        "2026-06-05",
        "2026-06-08",
        "2026-06-09",
        "2026-06-10",
        "2026-06-11",
        trading_day,
    ]
    rows: list[dict[str, Any]] = []
    for index, day in enumerate(dates):
        close = round(29.8 + index * 0.18, 2)
        rows.append(
            {
                "trading_day": day,
                "trade_date": day,
                "open": close - 0.1,
                "high": close + 0.35,
                "low": close - 0.45,
                "close": close,
                "close_price": close,
                "volume": 100_000_000 + index,
                "amount": 100_000_000 + index * 10_000,
                "available_at": "2026-06-13T03:05:07Z",
            }
        )
    rows[-1].update(
        {
            "open": 38.60,
            "high": 38.70,
            "low": 36.15,
            "close": 36.35,
            "close_price": 36.35,
            "volume": 261_471_118,
            "amount": 9_702_654_429.79,
        }
    )
    return rows


def build_live_dispatch_sample_payload(
    task_code: str,
    *,
    trading_day: str = "2026-06-12",
    as_of_time_utc: str = "2026-06-13T03:10:00Z",
) -> dict[str, Any]:
    """Return a deterministic business payload for scheduler live-dispatch probing.

    The payload is shaped for scheduler input, not for direct owner-service calls.
    ThreeModelLiveDispatcher.request_body_for performs the owner-specific wrapping.
    """

    if task_code == "hot.release_gate.preopen":
        return {
            "run_id": f"sample-hot-release-{trading_day}",
            "as_of_time_utc": as_of_time_utc,
            "row": {
                "instrument_id": 63,
                "symbol": "000063.SZ",
                "name": "ZTE",
                "p_limit_up": 0.62,
                "p_limit_up_source": "scheduler_live_dispatch_contract_sample",
                "contract_audit_status": "passed",
                "ingest_mode": "external_ths_model",
                "reference_entry_price": 36.35,
                "daily_bars": [_sample_bar_rows(trading_day)[-1]],
            },
        }
    if task_code == "memory.release_gate.close":
        return {
            "run_id": f"sample-memory-release-{trading_day}",
            "as_of_time_utc": as_of_time_utc,
            "instrument_id": 63,
            "symbol": "000063.SZ",
            "memory_id": "sample-memory-000063",
            "appearance_id": "sample-appearance-000063",
            "appearance_count": 1,
            "ingest_mode": "external_ths_model",
            "contract_audit_status": "passed",
            "p_limit_up": 0.62,
            "p_limit_up_source": "scheduler_live_dispatch_contract_sample",
            "memory_age_days": 5,
            "daily_bars": [_sample_bar_rows(trading_day)[-1]],
        }
    if task_code == "ambush.phase3.release_gate.close":
        return {
            "instrument": {
                "instrument_id": 63,
                "symbol": "000063",
                "exchange": "SZ",
                "is_active": True,
                "is_st": False,
                "is_suspended": False,
                "is_delisting_risk": False,
            },
            "valley_watch": {
                "symbol": "000063",
                "instrument_id": 63,
                "pool_state": "valley_watch",
                "price_adjustment_mode": "adjusted_ohlc",
                "valley_maturity_score": 72,
                "bottom_stability_score": 68,
                "weekly_structure_score": 64,
                "volume_structure_score": 70,
                "false_rebound_risk": 35,
                "hard_negative_similarity": 20,
                "source_gap_codes": [],
            },
            "effective_turn_anchor": {
                "symbol": "000063",
                "instrument_id": 63,
                "l1_status": "accepted",
                "effective_turn_score": 75,
                "turn_freshness_score": 80,
                "support_hold_score": 70,
                "micro_breakout_quality": 72,
                "runaway_risk": 20,
                "upper_shadow_risk": 18,
                "source_gap_codes": [],
            },
            "bars": _sample_bar_rows(trading_day),
            "moneyflow_context": {
                "outflow_decay_score": 72,
                "net_inflow_turning_score": 70,
                "intraday_support_flow_score": 68,
            },
            "sector_context": {
                "sector_relative_strength_score": 70,
                "sector_breadth_repair_score": 68,
            },
            "market_context": {
                "market_risk_appetite_score": 66,
                "limit_up_environment_score": 62,
            },
            "tradability_context": {
                "tradability_score": 85,
                "liquidity_score": 88,
            },
            "as_of_trading_day": trading_day,
            "as_of_time": as_of_time_utc,
        }
    raise ValueError(f"no live-dispatch sample payload for task_code: {task_code}")


class ThreeModelLiveDispatcher:
    """Dispatch three-model scheduler tasks to their owner services.

    The dispatcher is deliberately generic, but it does not infer success. A live
    call is accepted only when the owner service returns a 2xx response. Source
    tasks cannot publish official signals, and append-only tasks cannot be run if
    their task definition violates the append-only contract.
    """

    def __init__(self, registry: OwnerEndpointRegistry, client: DispatchHttpClient | None = None) -> None:
        self.registry = registry
        self.client = client or httpx.Client()
        self.tasks: dict[str, ScheduledTask] = {task.task_code: task for task in THREE_MODEL_TASKS}

    @staticmethod
    def path_for(task: ScheduledTask) -> str:
        return TASK_CODE_PATH_OVERRIDES.get(task.task_code) or DEFAULT_PATH_BY_KIND.get(task.task_kind, "/healthz")

    @staticmethod
    def _scheduler_context(task: ScheduledTask) -> dict[str, Any]:
        return {
            "task_code": task.task_code,
            "task_kind": task.task_kind,
            "owner_service": task.owner_service,
            "append_only": task.append_only,
            "is_official_publish": task.is_official_publish,
            "reads_from": task.reads_from,
            "writes_to": task.writes_to,
        }

    @classmethod
    def request_body_for(cls, task: ScheduledTask, payload: dict[str, Any]) -> dict[str, Any]:
        """Build the body expected by the current owner-service API contract."""
        context = cls._scheduler_context(task)
        run_id = payload.get("run_id") or task.task_code
        control_fields = {"run_id", "as_of_time_utc"}
        business_payload = {key: value for key, value in payload.items() if key not in control_fields}
        if task.owner_service == "hot-candidates-service":
            body_payload = dict(business_payload)
            body_payload.setdefault("_scheduler_context", context)
            body = {
                "payload": body_payload,
                "run_id": run_id,
            }
            if payload.get("as_of_time_utc") is not None:
                body["as_of_time_utc"] = payload["as_of_time_utc"]
            return body
        if task.owner_service == "candidate-memory-service":
            row = dict(business_payload)
            row.setdefault("_scheduler_context", context)
            body = {
                "row": row,
                "run_id": run_id,
            }
            if payload.get("as_of_time_utc") is not None:
                body["as_of_time_utc"] = payload["as_of_time_utc"]
            return body
        if task.owner_service == "ambush-watchlist-service":
            body = dict(payload)
            body.setdefault("_scheduler_context", context)
            return body
        return {
            **context,
            "payload": payload,
        }

    def validate_task_contract(self, task: ScheduledTask) -> None:
        if task.task_kind == "source_collect" and task.is_official_publish:
            raise RuntimeError("source collection cannot publish official model facts")
        if task.task_kind in {"observation", "outcome", "evolution"} and not task.append_only:
            raise RuntimeError(f"{task.task_kind} task must be append-only")
        if task.is_official_publish and task.task_kind != "release_gate":
            raise RuntimeError("only release_gate tasks may publish official model signals")

    def dispatch(self, task_code: str, *, payload: dict[str, Any]) -> ThreeModelDispatchResult:
        task = self.tasks.get(task_code)
        if task is None:
            raise ValueError(f"unknown three-model task: {task_code}")
        self.validate_task_contract(task)
        base_url = self.registry.resolve(task.owner_service)
        url = f"{base_url}{self.path_for(task)}"
        request_payload = self.request_body_for(task, payload)
        response = self.client.post(url, json=request_payload, timeout=30.0)
        status_code = int(getattr(response, "status_code", 0))
        try:
            body = response.json()
        except Exception:  # noqa: BLE001
            body = {"text": str(getattr(response, "text", ""))[:500]}
        accepted = 200 <= status_code < 300
        return ThreeModelDispatchResult(
            contract_kind="three_model_live_dispatch_result_v1",
            dispatcher_version=THREE_MODEL_LIVE_DISPATCH_VERSION,
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
