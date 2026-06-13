# ambush-watchlist-service README

> 唯一模型根目录 MD。已整合当前契约、最终设计、Phase 1/2/3/4 实施报告。
> 锁定候选版本：`ambush_watchlist_service_v1.0_rc_backend_closure_candidate`。未经用户明确批准，不得修改模型三业务代码、字段、表结构、公式或发布闸门。


---

# 当前服务契约与 API

# ambush-watchlist-service 当前契约

端口：`8033`
模型版本：`ambush_watchlist_effective_turn_v1_1`

## 定位

深圳 A 股潜伏抬头 / 龙抬头模型。它在全市场扫描中识别低位衰竭后刚抬头的结构，并分阶段过滤晚反弹、假反弹、流动性不足和证据缺口。

## API

- `GET /health`
- `GET /healthz`
- `GET /readyz`
- `POST /dragon/window-feature`
- `POST /dragon/window-features`
- `POST /ambush/valley-watch`
- `POST /ambush/effective-turn-candidate`
- `POST /ambush/pool-transition-audit`
- `POST /dragon/l2-candidate`
- `POST /dragon/deep-analysis`

## 数据入口

生产入口是 `research-service /ambush-watchlist/runs`，内部调用本服务多个阶段 API。模型只接收 payload，不采集 provider，不写库。

基础对象：

- `instrument`：`instrument_id`、`symbol`、`exchange`、`asset_type`、`board`、`is_active`、`is_suspended`、`is_st`、`is_delisting_risk`、`has_trade_calendar`、`trade_calendar_missing`、`adjustment_conflict`、`listing_days`、`price_limit_regime`。
- `bars`：日线数组，包含交易日、`open_price`、`high_price`、`low_price`、`close_price`、`volume`、`amount`、复权冲突标记。
- `as_of_trading_day`
- `as_of_time`

深度分析额外输入：

- `best_feature`
- `l2_candidate`
- `effective_turn_candidate`
- `stock_rank`
- `theme_ranks`
- `news_context`
- `market_context`

## 阶段

1. `window-feature`：计算单窗口形态分。
2. `window-features`：计算 20/30/40/60/90/120 日所有窗口。
3. `valley-watch`：找低位谷底观察对象。
4. `effective-turn-candidate`：识别第一反弹、二次转折或平台突破。
5. `pool-transition-audit`：记录池迁移。
6. `l2-candidate`：检查流动性、停牌、ST、退市风险、日线完整度。
7. `deep-analysis`：融合资金、板块、新闻、市场环境，给出 dragon state。

## 编排层异常兜底

`research-service` 按标的和阶段调用本服务。单条或单阶段异常不终止整批：

- run warning：`ambush_watchlist:row_failed:{symbol}:{stage}:{error_code}`。
- transition audit：写 `decision_result=data_blocked`、`trigger_event=model_service_exception`、`reject_reason_codes=["model_service_scoring_failed", "model_service_exception:{error_code}"]`。
- window feature 失败：为 20/30/40/60/90/120 窗口写 `pass_l1_gate=false` 和 `block_reasons=["blocked_model_service_exception", ...]`。
- L2 失败：在已有 `best_feature` 时写 `l2_status=blocked`、`liquidity_check=blocked_model_service_exception`。
- deep 失败：写 `dragon_state=dragon_failed`、`dragon_head_score=null`、`evidence_gap_penalty=100`、`source_gap_count>0`。
- 异常 payload 字段：`stage`、`symbol`、`instrument_id`、`as_of_time`、`error_code`、`error_message`、输入引用。

整批状态：有任一 `row_failed` 时 run 返回 `partial`；无输入返回 `empty`；其余返回 `completed`。

## 阈值

- 窗口：`20,30,40,60,90,120`。
- 日线完整度：至少 `0.95`。
- L2 20 日平均成交额：不低于 `30000000`。
- 谷底回撤：`8%-45%`。
- 距主低点：不超过 `6%` 才进入 `valley_watch`。
- 有效转折新鲜度：优先 `0-3` 个交易日。
- 证据层级封顶：L0=0、L1=59、L2=69、L3=82、L4=100。
- L4 要求：L2 passed、false reversal risk <=45、upside >=55、liquidity >=60、无 P0/L4 阻断、非防御性大盘逆风。

## 状态

谷底：

- `data_blocked`
- `valley_invalidated`
- `valley_watch`

有效转折：

- `rejected`
- `backup_only`
- `accepted`

深度：

- `dragon_failed`
- `dragon_expired`
- `dragon_bottoming`
- `dragon_turning_up`
- `dragon_confirming`
- `dragon_ready`

证据：

- `L1_EFFECTIVE_TURN`
- `L2_FILTER_PASSED`
- `L3_DEEP_CONFIRMED`
- `L4_DRAGON_READY`

## 缺口

P0：

- `daily_bar_missing`
- `daily_bar_incomplete`
- `daily_bar_completeness_missing`
- `trading_calendar_missing`
- `daily_bar_completeness_below_l4`
- `effective_turn_candidate_missing`

L4 阻断额外包括：

- `moneyflow_missing`
- `deep_capital_probe_missing`
- `market_context_missing`
- `false_reversal_risk_missing`
- `distance_from_trough_missing`
- `dragon_priority_score_missing`

## 分数

深度分析分量：

