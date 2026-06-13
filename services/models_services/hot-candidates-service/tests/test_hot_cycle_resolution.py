from __future__ import annotations

from hot_candidates_model_service.research import build_hot_cycle_identity


def test_consecutive_candidate_reuses_active_hot_cycle() -> None:
    row = {
        "symbol": "002354",
        "trade_date": "2026-06-09",
        "consecutive_board_count": 2,
        "active_hot_cycle": {
            "hot_cycle_id": "hot-cycle-existing",
            "cycle_start_date": "2026-06-08",
            "last_seen_trade_date": "2026-06-08",
            "cycle_status": "active",
        },
    }
    cycle = build_hot_cycle_identity(row)
    assert cycle["hot_cycle_id"] == "hot-cycle-existing"
    assert cycle["lifecycle_stage"] == "consecutive_board_continuation"
    assert cycle["cycle_resolution"]["continuity_state"] == "same_active_cycle"


def test_cooled_candidate_starts_new_cycle() -> None:
    row = {
        "symbol": "002354",
        "trade_date": "2026-06-20",
        "cycle_start_date": "2026-06-20",
        "active_hot_cycle": {
            "hot_cycle_id": "hot-cycle-old",
            "cycle_start_date": "2026-06-08",
            "last_seen_trade_date": "2026-06-10",
            "cycle_status": "active",
            "drawdown_from_cycle_high_pct": 15,
        },
    }
    cycle = build_hot_cycle_identity(row)
    assert cycle["hot_cycle_id"] != "hot-cycle-old"
    assert cycle["cycle_resolution"]["should_start_new_cycle"] is True
    assert "cooling_window_exceeded" in cycle["cycle_resolution"]["cooling_reason_codes"]


def test_relimit_after_break_can_remain_same_cycle_even_after_gap() -> None:
    row = {
        "symbol": "002354",
        "trade_date": "2026-06-16",
        "relimit_after_break_flag": True,
        "active_hot_cycle": {
            "hot_cycle_id": "hot-cycle-existing",
            "cycle_start_date": "2026-06-08",
            "last_seen_trade_date": "2026-06-10",
            "cycle_status": "active",
            "drawdown_from_cycle_high_pct": 8,
        },
    }
    cycle = build_hot_cycle_identity(row)
    assert cycle["hot_cycle_id"] == "hot-cycle-existing"
    assert cycle["lifecycle_stage"] == "relimit_after_break"
