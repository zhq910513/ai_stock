# models_services README

> 唯一模型集合根目录 MD。三大模型业务代码均处于锁定或锁定候选状态；未经用户明确批准不得修改。

## 当前锁定状态

- `hot-candidates-service`：`hot_candidates_service_v1.0_rc`，已锁定。
- `candidate-memory-service`：`candidate_memory_service_v1.0_rc_backend_closure_candidate`，已锁定。
- `ambush-watchlist-service`：`ambush_watchlist_service_v1.0_rc_backend_closure_candidate`，已锁定候选。
- 三模型调度：`scheduler_three_model_service_v1.0_rc_dispatch_candidate`，已锁定候选。

## 文档规则

- 本目录只保留 `README.md`。
- 每个模型根目录只保留一个 `README.md`，所有设计、接口、表、公式、调度、验证和未验证范围都必须合并在对应 README。
- 旧阶段报告、设计补丁、临时文档不得长期留在项目根目录。

---

# models_services 当前契约

更新时间: 2026-06-11

## 文档标准

本目录只能保留一个项目 MD：`README.md`。每个子模型目录也只能保留一个项目 MD：`README.md`。模型契约、跨服务协同、调度、前端展示和后续维护规则都写入本文件或对应子模型 README。

新需求包落地后，必须按模块合并覆盖唯一 README，不得新增分散 MD。

## 服务

- `hot-candidates-service:8031`：热点候选蒸馏模型，版本 `hot_candidates_v1`，详情见 `hot-candidates-service/README.md`。
- `candidate-memory-service:8032`：候选记忆模型，版本 `candidate_memory_v1`，详情见 `candidate-memory-service/README.md`。
- `ambush-watchlist-service:8033`：潜伏抬头 / 龙抬头模型，版本 `ambush_watchlist_effective_turn_v1_1`，详情见 `ambush-watchlist-service/README.md`。

## 跨服务数据流

```text
candidate / market / news / inspection facts
-> research-service 组装 row 或阶段 payload
-> 三大模型服务评分
-> research-service 落库
-> research-data-mart 同步研究快照、治理信号、标签和指标
-> execution-timing-service 生成买点版本
-> data-inspector-service 巡检模型、买点、监控、outcome、Jarvis 上下文
-> scheduler-service 启动守卫、定时评分、补跑、研究任务
-> gateway / frontend / Jarvis / explanation 只读展示与解释
```

## 跨服务职责

- `research-service`：组装三大模型真实输入、调用模型、写 decision 表、同步 data mart。
- `research-data-mart`：生成研究快照、黄金样本、治理信号、错排、消融、效果报告和机会反馈。
- `execution-timing-service`：读取模型信号和治理信号，生成 append-only 买点版本和诊断。
- `data-inspector-service`：巡检 `batch_next_day,realtime_top5,ambush,candidate_memory,model_hot_decision_review,model_memory_decision_review,model_ambush_decision_review,buy_point_service,signal_monitoring,outcome_validation,jarvis_context`。
- `scheduler-service`：启动触发 `data_inspection startup_guard`，并注册盘前热点评分、候选记忆评分、潜伏日线补跑、买点重算、信号监控和研究任务。
- `gateway-service` / `shence-frontend-service`：只读聚合、展示和状态翻译。
- `jarvis-service` / `explanation-service`：只读解释、巡检和建议。

## 统一不变量

- 模型服务不直接采集 provider，不直接写库。
- 模型服务不改标签、买点、交易、发布闸门或学习权重。
- 缺真实数据只能输出 `contract_gaps`、`source_gap_codes`、`warning`、空态或阻断状态。
- 编排层必须把模型服务异常转成行级研究事实：`row_failed` warning、`model_service_failure` payload、`source_gap:model_service_scoring_failed` 和阻断状态。
- `reference_entry_price` 是评估基准，不是交易价或推荐价。
- 买点版本链 append-only，修复写新版本。
- GPT/Jarvis 不得反写模型事实。
- 前端不得自行估算模型分、参考价、延迟或推荐状态。

## 异常状态标准

- 热点：`state=blocked`、`hot_score=null`，写入 `candidate_source_analysis_v1`、证据快照和缺口码。
- 候选记忆：`memory_state=blocked_data_gap`、`publication_state=blocked`，写入 entity、evidence、feature、analysis 和状态审计。
- 潜伏抬头：transition audit 写 `decision_result=data_blocked`；窗口特征写 `pass_l1_gate=false`；deep 失败写 `dragon_state=dragon_failed`。
- 异常记录字段：`symbol`、`instrument_id`、`stage`、`run_id/as_of_time`、`error_code`、`error_message`、`source_gap_codes`、输入引用。

## 调度概览

- 冻结采样：`09:25:05,09:25:30`。
- 热点盘前评分：`09:26:00,09:28:00,09:29:30`。
- 候选记忆评分：`09:00:00,09:40:00,11:50:00,15:40:00,16:20:00`。
- 潜伏日线补跑：`16:10:00,20:10:00`。
- 数据巡检：`08:55:00,09:26:00,09:40:00,11:35:00,15:10:00,17:10:00`，启动时另有 `startup_guard`。
- 买点实时：`09:30-10:00` 每 60 秒；固定窗口：`09:25,09:35,09:45,10:00,10:30,13:05,13:30,14:00`。
- 信号监控：`09:30-11:30,13:00-15:00` 每 300 秒。

## 当前闭环状态

后续所有模型契约和跨服务要求只更新本 README 或对应子模型 README，不再新增分散文档。
