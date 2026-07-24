# t-board-relay-service README

本文件是 `t-board-relay-service` 模块根目录唯一当前 MD。全局硬约束以项目根目录 `AGENTS.md` 为准；集合层说明见 `services/models_services/README.md`。下载目录中的模型四设计文档只作为本轮临时输入，不能作为长期事实源。

本服务数据资产账本见 `services/models_services/t-board-relay-service/DATA_ASSETS.md`，记录模型四 P0 source 依赖、append-only repository 表和 non-official 调度边界。

## 定位

模型四 `t_board_relay` 是 T 字板主导资金博弈模型，研究 Day1 T 字板之后的三日接力行为：

```text
Day1 开盘涨停、盘中开板、收盘回封。
Day2 09:30 起每 5 分钟滚动观察，首次接近涨停只进入盘口确认；必须出现 `ASK` 方向主动买盘扫卖盘且成交金额有效，才触发接力机会提示。
Day2 理论买入后到收盘只要开板，直接判废。
Day3 开盘涨停则留下；14:40-14:55 尾盘仍未涨停则生成退出研究事件。
```

本服务是独立 owner service，不并入 `hot_candidates`、`candidate_memory` 或 `ambush_watchlist`。它不下单、不替代买点服务、不直接采集 provider、不直接读取 `raw_*`，只输出可研究、可回放、可审计的候选、触发、封板维护、Day3 去留、outcome 和博弈假设合同。

## 版本

- `model_code`: `t_board_relay`
- 模型版本：`t_board_relay_v1`
- 特征版本：`t_board_relay_feature_v1`
- 规则版本：`t_board_relay_rule_v1`
- 建议生产决策域：`decision_t_relay`
- 建议研究域：`research_t_relay`

## 代码入口

- FastAPI：`src/t_board_relay_model_service/main.py`
- API：`src/t_board_relay_model_service/api.py`
- 请求/响应 schema：`src/t_board_relay_model_service/schemas.py`
- 版本化规则配置：`src/t_board_relay_model_service/config.py`
- 状态机与评分合同：`src/t_board_relay_model_service/logic.py`
- Postgres repository：`src/t_board_relay_model_service/repository.py`

## API

健康：

```text
GET /health
GET /healthz
GET /readyz
GET /t-board-relay/healthz
GET /t-board-relay/readyz
```

生产合同入口：

```text
POST /t-board-relay/day1/scan
GET  /t-board-relay/day1/candidates
GET  /t-board-relay/day1/candidates/{day1_candidate_id}
POST /t-board-relay/day2/watch
POST /t-board-relay/day2/trigger-check
GET  /t-board-relay/day2/triggers
GET  /t-board-relay/day2/triggers/{entry_trigger_id}
POST /t-board-relay/post-entry/monitor
GET  /t-board-relay/post-entry/status
POST /t-board-relay/day3/exit-check
GET  /t-board-relay/day3/decisions
GET  /t-board-relay/outcomes
POST /t-board-relay/outcomes/build
GET  /t-board-relay/game-hypotheses
GET  /t-board-relay/observation-board
POST /t-board-relay/observation-monitor/snapshot
GET  /t-board-relay/observation-monitor/snapshots
```

当前观察台时间硬口径（2026-06-30 起执行，并覆盖旧的 snapshot 推动更新时间描述）：
- `latest_data_fetch_at` 与 `last_data_captured_at` 指向最新真实抓取 / 阶段事实时间，优先来自 Day2 watch、trigger、post-entry、Day3、outcome 等真实阶段记录的 `as_of_time`、`captured_at`、`available_at` 或 `as_of_time_utc`；无阶段业务时间时才退回阶段记录自身 `updated_at/created_at`。
- `latest_snapshot_time`、`updated_at`、`display_update_at` 在 `observation-board` 中保持真实阶段事实时间，不再被 5 分钟 `projection_snapshot_5m` 覆盖。
- `latest_projection_snapshot_at` 只表示最近一次 5 分钟观察投影快照生成时间，用于 append-only 审计、恢复和排查调度是否继续留痕，不得解释成真实抓取时间，不得反写 Day2/Day3/outcome 阶段事实。
- `last_model_output_at` 与 `model_evaluated_at` 表示最近一次 30 分钟 `model_result_30m` 模型结果产出时间；它可以更新模型判断、模型分和风险结论的可读投影，但不得覆盖真实抓取/阶段事实时间。
- 普通用户前端“更新”列必须同时展示最后一次模型产出时间和最新真实抓取/阶段事实时间；数据服务中断导致真实抓取缺失时，模型四可以不产出新模型结果，但一旦真实抓取恢复并形成阶段事实，`latest_data_fetch_at` 必须随正式链路尽快推进。

当前 owner service 已接入可选 Postgres repository。生产容器存在 `AI_STOCK_DATABASE_URL` 且 `PERSIST_DECISIONS=true` 时，POST 接口在完成规则计算后把阶段结果 append-only 写入 `decision_t_relay.*`；响应 `structured_output.repository_write` 返回真实写入状态、插入条数和主键。无数据库、schema 缺失或显式关闭持久化时，接口仍返回模型计算结果，但 `repository_write.persisted=false` 并保留明确 warning，禁止伪装为已落库。

仓库状态：

```text
GET /t-board-relay/repository/status
```

GET 列表接口优先查询真实 `decision_t_relay` 表；未连接 repository 时才返回 `repository_not_attached_*` warning。

普通用户观察台入口：

```text
GET /t-board-relay/observation-board
```

观察台快照入口：
```text
POST /t-board-relay/observation-monitor/snapshot
GET /t-board-relay/observation-monitor/snapshots
```

`POST /t-board-relay/observation-monitor/snapshot` 只读当前 `observation-board` 投影，把每个 Day1 合格观察对象当前的模型分、当前判断、关键依据、风险结论、真实数据时间和完整投影 append-only 写入 `decision_t_relay.t_board_observation_monitor_snapshot_v1`。`monitor_interval_minutes<30` 时快照语义为 `projection_snapshot_5m`，表示 5 分钟观察投影留痕；`observation-board` 读取最新 5 分钟快照后只输出 `latest_projection_snapshot_at` 和快照 id 作为审计/恢复 metadata，不再用它推动 `display_update_at/latest_snapshot_time`，不得把投影生成时间解释成真实抓取时间。`monitor_interval_minutes>=30` 时快照语义为 `model_result_30m`，表示 30 分钟模型结果版本，并写入 `last_model_output_at/model_evaluated_at`。`GET /t-board-relay/observation-monitor/snapshots` 只读返回这些快照。该入口不调用 provider、不补事实、不生成 official signal，也不替代 Day2 watch、post-entry monitor 或 Day3 阶段事实表；5 分钟快照不得覆盖 `latest_data_fetch_at/last_data_captured_at/display_update_at/latest_snapshot_time`，30 分钟模型快照时间不得冒充真实抓取时间。

