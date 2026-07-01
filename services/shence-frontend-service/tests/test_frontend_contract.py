from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from shence_frontend_service import main as frontend_main
from shence_frontend_service.main import app

SERVICE_ROOT = Path(__file__).resolve().parents[1]
APP_JS = SERVICE_ROOT / "public" / "app.js"
APP_CSS = SERVICE_ROOT / "public" / "app.css"
INDEX_HTML = SERVICE_ROOT / "public" / "index.html"


def _source() -> str:
    return APP_JS.read_text(encoding="utf-8")


def test_login_page_reuses_direct_login_shell() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")

    assert "login-root" in html
    assert "login-form" in html
    assert "login-username" in html
    assert "login-password" in html
    assert "欢迎来到AI神策中心" in html


def test_only_candidate_and_four_model_routes_are_open() -> None:
    source = _source()

    for route in [
        "candidates",
        "model-hot",
        "model-memory",
        "model-ambush",
        "model-tboard",
        "research-ambush-valley",
    ]:
        assert f'key: "{route}"' in source

    for hidden in [
        "workspace",
        "external",
        "recommendations",
        "health",
        "settings",
        "jarvis",
        "research-rank-regret",
        "research-ablation",
        "research-golden",
    ]:
        assert f'key: "{hidden}"' not in source


def test_candidate_page_uses_cookie_config_and_readonly_paid_probability() -> None:
    source = _source()

    for field in [
        "symbol",
        "stock_name",
        "rank_no",
        "limit_up_stage",
        "limit_up_type",
        "limit_up_open_count",
        "first_limit_up_at",
        "last_limit_up_at",
        "ths_limit_up_probability",
        "p_limit_up_source",
        "paid_probability_updated_at",
        "source.ths_paid_limit_up_probability_v1",
        "sourcePaidProbabilityApi",
        "candidate-cookie-config",
        "candidate-cookie-form",
        "candidate-cookie-saved",
        "fetch-current-batch",
        "batch-status?trade_date",
        "abandoned_no_probability_before_deadline",
        "shouldShowPaidProbabilityCookieForm",
        "isPaidProbabilityCookieUsable",
        "enrichmentError",
        "source_enrichment_degraded",
        "paidProbabilityBatchMessage",
    ]:
        assert field in source

    assert "保存并抓取" in source
    assert "立即抓取" in source
    assert "Cookie 已保存，开始抓取同花顺付费概率。" in source
    assert 'pending_probe: "Cookie 可用"' in source
    assert "真实接口探测失败前不展示编辑入口" in source
    assert "同花顺登录已失效，请更新 Cookie 后重新抓取。" in source
    assert "Cookie 已留存，正在等待付费概率入库。" in source
    assert "已过 ${paidProbabilityDeadlineLabel(batchStatus)} 仍未取得付费概率，本批候选已放弃。" in source
    assert 'configured: false, status: "missing"' not in source
    assert "未到该时间只阻断，不放弃候选" in source
    assert "候选草稿" in source
    assert "入库前检查" in source
    assert "等待当天涨停候选" in source
    assert "暂无可抓取概率的候选，请先等待当天涨停事实入库。" in source
    assert "当天候选已读到" in source
    assert "源数据复核" in source
    assert "candidate-draft-hero" in source
    assert "candidate-gate-panel" in source
    assert "candidate-source-panel" in source
    assert "probability-input" not in source
    assert "fillRandomTestProbabilities" not in source
    assert "test_random_probability" not in source
    assert "data-candidate-field" not in source
    assert "已提交生产" not in source
    assert "生成联调载荷" not in source
    assert "本地联调载荷" not in source


def test_candidate_page_localizes_source_status_and_missing_fields() -> None:
    source = _source()

    assert "sourceQualityLabel" in source
    assert "providerLabel" in source
    assert "frontendErrorLabel" in source
    assert "读取超时，页面已保留可见数据。" in source
    assert "读取失败，页面已保留中文空态。" in source
    assert "账号或密码不正确，请重新输入。" in source
    assert "涨停结构待核验" in source
    assert "质量待核验" in source
    assert "来源待核验" in source
    assert "涨停原因暂未发布" in source
    assert "名称暂未发布" in source
    assert "可用" in source
    assert "同花顺" in source
    assert "businessStatusLabel" in source
    assert "缺口：同花顺付费概率缺失" in source
    assert "入库前检查" in source
    assert "源数据复核" in source
    assert "renderCandidatePayloadSummary" not in source
    assert "已入库涨停事实" in source
    assert "usable · ths" not in source
    assert 'source_visible: "source可见"' not in source
    assert "source未返回" not in source
    assert "Payload Preview" not in source
    assert "提交载荷预览" not in source
    assert "正在读取 source.limit_event_v1" not in source
    assert "request timeout after" not in source
    assert "401 ${error.message}" not in source
    assert "admin · operator" not in source


