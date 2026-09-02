# 模型四：T 字板主导资金博弈研究中心设计文档 v1

> 平台：神策中心  
> 研究中心名称：模型四研究中心 / T 字板主导资金博弈研究中心  
> 对应模型：`t_board_relay`  
> 生产决策域：`decision_t_relay`  
> 研究域：`research_t_relay`  
> 共享动态研究域：`research_dynamic`  
> 文档目标：围绕 T 字板接力模型，建设可复盘、可验证、可沉淀 hard negative、可推动模型进化的独立研究中心。

---

## 0. 文档摘要

模型四研究中心不是交易记录页，也不是简单胜率报表。它要研究的是：

```text
Day1 T 字板是否是真强；
封单额 / 流通市值比例在哪个区间有效；
开板分歧是健康换手还是出货；
Day2 10:30 附近是否从分歧转一致；
“所有买单被吃掉”到底对应哪类盘口事件；
买入后开板失败前是否有预警；
市场上涨加速、涨停比例和大盘资金流是否显著影响接力；
Day3 开盘涨停留下、尾盘没涨停卖出的规则是否有效；
哪些样本属于虚封诱多和 hard negative。
```

研究中心的核心不是“事后解释”，而是把用户关于主导资金博弈的经验转化为可验证、可回放、可量化、可沉淀的研究体系。

---

## 1. 研究中心定位

### 1.1 正式名称

```text
T 字板主导资金博弈研究中心
```

### 1.2 研究边界

研究中心只研究 `t_board_relay` 模型产生的候选、触发、监控、退出和结果标签。

它不直接修改生产模型参数，不直接产生交易指令，不与前三个模型共用研究表。

### 1.3 研究对象

研究对象不是股票代码，而是三日接力样本事件：

```text
Day1 T 字板候选；
Day2 10:30 附近观察样本；
Day2 理论买入触发样本；
Day2 买入后开板失败样本；
Day3 开盘涨停留下样本；
Day3 尾盘未涨停退出样本。
```

---

## 2. 研究中心核心问题

研究中心必须回答以下问题：

```text
1. 什么样的 T 字板次日更容易接力？
2. 封单额 / 流通市值比例是否有效？最佳区间在哪里？
3. 封单比例极高是否反而存在虚封诱多风险？
4. Day1 开板是健康换手还是主导资金出货？
5. Day2 10:30 左右是否真的是最佳观察窗口？
6. Day2 接近涨停是主动推动、板块带动，还是一笔脉冲？
7. “所有买单被吃掉”到底是强信号还是风险信号？
8. 买入后开板失败前，封单、盘口、市场环境是否已有预警？
9. 大环境上涨加速、涨停比例、大盘资金流入是否影响接力成功？
10. Day3 开盘涨停留下是否有效？
11. Day3 尾盘没涨停卖出是否优于继续持有？
12. 哪些样本是 hard negative：看起来极强但实际诱多？
13. 人工复盘标签能否提升模型对虚封诱多和主导资金放弃的识别？
```

---

## 3. 研究样本定义

### 3.1 样本不是股票

研究样本必须绑定事件：

```text
某股票在某 Day1 出现 T 字板；
该样本在 Day2 是否触发；
触发后是否封到收盘；
Day3 是否加速或退出。
```

### 3.2 样本核心主键

```text
t_board_sample_id
```

它应关联：

```text
day1_candidate_id
entry_trigger_id
post_entry_monitor_id
day3_decision_id
outcome_label_id
```

### 3.3 样本来源

```text
day1_qualified
Day2_not_triggered
Day2_triggered
Day2_open_after_entry_failed
Day3_open_limit_hold
Day3_tail_no_limit_exit
research_only
manual_replay
hard_negative
```

### 3.4 样本角色

```text
positive_relay
failed_after_entry
failed_day3
hard_negative_fake_seal
hard_negative_orderbook_fake_strength
market_context_failed
control_group
research_only
manual_review_required
```

