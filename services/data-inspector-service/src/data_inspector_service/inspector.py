from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from data_inspector_service.client import ServiceClient, ServiceResult
from data_inspector_service.contracts import contracts_for_scope
from data_inspector_service.repository import DataInspectorRepository
from data_inspector_service.schemas import (
    InspectionGapOut,
    InspectionRunCreate,
    InspectionRunOut,
    InspectionSubjectOut,
    RemediationTaskOut,
)
from data_inspector_service.settings import Settings


PREFLIGHT_TARGETS: tuple[tuple[str, str, str], ...] = (
    ("hot_candidates", "preopen_release_gate", "hot_candidates_release_preflight"),
    ("candidate_memory", "outcome_label", "candidate_memory_release_preflight"),
    ("ambush_watchlist", "release_gate", "ambush_watchlist_release_preflight"),
    ("t_board_relay", "day1_scan", "t_board_relay_day1_preflight"),
    ("t_board_relay", "day2_trigger", "t_board_relay_day2_preflight"),
)
MODEL_CODES: tuple[str, ...] = ("hot_candidates", "candidate_memory", "ambush_watchlist", "t_board_relay")
MODEL_SERVICE_BY_CODE = {
    "hot_candidates": "hot-candidates-service",
    "candidate_memory": "candidate-memory-service",
    "ambush_watchlist": "ambush-watchlist-service",
    "t_board_relay": "t-board-relay-service",
}
MODEL_CODE_ALIASES = {
    "hot": "hot_candidates",
    "hot_candidates": "hot_candidates",
    "hot_candidates_service": "hot_candidates",
    "candidate_memory": "candidate_memory",
    "candidate_memory_service": "candidate_memory",
    "memory": "candidate_memory",
    "ambush": "ambush_watchlist",
    "ambush_watchlist": "ambush_watchlist",
    "ambush_watchlist_service": "ambush_watchlist",
    "model4": "t_board_relay",
    "model_four": "t_board_relay",
    "t_board": "t_board_relay",
    "t_board_relay": "t_board_relay",
    "t_board_relay_service": "t_board_relay",
    "t_relay": "t_board_relay",
}
RESEARCH_PAYLOAD_REQUIREMENTS_ENDPOINT = "/scheduler/model-payload/requirements"
RESEARCH_PAYLOAD_ASSEMBLE_PREFLIGHT_ENDPOINT = "/scheduler/model-payload/assemble-preflight"


def guardrails() -> dict[str, Any]:
    return {
        "read_only": True,
        "mutates_market_facts": False,
        "mutates_source_facts": False,
        "mutates_model_facts": False,
        "mutates_recommendation_scores": False,
        "can_publish_or_trade": False,
        "direct_provider_calls_allowed": False,
        "fetch_repairs_must_use_source_data_service_orchestration": True,
    }


def _status_from_gaps(gaps: list[InspectionGapOut]) -> str:
    if any(gap.severity == "P0" or gap.blocks_publish or gap.blocks_scoring for gap in gaps):
        return "blocked"
    if any(gap.severity == "P1" for gap in gaps):
        return "degraded"
    if gaps:
        return "warning"
    return "ready"


def _parse_required_model_codes(value: list[str] | tuple[str, ...] | str | None) -> tuple[str, ...]:
    if value is None:
        return MODEL_CODES
    if isinstance(value, str):
        text = value.strip()
        lowered = text.lower()
        if lowered in {"all", "*"}:
            return MODEL_CODES
        if lowered in {"", "none", "disabled", "off", "false"}:
            return ()
        tokens = [token.strip() for token in text.replace(";", ",").replace(" ", ",").split(",") if token.strip()]
    else:
        tokens = [str(token).strip() for token in value if str(token).strip()]
    required: set[str] = set()
    for token in tokens:
        normalized = token.lower().replace("-", "_")
        if normalized in {"all", "*"}:
            return MODEL_CODES
        if normalized in {"none", "disabled", "off", "false"}:
            continue
        model_code = MODEL_CODE_ALIASES.get(normalized)
        if model_code is None:
            raise ValueError(f"unknown required model service: {token}")
        required.add(model_code)
    return tuple(code for code in MODEL_CODES if code in required)


