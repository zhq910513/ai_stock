# research-service

## Hot Score Daily Bar Fallback Contract

2026-06-26 current contract: for `hot.score.auction_confirmed` only, if `source.daily_bar_v1` has no row for a paid-probability candidate but `source.adjusted_daily_bar_v1` has usable rows for the same symbol/trade date through the normal source build path, `research-service` may normalize the adjusted OHLC fields into the owner-facing `daily_bars` price-path view. The payload must keep `adjusted_daily_bars`, set `daily_bar_source=source.adjusted_daily_bar_v1`, set `daily_bar_fallback_used=true`, and keep `source_gap:daily_bar_missing_using_adjusted_daily_bar` in `warnings`.

This is not a source-data backfill and does not claim that `source.daily_bar_v1` exists. It is a research assembly fallback for the hot score stage so real THS paid-probability candidates are not blocked when the unadjusted daily source is incomplete but adjusted daily source is complete and usable. Other tasks, including ambush, memory, T relay, hot release gate, buy point, outcome, and evolution, continue to treat missing `source.daily_bar_v1` according to their own hard gap contracts. Missing adjusted daily rows, non-usable quality, or missing available-at/lineage remain gap-coded and must not be replaced with 0, mock, sample payloads, or inferred values.

## Hot Stage Case Reuse Contract

2026-06-27 current contract: `hot.score.auction_confirmed` is the only hot stage that may create `decision_hot.hot_cycle_v1`, `decision_hot.hot_decision_case_v1`, and source evidence rows from a newly assembled candidate payload. Later stages, including `hot.release_gate.preopen` and `hot.buy_point.open_5m`, must reuse the existing scored case. For non-score stages, the materializer resolves `hot_case_id` and `hot_cycle_id` from the assembled upstream `decision_hot.hot_decision_case_v1` row first; owner top-level ids and nested `hot_signal` / `buy_point` ids are accepted only when they match that scored case lineage.

Release-gate and buy-point materialization append only the owner-returned release audit, signal, and buy-point facts. They must not mint a replacement case id from `payload_hash`, must not insert another decision case or hot cycle for the same scored candidate, and must not add duplicate evidence snapshots for the stage run. If a non-score owner response carries a different generated case id, research-service ignores owner-provided signal/buy ids and regenerates deterministic signal/buy ids under the upstream scored case. If a non-score stage has no resolvable existing case id, materialization is skipped instead of inventing a new case. This preserves the one scored decision case -> many downstream facts chain used by scheduler catch-up, DB validation, and `/research/model-list/hot`.

本目录是 `research-service` 服务根目录唯一当前 MD。全局硬约束以项目根目录 `AGENTS.md` 为准；模型 owner 合同见 `services/models_services/README.md` 和各模型子服务 README。

本服务数据资产账本见 `services/research-service/DATA_ASSETS.md`，记录模型 payload 组装读取的 source 表、上游事实表、审计表、接口和禁止边界。

## 定位

`research-service` 是三模型与模型四 owner service 前的真实 payload 组装、owner 执行桥和 owner 输出物化层。它负责把已经经过 source build、quality_status、lineage 和 available_at 校验的 `source.*` 标准事实，以及允许读取且不携带硬阻断缺口 / sample 标记的 `decision_*` / `research_*` 上游事实，组装为 owner service 可接收的业务 payload；当 `scheduler-service` 开启模型任务 live dispatch 时，本服务通过 `/research/model-execution/run` 调用 owner service，并只把 owner 返回的结构化结果物化到对应 `decision_*` / `research_*` 表。模型四 Day2 watch/trigger、触发后监控、Day3 去留和 outcome 对 owner 已定义为非硬阻断的研究型上游缺口只进入 `warnings` / `warning_codes`，不得抹掉缺口，也不得因为 P1 缺口误阻断真实 source 组装。

本服务不计算模型分数、不修改 owner 内部 release gate、不自行生成买点版本、不生成 outcome 标签、不修改学习权重或交易事实，也不负责 provider 调用、raw ingest、source build 或 scheduler 调度。缺事实时返回 `blocked_data_gap` 和 `source_gap:*` 且不调用 owner；owner 返回 hot signal / buy point / outcome 等结构化事实时，本服务只做 append-only 物化，不自行发布、改写或提升 official 结论。不得用 0、空字符串、sample payload、前端 mock 或 GPT 推断补齐。

## 当前版本

- Payload assembler：`research_model_payload_assembler_v1`
- Model execution：`research_model_execution_v1`
- Assembled status：`assembled_research_payload`
- Blocked status：`blocked_data_gap`
- 审计表：`governance.research_model_payload_assembly_audit_v1`、`governance.research_model_execution_audit_v1`
- 物化器：`ResearchDecisionMaterializer`
- owner 调用器：`ModelOwnerClient`

## 冻结记录

2026-06-17，`research-service -> model-payload-assembler -> research_model_payload_assembler_v1` 达到当前拍板冻结标准：

- 已完成真实 source/upstream payload 组装接口、requirements 接口、readyz 和 append-only 审计表。
- 已验证缺 `source.stock_master_v1` 时返回 `blocked_data_gap`，不补假事实。
- 已验证上游事实携带 `source_gap_codes`、`gap_codes`、`contract_gaps` 或 sample 标记时返回 `blocked_data_gap`，并与 scheduler preflight 门禁一致。
- 已验证 source-data-service、data-inspector-service、scheduler-service 和 research-service readyz 均为 ready，且本轮仅重建 research-service。

冻结后，未经用户批准不得修改本服务的 payload 组装合同、状态语义、缺口码规则、审计表写入、Docker 入口、readyz 判定或禁止 provider/raw/model fact 写入边界。当前真实数据缺口（例如 `source.stock_master_v1` 为空、部分上游 decision 行携带 sample 标记）属于数据资产现状，不解除冻结；后续补数必须通过 source-data-service / owner service 正规链路完成。

