from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from candidate_memory_model_service.main import app
from candidate_memory_model_service.postgres_repository import MemoryPostgresRepository

client = TestClient(app)


def _bars() -> list[dict[str, object]]:
    out = []
    for i in range(18):
        close = 10.0 + i * 0.04
        out.append(
            {
                "trading_day": f"2026-05-{i + 1:02d}",
                "open": round(close - 0.02, 2),
                "high": round(close + 0.08, 2),
                "low": round(close - 0.05, 2),
                "close": round(close, 2),
                "amount": 10_000_000 + i * 150_000,
            }
        )
    return out


def test_source_feature_snapshot_standardizes_wide_data_and_excludes_future_events() -> None:
    response = client.post(
        "/production/source/features/build",
        json={
            "as_of_time_utc": "2026-06-01T10:00:00+00:00",
            "row": {
                "memory_entity_id": "mem-001",
                "symbol": "002354",
                "first_selected_price": "10.00",
                "first_hot_high": "11.00",
                "daily_bars": _bars(),
                "moneyflow_feature": {"moneyflow_delta_3d_score": 82, "available_at": "2026-06-01T09:58:00+00:00"},
                "sector_theme_feature": {"sector_strength_delta_3d_score": 78, "available_at": "2026-06-01T09:57:00+00:00"},
                "events": [
                    {"event_id": "evt-visible", "event_type": "theme_news", "available_at": "2026-06-01T09:50:00+00:00", "importance_score": 80},
                    {"event_id": "evt-future", "event_type": "post_limitup_review", "available_at": "2026-06-01T16:00:00+00:00", "importance_score": 100},
                ],
            },
        },
    )
    assert response.status_code == 200
    snapshot = response.json()["structured_output"]["source_feature_snapshot"]
    assert snapshot["event_signal_feature"]["ex_ante_event_count"] == 1
    assert snapshot["event_signal_feature"]["post_hoc_event_count"] == 1
    assert "evt-visible" in snapshot["event_signal_feature"]["ex_ante_event_refs"]
    assert "evt-future" in snapshot["event_signal_feature"]["post_hoc_event_refs"]
    assert snapshot["guardrails"]["typed_feature_snapshots_feed_pre_signal_not_raw_json"] is True


def test_persistence_plan_keeps_stages_separate_and_blocks_pending_outcome_truth() -> None:
    response = client.post(
        "/production/persistence/plan",
        json={
            "row": {
                "stage_outputs": {
                    "memory_seed": {"memory_seed_id": "seed-1", "symbol": "002354"},
                    "memory_entity": {"memory_entity_id": "mem-001", "symbol": "002354"},
                    "outcome_label": {"outcome_id": "out-1", "memory_entity_id": "mem-001", "symbol": "002354", "label_maturity_status": "pending"},
                    "evolution_sample": {"evolution_state": "blocked", "hard_block_reasons": ["outcome_not_mature"]},
                }
            },
            "as_of_time_utc": "2026-06-01T10:00:00+00:00",
        },
    )
    plan = response.json()["structured_output"]["stage_persistence_plan"]
    assert plan["plan_state"] == "blocked"
    assert "pending_outcome_cannot_be_persisted_as_mature_label" in plan["hard_block_reasons"]
    assert any(row["repository_method"] == "save_memory_seed" for row in plan["planned_writes"])
    assert plan["guardrails"]["production_stages_are_separate_transactions"] is True


def test_pre_signal_threshold_calibration_uses_mature_ex_ante_samples_only() -> None:
    mature = []
    for i in range(8):
        mature.append(
            {
                "sample_id": f"s-{i}",
                "label_maturity_status": "mature",
                "matured_at": "2026-06-10T15:00:00+00:00",
                "pre_signal_visible_before_activation": True,
                "pre_signal_score": 70 + i,
                "pre_signal_types": ["capital_memory_reactivation"],
                "outcome_label": "second_wave_success" if i < 6 else "fake_activation_failure",
            }
        )
    mature.append({"sample_id": "future", "label_maturity_status": "mature", "matured_at": "2026-07-01T00:00:00+00:00", "pre_signal_score": 99, "outcome_label": "second_wave_success"})
    mature.append({"sample_id": "new-cycle", "label_maturity_status": "mature", "matured_at": "2026-06-10T00:00:00+00:00", "pre_signal_score": 95, "outcome_label": "new_independent_cycle"})
    response = client.post(
        "/production/pre-signal/threshold-calibration",
        json={"row": {"calibration_cutoff_time": "2026-06-20T00:00:00+00:00", "mature_samples": mature}},
    )
    report = response.json()["structured_output"]["pre_signal_threshold_calibration"]
    assert report["eligible_sample_count"] == 8
    assert report["excluded_sample_count"] == 2
    assert report["calibration_state"] == "ready_for_shadow_validation"
    assert report["guardrails"]["new_independent_cycle_excluded_from_success"] is True


