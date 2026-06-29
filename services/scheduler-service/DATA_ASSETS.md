# scheduler-service DATA_ASSETS

本文件是 `scheduler-service` 的数据资产账本，不替代本目录 `README.md`。

## 服务定位

`scheduler-service` 负责任务定义、非临时 source 调度注册、source time wheel、交易日实例化、startup/current_closure 守卫、dry-run 和 live dispatch 编排。模型任务时间轮的正式 live dispatch 只调用 `research-service /research/model-execution/run`，不直连 owner endpoint。它不采 provider、不读 raw、不写模型事实、不修改 release gate、买点、outcome 或学习权重。

## 读取数据

| 资产 | 用途 | 边界 |
|---|---|---|
| `source-data-service /readyz` | source 服务健康 | 只读 |
| `/source/ops/production-readiness` | source 拍板门禁 | 只读 |
| `/source/fetch/queues/summary` | 队列阻断 | 只读 |
| `/source/fetch/plan`、`/source/fetch/submit` | 非临时和临时 source fetch orchestration | scheduler 只提交合同体，provider 并发由 source-data-worker 控制 |
| `/source/ths/paid-probability/fetch-current-batch`、`/source/ths/paid-probability/deadline-check` | 同花顺付费概率批次抓取和截止守卫 | scheduler 只调 source-data-service 受控端点，不接触 Cookie、provider 参数或 THS 响应 |
| `POST /scheduler/source-schedule/catch-up` | 非临时 source schedule 正式追补/对账入口 | 只复用 `source_fetch_schedule_registry_v1` 物化实例和本地 task store；默认 dry-run，不属于 temporary fetch |
| `POST /scheduler/task-store/archive-obsolete-source-dead-letters` | 本地旧合同 dead-letter 审计归档 | 默认 dry-run；只允许把已被当前调度/source 合同替代的旧 source schedule dead-letter 标记为 `obsolete_contract_replaced`，不得删除 `task_dead_letter_v1`，不得写 source/raw/lineage |
| `/source/release/preflight` | 三模型 official 和模型四 Day1/Day2 source 门禁 | 只读 |
| `data-inspector-service /readyz`、`POST /inspection-runs` | startup_guard 和 core_closure | 只读触发巡检审计 |
| required 模型 owner `/readyz` | readyz/core closure 守卫 | 由 `SCHEDULER_REQUIRED_MODEL_SERVICES` 显式声明；disabled owner 只写 `disabled_by_policy` 审计，不打 DNS。 |
| `research-service /research/model-execution/run` | 模型任务时间轮正式 live dispatch | research-service 负责 owner 调用、物化和 execution audit；scheduler 只按 accepted/blocked/failure 更新本地 task store |
| 四个模型 owner endpoint | 显式 trigger/sample 合同和 research-service 执行依赖 | scheduler model time wheel 不直连；owner 2xx 不等于 official signal 成功 |

热点模型调度资产边界：`hot.score.auction_confirmed`、`hot.release_gate.preopen`、`hot.buy_point.open_5m` 的生产候选池不由 scheduler 读取或回退。scheduler 只保存时间槽、`_scheduler_materialized_instance`、run slot、catch-up 审计和本地 task store 状态；真实候选 fanout 由 `research-service` 根据 `source.ths_paid_limit_up_probability_v1` 或 `decision_hot.hot_decision_case_v1 + decision_hot.hot_score_fact_v1` 决定。`SCHEDULER_GUARD_SYMBOL`、sample symbol、`000063.SZ` 或单个 catch-up 请求 symbol 均不得成为热点 release/buy-point 的生产候选事实。

## 写入/目标治理表

| 表 | 作用 | 当前边界 |
|---|---|---|
| `governance.owner_endpoint_registry_v1` | owner endpoint 合同 | schema 合同 |
| `governance.task_definition_registry_v1` | 任务定义 | schema 合同 |
| `governance.task_materialization_audit_v1` | 交易日实例化审计 | schema 合同 |
| `governance.scheduler_docs_sync_audit_v1` | 文档同步审计 | schema 合同 |
| `ai_stock_scheduler_task_store.sqlite3::task_instance_v1` | scheduler 本地非临时 source time wheel 与 model time wheel 任务实例、幂等键和状态 | 默认位于系统临时目录；source fetch 真实生产队列仍以 source-data-service Postgres queue 为准；模型业务事实以 research-service 物化的 owner 输出和 owner repository 写入为准 |
| `ai_stock_scheduler_task_store.sqlite3::task_lease_v1` | scheduler 本地 lease | 防止同一 scheduler 进程重复提交同一 source/model 窗口任务 |
| `ai_stock_scheduler_task_store.sqlite3::task_dead_letter_v1` | scheduler 本地 dead-letter | 记录 source fetch submit 或 model owner dispatch 多次失败的调度任务 |
| `ai_stock_scheduler_task_store.sqlite3::task_run_log_v1` | scheduler 本地运行日志 | 记录 lease、success、failure 事件 |

当前 runtime 对 source time wheel 和 `scheduler_model_time_wheel_v1` 使用本地 task store 审计。source fetch 的生产事实只以 source-data-service Postgres queue、raw/source/lineage 为准；模型事实只以 research-service 物化的 owner 输出、owner repository 写入和对应 decision/research 表为准；不得声明模型事实已由 scheduler 落库。热点 buy-point 的 `blocked` / `confirmed` 状态、`reference_entry_price`、`block_reason` 和 research-only/official signal flags 均来自 owner 经 research-service 物化，scheduler 不生成、不覆盖、不补 0/mock/推断。

## Current Closure / Source Submit Guard Assets

| Asset | Rule | Read/write boundary |
|---|---|---|
| `/source/release/preflight` | `current_closure` sends official decision times: hot preopen `09:29:40`, candidate memory close `16:05:00`, ambush close `16:05:00`, t-board Day1 `15:10:00`, t-board Day2 rolling window start `09:30:00`, all in `Asia/Shanghai`. | scheduler is read-only; source-data-service decides coverage/freshness and official-release blocking. |
| `checks.closure_guard.details.preflight.*.decision_time` | Runtime status must expose the exact preflight time used for each model phase. | Operators can audit why readyz is blocked without guessing the decision-time visibility window. |
| `checks.closure_guard.details.preflight.*.historical_late_observed` | When `SCHEDULER_GUARD_TRADE_DATE` is earlier than the current market date, coverage is `passed`, and every source preflight blocker ends with `:late`, scheduler may mark the blocker `ignored_for_readyz=true`. | The original source preflight remains blocked (`can_release_official_signal=false`); this only prevents historical backfill visibility from making the scheduler service not_ready. |
| `checks.closure_guard.details.preflight.*.ignored_for_readyz` | Only valid for historical guard dates with late-only blockers after source rows now exist. | `missing`, `stale`, coverage blocked, current/live guard-date late, model payload preflight, owner dispatch, and official release gates must still block. |
| `SCHEDULER_REQUIRED_MODEL_SERVICES` | Staged model availability policy. Code default is `all`; current hot-model recovery plus Model 4 continuous-monitoring Compose default is `hot_candidates,t_board_relay`. Allowed values include `all`, `none`, model codes, owner service names, and aliases such as `hot` / `hot_candidates` / `t_board_relay` / `model4`. | Disabled models are reported as `disabled_by_policy` and are not probed through DNS. Required model readyz failures still block `/readyz`. With the current Compose default, hot candidates and Model 4 owners are required; source readiness, queues, startup_guard and source release preflight remain hard gates. |
| `checks.closure_guard.details.model_availability_policy` | Exposes required/disabled model codes and owner services. | Audit-only runtime evidence; it does not mark any model output successful. |
| `scheduler_source_time_wheel_v1` submit result | `/source/fetch/submit` 2xx is recorded as `source_result_status=submit_accepted_pending_source_build`. | scheduler does not declare source rows, raw rows or lineage produced; source-data-service build/preflight remains authoritative. |
| `scheduler_source_schedule_catch_up_v1` | Missed non-temporary windows are reconciled by materializing registry instances and preserving the original schedule `biz_key` / `idempotency_key`; `force_resubmit=true` appends `:catchup:<run_id>` only after source row/build/lineage reconciliation proves old success did not produce facts. | Dry-run writes nothing; non-dry-run writes scheduler local task rows and may dispatch only to source-data-service controlled endpoints. |
| `ai_stock_scheduler_task_store.sqlite3::task_run_log_v1` | Source submit success/failure is local scheduler audit only. | Production source facts still live in Postgres queue/raw/source/lineage under source-data-service. |