2026-06-18 合同修正：official release gate 的 payload 组装不得等待自身即将产出的 `*_signal_fact_v1`。`hot.release_gate.preopen` 读取 `decision_hot.hot_score_fact_v1` 和 `decision_hot.hot_evidence_snapshot_v1`，且不把 `source.realtime_quote_v1` / `source.minute_bar_v1` 作为 research payload 硬依赖；source release preflight 仍是 official 发布前置门禁。`memory.release_gate.close` 读取 `decision_memory.memory_pre_signal_case_v1` 与 `decision_memory.memory_score_fact_v1`。`ambush.phase3.release_gate.close` 读取 `decision_ambush.effective_turn_pool_v1`。若这些上游事实缺失，继续返回 `blocked_data_gap`，不得用 signal 输出、sample payload、0 或推断补齐。

2026-06-19 合同修正：`hot.release_gate.preopen` 的 `decision_hot.hot_score_fact_v1` 与 `decision_hot.hot_evidence_snapshot_v1` 上游读取必须通过 `decision_hot.hot_decision_case_v1.hot_case_id` 按 `symbol + trade_date` 关联。两张上游表本身不含 `symbol` / `trade_date` 字段，不得因为通用 upstream 查询找不到字段而误报缺失；读取到上游后仍必须扫描其中的硬阻断缺口、sample 标记和 `source-data-service /source/release/preflight` 结果，`source_preflight_not_passed` 或 score blocked 仍返回 `blocked_data_gap`，不得发布 official signal。

2026-06-27 合同修正：`hot.score.auction_confirmed`、`hot.release_gate.preopen`、`hot.buy_point.open_5m` 在 scheduler live dispatch 或显式多标的请求下由 research-service 执行热点候选 fanout。评分阶段的候选池来自 `source.ths_paid_limit_up_probability_v1`；release/buy-point 阶段的候选池来自已落库 `decision_hot.hot_decision_case_v1` 关联最新 `decision_hot.hot_score_fact_v1`，按真实评分/概率排序。scheduler 仍只负责时间槽与本地 task store，不把 `SCHEDULER_GUARD_SYMBOL` 或 catch-up 占位 symbol 当作生产候选回退。

同一修正下，`hot.buy_point.open_5m` 的硬上游合同为 `decision_hot.hot_decision_case_v1`、`decision_hot.hot_score_fact_v1` 加开盘分钟/竞价 source 事实，不再硬等 `decision_hot.hot_release_gate_audit_v1` 或 `decision_hot.hot_signal_fact_v1`。owner `/production/buy-point/evaluate` 返回的 `hot_signal` 和 `buy_point` 均按 owner flags append-only 物化：`is_official_signal=false/is_research_only=true` 必须保持 research-only，`buy_point_status=blocked` 是诊断事实，不是交易指令；不得因为 `hot_signal_id` 字段非空而伪装 official signal。

同一修正的运行态修复要求：`decision_hot.hot_signal_fact_v1.release_gate_reason` 等无 `_json/_jsonb` 后缀但物理类型为 `jsonb` 的字段必须通过合法 JSONB 绑定落库；owner 返回的阻断原因数组必须保留为 JSON 数组，禁止以 PostgreSQL array 字面量、字符串拼接、空字符串或默认 `0` 代替真实阻断原因。

2026-06-19 定向发布记录：用户批准后，仅执行 `docker compose -f infra/docker-compose.yml build research-service` 与 `docker compose -f infra/docker-compose.yml up -d --no-deps research-service`，未重启 `source-data-service`、`source-data-worker`、`scheduler-service`、`data-inspector-service`、Postgres 或模型 owner 服务。发布前回滚标签为 `infra-research-service:rollback-20260619-hot-release-upstream`，对应镜像 `sha256:f7e781c06705f2e60d50997601c65bcbc82091f2a7ae717dc9186be93300856e`；发布后镜像为 `infra-research-service@sha256:df3bbdb65ebf244626a37205541a9adc48496243c36c640d3b3b152f2e78b707`，容器为 `ai-stock-research-service b263f422bac1`。运行态 no-persist assemble 验证 `hot.release_gate.preopen / 000759.SZ / 2026-06-12` 返回 `blocked_data_gap`、`audit_persisted=false`、`decision_hot.hot_score_fact_v1 row_count=1`、`decision_hot.hot_evidence_snapshot_v1 row_count=8`，不再出现 `decision_hot_hot_score_fact_missing` 或 `decision_hot_hot_evidence_snapshot_missing`，仍因 `source_gap:source_preflight_not_passed` 阻断 official release。

2026-06-18 定向发布冻结：用户批准“发布 research+scheduler”后，本服务与 `scheduler-service` 执行单服务镜像构建和 `--no-deps` 容器替换；未重启 `source-data-service`、`source-data-worker`、`data-inspector-service`、Postgres 或模型 owner 服务。发布后 `ai-stock-research-service` 容器为 `c27f4f6c9dbe`，镜像 digest 为 `sha256:3492ea38cd553bea0524846bf9256ebaaadf850a2dfff8eaec766e2d64152c35`；回滚标签为 `infra-research-service:rollback-20260618-research-scheduler-release`。运行态验证显示三条 official release gate 已使用新上游合同：`hot.release_gate.preopen` 只读取日线/资金/事件 source 和 `decision_hot.hot_score_fact_v1`、`decision_hot.hot_evidence_snapshot_v1`；`memory.release_gate.close` 读取 `decision_memory.memory_pre_signal_case_v1`、`decision_memory.memory_score_fact_v1`；`ambush.phase3.release_gate.close` 读取 `decision_ambush.effective_turn_pool_v1`。三条 no-persist assemble-preflight 因真实上游 decision fact 为空返回 `blocked_data_gap`，`dispatch_allowed=false`，不触达 owner endpoint，不写模型事实；正式模型任务执行必须走 `/research/model-execution/run` 并按 `research_model_execution_v1` 审计。该发布对象可冻结；未经用户再次解锁不得放宽上述 release gate 上游合同、缺口阻断、no-persist preflight 和禁止 provider/raw/model fact 写入边界。

## API

