# research-service DATA_ASSETS

## Hot Score Daily Bar Fallback Asset Contract

2026-06-26 asset contract: `hot.score.auction_confirmed` reads both `source.daily_bar_v1` and `source.adjusted_daily_bar_v1`. If the unadjusted daily row is missing for a paid-probability candidate while adjusted daily rows are present, usable, and source-built, `research-service` may expose those adjusted rows as normalized owner-facing `daily_bars` for the hot score stage only. The normalized rows map `adjusted_open/high/low/close` to `open_price/high_price/low_price/close_price` and preserve source audit fields such as `available_at`, `lineage_id`, and `build_batch_id`.

The fallback keeps the original `source.adjusted_daily_bar_v1` asset visible through `adjusted_daily_bars`, marks `daily_bar_source=source.adjusted_daily_bar_v1`, and records `source_gap:daily_bar_missing_using_adjusted_daily_bar` as a warning. It does not write `source.daily_bar_v1`, does not read raw/provider tables, does not change source-data-service orchestration, and does not apply to release gate, buy point, outcome, evolution, memory, ambush, or T relay tasks.

## Hot Stage Case Reuse Asset Contract

2026-06-27 asset contract: `decision_hot.hot_decision_case_v1` is created by the hot score stage only. `hot.release_gate.preopen` and `hot.buy_point.open_5m` read the existing case through assembled upstream facts and may append `decision_hot.hot_release_gate_audit_v1`, `decision_hot.hot_signal_fact_v1`, and `decision_hot.hot_buy_point_v1` rows returned by the owner. These stage tasks do not write another `hot_cycle_v1`, `hot_decision_case_v1`, or `hot_evidence_snapshot_v1` row.

For non-score stages, the materializer resolves the case lineage from assembled `upstream_model_facts["decision_hot.hot_decision_case_v1"]` first. Owner top-level ids and nested `hot_signal` / `buy_point` ids are used only when they match the upstream scored case; when owner emits a different generated case id, research-service regenerates deterministic signal/buy ids under the upstream case and does not trust the owner ids as lineage. Missing lineage on a non-score stage is a materialization skip, not a license to generate a new case from `payload_hash`. This keeps frontend and DB projections case-linked and prevents duplicate hot decision cases after scheduler catch-up or service restart.

本文件是 `research-service` 的数据资产账本，不替代本目录 `README.md`。

## 服务定位

`research-service` 读取已构建的 `source.*` 标准事实和允许的上游模型事实，组装 `research_model_payload_assembler_v1` payload。上游事实若携带硬阻断 `source_gap_codes` / `gap_codes` / `contract_gaps` 或 sample 标记，组装结果必须落为 `blocked_data_gap`。模型四 Day2 watch/trigger、触发后监控、Day3 去留和 outcome 对 owner 已定义为可审计研究缺口的上游 gap 只进入 `warnings` / `warning_codes`，不阻断真实 source 组装。当 `scheduler-service` 开启模型任务 live dispatch 时，本服务通过 `research_model_execution_v1` 调用 owner service，并只把 owner 返回的结构化结果物化到对应 `decision_*` / `research_*` 表。它不采 provider、不读 raw、不计算模型分数、不自行发布或提升 official signal。

## 读取数据

