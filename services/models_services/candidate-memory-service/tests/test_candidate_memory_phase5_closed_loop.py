from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from candidate_memory_model_service.main import app
from candidate_memory_model_service.postgres_repository import MemoryPostgresRepository

client = TestClient(app)


def _bars() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    # Keep the last sessions compressed near a prior high so structure repair and breakout pressure are strong.
    for i in range(24):
        close = 10.0 + min(i, 18) * 0.06
        if i >= 18:
            close = 11.05 + (i - 18) * 0.02
        rows.append(
            {
                "trading_day": f"2026-05-{i + 1:02d}",
                "open": round(close - 0.02, 2),
                "high": round(close + 0.05, 2),
                "low": round(close - 0.04, 2),
                "close": round(close, 2),
                "amount": 10_000_000 + i * 180_000,
            }
        )
    return rows


def _strong_row() -> dict[str, object]:
    return {
        "symbol": "002354",
        "first_source_model": "hot_candidates",
        "first_source_signal_id": "hot-sig-001",
        "first_source_case_id": "hot-case-001",
        "first_selected_date": "2026-05-10",
        "first_outcome_label": "direction_success_execution_missed",
        "first_model_score": 81,
        "p_limit_up": 0.68,
        "memory_entity_id": "mem-002354-001",
        "memory_age_days": 9,
        "ttl_days": 30,
        "ttl_remaining_days": 21,
        "ttl_health_score": 82,
        "memory_value_score": 84,
        "daily_bars": _bars(),
        "price_structure_feature": {
            "platform_compression_score": 86,
            "volatility_compression_score": 78,
            "higher_low_score": 82,
            "support_hold_score": 80,
            "breakout_pressure_score": 88,
            "pullback_health_score": 81,
            "distance_to_previous_hot_high_score": 90,
        },
        "moneyflow_feature": {
            "moneyflow_delta_3d_score": 86,
            "moneyflow_delta_5d_score": 82,
            "moneyflow_turning_point_score": 88,
            "capital_outflow_decay_score": 84,
            "intraday_support_flow_score": 83,
        },
        "sector_theme_feature": {
            "sector_strength_delta_3d_score": 81,
            "sector_strength_delta_5d_score": 78,
            "relative_sector_rank_change_score": 76,
            "sector_limit_up_breadth_score": 74,
            "theme_heat_recovery_score": 83,
            "theme_leader_confirmation_score": 72,
        },
        "events": [
            {
                "event_id": "evt-visible",
                "event_type": "theme_news",
                "available_at": "2026-06-01T09:58:00+00:00",
                "relevance_score": 84,
                "source_reliability": 80,
                "novelty_score": 78,
                "importance_score": 82,
            },
            {
                "event_id": "evt-post-hoc",
                "event_type": "post_limitup_review",
                "available_at": "2026-06-01T16:00:00+00:00",
                "importance_score": 99,
            },
        ],
        "market_risk_appetite_score": 74,
        "fake_activation_risk_score": 18,
        "tradability_status": "tradable",
        "entry_stage": "breakout_confirmed_entry",
        "platform_upper_price": "11.22",
        "label_maturity_status": "mature",
        "next_limit_up_hit": True,
        "tradable_success": True,
        "pre_signal_lead_days": 4,
        "time_to_next_limit_up_days": 3,
        "mfe_pct": 11.2,
        "mae_pct": -1.8,
        "confirmed_up_reason_codes": ["capital_memory_confirmed", "sector_resonance_confirmed"],
        "feature_watermarks": {
            "price_structure": {"watermark": "2026-06-01T09:59:00+00:00"},
            "moneyflow": {"watermark": "2026-06-01T09:59:00+00:00"},
            "sector_theme": {"watermark": "2026-06-01T09:59:00+00:00"},
            "event_signal": {"watermark": "2026-06-01T09:59:00+00:00"},
            "market_sentiment": {"watermark": "2026-06-01T09:59:00+00:00"},
            "tradability": {"watermark": "2026-06-01T09:59:00+00:00"},
        },
    }


def test_phase5_closure_pipeline_reaches_shadow_ready_and_excludes_post_hoc_events() -> None:
    response = client.post(
        "/production/closure/run",
        json={"as_of_time_utc": "2026-06-01T10:00:00+00:00", "row": _strong_row()},
    )
    assert response.status_code == 200, response.text
    closure = response.json()["structured_output"]["closure_pipeline"]
    assert closure["closure_state"] == "closed_ready_for_shadow_evaluation"
    assert closure["stage_states"]["release_gate_state"] == "official_signal_passed"
    assert closure["stage_states"]["buy_point_state"] == "buy_point_confirmed"
    assert closure["stage_states"]["outcome_label"] == "second_wave_success"
    window = closure["outputs"]["pre_signal_feature_window"]
    assert window["ex_ante_event_refs"] == ["evt-visible"]
    assert "evt-post-hoc" in window["post_hoc_event_refs"]
    assert closure["guardrails"]["future_or_post_hoc_events_excluded_from_pre_signal_score"] is True


def test_phase5_failure_attribution_does_not_call_single_case_systematic_failure() -> None:
    response = client.post(
        "/production/failure-attribution/build",
        json={
            "as_of_time_utc": "2026-06-20T15:00:00+00:00",
            "row": {
                "memory_signal_id": "sig-001",
                "memory_entity_id": "mem-001",
                "activation_case_id": "act-001",
                "symbol": "002354",
                "label_maturity_status": "mature",
                "fake_activation_failure": True,
                "breakout_failed": True,
                "fake_activation_risk_score": 82,
                "pre_signal_reason_codes": ["structure_repair_breakout"],
            },
        },
    )
    attribution = response.json()["structured_output"]["failure_attribution"]
    assert attribution["failure_type"] == "fake_activation"
    assert attribution["model_failure_class"] == "model_uncertain_single_case"
    assert attribution["guardrails"]["single_case_never_becomes_systematic_failure"] is True


