from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient

from ambush_watchlist_model_service.main import app


def test_ambush_healthz_probe() -> None:
    response = TestClient(app).get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "ambush-watchlist-model-service"}


def _bars() -> list[dict[str, str]]:
    closes = [
        "12.0",
        "11.7",
        "11.35",
        "11.0",
        "10.55",
        "10.15",
        "9.85",
        "9.62",
        "9.45",
        "9.38",
        "9.44",
        "9.58",
        "9.75",
        "9.95",
        "10.12",
        "10.28",
        "10.42",
        "10.55",
        "10.66",
        "10.76",
    ]
    return [
        {
            "trading_day": f"2026-05-{index + 1:02d}",
            "open_price": close,
            "high_price": str(float(close) * 1.012),
            "low_price": str(float(close) * 0.988),
            "close_price": close,
            "amount": "60000000",
            "volume": "6000000",
            "turnover_rate": "2.5",
            "raw_payload_id": str(index + 1),
        }
        for index, close in enumerate(closes)
    ]


def _bars_with_duplicate_lineage() -> list[dict[str, str]]:
    rows = _bars()
    for row in rows:
        row["raw_payload_id"] = "88"
    return rows


def _fresh_turn_bars() -> list[dict[str, str]]:
    start = date(2026, 1, 1)
    closes: list[float] = []
    for index in range(117):
        closes.append(12.0 - index * 0.020)
    closes.extend([9.40, 9.62, 9.74])
    rows: list[dict[str, str]] = []
    for index, close in enumerate(closes):
        high_ratio = 1.006 if index >= 117 else 1.012
        low_ratio = 0.986 if index >= 117 else 0.988
        volume = 1_250_000 if index == 118 else 1_000_000
        rows.append(
            {
                "trading_day": str(start + timedelta(days=index)),
                "open_price": str(close * 0.995),
                "high_price": str(close * high_ratio),
                "low_price": str(close * low_ratio),
                "close_price": str(close),
                "amount": str(close * volume),
                "volume": str(volume),
                "turnover_rate": "2.5",
                "raw_payload_id": str(5000 + index),
            }
        )
    return rows


def test_ambush_deep_analysis_returns_structured_jarvis_payload() -> None:
    client = TestClient(app)
    feature_response = client.post(
        "/dragon/window-feature",
        json={
            "symbol": "000001",
            "bars": _bars(),
            "window_days": 20,
            "as_of_trading_day": "2026-05-21",
        },
    )
    assert feature_response.status_code == 200
    feature = feature_response.json()
    l2_response = client.post(
        "/dragon/l2-candidate",
        json={
            "instrument": {
                "symbol": "000001",
                "is_suspended": False,
                "is_delisting_risk": False,
                "is_st": False,
                "listing_days": 100,
            },
            "best_feature": feature,
            "bars": _bars(),
            "as_of_trading_day": "2026-05-21",
        },
    )
    assert l2_response.status_code == 200
    deep_response = client.post(
        "/dragon/deep-analysis",
        json={
            "instrument": {"symbol": "000001"},
            "best_feature": feature,
            "l2_candidate": l2_response.json(),
            "bars": _bars(),
            "stock_rank": {"main_net_inflow": "1000000"},
            "theme_ranks": [{"rank_no": 20, "theme_name": "测试板块"}],
            "as_of_trading_day": "2026-05-21",
        },
    )
    assert deep_response.status_code == 200
    body = deep_response.json()
    assert body["model_name"] == "ambush_watchlist"
    assert body["jarvis_payload"]["schema_version"] == "jarvis_model_payload_v1"


def test_ambush_window_feature_blocks_missing_open_price() -> None:
    client = TestClient(app)
    bars = _bars()
    bars[-1].pop("open_price")

    response = client.post(
        "/dragon/window-feature",
        json={
            "symbol": "000001",
            "bars": bars,
            "window_days": 20,
            "as_of_trading_day": "2026-05-21",
        },
    )

    assert response.status_code == 200
    feature = response.json()
    assert feature["pass_l1_gate"] is False
    assert "blocked_price_data_invalid" in feature["block_reasons"]
    assert feature["dragon_shape_score"] is None


