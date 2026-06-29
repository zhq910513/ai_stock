# 神策中心研究中心 V2 动态特征增强版文档包

生成时间：2026-06-14 05:58:37 UTC

本包是在以下原始文档基础上继续优化：

- hot_model_research_center_design_v1.md
- candidate_memory_model_research_center_design_v1.md
- ambush_watchlist_model_research_center_design_v1.md
- dynamic_feature_service_v2_landing_design.md

## 文档列表

1. `hot_model_research_center_design_v2_dynamic_enhanced.md`
   - 热点模型研究中心 V2。
   - 增加 teacher prior 盘中确认、热点动态重排、高开低走风险、涨停可交易性研究。

2. `candidate_memory_model_research_center_design_v2_dynamic_enhanced.md`
   - 候选记忆模型研究中心 V2。
   - 增加盘中提前重新激活、false reactivation 动态预警、missed reactivation 动态提示、二波分时结构研究。

3. `ambush_watchlist_model_research_center_design_v2_dynamic_enhanced.md`
   - 潜伏抬头模型研究中心 V2。
   - 增加分时微确认、回踩支撑、横盘压缩分时突破、假抬头动态预警、hard negative 动态可分离性。
   - 同步升级低谷图形标注中心，增加分时图、VWAP、买点窗口与分时打标维度。

4. `research_dynamic_shared_domain_design_v1.md`
   - 新增共享研究域 `research_dynamic`。
   - 用于跨模型动态特征增益验证、分桶有效性、动态重排后悔、replay 一致性和动态缺口影响研究。

## 核心边界

- 三大模型研究中心仍然独立，不混合样本。
- `research_dynamic` 是共享动态研究域，不替代模型研究域。
- 动态特征只能通过研究验证后进入生产候选。
- research replay 不能等同于 production snapshot。
- 总览页后续只展示模型级动态贡献趋势，不展示个股明细。
