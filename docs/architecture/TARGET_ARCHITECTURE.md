# 目标架构

`D:\ai_stock` 是后期 MACP 系统本体。现有能力从 `ai_stock_source` 整包迁入，不在源码树里继续发展。

## 仓库布局

```text
D:\ai_stock\
  AGENTS.md
  需优化点.MD
  ai_stock_source\                 迁入前只读对照
  archive\knowledge_baseline_v1_1\ 只读旧原则
  docs\                            治理文档
  macp\                            瘦 Control Plane（新叠加）
  data_foundation\                 source-data-service + worker
  intelligence\                    四模型 + 跨模型评估
  runtime\                         scheduler + data-inspector
  research\                        assembler + research-center
  frontend\                        shence-frontend
  packages\                        common / db-schema / macp-contracts
  infra\
  scripts\
```

## 层（治理）

```text
macp/                  注册、决策、恢复提案、上下文
research/              组装与研究资产，不写生产公式
intelligence/          四模型认知 + evaluation 视图
runtime/               调度与巡检
data_foundation/       标准事实
packages/ + infra/     合同、schema、部署
```

## 管道（运行）

```text
provider
-> data_foundation raw/quality/source/lineage/preflight
-> research 组装 payload
-> intelligence owner 计算
-> append-only 落库
-> runtime inspector 巡检
-> runtime scheduler 调度
-> frontend / 后续 gateway / Jarvis 只读
```

缺块不得伪装已有：`research-data-mart`、`gateway-service`、`execution-timing-service`、`dynamic-feature-service`、完整 Jarvis。

## Control Plane

允许：登记能力、恢复提案、统一评估视图、会话恢复。
禁止：新调度运行时、新采集面、新模型 owner、直接补数或改分数。
