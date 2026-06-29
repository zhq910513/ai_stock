# candidate-memory-service README

本文件是 `candidate-memory-service` 模块根目录唯一当前 MD。全局硬约束以项目根目录 `AGENTS.md` 为准；集合层说明见 `services/models_services/README.md`。

本服务数据资产账本见 `services/models_services/candidate-memory-service/DATA_ASSETS.md`，记录候选记忆 source 依赖、目标持久化表和调度频率。

## 定位

候选记忆模型 `candidate_memory` 研究曾经进入热点候选链路的股票，在离开短窗口后是否出现延迟兑现、二波、慢趋势或失效风险。它不复用热点模型 signal，不把 `memory_entity` 当推荐信号；每次正式二次激活必须生成新的 `memory_signal_id`。

模型只输出 seed、entity、前置信号、激活、release gate、买点、outcome、上涨原因、失败归因、TTL/阈值校准、matched-control uplift、shadow evaluation 等合同；不直接采集 provider，不直接读取 `raw_*`，不反写前端/Jarvis/学习权重。

## 版本

- 模型版本：`candidate_memory_v1`。
- Phase 5 闭环 schema：`candidate_memory_phase5_v1`。

## 代码入口

- FastAPI：`src/candidate_memory_model_service/main.py`
- API：`src/candidate_memory_model_service/api.py`
- 请求/响应 schema：`src/candidate_memory_model_service/schemas.py`
- 兼容评分逻辑：`src/candidate_memory_model_service/logic.py`
- 生产阶段研究合同：`src/candidate_memory_model_service/research_v1.py`
- 批量 observation、事件标准化、TTL/uplift：`src/candidate_memory_model_service/phase2.py`
- readiness、due plan、schedule contract：`src/candidate_memory_model_service/phase3.py`
- source feature、persistence plan、replay、阈值校准：`src/candidate_memory_model_service/phase4.py`
- closure、失败归因、shadow evaluation、最终验收：`src/candidate_memory_model_service/phase5.py`
- 本地 SQLite 验证持久化：`src/candidate_memory_model_service/persistence.py`
- Postgres repository 合同：`src/candidate_memory_model_service/postgres_repository.py`

## API

健康：

```text
GET /health
GET /healthz
GET /readyz
```

兼容入口：

```text
POST /score
```

生产阶段入口：

```text
POST /production/seed/build
POST /production/entity/build
POST /production/source/features/build
POST /production/features/readiness
POST /production/pre-signal/window
POST /production/pre-signal/detect
POST /production/activation/evaluate
POST /production/release-gate/evaluate
POST /production/buy-point/evaluate
POST /production/outcomes/mature
POST /production/up-reason/build
POST /production/evolution/build
POST /production/events/standardize
POST /production/registry/upsert
POST /production/observations/bulk
POST /production/observations/due-plan
POST /production/matched-control/uplift
POST /production/ttl-calibration/build
POST /production/pre-limitup/analyze
POST /production/schedule/contract
POST /production/persistence/plan
POST /production/pre-signal/threshold-calibration
POST /production/replay/multi-day
POST /production/phase4/acceptance
POST /production/closure/run
POST /production/failure-attribution/build
POST /production/model-version/shadow-evaluate
POST /production/phase5/final-acceptance
```

`/score` 是旧评分合同兼容入口；正式链路以 `/production/*` 分阶段入口为准。`/production/closure/run` 是 side-effect free 闭环验证，不替代生产分阶段调度。

## 输入数据样式

统一请求：

```json
{
  "row": {},
  "as_of_time_utc": "datetime|null",
  "run_id": "string|null"
}
```

核心字段包括：

