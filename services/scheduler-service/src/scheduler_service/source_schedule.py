from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Literal
from zoneinfo import ZoneInfo

SOURCE_SCHEDULE_REGISTRY_VERSION = "source_fetch_schedule_registry_v1"
SOURCE_TIME_WHEEL_VERSION = "scheduler_source_time_wheel_v1"
DEFAULT_MARKET_TZ = "Asia/Shanghai"
T_RELAY_LIMIT_EVENT_STAGE_CANDIDATE_SOURCE = "t_relay_limit_event_t_board"
T_RELAY_DAY1_QUALIFIED_STAGE_CANDIDATE_SOURCE = "t_relay_day1_qualified_candidates"
EXPLICIT_MODEL_STAGE_CANDIDATE_SOURCE = "explicit_model_stage_candidates"
SOURCE_FETCH_ENDPOINTS = ("POST /source/fetch/plan", "POST /source/fetch/submit")
THS_PAID_FETCH_ENDPOINTS = ("POST /source/ths/paid-probability/fetch-current-batch",)
THS_PAID_DEADLINE_ENDPOINTS = ("POST /source/ths/paid-probability/deadline-check",)
ALLOWED_SOURCE_ENDPOINT_CHAINS = {SOURCE_FETCH_ENDPOINTS, THS_PAID_FETCH_ENDPOINTS, THS_PAID_DEADLINE_ENDPOINTS}
RESEARCH_PAYLOAD_REQUIRED_SOURCE_TABLES = (
    "source.adjusted_daily_bar_v1",
    "source.daily_bar_v1",
    "source.event_news_v1",
    "source.limit_event_v1",
    "source.limit_price_v1",
    "source.minute_bar_v1",
    "source.realtime_quote_v1",
    "source.stock_master_v1",
    "source.stock_moneyflow_daily_v1",
    "source.ths_paid_limit_up_probability_v1",
    "source.trade_calendar_v1",
    "source.trade_status_v1",
    "source.trade_tick_v1",
)


@dataclass(frozen=True)
class SourceFetchScheduleSpec:
    schedule_code: str
    schedule_group: str
    frequency: str
    source_table_name: str
    canonical_fields: tuple[str, ...]
    trigger_type: str
    priority: str
    times_local: tuple[time, ...]
    default_symbols: tuple[str, ...] = ()
    symbol_scope: Literal["none", "full_a_share", "configured_symbols", "stage_candidates"] = "configured_symbols"
    date_mode: str = "trade_date"
    model_code: str | None = None
    model_phase: str | None = None
    stage_candidate_source: str | None = None
    endpoint_chain: tuple[str, ...] = SOURCE_FETCH_ENDPOINTS
    owner_endpoint_path: str = "/source/fetch/submit"
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["times_local"] = [item.isoformat() for item in self.times_local]
        payload["canonical_fields"] = list(self.canonical_fields)
        payload["default_symbols"] = list(self.default_symbols)
        payload["endpoint_chain"] = list(self.endpoint_chain)
        return payload


@dataclass(frozen=True)
class SourceFetchInstance:
    schedule_code: str
    schedule_group: str
    frequency: str
    source_table_name: str
    scheduled_at: datetime
    scheduled_at_local: datetime
    run_slot: str
    trading_day: str
    biz_key: str
    idempotency_key: str
    request_body: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["scheduled_at"] = self.scheduled_at.isoformat()
        payload["scheduled_at_local"] = self.scheduled_at_local.isoformat()
        return payload


def _minute_range(start: time, end: time, step_seconds: int) -> tuple[time, ...]:
    current = datetime.combine(date(2000, 1, 1), start)
    stop = datetime.combine(date(2000, 1, 1), end)
    values: list[time] = []
    while current <= stop:
        values.append(current.time().replace(microsecond=0))
        current += timedelta(seconds=step_seconds)
    return tuple(values)


def _session_minute_ranges(
    sessions: tuple[tuple[time, time], ...],
    step_seconds: int,
) -> tuple[time, ...]:
    return tuple(item for start, end in sessions for item in _minute_range(start, end, step_seconds))


T_RELAY_STAGE_MONITOR_TIMES_LOCAL = _session_minute_ranges(
    ((time(9, 30), time(11, 30)), (time(13, 0), time(15, 0))),
    300,
)


