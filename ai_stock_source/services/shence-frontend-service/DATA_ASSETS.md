# shence-frontend-service DATA_ASSETS

本文件是 `shence-frontend-service` 的数据资产账本，不替代本目录 `README.md`。

## 服务定位

前端负责只读展示候选输入、四模型列表、研究中心低谷图库和轻量代理。除研究中心低谷图库受控 POST 外，不写模型事实、source/raw、调度、交易、release gate、买点、outcome 或学习权重。

## 读取数据

| 代理 | 后端资产 | 用途 | 边界 |
|---|---|---|---|
| `/api/backend/source/*` | `source.*`、source readiness/preflight | 候选页、候选记忆/潜伏抬头过渡 universe、健康信号 | 只读 |
| `/api/source/ths/paid-probability/*` | source-data-service 付费概率 Cookie 状态、批次状态和受控抓取入口 | 候选页 Cookie 配置、立即抓取、批次状态提示 | 仅允许 cookie/status、cookie、probe、fetch-current-batch、batch-status、deadline-check；不放开通用 source 写代理 |
| `/api/model-list/hot` | `research-service /research/model-list/hot`、`decision_hot.*` 只读投影、`source.stock_master_v1`、`source.daily_bar_v1`、`source.ths_paid_limit_up_probability_v1` 展示上下文、`hot_model_data_readiness_v1` 准备度字段 | 热点模型页；只展示已落库模型结果，按模型分降序，并展示准备度、缺失分、P0 阻断和维度明细 | 只读；不回退 source universe，不触发 owner，不计算分数，不补买点/概率/行情；保留准备度合同字段，剥离审计大字段 |
| `/api/backend/tboard/*` | `decision_t_relay.*`、`research_t_relay.*` owner GET | 模型四 owner 只读事实 | 只读 |
| `/api/model-list/tboard` | `t-board-relay-service /t-board-relay/observation-board`、repository status 和 `/t-board-relay/day1/candidates` | 模型四 T 字接力观察台；普通用户列为股票、模型分、Day1、Day2、监测时间、当前判断、接力强度、关键依据、风险结论、更新；顶部显示最近 Day1 扫描汇总 | 只读；只消费 Day1 合格观察对象和 owner `model_score`；Day1 candidates 只在最新交易日内按股票去重并保留最新行后生成汇总计数和白话原因，不返回 rejected/data_blocked 明细；按模型分降序展示；`更新` 同时展示 `last_model_output_at/model_evaluated_at` 对应的最后一次模型产出时间，以及 `latest_data_fetch_at/last_data_captured_at` 对应的最新真实抓取/阶段事实时间；`latest_projection_snapshot_at` 只作审计，不冒充抓取；剥离审计大字段，不改后端事实；普通用户列表不展示 `current_stage`、`day3_trade_date`、`next_observation`、`data_notice`、`data_gap_labels`、`ASK` 或 `BID` |
| `/api/backend/data-inspector/*` | 巡检摘要 | 健康/缺口展示 | 只读 |
| `/api/backend/scheduler/*` | scheduler status/sample | 调度状态展示 | 只读 |
| `/api/research/*` | `research_ambush.*` | 低谷图库研究资产写入 | 只允许研究中心合同 POST |

## 写入数据

| 写入 | 表 | 边界 |
|---|---|---|
| 付费概率 Cookie 表单 | `governance.ths_paid_probability_cookie_v1` | 只通过 source-data-service 受控 API 替换运行库 Cookie；前端不保存 Cookie，不写 raw/source/model 事实 |
| 低谷图库 POST | `research_ambush.*` | 研究资产，不是模型生产事实 |

候选输入页不再手动写入同花顺概率，不生成本地随机概率测试 payload，不显示“已提交生产”。页面只读展示 `source.ths_paid_limit_up_probability_v1`；数据库已有留存 Cookie 且未被真实接口探测判定失败时，页面只展示脱敏状态并隐藏编辑入口。Cookie 缺失或真实探测失败后才展示配置表单，提交后会触发 source-data-service 受控抓取当前批次。

## 调度频率

热点模型页无后台调度；浏览器首屏只读调用 `/api/model-list/hot?limit=20`，前端服务再只读调用 `research-service /research/model-list/hot`。20 行只是普通用户首屏读取规模，用于保证准备度逐行真实验证后页面可及时展示，不改变后端接口 `limit` 参数能力，也不截断或删除任何已落库模型事实；该首屏真实准备度链路使用 24.0 秒浏览器预算和 30.0 秒服务端代理预算，避免 20 行逐条准备度验证在 12 秒边界误判为空态。该路径只读取已落库 `decision_hot.*` 投影、必要 source 展示上下文和 `hot_model_data_readiness_v1` 准备度合同，不触发 owner、scheduler、source fetch 或 provider 请求；无结果时显示空态/缺口，不回退到 source universe。准备度 KPI、准备度列和维度矩阵只消费后端返回的 `readiness_score_pct`、`missing_points`、`blocked_points`、`readiness_state`、`top_missing_dimension`、`readiness_gap_codes`、`readiness_dimensions` 和 `readiness_summary`；KPI 固定展示数据准备度、P0 阻断、已有模型分、概率覆盖和数据缺口，维度矩阵展示优先级、权重、覆盖和缺失分；字段覆盖矩阵的事实来源只展示中文业务来源，不展示服务名、schema/table、`source_gap:*` 原码、raw/provider/internal 文本或接口路径；没有真实行或没有准备度数值时显示“暂无”或“待评估”，不得把空态显示成 0% 或 100%。

