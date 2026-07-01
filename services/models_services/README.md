# models_services README

本文件是 `services/models_services` 目录唯一当前 MD，也是模型服务集合层事实源。全局硬约束以项目根目录 `AGENTS.md` 为准；各模型子服务的细节事实源分别以各自目录 `README.md` 为准。

模型服务集合层数据资产账本见 `services/models_services/DATA_ASSETS.md`；各模型子服务的数据资产账本见对应目录 `DATA_ASSETS.md`。

## 当前服务

| 服务 | 端口 | 当前版本 | 定位 |
|---|---:|---|---|
| `hot-candidates-service` | `8031` | `hot_candidates_v1` 兼容评分；`hot_candidates_v2_lifecycle` 生产阶段合同 | 消费 `source.ths_paid_limit_up_probability_v1` 的同花顺付费次日概率教师先验，识别 T+1/T+5/T+20 短窗口兑现机会 |
| `candidate-memory-service` | `8032` | `candidate_memory_v1` | 历史热点候选记忆，识别延迟兑现、二波、慢趋势和失效风险 |
| `ambush-watchlist-service` | `8033` | `ambush_watchlist_effective_turn_v1_1`；Phase2/3/4 分阶段版本 | 深圳 A 股低位潜伏抬头 / 龙抬头结构扫描 |
| `t-board-relay-service` | 容器 `8034` / 宿主默认 `8035` | `t_board_relay_v1` | T 字板主导资金博弈，识别 Day1 T 字板、Day2 开盘后 5 分钟滚动接力触发、买入后封板维护和 Day3 去留 |

模型四当前集合层合同：Day2 未触发前由 `t_board_day2_watch_snapshot_v1` 五分钟滚动事实驱动普通用户观察台；触发确认以“买盘主动扫掉卖盘”为主，卖盘主动砸向买盘是风险 / 失效条件；触发后封板维护按开盘时段每 5 分钟留存至收盘；`observation-board` 同步输出 `model_score`、`model_score_label`、`score_state` 和 `model_score_version=t_board_relay_observation_score_v1`，由模型四 owner 基于阶段事实综合计算，缺关键事实时保持 `model_score=NULL`，不补 0；Day2 10:30 后缺有效五分钟事实时必须落 `data_wait`，不得继续显示观察中；`t_relay.observation.monitor.snapshot_5m` 每 5 分钟通过 `POST /t-board-relay/observation-monitor/snapshot` 留存 `projection_snapshot_5m`，只作为观察投影留痕和恢复审计，不覆盖真实阶段事实时间；`t_relay.live_result.compute_30m` 每 30 分钟留存 `model_result_30m`，写入 `model_evaluated_at/last_model_output_at`，二者都 append-only 写入 `decision_t_relay.t_board_observation_monitor_snapshot_v1`；前端只读消费 `observation-board` 投影和模型分降序，`更新` 列必须同时展示最后一次模型产出时间 `last_model_output_at/model_evaluated_at` 与最新真实抓取/阶段事实时间 `latest_data_fetch_at/last_data_captured_at`，`latest_projection_snapshot_at` 仅作审计，不得冒充真实抓取时间，前端不生成、不修改模型事实。

2026-07-01 用户回复“允许”后，模型四集合层双时间合同进入拍板冻结：5 分钟 `projection_snapshot_5m` 只能证明观察台投影链路仍在运行，30 分钟 `model_result_30m` 才能推动 `last_model_output_at/model_evaluated_at`，真实抓取 / 阶段事实时间只能来自 owner 阶段事实。未经解锁不得合并三类时间，不得把投影时间显示成抓取时间或模型产出时间，不得移除 `t_relay.live_result.compute_30m`，不得让前端、research、scheduler 或 Jarvis 补写模型四事实。