SOURCE_FETCH_SCHEDULES: tuple[SourceFetchScheduleSpec, ...] = (
    SourceFetchScheduleSpec(
        schedule_code="source.init.trade_calendar",
        schedule_group="one_time_initial",
        frequency="one_time_before_first_launch",
        source_table_name="source.trade_calendar_v1",
        canonical_fields=("calendar_date", "is_trading_day", "pretrade_date"),
        trigger_type="scheduled_periodic",
        priority="P1_normal_ingest",
        times_local=(time(8, 45),),
        symbol_scope="none",
        date_mode="forward_24m_range",
        description="Initial and quarterly refresh for the shared trading timeline.",
    ),
    SourceFetchScheduleSpec(
        schedule_code="source.init.stock_master",
        schedule_group="one_time_initial",
        frequency="one_time_before_first_launch",
        source_table_name="source.stock_master_v1",
        canonical_fields=("stock_name", "ipo_date", "delist_date", "list_status", "exchange", "board"),
        trigger_type="scheduled_periodic",
        priority="P1_normal_ingest",
        times_local=(time(8, 50),),
        symbol_scope="full_a_share",
        date_mode="as_of_range",
        description="Initial and quarterly stock identity refresh.",
    ),
    SourceFetchScheduleSpec(
        schedule_code="source.daily.preopen_universe",
        schedule_group="daily_preopen",
        frequency="daily 09:05",
        source_table_name="source.stock_universe_daily_v1",
        canonical_fields=("is_tradable", "trade_status", "is_st", "is_suspended", "is_delisting_risk"),
        trigger_type="scheduled_periodic",
        priority="P1_normal_ingest",
        times_local=(time(9, 5),),
        symbol_scope="full_a_share",
        description="Daily tradable universe and hard-block flags before release windows.",
    ),
    SourceFetchScheduleSpec(
        schedule_code="source.daily.trade_status",
        schedule_group="daily_preopen",
        frequency="daily 09:10",
        source_table_name="source.trade_status_v1",
        canonical_fields=("trade_status", "is_tradable", "is_st", "is_suspended"),
        trigger_type="scheduled_periodic",
        priority="P1_normal_ingest",
        times_local=(time(9, 10),),
        symbol_scope="full_a_share",
        description="Daily trade status refresh shared by all release gates.",
    ),
    SourceFetchScheduleSpec(
        schedule_code="source.daily.limit_price_preopen",
        schedule_group="daily_preopen",
        frequency="daily 09:12",
        source_table_name="source.limit_price_v1",
        canonical_fields=("pre_close_price", "up_limit_price", "down_limit_price", "limit_rule"),
        trigger_type="model_release_preflight",
        priority="P0_urgent_release",
        times_local=(time(9, 12),),
        symbol_scope="full_a_share",
        model_code="shared_release_gate",
        model_phase="preopen_limit_price",
        description="Preopen price-limit facts required by official release gates and T-board relay.",
    ),
    SourceFetchScheduleSpec(
        schedule_code="source.window.limit_event_t_relay",
        schedule_group="t_relay_day1_window",
        frequency="10:40,14:55,15:02,15:10",
        source_table_name="source.limit_event_v1",
        canonical_fields=("limit_event_type", "is_one_word_board", "is_break_limit", "close_on_limit_flag", "limit_open_count"),
        trigger_type="model_release_preflight",
        priority="P0_urgent_release",
        times_local=(time(10, 40), time(14, 55), time(15, 2), time(15, 10)),
        symbol_scope="full_a_share",
        model_code="t_board_relay",
        model_phase="limit_event_window",
        description="Limit-up event facts for model-four Day1 scan and post-entry monitoring windows.",
    ),
    SourceFetchScheduleSpec(
        schedule_code="source.window.t_relay_candidate_trade_status",
        schedule_group="t_relay_day1_candidate_facts",
        frequency="15:12,15:35,15:45 after THS limit-up pool T-board candidates",
        source_table_name="source.trade_status_v1",
        canonical_fields=("trade_status", "is_tradable", "is_st", "is_suspended"),
        trigger_type="model_release_preflight",
        priority="P0_urgent_release",
        times_local=(time(15, 12), time(15, 35), time(15, 45)),
        symbol_scope="stage_candidates",
        model_code="t_board_relay",
        model_phase="day1_candidate_facts",
        stage_candidate_source=T_RELAY_LIMIT_EVENT_STAGE_CANDIDATE_SOURCE,
        description="Candidate-level trade-status repair for T-board symbols found in the THS limit-up pool.",
    ),
    SourceFetchScheduleSpec(
        schedule_code="source.window.t_relay_candidate_daily_bar",
        schedule_group="t_relay_day1_candidate_facts",
        frequency="15:12,15:35,15:45 after THS limit-up pool T-board candidates",
        source_table_name="source.daily_bar_v1",
        canonical_fields=("open_price", "high_price", "low_price", "close_price", "volume", "amount", "pct_chg"),
        trigger_type="model_release_preflight",
        priority="P0_urgent_release",
        times_local=(time(15, 12), time(15, 35), time(15, 45)),
        symbol_scope="stage_candidates",
        model_code="t_board_relay",
        model_phase="day1_candidate_facts",
        stage_candidate_source=T_RELAY_LIMIT_EVENT_STAGE_CANDIDATE_SOURCE,
        description="Candidate-level daily-bar repair for T-board symbols found in the THS limit-up pool.",
    ),
    SourceFetchScheduleSpec(
        schedule_code="source.window.t_relay_candidate_limit_price",
        schedule_group="t_relay_day1_candidate_facts",
        frequency="15:12,15:35,15:45 after THS limit-up pool T-board candidates",
        source_table_name="source.limit_price_v1",
        canonical_fields=("pre_close_price", "up_limit_price", "down_limit_price", "limit_rule"),
        trigger_type="model_release_preflight",
        priority="P0_urgent_release",
        times_local=(time(15, 12), time(15, 35), time(15, 45)),
        symbol_scope="stage_candidates",
        model_code="t_board_relay",
        model_phase="day1_candidate_facts",
        stage_candidate_source=T_RELAY_LIMIT_EVENT_STAGE_CANDIDATE_SOURCE,
        description="Candidate-level price-limit repair for T-board symbols found in the THS limit-up pool.",
    ),
    SourceFetchScheduleSpec(
        schedule_code="source.window.t_relay_candidate_float_market_cap",
        schedule_group="t_relay_day1_candidate_facts",
        frequency="15:12,15:20,15:30 after THS limit-up pool T-board candidates",
        source_table_name="source.realtime_quote_v1",
        canonical_fields=("latest_price", "float_market_cap", "event_time"),
        trigger_type="model_release_preflight",
        priority="P0_urgent_release",
        times_local=(time(15, 12), time(15, 20), time(15, 30)),
        symbol_scope="stage_candidates",
        model_code="t_board_relay",
        model_phase="day1_candidate_facts",
        stage_candidate_source=T_RELAY_LIMIT_EVENT_STAGE_CANDIDATE_SOURCE,
        description="Candidate-level float-market-cap refresh for T-board Day1 qualification.",
    ),
    SourceFetchScheduleSpec(
        schedule_code="source.daily.ths_paid_probability_fetch",
        schedule_group="daily_close_paid_probability",
        frequency="daily 15:20,16:05,18:00,20:30 until next trading day 09:00",
        source_table_name="source.ths_paid_limit_up_probability_v1",
        canonical_fields=("paid_limit_up_probability",),
        trigger_type="scheduled_periodic",
        priority="P0_urgent_release",
        times_local=(time(15, 20), time(16, 5), time(18, 0), time(20, 30)),
        symbol_scope="none",
        model_code="hot_candidates",
        model_phase="paid_probability_ingest",
        endpoint_chain=THS_PAID_FETCH_ENDPOINTS,
        owner_endpoint_path="/source/ths/paid-probability/fetch-current-batch",
        description="Credentialed THS paid next-day probability fetch after limit-up candidates are visible; source service probes cookies before queuing provider jobs.",
    ),
    SourceFetchScheduleSpec(
        schedule_code="source.daily.ths_paid_probability_deadline_guard",
        schedule_group="daily_preopen_paid_probability_guard",
        frequency="daily 09:01 checks unresolved candidate batches after their next trading day 09:00 deadline",
        source_table_name="source.ths_paid_limit_up_probability_v1",
        canonical_fields=("paid_limit_up_probability",),
        trigger_type="scheduled_periodic",
        priority="P0_urgent_release",
        times_local=(time(9, 1),),
        symbol_scope="none",
        date_mode="auto_unresolved_batch",
        model_code="hot_candidates",
        model_phase="paid_probability_deadline_guard",
        endpoint_chain=THS_PAID_DEADLINE_ENDPOINTS,
        owner_endpoint_path="/source/ths/paid-probability/deadline-check",
        description="Deadline guard: only after next trading day 09:00 Asia/Shanghai may unresolved paid-probability candidates be abandoned.",
    ),
    SourceFetchScheduleSpec(
        schedule_code="source.daily.close_bars",
        schedule_group="daily_close",
        frequency="daily 15:35",
        source_table_name="source.daily_bar_v1",
        canonical_fields=("open_price", "high_price", "low_price", "close_price", "volume", "amount", "pct_chg"),
        trigger_type="scheduled_periodic",
        priority="P1_normal_ingest",
        times_local=(time(15, 35),),
        symbol_scope="full_a_share",
        description="Unadjusted daily bars after close.",
    ),
    SourceFetchScheduleSpec(
        schedule_code="source.daily.adjusted_bars",
        schedule_group="daily_close",
        frequency="daily 15:45",
        source_table_name="source.adjusted_daily_bar_v1",
        canonical_fields=("adjusted_open", "adjusted_high", "adjusted_low", "adjusted_close", "adjust_factor"),
        trigger_type="scheduled_periodic",
        priority="P1_normal_ingest",
        times_local=(time(15, 45),),
        symbol_scope="full_a_share",
        description="Adjusted daily bars and factors after close.",
    ),
    SourceFetchScheduleSpec(
        schedule_code="source.daily.moneyflow",
        schedule_group="daily_research_context",
        frequency="daily 16:15",
        source_table_name="source.stock_moneyflow_daily_v1",
        canonical_fields=("main_net_inflow", "provider_definition"),
        trigger_type="scheduled_periodic",
        priority="research",
        times_local=(time(16, 15),),
        symbol_scope="full_a_share",
        description="Daily moneyflow context. Missing values remain P1 degraded.",
    ),
    SourceFetchScheduleSpec(
        schedule_code="source.daily.event_news",
        schedule_group="daily_research_context",
        frequency="daily 16:30",
        source_table_name="source.event_news_v1",
        canonical_fields=("title", "published_at", "available_at", "event_type", "url"),
        trigger_type="scheduled_periodic",
        priority="research",
        times_local=(time(16, 30),),
        symbol_scope="none",
        description="Research-only event and news context.",
    ),
    SourceFetchScheduleSpec(
        schedule_code="source.minute.auction_snapshot",
        schedule_group="minute_auction",
        frequency="09:15-09:25 every 30s",
        source_table_name="source.auction_snapshot_v1",
        canonical_fields=("virtual_open_price", "matched_volume", "matched_amount", "event_time"),
        trigger_type="model_release_preflight",
        priority="P0_urgent_release",
        times_local=_minute_range(time(9, 15), time(9, 25), 30),
        symbol_scope="configured_symbols",
        model_code="hot_candidates",
        model_phase="preopen_release_gate",
        description="Auction facts for the hot candidate preopen release gate.",
    ),
    SourceFetchScheduleSpec(
        schedule_code="source.minute.realtime_quote",
        schedule_group="minute_intraday",
        frequency="09:30-15:00 every 60s",
        source_table_name="source.realtime_quote_v1",
        canonical_fields=("latest_price", "float_market_cap", "event_time"),
        trigger_type="scheduled_periodic",
        priority="P1_normal_ingest",
        times_local=_minute_range(time(9, 30), time(15, 0), 60),
        symbol_scope="configured_symbols",
        description="Intraday quote refresh for release gates and model-four watch windows.",
    ),
    SourceFetchScheduleSpec(
        schedule_code="source.minute.minute_bar",
        schedule_group="minute_intraday",
        frequency="09:30-15:00 every 60s",
        source_table_name="source.minute_bar_v1",
        canonical_fields=("open_price", "high_price", "low_price", "close_price", "volume", "bar_time"),
        trigger_type="scheduled_periodic",
        priority="P1_normal_ingest",
        times_local=_minute_range(time(9, 30), time(15, 0), 60),
        symbol_scope="configured_symbols",
        description="Intraday minute bars for buy-point, watch and outcome windows.",
    ),
    SourceFetchScheduleSpec(
        schedule_code="source.window.t_relay_day2_limit_price",
        schedule_group="t_relay_day2_window",
        frequency="09:25,09:30 before rolling Day2/Day3 watch",
        source_table_name="source.limit_price_v1",
        canonical_fields=("pre_close_price", "up_limit_price", "down_limit_price", "limit_rule"),
        trigger_type="model_release_preflight",
        priority="P0_urgent_release",
        times_local=(time(9, 25), time(9, 30)),
        symbol_scope="stage_candidates",
        model_code="t_board_relay",
        model_phase="day2_day3_monitor",
        stage_candidate_source=T_RELAY_DAY1_QUALIFIED_STAGE_CANDIDATE_SOURCE,
        description="Model-four price-limit facts for Day1-qualified Day2 and Day3 rolling watch candidates.",
    ),
    SourceFetchScheduleSpec(
        schedule_code="source.window.t_relay_day2_realtime_quote",
        schedule_group="t_relay_day2_window",
        frequency="09:30-11:30 and 13:00-15:00 every 5m through Day3 monitoring",
        source_table_name="source.realtime_quote_v1",
        canonical_fields=("latest_price", "float_market_cap", "event_time"),
        trigger_type="model_release_preflight",
        priority="P0_urgent_release",
        times_local=T_RELAY_STAGE_MONITOR_TIMES_LOCAL,
        symbol_scope="stage_candidates",
        model_code="t_board_relay",
        model_phase="day2_day3_monitor",
        stage_candidate_source=T_RELAY_DAY1_QUALIFIED_STAGE_CANDIDATE_SOURCE,
        description="Model-four stage-candidate quotes for Day2 trigger, post-entry maintenance, and Day3 hold/exit monitoring.",
    ),
    SourceFetchScheduleSpec(
        schedule_code="source.window.t_relay_day2_minute_bar",
        schedule_group="t_relay_day2_window",
        frequency="09:30-11:30 and 13:00-15:00 every 5m through Day3 monitoring",
        source_table_name="source.minute_bar_v1",
        canonical_fields=("open_price", "high_price", "low_price", "close_price", "volume", "bar_time"),
        trigger_type="model_release_preflight",
        priority="P0_urgent_release",
        times_local=T_RELAY_STAGE_MONITOR_TIMES_LOCAL,
        symbol_scope="stage_candidates",
        model_code="t_board_relay",
        model_phase="day2_day3_monitor",
        stage_candidate_source=T_RELAY_DAY1_QUALIFIED_STAGE_CANDIDATE_SOURCE,
        description="Model-four five-minute bars for Day2 trigger, post-entry maintenance, and Day3 hold/exit monitoring.",
    ),
    SourceFetchScheduleSpec(
        schedule_code="source.window.t_relay_trade_tick",
        schedule_group="t_relay_day2_window",
        frequency="09:30-11:30 and 13:00-15:00 every 5m through Day3 monitoring",
        source_table_name="source.trade_tick_v1",
        canonical_fields=("price", "side_code", "amount", "tick_time"),
        trigger_type="model_release_preflight",
        priority="P0_urgent_release",
        times_local=T_RELAY_STAGE_MONITOR_TIMES_LOCAL,
        symbol_scope="stage_candidates",
        model_code="t_board_relay",
        model_phase="day2_day3_monitor",
        stage_candidate_source=T_RELAY_DAY1_QUALIFIED_STAGE_CANDIDATE_SOURCE,
        description="Model-four public tick-like details for Day2 ASK/BID confirmation and later risk review; missing facts stay gap-coded.",
    ),
)