def test_ambush_l2_blocks_special_treatment_stock() -> None:
    client = TestClient(app)
    feature_response = client.post(
        "/dragon/window-feature",
        json={
            "symbol": "000001",
            "bars": _bars(),
            "window_days": 20,
            "as_of_trading_day": "2026-05-21",
        },
    )
    assert feature_response.status_code == 200

    response = client.post(
        "/dragon/l2-candidate",
        json={
            "instrument": {
                "symbol": "000001",
                "is_suspended": False,
                "is_delisting_risk": False,
                "is_st": True,
                "listing_days": 300,
            },
            "best_feature": feature_response.json(),
            "bars": _bars(),
            "as_of_trading_day": "2026-05-21",
        },
    )

    assert response.status_code == 200
    l2_candidate = response.json()
    assert l2_candidate["l2_status"] == "blocked"
    assert "blocked_special_treatment" in l2_candidate["block_reasons"]


def test_ambush_v11_valley_turn_and_transition_audit_contract() -> None:
    client = TestClient(app)
    bars = _fresh_turn_bars()
    instrument = {
        "instrument_id": 1,
        "symbol": "000001",
        "exchange": "SZSE",
        "asset_type": "A_SHARE",
        "is_active": True,
    }

    valley_response = client.post(
        "/ambush/valley-watch",
        json={"instrument": instrument, "bars": bars, "as_of_trading_day": "2026-04-30"},
    )
    assert valley_response.status_code == 200
    valley = valley_response.json()["structured_output"]["valley_watch"]
    assert valley["valley_status"] == "valley_watch"
    assert float(valley["close_to_trough_pct"]) <= 6

    turn_response = client.post(
        "/ambush/effective-turn-candidate",
        json={
            "instrument": instrument,
            "valley_watch": valley,
            "bars": bars,
            "as_of_trading_day": "2026-04-30",
        },
    )
    assert turn_response.status_code == 200
    turn = turn_response.json()["structured_output"]["effective_turn_candidate"]
    assert turn["l1_status"] == "accepted"
    assert turn["shape_type"] in {"first_rebound", "second_turn", "base_breakout"}
    assert turn["effective_turn_age_days"] <= 2
    assert float(turn["post_turn_return_pct"]) <= 6

    audit_response = client.post(
        "/ambush/pool-transition-audit",
        json={"instrument": instrument, "valley_watch": valley, "effective_turn_candidate": turn},
    )
    assert audit_response.status_code == 200
    audit = audit_response.json()["structured_output"]["transition_audit"]
    assert audit["from_pool"] == "valley_watch_pool"
    assert audit["to_pool"] == "effective_turn_pool"
    assert audit["trigger_event"] == "effective_turn_anchor_detected"


def test_ambush_v11_valley_data_gap_blocks_turn_transition() -> None:
    client = TestClient(app)
    bars = _fresh_turn_bars()
    instrument = {
        "instrument_id": 1,
        "symbol": "000001",
        "exchange": "SZSE",
        "asset_type": "A_SHARE",
        "is_active": True,
        "has_trade_calendar": False,
    }

    valley_response = client.post(
        "/ambush/valley-watch",
        json={"instrument": instrument, "bars": bars, "as_of_trading_day": "2026-04-30"},
    )
    assert valley_response.status_code == 200
    valley = valley_response.json()["structured_output"]["valley_watch"]
    assert valley["valley_status"] == "data_blocked"
    assert "trading_calendar_missing" in valley["source_gap_codes"]

    turn_response = client.post(
        "/ambush/effective-turn-candidate",
        json={
            "instrument": instrument,
            "valley_watch": valley,
            "bars": bars,
            "as_of_trading_day": "2026-04-30",
        },
    )
    assert turn_response.status_code == 200
    turn = turn_response.json()["structured_output"]["effective_turn_candidate"]
    assert turn["l1_status"] == "rejected"
    assert turn["reject_reason_codes"] == ["trading_calendar_missing"]
    assert "effective_turn_anchor_day" not in turn

    audit_response = client.post(
        "/ambush/pool-transition-audit",
        json={
            "instrument": instrument,
            "valley_watch": valley,
            "effective_turn_candidate": {
                "symbol": "000001",
                "instrument_id": 1,
                "l1_status": "accepted",
                "effective_turn_anchor_day": "2026-04-29",
                "effective_turn_age_days": 1,
                "snapshot_type": "close_confirmed",
            },
        },
    )
    assert audit_response.status_code == 200
    audit = audit_response.json()["structured_output"]["transition_audit"]
    assert audit["decision_result"] == "not_created"