---

## 4. 研究中心页面结构

建议前端页面拆成 8 个子页面。

```text
1. 研究总览
2. Day1 T 字板质量研究
3. 封单比例与封板承诺研究
4. Day2 10:30 触发研究
5. 盘口吃单语义研究
6. 买入后封板维护失败研究
7. Day3 去留研究
8. T 字板博弈复盘中心（人工标注页）
```

---

## 5. 页面一：研究总览

### 5.1 页面目标

展示模型四近期整体研究健康度，不展示交易建议。

### 5.2 核心指标

```text
day1_t_board_count
qualified_candidate_count
Day2_near_limit_rate
Day2_entry_trigger_rate
Day2_sealed_to_close_rate
Day2_board_open_after_entry_rate
Day3_open_limit_hold_rate
Day3_tail_exit_rate
strong_success_rate
hard_negative_rate
market_context_weak_block_rate
p0_data_gap_rate
```

### 5.3 趋势图

```text
Day1 合格样本数量趋势
Day2 触发率趋势
Day2 买入后开板失败率趋势
Day3 开盘涨停率趋势
strong_success_rate 趋势
hard_negative_rate 趋势
```

### 5.4 总览页禁止展示

```text
不展示“推荐买入”；
不展示“收益排名”；
不允许把研究结论渲染成交易指令。
```

---

## 6. 页面二：Day1 T 字板质量研究

### 6.1 研究问题

```text
什么样的 T 字板次日更容易接力？
```

### 6.2 研究维度

```text
开板次数
开板时长
第一次开板时间
最后回封时间
回封速度
开板最大回落幅度
开板期间成交额
Day1 换手率
成交额 / 流通市值
封单稳定性
```

### 6.3 研究指标

```text
t_board_next_day_near_limit_rate
Day2_entry_trigger_rate
Day2_sealed_to_close_rate
Day2_board_open_after_entry_rate
Day3_open_limit_rate
strong_success_rate
```

### 6.4 建议研究表

```text
research_t_relay.t_board_day1_quality_analysis_v1
```

字段：

```sql
day1_quality_analysis_id
research_run_id

open_board_count_bucket
open_board_minutes_bucket
reseal_speed_bucket
drawdown_bucket
turnover_bucket

sample_count
Day2_near_limit_rate
Day2_entry_trigger_rate
Day2_sealed_to_close_rate
Day2_board_open_after_entry_rate
Day3_open_limit_rate
strong_success_rate

avg_seal_commitment_score
avg_disagreement_absorption_score
avg_fake_seal_trap_risk_score
confidence_level
created_at
```

### 6.5 研究结论示例

```text
开板次数 1-2 次、回封速度快、开板回落浅的 T 字板，Day2 触发率较高。
开板时间过长且尾盘封单衰减明显的样本，Day2 买入后开板失败率较高。
```

---

## 7. 页面三：封单比例与封板承诺研究

### 7.1 研究问题

```text
封单额 / 流通市值比例是否有效？
比例越高是否越好？
极高封单是否存在虚封诱多风险？
```

### 7.2 分桶设计

```text
very_low
low
medium
high
extreme
```

第一版不硬编码区间，可由配置控制。示例：

```yaml
seal_ratio_buckets:
  very_low: [0, 0.001]
  low: [0.001, 0.003]
  medium: [0.003, 0.008]
  high: [0.008, 0.015]
  extreme: [0.015, null]
```

### 7.3 研究表

```text
research_t_relay.t_board_seal_ratio_effectiveness_v1
```

字段：