def source_schedule_registry() -> list[dict[str, Any]]:
    return [item.to_dict() for item in SOURCE_FETCH_SCHEDULES]


def scheduled_source_table_names() -> set[str]:
    return {item.source_table_name for item in SOURCE_FETCH_SCHEDULES}


def validate_source_schedule_registry() -> dict[str, Any]:
    seen: set[str] = set()
    duplicate_codes: list[str] = []
    missing_endpoint_chain: list[str] = []
    provider_or_raw_violations: list[str] = []
    missing_required_fields: list[str] = []
    invalid_trigger_priority_pairs: list[str] = []
    invalid_symbol_scope_pairs: list[str] = []
    for spec in SOURCE_FETCH_SCHEDULES:
        if spec.schedule_code in seen:
            duplicate_codes.append(spec.schedule_code)
        seen.add(spec.schedule_code)
        if spec.endpoint_chain not in ALLOWED_SOURCE_ENDPOINT_CHAINS:
            missing_endpoint_chain.append(spec.schedule_code)
        if spec.source_table_name.startswith("raw_") or spec.source_table_name.startswith("provider."):
            provider_or_raw_violations.append(spec.schedule_code)
        if not spec.times_local or not spec.source_table_name or not spec.canonical_fields:
            missing_required_fields.append(spec.schedule_code)
        if spec.trigger_type == "model_release_preflight" and spec.priority != "P0_urgent_release":
            invalid_trigger_priority_pairs.append(spec.schedule_code)
        if spec.symbol_scope in {"none", "full_a_share"} and spec.default_symbols:
            invalid_symbol_scope_pairs.append(spec.schedule_code)
    groups = sorted({item.schedule_group for item in SOURCE_FETCH_SCHEDULES})
    missing_research_payload_tables = sorted(set(RESEARCH_PAYLOAD_REQUIRED_SOURCE_TABLES) - scheduled_source_table_names())
    return {
        "contract_kind": "source_schedule_registry_validation_v1",
        "registry_version": SOURCE_SCHEDULE_REGISTRY_VERSION,
        "schedule_count": len(SOURCE_FETCH_SCHEDULES),
        "groups": groups,
        "duplicate_codes": duplicate_codes,
        "missing_endpoint_chain": missing_endpoint_chain,
        "provider_or_raw_violations": provider_or_raw_violations,
        "missing_required_fields": missing_required_fields,
        "invalid_trigger_priority_pairs": invalid_trigger_priority_pairs,
        "invalid_symbol_scope_pairs": invalid_symbol_scope_pairs,
        "research_payload_required_source_tables": list(RESEARCH_PAYLOAD_REQUIRED_SOURCE_TABLES),
        "missing_research_payload_tables": missing_research_payload_tables,
        "valid": not duplicate_codes
        and not missing_endpoint_chain
        and not provider_or_raw_violations
        and not missing_required_fields
        and not invalid_trigger_priority_pairs
        and not invalid_symbol_scope_pairs
        and not missing_research_payload_tables,
        "hard_rules": [
            "Recurring source fetch schedules submit only to source-data-service fetch orchestration.",
            "Scheduler schedules never call provider APIs and never read raw_*.",
            "Temporary source requests are not added to the recurring registry.",
            "Every research-service payload required source table must have a non-temporary scheduler entry.",
            "Full-A daily schedules use universe_scope=full_a_share and never inherit configured sample symbols.",
            "Minute/tick schedules use configured_symbols or stage_candidates only; they are not whole-market recurring fetches.",
        ],
    }


