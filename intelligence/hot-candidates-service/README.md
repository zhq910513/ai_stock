<!-- macp-migrated: copy-only 2026-09-02 -->

# MACP 迁入

状态：migrated_copy
来源：ai_stock_source/services/models_services/hot-candidates-service
代码与对照源一致，未改业务逻辑。未切换运行容器到本树。

---

# hot-candidates-service README

本文件是 `hot-candidates-service` 模块根目录唯一当前 MD。全局硬约束以项目根目录 `AGENTS.md` 为准；集合层说明见 `services/models_services/README.md`。

本服务数据资产账本见 `services/models_services/hot-candidates-service/DATA_ASSETS.md`，记录热点模型 source 依赖、目标持久化表和调度频率。

## 定位

热点模型 `hot_candidates` 用 `source.ths_paid_limit_up_probability_v1` 中的同花顺付费次日概率作为教师先验，结合本地行情、竞价、资金、题材、市场环境、可交易性和 source 可见性，判断 T+1/T+5/T+20 短窗口内是否具备可验证的方向兑现价值。

模型只输出研究信号、阶段评分、release gate、评估基准价、观察、outcome、失败归因和 evolution 合同；不提供交易建议，不直接采集 provider，不直接读取 `raw_*`，不反写前端/Jarvis/学习权重。

## 版本

- 兼容评分版本：`hot_candidates_v1`。
- 生产生命周期合同版本：`hot_candidates_v2_lifecycle`。
- 生产 API 版本：`hot_candidates_production_phase7_v1`。

## 代码入口

- FastAPI：`src/hot_candidates_model_service/main.py`
- API：`src/hot_candidates_model_service/api.py`
- 请求/响应 schema：`src/hot_candidates_model_service/schemas.py`
- 兼容评分逻辑：`src/hot_candidates_model_service/logic.py`
- 生命周期研究合同：`src/hot_candidates_model_service/research.py`
- source 可见性、买点、outcome、失败归因：`src/hot_candidates_model_service/pipeline.py`
- 生产分阶段封装：`src/hot_candidates_model_service/production.py`
- 本地 SQLite 验证持久化：`src/hot_candidates_model_service/persistence.py`
- Postgres 写入计划合同：`src/hot_candidates_model_service/postgres_repository.py`

## API

健康：

```text
GET /health
GET /healthz
GET /readyz
```

兼容和研究入口：

```text
POST /score
POST /observe
POST /evolution-sample
POST /distortion-report
POST /pipeline/run
POST /research-pool/classify
POST /teacher-calibration/report
```

生产阶段入口：

```text
POST /production/cases/build
POST /production/features/build
POST /production/scores/compute
POST /production/release-gate/evaluate
POST /production/buy-point/evaluate
POST /production/observations/bulk
POST /production/outcomes/mature
POST /production/evolution/build
POST /production/failure-analysis/build
POST /production/teacher-calibration/version
```

`/pipeline/run` 只用于 side-effect free 集成验证，不是生产 scheduler 主入口。

## 输入数据样式

`/score` 请求：

```json
{
  "row": {},
  "as_of_time_utc": "datetime|null",
  "run_id": "string|null"
}
```

生产阶段请求使用：

```json
{
  "payload": {},
  "as_of_time_utc": "datetime|null",
  "run_id": "string|null"
}
```

核心字段包括：

- 标的和候选：`instrument_id`、`symbol`、`name`、`batch_id`、`candidate_id`、`candidate_source=hot_candidates`。
- 教师先验：`p_limit_up`、`p_limit_up_source=source.ths_paid_limit_up_probability_v1`、`p_limit_up_available_at`、`p_limit_up_model_version`、`p_limit_up_credential_version`。本服务不接收前端手填概率，不读取 Cookie，不直接调用同花顺 provider。
- source 时间线：`candidate_available_at`、`batch_available_at`、`auction_snapshot.available_at`、`stock_rank.available_at`、`market_regime.available_at`、`daily_bars[].available_at`。
- 行情和交易：`daily_bars`、`auction_snapshot`、`minute_bars`、`open_5m_vwap`、`open_5m_available_at`、`reference_entry_price`。
- 上下文：`stock_rank`、`theme_ranks`、`market_regime_context`、`news_events`、`inspection`。`news_events` 当前只能来自经过 source-data-service 构建的 `source.event_news_v1`，Baidu Finance `finance_news_feed` 是 research-only 主源，CNINFO 为备源登记；字段至少保留 `title/published_at/available_at/event_type/url/source_quality_status/lineage_id`，缺失时保留 `source_gap:news_event_context`。