def test_candidate_empty_state_does_not_treat_zero_rows_as_ready() -> None:
    source = _source()
    stats_body = source.split("function buildCandidateDraftStats", 1)[1].split("function renderCandidateDraftHero", 1)[0]
    gate_body = source.split("function renderCandidateDraftGate", 1)[1].split("function renderCandidateSourceEvidencePanel", 1)[0]
    load_body = source.split("async function loadCandidateSourceData", 1)[1].split("function buildCandidateRowsFromSource", 1)[0]

    assert 'probabilityText: hasCandidates ? `${filled}/${total}` : "等待候选"' in stats_body
    assert 'probabilitySubtext: hasCandidates ? paidProbabilityBatchStatusLabel(batchStatus) : "没有可抓取股票"' in stats_body
    assert '["付费概率已入库", stats.total > 0 && stats.missingCount === 0]' in gate_body
    assert '["概率范围有效", stats.total > 0 && !(audit.blocking_reasons || []).includes("invalid_p_limit_up_range")]' in gate_body
    assert "hasDisplayRows ? safeLoad(() => loadSourceRows(\"source.daily_bar_v1\"" in load_body
    assert "hasDisplayRows ? safeLoad(() => loadSourceRows(\"source.ths_paid_limit_up_probability_v1\"" in load_body
    assert "sourcePaidProbabilityApi(\"cookie/status\"" in load_body
    assert "PREFERRED_CANDIDATE_TRADE_DATE" in source
    assert "当前页不拿历史记录冒充当前候选" in source
    assert "const PREFERRED_CANDIDATE_TRADE_DATE = null" in source


def test_four_model_pages_use_locked_backend_readonly_contract() -> None:
    source = _source()

    assert 'modelCode: "hot_candidates"' in source
    assert 'modelCode: "candidate_memory"' in source
    assert 'modelCode: "ambush_watchlist"' in source
    assert 'modelCode: "t_board_relay"' in source
    assert "/api/source/preflight" in source
    assert "/api/model-list/hot" in source
    assert "/api/model-list/tboard" in source
    assert 'readinessValue = averageReadiness === null ? "暂无"' in source
    assert "待评估" in source
    assert "FRONTEND_HOT_MODEL_LIST_LIMIT = 20" in source
    assert "FRONTEND_HOT_MODEL_LIST_TIMEOUT_MS = 24000" in source
    assert "FRONTEND_TBOARD_COMPACT_TIMEOUT_MS = 24000" in source
    assert "TBOARD_AUTO_REFRESH_MS = 60000" in source
    assert "research/model-list/hot" in (SERVICE_ROOT / "src" / "shence_frontend_service" / "main.py").read_text(encoding="utf-8")
    assert "t-board-relay/repository/status" in source
    assert "t-board-relay/observation-board" in source
    assert "t-board-relay/day1/candidates" in (SERVICE_ROOT / "src" / "shence_frontend_service" / "main.py").read_text(encoding="utf-8")
    assert "day1_scan_summary" in (SERVICE_ROOT / "src" / "shence_frontend_service" / "main.py").read_text(encoding="utf-8")
    assert "renderTBoardDay1ScanSummary" in source
    assert "最近 Day1 扫描" in source
    assert '模型 ${data.last_model_output_at ? formatDateTimeValue(data.last_model_output_at) : "未产出"}' in source
    assert '抓取 ${data.latest_data_fetch_at ? formatDateTimeValue(data.latest_data_fetch_at) : "未推进"}' in source
    assert "renderModelRefreshStatus" in source
    assert "compact_audit_payloads" in (SERVICE_ROOT / "src" / "shence_frontend_service" / "main.py").read_text(encoding="utf-8")
    assert "前端只读展示，不触发模型评分" in source
    assert "renderHotReadinessKpis(profile, listRows, visibleRows)" in source
    assert "renderHotReadinessCoverage(profile, listRows)" in source
    assert "data-model-readiness-kpis" in source
    assert "data-model-readiness-coverage" in source
    assert "数据准备度" in source
    assert "P0阻断" in source
    assert "准备度维度" in source
    assert '["热点决策列表", "热点模型结果"' in source
    assert "research-service 决策投影" not in source
    assert "只读 decision_hot 已落库结果" not in source


