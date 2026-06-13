from __future__ import annotations

from fastapi.testclient import TestClient

from hot_candidates_model_service.main import app


def _base_row() -> dict:
    return {
        "batch_id": 1,
        "candidate_id": 11,
        "instrument_id": 1001,
        "symbol": "000001",
        "name": "测试股票",
        "trade_date": "2026-06-08",
        "p_limit_up": "0.45",
        "p_limit_up_source": "paid_ths_prior",
        "limit_up_stage": 2,
        "consecutive_board_count": 2,
        "daily_bars": [
            {
                "trading_day": f"2026-05-{day:02d}",
                "open_price": "10",
                "high_price": "10.5",
                "low_price": "9.8",
                "close_price": "10.2",
                "amount": "100000000",
                "volume": "10000000",
                "turnover_rate": "5",
            }
            for day in range(1, 22)
        ],
        "stock_rank": {
            "main_net_inflow_pct_rank": "0.75",
            "large_order_net_inflow_pct_rank": "0.70",
            "super_large_order_net_inflow_pct_rank": "0.66",
            "main_net_inflow": "1000000",
            "large_order_net_inflow": "800000",
            "super_large_order_net_inflow": "500000",
        },
        "auction_snapshot": {
            "matched_amount": "8000000",
            "imbalance_ratio": "0.2",
            "open_price": "10.3",
        },
        "teacher_calibration": {
            "p40_50": {"sample_count": 150, "bucket_realized_rate": "0.61", "source": "test"}
        },
    }


def test_score_includes_lifecycle_research_contract() -> None:
    body = TestClient(app).post(
        "/score",
        json={"row": _base_row(), "as_of_time_utc": "2026-06-09T01:26:00Z"},
    ).json()
    research = body["structured_output"]["research_contract"]
    assert research["contract_kind"] == "hot_candidates_lifecycle_research_v1"
    assert research["hot_cycle"]["lifecycle_stage"] == "consecutive_board_continuation"
    assert research["hot_decision_case"]["hot_case_id"].startswith("hot-case-")
    assert research["teacher_calibration"]["teacher_prior_calibrated"] == "0.610000"
    assert research["initial_decision_snapshot"]["is_immutable_first_decision"] is True
    assert "decision_hot.hot_evolution_sample_v1" in research["persistence_plan"]["decision_hot_tables"]


def test_observe_generates_append_only_snapshot_and_deviation() -> None:
    response = TestClient(app).post(
        "/observe",
        json={
            "payload": {
                "hot_case_id": "hot-case-test",
                "hot_cycle_id": "hot-cycle-test",
                "observe_seq": 2,
                "reference_entry_price": "10.00",
                "latest_price": "9.60",
                "high_since_entry": "10.20",
                "low_since_entry": "9.50",
                "invalidation_price": "9.70",
                "vwap_lost_after_entry": True,
            },
            "as_of_time_utc": "2026-06-09T02:00:00Z",
        },
    )
    assert response.status_code == 200
    observation = response.json()["structured_output"]["observation"]
    assert observation["append_only"] is True
    assert observation["first_event_type"] == "invalidation_hit_or_touched"
    assert "vwap_lost_after_entry" in observation["deviation_reason_codes"]


def test_evolution_sample_keeps_model_mutation_offline() -> None:
    response = TestClient(app).post(
        "/evolution-sample",
        json={
            "payload": {
                "hot_case_id": "hot-case-test",
                "initial_decision_snapshot": {"first_lifecycle_stage": "high_board_overheat"},
                "observation": {
                    "observation_id": "hot-observe-test",
                    "hot_case_id": "hot-case-test",
                    "deviation_reason_codes": ["vwap_lost_after_entry"],
                },
                "outcome_label": {
                    "direction_outcome": "direction_failed",
                    "execution_outcome": "executable",
                    "label_maturity_status": "mature",
                },
            }
        },
    )
    assert response.status_code == 200
    sample = response.json()["structured_output"]["evolution_sample"]
    assert sample["sample_type"] in {"vwap_lost_failure", "high_board_overheat_failure"}
    assert sample["recommended_adjustment_json"]["do_not_mutate_production_model_online"] is True
