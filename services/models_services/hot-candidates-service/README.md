# hot-candidates-service README

> 唯一模型根目录 MD。已整合当前契约、最终设计和各阶段验证报告。
> 锁定版本：`hot_candidates_service_v1.0_rc`。未经用户明确批准，不得修改模型一业务代码、字段、表结构、公式或发布闸门。


---

# 当前服务契约与 API

# hot-candidates-service refined contract

Port: `8031`  
Legacy model version remains `hot_candidates_v1` for `/score` compatibility. Refined research contract version is `hot_candidates_v2_lifecycle`.

## Refactor objective

This service is no longer only a fixed weighted scoring endpoint. It is the backend entry point for the independent hot model domain `decision_hot.*`.

The refined hot model must support:

1. hot lifecycle recognition: `hot_cycle`.
2. per-day independent decision case: `hot_decision_case`.
3. immutable first decision snapshot.
4. staged scoring: pre-auction, auction-confirmed, open-5m-confirmed, official score.
5. independent release gate; `ready` or a completed score is not an official signal.
6. append-only observation snapshots from the second calculation onward.
7. independent direction/execution/path/environment/data labels.
8. independent failure attribution and evolution samples.
9. no shared business truth table with memory or ambush models.

## API

- `GET /health`, `/healthz`, `/readyz`
- `POST /score`
- `POST /observe`
- `POST /evolution-sample`
- `POST /distortion-report`

`/score` still returns legacy `analysis` and `contract`, but now also returns:

```json
{
  "structured_output": {
    "research_contract": {
      "hot_cycle": {},
      "hot_decision_case": {},
      "teacher_calibration": {},
      "stage_scores": {},
      "release_gate": {},
      "initial_decision_snapshot": {},
      "persistence_plan": {}
    }
  }
}
```

## Data ownership

The service reads model-agnostic `source.*` facts and writes only to `decision_hot.*` through orchestration/persistence code. It must not write to common model result tables keyed only by `model_code`.

Allowed shared layers:

- `source.*` market facts
- `governance.*` lightweight registry/task/quality indexes
- formula library and timestamp/audit conventions

Forbidden shared business tables:

- shared feature matrix
- shared score fact
- shared buy point
- shared monitoring snapshot
- shared outcome label
- shared failure attribution
- shared evolution sample

## Lifecycle stages

- `new_hot_ignition`
- `first_board_confirmation`
- `consecutive_board_continuation`
- `high_board_overheat`
- `board_break_divergence`
- `relimit_after_break`

The same symbol can generate multiple daily `hot_decision_case` records in one `hot_cycle`. A cooled-down later event must open a new `hot_cycle`.

## First decision vs observation

First decision facts are immutable. From the second calculation onward, every run produces append-only observations.

- First decision: `decision_hot.hot_initial_decision_snapshot_v1` equivalent payload inside research contract.
- Continuous observations: `POST /observe` -> `decision_hot.hot_observation_snapshot_v1`.
- Evolution: matured labels + observations -> `POST /evolution-sample` -> `decision_hot.hot_evolution_sample_v1`.

Online observations must never mutate production weights. They only feed offline evaluation and shadow runs.

## Database DDL

See `infra/sql/0002_source_decision_hot_refactor.sql`.


---

# 最终设计说明

# 热点模型 hot_candidates 最终设计说明 v1.0 RC

> 文件位置：`services/models_services/hot-candidates-service/README.md（已合并）`  
> 锁定口径：`hot_candidates_service_v1.0_rc`  
> 对应包：`ai_stock_hot_phase7_production_finalization.zip`  
> 状态：已拍板锁定。除非真实验收暴露问题并经用户明确同意，否则不得修改代码、字段、契约或模型逻辑。

---

## 1. 模型定位

热点模型不是直接交易模型，也不是普通涨停概率模型。它是神策中心中用于识别“外部热度已经显性化后，短窗口内是否可能兑现”的独立研究模型。

它的核心输入是同花顺付费次日概率候选榜提供的教师先验，再结合本地行情、集合竞价、资金、板块、市场环境、可交易性和数据质量，对短窗口机会进行阶段化判断。

一句话定义：

```text
热点模型负责回答：市场已经开始关注这只股票后，它在 T+1 / T+3 / T+5 短窗口内是否具备可验证的方向兑现价值。
```

模型只提供研究信号、评估基准价和后续路径验证，不给出直接交易建议。

---

## 2. 与其他模型的边界

### 2.1 与候选记忆模型的区别

热点模型关注“当前已经被外部热度发现”的股票；候选记忆模型关注“历史热点沉淀后再次上涨前的前置信号”。

热点模型不负责长期二波研究，不负责 TTL 和记忆衰减，也不把后续二次机会计入自身首次成功率。

### 2.2 与潜伏抬头模型的区别

热点模型看到的是“火已经点起来”；潜伏抬头模型看到的是“低位刚出现火苗”。热点模型不做全市场低谷结构扫描。

---

## 3. 业务对象

热点模型独立使用 `decision_hot.*` 域，不与其他模型混用业务事实表。

核心对象：