当前 Day2 滚动投影合同：
- `observation-board` 在读取 Day2 触发、封板维护、Day3、outcome 和博弈假设前，必须同时读取每个 Day1 合格对象最新的 `decision_t_relay.t_board_day2_watch_snapshot_v1`。
- Day2 尚未形成有效触发时，若已有五分钟 watch 快照，普通用户投影仍要展示 `day2_trade_date`、由 `as_of_time` 转成的 `day2_trigger_time`、当前判断、关键依据、风险结论和来自 watch 的 `latest_snapshot_time`。
- Day2 `09:30-10:30` 窗口已过且没有有效 Day2 watch / trigger 事实时，`observation_status=data_wait`、`score_state=data_wait`、`model_score=NULL`，关键依据必须说明 Day2 五分钟监测事实缺失；不得继续显示“观察中”或用 Day1 旧事实冒充仍在观察。
- Day2 窗口是否已过必须先按 Asia/Shanghai 从 Day1 推导预期 Day2 工作日，周末顺延；当前日期已经晚于该预期 Day2 时，视为窗口已过，不再受当前钟点是否到 10:30 影响。缺交易日历时该工作日口径只是保守近似，不能用来补事实。
- `ASK` / `BID` 只允许保留在内部事实枚举中；普通用户文案必须翻译为“买盘主动扫掉卖盘”“卖盘主动砸向买盘”或“盘口方向待确认”。
- Day2 有效触发后，`decision_t_relay.t_board_post_entry_monitor_v1` 继续 append-only 留存封板维护快照；触发后开板必须及时投影为停止观察，同时保留原始监测记录。
- 观察台输出的时间分三层：`latest_data_fetch_at`、`last_data_captured_at`、`updated_at`、`display_update_at` 和 `latest_snapshot_time` 指向最近真实阶段事实时间，单条阶段记录优先使用 `as_of_time`、`captured_at`、`available_at` 或 `as_of_time_utc`，没有业务时间时才退回 `updated_at` / `created_at`；`latest_projection_snapshot_at` 只指向最近一次 5 分钟观察投影快照时间，用于审计和恢复排查，不驱动 `display_update_at/latest_snapshot_time`；30 分钟模型快照时间进入 `last_model_output_at/model_evaluated_at`，作为最后一次模型产出时间，不得冒充真实抓取时间。
- 30 分钟 `model_result_30m` 可以刷新最近模型产出时间；但当 owner 基于当前阶段事实已经判为 `data_wait`、`stopped` 或 `completed` 时，历史快照不得把状态、分数、当前判断、关键依据或风险结论复活为 `continue_watch` / `opportunity`。
- 观察台输出 `last_monitor_at`、`monitor_interval_minutes` 和 `monitoring_summary`，由现有 Day2 watch、Day2 trigger、post-entry monitor、Day3 和 outcome 阶段记录只读派生；若底层阶段表没有真实计数字段，不伪造监测次数。
- 观察台同步输出 `model_score`、`model_score_label`、`score_state` 和 `model_score_version=t_board_relay_observation_score_v1`。分数由模型四 owner 根据 Day1 封单/分歧吸收、Day2 五分钟滚动接近涨停、ASK 扫卖盘确认、BID 主动砸盘风险、触发后封板维护、Day3 去留和 outcome 阶段事实综合计算；关键事实缺失时 `model_score=NULL`、`score_state=data_wait`，不得用 0 或前端推断补齐。接口先构建最多 500 条 Day1 合格对象的评分排序窗口，再按 `model_score` 降序、无分后置、更新时间倒序返回 `limit` 条。

`observation-board` 是模型四给前端消费的只读投影，不是新的事实写入表。它从 `decision_t_relay.*` append-only 阶段表读取当前最新事实后生成 `t_board_relay_observation_board_v1`：

- 只纳入 Day1 已通过的观察对象：`candidate_status=qualified`、`is_t_board=true`、`float_market_cap_pass=true`。Day1 未通过、拒绝或数据阻断的股票不进入普通用户观察台主列表；它们仍保留在 Day1 repository 审计表中。
- 观察台查询阶段必须优先读取 Day1 合格对象进入评分排序窗口，再按 `model_score` 降序和 `limit` 截断展示；不得先按最新 Day1 行取前 N 条再过滤，否则 rejected 行可能挤掉真实合格观察对象，也不得让低分新记录在排序前挤掉高分观察对象。当前实现使用 `list_day1_observation_candidates` 只读查询 `decision_t_relay.t_board_day1_candidate_v1` 最新合格对象，并在 owner 内部构建最多 500 条评分窗口。
- Day1、Day2、Day3 均按正常开市交易日顺序解释：Day2 必须晚于 Day1，Day3 必须晚于 Day2。若历史阶段记录出现 Day2 与 Day1 同日或 Day3 不晚于 Day2，观察台不把该阶段作为有效 Day2 / Day3 展示，只返回中文 `data_notice` 等待交易日校验。
- 只用 `day1_candidate_id` 和 `entry_trigger_id` 做阶段关联，不按股票代码兜底合并，避免同股票不同交易日或 Day1 未通过记录被误拼成观察对象。
- 输出面向普通用户的字段：`stock`、`day1_trade_date`、`day2_trade_date`、`day3_trade_date`、`observation_status`、`current_stage`、`current_conclusion`、`next_observation`、`key_reason`、`model_score`、`model_score_label`、`score_state`、`model_score_version`、`relay_strength_label`、`risk_tip`、`data_notice`、`data_gap_count`、`data_gap_labels`、`latest_snapshot_time`、`updated_at`、`display_update_at`、`latest_data_fetch_at`、`last_data_captured_at`、`latest_projection_snapshot_at`、`latest_projection_snapshot_id`、`last_model_output_at`、`model_evaluated_at`、`model_result_interval_minutes`、`last_monitor_at`、`monitor_interval_minutes`、`monitoring_summary`。其中 `current_stage`、`current_conclusion`、`next_observation`、`key_reason` 使用 `Day2` / `Day3` 描述阶段和原因，不用“次日”或“第三日”；`model_score` 是模型四 owner 给出的综合分，前端只能展示和排序；`ASK` / `BID` 只作为内部事实枚举保留，普通用户文案必须翻译为“买盘主动扫掉卖盘”或“卖盘主动砸向买盘”；`risk_tip` 是基于盘口方向、日内强度、封板维护、Day3 去留或缺口事实生成的风险结论，不得输出“仅作观察、不自动下单”这类免责提示；`monitoring_summary` 只描述已有阶段记录对应的最近监测进度，不用推断补齐不存在的监测次数；`data_gap_labels` 为中文业务提示，不暴露 `source_gap:*`。前端普通用户列表只展示去重后的核心列 `股票 / 模型分 / Day1 / Day2 / 监测时间 / 当前判断 / 接力强度 / 关键依据 / 风险结论 / 更新`，其中 `更新` 必须并列展示 `last_model_output_at/model_evaluated_at` 对应的最后一次模型产出时间与 `latest_data_fetch_at/last_data_captured_at` 对应的最新真实抓取/阶段事实时间；`latest_projection_snapshot_at` 只保留给审计和恢复排查，不展示成抓取时间；不展示 `current_stage`、`day3_trade_date`、`next_observation`、`data_notice` 或 `data_gap_labels`，这些字段仅保留给只读合同、审计和问题追溯。
- 该接口只读，不写 repository，不触发 scheduler，不调用 provider，不生成 official signal，不补齐缺失事实。
- 查询 Day2/Day3/outcome/game hypothesis 阶段时使用轻量业务列投影，不读取或返回 `request_payload`、`result_payload`、`game_hypothesis_payload`、`evidence_json`、`related_payload` 等审计大字段；这些 JSONB 字段只保留给 repository 审计和问题追溯。

