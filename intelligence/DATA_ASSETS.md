# models_services DATA_ASSETS

本文件是模型服务集合层数据资产账本，不替代本目录 `README.md` 或各模型子服务 `README.md`。

## 集合边界

四个模型 owner service 只接收已组装 payload，执行模型合同计算并返回结构化结果。生产 payload 由 `research-service` 的 `research_model_payload_assembler_v1` 从已构建 `source.*` 和允许的上游模型事实组装；模型服务集合层不直接调用 provider，不直接读取 raw，不修改 frontend/Jarvis/交易/学习权重。三模型 official 发布必须同时满足 owner release gate 和 source-data-service preflight；模型四当前全部 non-official。

## 共享读取资产

| 资产 | 用途 | 使用方 |
|---|---|---|
| `source.trade_calendar_v1` | T+N、记忆年龄、outcome 窗口 | hot、memory、ambush、t-board |
| `source.stock_master_v1`、`source.trade_status_v1` | 身份、可交易、ST/停牌/退市阻断 | 全部模型 |
| `source.daily_bar_v1` | 未复权行情、收益、涨跌停、买点 | 全部模型 |
| `source.adjusted_daily_bar_v1` | 图形、历史结构、记忆趋势 | memory、ambush |
| `source.limit_price_v1`、`source.limit_event_v1` | 涨跌停、THS 公开涨停池和 T 字板结构 | t-board、候选输入链路 |
| `source.realtime_quote_v1.float_market_cap`、`source.minute_bar_v1`、`source.trade_tick_v1` | 模型四 Day1 流通市值、Day2 接力窗口和热点开盘/盘中观察 | hot、t-board |
| `source.stock_moneyflow_daily_v1`、`source.event_news_v1` | 资金/事件上下文 | hot、memory、ambush |
| `/source/release/preflight` | release 前 source 门禁 | scheduler、data-inspector、三模型 official |

## 写入资产

前三模型当前 owner service 本身不直接写生产数据库，目标表由后续编排/仓储层持久化。模型四 `t-board-relay-service` 在 repository attached 时可直接 append-only 写 `decision_t_relay.*` / `research_t_relay.*`；其中 `decision_t_relay.t_board_observation_monitor_snapshot_v1` 专门留存普通用户观察台当前输出的 5 分钟快照，用于三交易日回放、模型分排序审计和后续调优。

## 禁止事项

- 不直接调用 BaoStock、AKShare、Tencent、Tushare、EastMoney、Baidu、CNINFO、THS、Sina、Sohu。
- 不直接读取 raw 表。
- 不用 sample payload、0、空字符串或推断值补缺口。
- 不把模型四 research 结果发布为 official signal。
- 不让模型四 Day1 高频/报价全 A 盲扫；模型四先读 `source.limit_event_v1` 涨停池/T 字板候选，再候选级补事实。模型三所需全 A 日频底座继续保留。
