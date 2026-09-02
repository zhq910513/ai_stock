# hot-candidates-service DATA_ASSETS

本文件是 `hot-candidates-service` 的数据资产账本，不替代本目录 `README.md`。

## 读取数据

| 资产 | 用途 |
|---|---|
| `source.trade_calendar_v1` | T+5/T+20 outcome 和交易日窗口 |
| `source.ths_paid_limit_up_probability_v1` | 同花顺付费次日概率教师先验；只读消费，缺失时阻断/等待或由 source-data-service deadline 判定放弃批次 |
| `source.stock_master_v1`、`source.trade_status_v1` | 身份、可交易性、ST/停牌阻断 |
| `source.daily_bar_v1` | 日线、收益、风险、涨跌停状态 |
| `source.auction_snapshot_v1` | 竞价确认 |
| `source.minute_bar_v1`、`source.realtime_quote_v1` | 开盘 5 分钟买点和盘中观察 |
| `source.stock_moneyflow_daily_v1` | 资金确认，P1 degraded |
| `source.event_news_v1` | 新闻/题材 research-only 上下文 |
| `/source/release/preflight` | official release 前 source 门禁 |

## 目标写入表

当前 owner service 本身不直接写生产库；目标合同包括 `decision_hot.hot_cycle_v1`、`hot_decision_case_v1`、`hot_feature_matrix_v1`、`hot_score_fact_v1`、`hot_release_gate_audit_v1`、`hot_signal_fact_v1`、`hot_buy_point_v1`、`hot_observation_snapshot_v1`、`hot_outcome_label_v1`、`hot_failure_attribution_v1`、`hot_evolution_sample_v1` 等。实际落库应由 research-service 或后续编排/仓储层执行。

## 调度频率

- 09:15-09:25 竞价采集。
- 15:20/16:05/18:00/20:30 source-data-service 自动抓取同花顺付费概率；09:01 deadline guard 只在下一交易日 09:00 后放弃仍未补齐批次。
- 09:25:05/09:25:30 竞价冻结。
- 09:26/09:28/09:29:30 评分。
- 09:25:40/09:28:40/09:29:40 release gate。
- 09:30-09:36 开盘买点。
- 09:30-15:00 观察。
- 15:10/15:40 与 T+5/T+20 outcome。

## 禁止事项

不直接采 provider、不读 raw、不读取或保存同花顺 Cookie、不反写前端/Jarvis/学习权重、不把缺同花顺概率或 source 事实补成 0、手填值、随机值或旧 payload。Cookie 失效或取不到时，下一交易日 09:00 前只能阻断/等待；只有 source-data-service 标记批次放弃后，本服务才可把该批候选作为 abandoned 处理。

## 数据资产冻结记录

### hot-candidates-service -> source probability prior -> model1 closure evidence

