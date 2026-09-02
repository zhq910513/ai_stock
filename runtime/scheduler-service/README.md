<!-- macp-migrated: copy-only 2026-09-02 -->

# MACP 迁入

状态：migrated_copy
来源：ai_stock_source/services/scheduler-service
代码与对照源一致，未改业务逻辑。未切换运行容器到本树。

---

# scheduler-service

`scheduler-service` 是当前核心生产闭环的编排服务，只负责数据源、三大模型 owner service、模型四 owner service 和调度健康之间的任务定义、交易日实例化、启动守卫、dry-run 验证和 live dispatch。它不生产 source 事实，不计算模型分数，不写官方信号、买点、标签、演化样本或学习权重。

本服务数据资产账本见 `services/scheduler-service/DATA_ASSETS.md`，记录 source 调度频率、owner endpoint 依赖和禁止直接 provider/raw 边界。

当前必须调通的服务范围：

- `source-data-service` 与 `source-data-worker`
- `data-inspector-service`
- `hot-candidates-service`
- `candidate-memory-service`
- `ambush-watchlist-service`
- `t-board-relay-service`
- `scheduler-service`

其他业务服务不是当前闭环前置条件，不能作为 scheduler ready 或核心模型调度成功的必要条件。默认 `SCHEDULER_GUARD_MODE=current_closure`，scheduler ready 直接校验当前核心闭环：source-data-service、source-data-worker 队列、data-inspector-service `/readyz`、本次 `startup_guard`、最新 `startup_guard/core_closure` 巡检、`SCHEDULER_REQUIRED_MODEL_SERVICES` 声明的 required 模型 owner `/readyz`、三条 official source release preflight 和模型四 Day1/Day2 source preflight。代码默认 required 模型为 `all`；当前热点模型恢复与模型四连续监测阶段 Compose 默认 `hot_candidates,t_board_relay`，把热点 owner 和模型四 owner 纳入 required readyz 与 model time wheel live dispatch，candidate_memory/ambush 继续记录为 `disabled_by_policy`，不打模型 DNS，不阻断 source/scheduler 底座 ready。显式设置 `SCHEDULER_REQUIRED_MODEL_SERVICES=none` 时才暂停全部模型 owner。`SCHEDULER_GUARD_MODE=legacy_data_inspector` 只作为旧全栈巡检兼容模式；该模式下如果 `startup_guard` 返回 `blocked` 或 P0/P1 缺口大于 0，scheduler 必须判 not_ready。scheduler 不得绕过 source-data-service 直接并发调用 BaoStock、AKShare、Tencent、Tushare、EastMoney、Baidu、CNINFO 等 provider。

## 当前版本

- Scheduler runtime/readyz：`scheduler_runtime_guard_v2`
- Source schedule registry：`source_fetch_schedule_registry_v1`
- Source time wheel：`scheduler_source_time_wheel_v1`
- Model task time wheel：`scheduler_model_time_wheel_v1`
- Model execution dispatch：`scheduler_research_model_execution_dispatch_v1`
- Scheduler service lock：`scheduler_three_model_service_v1.0_rc_dispatch_candidate`
- Core-model plan：`core_model_scheduler_design_v2`
- Explicit trigger dispatch：`three_model_live_dispatch_v1`
- Live dispatch sample guard：`three_model_live_dispatch_sample_v1`
- Trading-day materializer：`three_model_materializer_v1`
- Documentation sync guard：`scheduler_docs_sync_v1`

当前模型四交易日实例化合同：
- `t_relay.day2.watch.rolling_5m` 和 `t_relay.day2.trigger.rolling_5m` 为 Day2 `09:30-10:30` 每 5 分钟，用于滚动观察接近涨停和盘口方向确认。
- `t_relay.day2.post_entry.monitor` 为 Day2 触发后的持续封板维护，当前 materializer 在开盘时段 `09:35-11:30` 与 `13:00-15:00` 每 5 分钟生成实例；午休不生成监测实例。
- `t_relay.day3.exit.open` 为 Day3 `09:25-11:30` 每 5 分钟上午去留观察；`t_relay.day3.exit.tail` 为 Day3 `13:00-15:00` 每 5 分钟下午去留观察，其中 `14:40-14:55` 是尾盘退出判断重点。
- `t_relay.observation.monitor.snapshot_5m` 为模型四普通用户观察台当前 5 分钟投影快照，当前 materializer 在 `09:30-11:30` 与 `13:00-15:00` 每 5 分钟生成实例；owner 端点 append-only 写 `decision_t_relay.t_board_observation_monitor_snapshot_v1`，用于三交易日回放和后续调优。
- `t_relay.live_result.compute_30m` 为模型四普通用户观察台 30 分钟模型结果快照，当前 materializer 在 `09:32-11:32` 与 `13:02-15:02` 每 30 分钟生成实例，错开五分钟数据采集；owner 端点同样写 `decision_t_relay.t_board_observation_monitor_snapshot_v1`，但 payload 必须带 `monitor_interval_minutes=30` 和 `result_kind=model_result_30m`。
- 上述模型四任务全部保持 `is_official_publish=false`；scheduler 只负责任务实例化、审计和转交，不生成交易指令、官方信号或模型事实。

模型锁定状态：

- Hot candidates：`hot_candidates_service_v1.0_rc`
- Candidate memory：`candidate_memory_service_v1.0_rc_backend_closure_candidate`
- Ambush watchlist：`ambush_watchlist_service_v1.0_rc_backend_closure_candidate`

## API

- `GET /health`
- `GET /healthz`
- `GET /readyz`
- `GET /scheduler/status`
- `GET /scheduler/runtime/status`
- `GET /scheduler/plan/hot-candidates`
- `GET /scheduler/validate/hot-candidates`
- `GET /scheduler/plan/three-models`
- `GET /scheduler/validate/three-models`
- `GET /scheduler/materialize/three-models?trading_day=YYYY-MM-DD&include_research_intraday=false`
- `GET /scheduler/source-schedule/registry`
- `GET /scheduler/validate/source-schedule`
- `GET /scheduler/materialize/source-schedule?trading_day=YYYY-MM-DD&symbols=000063.SZ,000759.SZ&include_one_time=false`
- `POST /scheduler/source-schedule/catch-up`
- `GET /scheduler/task-store/daily-summary?trading_day=YYYY-MM-DD&owner_service=source-data-service`
- `POST /scheduler/task-store/archive-obsolete-source-dead-letters`
- `POST /scheduler/source-time-wheel/run-once`
- `POST /scheduler/model-time-wheel/run-once`
- `POST /scheduler/model-schedule/catch-up`
- `GET /scheduler/model-payload/requirements`
- `POST /scheduler/model-payload/preflight`
- `POST /scheduler/model-payload/assemble-preflight`
- `POST /scheduler/source-fetch/temporary`
- `GET /scheduler/task-store/daily-summary?trading_day=YYYY-MM-DD&owner_service=source-data-service` also exposes the latest source submit audit fields from `task_run_log_v1`: `source_fetch_batch_id`, `source_fetch_status`, `source_fetch_queue_name`, `source_submitted_job_count`, `source_skipped_duplicate_count`, and `source_producer_ack`. These fields let admin dashboards distinguish a scheduler-completed no-op/duplicate from a task that really has an open source job waiting for raw/source output.
`GET /scheduler/live-dispatch/sample/{task_code}`
- `GET /scheduler/validate/live-dispatch-samples`
- `GET /scheduler/validate/docs-sync?project_root=.`
- `POST /scheduler/trigger`
- `GET /scheduler/validate/hot-workflow`

`POST /scheduler/trigger` 默认 `dry_run=true`。非 dry-run 必须显式传入 `owner_endpoints`，scheduler 只以 owner service 的真实 2xx 响应作为 `accepted=true`，不伪造成功。

非 dry-run 请求体的 `payload` 必须是 owner service 的业务 payload，不得额外包一层模型端字段。scheduler 会按 owner 适配：

- `hot-candidates-service`：把传入 payload 放入模型端 `{ "payload": ... }`，所以调用方传入的 payload 应直接包含 `row`、`run_id`、`as_of_time_utc` 等业务字段。
- `candidate-memory-service`：把传入 payload 放入模型端 `{ "row": ... }`，所以调用方传入的 payload 应是记忆对象/候选行字段本体。
- `ambush-watchlist-service`：直接透传阶段 payload，本体必须满足目标阶段 schema，例如 Phase 3 release task 需要 `instrument`、`valley_watch`、`effective_turn_anchor`、`bars`、`as_of_trading_day` 等字段。
- `t-board-relay-service`：Day1 scan 使用 `{ "rows": [...], "trade_date": "...", "run_id": "..." }`；Day2/Day3/outcome 使用 `{ "payload": { ... }, "run_id": "...", "as_of_time_utc": "..." }`。所有 `t_relay.*` 任务均 non-official。
- `source-data-service`：source 采集任务默认只能提交 `/source/fetch/submit` 合同体，调用方 payload 必须包含 `source_table_name`、`canonical_fields`、`symbols`/日期范围、`trigger_type`、`priority` 等 source fetch 字段；scheduler 自动补 `request_source=scheduler-service` 和稳定 `idempotency_key`，不得传 provider 原始参数绕过 fetch plan。唯一受控例外是同花顺付费概率：scheduler 只可调用 `/source/ths/paid-probability/fetch-current-batch` 和 `/source/ths/paid-probability/deadline-check`，由 source-data-service 自行探测 Cookie、提交 fetch orchestration 和判定下一交易日 09:00 后放弃批次。

调度连通不等于官方信号通过。owner service 返回 2xx 只表示接口合同和编排链路调通；如果模型根据真实缺口返回 `blocked`、`research_only`、`source_gap_codes` 或 `contract_gaps`，scheduler 必须保留该结果，不得改写为发布成功。

`GET /scheduler/task-store/daily-summary?trading_day=YYYY-MM-DD&owner_service=source-data-service` 返回 `scheduler_daily_source_execution_summary_v1`，只读对账 scheduler 当日 source schedule 物化实例与本地 `task_instance_v1`。该接口不提交 fetch、不触发 time wheel、不调用 provider/raw，只按 `biz_key` 合并任务账本：`success` 与 `source_duplicate_skipped` 计为 `completed`，`running` 计为 `collecting`，`retry_ready` / `failed` / `dead_letter` / `blocked_data_gap` 计为 `failed`，未到计划时间计为 `not_due`，已到计划时间但无任务实例计为 `awaiting_dispatch`。下游 admin 看板只能使用该接口做日生命周期执行计数，source fact 是否产出仍以 source-data-service 的 raw/build/source/lineage 和 release preflight 为准。
`GET /scheduler/live-dispatch/sample/{task_code}` 返回 `scheduler_live_dispatch_sample_v1`，包含 scheduler 触发层 payload 和 owner request body 预览，用于验证 live dispatch 包装合同。当前内置样例覆盖三条官方 release gate 和模型四关键 non-official 任务：

- `hot.release_gate.preopen`
- `memory.release_gate.close`
- `ambush.phase3.release_gate.close`
- `t_relay.day1.scan.close`
- `t_relay.day2.watch.rolling_5m`
- `t_relay.day2.trigger.rolling_5m`
- `t_relay.day2.post_entry.monitor`
- `t_relay.day3.exit.open`
- `t_relay.day3.exit.tail`
- `t_relay.observation.monitor.snapshot_5m`
- `t_relay.live_result.compute_30m`
- `t_relay.outcome.build`

`GET /scheduler/validate/live-dispatch-samples` 会校验上述样例都能生成 owner-service 合同体。样例 payload 只用于调度联通和请求体合同验证，不是市场事实、provider 响应或 source 证据；不得替代 `source.*`、lineage、available_at 或 release preflight。模型四真实数据验收必须使用 `000759.SZ / 2026-06-12` 的 source 标准层事实。

2026-06-18 合同修正：scheduler 三/四模型 plan 与 `research-service` payload requirements 对齐。三条 official release gate 不得把自身即将写出的 `*_signal_fact_v1` 当上游读取条件；`memory.pre_signal.scan` 写入、`memory.release_gate.close` 读取的表名均为实际存在的 `decision_memory.memory_pre_signal_case_v1`，不是旧写法 `decision_memory.pre_signal_case_v1`。`hot.release_gate.preopen` 的 research payload 上游是 `decision_hot.hot_score_fact_v1` 与 `decision_hot.hot_evidence_snapshot_v1`，分钟线/实时行情不再作为该 payload 硬依赖；source preflight 和 owner release gate 仍然保留 official 发布前置门禁。

跨服务验收脚本 `scripts/core_services_acceptance.py` 会复用上述 sample API 完成三条官方 release gate 和模型四 Day1/Day2 关键任务的非 dry-run live dispatch 验收，并同时检查 source-data-service 的生产门禁、source row、lineage、release preflight、三大模型 owner API、模型四 owner API 与模型四 repository 写入。该脚本返回 0 表示当前核心生产闭环服务合同调通；不代表 scheduler 生成或改写官方信号。官方信号仍只能由三大模型 owner release gate 与后续 research-service 持久化链路产生，模型四当前只能写 `decision_t_relay` 研究事实。

2026-06-14 本地 Docker 验收结果：

```text
GET /readyz
  -> status=ready, background_loop=ready
  -> data_inspector.status=ready
  -> startup_guard.status=ready, run_id=2062, p0_gap_count=0, p1_gap_count=0
  -> closure_guard.status=ready
  -> latest startup_guard run_id=2062, latest core_closure run_id=2063
  -> latest startup_guard/core_closure inspection status=ready, P0/P1 gaps=0
  -> source production_readiness.status=passed
  -> hot_candidates / candidate_memory / ambush_watchlist / t_board_relay ready
  -> source preflight: 三模型 official preflight + t_board_relay day1/day2 preflight 均 can_release_official_signal=true, blocking_reasons=[]

python scripts/core_services_acceptance.py --require-postgres --real-provider-probe --source-quality-matrix
  -> exit 0, status=passed, required_failed=[]
  -> scheduler.live_dispatch.hot.release_gate.preopen accepted=true
  -> scheduler.live_dispatch.memory.release_gate.close accepted=true
  -> scheduler.live_dispatch.ambush.phase3.release_gate.close accepted=true
  -> scheduler.live_dispatch.t_relay.day1.scan.close accepted=true
  -> scheduler.live_dispatch.t_relay.day2.watch.rolling_5m accepted=true
  -> scheduler.live_dispatch.t_relay.day2.trigger.rolling_5m accepted=true
```

推荐执行：

```bash
python scripts/core_services_acceptance.py --require-postgres
```

如果需要把当前生产必需 provider 真实 probe 纳入同一轮验收：

```bash
python scripts/core_services_acceptance.py --require-postgres --real-provider-probe
```

