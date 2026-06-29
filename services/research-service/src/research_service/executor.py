from __future__ import annotations

from typing import Any

from research_service.assembler import ResearchPayloadAssembler
from research_service.materializer import ResearchDecisionMaterializer
from research_service.owner_client import ModelOwnerClient, OwnerCallResult
from research_service.repository import ResearchPayloadRepository, new_id
from research_service.schemas import (
    ModelExecutionRunRequest,
    ModelExecutionRunResponse,
    ModelPayloadAssembleRequest,
    ModelPayloadAssembleResponse,
)
from research_service.task_registry import ASSEMBLED_RESEARCH_PAYLOAD_STATUS, get_requirement

HOT_SCORE_TASK = "hot.score.auction_confirmed"
HOT_RELEASE_GATE_TASK = "hot.release_gate.preopen"
HOT_BUY_POINT_TASK = "hot.buy_point.open_5m"
HOT_FANOUT_TASKS = {HOT_SCORE_TASK, HOT_RELEASE_GATE_TASK, HOT_BUY_POINT_TASK}


class ResearchModelExecutor:
    def __init__(
        self,
        *,
        assembler: ResearchPayloadAssembler,
        repository: ResearchPayloadRepository,
        owner_client: ModelOwnerClient,
        materializer: ResearchDecisionMaterializer,
    ) -> None:
        self.assembler = assembler
        self.repository = repository
        self.owner_client = owner_client
        self.materializer = materializer

    def run(self, request: ModelExecutionRunRequest) -> ModelExecutionRunResponse:
        if self._should_fanout_hot_task(request):
            return self._run_hot_task_fanout(request)
        return self._run_single(request)

    def _run_single(self, request: ModelExecutionRunRequest) -> ModelExecutionRunResponse:
        task = get_requirement(request.task_code)
        if task is None:
            raise ValueError(f"unknown task_code: {request.task_code}")
        assembly = self.assembler.assemble(
            ModelPayloadAssembleRequest(
                task_code=request.task_code,
                trade_date=request.trade_date,
                symbol=request.symbol,
                symbols=request.symbols,
                as_of_time_utc=request.as_of_time_utc,
                decision_time=request.decision_time,
                run_id=request.run_id,
                persist_audit=request.persist_audit,
                extra_context=request.extra_context,
            )
        )
        execution_id = request.execution_id or new_id("research_exec")
        base = self._base_response(execution_id, assembly)
        if assembly.payload_assembly_status != ASSEMBLED_RESEARCH_PAYLOAD_STATUS:
            response = base | {
                "execution_status": "blocked_data_gap",
                "accepted": False,
                "dispatch_allowed": False,
                "owner_called": False,
                "materialization_attempted": False,
                "gap_codes": assembly.gap_codes,
                "materialized_counts": {},
                "audit_persisted": False,
            }
            response["audit_persisted"] = self._persist(response, assembly, None, None)
            return ModelExecutionRunResponse(**response)
        owner_result: OwnerCallResult | None = None
        try:
            owner_result = self.owner_client.call_owner(
                task,
                payload=assembly.payload,
                run_id=assembly.run_id,
                as_of_time_utc=assembly.as_of_time_utc,
            )
        except Exception as exc:  # noqa: BLE001
            response = base | {
                "execution_status": "owner_failed",
                "accepted": False,
                "dispatch_allowed": True,
                "owner_called": True,
                "materialization_attempted": False,
                "gap_codes": ["owner_call_exception"],
                "error_code": "owner_call_exception",
                "error_message": str(exc),
                "materialized_counts": {},
                "audit_persisted": False,
            }
            response["audit_persisted"] = self._persist(response, assembly, None, None)
            return ModelExecutionRunResponse(**response)
        if not owner_result.accepted:
            response = base | {
                "execution_status": "owner_failed",
                "accepted": False,
                "dispatch_allowed": True,
                "owner_called": True,
                "materialization_attempted": False,
                "owner_endpoint": owner_result.endpoint,
                "owner_status_code": owner_result.status_code,
                "owner_response": owner_result.response_body,
                "gap_codes": ["owner_call_failed"],
                "error_code": "owner_call_failed",
                "error_message": f"status_code={owner_result.status_code}; url={owner_result.url}",
                "materialized_counts": {},
                "audit_persisted": False,
            }
            response["audit_persisted"] = self._persist(response, assembly, owner_result, None)
            return ModelExecutionRunResponse(**response)
        try:
            counts = self.materializer.materialize(task=task, assembly=assembly, owner_response=owner_result.response_body)
        except Exception as exc:  # noqa: BLE001
            response = base | {
                "execution_status": "materialization_failed",
                "accepted": False,
                "dispatch_allowed": True,
                "owner_called": True,
                "materialization_attempted": True,
                "owner_endpoint": owner_result.endpoint,
                "owner_status_code": owner_result.status_code,
                "owner_response": owner_result.response_body,
                "gap_codes": ["materialization_exception"],
                "error_code": "materialization_exception",
                "error_message": str(exc),
                "materialized_counts": {},
                "audit_persisted": False,
            }
            response["audit_persisted"] = self._persist(response, assembly, owner_result, None)
            return ModelExecutionRunResponse(**response)
        materializer_gaps = list(counts.get("materializer_gap_codes") or [])
        persisted_count = sum(int(value) for key, value in counts.items() if key != "materializer_gap_codes" and isinstance(value, int))
        if persisted_count > 0 and not materializer_gaps:
            status = "materialized"
            accepted = True
        elif persisted_count > 0:
            status = "materialized_with_gaps"
            accepted = False
        else:
            status = "materialization_skipped"
            accepted = False
            materializer_gaps.append(f"research_materializer_no_rows:{task.task_code}")
        response = base | {
            "execution_status": status,
            "accepted": accepted,
            "dispatch_allowed": True,
            "owner_called": True,
            "materialization_attempted": True,
            "owner_endpoint": owner_result.endpoint,
            "owner_status_code": owner_result.status_code,
            "owner_response": owner_result.response_body,
            "gap_codes": materializer_gaps,
            "materialized_counts": counts,
            "audit_persisted": False,
        }
        response["audit_persisted"] = self._persist(response, assembly, owner_result, counts)
        return ModelExecutionRunResponse(**response)

    def _run_hot_task_fanout(self, request: ModelExecutionRunRequest) -> ModelExecutionRunResponse:
        symbols = self._hot_fanout_symbols(request)
        if not symbols:
            return self._run_blocked_hot_empty_pool(request)

        execution_id = request.execution_id or new_id("research_exec_batch")
        child_responses: list[ModelExecutionRunResponse] = []
        for index, symbol in enumerate(symbols, start=1):
            child_context = dict(request.extra_context or {})
            child_context.update(
                {
                    "hot_stage_fanout_child": True,
                    "hot_stage_fanout_task_code": request.task_code,
                    "hot_stage_fanout_parent_execution_id": execution_id,
                    "hot_stage_fanout_index": index,
                    "hot_stage_fanout_total": len(symbols),
                }
            )
            if request.task_code == HOT_SCORE_TASK:
                child_context["hot_score_fanout_child"] = True
            child_request = ModelExecutionRunRequest(
                task_code=request.task_code,
                trade_date=request.trade_date,
                symbol=symbol,
                symbols=[symbol],
                as_of_time_utc=request.as_of_time_utc,
                decision_time=request.decision_time,
                run_id=f"{request.run_id or request.task_code}:{symbol}",
                persist_audit=request.persist_audit,
                extra_context=child_context,
            )
            child_responses.append(self._run_single(child_request))

        assembly = child_responses[0].assembly
        counts = self._fanout_counts(child_responses, symbols, task_code=request.task_code)
        materializer_gaps = sorted({gap for response in child_responses for gap in response.gap_codes})
        persisted_count = sum(
            int(value)
            for key, value in counts.items()
            if key not in {"fanout_total", "fanout_materialized", "fanout_blocked", "fanout_failed"}
            and isinstance(value, int)
        )
        if counts["fanout_materialized"] == counts["fanout_total"] and not materializer_gaps:
            status = "materialized"
            accepted = True
        elif persisted_count > 0:
            status = "materialized_with_gaps"
            accepted = False
        else:
            status = "materialization_skipped"
            accepted = False
            materializer_gaps.append(f"research_materializer_no_rows:{request.task_code}")

        response = self._base_response(execution_id, assembly) | {
            "symbol": None,
            "run_id": request.run_id or f"hot_stage_fanout:{request.task_code}:{request.trade_date.isoformat()}",
            "execution_status": status,
            "accepted": accepted,
            "dispatch_allowed": True,
            "owner_called": any(item.owner_called for item in child_responses),
            "materialization_attempted": any(item.materialization_attempted for item in child_responses),
            "owner_endpoint": assembly.payload.get("owner_endpoint"),
            "owner_status_code": None,
            "owner_response": {
                "fanout_contract": counts["fanout_contract"],
                "task_code": request.task_code,
                "child_execution_ids": [item.execution_id for item in child_responses],
                "child_status_counts": self._fanout_status_counts(child_responses),
            },
            "gap_codes": sorted(set(materializer_gaps)),
            "materialized_counts": counts,
            "audit_persisted": False,
        }
        response["audit_persisted"] = self._persist(response, assembly, None, counts, symbol_override=None)
        return ModelExecutionRunResponse(**response)

    def _run_blocked_hot_empty_pool(self, request: ModelExecutionRunRequest) -> ModelExecutionRunResponse:
        assembly = self.assembler.assemble(
            ModelPayloadAssembleRequest(
                task_code=request.task_code,
                trade_date=request.trade_date,
                symbol=request.symbol,
                symbols=request.symbols,
                as_of_time_utc=request.as_of_time_utc,
                decision_time=request.decision_time,
                run_id=request.run_id,
                persist_audit=request.persist_audit,
                extra_context=request.extra_context,
            )
        )
        execution_id = request.execution_id or new_id("research_exec")
        gap_codes = sorted(set([*assembly.gap_codes, self._hot_empty_pool_gap(request.task_code)]))
        response = self._base_response(execution_id, assembly) | {
            "execution_status": "blocked_data_gap",
            "accepted": False,
            "dispatch_allowed": False,
            "owner_called": False,
            "materialization_attempted": False,
            "gap_codes": gap_codes,
            "materialized_counts": {
                "fanout_total": 0,
                "fanout_materialized": 0,
                "fanout_blocked": 0,
                "fanout_failed": 0,
            },
            "audit_persisted": False,
        }
        response["audit_persisted"] = self._persist(response, assembly, None, response["materialized_counts"])
        return ModelExecutionRunResponse(**response)

    def _base_response(self, execution_id: str, assembly: ModelPayloadAssembleResponse) -> dict[str, Any]:
        return {
            "execution_id": execution_id,
            "assembly": assembly,
            "task_code": assembly.task_code,
            "owner_service": assembly.owner_service,
            "model_code": assembly.model_code,
            "model_phase": assembly.model_phase,
            "symbol": assembly.symbols[0] if assembly.symbols else None,
            "trade_date": assembly.trade_date,
            "run_id": assembly.run_id,
            "payload_hash": assembly.payload_hash,
            "owner_endpoint": None,
            "owner_status_code": None,
            "owner_response": None,
            "gap_codes": [],
            "error_code": None,
            "error_message": None,
        }

    def _persist(
        self,
        response: dict[str, Any],
        assembly: ModelPayloadAssembleResponse,
        owner_result: OwnerCallResult | None,
        counts: dict[str, Any] | None,
        symbol_override: str | None = "",
    ) -> bool:
        return self.repository.persist_execution_audit(
            execution_id=response["execution_id"],
            assembly_id=assembly.assembly_id,
            task_code=assembly.task_code,
            owner_service=assembly.owner_service,
            model_code=assembly.model_code,
            model_phase=assembly.model_phase,
            symbol=(assembly.symbols[0] if assembly.symbols else None) if symbol_override == "" else symbol_override,
            trade_date=assembly.trade_date,
            run_id=response.get("run_id") or assembly.run_id,
            payload_hash=assembly.payload_hash,
            owner_endpoint=owner_result.endpoint if owner_result else response.get("owner_endpoint"),
            owner_status_code=owner_result.status_code if owner_result else response.get("owner_status_code"),
            execution_status=response["execution_status"],
            accepted=bool(response["accepted"]),
            dispatch_allowed=bool(response["dispatch_allowed"]),
            owner_called=bool(response["owner_called"]),
            materialization_attempted=bool(response["materialization_attempted"]),
            gap_codes=list(response.get("gap_codes") or []),
            error_code=response.get("error_code"),
            error_message=response.get("error_message"),
            owner_request=owner_result.request_body if owner_result else None,
            owner_response=owner_result.response_body if owner_result else response.get("owner_response"),
            materialized_counts=counts or response.get("materialized_counts") or {},
        )

    @staticmethod
    def _should_fanout_hot_task(request: ModelExecutionRunRequest) -> bool:
        if request.task_code not in HOT_FANOUT_TASKS:
            return False
        if request.extra_context.get("hot_stage_fanout_child") is True:
            return False
        has_scheduler_context = bool(
            request.extra_context.get("scheduler_task_instance_id")
            or request.extra_context.get("scheduler_materialized_instance")
        )
        has_multi_symbol_request = len(request.symbols) > 1
        has_manual_symbol = bool(request.symbol or request.symbols)
        return has_scheduler_context or has_multi_symbol_request or not has_manual_symbol

    def _hot_fanout_symbols(self, request: ModelExecutionRunRequest) -> list[str]:
        has_scheduler_context = bool(
            request.extra_context.get("scheduler_task_instance_id")
            or request.extra_context.get("scheduler_materialized_instance")
        )
        if len(request.symbols) > 1 and not has_scheduler_context:
            return request.symbols
        if request.task_code == HOT_SCORE_TASK:
            return self.repository.fetch_hot_score_candidate_symbols(trade_date=request.trade_date)
        fetch_stage_symbols = getattr(self.repository, "fetch_hot_stage_candidate_symbols", None)
        if callable(fetch_stage_symbols):
            return fetch_stage_symbols(trade_date=request.trade_date, task_code=request.task_code)
        return []

    @staticmethod
    def _fanout_counts(responses: list[ModelExecutionRunResponse], symbols: list[str], *, task_code: str) -> dict[str, Any]:
        contract = "research_hot_score_fanout_v1" if task_code == HOT_SCORE_TASK else "research_hot_stage_fanout_v1"
        counts: dict[str, Any] = {
            "fanout_contract": contract,
            "fanout_task_code": task_code,
            "fanout_total": len(symbols),
            "fanout_materialized": sum(1 for item in responses if item.execution_status == "materialized"),
            "fanout_blocked": sum(1 for item in responses if item.execution_status == "blocked_data_gap"),
            "fanout_failed": sum(1 for item in responses if item.execution_status in {"owner_failed", "materialization_failed"}),
            "fanout_symbols": symbols,
        }
        for response in responses:
            for key, value in response.materialized_counts.items():
                if isinstance(value, int):
                    counts[key] = int(counts.get(key, 0)) + value
        return counts

    @staticmethod
    def _fanout_status_counts(responses: list[ModelExecutionRunResponse]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for response in responses:
            counts[response.execution_status] = counts.get(response.execution_status, 0) + 1
        return counts

    @staticmethod
    def _hot_empty_pool_gap(task_code: str) -> str:
        if task_code == HOT_SCORE_TASK:
            return "source_gap:hot_score_candidate_pool_empty"
        return "source_gap:hot_stage_candidate_pool_empty"
