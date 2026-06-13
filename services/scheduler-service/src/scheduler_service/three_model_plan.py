from __future__ import annotations

from scheduler_service.hot_plan import HOT_CANDIDATES_TASKS, ScheduledTask

THREE_MODEL_SCHEDULER_VERSION = "three_model_scheduler_design_v1"

CANDIDATE_MEMORY_TASKS: tuple[ScheduledTask, ...] = (
    ScheduledTask(
        task_code="memory.seed.from_hot_signals",
        task_kind="model_compute",
        owner_service="candidate-memory-service",
        schedule_hint="15:45 after hot official signal and observation snapshots",
        frequency_hint="daily_close",
        reads_from=["decision_hot.hot_signal_fact_v1", "decision_hot.hot_observation_snapshot_v1", "decision_hot.hot_outcome_label_v1"],
        writes_to=["decision_memory.memory_seed_v1", "decision_memory.memory_entity_v1"],
        notes="Creates/updates memory entities from locked hot model facts; does not publish official memory signals.",
    ),
    ScheduledTask(
        task_code="memory.pre_signal.scan",
        task_kind="model_compute",
        owner_service="candidate-memory-service",
        schedule_hint="15:55 close confirmed; optional 10:30 research scan",
        frequency_hint="daily_close_plus_optional_intraday_research",
        reads_from=["decision_memory.memory_entity_v1", "source.daily_bar_v1", "source.moneyflow_snapshot_v1", "source.sector_snapshot_v1"],
        writes_to=["decision_memory.pre_signal_case_v1", "decision_memory.memory_score_fact_v1"],
        notes="Computes ex-ante pre-signal facts only with available_at <= decision_time.",
    ),
    ScheduledTask(
        task_code="memory.release_gate.close",
        task_kind="release_gate",
        owner_service="candidate-memory-service",
        schedule_hint="16:05 close confirmed",
        frequency_hint="daily_close",
        reads_from=["decision_memory.pre_signal_case_v1", "decision_memory.memory_score_fact_v1"],
        writes_to=["decision_memory.memory_release_gate_audit_v1", "decision_memory.memory_signal_fact_v1", "governance.model_signal_registry_v1"],
        is_official_publish=True,
        notes="Only this task may promote official candidate-memory signals.",
    ),
    ScheduledTask(
        task_code="memory.buy_point.next_session_reference",
        task_kind="buy_point",
        owner_service="execution-timing-service",
        schedule_hint="next trading day 09:30-10:00 reference evaluation",
        frequency_hint="next_session_open_window",
        reads_from=["decision_memory.memory_signal_fact_v1", "source.minute_bar_v1", "source.realtime_quote_v1"],
        writes_to=["decision_memory.memory_buy_point_v1"],
        notes="Freezes memory model evaluation reference price; not trading advice.",
    ),
    ScheduledTask(
        task_code="memory.observe.outcome.evolution",
        task_kind="outcome",
        owner_service="candidate-memory-service",
        schedule_hint="daily 15:50 plus T+5/T+20/T+40 maturity checks",
        frequency_hint="daily_maturity",
        reads_from=["decision_memory.memory_signal_fact_v1", "decision_memory.memory_buy_point_v1", "source.daily_bar_v1"],
        writes_to=["decision_memory.memory_observation_snapshot_v1", "decision_memory.memory_outcome_label_v1", "decision_memory.memory_failure_attribution_v1", "decision_memory.memory_evolution_sample_v1"],
        notes="Append-only monitoring and delayed realization / second-wave / independent-cycle labels.",
    ),
)

