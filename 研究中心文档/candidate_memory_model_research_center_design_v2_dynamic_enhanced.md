# 神策中心研究中心 V2：动态特征增强版设计说明

> 本文档是在原三大模型研究中心 V1 设计基础上的增强版。核心变化是引入 `dynamic-feature-service` 后，研究中心从“日级模型效果研究”升级为“日级结构 + 盘中行为 + 可交易性 + 动态增益验证”的完整研究系统。

## V2 全局设计原则

1. `source-data-service` 继续负责事实数据采集、标准化、质量、血缘、缺口、修复，不被研究中心和动态特征服务绕过。
2. `dynamic-feature-service` 只产出动态特征事实，不产出模型决策，不抓外部 provider，不模拟缺失分钟线。
3. 三大模型研究中心保留各自独立研究域，不混合样本、不混合标签、不混合结果验证。
4. 新增 `research_dynamic` 共享研究域，用于跨模型验证动态特征是否具备增量价值、单调性、稳定性、可回放一致性。
5. 所有动态研究必须区分 `production_snapshot` 与 `research_replay`，并记录 `as_of_time`、`feature_bundle_code`、`feature_set_version`、`formula_version`、`source_lineage_id`。
6. 动态特征不得直接进入生产公式，必须通过分桶单调性、增量 lift、同批次重排验证、样本量置信度、人工审核后，才能进入生产候选。
7. 总览页未来只展示模型级进化与动态特征贡献趋势，不展示个股、分时图、具体研究样本。

---

# 候选记忆模型研究中心 V2 动态增强版

# 候选记忆模型研究中心设计文档 v1

> 适用平台：神策中心  
> 适用模型：模型二 `candidate_memory` / 候选记忆模型  
> 文档定位：后续 Codex 落 MD / SQL / 服务代码的设计依据  
> 设计原则：研究中心只读 `source-data-service` 的 source 标准事实表与模型生产快照，不直接调用任何外部 provider，不直接修改生产模型参数。

---

## 1. 研究中心定位

候选记忆模型研究中心不是研究“今天推荐涨没涨”，而是研究：

```text
1. 热点模型或其他候选源流出的历史候选，是否仍有后续价值？
2. 首次短窗口失败后，哪些样本会迟到兑现？
3. 二波启动前有什么稳定前兆？
4. 重新激活信号是否过早、过晚，还是刚好？
5. 失败样本到底是彻底失败，还是仍在结构修复中？
6. 历史候选记忆池有没有帮助系统减少漏选？
7. 新 signal_id 是否清晰表达了“重新激活”，而不是复用旧信号？
```

一句话定位：

```text
候选记忆模型研究中心 = 历史候选生命周期、迟到兑现、二波启动、重新激活时机与记忆价值研究中心。
```

---

## 2. 模型二和热点模型的根本区别

热点模型研究对象：

```text
teacher prior batch -> 短窗口 T+1/T+3/T+5 兑现
```

候选记忆模型研究对象：

```text
历史 candidate / old signal
-> memory_entity
-> 持续观察
-> 结构修复 / 资金回流 / 板块再共振
-> 重新激活 new_signal_id
-> 中窗口兑现
```

因此模型二必须同时维护两条时间线。

### 2.1 首次信号时间线

```text
first_signal_date
first_observation_window
first_outcome_label
exit_hot_window_date
enter_memory_pool_date
```

用于研究：

```text
首次为什么失败？
失败后是否还有价值？
多久后开始修复？
```

### 2.2 重新激活时间线

```text
reactivation_candidate_date
reactivation_signal_date
new_signal_id
reactivation_observation_window
reactivation_outcome_label
```

用于研究：

```text
重新激活是否有效？
重新激活是否过早或过晚？
新信号是否比旧信号更有研究价值？
```

两条时间线不能混，否则模型二会退化成模型一的延长版。

---

## 3. 硬性规则：每次正式激活必须生成新的 signal_id

模型二最重要的生产和研究规则：

```text
首次入选信号 first_signal_id 不能被复用为后续激活信号。
```

正确关系：

```text
memory_entity_id
  ├── first_signal_id
  ├── observation_records
  ├── reactivation_candidate_id
  └── new_signal_id
```

模型二研究中心必须能回答：

```text
这个新信号来自哪个历史候选？
旧信号当时为什么失败？
重新激活时哪些证据发生了变化？
新信号发布后是否比旧信号更有效？
```

如果系统复用旧 `signal_id`，就无法研究二波启动和重新激活价值。

---

## 4. 模型二全链路数据结构

候选记忆模型研究中心的数据链路建议如下：