`--real-provider-probe` 会按 `source-data-service /source/probe/matrix` 中 `real_probe_required=true` 的当前必需项执行真实探针，覆盖 BaoStock P0 基础源、Tencent `daily_bars`、Sohu `daily_bars` 个股金额/涨跌幅备源和模型四 EastMoney `quote_snapshot/minute_bars/trade_details`。脚本默认输出 compact evidence，用于日常逐项验收和定位阻断项；需要核对完整 scheduler sample、owner response 或 source-data-service 响应时，追加 `--verbose-evidence`。compact 输出不改变 live dispatch 的非 dry-run 行为，也不允许 scheduler 把 sample payload 当作 source 事实。

## Readyz 与启动守卫

默认 `current_closure` 模式下，`GET /readyz` 必须同时满足：

- 后台 heartbeat 循环存活且心跳未过期。
- `data-inspector-service /readyz` 返回 ready 或 ok。
- scheduler 本次触发的 `startup_guard` 返回 ready/passed/ok/completed 且 P0/P1 缺口为 0。
- `data-inspector-service` 在 `SCHEDULER_GUARD_TRADE_DATE` 对应交易日内最新持久化 `startup_guard` 和 `core_closure` 巡检均为 ready/passed/ok/completed 且 P0/P1 缺口为 0。
- `source-data-service /readyz` 返回 ready 或 ok。
- `/source/ops/production-readiness?require_postgres=true&require_real_provider_probe=true` 返回 passed 且 `can拍板=true`。
- `/source/fetch/queues/summary` 所有队列 `dead_letter_count=0`；`leased_count` 表示 `source-data-worker` 正在处理中的采集进度，必须在 runtime details 中展示，但不再作为 scheduler readyz 硬阻断。
- `scheduler_source_time_wheel_v1` 常驻启用，当前窗口内的非临时 source 调度只提交 source-data-service 受控端点；过期窗口不由 time wheel 自动追发，发现缺口、发布滞后或错过窗口时必须使用 `POST /scheduler/source-schedule/catch-up` 复用正式 registry 实例追补，不得把 temporary fetch 当作非临时闭环。
- `hot-candidates-service`、`candidate-memory-service`、`ambush-watchlist-service`、`t-board-relay-service` 的 `/readyz` 返回 ready 或 ok。
- 三条 source release preflight 全部 `can_release_official_signal=true` 且 `blocking_reasons=[]`：`hot_candidates/preopen_release_gate`、`candidate_memory/outcome_label`、`ambush_watchlist/release_gate`。若 `SCHEDULER_GUARD_TRADE_DATE` 是历史验收/回放日期，且 coverage passed、blocking reasons 全部为 `:late`，scheduler 可把该 late 作为历史可见性审计而非服务 readyz 阻断；source preflight 原始结果仍必须保留 blocked。
- 模型四 source release preflight 全部 `can_release_official_signal=true` 且 `blocking_reasons=[]`：`t_board_relay/day1_scan`、`t_board_relay/day2_trigger`。模型四 guard symbol 使用 `SCHEDULER_T_BOARD_GUARD_SYMBOL`，默认 `000759.SZ`。同样仅允许历史验收/回放日期的 coverage passed + `:late` only blocker 不阻断 scheduler readyz；`missing`、`stale`、coverage blocked 或当前/实时交易日 `late` 仍必须阻断。

`current_closure` 调用 `/source/release/preflight` 时必须显式传入 official decision time，避免 readyz 用非官方时点得到假绿。当前决策时间矩阵为：`hot_candidates/preopen_release_gate=09:29:40 Asia/Shanghai`、`candidate_memory/outcome_label=16:05:00`、`ambush_watchlist/release_gate=16:05:00`、`t_board_relay/day1_scan=15:10:00`、`t_board_relay/day2_trigger=09:30:00`。`checks.closure_guard.details.preflight.*.decision_time` 必须暴露实际请求时间；任一当前/实时 official 时点 source coverage/freshness blocked 都会让 `/readyz` 返回 not_ready。唯一例外是历史验收/回放日期：当 guard date 早于当前市场日期、coverage passed 且全部 blocker 以 `:late` 结尾时，`checks.closure_guard.details.preflight.*` 必须保留 `can_release_official_signal=false`、原始 `blocking_reasons`、`historical_late_observed=true`、`ignored_for_readyz=true` 和 `official_release_preflight_still_blocked=true`；这只表示后补数据已存在但晚于历史 decision time，不得被任何 official release、model payload preflight 或 owner dispatch 解释成 source gate 已通过。

`GET /scheduler/runtime/status` 会在 `checks.data_inspector`、`checks.startup_guard` 和 `checks.closure_guard.details` 返回上述检查的 compact details，用于定位 data-inspector、source、模型、队列或 preflight 阻断。任何 source、模型、preflight、队列或真实巡检 blocked 都不能被包装成 ready。`core_closure` 因自身检查 `scheduler-service /readyz` 形成的唯一 `scheduler_ready` P0 自依赖缺口，会在 scheduler 已经完成直接 source/model/preflight 检查后记录为 `self_dependency_ignored=true`，避免 `/readyz` 和 `core_closure` 互相等待；除此之外的任何 P0/P1 仍然阻断。

`legacy_data_inspector` 模式仅在需要兼容旧全栈巡检时启用。默认 `current_closure` 和 legacy 模式都会先检查 `data-inspector-service /readyz`，再调用 `POST /inspection-runs`：


```json
{
  "scope": "startup_guard",
  "as_of_trading_day": "<SCHEDULER_GUARD_TRADE_DATE>",
  "as_of_time": "<utc-iso-time>",
  "lookback_days": 20,
  "max_subjects": 500,
  "persist": true
}
```

若 data-inspector 暂时不可用，runtime 会在后台循环中按 `DATA_INSPECTION_STARTUP_GUARD_RETRY_ATTEMPTS` 继续重试；启动巡检未完成、请求失败、返回 `blocked` 或 P0/P1 缺口大于 0 时 `/readyz` 返回 503。旧 data-inspector 的旧 `market.*` 巡检结果不得覆盖当前最小闭环事实。

关键环境变量：

- `SCHEDULER_GUARD_MODE`：默认 `current_closure`；可选 `legacy_data_inspector`。
- `SOURCE_DATA_SERVICE_BASE_URL`：默认 `http://source-data-service:8041`。
- `HOT_CANDIDATES_SERVICE_BASE_URL`：默认 `http://hot-candidates-service:8031`。
- `CANDIDATE_MEMORY_SERVICE_BASE_URL`：默认 `http://candidate-memory-service:8032`。
- `AMBUSH_WATCHLIST_SERVICE_BASE_URL`：默认 `http://ambush-watchlist-service:8033`。
- `T_BOARD_RELAY_SERVICE_BASE_URL`：默认 `http://t-board-relay-service:8034`。
- `SCHEDULER_GUARD_TRADE_DATE`：默认当前验收样例 `2026-06-12`，生产应显式传最近有效交易日。
- `SCHEDULER_GUARD_SYMBOL`：默认当前验收样例 `000063.SZ`。
- `SCHEDULER_T_BOARD_GUARD_SYMBOL`：默认模型四真实闭环样例 `000759.SZ`。
- `SCHEDULER_REQUIRED_MODEL_SERVICES`：代码默认 `all`，生产严格模式下四个模型 owner `/readyz` 都是 `current_closure` 硬依赖；当前热点模型恢复与模型四连续监测阶段 Compose 默认 `hot_candidates,t_board_relay`，表示热点 owner 与模型四 owner 必须 ready 并可进入 model time wheel live dispatch，candidate_memory/ambush 在 `/scheduler/runtime/status` 中记录为 `disabled_by_policy`，不触发模型 DNS 探测，不阻断 source/scheduler 底座 ready。可填写 `none`、`t_board_relay`、`hot_candidates,t_board_relay`、`hot_candidates,candidate_memory` 或 owner service 名；只有列为 required 的模型 owner readyz 不可达才阻断 `/readyz`。
- `DATA_INSPECTOR_SERVICE_BASE_URL`：默认 `http://data-inspector-service:8025`。
- `SCHEDULER_RUNTIME_POLL_SECONDS`：后台循环间隔，默认 30 秒。
- `SCHEDULER_RUNTIME_REQUEST_TIMEOUT_SECONDS`：ready 快速探针超时，默认 5 秒；source time wheel 提交 `/source/fetch/submit` 使用独立预算 `max(request_timeout * 6, 30)` 秒，任务 lease 使用 `max(submit_timeout * 2, 60)` 秒，避免全 A 批量计划展开时被 ready 快速探针预算误杀。submit 非 2xx 或客户端异常/超时必须立即写入本地 task store failure/retry 审计，并在 `scheduler_source_time_wheel_v1.details.dispatched[]` 暴露 `submit_failed` 或 `submit_exception`，不得让任务长期停留在 `running` 等待 lease 过期。
- `DATA_INSPECTION_STARTUP_GUARD_TIMEOUT_SECONDS`：启动巡检请求超时，默认 60 秒。
- `DATA_INSPECTION_STARTUP_GUARD_SCOPE`：默认 `startup_guard`。
- `DATA_INSPECTION_LOOKBACK_DAYS`：默认 20。
- `DATA_INSPECTION_MAX_SUBJECTS`：默认 500。
- `DATA_INSPECTION_STARTUP_GUARD_RETRY_ATTEMPTS`：默认 12。
- `SCHEDULER_SOURCE_TIME_WHEEL_ENABLED`：默认 `true`，启用非临时 source 调度时间轮。
- `SCHEDULER_SOURCE_TIME_WHEEL_LIVE_SUBMIT`：默认 `true`，到点任务提交 `source-data-service /source/fetch/submit`。
- `SCHEDULER_SOURCE_TIME_WHEEL_SYMBOLS`：默认 `000063.SZ,000759.SZ`，只影响 `symbol_scope=configured_symbols` 或人工传入的 `stage_candidates` 窗口任务；`symbol_scope=full_a_share` 的日频全 A 调度必须物化为 `symbols=[]` + `universe_scope=full_a_share`，不得继承该配置样本。
- `SCHEDULER_SOURCE_TIME_WHEEL_LATENESS_SECONDS`：默认 `90`，超过该窗口的历史任务不由常驻 time wheel 自动追发，避免重启后误提交过期窗口；正式缺口追补必须走 `POST /scheduler/source-schedule/catch-up`，并保留原始 schedule `biz_key`/`idempotency_key` 口径。
- `SCHEDULER_SOURCE_TIME_WHEEL_MAX_DISPATCH`：默认 `20`，单轮最多提交的 source fetch 任务数。
- `SCHEDULER_MODEL_TIME_WHEEL_ENABLED`：默认 `true`，启用三/四模型 owner 任务时间轮，只处理非 `source_collect` 模型任务。
- `SCHEDULER_MODEL_TIME_WHEEL_LIVE_DISPATCH`：代码默认 `false`，Compose 生产候选默认显式设为 `true`；为 `true` 时，模型任务时间轮调用 `research-service /research/model-execution/run`，不直连 owner endpoint。`blocked_data_gap`、`materialized_with_gaps`、`materialization_skipped` 属于已审计终态，不重试、不伪装成成功；HTTP 非 2xx、`owner_failed`、`materialization_failed`、异常或本地存在 `retry_ready/dead_letter` 时会让 `scheduler_model_time_wheel_v1` 进入 `failed` 并阻断 `/readyz`。
- `SCHEDULER_REQUIRED_MODEL_SERVICES=hot_candidates,t_board_relay` 是当前 Compose 默认值：热点模型盘前评分、release gate、买点/观察/outcome/evolution 任务以及模型四 Day1/Day2/触发后监控/Day3/outcome 任务可以进入模型时间轮和 research execution；candidate_memory/ambush 暂停并记录 `disabled_by_policy`。
- `SCHEDULER_REQUIRED_MODEL_SERVICES=none` 时，模型时间轮仍可运行但不会入队或 live dispatch 暂停全部模型 owner 的任务，只在 `details.skipped[]` 记录 `disabled_by_policy`；本地 retry/dead-letter readiness guard 只统计 required owner services，避免暂停中的模型历史任务拖垮数据底座。该策略不改变 source preflight、source queue、startup_guard 或 research payload preflight 的硬门禁。
- `SCHEDULER_MODEL_TIME_WHEEL_INCLUDE_RESEARCH_INTRADAY`：默认 `false`，可选加入 10:30 research-only 任务，加入后仍不得发布 official signal。
- `SCHEDULER_MODEL_TIME_WHEEL_LATENESS_SECONDS`：默认 `90`，超过窗口的模型任务不追发，避免重启后误触发过期 release gate 或研究任务。
- `SCHEDULER_MODEL_TIME_WHEEL_MAX_DISPATCH`：默认 `20`，单轮最多 live dispatch 的模型 owner 任务数。
- `SCHEDULER_MARKET_TIMEZONE`：默认 `Asia/Shanghai`，用于交易日任务实例化。
- `SCHEDULER_TASK_STORE_PATH`：代码默认系统临时目录下的 `ai_stock_scheduler_task_store.sqlite3`；Compose 生产候选默认 `/var/lib/ai_stock_scheduler/task_store.sqlite3`，并挂载 `scheduler_task_store` 命名卷，保存本服务本地 task lease、terminal blocked、retry、dead-letter 和 dispatch audit；source fetch 真实生产队列仍以 source-data-service Postgres queue 为准。

## 三模型任务链

Hot candidates：

```text
source.auction.collect.0915_0925
-> source.auction.freeze.092505_092530
-> hot.score.auction_confirmed
-> hot.release_gate.preopen
-> source.open_5m.collect
-> hot.buy_point.open_5m
-> hot.observe.intraday
-> hot.outcome.t5_t20
-> hot.evolution.offline
```

Candidate memory：

```text
memory.seed.from_hot_signals
-> memory.pre_signal.scan
-> memory.release_gate.close
-> memory.buy_point.next_session_reference
-> memory.observe.outcome.evolution
```

Ambush watchlist：

```text
ambush.source_capability.audit
-> ambush.pattern_library.mine
-> ambush.phase2.valley_turn.close
-> ambush.phase3.release_gate.close
-> ambush.buy_point.reference
-> ambush.observe.outcome.evolution
```

T-board relay：

```text
t_relay.day1.scan.close
-> t_relay.day2.watch.rolling_5m
-> t_relay.day2.trigger.rolling_5m
-> t_relay.day2.post_entry.monitor
-> t_relay.day3.exit.open
-> t_relay.day3.exit.tail
-> t_relay.observation.monitor.snapshot_5m
-> t_relay.live_result.compute_30m
-> t_relay.outcome.build
```

## Source 数据调度频率