健康：

```text
GET /healthz
GET /readyz
```

Payload 合同：

```text
GET  /research/model-payload/requirements
POST /research/model-payload/assemble
POST /research/model-execution/run
```

`GET /research/model-payload/requirements` 返回 25 个非 source 的模型 owner 任务合同，覆盖：

```text
hot.* 6 个
memory.* 5 个
ambush.* 6 个
t_relay.* 8 个
```

`POST /research/model-payload/assemble` 请求：

```json
{
  "task_code": "t_relay.day1.scan.close",
  "symbol": "000759.SZ",
  "symbols": ["000759.SZ"],
  "trade_date": "2026-06-12",
  "as_of_time_utc": "2026-06-12T07:05:00Z",
  "run_id": "research-run-id",
  "persist_audit": true,
  "extra_context": {}
}
```

响应始终包含：

```text
payload_assembly_contract=research_model_payload_assembler_v1
payload_assembly_status=assembled_research_payload | blocked_data_gap
payload_assembly_source=research-service:research_model_payload_assembler_v1
assembly_id
payload_hash
source_refs
upstream_refs
gap_codes
warnings
payload
```

official release 任务还会调用 `source-data-service /source/release/preflight`；返回 `can_release_official_signal=false` 时，本服务必须返回 `blocked_data_gap`。

`POST /research/model-execution/run` 请求继承 `POST /research/model-payload/assemble` 合同，并可额外传入 `execution_id`。执行链路为：

```text
payload assemble
-> blocked_data_gap 时停止且 owner_called=false
-> assembled_research_payload 时调用 owner endpoint
-> owner 2xx 后物化 owner structured_output
-> 写入 governance.research_model_execution_audit_v1
```

响应始终包含：

```text
execution_contract=research_model_execution_v1
execution_status=blocked_data_gap | owner_failed | materialization_failed | materialized | materialized_with_gaps | materialization_skipped
accepted
dispatch_allowed
owner_called
materialization_attempted
owner_endpoint
owner_status_code
materialized_counts
gap_codes
audit_persisted
assembly
```

`GET /research/model-list/hot?limit=100` 返回热点模型前端只读投影：

```text
contract_kind=research_hot_model_list_v1
model_code=hot_candidates
read_only=true
readiness_contract=hot_model_data_readiness_v1
readiness_weight_total=100
readiness_dimensions[]
readiness_summary
items[]
gap_codes[]
```

该接口只读取 `decision_hot.hot_decision_case_v1`、最新 `decision_hot.hot_score_fact_v1`、`decision_hot.hot_release_gate_audit_v1`、`decision_hot.hot_signal_fact_v1`、`decision_hot.hot_buy_point_v1`，并只读关联 `source.stock_master_v1`、`source.daily_bar_v1`、`source.ths_paid_limit_up_probability_v1` 作为展示上下文。同一 `symbol + trade_date` 存在历史重复 case 时，列表优先选择已关联 `hot_score_fact_v1` 的 scored current case，再关联 signal/buy；历史重复 case 继续留库审计但不作为当前前端行。列表按真实 `model_score` 降序输出；缺信号、缺买点、缺同花顺概率或缺同日行情时保留 `NULL` 与 `source_gap:*`，不得在 research-service 内补 0、生成买点、改 release gate、调用 provider 或触发 owner。

热点列表同时返回 `hot_model_data_readiness_v1` 数据准备度合同，用于回答“当前距离可产出还差多少”。该准备度只基于已落库 `decision_hot.*`、已构建 `source.*` 和 lineage/preflight 缺口事实计算，不调用 owner、不触发 source fetch、不写任何表，也不改变模型分、release gate、买点或 official signal。每行新增字段：

```text
readiness_score_pct        已具备权重点数，0-100；无行时汇总平均值为 null
missing_points             100 - readiness_score_pct
blocked_points             缺失 P0 权重点数
readiness_state            ready / degraded / blocked
top_missing_dimension      当前最大缺失维度
readiness_gap_codes[]      按维度生成的 source_gap:* 缺口码
readiness_dimensions[]     逐维度权重、优先级、状态、缺失分、来源表和处理规则
```

固定权重总分为 100：P0 共 75 分，包含候选与可交易 12、同花顺付费概率 22、交易日历与窗口 6、日线与涨跌停 12、竞价确认 10、开盘 5 分钟路径与基准价 8、source 治理门禁 5；P1 共 18 分，包含资金上下文 7、市场环境 5、题材板块 4、巡检上下文 2；P2 共 7 分，包含新闻事件 4、后验验证 3。任一 P0 维度缺失时 `readiness_state=blocked`；仅 P1/P2 缺失时为 `degraded`；全部齐全才为 `ready`。真实数据缺失必须保持 `NULL`、缺口码和缺失分，不得用 0、空字符串、前端 mock 或 GPT 推断补齐。

准备度逐行检查会读取多个 `source.*` / `decision_hot.*` 表的存在性和字段集合；仓储实例内允许缓存 `table_exists` 与 `table_columns` 这类 metadata 查询，减少同一请求内重复 information_schema 访问。该缓存只覆盖表结构元数据，不缓存业务行、不改变 source freshness/lineage/preflight 事实，也不能用来跳过缺口判断。

## 数据入口

只读 source 标准事实：

```text
source.trade_calendar_v1
source.stock_master_v1
source.stock_universe_daily_v1
source.trade_status_v1
source.daily_bar_v1
source.adjusted_daily_bar_v1
source.limit_price_v1
source.limit_event_v1
source.stock_moneyflow_daily_v1
source.event_news_v1
source.realtime_quote_v1
source.minute_bar_v1
source.trade_tick_v1
```

只读上游模型事实：

