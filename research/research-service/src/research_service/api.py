from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from research_service.assembler import PayloadAssemblyError, requirements_payload
from research_service.schemas import ModelExecutionRunRequest, ModelPayloadAssembleRequest
from research_service.service_factory import build_assembler, build_executor, build_repository

router = APIRouter(tags=["research-payload-assembler"])


@router.get("/research/model-payload/requirements")
def model_payload_requirements() -> dict:
    return requirements_payload()


@router.get("/research/model-list/hot")
def hot_model_list(limit: int = Query(default=100, ge=1, le=1000)) -> dict:
    return build_repository().fetch_hot_model_list(limit=limit)


@router.post("/research/model-payload/assemble")
def assemble_model_payload(payload: ModelPayloadAssembleRequest) -> dict:
    try:
        return build_assembler().assemble(payload).model_dump()
    except PayloadAssemblyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/research/model-execution/run")
def run_model_execution(payload: ModelExecutionRunRequest) -> dict:
    try:
        return build_executor().run(payload).model_dump()
    except PayloadAssemblyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