非临时 source 调度已经代码化为 `source_fetch_schedule_registry_v1`，运行入口为 `scheduler_source_time_wheel_v1`。scheduler 负责调度频率、交易日实例、幂等键、本地 task lease/retry/dead-letter、`symbol_scope` 到 `universe_scope` 的物化和到点提交；数据新增、补采和真实 provider 请求必须提交给 `source-data-service`，常规链路由 `/source/fetch/plan` -> `/source/fetch/submit` -> worker -> raw -> quality -> source -> lineage 执行。`source.ths_paid_limit_up_probability_v1` 使用 source-data-service 暴露的受控 `/source/ths/paid-probability/*` 端点，scheduler 不接触 Cookie、不构造 provider 参数、不直接访问 THS。scheduler 不得直接并发调用 BaoStock、AKShare、Tencent、Tushare、EastMoney、Baidu、CNINFO、THS、Sina、Sohu 或其它 provider。

`SourceFetchScheduleSpec.symbol_scope` 是调度范围硬合同：`none` 不传股票集合；`full_a_share` 物化为 `symbols=[]` 和 `universe_scope=full_a_share`，由 source-data-service 从 source 层展开；`configured_symbols` 只使用 `SCHEDULER_SOURCE_TIME_WHEEL_SYMBOLS` 或 spec 默认小集合；`stage_candidates` 优先使用模型阶段专用候选，人工验收或定向补跑可显式传入 `explicit_model_stage_candidates`，缺候选时不得自动退回全 A 或配置样本。

模型四 Day1 不做全 A 高频/报价盲扫。正式链路先由 `t_relay_day1_window` 通过 THS 公开涨停池构建 `source.limit_event_v1`，scheduler 再只读 `source-data-service /source/rows` 取出 `limit_event_type=t_board_limit_up` 或 `is_break_limit=true` 且 `close_on_limit_flag` 未明确为 false 的 T 字板阶段候选。随后 `t_relay_day1_candidate_facts` 只对这些候选补 `source.trade_status_v1`、`source.daily_bar_v1`、`source.limit_price_v1` 和 `source.realtime_quote_v1.float_market_cap`。Day2 逐笔窗口继续使用显式模型阶段候选，不把当天涨停池候选和次交易日 Day1 合格候选混同。

模型任务时间轮和 `POST /scheduler/model-schedule/catch-up` 对 `t_relay.day1.scan.close` 使用同一候选口径：调度 payload 必须从当日 `source.limit_event_v1` 的 T 字板阶段候选生成 `symbols[]`，并把 `stage_candidate_source=t_relay_limit_event_t_board`、候选数量和原始调度实例写入 `_scheduler_materialized_instance`。`SCHEDULER_T_BOARD_GUARD_SYMBOL` 只用于 readyz/source preflight guard 和样例合同，不得作为 Day1 scan 的生产候选回退。若当日没有真实 T 字板阶段候选，scheduler 必须把该任务记为 `blocked_data_gap`，保留 `source_gap:t_relay_day1_stage_candidates_missing`，且不得调用 `research-service /research/model-execution/run`，避免 research-service 回落默认样本股。

| 频率 | 调度对象 | symbol_scope -> universe_scope | 对应 source-data-service 接口 | source 表 | 队列/优先级 | 说明 |
|---|---|---|---|---|---|---|
| 一次性/初始化 | 交易日历、股票主数据、provider symbol map | 交易日历 `none -> explicit_symbols`；股票主数据 `full_a_share -> full_a_share` | `/source/fetch/plan`、`/source/fetch/submit`、`/source/build/worker/run-once` | `source.trade_calendar_v1`、`source.stock_master_v1` | `normal_daily_ingest_queue` 或 `backfill_queue` | 首次上线最高优先级；交易日历先于所有 T+N、买点和 outcome。 |
| 日调度盘前 | 当日 universe、交易状态、停牌/ST/退市风险、涨跌停价格 | `full_a_share -> full_a_share` | `/source/fetch/plan`、`/source/fetch/submit` | `source.stock_universe_daily_v1`、`source.trade_status_v1`、`source.limit_price_v1` | `normal_daily_ingest_queue`；`limit_price` 走 `urgent_release_gate_queue` | 09:05-09:12 完成，阻断 official release 时不得降级为可交易。 |
| 日调度收盘 | 未复权日线、前复权日线 | `full_a_share -> full_a_share` | `/source/fetch/plan`、`/source/fetch/submit`、`/source/build/worker/run-once` | `source.daily_bar_v1`、`source.adjusted_daily_bar_v1` | `normal_daily_ingest_queue` | 15:35-17:00 完成，供三模型收盘任务和模型四 Day1 scan。 |
| 日调度付费概率 | 同花顺付费次日概率 | `none -> explicit_symbols`；由 source 候选批次决定对象 | `/source/ths/paid-probability/fetch-current-batch` | `source.ths_paid_limit_up_probability_v1` | `P0_urgent_release` | 15:20、16:05、18:00、20:30；source-data-service 先 probe Cookie，再提交付费概率 fetch。 |
| 日调度截止守卫 | 未补齐付费概率候选批次 | `none -> explicit_symbols` | `/source/ths/paid-probability/deadline-check` | `governance.ths_paid_probability_batch_status_v1` | `P0_urgent_release` | 每日 09:01；仅候选交易日的下一交易日 09:00 后仍缺概率时才放弃该批。 |
| 日调度收盘后 | 资金流、事件新闻、板块/题材上下文 | 资金流 `full_a_share -> full_a_share`；新闻/事件 `none -> explicit_symbols` | `/source/fetch/plan`、`/source/fetch/submit` | `source.stock_moneyflow_daily_v1`、`source.event_news_v1`、`source.stock_board_membership_v1` | `research_queue` 或 `normal_daily_ingest_queue` | P1/P2 上下文缺失时保留 degraded/research-only 缺口。 |
| 分钟级 09:15-09:25 | 集合竞价快照 | `configured_symbols -> explicit_symbols` | `/source/fetch/plan`、`/source/fetch/submit` | `source.auction_snapshot_v1` canonical fields=`virtual_open_price,matched_volume,matched_amount,event_time` | release 相关走 `urgent_release_gate_queue` | 热点盘前 release gate 只读消费该事实，不做全 A 分钟级常规调度；scheduler 不提交 provider raw 字段 `price/volume/amount/provider_definition`。 |
| 分钟级 09:30-15:00 | 报价、分钟线、开盘 5 分钟和盘中观察 | `configured_symbols -> explicit_symbols` | `/source/fetch/plan`、`/source/fetch/submit` | `source.realtime_quote_v1`、`source.minute_bar_v1` | `urgent_release_gate_queue` for P0 windows, otherwise normal | source 高频窗口由 scheduler source time wheel 到点提交 fetch orchestration，provider 并发仍由 source-data-worker 控制。 |
| 窗口级 09:30-10:30 每 5 分钟 | 模型四 Day2 滚动接近涨停观察 | `stage_candidates -> stage_candidates` | `/source/fetch/plan`、`/source/fetch/submit` | `source.trade_tick_v1` | `urgent_release_gate_queue` | 只抓 Day1 合格或阶段候选；首次接近涨停即触发机会提示，缺逐笔或动态特征时保持 `source_gap:*`，不得补 0 或 mock。 |
| 窗口级 10:40/14:55/15:02/15:10 | 模型四涨停事件确认 | `full_a_share -> full_a_share` | `/source/fetch/plan`、`/source/fetch/submit` | `source.limit_event_v1` | `urgent_release_gate_queue` | Day1 scan 和 post-entry monitor 的 P0 事件事实；缺失时阻断 payload，不降级成 sample。 |
| 窗口级 15:12/15:20/15:30/15:35/15:45 | 模型四 Day1 T 字板候选事实补齐 | `stage_candidates -> stage_candidates`，候选源为 `t_relay_limit_event_t_board` | `/source/fetch/plan`、`/source/fetch/submit` | `source.trade_status_v1`、`source.daily_bar_v1`、`source.limit_price_v1`、`source.realtime_quote_v1` | `urgent_release_gate_queue` | 先扫 `source.limit_event_v1` 的涨停池/T 字板事件，再只对候选补 Day1 qualification 所需事实；没有候选时跳过，不继承配置样本。 |
| 巡检/修复触发 | data-inspector P0/P1 缺口 | 按缺口请求显式传入，必要时 `full_a_share` | `/source/gaps/diagnose`、`/source/gaps/repair-plan`、`/source/fetch/submit` | 按 source requirement | `repair_queue` 或 `urgent_release_gate_queue` | scheduler 只等待 source/data-inspector ready，不直接修表。 |

代码级校验：

```text
GET /scheduler/source-schedule/registry
GET /scheduler/validate/source-schedule
GET /scheduler/materialize/source-schedule?trading_day=2026-06-12&symbols=000063.SZ,000759.SZ&include_one_time=true
POST /scheduler/source-time-wheel/run-once
POST /scheduler/source-schedule/catch-up
```

当前 registry 事实：

```text
registry_version=source_fetch_schedule_registry_v1
schedule_count=20
groups=daily_close,daily_close_paid_probability,daily_preopen,daily_preopen_paid_probability_guard,daily_research_context,minute_auction,minute_intraday,one_time_initial,t_relay_day1_candidate_facts,t_relay_day1_window,t_relay_day2_window
materialize explicit symbols include_one_time=true -> instance_count=734
t_relay_day1_candidate_facts -> 12 instances for two explicit symbols; without stage candidates this group is skipped instead of inheriting configured samples
```

时间轮只 materialize 当前 UTC 时间落在 `scheduled_at - SCHEDULER_SOURCE_TIME_WHEEL_LATENESS_SECONDS <= now <= scheduled_at` 的任务；重启后不会自动追发已经过期的竞价、开盘 5 分钟或 Day2 窗口任务。`POST /scheduler/source-schedule/catch-up` 是非临时 source 调度的正式追补/对账入口，必须从 `source_fetch_schedule_registry_v1` 物化实例，支持按 `schedule_codes`、`schedule_groups`、`source_table_names`、`run_slots`、`include_one_time` 和交易日筛选，默认 `dry_run=true`；非 dry-run 只写入 scheduler 本地 task store，并在 `dispatch_immediately=true` 时转交 source-data-service 受控端点。该入口不属于 temporary fetch，不允许绕过 registry、provider、raw、quality gate 或 lineage。默认复用原始 schedule `biz_key`/`idempotency_key`；当对账证明旧 scheduler task 已 success 但 source row/build/lineage 未产出时，可显式传 `force_resubmit=true` 和 `catch_up_run_id`，生成带 `:catchup:<run_id>` 后缀的新 task/source 幂等键重提。同花顺付费概率抓取和 deadline guard 默认被 catch-up 阻断，必须显式传入 `allow_ths_paid_probability_fetch=true` 或 `allow_ths_paid_probability_deadline_guard=true` 才能选择对应受控端点，避免误触发历史付费批次。常规 `/source/fetch/submit` 提交体必须包含 `source_table_name`、`canonical_fields`、`trigger_type`、`priority`、`request_source=scheduler-service` 和稳定 `idempotency_key`；同花顺付费概率两个受控端点只携带 source-data-service 定义的批次请求体和内部 `__source_endpoint_path`，runtime 提交前必须移除该内部键。

`scheduler_source_time_wheel_v1` 收到 `/source/fetch/submit` 2xx 只表示 source fetch batch 已被 source-data-service 接收；runtime details 使用 `source_result_status=submit_accepted_pending_source_build`，不得把该状态解释为 raw/source/lineage 已经产出。只有 source-data-service 的 raw ingest、quality gate、`source_build_trigger`、source build 和 lineage 成功后，下游 preflight 才能认定 source rows 可用。

`daily_preopen` ??? A ????????? universe????????????????????????`orchestration_context.lifecycle_expires_at` ??????? Asia/Shanghai `23:59:59`?????????????????????????????????????????? raw/source/lineage??????????????????? repair/backfill??????????????????????????????????????????

临时取数入口：

```text
POST /scheduler/source-fetch/temporary
```

该接口只用于其他服务显式临时取数或人工补充请求，默认 `dry_run=true`，非 dry-run 时也只转交 `source-data-service /source/fetch/submit`。临时请求不得使用 `trigger_type=scheduled_periodic`，不得进入 `source_fetch_schedule_registry_v1`，不得直接写 provider 参数或 raw 表。

唯一允许发布官方信号的任务是：

```text
hot.release_gate.preopen
memory.release_gate.close
ambush.phase3.release_gate.close
```

source、score、buy point、observation、outcome、evolution、pattern library、valley turn、research intraday 和全部 `t_relay.*` 任务都不得发布 official signal。

## Live Dispatch 合同

模型任务时间轮 live dispatch 版本是 `scheduler_research_model_execution_dispatch_v1`。`scheduler_model_time_wheel_v1` 只调用 `research-service /research/model-execution/run`，由 research-service 完成 payload 组装、owner 调用、owner 输出物化和 `governance.research_model_execution_audit_v1` 审计。scheduler 不直接读取 raw 表，不直接采集 provider，不写 `decision_hot.*`、`decision_memory.*`、`decision_ambush.*`、`decision_t_relay.*` 或 `research_t_relay.*`。

`three_model_live_dispatch_v1` 仍作为 `POST /scheduler/trigger` 和样例合同校验的显式触发适配器，不是非临时模型任务时间轮的 owner 直连路径。

| Task code | Owner service | Owner endpoint |
|---|---|---|
| `source.auction.collect.0915_0925` | `source-data-service` | `POST /source/fetch/submit` |
| `source.auction.freeze.092505_092530` | `source-data-service` | `POST /source/fetch/submit` |
| `source.daily.ths_paid_probability_fetch` | `source-data-service` | `POST /source/ths/paid-probability/fetch-current-batch` |
| `source.daily.ths_paid_probability_deadline_guard` | `source-data-service` | `POST /source/ths/paid-probability/deadline-check` |
| `hot.score.auction_confirmed` | `hot-candidates-service` | `POST /production/scores/compute` |
| `hot.release_gate.preopen` | `hot-candidates-service` | `POST /production/release-gate/evaluate` |
| `source.open_5m.collect` | `source-data-service` | `POST /source/fetch/submit` |
| `hot.buy_point.open_5m` | `hot-candidates-service` | `POST /production/buy-point/evaluate` |
| `hot.observe.intraday` | `hot-candidates-service` | `POST /production/observations/bulk` |
| `hot.outcome.t5_t20` | `hot-candidates-service` | `POST /production/outcomes/mature` |
| `hot.evolution.offline` | `hot-candidates-service` | `POST /production/evolution/build` |
| `memory.seed.from_hot_signals` | `candidate-memory-service` | `POST /production/seed/build` |
| `memory.pre_signal.scan` | `candidate-memory-service` | `POST /production/pre-signal/detect` |
| `memory.release_gate.close` | `candidate-memory-service` | `POST /production/release-gate/evaluate` |
| `memory.buy_point.next_session_reference` | `candidate-memory-service` | `POST /production/buy-point/evaluate` |
| `memory.observe.outcome.evolution` | `candidate-memory-service` | `POST /production/outcomes/mature` |
| `ambush.source_capability.audit` | `ambush-watchlist-service` | `POST /ambush/source-capability-audit` |
| `ambush.pattern_library.mine` | `ambush-watchlist-service` | `POST /ambush/historical-valley-sample-label` |
| `ambush.phase2.valley_turn.close` | `ambush-watchlist-service` | `POST /ambush/phase2/run` |
| `ambush.phase3.release_gate.close` | `ambush-watchlist-service` | `POST /ambush/phase3/run` |
| `ambush.buy_point.reference` | `ambush-watchlist-service` | `POST /ambush/phase3/run` |
| `ambush.observe.outcome.evolution` | `ambush-watchlist-service` | `POST /ambush/phase4/outcome` |
| `t_relay.day1.scan.close` | `t-board-relay-service` | `POST /t-board-relay/day1/scan` |
| `t_relay.day2.watch.rolling_5m` | `t-board-relay-service` | `POST /t-board-relay/day2/watch` |
| `t_relay.day2.trigger.rolling_5m` | `t-board-relay-service` | `POST /t-board-relay/day2/trigger-check` |
| `t_relay.day2.post_entry.monitor` | `t-board-relay-service` | `POST /t-board-relay/post-entry/monitor` |
| `t_relay.day3.exit.open` | `t-board-relay-service` | `POST /t-board-relay/day3/exit-check` |
| `t_relay.day3.exit.tail` | `t-board-relay-service` | `POST /t-board-relay/day3/exit-check` |
| `t_relay.observation.monitor.snapshot_5m` | `t-board-relay-service` | `POST /t-board-relay/observation-monitor/snapshot` |
| `t_relay.live_result.compute_30m` | `t-board-relay-service` | `POST /t-board-relay/observation-monitor/snapshot` |
| `t_relay.outcome.build` | `t-board-relay-service` | `POST /t-board-relay/outcomes/build` |

