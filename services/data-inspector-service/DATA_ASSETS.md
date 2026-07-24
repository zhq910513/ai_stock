# data-inspector-service DATA_ASSETS

## 2026-06-18 Research Payload Assembly 数据资产

本服务新增 `research_payload_assembly` 只读巡检 scope，负责把 `research-service` payload 组装阻断纳入 `decision.data_inspection_*` 审计。该 scope 独立运行，不自动并入 `core_closure` 或 scheduler ready 守卫。

| 读取资产 | 用途 | 边界 |
|---|---|---|
| `scheduler-service /scheduler/model-payload/requirements` | 获取 24 个模型 owner task 的 payload 合同、owner、official_publish 和 task_kind | 只读 GET |
| `scheduler-service /scheduler/model-payload/assemble-preflight` | 逐 task 调用 research assembler 并执行 scheduler preflight | 只读 POST；`persist_audit=false`；不触达 owner endpoint |
| `research_model_payload_assembler_v1` 返回字段 | 读取 `payload_assembly_status`、`source_refs`、`source_preflight`、`gap_codes` | 通过 scheduler response 只读观察 |
| `decision.data_inspection_*` | 保存巡检 run、subject、gap、remediation task | 仅写 data-inspector 审计事实 |

| 新增 domain | 严重度 | 写入 gap 条件 | remediation |
|---|---|---|---|
| `research_payload_assembly` | official task 为 P0；non-official task 为 P1 且 `blocks_scoring=true` | requirements 不可用、assemble-preflight 非 2xx、`blocked_data_gap`、`source_gap:*`、`scheduler_preflight.valid=false`、`dispatch_allowed=false` | `diagnose_research_payload_assembly`；若含 source gap 或 source preflight blocking reason，则建议 `repair_research_payload_source_gap` 且 owner 为 `source-data-service` |

禁止事项：

- 不直接读取 `raw_*` 或 provider 原始响应。
- 不调用 hot/memory/ambush/t_relay owner endpoint。
- 不把 `blocked_data_gap`、late/stale/missing 或 sample marker 改写为可派发。
- 不把 `dispatch_allowed=true` 解释为 owner 已执行或 official signal 已发布。

2026-06-18 运行态验收资产记录：

| 对象 | 验收结果 |
|---|---|
| 发布边界 | 仅重建/重启 `data-inspector-service --no-deps`；`source-data-service`、`scheduler-service`、`research-service` 未重启 |
| 容器状态 | `data-inspector-service=0995dca891f7 healthy`；`source-data-service=cc2b01689dc5 healthy`；`scheduler-service=d6e0ee0e72a5 healthy`；`research-service=fca2b9b1a97d healthy` |
| domain contract | `GET /inspection-domain-contracts` 返回 `research_payload_assembly` |
| no-persist probe | `task_count=24`；`assembled_count=3`；`blocked_count=21`；不写 research audit，不触达 owner endpoint |
| persisted run | `run_id=2095`；`status=blocked`；`gap_count=21`；`p0_gap_count=3`；`p1_gap_count=18` |
| gap evidence | gap details 仅保存 scheduler response 审计摘要、preflight 原因、gap/source refs 样本和 preview 存在性，不持久化完整模型 payload |
| source queue | 全队列 `queued_count=0`、`leased_count=0`、`dead_letter_count=0` |

run `2095` 是 research payload 组装缺口审计，不是 `core_closure` 守卫。该 run 的 P0/P1 gap 不得被包装为 ready；后续修复必须继续通过 source-data-service、research-service 或对应 owner 事实链完成，data-inspector 只保留审计和 remediation 建议。

本文件是 `data-inspector-service` 的数据资产账本，不替代本目录 `README.md`。

## 服务定位

`data-inspector-service` 只读 source、preflight、lineage、scheduler ready 和模型 owner ready，写入巡检审计事实。它不修 source、不读 raw 作为模型事实、不调用 provider、不修改模型分数、release gate、买点、outcome 或调度计划。

## 读取数据

