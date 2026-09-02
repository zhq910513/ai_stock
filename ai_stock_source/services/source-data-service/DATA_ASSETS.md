# source-data-service DATA_ASSETS

本文件是 `source-data-service` 的数据资产账本，不替代本目录 `README.md`。全局硬约束以根目录 `AGENTS.md` 为准。

## 服务定位

`source-data-service` 是数据事实底座，负责 provider API registry、fetch orchestration、raw ingest、quality gate、source build、source lineage、release preflight、production readiness 和验收证据。模型、调度、前端、Jarvis 和研究服务不得绕过本服务直接并发调用 provider。

`source-data-worker` 是同一服务根目录下的 Compose worker 角色，不单独拥有代码服务目录。它的数据资产、接口边界、队列、raw/source/lineage 写入和冻结记录均归入本 `DATA_ASSETS.md`；不得为 `source-data-worker` 另造脱离本服务契约的独立事实源。

## 读取数据

| 类型 | 资产 | 用途 | 读写边界 |
|---|---|---|---|
| Provider | BaoStock、Tencent、Sohu、EastMoney、THS、Baidu、Jin10、Tushare 候选 | 真实 probe、raw fetch、备源修复 | 只能由本服务 adapter/worker 调用；Tushare 需 token；THS 默认只允许公开无登录接口，唯一例外是 `ths.paid_limit_up_probability` 通过受控数据库/运行时 Cookie 访问。 |
| 配置 | `infra/provider-configs/market-data-sources.toml` | provider 准入和角色说明 | 禁止写明文 token。 |
| 合同 | `provider_registry.py`、`operational_governance.py` | API spec、source requirement、freshness SLA、storage policy、model requirement | 合同变更必须同步 README 和本账本。 |

## 写入数据

| 分层 | 表 | 作用 | 首次上线优先级 |
|---|---|---|---|
| raw | `raw_baostock.*`、`raw_tencent.*`、`raw_sohu.*`、`raw_eastmoney.*`、`raw_ths.*`、`raw_baidu.*`、`raw_jin10.*`、`raw_tushare.*` | 一接口一原表，保存 request/response hash、raw payload 和 provider 字段 | P0/P1/P2 按 source requirement 决定 |
| source P0 | `source.trade_calendar_v1` | 交易日时间线、pretrade、T+N 标签、scheduler materialize | P0 最高 |
| source P0 | `source.stock_master_v1`、`source.stock_universe_daily_v1`、`source.trade_status_v1` | 股票身份、每日可交易 universe、停牌/ST/退市风险 | P0 |
| source P0 | `source.daily_bar_v1`、`source.adjusted_daily_bar_v1`、`source.adjustment_factor_v1` | 未复权/前复权行情、图形/收益/涨跌停基座 | P0 |
| source P0 | `source.limit_price_v1`、`source.limit_event_v1` | 涨跌停价、涨停/T 字板/回封事件 | P0 |
| source P0 | `source.ths_paid_limit_up_probability_v1` | 同花顺付费次日概率，热点候选教师先验 | P0；无备源，缺失/失效 Cookie 阻断，下一交易日 09:00 后仍缺失才放弃候选批次 |
| source P0 | `source.realtime_quote_v1`、`source.minute_bar_v1`、`source.trade_tick_v1` | 模型四 Day1 候选流通市值、Day2 接力窗口、热点开盘窗口和盘中观察 | P0 窗口级 |
| source P1 | `source.stock_moneyflow_daily_v1`、`source.index_daily_bar_v1` | 资金流、市场环境、相对强弱 | P1 degraded |
| source P2 | `source.event_news_v1`、`source.stock_board_membership_v1`、`source.board_daily_bar_v1` | 事件、题材和研究上下文 | P2/research-only |
| governance | `governance.raw_fetch_*`、`governance.source_build_*`、`governance.source_lineage_v1`、`governance.source_gap_v1`、`governance.source_repair_task_v1` | 队列、build、lineage、缺口、修复 | P0 |
| governance | `governance.source_freshness_*`、`governance.model_source_*`、`governance.model_release_preflight_v1`、`governance.source_data_acceptance_*` | freshness、coverage、release preflight、验收证据 | P0 |
| governance | `governance.ths_paid_probability_cookie_v1`、`governance.ths_paid_probability_batch_status_v1` | 付费概率 Cookie 留存状态和候选批次等待/放弃状态 | P0；Cookie 明文仅存在运行库，不进入 raw params、日志、仓库或前端响应 |

`raw_ths.paid_limit_up_probability_v1` is a typed raw table. Source build must read its safe physical columns and `raw_provider_row` as raw evidence for quality validation, including `symbol`, `trade_date`, `paid_limit_up_probability`, `status_code`, `status_msg`, `credential_version` and `available_at`; the active Cookie values remain only in `governance.ths_paid_probability_cookie_v1` and must not appear in raw params, raw payload, logs, docs or frontend output.

## 接口入口