```text
source.daily_bar_v1
source.adjusted_daily_bar_v1
source.weekly_bar_v1
source.trade_status_v1
source.limit_price_v1
source.index_daily_bar_v1
source.market_breadth_v1
source.stock_board_membership_v1
source.board_daily_bar_v1
source.stock_moneyflow_daily_v1
source.event_news_v1
        ↓
decision_hot.hot_official_signal_v1
decision_hot.hot_outcome_label_v1
decision_hot.hot_observation_path_v1
        ↓
decision_memory.memory_entity_v1
decision_memory.memory_observation_path_v1
decision_memory.memory_state_transition_v1
decision_memory.memory_reactivation_candidate_v1
decision_memory.memory_release_gate_audit_v1
decision_memory.memory_official_signal_v1
decision_memory.memory_outcome_label_v1
        ↓
research_memory.memory_research_run_v1
research_memory.memory_research_sample_v1
research_memory.memory_lifecycle_analysis_v1
research_memory.memory_delayed_success_analysis_v1
research_memory.memory_reactivation_timing_analysis_v1
research_memory.memory_second_wave_analysis_v1
research_memory.memory_failure_attribution_v1
research_memory.memory_missed_reactivation_v1
research_memory.memory_model_evolution_metric_v1
```

研究中心只读：

```text
1. source 标准事实表；
2. decision_hot 历史候选 / 历史信号；
3. decision_memory 生产快照；
4. source coverage / freshness / lineage。
```

研究中心不直接读 raw 接口表，也不直接调用 provider。

---

## 5. Source 字段依赖设计

以下字段可作为后续 Codex 实现时的字段契约。真实库表字段不同，也可以按注释映射。

### 5.1 历史行情字段

来源：

```text
source.daily_bar_v1
source.adjusted_daily_bar_v1
source.weekly_bar_v1
```

字段建议：

```sql
canonical_symbol              -- 统一股票代码，例如 000759.SZ
trade_date                    -- 交易日

open_price                    -- 未复权开盘价，用于可交易评估
high_price                    -- 未复权最高价，用于结果路径
low_price                     -- 未复权最低价，用于回撤和支撑破位判断
close_price                   -- 未复权收盘价
pre_close_price               -- 昨收价
volume                        -- 成交量
amount                        -- 成交额
turnover_rate                 -- 换手率
pct_chg                       -- 当日涨跌幅

adjustment_mode               -- qfq/hfq/raw，结构研究建议使用 qfq
adjusted_close                -- 前复权收盘价，用于长期观察和结构修复
weekly_close                  -- 周线收盘价，占位字段，后续由 daily 聚合或 source.weekly_bar_v1 提供
weekly_volume                 -- 周线成交量，占位字段

source_quality_status         -- passed/degraded/suspect
source_build_batch_id
lineage_id
```

模型二用途：

```text
1. 追踪首次信号失败后的价格路径；
2. 识别结构是否修复；
3. 识别二波启动前的量价变化；
4. 计算 T+10/T+20/T+40/T+60 的迟到兑现。
```

### 5.2 交易状态字段

来源：

```text
source.trade_status_v1
source.limit_price_v1
source.limit_event_v1
```

字段建议：

```sql
canonical_symbol
trade_date
is_tradable                   -- 是否可交易
is_suspended                  -- 是否停牌
is_st                         -- 是否 ST
is_delisting_risk             -- 是否退市风险
security_type                 -- 股票/ETF/指数/其他

up_limit_price
down_limit_price
is_limit_up
is_limit_down
is_one_word_limit
tradability_state             -- tradable/unfriendly/blocked/unknown
```

模型二用途：

```text
1. 过滤不可继续观察的样本；
2. 避免把停牌、ST、退市风险导致的失败归因为模型失败；
3. 判断重新激活信号是否具备可交易性。
```

### 5.3 市场环境字段

来源：

```text
source.index_daily_bar_v1
source.market_breadth_v1
source.market_regime_v1
```

字段建议：

```sql
trade_date
index_code
index_pct_chg
index_return_3d
index_return_5d
index_return_20d

market_up_count
market_down_count
limit_up_count
limit_down_count
market_breadth_up_ratio
risk_appetite_score            -- 市场风险偏好分，占位字段
market_regime                  -- strong/weak/choppy/risk_off/unknown
```

模型二用途：

```text
1. 判断首次失败是否由市场环境拖累；
2. 判断重新激活是否发生在市场环境改善阶段；
3. 研究不同市场环境下 memory 重新激活的有效性。
```

### 5.4 板块字段

来源：

```text
source.stock_board_membership_v1
source.board_daily_bar_v1
```

字段建议：

```sql
canonical_symbol
trade_date
board_code
board_name
board_type                    -- industry/concept/theme
membership_time_mode          -- historical/current_snapshot

board_return_1d
board_return_3d
board_return_5d
board_return_20d
board_rank_percentile
board_up_member_ratio
board_limit_up_count
stock_vs_board_relative_strength
```

模型二用途：

```text
1. 判断历史候选是否重新获得板块共振；
2. 判断二波启动是否来自板块再扩散；
3. 研究板块强弱变化是否领先于重新激活。
```

