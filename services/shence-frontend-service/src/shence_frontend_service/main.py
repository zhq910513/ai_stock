from __future__ import annotations

import asyncio
import json
import os
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

SERVICE_NAME = "shence-frontend-service"

app = FastAPI(title="ai_stock shence-frontend-service")

PUBLIC_DIR = Path(__file__).resolve().parents[2] / "public"
SESSION_COOKIE = "ai_stock_frontend_session"
SESSION_VALUE = "local-dev-session"

HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}
UPSTREAM_ENTITY_HEADERS_TO_REBUILD = {"content-encoding", "content-length"}
READ_ONLY_METHODS = {"GET", "HEAD", "OPTIONS"}
RESEARCH_METHODS = {"GET", "HEAD", "OPTIONS", "POST"}
SOURCE_THS_PAID_METHODS = {"GET", "POST", "PUT"}
SOURCE_THS_PAID_ALLOWED_PATHS = {
    ("GET", "cookie/status"),
    ("PUT", "cookie"),
    ("POST", "probe"),
    ("POST", "fetch-current-batch"),
    ("GET", "batch-status"),
    ("POST", "deadline-check"),
}
TBOARD_AUDIT_PAYLOAD_FIELDS = {
    "request_payload",
    "result_payload",
    "game_hypothesis_payload",
    "evidence_json",
    "related_payload",
}
TBOARD_COMPACT_PATHS = {
    "repository": "t-board-relay/repository/status",
    "observation_board": "t-board-relay/observation-board",
}
TBOARD_DAY1_SUMMARY_LIMIT = 500
TBOARD_STOPPED_DEFAULT_VISIBLE_DAYS = 3
TBOARD_MARKET_TIMEZONE = ZoneInfo("Asia/Shanghai")


def _backend_proxy_timeout_seconds() -> float:
    return float(os.getenv("SHENCE_FRONTEND_BACKEND_TIMEOUT_SECONDS", "6.0"))


def _source_preflight_timeout_seconds() -> float:
    return float(os.getenv("SHENCE_FRONTEND_PREFLIGHT_TIMEOUT_SECONDS", "6.0"))


def _tboard_compact_timeout_seconds() -> float:
    return float(os.getenv("SHENCE_FRONTEND_TBOARD_COMPACT_TIMEOUT_SECONDS", "30.0"))


def _hot_model_list_timeout_seconds() -> float:
    return float(os.getenv("SHENCE_FRONTEND_HOT_MODEL_LIST_TIMEOUT_SECONDS", "30.0"))


def _frontend_user() -> dict[str, str]:
    return {
        "username": os.getenv("SHENCE_FRONTEND_USERNAME", "admin"),
        "role": os.getenv("SHENCE_FRONTEND_ROLE", "operator"),
    }


def _expected_password() -> str:
    return os.getenv("SHENCE_FRONTEND_PASSWORD", "admin")


def _is_authenticated(request: Request) -> bool:
    return request.cookies.get(SESSION_COOKIE) == SESSION_VALUE


def _backend_base_urls() -> dict[str, str]:
    return {
        "source": os.getenv("SOURCE_DATA_SERVICE_BASE_URL", "http://127.0.0.1:8041").rstrip("/"),
        "scheduler": os.getenv("SCHEDULER_SERVICE_BASE_URL", "http://127.0.0.1:8023").rstrip("/"),
        "data-inspector": os.getenv("DATA_INSPECTOR_SERVICE_BASE_URL", "http://127.0.0.1:8025").rstrip("/"),
        "hot": os.getenv("HOT_CANDIDATES_SERVICE_BASE_URL", "http://127.0.0.1:8031").rstrip("/"),
        "memory": os.getenv("CANDIDATE_MEMORY_SERVICE_BASE_URL", "http://127.0.0.1:8032").rstrip("/"),
        "ambush": os.getenv("AMBUSH_WATCHLIST_SERVICE_BASE_URL", "http://127.0.0.1:8033").rstrip("/"),
        "tboard": os.getenv("T_BOARD_RELAY_SERVICE_BASE_URL", "http://127.0.0.1:8035").rstrip("/"),
        "research-service": os.getenv("RESEARCH_SERVICE_BASE_URL", "http://127.0.0.1:8029").rstrip("/"),
        "research": os.getenv("RESEARCH_CENTER_SERVICE_BASE_URL", "http://127.0.0.1:8028").rstrip("/"),
    }


