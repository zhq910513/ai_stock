from __future__ import annotations

from typing import Any

from scheduler_service.runtime import SchedulerRuntime, SCHEDULER_RUNTIME_VERSION


class FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, Any], text: str = "") -> None:
        self.status_code = status_code
        self.payload = payload
        self.text = text

    def json(self) -> dict[str, Any]:
        return self.payload


class ReadyInspectorClient:
    def __init__(self) -> None:
        self.gets: list[tuple[str, float]] = []
        self.posts: list[tuple[str, dict[str, Any], float]] = []

    def get(self, url: str, *, timeout: float) -> FakeResponse:
        self.gets.append((url, timeout))
        return FakeResponse(200, {"status": "ready", "service": "data-inspector-service"})

    def post(self, url: str, *, json: dict[str, Any], timeout: float) -> FakeResponse:
        self.posts.append((url, json, timeout))
        return FakeResponse(
            201,
            {
                "run_id": "startup-1",
                "status": "ready",
                "p0_gap_count": 0,
                "p1_gap_count": 0,
            },
        )


class DelayedInspectorClient(ReadyInspectorClient):
    def __init__(self) -> None:
        super().__init__()
        self.fail_first_get = True

    def get(self, url: str, *, timeout: float) -> FakeResponse:
        self.gets.append((url, timeout))
        if self.fail_first_get:
            self.fail_first_get = False
            return FakeResponse(503, {"status": "not_ready"}, text="not ready")
        return FakeResponse(200, {"status": "ready", "service": "data-inspector-service"})


def test_runtime_guard_requires_background_data_inspector_and_startup_guard() -> None:
    client = ReadyInspectorClient()
    runtime = SchedulerRuntime(
        client=client,
        data_inspector_base_url="http://data-inspector:8025",
        poll_seconds=1,
        request_timeout_seconds=1,
        startup_guard_max_subjects=1,
    )

    runtime.run_startup_cycle()
    snapshot = runtime.ready_snapshot()

    assert snapshot["status"] == "ready"
    assert snapshot["runtime_version"] == SCHEDULER_RUNTIME_VERSION
    assert snapshot["checks"]["background_loop"]["status"] == "ready"
    assert snapshot["checks"]["data_inspector"]["status"] == "ready"
    assert snapshot["checks"]["startup_guard"]["status"] == "ready"
    assert snapshot["checks"]["startup_guard"]["run_id"] == "startup-1"
    assert client.gets[0][0] == "http://data-inspector:8025/readyz"
    assert client.posts[0][0] == "http://data-inspector:8025/inspection-runs"
    assert client.posts[0][1]["scope"] == "startup_guard"
    assert client.posts[0][1]["persist"] is True
    assert client.posts[0][1]["max_subjects"] == 1


def test_runtime_guard_retries_startup_guard_after_data_inspector_becomes_ready() -> None:
    client = DelayedInspectorClient()
    runtime = SchedulerRuntime(
        client=client,
        data_inspector_base_url="http://data-inspector:8025",
        poll_seconds=1,
        request_timeout_seconds=1,
        startup_guard_max_subjects=1,
    )

    runtime.run_startup_cycle()
    first = runtime.ready_snapshot()
    runtime.run_startup_cycle()
    second = runtime.ready_snapshot()

    assert first["status"] == "not_ready"
    assert first["checks"]["data_inspector"]["status"] == "not_ready"
    assert first["checks"]["startup_guard"]["status"] == "not_started"
    assert second["status"] == "ready"
    assert len(client.posts) == 1
