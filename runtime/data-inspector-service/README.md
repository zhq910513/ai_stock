<!-- macp-migrated: copy-only 2026-09-02 -->

# MACP 迁入

状态：migrated_copy
来源：ai_stock_source/services/data-inspector-service
代码与对照源一致，未改业务逻辑。未切换运行容器到本树。

---

# data-inspector-service

`data-inspector-service` 是当前闭环的数据巡检与缺口审计服务。它按新数据源、三模型和调度合同重新设计，不再沿用旧代码中的 `market.*` 直连巡检口径。旧仓库 `D:\projects\ai_stock_old\services\data-inspector-service` 只作为 API 形态、缺口语义和只读 guardrail 的参考，当前事实以本目录代码和本 README 为准。

本服务数据资产账本见 `services/data-inspector-service/DATA_ASSETS.md`，记录只读 source/preflight/lineage 依赖、巡检审计表和禁止反写边界。

## 边界

本服务只读 source、模型和调度事实，生成 inspection run、subject、gap 和 remediation task。它不得直接调用 BaoStock、AKShare、Tencent、Tushare、EastMoney、Baidu、CNINFO 等 provider，不得直接读取 raw 表作为模型事实，不得修改 source 事实、模型分数、release gate、买点、outcome、标签、调度计划、交易或学习权重。

数据补采建议只能生成 remediation task；真实补采必须由 `source-data-service` 的 fetch orchestration 执行：`/source/fetch/plan` -> `/source/fetch/submit` -> worker -> raw -> quality -> source -> lineage。

## 数据入口

- `source-data-service`
  - `GET /source/ops/production-readiness?require_postgres=true&require_real_provider_probe=true`
  - `GET /source/fetch/queues/summary`
  - `GET /source/contracts`
  - `POST /source/release/preflight`
- Postgres
  - `source.*` 标准事实表计数
  - `governance.source_lineage_v1`
  - `decision.data_inspection_*`
- `scheduler-service`
  - `GET /readyz`，仅 `core_closure` 巡检调用
- 三模型 owner service 与模型四 owner service
  - `GET /readyz`，仅 `core_closure` 巡检调用
- 模型四 repository
  - `decision_t_relay.*`
  - `research_t_relay.*`

## 巡检范围

### startup_guard

供 scheduler 默认 `current_closure` 和 legacy 启动守卫调用。该 scope 只检查 source 底座，不调用 scheduler 或三模型，避免启动循环依赖：

1. source production readiness passed 且无 blocking/warning。
2. source fetch 队列无 dead-letter 终态阻断任务；queued/leased 表示待处理和处理中进度，failed 表示 provider/job 审计，均不直接等同服务不可用。
3. source 字段合同可见。
4. `source.adjusted_daily_bar_v1` 与 `governance.source_lineage_v1` 有真实持久化行。
5. 五条 source release preflight passed：`hot_candidates/preopen_release_gate`、`candidate_memory/outcome_label`、`ambush_watchlist/release_gate`、`t_board_relay/day1_scan`、`t_board_relay/day2_trigger`。模型四 preflight 使用 `t_board_default_symbol`，默认 `000759.SZ`。

### source_release_gate

审计三模型 official release 前的 source 预检、模型四 Day1/Day2 source 预检与 release 所需 lineage presence。任一 preflight 返回 `can_release_official_signal=false`、coverage/freshness blocked、blocking_reasons 非空，或 `source.adjusted_daily_bar_v1` / `governance.source_lineage_v1` 无持久化行时，生成 P0 gap 和 source repair remediation task。

### core_closure

完整闭环巡检，覆盖 startup/source_release_gate/source_lineage，并额外检查：

1. `scheduler-service /readyz`。
2. `hot-candidates-service /readyz`。
3. `candidate-memory-service /readyz`。
4. `ambush-watchlist-service /readyz`。
5. `t-board-relay-service /readyz`。
6. `decision_t_relay` / `research_t_relay` 模型四 repository 表存在。

