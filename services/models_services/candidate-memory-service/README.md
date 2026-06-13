# candidate-memory-service README

> 唯一模型根目录 MD。已整合当前契约、最终设计和各阶段闭环报告。
> 锁定版本：`candidate_memory_service_v1.0_rc_backend_closure_candidate`。未经用户明确批准，不得修改模型二业务代码、字段、表结构、公式或发布闸门。


---

# 当前服务契约与 API

# candidate-memory-service 当前契约

端口：`8032`
模型版本：`candidate_memory_v1`

## 定位

历史候选记忆模型。它把历史同花顺付费候选转成可追踪记忆对象，判断离开短窗口后的延迟兑现、二波、慢趋势和失效风险。

## API

- `GET /health`
- `GET /healthz`
- `GET /readyz`
- `POST /score`

`/score` 请求：

```json
{
  "row": {},
  "as_of_time_utc": "datetime|null",
  "run_id": "string|null"
}
```

响应：

```json
{
  "model_name": "candidate_memory",
  "model_version": "candidate_memory_v1",
  "structured_output": {
    "contract": {}
  },
  "jarvis_payload": {},
  "contract_gaps": []
}
```

## 数据入口

生产调用由 `research-service /candidate-memory/runs` 发起。模型只接收 `row`，不采集 provider，不写库。

核心字段：

- `memory_id`
- `appearance_id`
- `appearance_count`
- `batch_id` 或 `latest_batch_id`
- `candidate_id` 或 `latest_candidate_id`
- `ingest_mode`
- `contract_audit_status`
- `p_limit_up` 或 `max_p_limit_up`
- `p_limit_up_source`、`max_p_limit_up_source`、`latest_p_limit_up_source` 或 `prior_p_limit_up_source`
- `instrument_id`
- `symbol`
- `daily_bars` 或 `price_path`
- `stock_rank`
- `memory_age_days`、`candidate_memory_age_days` 或 `days_since_last_candidate`
- `appearance_events`

## 准入

必须满足：

- `ingest_mode=external_ths_model`
- `contract_audit_status=passed`
- 有生产候选批次和候选项
- 有付费同花顺 prior
- 有证券身份
- 有有效日线
- 有交易日历年龄

硬阻断：

- `public_limitup_draft_not_allowed`
- `invalid_candidate_ingest_mode`
- `missing_production_candidate_batch`
- `missing_production_candidate_item`
- `contract_audit_not_passed`
- `missing_paid_ths_prior`
- `missing_instrument_identity`
- `missing_daily_price_path`
- `missing_trading_calendar`
- `missing_trading_calendar_memory_age`
- `invalid_trading_calendar_memory_age`

缺交易日历年龄时不补 0，输出 `memory_age_days=null`、`blocked_data_gap` 和 `source_gap:missing_trading_calendar_memory_age`。

## 评分

分量：

- `historical_candidate_quality`
- `post_candidate_trend_quality`
- `quiet_accumulation_score`
- `second_wave_setup_score`
- `upside_room_score`
- `breakdown_failure_risk`

公式：

```text
memory_hit_8pct_score =
0.20*historical
+0.25*trend
+0.20*accumulation
+0.20*second_wave
+0.15*upside
-0.30*breakdown
```

缺任一分量或有硬阻断时 `memory_hit_8pct_score=null`。

## 状态

```text
production candidate appearance
-> candidate_memory_entity
-> evidence_snapshot
-> feature_matrix
-> analysis state
-> state_history / outcome_label / performance
```

- 有硬阻断：`blocked_data_gap`。
- 缺评分分量：`memory_watch`。
- `breakdown_failure_risk >= 70`：`memory_invalidated`。
- `second_wave_setup_score >= 70`、`breakdown < 45`、`memory_age_days` 在 5-20、结构证据数至少 2：`memory_reactivated`。
- `trend >= 60` 且 `breakdown < 50`：`memory_active`。
- `memory_age_days > 30`：`memory_decayed`。
- 其他：`memory_watch`。

## 编排层异常兜底

`research-service` 按记忆对象逐条调用 `/score`。单条异常不终止整批：

- run warning：`candidate_memory:row_failed:{symbol}:score:{error_code}`。
- 合同状态：`memory_state=blocked_data_gap`、`publication_state=blocked`、`memory_hit_8pct_score=null`。
- 缺口码：`source_gap:model_service_scoring_failed`、`source_gap:model_service_exception:{error_code}`；缺年龄时继续写 `source_gap:missing_trading_calendar_memory_age`。
- 证据：`feature_payload_json.model_service_failure` 保留 `stage`、`run_id`、`symbol`、`instrument_id`、`error_code`、`error_message`、输入引用。
- 落库：仍写 entity、evidence_snapshot、feature_matrix、analysis、state_history 和 transition_audit。
- job 计数：异常行进入 `failed_count`，成功数不包含异常兜底行。