owner 请求体适配规则：

- `hot-candidates-service` 使用顶层 `payload`，示例：`{ "payload": { ... }, "run_id": "...", "as_of_time_utc": "..." }`。
- `candidate-memory-service` 使用顶层 `row`，示例：`{ "row": { ... }, "run_id": "...", "as_of_time_utc": "..." }`；`memory.seed.from_hot_signals` 的正式执行由 research-service 串联 seed 与 entity build。
- `ambush-watchlist-service` 接收阶段 payload 本体。
- `t-board-relay-service` 的 Day1 scan 使用 `rows`；Day2/Day3/outcome 使用 `payload`。

`_scheduler_context` 只用于调度审计，包含 `task_code`、`task_kind`、`owner_service`、`append_only`、`is_official_publish`、`reads_from` 和 `writes_to`。它不授予 scheduler 修改模型事实、分数、状态、标签、发布闸门或学习权重的权限。

## 交易日实例化

`GET /scheduler/materialize/three-models` 调用 `materialize_three_model_day`，按交易日生成确定性的任务实例：

- 每个实例有稳定 `biz_key`。
- 每个实例有稳定 `idempotency_seed`。
- `include_research_intraday=true` 只增加 non-official 研究任务。
- 高频 source 窗口由 `scheduler_source_time_wheel_v1` 提交 source fetch 任务；模型 owner 任务仍只接收 research-service 组装和转交的业务 payload，scheduler 不伪造模型输入。

## 模型任务时间轮

`scheduler_model_time_wheel_v1` 是三/四模型非临时 owner 任务的常驻调度入口，复用 `three_model_materializer_v1` 生成交易日实例，并复用本地 `ai_stock_scheduler_task_store.sqlite3` 的 `task_instance_v1`、`task_lease_v1`、`task_run_log_v1` 和 `task_dead_letter_v1` 记录入队、lease、retry、dead-letter 与 dispatch audit。

运行口径：
- 默认 `SCHEDULER_MODEL_TIME_WHEEL_ENABLED=true`，runtime 每轮按当前 `Asia/Shanghai` 交易日物化任务，只入队 `hot-candidates-service`、`candidate-memory-service`、`ambush-watchlist-service`、`t-board-relay-service` 四类 owner 任务；`source_collect` 任务仍由 `scheduler_source_time_wheel_v1` 和 `source-data-service /source/fetch/submit` 承担。
- 默认 `SCHEDULER_MODEL_TIME_WHEEL_LIVE_DISPATCH=false`，scheduler 只完成模型任务入队、幂等、lease 前置审计和状态展示，不调用 owner endpoint，不生成模型事实，也不伪造模型输入。
- 显式开启 `SCHEDULER_MODEL_TIME_WHEEL_LIVE_DISPATCH=true` 后，scheduler 调用 `RESEARCH_SERVICE_BASE_URL/research/model-execution/run`；research-service 负责 owner 调用和物化，scheduler 不直连 owner service。
- 自动入队 payload 只包含 `scheduler_payload_status=blocked_payload_assembly_required`、`source_gap_codes=["scheduler_payload_assembly_required"]`、`contract_gaps=["scheduler_payload_assembly_required"]` 和 `_scheduler_materialized_instance` 审计上下文；缺真实研究输入时必须保留缺口，不得用 sample payload、0、空字符串或 GPT 推断补齐。
- live dispatch 中 research execution 返回 `accepted=false`、HTTP 非 2xx、异常、`retry_ready` 或 `dead_letter` 未清空时，`scheduler_model_time_wheel_v1` 状态为 `failed`，`/readyz` 必须进入 `not_ready`；默认非 live 入队成功时可保持 ready/idle。

## 模型 Payload 预检

`scheduler_model_payload_preflight_v1` 是模型任务 live dispatch 前的硬门禁。真实生产 payload 必须由 `research-service` 的研究组装层显式声明 `payload_assembly_contract=research_model_payload_assembler_v1`、`payload_assembly_status=assembled_research_payload` 和非空 `payload_assembly_source`；三条 official release gate 还必须携带 `source_preflight`，且 `can_release_official_signal=true`、`blocking_reasons=[]`、coverage/freshness passed。

只读合同入口：

```text
GET /scheduler/model-payload/requirements
POST /scheduler/model-payload/preflight
POST /scheduler/model-payload/assemble-preflight
```

`POST /scheduler/model-payload/assemble-preflight` 返回 `scheduler_research_payload_assemble_preflight_v1`，用于显式联调真实 payload：scheduler 调用 `research-service /research/model-payload/assemble`，取回 payload 后立即执行现有 `scheduler_model_payload_preflight_v1`，并且只在预检通过时返回 owner request body preview。该接口不调用模型 owner endpoint，不写模型事实，默认 `persist_audit=false`；调用方显式传 `persist_audit=true` 时，审计写入仍由 `research-service` 的 append-only 表负责。若 research-service 返回 `blocked_data_gap`，或 source preflight 因 `decision_time/as_of_time_utc` 可见性判定为 late/stale/missing，scheduler 必须返回 `dispatch_allowed=false`，不得用当前健康检查口径、sample payload、0、空字符串或推断值改写为可派发。

`POST /scheduler/model-schedule/catch-up` 返回 `scheduler_model_schedule_catch_up_v1`，用于补偿因服务未运行、发布窗口错过或迟到窗口过窄而没有进入本地 task store 的模型任务实例。该入口默认 `dry_run=true`，按 `trading_day`、`task_codes`、`owner_services`、`run_slots` 和 `max_instances` 从 `three_model_materializer_v1` 中筛选实例；非 dry-run 只写入 scheduler 本地 task store，`dispatch_immediately=true` 时也只调用 `research-service /research/model-execution/run`。默认复用原 `biz_key` 保持幂等；只有显式 `force_resubmit=true` 时才追加 `:catchup:<catch_up_run_id>`。模型四 `t_relay.observation.monitor.snapshot_5m` 与 `t_relay.live_result.compute_30m` 的 catch-up payload 会把实际补偿时间写入 `as_of_time_utc`，并在 `_scheduler_materialized_instance` 中保留原始 `scheduled_at/run_slot`、`catch_up_run_id`、`captured_late` 和 `catch_up_checked_at`；其中 5 分钟快照只表示实际补偿时刻的当前投影，30 分钟快照才表示模型结果版本，二者都不得被解释为原计划槽位的历史实时盘口事实。

2026-06-27 热点调度合同修正：`hot.score.auction_confirmed`、`hot.release_gate.preopen`、`hot.buy_point.open_5m` 的 `model-schedule/catch-up` 与模型时间轮仍只负责物化时间槽、写本地 task store 和调用 `research-service /research/model-execution/run`。scheduler 可以在调度实例中保留 guard/sample symbol 作为审计上下文，但生产候选 fanout 必须由 research-service 从真实 `source.ths_paid_limit_up_probability_v1` 或已评分 `decision_hot.hot_decision_case_v1 + hot_score_fact_v1` 读取；不得把 `000063.SZ`、`SCHEDULER_GUARD_SYMBOL`、sample payload 或用户传入的单个占位 symbol 当作热点 release/buy-point 生产候选。

同一修正下，`hot.buy_point.open_5m` 计划读取 `decision_hot.hot_decision_case_v1`、`decision_hot.hot_score_fact_v1`、`source.minute_bar_v1` 和 `source.auction_snapshot_v1`。`decision_hot.hot_release_gate_audit_v1` 与 `decision_hot.hot_signal_fact_v1` 可作为后续观察/发布事实，但不是 buy-point 诊断产出的硬前置。该任务产出的 `blocked` buy-point 是 owner 诊断事实，不是交易指令；scheduler 不写 `decision_hot.hot_buy_point_v1`、不生成 `hot_signal_fact_v1`、不把 owner 2xx 解释成 official signal。

硬规则：

- `scheduler_payload_assembly_required`、`blocked_payload_assembly_required`、`scheduler_live_dispatch_contract_sample` 或 `sample-*` payload 一律不得 live dispatch。
- 预检失败时，显式 assemble-preflight 不触达 owner；正式 model time wheel live dispatch 由 research-service 在 payload assembly 阻断时停止在 owner 前。scheduler 只写本地 task store failure/retry/dead-letter 审计，不得绕过 research-service 直连 owner。
- 预检失败会让 `scheduler_model_time_wheel_v1` 本轮状态为 `failed` 并阻断 `/readyz`；这表示 scheduler 缺真实研究输入，不表示 owner service 故障。
- 当前仓库已落地独立 `research-service` payload assembler；`research-center-service` 仍只承载模型三低谷图库研究资产，不能被伪装成三/四模型生产 payload assembler。scheduler 已冻结的 payload preflight 逻辑不变，默认 `SCHEDULER_MODEL_TIME_WHEEL_LIVE_DISPATCH=false` 仍不会自动触达 owner endpoint。

只读/手动验收入口：
```text
POST /scheduler/model-time-wheel/run-once
POST /scheduler/model-schedule/catch-up
GET /scheduler/runtime/status
GET /scheduler/materialize/three-models?trading_day=2026-06-12&include_research_intraday=false
POST /scheduler/model-payload/assemble-preflight
```

## 2026-06-17 调度服务定向解锁修复记录

用户确认数据源稳定冻结后，批准将下一步重点放到 `scheduler-service` 并定向解锁最小修复。本轮修复范围只限 scheduler 服务代码、测试和本 README / DATA_ASSETS，不修改 `source-data-service`、Docker、schema、provider、data-inspector 或模型服务。

修复后的调度硬合同：

- `source.auction.collect.0915_0925`、`source.auction.freeze.092505_092530`、`source.open_5m.collect` 的 owner 统一为 `source-data-service`，非 dry-run 只允许调用 `POST /source/fetch/submit`。
- scheduler task definition 不得出现 `provider.*` 或 `raw_*` 读取；source fetch 任务必须在 `reads_from` 中声明 `source-data-service:/source/fetch/submit`。
- `/scheduler/plan/three-models` 的 `plan_version` 与代码常量统一为 `core_model_scheduler_design_v2`。
- hot / memory buy point 当前仍由各自 owner service 的 `/production/buy-point/evaluate` 处理；独立 `execution-timing-service` 接入前，不得把当前闭环任务 owner 写成不存在的服务。
- docs sync 除 token 外，还校验 README 中的 `Task code / Owner service / Owner endpoint` 行必须逐项匹配当前代码任务表。
- `source_fetch_schedule_registry_v1` 覆盖一次性、日调度、分钟级和窗口级 source fetch 计划；`scheduler_source_time_wheel_v1` 常驻执行当前窗口任务，带本地 lease/retry/dead-letter 审计并提交 `source-data-service /source/fetch/submit`。
- `source_fetch_schedule_registry_v1` 必须覆盖 `research_model_payload_assembler_v1` 当前 13 张 required source 表；`source.limit_price_v1`、`source.limit_event_v1` 和 `source.ths_paid_limit_up_probability_v1` 均为 P0 source 调度，不得只靠临时取数。
- scheduler 模型任务计划不得出现 `source.*` wildcard、`provider.*`、`raw_*` 或未进入非临时 source registry 的 `source.*` 读取依赖。

2026-06-17 用户回复“继续”后，按单服务发布计划只重建/重启 `scheduler-service`，未带 `--deps`，未重启 `source-data-service`、`data-inspector-service`、模型服务、research-service 或 Postgres。发布后运行态验收：

- `scheduler-service` 容器从 `91fc0d9eff72` 更新为 `b3611d45f48c`，状态 healthy。
- `source-data-service` 容器仍为 `cc2b01689dc5`，`source-data-worker` 仍为 `8f8ef27b76c9`，`data-inspector-service` 仍为 `f7daebc8cf97`。
- `GET /readyz` 返回 `ready`，`source_time_wheel=idle`，`model_time_wheel=idle`，`warning_codes=[]`。
- `GET /scheduler/validate/source-schedule` 返回 `valid=true`，`schedule_count=16`，`missing_research_payload_tables=[]`。
- `GET /scheduler/materialize/source-schedule?trading_day=2026-06-12&symbols=000063.SZ,000759.SZ&include_one_time=true` 返回 `instance_count=722`。
- `GET /scheduler/validate/three-models` 返回 `valid=true`，`source_wildcard_violations=[]`，`source_read_schedule_violations=[]`。
- `GET /scheduler/validate/docs-sync?project_root=.` 返回 `valid=true`。

据此，`scheduler-service -> source schedule registry -> non-temporary source fetch schedules` 运行态达到当前拍板冻结标准。
- `POST /scheduler/source-fetch/temporary` 是其他服务临时取数的调度入口；临时请求必须显式 `trigger_type=model_adhoc_request`、`data_inspection_gap_repair`、`manual_backfill`、`operator_manual` 或 `model_release_preflight`，不得冒充非临时 `scheduled_periodic`。
- `scheduler_model_payload_preflight_v1` 阻止 model time wheel 在缺真实 payload assembler 时误触发 owner live dispatch；真实 payload 必须满足 `research_model_payload_assembler_v1` 合同，官方 release gate 必须携带 passed `source_preflight`。

本记录为定向解锁修复记录；用户在本轮明确“继续/批准”后，以下对象进入拍板冻结。

## 2026-06-17 调度服务 source 调度闭环冻结记录

