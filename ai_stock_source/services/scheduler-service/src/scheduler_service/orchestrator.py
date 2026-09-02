from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any

from scheduler_service.hot_plan import HOT_CANDIDATES_TASKS, ScheduledTask, validate_hot_plan_contract


@dataclass(frozen=True)
class HotWorkflowEvent:
    task_code: str
    task_kind: str
    owner_service: str
    accepted: bool
    official_publish: bool
    append_only: bool
    message: str
    event_time: datetime

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class HotWorkflowOrchestrator:
    """Contract-level orchestrator for the complete hot model chain.

    It does not fake provider or model results. It validates that a live deployment can
    dispatch the right tasks in the right order, and that only release_gate can publish
    official model facts while observation/outcome/evolution remain append-only.
    """

    def __init__(self) -> None:
        self.tasks: dict[str, ScheduledTask] = {task.task_code: task for task in HOT_CANDIDATES_TASKS}
        self.events: list[HotWorkflowEvent] = []

    def trigger(self, task_code: str, *, allow_live_dispatch: bool = False) -> HotWorkflowEvent:
        task = self.tasks.get(task_code)
        if task is None:
            raise ValueError(f"unknown hot workflow task: {task_code}")
        if allow_live_dispatch:
            raise RuntimeError("live dispatch must be bound to deployment endpoints; contract orchestrator refuses fake success")
        if task.task_kind == "source_collect" and task.is_official_publish:
            raise RuntimeError("source collection task may not publish official model facts")
        if task.task_kind in {"observation", "outcome", "evolution"} and not task.append_only:
            raise RuntimeError(f"{task.task_kind} task must be append-only: {task_code}")
        event = HotWorkflowEvent(
            task_code=task.task_code,
            task_kind=task.task_kind,
            owner_service=task.owner_service,
            accepted=True,
            official_publish=task.is_official_publish,
            append_only=task.append_only,
            message="contract trigger accepted; external side effects are intentionally not fabricated",
            event_time=datetime.now(timezone.utc),
        )
        self.events.append(event)
        return event

    def validate_full_chain(self) -> dict[str, Any]:
        validation = validate_hot_plan_contract()
        kinds = [task.task_kind for task in HOT_CANDIDATES_TASKS]
        return {
            "contract_kind": "hot_workflow_orchestrator_validation_v1",
            "scheduler_plan_valid": validation["valid"],
            "has_source_collect": "source_collect" in kinds,
            "has_model_compute": "model_compute" in kinds,
            "has_release_gate": "release_gate" in kinds,
            "has_buy_point": "buy_point" in kinds,
            "has_observation": "observation" in kinds,
            "has_outcome": "outcome" in kinds,
            "has_evolution": "evolution" in kinds,
            "only_release_gate_publishes": validation["official_publish_tasks"] == ["hot.release_gate.preopen"],
            "valid": validation["valid"],
        }
