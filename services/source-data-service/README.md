# source-data-service

## Cross-Service Source Quality Matrix Gate

`scripts/core_services_acceptance.py --source-quality-matrix` uses this service's persisted acceptance evidence as the default quality-matrix gate for the source + model + scheduler closure chain. It reads `/source/ops/acceptance-runs`, finds the latest `quality_matrix` check written by `scripts/source_data_acceptance.py --quality-matrix`, and requires every requested `symbol + trade_date + source table` matrix entry to be covered and passed. Warnings remain blocking unless `--source-quality-allow-warning` is set. The core closure script only re-runs `/source/quality/multi-source/check` when `--force-live-source-quality-matrix` is explicitly supplied; in both modes it never imports provider adapters, never directly calls BaoStock / AKShare / Tencent / Sohu / Tushare / EastMoney / CNINFO, never restarts containers, and never replaces raw/source/lineage/preflight.

## Fetch Queue Raw Hash Audit

Current queue completion contract:

- `POST /source/fetch/jobs/{job_item_id}/complete` accepts `raw_request_hash` and `raw_response_schema_hash` from the worker after provider fetch and raw ingest.
- `FetchJobStatusOut` exposes both hashes so `GET /source/fetch/jobs/{job_item_id}` can audit the fetch job against the raw interface batch.
- Postgres queue persistence writes both hashes to `governance.raw_fetch_job_item_v1.raw_request_hash` and `governance.raw_fetch_job_item_v1.raw_response_schema_hash`; later status updates keep existing non-null hash values unless the worker supplies new values.
- `job_succeeded` callback payload includes `raw_request_hash` and `raw_response_schema_hash`; downstream callback/outbox consumers can reconcile job status, raw ingest, source build trigger and lineage without re-reading provider responses.
- In Postgres queue mode, `/source/fetch/callbacks` reads `governance.raw_fetch_callback_event_v1`, not only the API process memory list. Worker-created events such as `job_leased`, `job_heartbeat`, `source_build_trigger_created`, `job_succeeded` and `batch_completed` remain visible after API/worker process separation or restart.
- `/source/fetch/callbacks/dispatch` also reads pending durable outbox rows in Postgres mode and persists delivery status updates back to `governance.raw_fetch_callback_event_v1`; callback delivery state must not be lost because the worker and API run in different processes.
- `source-data-worker` passes the hashes returned by provider runtime/raw ingest into the completion callback. This keeps DS-6 raw/source/lineage evidence append-only and auditable.
- Duplicate fetch submissions that resolve to an already succeeded/skipped job ensure a matching `source_build_trigger` exists for the requested source table, symbol and trade date; duplicate suppression must not silently skip the raw-to-source build path.
- Duplicate fetch submissions that resolve to an active `queued` or `leased` raw job must register a `__source_build_aliases` entry for the current `fetch_batch_id + source_table_name`. When the shared raw job later succeeds, completion must create build triggers for both the original source table and every active alias; candidate-level batches such as Model 4 Day1 daily/limit/trade-status repairs must not finish as empty duplicate skips while the original raw job is still running.
- `source-data-worker` must drain queued `source_build_trigger` rows even when a worker cycle leases no raw fetch jobs. This keeps catch-up batches that only reuse historical raw jobs from stalling after trigger creation; source build still runs through `/source/build/worker/run-once`, writes `source.*` and `governance.source_lineage_v1`, and never hand-writes source rows.

## Release Preflight Date Semantics

`POST /source/release/preflight` and `POST /source/models/coverage/check` evaluate each required source row at the date role required by the model phase, not blindly at the request `trade_date`.

- `hot_candidates / preopen_release_gate`: `source.daily_bar_v1` uses the previous trading day resolved from `source.trade_calendar_v1.pretrade_date`; `source.trade_status_v1` and other same-day gate facts continue to use the current `trade_date`.
- If the previous trading day cannot be resolved, the request remains blocked with `source.trade_calendar_v1.pretrade_date:<any>:missing_for_<trade_date>`.
- Freshness and coverage checks use the same per-requirement trade date context, so scheduler readyz and model official release preflight see the same source visibility window.

This keeps a 09:29:40 preopen release gate from requiring same-day close price rows that cannot exist yet, while still blocking on true same-day tradability gaps.

## Source Build Requested Identity Guard

`source_build_trigger` success must mean the built source rows match the requested `symbol` and `trade_date`. For date-guarded source tables, including `source.daily_bar_v1`, `source.adjusted_daily_bar_v1`, `source.trade_status_v1`, `source.limit_price_v1`, `source.limit_event_v1`, `source.minute_bar_v1`, `source.realtime_quote_v1`, `source.stock_moneyflow_daily_v1`, `source.stock_universe_daily_v1` and `source.trade_tick_v1`, source build now rejects any raw row whose parsed source identity differs from the fetch job identity.

Example: a job requested for `2026-06-19` whose provider payload actually contains `2026-06-18` is recorded as a build error and does not create a `2026-06-19` source row or lineage. The gap remains visible to preflight, data-inspector and scheduler instead of becoming a fake successful source build.

## Source Build Physical Row Completeness

Single-field repairs for physical daily source rows may request one canonical field, but the source build writes the full mapped row from the same raw provider payload when the target table has row-level persistence requirements. For `source.daily_bar_v1`, `source.adjusted_daily_bar_v1`, `source.index_daily_bar_v1` and `source.limit_price_v1`, a repair such as `canonical_fields=["close_price"]` or `canonical_fields=["up_limit_price"]` expands build values to the complete mapped row or complete limit-price row available from the same source build context before writing source/lineage. Missing raw fields remain warnings or write-time blockers; the service never fills prices, volume, amount or pct fields with `0`, empty strings, mock payloads or inferred values.

`source.limit_price_v1` derives `pre_close_price`, `up_limit_price`, `down_limit_price` and `limit_rule` as one row. Raw daily payload fields `preclose` / `pre_close` / `pre_close_price` / `prev_close_price` remain the first source for `pre_close_price`. If a public backup raw daily payload lacks those fields, source build may only fall back to the previous trading day's usable `source.daily_bar_v1.close_price`, resolved through `source.trade_calendar_v1.pretrade_date`; if that standard source fact is absent, the build stays failed with a visible warning instead of fabricating a limit price.

`source.trade_status_v1` can use Tencent `daily_bars` only as a limited backup build path. When a Tencent raw daily row has complete OHLC and positive volume, source build may derive `is_tradable=true`, `is_suspended=false` and `raw_status=daily_bar_present`. Tencent daily bars do not carry a reliable ST flag, so `is_st` must remain `NULL` / gap unless BaoStock `isST` or another contracted status source provides the fact; the service must not fill `is_st=false` from daily-bar existence.

This keeps P0 gap repair precise while preventing a real raw daily-bar payload from failing physical source persistence only because the repair was triggered by one missing field.

## Fetch Queue Zero-Row Backup Guard

P0/P1 fetch jobs must not treat an empty provider result as a usable source fact. In a real worker cycle, when the provider returns `row_count=0`, `source-data-worker` completes the job as failed with `provider_structured_error` and error message `provider returned zero rows; backup required`. If the failed job carries `__backup_plans`, `source-data-service` appends a `backup_job_queued` callback and queues the first backup plan in the same fetch batch; if it is already the final backup, the failed state remains visible for retry/dead-letter governance. Dry-run provider checks still allow `row_count=0` so queue semantics can be tested without external calls.

Fetch plans merge backup repairs by backup request hash and sort them by canonical-field coverage before queuing. A multi-field daily-bar repair therefore can send the Tencent price/volume backup before a narrower Sohu amount/pct_chg backup, so P0 price fields are not delayed by lower-priority field coverage.

Duplicate fetch submissions also check historical succeeded/skipped jobs for raw audit hashes. If a duplicate primary job is marked succeeded but has no `raw_request_hash` or no `raw_response_schema_hash`, it is treated as an unusable historical success: the new batch queues the backup job instead of silently skipping or creating another failed source build trigger. If the backup job already exists in a terminal unusable state for the same `provider + api + raw_table + request_hash`, the service requeues that existing job and appends `job_requeued` plus `backup_job_queued(reused_existing_job=true)` callback evidence instead of inserting a second row that would violate the queue uniqueness contract. The old job/callback/build-trigger audit is retained; the repair path appends new queue and callback evidence.

Duplicate submissions that resolve to a historical `failed` / `cancelled` / `dead_letter` job are also terminal unusable facts, not true duplicates. The new batch rebuilds a duplicate repair context from the current planned `source_table_name`, `canonical_fields`, symbol, trade date, priority and backup plans. If a backup can be queued or an existing backup can be requeued, the submit result reports it as `submitted_job_count=1` and `skipped_duplicate_count=0`; if the reusable backup is already queued or leased, the job stores a `__source_build_aliases` entry so a later successful completion emits a `source_build_trigger` for the current source table as well as the original one. If the original terminal job has no backup plan, the original job is requeued with the same alias contract. This prevents a failed raw request reused across `source.daily_bar_v1`, `source.trade_status_v1`, `source.limit_price_v1` or other shared source tables from silently suppressing the current source build path.

Active duplicates are not terminal repair cases. If a new batch requests `source.daily_bar_v1`, `source.limit_price_v1` or another shared source table while an equivalent raw job from `source.trade_status_v1` is still `queued` or `leased`, submit must keep the new batch auditable by storing `__source_build_aliases` on the active job. The new batch may report duplicate skips because it does not create another raw job, but it must receive source build triggers when the active job completes successfully.

Regression verification:

```bash
PYTHONPATH=services/source-data-service/src python -m pytest -q services/source-data-service/tests/test_source_data_service.py -k duplicate
PYTHONPATH=services/source-data-service/src python -m pytest -q services/source-data-service/tests
```

2026-06-18 定向发布验证：

```text
target: source-data-service -> fetch orchestration -> failed duplicate request_hash requeue/backup
docker image: infra-source-data-service:latest -> d04d1fde123f
deploy: docker compose -f infra/docker-compose.yml up -d --no-deps --force-recreate source-data-service
runtime code: __source_build_aliases=true, terminal duplicate repair branch=true
health: /healthz ok, /readyz ready
contracts: /source/apis api_count=58, /source/contracts contract_count=63, source.daily_bar_v1 requirements=9
repair dry-run: /source/gaps/repair-plan source.daily_bar_v1.close_price 000063.SZ 2026-06-18 -> baostock primary + tencent backup
P0 fetch dry-run: /source/fetch/plan source.daily_bar_v1.close_price 000063.SZ 2026-06-18 -> urgent_release_gate_queue, job_count=1
production readiness: /source/ops/production-readiness?require_postgres=true&require_real_provider_probe=true -> passed
acceptance: scripts/source_data_acceptance.py --require-postgres -> acceptance_b2d2f9b3d1c4422fa0a5 passed, can_lock_candidate=true
queue: queued=0, leased=0, dead_letter=0 across all fetch queues
guards: data-inspector-service /readyz ready; scheduler-service /readyz ready
```

2026-06-18 runtime repair evidence for `research_payload_assembly` run `2095`:

```text
target: source.minute_bar_v1 close_price, 000063.SZ, 2026-06-12, hot.release_gate.preopen
historical primary: fetch_job_d7b305c3155947048625 eastmoney/minute_bars
  status=succeeded but row_count=0, raw_request_hash=NULL, raw_response_schema_hash=NULL
historical backup: fetch_job_232a9a40a2ce4991b81d tencent/minute_bars
  previous callback job_succeeded row_count=0, raw_response_schema_hash=NULL
repair submit: fetch_batch_21d4215b24a04ab4b9eb
  callback backup_job_queued reused_existing_job=true existing_fetch_batch_id=fetch_batch_d287829333ea44cbbec5
  callback job_requeued on fetch_job_232a9a40a2ce4991b81d
latest worker result:
  fetch_job_232a9a40a2ce4991b81d status=failed
  last_error_code=provider_structured_error
  last_error_message=provider returned zero rows; backup required
  raw_eastmoney.minute_bars_v1 rows=0 for request_hash=2233e354f251149791de31cd4d7bbd9218aeadf0f4e1605e85075d5d6d5e8f52
  raw_tencent.minute_bars_v1 rows=0 for request_hash=1153588a5b11f992e4a1cd1a6cb55ac8001c48594181efb1b24cae90cc8f1270
  source.minute_bar_v1 rows=0, governance.source_lineage_v1 rows=0
no-persist scheduler assemble-preflight:
  hot.release_gate.preopen -> blocked_data_gap
  scheduler gap_codes=[source_gap:minute_bar_missing]
  source_preflight passed, realtime_quote_v1 row_count=1 usable
post-change validation:
  /source/ops/production-readiness?require_postgres=true&require_real_provider_probe=true -> status=passed, can拍板=true
  scripts/source_data_acceptance.py --require-postgres -> exit 0, acceptance_run_id=acceptance_7e7560c4660f4e0186bb, can_lock_candidate=true
  /source/fetch/queues/summary -> queued=0, leased=0, dead_letter=0
  scheduler-service /readyz=ready, data-inspector-service /readyz=ready
```

Verification:

```bash
PYTHONPATH=services/source-data-service/src python -m pytest -q services/source-data-service/tests/test_source_data_service.py
```

## First-Launch Data Foundation

本服务在首次上线时按 source-first 顺序建立数据底座。所有采集必须走 `/source/fetch/plan` -> `/source/fetch/submit` -> `source-data-worker` -> `/source/raw/ingest-result` -> quality gate -> `source_build_trigger` -> source build -> `governance.source_lineage_v1`，不得由模型、调度、前端或研究服务直接并发调用 provider。

### 首次构建优先级

| 优先级 | 数据资产 | 表 | 构建方式 | 说明 |
|---|---|---|---|---|
| P0 | 交易日时间线 | `source.trade_calendar_v1` | BaoStock `query_trade_dates` 主源，Tushare `trade_cal` 备源 | scheduler materialize、T+N outcome、记忆年龄、启动守卫的最高优先级。 |
| P0 | 股票主数据和 provider symbol | `source.stock_master_v1`、`core.provider_symbol_map` | BaoStock `query_stock_basic` 主源，EastMoney universe 备源 | 所有服务共享身份锚点，禁止用前端名称或样例代码补齐。 |
| P0 | 每日可交易 universe | `source.stock_universe_daily_v1`、`source.trade_status_v1` | BaoStock `query_all_stock` 与日线 `tradestatus` | release gate、候选过滤、停牌/ST/退市风险硬阻断。 |
| P0 | 未复权日线 | `source.daily_bar_v1` | BaoStock raw 主源，Tencent/Sohu 字段级备源 | 所有模型共用行情事实和涨跌停计算基座。 |
| P0 | 前复权日线和复权因子 | `source.adjusted_daily_bar_v1`、`source.adjustment_factor_v1` | BaoStock qfq/adjust_factor 主源，Tencent/Tushare 备源 | 记忆模型和潜伏抬头图形必须依赖 adjusted OHLC。 |
| P0 | 涨跌停价格与事件 | `source.limit_price_v1`、`source.limit_event_v1` | 日线 source build + 上一交易日标准日线 close 锚点 + THS public limit_up_pool | 候选输入页、模型四 Day1 scan 和 Day2 接力观察共用；缺 pre-close 锚点时保持缺口。 |
| P0 | 同花顺付费次日概率 | `source.ths_paid_limit_up_probability_v1` | THS `paid_limit_up_probability`，仅允许受控 Cookie | 热点候选教师先验；无合法备源，Cookie 失效或取不到时先阻断，候选交易日的下一交易日 09:00 后仍缺失才放弃该批候选。 |
| P0 | raw/source/lineage 治理 | `governance.raw_fetch_*`、`governance.source_build_*`、`governance.source_lineage_v1` | source-data-service 内部写入 | 所有事实必须能反查 provider/API/raw 行。 |
| P1 | 个股资金流 | `source.stock_moneyflow_daily_v1` | EastMoney `moneyflow_stock_series` 主源，Tushare 备源 | 三模型资金确认字段，缺失降级但不补 0。 |
| P1 | 指数与市场环境 | `source.index_daily_bar_v1`、`source.market_regime_snapshot_v1` | Tencent index 主源，BaoStock 备源 | 市场环境与相对强弱，指数 volume/amount 仍为显式审计。 |
| P1 | 竞价、报价、分钟、逐笔 | `source.auction_snapshot_v1`、`source.realtime_quote_v1`、`source.minute_bar_v1`、`source.trade_tick_v1` | EastMoney/Tencent/Sina public adapters | 热点开盘窗口和模型四 Day2 观察使用；竞价 source 字段为 `virtual_open_price`、`matched_volume`、`matched_amount`、`event_time`，`snapshot_time` 由 source build 从 provider event time 写入物理行身份。 |
| P2 | 新闻、公告、题材上下文 | `source.event_news_v1`、`source.stock_board_membership_v1`、`source.board_daily_bar_v1` | Baidu/Jin10/THS/CNINFO/board adapters | research-only 或 degraded 证据，不能变成 P0 hard gate。 |

### 首次构建当前补齐状态

2026-06-17 定向修复后，`source-data-worker` 的 source build 支持 BaoStock `query_trade_dates -> source.trade_calendar_v1` 与 `query_stock_basic -> source.stock_master_v1`。2026-06-22 定向修复后，BaoStock `query_all_stock -> source.stock_universe_daily_v1` 增加 source build 映射：`code_name` 写入 `stock_name`，`tradeStatus` 原文写入 `trade_status`，并只用可解析的真实 `tradeStatus` 派生 `is_tradable`；不可解析时保留 warning/NULL，不得默认可交易，也不得写入物理表不存在的 `is_suspended` 或 `is_delisting_risk`。这些路径仍严格走 `/source/fetch/plan` -> `/source/fetch/submit` -> worker -> raw ingest -> `source_build_trigger` -> source build -> `governance.source_lineage_v1`，不允许直接写 source 表。

`source.stock_universe_daily_v1` 是全 A 股票 universe，不是 BaoStock `query_all_stock` 原始返回全集。source build 仅保留沪市 `60*`/`68*`、深市 `00*`/`30*`，以及 provider 返回时的北交所 `4*`/`8*`/`92*` `.BJ` 股票；沪市 `000*` 指数、深市 `399*` 指数、`510/511/512/513/515/516/517/518/520/526/530/551/560/561/562/563/588/589` 等基金类对象、深市 `159*` 基金、`200*`/`900*` B 股和其他非 A 股票对象不得写入该 source 表。正式 `build_scope=batch` 的 universe source build 成功后，必须按交易日清理该表已有非 A 旧行，避免历史污染继续被下游读取；`full_a_share` 展开读取时也必须再次用同一 A 股规则防御过滤。

当前运行证据：

```text
source_build_trigger_3e12e9c58a04442bb4f2 source.trade_calendar_v1 -> succeeded
  raw_row_count=365 source_row_count=365 lineage_row_count=1460
  source.trade_calendar_v1 min=2026-01-01 max=2026-12-31 days=365 trading_days=242
  sample 2026-06-12 is_trading_day=true pretrade_date=2026-06-11 primary_provider=baostock

source_build_trigger_59ac534c422848f99031 source.stock_master_v1 000063.SZ -> succeeded
source_build_trigger_6d2ee951963e4bdbae98 source.stock_master_v1 000759.SZ -> succeeded
  source.stock_master_v1 rows=2, lineage rows=16
  000063.SZ 中兴通讯 ipo_date=1997-11-18 list_status=1
  000759.SZ 中百集团 ipo_date=1997-05-19 list_status=1
```

真实限制：本次向 BaoStock 请求 `2026-01-01` 至 `2027-12-31`，provider 实际 raw 只返回到 `2026-12-31`。因此当前不可宣称 2027 日历已补齐；后续必须再次通过 fetch orchestration 补采，缺口保留为真实 provider 覆盖范围问题，不得用 mock、0、空字符串或人工推断补齐。

### 数据调度频率矩阵

| 频率 | 数据 | 范围口径 | source-data-service 接口 | Provider/API | 队列 | 产出 |
|---|---|---|---|---|---|---|
| 一次性/季度补齐 | 交易日历未来 12-24 个月、历史股票主数据、provider symbol map | 交易日历 `none`；股票主数据 `full_a_share` 市场批接口 | `/source/fetch/plan`、`/source/fetch/submit`、`/source/build/worker/run-once` | BaoStock `query_trade_dates`、`query_stock_basic` | `normal_daily_ingest_queue` 或 `backfill_queue` | `source.trade_calendar_v1`、`source.stock_master_v1` |
| 每日盘前 09:05-09:20 | 当日可交易 universe、交易状态、停牌/ST 风险、涨跌停价 | `source.stock_universe_daily_v1` 走 `full_a_share` 市场批接口；逐股表从当日 universe 展开 | `/source/fetch/plan`、`/source/fetch/submit` | BaoStock `query_all_stock`、日线状态备查 | `normal_daily_ingest_queue`；release 阻断修复走 `urgent_release_gate_queue` | `source.stock_universe_daily_v1`、`source.trade_status_v1`、`source.limit_price_v1` |
| 每日收盘 15:35-17:00 | 日线、前复权日线、复权因子、涨跌停事件 | 日频逐股表使用 `full_a_share`；`source.limit_event_v1` 使用市场批接口 | `/source/fetch/plan`、`/source/fetch/submit`、`/source/build/worker/run-once` | BaoStock raw/qfq/adjust_factor、Tencent/Sohu/THS | `normal_daily_ingest_queue` | `source.daily_bar_v1`、`source.adjusted_daily_bar_v1`、`source.limit_price_v1`、`source.limit_event_v1` |
| 每日 15:20/16:05/18:00/20:30 | 同花顺付费次日概率 | `none`；由候选批次决定股票集合 | `/source/ths/paid-probability/fetch-current-batch` | THS `paid_limit_up_probability` | `urgent_release_gate_queue` | `raw_ths.paid_limit_up_probability_v1`、`source.ths_paid_limit_up_probability_v1`、`governance.ths_paid_probability_batch_status_v1` |
| 每日 09:01 | 付费概率截止守卫 | `none` | `/source/ths/paid-probability/deadline-check` | 不直接调用 provider | `P0_urgent_release` 调度审计 | 仅当候选交易日的下一交易日 09:00 Asia/Shanghai 已过且仍未补齐概率时，标记 `abandoned_no_probability_before_deadline`。 |
| 每日 16:15-18:00 | 个股资金流、板块/题材上下文、新闻事件 | 个股资金流 `full_a_share`；新闻/事件 `none` | `/source/fetch/plan`、`/source/fetch/submit` | EastMoney moneyflow、THS context、Baidu/Jin10 news | `research_queue` 或 `normal_daily_ingest_queue` | `source.stock_moneyflow_daily_v1`、`source.event_news_v1` |
| 分钟级 09:15-09:25 | 集合竞价快照 | `configured_symbols`；不做全 A 常规分钟抓取 | `/source/fetch/plan`、`/source/fetch/submit` | EastMoney auction 主源，Tencent/Sina auction 备验 | `urgent_release_gate_queue` when release-gate critical | `source.auction_snapshot_v1`：`price/volume/amount` 仅作为 raw/provider 字段，source build 映射为 `virtual_open_price/matched_volume/matched_amount` 并写 lineage |
| 分钟级 09:30-15:00 | 实时报价、分钟线 | `configured_symbols`；仅服务 release/window 必要集合 | `/source/fetch/plan`、`/source/fetch/submit` | EastMoney/Tencent quote/minute | `urgent_release_gate_queue` for P0 release windows, otherwise normal | `source.realtime_quote_v1`、`source.minute_bar_v1` |
| 窗口级 15:12-15:45 | 模型四 Day1 T 字板候选事实补齐 | `stage_candidates`；候选由 scheduler 从 `source.limit_event_v1` 的 THS 公开涨停池/T 字板事件筛出 | `/source/fetch/plan`、`/source/fetch/submit` | BaoStock/EastMoney/Tencent/Tushare source adapters | `urgent_release_gate_queue` | `source.trade_status_v1`、`source.daily_bar_v1`、`source.limit_price_v1`、`source.realtime_quote_v1.float_market_cap` |
| 窗口级 10:20-10:40 | 模型四 Day2 接力观察 | `stage_candidates`；只接收 Day1 合格/阶段候选 | `/source/fetch/plan`、`/source/fetch/submit` | EastMoney quote/minute/trade_details | `urgent_release_gate_queue` | `source.realtime_quote_v1`、`source.minute_bar_v1`、`source.trade_tick_v1` |
| 巡检/修复触发 | 任意 P0/P1 缺口 | 按缺口对象显式传入或使用 `full_a_share` 展开 | `/source/gaps/diagnose`、`/source/gaps/repair-plan`、`/source/fetch/submit` | 按 `governance.source_table_requirement_v1` | `repair_queue` 或 `urgent_release_gate_queue` | raw/source/lineage 修复证据 |
| 生产拍板验收 | source readiness、probe matrix、质量矩阵 | 只读证据，不改变调度范围 | `/source/ops/production-readiness`、`/source/probe/matrix`、`/source/quality/multi-source/check` | 必需真实 probe 读取固化证据 | 不直接采 provider，除非验收脚本显式 real probe | acceptance evidence |

