# scheduler-service

`scheduler-service` 是当前最小生产闭环的编排服务，只负责数据源、三大模型 owner service 和调度健康之间的任务定义、交易日实例化、启动守卫、dry-run 验证和 live dispatch。它不生产 source 事实，不计算模型分数，不写官方信号、买点、标签、演化样本或学习权重。

当前必须调通的服务范围：

- `source-data-service` 与 `source-data-worker`
- `hot-candidates-service`
- `candidate-memory-service`
- `ambush-watchlist-service`
- `scheduler-service`

其他业务服务不是当前闭环前置条件，不能作为 scheduler ready 或三模型调度成功的必要条件。`scheduler-service` 可以读取 `data-inspector-service /readyz` 和触发 `POST /inspection-runs` 作为启动守卫，但不得绕过 source-data-service 直接并发调用 BaoStock、AKShare、Tushare、EastMoney、CNINFO 等 provider。

## 当前版本

- Scheduler runtime/readyz：`scheduler_runtime_guard_v1`
- Scheduler service lock：`scheduler_three_model_service_v1.0_rc_dispatch_candidate`
- Three-model plan：`three_model_scheduler_design_v1`
- Live dispatch：`three_model_live_dispatch_v1`
- Live dispatch sample guard：`three_model_live_dispatch_sample_v1`
- Trading-day materializer：`three_model_materializer_v1`
- Documentation sync guard：`scheduler_docs_sync_v1`

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
- `GET /scheduler/live-dispatch/sample/{task_code}`
- `GET /scheduler/validate/live-dispatch-samples`
- `GET /scheduler/validate/docs-sync?project_root=.`
- `POST /scheduler/trigger`
- `GET /scheduler/validate/hot-workflow`

`POST /scheduler/trigger` 默认 `dry_run=true`。非 dry-run 必须显式传入 `owner_endpoints`，scheduler 只以 owner service 的真实 2xx 响应作为 `accepted=true`，不伪造成功。

非 dry-run 请求体的 `payload` 必须是 owner service 的业务 payload，不得额外包一层模型端字段。scheduler 会按 owner 适配：

- `hot-candidates-service`：把传入 payload 放入模型端 `{ "payload": ... }`，所以调用方传入的 payload 应直接包含 `row`、`run_id`、`as_of_time_utc` 等业务字段。
- `candidate-memory-service`：把传入 payload 放入模型端 `{ "row": ... }`，所以调用方传入的 payload 应是记忆对象/候选行字段本体。
- `ambush-watchlist-service`：直接透传阶段 payload，本体必须满足目标阶段 schema，例如 Phase 3 release task 需要 `instrument`、`valley_watch`、`effective_turn_anchor`、`bars`、`as_of_trading_day` 等字段。

调度连通不等于官方信号通过。owner service 返回 2xx 只表示接口合同和编排链路调通；如果模型根据真实缺口返回 `blocked`、`research_only`、`source_gap_codes` 或 `contract_gaps`，scheduler 必须保留该结果，不得改写为发布成功。

`GET /scheduler/live-dispatch/sample/{task_code}` 返回 `scheduler_live_dispatch_sample_v1`，包含 scheduler 触发层 payload 和 owner request body 预览，用于验证 live dispatch 包装合同。当前内置样例只覆盖三条官方 release gate：

- `hot.release_gate.preopen`
- `memory.release_gate.close`
- `ambush.phase3.release_gate.close`

`GET /scheduler/validate/live-dispatch-samples` 会校验上述三条样例都能生成 owner-service 合同体。样例 payload 只用于调度联通和请求体合同验证，不是市场事实、provider 响应或 source 证据；不得写入模型证据表，不得替代 `source.*`、lineage、available_at 或 release preflight。

## Readyz 与启动守卫

`GET /readyz` 必须同时满足：

- 后台 heartbeat 循环存活且心跳未过期。
- `data-inspector-service /readyz` 返回 ready 或 ok。
- 本次启动已触发并完成 `startup_guard` 巡检。

启动后 runtime 会先检查 `data-inspector-service /readyz`，再调用 `POST /inspection-runs`：

```json
{
  "scope": "startup_guard",
  "as_of_time": "<utc-iso-time>",
  "lookback_days": 20,
  "max_subjects": 500,
  "persist": true
}
```

若 data-inspector 暂时不可用，runtime 会在后台循环中按 `DATA_INSPECTION_STARTUP_GUARD_RETRY_ATTEMPTS` 继续重试；启动巡检未完成或请求失败时 `/readyz` 返回 503。`GET /scheduler/runtime/status` 返回同一套运行快照，用于排查后台循环、data-inspector 探针和启动巡检 run_id、P0/P1 缺口计数。