```sql
seal_ratio_analysis_id
research_run_id

seal_ratio_type                -- final / max / avg_after_reseal
seal_ratio_bucket
bucket_min_value
bucket_max_value

sample_count
Day2_near_limit_rate
Day2_entry_trigger_rate
Day2_sealed_to_close_rate
Day2_board_open_after_entry_rate
Day3_open_limit_rate
Day3_tail_exit_rate
strong_success_rate
failure_rate

avg_return_after_entry
avg_max_drawdown_after_entry
avg_fake_seal_trap_risk_score
recommended_seal_ratio_range
confidence_level
created_at
```

### 7.4 特别研究点

```text
封单额 / 流通市值比例极高：
  可能代表强一致；
  也可能是虚封、诱导排板、次日不可参与。

因此必须同时看：
  seal_cancel_rate；
  seal_decay_rate；
  Day2 触发后是否开板；
  Day3 是否加速。
```

---

## 8. 页面四：分歧消化研究

### 8.1 研究问题

```text
Day1 T 字板开板是健康换手，还是出货？
```

### 8.2 核心指标

```text
disagreement_absorption_score
```

组成：

```text
开板深度
开板时长
开板成交额
开板换手
回封速度
回封后封单稳定性
```

### 8.3 研究表

```text
research_t_relay.t_board_disagreement_absorption_analysis_v1
```

字段：

```sql
disagreement_analysis_id
research_run_id

absorption_score_bucket
sample_count

Day2_near_limit_rate
Day2_entry_trigger_rate
Day2_sealed_to_close_rate
Day2_board_open_after_entry_rate
Day3_open_limit_rate
strong_success_rate

avg_open_board_count
avg_total_open_board_minutes
avg_reseal_speed_seconds
avg_open_board_drawdown_pct
avg_open_board_turnover_rate

recommended_absorption_rule
confidence_level
created_at
```

### 8.4 研究结论关注

```text
高分歧消化样本是否 Day2 更容易接近涨停？
低分歧消化样本是否更容易买入后开板？
分歧消化分是否比单独的封单比例更有效？
```

---

## 9. 页面五：Day2 10:30 触发研究

### 9.1 研究问题

```text
10:30 左右是否真的是最佳观察窗口？
10:20 是否太早？
10:40 是否太晚？
```

### 9.2 时间分桶

```text
10:00-10:10
10:10-10:20
10:20-10:30
10:30-10:40
10:40-11:00
```

生产第一版严格按 10:20-10:40，但研究中心可以扩展对照窗口。

### 9.3 研究表

```text
research_t_relay.t_board_day2_entry_timing_analysis_v1
```

字段：

```sql
timing_analysis_id
research_run_id

watch_time_bucket
sample_count

near_limit_rate
entry_trigger_rate
sealed_to_close_rate
board_open_after_entry_rate
Day3_open_limit_rate
Day3_tail_exit_rate
strong_success_rate
avg_return_after_entry
avg_max_drawdown_after_entry

best_trigger_time_bucket
confidence_level
created_at
```

### 9.4 关键解释

10:30 不是机械时间点，而是早盘分歧释放后重新选择方向的窗口。

---

## 10. 页面六：Day2 接近涨停质量研究

### 10.1 研究问题

```text
接近涨停是主动推动、板块带动，还是一笔脉冲？
```

### 10.2 分桶

```text
active_push
board_driven
one_pulse
unknown
```

### 10.3 研究表

```text
research_t_relay.t_board_near_limit_quality_analysis_v1
```

字段：

```sql
near_limit_quality_analysis_id
research_run_id

price_push_mode
near_limit_quality_bucket
sample_count

entry_trigger_rate
sealed_to_close_rate
board_open_after_entry_rate
Day3_open_limit_rate
strong_success_rate
failure_rate

avg_near_limit_volume_ratio
avg_stock_vs_board_strength
avg_stock_vs_index_strength
avg_vwap_support_state_score
created_at
```

### 10.4 研究价值

```text
主动推动接近涨停且承接强，可能是真接力。
板块带动接近涨停，需看个股是否强于板块。
一笔脉冲接近涨停，容易出现买入后开板失败。
```

---