- 冻结时间：2026-06-21。
- 拍板人 / 确认来源：用户在模型一只读闭环审查任务书后回复“批准”。
- 锁定范围：只读读取 `source.ths_paid_limit_up_probability_v1` 作为教师先验；只读读取行情、竞价、分钟、资金、新闻、交易日历和 source preflight；目标 `decision_hot.*` 合同表由编排/仓储层 append-only 落库；本服务不保存 Cookie、不采 provider、不读 raw。
- 关联表：`source.limit_event_v1` 作为候选 universe 上游事实，`source.ths_paid_limit_up_probability_v1` 作为付费概率教师先验，`source.daily_bar_v1`、`source.adjusted_daily_bar_v1`、`source.minute_bar_v1`、`source.realtime_quote_v1`、`source.auction_snapshot_v1`、`source.stock_moneyflow_daily_v1`、`source.event_news_v1`、`source.trade_calendar_v1`、`source.trade_status_v1` 为评分、买点、观察和 outcome 输入；`decision_hot.hot_score_fact_v1`、`decision_hot.hot_release_gate_audit_v1`、`decision_hot.hot_signal_fact_v1`、`decision_hot.hot_buy_point_v1`、`decision_hot.hot_observation_snapshot_v1`、`decision_hot.hot_outcome_label_v1`、`decision_hot.hot_failure_attribution_v1`、`decision_hot.hot_evolution_sample_v1` 为下游事实合同。
- 当前运行事实：source 付费概率 Cookie 当前 `configured=false/status=missing`；`2026-06-18` 批次为 `pending_cookie`，87 只候选未抓取概率，deadline 为 `2026-06-22 09:00 Asia/Shanghai`。该缺口必须保留为阻断/等待或由 source-data-service deadline guard 标记放弃，不得由本服务补值。
- 允许的只读验收：读取 source rows、source preflight、scheduler 热点校验、source 付费概率 cookie/status 与 batch-status、source 队列摘要、模型一 owner ready 和单元测试。
- 禁止修改项：未经解锁不得改变上述读取表、目标表、调度频率、source preflight hard block、Cookie 归属、概率缺失处理、行级异常缺口码和下游只读消费边界；不得把 `source.ths_paid_limit_up_probability_v1` 缺失替换为 0、空字符串、前端手填、随机值、旧样例或 GPT 推断。
- 解锁条件：用户明确批准本冻结对象解锁；若涉及 source 付费概率表、Cookie 留存、provider probe、scheduler source schedule 或前端 Cookie 表单，必须同时解锁对应 source-data-service、scheduler-service 或 shence-frontend-service 对象。
- 回滚方式：回退本服务 DATA_ASSETS/README 中冻结对象的后续变更，恢复当前只读 source 标准层和 append-only `decision_hot.*` 合同口径；回滚后重新验证 source preflight、scheduler 热点计划和模型一单测。
- 验证清单：`python -m pytest -q -p no:cacheprovider services/models_services/hot-candidates-service/tests`；`GET /scheduler/validate/hot-candidates`；`GET /scheduler/validate/source-schedule`；`GET /source/ths/paid-probability/cookie/status`；`GET /source/ths/paid-probability/batch-status?trade_date=2026-06-18`。

### hot-candidates-service -> model1 reset -> 2026-07-08 data asset state

- 记录时间：2026-07-08 Asia/Shanghai。
- 确认来源：用户批准“按此范围清理模型一数据，无需备份历史数据”，随后用户回复“你来决定”，由 Codex 判定本轮清理事实可拍板记录。
- 已清数据资产：`decision_hot.*` 全部模型一事实表清零；`governance.research_model_execution_audit_v1` 中模型一相关执行审计清零。
- 保留数据资产：`source.ths_paid_limit_up_probability_v1`、`raw_ths.paid_limit_up_probability_v1`、`governance.ths_paid_probability_batch_status_v1`、`governance.ths_paid_probability_cookie_v1`、source lineage、source queue、scheduler task store 均保留。
- 验收事实：`decision_hot_total=0`、模型一 execution audit 剩余 `0`、research hot list `item_count=0`；source 概率 `279` 行、raw 概率 `309` 行、批次状态 `17` 行、Cookie `3` 行仍在；source queue `queued=0/leased=0/dead_letter=0`。
- 当前等待资产状态：`2026-07-08` 付费概率批次 `status=no_candidates`、`candidate_count=0`、`fetched_count=0`、`cookie_status=expired`、deadline `2026-07-09T01:00:00Z`。模型一重新产出只能由真实候选批次、有效 Cookie、source build/lineage、research execution 和 owner materialization 正式链路生成。
- 禁止事项：不得手写 `decision_hot.*`、不得直接写 `source.*` 或 `raw_ths.*`、不得补 0/空字符串/mock/GPT 推断、不得跳过 source preflight 或把当前空表解释为已恢复产出。
- 回滚方式：本轮按用户要求未备份历史模型一数据，删除事实不可从备份恢复；后续只能通过正式 source/scheduler/research/model 链路重新产生新事实。