模型服务均是 owner service：只接收已组装 payload，执行模型合同计算并返回结构化结果；不直接并发调用 BaoStock、AKShare、Tencent、Tushare、EastMoney、Baidu、CNINFO 等 provider；不直接读取 `raw_*`；不直接修改前端、Jarvis、交易、学习权重或人工状态。

## 当前代码事实

当前仓库本体包含：

- `services/models_services/*` 模型 owner service。
- `services/source-data-service` 数据源服务和 worker。
- `services/scheduler-service` 调度服务。
- `packages/db-schema` SQL bootstrap 工具。

当前仓库本体已包含 `services/data-inspector-service` 源码目录，用于按新 source/preflight/lineage、模型 ready 和 scheduler ready 重新设计的数据巡检、缺口审计和 remediation task；也已包含独立 `services/research-service`，用于按 `research_model_payload_assembler_v1` 从已构建 `source.*` 和允许的上游模型事实组装 owner payload 或返回 `blocked_data_gap`。当前仓库本体仍不包含 `research-data-mart`、`gateway-service`、`execution-timing-service`、`dynamic-feature-service` 源码目录。`AGENTS.md` 中的主链路仍是业务目标；在本仓库当前闭环里，scheduler 负责已接入模型的 time wheel、preflight gate 和 dispatch 守卫，source-data-service 负责 source preflight，research-service 负责 payload assembly，data-inspector-service 负责巡检缺口审计，模型 owner service 负责模型阶段合同输出。正式 data mart 同步、买点版本链、动态特征服务和前端展示由对应下游服务或后续接入承担，不能在本目录 README 中伪装成当前已由本仓库源码完成。

## 跨服务数据流

当前最小闭环：

```text
source-data-service provider probe / raw ingest / source build / lineage
-> /source/release/preflight
-> scheduler-service task plan / live dispatch
-> 已接入模型 owner service API
-> owner service structured_output / contract_gaps / jarvis_payload
```

目标生产主线：

```text
provider / market / candidate facts
-> source-data-service raw/source/lineage
-> research-service 组装真实输入并持久化模型事实
-> 模型服务评分和 release gate
-> research-data-mart / data-inspector / scheduler / execution-timing / gateway / frontend / Jarvis 只读消费或调度
```

当前验收不能用 scheduler sample payload 代替市场事实。sample 只用于请求体包装和 owner API 连通性验证；生产 payload 必须由 `research-service` 标记 `payload_assembly_contract=research_model_payload_assembler_v1` 和 `payload_assembly_status=assembled_research_payload`，official signal 还必须同时满足模型 release gate 和 `source-data-service /source/release/preflight`。模型四 `t_board_relay` 已接入 scheduler live dispatch、`decision_t_relay` / `research_t_relay` schema、Postgres repository 和 data-inspector 巡检域，但它仍是研究模型，所有 `t_relay.*` 调度任务均 `is_official_publish=false`，不得误读为官方交易信号。

## 统一 API 合同

所有 owner service 均提供：

```text
GET /health
GET /healthz
GET /readyz
```

统一响应主体包含：

```json
{
  "model_name": "hot_candidates|candidate_memory|ambush_watchlist|t_board_relay",
  "model_version": "string",
  "structured_output": {},
  "jarvis_payload": {},
  "contract_gaps": []
}
```

`contract_gaps` 是事实，不是错误吞噬区。缺真实数据、缺 `available_at`、未来数据、模型阶段阻断和异常兜底必须保留缺口码、阻断状态或 warning，不得用 0、空字符串、mock 或推断补齐。

## 调度合同

调度服务代码入口：

- `services/scheduler-service/src/scheduler_service/hot_plan.py`
- `services/scheduler-service/src/scheduler_service/three_model_plan.py`
- `services/scheduler-service/src/scheduler_service/three_model_dispatch.py`
- `services/scheduler-service/src/scheduler_service/runtime.py`

关键 API：

