# 当前冻结决策

## D-20260902-01 仓库角色

`D:\ai_stock` 是 MACP 系统本体。`ai_stock_source` 只读对照，直到按服务整包迁入。

## D-20260902-02 MACP 不替代智力

MACP 协调四模型，不替换认知。Agent 不是模型或交易员。

## D-20260902-03 瘦 Control Plane

只允许注册表、决策记录、恢复提案审批、上下文索引。
禁止新调度、新采集、新 owner、新 inspector 执行面。

## D-20260902-04 叠加不重建

迁入是整包搬家，不是按目录名重写。

## D-20260902-05 数据可靠性智能

最高价值增量：影响分析 → 优先级 → 决策记录 → 原编排执行。

## D-20260902-06 知识基线

`archive/knowledge_baseline_v1_1` 只读。现行文档在 `docs/`。

## D-20260902-07 锁定服务

未按服务名解锁，不得改下列服务的逻辑与运行合同：

`postgres`、`schema-bootstrap`、`source-data-service`、`source-data-worker`、`hot-candidates-service`、`candidate-memory-service`、`ambush-watchlist-service`、`t-board-relay-service`、`scheduler-service`、`data-inspector-service`

整包迁入只改路径，仍须先解锁对应服务名。

## D-20260902-08 真实结构

根目录能力树（`macp/` `data_foundation/` `intelligence/` `runtime/` `research/` `frontend/` `packages/` `infra/` `scripts/`）是代码落点。
`docs/` 只放治理。过时骨架与重复 README 已清理。

## D-20260902-09 共享包迁入

- `packages/common` 已整包复制并导入自检。
- `packages/db-schema` + `infra/sql` 已复制；未对运行库执行 bootstrap，未替换 schema-bootstrap。

## D-20260902-10 全量 copy-only

用户授权“你决定即可 / 最高权限”。已将映射服务整包复制到落点，只改 Compose/Dockerfile 路径。
未切换运行容器，未复制 `infra/env`，未执行 bootstrap。
对照源保持只读。
