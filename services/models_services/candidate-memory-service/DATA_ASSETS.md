# candidate-memory-service DATA_ASSETS

本文件是 `candidate-memory-service` 的数据资产账本，不替代本目录 `README.md`。

## 读取数据

| 资产 | 用途 |
|---|---|
| `source.trade_calendar_v1` | `memory_age_days`、T+5/T+20/T+40 成熟窗口 |
| `source.stock_master_v1`、`source.trade_status_v1` | 身份、可交易性、ST/停牌阻断 |
| `source.daily_bar_v1`、`source.adjusted_daily_bar_v1` | 路径、趋势、结构和历史观察 |
| `source.stock_moneyflow_daily_v1` | 资金恢复/二波确认，P1 degraded |
| `source.event_news_v1` | 事件 ex-ante 证据 |
| 热点成熟样本/信号合同 | seed/entity 来源 |
| `/source/release/preflight` | official release 前 source 门禁 |

## 目标写入表

当前 owner service 本身不直接写生产库；目标合同包括 `decision_memory.memory_seed_v1`、`memory_entity_v1`、`memory_feature_*`、`memory_pre_signal_case_v1`、`memory_activation_case_v1`、`memory_release_gate_audit_v1`、`memory_signal_fact_v1`、`memory_buy_point_v1`、`memory_outcome_label_v1`、`memory_failure_attribution_v1`、`memory_evolution_sample_v1`、`memory_latest_state_v1` 等。兼容运行事实还包括 `decision.candidate_memory_*` 表。

## 调度频率

- 热点成熟后 seed/entity。
- 15:55 pre-signal，10:30 可选研究扫描。
- 16:05 release gate。
- 下一交易日 09:30-10:00 买点评估。
- 每日 15:50 与 T+5/T+20/T+40 outcome/evolution。

## 禁止事项

缺交易日历年龄时 `memory_age_days=NULL`，状态为 `blocked_data_gap`；不得用自然日、0 或空字符串伪装交易日龄。

