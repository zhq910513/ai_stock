# research-center-service DATA_ASSETS

本文件是 `research-center-service` 的数据资产账本，不替代本目录 `README.md`。

## 服务定位

当前仅承载模型三低谷图库研究资产。它写 `research_ambush.*`，不写 `decision_ambush.*` 生产评分、release gate、signal、buy point、outcome、source/raw 或调度事实。

## 读取数据

| 资产 | 用途 | 边界 |
|---|---|---|
| 人工提交的低谷样本 payload | 建立研究样本 | 必须保留缺口码，不用 mock K 线 |
| 前端低谷图库提交 | 人工标注、复核、图库成员 | 受控 POST，只写研究资产 |
| 后续编排可读 `source.*`、`decision_ambush.*` | 自动样本沉淀候选 | 当前未内置调度，不直接 provider |

## 写入数据

| 表 | 作用 |
|---|---|
| `research_ambush.ambush_valley_chart_case_v1` | 图形样本 |
| `research_ambush.ambush_valley_manual_label_v1` | 人工标注 |
| `research_ambush.ambush_valley_manual_label_tag_v1` | 标注标签 |
| `research_ambush.ambush_valley_label_taxonomy_v1` | 标签字典 |
| `research_ambush.ambush_valley_label_review_v1` | 标注复核 |
| `research_ambush.ambush_valley_pattern_library_member_v1` | 图库成员 |

## 调度频率

当前无内置定时任务。人工或前端提交按需写入。后续自动样本沉淀必须另行批准，由 scheduler 或研究编排层只读 source/decision 后调用本服务 API。

## 禁止事项

- 不直接调用 provider。
- 不修改模型三生产公式、学习权重或 release gate。
- 不把研究标注直接写成 official signal。
- 不用前端本地状态或 mock 补 K 线/动态特征。