前端无后台调度。浏览器请求使用短超时，只读拉取当前页面所需数据；失败时显示中文空态，不补事实。模型四列表通过 `/api/model-list/tboard` 读取 owner `observation-board`、repository status 和 Day1 candidates；Day1 candidates 只在前端服务内按最新 `trade_date` 聚合，并在该交易日内按 `canonical_symbol`、`symbol`、`stock.symbol` 或 `instrument_id` 去重，保留 `updated_at` / `created_at` 最新行后统计最近 Day1 扫描数、严格 Day1 合格数、未通过主因和 Day1 更新时间，不把候选明细或审计字段返回浏览器；同一汇总会从 owner `observation-board` 压缩结果提取 `last_model_output_at/model_evaluated_at`、`latest_data_fetch_at/last_data_captured_at` 和只读审计用 `latest_projection_snapshot_at`。compact 响应在前端服务内剥离 `request_payload`、`result_payload`、`game_hypothesis_payload`、`evidence_json`、`related_payload` 后再返回浏览器，避免审计 / 证据大字段影响页面读取。模型四 `model_score` 只来自 owner 投影，页面按分数由高到低展示，缺关键事实时保持空态，不补 0、不自行评分。模型四 `day2_trigger_time` 仅展示 Day2 开盘后五分钟滚动监测中首次接近条件的检查时间，不代表前端写入交易、买点或 official signal。模型四 `更新` 同时展示 30 分钟模型结果时间 `last_model_output_at/model_evaluated_at` 和真实阶段事实时间 `latest_data_fetch_at/last_data_captured_at`；`latest_projection_snapshot_at` 只作为投影审计时间，不进入普通用户抓取时间。普通用户列表不展示“观察阶段”“Day3”“下一步”“数据提示”列；缺口只允许通过 owner 已投影的当前判断、关键依据或风险结论白话呈现。用户停留在 `#/model-tboard` 且已登录时，浏览器按 `TBOARD_AUTO_REFRESH_MS=60000` 每 60 秒重新读取 `/api/model-list/tboard?limit=100`；页面隐藏、切走路由或登出时清理 timer，这只是只读刷新节奏，不是 scheduler/source/model 写入调度。模型四已有可见数据时，自动刷新只 patch 表格 body、Day1 扫描汇总、错误提示和不占布局的刷新角标，不重建页面壳、筛选区或固定表头，不重置横向滚动，也不重复绑定表格 chrome；后台失败时保留上次可见内容。

候选页付费概率依赖 scheduler/source-data-service 调度：15:20、16:05、18:00、20:30 抓取当前候选批次；09:01 执行 deadline guard。前端只展示后端批次状态，不自行放弃候选批次；未到下一交易日 09:00 前只显示阻断/等待/部分入库。

## 禁止事项

- 不直接访问 provider。
- 不直接读 raw。
- 不把后端错误或空态改成 ready/passed。
- 不显示程序字段名、raw JSON、schema 名作为操作员事实。
- 不保存或回显同花顺 Cookie 明文；除受控 `/api/source/ths/paid-probability/*` 外不允许前端触发 source 写操作。

## 模型四语义翻译边界

`/api/model-list/tboard` 仍是模型四前端唯一普通用户列表入口，数据资产来自 owner `observation-board` 和 repository status。默认 compact 响应不主动返回 `observation_status=stopped` 的终止对象；`observation_status=data_wait` 仅在 Day2 09:30-10:30 验证窗口未过时保留，一旦窗口已过仍没有有效 Day2 监测事实，也从普通用户主列表下架。Day2 判断优先使用 owner 返回的 `day2_trade_date`，缺失时按 `day1_trade_date` 推导下一个工作日并周末顺延；该口径只用于前端默认可见性，不补交易日事实。该过滤只影响普通用户默认列表，不删除、不改写、不截断 owner `decision_t_relay.*` 或 monitor snapshot 事实；排查历史失效 / 缺口样本可显式读取 `GET /api/model-list/tboard?include_stale_stopped=true`。前端不写入 `decision_t_relay.*`、`research_t_relay.*`、source/raw、scheduler、release gate、交易、买点、outcome 或学习权重。

模型四页面允许把 owner 已返回的终止态和关键依据翻译成更直白的展示词：封板维护失败展示为“封板失败 / 已开板，停止观察”，卖压占优展示为“卖压占优 / 卖盘往下砸，买入确认失败”，滚动监测未接近涨停展示为“未触发 / 5 分钟监测未接近涨停”，买盘主动扫掉卖盘展示为“已触发，继续看封板 / 接近涨停，买盘扫掉卖盘”。该翻译只影响浏览器展示和前端排序阅读体验，不修改 `model_score`、`score_state`、`current_conclusion`、`relay_strength_label`、`key_reason`、`risk_tip` 的后端事实来源。

`model_score=0` 是 owner 明确给出的硬失败综合分，前端可以展示并按分数排序；缺关键事实时必须保持 `model_score=NULL` 或空态，不得补 0。风险结论必须来自 owner 已投影的盘口方向、成交强度、封板维护、Day3 去留或事实缺口结论，不展示空泛免责提示。

## 数据资产冻结记录

### shence-frontend-service -> model-hot -> readonly decision-hot list

- 冻结时间：2026-06-25 Asia/Shanghai。
- 拍板人 / 确认来源：用户批准热点候选/热点模型链路精修，要求打通真实模型输出到前端只读展示。
- 锁定范围：模型一前端只读读取 `/api/model-list/hot`，该 compact 入口代理 `research-service /research/model-list/hot` 并消费 `decision_hot.*` 已落库模型结果；同花顺概率、股票名和同日行情仅作为展示上下文，只读来自后端投影；Cookie 状态和批次状态仍只通过 `/api/source/ths/paid-probability/*` 受控代理展示。
- 当前运行事实：`#/model-hot` 不再从 `source.limit_event_v1`、固定旧日期或前端 source universe 拼热点模型行；无已落库模型结果、缺概率、缺行情、缺买点、缺评估基准价或缺验证时，页面显示空态/中文缺口，不补 0、不显示模拟分数、不把 source 候选冒充为模型产出。
- 允许的只读验收：读取模型一页面、`/api/model-list/hot`、`research-service /research/model-list/hot`、hot readyz/healthz、付费概率 cookie/status 与 batch-status、运行前端合同测试、截图和可见文本检查。
- 禁止修改项：未经解锁不得新增 provider/raw 读取，不得让模型一前端写 source、decision_hot、scheduler、release gate、买点、outcome、交易或学习权重；不得恢复 source-universe 伪模型行、手动概率输入、随机概率、旧样例数据或前端推断补值。
- 解锁条件：用户明确批准本冻结对象解锁；若需要改变 research-service 热点投影、模型 owner 逻辑、source 付费概率合同或调整 scheduler/source 调度，必须另行解锁对应服务。
- 回滚方式：回退模型一页面读取和展示合同相关变更，恢复上一版只读展示口径；回滚后重新验证页面不反写后端、不显示模拟数据。
- 验证清单：`python -m pytest -q services/shence-frontend-service/tests/test_frontend_contract.py`；`GET /api/model-list/hot` 返回 `read_only=true` 且不含审计 payload；`#/model-hot` 显示真实只读行或中文空态；可见文本不含 `source_gap:*`、接口路径、schema/table/raw/provider 程序文本；相关后端服务 ready。