### 5.5 资金流字段

来源：

```text
source.stock_moneyflow_daily_v1
source.stock_moneyflow_snapshot_v1
```

字段建议：

```sql
canonical_symbol
trade_date
moneyflow_provider
net_moneyflow_amount
large_order_net_flow           -- 大单/超大单净流入，占位字段
moneyflow_rank_percentile
moneyflow_continuity_3d
moneyflow_continuity_5d
moneyflow_reversal_flag
moneyflow_quality_status
```

模型二用途：

```text
1. 研究失败样本后续是否有资金重新流入；
2. 判断重新激活前是否存在资金回流；
3. 识别资金先行但价格未动的记忆候选。
```

资金流建议 P1，不作为第一版 P0 阻断项，但缺失要降低研究置信度。

### 5.6 新闻公告字段

来源：

```text
source.event_news_v1
source.announcement_event_v1
```

字段建议：

```sql
canonical_symbol
event_id
event_date
published_at
available_at
event_type                    -- announcement/news/inquiry/earnings/other
event_sentiment               -- positive/neutral/negative/unknown，占位字段
event_risk_level              -- low/medium/high/unknown
event_title
event_summary
event_source
event_url
```

模型二用途：

```text
1. 判断失败是否由突发负面事件导致；
2. 判断重新激活是否由公告、业绩、事件驱动；
3. 避免使用未来公告解释过去信号。
```

---

## 6. decision_memory 生产层设计

模型二研究中心必须依赖模型二生产快照，而不能只从行情表反推。

### 6.1 记忆实体表

```text
decision_memory.memory_entity_v1
```

字段建议：

```sql
memory_entity_id
canonical_symbol

origin_model_code              -- hot_candidates / manual_candidate / other_model，占位字段
origin_signal_id               -- 初始来源信号 ID
first_signal_date
first_signal_rank
first_signal_score

first_outcome_label            -- 首次信号结果，例如 short_window_failed / late_success / data_blocked
enter_memory_pool_date         -- 进入记忆池日期
enter_memory_reason            -- hot_window_expired / short_window_failed / delayed_watch_required

memory_status                  -- active/watching/reactivated/expired/invalidated/archived
max_observation_end_date
latest_observation_date

model_version
source_data_version
created_at
updated_at
```

说明：

```text
memory_entity_id 是模型二研究的核心对象；
一个 memory_entity 可以对应多个 observation，也可以产生多个新的 reactivation signal。
```

### 6.2 记忆观察路径表

```text
decision_memory.memory_observation_path_v1
```

字段建议：

```sql
observation_id
memory_entity_id
canonical_symbol
trade_date

days_since_first_signal        -- 距首次信号天数
days_since_enter_memory        -- 距进入记忆池天数

open_price
high_price
low_price
close_price
volume
amount
turnover_rate

return_since_first_signal
return_since_enter_memory
max_return_since_enter_memory
max_drawdown_since_enter_memory

structure_state                -- decaying/repairing/compressing/breaking_out/invalidated/unknown
moneyflow_state                -- inflow/outflow/reversal/unknown
board_state                    -- strong/weak/recovering/unknown
market_regime

tradability_state
data_quality_status
created_at
```

说明：

```text
这是研究“失败样本是否在修复”的基础表。
```

### 6.3 记忆状态转移表

```text
decision_memory.memory_state_transition_v1
```

字段建议：

```sql
transition_id
memory_entity_id
canonical_symbol
transition_date

from_state                     -- watching / repairing / compressing / reactivation_candidate / reactivated / invalidated
to_state
transition_reason_code         -- structure_repair / moneyflow_reentry / board_resonance / price_breakout / support_broken / max_window_expired
transition_evidence_json

triggered_by_job_id            -- 调度任务 ID，占位字段
model_version
created_at
```

说明：

```text
模型二必须能解释一个历史候选为什么从观察池变成重新激活候选。
```

### 6.4 重新激活候选表

```text
decision_memory.memory_reactivation_candidate_v1
```

字段建议：

```sql
reactivation_candidate_id
memory_entity_id
origin_signal_id
canonical_symbol
candidate_date

reactivation_reason            -- second_wave_setup / delayed_success_near / moneyflow_reentry / board_resonance / structure_repair
reactivation_score             -- 重新激活候选分，占位字段
structure_repair_score
moneyflow_reentry_score
board_resonance_score
market_support_score
risk_penalty_score
data_gap_penalty_score

source_coverage_snapshot_id
source_freshness_snapshot_id
data_quality_status

candidate_status               -- pending/rejected/promoted_to_signal
created_at
```

说明：

```text
这是 new_signal_id 之前的候选阶段；
不是所有 reactivation_candidate 都能成为 official signal。
```

### 6.5 release gate 审计表

```text
decision_memory.memory_release_gate_audit_v1
```