```text
decision_hot.hot_score_fact_v1
decision_hot.hot_evidence_snapshot_v1
decision_hot.hot_decision_case_v1
decision_hot.hot_release_gate_audit_v1
decision_hot.hot_signal_fact_v1
decision_hot.hot_buy_point_v1
decision_memory.memory_entity_v1
decision_memory.memory_pre_signal_case_v1
decision_memory.memory_score_fact_v1
decision_memory.memory_signal_fact_v1
decision_ambush.ambush_outcome_label_v1
decision_ambush.ambush_failure_attribution_v1
decision_ambush.effective_turn_pool_v1
decision_ambush.ambush_signal_fact_v1
decision_t_relay.t_board_day1_candidate_v1
decision_t_relay.t_board_day2_watch_snapshot_v1
decision_t_relay.t_board_day2_entry_trigger_v1
decision_t_relay.t_board_post_entry_monitor_v1
decision_t_relay.t_board_day3_exit_decision_v1
```

本服务禁止读取 `raw_*`、`raw.*` 或 provider 原始响应。

## 输入数据样式

组装后的 `payload` 是 owner service 的业务 payload 本体。显式预检时，scheduler `POST /scheduler/model-payload/assemble-preflight` 只读取本 payload 并生成 owner request body preview；正式模型任务 time wheel live dispatch 时，scheduler 调用 `POST /research/model-execution/run`，由 research-service 适配并调用 owner：

- `hot-candidates-service`：research-service 包装成 `{ "payload": ... }`。
- `candidate-memory-service`：research-service 包装成 `{ "row": ... }`；`memory.seed.from_hot_signals` 会先构建 seed，再调用 `/production/entity/build` 物化 entity。
- `ambush-watchlist-service`：research-service 直接透传阶段 payload。
- `t-board-relay-service`：Day1 使用 `rows[]`，每行从 `source.stock_master_v1.stock_name` 投影 `stock_name/name` 供 owner 写入 Day1 候选和前端只读观察台；Day2/Day3/outcome 与 `t_relay.observation.monitor.snapshot_5m` 使用单对象 `payload`，owner request body 不再携带 `row` 或 `rows`。

payload 内保留 `payload_assembly_contract`、`payload_assembly_status`、`payload_assembly_source`、`source_refs`、`source_gap_codes`、`contract_gaps`、`warning_codes` 和 `source_preflight`，供 scheduler preflight 和后续审计使用。

## 状态流转

```text
assemble request
-> task requirement lookup
-> source.* read with quality/available_at checks
-> allowed upstream decision/research read and upstream gap/sample marker scan
-> optional /source/release/preflight
-> assembled_research_payload or blocked_data_gap
-> append-only governance audit
```

正式执行状态流转：

```text
model execution request
-> payload assembly
-> blocked_data_gap: stop before owner and audit execution
-> owner call
-> owner_failed | materialization_failed | materialized | materialized_with_gaps | materialization_skipped
-> append-only execution audit
```

状态含义：

- `assembled_research_payload`：当前任务所需 source/upstream/preflight 合同满足组装要求，且 payload 中没有硬阻断上游缺口码或 sample 标记。模型四 `t_relay.day2.watch.rolling_5m`、`t_relay.day2.trigger.rolling_5m`、`t_relay.day2.post_entry.monitor`、`t_relay.day3.exit.open`、`t_relay.day3.exit.tail` 与 `t_relay.outcome.build` 中的 `source_gap:seal_order_snapshot_missing`、`source_gap:dynamic_feature_bundle_missing`、`source_gap:near_limit_order_absorption_missing` 属于 owner 已定义的可审计研究缺口，只进入 warnings，不改变 assembled 状态。`t_relay.observation.monitor.snapshot_5m` 不读取 source/upstream，只透传观察台快照参数和 scheduler 补偿上下文给 owner。
- `blocked_data_gap`：缺 source、缺 upstream、source quality 不可用、缺 available_at、上游事实携带硬阻断缺口码 / sample 标记，或 source preflight 未通过。

## 调度频率

本服务当前无内置定时任务。它由 scheduler 或人工验收按模型任务频率调用：

| 模型 | 任务频率 | 调用接口 |
|---|---|---|
| 热点 `hot.*` | 09:25-09:36 固定/窗口，盘中观察，收盘 outcome，18:30 evolution | 显式预检：`POST /research/model-payload/assemble`；正式 live dispatch：`POST /research/model-execution/run` |
| 候选记忆 `memory.*` | 15:45 seed，15:55 pre-signal，16:05 release，次日开盘窗口，收盘成熟检查 | 显式预检：`POST /research/model-payload/assemble`；正式 live dispatch：`POST /research/model-execution/run` |
| 潜伏抬头 `ambush.*` | 周期 source audit，18:10 图库，15:20 Phase2，15:35 release/buy point，15:55 outcome | 显式预检：`POST /research/model-payload/assemble`；正式 live dispatch：`POST /research/model-execution/run` |
| T 字板 `t_relay.*` | Day1 15:05-15:30，Day2 09:25 预加载、09:30-10:30 每五分钟滚动接近涨停观察、触发后至收盘维护，Day3 09:25-09:35/14:40-14:55，观察台快照 09:30-11:30/13:00-15:00 每五分钟，outcome | 显式预检：`POST /research/model-payload/assemble`；正式 live dispatch：`POST /research/model-execution/run` |

非临时 source 采集仍由 `scheduler-service` 提交到 `source-data-service /source/fetch/submit`，本服务不提交 provider fetch。

## 数据产出

本服务产出：

- owner service 业务 payload。
- `source_refs` / `upstream_refs` 审计引用。
- `source_gap_codes` / `contract_gaps`。
- `payload_hash`。
- `governance.research_model_payload_assembly_audit_v1` append-only 审计记录。
- `governance.research_model_execution_audit_v1` append-only 执行审计记录。
- owner 输出物化后的 `decision_hot.*`、`decision_memory.*`、`decision_ambush.*`、`decision_t_relay.*` / `research_t_relay.*` 事实；其中 `t_relay.*` 由 owner repository 负责写入，本服务只记录 execution audit。

本服务不自行计算模型分数、release gate、official signal、买点、outcome、标签、交易事实或学习权重；只持久化 owner service 的真实返回结果。owner 未返回或返回缺口时，必须保留缺口与异常审计。