## Source 数据调度

- 一次性：交易日历使用 `symbol_scope=none`，股票主数据/provider symbol map 使用 `symbol_scope=full_a_share`，均经 `/source/fetch/plan` 和 `/source/fetch/submit`。
- 日调度：盘前 universe/交易状态/涨跌停价、收盘日线/前复权/涨跌停事件/资金流使用 `symbol_scope=full_a_share`；`SCHEDULER_SOURCE_TIME_WHEEL_SYMBOLS` 不得污染这些全 A 调度。
- 分钟级：竞价、报价、分钟线使用 `symbol_scope=configured_symbols`，只抓 release/window 必要小集合。
- 窗口级：模型四 Day1 先用 `source.limit_event_v1` 涨停池/T 字板事件生成阶段候选，再对候选补 `source.trade_status_v1`、`source.daily_bar_v1`、`source.limit_price_v1` 和 `source.realtime_quote_v1.float_market_cap`；09:30-10:30 Day2 五分钟滚动监测使用显式模型阶段候选。
- 巡检触发：P0/P1 缺口走 `/source/gaps/diagnose`、`/source/gaps/repair-plan`、`/source/fetch/submit`。
- 调度追补：常驻 source time wheel 不自动追发过期窗口；发布滞后、漏提或缺口定位后，必须用 `POST /scheduler/source-schedule/catch-up` 复用正式 registry 实例筛选追补，默认 `dry_run=true`，非 dry-run 仍只转交 source-data-service fetch orchestration。

当前 scheduler 代码中所有 `source.*` 采集任务 owner 必须是 `source-data-service`，且非 dry-run 只能提交 `/source/fetch/submit` 合同体；`reads_from` 只允许记录 `source-data-service:/source/fetch/plan`、`source-data-service:/source/fetch/submit` 或已构建的 `source.*`，禁止出现 `provider.*` 或 `raw_*`。

`source_fetch_schedule_registry_v1` 是非临时 source 调度资产清单，当前注册 20 条 schedule。`symbol_scope=full_a_share` 物化时写入 `symbols=[]` 和 `universe_scope=full_a_share`，由 source-data-service 从 `source.stock_universe_daily_v1` / `source.stock_master_v1` 展开；`symbol_scope=configured_symbols` 物化为 `universe_scope=explicit_symbols`；`symbol_scope=stage_candidates` 优先接收上游阶段专用候选并物化为 `universe_scope=stage_candidates`，人工验收或定向补跑可显式传入 `explicit_model_stage_candidates`，缺候选时跳过，不继承配置样本；`symbol_scope=none` 不携带股票集合。

| 调度组 | 资产 | 频率 | symbol_scope | universe_scope | 目标接口 |
|---|---|---|---|---|---|
| `one_time_initial` | `source.trade_calendar_v1`、`source.stock_master_v1` | 首次上线/季度补齐 | `none` / `full_a_share` | `explicit_symbols` / `full_a_share` | `/source/fetch/submit` |
| `daily_preopen` | `source.stock_universe_daily_v1`、`source.trade_status_v1`、`source.limit_price_v1` | 每日 09:05-09:12 | `full_a_share` | `full_a_share` | `/source/fetch/submit` |
| `daily_close_paid_probability` | `source.ths_paid_limit_up_probability_v1` | 每日 15:20、16:05、18:00、20:30 | `none` | `explicit_symbols` | `/source/ths/paid-probability/fetch-current-batch` |
| `daily_preopen_paid_probability_guard` | `governance.ths_paid_probability_batch_status_v1` | 每日 09:01；检查下一交易日 09:00 后仍未补齐的候选批次 | `none` | `explicit_symbols` | `/source/ths/paid-probability/deadline-check` |
| `daily_close` | `source.daily_bar_v1`、`source.adjusted_daily_bar_v1` | 每日 15:35-15:45 | `full_a_share` | `full_a_share` | `/source/fetch/submit` |
| `daily_research_context` | `source.stock_moneyflow_daily_v1`、`source.event_news_v1` | 每日 16:15-16:30 | `full_a_share` / `none` | `full_a_share` / `explicit_symbols` | `/source/fetch/submit` |
| `minute_auction` | `source.auction_snapshot_v1` | 09:15-09:25 每 30 秒 | `configured_symbols` | `explicit_symbols` | `/source/fetch/submit` |
| `minute_intraday` | `source.realtime_quote_v1`、`source.minute_bar_v1` | 09:30-15:00 每 60 秒 | `configured_symbols` | `explicit_symbols` | `/source/fetch/submit` |
| `t_relay_day1_window` | `source.limit_event_v1` | 10:40、14:55、15:02、15:10 | `full_a_share` | `full_a_share` | `/source/fetch/submit` |
| `t_relay_day1_candidate_facts` | `source.trade_status_v1`、`source.daily_bar_v1`、`source.limit_price_v1`、`source.realtime_quote_v1` | 15:12、15:20、15:30、15:35、15:45 | `stage_candidates`，候选源 `t_relay_limit_event_t_board` | `stage_candidates` | `/source/fetch/submit` |
| `t_relay_day2_window` | `source.trade_tick_v1` | 09:30-10:30 每 5 分钟 | `stage_candidates` | `stage_candidates` | `/source/fetch/submit` |

`POST /scheduler/source-fetch/temporary` 是临时取数入口。它不进入上述非临时注册表，默认 dry-run，只允许转交 source-data-service fetch orchestration，禁止使用 `trigger_type=scheduled_periodic`。

`POST /scheduler/source-schedule/catch-up` 是非临时调度追补入口。它按交易日从 `source_fetch_schedule_registry_v1` 物化实例，并可按 `schedule_codes`、`schedule_groups`、`source_table_names`、`run_slots`、`include_one_time` 筛选；非 dry-run 入队时默认复用原始 `biz_key`、`scheduled_at`、`idempotency_key` 和 request body。`dispatch_immediately=true` 只派发本次入队的 due source task。若本地 task 已 success 但 source 表、build 或 lineage 仍缺失，必须显式传 `force_resubmit=true` 和 `catch_up_run_id`，生成带 `:catchup:<run_id>` 后缀的新 scheduler/source 幂等键，作为对账修复审计。THS 付费概率 fetch 与 deadline guard 默认排除，必须显式允许才可进入追补选择，避免历史付费批次误触发。

