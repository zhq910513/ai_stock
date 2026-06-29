# scripts

## Core Source Quality Matrix Acceptance

`core_services_acceptance.py` supports an optional source quality matrix gate:

```bash
python scripts/core_services_acceptance.py --require-postgres --source-quality-matrix --source-quality-symbol 000063.SZ,000001.SZ,600000.SH --source-quality-trade-date 2026-06-12
```

The gate reads persisted `quality_matrix` evidence from `source-data-service /source/ops/acceptance-runs` by default. That evidence must have been written by `source_data_acceptance.py --quality-matrix`, must cover every requested `symbol + trade_date + source table`, and must be `passed` with no required failures; warnings remain blocking unless `--source-quality-allow-warning` is set. This avoids re-hitting slow external providers inside the full source + model + scheduler closure run while still requiring auditable Postgres evidence. If a live quality check is required, add `--force-live-source-quality-matrix`; the script will then call `/source/quality/multi-source/check` through source-data-service only, without importing provider adapters, directly calling BaoStock, AKShare, Tencent, Sohu, Tushare, EastMoney or CNINFO, or restarting containers.

本目录只保留当前脚本说明文档：`README.md`。脚本不得成为业务事实源；业务合同仍以根目录 `AGENTS.md` 和对应服务根目录 README 为准。

## 生产闭环验收脚本

### `source_data_acceptance.py`

数据源服务 DS-7 HTTP-only 验收入口。它只调用 `source-data-service`，验证：

- `/healthz`、`/readyz`
- Postgres raw/source/lineage repository 状态
- Postgres fetch queue 持久化状态
- repair routes、fetch submit、worker run-once、queue summary
- source build worker dry-run
- `/source/ops/production-readiness`
- 可选真实 provider probe
- 可选多源同事实质量矩阵
- `governance.source_data_acceptance_*` 验收证据持久化

生产候选锁定时至少运行：

```bash
python scripts/source_data_acceptance.py --base-url http://127.0.0.1:8041 --require-postgres
```

需要真实 provider 探针时追加：

```bash
python scripts/source_data_acceptance.py --base-url http://127.0.0.1:8041 --require-postgres --real-provider-probe
```

脚本默认 `--trade-date` 使用最近工作日样例，避免周末或节假日把真实 provider 误判为 0 行不可用；生产验收也可以显式传入交易日。日线类 probe（BaoStock `query_all_stock`、BaoStock raw/qfq 日线、Tencent `daily_bars`、Sohu `daily_bars`）会把当天、未来日期或周末折回到最近已结束工作日样本；分钟线和实时类 probe 保留 `--trade-date` 指定口径。`--real-provider-probe` 会执行全部 `real_probe_required=true` 的 provider/API；如需抽样可传 `--probe-limit N`，`N<=0` 表示全部。真实 provider probe 使用独立的 `--probe-timeout`，默认 120 秒，避免 BaoStock `query_all_stock` 这类大结果接口被普通 HTTP 健康检查的短超时误判。当前真实门禁以 BaoStock P0 基础源、Tencent `daily_bars` 日 K/qfq/index 替代源、Sohu `daily_bars` 个股 amount/pct_chg 备源，以及模型四所需的 EastMoney quote/minute/tick 源为准。AKShare/EastMoney 的日 K、qfq、index 和 spot 包装接口在最新真实 probe 远端断开时只保留研究探针与历史 raw 合同，不阻断生产闭环。

需要把多源同事实质量矩阵纳入验收证据时追加：

```bash
python scripts/source_data_acceptance.py --base-url http://127.0.0.1:8041 --require-postgres --quality-matrix --quality-matrix-symbol 000063.SZ,000001.SZ,600000.SH --quality-matrix-trade-date 2026-06-12
```

`--quality-matrix` 默认复用 `source_data_quality_matrix.py` 的 P0 日 K 与 qfq 稳定字段组合，逐项调用 `/source/quality/multi-source/check`，并把 `quality_matrix` 作为 `governance.source_data_acceptance_*` 的验收检查项固化。默认日 K 阻断字段覆盖 `open_price/high_price/low_price/close_price/volume/amount/pct_chg`；其中 `amount/pct_chg` 由 Sohu `daily_bars` 提供备验，不再依赖 Tencent `qt` 快照推断。默认 qfq 阻断字段覆盖 adjusted OHLC/volume。需要纳入指数日线时追加 `--quality-matrix-table index --quality-matrix-symbol 399006.SZ`；该项比对 Tencent raw 指数 K 线主源与 BaoStock 指数 K 线备源。任一矩阵项 blocked，或 warning 且未传 `--quality-matrix-allow-warning`，整轮验收返回非 0。