| 接口 | 调用方 | 作用 |
|---|---|---|
| `GET /source/apis`、`GET /source/contracts`、`GET /source/requirements` | data-inspector、scheduler、人工验收 | 查询 provider/source 字段合同 |
| `POST /source/fetch/plan`、`POST /source/fetch/submit` | scheduler、data-inspector、人工补采 | 生产 fetch orchestration |
| `POST /source/fetch/worker/pull`、`POST /source/fetch/jobs/{id}/complete` | source-data-worker | 消费和回写任务状态 |
| `POST /source/raw/ingest-result` | worker/provider runtime | raw 原接口入库 |
| `POST /source/build/worker/run-once` | worker/验收 | raw 到 source 构建 |
| `POST /source/release/preflight` | scheduler、data-inspector、模型 release 前置检查 | source coverage/freshness 门禁 |
| `GET /source/ops/production-readiness` | scheduler、data-inspector、验收脚本 | 生产拍板门禁 |
| `GET /source/ops/daily-data-summary` | admin 看板、scheduler 对账审计 | 按 `trade_date` 只读汇总 raw job、source build、source gap 和 source 标准表当日产出；不触发 fetch/build/provider |
| `GET /source/ths/paid-probability/cookie/status`、`PUT /source/ths/paid-probability/cookie` | 前端受控代理/人工 | 查看脱敏 Cookie 状态、替换运行库留存 Cookie |
| `POST /source/ths/paid-probability/probe`、`POST /source/ths/paid-probability/fetch-current-batch` | 前端受控代理/scheduler | 探测 Cookie 是否可取数；可用时按当前候选批次提交付费概率抓取 |
| `GET /source/ths/paid-probability/batch-status`、`POST /source/ths/paid-probability/deadline-check` | 前端受控代理/scheduler | 查看批次概率入库状态；仅下一交易日 09:00 后允许将未补齐批次标记为放弃 |

## Release Preflight / Source Build Guard Assets

| Asset | Rule | Downstream effect |
|---|---|---|
| `source.trade_calendar_v1.pretrade_date` | `hot_candidates / preopen_release_gate` resolves `source.daily_bar_v1` to the previous trading day while same-day tradability facts remain on request `trade_date`. | scheduler `current_closure`, research payload preflight and official release preflight share the same date-role contract. |
| `governance.model_release_preflight_v1` | Missing previous-trade-date resolution is a blocker: `source.trade_calendar_v1.pretrade_date:<any>:missing_for_<trade_date>`. | No official signal can be released when the calendar anchor is absent. |
| `governance.source_build_trigger_v1` | Build success requires parsed source identity to match requested job `symbol` and `trade_date` for date-guarded source tables. | A provider row for a different date/symbol stays as raw evidence and does not create false `source.*` rows or lineage. |
| `source.daily_bar_v1` / `source.adjusted_daily_bar_v1` / `source.index_daily_bar_v1` | Single-field repair expands build values to the provider-mapped full daily row from the same raw payload before source/lineage persistence. Missing raw fields remain warnings or write-time blockers; no mock/default price facts are generated. | P0 repairs such as `close_price` can persist rows that satisfy physical OHLC requirements while preserving field-level lineage for the actual raw values written. |
| `source.trade_status_v1` | Tencent `daily_bars` is a limited backup build path: complete OHLC plus positive volume may derive `is_tradable=true`, `is_suspended=false` and `raw_status=daily_bar_present`; Tencent daily bars must not derive `is_st`, so ST remains `NULL` / gap unless BaoStock `isST` or another contracted status source supplies it. | Model-four Day1 candidate repairs can clear table-level trade-status gaps from real daily-bar evidence while avoiding fake ST facts. |

`source.trade_status_v1.is_delisting_risk` is a separate stock-basic risk fact. BaoStock `query_stock_basic` and Tushare `stock_basic` may update only this field from real list/delist status evidence; they must not be counted as tradability, suspension, ST, or raw daily status evidence.
For admin daily summaries, `source.trade_status_v1.source_row_count` is an effective complete-row count: a row is counted only when `is_tradable`, `is_suspended`, `is_st`, and `is_delisting_risk` are all non-null. `latest_source_available_at` may still advance on partial source writes so operators can see data movement without overstating completion.
| `source.limit_price_v1` | Single-field repairs expand to the complete limit-price row. Raw pre-close remains primary; if a backup raw daily payload lacks pre-close, source build may only use the previous trading day's usable `source.daily_bar_v1.close_price` resolved by `source.trade_calendar_v1.pretrade_date`. Missing daily close keeps the build failed. | Model-four Day2 near-limit watch can consume `up_limit_price` without manual SQL or fake prices, while gaps remain visible when the previous-close anchor is absent. |
| `source.daily_bar_v1` backup plans | Backup repairs are merged by backup request hash and ordered by canonical-field coverage. | P0 price/volume backups can run before narrower amount/pct_chg backups in a multi-field daily repair. |

## Fetch 队列零行备源资产

2026-07-13 stock universe repair contract: normal scheduling still tries BaoStock `query_all_stock` as the `source.stock_universe_daily_v1` full-market primary job first. Only when that primary job truly fails or returns zero rows does the same fetch batch fan out BaoStock `query_history_k_data_plus_daily_raw` symbol backup jobs from the A-share set in `source.stock_master_v1`. Internal full-market source reads use a 20000-row limit so scheduler/repair planning is not truncated by the public `/source/rows` default 1000-row guard. Backup build writes only real `tradestatus/tradeStatus`, `isST`, and available `source.stock_master_v1.stock_name`; unparseable status remains warning/gap, never default tradable, never sample symbols. Repeat repairs against a terminal failed market-batch request must create an auditable job under the new `fetch_batch_id` and reference the old failed job through `backup_of_job_item_id` / callback payload; `succeeded + job_count=0` repair batches are forbidden.

2026-07-13 duplicate success repair contract: a historical `succeeded` or `skipped_duplicate` job is reusable only when it still provides raw audit hashes or a live source-build path for the current planned source identity. If the historical primary lacks raw audit hashes and its backup route is already terminal unusable for the same request hash, a new repair job must be queued for the original planned provider request with `__repair_attempt_id`; returning an empty `succeeded` batch is forbidden. The worker strips `__repair_attempt_id` before provider execution, so raw/source/lineage hashes continue to represent the real provider request.