- `GET /scheduler/plan/three-models`
- `GET /scheduler/validate/three-models`
- `GET /scheduler/materialize/three-models`
- `GET /scheduler/live-dispatch/sample/{task_code}`
- `GET /scheduler/validate/live-dispatch-samples`
- `POST /scheduler/trigger`

`POST /scheduler/trigger` 默认 `dry_run=true`。非 dry-run 必须显式传入 `owner_endpoints`，scheduler 只以 owner service 的真实 2xx 响应作为 `accepted=true`，不得伪造成功。

官方发布任务只有三条：

| task_code | owner | endpoint |
|---|---|---|
| `hot.release_gate.preopen` | `hot-candidates-service` | `POST /production/release-gate/evaluate` |
| `memory.release_gate.close` | `candidate-memory-service` | `POST /production/release-gate/evaluate` |
| `ambush.phase3.release_gate.close` | `ambush-watchlist-service` | `POST /ambush/phase3/run` |

模型四调度已写入 `scheduler-service`，全部为 non-official 研究 / 模型阶段任务：

| task_code | owner | endpoint |
|---|---|---|
| `t_relay.day1.scan.close` | `t-board-relay-service` | `POST /t-board-relay/day1/scan` |
| `t_relay.day2.watch.rolling_5m` | `t-board-relay-service` | `POST /t-board-relay/day2/watch` |
| `t_relay.day2.trigger.rolling_5m` | `t-board-relay-service` | `POST /t-board-relay/day2/trigger-check` |
| `t_relay.day2.post_entry.monitor` | `t-board-relay-service` | `POST /t-board-relay/post-entry/monitor` |
| `t_relay.day3.exit.open` | `t-board-relay-service` | `POST /t-board-relay/day3/exit-check` |
| `t_relay.day3.exit.tail` | `t-board-relay-service` | `POST /t-board-relay/day3/exit-check` |
| `t_relay.observation.monitor.snapshot_5m` | `t-board-relay-service` | `POST /t-board-relay/observation-monitor/snapshot` |
| `t_relay.live_result.compute_30m` | `t-board-relay-service` | `POST /t-board-relay/observation-monitor/snapshot` |
| `t_relay.outcome.build` | `t-board-relay-service` | `POST /t-board-relay/outcomes/build` |

## 调度时间

- 热点：竞价冻结 `09:25:05,09:25:30`；盘前评分 `09:26:00,09:28:00,09:29:30`；release gate 截止 `09:30:00`；开盘 5 分钟买点 `09:30-09:36`；盘中观察 `09:30-15:00`；T+5/T+20 outcome 和离线 evolution 在收盘后。
- 候选记忆：seed/entity 在热点成熟样本后；pre-signal 扫描 `15:55` 及可选 `10:30` 研究扫描；release gate `16:05`；outcome/evolution 每日收盘后及 T+5/T+20/T+40。
- 潜伏抬头：source capability 周期审计；图库离线挖掘；Phase2 收盘后 `15:20`；Phase3 release gate `15:35`；观察/outcome/evolution `15:55` 及成熟窗口。
- T 字板接力：Day1 先在 `10:40/14:55/15:02/15:10` 通过 THS 公开涨停池构建 `source.limit_event_v1`，再于 `15:12/15:20/15:30/15:35/15:45` 只对 T 字板阶段候选补交易状态、日线、涨跌停价和流通市值；owner 在 `15:05-15:30` 评估候选 T 字板和封单比例；Day2 `09:25` 预加载、`09:30-10:30` 每 5 分钟滚动观察，首次接近涨停后进入盘口确认，仅 `order_consumption_side=ASK` 且 `order_consumption_amount>0` 表示卖盘被主动买盘扫掉并触发接力机会提示，`BID` 表示主动卖出打买盘并作为风险 / 失效条件，方向或金额缺失时等待确认或 `data_blocked`；触发后到 `15:00` 封板维护监控；观察台 `09:30-15:00` 每 5 分钟留存投影快照，并在 `09:32-15:02` 每 30 分钟留存模型结果快照；Day3 `09:25-09:35` 开盘涨停去留、`14:40-14:55` 尾盘未涨停退出研究事件。