| 资产 | 用途 | 边界 |
|---|---|---|
| `source.trade_calendar_v1` | T+N、成熟窗口和交易日年龄 | 只读，缺失保留 gap |
| `source.stock_master_v1` | 标的身份、名称、交易所 | 只读 |
| `source.trade_status_v1` | 可交易/ST/停牌/退市风险 | P0 只读 |
| `source.daily_bar_v1` | 日线行情基座 | P0 只读 |
| `source.adjusted_daily_bar_v1` | 复权图形和路径 | P0/P1 只读 |
| `source.limit_price_v1` | 涨跌停价格 | T 字板 Day1/Day2、买点只读；Day2 用 `up_limit_price` 计算滚动监测点距离涨停 |
| `source.limit_event_v1` | 涨停/T 字板事件 | T 字板只读 |
| `source.ths_paid_limit_up_probability_v1` | 同花顺付费次日概率 | 热点模型前端只读投影和准备度 P0 维度；缺失保留缺口，不补 0 |
| `source.stock_moneyflow_daily_v1` | 资金上下文 | P1 只读，缺失 degraded/gap |
| `source.moneyflow_stock_snapshot_v1` | 资金快照上下文 | 热点准备度 P1 备用只读事实；缺失 degraded/gap |
| `source.market_regime_snapshot_v1` / `source.index_daily_bar_v1` | 市场环境上下文 | 热点准备度 P1 只读事实；缺失 degraded/gap |
| `source.stock_board_membership_v1` / `source.board_daily_bar_v1` | 题材板块上下文 | 热点准备度 P1 只读事实；缺失 degraded/gap |
| `source.event_news_v1` | 事件上下文 | research-only 只读 |
| `source.realtime_quote_v1` | 开盘/盘中/模型四窗口 | 分钟级只读；`hot.release_gate.preopen` 不把它作为 research payload 硬依赖 |
| `source.minute_bar_v1` | 开盘 5 分钟、盘中观察、T 字板 Day2/Day3 | 分钟级只读；`hot.release_gate.preopen` 不把它作为 research payload 硬依赖 |
| `source.trade_tick_v1` | T 字板 Day2 盘口吃单 | 09:30-10:30 窗口级只读；`side_code/amount` 只作为 provider-native 逐笔侧向证据，不等同完整五档盘口 |
| `decision_hot.hot_decision_case_v1`、`decision_hot.hot_release_gate_audit_v1`、`decision_hot.hot_buy_point_v1` | 热点模型前端只读列表投影 | 只读；供 `GET /research/model-list/hot` 合并已落库决策、发布闸门和买点上下文；同一 `symbol + trade_date` 存在历史重复 case 时优先只读已关联 `hot_score_fact_v1` 的 scored current case，旧重复 case 留库审计但不作为当前展示行；不计算分数、不生成买点、不改 release gate |
| `decision_hot.hot_score_fact_v1`、`decision_hot.hot_evidence_snapshot_v1` | `hot.release_gate.preopen` 上游评分和证据 | 只读；通过 `decision_hot.hot_decision_case_v1.hot_case_id` 按 `symbol + trade_date` 关联；缺失、硬阻断 gap 或 sample 标记时阻断；不得等待自身 `hot_signal_fact_v1` |
| `decision_hot.hot_signal_fact_v1` | 热点观察、outcome/evolution 上游事实；buy-point owner 返回 signal 时的 append-only 关联事实 | 只读上游时携带缺口或 sample 标记则阻断；写入时必须保持 owner 返回的 `is_official_signal` / `is_research_only`，不得把 research-only 升级成 official |
| `decision_hot.hot_outcome_label_v1` / `decision_hot.hot_evolution_sample_v1` | 热点后验验证与演化上下文 | 热点准备度 P2 只读事实；未成熟时保留缺口，不显示成功 |
| `decision_memory.memory_entity_v1` | `memory.pre_signal.scan` 上游实体 | 只读；缺失时阻断 |
| `decision_memory.memory_pre_signal_case_v1`、`decision_memory.memory_score_fact_v1` | `memory.release_gate.close` 上游 pre-signal 和评分 | 只读；缺失时阻断；不得等待自身 `memory_signal_fact_v1` |
| `decision_memory.memory_signal_fact_v1` | 候选记忆买点、观察、outcome/evolution 上游事实 | 只读；携带缺口或 sample 标记时阻断 |
| `decision_ambush.ambush_outcome_label_v1`、`decision_ambush.ambush_failure_attribution_v1` | `ambush.pattern_library.mine` 离线图库上游事实 | 只读；缺失时阻断 |
| `decision_ambush.effective_turn_pool_v1` | `ambush.phase3.release_gate.close` 上游有效抬头池 | 只读；缺失时阻断；不得等待自身 `ambush_signal_fact_v1` |
| `decision_ambush.ambush_signal_fact_v1` | 潜伏买点、观察、outcome/evolution 上游事实 | 只读；携带缺口或 sample 标记时阻断 |
| `decision_t_relay.t_board_day1_candidate_v1` | T 字板 Day2 watch/trigger 上游候选事实 | 只读；sample 标记硬阻断；`source_gap:seal_order_snapshot_missing` 对 Day2 为 warning |
| `decision_t_relay.t_board_day2_watch_snapshot_v1` | T 字板 Day2 trigger 上游观察快照 | 只读；sample 标记硬阻断；动态特征 / 吸收分研究缺口对 Day2 trigger 为 warning；进入 owner payload 前剔除 `request_payload`、`result_payload`、`game_hypothesis_payload`、`evidence_json`、`related_payload` 等审计大字段 |
| `decision_t_relay.t_board_day2_entry_trigger_v1`、`decision_t_relay.t_board_post_entry_monitor_v1`、`decision_t_relay.t_board_day3_exit_decision_v1` | T 字板后续阶段链上游事实 | 只读；sample 标记或硬阻断缺口仍阻断；`seal_order_snapshot_missing`、`dynamic_feature_bundle_missing`、`near_limit_order_absorption_missing` 对 post-entry、Day3、outcome 为 warning-only |
| `source-data-service /source/release/preflight` | official release 和模型四 Day1/P0 source preflight；不用于 `t_relay.day2.trigger.rolling_5m` 研究触发 | 只读 HTTP |
| `scheduler-service /scheduler/model-payload/assemble-preflight` | 下游显式组装+预检联调入口 | scheduler 只调用本服务组装并预检，不触达 owner endpoint；`blocked_data_gap` 必须阻断 |
| `scheduler-service /scheduler/model-time-wheel/run-once`、`scheduler_model_time_wheel_v1` | 正式模型任务触发入口 | scheduler live dispatch 只调用本服务 `/research/model-execution/run`，不得直连 owner |
| `scheduler-service /scheduler/model-schedule/catch-up` | 模型任务迟到窗口补偿/对账入口 | 只补 scheduler 本地模型任务实例并通过 `/research/model-execution/run` 派发；不得补 source/provider 事实 |
| 四个模型 owner service production endpoints | owner 评分、release gate、买点、观察、outcome 或研究输出 | 仅由 `/research/model-execution/run` 在 payload assembled 后调用；owner 失败保留审计 |

