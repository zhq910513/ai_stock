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

# 热点模型研究中心 V2 动态增强版

# 神策中心：热点模型研究中心设计文档 v1

> 文件名：`hot_model_research_center_design_v1.md`  
> 适用模型：模型一 `hot_candidates` / 热点模型  
> 适用阶段：研究中心设计阶段，暂不落代码  
> 文档状态：设计锁定候选  
> 重要边界：本文只设计热点模型研究中心，不设计候选记忆模型、潜伏抬头模型，也不设计研究中心总览。三个模型全部设计完成后，再统一设计研究中心总览。

---

## 0. 设计结论

热点模型研究中心不是“推荐结果展示页”，也不是普通收益率回测页。它的核心目标是研究：

1. 同花顺 teacher prior 是否具备短窗口预测力；
2. 本地行情、板块、资金、市场环境、事件风险等证据是否真的提升 teacher prior；
3. 模型最终排序 `final_rank` 是否优于 teacher 原始排序 `teacher_rank`；
4. Top1 输给 Top2 / Top3 的原因是什么；
5. 热点失败到底是 teacher prior 噪声、本地证据误判、市场环境拖累、板块失败、资金反转、事件风险、可交易失败，还是数据缺口误导；
6. 哪些研究结论可以进入人工审核和后续模型迭代。

最终研究链路应为：

```text
teacher prior 输入
-> 本地证据确认
-> release gate 审计
-> 排序快照
-> official signal
-> T+1/T+3/T+5 观察
-> outcome 标签
-> teacher prior 有效性研究
-> 本地证据增益研究
-> 排名后悔分析
-> 失败归因
-> 数据缺口影响研究
-> 研究结论
-> 人工审核
-> 后续模型迭代
```

---

## 1. 热点模型研究中心定位

### 1.1 研究中心不是生产模型

热点模型生产服务负责：

```text
候选接收
source preflight
特征计算
release gate
排序
official signal
观察链路
结果标签
```

热点模型研究中心负责：

```text
研究 teacher prior 是否有效
研究本地证据是否有增益
研究排序是否改善
研究失败原因
研究数据缺口影响
沉淀样本、结论、人工审核建议
```

### 1.2 研究中心禁止事项

研究中心禁止：

```text
1. 直接调用 BaoStock / AKShare / Tushare / EastMoney / 同花顺接口；
2. 直接读取 raw 原接口表作为研究事实来源；
3. 直接写入 official_signal；
4. 直接修改热点模型生产参数；
5. 使用缺口数据生成正式研究结论；
6. 把 T+10 / T+20 才上涨的样本算成热点模型短窗口成功；
7. 把一字涨停、无合理成交窗口的样本简单算成模型高质量成功；
8. 把数据缺失导致的失败直接归因为模型失败。
```

### 1.3 研究中心允许事项

研究中心允许：

```text
1. 读取 source-data-service 的 source 标准事实表；
2. 读取 hot-candidates-service 产出的 decision_hot 生产快照；
3. 读取数据源服务的 coverage / freshness / lineage / preflight 结果；
4. 固化热点模型研究样本；
5. 计算短窗口兑现结果；
6. 分析 teacher prior 预测力；
7. 分析 local evidence 是否提升排序；
8. 分析 Top1 / Top2 / Top3 排名后悔；
9. 分析失败归因；
10. 形成研究结论和模型迭代建议。
```

---

## 2. 研究主线

热点模型研究中心第一版拆成 8 条主线：

```text
1. 榜单批次研究；
2. teacher prior 有效性研究；
3. 本地证据增益研究；
4. 短窗口兑现研究；
5. 排名后悔分析；
6. 失败归因研究；
7. 数据缺口影响研究；
8. 研究结论与模型成长建议。
```

这 8 条主线共同回答一个问题：

```text
热点模型是否比单纯照搬同花顺榜单更有研究价值？
```

---

## 3. 研究口径

### 3.1 热点模型只研究短窗口

建议固定观察窗口：

```text
T+1：验证次日兑现能力；
T+3：验证短线热点延续能力；
T+5：验证热点窗口最大有效期。
```

T+10 以后才上涨的样本不得计为热点模型短窗口成功，只能标记为：

```text
late_success_after_hot_window
```

### 3.2 成功不能只看最高收益

热点模型成功至少分三层：

```text
price_success：价格层成功；
tradability_success：可交易层成功；
execution_friendly：存在合理可交易窗口。
```

若样本价格上涨，但一字板不可交易，则不得简单算成高质量成功。应标记：

```text
price_success_but_execution_unfriendly
```

### 3.3 排名后悔必须同批次比较

排名后悔分析必须满足：

```text
同一个 teacher_prior_batch_id；
同一个 batch_date；
同一个 model_version；
同一个 score_formula_version；
同一个 release_gate_version；
同一个 source_data_version；
同一个 evaluation_window。
```

禁止跨日期、跨版本、跨市场环境随意比较 Top1 / Top2。

---

## 4. 数据链路

热点模型研究中心数据链路如下：

```text
source.ths_hot_candidate_prior_v1
source.daily_bar_v1
source.adjusted_daily_bar_v1
source.trade_status_v1
source.limit_price_v1
source.index_daily_bar_v1
source.market_breadth_v1
source.stock_board_membership_v1
source.board_daily_bar_v1
source.stock_moneyflow_daily_v1
source.event_news_v1
        ↓
decision_hot.hot_candidate_snapshot_v1
decision_hot.hot_feature_snapshot_v1
decision_hot.hot_score_snapshot_v1
decision_hot.hot_release_gate_audit_v1
decision_hot.hot_ranking_snapshot_v1
decision_hot.hot_official_signal_v1
decision_hot.hot_observation_path_v1
decision_hot.hot_outcome_label_v1
        ↓
research_hot.hot_research_run_v1
research_hot.hot_research_sample_v1
research_hot.hot_batch_effectiveness_v1
research_hot.hot_teacher_prior_analysis_v1
research_hot.hot_local_evidence_lift_v1
research_hot.hot_short_window_effectiveness_v1
research_hot.hot_rank_regret_pair_v1
research_hot.hot_failure_attribution_v1
research_hot.hot_data_gap_impact_v1
research_hot.hot_research_finding_v1
```