## 缺口码

当前缺口码模式：

```text
source_gap:<source_table>_missing
source_gap:<source_table>_available_at_missing
source_gap:<source_table>_quality_<status>
source_gap:<upstream_table>_missing
source_gap:source_preflight_unavailable
source_gap:source_preflight_not_passed
payload_gap:upstream_sample_payload_marker_present
owner_call_exception
owner_call_failed
materialization_exception
research_materializer_no_rows:<task_code>
source_gap:memory_age_trading_calendar_missing
source_gap:candidate_identity_tradeability_missing
source_gap:ths_paid_probability_missing
source_gap:trade_calendar_deadline_missing
source_gap:daily_limit_event_missing
source_gap:auction_confirmation
source_gap:open_5m_reference_path_missing
source_gap:stock_moneyflow_rank
source_gap:market_regime_context
source_gap:board_theme_context
source_gap:inspection_context
source_gap:news_event_context
source_gap:outcome_evolution_context
```

缺口必须保留在响应和审计表中，不得补事实。`warnings` / `warning_codes` 只表示不阻断当前组装的可审计研究缺口，不能被下游解释成事实完整。

## 模型四 Day2 组装合同

2026-06-23 定向更新 `t_relay.day2.watch.rolling_5m` 与 `t_relay.day2.trigger.rolling_5m`：

- Day2 source 组装显式读取 `source.limit_price_v1`、`source.minute_bar_v1`、`source.realtime_quote_v1`、`source.trade_tick_v1`。
- `t_relay.day2.watch.rolling_5m` 读取 `decision_t_relay.t_board_day1_candidate_v1`；Day1 候选携带 `source_gap:seal_order_snapshot_missing` 时保留为 warning，不阻断 Day2 watch 组装。
- `t_relay.day2.trigger.rolling_5m` 同时读取 `decision_t_relay.t_board_day1_candidate_v1` 与 `decision_t_relay.t_board_day2_watch_snapshot_v1`，确保 owner 能看到 Day1 candidate status 与 Day2 watch snapshot；该任务是 non-official 研究触发，不走 `source-data-service /source/release/preflight`，source 完整性由上述真实 source/upstream 读取和 gap 码约束。
- Day2 观察价来自 `09:30-10:30 Asia/Shanghai` 每 5 分钟滚动槽内的 `source.minute_bar_v1.close_price`；涨停价来自 `source.limit_price_v1.up_limit_price`；`distance_to_up_limit_pct` 由真实价格计算。若任一 5 分钟槽首次达到 `distance_to_up_limit_pct <= 0.01`，payload 写入 `first_qualified_monitor_time`、`monitor_check_time`、`monitor_interval_minutes=5` 和 `trigger_time`。
- 09:30 到当前 `monitor_check_time` 的 `source.trade_tick_v1.side_code/amount` 只作为 provider-native 逐笔侧向证据，组装为 owner 已支持的 `aggressive_buy_sweep_amount`、`aggressive_sell_hit_bid_amount`、`order_consumption_side` 和 `order_consumption_amount`。它不等同完整五档盘口，不得伪装为 `source.order_book_snapshot_v1`。
- `near_limit_order_absorption_score` 和动态特征 bundle 缺失时继续保留 warning/gap，不用 0、空字符串、mock 或推断补齐。

2026-06-23 更新口径：用户批准后，研究组装不再固定选最接近 10:30 的 bar；对当前可见 source 分钟线按本地交易时间升序选择首次接近涨停的 5 分钟槽。若未触发，则用窗口内最新可见 5 分钟槽继续输出 `rolling_watch`，缺分钟线或涨停价时保持 `source_gap:*`。

2026-06-23 性能修正：`t_relay.day2.watch.rolling_5m`、`t_relay.day2.trigger.rolling_5m`、Day3/outcome 等模型四非 Day1 阶段只向 owner 发送单对象 `payload`，不再把整批 `rows[]` 嵌入请求。读取 `decision_t_relay.*` 上游阶段事实时，research-service 仍用原始行扫描 gap/sample 标记，但写入 owner payload 前会剔除 `request_payload`、`result_payload`、`game_hypothesis_payload`、`evidence_json`、`related_payload` 等审计大字段；这些字段继续保留在 owner repository 和 governance audit 中用于追溯，不作为二次 owner 请求或前端只读 payload 的内容。

## 模型四 Day2 触发后与 Day3 组装合同

2026-06-24 定向更新 `t_relay.day2.post_entry.monitor`、`t_relay.day3.exit.open` 与 `t_relay.day3.exit.tail`：

- `t_relay.day2.post_entry.monitor` 读取 `decision_t_relay.t_board_day2_entry_trigger_v1` 作为触发锚点，继承触发时的 `trigger_time`、`monitor_check_time` 与 `up_limit_price`；若当前 source 未提供涨停价，允许从触发事实或上一阶段监控事实继承，不得用 0、空字符串或推断补齐。
- 触发后监控只使用触发时间之后到当前 `as_of_time_utc` 可见的 `source.minute_bar_v1`。当任一真实分钟线价格低于涨停价时，payload 写入 `post_entry_board_opened=true`、首次破板时间、破板次数、最低价、收盘价和最大回撤；若缺分钟线或缺涨停价，保持 `source_gap:*` 或 `NULL`，不伪造“封住到收盘”。
- `t_relay.day3.exit.open` 与 `t_relay.day3.exit.tail` 读取 Day2 触发事实、触发后监控事实和已存在的 Day3 决策事实；开盘判断取 09:25-09:35 可见分钟线，尾盘判断取 14:40-14:55 可见分钟线，均以真实价格是否接近或等于涨停价为准。
- Day3 payload 只提供 owner 决策所需的真实观测事实，例如 `day3_open_on_limit_flag`、`day3_tail_on_limit_flag`、`day3_open_price`、`day3_tail_price` 和对应时间；不得在 research-service 内生成卖出结论、交易指令或 official signal。
- 上游 `decision_t_relay.*` 携带的研究型 `source_gap:seal_order_snapshot_missing`、`source_gap:dynamic_feature_bundle_missing`、`source_gap:near_limit_order_absorption_missing` 对上述阶段保持 warning-only；sample 标记、缺上游触发事实、缺真实 source 价格或硬阻断 gap 仍按 `blocked_data_gap` 处理。

