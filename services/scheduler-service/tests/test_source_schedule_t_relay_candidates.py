from __future__ import annotations

from datetime import date, datetime, timezone

from scheduler_service.source_schedule import (
    T_RELAY_DAY1_QUALIFIED_STAGE_CANDIDATE_SOURCE,
    T_RELAY_LIMIT_EVENT_STAGE_CANDIDATE_SOURCE,
    due_source_fetch_instances,
    materialize_source_fetch_schedule,
    source_schedule_registry,
    validate_source_schedule_registry,
)


def test_t_relay_candidate_fact_schedules_are_stage_candidate_scoped() -> None:
    schedules = {item["schedule_code"]: item for item in source_schedule_registry()}

    assert validate_source_schedule_registry()["valid"] is True
    assert schedules["source.daily.close_bars"]["symbol_scope"] == "full_a_share"
    assert schedules["source.daily.adjusted_bars"]["symbol_scope"] == "full_a_share"
    assert schedules["source.window.limit_event_t_relay"]["symbol_scope"] == "full_a_share"

    candidate_codes = {
        "source.window.t_relay_candidate_trade_status",
        "source.window.t_relay_candidate_daily_bar",
        "source.window.t_relay_candidate_limit_price",
        "source.window.t_relay_candidate_float_market_cap",
    }
    for code in candidate_codes:
        schedule = schedules[code]
        assert schedule["schedule_group"] == "t_relay_day1_candidate_facts"
        assert schedule["symbol_scope"] == "stage_candidates"
        assert schedule["stage_candidate_source"] == T_RELAY_LIMIT_EVENT_STAGE_CANDIDATE_SOURCE
        assert schedule["priority"] == "P0_urgent_release"
        assert schedule["model_code"] == "t_board_relay"
    day2_codes = {
        "source.window.t_relay_day2_limit_price",
        "source.window.t_relay_day2_realtime_quote",
        "source.window.t_relay_day2_minute_bar",
        "source.window.t_relay_trade_tick",
    }
    for code in day2_codes:
        schedule = schedules[code]
        assert schedule["schedule_group"] == "t_relay_day2_window"
        assert schedule["symbol_scope"] == "stage_candidates"
        assert schedule["stage_candidate_source"] == T_RELAY_DAY1_QUALIFIED_STAGE_CANDIDATE_SOURCE
        assert schedule["priority"] == "P0_urgent_release"
        assert schedule["model_code"] == "t_board_relay"
    rolling_codes = day2_codes - {"source.window.t_relay_day2_limit_price"}
    for code in rolling_codes:
        slots = set(schedules[code]["times_local"])
        assert {"09:30:00", "11:30:00", "13:00:00", "15:00:00"}.issubset(slots)
        assert "12:30:00" not in slots


def test_stage_candidate_schedules_do_not_inherit_configured_sample_symbols() -> None:
    instances = materialize_source_fetch_schedule(
        trading_day=date(2026, 6, 22),
        symbols=["000063.SZ", "000759.SZ"],
    )

    assert any(item.schedule_code == "source.minute.realtime_quote" for item in instances)
    assert not any(item.schedule_group == "t_relay_day1_candidate_facts" for item in instances)
    assert not any(item.schedule_group == "t_relay_day2_window" for item in instances)


def test_t_relay_limit_event_candidates_materialize_candidate_fact_fetches() -> None:
    candidate_symbols = ["000048.SZ", "002885.SZ"]
    instances = materialize_source_fetch_schedule(
        trading_day=date(2026, 6, 22),
        symbols=["000063.SZ"],
        stage_candidate_symbols_by_source={
            T_RELAY_LIMIT_EVENT_STAGE_CANDIDATE_SOURCE: candidate_symbols,
        },
    )

    candidate_instances = [item for item in instances if item.schedule_group == "t_relay_day1_candidate_facts"]
    assert candidate_instances
    assert {item.source_table_name for item in candidate_instances} == {
        "source.daily_bar_v1",
        "source.limit_price_v1",
        "source.realtime_quote_v1",
        "source.trade_status_v1",
    }
    assert all(item.request_body["symbols"] == sorted(candidate_symbols) for item in candidate_instances)
    assert all(item.request_body["universe_scope"] == "stage_candidates" for item in candidate_instances)
    assert all(item.request_body["model_phase"] == "day1_candidate_facts" for item in candidate_instances)
    assert not any(item.schedule_code == "source.window.t_relay_trade_tick" for item in instances)


def test_day1_qualified_candidates_materialize_day2_window_fetches() -> None:
    instances = materialize_source_fetch_schedule(
        trading_day=date(2026, 6, 23),
        stage_candidate_symbols_by_source={
            T_RELAY_DAY1_QUALIFIED_STAGE_CANDIDATE_SOURCE: ["000048.SZ"],
        },
    )

    day2_instances = [item for item in instances if item.schedule_group == "t_relay_day2_window"]
    assert day2_instances
    assert {item.source_table_name for item in day2_instances} == {
        "source.limit_price_v1",
        "source.minute_bar_v1",
        "source.realtime_quote_v1",
        "source.trade_tick_v1",
    }
    assert all(item.request_body["symbols"] == ["000048.SZ"] for item in day2_instances)
    assert all(item.request_body["universe_scope"] == "stage_candidates" for item in day2_instances)
    by_code = {}
    for item in day2_instances:
        by_code.setdefault(item.schedule_code, set()).add(item.run_slot)
    assert {"093000", "113000", "130000", "150000"}.issubset(by_code["source.window.t_relay_day2_minute_bar"])
    assert "123000" not in by_code["source.window.t_relay_day2_minute_bar"]


def test_due_source_fetch_instances_can_submit_candidate_fact_window_only() -> None:
    due = due_source_fetch_instances(
        now=datetime(2026, 6, 22, 7, 12, 30, tzinfo=timezone.utc),
        symbols=["000063.SZ"],
        stage_candidate_symbols_by_source={
            T_RELAY_LIMIT_EVENT_STAGE_CANDIDATE_SOURCE: ["000048.SZ"],
        },
        lateness_seconds=90,
    )

    assert {item.schedule_group for item in due} == {"t_relay_day1_candidate_facts"}
    assert {item.source_table_name for item in due} == {
        "source.daily_bar_v1",
        "source.limit_price_v1",
        "source.trade_status_v1",
        "source.realtime_quote_v1",
    }