- `decline_maturity_score`
- `bottom_stabilization_score`
- `early_turn_up_score`
- `dragon_shape_score`
- `turn_freshness_score`
- `breakout_readiness_score`
- `capital_probe_score`
- `sector_context_score`
- `news_event_score`
- `market_context_score`
- `upside_room_score`
- `liquidity_tradability_score`
- `false_reversal_risk`
- `late_rebound_penalty`
- `evidence_gap_penalty`

`dragon_priority_score` 按证据层级封顶：L1 59，L2 69，L3 82，L4 100。

## 决策回顾字段

主列表：

- `symbol`
- `name`
- `trade_date`
- `dragon_priority_score`
- `dragon_state`
- `evidence_level`
- `reference_entry_price`
- `return_from_entry_pct`
- `mfe_pct`
- `mae_pct`
- `buy_point_status`
- `verification_status`
- `source_gap_codes`
- `as_of_time`

详情：

- 当前结论
- 价格与评估基准
- 为什么值得看
- 主要风险
- 后续观察
- 人工复核
- 数据质量与买点审计

## 落库和下游

由 `research-service` 写入：

- `decision.ambush_scan_universe_v1`
- `decision.ambush_valley_watch_pool_v1`
- `decision.ambush_effective_turn_candidate_v1`
- `decision.ambush_pool_transition_audit_v1`
- `decision.dragon_deep_analysis_v1`

下游：

- research-data-mart 做研究和标签。
- execution-timing-service 生成买点版本。
- gateway/frontend/Jarvis 只读。
- data-inspector 巡检模型决策、买点和证据缺口。

## 调度

- 潜伏日线补跑：`16:10:00,20:10:00`。
- 潜伏 outcome：`15:20:00`。
- 潜伏研究任务主要在 `18:25-19:10`。

## 不变量

- 当前 universe 只接受深圳 A 股活动标的。
- 不得为缺日线、缺交易日历、缺资金流、缺市场上下文的标的生成假 L4。
- `reference_entry_price` 是评估基准，不是推荐交易价。
- 前端不计算模型分，不裸露 `source_gap:*`、`buy_point_block:*`、`domain_missing:*` 到主列表。
- Jarvis、frontend 和 gateway 不得改模型状态或分数。


---

# 最终设计说明

# 潜伏抬头 / 龙抬头模型 ambush_watchlist 最终设计说明 v1

> 文件位置：`services/models_services/ambush-watchlist-service/README.md（已合并）`  
> 模型名称：潜伏抬头 / 龙抬头模型  
> 模型代码：`ambush_watchlist`  
> 状态：模型三正式设计稿。尚未拍板代码实现，进入代码前必须以本文作为根目录设计契约。

---

## 0. 计算硬性标准

模型三所有计算必须专业、可解释、可验证，不能想当然随便用数据或随便组合公式。

任何指标进入正式模型前，必须具备：

```text
1. 金融含义：解释什么市场行为。
2. 数据来源：来自日K、周K、资金、板块、交易状态还是其他源。
3. 数据口径：复权价还是原始价，close、typical price、high-low envelope 还是成交均价。
4. 计算公式：公式、窗口、参数、归一化方式。
5. 适用场景：低谷成熟、图形相似、假底风险、有效抬头、release_gate。
6. 反例风险：什么场景下会误判。
7. 验证方式：正负样本分桶、hard negative 检验、walk-forward、真实 replay。
8. 版本记录：formula_code、formula_version、threshold_version、pattern_library_version。
```

未经论证的计算不得进入正式 release gate。

---

## 1. 模型最终定义

潜伏抬头模型不是低位股筛选器，也不是超跌反弹筛选器。

正式定义：

```text
潜伏抬头模型是神策中心的全市场早期弱转强结构扫描模型。
它以低谷图形库为历史形态先验，以日K/周K多周期结构、下跌衰竭、波动收敛、支撑稳定、量能修复、相对强弱、资金修复、板块环境和假反弹风险为计算依据，识别那些尚未明显走热、但已经从成熟低谷中出现第一天或第二天有效抬头的股票。
```

一句话：

```text
模型三的 alpha 来源，不是“低位”，而是“低谷成熟后第一次有效抬头”。
```

---

## 2. 与模型一、模型二的边界

```text
热点模型 hot_candidates：
市场已经显性关注后的短窗口兑现。

候选记忆模型 candidate_memory：
历史热点样本沉淀后的二次上涨前置信号。

潜伏抬头模型 ambush_watchlist：
还没有明显成为热点、但低位结构刚刚从弱转强的早期抬头。
```

模型三不依赖热点模型入选历史，也不以同花顺教师概率作为核心先验。它面对的是深圳 A 股全市场扫描范围，重点研究日K/周K低谷结构。

---

## 3. 总体架构

模型三由两套系统和一条主链路组成。

### 3.1 独立低谷图库系统

```text
ambush-pattern-miner-service
```

职责：

```text
历史窗口扫描
正负样本挖掘
hard negative 挖掘
反弹质量打标
shape signature 生成
prototype 聚类
图库版本发布
图库反馈回收
```

### 3.2 潜伏抬头主模型服务

```text
ambush-watchlist-service
```

职责：

```text
消费 active 图库版本
全市场当前窗口扫描
三路召回
valley_watch_pool
有效抬头锚点识别
deep confirmation
release_gate
buy_point
monitoring
outcome / evolution
```

### 3.3 主链路