def materialize_source_fetch_schedule(
    *,
    trading_day: date,
    symbols: list[str] | None = None,
    stage_candidate_symbols_by_source: dict[str, list[str]] | None = None,
    include_one_time: bool = False,
    timezone_name: str = DEFAULT_MARKET_TZ,
) -> list[SourceFetchInstance]:
    tz = ZoneInfo(timezone_name)
    default_symbols = list(symbols or [])
    instances: list[SourceFetchInstance] = []
    for spec in SOURCE_FETCH_SCHEDULES:
        if spec.schedule_group == "one_time_initial" and not include_one_time:
            continue
        request_symbols = _symbols_for_spec(spec, default_symbols, stage_candidate_symbols_by_source or {})
        if spec.symbol_scope == "stage_candidates" and not request_symbols:
            continue
        for local_time in spec.times_local:
            local_dt = datetime.combine(trading_day, local_time).replace(tzinfo=tz)
            scheduled_at = local_dt.astimezone(timezone.utc)
            run_slot = local_time.strftime("%H%M%S")
            biz_key = f"{spec.schedule_code}:{trading_day.isoformat()}:{run_slot}"
            idempotency_key = f"scheduler:{biz_key}"
            request_body = _request_body_for(spec, trading_day=trading_day, symbols=request_symbols, idempotency_key=idempotency_key)
            instances.append(
                SourceFetchInstance(
                    schedule_code=spec.schedule_code,
                    schedule_group=spec.schedule_group,
                    frequency=spec.frequency,
                    source_table_name=spec.source_table_name,
                    scheduled_at=scheduled_at,
                    scheduled_at_local=local_dt,
                    run_slot=run_slot,
                    trading_day=trading_day.isoformat(),
                    biz_key=biz_key,
                    idempotency_key=idempotency_key,
                    request_body=request_body,
                )
            )
    instances.sort(key=lambda item: item.scheduled_at)
    return instances