当前逐个模型校验阶段支持 `DATA_INSPECTOR_REQUIRED_MODEL_SERVICES` 显式声明哪些模型 owner 是 `core_closure` 硬依赖。代码默认 `all`，保持生产严格口径；当前 Compose 默认 `none`，表示四个模型 owner 被策略性暂停，巡检 evidence 记录为 `disabled_by_policy` 并计入对应 `*_model_ready` 观测域，但不调用 owner `/readyz`、不生成 P0 gap、不把模型输出伪装成成功。后续只校验模型四时可设为 `t_board_relay`，则仅模型四 owner readyz 失败会生成 P0 gap；source foundation、source release preflight、lineage、scheduler ready 和模型四 repository presence 仍按原规则阻断。

### lineage duplicate audit

`source_lineage` 巡检同时检查 `governance.source_lineage_v1` 是否存在同一 `source_table_name/source_pk/canonical_field_name/provider/api/raw_table/raw_id` 重复写入。重复 lineage 属于治理洁净度观察项：写入 `diagnostics.source_lineage.duplicate_summary` 和 `warning_codes=source_lineage_duplicate_observed:*`，不生成 P0 gap、不阻断评分或发布、不删除历史审计行。后续修复必须通过 source build / lineage 写入幂等规则处理，不得由 data-inspector 直接改写 source 或 governance 事实。

## API

- `GET /healthz`
- `GET /readyz`
- `GET /inspection-domain-contracts`
- `POST /inspection-domain-contracts/sync`
- `POST /inspection-runs`
- `GET /inspection-runs/latest`
- `GET /inspection-gaps`
- `GET /ui/data-inspector/latest`

`GET /inspection-runs/latest` 支持按 `scope` 和 `as_of_trading_day=YYYY-MM-DD` 查询指定交易日内最新持久化巡检。scheduler 默认 `current_closure` 只读取 `SCHEDULER_GUARD_TRADE_DATE` 对应交易日的 `startup_guard/core_closure`，避免其它交易日的巡检结果污染当前启动守卫。

`GET /ui/data-inspector/latest` 同样支持 `scope` 和 `as_of_trading_day`，用于前端只读展示某个巡检范围、某个交易日的最新状态；该接口只返回巡检摘要，不修改 source、模型或调度事实。

`POST /inspection-runs` 请求体：

```json
{
  "scope": "startup_guard",
  "as_of_trading_day": "2026-06-12",
  "as_of_time": "2026-06-14T10:00:00Z",
  "lookback_days": 20,
  "max_subjects": 100,
  "symbols": ["000063.SZ"],
  "persist": true
}
```

## 状态流转

```text
request
-> source foundation checks
-> source release preflight checks
-> source lineage checks
-> t-board relay repository presence checks
-> optional scheduler/model ready checks
-> run status ready/degraded/blocked
-> optional Postgres audit write
```

状态规则：

- `ready`：P0/P1 blocking gap 为 0。
- `blocked`：任一 P0 gap、`blocks_scoring=true` 或 `blocks_publish=true`。
- `degraded`：仅 P1 非发布阻断 gap。
- `warning`：仅 P2/INFO 非阻断发现。

## 数据产出与落库

持久化表沿用当前基线：

- `decision.data_inspection_domain_contract`
- `decision.data_inspection_run`
- `decision.data_inspection_subject`
- `decision.data_inspection_gap`
- `decision.data_inspection_remediation_task`

当前服务写入的是审计事实，不写入 source、raw、模型事实、买点、outcome 或 scheduler 计划。

## 缺口码

当前新合同域：