- 记忆身份：`memory_id`、`memory_entity_id`、`memory_seed_id`、`appearance_id`、`appearance_count`。
- 热点来源：`first_source_model`、`source_model`、`hot_signal_id`、`first_source_signal_id`、`first_outcome_label`。
- 候选审计：`ingest_mode=external_ths_model`、`contract_audit_status=passed`、`batch_id/latest_batch_id`、`candidate_id/latest_candidate_id`。
- 标的：`instrument_id`、`symbol`、`name`。
- 教师先验：`p_limit_up`、`max_p_limit_up`、`p_limit_up_source`。
- 行情和特征：`daily_bars`、`price_path`、`stock_rank`、`moneyflow_context`、`sector_theme_context`、`tradability_context`。
- 年龄和 TTL：`memory_age_days`、`candidate_memory_age_days`、`days_since_last_candidate`、`ttl_days`、`ttl_remaining_days`、`ttl_health_score`。
- 事件：`events[]`，每条必须有 `available_at`、`published_at` 或 `captured_at` 才能作为 ex-ante 证据。当前事件源只能来自 source-data-service 的 `source.event_news_v1` 或后续编排层等价 source 输出；Baidu Finance `finance_news_feed` 是 research-only 主源，CNINFO 为备源登记，输入需保留 `title/published_at/available_at/event_type/url/source_quality_status/lineage_id`。

缺交易日历年龄时必须保留 `memory_age_days=null`，状态落为 `blocked_data_gap`，缺口码保留 `source_gap:missing_trading_calendar_memory_age`。

## 状态流转

```text
hot mature sample / source signal
-> memory_seed
-> memory_entity
-> source_feature_snapshot
-> feature_readiness_audit
-> pre_signal_feature_window
-> pre_signal_case
-> activation_case
-> release_gate
-> memory_signal_fact contract
-> buy_point
-> observation / latest_state projection
-> mature outcome
-> up_reason_attribution
-> failure_attribution
-> evolution sample
-> TTL / threshold calibration
-> model version shadow evaluation
```

重要状态：

- `blocked_data_gap`
- `memory_watch`
- `memory_active`
- `memory_reactivated`
- `memory_invalidated`
- `memory_decayed`
- `pre_signal_detected`
- `activation_watch`
- `activation_blocked`
- `official_signal_passed`
- `research_only_blocked`
- `buy_point_confirmed`
- `buy_point_blocked`
- `closed_ready_for_shadow_evaluation`

`latest_state` 只作为投影，不是训练真相。pending outcome、post-hoc-only 样本、`new_independent_cycle` 不得进入正式 evolution 成功样本。

## 分数和阈值

兼容评分公式：

```text
memory_hit_8pct_score =
0.20*historical
+0.25*trend
+0.20*accumulation
+0.20*second_wave
+0.15*upside
-0.30*breakdown
```

旧评分状态规则：

- 有硬阻断：`blocked_data_gap`。
- 缺评分分量：`memory_watch`。
- `breakdown_failure_risk >= 70`：`memory_invalidated`。
- `second_wave_setup_score >= 70`、`breakdown < 45`、`memory_age_days` 在 5-20、结构证据数至少 2：`memory_reactivated`。
- `trend >= 60` 且 `breakdown < 50`：`memory_active`。
- `memory_age_days > 30`：`memory_decayed`。

生产 release gate：

- `activation_quality_score >= 70` 才可进入 official gate。
- `ttl_health_score >= 25`。
- `data_time_contract_failed` 阻断 official。
- 需要新 `memory_signal_id`，不得复用 `memory_entity_id` 或热点 signal。

校准阈值：

- matched control 最少样本：`10`。
- TTL calibration 最少成熟样本：`20`。
- pre-signal threshold calibration 默认 `62`，activation 默认 `68`，每桶最少样本 `5`。
- final acceptance 最少样本：`8`。

## 缺口码和阻断

兼容评分硬阻断：

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

生产缺口和阻断包括：

