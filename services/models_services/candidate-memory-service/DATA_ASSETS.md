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


### candidate-memory-service -> model2 reset -> 2026-07-08 data asset state

- Record time: 2026-07-08 Asia/Shanghai.
- Confirmation source: user explicitly approved clearing model2/model3 execution audit and model3 taxonomy without historical backup, and explicitly requested not to start model2/model3 owner services.
- Cleared audit scope: `governance.research_model_execution_audit_v1` rows where `model_code='candidate_memory'`, `owner_service='candidate-memory-service'`, or `task_code LIKE 'memory.%'`; the audit scope was already empty, so `0` rows were deleted.
- Current asset state: all current `decision_memory.*`, `research_memory.*`, and compatible `decision.candidate_memory*` tables have `0` rows.
- Preserved scope: source standard tables, raw provider tables, lineage, source fetch queue, scheduler task store, provider probe evidence, Cookie/runtime source credentials, and owner service code/config were not cleared or rewritten.
- Runtime state: `ai-stock-candidate-memory-service` remains `Exited (0)` as requested.

### candidate-memory-service -> model2 reset -> zero-data asset freeze 2026-07-08

- 冻结对象：`candidate-memory-service -> model2 reset -> zero-data asset state`。
- 冻结时间：2026-07-08 Asia/Shanghai。
- 拍板人 / 确认来源：用户授权 Codex 决定拍板；Codex 判定当前模型二数据资产已满足零数据状态。
- 锁定范围：`decision_memory.*`、`research_memory.*`、兼容 `decision.candidate_memory*` 和模型二 execution audit 的零行状态；source/raw/lineage/source queue/scheduler task store/provider probe/Cookie 均不属于本冻结对象。
- 允许的只读验收：只读 SQL 计数、owner 容器状态查看、核心服务 readyz、source queue summary。
- 禁止修改项：未经解锁不得直接插入、更新或删除模型二事实资产；不得重启 owner 来掩盖缺口；不得把缺失交易日龄、缺 source 或缺 upstream 事实补成 `0` 或空值。
- 解锁条件：用户明确批准模型二 owner 启动、模型二数据再生、执行审计恢复、数据资产合同变化或调度恢复。
- 回滚方式：无本轮数据备份；恢复事实只能走正式链路再生成，不能手工补库。
- 验证清单：所有模型二资产计数为 0；模型二 audit 计数为 0；candidate-memory owner 保持退出；source/scheduler/data-inspector/research ready。
