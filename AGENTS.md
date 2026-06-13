# ai_stock Codex 项目规则

## 事实源

项目全局硬性约束只看项目根目录 `AGENTS.md`。`AGENTS.md` 是项目主契约、全局规则、执行标准和跨模块业务主线的唯一文档入口；任何根目录 `README.md`、临时包说明、聊天记录、旧 docs、检查清单或历史账本都不得覆盖 `AGENTS.md`。

代码与运行事实以当前代码、运行容器、SQLAlchemy metadata 和 `infra/sql/bootstrap_schema.sql` 为准。

各功能模块、服务、子系统或功能块的文档事实源，只能是对应模块根目录下的唯一当前 MD 文档，默认是该目录的 `README.md`。模块根目录 MD 只记录本模块真实契约、接口、库表、运行逻辑、调度、验证和变更；不得把模块事实长期放在项目根目录、`docs/`、临时迭代包、历史归档或其他目录。

`需优化点.MD` 只记录非阻断优化账本，不作为已落地事实源。

模型契约入口：

1. `services/models_services/README.md`
2. `services/models_services/hot-candidates-service/README.md`
3. `services/models_services/candidate-memory-service/README.md`
4. `services/models_services/ambush-watchlist-service/README.md`

根目录新增的模型迭代包只允许作为临时输入。开发完成后必须把包内 MD 拆分覆盖到对应模块或服务根目录的唯一当前 MD；涉及多个模块时，每个模块只接收自己的真实变更。确认覆盖后再清理临时包，根目录临时包不得长期作为事实源。

## 根目录文档标准

项目根目录只保留两个项目 MD：

- `AGENTS.md`：项目主契约、硬性标准、业务主线和执行规则。
- `需优化点.MD`：非阻断优化账本。

根目录不得再新增业务架构、检查清单、研究准备、迭代包说明、历史归档、`README.md` 或任务账本类 MD。`docs/` 不再作为项目事实源或长期文档入口；此类内容必须合并到 `AGENTS.md`、`需优化点.MD` 或对应服务 / 模块 / 功能块根目录唯一当前 MD。

除根目录按上文固定保留两个项目 MD 外，一个目录下原则上尽可能有且只有一个项目 MD；每一层目录可以有自己的唯一 MD。父目录 MD 记录该层级的总契约、跨模块规则和聚合说明，子目录 MD 只记录该子模块 / 子服务 / 功能块自己的真实契约和变更，不得在同一目录下拆分多个业务事实源 MD。

## 开始前检查

1. 当前工作目录必须是 `D:\projects\ai_stock`。
2. Git 根目录必须是 `D:\projects\ai_stock`。
3. 项目模型配置必须存在：`infra/model-configs/chatgpt-5.5-xhigh.toml`。
4. 模型配置必须是 `model_provider=tokenapi`、`model=gpt-5.5`、`model_reasoning_effort=xhigh`。
5. 开发前必须读 `services/models_services/README.md`、三个子模型 README，以及本次涉及服务 / 模块 / 功能块根目录下的唯一当前 MD。

## 硬性执行标准