### Fetch Universe Scope 合同

`FetchPlanRequest.universe_scope` 控制 fetch plan 如何确定股票集合。默认 `explicit_symbols` 只使用请求里传入的 `symbols`；`full_a_share` 先读 `source.stock_universe_daily_v1` 的目标交易日可交易集合，若当日 universe 为空再退读 `source.stock_master_v1`，并过滤不可交易、停牌、ST/退市风险和已退市状态。若两个 source 表都没有可用股票，fetch plan 必须失败并提示先补 `source.stock_universe_daily_v1`，不得回退到 `000759.SZ`、`000063.SZ` 或任何样本标的。

`full_a_share` 的股票集合必须同时满足 A 股代码规则：`60*`/`68*`.SH、`00*`/`30*`.SZ、以及 provider 明确返回时的北交所 `4*`/`8*`/`92*`.BJ。即使旧 source 行标记 `is_tradable=true`，指数、基金、B 股和其他非 A 对象也不得进入逐股日频 fetch plan、模型三/模型四 Day1 全市场扫描或 release preflight。

`source.stock_universe_daily_v1`、`source.limit_event_v1`、`source.stock_master_v1` 是市场批接口资产，`full_a_share` 计划保持单个 market batch job，不展开成逐股 job。`source.daily_bar_v1`、`source.adjusted_daily_bar_v1`、`source.trade_status_v1`、`source.limit_price_v1`、`source.stock_moneyflow_daily_v1` 等逐股日频表按 `full_a_share` 展开。`stage_candidates` 只允许上游模型阶段传入明确 `symbols`，用于模型四 Day1 T 字板候选事实补齐和 Day2/Day3 收窄窗口；source-data-service 不生成候选、不推断候选，也不把配置样本当候选。模型四 Day1 候选来源由 scheduler 只读 `source.limit_event_v1` 的 THS 公开涨停池/T 字板事件决定。

若 `query_all_stock` 等市场批接口命中历史 duplicate `request_hash`，新 batch 的 `source_build_trigger` 必须使用当前 planned job 身份：`full_a_share` market batch 的 `symbol=NULL`、`build_scope=batch`，不得继承旧样本 job 的 `symbol_date` 身份。source build 执行时也以 trigger 的 `symbol/trade_date` 约束 raw rows，保证旧样本式 job 不会把全市场 raw 裁成单票。

`source_build_trigger` 与 source build worker 的去重边界只能限制在同一个 `fetch_batch_id` 内。源表语义、build mapping 或过滤规则迭代后，新的正式 catch-up batch 可以复用历史 raw job，但必须创建新的 build trigger 重新执行 source build 和 lineage/清理逻辑；build worker 判断已处理 trigger 时必须把 `fetch_batch_id` 纳入 key，不得因为旧 batch 下已有 queued/running/succeeded trigger 或成功 build result 就跳过当前 batch 的 raw-to-source 重建。

Active duplicate raw jobs obey the same batch-scoped trigger boundary: a later batch that reuses a still-running raw job must be recorded as an alias, and the completion path must emit a trigger under the later batch id. This is required for stage-candidate repairs where `source.trade_status_v1`, `source.daily_bar_v1` and `source.limit_price_v1` share the same BaoStock raw daily request hash.

### 同花顺付费概率 Cookie 合同

`ths.paid_limit_up_probability` 是同花顺付费接口的唯一登录态例外。其他 THS provider/API 仍必须保持公开无 Cookie、无账号 token、无动态 `hexin-v`。本接口的 `user`、`userid` Cookie 只能通过运行时 API 写入 `governance.ths_paid_probability_cookie_v1`，不得写入仓库、README、raw request params、日志、验收输出或前端响应；对外状态只返回脱敏值和 `credential_version`。

受控 API：

```text
GET  /source/ths/paid-probability/cookie/status
PUT  /source/ths/paid-probability/cookie
POST /source/ths/paid-probability/probe
POST /source/ths/paid-probability/fetch-current-batch
GET  /source/ths/paid-probability/batch-status?trade_date=YYYY-MM-DD
POST /source/ths/paid-probability/deadline-check
```

抓取链路：候选涨停事实先进入 `source.limit_event_v1`，本服务再按候选 `symbol + trade_date` 调用付费概率接口。provider 请求参数只允许包含 `date`、`stock_code`、`credential_version`，Cookie 只在 adapter 运行时注入 HTTP cookies。返回成功体写入 `raw_ths.paid_limit_up_probability_v1`，通过质量门禁后构建 `source.ths_paid_limit_up_probability_v1` 和 lineage。`source.ths_paid_limit_up_probability_v1.paid_limit_up_probability` 必须是 `[0,100]` 的 Decimal，缺失保持 NULL/缺口，不得用 0、手工值、随机值、旧 payload 或前端推断补齐。

批次状态写入 `governance.ths_paid_probability_batch_status_v1`。Cookie 缺失、失效、接口不可取或概率未入库时，候选批次在候选交易日的下一交易日 09:00 Asia/Shanghai 前只能是 `pending_cookie`、`cookie_expired`、`partial` 或 `fetching` 等阻断/等待状态；其中 `pending_probe` 与 `valid` 均表示数据库已有留存 Cookie，只有真实付费接口 probe 失败后才允许写成 `cookie_expired`。只有 `/source/ths/paid-probability/deadline-check` 在该时间点之后确认仍缺失时，才允许标记 `abandoned_no_probability_before_deadline` 并放弃这一批候选；若 Cookie 未发生真实失败，放弃原因只能写成概率仍缺失，不得伪装成 Cookie 已失效。该表无备源是设计要求，DS-7 backup provider 门禁只对本 source/API 组合放行，其他 P0/P1 source 字段仍必须有备源。

### 性能与索引基线

`infra/sql/0025_source_data_foundation_indexes_v1.sql` 新增首次上线读路径索引，并已同步到 `infra/sql/bootstrap_schema.sql`。索引覆盖交易日历、股票主数据、日 universe、日线、前复权日线、交易状态、涨跌停价格/事件、分钟/逐笔、资金流、事件新闻、lineage duplicate audit、source build trigger、canonical write audit 和 urgent release queue。`infra/sql/0028_ths_paid_probability_v1.sql` 新增同花顺付费概率 Cookie、raw、source 和批次状态表索引，覆盖 `symbol + trade_date`、`source_quality_status + available_at`、`credential_version`、`status + updated_at` 等读写路径。上述 SQL 不写入事实、不改变模型分数或 release gate。

数据资产账本见 `services/source-data-service/DATA_ASSETS.md`。后续若新增 source 表、raw 表、provider adapter、字段合同、索引、freshness SLA 或 storage policy，必须同步更新本 README 和该账本。

锁定目标：`source_data_service_ds7_production_readiness_candidate`

本服务是神策中心后续所有服务的数据源底座。三大模型、调度服务、后续数据巡检、特征服务、研究服务都必须依赖这里沉淀的 **provider 原接口表** 和 **source 标准事实表**。

## 1. 硬性架构原则

1. **一接口一原表**：每个 provider 的每个 API 单独落一张 `raw_<provider>.<api>_v1` 原表。
2. **模型不读 raw**：模型只能读取 `source.*` 标准事实表，不能直接读取 `raw_baostock.*`、`raw_akshare.*`、`raw_tushare.*`。
3. **source 由 raw 构建**：`source.*` 不是某一个 API 的直接别名，而是由多个接口原表通过字段映射、单位转换、主备源比对、质量标记、血缘记录后构建。
4. **缺口可反查接口**：数据巡检发现某个 `source` 字段缺失时，必须能通过 `governance.source_table_requirement_v1` 找到应该补采的 provider、api、raw_table 和请求参数。
5. **所有字段有 lineage**：source 表每个关键字段要能通过 `governance.source_lineage_v1` 追溯到 raw 表、raw_id、batch_id、provider、api_name。
6. **免费公开源优先**：优先 BaoStock、Tencent 公开 K 线、交易所/巨潮公开数据；AKShare 只在其底层公开接口完成最新真实 probe 后才能进入生产主备链路，无法满足再进入 Tushare/聚宽/Wind/Choice/iFinD 等付费或积分制接口。
7. **数据源服务不因单个 provider 掉线而掉线**：provider 失败必须通过超时、重试、熔断、备源和 research-only 降级处理，不能拖垮服务本身。
8. **数据源只存事实**：source/raw 层禁止出现模型语义字段，例如 `signal`、`score`、`buy_point`、`outcome`、`success`、`ambush_score`、`hot_score`。
9. **持久化队列恢复不依赖进程内上下文**：Postgres 队列是 fetch batch/job/callback 的事实源；worker 启动、租约前和 lease maintenance 都必须按 `job.fetch_batch_id` 从 Postgres 恢复 batch 回调上下文，并用 Postgres 中更新的 queued/retry 状态刷新 worker 进程内旧状态。若数据库中真的不存在 batch，job 必须进入 `dead_letter` 并记录 `fetch_batch_missing`，禁止因 `_BATCHES` 缺失导致 worker 重启循环或静默丢弃任务。
10. **duplicate backup 不允许同表失败循环**：相同 provider/API/request_hash 的 failed/cancelled/dead-letter backup job 只能在新 `source_table_name` 需要复用时重新排队；同一 `source_table_name` 重复提交必须保留终态失败和缺口事实，不得反复 requeue。`succeeded` 但缺 raw 审计 hash 的 unusable backup 仍允许重试。

## 2. 服务边界

本服务负责：

- provider API registry
- provider adapter
- raw interface ingestion
- source table requirement registry
- field mapping registry
- source build lineage
- gap repair plan
- provider probe / readiness report
- raw/source SQL migration

本服务不负责：

- 模型评分
- 模型信号发布
- 买点决策
- 交易建议
- 前端展示

## 3. 微服务结构

```text
services/source-data-service/
  pyproject.toml
  README.md
  src/source_data_service/
    acceptance_evidence.py
    api.py
    fetch_orchestrator.py
    fetch_persistence.py
    main.py
    models.py
    operational_governance.py
    postgres_repository.py
    settings.py
    provider_registry.py
    provider_runtime.py
    gap_detector.py
    probe.py
    production_readiness.py
    resilience.py
    source_build.py
    source_repository.py
    ths_paid_credentials.py
    ths_paid_probability.py
    worker_executor.py
    worker_loop.py
    adapters/
      base.py
      baostock_adapter.py
      akshare_adapter.py
      baidu_adapter.py
      eastmoney_adapter.py
      tencent_adapter.py
      tushare_adapter.py
  tests/
```

## 4. 核心 API

### 4.1 健康检查

```http
GET /health
```

返回服务状态。provider 掉线不应影响该接口。

### 4.2 查看已注册 provider API

```http
GET /source/apis
GET /source/apis/{provider}/{api_name}
```

用途：告诉数据巡检和调度服务，当前有哪些 provider API、请求参数、返回字段、对应 raw 表和目标 source 表。

### 4.3 查看 source 标准表字段需求

```http
GET /source/requirements
GET /source/requirements?source_table_name=source.adjusted_daily_bar_v1
```

用途：告诉巡检服务每个 source 字段的主源、备源、最低覆盖率、是否 P0、是否允许 online 使用。

### 4.4 原接口拉取

```http
POST /source/raw/fetch
```

请求示例：

```json
{
  "provider": "baostock",
  "api_name": "query_history_k_data_plus_daily_qfq",
  "params": {
    "code": "sz.000759",
    "fields": "date,code,open,high,low,close,preclose,volume,amount,adjustflag,turn,tradestatus,pctChg,isST",
    "start_date": "2026-05-25",
    "end_date": "2026-05-25",
    "frequency": "d",
    "adjustflag": "2"
  },
  "dry_run": true
}
```

说明：`dry_run=true` 不调用真实 provider，只校验请求结构。真实环境取消 `dry_run` 后才会访问 provider。

### 4.5 provider 实测探针

```http
POST /source/probe
GET  /source/probe/results
```

用途：真实拉取 provider API，检查 connectivity、schema、row_count、missing_fields、usable_for_source_table。
`dry_run=false` 的真实 probe 会写入 `governance.source_probe_result_v1`；`GET /source/probe/results` 用于查看最近固化的 provider 可用性证据。生产门禁在 `require_real_provider_probe=true` 时必须读取这张表里的最新真实 probe 记录，不能只依赖一次控制台输出。
`usable_for_model_online` 只在该 provider/API 对应的 source requirement 存在 `required_for_online=true` 合同时才允许为 true；research-only 源即使真实 probe、schema 和 row_count 都通过，也必须返回 `usable_for_model_online=false`、`usable_for_research_only=true`。Baidu Finance `finance_news_feed` 当前即按该口径处理，避免事件新闻研究源被误读为 official release hard gate。

请求示例：

```json
{
  "provider": "tencent",
  "api_name": "daily_bars",
  "sample_params": {
    "provider_code": "sz000063",
    "period": "day",
    "start_date": "2026-06-12",
    "end_date": "2026-06-12",
    "count": 10,
    "adjustment": "qfq"
  },
  "dry_run": true
}
```

### 4.6 数据缺口补采计划

```http
POST /source/gaps/repair-plan
```

请求示例：

```json
{
  "source_table_name": "source.adjusted_daily_bar_v1",
  "canonical_field_name": "adjusted_close",
  "symbol": "000759.SZ",
  "trade_date": "2026-05-25"
}
```

返回示例：

```json
{
  "source_table_name": "source.adjusted_daily_bar_v1",
  "canonical_field_name": "adjusted_close",
  "symbol": "000759.SZ",
  "trade_date": "2026-05-25",
  "primary_repair": {
    "provider": "baostock",
    "api_name": "query_history_k_data_plus_daily_qfq",
    "raw_table_name": "raw_baostock.query_history_k_data_plus_daily_qfq_v1",
    "params": {
      "code": "sz.000759",
      "start_date": "2026-05-25",
      "end_date": "2026-05-25",
      "frequency": "d",
      "adjustflag": "2"
    }
  },
  "backup_repairs": [
    {
      "provider": "tencent",
      "api_name": "daily_bars",
      "raw_table_name": "raw_tencent.daily_bars_v1",
      "params": {
        "provider_code": "sz000759",
        "period": "day",
        "start_date": "2026-05-25",
        "end_date": "2026-05-25",
        "count": 10,
        "adjustment": "qfq"
      }
    }
  ],
  "source_rebuild_required": true
}
```

### 4.7 source 表 readiness 评估

```http
POST /source/readiness/evaluate
```

请求示例：

```json
{
  "source_table_name": "source.daily_bar_v1"
}
```

用于判断某张 source 表是否具备进入正式模型链路的基础条件。

### 4.8 多源质量一致性校验

```http
POST /source/quality/multi-source/check
```

用途：对同一个 `source_table_name + symbol + trade_date + canonical_field` 事实，按字段合同和 `/source/gaps/repair-plan` 找到主源和备源，真实拉取 provider 原接口结果，先执行 raw 质量门禁，再映射成 canonical 字段并做同事实比对。该接口只用于质量审计、上线验收和 provider 准入判断，不允许绕过 `/source/raw/ingest-result`、`source_build_trigger`、quality gate、source build 和 lineage 直接把 provider 返回供模型使用。

请求示例：

```json
{
  "source_table_name": "source.daily_bar_v1",
  "canonical_fields": ["open_price", "high_price", "low_price", "close_price", "volume", "amount", "pct_chg"],
  "symbol": "000063.SZ",
  "trade_date": "2026-06-12",
  "include_backup": true,
  "dry_run": false
}
```

当前主备比对口径：

```text
source.daily_bar_v1:
  primary  = baostock.query_history_k_data_plus_daily_raw
  backup   = tencent.daily_bars(adjustment=raw) for OHLC/volume
  backup   = sohu.daily_bars for amount/pct_chg/turnover_rate

source.adjusted_daily_bar_v1:
  primary  = baostock.query_history_k_data_plus_daily_qfq
  backup   = tencent.daily_bars(adjustment=qfq) for adjusted OHLC/volume

source.index_daily_bar_v1:
  primary  = tencent.daily_bars(adjustment=raw)
  backup   = baostock.query_history_k_data_plus_daily_raw
  fields   = P0 close_price; P1 open_price/high_price/low_price/volume/amount/pct_chg
```

`source.index_daily_bar_v1` 的多源硬矩阵默认只比较 `open_price/high_price/low_price/close_price/pct_chg`。2026-06-13 真实 probe 显示 Tencent 与 BaoStock 的指数 `volume/amount` 存在 provider 定义差异：OHLC 与涨跌幅可通过严格同事实比对，但成交量、成交额会超过默认容忍度。因此 `volume/amount` 仍保留为 P1 source 合同字段和显式审计字段，缺失或差异必须保留 warning / blocked 证据，不进入默认 passed 矩阵；后续需完成指数成交口径归一后才能升为硬门禁字段。

比对规则：

```text
1. 只比较同一 symbol + trade_date 的目标行；provider 返回多行时必须先命中目标行。
2. provider 行必须先通过 /source/quality/validate-raw 的 OHLC、volume、amount 门禁。
3. canonical 字段缺失、目标行未命中或可用 provider 少于 2 个时，结果为 blocked。
4. 价格类字段默认绝对容忍度为 0.02；pct_chg 默认绝对容忍度为 0.05。
5. volume、amount 默认相对容忍度为 0.005；其他字段默认相对容忍度为 0.001。
6. Tencent daily_bars 的 volume 原接口按手口径返回，进入 canonical 比对前乘以 100，与 BaoStock 股数口径对齐。
7. Sohu daily_bars 的 volume 原接口按手口径返回，进入 canonical 比对前乘以 100；amount 原接口按万元返回，进入 canonical 前乘以 10000。
8. 超出容忍度返回 blocked，不用均值、0、空字符串、上一交易日或示例值掩盖差异。
```

返回重点字段：

```text
status: passed / warning / blocked
provider_evidence[].target_row_found
provider_evidence[].target_row_identity
provider_evidence[].canonical_values
comparisons[].absolute_diff
comparisons[].relative_diff
comparisons[].reason
blocking_reasons
warning_reasons
```

2026-06-15 本地代码真实 Sohu 探针：

```text
Sohu hisHq daily_bars / cn_000063 / 2026-06-12:
  row_count=1
  open/high/low/close=38.60/38.70/36.15/36.35
  volume=261471100
  amount=9702653800
  pct_chg=-3.86
  turnover_rate=6.49
```

2026-06-13/2026-06-15 本地 Docker 与本地 adapter 真实多源验收：

```text
source.daily_bar_v1 / 000063.SZ / 2026-06-12:
  BaoStock query_history_k_data_plus_daily_raw vs Tencent daily_bars(adjustment=raw) vs Sohu daily_bars
  field-level status=passed after Sohu backup is deployed
  open/high/low/close 完全一致：38.6 / 38.7 / 36.15 / 36.35
  volume: 261471118 vs 261471100，差异 18，relative_diff≈0.0000000688
  amount: BaoStock 9702654429.79 vs Sohu 9702653800，relative_diff≈0.0000000649
  pct_chg: BaoStock -3.8614 vs Sohu -3.86，absolute_diff=0.0014

source.adjusted_daily_bar_v1 / 000063.SZ / 2026-06-12:
  BaoStock query_history_k_data_plus_daily_qfq vs Tencent daily_bars(adjustment=qfq)
  status=passed, usable_provider_count=2, passed_field_count=6, blocked_field_count=0
  adjusted_open/high/low/close 完全一致：38.6 / 38.7 / 36.15 / 36.35
  volume: 261471118 vs 261471100，差异 18，relative_diff≈0.0000000688
  amount: 9702654429.79 vs 9702654430，差异 0.21
```

批量矩阵验收入口：

```bash
python scripts/source_data_quality_matrix.py --base-url http://127.0.0.1:8041 --symbol 000063.SZ --trade-date 2026-06-12
```

`source_data_quality_matrix.py` 只通过 HTTP 调用本接口，不导入 provider adapter，不直接并发访问 BaoStock、AKShare、Tencent、Sohu、Tushare、EastMoney 或 CNINFO，也不重启容器。默认矩阵覆盖 `source.daily_bar_v1` 与 `source.adjusted_daily_bar_v1` 两张 P0 行情表；可通过 `--symbol`、`--trade-date` 和 `--table daily|adjusted|index|source.daily_bar_v1|source.adjusted_daily_bar_v1|source.index_daily_bar_v1` 扩展多标的、多日期和多表。`daily` 默认比较 `open_price/high_price/low_price/close_price/volume/amount/pct_chg`，其中 Tencent 提供 OHLC/volume 备验，Sohu 提供 `amount/pct_chg` 备验。`adjusted` 默认比较 adjusted OHLC/volume。`index`/`source.index_daily_bar_v1` 会对 Tencent raw 指数 K 线和 BaoStock 指数 K 线做同事实比对，默认字段为 `open_price/high_price/low_price/close_price/pct_chg`；指数 `volume/amount` 仅在显式调用 `/source/quality/multi-source/check` 并传入字段时参与审计。脚本返回 `0` 代表矩阵全部 passed；任一同事实比对 blocked，或 warning 且未显式 `--allow-warning`，返回非 0。该脚本只用于质量审计和准入验收，不能替代 `/source/raw/ingest-result`、`source_build_trigger`、quality gate、source build、lineage 与 `/source/release/preflight` 正规生产链路。

2026-06-15 当前质量矩阵口径：

```text
source.daily_bar_v1:
  BaoStock raw primary
  Tencent raw backup for open/high/low/close/volume
  Sohu raw backup for amount/pct_chg/turnover_rate
  default fields=open_price,high_price,low_price,close_price,volume,amount,pct_chg

source.adjusted_daily_bar_v1:
  BaoStock qfq primary
  Tencent qfq backup for adjusted_open/adjusted_high/adjusted_low/adjusted_close/volume
  default fields=adjusted_open,adjusted_high,adjusted_low,adjusted_close,volume

source.index_daily_bar_v1:
  Tencent raw primary
  BaoStock index-safe raw backup
  default fields=open_price,high_price,low_price,close_price,pct_chg
  index volume/amount remains explicit audit only because provider definitions diverge.
```

## 5. 第一批 provider API 与原表

### 5.1 BaoStock 免费源