状态审计：正式评分任务写真实 `job_run_id`；通用候选分析触发时写 `ad_hoc:{score_stage}`，状态变化不得丢失。

## 输出字段

- `schema_version=candidate_memory_contract_v1`
- `run_id`
- `model_version`
- `symbol`
- `name`
- `memory_id`
- `appearance_count`
- `latest_candidate_trading_day`
- `memory_age_days`
- `memory_hit_8pct_score`
- `memory_state`
- `publication_state`
- `score_breakdown`
- `structure_evidence_count`
- `main_positive_factors`
- `main_negative_factors`
- `hard_block_reasons`
- `source_gap_codes`
- `evidence_refs`
- `feature_payload_json`
- `feature_hash`
- `score_hash`

## 落库和下游

由 `research-service` 写入：

- `decision.candidate_memory_entity`
- `decision.candidate_memory_appearance`
- `decision.candidate_memory_evidence_snapshot_v1`
- `decision.candidate_memory_feature_matrix_v1`
- `decision.candidate_memory_analysis_v1`
- `decision.candidate_memory_state_history`
- `decision.candidate_memory_state_transition_audit_v1`
- `decision.candidate_memory_outcome_label_v1`
- `decision.candidate_memory_performance_metric_v1`

下游：

- gateway/frontend 展示历史二波列表和详情。
- research-data-mart 同步研究快照和成熟标签。
- execution-timing-service 读取统一信号后生成买点版本。
- Jarvis 只读解释。

## 调度

- 候选记忆评分：`09:00:00,09:40:00,11:50:00,15:40:00,16:20:00`。
- 候选记忆标签：`15:55:00,18:20:00`。

## 不变量

- `memory_age_days` 可为 `NULL`；非空必须 `>=0`。
- `memory_reactivated` 必须有非空且 5-20 的 `memory_age_days`。
- 公开涨停草稿不得进入生产记忆链路。
- Jarvis 和前端不得反写状态或分数。


---

# 最终设计说明

# 候选记忆模型 candidate_memory 最终设计说明 v1.0 RC

> 文件位置：`services/models_services/candidate-memory-service/README.md（已合并）`  
> 锁定口径：`candidate_memory_service_v1.0_rc_backend_closure_candidate`  
> 对应包：`ai_stock_candidate_memory_phase5_closed_loop.zip`  
> 状态：已拍板锁定。除非真实验收暴露问题并经用户明确同意，否则不得修改代码、字段、契约或模型逻辑。

---

## 1. 模型定位

候选记忆模型不是历史候选股列表，也不是热点模型的延长线。它是神策中心中专门研究“历史热点候选后续二次上涨前置信号和上涨原因”的独立模型。

一句话定义：

```text
候选记忆模型负责研究：曾经进入热点模型的股票，在离开短窗口后，是否正在重新积累可提前观察到的二次上涨原因。
```

它不复用热点模型第一次信号作为推荐，不把历史入选等同于现在可买。每次正式激活必须生成新的 `memory_signal_id`。

---

## 2. 核心金融假设

用户观察到：能够进入热点模型的股票，后期出现涨停的概率可能大于从未进入过热点模型的股票。

模型二将该观察提升为可验证假设：

```text
在控制板块、市值、换手率、波动率、近期涨幅和市场环境后，历史热点入选本身是否仍然提供后续涨停或二波启动的增量信息价值。
```

因此必须设计 matched control / uplift research，避免把高波动股、题材股本身的自然涨停倾向误认为模型 alpha。

---

## 3. 与其他模型的边界

热点模型关注：

```text
外部热度已经显性化后的 T+1 / T+5 短窗口兑现。
```

候选记忆模型关注：

```text
历史热点沉淀后，再次涨停前 1 / 3 / 5 / 10 个交易日是否出现可提前观察的前置信号。
```

潜伏抬头模型关注：

```text
没有历史热点先验的全市场低谷刚抬头结构。
```

候选记忆模型的独特性在于：它有历史热点注意力先验，并研究这份注意力是否在未来重新激活。

---

## 4. 核心对象

模型二独立使用 `decision_memory.*` 域。

核心对象：

```text
memory_seed                     从热点成熟样本沉淀出的记忆种子
memory_entity                   长期记忆实体
memory_initial_snapshot          首次来源事实冻结
memory_observation_snapshot      append-only 持续观察
memory_pre_signal_case           二次上涨前兆案例
memory_activation_case           二次激活案例
memory_feature_matrix            特征矩阵
memory_score_fact                评分事实
memory_release_gate_audit        发布闸门审计
memory_signal_fact               正式二次信号
memory_buy_point                 买点评估基准价
memory_monitoring_snapshot       信号后路径监控
memory_outcome_label             成熟结果标签
memory_up_reason_attribution     上涨原因归因
memory_failure_attribution       失败归因
memory_evolution_sample          进化样本
memory_ttl_calibration           TTL 校准
memory_matched_control_uplift    对照组增量研究
memory_model_version_evaluation  版本评估
```