- `source_production_readiness`
- `source_queue_health`
- `source_contract_visibility`
- `source_lineage_presence`
- `source_lineage_duplicate_observed:*`（非阻断 warning code，仅用于 lineage 治理观察）
- `hot_candidates_release_preflight`
- `candidate_memory_release_preflight`
- `ambush_watchlist_release_preflight`
- `t_board_relay_day1_preflight`
- `t_board_relay_day2_preflight`
- `t_board_relay_repository_presence`
- `scheduler_ready`
- `hot_candidates_model_ready`
- `candidate_memory_model_ready`
- `ambush_watchlist_model_ready`
- `t_board_relay_model_ready`

缺口必须保留原始 evidence、blocking_reasons、degraded_reasons、repair_actions、HTTP status 和 error。禁止用 0、空字符串、mock 或 GPT 推断补事实。

## 调度关系

`scheduler-service` 默认 `current_closure` 必须先检查 `data-inspector-service /readyz`，用 `SCHEDULER_GUARD_TRADE_DATE` 触发本服务 `startup_guard`，再按同一交易日检查最新持久化 `startup_guard/core_closure` 结果、source、三模型、模型四和 release preflight。`startup_guard` 必须返回无 P0/P1 blocking gap 才能让 scheduler ready；`core_closure` blocked 时 scheduler 同样不得包装成 ready。

由于 `core_closure` 自身会检查 `scheduler-service /readyz`，调度服务在判定自身 ready 时只允许一个死锁豁免：最新 `core_closure` 的状态为 `blocked`、P0=1、P1=0，且 `GET /inspection-gaps?run_id=<run_id>&severity=P0` 的唯一缺口码是 `scheduler_ready`。该豁免只存在于 scheduler ready 判定中，data-inspector 仍然保留原始 `scheduler_ready` gap 审计事实；任何 source、模型、preflight、队列、lineage、repository 或其它 P0/P1 缺口都继续阻断。

生产巡检建议：

```text
POST /inspection-runs scope=startup_guard as_of_trading_day=<guard_trade_date> persist=true
POST /inspection-runs scope=core_closure as_of_trading_day=<guard_trade_date> persist=true
```

## Docker

服务端口为 `8025`，启动命令：

```text
uvicorn data_inspector_service.main:app --host 0.0.0.0 --port 8025
```

如 8025 已被旧容器占用，本地验证可以先用其他端口运行新服务；不得因此重启、替换或重建已锁定的 `source-data-service`、`source-data-worker`、三模型服务或 `scheduler-service`。

关键运行变量：

- `DATA_INSPECTOR_REQUIRED_MODEL_SERVICES`：代码默认 `all`；当前逐个模型校验 Compose 默认 `none`。可填 `t_board_relay`、`hot_candidates,candidate_memory` 或 owner service 名。disabled 模型只写 `disabled_by_policy` 审计，不打 owner DNS。
- `REQUIRED_MODEL_SERVICES`：兼容同策略的通用变量；当 `DATA_INSPECTOR_REQUIRED_MODEL_SERVICES` 未设置时读取。

## 验收

当前代码级验证：

```text
PYTHONPATH=services/data-inspector-service/src python -m pytest -q services/data-inspector-service/tests
```

通过标准：

- `startup_guard` 不调用 scheduler 或三模型。
- `core_closure` 覆盖 source、lineage、scheduler ready、`DATA_INSPECTOR_REQUIRED_MODEL_SERVICES` 声明的 required 模型 ready、disabled 模型 `disabled_by_policy` 审计、模型四 repository presence 和五条 source release preflight。
- preflight blocked 必须生成 P0 gap 和 source-data-service remediation task。

## 生产候选锁定

2026-06-14 已完成本地 Docker / Postgres 真实闭环巡检并经用户拍板锁定：

