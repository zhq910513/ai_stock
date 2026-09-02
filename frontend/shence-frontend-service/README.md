<!-- macp-migrated: copy-only 2026-09-02 -->

# MACP 迁入

状态：migrated_copy
来源：ai_stock_source/services/shence-frontend-service
代码与对照源一致，未改业务逻辑。未切换运行容器到本树。

---

# shence-frontend-service

本目录是新版本前端服务根目录唯一当前 MD。全局硬约束以项目根目录 `AGENTS.md` 为准；旧项目 `D:\projects\ai_stock_old\services\shence-frontend-service` 只能作为交互参考，不能作为事实源或兼容目标。

本服务数据资产账本见 `services/shence-frontend-service/DATA_ASSETS.md`，记录只读代理、研究中心受控写入和前端不得补事实的边界。

## 定位

`shence-frontend-service` 是当前锁定后端服务之上的工作台前端。它负责登录壳、候选输入页、四个模型页、研究中心-低谷图库页和轻量代理；除低谷图库页按研究中心合同写入 `research_ambush.*` 研究资产外，不负责生成模型事实、修改模型分数、补数据、发布 official signal、写交易建议或改写后端状态。

页面风格和布局按旧版神策前端的视觉语言重构：登录页保留深蓝双栏欢迎页，应用壳使用固定深色左侧导航、右侧内容区、旧版页头、8px 卡片、候选草稿 hero、KPI 卡片、sticky 表格和模型迭代列表样式。旧项目只作为视觉和交互布局参考，不继承旧页面入口、旧数据合同、旧接口或旧业务逻辑。

当前开放页面：

- `#/candidates`：候选输入页，复刻旧前端“候选草稿工作台 + 同花顺次日概率补充”的信息架构，但当前版本不再手动输入概率；页面展示 Cookie 配置小区域、付费概率自动抓取状态、只读概率表格、生成前检查和源数据复核面板。候选数量和候选事实只读取新版本已入库涨停事实，只统计收盘封板的 `limit_up` / `t_board_limit_up` 事件，炸板、未封板或 source 未覆盖的全市场标的不计入候选数。
- `#/model-hot`：热点候选模型页。
- `#/model-memory`：候选记忆模型页。
- `#/model-ambush`：潜伏抬头模型页。
- `#/model-tboard`：T 字接力观察台，只展示 Day1 已通过的普通用户观察对象，并跟踪 Day2 开盘后五分钟滚动接力机会。
- `#/research-ambush-valley`：研究中心-低谷图库页，只用于登记、查看和标注模型三低谷图形研究样本。

登录页直接复用旧前端的视觉和交互结构：账号、密码、登录状态、退出登录。当前本服务内置本地开发会话，默认账号来自环境变量 `SHENCE_FRONTEND_USERNAME` / `SHENCE_FRONTEND_PASSWORD`，默认值为 `admin` / `admin`。接入 gateway 后，可以改为代理 `/ui/auth/*`，但不得绕过后端权限事实。

其他旧页面（工作台、资讯、推荐、运行监管、Jarvis、设置、旧研究专项页）当前不开放，不出现在导航里；未知 hash 会跳回 `#/candidates`。

## 端口与运行

默认端口：`8030`。

```bash
python -m uvicorn shence_frontend_service.main:app --host 0.0.0.0 --port 8030
```

依赖：

- `fastapi`
- `httpx`
- `uvicorn`

## 页面字段合同

候选输入页字段：

```text
symbol
stock_name / name
rank_no / source_rank_no
limit_up_stage
limit_up_type
limit_up_open_count / open_num -> 显示为开板次数
first_limit_up_at
last_limit_up_at
paid_limit_up_probability -> source.ths_paid_limit_up_probability_v1 只读概率
paid_probability_status -> pending_cookie / cookie_expired / partial / ready / status_unknown / abandoned_no_probability_before_deadline
paid_probability_deadline -> 候选交易日的下一交易日 09:00 Asia/Shanghai
cookie_status -> missing / pending_probe / valid / expired / invalid / read_failed
cookie_user_masked / cookie_userid_masked -> 脱敏展示
candidate_source -> source.limit_event_v1
```

候选输入页沿用旧版“候选草稿 + KPI + 概率补充表格 + 生成前检查 + 源数据复核”的布局。页面默认读取 `source.limit_event_v1` 中最新可见交易日的已入库涨停事实；若后续显式指定业务日，则只展示该业务日候选，不把其他历史日期冒充为当前候选。只有读到候选行后，页面才并发关联同日标准日线、涨停价、资金流、`source.ths_paid_limit_up_probability_v1`、Cookie 状态和批次状态，只读展示行情、涨停价、资金事实和付费概率事实。首次登录后若没有 hash，前端只设置 `#/candidates` 并交给 hashchange 渲染候选页，避免同一候选页发起两次并发加载后把真实返回丢弃；加载期间保持完整候选工作台骨架，最终只读结果返回后原地更新数据，不用空白页或单块加载卡替换整屏。股票、交易日、涨停结构、开板次数、收盘封板、数据质量、数据来源和同花顺概率均为后端事实，不在前端编辑；页面唯一可写动作是必要时展示小型 Cookie 配置表单，提交后只调用 source-data-service 受控接口替换运行库留存 Cookie 并触发当前批次抓取。若标准层当前只返回 1 条涨停事件，页面候选数就显示 1，不把前端样例或旧公开池数量伪装成全市场涨停数量。候选页可见文案必须使用中文业务表达；标准层表名、provider 内部代码、原始记录号和提交 JSON 字段名只能留在内部 payload 中，不直接显示给操作员。

候选页 UI 必须保持旧代码页面风格和布局：

```text
candidate-workbench
-> candidate-draft-hero：当前候选草稿、业务日、候选来源、最近入库、读取状态
-> candidate-kpi-grid：候选数量、概率补齐、一板/二板、涨停原因、数据检查、生成检查
-> candidate-draft-main-grid
   -> candidate-editor-panel：同花顺 Cookie 配置、自动抓取状态、只读概率表格和工具条
   -> candidate-gate-panel：生成前检查、检查项、不能生成的原因、Cookie/批次阻断提示
   -> candidate-source-panel：源数据复核、开板次数、回封状态、页面形态
```

当前前端不再生成本地概率测试包，不提供手工概率输入，不显示测试补齐工具，也不把浏览器状态当成 owner model、scheduler、release gate 或数据库写入成功。当前候选为 0 时，概率补齐显示“等待候选”，概率检查不通过，按钮保持禁用，不能把 `0/0` 当成“已补齐”。Cookie 表单只在 `missing`、真实探测后的 `expired/invalid` 或后端批次 `cookie_expired` 时展示；`pending_probe` 和 `valid` 都显示为“Cookie 可用”，并隐藏编辑入口。Cookie 表单提交 `user`、`userid` 后调用 `/api/source/ths/paid-probability/cookie`，随后主动调用 `/api/source/ths/paid-probability/fetch-current-batch`；“立即抓取”按钮只触发同一 source-data-service 受控抓取入口。浏览器请求不得携带自身 Cookie 到后端代理，后端响应只允许返回脱敏 Cookie 状态。

Cookie 缺失时页面提示配置 Cookie；Cookie 失效必须来自 source-data-service 对同花顺付费接口的真实探测失败结果，前端不能因为读取超时、批次未返回或概率缺失自行判定失效。数据库已有留存 Cookie 且状态为 `pending_probe` 或 `valid` 时，页面显示“Cookie 可用”，不展示编辑块；Cookie 状态读取失败时显示“状态读取中”，不降级为未配置。日线、涨停价、资金流或概率 source 辅助读取超时只能进入 `source_enrichment_degraded` 辅助降级，不得覆盖候选主事实读取状态，也不得触发 Cookie 表单。批次说明必须由前端按 `status + cookie_status` 转成中文业务文案，不直接暴露后端英文 message、接口名、provider 细节或旧过期暗示。未到候选交易日的下一交易日 09:00 Asia/Shanghai 前，页面只能显示阻断/等待/部分入库，不得提示“本批已放弃”；只有 source-data-service 批次状态返回 `abandoned_no_probability_before_deadline` 时，页面才显示“本批候选已按规则放弃”。前端不得自行计算并写入放弃状态，deadline 判定以 source-data-service 为准。

候选过滤口径只接受最新交易日中 `limit_event_type in (limit_up, t_board_limit_up)` 且 `close_on_limit_flag=true` 的 source 行。前端会把后端布尔字段的 `true/false`、`"true"/"false"`、`1/0` 归一化后再展示，避免序列化形态差异导致真实候选被误过滤；但不会把炸板、未封板或 source 未覆盖股票补成候选。

候选输入表格保持旧页主列结构：

```text
股票
梯队 / 结构
首次涨停时间
最后涨停时间
形态
涨停原因
同花顺次日概率
状态
```

source 标准层未发布连续板梯队、首次/最后涨停时间、涨停原因、股票名称或排名时，页面显示“梯队暂未发布”“时间暂未发布”“涨停原因暂未发布”“名称暂未发布”等中文空态，对应内部字段保持 `null`，不得写入展示文案，也不得绕过标准层直接读取 raw。候选页会把 `source_quality_status` 和 `primary_provider` 翻译成中文展示，例如 `usable` 显示为“可用”、`ths` 显示为“同花顺”，避免把数据库枚举或 provider 代码直接暴露给操作员。候选输入页只展示 source 候选、source 付费概率、Cookie 状态和批次状态；生成前检查只展示候选来源、候选总数、概率入库数、Cookie/批次阻断原因和明细状态，不展示原始 JSON，不显示“自动提交=是”之类会被误读成已提交生产的文案。若后续接入候选服务，提交必须通过后端真实 API，并保留登录用户，不得用默认账号伪造 `created_by`。

模型页字段：

四个模型展示页当前只展示列表内容和列表顶部搜索/筛选工具条。本轮不开放单票详情、页头说明、KPI 卡片、字段覆盖矩阵、缺口聚合卡、运行合同摘要、低谷图库说明块、右上角只读角标或原始证据展开区。页面视觉复刻旧版“模型 / 决策回顾”列表风格：外层使用 `model-decision-list-page`，固定顶部使用 `decision-review-sticky-stack` 组合搜索/筛选条和 `decision-review-sticky-table-wrap` 表头，列表使用 `model-iteration-list`，主表使用 `model-iteration-table` 和 `model-iteration-row` 的紧凑密度、8px 边框、浅蓝加粗表头、状态胶囊、股票主副行和横向滚动同步。该复刻只针对页面风格和列表布局，不继承旧接口、旧字段、旧详情抽屉、旧 Jarvis 动作或旧业务逻辑。页面仍按锁定后端只读读取 source 标准层或模型四阶段仓库事实，但这些运行证据不再作为模型页可见模块输出；前端不执行写接口、不执行模型评分提交、不改后端状态、不补事实。