def test_ambush_v11_valley_invalidated_does_not_create_accepted_turn() -> None:
    client = TestClient(app)
    bars = _fresh_turn_bars()
    instrument = {
        "instrument_id": 1,
        "symbol": "000001",
        "exchange": "SZSE",
        "asset_type": "A_SHARE",
        "is_active": True,
    }
    valley = {
        "trade_date": "2026-04-30",
        "symbol": "000001",
        "instrument_id": 1,
        "valley_status": "valley_invalidated",
        "source_gap_codes": [],
        "invalidation_reason_codes": ["support_broken"],
    }

    turn_response = client.post(
        "/ambush/effective-turn-candidate",
        json={
            "instrument": instrument,
            "valley_watch": valley,
            "bars": bars,
            "as_of_trading_day": "2026-04-30",
        },
    )

    assert turn_response.status_code == 200
    turn = turn_response.json()["structured_output"]["effective_turn_candidate"]
    assert turn["l1_status"] == "rejected"
    assert turn["reject_reason_codes"] == ["valley_status_not_eligible"]
    assert "effective_turn_anchor_day" not in turn


def test_ambush_v11_evidence_level_cap_blocks_l1_over_scoring() -> None:
    client = TestClient(app)
    feature = {
        "symbol": "000001",
        "window_days": 60,
        "decline_maturity_score": "100",
        "bottom_stabilization_score": "100",
        "early_turn_up_score": "100",
        "dragon_shape_score": "100",
        "false_reversal_risk_pre": "10",
        "distance_from_trough": "0.02",
        "feature_hash": "feature-hash-v11",
    }
    l2_candidate = {
        "l2_status": "blocked",
        "avg_turnover_20d": "2.5",
        "daily_data_completeness": "1.000000",
        "liquidity_check": "passed",
        "block_reasons": ["blocked_low_liquidity"],
    }
    effective_turn = {
        "l1_status": "accepted",
        "turn_freshness_score": "100",
        "late_rebound_penalty": "0",
    }

    response = client.post(
        "/dragon/deep-analysis",
        json={
            "instrument": {"instrument_id": 1, "symbol": "000001"},
            "best_feature": feature,
            "l2_candidate": l2_candidate,
            "effective_turn_candidate": effective_turn,
            "bars": _fresh_turn_bars(),
            "stock_rank": {"main_net_inflow": "1000000"},
            "theme_ranks": [{"rank_no": 1, "theme_name": "test-board"}],
            "news_context": {"impact_score": 80},
            "market_context": {"market_context_score": 80},
            "as_of_trading_day": "2026-04-30",
        },
    )

    assert response.status_code == 200
    analysis = response.json()["structured_output"]["analysis"]
    assert analysis["evidence_level"] == "L1_EFFECTIVE_TURN"
    assert float(analysis["dragon_priority_score"]) <= 59
    assert analysis["dragon_state"] == "dragon_failed"


def test_ambush_deep_analysis_evidence_refs_are_deduplicated() -> None:
    client = TestClient(app)
    feature = {
        "symbol": "000001",
        "window_days": 60,
        "decline_maturity_score": "80",
        "bottom_stabilization_score": "78",
        "early_turn_up_score": "76",
        "dragon_shape_score": "75",
        "false_reversal_risk_pre": "20",
        "distance_from_trough": "0.08",
        "feature_hash": "feature-hash-duplicate-lineage",
    }
    l2_candidate = {
        "l2_status": "passed",
        "avg_turnover_20d": "2.5",
        "daily_data_completeness": "1.000000",
        "liquidity_check": "passed",
        "block_reasons": [],
    }

    response = client.post(
        "/dragon/deep-analysis",
        json={
            "instrument": {"symbol": "000001"},
            "best_feature": feature,
            "l2_candidate": l2_candidate,
            "bars": _bars_with_duplicate_lineage(),
            "stock_rank": {"main_net_inflow": "1000000"},
            "theme_ranks": [{"rank_no": 1, "theme_name": "test-board"}],
            "as_of_trading_day": "2026-05-21",
        },
    )

    assert response.status_code == 200
    analysis = response.json()["structured_output"]["analysis"]
    assert analysis["evidence_refs"] == [88]



