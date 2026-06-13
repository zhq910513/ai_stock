from __future__ import annotations

import pytest

from scheduler_service.orchestrator import HotWorkflowOrchestrator


def test_hot_workflow_orchestrator_validates_complete_chain() -> None:
    orchestrator = HotWorkflowOrchestrator()
    validation = orchestrator.validate_full_chain()
    assert validation["valid"] is True
    assert validation["only_release_gate_publishes"] is True
    assert validation["has_observation"] is True
    assert validation["has_evolution"] is True


def test_hot_workflow_orchestrator_refuses_fake_live_dispatch() -> None:
    orchestrator = HotWorkflowOrchestrator()
    with pytest.raises(RuntimeError):
        orchestrator.trigger("hot.release_gate.preopen", allow_live_dispatch=True)
    event = orchestrator.trigger("hot.observe.intraday")
    assert event.append_only is True
    assert event.official_publish is False
