# ambush-watchlist-service README

本文件是 `ambush-watchlist-service` 模块根目录唯一当前 MD。全局硬约束以项目根目录 `AGENTS.md` 为准；集合层说明见 `services/models_services/README.md`。

本服务数据资产账本见 `services/models_services/ambush-watchlist-service/DATA_ASSETS.md`，记录潜伏抬头 source 依赖、目标持久化表和调度频率。

## 定位

潜伏抬头模型 `ambush_watchlist` 是深圳 A 股低位弱转强结构扫描模型。它以低谷图库、多通道 OHLCV 数值序列、hard negative、低谷成熟度、有效抬头新鲜度、资金/板块/市场确认和可交易性为依据，识别尚未明显走热但已经从成熟低谷中抬头的标的。

模型不依赖热点模型历史，不使用同花顺教师概率作为核心先验；不直接采集 provider，不直接读取 `raw_*`，不反写前端/Jarvis/学习权重。

## 版本

- 兼容/基础模型版本：`ambush_watchlist_effective_turn_v1_1`。
- 图库版本：`ambush_valley_pattern_library_v1_0`。
- 公式治理版本：`ambush_formula_governance_v1_0`。
- Phase2：`ambush_watchlist_phase2_valley_turn_v1_0_rc`。
- Phase3：`ambush_watchlist_phase3_release_signal_v1_0_rc`。
- Phase4：`ambush_watchlist_phase4_closed_loop_v1_0_rc`。
- 锁定候选：`ambush_watchlist_service_v1.0_rc_backend_closure_candidate`。

## 代码入口

- FastAPI：`src/ambush_watchlist_model_service/main.py`
- API：`src/ambush_watchlist_model_service/api.py`
- 请求/响应 schema：`src/ambush_watchlist_model_service/schemas.py`
- 兼容 dragon 逻辑：`src/ambush_watchlist_model_service/logic.py`
- 图库和三路召回：`src/ambush_watchlist_model_service/pattern_library.py`
- Phase2 谷底观察和有效抬头：`src/ambush_watchlist_model_service/phase2.py`
- Phase3/4 release、买点、outcome、失败归因：`src/ambush_watchlist_model_service/phase3.py`

## API

健康：

```text
GET /health
GET /healthz
GET /readyz
```

source capability 和图库：

```text
POST /ambush/source-capability-audit
POST /ambush/shape-signature
POST /ambush/pattern-prototype-match
POST /ambush/historical-valley-sample-label
POST /ambush/three-channel-recall
```

兼容 dragon / L1-L3：

```text
POST /dragon/window-feature
POST /dragon/window-features
POST /ambush/valley-watch
POST /ambush/effective-turn-candidate
POST /ambush/pool-transition-audit
POST /dragon/l2-candidate
POST /dragon/deep-analysis
```

生产阶段：

```text
POST /ambush/phase2/valley-watch-pool
POST /ambush/phase2/effective-turn-anchor
POST /ambush/phase2/pool-transition
POST /ambush/phase2/run
POST /ambush/phase3/deep-confirmation
POST /ambush/phase3/release-gate
POST /ambush/phase3/run
POST /ambush/phase4/observation
POST /ambush/phase4/outcome
POST /ambush/phase4/failure-attribution
POST /ambush/finalization/lock-candidate
```

`/ambush/phase2/run` 和 `/ambush/phase3/run` 是 side-effect free 阶段管道验证；生产持久化仍由编排/仓储层完成。

## 输入数据样式

核心请求对象：

- `instrument`：`instrument_id`、`symbol`、`exchange`、`asset_type`、`board`、`is_active`、`is_suspended`、`is_st`、`is_delisting_risk`、`listing_days`、`price_limit_regime`。
- `bars`：日线数组，必须包含 `trading_day/trade_date`、`open/open_price`、`high/high_price`、`low/low_price`、`close/close_price`、`volume`、`amount`，正式评分优先使用 adjusted OHLC 字段。
- `weekly_bars`：周线上下文。
- `prototypes`：图库原型，含 positive、false bottom、hard negative。
- `as_of_trading_day`、`as_of_time`。
- Phase3 context：`moneyflow_context`、`sector_context`、`market_context`、`tradability_context`、`event_news_context`。`event_news_context` 只能来自经过 source-data-service 构建的 `source.event_news_v1`；Baidu Finance `finance_news_feed` 当前是 research-only 主源，CNINFO 为备源登记，不得把 provider 原始 feed 直接作为模型事实。
- Phase4：`signal_fact`、`buy_point`、成熟窗口内 `bars`。

所有在线阶段只能使用 `trading_day <= as_of_trading_day` 的数据。Phase4 outcome 才允许使用 signal 后路径数据。