| API | 原表 | 请求参数 | 返回字段 | 目标 source |
|---|---|---|---|---|
| `bs.query_all_stock` | `raw_baostock.query_all_stock_v1` | `day` | `code`, `tradeStatus`, `code_name` | `source.stock_universe_daily_v1`, `source.trade_status_v1` |
| `bs.query_stock_basic` | `raw_baostock.query_stock_basic_v1` | `code` | `code`, `code_name`, `ipoDate`, `outDate`, `type`, `status` | `source.stock_master_v1` |
| `bs.query_trade_dates` | `raw_baostock.query_trade_dates_v1` | `start_date`, `end_date` | `calendar_date`, `is_trading_day` | `source.trade_calendar_v1` |
| `bs.query_history_k_data_plus` raw | `raw_baostock.query_history_k_data_plus_daily_raw_v1` | `code`, `fields`, `start_date`, `end_date`, `frequency=d`, `adjustflag=3` | `date`, `code`, `open`, `high`, `low`, `close`, `preclose`, `volume`, `amount`, `adjustflag`, `turn`, `tradestatus`, `pctChg`, `isST` | `source.daily_bar_v1`, `source.trade_status_v1` |
| `bs.query_history_k_data_plus` qfq | `raw_baostock.query_history_k_data_plus_daily_qfq_v1` | `code`, `fields`, `start_date`, `end_date`, `frequency=d`, `adjustflag=2` | 同上 | `source.adjusted_daily_bar_v1` |
| `bs.query_adjust_factor` | `raw_baostock.query_adjust_factor_v1` | `code`, `start_date`, `end_date` | `code`, `dividOperateDate`, `foreAdjustFactor`, `backAdjustFactor`, `adjustFactor` | `source.adjustment_factor_v1` |
| `bs.query_stock_industry` | `raw_baostock.query_stock_industry_v1` | `date` | `updateDate`, `code`, `code_name`, `industry`, `industryClassification` | `source.stock_board_membership_v1` |

运行约束：BaoStock Python 客户端内部使用全局登录态和 socket 连接，不能并发登录、查询、登出。`BaoStockAdapter` 对真实 provider 请求采用进程内互斥锁串行执行；`dry_run=true` 不进入锁。若在同一容器内并行触发 raw、qfq、probe，可能出现 `[Errno 9] Bad file descriptor`、空结果或 provider 超时，必须按 provider 运行事实返回 warning / blocked，不得补 0、空字符串或示例值。`query_all_stock` 的 source build 只负责 `source.stock_universe_daily_v1.stock_name/trade_status/is_tradable/is_st` 当前物理列；`tradeStatus` 无法解析时不得把 `is_tradable` 写成 true。

### 5.2 AKShare 免费源

AKShare 仍可登记为公开包装库和研究补充源，但 `stock_zh_a_hist_daily_raw`、`stock_zh_a_hist_daily_qfq`、`index_zh_a_hist` 与 `stock_zh_a_spot_em` 当前不再承担 P0 online 主源、备源或生产拍板硬门禁。2026-06-13 本地 Docker 真实 probe 显示这些接口依赖的 EastMoney 公开路径会出现远端断开；因此日 K / qfq / 指数日 K / spot 快照只保留为历史 raw 合同、当前快照补充和人工研究探针，进入评分、闸门或发布链路前必须重新取得最新可用真实 probe。

2026-06-13 不可用接口实测与处理：

| provider/API | 真实 probe 结果 | 当前处理 | 替代/后续 |
|---|---|---|---|
| `akshare.stock_zh_a_hist_daily_raw` | `connectivity_pass=false`, `row_count=0`, `RemoteDisconnected` | 弃用为生产日 K 主备源；保留历史 raw 合同与人工研究探针 | P0 未复权日 K 使用 BaoStock `query_history_k_data_plus_daily_raw` 主源，Tencent `daily_bars(adjustment=raw)` 备源 |
| `akshare.stock_zh_a_hist_daily_qfq` | `connectivity_pass=false`, `row_count=0`, `RemoteDisconnected` | 弃用为生产 qfq 主备源 | P0 qfq 使用 BaoStock `query_history_k_data_plus_daily_qfq` 主源，Tencent `daily_bars(adjustment=qfq)` 备源 |
| `akshare.index_zh_a_hist` | `connectivity_pass=false`, `row_count=0`, `RemoteDisconnected` | 弃用为生产指数日 K 主备源 | P0 指数日 K 使用 Tencent `daily_bars` 主源；后续可评估 BaoStock/Tushare 指数补充 |
| `akshare.stock_zh_a_spot_em` | `connectivity_pass=false`, `row_count=0`, `RemoteDisconnected` | 不再作为 universe/spot 生产硬门禁 | universe 使用 BaoStock `query_all_stock` 主源和 BaoStock 日线 `tradestatus/isST` 备路 |
| `akshare.stock_board_industry_name_em` / `stock_board_industry_cons_em` / `stock_board_industry_hist_em` | 远端断开，`row_count=0` | P1/research-only，不阻断三模型 release gate | 板块名称/成分优先降级到 BaoStock `query_stock_industry`；板块日 K 走内部按成分聚合路线，未完成时保留缺口码 |
| `akshare.stock_fund_flow_individual_realtime` | `connectivity_pass=true`, `row_count=5194`, 但缺 `大单流入`，`schema_pass=false` | research-only，不进入 hard gate；不得用 0 或空字符串补字段 | AKShare 资金流不得直接写入 `source.stock_moneyflow_daily_v1`；如后续使用，必须先修订字段合同并完成 raw/source/lineage 验证 |
| `eastmoney.moneyflow_stock_series` | adapter 已在运行容器启用，契约字段为 `main_net_inflow`、大小单净流入和 `provider_definition` | `source.stock_moneyflow_daily_v1.main_net_inflow` 的 P1 degradable 主源，不是 P0 hard gate | 已完成真实 probe、fetch orchestration、raw/source/lineage 写入和 scheduler preflight 验证 |
| `eastmoney.stock_universe` / `quote_snapshot` / `auction_snapshot` / `daily_bars` / `minute_bars` / `trade_details` / `moneyflow_*` / `theme_memberships` / `stock_board_profile` / `billboard_trades` / `northbound_summary` / `lpr_rates` | direct adapter 已接入 source-data-service；2026-06-15 本机真实外部 probe 均返回真实行 | 按字段合同分别作为 P0/P1/research/context 主备源；进入模型前必须经过 raw/source/lineage | 日 K/分钟/quote/资金/板块/龙虎榜/北向/LPR/股票主数据按当前 registry 和 README 合同使用，不再按旧 pending 口径处理 |

上述失败是 provider 外部可用性或当前 adapter 生产接入状态问题，不是 source build、Postgres、模型服务或调度服务的逻辑阻断。所有进入评分、闸门、标签、买点或发布链路的替代源仍必须走 `/source/fetch/plan` -> `/source/fetch/submit` -> worker -> raw -> quality -> source -> lineage -> preflight。

| API | 原表 | 请求参数 | 返回字段 | 目标 source |
|---|---|---|---|---|
| `ak.stock_zh_a_spot_em` | `raw_akshare.stock_zh_a_spot_em_v1` | 无 | `代码`, `名称`, `最新价`, `涨跌幅`, `成交量`, `成交额`, `最高`, `最低`, `今开`, `昨收`, `量比`, `换手率` | research-only current snapshot; not a production probe gate while EastMoney path fails |
| `ak.stock_zh_a_hist` raw | `raw_akshare.stock_zh_a_hist_daily_raw_v1` | `symbol`, `period=daily`, `start_date`, `end_date`, `adjust=""` | `日期`, `开盘`, `收盘`, `最高`, `最低`, `成交量`, `成交额`, `振幅`, `涨跌幅`, `涨跌额`, `换手率` | `source.daily_bar_v1` |
| `ak.stock_zh_a_hist` qfq | `raw_akshare.stock_zh_a_hist_daily_qfq_v1` | `symbol`, `period=daily`, `start_date`, `end_date`, `adjust=qfq` | 同上 | `source.adjusted_daily_bar_v1` |
| `ak.stock_board_industry_name_em` | `raw_akshare.stock_board_industry_name_em_v1` | 无 | `板块名称`, `板块代码`, `最新价`, `涨跌幅`, `总市值`, `换手率`, `上涨家数`, `下跌家数` | `source.board_master_v1` |
| `ak.stock_board_industry_cons_em` | `raw_akshare.stock_board_industry_cons_em_v1` | `symbol=板块名称` | `代码`, `名称`, `最新价`, `涨跌幅`, `成交量`, `成交额`, `换手率` | `source.stock_board_membership_v1` |
| `ak.stock_board_industry_hist_em` | `raw_akshare.stock_board_industry_hist_em_v1` | `symbol`, `adjust` | `日期`, `开盘`, `收盘`, `最高`, `最低`, `涨跌幅`, `成交量`, `成交额`, `换手率` | `source.board_daily_bar_v1` |
| `ak.stock_fund_flow_individual` | `raw_akshare.stock_fund_flow_individual_realtime_v1` | `symbol=即时` | `股票代码`, `股票简称`, `流入资金`, `流出资金`, `净额`, `成交额`, `大单流入` | research-only current snapshot; schema mismatch, not a `source.stock_moneyflow_daily_v1` producer until contract revision |
| `ak.index_zh_a_hist` | `raw_akshare.index_zh_a_hist_v1` | `symbol`, `period`, `start_date`, `end_date` | `日期`, `开盘`, `收盘`, `最高`, `最低`, `成交量`, `成交额`, `涨跌幅` | `source.index_daily_bar_v1` |
| `ak.stock_zh_a_disclosure_report_cninfo` | `raw_akshare.stock_zh_a_disclosure_report_cninfo_v1` | `symbol`, `market`, `start_date`, `end_date` | `代码`, `简称`, `公告标题`, `公告时间`, `公告类型`, `公告链接` | `source.event_news_v1` |

### 5.3 Tencent 公开 K 线替代源

Tencent `fqkline/kline` 公共接口作为 AKShare/EastMoney 日 K 类不可用时的生产替代源，当前 adapter 为 `TencentAdapter.fetch_daily_bars`，raw 表为 `raw_tencent.daily_bars_v1`。已真实外部 probe：

```text
sz000063 qfq day 2026-06-12 -> ["2026-06-12","38.600","36.350","38.700","36.150","2614711.000"]
sz000063 raw day 2026-06-12 -> ["2026-06-12","38.600","36.350","38.700","36.150","2614711.000"]
sz399006 index day 2026-06-12 -> ["2026-06-12","3921.090","3830.350","3921.530","3822.420","230246100.000"]
```

| API | 原表 | 请求参数 | 返回字段 | 目标 source |
|---|---|---|---|---|
| `TencentAdapter.fetch_daily_bars` raw | `raw_tencent.daily_bars_v1` | `provider_code=sz000063`, `period=day`, `start_date=YYYY-MM-DD`, `end_date=YYYY-MM-DD`, `count=10`, `adjustment=raw` | `date`, `code`, `provider_code`, `symbol`, `open`, `close`, `high`, `low`, `volume`, `amount=NULL`, `adjustment_mode`, `period`, `pct_chg=NULL` | `source.daily_bar_v1` |
| `TencentAdapter.fetch_daily_bars` qfq | `raw_tencent.daily_bars_v1` | `provider_code=sz000063`, `period=day`, `start_date=YYYY-MM-DD`, `end_date=YYYY-MM-DD`, `count=10`, `adjustment=qfq` | 同上 | `source.adjusted_daily_bar_v1` |
| `TencentAdapter.fetch_daily_bars` index | `raw_tencent.daily_bars_v1` | `provider_code=sz399006`, `period=day`, `start_date=YYYY-MM-DD`, `end_date=YYYY-MM-DD`, `count=10`, `adjustment=raw` | 同上 | `source.index_daily_bar_v1` |

字段口径：`provider_code` 使用 `sz000063` / `sh600000` / `sz399006`；canonical `symbol` 写成 `000063.SZ` / `600000.SH`；Tencent 历史 K 线当前只承担 OHLC/volume 备验，`amount` 与 `pct_chg` 保留 `NULL`，不得从实时 `qt` 快照推断目标历史日行；qfq 只用于 adjusted source，不得用于 raw limit/tradability 口径。

### 5.4 Sohu 个股日线 amount/pct_chg 备源

Sohu `hisHq` 公共接口作为个股未复权日线 `amount/pct_chg/turnover_rate` 的生产备源，当前 adapter 为 `SohuAdapter.fetch_daily_bars`，raw 表为 `raw_sohu.daily_bars_v1`。该源不替代 BaoStock 主源；它只在 Tencent 历史 K 线缺少可比 `amount/pct_chg` 时提供字段级备验和补采。

| API | 原表 | 请求参数 | 返回字段 | 目标 source |
|---|---|---|---|---|
| `SohuAdapter.fetch_daily_bars` raw | `raw_sohu.daily_bars_v1` | `provider_code=cn_000063`, `start_date=YYYYMMDD`, `end_date=YYYYMMDD`, `period=d` | `date`, `code`, `provider_code`, `symbol`, `open`, `close`, `change`, `pct_chg`, `low`, `high`, `volume`, `amount`, `turnover_rate`, `adjustment_mode`, `period`, `provider_definition` | `source.daily_bar_v1.amount`, `source.daily_bar_v1.pct_chg`, `source.daily_bar_v1.turnover_rate` |

字段口径：`provider_code` 使用 `cn_000063`；canonical `symbol` 写成 `000063.SZ` / `600000.SH`；Sohu `volume` 原始口径为手，adapter 转为股；Sohu `amount` 原始口径为万元，adapter 转为元；`pct_chg` 去掉百分号后保留数值文本。真实数据缺失时保留 `NULL`、gap 或 blocked，不得用 Tencent `qt`、0、空字符串、mock 或上一交易日值补齐。

### 5.5 EastMoney P1 资金流源

### 5.5.1 旧公开源扩充 v1（2026-06-15）

本轮根据旧项目 `market-data-service`、`news-service`、`candidate-service` 和 `packages/common/eastmoney_instrument_universe.py` 的数据源清单重新设计到新 `source-data-service`，旧代码只作为意图参考，不保留旧字段、旧 route、旧 loader 或旧服务写库逻辑。当前已接入的新代码事实如下：

| Provider/API | raw 表 | 目标 source | 当前用途 |
|---|---|---|---|
| `eastmoney.stock_universe` | `raw_eastmoney.stock_universe_v1` | `source.stock_master_v1` | EastMoney clist A 股分段主数据备验；只补 `stock_name/ipo_date/list_status/exchange/board`，不提供停牌、退市或可交易事实 |
| `eastmoney.quote_snapshot` | `raw_eastmoney.quote_snapshot_v1` | `source.realtime_quote_v1` | 模型四 Day2 近涨停 watch 的 P0 quote 主源 |
| `eastmoney.auction_snapshot` | `raw_eastmoney.auction_snapshot_v1` | `source.auction_snapshot_v1` | 集合竞价/盘口上下文证据；raw `price/volume/amount/event_time` 映射为 source `virtual_open_price/matched_volume/matched_amount/snapshot_time/event_time`，缺失保持 NULL/gap |
| `eastmoney.daily_bars` | `raw_eastmoney.daily_bars_v1` | `source.daily_bar_v1`, `source.adjusted_daily_bar_v1` | 公开 K 线研究/备验源；P0 日 K 仍以 BaoStock/Tencent/Sohu 合同为准 |
| `eastmoney.minute_bars` | `raw_eastmoney.minute_bars_v1` | `source.minute_bar_v1` | 模型四 10:30 与开板监控分钟 OHLC 主源 |
| `eastmoney.trade_details` | `raw_eastmoney.trade_details_v1` | `source.trade_tick_v1` | 逐笔/成交明细研究证据 |
| `eastmoney.moneyflow_stock_series` / `moneyflow_stock_rank` / `moneyflow_board_rank` | `raw_eastmoney.*` | `source.stock_moneyflow_daily_v1`, `source.stock_moneyflow_snapshot_v1`, `source.board_moneyflow_snapshot_v1` | 个股/截面/板块资金流 P1 或上下文证据 |
| `eastmoney.theme_memberships` / `stock_board_profile` | `raw_eastmoney.*` | `source.stock_board_membership_v1` | 行业/概念归属备验 |
| `eastmoney.billboard_trades` | `raw_eastmoney.billboard_trades_v1` | `source.billboard_trade_v1` | 龙虎榜/席位上下文证据 |
| `eastmoney.northbound_summary` | `raw_eastmoney.northbound_summary_v1` | `source.cross_market_context_v1` | 北向资金上下文；默认使用当前仍返回行的 `RPT_MUTUAL_DEAL_HISTORY` |
| `eastmoney.lpr_rates` | `raw_eastmoney.lpr_rates_v1` | `source.cross_market_context_v1` | LPR 利率宏观上下文 |
| `tencent.quote_snapshot` | `raw_tencent.quote_snapshot_v1` | `source.realtime_quote_v1` | EastMoney quote 的公开 fallback |
| `tencent.minute_bars` | `raw_tencent.minute_bars_v1` | `source.minute_bar_v1` | 使用 `appstock/app/kline/mkline` 的 m1 OHLC fallback；`provider_native_amount` 只做审计，`amount` 保持 `NULL` 直到单位归一 |
| `tencent.auction_snapshot` / `sina.auction_snapshot` | `raw_tencent.auction_snapshot_v1`, `raw_sina.auction_snapshot_v1` | `source.auction_snapshot_v1` | EastMoney auction 的公开备验；只通过 raw/source/lineage 补齐同一组 source canonical 字段，不把 provider 原始 `price/volume/amount` 暴露给下游 |
| `sohu.daily_bars` | `raw_sohu.daily_bars_v1` | `source.daily_bar_v1` | 个股日 K `amount/pct_chg/turnover_rate` 字段级备源 |
| `ths.limit_up_pool` / `zhangting5_reasons` / context APIs | `raw_ths.*` | `source.limit_event_v1`, `source.limit_reason_context_v1`, context source | 涨停池、涨停原因和同花顺公开上下文 |
| `baidu.finance_news_feed` / `jin10.public_flash` | `raw_baidu.finance_news_feed_v1`, `raw_jin10.public_flash_v1` | `source.event_news_v1` | research-only 事件新闻上下文 |
| `coingecko.simple_price/global_market` / `yahoo.chart` | `raw_coingecko.*`, `raw_yahoo.chart_v1` | `source.cross_market_context_v1` | 跨市场风险上下文 |

2026-06-15 本机真实外部 smoke probe（不重启 Docker）结果：

```text
PASS_ROWS eastmoney.stock_universe rows=3
PASS_ROWS eastmoney.quote_snapshot rows=1
PASS_ROWS eastmoney.auction_snapshot rows=1
PASS_ROWS eastmoney.daily_bars rows=1
PASS_ROWS eastmoney.minute_bars rows=241
PASS_ROWS eastmoney.trade_details rows=4187
PASS_ROWS eastmoney.moneyflow_stock_series rows=1
PASS_ROWS eastmoney.moneyflow_stock_rank rows=3
PASS_ROWS eastmoney.moneyflow_board_rank rows=3
PASS_ROWS eastmoney.theme_memberships rows=3
PASS_ROWS eastmoney.stock_board_profile rows=1
PASS_ROWS eastmoney.billboard_trades rows=3
PASS_ROWS eastmoney.northbound_summary rows=3
PASS_ROWS eastmoney.lpr_rates rows=6
PASS_ROWS tencent.daily_bars rows=1
PASS_ROWS tencent.quote_snapshot rows=1
PASS_ROWS tencent.minute_bars rows=3
PASS_ROWS tencent.auction_snapshot rows=1
PASS_ROWS sina.auction_snapshot rows=1
PASS_ROWS sohu.daily_bars rows=1
PASS_ROWS ths.limit_up_pool rows=144
PASS_ROWS ths.zhangting5_reasons rows=10
PASS_ROWS baidu.finance_news_feed rows=5
PASS_ROWS jin10.public_flash rows=20
PASS_ROWS coingecko.simple_price rows=2
PASS_ROWS yahoo.chart rows=2
```

同日附加环境检查：本机 Anaconda 进程未安装 `baostock/akshare`，因此直接脚本 probe 返回 import error；运行中的 `ai-stock-source-data-service` 容器内已确认安装 `baostock 00.9.20`、`akshare 1.18.64`，`/healthz` 与 `/readyz` 正常。通过容器当前 API 抽测 AKShare `stock_board_industry_name_em` 仍遇到 EastMoney 远端 `RemoteDisconnected`，继续维持 AKShare 包装源不作为生产 P0 主备 gate 的既有口径。BaoStock HTTP 直接 fetch 在本次 120 秒客户端窗口未返回；因服务健康和 provider status 未受影响，该问题作为运行探针窗口/长连接风险记录，不改变本轮旧公开 Web 源扩充结论。

2026-06-15 本地 Docker 追加 raw/source/lineage 闭环验证：

```text
fetch orchestration:
  POST /source/fetch/submit source.minute_bar_v1 000063.SZ 2026-06-15
  fetch_batch_id=fetch_batch_9898ff55e5d042c5aac7
  job_item_id=fetch_job_28138e084ce14e5fb7e1
  provider=eastmoney api_name=minute_bars queue=provider_probe_queue
  source-data-worker-1 自动消费，attempt_count=1，last_error_code=NULL
  source_build_trigger_e659292488a84ba796e2 -> status=succeeded

raw_eastmoney.minute_bars_v1:
  symbol=000063.SZ trade_date=2026-06-15 row_count=241
  bar_time range=2026-06-15 09:30:00+08:00 ~ 2026-06-15 15:00:00+08:00
  request_hash / response_schema_hash / response_row_hash 均 241/241 非空
  first rows:
    09:30 open/high/low/close=36.51/36.51/36.51/36.51 volume=13686
    09:31 open/high/low/close=36.51/36.68/36.40/36.40 volume=53739

source.minute_bar_v1:
  row_count=241, provider=eastmoney, quality_status=usable
  close_price range=35.730000 ~ 37.470000
  source_build_execution_result raw_row_count=241 source_row_count=241 lineage_row_count=1446 errors=[] warnings=[]

governance.source_lineage_v1:
  source_table_name=source.minute_bar_v1
  canonical fields bar_time/open_price/high_price/low_price/close_price/event_time each 241 rows
  lineage raw_table=raw_eastmoney.minute_bars_v1 raw_id starts at 1206
  build_batch_id=source_build_0f5faeda2465

queue/worker:
  /source/fetch/queues/summary provider_probe_queue queued=0 leased=0 succeeded=4 failed=0 dead_letter=0
  governance.raw_fetch_worker_heartbeat_v1 latest source-data-worker-1 status=alive note=worker_cycle_complete
```

同轮观察：`000063.SZ / 2026-06-12` 的 EastMoney `minute_bars` provider_probe job 可完成但未产生 raw 行；首个 source build trigger 因 `no raw rows found` 失败，验收重复产生的 trigger 已由 build worker 处理为 `skipped_no_raw` 并保留 warning。这是该公开分钟接口对历史日期覆盖的真实缺口，不得用 0、mock 或推断补齐。当前模型四已验证样本 `000759.SZ / 2026-06-12` 仍保留既有 raw/source/lineage 成功证据；当日实时/近端分钟链路以 `000063.SZ / 2026-06-15` 作为本轮追加成功样本。

EastMoney `fflow/kline/get` 公共路径当前只实现 `moneyflow_stock_series`，用于 `source.stock_moneyflow_daily_v1.main_net_inflow` 和 `provider_definition` 的 P1 degradable 资金流确认。该字段服务于 hot/candidate-memory/ambush 的资金确认和 L3/L4 证据质量，不属于 P0 online hard gate；缺失时必须返回 degraded、gap 或 warning，不得用 AKShare schema-mismatch 字段、0、空字符串或推断值补齐。

