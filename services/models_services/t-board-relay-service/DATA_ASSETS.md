# t-board-relay-service DATA_ASSETS

本文件是 `t-board-relay-service` 的数据资产账本，不替代本目录 `README.md`。

## 读取数据

| 资产 | 用途 | 优先级 |
|---|---|---|
| `source.daily_bar_v1` | Day1 T 字板日线结构 | P0 |
| `source.limit_price_v1` | 涨跌停价 | P0 |
| `source.limit_event_v1` | T 字板、回封、开板次数 | P0 |
| `source.trade_status_v1` | 可交易性 | P0 |
| `source.realtime_quote_v1.float_market_cap` | Day1 流通市值筛选；报价行同时服务 Day2 near-limit watch | P0 |
| `source.minute_bar_v1` | Day2 开盘后 5 分钟滚动观察、触发后封板维护 | P0 |
| `source.trade_tick_v1` | 逐笔方向和成交金额证据；Day2 `ASK` 扫卖盘为触发确认，`BID` 打买盘为风险 / 失效证据 | P0 |
| `decision.dynamic_feature_*` 或 `t_board_relay_intraday_bundle_v1` | 盘口吸收动态特征；缺吸收分或方向金额时保留 gap，不补 0 | 当前缺独立服务，缺失保留 gap |

## 写入数据

repository attached 且 `PERSIST_DECISIONS=true` 时，本服务 append-only 写入：

| 表 | 作用 |
|---|---|
| `decision_t_relay.t_board_day1_candidate_v1` | Day1 候选 |
| `decision_t_relay.t_board_day2_watch_snapshot_v1` | Day2 观察 |
| `decision_t_relay.t_board_day2_entry_trigger_v1` | Day2 触发 |
| `decision_t_relay.t_board_post_entry_monitor_v1` | 触发后封板维护 |
| `decision_t_relay.t_board_day3_exit_decision_v1` | Day3 去留 |
| `decision_t_relay.t_board_outcome_label_v1` | outcome |
| `decision_t_relay.t_board_game_hypothesis_snapshot_v1` | 博弈假设 |
| `decision_t_relay.t_board_observation_monitor_snapshot_v1` | 普通用户观察台当前输出的 5 分钟 append-only 快照 |
| `research_t_relay.t_board_research_sample_v1` | 研究样本 |

## 只读投影

当前投影资产补充：
- `GET /t-board-relay/observation-board` 必须读取 `decision_t_relay.t_board_day2_watch_snapshot_v1`，用于未触发前的 Day2 五分钟滚动观察展示。
- `latest_snapshot_time` 的优先级包含 Day2 watch 和 post-entry monitor；只要 Day2 五分钟快照或触发后封板维护快照更新，普通用户前端的“更新”列就必须随只读投影更新。
- `decision_t_relay.t_board_post_entry_monitor_v1` 是触发后至收盘的封板维护留存资产，开板失败也必须 append-only 留存，不能由前端覆盖或推断。
- `model_score`、`model_score_label`、`score_state` 和 `model_score_version` 是 `observation-board` 只读派生字段，来源仍是下方 `decision_t_relay.*` 阶段资产；关键事实缺失时保持 `model_score=NULL`，不得补 0 或由前端自行评分。

