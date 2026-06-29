from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Literal

TaskKind = Literal["source_collect", "model_compute", "release_gate", "buy_point", "observation", "outcome", "evolution"]


@dataclass(frozen=True)
class ScheduledTask:
    task_code: str
    task_kind: TaskKind
    owner_service: str
    schedule_hint: str
    frequency_hint: str
    writes_to: list[str]
    reads_from: list[str]
    is_official_publish: bool = False
    append_only: bool = True
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


HOT_CANDIDATES_TASKS: tuple[ScheduledTask, ...] = (
    ScheduledTask(
        task_code="source.auction.collect.0915_0925",
        task_kind="source_collect",
        owner_service="source-data-service",
        schedule_hint="09:15-09:25 every 15-30 seconds",
        frequency_hint="15-30s",
        reads_from=["source-data-service:/source/fetch/plan", "source-data-service:/source/fetch/submit"],
        writes_to=["source.auction_snapshot_v1"],
        notes="Submit high-frequency auction fetch work through source-data-service orchestration; never calls providers directly.",
    ),
    ScheduledTask(
        task_code="source.auction.freeze.092505_092530",
        task_kind="source_collect",
        owner_service="source-data-service",
        schedule_hint="09:25:05,09:25:30",
        frequency_hint="fixed_time",
        reads_from=["source-data-service:/source/fetch/plan", "source-data-service:/source/fetch/submit"],
        writes_to=["source.auction_snapshot_v1"],
        notes="Submit auction freeze fetch work through source-data-service orchestration for decision-time lineage.",
    ),
    ScheduledTask(
        task_code="hot.score.auction_confirmed",
        task_kind="model_compute",
        owner_service="hot-candidates-service",
        schedule_hint="09:26:00,09:28:00,09:29:30",
        frequency_hint="fixed_time",
        reads_from=[
            "source.stock_master_v1",
            "source.trade_status_v1",
            "source.daily_bar_v1",
            "source.adjusted_daily_bar_v1",
            "source.stock_moneyflow_daily_v1",
            "source.event_news_v1",
            "source.realtime_quote_v1",
            "source.minute_bar_v1",
            "decision_hot.hot_decision_case_v1",
        ],
        writes_to=["decision_hot.hot_feature_matrix_v1", "decision_hot.hot_score_fact_v1"],
        notes="Computes stage scores; does not itself create official signals.",
    ),
    ScheduledTask(
        task_code="hot.release_gate.preopen",
        task_kind="release_gate",
        owner_service="hot-candidates-service",
        schedule_hint="09:25:40,09:28:40,09:29:40 deadline 09:30:00",
        frequency_hint="fixed_time",
        reads_from=["decision_hot.hot_score_fact_v1", "decision_hot.hot_evidence_snapshot_v1"],
        writes_to=["decision_hot.hot_release_gate_audit_v1", "decision_hot.hot_signal_fact_v1", "governance.model_signal_registry_v1"],
        is_official_publish=True,
        notes="Only this task may promote official hot signals after release gate passes.",
    ),
    ScheduledTask(
        task_code="source.open_5m.collect",
        task_kind="source_collect",
        owner_service="source-data-service",
        schedule_hint="09:30-09:36 every 30-60 seconds",
        frequency_hint="30-60s",
        reads_from=["source-data-service:/source/fetch/plan", "source-data-service:/source/fetch/submit"],
        writes_to=["source.minute_bar_v1", "source.realtime_quote_v1"],
        notes="Submit open-window minute/quote fetch work through source-data-service orchestration.",
    ),
    ScheduledTask(
        task_code="hot.buy_point.open_5m",
        task_kind="buy_point",
        owner_service="hot-candidates-service",
        schedule_hint="09:30-09:36 every 30-60 seconds; fixed 09:35,09:45,10:00",
        frequency_hint="30-60s in opening window",
        reads_from=[
            "decision_hot.hot_decision_case_v1",
            "decision_hot.hot_score_fact_v1",
            "source.minute_bar_v1",
            "source.auction_snapshot_v1",
        ],
        writes_to=["decision_hot.hot_buy_point_v1"],
        notes="Freezes first evaluation reference price from scored hot cases; release audit/signal are not hard prerequisites, and blocked rows remain explicit diagnostics, not trading instructions.",
    ),
    ScheduledTask(
        task_code="hot.observe.intraday",
        task_kind="observation",
        owner_service="hot-candidates-service",
        schedule_hint="09:30-10:00 every 60s; 10:00-14:30 every 300s; 14:30-15:00 every 60-180s",
        frequency_hint="60s/300s dynamic",
        reads_from=[
            "decision_hot.hot_signal_fact_v1",
            "decision_hot.hot_buy_point_v1",
            "source.realtime_quote_v1",
            "source.minute_bar_v1",
            "source.daily_bar_v1",
            "source.adjusted_daily_bar_v1",
        ],
        writes_to=["decision_hot.hot_observation_snapshot_v1"],
        notes="Append-only second and later observations; never overwrites initial decision.",
    ),
    ScheduledTask(
        task_code="hot.outcome.t5_t20",
        task_kind="outcome",
        owner_service="hot-candidates-service",
        schedule_hint="15:10,15:40 plus T+5/T+20 maturity checks",
        frequency_hint="daily_maturity",
        reads_from=["decision_hot.hot_observation_snapshot_v1", "decision_hot.hot_buy_point_v1", "source.trade_calendar_v1"],
        writes_to=["decision_hot.hot_outcome_label_v1", "decision_hot.hot_failure_attribution_v1"],
        notes="Labels direction/execution/path/environment/data independently.",
    ),
    ScheduledTask(
        task_code="hot.evolution.offline",
        task_kind="evolution",
        owner_service="hot-candidates-service",
        schedule_hint="18:30 after matured labels",
        frequency_hint="daily_offline",
        reads_from=["decision_hot.hot_initial_decision_snapshot_v1", "decision_hot.hot_observation_snapshot_v1", "decision_hot.hot_outcome_label_v1", "decision_hot.hot_failure_attribution_v1"],
        writes_to=["decision_hot.hot_evolution_sample_v1", "decision_hot.hot_model_version_evaluation_v1"],
        notes="Produces candidate adjustments and shadow-run inputs; never mutates production weights online.",
    ),
)