## 热点模型数据准备度资产

`GET /research/model-list/hot` 的 `hot_model_data_readiness_v1` 是只读投影资产，不是模型评分、不替代 release gate，也不写入数据库。它把热点模型产出所需事实拆成固定 13 个维度，按 P0/P1/P2 配权，总分 100，用于展示“已具备多少、还缺多少、是否被 P0 阻断”。

| 优先级 | 维度 | 权重 | 只读来源 |
|---|---:|---:|---|
| P0 | 候选与可交易 | 12 | `decision_hot.hot_decision_case_v1`、`source.stock_master_v1`、`source.trade_status_v1` |
| P0 | 同花顺付费概率 | 22 | `source.ths_paid_limit_up_probability_v1` |
| P0 | 交易日历与窗口 | 6 | `source.trade_calendar_v1` |
| P0 | 日线与涨跌停 | 12 | `source.daily_bar_v1`、`source.limit_price_v1`、`source.limit_event_v1` |
| P0 | 竞价确认 | 10 | `source.auction_snapshot_v1` 或已落库竞价评分 |
| P0 | 开盘 5 分钟路径与基准价 | 8 | `source.minute_bar_v1`、`source.realtime_quote_v1`、`decision_hot.hot_buy_point_v1` |
| P0 | source 治理门禁 | 5 | `governance.source_lineage_v1`、source preflight 缺口事实 |
| P1 | 资金上下文 | 7 | `source.stock_moneyflow_daily_v1`、`source.moneyflow_stock_snapshot_v1` |
| P1 | 市场环境 | 5 | `source.market_regime_snapshot_v1`、`source.index_daily_bar_v1` |
| P1 | 题材板块 | 4 | `source.stock_board_membership_v1`、`source.board_daily_bar_v1` |
| P1 | 巡检上下文 | 2 | 已投影缺口码中的 `source_gap:inspection_context` |
| P2 | 新闻事件 | 4 | `source.event_news_v1` |
| P2 | 后验验证 | 3 | `decision_hot.hot_outcome_label_v1`、`decision_hot.hot_evolution_sample_v1` |

准备度字段只返回在 `/research/model-list/hot` 响应中：行级 `readiness_score_pct`、`missing_points`、`blocked_points`、`readiness_state`、`top_missing_dimension`、`readiness_gap_codes`、`readiness_dimensions`，以及列表级 `readiness_summary`。无热点行时，平均准备度和平均缺失分为 `null`，不能显示成 0% 或 100 分缺失事实。任一 P0 缺失时为 `blocked`，仅 P1/P2 缺失时为 `degraded`，全部齐全才为 `ready`。

该资产禁止触发 source-data-service fetch orchestration、禁止 provider/raw 读取、禁止 owner 调用、禁止写 `decision_hot.*` / `source.*` / `governance.*`，也不得把缺失维度补成 0、空字符串、示例 payload 或 GPT 推断值。

性能边界：准备度请求可以在单个 `ResearchPayloadRepository` 实例内缓存 `table_exists` 与 `table_columns` 元数据，避免同一批行重复查 information_schema。该缓存不是业务数据缓存，不缓存 source/decision 行，不改变 available_at、quality_status、lineage 或 preflight 缺口判断。

## 写入数据

