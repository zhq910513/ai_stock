const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

const FRONTEND_DEFAULT_TIMEOUT_MS = 4500;
const FRONTEND_TABLE_TIMEOUT_MS = 3500;
const FRONTEND_FAST_TIMEOUT_MS = 2200;
const FRONTEND_REPOSITORY_TIMEOUT_MS = 6000;
const FRONTEND_HOT_MODEL_LIST_LIMIT = 20;
const FRONTEND_HOT_MODEL_LIST_TIMEOUT_MS = 24000;
const FRONTEND_TBOARD_COMPACT_TIMEOUT_MS = 24000;
const TBOARD_AUTO_REFRESH_MS = 60000;
const ADMIN_DASHBOARD_REFRESH_MS = 300000;
const ADMIN_DASHBOARD_REQUEST_TIMEOUT_MS = 95000;
const ADMIN_DAILY_BOARD_OPTIONAL_TIMEOUT_MS = 12000;
const ADMIN_BOARD_CACHE_TTL_MS = 10000;
const TBOARD_DEFAULT_HIDDEN_STATUSES = new Set(["stopped"]);
const TBOARD_DAY2_WINDOW_END_MINUTES = 10 * 60 + 30;
const FRONTEND_SOURCE_STATUS_TIMEOUT_MS = 24000;
const PREFERRED_CANDIDATE_TRADE_DATE = null;
const CANDIDATE_TRADE_DATE_FALLBACK_LABEL = "最新可见交易日";

const OPEN_ROUTES = [
  { key: "candidates", group: "数据", label: "候选输入", icon: "候", hash: "#/candidates" },
  { key: "model-hot", group: "四个模型", label: "热点模型", icon: "热", hash: "#/model-hot" },
  { key: "model-memory", group: "四个模型", label: "候选记忆", icon: "记", hash: "#/model-memory" },
  { key: "model-ambush", group: "四个模型", label: "潜伏抬头", icon: "伏", hash: "#/model-ambush" },
  { key: "model-tboard", group: "四个模型", label: "T字接力", icon: "T", hash: "#/model-tboard" },
  { key: "research-ambush-valley", group: "研究中心", label: "低谷图库", icon: "谷", hash: "#/research-ambush-valley" },
  { key: "admin-ops", group: "\u7ba1\u7406", label: "\u6570\u636e\u4efb\u52a1\u770b\u677f", icon: "A", hash: "#/admin-ops", requiresRole: "admin" },
];

const MODEL_PROFILES = {
  "model-hot": {
    key: "hot",
    title: "热点候选模型",
    subtitle: "同花顺付费次日概率候选榜蒸馏，观察 T+1 和短窗口兑现。",
    service: "hot",
    modelCode: "hot_candidates",
    modelPhase: "preopen_release_gate",
    symbol: "000063.SZ",
    readyPath: "readyz",
    healthPath: "healthz",
    scorePath: "score",
    samplePayload: {
      row: {
        instrument_id: "000063.SZ",
        symbol: "000063.SZ",
        name: "中兴通讯",
        candidate_source: "hot_candidates",
        p_limit_up: 62.5,
        p_limit_up_source: "source.ths_paid_limit_up_probability_v1",
        candidate_available_at: "2026-06-12T01:30:00Z",
        daily_bars: [],
      },
      as_of_time_utc: "2026-06-12T01:30:00Z",
    },
  },
  "model-memory": {
    key: "memory",
    title: "热点候选模型",
    subtitle: "追踪离开短窗口后的二波、慢趋势和延迟兑现价值。",
    service: "memory",
    modelCode: "candidate_memory",
    modelPhase: "outcome_label",
    symbol: "000063.SZ",
    readyPath: "readyz",
    healthPath: "healthz",
    scorePath: "score",
    samplePayload: {
      row: {
        instrument_id: "000063.SZ",
        symbol: "000063.SZ",
        name: "中兴通讯",
        memory_age_days: 3,
        first_source_model: "hot_candidates",
        first_signal_date: "2026-06-12",
        p_limit_up: 62.5,
        daily_bars: [],
      },
    },
  },
  "model-ambush": {
    key: "ambush",
    title: "热点候选模型",
    subtitle: "深圳 A 股低位潜伏、弱转强和龙抬头结构扫描。",
    service: "ambush",
    modelCode: "ambush_watchlist",
    modelPhase: "release_gate",
    symbol: "000063.SZ",
    readyPath: "readyz",
    healthPath: "healthz",
    scorePath: null,
    samplePayload: null,
  },
  "model-tboard": {
    key: "tboard",
    title: "T 字接力观察台",
    subtitle: "Day1 合格才入表；Day2 每 5 分钟刷新，触发后看封板能否守到收盘。",
    service: "tboard",
    modelCode: "t_board_relay",
    modelPhase: "day1_scan",
    symbol: "000759.SZ",
    readyPath: "t-board-relay/readyz",
    healthPath: "t-board-relay/healthz",
    scorePath: null,
    repositoryPaths: [
      ["repository", "t-board-relay/repository/status"],
      ["observation_board", "t-board-relay/observation-board"],
    ],
  },
};

const MODEL_LIST_COLUMNS = {
  hot: [
    ["stock", "股票"],
    ["signal_date", "入选日"],
    ["readiness_score_pct", "准备度"],
    ["ths_limit_up_probability", "同花顺概率"],
    ["model_score", "模型分"],
    ["current_price", "最新价格"],
    ["reference_entry_price", "评估基准价"],
    ["return_from_entry_pct", "基准后涨幅"],
    ["entry_opportunity_status", "买入状态"],
    ["mae_pct", "基准后最大回撤"],
    ["verification_status", "验证"],
    ["risk_summary", "风险"],
    ["latest_snapshot_time", "更新"],
  ],
  memory: [
    ["stock", "股票"],
    ["reactivated_date", "入选日"],
    ["second_wave_trigger_code", "触发证据"],
    ["model_score", "模型分"],
    ["current_price", "最新价格"],
    ["reference_entry_price", "评估基准价"],
    ["return_from_entry_pct", "基准后涨幅"],
    ["entry_opportunity_status", "买入状态"],
    ["mae_pct", "基准后最大回撤"],
    ["verification_status", "验证"],
    ["risk_summary", "风险"],
    ["latest_snapshot_time", "更新"],
  ],
  ambush: [
    ["stock", "股票"],
    ["effective_turn_anchor_day", "入选日"],
    ["selection_summary", "入选天数"],
    ["model_score", "模型分"],
    ["current_price", "最新价格"],
    ["reference_entry_price", "评估基准价"],
    ["return_from_entry_pct", "基准后涨幅"],
    ["entry_opportunity_status", "买入状态"],
    ["mae_pct", "基准后最大回撤"],
    ["verification_status", "验证"],
    ["risk_summary", "风险"],
    ["latest_snapshot_time", "更新"],
  ],
  tboard: [
    ["stock", "股票"],
    ["model_score", "模型分"],
    ["day1_trade_date", "Day1"],
    ["day2_trade_date", "Day2"],
    ["day2_trigger_time", "监测时间"],
    ["current_conclusion", "当前判断"],
    ["relay_strength_label", "接力强度"],
    ["key_reason", "关键依据"],
    ["risk_tip", "风险结论"],
    ["latest_snapshot_time", "更新"],
  ],
};

const MODEL_LIST_COLUMN_WIDTHS = {
  hot: {
    stock: 106,
    signal_date: 86,
    readiness_score_pct: 82,
    ths_limit_up_probability: 88,
    model_score: 72,
    current_price: 80,
    reference_entry_price: 88,
    return_from_entry_pct: 86,
    entry_opportunity_status: 92,
    mae_pct: 88,
    verification_status: 86,
    risk_summary: 86,
    latest_snapshot_time: 108,
  },
  memory: {
    stock: 106,
    reactivated_date: 86,
    second_wave_trigger_code: 104,
    model_score: 72,
    current_price: 80,
    reference_entry_price: 88,
    return_from_entry_pct: 86,
    entry_opportunity_status: 92,
    mae_pct: 88,
    verification_status: 90,
    risk_summary: 92,
    latest_snapshot_time: 108,
  },
  ambush: {
    stock: 102,
    effective_turn_anchor_day: 78,
    selection_summary: 70,
    model_score: 64,
    current_price: 70,
    reference_entry_price: 78,
    return_from_entry_pct: 78,
    entry_opportunity_status: 86,
    mae_pct: 78,
    verification_status: 78,
    risk_summary: 78,
    latest_snapshot_time: 80,
  },
  tboard: {
    stock: 104,
    model_score: 64,
    day1_trade_date: 70,
    day2_trade_date: 70,
    day2_trigger_time: 76,
    current_conclusion: 124,
    relay_strength_label: 86,
    key_reason: 196,
    risk_tip: 204,
    latest_snapshot_time: 142,
  },
};

const MODEL_COLUMN_HINTS = {
  stock: "股票代码和名称；名称只展示已入库或研究仓库可用事实，异常编码或旧样例英文名会显示为待标准化。",
  signal_date: "热点候选进入当前候选池的交易日。",
  selected_days: "该模型当前观察窗口，不代表已形成买点或收益结论。",
  limit_up_stage: "由标准涨停事实生成。",
  ths_limit_up_probability: "同花顺付费教师概率；当前未入库时保持空态和缺口。",
  model_score: "模型服务或后续决策仓库输出的真实模型分；未物化时不补 0。",
  current_price: "标准日线或研究仓库返回的最新可见价格。",
  reference_entry_price: "评估基准锚点，不是交易价；未物化时保持空态。",
  return_from_entry_pct: "基于评估基准后的真实收益验证，未成熟或未物化时保持空态。",
  entry_opportunity_status: "买入路径状态；缺买点或分钟路径时显示数据缺口。",
  mae_pct: "基准后最大不利波动；没有真实路径时保持空态。",
  verification_status: "收益或阶段结果验证状态；等待、缺口和未成熟不能当作成功。",
  risk_summary: "风险摘要，来自后端事实或缺口状态，前端不推断零风险。",
  data_quality: "标准事实或研究仓库可读质量。",
  latest_snapshot_time: "该行最后一次模型产出时间和最新真实抓取/事实时间。",
  source_gaps: "行级待补事实数量和前两个主要原因。",
  source: "该行主要数据来源。",
  first_signal_date: "候选记忆种子第一次出现在候选池的日期。",
  memory_age_days: "候选记忆交易日龄；缺交易日历时必须为空并阻断。",
  ttl_remaining_days: "记忆有效期剩余；未物化时保持空态。",
  second_wave_trigger_code: "候选记忆二波触发证据；未物化时不能用复现次数冒充确认。",
  effective_turn_anchor_day: "潜伏抬头样本当前观察日，由前复权日线窗口生成。",
  primary_trough_date: "窗口内最低点日期，用于低谷图库候选。",
  days_since_low_at_turn: "当前样本日距低点的天数。",
  shape_type: "前端根据前复权日线窗口生成的可复核形态提示，不等同于正式模型结论。",
  valley_maturity_hint: "低谷成熟提示，用于人工复核和后续图库建设。",
  turn_freshness_bucket: "低点后抬头新鲜度分桶。",
  current_conclusion: "模型四当前给普通用户看的阶段判断，避免和风险结论重复。",
  current_stage: "模型四当前所处观察阶段；普通用户列表默认不展示。",
  day1_trade_date: "首日合格 T 字板所在交易日。",
  day2_trade_date: "Day1 后的下一个正常开市交易日；未校验或未到时为空。",
  day2_trigger_time: "Day2 开盘后 5 分钟滚动监测中的检查时间或首次触发时间。",
  day3_trade_date: "Day2 后的下一个正常开市交易日；普通用户列表仅在进入 Day3 阶段后由后端结论体现。",
  relay_strength_label: "当前接力状态。已开板、卖压占优或未触发时优先显示失效原因。",
  next_observation: "后续需要看的时间窗口或停止跟踪提示；普通用户列表默认不展示。",
  key_reason: "当前判断的主要数据依据。",
  risk_tip: "由盘口、强度、封板维护或缺口事实生成的风险结论。",
};

const MODEL_REVIEW_FILTERS = {
  hot: [
    { key: "symbol", label: "股票代码", type: "text", placeholder: "000063" },
    { key: "release_gate", label: "发布状态", options: ["all", "allowed", "blocked", "blocked_data_gap"] },
    { key: "source_gap", label: "缺口", options: ["all", "with_gap", "no_gap"] },
  ],
  memory: [
    { key: "symbol", label: "股票代码", type: "text", placeholder: "000063" },
    { key: "memory_state", label: "记忆状态", options: ["all", "blocked_data_gap", "memory_watch", "memory_active", "memory_reactivated"] },
    { key: "appearance_count", label: "出现次数", options: ["all", "multi", "single"] },
    { key: "source_gap", label: "缺口", options: ["all", "with_gap", "no_gap"] },
  ],
  ambush: [
    { key: "symbol", label: "股票代码", type: "text", placeholder: "000063" },
    { key: "shape_type", label: "形态类型", options: ["all", "valley_stabilization", "horizontal_breakout_watch", "continuous_rebound_watch", "sample_insufficient"] },
    { key: "source_gap", label: "缺口", options: ["all", "with_gap", "no_gap"] },
  ],
  tboard: [
    { key: "symbol", label: "股票代码", type: "text", placeholder: "输入代码" },
    { key: "observation_status", label: "观察状态", options: ["all", "continue_watch", "opportunity", "data_wait", "stopped", "completed"] },
  ],
};

const MODEL_FILTER_VALUE_FIELDS = {
  limit_event_type: "涨停结构",
  data_quality: "数据质量",
  source_gap: "数据缺口",
  release_gate: "发布状态",
  memory_state: "记忆状态",
  appearance_count: "出现次数",
  shape_type: "前端根据前复权日线窗口生成的可复核形态提示，不等同于正式模型结论。",
  observation_status: "观察状态",
};

const FILTER_OPTION_LABELS = {
  all: "全部",
  with_gap: "有缺口",
  no_gap: "无缺口",
  allowed: "可发布",
  blocked: "已阻断",
  multi: "多次出现",
  single: "单次出现",
  t_board_limit_up: "T字板",
  limit_up: "普通涨停",
  blocked_data_gap: "数据缺口阻断",
  memory_watch: "记忆观察",
  memory_active: "有效观察期",
  memory_reactivated: "二波已激活",
  valley_stabilization: "低谷企稳",
  horizontal_breakout_watch: "横盘突破观察",
  continuous_rebound_watch: "连续反弹观察",
  sample_insufficient: "样本不足",
  qualified: "合格",
  continue_watch: "继续观察",
  opportunity: "出现机会",
  data_wait: "等待数据",
  stopped: "停止观察",
  completed: "已完成",
  data_blocked: "数据阻断",
};

const SOURCE_QUALITY_LABELS = {
  usable: "可用",
  research_only: "仅研究",
  gap: "数据缺口",
  suspect: "待核验",
  stale: "已过期",
  rejected: "已拒绝",
  source_visible: "已读到标准事实",
};

const PROVIDER_LABELS = {
  ths: "同花顺",
  baostock: "证券宝行情",
  eastmoney: "东方财富",
  tencent: "腾讯行情",
  sohu: "搜狐行情",
  sina: "新浪行情",
  akshare: "开源行情",
  tushare: "专业行情",
  baidu: "百度股市",
  cninfo: "巨潮资讯",
  internal: "内部构建",
};

const STATUS_LABELS = {
  ready: "就绪",
  passed: "通过",
  blocked: "阻断",
  degraded: "降级",
  warning: "预警",
  failed: "失败",
  unavailable: "不可用",
  pending: "等待",
  waiting: "等待",
  succeeded: "成功",
  rejected: "已拒绝",
  empty: "空",
  usable: "可用",
  research_only: "仅研究",
  not_materialized: "未物化",
  source_visible: "已读到标准事实",
  blocked_data_gap: "数据缺口阻断",
  data_blocked: "数据阻断",
  not_ready: "尚未就绪",
  outcome_not_mature: "结果未成熟",
  pending_verification: "等待验证",
  data_gap: "数据缺口",
  entry_path_data_gap: "缺买入路径",
  buy_point_not_materialized: "买点未物化",
  reference_entry_missing: "缺评估基准",
  model_not_materialized: "模型结果未物化",
  verification_data_gap: "验证数据缺口",
  monitoring: "监控中",
  mixed_reactivation: "混合再激活",
  qualified: "合格",
  triggered: "已触发",
  not_near_limit: "未接近涨停",
  order_consumption_triggered: "盘口吃单触发",
  no_order_consumption: "未出现盘口吃单",
  board_open_failed: "开板失败",
  day2_board_open_after_entry_failed: "Day2触发后开板失败",
  hold_open_limit: "开盘涨停留存",
  no_exit_signal: "未触发退出",
  distribution_suspected: "分歧派发疑似",
  dominant_buy_suspected: "主买疑似",
  relay_success: "接力成功",
  relay_failed: "接力失败",
  D1: "第1日",
  D2: "第2日",
  D3: "第3日",
  D4_D5: "第4至第5日",
  D6_D8_HORIZONTAL_BREAKOUT: "第6至第8日横盘突破",
  D9_PLUS: "第9日以后",
  d1: "第1日",
  d2: "第2日",
  d3: "第3日",
  d4_d5: "第4至第5日",
  d6_d8_horizontal_breakout: "第6至第8日横盘突破",
  d9_plus: "第9日以后",
  UNKNOWN: "未知",
  unknown: "未知",
  sample_insufficient: "样本不足",
  valley_stabilization: "低谷企稳",
  horizontal_breakout_watch: "横盘突破观察",
  continuous_rebound_watch: "连续反弹观察",
  unreviewed: "未标注",
  positive_valley: "正样本低谷",
  near_miss: "近似命中",
  false_bottom: "假低谷",
  hard_negative: "硬负样本",
  invalid_data: "数据无效",
  high: "高",
  medium: "中",
  low: "低",
  not_t_board: "非T字板",
  not_triggered: "未触发",
  day1_not_qualified: "首日未合格",
  float_market_cap_out_of_range: "流通市值不在范围内",
  sealed_to_close: "封至收盘",
  exit_tail_no_limit: "尾盘未涨停退出",
  t_board_relay_strong_success: "接力强成功",
  exit_required: "需要退出",
};

const GAP_CODE_LABELS = {
  "source_gap:hot_decision_list_not_materialized": "缺口：热点决策列表未物化",
  "source_gap:hot_signal_not_materialized": "缺口：热点信号未物化",
  "source_gap:ths_paid_probability_missing": "缺口：同花顺付费概率缺失",
  "source_gap:memory_entity_not_materialized": "缺口：候选记忆实体未物化",
  "source_gap:ambush_decision_list_not_materialized": "缺口：潜伏抬头决策列表未物化",
  "source_gap:model_score_not_materialized": "缺口：模型分未物化",
  "source_gap:buy_point_not_materialized": "缺口：买点未物化",
  "source_gap:reference_entry_price_not_materialized": "缺口：评估基准价未物化",
  "source_gap:outcome_not_materialized": "缺口：收益验证未物化",
  "source_gap:ambush_label_repository_missing": "缺口：潜伏图库标注仓库未接入",
  "source_gap:seal_order_snapshot_missing": "缺口：封单快照缺失",
  "source_gap:dynamic_feature_bundle_missing": "缺口：动态特征包缺失",
  "source_gap:near_limit_order_absorption_missing": "缺口：近涨停盘口吸收缺失",
  "source_gap:daily_bar_join_missing": "缺口：日线关联缺失",
  "source_gap:daily_bar_same_day_missing": "缺口：同日行情未发布",
  "source_gap:stock_moneyflow_join_missing": "缺口：资金流关联缺失",
  "source_gap:stock_moneyflow_same_day_missing": "缺口：同日资金流未发布",
  "source_gap:missing_trading_calendar_memory_age": "缺口：交易日历记忆年龄缺失",
  "source_gap:daily_bar_history_insufficient": "缺口：低谷日线历史不足",
  "source_gap:moneyflow_context_missing": "缺口：资金上下文缺失",
};

const state = {
  route: normalizeRoute(location.hash),
  user: null,
  authEpoch: 0,
  modelTboardRefreshTimer: null,
  adminBoardRefreshTimer: null,
  modelReviewFilters: {},
  modelReviewRows: {},
  modelReviewExtras: {},
  modelReviewErrors: {},
  modelReviewRefreshState: {},
  modelListChromeCleanup: null,
  candidateRows: [],
  candidateSource: {
    loaded: false,
    loading: false,
    tradeDate: null,
    sourceRows: [],
    allEventRows: [],
    preferredTradeDate: PREFERRED_CANDIDATE_TRADE_DATE,
    preferredTradeDateLoaded: false,
    fallbackTradeDate: null,
    sourceReadState: "waiting",
    dailyRows: [],
    limitPriceRows: [],
    moneyflowRows: [],
    paidProbabilityRows: [],
    paidProbabilityCookieStatus: null,
    paidProbabilityBatchStatus: null,
    paidProbabilityError: null,
    enrichmentError: null,
    error: null,
  },
  adminBoard: {
    tradeDate: null,
    data: null,
    task: null,
    loading: false,
    error: null,
    detailLoading: false,
    detailError: null,
    detailsOpen: false,
  },
  ambushValley: {
    loaded: false,
    loading: false,
    cases: [],
    taxonomy: [],
    selectedCaseId: null,
    labelMode: "as_of",
    error: null,
  },
};

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  })[char]);
}

function normalizeRoute(hash) {
  const key = String(hash || "").replace(/^#\/?/, "") || "candidates";
  return OPEN_ROUTES.some((item) => item.key === key) ? key : "candidates";
}

function isAdminUser() {
  return String(state.user?.role || "").toLowerCase() === "admin";
}

function canSeeRoute(route) {
  return !route.requiresRole || String(route.requiresRole).toLowerCase() === String(state.user?.role || "").toLowerCase();
}

function visibleRoutes() {
  return OPEN_ROUTES.filter(canSeeRoute);
}

async function api(path, options = {}) {
  const timeoutMs = Number(options.timeoutMs || FRONTEND_DEFAULT_TIMEOUT_MS);
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  const { timeoutMs: _ignoredTimeoutMs, headers, ...fetchOptions } = options;
  try {
    const response = await fetch(path, {
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", ...(headers || {}) },
      signal: controller.signal,
      ...fetchOptions,
    });
    const text = await response.text();
    const body = text ? JSON.parse(text) : null;
    if (!response.ok) {
      const message = body?.detail || body?.message || response.statusText;
      throw new Error(message);
    }
    return body;
  } catch (error) {
    if (error.name === "AbortError") {
      const friendly = new Error("读取超时，请稍后重试。");
      friendly.code = "frontend_timeout";
      throw friendly;
    }
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }
}

async function backend(service, path, timeoutMs = FRONTEND_DEFAULT_TIMEOUT_MS) {
  return api(`/api/backend/${service}/${path.replace(/^\/+/, "")}`, { method: "GET", timeoutMs });
}

async function researchApi(path, options = {}) {
  const method = options.method || "GET";
  const body = options.body ? JSON.stringify(options.body) : undefined;
  return api(`/api/research/${path.replace(/^\/+/, "")}`, {
    method,
    body,
    timeoutMs: options.timeoutMs || FRONTEND_DEFAULT_TIMEOUT_MS,
  });
}

async function sourcePaidProbabilityApi(path, options = {}) {
  const method = options.method || "GET";
  const body = options.body ? JSON.stringify(options.body) : undefined;
  return api(`/api/source/ths/paid-probability/${path.replace(/^\/+/, "")}`, {
    method,
    body,
    timeoutMs: options.timeoutMs || FRONTEND_DEFAULT_TIMEOUT_MS,
  });
}

const AMBUSH_VALLEY_FORM_KEYS = {
  stockCode: "research_stock_code",
  stockName: "research_stock_name",
  sampleDate: "research_sample_date",
  valleyLowDate: "research_valley_low_date",
  turnDate: "research_turn_date",
  structure: "research_structure_judgement",
  timing: "research_turn_timing",
  role: "research_sample_role",
  outcome: "research_outcome_reason",
  confidence: "research_label_confidence",
  note: "research_label_note",
  tags: "research_label_tags",
};

function setAuthState(authState) {
  document.body.dataset.authState = authState;
  const loginRoot = $("#login-root");
  if (loginRoot) {
    const authenticated = authState === "authenticated";
    loginRoot.classList.toggle("is-hidden", authenticated);
    loginRoot.setAttribute("aria-hidden", authenticated ? "true" : "false");
  }
}

function bindLogin() {
  const form = $("#login-form");
  if (!form) return;
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const authEpoch = ++state.authEpoch;
    const message = $("#login-message");
    const payload = {
      username: $("#login-username")?.value?.trim(),
      password: $("#login-password")?.value || "",
    };
    try {
      if (message) message.textContent = "正在校验账号...";
      const result = await api("/api/auth/login", { method: "POST", body: JSON.stringify(payload) });
      if (authEpoch !== state.authEpoch) return;
      state.user = result.user;
      clearAdminBoardRequestCache();
      setAuthState("authenticated");
      if (message) message.textContent = "";
      if (!location.hash) {
        location.hash = "#/candidates";
        return;
      }
      renderApp();
    } catch (error) {
      if (authEpoch !== state.authEpoch) return;
      if (message) message.textContent = "";
    }
  });
}

async function loadSession() {
  const authEpoch = state.authEpoch;
  try {
    const session = await api("/api/auth/session");
    if (authEpoch !== state.authEpoch) return;
    if (session.authenticated) {
      state.user = session.user;
      clearAdminBoardRequestCache();
      setAuthState("authenticated");
      renderApp();
    } else {
      setAuthState("anonymous");
    }
  } catch {
    if (authEpoch !== state.authEpoch) return;
    setAuthState("anonymous");
    const message = $("#login-message");
      if (message) message.textContent = "";
  }
}

async function logout() {
  state.authEpoch += 1;
  clearTBoardAutoRefresh();
  clearAdminBoardAutoRefresh();
  clearAdminBoardRequestCache();
  try { await api("/api/auth/logout", { method: "POST", body: "{}" }); } catch {}
  state.user = null;
  setAuthState("anonymous");
  $("#app-root").innerHTML = "";
}

function renderApp() {
  state.route = normalizeRoute(location.hash);
  state.pageEpoch = (state.pageEpoch || 0) + 1;
  clearTBoardAutoRefresh();
  clearAdminBoardAutoRefresh();
  clearModelListChrome();
  const route = OPEN_ROUTES.find((item) => item.key === state.route) || OPEN_ROUTES[0];
  const isModelRoute = Boolean(MODEL_PROFILES[state.route]);
  $("#app-root").innerHTML = `
    <div class="app-shell">
      ${renderSidebar()}
      <main class="main-shell">
        ${isModelRoute ? "" : renderHeader(route)}
        <section id="page-root" class="page-root"><div class="panel"><strong>正在读取真实接口数据...</strong></div></section>
      </main>
    </div>`;
  bindShellActions();
  const pageEpoch = state.pageEpoch;
  const routeKey = state.route;
  renderPage(pageEpoch, routeKey).catch((error) => {
    if (isStalePage(pageEpoch, routeKey)) return;
    renderPageError(error);
  });
}

function renderSidebar() {
  const grouped = visibleRoutes().reduce((acc, item) => {
    (acc[item.group] ||= []).push(item);
    return acc;
  }, {});
  return `<aside class="sidebar">
    <div class="sidebar-brand">
      <div class="brand-mark" aria-hidden="true"><span></span><span></span></div>
      <div><strong>神策中心</strong><small>锁定后端只读前端</small></div>
    </div>
    ${Object.entries(grouped).map(([group, items]) => `
      <nav class="nav-group" aria-label="${escapeHtml(group)}">
        <div class="nav-group-title">${escapeHtml(group)}</div>
        ${items.map((item) => `<a class="nav-link nav-item ${item.key === state.route ? "is-active" : ""}" href="${item.hash}"><span class="nav-item__icon">${escapeHtml(item.icon)}</span><b>${escapeHtml(item.label)}</b></a>`).join("")}
      </nav>`).join("")}
    <div class="sidebar-footer">
      <span>${escapeHtml(userDisplayName(state.user?.username))} · ${escapeHtml(userRoleLabel(state.user?.role))}</span>
      <button class="ghost-button sidebar-logout" data-action="logout">退出登录</button>
    </div>
  </aside>`;
}

function userDisplayName(username) {
  const text = String(username || "").trim();
  if (!text) return "-";
  if (text.toLowerCase() === "admin") return "管理员";
  return text;
}

function userRoleLabel(role) {
  const key = String(role || "").trim().toLowerCase();
  const labels = {
    admin: "管理员",
    operator: "操作员",
    viewer: "观察员",
  };
  return labels[key] || (key ? "用户" : "-");
}

function renderHeader(route) {
  return `<header class="topbar">
    <div><h1>${escapeHtml(route.label)}</h1><p>当前开放候选输入、四个模型页和模型三低谷图库；页面只读生产事实，研究标注只写研究资产。</p></div>
    <div class="topbar-actions"><span class="status-pill status-ready">后端锁定只读</span></div>
  </header>`;
}

function bindShellActions() {
  $$("[data-action='logout']").forEach((button) => button.addEventListener("click", logout));
}

function isStalePage(pageEpoch, routeKey) {
  return pageEpoch !== state.pageEpoch || routeKey !== state.route;
}

function clearTBoardAutoRefresh() {
  if (!state.modelTboardRefreshTimer) return;
  window.clearTimeout(state.modelTboardRefreshTimer);
  state.modelTboardRefreshTimer = null;
}

function clearModelListChrome() {
  if (typeof state.modelListChromeCleanup !== "function") return;
  state.modelListChromeCleanup();
  state.modelListChromeCleanup = null;
}