统一响应：

```json
{
  "model_name": "t_board_relay",
  "model_version": "t_board_relay_v1",
  "structured_output": {},
  "jarvis_payload": {},
  "contract_gaps": []
}
```

Jarvis payload 只读，不能改分数、状态、标签或模拟动作事件，且明确 `can_place_order=false`。

## 输入数据样式

统一请求：

```json
{
  "payload": {},
  "row": {},
  "rows": [],
  "trade_date": "2026-06-15",
  "as_of_time_utc": "2026-06-15T07:05:00Z",
  "run_id": "string|null",
  "mode": "production"
}
```

`day1/scan` 可传 `rows[]`；其他阶段传单对象 `payload`，research-service owner client 不向 Day2/Day3/outcome 请求体发送 `row` 或 `rows`。正式输入只能来自 `source.*` 标准事实层、`decision.dynamic_feature_*` 或后续 `dynamic-feature-service` 的特征事实，不得直接使用 provider 原始响应。

Day1 入口不是全 A 高频/报价盲扫。source-data-service 先通过 THS 公开涨停池构建 `source.limit_event_v1`，scheduler 从该 source 标准层只读筛出 T 字板阶段候选，再只对候选补齐 `source.trade_status_v1`、`source.daily_bar_v1`、`source.limit_price_v1` 和 `source.realtime_quote_v1.float_market_cap`。`day1/scan` 只评估这些候选；Day1 未通过、数据阻断或非 T 字板对象不得进入普通用户观察台主列表。

## Source 数据入口

P0 缺失时不得 official，只能 `data_blocked` 或 `research_only`：

- `source.daily_bar_v1`
- `source.limit_price_v1`
- `source.limit_event_v1`
- `source.trade_status_v1`
- `source.realtime_quote_v1.float_market_cap`
- `source.minute_bar_v1`
- `source.trade_tick_v1`

P1 缺失可运行但必须降置信并写 gap：

- `source.market_moneyflow_intraday_v1`
- `source.board_intraday_snapshot_v1`
- `source.intraday_moneyflow_snapshot_v1`
- `source.seal_order_snapshot_v1`
- `source.order_cancel_snapshot_v1`

P2 辅助：

- `source.news_event_v1`
- `source.announcement_event_v1`
- `source.sentiment_event_v1`

## Dynamic Feature 依赖

模型四强依赖动态特征 bundle：

```text
t_board_relay_intraday_bundle_v1
```

当前仓库已有 `decision.dynamic_feature_run`、`decision.dynamic_feature_snapshot` 和 `decision.dynamic_feature_latest` 基线表，但尚无独立 `dynamic-feature-service` 源码目录。本服务第一版只接收 `dynamic_feature_run_id` 或 `dynamic_feature_bundle` 作为输入事实；缺失时保留 `source_gap:dynamic_feature_bundle_missing`，不得用 0、空字符串或推断补齐。

核心特征：

- `day2_distance_to_up_limit_pct`
- `monitor_interval_minutes`
- `first_qualified_monitor_time`
- `near_limit_order_absorption_score`
- `order_consumption_side`
- `aggressive_buy_sweep_amount`
- `aggressive_sell_hit_bid_amount`
- `bid_replenish_speed_after_consumed`
- `ask_absorption_speed_near_limit`
- `market_return_acceleration_rolling`
- `limit_up_ratio_rolling`
- `market_net_moneyflow_rolling`
- `post_entry_board_opened`
- `day3_open_limit_up_flag`
- `day3_tail_limit_up_flag`

## 状态流转

```text
DAY1_SCAN
-> DAY1_T_BOARD_DETECTED
-> DAY1_T_BOARD_QUALIFIED
-> DAY2_PRE_WATCH
-> DAY2_ROLLING_5M_NEAR_LIMIT_WATCH
-> DAY2_ROLLING_NEAR_LIMIT_TRIGGER
-> DAY2_THEORETICAL_ENTRY
-> DAY2_POST_ENTRY_SEAL_MONITOR
-> DAY2_SEALED_TO_CLOSE / DAY2_BOARD_OPEN_FAILED
-> DAY3_OPEN_LIMIT_HOLD / DAY3_TAIL_NO_LIMIT_EXIT
-> FINAL_OUTCOME
```

Day1、Day2、Day3 的时间口径统一为正常开市交易日序列，而非自然日。Day1 是首个通过 T 字板规则的交易日；Day2 是 Day1 之后的下一个正常开市交易日；Day3 是 Day2 之后的下一个正常开市交易日。历史样本或回放数据如果缺交易日校验，必须在只读投影中保持空态或中文待校验提示，不能把同日记录显示成次日。

硬失败点：

- Day1 不是 T 字板：淘汰。
- Day1 流通市值不在 50 亿到 300 亿：淘汰。
- Day2 09:30-10:30 每 5 分钟滚动监测均未接近涨停：不触发。
- Day2 接近涨停后仍必须确认盘口方向：`ASK` 表示卖盘被主动买盘扫掉，是可买入观察的主确认；`BID` 表示主动卖出打买盘，是风险 / 失效条件；方向、逐笔或成交金额缺失时进入数据不足 / 等待确认，不得提示可买入观察。动态特征或盘口吸收分缺失继续保留缺口和风险提示，不用 0、mock 或推断补齐。
- Day2 触发后到收盘开板：直接判废，即使后续回封也不改变生产动作。
- Day3 尾盘仍未涨停：生成退出研究事件。

## 阈值

阈值集中在 `config.py` 的版本化配置，不得在业务逻辑里临时改口径：

```yaml
model_code: t_board_relay
model_version: t_board_relay_v1
feature_version: t_board_relay_feature_v1
rule_version: t_board_relay_rule_v1
rules:
  day1_float_market_cap_min: 5000000000
  day1_float_market_cap_max: 30000000000
  day2_monitor_window_start_time: "09:30:00"
  day2_monitor_window_end_time: "10:30:00"
  day2_monitor_interval_minutes: 5
  day2_near_limit_threshold_pct: 0.01
  day3_tail_window_start_time: "14:40:00"
  day3_tail_window_end_time: "14:55:00"
```