## 模型四观察台快照组装合同

2026-06-24 定向新增 `t_relay.observation.monitor.snapshot_5m`：

- 该任务只负责把 scheduler 的五分钟快照任务透传到 `t-board-relay-service /t-board-relay/observation-monitor/snapshot`；owner 从自身 repository 读取 `observation-board` 当前投影并 append-only 写入 `decision_t_relay.t_board_observation_monitor_snapshot_v1`。
- research-service 不读取 source 表、不读取 `decision_t_relay.*` 上游表、不补历史盘口或分钟事实；payload 只包含 `trade_date`、`limit=500`、`monitor_interval_minutes=5`、`as_of_time_utc`、`symbols` 和 `scheduler_context`。
- 当 scheduler 通过 `POST /scheduler/model-schedule/catch-up` 补偿错过的快照槽位时，`scheduler_context` 必须保留原始 `scheduled_at`、`run_slot`、`catch_up_run_id`、`captured_late` 和实际 `catch_up_checked_at`；快照更新时间按实际捕获时间记录，不伪装成历史实时采集。

### research-service -> model-payload-assembler -> t_relay observation snapshot pass-through freeze

- 冻结时间：2026-06-24 Asia/Shanghai。
- 拍板人 / 确认来源：用户授权 Codex 判断模型四链路是否可拍板，并在本轮回复“批准”；Codex 基于 scheduler catch-up、research execution、owner snapshot 和 frontend 只读验收判定可以冻结。
- 锁定范围：`t_relay.observation.monitor.snapshot_5m` 在 research-service 内只组装单对象 `payload`，字段为 `trade_date`、`limit`、`monitor_interval_minutes`、`as_of_time_utc`、`symbols` 和 `scheduler_context`；该任务不读取 source 表、不读取 `decision_t_relay.*` 上游表、不组装 row/rows，不补历史盘口或分钟事实。
- 当前冻结证据：`GET /research/model-payload/requirements` 返回 `task_count=25` 且该任务 `source_tables=[]`、`upstream_tables=[]`、`append_only=true`；2026-06-24 scheduler catch-up 非 dry-run 通过 `/research/model-execution/run` materialized，owner 快照表从 4 行增至 8 行，4 条 Day1 合格对象的观察台更新时间推进到 `2026-06-24T09:50:48.617447+00:00`。
- 允许的只读验收：`/readyz`、`/research/model-payload/requirements`、`/research/model-payload/assemble` 且 `persist_audit=false`、scheduler dry-run catch-up、owner snapshot/observation-board 和 frontend compact。
- 禁止修改项：未获解锁不得让该任务读取 raw/provider/source/upstream，不得把补偿快照伪装为历史实时盘口，不得由 research 计算模型分、状态、交易、买点、official signal 或前端展示事实。
- 解锁条件：owner snapshot endpoint 合同、scheduler catch-up 语义、research execution 合同、快照 payload 字段或用户明确批准解锁。
- 回滚方式：回退后续 snapshot pass-through 相关 research 变更；如曾发版，仅 `--no-deps` 替换 research-service；不触碰 source-data-service/source-data-worker/data-inspector/Postgres/model owner。
- 验证清单：requirements task_count=25；snapshot 任务无 source/upstream；research ready；scheduler catch-up dry-run 可选中槽位；非 dry-run 仅经 research execution 到 owner；owner snapshot append-only 增长；frontend compact 4 行可读。

## 落库表

SQL 文件：

```text
infra/sql/0026_research_model_payload_assembly_audit_v1.sql
infra/sql/0027_research_model_execution_audit_v1.sql
infra/sql/bootstrap_schema.sql
```

表：

```text
governance.research_model_payload_assembly_audit_v1
governance.research_model_execution_audit_v1
```

索引：

```text
idx_research_payload_assembly_task_day_v1
idx_research_payload_assembly_symbol_day_v1
idx_research_payload_assembly_status_v1
idx_research_payload_assembly_hash_v1
idx_research_model_execution_task_day_v1
idx_research_model_execution_owner_status_v1
idx_research_model_execution_symbol_day_v1
idx_research_model_execution_payload_hash_v1
```

## 下游消费

- `scheduler-service`：可通过 `POST /scheduler/model-payload/assemble-preflight` 显式调用本服务拿到真实 payload，并继续由 scheduler 执行 `scheduler_model_payload_preflight_v1`。该联调入口默认 `persist_audit=false`，不触达模型 owner；若本服务返回 `blocked_data_gap`，scheduler 必须保持 `dispatch_allowed=false`。
- `scheduler-service`：`scheduler_model_time_wheel_v1` 在 `SCHEDULER_MODEL_TIME_WHEEL_LIVE_DISPATCH=true` 时调用 `POST /research/model-execution/run`，不得直接调用 owner service；本服务返回 `accepted=false` 时，scheduler 必须记为 retry/failure 并阻断 readyz。
- 四个模型 owner service：只接收已组装业务 payload，评分和 release gate 仍由 owner 内部计算。
- `data-inspector-service`：后续可巡检 `blocked_data_gap` 和审计缺口。
- research-data-mart / gateway / frontend / Jarvis：后续只读消费或解释。

## 禁止反写

- 不直接调用 provider。
- 不读取 `raw_*` 或 `raw.*`。
- 不写 `source.*`。
- 不自行计算或改写模型分数、状态、release gate、official signal、买点、outcome、标签、交易或学习权重；只允许按 owner 返回的结构化事实 append-only 物化。
- 不让 sample payload、0、空字符串、mock 或 GPT 推断进入模型事实链。

## 验收

```bash
python -m py_compile services/research-service/src/research_service/*.py
python -m pytest -q services/research-service/tests
```

运行态验收：