def _domain_gap(
    *,
    domain_code: str,
    target_table: str,
    severity: str,
    details: dict[str, Any],
    symbol: str = "__service__",
    trading_day: date | None = None,
    blocks_scoring: bool = True,
    blocks_publish: bool = True,
    remediation_status: str = "pending",
    gap_type: str = "domain_blocked",
) -> InspectionGapOut:
    return InspectionGapOut(
        symbol=symbol,
        gap_type=gap_type,
        domain_code=domain_code,
        target_table=target_table,
        severity=severity,
        trading_day=trading_day,
        missing_count=1,
        expected_count=1,
        observed_count=0,
        blocks_scoring=blocks_scoring,
        blocks_publish=blocks_publish,
        replay_safe=True,
        provider_lineage_required=False,
        remediation_status=remediation_status,
        details=details,
    )


def _remediation_for_gap(gap: InspectionGapOut) -> RemediationTaskOut:
    action_type = "inspect_source_contract"
    owner_service = "source-data-service"
    provider_candidates: list[str] = []
    if gap.domain_code == "source_queue_health":
        action_type = "inspect_fetch_queue"
    elif gap.domain_code.endswith("_release_preflight"):
        action_type = "repair_source_release_preflight"
        provider_candidates = [str(item) for item in gap.details.get("provider_candidates", [])]
    elif gap.domain_code == "source_lineage_presence":
        action_type = "rebuild_source_lineage"
    elif gap.domain_code == "scheduler_ready":
        action_type = "inspect_scheduler_runtime"
        owner_service = "scheduler-service"
    elif gap.domain_code.endswith("_model_ready"):
        action_type = "inspect_model_service_health"
        owner_service = str(gap.details.get("owner_service") or "models_services")
    elif gap.domain_code == "research_payload_assembly":
        gap_codes = [str(item) for item in gap.details.get("gap_codes", [])]
        blocking_reasons = [str(item) for item in gap.details.get("blocking_reasons", [])]
        action_type = "diagnose_research_payload_assembly"
        owner_service = "research-service"
        if any(code.startswith("source_gap:") for code in gap_codes) or blocking_reasons:
            action_type = "repair_research_payload_source_gap"
            owner_service = "source-data-service"
    priority = "high" if gap.severity == "P0" else "normal" if gap.severity == "P1" else "low"
    return RemediationTaskOut(
        gap_id=gap.gap_id,
        action_type=action_type,
        owner_service=owner_service,
        priority=priority,
        provider_candidates=provider_candidates,
        request_payload={
            "domain_code": gap.domain_code,
            "target_table": gap.target_table,
            "symbol": gap.symbol,
            "trading_day": gap.trading_day.isoformat() if gap.trading_day else None,
            "details": gap.details,
            "must_use_fetch_orchestration": True,
        },
        status="suggested",
    )