字段建议：

```sql
gate_audit_id
reactivation_candidate_id
memory_entity_id
canonical_symbol
candidate_date

gate_name                      -- data_preflight/tradable/non_st/structure_repair/market_support/risk_event/max_observation
gate_result                    -- pass/fail/warn
blocking_level                 -- P0/P1/P2
gate_reason_code
gate_reason_text
evidence_json
created_at
```

说明：

```text
研究中心要分析 release gate 是否过严或过松；
尤其要研究被挡掉的 reactivation_candidate 后续是否成功。
```

### 6.6 模型二正式信号表

```text
decision_memory.memory_official_signal_v1
```

字段建议：

```sql
signal_id                      -- 新 signal_id，绝不能复用 origin_signal_id
memory_entity_id
origin_signal_id
reactivation_candidate_id

canonical_symbol
signal_date
decision_time

reactivation_score
final_rank                     -- 如果当天多个 memory 信号，保存排序
release_gate_status

model_version
feature_version
score_formula_version
release_gate_version
source_data_version

source_coverage_snapshot_id
source_freshness_snapshot_id
data_quality_status

signal_status                  -- official/research_only/blocked
created_at
```

硬规则：

```text
signal_id != origin_signal_id
```

Codex 后续必须加校验。

### 6.7 结果标签表

```text
decision_memory.memory_outcome_label_v1
```

字段建议：

```sql
outcome_label_id
signal_id
memory_entity_id
origin_signal_id
canonical_symbol
signal_date

evaluation_window              -- T10/T20/T40/T60
window_start_date
window_end_date

benchmark_buy_price
benchmark_buy_price_method

max_return
close_return
max_drawdown
hit_target
target_return_threshold
hit_target_date
days_to_hit

second_wave_confirmed          -- 是否确认二波启动
delayed_success_confirmed      -- 是否确认迟到兑现
reactivation_timing_label      -- too_early / on_time / too_late / false_reactivation

outcome_label                  -- reactivation_success / delayed_success / second_wave_success / false_reactivation / memory_failed / structure_invalidated
label_reason
label_version
created_at
```

说明：

```text
模型二不应该用模型一的 T+5 成功标签；
它必须用更长窗口和二波/迟到兑现标签。
```

---

## 7. research_memory 研究表设计

### 7.1 研究任务表

```text
research_memory.memory_research_run_v1
```

字段建议：

```sql
research_run_id
research_type                  -- lifecycle/delayed_success/reactivation_timing/second_wave/failure_attribution/missed_reactivation
research_name

model_code                     -- candidate_memory
model_version
feature_version
score_formula_version
release_gate_version
source_data_version

sample_start_date
sample_end_date
evaluation_window              -- T10/T20/T40/T60
status                         -- created/running/succeeded/failed/data_blocked
created_by
created_at
started_at
finished_at
comment
```

### 7.2 研究样本表

```text
research_memory.memory_research_sample_v1
```

字段建议：

```sql
research_sample_id
research_run_id

sample_origin                  -- memory_entity / official_signal / release_gate_rejected / missed_reactivation / control_group
sample_role                    -- delayed_success / second_wave_success / false_reactivation / hard_negative / persistent_failure / control_group

memory_entity_id
origin_signal_id
new_signal_id                  -- 如果已经重新激活，则填写
reactivation_candidate_id

canonical_symbol
first_signal_date
enter_memory_pool_date
reactivation_signal_date

first_outcome_label
memory_status
reactivation_outcome_label

model_version
source_data_version
source_coverage_snapshot_id
source_freshness_snapshot_id
source_quality_status

created_at
```

说明：

```text
模型二研究样本必须能同时看到旧信号和新信号；
否则无法研究“记忆是否带来价值”。
```

### 7.3 生命周期研究表

```text
research_memory.memory_lifecycle_analysis_v1
```

字段建议：

```sql
lifecycle_analysis_id
research_run_id

memory_age_bucket              -- 0_5d / 6_10d / 11_20d / 21_40d / 41_60d / 60d_plus
sample_count

reactivated_count
reactivation_rate
delayed_success_count
delayed_success_rate
expired_count
invalidated_count

avg_days_to_reactivation
avg_days_to_success
avg_max_drawdown_before_reactivation

best_lifecycle_window          -- 占位字段，表示最佳观察窗口
confidence_level
created_at
```

研究问题：

```text
历史候选进入记忆池后，多久最容易重新激活？
最大观察期应该设为多少？
观察太久是否只是在浪费资源？
```

### 7.4 迟到成功研究表

```text
research_memory.memory_delayed_success_analysis_v1
```

字段建议：