def _normalize_symbols(symbols: list[str] | tuple[str, ...]) -> list[str]:
    return sorted({str(item).strip() for item in symbols if str(item).strip()})


def _symbols_for_spec(
    spec: SourceFetchScheduleSpec,
    default_symbols: list[str],
    stage_candidate_symbols_by_source: dict[str, list[str]],
) -> list[str]:
    if spec.symbol_scope in {"none", "full_a_share"}:
        return []
    if spec.symbol_scope == "stage_candidates":
        source_key = spec.stage_candidate_source or EXPLICIT_MODEL_STAGE_CANDIDATE_SOURCE
        symbols = _normalize_symbols(stage_candidate_symbols_by_source.get(source_key, []))
        if symbols or source_key == EXPLICIT_MODEL_STAGE_CANDIDATE_SOURCE:
            return symbols
        return _normalize_symbols(stage_candidate_symbols_by_source.get(EXPLICIT_MODEL_STAGE_CANDIDATE_SOURCE, []))
    return default_symbols or list(spec.default_symbols)


def due_source_fetch_instances(
    *,
    now: datetime,
    symbols: list[str] | None = None,
    stage_candidate_symbols_by_source: dict[str, list[str]] | None = None,
    include_one_time: bool = False,
    timezone_name: str = DEFAULT_MARKET_TZ,
    lateness_seconds: int = 90,
) -> list[SourceFetchInstance]:
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    tz = ZoneInfo(timezone_name)
    local_now = now.astimezone(tz)
    trading_day = local_now.date()
    lower_bound = now - timedelta(seconds=max(lateness_seconds, 0))
    return [
        item
        for item in materialize_source_fetch_schedule(
            trading_day=trading_day,
            symbols=symbols,
            stage_candidate_symbols_by_source=stage_candidate_symbols_by_source,
            include_one_time=include_one_time,
            timezone_name=timezone_name,
        )
        if lower_bound <= item.scheduled_at <= now
    ]


