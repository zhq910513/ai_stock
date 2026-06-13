from __future__ import annotations

from fastapi.testclient import TestClient

from candidate_memory_model_service.main import app


client = TestClient(app)


def _bars() -> list[dict]:
    bars: list[dict] = []
    for i in range(1, 31):
        if i <= 15:
            close = 10.0 + i * 0.015
            high = close + 0.10
            low = 9.7 + i * 0.01
            amount = 100_000_000
        elif i <= 24:
            close = 10.25 + (i - 15) * 0.01
            high = close + 0.08
            low = 10.05 + (i - 15) * 0.012
            amount = 90_000_000
        else:
            close = 10.35 + (i - 24) * 0.045
            high = close + 0.09
            low = 10.18 + (i - 24) * 0.025
            amount = 130_000_000
        bars.append(
            {
                "trading_day": f"2026-05-{i:02d}",
                "open_price": f"{close - 0.03:.2f}",
                "high_price": f"{high:.2f}",
                "low_price": f"{low:.2f}",
                "close_price": f"{close:.2f}",
                "amount": str(amount),
                "volume": "10000000",
            }
        )
    return bars


def _strong_row() -> dict:
    return {
        "symbol": "002354",
        "name": "测试股份",
        "source_model": "hot_candidates",
        "first_source_signal_id": "hot-sig-001",
        "first_source_case_id": "hot-case-001",
        "first_selected_date": "2026-05-10",
        "first_outcome_label": "direction_success_execution_missed",
        "first_model_score": "78",
        "p_limit_up": "0.68",
        "memory_entity_id": "mem-002354-001",
        "memory_age_days": 12,
        "ttl_days": 30,
        "ttl_remaining_days": 18,
        "ttl_effective_days": 30,
        "daily_bars": _bars(),
        "moneyflow_feature": {
            "moneyflow_delta_3d_score": 76,
            "moneyflow_delta_5d_score": 73,
            "moneyflow_turning_point_score": 82,
            "capital_outflow_decay_score": 80,
            "intraday_support_flow_score": 68,
        },
        "sector_theme_feature": {
            "sector_strength_delta_3d_score": 75,
            "sector_strength_delta_5d_score": 74,
            "relative_sector_rank_change_score": 70,
            "sector_limit_up_breadth_score": 72,
            "theme_heat_recovery_score": 80,
            "theme_leader_confirmation_score": 66,
        },
        "market_risk_appetite_score": 70,
        "tradability_status": "tradable",
        "entry_stage": "pullback_confirmed_entry",
        "pullback_confirm_price": "10.58",
        "events": [
            {
                "event_id": "evt-1",
                "event_type": "industry_policy",
                "available_at": "2026-06-01T09:35:00+00:00",
                "relevance_score": 82,
                "source_reliability": 85,
                "novelty_score": 78,
                "importance_score": 80,
                "theme_tags": ["AI应用"],
            },
            {
                "event_id": "evt-posthoc",
                "event_type": "post_limitup_review",
                "available_at": "2026-06-01T16:10:00+00:00",
                "relevance_score": 100,
                "source_reliability": 100,
                "novelty_score": 100,
                "importance_score": 100,
            },
        ],
    }


def test_seed_and_entity_preserve_hot_lineage_but_do_not_create_signal() -> None:
    response = client.post("/production/seed/build", json={"row": _strong_row(), "as_of_time_utc": "2026-06-01T10:00:00+00:00"})
    assert response.status_code == 200
    seed = response.json()["structured_output"]["memory_seed"]
    assert seed["seed_status"] == "accepted"
    assert seed["source_model"] == "hot_candidates"
    assert "direction_success_execution_missed" in seed["seed_reasons"]

    response = client.post("/production/entity/build", json={"row": {**_strong_row(), "seed": seed}, "as_of_time_utc": "2026-06-01T10:00:00+00:00"})
    assert response.status_code == 200
    entity = response.json()["structured_output"]["memory_entity"]
    assert entity["memory_status"] in {"observing", "decaying", "near_expiry"}
    assert entity["guardrails"]["memory_entity_is_not_signal"] is True
    assert entity["guardrails"]["new_activation_requires_new_signal_id"] is True