### `source_data_quality_matrix.py`

数据源多源同事实质量矩阵脚本。它只通过 HTTP 调用 `source-data-service /source/quality/multi-source/check`，不导入服务内部代码，不直接并发调用 BaoStock、AKShare、Tencent、Tushare、EastMoney 或 CNINFO，不重启容器。脚本用于把单 symbol / 单表的多源一致性 probe 扩展为可重复运行的 symbol + trade_date + source table 矩阵。

默认矩阵覆盖：

- `source.daily_bar_v1`：`open_price`、`high_price`、`low_price`、`close_price`、`volume`、`amount`、`pct_chg`
- `source.adjusted_daily_bar_v1`：`adjusted_open`、`adjusted_high`、`adjusted_low`、`adjusted_close`、`volume`

显式追加 `--table index` 或 `--table source.index_daily_bar_v1` 时覆盖 `source.index_daily_bar_v1`：`open_price`、`high_price`、`low_price`、`close_price`、`pct_chg`。其中 `close_price` 是 P0 online 字段；指数 `volume/amount` 因 Tencent 与 BaoStock 指数成交口径存在真实 provider 定义差异，只能通过显式 `/source/quality/multi-source/check` 字段请求做审计，不作为默认 passed 矩阵字段。个股日线 `amount` 与 `pct_chg` 已由 Sohu `daily_bars` 作为字段级备源纳入默认矩阵；Tencent `daily_bars` 对这两个字段继续返回 `NULL`，不能用实时快照、0、空字符串、mock 或上一交易日值补齐。脚本仍只调用 source-data-service HTTP 接口。

推荐执行：

```bash
python scripts/source_data_quality_matrix.py --base-url http://127.0.0.1:8041 --symbol 000063.SZ --trade-date 2026-06-12
```

多标的或多日期用逗号或重复参数传入：

```bash
python scripts/source_data_quality_matrix.py --symbol 000063.SZ,000001.SZ --trade-date 2026-06-12 --table daily --table adjusted
python scripts/source_data_quality_matrix.py --symbol 399006.SZ --trade-date 2026-06-12 --table index
```

脚本返回 `0` 代表矩阵全部 passed；任一条 blocked，或 warning 且未传 `--allow-warning`，返回非 0。默认输出 compact evidence，保留 provider、API、raw 表、目标行命中、canonical 值、字段差异和阻断原因；需要查看 passed 字段逐项比较时追加 `--verbose-evidence`。

### `core_services_acceptance.py`

数据源服务、三大模型服务、模型四、调度服务和数据巡检服务的核心生产闭环验收入口。它只通过 HTTP 调用当前运行容器，不直接并发调用 provider，不重启容器；模型四 repository 状态通过 owner service API 检查。

检查范围：

- `source-data-service` health、ready、Postgres repository、Postgres queue、queue summary、dead-letter、production readiness
- probe matrix 中 BaoStock、Tencent、Sohu 与模型四 EastMoney intraday 必需条目存在；可选执行真实 probe
- `source.adjusted_daily_bar_v1` 指定 symbol/date 的 source row 与 lineage
- 三模型 source release preflight 当前合同：`hot_candidates/preopen_release_gate`、`candidate_memory/outcome_label`、`ambush_watchlist/release_gate`
- 模型四 source release preflight：`t_board_relay/day1_scan`、`t_board_relay/day2_trigger`，默认样本 `000759.SZ / 2026-06-12`
- scheduler 当前闭环 ready/runtime；data-inspector ready 作为非跳过时的核心健康信号
- `scheduler-service` ready、runtime、docs-sync、materialize、live-dispatch sample guard
- `scheduler-service` live-dispatch sample guard 覆盖当前 `LIVE_DISPATCH_TASKS`：三条 official release gate 加模型四 Day1/Day2/Post-entry/Day3/outcome 全阶段非 official 任务
- 三大模型 `/score` 或 Phase 3 owner API 合同
- 模型四 Day1 / Day2 真实 source payload 合同，以及 Post-entry / Day3 / outcome owner API 合同、repository write 和 repository status
- 三条官方 release gate 以及模型四全阶段非 dry-run live dispatch