| 表 | 作用 | 边界 |
|---|---|---|
| `governance.research_model_payload_assembly_audit_v1` | payload 组装审计、gap、source_refs、payload_hash | append-only；不是模型事实表 |
| `governance.research_model_execution_audit_v1` | research 执行 owner 调用、owner 响应、物化计数、gap/error 审计 | append-only；readiness 必须存在；不替代 owner 业务表 |
| `decision_hot.hot_cycle_v1`、`decision_hot.hot_decision_case_v1`、`decision_hot.hot_score_fact_v1`、`decision_hot.hot_release_gate_audit_v1`、`decision_hot.hot_evidence_snapshot_v1`、`decision_hot.hot_signal_fact_v1`、`decision_hot.hot_buy_point_v1` | 热点 owner 输出物化 | 只写 owner 返回结构化结果；`hot_signal_fact_v1` 同时保存 owner 标记的 official 与 research-only signal，flag 原样保留；`release_gate_reason` 等无 `_json/_jsonb` 后缀但物理类型为 `jsonb` 的字段必须按合法 JSONB 绑定，阻断原因数组不得被写成 PostgreSQL array 字面量或字符串兜底；`hot_buy_point_v1` 保存 owner buy-point 的 confirmed/blocked 诊断，不代表交易指令 |
| `decision_memory.memory_seed_v1`、`decision_memory.memory_entity_v1`、`decision_memory.memory_pre_signal_case_v1`、`decision_memory.memory_score_fact_v1`、`decision_memory.memory_release_gate_audit_v1`、`decision_memory.memory_signal_fact_v1` | 候选记忆 owner 输出物化 | `memory_age_days` 允许 `NULL`；缺交易日历年龄时写 `memory_status=blocked_data_gap` 与 `source_gap:memory_age_trading_calendar_missing` |
| `decision_ambush.valley_watch_pool_v1`、`decision_ambush.effective_turn_anchor_v1`、`decision_ambush.effective_turn_pool_v1`、`decision_ambush.ambush_pool_transition_audit_v1`、`decision_ambush.deep_confirmation_pool_v1`、`decision_ambush.ambush_score_fact_v1`、`decision_ambush.ambush_release_gate_audit_v1`、`decision_ambush.ambush_signal_fact_v1` | 潜伏抬头 owner 输出物化 | 只写 phase2/phase3 owner 结构化结果；official signal 仅当 owner release passed 且 signal_state=official_signal |
| `decision_t_relay.*`、`research_t_relay.*` | T 字板 owner 输出 | 由 `t-board-relay-service` owner repository 写入；research-service 只记录 execution audit |

## 调度频率

本服务无内置定时任务；由 scheduler 或人工按模型任务频率调用：

| 调度对象 | 频率 | 接口 |
|---|---|---|
| `hot.*` | 09:25-09:36、盘中观察、收盘、18:30 | 显式预检：`POST /research/model-payload/assemble`；正式 live dispatch：`POST /research/model-execution/run` |
| `memory.*` | 15:45、15:55、16:05、次日开盘、收盘成熟检查 | 显式预检：`POST /research/model-payload/assemble`；正式 live dispatch：`POST /research/model-execution/run` |
| `ambush.*` | 周期 source audit、18:10、15:20、15:35、15:55 | 显式预检：`POST /research/model-payload/assemble`；正式 live dispatch：`POST /research/model-execution/run` |
| `t_relay.*` | Day1/Day2/Day3 窗口、观察台快照和 outcome | 显式预检：`POST /research/model-payload/assemble`；正式 live dispatch：`POST /research/model-execution/run` |

## 模型四 Day2 数据资产修正

2026-06-23 修正后，`t_relay.day2.watch.rolling_5m` 和 `t_relay.day2.trigger.rolling_5m` 的组装资产口径如下：

| 字段/对象 | 来源 | 口径 |
|---|---|---|
| `up_limit_price` | `source.limit_price_v1.up_limit_price` | P0 只读涨停价，缺失硬阻断 |
| `last_price_at_watch` / `last_price_at_trigger` | 09:30-10:30 Asia/Shanghai 五分钟滚动窗口内首次接近涨停的 `source.minute_bar_v1.close_price`；未接近时取窗口内最新可见五分钟监测点，无分钟线时才回退 quote latest | 真实 source 价格，不补 0 |
| `day2_distance_to_up_limit_pct` / `distance_to_up_limit_pct` | `(up_limit_price - last_price_at_watch) / up_limit_price` | 仅在真实价格和涨停价均存在时计算；`<=0.01` 视为滚动监测接近条件 |
| `day1_candidate` / `day1_candidate_status` | `decision_t_relay.t_board_day1_candidate_v1` | owner 判断 `day1_not_qualified` 的只读上游事实 |
| `watch_snapshot` | `decision_t_relay.t_board_day2_watch_snapshot_v1` | Day2 trigger 只读上游观察快照 |
| `aggressive_buy_sweep_amount` / `aggressive_sell_hit_bid_amount` | `source.trade_tick_v1.amount` 按 provider-native `side_code` 聚合 | 09:30 到当前 `monitor_check_time`；仅作为逐笔侧向证据 |
| `order_consumption_side` / `order_consumption_amount` | 上述逐笔聚合结果 | `ASK` 表示买侧扫单证据占优，`BID` 表示卖侧打单证据占优，未知保持 `UNKNOWN` |
| `warning_codes` | owner 已定义的非硬阻断缺口 | 包括 `source_gap:seal_order_snapshot_missing`、`source_gap:dynamic_feature_bundle_missing`、`source_gap:near_limit_order_absorption_missing` |

