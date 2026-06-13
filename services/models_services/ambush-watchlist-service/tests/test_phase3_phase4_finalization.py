from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient

from ambush_watchlist_model_service.main import app


def _instrument() -> dict[str, object]:
    return {"instrument_id": 1, "symbol": "000001", "exchange": "SZSE", "asset_type": "A_SHARE", "is_active": True}


def _bars() -> list[dict[str, object]]:
    start = date(2026, 1, 1)
    closes = [12.0 - i * 0.07 for i in range(35)] + [9.58, 9.55, 9.56, 9.57, 9.60, 9.63, 9.66, 9.70, 9.86, 10.05]
    rows: list[dict[str, object]] = []
    for index, close in enumerate(closes):
        day = start + timedelta(days=index)
        open_price = close * 0.990
        high_price = close * 1.012
        low_price = close * 0.985
        volume = 1_800_000 if index >= len(closes) - 5 else 1_100_000
        row: dict[str, object] = {
            "symbol": "000001",
            "trading_day": day.isoformat(),
            "open_price": f"{open_price:.4f}",
            "high_price": f"{high_price:.4f}",
            "low_price": f"{low_price:.4f}",
            "close_price": f"{close:.4f}",
            "adjusted_open_price": f"{open_price:.4f}",
            "adjusted_high_price": f"{high_price:.4f}",
            "adjusted_low_price": f"{low_price:.4f}",
            "adjusted_close_price": f"{close:.4f}",
            "volume": str(volume),
            "amount": f"{close * volume:.2f}",
            "available_at": f"{day.isoformat()}T15:05:00+08:00",
        }
        rows.append(row)
    # post-signal bars for phase4 outcome
    signal_close = closes[-1]
    for add in range(1, 8):
        close = signal_close * (1 + 0.015 * add)
        day = start + timedelta(days=len(closes) - 1 + add)
        rows.append(
            {
                "symbol": "000001",
                "trading_day": day.isoformat(),
                "open_price": f"{close * 0.99:.4f}",
                "high_price": f"{close * 1.025:.4f}",
                "low_price": f"{close * 0.985:.4f}",
                "close_price": f"{close:.4f}",
                "volume": "2200000",
                "amount": f"{close * 2200000:.2f}",
            }
        )
    return rows


def _valley() -> dict[str, object]:
    return {
        "symbol": "000001",
        "instrument_id": 1,
        "pool_state": "valley_watch",
        "price_adjustment_mode": "adjusted_ohlc",
        "valley_maturity_score": "82.000000",
        "weekly_structure_score": "72.000000",
        "volume_structure_score": "70.000000",
        "bottom_stability_score": "82.000000",
        "false_rebound_risk": "22.000000",
        "hard_negative_similarity": "8.000000",
        "source_gap_codes": [],
        "pattern_library_version": "unit_pattern_library",
    }


def _turn() -> dict[str, object]:
    return {
        "symbol": "000001",
        "instrument_id": 1,
        "l1_status": "accepted",
        "pool_target": "effective_turn_pool",
        "effective_turn_score": "84.000000",
        "turn_freshness_score": "88.000000",
        "support_hold_score": "91.000000",
        "micro_breakout_quality": "86.000000",
        "runaway_risk": "12.000000",
        "upper_shadow_risk": "8.000000",
        "effective_turn_anchor_day": "2026-02-13",
        "source_gap_codes": [],
    }


def _contexts() -> dict[str, dict[str, object]]:
    return {
        "moneyflow_context": {
            "outflow_decay_score": 85,
            "net_inflow_turning_score": 78,
            "intraday_support_flow_score": 76,
        },
        "sector_context": {"sector_relative_strength_score": 76, "sector_breadth_repair_score": 72},
        "market_context": {"market_risk_appetite_score": 74, "limit_up_environment_score": 70},
        "tradability_context": {"tradability_score": 82, "liquidity_score": 80, "tradable_entry_window_score": 84},
    }