```text
source 数据能力审计
-> 历史低谷图库挖掘
-> 正负样本库 / hard negative 库
-> shape signature / prototype 图库
-> 当前全市场三路召回
-> valley_maturity_score
-> effective_turn_anchor_day
-> false_rebound_risk_score
-> valley_watch_pool
-> effective_turn_pool
-> L2/L3/L4 深度确认
-> release_gate
-> buy_point
-> monitoring
-> outcome_label
-> failure_attribution
-> pattern_library_feedback
-> formula_version_evaluation
```

---

## 4. 数据源能力审计

模型三正式计算前必须先做：

```text
ambush_source_capability_audit
```

目标：验证历史窗口中到底能拿到哪些数据，覆盖多少年、覆盖哪些股票、字段缺失率、是否支持复权、是否支持周K、是否支持 available_at。

### 4.1 P0 数据，缺失则 Phase 1 不成立

```text
日K OHLCV：open / high / low / close / volume / amount
复权因子：adjustment_factor / adjusted_ohlcv
交易状态：停牌、ST、退市风险、涨跌停状态
周K OHLCV：可由日K聚合，但复权口径必须一致
基础成交结构：成交额、成交量、换手率、振幅、量比或可计算量比
股票基础信息：symbol、名称、市场、上市日期、行业、板块、市值区间
交易日历：交易日、停牌日、复牌日、除权除息日
```

### 4.2 P1 数据，用于深度确认

```text
个股资金流
板块强度
板块涨停家数
市场情绪
指数行情
同板块相对强弱
公告 / 风险事件
可交易性数据
```

### 4.3 P2 数据，用于后续增强

```text
分钟线
集合竞价
题材关系
新闻事件
互动平台
龙虎榜后验
融资融券
舆情热度
```

### 4.4 审计表

```text
governance.source_capability_audit_v1
```

核心字段：

```text
provider
data_domain
field_name
frequency
history_start_date
history_end_date
symbol_coverage_rate
date_coverage_rate
missing_rate
available_at_supported
adjustment_supported
quality_status
usable_for_pattern_library
usable_for_online_scoring
reject_reason
checked_at
```

如果某公式依赖的数据覆盖率不足，该公式不能进入正式模型，只能进入研究模式。

---

## 5. 低谷图库设计

低谷图库不是图片文件夹，而是：

```text
历史低谷样本库
+ 正负样本标签库
+ hard negative 难负样本库
+ K线数值序列库
+ shape signature 向量库
+ prototype 原型库
+ 图形渲染资产
+ 图库版本管理系统
```

### 5.1 样本类型

必须同步收集正负样本。

```text
strong_positive：
低谷深、反弹强、相对收益好、过程可交易、结构延续。

weak_positive：
低谷后反弹成立，但持续性一般、回撤较大或可交易性一般。

hard_negative：
图形很像低谷，但后续失败。最重要。

easy_negative：
明显下跌中继、持续破位、低流动性死谷。
```

### 5.2 hard negative 示例

```text
像双底，但第二个底失效。
像圆弧底，但无量。
像平台突破，但放量冲高回落。
像 V 型修复，但板块继续下跌。
像缩量企稳，但流动性极差。
像低谷横盘，但随后破位。
```

### 5.3 样本生命周期点

每个样本必须保存：

```text
local_peak_day
decline_start_day
local_low_day
valley_anchor_day
compression_start_day
turn_anchor_day
confirmation_day
```

这样才能判断当前股票处于哪个阶段：下跌、跌速衰竭、局部低点、低谷确认、横盘压缩、第一天抬头、第二天抬头、已经走远。

---

## 6. 图形绘制与计算口径

不能简单二选一“用当天均值还是最高/最低价”。

硬规则：

```text
展示用 OHLC K线图；
计算用多通道数值序列。
```

### 6.1 展示图

用于人工复核和前端展示：

```text
日K蜡烛图
成交量柱
MA5 / MA10 / MA20
local_low_day 标记
valley_anchor_day 标记
turn_anchor_day 标记
T+10 / T+20 反弹标记
```

展示必须使用 OHLC，不用单一均值线替代 K 线。

### 6.2 计算通道

模型计算不直接用 PNG 像素，而用数值序列。

#### A. close path

```text
close_sequence
```

用途：主趋势、回撤、低谷主路径、收盘确认。

#### B. typical price path

```text
typical_price = (H + L + C) / 3
```

用途：平滑日内噪声、辅助判断价格重心、辅助相似度。

#### C. high-low envelope

```text
high_sequence
low_sequence
```

用途：支撑是否击穿、压力是否触碰、上影线风险、下影线承接、波动收敛。

#### D. K线几何结构

```text
body_ratio = abs(C - O) / (H - L)

upper_shadow_ratio =
(H - max(O, C)) / (H - L)

lower_shadow_ratio =
(min(O, C) - L) / (H - L)

close_position =
(C - L) / (H - L)
```

用途：识别冲高回落、下影承接、收盘强弱、假反弹。

#### E. volume path

```text
volume_sequence
amount_sequence
turnover_sequence
```

用途：缩量沉淀、温和放量、异常爆量、量价背离。

### 6.3 复权口径

```text
图形相似度：使用 adjusted OHLC。
趋势 / 回撤 / 斜率：使用 adjusted close / adjusted OHLC。
涨跌停判断：使用 raw close / raw limit price。
买点 / 可交易性：使用 raw price。
成交量 / 成交额：使用原始数据。
```