```sql
delayed_success_analysis_id
research_run_id

first_outcome_bucket           -- short_window_failed / data_degraded / hot_window_expired
delay_window                   -- T10/T20/T40/T60

sample_count
delayed_success_count
delayed_success_rate

avg_days_to_delayed_success
median_days_to_delayed_success
avg_return_before_success
avg_drawdown_before_success

pre_success_structure_state    -- repairing/compressing/breaking_out/unknown
pre_success_moneyflow_state
pre_success_board_state
market_regime

confidence_level
created_at
```

研究问题：

```text
首次短窗口失败后，有多少是真失败，有多少是迟到成功？
迟到成功前通常出现什么结构、资金、板块特征？
```

### 7.5 重新激活时机研究表

```text
research_memory.memory_reactivation_timing_analysis_v1
```

字段建议：

```sql
timing_analysis_id
research_run_id

timing_bucket                  -- too_early / on_time / too_late / false_reactivation
sample_count

hit_rate_t10
hit_rate_t20
hit_rate_t40
avg_max_return
avg_max_drawdown
avg_days_to_hit

avg_structure_repair_score
avg_moneyflow_reentry_score
avg_board_resonance_score
avg_market_support_score

timing_regret_rate             -- 重新激活时机后悔率，占位字段
confidence_level
created_at
```

研究问题：

```text
模型二是不是过早激活？
是不是等确认太久导致错过主升？
哪些证据组合对应 on_time？
```

### 7.6 二波启动研究表

```text
research_memory.memory_second_wave_analysis_v1
```

字段建议：

```sql
second_wave_analysis_id
research_run_id

sample_count
second_wave_confirmed_count
second_wave_success_rate

pre_second_wave_return_5d
pre_second_wave_volume_ratio
pre_second_wave_turnover_change
pre_second_wave_moneyflow_state
pre_second_wave_board_rank_percentile
pre_second_wave_market_regime

structure_pattern_bucket       -- pullback_repair / horizontal_compression / volume_breakout / board_reactivation / unknown
avg_days_from_first_signal_to_second_wave
avg_days_from_memory_enter_to_second_wave

confidence_level
created_at
```

研究问题：

```text
二波启动前最常见的结构是什么？
资金回流领先价格几天？
板块再共振是否提高成功率？
```

### 7.7 失败归因表

```text
research_memory.memory_failure_attribution_v1
```

字段建议：

```sql
failure_attribution_id
research_run_id

memory_entity_id
origin_signal_id
new_signal_id
canonical_symbol

failure_stage                  -- memory_observation / reactivation_candidate / release_gate / post_signal / outcome_label
failure_type                   -- persistent_weakness / structure_failed / false_reactivation / market_drag / board_failed / moneyflow_failed / data_gap_misled / tradability_failed

primary_reason
secondary_reason
evidence_json

first_signal_failure_impact
structure_impact
moneyflow_impact
board_impact
market_impact
event_impact
data_gap_impact
tradability_impact

manual_review_required
confidence_level
created_at
```

说明：

```text
模型二失败不能简单说 failed；
必须区分是记忆样本本身没有价值，还是重新激活太早/太晚，或数据缺口导致误判。
```

### 7.8 漏激活研究表

```text
research_memory.memory_missed_reactivation_v1
```

字段建议：

```sql
missed_reactivation_id
research_run_id

memory_entity_id
origin_signal_id
canonical_symbol
missed_date

post_missed_max_return
post_missed_hit_date
days_to_hit_after_missed

missed_reason                  -- threshold_too_strict / data_gap / board_signal_ignored / moneyflow_signal_ignored / structure_signal_ignored
evidence_json

would_have_been_reactivation_score -- 反事实占位字段
recommended_action

created_at
```

研究问题：

```text
模型二有没有错过本该重新激活的样本？
错过原因是阈值太严，还是某类证据没被重视？
```

这张表非常重要，因为模型二不只是研究“选中后成败”，还要研究“没选中但本该重新激活”。

### 7.9 模型二进化指标表

```text
research_memory.memory_model_evolution_metric_v1
```

字段建议：

```sql
metric_id
metric_date
model_code                     -- candidate_memory

model_version
feature_version
score_formula_version
release_gate_version
source_data_version

sample_count_20d
sample_count_60d

delayed_success_rate_20d
reactivation_success_rate_20d
second_wave_success_rate_20d

false_reactivation_rate_20d
missed_reactivation_rate_20d
timing_regret_rate_20d

avg_days_to_reactivation_20d
avg_days_to_success_20d

p0_coverage_rate
p1_coverage_rate
freshness_pass_rate

model_health_status            -- healthy/degraded/blocked/research_only
confidence_level
created_at
```

这张表以后给研究中心总览页使用。总览页只展示模型二的进化趋势，不展示个股明细。

---

## 8. 模型二核心研究主线

模型二研究中心第一版建议围绕 7 条主线。

### 8.1 记忆生命周期研究

研究：

```text
历史候选进入 memory pool 后，在哪个时间段最有价值？
最大观察期应该多长？
观察太久是否只是增加噪声？
```

关键字段：

