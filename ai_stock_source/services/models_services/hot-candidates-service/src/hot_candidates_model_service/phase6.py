from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from hot_candidates_model_service.calibration import build_hot_teacher_calibration_report
from hot_candidates_model_service.research import build_hot_observation_snapshot

HOT_PHASE6_VERSION = "hot_phase6_production_compute_v1"
ACTIVE_CASE_REGISTRY_VERSION = "hot_active_case_registry_v1"
LATEST_STATE_VERSION = "hot_case_latest_state_v1"
FEATURE_CONTRACT_VERSION = "hot_phase6_feature_snapshot_v1"
CALIBRATION_VERSION_CONTRACT = "hot_teacher_calibration_version_v1"


def _decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    if value in (None, ""):
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return default


def _optional_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value.quantize(Decimal("0.000001")))
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    return value


def _stable_hash(payload: dict[str, Any], prefix: str) -> str:
    encoded = json.dumps(_jsonable(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{prefix}-{hashlib.sha256(encoded.encode('utf-8')).hexdigest()[:24]}"


def _parse_time(value: Any, default: datetime | None = None) -> datetime:
    if value in (None, ""):
        return default or datetime.now(timezone.utc)
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return default or datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _text(value: Any, default: str = "") -> str:
    if value in (None, ""):
        return default
    return str(value)


def _boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return False
    return str(value).strip().lower() in {"true", "1", "yes", "y", "是"}


def _frequency_seconds(tracking_pool: str, priority_level: int) -> int:
    if tracking_pool == "official_signal_pool":
        return 60 if priority_level >= 80 else 300
    if tracking_pool == "teacher_distortion_pool":
        return 120 if priority_level >= 80 else 300
    if tracking_pool == "blocked_but_track_pool":
        return 600
    if tracking_pool == "calibration_pool":
        return 900
    return 1800


def build_active_case_registry_record(
    *,
    hot_case_id: str,
    hot_cycle_id: str,
    tracking_pool: str,
    now: datetime | None = None,
    priority_level: int | None = None,
    case_status: str = "active",
    last_observe_at: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    if priority_level is None:
        priority_level = {
            "official_signal_pool": 100,
            "teacher_distortion_pool": 90,
            "blocked_but_track_pool": 60,
            "calibration_pool": 40,
        }.get(tracking_pool, 20)
    freq = _frequency_seconds(tracking_pool, priority_level)
    base = last_observe_at or now
    next_observe_at = base + timedelta(seconds=freq)
    return _jsonable(
        {
            "contract_kind": ACTIVE_CASE_REGISTRY_VERSION,
            "hot_case_id": hot_case_id,
            "hot_cycle_id": hot_cycle_id,
            "tracking_pool": tracking_pool,
            "priority_level": priority_level,
            "observe_frequency_seconds": freq,
            "last_observe_at": last_observe_at,
            "next_observe_at": next_observe_at,
            "case_status": case_status,
            "close_reason": None,
            "updated_at": now,
        }
    )


def build_case_latest_state_from_observation(observation: dict[str, Any], *, updated_at: datetime | None = None) -> dict[str, Any]:
    updated_at = updated_at or datetime.now(timezone.utc)
    first_event = observation.get("first_event_type") or "none"
    if first_event == "target_hit":
        monitoring_status = "target_hit"
    elif first_event == "invalidation_hit":
        monitoring_status = "invalidation_hit"
    else:
        monitoring_status = "monitoring"
    return _jsonable(
        {
            "contract_kind": LATEST_STATE_VERSION,
            "hot_case_id": observation.get("hot_case_id"),
            "hot_cycle_id": observation.get("hot_cycle_id"),
            "latest_observation_id": observation.get("observation_id"),
            "latest_price": observation.get("latest_price"),
            "return_from_reference_pct": observation.get("return_from_reference_pct"),
            "mfe_pct": observation.get("mfe_pct"),
            "mae_pct": observation.get("mae_pct"),
            "first_event_type": first_event,
            "expectation_state": observation.get("expectation_state"),
            "freshness_status": observation.get("freshness_status"),
            "quality_status": observation.get("quality_status"),
            "monitoring_status": monitoring_status,
            "sequence_no": observation.get("sequence_no") or observation.get("observe_seq") or 0,
            "updated_at": updated_at,
        }
    )


def build_hot_cycle_day_feature(row: dict[str, Any], *, calculated_at: datetime | None = None) -> dict[str, Any]:
    calculated_at = calculated_at or datetime.now(timezone.utc)
    symbol = _text(row.get("symbol") or row.get("symbol_snapshot")).zfill(6)
    trade_date = _text(row.get("trade_date") or row.get("trading_day") or row.get("as_of_trading_day"), "unknown")
    board_count = int(_decimal(row.get("consecutive_board_count") or row.get("board_count") or row.get("limit_up_stage")))
    opened_times = int(_decimal(row.get("opened_times")))
    is_limit_up = _boolish(row.get("is_limit_up")) or board_count > 0
    is_one_word = _boolish(row.get("is_one_word_limit"))
    high = _optional_decimal(row.get("high_price") or row.get("high"))
    close = _optional_decimal(row.get("close_price") or row.get("close"))
    open_price = _optional_decimal(row.get("open_price") or row.get("open"))
    intraday_fade = None
    if high is not None and close is not None and high > 0:
        intraday_fade = ((high - close) / high * Decimal("100")).quantize(Decimal("0.000001"))
    feature = {
        "contract_kind": FEATURE_CONTRACT_VERSION,
        "feature_type": "hot_cycle_day_feature_v1",
        "feature_id": _stable_hash({"symbol": symbol, "trade_date": trade_date, "type": "cycle_day"}, "hot-day-feature"),
        "symbol": symbol,
        "trade_date": trade_date,
        "is_limit_up": is_limit_up,
        "is_one_word_limit": is_one_word,
        "is_t_shape_limit": _boolish(row.get("is_t_shape_limit")),
        "is_opened_limit": _boolish(row.get("is_opened_limit")) or opened_times > 0,
        "board_count": board_count,
        "consecutive_board_count": board_count,
        "break_board_flag": _boolish(row.get("break_board_flag")),
        "relimit_after_break_flag": _boolish(row.get("relimit_after_break_flag")),
        "turnover_rate": _optional_decimal(row.get("turnover_rate")),
        "volume_ratio": _optional_decimal(row.get("volume_ratio")),
        "seal_amount": _optional_decimal(row.get("seal_amount")),
        "seal_strength_score": _optional_decimal(row.get("seal_strength_score")),
        "opened_times": opened_times,
        "intraday_fade_score": intraday_fade,
        "open_price": open_price,
        "high_price": high,
        "low_price": _optional_decimal(row.get("low_price") or row.get("low")),
        "close_price": close,
        "calculated_at": calculated_at,
        "feature_hash": None,
    }
    feature["feature_hash"] = _stable_hash(feature, "hot-day-feature-hash")
    return _jsonable(feature)


def build_hot_execution_feature_snapshot(row: dict[str, Any], *, calc_stage: str, calculated_at: datetime | None = None) -> dict[str, Any]:
    calculated_at = calculated_at or datetime.now(timezone.utc)
    auction = row.get("auction_snapshot") if isinstance(row.get("auction_snapshot"), dict) else {}
    auction_price = _optional_decimal(auction.get("auction_price") or auction.get("virtual_open_price"))
    open_5m_vwap = _optional_decimal(row.get("open_5m_vwap") or row.get("open_5m_vwap_price"))
    previous_close = _optional_decimal(row.get("previous_close"))
    gap_pct = None
    if auction_price is not None and previous_close is not None and previous_close > 0:
        gap_pct = ((auction_price / previous_close - 1) * Decimal("100")).quantize(Decimal("0.000001"))
    deviation = None
    if auction_price is not None and open_5m_vwap is not None and open_5m_vwap > 0:
        deviation = ((auction_price / open_5m_vwap - 1) * Decimal("100")).quantize(Decimal("0.000001"))
    overheat = Decimal("0")
    if gap_pct is not None:
        overheat += max(Decimal("0"), gap_pct - Decimal("3")) * Decimal("8")
    if _boolish(row.get("is_one_word_limit")):
        overheat += Decimal("30")
    overheat = min(Decimal("100"), overheat).quantize(Decimal("0.000001"))
    snapshot = {
        "contract_kind": FEATURE_CONTRACT_VERSION,
        "feature_type": "hot_execution_feature_snapshot_v1",
        "feature_id": _stable_hash({"hot_case_id": row.get("hot_case_id"), "calc_stage": calc_stage, "time": calculated_at}, "hot-exec-feature"),
        "hot_case_id": row.get("hot_case_id"),
        "symbol": _text(row.get("symbol") or row.get("symbol_snapshot")).zfill(6),
        "calc_stage": calc_stage,
        "auction_price": auction_price,
        "auction_matched_amount": _optional_decimal(auction.get("matched_amount")),
        "auction_imbalance_ratio": _optional_decimal(auction.get("imbalance_ratio")),
        "open_5m_vwap": open_5m_vwap,
        "entry_vs_vwap_deviation_pct": deviation,
        "open_gap_pct": gap_pct,
        "open_overheat_score": overheat,
        "no_fill_risk_score": Decimal("100") if _boolish(row.get("is_one_word_limit")) else overheat,
        "calculated_at": calculated_at,
        "feature_hash": None,
    }
    snapshot["feature_hash"] = _stable_hash(snapshot, "hot-exec-feature-hash")
    return _jsonable(snapshot)


def build_bulk_observations(
    active_cases: Iterable[dict[str, Any]],
    *,
    as_of_time_utc: datetime | None = None,
) -> list[dict[str, Any]]:
    """Build append-only observations in batch from due active cases.

    The caller supplies current quote/feature fields in each active case. This function
    deliberately has no side effects and never mutates the initial decision fact.
    """
    now = as_of_time_utc or datetime.now(timezone.utc)
    observations: list[dict[str, Any]] = []
    for index, case in enumerate(active_cases, start=1):
        payload = dict(case)
        payload.setdefault("observe_seq", int(payload.get("last_observe_seq") or 0) + 1)
        payload.setdefault("sequence_no", payload["observe_seq"])
        payload.setdefault("observe_stage", "intraday_review")
        payload.setdefault("observe_time", now.isoformat())
        obs = build_hot_observation_snapshot(payload, as_of_time_utc=now)
        obs["batch_index"] = index
        observations.append(obs)
    return observations


def filter_mature_calibration_samples(samples: list[dict[str, Any]], *, cutoff_time: datetime) -> list[dict[str, Any]]:
    mature: list[dict[str, Any]] = []
    for sample in samples:
        outcome = sample.get("outcome_label") if isinstance(sample.get("outcome_label"), dict) else sample
        if _text(outcome.get("label_maturity_status")) != "mature":
            continue
        updated = _parse_time(outcome.get("updated_at") or outcome.get("label_available_at") or sample.get("updated_at"), default=cutoff_time)
        if updated <= cutoff_time:
            mature.append(sample)
    return mature


def build_versioned_teacher_calibration(
    samples: list[dict[str, Any]],
    *,
    calibration_version: str,
    training_window_start: str,
    training_window_end: str,
    cutoff_time: datetime,
    min_bucket_samples: int = 30,
    min_total_samples: int = 120,
) -> dict[str, Any]:
    mature = filter_mature_calibration_samples(samples, cutoff_time=cutoff_time)
    report = build_hot_teacher_calibration_report(
        mature,
        calibration_version=calibration_version,
        min_bucket_samples=min_bucket_samples,
        min_total_samples=min_total_samples,
        generated_at=cutoff_time,
    )
    can_activate = bool((report.get("activation_gate") or {}).get("can_activate_calibration"))
    return _jsonable(
        {
            "contract_kind": CALIBRATION_VERSION_CONTRACT,
            "calibration_version": calibration_version,
            "training_window_start": training_window_start,
            "training_window_end": training_window_end,
            "calibration_cutoff_time": cutoff_time,
            "raw_sample_count": len(samples),
            "mature_sample_count": len(mature),
            "min_total_samples": min_total_samples,
            "can_activate": can_activate,
            "activation_status": "active_candidate" if can_activate else "sample_insufficient",
            "report": report,
        }
    )