## 11. 页面七：盘口吃单语义研究

### 11.1 研究问题

用户规则“所有买单被吃掉”到底应该如何理解？

可能语义：

```text
BID 被主动卖单打掉：偏风险，但若迅速补单并上攻，说明承接强。
ASK 被主动买单扫掉：偏强势，说明主动进攻。
```

### 11.2 研究表

```text
research_t_relay.t_board_order_consumption_analysis_v1
```

字段：

```sql
order_consumption_analysis_id
research_run_id

order_consumption_side          -- BID / ASK / UNKNOWN
consumption_interpretation      -- bullish / bearish / mixed / unknown
consumption_strength_bucket     -- weak / medium / strong / extreme

sample_count
entry_trigger_rate
sealed_to_close_rate
board_open_after_entry_rate
Day3_open_limit_rate
Day3_tail_exit_rate
strong_success_rate
failure_rate

avg_consumption_amount
avg_consumption_speed
avg_bid_replenish_speed_after_consumed
avg_ask_absorption_speed_near_limit
recommended_consumption_rule
confidence_level
created_at
```

### 11.3 研究重点

```text
BID 被打掉后快速补单，是否比 ASK 被扫掉更有效？
ASK 被扫掉但随后无法封板，是否是假强？
强吃单之后买入后开板率是否下降？
```

这张表是模型四最重要的研究表之一。

---

## 12. 页面八：买入后封板维护失败研究

### 12.1 研究问题

```text
买入后开板失败之前，有没有盘口和市场预警？
```

### 12.2 研究表

```text
research_t_relay.t_board_post_entry_failure_analysis_v1
```

字段：

```sql
post_entry_failure_id
research_run_id

sample_count
board_open_after_entry_count
board_open_after_entry_rate

avg_time_from_entry_to_board_open_seconds
avg_board_open_count_after_entry
avg_max_drawdown_after_entry
avg_control_failure_score

avg_seal_commitment_score
avg_relay_consensus_score
avg_fake_seal_trap_risk_score
avg_market_context_score

common_failure_context_json
primary_failure_reason
recommended_negative_rule
created_at
```

### 12.3 失败归因枚举

```text
seal_commitment_weak
fake_seal_trap
orderbook_fake_strength
market_context_turned_weak
sell_pressure_not_absorbed
high_open_low_walk
liquidity_gap
data_gap
```

### 12.4 硬规则

即使买入后开板又重新封住，生产结果仍然按失败处理。研究中心可以分析这类样本是否有例外价值，但不得改变第一版规则。

---

## 13. 页面九：市场环境研究

### 13.1 研究问题

```text
上涨加速、涨停比例、大盘资金流入是否影响接力成功？
弱环境下是否应该禁止 official trigger？
```

### 13.2 研究表

```text
research_t_relay.t_board_market_context_analysis_v1
```

字段：

```sql
market_context_analysis_id
research_run_id

market_context_bucket           -- supportive / neutral / weak / data_degraded
sample_count

entry_trigger_rate
sealed_to_close_rate
board_open_after_entry_rate
Day3_open_limit_rate
failure_rate
strong_success_rate

avg_market_acceleration
avg_limit_up_ratio
avg_market_net_moneyflow
avg_market_large_order_net_flow

market_context_lift_score
recommended_market_gate_action  -- keep / tighten / loosen / research_only
confidence_level
created_at
```

### 13.3 重点指标

```text
market_return_acceleration_1030
limit_up_ratio_1030
market_net_moneyflow_1030
limit_down_ratio_1030
market_breadth_up_ratio_1030
```

---

## 14. 页面十：Day3 去留研究

### 14.1 研究问题

```text
Day3 开盘涨停留下是否有效？
Day3 尾盘未涨停卖出是否优于继续持有？
```

### 14.2 研究表

```text
research_t_relay.t_board_day3_exit_analysis_v1
```

字段：