当前代码合同：滚动监测组装只读 `source.limit_price_v1`、`source.minute_bar_v1`、`source.realtime_quote_v1`、`source.trade_tick_v1`、`decision_t_relay.t_board_day1_candidate_v1` 和 `decision_t_relay.t_board_day2_watch_snapshot_v1`；输出 `monitor_interval_minutes`、`monitor_check_time`、`first_qualified_monitor_time`、`day2_distance_to_up_limit_pct`、`rolling_near_limit_triggered` 和 `monitor_bar_count`。`t_relay.day2.trigger.rolling_5m` 是 non-official 研究触发，不调用或要求 `source-data-service /source/release/preflight`；source 完整性由真实 source/upstream 读取、quality/available_at 和 gap 码约束。该合同不新增 source/schema/provider 能力，不把逐笔、封单、动态特征或吸收分缺口补成事实。模型四非 Day1 阶段 owner request 只传单对象 `payload`，不携带整批 `rows[]`；上游审计大字段只留作审计资产，不进入二次 owner 请求 payload。

## 模型四 Post-entry / Day3 数据资产修正

2026-06-24 修正后，`t_relay.day2.post_entry.monitor`、`t_relay.day3.exit.open` 和 `t_relay.day3.exit.tail` 的组装资产口径如下：

| 字段/对象 | 来源 | 口径 |
|---|---|---|
| `entry_trigger`、`trigger_time`、`monitor_check_time` | `decision_t_relay.t_board_day2_entry_trigger_v1` | 触发后监控锚点；缺失时阻断，不用当前时间推断 |
| `up_limit_price` | 当前 `source.limit_price_v1.up_limit_price`，或已物化 entry/post-entry 上游事实 | 只允许真实 source 或已落库上游事实继承；缺失保持 gap/NULL |
| `post_entry_board_opened`、`first_board_open_time_after_entry`、`board_open_count_after_entry` | 触发时间之后的 `source.minute_bar_v1` | 任一真实分钟线价格低于涨停价即视为触发后破板；缺分钟线或缺涨停价不得推断 |
| `lowest_price_after_entry`、`max_drawdown_after_entry`、`close_price`、`close_on_limit_flag` | 触发后到当前可见时间的 `source.minute_bar_v1` | 用真实分钟线计算；没有价格时保持 `NULL` |
| `day3_open_*` | Day3 09:25-09:35 可见 `source.minute_bar_v1` | 用于 Day3 开盘去留观察；research-service 不生成交易指令 |
| `day3_tail_*` | Day3 14:40-14:55 可见 `source.minute_bar_v1` | 用于 Day3 尾盘去留观察；research-service 不生成卖出结论 |
| `warning_codes` | owner 已定义的非硬阻断缺口 | `source_gap:seal_order_snapshot_missing`、`source_gap:dynamic_feature_bundle_missing`、`source_gap:near_limit_order_absorption_missing` 对这些阶段保持 warning-only |

当前代码合同：触发后和 Day3 组装只读 `source.minute_bar_v1`、`source.limit_price_v1` 与 `decision_t_relay.*` 上游事实；只产出 owner payload 与 governance audit，不写 `decision_t_relay.*` 业务事实。模型四业务事实仍由 `t-board-relay-service` owner repository 写入；缺真实价格、缺涨停价或缺上游触发事实时，必须保留 `source_gap:*`、`NULL` 或 `blocked_data_gap`。

## 模型四 Observation Snapshot 数据资产

| 字段/对象 | 来源 | 口径 |
|---|---|---|
| `trade_date` | scheduler materializer / catch-up request | 本次快照所属交易日；不由 research-service 推断 Day1/Day2/Day3 结论 |
| `limit` | research-service 固定合同 | 默认 500，只控制 owner 读取观察台投影窗口 |
| `monitor_interval_minutes` | research-service 固定合同 | 固定 5，匹配模型四观察台五分钟留痕频率 |
| `scheduler_context` | scheduler `_scheduler_materialized_instance` | 保存原始计划槽位、`catch_up_run_id`、`captured_late`、`original_scheduled_at`、`catch_up_checked_at` 等调度审计字段 |

当前代码合同：`t_relay.observation.monitor.snapshot_5m` 不读取 `source.*`、`decision_t_relay.*` 或 raw/provider；它只调用 owner 快照入口，由 `t-board-relay-service` 从自身 repository 当前投影生成 append-only 快照。迟到补偿只能说明“当前捕获了某个错过槽位的观察台投影”，不得把补偿快照解释为历史实时盘口事实。

## 性能索引

