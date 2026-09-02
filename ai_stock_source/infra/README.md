# infra

本目录记录当前 Docker 和基础设施运行契约。当前核心闭环服务包括 `source-data-service`、`source-data-worker`、三大模型 owner service、模型四 `t-board-relay-service`、`scheduler-service` 和 `data-inspector-service`。其他业务服务不作为当前 compose ready 的前置条件。

## Compose 服务

核心基础设施：

- `postgres`：核心数据库。
- `schema-bootstrap`：执行 `infra/sql/*.sql`，当前数据源上线链路要求覆盖 `0012` 到 `0025`，模型四生产表从 `0022_t_board_relay_decision_schema_v1.sql` 起创建，source foundation 索引和 `source.trade_calendar_v1` current contract 加固在 `0025_source_data_foundation_indexes_v1.sql`。

`postgres` 与 `schema-bootstrap` 是 infra Compose 角色，不在 `services/` 下单独拥有服务代码目录或 `DATA_ASSETS.md`。它们的数据资产事实源归属本 `infra/README.md`、根目录 `AGENTS.md`、当前 SQL 文件和实际 Postgres metadata；涉及 source foundation 的冻结记录同步到 `services/source-data-service/README.md` 与 `services/source-data-service/DATA_ASSETS.md`。

当前闭环业务容器：

- `source-data-service`：端口 `8041`，入口 `source_data_service.api:app`。
- `source-data-worker`：消费 source fetch orchestration 队列。
- `hot-candidates-service`：端口 `8031`，入口 `hot_candidates_model_service.main:app`。
- `candidate-memory-service`：端口 `8032`，入口 `candidate_memory_model_service.main:app`。
- `ambush-watchlist-service`：端口 `8033`，入口 `ambush_watchlist_model_service.main:app`。
- `t-board-relay-service`：容器端口 `8034`、宿主默认端口 `8035`，入口 `t_board_relay_model_service.main:app`。
- `scheduler-service`：端口 `8023`，入口 `scheduler_service.main:app`。
- `data-inspector-service`：端口 `8025`，入口 `data_inspector_service.main:app`。

保留但非当前闭环必需的基础设施：

- `redis`
- `nats`
- `minio`

这些基础设施可供后续分布式锁、事件总线和对象归档使用，但当前三模型闭环不得依赖它们判定 ready。它们放入 Compose profile `optional-infra`，默认 `docker compose up` 不会启动；确需联调时必须显式传入 profile。

## 启动口径

首次上线或 Docker 已清理后的数据源服务镜像构建，只允许定向构建数据源 API 镜像：

```bash
docker compose -f infra/docker-compose.yml build source-data-service
```

该动作不会启动容器，不会重建其它业务服务，不会清库或删卷。2026-06-17 本地已按该口径执行一次，产出 `infra-source-data-service:latest`，最终验收镜像 ID 前缀为 `c7fbfcc57cec`；同轮仅额外重建 `infra-source-data-worker:latest`（`2a7c1df99784`）和 `infra-schema-bootstrap:latest`（`a4a7f8ede9f8`）以完成数据源闭环，未重建模型、scheduler 或 data-inspector 镜像。若需要启动 Postgres、schema-bootstrap、source-data-service 或 source-data-worker，必须另行确认启动顺序和验收范围。

构建当前闭环镜像：

```bash
docker compose -f infra/docker-compose.yml build source-data-service source-data-worker hot-candidates-service candidate-memory-service ambush-watchlist-service t-board-relay-service scheduler-service data-inspector-service
```

启动当前闭环服务：

```bash
docker compose -f infra/docker-compose.yml up -d source-data-service source-data-worker hot-candidates-service candidate-memory-service ambush-watchlist-service t-board-relay-service scheduler-service data-inspector-service
```

默认启动当前 compose：

```bash
docker compose -f infra/docker-compose.yml up -d
```

如需启动可选基础设施：

```bash
docker compose -f infra/docker-compose.yml --profile optional-infra up -d redis nats minio
```

调试时如需避免触碰已经常驻且锁定的 `source-data-service`、`source-data-worker`、三模型或 `scheduler-service`，只允许对未锁定服务做定向启动。例如只构建和验证新 data-inspector：

```bash
docker compose -f infra/docker-compose.yml build data-inspector-service
set DATA_INSPECTOR_SERVICE_PORT=8125
docker compose -f infra/docker-compose.yml up -d --no-deps data-inspector-service
```

如果宿主机 `8025` 已被旧 data-inspector 容器占用，本地验证可以临时映射到 `8125`。正式替换 `8025` 前必须先确认调度健康、数据源健康、停机影响和回滚方案。

模型四独立 owner service 默认宿主端口使用 `8035`，因为本机已有旧 `execution-timing-service` 占用 `8034` 宿主端口：

```bash
docker compose -f infra/docker-compose.yml up -d --build --no-deps t-board-relay-service
```

不得使用 `docker compose down`、全栈清理或网络重置处理普通联调问题。

## 健康检查

优先检查：

```text
GET http://127.0.0.1:8041/readyz
GET http://127.0.0.1:8041/source/ops/production-readiness?require_postgres=true&require_real_provider_probe=true
GET http://127.0.0.1:8031/readyz
GET http://127.0.0.1:8032/readyz
GET http://127.0.0.1:8033/readyz
GET http://127.0.0.1:8035/readyz
GET http://127.0.0.1:8023/readyz
GET http://127.0.0.1:8025/readyz
POST http://127.0.0.1:8025/inspection-runs scope=startup_guard
POST http://127.0.0.1:8025/inspection-runs scope=core_closure
```