2026-07-14 fetch submit performance contract: in Postgres queue mode, keyed submits must first read `governance.raw_fetch_idempotency_key_v1` and return the existing batch before plan expansion. New keyed batches must persist the idempotency row immediately after `governance.raw_fetch_batch_v1` is created, before per-job queue writes, so scheduler/data-inspector retries after timeout or API restart do not rebuild full A-share plans. Duplicate detection for the planned job set then uses one durable lookup keyed by `provider + api_name + raw_table_name + request_hash` for all planned jobs before queue writes. This keeps full A-share scheduled submits from issuing thousands of historical duplicate queries while preserving the same callback, raw/source build trigger and lineage boundaries. Memory mode and local tests may still fall back to the single-request lookup.

2026-06-18 定向解锁后，fetch orchestration 对有备源的 P0/P1 数据资产增加零行保护：

| 资产 | 规则 | 审计 |
|---|---|---|
| P0/P1 job | 真实 provider 返回 `row_count=0` 时，不得标记为可用成功，worker 以 `provider returned zero rows; backup required` 完成失败；final backup 没有二级备源时保留失败状态 | `governance.raw_fetch_job_item_v1.status=failed`、`last_error_code=provider_structured_error` |
| backup job | primary 空结果或历史不可审计成功触发第一条 backup plan；若同 `provider + api + raw_table + request_hash` 的 backup job 已存在且处于终态不可用，则复用该 job 重排，不新增重复行 | 新增或复用 `governance.raw_fetch_job_item_v1` backup job，`backup_of_job_item_id` 指向 primary；复用时追加 `job_requeued` |
| callback/outbox | backup 排队必须可见 | `governance.raw_fetch_callback_event_v1.event_type=backup_job_queued` |
| duplicate repair | 重复提交命中历史 `succeeded/skipped_duplicate` 但缺 `raw_request_hash` 或 `raw_response_schema_hash` 时，不再静默跳过 | 新 batch 追加 `backup_job_queued`；旧 job/callback/build trigger 原样保留；复用旧 backup 时 `payload.reused_existing_job=true` |
| failed duplicate repair | 重复提交命中历史 `failed/cancelled/dead_letter` 同 raw `request_hash` 时，不再计为静默 skip；当前 planned source 表会驱动备源排队或旧 job 重排 | 可排备源时 `submitted_job_count=1`、`skipped_duplicate_count=0`；复用旧 backup 时追加 `backup_job_queued(reused_existing_job=true)`，并在 job `request_params.__source_build_aliases` 记录当前 `fetch_batch_id + source_table_name` |
| active duplicate alias | 重复提交命中仍处于 `queued/leased` 的同 raw `request_hash` job 时，不新建 raw job，但必须在该 active job 上记录当前批次和 source 表 alias | job `request_params.__source_build_aliases` 追加 `fetch_batch_id + source_table_name`；原 job 成功完成后为 alias 批次补建 `source_build_trigger`，避免候选级 `daily_bar/limit_price/trade_status` 共用 raw 时新批次空转 |
| source build alias | 旧 job 属于其他 source 表但被当前请求复用/重排时，成功完成后必须给当前 source 表补建 trigger | `source_build_trigger` 继续以同一 `job_item_id` 追 raw/source/lineage，`source_table_name` 使用当前请求表，禁止只给旧表建 trigger |
| idle source build drain | catch-up 批次只复用历史 raw job、没有新 raw job 可租赁时，`source_build_trigger` 仍必须由 `source-data-worker` 空闲轮次消费 | `run_worker_once` 在 `leased_count=0` 且非 dry-run provider 时调用 source build worker；只消费 queued trigger，不绕过 raw/source/lineage，不手写 source 表 |

2026-06-18 回归验证：`PYTHONPATH=services/source-data-service/src python -m pytest -q services/source-data-service/tests/test_source_data_service.py -k duplicate` 通过 4 个 duplicate 用例；`PYTHONPATH=services/source-data-service/src python -m pytest -q services/source-data-service/tests` 通过 90 个 source-data-service 单测。定向发布仅替换 `source-data-service` API 容器，镜像 `infra-source-data-service:latest=d04d1fde123f`；容器内代码确认 `__source_build_aliases=true`、terminal duplicate repair branch=true；`/source/ops/production-readiness?require_postgres=true&require_real_provider_probe=true` passed；`scripts/source_data_acceptance.py --require-postgres` 写入 `acceptance_b2d2f9b3d1c4422fa0a5`，status=passed，can_lock_candidate=true；fetch queue 仍为 queued=0、leased=0、dead_letter=0；scheduler-service 与 data-inspector-service 均 ready。

2026-06-18 `source.minute_bar_v1 / 000063.SZ / 2026-06-12` 运行证据：

| 资产 | 状态 | 证据 |
|---|---|---|
| primary raw | EastMoney `minute_bars` 历史成功不可用 | `fetch_job_d7b305c3155947048625` 为 `succeeded`，但 `row_count=0`、`raw_request_hash=NULL`、`raw_response_schema_hash=NULL`，source build trigger 均 failed |
| backup raw | Tencent `minute_bars` 复用重排后真实失败 | `fetch_job_232a9a40a2ce4991b81d` 被 `fetch_batch_21d4215b24a04ab4b9eb` 触发复用重排；最终 `status=failed`、`last_error_code=provider_structured_error`、`last_error_message=provider returned zero rows; backup required` |
| raw/source/lineage | 保持真实缺口 | `raw_eastmoney.minute_bars_v1=0`、`raw_tencent.minute_bars_v1=0`、`source.minute_bar_v1=0`、`governance.source_lineage_v1=0` for `000063.SZ / 2026-06-12` |
| 下游 preflight | 禁止 dispatch | no-persist `POST /scheduler/model-payload/assemble-preflight` 对 `hot.release_gate.preopen` 返回 `blocked_data_gap`，`gap_codes=[source_gap:minute_bar_missing]`，`source_preflight` passed，`realtime_quote_v1` 已 usable |
| 发布自检 | 服务可继续锁定候选 | `/source/ops/production-readiness?require_postgres=true&require_real_provider_probe=true` passed；`scripts/source_data_acceptance.py --require-postgres` exit 0，`acceptance_run_id=acceptance_7e7560c4660f4e0186bb`，`can_lock_candidate=true`；source/scheduler/data-inspector ready |