### shence-frontend-service -> model-hot -> data readiness display

- 冻结时间：2026-06-27 Asia/Shanghai。
- 拍板人 / 确认来源：用户明确回复“拍板”，并要求“继续完成拍板”。
- 数据资产范围：`/api/model-list/hot?limit=20` 只读代理 `research-service /research/model-list/hot`，返回浏览器前剥离审计 payload；`#/model-hot` 只消费 `hot_model.data.items`、`readiness_summary` 和 `readiness_dimensions`。页面展示顶部准备度 KPI、行级准备度列和准备度维度矩阵；KPI 包含数据准备度、P0 阻断、已有模型分、概率覆盖和数据缺口，维度矩阵展示优先级、权重、覆盖和缺失分。
- 当前验收事实：登录后 compact API 返回 `read_only=true`、`compact_audit_payloads=true`、`hot_model_data_readiness_v1`、总权重 `100`、13 个维度、20 条真实行、平均准备度 `69.0%`、平均缺 `31.0` 分、P0 阻断 `20`；首行 `600367.SH` 准备度 `69`、状态 `blocked`、缺 `31` 分、最大缺口 `open_5m_reference_path`。Playwright DOM 验收显示 20 行真实列表、13 列、数据准备度 KPI、准备度维度矩阵、字段覆盖矩阵、权重、覆盖和缺失分；可见文本不含 `source_gap:*`、接口路径、服务名、schema/table、`decision_hot`、raw、provider、repository 或审计 payload。
- 数据边界：前端只读展示，不写 `decision_hot.*`、source/raw、scheduler、release gate、交易、买点、outcome 或学习权重；不调用 provider，不触发 source fetch，不计算模型分、不生成买点、不改 release gate。无真实行或无准备度数值时显示“暂无”或“待评估”，不得把空态显示成 0% 或 100%，不得把缺失概率、缺失买点、缺失验证或缺失维度补成 0/mock/示例 payload/前端推断。
- 允许的只读验收：访问 `#/model-hot`、读取 `/api/model-list/hot?limit=20`、读取 `research-service /research/model-list/hot?limit=20`、frontend `/readyz`、运行前端合同测试、Python 编译检查、JS 语法检查和 Playwright DOM/截图检查。
- 禁止修改项：未经解锁不得改变准备度 KPI、维度矩阵、默认 20 行首屏读取、24.0 秒浏览器预算、30.0 秒服务端代理预算、compact 字段剥离、空态显示或前端只读边界；不得将准备度展示变成后端事实写入、source/scheduler 动作、模型评分修改或数据库清理。
- 解锁条件：用户明确批准本冻结对象解锁；若要改变 research-service 准备度维度/权重/P0 语义、source/scheduler/owner 模型逻辑或付费概率合同，必须另行解锁对应服务。
- 回滚方式：回退本对象对应的前端展示、代理超时、合同测试和文档变更，重新运行前端合同测试、Python 编译检查、JS 语法检查和 Playwright 页面验收；不清库、不重启 `source-data-service`，也不修改 `decision_hot.*` 或模型 owner 数据。
- 验证清单：前端合同测试通过；Python 编译检查通过；JS 语法检查通过；`git diff --check` 通过；frontend/research/hot owner/scheduler/data-inspector/source 健康；`#/model-hot` 可见准备度 KPI、P0 阻断、20 行真实列表、准备度维度矩阵、字段覆盖矩阵和缺失分，且可见文本不含内部服务、schema/table、接口路径、raw/provider/repository 或审计 payload。

### shence-frontend-service -> model-tboard -> observation board readonly list

- 冻结时间：2026-06-21 Asia/Shanghai。
- 拍板人 / 确认来源：用户确认模型四前端后端整改任务书并要求普通用户观察台口径；本轮按确认范围解锁并完成整改。
- 锁定范围：模型四前端只读读取 `t-board-relay-service /t-board-relay/observation-board`；`/api/model-list/tboard` compact 聚合；剥离 `request_payload`、`result_payload`、`game_hypothesis_payload`、`evidence_json`、`related_payload` 后返回浏览器；页面仅展示 Day1 合格观察对象和 10 个核心列：股票、模型分、Day1、Day2、监测时间、当前判断、接力强度、关键依据、风险结论、更新；按 owner `model_score` 降序展示；不展示“观察阶段”“Day3”“下一步”“数据提示”列。
- 允许的只读验收：读取 `/api/model-list/tboard`、读取 `/api/backend/tboard/t-board-relay/observation-board`、截图 `#/model-tboard`、检查可见文本、运行前端测试、检查服务 ready。
- 禁止修改项：未经解锁不得新增 provider/raw 读取，不得让模型四前端写 `decision_t_relay.*`、`research_t_relay.*`、source/raw、scheduler、release gate、买点、outcome、交易或学习权重；不得把 Day1 未通过对象放入普通用户观察台；不得把缺失事实补成 0、mock、示例 payload 或前端推断。
- 解锁条件：用户明确批准本冻结对象解锁；若需要改变 owner `observation-board` 返回字段或纳入规则，必须另行解锁 `t-board-relay-service`。
- 回滚方式：回退 `/api/model-list/tboard` 与页面调用改动，恢复解锁前只读列表；回滚后重新验证页面空态、只读边界和中文缺口。
- 验证清单：compact 响应不含审计 / 证据大字段；页面只显示 Day1 合格观察对象；可见文本不含 `source_gap:*`、接口路径、schema/table/raw/provider 程序文本；前端合同测试通过；相关后端服务 ready。