| 资产 | 用途 | 边界 |
|---|---|---|
| `GET /source/ops/production-readiness` | source 生产门禁 | 只读 |
| `GET /source/fetch/queues/summary` | 队列 dead-letter 阻断与采集进度审计 | 只读；`dead_letter_count` 阻断 startup/core，`queued_count`/`leased_count`/`failed_count` 保留为待处理、处理中和失败审计，不直接等同服务不可用 |
| `GET /source/contracts` | source 字段合同可见性 | 只读 |
| `POST /source/release/preflight` | 三模型 official 和模型四 Day1/Day2 preflight | 只读请求，不发布信号 |
| `source.*` 标准事实表 | source 行存在性、覆盖度、质量状态 | 只读 |
| `governance.source_lineage_v1` | lineage presence 和 duplicate audit | 只读，不删除重复审计 |
| `decision_t_relay.*`、`research_t_relay.*` | 模型四 repository presence | 只读 |
| required 模型 owner `/readyz`、scheduler `/readyz` | core_closure 健康 | 模型 owner 范围由 `DATA_INSPECTOR_REQUIRED_MODEL_SERVICES` 控制；disabled owner 只写 `disabled_by_policy` 审计，不打 DNS。 |
| `DATA_INSPECTOR_REQUIRED_MODEL_SERVICES` | 分阶段模型 owner ready 硬依赖策略 | 代码默认 `all`；当前逐个模型校验 Compose 默认 `none`。disabled 模型记录为 `disabled_by_policy`，计入观测域但不打 owner DNS、不生成 P0 gap。 |

## 写入数据

| 表 | 作用 |
|---|---|
| `decision.data_inspection_domain_contract` | 巡检域合同 |
| `decision.data_inspection_run` | 巡检运行 |
| `decision.data_inspection_subject` | 巡检对象 |
| `decision.data_inspection_gap` | 缺口审计 |
| `decision.data_inspection_remediation_task` | 修复建议，真实补采仍由 source-data-service 执行 |

## 调度频率

- `startup_guard`：scheduler 启动和 ready 前触发。
- `core_closure`：重启、部署、补跑、验收和拍板前后触发。
- `DATA_INSPECTOR_REQUIRED_MODEL_SERVICES=none` 时，`core_closure` 仍检查 source foundation、source release preflight、lineage、scheduler ready 和模型四 repository presence；只跳过暂停模型 owner `/readyz`，并保留 `disabled_by_policy` 审计。
- `source_release_gate`：official release 前或巡检批次触发。
- `lineage duplicate audit`：随 source_lineage 巡检执行，warning 不阻断。

## 性能关注

主要读路径依赖 `source.*`、`governance.source_lineage_v1`、`governance.raw_fetch_*` 和 `decision.data_inspection_*` 索引。`0025_source_data_foundation_indexes_v1.sql` 已覆盖 source lineage duplicate audit 和 source foundation 常用读取。

## 禁止事项

- 不直接调用 provider。
- 不修复 source/raw/governance 事实。
- 不删除 lineage duplicate。
- 不把 P0/P1 缺口包装成 ready。

## 2026-06-17 冻结记录

本轮数据源闭环后，data-inspector 进入冻结候选，确认来源为用户本轮授权“完成闭环后可以拍板冻结”。

| 冻结对象 | 数据资产范围 | 验收证据 | 只读验收 | 解锁条件 |
|---|---|---|---|---|
| `data-inspector-service -> core_closure -> source/model/scheduler gate` | `decision.data_inspection_*`、`source.*` 只读、`governance.source_lineage_v1`、`/source/release/preflight`、required 模型 owner `/readyz`、disabled owner `disabled_by_policy` 审计、scheduler `/readyz` | 历史 run `2085` ready；gap_count=0；p0_gap_count=0；p1_gap_count=0；15 个巡检域全部 observed；当前策略由 `DATA_INSPECTOR_REQUIRED_MODEL_SERVICES` 收窄；2026-07-14 起 source queue health 只以 dead-letter 作为队列 P0 阻断，queued/leased/failed 仅作进度/失败审计 | `POST /inspection-runs`、`GET /inspection-runs/latest`、`GET /inspection-gaps`、runtime policy evidence | 任一 P0/P1 gap、source readiness blocked、queue dead-letter、lineage presence 缺失、required owner not ready、required model policy 变化，或用户明确批准解锁。 |