def test_multi_day_replay_separates_new_cycle_and_flags_future_event_leakage() -> None:
    response = client.post(
        "/production/replay/multi-day",
        json={
            "row": {
                "memory_entity_id": "mem-001",
                "symbol": "002354",
                "first_selected_date": "2026-06-01",
                "limit_up_dates": ["2026-06-12"],
                "new_independent_cycle_dates": ["2026-06-12"],
                "trading_days": [
                    {"trading_day": "2026-06-07", "pre_signal_score": 65, "activation_quality_score": 66, "pre_signal_types": ["sector_resonance_return"]},
                    {"trading_day": "2026-06-08", "pre_signal_score": 80, "activation_quality_score": 75, "future_event_used": True},
                    {"trading_day": "2026-06-09", "pre_signal_score": 75, "activation_quality_score": 73, "tradability_status": "one_word_limit_up"},
                ],
            },
            "as_of_time_utc": "2026-06-20T15:00:00+00:00",
        },
    )
    replay = response.json()["structured_output"]["multi_day_replay_validation"]
    assert replay["outcome_label"] == "new_independent_cycle"
    assert replay["pre_signal_lead_days"] == 5
    assert replay["replay_state"] == "failed_guardrail"
    assert "future_or_post_hoc_event_used:2026-06-08" in replay["guardrail_violations"]
    assert replay["guardrails"]["new_independent_cycle_not_counted_as_memory_success"] is True


def test_phase4_acceptance_check_requires_all_production_chain_items() -> None:
    response = client.post(
        "/production/phase4/acceptance",
        json={
            "row": {
                "checks": {
                    "postgres_stage_transactions": True,
                    "source_feature_standardization": True,
                    "due_case_db_plan": True,
                    "multi_day_replay": True,
                    "pre_signal_threshold_calibration": True,
                    "ex_ante_message_guardrail": True,
                    "new_cycle_exclusion": True,
                }
            }
        },
    )
    acceptance = response.json()["structured_output"]["phase4_acceptance_check"]
    assert acceptance["acceptance_state"] == "pass"
    assert acceptance["phase4_boundary"]["requires_real_environment_replay_before_online_final"] is True


class RecordingCursor:
    def __init__(self) -> None:
        self.statements: list[tuple[str, tuple[object, ...]]] = []
        self.rowcount = 1
        self.description = []

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> None:
        self.statements.append((sql, params))


class RecordingConnection:
    def __init__(self) -> None:
        self.cursor_obj = RecordingCursor()
        self.commits = 0
        self.rollbacks = 0

    def cursor(self) -> RecordingCursor:
        return self.cursor_obj

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def test_postgres_repository_phase4_declares_all_stage_persistence_boundaries() -> None:
    conn = RecordingConnection()
    repo = MemoryPostgresRepository(conn)
    repo.save_activation_case({"activation_case_id": "act-1", "memory_entity_id": "mem-001", "symbol": "002354", "activation_quality_score": 75})
    repo.save_release_gate_and_signal({"memory_entity_id": "mem-001", "activation_case_id": "act-1", "symbol": "002354", "release_gate_state": "official_signal_passed", "memory_signal_id": "memsig-001", "recommendation_eligibility": "official_candidate"})
    repo.save_mature_outcome({"outcome_id": "out-001", "memory_signal_id": "memsig-001", "memory_entity_id": "mem-001", "activation_case_id": "act-1", "symbol": "002354", "label_maturity_status": "mature", "outcome_label": "second_wave_success", "next_limit_up_hit": True, "include_official_success_rate": True})
    sql_text = "\n".join(sql for sql, _ in conn.cursor_obj.statements)
    assert "decision_memory.memory_activation_case_v1" in sql_text
    assert "decision_memory.memory_release_gate_audit_v1" in sql_text
    assert "decision_memory.memory_signal_fact_v1" in sql_text
    assert "decision_memory.memory_outcome_label_v1" in sql_text
    assert "ON CONFLICT" in sql_text
    assert conn.commits == 3