## 数据产出

`structured_output` 主要对象：

- `day1_scan`
- `day2_watch_snapshot`
- `day2_entry_trigger`
- `post_entry_monitor`
- `day3_exit_decision`
- `outcome_label`
- `game_hypothesis`
- `repository_write`

五个综合分：

- `seal_commitment_score`
- `disagreement_absorption_score`
- `relay_consensus_score`
- `fake_seal_trap_risk_score`
- `control_failure_score`

`dominant_capital_intent` 只允许作为可观测行为假设，不得写成确定事实。

## 缺口码

当前缺口码包括：

- `source_gap:instrument_identity`
- `source_gap:daily_bar_missing`
- `source_gap:limit_price_missing`
- `source_gap:float_market_cap_missing`
- `source_gap:limit_event_missing`
- `source_gap:close_on_limit_flag_missing`
- `source_gap:one_word_limit_flag_missing`
- `source_gap:seal_order_snapshot_missing`
- `source_gap:minute_bar_or_realtime_quote_missing`
- `source_gap:dynamic_feature_bundle_missing`
- `source_gap:order_book_snapshot_missing`
- `source_gap:trade_tick_missing`
- `source_gap:near_limit_order_absorption_missing`
- `source_gap:post_entry_board_monitor_missing`
- `source_gap:day3_open_price_missing`
- `source_gap:day3_tail_price_missing`

缺口必须保留，不得补 0、空字符串、mock 或 GPT 推断。

## 落库表

当前服务在 repository attached 时直接写生产数据库，生产目标域独立，不复用前三模型表：

- `decision_t_relay.t_board_day1_candidate_v1`
- `decision_t_relay.t_board_day2_watch_snapshot_v1`
- `decision_t_relay.t_board_day2_entry_trigger_v1`
- `decision_t_relay.t_board_day2_market_context_v1`
- `decision_t_relay.t_board_post_entry_monitor_v1`
- `decision_t_relay.t_board_day3_exit_decision_v1`
- `decision_t_relay.t_board_outcome_label_v1`
- `decision_t_relay.t_board_game_hypothesis_snapshot_v1`
- `decision_t_relay.t_board_observation_monitor_snapshot_v1`
- `research_t_relay.t_board_research_sample_v1`

当前 `infra/sql/0022_t_board_relay_decision_schema_v1.sql` 和 `infra/sql/bootstrap_schema.sql` 已包含 `decision_t_relay` / `research_t_relay` 域。`schema-bootstrap` 会按 `infra/sql/*.sql` 顺序创建这些表。表设计为 append-only 审计事实：每次 POST 写入新的阶段记录、原始请求 payload、结果 payload、模型版本、特征版本、run_id 和缺口码，不覆盖历史坏版本。

## 调度

观察台快照调度：`POST /t-board-relay/observation-monitor/snapshot` 由 scheduler 在开盘时段 `09:30-11:30` 与 `13:00-15:00` 每 5 分钟触发，持续记录当前 `observation-board` 输出，直到三交易日观察闭环结束；它只写 `decision_t_relay.t_board_observation_monitor_snapshot_v1`，不反写阶段事实。

当前 Day2 触发后封板维护频率：`POST /t-board-relay/post-entry/monitor` 由 scheduler 在开盘时段 `09:35-11:30` 与 `13:00-15:00` 每 5 分钟触发；任何开板失败都必须 append-only 留存并推动观察台 `updated_at`、`last_monitor_at`、`monitoring_summary` 和风险结论更新。

设计调度：

- Day1 `10:40/14:55/15:02/15:10`：从 THS 公开涨停池构建 `source.limit_event_v1`，识别 T 字板事件。
- Day1 `15:12/15:20/15:30/15:35/15:45`：只对 T 字板阶段候选补交易状态、日线、涨跌停价和流通市值；缺候选时跳过，不继承样本股。
- Day1 `15:05-15:30`：模型 owner 只评估已组装候选 payload，产出 T 字板、流通市值和封单额比例结论。
- Day2 `09:25`：预加载 Day1 合格候选。
- Day2 `09:30-10:30`：从开盘起每 5 分钟滚动观察，首次接近涨停后进入盘口确认；仅 `ASK` 方向主动买盘扫卖盘且成交金额有效时触发接力机会提示；`BID` 方向视为卖压打穿买盘，方向或逐笔缺失时等待确认。
- Day2 触发后到 `15:00`：持续监控是否开板。
- Day3 `09:25-09:35`：判断开盘涨停。
- Day3 `14:40-14:55`：尾盘未涨停则生成退出研究事件。

`scheduler-service` 已接入模型四 non-official 调度任务：

- `t_relay.day1.scan.close` -> `POST /t-board-relay/day1/scan`
- `t_relay.day2.watch.rolling_5m` -> `POST /t-board-relay/day2/watch`
- `t_relay.day2.trigger.rolling_5m` -> `POST /t-board-relay/day2/trigger-check`
- `t_relay.day2.post_entry.monitor` -> `POST /t-board-relay/post-entry/monitor`
- `t_relay.day3.exit.open` -> `POST /t-board-relay/day3/exit-check`
- `t_relay.day3.exit.tail` -> `POST /t-board-relay/day3/exit-check`
- `t_relay.observation.monitor.snapshot_5m` -> `POST /t-board-relay/observation-monitor/snapshot`
- `t_relay.outcome.build` -> `POST /t-board-relay/outcomes/build`

这些任务全部 `is_official_publish=false`。scheduler 可以调度和 live dispatch owner service，但不得把模型四输出改写成 official signal、交易指令或前三模型事实。

## Docker

容器端口为 `8034`，宿主默认端口为 `8035`，compose service 为 `t-board-relay-service`：

```text
uvicorn t_board_relay_model_service.main:app --host 0.0.0.0 --port 8034
```

关键环境变量：

- `AI_STOCK_DATABASE_URL` / `DATABASE_URL`：Postgres repository 连接。
- `PERSIST_DECISIONS`：默认 `true`，为 `false` 时只计算不落库。
- `SOURCE_DATA_SERVICE_BASE_URL`：保留给跨服务配置，不由本服务直接调用 provider。

独立验证可执行：

```text
docker compose -f infra/docker-compose.yml up -d --build --no-deps t-board-relay-service
```

## 禁止反写

- 不直接下单，不写交易事实。
- 不直接采集 BaoStock、AKShare、Tencent、Tushare、EastMoney、Baidu、CNINFO 等 provider。
- 不读取 `raw_*` 作为模型输入。
- 不反写前三模型分数、状态、标签、release gate、买点或学习权重。
- 不把“主导资金意图”写成确定事实，只能写成 `game_hypothesis`。
- 不发布 official signal；模型四当前所有 scheduler task 都是研究 / 模型阶段任务。

## 验收

定向测试：