## 状态流转

```text
source_capability_audit
-> shape_signature / pattern_prototype_match
-> three_channel_recall
-> valley_watch_pool
-> effective_turn_anchor
-> pool_transition_audit
-> phase3 deep_confirmation
-> release_gate
-> signal_fact contract
-> buy_point reference
-> observation
-> outcome
-> failure_attribution / pattern feedback
-> finalization lock candidate
```

池状态：

- `data_blocked`
- `valley_invalidated`
- `research_only`
- `not_qualified`
- `valley_watch`

有效抬头状态：

- `rejected`
- `backup_only`
- `accepted`

深度状态：

- `blocked`
- `research_only`
- `not_ready`
- `deep_confirmed`

release：

- `passed` -> `official_signal`
- `blocked` -> `not_released`

## 分数和阈值

图库和 source capability：

- P0 日线 OHLCV 覆盖率要求 `>= 98%`。
- `available_at` 覆盖率要求 `>= 98%`。
- 正式图形/结构计算要求 adjusted OHLC；缺 adjusted OHLC 只能 research-only。

Phase2：

- 窗口：默认 `60`，兼容窗口 `20/30/40/60/90/120`。
- 日线完整度：`>= 0.95`。
- 20 日平均成交额最低 `20,000,000`。
- 官方范围：深圳 A 股。
- `valley_maturity_score >= 62` 且 `false_rebound_risk <= 68` 才可进入 `valley_watch` 或 `research_only`。
- `hard_negative_similarity >= 75` 且 `shape_edge_score < 25` 阻断。
- `false_rebound_risk >= 75` 阻断。

Phase3 official：

- `MIN_OFFICIAL_TRADABILITY_SCORE = 60`。
- `MIN_OFFICIAL_DEEP_CONFIRMATION_SCORE = 64`。
- `MAX_OFFICIAL_FALSE_REBOUND_RISK = 72`。
- `MAX_OFFICIAL_RUNAWAY_RISK = 62`。
- `MAX_OFFICIAL_HARD_NEGATIVE_SIMILARITY = 65`。

证据层级：

- L1：有效抬头。
- L2：结构确认。
- L3：资金/量能确认。
- L4：板块/市场/可交易性确认。

## 缺口码和阻断

P0/结构缺口：

- `daily_bar_missing`
- `daily_bar_incomplete`
- `price_channel_invalid`
- `adjusted_ohlc_missing`
- `adjusted_ohlc_missing_research_only`
- `available_at_missing_or_incomplete`
- `weekly_context_missing`
- `pattern_match_missing`
- `not_shenzhen_a_share_scope`
- `not_a_share_scope`
- `special_treatment_stock`
- `suspended_stock`
- `delisting_risk_stock`
- `inactive_instrument`
- `daily_bar_history_insufficient`

Phase2 阻断：

- `hard_negative_similarity_dominates`
- `false_rebound_risk_too_high`
- `instrument_scope_or_tradability_blocked`
- `valley_pool_state_not_eligible`
- `runaway_from_trough`

Phase3 阻断：

- `effective_turn_anchor_not_accepted`
- `valley_watch_not_eligible`
- `deep_confirmation_not_passed`
- `effective_turn_not_accepted`
- `valley_watch_not_official`
- `source_gap_blocks_official_signal`
- `deep_confirmation_score_below_threshold`
- `false_rebound_risk_too_high`
- `tradability_score_too_low`
- `runaway_risk_too_high`
- `hard_negative_similarity_too_high`
- `moneyflow_context_missing`
- `sector_context_missing`
- `market_context_missing`

缺口必须保留，不得补 0 或空字符串。

## 数据产出

统一响应：

```json
{
  "model_name": "ambush_watchlist",
  "model_version": "string",
  "structured_output": {},
  "jarvis_payload": {},
  "contract_gaps": []
}
```

主要 `structured_output`：

- `recall`
- `valley_watch`
- `effective_turn_candidate`
- `effective_turn_anchor`
- `transition_audit`
- `analysis`
- `phase2`
- `deep_confirmation`
- `release_gate`
- `phase3`
- `observation`
- `outcome_label`
- `failure_attribution`
- `lock_candidate`

Jarvis payload 只读，不能给交易建议，不能修改模型状态、分数或标签。

## 落库表

当前服务本身不直接写生产数据库。持久化由编排/仓储层执行，目标合同表在分阶段 SQL 中定义：

- `infra/sql/0008_decision_ambush_phase1_pattern_library.sql`
- `infra/sql/0009_decision_ambush_phase2_valley_turn.sql`
- `infra/sql/0010_decision_ambush_phase3_phase4_finalization.sql`
- `infra/sql/bootstrap_schema.sql`
- `packages/db-schema/alembic/versions/0001_current_baseline.py`

