from __future__ import annotations

import os
import tempfile
import threading
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Protocol
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import httpx

from scheduler_service.source_schedule import (
    EXPLICIT_MODEL_STAGE_CANDIDATE_SOURCE,
    SOURCE_FETCH_SCHEDULES,
    SOURCE_TIME_WHEEL_VERSION,
    T_RELAY_DAY1_QUALIFIED_STAGE_CANDIDATE_SOURCE,
    T_RELAY_LIMIT_EVENT_STAGE_CANDIDATE_SOURCE,
    due_source_fetch_instances,
    materialize_source_fetch_schedule,
)
from scheduler_service.task_store import SchedulerSQLiteTaskStore
from scheduler_service.three_model_materializer import (
    DEFAULT_MARKET_TZ,
    THREE_MODEL_MATERIALIZER_VERSION,
    materialize_three_model_day,
)
from scheduler_service.three_model_plan import THREE_MODEL_TASKS

SCHEDULER_RUNTIME_VERSION = "scheduler_runtime_guard_v2"
MODEL_TIME_WHEEL_VERSION = "scheduler_model_time_wheel_v1"
RESEARCH_MODEL_EXECUTION_DISPATCH_VERSION = "scheduler_research_model_execution_dispatch_v1"
MODEL_OWNER_SERVICES = (
    "hot-candidates-service",
    "candidate-memory-service",
    "ambush-watchlist-service",
    "t-board-relay-service",
)
MODEL_SERVICE_BY_CODE = {
    "hot_candidates": "hot-candidates-service",
    "candidate_memory": "candidate-memory-service",
    "ambush_watchlist": "ambush-watchlist-service",
    "t_board_relay": "t-board-relay-service",
}
MODEL_CODE_BY_OWNER_SERVICE = {owner: code for code, owner in MODEL_SERVICE_BY_CODE.items()}
MODEL_CODE_ALIASES = {
    "hot": "hot_candidates",
    "hot_candidates": "hot_candidates",
    "hot_candidates_service": "hot_candidates",
    "candidate_memory": "candidate_memory",
    "candidate_memory_service": "candidate_memory",
    "memory": "candidate_memory",
    "ambush": "ambush_watchlist",
    "ambush_watchlist": "ambush_watchlist",
    "ambush_watchlist_service": "ambush_watchlist",
    "model4": "t_board_relay",
    "model_four": "t_board_relay",
    "t_board": "t_board_relay",
    "t_board_relay": "t_board_relay",
    "t_board_relay_service": "t_board_relay",
    "t_relay": "t_board_relay",
}
TERMINAL_MODEL_EXECUTION_STATUSES = {
    "blocked_data_gap",
    "materialized_with_gaps",
    "materialization_skipped",
}
T_RELAY_DAY1_SCAN_TASK_CODE = "t_relay.day1.scan.close"
T_RELAY_DAY1_STAGE_CANDIDATES_MISSING_GAP = "source_gap:t_relay_day1_stage_candidates_missing"
PREFLIGHT_DECISION_TIMES_LOCAL = {
    ("hot_candidates", "preopen_release_gate"): time(9, 29, 40),
    ("candidate_memory", "outcome_label"): time(16, 5, 0),
    ("ambush_watchlist", "release_gate"): time(16, 5, 0),
    ("t_board_relay", "day1_scan"): time(15, 10, 0),
    ("t_board_relay", "day2_trigger"): time(9, 30, 0),
}


def _source_preflight_decision_time(trade_date_text: str, model_code: str, model_phase: str) -> str:
    local_time = PREFLIGHT_DECISION_TIMES_LOCAL.get((model_code, model_phase), time(15, 0, 0))
    local_date = datetime.fromisoformat(str(trade_date_text)).date()
    local_dt = datetime.combine(local_date, local_time).replace(tzinfo=ZoneInfo(DEFAULT_MARKET_TZ))
    return local_dt.isoformat()


def _is_historical_guard_trade_date(
    trade_date_text: str,
    *,
    checked_at: datetime,
    market_timezone: ZoneInfo,
) -> bool:
    try:
        guard_date = datetime.fromisoformat(str(trade_date_text)).date()
    except ValueError:
        return False
    checked = checked_at
    if checked.tzinfo is None:
        checked = checked.replace(tzinfo=timezone.utc)
    return guard_date < checked.astimezone(market_timezone).date()


def _preflight_blockers_are_late_only(blocking_reasons: list[Any]) -> bool:
    return bool(blocking_reasons) and all(str(reason).endswith(":late") for reason in blocking_reasons)


def _parse_required_model_codes(value: list[str] | tuple[str, ...] | str | None) -> tuple[str, ...]:
    if value is None:
        return tuple(MODEL_SERVICE_BY_CODE)
    if isinstance(value, str):
        text = value.strip()
        lowered = text.lower()
        if lowered in {"all", "*"}:
            return tuple(MODEL_SERVICE_BY_CODE)
        if lowered in {"", "none", "disabled", "off", "false"}:
            return ()
        tokens = [token.strip() for token in text.replace(";", ",").replace(" ", ",").split(",") if token.strip()]
    else:
        tokens = [str(token).strip() for token in value if str(token).strip()]
    required: set[str] = set()
    for token in tokens:
        normalized = token.lower().replace("-", "_")
        if normalized in {"all", "*"}:
            return tuple(MODEL_SERVICE_BY_CODE)
        if normalized in {"none", "disabled", "off", "false"}:
            continue
        model_code = MODEL_CODE_ALIASES.get(normalized)
        if model_code is None:
            raise ValueError(f"unknown required model service: {token}")
        required.add(model_code)
    return tuple(code for code in MODEL_SERVICE_BY_CODE if code in required)


class RuntimeHttpClient(Protocol):
    def get(self, url: str, *, timeout: float) -> Any: ...

    def post(self, url: str, *, json: dict[str, Any], timeout: float) -> Any: ...


@dataclass
class RuntimeSnapshot:
    runtime_version: str = SCHEDULER_RUNTIME_VERSION
    service: str = "scheduler-service"
    started_at: datetime | None = None
    heartbeat_at: datetime | None = None
    background_loop_running: bool = False
    background_loop_last_error: str | None = None
    guard_mode: str = "current_closure"
    closure_guard_status: str = "not_started"
    closure_guard_error: str | None = None
    closure_guard_checked_at: datetime | None = None
    closure_guard_details: dict[str, Any] = field(default_factory=dict)
    startup_guard_status: str = "not_started"
    startup_guard_run_id: str | int | None = None
    startup_guard_inspection_status: str | None = None
    startup_guard_p0_gap_count: int | None = None
    startup_guard_p1_gap_count: int | None = None
    startup_guard_error: str | None = None
    data_inspector_status: str = "unknown"
    data_inspector_error: str | None = None
    data_inspector_checked_at: datetime | None = None
    data_inspector_base_url: str = ""
    poll_seconds: float = 30.0
    source_time_wheel_enabled: bool = True
    source_time_wheel_live_submit: bool = True
    source_time_wheel_status: str = "not_started"
    source_time_wheel_error: str | None = None
    source_time_wheel_checked_at: datetime | None = None
    source_time_wheel_details: dict[str, Any] = field(default_factory=dict)
    model_time_wheel_enabled: bool = True
    model_time_wheel_live_dispatch: bool = False
    model_time_wheel_status: str = "not_started"
    model_time_wheel_error: str | None = None
    model_time_wheel_checked_at: datetime | None = None
    model_time_wheel_details: dict[str, Any] = field(default_factory=dict)
    task_store_path: str = ""
    warning_codes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in (
            "started_at",
            "heartbeat_at",
            "closure_guard_checked_at",
            "data_inspector_checked_at",
            "source_time_wheel_checked_at",
            "model_time_wheel_checked_at",
        ):
            value = payload.get(key)
            if isinstance(value, datetime):
                payload[key] = value.isoformat()
        return payload