硬规则：

```text
research_hot 不直接依赖 raw 原接口表；
research_hot 依赖 source 标准事实表和 decision_hot 生产快照；
需要追溯字段来源时，通过 source_lineage / source_coverage / source_freshness 查询。
```

---

## 5. source 字段依赖设计

> 说明：以下字段是热点模型研究中心的字段契约。若真实库表字段不同，Codex 后续应按注释映射到真实字段，不得删除字段含义。

### 5.1 teacher prior 数据

来源建议：

```text
source.ths_hot_candidate_prior_v1
```

字段设计：

```sql
teacher_prior_id              -- 同花顺候选榜单原始记录唯一 ID
teacher_prior_batch_id        -- 同一批次榜单 ID
batch_date                    -- 榜单所属交易日
batch_time                    -- 榜单生成或导入时间
available_at                  -- 榜单在系统中可用于模型判断的时间，防止未来函数
captured_at                   -- 系统采集/导入时间

raw_symbol                    -- 原始股票代码，例如 000759
canonical_symbol              -- 系统统一股票代码，例如 000759.SZ
stock_name                    -- 股票名称

teacher_rank                  -- 同花顺原始排名，P0 字段
teacher_score                 -- 同花顺原始分数；如果真实字段不是 score，Codex 映射真实字段
teacher_probability           -- 同花顺给出的概率；如果没有，保留 null
teacher_reason_raw            -- 原始推荐理由文本
teacher_tags_raw             -- 原始标签 JSON；如字段真实名称为 tags_raw，由 Codex 映射

source_file_name              -- 人工导入文件名
source_file_hash              -- 文件 hash，用于幂等
raw_row_json                  -- 原始行 JSON
data_quality_status           -- passed/degraded/blocked
created_at
```

研究用途：

```text
teacher_rank 用于验证同花顺榜单排序是否有效；
teacher_score / teacher_probability 用于验证 teacher prior 强弱；
available_at 用于防止未来函数；
teacher_reason_raw 用于失败归因和研究解释。
```

### 5.2 行情数据

来源建议：

```text
source.daily_bar_v1
```

字段设计：

```sql
canonical_symbol              -- 统一股票代码
trade_date                    -- 交易日
open_price                    -- 未复权开盘价，用于可交易评估
high_price                    -- 未复权最高价，用于窗口最大收益
low_price                     -- 未复权最低价，用于最大回撤
close_price                   -- 未复权收盘价
pre_close_price               -- 昨收价
volume                        -- 成交量，单位必须在字段合同中定义
amount                        -- 成交额，单位必须统一
turnover_rate                 -- 换手率；如来源缺失，Codex 后续映射
pct_chg                       -- 当日涨跌幅
source_quality_status         -- passed/degraded/suspect
source_build_batch_id         -- source 构建批次
lineage_id                    -- 血缘 ID
```

用途：

```text
T-1/T-3/T-5/T-10 用于判断推荐前状态；
T+1/T+3/T+5 用于观察结果；
未复权价格用于真实可交易与收益评估。
```

### 5.3 复权行情

来源建议：

```text
source.adjusted_daily_bar_v1
```

字段设计：

```sql
canonical_symbol
trade_date
adjustment_mode               -- qfq/hfq/raw，热点模型第一版建议 qfq
adjusted_open
adjusted_high
adjusted_low
adjusted_close
source_quality_status
source_build_batch_id
lineage_id
```

用途：

```text
计算历史动量、均线、相对位置、波动率；
不用于真实成交判断。
```

### 5.4 交易状态

来源建议：

```text
source.trade_status_v1
```

字段设计：

```sql
canonical_symbol
trade_date
is_tradable                   -- 是否可交易
is_suspended                  -- 是否停牌
is_st                         -- 是否 ST
is_delisting_risk             -- 是否存在退市风险
security_type                 -- 股票/指数/ETF/其他
status_quality                -- passed/degraded/suspect
```

用途：

```text
release_gate P0 过滤；
停牌、ST、退市风险样本不得进入 official signal。
```

### 5.5 涨跌停与可交易状态

来源建议：

```text
source.limit_price_v1
source.limit_event_v1
```

字段设计：

```sql
canonical_symbol
trade_date
up_limit_price                -- 涨停价
down_limit_price              -- 跌停价
limit_rule                    -- 10pct/20pct/5pct_st/other
is_limit_up                   -- 是否涨停
is_limit_down                 -- 是否跌停
is_one_word_limit             -- 是否一字板；若无盘口数据，先用 open=high=low=close=up_limit 近似并加注释
limit_open_status             -- opened/sealed/one_word/unknown，占位字段
distance_to_up_limit          -- 距涨停价比例
tradability_state             -- tradable/unfriendly/blocked/unknown
```

用途：

```text
识别“涨了但买不到”的样本；
避免把一字涨停误算为模型高质量成功；
区分价格成功和可交易成功。
```

### 5.6 市场环境

来源建议：

```text
source.index_daily_bar_v1
source.market_breadth_v1
source.market_regime_v1
```

字段设计：