冻结前置验收证据：

- `pytest -q services/scheduler-service/tests` 通过，结果为 `39 passed`。
- `GET /readyz` 返回 `ready`，runtime 为 `scheduler_runtime_guard_v2`，`source_time_wheel.status=idle`。
- `GET /scheduler/plan/three-models` 返回 `plan_version=core_model_scheduler_design_v2`，`task_count=28`。
- `GET /scheduler/validate/three-models` 返回 `valid=true`，无 provider 直读。
- `GET /scheduler/validate/source-schedule` 返回 `valid=true`，`schedule_count=16`，`missing_research_payload_tables=[]`。
- `GET /scheduler/materialize/source-schedule?trading_day=2026-06-12&symbols=000063.SZ,000759.SZ&include_one_time=true` 返回 `instance_count=722`。
- `GET /scheduler/validate/docs-sync?project_root=.` 返回 `valid=true`，missing tokens/rows 均为 0。
- `GET /scheduler/validate/live-dispatch-samples` 返回 `valid=true`，`sample_count=10`。
- `POST /scheduler/source-fetch/temporary` dry-run 验证 owner 为 `source-data-service`，目标接口为 `POST /source/fetch/submit`。
- `source-data-service /readyz=ready`，`/source/ops/production-readiness=passed`，`data-inspector-service /readyz=ready`。
- 本轮 scheduler 重建/重启未中断 `source-data-service`；其容器 ID 前缀保持 `cc2b01689dc5`，启动时间保持 `2026-06-17T07:35:47Z`。

冻结对象：

| 服务 -> 模块 -> 功能 | 冻结时间 | 确认来源 | 锁定范围 | 允许的只读验收 | 禁止修改项 | 解锁条件 | 回滚方式 | 验证清单 |
|---|---|---|---|---|---|---|---|---|
| `scheduler-service -> source schedule registry -> non-temporary source fetch schedules` | 2026-06-17 18:06 Asia/Shanghai；2026-06-20 本轮补齐 THS paid probability 调度 | 用户本轮“继续/批准”，并要求非临时调度必须百分百完成 | `source_fetch_schedule_registry_v1` 的一次性、日调度、分钟级、窗口级计划；source table、canonical fields、频率、队列/优先级、owner endpoint、幂等键口径；覆盖 research payload required source tables；包含付费概率 fetch 与 deadline guard | `/scheduler/source-schedule/registry`、`/scheduler/validate/source-schedule`、`/scheduler/materialize/source-schedule` | 未获解锁不得改非临时调度范围、频率、目标接口、trigger_type、priority、idempotency、provider/raw 禁读规则；不得让 scheduler 接触 THS Cookie 或 provider 参数 | 新 P0/P1 source 调度缺口、调度合同变化、生产窗口阻断，或用户明确批准 | 回退 scheduler 镜像和 registry 代码；保留 source fetch queue/raw/source/lineage 审计 | `schedule_count=16`；materialized `instance_count=722`；`missing_research_payload_tables=[]`；source schedule valid |
| `scheduler-service -> source time wheel -> current-window submit and local task lease` | 2026-06-17 18:06 Asia/Shanghai | 同上 | `scheduler_source_time_wheel_v1` 常驻启用、当前窗口提交、过期窗口不追发、本地 task store、lease/retry/dead-letter、`/source/fetch/submit` 转交 | `/scheduler/runtime/status`、`POST /scheduler/source-time-wheel/run-once`、本地 task store 只读检查 | 未获解锁不得改 live submit 默认行为、lateness window、max dispatch、lease/dead-letter 语义、source-data-service submit 目标 | 时间轮阻断非临时 source 调度、重复提交、漏提交、误追发过期窗口，或用户明确批准 | 回退 scheduler 镜像；停用 time wheel 仅做只读观察；不得删除 source queue 审计 | `/readyz` ready；`source_time_wheel.status=idle`；tests `39 passed` |
| `scheduler-service -> source-fetch temporary -> cross-service ad hoc fetch orchestration` | 2026-06-17 18:06 Asia/Shanghai | 同上 | `POST /scheduler/source-fetch/temporary` 的 dry-run 默认、允许 trigger_type、source table/canonical fields 校验、`request_source=scheduler-service`、只转交 `source-data-service /source/fetch/submit` | temporary fetch dry-run、source-data-service fetch submit dry-run/状态查询 | 未获解锁不得把临时取数写入非临时 registry，不得允许 `scheduled_periodic`，不得直接写 provider 参数或 raw 表 | 下游服务临时取数合同变化、source orchestration 合同变化，或用户明确批准 | 回退 scheduler 镜像；下游临时取数请求保持阻断/缺口码，不绕过 source-data-service | dry-run owner=`source-data-service`；endpoint=`POST /source/fetch/submit` |

2026-06-17 用户批准对上述两个 scheduler source 调度边界执行定向小修：

- `scheduler-service -> source-fetch temporary -> table contract hard guard`：临时取数入口只允许 `source.*` 表，必须提供非空 `canonical_fields`，继续拒绝 `trigger_type=scheduled_periodic`，dry-run 也不得预览 `raw.*`、`raw_*`、`provider.*` 或 `decision_*` 目标。
- `scheduler-service -> source time wheel -> dispatch failure readiness guard`：当前窗口 source fetch submit 出现任一非 2xx 响应时，`scheduler_source_time_wheel_v1` 本轮状态必须为 `failed` 并写入 error，使 `/readyz` 进入 `not_ready`，不能把提交失败包装为 ready。

用户随后回复“继续”，确认拍板冻结上述两个小修对象。冻结前置验收证据：

- `pytest -q services/scheduler-service/tests` 通过，结果为 `39 passed`。
- `source-data-service /readyz=ready`，`data-inspector-service /readyz=ready`，`scheduler-service /readyz=ready`。
- `scheduler_source_time_wheel_v1` 当前状态为 `idle`，`startup_guard=ready`，`core_closure=ready`。
- `GET /scheduler/validate/docs-sync?project_root=.` 返回 `valid=true`，missing tokens/rows 均为 0。
- `GET /scheduler/validate/source-schedule` 返回 `valid=true`，`schedule_count=16`，`missing_research_payload_tables=[]`。
- `GET /scheduler/validate/live-dispatch-samples` 返回 `valid=true`，`rows=10`。
- 运行态 dry-run 验证：`decision_hot.bad_table` 被拒绝，缺 `canonical_fields` 被拒绝，合法 `source.minute_bar_v1` 只预览转交 `POST /source/fetch/submit`。
- 本轮只替换 `scheduler-service`，未中断 `source-data-service`；`source-data-service` 容器 ID 前缀保持 `cc2b01689dc5`，启动时间保持 `2026-06-17T07:35:47Z`。

冻结对象：

| 服务 -> 模块 -> 功能 | 冻结时间 | 确认来源 | 锁定范围 | 允许的只读验收 | 禁止修改项 | 解锁条件 | 回滚方式 | 验证清单 |
|---|---|---|---|---|---|---|---|---|
| `scheduler-service -> source-fetch temporary -> table contract hard guard` | 2026-06-17 18:30 Asia/Shanghai | 用户在交付报告后回复“继续” | `POST /scheduler/source-fetch/temporary` 的 `source.*` 表名前缀、非空 `canonical_fields`、拒绝 `scheduled_periodic`、dry-run 只预览 source orchestration、`request_source=scheduler-service:*` | temporary fetch dry-run；`/scheduler/validate/docs-sync`；合法 source 表和非法非 source 表的只读请求验证 | 未获解锁不得放宽到 `raw.*`、`raw_*`、`provider.*`、`decision_*` 或空 `canonical_fields`，不得允许临时请求冒充非临时调度 | 下游临时取数合同变化、source-data-service fetch submit 合同变化，或用户明确批准解锁 | 回退 scheduler 镜像；临时取数保持阻断/缺口码，不绕过 source-data-service | 非 source 表 409；空 `canonical_fields` 409；合法 `source.minute_bar_v1` dry-run owner=`source-data-service` |
| `scheduler-service -> source time wheel -> dispatch failure readiness guard` | 2026-06-17 18:30 Asia/Shanghai | 同上 | `scheduler_source_time_wheel_v1` 当前窗口 submit 失败判定、非 2xx dispatch failure 置 `failed`、error 记录、`/readyz` 阻断语义 | `/scheduler/runtime/status`；`POST /scheduler/source-time-wheel/run-once` dry-run/测试；scheduler 单测 | 未获解锁不得把 `/source/fetch/submit` 非 2xx 包装为 ready，不得静默吞掉本地 task failure 或 dead-letter | source submit 合同变化、生产窗口误阻断/漏阻断，或用户明确批准解锁 | 回退 scheduler 镜像；保留本地 task store 与 source queue 审计 | 单测覆盖 submit 503 -> time wheel failed；当前运行态 `/readyz` ready 且 time wheel idle |

2026-06-17 用户在交付报告后回复“继续”，确认拍板冻结模型任务时间轮对象。冻结前置验收证据：

- `pytest -q services/scheduler-service/tests` 通过，结果为 `39 passed`。
- `GET /readyz` 返回 `ready`，`source_time_wheel.status=idle`，`model_time_wheel.status=idle`，`model_time_wheel.live_dispatch=false`。
- `POST /scheduler/model-time-wheel/run-once` 返回 `version=scheduler_model_time_wheel_v1`、`status=idle`、`live_dispatch=false`。
- `GET /scheduler/validate/docs-sync?project_root=.` 返回 `valid=true`，missing docs/tokens/rows 均为 0。
- `GET /scheduler/validate/three-models` 返回 `valid=true`，`task_count=28`。
- `GET /scheduler/materialize/three-models?trading_day=2026-06-12&include_research_intraday=false` 返回 `instance_count=209`。
- `GET /scheduler/validate/source-schedule` 返回 `valid=true`，`schedule_count=16`，`missing_research_payload_tables=[]`；source 调度物化 `instance_count=722`。
- `source-data-service /readyz=ready`，`data-inspector-service /readyz=ready`，source fetch 队列 queued/leased/dead-letter 均为 0。
- 本轮只替换 `scheduler-service`；`source-data-service` 容器 ID 前缀保持 `cc2b01689dc5`，启动时间保持 `2026-06-17T07:35:47Z`。

冻结对象：

| 服务 -> 模块 -> 功能 | 冻结时间 | 确认来源 | 锁定范围 | 允许的只读验收 | 禁止修改项 | 解锁条件 | 回滚方式 | 验证清单 |
|---|---|---|---|---|---|---|---|---|
| `scheduler-service -> model task time wheel -> non-temporary owner task enqueue/audit/readiness guard` | 2026-06-17 19:26 Asia/Shanghai | 用户在交付报告后回复“继续” | `scheduler_model_time_wheel_v1`、`POST /scheduler/model-time-wheel/run-once`、四模型 owner 任务按 `three_model_materializer_v1` 入队、本地 task store lease/retry/dead-letter/run log、默认 `SCHEDULER_MODEL_TIME_WHEEL_LIVE_DISPATCH=false`、live dispatch 失败 readyz 阻断语义、`scheduler_payload_assembly_required` 缺口码口径 | `/scheduler/runtime/status`、`POST /scheduler/model-time-wheel/run-once`、`/scheduler/materialize/three-models`、`/scheduler/validate/three-models`、`/scheduler/validate/docs-sync`、scheduler 单测 | 未获解锁不得改 model time wheel 默认 live 行为、入队 payload 缺口码、owner allowlist、readyz 阻断语义、task store lease/retry/dead-letter 语义，且不得让 scheduler 用 sample payload、0、空字符串或 GPT 推断补模型输入 | 真实 research payload assembler 接入、owner endpoint 合同变化、模型任务 live dispatch 投产、readyz 误阻断/漏阻断，或用户明确批准解锁 | 回退 scheduler 镜像；保留本地 task store 审计；必要时设置 `SCHEDULER_MODEL_TIME_WHEEL_ENABLED=false` 只读观察；不得触碰 source-data-service | `39 passed`；`/readyz` ready；model time wheel idle；docs-sync valid；three-model plan valid；source-data-service 未中断 |

2026-06-17 用户在交付报告后回复“你认为可以冻结就行”，确认由 Codex 按验收结果判断并拍板冻结模型 payload 投产预检对象。冻结前置验收证据：

- `pytest -q services/scheduler-service/tests` 通过，结果为 `39 passed`。
- `GET /scheduler/model-payload/requirements` 返回 `preflight_version=scheduler_model_payload_preflight_v1`、`assembler_contract=research_model_payload_assembler_v1`，覆盖 24 个模型 owner 任务。
- `POST /scheduler/model-payload/preflight` 对 `scheduler_payload_assembly_required` 缺口 payload 返回 `valid=false`，包含 `payload_assembly_required_gap_present`、`scheduler_payload_status_blocked` 和 `source_preflight_not_passed`。
- `POST /scheduler/model-payload/preflight` 对带 `payload_assembly_contract=research_model_payload_assembler_v1`、`payload_assembly_status=assembled_research_payload`、非空 `payload_assembly_source` 且 passed `source_preflight` 的 official release payload 返回 `valid=true`。
- `GET /scheduler/validate/docs-sync?project_root=.` 返回 `valid=true`，missing docs/tokens/rows 均为 0。
- `GET /readyz` 返回 `ready`；`POST /scheduler/model-time-wheel/run-once` 返回 `status=idle`、`live_dispatch=false`。
- 本轮只替换 `scheduler-service`；`source-data-service` 容器 ID 前缀保持 `cc2b01689dc5`，启动时间保持 `2026-06-17T07:35:47Z`；`data-inspector-service` 容器 ID 前缀保持 `f7daebc8cf97`，启动时间保持 `2026-06-17T08:03:41Z`。

冻结对象：

| 服务 -> 模块 -> 功能 | 冻结时间 | 确认来源 | 锁定范围 | 允许的只读验收 | 禁止修改项 | 解锁条件 | 回滚方式 | 验证清单 |
|---|---|---|---|---|---|---|---|---|
| `scheduler-service -> model live dispatch -> payload production preflight guard` | 2026-06-17 20:55 Asia/Shanghai | 用户授权 Codex 判断可冻结：“你认为可以冻结就行” | `scheduler_model_payload_preflight_v1`、`GET /scheduler/model-payload/requirements`、`POST /scheduler/model-payload/preflight`、`research_model_payload_assembler_v1` 合同、`assembled_research_payload` 状态、official release `source_preflight` passed 门禁、缺口/sample payload 拦截、预检失败不触达 owner endpoint | `/scheduler/model-payload/requirements`、`/scheduler/model-payload/preflight`、`/scheduler/runtime/status`、`POST /scheduler/model-time-wheel/run-once`、`/scheduler/validate/docs-sync`、scheduler 单测 | 未获解锁不得放宽 `scheduler_payload_assembly_required`、`blocked_payload_assembly_required`、`scheduler_live_dispatch_contract_sample`、`sample-*` 拦截；不得取消 `research_model_payload_assembler_v1` / `assembled_research_payload` / `payload_assembly_source` 要求；不得跳过 official release `source_preflight`；不得让 scheduler 推断、补齐或伪造模型输入 | 真实 research payload assembler 接入、official release preflight 合同变化、owner endpoint payload 合同变化、live dispatch 投产、readyz 误阻断/漏阻断，或用户明确批准解锁 | 回退 scheduler 镜像；保持 `SCHEDULER_MODEL_TIME_WHEEL_LIVE_DISPATCH=false`；必要时设置 `SCHEDULER_MODEL_TIME_WHEEL_ENABLED=false` 只读观察；不得触碰 source-data-service | `39 passed`；docs-sync valid；缺口 payload `valid=false`；assembled payload `valid=true`；`/readyz` ready；source-data-service 未中断 |

