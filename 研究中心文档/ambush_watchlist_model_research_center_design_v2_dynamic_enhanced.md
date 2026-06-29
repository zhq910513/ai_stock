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

# 潜伏抬头模型研究中心 V2 动态增强版

# 潜伏抬头模型（龙抬头）研究中心设计文档 v1

> 平台：神策中心  
> 模型：模型三 / 潜伏抬头模型 / ambush_watchlist / 龙抬头  
> 文档目标：为后续 Codex 迭代提供可落地的研究中心设计、库表字段契约、低谷图形标注页面设计和验收标准。  
> 重要边界：本文是研究中心设计文档，不是交易建议文档；研究中心不得直接修改生产模型参数，不得直接写入 official signal，不得直接调用外部 provider。

---

## 0. 核心结论

模型三研究中心的核心不是简单统计“推荐后涨没涨”，而是研究完整结构链条：

```text
全市场 universe
-> 低谷观察池 valley_watch_pool
-> 有效抬头锚点 effective_turn_anchor_day
-> 有效抬头候选池 effective_turn_pool
-> 池间转移审计 transition_audit
-> L2/L3/L4 深度确认
-> release_gate
-> official_signal
-> 观察路径
-> 结果标签
-> 低谷有效性研究
-> 抬头时机研究
-> day1/day2 验证
-> 低点后 7-8 天连续反弹剔除规则验证
-> 横盘压缩后突破重启研究
-> hard negative 假反弹研究
-> missed opportunity 漏选研究
-> 失败归因
-> 模型成长建议
```

模型三研究中心必须增加一个独立页面：

```text
低谷图形标注中心
```

该页面是模型三最重要的研究资产入口之一，负责把人工经验沉淀为可追溯、可复核、可训练、可研究的结构化样本库。

---

## 1. 模型三研究中心定位

模型三不是热点追涨，也不是普通超跌反弹。它研究的是：

```text
低谷成熟之后，股票是否出现了第一天或第二天的有效抬头结构；
这个抬头是否具备后续启动价值；
模型是否能在“刚抬头”阶段识别，而不是等已经涨远才发现。
```

研究中心要长期回答：

```text
1. 低谷观察池是否真正发现了潜在启动样本？
2. 有效抬头锚点是否过早、过晚，还是刚好？
3. day1/day2 刚抬头规则是否合理？
4. 低点后 7-8 天连续反弹剔除规则是否误伤？
5. 横盘压缩后突破是否应该重新计为有效抬头？
6. L2/L3/L4 哪一层真正提升了成功率？
7. hard negative 和真实启动样本差在哪里？
8. 000759 这类样本为什么停在 valley_watch，没有进入有效抬头？
9. 模型三是否真正做到早期识别，而不是追涨确认？
```

一句话定位：

```text
模型三研究中心 = 低谷结构、有效抬头锚点、池间转移、刚抬头窗口、假反弹识别、hard negative 与早期启动验证研究中心。
```

---

## 2. 研究中心硬性边界

### 2.1 允许做的事

```text
1. 读取 source-data-service 的 source 标准事实表。
2. 读取 ambush-watchlist-service 的 decision_ambush 生产快照。
3. 读取数据源服务的 coverage / freshness / lineage / preflight。
4. 固化低谷样本、抬头样本、release 样本、失败样本、漏选样本。
5. 研究 valley_watch_pool 是否有效。
6. 研究 effective_turn_anchor_day 是否准确。
7. 研究低谷池 -> 抬头池转移是否合理。
8. 研究 day1/day2、7-8 天连续反弹、横盘压缩后突破重启规则。
9. 研究 hard negative 和 missed opportunity。
10. 形成模型三迭代建议。
```

### 2.2 禁止做的事

```text
1. 不允许 research_ambush 直接调用任何外部数据 provider。
2. 不允许研究中心直接写 official_signal。
3. 不允许研究中心直接修改模型三生产参数。
4. 不允许用未来数据参与低谷和抬头判断。
5. 不允许把已经连续反弹多日的追涨样本算成“刚抬头成功”。
6. 不允许把一字板、停牌、ST、退市风险样本算成正常成功。
7. 不允许把数据缺口导致的错判简单归因为模型失败。
8. 不允许把研究图形相似度直接当作正式交易信号。
```

---

## 3. 研究主线

模型三研究中心第一版拆成 12 条研究主线：

```text
1. 低谷样本库研究
2. 低谷观察池有效性研究
3. 有效抬头锚点时机研究
4. 低谷池 -> 抬头池转移审计研究
5. day1/day2 刚抬头窗口验证
6. 低点后 7-8 天连续反弹剔除规则验证
7. 横盘压缩后突破重启规则研究
8. L2/L3/L4 深度确认贡献研究
9. release_gate 有效性研究
10. hard negative 假反弹研究
11. missed opportunity 漏选研究
12. 数据缺口影响研究
```

这 12 条线共同回答：

```text
模型三是否真的能在“低谷成熟后的第一/第二天有效抬头”阶段识别机会？
```

---

## 4. 全链路数据结构

```text
source.stock_universe_daily_v1
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
decision_ambush.ambush_scan_universe_v1
decision_ambush.ambush_pattern_feature_snapshot_v1
decision_ambush.ambush_valley_watch_pool_v1
decision_ambush.ambush_effective_turn_anchor_v1
decision_ambush.ambush_effective_turn_pool_v1
decision_ambush.ambush_pool_transition_audit_v1
decision_ambush.ambush_l2_l3_l4_confirmation_v1
decision_ambush.ambush_release_gate_audit_v1
decision_ambush.ambush_official_signal_v1
decision_ambush.ambush_observation_path_v1
decision_ambush.ambush_outcome_label_v1
        ↓
research_ambush.ambush_research_run_v1
research_ambush.ambush_research_sample_v1
research_ambush.ambush_valley_pool_effectiveness_v1
research_ambush.ambush_turn_anchor_timing_v1
research_ambush.ambush_transition_audit_analysis_v1
research_ambush.ambush_day1_day2_validation_v1
research_ambush.ambush_late_rebound_rule_validation_v1
research_ambush.ambush_compression_restart_analysis_v1
research_ambush.ambush_confirmation_layer_contribution_v1
research_ambush.ambush_release_gate_effectiveness_v1
research_ambush.ambush_hard_negative_analysis_v1
research_ambush.ambush_missed_opportunity_v1
research_ambush.ambush_failure_attribution_v1
research_ambush.ambush_data_gap_impact_v1
research_ambush.ambush_model_evolution_metric_v1
        ↓
research_ambush.ambush_valley_chart_case_v1
research_ambush.ambush_valley_manual_label_v1
research_ambush.ambush_valley_manual_label_tag_v1
research_ambush.ambush_valley_label_taxonomy_v1
research_ambush.ambush_valley_label_review_v1
research_ambush.ambush_valley_pattern_library_member_v1
```

---

## 5. Source 字段依赖设计

真实库表字段不确定时，Codex 应按字段注释映射真实字段，不得擅自创造无金融含义字段。

### 5.1 全市场扫描 universe

来源：

```text
source.stock_universe_daily_v1
source.stock_master_v1
source.trade_status_v1
```

字段契约：

```sql
canonical_symbol              -- 统一股票代码，例如 000759.SZ
trade_date                    -- 扫描交易日
stock_name                    -- 股票名称
exchange_code                 -- SZSE/SSE/BSE，占位字段
market_board                  -- 主板/创业板/科创板/北交所，占位字段

is_in_scan_universe            -- 是否进入模型三扫描范围
universe_exclude_reason        -- ST/停牌/退市风险/非深市A股/数据缺失/其他
is_st                          -- 是否 ST
is_suspended                   -- 是否停牌
is_delisting_risk              -- 是否退市风险
is_tradable                    -- 是否可交易
security_type                  -- 股票/ETF/指数/其他
listing_date                   -- 上市日期
```

