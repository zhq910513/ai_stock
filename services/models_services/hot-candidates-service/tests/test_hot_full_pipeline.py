from __future__ import annotations

from fastapi.testclient import TestClient

from hot_candidates_model_service.main import app


def _supplied_hot_row() -> dict:
    # Uses the user's supplied hot-model row semantics for 天娱数科 002354:
    # p_limit_up=67.92%, model is expected to have enough local evidence to pass.
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
        "market_regime_context": {
            "snapshot_id": 9301,
            "available_at": "2026-06-08T01:24:00Z",
            "risk_appetite_score": "72",
        },
        "teacher_calibration": {
            "p60_70": {"sample_count": 160, "bucket_realized_rate": "0.62", "source": "decision_hot.hot_teacher_calibration_v1"}
        },
    }


def test_full_pipeline_connects_score_buy_point_observation_outcome_and_evolution() -> None:
    client = TestClient(app)
    response = client.post(
        "/pipeline/run",
        json={
            "as_of_time_utc": "2026-06-08T01:26:00Z",
            "payload": {
                "row": _supplied_hot_row(),
                "trade_day_index": 4,
                "observations": [
                    {
                        "observe_time": "2026-06-08T02:00:00Z",
                        "latest_price": "7.45",
                        "high_since_entry": "7.50",
                        "low_since_entry": "7.28",
                        "freshness_status": "fresh",
                        "quality_status": "usable",
                    },
                    {
                        "observe_time": "2026-06-11T06:51:00Z",
                        "latest_price": "7.98",
                        "high_since_entry": "7.98",
                        "low_since_entry": "7.28",
                        "freshness_status": "fresh",
                        "quality_status": "usable",
                    },
                ],
            },
        },
    )
    assert response.status_code == 200
    pipeline = response.json()["structured_output"]["pipeline"]
    assert pipeline["contract_kind"] == "hot_candidates_full_pipeline_v1"
    assert pipeline["research_contract"]["release_gate"]["official_signal_allowed"] is True
    assert pipeline["buy_point"]["buy_point_status"] == "confirmed"
    assert pipeline["buy_point"]["is_frozen_reference"] is True
    assert pipeline["outcome_label"]["direction_outcome"] == "direction_success"
    assert pipeline["outcome_label"]["first_event_type"] == "target_first"
    assert pipeline["validation_summary"]["observations_append_only"] is True
    assert pipeline["validation_summary"]["model_mutation_online"] is False
    assert pipeline["evolution_sample"]["recommended_adjustment_json"]["do_not_mutate_production_model_online"] is True


def test_full_pipeline_blocks_future_source_fact_time_leakage() -> None:
    row = _supplied_hot_row()
    row["p_limit_up_available_at"] = "2026-06-08T01:31:00Z"
    response = TestClient(app).post(
        "/pipeline/run",
        json={"as_of_time_utc": "2026-06-08T01:26:00Z", "payload": {"row": row}},
    )
    assert response.status_code == 200
    body = response.json()
    pipeline = body["structured_output"]["pipeline"]
    assert "evidence_available_after_decision_time" in body["contract_gaps"]
    assert pipeline["research_contract"]["release_gate"]["official_signal_allowed"] is False
    assert pipeline["buy_point"]["buy_point_status"] == "blocked"
    assert pipeline["research_contract"]["source_visibility_audit"]["status"] == "blocked_time_leakage"