| API | 原表 | 请求参数 | 返回字段 | 目标 source |
|---|---|---|---|---|
| `EastMoneyAdapter.fetch moneyflow_stock_series` | `raw_eastmoney.moneyflow_stock_series_v1` | `secid=0.000759`, `start_date=YYYY-MM-DD`, `end_date=YYYY-MM-DD`, `lmt=120` | `date`, `symbol`, `secid`, `main_net_inflow`, `super_large_net_inflow`, `large_net_inflow`, `medium_net_inflow`, `small_net_inflow`, `provider_definition` | `source.stock_moneyflow_daily_v1.main_net_inflow`, `provider_definition` |

字段口径：`secid` 使用 EastMoney `0.000759` / `1.600000`，进入 source 后统一成 `000759.SZ` / `600000.SH`；canonical 字段名固定为 `main_net_inflow`。Tushare `moneyflow.net_mf_amount` 只作为备源 raw 字段映射到 canonical `main_net_inflow`，不能把 `net_mf_amount` 作为 source 字段暴露给模型或 preflight。当前代码路径已具备 adapter、repair plan、source build、Postgres payload/key、lineage 和单元测试；2026-06-14 本地时间已在 Docker 中定向重建并只重启 `source-data-service` / `source-data-worker`，未执行 `docker compose down`、未清库、未重建 Postgres。

2026-06-14 本地 Docker 真实验证：

```text
POST /source/probe eastmoney.moneyflow_stock_series
  sample_params={secid=0.000063,start_date=2026-06-12,end_date=2026-06-12,lmt=120}
  connectivity_pass=true, schema_pass=true, row_count=1
  usable_for_source_table=true, usable_for_model_online=true

/source/rows?source_table_name=source.stock_moneyflow_daily_v1&symbol=000063.SZ&trade_date=2026-06-12
  source_pk=000063.SZ|2026-06-12
  primary_provider=eastmoney
  source_quality_status=usable
  main_net_inflow=-1965310992
  provider_definition=eastmoney_fflow_kline_get:f51=date,f52=main,f53=super_large,f54=large,f55=medium,f56=small
  build_batch_id=source_build_c0a7122c3530

/source/lineage/records?source_table_name=source.stock_moneyflow_daily_v1&source_pk=000063.SZ|2026-06-12
  main_net_inflow -> raw_eastmoney.moneyflow_stock_series_v1 raw_id=2
  provider_definition -> raw_eastmoney.moneyflow_stock_series_v1 raw_id=2
  request_hash=157c699fa440cc03375bc0498904020da346e5d530e331ea61d17cada64f536f
```

### 5.6 Baidu Finance 公开事件新闻源

Baidu Finance `selfselect/news` 公共接口当前作为 `source.event_news_v1` 的 research-only 主源，用于 hot/candidate-memory/ambush 的新闻、事件和 ex-ante 证据上下文增强。该源只提供事实证据和审计上下文，不提供模型分数、信号、标签、买点或发布闸门结论；缺失时保留 `source_gap:news_event_context`、`source_gap:event_missing_available_at` 或 research-only 空态，不得用 GPT、mock、0 或空字符串补齐。

| API | 原表 | 请求参数 | 返回字段 | 目标 source |
|---|---|---|---|---|
| `BaiduAdapter.fetch finance_news_feed` | `raw_baidu.finance_news_feed_v1` | `rn=20`, `pn=0`, `type=all`, `tag=all` | `provider_news_id`, `title`, `source_name`, `published_at`, `available_at`, `event_type`, `url`, `symbol`, `tags_json`, `stock_refs_json` | `source.event_news_v1.title`, `published_at`, `available_at`, `event_type`, `url` |

字段口径：`provider_news_id` 进入 source 时写成 `event_id=baidu:{provider_news_id}`；`symbol` 来自 Baidu `st_tags_arr` 中可识别的 6 位 A 股代码，无法识别时保留 `NULL`；`published_at` 来自 provider 发布时间，`available_at` 是本系统抓取可见时间；`event_type` 当前固定为 `finance_news`。`raw_baidu.finance_news_feed_v1` 只作为原接口层，模型和 scheduler 只能读取经过 source build、quality、lineage 和 available_at 校验后的 `source.event_news_v1`。
raw 审计列必须包含 `request_params_json`、`request_hash`、`response_schema_hash`、`response_row_hash`、`raw_row_json`。`request_hash` 是 provider/API/params 的稳定哈希，和 fetch orchestration 的 job `request_hash` 不是同一个语义；前者追踪 provider 原请求，后者追踪队列任务去重。

当前代码路径已具备 provider enum、adapter、API registry、repair plan、raw SQL、source build 映射、Postgres `event_id` 物理键适配、lineage 和单元测试。Baidu 事件源仍为 `research_only`，不属于 P0 online hard gate，也不会增加 `/source/ops/production-readiness?require_real_provider_probe=true` 的必需 probe 数量；任何后续要把事件新闻用于 official gate、标签、买点或发布链路，必须先完成真实外部 probe、raw/source/lineage 写入、覆盖率/freshness 规则和 README 覆盖。

2026-06-14 本地 Docker 真实验证：

```text
POST /source/probe baidu.finance_news_feed
  sample_params={rn=5,pn=0,type=all,tag=all}
  connectivity_pass=true, schema_pass=true, row_count=5, missing_fields=[]
  usable_for_source_table=true, usable_for_model_online=false, usable_for_research_only=true

POST /source/fetch/plan source.event_news_v1 fields=title,published_at,available_at,event_type,url
  -> provider=baidu, api_name=finance_news_feed, queue_name=repair_queue, backup=cninfo.cninfo_disclosure_direct
POST /source/fetch/submit
  -> fetch_batch_id=fetch_batch_8cc7a0d2230d4b2e88a8, submitted_job_count=1
source-data-worker
  -> job_id=fetch_job_5f10597b8fb7419e942b, succeeded_count=1, generated_build_trigger_count=1
/source/build/results
  -> trigger_id=source_build_trigger_afac3fd082b549369d4d, status=succeeded
  -> raw_row_count=20, source_row_count=20, lineage_row_count=100, quality_issue_count=0
/raw_baidu.finance_news_feed_v1
  -> request_hash column/index present
  -> current raw rows with request_hash=40/40
/source/lineage/records?source_table_name=source.event_news_v1&source_pk=baidu:edf2056057bf7e73fd43ec7ff0fbf7bb
  -> title/published_at/available_at/event_type/url 均有 lineage
  -> provider=baidu, api_name=finance_news_feed, raw_table_name=raw_baidu.finance_news_feed_v1
  -> provider request_hash=d002973650bc7f17c7f2eb92208e14a8f52af93f11df2d7c6782a367f235c3e8
```

### 5.7 Tushare 准免费 / 付费备源

| API | 原表 | 请求参数 | 返回字段 | 目标 source |
|---|---|---|---|---|
| `pro.stock_basic` | `raw_tushare.stock_basic_v1` | `exchange`, `list_status`, `fields` | `ts_code`, `symbol`, `name`, `industry`, `market`, `exchange`, `list_status`, `list_date`, `delist_date` | `source.stock_master_v1` |
| `pro.trade_cal` | `raw_tushare.trade_cal_v1` | `exchange`, `start_date`, `end_date` | `exchange`, `cal_date`, `is_open`, `pretrade_date` | `source.trade_calendar_v1` |
| `pro.daily` | `raw_tushare.daily_v1` | `ts_code`, `start_date`, `end_date` | `open`, `high`, `low`, `close`, `pre_close`, `vol`, `amount` | `source.daily_bar_v1` |
| `pro.adj_factor` | `raw_tushare.adj_factor_v1` | `ts_code`, `start_date`, `end_date` | `ts_code`, `trade_date`, `adj_factor` | `source.adjustment_factor_v1` |
| `pro.moneyflow` | `raw_tushare.moneyflow_v1` | `ts_code`, `start_date`, `end_date` | 大小单资金流、`net_mf_amount` | `source.stock_moneyflow_daily_v1` |
| `pro.stk_limit` | `raw_tushare.stk_limit_v1` | `trade_date` | `pre_close`, `up_limit`, `down_limit` | `source.limit_price_v1` |

## 6. 标准 source 表与主备源关系

| Source 表 | 主 raw 表 | 备 raw 表 | 说明 |
|---|---|---|---|
| `source.stock_master_v1` | `raw_baostock.query_stock_basic_v1` | `raw_eastmoney.stock_universe_v1`, `raw_tushare.stock_basic_v1` | 股票基础信息；EastMoney universe 只备验名称、上市日期和上市状态，不提供退市日期 |
| `source.stock_universe_daily_v1` | `raw_baostock.query_all_stock_v1` | `raw_baostock.query_history_k_data_plus_daily_raw_v1` | 某交易日可交易 universe；AKShare/EastMoney spot 当前仅研究补充 |
| `source.trade_calendar_v1` | `raw_baostock.query_trade_dates_v1` | `raw_tushare.trade_cal_v1` | 调度基础 |
| `source.daily_bar_v1` | `raw_baostock.query_history_k_data_plus_daily_raw_v1` | `raw_tencent.daily_bars_v1`, `raw_sohu.daily_bars_v1`, `raw_tushare.daily_v1` | 未复权日 K；Tencent 备验 OHLC/volume，Sohu 备验 amount/pct_chg/turnover_rate |
| `source.adjusted_daily_bar_v1` | `raw_baostock.query_history_k_data_plus_daily_qfq_v1` | `raw_tencent.daily_bars_v1` | qfq adjusted OHLC；Tencent 替代 AKShare/EastMoney qfq 备源 |
| `source.adjustment_factor_v1` | `raw_baostock.query_adjust_factor_v1` | `raw_tushare.adj_factor_v1` | 复权审计 |
| `source.weekly_bar_v1` | 内部由 `source.daily_bar_v1` 聚合 | AKShare/BaoStock 周K校验 | 不建议直接以外部周K为主 |
| `source.trade_status_v1` | BaoStock 日K中的 `tradestatus`, `isST` | Tushare suspend/status | 三模型 hard block |
| `source.limit_price_v1` | 内部交易规则计算，优先使用 raw pre-close，缺失时只允许使用上一交易日 `source.daily_bar_v1.close_price` | `raw_tushare.stk_limit_v1` | 不能简单 `pct_chg>=9.8`；缺上一交易日标准 close 时保持缺口 |
| `source.index_daily_bar_v1` | `raw_tencent.daily_bars_v1` | `raw_baostock.query_history_k_data_plus_daily_raw_v1` | 市场环境；`close_price` 为 P0 online 字段，OHLC/pct_chg 已纳入默认多源矩阵；volume/amount 为 P1 显式审计字段，因 provider 定义差异暂不作为默认 passed 矩阵字段；BaoStock 备源请求指数安全字段集 |
| `source.board_daily_bar_v1` | `raw_akshare.stock_board_industry_hist_em_v1` | 内部按成员聚合 | 板块相对强弱 |
| `source.stock_moneyflow_daily_v1` | `raw_eastmoney.moneyflow_stock_series_v1` | `raw_tushare.moneyflow_v1` | P1 degradable `main_net_inflow` / `provider_definition`；AKShare moneyflow 仅 research-only/schema mismatch，不作为 source 生产者 |
| `source.event_news_v1` | `raw_baidu.finance_news_feed_v1` | `raw_cninfo.disclosure_direct_v1` | Baidu Finance research-only 事件新闻主源；CNINFO 公告直连为备源；进入模型前必须经过 source build、quality、lineage 和 available_at 校验 |

## 7. 数据巡检补采机制

当巡检发现缺口：

```text
source.adjusted_daily_bar_v1.adjusted_close 缺 000759.SZ / 2026-05-25
```

处理链路：

```text
1. 查询 governance.source_table_requirement_v1
2. 定位 primary_provider = baostock
3. 定位 primary_api_name = query_history_k_data_plus_daily_qfq
4. 生成 request params
5. 写入 governance.source_gap_v1
6. 写入 governance.source_repair_task_v1
7. 调度 source-data-service /source/raw/fetch
8. raw 表补采完成
9. 触发 source_build 重建 source.adjusted_daily_bar_v1
10. 更新 lineage
```

这保证后续数据不混乱，也避免为了补一个字段重跑全部数据。

## 8. 稳定性设计

- provider adapter 懒加载，缺少 `baostock` / `akshare` / `tushare` 依赖不会影响服务启动。
- provider 调用失败返回 probe/reject，不拖垮服务。
- 后续生产版需要接入持久化熔断状态、限流、队列化补采、异步 worker 和 dead-letter 队列。
- P0 source 表至少一主一备；没有备源不得进入正式模型链路。

## 10. 数据源增加操作指导

本节是后续用 Codex 或人工新增数据源时必须遵守的操作手册。目标是保证“每个接口一张原表、source 标准表由原接口表构建、巡检缺口能精准补采”的架构不被破坏。

### 10.1 新增数据源的判断边界

新增数据源只允许发生在以下场景：

```text
1. 现有 provider 无法覆盖某个 P0/P1 source 字段。
2. 现有 provider 覆盖率、延迟、稳定性或历史深度不满足模型要求。
3. 需要为某张 source 表增加备用 provider。
4. 数据巡检发现某类缺口长期无法由现有 repair API 修复。
5. 新模型或新服务提出了新的事实字段需求。
```

禁止因为“接口看起来方便”就直接新增数据源。每个新增 API 必须先写清楚：服务哪个 `source.*` 字段、为什么现有 API 不够、是主源还是备源、是否允许 online 使用、是否只允许 research-only。

### 10.2 涉及库表总览

新增一个 provider API 至少涉及下面这些表和代码关系：

```text
governance.provider_api_registry_v1
    ↓ 注册 provider、api_name、raw_table_name、请求模板、频率、是否免费、优先级

raw_<provider>.<api_name>_v1
    ↓ 一接口一原表，原样保存接口返回字段 + 统一治理字段

governance.provider_field_mapping_v1
    ↓ raw 字段到 canonical source 字段的映射、单位转换、类型转换、空值策略

governance.source_table_requirement_v1
    ↓ source 标准表字段需求、P0/P1/P2、主源、备源、repair API、最低覆盖率

source_build.<builder 或内部构建任务>
    ↓ 从 raw 表读取，执行字段映射、清洗、主备比对、质量标记

source.<canonical_table>
    ↓ 三大模型、调度、后续服务真正读取的标准事实表

governance.source_lineage_v1
    ↓ 记录 source 字段来自哪个 raw 表、raw_id、batch_id、provider、api_name

governance.source_gap_v1
    ↓ 巡检发现缺口后记录 source_table、field、symbol、date、gap_type

governance.source_repair_task_v1
    ↓ 根据 requirement/registry 自动生成 provider API 补采任务
```

关系原则：

```text
raw 表只保存接口事实；
source 表只保存标准事实；
lineage 负责解释 source 字段来自哪里；
gap/repair 负责解释缺口应该补哪个接口。
```

### 10.3 标准操作步骤

#### Step 1：确认 source 字段需求

先确认本次新增 API 是为了补哪张标准表的哪个字段，例如：

```text
source.adjusted_daily_bar_v1.adjusted_close
source.stock_moneyflow_daily_v1.main_net_inflow
source.event_news_v1.published_at
source.trade_status_v1.is_st
```

需要在 `governance.source_table_requirement_v1` 中明确：

```text
source_table_name
canonical_field_name
required_level: P0 / P1 / P2 / research_only
used_by_models: hot_candidates / candidate_memory / ambush_watchlist / scheduler / future_service
required_for_online
required_for_backtest
minimum_coverage_rate
primary_provider
backup_provider
repair_api_name
```

如果字段会进入模型评分、release gate、买点、outcome 或调度阻断，必须是 P0/P1，并且至少有一主一备；没有备源时只能标记为 `research_only` 或 `blocked_until_backup_ready`。

#### Step 2：注册 provider API

在 `provider_registry.py` 与 `governance.provider_api_registry_v1` 中登记 API。必须包含：

```text
provider
api_name
api_function
raw_table_name
request_template_json
frequency
is_free
requires_token
rate_limit_note
owner_service = source-data-service
enabled
priority
timeout_ms
retry_policy
circuit_breaker_policy
```

命名规则：

```text
provider 使用小写：baostock / akshare / tushare / eastmoney / tencent / sina / cninfo
api_name 必须体现数据口径：stock_zh_a_hist_daily_qfq、query_history_k_data_plus_daily_raw
raw_table_name 必须和 provider + api_name 一一对应：raw_akshare.stock_zh_a_hist_daily_qfq_v1
```

禁止把多个不同请求参数的接口混进同一张 raw 表。例如未复权日K和前复权日K必须拆表：

```text
raw_akshare.stock_zh_a_hist_daily_raw_v1
raw_akshare.stock_zh_a_hist_daily_qfq_v1
```

#### Step 3：创建 raw 原接口表

在 `infra/sql` 新增 migration。raw 表必须包含：

```text
raw_id
provider
api_name
api_version
library_version
request_hash
request_params_json
response_schema_hash
response_row_hash
batch_id
biz_key
captured_at
available_at
ingest_status
error_code
error_message
raw_payload_json
raw_row_json
created_at
```

并额外保留接口解析后的主要字段。

唯一键必须体现请求口径。例如日K：

```text
(provider, api_name, symbol, trade_date, frequency, adjust_mode)
```

公告类数据：

```text
(provider, api_name, symbol, announcement_id 或 url_hash, published_at)
```

资金流排行类数据：

```text
(provider, api_name, rank_window, captured_trade_date, symbol)
```

#### Step 4：实现 provider adapter

在 `src/source_data_service/adapters/` 下新增或扩展 adapter。要求：

```text
1. adapter 必须懒加载第三方包。
2. 包缺失、网络失败、字段缺失、限流、远程 500 都不能让 source-data-service 进程崩溃。
3. 返回必须统一为 RawFetchResult。
4. dry_run=true 时只校验参数和 registry，不访问外部 provider。
5. 每次调用都要生成 request_hash、schema_hash、row_hash。
6. provider 原始字段必须保存在 raw_row_json，不得只保存转换后字段。
7. provider DataFrame、日期、numpy 标量、NaN 和嵌套 JSON 值进入 request/response hash 或 raw_row_json 前必须规范化为可序列化、可审计的 JSON 值；真实缺失保持 NULL，不得用 0 或空字符串补齐。
```

异常处理必须返回结构化错误：

```text
provider_unavailable
provider_package_missing
provider_timeout
provider_rate_limited
provider_schema_changed
provider_empty_response
provider_field_missing
provider_auth_required
```

#### Step 5：登记字段映射

在 `governance.provider_field_mapping_v1` 中登记 raw 字段到 canonical 字段的映射。

示例：

```text
raw_akshare.stock_zh_a_hist_daily_qfq_v1.收盘
-> source.adjusted_daily_bar_v1.adjusted_close
unit_transform = decimal_price
dtype_transform = Decimal(18,6)
null_policy = reject_if_p0
```

```text
raw_tushare.daily_v1.vol
-> source.daily_bar_v1.volume
unit_transform = hand_to_share_or_keep_hand_with_unit_flag
dtype_transform = Decimal(24,4)
null_policy = allow_null_if_suspended
```

资金流、成交额、成交量、涨跌幅这些字段必须写清单位，不允许 provider 间静默混用。

#### Step 6：定义 source build 规则

source 标准表构建必须明确：

```text
主源优先级
备源补缺规则
主备差异阈值
字段单位转换
复权口径
quality_status
lineage 写入规则
available_at 继承规则
```

示例：

```text
source.daily_bar_v1.close
主源：raw_baostock.query_history_k_data_plus_daily_raw_v1.close
备源：raw_akshare.stock_zh_a_hist_daily_raw_v1.收盘
差异阈值：价格相对差异 <= 0.5% 或绝对差异 <= 0.01
超阈值：source_quality_status = suspect_cross_provider_diff
不得自动取平均。
```

硬性规则：跨源差异超阈值时，不能用均值平滑出一个“看起来合理”的值；必须标记 suspect，由巡检或人工确认。

#### Step 7：配置缺口补采规则

新增 API 后必须确保 `/source/gaps/repair-plan` 能定位它。也就是说，`governance.source_table_requirement_v1` 中必须能回答：

```text
source_table_name + canonical_field_name + symbol + trade_date
应该调用哪个 provider？
哪个 api_name？
写入哪张 raw 表？
请求参数怎么生成？
主源失败后备源是谁？
补完 raw 后需要重建哪张 source 表？
```

补采参数生成规则必须显式定义。

日K类：

```text
internal symbol 000759.SZ
-> BaoStock code sz.000759
-> AKShare symbol 000759
-> Tushare ts_code 000759.SZ
```

日期类：

```text
canonical trade_date 2026-05-25
-> BaoStock 2026-05-25
-> AKShare 20260525
-> Tushare 20260525
```

#### Step 8：加入 readiness 评估

每个新增 API 和每张 source 表必须能被 `/source/readiness/evaluate` 评估。至少输出：

```text
provider_connectivity_pass
schema_pass
field_coverage_rate
symbol_coverage_rate
date_coverage_rate
missing_rate
duplicate_rate
cross_provider_diff_pass
available_at_supported
rate_limit_observed
latency_ms
usable_for_source_table
usable_for_model_online
usable_for_research_only
reject_reason
```

没有 readiness 的 API 不能进入正式模型链路。

#### Step 9：加入调度任务

新增 API 后，需要在 scheduler 中配置三类任务：

```text
raw ingest task：采集 provider 原接口数据
source build task：由 raw 构建 source 标准表
gap repair task：巡检发现缺口后补采
```

调度不能直接调用模型，也不能跳过 raw 表写 source 表。

#### Step 10：更新文档和测试

必须覆盖更新：

```text
services/source-data-service/README.md
AGENTS.md 如涉及项目硬性规则
infra/README.md 如涉及 Docker / migration 运行方式
相关服务 README 如新增 source 依赖
```

必须新增或更新测试：

```text
API registry 测试
repair-plan 测试
字段映射测试
SQL contract 测试
provider dry-run 测试
source readiness 测试
```

### 10.4 数据巡检发现缺口后的定位逻辑

数据巡检服务发现缺口后，不允许只输出“缺数据”。必须输出可执行补采计划。标准流程：

```text
1. data-inspector-service 发现 source 表字段缺失。
2. 写入 governance.source_gap_v1。
3. 调用 source-data-service /source/gaps/repair-plan。
4. source-data-service 查询 governance.source_table_requirement_v1。
5. 根据 source_table + canonical_field 找到 primary_provider / backup_provider / repair_api_name。
6. 根据 provider_api_registry_v1 找到 raw_table_name、request_template_json。
7. 根据 symbol/date 转换规则生成请求参数。
8. 写入 governance.source_repair_task_v1。
9. scheduler-service 调度 /source/raw/fetch。
10. raw 表写入成功后触发 source build。
11. source build 写入 source 标准表，并写 source_lineage_v1。
12. data-inspector-service 复检缺口是否关闭。
```

缺口示例：

```json
{
  "source_table_name": "source.adjusted_daily_bar_v1",
  "canonical_field_name": "adjusted_close",
  "symbol": "000759.SZ",
  "trade_date": "2026-05-25"
}
```

补采计划必须能返回：