模型页可见文本必须是中文业务表达。股票代码、日期、数字、百分比和必要品牌名可以保留；时间戳统一展示为普通日期时间，不暴露 `T`、`Z` 或时区偏移后缀；数据库表名、schema 名、接口路径、服务名、程序枚举、JSON、raw payload、`source_gap:*` 原码、provider 内部代码、`repository`、`source` 等英文/程序文本不得直接出现在四个模型页列表、筛选下拉或错误提示中。缺真实数据时显示中文空态、中文缺口或中文状态，不用 0、mock、前端推断或旧样例补齐。浏览器错误、超时、后端不可读和仓库读取预算耗尽统一显示为中文业务提示，不能把 `/api/...`、`readyz`、`healthz`、HTTP traceback 或内部字段名展示给操作员。

四模型列表字段按当前 README 合同重新定义：

```text
hot_candidates:
股票、入选日、准备度、同花顺概率、模型分、最新价格、评估基准价、基准后涨幅、买入状态、基准后最大回撤、验证、风险、更新

candidate_memory:
股票、入选日、二波触发、模型分、最新价格、评估基准价、基准后涨幅、买入状态、基准后最大回撤、验证、风险、更新

ambush_watchlist:
股票、入选日、入选天数、模型分、最新价格、评估基准价、基准后涨幅、买入状态、基准后最大回撤、验证、风险、更新

t_board_relay:
股票、模型分、Day1、Day2、监测时间、当前判断、接力强度、关键依据、风险结论、更新
```

旧前端决策回顾的前三模型主列原为 12 列紧凑表；本轮热点模型在 `入选日` 后新增后端准备度列，成为 13 列：`股票 -> 入选日 -> 准备度 -> 同花顺概率 -> 模型分 -> 最新价格 -> 评估基准价 -> 基准后涨幅 -> 买入状态 -> 基准后最大回撤 -> 验证 -> 风险 -> 更新`。候选记忆和潜伏抬头仍保持 12 列，第三列分别为 `触发证据` 和 `入选天数`。本轮前端保留旧版表格视觉和字段密度，表格使用固定布局、旧版 min-width 量级、9px/10px 单元格 padding、12px 内容字号、普通单元格 650 字重、14px 加粗表头、桌面端 `fixed` 顶部层（右侧内容区 `left: 282px; right: 24px; top: 0`，窄屏退回内容流 `sticky` 避免遮挡顶部导航）和旧版整格风险 / 缺口底色；股票列使用旧版主副行 `stock-finance-name` 样式，主行 15px/950、副行 11px/850，但全部重新映射到当前新版本事实：

四个模型页搜索/筛选共用同一套 `decision-review-filter-row` 视觉合同，只作用于当前已读取的只读列表行，不重新写后端、不触发模型评分、不补齐缺失事实。筛选条件包括股票代码、模型对应的结构/状态/形态条件和缺口有无；筛选变更复用页面已加载行缓存，重置按钮只清空当前模型页前端筛选状态。统一筛选区采用旧版后台工具条的紧凑横向样式：主控件高度 `34px`、统计/重置区高度 `28px`、轻量边框和弱阴影，不按模型拆分不同样式。固定顶部层会按实际高度给列表自动留白，并扣减页面外层顶部偏移，让表头底部到首条数据保持小间距；表头和正文共用同一 `colgroup`，横向滚动保持同步。

模型列表不再用平均列宽承载所有字段；前端为热点模型维护 13 列 `colgroup` 宽度合同，为候选记忆和潜伏抬头维护 12 列 `colgroup` 宽度合同，为模型四维护 10 列 `colgroup` 宽度合同，并把每列标记为股票、日期、短字段、概率、分数、价格、百分比、状态、触发、风险、更新时间或缺口等语义类。表头和正文共用同一套列宽，进入任一模型页时横向滚动默认复位到最左侧，避免模型四首列被上一次滚动位置裁掉。股票代码列禁止把 `002849.SZ` 之类代码拆成两行；日期、价格、分数和百分比使用表格数字字形并保持稳定列宽；状态短语尽量不拆字，风险和缺口长文案可以按中文业务表达换行。该列宽合同只影响前端只读展示，不改变 source、模型服务、调度或仓库事实。

- `hot_candidates`：列表只消费 `GET /api/model-list/hot`，由前端服务代理 `research-service GET /research/model-list/hot`，展示已落库 `decision_hot.*` 热点模型结果。页面不再从 `source.limit_event_v1` 拼出热点模型行，也不按旧固定日期回退 source universe；没有已落库模型结果时显示空态或后端缺口。股票名、准备度、同花顺概率、模型分、发布状态、买点状态、评估基准价、验证和风险只来自后端只读投影，缺失保持 `NULL` / 中文缺口，不补 0、不用前端推断。准备度列展示后端 `hot_model_data_readiness_v1` 的 `readiness_score_pct`、`missing_points`、`readiness_state` 和最大缺失维度；无准备度事实时显示“待评估”，热点 KPI 显示“暂无 / 等待真实行”，不得把空列表解释成 0%。
- `#/model-hot` 首屏固定展示热点准备度 KPI、准备度维度矩阵和字段覆盖矩阵：KPI 包含数据准备度、P0 阻断、已有模型分、概率覆盖和数据缺口；维度矩阵按后端 `readiness_dimensions` 展示优先级、权重、覆盖和缺失分；字段覆盖矩阵的事实来源必须翻译为中文业务来源，不展示服务名、schema、表名、`source_gap:*` 原码、raw/provider/internal 文本或接口路径。该展示只读消费后端逐行准备度结果，不在前端重新评分、不补事实、不触发 source fetch。
- `#/model-hot` 首屏默认只读拉取 `/api/model-list/hot?limit=20`，用于保证准备度逐行真实验证后仍能在普通用户打开页面时完成加载；这只是浏览器首屏规模，不改变 `/api/model-list/hot` 和 `research-service /research/model-list/hot` 的 `limit` 参数能力，也不代表后端只保留 20 条模型事实。
- `candidate_memory`：列表 universe 由历史收盘封板候选按 `symbol` 聚合成记忆种子投影，展示首次/最近候选日、出现次数、自然日龄、最近涨停结构、行情和资金关联。当前无正式记忆实体只读列表 GET，因此交易日龄、TTL、模型分、买点、评估基准价、收益验证保持 `null` 或数据缺口阻断。页面只按最近候选日读取关联标准日线和资金流。
- `ambush_watchlist`：列表 universe 来自前复权日线按股票形成的低谷样本窗口，展示低点日、低点距今、样本天数、形态类型、低谷成熟提示、抬头新鲜度、前复权最新价和数据质量。当前无正式模型三决策仓库和标注仓库，模型分、买点、评估基准价、收益验证保持空态；资金上下文只读取最新样本日，缺失时显示中文缺口。

候选记忆和潜伏抬头当前仍没有独立只读列表 GET，前端只能用 source 标准层拼出可见 universe，并把未物化模型事实保留为 `null`、中文空态或中文缺口。热点模型已经改为只消费 `GET /api/model-list/hot` 的 `decision_hot.*` 只读投影，不再由前端 source universe 代替模型输出。不得用旧页面样例、旧 DOM、默认分数或前端推断补齐模型分、买点、验证结果。调度 sample 只用于连通性证据，不能进入列表作为市场事实。

模型三页面只展示潜伏抬头候选列表，不展示人工打标列、标签置信列、下拉控件、本地草稿或低谷图库说明块。图形打标属于后续“研究中心-低谷图库”页面：打标对象应是可查看 K 线和低谷形态的图形样本，不是模型三列表行；建议维度为形态质量、低谷成熟、抬头新鲜度、假反弹风险、流动性可交易性、资金/板块确认和结果标签。正式打标闭环需要后续由研究中心提供 append-only 标注 API；模型页不得用浏览器本地状态、前端 mock 或列表控件反写模型三事实、评分、标签仓库或学习权重。

研究中心-低谷图库页字段：

```text
页面可见控件：股票代码、股票名称、样本日期、低点日期、抬头日期、结构判断、抬头时机、样本角色、结果归因、标注信心、备注、标注项。
后端合同映射：页面提交前在浏览器内部转换为 research-center-service 的低谷样本和人工标注合同字段；可见区域不得直接展示库表字段名、schema 名、接口路径、原始 JSON 或数据库枚举。
```

低谷图库页只写研究资产，不写模型三 owner service、source/raw、scheduler、买点、outcome 或 official signal。`当时可见` 模式只允许记录当时能看到的结构；`事后复盘` 模式可以记录假抬头、硬负样本和结果归因。动态特征或 K 线事实缺失时显示中文缺口或空态，不用 mock、0、旧样例或前端推断补齐。

热点模型页额外读取：

```text
GET /api/model-list/hot
GET /research/model-list/hot
```

浏览器热点列表只调用本服务只读 compact 入口 `GET /api/model-list/hot`。该入口向 `research-service` 发起 `GET /research/model-list/hot`，返回浏览器前剥离可能出现的审计大字段。页面用 `hot_model.data.items` 映射 12 列并按 `model_score` 降序展示；没有 `decision_hot` 已落库模型结果时显示空态或后端缺口，不再回退到 `source.limit_event_v1`。

热点页顶部白话摘要只展示“当前入口 / 排序口径 / 缺口处理”和“当前答案 / 已有模型分 / 待补事实”：当前入口指向已落库热点模型结果，排序口径只按真实模型分，待补事实覆盖同花顺概率、买点、验证和发布闸门缺口；缺分不补 0，缺记录不补候选。

模型四页额外读取：

```text
GET /api/model-list/tboard
GET /t-board-relay/repository/status
GET /t-board-relay/observation-board
GET /t-board-relay/day1/candidates
```

