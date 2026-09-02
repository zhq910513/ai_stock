from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from candidate_memory_model_service.research_v1 import MEMORY_MODEL_VERSION


def utc_run_id(prefix: str = "candidate-memory-phase3") -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        numeric = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not numeric.is_finite():
        return None
    return numeric


def _int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def _stable_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(_jsonable(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _score(value: Any, default: Decimal | None = None) -> Decimal | None:
    numeric = _decimal(value)
    if numeric is None:
        return default
    if numeric <= 1:
        numeric *= Decimal("100")
    if numeric < 0 or numeric > 100:
        return default
    return max(Decimal("0"), min(Decimal("100"), numeric)).quantize(Decimal("0.000001"))


def _is_closed_status(status: str) -> bool:
    return status in {"closed", "invalidated", "expired_closed", "structure_invalidated"}


def _freshness_status(watermark: datetime | None, decision_time: datetime, *, sla_seconds: int) -> tuple[str, int | None]:
    if watermark is None:
        return "missing", None
    lag_seconds = int((decision_time - watermark).total_seconds())
    if lag_seconds < 0:
        return "future_watermark", lag_seconds
    if lag_seconds <= sla_seconds:
        return "fresh", lag_seconds
    return "stale", lag_seconds


def build_feature_readiness_audit(row: dict[str, Any], *, as_of_time_utc: datetime | None = None, run_id: str | None = None) -> dict[str, Any]:
    """Audit whether typed source/model features are fresh enough before a memory stage runs.

    This function is intentionally model-specific, while the actual watermark records live in governance/source.
    It prevents a common production failure: tasks run successfully but use stale or future-leaked features.
    """

    decision_time = as_of_time_utc or datetime.now(timezone.utc)
    run_id = run_id or utc_run_id("memory-feature-readiness")
    stage_code = str(row.get("stage_code") or "pre_signal_detect")
    memory_entity_id = row.get("memory_entity_id")
    symbol = str(row.get("symbol") or "").zfill(6)
    feature_watermarks = row.get("feature_watermarks") or {}
    if not isinstance(feature_watermarks, dict):
        feature_watermarks = {}

    # Candidate memory has a wider data surface than hot candidates. Price is always mandatory;
    # official activation additionally requires at least one of moneyflow/sector/theme to be fresh.
    default_sla = {
        "price_structure": 900,
        "moneyflow": 900,
        "sector_theme": 900,
        "event_signal": 180,
        "market_sentiment": 900,
        "tradability": 300,
    }
    stage_required = {
        "pre_signal_detect": ["price_structure", "moneyflow", "sector_theme", "event_signal", "market_sentiment"],
        "activation_evaluate": ["price_structure", "moneyflow", "sector_theme", "event_signal", "market_sentiment", "tradability"],
        "release_gate": ["price_structure", "moneyflow", "sector_theme", "tradability"],
        "buy_point": ["price_structure", "tradability"],
        "observation": ["price_structure", "moneyflow", "sector_theme"],
    }
    required_features = list(row.get("required_features") or stage_required.get(stage_code, stage_required["pre_signal_detect"]))
    sla_overrides = row.get("freshness_sla_seconds") or {}
    hard_blocks: list[str] = []
    warning_codes: list[str] = []
    details: list[dict[str, Any]] = []
    fresh_set: set[str] = set()
    stale_or_missing: set[str] = set()

    for feature_name in required_features:
        info = feature_watermarks.get(feature_name) or {}
        watermark_raw = info.get("watermark") if isinstance(info, dict) else info
        watermark = _dt(watermark_raw)
        sla = int((sla_overrides.get(feature_name) if isinstance(sla_overrides, dict) else None) or default_sla.get(feature_name, 900))
        status, lag_seconds = _freshness_status(watermark, decision_time, sla_seconds=sla)
        if status == "fresh":
            fresh_set.add(feature_name)
        else:
            stale_or_missing.add(feature_name)
            if status == "future_watermark":
                hard_blocks.append(f"future_feature_watermark:{feature_name}")
            elif feature_name in {"price_structure", "tradability"}:
                hard_blocks.append(f"required_feature_not_fresh:{feature_name}")
            else:
                warning_codes.append(f"feature_not_fresh:{feature_name}")
        details.append(
            {
                "feature_name": feature_name,
                "watermark": watermark,
                "freshness_sla_seconds": sla,
                "freshness_status": status,
                "lag_seconds": lag_seconds,
                "provider": info.get("provider") if isinstance(info, dict) else None,
            }
        )

    if stage_code in {"activation_evaluate", "release_gate"} and not ({"moneyflow", "sector_theme"} & fresh_set):
        hard_blocks.append("activation_requires_fresh_moneyflow_or_sector_theme")
    if stage_code in {"activation_evaluate", "release_gate"} and "event_signal" in stale_or_missing:
        # Events are not always mandatory, but stale events cannot be used as ex-ante reasons.
        warning_codes.append("event_signal_not_fresh_exclude_event_reason")

    readiness_state = "ready" if not hard_blocks else "blocked"
    result = {
        "schema_version": "candidate_memory_feature_readiness_audit_v1",
        "run_id": run_id,
        "model_version": MEMORY_MODEL_VERSION,
        "stage_code": stage_code,
        "memory_entity_id": memory_entity_id,
        "symbol": symbol,
        "decision_time": decision_time,
        "readiness_state": readiness_state,
        "feature_details": details,
        "hard_block_reasons": sorted(set(hard_blocks)),
        "warning_codes": sorted(set(warning_codes)),
        "guardrails": {
            "feature_watermark_required_before_model_stage": True,
            "future_watermark_hard_blocked": True,
            "stale_price_or_tradability_blocks_official_stage": True,
            "event_signal_stale_excluded_from_pre_signal_reason": True,
        },
    }
    result["audit_hash"] = _stable_hash(result)
    return _jsonable(result)


def build_due_observation_plan(row: dict[str, Any], *, as_of_time_utc: datetime | None = None, run_id: str | None = None) -> dict[str, Any]:
    """Build a DB-backed due observation plan from active registry rows and typed feature maps.

    The service does not guess all active entities. It only schedules due rows from the registry. Each due row
    is enriched with precomputed feature snapshots if present, making the observation task batchable.
    """

    decision_time = as_of_time_utc or datetime.now(timezone.utc)
    run_id = run_id or utc_run_id("memory-due-plan")
    registry_rows = row.get("registry_rows") or row.get("active_registry_rows") or []
    if not isinstance(registry_rows, list):
        registry_rows = []
    limit = int(row.get("limit") or 1000)
    features_by_entity = row.get("features_by_entity") or {}
    if not isinstance(features_by_entity, dict):
        features_by_entity = {}
    due_cases: list[dict[str, Any]] = []
    skipped_rows: list[dict[str, Any]] = []

    sorted_rows = sorted(
        [item for item in registry_rows if isinstance(item, dict)],
        key=lambda item: (-(int(item.get("priority_level") or 0)), str(item.get("next_observe_at") or "")),
    )
    for registry in sorted_rows:
        memory_entity_id = registry.get("memory_entity_id")
        status = str(registry.get("memory_status") or "observing")
        next_observe_at = _dt(registry.get("next_observe_at"))
        if not memory_entity_id:
            skipped_rows.append({"reason": "missing_memory_entity_id", "registry": registry})
            continue
        if _is_closed_status(status):
            skipped_rows.append({"memory_entity_id": memory_entity_id, "reason": "closed_status", "memory_status": status})
            continue
        if next_observe_at is None:
            skipped_rows.append({"memory_entity_id": memory_entity_id, "reason": "missing_next_observe_at"})
            continue
        if next_observe_at > decision_time:
            skipped_rows.append({"memory_entity_id": memory_entity_id, "reason": "not_due", "next_observe_at": next_observe_at})
            continue
        feature_bundle = features_by_entity.get(memory_entity_id) or {}
        if not isinstance(feature_bundle, dict):
            feature_bundle = {}
        case = {
            "memory_entity_id": memory_entity_id,
            "symbol": str(registry.get("symbol") or feature_bundle.get("symbol") or "").zfill(6),
            "memory_status": status,
            "tracking_pool": registry.get("tracking_pool") or "memory_observation_pool",
            "priority_level": int(registry.get("priority_level") or 0),
            "observe_seq": int(registry.get("next_observe_seq") or registry.get("observe_seq") or 1),
            "ttl_remaining_days": registry.get("ttl_remaining_days") or feature_bundle.get("ttl_remaining_days"),
            "ttl_effective_days": registry.get("ttl_effective_days") or feature_bundle.get("ttl_effective_days"),
            "daily_bars": feature_bundle.get("daily_bars") or registry.get("daily_bars") or [],
            "moneyflow_feature": feature_bundle.get("moneyflow_feature") or registry.get("moneyflow_feature") or {},
            "sector_theme_feature": feature_bundle.get("sector_theme_feature") or registry.get("sector_theme_feature") or {},
            "events": feature_bundle.get("events") or registry.get("events") or [],
            "market_risk_appetite_score": feature_bundle.get("market_risk_appetite_score") or registry.get("market_risk_appetite_score"),
            "feature_bundle_hash": _stable_hash(feature_bundle) if feature_bundle else None,
            "registry_snapshot": registry,
        }
        due_cases.append(case)
        if len(due_cases) >= limit:
            break

    result = {
        "schema_version": "candidate_memory_due_observation_plan_v1",
        "run_id": run_id,
        "model_version": MEMORY_MODEL_VERSION,
        "planned_at": decision_time,
        "due_case_count": len(due_cases),
        "skipped_count": len(skipped_rows),
        "due_cases": due_cases,
        "skipped_rows": skipped_rows,
        "guardrails": {
            "only_registry_due_cases_are_observed": True,
            "closed_entities_are_never_rescheduled": True,
            "priority_then_next_observe_at_ordering": True,
            "feature_snapshots_are_precomputed_before_observation": True,
        },
    }
    result["plan_hash"] = _stable_hash(result)
    return _jsonable(result)


def build_pre_limitup_signal_analysis(row: dict[str, Any], *, as_of_time_utc: datetime | None = None, run_id: str | None = None) -> dict[str, Any]:
    """Analyze whether the memory model found ex-ante pre-signals before the next limit-up event."""

    decision_time = as_of_time_utc or datetime.now(timezone.utc)
    run_id = run_id or utc_run_id("memory-pre-limitup-analysis")
    memory_entity_id = row.get("memory_entity_id")
    memory_signal_id = row.get("memory_signal_id")
    symbol = str(row.get("symbol") or "").zfill(6)
    next_limit_up_date = row.get("next_limit_up_date")
    limit_up_dt = _dt(row.get("next_limit_up_at") or (f"{next_limit_up_date}T15:00:00+00:00" if next_limit_up_date else None))
    pre_signal_cases = row.get("pre_signal_cases") or []
    if not isinstance(pre_signal_cases, list):
        pre_signal_cases = []
    lookback_window_days = int(row.get("lookback_window_days") or 10)
    failed_matched_cases = row.get("matched_failed_cases") or []
    success_matched_cases = row.get("matched_success_cases") or []

    eligible: list[dict[str, Any]] = []
    post_hoc_cases: list[dict[str, Any]] = []
    if limit_up_dt is not None:
        window_start = limit_up_dt - timedelta(days=lookback_window_days)
        for case in pre_signal_cases:
            if not isinstance(case, dict):
                continue
            detected_at = _dt(case.get("detected_at") or case.get("available_at"))
            if detected_at is None:
                post_hoc_cases.append({"reason": "missing_detected_at", "case": case})
                continue
            if detected_at > limit_up_dt:
                post_hoc_cases.append({"reason": "detected_after_limit_up", "case": case})
                continue
            if detected_at >= window_start:
                eligible.append(case)
    else:
        for case in pre_signal_cases:
            if isinstance(case, dict):
                eligible.append(case)

    earliest_dt: datetime | None = None
    if eligible:
        earliest_dt = min(_dt(case.get("detected_at") or case.get("available_at")) for case in eligible if _dt(case.get("detected_at") or case.get("available_at")) is not None)
    lead_days: int | None = None
    if earliest_dt is not None and limit_up_dt is not None:
        lead_days = max(0, int((limit_up_dt.date() - earliest_dt.date()).days))

    signal_types: set[str] = set()
    strength_values: list[Decimal] = []
    reason_counts: dict[str, int] = {}
    for case in eligible:
        for item in case.get("pre_signal_types") or case.get("pre_signal_types_json") or []:
            signal_types.add(str(item))
            reason_counts[str(item)] = reason_counts.get(str(item), 0) + 1
        strength = _score(case.get("pre_signal_strength_score") or case.get("pre_signal_score"))
        if strength is not None:
            strength_values.append(strength)
    strength_score = (sum(strength_values) / Decimal(len(strength_values))).quantize(Decimal("0.000001")) if strength_values else None

    matched_failed_count = len(failed_matched_cases) if isinstance(failed_matched_cases, list) else 0
    matched_success_count = len(success_matched_cases) if isinstance(success_matched_cases, list) else 0
    total_matched = matched_failed_count + matched_success_count
    false_positive_rate_bucket = None
    if total_matched > 0:
        false_positive_rate_bucket = (Decimal(matched_failed_count) / Decimal(total_matched) * Decimal("100")).quantize(Decimal("0.000001"))

    primary_up_reason = row.get("primary_up_reason")
    if not primary_up_reason and reason_counts:
        primary_up_reason = max(reason_counts.items(), key=lambda item: item[1])[0]
    analysis_state = "valid_ex_ante_pre_signal" if eligible and limit_up_dt is not None else "no_ex_ante_pre_signal_found"
    if limit_up_dt is None:
        analysis_state = "limit_up_event_missing"

    result = {
        "schema_version": "candidate_memory_pre_limitup_signal_analysis_v1",
        "run_id": run_id,
        "model_version": MEMORY_MODEL_VERSION,
        "analysis_id": f"prelimit-{memory_entity_id or symbol}-{_stable_hash(row)[:12]}",
        "memory_entity_id": memory_entity_id,
        "memory_signal_id": memory_signal_id,
        "symbol": symbol,
        "analyzed_at": decision_time,
        "next_limit_up_date": next_limit_up_date,
        "lookback_window_days": lookback_window_days,
        "earliest_detected_pre_signal_at": earliest_dt,
        "lead_days_before_limit_up": lead_days,
        "pre_signal_types": sorted(signal_types),
        "pre_signal_strength_score": strength_score,
        "false_positive_rate_bucket": false_positive_rate_bucket,
        "matched_failed_case_count": matched_failed_count,
        "matched_success_case_count": matched_success_count,
        "primary_up_reason": primary_up_reason or "unknown",
        "excluded_post_hoc_case_count": len(post_hoc_cases),
        "analysis_state": analysis_state,
        "guardrails": {
            "uses_only_pre_limit_up_detected_signals": True,
            "post_limit_up_signals_excluded_from_lead_analysis": True,
            "lead_days_measures_early_discovery_value": True,
        },
    }
    result["analysis_hash"] = _stable_hash(result)
    return _jsonable(result)


def build_model_schedule_contract(row: dict[str, Any] | None = None, *, as_of_time_utc: datetime | None = None, run_id: str | None = None) -> dict[str, Any]:
    """Declare candidate_memory's scheduler v2 requirements without storing model truth in scheduler."""

    decision_time = as_of_time_utc or datetime.now(timezone.utc)
    run_id = run_id or utc_run_id("memory-schedule-contract")
    stages = [
        {
            "stage_code": "seed_build",
            "endpoint": "/production/seed/build",
            "trigger_type": "data_ready",
            "required_source_facts": ["decision_hot.memory_seed_candidates"],
            "freshness_sla_seconds": 86400,
            "hard_block_if_missing": ["hot_mature_outcome"],
            "priority": 40,
            "output_event": "memory_seed_created",
        },
        {
            "stage_code": "entity_build",
            "endpoint": "/production/entity/build",
            "trigger_type": "event",
            "required_source_facts": ["memory_seed_created"],
            "freshness_sla_seconds": 86400,
            "hard_block_if_missing": ["memory_seed"],
            "priority": 45,
            "output_event": "memory_entity_created_or_updated",
        },
        {
            "stage_code": "feature_readiness",
            "endpoint": "/production/features/readiness",
            "trigger_type": "before_stage_guard",
            "required_feature_snapshots": ["price_structure", "moneyflow", "sector_theme", "event_signal", "market_sentiment"],
            "freshness_sla_seconds": {"price_structure": 900, "moneyflow": 900, "sector_theme": 900, "event_signal": 180},
            "hard_block_if_missing": ["price_structure"],
            "priority": 70,
            "output_event": "memory_feature_readiness_checked",
        },
        {
            "stage_code": "observation_due_plan",
            "endpoint": "/production/observations/due-plan",
            "trigger_type": "state_due",
            "required_registry": "decision_memory.memory_active_case_registry_v1",
            "freshness_sla_seconds": 300,
            "priority": 75,
            "max_batch_size": 1000,
            "output_event": "memory_due_cases_planned",
        },
        {
            "stage_code": "observations_bulk",
            "endpoint": "/production/observations/bulk",
            "trigger_type": "event",
            "required_feature_snapshots": ["price_structure", "moneyflow", "sector_theme"],
            "freshness_sla_seconds": 900,
            "priority": 75,
            "max_batch_size": 1000,
            "output_event": "memory_observation_appended",
        },
        {
            "stage_code": "pre_signal_detect",
            "endpoint": "/production/pre-signal/detect",
            "trigger_type": "state_or_event",
            "required_feature_snapshots": ["price_structure", "moneyflow", "sector_theme", "event_signal", "market_sentiment"],
            "freshness_sla_seconds": {"event_signal": 180, "price_structure": 900},
            "hard_block_if_missing": ["price_structure"],
            "priority": 80,
            "output_event": "memory_pre_signal_detected",
        },
        {
            "stage_code": "activation_evaluate",
            "endpoint": "/production/activation/evaluate",
            "trigger_type": "event",
            "required_feature_snapshots": ["price_structure", "moneyflow", "sector_theme", "event_signal", "tradability"],
            "hard_block_if_missing": ["price_structure", "tradability"],
            "priority": 90,
            "output_event": "memory_activation_case_ready",
        },
        {
            "stage_code": "release_gate",
            "endpoint": "/production/release-gate/evaluate",
            "trigger_type": "event",
            "required_feature_snapshots": ["price_structure", "moneyflow", "sector_theme", "tradability"],
            "hard_block_if_missing": ["available_at", "ttl_valid", "tradability", "duplicate_signal_guard"],
            "priority": 95,
            "output_event": "memory_official_signal_or_research_only",
        },
        {
            "stage_code": "outcome_mature",
            "endpoint": "/production/outcomes/mature",
            "trigger_type": "trading_day_offset",
            "schedule_offsets": ["T+5", "T+10", "T+20", "T+30"],
            "hard_block_if_missing": ["mature_price_path"],
            "priority": 45,
            "output_event": "memory_outcome_matured",
        },
        {
            "stage_code": "ttl_calibration",
            "endpoint": "/production/ttl-calibration/build",
            "trigger_type": "offline_batch",
            "schedule_window": "after_close_or_night",
            "hard_block_if_missing": ["mature_outcomes_before_cutoff"],
            "priority": 30,
            "output_event": "memory_ttl_calibration_ready_for_review",
        },
    ]
    frequency_matrix = {
        "ordinary_memory_entity": "15-30m",
        "valuable_memory_entity": "15m",
        "pre_signal_case": "3-5m",
        "activation_case": "1-3m",
        "expired_but_researchable": "daily_or_60m",
        "closed_or_invalidated": "stop",
        "news_event_scan": "1-3m",
        "sector_theme_refresh": "5-15m",
        "moneyflow_refresh": "5-15m",
    }
    result = {
        "schema_version": "candidate_memory_model_schedule_contract_v1",
        "run_id": run_id,
        "model_code": "candidate_memory",
        "model_version": MEMORY_MODEL_VERSION,
        "declared_at": decision_time,
        "contract_state": "ready_for_scheduler_v2_design",
        "stages": stages,
        "frequency_matrix": frequency_matrix,
        "scheduler_boundaries": {
            "scheduler_can_store_task_status": True,
            "scheduler_cannot_store_model_scores_or_labels": True,
            "model_truth_schema": "decision_memory",
            "source_truth_schema": "source",
            "governance_schema_for_watermarks_only": "governance",
        },
        "guardrails": {
            "multi_frequency_model_requirements_declared": True,
            "data_freshness_checked_before_model_stage": True,
            "outcome_and_evolution_offline_after_maturity": True,
            "available_at_later_than_decision_time_never_used_for_pre_signal": True,
        },
    }
    result["contract_hash"] = _stable_hash(result)
    return _jsonable(result)