硬原则：`memory_entity` 是长期研究对象；`memory_signal_id` 是每一次正式激活信号。两者不能混用。

---

## 5. memory_seed 进入规则

不是所有热点样本都进入记忆池。优先进入：

```text
短窗口失败但 MFE 接近目标
T+5 未达标但 T+20 迟到达标
方向成功但买点错过
blocked-but-track 后续走强
教师概率低但本地纠偏成功
高教师概率但短期失败，后续有研究价值
首次题材仍有持续性
结构未彻底破坏
```

禁止进入：

```text
数据污染样本
严重不可交易样本
退市/ST/停牌风险样本
短窗口后结构彻底破坏且持续阴跌
纯一字不可成交且无后续研究价值样本
```

---

## 6. memory_entity 与 TTL

`memory_entity` 代表某只股票从某次首次热点发现开始形成的一条记忆线。

TTL 不是固定天数，而是历史热点记忆对当前上涨解释力的动态衰减过程。

影响 TTL 的因素：

```text
首次热点质量
首次失败类型
MFE / MAE
是否迟到达标
板块持续性
价格结构是否保持
资金是否撤退
是否仍在原题材周期内
是否出现全新题材替代
市场环境变化
```

关键原则：

```text
TTL 过期不代表股票不会涨；
TTL 过期只代表第一次热点记忆对当前上涨的解释力下降。
```

TTL 过期后发生的涨停，如果原因与首次热点无关，应打为 `new_independent_cycle`，不得计为候选记忆模型成功。

---

## 7. 前置信号体系

模型二的核心不是二波确认，而是二波前兆。

必须研究：

```text
涨停前 1 / 3 / 5 / 10 个交易日，哪些信号已经可见。
```

前置信号包括：

```text
资金流出减弱
资金重新回流
成交额温和恢复
缩量不跌
低点抬高
回踩不破
横盘压缩
接近前高
突破压力前蓄势
板块强度回暖
题材消息重新出现
同题材个股先动
短线情绪修复
```

`memory_pre_signal_case` 是模型二区别于热点模型的关键对象。它表示：历史记忆已经出现二次上涨前兆，但尚未正式激活。

---

## 8. 上涨原因归因

候选记忆模型必须解释“为什么后面涨”，但要严格区分事前和事后。

原因类型：

```text
attention_memory_retention       市场注意力记忆
capital_memory_reactivation      资金记忆重新激活
structure_repair_breakout        结构修复突破
theme_second_catalyst            题材二次催化
sector_resonance_return          板块再共振
delayed_catch_up_realization     补涨兑现
divergence_to_consensus          分歧转一致
market_risk_appetite_recovery    风险偏好修复
fake_activation                  假激活
breakout_trap                    突破诱多
new_independent_cycle            全新独立周期
```

归因必须分成：

```text
pre_signal_reason          决策前已经可见的原因
confirmed_up_reason        后续被验证的原因
post_hoc_explanation       涨后市场解释，不得进入生产评分
```

生产评分只能使用 `available_at <= decision_time` 的 `pre_signal_reason`。

---

## 9. 数据源与消息及时性

模型二对数据广度和消息及时性要求高。

P0 数据：

```text
热点成熟样本
日线行情
分钟行情
成交额 / 换手率
涨跌停状态
资金流
板块强度
市场情绪
公告 / 新闻基础事件
交易日历
可交易状态
```

P1 数据：

```text
题材 / 概念标签
产业链关系
同题材联动
板块涨停家数
龙头 / 补涨关系
互动平台
政策新闻
产品涨价
分时资金承接
```

消息数据必须记录：

```text
event_time
published_at
available_at
captured_at
source
source_reliability
entity_linked_symbol
theme_tags
event_type
importance_score
dedup_hash
```

硬规则：

```text
available_at > decision_time 的消息不得进入 pre_signal_score。
涨停后才出现的新闻或复盘解释，只能进入 post_hoc_explanation。
```

---

## 10. 评分结构

模型二不能只有一个总分。至少拆成四个分数：

```text
memory_value_score       这条历史记忆还有没有研究价值
pre_signal_score         二次上涨前兆是否已经出现
activation_quality_score 是否到了可正式激活的程度
reason_confidence_score  上涨驱动假设是否清晰
```

release gate 不能只看总分，必须要求：

```text
memory_value_score 达标
pre_signal_score 达标
activation_quality_score 达标
fake_activation_risk 可控
reason_confidence_score 不低
available_at 合规
可交易性达标
无重复激活污染
```

---

## 11. 结果标签

模型二 outcome 必须区分：