所有进入 official 阶段的数据必须满足 `available_at <= decision_time`。

## 状态流转

```text
candidate row
-> source_visibility_audit
-> hot_cycle_identity / hot_decision_case
-> stage_scores
-> release_gate
-> initial_decision_snapshot
-> hot_signal_fact contract
-> buy_point reference
-> observation snapshots
-> outcome label
-> failure attribution / first-output distortion
-> evolution sample / teacher calibration
```

首次决策快照不可覆盖；第二次及以后 observation append-only；latest state 只能是投影，不是训练真相。

## 分数和阈值

阶段分：

- `pre_auction_score`
- `auction_confirmed_score`
- `open_5m_confirmed_score`
- `official_hot_score`

release gate 阈值：

- `official_hot_score >= 60` 且无 hard block，允许 official。
- `official_hot_score >= 50` 但未达 official，进入 calibration/research。
- `open_5m_confirmed_score` 优先作为 official score；缺失时使用 `auction_confirmed_score`。

硬阻断包括：

- `evidence_available_after_decision_time`
- `missing_available_at_lineage`
- `missing_official_reference_stage_evidence`
- `one_word_limit_no_fill`
- `open_5m_available_after_calc_time`
- `auction_available_after_calc_time`
- `missing_reference_price`

source 缺口和 warning 包括：

- `source_gap:ths_paid_probability_missing`
- `source_gap:ths_paid_probability_cookie_expired`
- `source_gap:ths_paid_probability_batch_abandoned`
- `source_gap:candidate_pool_membership`
- `source_gap:instrument_identity`
- `source_gap:daily_bar_lookback`
- `source_gap:daily_ohlc_invalid`
- `source_gap:stock_moneyflow_rank`
- `source_gap:stock_moneyflow_rank_components`
- `source_gap:auction_confirmation`
- `source_gap:minute_trade_context`
- `source_gap:dynamic_signal_context`
- `source_gap:board_theme_context`
- `source_gap:news_event_context`
- `source_gap:market_regime_context`
- `source_gap:inspection_context`

缺口必须保留，不得补 0 或空字符串。

## 数据产出

响应统一包含：

```json
{
  "model_name": "hot_candidates",
  "model_version": "hot_candidates_v1|hot_candidates_v2_lifecycle",
  "structured_output": {},
  "jarvis_payload": {},
  "contract_gaps": []
}
```

主要 `structured_output`：

- `/score`：`analysis`、`contract`、`research_contract`。
- `/production/cases/build`：`case_build`。
- `/production/scores/compute`：`score_compute`。
- `/production/release-gate/evaluate`：`release_gate_result`。
- `/production/buy-point/evaluate`：`buy_point_result`。
- `/production/observations/bulk`：`observations`、`count`。
- `/production/outcomes/mature`：`outcome_mature_result`。
- `/production/evolution/build`：`evolution_build_result`。
- `/production/failure-analysis/build`：`failure_analysis_result`。

Jarvis payload 只用于只读解释，内含 guardrails：不得修改分数、状态、标签或模型事实。

## 落库表

当前服务本身不直接写生产数据库。持久化由编排/仓储层执行，目标合同表在分阶段 SQL 中定义：

- `infra/sql/0002_source_decision_hot_refactor.sql`
- `infra/sql/bootstrap_schema.sql`
- `packages/db-schema/alembic/versions/0001_current_baseline.py`

