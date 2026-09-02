# 数据架构

代码落点：`data_foundation/source-data-service`。

## 三分法

| 类别 | 含义 | 落点 | 禁止 |
|---|---|---|---|
| Fact | 可追溯市场事实 | `source.*`；raw 仅审计 | 含投资结论 |
| Context | 已组装研究输入 | `research/research-service` | sample 冒充生产 |
| Inference | 模型判断 | `intelligence/*` | 回写成 source |

## 正规链路

```text
provider
-> raw（request_hash / schema_hash / row_hash）
-> quality（build_allowed=false 不得进 source）
-> source build
-> governance.source_lineage_v1
-> /source/release/preflight
-> research 组装或 blocked_data_gap
```

P0 + online required 字段必须有主源、备源、raw、repair plan、lineage、质量规则、`available_at`。

## 状态

执行与智力状态不得混用。

- 采集：`queued` / `leased` / `succeeded` / `failed` / `dead_letter`
- 任务：`CREATED` / `QUEUED` / `RUNNING` / `SUCCESS` / `FAILED`
- 组装：`assembled_research_payload` / `blocked_data_gap`
- 模型四：`continue_watch` / `data_wait` / `stopped` / `completed`
- 巡检：`ready` / `degraded` / `blocked`
- 知识：`ACTIVE` / `SUPERSEDED` / `ARCHIVE`

## 数据可靠性智能

现网：`Detect -> remediation(suggested)`。
目标：影响分析 → 优先级 → MACP 决策 → 原编排执行。
inspector 只读；`macp/` 只审批，不补数。