```text
next_limit_up_hit
time_to_next_limit_up
second_wave_success
delayed_realization
new_independent_cycle
fake_activation_failure
activation_too_early
activation_too_late
ttl_too_short
ttl_too_long
capital_memory_confirmed
sector_resonance_confirmed
structure_repair_confirmed
theme_second_catalyst_confirmed
direction_success_execution_missed
tradable_success
entry_too_late
post_hoc_only_reason
```

最关键指标：

```text
pre_signal_lead_days
```

它回答：模型最早提前几天发现有效前兆。

---

## 12. matched control / uplift 研究

必须验证：热点入选组是否真的比匹配未入选组有更高后续涨停率。

入选组：

```text
曾经进入热点模型的股票，从 first_selected_date 起算 T+5 / T+10 / T+20 / T+30。
```

对照组匹配维度：

```text
同板块
相近市值
相近价格区间
相近换手率
相近波动率
相近近20日涨幅
相近近期涨停状态
相近市场环境
```

对比：

```text
next_limit_up_rate
time_to_next_limit_up
relative_sector_return
risk_adjusted_return
drawdown_difference
uplift_rate
```

只有通过对照组验证，历史热点入选本身才可被视为模型二的增量先验。

---

## 13. 失败归因与进化

失败不能简单写成 failed。至少要区分：

```text
fake_activation
activation_too_early
activation_too_late
ttl_decay_failure
execution_missed
moneyflow_not_confirmed
sector_not_resonant
new_independent_cycle
post_hoc_only_reason
```

进化重点：

```text
TTL
记忆衰减曲线
pre_signal 阈值
activation threshold
fake_activation penalty
资金回流权重
板块再共振权重
买点规则
```

pending outcome、post_hoc-only 样本、new_independent_cycle 不得进入正式进化成功样本。

---

## 14. 调度要求

候选记忆模型需要多源异步和动态升频。

```text
普通 memory_entity：15-30 分钟观察
pre_signal_case：1-5 分钟观察
activation_case：高频观察
expired / invalidated：降频或关闭
消息 / 公告：准实时扫描
TTL / decay：每日更新
up_reason_attribution：收盘后 / T+N 生成
evolution：离线批处理
```

需要为 scheduler v2 提供 `model_schedule_contract`，明确每个阶段的数据依赖、新鲜度 SLA、硬阻断、升降频和输出事件。

---

## 15. 高性能设计

模型二可能沉淀大量 `memory_entity`，不能全量高频扫。

必须有：

```text
memory_active_case_registry
memory_latest_state
memory_observation_snapshot append-only
memory_pre_signal_feature_window
memory_event_signal_feature
```

原则：

```text
从 registry 拉 due cases
批量读取特征
批量生成 observation
批量更新 latest_state
根据状态调整 next_observe_at
```

---

## 16. 验收标准

```text
1. 每次正式激活生成新的 memory_signal_id。
2. post_hoc 消息不得进入 pre_signal_score。
3. available_at > decision_time 的消息不得进入生产评分。
4. new_independent_cycle 不计为模型成功。
5. pending outcome 不得进入 evolution。
6. matched control 可计算 uplift。
7. TTL calibration 只用 mature outcome 和 cutoff_time 前样本。
8. direction_success / tradable_success / execution_success 分离。
9. pre_signal_lead_days 可回放。
10. 普通 memory_entity 不被全量高频扫。
```

---

## 17. 锁定说明

该文档记录的是已拍板的候选记忆模型后端设计口径。后续未经用户明确同意，不得修改模型二代码、字段、表结构、契约和业务逻辑。真实 PostgreSQL、真实 provider、scheduler v2 或多交易日 replay 暴露问题时，应以“验收问题回补”形式提出，待用户确认后处理。


---

# CANDIDATE_MEMORY_PHASE1_PRE_SIGNAL_CHAIN_REPORT

# Candidate Memory Phase 1：二次上涨前置信号链路实现报告

## 定位

本轮将 `candidate_memory` 从“历史候选评分器”升级为：

> 历史热点候选的二次上涨前置信号与上涨原因研究模型。

它不复用热点模型信号，不把 `memory_entity` 当推荐信号。每次正式二次激活必须生成新的 `memory_signal_id`。

## 已实现的生产分阶段接口

- `POST /production/seed/build`
- `POST /production/entity/build`
- `POST /production/pre-signal/window`
- `POST /production/pre-signal/detect`
- `POST /production/activation/evaluate`
- `POST /production/release-gate/evaluate`
- `POST /production/buy-point/evaluate`
- `POST /production/outcomes/mature`
- `POST /production/up-reason/build`
- `POST /production/evolution/build`

兼容旧版：

- `POST /score` 保留为旧评分合同入口；正式生产链路使用 `/production/*`。

## 已实现的核心后端逻辑

### 1. memory seed

从热点模型成熟样本生成记忆种子，重点支持：

- `direction_success_execution_missed`
- `delayed_success`
- `t20_delayed_success`
- `blocked_but_track_later_success`
- `teacher_underestimated_success`
- `failed_but_high_mfe`