## 日生命周期看板只读资产

`source_daily_data_summary_v1` 是 source-data-service 给 admin 看板的只读日报合同。它只读 `governance.raw_fetch_job_item_v1`、`governance.source_build_trigger_v1`、`governance.source_build_execution_result_v1`、`governance.source_gap_v1` 和可按日期识别的 `source.*` 标准表，按 `source_table_name` 汇总成功、等待、执行中、失败、build、lineage、当日 source 行数和最新更新时间。

Daily summary counts build failures as final only when they are still unrecovered for the same `source_table_name + symbol + trade_date`. A later successful build with source rows for that same identity moves the older failed/skipped build into `build_failure_audit_count` and keeps it out of `build_failed_count`, `build_failed_results`, and `data_failed_table_count`. This keeps the admin board truthful: recovered bad attempts remain visible as audit warnings, but do not lower today's completion rate.

Full-A daily tables are not completed by any non-zero row output alone. `source_daily_data_summary_v1` marks `source.stock_universe_daily_v1`, `source.trade_status_v1`, `source.limit_price_v1`, `source.daily_bar_v1`, and `source.adjusted_daily_bar_v1` as `coverage_insufficient` when the target-day row count is below 99.5% of the full-A universe baseline, using at least a 5000-row floor. These rows set `final_data_failed=true` and increase `coverage_insufficient_table_count`; admin boards and model release checks must treat them as unfinished/failed data assets until a formal repair/backfill produces complete source rows and lineage.

该日报用于回答“今天哪些数据已经产出、哪些还在等待、哪些采集失败”，不能替代 `/source/release/preflight`、质量门禁或模型输入覆盖检查。失败样本必须保留 provider、api、job_item_id、fetch_batch_id、symbol、error_code 和 error_message；缺事实不得补 0、空字符串、mock 或前端推断。

2026-07-14 性能边界：`source_daily_data_summary_v1` 的 build 恢复判定必须先聚合成功身份，再与失败结果做连接，禁止对每条失败结果重复扫描全量同日 build facts；timestamp 型 source 表按半开区间统计当日行数，禁止用 `列::date = trade_date` 破坏索引。`source_build_trigger` 消费必须走 Postgres 有界 queued 查询并按最早 `created_at` 消费，trigger 创建去重必须按完整 planned identity 精确查询 durable 表；不得用“最近 1000 条 trigger”推断全量积压状态。
## 调度频率

- 一次性/初始化：交易日历使用 `none` 范围，股票主数据和 provider symbol map 使用 `full_a_share` 市场批接口。
- 日调度盘前：当日 universe 使用 `full_a_share` 市场批接口；交易状态、停牌/ST/退市风险、涨跌停价从当日 universe 展开为全 A 逐股日频任务。
- 日调度收盘：日线、前复权、涨跌停价格、资金流等逐股日频表使用 `full_a_share`；涨停事件使用市场批接口。
- 日调度付费概率：15:20、16:05、18:00、20:30 通过 `/source/ths/paid-probability/fetch-current-batch` 抓取当前候选批次；09:01 通过 `/source/ths/paid-probability/deadline-check` 检查已超过下一交易日 09:00 的未补齐批次。
- 日调度收盘后：资金流、板块、新闻事件。
- 分钟级：竞价、报价、分钟线只允许 `configured_symbols`，不做全 A 常规分钟级调度。`source.auction_snapshot_v1` 由 EastMoney auction 主源和 Tencent/Sina auction 备验进入 raw/source/lineage；source canonical 字段为 `virtual_open_price`、`matched_volume`、`matched_amount`、`event_time`，物理行 `snapshot_time` 由 source build 使用 provider event time 写入。
- 窗口级：模型四 Day1 候选事实补齐和 Day2 10:20-10:40 逐笔/分钟/报价使用 `stage_candidates`。Day1 候选由 scheduler 从 `source.limit_event_v1` 的 THS 公开涨停池/T 字板事件筛出；source-data-service 只执行候选级 fetch orchestration，不自行生成候选。
- 巡检触发：P0/P1 缺口诊断和修复。

## Universe Scope 数据资产边界

| scope | 使用资产 | 读写边界 | 下游意义 |
|---|---|---|---|
| `explicit_symbols` | 请求体传入的 `symbols` | 只用于临时取数、修复或明确指定的小集合；缺 `symbols` 时不得猜测样本。 | 其他服务临时索取数据必须显式声明对象。 |
| `full_a_share` | `source.stock_universe_daily_v1`，为空时退读 `source.stock_master_v1` | `source.stock_universe_daily_v1`、`source.limit_event_v1`、`source.stock_master_v1` 作为市场批接口保持单 job；逐股日频表展开为可交易全 A 股票。 | 模型三和共享日频底座可全市场扫描；模型四 Day1 只用全市场涨停事件/涨停池做候选发现，不做全 A 高频/报价盲扫。 |
| `stage_candidates` | 上游模型阶段候选 `symbols` | source-data-service 只校验并提交 fetch orchestration，不生成候选、不扩大到全市场。 | 模型四 Day1 候选事实补齐和 Day2/Day3 高频窗口只抓阶段候选，避免全 A 分钟/逐笔/报价抓取压垮 provider 和队列。 |

`source.stock_universe_daily_v1` 的主源是 BaoStock `query_all_stock` 市场批接口。source build 将 `code_name` 写入 `stock_name`，将 `tradeStatus` 原文写入 `trade_status`，并仅在 `tradeStatus` 可解析时派生 `is_tradable`；不可解析或缺失时保留 warning/NULL，不得默认可交易。当前物理表只包含 `stock_name/trade_status/is_tradable/is_st`，不得把 `source.trade_status_v1` 才拥有的 `is_suspended/is_delisting_risk` 写入 universe 表。

