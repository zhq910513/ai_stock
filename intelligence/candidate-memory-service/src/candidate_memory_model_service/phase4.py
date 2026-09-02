from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from candidate_memory_model_service.research_v1 import MEMORY_MODEL_VERSION

PHASE4_SCHEMA_VERSION = "candidate_memory_phase4_v1"
MIN_BUCKET_SAMPLE_COUNT = 5
DEFAULT_PRE_SIGNAL_THRESHOLD = Decimal("62")
DEFAULT_ACTIVATION_THRESHOLD = Decimal("68")


def utc_run_id(prefix: str = "candidate-memory-phase4") -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        numeric = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not numeric.is_finite():
        return None
    return numeric


def _score(value: Any, default: Decimal | None = None) -> Decimal | None:
    numeric = _decimal(value)
    if numeric is None:
        return default
    if numeric <= 1:
        numeric *= Decimal("100")
    if numeric < 0 or numeric > 100:
        return default
    return max(Decimal("0"), min(Decimal("100"), numeric)).quantize(Decimal("0.000001"))


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


def _mean(values: list[Decimal]) -> Decimal | None:
    clean = [value for value in values if value is not None]
    if not clean:
        return None
    return (sum(clean) / Decimal(len(clean))).quantize(Decimal("0.000001"))


def _pct(current: Decimal | None, base: Decimal | None) -> Decimal | None:
    if current is None or base is None or base <= 0:
        return None
    return ((current / base - Decimal("1")) * Decimal("100")).quantize(Decimal("0.000001"))


def _bars(row: dict[str, Any]) -> list[dict[str, Any]]:
    bars = row.get("daily_bars") or row.get("price_path") or []
    if not isinstance(bars, list):
        return []
    return sorted([bar for bar in bars if isinstance(bar, dict)], key=lambda x: str(x.get("trading_day") or x.get("trade_date") or x.get("bar_time") or ""))


def _close(bar: dict[str, Any]) -> Decimal | None:
    return _decimal(bar.get("close") or bar.get("close_price") or bar.get("latest_price"))


def _high(bar: dict[str, Any]) -> Decimal | None:
    return _decimal(bar.get("high") or bar.get("high_price"))


def _low(bar: dict[str, Any]) -> Decimal | None:
    return _decimal(bar.get("low") or bar.get("low_price"))


def _amount(bar: dict[str, Any]) -> Decimal | None:
    amount = _decimal(bar.get("amount") or bar.get("turnover_amount"))
    if amount is not None:
        return amount
    close = _close(bar)
    volume = _decimal(bar.get("volume"))
    if close is None or volume is None:
        return None
    return close * volume