目标 `decision_ambush.*` 合同包括：

- `decision_ambush.valley_pattern_library_version_v1`
- `decision_ambush.valley_pattern_sample_v1`
- `decision_ambush.valley_shape_signature_v1`
- `decision_ambush.valley_pattern_prototype_v1`
- `decision_ambush.valley_pattern_match_result_v1`
- `decision_ambush.ambush_daily_window_feature_v1`
- `decision_ambush.valley_watch_pool_v1`
- `decision_ambush.effective_turn_anchor_v1`
- `decision_ambush.effective_turn_pool_v1`
- `decision_ambush.ambush_pool_transition_audit_v1`
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

当前 `bootstrap_schema.sql` 也包含 `decision.ambush_*` 和 `decision.dragon_*` 兼容事实表；运行事实以当前容器和 `bootstrap_schema.sql` 为准。若 `decision_ambush.*` 合同表未在运行库出现，不能由 README 声称已经持久化。

## 调度

scheduler 任务：

- `ambush.source_capability.audit` -> `POST /ambush/source-capability-audit`
- `ambush.pattern_library.mine` -> `POST /ambush/historical-valley-sample-label`
- `ambush.phase2.valley_turn.close` -> `POST /ambush/phase2/run`
- `ambush.phase3.release_gate.close` -> `POST /ambush/phase3/run`
- `ambush.buy_point.reference` -> `POST /ambush/phase3/run`
- `ambush.observe.outcome.evolution` -> `POST /ambush/phase4/outcome`

时间：

- source capability：每周或新 provider 激活前。
- 图库挖掘：每日 `18:10` 增量，月度全量重建/影子评估。
- Phase2：收盘后 `15:20`，可选 `10:30` 研究扫描。
- Phase3 release gate：`15:35`。
- 买点参考：`15:35` 收盘参考，后续可接下一交易日开盘窗口。
- observation/outcome/evolution：每日 `15:55` 加 T+5/T+10/T+20 成熟检查。

## source preflight

official release 前必须通过：

```text
POST /source/release/preflight
```

preflight 返回 `can_release_official_signal=false` 时，本模型不得发布 official。`source.stock_moneyflow_daily_v1.main_net_inflow` 是 L3/L4 资金确认使用的 P1 degraded 字段，主源为 EastMoney `moneyflow_stock_series`，备源为 Tushare `moneyflow.net_mf_amount` 到 canonical `main_net_inflow` 的映射；缺失时可作为 degraded 非阻断项保留，但不得伪装为完整资金证据，也不得用 AKShare schema-mismatch 字段、0、空字符串或推断值补齐。`source.event_news_v1` 的 Baidu Finance 新闻源只作为事件/题材解释上下文和 research-only 证据，不改变 P0 日线 OHLCV、adjusted OHLC、tradability 与 source preflight hard gate；缺失时保留事件上下文缺口，不得补事实。2026-06-14 本地运行容器已验证 `000063.SZ / 2026-06-12` 的 EastMoney `main_net_inflow` 经 raw/source/lineage 写入后，scheduler `ambush_watchlist.release_gate` preflight 返回 `can_release_official_signal=true`、`coverage_status=passed`、`freshness_status=passed`、`degraded_reasons=[]`。

## 下游消费

- scheduler：触发 owner endpoint，不改模型事实。
- source-data-service：提供 source row、lineage、quality、preflight。
- research-service 或后续编排层：组装真实输入、处理行级异常、持久化模型事实。
- research-data-mart / data-inspector / execution-timing / gateway / frontend / Jarvis：只读消费或巡检。

## 异常兜底

owner API 内部无法评分时返回 422。批处理编排层必须把单条或单阶段异常转为行级研究事实：

- warning：`ambush_watchlist:row_failed:{symbol}:{stage}:{error_code}`。
- transition audit：`decision_result=data_blocked`、`trigger_event=model_service_exception`。
- window feature：所有窗口写 `pass_l1_gate=false` 和 `blocked_model_service_exception`。
- L2：`l2_status=blocked`、`liquidity_check=blocked_model_service_exception`。
- deep：`dragon_state=dragon_failed`、`dragon_head_score=null`、`evidence_gap_penalty=100`。
- payload：保留 `stage`、`symbol`、`instrument_id`、`as_of_time`、`error_code`、`error_message`、输入引用。

单条失败不得拖垮整批；有任一 `row_failed` 时 run 应返回 `partial`。

## 验收

定向测试：

```bash
python -m pytest -q services/models_services/ambush-watchlist-service/tests
python -m pytest -q tests/test_ambush_phase1_sql_contract.py tests/test_ambush_phase2_sql_contract.py tests/test_ambush_phase3_phase4_sql_contract.py
```