`POST /scheduler/task-store/archive-obsolete-source-dead-letters` 是本地 task store 维护入口，不是补数据入口。它只匹配旧合同已经被当前 registry/source requirements 替代的 source dead-letter，例如旧 `source.minute.auction_snapshot` 请求字段 `price/volume/amount/captured_at/provider_definition` 被当前 canonical 字段 `virtual_open_price/matched_volume/matched_amount/event_time` 替代时，可把旧 task instance 标记为 `obsolete_contract_replaced` 并写入 `task_run_log_v1`。该操作必须保留 `task_dead_letter_v1` 原始审计；真实 source 补齐仍必须后续通过 `source-schedule/catch-up` 和 source-data-service fetch orchestration 完成。

当前 `source_fetch_schedule_registry_v1` 必须覆盖 `research_model_payload_assembler_v1` 的 13 张 required source 表；`source.limit_price_v1`、`source.limit_event_v1`、`source.realtime_quote_v1.float_market_cap` 和 `source.ths_paid_limit_up_probability_v1` 是 P0 非临时调度资产。模型四 Day1 候选事实由 `t_relay_day1_candidate_facts` 覆盖，缺失时 validator、payload assemble-preflight 或 source preflight 必须返回缺口并阻断派发，不得用样本、0 或推断补齐。

## 模型任务调度资产

模型四当前实例化资产：
- `three_model_materializer_v1` 对 `t_relay.day2.post_entry.monitor` 生成 Day2 开盘时段 `09:35-11:30`、`13:00-15:00` 每 5 分钟的本地调度实例。
- `three_model_materializer_v1` 对 `t_relay.observation.monitor.snapshot_5m` 生成 `09:30-11:30`、`13:00-15:00` 每 5 分钟的本地调度实例，owner 端点为 `POST /t-board-relay/observation-monitor/snapshot`，业务写入表为 `decision_t_relay.t_board_observation_monitor_snapshot_v1`。
- 这些实例只进入 scheduler 本地 task store / research execution 调度审计；封板维护事实仍由 `t-board-relay-service` 写入 `decision_t_relay.t_board_post_entry_monitor_v1`，观察台快照事实仍由 `t-board-relay-service` 写入 `decision_t_relay.t_board_observation_monitor_snapshot_v1`。
- `t_relay.day2.watch.rolling_5m` 与 `t_relay.day2.trigger.rolling_5m` 仍保持 `09:30-10:30` 每 5 分钟，避免把触发前观察和触发后封板维护混成同一个资产。

`scheduler_model_time_wheel_v1` 负责三/四模型 owner 任务的非临时调度入队和可选 live dispatch。它读取 `three_model_materializer_v1` 的交易日实例，写入本地 `ai_stock_scheduler_task_store.sqlite3::*` 调度审计表；开启 live dispatch 后只调用 `research-service /research/model-execution/run`，不直连 owner，不写 `decision_hot.*`、`decision_memory.*`、`decision_ambush.*`、`decision_t_relay.*` 或 `research_t_relay.*`。

模型四 `t_relay.day1.scan.close` 是模型任务时间轮里的特殊多候选任务：scheduler 在入队或 catch-up dry-run 时只读当日 `source.limit_event_v1`，筛出 `t_relay_limit_event_t_board` 阶段候选并写入 `symbols[]`；`SCHEDULER_T_BOARD_GUARD_SYMBOL` 不得作为生产候选回退。没有真实 T 字板候选时，scheduler 在本地 task store 中把任务标为 `blocked_data_gap`，输出 `source_gap:t_relay_day1_stage_candidates_missing`，不调用 `research-service /research/model-execution/run`，防止 research-service 使用默认样本股。该阻断是已审计终态，不进入 retry/dead-letter，也不代表模型 owner 或 source-data-service 异常。

当前模型校验阶段由 `SCHEDULER_REQUIRED_MODEL_SERVICES` 控制模型 owner 是否进入运行硬依赖。Compose 当前默认 `hot_candidates,t_board_relay`：热点 owner 和模型四 owner readyz、dispatch 失败和本地 task store 失败会阻断 scheduler ready；candidate_memory/ambush 暂停并在 `details.skipped[]` 记录 `disabled_by_policy`，不入队、不派发、不伪装 success。显式设为 `none` 时才暂停全部四个 owner；`status_counts` 与 retry/dead-letter readiness guard 只统计 required owner services。

| 调度对象 | 频率来源 | 执行入口 | 默认行为 |
|---|---|---|---|
| `hot.*` | `three_model_materializer_v1` 固定时间/窗口 | `POST /research/model-execution/run` | Compose 生产候选开启 `SCHEDULER_MODEL_TIME_WHEEL_LIVE_DISPATCH=true` 后交给 research-service 执行；代码未显式配置时仍可只入队审计 |
| `memory.*` | `three_model_materializer_v1` 收盘、次日窗口、成熟度检查 | `POST /research/model-execution/run` | 入队审计；缺研究输入保留 `scheduler_payload_assembly_required` 或 research execution gap |
| `ambush.*` | `three_model_materializer_v1` 周期审计、收盘、离线挖掘 | `POST /research/model-execution/run` | 入队审计；research execution 失败进入 retry/dead-letter 并阻断 ready |
| `t_relay.*` | `three_model_materializer_v1` Day1/Day2/Day3/outcome 窗口 | `POST /research/model-execution/run` | 全部 non-official；业务表由 owner repository 写入；scheduler 不反写前三模型 |

`POST /scheduler/model-time-wheel/run-once` 是只读验收/人工触发当前轮的入口。代码默认 `SCHEDULER_MODEL_TIME_WHEEL_LIVE_DISPATCH=false`，Compose 生产候选默认显式开启。开启 live 后，`materialized` 记为 success；`blocked_data_gap`、`materialized_with_gaps`、`materialization_skipped` 记为已审计终态，保留缺口码和 execution audit，不进入 retry，不伪装成成功；research execution HTTP 非 2xx、`owner_failed`、`materialization_failed`、异常、`retry_ready` 或 `dead_letter` 未清空必须让 `/scheduler/runtime/status` 中的 model time wheel 进入 `failed`，并通过 `/readyz` 阻断。自动入队 payload 只携带调度审计上下文和 `scheduler_payload_assembly_required` 缺口码，不得用 sample payload 代替真实市场事实。

`scheduler_model_payload_preflight_v1` 是显式 preview/live dispatch 前的数据资产门禁；只读入口为 `GET /scheduler/model-payload/requirements`、`POST /scheduler/model-payload/preflight` 和 `POST /scheduler/model-payload/assemble-preflight`。真实生产 payload 必须声明 `payload_assembly_contract=research_model_payload_assembler_v1`、`payload_assembly_status=assembled_research_payload`、非空 `payload_assembly_source`；official release gate 还必须携带 passed `source_preflight`。显式预检失败只返回 preview 阻断结果，不调用 owner endpoint，不写模型事实；正式 model time wheel live dispatch 由 `research-service /research/model-execution/run` 负责写 execution audit，scheduler 只按 success、terminal non-success、retry/dead-letter 更新本地 task store。

`POST /scheduler/model-payload/assemble-preflight` 的合同版本为 `scheduler_research_payload_assemble_preflight_v1`。该入口只读取 `research-service /research/model-payload/assemble` 返回的 payload，并用 scheduler 现有 preflight 校验；默认 `persist_audit=false`，不触达 owner endpoint。正式 time wheel live dispatch 不复用 preview 直连 owner，而是调用 `research-service /research/model-execution/run`。`blocked_data_gap`、`source_gap:*`、sample 标记或 source preflight late/stale/missing 必须让 `dispatch_allowed=false`。