同时阻断：

- 非热点来源
- 缺首次来源信号
- ST / 停牌 / 退市风险
- 数据污染
- 首次结构彻底失效

### 2. memory entity

实现独立 `memory_entity` 对象，支持：

- TTL
- dynamic TTL adjustment
- decay_score
- merge / create new entity 判断
- memory_entity 不是 signal 的 guardrail

### 3. pre-signal feature window

实现前置信号窗口，重点计算：

- `memory_value_score`
- `pre_signal_score`
- `structure_score`
- `moneyflow_reactivation_score`
- `sector_resonance_return_score`
- `event_freshness_relevance_score`
- `market_risk_appetite_score`
- `ttl_health_score`
- `fake_activation_risk_score`

### 4. 消息及时性

实现 ex-ante / post-hoc 分离：

- 生产前置信号只使用 `available_at <= decision_time` 的消息。
- `available_at > decision_time` 的消息只进入 post-hoc，不参与 `pre_signal_score`。
- 缺 `available_at` 的事件进入 gap，不作为可用前置信号。

### 5. pre_signal_case

当前置信号满足强度、TTL、假激活风险等条件后生成 `pre_signal_case`。

### 6. activation_case

从前置信号升级为激活候选，计算 `activation_quality_score`，但仍不是正式推荐。

### 7. release gate

正式信号前硬阻断：

- 重复 active memory signal
- TTL 不健康
- pre_signal_score 不达标
- activation_quality 不达标
- fake_activation_risk 过高
- 资金和板块均不确认
- 不可交易
- 数据时间合同失败

通过后生成新的 `memory_signal_id`，不复用热点模型 signal。

### 8. buy point

候选记忆买点区别于热点模型：

- 只允许 `breakout_confirmed_entry` / `pullback_confirmed_entry` 冻结正式基准价。
- `pre_signal_waiting` 不冻结正式买点。
- `latest_price` / `previous_close` 不得冻结正式买点。

### 9. outcome

区分：

- `second_wave_success`
- `delayed_realization`
- `fake_activation_failure`
- `new_independent_cycle`
- `second_wave_failed`

其中 `new_independent_cycle` 不计为候选记忆模型成功。

### 10. up reason attribution

独立区分：

- `pre_signal_reason_codes`
- `confirmed_up_reason_codes`
- `post_hoc_explanation_codes`

生产评分只允许使用 `pre_signal_reason_codes`。

### 11. evolution sample

只有 mature outcome 才能生成可用 evolution sample。

pending outcome、new independent cycle 会被阻断，避免污染模型进化。

## 新增 SQL

新增：

- `infra/sql/0003_decision_memory_model_v1.sql`

核心 schema：

- `decision_memory.memory_seed_v1`
- `decision_memory.memory_entity_v1`
- `decision_memory.memory_initial_snapshot_v1`
- `decision_memory.memory_observation_snapshot_v1`
- `decision_memory.memory_price_structure_feature_v1`
- `decision_memory.memory_moneyflow_feature_v1`
- `decision_memory.memory_sector_theme_feature_v1`
- `decision_memory.memory_event_signal_feature_v1`
- `decision_memory.memory_pre_signal_feature_window_v1`
- `decision_memory.memory_pre_signal_case_v1`
- `decision_memory.memory_activation_case_v1`
- `decision_memory.memory_release_gate_audit_v1`
- `decision_memory.memory_signal_fact_v1`
- `decision_memory.memory_buy_point_v1`
- `decision_memory.memory_outcome_label_v1`
- `decision_memory.memory_up_reason_attribution_v1`
- `decision_memory.memory_pre_limitup_signal_analysis_v1`
- `decision_memory.memory_failure_attribution_v1`
- `decision_memory.memory_evolution_sample_v1`
- `decision_memory.memory_ttl_calibration_v1`
- `decision_memory.memory_model_version_evaluation_v1`
- `decision_memory.memory_active_case_registry_v1`
- `decision_memory.memory_latest_state_v1`

## 验证结果

已执行：

```text
candidate-memory-service：18 passed
SQL contract：2 passed
compileall：通过
FastAPI TestClient smoke test：通过
```

Docker 说明：当前容器无 Docker 环境，未执行 Docker Compose / Postgres 真实部署验证。

## 当前阶段结论

本包不是最终定版，而是第二模型的第一阶段代码落地：

> Candidate Memory Phase 1：前置信号链路与上涨原因研究骨架。

下一阶段应继续补：

1. 生产级 Postgres repository。
2. memory_active_case_registry 批量观察与动态升频。
3. source event / theme / sector 标准化接入。
4. matched control / uplift research。
5. TTL calibration 离线任务。
6. scheduler v2 统一调度前的模型调度契约输出。


---

# CANDIDATE_MEMORY_PHASE2_VALIDATION_REPORT