- 当前代码版本视为最新需求落地。旧需求文档、旧抓包、旧 DOM、旧 API、旧迁移链、旧本地数据口径和旧迭代包不能覆盖当前代码事实。
- 所有项目自有 MD 必须是当前说明或当前契约，禁止保留过期任务账本、历史归档、旧实现承诺或未落地需求当作事实。
- 全局规则、跨模块契约和硬性执行标准只以根目录 `AGENTS.md` 为准；任何其他 MD、临时包、docs、README 或聊天记录与 `AGENTS.md` 冲突时，必须以 `AGENTS.md` 为准。
- 功能模块事实源只以该功能模块根目录的唯一当前 MD 为准；模块外部文档只能做索引或引用，不能成为该模块事实源。
- 根目录只保留 `AGENTS.md` 和 `需优化点.MD`。
- `services/models_services` 根目录只能有一个项目 MD：`README.md`。三个子模型目录也各自只能有一个项目 MD：`README.md`。`.pytest_cache` 等生成目录不属于项目文档。
- 三大模型所有契约、任务、跨服务调整、调度和前端展示要求必须合并到上述唯一 README 中，不得新增分散 MD。
- 文档更新必须覆盖，不只追加。一个主要目录保留一个当前 README；模型服务目录只保留唯一 README。
- 后期所有迭代、更新或新增，只要包含代码变更、接口变更、库表变更、调度变更、运行逻辑变更、业务逻辑变更、规则变更或 provider / adapter / converter 变更，必须在同一轮闭环内把最新变化详细覆盖到对应功能块根目录下的唯一当前 MD；不得只写在临时说明、聊天记录、根目录新增 MD 或 `docs/` 中。
- 多层目录允许逐层拥有各自唯一 MD：上层 MD 写跨目录总规则，下层 MD 写本目录功能细节；同一目录不得因为一次迭代拆出第二份业务说明、检查清单、任务账本或历史归档 MD。
- 三大模型每次优化后，必须写清数据入口、输入数据样式、状态流转、调度间隔、数据产出、落库表、缺口码、阈值、下游消费和禁止反写规则。
- 新需求包落地后，必须先拆服务和模块，再改代码；开发完成后把变更覆盖到对应唯一 README。多模块需求不得只写在总说明里。
- 功能不完善但不阻断当前链路时，不能伪装成已完善；统一记录到根目录 `需优化点.MD`，写清优先级、现状、影响和后续建议。
- 真实数据缺失必须保留 `NULL`、空态、缺口码或阻断状态，禁止用 0、空字符串、前端 mock、GPT 推断或示例 payload 补事实。
- 模型服务单条调用失败不得拖垮整批任务；必须生成行级 `row_failed` warning、模型服务异常缺口码、阻断状态和可审计 payload。异常本身是研究事实，不能吞掉。
- API 对外出参必须先经过契约适配，不能直接泄露物理库字段类型；例如库内整数 `run_id/job_run_id` 输出到字符串契约时必须显式转成字符串，查询接口不得因历史持久化字段类型差异返回 500。
- 任何进入评分、闸门、标签、买点或发布链路的新 provider、fallback、adapter、converter，必须先完成真实外部请求探针和数据契约记录。
- 前端、gateway、Jarvis、explanation 和 notification 只能读取、展示、翻译、解释或提醒，不得修改模型事实、分数、状态、标签、发布闸门、买点版本、交易或学习权重。
- 数据巡检与调度健康优先级高于模型展示、前端调试、Jarvis、通知和普通数据刷新。
- **数据源 Docker 服务不得随意关停**：后续使用 Codex 或人工进行任何项目迭代时，除非本次任务明确是“更改数据源服务代码、修改数据源 Docker 配置、增加/删除/迁移数据源 provider/API、执行 source-data-service 发布验证”，否则不得停止、重启、删除、重建或替换 `source-data-service` Docker 容器；不得执行会间接导致其停机的 `docker compose down`、全栈重建、全量清库、容器清理或网络重置。需要联调其他服务时，只允许让其他服务适配当前持续运行的数据源服务。
- 任何确需重启 `source-data-service` 的变更，必须先写明原因、影响范围、备份/回滚步骤、预计停机窗口和验证清单；完成后必须立刻验证 `/healthz`、`/readyz`、`/source/providers/status`、provider API registry、source requirements、gap repair plan 和至少一个 P0 原接口 dry-run。
- 每次重启、部署、清库、补跑、验收或前端联调前后，必须优先确认 `data-inspector-service` 与 `scheduler-service` 健康。
- 每次文档或代码闭环后，必须至少自检旧事实源引用、明显乱码、关键服务健康；代码变更还必须按风险运行相关测试。

## 业务架构

当前业务围绕三大模型运行：

- `hot_candidates`：同花顺付费次日概率候选榜蒸馏模型，提炼 T+1 和短窗口可兑现机会。
- `candidate_memory`：历史候选记忆模型，追踪离开短窗口后的延迟兑现、二波和慢趋势价值。
- `ambush_watchlist`：深圳 A 股潜伏抬头 / 龙抬头扫描模型，识别低位早期弱转强结构。

主链路：

```text
provider / market / candidate facts
-> candidate-service / market-data-service / news-service
-> research-service 组装真实输入
-> 三大模型服务评分
-> research-service 落库
-> research-data-mart 同步研究快照、治理、标签、指标
-> data-inspector-service 巡检缺口
-> scheduler-service 调度、补跑、启动守卫
-> execution-timing-service 生成买点版本
-> gateway-service / shence-frontend-service 展示
-> Jarvis / explanation 只读解释
```

数据采集服务模型训练、校准和解释。历史打标必须保留来源线、路径线、T+1 可兑现线、风险线、环境线、证据质量线和学习资格线。

## 研究数据标准