```sql
day3_exit_analysis_id
research_run_id

sample_count
Day3_open_limit_count
Day3_open_limit_rate
Day3_tail_no_limit_exit_count
Day3_tail_no_limit_exit_rate

hold_success_rate
tail_exit_avoid_loss_rate
avg_return_if_hold
avg_return_if_tail_exit
avg_drawdown_if_hold_after_tail_no_limit

recommended_exit_rule
confidence_level
created_at
```

### 14.3 对照研究

```text
按规则尾盘卖出 vs 假设继续持有到次日；
开盘涨停留下 vs 开盘未涨停但午后涨停；
尾盘未涨停卖出是否显著减少回撤。
```

---

## 15. 页面十一：虚封诱多与 hard negative 研究

### 15.1 研究问题

```text
什么样的 T 字板看起来极强，实际是诱多？
```

### 15.2 hard negative 类型

```text
fake_seal_trap
orderbook_fake_strength
high_open_low_walk
sell_pressure_not_absorbed
post_entry_control_failed
market_context_fake_support
extreme_seal_ratio_failed
```

### 15.3 研究表

```text
research_t_relay.t_board_hard_negative_analysis_v1
```

字段：

```sql
hard_negative_id
research_run_id

hard_negative_type
sample_count

avg_seal_commitment_score
avg_disagreement_absorption_score
avg_relay_consensus_score
avg_fake_seal_trap_risk_score
avg_control_failure_score

common_path_json
distinguishing_features_json
recommended_negative_rule
confidence_level
created_at
```

### 15.4 研究目标

把“看起来像真强”的失败样本沉淀为 hard negative，反向减少模型四后续误判。

---

## 16. T 字板博弈复盘中心

模型四必须有人工作业页面，用于复盘主导资金博弈行为。

### 16.1 页面名称

```text
T 字板博弈复盘中心
```

### 16.2 页面展示

```text
Day1 分时图；
Day1 开板 / 回封标记；
Day1 封单额曲线；
Day1 撤单曲线；
Day2 10:30 附近盘口回放；
Day2 接近涨停过程；
Day2 吃单事件；
Day2 理论买入点；
Day2 买入后是否开板；
Day3 开盘状态；
Day3 尾盘状态；
市场涨停比例；
大盘资金流；
研究中心自动归因。
```

### 16.3 页面模式

```text
as_of 模式：
  只看到当时可见数据，防止未来函数。

outcome_review 模式：
  可以看到 Day2 收盘、Day3 去留和后续结果，用于归因。
```

---

## 17. 人工打标体系

### 17.1 主导资金意图标签

```text
TRUE_RELAY_INTENT              -- 真接力意图
HEALTHY_WASH                   -- 健康洗盘
WASH_AND_RESEAL                -- 洗盘回封
WEAK_RESEAL                    -- 弱回封
DISTRIBUTION_SUSPECTED         -- 出货嫌疑
ABANDON_AFTER_ENTRY            -- 买入后放弃维护
UNKNOWN_INTENT                 -- 无法判断
```

### 17.2 封单行为标签

```text
SEAL_COMMITMENT_STRONG         -- 封板承诺强
SEAL_COMMITMENT_WEAK           -- 封板承诺弱
SEAL_DECAY_FAST                -- 封单衰减快
HIGH_CANCEL_RISK               -- 撤单风险高
FAKE_SEAL_TRAP                 -- 虚封诱多
```

### 17.3 分歧消化标签

```text
DISAGREEMENT_ABSORBED          -- 分歧被消化
SELL_PRESSURE_HEAVY            -- 卖压较重
SELL_PRESSURE_NOT_ABSORBED     -- 卖压未消化
OPEN_BOARD_HEALTHY             -- 开板健康
OPEN_BOARD_DANGEROUS           -- 开板危险
```

### 17.4 盘口吃单标签