```text
enter_memory_pool_date
memory_age_bucket
memory_status
reactivated_count
delayed_success_count
invalidated_count
avg_days_to_reactivation
```

### 8.2 迟到成功研究

研究：

```text
首次短窗口失败后，有多少样本后续迟到兑现？
迟到成功前有哪些稳定信号？
```

关键字段：

```text
first_outcome_label
delayed_success_confirmed
days_to_delayed_success
pre_success_structure_state
pre_success_moneyflow_state
pre_success_board_state
```

### 8.3 重新激活时机研究

研究：

```text
模型二重新激活是否过早、过晚，还是刚好？
```

关键字段：

```text
reactivation_signal_date
reactivation_timing_label
hit_rate_t10
hit_rate_t20
avg_drawdown_before_hit
timing_regret_rate
```

### 8.4 二波启动研究

研究：

```text
二波启动前的稳定结构是什么？
资金、板块、市场环境哪个更领先？
```

关键字段：

```text
second_wave_confirmed
structure_pattern_bucket
moneyflow_reentry_score
board_resonance_score
market_support_score
```

### 8.5 漏激活研究

研究：

```text
模型二有没有错过本该重新激活的历史候选？
```

关键字段：

```text
missed_date
post_missed_max_return
missed_reason
would_have_been_reactivation_score
```

### 8.6 Hard Negative 研究

研究：

```text
哪些历史候选看起来像要二波，但最终失败？
```

典型 hard negative：

```text
结构修复分高；
资金短暂回流；
板块短暂走强；
但价格未突破或突破失败。
```

这类样本必须沉淀，防止模型二过度激活。

### 8.7 数据缺口影响研究

研究：

```text
资金流缺失、板块历史成员缺失、事件数据缺失，是否导致重新激活误判？
```

模型二尤其要关注：

```text
moneyflow gap
board membership gap
event risk gap
adjusted price gap
```

---

## 9. 模型二关键指标

### 9.1 记忆价值指标

```text
memory_reactivation_rate
delayed_success_rate
second_wave_success_rate
memory_entity_survival_rate
memory_decay_rate
```

### 9.2 时机指标

```text
reactivation_success_rate
false_reactivation_rate
timing_regret_rate
too_early_rate
too_late_rate
avg_days_to_reactivation
```

### 9.3 风险指标

```text
max_drawdown_before_success
structure_invalidated_rate
tradability_failure_rate
data_gap_misled_rate
```

### 9.4 漏选指标

```text
missed_reactivation_rate
missed_success_rate
threshold_too_strict_count
```

### 9.5 数据质量指标

```text
p0_coverage_rate
p1_coverage_rate
freshness_pass_rate
moneyflow_gap_rate
board_gap_rate
event_gap_rate
```

---

## 10. 模型二研究 API 设计

建议第一版 API：

```text
GET  /research/memory/healthz
GET  /research/memory/readyz

POST /research/memory/runs
GET  /research/memory/runs/{research_run_id}
POST /research/memory/runs/{research_run_id}/execute

POST /research/memory/lifecycle/analyze
POST /research/memory/delayed-success/analyze
POST /research/memory/reactivation-timing/analyze
POST /research/memory/second-wave/analyze
POST /research/memory/failure-attribution/analyze
POST /research/memory/missed-reactivation/analyze

GET  /research/memory/samples
GET  /research/memory/entities
GET  /research/memory/lifecycle
GET  /research/memory/delayed-success
GET  /research/memory/reactivation-timing
GET  /research/memory/second-wave
GET  /research/memory/failures
GET  /research/memory/evolution-metrics
```

长任务必须异步执行，不能让前端等待大型研究任务同步完成。

---

## 11. 模型二研究任务流程

标准流程：

```text
1. 创建 memory_research_run。
2. 调用 source-data-service 做 coverage / freshness / preflight。
3. 选取 memory_entity / official_signal / release_gate_rejected / missed_reactivation 样本。
4. 冻结 memory_research_sample。
5. 读取 memory_observation_path。
6. 读取 memory_state_transition。
7. 读取 memory_outcome_label。
8. 执行 lifecycle / delayed_success / second_wave / timing / failure / missed_reactivation 分析。
9. 生成研究结果表。
10. 生成研究结论。
11. strong 以上结论进入人工审核。
12. 审核后才能形成生产模型迭代建议。
```

如果数据源返回：

```text
blocked
```

研究任务必须标记：

```text
status = data_blocked
```

不能生成正式研究结论。

---

## 12. 模型二第一阶段验收标准

模型二研究中心第一阶段必须能回答这些问题：