```json
{
  "primary_repair": {
    "provider": "baostock",
    "api_name": "query_history_k_data_plus_daily_qfq",
    "raw_table_name": "raw_baostock.query_history_k_data_plus_daily_qfq_v1",
    "params": {
      "code": "sz.000759",
      "start_date": "2026-05-25",
      "end_date": "2026-05-25",
      "frequency": "d",
      "adjustflag": "2"
    }
  },
  "backup_repairs": [
    {
      "provider": "akshare",
      "api_name": "stock_zh_a_hist_daily_qfq",
      "raw_table_name": "raw_akshare.stock_zh_a_hist_daily_qfq_v1",
      "params": {
        "symbol": "000759",
        "period": "daily",
        "start_date": "20260525",
        "end_date": "20260525",
        "adjust": "qfq"
      }
    }
  ],
  "source_rebuild_required": true,
  "source_rebuild_target": "source.adjusted_daily_bar_v1"
}
```

### 10.5 禁止事项

```text
1. 禁止模型服务直接调用 BaoStock / AKShare / Tushare / EastMoney / Tencent / Baidu 等 provider。
2. 禁止 adapter 直接写 decision_* 模型表。
3. 禁止 raw 表和 source 表混写。
4. 禁止多个接口混用一张 raw 表。
5. 禁止 source build 使用跨源均值掩盖差异。
6. 禁止缺失字段用 0、空字符串、上一个交易日或示例值填充。
7. 禁止没有 lineage 的 source 字段进入模型 release gate。
8. 禁止 provider 网络异常导致 source-data-service 容器退出。
9. 禁止普通服务迭代时关停 source-data-service Docker。
10. 禁止未经过 readiness 的 API 成为正式主源。
```

### 10.6 新增 API 完成定义

一个新增 provider API 只有同时满足下面条件，才算完成：

```text
1. provider_api_registry_v1 已登记。
2. raw_<provider>.<api>_v1 原表已存在。
3. adapter 支持 dry_run 和真实调用。
4. 原始返回字段能写入 raw_row_json。
5. provider_field_mapping_v1 已登记字段映射。
6. source_table_requirement_v1 已登记主备源和 repair API。
7. /source/gaps/repair-plan 能返回该 API 的补采计划。
8. source build 能写入 source 标准表。
9. source_lineage_v1 能追溯到 raw_id。
10. /source/readiness/evaluate 有结果。
11. README 已同步。
12. SQL contract、dry-run、repair-plan 相关测试通过。
```

## 9. 当前验证

当前 DS-1 是代码级、契约级、单元测试级底座。真实 provider 网络拉取、真实 Postgres migration、Docker/compose 启动仍需在你的本地环境执行。

## Docker 微服务运行口径 v2

本服务在微服务框架中作为独立 Docker 容器运行，Compose 服务名为 `source-data-service`，端口默认 `8041`。

### 稳定性原则

- 服务启动不强依赖 BaoStock / AKShare / Tushare Python 包是否安装；provider adapter 采用懒加载。
- 远程 provider 掉线、接口变更、限流、包缺失时，`/healthz` 和 `/readyz` 不会被拖垮。
- `/source/raw/fetch` 对 provider 异常返回结构化 `RawFetchResult.error`，而不是让服务进程崩溃。
- 每个 `provider + api_name` 独立 circuit breaker，避免单接口连续失败时拖慢全服务。
- 数据巡检或调度拿到错误后，应调用 `/source/gaps/repair-plan` 获取主备源补采计划。

### 新增健康与运行状态接口

```text
GET /healthz
GET /readyz
GET /source/providers/status
```

`/readyz` 只校验服务注册表和 P0 数据需求是否装载，不主动访问远程 provider。这样可以保证服务在外部数据源临时不可用时仍保持可调度、可诊断、可生成补采计划。

### Docker 依赖顺序

```text
postgres -> schema-bootstrap -> source-data-service -> models -> scheduler
```

三大模型和调度服务依赖 `source-data-service` 的 `service_healthy` 状态。provider 实测失败不会改变 source-data-service 的容器健康状态，而是进入 provider runtime status / probe / gap repair 体系处理。

---

## 11. DS-2 最高规格数据源可靠性加固

锁定候选目标：`source_data_service_ds2_reliability_hardening_candidate`

本轮加固目标是把数据源服务从“能登记 provider API 和生成补采计划”提升到“正式上线前可审计、可补采、可追溯、可稳定运行”的标准。

### 11.1 字段级合同是数据源拍板依据

每一个模型可读取的 `source.*` 字段都必须在字段合同中登记。字段合同不仅说明主备源，还必须说明：

```text
source_table_name
canonical_field_name
required_level: P0 / P1 / P2 / research_only
data_type
unit
price_adjustment_mode: raw / qfq / hfq / not_price / mixed
time_semantics
used_by_models
primary_provider + primary_api_name
backup_provider + backup_api_name
raw_table_name
field_quality_rules
online_policy: required / degradable / research_only
comment
```

代码入口：

```text
GET /source/contracts
GET /source/contracts?source_table_name=source.daily_bar_v1
GET /source/contracts/source.daily_bar_v1
```

落库表：

```text
governance.source_field_contract_v1
```

硬性标准：

```text
1. P0 + online_policy=required 的字段缺失时，模型 official release 必须阻断。
2. research_only 字段不能影响 official release，只能进入解释、研究或后验分析。
3. raw 价格和 adjusted 价格不能混用。
4. 每个字段必须有 source_lineage_v1 血缘。
5. 每个字段必须能反推出 repair provider / api / raw_table / request_params。
```

### 11.2 已扩展的 P0/P1 字段覆盖

本轮从原先少量代表字段，扩展到字段级链路，重点覆盖：

```text
source.daily_bar_v1:
open_price, high_price, low_price, close_price, pre_close_price, volume, amount, pct_chg, turnover_rate

source.adjusted_daily_bar_v1:
adjusted_open, adjusted_high, adjusted_low, adjusted_close, volume, amount

source.adjustment_factor_v1:
adjustment_factor

source.stock_master_v1:
stock_name, list_status, ipo_date, delist_date

source.stock_universe_daily_v1:
is_tradable, trade_status

source.trade_status_v1:
is_tradable, is_suspended, is_st, is_delisting_risk

source.trade_calendar_v1:
is_trading_day, pretrade_date

source.limit_price_v1:
up_limit_price, down_limit_price, limit_rule

source.limit_event_v1:
limit_event_type

source.index_daily_bar_v1:
close_price, pct_chg

source.board_master_v1:
board_name

source.stock_board_membership_v1:
board_name

source.board_daily_bar_v1:
close_price, pct_chg

source.stock_moneyflow_daily_v1:
main_net_inflow, provider_definition

source.event_news_v1:
title, published_at, available_at, event_type, url
```

### 11.3 数据缺口诊断链路

数据巡检服务发现缺口后，不应该只得到“缺字段”，而应该得到完整处置方案。

接口：

```http
POST /source/gaps/diagnose
```

请求示例：

```json
{
  "source_table_name": "source.adjusted_daily_bar_v1",
  "canonical_field_name": "adjusted_high",
  "symbol": "000759.SZ",
  "trade_date": "2026-05-25"
}
```

返回必须包含：

```text
1. required_level
2. affected_models
3. required_for_online / required_for_backtest
4. primary_repair
5. backup_repairs
6. rebuild_steps
7. lineage_lookup
8. operator_checklist
9. online_impact: block_online / degrade / research_only
```

处理流程：

```text
data-inspector-service
-> /source/gaps/diagnose
-> 生成 provider API 级补采任务
-> /source/raw/fetch
-> 写 raw_<provider>.<api>_v1
-> source build 重建 source.* 字段
-> 写 governance.source_lineage_v1
-> 再次 readiness / probe / diff
-> 调度服务再允许模型运行
```

### 11.4 血缘定位链路

接口：

```http
POST /source/lineage/resolve
```

用途：当某个 source 字段异常时，快速知道应该查哪张 raw 表、哪个 provider API、哪些原始字段。

请求示例：

```json
{
  "source_table_name": "source.daily_bar_v1",
  "canonical_field_name": "high_price",
  "symbol": "000759.SZ",
  "trade_date": "2026-05-25"
}
```

返回会包含：

```text
lineage_query_hint
candidate_raw_tables
candidate_provider_apis
expected_raw_fields
```

这保证后续数据巡检、人工排障、Codex 迭代都能从 source 字段反查到原始接口，不会出现“数据混乱但不知道从哪里来的”问题。

### 11.5 原接口采集批次与幂等

`/source/raw/fetch` 返回增加：

```text
request_hash
response_schema_hash
rows[].request_hash
rows[].response_schema_hash
rows[].response_row_hash
```

数据库新增：

```text
governance.raw_ingest_batch_v1
```

用途：

```text
1. request_hash 支持同一 provider/api/params 的幂等采集。
2. response_schema_hash 发现接口字段变更。
3. response_row_hash 支持行级去重和回放审计。
4. raw_ingest_batch_v1 记录一次 provider API 调用的开始、结束、状态、行数和错误。
```

如果 `response_schema_hash` 发生变化，必须先标记 `schema_pass=false`，再由字段映射审核后才能进入 source build。

### 11.6 SQL 注释与上线可读性

新增迁移：

```text
infra/sql/0015_source_data_reliability_hardening_v1.sql
```

新增/增强：

```text
governance.source_field_contract_v1
governance.provider_api_availability_v1
governance.raw_ingest_batch_v1
governance.source_canonical_build_rule_v1
```

并对关键表和字段补充 `COMMENT ON TABLE / COMMENT ON COLUMN`：

```text
source.daily_bar_v1
source.daily_bar_v1.open_price / high_price / low_price / close_price / pre_close_price / volume / amount / available_at
source.adjusted_daily_bar_v1
source.adjusted_daily_bar_v1.adjustment_mode / adjusted_close / source_quality_status
source.trade_status_v1
source.limit_price_v1
governance.source_gap_v1
governance.source_repair_task_v1
```

这些注释不是装饰，而是给 DBA、Codex、数据巡检和后续服务开发看的正式上线契约。

### 11.7 正式上线前必须执行的验证

代码级验证已覆盖：

```text
/source/contracts
/source/gaps/diagnose
/source/lineage/resolve
/source/raw/fetch dry_run request_hash
SQL contract: 0012 / 0013 / 0014 / 0015
```

真实上线前仍必须在你的本地或服务器执行：

```text
1. docker compose build source-data-service
2. docker compose up -d postgres schema-bootstrap source-data-service
3. 执行 infra/sql/0012~0015 migration
4. GET /healthz
5. GET /readyz
6. GET /source/providers/status
7. GET /source/contracts?source_table_name=source.daily_bar_v1
8. POST /source/probe dry_run=false 至少验证 probe matrix 中 `real_probe_required=true` 的生产必需接口：BaoStock P0 基础源、Tencent `daily_bars`、Sohu `daily_bars` 个股 `amount/pct_chg` 备源，以及模型四所需 EastMoney `quote_snapshot/minute_bars/trade_details`
9. POST /source/gaps/diagnose 验证缺口能生成主备源补采计划
10. POST /source/raw/fetch dry_run=false 真实拉取 000759 一个交易日样本
11. 检查 raw 表写入、source build、source_lineage_v1、readiness 结果
```

未执行真实 provider 网络实测前，数据源服务只能标记为：

```text
代码级 / 契约级 / 单元测试级锁定候选
```

不能标记为生产数据源已拍板。

## 11. DS-3 正式上线级 source build 与巡检闭环加固

版本建议：`source_data_service_ds4_concurrent_fetch_orchestration_candidate`

本阶段继续围绕数据源服务做上线级加固，目标不是增加模型能力，而是把 **provider 实测、raw 原表质量门禁、source 标准表构建计划、字段修复路由、readiness 证据** 做成可被 `data-inspector-service`、`scheduler-service` 和 Codex 后续迭代稳定调用的能力。

### 11.1 新增 API

```http
GET /source/readiness/matrix
GET /source/probe/matrix
GET /source/repair-routes
POST /source/build/plan
POST /source/quality/validate-raw
```

### 11.2 `/source/probe/matrix`

用途：列出每个 provider/API 的实测矩阵，告诉运维或数据巡检服务：

```text
1. 应该用什么 sample_params 做真实探针；
2. 预期返回字段是什么；
3. 原始数据应该落哪张 raw 表；
4. 这个 API 支撑哪些 source 标准表；
5. 是否必须在正式上线前做 real probe。
```

返回字段包括：

```text
provider
api_name
raw_table_name
sample_params
expected_fields
canonical_targets
dry_run_supported
real_probe_required
readiness_note
```

`real_probe_required=true` 的语义是“生产拍板硬门禁必需真实 probe”，不是“所有已登记接口都要立刻阻断拍板”。当前硬门禁只覆盖 `P0 + required_for_online` 字段对应的、adapter 已实现且不需要 token 的 provider/API；其中 Tencent `daily_bars` 已作为 AKShare/EastMoney 日 K / qfq / index 替代源进入 required probe。EastMoney 当前只有 `moneyflow_stock_series` 具备 adapter 运行路径，它服务的是 `source.stock_moneyflow_daily_v1.main_net_inflow` P1 degradable 字段，不是 P0 online hard gate；2026-06-14 本地运行容器已完成真实 probe、Postgres raw/source/lineage 写入和 preflight passed 验证。Baidu `finance_news_feed` 当前具备 adapter、raw/source/lineage 合同和 research-only repair route，用于 `source.event_news_v1` 事件证据，不是 P0 online hard gate；启用为 official gate 前必须另行完成覆盖率、freshness、分类质量和真实 probe 门禁。已登记但 adapter 仍 pending 的 EastMoney 其他接口、Tencent 其他接口、Sina、CNINFO，以及需要 token/积分/付费权益的 Tushare 备源，保留在矩阵中作为合同和后续接入证据项，但不阻断免费源生产候选闭环。任何这类 API 后续被启用为 online gate、主源、fallback、adapter 或 converter 后，必须先完成真实 probe 并把结果写入 `governance.source_probe_result_v1`。

AKShare 中 `stock_zh_a_spot_em`、`index_zh_a_hist`、`stock_zh_a_hist_daily_raw` 与 `stock_zh_a_hist_daily_qfq` 因最新真实 probe 遇到 EastMoney 远端断开，不再作为生产拍板硬门禁。日 K / qfq / index 缺口当前按 Tencent `daily_bars` 修复；stock universe 当前按 BaoStock `query_all_stock` 主源和 BaoStock 日线状态备路闭环；AKShare 这些历史 raw 合同如需恢复为 online gate、主源、fallback、adapter 或 converter，必须重新完成真实外部请求探针、raw/source/lineage 写入验证和 README 覆盖。

### 11.3 `/source/quality/validate-raw`

用途：在 raw provider 行进入 source build 前做行级质量检查。

当前已覆盖：

```text
1. schema 字段缺失检查；
2. OHLC 数值可解析检查；
3. high >= low；
4. open / close 必须落在 [low, high]；
5. volume / amount 非负；
6. provider/API 对应原表识别。
```

示例：

```json
{
  "provider": "baostock",
  "api_name": "query_history_k_data_plus_daily_raw",
  "rows": [
    {
      "date": "2026-05-25",
      "code": "sz.000759",
      "open": "5.0",
      "high": "5.3",
      "low": "4.9",
      "close": "5.2",
      "preclose": "4.8",
      "volume": "10000",
      "amount": "52000",
      "adjustflag": "3",
      "turn": "2.0",
      "tradestatus": "1",
      "pctChg": "4.0",
      "isST": "0"
    }
  ]
}
```

如果返回：

```text
build_allowed=false
```

则 `source_build` 不能继续写 `source.*`，必须先处理 raw 数据异常。禁止把异常值静默填 0 或跳过后仍进入模型。

### 11.4 `/source/build/plan`

用途：给定某张 source 表、字段和股票/日期范围，输出标准构建计划。

示例：

```json
{
  "source_table_name": "source.adjusted_daily_bar_v1",
  "canonical_fields": ["adjusted_close", "adjusted_high"],
  "symbol": "000759.SZ",
  "trade_date": "2026-05-25"
}
```

返回内容会说明：

```text
1. 每个 canonical field 的主 raw 表；
2. 备 raw 表；
3. 质量门禁；
4. source_lineage 是否必须写入；
5. build_rule_code；
6. source build 执行顺序。
```

标准执行顺序固定为：

```text
1. Fetch or verify raw provider rows in one-interface-one-table raw_* tables.
2. Validate raw schema hash and row-level quality gates.
3. Normalize units and field names into canonical source fields.
4. Compare primary and backup provider values where backup exists.
5. Upsert source.* canonical facts with source_quality_status.
6. Write governance.source_lineage_v1 for every canonical field.
7. Re-run readiness and gap diagnostics before model release tasks.
```

### 11.5 `/source/repair-routes`

用途：给巡检服务提供快速字段修复路由。

每一行代表：

```text
source_table_name + canonical_field_name
-> primary_provider / primary_api_name / primary_raw_table_name
-> backup_provider / backup_api_name
-> online_policy
-> used_by_models
```

后续 `data-inspector-service` 不应自行猜测“缺哪个接口”，而应优先读取该路由或调用 `/source/gaps/diagnose`。

### 11.6 `/source/readiness/matrix`

用途：以 source 表为粒度输出 readiness 概览。

判断规则：

```text
P0 / P1 字段没有备源 -> blocked
没有 P0 字段 -> research_only
P0 字段具备主备源 -> passed（仍需真实 coverage / probe evidence 才能生产拍板）
```

注意：`passed` 只表示合同层和路由层可通过，不等于真实 provider 已上线拍板。真实拍板还需要：

```text
provider_probe_matrix_v1
raw_quality_check_result_v1
source_readiness_evidence_v1
source_lineage_v1
真实 coverage / cross-provider compare 报告
```

### 11.7 新增治理表

新增 migration：

```text
infra/sql/0016_source_data_operational_readiness_v1.sql
```

新增表：

```text
governance.provider_probe_matrix_v1
governance.raw_quality_check_result_v1
governance.source_build_batch_v1
governance.source_readiness_evidence_v1
governance.source_field_repair_route_v1
```

#### `governance.provider_probe_matrix_v1`

每个 provider/API 的实测矩阵和最近探针状态。

用途：

```text
1. 正式上线前确认 API 真实可连；
2. 确认返回字段是否符合 registry；
3. 发现 response_schema_hash 变化；
4. 为 readiness 提供 provider 证据。
```

#### `governance.raw_quality_check_result_v1`

每次 raw 行级质量检查结果。

用途：

```text
1. 防止坏 raw 数据进入 source.*；
2. 保留 OHLC、schema、非负数、类型转换等问题；
3. 作为 source build 是否允许执行的前置门禁。
```

#### `governance.source_build_batch_v1`

每次 source 标准表构建批次。

用途：

```text
1. 记录 source 表重建范围；
2. 记录输入 raw batch；
3. 记录输出行数；
4. 记录 lineage 写入数量；
5. 支持回放和问题定位。
```

#### `governance.source_readiness_evidence_v1`

字段级 readiness 证据。

用途：

```text
1. 证明某个 source 字段不是“注册了接口”而是“真实可用”；
2. 存储 probe、coverage、quality、cross-provider、lineage 等证据；
3. 区分 passed / blocked / research_only / suspect。
```

#### `governance.source_field_repair_route_v1`

字段缺口快速修复路由。

用途：

```text
1. 让 data-inspector-service 快速定位补采接口；
2. 避免巡检服务硬编码 provider 规则；
3. 让新增数据源时只改 registry/route，不改模型和巡检逻辑。
```

### 11.8 DS-3 正式上线前验收标准

DS-3 完成后，正式上线前必须继续做真实环境验证：

```text
1. 至少对 BaoStock 和 Tencent 的 P0 日 K / qfq / index API 执行真实 probe；
2. 将真实 probe 结果写入 governance.provider_probe_matrix_v1；
3. 将真实 raw fetch 写入对应 raw_* 原表；
4. 对 raw rows 执行 /source/quality/validate-raw；
5. 将质量结果写入 governance.raw_quality_check_result_v1；
6. 执行 source build，写 source.* 和 governance.source_lineage_v1；
7. 写 source_build_batch_v1；
8. 写 source_readiness_evidence_v1；
9. 调用 /source/readiness/matrix 和 /source/gaps/diagnose；
10. 只有 P0 字段 evidence_status=passed，模型 release_gate 才允许读取。
```

### 11.9 当前未闭环风险

当前仍然是代码级、契约级、单元测试级加固，尚未完成：

```text
1. 真实 provider 网络实测；
2. 真实 Postgres migration；
3. raw 表真实写入；
4. source build 真实写入；
5. source_lineage_v1 真实写入；
6. 连续交易日数据巡检与补采闭环。
```

这些必须在处理其他服务前继续推进，不能因为模型代码已存在就跳过数据源真实验收。

## 12. DS-4 并发采集、生产-消费、任务状态回调与 provider 限流

### 12.1 设计目标

DS-4 解决数据源服务正式上线前最关键的并发问题：不能在模型监控多个股票、数据巡检发现大量缺口、模型临时索取数据、历史回补时，按股票逐个串行抓取，从而造成数据延迟。

正式原则：

```text
1. 支持批量优先：能按 trade_date 全市场拉取的接口，不逐只股票抓。
2. 支持 symbol 并发：只能按单股票拉历史窗口的接口，使用受控并发。
3. 支持 provider/API 限流：不同 provider、不同 API 有不同 max_concurrency 和 requests_per_minute。
4. 支持生产-消费：生产者创建 fetch batch，消费者 worker 领取 job，任务状态不丢。
5. 支持回调/outbox：batch/job 状态变化写 callback event，供巡检、调度、模型预检追踪。
6. 支持备源自动排队：主源失败后，按 backup_plans 自动创建备源 job。
7. 支持优先级队列：P0 release_gate 数据优先于普通采集、回补和研究任务。
```

### 12.2 数据抓取任务类型

所有数据抓取任务必须归入一种 `trigger_type`：

```text
scheduled_periodic：固定周期调度采集，例如每日收盘后日K、复权K、指数、板块。
data_inspection_gap_repair：数据巡检发现缺口后临时补采。
model_adhoc_request：模型临时索取某个 source 字段，例如模型三临时需要某只股票的 qfq 日K。
model_release_preflight：模型 release_gate 前 P0 数据预检与紧急补采。
manual_backfill：人工历史回补。
provider_probe：provider/API 真实探针。
operator_manual：运维人工触发。
```

优先级：

```text
P0_urgent_release：阻断模型 official signal 的数据。
P1_normal_ingest：常规每日采集。
P2_backfill：历史回补。
research：研究增强数据。
```

队列：

```text
urgent_release_gate_queue
normal_daily_ingest_queue
repair_queue
backfill_queue
research_queue
provider_probe_queue
```

### 12.3 新增 API

#### `POST /source/fetch/plan`

只生成计划，不入队。用于让调度、巡检、模型预检先看到将调用哪些 provider/API、落哪些 raw 表、会产生多少任务、预计耗时和限流策略。

示例：

```json
{
  "source_table_name": "source.adjusted_daily_bar_v1",
  "canonical_fields": ["adjusted_close", "adjusted_high"],
  "symbols": ["000759.SZ", "000001.SZ"],
  "trade_date": "2026-05-25",
  "trigger_type": "model_release_preflight",
  "priority": "P0_urgent_release",
  "request_source": "ambush-watchlist-service",
  "model_code": "ambush_watchlist",
  "model_phase": "release_gate",
  "dry_run": true
}
```

返回重点：

```text
fetch_plan_id
strategy：full_market_batch / symbol_parallel / single_request / api_batch_by_date
queue_name
job_count
jobs[].provider/api_name/raw_table_name/request_params/request_hash
jobs[].backup_plans
rate_limit_policies
operator_notes
```

#### `POST /source/fetch/submit`

生产者提交任务，生成 durable fetch batch 与 job items。服务返回 `fetch_batch_id`。