```text
BID_CONSUMED_REPLENISHED       -- 买单被打掉后快速补单
BID_CONSUMED_NOT_REPLENISHED   -- 买单被打掉后未补单
ASK_SWEPT_STRONG               -- 卖单被主动扫掉
ASK_SWEPT_NO_FOLLOW            -- 卖单被扫但无后续
ORDERBOOK_FAKE_STRENGTH        -- 盘口假强
```

### 17.5 Day2 结果标签

```text
SEALED_TO_CLOSE_AFTER_ENTRY    -- 买入后封到收盘
OPENED_AFTER_ENTRY_FAILED      -- 买入后开板失败
WEAK_SEAL_TO_CLOSE             -- 勉强封住
DATA_BLOCKED                   -- 数据不足
```

### 17.6 Day3 去留标签

```text
DAY3_ACCELERATION_SUCCESS      -- 第三天加速成功
DAY3_OPEN_LIMIT_HOLD_VALID     -- 开盘涨停留下有效
DAY3_RELAY_FAILED              -- 第三天接力失败
TAIL_EXIT_VALID                -- 尾盘退出有效
TAIL_EXIT_TOO_EARLY            -- 尾盘退出偏早，研究标签
```

### 17.7 样本角色标签

```text
POSITIVE_RELAY_PROTOTYPE
HARD_NEGATIVE_FAKE_SEAL
HARD_NEGATIVE_ORDERBOOK_FAKE
HARD_NEGATIVE_CONTROL_FAILED
MARKET_CONTEXT_FAILED_SAMPLE
CONTROL_GROUP
RESEARCH_ONLY
NEEDS_REVIEW
```

---

## 18. 人工标注库表

### 18.1 复盘样本表

```text
research_t_relay.t_board_replay_case_v1
```

字段：

```sql
replay_case_id
canonical_symbol
stock_name

day1_candidate_id
entry_trigger_id
post_entry_monitor_id
day3_decision_id
outcome_label_id

day1_trade_date
day2_trade_date
day3_trade_date

case_source                  -- triggered / failed / hard_negative / manual / control
case_status                  -- pending_labeling / labeled / review_required / approved

source_data_version
dynamic_feature_run_id
created_at
updated_at
```

### 18.2 人工标注主表

```text
research_t_relay.t_board_manual_label_v1
```

字段：

```sql
manual_label_id
replay_case_id
labeler_id
labeler_role
label_mode                   -- as_of / outcome_review

dominant_capital_intent_label
seal_behavior_label
disagreement_label
orderbook_behavior_label
day2_result_label
day3_result_label
sample_role_label

manual_confidence            -- high / medium / low
manual_note
label_version
created_at
```

### 18.3 多选标签明细表

```text
research_t_relay.t_board_manual_label_tag_v1
```

字段：

```sql
manual_label_tag_id
manual_label_id
tag_group                    -- capital_intent / seal / disagreement / orderbook / day2 / day3 / sample_role
tag_code
tag_value
tag_note
created_at
```

### 18.4 标注复核表

```text
research_t_relay.t_board_label_review_v1
```

字段：

```sql
review_id
replay_case_id
manual_label_id
reviewer_id

review_status                -- approved / rejected / needs_discussion
review_comment
final_sample_role_label
final_outcome_label
final_confidence
created_at
```

---

## 19. 研究运行表

### 19.1 研究 run 表

```text
research_t_relay.t_board_research_run_v1
```

字段：

```sql
research_run_id
research_type                 -- day1_quality / seal_ratio / disagreement / timing / order_consumption / market_context / post_entry_failure / day3_exit / hard_negative / manual_label
research_name
model_code                    -- t_board_relay
model_version
feature_version
rule_version
source_data_version

sample_start_date
sample_end_date
evaluation_window
as_of_time_policy             -- production_snapshot / research_replay / mixed

status                        -- created / running / succeeded / failed / data_blocked
created_by
created_at
started_at
finished_at
comment
```