`source.stock_universe_daily_v1` 只记录全 A 股票，不记录 `query_all_stock` 原始返回里的指数、基金、债券、B 股或其他非 A 对象。A 股规则为：沪市 `60*`/`68*`.SH，深市 `00*`/`30*`.SZ，以及 provider 返回时的北交所 `4*`/`8*`/`92*`.BJ。source build 对沪市 `000*` 指数、深市 `399*` 指数、沪深基金号段、`200*`/`900*` B 股等对象直接跳过；正式 batch build 成功后按交易日清理该表已存在的非 A 旧行，`full_a_share` 读取时也用同一规则二次过滤，避免旧污染数据流入模型三/模型四全市场扫描。

市场批接口的 duplicate 复用必须保留当前计划身份。若新的 `full_a_share` universe 任务复用历史同 `request_hash` 的 `query_all_stock` job，`source_build_trigger` 必须以当前 planned job 生成 `symbol=NULL`、`build_scope=batch`；source build 执行时以 trigger 的身份过滤 raw rows，禁止沿用旧样本 job 的 `symbol_date` 身份把全市场 raw 裁成单票。

`source_build_trigger` 与 source build worker 只允许在同一个 `fetch_batch_id` 内去重。新的 catch-up 或链路迭代验证 batch 复用历史 raw job 时，必须为当前 batch 重新生成 trigger 并执行 source build；worker 判断已处理 trigger 时必须把 `fetch_batch_id` 纳入 key，旧 batch 下已有 trigger 或成功 build result 不得阻断当前 batch 的重建、lineage 和非 A 旧行清理。

`source.daily_bar_v1`、`source.adjusted_daily_bar_v1`、`source.trade_status_v1`、`source.limit_price_v1`、`source.stock_moneyflow_daily_v1` 是全 A 日频共享底座；`source.auction_snapshot_v1`、`source.realtime_quote_v1`、`source.minute_bar_v1`、`source.trade_tick_v1` 是窗口/候选级高频资产，不进入全 A 常规调度。`source.auction_snapshot_v1` 的 source build 必须把 raw `price/volume/amount/event_time` 映射到物理 `virtual_open_price/matched_volume/matched_amount/snapshot_time/event_time`，`provider_definition` 只留在 raw/lineage 审计中，不作为 source canonical 字段。模型四 Day1 的 `source.realtime_quote_v1.float_market_cap` 只对 `source.limit_event_v1` 筛出的 T 字板候选补齐。`full_a_share` 若无法从 source 层读到股票集合，必须阻断并要求先补 `source.stock_universe_daily_v1`，不得回退到样本代码或前端配置。

Postgres 持久化队列是 `raw_fetch_batch_v1`、`raw_fetch_job_item_v1` 和 callback/outbox 的运行事实源。worker 启动、重启、租约前和 lease maintenance 必须按 job 的 `fetch_batch_id` 恢复 batch 回调上下文，并以 Postgres 中更新的 queued/retry 状态刷新 worker 进程内旧状态；无法恢复 batch 的孤儿 job 只能进入 `dead_letter/fetch_batch_missing`，不得让 worker 进入 KeyError 重启循环，也不得静默丢弃任务。

相同 provider/API/request_hash 的 failed/cancelled/dead-letter backup job 不允许在同一 `source_table_name` 内重复 requeue；只有新 `source_table_name` 复用旧失败 backup，或 `succeeded` 但缺 raw 审计 hash 的 unusable backup，需要重新验证时才允许重排。

Postgres durable job state 是队列观测、worker 租约和终态的事实源。API/worker 进程内 job 缓存只允许被更新的 durable 行刷新，不得用旧缓存覆盖数据库终态；`complete_fetch_job` 完成后必须清空 `worker_id`；`upsert_job` 只能在新 `updated_at` 不早于现有 durable 行时更新，防止陈旧 queued 缓存把已失败、已成功或 dead-letter 的 job 重新写活。最终失败的 backup job 不得再次被 worker lease。

2026-07-15 起，`source-data-worker` 在每次 lease 前自动执行过期租约维护；durable active job 装载与 queued `source_build_trigger` 消费在同优先级下按最新 `trade_date` 优先，再按 `created_at` 排序。该规则用于保障日生命周期看板和当日模型依赖数据优先落地，历史积压不得饿住今日任务；已存在历史 queued/backlog 不被删除，仍由正式 worker 后续处理。


2026-07-20 scheduler orchestration context contract: scheduler-origin `/source/fetch/submit` jobs may persist internal `request_params.__orchestration_context` for request-hash partitioning and lifecycle close. The context is audit metadata for source queue/build lifecycle only; worker provider calls must strip internal `__*` keys, and downstream models/frontends must not treat it as market data. Durable maintenance also closes legacy same-day scheduler jobs without this context by source-table fallback windows: 10 minutes for intraday quote/minute/tick/auction, same-market-day 23:59:59 for preopen universe/trade-status/limit-price, 4 hours for paid probability, and 2 hours for daily close/research/news. Expired lifecycle jobs are cancelled, not deleted; missing target facts still require a new formal fetch/repair/backfill.

2026-07-15 worker filter contract: `SOURCE_DATA_WORKER_PROVIDERS` and `SOURCE_DATA_WORKER_QUEUE_NAMES` may start targeted workers. The filters must be pushed down into the durable `governance.raw_fetch_job_item_v1` active-state query before the bounded queued limit is applied; loading global first-N queued jobs and filtering in process is forbidden. This prevents a BaoStock normal daily backlog from starving EastMoney moneyflow, Tencent backups, or research queue assets. Compose guards two targeted roles: `source-data-worker-eastmoney-research` for EastMoney research queue assets and `source-data-worker-tencent-normal` for Tencent normal daily backup assets.