2026-06-18 release gate 上游表合同：三条 official release gate 不以自身 `*_signal_fact_v1` 为前置读取条件。`hot.release_gate.preopen` 等待 `decision_hot.hot_score_fact_v1` 与 `decision_hot.hot_evidence_snapshot_v1`；`memory.pre_signal.scan` 声明写入、`memory.release_gate.close` 声明读取的 pre-signal 表均为 `decision_memory.memory_pre_signal_case_v1`；`ambush.phase3.release_gate.close` 等待 `decision_ambush.effective_turn_pool_v1`。scheduler 只校验和转交这些真实上游缺口，不写入对应 decision 表。

2026-06-18 runtime 发布冻结：用户批准“发布 research+scheduler”后，本服务只替换 `scheduler-service` 与 `research-service` 容器，未替换 source-data、data-inspector、Postgres 或模型 owner。发布后数据资产读写边界保持：

| 资产/接口 | 运行态结论 | 边界 |
|---|---|---|
| `/scheduler/model-payload/assemble-preflight` | 三条 official release gate 均按新 upstream contract 返回 no-persist 预检结果 | `blocked_data_gap` 时 `dispatch_allowed=false`，不触达 owner endpoint |
| `/research/model-execution/run` | 模型任务时间轮 live dispatch 唯一正式执行入口 | scheduler 只转交 task/symbol/date/run context；owner 调用、物化和 execution audit 归 research-service |
| `decision_hot.hot_score_fact_v1`、`decision_hot.hot_evidence_snapshot_v1` | `hot.release_gate.preopen` 的真实上游；当前为空所以阻断 | scheduler 只读/转交缺口；research 可物化 owner 输出 |
| `decision_memory.memory_pre_signal_case_v1`、`decision_memory.memory_score_fact_v1` | `memory.release_gate.close` 的真实上游；当前为空所以阻断 | scheduler 只读/转交缺口，不读取旧 `decision_memory.pre_signal_case_v1`；research 可物化 owner 输出 |
| `decision_ambush.effective_turn_pool_v1` | `ambush.phase3.release_gate.close` 的真实上游；当前为空所以阻断 | scheduler 只读/转交缺口，不读取自身 `ambush_signal_fact_v1`；research 可物化 owner 输出 |
| `/source/fetch/queues/summary` | 所有队列 queued/leased/dead_letter 均为 0 | source fetch 仍由 source-data-service/worker 持久化队列负责 |

回滚标签：`infra-scheduler-service:rollback-20260618-research-scheduler-release`。只读验收允许继续使用 `/readyz`、`/scheduler/validate/three-models`、`/scheduler/validate/docs-sync` 和 no-persist assemble-preflight；修改上述读写边界必须重新解锁。

当前仓库已落地独立 `research-service` payload assembler 和 `research_model_execution_v1` 执行桥；`research-center-service` 当前只承载模型三低谷图库研究资产，不作为三/四模型生产 payload assembler。缺真实 payload 时继续保留 `scheduler_payload_assembly_required` 或 research execution gap，不得用 0、空字符串、sample payload 或 GPT 推断补事实。scheduler 已冻结的 `scheduler_model_payload_preflight_v1` 只校验 payload 合同，不组装 payload。

## 禁止事项

- 不直接并发调用任何 provider。
- 不把 sample payload 当 source 事实。
- 不把 `scheduler_payload_assembly_required` 当 assembled payload 发给模型 owner。
- 不绕过 `research-service /research/model-execution/run` 直连 owner 执行非临时模型任务。
- 不把 owner service 2xx 改写为 official signal 成功。
- 不绕过 data-inspector startup/core closure 守卫。
- 不把临时取数登记为非临时调度。

## 2026-06-17 冻结记录

本轮数据源闭环和 scheduler 定向修复验收后，以下对象冻结；确认来源为用户本轮授权“完成闭环后可以拍板冻结”并继续批准执行。

| 冻结对象 | 数据资产范围 | 验收证据 | 只读验收 | 解锁条件 |
|---|---|---|---|---|
| `scheduler-service -> current_closure guard -> source/data-inspector readiness gate` | `source-data-service /readyz`、`/source/ops/production-readiness`、`/source/fetch/queues/summary`、`data-inspector-service /inspection-runs/latest` | `/readyz` ready；startup_guard run `2084` ready；core_closure run `2085` ready；source production readiness passed | `/readyz`、`/inspection-runs/latest`、`scripts/core_services_acceptance.py` | readyz blocked、P0/P1 gap、source readiness blocked，或用户明确批准解锁。 |
| `scheduler-service -> live dispatch -> owner endpoint contracts` | required 模型 owner `/readyz` 和 owner endpoint；scheduler 只传递 payload 与 `_scheduler_context`；当前逐个模型校验阶段 disabled owner 只记录 `disabled_by_policy` | 历史 core acceptance exit 0；`required_failed=[]`；hot/memory/ambush/t_relay live dispatch accepted；当前策略由 `SCHEDULER_REQUIRED_MODEL_SERVICES` 收窄 | core acceptance sample/live dispatch、required owner `/readyz`、disabled policy 审计 | owner endpoint 合同变化、live dispatch failed、required model policy 变化，或用户明确批准解锁。 |
| `scheduler-service -> source schedule registry -> non-temporary source fetch schedules` | `source_fetch_schedule_registry_v1`；一次性、日调度、分钟级、窗口级 source fetch 计划；source table、canonical fields、队列/优先级、频率、幂等键；覆盖 research payload required source tables；包含 THS paid probability fetch/deadline guard | `/scheduler/validate/source-schedule valid=true`；`schedule_count=16`；`missing_research_payload_tables=[]`；materialized `instance_count=722`；source-data-service 未中断 | `/scheduler/source-schedule/registry`、`/scheduler/validate/source-schedule`、`/scheduler/materialize/source-schedule` | 新 P0/P1 source 调度缺口、频率/接口合同变化、生产窗口阻断，或用户明确批准解锁。 |
| `scheduler-service -> source time wheel -> current-window submit and local task lease` | `scheduler_source_time_wheel_v1`；当前窗口提交、过期窗口不追发、本地 task store、lease/retry/dead-letter、`/source/fetch/submit` 转交 | `/readyz ready`；`source_time_wheel.status=idle`；scheduler tests `39 passed` | `/scheduler/runtime/status`、`POST /scheduler/source-time-wheel/run-once`、本地 task store 只读检查 | 重复提交、漏提交、误追发过期窗口、lease/dead-letter 语义变更，或用户明确批准解锁。 |
| `scheduler-service -> source-fetch temporary -> cross-service ad hoc fetch orchestration` | `POST /scheduler/source-fetch/temporary`；dry-run 默认、允许 trigger_type、source table/canonical fields 校验、`request_source=scheduler-service` | temporary fetch dry-run owner=`source-data-service`；endpoint=`POST /source/fetch/submit` | temporary fetch dry-run、source-data-service fetch submit 状态只读查询 | 下游临时取数合同变化、source orchestration 合同变化，或用户明确批准解锁。 |

2026-06-17 定向小修后，临时取数入口的数据资产边界加硬为：只允许 `source.*`，必须提供非空 `canonical_fields`，禁止 `scheduled_periodic` 进入临时入口；source time wheel 任一 `/source/fetch/submit` 非 2xx 响应必须让本轮 time wheel 状态为 `failed`，并通过 scheduler `/readyz` 阻断。

