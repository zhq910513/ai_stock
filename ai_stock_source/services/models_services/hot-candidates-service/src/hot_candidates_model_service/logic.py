from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any


SCHEMA_VERSION = "candidate_source_analysis_v1"
HOT_MODEL_VERSION = "hot_candidates_v1"
DEFAULT_ENTRY_BASIS = "open_5m_vwap"
DEFAULT_TARGET_RETURN = Decimal("0.08")
DEFAULT_STOP_LOSS_RETURN = Decimal("-0.04")
DEFAULT_TARGET_WINDOW_DAYS = 5
HOT_EVIDENCE_DIMENSIONS = (
    "ths_black_box_prior",
    "candidate_pool_membership",
    "instrument_identity",
    "daily_price_path",
    "stock_moneyflow_rank",
    "board_theme_context",
    "auction_context",
    "minute_trade_context",
    "dynamic_signal_context",
    "news_event_context",
    "market_regime_context",
    "inspection_context",
    "outcome_label_context",
)
HOT_ACTIVE_DIMENSIONS = (
    "ths_black_box_prior",
    "candidate_pool_membership",
    "daily_price_path",
    "stock_moneyflow_rank",
    "auction_context",
)
HOT_AUDIT_ONLY_DIMENSIONS = (
    "instrument_identity",
    "news_event_context",
    "inspection_context",
)
HOT_FUTURE_CALIBRATION_DIMENSIONS = (
    "board_theme_context",
    "minute_trade_context",
    "dynamic_signal_context",
    "market_regime_context",
)
HOT_LABEL_ONLY_DIMENSIONS = ("outcome_label_context",)
HOT_FORBIDDEN_DECISION_SCORING_DIMENSIONS = HOT_AUDIT_ONLY_DIMENSIONS + HOT_FUTURE_CALIBRATION_DIMENSIONS + HOT_LABEL_ONLY_DIMENSIONS
HOT_DAILY_PRICE_PATH_REQUIRED_DAYS = 20


def _decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    if value in (None, ""):
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return default


def _score(value: Any, *, percent: bool = False) -> Decimal:
    numeric = _decimal(value)
    if percent:
        if numeric > 1:
            numeric = numeric / Decimal("100")
    if numeric < 0:
        return Decimal("0")
    if numeric > 1:
        return Decimal("1")
    return numeric


def _score100(value: Any, *, percent: bool = False) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        numeric = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if percent and numeric <= 1:
        numeric = numeric * Decimal("100")
    if not percent and numeric <= 1:
        numeric = numeric * Decimal("100")
    if numeric < 0 or numeric > 100:
        return None
    return numeric.quantize(Decimal("0.000001"))


def _score01_to_100(value: Any) -> Decimal | None:
    return _score100(value, percent=True)


def _score_optional(value: Any, *, percent: bool = False) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        numeric = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if percent and numeric > 1:
        numeric = numeric / Decimal("100")
    if numeric < 0:
        return Decimal("0")
    if numeric > 1:
        return Decimal("1")
    return numeric.quantize(Decimal("0.000001"))


def _moneyflow_value(rank: dict[str, Any], *keys: str) -> Decimal | None:
    for key in keys:
        if rank.get(key) in (None, ""):
            continue
        try:
            return Decimal(str(rank.get(key)))
        except (InvalidOperation, ValueError, TypeError):
            continue
    return None


def _rank_percentile(rank: dict[str, Any], *keys: str) -> Decimal | None:
    pct_keys = [f"{key}_pct_rank" for key in keys] + [f"{key}_percentile" for key in keys]
    for key in pct_keys:
        score = _score_optional(rank.get(key), percent=True)
        if score is not None:
            return score
    return None


def _canonical_ths_prior_source(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"paid_ths_prior", "ths_paid_model", "ths_paid_prior"}:
        return "paid_ths_prior"
    if "paid" in text:
        return "paid_ths_prior"
    if "public" in text or "draft" in text:
        return "public_draft"
    return text or "unknown"


