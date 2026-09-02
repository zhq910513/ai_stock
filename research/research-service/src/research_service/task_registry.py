from __future__ import annotations

from dataclasses import asdict, dataclass

RESEARCH_PAYLOAD_ASSEMBLER_CONTRACT = "research_model_payload_assembler_v1"
ASSEMBLED_RESEARCH_PAYLOAD_STATUS = "assembled_research_payload"
BLOCKED_DATA_GAP_STATUS = "blocked_data_gap"
PAYLOAD_ASSEMBLY_SOURCE = "research-service:research_model_payload_assembler_v1"


@dataclass(frozen=True)
class TaskRequirement:
    task_code: str
    task_kind: str
    owner_service: str
    schedule_hint: str
    frequency_hint: str
    model_code: str
    model_phase: str | None
    endpoint: str
    source_tables: tuple[str, ...]
    upstream_tables: tuple[str, ...] = ()
    official_publish: bool = False
    append_only: bool = True
    source_preflight_required: bool = False
    notes: str = ""

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["payload_assembly_contract"] = RESEARCH_PAYLOAD_ASSEMBLER_CONTRACT
        payload["required_status"] = ASSEMBLED_RESEARCH_PAYLOAD_STATUS
        return payload


COMMON_DAILY_SOURCE = (
    "source.stock_master_v1",
    "source.trade_status_v1",
    "source.daily_bar_v1",
    "source.adjusted_daily_bar_v1",
)

HOT_CONTEXT = COMMON_DAILY_SOURCE + (
    "source.stock_moneyflow_daily_v1",
    "source.event_news_v1",
)

HOT_SCORE_CONTEXT = HOT_CONTEXT + (
    "source.ths_paid_limit_up_probability_v1",
)

INTRADAY_CONTEXT = (
    "source.realtime_quote_v1",
    "source.minute_bar_v1",
)

T_RELAY_DAY1_SOURCE = (
    "source.stock_master_v1",
    "source.daily_bar_v1",
    "source.limit_price_v1",
    "source.limit_event_v1",
    "source.trade_status_v1",
    "source.realtime_quote_v1",
)

T_RELAY_DAY2_SOURCE = (
    "source.limit_price_v1",
    "source.minute_bar_v1",
    "source.realtime_quote_v1",
    "source.trade_tick_v1",
)