# Candidate Memory Phase 2 Validation Report

## Phase name

Candidate Memory Phase 2：候选记忆模型生产持久化、批量观察、数据及时性与 TTL 校准增强版。

## Scope

本阶段在 Phase 1 的前置信号链路基础上，继续补齐候选记忆模型后端闭环的 P0 工程能力：

1. 事件 / 消息标准化：将消息分为 ex_ante、post_hoc、not_visible，防止后视镜污染。
2. 活跃 memory_entity 注册表：根据 memory_status、pre_signal、activation 动态决定观察频率。
3. 批量 observation：支持最多 1000 条 active memory case 一次性观察，生成 append-only observation、latest_state 投影、registry 更新。
4. SQLite 本地持久化合同：验证 append-only、latest_state projection、registry due query 的生产语义。
5. matched control / uplift 研究：验证“进入热点模型后的后续涨停概率优势”不能直接和全市场比，必须和匹配对照组比。
6. TTL calibration：只使用 cutoff_time 之前已经 mature 的 outcome，排除 pending 和 new_independent_cycle。
7. SQL Phase 2 扩展：补充 source relationship layer、matched-control uplift、event feature batch 表。

## New files

- `services/models_services/candidate-memory-service/src/candidate_memory_model_service/phase2.py`
- `services/models_services/candidate-memory-service/src/candidate_memory_model_service/persistence.py`
- `services/models_services/candidate-memory-service/tests/test_candidate_memory_phase2_persistence_and_calibration.py`
- `infra/sql/0004_decision_memory_phase2_research_calibration.sql`
- `CANDIDATE_MEMORY_PHASE2_VALIDATION_REPORT.md`

## New endpoints

- `POST /production/events/standardize`
- `POST /production/registry/upsert`
- `POST /production/observations/bulk`
- `POST /production/matched-control/uplift`
- `POST /production/ttl-calibration/build`

## Guardrails added

- Production pre-signal scoring uses only `available_at <= decision_time` event evidence.
- Future or missing-available_at events are excluded from ex-ante scoring.
- Post-hoc explanation is retained for research but never used as pre-signal score.
- observation remains append-only; latest_state is only a projection.
- active registry is scheduler state, not model training truth.
- matched-control uplift must pass sample gate before it can be treated as valid alpha evidence.
- TTL calibration uses only mature samples before cutoff and excludes `new_independent_cycle`.

## Validation executed

From `services/models_services/candidate-memory-service`:

```text
pytest -q
24 passed
```

From repo root:

```text
pytest -q tests/test_candidate_memory_sql_contract.py services/models_services/candidate-memory-service/tests
26 passed
```

Compile validation:

```text
python -m compileall -q services/models_services/candidate-memory-service/src infra/sql
passed
```

FastAPI smoke test:

```text
GET /healthz -> 200
POST /production/registry/upsert -> 200
```

## Not executed

Docker Compose / real PostgreSQL / real source provider ingestion were not executed in this environment.

## Current status

This package is a Candidate Memory Phase 2 backend implementation package, not a final production定版. 下一阶段建议继续补齐：

1. Postgres repository for real `decision_memory.*` writes.
2. DB-backed due active case pull + batch observation transaction.
3. Source event/theme relationship real provider ingestion.
4. Model-stage schedule contract for scheduler v2.
5. Multi-day replay using real hot model mature samples.


---

# CANDIDATE_MEMORY_PHASE3_PRODUCTION_REPOSITORY_SCHEDULE_REPORT

# Candidate Memory Phase 3：生产仓储、due-case 调度计划与调度契约增强

## 本阶段目标

将候选记忆模型从 Phase 2 的本地持久化和校准骨架，推进到更接近生产部署的后端形态：

1. PostgreSQL repository 合同；
2. DB-backed active registry due-case 观察计划；
3. 特征新鲜度 readiness audit；
4. pre-limitup 前置信号提前量分析；
5. candidate_memory model_schedule_contract，为后续 scheduler v2 统一整改做准备。

## 新增代码

- `candidate_memory_model_service/phase3.py`
- `candidate_memory_model_service/postgres_repository.py`
- `infra/sql/0005_decision_memory_phase3_production_repository_and_schedule.sql`
- `tests/test_candidate_memory_phase3_sql_contract.py`
- `candidate-memory-service/tests/test_candidate_memory_phase3_repository_schedule.py`

## 新增接口

- `POST /production/features/readiness`
- `POST /production/observations/due-plan`
- `POST /production/pre-limitup/analyze`
- `POST /production/schedule/contract`

## 关键约束

- 模型服务只观察 active registry 中到期的 memory_entity；
- 关闭、失效、彻底过期的 entity 不再被调度；
- feature watermark 未来时间硬阻断；
- price/tradability 等关键特征不新鲜时阻断 official 阶段；
- pre-limitup analysis 只统计涨停前已经可见的前置信号；
- governance/scheduler 只保存调度元数据，不保存模型业务真相。

