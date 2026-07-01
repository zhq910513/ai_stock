from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

import httpx

from scheduler_service.hot_plan import ScheduledTask
from scheduler_service.three_model_plan import THREE_MODEL_TASKS

THREE_MODEL_LIVE_DISPATCH_VERSION = "three_model_live_dispatch_v1"
THREE_MODEL_LIVE_DISPATCH_SAMPLE_VERSION = "three_model_live_dispatch_sample_v1"
MODEL_PAYLOAD_PREFLIGHT_VERSION = "scheduler_model_payload_preflight_v1"
RESEARCH_PAYLOAD_ASSEMBLER_CONTRACT = "research_model_payload_assembler_v1"
ASSEMBLED_RESEARCH_PAYLOAD_STATUS = "assembled_research_payload"
PAYLOAD_ASSEMBLY_REQUIRED_GAP = "scheduler_payload_assembly_required"
MODEL_OWNER_SERVICES = (
    "hot-candidates-service",
    "candidate-memory-service",
    "ambush-watchlist-service",
    "t-board-relay-service",
)
OFFICIAL_RELEASE_GATE_TASKS = (
    "hot.release_gate.preopen",
    "memory.release_gate.close",
    "ambush.phase3.release_gate.close",
)
LIVE_DISPATCH_SAMPLE_TASKS = OFFICIAL_RELEASE_GATE_TASKS + (
    "t_relay.day1.scan.close",
    "t_relay.day2.watch.rolling_5m",
    "t_relay.day2.trigger.rolling_5m",
    "t_relay.day2.post_entry.monitor",
    "t_relay.day3.exit.open",
    "t_relay.day3.exit.tail",
    "t_relay.observation.monitor.snapshot_5m",
    "t_relay.live_result.compute_30m",
    "t_relay.outcome.build",
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


@dataclass(frozen=True)
class ModelPayloadPreflightResult:
    contract_kind: str
    preflight_version: str
    task_code: str
    owner_service: str | None
    valid: bool
    failure_codes: list[str]
    gap_codes: list[str]
    required_contract: str
    required_status: str
    official_publish: bool
    checked_at: datetime
    hard_rules: list[str]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["checked_at"] = self.checked_at.isoformat()
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
    # T-board relay research model endpoints.
    "t_relay.day1.scan.close": "/t-board-relay/day1/scan",
    "t_relay.day2.watch.rolling_5m": "/t-board-relay/day2/watch",
    "t_relay.day2.trigger.rolling_5m": "/t-board-relay/day2/trigger-check",
    "t_relay.day2.post_entry.monitor": "/t-board-relay/post-entry/monitor",
    "t_relay.day3.exit.open": "/t-board-relay/day3/exit-check",
    "t_relay.day3.exit.tail": "/t-board-relay/day3/exit-check",
    "t_relay.observation.monitor.snapshot_5m": "/t-board-relay/observation-monitor/snapshot",
    "t_relay.live_result.compute_30m": "/t-board-relay/observation-monitor/snapshot",
    "t_relay.outcome.build": "/t-board-relay/outcomes/build",
}

DEFAULT_PATH_BY_KIND: dict[str, str] = {
    "source_collect": "/source/fetch/submit",
    "model_compute": "/production/scores/compute",
    "release_gate": "/production/release-gate/evaluate",
    "buy_point": "/production/buy-point/evaluate",
    "observation": "/production/observations/bulk",
    "outcome": "/production/outcomes/mature",
    "evolution": "/production/evolution/build",
}


def _walk_values(value: Any) -> list[Any]:
    values = [value]
    if isinstance(value, dict):
        for item in value.values():
            values.extend(_walk_values(item))
    elif isinstance(value, list):
        for item in value:
            values.extend(_walk_values(item))
    return values


def _collect_gap_codes(value: Any) -> list[str]:
    codes: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"source_gap_codes", "contract_gaps", "gap_codes", "blocking_gap_codes"}:
                if isinstance(item, list):
                    codes.extend(str(code) for code in item)
                elif item:
                    codes.append(str(item))
            codes.extend(_collect_gap_codes(item))
    elif isinstance(value, list):
        for item in value:
            codes.extend(_collect_gap_codes(item))
    return sorted(set(codes))


def _contains_sample_marker(value: Any) -> bool:
    for item in _walk_values(value):
        if not isinstance(item, str):
            continue
        text = item.lower()
        if "scheduler_live_dispatch_contract_sample" in text:
            return True
        if text.startswith("sample-") or text.startswith("sample_"):
            return True
    return False