def test_hot_model_list_compact_uses_research_service_projection(monkeypatch) -> None:
    async def fake_fetch(_client, *, service: str, path: str, headers: dict[str, str]):
        assert service == "research-service"
        assert path == "research/model-list/hot?limit=20"
        assert headers is not None
        return {
            "contract_kind": "research_hot_model_list_v1",
            "model_code": "hot_candidates",
            "read_only": True,
            "items": [
                {
                    "stock": {"symbol": "000759.SZ", "name": "中百集团"},
                    "model_score": 88.5,
                    "readiness_score_pct": 78,
                    "missing_points": 22,
                    "readiness_state": "blocked",
                    "top_missing_dimension": {"code": "ths_paid_probability", "label": "ths probability"},
                    "readiness_dimensions": [
                        {
                            "code": "ths_paid_probability",
                            "label": "ths probability",
                            "priority": "P0",
                            "weight": 22,
                            "earned": 0,
                            "missing": 22,
                            "status": "missing",
                            "gap_code": "source_gap:ths_paid_probability_missing",
                        }
                    ],
                    "request_payload": {"hidden": True},
                    "result_payload": {"hidden": True},
                }
            ],
        }

    monkeypatch.setattr(frontend_main, "_fetch_backend_json", fake_fetch)
    client = TestClient(app)
    client.post("/api/auth/login", json={"username": "admin", "password": "admin"})

    response = client.get("/api/model-list/hot?limit=20")

    assert response.status_code == 200
    body = response.json()
    assert body["contract_kind"] == "shence_hot_model_list_compact_v1"
    assert body["read_only"] is True
    assert body["hot_model"]["data"]["items"][0]["model_score"] == 88.5
    assert body["hot_model"]["data"]["items"][0]["readiness_score_pct"] == 78
    assert body["hot_model"]["data"]["items"][0]["missing_points"] == 22
    assert body["hot_model"]["data"]["items"][0]["top_missing_dimension"]["code"] == "ths_paid_probability"
    encoded = frontend_main.dumps_compact(body)
    assert "request_payload" not in encoded
    assert "result_payload" not in encoded


def test_tboard_compact_day1_summary_does_not_expose_audit_payloads(monkeypatch) -> None:
    async def fake_fetch(_client, *, service: str, path: str, headers: dict[str, str]):
        assert service == "tboard"
        assert headers is not None
        if path.startswith("t-board-relay/repository/status"):
            return {"repository_attached": True, "table_ready": True}
        if path.startswith("t-board-relay/observation-board"):
            return {
                "items": [
                    {
                        "stock": {"symbol": "002297.SZ", "name": "博云新材"},
                        "model_score": 15,
                        "latest_data_fetch_at": "2026-06-24T09:40:00+08:00",
                        "last_model_output_at": "2026-06-24T10:02:00+08:00",
                        "latest_projection_snapshot_at": "2026-06-24T10:05:00+08:00",
                        "current_conclusion": "已触发，继续看封板",
                        "request_payload": {"hidden": True},
                        "result_payload": {"hidden": True},
                    }
                ]
            }
        if path.startswith("t-board-relay/day1/candidates"):
            return {
                "items": [
                    {
                        "canonical_symbol": "600001.SH",
                        "trade_date": "2026-06-24",
                        "candidate_status": "rejected",
                        "reject_reason": "not_t_board",
                        "created_at": "2026-06-24T11:01:28+00:00",
                        "request_payload": {"hidden": True},
                        "result_payload": {"open_price": "9.00", "up_limit_price": "10.00"},
                    },
                    {
                        "canonical_symbol": "600002.SH",
                        "trade_date": "2026-06-24",
                        "candidate_status": "rejected",
                        "reject_reason": "not_t_board",
                        "created_at": "2026-06-24T11:01:29+00:00",
                        "result_payload": {"open_price": "8.00", "up_limit_price": "9.00"},
                    },
                ]
            }
        raise AssertionError(path)

    monkeypatch.setattr(frontend_main, "_fetch_backend_json", fake_fetch)
    client = TestClient(app)
    client.post("/api/auth/login", json={"username": "admin", "password": "admin"})

    response = client.get("/api/model-list/tboard?limit=20")

    assert response.status_code == 200
    body = response.json()
    summary = body["day1_scan_summary"]["data"]
    assert summary["trade_date"] == "2026-06-24"
    assert summary["scanned_count"] == 2
    assert summary["qualified_count"] == 0
    assert summary["open_on_limit_count"] == 0
    assert summary["latest_data_fetch_at"] == "2026-06-24T09:40:00+08:00"
    assert summary["last_model_output_at"] == "2026-06-24T10:02:00+08:00"
    assert summary["latest_projection_snapshot_at"] == "2026-06-24T10:05:00+08:00"
    assert summary["main_reason"] == "没有开盘即涨停，不满足模型四 Day1 T 字板条件"
    assert "严格 Day1 合格 0 只" in summary["summary_text"]
    encoded = frontend_main.dumps_compact(body)
    assert "day1_candidates" not in encoded
    assert "request_payload" not in encoded
    assert "result_payload" not in encoded