推荐执行：

```bash
python scripts/core_services_acceptance.py --require-postgres
```

模型四默认使用 `--tboard-symbol 000759.SZ`，因为该样本已实测 Day1/Day2 source preflight passed；默认三模型验收 symbol 仍为 `000063.SZ`。需要显式改模型四样本时：

```bash
python scripts/core_services_acceptance.py --require-postgres --tboard-symbol 000759.SZ
```

默认输出为 compact evidence：保留每个检查项的 pass/block 状态、关键字段、计数、样本和阻断原因，避免把完整 probe matrix、source rows、lineage rows 或 scheduler sample payload 全量刷到 stdout。需要定位单项 payload 时追加：

```bash
python scripts/core_services_acceptance.py --require-postgres --verbose-evidence
```

最高规格生产必需真实 provider probe 证据执行：

```bash
python scripts/core_services_acceptance.py --require-postgres --real-provider-probe
```

该模式读取并要求 `source-data-service /source/probe/results` 中已经由 `source_data_acceptance.py --real-provider-probe --probe-limit 0` 固化的真实探针证据全部可用；最小覆盖包含 BaoStock P0 基础源、Tencent `daily_bars`、Sohu `daily_bars` 个股金额/涨跌幅备源，以及模型四 EastMoney `quote_snapshot/minute_bars/trade_details`。如需在核心脚本里再次逐项真实外部重探，追加 `--force-live-provider-probe`；该模式会显著拉长运行时间，通常只在 provider 准入或发布前复核时使用。

真实多源质量矩阵会逐项调用 provider 主备源并执行 canonical 字段比对，单格可能耗时 70 秒以上；因此核心闭环脚本默认只读取 `source_data_acceptance.py --quality-matrix` 已固化到 `governance.source_data_acceptance_*` 的最新可覆盖证据。最高规格闭环验收推荐先运行数据源验收固化真实 provider probe 与质量矩阵，再运行核心闭环读取固化证据：

```bash
python scripts/source_data_acceptance.py --base-url http://127.0.0.1:8041 --require-postgres --real-provider-probe --probe-limit 0 --quality-matrix --quality-matrix-symbol 000063.SZ,000001.SZ,600000.SH,000759.SZ --quality-matrix-trade-date 2026-06-12 --quality-matrix-timeout 720
python scripts/core_services_acceptance.py --require-postgres --real-provider-probe --source-quality-matrix --source-quality-symbol 000063.SZ,000001.SZ,600000.SH,000759.SZ --source-quality-trade-date 2026-06-12 --timeout 120
```

若需要在核心闭环脚本中现场重跑质量矩阵，必须显式追加 `--force-live-source-quality-matrix` 并给足矩阵超时：

```bash
python scripts/core_services_acceptance.py --require-postgres --real-provider-probe --source-quality-matrix --force-live-source-quality-matrix --source-quality-symbol 000063.SZ,000001.SZ,600000.SH,000759.SZ --source-quality-trade-date 2026-06-12 --source-quality-timeout 720 --timeout 120
```

硬边界：

- scheduler sample payload 只用于 live-dispatch 请求体合同和 owner 连通性验证，不是市场事实、provider 响应或 source 证据。
- source row、lineage、preflight 必须来自 `source-data-service` 的 source/lineage/preflight API。
- 三模型和模型四 source release preflight 必须全部 `can_release_official_signal=true` 且 `blocking_reasons=[]`；返回 `can_release_official_signal=false` 即使带有 repair actions 也视为未闭环。
- 模型四 POST 阶段接口必须返回 `repository_write.persisted=true`，`GET /t-board-relay/repository/status` 必须显示 repository attached，且 Day1/Day2/Post-entry/Day3/outcome/game_hypothesis 表有真实写入。
- 若任一必需检查失败，脚本返回非 0；非必需的 latest probe evidence 只作为提示，不替代 `--real-provider-probe`。
- compact evidence 只影响 stdout 展示，不改变检查逻辑；`--verbose-evidence` 可输出完整 HTTP 响应证据。
