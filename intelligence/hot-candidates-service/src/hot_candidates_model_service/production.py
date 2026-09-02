from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from hot_candidates_model_service.logic import build_candidate_source_analysis, build_hot_candidate_v1_contract, utc_run_id
from hot_candidates_model_service.pipeline import (
    build_hot_buy_point_decision,
    build_hot_failure_attribution,
    build_hot_first_output_distortion_analysis,
    build_hot_outcome_label,
    build_hot_signal_fact,
    build_hot_source_visibility_audit,
)
from hot_candidates_model_service.research import (
    HOT_MODEL_REFINED_VERSION,
    build_hot_evolution_sample,
    build_hot_research_contract,
)
from hot_candidates_model_service.calibration import build_hot_research_sample_pool_record

HOT_PRODUCTION_API_VERSION = "hot_candidates_production_phase7_v1"


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    return value


def _now(value: datetime | None = None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _build_initial_research(row: dict[str, Any], *, as_of_time_utc: datetime, run_id: str | None = None) -> dict[str, Any]:
    run_id = run_id or utc_run_id("hot-prod")
    analysis = build_candidate_source_analysis(row, candidate_source="hot_candidates", run_id=run_id)
    legacy_contract = build_hot_candidate_v1_contract(analysis, as_of_time_utc=as_of_time_utc)
    research = build_hot_research_contract(row, legacy_analysis=analysis, legacy_contract=legacy_contract, as_of_time_utc=as_of_time_utc)
    audit = build_hot_source_visibility_audit(row, decision_time=as_of_time_utc)
    research["source_visibility_audit"] = audit
    # Production hard rule: no official signal when P0 lineage is missing or future leaked.
    if audit.get("hard_block_codes"):
        gate = research["release_gate"]
        gate["gate_status"] = "blocked"
        gate["official_signal_allowed"] = False
        gate["recommendation_eligibility"] = "not_eligible"
        gate["signal_stage"] = "research_sample"
        gate["block_reasons"] = sorted(set(list(gate.get("block_reasons") or []) + list(audit.get("hard_block_codes") or [])))
    return {"analysis": analysis, "legacy_contract": legacy_contract, "research_contract": research}


def build_hot_case_build_result(payload: dict[str, Any], *, as_of_time_utc: datetime | None = None) -> dict[str, Any]:
    now = _now(as_of_time_utc)
    row = payload.get("row") if isinstance(payload.get("row"), dict) else payload
    built = _build_initial_research(row, as_of_time_utc=now, run_id=payload.get("run_id"))
    research = built["research_contract"]
    return _jsonable(
        {
            "contract_kind": "hot_cases_build_result_v1",
            "production_api_version": HOT_PRODUCTION_API_VERSION,
            "model_version": HOT_MODEL_REFINED_VERSION,
            "hot_cycle": research.get("hot_cycle"),
            "hot_decision_case": research.get("hot_decision_case"),
            "initial_decision_snapshot": research.get("initial_decision_snapshot"),
            "source_visibility_audit": research.get("source_visibility_audit"),
            "db_cycle_resolution_required": True,
            "db_cycle_resolution_contract": build_hot_cycle_db_resolution_contract(research.get("hot_decision_case") or {}),
            "legacy_analysis": built["analysis"],
            "legacy_contract": built["legacy_contract"],
        }
    )


def build_hot_score_compute_result(payload: dict[str, Any], *, as_of_time_utc: datetime | None = None) -> dict[str, Any]:
    now = _now(as_of_time_utc)
    row = payload.get("row") if isinstance(payload.get("row"), dict) else payload
    built = _build_initial_research(row, as_of_time_utc=now, run_id=payload.get("run_id"))
    research = built["research_contract"]
    return _jsonable(
        {
            "contract_kind": "hot_scores_compute_result_v1",
            "production_api_version": HOT_PRODUCTION_API_VERSION,
            "hot_case_id": (research.get("hot_decision_case") or {}).get("hot_case_id"),
            "feature_matrix": (built["legacy_contract"] or {}).get("feature_matrix"),
            "stage_scores": research.get("stage_scores"),
            "source_visibility_audit": research.get("source_visibility_audit"),
            "score_state": "blocked" if (research.get("source_visibility_audit") or {}).get("hard_block_codes") else "scored",
        }
    )


def build_hot_release_gate_result(payload: dict[str, Any], *, as_of_time_utc: datetime | None = None) -> dict[str, Any]:
    now = _now(as_of_time_utc)
    row = payload.get("row") if isinstance(payload.get("row"), dict) else payload
    built = _build_initial_research(row, as_of_time_utc=now, run_id=payload.get("run_id"))
    research = built["research_contract"]
    signal = build_hot_signal_fact(research, selected_at=now)
    research_pool = build_hot_research_sample_pool_record({"research_contract": research, "hot_signal": signal}, generated_at=now)
    return _jsonable(
        {
            "contract_kind": "hot_release_gate_evaluate_result_v1",
            "production_api_version": HOT_PRODUCTION_API_VERSION,
            "hot_case_id": (research.get("hot_decision_case") or {}).get("hot_case_id"),
            "release_gate": research.get("release_gate"),
            "hot_signal": signal,
            "research_sample_pool": research_pool,
            "source_visibility_audit": research.get("source_visibility_audit"),
            "official_publish_only_here": True,
        }
    )


def build_hot_buy_point_result(payload: dict[str, Any], *, as_of_time_utc: datetime | None = None) -> dict[str, Any]:
    now = _now(as_of_time_utc)
    row = payload.get("row") if isinstance(payload.get("row"), dict) else payload
    built = _build_initial_research(row, as_of_time_utc=now, run_id=payload.get("run_id"))
    research = built["research_contract"]
    signal = build_hot_signal_fact(research, selected_at=now)
    buy_point = build_hot_buy_point_decision(row, research, calculated_at=now)
    buy_point["hot_signal_id"] = signal.get("hot_signal_id")
    return _jsonable(
        {
            "contract_kind": "hot_buy_point_evaluate_result_v1",
            "production_api_version": HOT_PRODUCTION_API_VERSION,
            "hot_case_id": (research.get("hot_decision_case") or {}).get("hot_case_id"),
            "hot_signal": signal,
            "buy_point": buy_point,
            "source_visibility_audit": research.get("source_visibility_audit"),
            "buy_point_can_freeze_reference": buy_point.get("is_first_valid") is True,
        }
    )


def build_hot_outcome_mature_result(payload: dict[str, Any], *, as_of_time_utc: datetime | None = None) -> dict[str, Any]:
    now = _now(as_of_time_utc)
    hot_case_id = str(payload.get("hot_case_id") or "unknown-hot-case")
    buy_point = payload.get("buy_point") if isinstance(payload.get("buy_point"), dict) else {}
    observations = payload.get("observations") if isinstance(payload.get("observations"), list) else []
    trade_day_index = payload.get("trade_day_index")
    trade_day_index = int(trade_day_index) if trade_day_index not in (None, "") else None
    outcome = build_hot_outcome_label(hot_case_id=hot_case_id, buy_point=buy_point, observations=observations, as_of_time_utc=now, trade_day_index=trade_day_index)
    return _jsonable(
        {
            "contract_kind": "hot_outcome_mature_result_v1",
            "production_api_version": HOT_PRODUCTION_API_VERSION,
            "outcome_label": outcome,
            "can_build_evolution_sample": outcome.get("label_maturity_status") == "mature",
            "requires_trade_calendar": True,
        }
    )


def build_hot_evolution_build_result(payload: dict[str, Any], *, as_of_time_utc: datetime | None = None) -> dict[str, Any]:
    now = _now(as_of_time_utc)
    outcome = payload.get("outcome_label") if isinstance(payload.get("outcome_label"), dict) else {}
    if outcome.get("label_maturity_status") != "mature":
        return _jsonable(
            {
                "contract_kind": "hot_evolution_build_result_v1",
                "production_api_version": HOT_PRODUCTION_API_VERSION,
                "evolution_sample": None,
                "build_status": "blocked_outcome_not_mature",
                "hard_rule": "evolution_sample_requires_mature_outcome",
            }
        )
    sample = build_hot_evolution_sample(payload, as_of_time_utc=now)
    return _jsonable(
        {
            "contract_kind": "hot_evolution_build_result_v1",
            "production_api_version": HOT_PRODUCTION_API_VERSION,
            "evolution_sample": sample,
            "build_status": "built",
            "hard_rule": "offline_only_do_not_mutate_production_model_online",
        }
    )


def build_hot_failure_analysis_result(payload: dict[str, Any], *, as_of_time_utc: datetime | None = None) -> dict[str, Any]:
    now = _now(as_of_time_utc)
    research = payload.get("research_contract") if isinstance(payload.get("research_contract"), dict) else {}
    buy_point = payload.get("buy_point") if isinstance(payload.get("buy_point"), dict) else {}
    outcome = payload.get("outcome_label") if isinstance(payload.get("outcome_label"), dict) else {}
    observations = payload.get("observations") if isinstance(payload.get("observations"), list) else []
    source_audit = payload.get("source_visibility_audit") if isinstance(payload.get("source_visibility_audit"), dict) else {}
    failure = build_hot_failure_attribution(research_contract=research, buy_point=buy_point, outcome=outcome, observations=observations, source_visibility_audit=source_audit)
    distortion = build_hot_first_output_distortion_analysis(research_contract=research, outcome=outcome, failure_attribution=failure)
    return _jsonable({"contract_kind": "hot_failure_analysis_result_v1", "production_api_version": HOT_PRODUCTION_API_VERSION, "failure_attribution": failure, "first_output_distortion_analysis": distortion, "analyzed_at": now})


def build_hot_cycle_db_resolution_contract(decision_case: dict[str, Any]) -> dict[str, Any]:
    symbol = decision_case.get("symbol")
    trade_date = decision_case.get("trade_date")
    return {
        "contract_kind": "hot_cycle_db_resolution_contract_v1",
        "symbol": symbol,
        "trade_date": trade_date,
        "rules": [
            "query active decision_hot.hot_cycle_v1 by symbol inside transaction",
            "lock active cycle row with SELECT FOR UPDATE before deciding reuse_or_create",
            "enforce partial unique index: one active hot_cycle per symbol",
            "reuse active cycle for consecutive listing, board continuation, break divergence, or relimit_after_break",
            "create new cycle only after cooling rule confirms previous cycle closed",
        ],
        "required_unique_constraint": "uq_hot_active_cycle_symbol",
    }