def _date(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if not value:
        return None
    text = str(value)
    if "T" in text:
        return text.split("T", 1)[0]
    return text[:10]


def _visible_at_or_before(evidence: dict[str, Any], decision_time: datetime) -> tuple[bool, str | None, datetime | None]:
    available_at = _dt(evidence.get("available_at") or evidence.get("captured_at") or evidence.get("published_at"))
    if available_at is None:
        return False, "missing_available_at", None
    if available_at > decision_time:
        return False, "future_available_at", available_at
    return True, None, available_at


def build_source_feature_snapshot(row: dict[str, Any], *, as_of_time_utc: datetime | None = None, run_id: str | None = None) -> dict[str, Any]:
    """Normalize wide source facts into typed candidate-memory feature snapshots.

    Candidate memory needs wider and faster data than hot candidates. This stage deliberately converts raw
    price/moneyflow/sector/event/tradability inputs into typed feature blocks with watermarks and a visibility
    audit. The model stages should read this output instead of scanning raw news JSON or historical bars.
    """

    decision_time = as_of_time_utc or datetime.now(timezone.utc)
    run_id = run_id or utc_run_id("memory-source-feature")
    symbol = str(row.get("symbol") or "").zfill(6)
    memory_entity_id = row.get("memory_entity_id") or f"mem-{symbol}"
    bars = _bars(row)
    closes = [_close(bar) for bar in bars if _close(bar) is not None]
    highs = [_high(bar) for bar in bars if _high(bar) is not None]
    lows = [_low(bar) for bar in bars if _low(bar) is not None]
    amounts = [_amount(bar) for bar in bars if _amount(bar) is not None]
    latest_close = closes[-1] if closes else _decimal(row.get("latest_price"))
    previous_hot_high = _decimal(row.get("first_hot_high") or row.get("previous_hot_high")) or (max(highs) if highs else None)
    recent_high = max(highs[-20:]) if highs else previous_hot_high
    recent_low = min(lows[-20:]) if lows else None
    first_selected_price = _decimal(row.get("first_selected_price") or row.get("reference_entry_price"))

    distance_to_first_hot_high = _pct(latest_close, previous_hot_high) if latest_close is not None and previous_hot_high is not None else None
    distance_to_recent_high = _pct(latest_close, recent_high) if latest_close is not None and recent_high is not None else None
    volatility_values: list[Decimal] = []
    for bar in bars[-10:]:
        h = _high(bar)
        l = _low(bar)
        c = _close(bar)
        if h is not None and l is not None and c is not None and c > 0:
            volatility_values.append(((h - l) / c * Decimal("100")).copy_abs())
    volatility_compression_score = None
    if volatility_values:
        avg_volatility = _mean(volatility_values) or Decimal("0")
        volatility_compression_score = max(Decimal("0"), min(Decimal("100"), Decimal("100") - avg_volatility * Decimal("8"))).quantize(Decimal("0.000001"))

    higher_low_count = 0
    lows_6 = [value for value in lows[-6:] if value is not None]
    for idx in range(1, len(lows_6)):
        if lows_6[idx] >= lows_6[idx - 1]:
            higher_low_count += 1
    support_hold_count = 0
    if recent_low is not None:
        support_line = recent_low * Decimal("1.02")
        for close in closes[-10:]:
            if close >= support_line:
                support_hold_count += 1

    amount_recovery_score = None
    if len(amounts) >= 10:
        recent_amount = _mean(amounts[-3:]) or Decimal("0")
        base_amount = _mean(amounts[-10:-3]) or Decimal("0")
        if base_amount > 0:
            amount_recovery_score = max(Decimal("0"), min(Decimal("100"), recent_amount / base_amount * Decimal("60"))).quantize(Decimal("0.000001"))

    price_watermark = _dt(row.get("price_watermark") or row.get("daily_bar_available_at") or row.get("available_at")) or decision_time
    price_feature = {
        "memory_entity_id": memory_entity_id,
        "symbol": symbol,
        "watermark": price_watermark,
        "latest_price": latest_close,
        "return_since_first_selected_pct": _pct(latest_close, first_selected_price),
        "distance_to_first_hot_high_pct": distance_to_first_hot_high,
        "distance_to_recent_high_pct": distance_to_recent_high,
        "higher_low_count": higher_low_count,
        "support_hold_count": support_hold_count,
        "volatility_compression_score": volatility_compression_score,
        "volume_recovery_ratio_score": amount_recovery_score,
        "breakout_pressure_score": max(Decimal("0"), min(Decimal("100"), Decimal("100") + (distance_to_recent_high or Decimal("-100")))).quantize(Decimal("0.000001")) if distance_to_recent_high is not None else None,
        "provider": row.get("price_provider") or "source.daily_bar/minute_bar",
    }

    moneyflow = row.get("moneyflow_feature") if isinstance(row.get("moneyflow_feature"), dict) else row.get("moneyflow") or {}
    if not isinstance(moneyflow, dict):
        moneyflow = {}
    moneyflow_feature = {
        "memory_entity_id": memory_entity_id,
        "symbol": symbol,
        "watermark": _dt(moneyflow.get("available_at") or row.get("moneyflow_watermark") or row.get("available_at")) or decision_time,
        "moneyflow_delta_3d_score": _score(moneyflow.get("moneyflow_delta_3d_score") or moneyflow.get("moneyflow_delta_3d"), Decimal("50")),
        "moneyflow_delta_5d_score": _score(moneyflow.get("moneyflow_delta_5d_score") or moneyflow.get("moneyflow_delta_5d"), Decimal("50")),
        "moneyflow_turning_point_score": _score(moneyflow.get("moneyflow_turning_point_score") or moneyflow.get("turning_point"), Decimal("50")),
        "capital_outflow_decay_score": _score(moneyflow.get("capital_outflow_decay_score"), Decimal("50")),
        "intraday_support_flow_score": _score(moneyflow.get("intraday_support_flow_score"), Decimal("50")),
        "provider": moneyflow.get("provider") or "source.moneyflow_stock_snapshot",
    }

    sector = row.get("sector_theme_feature") if isinstance(row.get("sector_theme_feature"), dict) else row.get("sector_theme") or {}
    if not isinstance(sector, dict):
        sector = {}
    sector_theme_feature = {
        "memory_entity_id": memory_entity_id,
        "symbol": symbol,
        "watermark": _dt(sector.get("available_at") or row.get("sector_theme_watermark") or row.get("available_at")) or decision_time,
        "sector_strength_delta_3d_score": _score(sector.get("sector_strength_delta_3d_score") or sector.get("sector_strength_delta_3d"), Decimal("50")),
        "sector_strength_delta_5d_score": _score(sector.get("sector_strength_delta_5d_score") or sector.get("sector_strength_delta_5d"), Decimal("50")),
        "relative_sector_rank_change_score": _score(sector.get("relative_sector_rank_change_score"), Decimal("50")),
        "theme_heat_recovery_score": _score(sector.get("theme_heat_recovery_score"), Decimal("50")),
        "sector_limit_up_breadth_score": _score(sector.get("sector_limit_up_breadth_score"), Decimal("50")),
        "provider": sector.get("provider") or "source.sector_theme_snapshot",
    }

    events = row.get("events") or row.get("news_events") or []
    if not isinstance(events, list):
        events = []
    visible_events: list[dict[str, Any]] = []
    post_hoc_events: list[dict[str, Any]] = []
    event_gaps: list[str] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        ok, reason, available_at = _visible_at_or_before(event, decision_time)
        enriched = dict(event)
        enriched["available_at"] = available_at
        enriched["visibility_state"] = "ex_ante" if ok else reason
        if ok:
            visible_events.append(enriched)
        else:
            post_hoc_events.append(enriched)
            event_gaps.append(f"event_{reason}")
    visible_scores = [_score(event.get("importance_score") or event.get("catalyst_strength_score"), Decimal("50")) or Decimal("50") for event in visible_events]
    event_signal_feature = {
        "memory_entity_id": memory_entity_id,
        "symbol": symbol,
        "watermark": max([event["available_at"] for event in visible_events if event.get("available_at")] or [decision_time if not events else datetime.fromtimestamp(0, tz=timezone.utc)]),
        "ex_ante_event_count": len(visible_events),
        "post_hoc_event_count": len(post_hoc_events),
        "event_signal_score": _mean(visible_scores) or Decimal("0"),
        "ex_ante_event_refs": [event.get("event_id") for event in visible_events if event.get("event_id")],
        "post_hoc_event_refs": [event.get("event_id") for event in post_hoc_events if event.get("event_id")],
        "provider": "source.news_event/event_entity_link",
    }

    tradability = row.get("tradability_feature") if isinstance(row.get("tradability_feature"), dict) else {}
    tradability_feature = {
        "memory_entity_id": memory_entity_id,
        "symbol": symbol,
        "watermark": _dt(tradability.get("available_at") or row.get("tradability_watermark") or row.get("available_at")) or decision_time,
        "tradability_status": tradability.get("tradability_status") or row.get("tradability_status") or "tradable",
        "limit_up_blocked": bool(tradability.get("limit_up_blocked") or row.get("limit_up_blocked") or False),
        "liquidity_score": _score(tradability.get("liquidity_score") or row.get("liquidity_score"), Decimal("70")),
        "provider": tradability.get("provider") or "source.tradability_status",
    }

    feature_watermarks = {
        "price_structure": {"watermark": price_feature["watermark"], "provider": price_feature["provider"]},
        "moneyflow": {"watermark": moneyflow_feature["watermark"], "provider": moneyflow_feature["provider"]},
        "sector_theme": {"watermark": sector_theme_feature["watermark"], "provider": sector_theme_feature["provider"]},
        "event_signal": {"watermark": event_signal_feature["watermark"], "provider": event_signal_feature["provider"]},
        "tradability": {"watermark": tradability_feature["watermark"], "provider": tradability_feature["provider"]},
    }
    result = {
        "schema_version": "candidate_memory_source_feature_snapshot_v1",
        "run_id": run_id,
        "model_version": MEMORY_MODEL_VERSION,
        "memory_entity_id": memory_entity_id,
        "symbol": symbol,
        "decision_time": decision_time,
        "price_structure_feature": price_feature,
        "moneyflow_feature": moneyflow_feature,
        "sector_theme_feature": sector_theme_feature,
        "event_signal_feature": event_signal_feature,
        "tradability_feature": tradability_feature,
        "feature_watermarks": feature_watermarks,
        "source_gap_codes": sorted(set(event_gaps)),
        "guardrails": {
            "raw_source_standardized_before_model_stage": True,
            "events_after_decision_time_excluded_from_ex_ante_features": True,
            "typed_feature_snapshots_feed_pre_signal_not_raw_json": True,
        },
    }
    result["snapshot_hash"] = _stable_hash(result)
    return _jsonable(result)


def build_stage_persistence_plan(row: dict[str, Any], *, as_of_time_utc: datetime | None = None, run_id: str | None = None) -> dict[str, Any]:
    """Build an auditable stage write plan for repository transaction boundaries.

    The API remains side-effect free in this environment, but this plan enumerates exactly which repository
    method must be called for each formal stage and which writes are append-only versus projections.
    """

    decision_time = as_of_time_utc or datetime.now(timezone.utc)
    run_id = run_id or utc_run_id("memory-persistence-plan")
    stage_outputs = row.get("stage_outputs") or row
    if not isinstance(stage_outputs, dict):
        stage_outputs = {}
    stage_order = [
        ("seed", "memory_seed", "save_memory_seed", "insert_once"),
        ("entity", "memory_entity", "upsert_memory_entity", "upsert_projection_with_initial_snapshot_insert_once"),
        ("pre_signal", "pre_signal_case", "save_pre_signal_case", "append_only"),
        ("activation", "activation_case", "save_activation_case", "insert_once"),
        ("release_gate", "release_gate", "save_release_gate_and_signal", "transactional_insert_signal_if_passed"),
        ("buy_point", "buy_point", "save_buy_point", "insert_once_first_valid_price"),
        ("outcome", "outcome_label", "save_mature_outcome", "upsert_mature_version_only"),
        ("up_reason", "up_reason_attribution", "save_up_reason_attribution", "insert_once"),
        ("evolution", "evolution_sample", "save_evolution_sample", "insert_if_outcome_mature"),
    ]
    planned_writes: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    hard_blocks: list[str] = []
    for stage_code, payload_key, repository_method, write_mode in stage_order:
        payload = stage_outputs.get(payload_key)
        if payload is None:
            skipped.append({"stage_code": stage_code, "reason": "stage_output_missing", "payload_key": payload_key})
            continue
        if stage_code == "evolution" and payload.get("evolution_state") == "blocked":
            skipped.append({"stage_code": stage_code, "reason": "blocked_evolution_not_persisted_as_training_sample"})
            continue
        if stage_code == "outcome" and payload.get("label_maturity_status") not in {"mature", "final"}:
            hard_blocks.append("pending_outcome_cannot_be_persisted_as_mature_label")
        planned_writes.append(
            {
                "stage_code": stage_code,
                "payload_key": payload_key,
                "repository_method": repository_method,
                "write_mode": write_mode,
                "idempotency_key": payload.get("idempotency_key") or payload.get("seed_id") or payload.get("memory_entity_id") or payload.get("pre_signal_case_id") or payload.get("activation_case_id") or payload.get("memory_signal_id") or payload.get("buy_point_id") or payload.get("outcome_id") or payload.get("attribution_id") or payload.get("evolution_sample_id"),
                "transaction_scope": "single_stage_transaction",
                "payload_hash": _stable_hash(payload) if isinstance(payload, dict) else None,
            }
        )
    result = {
        "schema_version": "candidate_memory_stage_persistence_plan_v1",
        "run_id": run_id,
        "model_version": MEMORY_MODEL_VERSION,
        "planned_at": decision_time,
        "plan_state": "blocked" if hard_blocks else "ready",
        "planned_writes": planned_writes,
        "skipped_stages": skipped,
        "hard_block_reasons": sorted(set(hard_blocks)),
        "guardrails": {
            "production_stages_are_separate_transactions": True,
            "initial_snapshot_and_observations_are_append_only": True,
            "latest_state_is_projection_not_training_truth": True,
            "pending_outcome_not_allowed_as_mature_truth": True,
        },
    }
    result["plan_hash"] = _stable_hash(result)
    return _jsonable(result)


def build_pre_signal_threshold_calibration(row: dict[str, Any], *, as_of_time_utc: datetime | None = None, run_id: str | None = None) -> dict[str, Any]:
    """Calibrate pre-signal thresholds from mature, ex-ante-labelled samples only."""

    decision_time = as_of_time_utc or datetime.now(timezone.utc)
    run_id = run_id or utc_run_id("memory-threshold-calibration")
    cutoff = _dt(row.get("calibration_cutoff_time")) or decision_time
    samples = row.get("mature_samples") or row.get("samples") or []
    if not isinstance(samples, list):
        samples = []
    eligible: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for sample in samples:
        if not isinstance(sample, dict):
            continue
        matured_at = _dt(sample.get("matured_at") or sample.get("label_matured_at") or sample.get("available_at"))
        if sample.get("label_maturity_status") not in {"mature", "final"}:
            excluded.append({"sample_id": sample.get("sample_id") or sample.get("memory_signal_id"), "reason": "not_mature"})
            continue
        if matured_at is not None and matured_at > cutoff:
            excluded.append({"sample_id": sample.get("sample_id") or sample.get("memory_signal_id"), "reason": "future_matured_after_cutoff"})
            continue
        if sample.get("new_independent_cycle") or sample.get("outcome_label") == "new_independent_cycle":
            excluded.append({"sample_id": sample.get("sample_id") or sample.get("memory_signal_id"), "reason": "new_independent_cycle_excluded"})
            continue
        if sample.get("pre_signal_visible_before_activation") is False:
            excluded.append({"sample_id": sample.get("sample_id") or sample.get("memory_signal_id"), "reason": "pre_signal_not_ex_ante"})
            continue
        eligible.append(sample)

    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for sample in eligible:
        score = _score(sample.get("pre_signal_score") or sample.get("pre_signal_strength_score"), Decimal("0")) or Decimal("0")
        bucket = f"{int(score // Decimal('10')) * 10}-{int(score // Decimal('10')) * 10 + 9}"
        for reason in sample.get("pre_signal_types") or sample.get("pre_signal_reason_codes") or ["all"]:
            buckets[f"{reason}|{bucket}"].append(sample)

    bucket_reports: list[dict[str, Any]] = []
    best_threshold = DEFAULT_PRE_SIGNAL_THRESHOLD
    best_uplift = Decimal("-999")
    threshold_candidates = [Decimal("55"), Decimal("60"), Decimal("62"), Decimal("65"), Decimal("68"), Decimal("70"), Decimal("75")]
    for threshold in threshold_candidates:
        selected = [s for s in eligible if (_score(s.get("pre_signal_score") or s.get("pre_signal_strength_score"), Decimal("0")) or Decimal("0")) >= threshold]
        if len(selected) < MIN_BUCKET_SAMPLE_COUNT:
            continue
        successes = [s for s in selected if s.get("outcome_label") in {"second_wave_success", "delayed_realization"} or s.get("next_limit_up_hit") is True]
        false_positives = [s for s in selected if s.get("outcome_label") in {"fake_activation_failure", "second_wave_failed"}]
        success_rate = Decimal(len(successes)) / Decimal(len(selected)) * Decimal("100")
        false_positive_rate = Decimal(len(false_positives)) / Decimal(len(selected)) * Decimal("100")
        uplift = success_rate - false_positive_rate
        if uplift > best_uplift:
            best_uplift = uplift
            best_threshold = threshold
    for bucket_key, rows in sorted(buckets.items()):
        reason, score_bucket = bucket_key.split("|", 1)
        successes = [s for s in rows if s.get("outcome_label") in {"second_wave_success", "delayed_realization"} or s.get("next_limit_up_hit") is True]
        false_positives = [s for s in rows if s.get("outcome_label") in {"fake_activation_failure", "second_wave_failed"}]
        bucket_reports.append(
            {
                "pre_signal_reason": reason,
                "score_bucket": score_bucket,
                "sample_count": len(rows),
                "success_count": len(successes),
                "false_positive_count": len(false_positives),
                "success_rate_pct": (Decimal(len(successes)) / Decimal(len(rows)) * Decimal("100")).quantize(Decimal("0.000001")) if rows else None,
                "false_positive_rate_pct": (Decimal(len(false_positives)) / Decimal(len(rows)) * Decimal("100")).quantize(Decimal("0.000001")) if rows else None,
                "sample_warning": "sample_insufficient" if len(rows) < MIN_BUCKET_SAMPLE_COUNT else None,
            }
        )
    result = {
        "schema_version": "candidate_memory_pre_signal_threshold_calibration_v1",
        "run_id": run_id,
        "model_version": MEMORY_MODEL_VERSION,
        "calculated_at": decision_time,
        "calibration_cutoff_time": cutoff,
        "eligible_sample_count": len(eligible),
        "excluded_sample_count": len(excluded),
        "excluded_samples": excluded[:100],
        "recommended_pre_signal_threshold": best_threshold,
        "recommended_activation_threshold": max(DEFAULT_ACTIVATION_THRESHOLD, best_threshold + Decimal("5")),
        "bucket_reports": bucket_reports,
        "calibration_state": "sample_insufficient" if len(eligible) < MIN_BUCKET_SAMPLE_COUNT else "ready_for_shadow_validation",
        "guardrails": {
            "uses_only_mature_samples_before_cutoff": True,
            "new_independent_cycle_excluded_from_success": True,
            "post_hoc_only_signals_excluded": True,
            "thresholds_require_shadow_validation_before_activation": True,
        },
    }
    result["calibration_hash"] = _stable_hash(result)
    return _jsonable(result)


def build_multi_day_replay_validation(row: dict[str, Any], *, as_of_time_utc: datetime | None = None, run_id: str | None = None) -> dict[str, Any]:
    """Replay memory pre-signal/activation/outcome boundaries across multiple trading days.

    This is a deterministic validation helper. It checks that a future/post-hoc event does not improve an earlier
    pre-signal, that delayed realization/second-wave/new-cycle are separated, and that tradability is not confused
    with direction success.
    """

    decision_time = as_of_time_utc or datetime.now(timezone.utc)
    run_id = run_id or utc_run_id("memory-replay")
    memory_entity_id = row.get("memory_entity_id") or "mem-replay"
    symbol = str(row.get("symbol") or "").zfill(6)
    trading_days = row.get("trading_days") or []
    if not isinstance(trading_days, list):
        trading_days = []
    limit_up_dates = {_date(item) for item in row.get("limit_up_dates") or []}
    new_cycle_dates = {_date(item) for item in row.get("new_independent_cycle_dates") or []}
    first_selected_date = _date(row.get("first_selected_date"))
    activation_records: list[dict[str, Any]] = []
    pre_signal_records: list[dict[str, Any]] = []
    guardrail_violations: list[str] = []
    earliest_pre_signal_date: str | None = None
    first_activation_date: str | None = None
    for day in trading_days:
        if not isinstance(day, dict):
            continue
        day_date = _date(day.get("trading_day") or day.get("date"))
        day_time = _dt(day.get("decision_time")) or decision_time
        pre_signal_score = _score(day.get("pre_signal_score"), Decimal("0")) or Decimal("0")
        activation_score = _score(day.get("activation_quality_score"), Decimal("0")) or Decimal("0")
        future_event_used = bool(day.get("future_event_used") or day.get("post_hoc_used_in_pre_signal"))
        tradability_status = day.get("tradability_status") or "tradable"
        if future_event_used:
            guardrail_violations.append(f"future_or_post_hoc_event_used:{day_date}")
        if pre_signal_score >= DEFAULT_PRE_SIGNAL_THRESHOLD and not future_event_used:
            pre_signal_records.append({"trading_day": day_date, "pre_signal_score": pre_signal_score, "pre_signal_types": day.get("pre_signal_types") or []})
            if earliest_pre_signal_date is None:
                earliest_pre_signal_date = day_date
        if activation_score >= DEFAULT_ACTIVATION_THRESHOLD and pre_signal_score >= DEFAULT_PRE_SIGNAL_THRESHOLD and not future_event_used:
            activation_records.append({"trading_day": day_date, "activation_quality_score": activation_score, "tradability_status": tradability_status})
            if first_activation_date is None:
                first_activation_date = day_date
    outcome_label = "no_replay_outcome"
    next_limit_up_date = min([date for date in limit_up_dates if date is not None], default=None)
    if next_limit_up_date in new_cycle_dates:
        outcome_label = "new_independent_cycle"
    elif next_limit_up_date and first_activation_date:
        if first_selected_date and (datetime.fromisoformat(next_limit_up_date) - datetime.fromisoformat(first_selected_date)).days <= 5:
            outcome_label = "delayed_realization"
        else:
            outcome_label = "second_wave_success"
    elif first_activation_date and not next_limit_up_date:
        outcome_label = "second_wave_failed"
    tradable_success = False
    direction_success_execution_missed = False
    if next_limit_up_date and first_activation_date:
        activation = next((item for item in activation_records if item["trading_day"] == first_activation_date), {})
        if activation.get("tradability_status") in {"tradable", "pullback_confirmed_entry", "breakout_confirmed_entry"}:
            tradable_success = True
        else:
            direction_success_execution_missed = True
    lead_days = None
    if earliest_pre_signal_date and next_limit_up_date:
        lead_days = max(0, (datetime.fromisoformat(next_limit_up_date) - datetime.fromisoformat(earliest_pre_signal_date)).days)
    replay_state = "pass" if not guardrail_violations else "failed_guardrail"
    result = {
        "schema_version": "candidate_memory_multi_day_replay_validation_v1",
        "run_id": run_id,
        "model_version": MEMORY_MODEL_VERSION,
        "memory_entity_id": memory_entity_id,
        "symbol": symbol,
        "replayed_at": decision_time,
        "trading_day_count": len(trading_days),
        "pre_signal_records": pre_signal_records,
        "activation_records": activation_records,
        "earliest_pre_signal_date": earliest_pre_signal_date,
        "first_activation_date": first_activation_date,
        "next_limit_up_date": next_limit_up_date,
        "pre_signal_lead_days": lead_days,
        "outcome_label": outcome_label,
        "tradable_success": tradable_success,
        "direction_success_execution_missed": direction_success_execution_missed,
        "guardrail_violations": sorted(set(guardrail_violations)),
        "replay_state": replay_state,
        "guardrails": {
            "future_or_post_hoc_events_fail_replay": True,
            "new_independent_cycle_not_counted_as_memory_success": True,
            "pre_signal_lead_days_measured_before_limit_up": True,
            "direction_success_separated_from_tradable_success": True,
        },
    }
    result["replay_hash"] = _stable_hash(result)
    return _jsonable(result)


def build_phase4_acceptance_check(row: dict[str, Any], *, as_of_time_utc: datetime | None = None, run_id: str | None = None) -> dict[str, Any]:
    decision_time = as_of_time_utc or datetime.now(timezone.utc)
    run_id = run_id or utc_run_id("memory-phase4-acceptance")
    checks = row.get("checks") or {}
    if not isinstance(checks, dict):
        checks = {}
    required = {
        "postgres_stage_transactions": bool(checks.get("postgres_stage_transactions")),
        "source_feature_standardization": bool(checks.get("source_feature_standardization")),
        "due_case_db_plan": bool(checks.get("due_case_db_plan")),
        "multi_day_replay": bool(checks.get("multi_day_replay")),
        "pre_signal_threshold_calibration": bool(checks.get("pre_signal_threshold_calibration")),
        "ex_ante_message_guardrail": bool(checks.get("ex_ante_message_guardrail")),
        "new_cycle_exclusion": bool(checks.get("new_cycle_exclusion")),
    }
    missing = [key for key, value in required.items() if not value]
    result = {
        "schema_version": "candidate_memory_phase4_acceptance_check_v1",
        "run_id": run_id,
        "model_version": MEMORY_MODEL_VERSION,
        "checked_at": decision_time,
        "acceptance_state": "pass" if not missing else "blocked",
        "checks": required,
        "missing_checks": missing,
        "phase4_boundary": {
            "status": "production_chain_acceptance_candidate" if not missing else "incomplete",
            "docker_postgres_real_provider_not_executed_in_this_environment": True,
            "requires_real_environment_replay_before_online_final": True,
        },
    }
    result["acceptance_hash"] = _stable_hash(result)
    return _jsonable(result)
