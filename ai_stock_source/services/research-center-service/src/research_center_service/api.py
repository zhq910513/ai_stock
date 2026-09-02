from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from research_center_service.repository import ResearchCenterRepository, ResearchRepositoryError
from research_center_service.schemas import (
    LibraryMemberCreate,
    ManualLabelCreate,
    ReviewCreate,
    ValleyChartCaseCreate,
)
from research_center_service.service_factory import build_repository

router = APIRouter(tags=["research-center"])


def get_repository() -> ResearchCenterRepository:
    return build_repository()


@router.get("/research/ambush/taxonomy")
def list_ambush_taxonomy(label_mode: str | None = Query(default=None)) -> dict[str, object]:
    return {
        "contract_kind": "ambush_valley_taxonomy_v1",
        "items": get_repository().list_taxonomy(label_mode=label_mode),
        "guardrails": {
            "taxonomy_driven": True,
            "frontend_hardcode_required": False,
            "manual_labels_mutate_model_facts": False,
        },
    }


@router.get("/research/ambush/valley-chart/cases")
def list_valley_chart_cases(
    status: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, object]:
    return {
        "contract_kind": "ambush_valley_chart_cases_v1",
        "items": get_repository().list_cases(status=status, symbol=symbol, limit=limit),
        "empty_state": "暂无低谷图库样本" if not status and not symbol else "当前筛选下暂无样本",
    }


@router.post("/research/ambush/valley-chart/cases", status_code=status.HTTP_201_CREATED)
def create_valley_chart_case(payload: ValleyChartCaseCreate) -> dict[str, object]:
    try:
        item = get_repository().create_case(payload)
    except ResearchRepositoryError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"contract_kind": "ambush_valley_chart_case_v1", "item": item}


@router.get("/research/ambush/valley-chart/cases/{chart_case_id}")
def get_valley_chart_case(chart_case_id: str) -> dict[str, object]:
    item = get_repository().get_case(chart_case_id)
    if item is None:
        raise HTTPException(status_code=404, detail="低谷图库样本不存在。")
    return {"contract_kind": "ambush_valley_chart_case_detail_v1", "item": item}


@router.post("/research/ambush/valley-chart/cases/{chart_case_id}/labels", status_code=status.HTTP_201_CREATED)
def create_valley_chart_label(chart_case_id: str, payload: ManualLabelCreate) -> dict[str, object]:
    try:
        item = get_repository().create_label(chart_case_id, payload)
    except ResearchRepositoryError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "contract_kind": "ambush_valley_manual_label_v1",
        "item": item,
        "guardrails": {
            "append_only": True,
            "manual_label_mutates_official_signal": False,
            "as_of_outcome_isolation": True,
        },
    }


@router.post("/research/ambush/valley-chart/cases/{chart_case_id}/reviews", status_code=status.HTTP_201_CREATED)
def create_valley_chart_review(chart_case_id: str, payload: ReviewCreate) -> dict[str, object]:
    try:
        item = get_repository().create_review(chart_case_id, payload)
    except ResearchRepositoryError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"contract_kind": "ambush_valley_label_review_v1", "item": item}


@router.post("/research/ambush/valley-chart/cases/{chart_case_id}/library-members", status_code=status.HTTP_201_CREATED)
def create_valley_library_member(chart_case_id: str, payload: LibraryMemberCreate) -> dict[str, object]:
    try:
        item = get_repository().create_library_member(chart_case_id, payload)
    except ResearchRepositoryError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "contract_kind": "ambush_valley_pattern_library_member_v1",
        "item": item,
        "guardrails": {
            "requires_review_for_production_change": True,
            "mutates_model_parameters": False,
        },
    }
