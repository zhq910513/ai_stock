# ambush-watchlist-service DATA_ASSETS

本文件是 `ambush-watchlist-service` 的数据资产账本，不替代本目录 `README.md`。

## 读取数据

| 资产 | 用途 |
|---|---|
| `source.stock_master_v1`、`source.trade_status_v1` | 深圳 A 股范围、可交易性、ST/停牌/退市阻断 |
| `source.daily_bar_v1`、`source.adjusted_daily_bar_v1` | 低谷图形、有效抬头、风险结构 |
| `source.adjustment_factor_v1` | 复权审计 |
| `source.stock_moneyflow_daily_v1` | L3/L4 资金确认，P1 degraded |
| `source.index_daily_bar_v1`、市场环境事实 | 相对强弱和环境 |
| `source.event_news_v1` | 题材/事件 research-only 上下文 |
| `/source/release/preflight` | official release 前 source 门禁 |

## 目标写入表

当前 owner service 本身不直接写生产库；目标合同包括 `decision_ambush.valley_pattern_*`、`ambush_daily_window_feature_v1`、`valley_watch_pool_v1`、`effective_turn_anchor_v1`、`ambush_feature_matrix_v1`、`ambush_score_fact_v1`、`ambush_release_gate_audit_v1`、`ambush_signal_fact_v1`、`ambush_buy_point_v1`、`ambush_outcome_label_v1`、`ambush_failure_attribution_v1`、`ambush_evolution_sample_v1` 等。研究中心低谷图库写入 `research_ambush.*`，不由本 owner service 直接写。

## 调度频率

- source capability：每周或新 provider 激活前。
- 图库挖掘：每日 18:10 增量，月度全量。
- Phase2：15:20 收盘后，可选 10:30 研究扫描。
- Phase3 release gate：15:35。
- observation/outcome/evolution：15:55 与 T+5/T+10/T+20。

## 禁止事项

不直接调用 provider；缺 adjusted OHLC、moneyflow、event 或 market context 时保留缺口，不补 0 或 mock。


### ambush-watchlist-service -> model3 reset -> 2026-07-08 data asset state

- Record time: 2026-07-08 Asia/Shanghai.
- Confirmation source: user explicitly approved clearing model2/model3 execution audit and model3 taxonomy without historical backup, and explicitly requested not to start model2/model3 owner services.
- Cleared audit scope: `governance.research_model_execution_audit_v1` rows where `model_code='ambush_watchlist'`, `owner_service='ambush-watchlist-service'`, `task_code LIKE 'ambush.%'`, or `task_code LIKE 'dragon.%'`; `3` rows were deleted.
- Cleared asset scope: `research_ambush.ambush_valley_label_taxonomy_v1`; `11` taxonomy rows were deleted.
- Current asset state: all current `decision_ambush.*`, `research_ambush.*`, compatible `decision.ambush_*`, and compatible `decision.dragon_*` tables have `0` rows.
- Preserved scope: source standard tables, raw provider tables, lineage, source fetch queue, scheduler task store, provider probe evidence, Cookie/runtime source credentials, and owner service code/config were not cleared or rewritten.
- Runtime state: `ai-stock-ambush-watchlist-service` remains `Exited (0)` as requested.

### ambush-watchlist-service -> model3 reset -> zero-data asset freeze 2026-07-08

- 冻结对象：`ambush-watchlist-service -> model3 reset -> zero-data asset state`。
- 冻结时间：2026-07-08 Asia/Shanghai。
- 拍板人 / 确认来源：用户授权 Codex 决定拍板；Codex 判定当前模型三数据资产已满足零数据状态。
- 锁定范围：`decision_ambush.*`、`research_ambush.*`、兼容 `decision.ambush_*`、兼容 `decision.dragon_*`、`research_ambush.ambush_valley_label_taxonomy_v1` 和模型三 execution audit 的零行状态；source/raw/lineage/source queue/scheduler task store/provider probe/Cookie 均不属于本冻结对象。
- 允许的只读验收：只读 SQL 计数、taxonomy 计数、owner 容器状态查看、核心服务 readyz、source queue summary。
- 禁止修改项：未经解锁不得直接插入、更新或删除模型三事实资产或 taxonomy 字典；不得重启 owner 来掩盖缺口；不得把缺 source、缺图库、缺 event/news、缺 moneyflow 或缺 market context 补成 `0`、空字符串或 mock。
- 解锁条件：用户明确批准模型三 owner 启动、模型三数据再生、taxonomy/图库字典重新初始化、执行审计恢复、数据资产合同变化或调度恢复。
- 回滚方式：无本轮数据备份；恢复事实或 taxonomy 只能走正式初始化/研究/调度链路再生成，不能手工补库。
- 验证清单：所有模型三资产计数为 0；模型三 audit 计数为 0；taxonomy 计数为 0；ambush owner 保持退出；source/scheduler/data-inspector/research ready。