def test_pre_signal_uses_only_ex_ante_events_and_tracks_post_hoc_separately() -> None:
    response = client.post("/production/pre-signal/window", json={"row": _strong_row(), "as_of_time_utc": "2026-06-01T10:00:00+00:00"})
    assert response.status_code == 200
    window = response.json()["structured_output"]["pre_signal_feature_window"]
    assert window["ex_ante_event_count"] == 1
    assert window["post_hoc_event_count"] == 1
    assert "evt-1" in window["ex_ante_event_refs"]
    assert "evt-posthoc" in window["post_hoc_event_refs"]
    assert window["guardrails"]["post_hoc_events_excluded_from_pre_signal_score"] is True
    assert "theme_second_catalyst" in window["pre_signal_types"]


def test_strong_pre_signal_can_pass_activation_and_release_gate() -> None:
    response = client.post("/production/pre-signal/detect", json={"row": _strong_row(), "as_of_time_utc": "2026-06-01T10:00:00+00:00"})
    assert response.status_code == 200
    pre_case = response.json()["structured_output"]["pre_signal_case"]
    assert pre_case["status"] == "pre_signal_detected"

    response = client.post("/production/activation/evaluate", json={"row": {**_strong_row(), "pre_signal_case": pre_case}, "as_of_time_utc": "2026-06-01T10:00:00+00:00"})
    assert response.status_code == 200
    activation = response.json()["structured_output"]["activation_case"]
    assert activation["activation_status"] == "activation_ready"
    assert float(activation["activation_quality_score"]) >= 68

    response = client.post("/production/release-gate/evaluate", json={"row": {**_strong_row(), "activation_case": activation}, "as_of_time_utc": "2026-06-01T10:00:00+00:00"})
    assert response.status_code == 200
    release = response.json()["structured_output"]["release_gate"]
    assert release["release_gate_state"] == "official_signal_passed"
    assert release["memory_signal_id"].startswith("memsig-")
    assert release["guardrails"]["hot_signal_id_is_never_reused"] is True


def test_duplicate_active_signal_blocks_release_gate() -> None:
    row = {**_strong_row(), "active_memory_signal_exists": True}
    response = client.post("/production/release-gate/evaluate", json={"row": row, "as_of_time_utc": "2026-06-01T10:00:00+00:00"})
    assert response.status_code == 200
    release = response.json()["structured_output"]["release_gate"]
    assert release["release_gate_state"] == "research_only_blocked"
    assert "duplicate_active_memory_signal" in release["hard_block_reasons"]


def test_expired_ttl_cannot_be_official_but_remains_researchable() -> None:
    row = {**_strong_row(), "ttl_remaining_days": 0, "memory_status": "expired"}
    response = client.post("/production/release-gate/evaluate", json={"row": row, "as_of_time_utc": "2026-06-01T10:00:00+00:00"})
    assert response.status_code == 200
    release = response.json()["structured_output"]["release_gate"]
    assert release["recommendation_eligibility"] == "research_only_activation"
    assert "memory_entity_not_active" in release["hard_block_reasons"]
    assert "ttl_not_healthy_for_official_signal" in release["hard_block_reasons"]


