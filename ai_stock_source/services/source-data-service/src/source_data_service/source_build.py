from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from source_data_service.models import (
    Provider,
    QualityCheckIssue,
    QualityValidationRequest,
    QualityValidationResult,
    ReadinessMatrixOut,
    ReadinessMatrixRow,
    RepairRouteOut,
    RepairRouteRow,
    SourceBuildPlan,
    SourceBuildPlanRequest,
    SourceBuildStep,
    SourceProbeMatrixOut,
    SourceProbeMatrixRow,
)
from source_data_service.provider_registry import (
    get_api_spec,
    list_api_specs,
    list_field_contracts,
    list_source_requirements,
)
from source_data_service.provider_runtime import list_provider_status
from source_data_service.gap_detector import build_repair_plan
from source_data_service.models import SourceGapRequest


OHLC_RAW_FIELD_SETS: dict[str, dict[str, str]] = {
    # canonical validation names -> provider raw row field names
    "baostock_raw": {"open": "open", "high": "high", "low": "low", "close": "close", "volume": "volume", "amount": "amount"},
    "akshare_raw": {"open": "开盘", "high": "最高", "low": "最低", "close": "收盘", "volume": "成交量", "amount": "成交额"},
    "tencent_raw": {"open": "open", "high": "high", "low": "low", "close": "close", "volume": "volume", "amount": "amount"},
    "sohu_raw": {"open": "open", "high": "high", "low": "low", "close": "close", "volume": "volume", "amount": "amount"},
    "tushare_raw": {"open": "open", "high": "high", "low": "low", "close": "close", "volume": "vol", "amount": "amount"},
}


def _as_decimal(value: Any) -> Decimal | None:
    if value in (None, "", "None", "nan", "NaN"):
        return None
    try:
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return None


def _field_set_for(provider: Provider, api_name: str) -> dict[str, str] | None:
    if provider == Provider.BAOSTOCK and "history_k_data" in api_name:
        return OHLC_RAW_FIELD_SETS["baostock_raw"]
    if provider == Provider.AKSHARE and ("hist" in api_name or "index_zh_a_hist" in api_name or "board_industry_hist" in api_name):
        return OHLC_RAW_FIELD_SETS["akshare_raw"]
    if provider == Provider.TENCENT and api_name == "daily_bars":
        return OHLC_RAW_FIELD_SETS["tencent_raw"]
    if provider == Provider.SOHU and api_name == "daily_bars":
        return OHLC_RAW_FIELD_SETS["sohu_raw"]
    if provider == Provider.TUSHARE and api_name == "daily":
        return OHLC_RAW_FIELD_SETS["tushare_raw"]
    return None