模型三当前范围要求：

```text
深圳 A 股全市场扫描，排除 ST、停牌、退市风险、非股票、数据不足样本。
```

### 5.2 日线行情字段

来源：

```text
source.daily_bar_v1
```

字段契约：

```sql
canonical_symbol
trade_date
open_price                    -- 未复权开盘价，用于真实交易状态
high_price                    -- 未复权最高价
low_price                     -- 未复权最低价
close_price                   -- 未复权收盘价
pre_close_price               -- 昨收价
volume                        -- 成交量
amount                        -- 成交额
turnover_rate                 -- 换手率
pct_chg                       -- 涨跌幅
source_quality_status
source_build_batch_id
lineage_id
```

用途：

```text
未复权价格用于涨跌停、可交易性、真实成交判断和观察路径；不能用复权价格判断涨跌停。
```

### 5.3 复权行情字段

来源：

```text
source.adjusted_daily_bar_v1
```

字段契约：

```sql
canonical_symbol
trade_date
adjustment_mode               -- qfq/hfq/raw；模型三形态研究建议 qfq
adjusted_open
adjusted_high
adjusted_low
adjusted_close
adjusted_volume               -- 如果 provider 无复权成交量，保留原 volume 并注释说明
source_quality_status
source_build_batch_id
lineage_id
```

用途：

```text
低谷形态识别、历史相对位置、回撤成熟度、形态相似度、窗口特征计算。
```

硬规则：

```text
形态计算使用 adjusted 系列；涨跌停和可交易性判断使用 raw price。
```

### 5.4 周线字段

来源：

```text
source.weekly_bar_v1
```

字段契约：

```sql
canonical_symbol
week_end_date
weekly_open
weekly_high
weekly_low
weekly_close
weekly_volume
weekly_amount
weekly_return
weekly_trend_state             -- downtrend/basing/turning_up/uptrend/unknown，占位字段
weekly_support_state           -- support_intact/support_broken/unknown，占位字段
```

用途：

```text
过滤日线低谷但周线仍持续破位的弱结构；识别中期低谷修复。
```

### 5.5 涨跌停与可交易字段

来源：

```text
source.limit_price_v1
source.limit_event_v1
source.trade_status_v1
```

字段契约：

```sql
canonical_symbol
trade_date
up_limit_price
down_limit_price
limit_rule                    -- 10pct/20pct/5pct_st/other
is_limit_up
is_limit_down
is_one_word_limit
limit_open_status             -- opened/sealed/one_word/unknown，占位字段
distance_to_up_limit
tradability_state             -- tradable/unfriendly/blocked/unknown
```

用途：

```text
过滤不可交易样本；识别涨停后次日可交易窗口；区分价格成功和可交易成功。
```

### 5.6 市场环境字段

来源：

```text
source.index_daily_bar_v1
source.market_breadth_v1
source.market_regime_v1
```

字段契约：

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
risk_appetite_score            -- 市场风险偏好，占位字段
market_regime                  -- strong/weak/choppy/risk_off/unknown
```

用途：

```text
判断低谷抬头是否处于支持性市场环境；研究弱市下假抬头概率是否更高。
```

### 5.7 板块字段

来源：

```text
source.stock_board_membership_v1
source.board_daily_bar_v1
```

字段契约：

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
board_resonance_score          -- 板块共振分，占位字段
```

用途：

```text
研究抬头样本是否受到板块共振支持；判断个股独立抬头还是板块带动抬头。
```

### 5.8 资金流字段

来源：

```text
source.stock_moneyflow_daily_v1
source.stock_moneyflow_snapshot_v1
```

字段契约：

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

用途：

```text
研究低谷抬头是否伴随资金回流；识别缩量假反弹和放量有效抬头。
```

第一版建议：

```text
资金流为 P1，不作为 P0 阻断项；缺失时降低研究置信度。
```

### 5.9 事件与风险字段

来源：

```text
source.event_news_v1
source.announcement_event_v1
```

字段契约：

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

用途：

```text
识别低谷样本中是否存在重大风险；避免用盘后公告解释盘前决策。
```

---

## 6. decision_ambush 生产层设计

### 6.1 扫描 universe 表

```text
decision_ambush.ambush_scan_universe_v1
```

字段：

```sql
scan_universe_id
scan_date
canonical_symbol
stock_name
is_in_universe
exclude_reason                 -- non_sz_a/st/suspended/delisting_risk/insufficient_history/data_gap
history_days_available
required_history_days
source_coverage_snapshot_id
source_freshness_snapshot_id
data_quality_status
created_at
```

用途：

```text
研究模型三有没有漏扫；确认 000759 这类样本是否进入过 universe。
```

### 6.2 形态特征快照表

```text
decision_ambush.ambush_pattern_feature_snapshot_v1
```

建议采用长表，便于后续扩展。

```sql
feature_snapshot_id
scan_universe_id
canonical_symbol
scan_date
feature_group                  -- price_path / candle_geometry / volume_path / valley_maturity / compression / pattern_similarity / weekly_context
feature_name                   -- 具体特征名
feature_value_numeric
feature_value_text
feature_value_json
feature_unit
window_start_date
window_end_date
lookback_days                  -- 例如 20/40/60/120
source_table_name
source_field_name
source_lineage_id
available_at
feature_version
quality_status                 -- passed/degraded/suspect/missing
comment                        -- Codex 注释：说明金融含义
```

典型 feature 示例：

```text
feature_group = valley_maturity
feature_name = drawdown_from_recent_high_pct
comment = 从近 N 日高点到当前低位的回撤比例，用于判断低谷成熟度，不能使用未来数据。
```

```text
feature_group = compression
feature_name = horizontal_compression_width
comment = 低点后横盘压缩区间宽度，占位字段，后续按高低价区间波动收敛定义。
```

```text
feature_group = pattern_similarity
feature_name = valley_pattern_similarity_score
comment = 与低谷样本库原型的形态相似度，占位字段，可由 shape_signature / DTW / 归一化价格路径计算。
```

### 6.3 低谷观察池表

```text
decision_ambush.ambush_valley_watch_pool_v1
```

字段：

```sql
valley_watch_id
scan_universe_id
canonical_symbol
scan_date
valley_low_date                -- 当前识别的低点日期
valley_low_price               -- 低点价格，建议 qfq 口径用于结构
days_since_valley_low          -- 距低点天数
valley_maturity_score          -- 低谷成熟分
drawdown_maturity_score        -- 回撤成熟分
near_low_score                 -- 靠近低点程度分
downside_slowdown_score        -- 下跌速度放缓分
support_intact_score           -- 支撑未破分
volume_shrink_score            -- 缩量低谷分，占位字段
weekly_context_score           -- 周线环境分，占位字段
valley_watch_score             -- 综合低谷观察分
valley_watch_status            -- active/expired/invalidated/promoted_to_turn_pool
enter_reason
invalid_reason
model_version
feature_version
source_data_version
created_at
updated_at
```

用途：

```text
研究低谷池是否真正捕捉了潜在机会；解释为什么某只股票停留在 valley_watch。
```

### 6.4 有效抬头锚点表

```text
decision_ambush.ambush_effective_turn_anchor_v1
```

字段：

```sql
turn_anchor_id
valley_watch_id
canonical_symbol
anchor_date                    -- 有效抬头锚点日
anchor_day_offset              -- 距 valley_low_date 第几天
turn_day_type                  -- day1/day2/late_breakout/compression_restart/invalid
open_price
high_price
low_price
close_price
volume
amount
price_turn_score               -- 价格抬头分
candle_quality_score           -- K线质量分
volume_confirmation_score      -- 量能确认分
support_retest_score           -- 回踩支撑未破分
false_rebound_risk_score       -- 假反弹风险分
is_first_or_second_turn_day    -- 是否第一/第二天抬头
is_continuous_rebound_7_8d     -- 是否低点后 7-8 天连续反弹
is_horizontal_compression_restart -- 是否横盘压缩后突破重启
anchor_status                  -- valid/invalid/research_only
anchor_reason
created_at
```