class SchedulerRuntime:
    """Runtime guard for scheduler readiness.

    The runtime starts a lightweight heartbeat loop, triggers a data-inspector
    startup guard once, and keeps a structured readiness snapshot. It does not
    execute model tasks or write business facts.
    """

    def __init__(
        self,
        *,
        client: RuntimeHttpClient | None = None,
        guard_mode: str | None = None,
        source_data_base_url: str | None = None,
        hot_candidates_base_url: str | None = None,
        candidate_memory_base_url: str | None = None,
        ambush_watchlist_base_url: str | None = None,
        t_board_relay_base_url: str | None = None,
        research_service_base_url: str | None = None,
        guard_trade_date: str | None = None,
        guard_symbol: str | None = None,
        t_board_guard_symbol: str | None = None,
        data_inspector_base_url: str | None = None,
        source_time_wheel_enabled: bool | None = None,
        source_time_wheel_live_submit: bool | None = None,
        source_time_wheel_symbols: list[str] | str | None = None,
        source_time_wheel_lateness_seconds: int | None = None,
        source_time_wheel_max_dispatch: int | None = None,
        model_time_wheel_enabled: bool | None = None,
        model_time_wheel_live_dispatch: bool | None = None,
        model_time_wheel_include_research_intraday: bool | None = None,
        model_time_wheel_lateness_seconds: int | None = None,
        model_time_wheel_max_dispatch: int | None = None,
        task_store: SchedulerSQLiteTaskStore | None = None,
        task_store_path: str | None = None,
        poll_seconds: float | None = None,
        request_timeout_seconds: float | None = None,
        startup_guard_request_timeout_seconds: float | None = None,
        startup_guard_scope: str | None = None,
        startup_guard_lookback_days: int | None = None,
        startup_guard_max_subjects: int | None = None,
        startup_guard_retry_attempts: int | None = None,
        required_model_services: list[str] | tuple[str, ...] | str | None = None,
    ) -> None:
        self.client = client or httpx.Client()
        self.guard_mode = (guard_mode or os.getenv("SCHEDULER_GUARD_MODE") or "current_closure").strip().lower()
        self.source_data_base_url = (
            source_data_base_url
            or os.getenv("SOURCE_DATA_SERVICE_BASE_URL")
            or os.getenv("source_data_service_base_url")
            or "http://source-data-service:8041"
        ).rstrip("/")
        self.model_base_urls = {
            "hot_candidates": (
                hot_candidates_base_url
                or os.getenv("HOT_CANDIDATES_SERVICE_BASE_URL")
                or "http://hot-candidates-service:8031"
            ).rstrip("/"),
            "candidate_memory": (
                candidate_memory_base_url
                or os.getenv("CANDIDATE_MEMORY_SERVICE_BASE_URL")
                or "http://candidate-memory-service:8032"
            ).rstrip("/"),
            "ambush_watchlist": (
                ambush_watchlist_base_url
                or os.getenv("AMBUSH_WATCHLIST_SERVICE_BASE_URL")
                or "http://ambush-watchlist-service:8033"
            ).rstrip("/"),
            "t_board_relay": (
                t_board_relay_base_url
                or os.getenv("T_BOARD_RELAY_SERVICE_BASE_URL")
                or "http://t-board-relay-service:8034"
            ).rstrip("/"),
        }
        env_required_model_services = os.environ.get("SCHEDULER_REQUIRED_MODEL_SERVICES")
        if env_required_model_services is None:
            env_required_model_services = os.environ.get("SCHEDULER_REQUIRED_MODEL_CODES")
        self.required_model_codes = _parse_required_model_codes(
            required_model_services if required_model_services is not None else env_required_model_services
        )
        self.required_model_owner_services = tuple(MODEL_SERVICE_BY_CODE[code] for code in self.required_model_codes)
        self.research_service_base_url = (
            research_service_base_url
            or os.getenv("RESEARCH_SERVICE_BASE_URL")
            or os.getenv("research_service_base_url")
            or "http://research-service:8029"
        ).rstrip("/")
        self.guard_trade_date = guard_trade_date or os.getenv("SCHEDULER_GUARD_TRADE_DATE", "2026-06-12")
        self.guard_symbol = guard_symbol or os.getenv("SCHEDULER_GUARD_SYMBOL", "000063.SZ")
        self.t_board_guard_symbol = t_board_guard_symbol or os.getenv("SCHEDULER_T_BOARD_GUARD_SYMBOL", "000759.SZ")
        self.data_inspector_base_url = (
            data_inspector_base_url
            or os.getenv("DATA_INSPECTOR_SERVICE_BASE_URL")
            or os.getenv("data_inspector_service_base_url")
            or "http://data-inspector-service:8025"
        ).rstrip("/")
        self.poll_seconds = float(poll_seconds or os.getenv("SCHEDULER_RUNTIME_POLL_SECONDS", "30"))
        self.request_timeout_seconds = float(request_timeout_seconds or os.getenv("SCHEDULER_RUNTIME_REQUEST_TIMEOUT_SECONDS", "5"))
        self.startup_guard_request_timeout_seconds = float(
            startup_guard_request_timeout_seconds
            or os.getenv("DATA_INSPECTION_STARTUP_GUARD_TIMEOUT_SECONDS", "60")
        )
        self.startup_guard_scope = startup_guard_scope or os.getenv("DATA_INSPECTION_STARTUP_GUARD_SCOPE", "startup_guard")
        self.startup_guard_lookback_days = int(startup_guard_lookback_days or os.getenv("DATA_INSPECTION_LOOKBACK_DAYS", "20"))
        self.startup_guard_max_subjects = int(startup_guard_max_subjects or os.getenv("DATA_INSPECTION_MAX_SUBJECTS", "500"))
        self.startup_guard_retry_attempts = int(startup_guard_retry_attempts or os.getenv("DATA_INSPECTION_STARTUP_GUARD_RETRY_ATTEMPTS", "12"))
        self.source_time_wheel_enabled = self._env_bool(
            source_time_wheel_enabled,
            "SCHEDULER_SOURCE_TIME_WHEEL_ENABLED",
            default=True,
        )
        self.source_time_wheel_live_submit = self._env_bool(
            source_time_wheel_live_submit,
            "SCHEDULER_SOURCE_TIME_WHEEL_LIVE_SUBMIT",
            default=True,
        )
        self.source_time_wheel_symbols = self._coerce_symbols(
            source_time_wheel_symbols
            if source_time_wheel_symbols is not None
            else os.getenv("SCHEDULER_SOURCE_TIME_WHEEL_SYMBOLS", "000063.SZ,000759.SZ")
        )
        self.source_time_wheel_lateness_seconds = int(
            source_time_wheel_lateness_seconds
            or os.getenv("SCHEDULER_SOURCE_TIME_WHEEL_LATENESS_SECONDS", "90")
        )
        self.source_time_wheel_max_dispatch = int(
            source_time_wheel_max_dispatch
            or os.getenv("SCHEDULER_SOURCE_TIME_WHEEL_MAX_DISPATCH", "20")
        )
        self.model_time_wheel_enabled = self._env_bool(
            model_time_wheel_enabled,
            "SCHEDULER_MODEL_TIME_WHEEL_ENABLED",
            default=True,
        )
        self.model_time_wheel_live_dispatch = self._env_bool(
            model_time_wheel_live_dispatch,
            "SCHEDULER_MODEL_TIME_WHEEL_LIVE_DISPATCH",
            default=False,
        )
        self.model_time_wheel_include_research_intraday = self._env_bool(
            model_time_wheel_include_research_intraday,
            "SCHEDULER_MODEL_TIME_WHEEL_INCLUDE_RESEARCH_INTRADAY",
            default=False,
        )
        self.model_time_wheel_lateness_seconds = int(
            model_time_wheel_lateness_seconds
            or os.getenv("SCHEDULER_MODEL_TIME_WHEEL_LATENESS_SECONDS", "90")
        )
        self.model_time_wheel_max_dispatch = int(
            model_time_wheel_max_dispatch
            or os.getenv("SCHEDULER_MODEL_TIME_WHEEL_MAX_DISPATCH", "20")
        )
        self.market_timezone_name = os.getenv("SCHEDULER_MARKET_TIMEZONE", DEFAULT_MARKET_TZ)
        self.market_timezone = ZoneInfo(self.market_timezone_name)
        self.model_tasks = {task.task_code: task for task in THREE_MODEL_TASKS}
        resolved_task_store_path = (
            task_store_path
            or os.getenv("SCHEDULER_TASK_STORE_PATH")
            or os.path.join(tempfile.gettempdir(), "ai_stock_scheduler_task_store.sqlite3")
        )
        self.task_store = task_store or SchedulerSQLiteTaskStore(resolved_task_store_path)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._startup_guard_attempt_count = 0
        self.snapshot = RuntimeSnapshot(
            guard_mode=self.guard_mode,
            data_inspector_base_url=self.data_inspector_base_url,
            poll_seconds=self.poll_seconds,
            source_time_wheel_enabled=self.source_time_wheel_enabled,
            source_time_wheel_live_submit=self.source_time_wheel_live_submit,
            model_time_wheel_enabled=self.model_time_wheel_enabled,
            model_time_wheel_live_dispatch=self.model_time_wheel_live_dispatch,
            task_store_path=resolved_task_store_path,
        )

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            now = datetime.now(timezone.utc)
            self.snapshot.started_at = now
            self.snapshot.background_loop_running = True
            self.snapshot.startup_guard_status = "pending"
            self.snapshot.closure_guard_status = "pending"
            self.snapshot.source_time_wheel_status = "pending" if self.source_time_wheel_enabled else "disabled"
            self.snapshot.model_time_wheel_status = "pending" if self.model_time_wheel_enabled else "disabled"
            self.snapshot.startup_guard_error = None
            self.snapshot.closure_guard_error = None
            self.snapshot.source_time_wheel_error = None
            self.snapshot.model_time_wheel_error = None
            self._startup_guard_attempt_count = 0
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="scheduler-runtime-guard", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=min(self.poll_seconds, 2.0))
        with self._lock:
            self.snapshot.background_loop_running = False

    def run_startup_cycle(self) -> None:
        self._heartbeat()
        self._check_data_inspector_ready()
        with self._lock:
            startup_ready = self._startup_guard_passed(self.snapshot.to_dict())
            inspector_ready = self.snapshot.data_inspector_status == "ready"
            attempts_remaining = self._startup_guard_attempt_count < self.startup_guard_retry_attempts
        if not startup_ready and inspector_ready and attempts_remaining:
            self._trigger_startup_guard()
        if self.guard_mode == "current_closure":
            self._check_current_closure_guard()
        self._run_source_time_wheel_cycle()
        self._run_model_time_wheel_cycle()

    def run_source_time_wheel_once(self, now: datetime | None = None) -> dict[str, Any]:
        self._run_source_time_wheel_cycle(now=now)
        with self._lock:
            snapshot = self.snapshot.to_dict()
        return {
            "version": SOURCE_TIME_WHEEL_VERSION,
            "enabled": snapshot.get("source_time_wheel_enabled"),
            "live_submit": snapshot.get("source_time_wheel_live_submit"),
            "status": snapshot.get("source_time_wheel_status"),
            "checked_at": snapshot.get("source_time_wheel_checked_at"),
            "error": snapshot.get("source_time_wheel_error"),
            "details": snapshot.get("source_time_wheel_details") or {},
        }

    def catch_up_source_schedule(
        self,
        *,
        trading_day: date,
        symbols: list[str] | None = None,
        include_one_time: bool = False,
        schedule_codes: list[str] | None = None,
        schedule_groups: list[str] | None = None,
        source_table_names: list[str] | None = None,
        run_slots: list[str] | None = None,
        allow_ths_paid_probability_fetch: bool = False,
        allow_ths_paid_probability_deadline_guard: bool = False,
        dispatch_immediately: bool = False,
        dry_run: bool = True,
        force_resubmit: bool = False,
        catch_up_run_id: str | None = None,
        max_instances: int = 50,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        checked_at = now or datetime.now(timezone.utc)
        if checked_at.tzinfo is None:
            checked_at = checked_at.replace(tzinfo=timezone.utc)
        resolved_catch_up_run_id = (
            str(catch_up_run_id).strip()
            if catch_up_run_id and str(catch_up_run_id).strip()
            else f"catchup-{checked_at.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        )
        code_filter = self._normalize_filter(schedule_codes)
        group_filter = self._normalize_filter(schedule_groups)
        table_filter = self._normalize_filter(source_table_names)
        slot_filter = self._normalize_filter(run_slots)
        stage_candidate_symbols_by_source = (
            self._stage_candidate_symbols_by_source(
                trading_day=trading_day,
                explicit_symbols=symbols,
            )
            if symbols
            or self._catch_up_needs_stage_candidate_source(
                code_filter=code_filter,
                group_filter=group_filter,
                table_filter=table_filter,
            )
            else {}
        )
        materialized = materialize_source_fetch_schedule(
            trading_day=trading_day,
            symbols=symbols or self.source_time_wheel_symbols,
            stage_candidate_symbols_by_source=stage_candidate_symbols_by_source,
            include_one_time=include_one_time,
            timezone_name=self.market_timezone_name,
        )
        selected = []
        excluded: list[dict[str, Any]] = []
        for instance in materialized:
            if code_filter and instance.schedule_code not in code_filter:
                continue
            if group_filter and instance.schedule_group not in group_filter:
                continue
            if table_filter and instance.source_table_name not in table_filter:
                continue
            if slot_filter and instance.run_slot not in slot_filter:
                continue
            endpoint_path = str(instance.request_body.get("__source_endpoint_path") or "/source/fetch/submit")
            if endpoint_path == "/source/ths/paid-probability/fetch-current-batch" and not allow_ths_paid_probability_fetch:
                excluded.append(
                    {
                        "schedule_code": instance.schedule_code,
                        "run_slot": instance.run_slot,
                        "reason": "ths_paid_probability_fetch_requires_explicit_allow",
                    }
                )
                continue
            if endpoint_path == "/source/ths/paid-probability/deadline-check" and not allow_ths_paid_probability_deadline_guard:
                excluded.append(
                    {
                        "schedule_code": instance.schedule_code,
                        "run_slot": instance.run_slot,
                        "reason": "ths_paid_probability_deadline_guard_requires_explicit_allow",
                    }
                )
                continue
            selected.append(instance)
        if max_instances < 1:
            raise ValueError("max_instances must be >= 1")
        if len(selected) > max_instances:
            raise ValueError(f"catch-up selected {len(selected)} instances; narrow filters or raise max_instances")

        details: dict[str, Any] = {
            "contract_kind": "scheduler_source_schedule_catch_up_v1",
            "source_time_wheel_version": SOURCE_TIME_WHEEL_VERSION,
            "trading_day": trading_day.isoformat(),
            "timezone": self.market_timezone_name,
            "dry_run": dry_run,
            "dispatch_immediately": dispatch_immediately,
            "force_resubmit": force_resubmit,
            "catch_up_run_id": resolved_catch_up_run_id,
            "include_one_time": include_one_time,
            "filters": {
                "schedule_codes": sorted(code_filter),
                "schedule_groups": sorted(group_filter),
                "source_table_names": sorted(table_filter),
                "run_slots": sorted(slot_filter),
                "allow_ths_paid_probability_fetch": allow_ths_paid_probability_fetch,
                "allow_ths_paid_probability_deadline_guard": allow_ths_paid_probability_deadline_guard,
                "max_instances": max_instances,
            },
            "selected_count": len(selected),
            "excluded_count": len(excluded),
            "excluded": excluded,
            "stage_candidate_sources": {
                key: {"symbol_count": len(value), "symbols": value[:50]}
                for key, value in sorted(stage_candidate_symbols_by_source.items())
            },
            "instances": [
                self._source_catch_up_instance_payload(
                    item,
                    force_resubmit=force_resubmit,
                    catch_up_run_id=resolved_catch_up_run_id,
                )
                for item in selected
            ],
            "enqueued_task_ids": [],
            "dispatched": [],
            "skipped": [],
            "status_counts": {},
            "hard_rules": [
                "Catch-up uses source_fetch_schedule_registry_v1 materialized instances; it is not a temporary fetch.",
                "Scheduler still submits only to source-data-service controlled endpoints and never calls providers.",
                "THS paid-probability catch-up and deadline guard require explicit allow flags.",
            ],
        }
        if dry_run:
            return details
        for instance in details["instances"]:
            task_id = self.task_store.enqueue(
                task_code=str(instance["schedule_code"]),
                owner_service="source-data-service",
                biz_key=str(instance["biz_key"]),
                scheduled_at=self._parse_dt(instance["scheduled_at"]),
                payload=dict(instance["request_body"]),
            )
            details["enqueued_task_ids"].append(task_id)
        if dispatch_immediately:
            self._dispatch_due_source_fetches(
                checked_at,
                details,
                task_instance_ids=set(details["enqueued_task_ids"]),
                lease_owner="scheduler-source-schedule-catch-up",
            )
        details["status_counts"] = self.task_store.status_counts(owner_services=("source-data-service",))
        return details

    def run_model_time_wheel_once(self, now: datetime | None = None) -> dict[str, Any]:
        self._run_model_time_wheel_cycle(now=now)
        with self._lock:
            snapshot = self.snapshot.to_dict()
        return {
            "version": MODEL_TIME_WHEEL_VERSION,
            "enabled": snapshot.get("model_time_wheel_enabled"),
            "live_dispatch": snapshot.get("model_time_wheel_live_dispatch"),
            "status": snapshot.get("model_time_wheel_status"),
            "checked_at": snapshot.get("model_time_wheel_checked_at"),
            "error": snapshot.get("model_time_wheel_error"),
            "details": snapshot.get("model_time_wheel_details") or {},
        }

    def catch_up_model_schedule(
        self,
        *,
        trading_day: date,
        task_codes: list[str] | None = None,
        owner_services: list[str] | None = None,
        run_slots: list[str] | None = None,
        include_research_intraday: bool | None = None,
        dispatch_immediately: bool = False,
        dry_run: bool = True,
        force_resubmit: bool = False,
        catch_up_run_id: str | None = None,
        max_instances: int = 50,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        checked_at = now or datetime.now(timezone.utc)
        if checked_at.tzinfo is None:
            checked_at = checked_at.replace(tzinfo=timezone.utc)
        resolved_catch_up_run_id = (
            str(catch_up_run_id).strip()
            if catch_up_run_id and str(catch_up_run_id).strip()
            else f"model-catchup-{checked_at.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        )
        task_filter = self._normalize_filter(task_codes)
        owner_filter = self._normalize_filter(owner_services)
        slot_filter = self._normalize_filter(run_slots)
        include_intraday = (
            self.model_time_wheel_include_research_intraday
            if include_research_intraday is None
            else bool(include_research_intraday)
        )
        materialized = materialize_three_model_day(
            trading_day=trading_day,
            timezone_name=self.market_timezone_name,
            include_research_intraday=include_intraday,
        )
        selected: list[dict[str, Any]] = []
        excluded: list[dict[str, Any]] = []
        for instance in materialized.get("instances", []):
            if not isinstance(instance, dict):
                continue
            task_code = str(instance.get("task_code") or "")
            owner_service = str(instance.get("owner_service") or "")
            task = self.model_tasks.get(task_code)
            if task is None or owner_service not in MODEL_OWNER_SERVICES:
                continue
            if task_filter and task_code not in task_filter:
                continue
            if owner_filter and owner_service not in owner_filter:
                continue
            if slot_filter and str(instance.get("run_slot") or "") not in slot_filter:
                continue
            if not self._model_owner_required(owner_service):
                excluded.append(
                    {
                        "task_code": task_code,
                        "owner_service": owner_service,
                        "run_slot": instance.get("run_slot"),
                        "reason": "disabled_by_policy",
                    }
                )
                continue
            selected.append(instance)
        if max_instances < 1:
            raise ValueError("max_instances must be >= 1")
        if len(selected) > max_instances:
            raise ValueError(f"model catch-up selected {len(selected)} instances; narrow filters or raise max_instances")

        details: dict[str, Any] = {
            "contract_kind": "scheduler_model_schedule_catch_up_v1",
            "model_time_wheel_version": MODEL_TIME_WHEEL_VERSION,
            "materializer_version": THREE_MODEL_MATERIALIZER_VERSION,
            "dispatcher_version": RESEARCH_MODEL_EXECUTION_DISPATCH_VERSION,
            "trading_day": trading_day.isoformat(),
            "timezone": self.market_timezone_name,
            "dry_run": dry_run,
            "dispatch_immediately": dispatch_immediately,
            "force_resubmit": force_resubmit,
            "catch_up_run_id": resolved_catch_up_run_id,
            "include_research_intraday": include_intraday,
            "model_availability_policy": self._model_availability_policy(),
            "filters": {
                "task_codes": sorted(task_filter),
                "owner_services": sorted(owner_filter),
                "run_slots": sorted(slot_filter),
                "max_instances": max_instances,
            },
            "selected_count": len(selected),
            "excluded_count": len(excluded),
            "excluded": excluded,
            "instances": [
                self._model_catch_up_instance_payload(
                    item,
                    force_resubmit=force_resubmit,
                    catch_up_run_id=resolved_catch_up_run_id,
                    checked_at=checked_at,
                )
                for item in selected
            ],
            "enqueued_task_ids": [],
            "dispatched": [],
            "research_execution": [],
            "skipped": [],
            "status_counts": {},
            "hard_rules": [
                "Model catch-up reuses three_model_materializer_v1; it is not a source fetch or provider call.",
                "Scheduler still dispatches only to research-service /research/model-execution/run.",
                "Late observation snapshots carry catch-up metadata and do not pretend to be live historical captures.",
            ],
        }
        if dry_run:
            return details
        for instance in details["instances"]:
            payload = dict(instance["scheduler_payload"])
            task_id = self.task_store.enqueue(
                task_code=str(instance["task_code"]),
                owner_service=str(instance["owner_service"]),
                biz_key=str(instance["biz_key"]),
                scheduled_at=self._parse_dt(instance["scheduled_at"]),
                payload=payload,
            )
            details["enqueued_task_ids"].append(task_id)
        if dispatch_immediately:
            self._dispatch_due_model_tasks(
                checked_at,
                details,
                task_instance_ids=set(details["enqueued_task_ids"]),
                lease_owner="scheduler-model-schedule-catch-up",
            )
        details["status_counts"] = self.task_store.status_counts(owner_services=self.required_model_owner_services)
        return details

    def ready_snapshot(self) -> dict[str, Any]:
        with self._lock:
            snapshot = self.snapshot.to_dict()
        checked_at = datetime.now(timezone.utc)
        source_task_store_health = self._task_store_health(
            now=checked_at,
            owner_services=("source-data-service",),
        )
        model_task_store_health = self._task_store_health(
            now=checked_at,
            owner_services=self.required_model_owner_services,
        )
        heartbeat_text = snapshot.get("heartbeat_at")
        heartbeat_ok = False
        if heartbeat_text:
            heartbeat = datetime.fromisoformat(str(heartbeat_text))
            heartbeat_ok = datetime.now(timezone.utc) - heartbeat <= timedelta(seconds=max(self.poll_seconds * 2, 10))
        background_ok = bool(snapshot.get("background_loop_running")) and heartbeat_ok
        legacy_mode = snapshot.get("guard_mode") == "legacy_data_inspector"
        startup_ok = self._startup_guard_passed(snapshot)
        closure_ok = snapshot.get("closure_guard_status") == "ready" if not legacy_mode else True
        inspector_ok = snapshot.get("data_inspector_status") == "ready"
        time_wheel_status = str(snapshot.get("source_time_wheel_status") or "")
        time_wheel_ok = time_wheel_status in {"ready", "idle", "disabled"}
        model_time_wheel_status = str(snapshot.get("model_time_wheel_status") or "")
        model_time_wheel_ok = model_time_wheel_status in {"ready", "idle", "disabled"}
        source_task_store_ok = source_task_store_health["status"] == "ready"
        model_task_store_ok = model_task_store_health["status"] == "ready"
        ready = (
            background_ok
            and startup_ok
            and closure_ok
            and inspector_ok
            and time_wheel_ok
            and model_time_wheel_ok
            and source_task_store_ok
            and model_task_store_ok
        )
        return {
            "status": "ready" if ready else "not_ready",
            "service": "scheduler-service",
            "runtime_version": SCHEDULER_RUNTIME_VERSION,
            "checks": {
                "background_loop": {
                    "status": "ready" if background_ok else "not_ready",
                    "running": bool(snapshot.get("background_loop_running")),
                    "heartbeat_at": snapshot.get("heartbeat_at"),
                    "last_error": snapshot.get("background_loop_last_error"),
                },
                "data_inspector": {
                    "status": snapshot.get("data_inspector_status"),
                    "checked_at": snapshot.get("data_inspector_checked_at"),
                    "error": snapshot.get("data_inspector_error"),
                    "base_url": snapshot.get("data_inspector_base_url"),
                },
                "startup_guard": {
                    "status": snapshot.get("startup_guard_status"),
                    "run_id": snapshot.get("startup_guard_run_id"),
                    "inspection_status": snapshot.get("startup_guard_inspection_status"),
                    "p0_gap_count": snapshot.get("startup_guard_p0_gap_count"),
                    "p1_gap_count": snapshot.get("startup_guard_p1_gap_count"),
                    "attempt_count": self._startup_guard_attempt_count,
                    "max_attempts": self.startup_guard_retry_attempts,
                    "error": snapshot.get("startup_guard_error"),
                },
                "closure_guard": {
                    "mode": snapshot.get("guard_mode"),
                    "status": snapshot.get("closure_guard_status"),
                    "checked_at": snapshot.get("closure_guard_checked_at"),
                    "error": snapshot.get("closure_guard_error"),
                    "details": snapshot.get("closure_guard_details") or {},
                },
                "source_time_wheel": {
                    "version": SOURCE_TIME_WHEEL_VERSION,
                    "enabled": bool(snapshot.get("source_time_wheel_enabled")),
                    "live_submit": bool(snapshot.get("source_time_wheel_live_submit")),
                    "status": snapshot.get("source_time_wheel_status"),
                    "checked_at": snapshot.get("source_time_wheel_checked_at"),
                    "error": snapshot.get("source_time_wheel_error"),
                    "task_store_path": snapshot.get("task_store_path"),
                    "details": snapshot.get("source_time_wheel_details") or {},
                },
                "model_time_wheel": {
                    "version": MODEL_TIME_WHEEL_VERSION,
                    "materializer_version": THREE_MODEL_MATERIALIZER_VERSION,
                    "dispatcher_version": RESEARCH_MODEL_EXECUTION_DISPATCH_VERSION,
                    "enabled": bool(snapshot.get("model_time_wheel_enabled")),
                    "live_dispatch": bool(snapshot.get("model_time_wheel_live_dispatch")),
                    "status": snapshot.get("model_time_wheel_status"),
                    "checked_at": snapshot.get("model_time_wheel_checked_at"),
                    "error": snapshot.get("model_time_wheel_error"),
                    "task_store_path": snapshot.get("task_store_path"),
                    "details": snapshot.get("model_time_wheel_details") or {},
                },
                "task_store": {
                    "source": source_task_store_health,
                    "model": model_task_store_health,
                },
            },
            "warning_codes": snapshot.get("warning_codes") or [],
        }

    def _task_store_health(
        self,
        *,
        now: datetime,
        owner_services: tuple[str, ...],
    ) -> dict[str, Any]:
        if not owner_services:
            return {
                "status": "ready",
                "owner_services": [],
                "status_counts": {},
                "stale_running_count": 0,
                "stale_running_sample": [],
                "blocking_statuses": [],
            }
        status_counts = self.task_store.status_counts(owner_services=owner_services)
        stale_running_count = self.task_store.expired_running_count(
            now=now,
            owner_services=owner_services,
        )
        stale_running = self.task_store.expired_running_tasks(
            now=now,
            owner_services=owner_services,
            limit=10,
        )
        blocking_statuses: list[str] = []
        for status in ("retry_ready", "dead_letter"):
            if int(status_counts.get(status) or 0) > 0:
                blocking_statuses.append(status)
        if stale_running_count:
            blocking_statuses.append("stale_running")
        return {
            "status": "not_ready" if blocking_statuses else "ready",
            "owner_services": list(owner_services),
            "status_counts": status_counts,
            "stale_running_count": stale_running_count,
            "stale_running_sample": self._compact_task_rows(stale_running),
            "blocking_statuses": blocking_statuses,
        }

    @staticmethod
    def _compact_task_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        keys = (
            "task_instance_id",
            "task_code",
            "owner_service",
            "status",
            "scheduled_at",
            "updated_at",
            "lease_owner",
            "lease_until",
        )
        return [{key: row.get(key) for key in keys if row.get(key) is not None} for row in rows]

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.run_startup_cycle()
            except Exception as exc:  # noqa: BLE001
                with self._lock:
                    self.snapshot.background_loop_last_error = str(exc)
            self._stop.wait(self.poll_seconds)
        with self._lock:
            self.snapshot.background_loop_running = False

    def _heartbeat(self) -> None:
        with self._lock:
            self.snapshot.heartbeat_at = datetime.now(timezone.utc)
            self.snapshot.background_loop_running = True

    def _trigger_startup_guard(self) -> None:
        with self._lock:
            self._startup_guard_attempt_count += 1
            attempt_count = self._startup_guard_attempt_count
            self.snapshot.startup_guard_status = "running"
            self.snapshot.startup_guard_error = None
        try:
            response = self.client.post(
                f"{self.data_inspector_base_url}/inspection-runs",
                json={
                    "scope": self.startup_guard_scope,
                    "as_of_trading_day": self.guard_trade_date,
                    "as_of_time": datetime.now(timezone.utc).isoformat(),
                    "lookback_days": self.startup_guard_lookback_days,
                    "persist": True,
                    "max_subjects": self.startup_guard_max_subjects,
                },
                timeout=self.startup_guard_request_timeout_seconds,
            )
            status_code = int(getattr(response, "status_code", 0))
            body = self._response_json(response)
            with self._lock:
                if 200 <= status_code < 300:
                    self.snapshot.startup_guard_run_id = body.get("run_id")
                    self.snapshot.startup_guard_inspection_status = str(body.get("status") or "unknown")
                    self.snapshot.startup_guard_p0_gap_count = self._optional_int(body.get("p0_gap_count"))
                    self.snapshot.startup_guard_p1_gap_count = self._optional_int(body.get("p1_gap_count"))
                    if self._inspection_body_passed(body):
                        self.snapshot.startup_guard_status = "ready"
                        self.snapshot.startup_guard_error = None
                    else:
                        self.snapshot.startup_guard_status = "failed"
                        self.snapshot.startup_guard_error = (
                            f"attempt={attempt_count}; startup_guard blocked; body={self._response_text(response)}"
                        )
                else:
                    self.snapshot.startup_guard_status = "failed"
                    self.snapshot.startup_guard_error = (
                        f"attempt={attempt_count}; status_code={status_code}; body={self._response_text(response)}"
                    )
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self.snapshot.startup_guard_status = "failed"
                self.snapshot.startup_guard_error = f"attempt={attempt_count}; {exc}"

    def _check_data_inspector_ready(self) -> None:
        try:
            response = self.client.get(f"{self.data_inspector_base_url}/readyz", timeout=self.request_timeout_seconds)
            status_code = int(getattr(response, "status_code", 0))
            body = self._response_json(response)
            body_status = str(body.get("status") or "").lower()
            ready = 200 <= status_code < 300 and body_status in {"ready", "ok"}
            with self._lock:
                self.snapshot.data_inspector_status = "ready" if ready else "not_ready"
                self.snapshot.data_inspector_error = None if ready else f"status_code={status_code}; body={self._response_text(response)}"
                self.snapshot.data_inspector_checked_at = datetime.now(timezone.utc)
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self.snapshot.data_inspector_status = "unreachable"
                self.snapshot.data_inspector_error = str(exc)
                self.snapshot.data_inspector_checked_at = datetime.now(timezone.utc)

    def _check_current_closure_guard(self) -> None:
        checked_at = datetime.now(timezone.utc)
        historical_guard_date = _is_historical_guard_trade_date(
            self.guard_trade_date,
            checked_at=checked_at,
            market_timezone=self.market_timezone,
        )
        details: dict[str, Any] = {
            "source": {},
            "data_inspector": {"guard_trade_date": self.guard_trade_date},
            "models": {},
            "model_availability_policy": self._model_availability_policy(),
            "preflight": {},
            "preflight_policy": {
                "guard_trade_date": self.guard_trade_date,
                "historical_guard_date": historical_guard_date,
                "historical_late_only_readyz_policy": "ignore_for_readyz_after_coverage_passed",
            },
            "queue": {},
        }
        blockers: list[str] = []
        try:
            inspector_ready = self._get_json(f"{self.data_inspector_base_url}/readyz")
            details["data_inspector"]["readyz"] = inspector_ready
            if str(inspector_ready.get("status") or "").lower() not in {"ready", "ok"}:
                blockers.append("data-inspector-service readyz not ready")

            for scope in ("startup_guard", "core_closure"):
                latest = self._get_json(
                    f"{self.data_inspector_base_url}/inspection-runs/latest"
                    f"?scope={scope}&as_of_trading_day={self.guard_trade_date}"
                )
                details["data_inspector"][f"latest_{scope}"] = {
                    "run_id": latest.get("run_id"),
                    "as_of_trading_day": latest.get("as_of_trading_day"),
                    "status": latest.get("status"),
                    "p0_gap_count": latest.get("p0_gap_count"),
                    "p1_gap_count": latest.get("p1_gap_count"),
                    "gap_count": latest.get("gap_count"),
                    "finished_at": latest.get("finished_at"),
                }
                if not self._inspection_body_passed(latest):
                    if scope == "core_closure" and self._core_closure_self_gap_only(latest, details):
                        details["data_inspector"][f"latest_{scope}"]["self_dependency_ignored"] = True
                    else:
                        blockers.append(f"data inspection {scope} not ready")

            source_ready = self._get_json(f"{self.source_data_base_url}/readyz")
            details["source"]["readyz"] = source_ready
            if str(source_ready.get("status") or "").lower() not in {"ready", "ok"}:
                blockers.append("source-data-service readyz not ready")

            production = self._get_json(
                f"{self.source_data_base_url}/source/ops/production-readiness?require_postgres=true&require_real_provider_probe=true"
            )
            details["source"]["production_readiness"] = {
                "status": production.get("status"),
                "can拍板": production.get("can拍板"),
            }
            if production.get("status") != "passed" or production.get("can拍板") is not True:
                blockers.append("source production readiness blocked")

            queue = self._get_json(f"{self.source_data_base_url}/source/fetch/queues/summary")
            details["queue"] = queue
            for row in queue.get("rows", []):
                if int(row.get("leased_count") or 0) or int(row.get("dead_letter_count") or 0):
                    blockers.append(f"source queue {row.get('queue_name')} has leased/dead_letter jobs")

            for model_code, base_url in self.model_base_urls.items():
                if not self._model_code_required(model_code):
                    details["models"][model_code] = {
                        "status": "disabled_by_policy",
                        "required": False,
                        "base_url": base_url,
                    }
                    continue
                try:
                    model_ready = self._get_json(f"{base_url}/readyz")
                except Exception as exc:  # noqa: BLE001
                    details["models"][model_code] = {
                        "status": "not_ready",
                        "required": True,
                        "base_url": base_url,
                        "error": str(exc),
                    }
                    blockers.append(f"{model_code} readyz not ready: {exc}")
                    continue
                details["models"][model_code] = {**model_ready, "required": True, "base_url": base_url}
                if str(model_ready.get("status") or "").lower() not in {"ready", "ok"}:
                    blockers.append(f"{model_code} readyz not ready")

            preflight_targets = (
                ("hot_candidates", "preopen_release_gate", self.guard_symbol),
                ("candidate_memory", "outcome_label", self.guard_symbol),
                ("ambush_watchlist", "release_gate", self.guard_symbol),
                ("t_board_relay", "day1_scan", self.t_board_guard_symbol),
                ("t_board_relay", "day2_trigger", self.t_board_guard_symbol),
            )
            for model_code, model_phase, symbol in preflight_targets:
                decision_time = _source_preflight_decision_time(self.guard_trade_date, model_code, model_phase)
                result = self._post_json(
                    f"{self.source_data_base_url}/source/release/preflight",
                    {
                        "model_code": model_code,
                        "model_phase": model_phase,
                        "trade_date": self.guard_trade_date,
                        "symbols": [symbol],
                        "decision_time": decision_time,
                    },
                )
                key = f"{model_code}.{model_phase}"
                blocking_reasons = result.get("blocking_reasons") or []
                historical_late_only = (
                    historical_guard_date
                    and result.get("coverage_status") == "passed"
                    and _preflight_blockers_are_late_only(blocking_reasons)
                )
                details["preflight"][key] = {
                    "symbol": symbol,
                    "decision_time": decision_time,
                    "can_release_official_signal": result.get("can_release_official_signal"),
                    "coverage_status": result.get("coverage_status"),
                    "freshness_status": result.get("freshness_status"),
                    "blocking_reasons": blocking_reasons,
                    "degraded_reasons": result.get("degraded_reasons") or [],
                    "historical_late_observed": historical_late_only,
                    "ignored_for_readyz": historical_late_only,
                }
                if historical_late_only:
                    details["preflight"][key]["readyz_policy"] = (
                        "source preflight remains blocked for historical decision_time, "
                        "but late-only historical backfill visibility does not block scheduler service readiness"
                    )
                    details["preflight"][key]["official_release_preflight_still_blocked"] = (
                        result.get("can_release_official_signal") is not True
                    )
                elif result.get("can_release_official_signal") is not True or blocking_reasons:
                    blockers.append(f"source release preflight blocked: {key}")

            with self._lock:
                self.snapshot.closure_guard_status = "ready" if not blockers else "failed"
                self.snapshot.closure_guard_error = "; ".join(blockers) if blockers else None
                self.snapshot.closure_guard_checked_at = checked_at
                self.snapshot.closure_guard_details = details
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self.snapshot.closure_guard_status = "failed"
                self.snapshot.closure_guard_error = str(exc)
                self.snapshot.closure_guard_checked_at = checked_at
                self.snapshot.closure_guard_details = details

    def _run_source_time_wheel_cycle(self, now: datetime | None = None) -> None:
        checked_at = now or datetime.now(timezone.utc)
        if checked_at.tzinfo is None:
            checked_at = checked_at.replace(tzinfo=timezone.utc)
        if not self.source_time_wheel_enabled:
            with self._lock:
                self.snapshot.source_time_wheel_status = "disabled"
                self.snapshot.source_time_wheel_checked_at = checked_at
                self.snapshot.source_time_wheel_error = None
                self.snapshot.source_time_wheel_details = {
                    "reason": "SCHEDULER_SOURCE_TIME_WHEEL_ENABLED=false",
                }
            return
        details: dict[str, Any] = {
            "symbols": self.source_time_wheel_symbols,
            "lateness_seconds": self.source_time_wheel_lateness_seconds,
            "live_submit": self.source_time_wheel_live_submit,
            "stage_candidate_sources": {},
            "due_count": 0,
            "enqueued_task_ids": [],
            "dispatched": [],
            "skipped": [],
            "recovered_expired_running_count": 0,
            "recovered_expired_running": [],
            "status_counts": {},
            "task_store_health": {},
        }
        try:
            recovered = self.task_store.recover_expired_running(
                now=checked_at,
                owner_services=("source-data-service",),
                limit=self.source_time_wheel_max_dispatch,
            )
            details["recovered_expired_running_count"] = len(recovered)
            details["recovered_expired_running"] = self._compact_task_rows(recovered)
            trading_day = checked_at.astimezone(ZoneInfo(self.market_timezone_name)).date()
            stage_candidate_symbols_by_source = self._stage_candidate_symbols_by_source(trading_day=trading_day)
            details["stage_candidate_sources"] = {
                key: {"symbol_count": len(value), "symbols": value[:50]}
                for key, value in sorted(stage_candidate_symbols_by_source.items())
            }
            due = due_source_fetch_instances(
                now=checked_at,
                symbols=self.source_time_wheel_symbols,
                stage_candidate_symbols_by_source=stage_candidate_symbols_by_source,
                include_one_time=False,
                timezone_name=self.market_timezone_name,
                lateness_seconds=self.source_time_wheel_lateness_seconds,
            )
            details["due_count"] = len(due)
            for instance in due:
                task_id = self.task_store.enqueue(
                    task_code=instance.schedule_code,
                    owner_service="source-data-service",
                    biz_key=instance.biz_key,
                    scheduled_at=instance.scheduled_at,
                    payload=instance.request_body,
                )
                details["enqueued_task_ids"].append(task_id)
            if self.source_time_wheel_live_submit:
                self._dispatch_due_source_fetches(checked_at, details)
            elif details["enqueued_task_ids"]:
                details["skipped"].append("live_submit_disabled")
            dispatch_failures = [
                item
                for item in details["dispatched"]
                if int(item.get("status_code") or 0) < 200 or int(item.get("status_code") or 0) >= 300
            ]
            status_counts = self.task_store.status_counts(owner_services=("source-data-service",))
            details["status_counts"] = status_counts
            task_store_health = self._task_store_health(now=checked_at, owner_services=("source-data-service",))
            details["task_store_health"] = task_store_health
            has_unresolved_task_store = bool(task_store_health["blocking_statuses"])
            if dispatch_failures or has_unresolved_task_store:
                status = "failed"
            elif (
                details["due_count"]
                or details["enqueued_task_ids"]
                or details["dispatched"]
                or details["recovered_expired_running_count"]
            ):
                status = "ready"
            else:
                status = "idle"
            error = None
            if dispatch_failures:
                error = f"source fetch submit failed for {len(dispatch_failures)} task(s)"
            elif has_unresolved_task_store:
                error = "source task store has unresolved statuses: " + ",".join(task_store_health["blocking_statuses"])
            with self._lock:
                self.snapshot.source_time_wheel_status = status
                self.snapshot.source_time_wheel_error = error
                self.snapshot.source_time_wheel_checked_at = checked_at
                self.snapshot.source_time_wheel_details = details
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self.snapshot.source_time_wheel_status = "failed"
                self.snapshot.source_time_wheel_error = str(exc)
                self.snapshot.source_time_wheel_checked_at = checked_at
                self.snapshot.source_time_wheel_details = details

    def _dispatch_due_source_fetches(
        self,
        checked_at: datetime,
        details: dict[str, Any],
        *,
        task_instance_ids: set[str] | None = None,
        lease_owner: str = "scheduler-source-time-wheel",
    ) -> None:
        if task_instance_ids is None:
            tasks = self.task_store.due_tasks(
                now=checked_at,
                limit=self.source_time_wheel_max_dispatch,
                owner_service="source-data-service",
            )
        else:
            tasks = self.task_store.due_tasks_by_ids(
                task_instance_ids=sorted(task_instance_ids),
                now=checked_at,
                owner_service="source-data-service",
            )
        for task in tasks:
            task_id = str(task["task_instance_id"])
            lease = self.task_store.acquire_lease(
                task_id,
                lease_owner=lease_owner,
                now=checked_at,
                lease_seconds=max(int(self.request_timeout_seconds * 3), 30),
            )
            if not lease.acquired:
                details["skipped"].append(
                    {
                        "task_instance_id": task_id,
                        "reason": lease.message,
                    }
                )
                continue
            payload = self.task_store.payload_for(task)
            endpoint_path = str(payload.pop("__source_endpoint_path", "/source/fetch/submit") or "/source/fetch/submit")
            if not endpoint_path.startswith("/source/"):
                endpoint_path = "/source/fetch/submit"
            response = self.client.post(
                f"{self.source_data_base_url}{endpoint_path}",
                json=payload,
                timeout=self.request_timeout_seconds,
            )
            status_code = int(getattr(response, "status_code", 0))
            body = self._response_json(response)
            source_result_status = "submit_accepted_pending_source_build" if 200 <= status_code < 300 else "submit_failed"
            if 200 <= status_code < 300 and self._is_source_duplicate_noop(body):
                source_result_status = "submit_duplicate_no_new_job"
            dispatched = {
                "task_instance_id": task_id,
                "task_code": task.get("task_code"),
                "source_endpoint_path": endpoint_path,
                "status_code": status_code,
                "source_fetch_batch_id": body.get("fetch_batch_id"),
                "queue_name": body.get("queue_name"),
                "source_result_status": source_result_status,
            }
            details["dispatched"].append(dispatched)
            if 200 <= status_code < 300:
                if source_result_status == "submit_duplicate_no_new_job":
                    self.task_store.mark_terminal(
                        task_id,
                        status="source_duplicate_skipped",
                        output=body,
                        message="source submit accepted as duplicate; no new raw job queued",
                        error_code="source_submit_duplicate_no_new_job",
                    )
                else:
                    self.task_store.mark_success(task_id, output=body)
            else:
                self.task_store.mark_failure(
                    task_id,
                    error_code="source_fetch_submit_failed",
                    error_message=f"status_code={status_code}; body={self._response_text(response)}",
                )

    @staticmethod
    def _is_source_duplicate_noop(body: dict[str, Any]) -> bool:
        try:
            submitted = int(body.get("submitted_job_count") or 0)
            skipped = int(body.get("skipped_duplicate_count") or 0)
        except (TypeError, ValueError):
            return False
        return submitted == 0 and skipped > 0

    def _stage_candidate_symbols_by_source(
        self,
        *,
        trading_day: date,
        explicit_symbols: list[str] | None = None,
    ) -> dict[str, list[str]]:
        explicit = self._coerce_symbols(explicit_symbols) if explicit_symbols else []
        if explicit:
            return {
                EXPLICIT_MODEL_STAGE_CANDIDATE_SOURCE: explicit,
                T_RELAY_DAY1_QUALIFIED_STAGE_CANDIDATE_SOURCE: explicit,
                T_RELAY_LIMIT_EVENT_STAGE_CANDIDATE_SOURCE: explicit,
            }
        day2_candidates: list[str] = []
        try:
            day2_candidates = self._load_t_relay_day1_qualified_stage_candidates(trading_day)
        except Exception:
            day2_candidates = []
        return {
            T_RELAY_DAY1_QUALIFIED_STAGE_CANDIDATE_SOURCE: day2_candidates,
            T_RELAY_LIMIT_EVENT_STAGE_CANDIDATE_SOURCE: self._load_t_relay_limit_event_stage_candidates(trading_day),
        }

    @staticmethod
    def _catch_up_needs_stage_candidate_source(
        *,
        code_filter: set[str],
        group_filter: set[str],
        table_filter: set[str],
    ) -> bool:
        for spec in SOURCE_FETCH_SCHEDULES:
            if code_filter and spec.schedule_code not in code_filter:
                continue
            if group_filter and spec.schedule_group not in group_filter:
                continue
            if table_filter and spec.source_table_name not in table_filter:
                continue
            if spec.symbol_scope == "stage_candidates":
                return True
        return False

    def _load_t_relay_limit_event_stage_candidates(self, trading_day: date) -> list[str]:
        query = urlencode(
            {
                "source_table_name": "source.limit_event_v1",
                "trade_date": trading_day.isoformat(),
            }
        )
        response = self.client.get(
            f"{self.source_data_base_url}/source/rows?{query}",
            timeout=self.request_timeout_seconds,
        )
        status_code = int(getattr(response, "status_code", 0))
        if not 200 <= status_code < 300:
            raise RuntimeError(f"GET /source/rows source.limit_event_v1 status_code={status_code}; body={self._response_text(response)}")
        try:
            rows = response.json()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("GET /source/rows source.limit_event_v1 returned non-json response") from exc
        if not isinstance(rows, list):
            rows = rows.get("response", []) if isinstance(rows, dict) else []
        symbols: set[str] = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            values = row.get("values") if isinstance(row.get("values"), dict) else {}
            event_type = str(values.get("limit_event_type") or row.get("limit_event_type") or "").strip()
            close_on_limit = values.get("close_on_limit_flag")
            is_break_limit = values.get("is_break_limit")
            if event_type != "t_board_limit_up" and not bool(is_break_limit):
                continue
            if close_on_limit is False:
                continue
            symbol = str(row.get("symbol") or "").strip()
            if symbol:
                symbols.add(symbol)
        return sorted(symbols)

    def _load_t_relay_day1_qualified_stage_candidates(self, trading_day: date) -> list[str]:
        response = self.client.get(
            f"{self.model_base_urls['t_board_relay']}/t-board-relay/observation-board?limit=1000",
            timeout=self.request_timeout_seconds,
        )
        status_code = int(getattr(response, "status_code", 0))
        if not 200 <= status_code < 300:
            raise RuntimeError(
                f"GET /t-board-relay/observation-board status_code={status_code}; body={self._response_text(response)}"
            )
        try:
            body = response.json()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("GET /t-board-relay/observation-board returned non-json response") from exc
        data = body.get("data") if isinstance(body, dict) and isinstance(body.get("data"), dict) else body
        items = data.get("items", []) if isinstance(data, dict) else []
        symbols: set[str] = set()
        trading_day_text = trading_day.isoformat()
        for item in items:
            if not isinstance(item, dict):
                continue
            day2_trade_date = str(item.get("day2_trade_date") or "").strip()
            day1_trade_date = str(item.get("day1_trade_date") or "").strip()
            if day2_trade_date and day2_trade_date != trading_day_text:
                continue
            if not day2_trade_date and (not day1_trade_date or day1_trade_date >= trading_day_text):
                continue
            status = str(item.get("observation_status") or "").strip()
            if status in {"stopped", "completed"} and day2_trade_date != trading_day_text:
                continue
            stock = item.get("stock") if isinstance(item.get("stock"), dict) else {}
            symbol = str(stock.get("symbol") or item.get("canonical_symbol") or item.get("symbol") or "").strip()
            if symbol:
                symbols.add(symbol)
        return sorted(symbols)

    def _run_model_time_wheel_cycle(self, now: datetime | None = None) -> None:
        checked_at = now or datetime.now(timezone.utc)
        if checked_at.tzinfo is None:
            checked_at = checked_at.replace(tzinfo=timezone.utc)
        if not self.model_time_wheel_enabled:
            with self._lock:
                self.snapshot.model_time_wheel_status = "disabled"
                self.snapshot.model_time_wheel_checked_at = checked_at
                self.snapshot.model_time_wheel_error = None
                self.snapshot.model_time_wheel_details = {
                    "reason": "SCHEDULER_MODEL_TIME_WHEEL_ENABLED=false",
                }
            return
        details: dict[str, Any] = {
            "timezone": self.market_timezone_name,
            "lateness_seconds": self.model_time_wheel_lateness_seconds,
            "live_dispatch": self.model_time_wheel_live_dispatch,
            "include_research_intraday": self.model_time_wheel_include_research_intraday,
            "model_availability_policy": self._model_availability_policy(),
            "due_count": 0,
            "enqueued_task_ids": [],
            "dispatched": [],
            "research_execution": [],
            "skipped": [],
            "status_counts": {},
            "recovered_expired_running_count": 0,
            "recovered_expired_running": [],
            "task_store_health": {},
        }
        try:
            recovered = self.task_store.recover_expired_running(
                now=checked_at,
                owner_services=self.required_model_owner_services,
                limit=self.model_time_wheel_max_dispatch,
            )
            details["recovered_expired_running_count"] = len(recovered)
            details["recovered_expired_running"] = self._compact_task_rows(recovered)
            due = self._due_model_instances(checked_at)
            details["due_count"] = len(due)
            for instance in due:
                owner_service = str(instance.get("owner_service") or "")
                if not self._model_owner_required(owner_service):
                    details["skipped"].append(
                        {
                            "task_code": instance.get("task_code"),
                            "owner_service": owner_service,
                            "reason": "disabled_by_policy",
                        }
                    )
                    continue
                task_id = self.task_store.enqueue(
                    task_code=instance["task_code"],
                    owner_service=owner_service,
                    biz_key=instance["biz_key"],
                    scheduled_at=self._parse_dt(instance["scheduled_at"]),
                    payload=self._model_task_payload(instance),
                )
                details["enqueued_task_ids"].append(task_id)
            if self.model_time_wheel_live_dispatch:
                self._dispatch_due_model_tasks(checked_at, details)
            elif details["enqueued_task_ids"]:
                details["skipped"].append("live_dispatch_disabled")

            status_counts = self.task_store.status_counts(owner_services=self.required_model_owner_services)
            details["status_counts"] = status_counts
            task_store_health = self._task_store_health(
                now=checked_at,
                owner_services=self.required_model_owner_services,
            )
            details["task_store_health"] = task_store_health
            has_unresolved_failure = self.model_time_wheel_live_dispatch and bool(task_store_health["blocking_statuses"])
            dispatch_failures = [item for item in details["dispatched"] if item.get("completed") is not True]
            if has_unresolved_failure or dispatch_failures:
                status = "failed"
            elif (
                details["due_count"]
                or details["enqueued_task_ids"]
                or details["dispatched"]
                or details["research_execution"]
                or details["recovered_expired_running_count"]
            ):
                status = "ready"
            else:
                status = "idle"
            error = None
            if dispatch_failures:
                error = f"research model execution failed for {len(dispatch_failures)} task(s)"
            elif has_unresolved_failure:
                error = "model task store has unresolved statuses: " + ",".join(task_store_health["blocking_statuses"])
            with self._lock:
                self.snapshot.model_time_wheel_status = status
                self.snapshot.model_time_wheel_error = error
                self.snapshot.model_time_wheel_checked_at = checked_at
                self.snapshot.model_time_wheel_details = details
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self.snapshot.model_time_wheel_status = "failed"
                self.snapshot.model_time_wheel_error = str(exc)
                self.snapshot.model_time_wheel_checked_at = checked_at
                self.snapshot.model_time_wheel_details = details

    def _due_model_instances(self, checked_at: datetime) -> list[dict[str, Any]]:
        local_day = checked_at.astimezone(self.market_timezone).date()
        materialized = materialize_three_model_day(
            trading_day=local_day,
            timezone_name=self.market_timezone_name,
            include_research_intraday=self.model_time_wheel_include_research_intraday,
        )
        lower_bound = checked_at - timedelta(seconds=self.model_time_wheel_lateness_seconds)
        due: list[dict[str, Any]] = []
        for instance in materialized.get("instances", []):
            if not isinstance(instance, dict):
                continue
            task_code = str(instance.get("task_code") or "")
            task = self.model_tasks.get(task_code)
            if task is None:
                continue
            if task.owner_service not in MODEL_OWNER_SERVICES:
                continue
            scheduled_at = self._parse_dt(instance["scheduled_at"])
            if lower_bound <= scheduled_at <= checked_at:
                due.append(instance)
        return due

    def _model_task_payload(self, instance: dict[str, Any]) -> dict[str, Any]:
        task_code = str(instance["task_code"])
        owner_service = str(instance.get("owner_service") or "")
        symbol = self.t_board_guard_symbol if owner_service == "t-board-relay-service" else self.guard_symbol
        symbols = [symbol]
        stage_candidate_source: str | None = None
        stage_candidate_count: int | None = None
        stage_candidate_gap_codes: list[str] = []
        if task_code == T_RELAY_DAY1_SCAN_TASK_CODE:
            stage_candidate_source = T_RELAY_LIMIT_EVENT_STAGE_CANDIDATE_SOURCE
            symbols = self._load_t_relay_limit_event_stage_candidates(
                datetime.fromisoformat(str(instance["trading_day"])).date()
            )
            symbol = symbols[0] if len(symbols) == 1 else None
            stage_candidate_count = len(symbols)
            if not symbols:
                stage_candidate_gap_codes.append(T_RELAY_DAY1_STAGE_CANDIDATES_MISSING_GAP)
        return {
            "run_id": f"scheduler:{task_code}:{instance['trading_day']}:{instance['run_slot']}",
            "as_of_time_utc": instance["scheduled_at"],
            "trade_date": instance["trading_day"],
            "symbol": symbol,
            "symbols": symbols,
            "source_gap_codes": stage_candidate_gap_codes,
            "_scheduler_materialized_instance": {
                "model_time_wheel_version": MODEL_TIME_WHEEL_VERSION,
                "materializer_version": THREE_MODEL_MATERIALIZER_VERSION,
                "task_code": task_code,
                "task_kind": instance.get("task_kind"),
                "owner_service": instance.get("owner_service"),
                "scheduled_at": instance.get("scheduled_at"),
                "scheduled_at_local": instance.get("scheduled_at_local"),
                "biz_key": instance.get("biz_key"),
                "idempotency_seed": instance.get("idempotency_seed"),
                "is_official_publish": instance.get("is_official_publish"),
                "append_only": instance.get("append_only"),
                "reads_from": instance.get("reads_from") or [],
                "writes_to": instance.get("writes_to") or [],
                "stage_candidate_source": stage_candidate_source,
                "stage_candidate_count": stage_candidate_count,
            },
        }

    def _dispatch_due_model_tasks(
        self,
        checked_at: datetime,
        details: dict[str, Any],
        *,
        task_instance_ids: set[str] | None = None,
        lease_owner: str = "scheduler-model-time-wheel",
    ) -> None:
        execution_url = f"{self.research_service_base_url}/research/model-execution/run"
        if task_instance_ids is None:
            tasks = self.task_store.due_tasks(
                now=checked_at,
                limit=self.model_time_wheel_max_dispatch,
                owner_services=self.required_model_owner_services,
            )
        else:
            tasks = self.task_store.due_tasks_by_ids(
                task_instance_ids=sorted(task_instance_ids),
                now=checked_at,
            )
        for task in tasks:
            if not self._model_owner_required(str(task.get("owner_service") or "")):
                details["skipped"].append(
                    {
                        "task_instance_id": task.get("task_instance_id"),
                        "task_code": task.get("task_code"),
                        "owner_service": task.get("owner_service"),
                        "reason": "disabled_by_policy",
                    }
                )
                continue
            task_id = str(task["task_instance_id"])
            lease = self.task_store.acquire_lease(
                task_id,
                lease_owner=lease_owner,
                now=checked_at,
                lease_seconds=max(int(self.request_timeout_seconds * 6), 30),
            )
            if not lease.acquired:
                details["skipped"].append(
                    {
                        "task_instance_id": task_id,
                        "task_code": task.get("task_code"),
                        "reason": lease.message,
                    }
                )
                continue
            payload = self.task_store.payload_for(task)
            try:
                scheduler_instance = (
                    payload.get("_scheduler_materialized_instance")
                    if isinstance(payload.get("_scheduler_materialized_instance"), dict)
                    else {}
                )
                task_code = str(task["task_code"])
                symbols = payload.get("symbols") or ([payload.get("symbol")] if payload.get("symbol") else [])
                if task_code == T_RELAY_DAY1_SCAN_TASK_CODE and not symbols:
                    gap_codes = payload.get("source_gap_codes") if isinstance(payload.get("source_gap_codes"), list) else []
                    if T_RELAY_DAY1_STAGE_CANDIDATES_MISSING_GAP not in gap_codes:
                        gap_codes = [*gap_codes, T_RELAY_DAY1_STAGE_CANDIDATES_MISSING_GAP]
                    body = {
                        "accepted": False,
                        "execution_status": "blocked_data_gap",
                        "execution_id": None,
                        "gap_codes": sorted({str(code) for code in gap_codes}),
                        "owner_called": False,
                        "dispatch_allowed": False,
                        "reason": "t_relay_day1_stage_candidates_missing",
                        "scheduler_task_instance_id": task_id,
                    }
                    details["research_execution"].append(
                        {
                            "task_instance_id": task_id,
                            "task_code": task_code,
                            "owner_service": task.get("owner_service"),
                            "status_code": None,
                            "accepted": False,
                            "execution_status": "blocked_data_gap",
                            "completed": True,
                            "terminal_non_success": True,
                            "gap_codes": body["gap_codes"],
                            "execution_id": None,
                            "materialized_counts": {},
                        }
                    )
                    details["dispatched"].append(
                        {
                            "task_instance_id": task_id,
                            "task_code": task_code,
                            "owner_service": task.get("owner_service"),
                            "completed": True,
                            "status_code": None,
                            "accepted": False,
                            "execution_status": "blocked_data_gap",
                            "gap_codes": body["gap_codes"],
                        }
                    )
                    self.task_store.mark_terminal(
                        task_id,
                        status="blocked_data_gap",
                        output=body,
                        error_code="model_blocked_data_gap",
                        message="model day1 stage candidates missing; research execution skipped",
                    )
                    continue
                request_body = {
                    "task_code": task_code,
                    "symbol": payload.get("symbol"),
                    "symbols": symbols,
                    "trade_date": payload.get("trade_date") or payload.get("trading_day"),
                    "as_of_time_utc": payload.get("as_of_time_utc"),
                    "run_id": payload.get("run_id"),
                    "persist_audit": True,
                    "extra_context": {
                        "scheduler_task_instance_id": task_id,
                        "scheduler_biz_key": task.get("biz_key"),
                        "scheduler_materialized_instance": scheduler_instance,
                    },
                }
                response = self.client.post(
                    execution_url,
                    json=request_body,
                    timeout=max(self.request_timeout_seconds * 6, 30),
                )
                status_code = int(getattr(response, "status_code", 0) or 0)
                try:
                    body = response.json()
                except Exception:  # noqa: BLE001
                    body = {"error": self._response_text(response)}
                execution_status = str(body.get("execution_status") or "research_model_execution_failed")
                accepted = 200 <= status_code < 300 and body.get("accepted") is True
                terminal_non_success = (
                    200 <= status_code < 300
                    and not accepted
                    and execution_status in TERMINAL_MODEL_EXECUTION_STATUSES
                )
                completed = accepted or terminal_non_success
                details["research_execution"].append(
                    {
                        "task_instance_id": task_id,
                        "task_code": task.get("task_code"),
                        "owner_service": task.get("owner_service"),
                        "dispatch_version": RESEARCH_MODEL_EXECUTION_DISPATCH_VERSION,
                        "url": execution_url,
                        "status_code": status_code,
                        "accepted": accepted,
                        "completed": completed,
                        "terminal_non_success": terminal_non_success,
                        "execution_status": execution_status,
                        "execution_id": body.get("execution_id"),
                        "gap_codes": body.get("gap_codes") or [],
                    }
                )
                row = {
                    "task_instance_id": task_id,
                    "task_code": task.get("task_code"),
                    "owner_service": task.get("owner_service"),
                    "status_code": status_code,
                    "accepted": accepted,
                    "completed": completed,
                    "terminal_non_success": terminal_non_success,
                    "execution_status": execution_status,
                }
                details["dispatched"].append(row)
                if accepted:
                    self.task_store.mark_success(task_id, output=body)
                elif terminal_non_success:
                    self.task_store.mark_terminal(
                        task_id,
                        status=execution_status,
                        output=body,
                        error_code=f"model_{execution_status}",
                        message=(
                            f"research execution terminal non-success; "
                            f"status_code={status_code}; gaps={','.join(body.get('gap_codes') or [])}"
                        ),
                    )
                else:
                    self.task_store.mark_failure(
                        task_id,
                        error_code=f"model_{execution_status}",
                        error_message=f"status_code={status_code}; url={execution_url}; gaps={','.join(body.get('gap_codes') or [])}",
                    )
            except Exception as exc:  # noqa: BLE001
                details["dispatched"].append(
                    {
                        "task_instance_id": task_id,
                        "task_code": task.get("task_code"),
                        "owner_service": task.get("owner_service"),
                        "accepted": False,
                        "error": str(exc),
                    }
                )
                self.task_store.mark_failure(
                    task_id,
                    error_code="research_model_execution_exception",
                    error_message=str(exc),
                )

    def _model_code_required(self, model_code: str) -> bool:
        return model_code in self.required_model_codes

    def _model_owner_required(self, owner_service: str) -> bool:
        return owner_service in self.required_model_owner_services

    def _model_availability_policy(self) -> dict[str, Any]:
        all_codes = tuple(MODEL_SERVICE_BY_CODE)
        disabled_codes = tuple(code for code in all_codes if code not in self.required_model_codes)
        return {
            "policy_version": "scheduler_staged_model_availability_v1",
            "required_model_codes": list(self.required_model_codes),
            "required_owner_services": list(self.required_model_owner_services),
            "disabled_model_codes": list(disabled_codes),
            "disabled_owner_services": [MODEL_SERVICE_BY_CODE[code] for code in disabled_codes],
            "disabled_status": "disabled_by_policy",
        }

    def _core_closure_self_gap_only(self, latest: dict[str, Any], details: dict[str, Any]) -> bool:
        """Prevent scheduler /readyz from deadlocking on data-inspector's scheduler_ready self-check."""
        run_id = latest.get("run_id")
        if run_id is None:
            return False
        status = str(latest.get("status") or "").lower()
        if status != "blocked":
            return False
        p0 = self._optional_int(latest.get("p0_gap_count")) or 0
        p1 = self._optional_int(latest.get("p1_gap_count")) or 0
        if p0 != 1 or p1 != 0:
            return False
        try:
            gaps = self._get_json(
                f"{self.data_inspector_base_url}/inspection-gaps?run_id={run_id}&severity=P0&limit=1000"
            ).get("response")
        except Exception as exc:  # noqa: BLE001
            details["data_inspector"]["core_closure_p0_gap_lookup_error"] = str(exc)
            return False
        if not isinstance(gaps, list):
            return False
        domain_codes = sorted({str(gap.get("domain_code") or "") for gap in gaps if isinstance(gap, dict)})
        details["data_inspector"]["core_closure_p0_gap_codes"] = domain_codes
        return domain_codes == ["scheduler_ready"]

    @staticmethod
    def _parse_dt(value: Any) -> datetime:
        if isinstance(value, datetime):
            parsed = value
        else:
            text = str(value)
            if text.endswith("Z"):
                text = f"{text[:-1]}+00:00"
            parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _get_json(self, url: str) -> dict[str, Any]:
        response = self.client.get(url, timeout=self.request_timeout_seconds)
        status_code = int(getattr(response, "status_code", 0))
        body = self._response_json(response)
        if not 200 <= status_code < 300:
            raise RuntimeError(f"GET {url} status_code={status_code}; body={self._response_text(response)}")
        return body

    def _post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self.client.post(url, json=payload, timeout=self.request_timeout_seconds)
        status_code = int(getattr(response, "status_code", 0))
        body = self._response_json(response)
        if not 200 <= status_code < 300:
            raise RuntimeError(f"POST {url} status_code={status_code}; body={self._response_text(response)}")
        return body

    @classmethod
    def _startup_guard_passed(cls, snapshot: dict[str, Any]) -> bool:
        return snapshot.get("startup_guard_status") == "ready" and cls._inspection_body_passed(
            {
                "status": snapshot.get("startup_guard_inspection_status"),
                "p0_gap_count": snapshot.get("startup_guard_p0_gap_count"),
                "p1_gap_count": snapshot.get("startup_guard_p1_gap_count"),
            }
        )

    @staticmethod
    def _inspection_body_passed(body: dict[str, Any]) -> bool:
        status = str(body.get("status") or "").lower()
        p0 = SchedulerRuntime._optional_int(body.get("p0_gap_count")) or 0
        p1 = SchedulerRuntime._optional_int(body.get("p1_gap_count")) or 0
        return status in {"ready", "passed", "ok", "completed"} and p0 == 0 and p1 == 0

    @staticmethod
    def _response_json(response: Any) -> dict[str, Any]:
        try:
            body = response.json()
        except Exception:  # noqa: BLE001
            return {}
        return body if isinstance(body, dict) else {"response": body}

    @staticmethod
    def _response_text(response: Any) -> str:
        text = str(getattr(response, "text", ""))
        return text[:500]

    @staticmethod
    def _source_catch_up_instance_payload(
        instance: Any,
        *,
        force_resubmit: bool,
        catch_up_run_id: str,
    ) -> dict[str, Any]:
        payload = instance.to_dict()
        request_body = dict(payload.get("request_body") or {})
        if force_resubmit:
            payload["original_biz_key"] = payload["biz_key"]
            payload["original_idempotency_key"] = payload["idempotency_key"]
            payload["biz_key"] = f"{payload['biz_key']}:catchup:{catch_up_run_id}"
            payload["idempotency_key"] = f"{payload['idempotency_key']}:catchup:{catch_up_run_id}"
            if request_body.get("idempotency_key"):
                request_body["idempotency_key"] = f"{request_body['idempotency_key']}:catchup:{catch_up_run_id}"
            payload["catch_up_run_id"] = catch_up_run_id
        payload["request_body"] = request_body
        return payload

    def _model_catch_up_instance_payload(
        self,
        instance: dict[str, Any],
        *,
        force_resubmit: bool,
        catch_up_run_id: str,
        checked_at: datetime,
    ) -> dict[str, Any]:
        payload = dict(instance)
        scheduled_at = self._parse_dt(payload["scheduled_at"])
        original_biz_key = str(payload["biz_key"])
        if force_resubmit:
            payload["original_biz_key"] = original_biz_key
            payload["biz_key"] = f"{original_biz_key}:catchup:{catch_up_run_id}"
        scheduler_payload = self._model_task_payload(payload)
        scheduler_payload["run_id"] = (
            f"scheduler-catchup:{catch_up_run_id}:{payload['task_code']}:{payload['trading_day']}:{payload['run_slot']}"
        )
        if payload["task_code"] == "t_relay.observation.monitor.snapshot_5m":
            scheduler_payload["as_of_time_utc"] = checked_at.astimezone(timezone.utc).isoformat()
        materialized = scheduler_payload.get("_scheduler_materialized_instance")
        if isinstance(materialized, dict):
            materialized.update(
                {
                    "catch_up_run_id": catch_up_run_id,
                    "catch_up_reason": "model_schedule_reconcile",
                    "captured_late": scheduled_at < checked_at,
                    "original_scheduled_at": instance.get("scheduled_at"),
                    "original_scheduled_at_local": instance.get("scheduled_at_local"),
                    "catch_up_checked_at": checked_at.astimezone(timezone.utc).isoformat(),
                }
            )
            if force_resubmit:
                materialized["force_resubmit"] = True
                materialized["original_biz_key"] = original_biz_key
        payload["scheduler_payload"] = scheduler_payload
        payload["effective_as_of_time_utc"] = scheduler_payload.get("as_of_time_utc")
        payload["catch_up_run_id"] = catch_up_run_id
        return payload

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _normalize_filter(values: list[str] | None) -> set[str]:
        return {str(item).strip() for item in (values or []) if str(item).strip()}

    @staticmethod
    def _env_bool(explicit: bool | None, env_name: str, *, default: bool) -> bool:
        if explicit is not None:
            return bool(explicit)
        raw = os.getenv(env_name)
        if raw is None:
            return default
        return raw.strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _coerce_symbols(value: list[str] | str | None) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return [str(item).strip() for item in value if str(item).strip()]


runtime = SchedulerRuntime()