浏览器模型四列表优先调用本服务只读 compact 聚合入口 `GET /api/model-list/tboard`。该入口向 `t-board-relay-service` 发起 `GET /t-board-relay/observation-board`、`GET /t-board-relay/repository/status` 和 `GET /t-board-relay/day1/candidates` 请求；前两个结果用于主列表、仓库可读性和观察台时间汇总，Day1 candidates 只用于生成“最近 Day1 扫描”汇总，不把 rejected/data_blocked 明细返回给浏览器。Day1 汇总只看最新 `trade_date`，并在该交易日内按 `canonical_symbol`、`symbol`、`stock.symbol` 或 `instrument_id` 去重，保留 `updated_at` / `created_at` 最新的一行后再统计扫描数、合格数、未通过数和主因；同时从 observation-board 压缩结果中提取 `last_model_output_at/model_evaluated_at` 作为最后一次模型产出时间、`latest_data_fetch_at/last_data_captured_at` 作为最新真实抓取 / 阶段事实时间、`latest_projection_snapshot_at` 作为只读审计时间。这是前端 compact 展示口径，不删除、不改写 owner append-only 候选事实。compact 响应继续剥离可能出现的 `request_payload`、`result_payload`、`game_hypothesis_payload`、`evidence_json`、`related_payload` 等审计 / 证据大字段后再返回给页面；完整审计 payload 仍保留在模型四 owner repository 和数据库中，前端不修改、不截断后端事实。`model_score`、`model_score_label`、`score_state` 和 `model_score_version` 只来自 owner `observation-board`，前端只展示并按 `model_score` 降序排序，不计算或补写模型分。默认 compact 响应不主动返回 `observation_status=stopped` 的终止对象；`observation_status=data_wait` 仅在 Day2 09:30-10:30 验证窗口未过时保留，一旦窗口已过仍没有有效 Day2 监测事实，也从普通用户主列表下架。Day2 判断优先使用 owner 返回的 `day2_trade_date`，缺失时按 `day1_trade_date` 推导下一个工作日并周末顺延；该口径只用于前端默认可见性，不补交易日事实。该过滤只影响普通用户默认列表，不删除 owner observation-board、monitor snapshot、repository 或 append-only 审计事实；排查历史失效 / 缺口样本时可显式读取 `GET /api/model-list/tboard?include_stale_stopped=true`。

模型四页面不再自行按 Day1/Day2/Day3 阶段仓库拼接事实，也不按股票代码兜底合并。普通用户列表只消费 owner `observation-board` 已投影好的观察对象：Day1 未通过、拒绝或数据阻断的股票不进入列表；Day2 必须是 Day1 后的下一个正常开市交易日，并在 09:30-10:30 每五分钟滚动观察，首次接近条件即作为接力机会提示；Day3 必须是 Day2 后的下一个正常开市交易日。若后端返回交易日待校验，页面只通过 owner 已投影的当前判断、关键依据或风险结论展示，不把同日记录显示成 Day2。所有模型页只展示后端返回事实；缺数据时显示空态、中文缺口或中文状态，不用 0、mock、前端推断或旧样例补齐。

模型四页面面向普通用户展示 10 个核心列：股票、模型分、Day1、Day2、监测时间、当前判断、接力强度、关键依据、风险结论、更新。页面不展示 `current_stage` / 观察阶段、`day3_trade_date` / Day3、`next_observation` / 下一步、`data_notice` / 数据提示、`data_gap_labels`、`candidate_status`、`not_triggered`、`day1_not_qualified`、`repository`、`source_gap:*`、`ASK`、`BID` 或接口路径。`模型分` 是模型四 owner 根据阶段事实投影的综合分，缺关键事实时保持空态，不补 0；页面按模型分由高到低展示，分数相同或缺失时再按 owner 更新时间兜底。`监测时间` 是 Day2 开盘后五分钟滚动监测中首次接近条件的检查时间，不是自动下单时间；`observation_status=data_wait` 在普通用户表中必须展示为“暂不观察 / 数据缺口”，不能展示为“等待确认 / 待确认”。`更新` 列必须显示两段时间：`last_model_output_at/model_evaluated_at` 对应“模型”最后一次 30 分钟结果产出，`latest_data_fetch_at/last_data_captured_at` 对应“抓取”最新真实抓取 / 阶段事实时间；`latest_projection_snapshot_at` 只保留为只读审计字段，不得冒充抓取时间。`风险结论` 只消费模型四 owner 根据盘口方向、成交强度、封板维护、Day3 去留或缺口事实投影出的结论，前端不得自行推断。当前判断、关键依据和风险结论列允许在模型四表格内按中文自然换行，`接力强度` 与 `更新` 列保留完整表头和稳定宽度，以保证 Day1 合格对象在普通用户页面可读。若后端返回股票名称为异常编码或英文样例名，前端显示“名称待标准化”或“标准层未发布名称”，不得把异常编码、旧样例英文名或数据库内部字段当成中文业务事实。

模型四移动端仍保留同一 10 列事实合同，不删列、不改字段、不补事实；页面标题条和最近 Day1 扫描摘要必须在窄屏下分行展示，避免把摘要正文挤成竖排。手机视口下模型四行展示为只读字段卡片，每张卡片仍按股票、模型分、Day1、Day2、监测时间、当前判断、接力强度、关键依据、风险结论、更新完整呈现，便于初级用户不用横向滑动就读到风险结论；该卡片化只影响浏览器展示，不改变 owner `observation-board`、compact 响应、排序或只读边界。

前端浏览器请求默认设置短超时保护，避免单个只读接口长时间不返回时卡住整个模型页。当前浏览器默认超时为 4.5 秒，列表事实读取为 3.5 秒，轻量关联读取为 2.2 秒；通用模型四只读代理保留 6.0 秒预算，热点模型 `/api/model-list/hot` 首屏真实 20 行准备度使用 24.0 秒浏览器预算和服务端 `SHENCE_FRONTEND_HOT_MODEL_LIST_TIMEOUT_SECONDS` 默认 30.0 秒预算，`/api/model-list/tboard` compact 聚合入口使用 24.0 秒浏览器预算和服务端 `SHENCE_FRONTEND_TBOARD_COMPACT_TIMEOUT_SECONDS` 默认 30.0 秒预算。候选页和前三模型页按页面所需分流读取，模型四观察台通过 compact 聚合入口读取，并在用户停留于 `#/model-tboard` 且已登录时按 `TBOARD_AUTO_REFRESH_MS=60000` 每 60 秒重新读取同一个只读接口；页面隐藏、切走路由或登出时清理刷新 timer，不写模型事实。候选页和四个模型页都采用静默刷新：已有内容时不先清空页面。模型四自动刷新在页面已渲染后只 patch 表格 body、Day1 扫描汇总、错误提示和不占布局的刷新角标，不重建页面壳、筛选区或固定表头，不重置横向滚动，也不重复绑定表格 chrome；读取失败时保留上次可见列表，并用中文状态提示“刷新失败，已保留上次结果”或对应业务失败原因，不把失败改写成 ready、passed 或模拟数据。页面渲染带有路由令牌保护：用户切到四模型页后，候选页旧异步请求返回不得覆盖当前模型页；模型页切换同理，旧请求只更新自己的缓存，不改写新路由的可见区域。模型页可以在内部读取 ready/health/source preflight 或模型四观察台作为组装依据，但最终可见区域只保留模型列表和模型四 Day1 扫描汇总。

## 后端代理

本服务提供 `/api/backend/{service}/{path}` 只读代理，面向当前已锁定服务：

- `source` -> `SOURCE_DATA_SERVICE_BASE_URL`，默认 `http://127.0.0.1:8041`
- `scheduler` -> `SCHEDULER_SERVICE_BASE_URL`，默认 `http://127.0.0.1:8023`
- `data-inspector` -> `DATA_INSPECTOR_SERVICE_BASE_URL`，默认 `http://127.0.0.1:8025`
- `hot` -> `HOT_CANDIDATES_SERVICE_BASE_URL`，默认 `http://127.0.0.1:8031`
- `memory` -> `CANDIDATE_MEMORY_SERVICE_BASE_URL`，默认 `http://127.0.0.1:8032`
- `ambush` -> `AMBUSH_WATCHLIST_SERVICE_BASE_URL`，默认 `http://127.0.0.1:8033`
- `tboard` -> `T_BOARD_RELAY_SERVICE_BASE_URL`，默认 `http://127.0.0.1:8035`
- `research-service` -> `RESEARCH_SERVICE_BASE_URL`，默认 `http://127.0.0.1:8029`，只用于热点模型列表 compact 代理。
- `research` -> `RESEARCH_CENTER_SERVICE_BASE_URL`，默认 `http://127.0.0.1:8028`

默认只允许 `GET`。候选输入页和模型页不得通过前端代理直接触发后端写操作。需要新增写操作时必须先解除对应服务锁定并由后端提供明确合同。

候选页的同花顺付费概率 Cookie 配置使用独立受控代理 `/api/source/ths/paid-probability/{path}`，只允许下列方法和路径：

```text
GET  cookie/status
PUT  cookie
POST probe
POST fetch-current-batch
GET  batch-status
POST deadline-check
```

该代理只转发到 `source-data-service /source/ths/paid-probability/*`，会剥离浏览器请求自带 Cookie；它不得作为通用 source 写代理，不得修改模型事实、source 概率事实、调度事实、release gate、买点、outcome 或学习权重。Cookie 明文只在提交请求体中短暂经过前端和 source-data-service，后端响应只允许返回脱敏状态。

`/api/research/{path}` 是研究中心受控代理，允许 `GET/HEAD/OPTIONS/POST`。当前 POST 只面向 `research-center-service` 的低谷图库研究资产写入；它不得被用于修改模型评分、发布闸门、source/raw、调度任务、交易事实或学习权重。

只读代理默认超时由 `SHENCE_FRONTEND_BACKEND_TIMEOUT_SECONDS` 控制，默认 `6.0` 秒；source preflight 代理默认超时由 `SHENCE_FRONTEND_PREFLIGHT_TIMEOUT_SECONDS` 控制，默认 `6.0` 秒；热点模型列表 compact 入口由 `SHENCE_FRONTEND_HOT_MODEL_LIST_TIMEOUT_SECONDS` 控制，默认 `30.0` 秒；模型四 compact 聚合入口由 `SHENCE_FRONTEND_TBOARD_COMPACT_TIMEOUT_SECONDS` 控制，默认 `30.0` 秒。代理超时只影响前端等待体验，不改变后端事实、不重试写操作、不触发抓取、不修改模型状态。