def _source_preflight_passed(payload: dict[str, Any]) -> bool:
    source_preflight = payload.get("source_preflight")
    if not isinstance(source_preflight, dict):
        return False
    can_release = source_preflight.get("can_release_official_signal")
    blocking_reasons = source_preflight.get("blocking_reasons") or []
    coverage = str(source_preflight.get("coverage_status") or "passed").lower()
    freshness = str(source_preflight.get("freshness_status") or "passed").lower()
    return (
        can_release is True
        and isinstance(blocking_reasons, list)
        and not blocking_reasons
        and coverage in {"passed", "ready", "ok"}
        and freshness in {"passed", "ready", "ok"}
    )


def _task_lookup() -> dict[str, ScheduledTask]:
    return {task.task_code: task for task in THREE_MODEL_TASKS}


def model_payload_requirements() -> dict[str, Any]:
    rows = []
    for task in THREE_MODEL_TASKS:
        if task.owner_service not in MODEL_OWNER_SERVICES:
            continue
        rows.append(
            {
                "task_code": task.task_code,
                "task_kind": task.task_kind,
                "owner_service": task.owner_service,
                "official_publish": task.is_official_publish,
                "required_contract": RESEARCH_PAYLOAD_ASSEMBLER_CONTRACT,
                "required_status": ASSEMBLED_RESEARCH_PAYLOAD_STATUS,
                "requires_source_preflight_passed": task.is_official_publish,
                "forbidden_gap_code": PAYLOAD_ASSEMBLY_REQUIRED_GAP,
                "forbidden_sample_marker": "scheduler_live_dispatch_contract_sample",
            }
        )
    return {
        "contract_kind": "scheduler_model_payload_requirements_v1",
        "preflight_version": MODEL_PAYLOAD_PREFLIGHT_VERSION,
        "assembler_contract": RESEARCH_PAYLOAD_ASSEMBLER_CONTRACT,
        "required_status": ASSEMBLED_RESEARCH_PAYLOAD_STATUS,
        "task_count": len(rows),
        "tasks": rows,
        "hard_rules": [
            "Scheduler model time wheel cannot live-dispatch scheduler_payload_assembly_required payloads.",
            "Scheduler live dispatch samples are request-shape probes only and never production model facts.",
            "Official release gate payloads must carry a passed source_preflight block.",
        ],
    }