用户随后回复“继续”，确认拍板冻结本次小修后的数据资产边界：

| 冻结对象 | 数据资产范围 | 验收证据 | 只读验收 | 解锁条件 |
|---|---|---|---|---|
| `scheduler-service -> source-fetch temporary -> table contract hard guard` | 临时取数入口只允许 `source.*`、非空 `canonical_fields`、非 `scheduled_periodic` trigger；只转交 `source-data-service /source/fetch/submit` | `pytest` 39 passed；非 source 表 409；空 `canonical_fields` 409；合法 source dry-run 预览成功 | temporary fetch dry-run；`/scheduler/validate/docs-sync`；`/scheduler/runtime/status` | 下游临时取数合同变化、source fetch submit 合同变化，或用户明确批准解锁。 |
| `scheduler-service -> source time wheel -> dispatch failure readiness guard` | 本地 task store 的 source time wheel submit 状态、dispatch failure、error、readyz 阻断 | `pytest` 39 passed；submit 503 测试进入 `failed`；运行态 time wheel `idle` | `/scheduler/runtime/status`、`POST /scheduler/source-time-wheel/run-once`、本地 task store 只读检查 | source submit 合同变化、生产窗口误阻断/漏阻断，或用户明确批准解锁。 |

用户随后回复“继续”，确认拍板冻结模型任务时间轮的数据资产边界：

| 冻结对象 | 数据资产范围 | 验收证据 | 只读验收 | 解锁条件 |
|---|---|---|---|---|
| `scheduler-service -> model task time wheel -> non-temporary owner task enqueue/audit/readiness guard` | `scheduler_model_time_wheel_v1`；`ai_stock_scheduler_task_store.sqlite3::task_instance_v1/task_lease_v1/task_run_log_v1/task_dead_letter_v1`；四模型 owner 任务按 `three_model_materializer_v1` 入队；默认 `SCHEDULER_MODEL_TIME_WHEEL_LIVE_DISPATCH=false`；自动入队仅保留 `scheduler_payload_assembly_required` 缺口码与调度审计上下文 | `pytest` 39 passed；`/readyz` ready；model time wheel `idle`；`/scheduler/model-time-wheel/run-once` idle；docs-sync valid；three-model plan valid；source-data-service 未中断 | `/scheduler/runtime/status`、`POST /scheduler/model-time-wheel/run-once`、`/scheduler/materialize/three-models`、`/scheduler/validate/three-models`、`/scheduler/validate/docs-sync`、本地 task store 只读检查 | 真实 research payload assembler 接入、owner endpoint 合同变化、模型任务 live dispatch 投产、readyz 误阻断/漏阻断，或用户明确批准解锁。 |

用户随后回复“你认为可以冻结就行”，确认由 Codex 按验收结果拍板冻结模型 payload 投产预检数据资产边界：

| 冻结对象 | 数据资产范围 | 验收证据 | 只读验收 | 解锁条件 |
|---|---|---|---|---|
| `scheduler-service -> model live dispatch -> payload production preflight guard` | `scheduler_model_payload_preflight_v1`；`GET /scheduler/model-payload/requirements`；`POST /scheduler/model-payload/preflight`；`research_model_payload_assembler_v1`；`assembled_research_payload`；official release `source_preflight` passed 门禁；缺口/sample payload 拦截；预检失败只写 `ai_stock_scheduler_task_store.sqlite3::*` failure/retry/dead-letter 审计，不触达 owner endpoint | `pytest` 39 passed；requirements 覆盖 24 个模型 owner 任务；缺口 payload `valid=false`；assembled official payload `valid=true`；docs-sync valid；`/readyz` ready；source-data-service 未中断 | `/scheduler/model-payload/requirements`、`/scheduler/model-payload/preflight`、`/scheduler/runtime/status`、`POST /scheduler/model-time-wheel/run-once`、`/scheduler/validate/docs-sync`、本地 task store 只读检查 | 真实 research payload assembler 接入、official release preflight 合同变化、owner endpoint payload 合同变化、live dispatch 投产、readyz 误阻断/漏阻断，或用户明确批准解锁。 |

2026-06-17 用户回复“继续”后，`scheduler-service` 已按 `--no-deps` 单服务发布，运行态冻结证据如下：

| 冻结对象 | 数据资产范围 | 发布后验收证据 | 只读验收 | 解锁条件 |
|---|---|---|---|---|
| `scheduler-service -> source schedule registry -> research payload source coverage` | `source_fetch_schedule_registry_v1`；16 条非临时 source 调度；覆盖 `research_model_payload_assembler_v1` 的 13 张 required source 表；P0 `source.limit_price_v1`、`source.limit_event_v1` 与 `source.ths_paid_limit_up_probability_v1` | `scheduler-service` 容器 healthy；`/scheduler/validate/source-schedule valid=true`；`schedule_count=16`；`missing_research_payload_tables=[]`；materialized `instance_count=722`；`/scheduler/validate/three-models valid=true`；`/scheduler/validate/docs-sync valid=true`；source-data-service 未中断 | `/scheduler/source-schedule/registry`、`/scheduler/validate/source-schedule`、`/scheduler/materialize/source-schedule`、`/scheduler/validate/three-models`、`/scheduler/validate/docs-sync`、`/readyz` | 新 P0/P1 source 调度缺口、research payload required source 表变化、source fetch submit 合同变化、运行态 readyz 误阻断/漏阻断，或用户明确批准解锁。 |

## 2026-06-17 定向解锁修复记录

用户批准将下一步重点放到 `scheduler-service` 后，本服务被定向解锁执行最小调度合同修复。本轮数据资产变更范围：

- `source.auction.collect.0915_0925`、`source.auction.freeze.092505_092530`、`source.open_5m.collect` 改为只通过 `source-data-service /source/fetch/submit` 发起数据源任务。
- hot / memory buy point owner 与当前 owner service API 对齐，不再指向当前 Compose 中不存在的 `execution-timing-service`。
- 调度计划校验新增 provider/raw 禁读、source orchestration owner、当前 owner allowlist 和 README owner endpoint 映射检查。
- 新增 `source_fetch_schedule_registry_v1`、`scheduler_source_time_wheel_v1` 和 `POST /scheduler/source-fetch/temporary`，使非临时 source 调度与其他服务临时取数都走 source-data-service fetch orchestration。

本记录不解除前述冻结约束；后续若要继续修改 scheduler live dispatch 行为、source schedule registry 范围或跨服务临时取数合同，仍需再次获得用户批准。
## 2026-06-18 Research Assemble-Preflight 数据资产冻结记录

用户本轮确认后，`scheduler-service` 仅按 `--no-deps` 单服务发布，验证 `POST /scheduler/model-payload/assemble-preflight` 已在运行态加载。该入口的数据资产边界如下：

