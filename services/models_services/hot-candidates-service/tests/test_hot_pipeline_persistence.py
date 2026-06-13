from __future__ import annotations

from datetime import datetime, timezone

from hot_candidates_model_service.persistence import HotSQLitePersistence
from hot_candidates_model_service.pipeline import run_hot_full_pipeline


def _row(symbol: str = "002354", *, p_limit_up: str = "0.6792") -> dict:
    return {
        "batch_id": 2026060801,
        "candidate_id": int(f"2026060801{symbol}"),
        "instrument_id": int(symbol),
        "symbol": symbol,
        "name": "天娱数科" if symbol == "002354" else "样本股",
        "trade_date": "2026-06-08",
        "candidate_available_at": "2026-06-08T01:24:00Z",
        "p_limit_up": p_limit_up,
        "p_limit_up_available_at": "2026-06-08T01:24:20Z",
        "p_limit_up_source": "paid_ths_prior",
        "limit_up_stage": 1,
        "consecutive_board_count": 1,
        "previous_close": "7.20",
        "auction_snapshot": {
            "auction_price": "7.33",
            "matched_amount": "32000000",
            "imbalance_ratio": "0.31",
            "available_at": "2026-06-08T01:25:05Z",
            "raw_payload_id": 8101,
        },
        "daily_bars": [
            {
                "trading_day": f"2026-05-{day:02d}",
                "open_price": "6.80",
                "high_price": "7.40",
                "low_price": "6.60",
                "close_price": "7.20",
                "amount": "180000000",
                "volume": "26000000",
                "turnover_rate": "6.5",
                "available_at": "2026-06-08T00:30:00Z",
                "raw_payload_id": 9000 + day,
            }
            for day in range(1, 22)
        ],
        "stock_rank": {
            "main_net_inflow": "35000000",
            "large_order_net_inflow": "22000000",
            "super_large_order_net_inflow": "9000000",
            "main_net_inflow_pct_rank": "0.82",
            "large_order_net_inflow_pct_rank": "0.78",
            "super_large_order_net_inflow_pct_rank": "0.71",
            "available_at": "2026-06-08T01:24:50Z",
            "raw_payload_id": 9201,
        },
        "market_regime_context": {
            "snapshot_id": 9301,
            "available_at": "2026-06-08T01:24:00Z",
            "risk_appetite_score": "72",
        },
        "teacher_calibration": {
            "p60_70": {"sample_count": 160, "bucket_realized_rate": "0.62"}
        },
    }


def test_pipeline_persists_real_hot_lifecycle_tables_and_keeps_initial_snapshot_frozen() -> None:
    pipeline = run_hot_full_pipeline(
        {
            "row": _row(),
            "trade_day_index": 4,
            "observations": [
                {"observe_time": "2026-06-08T02:00:00Z", "latest_price": "7.45", "high_since_entry": "7.50", "low_since_entry": "7.28", "freshness_status": "fresh", "quality_status": "usable"},
                {"observe_time": "2026-06-11T06:51:00Z", "latest_price": "7.98", "high_since_entry": "7.98", "low_since_entry": "7.28", "freshness_status": "fresh", "quality_status": "usable"},
            ],
        },
        as_of_time_utc=datetime(2026, 6, 8, 1, 26, tzinfo=timezone.utc),
    )
    store = HotSQLitePersistence()
    summary = store.apply_pipeline(pipeline)
    assert summary.table_counts["hot_cycle_v1"] == 1
    assert summary.table_counts["hot_decision_case_v1"] == 1
    assert summary.table_counts["hot_signal_fact_v1"] == 1
    assert summary.table_counts["hot_buy_point_v1"] == 1
    assert summary.table_counts["hot_observation_snapshot_v1"] == 2
    assert summary.table_counts["hot_outcome_label_v1"] == 1
    frozen = store.latest_initial_snapshot(summary.hot_case_id)
    assert frozen is not None
    assert frozen["is_immutable_first_decision"] == 1
    assert frozen["first_release_gate_status"] == "passed"
    evaluation = store.build_model_version_evaluation()
    assert evaluation["sample_count"] == 1
    assert evaluation["direction_success_rate"] == 100.0


def test_persistence_does_not_replace_initial_decision_when_same_case_is_replayed() -> None:
    base = run_hot_full_pipeline(
        {"row": _row(), "observations": []},
        as_of_time_utc=datetime(2026, 6, 8, 1, 26, tzinfo=timezone.utc),
    )
    replay = run_hot_full_pipeline(
        {"row": _row(p_limit_up="0.9999"), "observations": []},
        as_of_time_utc=datetime(2026, 6, 8, 1, 26, tzinfo=timezone.utc),
    )
    store = HotSQLitePersistence()
    summary = store.apply_pipeline(base)
    before = store.latest_initial_snapshot(summary.hot_case_id)
    assert before is not None
    store.apply_pipeline(replay)
    after = store.latest_initial_snapshot(summary.hot_case_id)
    assert after is not None
    assert after["initial_snapshot_id"] == before["initial_snapshot_id"]
    assert after["first_teacher_prior_raw"] == before["first_teacher_prior_raw"]
    assert store.table_count("hot_initial_decision_snapshot_v1") == 1