## 验证

```bash
$env:PYTHONPATH='services/shence-frontend-service/src'
python -m pytest -q services/shence-frontend-service/tests
```

验收重点：

- 导航只开放候选输入、四个模型页和研究中心-低谷图库页。
- 登录页存在且未登录时遮挡应用。
- 其他旧页面入口不在前端源码开放列表中。
- 候选页候选数量等于 `source.limit_event_v1` 最新可见交易日中收盘封板涨停/T 字板行数；炸板和未封板事件只计入过滤数，不作为候选。若显式指定业务日，则不回退历史日期冒充当前候选。
- 候选页不允许手动编辑同花顺次日概率，不显示随机测试补齐；概率只读来自 `source.ths_paid_limit_up_probability_v1`，页面仅在 Cookie 缺失或真实探测失败后展示 `user`、`userid` Cookie 配置表单。
- 候选页无候选时，概率补齐显示“等待候选”，抓取按钮禁用，不能把 `0/0` 当作通过。
- 数据库已有留存 Cookie 且未被真实接口探测判定失败时，页面显示 Cookie 可用并隐藏编辑入口；读取超时不能降级为未配置。未到候选交易日的下一交易日 09:00 前只能阻断/等待，只有后端批次状态为 `abandoned_no_probability_before_deadline` 时才显示“本批已放弃”。
- `/api/source/ths/paid-probability/*` 只允许 cookie/status、cookie、probe、fetch-current-batch、batch-status、deadline-check 六个受控路径，不放开通用 source 写代理，且不得把浏览器 Cookie 转发给后端。
- 四模型页必须有列表主视图；前三模型展示标准层可见 universe 和中文缺口，模型四展示 owner `observation-board` 投影后的 Day1 合格观察台。
- 模型四默认列表不主动展示已终止对象；Day2 09:30-10:30 验证窗口已过仍缺有效监测事实的 `data_wait` 对象也默认下架。历史失效 / 缺口事实只能通过显式只读参数或 owner 观察台排查，不在普通用户默认视图里挤占当前观察对象。
- 候选页和模型页必须使用短超时和并发读取；一个后端只读接口慢或失败时，页面不能整体卡死，必须保留已读取行和中文空态。
- 前三模型列表必须复刻旧版决策回顾 12 列骨架和字段大小，覆盖模型分、最新价、评估基准价、基准后涨幅、买入状态、最大回撤、验证、风险和更新；四个模型页必须保留顶部搜索/筛选条件，并且搜索条件必须共用同一套紧凑专业样式；表头必须固定、加大加粗，表头与首条数据之间不得出现明显空洞，状态 / 风险 / 缺口优先用旧版整格单元格样式，不在模型列表里使用大面积调试胶囊；当前未物化事实必须显示中文空态或中文缺口，不在列表里新增调试列。
- 模型三页面只展示低谷候选列表，不展示人工标签、标签置信、打标维度或本地草稿；图形打标只放在研究中心-低谷图库。
- 研究中心-低谷图库页使用中文白话控件，不把 `research_ambush.*`、库表字段名、接口路径或原始 JSON 暴露给操作员；提交时只在内部映射到研究中心后端合同。
- 模型页只读调用当前后端服务，不直接访问 provider，不直接读取 raw。
- 文案明确不补事实、不生成模拟推荐。

## 模型四前端语义

模型四页面只做用户可读翻译，不改 owner 事实。`model_score`、`model_score_label`、`score_state`、`current_conclusion`、`relay_strength_label`、`key_reason`、`risk_tip` 仍以 `GET /api/model-list/tboard` 聚合后的 owner 投影为准；前端只允许把明显终止态翻译成更直白的展示词，避免普通用户看到“模型分 0”同时又看到“中”等强度标签而误解。页面主体在模型四路由顶部显示“T 字接力观察台”标题条和“首日合格对象；次日每 5 分钟观察；停止原因逐行展示。”的简短口径，帮助普通用户确认当前列表含义；该标题条不增加写操作、不改变 10 列合同、不替代 Day1 扫描汇总。默认列表会立即隐藏 `stopped` 终止对象；`data_wait` 只有 Day2 09:30-10:30 验证窗口未过时保留，一旦窗口已过仍没有有效 Day2 监测事实，也从普通用户主列表下架；继续观察或仍在验证窗口内的对象仍按 owner 分数和更新时间排序。

当前白话规则：
- 触发后开板、破板、封板维护失败或封住到收盘失败，展示为“封板失败 / 已开板，停止观察 / 封板没守住，次日退出风险高”，关键依据简写为“触发后开板，封板没守住”。
- 接近涨停时卖盘主动砸向买盘，展示为“卖压占优 / 卖压占优，停止观察 / 卖盘往下砸，买入确认失败”，关键依据简写为“接近涨停，卖盘往下砸”。
- Day2 滚动监测未接近涨停，展示为“未触发 / 未触发，停止观察 / 没有接近涨停，接力不足”，关键依据简写为“5 分钟监测未接近涨停”。
- Day2 买盘主动扫掉卖盘且触发接力时，展示为“已触发，继续看封板”，关键依据简写为“接近涨停，买盘扫掉卖盘”，风险结论聚焦“收盘前能否封住”。
- `model_score=0` 是 owner 明确给出的硬失败综合分，可以展示；缺关键事实时必须保持 `model_score=NULL` 或空态，前端不得用 0 补齐。
- 风险结论必须是模型基于盘口方向、成交强度、封板维护、Day3 去留或事实缺口得出的具体结论；不得展示空泛免责文案。

## 拍板冻结记录

### shence-frontend-service -> model-hot -> readonly decision-hot list

- 冻结时间：2026-06-25 Asia/Shanghai。
- 拍板人 / 确认来源：用户批准热点候选/热点模型链路精修，要求打通真实模型输出到前端只读展示。
- 锁定范围：`#/model-hot` 模型一列表页、热点候选 12 列只读展示、搜索 / 筛选工具条、`GET /api/model-list/hot` compact 入口、`research-service GET /research/model-list/hot` 读取路径、`decision_hot.*` 已落库模型结果投影、审计 payload 剥离、中文空态和中文缺口展示、前端只读代理边界。
- 当前运行事实：`#/model-hot` 不再从 `source.limit_event_v1` 或固定历史日期拼出热点模型行；列表只消费 `hot_model.data.items`，按真实 `model_score` 降序展示。无已落库热点模型结果、缺同花顺概率、缺买点、缺评估基准或缺同日行情时，页面显示空态或中文缺口，不补 0、不显示模拟分数、不把 source universe 冒充为模型产出。
- 允许的只读验收：访问 `#/model-hot`、读取 `/api/model-list/hot`、读取 `research-service /research/model-list/hot`、读取 `/api/backend/hot/readyz` 和 `/api/backend/hot/healthz`、运行前端合同测试、Playwright 截图、DOM 可见文本检查、服务健康检查。
- 禁止修改项：未经解锁不得修改模型一列表列定义、`/api/model-list/hot` compact 合同、research-service 热点投影读取边界、缺口中文翻译、只读代理方法限制、Cookie 受控代理边界、前端 DATA_ASSETS/README 事实；不得让模型一页面触发模型评分、scheduler dispatch、source fetch、provider 请求、raw 读取、official signal、交易事实、买点、outcome 或学习权重写入。
- 解锁条件：用户明确批准 `shence-frontend-service -> model-hot -> readonly decision-hot list` 解锁，并说明目标、影响范围、拟修改文件、回滚方式和验证清单；若需改变 source/scheduler/owner 模型逻辑，必须另行解锁对应服务。
- 回滚方式：回退本对象相关前端变更，恢复到上一版模型一页面只读展示口径；回滚后必须确认页面不误显示模拟数据、不反写后端，并重新运行前端合同测试。
- 验证清单：`python -m pytest -q services/shence-frontend-service/tests/test_frontend_contract.py`；`GET /api/model-list/hot` 返回 `read_only=true` 且不含审计 payload；`#/model-hot` 显示真实只读行或中文空态，且可见文本不包含 `source_gap:*`、接口路径、`raw`、provider 程序文本或模拟推荐；source-data、data-inspector、scheduler、research、hot owner ready。

### shence-frontend-service -> model-hot -> data readiness display

- 冻结时间：2026-06-27 Asia/Shanghai。
- 拍板人 / 确认来源：用户明确回复“拍板”，并要求“继续完成拍板”。
- 锁定范围：`#/model-hot` 热点准备度展示层、`GET /api/model-list/hot?limit=20` compact 读取、浏览器 24 秒预算、服务端 `SHENCE_FRONTEND_HOT_MODEL_LIST_TIMEOUT_SECONDS=30.0` 默认预算、顶部准备度 KPI、行级准备度列、下方准备度维度矩阵、字段覆盖矩阵、审计 payload 剥离和只读边界。KPI 固定展示列表记录、数据准备度、P0 阻断、已有模型分、概率覆盖和数据缺口；维度矩阵展示后端 `readiness_dimensions` 的优先级、权重、覆盖和缺失分；字段覆盖矩阵只展示中文业务来源。
- 当前运行事实：登录后 `GET /api/model-list/hot?limit=20` 返回 `contract_kind=shence_hot_model_list_compact_v1`、`read_only=true`、`compact_audit_payloads=true`、`hot_model.data.readiness_contract=hot_model_data_readiness_v1`、`readiness_weight_total=100`、13 个维度、20 条真实行、平均准备度 `69.0%`、平均缺 `31.0` 分、P0 阻断 `20`；首行 `600367.SH` 准备度 `69`、状态 `blocked`、缺 `31` 分、最大缺口 `open_5m_reference_path`。浏览器 `#/model-hot` 显示 20 行真实列表、13 列、数据准备度 KPI、准备度维度矩阵、字段覆盖矩阵和缺失分；可见文本不得包含 `source_gap:*`、接口路径、服务名、schema/table、`decision_hot`、raw、provider、repository 或审计 payload。
- 允许的只读验收：访问 `#/model-hot`、读取 `/readyz`、读取 `/api/model-list/hot?limit=20`、读取 `research-service /research/model-list/hot?limit=20`、运行前端合同测试、Python 编译检查、JS 语法检查、Playwright DOM 与截图检查、检查相关服务 ready。
- 禁止修改项：未经解锁不得改变准备度 KPI、维度矩阵、默认 20 行首屏、24/30 秒等待预算、compact 字段剥离、只读代理边界或空态显示；不得让前端触发模型评分、scheduler dispatch、source fetch、provider 请求、raw 读取、official signal、交易、买点、outcome 或学习权重写入；不得把缺失准备度、缺失概率、缺失买点或缺失验证补成 0、空字符串、mock、示例 payload 或前端推断。
- 解锁条件：用户明确批准 `shence-frontend-service -> model-hot -> data readiness display` 解锁；若需要改变 `research-service` 准备度维度/权重/P0 语义、source/scheduler/owner 模型逻辑、或付费概率合同，必须另行解锁对应服务。
- 回滚方式：回退本对象对应的前端 JS、代理超时、合同测试和 README / DATA_ASSETS 变更，重新运行前端合同测试、Python 编译检查、JS 语法检查和 Playwright 页面验收；不清库、不重启 `source-data-service`，也不修改 `decision_hot.*` 或模型 owner 数据。
- 验证清单：`PYTHONPATH=services/shence-frontend-service/src python -m pytest -q services/shence-frontend-service/tests/test_frontend_contract.py` 通过；`python -m compileall -q services/shence-frontend-service/src services/shence-frontend-service/tests` 通过；`node --check services/shence-frontend-service/public/app.js` 通过；`git diff --check` 通过；frontend/research/hot owner/scheduler/data-inspector/source 健康；`#/model-hot` 可见准备度 KPI、P0 阻断、20 行真实列表、准备度维度矩阵、字段覆盖矩阵和缺失分，且可见文本不含内部服务、schema/table、接口路径、raw/provider/repository 或审计 payload。

