from __future__ import annotations

import importlib.util
from collections import defaultdict
from typing import Any

from source_data_service.adapters import get_adapter
from source_data_service.models import Provider, ProviderRuntimeStatus, RawFetchResult
from source_data_service.provider_registry import get_api_spec, list_api_specs
from source_data_service.resilience import CircuitOpenError, RetryPolicy, state
from source_data_service.settings import settings

_LAST_ERRORS: dict[str, str] = {}

_OPTIONAL_PACKAGE_BY_PROVIDER: dict[Provider, str] = {
    Provider.BAOSTOCK: "baostock",
    Provider.AKSHARE: "akshare",
    Provider.TUSHARE: "tushare",
}

_IMPLEMENTED_ADAPTERS = {Provider.BAOSTOCK, Provider.AKSHARE, Provider.TUSHARE}


def provider_runtime_key(provider: Provider, api_name: str) -> str:
    return f"{provider.value}.{api_name}"


def optional_package_available(provider: Provider) -> bool | None:
    package_name = _OPTIONAL_PACKAGE_BY_PROVIDER.get(provider)
    if package_name is None:
        return None
    return importlib.util.find_spec(package_name) is not None


def execute_provider_fetch(
    *,
    provider: Provider,
    api_name: str,
    params: dict[str, Any],
    dry_run: bool = False,
) -> RawFetchResult:
    """Execute a provider fetch without allowing provider failure to kill the service.

    This wrapper applies per provider+api circuit breaking and retry. Failures are
    returned as structured RawFetchResult.error so orchestration, data inspection,
    and repair planning can fall back to a backup provider while the service stays
    alive.
    """
    spec = get_api_spec(provider, api_name)
    key = provider_runtime_key(provider, api_name)
    breaker = state.get_circuit(
        key,
        failure_threshold=settings.circuit_breaker_failure_threshold,
        recovery_seconds=settings.circuit_breaker_recovery_seconds,
    )
    try:
        breaker.before_call()
        adapter = get_adapter(provider)
        policy = RetryPolicy(max_retries=settings.provider_max_retries)
        result = policy.run(lambda: adapter.fetch(api_name, params, dry_run=dry_run))
        breaker.record_success()
        _LAST_ERRORS.pop(key, None)
        return result
    except CircuitOpenError as exc:
        _LAST_ERRORS[key] = str(exc)
        return RawFetchResult(
            provider=provider,
            api_name=api_name,
            raw_table_name=spec.raw_table_name,
            request_params=params,
            dry_run=dry_run,
            row_count=0,
            rows=[],
            warning="provider circuit open; use backup provider or try later",
            error=str(exc),
        )
    except Exception as exc:  # noqa: BLE001 - provider adapters are intentionally isolated
        breaker.record_failure()
        _LAST_ERRORS[key] = str(exc)
        return RawFetchResult(
            provider=provider,
            api_name=api_name,
            raw_table_name=spec.raw_table_name,
            request_params=params,
            dry_run=dry_run,
            row_count=0,
            rows=[],
            warning="provider fetch failed; service remained alive and caller should use repair/fallback plan",
            error=str(exc),
        )


def list_provider_status(provider: Provider | None = None) -> list[ProviderRuntimeStatus]:
    specs = list_api_specs()
    if provider is not None:
        specs = [spec for spec in specs if spec.provider == provider]
    rows: list[ProviderRuntimeStatus] = []
    seen: set[tuple[Provider, str]] = set()
    for spec in specs:
        key = provider_runtime_key(spec.provider, spec.api_name)
        breaker = state.get_circuit(
            key,
            failure_threshold=settings.circuit_breaker_failure_threshold,
            recovery_seconds=settings.circuit_breaker_recovery_seconds,
        )
        seen.add((spec.provider, spec.api_name))
        rows.append(
            ProviderRuntimeStatus(
                provider=spec.provider,
                api_name=spec.api_name,
                adapter_implemented=spec.provider in _IMPLEMENTED_ADAPTERS,
                optional_package_available=optional_package_available(spec.provider),
                circuit_state="open" if breaker.opened_at is not None else "closed",
                failure_count=breaker.failure_count,
                recovery_seconds=settings.circuit_breaker_recovery_seconds,
                last_error=_LAST_ERRORS.get(key),
            )
        )
    return rows


def provider_summary() -> dict[str, int]:
    totals: dict[str, int] = defaultdict(int)
    for item in list_provider_status():
        totals["registered_api_count"] += 1
        if item.adapter_implemented:
            totals["implemented_api_count"] += 1
        if item.circuit_state == "open":
            totals["open_circuit_count"] += 1
        if item.last_error:
            totals["last_error_count"] += 1
    return dict(totals)
