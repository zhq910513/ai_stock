from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from source_data_service.gap_detector import build_repair_plan
from source_data_service.models import (
    MultiSourceFieldComparison,
    MultiSourceProviderEvidence,
    MultiSourceQualityCheckRequest,
    MultiSourceQualityCheckResult,
    Provider,
    QualityValidationRequest,
    RepairApiPlan,
    SourceGapRequest,
)
from source_data_service.provider_registry import build_provider_code
from source_data_service.provider_runtime import execute_provider_fetch
from source_data_service.source_build import validate_raw_rows
from source_data_service.source_repository import CANONICAL_FIELD_MAP


DEFAULT_ABSOLUTE_TOLERANCE: dict[str, Decimal] = {
    "open_price": Decimal("0.02"),
    "high_price": Decimal("0.02"),
    "low_price": Decimal("0.02"),
    "close_price": Decimal("0.02"),
    "pre_close_price": Decimal("0.02"),
    "adjusted_open": Decimal("0.02"),
    "adjusted_high": Decimal("0.02"),
    "adjusted_low": Decimal("0.02"),
    "adjusted_close": Decimal("0.02"),
    "pct_chg": Decimal("0.05"),
}

DEFAULT_RELATIVE_TOLERANCE: dict[str, Decimal] = {
    "volume": Decimal("0.005"),
    "amount": Decimal("0.005"),
}

TENCENT_VOLUME_FIELDS = {"volume"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _decimal_or_none(value: Any) -> Decimal | None:
    if value in (None, "", "None", "nan", "NaN"):
        return None
    try:
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return None


def _decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.normalize(), "f")


def _field_absolute_tolerance(field_name: str, request: MultiSourceQualityCheckRequest) -> Decimal:
    override = request.absolute_tolerance.get(field_name)
    if override is not None:
        parsed = _decimal_or_none(override)
        if parsed is not None:
            return parsed
    return DEFAULT_ABSOLUTE_TOLERANCE.get(field_name, Decimal("0"))


def _field_relative_tolerance(field_name: str, request: MultiSourceQualityCheckRequest) -> Decimal:
    override = request.relative_tolerance.get(field_name)
    if override is not None:
        parsed = _decimal_or_none(override)
        if parsed is not None:
            return parsed
    return DEFAULT_RELATIVE_TOLERANCE.get(field_name, Decimal("0.001"))


def _normalize_provider_value(provider: Provider, canonical_field_name: str, value: Any) -> Decimal | None:
    parsed = _decimal_or_none(value)
    if parsed is None:
        return None
    if provider == Provider.TENCENT and canonical_field_name in TENCENT_VOLUME_FIELDS:
        return parsed * Decimal("100")
    return parsed


def _date_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return text[:10]


def _provider_symbol_candidates(provider: Provider, symbol: str) -> set[str]:
    canonical = str(symbol or "").strip().upper()
    candidates = {canonical}
    if canonical:
        try:
            provider_code = build_provider_code(canonical, provider)
            candidates.add(provider_code)
            candidates.add(provider_code.upper())
            candidates.add(provider_code.lower())
            if provider == Provider.BAOSTOCK:
                candidates.add(provider_code.replace(".", ""))
            if provider == Provider.TENCENT:
                candidates.add(provider_code[2:8])
            if provider == Provider.AKSHARE:
                candidates.add(provider_code[:6])
        except Exception:
            pass
        short = canonical.split(".")[0]
        if short:
            candidates.add(short)
    return {item for item in candidates if item}


def _row_symbol_values(raw_row: dict[str, Any]) -> set[str]:
    values: set[str] = set()
    for key in ("symbol", "code", "provider_code", "ts_code"):
        value = raw_row.get(key)
        if value not in (None, ""):
            text = str(value)
            values.add(text)
            values.add(text.upper())
            values.add(text.lower())
            values.add(text.replace(".", ""))
    return values


def _row_date_value(raw_row: dict[str, Any]) -> str:
    for key in ("date", "trade_date", "cal_date", "日期"):
        if raw_row.get(key) not in (None, ""):
            return _date_text(raw_row.get(key))
    return ""


def _pick_target_raw_row(
    *,
    provider: Provider,
    request: MultiSourceQualityCheckRequest,
    raw_rows: list[dict[str, Any]],
) -> dict[str, Any] | None:
    expected_date = request.trade_date.isoformat()
    expected_symbols = _provider_symbol_candidates(provider, request.symbol)
    for raw_row in raw_rows:
        if _row_date_value(raw_row) != expected_date:
            continue
        row_symbols = _row_symbol_values(raw_row)
        if not row_symbols or row_symbols.intersection(expected_symbols):
            return raw_row
    return None