```sql
index_code
trade_date
index_close_price
index_pct_chg
index_return_3d
index_return_5d

market_up_count               -- 上涨家数
market_down_count             -- 下跌家数
limit_up_count                -- 涨停家数
limit_down_count              -- 跌停家数
market_breadth_up_ratio       -- 上涨家数占比
risk_appetite_score           -- 市场风险偏好分，占位字段
market_regime                 -- strong/weak/choppy/risk_off/unknown
```

用途：

```text
区分个股失败和市场环境拖累；
研究弱市是否需要提高 release_gate 或减少发布数量。
```

### 5.7 板块共振

来源建议：

```text
source.stock_board_membership_v1
source.board_daily_bar_v1
```

字段设计：

```sql
canonical_symbol
trade_date
board_code
board_name
board_type                    -- industry/concept/theme
membership_time_mode          -- historical/current_snapshot，必须标记是否历史成份

board_return_1d
board_return_3d
board_rank_percentile
board_up_member_ratio
board_limit_up_count
stock_vs_board_relative_strength
```

用途：

```text
研究热点是否有板块共振；
研究单股热点与板块热点的兑现差异；
验证板块强度是否能修正 teacher_rank。
```

### 5.8 资金流

来源建议：

```text
source.stock_moneyflow_daily_v1
source.stock_moneyflow_snapshot_v1
```

字段设计：

```sql
canonical_symbol
trade_date
moneyflow_provider
net_moneyflow_amount
large_order_net_flow          -- 占位字段，按真实 provider 映射
moneyflow_rank_percentile
moneyflow_continuity_3d
moneyflow_reversal_flag
moneyflow_quality_status
```

第一阶段建议：

```text
资金流为 P1；
不阻断模型运行；
缺失时降低 ranking_confidence，并进入 data_gap_impact 研究。
```

### 5.9 新闻事件

来源建议：

```text
source.event_news_v1
source.announcement_event_v1
```

字段设计：

```sql
canonical_symbol
event_id
event_date
published_at
available_at                  -- 防止未来函数
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
解释异常失败或异常成功；
重大负面事件进入 release_gate 风险项；
盘后才可见的公告不能影响盘前决策。
```

---

## 6. decision_hot 生产快照设计

### 6.1 候选快照表

表名：

```text
decision_hot.hot_candidate_snapshot_v1
```

字段：

```sql
candidate_snapshot_id
teacher_prior_batch_id
batch_date
decision_time

canonical_symbol
stock_name

teacher_rank
teacher_score
teacher_probability

source_preflight_status        -- passed/degraded/blocked
source_coverage_snapshot_id
source_freshness_snapshot_id
data_gap_fields_json           -- 缺失字段列表

candidate_status               -- normalized/rejected/eligible
candidate_reject_reason        -- symbol_mapping_failed/suspended/st/data_blocked/other

created_at
```

作用：

```text
记录 teacher 候选进入模型前的标准化状态；
支持研究 release_gate rejected、data_blocked、symbol mapping failed。
```

### 6.2 特征快照表

表名：

```text
decision_hot.hot_feature_snapshot_v1
```

建议采用长表，不建议第一版做超宽表。

字段：

```sql
feature_snapshot_id
candidate_snapshot_id
canonical_symbol
batch_date
decision_time

feature_group                  -- teacher_prior/price_momentum/liquidity/tradability/sector/market/moneyflow/event_risk
feature_name                   -- 具体特征名
feature_value_numeric          -- 数值型特征
feature_value_text             -- 文本型特征
feature_value_json             -- JSON 型特征
feature_unit                   -- %, amount, score, rank, flag

source_table_name              -- 来源 source 表
source_field_name              -- 来源字段
source_lineage_id              -- 可选血缘
available_at                   -- 数据可见时间

feature_version
quality_status                 -- passed/degraded/suspect/missing
comment                        -- Codex 注释：说明金融含义
```

示例：

```text
feature_group = price_momentum
feature_name = return_3d
comment = 推荐日前 3 个交易日累计涨跌幅，用于衡量短线热度，不能使用推荐日之后数据。
```

```text
feature_group = sector
feature_name = board_up_member_ratio
comment = 候选股所属板块内上涨股票占比，用于衡量板块共振强度。
```

```text
feature_group = moneyflow
feature_name = large_order_net_flow
comment = 大单/超大单净流入，占位字段，后续按 provider 字段映射。
```

### 6.3 评分快照表

表名：

```text
decision_hot.hot_score_snapshot_v1
```

字段：

```sql
score_snapshot_id
candidate_snapshot_id
canonical_symbol
batch_date
decision_time

teacher_prior_component
local_confirmation_component
price_momentum_component
liquidity_component
tradability_component
sector_resonance_component
market_regime_component
moneyflow_component
event_risk_component

risk_penalty_component
data_gap_penalty_component
final_score

score_formula_version
component_weight_json
score_explain_json
created_at
```

硬规则：

```text
component 可以先作为研究字段存在；
每个 component 的权重不能凭感觉拍死；
必须由研究中心验证后才能进入正式公式版本。
```

### 6.4 release gate 审计表

表名：

```text
decision_hot.hot_release_gate_audit_v1
```

字段：

```sql
gate_audit_id
candidate_snapshot_id
canonical_symbol
batch_date
decision_time

gate_name                      -- teacher_prior_exists/data_preflight/tradable/non_st/non_suspended/risk_event/market_extreme
gate_result                    -- pass/fail/warn
blocking_level                 -- P0/P1/P2
gate_reason_code
gate_reason_text
evidence_json
created_at
```

用途：

```text
研究 release_gate 是否过严；
研究被挡掉的样本后续是否上涨；
挖掘 missed opportunity。
```

### 6.5 排序快照表

表名：

```text
decision_hot.hot_ranking_snapshot_v1
```