- `source_gap:daily_bar_20d`
- `source_gap:daily_ohlc_invalid`
- `source_gap:moneyflow_stock_rank`
- `source_gap:event_missing_available_at`
- `source_gap:event_future_available_at`
- `future_feature_watermark:{feature}`
- `required_feature_not_fresh:{feature}`
- `activation_requires_fresh_moneyflow_or_sector_theme`
- `ttl_not_healthy_for_official_signal`
- `activation_quality_below_official_gate`
- `data_time_contract_failed`
- `release_gate_not_passed`
- `unsupported_memory_buy_point_stage`
- `outcome_not_mature`
- `new_independent_cycle_excluded`

缺口必须保留，不得补 0 或空字符串。

## 数据产出

统一响应：

```json
{
  "model_name": "candidate_memory",
  "model_version": "candidate_memory_v1",
  "structured_output": {},
  "jarvis_payload": {},
  "contract_gaps": []
}
```

主要 `structured_output`：

- `contract`
- `memory_seed`
- `memory_entity`
- `source_feature_snapshot`
- `feature_readiness_audit`
- `pre_signal_feature_window`
- `pre_signal_case`
- `activation_case`
- `release_gate`
- `buy_point`
- `outcome_label`
- `up_reason_attribution`
- `failure_attribution`
- `evolution_sample`
- `active_case_registry`
- `bulk_observation_result`
- `due_observation_plan`
- `ttl_calibration_report`
- `matched_control_uplift`
- `model_schedule_contract`
- `stage_persistence_plan`
- `closure_pipeline`
- `model_version_shadow_evaluation`
- `phase5_final_acceptance`

Jarvis payload 只读，不得修改状态、分数、标签或模型事实。

## 落库表

当前服务本身不直接写生产数据库。持久化由编排/仓储层执行，目标合同表在分阶段 SQL 中定义：

- `infra/sql/0003_decision_memory_model_v1.sql`
- `infra/sql/0004_decision_memory_phase2_research_calibration.sql`
- `infra/sql/0005_decision_memory_phase3_production_repository_and_schedule.sql`
- `infra/sql/0006_decision_memory_phase4_production_chain_acceptance.sql`
- `infra/sql/0007_decision_memory_phase5_closed_loop_finalization.sql`
- `infra/sql/bootstrap_schema.sql`
- `packages/db-schema/alembic/versions/0001_current_baseline.py`

目标 `decision_memory.*` 合同包括：

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
- `decision_memory.memory_score_fact_v1`
- `decision_memory.memory_release_gate_audit_v1`
- `decision_memory.memory_signal_fact_v1`
- `decision_memory.memory_buy_point_v1`
- `decision_memory.memory_monitoring_snapshot_v1`
- `decision_memory.memory_outcome_label_v1`
- `decision_memory.memory_up_reason_attribution_v1`
- `decision_memory.memory_pre_limitup_signal_analysis_v1`
- `decision_memory.memory_failure_attribution_v1`
- `decision_memory.memory_evolution_sample_v1`
- `decision_memory.memory_ttl_calibration_v1`
- `decision_memory.memory_model_version_evaluation_v1`
- `decision_memory.memory_active_case_registry_v1`
- `decision_memory.memory_latest_state_v1`
- `decision_memory.memory_model_version_shadow_evaluation_v1`

当前 `bootstrap_schema.sql` 也包含 `decision.candidate_memory_*` 兼容事实表；运行事实以当前容器和 `bootstrap_schema.sql` 为准。若 `decision_memory.*` 合同表未在运行库出现，不能由 README 声称已经持久化。

## 调度

scheduler 任务：

- `memory.seed.from_hot_signals` -> `POST /production/seed/build`
- `memory.pre_signal.scan` -> `POST /production/pre-signal/detect`
- `memory.release_gate.close` -> `POST /production/release-gate/evaluate`
- `memory.buy_point.next_session_reference` -> `POST /production/buy-point/evaluate`
- `memory.observe.outcome.evolution` -> `POST /production/outcomes/mature`

时间：