```text
GET /readyz
GET /research/model-payload/requirements
POST /research/model-payload/assemble
POST /research/model-execution/run
```

## 2026-06-18 Execution Bridge Runtime Closure

用户本轮要求“继续闭环”后，`research-service` 与 `scheduler-service` 执行最小发布闭环：先应用 `infra/sql/0027_research_model_execution_audit_v1.sql`，再构建并 `--no-deps` 替换 `research-service`、`scheduler-service`。未重启、未替换 `source-data-service`、`source-data-worker`、`data-inspector-service`、Postgres 或任一模型 owner 服务。

发布与回滚：

```text
applied sql:
  infra/sql/0027_research_model_execution_audit_v1.sql
  sha256=05D782E6A7D63FD23EF797C1AEF69EFC280C357A7A0B25FFEB29E5CB5C86EC17

rollback tags:
  infra-research-service:rollback-20260618-execution-bridge-closure
  infra-scheduler-service:rollback-20260618-execution-bridge-closure

new images:
  infra-research-service@sha256:62d9d5798d78dea858eaff1f58ff1a0e02eca93c80220a0e70260bd220ab2693
  infra-scheduler-service@sha256:7b40e9e6c2f17fc0129d26587dc2f6b0934afd3fc13e092ef304fd33c1dd3eeb

new containers:
  ai-stock-research-service a2a5aa571c29 started_at=2026-06-18T07:07:11Z
  ai-stock-scheduler-service 7ce78da5adf2 started_at=2026-06-18T07:07:11Z
```

未替换对象：

```text
source-data-service 125b58ac7f9e started_at=2026-06-17T19:31:38Z
source-data-worker 0df61d50252b started_at=2026-06-17T19:31:44Z
data-inspector-service 0995dca891f7 started_at=2026-06-17T17:01:59Z
postgres af846a793868 started_at=2026-06-17T07:23:49Z
```

发布后验收：

```text
source-data-service /readyz -> ready
data-inspector-service /readyz -> ready
research-service /readyz -> ready, execution_audit_ready=true
scheduler-service /readyz -> ready, startup_guard run_id=2097, p0_gap_count=0, p1_gap_count=0
scheduler model_time_wheel dispatcher_version=scheduler_research_model_execution_dispatch_v1
/source/fetch/queues/summary -> queued_count=0, leased_count=0, dead_letter_count=0 across all queues
/scheduler/validate/docs-sync?project_root=. -> valid=true
/scheduler/validate/three-models -> valid=true
```

阻断型执行探针：

```text
POST /research/model-execution/run hot.release_gate.preopen
  execution_id=exec-closure-20260618150910
  execution_status=blocked_data_gap
  accepted=false
  dispatch_allowed=false
  owner_called=false
  materialization_attempted=false
  audit_persisted=true
  gap_codes=source_gap:decision_hot_hot_evidence_snapshot_missing,
            source_gap:decision_hot_hot_score_fact_missing,
            source_gap:source_preflight_not_passed
```

冻结对象：