def _backend_base_url_candidates() -> dict[str, list[str]]:
    docker_defaults = {
        "source": "http://source-data-service:8041",
        "scheduler": "http://scheduler-service:8023",
        "data-inspector": "http://data-inspector-service:8025",
        "hot": "http://hot-candidates-service:8031",
        "memory": "http://candidate-memory-service:8032",
        "ambush": "http://ambush-watchlist-service:8033",
        "tboard": "http://t-board-relay-service:8034",
        "research-service": "http://research-service:8029",
        "research": "http://research-center-service:8028",
    }
    candidates: dict[str, list[str]] = {}
    for service, primary in _backend_base_urls().items():
        urls = [primary]
        docker_url = docker_defaults.get(service)
        if docker_url and docker_url.rstrip("/") not in urls:
            urls.append(docker_url.rstrip("/"))
        candidates[service] = urls
    return candidates


def _response_raw_headers(upstream: httpx.Response) -> list[tuple[bytes, bytes]]:
    raw_headers: list[tuple[bytes, bytes]] = []
    content_type = upstream.headers.get("content-type", "")
    rebuild_json_content_type = content_type.startswith("application/json") and "charset" not in content_type.lower()
    for key, value in upstream.headers.raw:
        lower_key = key.decode("latin-1").lower()
        if lower_key in HOP_BY_HOP_HEADERS or lower_key in UPSTREAM_ENTITY_HEADERS_TO_REBUILD:
            continue
        if rebuild_json_content_type and lower_key == "content-type":
            continue
        raw_headers.append((key, value))
    if rebuild_json_content_type:
        raw_headers.append((b"content-type", b"application/json; charset=utf-8"))
    return raw_headers


def _tboard_market_today() -> date:
    return datetime.now(TBOARD_MARKET_TIMEZONE).date()