## Docker 运行

Docker Compose 中 scheduler 端口固定为 `8023`，启动命令固定为：

```text
uvicorn scheduler_service.main:app --host 0.0.0.0 --port 8023
```

当前核心闭环 compose 要求 Postgres、schema-bootstrap、source-data-service、source-data-worker、research-service、data-inspector-service 和 scheduler-service 可用。三大模型服务与模型四 `t-board-relay-service` 是否作为 ready 硬依赖由 `SCHEDULER_REQUIRED_MODEL_SERVICES` 显式声明；当前逐个模型校验阶段默认 `none`，不得因为模型 owner 暂停而启动或拖垮数据底座。Redis、NATS、MinIO 或其他业务服务不应成为当前核心调度 ready 的必要条件。

## 调度与落库边界

- 数据新增或补采必须走 `source-data-service` fetch orchestration，不得由 scheduler 直接并发调用 provider。
- source 任务只写 `source.*` 或 `governance.*`。
- hot candidates 业务事实只属于 `decision_hot.*`。
- candidate memory 业务事实只属于 `decision_memory.*`。
- ambush watchlist 业务事实只属于 `decision_ambush.*`。
- t-board relay 业务事实只属于 `decision_t_relay.*` / `research_t_relay.*`，且由模型四 owner repository 写入。
- scheduler 可写治理调度元数据，但不保存模型业务真相。
- observation、outcome 和 evolution 全部 append-only。
- scheduler 不反写模型分数、release gate、buy point、标签、交易或学习权重。

## 2026-06-17 数据源闭环冻结记录

本轮首次上线重建后，scheduler 以现有镜像启动，未重建本服务镜像。`docker compose -f infra/docker-compose.yml up -d hot-candidates-service candidate-memory-service ambush-watchlist-service t-board-relay-service data-inspector-service scheduler-service` 后，本服务 `/readyz` 返回 `ready`：

```text
background_loop.status=ready
data_inspector.status=ready
startup_guard.run_id=2084, status=ready, p0_gap_count=0, p1_gap_count=0
closure_guard.latest_core_closure.run_id=2085, status=ready, p0_gap_count=0, p1_gap_count=0
source.production_readiness.status=passed, can拍板=true
models.hot_candidates/candidate_memory/ambush_watchlist/t_board_relay -> ready
preflight hot/memory/ambush/t_board_relay day1/day2 -> can_release_official_signal=true
```

跨服务验收：

```text
python scripts/core_services_acceptance.py --require-postgres --real-provider-probe --source-quality-matrix --source-quality-symbol 000063.SZ,000001.SZ,600000.SH,000759.SZ --source-quality-trade-date 2026-06-12 --source-quality-table daily --source-quality-table adjusted --timeout 30 --source-quality-timeout 240
  -> exit 0
  -> status=passed
  -> required_failed=[]
  -> scheduler live dispatch accepted: hot.release_gate.preopen, memory.release_gate.close, ambush.phase3.release_gate.close, t_relay.day1/day2/day3/outcome tasks
```

冻结对象：

| 服务 -> 模块 -> 功能 | 冻结时间 | 确认来源 | 锁定范围 | 允许的只读验收 | 禁止修改项 | 解锁条件 | 回滚方式 | 验证清单 |
|---|---|---|---|---|---|---|---|---|
| `scheduler-service -> current_closure guard -> readyz source/data-inspector/preflight gate` | 2026-06-17 16:08 Asia/Shanghai | 用户本轮确认按任务书执行并授权完成闭环后拍板冻结 | `/readyz` 的 background loop、data-inspector ready、startup_guard、current_closure、source production readiness、模型 owner ready、release preflight 汇总 | `/readyz`、`data-inspector-service /inspection-runs/latest`、`scripts/core_services_acceptance.py` | 未获解锁不得改 readyz 守卫、startup/core closure 依赖、preflight 降级规则、source 队列阻断规则 | readyz blocked、startup/core closure P0/P1 gap、source readiness blocked 或用户明确批准 | 回退 scheduler 镜像和环境变量；保留 data-inspector run 审计 | `/readyz` ready；startup_guard run `2084` ready；core_closure run `2085` ready |
| `scheduler-service -> live dispatch -> four model owner endpoint wrapping` | 2026-06-17 16:08 Asia/Shanghai | 同上 | `hot.*`、`memory.*`、`ambush.*`、`t_relay.*` owner endpoint 包装、`_scheduler_context` 注入和 official publish 标记 | `scripts/core_services_acceptance.py` sample/live dispatch、owner `/readyz` | 未获解锁不得让 scheduler 写模型事实、改 release gate 结果、伪造 owner 成功或直接采 provider | owner endpoint 合同变化、live dispatch failed 或用户明确批准 | 回退 scheduler 镜像；停用 live dispatch 只读观察，不删除 owner facts | core acceptance live dispatch accepted 且 `required_failed=[]` |

## 文档同步

每次修改 scheduler 代码、API、任务计划、调度时间、Docker 健康或启动守卫，都必须覆盖本 README，并通过：

```text
GET /scheduler/validate/docs-sync
```

代码级校验由 `scheduler_service.docs_sync.validate_scheduler_docs_sync` 执行，检查版本号、核心 API、runtime 入口、官方发布任务、owner endpoint 和三模型锁定标签是否写入本 README。
## 2026-06-18 Research Payload Assemble Preflight 冻结记录

2026-06-18 用户确认按任务书继续执行后，本服务执行单服务 `--no-deps` 发布验证，仅重建/重启 `scheduler-service`，未重启 `source-data-service`、`data-inspector-service`、`research-service`、Postgres 或模型 owner 服务。发布后验收结果：

- `scheduler-service` 容器从 `b3611d45f48c` 更新为 `d6e0ee0e72a5`，状态 `healthy`。
- `source-data-service` 容器仍为 `cc2b01689dc5`，启动时间仍为 `2026-06-17T07:35:47Z`。
- `data-inspector-service` 容器仍为 `f7daebc8cf97`，`research-service` 容器仍为 `fca2b9b1a97d`，均为 `healthy`。
- `GET /readyz` 返回 `ready`，`startup_guard.run_id=2093`，`p0_gap_count=0`，`p1_gap_count=0`，`warning_codes=[]`，source/model time wheel 均为 `idle`。
- `GET /source/fetch/queues/summary` 返回所有队列 `queued_count=0`、`leased_count=0`、`dead_letter_count=0`。
- `GET /scheduler/model-payload/requirements` 返回 `preflight_version=scheduler_model_payload_preflight_v1`、`assembler_contract=research_model_payload_assembler_v1`、`task_count=24`。
- `POST /scheduler/model-payload/assemble-preflight` 在 `t_relay.day1.scan.close / 000759.SZ / 2026-06-12 / as_of_time_utc=2026-06-12T07:05:00Z / persist_audit=false` 下返回 `contract_kind=scheduler_research_payload_assemble_preflight_v1`、`payload_assembly_status=blocked_data_gap`、`scheduler_preflight.valid=false`、`dispatch_allowed=false`、`owner_request_body_preview=null`；阻断原因来自 source preflight freshness late，不得绕过。
- `POST /scheduler/model-payload/assemble-preflight` 在同任务不传历史 `as_of_time_utc`、`persist_audit=false` 下返回 `payload_assembly_status=assembled_research_payload`、`scheduler_preflight.valid=true`、`dispatch_allowed=true`，仅返回 owner request body preview，不触达 owner endpoint，不写模型事实。
- `GET /scheduler/validate/docs-sync?project_root=.` 返回 `valid=true`，`missing_docs=[]`，`missing_tokens=[]`，`missing_owner_endpoint_rows=[]`。
- `pytest -q services/scheduler-service/tests` 通过，结果为 `41 passed`；`pytest -q services/research-service/tests` 通过，结果为 `6 passed`；`compileall` 通过。

据此，以下对象达到当前拍板冻结标准：

| 服务 -> 模块 -> 功能 | 冻结时间 | 确认来源 | 锁定范围 | 允许的只读验收 | 禁止修改项 | 解锁条件 | 回滚方式 | 验证清单 |
|---|---|---|---|---|---|---|---|---|
| `scheduler-service -> model payload integration -> research assemble-preflight bridge` | 2026-06-18 00:32 Asia/Shanghai | 用户本轮“确认”，且此前授权 Codex 按验收结果判断冻结 | `POST /scheduler/model-payload/assemble-preflight`、`scheduler_research_payload_assemble_preflight_v1`、`RESEARCH_SERVICE_BASE_URL` 读取、调用 `research-service /research/model-payload/assemble`、默认 `persist_audit=false`、blocked/assembled 两类门禁、owner request body preview 只读生成 | `/scheduler/model-payload/assemble-preflight` no-persist 探针、`/scheduler/model-payload/requirements`、`/scheduler/validate/docs-sync`、`/readyz`、source queue summary、scheduler/research 单测 | 未获解锁不得让该入口触达 owner endpoint，不得默认持久化审计，不得把 `blocked_data_gap`、`source_gap:*`、late/stale/missing preflight 或 sample payload 改写为可派发，不得让 scheduler 推断或补齐模型输入 | research payload assembler 合同变化、owner endpoint body 合同变化、official release preflight 合同变化、需要投产真实 live dispatch，或用户明确批准解锁 | 回退 `infra-scheduler-service:latest` 到上一 scheduler 镜像；保持 `SCHEDULER_MODEL_TIME_WHEEL_LIVE_DISPATCH=false`；必要时临时停用 model time wheel 只读观察；不得触碰 `source-data-service` | 新端点 200；历史 as_of 阻断 `dispatch_allowed=false`；当前可见性 assembled 仅返回 preview；`/readyz` ready；队列无 queued/leased/dead-letter；`41 passed` / `6 passed` |

## 2026-06-18 Scheduler Post-Source-Freeze Review Record

2026-06-18 07:31 Asia/Shanghai, after the source-data zero-row backup guard was approved and frozen, scheduler was reviewed without code changes, Docker changes, image rebuilds, service restarts, schema changes, provider calls, or owner live dispatch. This record refreshes scheduler evidence after the latest source-data-service/source-data-worker recreate; it does not unlock or relax any existing scheduler freeze object.

Current runtime evidence:

```text
scheduler-service docker status: Up 7 hours (healthy)
source-data-service docker status: Up 4 hours (healthy)
source-data-worker docker status: Up 4 hours
data-inspector-service docker status: Up 6 hours (healthy)
research-service docker status: Up 10 hours (healthy)

GET /readyz:
  status=ready
  startup_guard.run_id=2093, status=ready, p0_gap_count=0, p1_gap_count=0
  closure_guard.mode=current_closure, status=ready
  warning_codes=[]
  source_time_wheel.status=idle, live_submit=true
  model_time_wheel.status=idle, live_dispatch=false

GET /scheduler/validate/source-schedule:
  valid=true
  registry_version=source_fetch_schedule_registry_v1
  schedule_count=16
  groups=daily_close,daily_close_paid_probability,daily_preopen,daily_preopen_paid_probability_guard,daily_research_context,minute_auction,minute_intraday,one_time_initial,t_relay_day1_window,t_relay_day2_window
  missing_research_payload_tables=[]
  provider_or_raw_violations=[]

GET /scheduler/validate/three-models:
  valid=true
  task_count=28
  official_publish_tasks=hot.release_gate.preopen,memory.release_gate.close,ambush.phase3.release_gate.close
  provider_read_violations=[]
  raw_read_violations=[]
  source_orchestration_violations=[]

GET /scheduler/validate/docs-sync:
  valid=true
  missing_docs=[]
  missing_tokens=[]
  missing_owner_endpoint_rows=[]

source-data-service:
  /readyz status=ready
  /source/ops/production-readiness?require_postgres=true&require_real_provider_probe=true status=passed
  can拍板=true
  queue summary: queued_count=0, leased_count=0, dead_letter_count=0 across all queues

data-inspector-service:
  /readyz status=ready
```

Freeze review object:

| 服务 -> 模块 -> 功能 | 复核时间 | 确认来源 | 当前结论 | 允许的只读验收 | 禁止修改项 | 解锁条件 | 验证清单 |
|---|---|---|---|---|---|---|---|
| `scheduler-service -> post-source-freeze review -> non-temporary schedule and readiness evidence` | 2026-06-18 07:31 Asia/Shanghai | 用户本轮“批准” | 源服务最新冻结后，scheduler 非临时 source registry、source/model time wheel、current_closure readyz、三/四模型 plan validation 和 docs-sync 均保持 ready/valid；无需改代码即可继续冻结候选 | `/readyz`、`/scheduler/runtime/status`、`/scheduler/validate/source-schedule`、`/scheduler/validate/three-models`、`/scheduler/validate/docs-sync`、`/source/fetch/queues/summary` | 未获解锁不得改非临时调度频率、owner endpoint、source fetch submit 目标、临时取数边界、time wheel lateness/live 行为、payload preflight hard gate、readyz current_closure 守卫或 owner live dispatch 默认值 | 新 P0/P1 source 表进入 research payload required set、source-data-service fetch submit 合同变化、readyz 误阻断/漏阻断、time wheel 漏提交/重复提交、需要投产真实 owner live dispatch，或用户明确批准 | scheduler ready；source schedule valid；three-model plan valid；docs-sync valid；source readiness passed；source queues queued/leased/dead_letter 全 0；data-inspector ready |

## 2026-06-18 Research/Scheduler Runtime Release Freeze

2026-06-18 用户明确批准“发布 research+scheduler”后，本服务与 `research-service` 执行定向发布：

```text
rollback tags:
  infra-scheduler-service:rollback-20260618-research-scheduler-release
  infra-research-service:rollback-20260618-research-scheduler-release

build:
  docker compose -f infra/docker-compose.yml build research-service scheduler-service

replace:
  docker compose -f infra/docker-compose.yml up -d --no-deps research-service scheduler-service
```

发布影响范围：