function scheduleTBoardAutoRefresh(pageEpoch, routeKey) {
  clearTBoardAutoRefresh();
  if (routeKey !== "model-tboard" || !state.user || isStalePage(pageEpoch, routeKey)) return;
  state.modelTboardRefreshTimer = window.setTimeout(() => {
    state.modelTboardRefreshTimer = null;
    if (state.route !== "model-tboard" || !state.user) return;
    if (document.hidden) {
      scheduleTBoardAutoRefresh(state.pageEpoch, "model-tboard");
      return;
    }
    renderModelPage(MODEL_PROFILES["model-tboard"], { pageEpoch: state.pageEpoch, routeKey: "model-tboard", silentRefresh: true }).catch((error) => {
      if (isStalePage(state.pageEpoch, "model-tboard")) return;
      if (Array.isArray(state.modelReviewRows.tboard)) {
        state.modelReviewErrors.tboard = [frontendErrorLabel(error)];
        state.modelReviewRefreshState.tboard = { status: "error", message: "刷新失败，已保留上次结果" };
        if (!patchModelPageFromState(MODEL_PROFILES["model-tboard"], state.pageEpoch, "model-tboard")) {
          renderModelPage(MODEL_PROFILES["model-tboard"], { pageEpoch: state.pageEpoch, routeKey: "model-tboard", useCachedRows: true });
        }
      } else {
        renderPageError(error);
      }
      scheduleTBoardAutoRefresh(state.pageEpoch, "model-tboard");
    });
  }, TBOARD_AUTO_REFRESH_MS);
}

function clearAdminBoardAutoRefresh() {
  if (!state.adminBoardRefreshTimer) return;
  window.clearTimeout(state.adminBoardRefreshTimer);
  state.adminBoardRefreshTimer = null;
}

function scheduleAdminBoardAutoRefresh(pageEpoch, routeKey) {
  clearAdminBoardAutoRefresh();
  if (routeKey !== "admin-ops" || !state.user || !isAdminUser() || isStalePage(pageEpoch, routeKey)) return;
  state.adminBoardRefreshTimer = window.setTimeout(() => {
    state.adminBoardRefreshTimer = null;
    if (state.route !== "admin-ops" || !state.user || !isAdminUser()) return;
    if (document.hidden) {
      scheduleAdminBoardAutoRefresh(state.pageEpoch, "admin-ops");
      return;
    }
    renderAdminOpsPage({ pageEpoch: state.pageEpoch, routeKey: "admin-ops", silentRefresh: true }).catch((error) => {
      if (isStalePage(state.pageEpoch, "admin-ops")) return;
      state.adminBoard.error = frontendErrorLabel(error);
      const status = $("[data-admin-refresh-status]");
      if (status) status.textContent = `刷新失败，保留上次看板：${state.adminBoard.error}`;
      scheduleAdminBoardAutoRefresh(state.pageEpoch, "admin-ops");
    });
  }, ADMIN_DASHBOARD_REFRESH_MS);
}