AMBUSH_WATCHLIST_TASKS: tuple[ScheduledTask, ...] = (
    ScheduledTask(
        task_code="ambush.source_capability.audit",
        task_kind="source_collect",
        owner_service="ambush-watchlist-service",
        schedule_hint="weekly Sunday 20:00 and before new provider activation",
        frequency_hint="weekly_or_on_demand",
        reads_from=["source.daily_bar_v1", "source.weekly_bar_v1", "source.stock_master_v1"],
        writes_to=["governance.source_capability_audit_v1"],
        notes="Audits whether required OHLCV/adjusted/trading-state fields are usable. Source audit may not publish model facts.",
    ),
    ScheduledTask(
        task_code="ambush.pattern_library.mine",
        task_kind="model_compute",
        owner_service="ambush-watchlist-service",
        schedule_hint="daily 18:10 incremental; monthly full rebuild/shadow evaluation",
        frequency_hint="daily_incremental_monthly_rebuild",
        reads_from=["source.daily_bar_v1", "source.weekly_bar_v1", "decision_ambush.ambush_outcome_label_v1", "decision_ambush.ambush_failure_attribution_v1"],
        writes_to=["decision_ambush.valley_pattern_sample_v1", "decision_ambush.valley_shape_signature_v1", "decision_ambush.valley_pattern_prototype_v1", "decision_ambush.valley_pattern_library_version_v1"],
        notes="Updates positive, negative and hard-negative low-valley pattern assets. Offline only.",
    ),
    ScheduledTask(
        task_code="ambush.phase2.valley_turn.close",
        task_kind="model_compute",
        owner_service="ambush-watchlist-service",
        schedule_hint="15:20 after close-confirmed daily bars; optional 10:30 research scan",
        frequency_hint="daily_close_plus_research_intraday",
        reads_from=["source.daily_bar_v1", "source.weekly_bar_v1", "decision_ambush.valley_pattern_prototype_v1"],
        writes_to=["decision_ambush.valley_watch_pool_v1", "decision_ambush.effective_turn_anchor_v1", "decision_ambush.effective_turn_pool_v1", "decision_ambush.ambush_pool_transition_audit_v1"],
        notes="Computes low-valley pool and effective-turn anchors. Not an official signal.",
    ),
    ScheduledTask(
        task_code="ambush.phase3.release_gate.close",
        task_kind="release_gate",
        owner_service="ambush-watchlist-service",
        schedule_hint="15:35 close confirmed after Phase 2 and P1 context refresh",
        frequency_hint="daily_close",
        reads_from=["decision_ambush.effective_turn_pool_v1", "source.moneyflow_snapshot_v1", "source.sector_snapshot_v1", "source.market_regime_snapshot_v1"],
        writes_to=["decision_ambush.deep_confirmation_pool_v1", "decision_ambush.ambush_score_fact_v1", "decision_ambush.ambush_release_gate_audit_v1", "decision_ambush.ambush_signal_fact_v1", "governance.model_signal_registry_v1"],
        is_official_publish=True,
        notes="Only this task may promote official ambush signals after deep confirmation and release gate pass.",
    ),
    ScheduledTask(
        task_code="ambush.buy_point.reference",
        task_kind="buy_point",
        owner_service="ambush-watchlist-service",
        schedule_hint="15:35 close reference; next-session open-window integration later",
        frequency_hint="daily_close_reference",
        reads_from=["decision_ambush.ambush_signal_fact_v1", "source.daily_bar_v1"],
        writes_to=["decision_ambush.ambush_buy_point_v1"],
        notes="Freezes first evaluation benchmark price for ambush signal; not trading advice.",
    ),
    ScheduledTask(
        task_code="ambush.observe.outcome.evolution",
        task_kind="outcome",
        owner_service="ambush-watchlist-service",
        schedule_hint="daily 15:55 plus T+5/T+10/T+20 maturity checks",
        frequency_hint="daily_maturity",
        reads_from=["decision_ambush.ambush_signal_fact_v1", "decision_ambush.ambush_buy_point_v1", "source.daily_bar_v1"],
        writes_to=["decision_ambush.ambush_observation_snapshot_v1", "decision_ambush.ambush_outcome_label_v1", "decision_ambush.ambush_failure_attribution_v1", "decision_ambush.ambush_evolution_sample_v1", "decision_ambush.ambush_formula_version_evaluation_v1"],
        notes="Append-only observation/outcome/failure attribution and hard-negative/positive pattern-library feedback.",
    ),
)

THREE_MODEL_TASKS: tuple[ScheduledTask, ...] = HOT_CANDIDATES_TASKS + CANDIDATE_MEMORY_TASKS + AMBUSH_WATCHLIST_TASKS


def three_model_plan() -> list[dict]:
    return [task.to_dict() for task in THREE_MODEL_TASKS]


def validate_three_model_plan_contract() -> dict:
    tasks = list(THREE_MODEL_TASKS)
    official_publish_tasks = [task.task_code for task in tasks if task.is_official_publish]
    expected_publishers = ["hot.release_gate.preopen", "memory.release_gate.close", "ambush.phase3.release_gate.close"]
    source_publish_violations = [task.task_code for task in tasks if task.task_kind == "source_collect" and task.is_official_publish]
    append_only_violations = [
        task.task_code
        for task in tasks
        if task.task_kind in {"observation", "outcome", "evolution"} and not task.append_only
    ]
    direct_cross_model_write_violations = [
        task.task_code
        for task in tasks
        if task.owner_service == "ambush-watchlist-service" and any(target.startswith("decision_hot.") or target.startswith("decision_memory.") for target in task.writes_to)
    ]
    return {
        "contract_kind": "three_model_scheduler_plan_validation_v1",
        "scheduler_version": THREE_MODEL_SCHEDULER_VERSION,
        "task_count": len(tasks),
        "official_publish_tasks": official_publish_tasks,
        "source_publish_violations": source_publish_violations,
        "append_only_violations": append_only_violations,
        "direct_cross_model_write_violations": direct_cross_model_write_violations,
        "expected_publishers": expected_publishers,
        "valid": official_publish_tasks == expected_publishers
        and not source_publish_violations
        and not append_only_violations
        and not direct_cross_model_write_violations,
        "hard_rules": [
            "Source tasks write source/governance facts only and never publish official signals.",
            "Only model-specific release_gate tasks may write official signal facts.",
            "Observation/outcome/evolution tasks are append-only.",
            "Scheduler dispatches owner services; it does not fabricate model outputs.",
            "Locked model one and model two services are not mutated by ambush scheduler tasks.",
        ],
    }
