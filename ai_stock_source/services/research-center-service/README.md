# research-center-service

本目录是 `research-center-service` 服务根目录唯一当前 MD。全局硬约束以项目根目录 `AGENTS.md` 为准；`D:\projects\ai_stock\研究中心文档` 是本轮需求输入，落地事实以本 README、当前代码和 `infra/sql/bootstrap_schema.sql` 为准。

本服务数据资产账本见 `services/research-center-service/DATA_ASSETS.md`，记录 `research_ambush.*` 研究资产表、只读依赖和禁止反写边界。

## 定位

`research-center-service` 是研究中心后端承载层。第一阶段只落地模型三 `ambush_watchlist` 的低谷图形标注中心和低谷图库研究资产，不负责生产评分、发布 official signal、修改模型参数、改写买点、改写 outcome 或触发 provider。

本服务只写 `research_ambush.*` 研究资产表；模型三 owner service、source-data-service、scheduler-service 和 data-inspector-service 仍是只读依赖或健康信号，不由本服务改写。

第一阶段闭环范围：

```text
低谷图形样本登记
-> 样本队列读取
-> 标注字典读取
-> 当时可见 / 事后复盘人工标注
-> 复核记录
-> 图库成员沉淀
```

暂不落地完整 `research_dynamic` 共享域、动态特征重排验证、生产公式改版、模型三自动学习权重更新或调度自动生成样本；这些不是当前已落地事实。

## API

健康：

```text
GET /health
GET /healthz
GET /readyz
```

模型三低谷图库：

```text
GET  /research/ambush/taxonomy
GET  /research/ambush/valley-chart/cases
POST /research/ambush/valley-chart/cases
GET  /research/ambush/valley-chart/cases/{chart_case_id}
POST /research/ambush/valley-chart/cases/{chart_case_id}/labels
POST /research/ambush/valley-chart/cases/{chart_case_id}/reviews
POST /research/ambush/valley-chart/cases/{chart_case_id}/library-members
```

## 数据入口

- 人工或后续编排层提交的低谷图库样本。
- 后续可由研究编排从 `decision_ambush.*`、`source.*`、模型三 owner 输出和 outcome 标签生成样本，但本服务不得直接读取 raw，也不得直接调用 BaoStock、AKShare、EastMoney、Tushare、CNINFO 等 provider。
- 动态特征缺失时写入 `dynamic_gap_codes`，不使用 mock、0、空字符串或前端推断补齐。
- 前端低谷图库页提交的人工样本和标注；前端只提供中文白话控件，后端仍按本服务合同字段接收。

## 输入数据样式

低谷图库样本包含：

```text
chart_case_id
canonical_symbol
stock_name
case_trade_date
case_source
case_status
label_mode_allowed
as_of_date
valley_low_date
turn_anchor_date
source_data_version
model_version
feature_version
source_gap_codes
dynamic_gap_codes
daily_bar_payload
weekly_bar_payload
automatic_feature_payload
decision_ref
```

人工标注包含：

```text
labeler_id
label_mode: as_of / outcome_review
valley_structure_label
turn_timing_label
sample_role_label
outcome_label
manual_label_confidence
manual_label_note
tags
```

`as_of` 模式只能标注当时可见结构，禁止携带 `outcome_label`，也禁止使用只允许 `outcome_review` 的 taxonomy 标签。

前端页面不得直接显示上述字段名。操作员看到的是“结构判断、抬头时机、样本角色、结果归因、标注信心、备注、标注项”等白话控件；浏览器提交前再映射到本服务 API 合同。

## 状态流转

```text
pending_labeling
-> labeled
-> review_required / approved
-> pattern_library_member
```

状态只表示研究资产处理进度，不表示模型三生产信号状态。

`case_status=data_blocked` 表示样本缺少可复核事实；缺口必须保留在 `source_gap_codes` 或 `dynamic_gap_codes` 中。缺事实时仍可登记研究样本，但不能把空 K 线、空动态特征或事后推断当成真实事实。

## 数据产出

- 低谷图库样本列表和详情。
- 低谷图形人工标注记录。
- 标注多选标签明细。
- 标注复核记录。
- 图库成员记录，角色包括正样本原型、硬负样本、漏选机会、对照样本和仅研究样本。

这些产出只供研究中心、后续人工复核和训练样本准备使用；进入生产模型必须另走人工审核、版本变更和 owner service 合同。

## 调度

当前无内置定时任务，无启动时自动抓取，无 source fetch orchestration 提交。后续若需要自动从 `decision_ambush.*` 或 source 标准层沉淀样本，应由研究编排层或 scheduler 按批准后的新合同调用本服务 API，并继续遵守 source-data-service fetch orchestration 和 preflight 规则。

## 落库表

新增 schema：`research_ambush`。

表：

```text
research_ambush.ambush_valley_chart_case_v1
research_ambush.ambush_valley_manual_label_v1
research_ambush.ambush_valley_manual_label_tag_v1
research_ambush.ambush_valley_label_taxonomy_v1
research_ambush.ambush_valley_label_review_v1
research_ambush.ambush_valley_pattern_library_member_v1
```

SQL 文件：

```text
infra/sql/0024_research_ambush_valley_chart_library_v1.sql
infra/sql/bootstrap_schema.sql
```

## 缺口码

- `source_gap:research_ambush_case_missing`
- `source_gap:ambush_label_repository_missing`
- `source_gap:daily_bar_history_insufficient`
- `source_gap:dynamic_feature_bundle_missing`
- `source_gap:intraday_snapshot_missing`

缺口必须保留为数组或空态，不得用 mock 数据补齐。

## 禁止反写规则

- 不写 `decision_ambush.*` 生产评分、release gate、signal、buy point 或 outcome。
- 不写 source/raw。
- 不触发 scheduler 任务。
- 不修改模型参数或学习权重。
- 人工标注必须先作为研究资产保存，后续进入 pattern library 前需要 review；研究结论进入生产必须另走人工审核和版本变更。

## 验证

```bash
PYTHONPATH=services/research-center-service/src python -m pytest -q services/research-center-service/tests
python -m pytest -q tests/test_research_ambush_valley_chart_sql_contract.py
python -m py_compile services/research-center-service/src/research_center_service/*.py
```