| 冻结对象 | 数据资产范围 | 发布后验收证据 | 只读验收 | 解锁条件 |
|---|---|---|---|---|
| `scheduler-service -> model payload integration -> research assemble-preflight bridge` | `scheduler_research_payload_assemble_preflight_v1`；只读调用 `research-service /research/model-payload/assemble`；默认 `persist_audit=false`；读取 `research_model_payload_assembler_v1` payload、source refs、source preflight、gap codes；只生成 scheduler preflight 结果和 owner request body preview | `scheduler-service` 容器 `d6e0ee0e72a5` healthy；`source-data-service` 容器 `cc2b01689dc5` 未重启；`data-inspector-service` 与 `research-service` healthy；`/readyz ready` 且 startup_guard run `2093` P0/P1 gap 为 0；source queue queued/leased/dead-letter 均为 0；历史 `as_of_time_utc=2026-06-12T07:05:00Z` 返回 `blocked_data_gap`、`dispatch_allowed=false`；不传历史 `as_of_time_utc` 返回 `assembled_research_payload`、`dispatch_allowed=true` 且仅有 preview；scheduler docs-sync valid；scheduler tests `41 passed`；research tests `6 passed` | `/scheduler/model-payload/assemble-preflight` no-persist 探针、`/scheduler/model-payload/requirements`、`/scheduler/validate/docs-sync`、`/readyz`、`/source/fetch/queues/summary`、scheduler/research 单测 | research assembler 合同变化、owner request body 合同变化、official release preflight 合同变化、需要真实 owner live dispatch，或用户明确批准解锁 |

冻结后，scheduler 仍不得读取 `raw_*`、不得直接调 provider、不得把 `blocked_data_gap` 或 `source_gap:*` 改写为可派发、不得用 sample/0/空字符串/GPT 推断补模型输入；该入口即使 `dispatch_allowed=true` 也只表示 preflight preview 通过，不等于已经调用 owner service 或发布 official signal。

## 2026-06-18 Scheduler Post-Source-Freeze 数据资产复核记录

数据源零行备源保护冻结后，本服务在不改代码、不重启、不重建、不触发 owner live dispatch 的前提下完成只读复核。该记录只刷新当前运行证据，不解除既有冻结。

| 冻结对象 | 数据资产范围 | 复核证据 | 只读验收 | 解锁条件 |
|---|---|---|---|---|
| `scheduler-service -> post-source-freeze review -> non-temporary schedule and readiness evidence` | `source_fetch_schedule_registry_v1` 16 条非临时 source 调度；`scheduler_source_time_wheel_v1`；`scheduler_model_time_wheel_v1`；`current_closure` readyz；`three_model_materializer_v1` 27 个模型任务；`scheduler_docs_sync_v1` | source/data-inspector/research ready；source/model time wheel 均 `idle`；`/scheduler/validate/source-schedule valid=true`、`schedule_count=16`、`missing_research_payload_tables=[]`；`/scheduler/validate/three-models valid=true`；`/scheduler/validate/docs-sync valid=true`；source readiness passed；source queues queued/leased/dead_letter 全 0 | `/readyz`、`/scheduler/runtime/status`、`/scheduler/validate/source-schedule`、`/scheduler/validate/three-models`、`/scheduler/validate/docs-sync`、`/source/fetch/queues/summary` | 新 P0/P1 source 表进入 research payload required set、source-data-service fetch submit 合同变化、readyz 误阻断/漏阻断、time wheel 漏提交/重复提交、需要投产真实 owner live dispatch，或用户明确批准解锁。 |

继续禁止：scheduler 不读取 `raw_*`，不直接调用 provider，不将临时取数登记为非临时调度，不把 `blocked_data_gap`、`source_gap:*` 或 sample payload 改写为可派发，不写模型事实、official signal、买点、outcome 或学习权重。

## 2026-06-18 Execution Bridge Runtime 数据资产冻结记录

用户要求“继续闭环”后，scheduler 模型任务时间轮已在运行态切到 research execution dispatch：

| 资产/接口 | 发布后证据 | 数据边界 |
|---|---|---|
| `scheduler_model_time_wheel_v1` | `/readyz` 中 `dispatcher_version=scheduler_research_model_execution_dispatch_v1`、`live_dispatch=false`、`status=idle` | 代码可只入队/审计；Compose 生产候选开启 live 后只调用 `research-service /research/model-execution/run` |
| `RESEARCH_SERVICE_BASE_URL/research/model-execution/run` | research `/readyz` 显示 `execution_audit_ready=true`；阻断探针 `exec-closure-20260618150910` 已写 audit 且 `owner_called=false` | scheduler 不直连 owner，不写 `decision_*` / `research_*` |
| `ai_stock_scheduler_task_store.sqlite3::*` | 本地 task store 继续用于 pending/terminal blocked/retry/dead-letter；readyz 中 model time wheel 无 error | `blocked_data_gap`、`materialized_with_gaps`、`materialization_skipped` 为已审计终态；HTTP 非 2xx、`owner_failed`、`materialization_failed`、异常或 retry/dead-letter 未清空必须阻断 readyz |
| `/source/fetch/queues/summary` | 所有队列 `queued_count=0`、`leased_count=0`、`dead_letter_count=0` | source fetch 仍由 source-data-service/worker 持久化队列负责 |

发布对象：

```text
scheduler image: infra-scheduler-service@sha256:7b40e9e6c2f17fc0129d26587dc2f6b0934afd3fc13e092ef304fd33c1dd3eeb
scheduler container: ai-stock-scheduler-service 7ce78da5adf2
rollback: infra-scheduler-service:rollback-20260618-execution-bridge-closure
```

未中断对象：

```text
source-data-service 125b58ac7f9e
source-data-worker 0df61d50252b
data-inspector-service 0995dca891f7
postgres af846a793868
```

冻结后，scheduler 可以继续做 `/readyz`、`/scheduler/runtime/status`、`/scheduler/validate/three-models`、`/scheduler/validate/docs-sync` 和 source queue summary 只读验收；需要改 owner dispatch 路径、terminal non-success 分类或 retry/dead-letter 语义时必须重新解锁。

## 2026-06-18 Model Time Wheel Live Dispatch 数据资产变更

用户批准本轮解锁后，`scheduler-service` 数据资产边界新增：

| 资产/接口 | 本轮变更 | 数据边界 |
|---|---|---|
| `scheduler_task_store` Docker volume | `infra/docker-compose.yml` 挂载到 `/var/lib/ai_stock_scheduler`，`SCHEDULER_TASK_STORE_PATH=/var/lib/ai_stock_scheduler/task_store.sqlite3` | 只保存 scheduler 本地任务实例、lease、terminal blocked、retry/dead-letter 和 run log；不替代 source-data-service Postgres fetch queue，也不作为模型事实库 |
| `SCHEDULER_MODEL_TIME_WHEEL_LIVE_DISPATCH` | Compose 生产候选默认 `true` | 正式模型时间轮只调用 `research-service /research/model-execution/run`；不直连 owner，不写 decision/research 业务事实 |
| `task_instance_v1.status` | 新增终态非成功口径：`blocked_data_gap`、`materialized_with_gaps`、`materialization_skipped` | 保留真实缺口、无行或物化 gap，不 retry、不伪装 success；下游可只读审计 |
| `retry_ready/dead_letter` | 保持 failure guard | 仅用于 HTTP 非 2xx、`owner_failed`、`materialization_failed` 或异常，未清空时阻断 `/readyz` |

发布前必须备份旧容器 `/tmp/ai_stock_scheduler_task_store.sqlite3` 并灌入新命名卷，保证已入队未执行的非临时模型任务继续被正式 live dispatch 处理。该变更不允许触碰 `source-data-service`、`source-data-worker`、`data-inspector-service`、Postgres 或模型 owner 服务。

发布后数据资产证据：