### shence-frontend-service -> model-tboard -> observation board readonly list

- 冻结时间：2026-06-21 Asia/Shanghai。
- 拍板人 / 确认来源：用户确认模型四前端后端整改任务书并要求普通用户观察台口径；本轮按确认范围解锁并完成整改。
- 锁定范围：`#/model-tboard` T 字接力观察台、模型四 10 列只读展示（股票、模型分、Day1、Day2、监测时间、当前判断、接力强度、关键依据、风险结论、更新）、搜索 / 筛选工具条、`GET /api/model-list/tboard` compact 聚合入口、`GET /t-board-relay/observation-board` owner 读取路径、审计 / 证据大字段剥离清单、中文业务结论 / 风险结论、浏览器 24 秒 compact 预算、服务端 `SHENCE_FRONTEND_TBOARD_COMPACT_TIMEOUT_SECONDS=30.0` 默认预算、前端只读代理边界。模型分只来自 owner 字段，页面只展示和排序。
- 允许的只读验收：访问 `#/model-tboard`、读取 `/readyz`、读取 `/api/model-list/tboard`、读取模型四 `/t-board-relay/observation-board`、运行前端合同测试、Playwright 截图、DOM 可见文本裸码检查、服务健康检查。
- 禁止修改项：未经解锁不得修改模型四观察台列定义、Day1 未通过不入列表规则、正常开市交易日口径、compact 聚合入口、审计大字段剥离清单、只读代理方法限制、中文业务文案、超时预算、模型四前端数据资产记录、README 冻结事实；普通用户列表不得重新展示“观察阶段”“Day3”“下一步”“数据提示”列，不得直接展示 `ASK` / `BID`；不得让前端触发模型评分、调度、source fetch、provider 请求、raw 读取、official signal、交易事实、买点、outcome 或学习权重写入。
- 解锁条件：用户明确批准 `shence-frontend-service -> model-tboard -> observation board readonly list` 解锁，并说明目标、影响范围、拟修改文件、回滚方式和验证清单；若需改 `t-board-relay-service` owner `observation-board` 合同，必须另行解锁模型四 owner 服务。
- 回滚方式：回退本冻结对象相关前端变更，恢复到解锁前模型四只读列表；回滚后必须确认页面不误显示模拟数据、不反写后端，并重新运行前端合同测试。
- 验证清单：`python -m pytest -q services/shence-frontend-service/tests`；`python -m compileall -q services/shence-frontend-service/src services/shence-frontend-service/tests`；`GET /api/model-list/tboard` 不包含 `request_payload/result_payload/game_hypothesis_payload/evidence_json/related_payload`；`#/model-tboard` 只显示 Day1 合格观察对象且可见文本不包含 `source_gap:*`、接口路径、`repository`、`not_triggered`、`day1_not_qualified`、`blocked_data_gap`；source-data、data-inspector、scheduler、research、t-board owner ready。

### shence-frontend-service -> model-tboard -> live readonly observation board

- 冻结时间：2026-06-24 Asia/Shanghai。
- 拍板人 / 确认来源：用户要求 Codex 决定是否拍板；Codex 判定“今天可以看到模型四正常产出”的前端只读目标已达成，可窄冻结。
- 锁定范围：`#/model-tboard` 当前只读展示 4 条 Day1 合格观察对象；主列表锁定 10 列：股票、模型分、Day1、Day2、监测时间、当前判断、接力强度、关键依据、风险结论、更新；浏览器按 `TBOARD_AUTO_REFRESH_MS=60000` 每 60 秒只读刷新 `/api/model-list/tboard?limit=100` 并按 owner `model_score` 降序展示；不展示“观察阶段”“Day3”“下一步”“数据提示”列，不直接展示 `ASK` / `BID`、`source_gap:*`、repository/schema/provider/raw/internal 文本。
- 当前运行事实：`GET /api/model-list/tboard?limit=20` 返回 `read_only=true`，且 `observation_board.data.items` 为 4 条；`600172.SH 黄河旋风` 已显示“触发后开板，停止观察”，关键依据为“理论触发后出现开板”，风险结论为“触发后开板，封板维护失败，Day3退出风险升高”；截图留存在 `services/shence-frontend-service/playwright-artifacts/model-tboard-20260624-final-validation.png`。
- 允许的只读验收：访问 `#/model-tboard`、读取 `/api/model-list/tboard`、读取 owner `/t-board-relay/observation-board`、检查 DOM 可见文本、运行前端合同测试、检查相关服务 ready。
- 禁止修改项：未获解锁不得调整模型四列定义、60 秒只读刷新、compact 字段剥离、中文白话文案、Day1 合格对象纳入规则或前端只读边界；不得让前端触发模型评分、scheduler dispatch、source fetch、provider 请求、raw 读取、official signal、交易、买点、outcome 或学习权重写入。
- 解锁条件：用户明确批准本子对象解锁；若 owner `observation-board` 字段、状态或纳入规则变化，必须另行解锁 `t-board-relay-service`。
- 回滚方式：回退后续前端只读展示/compact 变更并重新运行前端合同测试；不清库、不重启 source-data-service。
- 验证清单：compact 的 `observation_board.data.items` 为 4 条；响应不含审计大字段；页面只显示 10 列并包含“模型分”；页面可见文本不含旧列名、`ASK`、`BID`、`source_gap:*`、接口路径或内部表名；相关后端服务 ready；frontend tests 通过。

### shence-frontend-service -> model-tboard -> snapshot refresh acceptance

- 冻结时间：2026-06-24 Asia/Shanghai。
- 拍板人 / 确认来源：用户授权 Codex 判断模型四链路是否可拍板，并在本轮回复“批准”；Codex 基于登录会话、compact API 和 Playwright DOM 验收判定普通用户可读目标已达成。
- 锁定范围：登录后的 `GET /api/model-list/tboard?limit=20` 和 `#/model-tboard` 页面必须只读消费 owner `observation-board` 当前投影；股票代码/名称来自 `stock.symbol/name`；页面按 owner `model_score` 降序展示，并显示最后一次模型产出时间和最新真实抓取/阶段事实时间。
- 当前运行事实：`/api/auth/login` 使用默认本地账号认证成功；`/api/model-list/tboard?limit=20` 返回 `contract_kind=shence_tboard_model_list_compact_v1`、`read_only=true`、`compact_audit_payloads=true`、repository/observation_board 均 `ok=true`；4 条 Day1 合格对象为 002297.SZ 博云新材、600769.SH 祥龙电业、301580.SZ 爱迪特、600172.SH 黄河旋风；模型分排序为 15/12/12/0；4 行更新时间均为 `2026-06-24 09:50:48`；响应不含 `request_payload/result_payload/game_hypothesis_payload/evidence_json/related_payload`。
- 浏览器验收事实：Playwright 登录后进入 `#/model-tboard`，DOM 表头为股票、模型分、Day1、Day2、监测时间、当前判断、接力强度、关键依据、风险结论、更新；DOM 行数为 4，四只股票代码和中文名称均可见；页面未显示“数据提示”“不自动下单”“接力机会提示仅作观察”。
- 允许的只读验收：访问 `#/model-tboard`、读取 `/api/model-list/tboard`、读取 owner `/t-board-relay/observation-board`、检查 DOM 可见文本、检查 frontend `/readyz`、运行前端合同测试。
- 禁止修改项：未获解锁不得调整模型四列定义、compact 字段剥离、60 秒只读刷新、股票名读取口径、模型分排序、中文白话文案或前端只读边界；不得让前端触发模型评分、scheduler dispatch、source fetch、provider 请求、raw 读取、official signal、交易、买点、outcome 或学习权重写入。
- 回滚方式：回退后续前端只读展示/compact 变更并重新运行前端合同测试和 DOM 验收；不清库、不重启 source-data-service。
- 验证清单：compact 4 行可读；股票代码和名称完整；模型分按 15/12/12/0 降序；更新列展示模型产出时间和真实抓取/阶段事实时间；页面只有 10 个核心列；无审计 payload、`ASK`、`BID`、`source_gap:*` 或无意义免责声明。

### shence-frontend-service -> model-tboard -> dual-time update display