def _date_key(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(TBOARD_MARKET_TIMEZONE).date() if value.tzinfo else value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if len(text) < 10:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _tboard_terminal_date(item: dict[str, Any]) -> date | None:
    for field in ("day3_trade_date", "day2_trade_date", "day1_trade_date", "latest_snapshot_time", "updated_at"):
        parsed = _date_key(item.get(field))
        if parsed:
            return parsed
    return None


def _tboard_is_stale_stopped(item: Any, *, today: date | None = None) -> bool:
    if not isinstance(item, dict):
        return False
    if str(item.get("observation_status") or "").lower() != "stopped":
        return False
    terminal_date = _tboard_terminal_date(item)
    if terminal_date is None:
        return False
    age_days = (_tboard_market_today() if today is None else today) - terminal_date
    return age_days.days > TBOARD_STOPPED_DEFAULT_VISIBLE_DAYS


def _compact_tboard_repository_view(body: Any, *, include_stale_stopped: bool = False) -> Any:
    if not isinstance(body, dict):
        return body
    compact = dict(body)
    items = compact.get("items")
    if isinstance(items, list):
        compact["items"] = [
            {key: value for key, value in item.items() if key not in TBOARD_AUDIT_PAYLOAD_FIELDS}
            if isinstance(item, dict)
            else item
            for item in items
            if include_stale_stopped or not _tboard_is_stale_stopped(item)
        ]
    return compact


def _tboard_time_order_key(value: Any) -> tuple[int, float, str]:
    text = str(value or "").strip()
    if not text:
        return (0, 0.0, "")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return (1, parsed.timestamp(), text)
    except ValueError:
        return (0, 0.0, text)


def _latest_tboard_observation_time(items: list[Any], fields: tuple[str, ...]) -> str | None:
    best_value: str | None = None
    best_key: tuple[int, float, str] = (0, 0.0, "")
    for item in items:
        if not isinstance(item, dict):
            continue
        for field in fields:
            value = str(item.get(field) or "").strip()
            if not value:
                continue
            key = _tboard_time_order_key(value)
            if best_value is None or key > best_key:
                best_value = value
                best_key = key
    return best_value


def _tboard_observation_time_summary(observation_board: Any) -> dict[str, str | None]:
    items = _response_items(observation_board)
    return {
        "latest_data_fetch_at": _latest_tboard_observation_time(items, ("latest_data_fetch_at", "last_data_captured_at")),
        "last_model_output_at": _latest_tboard_observation_time(items, ("last_model_output_at", "model_evaluated_at")),
        "latest_projection_snapshot_at": _latest_tboard_observation_time(items, ("latest_projection_snapshot_at",)),
    }


def _compact_hot_model_list_view(body: Any) -> Any:
    if not isinstance(body, dict):
        return body
    compact = dict(body)
    items = compact.get("items")
    if isinstance(items, list):
        compact["items"] = [
            {key: value for key, value in item.items() if key not in TBOARD_AUDIT_PAYLOAD_FIELDS}
            if isinstance(item, dict)
            else item
            for item in items
        ]
    return compact


def _response_items(body: Any) -> list[Any]:
    if not isinstance(body, dict):
        return []
    items = body.get("items")
    if isinstance(items, list):
        return items
    data = body.get("data")
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return data["items"]
    return []


def _decimal_equal(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return False
    try:
        return Decimal(str(left)) == Decimal(str(right))
    except (InvalidOperation, ValueError):
        return str(left).strip() == str(right).strip()


def _tboard_open_on_limit(item: dict[str, Any]) -> bool:
    payload = item.get("result_payload") if isinstance(item.get("result_payload"), dict) else {}
    explicit = payload.get("open_on_limit_flag")
    if isinstance(explicit, bool):
        return explicit
    if explicit is not None:
        return str(explicit).strip().lower() in {"1", "true", "yes"}
    return _decimal_equal(payload.get("open_price"), payload.get("up_limit_price"))


def _tboard_reason_label(reason: Any) -> str:
    labels = {
        "not_t_board": "未满足严格 T 字板",
        "float_market_cap_out_of_range": "流通市值不在 50 亿到 300 亿",
        "float_market_cap_missing": "流通市值暂未读到",
        "data_blocked": "关键事实暂未补齐",
    }
    key = str(reason or "").strip()
    return labels.get(key, "其他未通过原因" if key else "未写明原因")


def _tboard_day1_candidate_stock_key(item: dict[str, Any]) -> str | None:
    payloads = [
        item,
        item.get("stock") if isinstance(item.get("stock"), dict) else {},
        item.get("result_payload") if isinstance(item.get("result_payload"), dict) else {},
        item.get("request_payload") if isinstance(item.get("request_payload"), dict) else {},
    ]
    for payload in payloads:
        for field in ("canonical_symbol", "symbol", "stock_code", "instrument_id"):
            value = str(payload.get(field) or "").strip()
            if value:
                return value.upper()
        nested_stock = payload.get("stock")
        if isinstance(nested_stock, dict):
            value = str(nested_stock.get("symbol") or nested_stock.get("canonical_symbol") or "").strip()
            if value:
                return value.upper()
    return None


def _tboard_day1_candidate_updated_key(item: dict[str, Any], index: int) -> tuple[str, int]:
    for field in ("updated_at", "created_at", "as_of_time_utc"):
        value = str(item.get(field) or "").strip()
        if value:
            return (value, index)
    return ("", index)


def _dedupe_tboard_day1_latest_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest_by_stock: dict[str, tuple[tuple[str, int], dict[str, Any]]] = {}
    for index, item in enumerate(items):
        stock_key = _tboard_day1_candidate_stock_key(item) or f"__row__:{index}"
        updated_key = _tboard_day1_candidate_updated_key(item, index)
        current = latest_by_stock.get(stock_key)
        if current is None or updated_key >= current[0]:
            latest_by_stock[stock_key] = (updated_key, item)
    return [entry[1] for entry in latest_by_stock.values()]


def _compact_tboard_day1_scan_summary(body: Any, observation_board: Any | None = None) -> dict[str, Any]:
    items = [item for item in _response_items(body) if isinstance(item, dict)]
    trade_dates = sorted({str(item.get("trade_date") or "").strip() for item in items if item.get("trade_date")})
    latest_trade_date = trade_dates[-1] if trade_dates else None
    latest_rows = [item for item in items if str(item.get("trade_date") or "").strip() == latest_trade_date] if latest_trade_date else []
    latest_items = _dedupe_tboard_day1_latest_items(latest_rows)
    scanned_count = len(latest_items)
    qualified_count = sum(1 for item in latest_items if item.get("candidate_status") == "qualified")
    rejected_count = sum(1 for item in latest_items if item.get("candidate_status") == "rejected")
    data_blocked_count = sum(1 for item in latest_items if item.get("candidate_status") == "data_blocked")
    open_on_limit_count = sum(1 for item in latest_items if _tboard_open_on_limit(item))
    reason_counter: dict[str, int] = {}
    for item in latest_items:
        if item.get("candidate_status") != "rejected":
            continue
        reason = str(item.get("reject_reason") or "unknown").strip() or "unknown"
        reason_counter[reason] = reason_counter.get(reason, 0) + 1
    reason_counts = [
        {"reason": reason, "label": _tboard_reason_label(reason), "count": count}
        for reason, count in sorted(reason_counter.items(), key=lambda entry: (-entry[1], entry[0]))
    ]
    top_reason = reason_counts[0]["reason"] if reason_counts else None
    if scanned_count == 0:
        main_reason = "暂未读到今日 Day1 扫描结果"
        summary_text = "今日 Day1 扫描结论暂时不可读。"
    elif qualified_count > 0:
        main_reason = f"{qualified_count} 只通过严格 Day1 条件，已进入观察列表"
        summary_text = f"今日已扫描 {scanned_count} 只 Day1 候选，严格 Day1 合格 {qualified_count} 只；已进入观察列表。"
    else:
        if top_reason == "not_t_board" and open_on_limit_count == 0:
            main_reason = "没有开盘即涨停，不满足模型四 Day1 T 字板条件"
        elif top_reason == "not_t_board":
            main_reason = "开盘、盘中开板、收盘回封结构未同时满足严格 T 字板条件"
        elif data_blocked_count > 0 and data_blocked_count >= rejected_count:
            main_reason = "关键事实暂未补齐，暂不能判断 Day1 是否合格"
        elif top_reason:
            main_reason = _tboard_reason_label(top_reason)
        else:
            main_reason = "未满足模型四 Day1 入选条件"
        summary_text = f"今日已扫描 {scanned_count} 只 Day1 候选，严格 Day1 合格 0 只；主要原因：{main_reason}。"
    updated_values = [
        str(item.get("updated_at") or item.get("created_at") or "").strip()
        for item in latest_items
        if item.get("updated_at") or item.get("created_at")
    ]
    observation_times = _tboard_observation_time_summary(observation_board)
    return {
        "ok": True,
        "data": {
            "trade_date": latest_trade_date,
            "scanned_count": scanned_count,
            "qualified_count": qualified_count,
            "rejected_count": rejected_count,
            "data_blocked_count": data_blocked_count,
            "open_on_limit_count": open_on_limit_count,
            "main_reason": main_reason,
            "summary_text": summary_text,
            "reason_counts": reason_counts[:5],
            "updated_at": max(updated_values) if updated_values else None,
            **observation_times,
        },
    }


async def _fetch_backend_json(
    client: httpx.AsyncClient,
    *,
    service: str,
    path: str,
    headers: dict[str, str],
) -> Any:
    base_urls = _backend_base_url_candidates().get(service)
    if not base_urls:
        raise HTTPException(status_code=404, detail=f"unknown backend service: {service}")
    last_error: str | None = None
    for base_url in base_urls:
        target_url = f"{base_url}/{path}"
        try:
            response = await client.get(target_url, headers=headers)
        except httpx.RequestError as exc:
            last_error = str(exc)
            continue
        if response.status_code >= 400:
            last_error = f"upstream status {response.status_code}"
            continue
        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=502, detail="后端只读服务返回内容暂时无法识别") from exc
    raise HTTPException(status_code=502, detail=f"后端只读服务暂时不可读：{service}; {last_error or 'no route'}")


def _read_only_headers(request: Request) -> dict[str, str]:
    return {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS and key.lower() != "cookie"
    }


@app.middleware("http")
async def no_store_frontend_assets(request: Request, call_next):
    response = await call_next(request)
    if request.url.path in {"/", "/index.html", "/app.js", "/app.css"}:
        response.headers["Cache-Control"] = "no-store, max-age=0"
    return response


@app.get("/healthz")
def health() -> dict[str, str]:
    return {"status": "ok", "service": SERVICE_NAME}


@app.get("/readyz")
def ready() -> dict[str, Any]:
    return {
        "status": "ready",
        "service": SERVICE_NAME,
        "open_pages": [
            "candidates",
            "model-hot",
            "model-memory",
            "model-ambush",
            "model-tboard",
            "research-ambush-valley",
        ],
        "locked_backend_mode": True,
    }


@app.post("/api/auth/login")
async def login(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid json payload") from exc
    username = str(payload.get("username") or "").strip()
    password = str(payload.get("password") or "")
    expected_user = _frontend_user()["username"]
    if username != expected_user or password != _expected_password():
        raise HTTPException(status_code=401, detail="invalid credentials")
    response = JSONResponse({"authenticated": True, "user": _frontend_user()})
    response.set_cookie(SESSION_COOKIE, SESSION_VALUE, httponly=True, samesite="lax")
    return response


@app.get("/api/auth/session")
def session(request: Request) -> dict[str, Any]:
    authenticated = _is_authenticated(request)
    return {"authenticated": authenticated, "user": _frontend_user() if authenticated else None}


@app.post("/api/auth/logout")
def logout() -> JSONResponse:
    response = JSONResponse({"authenticated": False})
    response.delete_cookie(SESSION_COOKIE)
    return response


@app.api_route("/api/backend/{service}/{path:path}", methods=["GET", "HEAD", "OPTIONS"])
async def proxy_backend(service: str, path: str, request: Request) -> StreamingResponse:
    if not _is_authenticated(request):
        raise HTTPException(status_code=401, detail="login required")
    if request.method not in READ_ONLY_METHODS:
        raise HTTPException(status_code=405, detail="locked backend proxy is read-only")
    base_urls = _backend_base_url_candidates().get(service)
    if not base_urls:
        raise HTTPException(status_code=404, detail=f"unknown backend service: {service}")
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS and key.lower() != "cookie"
    }
    last_error: str | None = None
    for base_url in base_urls:
        target_url = f"{base_url}/{path}"
        if request.url.query:
            target_url = f"{target_url}?{request.url.query}"
        client = httpx.AsyncClient(timeout=_backend_proxy_timeout_seconds(), follow_redirects=False)
        upstream_request = client.build_request(request.method, target_url, headers=headers)
        try:
            upstream = await client.send(upstream_request, stream=True)
        except httpx.RequestError as exc:
            last_error = str(exc)
            await client.aclose()
            continue
        response_headers = _response_raw_headers(upstream)

        async def iter_body():
            try:
                async for chunk in upstream.aiter_bytes():
                    yield chunk
            finally:
                await upstream.aclose()
                await client.aclose()

        response = StreamingResponse(iter_body(), status_code=upstream.status_code, media_type=None)
        response.raw_headers = response_headers
        return response
    raise HTTPException(status_code=502, detail=f"后端只读服务暂时不可读：{service}; {last_error or 'no route'}")


@app.get("/api/model-list/tboard")
async def tboard_model_list(
    request: Request,
    limit: int = Query(default=100, ge=1, le=1000),
    include_stale_stopped: bool = Query(default=False),
) -> dict[str, Any]:
    if not _is_authenticated(request):
        raise HTTPException(status_code=401, detail="login required")
    headers = _read_only_headers(request)
    timeout = _tboard_compact_timeout_seconds()
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        tasks = []
        keys = []
        for key, base_path in TBOARD_COMPACT_PATHS.items():
            keys.append(key)
            separator = "&" if "?" in base_path else "?"
            path = base_path if key == "repository" else f"{base_path}{separator}limit={limit}"
            tasks.append(_fetch_backend_json(client, service="tboard", path=path, headers=headers))
        keys.append("day1_candidates")
        tasks.append(
            _fetch_backend_json(
                client,
                service="tboard",
                path=f"t-board-relay/day1/candidates?limit={TBOARD_DAY1_SUMMARY_LIMIT}",
                headers=headers,
            )
        )
        results = await asyncio.gather(*tasks, return_exceptions=True)
    raw_results_by_key = dict(zip(keys, results, strict=True))
    compact_observation_board: Any | None = None
    observation_result = raw_results_by_key.get("observation_board")
    if not isinstance(observation_result, Exception):
        compact_observation_board = _compact_tboard_repository_view(
            observation_result,
            include_stale_stopped=include_stale_stopped,
        )
    payload: dict[str, Any] = {
        "contract_kind": "shence_tboard_model_list_compact_v1",
        "read_only": True,
        "compact_audit_payloads": True,
    }
    for key, result in zip(keys, results, strict=True):
        if key == "day1_candidates":
            payload["day1_scan_summary"] = (
                {"ok": False, "error": "今日 Day1 扫描结论暂时不可读"}
                if isinstance(result, Exception)
                else _compact_tboard_day1_scan_summary(result, compact_observation_board)
            )
            continue
        if isinstance(result, Exception):
            payload[key] = {"ok": False, "error": "模型四阶段事实暂时不可读"}
        else:
            payload[key] = {
                "ok": True,
                "data": compact_observation_board
                if key == "observation_board" and compact_observation_board is not None
                else _compact_tboard_repository_view(result, include_stale_stopped=include_stale_stopped),
            }
    return payload


@app.get("/api/model-list/hot")
async def hot_model_list(request: Request, limit: int = Query(default=100, ge=1, le=1000)) -> dict[str, Any]:
    if not _is_authenticated(request):
        raise HTTPException(status_code=401, detail="login required")
    headers = _read_only_headers(request)
    timeout = _hot_model_list_timeout_seconds()
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        result = await _fetch_backend_json(
            client,
            service="research-service",
            path=f"research/model-list/hot?limit={limit}",
            headers=headers,
        )
    return {
        "contract_kind": "shence_hot_model_list_compact_v1",
        "read_only": True,
        "compact_audit_payloads": True,
        "hot_model": {"ok": True, "data": _compact_hot_model_list_view(result)},
    }


@app.api_route("/api/research/{path:path}", methods=["GET", "HEAD", "OPTIONS", "POST"])
async def proxy_research(path: str, request: Request) -> StreamingResponse:
    if not _is_authenticated(request):
        raise HTTPException(status_code=401, detail="login required")
    if request.method not in RESEARCH_METHODS:
        raise HTTPException(status_code=405, detail="research center proxy only supports controlled read and research asset writes")
    base_urls = _backend_base_url_candidates().get("research") or []
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS and key.lower() != "cookie"
    }
    body = await request.body()
    last_error: str | None = None
    for base_url in base_urls:
        target_url = f"{base_url}/{path}"
        if request.url.query:
            target_url = f"{target_url}?{request.url.query}"
        client = httpx.AsyncClient(timeout=_backend_proxy_timeout_seconds(), follow_redirects=False)
        upstream_request = client.build_request(request.method, target_url, headers=headers, content=body)
        try:
            upstream = await client.send(upstream_request, stream=True)
        except httpx.RequestError as exc:
            last_error = str(exc)
            await client.aclose()
            continue
        response_headers = _response_raw_headers(upstream)

        async def iter_body():
            try:
                async for chunk in upstream.aiter_bytes():
                    yield chunk
            finally:
                await upstream.aclose()
                await client.aclose()

        response = StreamingResponse(iter_body(), status_code=upstream.status_code, media_type=None)
        response.raw_headers = response_headers
        return response
    raise HTTPException(status_code=502, detail=f"研究中心暂时不可读：{last_error or 'no route'}")