```text
1. 历史候选进入 memory pool 后，多久最容易重新激活？
2. 首次短窗口失败样本中，有多少是迟到成功？
3. 迟到成功前最常见的结构、资金、板块状态是什么？
4. 重新激活信号是否明显优于继续观察？
5. 重新激活是否过早或过晚？
6. 二波启动前资金是否领先价格？
7. 哪类样本是 hard negative？
8. 哪些样本模型没有重新激活但后续成功了？
9. 模型二每次 official activation 是否都生成了新的 signal_id？
10. 数据缺口是否导致 false reactivation 或 missed reactivation？
```

如果这些问题回答不了，模型二研究中心不算完成。

---

## 13. 给 Codex 的硬性规则

后续落代码时必须写入 README / AGENTS：

```text
1. memory_official_signal.signal_id 不得等于 origin_signal_id。
2. research_memory 不允许直接调用任何外部数据 provider。
3. 所有研究样本必须绑定 memory_entity_id。
4. 所有重新激活研究必须同时保存 origin_signal_id 和 new_signal_id。
5. 模型二成功口径不得使用热点模型 T+1/T+3/T+5 短窗口口径。
6. 迟到成功、二波启动、重新激活成功必须分别打标签。
7. 失败样本必须持续观察到迟到成功、最大观察期结束或结构失效。
8. 漏激活样本必须进入 missed_reactivation 研究。
9. 数据缺口样本不得直接归因为模型失败。
10. 研究结论不得直接修改生产模型参数。
```

---

## 14. 本阶段结论

候选记忆模型研究中心的核心不是简单回看历史收益，而是建立：

```text
历史候选
-> memory_entity
-> 观察路径
-> 状态转移
-> 重新激活候选
-> 新 signal_id
-> 中窗口结果标签
-> 生命周期研究
-> 迟到成功研究
-> 二波启动研究
-> 激活时机研究
-> 漏激活研究
-> hard negative 研究
-> 研究结论
```

它真正要证明的是：

```text
模型二是否让历史失败样本重新产生研究价值；
模型二是否能识别迟到成功和二波启动；
模型二是否能减少漏选；
模型二是否能避免过早激活和假修复。
```


---

# V2 动态特征增强：候选记忆模型研究中心改造

## 1. V2 新增研究目标

候选记忆模型 V1 的核心是历史候选生命周期、迟到成功、二波启动、重新激活时机、漏激活与失败归因。引入 dynamic-feature-service 后，模型二研究中心新增目标：

```text
1. 分时突破是否能比日线重新激活更早发现二波？
2. 重新激活当天的盘中动态特征是否能判断 on_time / too_early / too_late？
3. false reactivation 样本在盘中是否已经出现风险预警？
4. missed reactivation 样本是否曾出现动态提示，但模型二未捕捉？
5. 分时回踩支撑、突破质量、量能恢复、板块盘中共振是否能提高二波识别质量？
```

模型二动态研究的关键不是“盘中强就买”，而是：

```text
能不能让重新激活更早、更准，减少 false reactivation 和 missed reactivation。
```

---

## 2. 新增动态特征依赖

优先 bundle：

```text
memory_reactivation_intraday_bundle_v1
buy_point_intraday_bundle_v1
```

重点 feature：

```text
intraday_breakout_quality_score
intraday_break_previous_high_flag
support_retest_quality_score
post_pullback_reattack_score
volume_recovery_ratio
intraday_moneyflow_reentry_score
board_intraday_resonance_score
false_breakout_risk_score
breakout_fade_risk_score
tradable_entry_window_quality_score
```

---

## 3. 新增表：盘中提前重新激活研究