- 冻结对象：`shence-frontend-service -> model-tboard -> dual-time update display`。
- 冻结时间：2026-07-01 Asia/Shanghai。
- 拍板人 / 确认来源：用户在模型四双时间修复交付后回复“允许”，批准拍板冻结。
- 锁定范围：`GET /api/model-list/tboard` compact 聚合和 `#/model-tboard` 更新列展示。前端必须从 owner `observation-board` 提取 `last_model_output_at/model_evaluated_at` 作为“模型”最后一次 30 分钟结果产出时间，提取 `latest_data_fetch_at/last_data_captured_at` 作为“抓取”最新真实抓取 / 阶段事实时间；`latest_projection_snapshot_at` 只可作为审计字段参与排查，不得展示或排序成抓取时间。页面仍只读消费 owner 投影，不触发 scheduler/source/provider/raw，也不计算模型分。
- 当前冻结证据：2026-07-01 登录后读取 `/api/model-list/tboard?limit=20` 返回 `contract_kind=shence_tboard_model_list_compact_v1`、`read_only=true`、repository / observation_board 均 `ok=true`；summary 暴露 `last_model_output_at=2026-07-01T02:32:00+00:00`、`latest_data_fetch_at=2026-06-26T07:53:37.143354+00:00`、`latest_projection_snapshot_at=2026-07-01T02:30:00+00:00`，前端更新列显示“模型 / 抓取”双时间而不是单一更新时间。
- 允许的只读验收：访问 `#/model-tboard`、读取 `/readyz`、读取 `/api/model-list/tboard`、读取 owner `/t-board-relay/observation-board`、检查 DOM 可见文本、运行前端合同测试、Python 编译检查和 JS 语法检查。
- 禁止修改项：未经解锁不得把投影时间显示成抓取时间，不得把 5 分钟快照当作模型产出时间，不得删除“模型 / 抓取”双时间展示，不得让前端补 0、空字符串、当前时间或推断时间，不得让前端触发模型评分、scheduler dispatch、source fetch、provider 请求、raw 读取、official signal、交易、买点、outcome 或学习权重写入。
- 解锁条件：owner `observation-board` 时间字段合同、research 30 分钟结果合同、scheduler 调度频率、前端模型四列合同或用户明确批准解锁。
- 回滚方式：回退本对象对应的 compact 时间提取、浏览器渲染、合同测试、README 和 DATA_ASSETS 变更，重新运行前端合同测试、Python 编译检查、JS 语法检查和 `/api/model-list/tboard` 只读验收；不清库、不重启 `source-data-service`，也不修改模型四 owner 数据。
- 验证清单：更新列显示“模型 <30 分钟结果时间|未产出> / 抓取 <真实抓取时间|未推进>”；`latest_projection_snapshot_at` 不冒充抓取；compact 不泄露审计 payload；模型分仍来自 owner 并按分数排序；scheduler/data-inspector/frontend/source 健康。

### shence-frontend-service -> model-tboard -> plain user semantics

- 冻结时间：2026-06-24 Asia/Shanghai。
- 拍板人 / 确认来源：用户确认当前版本不错，并授权 Codex 判断模型四链路是否可拍板；Codex 基于前端合同测试、compact 只读接口、Playwright DOM 和截图验收判定可以拍板，用户随后明确回复“可以  继续”确认冻结。
- 锁定范围：`#/model-tboard` 普通用户语义层；主列表继续保持 10 列：股票、模型分、Day1、Day2、监测时间、当前判断、接力强度、关键依据、风险结论、更新；页面按 owner `model_score` 降序展示，`model_score=0` 只表示 owner 明确给出的硬失败综合分，缺关键事实时仍保持空态，不用 0 补齐；页面主体显示“T 字接力观察台”标题条和首日/次日/停止原因的普通用户口径。
- 锁定文案：触发后开板、破板或封板维护失败显示为“封板失败 / 已开板，停止观察 / 触发后开板，封板没守住 / 封板没守住，次日退出风险高”；卖盘主动砸向买盘显示为“卖压占优 / 卖压占优，停止观察 / 接近涨停，卖盘往下砸 / 卖盘往下砸，买入确认失败”；Day2 滚动监测未接近涨停显示为“未触发 / 未触发，停止观察 / 5 分钟监测未接近涨停 / 没有接近涨停，接力不足”；买盘主动扫掉卖盘且触发接力显示为“已触发，继续看封板 / 接近涨停，买盘扫掉卖盘 / 已触发，重点看收盘前能否封住”。
- 允许的只读验收：访问 `#/model-tboard`、读取 `/readyz`、读取 `/api/model-list/tboard`、读取 owner `/t-board-relay/observation-board`、运行前端合同测试、运行 `node --check`、Playwright DOM 可见文本检查和截图。
- 禁止修改项：未经解锁不得恢复“观察阶段”“Day3”“下一步”“数据提示”列，不得展示 `ASK` / `BID`、`source_gap:*`、repository/schema/provider/raw/internal 文本，不得恢复“可买入观察”“接力机会提示仅作观察”“不自动下单”等空泛提示，不得让前端触发模型评分、scheduler dispatch、source fetch、provider 请求、raw 读取、official signal、交易、买点、outcome 或学习权重写入。
- 解锁条件：用户明确批准 `shence-frontend-service -> model-tboard -> plain user semantics` 解锁并说明目标；若需要改变 owner `observation-board` 字段、状态机、评分或纳入规则，必须另行解锁 `t-board-relay-service`。
- 回滚方式：回退本冻结对象对应的前端语义翻译、测试和文档变更，重新运行前端合同测试、JS 语法检查和 Playwright 页面验收；不清库、不重启 `source-data-service`，也不修改模型四 owner 数据。
- 验证清单：`python -m pytest -q services/shence-frontend-service/tests` 通过；`python -m compileall -q services/shence-frontend-service/src services/shence-frontend-service/tests` 通过；`node --check services/shence-frontend-service/public/app.js` 通过；`GET /api/model-list/tboard?limit=20` 返回 `read_only=true` 且只包含 Day1 合格观察对象；浏览器 DOM 显示“T 字接力观察台”标题条、10 个核心列和真实观察行，且不含“数据提示”“下一步”“观察阶段”“ASK”“BID”“source_gap:*”“不自动下单”“接力机会提示仅作观察”“可买入观察”；开板失败风险使用“次日退出风险高”白话表达。

### shence-frontend-service -> model-tboard -> terminal default visibility

- 冻结对象：`shence-frontend-service -> model-tboard -> terminal default visibility`。
- 冻结时间：2026-07-02 Asia/Shanghai。
- 拍板人 / 确认来源：用户在交付报告后明确回复“拍板”；此前用户指出“第二天或者第三天不符合就应该下架，而不是一直留着待观察”，并回复“继续”批准继续修复和发布验证。
- 锁定范围：`GET /api/model-list/tboard` 默认不主动返回 `observation_status=stopped` 的终止对象；`observation_status=data_wait` 仅在 Day2 09:30-10:30 验证窗口未过时保留，一旦窗口已过仍没有有效 Day2 监测事实，也从普通用户主列表下架。Day2 判断优先使用 owner 返回的 `day2_trade_date`，缺失时按 `day1_trade_date` 推导下一个工作日并周末顺延；该口径只影响普通用户默认列表和浏览器兜底过滤，不删除 owner 事实。
- 当前冻结证据：2026-07-02 前端 8030 重启后 `/readyz=ready`；登录读取默认 `/api/model-list/tboard?limit=20` 返回 0 条普通用户可见观察对象；读取 `/api/model-list/tboard?limit=20&include_stale_stopped=true` 返回 5 条审计对象，其中 `000823.SZ` 为 `observation_status=data_wait`、`model_score=NULL`，当前判断为 Day2 监测数据未落库、暂不继续观察，风险结论为真实抓数时间未推进、不能按继续观察展示；scheduler `/readyz=ready`，data-inspector `/readyz=ready`，`source-data-service` 未重启。
- 允许的只读验收：读取 `/api/model-list/tboard`、读取 `/api/model-list/tboard?include_stale_stopped=true`、读取 owner `/t-board-relay/observation-board`、访问 `#/model-tboard`、检查 frontend `/readyz`、运行前端合同测试、Python 编译检查和 JS 语法检查。
- 禁止修改项：未经解锁不得改变终止态默认下架、Day2 窗口错过后的 `data_wait` 默认下架、`include_stale_stopped=true` 只读排查参数、owner 事实保留边界或前端只读边界；不得删除、改写、截断 `t-board-relay-service` owner `observation-board`、repository、monitor snapshot 或 append-only 审计事实；不得让前端触发模型评分、scheduler dispatch、source fetch、provider 请求、raw 读取、official signal、交易、买点、outcome 或学习权重写入。
- 解锁条件：用户明确批准 `shence-frontend-service -> model-tboard -> terminal default visibility` 解锁；若要改变 owner `observation-board` 字段或状态机、删除历史失效事实、调整 scheduler/source 逻辑，必须另行解锁对应服务。
- 回滚方式：回退本对象对应的 compact 默认过滤、页面兜底过滤、测试和文档变更，重新运行前端合同测试、Python 编译检查、JS 语法检查，并重启前端服务；不清库、不重启 `source-data-service`，也不修改模型四 owner 数据。
- 验证清单：`python -m pytest -q services/shence-frontend-service/tests/test_frontend_contract.py` 通过；`python -m compileall -q services/shence-frontend-service/src services/shence-frontend-service/tests` 通过；`node --check services/shence-frontend-service/public/app.js` 通过；`git diff --check` 通过；前端 `8030` 重启后 `/readyz` 为 ready；默认 `/api/model-list/tboard?limit=20` 不返回已终止或 Day2 窗口错过的 `data_wait` 对象；`include_stale_stopped=true` 可显式排查历史失效和缺口对象；`source-data-service` 未重启。

### shence-frontend-service -> model-tboard -> Day1 summary dedupe

