# source-data-service

锁定目标：`source_data_service_ds7_production_readiness_candidate`

本服务是神策中心后续所有服务的数据源底座。三大模型、调度服务、后续数据巡检、特征服务、研究服务都必须依赖这里沉淀的 **provider 原接口表** 和 **source 标准事实表**。

## 1. 硬性架构原则

1. **一接口一原表**：每个 provider 的每个 API 单独落一张 `raw_<provider>.<api>_v1` 原表。
2. **模型不读 raw**：模型只能读取 `source.*` 标准事实表，不能直接读取 `raw_baostock.*`、`raw_akshare.*`、`raw_tushare.*`。
3. **source 由 raw 构建**：`source.*` 不是某一个 API 的直接别名，而是由多个接口原表通过字段映射、单位转换、主备源比对、质量标记、血缘记录后构建。
4. **缺口可反查接口**：数据巡检发现某个 `source` 字段缺失时，必须能通过 `governance.source_table_requirement_v1` 找到应该补采的 provider、api、raw_table 和请求参数。
5. **所有字段有 lineage**：source 表每个关键字段要能通过 `governance.source_lineage_v1` 追溯到 raw 表、raw_id、batch_id、provider、api_name。
6. **免费公开源优先**：优先 BaoStock、AKShare、交易所/巨潮公开数据；无法满足再进入 Tushare/聚宽/Wind/Choice/iFinD 等付费或积分制接口。
7. **数据源服务不因单个 provider 掉线而掉线**：provider 失败必须通过超时、重试、熔断、备源和 research-only 降级处理，不能拖垮服务本身。
8. **数据源只存事实**：source/raw 层禁止出现模型语义字段，例如 `signal`、`score`、`buy_point`、`outcome`、`success`、`ambush_score`、`hot_score`。

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
    worker_executor.py
    worker_loop.py
    adapters/
      base.py
      baostock_adapter.py
      akshare_adapter.py
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

请求示例：