def test_tboard_compact_day1_summary_dedupes_latest_candidate_per_stock(monkeypatch) -> None:
    async def fake_fetch(_client, *, service: str, path: str, headers: dict[str, str]):
        assert service == "tboard"
        assert headers is not None
        if path.startswith("t-board-relay/repository/status"):
            return {"repository_attached": True, "table_ready": True}
        if path.startswith("t-board-relay/observation-board"):
            return {"items": []}
        if path.startswith("t-board-relay/day1/candidates"):
            return {
                "items": [
                    {
                        "canonical_symbol": "000823.SZ",
                        "trade_date": "2026-06-26",
                        "candidate_status": "rejected",
                        "reject_reason": "not_t_board",
                        "created_at": "2026-06-26T07:50:00+00:00",
                        "result_payload": {"open_price": "9.00", "up_limit_price": "10.00"},
                    },
                    {
                        "canonical_symbol": "000823.SZ",
                        "trade_date": "2026-06-26",
                        "candidate_status": "qualified",
                        "created_at": "2026-06-26T07:53:37+00:00",
                        "result_payload": {"open_on_limit_flag": True},
                    },
                    {
                        "stock": {"symbol": "600769.SH", "name": "祥龙电业"},
                        "trade_date": "2026-06-26",
                        "candidate_status": "rejected",
                        "reject_reason": "float_market_cap_out_of_range",
                        "created_at": "2026-06-26T07:53:38+00:00",
                        "result_payload": {"open_on_limit_flag": True},
                    },
                    {
                        "canonical_symbol": "999999.SH",
                        "trade_date": "2026-06-25",
                        "candidate_status": "qualified",
                        "created_at": "2026-06-25T07:53:38+00:00",
                    },
                ]
            }
        raise AssertionError(path)

    monkeypatch.setattr(frontend_main, "_fetch_backend_json", fake_fetch)
    client = TestClient(app)
    client.post("/api/auth/login", json={"username": "admin", "password": "admin"})

    response = client.get("/api/model-list/tboard?limit=20")

    assert response.status_code == 200
    summary = response.json()["day1_scan_summary"]["data"]
    assert summary["trade_date"] == "2026-06-26"
    assert summary["scanned_count"] == 2
    assert summary["qualified_count"] == 1
    assert summary["rejected_count"] == 1
    assert summary["open_on_limit_count"] == 2
    assert summary["updated_at"] == "2026-06-26T07:53:38+00:00"
    assert summary["reason_counts"] == [
        {"reason": "float_market_cap_out_of_range", "label": "流通市值不在 50 亿到 300 亿", "count": 1}
    ]
    assert "严格 Day1 合格 1 只" in summary["summary_text"]


def test_tboard_compact_hides_stale_stopped_rows_by_default(monkeypatch) -> None:
    async def fake_fetch(_client, *, service: str, path: str, headers: dict[str, str]):
        assert service == "tboard"
        assert headers is not None
        if path.startswith("t-board-relay/repository/status"):
            return {"repository_attached": True, "table_ready": True}
        if path.startswith("t-board-relay/observation-board"):
            return {
                "items": [
                    {
                        "stock": {"symbol": "600000.SH", "name": "过期失效"},
                        "observation_status": "stopped",
                        "day2_trade_date": "2026-06-20",
                        "model_score": 0,
                    },
                    {
                        "stock": {"symbol": "600001.SH", "name": "三天内失效"},
                        "observation_status": "stopped",
                        "day2_trade_date": "2026-06-22",
                        "model_score": 0,
                    },
                    {
                        "stock": {"symbol": "600002.SH", "name": "继续观察"},
                        "observation_status": "continue_watch",
                        "day2_trade_date": "2026-06-20",
                        "model_score": 70,
                    },
                ]
            }
        if path.startswith("t-board-relay/day1/candidates"):
            return {"items": []}
        raise AssertionError(path)

    monkeypatch.setattr(frontend_main, "_fetch_backend_json", fake_fetch)
    monkeypatch.setattr(frontend_main, "_tboard_market_today", lambda: date(2026, 6, 25))
    client = TestClient(app)
    client.post("/api/auth/login", json={"username": "admin", "password": "admin"})

    response = client.get("/api/model-list/tboard?limit=20")

    assert response.status_code == 200
    items = response.json()["observation_board"]["data"]["items"]
    assert [item["stock"]["symbol"] for item in items] == ["600001.SH", "600002.SH"]

    with_stale = client.get("/api/model-list/tboard?limit=20&include_stale_stopped=true")

    assert with_stale.status_code == 200
    all_items = with_stale.json()["observation_board"]["data"]["items"]
    assert [item["stock"]["symbol"] for item in all_items] == ["600000.SH", "600001.SH", "600002.SH"]