- 冻结时间：2026-06-26 Asia/Shanghai。
- 拍板人 / 确认来源：用户确认 Codex 交付报告，批准将模型四 Day1 汇总去重口径拍板冻结。
- 锁定范围：`GET /api/model-list/tboard` 的 `day1_scan_summary` 只读汇总口径；前端服务只读取 owner `/t-board-relay/day1/candidates` 的 append-only 候选行，不返回明细给浏览器。汇总必须先取最新 `trade_date`，再在该交易日内按 `canonical_symbol`、`symbol`、`stock.symbol` 或 `instrument_id` 识别同一股票，保留 `updated_at`、`created_at`、`as_of_time_utc` 或列表顺序最新的一行后，再统计 `scanned_count`、`qualified_count`、`rejected_count`、`data_blocked_count`、`open_on_limit_count`、`reason_counts` 和 `updated_at`。
- 当前运行事实：重启本地前端 `8030` 后，登录读取 `/api/model-list/tboard?limit=10` 返回 `read_only=true`；`day1_scan_summary.data.trade_date=2026-06-26`、`scanned_count=21`、`qualified_count=1`、`rejected_count=20`、`data_blocked_count=0`；`observation_board.data.items[0]` 为 `000823.SZ 超声电子`，`model_score=48.0`，状态 `continue_watch`，结论“等待Day2开盘后滚动观察”。同一响应不含 `request_payload`、`result_payload`、`game_hypothesis_payload`、`evidence_json` 或 `related_payload`。
- 允许的只读验收：读取 `/api/model-list/tboard`、读取 `/api/model-list/tboard?include_stale_stopped=true`、读取 owner `/t-board-relay/day1/candidates` 和 `/t-board-relay/observation-board` 做事实对账、访问 `#/model-tboard`、检查 frontend `/readyz`、运行前端合同测试、Python 编译检查、JS 语法检查和 compact payload 剥离检查。
- 禁止修改项：未经解锁不得改变 Day1 汇总的最新交易日选择、股票去重 key、最新行选择顺序、计数字段含义、审计 payload 剥离、普通用户不看 rejected/data_blocked 明细的边界或前端只读边界；不得删除、改写、截断 owner `decision_t_relay.*` append-only 候选事实；不得把前端汇总下沉为模型四 owner 状态、scheduler/source 动作、数据库清理、模型评分修改、official signal、交易、买点、outcome 或学习权重写入。
- 解锁条件：用户明确批准 `shence-frontend-service -> model-tboard -> Day1 summary dedupe` 解锁；若要改变 owner `day1/candidates` 合同、Day1 合格判定、schema、scheduler/source 取数或模型四状态机，必须另行解锁对应服务。
- 回滚方式：回退本对象对应的前端 compact helper、合同测试、README 和 DATA_ASSETS 变更，重新运行前端合同测试、Python 编译检查、JS 语法检查，并只重启前端服务；不清库、不重启 `source-data-service`，也不修改模型四 owner 数据。
- 验证清单：`PYTHONPATH=services/shence-frontend-service/src python -m pytest -q services/shence-frontend-service/tests/test_frontend_contract.py` 通过；`python -m compileall -q services/shence-frontend-service/src services/shence-frontend-service/tests` 通过；`node --check services/shence-frontend-service/public/app.js` 通过；`git diff --check` 通过；重启后 scheduler/data-inspector/frontend `/readyz` 均 ready；`/api/model-list/tboard?limit=10` 返回 Day1 汇总 `21/1/20/0`，首条观察对象为 `000823.SZ 超声电子`；`source-data-service` 未重启。

### shence-frontend-service -> model-tboard -> mobile plain-user cards

- 冻结对象：`shence-frontend-service -> model-tboard -> mobile plain-user cards`。
- 冻结时间：2026-06-26 Asia/Shanghai。
- 拍板人 / 确认来源：用户在本轮交付报告后回复“确认”，批准将模型四移动端普通用户字段卡片展示拍板冻结。
- 锁定范围：`#/model-tboard` 手机视口展示层；模型四仍只读消费 `/api/model-list/tboard` compact 响应和 owner `observation-board` 投影，仍保留 10 个事实字段：股票、模型分、Day1、Day2、监测时间、当前判断、接力强度、关键依据、风险结论、更新。桌面保持 10 列表格；手机隐藏重复表头，把每条真实观察行展示为只读字段卡片，字段标签来自同一列合同，便于初级用户不用横向滑动即可读到当前判断、关键依据和风险结论。
- 当前验收事实：登录后 compact API 返回 `contract_kind=shence_tboard_model_list_compact_v1`、`read_only=true`、`compact_audit_payloads=true`、repository/observation_board 均 `ok=true`，与 owner `/t-board-relay/observation-board?limit=20` 均为 5 条真实观察对象；今日 Day1 汇总为 `trade_date=2026-06-26`、`scanned_count=21`、`qualified_count=1`、`rejected_count=20`、`data_blocked_count=0`；手机 DOM 中 5 条观察对象均为字段卡片，第一行 `000823.SZ 超声电子` 继续观察，`600172.SH 黄河旋风` 风险结论显示“封板没守住，次日退出风险高”，页面不显示 owner 原始 `Day3退出风险` 文案；桌面截图 `services/shence-frontend-service/playwright-artifacts/model-tboard-20260626-desktop-validation.png` 和手机截图 `services/shence-frontend-service/playwright-artifacts/model-tboard-20260626-mobile-validation.png` 已留存。
- 允许的只读验收：访问 `#/model-tboard`，读取 `/readyz`、`/api/model-list/tboard`、owner `/t-board-relay/observation-board`，运行前端合同测试、Python 编译检查、JS 语法检查，执行 Playwright 桌面 / 手机 DOM 与截图检查。
- 禁止修改项：未经解锁不得改回手机横向表格为唯一阅读方式，不得删减 10 个事实字段，不得恢复“观察阶段”“Day3”“下一步”“数据提示”列，不得展示 `ASK` / `BID`、`source_gap:*`、repository/schema/provider/raw/internal 文本，不得恢复“可买入观察”“接力机会提示仅作观察”“不自动下单”等空泛提示，不得让前端触发模型评分、scheduler dispatch、source fetch、provider 请求、raw 读取、official signal、交易、买点、outcome 或学习权重写入。
- 解锁条件：用户明确批准 `shence-frontend-service -> model-tboard -> mobile plain-user cards` 解锁并说明目标；若需要改变 owner `observation-board` 字段、模型分排序、Day1 汇总口径、状态机、schema、scheduler/source 取数或模型四事实语义，必须另行解锁对应服务。
- 回滚方式：回退本对象对应的移动端卡片 CSS、合同测试和 README / DATA_ASSETS 冻结记录，重新运行前端合同测试、Python 编译检查、JS 语法检查和 Playwright 页面验收；不清库、不重启 `source-data-service`，也不修改模型四 owner 数据。
- 验证清单：`node --check services/shence-frontend-service/public/app.js` 通过；`PYTHONPATH=services/shence-frontend-service/src python -m pytest -q services/shence-frontend-service/tests/test_frontend_contract.py` 通过；`python -m compileall -q services/shence-frontend-service/src services/shence-frontend-service/tests` 通过；尾随空白检查通过；Playwright 桌面 / 手机 DOM 验收通过，手机状态为 `stickyHeaderDisplay=none`、`rowDisplay=grid`、`cellDisplay=grid`、10 个 `data-label` 完整；frontend、scheduler、data-inspector `/readyz` 均 ready；`source-data-service` 未重启。

## Admin 数据任务看板

`#/admin-ops` 是仅 `admin` 角色可见的只读运维看板。登录态由前端服务签发随机 session token；默认管理员账号来自 `SHENCE_FRONTEND_ADMIN_USERNAME` / `SHENCE_FRONTEND_ADMIN_PASSWORD`，未配置时回退到本地 `admin/admin`。兼容的 `SHENCE_FRONTEND_USERNAME` 账号只有在与管理员账号不同且显式配置时才作为非管理员角色进入，非 `admin` 访问 `/api/admin/daily-board` 与 `/api/admin/task-board` 返回 403。

看板按单个 `trade_date` 作为日生命周期，浏览器每 300 秒只读刷新一次，也允许手动刷新或切换日期。刷新只调用前端服务的 read-only 聚合接口，不触发 `source-data-service` fetch submit、不触发 scheduler dispatch、不调用 provider、不写 source/raw/model/research/outcome/release gate。页面隐藏时暂停本轮自动刷新，登出或切换页面会清理 timer。

Admin main screen is an aggregated daily lifecycle board, not a task detail table. It must show total planned tasks, completed, unfinished, not-yet-due, waiting/running, final data failures, raw-audit warnings, source output, and repairable/non-repairable/pending counts only for failed or missing data. Completed tasks stay as counts; unfinished or failed blocks are the only blocks promoted to the main screen.

Task completion starts from scheduler daily task-store facts but must be reconciled with source daily asset final status. `success` and `source_duplicate_skipped` only mean submitted or deduplicated. If the same `source_table_name` is `final_data_failed=true`, `data_asset_status=failed`, `data_asset_status=coverage_insufficient`, `coverage_insufficient=true`, or has unrecovered build failures in `/source/ops/daily-data-summary`, the frontend must downgrade the matching completed task to `target_fact_missing`, `build_failed`, or `coverage_insufficient`, subtract it from completed, and count it as final data failure. If the source daily fact is still `collecting` / queued / running / waiting, has active or waiting raw jobs, and has no target evidence (`source_row_count=0` and `build_succeeded_count=0`), the matching task must be downgraded to `collecting` or `awaiting_evidence`, subtracted from completed, and counted as unfinished rather than failure. Target evidence excludes `coverage_insufficient`: partial full-A rows do not count as completed evidence. If `/source/ops/daily-data-summary` is unavailable, the task-board must fail closed: set `source_facts_available=false`, keep source output counts as null, downgrade scheduler-completed source tasks to `awaiting_evidence`, and show Chinese `source data temporarily unreadable` wording instead of a completion percentage that relies only on scheduler facts. `raw_failure_audit_only=true` or `completed_with_provider_audit` is an audit warning only and must not count as failure; it counts as completed only when non-partial target evidence exists.

Visible UI labels must remain Chinese business labels. Internal audit states map as follows: `not_due` means not-yet-due collection time, `awaiting_dispatch` means waiting submit, `collecting` means waiting for raw/source output rather than proof of active worker processing, `target_fact_missing` means target data not produced, `coverage_insufficient` means full-A coverage is below the required threshold and must display as ??????, `data_failed` means final data output failed, `build_failed` means build failed, `awaiting_data_result` means waiting data result, `completed` means completed, and `no_known_gap` means produced. The default screen must not expose raw English status codes.