```text
hot_cycle                  一只股票的一轮热点生命周期
hot_cycle_day_snapshot      热点生命周期内的每日状态
hot_decision_case           某日某批次某候选的独立决策样本
hot_initial_decision_snapshot 首次决策冻结快照
hot_evidence_snapshot       决策时可见证据快照
hot_feature_matrix          阶段特征矩阵
hot_score_fact              阶段评分事实
hot_release_gate_audit      发布闸门审计
hot_signal_fact             正式信号事实
hot_buy_point               买点评估基准价
hot_observation_snapshot    第二次及以后 append-only 观察快照
hot_case_latest_state       当前投影，仅服务调度和读取
hot_outcome_label           成熟结果标签
hot_failure_attribution     失败归因
hot_first_output_distortion_analysis 首次输出失真分析
hot_evolution_sample        模型进化样本
hot_teacher_calibration     教师概率校准
hot_model_version_evaluation 版本评估
```

硬原则：首次决策事实必须冻结；第二次开始的所有计算结果只能 append-only 追加，不能覆盖首次事实。

---

## 4. 热点生命周期

热点模型不能把同一只股票每天的候选都视为互不相关的独立样本。必须先识别热点生命周期：

```text
new_hot_ignition              新热点点火
first_board_confirmation      首板确认
consecutive_board_continuation 连板延续
high_board_overheat           高位过热
board_break_divergence        断板分歧
relimit_after_break           断板后反包 / 回封
cooling                       冷却
closed                        生命周期关闭
```

同一股票同一热点周期内可以产生多个 `hot_decision_case`，但共享同一个 `hot_cycle`。冷却足够久或题材周期变化后，才允许创建新的 `hot_cycle`。

数据库层必须避免并发创建多个 active cycle。生产实现应使用 active cycle 唯一约束和事务锁。

---

## 5. 阶段化评分

热点模型不能只用一个固定总分贯穿所有阶段。它至少需要拆成：

```text
pre_auction_score             盘前 / 竞价前教师先验和本地证据
auction_confirmed_score       集合竞价确认后的短线承接判断
open_5m_confirmed_score       开盘 5 分钟 VWAP / 承接确认
official_hot_score            发布闸门前官方候选评分
```

评分需要生命周期自适应。例如：

```text
new_hot_ignition：更看教师先验、本地题材、空间和初始资金。
first_board_confirmation：更看竞价、封单、开盘承接和可交易性。
consecutive_board_continuation：更看无买入机会风险、过热风险、开板风险。
high_board_overheat：更看假强、追高、回撤和执行风险。
board_break_divergence / relimit_after_break：更看修复确认、资金回流和板块支撑。
```

竞价确认和资金承接必须进入 official score。高教师概率但弱竞价、弱承接时必须降级。

---

## 6. 发布闸门

`ready`、`score passed`、`analysis completed` 都不等于正式信号。正式信号只能由独立 release gate 生成。

发布闸门需要检查：

```text
1. source evidence available_at 合规；
2. 关键 P0 数据不缺失；
3. 生命周期阶段允许发布；
4. 竞价或开盘承接符合当前阶段要求；
5. 过热风险可控；
6. 可交易性达标；
7. 非 ST、非停牌、无退市风险；
8. blocked-but-track 不能进入 official_signal_pool；
9. 缺失关键证据只能进入 research_only 或 calibration_pool。
```

关键证据缺少 `available_at` 时，不得进入正式信号。可以进入研究池，但不能计入官方成功率。

---

## 7. 买点评估

热点模型买点不是交易建议，而是评估基准价。它用于后续路径验证、收益计算和模型校准。

正式基准价只能来自明确阶段：

```text
auction_confirmed      集合竞价阶段确认
open_5m_confirmed      开盘 5 分钟 VWAP 确认
```

`latest_price`、`previous_close` 只能作为诊断参考，不能冻结正式买点。

首次有效评估基准价必须冻结；后续买点版本只能作为诊断和优化样本，不得重算历史收益。

---

## 8. 观察、结果和归因

热点模型必须拆开多个结果维度：

```text
direction_outcome       方向是否兑现
execution_outcome       是否存在可执行机会
path_outcome            路径是否健康
environment_outcome     是否被市场/板块环境压制
data_outcome            是否存在数据质量问题
```

方向成功但执行错过，不应记为模型方向失败。

关键路径指标：

```text
MFE
MAE
first_target_hit_at
first_invalidation_hit_at
first_event_type
time_to_target
time_to_invalidation
relative_market_return
relative_sector_return
```

outcome 必须在成熟条件满足后生成，例如 T+5、T+20、触达目标、跌破失效、结构失效、数据不足归档。pending outcome 不得进入 evolution sample。

---

## 9. 教师概率校准

同花顺概率是教师先验，不是绝对真理。必须按以下维度做校准：

```text
probability bucket
hot lifecycle stage
market regime
sector heat
tradability bucket
sample maturity
```

校准只允许使用：

```text
label_maturity_status = mature
outcome_matured_at <= calibration_cutoff_time
```

校准结果必须版本化：

```text
calibration_version
training_window_start
training_window_end
sample_count
mature_sample_count
brier_score
calibration_error
activated_at
is_active
```