def test_frontend_uses_short_parallel_read_strategy() -> None:
    source = _source()
    candidate_body = source.split("async function loadCandidateSourceData", 1)[1].split("function buildCandidateRowsFromSource", 1)[0]
    extra_body = source.split("async function loadModelExtra", 1)[1].split("async function buildModelListRows", 1)[0]
    list_body = source.split("async function buildModelListRows", 1)[1].split("function rowsBySymbol", 1)[0]
    proxy_source = (SERVICE_ROOT / "src" / "shence_frontend_service" / "main.py").read_text(encoding="utf-8")

    assert "FRONTEND_DEFAULT_TIMEOUT_MS = 4500" in source
    assert "FRONTEND_TABLE_TIMEOUT_MS = 3500" in source
    assert "FRONTEND_FAST_TIMEOUT_MS = 2200" in source
    assert "FRONTEND_REPOSITORY_TIMEOUT_MS = 6000" in source
    assert "FRONTEND_SOURCE_STATUS_TIMEOUT_MS = 24000" in source
    assert "FRONTEND_HOT_MODEL_LIST_LIMIT" in extra_body
    assert "/api/model-list/hot?limit=${FRONTEND_HOT_MODEL_LIST_LIMIT}" in extra_body
    assert "buildHotModelListRows(extra.data || {})" in list_body
    assert 'loadLatestSourceRows("source.limit_event_v1", PREFERRED_CANDIDATE_TRADE_DATE' in candidate_body
    assert "hasDisplayRows ? safeLoad(() => loadSourceRows(\"source.daily_bar_v1\"" in candidate_body
    assert "hasDisplayRows ? safeLoad(() => loadSourceRows(\"source.ths_paid_limit_up_probability_v1\"" in candidate_body
    assert "sourcePaidProbabilityApi(`batch-status?trade_date=" in candidate_body
    assert "Promise.all([" in candidate_body
    assert "source_table_name=source.limit_event_v1\", 10000" not in source
    assert "Object.fromEntries(await Promise.all(tasks))" in extra_body
    assert "backend(profile.service, path, FRONTEND_REPOSITORY_TIMEOUT_MS)" in extra_body
    assert "loadHotModelSourceContext" not in source
    assert "buildHotDecisionRows" not in source
    assert '"2026-06-16"' not in source
    assert "loadMemoryModelSourceContext" in list_body
    assert "loadAmbushModelSourceContext" in list_body
    assert "SHENCE_FRONTEND_BACKEND_TIMEOUT_SECONDS" in proxy_source
    assert "SHENCE_FRONTEND_HOT_MODEL_LIST_TIMEOUT_SECONDS" in proxy_source
    assert "SHENCE_FRONTEND_TBOARD_COMPACT_TIMEOUT_SECONDS" in proxy_source
    assert '"6.0"' in proxy_source
    assert '"30.0"' in proxy_source


def test_async_page_loads_do_not_overwrite_new_route() -> None:
    source = _source()
    login_body = source.split("function bindLogin()", 1)[1].split("async function loadSession", 1)[0]
    render_app_body = source.split("function renderApp()", 1)[1].split("function renderSidebar", 1)[0]
    refresh_body = source.split("function scheduleTBoardAutoRefresh", 1)[1].split("async function renderPage", 1)[0]
    candidate_body = source.split("async function loadCandidateSourceData", 1)[1].split("function buildCandidateRowsFromSource", 1)[0]
    model_body = source.split("async function renderModelPage", 1)[1].split("function collectModelLoadErrors", 1)[0]

    assert 'if (!location.hash) {' in login_body
    assert 'location.hash = "#/candidates";' in login_body
    assert "return;" in login_body.split('location.hash = "#/candidates";', 1)[1].split("renderApp();", 1)[0]
    assert "state.pageEpoch = (state.pageEpoch || 0) + 1" in render_app_body
    assert "clearTBoardAutoRefresh();" in render_app_body
    assert "function clearTBoardAutoRefresh()" in source
    assert 'routeKey !== "model-tboard" || !state.user || isStalePage(pageEpoch, routeKey)' in refresh_body
    assert "document.hidden" in refresh_body
    assert 'renderModelPage(MODEL_PROFILES["model-tboard"], { pageEpoch: state.pageEpoch, routeKey: "model-tboard", silentRefresh: true })' in refresh_body
    assert 'api("/api/model-list/tboard?limit=100"' in source
    assert "isStalePage(pageEpoch, routeKey)" in source
    assert "renderPage(pageEpoch, routeKey)" in render_app_body
    assert "if (isStalePage(pageEpoch, routeKey)) return;" in candidate_body
    assert "if (state.candidateSource.loaded) renderCandidatePage({ pageEpoch, routeKey });" in candidate_body
    assert "root.innerHTML = renderCandidateDraftWorkbench(buildCandidateDraftContext());" in source
    assert "bindCandidateActions();" in source.split("function renderCandidateLoading", 1)[1].split("async function renderCandidatePage", 1)[0]
    assert "if (state.candidateSource.loaded) {" in candidate_body
    assert "if (!isStalePage(pageEpoch, routeKey)) renderCandidatePage({ pageEpoch, routeKey })" in candidate_body
    assert "const pageEpoch = options.pageEpoch ?? state.pageEpoch" in model_body
    assert "const routeKey = options.routeKey ?? Object.entries(MODEL_PROFILES)" in model_body
    assert "hasCachedRows" in model_body
    assert "isSilentRefresh" in model_body
    assert "hasCachedRows && !isSilentRefresh" in model_body
    assert "patchModelPageContent(profile" in model_body
    assert "patchModelPageFromState" in refresh_body
    assert "modelReviewRefreshState" in model_body
    assert "renderModelRefreshStatus(refreshState)" in model_body
    assert model_body.count("if (isStalePage(pageEpoch, routeKey)) return;") >= 4
    assert 'if (profile.key === "tboard") scheduleTBoardAutoRefresh(pageEpoch, routeKey);' in model_body