防止除权被误判为暴跌低谷。

---

## 7. 三路召回机制

模型三不能只靠图库相似度。最终采用三路召回：

```text
A. 图形相似度召回
B. 数学低谷成熟度召回
C. 横盘压缩突破召回
```

### A. 图形相似度召回

输出：

```text
positive_valley_similarity
false_bottom_similarity
hard_negative_similarity
shape_edge_score
```

建议公式：

```text
shape_edge_score =
positive_valley_similarity
- 0.7 * false_bottom_similarity
- 1.0 * hard_negative_similarity
```

像成功低谷不够，必须不像 hard negative。

### B. 数学低谷成熟度召回

召回那些不完全像图库原型，但回撤、衰竭、支撑、波动收敛、量能沉淀、周K位置成立的股票。

### C. 横盘压缩突破召回

覆盖：低点后不是连续反弹，而是横盘 7-15 天后刚刚突破的股票。

最终：

```text
recall_candidates = A ∪ B ∪ C
```

然后统一进入深度评测。

---

## 8. 核心公式体系

以下公式是 v1 候选公式，不是永久真理。后续必须通过分桶回测、hard negative 检验和 outcome 校准。

### 8.1 回撤成熟度

金融含义：衡量是否经历足够风险释放。

```text
drawdown_N(t) =
C_t / max(C_{t-N+1 ... t}) - 1
```

```text
days_since_peak_N =
t - argmax(C_{t-N+1 ... t})
```

```text
valley_depth_score =
0.60 * drawdown_depth_score
+ 0.40 * drawdown_duration_score
```

不能单独作为机会判断，因为跌得深不等于安全。

### 8.2 下跌衰竭

金融含义：衡量杀跌动能是否衰减。

```text
ln(C_i) = α + β * i + ε
```

```text
downtrend_deceleration = β_5 - β_20
```

如果 `β_20 < 0` 且 `β_5 > β_20`，说明中期仍弱，但短期下跌速度在减缓。

### 8.3 支撑稳定

```text
distance_to_low_N =
C_t / min(L_{t-N+1 ... t}) - 1
```

```text
break_low_count_N =
count(L_i < previous_local_low * (1 - ε))
```

```text
higher_low_count_N =
count(local_low_i > local_low_{i-1} * (1 + ε))
```

```text
support_stability_score =
0.40 * low_near_but_not_break_score
+ 0.35 * higher_low_score
+ 0.25 * support_hold_score
- 0.40 * break_low_penalty
```

### 8.4 波动收敛

```text
realized_volatility_N =
sqrt(252 / N * Σ r_i²)
```

```text
TR_t = max(H_t - L_t, |H_t - C_{t-1}|, |L_t - C_{t-1}|)
ATR_N = MA(TR, N)
NATR_N = ATR_N / C_t
```

```text
volatility_compression = RV_10 / RV_40
```

```text
volatility_compression_score =
1 - clip(RV_10 / RV_40, 0, 1)
```

### 8.5 量能衰竭与恢复

```text
volume_compression_ratio =
mean(volume_5d) / mean(volume_20d)
```

```text
volume_recovery_ratio =
volume_today / mean(volume_20d)
```

```text
abnormal_volume_spike =
volume_today / mean(volume_20d)
```

```text
volume_structure_score =
0.45 * volume_exhaustion_score
+ 0.35 * mild_recovery_score
- 0.30 * abnormal_spike_risk
```

### 8.6 周K结构

```text
weekly_drawdown_16w =
C_week_t / max(C_week_{t-15 ... t}) - 1
```

```text
weekly_slope_repair =
β_week_4w - β_week_12w
```

```text
weekly_structure_score =
0.35 * weekly_drawdown_maturity
+ 0.30 * weekly_slope_repair
+ 0.20 * weekly_volatility_compression
+ 0.15 * weekly_support_stability
```

周K空头压力是 risk multiplier，不是所有场景的绝对 hard block。

### 8.7 有效抬头新鲜度

```text
close_position =
(C_t - L_t) / (H_t - L_t)
```

```text
micro_breakout =
C_t > max(H_{t-5 ... t-1})
```

```text
MA5_slope = MA5_t - MA5_{t-1}
```

```text
return_since_recent_low =
C_t / recent_low_N - 1
```

```text
consecutive_rebound_days =
count_recent_days(C_i > C_{i-1})
```

```text
turn_freshness_score =
0.30 * close_strength_score
+ 0.25 * micro_breakout_score
+ 0.20 * MA5_slope_turn_score
+ 0.15 * higher_low_confirmation
- 0.35 * runaway_risk
```

硬规则：低点后连续反弹 7-8 天，默认降权或剔除；如果这 7-8 天是横盘压缩，而非连续上行，则允许重新计为有效抬头。

### 8.8 假反弹风险

```text
upper_shadow_ratio =
(H_t - max(O_t, C_t)) / (H_t - L_t)
```

```text
weak_close_risk = 1 - close_position
```

```text
volume_spike_weak_close =
abnormal_volume_spike * weak_close_risk
```

```text
false_rebound_risk =
0.20 * weekly_bear_pressure
+ 0.18 * break_low_frequency
+ 0.18 * volume_spike_weak_close
+ 0.15 * upper_shadow_risk
+ 0.12 * sector_weakness
+ 0.10 * pressure_too_close
+ 0.07 * liquidity_risk
```