样本不足时不能激活校准版本，只能输出 `sample_insufficient`。

---

## 10. 研究样本池

热点模型必须防止选择偏差，因此除正式信号外，还需要研究池：

```text
official_signal_pool        计入正式成功率
calibration_pool            用于校准
blocked_but_track_pool      被阻断但继续跟踪
teacher_distortion_pool     教师概率失真研究
research_watch_pool         低频观察研究
```

只有 `official_signal_pool` 进入正式成功率。其他池子用于研究和进化，不得混入官方表现。

---

## 11. 调度要求

热点模型对时间边界要求最高。

建议阶段：

```text
09:15-09:25 集合竞价采集
09:25 竞价冻结
09:26-09:30 首次评分和 release gate
09:30-09:36 开盘 VWAP 买点评估
盘中 5 分钟 observation
14:30 尾盘风险检查
15:00 后收盘路径冻结
T+1 / T+5 / T+20 成熟结果
夜间 / 周期性教师校准和版本评估
```

调度系统必须支持数据新鲜度水位线、交易日历、任务租约、重试、死信和幂等。

---

## 12. 数据口径和时间合规

所有证据必须有：

```text
event_time
available_at
captured_at
calculated_at
published_at
```

正式评分只能使用：

```text
available_at <= decision_time
```

任何未来数据、缺少关键可见时间的数据，不得进入 official signal。

---

## 13. 大数据量设计

热点模型后续观察量可能非常大，因此必须有：

```text
hot_active_case_registry       控制观察频率和优先级
hot_case_latest_state          当前投影
hot_observation_snapshot       append-only 历史事实
hot_intraday_feature_snapshot  盘中特征预计算
hot_execution_feature_snapshot 买点执行特征
```

原则：

```text
批量读取 active cases
批量读取 source / feature
批量写 observation
批量更新 latest_state
不逐条 case 反复扫源数据
```

---

## 14. 验收标准

热点模型 v1.0 RC 验收标准：

```text
1. 首次决策快照不可覆盖。
2. 第二次及以后 observation append-only。
3. available_at 缺失不得 official。
4. 弱竞价不能因高教师概率直接放行。
5. latest_price / previous_close 不得冻结正式买点。
6. pending outcome 不得生成 evolution sample。
7. blocked-but-track 不计入正式成功率。
8. teacher calibration 只用 mature label。
9. 同 symbol 并发不得生成多个 active hot_cycle。
10. direction / execution / path / environment / data outcome 分离。
```

---

## 15. 锁定说明

该文档记录的是已拍板的热点模型后端设计口径。后续未经用户明确同意，不得修改模型一代码、字段、表结构、契约和业务逻辑。真实 PostgreSQL、真实 provider、scheduler v2 或多交易日 replay 暴露问题时，应以“验收问题回补”形式提出，待用户确认后处理。


---

# REFACTOR_SUMMARY_HOT_PHASE1

# Hot model phase-1 refactor summary

## Scope completed

This package refactors the first phase around the hot-candidates model. Frontend, Jarvis, research-center UI, memory model, and ambush model were intentionally not modified.

## Architecture changes

1. Introduced model-agnostic `source.*` fact layer DDL.
2. Introduced independent `decision_hot.*` hot model domain DDL.
3. Introduced lightweight `governance.*` registry/task tables.
4. Added hot lifecycle research contract to `/score` without breaking existing legacy response.
5. Added `/observe` for append-only second-and-later calculations.
6. Added `/evolution-sample` for offline model evolution input.
7. Added scheduler-service implementation and hot pipeline plan.
8. Added source fact contract guard in market-data-service.

## Key files changed/added

- `infra/sql/0002_source_decision_hot_refactor.sql`
- `services/models_services/hot-candidates-service/src/hot_candidates_model_service/research.py`
- `services/models_services/hot-candidates-service/src/hot_candidates_model_service/api.py`
- `services/models_services/hot-candidates-service/src/hot_candidates_model_service/schemas.py`
- `services/models_services/hot-candidates-service/src/hot_candidates_model_service/config.py`
- `services/models_services/hot-candidates-service/tests/test_hot_research_contract.py`
- `services/scheduler-service/pyproject.toml`
- `services/scheduler-service/src/scheduler_service/*`
- `services/scheduler-service/tests/test_scheduler_hot_plan.py`
- `services/market-data-service/src/market_data_service/source_contract.py`
- `services/market-data-service/tests/test_source_contract.py`

## Tests run in this container

- `services/models_services/hot-candidates-service`: 11 passed
- `services/scheduler-service`: 2 passed
- `services/market-data-service/tests/test_source_contract.py`: 2 passed
- Python compile check passed for changed service source paths

## Docker note

Docker is not installed in this execution container, so I could not run `docker compose` here. The code was validated with local Python tests and compile checks.


---

# HOT_PHASE2_FULL_PIPELINE_VALIDATION_REPORT

# Hot Candidates Phase 2 Full Pipeline Refactor Validation Report

## Scope

This phase strengthens the hot-candidates backend flow before touching frontend/Jarvis/research-center UI.

It treats the hot model as an independent model domain:

