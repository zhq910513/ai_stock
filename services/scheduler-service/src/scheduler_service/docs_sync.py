from __future__ import annotations

from pathlib import Path
from typing import Any

from scheduler_service.three_model_plan import THREE_MODEL_SCHEDULER_VERSION, THREE_MODEL_TASKS, validate_three_model_plan_contract
from scheduler_service.three_model_dispatch import (
    MODEL_PAYLOAD_PREFLIGHT_VERSION,
    RESEARCH_PAYLOAD_ASSEMBLER_CONTRACT,
    THREE_MODEL_LIVE_DISPATCH_VERSION,
    ThreeModelLiveDispatcher,
)
from scheduler_service.three_model_materializer import THREE_MODEL_MATERIALIZER_VERSION
from scheduler_service.runtime import MODEL_TIME_WHEEL_VERSION, SCHEDULER_RUNTIME_VERSION
from scheduler_service.source_schedule import SOURCE_SCHEDULE_REGISTRY_VERSION, SOURCE_TIME_WHEEL_VERSION

DOC_SYNC_VERSION = "scheduler_docs_sync_v1"

REQUIRED_DOCS = [
    "services/scheduler-service/README.md",
    "services/scheduler-service/DATA_ASSETS.md",
]

REQUIRED_TOKENS = [
    THREE_MODEL_SCHEDULER_VERSION,
    THREE_MODEL_LIVE_DISPATCH_VERSION,
    THREE_MODEL_MATERIALIZER_VERSION,
    SCHEDULER_RUNTIME_VERSION,
    SOURCE_SCHEDULE_REGISTRY_VERSION,
    SOURCE_TIME_WHEEL_VERSION,
    MODEL_TIME_WHEEL_VERSION,
    MODEL_PAYLOAD_PREFLIGHT_VERSION,
    RESEARCH_PAYLOAD_ASSEMBLER_CONTRACT,
    "GET /scheduler/materialize/three-models",
    "GET /scheduler/source-schedule/registry",
    "GET /scheduler/validate/source-schedule",
    "GET /scheduler/materialize/source-schedule",
    "POST /scheduler/source-schedule/catch-up",
    "POST /scheduler/source-fetch/temporary",
    "POST /scheduler/source-time-wheel/run-once",
    "POST /scheduler/model-time-wheel/run-once",
    "POST /scheduler/model-schedule/catch-up",
    "GET /scheduler/model-payload/requirements",
    "POST /scheduler/model-payload/preflight",
    "POST /scheduler/model-payload/assemble-preflight",
    "scheduler_research_payload_assemble_preflight_v1",
    "scheduler_payload_assembly_required",
    "SCHEDULER_MODEL_TIME_WHEEL_LIVE_DISPATCH",
    "GET /scheduler/live-dispatch/sample/{task_code}",
    "GET /scheduler/validate/live-dispatch-samples",
    "POST /scheduler/trigger",
    "GET /scheduler/validate/docs-sync",
    "GET /scheduler/runtime/status",
    "POST /inspection-runs",
    "startup_guard",
    "hot.release_gate.preopen",
    "memory.release_gate.close",
    "ambush.phase3.release_gate.close",
    "ambush_watchlist_service_v1.0_rc_backend_closure_candidate",
    "POST /production/release-gate/evaluate",
    "POST /production/pre-signal/detect",
    "POST /ambush/phase3/run",
    "candidate-memory-service",
    "`row`",
    "`payload`",
    "_scheduler_context",
    "three_model_live_dispatch_sample_v1",
    "scheduler_live_dispatch_sample_v1",
]


def validate_scheduler_docs_sync(project_root: str | Path) -> dict[str, Any]:
    root = Path(project_root)
    missing_docs: list[str] = []
    docs_text = ""
    for rel in REQUIRED_DOCS:
        path = root / rel
        if not path.exists():
            missing_docs.append(rel)
            continue
        docs_text += f"\n<!-- {rel} -->\n" + path.read_text(encoding="utf-8")
    missing_tokens = [token for token in REQUIRED_TOKENS if token not in docs_text]
    plan_validation = validate_three_model_plan_contract()
    expected_owner_endpoint_rows = [
        f"| `{task.task_code}` | `{task.owner_service}` | `POST {ThreeModelLiveDispatcher.path_for(task)}` |"
        for task in THREE_MODEL_TASKS
    ]
    missing_owner_endpoint_rows = [
        row for row in expected_owner_endpoint_rows if row not in docs_text
    ]
    return {
        "contract_kind": "scheduler_docs_sync_validation_v1",
        "docs_sync_version": DOC_SYNC_VERSION,
        "project_root": str(root),
        "required_docs": REQUIRED_DOCS,
        "missing_docs": missing_docs,
        "missing_tokens": missing_tokens,
        "missing_owner_endpoint_rows": missing_owner_endpoint_rows,
        "plan_valid": plan_validation["valid"],
        "official_publish_tasks": plan_validation["official_publish_tasks"],
        "valid": not missing_docs and not missing_tokens and not missing_owner_endpoint_rows and plan_validation["valid"],
        "hard_rules": [
            "Every scheduler code optimization must update services/scheduler-service/README.md.",
            "Official publish task list in README must match code validation.",
            "Materialization, dispatch and docs-sync APIs must be documented in the single service README before package handoff.",
        ],
    }
