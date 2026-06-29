from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Query

from data_inspector_service.contracts import all_contracts
from data_inspector_service.inspector import DataInspector
from data_inspector_service.repository import DataInspectorRepository
from data_inspector_service.schemas import (
    DomainContractOut,
    InspectionGapRecordOut,
    InspectionRunCreate,
    InspectionRunOut,
)
from data_inspector_service.service_factory import build_client, build_repository, settings


router = APIRouter(tags=["data-inspector"])


def get_repository() -> DataInspectorRepository:
    return build_repository()


def get_inspector() -> DataInspector:
    return DataInspector(
        settings=settings,
        repository=build_repository(),
        client=build_client(),
    )


@router.get("/inspection-domain-contracts", response_model=list[DomainContractOut])
def list_domain_contracts() -> list[DomainContractOut]:
    return [DomainContractOut.model_validate(contract.to_dict()) for contract in all_contracts()]


@router.post("/inspection-domain-contracts/sync")
def sync_domain_contracts() -> dict[str, int | str]:
    repo = get_repository()
    return {
        "contract_kind": "data_inspection_domain_contract_sync_v2",
        "accepted_count": repo.sync_domain_contracts(all_contracts()),
    }


@router.post("/inspection-runs", response_model=InspectionRunOut, status_code=201)
def create_inspection_run(payload: InspectionRunCreate) -> InspectionRunOut:
    return get_inspector().build_inspection(payload)


@router.get("/inspection-runs/latest")
def get_latest_inspection_run(
    scope: str | None = Query(default=None),
    as_of_trading_day: date | None = Query(default=None),
) -> dict[str, object]:
    run = get_repository().latest_run_summary(scope=scope, as_of_trading_day=as_of_trading_day)
    if run is None:
        raise HTTPException(status_code=404, detail="No data inspection run found")
    return dict(run)


@router.get("/inspection-gaps", response_model=list[InspectionGapRecordOut])
def list_inspection_gaps(
    run_id: int | None = Query(default=None),
    severity: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
) -> list[InspectionGapRecordOut]:
    return get_repository().list_gap_records(run_id=run_id, severity=severity, symbol=symbol, limit=limit)


@router.get("/ui/data-inspector/latest")
def get_data_inspector_latest_ui_status(
    scope: str | None = Query(default=None),
    as_of_trading_day: date | None = Query(default=None),
) -> dict[str, object]:
    latest = get_repository().latest_run_summary(scope=scope, as_of_trading_day=as_of_trading_day)
    return {
        "contract_kind": "data_inspector_latest_ui_v2",
        "scope": scope,
        "as_of_trading_day": as_of_trading_day.isoformat() if as_of_trading_day else None,
        "latest_run": dict(latest) if latest is not None else None,
        "data_status": (latest or {}).get("status") or "no_run",
        "guardrails": {
            "read_only": True,
            "mutates_source_facts": False,
            "mutates_model_facts": False,
            "direct_provider_calls_allowed": False,
        },
    }