```bash
PYTHONPATH=services/models_services/t-board-relay-service/src python -m pytest -q services/models_services/t-board-relay-service/tests
```

第一版验收点：

- Day1 严格识别 T 字板：开盘涨停、盘中开板、收盘封涨停。
- Day1 流通市值默认限制 50 亿到 300 亿。
- Day1 计算封单额 / 流通市值比例。
- Day2 保存原始逐笔侧和标准化盘口侧；策略触发语义以“卖盘被主动买盘扫掉”为准，即 `order_consumption_side=ASK`，`BID` 仅作为卖压风险 / 失效条件。
- Day2 缺盘口或逐笔核心数据时 `data_blocked`，不得 official。
- Day2 触发后只要开板就标记 `day2_board_open_after_entry_failed`。
- Day3 开盘涨停生成 `hold_open_limit`。
- Day3 尾盘未涨停生成 `exit_tail_no_limit`。
- Jarvis 只读且 `can_place_order=false`。
- POST 阶段接口在 repository attached 时返回 `repository_write.persisted=true`，并能通过 GET 仓库接口查到真实记录。
- `scheduler-service` sample 和非 dry-run live dispatch 覆盖 Day1 scan、Day2 watch 和 Day2 trigger。
- `data-inspector-service core_closure` 覆盖模型四 ready、Day1/Day2 source preflight 和 `decision_t_relay` repository presence。

2026-06-14 真实 source 样本验收：

```text
样本：000759.SZ / 2026-06-12

source preflight:
  - /source/release/preflight t_board_relay/day1_scan -> can_release_official_signal=true, coverage_status=passed, freshness_status=passed, blocking_reasons=[]。
  - /source/release/preflight t_board_relay/day2_trigger -> can_release_official_signal=true, coverage_status=passed, freshness_status=passed, blocking_reasons=[]。

Day1 输入来自 source.daily_bar_v1、source.limit_price_v1、source.limit_event_v1、source.realtime_quote_v1：
  open_price=5.29, high_price=5.83, low_price=5.16, close_price=5.83
  pre_close_price=5.30, up_limit_price=5.83
  float_market_cap=3822766125.75
  limit_event_type=t_board_limit_up
  limit_open_count=1
  is_one_word_board=false
  close_on_limit_flag=true
  is_break_limit=true

Day1 输出：
  candidate_count=1
  qualified_count=0
  data_blocked_count=0
  candidate_status=rejected
  reject_reason=not_t_board
  is_t_board=false
  float_market_cap_pass=false
  source_gap_codes=[source_gap:seal_order_snapshot_missing]

Day2 watch / trigger 输入来自 source.minute_bar_v1 和 source.trade_tick_v1：
  09:30-10:30 China rolling 5m monitor
  first_qualified_monitor_time=09:35:00 when near-limit condition first appears
  last_price_at_watch=5.78
  up_limit_price=5.83
  distance_to_up_limit_pct=0.008576
  09:30-trigger_time buy-side tick amount=121998001
  buy_tick_count=528

Day2 输出：
  watch_status=near_limit_reached
  entry_trigger_status=triggered
  trigger_time=09:35:00
  no data_blocked
  source_gap_codes=[source_gap:dynamic_feature_bundle_missing, source_gap:near_limit_order_absorption_missing]

结论：该样本真实 source 链路不阻断，模型按滚动 5 分钟规则触发接力机会；剩余动态特征和吸收分缺口必须保留，不得用 0、mock 或推断补齐。
```

字段兼容要求：`day1/scan` 必须接受 source 标准字段 `is_one_word_board`，并等价映射到模型内部 `is_one_word_limit` 语义；不得因为 source 字段名与早期模型字段名不同生成 `source_gap:one_word_limit_flag_missing`。

## 当前闭环结论

模型四 owner service 已从纯 side-effect free API 升级为可生产闭环服务：实现版本化阈值、Day1/Day2/Day3 状态机、缺口码、理论买入研究事件、买入后封板维护硬规则、Day3 去留动作、outcome、博弈假设输出、Postgres append-only repository、scheduler live dispatch 和 data-inspector 巡检域。2026-06-15 闭环口径使用 `000759.SZ / 2026-06-12` 真实 source 标准层事实验证 Day1/Day2 source preflight；该样本 Day1/Day2 source preflight passed，owner API 不 data_blocked，业务结果可为真实规则拒绝/未触发。动态特征服务源码仍未落地，缺 `dynamic_feature_bundle` 或 `near_limit_order_absorption_score` 时必须保留缺口码，不能用 0、mock 或推断补齐；Day2 买入观察提示以 `ASK` 方向主动买盘扫卖盘和有效成交金额为硬确认，`BID` 方向不触发。

2026-06-23 复核 `2026-06-22` 真实 source T 字板阶段候选：`source.limit_event_v1` 候选 65 只，`source.daily_bar_v1`、`source.limit_price_v1`、`source.trade_status_v1`、`source.realtime_quote_v1` 覆盖均为 65/65；模型四 Day1 owner 写入 `decision_t_relay.t_board_day1_candidate_v1` 65 行，`qualified=4`、`rejected=61`、`data_blocked=0`。观察台修复为查询阶段先取 Day1 合格对象，默认 `limit` 不再被 rejected 行挤占；用户文案统一由 observation-board 投影层输出中文业务提示。

2026-06-23 ASK/BID 触发语义修正：用户确认策略真实意图为“卖盘被主动买盘扫掉”才是买入观察确认，因此 Day2 `entry_trigger_status=triggered` 必须同时满足 Day1 合格、09:30-10:30 五分钟滚动接近涨停、`order_consumption_side=ASK` 且 `order_consumption_amount>0`。`order_consumption_side=BID` 表示主动卖出打买盘，输出 `not_triggered/day2_bid_pressure_hit_buy_orders`；方向或成交金额缺失时输出 `data_blocked/day2_ask_sweep_confirmation_missing`。`observation-board` 对历史遗留 `triggered+BID` 记录也按停止观察投影，不再显示“可买入观察”。普通用户投影不得直接展示 `ASK` / `BID`，必须显示“买盘主动扫掉卖盘”“卖盘主动砸向买盘”或“盘口方向待确认”这类白话结论。

2026-06-24 普通用户观察台字段去重：前端主列表只展示 `股票 / 模型分 / Day1 / Day2 / 监测时间 / 当前判断 / 接力强度 / 关键依据 / 风险结论 / 更新`。`模型分` 承载 owner 投影给出的综合排序分，`当前判断` 承载阶段性结果，`关键依据` 承载触发或停止观察的主因，`风险结论` 承载模型从盘口方向、成交强度、封板维护、Day3 去留或事实缺口得到的风险事实，不再使用“接力机会提示仅作观察，不自动下单”这类无业务含义提示。

