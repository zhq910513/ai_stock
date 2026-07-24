from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class DomainContract:
    domain_code: str
    business_line: str
    target_table: str
    grain: str
    required_level: str
    default_severity: str
    description: str
    blocks_scoring: bool = False
    blocks_publish: bool = False
    replay_safe: bool = True
    provider_lineage_required: bool = True

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


CONTRACTS: tuple[DomainContract, ...] = (
    DomainContract(
        domain_code="source_production_readiness",
        business_line="startup_guard",
        target_table="source-data-service:/source/ops/production-readiness",
        grain="service",
        required_level="P0",
        default_severity="P0",
        description="数据源生产拍板门禁必须 passed，且 blocking/warning 为空。",
        blocks_scoring=True,
        blocks_publish=True,
        replay_safe=True,
        provider_lineage_required=False,
    ),
    DomainContract(
        domain_code="source_queue_health",
        business_line="startup_guard",
        target_table="source-data-service:/source/fetch/queues/summary",
        grain="queue",
        required_level="P0",
        default_severity="P0",
        description="source fetch 持久化队列不得存在 dead-letter 终态阻断任务；queued/leased/failed 作为采集进度和失败审计展示，不等同服务不可用。",
        blocks_scoring=True,
        blocks_publish=True,
        replay_safe=True,
        provider_lineage_required=False,
    ),
    DomainContract(
        domain_code="source_contract_visibility",
        business_line="startup_guard",
        target_table="source-data-service:/source/contracts",
        grain="contract",
        required_level="P0",
        default_severity="P0",
        description="source 字段合同必须可见，P0 字段必须具备主备源和质量规则。",
        blocks_scoring=True,
        blocks_publish=True,
        replay_safe=True,
        provider_lineage_required=False,
    ),
    DomainContract(
        domain_code="hot_candidates_release_preflight",
        business_line="source_release_gate",
        target_table="source-data-service:/source/release/preflight",
        grain="model_phase",
        required_level="P0",
        default_severity="P0",
        description="hot_candidates preopen_release_gate 必须通过 source 覆盖度和 freshness 预检。",
        blocks_scoring=True,
        blocks_publish=True,
    ),
    DomainContract(
        domain_code="candidate_memory_release_preflight",
        business_line="source_release_gate",
        target_table="source-data-service:/source/release/preflight",
        grain="model_phase",
        required_level="P0",
        default_severity="P0",
        description="candidate_memory outcome_label 必须通过 source 覆盖度和 freshness 预检。",
        blocks_scoring=True,
        blocks_publish=True,
    ),
    DomainContract(
        domain_code="ambush_watchlist_release_preflight",
        business_line="source_release_gate",
        target_table="source-data-service:/source/release/preflight",
        grain="model_phase",
        required_level="P0",
        default_severity="P0",
        description="ambush_watchlist release_gate 必须通过 source 覆盖度和 freshness 预检。",
        blocks_scoring=True,
        blocks_publish=True,
    ),
    DomainContract(
        domain_code="t_board_relay_day1_preflight",
        business_line="source_release_gate",
        target_table="source-data-service:/source/release/preflight",
        grain="model_phase",
        required_level="P0",
        default_severity="P0",
        description="t_board_relay day1_scan 必须通过 source 覆盖度和 freshness 预检，样本使用模型四真实闭环标的。",
        blocks_scoring=True,
        blocks_publish=True,
    ),
    DomainContract(
        domain_code="t_board_relay_day2_preflight",
        business_line="source_release_gate",
        target_table="source-data-service:/source/release/preflight",
        grain="model_phase",
        required_level="P0",
        default_severity="P0",
        description="t_board_relay day2_trigger 必须通过 source 覆盖度和 freshness 预检，缺盘口或逐笔事实必须阻断。",
        blocks_scoring=True,
        blocks_publish=True,
    ),
    DomainContract(
        domain_code="source_lineage_presence",
        business_line="source_lineage",
        target_table="governance.source_lineage_v1",
        grain="source_row",
        required_level="P0",
        default_severity="P0",
        description="参与 release gate 的 source 行必须能追溯到 raw/provider/API/字段血缘。",
        blocks_scoring=True,
        blocks_publish=True,
    ),
    DomainContract(
        domain_code="t_board_relay_repository_presence",
        business_line="model_four_repository",
        target_table="decision_t_relay.*",
        grain="model_repository",
        required_level="P0",
        default_severity="P0",
        description="模型四生产 schema 和 repository 表必须存在，owner POST 结果才能 append-only 落库。",
        blocks_scoring=True,
        blocks_publish=True,
        provider_lineage_required=False,
    ),
    DomainContract(
        domain_code="model_decision_review",
        business_line="model_decision_review",
        target_table="decision_hot/decision_memory/decision_ambush",
        grain="model_output",
        required_level="P1",
        default_severity="P1",
        description="模型输出异常、缺口码和 row_failed warning 必须可被巡检读取并保留审计。",
        blocks_scoring=False,
        blocks_publish=False,
        provider_lineage_required=False,
    ),
    DomainContract(
        domain_code="research_payload_assembly",
        business_line="research_payload_assembly",
        target_table="scheduler-service:/scheduler/model-payload/assemble-preflight",
        grain="scheduler_task",
        required_level="P0",
        default_severity="P0",
        description="research-service payload assembly must be inspectable through scheduler assemble-preflight; blocked_data_gap must remain gap-coded.",
        blocks_scoring=True,
        blocks_publish=True,
        provider_lineage_required=False,
    ),
    DomainContract(
        domain_code="scheduler_ready",
        business_line="runtime_services",
        target_table="scheduler-service:/readyz",
        grain="service",
        required_level="P0",
        default_severity="P0",
        description="调度服务后台循环和 current_closure 守卫必须 ready。",
        blocks_scoring=True,
        blocks_publish=True,
        provider_lineage_required=False,
    ),
    DomainContract(
        domain_code="hot_candidates_model_ready",
        business_line="runtime_services",
        target_table="hot-candidates-service:/readyz",
        grain="service",
        required_level="P0",
        default_severity="P0",
        description="热点候选模型 owner service 必须 ready。",
        blocks_scoring=True,
        blocks_publish=True,
        provider_lineage_required=False,
    ),
    DomainContract(
        domain_code="candidate_memory_model_ready",
        business_line="runtime_services",
        target_table="candidate-memory-service:/readyz",
        grain="service",
        required_level="P0",
        default_severity="P0",
        description="候选记忆模型 owner service 必须 ready。",
        blocks_scoring=True,
        blocks_publish=True,
        provider_lineage_required=False,
    ),
    DomainContract(
        domain_code="ambush_watchlist_model_ready",
        business_line="runtime_services",
        target_table="ambush-watchlist-service:/readyz",
        grain="service",
        required_level="P0",
        default_severity="P0",
        description="潜伏抬头模型 owner service 必须 ready。",
        blocks_scoring=True,
        blocks_publish=True,
        provider_lineage_required=False,
    ),
    DomainContract(
        domain_code="t_board_relay_model_ready",
        business_line="runtime_services",
        target_table="t-board-relay-service:/readyz",
        grain="service",
        required_level="P0",
        default_severity="P0",
        description="T 字板接力模型 owner service 必须 ready。",
        blocks_scoring=True,
        blocks_publish=True,
        provider_lineage_required=False,
    ),
)


def all_contracts() -> list[DomainContract]:
    return list(CONTRACTS)


def contracts_for_scope(scope: str) -> list[DomainContract]:
    if scope in {"startup_guard", "core_closure"}:
        business_lines = {"startup_guard", "source_release_gate", "source_lineage"}
        if scope == "core_closure":
            business_lines.update({"runtime_services", "model_four_repository"})
    elif scope == "source_release_gate":
        business_lines = {"source_release_gate", "source_lineage"}
    elif scope == "model_t_board_relay_decision_review":
        business_lines = {"model_decision_review", "source_release_gate", "source_lineage", "model_four_repository"}
    elif scope in {"model_hot_decision_review", "model_memory_decision_review", "model_ambush_decision_review"}:
        business_lines = {"model_decision_review", "source_release_gate", "source_lineage"}
    elif scope == "research_payload_assembly":
        business_lines = {"research_payload_assembly"}
    else:
        business_lines = {"startup_guard", "source_release_gate"}
    return [contract for contract in CONTRACTS if contract.business_line in business_lines]