- `/readyz` 返回 `ready`。
- `startup_guard` 持久化巡检 run `2062`：由 scheduler 默认 `current_closure` 启动后触发，`ready`，P0/P1 gap 均为 0。
- `core_closure` 持久化巡检 run `2063`：`ready`，覆盖 source、lineage、scheduler ready、三模型 ready 和三条 source release preflight，P0/P1 gap 均为 0。
- run `2062/2063` 使用 as_of_trading_day=`2026-06-12`，是在补齐 `000759.SZ` 的 `source.trade_status_v1`、`source.adjusted_daily_bar_v1` 和 `source.stock_moneyflow_daily_v1` 后重新执行并被 scheduler 硬门禁读取的真实巡检。
- `GET /inspection-gaps?run_id=2063` 返回空数组。
- `warning_codes` 中 `source_lineage_duplicate_observed:9` 是 lineage duplicate audit 的非阻断治理观察项，不生成 P0/P1 gap，不阻断 scoring / publish，不允许由 data-inspector 直接删除或改写历史 lineage。
- `services/data-inspector-service/tests` 单测通过：`5 passed`。

2026-06-15 本服务被定向解锁扩展模型四闭环：新增 `t_board_relay_day1_preflight`、`t_board_relay_day2_preflight`、`t_board_relay_repository_presence`、`t_board_relay_model_ready`。模型四 preflight 使用 `000759.SZ / 2026-06-12` 真实 source 标准层样本；core_closure 必须能看到模型四 owner ready 和 `decision_t_relay` / `research_t_relay` 表存在。锁定后，除非用户明确批准 `data-inspector-service` 解锁或定向修复，不得修改本服务代码、Docker 启动配置、API 合同、scope、domain contract、缺口码、severity / blocking 判断、remediation task 生成、只读 guardrail、调度健康依赖、持久化写入合同，或会改变本服务运行事实的测试和 schema。

2026-06-17 首次上线重建后复核并刷新冻结证据：

- `POST /inspection-runs scope=core_closure as_of_trading_day=2026-06-12 persist=true` 生成 run `2085`。
- run `2085` 返回 `status=ready`、`gap_count=0`、`p0_gap_count=0`、`p1_gap_count=0`。
- run `2085` 覆盖 15 个域：source production readiness、source contract visibility、source queue health、source lineage presence、scheduler ready、三模型 ready、三模型 release preflight、模型四 ready、模型四 repository presence、模型四 Day1/Day2 preflight。
- `warning_codes=["source_lineage_duplicate_observed:9"]` 仍为 lineage duplicate audit 的非阻断治理观察项，不生成 P0/P1 gap，不允许 data-inspector 删除或改写历史 lineage。
- `scheduler-service /readyz` 已读取最新 `core_closure` run `2085` 并保持 `ready`。

冻结对象：

| 服务 -> 模块 -> 功能 | 冻结时间 | 确认来源 | 锁定范围 | 允许的只读验收 | 禁止修改项 | 解锁条件 | 回滚方式 | 验证清单 |
|---|---|---|---|---|---|---|---|---|
| `data-inspector-service -> core_closure -> source/model/scheduler gate` | 2026-06-17 16:08 Asia/Shanghai | 用户本轮确认按任务书执行并授权完成闭环后拍板冻结 | `core_closure` 15 域合同、source readiness、queue、lineage、release preflight、scheduler ready、四模型 ready、模型四 repository presence | `POST /inspection-runs` 只读巡检、`GET /inspection-runs/latest`、`GET /inspection-gaps`、Postgres 审计查询 | 未获解锁不得改 scope、domain contract、缺口码、severity/blocking、remediation task、只读 guardrail 或调度 ready 依赖 | run blocked、P0/P1 gap、source/preflight/queue/lineage/model ready 阻断，或用户明确批准 | 回退 data-inspector 镜像和环境变量；保留 decision.data_inspection_* 审计 | run `2085` ready；gap_count=0；P0/P1=0；scheduler `/readyz` 引用 run `2085` |

允许继续执行只读健康检查、`POST /inspection-runs` 巡检观察、`GET /inspection-runs/latest`、`GET /inspection-gaps`、Postgres 审计查询和文档事实核对。发现 P0/P1 阻断、readyz 失败、preflight 阻断、队列 dead-letter、lineage presence 缺失或 owner service 不 ready 时，必须先报告证据、影响范围和建议修复点，再等待用户批准解锁或定向修复。