关键环境变量：

- `DATA_INSPECTOR_SERVICE_BASE_URL`：默认 `http://data-inspector-service:8025`。
- `SCHEDULER_RUNTIME_POLL_SECONDS`：后台循环间隔，默认 30 秒。
- `SCHEDULER_RUNTIME_REQUEST_TIMEOUT_SECONDS`：ready 快速探针超时，默认 5 秒。
- `DATA_INSPECTION_STARTUP_GUARD_TIMEOUT_SECONDS`：启动巡检请求超时，默认 60 秒。
- `DATA_INSPECTION_STARTUP_GUARD_SCOPE`：默认 `startup_guard`。
- `DATA_INSPECTION_LOOKBACK_DAYS`：默认 20。
- `DATA_INSPECTION_MAX_SUBJECTS`：默认 500。
- `DATA_INSPECTION_STARTUP_GUARD_RETRY_ATTEMPTS`：默认 12。

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

唯一允许发布官方信号的任务是：

```text
hot.release_gate.preopen
memory.release_gate.close
ambush.phase3.release_gate.close
```

source、score、buy point、observation、outcome、evolution、pattern library、valley turn 和 research intraday 任务都不得发布 official signal。

## Live Dispatch 合同

Live dispatch 版本是 `three_model_live_dispatch_v1`。scheduler 根据 task owner 调用对应服务，不直接读取 raw 表，不直接采集 provider，不写 `decision_hot.*`、`decision_memory.*` 或 `decision_ambush.*`。

| Task code | Owner service | Owner endpoint |
|---|---|---|
| `hot.score.auction_confirmed` | `hot-candidates-service` | `POST /production/scores/compute` |
| `hot.release_gate.preopen` | `hot-candidates-service` | `POST /production/release-gate/evaluate` |
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

请求体适配规则：

- `hot-candidates-service` 使用顶层 `payload`，示例：`{ "payload": { ... }, "run_id": "...", "as_of_time_utc": "..." }`。
- `candidate-memory-service` 使用顶层 `row`，示例：`{ "row": { ... }, "run_id": "...", "as_of_time_utc": "..." }`。
- `ambush-watchlist-service` 接收阶段 payload 本体，scheduler 只注入 `_scheduler_context`。

`_scheduler_context` 只用于审计，包含 `task_code`、`task_kind`、`owner_service`、`append_only`、`is_official_publish`、`reads_from` 和 `writes_to`。它不授予 scheduler 修改模型事实、分数、状态、标签、发布闸门或学习权重的权限。

## 交易日实例化

`GET /scheduler/materialize/three-models` 调用 `materialize_three_model_day`，按交易日生成确定性的任务实例：

- 每个实例有稳定 `biz_key`。
- 每个实例有稳定 `idempotency_seed`。
- `include_research_intraday=true` 只增加 non-official 研究任务。
- 高频窗口内部频率由 owner service 控制，scheduler 只启动窗口级任务。

## Docker 运行

Docker Compose 中 scheduler 端口固定为 `8023`，启动命令固定为：

```text
uvicorn scheduler_service.main:app --host 0.0.0.0 --port 8023
```

当前最小闭环 compose 只要求 Postgres、schema-bootstrap、source-data-service、source-data-worker、三大模型服务和 scheduler-service 可用。Redis、NATS、MinIO 或其他业务服务不应成为当前三模型调度 ready 的必要条件。

## 调度与落库边界

- 数据新增或补采必须走 `source-data-service` fetch orchestration，不得由 scheduler 直接并发调用 provider。
- source 任务只写 `source.*` 或 `governance.*`。
- hot candidates 业务事实只属于 `decision_hot.*`。
- candidate memory 业务事实只属于 `decision_memory.*`。
- ambush watchlist 业务事实只属于 `decision_ambush.*`。
- scheduler 可写治理调度元数据，但不保存模型业务真相。
- observation、outcome 和 evolution 全部 append-only。
- scheduler 不反写模型分数、release gate、buy point、标签、交易或学习权重。

## 文档同步

每次修改 scheduler 代码、API、任务计划、调度时间、Docker 健康或启动守卫，都必须覆盖本 README，并通过：

```text
GET /scheduler/validate/docs-sync
```

代码级校验由 `scheduler_service.docs_sync.validate_scheduler_docs_sync` 执行，检查版本号、核心 API、runtime 入口、官方发布任务、owner endpoint 和三模型锁定标签是否写入本 README。
