# packages README

本文件是 `packages` 目录唯一当前 MD。全局硬约束以项目根目录 `AGENTS.md` 为准；子包细节以各子包根目录唯一 README 为准。

## 当前包

- `common`：轻量通用工具，当前提供健康检查 payload helper 和包版本。
- `db-schema`：当前 Docker schema-bootstrap 工具和 Alembic 当前基线入口。

当前仓库没有 `packages/clients` 或 `packages/contracts` 目录，不能把它们写成已存在事实源。

## 变更规则

共享包变更会影响多个服务镜像。涉及共享包代码、依赖、数据库 bootstrap 或基线入口时，必须同步更新本 README、对应子包 README，以及受影响服务或基础设施目录的唯一当前 MD。