def test_ambush_ready_requires_strict_false_reversal_risk_and_minimum_daily_completeness() -> None:
    client = TestClient(app)
    base_feature = {
        "symbol": "000001",
        "window_days": 60,
        "decline_maturity_score": "100",
        "bottom_stabilization_score": "100",
        "early_turn_up_score": "100",
        "dragon_shape_score": "100",
        "false_reversal_risk_pre": "50",
        "distance_from_trough": "0.08",
        "feature_hash": "feature-hash",
    }
    base_l2 = {
        "l2_status": "passed",
        "avg_turnover_20d": "2.5",
        "daily_data_completeness": "1.000000",
        "liquidity_check": "passed",
        "block_reasons": [],
    }
    payload = {
        "instrument": {"symbol": "000001"},
        "best_feature": base_feature,
        "l2_candidate": base_l2,
        "effective_turn_candidate": {
            "l1_status": "accepted",
            "turn_freshness_score": "100",
            "late_rebound_penalty": "0",
        },
        "bars": _bars(),
        "stock_rank": {"main_net_inflow": "1000000"},
        "theme_ranks": [{"rank_no": 1, "theme_name": "test-board"}],
        "news_context": {"impact_score": 80},
        "market_context": {"market_context_score": 80},
        "as_of_trading_day": "2026-05-21",
    }
    risk_response = client.post("/dragon/deep-analysis", json=payload)
    assert risk_response.status_code == 200
    risk_analysis = risk_response.json()["structured_output"]["analysis"]
    assert float(risk_analysis["dragon_head_score"]) >= 72
    assert risk_analysis["dragon_state"] != "dragon_ready"

    minimum_complete_payload = {
        **payload,
        "best_feature": {**base_feature, "false_reversal_risk_pre": "20"},
        "l2_candidate": {**base_l2, "daily_data_completeness": "0.950000"},
    }
    minimum_complete_response = client.post("/dragon/deep-analysis", json=minimum_complete_payload)
    assert minimum_complete_response.status_code == 200
    minimum_complete_analysis = minimum_complete_response.json()["structured_output"]["analysis"]
    assert minimum_complete_analysis["evidence_level"] == "L4_DRAGON_READY"
    assert minimum_complete_analysis["dragon_state"] == "dragon_ready"

    incomplete_payload = {
        **payload,
        "best_feature": {**base_feature, "false_reversal_risk_pre": "20"},
        "l2_candidate": {**base_l2, "daily_data_completeness": "0.940000"},
    }
    incomplete_response = client.post("/dragon/deep-analysis", json=incomplete_payload)
    assert incomplete_response.status_code == 200
    incomplete_analysis = incomplete_response.json()["structured_output"]["analysis"]
    assert incomplete_analysis["evidence_level"] == "L2_FILTER_PASSED"
    assert float(incomplete_analysis["dragon_priority_score"]) <= 69
    assert incomplete_analysis["dragon_state"] == "dragon_turning_up"

    ready_payload = {
        **payload,
        "best_feature": {**base_feature, "false_reversal_risk_pre": "20"},
    }
    ready_response = client.post("/dragon/deep-analysis", json=ready_payload)
    assert ready_response.status_code == 200
    ready_analysis = ready_response.json()["structured_output"]["analysis"]
    assert ready_analysis["evidence_level"] == "L4_DRAGON_READY"
    assert ready_analysis["dragon_state"] == "dragon_ready"

    defensive_payload = {
        **ready_payload,
        "market_context": {
            "features": {
                "risk_regime": "defensive",
                "breadth_down_count": "1500",
                "total_count": "2000",
            },
            "data_quality": "ready",
        },
    }
    defensive_response = client.post("/dragon/deep-analysis", json=defensive_payload)
    assert defensive_response.status_code == 200
    defensive_analysis = defensive_response.json()["structured_output"]["analysis"]
    assert defensive_analysis["dragon_state"] == "dragon_confirming"
    assert defensive_analysis["market_defensive_headwind"] is True


def test_ambush_missing_moneyflow_is_gap_not_synthetic_weak_score() -> None:
    client = TestClient(app)
    feature = {
        "symbol": "000001",
        "window_days": 60,
        "decline_maturity_score": "80",
        "bottom_stabilization_score": "78",
        "early_turn_up_score": "76",
        "dragon_shape_score": "75",
        "false_reversal_risk_pre": "20",
        "distance_from_trough": "0.08",
        "feature_hash": "feature-hash-no-moneyflow",
    }
    l2_candidate = {
        "l2_status": "passed",
        "avg_turnover_20d": "2.5",
        "daily_data_completeness": "1.000000",
        "liquidity_check": "passed",
        "block_reasons": [],
    }

    response = client.post(
        "/dragon/deep-analysis",
        json={
            "instrument": {"symbol": "000001"},
            "best_feature": feature,
            "l2_candidate": l2_candidate,
            "effective_turn_candidate": {
                "l1_status": "accepted",
                "turn_freshness_score": "80",
                "late_rebound_penalty": "0",
            },
            "bars": _bars(),
            "stock_rank": None,
            "theme_ranks": [{"rank_no": 10, "theme_name": "test-board"}],
            "as_of_trading_day": "2026-05-21",
        },
    )

    assert response.status_code == 200
    analysis = response.json()["structured_output"]["analysis"]
    assert "moneyflow_missing" in analysis["source_gap_codes"]
    assert analysis["source_gap_count"] >= 1
    assert analysis["source_gap_p0_count"] == 0
    assert analysis["evidence_level"] == "L3_DEEP_CONFIRMED"
    assert analysis["dragon_state"] != "dragon_ready"
    assert analysis["mild_capital_probe_score"] is not None


