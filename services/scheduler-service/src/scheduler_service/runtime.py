from __future__ import annotations

import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

import httpx

SCHEDULER_RUNTIME_VERSION = "scheduler_runtime_guard_v1"


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
    warning_codes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in ("started_at", "heartbeat_at", "data_inspector_checked_at"):
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
        data_inspector_base_url: str | None = None,
        poll_seconds: float | None = None,
        request_timeout_seconds: float | None = None,
        startup_guard_request_timeout_seconds: float | None = None,
        startup_guard_scope: str | None = None,
        startup_guard_lookback_days: int | None = None,
        startup_guard_max_subjects: int | None = None,
        startup_guard_retry_attempts: int | None = None,
    ) -> None:
        self.client = client or httpx.Client()
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
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._startup_guard_attempt_count = 0
        self.snapshot = RuntimeSnapshot(
            data_inspector_base_url=self.data_inspector_base_url,
            poll_seconds=self.poll_seconds,
        )

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            now = datetime.now(timezone.utc)
            self.snapshot.started_at = now
            self.snapshot.background_loop_running = True
            self.snapshot.startup_guard_status = "pending"
            self.snapshot.startup_guard_error = None
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
            startup_ready = self.snapshot.startup_guard_status == "ready"
            inspector_ready = self.snapshot.data_inspector_status == "ready"
            attempts_remaining = self._startup_guard_attempt_count < self.startup_guard_retry_attempts
        if not startup_ready and inspector_ready and attempts_remaining:
            self._trigger_startup_guard()

    def ready_snapshot(self) -> dict[str, Any]:
        with self._lock:
            snapshot = self.snapshot.to_dict()
        heartbeat_text = snapshot.get("heartbeat_at")
        heartbeat_ok = False
        if heartbeat_text:
            heartbeat = datetime.fromisoformat(str(heartbeat_text))
            heartbeat_ok = datetime.now(timezone.utc) - heartbeat <= timedelta(seconds=max(self.poll_seconds * 2, 10))
        background_ok = bool(snapshot.get("background_loop_running")) and heartbeat_ok
        startup_ok = snapshot.get("startup_guard_status") == "ready"
        inspector_ok = snapshot.get("data_inspector_status") == "ready"
        ready = background_ok and startup_ok and inspector_ok
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
                    "status": "ready" if startup_ok else snapshot.get("startup_guard_status"),
                    "run_id": snapshot.get("startup_guard_run_id"),
                    "inspection_status": snapshot.get("startup_guard_inspection_status"),
                    "p0_gap_count": snapshot.get("startup_guard_p0_gap_count"),
                    "p1_gap_count": snapshot.get("startup_guard_p1_gap_count"),
                    "attempt_count": self._startup_guard_attempt_count,
                    "max_attempts": self.startup_guard_retry_attempts,
                    "error": snapshot.get("startup_guard_error"),
                },
            },
            "warning_codes": snapshot.get("warning_codes") or [],
        }

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
                    self.snapshot.startup_guard_status = "ready"
                    self.snapshot.startup_guard_run_id = body.get("run_id")
                    self.snapshot.startup_guard_inspection_status = str(body.get("status") or "unknown")
                    self.snapshot.startup_guard_p0_gap_count = self._optional_int(body.get("p0_gap_count"))
                    self.snapshot.startup_guard_p1_gap_count = self._optional_int(body.get("p1_gap_count"))
                    self.snapshot.startup_guard_error = None
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
    def _optional_int(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None


runtime = SchedulerRuntime()