```text
生产者只负责 submit，不直接抓 provider。
消费者 worker 后续通过 pull 领取任务。
```

#### `POST /source/fetch/worker/pull`

消费者领取任务。服务会检查 provider/API 当前并发，超过 `max_concurrency` 的 API 不会继续派发任务。

#### `POST /source/fetch/jobs/{job_item_id}/complete`

消费者完成任务后回写成功/失败。

成功：

```text
job.status = succeeded
写 job_succeeded callback event
后续应触发 raw quality -> source build -> source_lineage
```

失败：

```text
job.status = failed
写 job_failed callback event
如果存在 backup_plans，自动创建 backup job，并写 backup_job_queued callback event
```

#### `GET /source/fetch/batches/{fetch_batch_id}`

查看 batch 级状态，包含 queued/leased/succeeded/failed 数量。

#### `GET /source/fetch/jobs/{job_item_id}`

查看单个任务状态。

#### `GET /source/fetch/callbacks`

查看生产-消费状态回调 outbox。

#### `GET /source/providers/runtime-status`

查看 provider/API 并发状态、排队数量、失败数量、circuit 状态。

#### `GET /source/fetch/rate-limit-policies`

查看 provider/API 限流策略。

### 12.4 新增治理表

新增 migration：

```text
infra/sql/0017_source_data_concurrent_fetch_orchestration_v1.sql
```

新增表：

```text
governance.provider_rate_limit_policy_v1
governance.raw_fetch_batch_v1
governance.raw_fetch_job_item_v1
governance.raw_fetch_callback_event_v1
governance.provider_runtime_status_v1
governance.source_build_trigger_v1
```

关系说明：

```text
provider_rate_limit_policy_v1
  控制每个 provider/API 的 max_concurrency、requests_per_minute、timeout、retry、circuit breaker。

raw_fetch_batch_v1
  一次生产者提交的采集批次。来源可以是调度、巡检、模型临时请求、release preflight、人工回补。

raw_fetch_job_item_v1
  一个精确 provider/API/raw_table/request_params 的消费者任务。request_hash 唯一，防重复抓取。

raw_fetch_callback_event_v1
  任务状态 outbox，确保 batch_submitted、job_leased、job_succeeded、job_failed、backup_job_queued、batch_completed 等状态不丢。

provider_runtime_status_v1
  provider/API 运行状态快照，供路由、限流、降级和备源切换使用。

source_build_trigger_v1
  raw 抓取成功后触发 source build。source build 必须先过 raw quality，再写 source.* 和 source_lineage_v1。
```

### 12.5 与数据巡检服务的配合

巡检发现缺口时，流程是：

```text
/source/gaps/diagnose
-> /source/fetch/plan
-> /source/fetch/submit
-> worker pull/complete
-> raw quality validate
-> source build
-> source_lineage_v1
-> /source/models/coverage/check（后续 DS-5）
```

巡检服务不再猜 provider/API。它只提交 source table + canonical field + symbol/date，source-data-service 根据 registry、field contract、repair route 和 rate-limit policy 生成补采任务。

### 12.6 与调度服务的配合

调度服务负责“何时生产任务”，source-data-service 负责“如何拆 provider/API 并执行受控并发”。

调度服务可生产：

```text
source.fetch.daily_bar.close
source.fetch.adjusted_daily_bar.close
source.fetch.trade_status.close
source.fetch.limit_price.preopen
source.fetch.market_breadth.close
source.fetch.model_release_preflight
source.fetch.gap_repair
source.fetch.manual_backfill
```

但调度服务不得直接调用 provider，也不得写 raw/source 表。

### 12.7 拍板标准

DS-4 当前达到代码级、契约级、单元测试级闭环。正式生产拍板前，还必须完成：

```text
1. 将 raw_fetch_batch_v1 / raw_fetch_job_item_v1 从当前内存实现切换到真实 Postgres repository。
2. 真实 worker 进程从 /source/fetch/worker/pull 领取任务并调用 provider adapter。
3. 成功 raw fetch 后真实写 raw_<provider>.<api>_v1。
4. 成功后真实触发 raw quality、source build、source_lineage_v1。
5. P0 release preflight 任务在 provider 限流下能按 SLA 完成。
6. 主源失败时备源 job 自动入队并可完成。
7. 连续交易日验证无任务丢失、无重复抓取、无无限重试。
```


## 13. DS-5 持久化队列、worker 执行器与任务不丢失加固

DS-5 的目标是把 DS-4 的生产-消费任务链路从“接口合同 + 内存演示”推进到正式上线可运行的队列治理标准。数据源服务不再只提供任务拆解能力，还必须明确任务如何持久化、如何被 worker 领取、如何续租、如何取消、如何出死信、如何触发 source build，以及如何让调度、巡检、模型临时请求都走同一条不丢任务链路。

### 13.1 任务来源分类

数据抓取任务统一分为：

```text
scheduled_periodic          固定周期调度采集，由 scheduler-service 生产。
data_inspection_gap_repair  数据巡检发现 source 字段缺口后生产。
model_adhoc_request         模型临时索取数据，但模型不得直接调用 provider。
model_release_preflight     模型 release_gate 前 P0 数据预检与紧急补齐。
manual_backfill             运维或研究人员发起的历史回补。
provider_probe              provider/API 上线前真实探针或 dry-run 探针。
operator_manual             其他人工触发任务。
```

所有任务都必须进入 `raw_fetch_batch_v1` 和 `raw_fetch_job_item_v1`，禁止绕过队列直接抓 provider。

### 13.2 DS-5 新增 API

```text
GET  /source/fetch/persistence/status
GET  /source/fetch/queues/summary
POST /source/fetch/maintenance/requeue-expired-leases
GET  /source/fetch/dead-letter
POST /source/fetch/batches/{fetch_batch_id}/cancel
POST /source/fetch/jobs/{job_item_id}/heartbeat
POST /source/fetch/worker/run-once
POST /source/fetch/callbacks/dispatch
GET  /source/build/triggers
```

说明：

```text
/source/fetch/persistence/status
  检查当前队列后端是 memory 还是 postgres。生产必须是 postgres，否则只能算本地合同测试。

/source/fetch/queues/summary
  查看各队列 queued/leased/succeeded/failed/dead_letter 计数。生产后端为 postgres 且 ready_for_production_queue=true 时，必须直接读取 governance.raw_fetch_job_item_v1 的 durable 状态，不得使用 API 容器进程内 _JOBS 作为观测事实；API 与 worker 分离部署后，进程内队列只允许作为 memory 单元测试口径。

/source/fetch/jobs/{job_item_id}/heartbeat
  worker 长任务续租。没有 heartbeat 的超时任务会被 maintenance 重新入队。

/source/fetch/maintenance/requeue-expired-leases
  重新入队已过 lease_expires_at 的任务，保证 worker 掉线后任务不丢。

/source/fetch/dead-letter
  查看失败超过重试上限且无可用备源的任务。P0/P1 相关死信必须人工处理，不能被模型忽略。

/source/fetch/worker/run-once
  单轮 worker 执行器。正式部署中可由 source-data-worker 容器循环调用。

/source/build/triggers
  raw 抓取成功后生成 source build trigger。source build 必须继续执行 raw quality -> source.* -> source_lineage_v1。
```

### 13.3 新增库表

新增 migration：

```text
infra/sql/0018_source_data_durable_queue_worker_v1.sql
```

新增表：

```text
governance.raw_fetch_idempotency_key_v1
governance.raw_fetch_worker_heartbeat_v1
governance.raw_fetch_dead_letter_v1
```

并增强：

```text
governance.raw_fetch_callback_event_v1
  next_delivery_at
  last_attempted_at
```

关系：

```text
raw_fetch_batch_v1
  一次生产者提交。

raw_fetch_job_item_v1
  一个精确 provider/API/raw_table/request_params 任务。
  `provider + api_name + raw_table_name + request_hash` 是 durable queue 的幂等键。`/source/fetch/submit` 在写入 Postgres 前必须同时检查进程内索引和 Postgres 历史任务；如果同一请求已经存在，不得再次插入任务，也不得把唯一约束异常返回给调用方，必须以 `skipped_duplicate_count` 和 `producer_ack` 形式返回可审计的幂等结果。
  同一 raw 请求可能服务多个目标 source 表。若提交新 `source_table_name/canonical_fields` 时命中已成功的重复 raw job，仍必须为新目标 source 表生成独立 `source_build_trigger_v1`，继续执行 quality/source build/lineage；不得因为 raw fetch 去重而跳过新 source 表构建。

raw_<provider>.<api>_v1
  每行 provider 原接口数据必须物理保留 `request_hash`、`response_schema_hash`、`response_row_hash`、`request_params_json`、`captured_at` 和 `available_at`；`request_hash` 不能只存在于 fetch job 或 raw write audit 中。0020 会对历史 raw 表执行幂等 ALTER，补齐 DS-6 真实回放和行级审计所需字段。

raw_fetch_idempotency_key_v1
  防止调度、巡检、模型重复提交同一任务。

raw_fetch_worker_heartbeat_v1
  记录 worker 存活、当前任务、最近心跳。`source-data-worker` 循环启动、空闲轮询、任务处理开始和单轮结束时都会 upsert 本表；处理任务时 `current_job_item_id` 指向当前 job，空闲时置为 `NULL`、`status=alive`。长任务开始 provider 请求前还会调用 job heartbeat 续租，保证 lease 和 worker 存活两条审计线都可观测。

raw_fetch_dead_letter_v1
  记录最终失败且需要人工处理的任务。

raw_fetch_callback_event_v1
  任务状态 outbox。下游 callback 失败时不得丢状态。

source_build_trigger_v1
  raw 成功后的标准表构建触发器。
  真实 source build 执行时必须把 trigger 状态从 `queued` 推进到 `running`，完成后回写 `succeeded` 或 `failed` 以及 `finished_at`；`source_build_execution_result_v1` 成功但 trigger 仍停留 `queued` 属于未闭环审计缺陷。`dry_run=true` 只验证构建路径，不消费真实 trigger。
  worker 领取 trigger 前必须先读取 `source_build_execution_result_v1`，已有 `succeeded/failed/dry_run/skipped_no_raw` 终态结果的 trigger 不得重复构建。0020 会以 durable successful build result 为权威，修复历史上因 API/worker 内存分离导致的 trigger `queued/failed` 陈旧状态。

source_lineage_v1
  每个 canonical field 的 lineage 必须记录 raw_table/raw_id、provider/api、build_batch_id、confidence_score、`request_hash` 和 `response_row_hash`。API 读取 lineage 时不得把这两个 hash 置空；否则无法从 source 字段反查同一次 provider request 和原始 response row。
```

### 13.4 Docker 部署变化

Compose 新增：

```text
source-data-worker
```

`source-data-service` 负责 API、计划、任务提交、状态查询；`source-data-worker` 负责消费任务、调用 provider、回写状态。两者使用同一份 `source-data-service` 代码包，但作为两个容器运行，避免抓取任务阻塞 API 服务。

生产环境必须设置：

```text
SOURCE_DATA_QUEUE_BACKEND=postgres
SOURCE_DATA_DATABASE_URL=${AI_STOCK_DATABASE_URL}
```

Docker 构建 `source-data-service` 与 `source-data-worker` 时必须安装 `services/source-data-service[providers]`，确保 BaoStock、AKShare、Tushare adapter 在容器内具备真实 provider 包；`requests` 是 Tencent、Sohu、EastMoney、Baidu 等公开 Web adapter 的直接运行依赖，必须由基础依赖显式安装，不能依赖传递依赖碰运气。其他服务不得默认安装 provider extras。

`SOURCE_DATA_WORKER_DRY_RUN_PROVIDER=true` 只用于队列合同单元验收；本地 Docker 发布验证与生产候选验证必须使用 `SOURCE_DATA_WORKER_DRY_RUN_PROVIDER=false`，由 worker 真实调用 provider。

当前 DS-7 实现要求 `/source/fetch/submit` 在 Postgres 队列中先持久化 `raw_fetch_batch_v1`，再写入 `raw_fetch_job_item_v1`，最后回写 batch 计数和状态，避免 job 外键指向尚未落库的 batch。

`/source/fetch/persistence/status` 与 `/source/fetch/queues/summary` 在 Postgres 队列 ready 时必须从 durable queue 读取 active batch、queued、leased、dead-letter 和分队列状态，避免 API 容器重启、worker 独立消费或零任务 batch 导致内存态与数据库事实不一致。内存态只服务 `SOURCE_DATA_QUEUE_BACKEND=memory` 的本地单元测试。

`/source/fetch/batches/{fetch_batch_id}`、`/source/fetch/jobs/{job_item_id}`、`/source/build/triggers` 和 `/source/build/results` 在 Postgres 队列 ready 时也必须优先读取 durable queue / build 表，不能读取 API 容器进程内状态作为生产事实。batch 状态必须从 job item 当前状态派生；如果历史 API 内存态曾把已完成 batch 回写成 `queued`，查询端必须以 job 表事实自修正为 `succeeded`、`running`、`completed_with_errors` 或 `cancelled`。source build worker 只消费 `queued` trigger，禁止因 durable trigger 列表包含历史 `succeeded` 记录而重复构建。

Postgres durable job state 是 worker 租约和终态事实的权威。API/worker 进程内 `_JOBS` 行只允许作为本地缓存；当 `_get_fetch_job_for_update` 发现 Postgres durable 行更新时间更新时，必须用 durable 行刷新缓存。`complete_fetch_job` 完成终态后必须清空 `worker_id`，避免后续观测把已完成任务误判为仍被租赁。Postgres `upsert_job` 只能用 `EXCLUDED.updated_at >= current.updated_at` 的新事实覆盖旧事实，禁止陈旧的内存 queued 行把已失败、已成功或 dead-letter 的 durable 终态重新写回 queued，禁止最终失败 backup job 再次被 worker lease。

`source-data-worker` 启动后必须从 Postgres 持久化队列恢复 active batch/job，不依赖 API 容器进程内存。真实 provider job 成功后，worker 必须先通过 raw repository 写入对应 `raw_<provider>.<api>_v1`，再完成 job 并生成 `source_build_trigger_v1`；随后继续推进 source build，把 canonical row 写入 `source.*` 并生成 `governance.source_lineage_v1`。`/source/probe` 的真实探针结果必须写入 `governance.source_probe_result_v1` 作为 provider 可用性证据。

`/source/ops/production-readiness` 的 real provider probe 证据使用 72 小时 recent usable 窗口：每个 required probe 只要在窗口内存在 `usable=true` 的真实观测，就可作为生产 readiness 可用证据；若窗口内没有 usable 观测则必须 blocked。接口仍必须返回 `latest_observed_results`，保留最新失败、零行或异常观测用于审计；最新失败观测不得被删除、隐藏或改写为成功，但也不得在已有 recent usable 证据时单独毒化 readiness。

`source-data-worker` 的运行状态不得只依赖容器日志判断。worker 每轮必须写 `governance.raw_fetch_worker_heartbeat_v1`：启动 / 空闲轮询为 `status=alive,current_job_item_id=NULL`，处理任务时为 `status=busy,current_job_item_id=<job_item_id>`，单轮完成后恢复 alive；对单个 job 发起真实 provider 请求前必须执行 job heartbeat 续租并产生 `job_heartbeat` callback event。若心跳表长时间无 `last_seen_at` 更新，即使容器仍 Up，也应由巡检或人工按 worker 消费阻断处理。

### 13.5 拍板标准

DS-5 代码级可拍板的范围：

```text
1. 任务分类、任务优先级、队列状态、worker lease、heartbeat、过期重排、取消、callback outbox、source build trigger 的接口合同可锁定。
2. Postgres 持久化表结构和字段注释可锁定。
3. Docker 中 source-data-service + source-data-worker 的拆分方式可锁定。
4. 普通调度、巡检补采、模型临时请求、release preflight、人工回补、provider probe 都必须走统一 fetch orchestration。
```

正式生产拍板还需要在你的环境完成：

```text
1. docker compose build source-data-service source-data-worker schema-bootstrap
2. docker compose up -d postgres schema-bootstrap source-data-service source-data-worker
3. GET /source/fetch/persistence/status 返回 backend=postgres 且 ready_for_production_queue=true
4. 提交 scheduled_periodic / gap_repair / model_adhoc_request / provider_probe 四类任务
5. worker 能领取任务、heartbeat、完成任务，并生成 source_build_trigger_v1
6. 人为停止 worker 后，lease 到期任务能 requeue
7. 主源失败时备源任务自动入队
8. callback outbox 不丢事件
9. P0 任务不会被 backfill / research 队列阻塞
10. 真实 provider dry-run 与 real-run 均有 batch/job/callback/source-build-trigger 审计记录
```

## 14. DS-6 raw 写入、source build、lineage、freshness、coverage 与 release preflight 闭环

DS-6 的目标是让数据源服务具备正式上线前的最后一层运行闭环：抓取任务完成后，不停留在“任务成功”，而是必须完成 raw 原接口结果入库、质量门禁、source 标准表构建、字段血缘写入、及时性检查、容量策略检查、模型覆盖度检查和 release_gate 前置判断。

### 14.1 raw 真实写入

接口：

```text
POST /source/raw/ingest-result
GET  /source/repository/status
```

要求：

```text
1. 每个 provider/API 返回结果必须写到对应 raw_<provider>.<api>_v1 原接口表。
2. 每行 raw 必须保留 request_params、request_hash、response_schema_hash、response_row_hash、captured_at、available_at。
3. response_schema_hash 变化时不得直接进入 source build，必须先检查 field mapping。
4. 同一 request_hash + response_row_hash 重复写入必须幂等，不得重复污染 raw 表。
```

### 14.2 source build 与 lineage

接口：

```text
POST /source/build/triggers/{trigger_id}/execute
POST /source/build/worker/run-once
GET  /source/build/results
GET  /source/rows
GET  /source/lineage/records
```

执行顺序：

```text
source_build_trigger
-> 查找 raw rows
-> raw schema/quality 校验
-> provider 字段映射到 canonical source field
-> upsert source.*
-> 写 governance.source_lineage_v1
-> 记录 governance.source_build_execution_result_v1
```

硬标准：没有 lineage 的 source 字段不得供模型 official release 使用。

当前 canonical build 口径：

- `source.daily_bar_v1` 由 BaoStock raw 日 K `open/high/low/close/preclose/volume/amount/pctChg/turn` 构建；Tencent backup 只承担 OHLC/volume；Sohu backup 承担 `amount/pct_chg/turnover_rate`。
- `source.adjusted_daily_bar_v1` 由 BaoStock qfq 日 K `open/high/low/close/volume/amount` 构建；Tencent qfq backup 只承担 adjusted OHLC/volume。
- `source.trade_status_v1` 由 BaoStock raw 日 K真实字段 `tradestatus/isST` 构建，标准字段为 `is_tradable`、`is_suspended`、`is_st`、`raw_status`。`tradestatus=1` 才能生成 `is_tradable=true` 和 `is_suspended=false`；字段缺失或无法解析时保留缺口并阻断 release preflight，禁止默认当作可交易。
- 每个 canonical 字段都必须写 `governance.source_lineage_v1`。trade status 也必须追溯到 `raw_baostock.query_history_k_data_plus_daily_raw_v1` 的真实 raw 行，不允许人工写 `source.trade_status_v1` 绕过 raw/source/lineage。

### 14.3 freshness SLA

接口：

```text
GET  /source/freshness/sla
POST /source/freshness/status/check
```

用于判断：

```text
1. 数据是否已经到达。
2. 数据是否晚到。
3. 数据是否 stale。
4. late/stale 对模型 release 是阻断还是降级。
```

判定口径：

- 显式传入 `decision_time` 时，source 行必须满足 `available_at <= decision_time` 才算可见；如果真实 source 行在决策时间之后才 available，返回 `late` 并阻断 official release。
- 未传 `decision_time` 的历史或回放交易日，已完成交易日的可用 source 行不再因当前墙钟距离 `available_at` 超过 60/90 分钟而误判 `stale`；只要指定 `trade_date` 的 canonical 字段存在且 source quality 可用，历史事实按 completed trade-date 口径判 fresh。
- 当天 live 数据仍按 SLA 的 `stale_after_minutes` 判断，P0 字段 missing、late 或 stale 都会进入 `blocking_reasons`。

### 14.4 数据量级与存储策略

接口：

```text
GET /source/storage/policies
```

必须声明：

```text
partition_key
partition_granularity
retention_hot_days
archive_enabled
archive_target
required_indexes
expected_daily_rows
expected_total_rows_1y
expected_total_rows_10y
```

特别注意：`governance.source_lineage_v1` 的数据量可能超过行情表，生产必须做索引、分区和冷热归档。

### 14.5 三大模型覆盖度与 release preflight

接口：

```text
GET  /source/models/requirements
POST /source/models/coverage/check
POST /source/release/preflight
```

`/source/release/preflight` 是三大模型 release_gate 前必须调用的统一入口。它同时检查：

```text
1. 模型阶段所需 source 字段覆盖率。
2. P0/P1 字段阻断或降级策略。
3. source 字段 freshness。
4. 缺口字段的 repair route。
```

如果返回 `can_release_official_signal=false`，模型服务不得发布 official signal。
在当前闭环验收标准下，三大模型对应 preflight 必须全部 `can_release_official_signal=true` 且 `blocking_reasons=[]`，任何 blocked 都视为链路未闭环。

### 14.6 DS-6 拍板边界

DS-6 可以拍板：

```text
1. raw->quality->source->lineage->coverage->freshness->preflight 的接口和表结构。
2. 每个任务都有状态、每个 raw/source 写入都有审计、每个 source 字段都有 lineage。
3. 数据源服务作为所有后续服务事实底座的运行合同。
```

仍需真实环境验证：

```text
1. Docker compose 启动 source-data-service + source-data-worker + postgres。
2. schema-bootstrap 执行 0012~0020 migration。
3. BaoStock / Tencent 至少 P0 日 K / qfq / 指数日 K 接口真实网络 probe；AKShare 日 K / qfq / index 接口只在重新取得最新可用 probe 后才能恢复生产主备角色。
4. raw 原接口表真实写入。
5. source 标准表真实写入。
6. governance.source_lineage_v1 真实写入。
7. 连续交易日 preflight blocked/degraded/passed 行为验证。
```

## 15. DS-7 生产拍板验收与真实运行证据

DS-7 的目标是把 DS-6 的闭环从“代码与契约成立”推进到“可以在服务器上按正式上线流程验收”。本阶段新增生产拍板门禁、Postgres raw/source/lineage 持久化实现、HTTP-only 验收脚本和验收证据表。

### 15.1 新增生产拍板门禁接口

```text
GET /source/ops/production-readiness
```

参数：

```text
require_postgres=true|false
require_real_provider_probe=true|false
```

该接口和 `/readyz` 不同：

```text
/readyz 只证明服务进程可用；
/source/ops/production-readiness 用于判断数据源服务能否进入生产候选拍板。
```

检查项包括：

```text
1. provider API registry 是否完整。
2. source field contracts 是否覆盖 P0 字段。
3. source requirements 的 P0/P1 是否有备源。
4. readiness matrix 是否存在 blocked source 表。
5. repair routes 是否可从 source 字段反查 provider/api/raw_table。
6. probe matrix 是否覆盖正式接口实测清单。
7. fetch queue 是否为 Postgres 持久化。
8. raw/source/lineage repository 是否为 Postgres 持久化。
9. queue summary 是否可观测。
10. freshness SLA 是否覆盖 release_gate 字段。
11. storage policy 是否覆盖大表。
12. model source requirements 是否覆盖三大模型阶段。
13. 是否要求真实 provider probe 证据。
```