| 资产 | 发布后状态 | 只读证据 |
|---|---|---|
| `scheduler_task_store` volume | 已灌入旧 `/tmp` task store 并由新容器挂载 | backup `C:\Users\JUNQIA~1\AppData\Local\Temp\ai_stock_scheduler_task_store_20260618-174528\task_store.sqlite3`；seeded bytes `69632`；path `/var/lib/ai_stock_scheduler/task_store.sqlite3` |
| `task_instance_v1` | pending 已清零，真实缺口保留为终态 | `blocked_data_gap=12`、`success=5`、`pending=0`、`retry_ready=0`、`dead_letter=0` |
| `scheduler_model_time_wheel_v1` | 正式 live dispatch 已开启 | `/scheduler/runtime/status` 显示 `live_dispatch=true`、`status=idle`、`dispatcher_version=scheduler_research_model_execution_dispatch_v1` |
| `research_model_execution_v1` | 12 条旧 pending 已派发并写 execution audit | 每条返回 HTTP 200、`accepted=false`、`completed=true`、`terminal_non_success=true`、`execution_status=blocked_data_gap`，缺口码保留在 response/task log |
| source fetch queue | 未产生新 source 阻塞 | `/source/fetch/queues/summary` 所有队列 `queued_count=0`、`leased_count=0`、`dead_letter_count=0` |

用户在交付报告后回复“批准”，确认以下数据资产边界正式拍板冻结。

冻结对象：

| 冻结对象 | 数据资产范围 | 发布后验收证据 | 只读验收 | 解锁条件 |
|---|---|---|---|---|
| `scheduler-service -> model time wheel -> production live dispatch and terminal blocked audit` | `SCHEDULER_MODEL_TIME_WHEEL_LIVE_DISPATCH=true`；`scheduler_task_store` 命名卷；`task_instance_v1` terminal non-success 状态；`research-service /research/model-execution/run` 正式执行桥；retry/dead-letter readyz guard；2026-06-18 17:53 Asia/Shanghai 用户批准后冻结 | `scheduler-service` 容器 `96024e43e68c` healthy；image `sha256:050ffdcb096875771b0f094fc3ec82486ed022ff249a39a4cbea572f1c7c84e7`；startup_guard run `2098` ready；task store `blocked_data_gap=12/success=5/pending=0/retry_ready=0/dead_letter=0`；source/data-inspector/research ready；source queues clear；source schedule/three-model/docs-sync valid；scheduler tests `43 passed` | `/readyz`、`/scheduler/runtime/status`、task store 只读统计、`/scheduler/validate/source-schedule`、`/scheduler/validate/three-models`、`/scheduler/validate/docs-sync`、source queue summary | research execution 合同变化、owner endpoint 合同变化、terminal non-success 分类变化、task store 持久化路径变化、readyz 误阻断/漏阻断，或用户明确批准解锁 |

## 2026-06-20 Scheduler Readonly Closure 数据资产复核

用户批准仅同步当前 MD，本次不改代码、schema、Docker、环境变量，不重启、不 rebuild、不触发非 dry-run 临时取数。复核结论是调度服务继续维持冻结。

| 数据资产/接口 | 当前复核证据 | 数据边界 |
|---|---|---|
| `source_fetch_schedule_registry_v1` | `/scheduler/validate/source-schedule valid=true`；`schedule_count=16`；`missing_research_payload_tables=[]`；`provider_or_raw_violations=[]`；`missing_endpoint_chain=[]`；`invalid_trigger_priority_pairs=[]` | 只登记非临时 recurring source 调度；不得把临时取数、provider 原始参数或 raw 读取加入 registry。 |
| `scheduler_source_time_wheel_v1` | `/readyz source_time_wheel.status=idle`；`live_submit=true`；materialize `instance_count=722`、`scheduled_periodic_instance_count=670` | 到点任务只提交 source-data-service 受控端点；过期窗口不追发，不直接调用 provider。 |
| `ths paid probability schedule` | registry allowed endpoints 包含 `/source/ths/paid-probability/fetch-current-batch` 与 `/source/ths/paid-probability/deadline-check` | scheduler 不接触 Cookie，不构造 THS provider 参数；Cookie probe、fetch orchestration 和下一交易日 09:00 放弃判定均由 source-data-service 执行。 |
| `scheduler_temporary_source_fetch_preview_v1` | dry-run 返回 `owner_endpoint=POST /source/fetch/submit`、`request_source=scheduler-service:hot-candidates-service`、`trigger_type=model_adhoc_request`；`scheduled_periodic` 临时请求被 409 拒绝 | 临时取数是显式 ad hoc source orchestration，不进入 recurring schedules；dry-run 不提交 source queue。 |
| `scheduler_model_time_wheel_v1` | `/readyz model_time_wheel.status=idle`；`live_dispatch=true`；`status_counts.blocked_data_gap=84`；`/scheduler/validate/live-dispatch-samples valid=true` | 模型任务只通过 research execution bridge；blocked 数据缺口保留为审计终态，不伪装成 success。 |
| `source fetch queue` | `/source/fetch/queues/summary queued_total=0, leased_total=0, dead_letter_total=0` | source fetch 生产队列仍归 source-data-service Postgres queue；scheduler 只读观测，不清队列、不改 job。 |
| `scheduler tests` | `PYTHONPATH=services/scheduler-service/src python -m pytest -q services/scheduler-service/tests -> 47 passed` | 测试覆盖 source schedule registry、time wheel、临时取数拒绝规则、runtime guard、模型 dispatch 合同。 |

冻结延续对象：`scheduler-service -> source schedule registry -> non-temporary source orchestration coverage`、`scheduler-service -> model time wheel -> production live dispatch and terminal blocked audit`。允许只读验收 `/readyz`、`/scheduler/runtime/status`、`/scheduler/validate/source-schedule`、`/scheduler/validate/three-models`、`/scheduler/validate/docs-sync`、`/scheduler/validate/live-dispatch-samples`、source queue summary 和 dry-run temporary preview。解锁条件：新增 P0/P1 source 表进入 research payload required set、source-data-service fetch submit 合同变化、THS paid probability endpoint 合同变化、readyz 误阻断/漏阻断、time wheel 漏提/重复提、terminal non-success 分类变化、或用户明确批准解锁。

## 2026-06-24 Model4 Rolling Monitor 数据资产冻结

2026-06-24 验收补充：`POST /scheduler/model-schedule/catch-up` 对 `t_relay.observation.monitor.snapshot_5m` 的 09:35 槽位可 dry-run 精确选中 1 个实例；非 dry-run 仅写 scheduler 本地 task store，并在 `dispatch_immediately=true` 时调用 `research-service /research/model-execution/run`。补偿 payload 将实际捕获时间写入 `as_of_time_utc`，原始 `scheduled_at/run_slot/catch_up_run_id/captured_late` 保留在 `_scheduler_materialized_instance`，不得把迟到快照解释成历史实时盘口事实。当前实测后 owner 快照表从 4 行增至 8 行，frontend compact/DOM 可读 4 条 Day1 合格对象，scheduler tests 当前为 `64 passed`。

| 冻结对象 | 数据资产范围 | 当前验收事实 | 只读验收 | 解锁条件 |
|---|---|---|---|---|
| `scheduler-service -> model time wheel -> model4 rolling watch and post-entry monitor schedule` | `scheduler_model_time_wheel_v1` 中模型四 Day2 `09:30-10:30` 每 5 分钟 watch/trigger，Day2 触发后 `09:35-11:30`、`13:00-15:00` 每 5 分钟 post-entry monitor，观察台当前输出 `09:30-11:30`、`13:00-15:00` 每 5 分钟 snapshot，Day3 `09:25-09:35` 与 `14:40-14:55` 去留检查；source queue 仍归 source-data-service Postgres queue | `/scheduler/validate/three-models valid=true task_count=28`；source fetch queue `queued_total=0`、`leased_total=0`、`dead_letter_total=0`；scheduler runtime policy 当前要求 `hot_candidates,t_board_relay`；scheduler tests `61 passed` | `/readyz`、`/scheduler/runtime/status`、`/scheduler/validate/three-models`、source queue summary、task store 只读统计、research/owner/frontend 只读观察结果 | 模型四窗口或频率变化、research execution bridge 合同变化、owner endpoint 合同变化、source queue 边界变化、Day3 自然窗口验收失败、或用户明确批准解锁 |