@app.api_route("/api/source/ths/paid-probability/{path:path}", methods=["GET", "POST", "PUT"])
async def proxy_source_ths_paid_probability(path: str, request: Request) -> StreamingResponse:
    if not _is_authenticated(request):
        raise HTTPException(status_code=401, detail="login required")
    normalized_path = path.strip("/")
    method = request.method.upper()
    if method not in SOURCE_THS_PAID_METHODS or (method, normalized_path) not in SOURCE_THS_PAID_ALLOWED_PATHS:
        raise HTTPException(status_code=405, detail="source THS paid probability proxy only allows its controlled endpoints")
    base_urls = _backend_base_url_candidates().get("source") or []
    headers = _read_only_headers(request)
    body = await request.body()
    last_error: str | None = None
    for base_url in base_urls:
        target_url = f"{base_url}/source/ths/paid-probability/{normalized_path}"
        if request.url.query:
            target_url = f"{target_url}?{request.url.query}"
        client = httpx.AsyncClient(timeout=_backend_proxy_timeout_seconds(), follow_redirects=False)
        upstream_request = client.build_request(method, target_url, headers=headers, content=body)
        try:
            upstream = await client.send(upstream_request, stream=True)
        except httpx.RequestError as exc:
            last_error = str(exc)
            await client.aclose()
            continue
        response_headers = _response_raw_headers(upstream)

        async def iter_body():
            try:
                async for chunk in upstream.aiter_bytes():
                    yield chunk
            finally:
                await upstream.aclose()
                await client.aclose()

        response = StreamingResponse(iter_body(), status_code=upstream.status_code, media_type=None)
        response.raw_headers = response_headers
        return response
    raise HTTPException(status_code=502, detail=f"同花顺付费概率入口暂时不可读：{last_error or 'no route'}")


