from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient

from ambush_watchlist_model_service.main import app


def _phase2_bars(*, adjusted: bool = True, runaway: bool = False) -> list[dict[str, object]]:
    start = date(2026, 1, 1)
    closes: list[float] = []
    for index in range(35):
        closes.append(12.0 - index * 0.075)
    for index in range(8):
        closes.append(9.38 + ((index % 2) - 0.5) * 0.03)
    if runaway:
        closes += [9.95, 10.45, 10.90, 11.20]
    else:
        closes += [9.50, 9.72]
    rows: list[dict[str, object]] = []
    for index, close in enumerate(closes):
        trading_day = start + timedelta(days=index)
        if index >= len(closes) - 2:
            open_price = close * 0.988
            high_price = close * 1.003
            low_price = open_price * 0.998
            volume = 1_200_000
        else:
            open_price = close * (0.995 if index % 2 == 0 else 1.001)
            high_price = max(open_price, close) * 1.008
            low_price = min(open_price, close) * 0.992
            volume = 850_000
        row: dict[str, object] = {
            "symbol": "000001",
            "trading_day": trading_day.isoformat(),
            "open_price": f"{open_price:.4f}",
            "high_price": f"{high_price:.4f}",
            "low_price": f"{low_price:.4f}",
            "close_price": f"{close:.4f}",
            "volume": str(volume),
            "amount": f"{close * volume:.2f}",
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


def _weekly_bars() -> list[dict[str, object]]:
    start = date(2025, 10, 1)
    rows: list[dict[str, object]] = []
    for index in range(16):
        close = 13.0 - index * 0.22 if index < 12 else 10.3 + (index - 12) * 0.05
        trading_day = start + timedelta(days=index * 7)
        open_price = close * 0.995
        high_price = close * 1.020
        low_price = close * 0.980
        row: dict[str, object] = {
            "symbol": "000001",
            "trading_day": trading_day.isoformat(),
            "open_price": f"{open_price:.4f}",
            "high_price": f"{high_price:.4f}",
            "low_price": f"{low_price:.4f}",
            "close_price": f"{close:.4f}",
            "volume": "5000000",
            "amount": f"{close * 5000000:.2f}",
        }
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


def _instrument() -> dict[str, object]:
    return {"instrument_id": 1, "symbol": "000001", "exchange": "SZSE", "asset_type": "A_SHARE", "is_active": True}


def _pattern_match(*, hard_negative: int = 5) -> dict[str, object]:
    return {
        "pattern_library_version": "unit_pattern_library",
        "positive_valley_similarity": "85.000000",
        "false_bottom_similarity": "10.000000",
        "hard_negative_similarity": f"{hard_negative}.000000",
        "shape_edge_score": "73.000000" if hard_negative < 70 else "8.000000",
    }


def test_phase2_valley_watch_pool_promotes_mature_adjusted_valley() -> None:
    client = TestClient(app)
    bars = _phase2_bars()
    as_of = bars[-1]["trading_day"]
    response = client.post(
        "/ambush/phase2/valley-watch-pool",
        json={
            "instrument": _instrument(),
            "bars": bars,
            "weekly_bars": _weekly_bars(),
            "pattern_match": _pattern_match(),
            "as_of_trading_day": as_of,
            "window_days": 45,
        },
    )
    assert response.status_code == 200
    valley = response.json()["structured_output"]["valley_watch"]
    assert valley["pool_state"] == "valley_watch"
    assert float(valley["valley_maturity_score"]) >= 62
    assert valley["formula_governance"]["not_a_signal"] is True
    assert valley["price_adjustment_mode"] == "adjusted_ohlc"


def test_phase2_effective_turn_anchor_moves_to_effective_turn_pool() -> None:
    client = TestClient(app)
    bars = _phase2_bars()
    as_of = bars[-1]["trading_day"]
    pipeline = client.post(
        "/ambush/phase2/run",
        json={
            "instrument": _instrument(),
            "bars": bars,
            "weekly_bars": _weekly_bars(),
            "pattern_match": _pattern_match(),
            "as_of_trading_day": as_of,
            "window_days": 45,
        },
    )
    assert pipeline.status_code == 200
    phase2 = pipeline.json()["structured_output"]["phase2"]
    valley = phase2["valley_watch"]
    turn = phase2["effective_turn_anchor"]
    transition = phase2["transition_audit"]
    assert valley["pool_state"] == "valley_watch"
    assert turn["l1_status"] == "accepted"
    assert turn["pool_target"] == "effective_turn_pool"
    assert turn["anchor_type"] in {"first_turn_day", "second_turn_day", "horizontal_compression_breakout"}
    assert transition["decision_result"] == "created"
    assert transition["to_pool"] == "effective_turn_pool"


def test_phase2_hard_negative_similarity_blocks_valley_promotion() -> None:
    client = TestClient(app)
    bars = _phase2_bars()
    response = client.post(
        "/ambush/phase2/valley-watch-pool",
        json={
            "instrument": _instrument(),
            "bars": bars,
            "weekly_bars": _weekly_bars(),
            "pattern_match": _pattern_match(hard_negative=92),
            "as_of_trading_day": bars[-1]["trading_day"],
            "window_days": 45,
        },
    )
    assert response.status_code == 200
    valley = response.json()["structured_output"]["valley_watch"]
    assert valley["pool_state"] == "valley_invalidated"
    assert "hard_negative_similarity_dominates" in valley["block_reason_codes"]


def test_phase2_missing_adjusted_ohlc_is_research_only_not_official() -> None:
    client = TestClient(app)
    bars = _phase2_bars(adjusted=False)
    response = client.post(
        "/ambush/phase2/valley-watch-pool",
        json={
            "instrument": _instrument(),
            "bars": bars,
            "weekly_bars": _weekly_bars(),
            "pattern_match": _pattern_match(),
            "as_of_trading_day": bars[-1]["trading_day"],
            "window_days": 45,
        },
    )
    assert response.status_code == 200
    valley = response.json()["structured_output"]["valley_watch"]
    assert valley["pool_state"] in {"research_only", "not_qualified"}
    assert "adjusted_ohlc_missing_research_only" in valley["source_gap_codes"]
    assert "adjusted_ohlc_required_for_official_scoring" in valley["research_only_reason_codes"]


def test_phase2_runaway_rebound_is_rejected_by_effective_turn() -> None:
    client = TestClient(app)
    bars = _phase2_bars(runaway=True)
    response = client.post(
        "/ambush/phase2/effective-turn-anchor",
        json={
            "instrument": _instrument(),
            "bars": bars,
            "valley_watch": {
                "pool_state": "valley_watch",
                "primary_trough_day": "2026-02-06",
                "primary_trough_low": "9.2266",
                "window_days": 49,
                "source_gap_codes": [],
                "false_rebound_risk": "20.000000",
            },
            "as_of_trading_day": bars[-1]["trading_day"],
            "window_days": 49,
        },
    )
    assert response.status_code == 200
    turn = response.json()["structured_output"]["effective_turn_anchor"]
    assert turn["l1_status"] == "rejected"
    assert set(turn["reject_reason_codes"]) & {"runaway_from_trough", "post_turn_return_too_high", "late_rebound_without_compression_breakout"}