function adminBoardDefaultTradeDate() {
  try {
    const parts = new Intl.DateTimeFormat("zh-CN", {
      timeZone: "Asia/Shanghai",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).formatToParts(new Date()).reduce((acc, part) => ({ ...acc, [part.type]: part.value }), {});
    return `${parts.year}-${parts.month}-${parts.day}`;
  } catch {
    return new Date().toISOString().slice(0, 10);
  }
}

const adminBoardRequestCache = new Map();
const adminBoardRequestInflight = new Map();

function clearAdminBoardRequestCache() {
  adminBoardRequestCache.clear();
  adminBoardRequestInflight.clear();
}

function adminBoardCacheKey(kind, tradeDate) {
  return `${kind}:${tradeDate || adminBoardDefaultTradeDate()}`;
}

async function loadAdminBoardEndpoint(kind, tradeDate, path, timeoutMs, options = {}) {
  const key = adminBoardCacheKey(kind, tradeDate);
  const pending = adminBoardRequestInflight.get(key);
  if (pending) return pending;
  const cached = adminBoardRequestCache.get(key);
  if (!options.force && cached && cached.expiresAt > Date.now()) return cached.payload;
  const request = api(path, { method: "GET", timeoutMs })
    .then((payload) => {
      adminBoardRequestCache.set(key, { payload, expiresAt: Date.now() + ADMIN_BOARD_CACHE_TTL_MS });
      return payload;
    })
    .finally(() => adminBoardRequestInflight.delete(key));
  adminBoardRequestInflight.set(key, request);
  return request;
}

function buildAdminDailyBoardShell(task, tradeDate, detailState = "idle", error = null) {
  return {
    contract_kind: "shence_admin_daily_data_board_deferred_v1",
    read_only: true,
    role_required: "admin",
    trade_date: task?.trade_date || tradeDate || adminBoardDefaultTradeDate(),
    generated_at: task?.generated_at || null,
    refresh_interval_seconds: task?.refresh_interval_seconds || ADMIN_DASHBOARD_REFRESH_MS / 1000,
    summary: {
      queue: task?.summary?.queue || {},
      detail_state: detailState,
      detail_message: error ? frontendErrorLabel(error) : "",
    },
    assets: [],
    gaps: [],
    upstream_status: error ? { daily_board_detail: { status: "unavailable", message: frontendErrorLabel(error) } } : {},
  };
}

function adminDailyBoardLoaded(data) {
  return data?.contract_kind === "shence_admin_daily_data_board_v1";
}

async function loadAdminTaskBoard(tradeDate, options = {}) {
  const query = tradeDate ? `?trade_date=${encodeURIComponent(tradeDate)}` : "";
  return loadAdminBoardEndpoint(
    "task-board",
    tradeDate,
    `/api/admin/task-board${query}`,
    ADMIN_DASHBOARD_REQUEST_TIMEOUT_MS,
    options,
  );
}

async function loadAdminDailyBoardDetail(tradeDate, options = {}) {
  const query = tradeDate ? `?trade_date=${encodeURIComponent(tradeDate)}` : "";
  return loadAdminBoardEndpoint(
    "daily-board",
    tradeDate,
    `/api/admin/daily-board${query}`,
    ADMIN_DAILY_BOARD_OPTIONAL_TIMEOUT_MS,
    options,
  );
}

async function loadAdminBoardData(tradeDate, options = {}) {
  const task = await loadAdminTaskBoard(tradeDate, options);
  const resolvedTradeDate = task?.trade_date || tradeDate || adminBoardDefaultTradeDate();
  return { data: buildAdminDailyBoardShell(task, resolvedTradeDate), task };
}

async function renderAdminOpsPage(options = {}) {
  const pageEpoch = options.pageEpoch ?? state.pageEpoch;
  const routeKey = options.routeKey ?? "candidates";
  const root = $("#page-root");
  if (!root || isStalePage(pageEpoch, routeKey)) return;
  if (!isAdminUser()) {
    root.innerHTML = `<section class="notice-bar notice-bar--inline"><strong>无权限</strong><span>只有 admin 账户可以查看数据和任务看板。</span></section>`;
    return;
  }
  const tradeDate = state.adminBoard.tradeDate || adminBoardDefaultTradeDate();
  if (!options.silentRefresh) {
    root.innerHTML = `<section class="panel"><strong>\u6b63\u5728\u8bfb\u53d6\u6570\u636e\u4efb\u52a1\u770b\u677f...</strong><span>\u7b49\u5f85\u6e90\u6570\u636e\u4e0e\u8c03\u5ea6\u8d26\u672c\u8fd4\u56de\uff0c\u4e0d\u4f7f\u7528\u5176\u4ed6\u9875\u9762\u6587\u6848\u3002</span></section>`;
  }
  state.adminBoard.loading = true;
  try {
    const keepDetailsOpen = Boolean(state.adminBoard.detailsOpen);
    const { data, task } = await loadAdminBoardData(tradeDate, { force: Boolean(options.forceRefresh) });
    if (isStalePage(pageEpoch, routeKey)) return;
    const resolvedTradeDate = data?.trade_date || task?.trade_date || tradeDate;
    state.adminBoard = { tradeDate: resolvedTradeDate, data, task, loading: false, error: null, detailLoading: false, detailError: null, detailsOpen: keepDetailsOpen };
    root.innerHTML = renderAdminOpsWorkbench(data, task);
    bindAdminOpsActions(pageEpoch, routeKey);
    scheduleAdminBoardAutoRefresh(pageEpoch, routeKey);
    if (state.adminBoard.detailsOpen && !adminDailyBoardLoaded(state.adminBoard.data)) {
      hydrateAdminDailyBoard(pageEpoch, routeKey, { force: Boolean(options.forceRefresh) }).catch(() => {});
    }
  } catch (error) {
    if (isStalePage(pageEpoch, routeKey)) return;
    state.adminBoard.loading = false;
    state.adminBoard.error = frontendErrorLabel(error);
    if (options.silentRefresh && state.adminBoard.data && state.adminBoard.task) {
      const status = $("[data-admin-refresh-status]");
      if (status) status.textContent = `刷新失败，保留上次看板：${state.adminBoard.error}`;
      scheduleAdminBoardAutoRefresh(pageEpoch, routeKey);
      return;
    }
    renderPageError(error);
  }
}

async function hydrateAdminDailyBoard(pageEpoch, routeKey, options = {}) {
  const root = $("#page-root");
  if (!root || isStalePage(pageEpoch, routeKey)) return;
  if (state.adminBoard.detailLoading || adminDailyBoardLoaded(state.adminBoard.data)) return;
  const tradeDate = state.adminBoard.tradeDate || adminBoardDefaultTradeDate();
  const task = state.adminBoard.task;
  state.adminBoard = {
    ...state.adminBoard,
    data: buildAdminDailyBoardShell(task, tradeDate, "loading"),
    detailLoading: true,
    detailError: null,
    detailsOpen: true,
  };
  root.innerHTML = renderAdminOpsWorkbench(state.adminBoard.data, task);
  bindAdminOpsActions(pageEpoch, routeKey);
  try {
    const data = await loadAdminDailyBoardDetail(tradeDate, options);
    if (isStalePage(pageEpoch, routeKey)) return;
    state.adminBoard = { ...state.adminBoard, data, detailLoading: false, detailError: null, detailsOpen: true };
  } catch (error) {
    if (isStalePage(pageEpoch, routeKey)) return;
    state.adminBoard = {
      ...state.adminBoard,
      data: buildAdminDailyBoardShell(task, tradeDate, "error", error),
      detailLoading: false,
      detailError: frontendErrorLabel(error),
      detailsOpen: true,
    };
  }
  root.innerHTML = renderAdminOpsWorkbench(state.adminBoard.data, state.adminBoard.task);
  bindAdminOpsActions(pageEpoch, routeKey);
}

function renderAdminOpsWorkbench(data, task) {
  const dataSummary = data?.summary || {};
  const taskSummary = task?.summary || {};
  const queue = dataSummary.queue || taskSummary.queue || {};
  const tradeDate = data?.trade_date || task?.trade_date || state.adminBoard.tradeDate || adminBoardDefaultTradeDate();
  const refreshSeconds = Number(data?.refresh_interval_seconds || task?.refresh_interval_seconds || ADMIN_DASHBOARD_REFRESH_MS / 1000);
  const upstream = { ...(data?.upstream_status || {}), ...(task?.upstream_status || {}) };
  const assets = data?.assets || [];
  const tasks = task?.tasks || [];
  const gaps = data?.gaps || [];
  const blocks = buildAdminDataBlockSummary(assets, tasks, gaps);
  return `<section class="admin-board admin-board--summary" data-admin-board="true">
    <div class="admin-board-toolbar panel">
      <div>
        <strong>今日任务看板 ${escapeHtml(tradeDate)}</strong>
        <span data-admin-refresh-status>每 ${Math.max(Math.round(refreshSeconds / 60), 1)} 分钟自动刷新；生成 ${escapeHtml(formatDateTimeValue(data?.generated_at || task?.generated_at))}</span>
      </div>
      <div class="admin-board-actions">
        <label class="admin-board-date"><span>日期</span><input id="admin-board-date" type="date" value="${escapeHtml(tradeDate)}"></label>
        <button class="secondary-button" data-action="reload-admin-board">刷新</button>
      </div>
    </div>
    ${renderAdminCoverageAlert(dataSummary, upstream)}
    ${renderAdminCompletionOverview(dataSummary, taskSummary, queue, blocks)}
    ${renderAdminDataBlockBoard(blocks)}
    ${renderAdminExceptionList(blocks)}
    <section class="admin-audit-compact panel">
      <strong>规划与差异对比</strong>
      <span>${escapeHtml(display(tasks.length, "0"))} 条任务已折叠为上方计数，不逐条铺开；需要排查时再展开只读审计明细。</span>
    </section>
    ${renderAdminAuditDetails(data, tasks, assets, gaps, dataSummary)}
    <div class="admin-upstream-strip">${renderAdminUpstreamStatus(upstream)}</div>
  </section>`;
}

function renderAdminAuditDetails(data, tasks, assets, gaps, dataSummary) {
  const openAttr = state.adminBoard.detailsOpen ? " open" : "";
  const loaded = adminDailyBoardLoaded(data);
  if (!loaded) {
    const detailState = state.adminBoard.detailLoading ? "loading" : state.adminBoard.detailError ? "error" : (dataSummary?.detail_state || "idle");
    const message = detailState === "loading"
      ? "\u6b63\u5728\u8bfb\u53d6\u6570\u636e\u8d44\u4ea7\u660e\u7ec6..."
      : detailState === "error"
        ? `\u6570\u636e\u8d44\u4ea7\u660e\u7ec6\u8bfb\u53d6\u5931\u8d25\uff1a${display(state.adminBoard.detailError || dataSummary?.detail_message)}`
        : "\u5c55\u5f00\u540e\u8bfb\u53d6\u6570\u636e\u8d44\u4ea7\u660e\u7ec6\uff1b\u4e3b\u770b\u677f\u5df2\u6309\u4efb\u52a1\u770b\u677f\u5c55\u793a\u3002";
    return `<details class="admin-audit-details" data-admin-audit-details="true"${openAttr}>
      <summary>\u5c55\u5f00\u5ba1\u8ba1\u660e\u7ec6</summary>
      <section class="admin-board-panel panel" data-admin-detail-placeholder="true">
        <div class="panel__head"><h2 class="panel-title">\u6570\u636e\u8d44\u4ea7\u660e\u7ec6</h2><span>\u6309\u9700\u8bfb\u53d6</span></div>
        <div class="admin-empty-state">${escapeHtml(message)}</div>
      </section>
    </details>`;
  }
  return `<details class="admin-audit-details" data-admin-audit-details="true"${openAttr}>
      <summary>\u5c55\u5f00\u5ba1\u8ba1\u660e\u7ec6</summary>
      <section class="admin-board-panel panel">
        <div class="panel__head"><h2 class="panel-title">\u6570\u636e\u8d44\u4ea7\u660e\u7ec6</h2><span>\u9a8c\u6536\u6279\u6b21 ${escapeHtml(display(dataSummary.latest_inspection_run_id))} \u00b7 ${escapeHtml(formatDateTimeValue(dataSummary.latest_inspection_finished_at))}</span></div>
        ${renderAdminAssetTable(assets)}
      </section>
      <section class="admin-board-panel panel">
        <div class="panel__head"><h2 class="panel-title">\u4efb\u52a1\u660e\u7ec6\u5df2\u6c47\u603b</h2><span>${escapeHtml(display(tasks.length, "0"))} \u6761\u4efb\u52a1\u5df2\u6298\u53e0\u4e3a\u4e0a\u65b9\u8ba1\u6570\uff0c\u4e0d\u9010\u6761\u94fa\u5f00\u3002</span></div>
        <div class="admin-empty-state">\u9700\u8981\u9010\u6761\u6392\u67e5\u65f6\u518d\u8bfb\u53d6\u540e\u7aef\u63a5\u53e3\uff1b\u9ed8\u8ba4\u9875\u9762\u53ea\u5c55\u793a\u4eca\u65e5\u751f\u547d\u5468\u671f\u805a\u5408\u7ed3\u679c\u3002</div>
      </section>
      <section class="admin-board-panel panel">
        <div class="panel__head"><h2 class="panel-title">\u7f3a\u53e3\u660e\u7ec6</h2><span>${escapeHtml(display(gaps.length, "0"))} \u6761</span></div>
        ${renderAdminGapTable(gaps)}
      </section>
    </details>`;
}

function renderAdminCoverageAlert(dataSummary, upstream) {
  const inspection = dataSummary?.inspection_coverage || {};
  if (inspection.covered === true) return "";
  const message = dataSummary?.inspection_message || dataSummary?.message || upstream?.daily_acceptance?.message || "完整性验收还未生成，任务完成度仍以调度账本和数据产出为准。";
  const label = "完整性验收未生成";
  return `<section class="admin-coverage-alert panel admin-coverage-alert--warn">
    <strong>${escapeHtml(label)}</strong>
    <span>${escapeHtml(message)}</span>
  </section>`;
}

function renderAdminCompletionOverview(dataSummary, taskSummary, queue, blocks) {
  const totalTasks = Number(taskSummary.total_tasks || 0);
  const completedTasks = Number(taskSummary.completed_tasks ?? taskSummary.built_tasks ?? 0);
  const unfinishedTasks = Number(taskSummary.unfinished_tasks ?? Math.max(totalTasks - completedTasks, 0));
  const schedulerCompletedTasks = Number(taskSummary.scheduler_completed_tasks ?? completedTasks);
  const schedulerDueTasks = Number(taskSummary.scheduler_due_tasks ?? 0);
  const schedulerNotDueTasks = Number(taskSummary.scheduler_not_due_tasks ?? taskSummary.not_due_tasks ?? 0);
  const waitingTasks = Number(taskSummary.waiting_collection_tasks ?? taskSummary.not_due_tasks ?? schedulerNotDueTasks);
  const collectingTasks = Number(taskSummary.collecting_tasks ?? taskSummary.queue_active_tasks ?? 0);
  const awaitingDispatchTasks = Number(taskSummary.awaiting_dispatch_tasks || 0);
  const awaitingEvidenceTasks = Number(taskSummary.awaiting_evidence_tasks || 0);
  const expiredClosedTasks = Number(taskSummary.expired_closed_tasks || 0);
  const executionFailedTasks = Number(taskSummary.execution_failed_tasks || 0);
  const processingTasks = awaitingDispatchTasks + awaitingEvidenceTasks + collectingTasks;
  const dataFailedJobs = Number(taskSummary.data_failed_jobs || 0);
  const rawAuditWarnings = Number(taskSummary.raw_audit_warning_table_count || dataSummary.raw_audit_warning_table_count || 0);
  const failedTasks = Number(taskSummary.failed_tasks ?? (executionFailedTasks + dataFailedJobs));
  const repairableFailed = Number(taskSummary.repairable_failed_tasks || 0);
  const unrepairableFailed = Number(taskSummary.unrepairable_failed_tasks || 0);
  const contractPendingFailed = Number(taskSummary.contract_pending_failed_tasks || 0);
  const sourceFactsAvailable = taskSummary.source_facts_available !== false;
  const sourceRowsRaw = taskSummary.source_row_count ?? dataSummary.source_row_count;
  const sourceRows = sourceFactsAvailable && sourceRowsRaw !== null && sourceRowsRaw !== undefined ? Number(sourceRowsRaw) : null;
  const rawWaitingJobs = sourceFactsAvailable && taskSummary.raw_waiting_jobs !== null && taskSummary.raw_waiting_jobs !== undefined ? Number(taskSummary.raw_waiting_jobs) : null;
  const rawActiveJobs = sourceFactsAvailable && taskSummary.raw_active_jobs !== null && taskSummary.raw_active_jobs !== undefined ? Number(taskSummary.raw_active_jobs) : null;
  const rawCancelledJobs = sourceFactsAvailable && taskSummary.raw_cancelled_jobs !== null && taskSummary.raw_cancelled_jobs !== undefined ? Number(taskSummary.raw_cancelled_jobs) : null;
  const latestDataUpdate = sourceFactsAvailable ? (taskSummary.latest_data_update_at || dataSummary.latest_data_update_at) : null;
  const completionPct = totalTasks > 0 ? Math.round((completedTasks / totalTasks) * 100) : null;
  const tone = !sourceFactsAvailable ? "danger" : failedTasks ? "danger" : waitingTasks || processingTasks || expiredClosedTasks || rawAuditWarnings ? "warn" : "ok";
  const completionText = !sourceFactsAvailable ? "\u5f85\u5224\u5b9a" : completionPct === null ? "-" : `${completionPct}%`;
  const schedulerSub = schedulerDueTasks
    ? `\u8c03\u5ea6\u8d26\u672c\u5df2\u5904\u7406 ${display(schedulerCompletedTasks, "0")} / \u5df2\u5230\u65f6\u95f4 ${display(schedulerDueTasks, "0")}\uff1b`
    : schedulerCompletedTasks
      ? `\u8c03\u5ea6\u8d26\u672c\u5df2\u5904\u7406 ${display(schedulerCompletedTasks, "0")}\uff1b`
      : "";
  const rawSub = rawWaitingJobs || rawActiveJobs
    ? `\u4eca\u65e5\u539f\u59cb\u6293\u53d6\u7b49\u5f85 ${display(rawWaitingJobs, "0")}\u3001\u5904\u7406\u4e2d ${display(rawActiveJobs, "0")}\uff1b`
    : "";
  const expiredSub = expiredClosedTasks ? `\u5df2\u8fc7\u671f\u5173\u95ed ${display(expiredClosedTasks, "0")}\uff1b` : "";
  const completionSub = !sourceFactsAvailable
    ? `\u6e90\u6570\u636e\u6682\u4e0d\u53ef\u8bfb\uff0c\u4eca\u65e5\u5b8c\u6210\u5ea6\u4e0d\u80fd\u6309\u8c03\u5ea6\u8d26\u672c\u62cd\u677f\uff1b${schedulerSub}\u6682\u5217\u672a\u5b8c\u6210 ${display(unfinishedTasks, "0")} \u9879`
    : `${schedulerSub}${rawSub}${expiredSub}\u6700\u7ec8\u6570\u636e\u5b8c\u6210 ${display(completedTasks, "0")} / \u4eca\u65e5\u8ba1\u5212 ${display(totalTasks, "0")}\uff1b\u672a\u5b8c\u6210 ${display(unfinishedTasks, "0")}`;
  const lifecycleReasons = [];
  if (!sourceFactsAvailable) lifecycleReasons.push({ reason: "\u6e90\u6570\u636e\u6682\u4e0d\u53ef\u8bfb", count: unfinishedTasks });
  if (schedulerCompletedTasks > completedTasks) lifecycleReasons.push({ reason: "\u8c03\u5ea6\u5df2\u5904\u7406\uff0c\u7b49\u5f85\u6700\u7ec8\u6570\u636e", count: schedulerCompletedTasks - completedTasks });
  if (rawWaitingJobs) lifecycleReasons.push({ reason: "\u539f\u59cb\u6293\u53d6\u7b49\u5f85", count: rawWaitingJobs });
  if (waitingTasks) lifecycleReasons.push({ reason: "未到抓取时间", count: waitingTasks });
  if (awaitingDispatchTasks) lifecycleReasons.push({ reason: "待提交抓取", count: awaitingDispatchTasks });
  if (awaitingEvidenceTasks) lifecycleReasons.push({ reason: "等待数据结果", count: awaitingEvidenceTasks });
  if (collectingTasks) lifecycleReasons.push({ reason: "等待抓取/产出", count: collectingTasks });
  if (expiredClosedTasks) lifecycleReasons.push({ reason: "\u5df2\u8fc7\u671f\u5173\u95ed", count: expiredClosedTasks });
  if (executionFailedTasks) lifecycleReasons.push({ reason: "\u8c03\u5ea6\u6267\u884c\u5931\u8d25", count: executionFailedTasks });
  if (dataFailedJobs) lifecycleReasons.push({ reason: "\u6570\u636e\u4ea7\u51fa\u5931\u8d25", count: dataFailedJobs });
  if (rawAuditWarnings) lifecycleReasons.push({ reason: "\u91c7\u96c6\u5ba1\u8ba1\u544a\u8b66", count: rawAuditWarnings });
  const failedSub = failedTasks
    ? `\u53ef\u8865 ${display(repairableFailed, "0")} \u00b7 \u4e0d\u53ef\u8865 ${display(unrepairableFailed, "0")} \u00b7 \u5f85\u786e\u8ba4 ${display(contractPendingFailed, "0")}`
    : rawAuditWarnings
      ? `\u91c7\u96c6\u5ba1\u8ba1\u544a\u8b66 ${display(rawAuditWarnings, "0")}\uff0c\u4e0d\u8ba1\u5931\u8d25`
      : "\u6682\u65e0\u5931\u8d25\u4efb\u52a1\u6216\u5931\u8d25\u6570\u636e";
  return `<section class="admin-overview panel admin-overview--${escapeClass(tone)}">
    <div class="admin-overview-main">
      <span>\u4eca\u65e5\u6570\u636e\u4efb\u52a1\u770b\u677f\uff1a\u53ea\u6309\u771f\u5b9e\u6e90\u6570\u636e\u548c\u8c03\u5ea6\u8d26\u672c\u5224\u5b9a\u5b8c\u6210\u5ea6\u3002</span>
      <strong>${escapeHtml(completionText)}</strong>
      <small>${escapeHtml(completionSub)}</small>
      <div class="admin-progress admin-progress--${escapeClass(tone)}"><span style="width:${completionPct === null ? 0 : Math.max(0, Math.min(completionPct, 100))}%"></span></div>
    </div>
    <div class="admin-overview-grid admin-overview-grid--daily">
      ${renderAdminStackMetric("今日计划任务", totalTasks, "按日周期应执行", "neutral")}
      ${renderAdminStackMetric("\u8c03\u5ea6\u5df2\u5904\u7406", schedulerCompletedTasks, schedulerDueTasks ? `\u5df2\u5230\u65f6\u95f4 ${display(schedulerDueTasks, "0")}\uff1b\u672a\u5230\u65f6\u95f4 ${display(schedulerNotDueTasks, "0")}` : "\u8c03\u5ea6\u8d26\u672c\u5df2\u63d0\u4ea4\u6216\u53bb\u91cd", schedulerCompletedTasks ? "ok" : "neutral")}
      ${renderAdminStackMetric("\u6700\u7ec8\u5b8c\u6210", completedTasks, "\u53ea\u8ba1\u76ee\u6807 source \u6570\u636e\u5df2\u4ea7\u51fa", completedTasks ? "ok" : "neutral")}
      ${renderAdminStackMetric("\u672a\u5b8c\u6210", unfinishedTasks, "\u672a\u5230\u65f6\u95f4\u3001\u5f85\u63d0\u4ea4\u3001\u6267\u884c\u4e2d\u6216\u6570\u636e\u5931\u8d25", unfinishedTasks ? "warn" : "ok")}
      ${renderAdminStackMetric("未到时间", waitingTasks, "还没到计划抓取时间", waitingTasks ? "warn" : "ok")}
      ${renderAdminStackMetric("等待抓取/产出", processingTasks, "调度已处理但 raw/source 尚未闭环", processingTasks ? "warn" : "ok")}
      ${renderAdminStackMetric("\u5df2\u8fc7\u671f\u5173\u95ed", expiredClosedTasks, rawCancelledJobs ? `\u539f\u59cb\u4efb\u52a1\u5173\u95ed ${display(rawCancelledJobs, "0")}` : "\u8d85\u8fc7\u65e5\u5468\u671f\u540e\u4e0d\u518d\u542f\u7528", expiredClosedTasks ? "warn" : "ok")}
      ${renderAdminStackMetric("\u6570\u636e\u5931\u8d25", failedTasks, failedSub, failedTasks ? "danger" : rawAuditWarnings ? "warn" : "ok")}
      ${renderAdminStackMetric("\u6570\u636e\u4ea7\u51fa", sourceRows, sourceFactsAvailable ? (latestDataUpdate ? `\u6700\u65b0 ${formatDateTimeValue(latestDataUpdate)}` : "\u7b49\u5f85 source \u4ea7\u51fa") : "\u6e90\u6570\u636e\u6682\u4e0d\u53ef\u8bfb", sourceFactsAvailable ? (sourceRows ? "ok" : "neutral") : "danger")}
      ${renderAdminStackMetric("\u539f\u59cb\u6293\u53d6\u7b49\u5f85", rawWaitingJobs, rawActiveJobs ? `\u5904\u7406\u4e2d ${display(rawActiveJobs, "0")}` : "\u5c1a\u672a\u8fdb\u5165 source \u4ea7\u51fa", rawWaitingJobs ? "warn" : "ok")}
    </div>
    <div class="admin-reason-strip">${lifecycleReasons.length ? lifecycleReasons.map((item) => `<span class="admin-reason-chip admin-reason-chip--${adminReasonTone(item.reason)}">${escapeHtml(item.reason)} \u00b7 ${escapeHtml(display(item.count))}</span>`).join("") : `<span class="admin-reason-chip admin-reason-chip--ok">今日任务已完成</span>`}</div>
  </section>`;
}function renderAdminStackMetric(label, value, sub, tone = "neutral") {
  return `<article class="admin-stack-metric admin-stack-metric--${escapeClass(tone)}"><span>${escapeHtml(label)}</span><strong>${escapeHtml(display(value))}</strong><small>${escapeHtml(sub || "")}</small></article>`;
}

function buildAdminDataBlockSummary(assets, tasks, gaps) {
  const blockMap = new Map();
  const ensureBlock = (key) => {
    if (!blockMap.has(key)) {
      const meta = adminAssetBlockMeta(key);
      blockMap.set(key, {
        key,
        label: meta.label,
        order: meta.order,
        assetCount: 0,
        dueCount: 0,
        completedCount: 0,
        completedDueCount: 0,
        unresolvedCount: 0,
        problemCount: 0,
        unknownCount: 0,
        repairableCount: 0,
        unrepairableCount: 0,
        contractPendingCount: 0,
        notDueCount: 0,
        taskCount: 0,
        taskCompletedCount: 0,
        taskWaitingCount: 0,
        taskCollectingCount: 0,
        taskPendingAcceptanceCount: 0,
        taskAwaitingDispatchCount: 0,
        taskAwaitingEvidenceCount: 0,
        taskFailedCount: 0,
        taskExpiredClosedCount: 0,
        taskRepairableFailedCount: 0,
        taskUnrepairableFailedCount: 0,
        taskContractPendingFailedCount: 0,
        assets: [],
        gaps: [],
        reasonCounts: new Map(),
        modelSet: new Set(),
      });
    }
    return blockMap.get(key);
  };
  (assets || []).forEach((asset) => {
    const key = adminAssetBlockKey(asset.source_table_name);
    const block = ensureBlock(key);
    const gapSummary = asset.gap_summary || {};
    const gapCount = Number(gapSummary.count || 0);
    const reason = adminAssetProblemReason(asset);
    const complete = adminAssetIsComplete(asset);
    const notDue = asset?.status === "not_due";
    const problem = adminAssetHasBlockingProblem(asset);
    block.assetCount += 1;
    block.dueCount += notDue ? 0 : 1;
    block.completedCount += complete ? 1 : 0;
    block.completedDueCount += complete && !notDue ? 1 : 0;
    block.unresolvedCount += problem ? 1 : 0;
    block.problemCount += problem ? 1 : 0;
    block.unknownCount += asset?.status === "awaiting_data_result" ? 1 : 0;
    block.repairableCount += problem && gapCount && asset.repairability?.code === "repairable_after_expiry" ? 1 : 0;
    block.unrepairableCount += problem && gapCount && asset.repairability?.code === "non_repairable_after_window" ? 1 : 0;
    block.contractPendingCount += problem && gapCount && asset.repairability?.code === "contract_pending" ? 1 : 0;
    block.notDueCount += notDue ? 1 : 0;
    block.assets.push(asset);
    (asset.used_by_models || []).forEach((model) => block.modelSet.add(model));
    if (problem) block.reasonCounts.set(reason, (block.reasonCounts.get(reason) || 0) + 1);
  });
  (tasks || []).forEach((task) => {
    const key = adminAssetBlockKey(task.source_table_name);
    const block = ensureBlock(key);
    const repairCode = task.repairability?.code;
    const status = String(task.status || "");
    const completed = status === "completed" || status === "build_succeeded_target_check";
    const waiting = status === "not_due";
    const collecting = status === "collecting" || status === "queue_active";
    const awaitingDispatch = status === "awaiting_dispatch";
    const awaitingEvidence = status === "awaiting_evidence";
    const expiredClosed = status === "expired_closed";
    const failed = status === "failed" || status === "target_fact_missing" || status === "build_failed" || status === "data_failed";
    block.taskCount += 1;
    block.taskCompletedCount += completed ? 1 : 0;
    block.taskWaitingCount += waiting ? 1 : 0;
    block.taskCollectingCount += collecting ? 1 : 0;
    block.taskAwaitingDispatchCount += awaitingDispatch ? 1 : 0;
    block.taskAwaitingEvidenceCount += awaitingEvidence ? 1 : 0;
    block.taskExpiredClosedCount += expiredClosed ? 1 : 0;
    block.taskFailedCount += failed ? 1 : 0;
    block.taskRepairableFailedCount += failed && repairCode === "repairable_after_expiry" ? 1 : 0;
    block.taskUnrepairableFailedCount += failed && repairCode === "non_repairable_after_window" ? 1 : 0;
    block.taskContractPendingFailedCount += failed && repairCode === "contract_pending" ? 1 : 0;
    if (!completed) block.reasonCounts.set(adminTaskProblemReason(task), (block.reasonCounts.get(adminTaskProblemReason(task)) || 0) + 1);
  });
  (gaps || []).forEach((gap) => {
    const table = gap.source_table_name || gap.target_table || gap.table_name || gap.asset_table || "";
    const block = ensureBlock(adminAssetBlockKey(table));
    block.gaps.push(gap);
  });
  return Array.from(blockMap.values()).sort((a, b) => a.order - b.order || a.label.localeCompare(b.label));
}function adminAssetBlockKey(sourceTableName) {
  const table = String(sourceTableName || "");
  if (table.includes("trade_calendar") || table.includes("stock_master") || table.includes("stock_universe") || table.includes("trade_status")) return "foundation";
  if (table.includes("daily_bar") || table.includes("adjustment_factor") || table.includes("limit_price") || table.includes("limit_event")) return "price_limit";
  if (table.includes("realtime_quote") || table.includes("minute_bar") || table.includes("trade_tick") || table.includes("auction_snapshot")) return "intraday";
  if (table.includes("ths_paid_limit_up_probability")) return "paid_probability";
  if (table.includes("moneyflow") || table.includes("board")) return "flow_board";
  if (table.includes("index_")) return "index_env";
  if (table.includes("news")) return "news_event";
  return "other";
}

function adminAssetBlockMeta(key) {
  const map = {
    foundation: { label: "基础日历/股票池", order: 10 },
    price_limit: { label: "日线/价格/涨跌停", order: 20 },
    intraday: { label: "盘中分钟/逐笔/竞价", order: 30 },
    paid_probability: { label: "付费概率/候选补充", order: 40 },
    flow_board: { label: "资金/板块", order: 50 },
    index_env: { label: "指数环境", order: 60 },
    news_event: { label: "新闻事件", order: 70 },
    other: { label: "其他数据", order: 90 },
  };
  return map[key] || map.other;
}

function adminAssetIsComplete(asset) {
  return Number(asset?.gap_summary?.count || 0) === 0 && asset?.status === "no_known_gap";
}

function adminAssetHasBlockingProblem(asset) {
  if (!asset) return false;
  if (["not_due", "awaiting_data_result"].includes(asset.status)) return false;
  if (adminAssetIsComplete(asset)) return false;
  if (["data_failed", "build_failed", "expired_unrepairable", "missing_repairable", "missing_unknown_repairability"].includes(asset.status)) return true;
  if (Number(asset?.gap_summary?.count || 0) > 0) return true;
  return (asset?.readiness_blocking_reasons || []).length > 0;
}

function adminAssetProblemReason(asset) {
  const status = String(asset?.status || "");
  const gapCount = Number(asset?.gap_summary?.count || 0);
  if (status === "data_failed") return "数据产出失败";
  if (status === "build_failed") return "构建失败";
  if (status === "not_due") return "未到抓取时间";
  if (status === "awaiting_data_result") return "等待数据结果";
  if (gapCount > 0) {
    if (asset?.repairability?.code === "non_repairable_after_window") return "不可补数据缺失";
    if (asset?.repairability?.code === "repairable_after_expiry") return "可补数据缺失";
    if (asset?.repairability?.code === "contract_pending") return "补救方式待确认";
    return "数据缺失待确认";
  }
  if ((asset?.readiness_blocking_reasons || []).length) return "准入条件未满足";
  return "等待数据结果";
}

function adminTaskProblemReason(task) {
  const status = String(task?.status || "");
  if (status === "not_due") return "未到抓取时间";
  if (status === "awaiting_dispatch") return "待提交抓取";
  if (status === "awaiting_evidence") return "等待数据结果";
  if (status === "collecting" || status === "queue_active") return "等待抓取/产出";
  if (status === "expired_closed") return "\u5df2\u8fc7\u671f\u5173\u95ed";
  if (status === "build_failed") return "构建失败";
  if (status === "target_fact_missing" || status === "data_failed") return "目标数据未产出";
  if (status === "failed") return "调度执行失败";
  if (status === "completed" || status === "build_succeeded_target_check") return "";
  return "等待数据结果";
}
function adminReasonTone(reason) {
  const text = String(reason || "");
  if (text.includes("失败") || text.includes("缺失") || text.includes("不可补")) return "danger";
  if (text.includes("\u8fc7\u671f")) return "warn";
  if (text.includes("blocked") || text.includes("reject") || text.includes("failed") || text.includes("invalid")) return "blocked";
  return "ok";
}function adminTopReasonSummary(blocks, limit = 4) {
  const counts = new Map();
  (blocks || []).forEach((block) => {
    block.reasonCounts.forEach((count, reason) => counts.set(reason, (counts.get(reason) || 0) + count));
  });
  return Array.from(counts.entries())
    .map(([reason, count]) => ({ reason, count }))
    .sort((a, b) => b.count - a.count || a.reason.localeCompare(b.reason))
    .slice(0, limit);
}

function renderAdminDataBlockBoard(blocks) {
  const visibleBlocks = (blocks || []).filter(adminBlockNeedsAttention);
  if (!visibleBlocks.length) {
    return `<section class="admin-block-board" data-admin-block-board="true"><div class="admin-empty-state">今日任务均已完成，暂无需要展开的数据块。</div></section>`;
  }
  return `<section class="admin-block-board" data-admin-block-board="true">
    ${visibleBlocks.map(renderAdminDataBlockCard).join("")}
  </section>`;
}
function adminBlockNeedsAttention(block) {
  return Number(block.taskWaitingCount || 0) > 0
    || Number(block.taskCollectingCount || 0) > 0
    || Number(block.taskPendingAcceptanceCount || 0) > 0
    || Number(block.taskAwaitingDispatchCount || 0) > 0
    || Number(block.taskAwaitingEvidenceCount || 0) > 0
    || Number(block.taskExpiredClosedCount || 0) > 0
    || Number(block.taskFailedCount || 0) > 0
    || Number(block.problemCount || 0) > 0;
}

function renderAdminDataBlockCard(block) {
  const unfinished = Math.max(Number(block.taskCount || 0) - Number(block.taskCompletedCount || 0), 0);
  const pct = Number(block.taskCount || 0) > 0 ? Math.round((Number(block.taskCompletedCount || 0) / Number(block.taskCount || 0)) * 100) : null;
  const failureCount = Number(block.taskFailedCount || 0) + Number(block.problemCount || 0);
  const tone = failureCount || block.unrepairableCount ? "danger" : unfinished ? "warn" : "ok";
  const reasons = Array.from(block.reasonCounts.entries()).sort((a, b) => b[1] - a[1]).slice(0, 3);
  const statusLabel = failureCount ? "\u6570\u636e\u5931\u8d25" : unfinished ? "\u672a\u5b8c\u6210" : "\u5df2\u5b8c\u6210";
  const failedTags = failureCount || block.repairableCount || block.unrepairableCount || block.contractPendingCount
    ? `<div class="admin-block-card__counts"><span>可补 ${escapeHtml(display(block.taskRepairableFailedCount + block.repairableCount, "0"))}</span><span>不可补 ${escapeHtml(display(block.taskUnrepairableFailedCount + block.unrepairableCount, "0"))}</span><span>待确认 ${escapeHtml(display(block.taskContractPendingFailedCount + block.contractPendingCount, "0"))}</span></div>`
    : "";
  return `<article class="admin-block-card admin-block-card--${escapeClass(tone)}">
    <div class="admin-block-card__head">
      <div><strong>${escapeHtml(block.label)}</strong><span>\u4eca\u65e5\u8ba1\u5212 ${escapeHtml(display(block.taskCount, "0"))} \u00b7 \u5df2\u5b8c\u6210 ${escapeHtml(display(block.taskCompletedCount, "0"))} \u00b7 \u672a\u5b8c\u6210 ${escapeHtml(display(unfinished, "0"))}</span></div>
      ${adminStatusBadge(statusLabel, tone)}
    </div>
    <div class="admin-progress admin-progress--${escapeClass(tone)}"><span style="width:${pct === null ? 0 : Math.max(0, Math.min(pct, 100))}%"></span></div>
    <div class="admin-block-card__counts">
      <span>未到时间 ${escapeHtml(display(block.taskWaitingCount, "0"))}</span><span>等待产出 ${escapeHtml(display(block.taskCollectingCount, "0"))}</span><span>待提交 ${escapeHtml(display(block.taskAwaitingDispatchCount, "0"))}</span><span>待结果 ${escapeHtml(display(block.taskAwaitingEvidenceCount, "0"))}</span><span>失败 ${escapeHtml(display(failureCount, "0"))}</span>
    </div>
    ${failedTags}
    <div class="admin-block-card__reasons">${reasons.length ? reasons.map(([reason, count]) => `<span class="admin-reason-chip admin-reason-chip--${adminReasonTone(reason)}">${escapeHtml(reason)} \u00b7 ${escapeHtml(display(count))}</span>`).join("") : `<span class="admin-reason-chip admin-reason-chip--${unfinished ? "warn" : "ok"}">${unfinished ? "等待后续采集" : "已完成"}</span>`}</div>
  </article>`;
}
function renderAdminExceptionList(blocks) {
  const failedBlocks = (blocks || []).filter((block) => block.taskFailedCount || block.problemCount || block.repairableCount || block.unrepairableCount || block.contractPendingCount);
  if (!failedBlocks.length) {
    return `<section class="admin-exception-panel panel"><div class="panel__head"><h2 class="panel-title">失败补救</h2><span>0 块</span></div><div class="admin-empty-state">当前没有失败任务或失败数据；未到时间、待提交和等待产出不贴可补/不可补标签。</div></section>`;
  }
  return `<section class="admin-exception-panel panel">
    <div class="panel__head"><h2 class="panel-title">失败补救</h2><span>${escapeHtml(display(failedBlocks.length))} 块需要处理</span></div>
    <div class="admin-exception-list">${failedBlocks.map(renderAdminExceptionItem).join("")}</div>
  </section>`;
}

function renderAdminExceptionItem(block) {
  const reasons = Array.from(block.reasonCounts.entries()).sort((a, b) => b[1] - a[1]);
  const action = adminBlockActionText(block);
  const failureCount = Number(block.taskFailedCount || 0) + Number(block.problemCount || 0);
  return `<article class="admin-exception-item">
    <div class="admin-exception-item__main">
      <strong>${escapeHtml(block.label)}</strong>
      <span>${escapeHtml(action)}</span>
    </div>
    <div class="admin-exception-item__metrics">
      <span>失败 ${escapeHtml(display(failureCount, "0"))}</span><span>可补 ${escapeHtml(display(block.taskRepairableFailedCount + block.repairableCount, "0"))}</span><span>不可补 ${escapeHtml(display(block.taskUnrepairableFailedCount + block.unrepairableCount, "0"))}</span><span>待确认 ${escapeHtml(display(block.taskContractPendingFailedCount + block.contractPendingCount, "0"))}</span>
    </div>
    <div class="admin-exception-item__reasons">${reasons.length ? reasons.map(([reason, count]) => `<span class="admin-reason-chip admin-reason-chip--${adminReasonTone(reason)}">${escapeHtml(reason)} · ${escapeHtml(display(count))}</span>`).join("") : `<span class="admin-reason-chip admin-reason-chip--warn">等待补救判断</span>`}</div>
  </article>`;
}

function adminBlockActionText(block) {
  if (block.taskUnrepairableFailedCount > 0 || block.unrepairableCount > 0) return "窗口型数据已经错过当时采集点，不允许用事后数据冒充当时事实。";
  if (block.taskRepairableFailedCount > 0 || block.repairableCount > 0) return "可走正规补采，补完后等待今日验收。";
  if (block.taskContractPendingFailedCount > 0 || block.contractPendingCount > 0) return "补救方式还没在合同里说清楚，需要先确认补救路径。";
  if (block.taskFailedCount > 0 || block.problemCount > 0) return "存在失败或目标数据缺失，需要排查采集结果。";
  return "等待后续采集结果。";
}function renderAdminKpi(label, value, sub, tone = "neutral") {
  return `<article class="admin-kpi admin-kpi--${escapeClass(tone)}"><span>${escapeHtml(label)}</span><strong>${escapeHtml(display(value))}</strong><small>${escapeHtml(sub || "")}</small></article>`;
}

function renderAdminUpstreamStatus(upstream) {
  const entries = Object.entries(upstream || {});
  if (!entries.length) return `<span class="admin-status admin-status--muted">上游读取状态未知</span>`;
  return entries.map(([key, item]) => {
    const status = String(item?.status || "").toLowerCase();
    const ok = status === "ok" || status === "ready" || status === "available" || status === "read";
    const missingInspection = key === "inspection_latest" && (status === "missing" || status === "not_found" || String(item?.message || "").includes("未生成"));
    const tone = ok ? "ok" : missingInspection ? "warn" : "danger";
    const label = ok ? "可读" : missingInspection ? "未生成" : "读取失败";
    return `<span class="admin-status admin-status--${tone}">${escapeHtml(adminUpstreamLabel(key))} · ${escapeHtml(label)}</span>`;
  }).join("");
}function adminUpstreamLabel(key) {
  const map = {
    requirements: "数据合同",
    freshness_sla: "时效合同",
    readiness_matrix: "准入矩阵",
    repair_routes: "补救路径",
    queue_summary: "采集队列",
    build_results: "构建结果",
    build_triggers: "构建触发",
    storage_policies: "存储策略",
    source_schedule_registry: "任务计划",
    source_schedule_materialized: "今日任务",
    scheduler_runtime: "调度运行",
    source_daily_summary: "今日数据产出",
    scheduler_daily_summary: "调度账本",
    inspection_latest: "今日验收",
    inspection_gaps: "缺口明细",
  };
  return map[key] || "上游服务";
}
function adminStatusTone(status) {
  const text = String(status || "").toLowerCase();
  if (text.includes("danger") || text.includes("missing") || text.includes("expired") || text.includes("failed") || text.includes("blocked") || text.includes("dead") || text.includes("失败") || text.includes("缺失")) return "danger";
  if (text.includes("warn") || text.includes("unknown") || text.includes("stale") || text.includes("unavailable") || text.includes("repairable") || text.includes("active") || text.includes("awaiting") || text.includes("not_due") || text.includes("等待") || text.includes("未到") || text.includes("采集")) return "warn";
  if (text.includes("ok") || text.includes("succeeded") || text.includes("no_known_gap") || text.includes("ready") || text.includes("完成")) return "ok";
  return "muted";
}
function adminStatusBadge(label, status) {
  return `<span class="admin-status admin-status--${adminStatusTone(status || label)}">${escapeHtml(display(label || businessStatusLabel(status)))}</span>`;
}
function renderAdminAssetTable(rows) {
  return `<div class="admin-table-wrap"><table class="admin-table admin-table--assets">
          <thead><tr><th>准备度维度</th><th>优先级</th><th>权重</th><th>覆盖</th><th>缺失分</th></tr></thead>
    <tbody>${renderAdminAssetRows(rows)}</tbody>
  </table></div>`;
}

function renderAdminAssetRows(rows) {
  if (!rows.length) return renderEmptyTableRow(8, "没有读到数据资产合同。");
  return rows.map((row) => {
    const fields = (row.fields || []).slice(0, 4).join(" / ");
    const missing = row.known_missing_field_count ?? row.gap_summary?.count ?? null;
    const total = row.required_field_count ?? null;
    const build = row.latest_build;
    const buildText = build ? `${businessStatusLabel(build.status)} · ${formatDateTimeValue(build.finished_at)}` : "-";
    const buildRows = build ? `raw ${display(build.raw_row_count)} / source ${display(build.source_row_count)} / lineage ${display(build.lineage_row_count)}` : "";
    const gapCodes = (row.gap_summary?.top_codes || []).join(" / ");
    return `<tr>
      <td data-label="数据资产"><strong>${escapeHtml(display(row.asset_label || row.source_table_name))}</strong><small>${escapeHtml(display(row.source_table_name))}${fields ? ` · ${escapeHtml(fields)}` : ""}</small></td>
      <td data-label="优先级">${escapeHtml(display(row.priority))}</td>
      <td data-label="生命周期"><strong>${escapeHtml(display(row.lifecycle?.label))}</strong><small>${escapeHtml(display(row.lifecycle?.expected_at))} - ${escapeHtml(display(row.lifecycle?.latest_acceptable_at))}</small></td>
      <td data-label="补全属性"><strong>${escapeHtml(display(row.repairability?.label))}</strong><small>${escapeHtml(display(row.repairability?.reason))}</small></td>
      <td data-label="完成/缺失"><strong>${escapeHtml(display(row.known_completed_field_count))}/${escapeHtml(display(total))}</strong><small>缺失 ${escapeHtml(display(missing))}</small></td>
      <td data-label="最新构建"><strong>${escapeHtml(buildText)}</strong><small>${escapeHtml(buildRows || build?.note || "-")}</small></td>
      <td data-label="巡检缺口"><strong>P0 ${escapeHtml(display(row.gap_summary?.p0_count))} / P1 ${escapeHtml(display(row.gap_summary?.p1_count))}</strong><small>${escapeHtml(gapCodes || "-")}</small></td>
      <td data-label="状态">${adminStatusBadge(row.status_label, row.status)}</td>
    </tr>`;
  }).join("");
}

function renderAdminTaskTable(rows) {
  return `<div class="admin-table-wrap"><table class="admin-table admin-table--tasks">
        <thead><tr><th>股票</th><th>梯队</th><th>首次涨停时间</th><th>最后涨停时间</th><th>形态</th><th>涨停原因</th><th>同花顺次日概率</th><th>状态</th></tr></thead>
    <tbody>${renderAdminTaskRows(rows)}</tbody>
  </table></div>`;
}

function renderAdminTaskRows(rows) {
  if (!rows.length) return renderEmptyTableRow(7, "今天没有读到已物化调度任务。");
  return rows.map((row) => {
    const scope = [row.universe_scope, row.symbol_count ? `${row.symbol_count} 只` : null, row.trigger_type].filter(Boolean).join(" · ") || "-";
    const buildText = [row.fetch_batch_id ? `batch ${row.fetch_batch_id}` : null, row.latest_build_status ? businessStatusLabel(row.latest_build_status) : null].filter(Boolean).join(" · ") || "-";
    const target = `P0 ${display(row.gap_summary?.p0_count)} / 缺口 ${display(row.gap_summary?.count)}`;
    return `<tr>
      <td data-label="任务"><strong>${escapeHtml(display(row.schedule_code))}</strong><small>${escapeHtml(display(row.schedule_group))}</small></td>
      <td data-label="数据资产"><strong>${escapeHtml(display(row.asset_label || row.source_table_name))}</strong><small>${escapeHtml(display(row.source_table_name))}</small></td>
      <td data-label="计划时间"><strong>${escapeHtml(formatDateTimeValue(row.scheduled_at_local || row.scheduled_at))}</strong><small>${escapeHtml(display(row.run_slot || row.trading_day))}</small></td>
      <td data-label="范围">${escapeHtml(scope)}</td>
      <td data-label="抓取/构建"><strong>${escapeHtml(buildText)}</strong><small>${escapeHtml(formatDateTimeValue(row.latest_build_finished_at))}</small></td>
      <td data-label="目标事实"><strong>${escapeHtml(target)}</strong><small>source ${escapeHtml(display(row.source_row_count))} / lineage ${escapeHtml(display(row.lineage_row_count))}</small></td>
      <td data-label="状态">${adminStatusBadge(row.status_label, row.status)}</td>
    </tr>`;
  }).join("");
}

function renderAdminGapTable(rows) {
  return `<div class="admin-table-wrap"><table class="admin-table admin-table--gaps">
          <thead><tr><th>准备度维度</th><th>优先级</th><th>权重</th><th>覆盖</th><th>缺失分</th></tr></thead>
    <tbody>${renderAdminGapRows(rows)}</tbody>
  </table></div>`;
}

function renderAdminGapRows(rows) {
  if (!rows.length) return renderEmptyTableRow(6, "当前巡检没有返回缺口明细。");
  return rows.map((row) => {
    const table = row.source_table_name || row.target_table || row.table_name || row.asset_table || "-";
    const subject = [row.canonical_symbol || row.symbol, row.trade_date || row.as_of_date || row.as_of_trading_day].filter(Boolean).join(" · ") || "-";
    const actions = Array.isArray(row.repair_actions) ? row.repair_actions.map((item) => item.action_code || item.code || item.action || item).join(" / ") : (row.repair_action || row.recommended_action || row.remediation || "-");
    return `<tr>
      <td data-label="数据资产"><strong>${escapeHtml(display(table))}</strong><small>${escapeHtml(display(row.domain || row.scope))}</small></td>
      <td data-label="字段">${escapeHtml(display(row.field_name || row.canonical_field_name || row.target_field))}</td>
      <td data-label="等级">${adminStatusBadge(row.severity || row.priority, row.severity || row.priority)}</td>
      <td data-label="缺口码"><strong>${escapeHtml(display(row.gap_code || row.gap_type || row.domain_code))}</strong><small>${escapeHtml(display(row.message || row.description))}</small></td>
      <td data-label="对象">${escapeHtml(subject)}</td>
      <td data-label="补救动作">${escapeHtml(display(actions))}</td>
    </tr>`;
  }).join("");
}

function bindAdminOpsActions(pageEpoch, routeKey) {
  const reloadButton = $("[data-action='reload-admin-board']");
  const dateInput = $("#admin-board-date");
  const detailPanel = $("[data-admin-audit-details='true']");
  reloadButton?.addEventListener("click", async () => {
    const value = dateInput?.value || adminBoardDefaultTradeDate();
    state.adminBoard.tradeDate = value;
    renderAdminOpsPage({ pageEpoch, routeKey, forceRefresh: true });
  });
  dateInput?.addEventListener("change", (event) => {
    state.adminBoard.tradeDate = event.target.value || adminBoardDefaultTradeDate();
    state.adminBoard.detailsOpen = false;
    state.adminBoard.detailError = null;
    renderAdminOpsPage({ pageEpoch, routeKey, forceRefresh: true });
  });
  detailPanel?.addEventListener("toggle", (event) => {
    state.adminBoard.detailsOpen = Boolean(event.target.open);
    if (state.adminBoard.detailsOpen && !adminDailyBoardLoaded(state.adminBoard.data)) {
      hydrateAdminDailyBoard(pageEpoch, routeKey).catch(() => {});
    }
  });
}

async function renderPage(pageEpoch = state.pageEpoch, routeKey = state.route) {
  if (routeKey === "candidates") return renderCandidatePage({ pageEpoch, routeKey });
  if (routeKey === "research-ambush-valley") return renderAmbushValleyResearchPage({ pageEpoch, routeKey });
  if (routeKey === "admin-ops") return renderAdminOpsPage({ pageEpoch, routeKey });
  if (MODEL_PROFILES[routeKey]) return renderModelPage(MODEL_PROFILES[routeKey], { pageEpoch, routeKey });
  state.route = "candidates";
  location.hash = "#/candidates";
}

function renderPageError(error) {
  $("#page-root").innerHTML = `<section class="notice-bar"><strong>页面不可读</strong><span>${escapeHtml(frontendErrorLabel(error))}</span></section>`;
}

function display(value, fallback = "-") {
  if (value === null || value === undefined || value === "") return fallback;
  return String(value);
}

function isFiniteNumber(value) {
  if (typeof value === "boolean") return false;
  return value !== "" && value !== null && value !== undefined && Number.isFinite(Number(value));
}

function numberOrNull(value) {
  return isFiniteNumber(value) ? Number(value) : null;
}

function arrayFromResponse(data) {
  if (Array.isArray(data)) return data;
  if (Array.isArray(data?.value)) return data.value;
  if (Array.isArray(data?.items)) return data.items;
  if (Array.isArray(data?.data)) return data.data;
  if (Array.isArray(data?.result)) return data.result;
  if (Array.isArray(data?.result?.items)) return data.result.items;
  return [];
}

function frontendErrorLabel(error) {
  const raw = String(error?.message || error || "").trim();
  if (!raw) return "暂时没有读到数据，请稍后重试。";
  const lower = raw.toLowerCase();
  if ((lower.includes("ths paid probability") || lower.includes("paid probability")) && (lower.includes("403") || lower.includes("denied"))) {
    return "同花顺登录已失效，请更新 Cookie 后重新抓取。";
  }
  if (lower.includes("cookie") && (lower.includes("expired") || lower.includes("invalid") || lower.includes("denied"))) {
    return "同花顺登录已失效，请更新 Cookie 后重新抓取。";
  }
  if (error?.code === "frontend_timeout" || lower.includes("timeout") || lower.includes("timed out") || lower.includes("abort")) return "读取超时，页面已保留可见数据。";
  if (lower.includes("401") || lower.includes("login required") || lower.includes("unauthorized")) return "登录状态已过期，请重新登录。";
  if (lower.includes("503") || lower.includes("502") || lower.includes("unreachable") || lower.includes("connection") || lower.includes("network")) return "后端暂时不可读，页面已保留空态。";
  if (lower.includes("404")) return "当前事实入口暂未开放。";
  if (lower.includes("invalid") || lower.includes("parse")) return "返回内容暂时无法识别。";
  if (!/[\u4e00-\u9fff]/.test(raw) || /\/api|source\/|readyz|healthz|repository|backend|service|payload|json|request|http/i.test(raw)) {
    return "读取失败，页面已保留中文空态。";
  }
  return raw;
}

function safeLoadErrorLabel(error) {
  return frontendErrorLabel(error);
}

function uniqueMessages(messages) {
  return [...new Set((messages || []).filter(Boolean))];
}

function latestTradeDate(rows) {
  const dates = rows.map((item) => item.trade_date || item.day1_trade_date || item.day2_trade_date || item.trading_day).filter(Boolean).sort();
  return dates[dates.length - 1] || null;
}

function rowValues(row) {
  return row?.values && typeof row.values === "object" ? row.values : {};
}

function bySymbol(rows) {
  return new Map(rows.map((row) => [row.symbol || row.canonical_symbol, row]).filter(([symbol]) => symbol));
}

function formatPercentValue(value) {
  if (!isFiniteNumber(value)) return "-";
  const number = Number(value);
  return `${number.toFixed(Math.abs(number) >= 10 ? 1 : 2)}%`;
}

function formatMoneyWan(value) {
  if (!isFiniteNumber(value)) return "-";
  const number = Number(value);
  const abs = Math.abs(number);
  if (abs >= 100000000) return `${(number / 100000000).toFixed(2)}亿`;
  if (abs >= 10000) return `${(number / 10000).toFixed(1)}万`;
  return number.toFixed(0);
}

function formatPrice(value) {
  if (!isFiniteNumber(value)) return "-";
  return Number(value).toFixed(2);
}

function formatScore(value) {
  if (!isFiniteNumber(value)) return "-";
  return Number(value).toFixed(1);
}

function formatDateTimeValue(value) {
  if (value === null || value === undefined || value === "") return "-";
  const text = String(value).trim();
  if (/^\d{4}-\d{2}-\d{2}$/.test(text)) return text;
  const normalized = text.replace(/^(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2}:\d{2})/, "$1T$2");
  if (/(?:Z|[+-]\d{2}:?\d{2})$/.test(normalized)) {
    const parsed = new Date(normalized);
    if (!Number.isNaN(parsed.getTime())) {
      const parts = new Intl.DateTimeFormat("zh-CN", {
        timeZone: "Asia/Shanghai",
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hourCycle: "h23",
      }).formatToParts(parsed);
      const byType = Object.fromEntries(parts.map((part) => [part.type, part.value]));
      return `${byType.year}-${byType.month}-${byType.day} ${byType.hour}:${byType.minute}:${byType.second}`;
    }
  }
  return text.replace("T", " ").replace(/\.\d+(?:Z|[+-]\d{2}:?\d{2})?$/, "").replace(/(?:Z|[+-]\d{2}:?\d{2})$/, "");
}