def _target_identity(raw_row: dict[str, Any] | None) -> dict[str, Any]:
    if raw_row is None:
        return {}
    identity: dict[str, Any] = {}
    for key in ("symbol", "code", "provider_code", "ts_code", "date", "trade_date", "日期"):
        if raw_row.get(key) not in (None, ""):
            identity[key] = raw_row.get(key)
    return identity


def _raw_to_canonical_values(
    *,
    provider: Provider,
    api_name: str,
    source_table_name: str,
    raw_row: dict[str, Any],
    canonical_fields: list[str],
) -> dict[str, str | None]:
    mapping = CANONICAL_FIELD_MAP.get((provider, api_name, source_table_name), {})
    values: dict[str, str | None] = {}
    for field_name in canonical_fields:
        raw_field = mapping.get(field_name)
        if not raw_field:
            values[field_name] = None
            continue
        values[field_name] = _decimal_text(_normalize_provider_value(provider, field_name, raw_row.get(raw_field)))
    return values


def _provider_supports_field(evidence: MultiSourceProviderEvidence, source_table_name: str, field_name: str) -> bool:
    mapping = CANONICAL_FIELD_MAP.get((evidence.provider, evidence.api_name, source_table_name), {})
    return field_name in mapping


def _fetch_evidence(
    plan: RepairApiPlan,
    request: MultiSourceQualityCheckRequest,
    canonical_fields: list[str],
) -> MultiSourceProviderEvidence:
    result = execute_provider_fetch(
        provider=plan.provider,
        api_name=plan.api_name,
        params=plan.params,
        dry_run=request.dry_run,
    )
    quality_status = "not_checked"
    build_allowed = False
    canonical_values = {field: None for field in canonical_fields}
    target_row: dict[str, Any] | None = None
    if result.rows:
        raw_rows = [row.row for row in result.rows]
        quality = validate_raw_rows(QualityValidationRequest(provider=plan.provider, api_name=plan.api_name, rows=raw_rows))
        quality_status = "passed" if quality.build_allowed else "blocked"
        build_allowed = quality.build_allowed
        if quality.build_allowed:
            target_row = _pick_target_raw_row(provider=plan.provider, request=request, raw_rows=raw_rows)
            if target_row is None:
                build_allowed = False
                quality_status = "blocked"
            else:
                canonical_values = _raw_to_canonical_values(
                    provider=plan.provider,
                    api_name=plan.api_name,
                    source_table_name=request.source_table_name,
                    raw_row=target_row,
                    canonical_fields=canonical_fields,
                )
    return MultiSourceProviderEvidence(
        provider=plan.provider,
        api_name=plan.api_name,
        raw_table_name=plan.raw_table_name,
        request_params=plan.params,
        row_count=result.row_count,
        target_row_found=target_row is not None,
        target_row_identity=_target_identity(target_row),
        raw_quality_status=quality_status,  # type: ignore[arg-type]
        build_allowed=build_allowed,
        error=result.error,
        warning=result.warning or (None if target_row is not None or not result.rows else "target symbol/trade_date row not found in provider result"),
        canonical_values=canonical_values,
    )


def _pick_fields(request: MultiSourceQualityCheckRequest) -> list[str]:
    if request.canonical_fields:
        return list(dict.fromkeys(request.canonical_fields))
    plan = build_repair_plan(
        SourceGapRequest(
            source_table_name=request.source_table_name,
            canonical_field_name="close_price" if request.source_table_name != "source.adjusted_daily_bar_v1" else "adjusted_close",
            symbol=request.symbol,
            trade_date=request.trade_date,
        )
    )
    mapping = CANONICAL_FIELD_MAP.get((plan.primary_repair.provider, plan.primary_repair.api_name, request.source_table_name), {})
    return list(mapping.keys())


def _plans_for_fields(request: MultiSourceQualityCheckRequest, canonical_fields: list[str]) -> list[RepairApiPlan]:
    plans: list[RepairApiPlan] = []
    seen: set[tuple[Provider, str]] = set()
    for field_name in canonical_fields:
        repair_plan = build_repair_plan(
            SourceGapRequest(
                source_table_name=request.source_table_name,
                canonical_field_name=field_name,
                symbol=request.symbol,
                trade_date=request.trade_date,
            )
        )
        candidates = [repair_plan.primary_repair]
        if request.include_backup:
            candidates.extend(repair_plan.backup_repairs)
        for candidate in candidates:
            key = (candidate.provider, candidate.api_name)
            if key in seen or candidate.provider == Provider.INTERNAL:
                continue
            if (candidate.provider, candidate.api_name, request.source_table_name) not in CANONICAL_FIELD_MAP:
                continue
            seen.add(key)
            plans.append(candidate)
    return plans


