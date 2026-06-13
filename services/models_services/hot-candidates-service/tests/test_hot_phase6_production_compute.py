from __future__ import annotations

from datetime import datetime, timedelta, timezone

from hot_candidates_model_service.phase6 import (
    build_active_case_registry_record,
    build_bulk_observations,
    build_hot_cycle_day_feature,
    build_hot_execution_feature_snapshot,
    build_versioned_teacher_calibration,
)
from hot_candidates_model_service.persistence import HotSQLitePersistence
from hot_candidates_model_service.pipeline import run_hot_full_pipeline


def _row(symbol: str = "002354", candidate_suffix: int = 1) -> dict:
    return {
        "batch_id": 2026060801,
        "candidate_id": 2026060801000000 + candidate_suffix,
        "instrument_id": int(symbol),
        "symbol": symbol,
        "name": "样本股",
        "trade_date": "2026-06-08",
        "candidate_available_at": "2026-06-08T01:24:00Z",
        "p_limit_up": "0.6792",
        "p_limit_up_available_at": "2026-06-08T01:24:20Z",
        "limit_up_stage": 1,
        "consecutive_board_count": 1,
        "previous_close": "7.20",
        "auction_snapshot": {
            "auction_price": "7.33",
            "matched_amount": "32000000",
            "imbalance_ratio": "0.31",
            "available_at": "2026-06-08T01:25:05Z",
        },
        "daily_bars": [
            {
                "trading_day": f"2026-05-{day:02d}",
                "open_price": "6.80",
                "high_price": "7.40",
                "low_price": "6.60",
                "close_price": "7.20",
                "amount": "180000000",
                "turnover_rate": "6.5",
                "available_at": "2026-06-08T00:30:00Z",
            }
            for day in range(1, 22)
        ],
        "stock_rank": {"main_net_inflow_pct_rank": "0.82", "available_at": "2026-06-08T01:24:50Z"},
        "market_regime_context": {"available_at": "2026-06-08T01:24:00Z", "risk_appetite_score": "72"},
        "teacher_calibration": {"p60_70": {"sample_count": 160, "bucket_realized_rate": "0.62"}},
    }


def test_phase6_precomputed_features_are_persisted_without_source_rescan() -> None:
    now = datetime(2026, 6, 8, 1, 35, tzinfo=timezone.utc)
    row = _row()
    row.update({"open_price": "7.33", "high_price": "7.98", "low_price": "7.28", "close_price": "7.90", "open_5m_vwap": "7.41"})
    day_feature = build_hot_cycle_day_feature(row, calculated_at=now)
    exec_feature = build_hot_execution_feature_snapshot(row, calc_stage="open_5m_confirmed", calculated_at=now)
    store = HotSQLitePersistence()
    assert store.apply_feature_snapshots([day_feature, exec_feature]) == 2
    assert store.table_count("hot_cycle_day_feature_v1") == 1
    assert store.table_count("hot_execution_feature_snapshot_v1") == 1


def test_phase6_active_registry_and_bulk_observation_handles_1000_cases() -> None:
    store = HotSQLitePersistence()
    decision_time = datetime(2026, 6, 8, 1, 26, tzinfo=timezone.utc)
    due_time = datetime(2026, 6, 8, 2, 0, tzinfo=timezone.utc)
    active_payloads = []
    for i in range(1000):
        symbol = f"{200000 + i:06d}"
        pipeline = run_hot_full_pipeline({"row": _row(symbol=symbol, candidate_suffix=i + 1)}, as_of_time_utc=decision_time)
        summary = store.apply_pipeline(pipeline)
        record = build_active_case_registry_record(
            hot_case_id=summary.hot_case_id,
            hot_cycle_id=summary.hot_cycle_id,
            tracking_pool="official_signal_pool",
            now=decision_time,
            priority_level=100,
        )
        # force due now for batch observation acceptance test
        record["next_observe_at"] = (due_time - timedelta(seconds=1)).isoformat()
        store.upsert_active_case_registry(record)
        active_payloads.append(
            {
                "hot_case_id": summary.hot_case_id,
                "hot_cycle_id": summary.hot_cycle_id,
                "latest_price": "7.60",
                "reference_entry_price": "7.33",
                "high_since_entry": "7.70",
                "low_since_entry": "7.20",
                "freshness_status": "fresh",
                "quality_status": "usable",
                "observe_seq": 10,
            }
        )
    due = store.due_active_cases(now=due_time, limit=1000)
    assert len(due) == 1000
    observations = build_bulk_observations(active_payloads, as_of_time_utc=due_time)
    inserted = store.append_observations_bulk(observations)
    assert inserted == 1000
    assert store.table_count("hot_observation_snapshot_v1") == 1000
    latest = store.latest_state(active_payloads[0]["hot_case_id"])
    assert latest is not None
    assert latest["monitoring_status"] in {"monitoring", "target_hit", "invalidation_hit"}
    # Replay is idempotent and does not duplicate append-only facts.
    assert store.append_observations_bulk(observations) == 0
    assert store.table_count("hot_observation_snapshot_v1") == 1000


def test_phase6_teacher_calibration_uses_only_mature_samples_before_cutoff() -> None:
    cutoff = datetime(2026, 6, 30, 15, 0, tzinfo=timezone.utc)
    mature_samples = []
    for i in range(120):
        mature_samples.append(
            {
                "hot_case_id": f"case-{i}",
                "lifecycle_stage": "first_board_confirmation",
                "probability_bucket": "p60_70",
                "teacher_prior_raw": "0.65",
                "direction_outcome": "direction_success" if i < 72 else "direction_failed",
                "execution_outcome": "executable",
                "label_maturity_status": "mature",
                "updated_at": "2026-06-29T15:00:00+00:00",
            }
        )
    immature = {
        "hot_case_id": "future-case",
        "lifecycle_stage": "first_board_confirmation",
        "probability_bucket": "p60_70",
        "teacher_prior_raw": "0.65",
        "direction_outcome": "direction_success",
        "execution_outcome": "executable",
        "label_maturity_status": "pending",
        "updated_at": "2026-07-01T15:00:00+00:00",
    }
    versioned = build_versioned_teacher_calibration(
        mature_samples + [immature],
        calibration_version="hot-cal-v2-test",
        training_window_start="2026-06-01",
        training_window_end="2026-06-30",
        cutoff_time=cutoff,
        min_bucket_samples=30,
        min_total_samples=120,
    )
    assert versioned["raw_sample_count"] == 121
    assert versioned["mature_sample_count"] == 120
    assert versioned["can_activate"] is True
    store = HotSQLitePersistence()
    store.apply_calibration_version(versioned)
    assert store.table_count("hot_calibration_job_v1") == 1
    assert store.table_count("hot_teacher_calibration_version_v1") == 1