| 索引 | 用途 |
|---|---|
| `idx_research_payload_assembly_task_day_v1` | 按任务和交易日追溯组装结果 |
| `idx_research_payload_assembly_symbol_day_v1` | 按标的和交易日追溯组装结果 |
| `idx_research_payload_assembly_status_v1` | 巡检 blocked/assembled 状态 |
| `idx_research_payload_assembly_hash_v1` | payload 去重和审计比对 |
| `idx_research_model_execution_task_day_v1` | 按任务、交易日和时间追溯执行结果 |
| `idx_research_model_execution_owner_status_v1` | 按 owner 与执行状态排查阻断/失败 |
| `idx_research_model_execution_symbol_day_v1` | 按标的和交易日追溯 owner 调用与物化 |
| `idx_research_model_execution_payload_hash_v1` | payload 与执行审计比对 |
| `decision_hot.hot_decision_case_v1.hot_case_id` | `hot.release_gate.preopen` 关联读取 `hot_score_fact_v1` / `hot_evidence_snapshot_v1` |

## 发布冻结记录

2026-06-18 用户批准“发布 research+scheduler”后，`research-service` 随 `scheduler-service` 做定向 `--no-deps` 发布；未重启 source/data-inspector/Postgres/模型 owner。发布后运行态数据资产合同如下：

| 服务 -> 模块 -> 功能 | 冻结对象 | 运行态证据 | 数据边界 |
|---|---|---|---|
| `research-service -> model-payload-assembler -> release gate upstream mapping` | official release gate 上游读取表、缺口阻断、append-only audit | `hot.release_gate.preopen` 上游为 `decision_hot.hot_score_fact_v1` + `decision_hot.hot_evidence_snapshot_v1`；`memory.release_gate.close` 上游为 `decision_memory.memory_pre_signal_case_v1` + `decision_memory.memory_score_fact_v1`；`ambush.phase3.release_gate.close` 上游为 `decision_ambush.effective_turn_pool_v1`；三者均因真实上游表为空返回 `blocked_data_gap` | 只读 `source.*` 与允许的 `decision_*`；不读 raw/provider；不把缺口补成 0、空字符串、sample 或推断 |
| `research-service -> model-payload-assembler -> hot release upstream case-link reader` | `hot.release_gate.preopen` 按 `hot_decision_case_v1.hot_case_id` 读取 `hot_score_fact_v1` / `hot_evidence_snapshot_v1` | 2026-06-19 定向发布后，no-persist assemble 对 `000759.SZ / 2026-06-12` 读到 score `row_count=1`、evidence `row_count=8`，仅保留 `source_gap:source_preflight_not_passed` | 只读 `decision_hot.hot_decision_case_v1`、`decision_hot.hot_score_fact_v1`、`decision_hot.hot_evidence_snapshot_v1`；不写 release audit，不生成 `hot_signal_fact_v1` |
| `research-service -> model-execution -> owner materialization bridge` | `/research/model-execution/run`、`ResearchDecisionMaterializer`、`governance.research_model_execution_audit_v1`、owner 输出物化表 | 代码合同：blocked assembly 不触达 owner；owner 失败/物化失败均写 execution audit；materialized_counts 记录写入表计数；scheduler live time wheel 只调用 research execution；热点 score/release/buy-point 可按真实候选池 fanout | 只物化 owner 返回的真实结构化结果；不计算分数、不绕过 source preflight、不直接发布、改写或提升 official signal；热点 research-only signal 与 blocked buy-point 保留诊断语义；T 字板业务事实由 owner repository 写入 |
| `research-service -> model-payload-assembler -> t_relay Day2 warning/assembly contract` | `t_relay.day2.watch.rolling_5m` / `t_relay.day2.trigger.rolling_5m` 的 Day2 source/upstream 资产读取、warning 语义和 no-persist 验收口径 | 2026-06-23 用户批准解锁为开盘后五分钟滚动监测；首次 `day2_distance_to_up_limit_pct <= 0.01` 视为接近条件，提示可买入观察；未接近时继续滚动观察 | 只读 `source.limit_price_v1`、`source.minute_bar_v1`、`source.realtime_quote_v1`、`source.trade_tick_v1`、`decision_t_relay.t_board_day1_candidate_v1`、`decision_t_relay.t_board_day2_watch_snapshot_v1`；`trade_tick` 仅为逐笔侧向证据；不读 raw/provider；不把封单快照、动态特征或吸收分缺口补成事实 |
| `research-service -> model-payload-assembler -> t_relay observation snapshot pass-through` | `t_relay.observation.monitor.snapshot_5m`、owner `/t-board-relay/observation-monitor/snapshot`、scheduler catch-up context | 2026-06-24 新增第 25 个 research task；no-persist 组装不读取 source/upstream，owner request body 只携带单对象 `payload` | 不读 raw/provider/source/upstream；不补历史盘口事实；不生成前端事实；owner repository 负责 `decision_t_relay.t_board_observation_monitor_snapshot_v1` 写入 |

