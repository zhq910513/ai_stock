from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from candidate_memory_model_service.main import app
from candidate_memory_model_service.postgres_repository import MemoryPostgresRepository

client = TestClient(app)


def test_feature_readiness_blocks_stale_price_and_future_watermark() -> None:
    response = client.post(
        "/production/features/readiness",
        json={
            "as_of_time_utc": "2026-06-01T10:00:00+00:00",
            "row": {
                "stage_code": "activation_evaluate",
                "memory_entity_id": "mem-001",
                "symbol": "002354",
                "feature_watermarks": {
                    "price_structure": {"watermark": "2026-06-01T09:30:00+00:00", "provider": "source.daily_bar"},
                    "moneyflow": {"watermark": "2026-06-01T09:58:00+00:00"},
                    "sector_theme": {"watermark": "2026-06-01T10:05:00+00:00"},
                    "tradability": {"watermark": "2026-06-01T09:59:00+00:00"},
                },
            },
        },
    )
    assert response.status_code == 200
    audit = response.json()["structured_output"]["feature_readiness_audit"]
    assert audit["readiness_state"] == "blocked"
    assert "required_feature_not_fresh:price_structure" in audit["hard_block_reasons"]
    assert "future_feature_watermark:sector_theme" in audit["hard_block_reasons"]
    assert audit["guardrails"]["future_watermark_hard_blocked"] is True


def test_due_observation_plan_uses_only_due_open_registry_rows_and_orders_by_priority() -> None:
    response = client.post(
        "/production/observations/due-plan",
        json={
            "as_of_time_utc": "2026-06-01T10:00:00+00:00",
            "row": {
                "limit": 10,
                "registry_rows": [
                    {"memory_entity_id": "mem-low", "symbol": "002001", "memory_status": "valuable", "next_observe_at": "2026-06-01T09:59:00+00:00", "priority_level": 30},
                    {"memory_entity_id": "mem-high", "symbol": "002002", "memory_status": "valuable", "next_observe_at": "2026-06-01T09:58:00+00:00", "priority_level": 90},
                    {"memory_entity_id": "mem-future", "symbol": "002003", "memory_status": "valuable", "next_observe_at": "2026-06-01T10:30:00+00:00", "priority_level": 99},
                    {"memory_entity_id": "mem-closed", "symbol": "002004", "memory_status": "closed", "next_observe_at": "2026-06-01T09:00:00+00:00", "priority_level": 99},
                ],
                "features_by_entity": {
                    "mem-high": {"daily_bars": [{"close": 10}], "moneyflow_feature": {"moneyflow_delta_3d_score": 88}},
                },
            },
        },
    )
    assert response.status_code == 200
    plan = response.json()["structured_output"]["due_observation_plan"]
    assert plan["due_case_count"] == 2
    assert [case["memory_entity_id"] for case in plan["due_cases"]] == ["mem-high", "mem-low"]
    assert {row["reason"] for row in plan["skipped_rows"]} == {"not_due", "closed_status"}
    assert plan["guardrails"]["only_registry_due_cases_are_observed"] is True


def test_pre_limitup_analysis_counts_only_ex_ante_pre_signals_and_lead_days() -> None:
    response = client.post(
        "/production/pre-limitup/analyze",
        json={
            "as_of_time_utc": "2026-06-20T16:00:00+00:00",
            "row": {
                "memory_entity_id": "mem-001",
                "memory_signal_id": "sig-001",
                "symbol": "002354",
                "next_limit_up_date": "2026-06-12",
                "lookback_window_days": 10,
                "pre_signal_cases": [
                    {"detected_at": "2026-06-09T10:00:00+00:00", "pre_signal_types": ["capital_memory_reactivation"], "pre_signal_strength_score": 78},
                    {"detected_at": "2026-06-13T10:00:00+00:00", "pre_signal_types": ["post_hoc_noise"], "pre_signal_strength_score": 99},
                ],
                "matched_failed_cases": [{"id": 1}, {"id": 2}],
                "matched_success_cases": [{"id": 3}],
            },
        },
    )
    analysis = response.json()["structured_output"]["pre_limitup_signal_analysis"]
    assert analysis["analysis_state"] == "valid_ex_ante_pre_signal"
    assert analysis["lead_days_before_limit_up"] == 3
    assert analysis["excluded_post_hoc_case_count"] == 1
    assert analysis["pre_signal_types"] == ["capital_memory_reactivation"]
    assert float(analysis["false_positive_rate_bucket"]) > 60


def test_schedule_contract_declares_multi_frequency_requirements_and_model_truth_boundary() -> None:
    response = client.post("/production/schedule/contract", json={"row": {}})
    assert response.status_code == 200
    contract = response.json()["structured_output"]["model_schedule_contract"]
    stage_codes = {stage["stage_code"] for stage in contract["stages"]}
    assert {"pre_signal_detect", "activation_evaluate", "outcome_mature", "ttl_calibration"}.issubset(stage_codes)
    assert contract["frequency_matrix"]["pre_signal_case"] == "3-5m"
    assert contract["scheduler_boundaries"]["scheduler_cannot_store_model_scores_or_labels"] is True


class RecordingCursor:
    def __init__(self) -> None:
        self.statements: list[tuple[str, tuple[object, ...]]] = []
        self.description = [("memory_entity_id",), ("symbol",), ("tracking_pool",), ("priority_level",), ("next_observe_at",), ("last_observe_at",), ("observe_frequency_seconds",), ("memory_status",), ("budget_class",), ("close_reason",)]
        self.rowcount = 1

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> None:
        self.statements.append((sql, params))

    def fetchall(self) -> list[tuple[object, ...]]:
        return [("mem-001", "002354", "pre_signal_case_pool", 90, datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc), None, 300, "valuable", "high", None)]


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


def test_postgres_repository_contract_uses_upsert_append_only_and_due_query() -> None:
    conn = RecordingConnection()
    repo = MemoryPostgresRepository(conn)
    due = repo.get_due_active_cases(as_of_time_utc=datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc), limit=5)
    assert due[0]["memory_entity_id"] == "mem-001"
    repo.upsert_registry({"memory_entity_id": "mem-001", "symbol": "002354", "tracking_pool": "pre_signal_case_pool", "priority_level": 90, "next_observe_at": datetime(2026, 6, 1, 10, 5, tzinfo=timezone.utc), "observe_frequency_seconds": 300, "memory_status": "valuable"})
    repo.append_observation({"observation_id": "obs-001", "memory_entity_id": "mem-001", "symbol": "002354", "observe_seq": 1, "observe_time": datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc), "memory_value_score": 80, "pre_signal_score": 75, "fake_activation_risk_score": 20, "expectation_state": "pre_signal_strengthening"})
    sql_text = "\n".join(sql for sql, _ in conn.cursor_obj.statements)
    assert "decision_memory.memory_active_case_registry_v1" in sql_text
    assert "ON CONFLICT(memory_entity_id) DO UPDATE" in sql_text
    assert "decision_memory.memory_observation_snapshot_v1" in sql_text
    assert "ON CONFLICT(observation_id) DO NOTHING" in sql_text
    assert conn.commits >= 2
