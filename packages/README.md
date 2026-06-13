# packages 当前说明

`packages` 存放跨服务共享代码。

## 包

- `common`：通用设置、健康检查、时间、序列化等基础能力。
- `clients`：服务间 HTTP client，当前包含三大模型、research-data-mart 等调用封装。
- `contracts`：跨服务 Pydantic 契约。
- `db-schema`：SQLAlchemy metadata、Alembic 当前基线、schema bootstrap。

共享包变更会影响多服务镜像，必须同步对应服务 README 和数据库/契约说明。