| 接口 | 读取资产 | 作用 | 边界 |
|---|---|---|---|
| `GET /t-board-relay/observation-board` | `decision_t_relay.t_board_day1_candidate_v1`、`decision_t_relay.t_board_day2_watch_snapshot_v1`、`decision_t_relay.t_board_day2_entry_trigger_v1`、`decision_t_relay.t_board_post_entry_monitor_v1`、`decision_t_relay.t_board_day3_exit_decision_v1`、`decision_t_relay.t_board_outcome_label_v1`、`decision_t_relay.t_board_game_hypothesis_snapshot_v1`、`decision_t_relay.t_board_observation_monitor_snapshot_v1` | 生成普通用户 T 字接力观察台和 `t_board_relay_observation_score_v1` 模型分 | 只读；查询阶段先读取 Day1 合格对象，构建最多 500 条评分排序窗口，再按 `model_score` 降序、无分后置、更新时间倒序返回 `limit` 条；只纳入 Day1 合格对象；按正常开市交易日顺序校验 Day2/Day3；历史遗留 `triggered+BID` 记录按停止观察投影，`triggered` 但缺 `ASK` 扫卖盘确认时按等待确认投影，不提示可买入观察；只在观察台快照时间晚于阶段投影时，用快照刷新用户可读字段、`updated_at` 和模型分；`key_reason` 使用 `Day2` / `Day3` 描述关键原因；普通用户文案不直接展示 `ASK` / `BID`，只显示“买盘主动扫掉卖盘”“卖盘主动砸向买盘”或“盘口方向待确认”；阶段查询只取轻量业务列，不读取或返回 `request_payload`、`result_payload`、`game_hypothesis_payload`、`evidence_json`、`related_payload`；不写库、不触发调度、不补事实、不暴露 `source_gap:*`。前端普通用户列表展示 `model_score` 但不自行计算分数；不展示 `data_notice` 或 `data_gap_labels`，这些字段只保留给只读合同和审计。 |
| `POST /t-board-relay/observation-monitor/snapshot` | `GET /t-board-relay/observation-board` 当前投影 | 写入 `decision_t_relay.t_board_observation_monitor_snapshot_v1` | 每 5 分钟留存当前用户可读输出、模型分、关键原因、风险结论和更新时间；不调用 provider、不补事实、不生成 official signal。 |
| `GET /t-board-relay/observation-monitor/snapshots` | `decision_t_relay.t_board_observation_monitor_snapshot_v1` | 只读返回观察台快照 | 用于回放和调优审计，不反写 Day2/Day3 阶段事实表。 |

`observation-board` 的 `risk_tip` 是面向普通用户的风险结论资产，只能来自盘口方向、成交强度、封板维护、Day3 去留或事实缺口；不得用“仅作观察、不自动下单”这类免责提示占位。前端主列表仅展示去重后的核心列：`股票 / 模型分 / Day1 / Day2 / 监测时间 / 当前判断 / 接力强度 / 关键依据 / 风险结论 / 更新`。

## 调度频率

当前观察台快照频率：`t_relay.observation.monitor.snapshot_5m` 在 `09:30-11:30` 与 `13:00-15:00` 每 5 分钟触发，写入 `decision_t_relay.t_board_observation_monitor_snapshot_v1`，持续留存 Day1 入选后到 Day3 闭环的当前模型输出；该资产用于后续调优和前端更新时间持续前进，不替代阶段事实。

当前 Day2 触发后维护频率：`post-entry/monitor` 应按开盘时段每 5 分钟持续记录，覆盖 `09:35-11:30` 与 `13:00-15:00`；中间若开板，状态和风险结论需要及时更新，但历史快照继续留存。

- Day1 10:40、14:55、15:02、15:10 从 THS 公开涨停池构建 `source.limit_event_v1`。
- Day1 15:12、15:20、15:30、15:35、15:45 只对 T 字板阶段候选补 `source.trade_status_v1`、`source.daily_bar_v1`、`source.limit_price_v1` 和 `source.realtime_quote_v1.float_market_cap`。
- Day1 15:05-15:30 owner 评估已组装候选，产出 T 字板、流通市值和封单额比例结论。
- Day2 09:25 预加载。
- Day2 09:30-10:30 每 5 分钟滚动观察；接近涨停后必须继续确认 `order_consumption_side=ASK` 且 `order_consumption_amount>0` 才触发，`BID` 为卖压风险 / 失效条件，方向或金额缺失时等待确认或 `data_blocked`。
- Day2 触发后至 15:00 封板维护。
- Day3 09:25-09:35 开盘去留。
- Day3 14:40-14:55 尾盘退出研究事件。
- outcome 每日收盘和成熟窗口。

## 禁止事项

模型四当前 non-official，不发布 official signal，不下单，不写交易事实，不把 `dominant_capital_intent` 写成确定事实。缺动态特征、逐笔方向、成交金额或盘口吸收时保留 `source_gap:*` 或阻断状态，不用 0、空字符串、mock 或推断补齐，也不得把 `BID` 打买盘解释成买入确认。

## 数据资产冻结记录