### shence-frontend-service -> candidates -> ths paid probability cookie config

- 冻结时间：2026-06-20。
- 拍板人 / 确认来源：用户要求候选股增加自动抓取同花顺次日概率程序，并补充 Cookie 失效或取不到时下一交易日 09:00 后才放弃该批候选。
- 锁定范围：候选页 Cookie 状态小区域、只读 `source.ths_paid_limit_up_probability_v1` 概率展示、批次状态中文提示、`/api/source/ths/paid-probability/*` 受控代理 allowlist、浏览器 Cookie 剥离、无手动概率输入/无随机测试概率；Cookie 表单仅在缺失或真实探测失败后显示；日线/涨停价/资金流/概率 source 辅助读取超时只进入辅助降级，不得覆盖候选主事实读取和 Cookie 状态。
- 允许的只读验收：打开 `#/candidates`、读取 cookie/status、batch-status、source 概率行、运行前端合同测试、检查页面无旧手填控件或旧测试入口。
- 禁止修改项：未经解锁不得恢复手动概率输入、随机概率测试包、通用 source 写代理、浏览器 Cookie 转发、前端自行放弃批次、前端补概率事实，或因读取超时把已留存 Cookie 显示成未配置/失效。
- 解锁条件：source-data-service 付费概率合同变化、候选服务提交合同变化、用户明确批准调整候选页写边界。
- 回滚方式：回退候选页 Cookie 配置与受控代理，保留 source-data-service 付费概率事实和 Cookie 审计，不清库。
- 验证清单：前端合同测试通过；Cookie 明文不出现在源码/README 响应示例；候选页只读概率来自 source 表；`pending_probe/valid` 显示 Cookie 可用且隐藏编辑入口；下一交易日 09:00 前未显示已放弃。

### shence-frontend-service -> model-tboard -> live readonly observation board

- 冻结时间：2026-06-24 Asia/Shanghai。
- 数据资产范围：`/api/model-list/tboard` 只读聚合 owner `GET /t-board-relay/observation-board`；返回浏览器前剥离 `request_payload`、`result_payload`、`game_hypothesis_payload`、`evidence_json`、`related_payload`；页面只消费 10 个用户列，按 owner `model_score` 降序展示，并按 60 秒只读刷新。默认列表不主动展示 `stopped` 终止对象；`data_wait` 仅在 Day2 09:30-10:30 验证窗口未过时保留，窗口已过仍缺有效 Day2 监测事实时默认下架。历史失效和缺口事实仍保留在 owner 和 append-only 快照中。
- 当前运行事实：compact 响应 `read_only=true`，且 `observation_board.data.items` 为 4 条 Day1 合格对象；`600172.SH` 已随 post-entry monitor 更新为“触发后开板，停止观察”；截图留存在 `services/shence-frontend-service/playwright-artifacts/model-tboard-20260624-final-validation.png`。
- 数据边界：前端不写 `decision_t_relay.*`、`research_t_relay.*`、source/raw、scheduler、release gate、交易、买点、outcome 或学习权重；不把缺口补成 0/mock/示例 payload/前端推断；不直接展示 `ASK` / `BID` 或 `source_gap:*`。
- 更新时间边界：模型四列表“更新”列并列展示 `last_model_output_at/model_evaluated_at`（最后一次 30 分钟模型结果产出时间）和 `latest_data_fetch_at/last_data_captured_at`（最新真实抓取 / 阶段事实时间）。`latest_projection_snapshot_at` 只表示最近 5 分钟投影快照生成时间，用于审计和排查，不得冒充抓取时间。
- 数据缺口语义：owner 返回 `observation_status=data_wait` 时，普通用户列表当前判断必须展示“暂不观察”，接力强度必须展示“数据缺口”；不得展示“等待确认 / 待确认”，避免被理解为仍可继续观察。
- 解锁条件：用户明确批准本子对象解锁；若 owner projection 合同变化，必须另行解锁 `t-board-relay-service`。

### shence-frontend-service -> model-tboard -> snapshot refresh acceptance

- 冻结时间：2026-06-24 Asia/Shanghai。
- 拍板人 / 确认来源：用户授权 Codex 判断模型四链路是否可拍板，并在本轮回复“批准”；Codex 基于登录会话、compact API 和 Playwright DOM 验收判定普通用户可读目标已达成。
- 数据资产范围：`/api/model-list/tboard` 只读聚合 owner repository status 和 `observation-board`，返回浏览器前剥离审计 payload；`#/model-tboard` 只消费 `stock.symbol/name`、owner `model_score`、阶段日期、当前判断、接力强度、关键依据、风险结论和更新时间。更新时间并列展示 owner 最近 30 分钟模型结果时间 `last_model_output_at/model_evaluated_at` 与真实阶段事实时间 `latest_data_fetch_at/last_data_captured_at`；`latest_projection_snapshot_at` 只作 5 分钟投影审计，不得代替抓取时间。
- 当前验收事实：compact API 返回 `read_only=true`、`compact_audit_payloads=true`、4 条 Day1 合格对象、股票名完整、模型分排序 15/12/12/0、更新时间 `2026-06-24 09:50:48`；Playwright DOM 显示 4 行和 10 个核心列，不显示“数据提示”“不自动下单”“接力机会提示仅作观察”。
- 数据边界：前端不写 `decision_t_relay.*`、`research_t_relay.*`、source/raw、scheduler、release gate、交易、买点、outcome 或学习权重；不补股票名、模型分、盘口方向或风险结论；`model_score=0` 仅展示 owner 明确给出的硬失败综合分。
- 只读验收：frontend readyz、登录 session、`/api/model-list/tboard`、owner observation-board、Playwright DOM、前端合同测试。
- 解锁条件：owner `observation-board` 字段、compact 聚合合同、列定义、排序口径、自动刷新语义、股票名来源或用户明确批准解锁。

### shence-frontend-service -> model-tboard -> dual-time update display asset