- 研究数据必须来自真实库表、真实 provider 响应或可追溯服务输出。
- 缺事实保留 `NULL`、缺口码和巡检记录，不用 0 或空字符串补齐。
- Decimal、价格、收益、分数和 JSONB payload 保持高精度与可审计。
- outcome 标签必须区分等待、阻断、失败、完成和失效；非完成态不得携带完成耗时。
- 买点、监控、信号、标签、研究快照必须保留来源时间、计算时间、模型版本和质量信息。
- 热榜、候选记忆、潜伏抬头的模型异常必须落到对应分析、证据、特征或 transition audit 中，字段至少包含 `symbol`、`instrument_id`、`stage`、`run_id/as_of_time`、`error_code`、`error_message`、`source_gap_codes`、输入引用。

## 工程口径

- 数据库为当前基线口径，唯一有效迁移是 `packages/db-schema/alembic/versions/0001_current_baseline.py`。
- `infra/sql/bootstrap_schema.sql` 必须由当前 SQLAlchemy metadata 和当前基线渲染。
- 不迁移旧数据，不为旧字段、旧接口、旧 DOM、旧批次或旧文档保留兼容分支。
- `infra/model-configs/chatgpt-5.5-xhigh.toml` 是项目内部 GPT / Jarvis 分析配置唯一入口。
- GPT/Jarvis 只做解释、巡检、监督和建议，不能修改事实、置信度、分数、状态、发布闸门、交易或学习权重。
- 缺真实数据时保留 `NULL` 和 `source_gap:*`，禁止用 0、空字符串、前端 mock 或 GPT 推断补事实。
- `reference_entry_price` 是评估基准锚点，不是交易价或推荐价。
- 买点版本链 append-only，修复写新版本，旧坏版本保留审计。
- 候选记忆缺交易日历年龄时 `memory_age_days=NULL`，状态落为 `blocked_data_gap` 并保留缺口码。
- 候选记忆状态变化允许由正式 job 或 `ad_hoc:*` 编排触发，但都必须写 `candidate_memory_state_history` 和 transition audit，不能因缺 job_run_id 丢状态。

## 运行保障

- `data-inspector-service` 和 `scheduler-service` 优先级最高。
- 重启、部署、清库、补跑、前端调试和链路验收前后，都必须先确认这两个服务健康。
- `scheduler-service` 启动后必须立即触发 `data_inspection startup_guard`。
- `scheduler-service /readyz` 必须同时校验后台循环、`data-inspector-service /readyz` 和本次启动巡检结果。
- 启动巡检未完成或失败时不得判定 ready。
- 前端、网关、工作台和运行监管必须把数据巡检与调度状态作为核心健康信号。

## 三模型闭环检查

- `services/models_services` 根目录和三个子模型目录各自只保留一个当前 README，且必须覆盖当前代码。
- 根目录临时模型迭代包不得作为长期事实源。
- `research-service` 负责组装模型输入、调用模型服务、写入数据库并同步 research-data-mart。
- `data-inspector-service` 覆盖模型决策回顾、买点服务、信号监控、outcome、Jarvis 上下文等巡检域。
- `scheduler-service` 注册启动巡检、盘前评分、候选记忆评分、潜伏日线补跑、买点重算、监控刷新和研究任务。
- 待处理模型链路阻断项当前为无；非阻断项统一见 `需优化点.MD`。

## 数据源准入

- 新 provider、fallback、adapter、converter 进入评分或闸门前，必须完成真实外部请求探针和数据契约记录。
- 同花顺只允许接入无需登录态、Cookie、账号 token、动态 `hexin-v` 的公开接口。
- 市场数据源清单只维护在 `infra/provider-configs/market-data-sources.toml`。
- 仓库禁止写入明文 API key、token、password 或 access secret。

## 危险操作

未经用户明确确认，禁止执行或等价执行：

- `git add`
- `git commit`
- `git push`
- `git reset`
- `git clean`
- 删除、移动、重命名、递归清理文件或目录

如果用户明确要求清理，必须先解析绝对路径并确认目标位于 `D:\projects\ai_stock` 内。Windows 下优先使用 PowerShell 原生命令和 `-LiteralPath`。

## 文档同步

每次功能、接口、库表、运行、部署、调度、前端或规则变更，必须立即覆盖对应功能模块根目录的唯一当前 MD；跨模块或全局规则变更必须覆盖根目录 `AGENTS.md`。

三大模型每次优化完成后，必须覆盖对应模型服务根目录的唯一 `README.md`，写清数据入口、数据样式、状态流转、调度间隔、数据产出、落库表、缺口码、阈值、下游消费和禁止反写规则。

当前代码版本视为最新需求落地。功能不完善但不阻断现链路的内容，记录到根目录 `需优化点.MD`，等待下一批需求文档处理。