## 当前闭环结论

本服务已按新数据源、三模型、模型四和调度服务重新设计为 source-first 巡检服务，并已进入核心闭环候选状态。当前实现覆盖 source production readiness、队列、字段合同、source lineage、三模型 release preflight、模型四 Day1/Day2 preflight、scheduler ready、四个模型 owner ready 和模型四 repository presence；source queue health 只把 dead-letter 视为 P0 阻断，queued/leased/failed 作为采集进度和失败审计保留在 diagnostics 中；不会直接采集 provider，不会读取 raw 作为模型输入，不会反写模型或调度事实。后续如扩展买点、outcome、Jarvis 上下文和模型决策回顾，必须先获得用户批准解锁或定向扩展，继续把事实入口限定为 source/preflight/decision 审计表和 owner service 只读接口，并在本 README 覆盖更新。

## Research Payload Assembly 巡检

`research_payload_assembly` 是本服务当前新增的只读巡检 scope，用于审计 `research-service` 真实 payload 组装是否能通过 scheduler 投产预检门禁。该 scope 不属于 `core_closure` 默认 ready 守卫，避免历史 `as_of_time` freshness late 样本直接影响 scheduler ready；需要显式调用：

```text
POST /inspection-runs
{
  "scope": "research_payload_assembly",
  "as_of_trading_day": "2026-06-12",
  "as_of_time": "2026-06-18T00:40:00Z",
  "symbols": ["000063.SZ"],
  "persist": false
}
```

巡检流程：

```text
GET scheduler-service /scheduler/model-payload/requirements
-> for each task POST scheduler-service /scheduler/model-payload/assemble-preflight
-> persist_audit=false
-> inspect payload_assembly_status / scheduler_preflight / dispatch_allowed / gap_codes
-> generate decision.data_inspection_* gap and remediation suggestion only
```

硬规则：

- 该 scope 只调用 scheduler 的 `assemble-preflight` 只读联调入口，不触达模型 owner endpoint。
- `blocked_data_gap`、`source_gap:*`、`source_preflight` late/stale/missing 或 sample marker 必须保留为 gap，不得改写为 ready。
- official release task 阻断记为 P0；non-official task 阻断记为 P1，但仍标记 `blocks_scoring=true`，因为 owner task 缺真实 payload 不能执行。
- remediation task 只给出诊断或 source 修复建议；真实补数仍必须走 `source-data-service` fetch orchestration。
- 该 scope 的 `dispatch_allowed=true` 只代表 preflight preview 通过，不代表 owner service 已被调用，也不代表 official signal 已发布。

新增缺口码 / domain：

```text
research_payload_assembly
```

当 scheduler requirements 不可用、assemble-preflight 非 2xx、`payload_assembly_status!=assembled_research_payload`、`scheduler_preflight.valid=false` 或 `dispatch_allowed=false` 时，本服务生成 `gap_type=research_payload_assembly_blocked`，details 保留 `task_code`、`task_kind`、`owner_service`、`official_publish`、`gap_codes`、`blocking_reasons`、`source_preflight`、scheduler response 和原始 request。

2026-06-18 运行态验收：