def test_model_lists_replicate_old_decision_review_columns_with_current_facts() -> None:
    source = _source()
    css = APP_CSS.read_text(encoding="utf-8")
    render_body = source.split("async function renderModelPage", 1)[1].split("function renderModelKpi", 1)[0]
    header_body = source.split("function renderModelHeaderCell", 1)[1].split("function renderModelCell", 1)[0]

    for token in [
        "MODEL_LIST_COLUMNS",
        "MODEL_LIST_COLUMN_WIDTHS",
        "renderModelListColGroup",
        "modelListColumnKind",
        "renderModelHeaderCell",
        "buildHotModelListRows",
        "buildMemoryDecisionRows",
        "buildAmbushDecisionRows",
        "entry_opportunity_status",
        "reference_entry_price",
        "return_from_entry_pct",
        "mae_pct",
        "verification_status",
        "risk_summary",
        "source_gap:model_score_not_materialized",
        "source_gap:buy_point_not_materialized",
        "source_gap:reference_entry_price_not_materialized",
        "source_gap:outcome_not_materialized",
        "repositoryCountLabel",
        "stockNameLabel",
        "observation_board",
        "current_conclusion",
        "next_observation",
        "day2_trigger_time",
    ]:
        assert token in source

    assert "只看已落库的热点模型结果" in source
    assert "缺概率、缺买点或未过闸门时直接显示缺口" in source
    assert "复刻旧版历史二波决策回顾 12 列" in source
    assert "复刻旧版潜伏抬头决策回顾 12 列" in source
    assert "T 字接力观察台" in source
    assert "只看 Day1 通过对象" in source
    assert "按模型分从高到低排" in source
    assert "已停止的行直接写明原因" in source
    assert "Day2 每 5 分钟刷新" in source
    assert "首日合格对象；次日每 5 分钟观察；停止原因逐行展示。" in source
    assert '["model_score", "模型分"]' in source
    assert '["day2_trigger_time", "监测时间"]' in source
    assert '["current_conclusion", "当前判断"]' in source
    assert '["key_reason", "关键依据"]' in source
    assert '["risk_tip", "风险结论"]' in source
    assert '["current_stage", "观察阶段"]' not in source
    assert '["day3_trade_date", "Day3"]' not in source
    assert '["next_observation", "下一步"]' not in source
    assert "页面展示当前结论、观察阶段、下一步和风险提示" not in source
    assert "当前没有进入接力观察的股票。" in source
    assert '["second_wave_trigger_code", "触发证据"]' in source
    assert '["selection_summary", "入选天数"]' in source
    assert 'placeholder: "输入代码"' in source
    assert "tBoardDataNoticeText" not in source
    assert '["data_notice", "数据提示"]' not in source
    assert "data_notice: tBoardDataNoticeText(item)" not in source
    assert "data_notice: 172" not in source
    assert "model-iteration-cell-key--data_notice" not in css
    assert "model-decision-list-page" in render_body
    assert "decision-review-sticky-stack" in render_body
    assert "renderModelListStickyHeader(profile)" in render_body
    assert "bindModelListChrome" in render_body
    assert 'const isModelRoute = Boolean(MODEL_PROFILES[state.route])' in source
    assert '${isModelRoute ? "" : renderHeader(route)}' in source
    assert "model-iteration-row" in source
    assert "stock-finance-name" in source
    assert "model-iteration-cell" in source
    assert "model-iteration-cell--kind-${escapeClass(modelListColumnKind(key))}" in source
    assert "model-iteration-header--kind-" in source
    assert "model-iteration-col--kind-" in source
    assert "modelListCellTone" in source
    assert "decision-review-sticky-table-wrap" in source
    assert "model-iteration-table__native-head" in source
    assert "resetHorizontalScroll" in source
    assert "requestAnimationFrame(resetHorizontalScroll)" in source
    assert 'data-model-table-body="true"' in source
    assert 'data-model-refresh-status="true"' in source
    assert 'data-model-page-lead="true"' in source
    assert 'data-model-day1-summary="true"' in source
    assert 'data-model-load-notice="true"' in source
    assert 'data-model-filter-count="rows"' in source
    assert "renderModelListTableRows(profile, visibleRows)" in source
    assert "body.innerHTML = renderModelListTableRows(profile, visibleRows)" in source
    assert "renderModelListPageLead(profile)" in render_body
    assert "clearModelListChrome" in source
    assert "state.modelListChromeCleanup" in source
    assert "modelScoreSortValue" in source
    assert "model_score: item.model_score" in source
    assert "score_state: item.score_state" in source
    assert "modelScoreSortValue(b) - modelScoreSortValue(a)" in source
    assert "renderModelReviewFilters(profile, listRows.length, visibleRows.length)" in render_body
    assert "const visibleRows = applyModelReviewFilters(profile, listRows)" in render_body
    assert "renderModelListTable(profile, visibleRows)" in render_body
    assert "state.modelReviewRows" in source
    assert "restoreModelFilterFocus" in source
    assert "const compactGap = 2" in source
    assert "height + compactGap - pageTop" in source
    assert "title=" not in header_body
    assert "MODEL_COLUMN_HINTS" not in header_body
    assert "position: fixed;" in css
    assert "top: 0;" in css
    assert "left: 282px;" in css
    assert "right: 24px;" in css
    assert "z-index: 28;" in css
    assert "font-size: 13px;" in css
    assert "font-weight: 950;" in css
    assert "font-weight: 650;" in css
    assert "font-size: 15px;" in css
    assert "font-size: 14px;" in css
    assert "decision-review-filter-line--primary" in source
    assert "filter-row decision-review-filter-row" in source
    assert ".model-decision-list-page .decision-review-filter-row" in css
    assert ".model-list-page-lead" in css
    assert ".model-decision-list-page .model-column-help__label" in css
    assert "linear-gradient(180deg, #f5f9ff 0%, #edf4ff 100%)" in css
    assert "height: 34px;" in css
    assert "min-height: 28px;" in css
    assert "gap: 5px;" in css
    assert "white-space: nowrap;" in css
    assert "font-variant-numeric: tabular-nums;" in css
    assert ".model-iteration-cell--kind-stock" in css
    assert ".model-iteration-cell--data-gap" in css
    assert ".model-iteration-cell--risk" in css
    assert ".model-iteration-table--tboard .model-iteration-cell-key--current_conclusion .model-status-text" in css
    assert ".model-refresh-status--empty" in css
    assert ".tboard-day1-summary--empty" in css
    assert "flex-wrap: wrap;" in css
    assert ".tboard-day1-summary small" in css
    assert "-webkit-overflow-scrolling: touch;" in css
    assert ".model-decision-list-page--tboard .decision-review-sticky-table-wrap" in css
    assert "content: attr(data-label);" in css
    assert "grid-template-columns: 82px minmax(0, 1fr);" in css
    assert "position: absolute;" in css
    assert "overflow-wrap: break-word;" in css
    for hidden_block in [
        "renderModelComparisonPlan",
        "renderModelDecisionBrief",
        "renderModelSummary",
        "raw-evidence-details",
        "renderAmbushValleyLibraryPlan",
        "page-header",
        "model-iteration-contract-note",
        "model-iteration-summary",
        "ambush-library-plan",
    ]:
        assert hidden_block not in render_body