## 验证范围

- feature readiness hard block；
- due plan priority 排序与 closed/not-due 过滤；
- pre-limitup lead_days 计算；
- schedule contract 多频率声明；
- Postgres repository SQL 合同；
- SQL schema contract；
- compileall。

## 尚未完成

- 未连接真实 PostgreSQL 服务执行 DDL；
- 未接入真实 source provider；
- 未执行 5-20 个交易日真实 replay；
- scheduler v2 统一调度编排尚未开始，应在三大模型设计完后单独整改。


---

# CANDIDATE_MEMORY_PHASE4_PRODUCTION_CHAIN_ACCEPTANCE_REPORT

# Candidate Memory Phase 4：生产链路验收增强版

## 版本定位

本阶段将候选记忆模型从 Phase 3 的“生产仓储合同 + due-case 调度计划”推进到：

```text
生产链路验收候选版：
source typed feature standardization
-> stage persistence plan
-> pre-signal threshold calibration
-> multi-day replay validation
-> phase acceptance check
```

本阶段仍不声称已完成真实 Docker/PostgreSQL/真实 provider 的线上终验；它完成的是第二个模型在代码和合同层面的生产链路闭环增强。

## 新增代码

```text
services/models_services/candidate-memory-service/src/candidate_memory_model_service/phase4.py
services/models_services/candidate-memory-service/tests/test_candidate_memory_phase4_production_chain.py
infra/sql/0006_decision_memory_phase4_production_chain_acceptance.sql
tests/test_candidate_memory_phase4_sql_contract.py
```

## 新增生产接口

```text
POST /production/source/features/build
POST /production/persistence/plan
POST /production/pre-signal/threshold-calibration
POST /production/replay/multi-day
POST /production/phase4/acceptance
```

## 关键增强

### 1. source typed feature standardization

新增 `build_source_feature_snapshot`，将宽源数据整理为候选记忆模型可直接读取的 typed feature：

```text
price_structure_feature
moneyflow_feature
sector_theme_feature
event_signal_feature
tradability_feature
feature_watermarks
```

核心原则：模型阶段不直接扫描原始新闻 JSON 或历史行情明细，而是读取标准化后的特征快照。

### 2. 消息及时性继续硬化

事件被严格划分：

```text
ex_ante：available_at <= decision_time
post_hoc/future：available_at > decision_time
missing_available_at：不可用于生产前置信号
```

未来消息和涨后复盘消息只进入 post_hoc，不进入 pre_signal_score。

### 3. stage persistence plan

新增 `build_stage_persistence_plan`，明确每个生产阶段对应的 repository 方法、事务边界、写入模式和幂等键。

阶段包括：

```text
memory_seed
memory_entity
pre_signal_case
activation_case
release_gate + signal
buy_point
outcome_label
up_reason_attribution
evolution_sample
```

pending outcome 被硬阻断，不允许作为 mature truth 进入进化样本。

### 4. PostgreSQL repository 阶段写入方法补强

新增/增强：

```text
save_memory_seed
upsert_memory_entity
save_activation_case
save_release_gate_and_signal
save_buy_point
save_mature_outcome
```

继续保持：

```text
observation append-only
latest_state projection-only
stage-level transaction boundary
ON CONFLICT idempotency
```

### 5. pre-signal threshold calibration

新增 `build_pre_signal_threshold_calibration`，只使用：

```text
mature outcome
cutoff_time 前已成熟样本
ex_ante pre_signal
非 new_independent_cycle 样本
```

输出 recommended pre-signal / activation threshold，但状态为 `ready_for_shadow_validation`，不能自动改生产阈值。

### 6. multi-day replay validation

新增 `build_multi_day_replay_validation`，用于验证：

```text
前置信号提前量
future/post_hoc 消息泄露
second_wave / delayed_realization / new_independent_cycle 区分
tradable_success 与 direction_success_execution_missed 区分
```

### 7. Phase 4 acceptance check

新增验收检查：

```text
postgres_stage_transactions
source_feature_standardization
due_case_db_plan
multi_day_replay
pre_signal_threshold_calibration
ex_ante_message_guardrail
new_cycle_exclusion
```

## 已执行验证

```text
candidate-memory-service tests：35 passed
candidate memory SQL contract tests：4 passed
合计 targeted validation：39 passed
compileall：通过
FastAPI TestClient smoke test：5 个 Phase 4 新 endpoint 全部 200
```

说明：尝试执行全仓库 pytest 时，非本阶段相关的 market-data/news/ambush/hot 测试因当前容器缺少 `db_schema`、`sqlalchemy` 或包路径冲突而无法收集。这不是本阶段新增代码导致的失败。本阶段已对 candidate-memory-service 与 candidate-memory SQL contract 做定向验证。

## 当前边界

