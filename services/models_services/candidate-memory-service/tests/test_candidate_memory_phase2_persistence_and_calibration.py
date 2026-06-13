from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from candidate_memory_model_service.main import app
from candidate_memory_model_service.persistence import MemorySQLiteRepository

client = TestClient(app)


def _bars(days: int = 25) -> list[dict[str, object]]:
    out = []
    base = 10.0
    for i in range(days):
        close = base + i * 0.03
        # last 8 days are compressed near high, matching a memory pre-signal setup
        if i > days - 9:
            close = 10.65 + (i - (days - 8)) * 0.015
        out.append(
            {
                "trading_day": f"2026-05-{i+1:02d}",
                "open": round(close - 0.02, 2),
                "high": round(close + 0.08, 2),
                "low": round(close - 0.07, 2),
                "close": round(close, 2),
                "amount": 10000000 + i * 120000,
            }
        )
    return out


def _active_case(idx: int, *, next_observe_at: str = "2026-06-01T09:55:00+00:00") -> dict[str, object]:
    return {
        "memory_entity_id": f"mem-{idx:04d}",
        "symbol": f"00{2354 + idx % 100:04d}"[-6:],
        "memory_status": "valuable",
        "priority_level": 60 + (idx % 20),
        "next_observe_at": next_observe_at,
        "observe_seq": idx + 1,
        "ttl_remaining_days": 18,
        "ttl_effective_days": 30,
        "daily_bars": _bars(),
        "moneyflow_feature": {
            "moneyflow_delta_3d_score": 76,
            "moneyflow_delta_5d_score": 72,
            "moneyflow_turning_point_score": 78,
            "capital_outflow_decay_score": 75,
        },
        "sector_theme_feature": {
            "sector_strength_delta_3d_score": 72,
            "sector_strength_delta_5d_score": 70,
            "relative_sector_rank_change_score": 68,
            "theme_heat_recovery_score": 74,
        },
        "market_risk_appetite_score": 68,
        "events": [
            {
                "event_id": f"evt-{idx}",
                "event_type": "theme_news",
                "available_at": "2026-06-01T09:40:00+00:00",
                "relevance_score": 78,
                "source_reliability": 80,
                "novelty_score": 75,
                "importance_score": 72,
            }
        ],
    }


def test_event_standardization_blocks_future_and_missing_available_at_from_ex_ante() -> None:
    response = client.post(
        "/production/events/standardize",
        json={
            "as_of_time_utc": "2026-06-01T10:00:00+00:00",
            "row": {
                "memory_entity_id": "mem-evt",
                "symbol": "002354",
                "events": [
                    {"event_id": "ex-ante", "available_at": "2026-06-01T09:35:00+00:00", "relevance_score": 90, "source_reliability": 90, "novelty_score": 80, "importance_score": 80},
                    {"event_id": "future", "available_at": "2026-06-01T15:30:00+00:00", "relevance_score": 100, "source_reliability": 100, "novelty_score": 100, "importance_score": 100},
                    {"event_id": "missing-time", "relevance_score": 100},
                ],
            },
        },
    )
    assert response.status_code == 200
    batch = response.json()["structured_output"]["event_signal_feature_batch"]
    assert batch["ex_ante_event_count"] == 1
    assert batch["post_hoc_event_count"] == 1
    features = {item["event_id"]: item for item in batch["features"]}
    assert features["future"]["excluded_from_pre_signal_score"] is True
    assert features["missing-time"]["visibility_class"] == "not_visible"
    assert "source_gap:event_missing_available_at" in batch["source_gap_codes"]


def test_registry_dynamic_frequency_escalates_pre_signal_and_activation_cases() -> None:
    pre_signal = client.post(
        "/production/registry/upsert",
        json={"as_of_time_utc": "2026-06-01T10:00:00+00:00", "row": {"memory_entity_id": "mem-pre", "symbol": "002354", "memory_status": "valuable", "pre_signal_status": "pre_signal_detected"}},
    ).json()["structured_output"]["active_case_registry"]
    assert pre_signal["tracking_pool"] == "pre_signal_case_pool"
    assert pre_signal["observe_frequency_seconds"] == 300
    assert pre_signal["priority_level"] >= 90

    activation = client.post(
        "/production/registry/upsert",
        json={"as_of_time_utc": "2026-06-01T10:00:00+00:00", "row": {"memory_entity_id": "mem-act", "symbol": "002354", "memory_status": "valuable", "activation_status": "activation_ready"}},
    ).json()["structured_output"]["active_case_registry"]
    assert activation["tracking_pool"] == "activation_case_pool"
    assert activation["observe_frequency_seconds"] == 180