---

## 9. 评分结构

模型三不能只输出一个总分，要输出多组分。

### 9.1 图形分

```text
pattern_match_score =
positive_valley_similarity
- 0.7 * false_bottom_similarity
- 1.0 * hard_negative_similarity
```

### 9.2 低谷成熟度分

```text
valley_maturity_score =
0.20 * valley_depth_score
+ 0.15 * cycle_maturity_score
+ 0.15 * weekly_structure_score
+ 0.15 * downtrend_exhaustion_score
+ 0.15 * support_stability_score
+ 0.10 * volatility_compression_score
+ 0.10 * volume_structure_score
```

### 9.3 有效抬头分

```text
effective_turn_score =
0.35 * turn_freshness_score
+ 0.20 * micro_breakout_quality
+ 0.15 * higher_low_confirmation
+ 0.15 * mild_volume_recovery
+ 0.15 * relative_strength_repair
```

### 9.4 外部确认分

```text
confirmation_score =
0.40 * moneyflow_repair_score
+ 0.35 * sector_market_support_score
+ 0.25 * tradability_score
```

### 9.5 总分

```text
ambush_score =
0.25 * pattern_match_score
+ 0.30 * valley_maturity_score
+ 0.25 * effective_turn_score
+ 0.20 * confirmation_score
- 0.35 * false_rebound_risk
- 0.20 * runaway_risk
```

该权重只是 `ambush_formula_v1` 初始解释权重，必须支持 `formula_version`、`market_regime`、`weight_profile`、`shadow_evaluation`、`active_version`，不能长期写死。

---

## 10. release gate 硬规则

正式进入 `release_signal_pool` 不能只看总分。

### Hard block

```text
1. 数据不完整或复权异常。
2. 非深圳A股、ST、停牌、退市风险。
3. available_at 不合规。
4. 图形更像 hard negative 而不是成功低谷。
5. false_rebound_risk 超阈值。
6. 支撑位连续破坏。
7. 低点后连续反弹已经走远。
8. 异常爆量但收盘弱。
9. 流动性不足。
10. 上方压力过近且无突破空间。
```

### Research only

```text
1. 图形相似度高，但资金/板块不足。
2. 周K空头压力较大，但日K修复明显。
3. 横盘压缩刚突破但样本不足。
4. 数据轻微缺失但不影响主要形态。
```

### Official signal

必须满足：

```text
低谷成熟
有效抬头新鲜
假反弹风险可控
图形净优势为正
数据口径合规
未走远
可交易性达标
```

---

## 11. 分层池设计

```text
ambush_recall_candidate_pool
三路召回后的原始候选。

valley_watch_pool
低谷成熟但尚未有效抬头。

early_turn_pre_signal_pool
出现刚抬头前兆，但尚未深度确认。

effective_turn_pool
出现 effective_turn_anchor_day，进入深度确认。

deep_confirmation_pool
L2/L3/L4 资金、结构、环境确认中。

release_signal_pool
通过 release_gate 的正式信号。
```

只有 `release_signal_pool` 进入正式决策回顾和买点服务。

---

## 12. 核心表设计

独立 schema：

```text
decision_ambush.*
```

### 12.1 图库相关

```text
decision_ambush.valley_pattern_library_version_v1
decision_ambush.valley_pattern_sample_v1
decision_ambush.valley_pattern_prototype_v1
decision_ambush.valley_shape_signature_v1
decision_ambush.valley_pattern_match_result_v1
decision_ambush.valley_pattern_review_v1
```

### 12.2 窗口特征

```text
decision_ambush.ambush_daily_window_feature_v1
decision_ambush.ambush_weekly_window_feature_v1
```

### 12.3 主链路

```text
decision_ambush.ambush_recall_candidate_v1
decision_ambush.valley_watch_pool_v1
decision_ambush.effective_turn_anchor_v1
decision_ambush.effective_turn_pool_v1
decision_ambush.ambush_feature_matrix_v1
decision_ambush.ambush_score_fact_v1
decision_ambush.ambush_release_gate_audit_v1
decision_ambush.ambush_signal_fact_v1
decision_ambush.ambush_buy_point_v1
decision_ambush.ambush_observation_snapshot_v1
decision_ambush.ambush_latest_state_v1
decision_ambush.ambush_outcome_label_v1
decision_ambush.ambush_failure_attribution_v1
decision_ambush.ambush_evolution_sample_v1
decision_ambush.ambush_formula_version_evaluation_v1
```

### 12.4 公式治理

```text
decision_ambush.ambush_formula_registry_v1
decision_ambush.ambush_formula_execution_audit_v1
```

---

## 13. 高性能设计

模型三是三大模型里数据量压力最大的。

如果股票数 5000+、10 年约 2400 个交易日、40/60/120 三类窗口，则滚动窗口约：

```text
5000 * 2400 ≈ 1200 万个窗口
```

不能在线暴力计算所有窗口，也不能在线全量 DTW。

正确架构：

```text
source.daily_bar / weekly_bar
-> window_feature_precompute
-> shape_signature
-> prototype 图库
-> TopK pattern match
-> valley_candidate
-> deep_confirmation
-> signal
```

原则：