## 数据源服务常驻与字段合同硬标准

- `source-data-service` 是项目事实底座。除非本次任务明确修改数据源服务、数据源 Docker、provider/API 或执行数据源发布验证，否则不得停止、重启、重建、删除或替换 `source-data-service` 容器。
- 新增或修改任何 source 字段，必须同步更新字段合同、README、SQL 注释或 migration，并保证 `/source/contracts` 可见。
- P0 + online required 字段必须有主源、备源、raw 表、repair plan、lineage plan、质量规则和 available_at 口径。
- 巡检发现数据缺口时，必须能通过 `/source/gaps/diagnose` 定位 provider/api/raw_table/request_params/rebuild_steps，不能只输出“缺数据”。
- 任何服务不得直接读取 `raw_*` 作为模型输入；只能读取经过 source build、quality_status、lineage 和 available_at 校验的 `source.*`。

## 输出要求

完成任务时必须说明：

1. 本次改动范围。
2. 是否更新文档。
3. 是否运行测试或自检。
4. 未闭环风险和下一步建议。

## 数据源并发采集硬性标准（DS-4）

任何服务需要新增或临时索取数据时，必须通过 `source-data-service` 的 fetch orchestration：`/source/fetch/plan` -> `/source/fetch/submit` -> worker pull/complete。不得在模型服务、调度服务或后续业务服务中直接并发调用 BaoStock、AKShare、Tushare、EastMoney、CNINFO 等 provider。P0 release_gate 数据必须进入 `urgent_release_gate_queue`；历史回补和研究任务不得抢占 P0 数据源并发资源。


## DS-5 数据源持久化队列与 worker 硬标准

数据源抓取任务必须采用生产-消费-状态回调模式。所有周期调度、数据巡检补采、模型临时索取、release_gate 预检、人工回补、provider probe 都必须提交到 source-data-service fetch orchestration，不允许模型或其他服务直接并发调用外部 provider。

生产环境硬要求：

```text
1. SOURCE_DATA_QUEUE_BACKEND 必须为 postgres。memory 只允许本地单元测试。
2. source-data-service 只负责 API 与任务状态；source-data-worker 负责消费任务。
3. 每个任务必须有 fetch_batch_id、job_item_id、request_hash、status、worker_id、lease_expires_at、attempt_count。
4. worker 长任务必须 heartbeat；超时 lease 必须可重排。
5. 任务失败必须进入 retry / backup / dead-letter 之一，禁止静默丢弃。
6. callback 采用 outbox；下游回调失败不得丢失任务状态。
7. raw 抓取成功后必须生成 source_build_trigger，继续执行 quality check、source build、source_lineage。
8. 普通迭代不得关停 source-data-service；若只改 worker，也不得重启 API 容器。
```

## DS-6 数据源上线闭环硬标准

- provider 真实返回结果不得直接供模型使用，必须先 `/source/raw/ingest-result` 写入 raw 原接口层，并保留 `request_hash`、`response_schema_hash`、`response_row_hash`。
- raw 进入 source 前必须执行质量门禁；`build_allowed=false` 的 raw 批次不得进入 `source.*`。
- `source_build_trigger` 是 raw 到 source 的唯一正规入口；source build 必须同步生成 `governance.source_lineage_v1` 或等价 lineage 记录。
- 三大模型 release_gate 前必须调用 `/source/release/preflight`；返回 `can_release_official_signal=false` 时禁止发布 official signal。
- preflight 必须同时看模型 source 覆盖度和 source freshness；P0 字段缺失、过期、低覆盖率时必须阻断，不得自动降级。
- 大表必须遵守 `/source/storage/policies`：raw/source/lineage 的分区键、索引、热保留天数和归档目标必须明确后才能进入生产。

## DS-7 数据源生产拍板门禁硬标准

- 数据源服务是否可拍板，不再只看 `/readyz`，必须看 `/source/ops/production-readiness`。
- 生产环境必须执行 `scripts/source_data_acceptance.py --require-postgres`，返回 0 后才能进入生产候选锁定。
- provider 真实可用性不能靠猜测；需要按 `/source/probe/matrix` 执行真实 probe，并保留验收输出或写入 `governance.source_data_acceptance_*` 表。
- memory queue / memory repository 只允许本地单元测试；生产必须使用 Postgres 持久化队列和 raw/source/lineage 持久化写入。
- Codex 后续迭代如果不是修改数据源服务或数据源发布验证，不得重启 `source-data-service`；如果必须跑验收，应优先只重启 `source-data-worker` 或单独运行脚本。