回滚标签：`infra-research-service:rollback-20260618-research-scheduler-release`。只读验收允许继续调用 `/readyz`、`/research/model-payload/requirements`、`/scheduler/model-payload/assemble-preflight`；`/research/model-execution/run` 会写 execution audit 且可能触达 owner，只能在用户明确批准 live 验收、发布或调度执行时调用。修改上述合同必须重新解锁。

Hot release case-link 发布回滚标签：`infra-research-service:rollback-20260619-hot-release-upstream`，对应旧镜像 `sha256:f7e781c06705f2e60d50997601c65bcbc82091f2a7ae717dc9186be93300856e`；当前发布镜像 `infra-research-service@sha256:df3bbdb65ebf244626a37205541a9adc48496243c36c640d3b3b152f2e78b707`，容器 `ai-stock-research-service b263f422bac1`。该发布只替换 research-service，未重启 source-data、scheduler、data-inspector、Postgres 或模型 owner。

2026-06-19 20:40 Asia/Shanghai，用户授权“继续，你决定是否可以拍板”后，`research-service -> model-payload-assembler -> hot release upstream case-link reader` 冻结。冻结范围为 `hot.release_gate.preopen` 只读 `decision_hot.hot_decision_case_v1`、`decision_hot.hot_score_fact_v1`、`decision_hot.hot_evidence_snapshot_v1` 的 case-link 读取口径，以及 `source_preflight_not_passed` 阻断语义；允许只读验收 `/readyz`、direct no-persist assemble、scheduler no-persist assemble-preflight 和数据库只读计数；禁止未经解锁改回通用 symbol/date 直查、绕过 source preflight、写 `hot_release_gate_audit_v1`、生成 `hot_signal_fact_v1`、读取 raw/provider 或用 0/sample/mock/GPT 补事实。解锁条件为 hot decision 表结构、release gate 上游合同、source preflight 口径变化或用户明确批准；回滚使用 `infra-research-service:rollback-20260619-hot-release-upstream` 并仅 `--no-deps` 替换 research-service。

Day2 合同单独回滚标签：`infra-research-service:rollback-20260618-trelay-day2-assembler`。修改 `t_relay Day2 warning/assembly contract` 必须重新解锁；只读验收优先使用 `persist_audit=false` 的 direct assemble 和 scheduler preflight，不调用 `/research/model-execution/run`。

### research-service -> t_relay observation snapshot pass-through asset freeze

- 冻结时间：2026-06-24 Asia/Shanghai。
- 数据资产范围：`t_relay.observation.monitor.snapshot_5m` 的 research payload 只承载 scheduler 快照参数和 catch-up 审计上下文，转交 owner `/t-board-relay/observation-monitor/snapshot`；owner 负责写 `decision_t_relay.t_board_observation_monitor_snapshot_v1`。
- 当前验收事实：requirements 当前为 25 个任务；snapshot 任务不声明 source/upstream 资产；2026-06-24 非 dry-run catch-up materialized 后，owner 快照表 append-only 增长 4 行，覆盖 002297.SZ、600769.SH、301580.SZ、600172.SH，观察台更新时间推进到 `2026-06-24T09:50:48.617447+00:00`。
- 数据边界：research-service 不读取 raw/provider/source/upstream，不补盘口事实，不生成前端事实、模型分、交易、买点或 official signal；迟到补偿保留原计划槽位和实际捕获时间，不能伪装成历史实时数据。
- 只读验收：requirements、no-persist assemble、scheduler dry-run catch-up、owner snapshot/observation-board、frontend compact。
- 解锁条件：snapshot payload 字段、owner endpoint、scheduler catch-up、research execution 合同或用户明确批准解锁。

## 禁止事项

- 不直接调用 BaoStock、AKShare、Tushare、EastMoney、CNINFO、Baidu 等 provider。
- 不读取 `raw_*`、`raw.*` 或 provider 原始响应。
- 不写 `source.*`，不自行计算模型分数、release gate、official signal、买点、outcome、标签、交易或学习权重；只允许物化 owner service 的真实返回。
- 不用 sample payload、0、空字符串、mock 或 GPT 推断补缺口。

## 2026-06-18 Execution Bridge 数据资产冻结记录

用户要求“继续闭环”后，已将 `research_model_execution_v1` 运行态闭合到 Postgres 和 Docker：

