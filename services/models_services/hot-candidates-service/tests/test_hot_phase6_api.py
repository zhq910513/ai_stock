from __future__ import annotations

from fastapi.testclient import TestClient

from hot_candidates_model_service.main import app


def test_phase6_production_endpoints_return_contracts() -> None:
    client = TestClient(app)
    row = {
        "symbol": "002354",
        "trade_date": "2026-06-08",
        "open_price": "7.33",
        "high_price": "7.98",
        "low_price": "7.28",
        "close_price": "7.90",
        "previous_close": "7.20",
        "open_5m_vwap": "7.41",
        "consecutive_board_count": 1,
        "auction_snapshot": {"auction_price": "7.33", "matched_amount": "32000000", "imbalance_ratio": "0.31"},
    }
    feature_resp = client.post("/production/features/build", json={"rows": [row], "as_of_time_utc": "2026-06-08T01:35:00Z"})
    assert feature_resp.status_code == 200
    assert feature_resp.json()["structured_output"]["count"] == 2

    obs_resp = client.post(
        "/production/observations/bulk",
        json={
            "as_of_time_utc": "2026-06-08T02:00:00Z",
            "active_cases": [
                {
                    "hot_case_id": "hot-case-api",
                    "hot_cycle_id": "hot-cycle-api",
                    "latest_price": "7.60",
                    "reference_entry_price": "7.33",
                    "high_since_entry": "7.70",
                    "low_since_entry": "7.20",
                    "freshness_status": "fresh",
                    "quality_status": "usable",
                }
            ],
        },
    )
    assert obs_resp.status_code == 200
    assert obs_resp.json()["structured_output"]["count"] == 1

    samples = [
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
        for i in range(120)
    ]
    cal_resp = client.post(
        "/production/teacher-calibration/version",
        json={
            "samples": samples,
            "calibration_version": "hot-cal-api",
            "training_window_start": "2026-06-01",
            "training_window_end": "2026-06-30",
            "calibration_cutoff_time": "2026-06-30T15:00:00Z",
        },
    )
    assert cal_resp.status_code == 200
    assert cal_resp.json()["structured_output"]["calibration_version"]["can_activate"] is True
