# services

本目录记录当前仓库内服务层事实源索引。每个服务或服务组的真实契约必须写在对应目录根部唯一 `README.md`，不得写入 `docs/`、临时包或根目录新增 MD。服务目录允许额外保留一个 `DATA_ASSETS.md`，只记录该服务的数据源表、独立表、关联表、调度频率、接口入口、性能索引和读写边界；它不替代 `README.md` 的服务契约。

当前仓库服务：

```text
source-data-service
data-inspector-service
models_services
scheduler-service
shence-frontend-service
research-center-service
research-service
```

当前闭环边界：

- `source-data-service` 与 `source-data-worker`：数据源 API、fetch orchestration、worker、raw/source/lineage、production-readiness 和 release preflight。
- `data-inspector-service`：按新 source/preflight/lineage、已接入模型 ready 和 scheduler ready 重新设计的数据巡检、缺口审计和 remediation task。
- `models_services`：模型 owner service 集合，当前包含已锁定三模型和新增模型四 `t-board-relay-service`。
- `scheduler-service`：已锁定三模型与模型四任务计划、startup/current_closure 守卫、materialize、trigger 和 live dispatch；模型四 `t_relay.*` 任务均为 non-official 研究 / 模型阶段任务，不发布 official signal。
- `shence-frontend-service`：新增只读前端服务，当前开放登录页、候选输入页、四个模型页和研究中心-低谷图库页；其他旧前端页面隐藏不开放。
- `research-center-service`：研究中心后端承载层，第一阶段只落地模型三低谷图形标注中心和低谷图库研究资产，写入 `research_ambush.*` 研究表，不改写模型三生产评分、official signal、买点、outcome、source/raw 或调度事实。
- `research-service`：模型 owner payload 组装层，读取已构建的 `source.*` 和允许的上游决策事实，输出 `research_model_payload_assembler_v1` payload 或 `blocked_data_gap`，不采 provider、不读 raw、不写模型事实。

尚未在当前仓库源码闭环内完整接入的业务服务包括 research-data-mart、gateway-service、execution-timing-service、Jarvis/explanation/notification 等。后续接入必须依赖 `source-data-service` 的 source 标准事实、质量、lineage、available_at 和 preflight 合同，不得直接读取 raw 或并发调用 provider。

## 数据资产账本

当前服务数据资产账本：

```text
services/source-data-service/DATA_ASSETS.md
services/data-inspector-service/DATA_ASSETS.md
services/scheduler-service/DATA_ASSETS.md
services/research-service/DATA_ASSETS.md
services/research-center-service/DATA_ASSETS.md
services/shence-frontend-service/DATA_ASSETS.md
services/models_services/DATA_ASSETS.md
services/models_services/hot-candidates-service/DATA_ASSETS.md
services/models_services/candidate-memory-service/DATA_ASSETS.md
services/models_services/ambush-watchlist-service/DATA_ASSETS.md
services/models_services/t-board-relay-service/DATA_ASSETS.md
```

`DATA_ASSETS.md` 只记录当前服务数据资产和读写边界，不记录历史任务账本。若服务拍板冻结，冻结范围涉及数据资产时必须同步写入对应账本。
