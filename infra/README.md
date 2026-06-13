# infra

本目录只记录当前 Docker/基础设施运行契约。当前最小闭环优先调通数据源服务、三大模型服务和调度服务；其他业务服务不作为本轮 compose 启动前置条件。

## 当前 Compose 服务

核心基础设施：

- `postgres`：核心数据库。
- `schema-bootstrap`：执行 `infra/sql/*.sql`，当前数据源上线链路要求覆盖 `0012` 到 `0020`。

当前必须调通的业务容器：

- `source-data-service`：端口 `8041`，入口 `source_data_service.api:app`。
- `source-data-worker`：消费 source fetch orchestration 队列。
- `hot-candidates-service`：端口 `8031`，入口 `hot_candidates_model_service.main:app`。
- `candidate-memory-service`：端口 `8032`，入口 `candidate_memory_model_service.main:app`。
- `ambush-watchlist-service`：端口 `8033`，入口 `ambush_watchlist_model_service.main:app`。
- `scheduler-service`：端口 `8023`，入口 `scheduler_service.main:app`。

保留但非当前闭环必需的基础设施：

- `redis`
- `nats`
- `minio`

这些基础设施可供后续分布式锁、事件总线和对象归档使用，但当前三模型最小闭环不得依赖它们判定 ready。它们已经放入 Compose profile `optional-infra`，默认 `docker compose up` 不会启动；确需联调时必须显式传入 profile。

## 启动口径

构建当前闭环镜像：

```bash
docker compose -f infra/docker-compose.yml build source-data-service source-data-worker hot-candidates-service candidate-memory-service ambush-watchlist-service scheduler-service
```

启动当前闭环服务：

```bash
docker compose -f infra/docker-compose.yml up -d source-data-service source-data-worker hot-candidates-service candidate-memory-service ambush-watchlist-service scheduler-service
```

默认启动当前 compose 时，启动集只包含 Postgres、schema-bootstrap、source-data-service、source-data-worker、三大模型服务和 scheduler-service：

```bash
docker compose -f infra/docker-compose.yml up -d
```

如确需启动可选基础设施：

```bash
docker compose -f infra/docker-compose.yml --profile optional-infra up -d redis nats minio
```

调试时如需避免触碰已经常驻的 `source-data-service`，只允许对模型和 scheduler 使用定向启动：

```bash
docker compose -f infra/docker-compose.yml up -d --no-deps hot-candidates-service candidate-memory-service ambush-watchlist-service scheduler-service
```

不得使用 `docker compose down`、全栈清理或网络重置来处理普通联调问题。

## 健康检查

优先检查：

```text
GET http://127.0.0.1:8041/readyz
GET http://127.0.0.1:8041/source/providers/status
GET http://127.0.0.1:8031/readyz
GET http://127.0.0.1:8032/readyz
GET http://127.0.0.1:8033/readyz
GET http://127.0.0.1:8023/readyz
```

`scheduler-service /readyz` 还要求 `data-inspector-service /readyz` 可达，并且本次启动已完成 `startup_guard` 巡检。当前仓库没有把 data-inspector 源码纳入最小 compose；本地闭环可复用同一 Docker network 内已运行的 `data-inspector-service`，生产候选锁定前必须保证该服务可达。

## 数据源硬规则

- `SOURCE_DATA_QUEUE_BACKEND` 必须为 `postgres`；`memory` 只允许本地单元测试。
- `source-data-service` 负责 API 与任务状态，`source-data-worker` 负责消费任务。
- 新增或临时索取数据必须走 `/source/fetch/plan` -> `/source/fetch/submit` -> worker pull/complete。
- provider 真实返回结果必须先进入 raw 原接口层，再通过质量门禁、source build 和 lineage 进入 `source.*`。
- 普通迭代不得停止、重启、重建、删除或替换 `source-data-service`；确需变更时必须先写明影响范围、备份/回滚步骤和验证清单。

## 三模型与 scheduler 边界

- 三模型服务只接收 research/scheduler 组装好的 payload，不直接并发调用 provider。
- scheduler 只调用 owner service，不写模型事实、分数、状态、标签、发布闸门、买点版本或学习权重。
- official signal 只能由三模型 release gate 任务发布：`hot.release_gate.preopen`、`memory.release_gate.close`、`ambush.phase3.release_gate.close`。
- source 缺口必须保留 `NULL`、缺口码、阻断状态或 warning，不得用 0、空字符串、mock 或推断补事实。
