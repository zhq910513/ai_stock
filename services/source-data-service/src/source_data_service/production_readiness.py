from __future__ import annotations

from datetime import datetime, timezone

from source_data_service import __version__
from source_data_service.fetch_orchestrator import queue_persistence_status, queue_summary
from source_data_service.models import ProductionReadinessCheck, ProductionReadinessReport
from source_data_service.operational_governance import (
    list_freshness_sla,
    list_model_requirements,
    list_storage_policies,
)
from source_data_service.provider_registry import list_api_specs, list_field_contracts, list_source_requirements
from source_data_service.probe import real_probe_evidence_summary
from source_data_service.source_build import build_probe_matrix, build_readiness_matrix, build_repair_routes
from source_data_service.source_repository import repository_status


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _check(check_code: str, passed: bool, *, evidence: dict, action: str | None = None, required: bool = True, warning: bool = False) -> ProductionReadinessCheck:
    status = "passed" if passed else ("warning" if warning else "blocked")
    return ProductionReadinessCheck(
        check_code=check_code,
        status=status,  # type: ignore[arg-type]
        required_for拍板=required,
        evidence=evidence,
        operator_action=action,
    )


def build_production_readiness_report(*, require_postgres: bool = True, require_real_provider_probe: bool = False) -> ProductionReadinessReport:
    """Build the source-data-service production readiness gate.

    This gate is stricter than /readyz. /readyz only means the API process can
    serve contracts. This report answers whether the data-source chain can be
    locked as a production candidate: durable queue, durable repository,
    source contracts, repair routes, model coverage, freshness SLA, storage
    policy and provider probe matrix must all be present.
    """

    checks: list[ProductionReadinessCheck] = []
    queue = queue_persistence_status()
    repo = repository_status()
    specs = list_api_specs()
    requirements = list_source_requirements()
    contracts = list_field_contracts()
    readiness = build_readiness_matrix()
    repairs = build_repair_routes()
    probe_matrix = build_probe_matrix()
    freshness = list_freshness_sla()
    storage = list_storage_policies()
    model_reqs = list_model_requirements()
    queues = queue_summary()
    p0_p1_missing_backup = [
        f"{r.source_table_name}.{r.canonical_field_name}"
        for r in requirements
        if r.required_level.value in {"P0", "P1"} and not r.backup_provider and not r.allows_missing_backup()
    ]
    p0_p1_allowed_no_backup = [
        f"{r.source_table_name}.{r.canonical_field_name}"
        for r in requirements
        if r.required_level.value in {"P0", "P1"} and not r.backup_provider and r.allows_missing_backup()
    ]

    checks.append(
        _check(
            "provider_api_registry_loaded",
            len(specs) >= 20,
            evidence={"registered_api_count": len(specs)},
            action="provider_api_registry_v1 至少要覆盖 P0/P1 免费源、已有 EastMoney/Tencent/Sina/CNINFO 接口登记。",
        )
    )
    checks.append(
        _check(
            "source_field_contracts_loaded",
            len(contracts) >= 20 and any(c.required_level.value == "P0" for c in contracts),
            evidence={"field_contract_count": len(contracts), "p0_contract_count": sum(1 for c in contracts if c.required_level.value == "P0")},
            action="补齐 source_field_contract_v1：每个模型字段必须有字段口径、时间语义、主备源和质量规则。",
        )
    )
    checks.append(
        _check(
            "source_requirements_loaded",
            len(requirements) >= 20 and not p0_p1_missing_backup,
            evidence={
                "source_requirement_count": len(requirements),
                "p0_p1_missing_backup": p0_p1_missing_backup,
                "p0_p1_allowed_no_backup": p0_p1_allowed_no_backup,
            },
            action="P0/P1 source 字段必须有 backup provider；仅 ths.paid_limit_up_probability 允许无备源，失效时阻断或在下一交易日 09:00 后放弃批次。",
        )
    )
    checks.append(
        _check(
            "readiness_matrix_not_blocked",
            all(row.readiness_status != "blocked" for row in readiness.rows),
            evidence={"table_count": readiness.table_count, "blocked_tables": [row.source_table_name for row in readiness.rows if row.readiness_status == "blocked"]},
            action="修复 readiness_matrix 中 blocked 的 source 表字段合同或备源。",
        )
    )
    checks.append(
        _check(
            "repair_routes_available",
            repairs.route_count >= 20,
            evidence={"repair_route_count": repairs.route_count},
            action="数据巡检发现缺口后必须能反查 provider/api/raw_table/request_params。",
        )
    )
    checks.append(
        _check(
            "probe_matrix_available",
            probe_matrix.api_count >= 20,
            evidence={"probe_api_count": probe_matrix.api_count, "real_probe_required_count": sum(1 for r in probe_matrix.rows if r.real_probe_required)},
            action="上线前必须按 /source/probe/matrix 逐项完成真实 provider probe。",
        )
    )
    checks.append(
        _check(
            "durable_queue_ready",
            queue.backend == "postgres" and queue.ready_for_production_queue if require_postgres else True,
            evidence=queue.model_dump(mode="json"),
            action="生产环境必须设置 SOURCE_DATA_QUEUE_BACKEND=postgres、SOURCE_DATA_DATABASE_URL/AI_STOCK_DATABASE_URL，并确认 psycopg 可用。",
        )
    )
    checks.append(
        _check(
            "durable_raw_source_repository_ready",
            repo.backend == "postgres" and repo.ready_for_production_raw_store if require_postgres else True,
            evidence=repo.model_dump(mode="json"),
            action="生产环境 raw/source/lineage 写入必须走 Postgres，memory 只允许单元测试。",
        )
    )
    checks.append(
        _check(
            "queue_summary_accessible",
            len(queues.rows) >= 5,
            evidence={"queue_count": len(queues.rows), "queued_jobs": sum(r.queued_count for r in queues.rows), "leased_jobs": sum(r.leased_count for r in queues.rows)},
            action="队列状态必须可观测，生产-消费任务不能黑盒运行。",
        )
    )
    checks.append(
        _check(
            "freshness_sla_loaded",
            len(freshness) >= 3,
            evidence={"freshness_sla_count": len(freshness), "release_gate_required_count": sum(1 for r in freshness if r.required_for_release_gate)},
            action="P0/P1 字段必须有 expected/latest acceptable time 与 late_policy。",
        )
    )
    checks.append(
        _check(
            "storage_policy_loaded",
            len(storage) >= 3,
            evidence={"storage_policy_count": len(storage), "archive_enabled_count": sum(1 for r in storage if r.archive_enabled)},
            action="大数据量 raw/source/lineage 必须声明分区、索引、冷热归档和十年规模。",
        )
    )
    checks.append(
        _check(
            "model_source_requirements_loaded",
            len(model_reqs) >= 6,
            evidence={"model_requirement_count": len(model_reqs), "model_phase_count": len({(r.model_code, r.model_phase) for r in model_reqs})},
            action="三大模型每个 release/scan/observation 阶段都必须有 source 覆盖度合同。",
        )
    )
    required_real_probe_keys = [
        (row.provider.value, row.api_name)
        for row in probe_matrix.rows
        if row.real_probe_required
    ]
    real_probe_evidence = real_probe_evidence_summary(required_real_probe_keys)
    checks.append(
        _check(
            "real_provider_probe_evidence",
            real_probe_evidence["all_required_probes_usable"] if require_real_provider_probe else False,
            evidence={"required": require_real_provider_probe, **real_probe_evidence},
            action="执行 scripts/source_data_acceptance.py --real-provider-probe 并固化结果。",
            required=require_real_provider_probe,
            warning=not require_real_provider_probe,
        )
    )

    blocking = [c for c in checks if c.required_for拍板 and c.status == "blocked"]
    warnings = [c for c in checks if c.status == "warning"]
    return ProductionReadinessReport(
        version_label=f"source_data_service_ds7_production_readiness_candidate/{__version__}",
        can拍板=not blocking,
        status="passed" if not blocking else "blocked",
        checked_at=utcnow(),
        checks=checks,
        blocking_reasons=[f"{c.check_code}: {c.operator_action}" for c in blocking],
        warning_reasons=[f"{c.check_code}: {c.operator_action}" for c in warnings],
    )
