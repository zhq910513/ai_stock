from __future__ import annotations

from scheduler_service.hot_plan import HOT_CANDIDATES_TASKS, ScheduledTask
from scheduler_service.source_schedule import scheduled_source_table_names

THREE_MODEL_SCHEDULER_VERSION = "core_model_scheduler_design_v2"

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
        reads_from=[
            "decision_memory.memory_entity_v1",
            "source.daily_bar_v1",
            "source.adjusted_daily_bar_v1",
            "source.stock_moneyflow_daily_v1",
            "source.event_news_v1",
        ],
        writes_to=["decision_memory.memory_pre_signal_case_v1", "decision_memory.memory_score_fact_v1"],
        notes="Computes ex-ante pre-signal facts only with available_at <= decision_time.",
    ),
    ScheduledTask(
        task_code="memory.release_gate.close",
        task_kind="release_gate",
        owner_service="candidate-memory-service",
        schedule_hint="16:05 close confirmed",
        frequency_hint="daily_close",
        reads_from=["decision_memory.memory_pre_signal_case_v1", "decision_memory.memory_score_fact_v1"],
        writes_to=["decision_memory.memory_release_gate_audit_v1", "decision_memory.memory_signal_fact_v1", "governance.model_signal_registry_v1"],
        is_official_publish=True,
        notes="Only this task may promote official candidate-memory signals.",
    ),
    ScheduledTask(
        task_code="memory.buy_point.next_session_reference",
        task_kind="buy_point",
        owner_service="candidate-memory-service",
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
        reads_from=["source.daily_bar_v1", "source.adjusted_daily_bar_v1", "source.stock_master_v1", "source.trade_status_v1"],
        writes_to=["governance.source_capability_audit_v1"],
        notes="Audits whether required OHLCV/adjusted/trading-state fields are usable. Source audit may not publish model facts.",
    ),
    ScheduledTask(
        task_code="ambush.pattern_library.mine",
        task_kind="model_compute",
        owner_service="ambush-watchlist-service",
        schedule_hint="daily 18:10 incremental; monthly full rebuild/shadow evaluation",
        frequency_hint="daily_incremental_monthly_rebuild",
        reads_from=[
            "source.daily_bar_v1",
            "source.adjusted_daily_bar_v1",
            "decision_ambush.ambush_outcome_label_v1",
            "decision_ambush.ambush_failure_attribution_v1",
        ],
        writes_to=["decision_ambush.valley_pattern_sample_v1", "decision_ambush.valley_shape_signature_v1", "decision_ambush.valley_pattern_prototype_v1", "decision_ambush.valley_pattern_library_version_v1"],
        notes="Updates positive, negative and hard-negative low-valley pattern assets. Offline only.",
    ),
    ScheduledTask(
        task_code="ambush.phase2.valley_turn.close",
        task_kind="model_compute",
        owner_service="ambush-watchlist-service",
        schedule_hint="15:20 after close-confirmed daily bars; optional 10:30 research scan",
        frequency_hint="daily_close_plus_research_intraday",
        reads_from=["source.daily_bar_v1", "source.adjusted_daily_bar_v1", "source.stock_moneyflow_daily_v1", "decision_ambush.valley_pattern_prototype_v1"],
        writes_to=["decision_ambush.valley_watch_pool_v1", "decision_ambush.effective_turn_anchor_v1", "decision_ambush.effective_turn_pool_v1", "decision_ambush.ambush_pool_transition_audit_v1"],
        notes="Computes low-valley pool and effective-turn anchors. Not an official signal.",
    ),
    ScheduledTask(
        task_code="ambush.phase3.release_gate.close",
        task_kind="release_gate",
        owner_service="ambush-watchlist-service",
        schedule_hint="15:35 close confirmed after Phase 2 and P1 context refresh",
        frequency_hint="daily_close",
        reads_from=[
            "decision_ambush.effective_turn_pool_v1",
            "source.stock_moneyflow_daily_v1",
            "source.event_news_v1",
            "source.trade_status_v1",
        ],
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

T_BOARD_RELAY_TASKS: tuple[ScheduledTask, ...] = (
    ScheduledTask(
        task_code="t_relay.day1.scan.close",
        task_kind="model_compute",
        owner_service="t-board-relay-service",
        schedule_hint="15:05-15:30 close confirmed",
        frequency_hint="daily_close",
        reads_from=[
            "source.daily_bar_v1",
            "source.limit_price_v1",
            "source.limit_event_v1",
            "source.realtime_quote_v1",
        ],
        writes_to=["decision_t_relay.t_board_day1_candidate_v1"],
        is_official_publish=False,
        notes="Scans Day1 T-board candidates for research relay; cannot publish official signals.",
    ),
    ScheduledTask(
        task_code="t_relay.day2.watch.rolling_5m",
        task_kind="model_compute",
        owner_service="t-board-relay-service",
        schedule_hint="09:30-10:30 every 5 minutes from next-session open",
        frequency_hint="rolling_5m_open_window",
        reads_from=[
            "decision_t_relay.t_board_day1_candidate_v1",
            "source.minute_bar_v1",
            "source.realtime_quote_v1",
            "decision.dynamic_feature_latest",
        ],
        writes_to=["decision_t_relay.t_board_day2_watch_snapshot_v1"],
        is_official_publish=False,
        notes="Builds Day2 rolling five-minute near-limit watch snapshots; source/dynamic gaps stay explicit.",
    ),
    ScheduledTask(
        task_code="t_relay.day2.trigger.rolling_5m",
        task_kind="model_compute",
        owner_service="t-board-relay-service",
        schedule_hint="09:30-10:30 every 5 minutes after Day1 qualification",
        frequency_hint="rolling_5m_open_window",
        reads_from=[
            "decision_t_relay.t_board_day2_watch_snapshot_v1",
            "source.minute_bar_v1",
            "source.realtime_quote_v1",
            "source.trade_tick_v1",
            "decision.dynamic_feature_latest",
        ],
        writes_to=[
            "decision_t_relay.t_board_day2_entry_trigger_v1",
            "decision_t_relay.t_board_game_hypothesis_snapshot_v1",
        ],
        is_official_publish=False,
        notes="Checks Day2 rolling near-limit trigger for research-only opportunity prompts.",
    ),
    ScheduledTask(
        task_code="t_relay.day2.post_entry.monitor",
        task_kind="observation",
        owner_service="t-board-relay-service",
        schedule_hint="after theoretical entry, every 5 minutes during 09:35-11:30 and 13:00-15:00",
        frequency_hint="rolling_5m_post_entry_sessions",
        reads_from=[
            "decision_t_relay.t_board_day2_entry_trigger_v1",
            "source.minute_bar_v1",
            "source.limit_event_v1",
        ],
        writes_to=[
            "decision_t_relay.t_board_post_entry_monitor_v1",
            "decision_t_relay.t_board_game_hypothesis_snapshot_v1",
        ],
        is_official_publish=False,
        append_only=True,
        notes="Append-only hard rule: any post-entry board open fails the research event.",
    ),
    ScheduledTask(
        task_code="t_relay.day3.exit.open",
        task_kind="model_compute",
        owner_service="t-board-relay-service",
        schedule_hint="Day3 09:25-11:30 every 5 minutes",
        frequency_hint="day3_morning_rolling_5m",
        reads_from=[
            "decision_t_relay.t_board_post_entry_monitor_v1",
            "source.minute_bar_v1",
            "source.limit_price_v1",
        ],
        writes_to=[
            "decision_t_relay.t_board_day3_exit_decision_v1",
            "decision_t_relay.t_board_game_hypothesis_snapshot_v1",
        ],
        is_official_publish=False,
        notes="Day3 morning rolling hold/exit research decisions; not a trading instruction.",
    ),
    ScheduledTask(
        task_code="t_relay.day3.exit.tail",
        task_kind="model_compute",
        owner_service="t-board-relay-service",
        schedule_hint="Day3 13:00-15:00 every 5 minutes, with 14:40-14:55 as tail decision emphasis",
        frequency_hint="day3_afternoon_rolling_5m",
        reads_from=[
            "decision_t_relay.t_board_post_entry_monitor_v1",
            "source.minute_bar_v1",
            "source.limit_price_v1",
        ],
        writes_to=[
            "decision_t_relay.t_board_day3_exit_decision_v1",
            "decision_t_relay.t_board_game_hypothesis_snapshot_v1",
        ],
        is_official_publish=False,
        notes="Day3 afternoon rolling hold/exit research decisions; tail no-limit remains the exit emphasis and is not a trading instruction.",
    ),
    ScheduledTask(
        task_code="t_relay.observation.monitor.snapshot_5m",
        task_kind="observation",
        owner_service="t-board-relay-service",
        schedule_hint="Day1 selection through Day3 close, every 5 minutes during 09:30-11:30 and 13:00-15:00",
        frequency_hint="rolling_5m_three_day_observation_snapshot",
        reads_from=[
            "decision_t_relay.t_board_day1_candidate_v1",
            "decision_t_relay.t_board_day2_watch_snapshot_v1",
            "decision_t_relay.t_board_day2_entry_trigger_v1",
            "decision_t_relay.t_board_post_entry_monitor_v1",
            "decision_t_relay.t_board_day3_exit_decision_v1",
            "decision_t_relay.t_board_outcome_label_v1",
        ],
        writes_to=["decision_t_relay.t_board_observation_monitor_snapshot_v1"],
        is_official_publish=False,
        append_only=True,
        notes="Append-only five-minute snapshots of the current user-readable model-four output for later tuning.",
    ),
    ScheduledTask(
        task_code="t_relay.outcome.build",
        task_kind="outcome",
        owner_service="t-board-relay-service",
        schedule_hint="daily close plus Day3 maturity",
        frequency_hint="daily_maturity",
        reads_from=[
            "decision_t_relay.t_board_post_entry_monitor_v1",
            "decision_t_relay.t_board_day3_exit_decision_v1",
            "source.daily_bar_v1",
        ],
        writes_to=["decision_t_relay.t_board_outcome_label_v1"],
        is_official_publish=False,
        append_only=True,
        notes="Append-only outcome label builder for model-four research samples.",
    ),
)

THREE_MODEL_TASKS: tuple[ScheduledTask, ...] = (
    HOT_CANDIDATES_TASKS + CANDIDATE_MEMORY_TASKS + AMBUSH_WATCHLIST_TASKS + T_BOARD_RELAY_TASKS
)


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
    scheduled_source_tables = scheduled_source_table_names()
    source_read_schedule_violations = [
        task.task_code
        for task in tasks
        if not task.task_code.startswith("source.")
        and any(source.startswith("source.") and source not in scheduled_source_tables for source in task.reads_from)
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
    current_owner_allowlist = {
        "source-data-service",
        "hot-candidates-service",
        "candidate-memory-service",
        "ambush-watchlist-service",
        "t-board-relay-service",
    }
    missing_current_owner_violations = [
        task.task_code
        for task in tasks
        if task.owner_service not in current_owner_allowlist
    ]
    return {
        "contract_kind": "three_model_scheduler_plan_validation_v1",
        "scheduler_version": THREE_MODEL_SCHEDULER_VERSION,
        "task_count": len(tasks),
        "official_publish_tasks": official_publish_tasks,
        "source_publish_violations": source_publish_violations,
        "append_only_violations": append_only_violations,
        "direct_cross_model_write_violations": direct_cross_model_write_violations,
        "provider_read_violations": provider_read_violations,
        "raw_read_violations": raw_read_violations,
        "source_wildcard_violations": source_wildcard_violations,
        "source_read_schedule_violations": source_read_schedule_violations,
        "source_orchestration_violations": source_orchestration_violations,
        "missing_current_owner_violations": missing_current_owner_violations,
        "expected_publishers": expected_publishers,
        "valid": official_publish_tasks == expected_publishers
        and not source_publish_violations
        and not append_only_violations
        and not direct_cross_model_write_violations
        and not provider_read_violations
        and not raw_read_violations
        and not source_wildcard_violations
        and not source_read_schedule_violations
        and not source_orchestration_violations
        and not missing_current_owner_violations,
        "hard_rules": [
            "Source tasks write source/governance facts only and never publish official signals.",
            "Source fetch tasks must be owned by source-data-service and go through /source/fetch/submit.",
            "Scheduler task definitions must not read provider.* or raw_* directly.",
            "Scheduler task definitions must not use source.* wildcards or unscheduled source tables.",
            "Only model-specific release_gate tasks may write official signal facts.",
            "Observation/outcome/evolution tasks are append-only.",
            "Scheduler dispatches owner services; it does not fabricate model outputs.",
            "Locked model one and model two services are not mutated by ambush scheduler tasks.",
            "T-board relay tasks are research/model tasks and may not publish official signals.",
        ],
    }
