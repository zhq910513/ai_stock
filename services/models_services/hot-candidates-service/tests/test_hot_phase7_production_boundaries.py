from __future__ import annotations

from fastapi.testclient import TestClient

from hot_candidates_model_service.main import app


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
        "previous_close": "7.20",
        "auction_snapshot": {"auction_price": "7.33", "matched_amount": "32000000", "imbalance_ratio": "0.31", "available_at": "2026-06-08T01:25:05Z"},
        "daily_bars": [
            {"trading_day": f"2026-05-{d:02d}", "open_price": "6.8", "high_price": "7.4", "low_price": "6.6", "close_price": "7.2", "available_at": "2026-06-08T00:30:00Z"}
            for d in range(1, 22)
        ],
        "stock_rank": {"main_net_inflow_pct_rank": "0.82", "large_order_net_inflow_pct_rank": "0.78", "available_at": "2026-06-08T01:24:50Z"},
        "market_regime_context": {"available_at": "2026-06-08T01:24:00Z"},
        "teacher_calibration": {"p60_70": {"sample_count": 160, "bucket_realized_rate": "0.62"}},
    }


def test_missing_available_at_blocks_official_release_gate() -> None:
    row = _row()
    row.pop("p_limit_up_available_at")
    response = TestClient(app).post("/production/release-gate/evaluate", json={"as_of_time_utc": "2026-06-08T01:26:00Z", "payload": {"row": row}})
    assert response.status_code == 200
    result = response.json()["structured_output"]["release_gate_result"]
    assert result["release_gate"]["official_signal_allowed"] is False
    assert "missing_available_at_lineage" in result["release_gate"]["block_reasons"]
    assert result["research_sample_pool"]["include_in_official_success_rate"] is False


def test_missing_optional_context_does_not_trigger_available_at_lineage_block() -> None:
    row = _row()
    row.pop("auction_snapshot")
    row.pop("stock_rank")
    row.pop("market_regime_context")

    response = TestClient(app).post("/production/scores/compute", json={"as_of_time_utc": "2026-06-08T01:26:00Z", "payload": {"row": row}})

    assert response.status_code == 200
    result = response.json()["structured_output"]["score_compute"]
    audit = result["source_visibility_audit"]
    assert audit["status"] == "usable"
    assert "missing_available_at_lineage" not in audit["hard_block_codes"]
    assert result["score_state"] != "blocked"
    assert result["stage_scores"]["auction_confirmed_score"] is None
    assert result["stage_scores"]["pre_auction_score"] is not None


def test_present_optional_context_missing_available_at_still_blocks_lineage() -> None:
    row = _row()
    row["auction_snapshot"].pop("available_at")

    response = TestClient(app).post("/production/scores/compute", json={"as_of_time_utc": "2026-06-08T01:26:00Z", "payload": {"row": row}})

    assert response.status_code == 200
    result = response.json()["structured_output"]["score_compute"]
    audit = result["source_visibility_audit"]
    assert audit["status"] == "blocked_missing_available_at_lineage"
    assert "missing_available_at_lineage" in audit["hard_block_codes"]
    assert result["score_state"] == "blocked"


def test_buy_point_does_not_freeze_from_latest_or_previous_close() -> None:
    row = _row()
    row.pop("auction_snapshot")
    row["latest_price"] = "7.40"
    row["previous_close"] = "7.20"
    response = TestClient(app).post("/production/buy-point/evaluate", json={"as_of_time_utc": "2026-06-08T01:26:00Z", "payload": {"row": row}})
    assert response.status_code == 200
    buy = response.json()["structured_output"]["buy_point_result"]["buy_point"]
    assert buy["buy_point_status"] == "blocked"
    assert buy["is_frozen_reference"] is False
    assert "missing_official_reference_stage_evidence" in buy["block_reason"]


def test_pending_outcome_cannot_build_evolution_sample() -> None:
    response = TestClient(app).post(
        "/production/evolution/build",
        json={"as_of_time_utc": "2026-06-08T03:00:00Z", "payload": {"outcome_label": {"hot_case_id": "case-1", "label_maturity_status": "pending"}}},
    )
    assert response.status_code == 200
    result = response.json()["structured_output"]["evolution_build_result"]
    assert result["build_status"] == "blocked_outcome_not_mature"
    assert result["evolution_sample"] is None


def test_production_endpoints_are_split_by_stage() -> None:
    client = TestClient(app)
    row = _row()
    assert client.post("/production/cases/build", json={"as_of_time_utc": "2026-06-08T01:26:00Z", "payload": {"row": row}}).status_code == 200
    assert client.post("/production/scores/compute", json={"as_of_time_utc": "2026-06-08T01:26:00Z", "payload": {"row": row}}).status_code == 200
    assert client.post("/production/release-gate/evaluate", json={"as_of_time_utc": "2026-06-08T01:26:00Z", "payload": {"row": row}}).status_code == 200
    assert client.post("/production/buy-point/evaluate", json={"as_of_time_utc": "2026-06-08T01:26:00Z", "payload": {"row": row}}).status_code == 200