### 19.2 样本表

```text
research_t_relay.t_board_research_sample_v1
```

字段：

```sql
research_sample_id
research_run_id
sample_origin                 -- day1_qualified / day2_triggered / failed_after_entry / day3_exit / hard_negative / control
sample_role                   -- positive / negative / hard_negative / control / research_only

day1_candidate_id
entry_trigger_id
post_entry_monitor_id
day3_decision_id
outcome_label_id

canonical_symbol
day1_trade_date
day2_trade_date
day3_trade_date

outcome_label
model_version
feature_version
rule_version
source_data_version
data_quality_status
created_at
```

---

## 20. 研究发现表

```text
research_t_relay.t_board_research_finding_v1
```

字段：

```sql
finding_id
research_run_id
finding_type                  -- rule_effective / rule_ineffective / hard_negative_found / gap_material / market_gate_needed / manual_review_needed
finding_title
finding_summary

sample_count
evidence_level                -- weak / medium / strong
confidence_level

related_feature_name
related_rule_code
recommended_action            -- keep / tighten / loosen / add_negative_rule / research_only / manual_review
production_change_allowed
manual_review_required

evidence_json
created_at
```

### 20.1 finding_type 建议枚举

```text
seal_ratio_effective
seal_ratio_extreme_risk
Day2_1030_window_effective
Day2_1030_window_unstable
order_consumption_bullish
order_consumption_bearish
order_consumption_ambiguous
post_entry_open_failure_warning
market_context_material
Day3_exit_rule_effective
fake_seal_hard_negative
orderbook_fake_strength_hard_negative
data_gap_material
```

---

## 21. 模型进化指标表

用于研究中心总览或四模型总览读取。

```text
research_t_relay.t_board_model_evolution_metric_v1
```

字段：

```sql
metric_id
metric_date
model_code                    -- t_board_relay
model_version
feature_version
rule_version
source_data_version

sample_count_20d
sample_count_60d
Day2_entry_trigger_rate_20d
Day2_sealed_to_close_rate_20d
Day2_board_open_after_entry_rate_20d
Day3_open_limit_rate_20d
Day3_tail_exit_rate_20d
strong_success_rate_20d
hard_negative_rate_20d

seal_ratio_effective_score_20d
order_consumption_validity_score_20d
market_context_lift_score_20d
Day3_exit_rule_effectiveness_20d

p0_coverage_rate
p1_coverage_rate
dynamic_replay_consistency_rate
model_health_status
confidence_level
created_at
```

---

## 22. 与 research_dynamic 的关系

模型四强依赖动态特征，因此研究中心必须读取 `research_dynamic` 中的共享研究结论。

相关表：

```text
research_dynamic.dynamic_feature_lift_analysis_v1
research_dynamic.dynamic_feature_bucket_effectiveness_v1
research_dynamic.dynamic_rerank_regret_v1
research_dynamic.dynamic_feature_replay_consistency_v1
research_dynamic.dynamic_feature_gap_impact_v1
```

模型四重点关联动态特征：

```text
near_limit_order_absorption_score
order_consumption_side
market_return_acceleration_1030
limit_up_ratio_1030
market_net_moneyflow_1030
post_entry_board_opened
day3_open_limit_up_flag
day3_tail_limit_up_flag
```

研究原则：

```text
动态特征没有通过分桶单调性、增量 lift 和 replay 一致性验证，不得进入生产规则。
```

---

## 23. 研究 API 设计