字段：

```sql
ranking_snapshot_id
teacher_prior_batch_id
batch_date
ranking_version

candidate_snapshot_id
canonical_symbol

teacher_rank
teacher_score
local_score
risk_penalty_score
data_gap_penalty_score
final_score
final_rank
rank_change_from_teacher       -- final_rank - teacher_rank，负数表示被上调

ranking_confidence             -- high/medium/low
ranking_confidence_reason
top_bucket                     -- top1/top3/top5/top10/other

created_at
```

这是排名后悔分析的核心表。

### 6.6 正式信号表

表名：

```text
decision_hot.hot_official_signal_v1
```

字段：

```sql
signal_id
teacher_prior_batch_id
candidate_snapshot_id
ranking_snapshot_id

canonical_symbol
signal_date
decision_time

teacher_rank
final_rank
final_score
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

只有：

```text
signal_status = official
```

才进入正式成功率统计。

---

## 7. 观察与标签设计

### 7.1 观察路径表

表名：

```text
decision_hot.hot_observation_path_v1
```

字段：

```sql
observation_id
signal_id
canonical_symbol
signal_date
trade_date
day_offset                    -- T+1/T+2/T+3/T+5

benchmark_buy_price
benchmark_buy_price_method    -- next_day_high_low_mid_research_v1 / buy_point_service_vX
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

is_limit_up
is_limit_down
is_one_word_limit
tradability_state

market_regime
board_return_1d
stock_vs_board_relative_strength

data_quality_status
created_at
```

第一版 `benchmark_buy_price_method` 可用：

```text
next_day_high_low_mid_research_v1
```

含义：

```text
入选批次日期的下一个交易日的（最高价 + 最低价）/2。
```

注意：这是研究评估基准，不是交易建议。

### 7.2 结果标签表

表名：

```text
decision_hot.hot_outcome_label_v1
```

字段：

```sql
outcome_label_id
signal_id
canonical_symbol
signal_date

evaluation_window             -- T1/T3/T5
window_start_date
window_end_date

benchmark_buy_price
max_return
close_return
max_drawdown
hit_target
target_return_threshold       -- 占位字段，后续研究配置，例如 3%、5%
hit_target_date
days_to_hit

execution_friendly            -- 是否存在合理可交易窗口
price_success
structure_success             -- 热点结构是否延续，占位字段
tradability_success

outcome_label                  -- next_day_hit/short_window_hit/short_window_failed/late_success_after_hot_window/execution_unfriendly
label_reason
label_version
created_at
```

成功标签必须区分：

```text
价格成功；
可交易成功；
热点窗口内成功；
迟到成功。
```

---

## 8. research_hot 表设计

### 8.1 研究任务表

表名：

```text
research_hot.hot_research_run_v1
```

字段：

```sql
research_run_id
research_type                 -- batch_effectiveness/teacher_prior/local_lift/rank_regret/failure_attribution/data_gap_impact
research_name
model_code                    -- 固定 hot_candidates
model_version
feature_version
score_formula_version
release_gate_version
source_data_version

sample_start_date
sample_end_date
evaluation_window
status                        -- created/running/succeeded/failed/data_blocked
created_by
created_at
started_at
finished_at
comment
```

用途：

```text
每一次研究都必须有任务 ID；
研究结论不能脱离任务上下文。
```

### 8.2 研究样本表

表名：

```text
research_hot.hot_research_sample_v1
```

字段：

```sql
research_sample_id
research_run_id

sample_origin                 -- official_signal/release_gate_rejected/near_miss/missed_opportunity/control_group
sample_role                   -- positive/negative/hard_negative/late_success/rank_regret_candidate/data_blocked_case

signal_id
candidate_snapshot_id
ranking_snapshot_id

canonical_symbol
signal_date
decision_time

teacher_rank
final_rank
teacher_score
final_score

model_version
feature_version
score_formula_version
release_gate_version
source_data_version

source_coverage_snapshot_id
source_freshness_snapshot_id
source_quality_status

outcome_label
attribution_status             -- pending/done/needs_manual_review
created_at
```

研究样本必须支持非 official_signal。否则研究不到：

```text
release_gate 错杀；
near miss；
missed opportunity；
control group。
```

### 8.3 榜单批次效果表

表名：

```text
research_hot.hot_batch_effectiveness_v1
```

字段：

```sql
batch_effectiveness_id
research_run_id
teacher_prior_batch_id
batch_date

sample_count
official_signal_count
blocked_count
research_only_count

teacher_top1_hit_rate_t1
teacher_top3_hit_rate_t3
teacher_top5_hit_rate_t5

final_top1_hit_rate_t1
final_top3_hit_rate_t3
final_top5_hit_rate_t5

teacher_top1_avg_max_return
final_top1_avg_max_return
teacher_top5_avg_max_drawdown
final_top5_avg_max_drawdown

rank_improvement_score         -- final 排序相对 teacher 排序的改善分，占位字段
rank_regret_rate
data_gap_rate

market_regime
p0_coverage_rate
p1_coverage_rate
created_at
```

研究问题：

```text
final_rank 是否优于 teacher_rank？
本地证据有没有产生真实增益？
```

### 8.4 teacher prior 有效性表

表名：

```text
research_hot.hot_teacher_prior_analysis_v1
```

字段：

```sql
teacher_analysis_id
research_run_id
analysis_window               -- rolling_20d/rolling_60d/custom
rank_bucket                   -- top1/top2_3/top4_5/top6_10/other

sample_count
hit_rate_t1
hit_rate_t3
hit_rate_t5
avg_max_return_t3
median_max_return_t3
avg_max_drawdown_t5
late_success_rate
failure_rate