function boolValue(value) {
  if (value === true || value === 1) return true;
  if (value === false || value === 0) return false;
  const text = String(value ?? "").trim().toLowerCase();
  if (["true", "1", "yes", "y"].includes(text)) return true;
  if (["false", "0", "no", "n"].includes(text)) return false;
  return null;
}

function formatBool(value) {
  const normalized = boolValue(value);
  if (normalized === true) return "是";
  if (normalized === false) return "否";
  return "-";
}

function gapCount(value) {
  return Array.isArray(value) ? value.length : 0;
}

function factorList(value) {
  if (Array.isArray(value)) return value.filter((item) => item !== null && item !== undefined && item !== "");
  if (value === null || value === undefined || value === "") return [];
  return String(value).split(/[,\n/]+/).map((item) => item.trim()).filter(Boolean);
}

function eventTypeLabel(value) {
  const map = {
    limit_up: "涨停",
    t_board_limit_up: "T字板",
    limit_up_broken: "炸板",
    none: "无涨停",
  };
  return map[value] || "涨停结构待核验";
}

function sourceQualityLabel(value) {
  const key = String(value || "").trim().toLowerCase();
  return SOURCE_QUALITY_LABELS[key] || "质量待核验";
}

function providerLabel(value) {
  const key = String(value || "").trim().toLowerCase();
  return PROVIDER_LABELS[key] || "来源待核验";
}

function factsSourceLabel(value) {
  const key = String(value || "").trim().toLowerCase();
  const labels = {
    limit_event: "标准涨停事实",
    daily_bar: "标准日线行情",
    adjusted_daily_bar: "前复权日线",
    moneyflow: "资金流事实",
    limit_price: "涨停价事实",
    tboard_repository: "T字接力观察台",
    model_repository: "模型研究仓库",
    source_requirement: "数据要求清单",
  };
  return labels[key] || "标准事实";
}

function selectedBusinessDateLabel(value) {
  return value || PREFERRED_CANDIDATE_TRADE_DATE || CANDIDATE_TRADE_DATE_FALLBACK_LABEL;
}

function candidateRequestedTradeDateLabel() {
  return PREFERRED_CANDIDATE_TRADE_DATE || CANDIDATE_TRADE_DATE_FALLBACK_LABEL;
}

function candidateReadStateLabel(value) {
  const labels = {
    waiting: "等待读取",
    reading: "正在读取",
    preferred_ready: "候选数据已读到",
    preferred_empty: "暂无入库涨停",
    fallback_visible: "仅看到其他日期",
    read_failed: "读取失败",
  };
  return labels[String(value || "")] || businessStatusLabel(value || "waiting");
}

function candidateReadDetail() {
  const source = state.candidateSource || {};
  if (source.error) return `读取时遇到问题：${businessStatusLabel(source.error)}`;
  if (source.sourceReadState === "preferred_ready") return `已读取 ${selectedBusinessDateLabel(source.tradeDate)} 已入库的涨停事实。`;
  if (source.sourceReadState === "preferred_empty") {
    return `没有读到 ${candidateRequestedTradeDateLabel()} 的收盘封板候选；请先完成涨停数据抓取和入库。`;
  }
  if (source.sourceReadState === "fallback_visible") {
    return `没有读到 ${candidateRequestedTradeDateLabel()} 的候选；系统只看到 ${source.fallbackTradeDate || "其他日期"} 的历史记录，当前页不拿历史记录冒充当前候选。`;
  }
  if (source.sourceReadState === "read_failed") return "候选事实暂时不可读，页面保持空态。";
    return "读取失败，页面已保留中文空态。";
}

function modelBusinessName(value) {
  const labels = {
    hot_candidates: "热点候选",
    candidate_memory: "候选记忆",
    ambush_watchlist: "潜伏抬头",
    t_board_relay: "T字板接力",
    hot: "热点候选",
    memory: "候选记忆",
    ambush: "潜伏抬头",
    tboard: "T字板接力",
  };
  return labels[String(value || "").trim()] || businessStatusLabel(value);
}

function canonicalMissingLabel(fieldName) {
  const labels = {
    stock_name: "名称暂未发布",
    first_limit_up_at: "时间暂未发布",
    last_limit_up_at: "收盘封板，时点未发布",
    limit_up_reason: "涨停原因暂未发布",
  };
  return labels[fieldName] || "暂未发布";
}

function stockNameLabel(name, symbol = "") {
  const text = String(name || "").trim();
  if (!text || text === symbol) return canonicalMissingLabel("stock_name");
  if (/[\uFFFD\u00C3\u00E4\u00E5\u00E7\u00E9\u00E8\u00E6]/.test(text)) return "名称待标准化";
  if (/\.(SZ|SH|BJ)$/i.test(String(symbol || "")) && /^[A-Za-z0-9 .&()/-]+$/.test(text)) return "名称待标准化";
  return text;
}

function businessStatusLabel(value) {
  if (value === null || value === undefined || value === "") return "-";
  if (Array.isArray(value)) return value.map(businessStatusLabel).join(" / ");
  const text = String(value).trim();
  const key = text.toLowerCase();
  if (GAP_CODE_LABELS[key]) return GAP_CODE_LABELS[key];
  if (STATUS_LABELS[key]) return STATUS_LABELS[key];
  if (key.startsWith("source_gap:")) {
    return translatedGapLabel(text);
  }
  if (!/[\u4e00-\u9fff]/.test(text) && /[A-Za-z_]/.test(text) && !/^\d{6}\.(SZ|SH|BJ)$/i.test(text) && !/^T\+\d/i.test(text)) {
    return programStatusFallback(key);
  }
  return display(value);
}

function translatedGapLabel(value) {
  let label = String(value || "").trim().toLowerCase().replace(/^source_gap:/, "");
  const replacements = [
    ["hot_decision_list", "热点决策列表"],
    ["ths_paid_probability", "同花顺付费概率"],
    ["paid_probability", "付费概率"],
    ["memory_entity", "候选记忆实体"],
    ["ambush_decision_list", "潜伏抬头决策列表"],
    ["ambush_label_repository", "潜伏图库标注仓库"],
    ["repository_probe_budget_exhausted", "仓库读取预算耗尽"],
    ["repository_not_attached", "仓库未连接"],
    ["source_read_timeout", "标准事实读取超时"],
    ["frontend_timeout", "前端读取超时"],
    ["model_score", "模型分"],
    ["buy_point", "买点"],
    ["reference_entry_price", "评估基准价"],
    ["outcome", "收益验证"],
    ["daily_bar_history", "低谷日线历史"],
    ["daily_bar", "日线"],
    ["stock_moneyflow", "资金流"],
    ["moneyflow_context", "资金上下文"],
    ["trading_calendar_memory_age", "交易日历记忆年龄"],
    ["trading_calendar", "交易日历"],
    ["seal_order_snapshot", "封单快照"],
    ["dynamic_feature_bundle", "动态特征包"],
    ["near_limit_order_absorption", "近涨停盘口吸收"],
    ["float_market_cap", "流通市值"],
    ["limit_price", "涨停价"],
    ["limit_event", "涨停事件"],
    ["trade_tick", "逐笔成交"],
    ["minute_bar", "分钟行情"],
    ["realtime_quote", "实时行情"],
    ["order_book_snapshot", "盘口快照"],
    ["close_on_limit_flag", "收盘封板标记"],
    ["one_word_limit_flag", "一字板标记"],
    ["instrument_identity", "标的身份"],
    ["same_day", "同日"],
    ["join", "关联"],
    ["not_materialized", "未物化"],
    ["insufficient", "不足"],
    ["missing", "缺失"],
  ];
  replacements.forEach(([raw, translated]) => {
    label = label.replaceAll(raw, translated);
  });
  label = label.replace(/[_:.-]+/g, "").replace(/\s+/g, "").trim();
  if (!label || /[A-Za-z]/.test(label)) return "数据缺口：未发布事实";
  return `数据缺口：${label}`;
}

function programStatusFallback(key) {
  if (key.includes("repository_probe_budget_exhausted")) return "仓库读取预算耗尽";
  if (key.includes("timeout")) return "读取超时";
  if (key.includes("unreachable")) return "暂时不可读";
  if (key.includes("not_materialized")) return "未物化";
  if (key.includes("missing")) return "事实缺失";
  if (key.includes("blocked")) return "阻断";
  if (key.includes("failed")) return "失败";
  if (key.includes("reject")) return "已拒绝";
  if (key.includes("trigger")) return "触发状态待核验";
  if (key.includes("watch")) return "观察中";
  if (key.includes("passed")) return "通过";
  if (key.includes("ready")) return "就绪";
    return "读取失败，页面已保留中文空态。";
}

function isClosedLimitCandidate(row) {
  const values = rowValues(row);
  return ["limit_up", "t_board_limit_up"].includes(values.limit_event_type)
    && boolValue(values.close_on_limit_flag) === true;
}

function queryJoin(params) {
  return new URLSearchParams(params).toString();
}

function sourceRowsPath(sourceTableName, params = {}) {
  return `source/rows?${queryJoin({ source_table_name: sourceTableName, ...params })}`;
}

async function loadSourceRows(sourceTableName, params = {}, timeoutMs = FRONTEND_TABLE_TIMEOUT_MS) {
  return arrayFromResponse(await backend("source", sourceRowsPath(sourceTableName, params), timeoutMs));
}

async function loadLatestSourceRows(sourceTableName, preferredTradeDate = PREFERRED_CANDIDATE_TRADE_DATE, timeoutMs = FRONTEND_TABLE_TIMEOUT_MS) {
  if (preferredTradeDate) {
    const preferredRows = await loadSourceRows(sourceTableName, { trade_date: preferredTradeDate }, timeoutMs);
    if (preferredRows.length) {
      return { rows: preferredRows, tradeDate: preferredTradeDate, preferredUsed: true, latestUsed: false, fallbackRows: [], fallbackTradeDate: null };
    }
  }
  const fallbackRows = await loadSourceRows(sourceTableName, {}, timeoutMs);
  const tradeDate = latestTradeDate(fallbackRows);
  const rows = tradeDate ? fallbackRows.filter((row) => (row.trade_date || row.trading_day) === tradeDate) : fallbackRows;
  return {
    rows,
    tradeDate: tradeDate || preferredTradeDate || null,
    preferredUsed: !preferredTradeDate && Boolean(tradeDate),
    latestUsed: !preferredTradeDate && Boolean(tradeDate),
    fallbackRows,
    fallbackTradeDate: tradeDate,
  };
}

function limitPatternText(values) {
  if (boolValue(values.is_one_word_board) === true) return "一字板";
  if (values.limit_event_type === "t_board_limit_up") return "T字板";
  const openCount = Number(values.limit_open_count);
  if (Number.isFinite(openCount) && openCount > 0) return `开板${openCount}次回封`;
  if (boolValue(values.is_break_limit) === true) return "开板回封";
  return eventTypeLabel(values.limit_event_type);
}

function statusTone(value) {
  const text = String(value || "").toLowerCase();
  if (text.includes("blocked") || text.includes("reject") || text.includes("failed") || text.includes("invalid")) return "blocked";
  if (text.includes("missing") || text.includes("waiting") || text.includes("watch") || text.includes("research") || text.includes("gap") || text.includes("not_")) return "warning";
  return "ready";
}

function candidateKey(row) {
  return `${row.symbol || ""}|${row.trade_date || ""}`;
}

function candidateCodeKey(row) {
  return `${normalizeStockSymbol(row.symbol)}|${row.trade_date || ""}`;
}

function candidateEventPriority(row) {
  const values = rowValues(row);
  if (values.limit_event_type === "t_board_limit_up") return 2;
  if (values.limit_event_type === "limit_up") return 1;
  return 0;
}

function uniqueCandidateSourceRows(rows) {
  const byKey = new Map();
  for (const row of rows || []) {
    const key = candidateCodeKey(row);
    if (!key.trim()) continue;
    const existing = byKey.get(key);
    if (!existing || candidateEventPriority(row) > candidateEventPriority(existing)) {
      byKey.set(key, row);
    }
  }
  return Array.from(byKey.values());
}

function candidatePaidProbabilityMap(rows) {
  const map = new Map();
  (rows || []).forEach((row) => {
    const values = rowValues(row);
    const tradeDate = row.trade_date || values.trade_date || values.date;
    const probability = values.paid_limit_up_probability ?? row.paid_limit_up_probability;
    if (!tradeDate || !isFiniteNumber(probability)) return;
    const entry = { probability, row };
    const symbol = row.symbol || values.symbol;
    if (symbol) map.set(`${symbol}|${tradeDate}`, entry);
    const code = normalizeStockSymbol(symbol || values.stock_code || values.code);
    if (code) map.set(`${code}|${tradeDate}`, entry);
  });
  return map;
}

function normalizeStockSymbol(value) {
  const digits = String(value ?? "").replace(/\D/g, "");
  if (!digits) return "";
  return digits.length >= 6 ? digits.slice(-6) : digits.padStart(6, "0");
}

function baiduStockUrl(symbol) {
  const code = normalizeStockSymbol(symbol);
  return code ? `https://finance.baidu.com/stock/ab-${code}` : "";
}

function renderStockFinanceName(symbol, primary, secondary = "") {
  const code = normalizeStockSymbol(symbol);
  const url = baiduStockUrl(code);
  const primaryText = primary || code || "-";
  const secondaryText = secondary || (code && primaryText !== code ? code : "");
  const body = `<strong>${escapeHtml(primaryText)}</strong>${secondaryText ? `<span>${escapeHtml(secondaryText)}</span>` : ""}`;
  if (!url) return `<span class="stock-finance-name">${body}</span>`;
  return `<a class="stock-finance-name" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer" title="${escapeHtml(`在百度股市打开 ${code}`)}">${body}</a>`;
}

function escapeClass(value) {
  return String(value || "pending").toLowerCase().replace(/[^a-z0-9_-]+/g, "-") || "pending";
}

function formatRatioPercent(value) {
  if (!isFiniteNumber(value)) return "-";
  return `${(Number(value) * 100).toFixed(1)}%`;
}

function hotTierLabel(value) {
  const number = Number(value);
  if (Number.isFinite(number) && number > 0) return `${number}板`;
    return "读取失败，页面已保留中文空态。";
}

function candidateBatchTypeLabel(value) {
  const map = {
    source_standard_limit_event: "已入库涨停事实",
    external_ths_model: "同花顺候选模型",
    public_limitup_draft: "公开涨停池草稿",
  };
  return map[String(value || "")] || businessStatusLabel(value);
}

function candidateStatusLabel(status) {
  const map = {
    standard_source_loaded: "已读到候选",
    waiting_probability: "等待自动抓取",
  empty: "空",
    partial_source: "部分数据降级",
  };
  return map[String(status || "")] || businessStatusLabel(status || "waiting");
}

function candidateAuditLabel(status) {
  const map = {
  ready: "就绪",
  passed: "通过",
    blocked: "阻断",
    pending: "等待抓取",
    not_applicable: "等待候选",
  warning: "预警",
    fetching: "自动抓取中",
    partial: "部分入库",
    pending_cookie: "等待登录 Cookie",
    cookie_expired: "登录 Cookie 已失效",
    abandoned_no_probability_before_deadline: "本批已放弃",
    status_unknown: "状态读取中",
  };
  return map[String(status || "")] || businessStatusLabel(status || "pending");
}

function candidateAuditReasonLabel(reason) {
  const map = {
    missing_paid_prior: "缺少同花顺次日概率",
    paid_probability_cookie_missing: "缺少同花顺登录 Cookie",
    paid_probability_cookie_expired: "同花顺登录 Cookie 已失效",
    paid_probability_batch_abandoned: "本批候选已在下一个交易日 09:00 后放弃",
    invalid_p_limit_up_range: "同花顺概率超出 0-100",
    no_limitup_candidate: "当天没有可展示的收盘封板候选",
    source_read_degraded: "部分标准事实读取降级",
    source_enrichment_degraded: "部分辅助事实稍后刷新",
    paid_probability_read_degraded: "付费概率状态读取降级",
  };
  return map[String(reason || "")] || businessStatusLabel(reason);
}

function paidProbabilityCookieStatusLabel(status) {
  const map = {
    missing: "未配置",
    pending_probe: "Cookie 可用",
    valid: "Cookie 可用",
    expired: "已失效",
    invalid: "不可用",
    read_failed: "读取失败",
  };
  return map[String(status || "missing")] || "待核验";
}

function paidProbabilityBatchStatusLabel(status) {
  const map = {
    no_candidates: "暂无候选",
    pending_cookie: "等待登录 Cookie",
    fetching: "自动抓取中",
    partial: "部分入库",
  ready: "就绪",
    cookie_expired: "登录 Cookie 已失效",
    abandoned_no_probability_before_deadline: "本批已放弃",
    status_unknown: "状态读取中",
  };
  return map[String(status || "status_unknown")] || "状态读取中";
}

function paidProbabilityDeadlineLabel(batchStatus) {
  if (batchStatus?.next_trade_date) return `${batchStatus.next_trade_date} 09:00`;
  if (batchStatus?.deadline_at) return formatDateTimeValue(batchStatus.deadline_at);
  return "下一个交易日 09:00";
}

function paidProbabilityBatchMessage(batchStatus, stats) {
  const status = String(stats?.batchStatus || batchStatus?.status || "status_unknown");
  const cookieStatus = String(stats?.cookieStatus || batchStatus?.cookie_status || "");
  if (status === "abandoned_no_probability_before_deadline") {
    if (["expired", "invalid"].includes(cookieStatus)) return "真实接口探测失败且已过放弃时间，本批候选已放弃。";
    return `已过 ${paidProbabilityDeadlineLabel(batchStatus)} 仍未取得付费概率，本批候选已放弃。`;
  }
  if (status === "cookie_expired") return "真实接口探测失败，请更新登录 Cookie。";
  if (status === "pending_cookie") return "未读取到留存 Cookie，请配置后抓取。";
  if (status === "fetching") return "Cookie 已留存，正在等待付费概率入库。";
  if (status === "partial") return "部分概率已入库，剩余候选继续等待抓取。";
  if (status === "ready") return "本批候选付费概率已入库。";
  if (status === "no_candidates") return "当前没有可抓取的收盘封板候选。";
  return "等待 source-data-service 返回抓取状态。";
}

function isPaidProbabilityCookieUsable(status) {
  return ["valid", "pending_probe"].includes(String(status || ""));
}

function shouldShowPaidProbabilityCookieForm(stats) {
  return stats.cookieStatus === "missing"
    || ["expired", "invalid"].includes(stats.cookieStatus)
    || stats.batchStatus === "cookie_expired";
}

function paidProbabilityRowStatusInfo(item) {
  if (isFiniteNumber(item.ths_limit_up_probability)) {
    return { label: "已入库", tone: "ready", detail: item.paid_probability_updated_at ? `更新 ${formatDateTimeValue(item.paid_probability_updated_at)}` : "来自付费概率 source 表" };
  }
  const batchStatus = state.candidateSource.paidProbabilityBatchStatus || {};
  const status = String(batchStatus.status || "");
  if (status === "abandoned_no_probability_before_deadline") {
    return { label: "本批已放弃", tone: "blocked", detail: `超过 ${paidProbabilityDeadlineLabel(batchStatus)} 仍未取得概率` };
  }
  if (status === "cookie_expired") {
    return { label: "Cookie 已失效", tone: "blocked", detail: "真实探测失败后需要更新登录 Cookie" };
  }
  if (status === "pending_cookie") {
    return { label: "等待 Cookie", tone: "warning", detail: "配置登录 Cookie 后自动抓取" };
  }
  if (status === "status_unknown") {
    return { label: "状态读取中", tone: "warning", detail: "暂未读到批次状态，不判定 Cookie 失效" };
  }
  if (status === "partial") {
    return { label: "部分入库", tone: "warning", detail: `截止 ${paidProbabilityDeadlineLabel(batchStatus)} 前继续抓取` };
  }
    return { label: "部分入库", tone: "warning", detail: `截止 ${paidProbabilityDeadlineLabel(batchStatus)} 前继续抓取` };
}