def test_ambush_list_excludes_labeling_controls_until_research_center() -> None:
    source = _source()
    render_model_body = source.split("async function renderModelPage", 1)[1].split(
        "async function loadAmbushValleyResearchData", 1
    )[0]
    research_body = source.split("async function loadAmbushValleyResearchData", 1)[1]

    for forbidden in [
        "ai_stock_ambush_label_drafts_v1",
        "AMBUSH_LABEL_OPTIONS",
        "AMBUSH_LABEL_CONFIDENCE_OPTIONS",
        "renderAmbushValleyLibraryPlan",
        "data-ambush-label-field",
        "本地人工标注草稿",
        "manual_label_status",
        "label_confidence",
        "label_key",
    ]:
        assert forbidden not in render_model_body

    assert "前复权日线" in source
    assert "source_gap:ambush_label_repository_missing" in source
    assert "研究中心-低谷图库" in source
    assert "模型列表不放人工打标控件" in source
    assert "低谷图形标注中心" in research_body
    assert "research_structure_judgement" in source
    assert "research_turn_timing" in source
    assert "research_sample_role" in source
    assert "research_label_confidence" in source
    assert "manual_label_confidence" in research_body


def test_tboard_terminal_rows_use_plain_user_semantics() -> None:
    source = _source()
    tboard_body = source.split("function buildTBoardListRows", 1)[1].split("function modelListDescription", 1)[0]
    render_cell_body = source.split("function renderModelCell", 1)[1].split("function modelListCellClass", 1)[0]

    assert "function tBoardRelayStrengthText" in source
    assert "function tBoardConclusionText" in source
    assert "function tBoardKeyReasonText" in source
    assert "function tBoardRiskText" in source
    assert "function tBoardUpdateText" in source
    assert "relay_strength_label: tBoardRelayStrengthText(item)" in tboard_body
    assert "current_conclusion: tBoardConclusionText(item)" in tboard_body
    assert "key_reason: tBoardKeyReasonText(item)" in tboard_body
    assert "risk_tip: tBoardRiskText(item)" in tboard_body
    assert "const latestDataFetchAt = item.latest_data_fetch_at || item.last_data_captured_at || null;" in tboard_body
    assert "const lastModelOutputAt = item.last_model_output_at || item.model_evaluated_at || null;" in tboard_body
    assert "const projectionSnapshotAt = item.latest_projection_snapshot_at || null;" in tboard_body
    assert "latest_snapshot_time: tBoardUpdateText(lastModelOutputAt, latestDataFetchAt)" in tboard_body
    assert "latest_data_fetch_at: latestDataFetchAt" in tboard_body
    assert "last_data_captured_at: item.last_data_captured_at || null" in tboard_body
    assert "last_model_output_at: lastModelOutputAt" in tboard_body
    assert "model_evaluated_at: item.model_evaluated_at || null" in tboard_body
    assert 'if (status === "data_wait") return "暂不观察";' in source
    assert 'if (status === "data_wait") return "数据缺口";' in source
    assert 'if (status === "data_wait") return "等待确认";' not in source
    assert 'if (status === "data_wait") return "待确认";' not in source
    assert "封板失败" in source
    assert "卖压占优" in source
    assert "未触发" in source
    assert "5 分钟监测未接近涨停" in source
    assert "接近涨停，买盘扫掉卖盘" in source
    assert "接近涨停，卖盘往下砸" in source
    assert "卖盘往下砸，买入确认失败" in source
    assert "封板没守住，次日退出风险高" in source
    assert "按模型分从高到低排" in source
    assert "TBOARD_STOPPED_DEFAULT_VISIBLE_DAYS = 3" in source
    assert "function tBoardIsStaleStopped" in source
    assert ".filter((item) => !tBoardIsStaleStopped(item))" in source
    assert "model-score-pair" in render_cell_body
    assert "可买入观察" not in source
    assert "接力机会提示仅作观察" not in source
    assert "不自动下单" not in source
    assert "不代表买入建议" not in source