目标 `decision_hot.*` 合同包括：

- `decision_hot.hot_cycle_v1`
- `decision_hot.hot_cycle_day_snapshot_v1`
- `decision_hot.hot_decision_case_v1`
- `decision_hot.hot_evidence_snapshot_v1`
- `decision_hot.hot_feature_matrix_v1`
- `decision_hot.hot_score_fact_v1`
- `decision_hot.hot_initial_decision_snapshot_v1`
- `decision_hot.hot_release_gate_audit_v1`
- `decision_hot.hot_signal_fact_v1`
- `decision_hot.hot_buy_point_v1`
- `decision_hot.hot_observation_snapshot_v1`
- `decision_hot.hot_outcome_label_v1`
- `decision_hot.hot_failure_attribution_v1`
- `decision_hot.hot_first_output_distortion_analysis_v1`
- `decision_hot.hot_research_sample_pool_v1`
- `decision_hot.hot_teacher_calibration_v1`
- `decision_hot.hot_teacher_calibration_version_v1`
- `decision_hot.hot_evolution_sample_v1`
- `decision_hot.hot_model_version_evaluation_v1`

若运行库只存在 `decision.*` 兼容事实表，则以当前 `bootstrap_schema.sql` 和运行容器为准，不能由 README 声称已落入不存在的表。

## 调度

scheduler 任务：

- `hot.score.auction_confirmed` -> `POST /production/scores/compute`
- `hot.release_gate.preopen` -> `POST /production/release-gate/evaluate`
- `hot.buy_point.open_5m` -> `POST /production/buy-point/evaluate`
- `hot.observe.intraday` -> `POST /production/observations/bulk`
- `hot.outcome.t5_t20` -> `POST /production/outcomes/mature`
- `hot.evolution.offline` -> `POST /production/evolution/build`

时间：

- 竞价采集：`09:15-09:25`。
- 竞价冻结：`09:25:05,09:25:30`。
- 热点评分：`09:26:00,09:28:00,09:29:30`。
- release gate：`09:25:40,09:28:40,09:29:40`，截止 `09:30:00`。
- open 5m 买点：`09:30-09:36`。
- observation：`09:30-10:00` 每 60 秒；`10:00-14:30` 每 300 秒；尾盘加密。
- outcome：`15:10,15:40` 加 T+5/T+20。
- evolution：`18:30` 后。

## source preflight

official release 前必须通过：

```text
POST /source/release/preflight
```

source preflight 返回 `can_release_official_signal=false` 时，本模型不得发布 official。scheduler owner 2xx 只表示调用成功，不表示 source gate 或 official signal 已通过。

`source.event_news_v1` 的 Baidu Finance 新闻源只用于新闻事件上下文、解释和事后审计，当前不是热点 official release hard gate。若新闻事件进入 official 评分、标签、买点或发布闸门，必须先由 source-data-service 完成真实 probe、raw/source/lineage 写入、coverage/freshness 规则和 README 覆盖；本服务不得直接调用 Baidu、CNINFO、AKShare 或其他 provider。

`source.ths_paid_limit_up_probability_v1` 是热点候选教师先验的唯一 source 表。付费概率抓取、Cookie 留存、Cookie probe、raw/source/lineage 和批次 deadline 均由 source-data-service 负责；本服务只消费已通过 source build 的概率事实。Cookie 缺失、失效、接口不可取数或概率尚未入库时，候选交易日的下一交易日 09:00 Asia/Shanghai 前保持阻断/等待缺口；超过该时间仍未补齐且 source-data-service 批次状态为 `abandoned_no_probability_before_deadline` 时，该批候选进入放弃态，不得用 0、手填、随机、旧 payload 或 GPT 推断补教师先验。

## 下游消费

- scheduler：触发 owner endpoint，不改模型事实。
- source-data-service：提供 source row、lineage、quality、preflight。
- research-service 或后续编排层：组装真实输入、处理行级异常、持久化模型事实。
- research-data-mart / data-inspector / execution-timing / gateway / frontend / Jarvis：只读消费或巡检。