function formatLimitUpTime(value) {
  if (value === null || value === undefined || value === "") return "等待真实时间";
  if (typeof value === "string" && value.includes(":") && !/^\d+(\.\d+)?$/.test(value.trim())) {
    return formatDateTimeValue(value).replace(/^\d{4}-\d{2}-\d{2}\s*/, "") || value;
  }
  const seconds = Number(value);
  if (!Number.isFinite(seconds) || seconds <= 0) return display(value, "等待真实时间");
  const date = new Date(seconds * 1000);
  if (Number.isNaN(date.getTime())) return "等待真实时间";
  return date.toLocaleTimeString("zh-CN", {
    timeZone: "Asia/Shanghai",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function buildLimitUpPatternTag(item) {
  const openCount = Number(item.limit_up_open_count ?? item.open_num);
  const limitUpType = String(item.limit_up_type || "").trim();
  const first = formatLimitUpTime(item.first_limit_up_at || item.first_limit_up_time || item.limit_up_time);
  const last = formatLimitUpTime(item.last_limit_up_at || item.last_limit_up_time || item.first_limit_up_at || item.first_limit_up_time || item.limit_up_time);
  if (limitUpType.includes("一字")) return "一字板";
  if (limitUpType.includes("T字")) return "T字板";
  if (Number.isFinite(openCount) && openCount > 0) return `开板${openCount}次回封`;
  if (first !== "等待真实时间" && last !== "等待真实时间" && first !== last) return "回封";
  if (limitUpType.includes("一字")) return "一字板";
  return "封板";
}

function renderGateNotice(title, detail) {
  return `<div class="render-gate-notice"><strong>${escapeHtml(title)}</strong><span>${escapeHtml(detail)}</span></div>`;
}

async function loadCandidateSourceData(force = false, pageEpoch = state.pageEpoch, routeKey = "candidates") {
  if (state.candidateSource.loading) return;
  if (state.candidateSource.loaded && !force) return;
  state.candidateSource.loading = true;
  state.candidateSource.error = null;
  state.candidateSource.sourceReadState = "reading";
  if (!isStalePage(pageEpoch, routeKey)) {
    if (state.candidateSource.loaded) renderCandidatePage({ pageEpoch, routeKey });
    else renderCandidateLoading();
  }
  try {
    const cookieStatusTask = safeLoad(() => sourcePaidProbabilityApi("cookie/status", { timeoutMs: FRONTEND_SOURCE_STATUS_TIMEOUT_MS }));
    const eventResult = await loadLatestSourceRows("source.limit_event_v1", PREFERRED_CANDIDATE_TRADE_DATE, FRONTEND_SOURCE_STATUS_TIMEOUT_MS);
    if (isStalePage(pageEpoch, routeKey)) return;
    const displayRows = eventResult.rows;
    const tradeDate = eventResult.tradeDate || PREFERRED_CANDIDATE_TRADE_DATE;
    const hasDisplayRows = displayRows.length > 0;
    const emptyLoad = Promise.resolve({ ok: true, data: [] });
    const [sourceRows, dailyRows, limitPriceRows, moneyflowRows, paidProbabilityRows, cookieStatus, batchStatus] = await Promise.all([
      Promise.resolve({ ok: true, data: displayRows }),
      hasDisplayRows ? safeLoad(() => loadSourceRows("source.daily_bar_v1", tradeDate ? { trade_date: tradeDate } : {}, FRONTEND_FAST_TIMEOUT_MS)) : emptyLoad,
      hasDisplayRows ? safeLoad(() => loadSourceRows("source.limit_price_v1", tradeDate ? { trade_date: tradeDate } : {}, FRONTEND_FAST_TIMEOUT_MS)) : emptyLoad,
      hasDisplayRows ? safeLoad(() => loadSourceRows("source.stock_moneyflow_daily_v1", tradeDate ? { trade_date: tradeDate } : {}, FRONTEND_FAST_TIMEOUT_MS)) : emptyLoad,
      hasDisplayRows ? safeLoad(() => loadSourceRows("source.ths_paid_limit_up_probability_v1", tradeDate ? { trade_date: tradeDate } : {}, FRONTEND_SOURCE_STATUS_TIMEOUT_MS)) : emptyLoad,
      cookieStatusTask,
      hasDisplayRows && tradeDate ? safeLoad(() => sourcePaidProbabilityApi(`batch-status?trade_date=${encodeURIComponent(tradeDate)}`, { timeoutMs: FRONTEND_SOURCE_STATUS_TIMEOUT_MS })) : emptyLoad,
    ]);
    const paidProbabilityErrors = [paidProbabilityRows, cookieStatus, batchStatus]
      .filter((item) => !item.ok)
      .map((item) => safeLoadErrorLabel(item.error));
    const enrichmentReasons = [dailyRows, limitPriceRows, moneyflowRows, paidProbabilityRows, cookieStatus, batchStatus]
      .filter((item) => !item.ok)
      .map((item) => safeLoadErrorLabel(item.error));
    const degradedReasons = [];
    const sourceReadState = displayRows.length
      ? "preferred_ready"
      : eventResult.fallbackRows.length
        ? "fallback_visible"
        : "preferred_empty";
    if (PREFERRED_CANDIDATE_TRADE_DATE && !eventResult.preferredUsed && eventResult.fallbackRows.length) {
      degradedReasons.push(`没有读到 ${candidateRequestedTradeDateLabel()} 的候选；只看到 ${eventResult.fallbackTradeDate || "其他日期"} 的历史记录。`);
    }
    const previousCookieStatus = state.candidateSource.paidProbabilityCookieStatus;
    const previousBatchStatus = state.candidateSource.paidProbabilityBatchStatus;
    const resolvedCookieStatus = cookieStatus.ok
      ? cookieStatus.data
      : previousCookieStatus || {
          configured: null,
          status: "read_failed",
          read_error: safeLoadErrorLabel(cookieStatus.error),
        };
    const resolvedBatchStatus = batchStatus.ok
      ? batchStatus.data
      : previousBatchStatus || {
          trade_date: tradeDate,
          status: hasDisplayRows ? "status_unknown" : "no_candidates",
          message: batchStatus.error ? safeLoadErrorLabel(batchStatus.error) : "批次状态暂未读到",
        };
    state.candidateSource = {
      loaded: true,
      loading: false,
      tradeDate,
      preferredTradeDate: PREFERRED_CANDIDATE_TRADE_DATE,
      preferredTradeDateLoaded: eventResult.preferredUsed,
      fallbackTradeDate: eventResult.fallbackTradeDate || null,
      sourceReadState,
      sourceRows: arrayFromResponse(sourceRows.data),
      allEventRows: eventResult.fallbackRows.length ? eventResult.fallbackRows : eventResult.rows,
      dailyRows: arrayFromResponse(dailyRows.data),
      limitPriceRows: arrayFromResponse(limitPriceRows.data),
      moneyflowRows: arrayFromResponse(moneyflowRows.data),
      paidProbabilityRows: arrayFromResponse(paidProbabilityRows.data),
      paidProbabilityCookieStatus: resolvedCookieStatus,
      paidProbabilityBatchStatus: resolvedBatchStatus,
      paidProbabilityError: uniqueMessages(paidProbabilityErrors).join("；") || null,
      enrichmentError: uniqueMessages(enrichmentReasons).join("；") || null,
      error: uniqueMessages(degradedReasons).join("；") || null,
    };
    state.candidateRows = buildCandidateRowsFromSource();
  } catch (error) {
    if (isStalePage(pageEpoch, routeKey)) return;
    if (state.candidateSource.loaded) {
      state.candidateSource = {
        ...state.candidateSource,
        loading: false,
        sourceReadState: "read_failed",
        error: frontendErrorLabel(error),
      };
    } else {
      state.candidateSource = {
        ...state.candidateSource,
        loaded: true,
        loading: false,
        sourceReadState: "read_failed",
        paidProbabilityRows: [],
        paidProbabilityCookieStatus: null,
        paidProbabilityBatchStatus: null,
        paidProbabilityError: null,
        enrichmentError: null,
        error: frontendErrorLabel(error),
      };
      state.candidateRows = [];
    }
  }
  if (!isStalePage(pageEpoch, routeKey)) renderCandidatePage({ pageEpoch, routeKey });
}

function buildCandidateRowsFromSource() {
  const daily = bySymbol(state.candidateSource.dailyRows);
  const limitPrice = bySymbol(state.candidateSource.limitPriceRows);
  const moneyflow = bySymbol(state.candidateSource.moneyflowRows);
  const paidProbability = candidatePaidProbabilityMap(state.candidateSource.paidProbabilityRows);
  return uniqueCandidateSourceRows(state.candidateSource.sourceRows.filter(isClosedLimitCandidate))
    .map((row, index) => {
      const values = rowValues(row);
      const dailyValues = rowValues(daily.get(row.symbol));
      const limitPriceValues = rowValues(limitPrice.get(row.symbol));
      const moneyflowValues = rowValues(moneyflow.get(row.symbol));
      const key = candidateKey(row);
      const paidEntry = paidProbability.get(key) || paidProbability.get(candidateCodeKey(row));
      const paidRow = paidEntry?.row || null;
      const paidRowValues = rowValues(paidRow);
      const stockName = values.stock_name || values.name || values.name_at_snapshot || row.stock_name || row.name || null;
      const gaps = [];
      if (!daily.get(row.symbol)) gaps.push("source_gap:daily_bar_same_day_missing");
      if (!limitPrice.get(row.symbol)) gaps.push("source_gap:limit_price_missing");
      if (!moneyflow.get(row.symbol)) gaps.push("source_gap:stock_moneyflow_same_day_missing");
      if (!paidEntry) gaps.push("source_gap:ths_paid_probability_missing");
      return {
        instrument_id: row.symbol,
        symbol: row.symbol,
        stock_name: stockName,
        rank_no: index + 1,
        source_rank_no: values.rank_no || values.source_rank_no || null,
        trade_date: row.trade_date,
        limit_up_stage: values.limit_up_stage ?? null,
        limit_up_stage_label: values.limit_event_type === "t_board_limit_up" ? "T字板" : "涨停",
        limit_up_type: limitPatternText(values),
        limit_up_reason: values.limit_up_reason || values.reason || values.reason_type || null,
        limit_up_open_count: values.limit_open_count ?? null,
        first_limit_up_at: values.first_limit_up_at || values.first_limit_up_time || null,
        last_limit_up_at: values.last_limit_up_at || values.last_limit_up_time || null,
        ths_limit_up_probability: paidEntry?.probability ?? null,
        p_limit_up_source: paidEntry ? "source.ths_paid_limit_up_probability_v1" : null,
        paid_probability_updated_at: paidRow?.updated_at || paidRow?.available_at || paidRowValues.available_at || null,
        limit_event_type: values.limit_event_type,
        is_one_word_board: boolValue(values.is_one_word_board),
        is_break_limit: boolValue(values.is_break_limit),
        close_on_limit_flag: boolValue(values.close_on_limit_flag),
        up_limit_price: limitPriceValues.up_limit_price,
        close_price: dailyValues.close_price,
        pct_chg: dailyValues.pct_chg,
        amount: dailyValues.amount,
        main_net_inflow: moneyflowValues.main_net_inflow,
        source_quality_status: row.source_quality_status,
        primary_provider: row.primary_provider,
        available_at: row.available_at,
        updated_at: row.updated_at || row.available_at,
        source_pk: row.source_pk,
        raw_payload_id: values.raw_payload_id || row.raw_payload_id || row.source_pk || null,
        change_tag: values.change_tag || null,
        source_gap_codes: gaps,
      };
    });
}

function renderCandidateLoading() {
  const root = $("#page-root");
  if (!root) return;
  root.innerHTML = renderCandidateDraftWorkbench(buildCandidateDraftContext());
  bindCandidateActions();
}

async function renderCandidatePage(options = {}) {
  const pageEpoch = options.pageEpoch ?? state.pageEpoch;
  const routeKey = options.routeKey ?? "candidates";
  if (isStalePage(pageEpoch, routeKey)) return;
  if (!state.candidateSource.loaded && !state.candidateSource.loading) {
    await loadCandidateSourceData(false, pageEpoch, routeKey);
    return;
  }
  if (isStalePage(pageEpoch, routeKey)) return;
  $("#page-root").innerHTML = renderCandidateDraftWorkbench(buildCandidateDraftContext());
  bindCandidateActions();
}

function buildCandidateDraftContext() {
  const rows = state.candidateRows || [];
  const latestAt = rows.map((item) => item.updated_at || item.available_at).filter(Boolean).sort().at(-1);
  const paidBatchStatus = state.candidateSource.paidProbabilityBatchStatus || {};
  const batch = {
    batch_id: `source-${state.candidateSource.tradeDate || "latest"}`,
    business_date: selectedBusinessDateLabel(state.candidateSource.tradeDate),
    ingest_mode: "source_standard_limit_event",
    batch_status: rows.length ? (paidBatchStatus.status || "waiting_probability") : "empty",
    updated_at: latestAt,
    item_count: rows.length,
  };
  const audit = buildCandidateDraftAudit(rows);
  return { batch, items: rows, audit };
}

function buildCandidateDraftAudit(items) {
  const total = items.length;
  const missingProbability = items.filter((item) => !isFiniteNumber(item.ths_limit_up_probability)).length;
  const invalidProbability = items.filter((item) => {
    if (!isFiniteNumber(item.ths_limit_up_probability)) return false;
    const value = Number(item.ths_limit_up_probability);
    return value < 0 || value > 100;
  }).length;
  const blockingReasons = [];
  const warningReasons = [];
  const paidBatchStatus = state.candidateSource.paidProbabilityBatchStatus || {};
  const cookieStatus = state.candidateSource.paidProbabilityCookieStatus || {};
  if (!total) blockingReasons.push("no_limitup_candidate");
  if (missingProbability) {
    if (paidBatchStatus.status === "abandoned_no_probability_before_deadline") blockingReasons.push("paid_probability_batch_abandoned");
    else if (paidBatchStatus.status === "cookie_expired" || ["expired", "invalid"].includes(cookieStatus.status)) blockingReasons.push("paid_probability_cookie_expired");
    else if (paidBatchStatus.status === "pending_cookie" || cookieStatus.status === "missing") blockingReasons.push("paid_probability_cookie_missing");
    else warningReasons.push("missing_paid_prior");
  }
  if (invalidProbability) blockingReasons.push("invalid_p_limit_up_range");
  if (state.candidateSource.error) warningReasons.push("source_read_degraded");
  if (state.candidateSource.enrichmentError) warningReasons.push("source_enrichment_degraded");
  if (state.candidateSource.paidProbabilityError) warningReasons.push("paid_probability_read_degraded");
  const ready = total > 0 && missingProbability === 0 && invalidProbability === 0;
  return {
    status: blockingReasons.length ? "blocked" : ready ? "ready" : "pending",
    blocking_reasons: blockingReasons,
    warning_reasons: warningReasons,
  };
}

function renderCandidateDraftWorkbench(context) {
  const batch = context.batch || {};
  const items = Array.isArray(context.items) ? context.items : [];
  const audit = context.audit || {};
  const stats = buildCandidateDraftStats(batch, items, audit);
  return `<div class="candidate-workbench">
    ${renderCandidateDraftHero(batch, stats)}
    ${renderCandidateDraftKpis(stats)}
    <section class="candidate-draft-main-grid">
      ${renderCandidatePaidProbabilityPanel(batch, items, stats)}
      ${renderCandidateDraftGate(batch, audit, stats)}
      ${renderCandidateSourceEvidencePanel(items)}
    </section>
  </div>`;
}

function buildCandidateDraftStats(batch, items, audit) {
  const total = items.length;
  const filled = items.filter((item) => isFiniteNumber(item.ths_limit_up_probability)).length;
  const invalidProbability = items.filter((item) => {
    if (!isFiniteNumber(item.ths_limit_up_probability)) return false;
    const value = Number(item.ths_limit_up_probability);
    return value < 0 || value > 100;
  }).length;
  const stage1 = items.filter((item) => Number(item.limit_up_stage) === 1).length;
  const stage2 = items.filter((item) => Number(item.limit_up_stage) === 2).length;
  const tBoard = items.filter((item) => item.limit_event_type === "t_board_limit_up").length;
  const reasonCovered = items.filter((item) => item.limit_up_reason).length;
  const allEventCount = state.candidateSource.sourceRows.length;
  const closedEventRows = state.candidateSource.sourceRows.filter(isClosedLimitCandidate);
  const duplicateClosedEventCount = Math.max(0, closedEventRows.length - total);
  const filteredCount = duplicateClosedEventCount + state.candidateSource.sourceRows.filter((row) => {
    const values = rowValues(row);
    return values.limit_event_type === "limit_up_broken" || boolValue(values.close_on_limit_flag) === false;
  }).length;
  const allReadableEventCount = state.candidateSource.allEventRows.length || state.candidateSource.sourceRows.length;
  const missingCount = Math.max(0, total - filled);
  const blocked = audit.status === "blocked";
  const paidBatchStatus = state.candidateSource.paidProbabilityBatchStatus || {};
  const cookieStatus = state.candidateSource.paidProbabilityCookieStatus || {};
  const cookieStatusValue = cookieStatus.status || (total ? "read_failed" : "missing");
  const batchStatus = paidBatchStatus.status || (total ? "status_unknown" : "no_candidates");
  const sourceReady = total > 0 && missingCount === 0 && !blocked;
  const hasCandidates = total > 0;
  let gateText = "等待当天涨停候选";
  if (hasCandidates && batchStatus === "abandoned_no_probability_before_deadline") gateText = "本批候选已按规则放弃";
  else if (hasCandidates && (batchStatus === "cookie_expired" || ["expired", "invalid"].includes(cookieStatusValue))) gateText = "登录 Cookie 已失效";
  else if (hasCandidates && (batchStatus === "pending_cookie" || cookieStatusValue === "missing")) gateText = "需要配置登录 Cookie";
  else if (hasCandidates && batchStatus === "status_unknown") gateText = "付费概率状态读取中";
  else if (hasCandidates && sourceReady) gateText = "付费概率已入库";
  else if (hasCandidates && batchStatus === "partial") gateText = `还差 ${missingCount} 只概率`;
  else if (hasCandidates) gateText = "等待自动抓取概率";
  return {
    total,
    hasCandidates,
    filled,
    missingCount,
    invalidProbability,
    fillRate: total ? filled / total : 0,
    stage1,
    stage2,
    tBoard,
    reasonCovered,
    reasonCoverage: total ? reasonCovered / total : 0,
    allEventCount,
    allReadableEventCount,
    filteredCount,
    auditStatus: batchStatus === "ready" ? "ready" : audit.status || batch.batch_status || "pending",
    blocked,
    sourceReady,
    batchStatus,
    cookieStatus: cookieStatusValue,
    readState: state.candidateSource.sourceReadState || "waiting",
    readStateLabel: candidateReadStateLabel(state.candidateSource.sourceReadState),
    readDetail: candidateReadDetail(),
    probabilityText: hasCandidates ? `${filled}/${total}` : "等待候选",
    probabilitySubtext: hasCandidates ? paidProbabilityBatchStatusLabel(batchStatus) : "没有可抓取股票",
    reasonText: hasCandidates ? `${reasonCovered}/${total}` : "等待候选",
    reasonSubtext: hasCandidates ? formatRatioPercent(reasonCovered / total) : "没有可核对原因",
    gateText,
  };
}

function renderCandidateDraftHero(batch, stats) {
  return `<section class="candidate-draft-hero candidate-draft-hero--${escapeClass(stats.auditStatus)}">
    <div>
      <span class="hot-mini-label">当前候选草稿</span>
      <strong>${escapeHtml(stats.gateText)}</strong>
      <p>${escapeHtml(stats.readDetail || "候选事实来自已入库涨停数据；同花顺付费概率由 source-data-service 使用登录 Cookie 自动抓取并入库。")}</p>
    </div>
    <dl>
      <div><dt>业务日</dt><dd>${escapeHtml(display(batch.business_date))}</dd></div>
      <div><dt>候选来源</dt><dd>${escapeHtml(candidateBatchTypeLabel(batch.ingest_mode))}</dd></div>
      <div><dt>最近入库</dt><dd>${escapeHtml(formatDateTimeValue(batch.updated_at))}</dd></div>
      <div><dt>读取状态</dt><dd>${escapeHtml(stats.readStateLabel)}</dd></div>
    </dl>
  </section>`;
}

function renderCandidateDraftKpis(stats) {
  const kpis = [
    ["候选数量", stats.total, "收盘封板候选"],
    ["概率补齐", stats.probabilityText, stats.probabilitySubtext],
    ["一板 / 二板", stats.hasCandidates ? `${stats.stage1}/${stats.stage2}` : "等待候选", stats.tBoard ? `T字板 ${stats.tBoard} 只` : "等待梯队"],
    ["涨停原因", stats.reasonText, stats.reasonSubtext],
    ["数据检查", candidateAuditLabel(stats.auditStatus), stats.blocked ? "存在阻断" : "等待候选"],
    ["Cookie 状态", paidProbabilityCookieStatusLabel(stats.cookieStatus), stats.hasCandidates ? `截止 ${paidProbabilityDeadlineLabel(state.candidateSource.paidProbabilityBatchStatus || {})}` : "等待候选"],
  ];
  return `<section class="candidate-kpi-grid">${kpis.map(([title, value, sub]) => renderCandidateKpi(title, value, sub)).join("")}</section>`;
}

function renderCandidateKpi(title, value, sub) {
  return `<article class="hot-kpi-card"><span>${escapeHtml(title)}</span><strong>${escapeHtml(String(value))}</strong><small>${escapeHtml(sub)}</small></article>`;
}

function renderCandidatePaidProbabilityPanel(batch, items, stats) {
  const batchStatus = state.candidateSource.paidProbabilityBatchStatus || {};
  const fetchDisabled = !items.length
    || stats.batchStatus === "abandoned_no_probability_before_deadline"
    || !isPaidProbabilityCookieUsable(stats.cookieStatus);
  return `<section class="panel candidate-editor-panel">
    <div class="panel__head">
      <div><h2 class="panel-title">同花顺付费概率抓取</h2><p class="candidate-section-note">候选榜概率只读展示 source 入库结果；Cookie 只用于付费概率接口，其他同花顺公开接口保持原样。</p></div>
      <div class="candidate-actions">
        <button class="secondary-button" data-action="reload-candidates">重新读取事实</button>
      </div>
    </div>
    ${renderCandidateCookieConfigPanel(stats)}
    <div class="candidate-editor-toolbar">
      <span>入库进度：${escapeHtml(stats.probabilityText)}</span>
      <span>放弃时间：${escapeHtml(paidProbabilityDeadlineLabel(batchStatus))}</span>
      <span>批次状态：${escapeHtml(paidProbabilityBatchStatusLabel(stats.batchStatus))}</span>
      <span>过滤事件：${stats.filteredCount}/${stats.allReadableEventCount}</span>
    </div>
    <div class="candidate-probability-table-wrap">
      <table class="candidate-probability-table">
        <thead><tr><th>股票</th><th>梯队</th><th>首次涨停时间</th><th>最后涨停时间</th><th>形态</th><th>涨停原因</th><th>同花顺次日概率</th><th>状态</th></tr></thead>
        <tbody>${items.length ? items.map((item, index) => renderCandidateProbabilityRow(item, index)).join("") : renderEmptyTableRow(8, `没有读到 ${selectedBusinessDateLabel(state.candidateSource.tradeDate)} 的收盘封板候选。`)}</tbody>
      </table>
    </div>
    <footer class="candidate-editor-footer">
      <span>${escapeHtml(candidateEditorFooterText(stats))}</span>
      <button class="primary-button" data-action="fetch-paid-probability" ${fetchDisabled ? "disabled" : ""}>立即抓取</button>
    </footer>
  </section>`;
}

function renderCandidateCookieConfigPanel(stats) {
  const cookie = state.candidateSource.paidProbabilityCookieStatus || {};
  const batchStatus = state.candidateSource.paidProbabilityBatchStatus || {};
  const cookieSummary = cookie.configured
    ? `${cookie.user_masked || "user已保存"} / ${cookie.userid_masked || "userid已保存"}`
    : stats.cookieStatus === "read_failed" ? "状态暂未读到" : "未配置";
  const statusTone = stats.batchStatus === "abandoned_no_probability_before_deadline"
    ? "blocked"
    : isPaidProbabilityCookieUsable(stats.cookieStatus) ? "ready" : "warning";
  const showForm = shouldShowPaidProbabilityCookieForm(stats);
  const formHtml = showForm ? `
    <form class="candidate-cookie-form" data-form="ths-paid-cookie" autocomplete="off">
      <label><span>user</span><input class="field" name="user" type="password" autocomplete="off" placeholder="填写登录后的 user Cookie"></label>
      <label><span>userid</span><input class="field" name="userid" type="text" autocomplete="off" placeholder="填写登录后的 userid"></label>
      <button class="primary-button" type="submit">保存并抓取</button>
      <span class="status-pill status-${statusTone}">${escapeHtml(paidProbabilityCookieStatusLabel(stats.cookieStatus))}</span>
    </form>` : `
    <div class="candidate-cookie-saved">
      <span class="status-pill status-${statusTone}">${escapeHtml(paidProbabilityCookieStatusLabel(stats.cookieStatus))}</span>
      <small>${escapeHtml(isPaidProbabilityCookieUsable(stats.cookieStatus) ? "已留存登录 Cookie；真实接口探测失败前不展示编辑入口。" : "状态读取中，不判定 Cookie 失效。")}</small>
    </div>`;
  return `<div class="candidate-cookie-config">
    <div class="candidate-cookie-status">
      <div><span>Cookie 状态</span><strong>${escapeHtml(paidProbabilityCookieStatusLabel(stats.cookieStatus))}</strong><small>${escapeHtml(cookieSummary)}</small></div>
      <div><span>批次状态</span><strong>${escapeHtml(paidProbabilityBatchStatusLabel(stats.batchStatus))}</strong><small>${escapeHtml(paidProbabilityBatchMessage(batchStatus, stats))}</small></div>
      <div><span>放弃规则</span><strong>${escapeHtml(paidProbabilityDeadlineLabel(batchStatus))}</strong><small>未到该时间只阻断，不放弃候选</small></div>
    </div>
    ${formHtml}
  </div>`;
}

function candidateEditorFooterText(stats) {
  if (!stats.hasCandidates) return "暂无可抓取概率的候选，请先等待当天涨停事实入库。";
  if (stats.batchStatus === "abandoned_no_probability_before_deadline") return "本批候选已在放弃时间后仍未取得付费概率，按规则放弃，不再补抓进入候选榜。";
  if (stats.cookieStatus === "missing") return "请先填写同花顺登录 Cookie，提交后会自动触发付费概率抓取。";
  if (["expired", "invalid"].includes(stats.cookieStatus) || stats.batchStatus === "cookie_expired") return "真实接口探测显示登录 Cookie 不可用，请提交新的 Cookie 替换留存值。";
  if (stats.cookieStatus === "read_failed" || stats.batchStatus === "status_unknown") return "状态暂未读到，不判定 Cookie 失效；页面不会展示编辑入口。";
  if (stats.missingCount) return `还缺 ${stats.missingCount} 只概率，未到放弃时间前保持阻断等待。`;
  if (stats.invalidProbability) return "存在超出 0-100 的概率，请先修正。";
    return "读取失败，页面已保留中文空态。";
}

function renderCandidateProbabilityRow(item, index) {
  const probability = isFiniteNumber(item.ths_limit_up_probability) ? Number(item.ths_limit_up_probability) : null;
  const missing = probability === null;
  const statusInfo = paidProbabilityRowStatusInfo(item);
  const stockName = stockNameLabel(item.stock_name || item.name, item.symbol);
  const reasonText = item.limit_up_reason || canonicalMissingLabel("limit_up_reason");
  const firstLimitUpTimeText = formatLimitUpTime(item.first_limit_up_at || item.first_limit_up_time || item.limit_up_time);
  const lastLimitUpTimeText = formatLimitUpTime(item.last_limit_up_at || item.last_limit_up_time || item.first_limit_up_at || item.first_limit_up_time || item.limit_up_time);
  const patternTag = buildLimitUpPatternTag(item);
  return `<tr class="${missing ? "row-invalid" : ""}">
    <td>${renderStockFinanceName(item.symbol, item.symbol || "-", stockName)}<small>成交 ${escapeHtml(formatMoneyWan(item.amount))} · 涨停价 ${escapeHtml(formatPrice(item.up_limit_price))}</small></td>
    <td>${escapeHtml(hotTierLabel(item.limit_up_stage))}<small>${escapeHtml(item.limit_up_type || item.limit_up_stage_label ? businessStatusLabel(item.limit_up_type || item.limit_up_stage_label) : "")}</small></td>
    <td class="candidate-time-cell">${escapeHtml(firstLimitUpTimeText)}</td>
    <td class="candidate-time-cell">${escapeHtml(lastLimitUpTimeText)}</td>
    <td><span class="candidate-pattern-tag">${escapeHtml(patternTag)}</span></td>
    <td class="candidate-reason-cell"><strong>${escapeHtml(reasonText)}</strong><small>主力 ${escapeHtml(formatMoneyWan(item.main_net_inflow))} · ${escapeHtml(providerLabel(item.primary_provider))}</small></td>
    <td><strong class="candidate-probability-value">${escapeHtml(probability === null ? "等待入库" : formatPercentValue(probability))}</strong><small>${escapeHtml(statusInfo.detail)}</small></td>
    <td><span class="status-pill status-${escapeClass(statusInfo.tone)}">${escapeHtml(statusInfo.label)}</span><small>${escapeHtml(sourceQualityLabel(item.source_quality_status))} · ${escapeHtml(item.source_gap_codes?.length ? `${item.source_gap_codes.length} 个待补事实` : "事实可读")}</small></td>
  </tr>`;
}

function renderCandidateDraftGate(batch, audit, stats) {
  const reasons = [...(audit.blocking_reasons || []), ...(audit.warning_reasons || [])];
  const checks = [
    ["当天候选已读到", stats.total > 0],
    ["收盘仍封板", stats.total > 0 && stats.total + stats.filteredCount <= stats.allReadableEventCount],
    ["付费概率已入库", stats.total > 0 && stats.missingCount === 0],
    ["概率范围有效", stats.total > 0 && !(audit.blocking_reasons || []).includes("invalid_p_limit_up_range")],
    ["数据检查通过", audit.status === "ready" || audit.status === "passed"],
    ["Cookie 可用", isPaidProbabilityCookieUsable(stats.cookieStatus) && stats.batchStatus !== "cookie_expired"],
  ];
  return `<aside class="panel candidate-gate-panel">
    <div class="panel__head"><h2 class="panel-title">入库前检查</h2><span class="status-pill status-${stats.sourceReady ? "ready" : stats.blocked ? "blocked" : "warning"}">${stats.sourceReady ? "已入库" : stats.blocked ? "阻断" : "等待"}</span></div>
    <div class="candidate-gate-summary"><strong>${escapeHtml(stats.gateText)}</strong><span>未取得同花顺付费概率前，不允许进入评分、推荐或学习样本；下一个交易日 09:00 前只阻断等待，之后才放弃本批候选。</span></div>
    <div class="candidate-checklist">${checks.map(([label, ok]) => `<div class="${ok ? "is-ok" : "is-waiting"}"><span>${escapeHtml(label)}</span><b>${ok ? "通过" : "待处理"}</b></div>`).join("")}</div>
    ${reasons.length ? `<h3>当前阻断或等待原因</h3><ul class="hot-gap-list">${reasons.map((reason) => `<li><span>${escapeHtml(candidateAuditReasonLabel(reason))}</span><b>${reason.startsWith("missing") || reason.endsWith("degraded") ? "等待" : "阻断"}</b></li>`).join("")}</ul>` : renderGateNotice("暂无阻断原因", "数据检查未返回阻断项。")}
  </aside>`;
}

function renderCandidateSourceEvidencePanel(items) {
  const rows = candidateSourceEvidenceRows(items);
  return `<section class="panel candidate-source-panel">
    <div class="panel__head">
      <div><h2 class="panel-title">源数据复核</h2><p class="candidate-section-note">只读展示已入库涨停事实的关键字段，不参与概率、评分或后续生成判断。</p></div>
      <span class="status-pill status-ready">真实源字段</span>
    </div>
    <div class="candidate-source-rules">
      <div><strong>开板次数</strong><span>页面形态中的“开板N次”来自已入库开板次数。</span></div>
      <div><strong>回封状态</strong><span>T字板、回封和封板仅作形态展示，不改写涨停事实。</span></div>
      <div><strong>涨停原因</strong><span>只显示已入库原因，不用题材、概念或新闻兜底。</span></div>
    </div>
    ${rows.length ? `<div class="candidate-source-list">${rows.map(renderCandidateSourceEvidenceRow).join("")}</div>` : renderGateNotice("等待源字段", `当前没有 ${selectedBusinessDateLabel(state.candidateSource.tradeDate)} 可复核的涨停候选。`)}
  </section>`;
}

function candidateSourceEvidenceRows(items) {
  return [...(items || [])]
    .map((item) => {
  const openCount = Number(item.limit_up_open_count ?? item.open_num);
      return {
        item,
        openCount: Number.isFinite(openCount) ? openCount : null,
      };
    })
    .filter(({ item, openCount }) => openCount !== null || item.raw_payload_id || item.change_tag || item.source_quality_status)
    .sort((a, b) => Number(b.openCount || 0) - Number(a.openCount || 0))
    .slice(0, 6);
}

function renderCandidateSourceEvidenceRow(row) {
  const item = row.item || {};
  const openCount = row.openCount;
  const stockName = stockNameLabel(item.stock_name || item.name, item.symbol);
  const sourceText = item.source_pk ? "已入库留痕" : "等待源记录";
  const tagText = boolValue(item.is_break_limit) === true ? "回封形态" : buildLimitUpPatternTag(item);
  const patternText = Number.isFinite(openCount) && openCount > 0 ? `开板${openCount}次` : buildLimitUpPatternTag(item);
  return `<article class="candidate-source-row">
    <div class="candidate-source-stock">${renderStockFinanceName(item.symbol, item.symbol || "-", stockName)}</div>
    <dl>
      <div><dt>源记录</dt><dd>${escapeHtml(sourceText)}</dd></div>
      <div><dt>开板次数</dt><dd>${Number.isFinite(openCount) ? escapeHtml(String(openCount)) : "等待"}</dd></div>
      <div><dt>页面形态</dt><dd>${escapeHtml(patternText)}</dd></div>
      <div><dt>回封状态</dt><dd>${escapeHtml(tagText)}</dd></div>
    </dl>
  </article>`;
}

function renderCandidateRow(item, index) {
  return renderCandidateProbabilityRow(item, index);
}

function bindCandidateActions() {
  $("[data-action='reload-candidates']")?.addEventListener("click", () => loadCandidateSourceData(true));
  $("[data-action='fetch-paid-probability']")?.addEventListener("click", () => {
    triggerPaidProbabilityFetch();
  });
  $("[data-form='ths-paid-cookie']")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const payload = Object.fromEntries(new FormData(form).entries());
    const user = String(payload.user || "").trim();
    const userid = String(payload.userid || "").trim();
    if (!user || !userid) {
      toast("请填写 user 和 userid 后再提交。");
      return;
    }
    try {
      const savedStatus = await sourcePaidProbabilityApi("cookie", {
        method: "PUT",
        body: {
          user,
          userid,
          updated_by: state.user?.username || "shence-frontend-service",
        },
      });
      state.candidateSource.paidProbabilityCookieStatus = savedStatus;
      form.reset();
      toast("Cookie 已保存，开始抓取同花顺付费概率。");
      await triggerPaidProbabilityFetch({ silent: true });
    } catch (error) {
      toast(frontendErrorLabel(error));
      await loadCandidateSourceData(true);
    }
  });
}

async function triggerPaidProbabilityFetch(options = {}) {
  const tradeDate = state.candidateSource.tradeDate || PREFERRED_CANDIDATE_TRADE_DATE;
  if (!tradeDate) {
    toast("暂未读到可抓取的候选交易日。");
    return;
  }
  try {
    await sourcePaidProbabilityApi("fetch-current-batch", {
      method: "POST",
      body: {
        trade_date: tradeDate,
        request_source: "shence-frontend-service",
        dry_run: false,
      },
    });
    if (!options.silent) toast("已提交自动抓取任务。");
  } catch (error) {
    toast(frontendErrorLabel(error));
  } finally {
    await loadCandidateSourceData(true);
  }
}

async function renderModelPage(profile, options = {}) {
  const pageEpoch = options.pageEpoch ?? state.pageEpoch;
  const routeKey = options.routeKey ?? Object.entries(MODEL_PROFILES).find(([, item]) => item === profile)?.[0] ?? state.route;
  if (isStalePage(pageEpoch, routeKey)) return;
  const hasCachedRows = Array.isArray(state.modelReviewRows[profile.key]);
  const useCachedRows = Boolean(options.useCachedRows && hasCachedRows);
  const isSilentRefresh = Boolean(options.silentRefresh && hasCachedRows);
  let listRows = state.modelReviewRows[profile.key] || [];
  let extraData = state.modelReviewExtras[profile.key] || {};
  if (!useCachedRows) {
    if (hasCachedRows && !isSilentRefresh) {
      state.modelReviewRefreshState[profile.key] = { status: "loading", message: "正在更新，当前列表保持不变" };
      await renderModelPage(profile, { ...options, useCachedRows: true, silentRefresh: false });
      if (isStalePage(pageEpoch, routeKey)) return;
    } else {
      $("#page-root").innerHTML = `<section class="panel"><strong>正在读取 ${escapeHtml(profile.title)}...</strong></section>`;
    }
    let extra;
    try {
      extra = await safeLoad(() => loadModelExtra(profile));
      if (extra && extra.ok === false && hasCachedRows) throw new Error(safeLoadErrorLabel(extra.error));
      if (isStalePage(pageEpoch, routeKey)) return;
      listRows = await buildModelListRows(profile, extra);
      if (isStalePage(pageEpoch, routeKey)) return;
      state.modelReviewRows[profile.key] = listRows;
      state.modelReviewExtras[profile.key] = extra?.data || {};
      state.modelReviewErrors[profile.key] = collectModelLoadErrors(extra, listRows);
      delete state.modelReviewRefreshState[profile.key];
      extraData = state.modelReviewExtras[profile.key] || {};
    } catch (error) {
      if (isStalePage(pageEpoch, routeKey)) return;
      if (!hasCachedRows) throw error;
      listRows = state.modelReviewRows[profile.key] || [];
      extraData = state.modelReviewExtras[profile.key] || {};
      state.modelReviewErrors[profile.key] = [frontendErrorLabel(error)];
      state.modelReviewRefreshState[profile.key] = { status: "error", message: "刷新失败，已保留上次结果" };
    }
  }
  if (isStalePage(pageEpoch, routeKey)) return;
  const visibleRows = applyModelReviewFilters(profile, listRows);
  const loadErrors = state.modelReviewErrors[profile.key] || [];
  const refreshState = state.modelReviewRefreshState[profile.key] || null;
  if (isSilentRefresh && patchModelPageContent(profile, { pageEpoch, routeKey, listRows, visibleRows, loadErrors, refreshState, extraData })) {
    if (profile.key === "tboard") scheduleTBoardAutoRefresh(pageEpoch, routeKey);
    return;
  }
  $("#page-root").innerHTML = `
    <div class="model-workbench model-workbench--${escapeClass(profile.key)} model-decision-list-page model-decision-list-page--${escapeClass(profile.key)} model-golden-page--${escapeClass(profile.key)}">
      <div class="decision-review-sticky-stack">
        ${renderModelListPageLead(profile)}
        ${renderModelRefreshStatus(refreshState)}
        ${renderTBoardDay1ScanSummary(profile, extraData)}
        ${renderModelReviewFilters(profile, listRows.length, visibleRows.length)}
        ${renderHotReadinessKpis(profile, listRows, visibleRows)}
        ${renderModelListStickyHeader(profile)}
      </div>
      <section class="model-iteration-list model-iteration-list--${escapeClass(profile.key)} model-iteration-list--only">
        <div data-model-load-notice="true">${loadErrors.length ? renderModelLoadNotice(loadErrors) : ""}</div>
        ${renderModelListTable(profile, visibleRows)}
        ${renderHotReadinessCoverage(profile, listRows)}
      </section>
    </div>`;
  bindModelReviewActions(profile);
  bindModelListChrome();
  restoreModelFilterFocus(profile, options.focusFilterKey);
  if (profile.key === "tboard") scheduleTBoardAutoRefresh(pageEpoch, routeKey);
}

function patchModelPageFromState(profile, pageEpoch, routeKey) {
  const listRows = state.modelReviewRows[profile.key] || [];
  const extraData = state.modelReviewExtras[profile.key] || {};
  const visibleRows = applyModelReviewFilters(profile, listRows);
  return patchModelPageContent(profile, {
    pageEpoch,
    routeKey,
    listRows,
    visibleRows,
    loadErrors: state.modelReviewErrors[profile.key] || [],
    refreshState: state.modelReviewRefreshState[profile.key] || null,
    extraData,
  });
}

function patchModelPageContent(profile, context) {
  const { pageEpoch, routeKey, listRows, visibleRows, loadErrors, refreshState, extraData } = context;
  if (isStalePage(pageEpoch, routeKey)) return false;
  const page = document.querySelector(`.model-decision-list-page--${escapeClass(profile.key)}`);
  if (!page) return false;

  const refreshNode = page.querySelector("[data-model-refresh-status]");
  if (refreshNode) refreshNode.outerHTML = renderModelRefreshStatus(refreshState);

  const summaryNode = page.querySelector("[data-model-day1-summary]");
  if (summaryNode) summaryNode.outerHTML = renderTBoardDay1ScanSummary(profile, extraData);

  const noticeNode = page.querySelector("[data-model-load-notice]");
  if (noticeNode) noticeNode.innerHTML = loadErrors.length ? renderModelLoadNotice(loadErrors) : "";

  const countNode = page.querySelector("[data-model-filter-count='rows']");
  if (countNode) countNode.textContent = `显示 ${visibleRows.length} / ${listRows.length} 条真实只读记录`;

  const kpiNode = page.querySelector("[data-model-readiness-kpis]");
  if (kpiNode) kpiNode.outerHTML = renderHotReadinessKpis(profile, listRows, visibleRows);

  const body = page.querySelector("[data-model-table-body]");
  if (!body) return false;
  body.innerHTML = renderModelListTableRows(profile, visibleRows);

  const coverageNode = page.querySelector("[data-model-readiness-coverage]");
  if (coverageNode) coverageNode.outerHTML = renderHotReadinessCoverage(profile, listRows);
  return true;
}

function collectModelLoadErrors(extra, rows) {
  const errors = [];
  if (extra && extra.ok === false && extra.error) errors.push(safeLoadErrorLabel(extra.error));
  factorList(extra?.data?.gap_codes).forEach((item) => errors.push(item));
  factorList(extra?.data?.hot_model?.data?.gap_codes).forEach((item) => errors.push(item));
  Object.values(extra?.data || {}).forEach((item) => {
    if (item && item.ok === false && item.error) errors.push(safeLoadErrorLabel(item.error));
  });
  rows.forEach((row) => factorList(row.frontend_load_warnings).forEach((item) => errors.push(item)));
  return Array.from(new Set(errors.filter(Boolean))).slice(0, 3);
}

function renderModelListPageLead(profile) {
  if (profile.key !== "tboard") return "";
  return `<div class="model-list-page-lead model-list-page-lead--tboard" data-model-page-lead="true">
    <strong>${escapeHtml(profile.title)}</strong>
    <span>首日合格对象；次日每 5 分钟观察；停止原因逐行展示。</span>
  </div>`;
}

function renderModelRefreshStatus(refreshState) {
  const message = refreshState?.message || "";
  const tone = refreshState?.status === "error" ? "error" : "loading";
  const emptyClass = message ? "" : " model-refresh-status--empty";
  return `<div class="model-refresh-status model-refresh-status--${escapeClass(tone)}${emptyClass}" data-model-refresh-status="true" aria-live="polite">${escapeHtml(message)}</div>`;
}

function renderTBoardDay1ScanSummary(profile, extraData = {}) {
  if (profile.key !== "tboard") return "";
  const summary = extraData.day1_scan_summary;
  if (!summary) return `<div class="tboard-day1-summary tboard-day1-summary--empty" data-model-day1-summary="true"></div>`;
  if (summary.ok === false) {
    return `<div class="tboard-day1-summary tboard-day1-summary--warning" data-model-day1-summary="true"><strong>最近 Day1 扫描</strong><span>${escapeHtml(summary.error || "Day1 扫描结论暂时不可读")}</span></div>`;
  }
  const data = summary.data || {};
  const text = data.summary_text || data.main_reason;
  if (!text) return `<div class="tboard-day1-summary tboard-day1-summary--empty" data-model-day1-summary="true"></div>`;
  const meta = [
    data.trade_date ? `Day1 ${formatDateTimeValue(data.trade_date)}` : "",
    data.updated_at ? `Day1更新 ${formatDateTimeValue(data.updated_at)}` : "",
    `模型 ${data.last_model_output_at ? formatDateTimeValue(data.last_model_output_at) : "未产出"}`,
    `抓取 ${data.latest_data_fetch_at ? formatDateTimeValue(data.latest_data_fetch_at) : "未推进"}`,
  ].filter(Boolean).join(" / ");
  return `<div class="tboard-day1-summary" data-model-day1-summary="true">
    <strong>最近 Day1 扫描</strong>
    <span>${escapeHtml(text)}</span>
    ${meta ? `<small>${escapeHtml(meta)}</small>` : ""}
  </div>`;
}

function renderModelLoadNotice(errors) {
  return `<div class="notice-bar notice-bar--inline"><strong>部分事实暂未读到</strong><span>${escapeHtml(errors.map(businessStatusLabel).join("；"))}</span></div>`;
}

function renderModelKpi(label, value, tone, sub = "真实只读") {
  return `<article class="kpi-card model-card"><div class="kpi-card__head"><h3 class="kpi-title"><span class="kpi-icon">${escapeHtml(label.slice(0, 1))}</span><span>${escapeHtml(label)}</span></h3></div><strong class="kpi-value tone-${tone}">${escapeHtml(display(value))}</strong><small class="kpi-delta">${escapeHtml(sub)}</small></article>`;
}

function renderHotReadinessKpis(profile, rawRows, visibleRows) {
  if (profile.key !== "hot") return "";
  const kpis = modelReviewKpis(profile, rawRows, visibleRows);
  return `<section class="model-kpi-grid model-kpi-grid--hot-readiness" data-model-readiness-kpis="true">${kpis.map((item) => renderModelKpi(item.label, item.value, item.tone, item.sub)).join("")}</section>`;
}

function renderHotReadinessCoverage(profile, rows) {
  if (profile.key !== "hot") return "";
  return `<div data-model-readiness-coverage="true">${renderModelFieldCoverage(profile, rows)}</div>`;
}

function renderModelComparisonPlan(profile) {
  const rows = {
    hot: [
      ["当前入口", "读取 research-service 已落库的热点模型结果。"],
      ["排序口径", "按模型分从高到低展示；缺分保持空态，不补 0。"],
      ["缺口处理", "缺概率、缺买点或闸门阻断时直接写明待补事实。"],
    ],
    memory: [
      ["旧前端", "展示记忆池、二波触发、有效期、买点和结果。"],
      ["缺口处理", "缺概率、缺买点或闸门阻断时直接写明待补事实。"],
      ["本轮落地", "把列表改为候选记忆种子视图，展示首次/最近候选日、出现次数、自然日龄和缺口。"],
    ],
    ambush: [
      ["旧前端", "展示谷底观察、有效抬头、回落风险和买点。"],
      ["缺口处理", "缺概率、缺买点或闸门阻断时直接写明待补事实。"],
      ["本轮落地", "构建低谷候选列表；图形打标后续放在研究中心-低谷图库，不放在模型列表。"],
    ],
    tboard: [
      ["旧前端", "旧版没有模型四页。"],
      ["当前可用", "模型四只读观察台只纳入 Day1 通过对象。"],
      ["本轮落地", "页面只保留模型分、Day1、Day2、监测时间、当前判断、接力强度、关键依据、风险结论和更新。"],
    ],
  }[profile.key] || [];
  return `<section class="model-comparison-plan">
    <div class="model-comparison-plan__head">
      <strong>规划与差异对比</strong>
      <span>旧前端只作布局和字段密度参考；新页面只展示当前标准事实和模型服务事实。</span>
    </div>
    <div class="model-comparison-plan__grid">
      ${rows.map(([title, text]) => `<article><b>${escapeHtml(title)}</b><span>${escapeHtml(text)}</span></article>`).join("")}
    </div>
  </section>`;
}

function renderModelDecisionBrief(profile, rows) {
  const gaps = rows.reduce((total, row) => total + gapCount(row.source_gaps), 0);
  const brief = {
    hot: [
      ["当前答案", rows.length ? `${rows.length} 条模型结果` : "暂无模型结果", rows.length ? "来自已落库的热点模型决策。" : "没有落库记录时不补候选。"],
      ["已有模型分", rows.filter((row) => isFiniteNumber(row.model_score)).length ? `${rows.filter((row) => isFiniteNumber(row.model_score)).length} 条有分数` : "等待模型分", "按真实模型分排序，缺失不补 0。"],
      ["待补事实", gaps ? `${gaps} 个待补事实` : "事实完整", "概率、买点、验证或闸门缺失时逐行说明。"],
    ],
    memory: [
      ["当前答案", rows.length ? `${rows.length} 个记忆种子` : "等待历史种子", "由历史涨停候选按股票聚合，未冒充正式记忆实体。"],
      ["优质机会", rows.filter((row) => Number(row.appearance_count || 0) > 1).length ? `${rows.filter((row) => Number(row.appearance_count || 0) > 1).length} 只复现候选` : "等待二波证据", "多次出现只表示候选复现，不等于二波激活。"],
      ["待补事实", gaps ? `${gaps} 个待补事实` : "事实完整", "概率、买点、验证或闸门缺失时逐行说明。"],
    ],
    ambush: [
      ["当前答案", rows.length ? `${rows.length} 个记忆种子` : "等待历史种子", "由历史涨停候选按股票聚合，未冒充正式记忆实体。"],
      ["优质机会", rows.filter((row) => ["valley_stabilization", "horizontal_breakout_watch"].includes(row.shape_type)).length ? `${rows.filter((row) => ["valley_stabilization", "horizontal_breakout_watch"].includes(row.shape_type)).length} 个可复核结构` : "等待图库成熟", "结构分层用于人工复核，不直接改模型正式结论。"],
      ["待补事实", gaps ? `${gaps} 个待补事实` : "事实完整", "概率、买点、验证或闸门缺失时逐行说明。"],
    ],
    tboard: [
      ["观察对象", rows.length ? `${rows.length} 条` : "暂无", "Day1 通过才显示。"],
      ["已触发", rows.filter((row) => row.observation_status === "opportunity").length ? `${rows.filter((row) => row.observation_status === "opportunity").length} 条` : "暂无", "Day2 每 5 分钟刷新。"],
      ["已停止", rows.filter((row) => row.observation_status === "stopped").length ? `${rows.filter((row) => row.observation_status === "stopped").length} 条` : "暂无", "开板、卖压或未触发会写明原因。"],
    ],
  }[profile.key] || [];
  return `<section class="model-decision-brief model-decision-brief--${escapeHtml(profile.key)}">
    ${brief.map(([label, value, detail]) => `<article><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong><p>${escapeHtml(detail)}</p></article>`).join("")}
  </section>`;
}

function countCovered(rows, predicate) {
  return rows.filter((row) => {
    try {
      return Boolean(predicate(row));
    } catch {
      return false;
    }
  }).length;
}

function coverageStatus(count, total, emptyStatus = "未物化") {
  if (!total) return "无样本";
  if (count === total) return "已覆盖";
  if (count > 0) return "部分覆盖";
  return emptyStatus;
}

function coverageToneText(status) {
  if (status === "已覆盖") return "ready";
  if (status === "无样本" || status === "未物化") return "blocked";
  return "warning";
}

function coverageRatio(count, total) {
  return `${count}/${total}`;
}

function modelFieldCoverageRows(profile, rows) {
  const total = rows.length;
  const common = {
    score: ["模型分", "模型决策仓库", countCovered(rows, (row) => isFiniteNumber(row.model_score)), "未物化", "不补 0；逐行保留模型分缺口"],
    buyPoint: ["买点/评估基准", "买点服务或决策仓库", countCovered(rows, (row) => isFiniteNumber(row.reference_entry_price)), "未物化", "不推断买点价；缺口保持空态"],
    outcome: ["收益验证", "收益观察", countCovered(rows, (row) => !["verification_data_gap", "outcome_not_mature", null, undefined, ""].includes(row.verification_status)), "未物化", "未成熟或无路径时不显示成功"],
    quality: ["数据质量", "标准事实或只读观察台", countCovered(rows, (row) => ["usable", "source_visible", "ready"].includes(String(row.data_quality || "").toLowerCase()) || row.observation_status), "缺口", "只展示后端质量或观察台可读状态"],
  };
  if (profile.key === "hot") {
    return [
      ["热点决策列表", "热点模型结果", rows.length, "未物化", "只读已落库模型结果"],
      ["同花顺概率", "热点决策或付费概率事实", countCovered(rows, (row) => isFiniteNumber(row.ths_limit_up_probability)), "未物化", "缺失时显示缺口，不补 0"],
      common.score,
      common.buyPoint,
      common.outcome,
      common.quality,
    ];
  }
  if (profile.key === "memory") {
    return [
      ["记忆种子", "历史候选聚合", countCovered(rows, (row) => row.first_signal_date && row.latest_signal_date), "缺口", "按历史收盘封板候选聚合，不冒充正式记忆实体"],
      ["复现次数", "历史候选聚合", countCovered(rows, (row) => Number(row.appearance_count || 0) >= 1), "缺口", "多次出现只表示复现，不等于二波确认"],
      ["交易日龄", "交易日历或记忆实体", countCovered(rows, (row) => isFiniteNumber(row.memory_age_days)), "未物化", "缺交易日龄必须显示数据缺口阻断"],
      ["有效期", "记忆实体", countCovered(rows, (row) => isFiniteNumber(row.ttl_remaining_days)), "未物化", "未物化时保持空态"],
      common.score,
      common.buyPoint,
      common.outcome,
      common.quality,
    ];
  }
  if (profile.key === "ambush") {
    return [
      ["低谷样本", "前复权日线", countCovered(rows, (row) => row.primary_trough_date && isFiniteNumber(row.current_price)), "缺口", "按前复权日线窗口构建低谷候选"],
      ["形态提示", "前端只读窗口计算", countCovered(rows, (row) => row.shape_type), "缺口", "用于人工复核，不等同正式模型结论"],
      ["资金上下文", "标准资金流", countCovered(rows, (row) => !factorList(row.source_gaps).includes("source_gap:moneyflow_context_missing")), "缺口", "缺失时保留资金上下文缺口"],
      ["图形打标", "研究中心-低谷图库", 0, "后续开放", "模型列表不放人工打标控件"],
      common.score,
      common.buyPoint,
      common.outcome,
      common.quality,
    ];
  }
  return [
    ["首日观察对象", "模型四观察台", countCovered(rows, (row) => row.day1_trade_date && row.current_conclusion), "缺口", "首日未通过不进入列表"],
    ["Day2监测", "模型四观察台", countCovered(rows, (row) => row.day2_trade_date || row.day2_trigger_time), "缺口", "展示滚动监测或触发时间"],
    ["当前判断", "模型四观察台", countCovered(rows, (row) => row.current_conclusion), "缺口", "用户只看可理解判断"],
    ["关键依据", "模型四观察台", countCovered(rows, (row) => row.key_reason), "缺口", "不用程序状态码解释依据"],
    ["风险结论", "模型四观察台", countCovered(rows, (row) => row.risk_tip), "缺口", "来自盘口、强度、封板维护或缺口事实"],
  ];
}

function topGapRows(rows) {
  const counts = new Map();
  rows.forEach((row) => factorList(row.source_gaps).forEach((gap) => counts.set(gap, (counts.get(gap) || 0) + 1)));
  return Array.from(counts.entries())
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, 8);
}

