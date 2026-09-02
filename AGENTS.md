# ai_stock MACP 系统主契约

本文件是 `D:\ai_stock` 的唯一硬契约。
这里是后期 MACP 系统本体，不是文档沙盘。

## 三棵树

| 树 | 路径 | 角色 |
|---|---|---|
| 系统本体 | 根目录能力树 + `docs/` | 以后只在这里开发 |
| 迁入对照 | `ai_stock_source/` | 只读，按服务整包迁入 |
| 旧原则归档 | `archive/knowledge_baseline_v1_1/` | 只读，不覆盖 |

运行事实：未迁入前看 `ai_stock_source` 对应 README；迁入后看落点 README + 代码。

## 阅读顺序

1. 本文件
2. `docs/governance/MACP_CONSTITUTION.md`
3. `docs/decisions/ACTIVE/FROZEN_DECISIONS.md`
4. `docs/architecture/SERVICE_TO_MACP_MAP.md`
5. `docs/architecture/TARGET_ARCHITECTURE.md`
6. `docs/architecture/MIGRATION_PLAN.md`
7. `docs/context/CURRENT_STATE.md`
8. 本次落点 README
9. 对应 `ai_stock_source` 服务 README

## 代码落点

```text
macp/                                 瘦 Control Plane（新）
data_foundation/source-data-service/  数据底座 + worker
intelligence/*-service/               四模型
intelligence/evaluation/              跨模型只读视图（新）
runtime/scheduler-service/
runtime/data-inspector-service/
research/research-service/
research/research-center-service/
frontend/shence-frontend-service/
packages/{common,db-schema,macp-contracts}
infra/
scripts/
```

## 硬红线

- 未按服务名解锁，不得改锁定服务逻辑、schema、Docker 合同。
- 迁入是整包搬家，禁止在落点手写第二套 source/scheduler/owner/inspector。
- `macp/` 只做注册、决策、恢复提案审批、上下文。
- 补数必须走 source fetch orchestration。
- 缺事实保留 `NULL` / 缺口码，禁止 mock / 0 / GPT 推断。
- 前端与 Jarvis 只读。
- 可运行代码不进 `docs/`、`archive/`。

## 版本

`ai_stock_MACP_System_v1_4`