rank_monotonicity_score        -- teacher rank 分桶是否呈单调性，占位字段
teacher_predictive_power_score -- teacher prior 预测力综合分，占位字段
confidence_level              -- low/medium/high

created_at
```

研究判断：

```text
如果 teacher_rank 分桶表现不单调，teacher_rank 不应被高权重信任；
如果 Top1 长期不优于 Top2-5，排序逻辑必须调整。
```

### 8.5 本地证据增益表

表名：

```text
research_hot.hot_local_evidence_lift_v1
```

字段：

```sql
lift_id
research_run_id
analysis_window

teacher_strength_bucket        -- teacher_high/teacher_mid/teacher_low
local_evidence_bucket          -- local_high/local_mid/local_low
combined_bucket                -- teacher_high_local_high 等

sample_count
hit_rate_t3
hit_rate_t5
avg_max_return
avg_max_drawdown
rank_regret_rate
failure_rate

local_lift_vs_teacher_only     -- 本地证据相对 teacher-only 的提升，占位字段
evidence_quality_status        -- full_data/degraded/missing_key_fields
created_at
```

四象限研究：

```text
teacher_high_local_high：老师强，本地也强，理论最优；
teacher_high_local_low：老师强，本地弱，重点观察是否容易失败；
teacher_low_local_high：老师弱，本地强，重点观察是否被低估；
teacher_low_local_low：双弱，理论最弱。
```

这张表证明热点模型有没有独立价值。

### 8.6 短窗口兑现表

表名：

```text
research_hot.hot_short_window_effectiveness_v1
```

字段：

```sql
effectiveness_id
research_run_id
evaluation_window              -- T1/T3/T5

sample_count
valid_sample_count
excluded_sample_count
excluded_reason_json

hit_rate
avg_max_return
median_max_return
avg_close_return
avg_max_drawdown
avg_days_to_hit

execution_friendly_rate
price_success_rate
tradability_success_rate

market_regime
confidence_level
created_at
```

用途：

```text
统一沉淀热点模型短窗口兑现能力；
研究中心总览页未来可以读取其中的模型级指标，但不展示个股。
```

### 8.7 排名后悔样本对表

表名：

```text
research_hot.hot_rank_regret_pair_v1
```

字段：

```sql
regret_pair_id
research_run_id
teacher_prior_batch_id
batch_date

higher_rank_signal_id
lower_rank_signal_id
higher_rank_symbol
lower_rank_symbol

higher_teacher_rank
lower_teacher_rank
higher_final_rank
lower_final_rank

higher_final_score
lower_final_score
higher_max_return_t3
lower_max_return_t3
higher_max_return_t5
lower_max_return_t5

regret_gap_return
regret_type                    -- top1_underperformed_top2/high_rank_underperformed_low_rank/local_upgrade_failed

teacher_score_diff
local_score_diff
sector_evidence_diff_json
moneyflow_evidence_diff_json
market_evidence_diff_json
risk_penalty_diff_json
data_gap_diff_json

primary_regret_reason          -- teacher_overtrusted/sector_underweighted/moneyflow_missing/risk_penalty_too_low
secondary_regret_reason
suggested_research_action

created_at
```

这是热点模型研究中心最重要的表之一。它专门解决：

```text
第一名下跌，第二名涨停，为什么？
```

### 8.8 失败归因表

表名：

```text
research_hot.hot_failure_attribution_v1
```

字段：

```sql
failure_attribution_id
research_run_id
signal_id
canonical_symbol
signal_date

outcome_label
failure_stage                 -- pre_release/release_gate/post_signal_t1/observation_window/outcome_label
failure_type                  -- teacher_prior_noise/false_hot/market_drag/sector_failed/moneyflow_reversed/event_risk/tradability_failed/data_gap_misled/ranking_error

primary_reason
secondary_reason
evidence_json

teacher_prior_impact          -- high/medium/low
local_evidence_impact
market_impact
sector_impact
moneyflow_impact
event_impact
tradability_impact
data_gap_impact
buy_point_impact              -- 占位字段，后续接买点服务

manual_review_required
confidence_level
created_at
```

失败归因必须区分：

```text
teacher prior 噪声；
本地证据误判；
市场拖累；
板块失败；
资金反转；
事件风险；
可交易失败；
数据缺口误导；
排序权重问题。
```

### 8.9 数据缺口影响表

表名：

```text
research_hot.hot_data_gap_impact_v1
```

字段：

```sql
data_gap_impact_id
research_run_id
gap_field_group               -- moneyflow/board/event/market_breadth/limit_status
gap_field_name
required_level                -- P0/P1/P2

sample_count_with_gap
sample_count_without_gap

hit_rate_with_gap
hit_rate_without_gap
rank_regret_rate_with_gap
rank_regret_rate_without_gap
failure_rate_with_gap
failure_rate_without_gap

impact_score
recommended_requirement_change -- keep_p1/upgrade_to_p0/downgrade/ignore
created_at
```

用途：

```text
判断资金流、板块、事件等字段缺失是否真的影响模型；
如果影响显著，才考虑升级字段等级或增加 data_gap_penalty。
```

### 8.10 研究结论表

表名：

```text
research_hot.hot_research_finding_v1
```

字段：

```sql
finding_id
research_run_id
finding_type                  -- teacher_prior_valid/local_lift_positive/ranking_weight_suspect/data_gap_material_impact/market_regime_sensitive
finding_summary
evidence_json

evidence_level                -- weak/medium/strong/production_candidate
sample_count
affected_batches
affected_model_version

recommended_action            -- review_teacher_weight/review_sector_weight/upgrade_data_requirement/tighten_release_gate
production_change_allowed     -- 默认 false
manual_review_required        -- 默认 true

