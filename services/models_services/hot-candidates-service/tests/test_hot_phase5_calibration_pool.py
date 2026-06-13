from __future__ import annotations

from fastapi.testclient import TestClient

from hot_candidates_model_service.main import app
from hot_candidates_model_service.persistence import HotSQLitePersistence
from hot_candidates_model_service.calibration import build_hot_teacher_calibration_report


def _row() -> dict:
    return {
        "batch_id": 2026060801,
        "candidate_id": 2026060801002354,
        "instrument_id": 2354,
        "symbol": "002354",
        "name": "天娱数科",
        "trade_date": "2026-06-08",
        "candidate_available_at": "2026-06-08T01:24:00Z",
        "p_limit_up": "0.6792",
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
            "main_net_inflow_pct_rank": "0.82",
            "large_order_net_inflow_pct_rank": "0.78",
            "super_large_order_net_inflow_pct_rank": "0.71",
            "main_net_inflow": "35000000",
            "large_order_net_inflow": "22000000",
            "super_large_order_net_inflow": "9000000",
            "available_at": "2026-06-08T01:24:50Z",
            "raw_payload_id": 9201,
        },
        "market_regime_context": {"snapshot_id": 9301, "available_at": "2026-06-08T01:24:00Z"},
        "teacher_calibration": {
            "p60_70": {"sample_count": 160, "bucket_realized_rate": "0.62"}
        },
    }


def _pipeline_payload() -> dict:
    return {
        "as_of_time_utc": "2026-06-08T01:26:00Z",
        "payload": {
            "row": _row(),
            "trade_day_index": 4,
            "observations": [
                {"latest_price": "7.98", "high_since_entry": "7.98", "low_since_entry": "7.28", "freshness_status": "fresh", "quality_status": "usable"}
            ],
        },
    }


def test_pipeline_outputs_research_pool_record_for_selection_bias_control() -> None:
    client = TestClient(app)
    response = client.post("/pipeline/run", json=_pipeline_payload())
    assert response.status_code == 200
    pipeline = response.json()["structured_output"]["pipeline"]
    pool = pipeline["research_sample_pool"]
    assert pool["contract_kind"] == "hot_research_sample_pool_v1"
    assert pool["tracking_pool"] == "official_signal_pool"
    assert pool["include_in_official_success_rate"] is True
    assert pool["include_in_teacher_calibration"] is True
    assert pipeline["validation_summary"]["research_pool_append_only"] is True


def test_teacher_calibration_report_uses_brier_and_lifecycle_buckets() -> None:
    samples = []
    for i in range(4):
        samples.append(
            {
                "hot_case_id": f"case-success-{i}",
                "lifecycle_stage": "first_board_confirmation",
                "p_limit_up": "0.70",
                "direction_outcome": "direction_success",
                "execution_outcome": "executable",
                "market_regime_bucket": "all",
                "sector_heat_bucket": "hot",
                "official_signal_allowed": True,
            }
        )
    samples.append(
        {
            "hot_case_id": "case-failure-1",
            "lifecycle_stage": "first_board_confirmation",
            "p_limit_up": "0.70",
            "direction_outcome": "direction_failed",
            "execution_outcome": "executable",
            "market_regime_bucket": "all",
            "sector_heat_bucket": "hot",
            "official_signal_allowed": True,
        }
    )
    response = TestClient(app).post(
        "/teacher-calibration/report",
        json={"samples": samples, "min_bucket_samples": 3, "min_total_samples": 5},
    )
    assert response.status_code == 200
    report = response.json()["structured_output"]["teacher_calibration_report"]
    assert report["sample_counts"]["evaluated_count"] == 5
    assert report["overall_metrics"]["overall_brier_score"] is not None
    bucket = report["bucket_calibrations"][0]
    assert bucket["lifecycle_stage"] == "first_board_confirmation"
    assert bucket["probability_bucket"] == "p70_80"
    assert bucket["evaluated_count"] == 5
    assert bucket["can_activate"] is True
    assert report["activation_gate"]["must_shadow_run_before_production"] is True


def test_sqlite_persists_research_pool_and_teacher_calibration_rows() -> None:
    client = TestClient(app)
    pipeline = client.post("/pipeline/run", json=_pipeline_payload()).json()["structured_output"]["pipeline"]
    store = HotSQLitePersistence()
    try:
        summary = store.apply_pipeline(pipeline)
        assert summary.table_counts["hot_research_sample_pool_v1"] == 1
        report = build_hot_teacher_calibration_report([pipeline], min_bucket_samples=1, min_total_samples=1)
        inserted = store.apply_teacher_calibration_report(report)
        assert inserted >= 1
        assert store.table_count("hot_teacher_calibration_v1") >= 1
    finally:
        store.close()
