from __future__ import annotations

from scheduler_service.live_dispatch import HotLiveDispatcher, OwnerEndpointRegistry


class FakeResponse:
    status_code = 200
    def json(self):
        return {"ok": True}


class FakeClient:
    def __init__(self) -> None:
        self.calls = []
    def post(self, url, *, json, timeout):
        self.calls.append((url, json, timeout))
        return FakeResponse()


def test_live_dispatch_requires_real_owner_endpoint_and_routes_release_gate_to_production_endpoint() -> None:
    client = FakeClient()
    registry = OwnerEndpointRegistry.from_mapping({"hot-candidates-service": "http://hot:8031"})
    result = HotLiveDispatcher(registry, client=client).dispatch("hot.release_gate.preopen", payload={"row": {"symbol": "002354"}})
    assert result.accepted is True
    assert result.official_publish is True
    assert result.url == "http://hot:8031/production/release-gate/evaluate"
    assert client.calls[0][1]["task_code"] == "hot.release_gate.preopen"


def test_live_dispatch_refuses_missing_endpoint() -> None:
    dispatcher = HotLiveDispatcher(OwnerEndpointRegistry.from_mapping({}), client=FakeClient())
    try:
        dispatcher.dispatch("hot.observe.intraday", payload={})
    except RuntimeError as exc:
        assert "missing live endpoint" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected missing endpoint failure")