- `ai-stock-scheduler-service` 从 `d6e0ee0e72a5` 替换为 `146b1c3104b9`，新镜像 digest 为 `sha256:38f62b96992144c04b2292346e30973321d7ac2b4744c428d055991dbd407171`。
- `ai-stock-research-service` 从 `fca2b9b1a97d` 替换为 `c27f4f6c9dbe`，新镜像 digest 为 `sha256:3492ea38cd553bea0524846bf9256ebaaadf850a2dfff8eaec766e2d64152c35`。
- `source-data-service` 容器保持 `125b58ac7f9e`，启动时间保持 `2026-06-17T19:31:38Z`。
- `source-data-worker` 容器保持 `0df61d50252b`，启动时间保持 `2026-06-17T19:31:44Z`。
- `data-inspector-service` 容器保持 `0995dca891f7`，启动时间保持 `2026-06-17T17:01:59Z`。
- Postgres 容器保持 `af846a793868`，启动时间保持 `2026-06-17T07:23:49Z`。

发布后验收：

```text
source-data-service /readyz -> ready
data-inspector-service /readyz -> ready
scheduler-service /readyz -> ready
  startup_guard.run_id=2096
  p0_gap_count=0
  p1_gap_count=0
  closure_guard.status=ready
research-service /readyz -> ready
/source/fetch/queues/summary -> all queues queued_count=0, leased_count=0, dead_letter_count=0
/scheduler/validate/three-models -> valid=true
/scheduler/validate/docs-sync?project_root=. -> valid=true
```

运行态 release gate 探针：

```text
POST /scheduler/model-payload/assemble-preflight hot.release_gate.preopen
  source_tables_seen excludes source.realtime_quote_v1 and source.minute_bar_v1
  upstream_tables_seen=decision_hot.hot_score_fact_v1,decision_hot.hot_evidence_snapshot_v1
  gap_codes=source_gap:decision_hot_hot_evidence_snapshot_missing,source_gap:decision_hot_hot_score_fact_missing
  dispatch_allowed=false

POST /scheduler/model-payload/assemble-preflight memory.release_gate.close
  upstream_tables_seen=decision_memory.memory_pre_signal_case_v1,decision_memory.memory_score_fact_v1
  gap_codes=source_gap:decision_memory_memory_pre_signal_case_missing,source_gap:decision_memory_memory_score_fact_missing
  dispatch_allowed=false

POST /scheduler/model-payload/assemble-preflight ambush.phase3.release_gate.close
  upstream_tables_seen=decision_ambush.effective_turn_pool_v1
  gap_codes=source_gap:decision_ambush_effective_turn_pool_missing
  dispatch_allowed=false
```

冻结对象：

| 服务 -> 模块 -> 功能 | 冻结时间 | 确认来源 | 锁定范围 | 允许的只读验收 | 禁止修改项 | 解锁条件 | 回滚方式 | 验证清单 |
|---|---|---|---|---|---|---|---|---|
| `scheduler-service -> model payload bridge -> release gate upstream runtime contract` | 2026-06-18 13:47 Asia/Shanghai | 用户明确“批准发布 research+scheduler” | `scheduler_research_payload_assemble_preflight_v1` 调用 `research_model_payload_assembler_v1` 后的 release gate upstream contract；hot 不硬等分钟/实时；memory/ambush 不等待自身 signal；blocked payload 不触达 owner | `/scheduler/model-payload/assemble-preflight` no-persist、`/scheduler/validate/three-models`、`/scheduler/validate/docs-sync`、`/readyz`、source queue summary | 未获解锁不得放宽 `blocked_data_gap`、不得恢复自身 signal 依赖、不得把 sample/0/推断补事实、不得绕过 source preflight、不得让该 preflight 入口触达 owner endpoint | release gate upstream 合同变化、research assembler 合同变化、owner endpoint 合同变化、readyz 误阻断/漏阻断、或用户明确批准 | 重新标记 rollback 镜像为 latest 后 `docker compose -f infra/docker-compose.yml up -d --no-deps research-service scheduler-service`；不触碰 source/data-inspector/Postgres | source/data-inspector/scheduler/research ready；startup_guard run 2096 ready；source queues clear；three-models valid；docs-sync valid；三条 runtime release gate 探针符合新上游 |

## 2026-06-18 Execution Bridge Runtime Closure

用户要求“继续闭环”后，本服务与 `research-service` 完成 `research_model_execution_v1` 运行态闭环。执行顺序为：应用 `0027` schema，给旧 research/scheduler 镜像打 rollback 标签，构建新 research/scheduler 镜像，再执行：

```text
docker compose -f infra/docker-compose.yml up -d --no-deps research-service scheduler-service
```

发布影响范围：

```text
ai-stock-scheduler-service -> 7ce78da5adf2, image sha256:7b40e9e6c2f17fc0129d26587dc2f6b0934afd3fc13e092ef304fd33c1dd3eeb
ai-stock-research-service -> a2a5aa571c29, image sha256:62d9d5798d78dea858eaff1f58ff1a0e02eca93c80220a0e70260bd220ab2693

rollback:
infra-scheduler-service:rollback-20260618-execution-bridge-closure
infra-research-service:rollback-20260618-execution-bridge-closure
```

未替换对象保持：

```text
source-data-service 125b58ac7f9e started_at=2026-06-17T19:31:38Z
source-data-worker 0df61d50252b started_at=2026-06-17T19:31:44Z
data-inspector-service 0995dca891f7 started_at=2026-06-17T17:01:59Z
postgres af846a793868 started_at=2026-06-17T07:23:49Z
```

发布后验收：

```text
scheduler /readyz -> ready
startup_guard.run_id=2097, p0_gap_count=0, p1_gap_count=0
model_time_wheel.dispatcher_version=scheduler_research_model_execution_dispatch_v1
source_time_wheel.status=idle
model_time_wheel.status=idle
/scheduler/validate/docs-sync?project_root=. -> valid=true
/scheduler/validate/three-models -> valid=true
/source/fetch/queues/summary -> queued_count=0, leased_count=0, dead_letter_count=0 across all queues
research /readyz -> ready, execution_audit_ready=true
```

冻结对象：

| 服务 -> 模块 -> 功能 | 冻结时间 | 确认来源 | 锁定范围 | 允许的只读验收 | 禁止修改项 | 解锁条件 | 回滚方式 | 验证清单 |
|---|---|---|---|---|---|---|---|---|
| `scheduler-service -> model time wheel -> research execution dispatch` | 2026-06-18 15:09 Asia/Shanghai | 用户“继续闭环” | `scheduler_model_time_wheel_v1`、`scheduler_research_model_execution_dispatch_v1`、`RESEARCH_SERVICE_BASE_URL/research/model-execution/run`、readyz failure guard、本地 task store retry/dead-letter 语义 | `/readyz`、`/scheduler/runtime/status`、`/scheduler/validate/three-models`、`/scheduler/validate/docs-sync`、source queue summary | 未获解锁不得让模型时间轮直连 owner，不得把 `accepted=false` 改写成功，不得取消 retry/dead-letter readyz 阻断，不得让 scheduler 写 decision/research 业务事实 | research execution 合同变化、owner endpoint 合同变化、readyz 误阻断/漏阻断、live dispatch 投产策略变化，或用户明确批准 | 重新标记 rollback 镜像为 latest 后 `docker compose -f infra/docker-compose.yml up -d --no-deps scheduler-service research-service`；不触碰 source-data-service/data-inspector/Postgres | dispatcher 版本正确；docs-sync valid；three-model plan valid；source/data-inspector ready；队列无 leased/dead-letter |

## 2026-06-18 Model Time Wheel Live Dispatch Rollout

用户批准解锁 `scheduler-service -> model time wheel -> research execution live dispatch rollout` 后，本服务执行最小生产化调整：

- `infra/docker-compose.yml` 当时对 `scheduler-service` 显式设置 `SCHEDULER_MODEL_TIME_WHEEL_LIVE_DISPATCH=true`、`RESEARCH_SERVICE_BASE_URL=http://research-service:8029`、`SCHEDULER_REQUIRED_MODEL_SERVICES=t_board_relay` 和 `SCHEDULER_TASK_STORE_PATH=/var/lib/ai_stock_scheduler/task_store.sqlite3`。
- `scheduler_task_store` 命名卷挂载到 `/var/lib/ai_stock_scheduler`，用于持久保存本地非临时 source/model task instance、lease、terminal blocked、retry、dead-letter 和 dispatch audit，避免 scheduler 容器替换时丢失 pending 任务。
- `scheduler_model_time_wheel_v1` 对 `research_model_execution_v1` 返回做三类状态划分：`materialized` 为 success；`blocked_data_gap`、`materialized_with_gaps`、`materialization_skipped` 为 terminal non-success，保留缺口码和 execution audit，不重试、不伪装成功；HTTP 非 2xx、`owner_failed`、`materialization_failed` 和异常仍进入 retry/dead-letter 并阻断 `/readyz`。
- 正式 live dispatch 仍只调用 `research-service /research/model-execution/run`，不直连 owner endpoint，不读取 provider/raw，不写模型事实或 official signal。

本轮发布前必须先备份运行中 `/tmp/ai_stock_scheduler_task_store.sqlite3` 并灌入 `scheduler_task_store` 卷，再定向构建/替换 `scheduler-service`。不得重启、重建或替换 `source-data-service`、`source-data-worker`、`data-inspector-service`、Postgres 或任一模型 owner service。

发布与状态保全：

```text
rollback:
  infra-scheduler-service:rollback-20260618-model-time-wheel-live-dispatch
  image sha256:7b40e9e6c2f17fc0129d26587dc2f6b0934afd3fc13e092ef304fd33c1dd3eeb

task store backup:
  C:\Users\JUNQIA~1\AppData\Local\Temp\ai_stock_scheduler_task_store_20260618-174528\task_store.sqlite3
  seeded bytes=69632
  seeded volume=infra_scheduler_task_store
  seeded counts: pending=12, success=5

build:
  docker compose -f infra/docker-compose.yml build scheduler-service

replace:
  docker compose -f infra/docker-compose.yml up -d --no-deps scheduler-service
```

发布后验收：

```text
scheduler container: ai-stock-scheduler-service 96024e43e68c
scheduler image: infra-scheduler-service@sha256:050ffdcb096875771b0f094fc3ec82486ed022ff249a39a4cbea572f1c7c84e7
source-data-service: ready, container 45f75f040f41 remained running
source-data-worker: container 0df61d50252b remained running
data-inspector-service: ready, container 0995dca891f7 remained running
research-service: ready, container a2a5aa571c29 remained running
postgres: container af846a793868 remained running

scheduler /readyz -> ready
startup_guard.run_id=2098, p0_gap_count=0, p1_gap_count=0
source_time_wheel.live_submit=true, status=idle
model_time_wheel.live_dispatch=true, status=idle
task_store_path=/var/lib/ai_stock_scheduler/task_store.sqlite3
task_store counts: blocked_data_gap=12, success=5, pending=0, retry_ready=0, dead_letter=0
/source/fetch/queues/summary -> queued_count=0, leased_count=0, dead_letter_count=0 across all queues
/scheduler/validate/source-schedule -> valid=true, schedule_count=16
/scheduler/validate/three-models -> valid=true, task_count=28
/scheduler/validate/docs-sync?project_root=. -> valid=true
pytest services/scheduler-service/tests -> 43 passed
```

## 2026-06-20 Scheduler Readonly Closure Review

用户批准仅同步调度服务当前 MD，本次不改代码、schema、Docker、环境变量，不重启、不 rebuild、不触发非 dry-run 临时取数。复核对象继续维持冻结状态；若后续要改 source schedule registry、time wheel live submit、research execution dispatch、task store 语义或 readyz guard，必须重新申请解锁。

复核证据：

```text
scheduler-service /readyz:
  status=ready
  runtime_version=scheduler_runtime_guard_v2
  background_loop=ready
  startup_guard.run_id=2126
  startup_guard.status=ready
  startup_guard.p0_gap_count=0
  startup_guard.p1_gap_count=0
  closure_guard.status=ready
  source_time_wheel.status=idle
  source_time_wheel.live_submit=true
  model_time_wheel.status=idle
  model_time_wheel.live_dispatch=true
  model_time_wheel.status_counts.blocked_data_gap=84

/scheduler/validate/source-schedule:
  valid=true
  schedule_count=16
  registry_version=source_fetch_schedule_registry_v1
  missing_research_payload_tables=[]
  provider_or_raw_violations=[]
  missing_endpoint_chain=[]
  invalid_trigger_priority_pairs=[]
  groups=daily_close,daily_close_paid_probability,daily_preopen,daily_preopen_paid_probability_guard,daily_research_context,minute_auction,minute_intraday,one_time_initial,t_relay_day1_window,t_relay_day2_window

/scheduler/source-schedule/registry:
  registry_count=16
  allowed endpoint paths:
    /source/fetch/submit
    /source/ths/paid-probability/fetch-current-batch
    /source/ths/paid-probability/deadline-check

/scheduler/materialize/source-schedule?trading_day=2026-06-12&symbols=000063.SZ,000759.SZ&include_one_time=true:
  materialized_instance_count=722
  scheduled_periodic_instance_count=670

/scheduler/source-fetch/temporary dry-run:
  contract_kind=scheduler_temporary_source_fetch_preview_v1
  owner_endpoint=POST /source/fetch/submit
  request_source=scheduler-service:hot-candidates-service
  trigger_type=model_adhoc_request
  idempotency_key=temporary:hot-candidates-service:source.minute_bar_v1:2026-06-12
  hard_rule=Temporary fetch requests are explicit ad hoc source orchestration, not recurring schedules.
  scheduled_periodic temporary request rejected with 409

/scheduler/validate/three-models -> valid=true
/scheduler/validate/docs-sync?project_root=. -> valid=true
/scheduler/validate/live-dispatch-samples -> valid=true
source-data-service production-readiness -> status=passed
data-inspector-service /readyz -> ready
/source/fetch/queues/summary -> queued_total=0, leased_total=0, dead_letter_total=0
PYTHONPATH=services/scheduler-service/src python -m pytest -q services/scheduler-service/tests -> 47 passed
```

结论：非临时调度注册表已覆盖当前 research payload 所需 source 表，付费概率抓取与截止守卫均通过 source-data-service 受控端点执行，临时取数不会被登记为 recurring schedule，scheduler 未直接访问 provider 或 raw 表。调度服务当前可维持冻结；只读验收允许继续使用 `/readyz`、`/scheduler/runtime/status`、`/scheduler/validate/source-schedule`、`/scheduler/validate/three-models`、`/scheduler/validate/docs-sync`、`/scheduler/validate/live-dispatch-samples`、source queue summary 和 dry-run temporary preview。

用户在交付报告后回复“批准”，确认以下对象正式拍板冻结。