def hot_plan() -> list[dict]:
    return [task.to_dict() for task in HOT_CANDIDATES_TASKS]


def validate_hot_plan_contract() -> dict:
    """Validate hot workflow order and guardrails without dispatching tasks."""
    tasks = list(HOT_CANDIDATES_TASKS)
    index = {task.task_code: pos for pos, task in enumerate(tasks)}
    required_order = [
        "source.auction.collect.0915_0925",
        "source.auction.freeze.092505_092530",
        "hot.score.auction_confirmed",
        "hot.release_gate.preopen",
        "source.open_5m.collect",
        "hot.buy_point.open_5m",
        "hot.observe.intraday",
        "hot.outcome.t5_t20",
        "hot.evolution.offline",
    ]
    missing = [code for code in required_order if code not in index]
    order_ok = not missing and all(index[required_order[i]] < index[required_order[i + 1]] for i in range(len(required_order) - 1))
    official_publish_tasks = [task.task_code for task in tasks if task.is_official_publish]
    append_only_violations = [
        task.task_code
        for task in tasks
        if task.task_kind in {"observation", "outcome", "evolution"} and not task.append_only
    ]
    source_publish_violations = [
        task.task_code
        for task in tasks
        if task.task_kind == "source_collect" and task.is_official_publish
    ]
    provider_read_violations = [
        task.task_code
        for task in tasks
        if any(source.startswith("provider.") for source in task.reads_from)
    ]
    raw_read_violations = [
        task.task_code
        for task in tasks
        if any(source.startswith("raw.") or source.startswith("raw_") for source in task.reads_from)
    ]
    source_wildcard_violations = [
        task.task_code
        for task in tasks
        if any(source == "source.*" for source in task.reads_from)
    ]
    source_orchestration_violations = [
        task.task_code
        for task in tasks
        if task.task_code.startswith("source.")
        and (
            task.owner_service != "source-data-service"
            or "source-data-service:/source/fetch/submit" not in task.reads_from
        )
    ]
    return {
        "contract_kind": "hot_scheduler_plan_validation_v1",
        "order_ok": order_ok,
        "missing_required_tasks": missing,
        "official_publish_tasks": official_publish_tasks,
        "append_only_violations": append_only_violations,
        "source_publish_violations": source_publish_violations,
        "provider_read_violations": provider_read_violations,
        "raw_read_violations": raw_read_violations,
        "source_wildcard_violations": source_wildcard_violations,
        "source_orchestration_violations": source_orchestration_violations,
        "valid": order_ok
        and official_publish_tasks == ["hot.release_gate.preopen"]
        and not append_only_violations
        and not source_publish_violations
        and not provider_read_violations
        and not raw_read_violations
        and not source_wildcard_violations
        and not source_orchestration_violations,
    }