2026-07-23 worker throughput contract: the general `source-data-worker` defaults to `SOURCE_DATA_WORKER_MAX_JOBS=20`, but provider/API policies remain authoritative. BaoStock `query_history_k_data_plus_daily_raw` and `query_history_k_data_plus_daily_qfq` may run daily repair bursts at `max_concurrency=12` / `requests_per_minute=300`; this applies only to full A-share daily repair/ingest throughput and does not loosen THS paid probability, THS public limit pool, AkShare moneyflow, Baidu news, or other low-concurrency adapters.

2026-07-23 lease fairness contract: when queued jobs share the same priority, trade date, queue, provider, and API, durable hydration and in-memory leasing must round-robin by `source_table_name`. A large P0 repair batch for `source.limit_price_v1` must not monopolize all BaoStock daily leases while `source.daily_bar_v1`, `source.adjusted_daily_bar_v1`, or `source.trade_status_v1` remain queued for the same day.

2026-07-23 active duplicate promotion contract: a higher-priority repair/preflight submit that matches an existing queued duplicate raw job must promote the existing job's `priority` and `queue_name` in place after registering the source-build alias. The submit response may remain `skipped_duplicate` for compatibility, but durable job state must move from old P1 normal ingestion to the higher queue so formal repair work is not starved. Leased jobs are not preempted.
Provider readiness 证据采用 72 小时 recent usable 窗口：`/source/ops/production-readiness` 可以使用窗口内最新可用真实 probe 作为通过依据，同时必须返回 `latest_observed_results` 保留最新失败、零行或异常观测。若窗口内没有 usable 观测则 readiness blocked；若有 recent usable 证据，最新失败观测只能作为审计风险提示，不得删除、隐藏或改写。

2026-07-23 probe sample guard: BaoStock `query_adjust_factor` readiness evidence must use a symbol and historical window that can genuinely produce adjustment-factor rows, currently `sz.000063` over a long historical range. `sz.000001` can legitimately return zero adjustment rows and must not by itself be treated as provider or schema failure.

## 当前基础表状态

2026-06-17 定向修复后，P0 基础表已通过正规 raw/source/lineage 链路落库：

| 数据资产 | 当前覆盖 | raw/source/lineage 证据 | 真实边界 |
|---|---|---|---|
| `source.trade_calendar_v1` | `2026-01-01` 至 `2026-12-31`，365 天，242 个交易日 | BaoStock `query_trade_dates` raw 365 行；`source_build_trigger_3e12e9c58a04442bb4f2` succeeded；lineage 1460 行 | 本次请求到 `2027-12-31`，BaoStock 实际只返回到 `2026-12-31`；2027 日历未补齐，必须后续通过 fetch orchestration 继续补采。 |
| `source.stock_master_v1` | `000063.SZ`、`000759.SZ` 两个当前研究/调度样本身份锚点 | BaoStock `query_stock_basic` raw 2 行；两个 source build trigger succeeded；lineage 16 行 | 不是全市场股票主数据；全市场 identity / provider symbol map 后续仍需按分批 fetch orchestration 补齐。 |

## 性能与索引

首次上线索引基线是 `infra/sql/0025_source_data_foundation_indexes_v1.sql`，已同步 `infra/sql/bootstrap_schema.sql`。索引覆盖交易日历、股票身份、日 universe、日线/前复权、交易状态、涨跌停、分钟/逐笔、资金流、新闻、lineage duplicate audit、source build trigger、canonical write audit 和 urgent release queue。`infra/sql/0028_ths_paid_probability_v1.sql` 覆盖 `governance.ths_paid_probability_cookie_v1`、`raw_ths.paid_limit_up_probability_v1`、`source.ths_paid_limit_up_probability_v1`、`governance.ths_paid_probability_batch_status_v1` 的 `symbol + trade_date`、`credential_version`、`available_at`、`status + updated_at` 读写路径。

## 禁止事项

- 禁止模型、scheduler、frontend、Jarvis 直接读取 raw 表作为模型事实。
- 禁止把同花顺付费概率 Cookie 明文写入仓库、raw request params、日志、验收输出或前端响应；除 `ths.paid_limit_up_probability` 外，THS 接口仍禁止登录态/Cookie/token/动态 `hexin-v`。
- 禁止用 0、空字符串、mock、示例 payload 或 GPT 推断补 source 缺口。
- 禁止 provider 真实返回绕过 raw/source/lineage 直接进入模型。
- 禁止普通迭代停止、重启、删除、重建 `source-data-service`。

## 2026-06-17 冻结记录

本轮首次上线重建后，数据源闭环已通过最高规格验收并正式冻结。确认来源为用户本轮“按本任务书执行”，以及 2026-06-17 明确确认“数据源服务稳定后可以冻结”。