2026-06-24 持续监测投影强化：`observation-board` 新增 `updated_at`、`last_monitor_at`、`monitor_interval_minutes`、`monitoring_summary`。Day2 未触发时展示最近五分钟 watch；ASK 确认触发后展示“每5分钟跟踪封板”；post-entry 开板或封住到收盘时由最新 append-only monitor 记录更新状态、风险结论和更新时间。当前 schema 尚无真实监测次数列，因此观察台不输出伪造的累计次数；后续若要统计完整三交易日监测点，应先补阶段表或独立监测事件表。

2026-06-24 模型分排序投影：`observation-board` 新增 `model_score`、`model_score_label`、`score_state` 和 `model_score_version=t_board_relay_observation_score_v1`。评分只读派生自 Day1、Day2 watch/trigger、post-entry monitor、Day3、outcome 与缺口事实；`data_wait` 时保持 `model_score=NULL`，不补 0。接口在内部评分窗口内按模型分降序、无分后置、更新时间倒序排序后再返回 `limit` 条，前端只消费该分数字段并按同一口径降序展示。

## 拍板冻结记录

### t-board-relay-service -> observation-board -> qualified day1 projection

- 冻结时间：2026-06-23 Asia/Shanghai。
- 拍板人 / 确认来源：用户批准解锁并修复模型四观察台投影问题。
- 锁定范围：`GET /t-board-relay/observation-board` 查询阶段只读读取 Day1 合格对象、正常开市交易日顺序校验、中文用户文案投影、`data_gap_labels` 中文化且不暴露 `source_gap:*`、默认 `limit` 不丢失已合格观察对象。
- 当前冻结证据：模型四单测 `13 passed`；2026-06-22 owner 写入 65 行 Day1 候选，其中 4 行合格；修复前 `limit=20` 观察台为空而 `limit=80` 返回 4 行，修复目标为默认分页也返回合格对象。
- 允许的只读验收：读取 `/t-board-relay/observation-board?limit=20`、`/t-board-relay/repository/status`、Day1 candidates GET、scheduler readyz、data-inspector readyz、前端模型四页面只读查看。
- 禁止修改项：未经解锁不得改变 Day1 合格判定、状态机、阈值、schema、append-only 写入语义、source preflight、scheduler 任务计划或前端只读边界；不得把 rejected/data_blocked 对象放入普通用户观察台主列表。
- 解锁条件：用户明确批准本观察台投影子对象解锁，并说明目标、影响范围、拟修改文件、回滚方式和验证清单。
- 回滚方式：回退本次 `api.py`、`repository.py`、`test_api.py`、README 与 DATA_ASSETS 变更，重新构建模型四容器并复查 readyz 与 observation-board。
- 验证清单：默认 `limit` 返回 Day1 合格对象；响应文案为中文；响应中不出现 `source_gap:*`；repository attached/table_ready；scheduler/data-inspector/source ready。

### t-board-relay-service -> owner repository/frontend-readonly chain -> model4 closure evidence

- 冻结时间：2026-06-21 Asia/Shanghai。
- 拍板人 / 确认来源：用户在模型四 owner、调度和前端只读验收后回复“批准”，并授权 Codex 判定可冻结。
- 锁定范围：`t_board_relay_v1` owner service 健康契约、Day1/Day2/Day3 状态机、正常开市交易日口径、版本化阈值、缺口码语义、`decision_t_relay.*` / `research_t_relay.*` append-only repository、`GET /t-board-relay/repository/status`、Day1/Day2/Day3/outcome/game hypothesis 只读 GET、`GET /t-board-relay/observation-board` 普通用户观察台投影、scheduler non-official live dispatch 对接、data-inspector 模型四巡检域、前端 `#/model-tboard` 经 `GET /api/model-list/tboard` 只读展示观察台的边界。
- 当前冻结证据：2026-06-21 只读复验显示 `/readyz` 为 `ready`、`repository_attached=true`、`persist_decisions=true`、`table_ready=true`、`warning_codes=[]`；仓库计数为 Day1 候选 1、Day2 观察 1、Day2 触发 1、博弈假设 1、post-entry/Day3/outcome/research sample 当前为 0；`scheduler-service /readyz` 和 `data-inspector-service /readyz` 均为 `ready`。
- source preflight 口径：当前历史样本 `000759.SZ / 2026-06-12` 的模型四 Day1/Day2 preflight 为 coverage passed 但 historical decision_time freshness late，因此 `can_release_official_signal=false`；该结果只说明历史回放时间戳下 official release 仍被阻断，不解除模型四 non-official 研究定位，也不阻断当前 repository、scheduler、data-inspector 和前端只读闭环冻结。
- 允许的只读验收：读取 `/readyz`、`/t-board-relay/repository/status`、`/t-board-relay/observation-board`、Day1/Day2/Day3/outcome/game-hypothesis GET、scheduler validate / readyz、data-inspector readyz / current closure、source release preflight 只读探针、前端 `#/model-tboard` 截图与 compact 响应检查、模型四和前端相关单元/合同测试。
- 禁止修改项：未经用户明确解锁，不得修改模型四代码、阈值、状态机、交易日口径、缺口码、schema/bootstrap、repository 写入语义、`observation-board` 纳入规则、Docker/Compose/env/健康检查、scheduler 模型四任务计划或 live dispatch、data-inspector 模型四巡检域、source preflight 规则、前端模型四观察台投影和只读展示边界；不得把 Day1 未通过对象放入普通用户观察台，不得把模型四输出改写成 official signal、交易事实、买点版本或前三模型事实。
- 解锁条件：用户明确批准 `t-board-relay-service -> owner repository/frontend-readonly chain -> model4 closure evidence` 或其子对象解锁，并说明目标、影响范围、拟修改文件、回滚方式和验证清单；若涉及 source/scheduler/data-inspector/Postgres/schema/Docker，需要另行按锁定服务规则申请。
- 回滚方式：仅回退本冻结对象对应的后续变更；若后续曾发布镜像，恢复解锁前镜像或文档版本并重新执行只读健康检查。不得通过清库、全栈重建或重启 `source-data-service` 回滚模型四冻结事实。
- 验证清单：模型四 `/readyz` ready；`/t-board-relay/repository/status` repository attached 且 table ready；`/t-board-relay/observation-board` 只返回 Day1 合格观察对象且不暴露 `source_gap:*`；scheduler `/readyz` ready；data-inspector `/readyz` ready；source preflight blocked 时仍保留 blocking reasons；前端 compact 响应不泄露 `request_payload`、`result_payload`、`game_hypothesis_payload`、`evidence_json`、`related_payload`；页面可见文本不暴露 `source_gap:*`、接口路径、schema/table/raw/provider 程序文本；缺动态特征继续保留中文缺口或 gap，不用 0/mock/推断补齐。

### t-board-relay-service -> observation-monitor -> snapshot_5m output retention

