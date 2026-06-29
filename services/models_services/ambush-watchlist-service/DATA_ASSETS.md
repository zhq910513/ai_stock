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