用途：

```text
研究 anchor_date 是否过早或过晚；验证 day1/day2 规则；验证 7-8 天连续反弹剔除规则和横盘压缩后突破重启规则。
```

### 6.5 有效抬头候选池表

```text
decision_ambush.ambush_effective_turn_pool_v1
```

字段：

```sql
effective_turn_pool_id
turn_anchor_id
valley_watch_id
canonical_symbol
enter_pool_date
effective_turn_score
turn_strength_score
space_score                    -- 上方空间分，占位字段
risk_reward_score              -- 风险收益比分，占位字段
false_rebound_risk_score
data_gap_penalty_score
pool_status                    -- active/rejected/promoted_to_l2_l3_l4/release_gate_passed/release_gate_failed
reject_reason
created_at
updated_at
```

### 6.6 池间转移审计表

```text
decision_ambush.ambush_pool_transition_audit_v1
```

字段：

```sql
transition_audit_id
canonical_symbol
transition_date
from_pool                      -- valley_watch_pool
to_pool                        -- effective_turn_pool / rejected / expired / invalidated
from_entity_id
to_entity_id
trigger_rule_code              -- day1_turn / day2_turn / compression_restart / support_broken / continuous_rebound_too_late
trigger_features_json
transition_result              -- success/rejected/research_only
transition_reason_text
model_version
rule_version
created_at
```

这是模型三可审计性的核心表。

### 6.7 L2/L3/L4 深度确认表

```text
decision_ambush.ambush_l2_l3_l4_confirmation_v1
```

字段：

```sql
confirmation_id
effective_turn_pool_id
canonical_symbol
confirm_date
l2_price_structure_pass        -- L2 价格结构是否通过
l2_price_structure_score
l2_reason_json
l3_volume_moneyflow_pass       -- L3 量能/资金是否通过
l3_volume_moneyflow_score
l3_reason_json
l4_sector_market_pass          -- L4 板块/市场环境是否通过
l4_sector_market_score
l4_reason_json
combined_confirmation_score
confirmation_status            -- passed/degraded/failed
failed_layer                   -- L2/L3/L4/none
created_at
```

### 6.8 release gate 审计表

```text
decision_ambush.ambush_release_gate_audit_v1
```

字段：

```sql
gate_audit_id
effective_turn_pool_id
canonical_symbol
gate_date
gate_name                      -- data_preflight/tradable/non_st/valley_valid/anchor_valid/l2_l3_l4/market_risk/event_risk
gate_result                    -- pass/fail/warn
blocking_level                 -- P0/P1/P2
gate_reason_code
gate_reason_text
evidence_json
release_gate_version
created_at
```

### 6.9 正式信号表

```text
decision_ambush.ambush_official_signal_v1
```

字段：

