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

# 神策中心研究中心 V2：research_dynamic 共享研究域设计

## 1. 为什么需要 research_dynamic

引入 `dynamic-feature-service` 后，三大模型研究中心都会读取盘中动态特征，但动态特征的有效性不能由单个模型私下判断。否则会出现：

```text
热点模型认为 gap_acceptance_score 有效；
模型三认为 support_retest_quality_score 有效；
买点服务又使用另一个口径；
研究中心无法统一验证动态特征是否真正有增量价值。
```

因此需要一个独立共享域：

```text
research_dynamic
```

它不替代 `research_hot`、`research_memory`、`research_ambush`，而是补充一层“动态特征有效性研究”。它负责回答：

```text
1. 某个动态特征是否真的提升模型表现？
2. 这个提升是否在静态模型基础上仍然存在？
3. 这个特征是否有分桶单调性？
4. 这个特征能否解释排名后悔？
5. 这个特征是否只是事后结果描述，而不是 as_of 可用证据？
6. production snapshot 与 research replay 是否一致？
7. 分钟线、竞价、盘中板块等缺口是否显著影响研究结论？
```

---

## 2. 数据链路

```text
source.minute_bar_v1
source.auction_snapshot_v1
source.realtime_quote_snapshot_v1
source.intraday_moneyflow_snapshot_v1
source.board_intraday_snapshot_v1
source.limit_event_v1
source.daily_bar_v1
        ↓
dynamic_feature.dynamic_feature_run_v1
dynamic_feature.dynamic_feature_subject_v1
dynamic_feature.dynamic_feature_snapshot_v1
dynamic_feature.dynamic_feature_gap_v1
dynamic_feature.dynamic_feature_contract_v1
        ↓
research_dynamic.dynamic_feature_research_run_v1
research_dynamic.dynamic_feature_lift_analysis_v1
research_dynamic.dynamic_feature_bucket_effectiveness_v1
research_dynamic.dynamic_rerank_regret_v1
research_dynamic.dynamic_feature_replay_consistency_v1
research_dynamic.dynamic_feature_gap_impact_v1
        ↓
research_hot / research_memory / research_ambush
```

硬规则：

```text
research_dynamic 不直接读取 raw provider 表；
research_dynamic 不调用外部行情 API；
research_dynamic 不重算未落库事实；
research_dynamic 可以触发 research_replay，但 replay 只能使用当时已可见的 source 数据。
```

---

## 3. 动态研究任务表

```sql
CREATE TABLE IF NOT EXISTS research_dynamic.dynamic_feature_research_run_v1 (
    research_run_id              VARCHAR(64) PRIMARY KEY,
    research_type                VARCHAR(64) NOT NULL,  -- lift_analysis / bucket_effectiveness / dynamic_rerank / replay_consistency / gap_impact / model_specific
    research_name                TEXT,

    model_code                   VARCHAR(64) NOT NULL,  -- hot_candidates / candidate_memory / ambush_watchlist / buy_point / cross_model
    feature_bundle_code          VARCHAR(128) NOT NULL, -- hot_intraday_confirmation_bundle_v1 / ambush_micro_turn_bundle_v1 等
    feature_set_version          VARCHAR(64) NOT NULL,
    formula_version              VARCHAR(64) NOT NULL,

    sample_start_date            DATE NOT NULL,
    sample_end_date              DATE NOT NULL,
    evaluation_window            VARCHAR(32),           -- T1/T3/T5/T10/T15/T20/T40/T60 等
    as_of_time_policy            VARCHAR(64) NOT NULL,  -- production_snapshot / research_replay / mixed

    min_sample_count             INT DEFAULT 30,
    confidence_level             VARCHAR(32),           -- low/medium/high
    status                       VARCHAR(32) NOT NULL,  -- created/running/succeeded/failed/data_blocked
    data_quality_status          VARCHAR(32),           -- passed/degraded/blocked

    created_by                   VARCHAR(64),
    created_at                   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at                   TIMESTAMP,
    finished_at                  TIMESTAMP,
    comment                      TEXT
);
```

### 字段解释

`as_of_time_policy` 是动态研究的可信度核心：

```text
production_snapshot：只使用模型生产当时已经生成的 dynamic_feature_snapshot，可信度最高。
research_replay：使用当时可见 source 数据重放计算，用于补研究，但不能等同于生产当时可用。
mixed：混合使用，必须在研究结论中降级或标记。
```