```json
{
  "provider": "akshare",
  "api_name": "stock_zh_a_hist_daily_qfq",
  "sample_params": {
    "symbol": "000759",
    "period": "daily",
    "start_date": "20260525",
    "end_date": "20260525",
    "adjust": "qfq"
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

### 5.2 AKShare 免费源

| API | 原表 | 请求参数 | 返回字段 | 目标 source |
|---|---|---|---|---|
| `ak.stock_zh_a_spot_em` | `raw_akshare.stock_zh_a_spot_em_v1` | 无 | `代码`, `名称`, `最新价`, `涨跌幅`, `成交量`, `成交额`, `最高`, `最低`, `今开`, `昨收`, `量比`, `换手率` | `source.stock_universe_daily_v1`, quote snapshot |
| `ak.stock_zh_a_hist` raw | `raw_akshare.stock_zh_a_hist_daily_raw_v1` | `symbol`, `period=daily`, `start_date`, `end_date`, `adjust=""` | `日期`, `开盘`, `收盘`, `最高`, `最低`, `成交量`, `成交额`, `振幅`, `涨跌幅`, `涨跌额`, `换手率` | `source.daily_bar_v1` |
| `ak.stock_zh_a_hist` qfq | `raw_akshare.stock_zh_a_hist_daily_qfq_v1` | `symbol`, `period=daily`, `start_date`, `end_date`, `adjust=qfq` | 同上 | `source.adjusted_daily_bar_v1` |
| `ak.stock_board_industry_name_em` | `raw_akshare.stock_board_industry_name_em_v1` | 无 | `板块名称`, `板块代码`, `最新价`, `涨跌幅`, `总市值`, `换手率`, `上涨家数`, `下跌家数` | `source.board_master_v1` |
| `ak.stock_board_industry_cons_em` | `raw_akshare.stock_board_industry_cons_em_v1` | `symbol=板块名称` | `代码`, `名称`, `最新价`, `涨跌幅`, `成交量`, `成交额`, `换手率` | `source.stock_board_membership_v1` |
| `ak.stock_board_industry_hist_em` | `raw_akshare.stock_board_industry_hist_em_v1` | `symbol`, `adjust` | `日期`, `开盘`, `收盘`, `最高`, `最低`, `涨跌幅`, `成交量`, `成交额`, `换手率` | `source.board_daily_bar_v1` |
| `ak.stock_fund_flow_individual` | `raw_akshare.stock_fund_flow_individual_realtime_v1` | `symbol=即时` | `股票代码`, `股票简称`, `流入资金`, `流出资金`, `净额`, `成交额`, `大单流入` | `source.stock_moneyflow_daily_v1` |
| `ak.index_zh_a_hist` | `raw_akshare.index_zh_a_hist_v1` | `symbol`, `period`, `start_date`, `end_date` | `日期`, `开盘`, `收盘`, `最高`, `最低`, `成交量`, `成交额`, `涨跌幅` | `source.index_daily_bar_v1` |
| `ak.stock_zh_a_disclosure_report_cninfo` | `raw_akshare.stock_zh_a_disclosure_report_cninfo_v1` | `symbol`, `market`, `start_date`, `end_date` | `代码`, `简称`, `公告标题`, `公告时间`, `公告类型`, `公告链接` | `source.event_news_v1` |

### 5.3 Tushare 准免费 / 付费备源

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
| `source.stock_master_v1` | `raw_baostock.query_stock_basic_v1` | `raw_tushare.stock_basic_v1` | 股票基础信息 |
| `source.stock_universe_daily_v1` | `raw_baostock.query_all_stock_v1` | `raw_akshare.stock_zh_a_spot_em_v1` | 某交易日可交易 universe |
| `source.trade_calendar_v1` | `raw_baostock.query_trade_dates_v1` | `raw_tushare.trade_cal_v1` | 调度基础 |
| `source.daily_bar_v1` | `raw_baostock.query_history_k_data_plus_daily_raw_v1` | `raw_akshare.stock_zh_a_hist_daily_raw_v1`, `raw_tushare.daily_v1` | 未复权日K |
| `source.adjusted_daily_bar_v1` | `raw_baostock.query_history_k_data_plus_daily_qfq_v1` | `raw_akshare.stock_zh_a_hist_daily_qfq_v1` | 模型三图库主用 |
| `source.adjustment_factor_v1` | `raw_baostock.query_adjust_factor_v1` | `raw_tushare.adj_factor_v1` | 复权审计 |
| `source.weekly_bar_v1` | 内部由 `source.daily_bar_v1` 聚合 | AKShare/BaoStock 周K校验 | 不建议直接以外部周K为主 |
| `source.trade_status_v1` | BaoStock 日K中的 `tradestatus`, `isST` | Tushare suspend/status | 三模型 hard block |
| `source.limit_price_v1` | 内部交易规则计算 | `raw_tushare.stk_limit_v1` | 不能简单 `pct_chg>=9.8` |
| `source.index_daily_bar_v1` | `raw_akshare.index_zh_a_hist_v1` | BaoStock/Tushare 指数 | 市场环境 |
| `source.board_daily_bar_v1` | `raw_akshare.stock_board_industry_hist_em_v1` | 内部按成员聚合 | 板块相对强弱 |
| `source.stock_moneyflow_daily_v1` | `raw_akshare.stock_fund_flow_individual_realtime_v1` | `raw_tushare.moneyflow_v1` | 第一版 confirmation/research，不强 hard gate |
| `source.event_news_v1` | `raw_akshare.stock_zh_a_disclosure_report_cninfo_v1` | CNINFO direct | research-only until `available_at` 稳定 |

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
source.stock_moneyflow_daily_v1.net_main_inflow
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
1. 禁止模型服务直接调用 BaoStock / AKShare / Tushare / EastMoney 等 provider。
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
published_at, available_at
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
8. POST /source/probe dry_run=false 至少验证 BaoStock / AKShare P0 行情接口
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

`real_probe_required=true` 的语义是“生产拍板硬门禁必需真实 probe”，不是“所有已登记接口都要立刻阻断拍板”。当前硬门禁只覆盖 `P0 + required_for_online` 字段对应的、adapter 已实现且不需要 token 的 provider/API；已登记但 adapter 仍 pending 的 EastMoney/Tencent/Sina/CNINFO，以及需要 token/积分/付费权益的 Tushare 备源，保留在矩阵中作为合同和后续接入证据项，但不阻断免费源生产候选闭环。任何这类 API 后续被启用为 online gate、主源、fallback、adapter 或 converter 后，必须先完成真实 probe 并把结果写入 `governance.source_probe_result_v1`。

AKShare 中 `stock_zh_a_spot_em`、`index_zh_a_hist`、`stock_zh_a_hist_daily_raw` 与 `stock_zh_a_hist_daily_qfq` 可由公开 EastMoney 接口承载；如果 AKShare 默认请求路径被远端断开，adapter 会使用同等公开 EastMoney URL、浏览器 `User-Agent` 和 `Referer` 进行最小 fallback，并仍按原 AKShare API 的 raw 表和字段合同返回。日 K fallback 必须保持复权口径隔离：`adjust=""` 写入 `raw_akshare.stock_zh_a_hist_daily_raw_v1`，EastMoney `fqt=0`；`adjust="qfq"` 写入 `raw_akshare.stock_zh_a_hist_daily_qfq_v1`，EastMoney `fqt=1`。该 fallback 只用于保持同一 provider/API 合同的真实网络 probe 与采集可用性，不得绕过 raw 表、source build、lineage 或质量门禁。

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
1. 至少对 BaoStock 和 AKShare 的 P0 API 执行真实 probe；
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

raw_<provider>.<api>_v1
  每行 provider 原接口数据必须物理保留 `request_hash`、`response_schema_hash`、`response_row_hash`、`request_params_json`、`captured_at` 和 `available_at`；`request_hash` 不能只存在于 fetch job 或 raw write audit 中。0020 会对历史 raw 表执行幂等 ALTER，补齐 DS-6 真实回放和行级审计所需字段。

raw_fetch_idempotency_key_v1
  防止调度、巡检、模型重复提交同一任务。

raw_fetch_worker_heartbeat_v1
  记录 worker 存活、当前任务、最近心跳。

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

Docker 构建 `source-data-service` 与 `source-data-worker` 时必须安装 `services/source-data-service[providers]`，确保 BaoStock、AKShare、Tushare adapter 在容器内具备真实 provider 包。其他服务不得默认安装 provider extras。

`SOURCE_DATA_WORKER_DRY_RUN_PROVIDER=true` 只用于队列合同单元验收；本地 Docker 发布验证与生产候选验证必须使用 `SOURCE_DATA_WORKER_DRY_RUN_PROVIDER=false`，由 worker 真实调用 provider。

当前 DS-7 实现要求 `/source/fetch/submit` 在 Postgres 队列中先持久化 `raw_fetch_batch_v1`，再写入 `raw_fetch_job_item_v1`，最后回写 batch 计数和状态，避免 job 外键指向尚未落库的 batch。

`/source/fetch/persistence/status` 与 `/source/fetch/queues/summary` 在 Postgres 队列 ready 时必须从 durable queue 读取 active batch、queued、leased、dead-letter 和分队列状态，避免 API 容器重启、worker 独立消费或零任务 batch 导致内存态与数据库事实不一致。内存态只服务 `SOURCE_DATA_QUEUE_BACKEND=memory` 的本地单元测试。

`/source/fetch/batches/{fetch_batch_id}`、`/source/fetch/jobs/{job_item_id}`、`/source/build/triggers` 和 `/source/build/results` 在 Postgres 队列 ready 时也必须优先读取 durable queue / build 表，不能读取 API 容器进程内状态作为生产事实。batch 状态必须从 job item 当前状态派生；如果历史 API 内存态曾把已完成 batch 回写成 `queued`，查询端必须以 job 表事实自修正为 `succeeded`、`running`、`completed_with_errors` 或 `cancelled`。source build worker 只消费 `queued` trigger，禁止因 durable trigger 列表包含历史 `succeeded` 记录而重复构建。

`source-data-worker` 启动后必须从 Postgres 持久化队列恢复 active batch/job，不依赖 API 容器进程内存。真实 provider job 成功后，worker 必须先通过 raw repository 写入对应 `raw_<provider>.<api>_v1`，再完成 job 并生成 `source_build_trigger_v1`；随后继续推进 source build，把 canonical row 写入 `source.*` 并生成 `governance.source_lineage_v1`。`/source/probe` 的真实探针结果必须写入 `governance.source_probe_result_v1` 作为 provider 可用性证据。

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
3. BaoStock / AKShare / Tushare / EastMoney 至少 P0 接口真实网络 probe。
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

注意：memory repository 只允许单元测试，不允许生产运行。

### 15.3 验收脚本

新增：

```text
scripts/source_data_acceptance.py
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
acceptance evidence persist
```

`source build dry-run` 只允许作为只读验收动作：可以返回本次会处理哪些 trigger、是否找到 raw rows 以及会产生哪些 warning，但不得把真实 `source_build_trigger` 从 `queued` 改成 `failed/succeeded`，也不得写入 `governance.source_build_execution_result_v1`。同一 `job_item_id + source_table_name + symbol + trade_date + build_scope` 已经存在 `queued/running/succeeded` trigger 时，重复 `job complete` 不得再生成第二条 build trigger；同 key 已经有成功 build result 时，build worker 必须跳过后续重复 queued trigger，避免 dry-run 或重复回调污染生产审计。

验收脚本必须可以重复运行。同一 symbol/date/provider/API 的 fetch submit 已经存在时，应返回幂等跳过结果并继续后续 queue、worker、build、readiness 检查；重复 `request_hash` 不得造成 404/500 或阻断生产验收。
脚本结束前必须通过 `POST /source/ops/acceptance-runs` 固化本次验收运行和单项检查证据；当传入 `--require-postgres` 时，若证据未写入 `governance.source_data_acceptance_*`，脚本必须返回非 0，不能只把验收结果留在 stdout。
`--real-provider-probe --probe-limit N` 表示按 probe matrix 抽取前 N 个 `real_probe_required=true` 的真实 provider probe 并作为单项检查落证据；脚本会把 `YYYY-MM-DD` / `YYYYMMDD` 模板替换成 `--trade-date` 指定的真实日期。BaoStock `query_adjust_factor` 的验收样例固定使用 `sz.000001` 与 `1990-01-01` 至 `--trade-date` 的长窗口，避免因单只股票短窗口无除权除息记录而把真实可用 API 误判为 schema 不可用。AKShare `stock_zh_a_spot_em` 的真实 probe 只拉取公开 EastMoney 第一页单行样本用于连通性、schema 与行级可用性验收，正式采集仍必须走 fetch orchestration 和 worker 全量任务，并由 source coverage / freshness 门禁确认全量可用性。全量严格门禁应单独调用 `/source/ops/production-readiness?require_postgres=true&require_real_provider_probe=true`，该接口会要求全部 `real_probe_required=true` 的 API 都有可用的持久化真实 probe 记录。

`--real-provider-probe` 逐项调用真实 provider 时会按 `--probe-retries` 做有限重试，并把每次尝试记录到该 provider/API 的 `_acceptance_attempts` 证据中。远端偶发断连、限流或超时不会提前中断整轮脚本，但最终仍以最后一次可用真实 probe 为准；如果某个必需 API 在所有尝试后仍不可用，`real_provider_probe` 检查保持 blocked，脚本返回非 0。生产锁定仍以 `/source/ops/production-readiness?require_postgres=true&require_real_provider_probe=true` 读取 Postgres 中固化的全部必需 probe 证据为准。

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
5. 至少 BaoStock + AKShare P0 日K/qfq 接口真实 probe。
6. raw/source/lineage 真实写入后，/source/release/preflight 对缺失和完整样本分别返回 blocked/passed 或 degraded。
7. source-data-worker 连续运行，任务 lease/heartbeat/requeue/dead-letter 均可观测。
```