function hotReadinessDimensionRows(rows) {
  const dimensions = new Map();
  rows.forEach((row) => {
    (Array.isArray(row.readiness_dimensions) ? row.readiness_dimensions : []).forEach((dimension) => {
      if (!dimension || !dimension.code) return;
      const current = dimensions.get(dimension.code) || {
        code: dimension.code,
        label: dimension.label || dimension.code,
        priority: dimension.priority || "P2",
        weight: Number(dimension.weight || 0),
        readyCount: 0,
        missingCount: 0,
        missingPoints: 0,
      };
      if (dimension.status === "ready") current.readyCount += 1;
      else {
        current.missingCount += 1;
        current.missingPoints += Number(dimension.missing || dimension.weight || 0);
      }
      dimensions.set(dimension.code, current);
    });
  });
  const priorityOrder = { P0: 0, P1: 1, P2: 2 };
  return Array.from(dimensions.values()).sort((a, b) => (priorityOrder[a.priority] ?? 9) - (priorityOrder[b.priority] ?? 9) || b.weight - a.weight || a.code.localeCompare(b.code));
}

function renderModelFieldCoverage(profile, rows) {
  const total = rows.length;
  const coverageRows = modelFieldCoverageRows(profile, rows);
  const gapRows = topGapRows(rows);
  const readinessRows = profile.key === "hot" ? hotReadinessDimensionRows(rows) : [];
  const readinessTable = readinessRows.length ? `<div class="model-iteration-table-wrap">
        <table class="model-iteration-table model-field-coverage-table">
          <thead><tr><th>准备度维度</th><th>优先级</th><th>权重</th><th>覆盖</th><th>缺失分</th></tr></thead>
          <tbody>${readinessRows.map((row) => `<tr>
            <td>${escapeHtml(row.label)}</td>
            <td><span class="status-pill status-${row.priority === "P0" ? "blocked" : row.priority === "P1" ? "warning" : "ready"}">${escapeHtml(row.priority)}</span></td>
            <td>${escapeHtml(String(row.weight))}</td>
            <td>${escapeHtml(coverageRatio(row.readyCount, total))}</td>
            <td>${escapeHtml(String(row.missingPoints))}</td>
          </tr>`).join("")}</tbody>
        </table>
      </div>` : "";
  return `<section class="model-field-coverage">
    <div class="model-field-coverage__head">
      <div>
      <strong>规划与差异对比</strong>
      <span>旧前端只作布局和字段密度参考；新页面只展示当前标准事实和模型服务事实。</span>
      </div>
      <b>${escapeHtml(String(total))} 行</b>
    </div>
    ${readinessTable}
    <div class="model-field-coverage__grid">
      <div class="model-iteration-table-wrap">
        <table class="model-iteration-table model-field-coverage-table">
          <thead><tr><th>准备度维度</th><th>优先级</th><th>权重</th><th>覆盖</th><th>缺失分</th></tr></thead>
          <tbody>${coverageRows.map(([label, source, count, emptyStatus, handling]) => {
            const status = coverageStatus(count, total, emptyStatus);
            return `<tr>
              <td>${escapeHtml(label)}</td>
              <td>${escapeHtml(source)}</td>
              <td>${escapeHtml(coverageRatio(count, total))}</td>
              <td><span class="status-pill status-${coverageToneText(status)}">${escapeHtml(status)}</span></td>
              <td>${escapeHtml(handling)}</td>
            </tr>`;
          }).join("")}</tbody>
        </table>
      </div>
      <div class="model-iteration-table-wrap">
        <table class="model-iteration-table model-gap-digest-table">
          <thead><tr><th>主要缺口</th><th>行数</th></tr></thead>
          <tbody>${gapRows.length ? gapRows.map(([gap, count]) => `<tr><td>${escapeHtml(businessStatusLabel(gap))}</td><td>${escapeHtml(String(count))}</td></tr>`).join("") : renderEmptyTableRow(2, "当前没有行级缺口。")}</tbody>
        </table>
      </div>
    </div>
  </section>`;
}

function currentModelFilters(profile) {
  return state.modelReviewFilters[profile.key] || {};
}

function filterOptionLabel(value) {
  return FILTER_OPTION_LABELS[value] || sourceQualityLabel(value) || businessStatusLabel(value);
}

function filterFieldValueLabel(fieldKey, value) {
  if (fieldKey === "data_quality") return value === "all" ? "全部" : sourceQualityLabel(value);
  return filterOptionLabel(value);
}

function renderModelReviewFilters(profile, totalCount, visibleCount) {
  const fields = MODEL_REVIEW_FILTERS[profile.key] || [];
  const filters = currentModelFilters(profile);
  const activeCount = Object.keys(filters).length;
  return `<section class="filter-row decision-review-filter-row">
    <div class="decision-review-filter-line decision-review-filter-line--primary">
      ${fields.map((field) => {
        const value = filters[field.key] || "";
        if (field.type === "text") {
          return `<label><span>${escapeHtml(field.label)}</span><input class="filter-input" data-model-filter="${escapeHtml(field.key)}" value="${escapeHtml(value)}" placeholder="${escapeHtml(field.placeholder || "")}" /></label>`;
        }
        return `<label><span>${escapeHtml(field.label)}</span><select class="filter-select" data-model-filter="${escapeHtml(field.key)}">
          ${(field.options || ["all"]).map((option) => `<option value="${escapeHtml(option)}" ${String(value || "all") === option ? "selected" : ""}>${escapeHtml(filterFieldValueLabel(field.key, option))}</option>`).join("")}
        </select></label>`;
      }).join("")}
    </div>
    <div class="decision-review-filter-line decision-review-filter-line--secondary">
      <span class="filter-display" data-model-filter-count="rows">显示 ${escapeHtml(String(visibleCount))} / ${escapeHtml(String(totalCount))} 条真实只读记录</span>
      <span class="filter-display">已启用 ${escapeHtml(String(activeCount))} 个条件</span>
      <button class="secondary-button" data-action="reset-model-filters" ${activeCount ? "" : "disabled"}>重置</button>
    </div>
  </section>`;
}

function applyModelReviewFilters(profile, rows) {
  const filters = currentModelFilters(profile);
  return rows.filter((row) => {
    const symbolFilter = String(filters.symbol || "").replace(/\D/g, "");
    const symbol = String(row.stock?.symbol || row.symbol || "").replace(/\D/g, "");
    if (symbolFilter && !symbol.includes(symbolFilter)) return false;
    if (filters.source_gap === "with_gap" && !gapCount(row.source_gaps)) return false;
    if (filters.source_gap === "no_gap" && gapCount(row.source_gaps)) return false;
    if (profile.key === "hot" && filters.release_gate && filters.release_gate !== "all" && row.release_gate !== filters.release_gate) return false;
    if (profile.key === "memory" && filters.memory_state && filters.memory_state !== "all" && row.memory_state !== filters.memory_state) return false;
    if (profile.key === "memory" && filters.appearance_count === "multi" && Number(row.appearance_count || 0) < 2) return false;
    if (profile.key === "memory" && filters.appearance_count === "single" && Number(row.appearance_count || 0) !== 1) return false;
    if (profile.key === "ambush" && filters.shape_type && filters.shape_type !== "all" && row.shape_type !== filters.shape_type) return false;
    if (profile.key === "tboard" && filters.observation_status && filters.observation_status !== "all" && row.observation_status !== filters.observation_status) return false;
    return true;
  });
}

function bindModelReviewActions(profile) {
  $$("[data-model-filter]").forEach((input) => {
    input.addEventListener("change", () => {
      const key = input.dataset.modelFilter;
      const value = String(input.value || "").trim();
      const next = { ...currentModelFilters(profile) };
      if (value && value !== "all") next[key] = value;
      else delete next[key];
      state.modelReviewFilters[profile.key] = next;
      renderModelPage(profile, { useCachedRows: true, focusFilterKey: key });
    });
  });
  $$("input[data-model-filter]").forEach((input) => {
    input.addEventListener("input", () => {
      window.clearTimeout(input._modelFilterTimer);
      input._modelFilterTimer = window.setTimeout(() => {
        input.dispatchEvent(new Event("change"));
      }, 260);
    });
  });
  $("[data-action='reset-model-filters']")?.addEventListener("click", () => {
    delete state.modelReviewFilters[profile.key];
    renderModelPage(profile, { useCachedRows: true });
  });
}

function restoreModelFilterFocus(profile, key) {
  if (!key || !profile) return;
  const input = Array.from(document.querySelectorAll("[data-model-filter]"))
    .find((item) => item.dataset.modelFilter === key);
  if (!input || typeof input.focus !== "function") return;
  input.focus();
  if (typeof input.setSelectionRange === "function" && input.tagName === "INPUT") {
    const end = String(input.value || "").length;
    input.setSelectionRange(end, end);
  }
}

function modelReviewKpis(profile, rawRows, visibleRows) {
  const gapRows = rawRows.filter((row) => gapCount(row.source_gaps));
  if (profile.key === "hot") {
    const scored = rawRows.filter((row) => isFiniteNumber(row.model_score)).length;
    const probabilityReady = rawRows.filter((row) => isFiniteNumber(row.ths_limit_up_probability)).length;
    const readinessScores = rawRows.map((row) => Number(row.readiness_score_pct)).filter(Number.isFinite);
    const averageReadiness = readinessScores.length ? readinessScores.reduce((sum, value) => sum + value, 0) / readinessScores.length : null;
    const missingPoints = rawRows.map((row) => Number(row.missing_points)).filter(Number.isFinite);
    const averageMissing = missingPoints.length ? missingPoints.reduce((sum, value) => sum + value, 0) / missingPoints.length : null;
    const blockedRows = rawRows.filter((row) => row.readiness_state === "blocked").length;
    const readinessTone = averageReadiness === null ? "warning" : averageReadiness >= 100 ? "ready" : averageReadiness >= 70 ? "warning" : "blocked";
    const readinessValue = averageReadiness === null ? "暂无" : `${averageReadiness.toFixed(1)}%`;
    const readinessSub = averageMissing === null ? "等待真实行" : `平均缺 ${averageMissing.toFixed(1)} 分`;
    return [
      { label: "列表记录", value: visibleRows.length, tone: visibleRows.length ? "ready" : "warning", sub: "筛选后" },
      { label: "数据准备度", value: readinessValue, tone: readinessTone, sub: readinessSub },
      { label: "P0阻断", value: blockedRows, tone: blockedRows ? "blocked" : "ready", sub: "逐行真实缺口" },
      { label: "已有模型分", value: `${scored}/${rawRows.length}`, tone: scored ? "ready" : "warning", sub: "按模型分排序" },
      { label: "概率覆盖", value: `${probabilityReady}/${rawRows.length}`, tone: probabilityReady === rawRows.length && rawRows.length ? "ready" : "warning", sub: "缺失不补 0" },
      { label: "数据缺口", value: gapRows.length, tone: gapRows.length ? "warning" : "ready", sub: "逐行保留" },
    ];
  }
  if (profile.key === "memory") {
    const multi = rawRows.filter((row) => Number(row.appearance_count || 0) > 1).length;
    return [
      { label: "列表记录", value: visibleRows.length, tone: visibleRows.length ? "ready" : "warning", sub: "筛选后" },
      { label: "多次出现", value: multi, tone: multi ? "ready" : "warning", sub: "候选复现" },
      { label: "未物化", value: rawRows.filter((row) => row.memory_state === "blocked_data_gap").length, tone: "warning", sub: "保留缺口" },
      { label: "数据缺口", value: gapRows.length, tone: gapRows.length ? "warning" : "ready", sub: "逐行保留" },
    ];
  }
  if (profile.key === "ambush") {
    return [
      { label: "列表记录", value: visibleRows.length, tone: visibleRows.length ? "ready" : "warning", sub: "筛选后" },
      { label: "图库样本", value: rawRows.length, tone: rawRows.length ? "ready" : "warning", sub: "只读候选" },
      { label: "图形打标", value: "研究中心", tone: "warning", sub: "后续低谷图库" },
      { label: "数据缺口", value: gapRows.length, tone: gapRows.length ? "warning" : "ready", sub: "逐行保留" },
    ];
  }
  return [
      { label: "列表记录", value: visibleRows.length, tone: visibleRows.length ? "ready" : "warning", sub: "筛选后" },
      { label: "数据缺口", value: gapRows.length, tone: gapRows.length ? "warning" : "ready", sub: "逐行保留" },
  ];
}

