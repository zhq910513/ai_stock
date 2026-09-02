# 模型架构

代码落点：`intelligence/*-service`。

## 受保护资产

| 模型 | 落点 | 定位 |
|---|---|---|
| hot-candidates | `intelligence/hot-candidates-service` | T+1/T+5/T+20 |
| candidate-memory | `intelligence/candidate-memory-service` | 延迟兑现、二波 |
| ambush-watchlist | `intelligence/ambush-watchlist-service` | 潜伏抬头 |
| t-board-relay | `intelligence/t-board-relay-service` | T 字板接力；research-only |

## 三者不得合并

Model = 投资认知；Service = 执行载体；Agent = 只读助手（未建）。

owner 统一：`/healthz`、`/readyz`、`structured_output`、`contract_gaps`。

## 演化

```text
Fact -> Observation -> Prediction -> Outcome
-> Evaluation -> Proposal -> Approved Change
```

现有 evolution 端点只产样本，不得自动改生产权重。
批准写入 `docs/decisions/ACTIVE`。

跨模型只读视图落在 `intelligence/evaluation`，阶段 4 再实现。