```sql
signal_id
effective_turn_pool_id
turn_anchor_id
valley_watch_id
canonical_symbol
signal_date
decision_time
valley_low_date
effective_turn_anchor_day
anchor_day_offset
final_score
final_rank
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

只有 `signal_status = official` 才进入正式成功率统计。

### 6.10 观察路径表

```text
decision_ambush.ambush_observation_path_v1
```

字段：

```sql
observation_id
signal_id
canonical_symbol
signal_date
trade_date
day_offset                    -- T+1/T+3/T+5/T+10/T+15/T+20
benchmark_buy_price
benchmark_buy_price_method
open_price
high_price
low_price
close_price
volume
amount
return_open
return_high
return_low
return_close
max_return_so_far
max_drawdown_so_far
structure_state                -- turn_confirmed/compressing/continuing/broken/false_rebound/unknown
support_state                  -- support_intact/support_broken/unknown
volume_state                   -- volume_confirmed/shrinking/abnormal/unknown
tradability_state
market_regime
board_return_1d
stock_vs_board_relative_strength
data_quality_status
created_at
```

### 6.11 结果标签表

```text
decision_ambush.ambush_outcome_label_v1
```

字段：

```sql
outcome_label_id
signal_id
canonical_symbol
signal_date
evaluation_window              -- T5/T10/T15/T20
window_start_date
window_end_date
benchmark_buy_price
max_return
close_return
max_drawdown
hit_target
target_return_threshold
hit_target_date
days_to_hit
structure_success              -- 结构是否成功延续
price_success                  -- 价格是否达标
tradability_success            -- 是否有合理交易窗口
false_rebound_confirmed        -- 是否确认假反弹
late_breakout_confirmed        -- 是否迟到突破
outcome_label                  -- effective_turn_success / false_turn / late_breakout / structure_invalidated / hard_negative_false_rebound / data_blocked
label_reason
label_version
created_at
```

---

## 7. research_ambush 研究表设计

### 7.1 研究任务表

```text
research_ambush.ambush_research_run_v1
```

```sql
research_run_id
research_type                  -- valley_pool/turn_anchor/transition/day1_day2/late_rebound/compression_restart/l2_l3_l4/release_gate/hard_negative/missed_opportunity
research_name
model_code                     -- ambush_watchlist
model_version
feature_version
score_formula_version
release_gate_version
source_data_version
sample_start_date
sample_end_date
evaluation_window              -- T5/T10/T15/T20
status                         -- created/running/succeeded/failed/data_blocked
created_by
created_at
started_at
finished_at
comment
```

### 7.2 研究样本表

```text
research_ambush.ambush_research_sample_v1
```

```sql
research_sample_id
research_run_id
sample_origin                  -- valley_watch_pool/effective_turn_pool/official_signal/release_gate_rejected/missed_opportunity/control_group
sample_role                    -- positive/negative/hard_negative/late_breakout/false_turn/missed_opportunity/control_group
valley_watch_id
turn_anchor_id
effective_turn_pool_id
signal_id
canonical_symbol
scan_date
valley_low_date
anchor_date
signal_date
anchor_day_offset
turn_day_type                  -- day1/day2/late_breakout/compression_restart/invalid
outcome_label
model_version
source_data_version
source_coverage_snapshot_id
source_freshness_snapshot_id
source_quality_status
created_at
```

### 7.3 低谷观察池有效性研究表

```text
research_ambush.ambush_valley_pool_effectiveness_v1
```

```sql
valley_effectiveness_id
research_run_id
valley_score_bucket            -- high/mid/low
sample_count
promoted_to_turn_pool_count
promotion_rate
official_signal_count
official_signal_rate
effective_turn_success_count
effective_turn_success_rate
false_turn_count
false_turn_rate
late_breakout_count
late_breakout_rate
structure_invalidated_count
avg_days_from_valley_to_anchor
avg_max_return_after_valley
avg_max_drawdown_after_valley
confidence_level
created_at
```

### 7.4 有效抬头锚点时机研究表

```text
research_ambush.ambush_turn_anchor_timing_v1
```

```sql
timing_analysis_id
research_run_id
anchor_day_bucket              -- day1/day2/day3_5/day6_8/late/compression_restart
sample_count
success_rate_t5
success_rate_t10
success_rate_t15
false_turn_rate
late_breakout_rate
avg_max_return
avg_max_drawdown
too_early_rate
too_late_rate
on_time_rate
anchor_timing_regret_rate      -- 锚点时机后悔率，占位字段
confidence_level
created_at
```

### 7.5 池间转移审计研究表

```text
research_ambush.ambush_transition_audit_analysis_v1
```

```sql
transition_analysis_id
research_run_id
trigger_rule_code              -- day1_turn/day2_turn/compression_restart/support_broken/continuous_rebound_too_late
sample_count
transition_success_rate
transition_false_positive_rate
transition_false_negative_rate
post_transition_success_rate_t10
post_transition_success_rate_t15
avg_trigger_score
common_reject_reason
common_failure_reason
confidence_level
created_at
```

### 7.6 day1/day2 刚抬头验证表

```text
research_ambush.ambush_day1_day2_validation_v1
```

```sql
day_validation_id
research_run_id
turn_day_type                  -- day1/day2/non_day1_day2
sample_count
success_rate_t5
success_rate_t10
success_rate_t15
false_rebound_rate
avg_max_return
avg_max_drawdown
day1_vs_day2_lift_score        -- day1 相对 day2 的效果差，占位字段
day1_day2_rule_validity_score  -- day1/day2 规则有效性分，占位字段
confidence_level
created_at
```

### 7.7 低点后 7-8 天连续反弹规则验证表

```text
research_ambush.ambush_late_rebound_rule_validation_v1
```

```sql
late_rebound_validation_id
research_run_id
rebound_pattern_bucket         -- continuous_rebound_7_8d / continuous_rebound_5_6d / early_turn / compression_after_rebound
sample_count
excluded_by_rule_count
excluded_success_count
excluded_late_success_count
excluded_failure_count
success_rate_if_excluded
failure_rate_if_excluded
rule_precision_score           -- 剔除规则准确率，占位字段
rule_missed_opportunity_rate   -- 剔除后错过机会率，占位字段
recommended_rule_action        -- keep/tighten/loosen/add_exception
created_at
```

### 7.8 横盘压缩后突破重启研究表

```text
research_ambush.ambush_compression_restart_analysis_v1
```

```sql
compression_restart_id
research_run_id
compression_window_bucket      -- 3_5d / 6_10d / 11_20d / 20d_plus
sample_count
restart_signal_count
restart_success_count
restart_success_rate
false_restart_rate
avg_compression_width
avg_volume_shrink_score
avg_breakout_volume_ratio
avg_days_from_low_to_restart
recommended_restart_rule_action -- keep/tighten/loosen/research_only
confidence_level
created_at
```

### 7.9 L2/L3/L4 贡献研究表

```text
research_ambush.ambush_confirmation_layer_contribution_v1
```

```sql
layer_contribution_id
research_run_id
layer_name                     -- L2_price_structure / L3_volume_moneyflow / L4_sector_market
sample_count
pass_count
fail_count
pass_success_rate
fail_success_rate
lift_score                     -- 通过该层后的成功率提升，占位字段
false_negative_rate            -- 该层挡掉但后续成功的比例
false_positive_rate            -- 该层通过但后续失败的比例
recommended_layer_action       -- keep/tighten/loosen/research_only
confidence_level
created_at
```

### 7.10 release_gate 有效性研究表

```text
research_ambush.ambush_release_gate_effectiveness_v1
```

```sql
release_gate_effectiveness_id
research_run_id
gate_name
sample_count
passed_count
blocked_count
warn_count
passed_success_rate
blocked_late_success_rate
blocked_missed_opportunity_rate
gate_precision_score
gate_recall_cost_score
recommended_gate_action        -- keep/tighten/loosen/add_exception
confidence_level
created_at
```

### 7.11 hard negative 假反弹研究表

```text
research_ambush.ambush_hard_negative_analysis_v1
```

```sql
hard_negative_id
research_run_id
sample_count
hard_negative_type             -- false_rebound / support_break_after_turn / volume_fakeout / sector_fake_resonance / moneyflow_fake_inflow
avg_valley_maturity_score
avg_turn_strength_score
avg_volume_confirmation_score
avg_board_resonance_score
avg_false_rebound_risk_score
common_failure_path_json       -- 失败路径描述
distinguishing_features_json   -- 与成功样本差异字段
recommended_negative_rule      -- 建议加入 hard negative 规则
created_at
```

### 7.12 missed opportunity 漏选研究表

```text
research_ambush.ambush_missed_opportunity_v1
```

```sql
missed_opportunity_id
research_run_id
canonical_symbol
missed_date
valley_low_date
possible_anchor_date
post_missed_max_return
post_missed_hit_date
days_to_hit_after_missed
missed_stage                   -- universe_excluded / valley_not_detected / turn_anchor_not_detected / release_gate_blocked / rank_too_low
missed_reason                  -- data_gap / threshold_too_strict / compression_restart_not_supported / board_signal_ignored / moneyflow_signal_ignored
would_have_valley_score        -- 反事实占位字段
would_have_turn_score          -- 反事实占位字段
evidence_json
recommended_action
created_at
```

### 7.13 失败归因表

```text
research_ambush.ambush_failure_attribution_v1
```

```sql
failure_attribution_id
research_run_id
signal_id
valley_watch_id
turn_anchor_id
effective_turn_pool_id
canonical_symbol
signal_date
failure_stage                  -- valley_watch / turn_anchor / effective_turn_pool / l2_l3_l4 / release_gate / post_signal / outcome_label
failure_type                   -- false_rebound / support_broken / late_chase / market_drag / board_failed / moneyflow_failed / data_gap_misled / tradability_failed / event_risk
primary_reason
secondary_reason
evidence_json
valley_impact
anchor_timing_impact
structure_impact
volume_impact
board_impact
moneyflow_impact
market_impact
event_impact
data_gap_impact
tradability_impact
manual_review_required
confidence_level
created_at
```

### 7.14 数据缺口影响研究表

```text
research_ambush.ambush_data_gap_impact_v1
```

```sql
data_gap_impact_id
research_run_id
gap_field_group                -- adjusted_bar / daily_bar / weekly_bar / trade_status / board / moneyflow / event / market_breadth
gap_field_name
required_level                 -- P0/P1/P2
sample_count_with_gap
sample_count_without_gap
success_rate_with_gap
success_rate_without_gap
false_turn_rate_with_gap
false_turn_rate_without_gap
missed_opportunity_rate_with_gap
missed_opportunity_rate_without_gap
impact_score
recommended_requirement_change -- keep_p1 / upgrade_to_p0 / downgrade / ignore
created_at
```

### 7.15 模型三进化指标表

```text
research_ambush.ambush_model_evolution_metric_v1
```

```sql
metric_id
metric_date
model_code                     -- ambush_watchlist
model_version
feature_version
score_formula_version
release_gate_version
source_data_version
sample_count_20d
sample_count_60d
valley_promotion_rate_20d
effective_turn_success_rate_20d
official_signal_success_rate_20d
false_turn_rate_20d
hard_negative_rate_20d
missed_opportunity_rate_20d
anchor_timing_regret_rate_20d
day1_day2_validity_score_20d
compression_restart_success_rate_20d
p0_coverage_rate
p1_coverage_rate
freshness_pass_rate
model_health_status            -- healthy/degraded/blocked/research_only
confidence_level
created_at
```

---

## 8. 低谷图形标注中心

### 8.1 页面定位

页面名称：

```text
模型三研究中心 / 低谷图形标注中心
```

职责：

```text
1. 展示低谷样本的 K 线形态。
2. 支持人工标注低谷结构。
3. 支持人工判断是否属于有效抬头前结构。
4. 支持标记 hard negative。
5. 支持沉淀低谷图形样本库。
6. 支持后续模型三形态规则、pattern library、hard negative 规则迭代。
```

它不是：

```text
1. 推荐列表。
2. 交易建议。
3. 实时选股页面。
4. 模型三正式信号页。
```

### 8.2 为什么必须独立出来

模型三最难的不是算分，而是“低谷形态是否真的像低谷”。很多结构数值上接近，但肉眼看完全不同：

```text
1. 真低谷。
2. 下跌中继。
3. 假反弹。
4. 横盘压缩。
5. 支撑破位前夜。
6. 已经连续反弹走远。
7. 缩量低位但无抬头。
8. 板块带动的一日脉冲。
```

低谷图形页的价值：

```text
把模型三最容易误判的形态，沉淀成可复用、可审计、可训练的样本库。
```

---

## 9. 低谷图形标注页面核心视图

### 9.1 样本队列区

字段：

```text
股票代码
股票名称
扫描日期
低点日期
距低点天数
低谷观察分
当前状态
模型自动判断
人工标注状态
是否存在分歧
```

筛选项：

```text
valley_watch 高分未转入抬头池
effective_turn 成功样本
false_turn 失败样本
release_gate rejected 后续成功样本
missed opportunity
hard negative 候选
低点后 7-8 天连续反弹样本
横盘压缩后突破样本
```

### 9.2 K 线图形区

至少展示：

```text
1. 日 K 线图；
2. 成交量 / 成交额图；
3. 周线趋势小图。
```

图形标记：

```text
valley_low_date                -- 低点日
scan_date                      -- 模型扫描日
effective_turn_anchor_day      -- 有效抬头锚点日
release_gate_date              -- 正式发布日
observation_window             -- 后续观察窗口
```

叠加区域：

```text
低谷区间
横盘压缩区间
支撑线
前高压力位
涨跌停标记
放量标记
假突破标记
```

注意：页面展示可以画图，但模型计算仍然应使用数值序列：

```text
adjusted price path
candle geometry
volume path
shape_signature
window features
```

不能让 Codex 误以为模型是直接识别图片像素。

### 9.3 自动特征解释区

展示模型自动计算结构证据：

```text
valley_maturity_score
drawdown_maturity_score
near_low_score
downside_slowdown_score
support_intact_score
volume_shrink_score
horizontal_compression_score
pattern_similarity_score
false_rebound_risk_score
weekly_context_score
```

每个分数 tooltip 必须说明：

```text
字段来源
计算窗口
金融含义
是否使用复权价
是否可用于正式模型
```

### 9.4 人工打标区

人工打标必须分组，不能只给“好 / 不好”。

### 9.5 观察与结果区

展示：

```text
T+1
T+3
T+5
T+10
T+15
T+20
```

内容：

```text
最大收益
最大回撤
是否支撑破位
是否假反弹
是否迟到突破
是否可交易
最终 outcome_label
```

必须区分：

```text
as_of 标注模式：只能看到当时可见数据，防止未来函数。
outcome_review 模式：可以看到后续走势，用于结果归因和 hard negative 标注。
```

---

## 10. 人工打标维度设计

### 10.1 低谷结构类型

字段：

```text
valley_shape_type
```

可选：

```text
V_LEFT_HALF                 -- V 左半，快速下跌后初步止跌
SQRT_RIGHT_HALF             -- 根号右半，低位后开始缓慢抬头
U_SHAPE_BOTTOM              -- U 型底
DOUBLE_BOTTOM               -- 双底
MULTI_BOTTOM                -- 多重底
BOX_BOTTOM                  -- 箱体底部
PLATFORM_BASE               -- 平台低位整理
DESCENDING_CHANNEL_END      -- 下降通道末端
FALLING_KNIFE               -- 下跌中继 / 飞刀，不应作为正样本
NO_CLEAR_VALLEY             -- 无明显低谷
```

### 10.2 低谷成熟度标注

字段：

```text
valley_maturity_tags
manual_valley_maturity_score: 0-100
```

可多选：

```text
DRAWDOWN_SUFFICIENT          -- 回撤充分
TIME_AT_LOW_SUFFICIENT       -- 低位停留时间足够
NEAR_RECENT_LOW              -- 靠近近期低点
DOWNSIDE_SLOWING             -- 下跌速度放缓
SUPPORT_INTACT               -- 支撑未破
LOW_VOLUME_SHRINK            -- 低位缩量
VOLATILITY_CONTRACTING       -- 波动收敛
NO_MATURITY                  -- 未成熟
```

### 10.3 支撑结构标注

字段：

```text
support_structure_tags
```

可选：

```text
SUPPORT_CLEAR                -- 支撑明确
SUPPORT_RETEST_SUCCESS        -- 回踩支撑成功
SUPPORT_WEAK                 -- 支撑偏弱
SUPPORT_BROKEN               -- 支撑已破
SUPPORT_UNKNOWN              -- 无法判断
```

### 10.4 抬头锚点标注

字段：

```text
turn_anchor_label
manual_turn_quality_score: 0-100
manual_anchor_timing_score: 0-100
```

可选：

```text
NO_TURN_YET                  -- 尚未抬头
DAY1_VALID_TURN              -- 低点后第一天有效抬头
DAY2_VALID_TURN              -- 低点后第二天有效抬头
TOO_EARLY_TURN               -- 过早抬头，确认不足
TOO_LATE_TURN                -- 过晚抬头，已经走远
CONTINUOUS_REBOUND_7_8D      -- 低点后 7-8 天连续反弹
COMPRESSION_RESTART          -- 横盘压缩后突破重启
FALSE_TURN                   -- 假抬头
```

### 10.5 横盘压缩标注

字段：

```text
compression_tags
manual_compression_quality_score: 0-100
```

可多选：

```text
HAS_COMPRESSION              -- 存在横盘压缩
COMPRESSION_CLEAN            -- 压缩形态干净
COMPRESSION_TOO_SHORT        -- 压缩时间太短
COMPRESSION_TOO_WIDE         -- 压缩区间过宽
VOLUME_SHRINK_DURING_COMPRESSION -- 压缩期间缩量
BREAKOUT_AFTER_COMPRESSION   -- 压缩后突破
FAILED_COMPRESSION_BREAKOUT  -- 压缩突破失败
NO_COMPRESSION               -- 无压缩结构
```

### 10.6 量能结构标注

字段：

```text
volume_structure_tags
manual_volume_confirmation_score: 0-100
```

可多选：

```text
VALLEY_VOLUME_SHRINK         -- 低谷缩量
TURN_VOLUME_MODERATE         -- 抬头温和放量
TURN_VOLUME_STRONG           -- 抬头明显放量
VOLUME_FAKEOUT               -- 放量假突破
LOW_LIQUIDITY                -- 流动性不足
ABNORMAL_VOLUME              -- 异常量
NO_VOLUME_CONFIRMATION       -- 无量能确认
```

### 10.7 假反弹风险标注

字段：

```text
false_rebound_risk_tags
manual_false_rebound_risk_score: 0-100
```

可多选：

```text
ONE_DAY_PULSE                -- 一日脉冲
NO_FOLLOW_THROUGH            -- 无后续承接
UP_WITHOUT_VOLUME            -- 无量反弹
VOLUME_PRICE_DIVERGENCE      -- 量价背离
RESISTANCE_TOO_CLOSE         -- 上方压力太近
REBOUND_ALREADY_EXTENDED     -- 反弹已走远
SUPPORT_NOT_CONFIRMED        -- 支撑未确认
HIGH_FALSE_REBOUND_RISK      -- 高假反弹风险
```

### 10.8 周线背景标注

字段：

```text
weekly_context_tags
```

可多选：

```text
WEEKLY_DOWNTREND             -- 周线仍下跌
WEEKLY_BASING                -- 周线筑底
WEEKLY_TURNING_UP            -- 周线开始转强
WEEKLY_SUPPORT_INTACT        -- 周线支撑未破
WEEKLY_SUPPORT_BROKEN        -- 周线支撑破位
WEEKLY_CONTEXT_UNKNOWN       -- 周线背景不清晰
```

### 10.9 板块与市场环境标注

字段：

```text
context_tags
```

可多选：

```text
BOARD_RESONANCE              -- 板块共振
BOARD_WEAK                   -- 板块弱
STOCK_STRONGER_THAN_BOARD    -- 个股强于板块
BOARD_DRIVEN_ONLY            -- 主要由板块带动
MARKET_SUPPORTIVE            -- 市场环境支持
MARKET_RISK_OFF              -- 市场风险偏好弱
CONTEXT_UNKNOWN              -- 环境不明确
```

### 10.10 样本角色标注

字段：

```text
sample_role_label
```

可选：

```text
POSITIVE_VALLEY_PROTOTYPE    -- 正向低谷原型
POSITIVE_TURN_PROTOTYPE      -- 正向抬头原型
NEGATIVE_SAMPLE              -- 普通负样本
HARD_NEGATIVE                -- 高迷惑性负样本
FALSE_REBOUND_SAMPLE         -- 假反弹样本
MISSED_OPPORTUNITY           -- 漏选机会样本
CONTROL_GROUP                -- 对照组
RESEARCH_ONLY                -- 仅研究，不进入训练
NEEDS_REVIEW                 -- 需要复核
```

### 10.11 结果标签

字段：

```text
manual_outcome_label
```

可选：

```text
EFFECTIVE_TURN_SUCCESS       -- 有效抬头成功
FALSE_TURN                   -- 假抬头
LATE_BREAKOUT                -- 迟到突破
COMPRESSION_RESTART_SUCCESS  -- 横盘压缩重启成功
STRUCTURE_INVALIDATED        -- 结构失效
SUPPORT_BROKEN_AFTER_TURN    -- 抬头后支撑破位
PRICE_SUCCESS_BUT_UNTRADABLE -- 价格成功但不可交易
DATA_BLOCKED                 -- 数据缺失无法判断
```

注意：

```text
outcome_label 只能在 outcome_review 模式下打；as_of 模式不能提前知道未来结果。
```

### 10.12 标注置信度

字段：

```text
manual_label_confidence
manual_label_note
```

可选：

```text
HIGH
MEDIUM
LOW
```

---

## 11. 标注模式防未来函数

### 11.1 as_of 模式

只允许看到：

```text
低点日之前
扫描日之前
锚点日之前
决策时点之前
```

用途：

```text
判断当时模型是否应该识别。
```

可用于：

```text
训练低谷识别
训练抬头锚点识别
检验模型当时是否漏选
```

### 11.2 outcome_review 模式

允许看到：

```text
T+5
T+10
T+15
T+20
```

用途：

```text
打结果标签
打 hard negative
打 false rebound
打 missed opportunity
做失败归因
```

硬规则：

```text
outcome_review 下的标签不能直接作为当时模型输入特征，只能用于监督标签、结果归因、样本角色、后验研究。
```

---

## 12. 低谷图形标注相关库表

### 12.1 低谷图形样本表

```text
research_ambush.ambush_valley_chart_case_v1
```

```sql
chart_case_id
canonical_symbol
stock_name
scan_date
valley_watch_id
turn_anchor_id
effective_turn_pool_id
signal_id
valley_low_date
anchor_date
signal_date
chart_window_start_date
chart_window_end_date
chart_mode                  -- as_of / outcome_review
price_adjustment_mode        -- qfq/raw
source_data_version
source_coverage_snapshot_id
source_freshness_snapshot_id
auto_valley_maturity_score
auto_turn_quality_score
auto_false_rebound_risk_score
auto_pattern_similarity_score
case_status                  -- pending_labeling/labeled/review_required/approved/rejected
created_at
updated_at
```

### 12.2 人工标注主表

```text
research_ambush.ambush_valley_manual_label_v1
```

```sql
manual_label_id
chart_case_id
labeler_id
labeler_role                 -- researcher/operator/senior_reviewer
label_mode                   -- as_of/outcome_review
valley_shape_type
manual_valley_maturity_score
manual_turn_quality_score
manual_anchor_timing_score
manual_compression_quality_score
manual_volume_confirmation_score
manual_false_rebound_risk_score
turn_anchor_label
sample_role_label
manual_outcome_label
manual_label_confidence
manual_label_note
label_version
created_at
```

### 12.3 多选标签明细表

```text
research_ambush.ambush_valley_manual_label_tag_v1
```

```sql
manual_label_tag_id
manual_label_id
tag_group                    -- maturity/support/compression/volume/false_rebound/weekly/context
tag_code
tag_value                    -- true/false 或 severity
tag_note
created_at
```

多选项不建议全塞 JSON，单独明细表方便统计。

### 12.4 标注字典表

```text
research_ambush.ambush_valley_label_taxonomy_v1
```

```sql
taxonomy_id
tag_group
tag_code
tag_name
tag_description
allowed_label_mode           -- as_of/outcome_review/both
is_positive_signal
is_negative_signal
is_hard_negative_signal
is_training_eligible
enabled
created_at
```

作用：

```text
让 Codex 和前端知道每个勾选项是什么意思；后续新增标签不用改代码。
```

### 12.5 标注复核表

```text
research_ambush.ambush_valley_label_review_v1
```

```sql
review_id
chart_case_id
manual_label_id
reviewer_id
review_status                -- approved/rejected/needs_discussion
review_comment
final_sample_role_label
final_outcome_label
final_label_confidence
created_at
```

### 12.6 低谷图形样本库成员表

```text
research_ambush.ambush_valley_pattern_library_member_v1
```

```sql
library_member_id
chart_case_id
manual_label_id
library_role                 -- positive_prototype/hard_negative/missed_opportunity/control/research_only
pattern_family               -- v_left/sqrt_right/u_shape/box_bottom/compression_restart/false_rebound
training_split               -- train/validation/test/review_only
approved_by
approved_at
shape_signature_id           -- 数值形态签名 ID，占位字段
feature_snapshot_id          -- 对应 ambush_pattern_feature_snapshot
created_at
```

---

## 13. 页面操作流程

```text
1. 系统从 valley_watch_pool / effective_turn_pool / outcome_label 中生成待标注样本。
2. 人工进入低谷图形标注中心。
3. 选择 as_of 或 outcome_review 模式。
4. 查看 K 线、成交量、周线、自动分数、模型状态。
5. 勾选结构标签、风险标签、锚点标签、样本角色。
6. 保存 manual_label。
7. 若样本重要或存在分歧，进入 review。
8. 审核通过后，写入 pattern_library_member。
9. 后续研究任务读取 pattern library / hard negative library。
```

---

## 14. 标注结果如何反哺模型三

人工标注不能直接改模型参数，只能进入研究资产：

```text
1. positive valley prototype library
2. effective turn prototype library
3. hard negative library
4. false rebound library
5. missed opportunity library
6. compression restart library
7. control group library
```

后续通过研究中心验证：

```text
某类人工正样本是否真的成功率更高；
某类 hard negative 是否显著提高模型识别能力；
某类 compression restart 是否值得进入正式规则；
day1/day2 人工标注是否和模型自动 anchor 一致。
```

只有证据足够，才进入模型迭代建议。

---

## 15. 研究 API 设计

```text
GET  /research/ambush/healthz
GET  /research/ambush/readyz