- 冻结时间：2026-06-24 Asia/Shanghai。
- 拍板人 / 确认来源：用户授权 Codex 判断模型四链路是否可拍板，并在本轮回复“批准”；Codex 基于 scheduler catch-up、research execution、owner snapshot、frontend compact API 和浏览器 DOM 验收判定可以冻结。
- 锁定范围：`POST /t-board-relay/observation-monitor/snapshot` 只读当前 `observation-board`，每 5 分钟 append-only 写入 `decision_t_relay.t_board_observation_monitor_snapshot_v1`；2026-07-01 起，该历史冻结仅保留 `projection_snapshot_5m` 留痕和恢复审计语义，字段优先级由 `t-board-relay-service -> observation-board -> dual time and 30m result projection` 覆盖，5 分钟快照不得推动 `latest_snapshot_time`、`display_update_at`、`updated_at`、`last_monitor_at` 或 `last_model_output_at`；快照不替代 Day2 watch、post-entry monitor、Day3 或 outcome 阶段事实。
- 当前冻结证据：2026-06-24 通过 `POST /scheduler/model-schedule/catch-up` 对 `t_relay.observation.monitor.snapshot_5m` 执行 09:35 槽位补偿，research execution materialized；`decision_t_relay.t_board_observation_monitor_snapshot_v1` 从 4 行增至 8 行；owner `/t-board-relay/observation-monitor/snapshots?limit=20` 产生 4 条新快照；`/t-board-relay/observation-board?limit=20` 仍只返回 4 条 Day1 合格对象，且 4 行 `latest_snapshot_time/updated_at/last_monitor_at=2026-06-24T09:50:48.617447+00:00`，股票为 002297.SZ 博云新材、600769.SH 祥龙电业、301580.SZ 爱迪特、600172.SH 黄河旋风，模型分排序为 15/12/12/0。
- 允许的只读验收：读取 `/t-board-relay/observation-board?limit=20`、`/t-board-relay/observation-monitor/snapshots?limit=20`、`/t-board-relay/repository/status`、scheduler/runtime/status、research `/readyz`、frontend `/api/model-list/tboard` 和 `#/model-tboard` DOM。
- 禁止修改项：未获解锁不得把快照补偿时间伪装成历史实时盘口时间，不得让快照反写 Day2/Day3 阶段表，不得用快照补齐缺失盘口或交易事实，不得输出 official signal、交易、买点或前三模型事实，不得重启 `source-data-service` 回滚快照事实。
- 解锁条件：观察台快照频率、快照表结构、owner `observation-board` 字段优先级、scheduler catch-up 语义、research execution 合同变化，或用户明确批准解锁。
- 回滚方式：回退后续快照投影/文档变更；如曾发布 owner 镜像，仅 `--no-deps` 替换 t-board owner；不清库、不删除快照、不重启 source-data-service。
- 验证清单：Day1 合格对象可读；快照表 append-only 增长；最新 5 分钟投影快照只出现在 `latest_projection_snapshot_at` / 快照 id，不冒充抓取时间或模型产出时间；股票代码和名称完整；模型分由 owner 给出并降序展示；compact 不泄露审计 payload；前端页面不显示 `ASK`、`BID`、`source_gap:*`、`数据提示` 或无意义免责声明。

### t-board-relay-service -> observation-board -> dual time and 30m result projection

- 冻结对象：`t-board-relay-service -> observation-board -> dual time and 30m result projection`。
- 冻结时间：2026-07-01 Asia/Shanghai。
- 拍板人 / 确认来源：用户在本轮模型四双时间与 30 分钟产出修复交付后回复“允许”，批准将该口径拍板冻结。
- 锁定范围：`GET /t-board-relay/observation-board` 的时间字段语义、`POST /t-board-relay/observation-monitor/snapshot` 的 `projection_snapshot_5m` / `model_result_30m` 分流、`decision_t_relay.t_board_observation_monitor_snapshot_v1` append-only 留存和普通用户前端时间展示边界。`latest_data_fetch_at`、`last_data_captured_at`、`latest_snapshot_time`、`display_update_at` 必须来自真实阶段事实或真实抓取时间；`latest_projection_snapshot_at` 只代表 5 分钟投影审计；`last_model_output_at` / `model_evaluated_at` 只能由 `monitor_interval_minutes>=30` 且 `result_kind=model_result_30m` 的 30 分钟结果推动。该入口不调用 provider、不补盘口事实、不生成 official signal。
- 当前冻结证据：2026-07-01 验收时 research requirements 为 26 个任务并包含 `t_relay.live_result.compute_30m`；scheduler `/readyz` ready，source/model task store `blocking_statuses=[]`；人工仅在备份后重排两条模型四死信任务并保留审计，重放后成功；owner 观察台和前端 compact 同时暴露 `last_model_output_at=2026-07-01T02:32:00+00:00`、`latest_projection_snapshot_at=2026-07-01T02:30:00+00:00`，而真实抓取 / 阶段事实时间仍保持为旧值，未被 5 分钟投影覆盖。
- 允许的只读验收：读取 `/readyz`、`/t-board-relay/observation-board`、`/t-board-relay/observation-monitor/snapshots`、`/t-board-relay/repository/status`、research `/research/model-payload/requirements`、scheduler `/readyz` / runtime status、frontend `/api/model-list/tboard` 和 `#/model-tboard`。
- 禁止修改项：未经解锁不得把 `latest_projection_snapshot_at` 合并到抓取时间、模型产出时间或 `display_update_at`；不得让 5 分钟快照覆盖阶段事实时间；不得隐藏真实抓取未推进、数据缺口或失败状态；不得删除快照审计、死信重排审计或绕过 source-data-service 正规取数链路；不得让模型四 owner 直接调用 provider/raw 或输出交易、买点、official signal。
- 解锁条件：用户明确批准本冻结对象解锁；若涉及 owner 状态机、snapshot 表结构、scheduler 调度、research 任务注册、source 抓取链路、schema/Docker 或前端普通用户合同，必须分别说明影响范围、拟修改文件、回滚方式和验证清单。
- 回滚方式：回退本对象后续 owner 时间字段 / snapshot 分流变更，并重新构建或重启受影响 owner 容器做 readyz、observation-board、snapshot 和 frontend compact 只读验收；不得通过清库、全栈重建或重启 `source-data-service` 回滚时间事实。
- 验证清单：30 分钟模型结果能推动 `last_model_output_at/model_evaluated_at`；5 分钟快照只推动 `latest_projection_snapshot_at`；真实抓取/阶段事实时间不被投影覆盖；前端同时展示“模型”和“抓取”两段时间；模型四、research 和前端合同测试通过；scheduler/data-inspector/source 健康。

### t-board-relay-service -> observation-board -> terminal data gap and stale result guard