class DataInspector:
    def __init__(
        self,
        *,
        settings: Settings,
        repository: DataInspectorRepository,
        client: ServiceClient,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.client = client

    def build_inspection(self, payload: InspectionRunCreate) -> InspectionRunOut:
        started_at = datetime.now(timezone.utc)
        as_of_time = payload.as_of_time or started_at
        as_of_trading_day = payload.as_of_trading_day or date.fromisoformat(self.settings.default_trade_date)
        persist = self.settings.persist_default if payload.persist is None else payload.persist
        symbols = payload.symbols or [self.settings.default_symbol]

        gaps: list[InspectionGapOut] = []
        observed_domains: set[str] = set()
        diagnostics: dict[str, Any] = {
            "source_base_url": self.settings.source_data_service_base_url,
            "symbols": symbols,
        }

        if payload.scope in {"startup_guard", "core_closure", "source_release_gate"}:
            observed, new_gaps, evidence = self._inspect_source_foundation(as_of_trading_day=as_of_trading_day)
            observed_domains.update(observed)
            gaps.extend(new_gaps)
            diagnostics["source_foundation"] = evidence

        if payload.scope in {
            "startup_guard",
            "core_closure",
            "source_release_gate",
            "model_hot_decision_review",
            "model_memory_decision_review",
            "model_ambush_decision_review",
            "model_t_board_relay_decision_review",
        }:
            observed, new_gaps, evidence = self._inspect_release_preflight(
                trade_date=as_of_trading_day,
                symbols=symbols,
                include_targets=self._target_filter_for_scope(payload.scope),
            )
            observed_domains.update(observed)
            gaps.extend(new_gaps)
            diagnostics["release_preflight"] = evidence

        if payload.scope in {
            "startup_guard",
            "core_closure",
            "source_release_gate",
            "source_lineage",
            "model_hot_decision_review",
            "model_memory_decision_review",
            "model_ambush_decision_review",
            "model_t_board_relay_decision_review",
        }:
            observed, new_gaps, evidence = self._inspect_source_lineage()
            observed_domains.update(observed)
            gaps.extend(new_gaps)
            diagnostics["source_lineage"] = evidence

        if payload.scope in {"core_closure", "model_t_board_relay_decision_review"}:
            observed, new_gaps, evidence = self._inspect_t_board_repository()
            observed_domains.update(observed)
            gaps.extend(new_gaps)
            diagnostics["t_board_repository"] = evidence

        if payload.scope == "core_closure":
            observed, new_gaps, evidence = self._inspect_runtime_services()
            observed_domains.update(observed)
            gaps.extend(new_gaps)
            diagnostics["runtime_services"] = evidence

        if payload.scope == "research_payload_assembly":
            observed, new_gaps, evidence = self._inspect_research_payload_assembly(
                trade_date=as_of_trading_day,
                as_of_time=as_of_time,
                symbols=symbols,
            )
            observed_domains.update(observed)
            gaps.extend(new_gaps)
            diagnostics["research_payload_assembly"] = evidence

        contracts = contracts_for_scope(payload.scope)
        expected_domains = {contract.domain_code for contract in contracts}
        expected_count = max(len(expected_domains), 1)
        missing_domains = sorted(expected_domains - observed_domains)
        p0_gap_count = sum(1 for gap in gaps if gap.severity == "P0")
        p1_gap_count = sum(1 for gap in gaps if gap.severity == "P1")
        status = _status_from_gaps(gaps)
        warning_codes = self._warning_codes(diagnostics)
        completeness = (Decimal(len(observed_domains & expected_domains)) / Decimal(expected_count)).quantize(Decimal("0.000001"))
        subject = InspectionSubjectOut(
            symbol="__service__",
            scope=payload.scope,
            expected_domain_count=expected_count,
            observed_domain_count=len(observed_domains & expected_domains),
            missing_domain_count=len(missing_domains),
            inspection_status=status,
            completeness_score=completeness,
            publish_due_expected_domain_count=expected_count,
            publish_due_observed_domain_count=len(observed_domains & expected_domains),
            publish_due_missing_domain_count=len(missing_domains),
            publish_due_completeness_score=completeness,
            publish_due_status="blocked" if status == "blocked" else "ready",
            publish_due_missing_domains=missing_domains,
            missing_domains=missing_domains,
            gap_count=len(gaps),
            p0_gap_count=p0_gap_count,
            p1_gap_count=p1_gap_count,
            summary={
                "observed_domains": sorted(observed_domains),
                "missing_domains": missing_domains,
                "expected_domains": sorted(expected_domains),
                "diagnostics": diagnostics,
            },
        )
        run = InspectionRunOut(
            scope=payload.scope,
            as_of_trading_day=as_of_trading_day,
            as_of_time=as_of_time,
            lookback_days=payload.lookback_days,
            status=status,
            requested_subject_count=len(symbols),
            inspected_subject_count=1,
            gap_count=len(gaps),
            p0_gap_count=p0_gap_count,
            p1_gap_count=p1_gap_count,
            publish_due_completeness_score=completeness,
            publish_due_average_completeness_score=completeness,
            publish_due_status=subject.publish_due_status,
            publish_due_blocking_subject_count=1 if subject.publish_due_status == "blocked" else 0,
            publish_due_ready_subject_count=1 if subject.publish_due_status == "ready" else 0,
            publish_due_quarantined_subject_count=1 if subject.publish_due_status == "blocked" else 0,
            publish_due_publishable_subject_count=1 if subject.publish_due_status == "ready" else 0,
            publish_due_missing_domain_count=len(missing_domains),
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
            subjects=[subject],
            gaps=gaps,
            remediation_tasks=[_remediation_for_gap(gap) for gap in gaps],
            warning_codes=warning_codes,
            time_semantics={
                "as_of_trading_day": as_of_trading_day.isoformat(),
                "as_of_time": as_of_time.isoformat(),
                "source_fact_visibility": "source rows must pass quality_status, lineage and available_at checks",
            },
            guardrails=guardrails(),
        )
        if persist:
            run = self.repository.persist_run(run)
        return run

    @staticmethod
    def _target_filter_for_scope(scope: str) -> set[str] | None:
        return {
            "model_hot_decision_review": {"hot_candidates"},
            "model_memory_decision_review": {"candidate_memory"},
            "model_ambush_decision_review": {"ambush_watchlist"},
            "model_t_board_relay_decision_review": {"t_board_relay"},
        }.get(scope)

    def _inspect_source_foundation(self, *, as_of_trading_day: date) -> tuple[set[str], list[InspectionGapOut], dict[str, Any]]:
        observed: set[str] = set()
        gaps: list[InspectionGapOut] = []
        evidence: dict[str, Any] = {}

        readiness = self.client.get_source(
            "/source/ops/production-readiness",
            params={"require_postgres": "true", "require_real_provider_probe": "true"},
        )
        evidence["production_readiness"] = self._result_evidence(readiness)
        if readiness.ok and isinstance(readiness.data, dict) and readiness.data.get("status") == "passed" and not readiness.data.get("blocking_reasons") and not readiness.data.get("warning_reasons"):
            observed.add("source_production_readiness")
        else:
            gaps.append(
                _domain_gap(
                    domain_code="source_production_readiness",
                    target_table="/source/ops/production-readiness",
                    severity="P0",
                    trading_day=as_of_trading_day,
                    details=evidence["production_readiness"],
                    remediation_status="source_readiness_blocked",
                )
            )

        queue = self.client.get_source("/source/fetch/queues/summary")
        evidence["queue_summary"] = self._result_evidence(queue)
        queue_blocked = True
        if queue.ok and isinstance(queue.data, dict):
            rows = queue.data.get("rows") or queue.data.get("queues") or []
            queued = sum(int(row.get("queued_count") or 0) for row in rows if isinstance(row, dict))
            leased = sum(int(row.get("leased_count") or 0) for row in rows if isinstance(row, dict))
            dead = sum(int(row.get("dead_letter_count") or 0) for row in rows if isinstance(row, dict))
            queue_blocked = leased > 0 or dead > 0
            evidence["queue_totals"] = {"queued": queued, "leased": leased, "dead_letter": dead}
        if queue.ok and not queue_blocked:
            observed.add("source_queue_health")
        else:
            gaps.append(
                _domain_gap(
                    domain_code="source_queue_health",
                    target_table="/source/fetch/queues/summary",
                    severity="P0",
                    details=evidence["queue_summary"],
                    remediation_status="queue_blocked",
                )
            )

        contracts = self.client.get_source("/source/contracts")
        evidence["source_contracts"] = self._result_evidence(contracts, sample_limit=5)
        if contracts.ok and isinstance(contracts.data, list) and len(contracts.data) > 0:
            observed.add("source_contract_visibility")
        else:
            gaps.append(
                _domain_gap(
                    domain_code="source_contract_visibility",
                    target_table="/source/contracts",
                    severity="P0",
                    details=evidence["source_contracts"],
                    remediation_status="contract_unavailable",
                )
            )
        return observed, gaps, evidence

    def _inspect_release_preflight(
        self,
        *,
        trade_date: date,
        symbols: list[str],
        include_targets: set[str] | None,
    ) -> tuple[set[str], list[InspectionGapOut], dict[str, Any]]:
        observed: set[str] = set()
        gaps: list[InspectionGapOut] = []
        evidence: dict[str, Any] = {}
        for model_code, model_phase, domain_code in PREFLIGHT_TARGETS:
            if include_targets is not None and model_code not in include_targets:
                continue
            target_symbols = [self.settings.t_board_default_symbol] if model_code == "t_board_relay" else symbols
            result = self.client.post_source(
                "/source/release/preflight",
                {
                    "model_code": model_code,
                    "model_phase": model_phase,
                    "trade_date": trade_date.isoformat(),
                    "symbols": target_symbols,
                },
            )
            evidence[domain_code] = self._result_evidence(result)
            passed = (
                result.ok
                and isinstance(result.data, dict)
                and result.data.get("can_release_official_signal") is True
                and result.data.get("coverage_status") == "passed"
                and result.data.get("freshness_status") == "passed"
                and not result.data.get("blocking_reasons")
            )
            if passed:
                observed.add(domain_code)
                continue
            data = result.data if isinstance(result.data, dict) else {}
            gaps.append(
                _domain_gap(
                    domain_code=domain_code,
                    target_table="/source/release/preflight",
                    severity="P0",
                    symbol=target_symbols[0] if target_symbols else "__service__",
                    trading_day=trade_date,
                    details={
                        **self._result_evidence(result),
                        "blocking_reasons": data.get("blocking_reasons") if isinstance(data, dict) else [],
                        "degraded_reasons": data.get("degraded_reasons") if isinstance(data, dict) else [],
                        "repair_actions": data.get("repair_actions") if isinstance(data, dict) else [],
                    },
                    remediation_status="source_preflight_blocked",
                )
            )
        return observed, gaps, evidence

    def _inspect_research_payload_assembly(
        self,
        *,
        trade_date: date,
        as_of_time: datetime,
        symbols: list[str],
    ) -> tuple[set[str], list[InspectionGapOut], dict[str, Any]]:
        observed: set[str] = set()
        gaps: list[InspectionGapOut] = []
        evidence: dict[str, Any] = {"tasks": []}

        requirements = self.client.get_scheduler(RESEARCH_PAYLOAD_REQUIREMENTS_ENDPOINT)
        evidence["requirements"] = self._result_evidence(requirements, sample_limit=1)
        tasks = []
        if requirements.ok and isinstance(requirements.data, dict):
            raw_tasks = requirements.data.get("tasks") or []
            tasks = [item for item in raw_tasks if isinstance(item, dict) and item.get("task_code")]
        if not tasks:
            gaps.append(
                _domain_gap(
                    domain_code="research_payload_assembly",
                    target_table=RESEARCH_PAYLOAD_REQUIREMENTS_ENDPOINT,
                    severity="P0",
                    trading_day=trade_date,
                    details={**evidence["requirements"], "reason": "scheduler payload requirements unavailable or empty"},
                    remediation_status="research_payload_requirements_unavailable",
                    gap_type="research_payload_assembly_blocked",
                )
            )
            evidence["summary"] = {"task_count": 0, "assembled_count": 0, "blocked_count": 1}
            return observed, gaps, evidence

        assembled_count = 0
        for task in tasks:
            task_code = str(task.get("task_code"))
            task_symbols = self._symbols_for_research_payload_task(task_code=task_code, symbols=symbols)
            request_body = {
                "task_code": task_code,
                "symbol": task_symbols[0],
                "symbols": task_symbols,
                "trade_date": trade_date.isoformat(),
                "as_of_time_utc": as_of_time.isoformat(),
                "persist_audit": False,
                "extra_context": {
                    "inspection_scope": "research_payload_assembly",
                    "caller": "data-inspector-service",
                },
            }
            result = self.client.post_scheduler(RESEARCH_PAYLOAD_ASSEMBLE_PREFLIGHT_ENDPOINT, request_body)
            data = result.data if isinstance(result.data, dict) else {}
            assembly = data.get("assembly") if isinstance(data.get("assembly"), dict) else {}
            scheduler_preflight = data.get("scheduler_preflight") if isinstance(data.get("scheduler_preflight"), dict) else {}
            payload = assembly.get("payload") if isinstance(assembly.get("payload"), dict) else {}
            source_preflight = assembly.get("source_preflight") if isinstance(assembly.get("source_preflight"), dict) else payload.get("source_preflight")
            if not isinstance(source_preflight, dict):
                source_preflight = {}
            gap_codes = self._payload_gap_codes(assembly=assembly, payload=payload, scheduler_preflight=scheduler_preflight)
            blocking_reasons = [str(item) for item in source_preflight.get("blocking_reasons", [])]
            assembly_status = assembly.get("payload_assembly_status")
            preflight_valid = scheduler_preflight.get("valid") is True
            dispatch_allowed = data.get("dispatch_allowed") is True
            passed = (
                result.ok
                and assembly_status == "assembled_research_payload"
                and preflight_valid
                and dispatch_allowed
            )
            task_evidence = {
                "task_code": task_code,
                "task_kind": task.get("task_kind"),
                "owner_service": task.get("owner_service"),
                "official_publish": bool(task.get("official_publish")),
                "request": request_body,
                "response": self._research_payload_response_evidence(
                    result=result,
                    data=data,
                    assembly=assembly,
                    scheduler_preflight=scheduler_preflight,
                    source_preflight=source_preflight,
                ),
                "payload_assembly_status": assembly_status,
                "scheduler_preflight_valid": preflight_valid,
                "dispatch_allowed": dispatch_allowed,
                "gap_codes": gap_codes,
                "blocking_reasons": blocking_reasons,
            }
            evidence["tasks"].append(task_evidence)
            if passed:
                assembled_count += 1
                continue

            official_publish = bool(task.get("official_publish"))
            gaps.append(
                _domain_gap(
                    domain_code="research_payload_assembly",
                    target_table=RESEARCH_PAYLOAD_ASSEMBLE_PREFLIGHT_ENDPOINT,
                    severity="P0" if official_publish else "P1",
                    symbol=task_symbols[0],
                    trading_day=trade_date,
                    blocks_scoring=True,
                    blocks_publish=official_publish,
                    details={
                        "task_code": task_code,
                        "task_kind": task.get("task_kind"),
                        "owner_service": task.get("owner_service"),
                        "official_publish": official_publish,
                        "payload_assembly_status": assembly_status,
                        "scheduler_preflight_valid": preflight_valid,
                        "dispatch_allowed": dispatch_allowed,
                        "gap_codes": gap_codes,
                        "blocking_reasons": blocking_reasons,
                        "source_preflight": source_preflight,
                        "scheduler_response": self._research_payload_response_evidence(
                            result=result,
                            data=data,
                            assembly=assembly,
                            scheduler_preflight=scheduler_preflight,
                            source_preflight=source_preflight,
                        ),
                        "request": request_body,
                    },
                    remediation_status="research_payload_assembly_blocked",
                    gap_type="research_payload_assembly_blocked",
                )
            )

        evidence["summary"] = {
            "task_count": len(tasks),
            "assembled_count": assembled_count,
            "blocked_count": len(gaps),
            "endpoint": RESEARCH_PAYLOAD_ASSEMBLE_PREFLIGHT_ENDPOINT,
            "persist_audit": False,
        }
        if not gaps:
            observed.add("research_payload_assembly")
        return observed, gaps, evidence

    def _symbols_for_research_payload_task(self, *, task_code: str, symbols: list[str]) -> list[str]:
        if task_code.startswith("t_relay."):
            return [self.settings.t_board_default_symbol]
        return symbols or [self.settings.default_symbol]

    @staticmethod
    def _payload_gap_codes(
        *,
        assembly: dict[str, Any],
        payload: dict[str, Any],
        scheduler_preflight: dict[str, Any],
    ) -> list[str]:
        codes: list[str] = []
        for value in (
            assembly.get("gap_codes"),
            payload.get("source_gap_codes"),
            payload.get("contract_gaps"),
            scheduler_preflight.get("gap_codes"),
            scheduler_preflight.get("failure_codes"),
        ):
            if isinstance(value, list):
                codes.extend(str(item) for item in value)
        return sorted(set(codes))

    @staticmethod
    def _research_payload_response_evidence(
        *,
        result: ServiceResult,
        data: dict[str, Any],
        assembly: dict[str, Any],
        scheduler_preflight: dict[str, Any],
        source_preflight: dict[str, Any],
    ) -> dict[str, Any]:
        source_refs = assembly.get("source_refs")
        if not isinstance(source_refs, list):
            source_refs = []
        upstream_refs = assembly.get("upstream_refs")
        if not isinstance(upstream_refs, list):
            upstream_refs = []
        return {
            "ok": result.ok,
            "status_code": result.status_code,
            "error": result.error,
            "contract_kind": data.get("contract_kind"),
            "research_status_code": data.get("research_status_code"),
            "dispatch_allowed": data.get("dispatch_allowed"),
            "owner_service": data.get("owner_service") or assembly.get("owner_service"),
            "owner_endpoint": data.get("owner_endpoint"),
            "owner_request_body_preview_present": data.get("owner_request_body_preview") is not None,
            "assembly": {
                "assembly_id": assembly.get("assembly_id"),
                "task_code": assembly.get("task_code"),
                "payload_assembly_status": assembly.get("payload_assembly_status"),
                "payload_hash": assembly.get("payload_hash"),
                "audit_persisted": assembly.get("audit_persisted"),
                "gap_codes": assembly.get("gap_codes"),
                "source_ref_count": len(source_refs),
                "source_ref_sample": source_refs[:5],
                "upstream_ref_count": len(upstream_refs),
                "upstream_ref_sample": upstream_refs[:5],
            },
            "scheduler_preflight": {
                "valid": scheduler_preflight.get("valid"),
                "failure_codes": scheduler_preflight.get("failure_codes"),
                "gap_codes": scheduler_preflight.get("gap_codes"),
            },
            "source_preflight": {
                "can_release_official_signal": source_preflight.get("can_release_official_signal"),
                "coverage_status": source_preflight.get("coverage_status"),
                "freshness_status": source_preflight.get("freshness_status"),
                "blocking_reasons": source_preflight.get("blocking_reasons"),
                "degraded_reasons": source_preflight.get("degraded_reasons"),
            },
        }

    def _inspect_source_lineage(self) -> tuple[set[str], list[InspectionGapOut], dict[str, Any]]:
        counts = self.repository.source_table_counts()
        duplicate_summary = self.repository.lineage_duplicate_summary()
        evidence: dict[str, Any] = {
            "table_counts": counts,
            "duplicate_summary": duplicate_summary,
            "duplicate_policy": "non_blocking_governance_observation",
        }
        required_positive = (
            "source_adjusted_daily_bar_v1",
            "governance_source_lineage_v1",
        )
        if all(counts.get(key, 0) > 0 for key in required_positive):
            return {"source_lineage_presence"}, [], evidence
        gap = _domain_gap(
            domain_code="source_lineage_presence",
            target_table="governance.source_lineage_v1",
            severity="P0",
            details=evidence,
            remediation_status="lineage_missing",
        )
        return set(), [gap], evidence

    def _inspect_t_board_repository(self) -> tuple[set[str], list[InspectionGapOut], dict[str, Any]]:
        counts = self.repository.source_table_counts()
        required_tables = (
            "decision_t_relay_day1_candidate_v1",
            "decision_t_relay_day2_watch_snapshot_v1",
            "decision_t_relay_day2_entry_trigger_v1",
            "decision_t_relay_post_entry_monitor_v1",
            "decision_t_relay_day3_exit_decision_v1",
            "decision_t_relay_outcome_label_v1",
            "decision_t_relay_game_hypothesis_snapshot_v1",
            "research_t_relay_research_sample_v1",
        )
        missing = [key for key in required_tables if key not in counts]
        evidence = {
            "table_counts": {key: counts.get(key) for key in required_tables},
            "missing_table_keys": missing,
            "presence_policy": "tables must exist; row counts may be zero before first dispatch",
        }
        if not missing:
            return {"t_board_relay_repository_presence"}, [], evidence
        gap = _domain_gap(
            domain_code="t_board_relay_repository_presence",
            target_table="decision_t_relay.*",
            severity="P0",
            details=evidence,
            remediation_status="t_board_repository_schema_missing",
        )
        return set(), [gap], evidence

    @staticmethod
    def _warning_codes(diagnostics: dict[str, Any]) -> list[str]:
        source_lineage = diagnostics.get("source_lineage")
        if not isinstance(source_lineage, dict):
            return []
        duplicate_summary = source_lineage.get("duplicate_summary")
        if not isinstance(duplicate_summary, dict):
            return []
        duplicate_count = int(duplicate_summary.get("duplicate_group_count") or 0)
        if duplicate_count <= 0:
            return []
        return [f"source_lineage_duplicate_observed:{duplicate_count}"]

    def _inspect_runtime_services(self) -> tuple[set[str], list[InspectionGapOut], dict[str, Any]]:
        observed: set[str] = set()
        gaps: list[InspectionGapOut] = []
        required_model_codes = _parse_required_model_codes(
            self.settings.data_inspector_required_model_services
            if self.settings.data_inspector_required_model_services is not None
            else self.settings.required_model_services
        )
        disabled_model_codes = tuple(model_code for model_code in MODEL_CODES if model_code not in required_model_codes)
        evidence: dict[str, Any] = {
            "model_availability_policy": {
                "policy_version": "data_inspector_staged_model_availability_v1",
                "required_model_codes": list(required_model_codes),
                "required_owner_services": [MODEL_SERVICE_BY_CODE[model_code] for model_code in required_model_codes],
                "disabled_model_codes": list(disabled_model_codes),
                "disabled_owner_services": [MODEL_SERVICE_BY_CODE[model_code] for model_code in disabled_model_codes],
                "disabled_status": "disabled_by_policy",
            }
        }
        scheduler = self.client.get_scheduler("/readyz")
        evidence["scheduler_ready"] = self._result_evidence(scheduler)
        if scheduler.ok and isinstance(scheduler.data, dict) and scheduler.data.get("status") == "ready":
            observed.add("scheduler_ready")
        else:
            gaps.append(
                _domain_gap(
                    domain_code="scheduler_ready",
                    target_table="scheduler-service:/readyz",
                    severity="P0",
                    details=evidence["scheduler_ready"],
                    remediation_status="scheduler_not_ready",
                )
            )
        for model_code in MODEL_CODES:
            domain_code = f"{model_code}_model_ready"
            if model_code not in required_model_codes:
                evidence[domain_code] = {
                    "ok": True,
                    "status_code": 0,
                    "data": {
                        "status": "disabled_by_policy",
                        "required": False,
                        "owner_service": MODEL_SERVICE_BY_CODE[model_code],
                    },
                    "error": None,
                }
                observed.add(domain_code)
                continue
            result = self.client.get_model_ready(model_code)
            evidence[domain_code] = self._result_evidence(result)
            if result.ok and isinstance(result.data, dict) and result.data.get("status") in {"ready", "ok"}:
                observed.add(domain_code)
            else:
                gaps.append(
                    _domain_gap(
                        domain_code=domain_code,
                        target_table=f"{model_code}:/readyz",
                        severity="P0",
                        details={**evidence[domain_code], "owner_service": MODEL_SERVICE_BY_CODE[model_code]},
                        remediation_status="model_not_ready",
                    )
                )
        return observed, gaps, evidence

    @staticmethod
    def _result_evidence(result: ServiceResult, *, sample_limit: int = 3) -> dict[str, Any]:
        data = result.data
        if isinstance(data, list):
            compact_data: Any = {"count": len(data), "sample": data[:sample_limit]}
        else:
            compact_data = data
        return {
            "ok": result.ok,
            "status_code": result.status_code,
            "data": compact_data,
            "error": result.error,
        }