- `source.*`: clean source facts only, with `event_time`, `available_at`, `captured_at` lineage.
- `decision_hot.*`: hot model truth only.
- `governance.*`: lightweight registry/scheduler only, not model truth.

## Newly connected backend flow

The hot model now has an in-process full lifecycle pipeline endpoint:

```text
POST /pipeline/run
```

The endpoint wires these steps together:

```text
source visibility audit
-> legacy score compatibility
-> refined hot research contract
-> hot_cycle / hot_decision_case
-> initial decision snapshot freeze
-> release gate
-> buy point adapter and frozen first reference price
-> append-only observation snapshots
-> outcome label
-> failure attribution
-> first-output distortion analysis
-> evolution sample
```

This is not intended to replace persistence. It proves the contract flow is coherent before services write rows.

## Key backend additions

### hot-candidates-service

- Added `hot_candidates_model_service/pipeline.py`.
- Added `HotCandidatePipelineRunRequest` schema.
- Added `POST /pipeline/run`.
- Added source visibility audit for `available_at` time-lineage.
- Added hot buy point adapter output.
- Added outcome label builder.
- Added failure attribution builder.
- Added first-output distortion analysis builder.
- Added full lifecycle integration tests based on the user's supplied hot-model sample semantics for `002354 天娱数科`.

### scheduler-service

- Added `validate_hot_plan_contract()`.
- Added `GET /scheduler/validate/hot-candidates`.
- Added validation ensuring:
  - source collection never publishes official model facts;
  - only `hot.release_gate.preopen` can promote official hot signals;
  - observation/outcome/evolution tasks are append-only;
  - task order is coherent.

### market-data-service

- Added `build_source_fact_envelope_from_payload()`.
- Enforces source payloads must have `event_time` and `available_at` before model use.
- Continues rejecting model-owned fields inside source facts.

### SQL contract

- Added missing `decision_hot.hot_initial_decision_snapshot_v1` table.
- Added validation test to ensure required hot refactor tables exist.

## Validations executed

```text
services/models_services/hot-candidates-service: 13 passed
services/scheduler-service: 3 passed
services/market-data-service source_contract tests: 3 passed
root SQL contract test: 1 passed
compileall selected services: passed
```

## HTTP runtime validation

Started `hot-candidates-service` with uvicorn on port `8031` and called:

```text
GET /healthz
POST /pipeline/run
```

The runtime `/pipeline/run` test returned:

```text
model_version = hot_candidates_v2_lifecycle
official_allowed = True
buy_point_status = confirmed
outcome = direction_success / target_first
evolution_sample_type = validated_success
```

## Docker note

The current execution environment does not have Docker installed:

```text
docker: command not found
```

So Docker Compose runtime validation could not be performed in this container. The service was still started with uvicorn and tested through a real HTTP call.

## Known limitation

Full `market-data-service` test suite still requires project package dependencies such as `db_schema` and `sqlalchemy` in the Python path/environment. The new `source_contract` tests were isolated and passed.


---

# HOT_PHASE3_FULL_IMPLEMENTATION_VALIDATION_REPORT

# Hot Candidates Phase 3 Full Implementation Validation Report

本次继续按“接近从零开发”的口径强化热点模型主链路。本阶段仍然只处理：

- market-data-service 的独立源事实采集契约与本地可验证存储
- hot-candidates-service 的热点模型完整后端闭环
- scheduler-service 的热点模型调度链路与发布闸门保护

暂不处理前端、Jarvis、研究中心 UI、候选记忆模型和潜伏抬头模型。

## 核心架构原则

1. `source.*` 是统一、独立、一致的源事实层，不允许混入模型字段。
2. 热点模型所有业务真相落在 `decision_hot.*`，不和其他模型共用信号、买点、打标、进化表。
3. 高频采集不等于高频正式发布。
4. `release_gate` 是唯一正式信号提升路径。
5. 首次决策事实不可覆盖。
6. 第二次及之后持续观察必须 append-only。
7. 持续观察、结果标签、失败归因生成模型进化样本。
8. 模型进化只输出离线调整建议，不在线修改生产模型权重。

## 本阶段新增/强化文件

```text
services/models_services/hot-candidates-service/src/hot_candidates_model_service/persistence.py
services/models_services/hot-candidates-service/tests/test_hot_pipeline_persistence.py

services/market-data-service/src/market_data_service/source_store.py
services/market-data-service/tests/test_source_store.py

services/scheduler-service/src/scheduler_service/orchestrator.py
services/scheduler-service/tests/test_hot_workflow_orchestrator.py
```

## 热点模型后端闭环当前已打通

```text
source fact validation
-> hot lifecycle / hot_cycle
-> daily hot decision case
-> initial decision snapshot frozen
-> stage scores
-> release gate
-> independent hot signal fact
-> hot buy point adapter and frozen reference entry price
-> append-only observation snapshots
-> outcome label
-> failure attribution
-> first output distortion analysis
-> evolution sample
-> model version evaluation summary
```

## 真实执行验证

已执行：

```text
hot-candidates-service tests: 15 passed
scheduler-service tests: 5 passed
market-data source contract/store tests: 5 passed
compileall: passed
```

已启动真实 HTTP 服务验证：