### t-board-relay-service -> observation-board -> qualified day1 projection

- 冻结时间：2026-06-23 Asia/Shanghai。
- 拍板人 / 确认来源：用户批准解锁并修复模型四观察台投影问题。
- 锁定范围：`GET /t-board-relay/observation-board` 只读读取 `decision_t_relay.t_board_day1_candidate_v1` 最新 Day1 合格对象，避免 rejected/data_blocked 行在分页前挤掉合格对象；关联读取 Day2/Day3/outcome/hypothesis 表时只做只读投影，不写库、不触发调度、不补事实。
- 当前数据资产证据：2026-06-22 source T 字候选 65 只，P0 source 覆盖 65/65；模型四 Day1 写入 65 行，`qualified=4`、`rejected=61`、`data_blocked=0`；观察台默认分页修复为返回合格对象。
- 允许的只读验收：读取 observation-board、repository status、Day1 candidates GET、Postgres 只读计数、scheduler/data-inspector/source readyz。
- 禁止修改项：未经解锁不得改变 Day1 合格查询条件、Day2/Day3 正常交易日关联规则、中文缺口标签投影、append-only 表写入语义或 source/provider 边界；不得让前端、Jarvis、gateway 或解释层改写模型四事实。
- 解锁条件：用户明确批准本观察台数据资产子对象解锁；若涉及 schema、source、scheduler、data-inspector 或 Docker，需要另行说明影响范围、拟修改文件、回滚方式和验证清单。
- 回滚方式：回退本次观察台投影和 repository 查询变更，重建模型四容器，重新执行 observation-board、repository status、scheduler/data-inspector/source readyz。
- 验证清单：默认 `limit` 可返回 Day1 合格对象；响应只含中文业务缺口标签，不含 `source_gap:*`；repository attached/table_ready；source preflight blocked 时仍保留 blocking reasons。

### t-board-relay-service -> owner repository/frontend-readonly chain -> model4 closure evidence

- 冻结时间：2026-06-21 Asia/Shanghai。
- 拍板人 / 确认来源：用户在模型四链路验收后回复“批准”，并授权 Codex 判定可冻结。
- 锁定范围：模型四只读取经过 source build、quality_status、lineage 和 available_at 校验的 `source.daily_bar_v1`、`source.limit_price_v1`、`source.limit_event_v1`、`source.trade_status_v1`、`source.realtime_quote_v1`、`source.minute_bar_v1`、`source.trade_tick_v1` 以及允许的动态特征事实；append-only 写入 `decision_t_relay.t_board_day1_candidate_v1`、`decision_t_relay.t_board_day2_watch_snapshot_v1`、`decision_t_relay.t_board_day2_entry_trigger_v1`、`decision_t_relay.t_board_post_entry_monitor_v1`、`decision_t_relay.t_board_day3_exit_decision_v1`、`decision_t_relay.t_board_outcome_label_v1`、`decision_t_relay.t_board_game_hypothesis_snapshot_v1`、`research_t_relay.t_board_research_sample_v1`；`GET /t-board-relay/observation-board` 只读投影只纳入 Day1 合格对象并按正常开市交易日顺序展示 Day2/Day3；前端只通过 compact 只读列表消费观察台事实。
- 当前数据资产证据：2026-06-21 只读复验显示 repository 已连接、持久化开启、表可读且 warning 为空；仓库中 Day1 候选、Day2 观察、Day2 触发、博弈假设已有真实记录，post-entry、Day3、outcome、research sample 当前为空态。
- 调度频率锁定：Day1 15:05-15:30；Day2 09:25 预加载；Day2 09:30-10:30 每 5 分钟滚动观察和触发；Day2 触发后至 15:00 封板维护；Day3 09:25-09:35 开盘去留；Day3 14:40-14:55 尾盘退出研究事件；outcome 每日收盘和成熟窗口。全部保持 non-official 研究 / 模型阶段任务。
- 允许的只读验收：读取 owner repository status、`/t-board-relay/observation-board`、阶段 GET 列表、scheduler readyz/validate、data-inspector readyz/current closure、source release preflight、前端 compact 响应和页面截图；运行不会写库的合同测试或只读探针。
- 禁止修改项：未经解锁不得新增 provider/raw 读取，不得让模型四直接并发抓取外部 provider，不得把 `source.trade_tick_v1` 伪装成完整五档盘口，不得用 0、空字符串、mock、示例 payload 或推断补齐 `dynamic_feature_bundle`、`near_limit_order_absorption_score`、封单快照、post-entry、Day3、outcome 等缺口；不得让 Day1 未通过对象进入普通用户观察台；不得让前端、Jarvis、gateway 或解释层改写模型四事实。
- 解锁条件：用户明确批准本冻结对象或具体子对象解锁；若涉及 source 字段、schema/bootstrap、scheduler live dispatch、data-inspector 巡检域或 Docker，需要按锁定服务规则另行说明影响范围、拟修改文件、回滚方式和验证清单。
- 回滚方式：回退后续对上述数据资产合同的变更，并重新执行 owner repository status、scheduler readyz、data-inspector readyz 和前端 compact 只读检查；不得通过清库、全栈重建或 source-data-service 重启来回滚数据资产冻结记录。
- 验证清单：repository attached；table_ready；Day1/Day2 真实记录可读；观察台只返回 Day1 合格对象；source preflight blocked 时保留 blocking reasons；scheduler 和 data-inspector ready；前端 compact 响应不含审计大字段；页面中文展示缺口，不暴露 raw/provider/schema/table 程序事实。