当 `require_real_provider_probe=true` 时，`real_provider_probe_evidence` 检查会读取 `governance.source_probe_result_v1` 中 `/source/probe` 固化的最新结果；所有 `real_probe_required=true` 的 provider/API 都必须 `connectivity_pass=true`、`schema_pass=true`、`row_count>0`、`usable_for_source_table=true` 且 `usable_for_model_online=true`。缺少 Postgres 证据、缺少某个必需 API 记录或最近记录不可用时，拍板门禁必须 blocked。`real_probe_required=false` 的登记接口仍需在正式进入 online gate、主备源切换、评分、闸门、标签、买点或发布链路之前补真实 probe。

返回 `can拍板=true` 才允许把数据源服务标记为“生产候选可锁定”。

### 15.2 Postgres raw/source/lineage 持久化

DS-7 新增 `postgres_repository.py`，生产环境下：

```text
SOURCE_DATA_QUEUE_BACKEND=postgres
SOURCE_DATA_DATABASE_URL 或 AI_STOCK_DATABASE_URL 必须配置
psycopg 必须可用
```

`/source/raw/ingest-result` 会把 provider 返回行写入对应 raw 原接口表；`source build` 会把 canonical 行写入 `source.*`，并写入：

```text
governance.source_lineage_v1
governance.raw_interface_write_audit_v1
governance.source_build_execution_result_v1
governance.source_canonical_write_audit_v1
```

Postgres source 写入必须同时尊重 canonical 合同和当前物理表事实：

```text
source.adjusted_daily_bar_v1: canonical symbol + trade_date + adjustment_mode(qfq) 对应物理主键。
source.index_daily_bar_v1: 对外仍使用 canonical symbol，例如 399006.SZ；写入物理表时映射为 index_code，冲突键为 index_code + trade_date；/source/rows 读回时再还原 symbol/source_pk=399006.SZ|YYYY-MM-DD。
source.stock_moneyflow_daily_v1: canonical 字段为 main_net_inflow/provider_definition；当前物理主键为 symbol + trade_date + primary_provider，source build upsert 必须带 primary_provider，避免 EastMoney 主源和 Tushare 备源互相覆盖。
source.event_news_v1: canonical 主键为 event_id；Baidu Finance 写入时使用 event_id=baidu:{provider_news_id}，source build upsert 必须写 provider、title、published_at、available_at、event_type/url 和 lineage_id，不能用 symbol + trade_date 伪造事件主键。
source.daily_bar_v1: 当前运行库仍带旧基线物理键 instrument_id + trading_day + adjustment + provider；source build 写入前必须从 core.instrument_master 查到真实 instrument_id，并补齐 trading_day、adjustment=raw、provider、event_time、quality_status。查不到真实 instrument_id 时不得用 0、空字符串或哈希伪造，必须失败并形成可审计错误。
```

上述物理差异不得泄露给模型输入。模型、scheduler、preflight 和外部 API 仍只能读取经过 source build、quality_status、lineage、available_at 校验后的 canonical `source.*` 输出；`source.index_daily_bar_v1` 的 index_code 和 `source.daily_bar_v1` 的旧物理键只属于仓储层适配。

`governance.source_lineage_v1` 写入必须按业务身份幂等。业务身份固定为：

```text
source_table_name
source_pk
canonical_field_name
provider
api_name
raw_table_name
raw_id
request_hash
response_row_hash
```

`lineage_id` 和 `build_batch_id` 不是去重身份；重复 source build、重复 worker callback、验收脚本重跑或同一 raw 行重复触发时，不得因为随机 `lineage_id` 再插入同一业务身份的第二条 lineage。Postgres repository 在同一事务内使用上述业务身份获取 advisory lock，先查已存在 lineage；若存在则复用最早的 `lineage_id`，若不存在才插入新行。带 `lineage_id` 物理列的 source 表必须优先引用已存在的 lineage_id，避免 source 行指向未落库的随机 lineage。历史已经写入的重复 lineage 属审计事实，不由 source build 或 data-inspector 自动删除；巡检可继续报告 `source_lineage_duplicate_observed` warning，但新写入路径必须阻止重复扩大。

source build 读取 Postgres raw 行时必须以 fetch job 的 `provider/api/source_table_name/symbol/trade_date/request_hash` 为边界。部分 raw 表只有 provider 原始 `code`、`provider_code` 或 `secid`，没有 canonical `symbol` 物理列；仓储层即使 SQL 不能直接按 `symbol` 过滤，也必须先把 raw 行和 request params 归一为 canonical symbol/date，再做后置过滤。任何 trigger 重放、验收脚本重跑或 worker 补跑都不得把同一 request_hash、同一日期下其他标的 raw 行混入本 job 的 source build 和 lineage 写入。

注意：memory repository 只允许单元测试，不允许生产运行。

### 15.3 验收脚本

新增：

```text
scripts/source_data_acceptance.py
scripts/core_services_acceptance.py
```

本脚本只通过 HTTP 调用服务，不依赖服务内部代码。建议在服务器上执行：

```bash
python scripts/source_data_acceptance.py \
  --base-url http://127.0.0.1:8041 \
  --require-postgres
```

如果要执行真实 provider probe：

```bash
python scripts/source_data_acceptance.py \
  --base-url http://127.0.0.1:8041 \
  --require-postgres \
  --real-provider-probe \
  --probe-limit 10 \
  --probe-retries 3 \
  --timeout 90
```

如果要把多源同事实质量矩阵纳入同一轮生产验收证据：

```bash
python scripts/source_data_acceptance.py \
  --base-url http://127.0.0.1:8041 \
  --require-postgres \
  --quality-matrix \
  --quality-matrix-symbol 000063.SZ,000001.SZ,600000.SH \
  --quality-matrix-trade-date 2026-06-12
```

脚本覆盖：

```text
healthz
readyz
repository status
queue persistence
repair routes
fetch submit
worker run-once
queue summary
source build trigger
source build dry-run
production readiness gate
provider real probe（可选）
multi-source quality matrix（可选）
acceptance evidence persist
```

`source build dry-run` 只允许作为只读验收动作：可以返回本次会处理哪些 trigger、是否找到 raw rows 以及会产生哪些 warning，但不得把真实 `source_build_trigger` 从 `queued` 改成 `failed/succeeded`，也不得写入 `governance.source_build_execution_result_v1`。同一 `fetch_batch_id + job_item_id + source_table_name + symbol + trade_date + build_scope` 已经存在 `queued/running/succeeded` trigger 时，重复 `job complete` 不得再生成第二条 build trigger；同一 batch 内同 key 已经有成功 build result 时，build worker 必须跳过后续重复 queued trigger，避免 dry-run 或重复回调污染生产审计。不同 batch 复用同一 raw job 时必须重新处理当前 batch 的 trigger。

验收脚本必须可以重复运行。同一 symbol/date/provider/API 的 fetch submit 已经存在时，应返回幂等跳过结果并继续后续 queue、worker、build、readiness 检查；重复 `request_hash` 不得造成 404/500 或阻断生产验收。
脚本结束前必须通过 `POST /source/ops/acceptance-runs` 固化本次验收运行和单项检查证据；当传入 `--require-postgres` 时，若证据未写入 `governance.source_data_acceptance_*`，脚本必须返回非 0，不能只把验收结果留在 stdout。
`--real-provider-probe --probe-limit N` 表示按 probe matrix 执行 `real_probe_required=true` 的真实 provider probe 并作为单项检查落证据；`N<=0` 表示执行全部必需真实 probe，`N>0` 表示只取前 N 个用于抽样。真实 provider probe 使用独立 `--probe-timeout`，默认 120 秒；普通 `/healthz`、`/readyz`、repository、queue 等 HTTP 检查仍使用 `--timeout`，避免 BaoStock `query_all_stock` 等大结果接口被短健康检查窗口误判为不可用。脚本会把 `YYYY-MM-DD` / `YYYYMMDD` 模板替换成 `--trade-date` 指定的真实日期；日线类真实 probe（BaoStock `query_all_stock`、BaoStock raw/qfq 日线、Tencent `daily_bars`、Sohu `daily_bars`）会把当天、未来日期或周末折回到最近已结束工作日样本，避免把尚未形成稳定日线的日期误判为 0 行不可用；分钟线和实时类 probe 保留 `--trade-date` 指定的实时口径。BaoStock `query_adjust_factor` 的验收样例固定使用 `sz.000001` 与 `1990-01-01` 至 `--trade-date` 的长窗口，避免因单只股票短窗口无除权除息记录而把真实可用 API 误判为 schema 不可用。AKShare `stock_zh_a_spot_em`、日 K、qfq 与 index 在最新真实 probe 遇到 EastMoney 远端断开时不再作为 production gate 的 required real probe。正式采集仍必须走 fetch orchestration 和 worker 全量任务，并由 source coverage / freshness 门禁确认全量可用性。全量严格门禁应单独调用 `/source/ops/production-readiness?require_postgres=true&require_real_provider_probe=true`，该接口会要求全部 `real_probe_required=true` 的 API 都有可用的持久化真实 probe 记录。

`--real-provider-probe` 逐项调用真实 provider 时会按 `--probe-retries` 做有限重试，并把每次尝试记录到该 provider/API 的 `_acceptance_attempts` 证据中。远端偶发断连、限流或超时不会提前中断整轮脚本，但最终仍以最后一次可用真实 probe 为准；如果某个必需 API 在所有尝试后仍不可用，`real_provider_probe` 检查保持 blocked，脚本返回非 0。生产锁定仍以 `/source/ops/production-readiness?require_postgres=true&require_real_provider_probe=true` 读取 Postgres 中固化的全部必需 probe 证据为准。
`--quality-matrix` 会逐项调用 `/source/quality/multi-source/check` 并把 `quality_matrix` 作为验收检查项写入 `governance.source_data_acceptance_*`。默认矩阵覆盖 `source.daily_bar_v1` 与 `source.adjusted_daily_bar_v1`；可通过 `--quality-matrix-symbol`、`--quality-matrix-trade-date` 和 `--quality-matrix-table daily|adjusted|index|source.daily_bar_v1|source.adjusted_daily_bar_v1|source.index_daily_bar_v1` 扩展。任一矩阵项 blocked，或 warning 且未传 `--quality-matrix-allow-warning`，脚本必须返回非 0。该检查仍只用于审计和准入，不允许替代 raw/source/lineage 正规写入链路。

`scripts/core_services_acceptance.py` 是数据源服务、三大模型 owner service、模型四、data-inspector-service 和 scheduler-service 的跨服务闭环验收脚本。它仍然只通过 HTTP 调用服务，不直接访问数据库，不直接并发调用 BaoStock、AKShare、Tencent、Tushare、EastMoney、Baidu 或 CNINFO，也不重启任何容器。数据源侧检查包括 `/source/ops/production-readiness`、Postgres repository、Postgres fetch queue、`/source/fetch/queues/summary`、dead-letter、probe matrix 中所有 `real_probe_required=true` 的必需真实 probe 证据、`source.adjusted_daily_bar_v1` source row、`/source/lineage/records`、三大模型当前 source preflight 合同和模型四 Day1/Day2 source preflight 合同。

推荐执行：

```bash
python scripts/core_services_acceptance.py --require-postgres
```

最高规格真实 provider probe 证据执行：

```bash
python scripts/core_services_acceptance.py --require-postgres --real-provider-probe
```

`--real-provider-probe` 在核心闭环脚本中要求 `/source/ops/production-readiness?require_real_provider_probe=true` 通过，并逐项读取 `/source/probe/results` 中已固化的最新真实 probe 证据；它不重复直接打外部 provider。真实外部重探和证据固化由 `scripts/source_data_acceptance.py --require-postgres --real-provider-probe --probe-limit 0` 执行。若确需在核心脚本中再次重探，追加 `--force-live-provider-probe`。

脚本默认输出 compact evidence：source row 只展示关键 source 字段和质量状态，lineage 只展示关键字段的 provider/API/raw 表指针，probe matrix 展示当前所有 `real_probe_required=true` 的必需 provider/API 摘要。需要审计完整 HTTP 响应时追加 `--verbose-evidence`。compact 只收敛 stdout，不改变 raw/source/lineage、preflight、production-readiness 或真实 provider probe 的通过标准。

跨服务脚本中的 scheduler sample payload 只用于 live-dispatch 请求体包装和三模型 owner API 连通性验证，不是市场事实、provider 响应、source row 或 lineage 证据；source 事实必须来自本服务的 `/source/rows`、`/source/lineage/records` 和 `/source/release/preflight`。

### 15.4 新增验收证据表

```text
infra/sql/0020_source_data_production_readiness_v1.sql
```

新增：

```text
governance.source_data_acceptance_run_v1
governance.source_data_acceptance_check_v1
```

用途：保存生产验收运行和单项检查证据。后续 CI/CD 或人工上线验收必须把脚本输出固化到这两张表或等价审计系统中。

服务 API：

```text
POST /source/ops/acceptance-runs
GET  /source/ops/acceptance-runs
GET  /source/ops/acceptance-runs/{acceptance_run_id}
```

`POST /source/ops/acceptance-runs` 是 HTTP-only 验收脚本的唯一正规落库入口。写入内容包括 `base_url`、`require_postgres`、`require_real_provider_probe`、整体验收状态、是否可锁定、阻断原因、warning 原因和每个检查项的 evidence JSON。Postgres 未配置时接口会返回 `persisted=false`，只允许本地合同测试；生产验收必须返回 `persisted=true`。

### 15.5 DS-7 可拍板范围

可以拍板：

```text
1. 生产-消费-状态回调的数据抓取模式。
2. provider/API 级限流、任务分级、备源任务排队。
3. Postgres 持久化队列合同。
4. Postgres raw/source/lineage 写入实现路径。
5. source build、freshness、storage、model coverage、release preflight 的统一门禁。
6. 生产拍板验收接口和 HTTP-only 验收脚本。
```

仍需在目标服务器执行后才能最终锁定生产：

```text
1. docker compose build / up。
2. schema-bootstrap 执行 0012~0020 migration。
3. /source/ops/production-readiness?require_postgres=true 返回 passed。
4. scripts/source_data_acceptance.py --require-postgres 返回 0。
5. 至少完成 probe matrix 中全部 `real_probe_required=true` 接口真实 probe：BaoStock P0 基础源、Tencent `daily_bars` 日 K/qfq/index 替代源、Sohu `daily_bars` 个股 `amount/pct_chg/turnover_rate` 备源，以及模型四所需 EastMoney `quote_snapshot/minute_bars/trade_details`。AKShare/EastMoney 日K类和 spot 包装接口在最新真实 probe 不可用时不再阻断生产闭环；Baidu `finance_news_feed` 属 research-only 事件证据源，需真实 probe 和 raw/source/lineage 写入后才能对外声明事件源闭环。
6. raw/source/lineage 真实写入后，/source/release/preflight 对缺失和完整样本分别返回 blocked/passed 或 degraded。
7. source-data-worker 连续运行，任务 lease/heartbeat/requeue/dead-letter 均可观测。
```

2026-06-13 本地 Docker 闭环实测结果：

```text
docker compose -f infra/docker-compose.yml build source-data-service source-data-worker
docker compose -f infra/docker-compose.yml up -d --no-deps --force-recreate source-data-service source-data-worker
GET /source/ops/production-readiness?require_postgres=true&require_real_provider_probe=true -> status=passed, can拍板=true
python scripts/source_data_acceptance.py --base-url http://127.0.0.1:8041 --require-postgres --real-provider-probe --probe-retries 3 --timeout 8 --probe-timeout 120 -> exit 0, persisted=true
python scripts/core_services_acceptance.py --require-postgres --real-provider-probe --probe-attempts 2 --timeout 90 -> exit 0, status=passed
```

2026-06-14 本地运行容器复核：

```text
python scripts/source_data_acceptance.py --base-url http://127.0.0.1:8041 --require-postgres --real-provider-probe --probe-limit 0 --probe-retries 3 --timeout 90 --probe-timeout 120 --quality-matrix --quality-matrix-symbol 000063.SZ,000001.SZ,600000.SH --quality-matrix-trade-date 2026-06-12 --quality-matrix-timeout 180
  -> exit 0, persisted=true
  -> real_provider_probe required_count=7, usable_count=7
  -> quality_matrix entry_count=6, passed_count=6, warning_count=0, blocked_count=0

GET /source/ops/production-readiness?require_postgres=true&require_real_provider_probe=true
  -> status=passed, can拍板=true, warning_reasons=[]

python scripts/core_services_acceptance.py --require-postgres --real-provider-probe --probe-attempts 2 --timeout 120 --source-quality-matrix --source-quality-symbol 000063.SZ,000001.SZ,600000.SH --source-quality-trade-date 2026-06-12 --source-quality-timeout 180
  -> exit 0, status=passed
  -> source release preflight 3/3 passed
  -> scheduler live dispatch 3/3 accepted
  -> source quality matrix 6/6 passed
```

2026-06-17 首次上线重建后复核与冻结证据：

```text
Docker 镜像：
  infra-source-data-service:latest -> c7fbfcc57cec
  infra-source-data-worker:latest -> 2a7c1df99784
  infra-schema-bootstrap:latest -> a4a7f8ede9f8

schema-bootstrap:
  docker compose -f infra/docker-compose.yml up -d --force-recreate schema-bootstrap source-data-service source-data-worker
  -> schema-bootstrap exited 0
  -> applied 24 SQL migration files
  -> source-data-service /readyz ready
  -> source-data-worker running

source.trade_calendar_v1 首次上线兼容：
  - 旧物理表若只有 trading_day/is_open/prev_trading_day，0025 会幂等补齐 current contract 字段 calendar_date/is_trading_day/exchange/pretrade_date/source_quality_status/primary_provider/backup_provider/lineage_id/build_batch_id/captured_at/available_at。
  - Postgres repository 写入时会按当前字段合同映射到旧物理键 trading_day + market_code，不向 API 或模型泄露旧物理键。

验收：
  python scripts/source_data_acceptance.py --base-url http://127.0.0.1:8041 --require-postgres --real-provider-probe --probe-limit 0 --quality-matrix --symbol 000759.SZ --trade-date 2026-06-17 --quality-matrix-symbol 000063.SZ,000001.SZ,600000.SH,000759.SZ --quality-matrix-trade-date 2026-06-12 --quality-matrix-table daily --quality-matrix-table adjusted --timeout 15 --probe-timeout 180 --probe-retries 3 --quality-matrix-timeout 240
    -> exit 0
    -> acceptance_run_id=acceptance_92b1fd11770b421d8cf7
    -> status=passed, can_lock_candidate=true, blocking_reasons=[], warning_reasons=[]
    -> real_provider_probe required_count=15, usable_count=15
    -> quality_matrix entry_count=8, passed_count=8, warning_count=0, blocked_count=0

GET /source/ops/production-readiness?require_postgres=true&require_real_provider_probe=true
  -> status=passed, can拍板=true
  -> field_contract_count=63, p0_contract_count=41
  -> source_requirement_count=63
  -> probe_api_count=58, real_probe_required_count=15
  -> durable queue backend=postgres
  -> raw_row_count=272216, source_row_count=4827, lineage_row_count=29582
  -> queued_jobs=0, leased_jobs=0, dead_letter_count=0

跨服务闭环：
  python scripts/core_services_acceptance.py --require-postgres --real-provider-probe --source-quality-matrix --source-quality-symbol 000063.SZ,000001.SZ,600000.SH,000759.SZ --source-quality-trade-date 2026-06-12 --source-quality-table daily --source-quality-table adjusted --timeout 30 --source-quality-timeout 240
    -> exit 0, status=passed, required_failed=[]
  data-inspector core_closure run_id=2085
    -> status=ready, p0_gap_count=0, p1_gap_count=0, gap_count=0
  scheduler-service /readyz
    -> status=ready, startup_guard run_id=2084 ready, latest_core_closure run_id=2085 ready
```

冻结对象：