```text
1. 原始K线只在 source 层。
2. 窗口特征提前预计算。
3. shape signature 提前生成。
4. DTW 用于离线精算和 TopK 复核，不在线全量扫。
5. 图片只存路径，不进主计算。
6. 样本表不塞大规模 OHLCV JSON。
7. 在线只计算最新窗口和 TopK 原型匹配。
8. 历史图库按版本发布。
```

### 离线任务

```text
历史窗口扫描
正负样本挖掘
hard negative 挖掘
反弹质量打标
shape signature 生成
prototype 聚类
图库版本发布
公式分桶评估
```

### 在线任务

```text
读取最新窗口特征
生成当前 signature
TopK pattern match
计算 valley_maturity_score
计算 false_rebound_risk
更新池状态
识别 effective_turn_anchor_day
```

---

## 14. 反弹质量评分

低谷正样本不能只看涨幅，要看质量。

建议：

```text
rebound_quality_score =
0.25 * rebound_mfe_20d_score
+ 0.20 * relative_market_return_score
+ 0.20 * relative_sector_return_score
+ 0.15 * rebound_persistence_score
+ 0.10 * drawdown_control_score
+ 0.10 * tradable_entry_window_score
```

核心标签：

```text
direction_success
tradable_success
structure_success
next_limit_up_flag
time_to_next_limit_up
rebound_mfe_10d
rebound_mfe_20d
post_valley_max_drawdown
relative_market_return_20d
relative_sector_return_20d
```

一字板买不到、单日脉冲、回撤巨大，都不能算高质量正样本。

---

## 15. outcome 标签

模型三 outcome 不能只写成功失败。

```text
effective_turn_success
false_rebound_failure
turn_detected_too_early
turn_detected_too_late
valley_valid_but_no_turn
valley_invalidated
breakout_failed
support_lost_after_turn
volume_not_confirmed
sector_not_supportive
direction_success_execution_missed
late_runaway_excluded_success
horizontal_compression_breakout_success
pattern_positive_but_failed
hard_negative_similarity_missed
```

关键标签：

```text
turn_detected_too_late
late_runaway_excluded_success
horizontal_compression_breakout_success
```

因为模型三必须平衡：不能追晚，也不能错过真正启动。

---

## 16. 验证标准

### 16.1 Source capability 验证

```text
P0 数据覆盖率达标
复权字段可用
周K可构造
停牌/ST/退市状态可追溯
available_at 可记录
```

### 16.2 图库验证

```text
正负样本数量达标
hard negative 不少于最低比例
样本时间覆盖多个市场周期
样本不只来自当前仍存活股票
rebound_quality_score 可复算
```

### 16.3 公式验证

每个公式必须有：

```text
formula_code
金融含义
数据口径
公式定义
误判风险
分桶结果
版本号
```

### 16.4 Walk-forward 验证

不能只用全历史回看，要做时间切分：

```text
训练图库版本：历史区间 A
验证区间：之后的区间 B
上线模拟区间：更后的区间 C
```

### 16.5 hard negative 验证

模型必须能明显降低 hard negative 的误入率。

### 16.6 性能验证

```text
每日新增窗口特征增量计算可完成
TopK pattern match 不全量扫历史
全市场日级扫描不超时
active pool 动态观察不爆量
```

---

## 17. 实施阶段

### Phase 1：低谷图库与高性能窗口特征系统

只做底座：

```text
source capability audit
window feature precompute
positive / negative / hard negative 样本挖掘
rebound_quality_score
shape_signature
prototype library
TopK pattern match
图库版本管理
```

### Phase 2：valley_watch_pool 与 effective_turn_anchor_day

```text
三路召回
valley_maturity_score
false_rebound_risk
valley_watch_pool
turn_freshness_score
effective_turn_anchor_day
effective_turn_pool
```

### Phase 3：L2/L3/L4 深度确认与正式信号

```text
结构确认
量能资金确认
板块市场确认
release_gate
buy_point
monitoring
```

### Phase 4：闭环与进化

```text
outcome_label
failure_attribution
pattern_library_feedback
formula_version_evaluation
hard_negative 回收
图库版本 shadow evaluation
```

---

## 18. 最终结论

模型三最终不是找低位股票，也不是找涨了一天的股票，而是：

```text
从全市场历史中建立成功低谷与失败假底的图形原型库；
用日K/周K多通道数值序列做相似度召回；
再用经过金融论证的公式体系评估低谷深度、下跌衰竭、支撑稳定、波动收敛、量能修复、有效抬头新鲜度、假反弹风险、资金板块确认和可交易性；
最终只把低谷成熟、刚刚抬头、未走远、非假反弹、数据合规且可交易的样本放入正式信号。
```

一句话：

```text
潜伏抬头模型的底层能力，是“历史低谷图形先验 + 专业金融公式评测 + 正负样本闭环校准”的早期弱转强识别系统。
```


---

# Phase 1 低谷图库与高性能特征底座实现报告

# 潜伏抬头模型 Phase 1 低谷图库与高性能特征底座实现报告

## 实现范围

本次只修改 `ambush-watchlist-service` 与新增 `decision_ambush` / `governance` SQL 契约，未修改已锁定的热点模型和候选记忆模型代码。

实现内容：

1. `ambush_source_capability_audit`
   - 验证日K OHLCV、复权字段、available_at、周K上下文、字段覆盖率。
   - 没有 adjusted OHLC 时只允许 research-only，不能进入正式图库或在线评分。