def _stable_json_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(_to_jsonable(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _probability_bucket(score: Decimal) -> str:
    normalized = _score(score)
    pct = normalized * Decimal("100")
    if pct >= Decimal("90"):
        return "p90_100"
    if pct >= Decimal("80"):
        return "p80_90"
    if pct >= Decimal("70"):
        return "p70_80"
    if pct >= Decimal("60"):
        return "p60_70"
    if pct >= Decimal("50"):
        return "p50_60"
    if pct >= Decimal("40"):
        return "p40_50"
    return "p00_40"


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _hot_teacher_model(row: dict[str, Any], teacher_prior: Decimal) -> dict[str, Any]:
    return {
        "provider": "THS",
        "teacher_model_name": "THS_LIMIT_UP_ASSISTANT",
        "teacher_objective": "next_day_limit_up_probability",
        "raw_next_day_limit_up_probability": teacher_prior,
        "probability_bucket": _probability_bucket(teacher_prior),
        "source_rank_no": _positive_int(row.get("source_rank_no")),
        "manual_rank_no": _positive_int(row.get("manual_rank_no")),
        "limit_up_stage": row.get("limit_up_stage"),
        "p_limit_up_source": row.get("p_limit_up_source") or "external_ths_model",
        "p_limit_up_model_version": row.get("p_limit_up_model_version"),
        "immutable_external_prior": True,
    }


def _has_nonempty(value: Any) -> bool:
    if value in (None, "", [], {}):
        return False
    if isinstance(value, dict):
        return any(item not in (None, "", [], {}) for item in value.values())
    return True


def _explicit_due(row: dict[str, Any], *keys: str) -> bool | None:
    for key in keys:
        if key not in row or row.get(key) in (None, ""):
            continue
        value = row.get(key)
        if isinstance(value, bool):
            return value
        normalized = str(value).strip().lower()
        if normalized in {"false", "0", "no", "n", "not_due", "deferred"}:
            return False
        if normalized in {"true", "1", "yes", "y", "due"}:
            return True
    return None


def _dimension(
    *,
    status: str,
    decision_available: bool,
    scoring_role: str,
    source_gap_code: str | None = None,
    facts: dict[str, Any] | None = None,
    row_count: int | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": status,
        "decision_available": decision_available,
        "scoring_role": scoring_role,
    }
    if source_gap_code:
        payload["source_gap_code"] = source_gap_code
    if row_count is not None:
        payload["row_count"] = row_count
    if facts:
        payload["facts"] = facts
    return payload


def _latest_day(values: list[dict[str, Any]]) -> Any:
    if not values:
        return None
    return values[-1].get("trading_day")


def _latest_raw_payload_id(values: list[dict[str, Any]]) -> Any:
    for item in reversed(values):
        if item.get("raw_payload_id") not in (None, ""):
            return item.get("raw_payload_id")
    return None


def _hot_candidate_evidence_packet(row: dict[str, Any], teacher_prior: Decimal) -> dict[str, Any]:
    bars = _recent_bars(row)
    stock_rank = row.get("stock_rank") if isinstance(row.get("stock_rank"), dict) else {}
    theme_ranks = [item for item in list(row.get("theme_ranks") or []) if isinstance(item, dict)]
    auction = row.get("auction_snapshot") if isinstance(row.get("auction_snapshot"), dict) else {}
    minute_bars = [item for item in list(row.get("minute_bars") or []) if isinstance(item, dict)]
    dynamic_signal = row.get("dynamic_signal_bundle") or row.get("dynamic_feature_snapshot")
    news_events = row.get("news_event_context") or row.get("event_impacts") or row.get("news_events")
    market_regime = row.get("market_regime_context") or row.get("market_regime") or row.get("cross_market_context")
    inspection = row.get("inspection_context") or row.get("data_inspection")
    source_gap_codes: list[str] = []

    def record_gap(code: str) -> str:
        source_gap_codes.append(code)
        return code

    ths_present = row.get("p_limit_up") not in (None, "") and teacher_prior > 0
    candidate_present = row.get("batch_id") not in (None, "") and row.get("candidate_id") not in (None, "")
    identity_present = row.get("instrument_id") not in (None, "") and (
        row.get("symbol") not in (None, "") or row.get("symbol_snapshot") not in (None, "")
    )
    daily_gap_code = _recent_ohlc_gap_code(bars, required_days=HOT_DAILY_PRICE_PATH_REQUIRED_DAYS)
    daily_present = daily_gap_code is None
    capital_score = _capital_follow_through_score(row)
    stock_rank_present = _has_nonempty(stock_rank)
    stock_rank_complete = stock_rank_present and capital_score is not None
    auction_present = _has_nonempty(auction)
    auction_due = _explicit_due(row, "auction_context_due", "auction_due")
    if auction_present:
        auction_status = "present"
        auction_available = True
        auction_gap_code = None
        auction_due_state = "captured"
    elif auction_due is False:
        auction_status = "deferred"
        auction_available = False
        auction_gap_code = record_gap("source_deferred:auction_confirmation")
        auction_due_state = "not_due"
    else:
        auction_status = "missing"
        auction_available = False
        auction_gap_code = record_gap("source_gap:auction_confirmation")
        auction_due_state = "due" if auction_due is True else "unknown_or_due"
    dynamic_present = _has_nonempty(dynamic_signal)
    dynamic_facts = dynamic_signal if isinstance(dynamic_signal, dict) else {}
    dynamic_due = _explicit_due(row, "dynamic_signal_due", "dynamic_context_due", "dynamic_feature_due")
    if dynamic_present:
        dynamic_status = "present"
        dynamic_available = True
        dynamic_gap_code = None
        dynamic_due_state = "captured"
    elif dynamic_due is False:
        dynamic_status = "deferred"
        dynamic_available = False
        dynamic_gap_code = record_gap("source_deferred:dynamic_signal_context")
        dynamic_due_state = "not_due"
    else:
        dynamic_status = "missing"
        dynamic_available = False
        dynamic_gap_code = record_gap("source_gap:dynamic_signal_context")
        dynamic_due_state = "due" if dynamic_due is True else "unknown_or_due"

    dimensions = {
        "ths_black_box_prior": _dimension(
            status="present" if ths_present else "missing",
            decision_available=ths_present,
            scoring_role="active",
            source_gap_code=None if ths_present else record_gap("source_gap:ths_black_box_prior"),
            facts={
                "raw_next_day_limit_up_probability": teacher_prior,
                "probability_bucket": _probability_bucket(teacher_prior),
                "limit_up_stage": row.get("limit_up_stage"),
                "source_rank_no": _positive_int(row.get("source_rank_no")),
                "manual_rank_no": _positive_int(row.get("manual_rank_no")),
            },
        ),
        "candidate_pool_membership": _dimension(
            status="present" if candidate_present else "missing",
            decision_available=candidate_present,
            scoring_role="active",
            source_gap_code=None if candidate_present else record_gap("source_gap:candidate_pool_membership"),
            facts={
                "batch_id": row.get("batch_id"),
                "candidate_id": row.get("candidate_id"),
                "trade_date": row.get("trade_date") or row.get("trading_day") or row.get("as_of_trading_day"),
            },
        ),
        "instrument_identity": _dimension(
            status="present" if identity_present else "missing",
            decision_available=identity_present,
            scoring_role="audit_only",
            source_gap_code=None if identity_present else record_gap("source_gap:instrument_identity"),
            facts={
                "instrument_id": row.get("instrument_id"),
                "symbol": row.get("symbol") or row.get("symbol_snapshot"),
                "exchange": row.get("exchange"),
                "board": row.get("board"),
                "name": row.get("name") or row.get("name_at_snapshot"),
            },
        ),
        "daily_price_path": _dimension(
            status="present" if daily_present else "missing",
            decision_available=daily_present,
            scoring_role="active",
            source_gap_code=None if daily_present else record_gap(daily_gap_code),
            row_count=len(bars),
            facts={
                "required_lookback_days": HOT_DAILY_PRICE_PATH_REQUIRED_DAYS,
                "valid_ohlc_required": True,
                "latest_trading_day": _latest_day(bars),
                "latest_raw_payload_id": _latest_raw_payload_id(bars),
                "latest_provider": bars[-1].get("provider") if bars else None,
            },
        ),
        "stock_moneyflow_rank": _dimension(
            status="present" if stock_rank_complete else "missing",
            decision_available=stock_rank_complete,
            scoring_role="active",
            source_gap_code=None
            if stock_rank_complete
            else record_gap("source_gap:stock_moneyflow_rank" if not stock_rank_present else "source_gap:stock_moneyflow_rank_components"),
            facts={
                "rank_no": stock_rank.get("rank_no"),
                "main_net_inflow": stock_rank.get("main_net_inflow"),
                "large_order_net_inflow": stock_rank.get("large_order_net_inflow") or stock_rank.get("large_net_inflow"),
                "super_large_order_net_inflow": stock_rank.get("super_large_order_net_inflow")
                or stock_rank.get("super_large_net_inflow"),
                "main_net_inflow_pct_rank": stock_rank.get("main_net_inflow_pct_rank"),
                "large_order_net_inflow_pct_rank": stock_rank.get("large_order_net_inflow_pct_rank"),
                "super_large_order_net_inflow_pct_rank": stock_rank.get("super_large_order_net_inflow_pct_rank"),
                "capital_follow_through_score": capital_score,
                "captured_at": stock_rank.get("captured_at"),
                "raw_payload_id": stock_rank.get("raw_payload_id"),
            },
        ),
        "board_theme_context": _dimension(
            status="present" if theme_ranks else "missing",
            decision_available=bool(theme_ranks),
            scoring_role="future_calibration",
            source_gap_code=None if theme_ranks else record_gap("source_gap:board_theme_context"),
            row_count=len(theme_ranks),
            facts={
                "theme_ids": [item.get("theme_id") for item in theme_ranks[:10]],
                "theme_names": [item.get("theme_name") for item in theme_ranks[:10]],
                "best_rank_no": min(
                    [int(item["rank_no"]) for item in theme_ranks if str(item.get("rank_no") or "").isdigit()],
                    default=None,
                ),
            },
        ),
        "auction_context": _dimension(
            status=auction_status,
            decision_available=auction_available,
            scoring_role="active",
            source_gap_code=auction_gap_code,
            facts={
                "due_state": auction_due_state,
                "matched_amount": auction.get("matched_amount"),
                "imbalance_ratio": auction.get("imbalance_ratio"),
                "captured_at": auction.get("captured_at"),
                "quote_time": auction.get("quote_time"),
                "raw_payload_id": auction.get("raw_payload_id"),
            },
        ),
        "minute_trade_context": _dimension(
            status="present" if minute_bars else "missing",
            decision_available=bool(minute_bars),
            scoring_role="future_calibration",
            source_gap_code=None if minute_bars else record_gap("source_gap:minute_trade_context"),
            row_count=len(minute_bars),
            facts={"latest_trading_day": _latest_day(minute_bars), "latest_raw_payload_id": _latest_raw_payload_id(minute_bars)},
        ),
        "dynamic_signal_context": _dimension(
            status=dynamic_status,
            decision_available=dynamic_available,
            scoring_role="future_calibration",
            source_gap_code=dynamic_gap_code,
            facts={
                "due_state": dynamic_due_state,
                "snapshot_id": dynamic_facts.get("snapshot_id"),
                "latest_id": dynamic_facts.get("latest_id"),
                "as_of_time": dynamic_facts.get("as_of_time"),
                "window_seconds": dynamic_facts.get("window_seconds"),
                "data_quality": dynamic_facts.get("data_quality"),
                "source_gap_codes": dynamic_facts.get("source_gap_codes"),
                "raw_payload_id": dynamic_facts.get("latest_id") or dynamic_facts.get("snapshot_id"),
            },
        ),
        "news_event_context": _dimension(
            status="present" if _has_nonempty(news_events) else "missing",
            decision_available=_has_nonempty(news_events),
            scoring_role="audit_only",
            source_gap_code=None if _has_nonempty(news_events) else record_gap("source_gap:news_event_context"),
            row_count=len(news_events) if isinstance(news_events, list) else None,
            facts={
                "top_event_ids": [
                    item.get("event_id") for item in list(news_events or [])[:5] if isinstance(item, dict)
                ],
                "top_impact_scores": [
                    item.get("impact_score") for item in list(news_events or [])[:5] if isinstance(item, dict)
                ],
                "latest_first_seen_at": next(
                    (
                        item.get("first_seen_at")
                        for item in list(news_events or [])
                        if isinstance(item, dict) and item.get("first_seen_at") not in (None, "")
                    ),
                    None,
                ),
                "raw_payload_id": next(
                    (
                        item.get("impact_snapshot_id")
                        for item in list(news_events or [])
                        if isinstance(item, dict) and item.get("impact_snapshot_id") not in (None, "")
                    ),
                    None,
                ),
            },
        ),
        "market_regime_context": _dimension(
            status="present" if _has_nonempty(market_regime) else "missing",
            decision_available=_has_nonempty(market_regime),
            scoring_role="future_calibration",
            source_gap_code=None if _has_nonempty(market_regime) else record_gap("source_gap:market_regime_context"),
            facts={
                "snapshot_id": market_regime.get("snapshot_id") if isinstance(market_regime, dict) else None,
                "trading_day": market_regime.get("trading_day") if isinstance(market_regime, dict) else None,
                "as_of_time": market_regime.get("as_of_time") if isinstance(market_regime, dict) else None,
                "data_quality": market_regime.get("data_quality") if isinstance(market_regime, dict) else None,
                "raw_payload_id": market_regime.get("snapshot_id") if isinstance(market_regime, dict) else None,
            },
        ),
        "inspection_context": _dimension(
            status="present" if _has_nonempty(inspection) else "missing",
            decision_available=_has_nonempty(inspection),
            scoring_role="audit_only",
            source_gap_code=None if _has_nonempty(inspection) else record_gap("source_gap:inspection_context"),
            facts={
                "subject_id": inspection.get("subject_id") if isinstance(inspection, dict) else None,
                "run_id": inspection.get("run_id") if isinstance(inspection, dict) else None,
                "inspection_status": inspection.get("inspection_status") if isinstance(inspection, dict) else None,
                "completeness_score": inspection.get("completeness_score") if isinstance(inspection, dict) else None,
                "created_at": inspection.get("created_at") if isinstance(inspection, dict) else None,
                "raw_payload_id": inspection.get("subject_id") if isinstance(inspection, dict) else None,
            },
        ),
        "outcome_label_context": _dimension(
            status="future_label_only",
            decision_available=False,
            scoring_role="label_only",
            facts={
                "allowed_after_decision": True,
                "cannot_score_current_decision": True,
            },
        ),
    }
    missing_active_dimension_codes = _missing_dimension_codes(dimensions, HOT_ACTIVE_DIMENSIONS)
    missing_audit_dimension_codes = _missing_dimension_codes(dimensions, HOT_AUDIT_ONLY_DIMENSIONS)
    missing_future_calibration_dimension_codes = _missing_dimension_codes(
        dimensions, HOT_FUTURE_CALIBRATION_DIMENSIONS
    )
    deferred_dimension_codes = _dimension_codes_by_status(
        dimensions, HOT_ACTIVE_DIMENSIONS + HOT_FUTURE_CALIBRATION_DIMENSIONS, {"deferred"}
    )
    present_count = sum(1 for item in dimensions.values() if item["status"] == "present")
    active_count = len(HOT_ACTIVE_DIMENSIONS)
    return {
        "contract_kind": "hot_candidate_evidence_packet_v1",
        "capture_phase": "wide_evidence_accumulation",
        "black_box_boundary": {
            "cannot_explain_ths_private_dimensions": True,
            "can_only_validate_p_limit_up_with_local_evidence": True,
        },
        "data_policy": {
            "capture_broad_dimensions": True,
            "score_only_promoted_dimensions": True,
            "missing_evidence_is_not_neutral": True,
            "future_evidence_for_labeling_only": True,
        },
        "required_dimensions": list(HOT_EVIDENCE_DIMENSIONS),
        "present_dimension_count": present_count,
        "required_dimension_count": len(HOT_EVIDENCE_DIMENSIONS),
        "active_dimension_count": active_count,
        "decision_scoring_manifest": {
            "contract_kind": "hot_candidate_decision_scoring_manifest_v1",
            "active_dimension_codes": list(HOT_ACTIVE_DIMENSIONS),
            "audit_only_dimension_codes": list(HOT_AUDIT_ONLY_DIMENSIONS),
            "future_calibration_dimension_codes": list(HOT_FUTURE_CALIBRATION_DIMENSIONS),
            "label_only_dimension_codes": list(HOT_LABEL_ONLY_DIMENSIONS),
            "forbidden_decision_scoring_dimension_codes": list(HOT_FORBIDDEN_DECISION_SCORING_DIMENSIONS),
            "formula_inputs": [
                "ths_teacher_prior_score",
                "local_confirmation_score",
                "tradability_adjustment_score",
                "upside_room_score",
                "overheating_failure_risk",
            ],
            "rule": "wide_capture_narrow_v1_scoring_later_calibration",
        },
        "missing_active_dimension_codes": missing_active_dimension_codes,
        "missing_audit_dimension_codes": missing_audit_dimension_codes,
        "missing_future_calibration_dimension_codes": missing_future_calibration_dimension_codes,
        "deferred_dimension_codes": deferred_dimension_codes,
        "source_gap_codes": sorted(set(source_gap_codes)),
        "dimensions": dimensions,
    }


def _missing_dimension_codes(dimensions: dict[str, dict[str, Any]], dimension_codes: tuple[str, ...]) -> list[str]:
    return _dimension_codes_by_status(dimensions, dimension_codes, {"missing"})


def _dimension_codes_by_status(
    dimensions: dict[str, dict[str, Any]], dimension_codes: tuple[str, ...], statuses: set[str]
) -> list[str]:
    return sorted(
        code for code in dimension_codes if (dimensions.get(code) or {}).get("status") in statuses
    )


def _hot_distillation_tags(
    *,
    teacher_prior: Decimal,
    local_confirmation: Decimal | None,
    tradability: Decimal | None,
    capital: Decimal | None,
    auction: Decimal | None,
    overheat: Decimal | None,
    warnings: list[str],
    hard_blocks: list[str],
) -> list[str]:
    tags: list[str] = []
    missing_dimensions = {
        "local_confirmation": local_confirmation,
        "tradability": tradability,
        "capital": capital,
        "auction": auction,
        "overheat": overheat,
    }
    for name, value in missing_dimensions.items():
        if value is None:
            tags.append(f"{name}_missing")
    if teacher_prior >= Decimal("0.70") and local_confirmation is not None and local_confirmation < Decimal("0.50"):
        tags.append("ths_high_score_local_confirmation_weak")
    if teacher_prior >= Decimal("0.70") and auction is not None and auction < Decimal("0.45"):
        tags.append("ths_high_score_auction_weak")
    if teacher_prior >= Decimal("0.70") and tradability is not None and tradability < Decimal("0.48"):
        tags.append("ths_high_score_tradability_weak")
    if teacher_prior >= Decimal("0.70") and overheat is not None and overheat >= Decimal("0.60"):
        tags.append("ths_high_score_overheated")
    if teacher_prior <= Decimal("0.45") and local_confirmation is not None and local_confirmation >= Decimal("0.62"):
        tags.append("ths_low_score_local_confirmation_strong")
    if teacher_prior <= Decimal("0.45") and capital is not None and capital >= Decimal("0.60"):
        tags.append("ths_low_score_capital_follow_through")
    if warnings:
        tags.append("evidence_gap_requires_review")
    if hard_blocks:
        tags.append("hard_blocked_before_distillation")
    return tags


def _hot_distortion_watch_inputs(
    *,
    teacher_prior: Decimal,
    local_confirmation: Decimal | None,
    tradability: Decimal | None,
    capital: Decimal | None,
    auction: Decimal | None,
    overheat: Decimal | None,
    evidence_packet: dict[str, Any],
) -> dict[str, Any]:
    weak_active_evidence: list[dict[str, Any]] = []
    if local_confirmation is not None and local_confirmation < Decimal("0.50"):
        weak_active_evidence.append(
            {"code": "local_confirmation_weak", "score": local_confirmation, "threshold": Decimal("0.50")}
        )
    if auction is not None and auction < Decimal("0.45"):
        weak_active_evidence.append(
            {"code": "auction_confirmation_weak", "score": auction, "threshold": Decimal("0.45")}
        )
    if tradability is not None and tradability < Decimal("0.48"):
        weak_active_evidence.append(
            {"code": "tradability_weak", "score": tradability, "threshold": Decimal("0.48")}
        )
    if capital is not None and capital < Decimal("0.45"):
        weak_active_evidence.append(
            {"code": "capital_follow_through_weak", "score": capital, "threshold": Decimal("0.45")}
        )
    if overheat is not None and overheat >= Decimal("0.60"):
        weak_active_evidence.append(
            {"code": "overheat_high", "score": overheat, "threshold": Decimal("0.60"), "direction": "above"}
        )
    return {
        "contract_kind": "ths_teacher_distortion_watch_inputs_v1",
        "teacher_prior_bucket": _probability_bucket(teacher_prior),
        "high_score_failure_watch": bool(teacher_prior >= Decimal("0.70") and weak_active_evidence),
        "low_score_success_watch": bool(
            teacher_prior <= Decimal("0.45")
            and (
                (local_confirmation is not None and local_confirmation >= Decimal("0.62"))
                or (capital is not None and capital >= Decimal("0.60"))
            )
        ),
        "score_inputs": {
            "local_confirmation_score": local_confirmation,
            "tradability_adjustment_score": tradability,
            "capital_follow_through_score": capital,
            "auction_confirmation_score": auction,
            "overheating_failure_risk": overheat,
        },
        "weak_active_evidence": weak_active_evidence,
        "missing_active_dimension_codes": list(evidence_packet.get("missing_active_dimension_codes") or []),
        "missing_future_calibration_dimension_codes": list(
            evidence_packet.get("missing_future_calibration_dimension_codes") or []
        ),
        "deferred_dimension_codes": list(evidence_packet.get("deferred_dimension_codes") or []),
    }


def _hot_teacher_distillation_contract(
    *,
    teacher_prior: Decimal,
    local_confirmation: Decimal | None,
    tradability: Decimal | None,
    capital: Decimal | None,
    auction: Decimal | None,
    overheat: Decimal | None,
    warnings: list[str],
    distillation_tags: list[str],
    evidence_packet: dict[str, Any],
) -> dict[str, Any]:
    watch_inputs = _hot_distortion_watch_inputs(
        teacher_prior=teacher_prior,
        local_confirmation=local_confirmation,
        tradability=tradability,
        capital=capital,
        auction=auction,
        overheat=overheat,
        evidence_packet=evidence_packet,
    )
    return {
        "role": "student_calibration_layer",
        "diagnostic_contract_kind": "ths_teacher_distortion_diagnostics_v1",
        "calibration_status": "no_historical_calibration_yet",
        "double_count_guard": True,
        "diagnostic_tags": distillation_tags,
        "teacher_prior_bucket": _probability_bucket(teacher_prior),
        "high_score_failure_watch": bool(watch_inputs.get("high_score_failure_watch")),
        "low_score_success_watch": bool(watch_inputs.get("low_score_success_watch")),
        "missing_evidence_not_neutralized": bool(
            warnings or evidence_packet.get("missing_active_dimension_codes")
        ),
        "active_evidence_gap_codes": list(evidence_packet.get("missing_active_dimension_codes") or []),
        "future_calibration_gap_codes": list(
            evidence_packet.get("missing_future_calibration_dimension_codes") or []
        ),
        "deferred_dimension_codes": list(evidence_packet.get("deferred_dimension_codes") or []),
        "weak_active_evidence": list(watch_inputs.get("weak_active_evidence") or []),
        "distortion_watch_inputs": watch_inputs,
        "cannot_activate_weights": True,
        "weight_learning_gate": "requires_mature_t1_labels_and_frozen_decision_evidence",
    }


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return {}


def _bool_from_mapping(value: Any, key: str) -> bool:
    item = _mapping(value)
    return bool(item.get(key))


def _text_from_mapping(value: Any, key: str, default: str = "") -> str:
    item = _mapping(value)
    raw = item.get(key)
    return default if raw in (None, "") else str(raw)


def _analysis_hot_scores(analysis: Any) -> dict[str, Any]:
    row = _mapping(analysis)
    scores = row.get("source_specific_scores") or {}
    return scores.get("hot") if isinstance(scores.get("hot"), dict) else {}


def _count_codes(target: dict[str, int], codes: list[Any]) -> None:
    for code in codes:
        normalized = str(code)
        if not normalized:
            continue
        target[normalized] = target.get(normalized, 0) + 1


def _count_weak_evidence(target: dict[str, int], weak_items: list[Any]) -> None:
    for item in weak_items:
        payload = _mapping(item)
        code = str(payload.get("code") or "")
        if not code:
            continue
        target[code] = target.get(code, 0) + 1


def _rate(success_count: int, total_count: int) -> Decimal | None:
    if total_count <= 0:
        return None
    return (Decimal(success_count) / Decimal(total_count) * Decimal("100")).quantize(Decimal("0.000001"))


def _compact_hot_distortion_sample(analysis: Any, label: Any, *, sample_type: str) -> dict[str, Any]:
    row = _mapping(analysis)
    label_row = _mapping(label)
    hot_scores = _analysis_hot_scores(row)
    distillation = _mapping(hot_scores.get("teacher_distillation"))
    packet = _mapping(hot_scores.get("hot_candidate_evidence_packet"))
    teacher_prior = _decimal(hot_scores.get("ths_teacher_prior_score"))
    weak_items = [_mapping(item) for item in list(distillation.get("weak_active_evidence") or [])]
    return {
        "sample_type": sample_type,
        "analysis_id": row.get("analysis_id"),
        "label_id": label_row.get("label_id"),
        "trade_date": row.get("trade_date"),
        "instrument_id": row.get("instrument_id"),
        "symbol": row.get("symbol") or row.get("symbol_snapshot"),
        "limit_up_stage": (_mapping(hot_scores.get("teacher_model"))).get("limit_up_stage"),
        "teacher_prior_score": teacher_prior,
        "teacher_prior_bucket": distillation.get("teacher_prior_bucket")
        or (_mapping(hot_scores.get("teacher_model"))).get("probability_bucket")
        or _probability_bucket(teacher_prior),
        "result_class": label_row.get("result_class"),
        "label_status": label_row.get("label_status"),
        "realizable_hit_before_risk": bool(label_row.get("realizable_hit_before_risk")),
        "max_favorable_excursion": label_row.get("max_favorable_excursion"),
        "diagnostic_tags": list(distillation.get("diagnostic_tags") or []),
        "weak_active_evidence_codes": [str(item.get("code")) for item in weak_items if item.get("code")],
        "active_evidence_gap_codes": list(distillation.get("active_evidence_gap_codes") or []),
        "future_calibration_gap_codes": list(distillation.get("future_calibration_gap_codes") or []),
        "deferred_dimension_codes": list(packet.get("deferred_dimension_codes") or []),
    }


def _sorted_count_rows(counts: dict[str, int], *, limit: int = 20) -> list[dict[str, Any]]:
    return [
        {"code": code, "count": count}
        for code, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]
    ]


def build_hot_candidate_distortion_report(
    analyses: list[Any],
    labels: list[Any],
    *,
    trade_date: Any = None,
    min_learning_samples: int = 120,
) -> dict[str, Any]:
    hot_analyses = [item for item in analyses if _text_from_mapping(item, "candidate_source") == "hot_candidates"]
    analysis_by_id = {
        int(_mapping(item).get("analysis_id")): item
        for item in hot_analyses
        if _mapping(item).get("analysis_id") is not None
    }
    labels_by_analysis = {
        int(_mapping(item).get("analysis_id")): item
        for item in labels
        if _mapping(item).get("analysis_id") is not None
        and _text_from_mapping(item, "candidate_source") == "hot_candidates"
    }
    bucket_stats: dict[str, dict[str, Any]] = {}
    tag_counts: dict[str, int] = {}
    weak_counts: dict[str, int] = {}
    active_gap_counts: dict[str, int] = {}
    future_gap_counts: dict[str, int] = {}
    result_counts: dict[str, int] = {}
    high_score_failure_samples: list[dict[str, Any]] = []
    low_score_success_samples: list[dict[str, Any]] = []
    warning_codes: list[str] = []
    evaluated_count = 0
    success_count = 0
    high_score_evaluated_count = 0
    high_score_failure_count = 0
    low_score_evaluated_count = 0
    low_score_success_count = 0

    for analysis_id, analysis in analysis_by_id.items():
        hot_scores = _analysis_hot_scores(analysis)
        distillation = _mapping(hot_scores.get("teacher_distillation"))
        teacher = _mapping(hot_scores.get("teacher_model"))
        teacher_prior = _decimal(hot_scores.get("ths_teacher_prior_score"))
        bucket = str(distillation.get("teacher_prior_bucket") or teacher.get("probability_bucket") or _probability_bucket(teacher_prior))
        bucket_row = bucket_stats.setdefault(
            bucket,
            {
                "label": bucket,
                "sample_count": 0,
                "evaluated_count": 0,
                "success_count": 0,
                "failure_count": 0,
                "high_score_failure_count": 0,
                "low_score_success_count": 0,
            },
        )
        bucket_row["sample_count"] += 1
        _count_codes(tag_counts, list(distillation.get("diagnostic_tags") or []))
        _count_weak_evidence(weak_counts, list(distillation.get("weak_active_evidence") or []))
        _count_codes(active_gap_counts, list(distillation.get("active_evidence_gap_codes") or []))
        _count_codes(future_gap_counts, list(distillation.get("future_calibration_gap_codes") or []))

        label = labels_by_analysis.get(analysis_id)
        if label is None:
            continue
        label_status = _text_from_mapping(label, "label_status")
        if label_status != "evaluated":
            result_counts[label_status or "not_evaluated"] = result_counts.get(label_status or "not_evaluated", 0) + 1
            continue
        result_class = _text_from_mapping(label, "result_class", "evaluated")
        result_counts[result_class] = result_counts.get(result_class, 0) + 1
        evaluated_count += 1
        bucket_row["evaluated_count"] += 1
        is_success = _bool_from_mapping(label, "realizable_hit_before_risk")
        if is_success:
            success_count += 1
            bucket_row["success_count"] += 1
        else:
            bucket_row["failure_count"] += 1
        if teacher_prior >= Decimal("0.70"):
            high_score_evaluated_count += 1
            if not is_success:
                high_score_failure_count += 1
                bucket_row["high_score_failure_count"] += 1
                high_score_failure_samples.append(
                    _compact_hot_distortion_sample(analysis, label, sample_type="high_score_failure")
                )
        if teacher_prior <= Decimal("0.45"):
            low_score_evaluated_count += 1
            if is_success:
                low_score_success_count += 1
                bucket_row["low_score_success_count"] += 1
                low_score_success_samples.append(
                    _compact_hot_distortion_sample(analysis, label, sample_type="low_score_success")
                )

    if not hot_analyses:
        warning_codes.append("hot_candidate_analysis_empty")
    if evaluated_count == 0:
        warning_codes.append("hot_candidate_evaluated_label_empty")
    if evaluated_count < min_learning_samples:
        warning_codes.append("hot_candidate_learning_sample_insufficient")

    bucket_rows = []
    for bucket, row in bucket_stats.items():
        evaluated = int(row["evaluated_count"])
        success = int(row["success_count"])
        bucket_rows.append(
            {
                **row,
                "hit_rate_pct": _rate(success, evaluated),
                "failure_rate_pct": _rate(int(row["failure_count"]), evaluated),
            }
        )
    bucket_rows.sort(key=lambda item: str(item["label"]), reverse=True)

    high_score_failure_samples.sort(
        key=lambda item: (_decimal(item.get("teacher_prior_score")), str(item.get("symbol") or "")),
        reverse=True,
    )
    low_score_success_samples.sort(
        key=lambda item: (_decimal(item.get("teacher_prior_score")), str(item.get("symbol") or "")),
    )

    return {
        "contract_kind": "hot_candidate_teacher_distortion_report_v1",
        "status": "ready" if hot_analyses else "empty",
        "candidate_source": "hot_candidates",
        "trade_date": trade_date,
        "objective": {
            "target_return": DEFAULT_TARGET_RETURN,
            "target_window_days": DEFAULT_TARGET_WINDOW_DAYS,
            "entry_basis": DEFAULT_ENTRY_BASIS,
            "success_label": "realizable_hit_before_risk",
        },
        "sample_counts": {
            "analysis_count": len(hot_analyses),
            "label_count": len(labels_by_analysis),
            "evaluated_count": evaluated_count,
            "success_count": success_count,
            "failure_count": max(evaluated_count - success_count, 0),
            "high_score_evaluated_count": high_score_evaluated_count,
            "high_score_failure_count": high_score_failure_count,
            "low_score_evaluated_count": low_score_evaluated_count,
            "low_score_success_count": low_score_success_count,
        },
        "summary_metrics": {
            "overall_hit_rate_pct": _rate(success_count, evaluated_count),
            "high_score_failure_rate_pct": _rate(high_score_failure_count, high_score_evaluated_count),
            "low_score_success_rate_pct": _rate(low_score_success_count, low_score_evaluated_count),
        },
        "teacher_prior_buckets": bucket_rows,
        "result_class_distribution": _sorted_count_rows(result_counts),
        "diagnostic_tag_distribution": _sorted_count_rows(tag_counts),
        "weak_active_evidence_distribution": _sorted_count_rows(weak_counts),
        "active_gap_distribution": _sorted_count_rows(active_gap_counts),
        "future_calibration_gap_distribution": _sorted_count_rows(future_gap_counts),
        "top_failure_patterns": _sorted_count_rows({**weak_counts, **active_gap_counts}),
        "high_score_failure_samples": high_score_failure_samples[:20],
        "low_score_success_samples": low_score_success_samples[:20],
        "learning_gate": {
            "can_activate_weights": False,
            "current_evaluated_samples": evaluated_count,
            "minimum_required_samples": min_learning_samples,
            "reason": "requires_mature_t1_labels_and_frozen_decision_evidence",
        },
        "warning_codes": warning_codes,
    }


def _to_jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value.quantize(Decimal("0.000001")))
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(item) for item in value]
    return str(value)