`scheduler-service` 默认 `current_closure` 模式直接校验 source、data-inspector、三模型、模型四和 preflight。`legacy_data_inspector` 模式只用于兼容旧启动守卫，此时 scheduler 会调用 `data-inspector-service /inspection-runs` 的 `startup_guard`，该 scope 不得反向依赖 scheduler ready，避免启动循环。模型四进入 current_closure 时使用 `SCHEDULER_T_BOARD_GUARD_SYMBOL=000759.SZ` 进行 Day1/Day2 source preflight。

2026-06-18 起，Compose 生产候选对 `scheduler-service` 显式开启 `SCHEDULER_MODEL_TIME_WHEEL_LIVE_DISPATCH=true`，正式模型任务时间轮只调用 `research-service /research/model-execution/run`。`scheduler_task_store` 命名卷挂载到 `/var/lib/ai_stock_scheduler`，`SCHEDULER_TASK_STORE_PATH=/var/lib/ai_stock_scheduler/task_store.sqlite3`，用于持久保存 scheduler 本地非临时 task instance、lease、terminal blocked、retry/dead-letter 和 run log。该卷不是 source fetch 生产队列，也不是模型事实库；source fetch 队列仍以 source-data-service Postgres queue 为准，模型事实仍以 research/owner 持久化结果为准。

同日定向发布只执行 `docker compose -f infra/docker-compose.yml build scheduler-service` 和 `docker compose -f infra/docker-compose.yml up -d --no-deps scheduler-service`。发布前将旧容器 `/tmp/ai_stock_scheduler_task_store.sqlite3` 备份并灌入 `infra_scheduler_task_store` 卷；发布后 `ai-stock-scheduler-service` 为 `96024e43e68c`，镜像为 `infra-scheduler-service@sha256:050ffdcb096875771b0f094fc3ec82486ed022ff249a39a4cbea572f1c7c84e7`，rollback 标签为 `infra-scheduler-service:rollback-20260618-model-time-wheel-live-dispatch`。`source-data-service`、`source-data-worker`、`data-inspector-service`、`research-service`、Postgres 和模型 owner 均未在该命令中重建或替换。

## 数据源规则

- `SOURCE_DATA_QUEUE_BACKEND` 必须为 `postgres`；`memory` 只允许本地单元测试。
- `source-data-service` 负责 API 与任务状态，`source-data-worker` 负责消费任务。
- 新增或临时索取数据必须走 `/source/fetch/plan` -> `/source/fetch/submit` -> worker pull/complete。
- provider 真实返回必须先进入 raw 原接口层，再通过质量门禁、source build 和 lineage 进入 `source.*`。
- 当前日线字段级备源为 BaoStock 主源、Tencent OHLC/volume 备源、Sohu amount/pct_chg/turnover_rate 备源；旧公开源已扩充到 EastMoney universe/quote/auction/day/minute/trade/moneyflow/board/billboard/northbound/LPR、Tencent quote/minute/auction/day、Sina auction、THS limit/context、Baidu/Jin10 news、CoinGecko/Yahoo cross-market。上述公开 Web adapter 依赖 `requests`，必须随 `source-data-service` 镜像显式安装。
- 普通迭代不得停止、重启、重建、删除或替换已锁定的 `source-data-service`；确需变更时必须先写明影响范围、备份/回滚步骤和验证清单。

## 首次上线索引基线

`infra/sql/0025_source_data_foundation_indexes_v1.sql` 是首次上线 source 底座读路径索引基线。它只新增 `CREATE INDEX IF NOT EXISTS` 和索引注释，不创建业务表、不写事实、不改模型状态。覆盖路径：

- 交易日历、股票主数据、股票日 universe。
- 日线、前复权日线、交易状态、涨跌停价格、涨跌停事件。
- 实时报价、分钟线、逐笔、资金流、事件新闻。
- source lineage duplicate audit、source build trigger、canonical write audit 和 urgent release queue。

该索引用于降低 source preflight、data-inspector startup/core closure、候选页只读 universe、模型四 Day1/Day2 和数据资产审计的查询成本。新增索引后必须同步 `infra/sql/bootstrap_schema.sql` 与 SQL 合同测试。

2026-06-17 首次上线重建验收：schema-bootstrap exited 0，日志显示 applied 24 SQL migration files；`source-data-service /readyz` ready；`/source/ops/production-readiness?require_postgres=true&require_real_provider_probe=true` passed 且 `can拍板=true`；`scripts/source_data_acceptance.py --require-postgres --real-provider-probe --probe-limit 0 --quality-matrix` 写入 `acceptance_92b1fd11770b421d8cf7` 并返回 0；`scripts/core_services_acceptance.py --require-postgres --real-provider-probe --source-quality-matrix` 返回 0；data-inspector core_closure run `2085` ready。涉及 `schema-bootstrap -> source foundation schema -> 0025 indexes/trade_calendar hardening` 的冻结记录以 `services/source-data-service/README.md` 和 `DATA_ASSETS.md` 为模块事实源，根锁定清单见 `AGENTS.md`。

## 服务边界

- 模型服务只接收 research/scheduler 或人工验证组装好的 payload，不直接并发调用 provider。
- scheduler 只调用 owner service，不写模型事实、分数、状态、标签、发布闸门、买点版本或学习权重。
- data-inspector 只读 source/preflight/lineage、scheduler ready、已接入模型 ready 和模型四 repository 表存在性，写入 `decision.data_inspection_*` 审计表，不改 source、模型或调度事实。
- 当前已锁定 official signal 只能由三模型 release gate 任务发布：`hot.release_gate.preopen`、`memory.release_gate.close`、`ambush.phase3.release_gate.close`。模型四已接入 scheduler，但全部 `t_relay.*` 任务均为 non-official，不接入 official release gate。
- source 缺口必须保留 `NULL`、缺口码、阻断状态或 warning，不得用 0、空字符串、mock 或推断补事实。
