from __future__ import annotations

from datetime import datetime, timezone

from hot_candidates_model_service.pipeline import run_hot_full_pipeline
from hot_candidates_model_service.postgres_repository import HotPostgresWritePlanBuilder


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
        "auction_snapshot": {"auction_price": "7.33", "available_at": "2026-06-08T01:25:05Z"},
        "daily_bars": [
            {"trading_day": f"2026-05-{d:02d}", "open_price": "6.8", "high_price": "7.4", "low_price": "6.6", "close_price": "7.2", "available_at": "2026-06-08T00:30:00Z"}
            for d in range(1, 22)
        ],
        "stock_rank": {"main_net_inflow_pct_rank": "0.82", "available_at": "2026-06-08T01:24:50Z"},
        "market_regime_context": {"available_at": "2026-06-08T01:24:00Z"},
        "teacher_calibration": {"p60_70": {"sample_count": 160, "bucket_realized_rate": "0.62"}},
    }


def test_postgres_write_plan_targets_only_decision_hot_domain_and_keeps_first_snapshot_immutable() -> None:
    pipeline = run_hot_full_pipeline(
        {"row": _row(), "observations": [{"observe_time": "2026-06-08T02:00:00Z", "latest_price": "7.45", "high_since_entry": "7.5", "low_since_entry": "7.28"}]},
        as_of_time_utc=datetime(2026, 6, 8, 1, 26, tzinfo=timezone.utc),
    )
    statements = HotPostgresWritePlanBuilder().build(pipeline)
    joined_sql = "\n".join(statement.sql for statement in statements)
    assert "decision_hot.hot_initial_decision_snapshot_v1" in joined_sql
    assert "ON CONFLICT (initial_snapshot_id) DO NOTHING" in joined_sql
    assert "decision_hot.hot_observation_snapshot_v1" in joined_sql
    assert "ON CONFLICT (hot_case_id, observe_seq) DO NOTHING" in joined_sql
    assert "decision_memory" not in joined_sql
    assert "decision_ambush" not in joined_sql
    # Phase 7 production rule: pending outcome must not generate an evolution sample.
    assert pipeline["outcome_label"]["label_maturity_status"] == "pending"
    assert not any(statement.name == "insert_evolution_sample" for statement in statements)

    matured = run_hot_full_pipeline(
        {"row": _row(), "trade_day_index": 5, "observations": [{"observe_time": "2026-06-11T02:00:00Z", "latest_price": "7.98", "high_since_entry": "7.98", "low_since_entry": "7.28"}]},
        as_of_time_utc=datetime(2026, 6, 8, 1, 26, tzinfo=timezone.utc),
    )
    matured_statements = HotPostgresWritePlanBuilder().build(matured)
    assert matured["outcome_label"]["label_maturity_status"] == "mature"
    assert any(statement.name == "insert_evolution_sample" for statement in matured_statements)
    assert any(statement.name == "upsert_research_sample_pool" for statement in statements)
    assert "decision_hot.hot_research_sample_pool_v1" in joined_sql