def test_phase3_release_gate_creates_official_signal_and_buy_point() -> None:
    client = TestClient(app)
    bars = _bars()
    as_of = bars[44]["trading_day"]
    payload = {
        "instrument": _instrument(),
        "valley_watch": _valley(),
        "effective_turn_anchor": _turn(),
        "bars": bars[:45],
        "as_of_trading_day": as_of,
        **_contexts(),
    }
    response = client.post("/ambush/phase3/run", json=payload)
    assert response.status_code == 200
    phase3 = response.json()["structured_output"]["phase3"]
    assert phase3["deep_confirmation"]["deep_state"] == "deep_confirmed"
    assert phase3["release_gate"]["release_decision"] == "passed"
    assert phase3["signal_fact"]["signal_state"] == "official_signal"
    assert phase3["buy_point"]["valid_for_evaluation"] is True
    assert phase3["not_investment_advice"] is True


def test_phase3_missing_moneyflow_keeps_research_only_and_blocks_release() -> None:
    client = TestClient(app)
    bars = _bars()[:45]
    response = client.post(
        "/ambush/phase3/run",
        json={
            "instrument": _instrument(),
            "valley_watch": _valley(),
            "effective_turn_anchor": _turn(),
            "bars": bars,
            "sector_context": {"sector_relative_strength_score": 80, "sector_breadth_repair_score": 80},
            "market_context": {"market_risk_appetite_score": 80, "limit_up_environment_score": 80},
            "tradability_context": {"tradability_score": 100, "liquidity_score": 100, "tradable_entry_window_score": 100},
            "as_of_trading_day": bars[-1]["trading_day"],
        },
    )
    assert response.status_code == 200
    phase3 = response.json()["structured_output"]["phase3"]
    assert phase3["deep_confirmation"]["deep_state"] == "research_only"
    assert phase3["release_gate"]["release_decision"] == "blocked"
    assert "moneyflow_context_missing_research_only" in phase3["deep_confirmation"]["research_only_reason_codes"]


def test_phase4_observation_outcome_and_failure_attribution_are_append_only() -> None:
    client = TestClient(app)
    bars = _bars()
    phase3 = client.post(
        "/ambush/phase3/run",
        json={
            "instrument": _instrument(),
            "valley_watch": _valley(),
            "effective_turn_anchor": _turn(),
            "bars": bars[:45],
            "as_of_trading_day": bars[44]["trading_day"],
            **_contexts(),
        },
    ).json()["structured_output"]["phase3"]
    obs = client.post(
        "/ambush/phase4/observation",
        json={
            "signal_fact": phase3["signal_fact"],
            "buy_point": phase3["buy_point"],
            "bars": bars,
            "as_of_trading_day": bars[-1]["trading_day"],
        },
    )
    assert obs.status_code == 200
    observation = obs.json()["structured_output"]["observation"]
    assert observation["append_only"] is True
    assert float(observation["mfe_pct"]) > 8

    out = client.post(
        "/ambush/phase4/outcome",
        json={"signal_fact": phase3["signal_fact"], "buy_point": phase3["buy_point"], "bars": bars, "maturity_days": 7},
    )
    outcome = out.json()["structured_output"]["outcome_label"]
    assert outcome["direction_success"] is True
    assert outcome["append_only"] is True

    attr = client.post(
        "/ambush/phase4/failure-attribution",
        json={
            "signal_fact": phase3["signal_fact"],
            "outcome_label": outcome,
            "release_gate": phase3["release_gate"],
            "deep_confirmation": phase3["deep_confirmation"],
        },
    )
    assert attr.status_code == 200
    attribution = attr.json()["structured_output"]["failure_attribution"]
    assert attribution["append_only"] is True
    assert attribution["evolution_action"] in {"add_to_positive_validation_pool", "add_to_hard_negative_review"}


def test_ambush_lock_candidate_report_is_lockable_for_code_contract_scope() -> None:
    response = TestClient(app).post("/ambush/finalization/lock-candidate", json={"validation_summary": {}})
    assert response.status_code == 200
    report = response.json()["structured_output"]["lock_candidate"]
    assert report["lockable"] is True
    assert report["lock_version"] == "ambush_watchlist_service_v1.0_rc_backend_closure_candidate"
    assert "real provider data replay" in report["not_validated_here"]