- 冻结时间：2026-07-01 Asia/Shanghai。
- 拍板人 / 确认来源：用户在模型四双时间修复交付后回复“允许”，批准拍板冻结。
- 数据资产范围：`/api/model-list/tboard` 从 owner `observation-board` 中只读提取三类时间：`last_model_output_at/model_evaluated_at` 为 30 分钟模型结果产出时间，`latest_data_fetch_at/last_data_captured_at` 为真实抓取 / 阶段事实时间，`latest_projection_snapshot_at` 为 5 分钟投影审计时间。浏览器 `#/model-tboard` 的“更新”列只展示前两类为“模型 / 抓取”双时间。
- 当前验收事实：2026-07-01 compact 响应同时返回 `last_model_output_at=2026-07-01T02:32:00+00:00`、`latest_data_fetch_at=2026-06-26T07:53:37.143354+00:00` 和 `latest_projection_snapshot_at=2026-07-01T02:30:00+00:00`；页面不再把 5 分钟投影当作最新抓取或模型产出。
- 数据边界：前端服务不写 `decision_t_relay.*`、`research_t_relay.*`、source/raw、scheduler、release gate、交易、买点、outcome 或学习权重；缺模型产出显示“未产出”，缺真实抓取推进显示“未推进”，不得用当前时间、投影时间、0、空字符串、mock 或 GPT 推断补齐。
- 允许的只读验收：`/api/model-list/tboard`、owner observation-board、frontend `/readyz`、`#/model-tboard` DOM、前端合同测试、Python 编译检查、JS 语法检查。
- 禁止修改项：未经解锁不得合并三类时间，不得删除“模型 / 抓取”双时间，不得把 `latest_projection_snapshot_at` 作为普通用户更新时间，不得让前端触发抓取、调度、模型评分、official signal 或交易事实写入。
- 解锁条件：owner 时间字段合同、research 30 分钟任务、scheduler 频率、前端模型四列合同或用户明确批准解锁。
- 回滚方式：回退本对象后续 compact 时间提取、页面渲染、测试和文档变更，重新执行只读验收；不清库、不重启 `source-data-service`，不修改 owner append-only 数据。
- 验证清单：compact 返回双时间字段；页面更新列显示“模型 / 抓取”；投影时间只用于审计；响应剥离审计 payload；source/scheduler/data-inspector/frontend 健康。

### shence-frontend-service -> model-tboard -> plain user semantics

- 冻结时间：2026-06-24 Asia/Shanghai。
- 拍板人 / 确认来源：用户确认当前版本不错，并授权 Codex 判断模型四链路是否可拍板；Codex 基于前端合同测试、compact 只读接口、Playwright DOM 和截图验收判定可以拍板，用户随后明确回复“可以  继续”确认冻结。
- 数据资产范围：只冻结 `/api/model-list/tboard` 到 `#/model-tboard` 的普通用户语义翻译层；数据事实仍只来自 owner `observation-board` 和 repository status。页面按 owner `model_score` 降序展示，`model_score=0` 表示 owner 明确给出的硬失败综合分；缺关键事实时必须保持空态，不得补 0。页面主体标题条只说明当前是“T 字接力观察台”和首日/次日/停止原因口径，不读取或写入额外事实。
- 锁定文案：封板维护失败展示为“封板失败 / 已开板，停止观察 / 触发后开板，封板没守住 / 封板没守住，次日退出风险高”；卖压占优展示为“卖压占优 / 卖盘往下砸，买入确认失败”；滚动监测未接近涨停展示为“未触发 / 5 分钟监测未接近涨停 / 没有接近涨停，接力不足”；买盘主动扫掉卖盘且触发接力展示为“已触发，继续看封板 / 接近涨停，买盘扫掉卖盘 / 已触发，重点看收盘前能否封住”。
- 允许的只读验收：访问 `#/model-tboard`、读取 `/readyz`、读取 `/api/model-list/tboard`、读取 owner `/t-board-relay/observation-board`、运行前端合同测试、运行 `node --check`、执行 Playwright DOM 可见文本检查和截图。
- 禁止修改项：未经解锁不得恢复“观察阶段”“Day3”“下一步”“数据提示”列，不得展示 `ASK` / `BID`、`source_gap:*`、repository/schema/provider/raw/internal 文本，不得恢复“可买入观察”“接力机会提示仅作观察”“不自动下单”等空泛提示，不得让前端触发模型评分、scheduler dispatch、source fetch、provider 请求、raw 读取、official signal、交易、买点、outcome 或学习权重写入。
- 解锁条件：用户明确批准 `shence-frontend-service -> model-tboard -> plain user semantics` 解锁；若需要改变 owner `observation-board` 字段、状态机、评分或纳入规则，必须另行解锁 `t-board-relay-service`。
- 回滚方式：回退本冻结对象对应的前端语义翻译、测试和文档变更，重新运行前端合同测试、JS 语法检查和页面验收；不清库、不重启 `source-data-service`，也不修改模型四 owner 数据。
- 验证清单：compact 返回 `read_only=true` 且只包含 Day1 合格观察对象；页面显示“T 字接力观察台”标题条、10 个核心列和真实观察行；可见文本不含“数据提示”“下一步”“观察阶段”“ASK”“BID”“source_gap:*”“不自动下单”“接力机会提示仅作观察”“可买入观察”；开板失败风险使用“次日退出风险高”白话表达；前端合同测试、Python 编译检查和 JS 语法检查通过。

### shence-frontend-service -> model-tboard -> terminal default visibility