def validate_raw_rows(request: QualityValidationRequest) -> QualityValidationResult:
    """Validate raw interface rows before source build.

    This is intentionally provider-aware but model-agnostic. It prevents broken
    raw rows from silently entering source.* canonical facts.
    """

    issues: list[QualityCheckIssue] = []
    spec = get_api_spec(request.provider, request.api_name)
    expected_fields = set(spec.response_fields)
    observed_fields: set[str] = set()

    for row_index, row in enumerate(request.rows):
        observed_fields.update(row.keys())
        missing = sorted(expected_fields - set(row.keys()))
        for field in missing:
            issues.append(
                QualityCheckIssue(
                    row_index=row_index,
                    field_name=field,
                    severity="error" if field in spec.response_fields[: min(3, len(spec.response_fields))] else "warning",
                    rule_code="raw_schema_missing_field",
                    message=f"Expected raw field {field!r} missing for {request.provider.value}.{request.api_name}.",
                )
            )

        field_set = _field_set_for(request.provider, request.api_name)
        if request.provider == Provider.THS and request.api_name == "paid_limit_up_probability":
            probability = _as_decimal(row.get("paid_limit_up_probability"))
            status_code = row.get("status_code")
            if status_code not in (0, "0"):
                issues.append(
                    QualityCheckIssue(
                        row_index=row_index,
                        field_name="status_code",
                        severity="error",
                        rule_code="ths_paid_probability_status_not_success",
                        message="THS paid probability raw row must have status_code=0 before source build.",
                    )
                )
            if probability is None or probability < 0 or probability > 100:
                issues.append(
                    QualityCheckIssue(
                        row_index=row_index,
                        field_name="paid_limit_up_probability",
                        severity="error",
                        rule_code="ths_paid_probability_out_of_range",
                        message="THS paid probability must be parseable Decimal in [0,100].",
                    )
                )
        if field_set:
            open_v = _as_decimal(row.get(field_set["open"]))
            high_v = _as_decimal(row.get(field_set["high"]))
            low_v = _as_decimal(row.get(field_set["low"]))
            close_v = _as_decimal(row.get(field_set["close"]))
            volume_v = _as_decimal(row.get(field_set["volume"]))
            amount_v = _as_decimal(row.get(field_set["amount"]))
            if None in {open_v, high_v, low_v, close_v}:
                issues.append(
                    QualityCheckIssue(
                        row_index=row_index,
                        field_name="OHLC",
                        severity="error",
                        rule_code="ohlc_parse_failed",
                        message="Open/high/low/close must be parseable numeric values before canonical build.",
                    )
                )
            else:
                assert open_v is not None and high_v is not None and low_v is not None and close_v is not None
                if high_v < low_v:
                    issues.append(
                        QualityCheckIssue(row_index=row_index, field_name=field_set["high"], severity="error", rule_code="high_lt_low", message="High price must be >= low price.")
                    )
                if not (low_v <= open_v <= high_v):
                    issues.append(
                        QualityCheckIssue(row_index=row_index, field_name=field_set["open"], severity="error", rule_code="open_outside_high_low", message="Open price must be inside [low, high].")
                    )
                if not (low_v <= close_v <= high_v):
                    issues.append(
                        QualityCheckIssue(row_index=row_index, field_name=field_set["close"], severity="error", rule_code="close_outside_high_low", message="Close price must be inside [low, high].")
                    )
            if volume_v is not None and volume_v < 0:
                issues.append(QualityCheckIssue(row_index=row_index, field_name=field_set["volume"], severity="error", rule_code="negative_volume", message="Volume must be non-negative."))
            if amount_v is not None and amount_v < 0:
                issues.append(QualityCheckIssue(row_index=row_index, field_name=field_set["amount"], severity="error", rule_code="negative_amount", message="Amount must be non-negative."))

    errors = [issue for issue in issues if issue.severity == "error"]
    warnings = [issue for issue in issues if issue.severity == "warning"]
    return QualityValidationResult(
        provider=request.provider,
        api_name=request.api_name,
        raw_table_name=spec.raw_table_name,
        row_count=len(request.rows),
        observed_fields=sorted(observed_fields),
        issue_count=len(issues),
        error_count=len(errors),
        warning_count=len(warnings),
        build_allowed=len(errors) == 0,
        issues=issues,
    )


def build_source_plan(request: SourceBuildPlanRequest) -> SourceBuildPlan:
    requirements = list_source_requirements(request.source_table_name)
    if request.canonical_fields:
        requirements = [item for item in requirements if item.canonical_field_name in request.canonical_fields]
    steps: list[SourceBuildStep] = []
    for req in requirements:
        repair = build_repair_plan(
            SourceGapRequest(
                source_table_name=req.source_table_name,
                canonical_field_name=req.canonical_field_name,
                symbol=request.symbol,
                trade_date=request.trade_date,
                start_date=request.start_date,
                end_date=request.end_date,
            )
        )
        contract = next(
            (c for c in list_field_contracts(req.source_table_name) if c.canonical_field_name == req.canonical_field_name),
            None,
        )
        steps.append(
            SourceBuildStep(
                canonical_field_name=req.canonical_field_name,
                required_level=req.required_level,
                source_table_name=req.source_table_name,
                primary_provider=repair.primary_repair.provider,
                primary_api_name=repair.primary_repair.api_name,
                primary_raw_table_name=repair.primary_repair.raw_table_name,
                backup_raw_table_names=[item.raw_table_name for item in repair.backup_repairs],
                quality_gates=(contract.field_quality_rules if contract else []),
                lineage_required=True,
                build_rule_code=f"build_{req.source_table_name.replace('.', '_')}_{req.canonical_field_name}",
                rebuild_sql_hint=(
                    "UPSERT canonical field into source table, set source_quality_status, "
                    "and write one governance.source_lineage_v1 row per field."
                ),
            )
        )
    return SourceBuildPlan(
        source_table_name=request.source_table_name,
        symbol=request.symbol,
        trade_date=request.trade_date,
        start_date=request.start_date,
        end_date=request.end_date,
        step_count=len(steps),
        steps=steps,
        execution_order=[
            "1. Fetch or verify raw provider rows in one-interface-one-table raw_* tables.",
            "2. Validate raw schema hash and row-level quality gates.",
            "3. Normalize units and field names into canonical source fields.",
            "4. Compare primary and backup provider values where backup exists.",
            "5. Upsert source.* canonical facts with source_quality_status.",
            "6. Write governance.source_lineage_v1 for every canonical field.",
            "7. Re-run readiness and gap diagnostics before model release tasks.",
        ],
    )