2. `ambush_multi_channel_shape_signature`
   - 使用多通道数值序列，而不是 PNG 像素计算。
   - 通道包括 close、typical price、high envelope、low envelope、volume、实体比例、上影线、下影线、收盘位置。
   - 形态计算优先使用 adjusted OHLC；成交量/成交额保持原始口径。
   - 严格只使用 `as_of_trading_day` 及之前的数据。

3. `ambush_topk_pattern_match`
   - 正样本、普通负样本、hard negative 同时参与相似度计算。
   - 输出 `positive_valley_similarity`、`false_bottom_similarity`、`hard_negative_similarity` 和 `shape_edge_score`。
   - 在线路径使用预计算 embedding TopK，DTW 保留为离线精算/TopK 复核方向。

4. `ambush_historical_sample_label`
   - 历史样本打标分为 `strong_positive`、`weak_positive`、`hard_negative`、`easy_negative`。
   - 后置窗口只允许用于历史样本标签，不允许进入在线评分。
   - 反弹质量不只看涨幅，同时考虑相对市场/板块、持续性、回撤控制和可交易窗口。

5. `ambush_three_channel_recall`
   - 三路召回：图形相似度召回、数学低谷成熟度召回、横盘压缩突破召回。
   - 输出 research facts，不生成正式 signal。

## 新增接口

```text
POST /ambush/source-capability-audit
POST /ambush/shape-signature
POST /ambush/pattern-prototype-match
POST /ambush/historical-valley-sample-label
POST /ambush/three-channel-recall
```

## 新增代码文件

```text
services/models_services/ambush-watchlist-service/src/ambush_watchlist_model_service/pattern_library.py
services/models_services/ambush-watchlist-service/tests/test_pattern_library_phase1.py
```

## 修改文件

```text
services/models_services/ambush-watchlist-service/src/ambush_watchlist_model_service/api.py
services/models_services/ambush-watchlist-service/src/ambush_watchlist_model_service/config.py
services/models_services/ambush-watchlist-service/src/ambush_watchlist_model_service/schemas.py
```

## 新增 SQL 契约

```text
infra/sql/0008_decision_ambush_phase1_pattern_library.sql
```

包含：

```text
governance.source_capability_audit_v1
decision_ambush.valley_pattern_library_version_v1
decision_ambush.valley_pattern_sample_v1
decision_ambush.valley_shape_signature_v1
decision_ambush.valley_pattern_prototype_v1
decision_ambush.valley_pattern_match_result_v1
decision_ambush.ambush_daily_window_feature_v1
decision_ambush.ambush_recall_candidate_v1
decision_ambush.ambush_formula_registry_v1
```

## 验证结果

已通过：

```text
python -m pytest tests/test_ambush_phase1_sql_contract.py services/models_services/ambush-watchlist-service/tests -q
# 21 passed

python -m pytest tests services/models_services/ambush-watchlist-service/tests -q
# 27 passed

python -m compileall -q services/models_services/ambush-watchlist-service/src
# passed
```

未执行 Docker 验证，当前容器环境此前无 Docker 命令。

## 重要边界

1. 本阶段不发布正式模型三 signal。
2. `three-channel-recall` 是候选召回和研究事实，不进入买点服务。
3. 历史样本标签可以用后置窗口，但在线召回和评分不能使用未来数据。
4. 缺少复权 OHLC 时，不允许进入正式图库和在线评分。
5. 模型一、模型二保持锁定，不参与本次代码变更。


---

# Phase 2 低谷观察池与有效抬头锚点实现报告

# AMBUSH Phase 2：低谷观察池与有效抬头锚点实现报告

版本：`ambush_watchlist_phase2_valley_turn_v1_0_rc`

## 本阶段边界

本阶段只实现模型三 `ambush-watchlist-service` 的 Phase 2：

1. `valley_watch_pool` 低谷观察池正式计算事实。
2. `effective_turn_anchor_day` 有效抬头锚点识别。
3. `effective_turn_pool` 池间转移审计。
4. Phase 2 一键管道 `/ambush/phase2/run`。

本阶段仍然不是正式推荐信号，不接入 release gate，不接入买点服务，不修改模型一和模型二。

## 新增代码

```text
services/models_services/ambush-watchlist-service/src/ambush_watchlist_model_service/phase2.py
services/models_services/ambush-watchlist-service/tests/test_phase2_valley_turn.py
infra/sql/0009_decision_ambush_phase2_valley_turn.sql
tests/test_ambush_phase2_sql_contract.py
```

修改文件：

```text
services/models_services/ambush-watchlist-service/src/ambush_watchlist_model_service/api.py
services/models_services/ambush-watchlist-service/src/ambush_watchlist_model_service/schemas.py
```

## 新增 API

```text
POST /ambush/phase2/valley-watch-pool
POST /ambush/phase2/effective-turn-anchor
POST /ambush/phase2/pool-transition
POST /ambush/phase2/run
```

## 计算治理已落实

Phase 2 所有正式计算都带有：

```text
formula_code
formula_version
financial_purpose
data_policy
validation_policy
not_a_signal
```

本阶段明确执行以下硬约束：

