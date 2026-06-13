from __future__ import annotations

from fastapi.testclient import TestClient

from hot_candidates_model_service.main import app


def test_hot_healthz_probe() -> None:
    response = TestClient(app).get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "hot-candidates-model-service"}


def test_hot_score_returns_structured_jarvis_payload() -> None:
    client = TestClient(app)
    row = {
        "batch_id": 1,
        "candidate_id": 11,
        "instrument_id": 1001,
        "symbol": "000001",
        "p_limit_up": "0.82",
        "p_limit_up_source": "paid_ths_prior",
        "limit_up_stage": 1,
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
        "minute_bars": [{"amount": "1000000", "volume": "100000"} for _ in range(5)],
    }
    response = client.post("/score", json={"row": row})
    assert response.status_code == 200
    body = response.json()
    assert body["model_name"] == "hot_candidates"
    assert body["jarvis_payload"]["schema_version"] == "jarvis_model_payload_v1"
    assert body["jarvis_payload"]["guardrails"]["jarvis_can_mutate_scores"] is False
    contract = body["structured_output"]["contract"]
    assert contract["candidate_item"]["batch_id"] == 1
    assert contract["candidate_item"]["candidate_id"] == 11
    assert "missing_candidate_batch" not in contract["analysis"]["hard_block_reasons"]


def test_hot_score_preserves_runtime_evidence_lineage() -> None:
    client = TestClient(app)
    row = {
        "batch_id": 1,
        "candidate_id": 11,
        "instrument_id": 1001,
        "symbol": "000001",
        "p_limit_up": "0.82",
        "p_limit_up_source": "paid_ths_prior",
        "limit_up_stage": 1,
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
                "raw_payload_id": 500 + day,
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
            "raw_payload_id": 601,
        },
        "auction_snapshot": {
            "matched_amount": "8000000",
            "imbalance_ratio": "0.2",
            "open_price": "10.3",
            "raw_payload_id": 701,
        },
        "minute_bars": [{"amount": "1000000", "volume": "100000", "raw_payload_id": 801} for _ in range(5)],
        "dynamic_signal_bundle": {
            "latest_id": 901,
            "snapshot_id": 902,
            "as_of_time": "2026-05-12T01:30:00Z",
            "window_seconds": 300,
            "data_quality": "ready",
            "source_gap_codes": [],
        },
        "news_event_context": [
            {
                "impact_snapshot_id": 1001,
                "event_id": 1002,
                "impact_score": "0.62",
                "first_seen_at": "2026-05-12T01:20:00Z",
            }
        ],
        "market_regime_context": {
            "snapshot_id": 1101,
            "trading_day": "2026-05-12",
            "as_of_time": "2026-05-12T01:30:00Z",
            "data_quality": "ready",
        },
        "inspection_context": {
            "subject_id": 1201,
            "run_id": "inspect-1",
            "inspection_status": "passed",
            "completeness_score": "1.000000",
            "created_at": "2026-05-12T01:31:00Z",
        },
    }

    response = client.post("/score", json={"row": row, "as_of_time_utc": "2026-05-12T01:31:00Z"})

    assert response.status_code == 200
    snapshots = {
        item["evidence_domain"]: item
        for item in response.json()["structured_output"]["contract"]["evidence_snapshots"]
    }
    assert snapshots["dynamic_signal_context"]["dimension_status"] == "present"
    assert snapshots["dynamic_signal_context"]["source_table"] == "decision.dynamic_feature_latest"
    assert snapshots["dynamic_signal_context"]["source_primary_key"] == "901"
    assert snapshots["news_event_context"]["source_primary_key"] == "1001"
    assert snapshots["market_regime_context"]["source_primary_key"] == "1101"
    assert snapshots["inspection_context"]["source_primary_key"] == "1201"