| 服务 -> 模块 -> 功能 | 冻结时间 | 确认来源 | 锁定范围 | 允许的只读验收 | 禁止修改项 | 解锁条件 | 回滚方式 | 验证清单 |
|---|---|---|---|---|---|---|---|---|
| `research-service -> model-execution -> owner materialization bridge` | 2026-06-18 15:09 Asia/Shanghai | 用户“继续闭环” | `/research/model-execution/run`、`research_model_execution_v1`、`ModelOwnerClient`、`ResearchDecisionMaterializer`、`governance.research_model_execution_audit_v1`、blocked-before-owner 语义、owner 输出物化边界 | `/readyz`、`/research/model-payload/requirements`、阻断型 execution 探针、execution audit 只读查询 | 未获解锁不得绕过 source/preflight 缺口、不得在 blocked assembly 时调用 owner、不得由 research 计算分数或改写 official 结论、不得读取 raw/provider、不得用 0/sample/mock/GPT 补事实 | owner endpoint 合同变化、物化表合同变化、execution audit schema 变化、readyz 误判、或用户明确批准 | 重新标记 rollback 镜像为 latest 后 `docker compose -f infra/docker-compose.yml up -d --no-deps research-service scheduler-service`；不得触碰 source-data-service/data-inspector/Postgres | execution audit ready；blocked execution owner_called=false；audit persisted；scheduler dispatcher 指向 research execution；source/data-inspector ready |
| `research-service -> model-payload-assembler -> hot release upstream case-link reader` | 2026-06-19 20:40 Asia/Shanghai | 用户“继续，你决定是否可以拍板”，Codex 判定可拍板 | `hot.release_gate.preopen` 读取 `decision_hot.hot_score_fact_v1`、`decision_hot.hot_evidence_snapshot_v1` 时通过 `decision_hot.hot_decision_case_v1.hot_case_id` 按 `symbol + trade_date` 关联；`source_preflight_not_passed` 和上游硬阻断仍返回 `blocked_data_gap` | `/readyz`、`/research/model-payload/requirements`、`POST /research/model-payload/assemble` 且 `persist_audit=false`、`POST /scheduler/model-payload/assemble-preflight` 且不触达 owner、数据库只读计数 | 未获解锁不得改回通用 symbol/date 直查、不得绕过 `source-data-service /source/release/preflight`、不得在 `blocked_data_gap` 时生成 owner request preview、不得写 release audit 或 `hot_signal_fact_v1`、不得读取 raw/provider、不得用 0/sample/mock/GPT 补事实 | hot decision 表结构变化、release gate 上游合同变化、source preflight 口径变化、scheduler preflight 误判、或用户明确批准解锁 | 重新标记 `infra-research-service:rollback-20260619-hot-release-upstream` 为 latest 后 `docker compose -f infra/docker-compose.yml up -d --no-deps research-service`；不得触碰 source-data-service/source-data-worker/scheduler/data-inspector/Postgres/模型 owner | research/source/data-inspector/scheduler/hot owner ready；direct no-persist assemble 与 scheduler no-persist preflight 均读到 score `row_count=1`、evidence `row_count=8`；missing gap 消失；`gap_codes=[source_gap:source_preflight_not_passed]`；`dispatch_allowed=false`；`owner_request_body_preview=null`；`audit_persisted=false`；`hot_signal_fact_v1=0`；`hot_release_gate_audit_v1=0` |
| `research-service -> model-payload-assembler -> t_relay Day2 warning/assembly contract` | 2026-06-23 Asia/Shanghai | 用户批准解锁模型四 Day2 滚动监测调整 | `t_relay.day2.watch.rolling_5m`、`t_relay.day2.trigger.rolling_5m` 的 Day2 source/upstream 读取合同、`source_gap:seal_order_snapshot_missing` warning 语义、`source.limit_price_v1` / `source.minute_bar_v1` / `source.realtime_quote_v1` / `source.trade_tick_v1` 组装口径、Day1 candidate 与 Day2 watch snapshot 上游引用、no-persist assemble/preflight 验收口径 | `/readyz`、`/research/model-payload/requirements`、`POST /research/model-payload/assemble` 且 `persist_audit=false`、`POST /scheduler/model-payload/assemble-preflight` 且不触达 owner | 未获解锁不得把 Day1 `source_gap:seal_order_snapshot_missing` 升级为 Day2 硬阻断；不得丢弃 warning；不得用 0、空字符串、mock 或推断补齐动态特征 / 吸收分 / 封单快照；不得读取 `raw_*` / `raw.*` / provider；不得伪装 `source.trade_tick_v1` 为完整五档盘口；不得改写 owner 输出事实；`可买入观察` 只作为只读机会提示 | owner Day2 输入合同变化、source 标准层新增 canonical 封单快照、source/schema/provider 能力单独获批、或用户明确批准解锁 | 回退本轮 research-service 组装改动并仅 `--no-deps` 替换 research-service；不得触碰 source-data-service/source-data-worker/scheduler/data-inspector/Postgres/模型 owner | `source`、`data-inspector`、`research`、`scheduler` ready；direct no-persist assemble 与 scheduler no-persist preflight 均返回滚动监测字段；`warnings` 保留非硬阻断缺口；`gap_codes=[]`；`audit_persisted=false`；`monitor_check_time`、`first_qualified_monitor_time`、涨停价、涨停距离与逐笔聚合字段可见 |
| `research-service -> model-payload-assembler -> t_relay post-entry and Day3 observation payload` | 2026-06-24 Asia/Shanghai | 用户要求 Codex 决定是否拍板；Codex 判定可窄冻结已实测链路 | `t_relay.day2.post_entry.monitor`、`t_relay.day3.exit.open`、`t_relay.day3.exit.tail` 的只读 payload 组装边界；触发后用 `source.minute_bar_v1` 与 `source.limit_price_v1` 监测是否开板；Day3 仅锁定开盘/尾盘窗口和组装合同，不提前宣称自然窗口已完成 | `/readyz`、`POST /research/model-payload/assemble` 且 `persist_audit=false`、`POST /scheduler/model-payload/assemble-preflight`、owner observation-board 只读结果、前端 compact 只读结果 | 未获解锁不得把 post-entry/Day3 缺口补成 0、空字符串、mock 或推断；不得读取 raw/provider；不得由 research 生成交易、卖出、official signal 或前端展示事实；不得把 Day3 未自然验收写成完成结论 | source 标准层字段变化、owner post-entry/Day3 输入合同变化、Day3 自然窗口验收失败、或用户明确批准解锁 | 回退本轮 research-service 文档/组装相关后续变更并仅按需 `--no-deps` 替换 research-service；不触碰 source-data-service/source-data-worker/data-inspector/Postgres/模型 owner | 600172.SH no-persist 组装识别 `post_entry_board_opened=true`、首个开板时间 `09:43:00`、开板次数 `14`、涨停价 `16.95`；live execution 已物化 owner 行；research/scheduler/frontend 相关测试通过；Day3 自然窗口仍待后续只读验收 |
| `research-service -> hot model list -> data readiness projection` | 2026-06-27 Asia/Shanghai | 用户明确“拍板”，并要求“继续完成拍板” | `GET /research/model-list/hot` 的 `hot_model_data_readiness_v1` 只读投影合同、固定 13 个 P0/P1/P2 准备度维度、总权重 100、行级 `readiness_score_pct/missing_points/blocked_points/readiness_state/top_missing_dimension/readiness_gap_codes/readiness_dimensions`、列表级 `readiness_summary`、metadata-only 表结构缓存边界 | `/readyz`、`GET /research/model-list/hot?limit=20`、前端 compact `/api/model-list/hot?limit=20`、Playwright 只读页面验收、相关单测和编译检查 | 未获解锁不得改变 13 维权重、P0 阻断语义、缺口码、`NULL`/空态规则或 metadata-only 缓存边界；不得触发 owner/source fetch/provider/raw；不得由 research 改模型分、release gate、买点、official signal、交易、outcome 或学习权重；不得用 0、空字符串、mock、示例 payload 或 GPT 推断补事实 | 热点模型准备度维度/权重需求变化、source/decision 表合同变化、readiness 性能需进一步物化或批量化、前端展示合同变化、或用户明确批准解锁 | 回退本冻结对象对应 research-service 代码/测试/README/DATA_ASSETS 变更，并按需使用 `infra-research-service:rollback-20260627-hot-readiness` 或后续镜像回滚；不得触碰 source-data-service/source-data-worker/scheduler/data-inspector/Postgres/模型 owner | `GET /research/model-list/hot?limit=20` 返回 `contract_kind=research_hot_model_list_v1`、`readiness_contract=hot_model_data_readiness_v1`、`readiness_weight_total=100`、13 个维度、20 条真实行、平均准备度 `51.2%`；首行 `600367.SH` 准备度 `59`、状态 `blocked`、缺 `41` 分、最大缺口 `auction_confirmation`；frontend/research/hot owner/scheduler/data-inspector/source 健康 |