- 冻结对象：`t-board-relay-service -> observation-board -> terminal data gap and stale result guard`。
- 冻结时间：2026-07-02 Asia/Shanghai。
- 拍板人 / 确认来源：用户在本轮交付报告后明确回复“拍板”；此前用户指出模型四前端不应让第二天或第三天已经不符合的对象继续留在待观察状态。
- 锁定范围：`GET /t-board-relay/observation-board` 的 Day2 窗口过期判定、`data_wait` 投影、模型分空态和 30 分钟历史结果快照覆盖边界。Day2 `09:30-10:30` 窗口已过且没有有效 Day2 watch / trigger 事实时，必须投影为 `observation_status=data_wait`、`score_state=data_wait`、`model_score=NULL`，不得继续显示观察中。窗口是否已过必须按 Asia/Shanghai 先由 Day1 推导预期 Day2 工作日并周末顺延；当前日期晚于预期 Day2 时即视为窗口已过，不受当前时刻是否到 10:30 影响。30 分钟 `model_result_30m` 只能刷新模型产出时间；当 owner 当前投影已基于真实阶段事实或缺口判为 `data_wait`、`stopped` 或 `completed` 时，历史模型结果快照不得把状态、分数、当前判断、关键依据或风险结论复活为 `continue_watch` / `opportunity`。
- 当前冻结证据：2026-07-02 重新构建并单独重启 `t-board-relay-service` 后 `/readyz=ready`；`/t-board-relay/observation-board?limit=20` 中 `000823.SZ` 为 `observation_status=data_wait`、`model_score=NULL`，Day1 为 `2026-06-26`，真实阶段事实时间仍为 `2026-06-26T07:53:37.143354+00:00`，最后模型产出时间为 `2026-07-02T07:02:00+00:00`；前端默认 `/api/model-list/tboard?limit=20` 返回 0 条，审计参数仍可查询 000823；模型四 owner 单测 30 passed。
- 允许的只读验收：读取 `/readyz`、`/t-board-relay/observation-board`、`/t-board-relay/observation-monitor/snapshots`、`/t-board-relay/repository/status`、frontend `/api/model-list/tboard` 默认与 `include_stale_stopped=true` 响应、scheduler `/readyz`、data-inspector `/readyz`，以及模型四 owner 单测。
- 禁止修改项：未经解锁不得把 Day2 已错过验证窗口且缺真实监测事实的对象继续显示为 `continue_watch`、不得把 `data_wait` 分数补为 0、不得让历史 `model_result_30m` 覆盖当前终止或缺口状态、不得用 5 分钟投影快照或当前时间补真实抓取 / 阶段事实时间、不得删除 observation monitor snapshot 或 owner append-only 审计事实、不得让模型四 owner 直接调用 provider/raw 或输出交易、买点、official signal。
- 解锁条件：用户明确批准本冻结对象解锁；若涉及 Day2/Day3 状态机、正式交易日历、snapshot 表结构、scheduler 模型四频率、source 抓取链路、schema/Docker 或前端普通用户合同，必须分别说明影响范围、拟修改文件、回滚方式和验证清单。
- 回滚方式：回退本对象后续 owner Day2 过期判定、快照覆盖边界、测试和文档变更，并仅 `--no-deps` 替换或重启 `t-board-relay-service` 做 readyz、observation-board 和 frontend compact 只读验收；不清库、不删除快照、不重启 `source-data-service`。
- 验证清单：Day2 预期工作日已过时缺有效监测事实的对象投影为 `data_wait` 且 `model_score=NULL`；历史 30 分钟结果不得复活 `continue_watch` / 旧分数；真实抓取 / 阶段事实时间不被投影覆盖；前端默认列表下架终止 / 过期缺口对象，审计参数仍可查；模型四 owner、frontend、scheduler、data-inspector、source 健康。

### t-board-relay-service -> observation-board -> Day2 post-entry failure projection

- 冻结时间：2026-06-24 Asia/Shanghai。
- 拍板人 / 确认来源：用户要求 Codex 决定是否拍板；Codex 判定模型四 Day2 后触发开板投影和前端只读链路已满足当前“今天可读”目标，可窄冻结。
- 锁定范围：`GET /t-board-relay/observation-board` 对 Day2 有效触发后的 `decision_t_relay.t_board_post_entry_monitor_v1` 具有最新事实优先级；理论触发后只要出现开板即投影为停止观察；`risk_tip` 必须是基于封板维护失败、盘口方向、成交强度、Day3 去留或事实缺口的风险结论，不得输出无业务含义免责声明；`latest_snapshot_time` 随 Day2 watch 或 post-entry monitor 更新。
- 当前冻结证据：observation-board 当前返回 4 条 Day1 合格对象；`600172.SH 黄河旋风` 最新投影为 `current_conclusion=触发后开板，停止观察`，关键依据“理论触发后出现开板”，风险结论“触发后开板，封板维护失败，Day3退出风险升高”，更新时间来自 `2026-06-23T23:42:20.913001+00:00`；repository attached/table ready。
- 允许的只读验收：读取 `/t-board-relay/observation-board?limit=20`、`/t-board-relay/repository/status`、post-entry status GET、scheduler readyz、data-inspector readyz、前端 compact/page。
- 禁止修改项：未获解锁不得降低 post-entry monitor 优先级，不得把开板失败继续显示为可买入观察，不得恢复 `ASK` / `BID` 原始枚举展示，不得输出 `source_gap:*` 或审计大字段给普通用户，不得写 official signal、交易、买点或前三模型事实。
- 解锁条件：用户明确批准本子对象解锁；若涉及 scheduler 时间轮、schema/source/data-inspector/Docker，需另行说明影响范围和回滚方式。
- 回滚方式：回退后续 owner projection/repository 文档或代码变更；如曾发布镜像则仅重建/替换 t-board owner，不触碰 source-data-service/source-data-worker/data-inspector/Postgres。
- 验证清单：4 条 Day1 合格对象可读；600172.SH 显示开板失败；风险结论不是免责声明；compact 不泄露审计 payload；Day3 自然窗口未完成前不得写成已完成结论。

### t-board-relay-service -> model4 reset -> 2026-07-08 zero state

- Record time: 2026-07-08 Asia/Shanghai.
- Confirmation source: user explicitly approved clearing model4 data within the locked scope and without historical backup.
- Cleared scope: all rows in `decision_t_relay.*`, all rows in `research_t_relay.*`, and `governance.research_model_execution_audit_v1` rows where `model_code='t_board_relay'`, `owner_service='t-board-relay-service'`, or `task_code LIKE 't_relay.%'`.
- Preserved scope: `source.*`, `raw_*`, lineage, provider probes, source fetch queue, scheduler task store, Cookie/runtime source credentials, Docker images, service code, model thresholds, state machine, frontend contract, and locked scheduler/data-inspector/source facts.
- Verification facts: 9 model4 owner/research tables are `0` rows; model4 research execution audit is `0` rows; `GET /t-board-relay/observation-board?limit=100&include_stale_stopped=true` returns `0` items; source, scheduler, data-inspector, and t-board-relay readyz are ready.
- Boundary: this is an authorized zero-data operational state only. Future model4 data must be regenerated by the formal scheduler/research/owner chain and must keep real `NULL`, gap codes, blocked states, and append-only semantics.