def test_hot_distortion_report_returns_structured_output() -> None:
    client = TestClient(app)
    response = client.post(
        "/distortion-report",
        json={
            "analyses": [],
            "labels": [],
            "trade_date": "2026-05-15",
            "min_learning_samples": 120,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["model_name"] == "hot_candidates"
    report = body["structured_output"]["report"]
    assert report["contract_kind"] == "hot_candidate_teacher_distortion_report_v1"
    assert report["candidate_source"] == "hot_candidates"
    assert body["jarvis_payload"]["guardrails"]["jarvis_can_mutate_scores"] is False


def test_hot_contract_blocks_public_or_missing_paid_prior() -> None:
    client = TestClient(app)
    row = {
        "batch_id": 1,
        "candidate_id": 11,
        "instrument_id": 1001,
        "symbol": "000001",
        "p_limit_up": "0.82",
        "p_limit_up_source": "public_draft",
        "limit_up_stage": 1,
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
        },
        "auction_snapshot": {
            "matched_amount": "8000000",
            "imbalance_ratio": "0.2",
            "open_price": "10.3",
        },
    }

    response = client.post("/score", json={"row": row, "as_of_time_utc": "2026-05-12T01:25:00Z"})

    assert response.status_code == 200
    contract = response.json()["structured_output"]["contract"]
    assert contract["analysis"]["hot_score"] is None
    assert contract["analysis"]["state"] == "blocked"
    assert "missing_paid_prior" in contract["analysis"]["hard_block_reasons"]


def test_hot_contract_blocks_invalid_daily_ohlc_path() -> None:
    client = TestClient(app)
    row = {
        "batch_id": 1,
        "candidate_id": 11,
        "instrument_id": 1001,
        "symbol": "000001",
        "p_limit_up": "0.82",
        "p_limit_up_source": "paid_ths_prior",
        "limit_up_stage": 1,
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
    }
    row["daily_bars"][-1]["high_price"] = "9.9"

    response = client.post("/score", json={"row": row, "as_of_time_utc": "2026-05-12T01:25:00Z"})

    assert response.status_code == 200
    contract = response.json()["structured_output"]["contract"]
    assert contract["analysis"]["hot_score"] is None
    assert contract["analysis"]["state"] == "blocked"
    assert "missing_daily_price_path" in contract["analysis"]["hard_block_reasons"]
    assert "source_gap:daily_ohlc_invalid" in contract["analysis"]["source_gap_codes"]


def test_hot_contract_feature_hash_is_reproducible_for_same_snapshot() -> None:
    client = TestClient(app)
    row = {
        "batch_id": 1,
        "candidate_id": 11,
        "instrument_id": 1001,
        "symbol": "000001",
        "p_limit_up": "0.82",
        "p_limit_up_source": "paid_ths_prior",
        "limit_up_stage": 1,
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
    }
    payload = {"row": row, "as_of_time_utc": "2026-05-12T01:25:00Z", "run_id": "fixed-run"}

    first = client.post("/score", json=payload)
    second = client.post("/score", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    first_contract = first.json()["structured_output"]["contract"]
    second_contract = second.json()["structured_output"]["contract"]
    assert first_contract["candidate_item"]["batch_id"] == 1
    assert first_contract["candidate_item"]["candidate_id"] == 11
    assert first_contract["feature_matrix"]["feature_hash"] == second_contract["feature_matrix"]["feature_hash"]
    assert first_contract["analysis"]["score_hash"] == second_contract["analysis"]["score_hash"]


def test_hot_score_distinguishes_present_auction_snapshot_from_missing_auction() -> None:
    client = TestClient(app)
    row = {
        "batch_id": 1,
        "candidate_id": 11,
        "instrument_id": 1001,
        "symbol": "000001",
        "p_limit_up": "0.82",
        "p_limit_up_source": "paid_ths_prior",
        "limit_up_stage": 1,
        "auction_context_due": True,
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
            "imbalance_ratio": "0.2",
            "raw_payload_id": 701,
            "captured_at": "2026-05-12T01:25:10Z",
        },
    }

    response = client.post("/score", json={"row": row, "as_of_time_utc": "2026-05-12T01:25:30Z"})

    assert response.status_code == 200
    contract = response.json()["structured_output"]["contract"]
    source_gap_codes = contract["analysis"]["source_gap_codes"]
    assert "auction_missing_after_due" not in source_gap_codes
    assert "source_gap:auction_confirmation" not in source_gap_codes
    assert "auction_confirmation_score_incomplete" in source_gap_codes
    auction_snapshot = next(
        item for item in contract["evidence_snapshots"] if item["evidence_domain"] == "auction_context"
    )
    assert auction_snapshot["dimension_status"] == "present"
