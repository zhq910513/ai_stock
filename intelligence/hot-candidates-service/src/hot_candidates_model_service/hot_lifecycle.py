from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, asdict
from datetime import date, datetime
from typing import Any

HOT_LIFECYCLE_CONTRACT_VERSION = "hot_cycle_resolution_v1"
DEFAULT_COOLING_DAYS = 5
DEFAULT_COOLING_DRAWDOWN_PCT = 12.0


def _parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    text = str(value).strip()
    if "T" in text:
        text = text.split("T", 1)[0]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _stable_hash(payload: dict[str, Any], prefix: str) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return f"{prefix}-{hashlib.sha256(encoded.encode('utf-8')).hexdigest()[:24]}"


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return False
    return str(value).strip().lower() in {"true", "1", "yes", "y", "是"}


def _as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class HotCycleResolution:
    contract_kind: str
    hot_cycle_id: str
    symbol: str
    cycle_start_date: str
    continuity_state: str
    should_start_new_cycle: bool
    days_since_last_seen: int | None
    cooling_reason_codes: list[str]
    resolution_basis: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_hot_cycle(
    row: dict[str, Any],
    *,
    symbol: str,
    trade_date: str,
    lifecycle_stage: str,
    cooling_days: int = DEFAULT_COOLING_DAYS,
    cooling_drawdown_pct: float = DEFAULT_COOLING_DRAWDOWN_PCT,
) -> HotCycleResolution:
    """Resolve whether a daily hot decision belongs to an existing hot cycle.

    The hot model must not treat every daily THS candidate as a brand-new signal and
    must not merge a fully cooled historical cycle into a new ignition. This resolver is
    deliberately deterministic and does not mutate database state; repositories persist
    the resulting cycle id.
    """
    explicit_cycle_id = row.get("hot_cycle_id")
    if explicit_cycle_id not in (None, ""):
        cycle_start = row.get("cycle_start_date") or row.get("first_seen_trade_date") or trade_date
        return HotCycleResolution(
            contract_kind=HOT_LIFECYCLE_CONTRACT_VERSION,
            hot_cycle_id=str(explicit_cycle_id),
            symbol=symbol,
            cycle_start_date=str(cycle_start),
            continuity_state="explicit_cycle_id_supplied",
            should_start_new_cycle=False,
            days_since_last_seen=None,
            cooling_reason_codes=[],
            resolution_basis="row.hot_cycle_id",
        )

    active = row.get("active_hot_cycle") or row.get("historical_hot_cycle") or {}
    if not isinstance(active, dict):
        active = {}
    active_id = active.get("hot_cycle_id")
    active_status = str(active.get("cycle_status") or "active")
    active_start = active.get("cycle_start_date") or active.get("first_seen_trade_date")
    last_seen = _parse_date(active.get("last_seen_trade_date") or active.get("last_candidate_trade_date") or active.get("updated_trade_date"))
    current_day = _parse_date(trade_date)
    days_since = (current_day - last_seen).days if current_day and last_seen else None
    drawdown = _as_float(active.get("drawdown_from_cycle_high_pct") or active.get("max_drawdown_pct"))
    explicit_cooling = _as_bool(row.get("force_new_hot_cycle")) or _as_bool(active.get("force_closed"))
    relimit_after_break = lifecycle_stage == "relimit_after_break" or _as_bool(row.get("relimit_after_break_flag"))

    cooling_reasons: list[str] = []
    if active_status in {"closed", "archived", "cooled"}:
        cooling_reasons.append("previous_cycle_closed")
    if days_since is not None and days_since > cooling_days and not relimit_after_break:
        cooling_reasons.append("cooling_window_exceeded")
    if drawdown is not None and drawdown >= cooling_drawdown_pct and not relimit_after_break:
        cooling_reasons.append("drawdown_from_cycle_high_exceeded")
    if explicit_cooling:
        cooling_reasons.append("force_new_hot_cycle")

    if active_id and not cooling_reasons:
        return HotCycleResolution(
            contract_kind=HOT_LIFECYCLE_CONTRACT_VERSION,
            hot_cycle_id=str(active_id),
            symbol=symbol,
            cycle_start_date=str(active_start or trade_date),
            continuity_state="same_active_cycle",
            should_start_new_cycle=False,
            days_since_last_seen=days_since,
            cooling_reason_codes=[],
            resolution_basis="active_hot_cycle_reused",
        )

    cycle_start_date = str(row.get("cycle_start_date") or row.get("first_seen_trade_date") or row.get("first_candidate_trade_date") or trade_date)
    payload = {
        "symbol": symbol,
        "cycle_start_date": cycle_start_date,
        "primary_theme": row.get("primary_theme") or row.get("theme") or row.get("primary_concept"),
        "primary_catalyst_id": row.get("primary_catalyst_id") or row.get("news_event_id"),
    }
    return HotCycleResolution(
        contract_kind=HOT_LIFECYCLE_CONTRACT_VERSION,
        hot_cycle_id=_stable_hash(payload, "hot-cycle"),
        symbol=symbol,
        cycle_start_date=cycle_start_date,
        continuity_state="new_cycle_started" if active_id else "new_cycle_no_active_history",
        should_start_new_cycle=True,
        days_since_last_seen=days_since,
        cooling_reason_codes=cooling_reasons,
        resolution_basis="deterministic_cycle_hash",
    )