## 2026-06-25 Hot Candidates Required Policy Data Asset

用户批准解锁 `scheduler-service` 热点模型启用后，Compose 默认 `SCHEDULER_REQUIRED_MODEL_SERVICES` 从 `t_board_relay` 调整为 `hot_candidates,t_board_relay`。该变更只影响 scheduler readyz required owner 集合、model time wheel 入队/派发选择和本地 task store readiness guard；它不改变 source-data-service/provider/Cookie 归属，不让 scheduler 直连 owner/provider/raw，也不让 scheduler 写 `decision_hot.*`。

| 数据资产 | 当前口径 | 禁止事项 |
|---|---|---|
| `SCHEDULER_REQUIRED_MODEL_SERVICES=hot_candidates,t_board_relay` | 热点 owner 与模型四 owner 纳入 required readyz 和 model time wheel live dispatch；candidate_memory/ambush 继续 `disabled_by_policy`。 | 不得把 owner 2xx 解释为 official signal；不得跳过 `research-service /research/model-execution/run`、source preflight、payload assembly 或 source gaps。 |
| THS paid probability source batch | `2026-06-24` 批次已通过 source-data-service 受控路径达到 `ready`、50/50；Cookie 状态为 `valid`。 | scheduler 不接触 Cookie 明文，不构造 THS provider 参数，不直接写 raw/source/lineage。 |

## 2026-06-26 Task Store Recovery Data Assets

用户本轮批准解锁后，scheduler 本地任务账本新增暂停/重启恢复资产边界。该资产只用于 scheduler 本地 source/model 调度审计和恢复，不替代 source-data-service Postgres fetch queue、raw/source/lineage 或 research/owner 事实。

| 数据资产 | 本轮规则 | 边界 |
|---|---|---|
| `task_instance_v1.status=running` + expired `task_lease_v1.lease_until` | source/model time wheel 每轮执行前恢复为 `retry_ready`，并删除旧 lease | 只恢复已过期 running；有效 lease 继续防重，不得重复提交 |
| `task_run_log_v1.event_type=lease_recovered` | 记录 previous lease owner/until，保留重启恢复审计线 | 不写 source facts、不写 model facts、不吞异常 |
| `checks.task_store.source` | `/readyz` 暴露 source 本地 `status_counts`、`stale_running_count`、sample 和 blockers | `retry_ready`、`dead_letter`、`stale_running` 任一存在即阻断 scheduler ready |
| `checks.task_store.model` | `/readyz` 暴露 required model owner 本地 task store 健康 | disabled owner 不进入统计；terminal `blocked_data_gap` 不阻断 |
| source task recovery dispatch | 恢复后的 source task 仍只能提交 source-data-service 受控 endpoint | 不直接调用 provider，不读 raw，不接触 THS Cookie |
| model task recovery dispatch | 恢复后的 model task 仍只能提交 `research-service /research/model-execution/run` | 不直连 owner，不写 decision/research 业务事实 |

本轮已完成 scheduler-service 发布后运行态验证，未重启 `source-data-service`、未清理队列、未直接调用 provider、未真实补跑历史 dead-letter。当前证据：

| 验证项 | 当前结果 | 数据边界 |
|---|---|---|
| scheduler 容器加载 | 容器 `15bcce53dba6`，镜像 `sha256:3ce958d3de6a875829398ebe6f2c7ec91958111d72c9f5ceb8b29dfb3d6a3df3`，`runtime_version=scheduler_runtime_guard_v2`，`recover_expired_running loaded=true` | 仅替换 scheduler 运行态；`source-data-service` 容器保持运行 |
| scheduler task store | `/var/lib/ai_stock_scheduler/task_store.sqlite3`；source 账本 `success=5250, obsolete_contract_replaced=148`；model 账本 `success=135, blocked_data_gap=561`；`retry_ready/dead_letter/stale_running` 均为 0 | `blocked_data_gap` 是已审计终态，不代表 source 或 model 异常 |
| `/readyz` 暴露 | `checks.task_store.source.status=ready`，`checks.task_store.model.status=ready`，两侧 `blocking_statuses=[]`，两侧 `stale_running_count=0` | 若后续出现 `retry_ready`、`dead_letter` 或过期 running lease，scheduler 必须返回 not_ready |
| source queue | `/source/fetch/queues/summary` 所有队列 `queued_count=0`、`leased_count=0`、`dead_letter_count=0` | source 生产队列仍以 source-data-service Postgres queue 为准 |
| data-inspector 继承 | `core_closure` run `2174` ready，P0/P1=0，guardrail 为只读且 `direct_provider_calls_allowed=false`、`fetch_repairs_must_use_source_data_service_orchestration=true` | data-inspector 不直接读取 scheduler SQLite，不反写 source/model/scheduler 事实 |
| catch-up dry-run | `POST /scheduler/source-schedule/catch-up` 对 `source.minute.realtime_quote`、`2026-06-12 09:30` 选中 1 个实例，保留 `biz_key` 和 `idempotency_key`，只指向 `/source/fetch/submit` | dry-run 不写 source queue；真实补齐仍需经 scheduler catch-up 到 source-data-service orchestration |
| 测试 | scheduler tests `72 passed`；data-inspector tests `10 passed` | 测试覆盖过期 lease 恢复、readyz 阻断、catch-up 与只读巡检合同 |

用户在交付报告后回复“拍板”，确认以下数据资产边界正式冻结。

冻结对象：

| 冻结对象 | 数据资产范围 | 发布后验收证据 | 只读验收 | 解锁条件 |
|---|---|---|---|---|
| `scheduler-service -> task store/time wheel -> expired running lease recovery and catch-up safety` | `ai_stock_scheduler_task_store.sqlite3::task_instance_v1/task_lease_v1/task_run_log_v1/task_dead_letter_v1`；`recover_expired_running`；source/model time wheel 周期前恢复；`checks.task_store.source/model`；`POST /scheduler/source-schedule/catch-up` 正式追补入口 | scheduler 容器 `15bcce53dba6` 加载 `runtime_version=scheduler_runtime_guard_v2` 和 `recover_expired_running`；source task store `success=5250/obsolete_contract_replaced=148`；model task store `success=135/blocked_data_gap=561`；两侧 `retry_ready/dead_letter/stale_running=0`；source queues queued/leased/dead_letter 全 0；data-inspector `core_closure` run `2174` ready；scheduler tests `72 passed`、data-inspector tests `10 passed` | `/readyz`、`/scheduler/runtime/status`、task store 只读统计、`/scheduler/validate/source-schedule`、`/scheduler/validate/three-models`、catch-up dry-run、`/source/fetch/queues/summary`、data-inspector latest run 查询 | task store lease/retry/dead-letter 语义变化、readyz 阻断策略变化、source-data-service fetch submit 合同变化、research execution 合同变化、task store 持久化路径变化、真实历史补跑 dead-letter、或用户明确批准解锁 |