def test_bulk_observation_handles_1000_due_cases_and_updates_latest_projection() -> None:
    cases = [_active_case(i) for i in range(1000)]
    response = client.post(
        "/production/observations/bulk",
        json={"as_of_time_utc": "2026-06-01T10:00:00+00:00", "row": {"active_cases": cases}},
    )
    assert response.status_code == 200
    result = response.json()["structured_output"]["bulk_observation_result"]
    assert result["observation_count"] == 1000
    assert result["latest_state_count"] == 1000
    assert result["registry_update_count"] == 1000
    assert result["guardrails"]["bulk_observation_is_append_only"] is True
    assert all(item["next_observe_at"] > result["observe_time"] for item in result["registry_updates"])


def test_sqlite_repository_persists_append_only_observations_and_due_registry() -> None:
    repo = MemorySQLiteRepository()
    try:
        observe_time = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)
        cases = [_active_case(i) for i in range(5)]
        result = client.post(
            "/production/observations/bulk",
            json={"as_of_time_utc": observe_time.isoformat(), "row": {"active_cases": cases}},
        ).json()["structured_output"]["bulk_observation_result"]
        summary = repo.apply_bulk_observation_result(result)
        assert summary["observations_inserted"] == 5
        assert repo.count_rows("memory_observation_snapshot_v1") == 5
        assert repo.count_rows("memory_latest_state_v1") == 5
        assert repo.count_rows("memory_active_case_registry_v1") == 5
        # Repeat same batch: append-only primary keys make duplicates idempotent, latest projection remains upsertable.
        summary = repo.apply_bulk_observation_result(result)
        assert summary["observations_inserted"] == 0
        assert summary["observations_ignored_duplicate"] == 5
    finally:
        repo.close()


def test_matched_control_uplift_requires_control_group_and_reports_incremental_alpha() -> None:
    hot = [{"next_limit_up_hit": i < 18, "time_to_next_limit_up_days": 6 + i % 4} for i in range(30)]
    controls = [{"next_limit_up_hit": i < 9, "time_to_next_limit_up_days": 8 + i % 6} for i in range(30)]
    response = client.post(
        "/production/matched-control/uplift",
        json={"as_of_time_utc": "2026-06-30T15:30:00+00:00", "row": {"segment_key": "same_sector_turnover_vol", "hot_entered_samples": hot, "matched_control_samples": controls}},
    )
    uplift = response.json()["structured_output"]["matched_control_uplift"]
    assert uplift["research_state"] == "valid"
    assert float(uplift["uplift_rate_pct"]) > 0
    assert uplift["guardrails"]["compares_against_matched_controls_not_whole_market"] is True

    insufficient = client.post(
        "/production/matched-control/uplift",
        json={"row": {"hot_entered_samples": hot[:2], "matched_control_samples": controls[:2]}},
    ).json()["structured_output"]["matched_control_uplift"]
    assert insufficient["research_state"] == "sample_insufficient"
    assert "matched_control_sample_insufficient" in insufficient["hard_block_reasons"]


def test_ttl_calibration_uses_only_mature_cutoff_samples_and_excludes_new_cycle() -> None:
    mature = []
    for i in range(25):
        mature.append(
            {
                "memory_signal_id": f"sig-{i}",
                "label_maturity_status": "mature",
                "labeled_at": "2026-06-20T15:30:00+00:00",
                "outcome_label": "second_wave_success" if i < 12 else "second_wave_failed",
                "ttl_expired_at_activation": i < 5,
                "ttl_remaining_days_at_activation": 20 if i >= 18 else 5,
            }
        )
    mature.append({"memory_signal_id": "future", "label_maturity_status": "mature", "labeled_at": "2026-07-20T15:30:00+00:00", "outcome_label": "second_wave_success"})
    mature.append({"memory_signal_id": "new-cycle", "label_maturity_status": "mature", "labeled_at": "2026-06-20T15:30:00+00:00", "outcome_label": "second_wave_success", "new_independent_cycle": True})
    response = client.post(
        "/production/ttl-calibration/build",
        json={"as_of_time_utc": "2026-06-30T16:00:00+00:00", "row": {"current_ttl_days": 30, "calibration_cutoff_time": "2026-06-30T15:30:00+00:00", "mature_outcomes": mature}},
    )
    report = response.json()["structured_output"]["ttl_calibration_report"]
    assert report["mature_sample_count"] == 25
    assert report["excluded_sample_count"] == 2
    assert report["calibration_state"] == "ready_for_review"
    assert report["guardrails"]["uses_cutoff_time_to_prevent_future_leakage"] is True
    assert report["guardrails"]["new_independent_cycle_excluded_from_ttl_success"] is True