- 仅按 `--no-deps` 单服务发布 `data-inspector-service`，最终容器更新为 `0995dca891f7`，状态 `healthy`。
- `source-data-service` 容器仍为 `cc2b01689dc5`，`scheduler-service` 容器仍为 `d6e0ee0e72a5`，`research-service` 容器仍为 `fca2b9b1a97d`。
- `GET /inspection-domain-contracts` 已可见 `research_payload_assembly`。
- `POST /inspection-runs scope=research_payload_assembly persist=false` 返回 `task_count=24`、`assembled_count=3`、`blocked_count=21`。
- `POST /inspection-runs scope=research_payload_assembly persist=true` 写入最终验收 run `2095`，状态 `blocked`，`gap_count=21`，`p0_gap_count=3`，`p1_gap_count=18`。
- 3 个 P0 gap 对应三条 official release task；18 个 P1 gap 对应 non-official owner task，均保留 `blocked_data_gap` 与原始 gap codes。
- gap details 中的 scheduler response 已收窄为审计摘要，只保留状态、gap、source/upstream refs 样本、preflight 原因和 preview 是否存在，不再持久化完整模型 payload。
- 发布后 `data-inspector-service /readyz=ready`，`scheduler-service /readyz=ready`，source fetch queues 的 `queued/leased/dead_letter` 均为 0。

当前 run `2095` 说明 research payload assembly 数据事实尚未全量可派发；该结论不解除 scheduler preflight 冻结，也不表示 owner service 故障。后续修复必须按 gap codes 分流：source 缺口走 source-data-service fetch orchestration，上游 sample/decision 缺口走对应 owner/research 事实链修复。

2026-06-18 冻结记录：

| 冻结对象 | 冻结范围 | 验收证据 | 解锁条件 |
|---|---|---|---|
| `data-inspector-service -> research_payload_assembly -> blocked_data_gap audit` | scheduler requirements 读取、逐 task assemble-preflight、P0/P1 gap 分级、`decision.data_inspection_*` 审计、remediation 建议、紧凑 scheduler response evidence | local tests `8 passed`；`compileall` 通过；最终 run `2095` 为 `blocked` 且 `gap_count=21`、`p0_gap_count=3`、`p1_gap_count=18`；`data-inspector-service /readyz=ready`、`scheduler-service /readyz=ready`、source queues `queued/leased/dead_letter=0` | 新增 payload task、修改 scheduler assemble-preflight 合同、修改 gap 分级规则、把该 scope 纳入 `core_closure`、扩展 owner dispatch、修复 run `2095` 暴露的底层 source/research/owner 缺口，或用户明确批准解锁 |

## 2026-06-18 Post Source/Scheduler Freeze Review

2026-06-18 10:09:33 Asia/Shanghai，用户批准后对 data-inspector-service 做 source/scheduler 冻结后的只读复核。本轮没有代码变更、schema 变更、Docker 变更、镜像重建、服务重启、provider 调用，也没有新建 `persist=true` 巡检 run。

只读证据：

| 检查项 | 当前结果 |
|---|---|
| `GET /readyz` | `status=ready`；database `select_1=true`；source base URL 指向 `source-data-service:8041` |
| `GET /inspection-domain-contracts` | domain_count=17；已包含 `research_payload_assembly`；合同继续声明 `read_only=true`、`direct_provider_calls_allowed=false`、source 修复必须走 source-data-service orchestration |
| latest `startup_guard` | run `2093`；`status=ready`；`gap_count=0`；`p0_gap_count=0`；`p1_gap_count=0`；warning_codes=`source_lineage_duplicate_observed:9` |
| latest `core_closure` | run `2085`；`status=ready`；`gap_count=0`；`p0_gap_count=0`；`p1_gap_count=0`；warning_codes=`source_lineage_duplicate_observed:9` |
| latest `research_payload_assembly` | run `2095`；`status=blocked`；`gap_count=21`；`p0_gap_count=3`；`p1_gap_count=18`；该 scope 是 payload assembly 审计，不属于默认 ready 守卫，不得包装为 ready |
| `scheduler-service /readyz` | `status=ready`；startup_guard 引用 run `2093`；current_closure 引用 core_closure run `2085` |
| `source-data-service /readyz` | `status=ready`；version=`0.1.0-ds7` |
| `GET /source/fetch/queues/summary` | 6 个队列 `queued_count=0`、`leased_count=0`、`dead_letter_count=0` |

冻结复核对象：

