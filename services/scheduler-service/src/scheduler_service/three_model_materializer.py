from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from scheduler_service.three_model_plan import THREE_MODEL_TASKS, THREE_MODEL_SCHEDULER_VERSION

THREE_MODEL_MATERIALIZER_VERSION = "three_model_materializer_v1"
DEFAULT_MARKET_TZ = "Asia/Shanghai"


def _times_every_minutes(start: time, end: time, step_minutes: int) -> tuple[time, ...]:
    anchor = datetime.combine(date(2000, 1, 1), start)
    final = datetime.combine(date(2000, 1, 1), end)
    step = timedelta(minutes=step_minutes)
    items: list[time] = []
    current = anchor
    while current <= final:
        items.append(current.time())
        current += step
    return tuple(items)


def _trading_session_times_every_minutes(
    sessions: tuple[tuple[time, time], ...],
    step_minutes: int,
) -> tuple[time, ...]:
    return tuple(
        item
        for start, end in sessions
        for item in _times_every_minutes(start, end, step_minutes)
    )


T_RELAY_DAY2_POST_ENTRY_MONITOR_TIMES_LOCAL = _trading_session_times_every_minutes(
    ((time(9, 35), time(11, 30)), (time(13, 0), time(15, 0))),
    5,
)
T_RELAY_OBSERVATION_MONITOR_TIMES_LOCAL = _trading_session_times_every_minutes(
    ((time(9, 30), time(11, 30)), (time(13, 0), time(15, 0))),
    5,
)

T_RELAY_DAY3_MORNING_MONITOR_TIMES_LOCAL = _times_every_minutes(time(9, 25), time(11, 30), 5)
T_RELAY_DAY3_AFTERNOON_MONITOR_TIMES_LOCAL = _times_every_minutes(time(13, 0), time(15, 0), 5)

# These are execution starts for task windows. High-frequency windows are owned by
# the owner service after the scheduler starts the window task; the scheduler does
# not materialize every 15-second source pull as a separate row by default.
TASK_START_TIMES_LOCAL: dict[str, tuple[time, ...]] = {
    "source.auction.collect.0915_0925": (time(9, 15),),
    "source.auction.freeze.092505_092530": (time(9, 25, 5), time(9, 25, 30)),
    "hot.score.auction_confirmed": (time(9, 26), time(9, 28), time(9, 29, 30)),
    "hot.release_gate.preopen": (time(9, 25, 40), time(9, 28, 40), time(9, 29, 40)),
    "source.open_5m.collect": (time(9, 30),),
    "hot.buy_point.open_5m": (time(9, 35), time(9, 45), time(10, 0)),
    "hot.observe.intraday": (time(9, 30), time(10, 0), time(14, 30)),
    "hot.outcome.t5_t20": (time(15, 10), time(15, 40)),
    "hot.evolution.offline": (time(18, 30),),
    "memory.seed.from_hot_signals": (time(15, 45),),
    "memory.pre_signal.scan": (time(15, 55),),
    "memory.release_gate.close": (time(16, 5),),
    "memory.buy_point.next_session_reference": (time(9, 35),),
    "memory.observe.outcome.evolution": (time(15, 50),),
    "ambush.source_capability.audit": (time(20, 0),),
    "ambush.pattern_library.mine": (time(18, 10),),
    "ambush.phase2.valley_turn.close": (time(15, 20),),
    "ambush.phase3.release_gate.close": (time(15, 35),),
    "ambush.buy_point.reference": (time(15, 35),),
    "ambush.observe.outcome.evolution": (time(15, 55),),
    "t_relay.day1.scan.close": (time(15, 5), time(15, 30)),
    "t_relay.day2.watch.rolling_5m": (
        time(9, 30),
        time(9, 35),
        time(9, 40),
        time(9, 45),
        time(9, 50),
        time(9, 55),
        time(10, 0),
        time(10, 5),
        time(10, 10),
        time(10, 15),
        time(10, 20),
        time(10, 25),
        time(10, 30),
    ),
    "t_relay.day2.trigger.rolling_5m": (
        time(9, 30),
        time(9, 35),
        time(9, 40),
        time(9, 45),
        time(9, 50),
        time(9, 55),
        time(10, 0),
        time(10, 5),
        time(10, 10),
        time(10, 15),
        time(10, 20),
        time(10, 25),
        time(10, 30),
    ),
    "t_relay.day2.post_entry.monitor": T_RELAY_DAY2_POST_ENTRY_MONITOR_TIMES_LOCAL,
    "t_relay.day3.exit.open": T_RELAY_DAY3_MORNING_MONITOR_TIMES_LOCAL,
    "t_relay.day3.exit.tail": T_RELAY_DAY3_AFTERNOON_MONITOR_TIMES_LOCAL,
    "t_relay.observation.monitor.snapshot_5m": T_RELAY_OBSERVATION_MONITOR_TIMES_LOCAL,
    "t_relay.outcome.build": (time(15, 40),),
}