TASK_REQUIREMENTS: tuple[TaskRequirement, ...] = (
    TaskRequirement(
        task_code="hot.score.auction_confirmed",
        task_kind="model_compute",
        owner_service="hot-candidates-service",
        schedule_hint="09:26:00,09:28:00,09:29:30",
        frequency_hint="fixed_time",
        model_code="hot_candidates",
        model_phase="auction_confirmed_score",
        endpoint="/production/scores/compute",
        source_tables=HOT_SCORE_CONTEXT + INTRADAY_CONTEXT,
        notes="Builds hot candidate score input from source facts; no official publish.",
    ),
    TaskRequirement(
        task_code="hot.release_gate.preopen",
        task_kind="release_gate",
        owner_service="hot-candidates-service",
        schedule_hint="09:25:40,09:28:40,09:29:40 deadline 09:30:00",
        frequency_hint="fixed_time",
        model_code="hot_candidates",
        model_phase="preopen_release_gate",
        endpoint="/production/release-gate/evaluate",
        source_tables=HOT_CONTEXT,
        upstream_tables=("decision_hot.hot_score_fact_v1", "decision_hot.hot_evidence_snapshot_v1"),
        official_publish=True,
        source_preflight_required=True,
        notes="Official hot release payload; source preflight and upstream score/evidence facts must pass.",
    ),
    TaskRequirement(
        task_code="hot.buy_point.open_5m",
        task_kind="buy_point",
        owner_service="hot-candidates-service",
        schedule_hint="09:30-09:36 every 30-60 seconds; fixed 09:35,09:45,10:00",
        frequency_hint="30-60s in opening window",
        model_code="hot_candidates",
        model_phase="open_5m_buy_point",
        endpoint="/production/buy-point/evaluate",
        source_tables=COMMON_DAILY_SOURCE + INTRADAY_CONTEXT,
        upstream_tables=(
            "decision_hot.hot_decision_case_v1",
            "decision_hot.hot_score_fact_v1",
        ),
        notes="Evaluates owner buy-point diagnostics from scored hot cases and opening source facts; release audit/signal are not hard prerequisites and no trading instruction is produced.",
    ),
    TaskRequirement(
        task_code="hot.observe.intraday",
        task_kind="observation",
        owner_service="hot-candidates-service",
        schedule_hint="09:30-10:00 every 60s; 10:00-14:30 every 300s; 14:30-15:00 every 60-180s",
        frequency_hint="60s/300s dynamic",
        model_code="hot_candidates",
        model_phase="intraday_observation",
        endpoint="/production/observations/bulk",
        source_tables=COMMON_DAILY_SOURCE + INTRADAY_CONTEXT,
        upstream_tables=("decision_hot.hot_signal_fact_v1",),
        append_only=True,
        notes="Append-only observation payload.",
    ),
    TaskRequirement(
        task_code="hot.outcome.t5_t20",
        task_kind="outcome",
        owner_service="hot-candidates-service",
        schedule_hint="15:10,15:40 plus T+5/T+20 maturity checks",
        frequency_hint="daily_maturity",
        model_code="hot_candidates",
        model_phase="outcome_label",
        endpoint="/production/outcomes/mature",
        source_tables=("source.trade_calendar_v1", "source.daily_bar_v1", "source.adjusted_daily_bar_v1"),
        upstream_tables=("decision_hot.hot_signal_fact_v1",),
        append_only=True,
        notes="Append-only hot outcome payload.",
    ),
    TaskRequirement(
        task_code="hot.evolution.offline",
        task_kind="evolution",
        owner_service="hot-candidates-service",
        schedule_hint="18:30 after matured labels",
        frequency_hint="daily_offline",
        model_code="hot_candidates",
        model_phase="evolution",
        endpoint="/production/evolution/build",
        source_tables=("source.trade_calendar_v1", "source.daily_bar_v1"),
        upstream_tables=("decision_hot.hot_signal_fact_v1",),
        append_only=True,
        notes="Offline shadow/evolution payload; never mutates production weights online.",
    ),
    TaskRequirement(
        task_code="memory.seed.from_hot_signals",
        task_kind="model_compute",
        owner_service="candidate-memory-service",
        schedule_hint="15:45 after hot official signal and observation snapshots",
        frequency_hint="daily_close",
        model_code="candidate_memory",
        model_phase="seed_from_hot_signals",
        endpoint="/production/seed/build",
        source_tables=("source.trade_calendar_v1", "source.daily_bar_v1"),
        upstream_tables=("decision_hot.hot_signal_fact_v1",),
        notes="Builds memory seeds from locked hot facts.",
    ),
    TaskRequirement(
        task_code="memory.pre_signal.scan",
        task_kind="model_compute",
        owner_service="candidate-memory-service",
        schedule_hint="15:55 close confirmed; optional 10:30 research scan",
        frequency_hint="daily_close_plus_optional_intraday_research",
        model_code="candidate_memory",
        model_phase="pre_signal_scan",
        endpoint="/production/pre-signal/detect",
        source_tables=HOT_CONTEXT,
        upstream_tables=("decision_memory.memory_entity_v1",),
        notes="Pre-signal scan; missing memory entity remains blocked.",
    ),
    TaskRequirement(
        task_code="memory.release_gate.close",
        task_kind="release_gate",
        owner_service="candidate-memory-service",
        schedule_hint="16:05 close confirmed",
        frequency_hint="daily_close",
        model_code="candidate_memory",
        model_phase="outcome_label",
        endpoint="/production/release-gate/evaluate",
        source_tables=HOT_CONTEXT,
        upstream_tables=(
            "decision_memory.memory_entity_v1",
            "decision_memory.memory_pre_signal_case_v1",
            "decision_memory.memory_score_fact_v1",
        ),
        official_publish=True,
        source_preflight_required=True,
        notes="Official memory release payload; source preflight and upstream pre-signal/score facts must pass.",
    ),
    TaskRequirement(
        task_code="memory.buy_point.next_session_reference",
        task_kind="buy_point",
        owner_service="candidate-memory-service",
        schedule_hint="next trading day 09:30-10:00 reference evaluation",
        frequency_hint="next_session_open_window",
        model_code="candidate_memory",
        model_phase="buy_point_reference",
        endpoint="/production/buy-point/evaluate",
        source_tables=COMMON_DAILY_SOURCE + INTRADAY_CONTEXT,
        upstream_tables=("decision_memory.memory_signal_fact_v1",),
        notes="Memory reference price payload; no trading advice.",
    ),
    TaskRequirement(
        task_code="memory.observe.outcome.evolution",
        task_kind="outcome",
        owner_service="candidate-memory-service",
        schedule_hint="daily 15:50 plus T+5/T+20/T+40 maturity checks",
        frequency_hint="daily_maturity",
        model_code="candidate_memory",
        model_phase="outcome_evolution",
        endpoint="/production/outcomes/mature",
        source_tables=("source.trade_calendar_v1", "source.daily_bar_v1", "source.adjusted_daily_bar_v1"),
        upstream_tables=("decision_memory.memory_signal_fact_v1",),
        append_only=True,
        notes="Append-only memory observation/outcome/evolution payload.",
    ),
    TaskRequirement(
        task_code="ambush.source_capability.audit",
        task_kind="source_collect",
        owner_service="ambush-watchlist-service",
        schedule_hint="weekly Sunday 20:00 and before new provider activation",
        frequency_hint="weekly_or_on_demand",
        model_code="ambush_watchlist",
        model_phase="source_capability_audit",
        endpoint="/ambush/source-capability-audit",
        source_tables=COMMON_DAILY_SOURCE,
        notes="Audits source capability through already-built source facts.",
    ),
    TaskRequirement(
        task_code="ambush.pattern_library.mine",
        task_kind="model_compute",
        owner_service="ambush-watchlist-service",
        schedule_hint="daily 18:10 incremental; monthly full rebuild/shadow evaluation",
        frequency_hint="daily_incremental_monthly_rebuild",
        model_code="ambush_watchlist",
        model_phase="pattern_library_mine",
        endpoint="/ambush/historical-valley-sample-label",
        source_tables=COMMON_DAILY_SOURCE,
        upstream_tables=("decision_ambush.ambush_outcome_label_v1", "decision_ambush.ambush_failure_attribution_v1"),
        notes="Offline low-valley pattern library payload.",
    ),
    TaskRequirement(
        task_code="ambush.phase2.valley_turn.close",
        task_kind="model_compute",
        owner_service="ambush-watchlist-service",
        schedule_hint="15:20 after close-confirmed daily bars; optional 10:30 research scan",
        frequency_hint="daily_close_plus_research_intraday",
        model_code="ambush_watchlist",
        model_phase="phase2_valley_turn",
        endpoint="/ambush/phase2/run",
        source_tables=COMMON_DAILY_SOURCE + ("source.stock_moneyflow_daily_v1",),
        notes="Phase2 valley/turn payload.",
    ),
    TaskRequirement(
        task_code="ambush.phase3.release_gate.close",
        task_kind="release_gate",
        owner_service="ambush-watchlist-service",
        schedule_hint="15:35 close confirmed after Phase 2 and P1 context refresh",
        frequency_hint="daily_close",
        model_code="ambush_watchlist",
        model_phase="release_gate",
        endpoint="/ambush/phase3/run",
        source_tables=HOT_CONTEXT,
        upstream_tables=(
            "decision_ambush.valley_watch_pool_v1",
            "decision_ambush.effective_turn_anchor_v1",
            "decision_ambush.effective_turn_pool_v1",
        ),
        official_publish=True,
        source_preflight_required=True,
        notes="Official ambush release payload; source preflight and upstream effective-turn facts must pass.",
    ),
    TaskRequirement(
        task_code="ambush.buy_point.reference",
        task_kind="buy_point",
        owner_service="ambush-watchlist-service",
        schedule_hint="15:35 close reference; next-session open-window integration later",
        frequency_hint="daily_close_reference",
        model_code="ambush_watchlist",
        model_phase="buy_point_reference",
        endpoint="/ambush/phase3/run",
        source_tables=COMMON_DAILY_SOURCE,
        upstream_tables=("decision_ambush.ambush_signal_fact_v1",),
        notes="Ambush benchmark price payload.",
    ),
    TaskRequirement(
        task_code="ambush.observe.outcome.evolution",
        task_kind="outcome",
        owner_service="ambush-watchlist-service",
        schedule_hint="daily 15:55 plus T+5/T+10/T+20 maturity checks",
        frequency_hint="daily_maturity",
        model_code="ambush_watchlist",
        model_phase="outcome_evolution",
        endpoint="/ambush/phase4/outcome",
        source_tables=("source.trade_calendar_v1", "source.daily_bar_v1", "source.adjusted_daily_bar_v1"),
        upstream_tables=("decision_ambush.ambush_signal_fact_v1",),
        append_only=True,
        notes="Append-only ambush observation/outcome/evolution payload.",
    ),
    TaskRequirement(
        task_code="t_relay.day1.scan.close",
        task_kind="model_compute",
        owner_service="t-board-relay-service",
        schedule_hint="15:05-15:30 close confirmed",
        frequency_hint="daily_close",
        model_code="t_board_relay",
        model_phase="day1_scan",
        endpoint="/t-board-relay/day1/scan",
        source_tables=T_RELAY_DAY1_SOURCE,
        source_preflight_required=True,
        notes="Day1 T-board scan payload for research-only relay model.",
    ),
    TaskRequirement(
        task_code="t_relay.day2.watch.rolling_5m",
        task_kind="model_compute",
        owner_service="t-board-relay-service",
        schedule_hint="09:30-10:30 every 5 minutes from next-session open",
        frequency_hint="rolling_5m_open_window",
        model_code="t_board_relay",
        model_phase="day2_watch",
        endpoint="/t-board-relay/day2/watch",
        source_tables=T_RELAY_DAY2_SOURCE,
        upstream_tables=("decision_t_relay.t_board_day1_candidate_v1",),
        notes="Day2 rolling five-minute near-limit watch payload.",
    ),
    TaskRequirement(
        task_code="t_relay.day2.trigger.rolling_5m",
        task_kind="model_compute",
        owner_service="t-board-relay-service",
        schedule_hint="09:30-10:30 every 5 minutes after Day1 qualification",
        frequency_hint="rolling_5m_open_window",
        model_code="t_board_relay",
        model_phase="day2_trigger",
        endpoint="/t-board-relay/day2/trigger-check",
        source_tables=T_RELAY_DAY2_SOURCE,
        upstream_tables=(
            "decision_t_relay.t_board_day1_candidate_v1",
            "decision_t_relay.t_board_day2_watch_snapshot_v1",
        ),
        notes=(
            "Day2 rolling five-minute trigger payload; near-limit proximity is the opportunity gate. "
            "This non-official research trigger uses required source/upstream facts instead of release preflight."
        ),
    ),
    TaskRequirement(
        task_code="t_relay.day2.post_entry.monitor",
        task_kind="observation",
        owner_service="t-board-relay-service",
        schedule_hint="after theoretical entry until close 15:00",
        frequency_hint="intraday_after_trigger",
        model_code="t_board_relay",
        model_phase="post_entry_monitor",
        endpoint="/t-board-relay/post-entry/monitor",
        source_tables=("source.minute_bar_v1", "source.limit_price_v1", "source.limit_event_v1"),
        upstream_tables=("decision_t_relay.t_board_day2_entry_trigger_v1",),
        append_only=True,
        notes="Post-entry seal monitor payload.",
    ),
    TaskRequirement(
        task_code="t_relay.observation.monitor.snapshot_5m",
        task_kind="observation",
        owner_service="t-board-relay-service",
        schedule_hint="Day1 through Day3 open sessions every 5 minutes",
        frequency_hint="rolling_5m_observation_snapshot",
        model_code="t_board_relay",
        model_phase="observation_monitor_snapshot",
        endpoint="/t-board-relay/observation-monitor/snapshot",
        source_tables=(),
        upstream_tables=(),
        append_only=True,
        notes=(
            "Append-only observation-board projection snapshot. "
            "The owner service reads its repository projection and writes decision_t_relay snapshots."
        ),
    ),
    TaskRequirement(
        task_code="t_relay.live_result.compute_30m",
        task_kind="observation",
        owner_service="t-board-relay-service",
        schedule_hint="Day1 through Day3 open sessions every 30 minutes",
        frequency_hint="rolling_30m_model_result",
        model_code="t_board_relay",
        model_phase="observation_monitor_result_30m",
        endpoint="/t-board-relay/observation-monitor/snapshot",
        source_tables=(),
        upstream_tables=(),
        append_only=True,
        notes=(
            "Append-only observation-board model result. The owner service reads its repository "
            "projection and writes result_kind=model_result_30m snapshots."
        ),
    ),
    TaskRequirement(
        task_code="t_relay.day3.exit.open",
        task_kind="model_compute",
        owner_service="t-board-relay-service",
        schedule_hint="Day3 09:25-09:35",
        frequency_hint="next_session_open_window",
        model_code="t_board_relay",
        model_phase="day3_exit_open",
        endpoint="/t-board-relay/day3/exit-check",
        source_tables=("source.minute_bar_v1", "source.limit_price_v1"),
        upstream_tables=("decision_t_relay.t_board_post_entry_monitor_v1",),
        notes="Day3 open decision payload.",
    ),
    TaskRequirement(
        task_code="t_relay.day3.exit.tail",
        task_kind="model_compute",
        owner_service="t-board-relay-service",
        schedule_hint="Day3 14:40-14:55",
        frequency_hint="next_session_tail_window",
        model_code="t_board_relay",
        model_phase="day3_exit_tail",
        endpoint="/t-board-relay/day3/exit-check",
        source_tables=("source.minute_bar_v1", "source.limit_price_v1"),
        upstream_tables=("decision_t_relay.t_board_post_entry_monitor_v1",),
        notes="Day3 tail decision payload.",
    ),
    TaskRequirement(
        task_code="t_relay.outcome.build",
        task_kind="outcome",
        owner_service="t-board-relay-service",
        schedule_hint="daily close plus Day3 maturity",
        frequency_hint="daily_maturity",
        model_code="t_board_relay",
        model_phase="outcome_build",
        endpoint="/t-board-relay/outcomes/build",
        source_tables=("source.daily_bar_v1",),
        upstream_tables=("decision_t_relay.t_board_day3_exit_decision_v1",),
        append_only=True,
        notes="Append-only T-board relay outcome payload.",
    ),
)

TASK_BY_CODE = {task.task_code: task for task in TASK_REQUIREMENTS}


def list_requirements() -> list[dict]:
    return [task.to_dict() for task in TASK_REQUIREMENTS]


def get_requirement(task_code: str) -> TaskRequirement | None:
    return TASK_BY_CODE.get(task_code)