## 异常兜底

owner API 内部无法评分时返回 422。批处理编排层必须把单条异常转为行级研究事实：

- warning：`hot_candidates:row_failed:{symbol}:{stage}:{error_code}`。
- 状态：`state=blocked`、`hot_score=null`。
- 缺口：`source_gap:model_service_scoring_failed`、`source_gap:model_service_exception:{error_code}`。
- payload：保留 `stage`、`run_id`、`symbol`、`instrument_id`、`error_code`、`error_message`、输入引用。

单条失败不得拖垮整批。

## 验收

定向测试：

```bash
python -m pytest -q services/models_services/hot-candidates-service/tests
```

跨服务验收：

```bash
python scripts/core_services_acceptance.py --require-postgres
python scripts/core_services_acceptance.py --require-postgres --source-quality-matrix
```

真实 provider probe 由 source-data-service 和验收脚本执行，本服务不得绕开 source orchestration 直接探 provider。

## 当前闭环结论

热点 owner service 的 API、阶段合同、source visibility hard block、release gate、买点评估、outcome、失败归因和 evolution 合同已在当前代码中实现。2026-06-14 本地 Docker 闭环中，`scripts/core_services_acceptance.py --require-postgres --real-provider-probe --source-quality-matrix` 返回 0，`hot.release_gate.preopen` 经 scheduler live dispatch 到本服务返回 200，source release preflight 为 `can_release_official_signal=true`、`coverage_status=passed`、`freshness_status=passed`、`blocking_reasons=[]`。Baidu `source.event_news_v1` 已通过 source-data-service 真实 raw/source/lineage 写入验证，但在本模型中仍只作为 `news_events` research-only 证据上下文，不参与 official hard gate。当前最小闭环依赖 source-data-service、scheduler-service 和后续持久化编排；未阻断优化项见根目录 `需优化点.MD`。

## 拍板冻结记录

### hot-candidates-service -> owner contract/frontend-readonly chain -> model1 closure evidence

- 冻结时间：2026-06-21。
- 拍板人 / 确认来源：用户在模型一只读闭环审查任务书后回复“批准”。
- 锁定范围：热点候选 owner service API、阶段合同、source visibility hard block、官方 release gate 必须经 `/source/release/preflight`、同花顺付费概率只消费 `source.ths_paid_limit_up_probability_v1`、Cookie/付费概率抓取/批次 deadline 均归属 source-data-service、scheduler 热点计划和 `#/model-hot` 只读展示链路的当前合同证据。
- 当前运行事实：`hot-candidates-service /readyz` 为 ready；scheduler `validate/hot-candidates`、`validate/hot-workflow`、`validate/source-schedule` 均 valid；前端 `#/model-hot` 可读取 `source.limit_event_v1` 并展示 105 条真实只读记录；模型一单测和前端合同测试通过。当前同花顺付费概率 Cookie 运行状态为 `configured=false/status=missing`，`2026-06-18` 候选批次为 `pending_cookie`，87 只候选尚未抓取概率，deadline 为 `2026-06-22 09:00 Asia/Shanghai`；该状态是付费 Cookie 缺失导致的源数据阻断，不得写成概率数据已产出。
- 允许的只读验收：读取 `/readyz`、`/healthz`、scheduler 热点校验接口、source 付费概率 cookie/status 与 batch-status、source 队列摘要、`#/model-hot` 截图/可见文本检查、运行 `services/models_services/hot-candidates-service/tests` 和 `services/shence-frontend-service/tests`。
- 禁止修改项：未经解锁不得修改本服务评分、release gate、买点、观察、outcome、失败归因、evolution 合同、source preflight 口径、同花顺付费概率消费边界、Cookie 归属边界、scheduler 热点计划、模型一 README/DATA_ASSETS 冻结事实；不得让本服务读取 Cookie、调用同花顺 provider、读取 `raw_*`、用 0/手填/随机/旧 payload/GPT 推断补教师先验或越过 source preflight 发布 official signal。
- 解锁条件：用户明确批准 `hot-candidates-service -> owner contract/frontend-readonly chain -> model1 closure evidence` 解锁，并说明目标、影响范围、拟修改文件、回滚方式和验证清单；若需要改变 Cookie/API/provider/source 表或 scheduler 频率，必须另行解锁 source-data-service 或 scheduler-service 对应对象。
- 回滚方式：回退本冻结对象相关 README/DATA_ASSETS 记录或后续被批准的合同改动，恢复当前 owner 只读消费 source 标准层、source preflight hard block 和前端只读展示口径；回滚后必须重新验证 owner ready、scheduler 热点校验、source 付费概率状态和模型一/前端测试。
- 验证清单：`python -m pytest -q -p no:cacheprovider services/models_services/hot-candidates-service/tests`；`python -m pytest -q services/shence-frontend-service/tests/test_frontend_contract.py`；`GET /readyz`；`GET /scheduler/validate/hot-candidates`；`GET /scheduler/validate/hot-workflow`；`GET /scheduler/validate/source-schedule`；`GET /source/ths/paid-probability/cookie/status`；`GET /source/ths/paid-probability/batch-status?trade_date=2026-06-18`；`#/model-hot` 页面可见文本不出现 `source_gap:*`、接口路径、raw/provider 程序细节，缺失事实显示中文空态。