| 服务 -> 模块 -> 功能 | 复核时间 | 确认来源 | 当前结论 | 允许的只读验收 | 禁止修改项 | 解锁条件 | 验证清单 |
|---|---|---|---|---|---|---|---|
| `data-inspector-service -> post-source-scheduler-freeze review -> startup/core/research-payload evidence` | 2026-06-18 10:09 Asia/Shanghai | 用户本轮“批准” | source/scheduler 最新冻结后，data-inspector startup_guard 与 core_closure 仍 ready；research_payload_assembly 保持 blocked 审计事实，不影响默认 ready 守卫，也不解除底层 source/research/owner 缺口 | `/readyz`、`/inspection-domain-contracts`、`/inspection-runs/latest`、`/inspection-gaps`、scheduler `/readyz`、source `/readyz`、source queue summary | 未获解锁不得改 scope、domain contract、gap code、severity/blocking、remediation、read-only guardrail；不得修改 source/model/scheduler/release/buy/outcome/learning facts；不得直接调用 provider 或读取 `raw_*` 作为模型事实；不得把 run `2095` P0/P1 gap 包装为 ready | 新增巡检 domain、把 `research_payload_assembly` 纳入 `core_closure`、修改 scheduler assemble-preflight 合同、修改 owner/source 职责、startup/core 出现 P0/P1 gap，或用户明确批准解锁 | data-inspector ready；startup_guard run `2093` ready 且 P0/P1=0；core_closure run `2085` ready 且 P0/P1=0；research_payload_assembly run `2095` blocked 被保留为审计；scheduler/source ready；source queues queued/leased/dead_letter 全 0 |

## 2026-06-26 Scheduler Task-Store Risk Inheritance Freeze

用户在交付报告后回复“拍板”，确认 `data-inspector-service -> core_closure -> scheduler task-store risk inheritance` 正式冻结。本次冻结不新增巡检 scope，不修改 domain contract，不直接读取 scheduler SQLite；data-inspector 继续只读 `scheduler-service /readyz`，由 scheduler 自身暴露 `checks.task_store.source/model` 来承接本地调度账本风险。

冻结对象：

| 服务 -> 模块 -> 功能 | 冻结时间 | 确认来源 | 锁定范围 | 允许的只读验收 | 禁止修改项 | 解锁条件 | 回滚方式 | 验证清单 |
|---|---|---|---|---|---|---|---|---|
| `data-inspector-service -> core_closure -> scheduler task-store risk inheritance` | 2026-06-26 22:43 Asia/Shanghai | 用户明确回复“拍板” | `core_closure` 只读 scheduler `/readyz`；通过 scheduler 暴露的 `checks.task_store.source/model.status`、`blocking_statuses`、`stale_running_count` 继承 `retry_ready/dead_letter/stale_running` 风险；保留只读 guardrail 与 remediation 建议边界 | `POST /inspection-runs scope=core_closure persist=true/false`、`GET /inspection-runs/latest`、`GET /inspection-gaps`、`GET /readyz`、scheduler `/readyz`、source queue summary | 未获解锁不得直接读取 scheduler SQLite，不得新增反写 scheduler/source/model 事实，不得把 scheduler task-store blockers 包装为 ready，不得修改 `core_closure` severity/blocking 语义，不得绕过 source-data-service orchestration 生成补数事实 | scheduler readyz 合同变化、data-inspector core_closure P0/P1 误阻断或漏阻断、新增巡检 domain、需要直接审计 scheduler task store、或用户明确批准解锁 | 回退 data-inspector 镜像和环境变量；保留 `decision.data_inspection_*` 审计；scheduler task-store 仍由 scheduler 自身只读暴露和回滚 | `core_closure` run `2174` ready；P0/P1=0；observed_domain_count=15；guardrails.read_only=true；direct_provider_calls_allowed=false；fetch_repairs_must_use_source_data_service_orchestration=true；data-inspector tests `10 passed` |