def test_phase5_shadow_evaluation_uses_mature_ex_ante_and_excludes_new_cycle() -> None:
    samples = []
    for i in range(10):
        samples.append(
            {
                "sample_id": f"s-{i}",
                "label_maturity_status": "mature",
                "matured_at": "2026-06-10T15:00:00+00:00",
                "pre_signal_visible_before_activation": True,
                "candidate_activation_score": 72 + i,
                "baseline_activation_score": 69 + i,
                "outcome_label": "second_wave_success" if i < 8 else "fake_activation_failure",
            }
        )
    samples.append({"sample_id": "new-cycle", "label_maturity_status": "mature", "matured_at": "2026-06-10T15:00:00+00:00", "pre_signal_visible_before_activation": True, "candidate_activation_score": 99, "outcome_label": "new_independent_cycle"})
    samples.append({"sample_id": "future", "label_maturity_status": "mature", "matured_at": "2026-07-01T15:00:00+00:00", "pre_signal_visible_before_activation": True, "candidate_activation_score": 99, "outcome_label": "second_wave_success"})
    response = client.post(
        "/production/model-version/shadow-evaluate",
        json={
            "row": {
                "evaluation_cutoff_time": "2026-06-20T00:00:00+00:00",
                "candidate_model_version": "candidate_memory_v1_candidate_202606",
                "mature_samples": samples,
            }
        },
    )
    report = response.json()["structured_output"]["model_version_shadow_evaluation"]
    assert report["eligible_sample_count"] == 10
    assert report["excluded_sample_count"] == 2
    assert report["evaluation_state"] == "ready_for_manual_promotion_review"
    assert report["guardrails"]["new_independent_cycle_excluded"] is True


def test_phase5_final_acceptance_requires_all_closure_checks() -> None:
    checks = {
        "stage_endpoints_split": True,
        "postgres_stage_repository_contract": True,
        "source_typed_feature_contract": True,
        "due_case_registry_plan": True,
        "feature_watermark_hard_block": True,
        "ex_ante_message_guardrail": True,
        "pre_signal_chain": True,
        "release_gate_guardrails": True,
        "buy_point_direction_execution_split": True,
        "mature_outcome_only_evolution": True,
        "new_independent_cycle_exclusion": True,
        "failure_attribution": True,
        "ttl_calibration": True,
        "threshold_calibration": True,
        "matched_control_uplift": True,
        "multi_day_replay": True,
        "model_version_shadow_evaluation": True,
        "schedule_contract_ready_for_scheduler_v2": True,
    }
    response = client.post("/production/phase5/final-acceptance", json={"row": {"checks": checks}})
    acceptance = response.json()["structured_output"]["phase5_final_acceptance"]
    assert acceptance["acceptance_state"] == "pass"
    assert acceptance["acceptance_boundary"]["backend_model_closure_can_be_frozen_as_rc"] is True
    blocked = client.post("/production/phase5/final-acceptance", json={"row": {"checks": {"stage_endpoints_split": True}}}).json()["structured_output"]["phase5_final_acceptance"]
    assert blocked["acceptance_state"] == "blocked"
    assert "ex_ante_message_guardrail" in blocked["missing_or_failed_checks"]


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


def test_phase5_repository_declares_final_closure_writes() -> None:
    conn = RecordingConnection()
    repo = MemoryPostgresRepository(conn)
    repo.save_up_reason_attribution({"memory_signal_id": "sig-1", "memory_entity_id": "mem-1", "symbol": "002354", "primary_up_reason": "capital_memory_reactivation", "pre_signal_reason_codes": ["capital_memory_reactivation"], "attribution_hash": "h1"})
    repo.save_failure_attribution({"memory_signal_id": "sig-1", "memory_entity_id": "mem-1", "symbol": "002354", "failure_type": "fake_activation", "failure_reason_codes": ["fake_activation_risk_underestimated"], "model_failure_class": "model_uncertain_single_case", "outcome_label": "fake_activation_failure", "attribution_hash": "h2"})
    repo.save_evolution_sample({"memory_signal_id": "sig-1", "memory_entity_id": "mem-1", "symbol": "002354", "evolution_state": "ready_for_offline_evolution", "evolution_labels": ["activation_rule_positive_sample"], "evolution_hash": "h3"})
    repo.save_model_version_shadow_evaluation({"candidate_model_version": "candidate", "baseline_model_version": "baseline", "evaluation_cutoff_time": datetime(2026, 6, 20, tzinfo=timezone.utc), "eligible_sample_count": 10, "candidate_hit_rate_pct": 80, "baseline_hit_rate_pct": 70, "evaluation_state": "ready_for_manual_promotion_review", "evaluation_hash": "h4"})
    sql_text = "\n".join(sql for sql, _ in conn.cursor_obj.statements)
    assert "decision_memory.memory_up_reason_attribution_v1" in sql_text
    assert "decision_memory.memory_failure_attribution_v1" in sql_text
    assert "decision_memory.memory_evolution_sample_v1" in sql_text
    assert "decision_memory.memory_model_version_shadow_evaluation_v1" in sql_text
    assert conn.commits == 4