### t-board-relay-service -> observation-monitor -> snapshot_5m output asset

- 冻结时间：2026-06-24 Asia/Shanghai。
- 数据资产范围：`decision_t_relay.t_board_observation_monitor_snapshot_v1` 是普通用户观察台当前输出的 5 分钟 append-only 快照表；`POST /t-board-relay/observation-monitor/snapshot` 只读 `GET /t-board-relay/observation-board` 当前投影并写入快照；`GET /t-board-relay/observation-monitor/snapshots` 只读回放快照。
- 当前数据资产证据：2026-06-24 scheduler catch-up + research execution 已让快照表从 4 行增至 8 行；最新 4 条快照覆盖 002297.SZ 博云新材、600769.SH 祥龙电业、301580.SZ 爱迪特、600172.SH 黄河旋风；owner 观察台 4 行 `latest_snapshot_time/updated_at/last_monitor_at` 均推进到 `2026-06-24T09:50:48.617447+00:00`，模型分排序为 15/12/12/0。
- 数据边界：快照只留存当前用户可读输出、模型分、关键依据、风险结论和更新时间；不调用 provider，不读取 raw，不补盘口事实，不生成 official signal，不反写 Day2 watch、post-entry monitor、Day3 或 outcome 阶段表。迟到补偿只能表示“实际捕获时刻的当前投影”，不得解释为原计划槽位的历史实时盘口。
- 允许的只读验收：owner observation-board、observation-monitor snapshots、repository status、Postgres 只读计数、scheduler runtime、research readyz、frontend compact/DOM。
- 解锁条件：快照表结构、快照频率、owner 投影字段优先级、scheduler catch-up 语义、research execution 合同或用户明确批准解锁。

### t-board-relay-service -> post-entry monitor -> observation-board failure asset

- 冻结时间：2026-06-24 Asia/Shanghai。
- 数据资产范围：`decision_t_relay.t_board_post_entry_monitor_v1` 是 Day2 有效触发后至收盘的封板维护 append-only 留存表；`GET /t-board-relay/observation-board` 读取它时优先反映开板失败事实，并更新 `current_conclusion`、`key_reason`、`risk_tip` 和 `latest_snapshot_time`。
- 当前数据资产证据：600172.SH 已通过 post-entry monitor 投影为“触发后开板，停止观察”；observation-board 当前仍只返回 4 条 Day1 合格对象；`latest_snapshot_time` 随后触发监测更新。
- 数据边界：owner projection 只读聚合 `decision_t_relay.*`，不读取 raw/provider，不补缺口，不生成交易、买点、official signal 或前三模型事实；前端只能消费 compact 后的中文结论。
- 解锁条件：post-entry monitor 表结构、观察台优先级、risk_tip 生成口径、scheduler post-entry 频率或用户明确批准解锁。