```text
GET http://127.0.0.1:8031/healthz: passed
POST http://127.0.0.1:8031/pipeline/run: passed
```

HTTP 管线结果：

```text
model_version = hot_candidates_v2_lifecycle
release_gate = passed
hot_signal.is_official_signal = true
buy_point_status = confirmed
outcome.direction_outcome = direction_success
evolution_sample.sample_type = validated_success
```

## Docker 说明

当前后台环境没有 Docker：

```text
docker: command not found
```

因此无法在后台执行 docker compose。已使用本地 Python 测试、真实 uvicorn HTTP 服务和 SQLite 持久化测试替代验证。

## 当前仍未完成的下一阶段

1. 将 SQLite 本地验证仓库替换/绑定为正式 Postgres repository。
2. market-data-service 从真实 provider 拉取后直接写入 `source.*` 新表，而不是只验证 envelope。
3. scheduler-service 绑定真实 owner service endpoint 后开启非 dry-run 调度。
4. execution-timing-service 正式迁移到 `decision_hot.hot_buy_point_v1` 写入。
5. data-inspector-service 增加 `source.*` 与 `decision_hot.*` 的 P0/P1/P2 巡检。
6. 继续完善热点生命周期自动归并和冷却后新周期识别。
```


---

# HOT_PHASE4_PRODUCTION_CHAIN_VALIDATION_REPORT

# HOT Phase 4 Production Chain Validation Report

本阶段继续按“完全按最新讨论版本、接近从零开发”的口径强化热点模型后端主链路。重点仍然不碰前端、Jarvis、候选记忆、潜伏抬头，而是把热点模型的数据采集、生命周期、生产持久化、调度 live dispatch 和真实接口验证继续打牢。

## 本阶段新增能力

1. `hot_lifecycle.py`
   - 新增热点生命周期解析器 `resolve_hot_cycle`。
   - 支持同一股票连续入榜复用 active hot cycle。
   - 支持冷却窗口超过、周期高点回撤过大后创建新 cycle。
   - 支持断板后反包 `relimit_after_break` 继续归入同一热点周期。
   - 输出 `cycle_resolution`，进入 `research_contract.hot_cycle`，用于后续研究中心解释“同一轮热点 / 冷却后新启动”。

2. `postgres_repository.py`
   - 新增 `HotPostgresWritePlanBuilder` 和 `HotPostgresRepository`。
   - 写入目标限定为 `decision_hot.*`，不混入 `decision_memory` 或 `decision_ambush`。
   - 首次决策快照使用 `ON CONFLICT DO NOTHING`，防止后续重算覆盖首次事实。
   - 持续观察使用 `ON CONFLICT (hot_case_id, observe_seq) DO NOTHING`，保持 append-only。
   - 支持生产 Postgres 连接注入；无 psycopg 环境下仍可做 SQL 合同测试。

3. `source_postgres_store.py`
   - 新增生产级 source fact envelope 写入器。
   - 写入 `source.source_fact_envelope_v1`。
   - 每条 source fact 保留 `event_time / available_at / captured_at / quality_status / payload_hash`。
   - 禁止 source fact 携带 `hot_score / model_score` 等模型语义。

4. `live_dispatch.py`
   - 新增 scheduler live dispatch 能力。
   - 非 dry-run 必须绑定 owner endpoint，防止调度器伪造成功。
   - 仍保持架构硬规则：source_collect 不能发布正式模型事实；observation/outcome/evolution 必须 append-only。
   - `scheduler /scheduler/trigger` 已支持 `owner_endpoints` 非 dry-run 调度入口。

5. `infra/sql/0002_source_decision_hot_refactor.sql`
   - 新增 `source.source_fact_envelope_v1`。
   - 保留 `decision_hot.*` 独立域。
   - 保留 `governance.*` 轻量注册域。

## 已执行验证

### hot-candidates-service

```bash
cd services/models_services/hot-candidates-service
PYTHONPATH=src pytest -q
```

结果：`19 passed`

覆盖：
- `/score`
- `/pipeline/run`
- time leakage block
- lifecycle resolution
- SQLite real persistence
- Postgres write plan contract
- initial decision immutable
- observation append-only
- evolution sample generation

### scheduler-service

```bash
cd services/scheduler-service
PYTHONPATH=src pytest -q
```

结果：`7 passed`

覆盖：
- hot plan validation
- workflow orchestrator
- live dispatch endpoint routing
- missing endpoint refusal
- official publish guardrail

### market-data-service source fact subset

```bash
cd services/market-data-service
PYTHONPATH=src pytest -q tests/test_source_contract.py tests/test_source_store.py tests/test_source_postgres_store_contract.py
```

结果：`6 passed`

覆盖：
- source fact envelope contract
- available_at visibility
- SQLite source store
- Postgres source envelope write contract
- source fact 不混入模型字段

### SQL contract

```bash
PYTHONPATH=services/models_services/hot-candidates-service/src pytest -q tests/test_hot_refactor_sql_contract.py
```

结果：`1 passed`

### compileall

```bash
python -m compileall -q services/models_services/hot-candidates-service/src services/scheduler-service/src services/market-data-service/src
```

结果：通过。

### 真实 HTTP 运行验证

已启动 `hot-candidates-service`：

```bash
PYTHONPATH=src uvicorn hot_candidates_model_service.main:app --host 127.0.0.1 --port 8031
```

验证：
- `GET /healthz` 返回 ok。
- `POST /pipeline/run` 返回 200。
- active hot cycle 被正确复用。
- `release_gate.official_signal_allowed = true`。
- `buy_point.buy_point_status = confirmed`。
- `outcome_label.direction_outcome = direction_success`。
- `evolution_sample.sample_type = validated_success`。

## Docker 验证状态

当前后台环境没有 Docker：

```text
docker: command not found
```

因此本阶段无法执行 `docker compose`。已改用本地 Python 单元测试、SQLite 真持久化、SQL 合同、真实 uvicorn HTTP 验证替代。

## 本阶段架构结论

当前热点模型已具备以下后端核心能力：

```text
统一 source fact 可见性审计
-> hot_cycle 生命周期识别
-> hot_decision_case 每日独立决策
-> initial_decision_snapshot 首次事实冻结
-> stage_scores 阶段评分
-> release_gate 独立发布闸门
-> hot_signal_fact 独立正式/研究信号
-> hot_buy_point 首次评估基准价冻结
-> hot_observation_snapshot 第二次以后 append-only 观察
-> hot_outcome_label 方向/执行/路径/环境/数据结果拆分
-> hot_failure_attribution 偶发/环境/执行/数据/模型系统性归因
-> hot_first_output_distortion_analysis 首次输出失真诊断
-> hot_evolution_sample 离线模型进化样本
-> hot_model_version_evaluation 版本评估基础
```

下一阶段建议：

1. 将 `HotPostgresRepository` 接入真实 Postgres 环境变量和服务启动配置。
2. 将 `market-data-service` 的真实 provider 写入同时落入 granular source tables 与 source envelope。
3. 让 scheduler 在 Docker/Postgres 环境中跑非 dry-run workflow。
4. 增加热点研究样本池：official / calibration / blocked_but_track / teacher_distortion。
5. 增强 hot_teacher_calibration 的批量生成与 Brier Score 计算。


---

# HOT_PHASE5_RESEARCH_CALIBRATION_VALIDATION_REPORT

# HOT Phase 5 Research Pool and Teacher Calibration Validation Report

## Scope

This phase continues the hot-candidates-service backend refactor without touching frontend, Jarvis, candidate-memory, or ambush services.

Phase 5 adds the missing research-learning layer required by the latest architecture discussion:

1. official_signal_pool / calibration_pool / blocked_but_track_pool / teacher_distortion_pool / research_watch_pool
2. Selection-bias control: non-official samples can be tracked for research, but they are not counted as formal recommendation success.
3. Teacher probability calibration by lifecycle stage and probability bucket.
4. Brier Score / realized hit rate / calibration error / lift calculations.
5. Research pool persistence in SQLite validation store and Postgres write plan.
6. Teacher calibration report endpoint and persistence helper.

## New code

- `services/models_services/hot-candidates-service/src/hot_candidates_model_service/calibration.py`
- `POST /research-pool/classify`
- `POST /teacher-calibration/report`
- Pipeline output now includes `research_sample_pool`.
- SQLite persistence now writes `hot_research_sample_pool_v1`.
- SQLite validation store can persist generated `hot_teacher_calibration_v1` rows.
- Postgres write plan now includes `decision_hot.hot_research_sample_pool_v1`.
- SQL DDL now includes `decision_hot.hot_research_sample_pool_v1`.

## Hard rules enforced

1. Official signals are the only records eligible for formal success-rate calculation.
2. Calibration, blocked-but-track, and teacher-distortion samples can be tracked for research only.
3. Time-leakage samples are excluded from learning.
4. Teacher calibration cannot mutate production model online.
5. Calibration activation requires sample thresholds and must shadow-run before production activation.
6. Research sample pool records are append-oriented research contracts, not frontend decisions.

## Validation executed

```bash
PYTHONPATH=services/models_services/hot-candidates-service/src pytest -q services/models_services/hot-candidates-service/tests
# 22 passed