跨服务验收：

```bash
python scripts/core_services_acceptance.py --require-postgres
python scripts/core_services_acceptance.py --require-postgres --source-quality-matrix
```

真实 provider probe 由 source-data-service 和验收脚本执行，本服务不得绕开 source orchestration 直接探 provider。

## 当前闭环结论

潜伏抬头 owner service 的 source capability、图库、多通道签名、三路召回、谷底观察、有效抬头、Phase3 release、买点参考、observation、outcome、失败归因和锁定候选合同已在当前代码中实现。2026-06-14 本地 Docker 闭环中，`scripts/core_services_acceptance.py --require-postgres --real-provider-probe --source-quality-matrix` 返回 0，`ambush.phase3.release_gate.close` 经 scheduler live dispatch 到本服务返回 200，source release preflight 为 `can_release_official_signal=true`、`coverage_status=passed`、`freshness_status=passed`、`blocking_reasons=[]`。Baidu `source.event_news_v1` 已通过 source-data-service 真实 raw/source/lineage 写入验证，但在本模型中仍只作为 `event_news_context` research-only 题材/事件解释证据，不改变 P0/P1 source gate。当前最小闭环依赖 source-data-service、scheduler-service 和后续持久化编排；未阻断优化项见根目录 `需优化点.MD`。

### ambush-watchlist-service -> model3 reset -> 2026-07-08 zero state

- Record time: 2026-07-08 Asia/Shanghai.
- Confirmation source: user explicitly approved clearing model2/model3 execution audit and model3 taxonomy without historical backup, and explicitly requested not to start model2/model3 owner services.
- Cleared scope for model3: `governance.research_model_execution_audit_v1` rows where `model_code='ambush_watchlist'`, `owner_service='ambush-watchlist-service'`, `task_code LIKE 'ambush.%'`, or `task_code LIKE 'dragon.%'`; `3` rows were deleted. `research_ambush.ambush_valley_label_taxonomy_v1` was cleared; `11` taxonomy rows were deleted.
- Current data state: all current `decision_ambush.*`, `research_ambush.*`, compatible `decision.ambush_*`, and compatible `decision.dragon_*` tables have `0` rows.
- Runtime state: `ai-stock-ambush-watchlist-service` remains `Exited (0)` as requested; source, scheduler, data-inspector, and research services remain ready.
- Boundary: this is an authorized zero-data operational state only. Future ambush facts and taxonomy/reference rows must be regenerated through approved research/scheduler/owner flows, not manual table writes or mock data.

### ambush-watchlist-service -> model3 reset -> zero-data state freeze 2026-07-08

- 冻结对象：`ambush-watchlist-service -> model3 reset -> zero-data state`。
- 冻结时间：2026-07-08 Asia/Shanghai。
- 拍板人 / 确认来源：用户回复“你来决定拍板”；Codex 基于本轮数据库计数、服务健康和 owner 未启动状态决定可以拍板冻结。
- 锁定范围：模型三当前零数据运行状态；`decision_ambush.*`、`research_ambush.*`、兼容 `decision.ambush_*` 与兼容 `decision.dragon_*` 表均为 `0` 行；模型三 research execution audit 为 `0` 行；`research_ambush.ambush_valley_label_taxonomy_v1` 已按用户授权清为 `0` 行；`ai-stock-ambush-watchlist-service` 按用户要求保持 `Exited (0)`，本轮不启动。
- 允许的只读验收：数据库只读计数、`governance.research_model_execution_audit_v1` 模型三过滤计数、taxonomy 计数、Docker 只读状态、source/scheduler/data-inspector/research readyz。
- 禁止修改项：未经解锁不得手工写入模型三事实表或 taxonomy 字典、不得用 `0`、空字符串、mock payload 或推断补缺口、不得绕过 scheduler/research/owner 正式链路生成模型三事实、不得借本冻结记录修改模型三图库、阈值、状态机、调度或接口。
- 解锁条件：用户明确批准启动模型三 owner、恢复模型三正式调度/执行、重建模型三事实、重新初始化 taxonomy/图库字典、恢复历史数据或修改模型三数据合同。
- 回滚方式：本轮无历史备份；已删除的 3 条模型三 execution audit 和 11 条 taxonomy 字典不能从本轮备份恢复。若需要恢复，只能通过正式初始化、研究或 scheduler/research/owner 链路重新生成；文档冻结记录可按 Git 差异回退。
- 验证清单：模型三相关表非零残留为 0；模型三 execution audit 为 0；taxonomy 为 0；核心服务 ready；ambush owner 仍未启动。