非临时 source 高频窗口已由 `scheduler-service` 的 `source_fetch_schedule_registry_v1` 和 `scheduler_source_time_wheel_v1` 承担，到点只提交 `source-data-service /source/fetch/submit`，真实 provider 并发仍由 source-data-worker 控制。模型三可以使用全 A 日频/日线底座做市场扫描；模型四 Day1 不做全 A 高频/报价盲扫，而是先读 `source.limit_event_v1` 的涨停池/T 字板候选，再候选级补 P0 事实。模型 owner 任务仍只接收已组装业务 payload；`research-service` 负责组装，scheduler 负责任务定义、交易日实例化、dry-run、source time wheel、payload preflight 和已接入模型 live dispatch，不伪造模型输入或模型事实。模型四已定向接入 scheduler，但保持 non-official，不反写前三模型。

## source preflight

模型服务 release gate / official 动作前必须调用：

```text
POST /source/release/preflight
```

preflight 必须同时检查模型 source 覆盖度、freshness、P0 字段、quality_status、lineage 和 `available_at`。返回 `can_release_official_signal=false` 时禁止发布 official signal。P1 degraded 可作为非阻断风险保留，但不得在界面或报告中伪装成完整覆盖。

`source.event_news_v1` 当前由 source-data-service 以 Baidu Finance `finance_news_feed` 为 research-only 主源、CNINFO 为备源登记，字段包括 `title/published_at/available_at/event_type/url`。事件新闻只作为 ex-ante 证据上下文和审计材料，缺失时保留缺口码或空态，不得把 provider feed 直接当模型事实，也不得绕过 source build、quality_status、lineage 和 available_at 校验。该源当前不是 P0 official release hard gate。

模型四 P0 需要 `source.daily_bar_v1`、`source.limit_price_v1`、`source.limit_event_v1`、`source.trade_status_v1`、`source.realtime_quote_v1.float_market_cap`、`source.minute_bar_v1`、`source.trade_tick_v1` 和动态特征 bundle `t_board_relay_intraday_bundle_v1` 等事实。2026-06-14 已用 `000759.SZ / 2026-06-12` 真实 source 标准层完成 `t_board_relay/day1_scan` 与 `t_board_relay/day2_trigger` preflight，二者均 `can_release_official_signal=true`、coverage/freshness passed、blocking_reasons=[]。当前 owner service 只接收这些事实作为输入合同；`decision_t_relay` / `research_t_relay` schema、owner repository、scheduler non-official live dispatch 和 data-inspector 模型四巡检域已接入。当前仍未落地独立 `dynamic-feature-service` 源码，缺 `t_board_relay_intraday_bundle_v1` 时必须保留缺口码，不得补 0、mock 或推断值。

## 当前持久化口径

当前 SQL 文件包含三类合同：

- 目标独立域合同：`infra/sql/0002_source_decision_hot_refactor.sql`、`0003~0007`、`0008~0010` 定义 `decision_hot.*`、`decision_memory.*`、`decision_ambush.*` 等目标表。
- 当前 bootstrap 基线：`infra/sql/bootstrap_schema.sql` 是当前运行容器和 schema-bootstrap 的实际基线输出。
- 当前 Alembic 入口：`packages/db-schema/alembic/versions/0001_current_baseline.py` 委托执行 `infra/sql/*.sql`，使 AGENTS 约定的基线文件真实存在。

如果 `bootstrap_schema.sql` 与分阶段 SQL 文件出现差异，运行事实以当前容器、当前代码和 `bootstrap_schema.sql` 为准；差异必须在下一轮 schema 同步中修正，不能靠 README 声称已经落库。

## 验收入口

核心闭环验收：