@app.post("/api/source/preflight")
async def source_preflight(request: Request) -> dict[str, Any]:
    if not _is_authenticated(request):
        raise HTTPException(status_code=401, detail="login required")
    payload = await request.json()
    allowed_keys = {"model_code", "model_phase", "trade_date", "symbols"}
    forwarded = {key: payload.get(key) for key in allowed_keys if key in payload}
    if not forwarded.get("model_code") or not forwarded.get("model_phase") or not forwarded.get("symbols"):
        raise HTTPException(status_code=400, detail="model_code, model_phase and symbols are required")
    upstream: httpx.Response | None = None
    last_error: str | None = None
    async with httpx.AsyncClient(timeout=_source_preflight_timeout_seconds()) as client:
        for source_url in _backend_base_url_candidates()["source"]:
            try:
                upstream = await client.post(f"{source_url}/source/release/preflight", json=forwarded)
                break
            except httpx.RequestError as exc:
                last_error = str(exc)
                continue
    if upstream is None:
        raise HTTPException(status_code=502, detail=f"数据预检暂时不可读：{last_error or 'no route'}")
    try:
        body = upstream.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail="source preflight returned non-json response") from exc
    if upstream.status_code >= 400:
        raise HTTPException(status_code=upstream.status_code, detail=body)
    return body


@app.get("/api/backend-map")
def backend_map(request: Request) -> dict[str, Any]:
    if not _is_authenticated(request):
        raise HTTPException(status_code=401, detail="login required")
    return {"services": sorted(_backend_base_urls()), "read_only": True}


@app.get("/")
@app.get("/index.html")
def index() -> FileResponse:
    return FileResponse(PUBLIC_DIR / "index.html")


app.mount("/", StaticFiles(directory=PUBLIC_DIR, html=True), name="shence-frontend")


def dumps_compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