## 2026-06-18 Post Source/Scheduler Freeze 数据资产复核

本轮复核只读取运行态资产和既有巡检审计，不新增持久化 run，不修改任何 source/model/scheduler 事实。

| 资产 | 读取方式 | 复核结果 | 边界 |
|---|---|---|---|
| data-inspector health | `GET /readyz` | `status=ready`；database `select_1=true` | 只读 |
| domain contract | `GET /inspection-domain-contracts` | 17 个 domain；包含 `research_payload_assembly` | 只读；不得改合同、severity 或 blocking |
| startup guard audit | `GET /inspection-runs/latest?scope=startup_guard&as_of_trading_day=2026-06-12` | run `2093` ready；gap=0；P0/P1=0；warning=`source_lineage_duplicate_observed:9` | 只读；warning 不由 data-inspector 删除或改写 |
| core closure audit | `GET /inspection-runs/latest?scope=core_closure&as_of_trading_day=2026-06-12` | run `2085` ready；gap=0；P0/P1=0；warning=`source_lineage_duplicate_observed:9` | 只读 |
| research payload audit | `GET /inspection-runs/latest?scope=research_payload_assembly&as_of_trading_day=2026-06-12` | run `2095` blocked；gap=21；P0=3；P1=18 | 审计事实必须保留 blocked，不得包装为 ready |
| scheduler health | `GET scheduler-service /readyz` | ready；startup_guard/run `2093` 与 current_closure/run `2085` 被 scheduler 读取 | 只读；data-inspector 不改调度计划 |
| source health and queues | `GET source-data-service /readyz`、`GET /source/fetch/queues/summary` | source ready；6 个队列 queued/leased/dead_letter 全 0 | 只读；补采仍必须走 source-data-service orchestration |

冻结复核对象：`data-inspector-service -> data assets -> post-source-scheduler-freeze evidence`。当前可继续冻结的数据资产边界是 `decision.data_inspection_*` 审计读取、domain contract 可见性、startup/core ready 守卫、research_payload_assembly blocked 审计、scheduler/source ready 和 source queue 空闲观测。解锁条件为新增或修改巡检 domain、修改 research payload assembly 是否纳入 core closure、修改 P0/P1 severity、修改 source/scheduler/owner 合同、startup/core 出现 P0/P1 gap，或用户明确批准。

## 2026-06-26 Scheduler Task-Store Risk Inheritance 数据资产冻结

用户在交付报告后回复“拍板”，确认 data-inspector 对 scheduler task-store 风险的只读继承边界正式冻结。本冻结不让 data-inspector 读取 scheduler SQLite，也不新增对 source、model 或 scheduler 的反写能力。

| 冻结对象 | 数据资产范围 | 验收证据 | 只读验收 | 解锁条件 |
|---|---|---|---|---|
| `data-inspector-service -> core_closure -> scheduler task-store risk inheritance` | `scheduler-service /readyz` 中的 `checks.task_store.source/model`；`decision.data_inspection_*` 巡检审计；`core_closure` 15 域观测；只读 guardrail 与 remediation 建议 | `core_closure` run `2174` ready；P0/P1=0；observed_domain_count=15；scheduler task-store source/model 均 ready 且 `blocking_statuses=[]`、`stale_running_count=0`；source queues queued/leased/dead_letter 全 0；data-inspector tests `10 passed` | `POST /inspection-runs`、`GET /inspection-runs/latest`、`GET /inspection-gaps`、data-inspector `/readyz`、scheduler `/readyz`、source queue summary | scheduler readyz 合同变化、task-store 风险字段变化、core_closure severity/blocking 改动、新增或合并巡检 domain、需要直接读取 scheduler SQLite、或用户明确批准解锁 |