```text
GET  /research/t-board/healthz
GET  /research/t-board/readyz

POST /research/t-board/runs
GET  /research/t-board/runs/{research_run_id}
POST /research/t-board/runs/{research_run_id}/execute

POST /research/t-board/day1-quality/analyze
POST /research/t-board/seal-ratio/analyze
POST /research/t-board/disagreement/analyze
POST /research/t-board/day2-timing/analyze
POST /research/t-board/near-limit-quality/analyze
POST /research/t-board/order-consumption/analyze
POST /research/t-board/market-context/analyze
POST /research/t-board/post-entry-failure/analyze
POST /research/t-board/day3-exit/analyze
POST /research/t-board/hard-negative/analyze

GET  /research/t-board/samples
GET  /research/t-board/findings
GET  /research/t-board/manual-labels
GET  /research/t-board/evolution-metrics
```

---

## 24. 前端交互设计

### 24.1 研究总览卡片

```text
Day1 T 字板数量
合格候选数量
Day2 触发率
Day2 买入后开板失败率
Day3 开盘涨停率
Day3 尾盘退出率
hard negative 数量
P0 数据覆盖率
```

### 24.2 复盘页图层

```text
价格分时
成交量
封单额曲线
撤单曲线
盘口吃单事件
理论买入点
买入后开板标记
Day3 开盘 / 尾盘标记
大盘上涨加速曲线
涨停比例曲线
大盘资金流曲线
```

### 24.3 筛选器

```text
日期区间
Day1 seal_ratio_bucket
Day1 capital_intent_hypothesis
Day2 trigger_status
order_consumption_side
post_entry_status
Day3 action
outcome_label
manual_label_status
hard_negative_type
```

---

## 25. 研究结论进入生产的门槛

任何研究结论要进入生产规则，必须满足：

```text
1. sample_count 达到最低样本要求；
2. 分桶结果具备稳定性；
3. 单调性或显著分层成立；
4. production snapshot 与 research replay 一致性通过；
5. 不是未来函数；
6. 人工复核通过；
7. 形成 rule_version 变更记录。
```

---

## 26. 验收标准

模型四研究中心第一版必须能回答：

```text
1. Day1 T 字板样本中，哪些封单比例区间 Day2 成功率更高？
2. 封单比例极高是否更容易形成 hard negative？
3. 开板次数和开板时长是否影响 Day2 触发率？
4. Day2 10:30 窗口是否优于其他时间窗口？
5. “所有买单被吃掉”在盘口上到底对应 BID 还是 ASK？哪一种更有效？
6. 买入后开板失败之前，是否有封单衰减、撤单、市场走弱等预警？
7. 弱市场环境下 Day2 触发是否高失败？
8. Day3 开盘涨停留下是否提升结果？
9. Day3 尾盘未涨停卖出是否避免后续回撤？
10. 人工标注的虚封诱多样本是否能进入 hard negative 库？
```

---

## 27. AGENTS / Codex 研究硬规则

```text
1. research_t_relay 不得直接调用外部 provider。
2. 研究样本必须绑定 day1_candidate_id 或 entry_trigger_id。
3. 研究必须区分 production_snapshot 和 research_replay。
4. 盘口吃单必须保留原始口径和标准化方向。
5. 买入后开板必须作为硬失败，不得因后续回封改写生产结果。
6. Day3 尾盘未涨停必须生成退出研究事件。
7. 人工“主导资金意图”标签只能作为研究标签，不得作为事实。
8. hard negative 样本必须独立沉淀。
9. 研究结论不得直接改生产参数，必须进入人工审核和 rule_version 变更。
10. 所有动态特征必须校验 replay 一致性。
```

---

## 28. 最终结论

模型四研究中心的核心价值是：

```text
把用户关于 T 字板与主导资金博弈的经验规则，转化为可验证、可回放、可复盘、可进化的研究体系。
```

它不是为了简单看胜率，而是为了回答：

```text
什么是真强 T 字板；
什么是虚封诱多；
盘口吃单到底如何解释；
买入后开板失败能否提前预警；
第三天不加速退出是否严格有效；
哪些规则应该进入下一版模型。
```

这套研究中心必须和 `dynamic-feature-service`、`decision_t_relay`、人工复盘标签体系共同建设，才能支撑模型四长期进化。