| 冻结对象 | 数据资产范围 | 验收证据 | 只读验收 | 解锁条件 |
|---|---|---|---|---|
| `source-data-service -> DS-7 production readiness -> real probe + quality matrix gate` | `governance.source_data_acceptance_*`、`governance.source_probe_result_v1`、`governance.model_release_preflight_v1`、`source.daily_bar_v1`、`source.adjusted_daily_bar_v1` | `acceptance_92b1fd11770b421d8cf7` passed；real provider probe 15/15 usable；quality matrix 8/8 passed；`/source/ops/production-readiness` passed 且 `can拍板=true` | `/healthz`、`/readyz`、`/source/ops/production-readiness`、`/source/ops/acceptance-runs`、`scripts/source_data_acceptance.py` | P0 probe、quality matrix、readiness 或 release preflight 出现 blocked，或用户明确批准解锁。 |
| `source-data-service -> source foundation schema -> trade calendar and source indexes` | `source.trade_calendar_v1` current contract 字段、source foundation indexes、`governance.source_lineage_v1` duplicate audit index、urgent queue index | schema-bootstrap exited 0；24 个 SQL migration applied；trade calendar current columns visible；source foundation indexes present | `information_schema`、`pg_indexes`、schema-bootstrap 日志、只读 SQL 合同测试 | schema-bootstrap 失败、查询性能退化、字段合同不可见，或用户明确批准解锁。 |
| `source-data-worker -> postgres queue consumer -> raw/source/lineage callback closure` | `governance.raw_fetch_batch_v1`、`governance.raw_fetch_job_item_v1`、`governance.raw_fetch_callback_event_v1`、`governance.source_build_trigger_v1`、`governance.source_lineage_v1` | queue backend=postgres；queued=0；leased=0；dead_letter=0；raw rows=272216；source rows=4827；lineage rows=29582 | `/source/fetch/persistence/status`、`/source/fetch/queues/summary`、worker logs、dry-run build worker | dead-letter 非空、lease/heartbeat 卡死、callback/outbox 丢失，或用户明确批准解锁。 |
| `source-data-worker -> source foundation build -> trade_calendar and stock_master mapping` | `source.trade_calendar_v1`、`source.stock_master_v1`、对应 `governance.source_lineage_v1` | `source.trade_calendar_v1=365`、calendar lineage=1460；`source.stock_master_v1=2`、stock_master lineage=16；source/scheduler/data-inspector ready | 只读 SQL、`/source/rows`、`/source/lineage/records`、`/source/ops/production-readiness` | build failed、lineage 缺失、2027 calendar 需要补采、全市场 stock master 需要补齐，或用户明确批准解锁。 |
| `source-data-service -> fetch orchestration -> zero-row backup guard` | `governance.raw_fetch_job_item_v1`、`governance.raw_fetch_callback_event_v1`、`raw_eastmoney.minute_bars_v1`、`raw_tencent.minute_bars_v1`、`source.minute_bar_v1`、`governance.source_lineage_v1`、`governance.model_release_preflight_v1` | `fetch_batch_21d4215b24a04ab4b9eb` 复用重排 `fetch_job_232a9a40a2ce4991b81d`；primary/backup 对 `000063.SZ / 2026-06-12` 均零行；`source.minute_bar_v1=0`、lineage=0；preflight `blocked_data_gap` + `source_gap:minute_bar_missing`；`acceptance_7e7560c4660f4e0186bb` passed | `/source/fetch/queues/summary`、`/source/ops/production-readiness`、`scripts/source_data_acceptance.py --require-postgres`、只读 raw/source/lineage SQL、no-persist scheduler assemble-preflight | 新 provider 可覆盖该分钟线缺口、queue/retry/dead-letter 异常、preflight 阻断规则误判，或用户明确批准解锁。 |
| `source-data-service -> fetch orchestration -> failed duplicate request_hash requeue/backup` | `governance.raw_fetch_job_item_v1`、`governance.raw_fetch_callback_event_v1`、`governance.source_build_trigger_v1`、`governance.source_lineage_v1`、共享 raw `request_hash` 下游 source 表 | 历史 `failed/cancelled/dead_letter` 同 raw `request_hash` 不再静默 skip；当前 source 表驱动备源排队或旧 job 重排；`request_params.__source_build_aliases` 记录当前 `fetch_batch_id + source_table_name`；`acceptance_b2d2f9b3d1c4422fa0a5` passed | `/source/fetch/queues/summary`、`/source/ops/production-readiness`、`scripts/source_data_acceptance.py --require-postgres`、P0 fetch dry-run、只读 callback/job/build trigger 查询 | 失败终态 duplicate 再次静默跳过、alias trigger 漏建、重复插入同 request_hash backup job、绕过 source-data-service fetch orchestration，或用户明确批准解锁。 |
| `source-data-service -> fetch orchestration -> universe_scope full A/stage candidates` | `FetchPlanRequest.universe_scope`、`source.stock_universe_daily_v1`、`source.stock_master_v1`、`source.daily_bar_v1`、`source.adjusted_daily_bar_v1`、`source.trade_status_v1`、`source.limit_price_v1`、`source.stock_moneyflow_daily_v1`、`source.trade_tick_v1` | `full_a_share` 从 source universe/master 展开；市场批接口保持单 job；逐股日频表按全 A 展开；`stage_candidates` 只接受上游阶段候选；禁止样本 fallback；本轮 source/scheduler 单测和 runtime guard 通过，重启前 ready/queue clear | `/source/fetch/plan` dry-run、`/source/fetch/queues/summary`、`/source/ops/production-readiness`、source 单测、scheduler source schedule 单测、readyz | universe source 为空、阶段候选来源合同变化、全 A 展开误把样本当全集、分钟/逐笔被误注册为全 A 常规调度、队列/readyz 阻断，或用户明确批准解锁。 |
| `source-data-worker -> source build worker -> fetch_batch scoped trigger dedupe` | `governance.source_build_trigger_v1`、`governance.source_build_result_v1`、`governance.source_lineage_v1`、`source.stock_universe_daily_v1`、共享 raw `request_hash` | source build worker 的 processed key 纳入 `fetch_batch_id`；新 catch-up batch 复用历史 raw job 时仍必须重建 source、lineage 和清理同交易日非 A 旧行 | `/source/build/triggers`、只读 SQL、source 单测、acceptance 脚本、容器内代码探针 | 新 batch 被旧 trigger 阻断、lineage 漏写、清污漏执行、duplicate request_hash 复用语义变化，或用户明确批准解锁。 |
| `source-data-worker -> source build worker -> idle queued trigger drain` | `governance.source_build_trigger_v1`、`governance.source_build_result_v1`、`governance.source_lineage_v1`、`source.daily_bar_v1`、`source.limit_price_v1`、`source.realtime_quote_v1`、`source.trade_status_v1`、共享 raw `request_hash` | worker 空闲轮次消费 queued build trigger；alias-only/catch-up batch 即使没有新 raw job，也必须继续写入 source/lineage；`2026-06-22` 模型四 Day1 候选 65/65 四表覆盖已验证 | `/source/build/triggers`、65 候选四表覆盖 SQL、`/source/release/preflight`、scheduler assemble-preflight、source 单测、acceptance 脚本、容器内代码探针 | idle drain 被移除、queued trigger 滞留、coverage 退回、手写 source 绕过 raw/source/lineage、启动模型服务替代数据源修复，或用户明确批准解锁。 |
| `source-data-service -> stock universe build -> full A-share filter and prune` | `source.stock_universe_daily_v1`、`raw_baostock.query_all_stock_v1`、`governance.source_lineage_v1` | `2026-06-22` 正式 batch build 后只保留 5207 个 A 股股票，tradable=5191、not_tradable=16、unknown=0；指数、基金、B 股污染计数=0；trigger `source_build_trigger_60154f60991c44608ef6` succeeded | 只读 SQL 行数/污染计数、`/source/fetch/plan` full_a_share dry-run、`/source/ops/production-readiness`、`scripts/source_data_acceptance.py` | 非 A 对象进入 universe、`is_tradable` 缺失被默认为 true、source build 绕过 raw/source/lineage、full_a_share fallback 到样本代码，或用户明确批准解锁。 |
| `source-data-service -> acceptance runner -> real probe date semantics and recent evidence gate` | `governance.source_data_acceptance_*`、`governance.source_probe_result_v1`、`/source/ops/production-readiness` evidence | `scripts/source_data_acceptance.py` 区分日线已结算日期和分钟/快照当前窗口；即时 probe 失败时只能依赖 readiness 72h recent usable 放行，并保留 latest observed failure 审计；`acceptance_ab68236b2e764b85b768` passed | acceptance runs、probe results、production-readiness、source 单测 | 隐藏即时失败 probe、recent usable 缺失仍放行、质量矩阵 blocked 被忽略、非交易日/历史日线日期误套分钟接口，或用户明确批准解锁。 |
| `source-data-service -> ths paid probability -> cookie/probe/fetch/deadline` | `governance.ths_paid_probability_cookie_v1`、`raw_ths.paid_limit_up_probability_v1`、`source.ths_paid_limit_up_probability_v1`、`governance.ths_paid_probability_batch_status_v1` | Cookie 只存运行库；provider request params 只含 `date/stock_code/credential_version`；成功返回通过 raw/source/lineage；无备源；下一交易日 09:00 后才允许放弃未补齐批次 | Cookie status/probe、batch-status、deadline-check、source 单测、schema/bootstrap 文本自检 | Cookie 泄露、deadline 提前放弃、用手填/随机/0 补概率、为付费概率伪造备源、改变其他 THS public no-cookie 接口，或用户明确批准解锁。 |
| `source-data-service -> fetch orchestration -> durable job state anti-loop` | `governance.raw_fetch_job_item_v1`、worker lease、`worker_id`、`updated_at`、终态 job、backup job | source 单测 `102 passed`；最终失败 backup 不再被重复 lease；queue summary queued=0、leased=0、dead_letter=0；production-readiness passed | `/source/fetch/jobs/{job_item_id}`、`/source/fetch/queues/summary`、`/source/fetch/persistence/status`、source 单测 | 陈旧内存态覆盖 durable 终态、完成 job 仍残留 `worker_id`、失败 backup 再次被 lease、queue 卡住，或用户明确批准解锁。 |
| `source-data-service -> provider probe readiness -> 72h usable evidence with observed audit` | `governance.source_probe_result_v1`、`/source/ops/production-readiness`、`real_provider_probe_evidence.latest_results`、`latest_observed_results` | production-readiness passed；72 小时窗口内存在 usable 真实 probe；最新失败观测仍保留在 `latest_observed_results` | `/source/ops/production-readiness?require_postgres=true&require_real_provider_probe=true`、`/source/probe/results`、acceptance 脚本 | recent usable 窗口内无可用证据、latest observed 被隐藏或改写、readiness 漏阻断/误阻断，或用户明确批准解锁。 |