PYTHONPATH=services/scheduler-service/src pytest -q services/scheduler-service/tests
# 7 passed

PYTHONPATH=services/market-data-service/src pytest -q \
  services/market-data-service/tests/test_source_contract.py \
  services/market-data-service/tests/test_source_store.py \
  services/market-data-service/tests/test_source_postgres_store_contract.py
# 6 passed

pytest -q tests/test_hot_refactor_sql_contract.py
# 1 passed

python -m compileall -q \
  services/models_services/hot-candidates-service/src \
  services/scheduler-service/src \
  services/market-data-service/src
# passed
```

## Real HTTP validation executed

A real local uvicorn server was started for `hot_candidates_model_service.main:app` on `127.0.0.1:8031`.

Validated:

```text
GET /healthz -> 200
POST /pipeline/run -> research_sample_pool.tracking_pool = official_signal_pool
POST /teacher-calibration/report -> activation_gate.can_activate_calibration = true with test thresholds
```

## Docker status

The current background environment does not provide Docker. Docker Compose validation was not executed here. Local Python tests, SQLite persistence, SQL contract tests, compileall, and real uvicorn HTTP checks were executed instead.


---

# HOT_PHASE6_PRODUCTION_ACCEPTANCE_REPORT

# HOT PHASE 6 Production Acceptance Report

## Scope

本阶段只强化热点模型链路，不修改前端、Jarvis、候选记忆模型、潜伏抬头模型。

Phase 6 目标是把 Phase 5 的单 case 研究闭环推进为可支撑大数据量生产调度的热点模型后端链路：

1. 拆分生产级分阶段入口，不再把 `/pipeline/run` 当作唯一生产入口。
2. 增加热点特征预计算层，避免每个 case 反复扫 source 高频事实。
3. 增加 active case registry 和 latest state，解决持续观察爆量和前端/调度快速查询问题。
4. 保持 observation append-only，latest_state 只作为当前状态投影，不作为训练真相。
5. 增加 DB-backed scheduler task instance / lease / retry / dead letter / run log。
6. 教师概率校准只使用 mature label，并且版本化、cutoff 化，避免未来函数。
7. 增加批量 observation，真实验证 1000 个 active hot case 批量观察。
8. SQL DDL 补充生产计算表、活跃调度表、校准版本表和治理任务表。

## New / Changed Files

### hot-candidates-service

- `src/hot_candidates_model_service/phase6.py`
- `src/hot_candidates_model_service/persistence.py`
- `src/hot_candidates_model_service/api.py`
- `src/hot_candidates_model_service/schemas.py`
- `tests/test_hot_phase6_production_compute.py`
- `tests/test_hot_phase6_api.py`

### scheduler-service

- `src/scheduler_service/task_store.py`
- `tests/test_phase6_task_store.py`

### infra/sql

- `infra/sql/0002_source_decision_hot_refactor.sql`
- `tests/test_hot_refactor_sql_contract.py`

## Phase 6 Implemented Tables / Contracts

### decision_hot feature precompute layer

- `decision_hot.hot_cycle_day_feature_v1`
- `decision_hot.hot_intraday_feature_snapshot_v1`
- `decision_hot.hot_execution_feature_snapshot_v1`

### decision_hot active tracking layer

- `decision_hot.hot_active_case_registry_v1`
- `decision_hot.hot_case_latest_state_v1`

### decision_hot calibration / evolution production layer

- `decision_hot.hot_calibration_job_v1`
- `decision_hot.hot_teacher_calibration_version_v1`
- `decision_hot.hot_candidate_model_version_v1`
- `decision_hot.hot_shadow_run_result_v1`

### governance scheduler layer

- `governance.task_instance_v1`
- `governance.task_lease_v1`
- `governance.task_dead_letter_v1`
- `governance.task_run_log_v1`

## Production Endpoint Split

`/pipeline/run` is retained as a debug / integration endpoint, not as the only production path.

New Phase 6 endpoints:

- `POST /production/features/build`
- `POST /production/observations/bulk`
- `POST /production/teacher-calibration/version`

These map to the production responsibilities:

- feature precompute
- batch append-only observation
- offline mature-label teacher calibration versioning

## Important Architecture Rules Enforced

1. First decision facts remain immutable.
2. Observation snapshots are append-only.
3. Latest state is a fast projection only, not training truth.
4. Teacher calibration uses only mature labels available before `calibration_cutoff_time`.
5. Official success rate remains separate from research pools.
6. Scheduler tasks are idempotent, leased, retryable and dead-lettered.
7. Active case observation uses `next_observe_at`, `priority_level`, and `tracking_pool`, not brute-force full table scanning.
8. Same observation replay does not duplicate append-only facts.
9. `hot_cycle` has an active-cycle uniqueness contract on symbol in SQL.
10. Source typed tables are still the high-volume read path; source envelope remains audit lineage.

## Validation Performed

Commands executed successfully:

```bash
cd services/models_services/hot-candidates-service
python -m pytest -q
# 26 passed

