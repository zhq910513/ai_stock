from __future__ import annotations

from fastapi.testclient import TestClient

from candidate_memory_model_service.main import app


def _strong_second_wave_row(memory_age_days: int) -> dict:
    daily_bars = []
    for index in range(31):
        if index < 16:
            close = 10.00 + index * 0.01
            high = close + 0.12
            low = 9.20 + index * 0.02
            amount = 100_000_000
        elif index < 26:
            close = 10.15 + (index - 16) * 0.02
            high = close + 0.10
            low = 9.85 + (index - 16) * 0.02
            amount = 105_000_000
        else:
            close = 10.45 + (index - 26) * 0.04
            high = close + 0.08
            low = 10.18 + (index - 26) * 0.03
            amount = 135_000_000
        daily_bars.append(
            {
                "trading_day": f"2026-05-{index + 1:02d}",
                "open_price": f"{close - 0.04:.2f}",
                "high_price": f"{high:.2f}",
                "low_price": f"{low:.2f}",
                "close_price": f"{close:.2f}",
                "amount": str(amount),
                "volume": "10000000",
                "turnover_rate": "5",
            }
        )
    return {
        "batch_id": 1,
        "candidate_id": 11,
        "instrument_id": 1001,
        "symbol": "000001",
        "p_limit_up": "0.72",
        "p_limit_up_source": "paid_ths_prior",
        "max_p_limit_up": "0.72",
        "limit_up_stage": 1,
        "ingest_mode": "external_ths_model",
        "contract_audit_status": "passed",
        "memory_age_days": memory_age_days,
        "daily_bars": daily_bars,
        "stock_rank": {
            "main_net_inflow_pct_rank": "0.74",
            "large_order_net_inflow_pct_rank": "0.70",
            "super_large_order_net_inflow_pct_rank": "0.66",
        },
    }


def test_candidate_memory_healthz_probe() -> None:
    response = TestClient(app).get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "candidate-memory-model-service"}


def test_candidate_memory_score_returns_structured_jarvis_payload() -> None:
    client = TestClient(app)
    row = {
        "batch_id": 1,
        "candidate_id": 11,
        "instrument_id": 1001,
        "symbol": "000001",
        "p_limit_up": "0.62",
        "p_limit_up_source": "paid_ths_prior",
        "max_p_limit_up": "0.72",
        "limit_up_stage": 1,
        "ingest_mode": "external_ths_model",
        "contract_audit_status": "passed",
        "memory_age_days": 3,
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
            for day in range(1, 32)
        ],
        "stock_rank": {
            "main_net_inflow_pct_rank": "0.70",
            "large_order_net_inflow_pct_rank": "0.68",
            "super_large_order_net_inflow_pct_rank": "0.60",
        },
    }
    response = client.post("/score", json={"row": row})
    assert response.status_code == 200
    body = response.json()
    assert body["model_name"] == "candidate_memory"
    assert body["jarvis_payload"]["schema_version"] == "jarvis_model_payload_v1"
    assert body["jarvis_payload"]["guardrails"]["jarvis_can_mutate_state"] is False


def test_candidate_memory_moneyflow_gap_does_not_backfill_accumulation_score() -> None:
    client = TestClient(app)
    row = {
        "batch_id": 1,
        "candidate_id": 11,
        "instrument_id": 1001,
        "symbol": "000001",
        "p_limit_up": "0.62",
        "p_limit_up_source": "paid_ths_prior",
        "max_p_limit_up": "0.72",
        "limit_up_stage": 1,
        "ingest_mode": "external_ths_model",
        "contract_audit_status": "passed",
        "memory_age_days": 3,
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
            for day in range(1, 32)
        ],
    }
    response = client.post("/score", json={"row": row})
    assert response.status_code == 200
    contract = response.json()["structured_output"]["contract"]
    assert contract["memory_hit_8pct_score"] is None
    assert contract["publication_state"] == "warning"
    assert contract["score_breakdown"]["quiet_accumulation_score"] is None
    assert "source_gap:moneyflow_stock_rank" in contract["source_gap_codes"]