1. 图形与低谷结构正式计算优先使用 adjusted OHLC。
2. raw OHLC 缺少复权字段时只能进入 research-only。
3. 在线有效抬头识别只使用 `trading_day <= as_of_trading_day` 的数据。
4. 后置反弹数据不得进入 Phase 2 在线计算。
5. hard negative 相似度与 false rebound risk 是低谷观察池阻断因子。
6. 低点后已连续走远的样本默认拒绝，除非属于横盘压缩后突破。

## Phase 2 核心输出

### valley_watch_pool

输出：

```text
pool_state
valley_maturity_score
pattern_match_score
weekly_structure_score
false_rebound_risk
valley_components
risk_components
block_reason_codes
research_only_reason_codes
source_gap_codes
```

状态：

```text
valley_watch
research_only
not_qualified
valley_invalidated
data_blocked
```

### effective_turn_anchor

输出：

```text
l1_status
pool_target
anchor_type
effective_turn_anchor_day
effective_turn_age_days
turn_freshness_score
effective_turn_score
runaway_risk
reject_reason_codes
```

状态：

```text
accepted
backup_only
rejected
```

锚点类型：

```text
first_turn_day
second_turn_day
horizontal_compression_breakout
```

## 新增 SQL 表

```text
decision_ambush.valley_watch_pool_v1
decision_ambush.effective_turn_anchor_v1
decision_ambush.effective_turn_pool_v1
decision_ambush.ambush_pool_transition_audit_v1
```

## 验证结果

```text
pytest tests/test_ambush_phase2_sql_contract.py services/models_services/ambush-watchlist-service/tests/test_phase2_valley_turn.py -q
# 7 passed

pytest tests services/models_services/ambush-watchlist-service/tests -q
# 34 passed

python -m compileall -q services/models_services/ambush-watchlist-service/src
# passed
```

Docker / Postgres 实例级验证未执行。

## 下阶段

下一阶段建议进入：

```text
Phase 3：L2/L3/L4 深度确认、false_rebound release gate、正式 signal 与买点服务接入
```


---

# Phase 3 + Phase 4 后端闭环实施报告

# 模型三 Phase 3 + Phase 4 后端闭环实施报告

## 锁定候选版本

`ambush_watchlist_service_v1.0_rc_backend_closure_candidate`

## 本次范围

本次只修改模型三 `ambush-watchlist-service`，以及新增三模型调度服务设计。未修改已锁定的模型一 `hot-candidates-service` 和模型二 `candidate-memory-service` 的业务代码。

## Phase 3 新增能力

1. `POST /ambush/phase3/deep-confirmation`
   - L2 结构确认
   - L3 资金/量能确认
   - L4 板块/市场确认
   - 可交易性确认
   - 假反弹 release risk 聚合

2. `POST /ambush/phase3/release-gate`
   - 只有 release gate 可发布官方信号。
   - source gap、hard negative、高假反弹、高 runaway、低可交易性全部阻断。

3. `POST /ambush/phase3/run`
   - deep confirmation -> release gate -> signal fact -> buy point reference 一体化。
   - 买点只冻结评估基准价，不构成交易建议。

## Phase 4 新增能力

1. `POST /ambush/phase4/observation`
   - append-only 路径观察。
   - MFE / MAE / close return。

2. `POST /ambush/phase4/outcome`
   - 多标签 outcome。
   - 区分 direction_success、tradable_success、structure_success。

3. `POST /ambush/phase4/failure-attribution`
   - 失败原因归因。
   - 输出 pattern library feedback 动作：positive validation 或 hard negative review。

4. `POST /ambush/finalization/lock-candidate`
   - 输出后端闭环锁定候选报告。

## 新增 SQL

`infra/sql/0010_decision_ambush_phase3_phase4_finalization.sql`

新增表：

- `decision_ambush.deep_confirmation_pool_v1`
- `decision_ambush.ambush_feature_matrix_v1`
- `decision_ambush.ambush_score_fact_v1`
- `decision_ambush.ambush_release_gate_audit_v1`
- `decision_ambush.ambush_signal_fact_v1`
- `decision_ambush.ambush_buy_point_v1`
- `decision_ambush.ambush_observation_snapshot_v1`
- `decision_ambush.ambush_latest_state_v1`
- `decision_ambush.ambush_outcome_label_v1`
- `decision_ambush.ambush_failure_attribution_v1`
- `decision_ambush.ambush_evolution_sample_v1`
- `decision_ambush.ambush_formula_version_evaluation_v1`

## 计算治理落地

所有核心计算均带：

- formula_code
- formula_version
- financial_purpose
- data_policy
- validation_policy / hard_rule

硬规则：

- Phase 1/2/3 不允许使用未来数据。
- Phase 4 才允许使用 post-signal bars 做 outcome label。
- outcome/observation/failure attribution 全部 append-only。
- 没有 release gate 通过，不生成 official signal。
- 买点是评估基准价，不是交易建议。

## 验证结果

```bash
python -m pytest tests/test_ambush_phase3_phase4_sql_contract.py services/models_services/ambush-watchlist-service/tests/test_phase3_phase4_finalization.py -q
# 6 passed

python -m pytest tests services/models_services/ambush-watchlist-service/tests -q
# 40 passed

python -m compileall -q services/models_services/ambush-watchlist-service/src
# passed
```

## 未验证范围

- 真实 Postgres migration。
- 真实 provider 数据回放。
- Docker / 容器级启动。
- 多服务 live dispatch。

以上不影响本次后端代码级、契约级、单元测试级锁定候选。