| 服务 -> 模块 -> 功能 | 冻结时间 | 确认来源 | 锁定范围 | 允许的只读验收 | 禁止修改项 | 解锁条件 | 回滚方式 | 验证清单 |
|---|---|---|---|---|---|---|---|---|
| `source-data-service -> DS-7 production readiness -> real probe + quality matrix gate` | 2026-06-17 16:07 Asia/Shanghai | 用户本轮确认按任务书执行，并于 2026-06-17 明确确认“数据源服务稳定后可以冻结” | `/source/ops/production-readiness`、`/source/probe/matrix`、`/source/probe/results`、`/source/quality/multi-source/check`、`governance.source_data_acceptance_*` | `/healthz`、`/readyz`、`/source/ops/production-readiness`、`scripts/source_data_acceptance.py`、`scripts/core_services_acceptance.py` | 未获解锁不得改 provider required probe 清单、production readiness 判定、验收脚本通过标准、质量矩阵阻断规则 | 任一 P0 provider probe 持续不可用、quality_matrix blocked、readiness blocked 或用户明确批准 | 恢复到上一版 source-data 镜像和 schema-bootstrap SQL；保留 Postgres 审计证据，不清库 | readiness passed；acceptance `acceptance_92b1fd11770b421d8cf7` passed；core acceptance passed |
| `source-data-service -> source foundation schema -> 0025 source indexes and trade calendar hardening` | 2026-06-17 16:07 Asia/Shanghai | 同上 | `infra/sql/0025_source_data_foundation_indexes_v1.sql`、`infra/sql/bootstrap_schema.sql` 中 source foundation 索引、注释、trade_calendar current columns | 只读 `information_schema` / `pg_indexes` / `COMMENT` 查询、schema-bootstrap 重跑观察 | 未获解锁不得删除索引、降低字段约束、绕过 current contract 字段、重命名表/列或清理历史数据 | schema-bootstrap 失败、查询计划退化、字段合同不可见或用户明确批准 | 还原 SQL 与镜像，重跑 schema-bootstrap；保留已写入 source/raw/lineage | schema-bootstrap exited 0；trade_calendar current columns visible；索引存在 |
| `source-data-worker -> postgres queue consumer -> raw/source/lineage callback closure` | 2026-06-17 16:07 Asia/Shanghai | 同上 | Postgres queue backend、worker pull/heartbeat/complete、raw ingest、source build trigger、callback/outbox | 队列 summary、worker logs、`/source/fetch/persistence/status`、dry-run worker/build | 未获解锁不得改 worker 消费状态机、lease/heartbeat、dead-letter、callback/outbox 或 raw/source/lineage 写入边界 | dead-letter 非空、lease 卡死、worker 不 heartbeat 或用户明确批准 | 回退 worker 镜像；保留 queue/outbox 审计，按 request_hash 重排任务 | queue backend postgres；queued=0；leased=0；dead_letter=0 |
| `source-data-worker -> source foundation build -> trade_calendar and stock_master mapping` | 2026-06-17 23:08 Asia/Shanghai | 用户批准定向解锁；此前用户授权“你认为可以冻结就行” | BaoStock `query_trade_dates` / `query_stock_basic` 到 `source.trade_calendar_v1`、`source.stock_master_v1` 的 build mapping、source_pk、lineage、raw_request_hash 持久化重放 | 只读 SQL 行数、`/source/rows`、`/source/lineage/records`、`/source/ops/production-readiness`、worker logs | 未获解锁不得绕过 raw/source/lineage、不得手写 source 表、不得把 2027 缺口伪装为已补齐、不得重启 `source-data-service` API | calendar/source master build failed、lineage 缺失、provider 返回范围变化或用户明确批准 | 回退 `source-data-worker` 镜像；保留 raw/source/lineage 审计，按 request_hash 重排 source build | `source.trade_calendar_v1=365`、`source.stock_master_v1=2`、calendar lineage=1460、stock_master lineage=16；source/scheduler/data-inspector ready |
| `source-data-service -> fetch orchestration -> zero-row backup guard` | 2026-06-18 03:44 Asia/Shanghai | 用户本轮批准 | P0/P1 fetch job 零行保护、历史无 raw hash 成功 job 的备源重排、已存在终态不可用 backup job 复用重排、`source.minute_bar_v1 / 000063.SZ / 2026-06-12` 真实缺口阻断 | `/source/fetch/queues/summary`、`/source/ops/production-readiness`、`scripts/source_data_acceptance.py --require-postgres`、no-persist scheduler assemble-preflight、只读 raw/source/lineage 查询 | 未获解锁不得把 provider 零行标记为成功、不得跳过 backup、不得重复插入同 request_hash backup job、不得手写 raw/source/lineage 补事实、不得绕过 `source_gap:minute_bar_missing` 阻断 | 新 provider 覆盖该分钟线缺口、queue/retry/dead-letter 异常、preflight 阻断规则误判或用户明确批准 | 回退 source-data API/worker 镜像；保留现有 queue/callback/raw/source/lineage 审计，按 fetch_batch/request_hash 重排 | 单测 `89 passed`；readiness passed；acceptance `acceptance_7e7560c4660f4e0186bb` passed；queue queued=0/leased=0/dead_letter=0；scheduler/data-inspector ready；minute bar 缺口保留为真实 `source_gap:minute_bar_missing` |
| `source-data-service -> fetch orchestration -> failed duplicate request_hash requeue/backup` | 2026-06-18 17:01 Asia/Shanghai | 用户在交付报告拍板请求后回复“继续” | 历史 `failed/cancelled/dead_letter` 同 raw `request_hash` 不再静默 skip；当前 planned `source_table_name/canonical_fields` 驱动备源排队或旧 job 重排；复用旧 job 时通过 `__source_build_aliases` 为当前 source 表补建 build trigger | `/source/fetch/queues/summary`、`/source/ops/production-readiness`、`scripts/source_data_acceptance.py --require-postgres`、`/source/fetch/plan` P0 dry-run、容器内代码只读确认、scheduler/data-inspector `/readyz` | 未获解锁不得把失败终态 request_hash 当作已完成 duplicate；不得移除 alias trigger；不得让 scheduler/research/model 绕过 fetch orchestration；不得手写 raw/source/lineage 补事实；不得重启非本功能所需服务 | queue/retry/dead-letter 异常、alias build trigger 漏建、request_hash 唯一约束冲突、source preflight 误阻断/漏阻断，或用户明确批准 | 回退 `infra-source-data-service` 到上一镜像并 `docker compose -f infra/docker-compose.yml up -d --no-deps source-data-service`；保留 Postgres queue/callback/raw/source/lineage 审计，不清库 | duplicate 单测 `4 passed`；source-data-service 单测 `90 passed`；镜像 `infra-source-data-service:latest=d04d1fde123f`；readiness passed；acceptance `acceptance_b2d2f9b3d1c4422fa0a5` passed；queue queued=0/leased=0/dead_letter=0；scheduler/data-inspector ready |
| `source-data-service -> fetch orchestration -> universe_scope full A/stage candidates` | 2026-06-22 Asia/Shanghai | 用户本轮确认“继续；如果迭代完成，优先冻结数据源并重启数据源服务，确保容器是最新的代码” | `FetchUniverseScope`、`FetchPlanRequest.universe_scope`、`full_a_share` 从 `source.stock_universe_daily_v1` / `source.stock_master_v1` 展开、市场批接口不逐股展开、`stage_candidates` 必须由上游阶段候选传入、禁止样本 fallback | `/source/fetch/plan` dry-run、`/source/fetch/queues/summary`、`/source/ops/production-readiness`、source 单测、scheduler/data-inspector `/readyz` | 未获解锁不得恢复 `000759.SZ` / `000063.SZ` 样本兜底，不得让全 A 日频继承配置样本，不得把分钟/逐笔做成全 A 常规调度，不得让 source-data-service 自行生成模型候选 | 全 A universe source 为空、stage candidate 来源合同变化、fetch plan 漏展/误展、provider 批接口合同变化、队列/readyz 阻断或用户明确批准 | 回退 source-data-service/source-data-worker 镜像到上一版本；保留 Postgres queue/raw/source/lineage 审计，不清库；按 request_hash 重排必要任务 | source 定向单测 `13 passed`；scheduler source schedule 单测 `7 passed`；runtime guard `14 passed`；重启前 source/scheduler/data-inspector ready；source queues queued=0/leased=0/dead_letter=0 |
| `source-data-worker -> source build worker -> fetch_batch scoped trigger dedupe` | 2026-06-22 Asia/Shanghai | 用户批准继续闭环，且此前授权“你认为可以冻结就行” | `_build_trigger_key(fetch_batch_id, job_item_id, source_table_name, symbol, trade_date, build_scope)`；新 catch-up batch 复用历史 raw job 时必须重新执行当前 batch 的 source build、lineage 和清污逻辑 | 只读查询 `governance.source_build_trigger_v1`、`governance.source_lineage_v1`、`/source/build/triggers`、source 单测、容器内代码探针 | 未获解锁不得移除 `fetch_batch_id` 去重维度；不得因旧 batch 已有 succeeded trigger 跳过新 batch；不得手写 source 表绕过 build worker | 新 batch 被旧 trigger 阻断、lineage 漏写、duplicate request_hash 复用语义变化、或用户明确批准 | 回退 source-data-service/source-data-worker 镜像到上一版本；保留 raw/job/build/lineage 审计，不清库；按 fetch_batch 重排 build trigger | `source_build_trigger_60154f60991c44608ef6` succeeded；`raw_row_count=7269`、`source_row_count=5207`、`lineage_row_count=15621`；source 单测 `112 passed`；acceptance `acceptance_ab68236b2e764b85b768` passed |
| `source-data-worker -> source build worker -> idle queued trigger drain` | 2026-06-23 Asia/Shanghai | 用户批准继续闭环，且此前授权“你认为可以冻结就行” | `run_worker_once` 在没有 raw job 可租赁且 `dry_run_provider=false` 时调用 source build worker；catch-up 只复用历史 raw job 时，queued `source_build_trigger` 不得滞留 | 只读查询 `governance.source_build_trigger_v1`、65 候选四表覆盖 SQL、`/source/release/preflight`、scheduler assemble-preflight、source 单测、容器内代码探针、acceptance 脚本 | 未获解锁不得移除 idle drain；不得让 alias-only/catch-up trigger 依赖下一次 raw job 成功才执行；不得手写 `source.*` 或绕过 raw/source/lineage；不得启动模型服务替代数据源修复 | queued trigger 再次滞留、worker 空闲不消费、source 覆盖回退、freshness/coverage 误判、或用户明确批准 | 回退到 `infra-source-data-service:rollback-20260623-idle-build-drain` 与 `infra-source-data-worker:rollback-20260623-idle-build-drain`；保留 raw/job/build/lineage 审计，不清库；必要时按 fetch_batch 重排 build trigger | target tests `2 passed`；source-data tests `114 passed`；new images `source-data-service=ff2074eada0d`、`source-data-worker=a956048e970d`；`2026-06-22` Model 4 Day1 candidates 65/65 for daily_bar/limit_price/realtime_quote/trade_status；recent build triggers `succeeded=659`、only 4 old adjusted_daily failures；production-readiness passed；acceptance `acceptance_38ee3197373f4cd196cd` passed；source/scheduler/data-inspector ready |
| `source-data-service -> stock universe build -> full A-share filter and prune` | 2026-06-22 Asia/Shanghai | 同上 | `source.stock_universe_daily_v1` 只保留 A 股股票：沪市 `60*`/`68*`、深市 `00*`/`30*`、provider 返回时的北交所 `4*`/`8*`/`92*`；正式 batch build 成功后清理同交易日非 A 旧行 | 只读 SQL 行数/污染计数、`/source/fetch/plan` full_a_share dry-run、`/source/ops/production-readiness`、acceptance 脚本 | 未获解锁不得把指数、基金、B 股、债券或样本代码写入全 A universe；不得用前端配置或模型候选反推 universe；不得把缺失 `is_tradable` 默认为 true | universe 行数异常、污染计数非零、provider 代码规则变化、full_a_share 展开为空或用户明确批准 | 回退 source-data-service/source-data-worker 镜像；保留 raw/source/lineage 审计；按 `query_all_stock` request_hash 重排 build | `2026-06-22 source.stock_universe_daily_v1=5207`、tradable=5191、not_tradable=16、unknown=0；指数/基金/B 股污染计数=0；production-readiness passed |
| `source-data-service -> acceptance runner -> real probe date semantics and recent evidence gate` | 2026-06-22 Asia/Shanghai | 同上 | `scripts/source_data_acceptance.py` 的 real-provider probe：日线类用已结算交易日，高频/快照类用当前或最近工作日；即时 probe 失败但 `/source/ops/production-readiness` 72h recent usable 通过时验收可通过，并保留即时失败明细 | `scripts/source_data_acceptance.py --require-postgres --real-provider-probe --quality-matrix`、`/source/ops/acceptance-runs`、`/source/probe/results` | 未获解锁不得隐藏即时失败 probe；不得在 recent usable 缺失时放行；不得把非交易日或历史日线口径套到分钟线验收；不得取消质量矩阵阻断 | acceptance blocked、readiness blocked、recent usable 窗口缺失、provider probe 合同变化或用户明确批准 | 回退 acceptance 脚本；保留 `governance.source_data_acceptance_*` 和 `governance.source_probe_result_v1` 证据；重新执行验收 | target tests `2 passed`；source tests `112 passed`；acceptance `acceptance_ab68236b2e764b85b768` passed；latest Tencent minute immediate failure retained as observed audit |
| `source-data-service -> ths paid probability -> cookie/probe/fetch/deadline` | 2026-06-20 Asia/Shanghai | 用户明确说明付费接口需要登录 Cookie，并补充“cookie 失效或取不到就阻断/放弃这一批候选，放弃时间为下一个交易日的9点后” | `ths.paid_limit_up_probability` 唯一登录态例外、`governance.ths_paid_probability_cookie_v1`、`raw_ths.paid_limit_up_probability_v1`、`source.ths_paid_limit_up_probability_v1`、`governance.ths_paid_probability_batch_status_v1`、`/source/ths/paid-probability/*` | Cookie status/probe dry-run、batch-status、deadline-check、source 单测、schema/bootstrap 文本自检 | 未获解锁不得把 Cookie 写入仓库/raw params/log/frontend 响应；不得给付费概率伪造备源；不得把缺失概率补 0/手填/随机；不得在下一交易日 09:00 前放弃候选批次；不得改变其他 THS public no-cookie 接口 | 付费接口合同变化、Cookie 状态误判、deadline 计算错误、source build/lineage 缺失、或用户明确批准解锁 | 回退 0028 schema/API/provider adapter 相关改动；保留已有 raw/source/governance 审计，不清库；恢复候选页为只读缺口展示 | source 单测 `99 passed`；定向 paid probability 单测 `6 passed`；scheduler/front 合同测试通过；未执行真实付费接口探针，需运行时 Cookie 后验收 |

### 2026-06-20 冻结补充

确认来源：用户此前授权“你认为可以冻结就行”，本轮继续按已批准任务书收口。以下对象在 source 单测、readiness、queue summary、scheduler/data-inspector ready 复核通过后进入冻结候选锁定；未获用户明确解锁前，只允许只读验收、观测和报告整理。

| 服务 -> 模块 -> 功能 | 冻结时间 | 锁定范围 | 允许的只读验收 | 禁止修改项 | 解锁条件 | 回滚方式 | 验证清单 |
|---|---|---|---|---|---|---|---|
| `source-data-service -> fetch orchestration -> durable job state anti-loop` | 2026-06-20 Asia/Shanghai | `_get_fetch_job_for_update` durable refresh、`complete_fetch_job` 清空 `worker_id`、Postgres `upsert_job` 新旧 `updated_at` 覆盖规则、最终失败 backup job 不重复 lease | `/source/fetch/jobs/{job_item_id}`、`/source/fetch/queues/summary`、`/source/fetch/persistence/status`、source 单测 | 未获解锁不得让陈旧进程内 queued 状态覆盖 durable failed/succeeded/dead_letter 终态；不得让已完成 job 残留租约 owner；不得让最终失败 backup 继续被 worker lease | queue 出现重复租赁、陈旧状态复活、failed job 循环重排、worker lease 卡死，或用户明确批准 | 回退 source-data-service/source-data-worker 镜像到上一版本；保留 Postgres queue 审计，不清库；按 `job_item_id/request_hash` 重排需要修复的任务 | source 单测 `102 passed`；queue queued=0、leased=0、dead_letter=0；production-readiness passed；scheduler/data-inspector ready |
| `source-data-service -> provider probe readiness -> 72h usable evidence with observed audit` | 2026-06-20 Asia/Shanghai | `real_probe_evidence_summary`、`/source/ops/production-readiness` 的 72 小时 recent usable 证据窗口、`latest_results` 与 `latest_observed_results` 双轨审计 | `/source/ops/production-readiness?require_postgres=true&require_real_provider_probe=true`、`/source/probe/results`、acceptance 脚本 | 未获解锁不得隐藏最新失败观测；不得把 failed/zero-row probe 改写为 usable；不得在 72 小时窗口无 usable 证据时放行 readiness；不得取消 latest observed 审计字段 | recent usable 证据持续缺失、required probe 合同变化、readiness 漏阻断/误阻断，或用户明确批准 | 回退 source-data-service 镜像；保留 `governance.source_probe_result_v1` 观测记录；重新执行真实 probe 和 readiness 验收 | production-readiness passed；`real_provider_probe_evidence.status=passed`；最新失败观测仍在 `latest_observed_results` 可见 |

真实 provider probe 证据：

```text
BaoStock query_adjust_factor -> row_count=41, usable_for_model_online=true
BaoStock query_all_stock -> row_count=7273, usable_for_model_online=true
BaoStock query_history_k_data_plus_daily_raw -> row_count=1, usable_for_model_online=true
BaoStock query_history_k_data_plus_daily_qfq -> row_count=1, usable_for_model_online=true
BaoStock query_stock_basic -> row_count=1, usable_for_model_online=true
BaoStock query_trade_dates -> row_count=894, usable_for_model_online=true
Tencent daily_bars -> row_count=1, usable_for_model_online=true
```

真实 raw/source/lineage 写入证据：

```text
source.daily_bar_v1 000063.SZ 2026-06-12
  primary_provider=baostock
  open=38.600000 high=38.700000 low=36.150000 close=36.350000
  volume=261471118 amount=9702654429.790000 pct_chg=-3.8614
  source_quality_status=usable build_batch_id=source_build_63a2522dee84

source.adjusted_daily_bar_v1 000063.SZ 2026-06-12
  primary_provider=baostock adjustment_mode=qfq
  adjusted_open=38.6 adjusted_high=38.7 adjusted_low=36.15 adjusted_close=36.35
  volume=261471118 amount=9702654429.79
  lineage fields=adjusted_open,adjusted_high,adjusted_low,adjusted_close,volume,amount
  lineage raw_table=raw_baostock.query_history_k_data_plus_daily_qfq_v1 raw_id=11

source.index_daily_bar_v1 399001.SZ 2026-06-12
  primary_provider=tencent
  close_price=14963.41 pct_chg=0.75 source_quality_status=usable

source.stock_moneyflow_daily_v1 000063.SZ 2026-06-12
  primary_provider=eastmoney
  source_quality_status=usable
  main_net_inflow=-1965310992
  provider_definition=eastmoney_fflow_kline_get:f51=date,f52=main,f53=super_large,f54=large,f55=medium,f56=small
  build_batch_id=source_build_c0a7122c3530
  lineage fields=main_net_inflow,provider_definition
  lineage raw_table=raw_eastmoney.moneyflow_stock_series_v1 raw_id=2

source.event_news_v1 Baidu Finance 2026-06-14
  provider=baidu api_name=finance_news_feed
  fetch_batch_id=fetch_batch_8cc7a0d2230d4b2e88a8 job_item_id=fetch_job_5f10597b8fb7419e942b
  build_batch_id=source_build_1f6e8dbc883a
  raw_row_count=20 source_row_count=20 lineage_row_count=100
  raw_baidu request_hash populated=40/40, request_hash index=idx_raw_baidu_news_request_hash
  sample source_pk=baidu:edf2056057bf7e73fd43ec7ff0fbf7bb
  lineage fields=title,published_at,available_at,event_type,url
  lineage raw_table=raw_baidu.finance_news_feed_v1
```

worker 连续运行证据：

```text
ai-stock-source-data-worker Up 9 minutes after targeted recreate
worker leased_count=1 succeeded_count=1 failed_count=0 generated_build_trigger_count=1
latest completed jobs include:
  fetch_job_5f10597b8fb7419e942b Baidu finance_news_feed event_news
  fetch_job_0443c73c4cd24523b0f9 BaoStock raw daily
  fetch_job_8d182992a2a642fa9efc BaoStock qfq
  fetch_job_b5c84fc7779f44049310 Tencent index daily
/source/fetch/queues/summary -> queued_jobs=0, leased_jobs=0, dead_letter_count=0
```

2026-06-14 heartbeat 加固后，worker 闭环新增实测证据：

```text
docker compose -f infra/docker-compose.yml up -d --build --no-deps source-data-worker
  -> 只重建 source-data-worker；source-data-service API 容器保持 Up 11 hours，未重启。

governance.raw_fetch_worker_heartbeat_v1
  -> worker_id=source-data-worker-1
  -> status=alive
  -> last_seen_at 持续刷新
  -> current_job_item_id=NULL when idle

fetch_batch_ddfef4f1d5c340189c94 provider_probe real worker validation
  -> primary baostock query_history_k_data_plus_daily_raw failed with provider_structured_error
  -> backup tencent daily_bars succeeded
  -> raw_fetch_callback_event_v1 contains job_heartbeat=2, job_leased=2, backup_job_queued=1, source_build_trigger_created=1, job_succeeded=1
```

三模型/调度联调证据：

```text
hot-candidates-service /readyz -> ready
candidate-memory-service /readyz -> ready
ambush-watchlist-service /readyz -> ready
scheduler-service /readyz -> ready, background_loop running
data-inspector-service /readyz -> ready
core_services_acceptance 验证 source row、lineage、三模型 score/phase3 合同和 scheduler live dispatch 均通过。
```

2026-06-14 本地运行容器复核：`scheduler-service /readyz` 的 `closure_guard` 中 `hot_candidates.preopen_release_gate`、`candidate_memory.outcome_label`、`ambush_watchlist.release_gate` 三项 preflight 均为 `can_release_official_signal=true`、`coverage_status=passed`、`freshness_status=passed`，`blocking_reasons=[]`、`degraded_reasons=[]`。后续如遇真实数据缺口，仍必须返回 blocked/degraded/gap，不允许用 0、空字符串、mock 或 GPT 推断补齐。

2026-06-14 追加真实闭环复核与修复证据：

```text
代码合同修正：
  - EastMoney minute_bars 兼容 YYYY-MM-DD HH:MM 返回，_event_time('09:30') 必须落为 09:30:00，不得回落到 15:00:00。
  - source build 在复用同一个 raw job 给其他 source_table 时，canonical_fields 必须按 trigger.source_table_name 重新取该 source 表字段合同，避免 limit_price raw 被复用于 limit_event 时丢 close_on_limit_flag / limit_open_count。
  - source.limit_event_v1 的 source_pk / Postgres upsert / read identity 必须包含 limit_event_type，物理唯一键为 symbol + trade_date + limit_event_type。
  - t_board_relay 的 P0 source requirement 已包含 source.limit_event_v1.close_on_limit_flag 和 source.limit_event_v1.limit_open_count。

000759.SZ / 2026-06-12 真实 source 补齐：
  - source.trade_status_v1: is_tradable=true, is_suspended=false, is_st=false, raw_status=1, primary_provider=baostock, build_batch_id=source_build_476af93fdc3c。
  - source.adjusted_daily_bar_v1: qfq adjusted_open=5.29, adjusted_high=5.83, adjusted_low=5.16, adjusted_close=5.83, volume=95903200, amount=521672918.98, primary_provider=baostock, build_batch_id=source_build_987e1a948b24。
  - source.stock_moneyflow_daily_v1: main_net_inflow=92712725, provider_definition=eastmoney_fflow_kline_get:f51=date,f52=main,f53=super_large,f54=large,f55=medium,f56=small, primary_provider=eastmoney, build_batch_id=source_build_7f9217cfe9e3。
  - source.limit_event_v1: limit_event_type=t_board_limit_up, is_one_word_board=false, is_break_limit=true, close_on_limit_flag=true, limit_open_count=1。
  - source.minute_bar_v1: 241 rows, bar_time range 2026-06-12 01:30:00+00 to 2026-06-12 07:00:00+00, 10:30 China close_price=5.20。
  - source.trade_tick_v1: 4042 rows, 09:30-10:30 buy-side amount=121998001, buy tick count=528。

000759.SZ raw/source/lineage 验证：
  - raw_baostock.query_history_k_data_plus_daily_qfq_v1 已有 2026-06-12 qfq row，request_hash / response_schema_hash / response_row_hash 均非空。
  - raw_baostock.query_history_k_data_plus_daily_raw_v1、raw_eastmoney.minute_bars_v1、raw_eastmoney.trade_details_v1、raw_eastmoney.quote_snapshot_v1、raw_tencent.daily_bars_v1 均有真实行和 hash。
  - governance.source_lineage_v1 对 adjusted_daily、trade_status、limit_event、limit_price、minute_bar、trade_tick、realtime_quote 等字段均有对应 lineage；新增 adjusted_daily 6 条、trade_status 4 条、stock_moneyflow_daily 2 条 lineage。

三模型 release preflight 复核：
  - POST /source/release/preflight hot_candidates/preopen_release_gate symbols=[000063.SZ,000759.SZ] -> can_release_official_signal=true, coverage_status=passed, freshness_status=passed, blocking_reasons=[], degraded_reasons=[]。
  - POST /source/release/preflight candidate_memory/outcome_label symbols=[000063.SZ,000759.SZ] -> can_release_official_signal=true, coverage_status=passed, freshness_status=passed, blocking_reasons=[], degraded_reasons=[]。
  - POST /source/release/preflight ambush_watchlist/release_gate symbols=[000063.SZ,000759.SZ] -> can_release_official_signal=true, coverage_status=passed, freshness_status=passed, blocking_reasons=[], degraded_reasons=[]。

验收脚本与健康：
  - scripts/source_data_acceptance.py --require-postgres --real-provider-probe --probe-limit 0 --quality-matrix -> exit 0。
  - scripts/source_data_quality_matrix.py --symbol 000063.SZ,000001.SZ,600000.SH,000759.SZ --trade-date 2026-06-12 --table daily --table adjusted -> exit 0。
  - scripts/core_services_acceptance.py --require-postgres --real-provider-probe --source-quality-matrix --source-quality-symbol 000063.SZ,000001.SZ,600000.SH,000759.SZ --source-quality-trade-date 2026-06-12 -> exit 0。
  - source-data-worker 持续运行：ai-stock-source-data-worker Up 31 minutes；governance.raw_fetch_worker_heartbeat_v1 最新 source-data-worker-1 last_seen_at=2026-06-14 15:22:59+00, status=alive, note=worker_cycle_complete。
  - /source/fetch/queues/summary -> all queues queued_count=0, leased_count=0, dead_letter_count=0；repair_queue succeeded_count=6, failed_count=0。
```
