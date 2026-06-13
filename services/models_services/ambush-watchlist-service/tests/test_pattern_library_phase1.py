from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient

from ambush_watchlist_model_service.main import app


def _phase1_bars(*, adjusted: bool = True, future_rebound: bool = True) -> list[dict[str, object]]:
    start = date(2026, 1, 1)
    closes: list[float] = []
    for index in range(45):
        closes.append(12.0 - index * 0.055)
    for index in range(15):
        closes.append(9.55 + index * 0.006)
    if future_rebound:
        for index in range(20):
            closes.append(9.65 + index * 0.085)
    else:
        for index in range(20):
            closes.append(9.65 - index * 0.025)
    rows: list[dict[str, object]] = []
    for index, close in enumerate(closes):
        trading_day = start + timedelta(days=index)
        open_price = close * (0.995 if index % 2 == 0 else 1.003)
        high_price = max(open_price, close) * 1.012
        low_price = min(open_price, close) * 0.988
        volume = 1_000_000 + (index % 7) * 20_000
        if future_rebound and index > 60:
            volume = 1_250_000
        row: dict[str, object] = {
            "symbol": "000001",
            "trading_day": trading_day.isoformat(),
            "open_price": f"{open_price:.4f}",
            "high_price": f"{high_price:.4f}",
            "low_price": f"{low_price:.4f}",
            "close_price": f"{close:.4f}",
            "volume": str(volume),
            "amount": f"{close * volume:.2f}",
            "turnover_rate": "2.3",
            "available_at": f"{trading_day.isoformat()}T15:05:00+08:00",
        }
        if adjusted:
            row.update(
                {
                    "adjusted_open_price": row["open_price"],
                    "adjusted_high_price": row["high_price"],
                    "adjusted_low_price": row["low_price"],
                    "adjusted_close_price": row["close_price"],
                }
            )
        rows.append(row)
    return rows


def test_source_capability_audit_blocks_official_without_adjusted_ohlc() -> None:
    client = TestClient(app)
    good = client.post(
        "/ambush/source-capability-audit",
        json={"provider": "unit", "bars": _phase1_bars(adjusted=True), "instruments": [{"symbol": "000001"}]},
    )
    assert good.status_code == 200
    good_body = good.json()
    assert good_body["quality_status"] == "ready"
    assert good_body["usable_for_pattern_library"] is True
    assert good_body["usable_for_online_scoring"] is True

    bad = client.post(
        "/ambush/source-capability-audit",
        json={"provider": "unit", "bars": _phase1_bars(adjusted=False), "instruments": [{"symbol": "000001"}]},
    )
    assert bad.status_code == 200
    bad_body = bad.json()
    assert bad_body["usable_for_pattern_library"] is False
    assert "adjusted_ohlc_missing" in bad_body["source_gap_codes"]


def test_shape_signature_uses_multi_channel_adjusted_sequence_without_future_rows() -> None:
    client = TestClient(app)
    bars = _phase1_bars(adjusted=True)
    as_of = date(2026, 1, 1) + timedelta(days=59)
    response = client.post(
        "/ambush/shape-signature",
        json={"symbol": "000001", "bars": bars, "as_of_trading_day": as_of.isoformat(), "window_days": 60},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["official_scoring_allowed"] is True
    assert body["price_adjustment_mode"] == "adjusted_ohlc"
    assert len(body["embedding_vector"]) == 24 * 9
    assert set(body["channels"].keys()) >= {
        "close_path",
        "typical_price_path",
        "high_envelope_path",
        "low_envelope_path",
        "volume_path",
        "upper_shadow_path",
        "close_position_path",
    }
    assert body["formula_governance"]["future_data_policy"] == "Uses only bars up to as_of_trading_day."


def test_pattern_match_penalizes_hard_negative_similarity() -> None:
    client = TestClient(app)
    bars = _phase1_bars(adjusted=True)
    as_of = date(2026, 1, 1) + timedelta(days=59)
    signature = client.post(
        "/ambush/shape-signature",
        json={"symbol": "000001", "bars": bars, "as_of_trading_day": as_of.isoformat(), "window_days": 60},
    ).json()
    same_vector = signature["embedding_vector"]
    far_vector = [1.0 - float(value) for value in same_vector]
    response = client.post(
        "/ambush/pattern-prototype-match",
        json={
            "current_signature": signature,
            "prototypes": [
                {"prototype_id": "P1", "prototype_type": "strong_positive", "embedding_vector": same_vector, "quality_score": 95},
                {"prototype_id": "N1", "prototype_type": "hard_negative", "embedding_vector": same_vector, "quality_score": 90},
                {"prototype_id": "N2", "prototype_type": "easy_negative", "embedding_vector": far_vector, "quality_score": 60},
            ],
            "top_k": 3,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["positive_valley_similarity"] == "100.000000"
    assert body["hard_negative_similarity"] == "100.000000"
    assert float(body["shape_edge_score"]) < 5
    assert body["formula_governance"]["score_formula"].startswith("shape_edge_score")


def test_historical_sample_label_collects_positive_and_hard_negative_samples() -> None:
    client = TestClient(app)
    anchor_day = date(2026, 1, 1) + timedelta(days=59)
    positive_response = client.post(
        "/ambush/historical-valley-sample-label",
        json={"symbol": "000001", "bars": _phase1_bars(adjusted=True, future_rebound=True), "anchor_day": anchor_day.isoformat()},
    )
    assert positive_response.status_code == 200
    positive = positive_response.json()
    assert positive["sample_label"] in {"strong_positive", "weak_positive"}
    assert positive["direction_success"] is True
    assert float(positive["rebound_quality_score"]) >= 50

    negative_response = client.post(
        "/ambush/historical-valley-sample-label",
        json={"symbol": "000001", "bars": _phase1_bars(adjusted=True, future_rebound=False), "anchor_day": anchor_day.isoformat()},
    )
    assert negative_response.status_code == 200
    negative = negative_response.json()
    assert negative["sample_label"] in {"hard_negative", "easy_negative"}
    assert negative["direction_success"] is False


def test_three_channel_recall_returns_research_facts_not_official_signal() -> None:
    client = TestClient(app)
    bars = _phase1_bars(adjusted=True)
    as_of = date(2026, 1, 1) + timedelta(days=59)
    signature = client.post(
        "/ambush/shape-signature",
        json={"symbol": "000001", "bars": bars, "as_of_trading_day": as_of.isoformat(), "window_days": 60},
    ).json()
    response = client.post(
        "/ambush/three-channel-recall",
        json={
            "instrument": {"symbol": "000001", "exchange": "SZSE", "asset_type": "A_SHARE"},
            "bars": bars,
            "as_of_trading_day": as_of.isoformat(),
            "prototypes": [
                {"prototype_id": "P1", "prototype_type": "strong_positive", "embedding_vector": signature["embedding_vector"], "quality_score": 95}
            ],
            "market_context": {"risk_regime": "mixed"},
        },
    )
    assert response.status_code == 200
    recall = response.json()["structured_output"]["recall"]
    assert recall["recall_status"] == "recalled"
    assert "shape_similarity_recall" in recall["recall_channels"]
    assert recall["formula_governance"]["not_a_signal"] is True