```sql
CREATE TABLE IF NOT EXISTS research_memory.memory_intraday_reactivation_lead_v1 (
    lead_analysis_id               VARCHAR(64) PRIMARY KEY,
    research_run_id                VARCHAR(64) NOT NULL,

    memory_entity_id               VARCHAR(64) NOT NULL,
    origin_signal_id               VARCHAR(64),
    new_signal_id                  VARCHAR(64),
    canonical_symbol               VARCHAR(32) NOT NULL,

    intraday_signal_time           TIMESTAMP NOT NULL,
    daily_reactivation_signal_date DATE,
    lead_days                      INT,
    lead_minutes                   INT,
    as_of_time_policy              VARCHAR(64) NOT NULL,

    intraday_breakout_quality_score NUMERIC(12,6),
    support_retest_quality_score    NUMERIC(12,6),
    volume_recovery_ratio           NUMERIC(12,6),
    board_intraday_resonance_score  NUMERIC(12,6),

    post_intraday_signal_return_t3  NUMERIC(12,6),
    post_intraday_signal_return_t10 NUMERIC(12,6),
    reactivation_success            BOOLEAN,
    reactivation_timing_label       VARCHAR(32), -- too_early/on_time/too_late/false_reactivation

    confidence_level                VARCHAR(32),
    created_at                      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

### 研究口径

```text
lead_days > 0：动态信号早于日线 official reactivation；
lead_days = 0 但 lead_minutes > 0：同日盘中提前识别；
reactivation_success = true 且 lead_days/lead_minutes 显著，说明动态特征具备提前激活价值。
```

---

## 4. 新增表：错误重新激活动态预警研究

```sql
CREATE TABLE IF NOT EXISTS research_memory.memory_false_reactivation_intraday_warning_v1 (
    warning_id                      VARCHAR(64) PRIMARY KEY,
    research_run_id                 VARCHAR(64) NOT NULL,
    memory_entity_id                VARCHAR(64) NOT NULL,
    new_signal_id                   VARCHAR(64) NOT NULL,
    canonical_symbol                VARCHAR(32) NOT NULL,

    false_reactivation_label        VARCHAR(64),
    intraday_warning_signal_exists  BOOLEAN NOT NULL,

    false_breakout_risk_score       NUMERIC(12,6),
    breakout_fade_risk_score        NUMERIC(12,6),
    volume_fakeout_risk             NUMERIC(12,6),
    price_below_vwap_ratio          NUMERIC(12,6),
    high_open_low_walk_risk         NUMERIC(12,6),

    warning_lead_time_minutes       INT,
    recommended_action              VARCHAR(128), -- increase_risk_penalty / require_support_retest / research_only
    confidence_level                VARCHAR(32),
    created_at                      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

---

## 5. 新增表：漏激活动态提示研究

```sql
CREATE TABLE IF NOT EXISTS research_memory.memory_missed_reactivation_dynamic_signal_v1 (
    missed_dynamic_id               VARCHAR(64) PRIMARY KEY,
    research_run_id                 VARCHAR(64) NOT NULL,
    memory_entity_id                VARCHAR(64) NOT NULL,
    canonical_symbol                VARCHAR(32) NOT NULL,

    missed_date                     DATE NOT NULL,
    dynamic_signal_time             TIMESTAMP NOT NULL,
    as_of_time_policy               VARCHAR(64) NOT NULL,

    intraday_breakout_quality_score NUMERIC(12,6),
    support_retest_quality_score    NUMERIC(12,6),
    board_intraday_resonance_score  NUMERIC(12,6),
    volume_recovery_ratio           NUMERIC(12,6),

    post_dynamic_signal_max_return  NUMERIC(12,6),
    days_to_hit_after_dynamic_signal INT,

    missed_reason                   VARCHAR(128), -- threshold_too_strict / data_gap / dynamic_feature_not_used / board_signal_ignored
    recommended_action              VARCHAR(128),
    created_at                      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

---

## 6. 新增表：二波分时结构研究

```sql
CREATE TABLE IF NOT EXISTS research_memory.memory_second_wave_intraday_structure_v1 (
    structure_id                    VARCHAR(64) PRIMARY KEY,
    research_run_id                 VARCHAR(64) NOT NULL,
    structure_bucket                VARCHAR(64), -- breakout_first / pullback_then_breakout / board_driven / moneyflow_first / fake_breakout

    sample_count                    INT NOT NULL,
    second_wave_success_rate        NUMERIC(12,6),
    false_reactivation_rate         NUMERIC(12,6),
    avg_lead_minutes                NUMERIC(12,6),
    avg_intraday_breakout_quality   NUMERIC(12,6),
    avg_support_retest_quality      NUMERIC(12,6),
    avg_board_resonance_score       NUMERIC(12,6),

    recommended_rule_action         VARCHAR(128), -- keep/tighten/loosen/add_dynamic_confirmation
    confidence_level                VARCHAR(32),
    created_at                      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

---

## 7. 模型二新增研究指标

```text
reactivation_intraday_lead_score
intraday_breakout_before_daily_signal_rate
false_reactivation_intraday_warning_rate
dynamic_reactivation_timing_lift
missed_reactivation_dynamic_signal_rate
support_retest_reactivation_success_lift
board_intraday_resonance_lift
```

---

## 8. 模型二研究任务流程 V2

```text
1. 创建 memory_research_run。
2. 冻结 memory_entity、origin_signal、new_signal、outcome 样本。
3. 读取 reactivation_candidate / official_signal 对应 dynamic_feature_snapshot。
4. 对缺失样本创建 research_replay，并标记 replay_only。
5. 分析盘中提前重新激活。
6. 分析 false reactivation 动态预警。
7. 分析 missed reactivation 动态提示。
8. 分析二波分时结构。
9. 写入 research_dynamic 增益研究和分桶研究。
10. 生成 memory_research_finding。
```

---

## 9. V2 验收标准

候选记忆模型 V2 研究中心必须能回答：

```text
1. 二波启动是否常先出现分时突破？
2. 分时信号能比日线重新激活提前多久？
3. 提前激活是否带来更高收益或更低回撤？
4. false reactivation 是否有盘中风险预警？
5. missed reactivation 中有多少出现过动态提示？
6. 哪类动态结构是真二波，哪类是假突破？
7. 动态特征是否会导致过早激活？
```