OPTIONAL_RESEARCH_INTRADAY_TIMES_LOCAL: dict[str, tuple[time, ...]] = {
    "memory.pre_signal.scan": (time(10, 30),),
    "ambush.phase2.valley_turn.close": (time(10, 30),),
}


@dataclass(frozen=True)
class MaterializedTaskInstance:
    task_code: str
    task_kind: str
    owner_service: str
    trading_day: str
    run_slot: str
    scheduled_at: str
    scheduled_at_local: str
    biz_key: str
    idempotency_seed: str
    is_official_publish: bool
    append_only: bool
    reads_from: list[str]
    writes_to: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def _combine_local(trading_day: date, local_time: time, tz: ZoneInfo) -> datetime:
    return datetime.combine(trading_day, local_time).replace(tzinfo=tz)


def materialize_three_model_day(
    *,
    trading_day: date,
    timezone_name: str = DEFAULT_MARKET_TZ,
    include_research_intraday: bool = False,
) -> dict:
    tz = ZoneInfo(timezone_name)
    tasks = {task.task_code: task for task in THREE_MODEL_TASKS}
    instances: list[MaterializedTaskInstance] = []
    for task_code, times in TASK_START_TIMES_LOCAL.items():
        task = tasks.get(task_code)
        if task is None:
            continue
        for local_time in times:
            local_dt = _combine_local(trading_day, local_time, tz)
            utc_dt = local_dt.astimezone(timezone.utc)
            run_slot = local_time.strftime("%H%M%S")
            biz_key = f"{task_code}:{trading_day.isoformat()}:{run_slot}"
            instances.append(
                MaterializedTaskInstance(
                    task_code=task.task_code,
                    task_kind=task.task_kind,
                    owner_service=task.owner_service,
                    trading_day=trading_day.isoformat(),
                    run_slot=run_slot,
                    scheduled_at=utc_dt.isoformat(),
                    scheduled_at_local=local_dt.isoformat(),
                    biz_key=biz_key,
                    idempotency_seed=f"{THREE_MODEL_MATERIALIZER_VERSION}:{biz_key}",
                    is_official_publish=task.is_official_publish,
                    append_only=task.append_only,
                    reads_from=task.reads_from,
                    writes_to=task.writes_to,
                )
            )
    if include_research_intraday:
        for task_code, times in OPTIONAL_RESEARCH_INTRADAY_TIMES_LOCAL.items():
            task = tasks.get(task_code)
            if task is None:
                continue
            for local_time in times:
                local_dt = _combine_local(trading_day, local_time, tz)
                utc_dt = local_dt.astimezone(timezone.utc)
                run_slot = f"research_{local_time.strftime('%H%M%S')}"
                biz_key = f"{task_code}:{trading_day.isoformat()}:{run_slot}"
                instances.append(
                    MaterializedTaskInstance(
                        task_code=task.task_code,
                        task_kind=task.task_kind,
                        owner_service=task.owner_service,
                        trading_day=trading_day.isoformat(),
                        run_slot=run_slot,
                        scheduled_at=utc_dt.isoformat(),
                        scheduled_at_local=local_dt.isoformat(),
                        biz_key=biz_key,
                        idempotency_seed=f"{THREE_MODEL_MATERIALIZER_VERSION}:{biz_key}",
                        is_official_publish=False,
                        append_only=task.append_only,
                        reads_from=task.reads_from,
                        writes_to=task.writes_to,
                    )
                )
    instances.sort(key=lambda item: item.scheduled_at)
    return {
        "contract_kind": "three_model_materialized_day_v1",
        "scheduler_version": THREE_MODEL_SCHEDULER_VERSION,
        "materializer_version": THREE_MODEL_MATERIALIZER_VERSION,
        "trading_day": trading_day.isoformat(),
        "timezone": timezone_name,
        "include_research_intraday": include_research_intraday,
        "instance_count": len(instances),
        "official_publish_instances": [item.task_code for item in instances if item.is_official_publish],
        "instances": [item.to_dict() for item in instances],
        "hard_rules": [
            "High-frequency inner loops are owned by owner services after the scheduler starts the window task.",
            "Each materialized task has a deterministic biz_key and idempotency_seed.",
            "Optional research intraday scans are marked non-official and cannot publish signals.",
            "Model-four Day2 post-entry and Day3 hold/exit observations are materialized every five minutes during trading sessions.",
            "Model-four observation monitor snapshots persist the current user-readable model output every five minutes for later tuning.",
        ],
    }