created_at
```

研究中心不能直接改模型，只能形成结论和建议。

---

## 9. 热点模型研究 API 设计

第一版建议 API：

```text
GET  /research/hot/healthz
GET  /research/hot/readyz

POST /research/hot/runs
GET  /research/hot/runs/{research_run_id}
POST /research/hot/runs/{research_run_id}/execute

POST /research/hot/batch-effectiveness/analyze
POST /research/hot/teacher-prior/analyze
POST /research/hot/local-evidence-lift/analyze
POST /research/hot/short-window/analyze
POST /research/hot/rank-regret/analyze
POST /research/hot/failure-attribution/analyze
POST /research/hot/data-gap-impact/analyze

GET  /research/hot/findings
GET  /research/hot/samples
GET  /research/hot/rank-regret-pairs
GET  /research/hot/evolution-metrics
```

所有长任务必须异步执行。API 只负责创建任务、查询状态、读取结果。

---

## 10. 热点模型研究任务流程

标准流程：

```text
1. 创建 hot_research_run；
2. 调用 source-data-service preflight / coverage check；
3. 冻结研究样本 hot_research_sample；
4. 读取 decision_hot 快照；
5. 读取 observation / outcome；
6. 按研究类型执行分析；
7. 生成 batch_effectiveness / teacher_prior / local_lift / rank_regret / failure_attribution 等结果；
8. 生成 hot_research_finding；
9. 若 evidence_level 达到 strong，进入人工审核；
10. 人工审核后才能形成生产模型变更建议。
```

如果数据源返回：

```text
blocked
```

研究任务状态必须是：

```text
data_blocked
```

不得生成正式研究结论。

---

## 11. 关键研究公式口径

### 11.1 短窗口命中率

```text
short_window_hit_rate =
  count(signal where hit_target = true and evaluation_window in T+1/T+3/T+5)
  /
  count(valid official signals)
```

排除样本必须写清：

```text
data_blocked
suspended_after_signal
tradability_unknown 且无法评估
```

禁止随意排除失败样本来美化结果。

### 11.2 排名后悔率

```text
rank_regret_rate =
  count(batch where lower_rank_candidate materially outperformed higher_rank_candidate)
  /
  count(valid comparable batches)
```

`materially_outperformed` 占位规则：

```text
lower_rank_max_return_t3 - higher_rank_max_return_t3 >= {{regret_return_threshold}}
```

说明：

```text
{{regret_return_threshold}} 后续由研究中心配置，例如 3pct 或 5pct，不允许硬编码。
```

### 11.3 teacher prior 预测力

字段：

```text
teacher_predictive_power_score
```

占位定义：

```text
衡量 teacher_rank / teacher_score 与后续短窗口收益或命中率之间的单调关系。
第一版可用 rank_bucket hit_rate 单调性；
后续可升级为 Rank IC / Spearman correlation。
```

### 11.4 本地证据提升分

```text
local_evidence_lift_score =
  final_rank_strategy_performance - teacher_rank_strategy_performance