- 冻结对象：`shence-frontend-service -> model-tboard -> terminal default visibility`。
- 冻结时间：2026-07-02 Asia/Shanghai。
- 拍板人 / 确认来源：用户在交付报告后明确回复“拍板”；此前用户指出“第二天或者第三天不符合就应该下架，而不是一直留着待观察”，并回复“继续”批准继续修复和发布验证。
- 数据资产范围：`/api/model-list/tboard` 默认只读聚合 owner `observation-board` 后，不主动返回 `observation_status=stopped` 的终止对象；`observation_status=data_wait` 仅在 Day2 09:30-10:30 验证窗口未过时保留，一旦窗口已过仍没有有效 Day2 监测事实，也从普通用户主列表下架。Day2 判断优先使用 owner 返回的 `day2_trade_date`，缺失时按 `day1_trade_date` 推导下一个工作日并周末顺延；`include_stale_stopped=true` 只作为历史失效 / 缺口对象只读排查参数，不改变 owner 事实。
- 当前冻结证据：2026-07-02 前端 8030 重启后 `/readyz=ready`；默认 `/api/model-list/tboard?limit=20` 返回 0 条普通用户可见对象；`/api/model-list/tboard?limit=20&include_stale_stopped=true` 返回 5 条审计对象，其中 `000823.SZ` 为 `data_wait` 且 `model_score=NULL`；owner 原始 `/t-board-relay/observation-board?limit=20` 中 `000823.SZ` 同为 `data_wait`，真实抓取 / 阶段事实时间仍为 `2026-06-26T07:53:37.143354+00:00`，最后模型产出时间为 `2026-07-02T07:02:00+00:00`；scheduler、data-inspector ready，`source-data-service` 未重启。
- 数据边界：过滤只影响普通用户默认列表，不删除、不改写、不截断 `decision_t_relay.*`、`research_t_relay.*`、owner `observation-board`、monitor snapshot 或 append-only 审计事实；前端不写 source/raw、scheduler、release gate、交易、买点、outcome 或学习权重。
- 允许的只读验收：读取 `/api/model-list/tboard`、读取 `/api/model-list/tboard?include_stale_stopped=true`、读取 owner `/t-board-relay/observation-board`、访问 `#/model-tboard`、检查 frontend `/readyz`、运行前端合同测试、Python 编译检查和 JS 语法检查。
- 禁止修改项：未经解锁不得改变终止态默认下架、Day2 窗口错过后的 `data_wait` 默认下架、`include_stale_stopped=true` 只读排查参数或前端只读边界；不得将失效过滤下沉为 owner 事实删除、数据库清理、scheduler/source 动作或模型评分修改。
- 解锁条件：用户明确批准本对象解锁；若要改变 owner `observation-board` 字段或状态机、删除历史失效事实、调整 scheduler/source 逻辑，必须另行解锁对应服务。
- 回滚方式：回退本对象对应的 compact 默认过滤、页面兜底过滤、测试和文档变更，重新运行前端合同测试、Python 编译检查、JS 语法检查，并重启前端服务；不清库、不重启 `source-data-service`，也不修改模型四 owner 数据。
- 验证清单：`python -m pytest -q services/shence-frontend-service/tests/test_frontend_contract.py` 通过；`python -m compileall -q services/shence-frontend-service/src services/shence-frontend-service/tests` 通过；`node --check services/shence-frontend-service/public/app.js` 通过；`git diff --check` 通过；前端 `8030` 重启后 `/readyz` 为 ready；默认 `/api/model-list/tboard?limit=20` 不返回已终止或 Day2 窗口错过的 `data_wait` 对象；`include_stale_stopped=true` 可显式排查历史失效和缺口对象；`source-data-service` 未重启。

### shence-frontend-service -> model-tboard -> Day1 summary dedupe

- 冻结时间：2026-06-26 Asia/Shanghai。
- 拍板人 / 确认来源：用户确认 Codex 交付报告，批准将模型四 Day1 汇总去重口径拍板冻结。
- 数据资产范围：`/api/model-list/tboard` 读取 owner `GET /t-board-relay/day1/candidates` 只生成 `day1_scan_summary`，不向浏览器返回 rejected/data_blocked 候选明细或审计 payload。该汇总只看最新 `trade_date`，并在该交易日内按 `canonical_symbol`、`symbol`、`stock.symbol` 或 `instrument_id` 去重，保留 `updated_at`、`created_at`、`as_of_time_utc` 或列表顺序最新的一行后统计扫描数、合格数、未通过数、阻断数、开盘涨停数、未通过主因和更新时间。
- 当前验收事实：前端 `8030` 重启后，`/api/model-list/tboard?limit=10` 返回 `read_only=true`；`day1_scan_summary` 为 `trade_date=2026-06-26`、`scanned_count=21`、`qualified_count=1`、`rejected_count=20`、`data_blocked_count=0`；主列表首条为 `000823.SZ 超声电子`，`model_score=48.0`，`observation_status=continue_watch`。响应不含 `request_payload`、`result_payload`、`game_hypothesis_payload`、`evidence_json` 或 `related_payload`。
- 数据边界：去重只影响前端 compact 汇总展示，不删除、不改写、不截断 owner `decision_t_relay.*`、`research_t_relay.*`、`observation-board`、monitor snapshot 或 append-only 审计事实；前端不写 source/raw、scheduler、release gate、交易、买点、outcome 或学习权重，不把缺失事实补成 0/mock/示例 payload/前端推断。
- 允许的只读验收：读取 `/api/model-list/tboard`、owner `/t-board-relay/day1/candidates`、owner `/t-board-relay/observation-board`、frontend `/readyz`，运行前端合同测试、Python 编译检查、JS 语法检查和 compact payload 剥离检查。
- 禁止修改项：未经解锁不得改变 Day1 汇总去重 key、最新行选择顺序、计数字段含义、审计 payload 剥离、普通用户不看 rejected/data_blocked 明细的边界或前端只读边界；不得将该汇总变成 owner 事实删除、数据库清理、scheduler/source 动作或模型评分修改。
- 解锁条件：用户明确批准本冻结对象解锁；若 owner `day1/candidates` 合同、Day1 合格判定、schema、scheduler/source 取数或模型四状态机变化，必须另行解锁对应服务。
- 回滚方式：回退本对象对应的前端 compact helper、合同测试和文档变更，重新运行前端合同测试、Python 编译检查和 JS 语法检查，并只重启前端服务；不清库、不重启 `source-data-service`，也不修改模型四 owner 数据。
- 验证清单：前端合同测试通过；Python 编译检查通过；JS 语法检查通过；重启后 scheduler/data-inspector/frontend `/readyz` 均 ready；`/api/model-list/tboard?limit=10` 返回 Day1 汇总 `21/1/20/0`；`source-data-service` 未重启。

### shence-frontend-service -> model-tboard -> mobile plain-user cards