async function loadPreflight(profile) {
  return api("/api/source/preflight", {
    method: "POST",
    body: JSON.stringify({
      model_code: profile.modelCode,
      model_phase: profile.modelPhase,
      trade_date: "2026-06-12",
      symbols: [profile.symbol],
    }),
  }).catch(async () => {
    return backend("source", `source/models/requirements?model_code=${encodeURIComponent(profile.modelCode)}&model_phase=${encodeURIComponent(profile.modelPhase)}`)
      .then((requirements) => ({
        can_release_official_signal: null,
        coverage_status: "requirements_loaded",
        freshness_status: "preflight_unavailable",
        blocking_reasons: [],
        model_code: profile.modelCode,
        model_phase: profile.modelPhase,
        symbol: profile.symbol,
        requirement_count: Array.isArray(requirements) ? requirements.length : null,
        note: "数据预检暂时不可读，已退回数据要求清单；正式门禁仍以后端数据预检结果为准。",
      }));
  });
}

async function loadModelExtra(profile) {
  if (profile.key === "hot") {
    return api(`/api/model-list/hot?limit=${FRONTEND_HOT_MODEL_LIST_LIMIT}`, { method: "GET", timeoutMs: FRONTEND_HOT_MODEL_LIST_TIMEOUT_MS });
  }
  if (profile.key === "tboard") {
    return api("/api/model-list/tboard?limit=100", { method: "GET", timeoutMs: FRONTEND_TBOARD_COMPACT_TIMEOUT_MS });
  }
  if (profile.repositoryPaths) {
    const tasks = profile.repositoryPaths.map(([key, path]) => (
      safeLoad(() => backend(profile.service, path, FRONTEND_REPOSITORY_TIMEOUT_MS)).then((result) => [key, result])
    ));
    return Object.fromEntries(await Promise.all(tasks));
  }
  if (profile.scorePath && profile.samplePayload) {
    return {
      score_contract: {
        ok: false,
        skipped: true,
        reason: "锁定后端模式下，前端只读展示，不触发模型评分。",
        sample_payload_shape: Object.keys(profile.samplePayload),
      },
    };
  }
  return { note: "当前模型页无额外只读列表接口。" };
}

async function buildModelListRows(profile, extra) {
  if (profile.key === "tboard") return buildTBoardListRows(extra.data || {});
  if (profile.key === "hot") {
    return buildHotModelListRows(extra.data || {});
  }
  if (profile.key === "memory") {
    const context = await loadMemoryModelSourceContext();
    return buildMemoryDecisionRows(context.eventRows, context.dailyRows, context.moneyRows, context.warnings);
  }
  if (profile.key === "ambush") {
    const context = await loadAmbushModelSourceContext();
    return buildAmbushDecisionRows(context.adjustedRows, context.moneyRows, context.warnings);
  }
  return [];
}

async function loadMemoryModelSourceContext() {
  const eventRows = await loadSourceRows("source.limit_event_v1", {}, FRONTEND_TABLE_TIMEOUT_MS);
  const latestDate = latestTradeDate(eventRows);
  const [daily, money] = await Promise.all([
    safeLoad(() => loadSourceRows("source.daily_bar_v1", latestDate ? { trade_date: latestDate } : {}, FRONTEND_FAST_TIMEOUT_MS)),
    safeLoad(() => loadSourceRows("source.stock_moneyflow_daily_v1", latestDate ? { trade_date: latestDate } : {}, FRONTEND_FAST_TIMEOUT_MS)),
  ]);
  return {
    eventRows,
    dailyRows: arrayFromResponse(daily.data),
    moneyRows: arrayFromResponse(money.data),
    warnings: [daily, money].filter((item) => !item.ok).map((item) => safeLoadErrorLabel(item.error)),
  };
}

async function loadAmbushModelSourceContext() {
  const adjusted = await safeLoad(() => loadSourceRows("source.adjusted_daily_bar_v1", {}, FRONTEND_TABLE_TIMEOUT_MS));
  const adjustedRows = arrayFromResponse(adjusted.data);
  const latestDate = latestTradeDate(adjustedRows);
  const money = await safeLoad(() => loadSourceRows("source.stock_moneyflow_daily_v1", latestDate ? { trade_date: latestDate } : {}, FRONTEND_FAST_TIMEOUT_MS));
  return {
    adjustedRows,
    moneyRows: arrayFromResponse(money.data),
    warnings: [adjusted, money].filter((item) => !item.ok).map((item) => safeLoadErrorLabel(item.error)),
  };
}

function rowsBySymbol(rows) {
  const grouped = new Map();
  rows.forEach((row) => {
    const symbol = row?.symbol || row?.canonical_symbol;
    if (!symbol) return;
    if (!grouped.has(symbol)) grouped.set(symbol, []);
    grouped.get(symbol).push(row);
  });
  grouped.forEach((items) => items.sort((a, b) => String(a.trade_date || a.trading_day || "").localeCompare(String(b.trade_date || b.trading_day || ""))));
  return grouped;
}

function latestRowForSymbol(grouped, symbol, tradeDate = null) {
  const rows = grouped.get(symbol) || [];
  if (!rows.length) return null;
  const exact = rows.find((row) => row.trade_date === tradeDate || row.trading_day === tradeDate);
  if (exact) return exact;
  if (!tradeDate) return rows[rows.length - 1];
  const before = rows.filter((row) => String(row.trade_date || row.trading_day || "") <= String(tradeDate));
  return before[before.length - 1] || rows[rows.length - 1];
}

function dateDiffDays(startDate, endDate) {
  const start = Date.parse(`${startDate}T00:00:00Z`);
  const end = Date.parse(`${endDate}T00:00:00Z`);
  if (!Number.isFinite(start) || !Number.isFinite(end)) return null;
  return Math.max(0, Math.round((end - start) / 86400000));
}