`GET /api/admin/task-board` reads scheduler `/scheduler/task-store/daily-summary` plus source `/source/ops/daily-data-summary`. Its `summary` must expose daily aggregate fields including `total_tasks`, `completed_tasks`, `unfinished_tasks`, `waiting_collection_tasks`, `collecting_tasks`, `awaiting_dispatch_tasks`, `execution_failed_tasks`, `data_failed_jobs`, `data_failed_assets`, `raw_audit_warning_table_count`, `failed_tasks`, repairable/non-repairable/pending failed counts, `latest_task_update_at`, and `latest_data_update_at`. Admin dashboard backend reads use `SHENCE_FRONTEND_ADMIN_DASHBOARD_TIMEOUT_SECONDS` when set, otherwise a 90 second default, because source daily aggregation can exceed the generic proxy timeout while large repair queues are active. The task-board endpoint intentionally uses a lightweight read set and does not call source build result, build trigger, storage policy, readiness, registry, materialized schedule, scheduler runtime, or inspection detail endpoints. The browser must load `/api/admin/task-board` as the primary decision payload; `/api/admin/daily-board` is optional detail and may degrade to an empty read-only detail shell when it times out, so the main completion board remains visible. Admin loading copy must say it is reading the data/task board and must not reuse research/ambush valley copy. The main screen consumes these aggregate fields and Chinese labels only. Backend timestamps with explicit offsets (`Z`, `+00:00`, `+08:00`) are display-only converted by the browser to `Asia/Shanghai` as `YYYY-MM-DD HH:mm:ss`; the board must not show UTC offset strings or invent current time when a backend timestamp is missing.

2026-07-15 admin ops browser fix: `#/admin-ops` loading and coverage copy must use admin data/task board wording only; coverage alert must not reference model-page refresh state, and model-page refresh status must keep using its own `refreshState`. Manual refresh binds only to `reload-admin-board`; date changes only update the admin board trade date and re-read `/api/admin/task-board`; `/api/admin/daily-board` is read later only when audit details are expanded.
2026-07-15 task-count accuracy fix: admin task summary fields ending in `_tasks` must be counted from scheduler task rows after source evidence overlay only. Source `build_failed_results`, raw failure counts, and other source audit result counts are data-asset evidence and may be exposed as separate audit counters, but must not inflate planned/completed/unfinished/failed task counts. The browser separates `awaiting_dispatch_tasks` as “待提交抓取” and `awaiting_evidence_tasks` as “等待数据结果”.
2026-07-15 admin render failure fix: `#/admin-ops` must render successfully with real `/api/admin/task-board` and `/api/admin/daily-board` payloads. Admin upstream badges read `upstream_status.*.status`; asset/task reason helpers read only admin `asset.status` / `task.status` and must not reference model fields such as `observation_status`, `batchStatus`, `continue_watch`, or undefined local variables. Static `app.js` version is `20260715-admin-board-render-fix-v2` to force browsers off stale scripts.
2026-07-15 admin progress clarity: `/api/admin/task-board` exposes scheduler ledger progress separately from final source-data completion. The main board must show scheduler processed counts, final completed counts, raw waiting/active counts, and source output counts so `0%` final completion is not mistaken for no scheduler activity. Scheduler `success/source_duplicate_skipped` remains process evidence only; final completion still requires target source output.
2026-07-15 admin label clarity: admin upstream badges must map `source_daily_summary` to “今日数据产出”, `scheduler_daily_summary` to “调度账本”, and missing target-day `inspection_latest` to “今日验收 · 未生成” instead of “读取失败”. Main board status `collecting` must display as “等待抓取/产出” or “等待产出”, because real-time worker activity is only proven by raw active counts; raw waiting/source pending states must not be labelled as “执行中”.
2026-07-20 admin task accuracy fix: `collecting` is assigned to a scheduler-processed row only when that row reports a live source submission (`source_submitted_job_count>0` or `source_fetch_status` in queued/running states) and source daily summary still has open raw work. If the table has target evidence (`source_row_count>0` or `build_succeeded_count>0`) or the table is explicitly completed, the row remains completed even if other raw jobs for the same table are waiting. If there is no completion evidence and the row-level scheduler lifecycle has expired (`orchestration_context.lifecycle_expires_at*`, otherwise schedule-group fallback), the row becomes `expired_closed`; it is unfinished but not active waiting and not data failure. If source daily summary is unreadable, the row fails closed to `awaiting_evidence` instead of inferring expiry. Main-screen `raw_waiting_jobs/raw_active_jobs` count only rows still in active waiting/result states; source-wide residual totals are retained separately as `raw_waiting_jobs_total/raw_active_jobs_total` for audit. This prevents a few remaining same-table raw jobs from turning hundreds of expired minute tasks into active unfinished work.
2026-07-15 admin performance fix: `#/admin-ops` first screen reads only `/api/admin/task-board`; `/api/admin/daily-board` is loaded only when the admin expands audit/detail sections. Browser requests are de-duplicated by `trade_date + endpoint` with a 10 second in-flight/short cache, manual refresh bypasses stale cache but still reuses an active identical request, and the backend admin aggregator also coalesces identical read-only payload fetches for 10 seconds via `SHENCE_FRONTEND_ADMIN_DASHBOARD_CACHE_TTL_SECONDS`. This cache must never trigger source fetch, scheduler dispatch, provider calls, or fact mutation.

`GET /api/admin/daily-board` aggregates source requirements, freshness SLA, readiness matrix, repair routes, queue summary, daily data summary, build results, build triggers, storage policies, scheduler registry/materialized tasks/task-store summary, and data-inspector latest core closure run/gaps. Source daily summary is authoritative for final data asset state: only `final_data_failed=true`, `data_asset_status=failed`, or build failure is final failure; `raw_failure_audit_only=true` is audit warning only; rows or successful build mean produced; future schedule means not-yet-due; otherwise the board must say waiting data result.

数据资产分为三类：`repairable_after_expiry` 表示存在正规 repair route、备源 provider 或 source build 重建路径；`non_repairable_after_window` 表示实时盘口快照、分钟线、逐笔成交、竞价快照、同花顺付费次日概率等窗口事实，错过窗口后不能用事后数据冒充当时事实；`contract_pending` 表示当前只读合同未暴露可审计补全路线，缺失时必须保留缺口。上述英文枚举只属于接口审计字段，普通主屏展示必须翻译为“可补”“不可补”“待确认”。

Main data blocks only show unfinished or failed blocks such as foundation, price/limit, intraday, paid probability, flow/board, index environment, and news. Each card shows planned, completed, unfinished, not-yet-due, waiting submit, running, failed, and output counts. Repairability tags only appear for failed or missing target data. Full asset and gap details stay behind the audit details disclosure.

前端服务读取后端时优先使用环境变量配置的服务地址，同时保留本机 `127.0.0.1` 端口与 Docker service name 候选，以便本地运行的前端服务可以只读访问容器内 source、scheduler 和 data-inspector。上游不可读时只显示中文读取失败或等待数据结果，不用 0、空字符串、当前时间、mock、GPT 推断或前端默认值补事实。source-data-service、scheduler-service 和 data-inspector-service 的运行事实仍归各自服务所有，admin 看板只能读取、聚合和展示。
### shence-frontend-service -> admin-ops -> aggregated daily lifecycle board

- 当前对象：`shence-frontend-service -> admin-ops -> aggregated daily lifecycle board`。
- Current time: 2026-07-13 Asia/Shanghai.
- 确认来源：用户指出旧词“巡检未覆盖 / 未到窗口”难理解、前端尽量不展示英文字段，并确认按日周期任务总览口径执行。
- 当前范围：`#/admin-ops` 首屏日周期任务总览、未完成数据块聚合、失败补救聚合、审计明细默认折叠、300 秒只读刷新和 admin-only 可见边界；本轮只调整前端服务聚合与展示合同，不改变 source / scheduler / data-inspector 的事实生成逻辑。
- Acceptance: the main screen shows planned, completed, unfinished, not-yet-due, waiting submit, running, final data failure, raw-audit warning, source output, and repairable/non-repairable/pending counts. Raw fetch failures that are repaired into final source output are warnings only; final source asset failures must reduce completed task count and increase failed count.
- 允许的只读验收：访问 `#/admin-ops`、读取 `/api/admin/daily-board`、读取 `/api/admin/task-board`、检查 frontend `/readyz`、运行前端合同测试、JS 语法检查、Python 语法检查和页面截图。
- 禁止修改项：未经解锁不得让 admin 看板触发 source fetch、scheduler dispatch、provider 调用、模型评分、release gate、交易、买点、outcome 或学习权重写入；不得用 0、当前时间、mock 或历史验收 run 填补目标日未知事实；不得把任务明细重新铺成默认主屏。
- 回滚方式：回退 admin 聚合视图相关前端渲染、样式、前端服务聚合 helper、合同测试和文档变更，重跑前端合同测试、JS 语法检查、Python 语法检查和页面验收；不清库、不重启 `source-data-service`，不修改 source/scheduler/data-inspector 事实。
- Verification checklist: `/api/admin/daily-board` and `/api/admin/task-board` return `read_only=true`; missing target-day inspection is only an audit hint; task aggregates show planned, completed, unfinished, not-yet-due, waiting submit, running, scheduler failure, target data not produced, build failure, and raw-audit warning; default screen does not expose `inspection_unknown`, `not_due`, or other English state codes.

### admin-ops Task Lifecycle Display

Since 2026-07-20, the admin data task board recognizes both source-level closure (`data_asset_status=expired_closed`, `raw_cancelled_count`, `raw_cancelled_jobs`, `expired_closed_table_count`) and scheduler row lifecycle expiry. When a processed row has no completion evidence and its `orchestration_context.lifecycle_expires_at*` is past, or an older row falls past the schedule-group fallback window, the frontend displays the Chinese expired-closed status. It is counted as unfinished, but it is not counted as active waiting/producing work and not counted as data failure. The overview, reason chips, and data block cards show this count separately.

The expired-closed status only means the old normal daily job is no longer enabled. If data is still missing, a new formal source repair/backfill/fetch job must produce new evidence. The frontend must not infer completion, failure, repairability, or source facts from this state. Source queue residuals from completed or expired tasks are audit evidence only; they must not appear on the main screen as current raw waiting work.

### 2026-07-23 Admin Task Lifecycle Correction

The admin task board treats scheduler `expired_closed` rows and locally derived expired scheduler rows as the same Chinese state: `?????`. Not-enqueued or pending scheduler rows with explicit lifecycle metadata are no longer displayed as active `?????` after the lifecycle expires. Processed rows with real target source evidence stay completed/collecting as appropriate; table-wide residual raw work cannot demote completed rows. For legacy rows without explicit lifecycle metadata, the board only infers expiry from known schedule/table semantics and keeps window-limited rows with open raw work as `??????`.