def _parse_datetime_utc(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _dimension_captured_at_utc(dimension: dict[str, Any], fallback: datetime) -> datetime:
    facts = dimension.get("facts") if isinstance(dimension.get("facts"), dict) else {}
    for key in ("captured_at", "captured_at_utc", "quote_time", "as_of_time", "updated_at"):
        parsed = _parse_datetime_utc(facts.get(key))
        if parsed is not None:
            return parsed
    return fallback


def _late_evidence_domains(dimensions: dict[str, Any], as_of_time_utc: datetime) -> list[str]:
    late_domains: list[str] = []
    for domain, raw_dimension in sorted(dimensions.items()):
        if not isinstance(raw_dimension, dict):
            continue
        if raw_dimension.get("status") != "present":
            continue
        captured_at = _dimension_captured_at_utc(raw_dimension, as_of_time_utc)
        if captured_at > as_of_time_utc:
            late_domains.append(str(domain))
    return late_domains


def _recent_bars(row: dict[str, Any]) -> list[dict[str, Any]]:
    bars = [dict(item) for item in list(row.get("daily_bars") or []) if isinstance(item, dict)]
    return sorted(bars, key=lambda item: str(item.get("trading_day") or ""))


def _bar_has_valid_ohlc(bar: dict[str, Any]) -> bool:
    open_price = _decimal(bar.get("open_price") or bar.get("open"))
    high_price = _decimal(bar.get("high_price") or bar.get("high"))
    low_price = _decimal(bar.get("low_price") or bar.get("low"))
    close_price = _decimal(bar.get("close_price") or bar.get("close"))
    if any(not value.is_finite() or value <= 0 for value in (open_price, high_price, low_price, close_price)):
        return False
    return high_price >= max(open_price, close_price) and low_price <= min(open_price, close_price) and high_price >= low_price


def _recent_ohlc_gap_code(bars: list[dict[str, Any]], *, required_days: int) -> str | None:
    if len(bars) < required_days:
        return "source_gap:daily_bar_lookback"
    if not all(_bar_has_valid_ohlc(bar) for bar in bars[-required_days:]):
        return "source_gap:daily_ohlc_invalid"
    return None


def _has_valid_recent_ohlc_path(bars: list[dict[str, Any]], *, required_days: int) -> bool:
    return _recent_ohlc_gap_code(bars, required_days=required_days) is None


def _latest_bar(row: dict[str, Any]) -> dict[str, Any] | None:
    bars = _recent_bars(row)
    return bars[-1] if bars else None


def _recent_return_score(row: dict[str, Any], *, days: int = 3) -> Decimal:
    bars = _recent_bars(row)
    if len(bars) <= days:
        return Decimal("0.35")
    start = _decimal(bars[-days - 1].get("close_price"))
    end = _decimal(bars[-1].get("close_price"))
    if start <= 0 or end <= 0:
        return Decimal("0.35")
    change = (end / start) - Decimal("1")
    return _score((change + Decimal("0.04")) / Decimal("0.16"))


def _upside_room_score(row: dict[str, Any]) -> Decimal:
    bars = _recent_bars(row)
    if len(bars) < 5:
        return Decimal("0.45")
    latest_close = _decimal(bars[-1].get("close_price"))
    recent_high = max((_decimal(bar.get("high_price")) for bar in bars[-20:]), default=Decimal("0"))
    if latest_close <= 0 or recent_high <= 0:
        return Decimal("0.45")
    distance = (recent_high / latest_close) - Decimal("1")
    if distance >= Decimal("0.12"):
        return Decimal("0.85")
    if distance >= Decimal("0.08"):
        return Decimal("0.70")
    if distance >= Decimal("0.05"):
        return Decimal("0.52")
    return Decimal("0.28")


def _liquidity_score(row: dict[str, Any]) -> Decimal:
    latest = _latest_bar(row)
    if not latest:
        return Decimal("0.35")
    amount = _decimal(latest.get("amount"))
    if amount <= 0:
        close_price = _decimal(latest.get("close_price"))
        volume = _decimal(latest.get("volume"))
        if close_price > 0 and volume > 0:
            amount = close_price * volume
    turnover = _decimal(latest.get("turnover_rate"))
    amount_score = _score(amount / Decimal("100000000"))
    turnover_score = _score(turnover / Decimal("10"))
    return (amount_score * Decimal("0.65") + turnover_score * Decimal("0.35")).quantize(Decimal("0.000001"))


def _stock_flow_score(row: dict[str, Any]) -> Decimal:
    rank = row.get("stock_rank") if isinstance(row.get("stock_rank"), dict) else {}
    rank_no = _decimal(rank.get("rank_no"), Decimal("500"))
    inflow = _decimal(rank.get("main_net_inflow"))
    rank_score = Decimal("0.50")
    if rank_no > 0:
        rank_score = _score((Decimal("500") - rank_no) / Decimal("500"))
    inflow_score = _score((inflow / Decimal("100000000") + Decimal("0.5")) / Decimal("1.5"))
    return (rank_score * Decimal("0.55") + inflow_score * Decimal("0.45")).quantize(Decimal("0.000001"))


def _capital_follow_through_score(row: dict[str, Any]) -> Decimal | None:
    rank = row.get("stock_rank") if isinstance(row.get("stock_rank"), dict) else {}
    if not rank:
        return None
    main = _moneyflow_value(rank, "main_net_inflow")
    large = _moneyflow_value(rank, "large_order_net_inflow", "large_net_inflow")
    super_large = _moneyflow_value(rank, "super_large_order_net_inflow", "super_large_net_inflow")
    main_rank = _rank_percentile(rank, "main_net_inflow")
    large_rank = _rank_percentile(rank, "large_order_net_inflow", "large_net_inflow")
    super_large_rank = _rank_percentile(rank, "super_large_order_net_inflow", "super_large_net_inflow")
    if any(value is None for value in (main, large, super_large, main_rank, large_rank, super_large_rank)):
        return None
    score = Decimal("0.50") * main_rank + Decimal("0.30") * large_rank + Decimal("0.20") * super_large_rank
    if main > 0 and large < 0:
        score *= Decimal("0.75")
    if main < 0 and super_large < 0:
        score *= Decimal("0.60")
    return _score(score).quantize(Decimal("0.000001"))


def _auction_amount_score(auction: dict[str, Any]) -> Decimal | None:
    matched_amount = _moneyflow_value(auction, "matched_amount")
    if matched_amount is None:
        return None
    return _score(matched_amount / Decimal("20000000")).quantize(Decimal("0.000001"))


def _auction_price_position_score(row: dict[str, Any], auction: dict[str, Any]) -> Decimal | None:
    auction_price = _moneyflow_value(
        auction,
        "virtual_open_price",
        "open_price",
        "auction_price",
        "matched_price",
        "price",
    )
    latest = _latest_bar(row) or {}
    prev_close = _moneyflow_value(auction, "prev_close_price", "previous_close_price") or _moneyflow_value(
        latest, "close_price"
    )
    limit_up_price = _moneyflow_value(auction, "limit_up_price")
    if limit_up_price is None and prev_close is not None and prev_close > 0:
        limit_up_price = prev_close * Decimal("1.10")
    if auction_price is None or prev_close is None or limit_up_price is None or limit_up_price <= prev_close:
        return None
    return _score((auction_price - prev_close) / (limit_up_price - prev_close)).quantize(Decimal("0.000001"))


def _imbalance_support_score(auction: dict[str, Any]) -> Decimal | None:
    imbalance = _moneyflow_value(auction, "imbalance_ratio")
    if imbalance is None:
        return None
    return _score((imbalance + Decimal("0.25")) / Decimal("0.75")).quantize(Decimal("0.000001"))


def _auction_confirmation_score(row: dict[str, Any]) -> Decimal | None:
    auction = row.get("auction_snapshot") if isinstance(row.get("auction_snapshot"), dict) else {}
    if not auction:
        return None
    amount_score = _auction_amount_score(auction)
    price_score = _auction_price_position_score(row, auction)
    imbalance_score = _imbalance_support_score(auction)
    if any(score is None for score in (amount_score, price_score, imbalance_score)):
        return None
    return (
        Decimal("0.40") * amount_score
        + Decimal("0.30") * price_score
        + Decimal("0.30") * imbalance_score
    ).quantize(Decimal("0.000001"))


def _open_reachability(row: dict[str, Any]) -> str:
    auction = row.get("auction_snapshot") if isinstance(row.get("auction_snapshot"), dict) else {}
    explicit = row.get("open_reachability") or auction.get("open_reachability")
    if explicit not in (None, ""):
        return str(explicit)
    matched_volume = _moneyflow_value(auction, "matched_volume")
    auction_volume = _moneyflow_value(auction, "auction_volume") or matched_volume
    auction_price = _moneyflow_value(auction, "virtual_open_price", "open_price", "auction_price")
    limit_up_price = _moneyflow_value(auction, "limit_up_price")
    if auction_price is not None and limit_up_price is not None and auction_price >= limit_up_price:
        if auction_volume is None or auction_volume <= 0:
            return "blocked_limit_up_no_fill"
        if auction_volume < Decimal("10000"):
            return "hard_to_buy_limit_up_thin_liquidity"
    if auction:
        return "reachable"
    return "unknown"


def _open_reachability_score(row: dict[str, Any]) -> Decimal | None:
    mapping = {
        "reachable": Decimal("1"),
        "hard_to_buy_limit_up_thin_liquidity": Decimal("0.40"),
        "blocked_limit_up_no_fill": None,
        "blocked_no_open_trade": None,
        "unknown": None,
    }
    return mapping.get(_open_reachability(row), None)


def _open_5m_liquidity_score(row: dict[str, Any]) -> Decimal | None:
    explicit = _score_optional(row.get("open_5m_liquidity_score"), percent=True)
    if explicit is not None:
        return explicit
    minute_bars = [item for item in list(row.get("minute_bars") or []) if isinstance(item, dict)]
    if len(minute_bars) >= 5:
        total_amount = sum((_decimal(item.get("amount")) for item in minute_bars[:5]), Decimal("0"))
        return _score(total_amount / Decimal("20000000")).quantize(Decimal("0.000001"))
    return _liquidity_score(row)


def _price_gap_reasonable_score(row: dict[str, Any]) -> Decimal | None:
    explicit = _score_optional(row.get("price_gap_reasonable_score"), percent=True)
    if explicit is not None:
        return explicit
    auction = row.get("auction_snapshot") if isinstance(row.get("auction_snapshot"), dict) else {}
    auction_price = _moneyflow_value(auction, "virtual_open_price", "open_price", "auction_price")
    latest = _latest_bar(row) or {}
    prev_close = _moneyflow_value(auction, "prev_close_price", "previous_close_price") or _moneyflow_value(
        latest, "close_price"
    )
    if auction_price is None or prev_close is None or prev_close <= 0:
        return None
    gap = (auction_price / prev_close) - Decimal("1")
    if gap < Decimal("0"):
        return Decimal("0.45")
    if gap <= Decimal("0.035"):
        return Decimal("1")
    if gap <= Decimal("0.070"):
        return Decimal("0.70")
    if gap <= Decimal("0.095"):
        return Decimal("0.40")
    return Decimal("0.20")


def _tradability_adjustment_score(row: dict[str, Any]) -> Decimal | None:
    reachability = _open_reachability_score(row)
    liquidity = _open_5m_liquidity_score(row)
    gap_reasonable = _price_gap_reasonable_score(row)
    if any(score is None for score in (reachability, liquidity, gap_reasonable)):
        return None
    return (
        Decimal("0.50") * reachability
        + Decimal("0.30") * liquidity
        + Decimal("0.20") * gap_reasonable
    ).quantize(Decimal("0.000001"))


def _hot_upside_space_score(row: dict[str, Any]) -> Decimal | None:
    bars = _recent_bars(row)
    if len(bars) < HOT_DAILY_PRICE_PATH_REQUIRED_DAYS:
        return None
    latest = bars[-1]
    latest_close = _decimal(latest.get("close_price"))
    close_5 = _decimal(bars[-6].get("close_price")) if len(bars) >= 6 else Decimal("0")
    close_10 = _decimal(bars[-11].get("close_price")) if len(bars) >= 11 else Decimal("0")
    latest_high = _decimal(latest.get("high_price"))
    latest_open = _decimal(latest.get("open_price"))
    if latest_close <= 0 or close_5 <= 0 or close_10 <= 0 or latest_high <= 0 or latest_open <= 0:
        return None
    recent_5d_return = latest_close / close_5 - Decimal("1")
    recent_10d_return = latest_close / close_10 - Decimal("1")
    upper_shadow_ratio = (latest_high - max(latest_open, latest_close)) / latest_close
    score = Decimal("70")
    if recent_5d_return > Decimal("0.20"):
        score -= Decimal("20")
    if recent_10d_return > Decimal("0.35"):
        score -= Decimal("20")
    if upper_shadow_ratio > Decimal("0.06"):
        score -= Decimal("15")
    recent_20_high = max((_decimal(bar.get("high_price")) for bar in bars[-20:]), default=Decimal("0"))
    turnover_latest = _decimal(latest.get("turnover_rate"))
    avg_turnover = sum((_decimal(bar.get("turnover_rate")) for bar in bars[-5:]), Decimal("0")) / Decimal("5")
    near_high = recent_20_high > 0 and ((recent_20_high / latest_close) - Decimal("1")) < Decimal("0.03")
    turnover_expanded = turnover_latest > 0 and avg_turnover > 0 and turnover_latest > avg_turnover * Decimal("1.30")
    if near_high and turnover_expanded:
        score -= Decimal("10")
    return (max(Decimal("0"), min(Decimal("100"), score)) / Decimal("100")).quantize(Decimal("0.000001"))


def _hot_overheating_failure_risk(row: dict[str, Any]) -> Decimal | None:
    bars = _recent_bars(row)
    if len(bars) < HOT_DAILY_PRICE_PATH_REQUIRED_DAYS:
        return None
    latest = bars[-1]
    close_now = _decimal(latest.get("close_price"))
    close_5 = _decimal(bars[-6].get("close_price")) if len(bars) >= 6 else Decimal("0")
    close_10 = _decimal(bars[-11].get("close_price")) if len(bars) >= 11 else Decimal("0")
    latest_high = _decimal(latest.get("high_price"))
    latest_open = _decimal(latest.get("open_price"))
    if close_now <= 0 or close_5 <= 0 or close_10 <= 0 or latest_high <= 0 or latest_open <= 0:
        return None
    recent_5d_return = close_now / close_5 - Decimal("1")
    recent_10d_return = close_now / close_10 - Decimal("1")
    recent_return_overheat = _score((recent_5d_return / Decimal("0.25")) * Decimal("0.60") + (recent_10d_return / Decimal("0.40")) * Decimal("0.40"))
    upper_shadow_ratio = (latest_high - max(latest_open, close_now)) / close_now
    upper_shadow_pressure = _score(upper_shadow_ratio / Decimal("0.08"))
    turnover_latest = _decimal(latest.get("turnover_rate"))
    avg_turnover = sum((_decimal(bar.get("turnover_rate")) for bar in bars[-5:]), Decimal("0")) / Decimal("5")
    close_position = Decimal("0")
    if latest_high > _decimal(latest.get("low_price")):
        close_position = (close_now - _decimal(latest.get("low_price"))) / (latest_high - _decimal(latest.get("low_price")))
    turnover_divergence = _score((turnover_latest / avg_turnover - Decimal("1")) / Decimal("1.50")) if avg_turnover > 0 and close_position < Decimal("0.50") else Decimal("0")
    rank = row.get("stock_rank") if isinstance(row.get("stock_rank"), dict) else {}
    main = _moneyflow_value(rank, "main_net_inflow")
    large = _moneyflow_value(rank, "large_order_net_inflow", "large_net_inflow")
    super_large = _moneyflow_value(rank, "super_large_order_net_inflow", "super_large_net_inflow")
    capital_outflow_pressure = Decimal("0")
    if main is not None and main < 0:
        capital_outflow_pressure += Decimal("0.40")
    if large is not None and large < 0:
        capital_outflow_pressure += Decimal("0.30")
    if super_large is not None and super_large < 0:
        capital_outflow_pressure += Decimal("0.30")
    return (
        Decimal("0.35") * recent_return_overheat
        + Decimal("0.25") * upper_shadow_pressure
        + Decimal("0.20") * turnover_divergence
        + Decimal("0.20") * _score(capital_outflow_pressure)
    ).quantize(Decimal("0.000001"))


def _auction_score(row: dict[str, Any]) -> Decimal:
    auction = row.get("auction_snapshot") if isinstance(row.get("auction_snapshot"), dict) else {}
    if not auction:
        return Decimal("0.45")
    imbalance = _decimal(auction.get("imbalance_ratio"))
    matched_amount = _decimal(auction.get("matched_amount"))
    amount_score = _score(matched_amount / Decimal("20000000"))
    imbalance_score = _score((imbalance + Decimal("0.25")) / Decimal("0.75"))
    return (amount_score * Decimal("0.55") + imbalance_score * Decimal("0.45")).quantize(Decimal("0.000001"))


def _overheating_risk(row: dict[str, Any]) -> Decimal:
    bars = _recent_bars(row)
    if len(bars) < 3:
        return Decimal("0.35")
    latest = bars[-1]
    recent_return = _recent_return_score(row, days=3)
    high = _decimal(latest.get("high_price"))
    close = _decimal(latest.get("close_price"))
    open_price = _decimal(latest.get("open_price"))
    upper_shadow = Decimal("0")
    if high > 0 and close > 0 and open_price > 0:
        body_ref = max(close, open_price)
        upper_shadow = _score((high - body_ref) / high * Decimal("6"))
    return _score(recent_return * Decimal("0.65") + upper_shadow * Decimal("0.35"))


def _breakdown_risk(row: dict[str, Any]) -> Decimal:
    bars = _recent_bars(row)
    if len(bars) < 5:
        return Decimal("0.45")
    latest_close = _decimal(bars[-1].get("close_price"))
    lows = [_decimal(bar.get("low_price")) for bar in bars[-10:]]
    support = min([low for low in lows if low > 0], default=Decimal("0"))
    if latest_close <= 0 or support <= 0:
        return Decimal("0.45")
    support_buffer = (latest_close / support) - Decimal("1")
    if support_buffer <= Decimal("0.01"):
        return Decimal("0.75")
    if support_buffer <= Decimal("0.03"):
        return Decimal("0.55")
    return Decimal("0.25")


def _false_reversal_risk(row: dict[str, Any]) -> Decimal:
    bars = _recent_bars(row)
    if len(bars) < 10:
        return Decimal("0.55")
    latest_close = _decimal(bars[-1].get("close_price"))
    ma5 = sum((_decimal(bar.get("close_price")) for bar in bars[-5:]), Decimal("0")) / Decimal("5")
    ma10 = sum((_decimal(bar.get("close_price")) for bar in bars[-10:]), Decimal("0")) / Decimal("10")
    if latest_close <= 0 or ma5 <= 0 or ma10 <= 0:
        return Decimal("0.55")
    if latest_close < ma5 < ma10:
        return Decimal("0.80")
    if latest_close < ma10:
        return Decimal("0.62")
    return Decimal("0.30")


def _common_scores(row: dict[str, Any]) -> tuple[dict[str, Any], list[str], list[str]]:
    warnings: list[str] = []
    hard_blocks: list[str] = []
    bars = _recent_bars(row)
    daily_gap_code = _recent_ohlc_gap_code(bars, required_days=HOT_DAILY_PRICE_PATH_REQUIRED_DAYS)
    if daily_gap_code:
        warnings.append(daily_gap_code)
        hard_blocks.append("missing_daily_price_path")
    if not row.get("stock_rank"):
        warnings.append("source_gap:stock_moneyflow_rank")
    auction_not_due = (
        _explicit_due(row, "auction_context_due", "auction_due") is False
    )
    if not row.get("auction_snapshot") and row.get("candidate_source") == "hot_candidates" and not auction_not_due:
        warnings.append("source_gap:auction_confirmation")
    liquidity = _liquidity_score(row)
    if liquidity < Decimal("0.18"):
        hard_blocks.append("liquidity_too_weak")
    data_quality = "blocked" if hard_blocks else ("warning" if warnings else "ready")
    failure = max(_overheating_risk(row), _breakdown_risk(row), _false_reversal_risk(row))
    common = {
        "upside_room_score": _upside_room_score(row),
        "liquidity_score": liquidity,
        "data_quality_risk": data_quality,
        "event_risk": "none",
        "failure_risk_score": failure,
        "source_warning_codes": warnings,
    }
    return common, warnings, hard_blocks


def _base_payload(
    row: dict[str, Any],
    *,
    candidate_source: str,
    target_return: Decimal,
    target_window_days: int,
    entry_basis: str,
    run_id: str,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "trade_date": row.get("trade_date") or row.get("trading_day") or row.get("as_of_trading_day"),
        "instrument_id": int(row["instrument_id"]),
        "symbol_snapshot": str(row.get("symbol") or row.get("symbol_snapshot") or "").zfill(6),
        "candidate_source": candidate_source,
        "target_return": target_return,
        "target_window_days": target_window_days,
        "entry_basis": entry_basis,
    }


def build_candidate_source_analysis(
    row: dict[str, Any],
    *,
    candidate_source: str,
    target_return: Decimal = DEFAULT_TARGET_RETURN,
    target_window_days: int = DEFAULT_TARGET_WINDOW_DAYS,
    entry_basis: str = DEFAULT_ENTRY_BASIS,
    run_id: str,
) -> dict[str, Any]:
    if candidate_source != "hot_candidates":
        raise ValueError("hot-candidates model service only scores candidate_source=hot_candidates")
    row = {**row, "candidate_source": candidate_source}
    common, warnings, hard_blocks = _common_scores(row)
    source_scores: dict[str, Any] = {"hot": None}
    positives: list[str] = []
    negatives: list[str] = list(warnings)
    requires_confirmation = False

    teacher_prior = _score(row.get("p_limit_up"), percent=True)
    calibrated_prior = teacher_prior
    capital = _capital_follow_through_score(row)
    momentum = _recent_return_score(row, days=3)
    auction = _auction_confirmation_score(row)
    overheat = _hot_overheating_failure_risk(row)
    upside_space = _hot_upside_space_score(row)
    local_confirmation = None
    if capital is not None and auction is not None:
        local_confirmation = (
            Decimal("0.60") * capital + Decimal("0.40") * auction
        ).quantize(Decimal("0.000001"))
    tradability = _tradability_adjustment_score(row)
    distillation_tags = _hot_distillation_tags(
        teacher_prior=teacher_prior,
        local_confirmation=local_confirmation,
        tradability=tradability,
        capital=capital,
        auction=auction,
        overheat=overheat,
        warnings=warnings,
        hard_blocks=hard_blocks,
    )
    hot_evidence_packet = _hot_candidate_evidence_packet(row, teacher_prior)
    teacher_distillation = _hot_teacher_distillation_contract(
        teacher_prior=teacher_prior,
        local_confirmation=local_confirmation,
        tradability=tradability,
        capital=capital,
        auction=auction,
        overheat=overheat,
        warnings=warnings,
        distillation_tags=distillation_tags,
        evidence_packet=hot_evidence_packet,
    )
    requires_confirmation = any(
        tag
        in {
            "ths_high_score_local_confirmation_weak",
            "ths_high_score_auction_weak",
            "ths_high_score_tradability_weak",
        }
        for tag in distillation_tags
    )
    source_scores["hot"] = {
        "teacher_model": _hot_teacher_model(row, teacher_prior),
        "hot_candidate_evidence_packet": hot_evidence_packet,
        "ths_teacher_prior_score": teacher_prior,
        "theme_heat_score": teacher_prior,
        "calibrated_teacher_prior_score": calibrated_prior,
        "local_confirmation_score": local_confirmation,
        "tradability_adjustment_score": tradability,
        "upside_space_score": upside_space,
        "capital_follow_through_score": capital,
        "momentum_persistence_score": momentum,
        "auction_confirmation_score": auction,
        "overheating_failure_risk": overheat,
        "teacher_distillation": teacher_distillation,
    }
    if any(item is None for item in (local_confirmation, tradability, upside_space, overheat)):
        score = None
    else:
        score = (
            Decimal("0.40") * calibrated_prior
            + Decimal("0.25") * local_confirmation
            + Decimal("0.20") * tradability
            + Decimal("0.15") * upside_space
            - Decimal("0.30") * overheat
        )
    positives.append("同花顺次日概率提供了教师模型先验")
    if capital is not None and capital >= Decimal("0.55"):
        positives.append("资金承接有一定跟随")
    if local_confirmation is not None and local_confirmation >= Decimal("0.60"):
        positives.append("本地量价与竞价证据形成确认")
    if tradability is not None and tradability >= Decimal("0.58"):
        positives.append("流动性和可交易性条件相对顺畅")
    if requires_confirmation:
        negatives.append("同花顺高概率仍缺少本地确认，需要等待竞价和承接验证")
    positives.extend(["外部热度较高", "资金承接有迹象"] if capital is not None and capital >= Decimal("0.55") else ["外部热度较高"])
    if overheat is not None and overheat >= Decimal("0.60"):
        negatives.append("短线过热风险偏高")

    if candidate_source == "hot_candidates":
        hot_scores = source_scores.get("hot") or {}
        hot_distillation = hot_scores.get("teacher_distillation") or {}
        positives = ["同花顺次日概率提供了教师模型先验"]
        if _decimal(hot_scores.get("capital_follow_through_score")) >= Decimal("0.55"):
            positives.append("资金承接有一定跟随")
        if _decimal(hot_scores.get("local_confirmation_score")) >= Decimal("0.60"):
            positives.append("本地量价与竞价证据形成确认")
        if _decimal(hot_scores.get("tradability_adjustment_score")) >= Decimal("0.58"):
            positives.append("流动性和可交易性条件相对顺畅")
        if bool(hot_distillation.get("low_score_success_watch")):
            positives.append("同花顺概率不高但本地证据明显改善，适合纳入低分成功样本观察")

    common["source_warning_codes"] = sorted({str(item) for item in warnings if item})
    bounded_score = None if score is None else _score(score)
    if bounded_score is None:
        spike_reversal_risk = None
        realizable_quality_score = None
        hit_scores = {
            "hit_8pct_score_t3": None,
            "hit_8pct_score_t5": None,
            "hit_before_stop_loss_score": None,
            "realizable_hit_score_t3": None,
            "realizable_hit_score_t5": None,
            "realizable_quality_score": None,
            "spike_reversal_risk_score": None,
        }
    else:
        spike_reversal_risk = _score(
            common["failure_risk_score"] * Decimal("0.55") + _overheating_risk(row) * Decimal("0.45")
        )
        realizable_quality_score = _score(
            bounded_score * Decimal("0.55")
            + common["liquidity_score"] * Decimal("0.20")
            + common["upside_room_score"] * Decimal("0.15")
            + (Decimal("1") - spike_reversal_risk) * Decimal("0.10")
        )
        hit_scores = {
            "hit_8pct_score_t3": _score(bounded_score * Decimal("0.86")),
            "hit_8pct_score_t5": bounded_score,
            "hit_before_stop_loss_score": _score(bounded_score - common["failure_risk_score"] * Decimal("0.20")),
            "realizable_hit_score_t3": _score(realizable_quality_score * Decimal("0.86")),
            "realizable_hit_score_t5": realizable_quality_score,
            "realizable_quality_score": realizable_quality_score,
            "spike_reversal_risk_score": spike_reversal_risk,
        }
    common["support_evidence"] = list(positives)
    common["counterevidence"] = list(negatives)
    common["confirmation_conditions"] = ["竞价量价匹配", "开盘后承接稳定", "板块继续扩散", "高位不出现明显兑现"]
    common["invalidation_conditions"] = ["高开低走", "炸板率上升", "题材退潮", "冲高回落"]
    common["user_state_label"] = "等待确认"
    if hard_blocks:
        state = "blocked"
        common["user_state_label"] = "暂不关注"
    elif bounded_score is None:
        state = "warning"
        common["user_state_label"] = "等待证据"
    elif warnings or bounded_score < Decimal("0.55"):
        state = "warning"
        common["user_state_label"] = "等待确认"
    else:
        state = "ready"
        common["user_state_label"] = "重点关注"
    if bounded_score is not None and bounded_score < Decimal("0.35") and not hard_blocks:
        state = "watch"
        common["user_state_label"] = "谨慎观察"

    if candidate_source == "hot_candidates" and requires_confirmation and state == "ready":
        state = "warning"
        common["user_state_label"] = "等待确认"

    evidence_refs = list(row.get("evidence_refs") or [])
    evidence_refs.append(
        {
            "kind": "candidate_source_input",
            "candidate_source": candidate_source,
            "batch_id": row.get("batch_id"),
            "candidate_id": row.get("candidate_id"),
            "trade_date": str(row.get("trade_date") or row.get("trading_day") or row.get("as_of_trading_day") or ""),
            "instrument_id": row.get("instrument_id"),
            "symbol": row.get("symbol") or row.get("symbol_snapshot"),
        }
    )

    payload = {
        **_base_payload(
            row,
            candidate_source=candidate_source,
            target_return=target_return,
            target_window_days=target_window_days,
            entry_basis=entry_basis,
            run_id=run_id,
        ),
        "source_specific_scores": source_scores,
        "common_scores": common,
        "hit_8pct_scores": hit_scores,
        "state": state,
        "main_positive_factors": positives,
        "main_negative_factors": negatives,
        "hard_block_reasons": hard_blocks,
        "evidence_refs": evidence_refs,
    }
    return _to_jsonable(payload)


def build_hot_candidate_v1_contract(
    payload: dict[str, Any],
    *,
    as_of_time_utc: datetime | None = None,
) -> dict[str, Any] | None:
    """Project the hot candidate lane into the explicit v1 model contract."""
    if payload.get("candidate_source") != "hot_candidates":
        return None
    source_scores = payload.get("source_specific_scores") or {}
    hot_scores = source_scores.get("hot") if isinstance(source_scores, dict) else {}
    if not isinstance(hot_scores, dict):
        return None
    evidence_packet = hot_scores.get("hot_candidate_evidence_packet")
    if not isinstance(evidence_packet, dict):
        evidence_packet = {}
    dimensions = evidence_packet.get("dimensions")
    if not isinstance(dimensions, dict):
        dimensions = {}

    now = as_of_time_utc or datetime.now(timezone.utc)
    evidence_refs = [item for item in list(payload.get("evidence_refs") or []) if isinstance(item, dict)]
    batch_ref = next((item for item in evidence_refs if item.get("batch_id") is not None), {})
    batch_id = batch_ref.get("batch_id") or payload.get("batch_id")
    candidate_id = batch_ref.get("candidate_id") or payload.get("candidate_id")
    symbol = str(payload.get("symbol_snapshot") or payload.get("symbol") or "").zfill(6)
    teacher_model = hot_scores.get("teacher_model") if isinstance(hot_scores.get("teacher_model"), dict) else {}
    p_limit_up_source = _canonical_ths_prior_source(teacher_model.get("p_limit_up_source"))
    teacher_prior_score = _score01_to_100(hot_scores.get("ths_teacher_prior_score"))
    capital_score = _score01_to_100(hot_scores.get("capital_follow_through_score"))
    auction_score = _score01_to_100(hot_scores.get("auction_confirmation_score"))
    local_confirmation_score = _score01_to_100(hot_scores.get("local_confirmation_score"))
    tradability_score = _score01_to_100(hot_scores.get("tradability_adjustment_score"))
    upside_score = _score01_to_100(
        hot_scores.get("upside_space_score")
        if hot_scores.get("upside_space_score") is not None
        else (payload.get("common_scores") or {}).get("upside_room_score")
    )
    overheating_risk = _score01_to_100(hot_scores.get("overheating_failure_risk"))

    source_gap_codes = sorted(
        {
            str(code)
            for code in [
                *list(evidence_packet.get("source_gap_codes") or []),
                *list((payload.get("common_scores") or {}).get("source_warning_codes") or []),
            ]
            if code not in (None, "")
        }
    )
    feature_gap_codes: list[str] = []
    p0_codes: list[str] = []
    p1_codes: list[str] = []

    if batch_id in (None, ""):
        p0_codes.append("missing_candidate_batch")
    if payload.get("instrument_id") in (None, "") or not symbol:
        p0_codes.append("missing_instrument_identity")
    if p_limit_up_source != "paid_ths_prior":
        p0_codes.append("missing_paid_prior")
    if teacher_prior_score is None:
        p0_codes.append("invalid_p_limit_up_range")
    daily_dimension = dimensions.get("daily_price_path") if isinstance(dimensions.get("daily_price_path"), dict) else {}
    daily_row_count = int(daily_dimension.get("row_count") or 0)
    if daily_dimension.get("status") != "present" or daily_row_count < 20:
        p0_codes.append("missing_daily_price_path")

    stock_flow_dimension = (
        dimensions.get("stock_moneyflow_rank") if isinstance(dimensions.get("stock_moneyflow_rank"), dict) else {}
    )
    if stock_flow_dimension.get("status") != "present" or capital_score is None:
        p1_codes.append("capital_flow_missing")
        capital_score = None
    auction_dimension = dimensions.get("auction_context") if isinstance(dimensions.get("auction_context"), dict) else {}
    if auction_dimension.get("status") == "deferred":
        p1_codes.append("auction_deferred")
    elif auction_dimension.get("status") != "present":
        p1_codes.append("auction_missing_after_due")
        auction_score = None
    elif auction_score is None:
        p1_codes.append("auction_confirmation_score_incomplete")
    if capital_score is None or auction_score is None:
        local_confirmation_score = None
    if auction_score is None:
        tradability_score = None
    if any(score is None for score in (local_confirmation_score, tradability_score, upside_score, overheating_risk)):
        p1_codes.append("active_score_incomplete")
    late_evidence_domains = _late_evidence_domains(dimensions, now)
    if late_evidence_domains:
        p0_codes.append("evidence_captured_after_as_of")
        source_gap_codes = sorted(
            {
                *source_gap_codes,
                *[f"source_gap:{domain}_captured_after_as_of" for domain in late_evidence_domains],
            }
        )

    feature_gap_codes = sorted(set([*source_gap_codes, *p0_codes, *p1_codes]))
    feature_payload = {
        "model_version": HOT_MODEL_VERSION,
        "symbol": symbol,
        "teacher_prior_score": str(teacher_prior_score) if teacher_prior_score is not None else None,
        "capital_follow_through_score": str(capital_score) if capital_score is not None else None,
        "auction_confirmation_score": str(auction_score) if auction_score is not None else None,
        "local_confirmation_score": str(local_confirmation_score) if local_confirmation_score is not None else None,
        "tradability_adjustment_score": str(tradability_score) if tradability_score is not None else None,
        "upside_space_score": str(upside_score) if upside_score is not None else None,
        "overheating_failure_risk": str(overheating_risk) if overheating_risk is not None else None,
        "feature_gap_codes": feature_gap_codes,
    }
    feature_hash = _stable_json_hash(feature_payload)
    active_scores = (teacher_prior_score, local_confirmation_score, tradability_score, upside_score, overheating_risk)

    hot_score: Decimal | None
    state = "ready"
    hard_block_reasons = sorted(set([*list(payload.get("hard_block_reasons") or []), *p0_codes]))
    negative_factors = list(payload.get("main_negative_factors") or [])
    if hard_block_reasons:
        hot_score = None
        state = "blocked"
    elif any(score is None for score in active_scores):
        hot_score = None
        state = "watch" if "auction_deferred" in p1_codes else "warning"
        negative_factors.extend(p1_codes)
    else:
        raw_score = (
            Decimal("0.40") * teacher_prior_score
            + Decimal("0.25") * local_confirmation_score
            + Decimal("0.20") * tradability_score
            + Decimal("0.15") * upside_score
            - Decimal("0.30") * overheating_risk
        )
        hot_score = max(Decimal("0"), min(Decimal("100"), raw_score)).quantize(Decimal("0.000001"))
        if overheating_risk >= Decimal("85"):
            state = "warning"
            negative_factors.append("overheating_failure_risk_high")

    snapshots: list[dict[str, Any]] = []
    for domain, dimension in sorted(dimensions.items()):
        dimension = dimension if isinstance(dimension, dict) else {}
        role = str(dimension.get("scoring_role") or "audit_only")
        status = str(dimension.get("status") or "missing")
        facts = dimension.get("facts") if isinstance(dimension.get("facts"), dict) else {}
        captured_at_utc = _dimension_captured_at_utc(dimension, now)
        snapshots.append(
            {
                "batch_id": batch_id,
                "symbol": symbol,
                "evidence_domain": str(domain),
                "dimension_role": role,
                "dimension_status": status,
                "as_of_time_utc": now,
                "captured_at_utc": captured_at_utc,
                "source_table": _evidence_source_table(str(domain)),
                "source_primary_key": str(
                    facts.get("raw_payload_id")
                    or facts.get("latest_raw_payload_id")
                    or facts.get("latest_id")
                    or facts.get("snapshot_id")
                    or facts.get("subject_id")
                    or facts.get("impact_snapshot_id")
                    or batch_id
                    or symbol
                ),
                "source_version": HOT_MODEL_VERSION,
                "payload_json": {
                    "dimension": dimension,
                    "contract_kind": "hot_candidate_evidence_snapshot_v1",
                },
                "source_gap_codes": [code for code in [dimension.get("source_gap_code")] if code],
            }
        )

    score_hash = _stable_json_hash(
        {
            "feature_hash": feature_hash,
            "model_version": HOT_MODEL_VERSION,
            "formula": "0.40*teacher+0.25*local+0.20*tradability+0.15*upside-0.30*overheat",
            "state": state,
            "hot_score": str(hot_score) if hot_score is not None else None,
        }
    )
    return {
        "candidate_item": {
            "batch_id": batch_id,
            "candidate_id": candidate_id,
            "instrument_id": payload.get("instrument_id"),
            "symbol": symbol,
            "name": payload.get("name_snapshot") or payload.get("name") or symbol,
            "p_limit_up": teacher_prior_score,
            "p_limit_up_source": p_limit_up_source,
            "limit_up_stage": teacher_model.get("limit_up_stage"),
            "source_rank_no": teacher_model.get("source_rank_no"),
        },
        "evidence_snapshots": snapshots,
        "feature_matrix": {
            "batch_id": batch_id,
            "symbol": symbol,
            "model_version": HOT_MODEL_VERSION,
            "as_of_time_utc": now,
            "teacher_prior_score": teacher_prior_score,
            "local_confirmation_score": local_confirmation_score,
            "tradability_adjustment_score": tradability_score,
            "upside_space_score": upside_score,
            "overheating_failure_risk": overheating_risk,
            "feature_gap_codes": feature_gap_codes,
            "feature_hash": feature_hash,
            "feature_payload_json": feature_payload,
        },
        "analysis": {
            "batch_id": batch_id,
            "symbol": symbol,
            "model_version": HOT_MODEL_VERSION,
            "as_of_time_utc": now,
            "hot_score": hot_score,
            "state": state,
            "main_positive_factors": list(payload.get("main_positive_factors") or []),
            "main_negative_factors": sorted(set(str(item) for item in negative_factors if item)),
            "hard_block_reasons": hard_block_reasons,
            "evidence_refs": [],
            "score_hash": score_hash,
            "is_active": True,
            "source_gap_codes": feature_gap_codes,
        },
    }


def _evidence_source_table(domain: str) -> str:
    return {
        "ths_black_box_prior": "market.hot_candidate_item",
        "candidate_pool_membership": "market.candidate_batch",
        "instrument_identity": "core.instrument_master",
        "daily_price_path": "market.daily_bar",
        "stock_moneyflow_rank": "market.moneyflow_stock_rank",
        "board_theme_context": "market.moneyflow_board_rank",
        "auction_context": "market.auction_snapshot",
        "minute_trade_context": "market.minute_bar",
        "dynamic_signal_context": "decision.dynamic_feature_latest",
        "news_event_context": "news.news_event",
        "market_regime_context": "decision.cross_market_feature_snapshot",
        "inspection_context": "decision.data_inspection_subject",
        "outcome_label_context": "decision.hit_8pct_outcome_label_v1",
    }.get(domain, "raw.raw_payload")


def utc_run_id(prefix: str = "candidate-source") -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