- seed/entity：热点 official signal 和 observation 成熟后。
- pre-signal：`15:55` 收盘确认，可选 `10:30` 研究扫描。
- release gate：`16:05`。
- buy point：下一交易日 `09:30-10:00` 评估窗口。
- observation/outcome/evolution：每日 `15:50` 加 T+5/T+20/T+40 成熟检查。

## source preflight

official release 前必须通过：

```text
POST /source/release/preflight
```

preflight 返回 `can_release_official_signal=false` 时，本模型不得发布 official。事件、行情、资金、板块、交易状态等证据必须来自经过 source build、quality_status、lineage 和 `available_at` 校验的 `source.*`。

`source.event_news_v1` 的 Baidu Finance 新闻只作为候选记忆事件上下文和 ex-ante 审计证据，不是当前 official release hard gate。缺 `available_at` 或未来 `available_at` 时必须保留 `source_gap:event_missing_available_at` / `source_gap:event_future_available_at`，不得用 provider 原始 feed、GPT 推断、0、空字符串或 sample payload 补齐；本服务不得直接调用 Baidu、CNINFO、AKShare 或其他 provider。

## 下游消费

- scheduler：触发 owner endpoint，不改模型事实。
- source-data-service：提供 source row、lineage、quality、preflight。
- research-service 或后续编排层：组装真实输入、处理行级异常、持久化模型事实。
- research-data-mart / data-inspector / execution-timing / gateway / frontend / Jarvis：只读消费或巡检。

## 异常兜底

owner API 内部无法评分时返回 422。批处理编排层必须把单条异常转为行级研究事实：

- warning：`candidate_memory:row_failed:{symbol}:score:{error_code}`。
- 状态：`memory_state=blocked_data_gap`、`publication_state=blocked`、`memory_hit_8pct_score=null`。
- 缺口：`source_gap:model_service_scoring_failed`、`source_gap:model_service_exception:{error_code}`。
- payload：保留 `stage`、`run_id`、`symbol`、`instrument_id`、`error_code`、`error_message`、输入引用。
- 状态变化必须写 `candidate_memory_state_history` 和 transition audit；`ad_hoc:*` 触发也不能丢状态。

单条失败不得拖垮整批。

## 验收

定向测试：

```bash
python -m pytest -q services/models_services/candidate-memory-service/tests
python -m pytest -q tests/test_candidate_memory_sql_contract.py tests/test_candidate_memory_phase3_sql_contract.py tests/test_candidate_memory_phase4_sql_contract.py tests/test_candidate_memory_phase5_sql_contract.py
```

跨服务验收：

```bash
python scripts/core_services_acceptance.py --require-postgres
python scripts/core_services_acceptance.py --require-postgres --source-quality-matrix
```

真实 provider probe 由 source-data-service 和验收脚本执行，本服务不得绕开 source orchestration 直接探 provider。

## 当前闭环结论

候选记忆 owner service 的 API、兼容评分、生产分阶段合同、事件 ex-ante 防后视镜、release gate、买点、mature outcome、failure attribution、TTL/阈值校准、matched control 和 shadow evaluation 已在当前代码中实现。2026-06-14 本地 Docker 闭环中，`scripts/core_services_acceptance.py --require-postgres --real-provider-probe --source-quality-matrix` 返回 0，`memory.release_gate.close` 经 scheduler live dispatch 到本服务返回 200，source release preflight 为 `can_release_official_signal=true`、`coverage_status=passed`、`freshness_status=passed`、`blocking_reasons=[]`。验收样例中出现的 `source_gap:*` 属候选记忆行级审计语义，脚本 required checks 仍全部通过，不能被 scheduler 或本服务改写为事实。Baidu `source.event_news_v1` 已通过 source-data-service 真实 raw/source/lineage 写入验证，但在本模型中仍只作为 `events[]` research-only ex-ante 证据上下文，不参与 official hard gate。当前最小闭环依赖 source-data-service、scheduler-service 和后续持久化编排；未阻断优化项见根目录 `需优化点.MD`。