| 资产/对象 | 运行态证据 | 数据边界 |
|---|---|---|
| `governance.research_model_execution_audit_v1` | `0027` 已执行；表、4 个索引和 execution contract/status check 约束均存在 | append-only；记录 owner request/response、执行状态、gap、物化计数，不替代模型 owner 业务表 |
| `decision_memory.memory_entity_v1.memory_age_days` | information_schema 显示 `is_nullable=YES` | 缺交易日历年龄时保留 `NULL`，状态和缺口码由 materializer 写入 |
| `research-service /readyz` | `execution_audit_ready=true` | 缺 execution audit 表不得判 ready |
| `scheduler_model_time_wheel_v1` | scheduler readyz 中 `dispatcher_version=scheduler_research_model_execution_dispatch_v1` | 正式 live dispatch 只调用 `/research/model-execution/run`，不由 scheduler 直连 owner |
| `exec-closure-20260618150910` | `execution_status=blocked_data_gap`、`owner_called=false`、`audit_persisted=true` | 缺 `decision_hot` 上游事实和 source preflight 未通过时停止在 owner 前，只写审计 |

发布对象：

```text
research image: infra-research-service@sha256:62d9d5798d78dea858eaff1f58ff1a0e02eca93c80220a0e70260bd220ab2693
research container: ai-stock-research-service a2a5aa571c29
rollback: infra-research-service:rollback-20260618-execution-bridge-closure
```

未中断对象：

```text
source-data-service 125b58ac7f9e
source-data-worker 0df61d50252b
data-inspector-service 0995dca891f7
postgres af846a793868
```

冻结后，`/research/model-execution/run` 只能在用户批准 live 验收、发布或调度执行时调用；普通只读验收继续使用 `/readyz`、`/research/model-payload/requirements`、`/scheduler/model-payload/assemble-preflight` 和数据库只读审计查询。

## 2026-06-24 T Relay Post-Entry/Day3 数据资产冻结

| 服务 -> 模块 -> 功能 | 数据资产范围 | 当前验收事实 | 数据边界 |
|---|---|---|---|
| `research-service -> model-payload-assembler -> t_relay post-entry and Day3 observation payload` | 只读 `source.minute_bar_v1`、`source.limit_price_v1`、`decision_t_relay.t_board_day1_candidate_v1`、`decision_t_relay.t_board_day2_entry_trigger_v1`、`decision_t_relay.t_board_post_entry_monitor_v1`、`decision_t_relay.t_board_day3_exit_decision_v1`；组装 `t_relay.day2.post_entry.monitor`、`t_relay.day3.exit.open`、`t_relay.day3.exit.tail` owner payload | 2026-06-24 no-persist 验收显示 600172.SH 触发后出现开板，`post_entry_board_opened=true`、首个开板时间 `09:43:00`、开板次数 `14`、涨停价 `16.95`；live execution 已推动 owner observation-board 更新为停止观察；Day3 自然窗口仍待后续交易窗口只读验收 | 不读取 raw/provider；不把缺失 post-entry/Day3 事实补成 0、空字符串、mock 或推断；不生成交易、卖出、official signal 或前端事实；Day3 仅锁定开盘 `09:25-09:35` 与尾盘 `14:40-14:55` 的组装边界 |

## 2026-06-27 Hot Model Data Readiness 数据资产冻结

| 服务 -> 模块 -> 功能 | 数据资产范围 | 当前验收事实 | 数据边界 |
|---|---|---|---|
| `research-service -> hot model list -> data readiness projection` | `/research/model-list/hot` 返回 `hot_model_data_readiness_v1`，只读聚合 `decision_hot.*`、`source.*`、lineage/preflight/巡检上下文形成 13 个固定准备度维度；P0 75 分、P1 18 分、P2 7 分，总权重 100；行级字段为 `readiness_score_pct`、`missing_points`、`blocked_points`、`readiness_state`、`top_missing_dimension`、`readiness_gap_codes`、`readiness_dimensions`，列表级字段为 `readiness_summary` | 用户于 2026-06-27 明确“拍板”；验收时 `GET /research/model-list/hot?limit=20` 返回 20 条真实行、13 个维度、平均准备度 `51.2%`；首行 `600367.SH` 准备度 `59`、状态 `blocked`、缺 `41` 分、P0 阻断 `18` 分、最大缺口 `auction_confirmation`；frontend compact 与 Playwright 页面均可见准备度结果 | 该资产只读、非落库物化、非模型评分、非 release gate；不得触发 source fetch/provider/raw/owner；不得写 `decision_hot.*`、`source.*`、`governance.*`；无行时平均准备度和平均缺失分保持 `null`；缺失事实必须保留 `NULL`、缺口码、缺失分和阻断状态，不得补 0、空字符串、mock、示例 payload 或 GPT 推断 |

冻结后，修改准备度维度、权重、P0/P1/P2 语义、缺口码、表结构 metadata 缓存边界、性能物化方式或前端读取合同，必须先获得用户明确解锁。回滚优先使用 `infra-research-service:rollback-20260627-hot-readiness` 或后续等价回滚镜像，仅按需替换 research-service，不触碰 `source-data-service`、`source-data-worker`、scheduler、data-inspector、Postgres 或模型 owner。