本阶段可称为：

```text
Candidate Memory Phase 4 production-chain acceptance candidate
```

但还不能称为线上生产最终版，因为当前容器仍无法完成：

```text
Docker Compose 全服务启动
PostgreSQL 真实初始化
真实 provider 接入
scheduler v2 全链路编排
5-20 个交易日真实 replay
```

这些需要在你的真实部署环境执行。


---

# CANDIDATE_MEMORY_PHASE5_CLOSED_LOOP_REPORT

# Candidate Memory Phase 5 闭环验收报告

## 阶段定位

Phase 5 将候选记忆模型从 Phase 4 的“生产链路验收候选版”推进为“闭环定版候选版”。本阶段重点不是继续堆叠单点特征，而是把候选记忆模型的完整研究闭环收口：

```text
memory seed
-> memory entity
-> typed source feature
-> feature readiness watermark audit
-> pre-signal feature window
-> pre-signal case
-> activation case
-> release gate
-> buy point
-> mature outcome
-> up reason attribution
-> failure attribution
-> evolution sample
-> model version shadow evaluation
-> final acceptance
```

## 新增代码

```text
services/models_services/candidate-memory-service/src/candidate_memory_model_service/phase5.py
services/models_services/candidate-memory-service/tests/test_candidate_memory_phase5_closed_loop.py
infra/sql/0007_decision_memory_phase5_closed_loop_finalization.sql
tests/test_candidate_memory_phase5_sql_contract.py
```

## 新增 API

```text
POST /production/closure/run
POST /production/failure-attribution/build
POST /production/model-version/shadow-evaluate
POST /production/phase5/final-acceptance
```

## 新增能力

### 1. 闭环管线验证

`/production/closure/run` 用于 side-effect free 的闭环验证。它不会替代生产分阶段调度，只证明独立阶段之间的字段、状态和 guardrail 可以完整串起来。

硬规则：

```text
1. closure endpoint 不是生产 scheduler 主入口。
2. 每个生产阶段仍然保持独立 endpoint 与独立事务边界。
3. future/post_hoc 事件不得进入 pre_signal_score。
4. mature outcome 才能进入 evolution。
5. new_independent_cycle 不计为候选记忆模型成功。
6. 方向成功、可交易成功、买点成功分离。
```

### 2. 失败归因

新增 `memory_failure_attribution`，用于区分：

```text
fake_activation
activation_too_late
ttl_decay_failure
execution_missed
second_wave_failed
excluded_new_independent_cycle
not_failure
```

关键 guardrail：

```text
单个失败样本不得直接判定为模型系统性失败。
```

### 3. 模型版本影子评估

新增 `/production/model-version/shadow-evaluate`。

只允许使用：

```text
label_maturity_status = mature
matured_at <= evaluation_cutoff_time
pre_signal_visible_before_activation = true
outcome_label != new_independent_cycle
```

用于验证候选版本是否优于基线版本。未通过 shadow evaluation，不允许进入版本晋级。

### 4. Phase 5 最终验收

新增 `/production/phase5/final-acceptance`，验收项包括：

```text
stage_endpoints_split
postgres_stage_repository_contract
source_typed_feature_contract
due_case_registry_plan
feature_watermark_hard_block
ex_ante_message_guardrail
pre_signal_chain
release_gate_guardrails
buy_point_direction_execution_split
mature_outcome_only_evolution
new_independent_cycle_exclusion
failure_attribution
ttl_calibration
threshold_calibration
matched_control_uplift
multi_day_replay
model_version_shadow_evaluation
schedule_contract_ready_for_scheduler_v2
```

## 新增 SQL

```text
decision_memory.memory_closure_pipeline_v1
decision_memory.memory_up_reason_attribution_v1
decision_memory.memory_failure_attribution_v1
decision_memory.memory_evolution_sample_v1
decision_memory.memory_model_version_shadow_evaluation_v1
governance.model_phase_final_acceptance_v1
```

## 验证结果

已执行：

```text
candidate-memory-service 全量测试：40 passed
candidate memory SQL contract：5 passed
compileall：通过
FastAPI TestClient 新接口 smoke test：通过
```

## 当前结论

候选记忆模型已经完成闭环候选版。它现在具备：

```text
历史热点样本沉淀
前置信号识别
消息及时性 guardrail
激活与发布闸门
买点评估
成熟结果打标
上涨原因归因
失败归因
TTL / 阈值校准
matched control / uplift 研究
多交易日 replay 验证
版本影子评估
最终验收入口
```

## 边界说明

当前仍未在本容器完成：

```text
真实 PostgreSQL 初始化与事务写入
真实 provider 接入
scheduler v2 编排
5-20 个交易日真实 replay
Docker Compose 全服务验收
```

因此本阶段可以定位为：

```text
candidate_memory_service_v1.0_rc_backend_closure_candidate
```

不是线上最终部署验收版。