cd services/scheduler-service
python -m pytest -q
# 8 passed

cd services/market-data-service
PYTHONPATH=src python -m pytest -q tests/test_source_contract.py tests/test_source_store.py tests/test_source_postgres_store_contract.py
# 6 passed

cd <repo-root>
PYTHONPATH=services/models_services/hot-candidates-service/src python -m pytest -q tests/test_hot_refactor_sql_contract.py
# 1 passed

python -m compileall -q services/models_services/hot-candidates-service/src services/scheduler-service/src services/market-data-service/src
# passed
```

HTTP runtime smoke test executed:

```bash
GET /healthz
POST /production/observations/bulk
```

Observed successful response:

- service healthy
- one bulk observation generated
- `return_from_reference_pct`, `mfe_pct`, `mae_pct`, `expectation_state` calculated
- no contract gaps

## Phase 6 Acceptance Items

| Acceptance Item | Status |
|---|---|
| 1000 active hot cases batch observation does not time out in local validation | PASS |
| Observation append-only; replay is idempotent | PASS |
| latest_state updates but is not treated as training truth | PASS |
| First decision snapshot remains immutable | PASS, inherited from Phase 5 and revalidated |
| Active case registry supports priority and next_observe_at scheduling | PASS |
| Teacher calibration only uses mature labels before cutoff | PASS |
| Calibration output is versioned | PASS |
| Scheduler has task instance / lease / retry / dead letter / run log | PASS |
| SQL contract includes Phase 6 tables and uniqueness/index rules | PASS |
| Docker Compose validation | NOT RUN: current environment has no docker binary |

## Docker Note

The current execution environment does not include Docker:

```text
docker: command not found
```

Therefore Docker Compose could not be executed here. Validation was performed with:

- local Python unit/integration tests
- SQLite real persistence tests
- SQL contract tests
- compileall
- real uvicorn HTTP smoke test

## Remaining Production Work After This Phase

Phase 6 backend acceptance is complete for the local validation environment.

Before live deployment, run in the target environment:

1. Postgres DDL apply.
2. Real source provider ingestion into typed `source.*` tables.
3. Non-dry-run scheduler task dispatch with real owner endpoints.
4. 5-20 trading day replay using real THS candidates, auction, minute bars, moneyflow, sector and market regime data.
5. Compare Phase 6 local SQLite contract outputs with Postgres production repository outputs.


---

# HOT_PHASE7_PRODUCTION_FINALIZATION_REPORT

# Hot Candidates Phase 7 Production Finalization Report

## Scope

本阶段针对 Phase 6 最高规格审查发现的 P0/P1 问题继续整改，目标是让热点模型从“生产验收骨架”推进为“生产定版候选”。本次仍然只处理后端，不处理前端、Jarvis、研究中心 UI、候选记忆、潜伏抬头。

## Key Fixes

### 1. 生产分阶段接口

新增生产级分阶段入口，生产调度不再依赖 `/pipeline/run`：

- `POST /production/cases/build`
- `POST /production/scores/compute`
- `POST /production/release-gate/evaluate`
- `POST /production/buy-point/evaluate`
- `POST /production/outcomes/mature`
- `POST /production/evolution/build`
- `POST /production/failure-analysis/build`

`/pipeline/run` 保留为本地调试和集成验证入口，不作为生产调度主入口。

### 2. available_at 硬审计

`candidate_item`、`teacher_prior`、`auction`、`stock_moneyflow`、`market_regime`、最近 20 根日线的 `available_at` 缺失或未来可见均会阻断正式发布。

- `missing_available_at_lineage` 从 warning 升级为 hard block。
- 硬阻断样本可进入研究池，但不得进入正式成功率。

### 3. 阶段化评分增强

`official_hot_score` 不再绕开竞价确认。新的阶段分明确纳入：

- teacher prior calibration
- auction confirmation
- capital follow-through
- tradability
- upside
- overheat penalty
- lifecycle-stage-specific weights

高教师概率但弱竞价会被额外降级。

### 4. 买点正式基准价规则收紧

首次有效评估基准价只能来自：

- `auction_confirmed`
- `open_5m_confirmed`

`latest_price` 和 `previous_close` 只允许做诊断，不得冻结正式基准价。

### 5. outcome/evolution 成熟边界

`evolution_sample` 只能由 `label_maturity_status = mature` 的 outcome 生成。pending outcome 会被阻断：

- `build_status = blocked_outcome_not_mature`

### 6. scheduler live dispatch 修正

scheduler live dispatch 已改为生产分阶段 endpoint：

- model_compute -> `/production/scores/compute`
- release_gate -> `/production/release-gate/evaluate`
- buy_point -> `/production/buy-point/evaluate`
- observation -> `/production/observations/bulk`
- outcome -> `/production/outcomes/mature`
- evolution -> `/production/evolution/build`

### 7. DB/DDL 对齐

- `decision_hot.hot_buy_point_v1` 增加 `hot_cycle_id`，与 SQLite 测试表、repository、Pydantic 语义对齐。
- 增加 BRIN 索引和生产分区说明，用于后续真实大数据量部署。

## Validation

已执行：

```text
hot-candidates-service: 30 passed
scheduler-service: 8 passed
market-data source subset: 6 passed
compileall: passed
FastAPI TestClient smoke test: passed
```

当前后台环境没有 Docker，仍无法执行 Docker Compose：

```text
docker: command not found
```

因此本阶段完成的是本地 Python、SQLite、SQL contract、FastAPI TestClient 级别验证。真实 Docker Compose、Postgres 实库、真实 provider、全交易日回放仍需在具备 Docker/Postgres/真实数据源的环境继续执行。

## Remaining Production Environment Work

本代码包可以作为“热点模型生产定版候选”，但在正式定版前仍需在你的真实环境执行：

1. Docker Compose 全服务启动。
2. Postgres `source.*` 与 `decision_hot.*` DDL 初始化。
3. 真实 provider 数据写入 `source.*`。
4. scheduler 非 dry-run 调 owner service endpoint。
5. 连续 5-20 个交易日 replay。
6. 并发 hot_cycle 归并压力测试。
7. 大规模 active case observation 压测。

## Status

热点模型后端当前状态：

```text
生产定版候选：通过本地高级后端逻辑验收。
正式生产定版：等待真实 Docker/Postgres/provider/replay 环境验证。
```