## Task Lifecycle And Expired Close

Since 2026-07-20, `governance.raw_fetch_job_item_v1` keeps explicit scheduler lifecycle metadata when available and applies a legacy same-day fallback when it is missing. Old `queued/leased` scheduler-service jobs in normal/research/urgent scheduler queues are closed as `cancelled + expired_lifecycle` by worker-side durable maintenance before leasing once their context or table fallback window has expired. This is not a data result and not a row deletion; formal repair/backfill must create new fetch job, batch, raw, source, and lineage evidence.

`governance.source_build_trigger_v1` triggers linked to these expired scheduler jobs are closed as `cancelled` when they have no terminal build execution result. `repair_queue`, `backfill_queue`, and `provider_probe_queue` remain protected from this automatic close; urgent scheduler release-gate jobs are no longer exempt once their lifecycle window is explicitly or implicitly expired. Daily summary exposes `raw_cancelled_count`, `raw_cancelled_jobs`, and `expired_closed_table_count` so the admin board can separate expired-closed work from waiting or failed work.

### 2026-07-23 Duplicate Reuse Data Asset Guard

For symbol-date source assets, duplicate raw fetch reuse is valid only when target source evidence exists or an active/succeeded build trigger can still produce it. A succeeded raw job without the corresponding `source.*` row and without a usable build trigger is treated as missing canonical output and is requeued as a repair attempt. The repair keeps `backup_of_job_item_id`, callback `job_requeued`, and the original raw/source lineage audit instead of silently counting as skipped duplicate.