- 冻结时间：2026-06-26 Asia/Shanghai。
- 拍板人 / 确认来源：用户在本轮交付报告后回复“确认”，批准将模型四移动端普通用户字段卡片展示拍板冻结。
- 数据资产范围：只冻结 `/api/model-list/tboard` 到 `#/model-tboard` 的手机视口展示方式；数据事实仍只来自 owner `observation-board`、repository status 和 Day1 candidates 汇总。手机卡片完整展示同一 10 个事实字段：股票、模型分、Day1、Day2、监测时间、当前判断、接力强度、关键依据、风险结论、更新；字段标签来自前端列合同，展示方式改变不新增、不删除、不改写任何 owner 字段。
- 当前验收事实：compact API 与 owner `observation-board` 均返回 5 条真实观察对象；Day1 汇总为 `2026-06-26` 扫描 `21`、合格 `1`、未通过 `20`、阻断 `0`；手机 DOM 中 5 条观察对象均为字段卡片，`600172.SH 黄河旋风` 可见风险结论为“封板没守住，次日退出风险高”，页面不显示 owner 原始 `Day3退出风险` 文案；compact 响应不含 `request_payload`、`result_payload`、`game_hypothesis_payload`、`evidence_json` 或 `related_payload`。
- 数据边界：卡片化只影响浏览器展示和初级用户阅读体验，不写 `decision_t_relay.*`、`research_t_relay.*`、source/raw、scheduler、release gate、交易、买点、outcome 或学习权重；不补股票名、模型分、盘口方向、风险结论或缺口事实；`model_score=0` 仍仅展示 owner 明确给出的硬失败综合分，缺关键事实时必须保持空态。
- 允许的只读验收：读取 `/api/model-list/tboard`、owner `/t-board-relay/observation-board`、frontend `/readyz`，访问 `#/model-tboard`，运行前端合同测试、Python 编译检查、JS 语法检查和 Playwright 桌面 / 手机 DOM 与截图检查。
- 禁止修改项：未经解锁不得移除手机字段卡片合同，不得删减 10 个事实字段，不得恢复普通用户可见“观察阶段”“Day3”“下一步”“数据提示”列，不得展示 `ASK` / `BID`、`source_gap:*`、repository/schema/provider/raw/internal 文本，不得将卡片化变成 owner 字段变更、数据库清理、scheduler/source 动作或模型评分修改。
- 解锁条件：用户明确批准本冻结对象解锁；若 owner `observation-board` 字段、Day1 汇总口径、schema、scheduler/source 取数或模型四状态机变化，必须另行解锁对应服务。
- 回滚方式：回退本对象对应的移动端卡片 CSS、合同测试和文档变更，重新运行前端合同测试、Python 编译检查、JS 语法检查和 Playwright 页面验收；不清库、不重启 `source-data-service`，也不修改模型四 owner 数据。
- 验证清单：前端合同测试通过；Python 编译检查通过；JS 语法检查通过；尾随空白检查通过；Playwright 手机 DOM 验收显示 `rowDisplay=grid`、`cellDisplay=grid`、10 个 `data-label` 完整；frontend/scheduler/data-inspector `/readyz` 均 ready；`source-data-service` 未重启。

## Admin 数据任务看板资产

| 入口 | 读取资产 | 日生命周期 | 刷新 | 边界 |
|---|---|---|---|---|
| `/api/admin/daily-board` | `source/requirements`、`source/freshness/sla`、`source/readiness/matrix`、`source/repair-routes`、`source/fetch/queues/summary`、`source/ops/daily-data-summary`、`source/build/results`、`source/build/triggers`、`source/storage/policies`、`scheduler/source-schedule/registry`、`scheduler/materialize/source-schedule`、`scheduler/task-store/daily-summary`、`data-inspector inspection-runs/latest`、`data-inspector inspection-gaps` | `trade_date` | 首屏不自动读取；管理员展开审计/资产明细时按需只读读取；后端 10 秒短缓存合并同日期重复读取 | 仅 `admin`；不提交 fetch、不触发调度、不调用 provider、不写 source/raw/model/research；完整性验收未生成只能作为审计提示，不得把 scheduler 已执行任务清零 |
| `/api/admin/task-board` | scheduler daily task-store summary, source daily data summary, source fetch/build evidence, data-inspector gap audit | `trade_date` | browser read-only refresh every 300 seconds; backend read timeout defaults to 90 seconds unless `SHENCE_FRONTEND_ADMIN_DASHBOARD_TIMEOUT_SECONDS` is set; browser and backend coalesce identical same-day reads with a 10 second short cache while manual refresh bypasses stale cache; task-board uses a lightweight read set and does not read build result/trigger/storage/readiness/inspection details; browser treats task-board as primary and daily-board as optional detail, with admin-specific loading copy only | admin only; summary must provide planned, completed, unfinished, not-yet-due, waiting submit, waiting raw/source output, scheduler failure, target data not produced, build failure, raw-audit warning, and repairable/non-repairable/pending counts; default screen stays aggregated |

Daily lifecycle aggregation: planned tasks use scheduler materialized daily tasks and task-store reconciliation as denominator. `success` and `source_duplicate_skipped` only mean scheduler submitted or deduplicated. Frontend must overlay `/source/ops/daily-data-summary`: `final_data_failed=true`, `data_asset_status=failed`, or build failure counts as final data failure and is subtracted from completed; `data_asset_status=collecting` / queued / running / waiting, active or waiting raw jobs, and no target evidence (`source_row_count=0` plus `build_succeeded_count=0`) are counted as unfinished `collecting` / `awaiting_evidence` only while the row-level lifecycle is still open; after `orchestration_context.lifecycle_expires_at*` or the schedule-group fallback window has passed and there is no completion evidence, the row is `expired_closed`, not active waiting and not data failure; if source daily summary is unavailable, `source_facts_available=false`, source output counts stay null, and scheduler-completed source tasks are downgraded to `awaiting_evidence` rather than inferred expiry; `raw_failure_audit_only=true` or `completed_with_provider_audit` is raw-audit warning only and counts as completed only when target evidence exists. Missing target-day data-inspector run is an audit hint, not a reason to reset completed tasks.

