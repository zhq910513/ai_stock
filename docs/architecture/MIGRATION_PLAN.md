# 迁移计划

原则：按本仓库真实结构整包迁入，不重建、不改合同、不另写第二套运行时。

## 阶段

| 阶段 | 名称 | 做什么 | 不做什么 |
|---:|---|---|---|
| 0 | 源码事实审计 | 已完成 | 改源码 |
| 1 | 治理叠加 | 已完成 | 弱化硬法 |
| 1.5 | 真实结构落地 | 已完成 | 搬业务服务代码 |
| 2 | 整包迁入 | 业务服务已 copy-only 到落点；Compose 路径已改但未切运行 | 重写逻辑；未跑 bootstrap；未重启容器 |
| 3 | 数据可靠性智能 | inspector 影响分析 + 恢复提案 | 新采集面、自动执行 |
| 4 | 评估/演化统一视图 | 消费已有 outcome/evolution | 新造评分引擎 |
| 5 | 瘦 Control Plane | 实现 `macp/` 注册与审批 | 替换 scheduler |
| 6 | Agent | 只读助手 | 写事实、自动交易 |

## 阶段 2 迁入规则

1. 一次只迁一个已解锁服务包。
2. 保持 Python 包名、API、表、Docker 角色。
3. 只改导入路径、Compose `SERVICE_DIR`、文档路径。
4. 迁完以源码 README / 测试 / healthz 为验收，不以“目录好看”为验收。
5. `ai_stock_source` 在该包验收前保持只读对照，验收后再标 `migrated`。

## 禁止当新项目重写

`source-data-service`、`source-data-worker`、`scheduler-service`、四模型 owner、`data-inspector-service` 只读边界。