---

## 4. 动态特征增益研究表

```sql
CREATE TABLE IF NOT EXISTS research_dynamic.dynamic_feature_lift_analysis_v1 (
    lift_analysis_id             VARCHAR(64) PRIMARY KEY,
    research_run_id              VARCHAR(64) NOT NULL,
    model_code                   VARCHAR(64) NOT NULL,
    feature_bundle_code          VARCHAR(128) NOT NULL,
    feature_name                 VARCHAR(128) NOT NULL,
    analysis_window              VARCHAR(32),

    sample_count                 INT NOT NULL,
    valid_sample_count           INT NOT NULL,
    excluded_sample_count        INT DEFAULT 0,
    excluded_reason_json         JSONB,

    static_only_hit_rate          NUMERIC(12,6),
    static_plus_dynamic_hit_rate  NUMERIC(12,6),
    incremental_lift             NUMERIC(12,6),

    static_only_rank_regret_rate         NUMERIC(12,6),
    static_plus_dynamic_rank_regret_rate NUMERIC(12,6),
    rank_regret_lift                     NUMERIC(12,6),

    avg_max_return_before        NUMERIC(12,6),
    avg_max_return_after         NUMERIC(12,6),
    avg_max_drawdown_before      NUMERIC(12,6),
    avg_max_drawdown_after       NUMERIC(12,6),

    data_quality_status          VARCHAR(32),
    confidence_level             VARCHAR(32),
    created_at                   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

### 研究口径

```text
static_only = 原模型静态日级/结构/teacher prior 结果；
static_plus_dynamic = 在同一批次、同一 as_of_time、同一观察窗口下加入动态特征后的重排/过滤/确认结果；
incremental_lift = static_plus_dynamic_hit_rate - static_only_hit_rate。
```

注意：

```text
不允许跨日期比较；
不允许把 research_replay 特征当作 production_snapshot 直接证明生产提升；
不允许样本量不足时输出 strong 结论。
```

---

## 5. 动态特征分桶有效性表

```sql
CREATE TABLE IF NOT EXISTS research_dynamic.dynamic_feature_bucket_effectiveness_v1 (
    bucket_effectiveness_id      VARCHAR(64) PRIMARY KEY,
    research_run_id              VARCHAR(64) NOT NULL,
    model_code                   VARCHAR(64) NOT NULL,
    feature_bundle_code          VARCHAR(128) NOT NULL,
    feature_name                 VARCHAR(128) NOT NULL,

    bucket_name                  VARCHAR(64) NOT NULL,
    bucket_min_value             NUMERIC(18,6),
    bucket_max_value             NUMERIC(18,6),

    sample_count                 INT NOT NULL,
    hit_rate                     NUMERIC(12,6),
    avg_max_return               NUMERIC(12,6),
    avg_max_drawdown             NUMERIC(12,6),
    false_positive_rate          NUMERIC(12,6),
    false_negative_rate          NUMERIC(12,6),
    rank_regret_rate             NUMERIC(12,6),

    monotonicity_group_id        VARCHAR(64),
    monotonicity_score           NUMERIC(12,6),
    confidence_level             VARCHAR(32),
    created_at                   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

### 示例

`support_retest_quality_score` 分桶：

```text
0-20   支撑回踩质量差
20-40  偏弱
40-60  中性
60-80  良好
80-100 强支撑确认
```

若分数越高，成功率、结构延续率并不提升，则该特征不能进入正式评分，只能保留研究用途。

---

## 6. 动态重排后悔分析表

```sql
CREATE TABLE IF NOT EXISTS research_dynamic.dynamic_rerank_regret_v1 (
    dynamic_regret_id            VARCHAR(64) PRIMARY KEY,
    research_run_id              VARCHAR(64) NOT NULL,
    model_code                   VARCHAR(64) NOT NULL,
    batch_date                   DATE NOT NULL,

    original_top_signal_id       VARCHAR(64),
    dynamic_top_signal_id        VARCHAR(64),
    original_top_symbol          VARCHAR(32),
    dynamic_top_symbol           VARCHAR(32),

    original_top_return          NUMERIC(12,6),
    dynamic_top_return           NUMERIC(12,6),
    rerank_return_gap            NUMERIC(12,6),

    original_rank_json           JSONB,
    dynamic_rank_json            JSONB,
    dynamic_feature_diff_json    JSONB,

    primary_dynamic_reason       VARCHAR(128), -- weak_acceptance / support_retest_pass / breakout_quality / false_rebound_warning / high_open_low_walk
    confidence_level             VARCHAR(32),
    created_at                   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

用途：

```text
解释 Top1 输给 Top2 是否可以由动态特征解释；
验证动态特征能否改善同批次排序；
把动态排序错误沉淀到模型研究中心，而不是靠人工记忆。
```

---

## 7. 动态特征回放一致性表

```sql
CREATE TABLE IF NOT EXISTS research_dynamic.dynamic_feature_replay_consistency_v1 (
    consistency_id               VARCHAR(64) PRIMARY KEY,
    production_run_id            VARCHAR(64),
    replay_run_id                VARCHAR(64) NOT NULL,
    model_code                   VARCHAR(64) NOT NULL,
    canonical_symbol             VARCHAR(32) NOT NULL,
    trade_date                   DATE NOT NULL,
    as_of_time                   TIMESTAMP NOT NULL,

    feature_bundle_code          VARCHAR(128) NOT NULL,
    feature_name                 VARCHAR(128) NOT NULL,
    production_value             TEXT,
    replay_value                 TEXT,
    value_diff                   NUMERIC(18,6),
    is_consistent                BOOLEAN NOT NULL,
    inconsistency_reason         TEXT,

    created_at                   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

硬规则：

```text
production_vs_replay_feature_diff_rate 高时，该研究结论必须降级；
replay 结果不一致不能用于支持 production_candidate；
缺 production snapshot 的历史样本可以 replay，但结论必须标记 replay_only。
```

---

## 8. 动态特征缺口影响表

```sql
CREATE TABLE IF NOT EXISTS research_dynamic.dynamic_feature_gap_impact_v1 (
    gap_impact_id                VARCHAR(64) PRIMARY KEY,
    research_run_id              VARCHAR(64) NOT NULL,
    model_code                   VARCHAR(64) NOT NULL,
    feature_bundle_code          VARCHAR(128) NOT NULL,

    gap_source                   VARCHAR(64) NOT NULL, -- minute_bar / auction / realtime_quote / board_intraday / intraday_moneyflow
    gap_level                    VARCHAR(16) NOT NULL, -- P0/P1/P2

    sample_count_with_gap        INT NOT NULL,
    sample_count_without_gap     INT NOT NULL,

    hit_rate_with_gap            NUMERIC(12,6),
    hit_rate_without_gap         NUMERIC(12,6),
    rank_regret_rate_with_gap    NUMERIC(12,6),
    rank_regret_rate_without_gap NUMERIC(12,6),
    false_turn_rate_with_gap     NUMERIC(12,6),
    false_turn_rate_without_gap  NUMERIC(12,6),

    impact_score                 NUMERIC(12,6),
    recommended_requirement_change VARCHAR(64), -- keep_p1 / upgrade_to_p0 / downgrade / research_only
    created_at                   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

---

## 9. finding 类型扩展

三大模型研究结论表都需要新增动态类 finding：

```text
dynamic_feature_positive_lift
dynamic_feature_no_lift
dynamic_feature_unstable
dynamic_rerank_effective
dynamic_rerank_failed
intraday_confirmation_required
intraday_false_signal_warning
intraday_gap_material_impact
replay_inconsistency_detected
```

每条 finding 必须附带：

```sql
feature_bundle_code
feature_name
as_of_time_policy
sample_count
incremental_lift
monotonicity_score
confidence_level
production_change_allowed
manual_review_required
```

---

## 10. 验收标准

`research_dynamic` 第一阶段完成后，必须能回答：

```text
1. 某个动态特征是否在静态模型基础上有增量 lift？
2. 某个动态特征是否分桶单调？
3. 动态特征能否解释热点模型 Top1 输给 Top2？
4. 动态特征能否提前识别候选记忆二波启动？
5. 动态特征能否区分模型三真抬头和 hard negative？
6. production snapshot 和 research replay 是否一致？
7. 分钟线/竞价/盘中板块缺口是否影响研究结论？
8. 哪些动态特征只能研究，哪些可以进入 production_candidate？
```