POST /research/ambush/runs
GET  /research/ambush/runs/{research_run_id}
POST /research/ambush/runs/{research_run_id}/execute

POST /research/ambush/valley-pool/analyze
POST /research/ambush/turn-anchor/analyze
POST /research/ambush/transition-audit/analyze
POST /research/ambush/day1-day2/analyze
POST /research/ambush/late-rebound-rule/analyze
POST /research/ambush/compression-restart/analyze
POST /research/ambush/layers/analyze
POST /research/ambush/release-gate/analyze
POST /research/ambush/hard-negative/analyze
POST /research/ambush/missed-opportunity/analyze
POST /research/ambush/failure-attribution/analyze
POST /research/ambush/data-gap-impact/analyze

GET  /research/ambush/samples
GET  /research/ambush/valley-pool
GET  /research/ambush/turn-anchor
GET  /research/ambush/transitions
GET  /research/ambush/hard-negatives
GET  /research/ambush/missed-opportunities
GET  /research/ambush/evolution-metrics

GET  /research/ambush/valley-chart/cases
POST /research/ambush/valley-chart/cases
GET  /research/ambush/valley-chart/cases/{chart_case_id}
POST /research/ambush/valley-chart/cases/{chart_case_id}/labels
GET  /research/ambush/valley-chart/taxonomy
POST /research/ambush/valley-chart/reviews
POST /research/ambush/valley-chart/library-members
```

长任务必须异步执行。

---

## 16. 研究任务流程

```text
1. 创建 ambush_research_run。
2. 调用 source-data-service 做 coverage / freshness / preflight。
3. 选取 valley_watch / effective_turn / official_signal / rejected / missed_opportunity 样本。
4. 冻结 ambush_research_sample。
5. 读取 pattern_feature_snapshot。
6. 读取 valley_watch_pool。
7. 读取 effective_turn_anchor。
8. 读取 pool_transition_audit。
9. 读取 L2/L3/L4 confirmation。
10. 读取 release_gate_audit。
11. 读取 observation_path / outcome_label。
12. 执行具体研究任务。
13. 生成研究结果表。
14. 形成研究结论。
15. strong 以上结论进入人工审核。
16. 审核后才能形成生产模型迭代建议。
```

如果 source preflight 返回 blocked：

```text
研究任务必须标记 status = data_blocked，不能生成正式研究结论。
```

---

## 17. 第一阶段验收标准

模型三研究中心第一阶段必须能回答：

```text
1. 低谷观察池中高分样本是否更容易进入有效抬头池？
2. day1/day2 抬头规则是否提高了成功率？
3. day1 与 day2 谁更有效？
4. 低点后 7-8 天连续反弹剔除规则是否误伤有效样本？
5. 横盘压缩后突破重启规则是否有价值？
6. L2/L3/L4 哪一层真正提升成功率？
7. release_gate 是否挡掉了后续成功样本？
8. hard negative 的共同失败特征是什么？
9. 模型三漏选样本主要发生在哪一层？
10. 000759 这类样本为什么停留在 valley_watch 而没有进入 effective_turn_pool？
11. 某个 valley_watch 样本的 K 线是否能人工标记为真低谷？
12. 某个样本为什么是 hard negative？
13. day1/day2 抬头是否能被人工标注并和模型自动锚点对比？
14. as_of 标签和 outcome_review 标签是否严格隔离？
15. 标注后的样本是否能进入 pattern library 或 hard negative library？
```

如果这些问题回答不了，模型三研究中心不算完成。

---

## 18. 给 Codex 的硬性规则

后续落代码时必须写入 README / AGENTS：

```text
1. research_ambush 不允许直接调用任何外部 provider。
2. 所有研究样本必须绑定 source_data_version、model_version、feature_version。
3. 形态计算不得使用未来数据。
4. raw price 用于可交易和涨跌停；adjusted price 用于形态和历史结构。
5. 模型三成功标签必须区分 price_success、structure_success、tradability_success。
6. 低谷池、抬头池、release_gate 被挡样本都必须能进入研究。
7. hard negative 必须独立沉淀，不得混入普通失败。
8. missed opportunity 必须标记漏选发生阶段。
9. day1/day2、7-8 天连续反弹、横盘压缩重启规则必须可验证。
10. 研究结论不得直接修改生产模型参数。
11. 低谷图形标注必须区分 as_of 与 outcome_review 模式。
12. outcome_review 标签不得作为当时模型输入特征。
13. 多选标注项必须通过 taxonomy 表维护，不允许硬编码在前端。
14. 重要样本进入 pattern library 前必须经过 review。
15. 人工标注结果只能进入研究资产，不能直接写入 official signal。
```

---

## 19. 本阶段结论

模型三研究中心的核心是建立一套可解释、可验证、可反推的结构研究系统。

低谷图形标注中心必须作为模型三研究中心独立页面建设，它的核心价值是：

```text
把人工经验沉淀为可追溯、可复核、可训练、可研究的结构化样本库。
```

后续模型三能不能持续变强，很大程度取决于这套标注体系是否扎实。


---

# V2 动态特征增强：潜伏抬头模型研究中心改造

## 1. V2 新增研究目标

潜伏抬头模型 V1 已覆盖低谷池、有效抬头锚点、day1/day2、连续反弹剔除、横盘压缩重启、L2/L3/L4、hard negative、missed opportunity 和低谷图形标注中心。引入 dynamic-feature-service 后，模型三研究中心要进一步研究：

```text
1. 日线有效抬头是否需要分时微确认？
2. 低谷后盘中微调回踩不破，是否显著提高成功率？
3. 横盘压缩后，分时突破是否能确认重启有效？
4. 假抬头样本是否有盘中风险预警？
5. 动态特征是否能区分真抬头和 hard negative？
6. 低谷图形标注中心是否需要展示分时图、VWAP、动态特征和买点窗口？
7. 000759 类案例是否能被结构化沉淀为“低谷 + 分时微调回踩 + 再上攻”的研究样本？
```

模型三动态研究的核心不是变成分时追涨，而是：

```text
用盘中行为验证日线低谷抬头结构，减少假抬头，改善买点友好度。
```

---

## 2. 新增动态特征依赖

优先 bundle：

```text
ambush_micro_turn_bundle_v1
buy_point_intraday_bundle_v1
```

重点 feature：

```text
intraday_anchor_confirmation_score
support_retest_quality_score
post_pullback_reattack_score
compression_breakout_intraday_flag
intraday_breakout_quality_score
breakout_fade_risk_score
volume_quality_score
intraday_false_rebound_risk_score
morning_strength_afternoon_fade_flag
tradable_entry_window_quality_score
limit_up_tradability_score
```

---

## 3. 新增表：分时微确认研究

```sql
CREATE TABLE IF NOT EXISTS research_ambush.ambush_micro_turn_confirmation_v1 (
    micro_confirmation_id          VARCHAR(64) PRIMARY KEY,
    research_run_id                VARCHAR(64) NOT NULL,

    turn_anchor_id                 VARCHAR(64),
    effective_turn_pool_id         VARCHAR(64),
    signal_id                      VARCHAR(64),
    canonical_symbol               VARCHAR(32),
    anchor_date                    DATE,

    micro_turn_confirmation_bucket VARCHAR(32), -- strong/medium/weak/none/missing
    as_of_time_policy              VARCHAR(64) NOT NULL,
    sample_count                   INT NOT NULL,

    success_rate_t5                NUMERIC(12,6),
    success_rate_t10               NUMERIC(12,6),
    success_rate_t15               NUMERIC(12,6),
    false_turn_rate                NUMERIC(12,6),
    avg_max_return                 NUMERIC(12,6),
    avg_max_drawdown               NUMERIC(12,6),

    intraday_anchor_confirmation_score_avg NUMERIC(12,6),
    support_retest_quality_score_avg       NUMERIC(12,6),
    volume_quality_score_avg               NUMERIC(12,6),
    false_rebound_risk_score_avg           NUMERIC(12,6),

    micro_confirmation_lift_score  NUMERIC(12,6),
    confidence_level               VARCHAR(32),
    created_at                     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

---

## 4. 新增表：分时回踩支撑研究

```sql
CREATE TABLE IF NOT EXISTS research_ambush.ambush_intraday_support_retest_analysis_v1 (
    support_retest_analysis_id     VARCHAR(64) PRIMARY KEY,
    research_run_id                VARCHAR(64) NOT NULL,

    support_retest_bucket          VARCHAR(32), -- pass/fail/unknown/missing
    support_reference_type         VARCHAR(64), -- vwap/open_price/valley_low/anchor_low/previous_low
    sample_count                   INT NOT NULL,

    success_rate_t5                NUMERIC(12,6),
    success_rate_t10               NUMERIC(12,6),
    success_rate_t15               NUMERIC(12,6),
    false_turn_rate                NUMERIC(12,6),
    structure_invalidated_rate     NUMERIC(12,6),

    avg_pullback_depth_pct         NUMERIC(12,6),
    avg_rebound_after_pullback_pct NUMERIC(12,6),
    avg_support_retest_quality_score NUMERIC(12,6),

    support_retest_lift_score      NUMERIC(12,6),
    confidence_level               VARCHAR(32),
    created_at                     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

### 用途

这张表专门服务于 000759 类案例：

```text
低谷已经成熟；
模型未进入 effective_turn_pool；
次日上午出现微调回踩；
回踩不破后再上攻；
最终涨停。
```

研究中心需要能证明：

```text
这种分时回踩不破是否应该成为模型三有效抬头微确认规则。
```

---

## 5. 新增表：横盘压缩分时突破研究

```sql
CREATE TABLE IF NOT EXISTS research_ambush.ambush_compression_intraday_breakout_v1 (
    compression_intraday_id        VARCHAR(64) PRIMARY KEY,
    research_run_id                VARCHAR(64) NOT NULL,

    compression_window_bucket      VARCHAR(32), -- 3_5d/6_10d/11_20d/20d_plus
    breakout_quality_bucket        VARCHAR(32), -- strong/medium/weak/failed

    sample_count                   INT NOT NULL,
    breakout_success_rate          NUMERIC(12,6),
    false_breakout_rate            NUMERIC(12,6),
    avg_break_hold_minutes         NUMERIC(12,6),
    avg_breakout_retest_pass_rate  NUMERIC(12,6),
    avg_breakout_fade_risk_score   NUMERIC(12,6),

    recommended_restart_rule_action VARCHAR(128), -- keep/tighten/loosen/research_only
    confidence_level               VARCHAR(32),
    created_at                     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

---

## 6. 新增表：假抬头动态预警研究

```sql
CREATE TABLE IF NOT EXISTS research_ambush.ambush_intraday_false_turn_warning_v1 (
    false_turn_warning_id          VARCHAR(64) PRIMARY KEY,
    research_run_id                VARCHAR(64) NOT NULL,

    signal_id                      VARCHAR(64),
    turn_anchor_id                 VARCHAR(64),
    canonical_symbol               VARCHAR(32),

    false_turn_label               VARCHAR(64),
    intraday_warning_exists        BOOLEAN,

    intraday_false_rebound_risk_score NUMERIC(12,6),
    breakout_fade_risk_score       NUMERIC(12,6),
    volume_fakeout_risk            NUMERIC(12,6),
    morning_strength_afternoon_fade_flag BOOLEAN,
    price_below_vwap_ratio         NUMERIC(12,6),

    warning_lead_time_minutes      INT,
    recommended_negative_rule      VARCHAR(128),
    confidence_level               VARCHAR(32),
    created_at                     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

---

## 7. 新增表：hard negative 动态可分离性研究

```sql
CREATE TABLE IF NOT EXISTS research_ambush.ambush_hard_negative_dynamic_separability_v1 (
    separability_id                VARCHAR(64) PRIMARY KEY,
    research_run_id                VARCHAR(64) NOT NULL,

    hard_negative_type             VARCHAR(64), -- false_rebound/support_break_after_turn/volume_fakeout/sector_fake_resonance
    sample_count_positive          INT NOT NULL,
    sample_count_hard_negative     INT NOT NULL,

    feature_bundle_code            VARCHAR(128),
    feature_name                   VARCHAR(128),
    positive_avg_value             NUMERIC(18,6),
    hard_negative_avg_value        NUMERIC(18,6),
    feature_separation_score       NUMERIC(12,6),

    recommended_rule               VARCHAR(128),
    confidence_level               VARCHAR(32),
    created_at                     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

### 研究价值

模型三最容易失败的地方，是 hard negative：

```text
看起来像低谷抬头；
数值上也接近正样本；
但后续是假反弹、支撑破位或冲高回落。
```

动态可分离性研究要回答：

```text
分时承接质量、回踩支撑、突破后保持率、放量后价格保持率，是否能把真抬头和 hard negative 分开？
```

---

## 8. 低谷图形标注中心 V2 改造

低谷图形标注中心新增分时层。页面结构调整为：

```text
左侧：样本队列
中间上：日 K + 成交量 + 周线
中间下：锚点日/次日分时图
右侧上：自动日线特征 + 动态特征
右侧中：人工结构标签 + 分时标签
右侧下：outcome_review 标签 + 复核状态
```

### 新增图层

```text
1. 锚点日分时图
2. 次日分时图
3. VWAP 线
4. 回踩支撑线
5. 分时突破线
6. 涨停触及时间
7. 炸板次数
8. 买点窗口
9. dynamic_feature_snapshot 对应分数
```

### 新增人工打标维度

```text
INTRADAY_ACCEPTANCE_STRONG        -- 分时承接强
INTRADAY_ACCEPTANCE_WEAK          -- 分时承接弱
HIGH_OPEN_LOW_WALK                -- 高开低走
VWAP_SUPPORT_VALID                -- VWAP 支撑有效
VWAP_SUPPORT_BROKEN               -- VWAP 支撑破坏
PULLBACK_SUPPORT_HOLD             -- 回踩支撑不破
PULLBACK_SUPPORT_BROKEN           -- 回踩支撑破位
PULLBACK_TOO_DEEP                 -- 回踩过深
PULLBACK_REBOUND_VALID            -- 回踩后再上攻有效
INTRADAY_BREAKOUT_VALID           -- 分时突破有效
INTRADAY_BREAKOUT_FAILED          -- 分时突破失败
BREAKOUT_RETEST_PASS              -- 突破后回踩确认
BREAKOUT_FADE_FAST                -- 突破后快速回落
ONE_PULSE_REBOUND                 -- 一日/一波脉冲
VOLUME_FAKEOUT                    -- 放量假突破
MORNING_STRONG_AFTERNOON_WEAK     -- 早强午弱
NO_FOLLOW_THROUGH                 -- 无后续承接
ENTRY_WINDOW_CLEAR                -- 买点窗口清晰
ENTRY_WINDOW_TOO_SHORT            -- 买点窗口过短
ENTRY_PRICE_TOO_HIGH              -- 买点偏高
PRICE_SUCCESS_BUT_UNTRADABLE      -- 价格成功但不可交易
```

### 标注隔离规则

```text
as_of 模式：只能标注当时可见的分时结构，不能看未来 outcome。
outcome_review 模式：可以标注假抬头、hard negative、迟到突破、买点是否友好。
```

---

## 9. 模型三新增研究指标

```text
micro_turn_confirmation_rate
support_retest_success_lift
compression_breakout_intraday_success_rate
intraday_false_turn_warning_rate
day1_day2_micro_confirmation_lift
hard_negative_dynamic_separability
tradable_entry_window_quality_avg
price_success_but_untradable_rate
```

---

## 10. 模型三研究任务流程 V2

```text
1. 创建 ambush_research_run。
2. 冻结 valley_watch / turn_anchor / effective_turn_pool / official_signal / outcome 样本。
3. 读取 ambush_micro_turn_bundle_v1 的 production dynamic snapshot。
4. 对缺失 production snapshot 的历史样本创建 research_replay，并标记 replay_only。
5. 执行分时微确认研究。
6. 执行分时回踩支撑研究。
7. 执行压缩突破分时研究。
8. 执行假抬头动态预警研究。
9. 执行 hard negative 动态可分离性研究。
10. 低谷图形标注中心展示动态特征和分时图。
11. 将动态特征结论写入 research_dynamic。
12. 生成 ambush_research_finding。
```

---

## 11. V2 验收标准

潜伏抬头模型 V2 研究中心必须能回答：

```text
1. day1/day2 抬头样本中，分时微确认强弱是否影响成功率？
2. 回踩支撑不破是否显著降低 false_turn_rate？
3. 横盘压缩突破是否需要分时突破质量确认？
4. 假抬头样本是否能被盘中假反弹风险提前预警？
5. hard negative 和正样本在哪些动态特征上最可分？
6. 000759 类“低谷 + 微调回踩 + 再上攻”能否被标注和复盘？
7. 价格成功但不可交易的比例是多少？
8. 哪些动态特征可以进入 production_candidate？
```