function marketDateKey(date = new Date()) {
  try {
    const parts = new Intl.DateTimeFormat("en-CA", {
      timeZone: "Asia/Shanghai",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).formatToParts(date).reduce((acc, part) => {
      acc[part.type] = part.value;
      return acc;
    }, {});
    if (parts.year && parts.month && parts.day) return `${parts.year}-${parts.month}-${parts.day}`;
  } catch (_) {
    // If the browser lacks timezone formatting support, fall back to local calendar date.
  }
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function dateKey(value) {
  const match = String(value || "").trim().match(/\d{4}-\d{2}-\d{2}/);
  return match ? match[0] : "";
}

function tBoardTerminalDateKey(item) {
  return (
    dateKey(item?.day3_trade_date)
    || dateKey(item?.day2_trade_date)
    || dateKey(item?.day1_trade_date)
    || dateKey(item?.latest_snapshot_time)
    || dateKey(item?.updated_at)
  );
}

function marketTimeMinutes() {
  try {
    const parts = new Intl.DateTimeFormat("en-GB", {
      timeZone: "Asia/Shanghai",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    }).formatToParts(new Date()).reduce((acc, part) => {
      acc[part.type] = part.value;
      return acc;
    }, {});
    if (parts.hour && parts.minute) return Number(parts.hour) * 60 + Number(parts.minute);
  } catch (_) {
    // If timezone formatting is unavailable, fall back to local clock time.
  }
  const now = new Date();
  return now.getHours() * 60 + now.getMinutes();
}

function nextWeekdayDateKey(dayKey) {
  const match = String(dayKey || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return "";
  const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
  do {
    date.setUTCDate(date.getUTCDate() + 1);
  } while (date.getUTCDay() === 0 || date.getUTCDay() === 6);
  return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, "0")}-${String(date.getUTCDate()).padStart(2, "0")}`;
}

function tBoardDay2WindowElapsed(item) {
  const day1 = dateKey(item?.day1_trade_date);
  const expectedDay2 = dateKey(item?.day2_trade_date) || nextWeekdayDateKey(day1);
  const today = marketDateKey();
  if (!expectedDay2 || !today) return false;
  if (today > expectedDay2) return true;
  if (today < expectedDay2) return false;
  return marketTimeMinutes() >= TBOARD_DAY2_WINDOW_END_MINUTES;
}

function tBoardShouldHideDefault(item) {
  const status = String(item?.observation_status || "").toLowerCase();
  if (TBOARD_DEFAULT_HIDDEN_STATUSES.has(status)) return true;
  return status === "data_wait" && tBoardDay2WindowElapsed(item);
}

function valueWithGap(row, key) {
  const values = rowValues(row);
  return values[key] ?? row?.[key] ?? null;
}

function sourceRowQuality(rows) {
  const qualities = rows.map((row) => row?.source_quality_status).filter(Boolean);
  if (!qualities.length) return "gap";
  return qualities.every((item) => item === "usable") ? "usable" : qualities[0];
}

function buildMemoryDecisionRows(eventRows, dailyRows, moneyRows, warnings = []) {
  const closedEvents = eventRows.filter(isClosedLimitCandidate);
  const latestEventDate = latestTradeDate(closedEvents);
  const grouped = rowsBySymbol(closedEvents);
  const dailyBySymbol = rowsBySymbol(dailyRows);
  const moneyBySymbol = rowsBySymbol(moneyRows);
  return Array.from(grouped.entries()).map(([symbol, rows]) => {
    const first = rows[0];
    const latest = rows[rows.length - 1];
    const latestValues = rowValues(latest);
    const dailyRow = latestRowForSymbol(dailyBySymbol, symbol, latest.trade_date);
    const moneyRow = latestRowForSymbol(moneyBySymbol, symbol, latest.trade_date);
    const dailyValues = rowValues(dailyRow);
    const moneyValues = rowValues(moneyRow);
    const appearanceCount = rows.length;
    return {
      stock: { symbol, name: null },
      selected_days: "T+5/T+20/T+40",
      reactivated_date: latest.trade_date,
      first_signal_date: first.trade_date,
      latest_signal_date: latest.trade_date,
      first_source_model: "热点候选",
      appearance_count: appearanceCount,
      natural_age_days: dateDiffDays(first.trade_date, latestEventDate),
      memory_age_days: null,
      ttl_remaining_days: null,
      memory_state: "blocked_data_gap",
      second_wave_trigger_code: appearanceCount > 1 ? "mixed_reactivation" : null,
      latest_limit_structure: limitPatternText(latestValues),
      memory_score: null,
      model_score: null,
      release_gate: "blocked_data_gap",
      buy_point_status: "buy_point_not_materialized",
      current_price: dailyValues.close_price,
      main_net_inflow: moneyValues.main_net_inflow,
      reference_entry_price: null,
      return_from_entry_pct: null,
      entry_opportunity_status: "entry_path_data_gap",
      mae_pct: null,
      verification_status: "outcome_not_mature",
      risk_summary: "data_gap",
      data_quality: sourceRowQuality(rows),
      latest_snapshot_time: latest.updated_at || latest.available_at,
      source_gaps: [
        "source_gap:missing_trading_calendar_memory_age",
        "source_gap:memory_entity_not_materialized",
        "source_gap:model_score_not_materialized",
        "source_gap:buy_point_not_materialized",
        "source_gap:reference_entry_price_not_materialized",
        "source_gap:outcome_not_materialized",
        dailyRow?.trade_date !== latest.trade_date ? "source_gap:daily_bar_same_day_missing" : null,
        moneyRow?.trade_date !== latest.trade_date ? "source_gap:stock_moneyflow_same_day_missing" : null,
      ].filter(Boolean),
      frontend_load_warnings: warnings,
    };
  }).sort((a, b) => String(b.latest_signal_date).localeCompare(String(a.latest_signal_date)) || Number(b.appearance_count || 0) - Number(a.appearance_count || 0));
}

function classifyAmbushShape(barCount, reboundPct, drawdownPct, daysSinceLow) {
  if (barCount < 20) return "sample_insufficient";
  if (isFiniteNumber(reboundPct) && Number(reboundPct) >= 8 && daysSinceLow <= 5) return "continuous_rebound_watch";
  if (isFiniteNumber(reboundPct) && Number(reboundPct) >= 3 && daysSinceLow <= 8) return "horizontal_breakout_watch";
  if (isFiniteNumber(drawdownPct) && Number(drawdownPct) <= -8) return "valley_stabilization";
  return "valley_stabilization";
}

function valleyMaturityHint(barCount, daysSinceLow, reboundPct) {
  if (barCount < 20) return "样本不足";
  if (daysSinceLow <= 2) return "刚抬头";
  if (daysSinceLow <= 8 && Number(reboundPct || 0) <= 12) return "观察成熟";
    return "读取失败，页面已保留中文空态。";
}

function turnFreshnessBucket(daysSinceLow) {
  if (!isFiniteNumber(daysSinceLow)) return "UNKNOWN";
  const days = Number(daysSinceLow);
  if (days <= 1) return "D1";
  if (days === 2) return "D2";
  if (days === 3) return "D3";
  if (days <= 5) return "D4_D5";
  if (days <= 8) return "D6_D8_HORIZONTAL_BREAKOUT";
  return "D9_PLUS";
}

function buildAmbushDecisionRows(adjustedRows, moneyRows, warnings = []) {
  const grouped = rowsBySymbol(adjustedRows);
  const moneyBySymbol = rowsBySymbol(moneyRows);
  return Array.from(grouped.entries()).map(([symbol, rows]) => {
    const series = rows
      .map((row) => ({ row, values: rowValues(row), close: Number(rowValues(row).adjusted_close), low: Number(rowValues(row).adjusted_low), high: Number(rowValues(row).adjusted_high) }))
      .filter((item) => Number.isFinite(item.close));
    const latest = series[series.length - 1];
    const lowItem = series.reduce((best, item) => (!best || item.low < best.low ? item : best), null);
    const high = Math.max(...series.map((item) => item.high).filter(Number.isFinite));
    const latestClose = latest?.close;
    const trough = Number.isFinite(lowItem?.low) ? lowItem.low : null;
    const reboundPct = trough && latestClose ? ((latestClose - trough) / trough) * 100 : null;
    const drawdownPct = Number.isFinite(high) && latestClose ? ((latestClose - high) / high) * 100 : null;
    const lowIndex = lowItem ? series.indexOf(lowItem) : -1;
    const daysSinceLow = lowIndex >= 0 ? series.length - 1 - lowIndex : null;
    const asOfDate = latest?.row.trade_date || latest?.row.trading_day || null;
    const moneyRow = latestRowForSymbol(moneyBySymbol, symbol, asOfDate);
    const shapeType = classifyAmbushShape(series.length, reboundPct, drawdownPct, daysSinceLow);
      return {
      stock: { symbol, name: null },
        as_of_date: asOfDate,
        trade_date: asOfDate,
        effective_turn_anchor_day: asOfDate,
        selected_days: isFiniteNumber(daysSinceLow) ? `${daysSinceLow} 天` : null,
        selection_summary: isFiniteNumber(daysSinceLow) ? `${daysSinceLow} 天` : null,
        primary_trough_date: lowItem?.row.trade_date || lowItem?.row.trading_day || null,
        days_since_low_at_turn: daysSinceLow,
        bar_count: series.length,
        shape_type: shapeType,
      trough_price: trough,
      adjusted_close: latestClose,
      current_price: latestClose,
      rebound_from_trough_pct: reboundPct,
      drawdown_from_window_high_pct: drawdownPct,
        valley_maturity_hint: valleyMaturityHint(series.length, daysSinceLow, reboundPct),
        turn_freshness_bucket: turnFreshnessBucket(daysSinceLow),
        model_score: null,
        release_gate: "research_only",
        buy_point_status: "buy_point_not_materialized",
        reference_entry_price: null,
        return_from_entry_pct: null,
        entry_opportunity_status: "entry_path_data_gap",
        mae_pct: null,
        verification_status: "verification_data_gap",
        false_rebound_risk: null,
        risk_summary: "data_gap",
        data_quality: sourceRowQuality(rows),
        latest_snapshot_time: latest?.row.updated_at || latest?.row.available_at,
        source_gaps: [
          "source_gap:ambush_decision_list_not_materialized",
          "source_gap:ambush_label_repository_missing",
          "source_gap:model_score_not_materialized",
          "source_gap:buy_point_not_materialized",
          "source_gap:reference_entry_price_not_materialized",
          "source_gap:outcome_not_materialized",
          series.length < 60 ? "source_gap:daily_bar_history_insufficient" : null,
          moneyRow?.trade_date !== asOfDate ? "source_gap:moneyflow_context_missing" : null,
        ].filter(Boolean),
        frontend_load_warnings: warnings,
    };
  }).sort((a, b) => Number(b.bar_count || 0) - Number(a.bar_count || 0));
}

function recordOrderValue(item) {
  const timeFields = ["updated_at", "created_at", "available_at", "captured_at", "latest_snapshot_time", "as_of_time", "as_of_time_utc"];
  for (const field of timeFields) {
    const parsed = Date.parse(item?.[field]);
    if (Number.isFinite(parsed)) return parsed;
  }
  const pkFields = ["day1_candidate_pk", "day2_watch_pk", "entry_trigger_pk", "post_entry_monitor_pk", "day3_decision_pk", "outcome_pk", "game_hypothesis_pk"];
  for (const field of pkFields) {
    if (isFiniteNumber(item?.[field])) return Number(item[field]);
  }
  return 0;
}

function keepLatest(map, key, item) {
  if (!key || !item) return;
  const current = map.get(key);
  if (!current || recordOrderValue(item) >= recordOrderValue(current)) {
    map.set(key, item);
  }
}

function modelScoreSortValue(row) {
  const score = numberOrNull(row?.model_score);
  return score === null ? -1 : score;
}

function buildHotModelListRows(extra) {
  const items = arrayFromResponse(extra.hot_model?.data);
  return items.map((item) => ({
    stock: item.stock || { symbol: item.symbol, name: item.stock_name },
    symbol: item.symbol || item.stock?.symbol,
    stock_name: item.stock_name || item.stock?.name,
    signal_date: item.signal_date || item.trade_date,
    trade_date: item.trade_date || item.signal_date,
    ths_limit_up_probability: item.ths_limit_up_probability,
    p_limit_up: item.p_limit_up_calibrated ?? item.p_limit_up_raw ?? item.ths_limit_up_probability,
    model_score: item.model_score,
    model_score_label: item.model_score_label,
    model_score_stage: item.model_score_stage,
    readiness_contract: item.readiness_contract,
    readiness_score_pct: item.readiness_score_pct,
    missing_points: item.missing_points,
    blocked_points: item.blocked_points,
    readiness_state: item.readiness_state,
    top_missing_dimension: item.top_missing_dimension,
    readiness_gap_codes: factorList(item.readiness_gap_codes),
    readiness_dimensions: Array.isArray(item.readiness_dimensions) ? item.readiness_dimensions : [],
    score_state: item.score_state,
    release_gate: item.release_gate,
    current_price: item.current_price,
    reference_entry_price: item.reference_entry_price,
    return_from_entry_pct: item.return_from_entry_pct,
    entry_opportunity_status: item.entry_opportunity_status,
    buy_point_status: item.buy_point_status,
    mae_pct: item.mae_pct,
    verification_status: item.verification_status,
    risk_summary: item.risk_summary,
    latest_snapshot_time: item.latest_snapshot_time || item.updated_at,
    source_gaps: factorList(item.source_gaps),
    hard_block_reasons: factorList(item.hard_block_reasons),
    warning_reasons: factorList(item.warning_reasons),
    data_quality: item.data_quality,
  })).sort((a, b) => modelScoreSortValue(b) - modelScoreSortValue(a) || recordOrderValue(b) - recordOrderValue(a));
}

function tBoardFactText(item) {
  return [
    item?.current_conclusion,
    item?.key_reason,
    item?.risk_tip,
    item?.next_observation,
    item?.monitoring_summary,
    item?.relay_strength_label,
  ].map((value) => String(value || "").trim()).filter(Boolean).join(" ");
}

function tBoardStoppedReason(item) {
  const text = tBoardFactText(item);
  const status = String(item?.observation_status || "").toLowerCase();
  if (["开板", "破板", "封板维护失败", "封住到收盘失败", "封板没守住", "封不住"].some((token) => text.includes(token))) return "board_open";
  if (["卖盘主动砸向买盘", "卖压", "砸盘", "打向买盘"].some((token) => text.includes(token))) return "sell_pressure";
  if (["未到接力点", "未接近涨停", "未触发"].some((token) => text.includes(token))) return "not_triggered";
  return status === "stopped" ? "stopped" : "";
}

function tBoardRelayStrengthText(item) {
  const reason = tBoardStoppedReason(item);
  if (reason === "board_open") return "封板失败";
  if (reason === "sell_pressure") return "卖压占优";
  if (reason === "not_triggered") return "未触发";
  const status = String(item?.observation_status || "").toLowerCase();
  if (status === "stopped") return "已停止";
  if (status === "data_wait") return "数据缺口";
  if (status === "continue_watch") return "观察中";
  return item?.relay_strength_label || "待确认";
}

function tBoardConclusionText(item) {
  const reason = tBoardStoppedReason(item);
  if (reason === "board_open") return "封板失败";
  if (reason === "sell_pressure") return "卖压占优";
  if (reason === "not_triggered") return "未触发";
  const status = String(item?.observation_status || "").toLowerCase();
  if (status === "opportunity") return "已触发，继续看封板";
  if (status === "continue_watch") return "继续观察";
  if (status === "data_wait") return "暂不观察";
  const raw = String(item?.current_conclusion || "").trim();
  if (raw.includes("可买入") || raw.includes("已触发")) return "已触发，继续看封板";
  return item?.current_conclusion;
}

function tBoardKeyReasonText(item) {
  const keyReason = String(item?.key_reason || "").trim();
  const fullText = tBoardFactText(item);
  const reason = tBoardStoppedReason(item);
  if (reason === "board_open") return "封板失败";
  if (reason === "sell_pressure") return "接近涨停，卖盘往下砸";
  if (reason === "not_triggered") return "5 分钟监测未接近涨停";
  if (["买盘主动扫掉卖盘", "主动买盘扫掉卖盘", "买盘扫卖盘"].some((token) => fullText.includes(token))) return "接近涨停，买盘扫掉卖盘";
  if (keyReason.includes("开盘后5分钟滚动监测已接近涨停")) return "5 分钟监测已接近涨停";
  return keyReason
    .replace(/^Day2\s*/, "")
    .replace("09:30-10:30 滚动监测", "5 分钟监测")
    .replace("开盘后5分钟滚动监测", "5 分钟监测");
}

function tBoardRiskText(item) {
  const risk = String(item?.risk_tip || "").trim();
  const reason = tBoardStoppedReason(item);
  if (reason === "board_open") return "封板失败";
  if (reason === "sell_pressure") return "卖压占优";
  if (reason === "not_triggered") return "未触发";
  const emptyDisclaimerTokens = ["仅作" + "观察", "不自动" + "下单", "不代表" + "买入建议", "不构成" + "投资建议"];
  const emptyDisclaimer = emptyDisclaimerTokens.some((token) => risk.includes(token));
  if (risk && !emptyDisclaimer) return risk;
  const status = String(item?.observation_status || "").toLowerCase();
  if (status === "opportunity") return "已触发，重点看收盘前能否封住";
  if (status === "continue_watch") return "还没触发，等下一次 5 分钟监测";
  if (status === "data_wait") return "数据缺口";
  if (status === "stopped") return "已停止";
  return risk;
}

function tBoardUpdateText(lastModelOutputAt, latestDataFetchAt) {
  const modelText = lastModelOutputAt ? formatDateTimeValue(lastModelOutputAt) : "未产出";
  const fetchText = latestDataFetchAt ? formatDateTimeValue(latestDataFetchAt) : "未推进";
  return `模型 ${modelText} / 抓取 ${fetchText}`;
}

function buildTBoardListRows(extra) {
  const items = arrayFromResponse(extra.observation_board?.data)
    .filter((item) => !tBoardShouldHideDefault(item));
  return items.map((item) => {
    const latestDataFetchAt = item.latest_data_fetch_at || item.last_data_captured_at || null;
    const lastModelOutputAt = item.last_model_output_at || item.model_evaluated_at || null;
    const projectionSnapshotAt = item.latest_projection_snapshot_at || null;
    const rowUpdatedAt = lastModelOutputAt || latestDataFetchAt || projectionSnapshotAt;
    return {
      stock: item.stock || { symbol: item.canonical_symbol, name: item.stock_name },
      observation_id: item.observation_id,
      observation_status: item.observation_status,
      model_score: item.model_score,
      model_score_label: item.model_score_label,
      score_state: item.score_state,
      model_score_version: item.model_score_version,
      current_conclusion: tBoardConclusionText(item),
      current_stage: item.current_stage,
      day1_trade_date: item.day1_trade_date,
      day2_trade_date: item.day2_trade_date,
      day2_trigger_time: item.day2_trigger_time || item.trigger_time,
      day3_trade_date: item.day3_trade_date,
      relay_strength_label: tBoardRelayStrengthText(item),
      next_observation: item.next_observation,
      key_reason: tBoardKeyReasonText(item),
      risk_tip: tBoardRiskText(item),
      latest_snapshot_time: tBoardUpdateText(lastModelOutputAt, latestDataFetchAt),
      updated_at: rowUpdatedAt,
      display_update_at: projectionSnapshotAt,
      latest_data_fetch_at: latestDataFetchAt,
      last_data_captured_at: item.last_data_captured_at || null,
      last_model_output_at: lastModelOutputAt,
      model_evaluated_at: item.model_evaluated_at || null,
      latest_projection_snapshot_at: projectionSnapshotAt,
      model_result_interval_minutes: item.model_result_interval_minutes,
      latest_model_result_snapshot_id: item.latest_model_result_snapshot_id || null,
      latest_projection_snapshot_id: item.latest_projection_snapshot_id || null,
      source_gaps: item.data_gap_labels || [],
      data_gap_count: item.data_gap_count || 0,
      game_state: item.game_state_label,
    };
  }).sort((a, b) => modelScoreSortValue(b) - modelScoreSortValue(a) || recordOrderValue(b) - recordOrderValue(a));
}

function modelListDescription(profile) {
  if (profile.key === "hot") return "只看已落库的热点模型结果，按模型分从高到低排；缺概率、缺买点或未过闸门时直接显示缺口。";
  if (profile.key === "memory") return "复刻旧版历史二波决策回顾 12 列：入选日、触发证据、模型分、最新价、评估基准、基准后涨幅、买入状态、最大回撤、验证、风险和更新；未物化字段保持空态。";
  if (profile.key === "ambush") return "复刻旧版潜伏抬头决策回顾 12 列：入选日、入选天数、模型分、最新价、评估基准、基准后涨幅、买入状态、最大回撤、验证、风险和更新；人工打标后续放在研究中心-低谷图库。";
  if (profile.key === "tboard") return "只看 Day1 通过对象，按模型分从高到低排；已停止的行直接写明原因。";
  return "模型列表";
}

function modelListTitle(profile) {
  if (profile.key === "memory") return "历史二波 / 决策回顾列表";
  if (profile.key === "ambush") return "潜伏抬头 / 决策回顾列表";
  if (profile.key === "tboard") return "T 字接力观察台";
  return "热点模型 / 决策回顾列表";
}

function renderModelListTable(profile, rows) {
  const columns = MODEL_LIST_COLUMNS[profile.key] || [];
  return `<div class="model-iteration-table-wrap">
    <table class="model-iteration-table model-iteration-table--${escapeClass(profile.key)} model-iteration-table--list">
      ${renderModelListColGroup(profile)}
      <thead class="model-iteration-table__native-head"><tr>${columns.map(([key, label]) => renderModelHeaderCell(key, label)).join("")}</tr></thead>
      <tbody data-model-table-body="true">${renderModelListTableRows(profile, rows)}</tbody>
    </table>
  </div>`;
}

function renderModelListTableRows(profile, rows) {
  const columns = MODEL_LIST_COLUMNS[profile.key] || [];
  if (!rows.length) {
    return renderEmptyTableRow(columns.length, profile.key === "tboard" ? "当前没有进入接力观察的股票。" : "当前没有真实列表记录。");
  }
  return rows.map((row, index) => `<tr class="model-iteration-row model-iteration-row--${escapeClass(profile.key)}" data-model-list-row="${index + 1}">${columns.map(([key, label]) => `<td class="${modelListCellClass(key, row[key], row)}" data-label="${escapeHtml(label)}">${renderModelCell(key, row[key], row)}</td>`).join("")}</tr>`).join("");
}

function renderModelListStickyHeader(profile) {
  const columns = MODEL_LIST_COLUMNS[profile.key] || [];
  return `<div class="decision-review-sticky-table-wrap" data-decision-review-sticky-table-header="true">
    <table class="model-iteration-table model-iteration-table--${escapeClass(profile.key)} model-iteration-table--list decision-review-sticky-table">
      ${renderModelListColGroup(profile)}
      <thead><tr>${columns.map(([key, label]) => renderModelHeaderCell(key, label)).join("")}</tr></thead>
    </table>
  </div>`;
}

function renderModelListColGroup(profile) {
  const columns = MODEL_LIST_COLUMNS[profile.key] || [];
  const widths = MODEL_LIST_COLUMN_WIDTHS[profile.key] || {};
  return `<colgroup>${columns.map(([key]) => {
    const kind = modelListColumnKind(key);
    const width = Number(widths[key] || 0);
    const style = width > 0 ? ` style="width:${width}px"` : "";
    return `<col class="model-iteration-col model-iteration-col--kind-${escapeClass(kind)} model-iteration-col-key--${escapeClass(key)}"${style}>`;
  }).join("")}</colgroup>`;
}

function renderModelHeaderCell(key, label) {
  const kind = modelListColumnKind(key);
  return `<th class="model-iteration-header model-iteration-header--kind-${escapeClass(kind)} model-iteration-header-key--${escapeClass(key)}" data-column="${escapeHtml(key)}"><span class="model-column-help model-column-help--plain"><span class="model-column-help__label">${escapeHtml(label)}</span></span></th>`;
}

function renderModelCell(key, value, row = {}) {
  if (key === "stock") {
    if (value && typeof value === "object") {
      return renderStockFinanceName(value.symbol, display(value.symbol), stockNameLabel(value.name, value.symbol));
    }
    return renderStockFinanceName(value, display(value), "");
  }
  if (key === "source") return escapeHtml(providerLabel(value));
  if (key === "source_gaps") {
    const count = gapCount(value);
    return `<span class="model-gap-count ${count ? "model-gap-count--warning" : "model-gap-count--ready"}">${count}</span>${count ? `<small>${escapeHtml(value.slice(0, 2).map(businessStatusLabel).join(" / "))}</small>` : `<small>已齐</small>`}`;
  }
  if (key === "readiness_score_pct") {
    if (!isFiniteNumber(value)) return `<span class="model-empty">待评估</span>`;
    const missing = isFiniteNumber(row.missing_points) ? Number(row.missing_points) : null;
    const state = businessStatusLabel(row.readiness_state);
    const top = row.top_missing_dimension?.label || businessStatusLabel(row.top_missing_dimension?.gap_code);
    const sub = missing && missing > 0 ? `缺 ${missing} 分${top && top !== "-" ? ` · ${top}` : ""}` : "100% 已齐";
    return `<span class="model-score-pair"><strong>${escapeHtml(formatScore(value))}%</strong><small>${escapeHtml(state)} · ${escapeHtml(sub)}</small></span>`;
  }
  if (key === "data_quality") return `<span class="model-status-text">${escapeHtml(sourceQualityLabel(value))}</span>`;
  if (key === "current_conclusion" || key === "current_stage" || key === "next_observation" || key === "key_reason" || key === "risk_tip" || key === "relay_strength_label") {
    return `<span class="model-status-text">${escapeHtml(display(value))}</span>`;
  }
  if (key === "row_state" || key.endsWith("_status") || key === "release_gate" || key === "memory_state" || key === "outcome_label" || key === "game_state" || key === "risk_level" || key === "risk_summary" || key === "verification_status" || key === "entry_opportunity_status") {
    return `<span class="model-status-text">${escapeHtml(businessStatusLabel(value))}</span>`;
  }
  if (key === "model_score" && row.model_score_label && isFiniteNumber(value)) {
    return `<span class="model-score-pair"><strong>${escapeHtml(formatScore(value))}</strong><small>${escapeHtml(row.model_score_label)}</small></span>`;
  }
  if (key.includes("date") || key.includes("time") || key.endsWith("_at")) return escapeHtml(formatDateTimeValue(value));
  if (key.startsWith("is_") || key.endsWith("_flag") || key.endsWith("_pass") || key === "close_on_limit_flag") return escapeHtml(formatBool(value));
  if (key === "p_limit_up" || key.includes("_pct")) return escapeHtml(formatPercentValue(value));
  if (key === "ths_limit_up_probability") return escapeHtml(formatPercentValue(value));
  if (key.includes("price") || key === "current_price" || key === "adjusted_close") return escapeHtml(formatPrice(value));
  if (key.includes("score") || key.includes("risk")) return isFiniteNumber(value) ? escapeHtml(formatScore(value)) : escapeHtml(businessStatusLabel(value));
  if (key.includes("amount") || key.includes("market_cap") || key === "main_net_inflow") return escapeHtml(formatMoneyWan(value));
  if (typeof value === "boolean") return escapeHtml(formatBool(value));
  return escapeHtml(businessStatusLabel(value));
}

function modelListCellClass(key, value, row = {}) {
  const classes = [
    "model-iteration-cell",
    `model-iteration-cell--kind-${escapeClass(modelListColumnKind(key))}`,
    `model-iteration-cell-key--${escapeClass(key)}`,
  ];
  const tone = modelListCellTone(key, value, row);
  if (tone) classes.push(`model-iteration-cell--${escapeClass(tone)}`);
  return classes.join(" ");
}

function modelListColumnKind(key) {
  if (key === "stock") return "stock";
  if (key === "source_gaps") return "gaps";
  if (key === "readiness_score_pct") return "score";
  if (key === "is_t_board" || key === "selection_summary" || key === "relay_strength_label") return "short";
  if (key.includes("date") || key.includes("time") || key.endsWith("_at")) return key === "latest_snapshot_time" ? "updated" : "date";
  if (key === "ths_limit_up_probability") return "probability";
  if (key.includes("score")) return "score";
  if (key.includes("price") || key === "current_price") return "price";
  if (key.includes("_pct")) return "percent";
  if (key.includes("trigger") || key === "next_observation") return "trigger";
  if (key.includes("risk")) return "risk";
  if (key.includes("action")) return "action";
  if (key.includes("status") || key.includes("state") || key === "verification_status" || key === "entry_opportunity_status" || key === "outcome_label" || key === "current_conclusion" || key === "current_stage") return "status";
  return "text";
}

function modelListCellTone(key, value, row = {}) {
  if (key === "source_gaps") return gapCount(value) ? "data-gap" : "";
  if (key === "readiness_score_pct") {
    const score = Number(value);
    if (!Number.isFinite(score)) return "data-gap";
    if (score < 70 || row.readiness_state === "blocked") return "data-gap";
    if (score < 100 || row.readiness_state === "degraded") return "warning";
    return "";
  }
  if (key === "current_conclusion") {
    const status = String(row.observation_status || "").toLowerCase();
    if (status === "opportunity" || status === "completed") return "";
    if (status === "continue_watch" || status === "data_wait") return "warning";
    if (status === "stopped") return "risk";
  }
  const raw = String(value ?? "").toLowerCase();
  const label = businessStatusLabel(value);
  const rowGaps = gapCount(row.source_gaps);
  if (raw.includes("stale") || raw.includes("expired") || label.includes("过期")) return "stale";
  if (raw.includes("blocked") || raw.includes("reject") || raw.includes("failed") || raw.includes("invalid") || label.includes("阻断") || label.includes("拒绝") || label.includes("失败") || label.includes("失效")) return "risk";
  if (raw.includes("gap") || raw.includes("missing") || raw.includes("not_") || label.includes("缺口") || label.includes("缺")) return "data-gap";
  if (key === "risk_summary" && rowGaps) return "data-gap";
  if (raw.includes("waiting") || raw.includes("watch") || raw.includes("research") || label.includes("等待") || label.includes("观察")) return "warning";
  return "";
}

function renderEmptyTableRow(colspan, message) {
  return `<tr><td colspan="${Number(colspan) || 1}" class="empty-table-cell">${escapeHtml(message)}</td></tr>`;
}

function bindModelListChrome() {
  clearModelListChrome();
  const page = document.querySelector(".model-decision-list-page");
  const stickyStack = page?.querySelector(".decision-review-sticky-stack");
  const stickyWrap = page?.querySelector(".decision-review-sticky-table-wrap");
  const bodyWrap = page?.querySelector(".model-iteration-table-wrap");
  if (!stickyStack || !stickyWrap || !bodyWrap) return;
  const syncStickyLayout = () => {
    const position = window.getComputedStyle(stickyStack).position;
    const height = Math.ceil(stickyStack.getBoundingClientRect().height || 0);
    const pageTop = Math.max(0, Math.ceil(page.getBoundingClientRect().top || 0));
    const compactGap = 2;
    page.style.paddingTop = position === "fixed" && height > 0 ? `${Math.max(0, height + compactGap - pageTop)}px` : "0";
  };
  let syncing = false;
  const syncScroll = (source, target) => {
    if (syncing) return;
    syncing = true;
    target.scrollLeft = source.scrollLeft;
    requestAnimationFrame(() => {
      syncing = false;
    });
  };
  const onStickyScroll = () => syncScroll(stickyWrap, bodyWrap);
  const onBodyScroll = () => syncScroll(bodyWrap, stickyWrap);
  const onResize = () => syncStickyLayout();
  stickyWrap.addEventListener("scroll", onStickyScroll, { passive: true });
  bodyWrap.addEventListener("scroll", onBodyScroll, { passive: true });
  const resetHorizontalScroll = () => {
    stickyWrap.scrollLeft = 0;
    bodyWrap.scrollLeft = 0;
  };
  resetHorizontalScroll();
  requestAnimationFrame(resetHorizontalScroll);
  syncStickyLayout();
  requestAnimationFrame(syncStickyLayout);
  window.addEventListener("resize", onResize, { passive: true });
  state.modelListChromeCleanup = () => {
    stickyWrap.removeEventListener("scroll", onStickyScroll);
    bodyWrap.removeEventListener("scroll", onBodyScroll);
    window.removeEventListener("resize", onResize);
  };
}

function renderModelSummary(profile, ready, health, preflight, extra, listRows = []) {
  const rows = [
    ["模型", modelBusinessName(profile.modelCode)],
    ["服务状态", modelBusinessName(profile.service)],
    ["样本标的", profile.symbol],
    ["就绪检查", ready.data?.status || ready.error],
    ["健康检查", health.data?.status || health.error],
    ["覆盖状态", preflight.data?.coverage_status || "-"],
    ["新鲜度", preflight.data?.freshness_status || "-"],
    ["列表记录", listRows.length],
  ];
  if (profile.key === "tboard") {
    const repo = extra.data?.repository?.data;
    rows.push(["仓库状态", repo?.repository_attached === true ? "已连接" : display(repo?.repository_attached)]);
    if (repo?.table_counts) {
      Object.entries(repo.table_counts).forEach(([key, value]) => rows.push([repositoryCountLabel(key), value]));
    }
  }
  return `<div class="model-iteration-table-wrap"><table class="model-iteration-table model-iteration-table--${escapeHtml(profile.key)}"><tbody>${rows.map(([key, value]) => `<tr><th>${escapeHtml(key)}</th><td>${escapeHtml(display(value))}</td></tr>`).join("")}</tbody></table></div>`;
}

function repositoryCountLabel(key) {
  const labels = {
    day1_candidates: "Day1候选",
    day2_watch_snapshots: "Day2观察快照",
    day2_triggers: "Day2触发",
    post_entry_monitors: "封板维护",
    day3_decisions: "Day3去留",
    outcomes: "结果",
    game_hypotheses: "博弈假设",
    research_samples: "研究样本",
  };
  return labels[key] || businessStatusLabel(key);
}

async function loadAmbushValleyResearchData(force = false, pageEpoch = state.pageEpoch, routeKey = "research-ambush-valley") {
  if (state.ambushValley.loading) return;
  if (state.ambushValley.loaded && !force) return;
  state.ambushValley.loading = true;
  state.ambushValley.error = null;
  try {
    const [casesResult, taxonomyResult] = await Promise.all([
      safeLoad(() => researchApi("research/ambush/valley-chart/cases", { timeoutMs: FRONTEND_TABLE_TIMEOUT_MS })),
      safeLoad(() => researchApi("research/ambush/taxonomy", { timeoutMs: FRONTEND_TABLE_TIMEOUT_MS })),
    ]);
    if (isStalePage(pageEpoch, routeKey)) return;
    state.ambushValley.cases = arrayFromResponse(casesResult.data);
    state.ambushValley.taxonomy = arrayFromResponse(taxonomyResult.data);
    state.ambushValley.loaded = true;
    state.ambushValley.error = [casesResult, taxonomyResult].filter((item) => !item.ok).map((item) => frontendErrorLabel(item.error)).join("；") || null;
    if (!state.ambushValley.selectedCaseId && state.ambushValley.cases[0]) {
      state.ambushValley.selectedCaseId = state.ambushValley.cases[0].chart_case_id;
    }
  } finally {
    state.ambushValley.loading = false;
  }
}

async function renderAmbushValleyResearchPage(options = {}) {
  const pageEpoch = options.pageEpoch ?? state.pageEpoch;
  const routeKey = options.routeKey ?? "research-ambush-valley";
  const root = $("#page-root");
  if (!state.ambushValley.loaded) {
    root.innerHTML = `<section class="panel"><strong>正在读取低谷图库研究资产...</strong></section>`;
  }
  await loadAmbushValleyResearchData(false, pageEpoch, routeKey);
  if (isStalePage(pageEpoch, routeKey)) return;
  root.innerHTML = renderAmbushValleyResearchWorkbench();
  bindAmbushValleyResearchActions(pageEpoch, routeKey);
}

function renderAmbushValleyResearchWorkbench() {
  const cases = state.ambushValley.cases || [];
  const selected = cases.find((item) => item.chart_case_id === state.ambushValley.selectedCaseId) || cases[0] || null;
  const taxonomy = taxonomyForMode(state.ambushValley.labelMode);
  return `<section class="research-workbench ambush-valley-workbench">
    <div class="research-hero ${cases.length ? "research-hero--ready" : "research-hero--empty"}">
      <div>
      <span class="hot-mini-label">当前候选草稿</span>
      <strong>规划与差异对比</strong>
        <p>把人工低谷经验沉淀为可复核、可追溯、可研究的结构化样本。这里写入研究资产，不改模型分数、发布状态或交易事实。</p>
      </div>
      <dl>
        <div><dt>样本数量</dt><dd>${escapeHtml(cases.length)}</dd></div>
        <div><dt>标注字典</dt><dd>${escapeHtml(state.ambushValley.taxonomy.length ? "已读取" : "等待研究服务")}</dd></div>
        <div><dt>当前模式</dt><dd>${escapeHtml(ambushLabelModeLabel(state.ambushValley.labelMode))}</dd></div>
        <div><dt>动态特征</dt><dd>${escapeHtml("缺失保持缺口")}</dd></div>
      </dl>
    </div>
    ${state.ambushValley.error ? `<div class="notice-bar"><strong>研究服务暂不可读</strong><span>${escapeHtml(state.ambushValley.error)}</span></div>` : ""}
    <div class="research-layout">
      <aside class="panel research-queue-panel">
        <div class="panel__head">
          <h2 class="panel-title">样本队列</h2>
          <button class="secondary-button" data-action="reload-ambush-valley">重新读取</button>
        </div>
        <div class="research-case-list">
          ${cases.length ? cases.map(renderAmbushValleyCaseButton).join("") : `<div class="research-empty">暂无低谷图库样本。可以先登记一只真实复盘样本。</div>`}
        </div>
        ${renderAmbushValleyCaseCreateForm()}
      </aside>
      <main class="research-main-panel">
        ${selected ? renderAmbushValleyCaseDetail(selected, taxonomy) : renderAmbushValleyEmptyDetail(taxonomy)}
      </main>
    </div>
  </section>`;
}

function renderAmbushValleyCaseButton(item) {
  const active = item.chart_case_id === state.ambushValley.selectedCaseId ? "is-active" : "";
  return `<button class="research-case-item ${active}" data-action="select-ambush-valley-case" data-case-id="${escapeHtml(item.chart_case_id)}">
    <strong>${escapeHtml(display(item.canonical_symbol))}</strong>
    <span>${escapeHtml(stockNameLabel(item.stock_name, item.canonical_symbol))}</span>
    <small>${escapeHtml(formatDateTimeValue(item.case_trade_date))} · ${escapeHtml(ambushCaseStatusLabel(item.case_status))}</small>
  </button>`;
}

function renderAmbushValleyCaseCreateForm() {
  return `<form class="research-create-form" data-form="ambush-valley-case">
    <h3>登记复盘样本</h3>
    <label>股票代码<input name="${AMBUSH_VALLEY_FORM_KEYS.stockCode}" class="field" placeholder="000759.SZ" autocomplete="off"></label>
    <label>股票名称<input name="${AMBUSH_VALLEY_FORM_KEYS.stockName}" class="field" placeholder="名称暂未发布可留空" autocomplete="off"></label>
    <label>样本日期<input name="${AMBUSH_VALLEY_FORM_KEYS.sampleDate}" class="field" type="date"></label>
    <label>低点日期<input name="${AMBUSH_VALLEY_FORM_KEYS.valleyLowDate}" class="field" type="date"></label>
    <label>抬头日期<input name="${AMBUSH_VALLEY_FORM_KEYS.turnDate}" class="field" type="date"></label>
      <button class="primary-button" type="submit">保存并抓取</button>
  </form>`;
}

function renderAmbushValleyEmptyDetail(taxonomy) {
  return `<div class="panel research-detail-panel">
    <div class="panel__head"><h2 class="panel-title">等待样本</h2></div>
    <div class="research-empty research-empty--large">当前没有可标注的低谷图形样本。页面不会生成示例股票；请登记真实样本或等待研究服务生成样本队列。</div>
    ${renderAmbushTaxonomyPreview(taxonomy)}
  </div>`;
}

function renderAmbushValleyCaseDetail(item, taxonomy) {
  return `<div class="research-case-detail-grid">
    <section class="panel research-chart-panel">
      <div class="panel__head">
        <h2 class="panel-title">${escapeHtml(item.canonical_symbol)} · ${escapeHtml(stockNameLabel(item.stock_name, item.canonical_symbol))}</h2>
        <span class="status-pill status-${escapeClass(ambushCaseStatusTone(item.case_status))}">${escapeHtml(ambushCaseStatusLabel(item.case_status))}</span>
      </div>
      ${renderAmbushValleyChart(item)}
      ${renderAmbushValleyFactStrip(item)}
    </section>
    <section class="panel research-label-panel">
      <div class="panel__head">
        <h2 class="panel-title">人工标注</h2>
        <div class="segmented-control" role="group" aria-label="标注模式">
          <button class="${state.ambushValley.labelMode === "as_of" ? "is-active" : ""}" data-action="set-ambush-label-mode" data-mode="as_of">当时可见</button>
          <button class="${state.ambushValley.labelMode === "outcome_review" ? "is-active" : ""}" data-action="set-ambush-label-mode" data-mode="outcome_review">事后复盘</button>
        </div>
      </div>
      <p class="candidate-section-note">${escapeHtml(state.ambushValley.labelMode === "as_of" ? "只标当时能看到的结构，不允许填写结果标签。" : "可以记录假抬头、硬负样本和结果归因，但仍只写研究资产。")}</p>
      <form class="research-label-form" data-form="ambush-valley-label" data-case-id="${escapeHtml(item.chart_case_id)}">
        <label>结构判断<input name="${AMBUSH_VALLEY_FORM_KEYS.structure}" class="field" placeholder="例如：低谷成熟"></label>
        <label>抬头时机<input name="${AMBUSH_VALLEY_FORM_KEYS.timing}" class="field" placeholder="例如：刚抬头"></label>
        <label>样本角色<input name="${AMBUSH_VALLEY_FORM_KEYS.role}" class="field" placeholder="例如：正样本低谷"></label>
        ${state.ambushValley.labelMode === "outcome_review" ? `<label>结果归因<input name="${AMBUSH_VALLEY_FORM_KEYS.outcome}" class="field" placeholder="例如：假反弹"></label>` : ""}
        <label>标注信心
          <select name="${AMBUSH_VALLEY_FORM_KEYS.confidence}" class="field">
            <option value="medium">中</option>
            <option value="high">高</option>
            <option value="low">低</option>
          </select>
        </label>
        <div class="research-taxonomy-grid">${taxonomy.length ? taxonomy.map(renderAmbushTaxonomyCheck).join("") : `<span class="research-empty">标注字典暂未读取。</span>`}</div>
        <label>备注<textarea name="${AMBUSH_VALLEY_FORM_KEYS.note}" class="field" rows="3" placeholder="记录可复核的形态理由"></textarea></label>
        <button class="primary-button" type="submit">保存标注</button>
      </form>
      ${renderAmbushTaxonomyPreview(taxonomy)}
    </section>
  </div>`;
}

function renderAmbushValleyChart(item) {
  const bars = Array.isArray(item.daily_bar_payload) ? item.daily_bar_payload : [];
  const usableBars = bars.filter((bar) => isFiniteNumber(bar.close_price || bar.adjusted_close || bar.close));
  if (!usableBars.length) {
    return `<div class="research-chart-empty">K 线事实暂未接入；样本仍可先做结构备注，缺口会保留。</div>`;
  }
  const closes = usableBars.map((bar) => Number(bar.close_price || bar.adjusted_close || bar.close));
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const range = Math.max(0.0001, max - min);
  const points = closes.map((close, index) => {
    const x = usableBars.length <= 1 ? 8 : 8 + (index / (usableBars.length - 1)) * 184;
    const y = 92 - ((close - min) / range) * 72;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  return `<div class="research-chart-box">
    <svg viewBox="0 0 200 110" role="img" aria-label="低谷价格路径">
      <polyline points="${escapeHtml(points)}" fill="none" stroke="#1f6feb" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"></polyline>
      <line x1="8" y1="92" x2="192" y2="92" stroke="#d9e5f2"></line>
    </svg>
    <div><strong>日线价格路径</strong><span>${escapeHtml(usableBars.length)} 个已读点位</span></div>
  </div>`;
}

function renderAmbushValleyFactStrip(item) {
  const rows = [
    ["样本日期", formatDateTimeValue(item.case_trade_date)],
    ["低点日期", formatDateTimeValue(item.valley_low_date)],
    ["抬头日期", formatDateTimeValue(item.turn_anchor_date)],
    ["来源", ambushCaseSourceLabel(item.case_source)],
    ["标准事实缺口", gapCount(item.source_gap_codes)],
    ["动态特征缺口", gapCount(item.dynamic_gap_codes)],
  ];
  return `<div class="research-fact-strip">${rows.map(([label, value]) => `<div><span>${escapeHtml(label)}</span><strong>${escapeHtml(display(value))}</strong></div>`).join("")}</div>`;
}

function renderAmbushTaxonomyCheck(item) {
  return `<label class="research-taxonomy-option">
    <input type="checkbox" name="${AMBUSH_VALLEY_FORM_KEYS.tags}" value="${escapeHtml(item.tag_code)}">
    <span>${escapeHtml(item.tag_name)}</span>
  </label>`;
}

function renderAmbushTaxonomyPreview(taxonomy) {
  return `<div class="research-taxonomy-preview">
      <strong>规划与差异对比</strong>
    <div>${taxonomy.length ? taxonomy.slice(0, 8).map((item) => `<span>${escapeHtml(item.tag_name)}</span>`).join("") : "<span>等待研究服务</span>"}</div>
  </div>`;
}

function bindAmbushValleyResearchActions(pageEpoch, routeKey) {
  $("[data-action='reload-ambush-valley']")?.addEventListener("click", async () => {
    state.ambushValley.loaded = false;
    await renderAmbushValleyResearchPage({ pageEpoch, routeKey });
  });
  $$("[data-action='select-ambush-valley-case']").forEach((button) => {
    button.addEventListener("click", () => {
      state.ambushValley.selectedCaseId = button.dataset.caseId;
      $("#page-root").innerHTML = renderAmbushValleyResearchWorkbench();
      bindAmbushValleyResearchActions(pageEpoch, routeKey);
    });
  });
  $$("[data-action='set-ambush-label-mode']").forEach((button) => {
    button.addEventListener("click", () => {
      state.ambushValley.labelMode = button.dataset.mode || "as_of";
      $("#page-root").innerHTML = renderAmbushValleyResearchWorkbench();
      bindAmbushValleyResearchActions(pageEpoch, routeKey);
    });
  });
  $("[data-form='ambush-valley-case']")?.addEventListener("submit", submitAmbushValleyCase);
  $("[data-form='ambush-valley-label']")?.addEventListener("submit", submitAmbushValleyLabel);
}

async function submitAmbushValleyCase(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const formData = new FormData(form);
  const symbol = String(formData.get(AMBUSH_VALLEY_FORM_KEYS.stockCode) || "").trim().toUpperCase();
  const tradeDate = String(formData.get(AMBUSH_VALLEY_FORM_KEYS.sampleDate) || "").trim();
  if (!symbol || !tradeDate) {
    toast("暂未读到可抓取的候选交易日。");
    return;
  }
  const payload = {
    canonical_symbol: symbol,
    stock_name: optionalFormValue(formData, AMBUSH_VALLEY_FORM_KEYS.stockName),
    case_trade_date: tradeDate,
    case_source: "manual",
    valley_low_date: optionalFormValue(formData, AMBUSH_VALLEY_FORM_KEYS.valleyLowDate),
    turn_anchor_date: optionalFormValue(formData, AMBUSH_VALLEY_FORM_KEYS.turnDate),
    dynamic_gap_codes: ["source_gap:dynamic_feature_bundle_missing"],
    created_by: state.user?.username || "operator",
  };
  try {
    const result = await researchApi("research/ambush/valley-chart/cases", { method: "POST", body: payload, timeoutMs: FRONTEND_DEFAULT_TIMEOUT_MS });
    toast("暂未读到可抓取的候选交易日。");
    state.ambushValley.loaded = false;
    state.ambushValley.selectedCaseId = result.item?.chart_case_id || state.ambushValley.selectedCaseId;
    await renderAmbushValleyResearchPage({ pageEpoch: state.pageEpoch, routeKey: state.route });
  } catch (error) {
    toast(frontendErrorLabel(error));
  }
}

async function submitAmbushValleyLabel(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const chartCaseId = form.dataset.caseId;
  const formData = new FormData(form);
  const tags = formData.getAll(AMBUSH_VALLEY_FORM_KEYS.tags).map((item) => String(item));
  const payload = {
    labeler_id: state.user?.username || "operator",
    labeler_role: state.user?.role || "operator",
    label_mode: state.ambushValley.labelMode,
    valley_structure_label: optionalFormValue(formData, AMBUSH_VALLEY_FORM_KEYS.structure),
    turn_timing_label: optionalFormValue(formData, AMBUSH_VALLEY_FORM_KEYS.timing),
    sample_role_label: optionalFormValue(formData, AMBUSH_VALLEY_FORM_KEYS.role),
    outcome_label: optionalFormValue(formData, AMBUSH_VALLEY_FORM_KEYS.outcome),
    manual_label_confidence: String(formData.get(AMBUSH_VALLEY_FORM_KEYS.confidence) || "medium"),
    manual_label_note: optionalFormValue(formData, AMBUSH_VALLEY_FORM_KEYS.note),
    visible_feature_boundary: {
      mode: state.ambushValley.labelMode,
      note: state.ambushValley.labelMode === "as_of" ? "只包含当时可见结构" : "事后复盘标签",
    },
    tags,
  };
  try {
    await researchApi(`research/ambush/valley-chart/cases/${encodeURIComponent(chartCaseId)}/labels`, { method: "POST", body: payload, timeoutMs: FRONTEND_DEFAULT_TIMEOUT_MS });
    toast("暂未读到可抓取的候选交易日。");
    state.ambushValley.loaded = false;
    await renderAmbushValleyResearchPage({ pageEpoch: state.pageEpoch, routeKey: state.route });
  } catch (error) {
    toast(frontendErrorLabel(error));
  }
}

function optionalFormValue(formData, key) {
  const value = String(formData.get(key) || "").trim();
  return value || null;
}

function taxonomyForMode(mode) {
  return (state.ambushValley.taxonomy || []).filter((item) => item.allowed_label_mode === "both" || item.allowed_label_mode === mode);
}

function ambushLabelModeLabel(mode) {
  return mode === "outcome_review" ? "事后复盘" : "当时可见";
}

function ambushCaseStatusLabel(status) {
  const labels = {
    pending_labeling: "待标注",
    labeled: "已标注",
    review_required: "待复核",
    approved: "已复核",
    archived: "已归档",
    data_blocked: "数据阻断",
  };
  return labels[String(status || "")] || businessStatusLabel(status);
}

function ambushCaseSourceLabel(source) {
  const labels = {
    manual: "人工登记",
    valley_watch_pool: "低谷观察池",
    effective_turn_pool: "有效抬头池",
    outcome_label: "结果样本",
  };
  return labels[String(source || "")] || "研究样本";
}

function ambushCaseStatusTone(status) {
  const raw = String(status || "");
  if (raw.includes("approved") || raw.includes("labeled")) return "ready";
  if (raw.includes("blocked")) return "blocked";
  return "pending";
}

async function safeLoad(fn) {
  try {
    return { ok: true, data: await fn() };
  } catch (error) {
    return { ok: false, error: error.message };
  }
}

function toast(message) {
  const root = $("#toast-root");
  if (!root) return;
  const item = document.createElement("div");
  item.className = "toast";
  item.textContent = message;
  root.appendChild(item);
  setTimeout(() => item.remove(), 2600);
}

async function init() {
  bindLogin();
  window.addEventListener("hashchange", () => {
    state.route = normalizeRoute(location.hash);
    renderApp();
  });
  await loadSession();
}

init();