def _request_body_for(
    spec: SourceFetchScheduleSpec,
    *,
    trading_day: date,
    symbols: list[str],
    idempotency_key: str,
) -> dict[str, Any]:
    if spec.owner_endpoint_path != "/source/fetch/submit":
        payload: dict[str, Any] = {
            "__source_endpoint_path": spec.owner_endpoint_path,
            "source_table_name": spec.source_table_name,
            "request_source": "scheduler-service",
            "dry_run": False,
            "run_worker_once": False,
        }
        if spec.date_mode != "auto_unresolved_batch":
            payload["trade_date"] = trading_day.isoformat()
        return payload
    payload: dict[str, Any] = {
        "source_table_name": spec.source_table_name,
        "canonical_fields": list(spec.canonical_fields),
        "symbols": symbols,
        "universe_scope": _universe_scope_for_spec(spec),
        "trigger_type": spec.trigger_type,
        "priority": spec.priority,
        "request_source": "scheduler-service",
        "dry_run": False,
        "prefer_batch": True,
        "auto_start": False,
        "idempotency_key": idempotency_key,
    }
    if spec.model_code:
        payload["model_code"] = spec.model_code
    if spec.model_phase:
        payload["model_phase"] = spec.model_phase
    if spec.date_mode == "forward_24m_range":
        payload["start_date"] = trading_day.isoformat()
        payload["end_date"] = (trading_day + timedelta(days=730)).isoformat()
    elif spec.date_mode == "as_of_range":
        payload["end_date"] = trading_day.isoformat()
    else:
        payload["trade_date"] = trading_day.isoformat()
    return payload


def _universe_scope_for_spec(spec: SourceFetchScheduleSpec) -> str:
    if spec.symbol_scope == "full_a_share":
        return "full_a_share"
    if spec.symbol_scope == "stage_candidates":
        return "stage_candidates"
    return "explicit_symbols"
