# macp

状态：`new_overlay`

瘦 Control Plane。源码无对应服务，阶段 5 再写代码。

## 模块

| 目录 | 职责 |
|---|---|
| `registry/` | 能力登记 |
| `contracts/` | 引用现有合同，不覆盖源码合同 |
| `evolution/` | 演化提案与批准流 |
| `governance/` | 决策与知识生命周期 |
| `context/` | 会话恢复索引 |

## 禁止

新调度、新采集、新 owner、执行补数、改模型分数。
