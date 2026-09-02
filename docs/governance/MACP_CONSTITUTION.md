# MACP 宪法

## 原则

1. 保护四个核心投资模型，MACP 只协调不替代。
2. 未知代码合同不得猜测，未知依赖不得发明。
3. 优先最小工程：无证据不改，无价值不抽象。
4. 架构变更必须留下决策记录与版本。
5. 实际生成物才是真相，文档不得伪装未落地能力。

## 从原项目升格的硬法

1. 锁定服务未经按服务名解锁，不得改源码逻辑、schema、Docker 合同或测试口径。
2. 锁定清单：`postgres`、`schema-bootstrap`、`source-data-service`、`source-data-worker`、`hot-candidates-service`、`candidate-memory-service`、`ambush-watchlist-service`、`t-board-relay-service`、`scheduler-service`、`data-inspector-service`。
3. 取数必须走 `data_foundation/source-data-service` 迁入后的 fetch orchestration。
4. 不得把 `raw_*` 当模型输入。
5. 缺事实保留 `NULL` / 缺口码 / 阻断，禁止 0、空字符串、mock、GPT 推断。
6. 前端与 Jarvis 只读，不得改分数、闸门、买点、学习权重。
7. official 与 research-only 分开；`t_relay.*` 全部非 official。
8. 普通迭代不得重启 `source-data-service` API 容器。
9. 数据缺陷必须沿全链路归因。

## 仓库结构红线

1. `D:\ai_stock` 是后期 MACP 系统本体；`ai_stock_source` 只是迁入对照。
2. 可运行代码只落在约定落点，不落在 `docs/`、`archive/`。
3. 落点目录在迁入前禁止手写第二套实现。
4. Control Plane 只做注册、决策、恢复提案审批、上下文索引。
5. 知识基线只增版本，旧基线进 `archive/`，不覆盖。