```

说明：

```text
比较 final TopN 与 teacher TopN 在同批次、同窗口、同样本数下的表现差异。
不能跨日期、跨版本混算。
```

---

## 12. 资深金融研究员视角下的风控

热点模型研究必须规避 6 个常见错误。

### 12.1 幸存者偏差

不能只研究 official signal。必须研究：

```text
release_gate_rejected
near_miss
missed_opportunity
control_group
```

### 12.2 未来函数

所有 feature 必须满足：

```text
available_at <= decision_time
```

否则样本标记：

```text
future_leakage_suspected
```

不得进入正式结论。

### 12.3 只看最高收益

如果只看 T+3 最高收益，会高估模型。必须同时看：

```text
close_return
max_drawdown
tradability_state
execution_friendly
```

### 12.4 混淆模型成功和买点成功

模型一可以选对方向，但买点不好。outcome 必须区分：

```text
price_success
tradability_success
execution_friendly
```

### 12.5 把数据缺口当模型失败

如果 P0/P1 数据缺失导致误判，失败归因必须标记：

```text
data_gap_misled
```

### 12.6 把弱市失败当个股失败

必须用 `market_regime` 做归因。弱市下热点失败率高，不一定说明 teacher prior 无效，而可能说明 release_gate 需要按市场环境收紧。

---

## 13. 第一阶段验收标准

热点模型研究中心第一阶段完成，必须能回答以下 10 个问题：

```text
1. 某个 batch_date 的 teacher_rank Top1 / Top3 / Top5 表现如何？
2. final_rank 是否优于 teacher_rank？
3. teacher_rank 分桶是否有单调预测力？
4. teacher_high_local_low 样本是否高失败？
5. teacher_low_local_high 样本是否被低估？
6. Top1 输给 Top2 的批次有哪些？
7. Top1 输给 Top2 的主要原因是什么？
8. 哪些失败来自数据缺口，而不是模型错误？
9. 弱市下热点模型是否明显失效？
10. 有哪些研究结论可以进入人工审核，而不是直接改生产参数？
```

如果这 10 个问题回答不了，热点模型研究中心不算完成。

---

## 14. Codex 后续落地硬规则

后续 Codex 迭代必须遵守：

```text
1. research_hot 不允许直接调用外部 provider；
2. 所有研究任务必须绑定 research_run_id；
3. 所有研究样本必须冻结 model_version / feature_version / source_data_version；
4. 所有指标必须带 sample_count 和 confidence_level；
5. 样本量不足时不得输出 strong 结论；
6. outcome_label、failure_type、sample_role 不得混用；
7. 排名后悔分析只能在同 batch、同版本、同窗口内比较；
8. 数据缺口样本不得直接算模型失败；
9. 研究结论不得直接修改生产模型参数；
10. 任何公式新增必须写明金融含义、字段来源、适用窗口、失败模式和验证方法；
11. 任何新增字段必须补充 comment，说明字段业务含义、来源和是否可用于正式研究；
12. 任何新增表必须同步更新 README / MD 文档。
```

---

## 15. 最终结论

热点模型研究中心第一版的核心不是复杂算法，而是建立严谨研究闭环：

```text
teacher prior 输入
-> 本地证据确认
-> release gate 审计
-> 排序快照
-> official signal
-> T+1/T+3/T+5 观察
-> outcome 标签
-> teacher prior 有效性
-> 本地证据增益
-> 排名后悔
-> 失败归因
-> 数据缺口影响
-> 研究结论
-> 人工审核
-> 后续模型迭代
```

这套设计的研究价值是：

```text
1. 判断热点模型是否比同花顺榜单本身更有价值；
2. 判断本地数据是否真正改善排序；
3. 找出 Top 排名错误的稳定原因；
4. 找出哪些数据字段最影响模型；
5. 找出哪些研究发现值得进入下一版模型；
6. 为未来研究中心总览页提供模型级进化指标。
```


---

# V2 动态特征增强：热点模型研究中心改造

## 1. V2 新增研究目标

热点模型原 V1 已经覆盖 teacher prior、final_rank、本地证据、短窗口兑现、排名后悔和失败归因。引入 dynamic-feature-service 后，热点模型研究中心必须进一步回答：

```text
1. 同花顺 teacher prior 高排名样本是否在盘中得到真实市场确认？
2. teacher_rank 高但盘中承接弱的样本，失败率是否显著更高？
3. teacher_rank 不高但盘中确认强的样本，是否被 final_rank 低估？
4. 动态特征能否改善同批次排序？
5. Top1 输给 Top2 的案例中，动态特征是否能解释排序错误？
6. 高开低走、弱承接、冲高回落是否应进入热点模型风险惩罚？
7. 涨停样本是否存在合理可交易窗口，还是价格成功但执行不友好？
```

热点模型动态研究的核心不是“盘中涨了多少”，而是：

```text
teacher prior 是否被真实承接确认；
盘中行为是否能修正静态排序；
动态确认是否能降低 rank_regret_rate。
```

---

## 2. 新增动态特征依赖

热点模型研究中心新增读取：

```text
dynamic_feature.dynamic_feature_run_v1
dynamic_feature.dynamic_feature_subject_v1
dynamic_feature.dynamic_feature_snapshot_v1
dynamic_feature.dynamic_feature_gap_v1
research_dynamic.dynamic_feature_lift_analysis_v1
research_dynamic.dynamic_feature_bucket_effectiveness_v1
research_dynamic.dynamic_rerank_regret_v1
research_dynamic.dynamic_feature_gap_impact_v1
```

热点模型优先使用 bundle：

```text
hot_intraday_confirmation_bundle_v1
buy_point_intraday_bundle_v1
```

重点 feature：

```text
gap_acceptance_score                    -- 高开承接质量
high_open_low_walk_risk                 -- 高开低走风险
open_5m_return / open_15m_return         -- 开盘阶段收益
price_above_vwap_ratio_15m              -- 价格站上 VWAP 的时间占比
open_pullback_max_drawdown_15m           -- 开盘回撤幅度
volume_quality_score                    -- 量价配合质量
stock_vs_board_intraday_strength_score   -- 相对板块盘中强度
stock_vs_index_strength_score            -- 相对指数盘中强度
intraday_false_rebound_risk_score        -- 盘中假反弹风险
limit_up_tradability_score               -- 涨停可交易性
tradable_entry_window_quality_score      -- 买点窗口质量
```

---

## 3. 新增表：teacher prior 盘中确认研究

```sql
CREATE TABLE IF NOT EXISTS research_hot.hot_intraday_confirmation_analysis_v1 (
    intraday_confirmation_id        VARCHAR(64) PRIMARY KEY,
    research_run_id                 VARCHAR(64) NOT NULL,
    teacher_prior_batch_id          VARCHAR(64) NOT NULL,
    batch_date                      DATE NOT NULL,

    teacher_rank_bucket             VARCHAR(32) NOT NULL, -- top1/top2_3/top4_5/top6_10/other
    intraday_confirmation_bucket    VARCHAR(32) NOT NULL, -- strong/medium/weak/missing
    as_of_time_policy               VARCHAR(64) NOT NULL, -- production_snapshot/research_replay/mixed

    sample_count                    INT NOT NULL,
    valid_sample_count              INT NOT NULL,
    dynamic_gap_count               INT DEFAULT 0,

    hit_rate_t1                     NUMERIC(12,6),
    hit_rate_t3                     NUMERIC(12,6),
    hit_rate_t5                     NUMERIC(12,6),
    avg_max_return                  NUMERIC(12,6),
    avg_max_drawdown                NUMERIC(12,6),
    failure_rate                    NUMERIC(12,6),

    gap_acceptance_score_avg        NUMERIC(12,6),
    volume_quality_score_avg        NUMERIC(12,6),
    stock_vs_board_strength_avg     NUMERIC(12,6),
    false_rebound_risk_avg          NUMERIC(12,6),

    confirmation_lift_score         NUMERIC(12,6),
    confidence_level                VARCHAR(32),
    created_at                      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

### 研究口径

```text
teacher_high_intraday_strong：teacher_rank 靠前，盘中承接强。
teacher_high_intraday_weak：teacher_rank 靠前，但高开低走、弱承接、相对板块弱。
teacher_mid_intraday_strong：teacher_rank 中等，但盘中强确认。
```

这张表用于验证：

```text
盘中动态确认是否能过滤 teacher prior 噪声；
盘中确认强的中位排名样本是否值得上调；
teacher 高排名但盘中弱的样本是否应降低 final_rank。
```

---

## 4. 新增表：热点动态重排研究

```sql
CREATE TABLE IF NOT EXISTS research_hot.hot_dynamic_rerank_analysis_v1 (
    dynamic_rerank_id               VARCHAR(64) PRIMARY KEY,
    research_run_id                 VARCHAR(64) NOT NULL,
    teacher_prior_batch_id          VARCHAR(64) NOT NULL,
    batch_date                      DATE NOT NULL,
    as_of_time                      TIMESTAMP,
    as_of_time_policy               VARCHAR(64) NOT NULL,

    original_final_top1_signal_id   VARCHAR(64),
    dynamic_top1_signal_id          VARCHAR(64),
    original_top1_symbol            VARCHAR(32),
    dynamic_top1_symbol             VARCHAR(32),

    original_top1_return_t3         NUMERIC(12,6),
    dynamic_top1_return_t3          NUMERIC(12,6),
    original_top1_return_t5         NUMERIC(12,6),
    dynamic_top1_return_t5          NUMERIC(12,6),
    return_gap                      NUMERIC(12,6),

    dynamic_rank_lift_score         NUMERIC(12,6),
    rank_regret_before              NUMERIC(12,6),
    rank_regret_after               NUMERIC(12,6),

    primary_dynamic_reason          VARCHAR(128), -- weak_acceptance/high_open_low_walk/stock_vs_board_strong/limit_tradability
    feature_diff_json               JSONB,
    confidence_level                VARCHAR(32),
    created_at                      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

### 禁止事项

```text
不能用收盘后才知道的动态特征重排开盘前榜单；
不能跨 batch_date 比较；
不能把 research_replay 的重排收益直接当作 production 真实收益。
```

---

## 5. 新增表：高开低走风险研究

```sql
CREATE TABLE IF NOT EXISTS research_hot.hot_high_open_low_walk_analysis_v1 (
    analysis_id                     VARCHAR(64) PRIMARY KEY,
    research_run_id                 VARCHAR(64) NOT NULL,
    gap_bucket                      VARCHAR(32), -- high_gap/mid_gap/low_gap/flat/open_down

    sample_count                    INT NOT NULL,
    high_open_low_walk_count        INT NOT NULL,
    high_open_low_walk_failure_rate NUMERIC(12,6),
    non_high_open_low_walk_failure_rate NUMERIC(12,6),

    avg_auction_gap_pct             NUMERIC(12,6),
    avg_open_15m_return             NUMERIC(12,6),
    avg_drawdown_from_intraday_high NUMERIC(12,6),
    avg_price_below_vwap_ratio      NUMERIC(12,6),

    recommended_action              VARCHAR(64), -- increase_risk_penalty / research_only / ignore
    confidence_level                VARCHAR(32),
    created_at                      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

---

## 6. 新增表：涨停可交易性研究

```sql
CREATE TABLE IF NOT EXISTS research_hot.hot_limit_up_tradability_analysis_v1 (
    tradability_analysis_id         VARCHAR(64) PRIMARY KEY,
    research_run_id                 VARCHAR(64) NOT NULL,
    evaluation_window               VARCHAR(32) NOT NULL,

    sample_count                    INT NOT NULL,
    limit_up_count                  INT NOT NULL,
    one_word_limit_count            INT NOT NULL,
    tradable_limit_up_count         INT NOT NULL,

    price_success_rate              NUMERIC(12,6),
    tradability_success_rate        NUMERIC(12,6),
    price_success_but_untradable_rate NUMERIC(12,6),

    avg_limit_up_tradability_score  NUMERIC(12,6),
    avg_entry_window_minutes        NUMERIC(12,6),
    avg_limit_open_count            NUMERIC(12,6),

    recommended_label_action        VARCHAR(64), -- split_price_success / add_execution_penalty / research_only
    created_at                      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

---

## 7. 热点模型新增研究指标

```text
teacher_prior_intraday_confirm_rate
teacher_high_but_intraday_weak_failure_rate
teacher_mid_but_intraday_strong_success_rate
dynamic_rank_lift_score
intraday_confirmation_topN_lift
top1_dynamic_regret_explanation_rate
high_open_low_walk_failure_rate
limit_up_tradability_success_rate
price_success_but_execution_unfriendly_rate
```

---

## 8. 热点模型研究任务流程 V2

```text
1. 创建 hot_research_run。
2. 冻结 teacher prior、decision_hot、outcome 样本。
3. 读取 production dynamic_feature_snapshot。
4. 若缺 production snapshot，可创建 research_replay run，但结论降级。
5. 执行 teacher prior 盘中确认研究。
6. 执行动动态重排研究。
7. 执行高开低走风险研究。
8. 执行涨停可交易性研究。
9. 将关键结果同步写入 research_dynamic。
10. 生成 hot_research_finding，finding_type 支持 dynamic_feature_positive_lift / dynamic_rerank_effective / intraday_gap_material_impact。
```

---

## 9. V2 验收标准

热点模型 V2 研究中心必须能回答：

```text
1. teacher Top1 是否经常盘中确认弱？
2. 盘中确认强的 teacher Top3/Top5 样本是否显著更好？
3. 动态重排能否降低 Top1 输给 Top2 的比例？
4. 高开低走是否是热点模型失败的稳定先导信号？
5. 涨停成功样本中有多少买不到？
6. dynamic replay 与 production snapshot 是否一致？
7. 哪些动态特征可以进入 production_candidate，哪些只能 research_only？
```