def test_buy_point_requires_release_and_breakout_or_pullback_confirmation() -> None:
    release = client.post("/production/release-gate/evaluate", json={"row": _strong_row(), "as_of_time_utc": "2026-06-01T10:00:00+00:00"}).json()["structured_output"]["release_gate"]
    response = client.post("/production/buy-point/evaluate", json={"row": {**_strong_row(), "release_gate": release}, "as_of_time_utc": "2026-06-01T10:01:00+00:00"})
    assert response.status_code == 200
    buy_point = response.json()["structured_output"]["buy_point"]
    assert buy_point["buy_point_state"] == "buy_point_confirmed"
    assert buy_point["reference_entry_price"] == "10.58"

    waiting = {**_strong_row(), "entry_stage": "pre_signal_waiting", "release_gate": release}
    response = client.post("/production/buy-point/evaluate", json={"row": waiting, "as_of_time_utc": "2026-06-01T10:01:00+00:00"})
    buy_point = response.json()["structured_output"]["buy_point"]
    assert buy_point["reference_entry_price"] is None
    assert "waiting_for_breakout_or_pullback_confirmation" in buy_point["block_reasons"]


def test_outcome_separates_second_wave_from_new_independent_cycle() -> None:
    base = {
        "memory_signal_id": "memsig-1",
        "memory_entity_id": "mem-1",
        "activation_case_id": "act-1",
        "symbol": "002354",
        "label_maturity_status": "mature",
        "next_limit_up_hit": True,
        "tradable_success": True,
        "pre_signal_lead_days": 4,
    }
    response = client.post("/production/outcomes/mature", json={"row": base, "as_of_time_utc": "2026-06-08T15:30:00+00:00"})
    outcome = response.json()["structured_output"]["outcome_label"]
    assert outcome["outcome_label"] == "second_wave_success"
    assert outcome["include_official_success_rate"] is True

    response = client.post("/production/outcomes/mature", json={"row": {**base, "new_independent_cycle": True}, "as_of_time_utc": "2026-06-08T15:30:00+00:00"})
    outcome = response.json()["structured_output"]["outcome_label"]
    assert outcome["outcome_label"] == "new_independent_cycle"
    assert outcome["include_official_success_rate"] is False


def test_evolution_uses_mature_outcome_only_and_blocks_pending() -> None:
    pending = {
        "memory_signal_id": "memsig-2",
        "memory_entity_id": "mem-2",
        "activation_case_id": "act-2",
        "symbol": "002354",
        "label_maturity_status": "pending",
        "next_limit_up_hit": True,
    }
    response = client.post("/production/evolution/build", json={"row": pending, "as_of_time_utc": "2026-06-08T15:30:00+00:00"})
    evolution = response.json()["structured_output"]["evolution_sample"]
    assert evolution["evolution_state"] == "blocked"
    assert "outcome_not_mature" in evolution["hard_block_reasons"]

    mature = {**pending, "label_maturity_status": "mature", "pre_signal_lead_days": 5, "next_limit_up_hit": True}
    response = client.post("/production/evolution/build", json={"row": mature, "as_of_time_utc": "2026-06-08T15:30:00+00:00"})
    evolution = response.json()["structured_output"]["evolution_sample"]
    assert evolution["evolution_state"] == "ready_for_offline_evolution"
    assert "activation_rule_positive_sample" in evolution["evolution_labels"]
    assert "pre_signal_effective_lead_candidate" in evolution["evolution_labels"]


def test_up_reason_attribution_keeps_pre_signal_confirmed_and_post_hoc_separate() -> None:
    response = client.post(
        "/production/up-reason/build",
        json={
            "row": {
                "memory_signal_id": "memsig-3",
                "memory_entity_id": "mem-3",
                "symbol": "002354",
                "pre_signal_reason_codes": ["capital_memory_reactivation"],
                "confirmed_up_reason_codes": ["sector_resonance_return"],
                "post_hoc_explanation_codes": ["post_limitup_media_review"],
                "reason_confidence_score": 76,
            },
            "as_of_time_utc": "2026-06-08T15:30:00+00:00",
        },
    )
    attribution = response.json()["structured_output"]["up_reason_attribution"]
    assert attribution["primary_up_reason"] == "capital_memory_reactivation"
    assert attribution["guardrails"]["post_hoc_explanation_never_used_for_ex_ante_scoring"] is True