```bash
python scripts/core_services_acceptance.py --require-postgres
```

最高规格数据质量验收可追加：

```bash
python scripts/core_services_acceptance.py --require-postgres --source-quality-matrix
python scripts/core_services_acceptance.py --require-postgres --real-provider-probe
```

数据源生产拍板还必须执行：

```bash
python scripts/source_data_acceptance.py --require-postgres
```

上述脚本返回 0 代表当前最小闭环服务合同调通；不代表 scheduler 写入了官方信号，也不代表当前仓库已包含 data-mart/gateway/execution-timing 的完整源码闭环。`research-service` 当前只负责 payload assembly 和审计，不替代 research-data-mart、execution-timing 或模型 owner 的评分/发布职责。

## 禁止反写

- scheduler 不写模型事实、分数、状态、标签、发布闸门、买点版本或学习权重。
- gateway/frontend/Jarvis/explanation 只读展示、解释、翻译或提醒。
- 模型 owner service 不直接并发抓取 provider，不直接读取 raw，不跳过 source preflight，不把 sample payload 当 source 事实。
- 缺失真实数据必须保留 `NULL`、缺口码、阻断状态、warning 或空态。

## 当前闭环结论

当前已锁定三模型 owner service、模型四 owner service、source-data-service、source-data-worker、data-inspector-service 和 scheduler-service 已具备最小 Docker/Postgres/source preflight/live dispatch/inspection 闭环。2026-06-14 本地运行容器完成 `000063.SZ + 000759.SZ / 2026-06-12` 真实复核：`source.trade_status_v1`、`source.adjusted_daily_bar_v1`、`source.stock_moneyflow_daily_v1` 对 000759 补齐 raw/source/lineage 后，`hot_candidates.preopen_release_gate`、`candidate_memory.outcome_label`、`ambush_watchlist.release_gate` 均 `can_release_official_signal=true`、coverage/freshness passed、blocking_reasons=[]、degraded_reasons=[]；`t_board_relay/day1_scan` 与 `t_board_relay/day2_trigger` preflight 也已 passed；`data-inspector-service` `startup_guard/core_closure` 均 ready、gap 0；`scheduler-service /readyz` closure_guard ready；`/source/fetch/queues/summary` 全队列 queued/leased/dead-letter 均为 0。`python scripts/source_data_acceptance.py --require-postgres --real-provider-probe --probe-limit 0 --quality-matrix` 返回 0；`python scripts/source_data_quality_matrix.py --symbol 000063.SZ,000001.SZ,600000.SH,000759.SZ --trade-date 2026-06-12 --table daily --table adjusted` 返回 0；`python scripts/core_services_acceptance.py --require-postgres --real-provider-probe --source-quality-matrix --source-quality-symbol 000063.SZ,000001.SZ,600000.SH,000759.SZ --source-quality-trade-date 2026-06-12` 返回 0。2026-06-17 后续 scheduler 定向解锁已新增非临时 source 调度注册、source time wheel 和临时取数转交入口，所有 source fetch 仍只进入 source-data-service orchestration。Baidu Finance 事件新闻保持 research-only，probe 出参必须是 `usable_for_model_online=false`、`usable_for_research_only=true`，不改变 official release gate。模型四 `t-board-relay-service` 当前已落地独立 owner service、Day1/Day2/Day3 状态机、Postgres append-only repository、`decision_t_relay` / `research_t_relay` schema、scheduler non-official live dispatch 和 data-inspector 巡检域；动态特征服务源码仍未落地，相关缺口不阻断当前 Day1/Day2 source、调度、repository 和巡检闭环。当前未阻断项记录在根目录 `需优化点.MD`，其中包括 AKShare/EastMoney research-only 恢复、指数成交量口径归一、P1 资金流扩大样本与多源口径校准、Baidu 事件新闻覆盖率/分类质量扩样、模型四动态特征服务独立化等。