def preflight_model_dispatch_payload(task_code: str, payload: dict[str, Any]) -> ModelPayloadPreflightResult:
    tasks = _task_lookup()
    task = tasks.get(task_code)
    checked_at = datetime.now(timezone.utc)
    hard_rules = [
        "Do not live-dispatch missing-fact scheduler payloads.",
        "Do not live-dispatch scheduler sample payloads.",
        "Do not infer or fill model inputs in scheduler.",
    ]
    if task is None:
        return ModelPayloadPreflightResult(
            contract_kind="scheduler_model_payload_preflight_result_v1",
            preflight_version=MODEL_PAYLOAD_PREFLIGHT_VERSION,
            task_code=task_code,
            owner_service=None,
            valid=False,
            failure_codes=["unknown_task_code"],
            gap_codes=[],
            required_contract=RESEARCH_PAYLOAD_ASSEMBLER_CONTRACT,
            required_status=ASSEMBLED_RESEARCH_PAYLOAD_STATUS,
            official_publish=False,
            checked_at=checked_at,
            hard_rules=hard_rules,
        )
    if task.owner_service not in MODEL_OWNER_SERVICES:
        return ModelPayloadPreflightResult(
            contract_kind="scheduler_model_payload_preflight_result_v1",
            preflight_version=MODEL_PAYLOAD_PREFLIGHT_VERSION,
            task_code=task.task_code,
            owner_service=task.owner_service,
            valid=True,
            failure_codes=[],
            gap_codes=[],
            required_contract=RESEARCH_PAYLOAD_ASSEMBLER_CONTRACT,
            required_status=ASSEMBLED_RESEARCH_PAYLOAD_STATUS,
            official_publish=task.is_official_publish,
            checked_at=checked_at,
            hard_rules=hard_rules,
        )
    failure_codes: list[str] = []
    if not isinstance(payload, dict):
        payload = {}
        failure_codes.append("payload_not_object")
    gap_codes = _collect_gap_codes(payload)
    if PAYLOAD_ASSEMBLY_REQUIRED_GAP in gap_codes:
        failure_codes.append("payload_assembly_required_gap_present")
    if payload.get("scheduler_payload_status") == "blocked_payload_assembly_required":
        failure_codes.append("scheduler_payload_status_blocked")
    if _contains_sample_marker(payload):
        failure_codes.append("sample_payload_marker_present")
    if payload.get("payload_assembly_contract") != RESEARCH_PAYLOAD_ASSEMBLER_CONTRACT:
        failure_codes.append("payload_assembly_contract_missing")
    if payload.get("payload_assembly_status") != ASSEMBLED_RESEARCH_PAYLOAD_STATUS:
        failure_codes.append("payload_assembly_status_not_ready")
    if not payload.get("payload_assembly_source"):
        failure_codes.append("payload_assembly_source_missing")
    if task.is_official_publish and not _source_preflight_passed(payload):
        failure_codes.append("source_preflight_not_passed")
    failure_codes = sorted(set(failure_codes))
    return ModelPayloadPreflightResult(
        contract_kind="scheduler_model_payload_preflight_result_v1",
        preflight_version=MODEL_PAYLOAD_PREFLIGHT_VERSION,
        task_code=task.task_code,
        owner_service=task.owner_service,
        valid=not failure_codes,
        failure_codes=failure_codes,
        gap_codes=gap_codes,
        required_contract=RESEARCH_PAYLOAD_ASSEMBLER_CONTRACT,
        required_status=ASSEMBLED_RESEARCH_PAYLOAD_STATUS,
        official_publish=task.is_official_publish,
        checked_at=checked_at,
        hard_rules=hard_rules,
    )


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
    if task_code == "t_relay.day1.scan.close":
        return {
            "run_id": f"sample-t-relay-day1-{trading_day}",
            "trade_date": trading_day,
            "rows": [
                {
                    "symbol": "000759.SZ",
                    "canonical_symbol": "000759.SZ",
                    "stock_name": "ZB Group",
                    "trade_date": trading_day,
                    "open_price": "5.29",
                    "high_price": "5.83",
                    "low_price": "5.16",
                    "close_price": "5.83",
                    "pre_close_price": "5.30",
                    "up_limit_price": "5.83",
                    "float_market_cap": "3822766125.75",
                    "limit_open_count": 1,
                    "close_on_limit_flag": True,
                    "is_one_word_board": False,
                }
            ],
        }
    if task_code == "t_relay.day2.watch.rolling_5m":
        return {
            "run_id": f"sample-t-relay-watch-{trading_day}",
            "as_of_time_utc": as_of_time_utc,
            "day1_candidate_id": f"tbr-day1-000759.SZ-{trading_day}",
            "canonical_symbol": "000759.SZ",
            "day2_trade_date": trading_day,
            "as_of_time": "2026-06-12T01:35:00Z",
            "monitor_interval_minutes": 5,
            "monitor_check_time": "09:35:00",
            "first_qualified_monitor_time": "09:35:00",
            "last_price_at_watch": "5.78",
            "up_limit_price": "5.83",
            "market_context_status": "neutral",
        }
    if task_code == "t_relay.day2.trigger.rolling_5m":
        return {
            "run_id": f"sample-t-relay-trigger-{trading_day}",
            "as_of_time_utc": as_of_time_utc,
            "day1_candidate_id": f"tbr-day1-000759.SZ-{trading_day}",
            "day1_candidate_status": "rejected",
            "canonical_symbol": "000759.SZ",
            "day2_trade_date": trading_day,
            "trigger_time": "09:35:00",
            "monitor_interval_minutes": 5,
            "first_qualified_monitor_time": "09:35:00",
            "last_price_at_trigger": "5.78",
            "up_limit_price": "5.83",
            "distance_to_up_limit_pct": "0.008576",
            "market_context_status": "neutral",
            "p0_order_book_complete": True,
            "p0_trade_tick_complete": True,
            "aggressive_buy_sweep_amount": "121998001",
            "order_consumption_amount": "121998001",
        }
    if task_code == "t_relay.day2.post_entry.monitor":
        return {
            "run_id": f"sample-t-relay-monitor-{trading_day}",
            "entry_trigger_id": f"tbr-entry-000759.SZ-{trading_day}",
            "canonical_symbol": "000759.SZ",
            "day2_trade_date": trading_day,
            "post_entry_board_opened": False,
            "close_on_limit_flag": True,
            "entry_price": "5.83",
            "up_limit_price": "5.83",
        }
    if task_code == "t_relay.day3.exit.open":
        return {
            "run_id": f"sample-t-relay-day3-open-{trading_day}",
            "entry_trigger_id": f"tbr-entry-000759.SZ-{trading_day}",
            "canonical_symbol": "000759.SZ",
            "day3_trade_date": trading_day,
            "day3_open_limit_up_flag": True,
            "day3_tail_limit_up_flag": True,
            "open_price": "6.41",
            "up_limit_price": "6.41",
        }
    if task_code == "t_relay.day3.exit.tail":
        return {
            "run_id": f"sample-t-relay-day3-tail-{trading_day}",
            "entry_trigger_id": f"tbr-entry-000759.SZ-{trading_day}",
            "canonical_symbol": "000759.SZ",
            "day3_trade_date": trading_day,
            "day3_open_limit_up_flag": False,
            "day3_tail_limit_up_flag": False,
            "tail_price": "6.12",
            "up_limit_price": "6.41",
        }
    if task_code == "t_relay.observation.monitor.snapshot_5m":
        return {
            "run_id": f"sample-t-relay-observation-snapshot-{trading_day}",
            "as_of_time_utc": as_of_time_utc,
            "trade_date": trading_day,
            "limit": 500,
            "monitor_interval_minutes": 5,
        }
    if task_code == "t_relay.live_result.compute_30m":
        return {
            "run_id": f"sample-t-relay-live-result-{trading_day}",
            "as_of_time_utc": as_of_time_utc,
            "trade_date": trading_day,
            "limit": 500,
            "monitor_interval_minutes": 30,
            "result_kind": "model_result_30m",
        }
    if task_code == "t_relay.outcome.build":
        return {
            "run_id": f"sample-t-relay-outcome-{trading_day}",
            "entry_trigger_id": f"tbr-entry-000759.SZ-{trading_day}",
            "day1_candidate_id": f"tbr-day1-000759.SZ-{trading_day}",
            "canonical_symbol": "000759.SZ",
            "day1_trade_date": trading_day,
            "day2_trade_date": trading_day,
            "day3_trade_date": trading_day,
            "post_entry_monitor": {
                "entry_trigger_id": f"tbr-entry-000759.SZ-{trading_day}",
                "canonical_symbol": "000759.SZ",
                "day2_trade_date": trading_day,
                "post_entry_status": "SEALED_TO_CLOSE",
                "post_entry_board_opened": False,
                "close_on_limit_flag": True,
                "entry_price": "5.83",
            },
            "day3_decision": {
                "entry_trigger_id": f"tbr-entry-000759.SZ-{trading_day}",
                "canonical_symbol": "000759.SZ",
                "day3_trade_date": trading_day,
                "day3_open_limit_up_flag": True,
                "tail_limit_up_flag": True,
                "day3_action": "hold_open_limit",
            },
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
        if task.owner_service == "source-data-service":
            body = dict(business_payload)
            body.setdefault("request_source", "scheduler-service")
            idempotency_slot = body.get("trade_date") or body.get("start_date") or body.get("end_date") or run_id
            body.setdefault("idempotency_key", f"{task.task_code}:{idempotency_slot}")
            return body
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
        if task.owner_service == "t-board-relay-service":
            body = dict(business_payload)
            body.setdefault("_scheduler_context", context)
            if task.task_code == "t_relay.day1.scan.close":
                rows = body.get("rows")
                return {
                    "rows": rows if isinstance(rows, list) else [body],
                    "trade_date": body.get("trade_date"),
                    "run_id": run_id,
                    "as_of_time_utc": payload.get("as_of_time_utc"),
                }
            return {
                "payload": body,
                "run_id": run_id,
                "as_of_time_utc": payload.get("as_of_time_utc"),
            }
        return {
            **context,
            "payload": payload,
        }

    def validate_task_contract(self, task: ScheduledTask) -> None:
        if task.task_kind == "source_collect" and task.is_official_publish:
            raise RuntimeError("source collection cannot publish official model facts")
        if task.task_code.startswith("source.") and task.owner_service != "source-data-service":
            raise RuntimeError("source fetch tasks must be owned by source-data-service")
        if any(source.startswith("provider.") for source in task.reads_from):
            raise RuntimeError("scheduler tasks must not read provider.* directly")
        if any(source.startswith("raw.") or source.startswith("raw_") for source in task.reads_from):
            raise RuntimeError("scheduler tasks must not read raw_* directly")
        if task.task_kind in {"observation", "outcome", "evolution"} and not task.append_only:
            raise RuntimeError(f"{task.task_kind} task must be append-only")
        if task.is_official_publish and task.task_kind != "release_gate":
            raise RuntimeError("only release_gate tasks may publish official model signals")

    def dispatch(self, task_code: str, *, payload: dict[str, Any]) -> ThreeModelDispatchResult:
        task = self.tasks.get(task_code)
        if task is None:
            raise ValueError(f"unknown three-model task: {task_code}")
        self.validate_task_contract(task)
        payload_preflight = preflight_model_dispatch_payload(task_code, payload)
        if not payload_preflight.valid:
            raise RuntimeError(
                "model payload preflight failed: "
                + ",".join(payload_preflight.failure_codes)
            )
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