def test_candidate_memory_missing_paid_prior_is_p0_blocked() -> None:
    client = TestClient(app)
    row = {
        "batch_id": 1,
        "candidate_id": 11,
        "instrument_id": 1001,
        "symbol": "000001",
        "limit_up_stage": 1,
        "ingest_mode": "external_ths_model",
        "contract_audit_status": "passed",
        "memory_age_days": 3,
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
            for day in range(1, 32)
        ],
        "stock_rank": {
            "main_net_inflow_pct_rank": "0.70",
            "large_order_net_inflow_pct_rank": "0.68",
            "super_large_order_net_inflow_pct_rank": "0.60",
        },
    }

    response = client.post("/score", json={"row": row})

    assert response.status_code == 200
    contract = response.json()["structured_output"]["contract"]
    assert contract["memory_hit_8pct_score"] is None
    assert contract["memory_state"] == "blocked_data_gap"
    assert contract["publication_state"] == "blocked"
    assert "missing_paid_ths_prior" in contract["hard_block_reasons"]
    assert "source_gap:missing_paid_ths_prior" in contract["source_gap_codes"]


def test_candidate_memory_public_draft_source_is_p0_blocked() -> None:
    client = TestClient(app)
    row = {
        "latest_batch_id": 1,
        "latest_candidate_id": 11,
        "instrument_id": 1001,
        "symbol": "000001",
        "p_limit_up": "0.62",
        "p_limit_up_source": "public_draft",
        "ingest_mode": "public_limitup_draft",
        "memory_age_days": 3,
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
            for day in range(1, 32)
        ],
        "stock_rank": {
            "main_net_inflow_pct_rank": "0.70",
            "large_order_net_inflow_pct_rank": "0.68",
            "super_large_order_net_inflow_pct_rank": "0.60",
        },
    }

    response = client.post("/score", json={"row": row})

    assert response.status_code == 200
    contract = response.json()["structured_output"]["contract"]
    assert contract["memory_state"] == "blocked_data_gap"
    assert contract["publication_state"] == "blocked"
    assert "public_limitup_draft_not_allowed" in contract["hard_block_reasons"]
    assert "missing_paid_ths_prior" in contract["hard_block_reasons"]


def test_candidate_memory_missing_calendar_age_is_p0_blocked_not_target_window_fallback() -> None:
    client = TestClient(app)
    row = {
        "batch_id": 1,
        "candidate_id": 11,
        "instrument_id": 1001,
        "symbol": "000001",
        "p_limit_up": "0.62",
        "p_limit_up_source": "paid_ths_prior",
        "target_window_days": 30,
        "ingest_mode": "external_ths_model",
        "contract_audit_status": "passed",
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
            for day in range(1, 32)
        ],
        "stock_rank": {
            "main_net_inflow_pct_rank": "0.70",
            "large_order_net_inflow_pct_rank": "0.68",
            "super_large_order_net_inflow_pct_rank": "0.60",
        },
    }

    response = client.post("/score", json={"row": row})

    assert response.status_code == 200
    contract = response.json()["structured_output"]["contract"]
    assert contract["memory_state"] == "blocked_data_gap"
    assert contract["memory_hit_8pct_score"] is None
    assert contract["memory_age_days"] is None
    assert "missing_trading_calendar_memory_age" in contract["hard_block_reasons"]
    assert "source_gap:missing_trading_calendar_memory_age" in contract["source_gap_codes"]


def test_candidate_memory_invalid_daily_ohlc_path_is_p0_blocked() -> None:
    row = _strong_second_wave_row(memory_age_days=8)
    row["daily_bars"][-1]["high_price"] = "10.40"

    response = TestClient(app).post("/score", json={"row": row})

    assert response.status_code == 200
    contract = response.json()["structured_output"]["contract"]
    assert contract["memory_state"] == "blocked_data_gap"
    assert contract["memory_hit_8pct_score"] is None
    assert contract["publication_state"] == "blocked"
    assert "missing_daily_price_path" in contract["hard_block_reasons"]
    assert "source_gap:daily_ohlc_invalid" in contract["source_gap_codes"]


def test_candidate_memory_fresh_candidate_cannot_be_reactivated() -> None:
    response = TestClient(app).post("/score", json={"row": _strong_second_wave_row(memory_age_days=1)})

    assert response.status_code == 200
    contract = response.json()["structured_output"]["contract"]
    assert contract["memory_hit_8pct_score"] is not None
    assert float(contract["score_breakdown"]["second_wave_setup_score"]) >= 70
    assert contract["memory_state"] != "memory_reactivated"
    assert contract["memory_state"] == "memory_active"


def test_candidate_memory_reactivation_requires_mature_memory_age() -> None:
    response = TestClient(app).post("/score", json={"row": _strong_second_wave_row(memory_age_days=8)})

    assert response.status_code == 200
    contract = response.json()["structured_output"]["contract"]
    assert contract["memory_hit_8pct_score"] is not None
    assert float(contract["score_breakdown"]["second_wave_setup_score"]) >= 70
    assert contract["structure_evidence_count"] >= 2
    assert contract["memory_state"] == "memory_reactivated"