def test_readyz_exposes_locked_frontend_pages() -> None:
    response = TestClient(app).get("/readyz")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["locked_backend_mode"] is True
    assert body["open_pages"] == [
        "candidates",
        "model-hot",
        "model-memory",
        "model-ambush",
        "model-tboard",
        "research-ambush-valley",
    ]


def test_auth_session_and_login_flow() -> None:
    client = TestClient(app)

    assert client.get("/api/auth/session").json() == {"authenticated": False, "user": None}
    bad = client.post("/api/auth/login", json={"username": "admin", "password": "bad"})
    assert bad.status_code == 401
    ok = client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    assert ok.status_code == 200
    assert ok.json()["authenticated"] is True
    assert client.get("/api/auth/session").json()["authenticated"] is True
    assert client.post("/api/auth/logout", json={}).status_code == 200


def test_frontend_script_has_no_duplicate_status_tone_declaration() -> None:
    source = _source()

    assert source.count("function statusTone(") == 1
    assert "function ambushCaseStatusTone(" in source


def test_backend_proxy_is_auth_required_and_read_only() -> None:
    client = TestClient(app)
    proxy_source = (SERVICE_ROOT / "src" / "shence_frontend_service" / "main.py").read_text(encoding="utf-8")

    assert client.get("/api/backend/source/readyz").status_code == 401
    assert client.get("/api/model-list/hot").status_code == 401
    assert client.get("/api/model-list/tboard").status_code == 401
    assert client.get("/api/research/research/ambush/taxonomy").status_code == 401
    assert client.get("/api/source/ths/paid-probability/cookie/status").status_code == 401
    client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    assert client.post("/api/backend/source/readyz", json={}).status_code == 405
    assert client.post("/api/source/ths/paid-probability/cookie/status", json={}).status_code == 405
    assert 'RESEARCH_METHODS = {"GET", "HEAD", "OPTIONS", "POST"}' in proxy_source
    assert 'SOURCE_THS_PAID_METHODS = {"GET", "POST", "PUT"}' in proxy_source
    assert '("PUT", "cookie")' in proxy_source
    assert 'key.lower() != "cookie"' in proxy_source


def test_proxy_raw_headers_preserve_multiple_set_cookie_values() -> None:
    import httpx

    from shence_frontend_service.main import _response_raw_headers

    response = httpx.Response(
        200,
        headers=[
            ("set-cookie", "ai_stock_session=one; Path=/; HttpOnly; SameSite=lax"),
            ("set-cookie", "csrf_token=two; Path=/; SameSite=lax"),
            ("content-type", "application/json"),
            ("content-length", "128"),
            ("connection", "keep-alive"),
            ("cache-control", "no-store"),
        ],
        content=b"{}",
    )

    raw_headers = _response_raw_headers(response)

    assert [
        value
        for key, value in raw_headers
        if key.lower() == b"set-cookie"
    ] == [
        b"ai_stock_session=one; Path=/; HttpOnly; SameSite=lax",
        b"csrf_token=two; Path=/; SameSite=lax",
    ]
    assert (b"content-type", b"application/json; charset=utf-8") in raw_headers
    assert all(key.lower() != b"content-length" for key, _ in raw_headers)
    assert all(key.lower() != b"connection" for key, _ in raw_headers)