def build_readiness_matrix() -> ReadinessMatrixOut:
    requirements = list_source_requirements()
    table_names = sorted({item.source_table_name for item in requirements})
    rows: list[ReadinessMatrixRow] = []
    for table_name in table_names:
        table_requirements = [item for item in requirements if item.source_table_name == table_name]
        p0 = [item for item in table_requirements if item.required_level.value == "P0"]
        p1 = [item for item in table_requirements if item.required_level.value == "P1"]
        missing_backup = [
            item.canonical_field_name
            for item in p0 + p1
            if item.backup_provider is None and not item.allows_missing_backup()
        ]
        status = "passed"
        if missing_backup:
            status = "blocked"
        elif not p0:
            status = "research_only"
        rows.append(
            ReadinessMatrixRow(
                source_table_name=table_name,
                p0_field_count=len(p0),
                p1_field_count=len(p1),
                total_field_count=len(table_requirements),
                fields_with_backup_count=sum(1 for item in table_requirements if item.backup_provider is not None),
                readiness_status=status,
                blocking_reasons=[f"missing backup provider for {field}" for field in missing_backup],
            )
        )
    return ReadinessMatrixOut(table_count=len(rows), rows=rows)


def build_probe_matrix() -> SourceProbeMatrixOut:
    rows: list[SourceProbeMatrixRow] = []
    runtime_status = {
        (item.provider, item.api_name): item
        for item in list_provider_status()
        if item.api_name is not None
    }
    required_api_keys: set[tuple[Provider, str]] = set()
    for requirement in list_source_requirements():
        if requirement.required_level.value == "P0" and requirement.required_for_online:
            for provider, api_name in (
                (requirement.primary_provider, requirement.primary_api_name),
                (requirement.backup_provider, requirement.backup_api_name),
            ):
                if provider is None or api_name is None or provider == Provider.INTERNAL:
                    continue
                status = runtime_status.get((provider, api_name))
                spec = get_api_spec(provider, api_name)
                if status and status.adapter_implemented and not spec.requires_token:
                    required_api_keys.add((provider, api_name))
    for spec in list_api_specs():
        status = runtime_status.get((spec.provider, spec.api_name))
        adapter_ready = bool(status and status.adapter_implemented)
        real_probe_required = (spec.provider, spec.api_name) in required_api_keys
        if real_probe_required:
            note = "Production gate required: P0 online source route with implemented free/public adapter."
        elif not adapter_ready:
            note = "Registered for contract/repair planning; adapter migration pending, so it is not a production-gate real probe yet."
        elif spec.requires_token:
            note = "Token/paid provider: credential and entitlement probe is operator evidence, not mandatory for free-source production gate."
        elif spec.is_free:
            note = "Free/public provider: real probe before enabling this API for online model use."
        else:
            note = "Provider probe required before this API becomes an online gate or model input."
        rows.append(
            SourceProbeMatrixRow(
                provider=spec.provider,
                api_name=spec.api_name,
                raw_table_name=spec.raw_table_name,
                sample_params=spec.request_template,
                expected_fields=spec.response_fields,
                canonical_targets=spec.canonical_targets,
                dry_run_supported=True,
                real_probe_required=real_probe_required,
                readiness_note=note,
            )
        )
    return SourceProbeMatrixOut(api_count=len(rows), rows=rows)


def build_repair_routes() -> RepairRouteOut:
    rows: list[RepairRouteRow] = []
    for req in list_source_requirements():
        contract = next(
            (c for c in list_field_contracts(req.source_table_name) if c.canonical_field_name == req.canonical_field_name),
            None,
        )
        rows.append(
            RepairRouteRow(
                source_table_name=req.source_table_name,
                canonical_field_name=req.canonical_field_name,
                required_level=req.required_level,
                primary_provider=req.primary_provider,
                primary_api_name=req.primary_api_name,
                primary_raw_table_name=req.repair_raw_table_name,
                backup_provider=req.backup_provider,
                backup_api_name=req.backup_api_name,
                online_policy=(contract.online_policy if contract else "degradable"),
                used_by_models=req.used_by_models,
            )
        )
    return RepairRouteOut(route_count=len(rows), rows=rows)