2026-07-15 admin browser action asset: `reload-admin-board` is the only manual refresh action for `#/admin-ops`; date input changes only mutate the admin board `trade_date` and reload the read-only board. Coverage alert text comes from admin summary/upstream fields only; model page refresh copy remains isolated in `refreshState`.
2026-07-15 task-count asset boundary: `*_tasks` counters are scheduler task-row counters after source evidence overlay. Source build/raw result counters such as `build_failed_results` remain audit evidence (`build_failed_result_count`) and must not be added to task failure counts. Waiting states are split into `awaiting_dispatch_tasks` (待提交抓取) and `awaiting_evidence_tasks` (等待数据结果).
2026-07-15 admin render contract: real task-board and daily-board payloads must be accepted by browser render helpers without throwing. Upstream read badges use `upstream_status.status`; admin block reasons use admin task/asset statuses only and must not import model-list state fields. The page must show Chinese empty/progress states instead of `页面不可读` when payloads are readable.
2026-07-15 admin progress clarity: `/api/admin/task-board` exposes scheduler ledger progress separately from final source-data completion. The main board must show scheduler processed counts, final completed counts, raw waiting/active counts, and source output counts so `0%` final completion is not mistaken for no scheduler activity. Scheduler `success/source_duplicate_skipped` remains process evidence only; final completion still requires target source output.
2026-07-15 admin label clarity: upstream status labels must use Chinese business names for daily source output and scheduler ledger. Missing target-day inspection is “未生成”, not read failure. `collecting` is displayed as “等待抓取/产出”/“等待产出” and means raw/source output is not closed; it must not be interpreted as active worker processing unless raw active counts are positive.
2026-07-20 admin task-row overlay asset: `/api/admin/task-board` must use scheduler task rows plus source submit audit fields to classify each row. Same-table raw waiting does not demote all processed tasks; only rows with live source submissions are `collecting`, rows without completion evidence are `awaiting_evidence` while their lifecycle is open, lifecycle-expired rows are `expired_closed`, and rows with target source/build evidence or explicit completed asset state remain completed unless final data failure is reported. The main screen reports effective raw waiting/active counts for active unfinished rows only; source-wide residual queue totals remain in `raw_waiting_jobs_total/raw_active_jobs_total` audit fields.
2026-07-15 admin request performance: `#/admin-ops` first screen must call `/api/admin/task-board` only; `/api/admin/daily-board` is an on-demand detail payload loaded when the audit/details panel opens. Duplicate same-date admin reads are de-duplicated in browser and coalesced in backend for 10 seconds; the cache is read-only and cannot mutate source, scheduler, provider, model, or research facts.

补救标签口径：`可补` 只用于有正规 repair route、备源 provider 或 source build 重建路径的失败 / 缺失；`不可补` 只用于实时盘口快照、分钟线、逐笔成交、竞价快照、同花顺付费次日概率等窗口事实；`待确认` 表示当前合同没有明确补救路线。未到抓取时间、待提交抓取、等待抓取/产出和等待数据结果不展示可补 / 不可补标签。

前端展示口径：主屏只展示中文业务词，不展示 `inspection_unknown`、`not_due` 等英文状态码；数据表名、缺口码、接口路径、JSON 字段名等技术标识不得作为默认主屏内容。完整资产和缺口明细只放在折叠审计区；任务明细默认只汇总为计数，不逐条铺开。

### shence-frontend-service -> admin-ops -> aggregated daily lifecycle board

- Current time: 2026-07-13 Asia/Shanghai.
- 确认来源：用户确认按日周期任务总览、中文业务词和不逐条铺开任务的口径执行，并要求根据真实数据库数据和任务比对。
- 数据资产范围：`/api/admin/daily-board`、`/api/admin/task-board` 与 `#/admin-ops` 的只读聚合展示；不改变 source/scheduler/data-inspector 的事实生成。
- 时间展示口径：latest_task_update_at、latest_data_update_at 等后端时间字段保持原始事实；浏览器仅把带明确偏移的时间显示为北京时间 YYYY-MM-DD HH:mm:ss，不得改写、推断或用当前时间补事实。
- 禁止项：未经解锁不得把未到抓取时间计为失败，不得把完整性验收未生成计为任务未完成，不得用构建成功、历史验收 run、0、当前时间、mock 或前端推断补目标日事实，不得让 admin 看板触发 source fetch、scheduler dispatch、provider 调用或任何后端事实写入。
- Acceptance: default screen shows planned, completed, unfinished, not-yet-due, waiting submit, waiting raw/source output, scheduler failure, target data not produced, build failure, raw-audit warning, source output, and repairability counts; it does not expose raw English status codes or task rows by default. Raw failures with final source output do not count as failure; final source asset failures must reduce completed count and increase failed count.
- 回滚：回退 admin 看板展示、聚合 helper、合同测试和本账本文档变更；只重启受影响服务验证，不清库，不改 source/scheduler/data-inspector 事实。

## Admin Board Lifecycle State

`/api/admin/task-board` preserves `raw_cancelled_jobs`, row-level `raw_cancelled_count`, and `expired_closed` status from `source/ops/daily-data-summary`, and it may also derive `expired_closed` from scheduler row lifecycle expiry. `expired_closed` means a normal source daily task has exceeded its lifecycle and is no longer displayed as an active job. It does not mean data completion and does not enter repairable/non-repairable failure classification by itself. Completed and expired rows may still have source-wide raw queue residuals; those residuals are audit totals only and are excluded from the main effective waiting count. If data must be filled, scheduler or data-inspector must submit a new formal source fetch, repair, or backfill task.

### 2026-07-23 Admin Board Expired Task Aggregation

The task board's aggregation now counts row-level scheduler lifecycle expiry, including tasks that were never submitted to source-data-service. `expired_closed_tasks` is separate from `awaiting_dispatch_tasks`, `collecting_tasks`, and final data failures. The state means the original daily task instance is no longer enabled; it does not fabricate completion and it does not by itself assign repairability. Failed or missing target data still receives repairability labels only when the row is classified as an actual data failure/missing output.