2026-06-24 验收补充：本轮通过 `POST /scheduler/model-schedule/catch-up` 对 `t_relay.observation.monitor.snapshot_5m` 执行 09:35 槽位补偿；dry-run 精确选中 1 个实例，非 dry-run 经 `research-service /research/model-execution/run` materialized，未直连 owner/provider/raw，未重启 `source-data-service`。运行态验证显示 scheduler `/scheduler/runtime/status` ready，research `/readyz` ready，t-board owner `/readyz` ready，frontend `/readyz` ready；owner 观察台 4 行更新时间推进到 `2026-06-24T09:50:48.617447+00:00`；scheduler tests 当前为 `64 passed`。

冻结对象：

| 服务 -> 模块 -> 功能 | 冻结时间 | 确认来源 | 锁定范围 | 允许的只读验收 | 禁止修改项 | 解锁条件 | 回滚方式 | 验证清单 |
|---|---|---|---|---|---|---|---|---|
| `scheduler-service -> model time wheel -> production live dispatch and terminal blocked audit` | 2026-06-18 17:53 Asia/Shanghai | 用户在交付报告后明确“批准”正式冻结 | Compose 生产候选 `SCHEDULER_MODEL_TIME_WHEEL_LIVE_DISPATCH=true`、`scheduler_task_store` 命名卷、`scheduler_research_model_execution_dispatch_v1`、terminal non-success 状态分类、task store pending drain | `/readyz`、`/scheduler/runtime/status`、`/scheduler/validate/source-schedule`、`/scheduler/validate/three-models`、`/scheduler/validate/docs-sync`、source queue summary、task store 只读统计 | 未获解锁不得关闭 production live dispatch，不得让 scheduler 直连 owner/provider/raw，不得把 terminal blocked 改写为 success，不得取消 retry/dead-letter readyz 阻断，不得删除或重置 `scheduler_task_store` 卷 | research execution 合同变化、owner endpoint 合同变化、terminal non-success 分类变化、readyz 误阻断/漏阻断、task store 持久化路径变化，或用户明确批准 | 重新标记 `infra-scheduler-service:rollback-20260618-model-time-wheel-live-dispatch` 为 latest 后 `docker compose -f infra/docker-compose.yml up -d --no-deps scheduler-service`；如需恢复旧 task store，可用备份 sqlite 灌入卷；不触碰 source-data-service/data-inspector/Postgres/model owner | scheduler ready；startup_guard 2098 ready；model live_dispatch true；pending/retry/dead_letter 为 0；source/data-inspector/research ready；source queues clear；source schedule/three-model/docs-sync valid；scheduler tests 43 passed |
| `scheduler-service -> model time wheel -> model4 rolling watch and post-entry monitor schedule` | 2026-06-24 Asia/Shanghai | 用户要求 Codex 决定是否拍板；Codex 判定可窄冻结已实测调度边界 | 模型四 Day2 `09:30-10:30` 每 5 分钟滚动观察和触发；触发后 `09:35-11:30`、`13:00-15:00` 每 5 分钟 post-entry monitor；观察台当前输出 `09:30-11:30`、`13:00-15:00` 每 5 分钟 snapshot；Day3 `09:25-11:30` 每 5 分钟上午去留观察、`13:00-15:00` 每 5 分钟下午去留观察，`14:40-14:55` 为尾盘退出判断重点；当时 Compose/default policy 仅要求 `t_board_relay`；全部为 non-official research task，scheduler 只调用 research execution bridge | `/readyz`、`/scheduler/runtime/status`、`/scheduler/validate/three-models`、source queue summary、task store 只读统计、frontend/owner 只读观察结果 | 未获解锁不得改成固定 10:30 单次监测；不得跳过触发后封板维护；不得让 scheduler 直连 owner/provider/raw；不得把模型四任务改为 official signal、交易、买点或前端写入；不得重启 source-data-service 回滚调度事实 | 模型四时间窗口变化、research execution 合同变化、owner endpoint 合同变化、source queue 边界变化、Day3 自然窗口验收失败、或用户明确批准解锁 | 回退后续 scheduler 时间轮/策略文档变更；如曾发版则仅 `--no-deps` 替换 scheduler-service；不触碰 source-data-service/source-data-worker/data-inspector/Postgres/model owner | `/scheduler/validate/three-models valid=true task_count=28`；source queue `queued/leased/dead_letter=0`；scheduler ready；scheduler tests `61 passed`；600172.SH post-entry 开板状态已通过链路更新到 owner/前端只读观察 |
| `scheduler-service -> model availability policy -> hot plus model4 required dispatch` | 2026-06-25 Asia/Shanghai | 用户批准按任务书执行并解锁 scheduler-service 热点模型启用 | Compose 默认 `SCHEDULER_REQUIRED_MODEL_SERVICES=hot_candidates,t_board_relay`；热点 owner 与模型四 owner 进入 required readyz、model time wheel 入队和 research execution live dispatch；candidate_memory/ambush 继续 `disabled_by_policy`；scheduler 仍只调用 `research-service /research/model-execution/run`，不直连 owner/provider/raw，不写 `decision_hot.*` | `/readyz`、`/scheduler/runtime/status`、`/scheduler/validate/three-models`、source queue summary、task store 只读统计、`/research/model-list/hot`、`/api/model-list/hot` | 未获解锁不得让 scheduler 读取 Cookie、调用 THS/provider、绕过 source-data-service、绕过 research-service、把 owner 2xx 解释成 official signal、把 blocked/gap 改写为 success、或补 0/mock/推断模型事实 | 热点 owner readyz 失败、research execution 合同变化、source paid probability 合同变化、readyz 误阻断/漏阻断、热点 live dispatch 失败、或用户明确批准解锁 | 回退 `infra/docker-compose.yml` 默认值到 `t_board_relay` 后仅 `--no-deps` 替换 scheduler-service；不触碰 source-data-service/source-data-worker/data-inspector/Postgres/model owner | scheduler tests `64 passed`；`2026-06-24` THS paid probability batch `ready 50/50`；发布后需验证 runtime policy required=`hot_candidates,t_board_relay` |

## 2026-06-26 Scheduler Task Store Recovery Contract

用户本轮批准解锁后，`scheduler-service -> task store/time wheel -> expired running lease recovery` 进入当前合同。该变更只作用于 scheduler 本地任务账本和 readyz 暴露，不修改 `source-data-service`、provider、schema、Docker、模型 owner 或 research 事实。

- `ai_stock_scheduler_task_store.sqlite3::task_instance_v1` 中 `status=running` 且 `task_lease_v1.lease_until <= now` 的任务视为 expired running lease；source/model time wheel 每轮执行前必须把这类任务恢复为 `retry_ready`，删除旧 lease，并在 `task_run_log_v1` 写入 `lease_recovered` 审计事件。
- 有效 lease 未过期时不得恢复，不得重复提交同一任务；恢复后的 source task 仍只能经 `/source/fetch/submit` 或 source-data-service 受控 THS 端点提交，恢复后的 model task 仍只能经 `research-service /research/model-execution/run`。
- `GET /readyz` 与 `GET /scheduler/runtime/status` 必须暴露 `checks.task_store.source` 和 `checks.task_store.model`，包含 `status_counts`、`stale_running_count`、`stale_running_sample` 和 `blocking_statuses`。
- `retry_ready`、`dead_letter` 或 `stale_running` 未清空时，scheduler `/readyz` 必须返回 `not_ready`；data-inspector 继续只读 scheduler `/readyz`，通过该状态继承本地调度账本风险，不需要直接读取 scheduler SQLite。
- `blocked_data_gap`、`materialized_with_gaps`、`materialization_skipped` 仍是已审计终态，不进入 retry/dead-letter，也不得被改写为 success。
- 该恢复合同不代表 source facts 已产出。source 是否可用于模型仍以 source-data-service Postgres queue、raw ingest、quality gate、source build、lineage 和 `/source/release/preflight` 为准。

旧合同 dead-letter 维护入口：

- `GET /scheduler/task-store/daily-summary?trading_day=YYYY-MM-DD&owner_service=source-data-service`
- `POST /scheduler/task-store/archive-obsolete-source-dead-letters` 只用于归档已被当前代码合同明确替代的 source schedule dead-letter，默认 `dry_run=true`。
- 当前默认只匹配 `source.minute.auction_snapshot`、`source.auction_snapshot_v1`、旧字段 `price/volume/amount/captured_at/provider_definition`；归档后 task instance 状态为 `obsolete_contract_replaced`，不再阻断 readyz。
- 该入口不得删除 `task_dead_letter_v1`，必须在 `task_run_log_v1` 写入 `dead_letter_archived`，并返回匹配任务、旧字段、新字段和状态计数。
- 归档只说明旧调度请求合同已废弃，不代表 source facts 已补齐；补齐仍必须走 `/scheduler/source-schedule/catch-up` -> `/source/fetch/submit` -> source-data-worker -> raw/source/lineage。

本轮测试覆盖：

```text
services/scheduler-service/tests/test_phase6_task_store.py
  - expired running lease recovers to retry_ready while active lease remains running

services/scheduler-service/tests/test_runtime_guard.py
  - source time wheel recovers expired running before dispatch
  - readyz blocks source task store dead_letter

services/scheduler-service/tests/test_source_schedule_time_wheel.py
  - source schedule catch-up and controlled source-data-service dispatch contracts remain intact
```

本轮发布后验证（2026-06-26 22:05 Asia/Shanghai）：

```text
scheduler-service container:
  id=15bcce53dba6
  image=sha256:3ce958d3de6a875829398ebe6f2c7ec91958111d72c9f5ceb8b29dfb3d6a3df3
  started_at=2026-06-26T13:44:46Z
  runtime_version=scheduler_runtime_guard_v2
  task_store_path=/var/lib/ai_stock_scheduler/task_store.sqlite3
  recover_expired_running loaded=true

source-data-service remained running:
  id=4bda0447ea0a
  image=sha256:bc8dc350400969f91fcaa3e86c2a4ee8d3d970cd37ac8766a27b8a8addbf7be9
  started_at=2026-06-26T11:33:37Z

scheduler /readyz:
  status=ready
  startup_guard.run_id=2173
  startup_guard.p0_gap_count=0
  startup_guard.p1_gap_count=0
  closure_guard.status=ready
  source_time_wheel.status=idle
  source_time_wheel.details.recovered_expired_running_count=0
  source_time_wheel.task_store_health.blocking_statuses=[]
  source task store status_counts: success=5250, obsolete_contract_replaced=148
  source task store stale_running_count=0
  model_time_wheel.status=idle
  model_time_wheel.live_dispatch=true
  model_time_wheel.details.recovered_expired_running_count=0
  model_time_wheel.task_store_health.blocking_statuses=[]
  model task store status_counts: success=135, blocked_data_gap=561
  model task store stale_running_count=0

data-inspector core_closure:
  run_id=2174
  status=ready
  p0_gap_count=0
  p1_gap_count=0
  observed_domain_count=15
  guardrails.read_only=true
  guardrails.direct_provider_calls_allowed=false
  guardrails.fetch_repairs_must_use_source_data_service_orchestration=true

source-data-service /source/fetch/queues/summary:
  queued_count=0 across all queues
  leased_count=0 across all queues
  dead_letter_count=0 across all queues

scheduler contract validation:
  /scheduler/validate/source-schedule -> valid=true, schedule_count=23, provider_or_raw_violations=[]
  /scheduler/validate/three-models -> valid=true, task_count=28, provider_read_violations=[], raw_read_violations=[]
  /scheduler/source-schedule/catch-up dry-run for source.minute.realtime_quote 2026-06-12 09:30 -> selected_count=1
    owner path remains /source/fetch/submit
    request_source=scheduler-service
    idempotency_key=scheduler:source.minute.realtime_quote:2026-06-12:093000

tests:
  PYTHONPATH=services/scheduler-service/src python -m pytest -q services/scheduler-service/tests -> 72 passed
  PYTHONPATH=services/data-inspector-service/src python -m pytest -q services/data-inspector-service/tests -> 10 passed
```

用户在交付报告后回复“拍板”，确认以下对象正式冻结。

冻结对象：

| 服务 -> 模块 -> 功能 | 冻结时间 | 确认来源 | 锁定范围 | 允许的只读验收 | 禁止修改项 | 解锁条件 | 回滚方式 | 验证清单 |
|---|---|---|---|---|---|---|---|---|
| `scheduler-service -> task store/time wheel -> expired running lease recovery and catch-up safety` | 2026-06-26 22:43 Asia/Shanghai | 用户明确回复“拍板” | `recover_expired_running`、`task_lease_v1` 过期 lease 恢复、`task_run_log_v1.lease_recovered` 审计、source/model time wheel 周期前恢复、`checks.task_store.source/model` readyz 暴露、`retry_ready/dead_letter/stale_running` 阻断、`/scheduler/source-schedule/catch-up` 正式追补入口 | `/readyz`、`/scheduler/runtime/status`、`/scheduler/validate/source-schedule`、`/scheduler/validate/three-models`、`/source/fetch/queues/summary`、catch-up dry-run、task store 只读统计、data-inspector `core_closure` run 只读查询 | 未获解锁不得改 task store lease/retry/dead-letter 语义，不得删除或重置 `scheduler_task_store` 卷，不得把 `blocked_data_gap` 改写为 success，不得取消 readyz 对 `retry_ready/dead_letter/stale_running` 的阻断，不得让 scheduler 直接调 provider/raw/owner，不得把 temporary fetch 当作非临时补数闭环 | source-data-service fetch submit 合同变化、research execution 合同变化、task store 持久化路径变化、readyz 误阻断/漏阻断、恢复后重复提交或漏提交、需要真实历史补跑 dead-letter，或用户明确批准解锁 | 回退 scheduler 镜像到上一稳定版本并 `docker compose -f infra/docker-compose.yml up -d --no-deps scheduler-service`；保留 `scheduler_task_store` 卷审计，必要时从备份 sqlite 恢复；不触碰 `source-data-service`、Postgres、data-inspector 或模型 owner | scheduler `/readyz=ready`；startup_guard run `2173` P0/P1=0；core_closure run `2174` ready；source/model task store `blocking_statuses=[]`、`stale_running_count=0`；source queues queued/leased/dead_letter 全 0；source schedule valid；three-model plan valid；scheduler tests `72 passed` |

### 2026-07-23 Source Catch-Up Lifecycle Guard

`/scheduler/source-schedule/catch-up` now enforces the per-instance `orchestration_context.lifecycle_expires_at*` value before both dry-run preview and real enqueue. Expired instances are returned only in `excluded` with `reason=lifecycle_expired`; they are not selected, not enqueued, and `force_resubmit` does not revive them. Recoverable data after this point must be submitted as a new formal repair/backfill/fetch request rather than pretending the original time-window task is still alive.

`/scheduler/task-store/daily-summary` now reports due-but-never-submitted or pending tasks as `execution_status=expired_closed` when their lifecycle is past. The response includes row-level `lifecycle_expires_at`, `lifecycle_expired`, table-level `expired_closed_task_count`, and summary `expired_closed_task_count`. These rows remain unfinished audit facts, but they are no longer active waiting/dispatch work.