### hot-candidates-service -> model1 reset -> 2026-07-08 zero state

- 记录时间：2026-07-08 Asia/Shanghai。
- 确认来源：用户批准“按此范围清理模型一数据，无需备份历史数据”，随后用户回复“你来决定”，由 Codex 判定本轮清理事实可拍板记录。
- 清理范围：清空 `decision_hot.*` 全部模型一事实表；删除 `governance.research_model_execution_audit_v1` 中 `model_code='hot_candidates'`、`owner_service='hot-candidates-service'` 或 `task_code LIKE 'hot.%'` 的执行审计行。
- 明确未清范围：未清理 `source.*`、`raw_ths.*`、`governance.source_lineage_v1`、`governance.ths_paid_probability_batch_status_v1`、`governance.ths_paid_probability_cookie_v1`、scheduler task store、source fetch queue、provider probe evidence、Docker 镜像或代码。
- 当前运行事实：清理后 `decision_hot_total=0`，模型一 execution audit 剩余 `0`；`/research/model-list/hot?limit=20` 返回 `item_count=0`；source 概率 `279` 行、raw 概率 `309` 行、付费概率批次状态 `17` 行、Cookie `3` 行仍在；source、scheduler、data-inspector 均 ready，source queue `queued=0/leased=0/dead_letter=0`。
- 当前等待条件：`2026-07-08` 付费概率批次为 `no_candidates`，候选数 `0`；THS 付费概率 Cookie 状态为 `expired`，最近成功时间 `2026-06-29T12:30:18.780506Z`，最近失败原因 `ths paid probability status=403 msg=denied`。后续模型一重新产出必须等待真实收盘候选和有效 Cookie；缺候选或 Cookie 失效时必须保留真实阻断，不得用 0、手填、旧 payload、mock 或 GPT 推断补概率。
- 只读验收：`GET /research/model-list/hot?limit=20`、`GET /source/ths/paid-probability/cookie/status`、`GET /source/ths/paid-probability/batch-status?trade_date=2026-07-08`、source queue summary、scheduler `/readyz`、数据库只读计数。
- 禁止事项：不得把当前空列表解释为模型一已恢复产出；不得绕过 source-data-service 抓取链路；不得让 hot-candidates-service 读取 Cookie、调用 THS provider、读取 raw、补写概率或跳过 `/source/release/preflight` 发布 official signal。
- 回滚方式：本轮按用户要求未备份历史模型一事实，无法用备份恢复已删除的 `decision_hot.*` 和模型一 execution audit；只能在后续真实 source 数据成熟后通过正式 scheduler/research/model 链路重新生成新事实。