def _compare_field(
    request: MultiSourceQualityCheckRequest,
    field_name: str,
    baseline: MultiSourceProviderEvidence,
    compared: MultiSourceProviderEvidence,
) -> MultiSourceFieldComparison:
    baseline_value = _decimal_or_none(baseline.canonical_values.get(field_name))
    compared_value = _decimal_or_none(compared.canonical_values.get(field_name))
    absolute_tolerance = _field_absolute_tolerance(field_name, request)
    relative_tolerance = _field_relative_tolerance(field_name, request)
    if baseline_value is None or compared_value is None:
        return MultiSourceFieldComparison(
            canonical_field_name=field_name,
            status="blocked",
            baseline_provider=baseline.provider,
            baseline_api_name=baseline.api_name,
            compared_provider=compared.provider,
            compared_api_name=compared.api_name,
            baseline_value=_decimal_text(baseline_value),
            compared_value=_decimal_text(compared_value),
            absolute_tolerance=_decimal_text(absolute_tolerance),
            relative_tolerance=_decimal_text(relative_tolerance),
            reason="missing comparable numeric value from one provider",
        )
    absolute_diff = abs(baseline_value - compared_value)
    denominator = max(abs(baseline_value), Decimal("1"))
    relative_diff = absolute_diff / denominator
    passed = absolute_diff <= absolute_tolerance or relative_diff <= relative_tolerance
    return MultiSourceFieldComparison(
        canonical_field_name=field_name,
        status="passed" if passed else "blocked",
        baseline_provider=baseline.provider,
        baseline_api_name=baseline.api_name,
        compared_provider=compared.provider,
        compared_api_name=compared.api_name,
        baseline_value=_decimal_text(baseline_value),
        compared_value=_decimal_text(compared_value),
        absolute_diff=_decimal_text(absolute_diff),
        relative_diff=_decimal_text(relative_diff),
        absolute_tolerance=_decimal_text(absolute_tolerance),
        relative_tolerance=_decimal_text(relative_tolerance),
        reason="within tolerance" if passed else "provider values diverged beyond tolerance",
    )


def check_multi_source_quality(request: MultiSourceQualityCheckRequest) -> MultiSourceQualityCheckResult:
    canonical_fields = _pick_fields(request)
    plans = _plans_for_fields(request, canonical_fields)
    evidence = [_fetch_evidence(plan, request, canonical_fields) for plan in plans]
    usable = [item for item in evidence if item.build_allowed and item.row_count > 0 and not item.error]
    comparisons: list[MultiSourceFieldComparison] = []
    for field_name in canonical_fields:
        field_usable = [
            item
            for item in usable
            if _provider_supports_field(item, request.source_table_name, field_name)
            and _decimal_or_none(item.canonical_values.get(field_name)) is not None
        ]
        if len(field_usable) < 2:
            comparisons.append(
                MultiSourceFieldComparison(
                    canonical_field_name=field_name,
                    status="blocked",
                    reason="fewer than two usable provider results",
                )
            )
            continue
        baseline = field_usable[0]
        for compared in field_usable[1:]:
            comparisons.append(_compare_field(request, field_name, baseline, compared))
    blocking = [
        f"{item.canonical_field_name}:{item.reason}"
        for item in comparisons
        if item.status == "blocked"
    ]
    warnings = [
        f"{item.provider.value}.{item.api_name}:{item.error or item.warning}"
        for item in evidence
        if item.error or item.warning
    ]
    field_status: dict[str, str] = {}
    for field_name in canonical_fields:
        items = [item for item in comparisons if item.canonical_field_name == field_name]
        if any(item.status == "blocked" for item in items):
            field_status[field_name] = "blocked"
        elif any(item.status == "warning" for item in items):
            field_status[field_name] = "warning"
        elif any(item.status == "passed" for item in items):
            field_status[field_name] = "passed"
        else:
            field_status[field_name] = "blocked"
            blocking.append(f"{field_name}:no comparison produced")
    passed_count = sum(1 for item in field_status.values() if item == "passed")
    warning_count = sum(1 for item in field_status.values() if item == "warning")
    blocked_count = sum(1 for item in field_status.values() if item == "blocked")
    status = "blocked" if blocked_count else ("warning" if warnings or warning_count else "passed")
    return MultiSourceQualityCheckResult(
        source_table_name=request.source_table_name,
        symbol=request.symbol,
        trade_date=request.trade_date,
        status=status,  # type: ignore[arg-type]
        checked_at=_utcnow(),
        provider_count=len(evidence),
        usable_provider_count=len(usable),
        field_count=len(canonical_fields),
        passed_field_count=passed_count,
        warning_field_count=warning_count,
        blocked_field_count=blocked_count,
        provider_evidence=evidence,
        comparisons=comparisons,
        blocking_reasons=blocking,
        warning_reasons=warnings,
    )