def test_ambush_deep_analysis_consumes_nested_market_and_news_context() -> None:
    client = TestClient(app)
    feature = {
        "symbol": "000001",
        "window_days": 60,
        "decline_maturity_score": "88",
        "bottom_stabilization_score": "84",
        "early_turn_up_score": "82",
        "dragon_shape_score": "81",
        "false_reversal_risk_pre": "18",
        "distance_from_trough": "0.05",
        "feature_hash": "feature-hash-real-context",
    }
    l2_candidate = {
        "l2_status": "passed",
        "avg_turnover_20d": "2.5",
        "daily_data_completeness": "1.000000",
        "liquidity_check": "passed",
        "block_reasons": [],
    }

    response = client.post(
        "/dragon/deep-analysis",
        json={
            "instrument": {"instrument_id": 1, "symbol": "000001"},
            "best_feature": feature,
            "l2_candidate": l2_candidate,
            "effective_turn_candidate": {
                "l1_status": "accepted",
                "turn_freshness_score": "92",
                "late_rebound_penalty": "0",
            },
            "bars": _bars(),
            "stock_rank": {"main_net_inflow": "1000000"},
            "theme_ranks": [{"rank_no": 3, "theme_name": "test-board"}],
            "news_context": {"impact_score": "0.72", "direction_confidence": "0.88"},
            "market_context": {
                "features": {
                    "risk_regime": "risk_on",
                    "vix_session_change_pct": "-1.2",
                },
                "data_quality": "ready",
            },
            "as_of_trading_day": "2026-05-21",
        },
    )

    assert response.status_code == 200
    analysis = response.json()["structured_output"]["analysis"]
    assert analysis["news_event_score"] == "72.000000"
    assert analysis["market_context_score"] == "78.000000"
    assert analysis["dragon_state"] == "dragon_ready"
    assert analysis["evidence_level"] == "L4_DRAGON_READY"
    assert "news_event_missing" not in analysis["source_gap_codes"]
    assert "market_context_missing" not in analysis["source_gap_codes"]


def test_ambush_deep_analysis_consumes_mixed_cross_market_snapshot() -> None:
    client = TestClient(app)
    feature = {
        "symbol": "000001",
        "window_days": 60,
        "decline_maturity_score": "88",
        "bottom_stabilization_score": "84",
        "early_turn_up_score": "82",
        "dragon_shape_score": "81",
        "false_reversal_risk_pre": "18",
        "distance_from_trough": "0.05",
        "feature_hash": "feature-hash-mixed-market",
    }
    l2_candidate = {
        "l2_status": "passed",
        "avg_turnover_20d": "2.5",
        "daily_data_completeness": "1.000000",
        "liquidity_check": "passed",
        "block_reasons": [],
    }

    response = client.post(
        "/dragon/deep-analysis",
        json={
            "instrument": {"instrument_id": 1, "symbol": "000001"},
            "best_feature": feature,
            "l2_candidate": l2_candidate,
            "effective_turn_candidate": {
                "l1_status": "accepted",
                "turn_freshness_score": "92",
                "late_rebound_penalty": "0",
            },
            "bars": _bars(),
            "stock_rank": {"main_net_inflow": "1000000"},
            "theme_ranks": [{"rank_no": 3, "theme_name": "test-board"}],
            "news_context": {"impact_score": "0.72", "direction_confidence": "0.88"},
            "market_context": {
                "features": {
                    "risk_regime": "mixed",
                    "vix_session_change_pct": "3.8",
                    "usdcnh_session_change_pct": "0.3",
                },
                "data_quality": "ready",
            },
            "as_of_trading_day": "2026-05-21",
        },
    )

    assert response.status_code == 200
    analysis = response.json()["structured_output"]["analysis"]
    assert analysis["market_context_score"] == "55.000000"
    assert analysis["liquidity_tradability_score"] == "100.000000"
    assert "market_context_missing" not in analysis["source_gap_codes"]
